"""Cổng MQTT: adapter aiomqtt cho runtime, adapter in-memory cho unit test.

ADR-004: "Unit tests dùng in-memory adapter nhưng contract tests phải chạy
Mosquitto." Hai lớp dưới đây hiện thực cùng một Protocol để đổi qua lại được.

QoS/retain mặc định của từng topic nằm ở caller — xem docs/mqtt_spec.md bảng
topic. Module này không tự quyết định retain.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]


# Vì sao cần hai hàm dưới đây:
#
# paho-mqtt (lõi của aiomqtt) đăng ký socket qua `add_reader`/`remove_writer`.
# ProactorEventLoop — mặc định của Windows từ Python 3.8 — không hiện thực hai
# hàm đó, nên mọi kết nối MQTT nổ `NotImplementedError`. Trên Linux/macOS loop
# mặc định đã là selector nên cả hai hàm đều là no-op; container không đổi gì.
#
# Có hai cơ chế chọn loop và chúng không thay thế nhau được:
#   - loop_factory: `asyncio.run(...)` và uvicorn dùng cái này. Uvicorn BỎ QUA
#     policy hoàn toàn (xem uvicorn/loops/asyncio.py), nên với backend phải
#     truyền factory — đó là lý do có `src/serve.py`.
#   - policy: pytest-asyncio và mọi thứ tạo loop ngầm thì theo cái này.


def selector_loop_factory() -> Callable[[], asyncio.AbstractEventLoop]:
    """Factory loop hợp với paho-mqtt.

    CẢNH BÁO — **đừng** truyền vào `asyncio.run(loop_factory=...)`: tham số đó chỉ
    tồn tại từ Python 3.12, còn repo chạy 3.11 (`requires-python = ">=3.11"`, cả hai
    workflow CI đều pin `3.11`). Trên 3.11 nó nổ `TypeError` ngay dòng đầu. Đó là bug
    thật ở `src/vehicle_sim/__main__.py` và `scripts/smoke_mqtt.py`, chặn tầng test L3
    và chỉ lộ ra khi ai đó chạy đúng phiên bản Python của CI.

    Muốn selector loop thì dùng `ensure_selector_event_loop()` bên dưới rồi gọi
    `asyncio.run(...)` trần — xem `src/serve.py`. Hàm này hiện **không còn caller nào**;
    giữ lại cho trường hợp cần factory tường minh (uvicorn bỏ qua policy), nhưng chỉ
    dùng được khi repo đã lên sàn 3.12.
    """
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return asyncio.new_event_loop


def ensure_selector_event_loop() -> None:
    """Đặt policy selector, cho những chỗ tạo loop ngầm (pytest-asyncio).

    Không có tác dụng với uvicorn — uvicorn dùng loop_factory riêng.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@dataclass(frozen=True)
class Will:
    """Last Will khai trong gói CONNECT."""

    topic: str
    payload: dict[str, Any]
    qos: int = 1
    retain: bool = True


class MqttPort(Protocol):
    """Bề mặt tối thiểu mà executor và simulator cần."""

    async def publish(
        self, topic: str, payload: dict[str, Any] | None, *, qos: int = 1, retain: bool = False
    ) -> None:
        """`payload=None` gửi message rỗng; kèm `retain=True` là cách xoá
        retained message của topic đó theo đặc tả MQTT."""
        ...

    async def subscribe(self, topic_filter: str, handler: Handler) -> None: ...


def topic_matches(topic_filter: str, topic: str) -> bool:
    """Khớp topic theo wildcard MQTT (`+` một cấp, `#` nhiều cấp)."""
    filter_parts = topic_filter.split("/")
    topic_parts = topic.split("/")
    for index, expected in enumerate(filter_parts):
        if expected == "#":
            return True
        if index >= len(topic_parts):
            return False
        if expected != "+" and expected != topic_parts[index]:
            return False
    return len(filter_parts) == len(topic_parts)


class InMemoryBroker:
    """Broker giả cho unit test — không cần Mosquitto.

    Mô phỏng đủ hai hành vi quan trọng: định tuyến theo wildcard, và
    **retained message** được giao ngay cho subscriber nối vào sau.
    """

    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []
        self._retained: dict[str, dict[str, Any]] = {}
        self.published: list[tuple[str, dict[str, Any], int, bool]] = []

    async def publish(
        self, topic: str, payload: dict[str, Any] | None, *, qos: int = 1, retain: bool = False
    ) -> None:
        if payload is None:
            # Message rỗng + retain = xoá retained message của topic.
            if retain:
                self._retained.pop(topic, None)
            return
        self.published.append((topic, payload, qos, retain))
        if retain:
            self._retained[topic] = payload
        for topic_filter, handler in list(self._subs):
            if topic_matches(topic_filter, topic):
                await handler(topic, payload)

    async def subscribe(self, topic_filter: str, handler: Handler) -> None:
        self._subs.append((topic_filter, handler))
        for topic, payload in list(self._retained.items()):
            if topic_matches(topic_filter, topic):
                await handler(topic, payload)

    def retained(self, topic: str) -> dict[str, Any] | None:
        return self._retained.get(topic)

    def published_on(self, topic: str) -> list[dict[str, Any]]:
        return [payload for sent_topic, payload, _, _ in self.published if sent_topic == topic]


class AiomqttClient:
    """Adapter aiomqtt chạy nền, hợp với vòng đời FastAPI/asyncio.

    aiomqtt dùng async context manager; ta giữ context đó sống trong một task
    nền để service dài hạn publish/subscribe được bất cứ lúc nào.
    """

    def __init__(
        self,
        url: str,
        *,
        client_id: str,
        username: str | None = None,
        password: str | None = None,
        clean_session: bool = True,
        keepalive: int = 30,
        will: Will | None = None,
        reconnect_delay: float = 2.0,
    ) -> None:
        parsed = urlparse(url)
        self._hostname = parsed.hostname or "localhost"
        self._port = parsed.port or 1883
        self._client_id = client_id
        self._username = username or None
        self._password = password or None
        self._clean_session = clean_session
        self._keepalive = keepalive
        self._will = will
        self._reconnect_delay = reconnect_delay

        self._subs: list[tuple[str, Handler]] = []
        self._client: Any = None
        self._task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._stopping = False

    async def start(self, *, wait: bool = True, timeout: float = 10.0) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name=f"mqtt-{self._client_id}")
        if wait:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._client = None
        self._connected.clear()

    async def simulate_connection_loss(self) -> None:
        """Cắt socket mà không gửi DISCONNECT — broker sẽ phát Last Will.

        **Hook fault injection, KHÔNG gọi trong đường chạy thật.** Muốn dừng
        client bình thường thì dùng `stop()`.

        Tồn tại vì ADR-004 chọn MQTT một phần nhờ "hỗ trợ fault injection", và
        vì không có cách nào khác kiểm được LWT: `stop()` đóng context aiomqtt
        một cách sạch sẽ nên gửi DISCONNECT, mà DISCONNECT sạch thì theo đặc
        tả MQTT khiến broker **huỷ** Will thay vì phát nó.

        Hạn chế đã biết: huỷ context giữa chừng khiến vài task nội bộ của
        aiomqtt bị bỏ lại, asyncio có thể cảnh báo "Task was destroyed but it
        is pending". Không vá bằng cách đụng vào private của thư viện.
        """
        self._stopping = True
        paho = getattr(self._client, "_client", None)
        sock = paho.socket() if paho is not None else None
        if sock is None:
            raise RuntimeError("không lấy được socket để mô phỏng mất kết nối")
        # shutdown chứ không close: FIN vẫn được gửi nên broker thấy mất kết
        # nối bất thường, nhưng fd còn hợp lệ để event loop gỡ đăng ký. Gọi
        # close() thẳng làm selector nổ WinError 10038.
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        await self.stop()

    async def publish(
        self, topic: str, payload: dict[str, Any] | None, *, qos: int = 1, retain: bool = False
    ) -> None:
        await self._connected.wait()
        assert self._client is not None
        # payload rỗng + retain = xoá retained message (đặc tả MQTT).
        body = b"" if payload is None else json.dumps(payload).encode()
        await self._client.publish(topic, payload=body, qos=qos, retain=retain)

    async def subscribe(self, topic_filter: str, handler: Handler) -> None:
        self._subs.append((topic_filter, handler))
        if self._connected.is_set() and self._client is not None:
            await self._client.subscribe(topic_filter, qos=1)

    async def _run(self) -> None:
        import aiomqtt

        will = None
        if self._will is not None:
            will = aiomqtt.Will(
                topic=self._will.topic,
                payload=json.dumps(self._will.payload).encode(),
                qos=self._will.qos,
                retain=self._will.retain,
            )

        while not self._stopping:
            try:
                async with aiomqtt.Client(
                    hostname=self._hostname,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    identifier=self._client_id,
                    clean_session=self._clean_session,
                    keepalive=self._keepalive,
                    will=will,
                ) as client:
                    self._client = client
                    for topic_filter, _ in self._subs:
                        await client.subscribe(topic_filter, qos=1)
                    self._connected.set()
                    logger.info("MQTT connected: %s:%s as %s", self._hostname, self._port, self._client_id)
                    async for message in client.messages:
                        await self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — reconnect với mọi lỗi transport
                logger.warning("MQTT lỗi (%s), thử lại sau %.1fs", exc, self._reconnect_delay)
            finally:
                self._connected.clear()
                self._client = None
            if not self._stopping:
                await asyncio.sleep(self._reconnect_delay)

    async def _dispatch(self, message: Any) -> None:
        topic = str(message.topic)
        if not message.payload:
            # Message rỗng là tín hiệu xoá retained, không phải dữ liệu.
            return
        try:
            payload = json.loads(message.payload)
        except (ValueError, TypeError):
            logger.warning("Bỏ qua message không phải JSON trên %s", topic)
            return
        if not isinstance(payload, dict):
            logger.warning("Bỏ qua payload không phải object trên %s", topic)
            return
        for topic_filter, handler in list(self._subs):
            if topic_matches(topic_filter, topic):
                try:
                    await handler(topic, payload)
                except Exception:  # noqa: BLE001 — một handler hỏng không được giết vòng lặp
                    logger.exception("Handler lỗi trên topic %s", topic)

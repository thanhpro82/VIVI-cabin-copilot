"""Bus phát tán cho `/ws/engineer` + sampler định kỳ dùng chung.

Khác `IviEventBus` ở đúng một điểm quan trọng: **không khoá theo `session_id`**.
`docs/api_spec.md:531` chốt `connection.init` của `/ws/engineer` **bỏ** `session_id`
— kỹ sư nhìn cả đội xe, không nhìn một phiên. Nên đây là phát tán tới mọi listener.

Nhịp phát (`api_spec.md` liệt kê đủ payload nhưng **không** nói trigger — quyết
định ghi ở docs/tasks/TASK-BE-OBS-001 §4):

    connect   → health + metrics + state  (snapshot ngay, không bắt client chờ)
    lượt seal → trace                      (theo sự kiện)
    mỗi 5s    → metrics
    mỗi 10s   → health

SAMPLER LÀ **MỘT** CHO MỌI KẾT NỐI, không phải mỗi socket một cái. Health chạy 8
probe thật (`src/services/health.py`); nhân theo số socket thì ba tab dashboard mở
cùng lúc sẽ gọi STT/TTS/RAG smoke-test gấp ba. Sampler khởi động lúc có listener
đầu tiên và dừng khi listener cuối rời — không ai xem thì không tốn gì, và không
phải móc vào lifespan (`ASGITransport` trong test không chạy lifespan).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

EngineerListener = Callable[[str, dict[str, Any]], Awaitable[None]]


class EngineerEventBus:
    """Phát tán `(event_type, payload)` tới mọi listener đang nối."""

    def __init__(self) -> None:
        self._listeners: list[EngineerListener] = []
        self._sampler: asyncio.Task[None] | None = None
        self._sample: Callable[[], Awaitable[None]] | None = None

    # -- đăng ký ---------------------------------------------------------------

    def add_listener(self, callback: EngineerListener) -> None:
        self._listeners.append(callback)
        self._ensure_sampler()

    def remove_listener(self, callback: EngineerListener) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)
        if not self._listeners:
            self.stop_sampler()

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    # -- phát ------------------------------------------------------------------

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        # Chụp danh sách trước khi lặp: callback có thể tự gỡ mình ra giữa chừng
        # (WS disconnect ngay lúc publish), sửa list đang lặp thì lỗi. Cùng lý do
        # đã ghi ở `IviEventBus.publish`.
        for callback in list(self._listeners):
            try:
                await callback(event_type, payload)
            except Exception:
                # Một socket chết không được chặn việc giao cho các socket còn lại,
                # cũng không được làm gãy luồng của người publish.
                logger.exception("Engineer listener lỗi khi nhận %s, tiếp tục", event_type)

    # -- sampler ---------------------------------------------------------------

    def set_sampler(self, sample: Callable[[], Awaitable[None]]) -> None:
        """Cắm hàm lấy mẫu. Gọi trước khi có listener đầu tiên."""
        self._sample = sample

    def _ensure_sampler(self) -> None:
        if self._sample is None or self._sampler is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Không có event loop (đăng ký từ code đồng bộ trong test) — bỏ qua.
            # Bus vẫn phát được, chỉ là không có nhịp định kỳ.
            return
        self._sampler = loop.create_task(self._run_sampler())

    def stop_sampler(self) -> None:
        if self._sampler is not None:
            self._sampler.cancel()
            self._sampler = None

    async def _run_sampler(self) -> None:
        assert self._sample is not None
        try:
            while self._listeners:
                await self._sample()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Sampler chết im lặng nghĩa là dashboard đóng băng mà không ai biết.
            logger.exception("Sampler của /ws/engineer dừng vì lỗi")


class EngineerSampler:
    """Nhịp định kỳ cho `metrics` và `health`, hai chu kỳ khác nhau trên một task.

    Gộp vào một task thay vì hai: hai `asyncio.Task` cho hai nhịp nghĩa là hai chỗ
    phải huỷ đúng lúc, và một cái sót lại sẽ giữ tham chiếu tới bus mãi mãi.
    """

    def __init__(
        self,
        bus: EngineerEventBus,
        metrics_payload: Callable[[], Awaitable[dict[str, Any]]],
        health_payload: Callable[[], Awaitable[dict[str, Any]]],
        metrics_interval_s: float,
        health_interval_s: float,
    ) -> None:
        self._bus = bus
        self._metrics_payload = metrics_payload
        self._health_payload = health_payload
        self._metrics_interval = metrics_interval_s
        self._health_interval = health_interval_s
        self._elapsed = 0.0
        #: Bước lặp = ước chung; mỗi vòng chỉ ngủ đúng bằng đó rồi kiểm hai mốc.
        self._tick = min(metrics_interval_s, health_interval_s)

    async def __call__(self) -> None:
        """Phát TRƯỚC rồi mới ngủ, nên vòng đầu bắn ngay cả `metrics` lẫn `health`.

        Ngủ trước thì dashboard vừa mở phải đợi hết một chu kỳ health (10s) mới thấy
        readiness. Phát trước cho snapshot ngay mà **không** chặn handshake: sampler
        chạy trong task riêng, còn `collect_health` thì nặng thật — nó nạp model STT
        thật ở lần đầu, nên tuyệt đối không được nằm trên đường `connect`.
        """
        if self._elapsed % self._metrics_interval < self._tick:
            await self._publish("metrics", self._metrics_payload)
        if self._elapsed % self._health_interval < self._tick:
            await self._publish("health", self._health_payload)
        await asyncio.sleep(self._tick)
        self._elapsed += self._tick

    async def _publish(self, event_type: str, build: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        try:
            payload = await build()
        except Exception:
            # Probe health hoặc fold metrics lỗi thì bỏ nhịp này, không giết sampler:
            # một lần MQTT chớp tắt không được làm dashboard câm vĩnh viễn.
            logger.exception("Không dựng được payload %s, bỏ qua nhịp này", event_type)
            return
        await self._bus.publish(event_type, payload)


_BUS = EngineerEventBus()


def get_engineer_bus() -> EngineerEventBus:
    return _BUS


def reset_engineer_bus() -> None:
    """Hook cho test — listener và sampler của test trước không rò sang test sau."""
    global _BUS
    with contextlib.suppress(Exception):
        _BUS.stop_sampler()
    _BUS = EngineerEventBus()

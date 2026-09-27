"""Cache trạng thái xe phía backend, nuôi từ retained message của simulator.

Backend **chỉ forward** cache này ra `GET /api/v1/vehicle/state` và WebSocket,
không map lại tên field. `VehicleStateSnapshot` trừ `schema_version` phải bằng
đúng `data.vehicle_state` — hai bên lệch nhau là bug (docs/mqtt_spec.md).

Nhờ `state/snapshot` và `health` đều retain, cache đầy ngay khi backend nối
vào broker, không phải hỏi lại simulator.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from src import mqtt_topics
from src.models.vehicle import Health, VehicleState, VehicleStateSnapshot
from src.services.mqtt_client import MqttPort

logger = logging.getLogger(__name__)

Listener = Callable[[VehicleState], Awaitable[None]]

#: Vì sao xe ảo bị coi là chưa sẵn sàng. Bốn lý do này **khác nhau về hành động**:
#: `broker_unreachable` là ta còn không có đường nghe (sửa hạ tầng);
#: `no_health` là có đường nhưng chưa nghe thấy gì (có thể vừa nối, đợi thêm);
#: `offline` là simulator đã chủ động nói nó chết hoặc Last Will đã bắn (đợi vô
#: ích); `heartbeat_stale` là nó im lặng quá lâu (khả năng cao đã treo).
#:
#: `broker_unreachable` do tầng gateway gán chứ không phải cache — cache không
#: biết gì về transport, nó chỉ biết mình đã nhận được gì.
ReadinessReason = Literal["ready", "broker_unreachable", "no_health", "offline", "heartbeat_stale"]


@dataclass(frozen=True)
class SimulatorReadiness:
    """Kết quả chấm điểm sẵn sàng, kèm số liệu để đưa vào `error.details`.

    Trả cả lý do chứ không chỉ bool vì `GET /api/v1/vehicle/state` và `/healthz`
    đều cần nói cho client biết *vì sao* — "lỗi không rõ" là thứ khiến người dùng
    frontend không debug được.
    """

    ready: bool
    reason: ReadinessReason
    online: bool | None
    health_age_s: float | None
    heartbeat_stale_s: float


class VehicleStateCache:
    def __init__(
        self,
        vehicle_id: str,
        *,
        heartbeat_stale_s: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`clock` tiêm được để test tuổi heartbeat mà không phải `sleep`.

        Trên Windows độ phân giải timer khoảng 15,6 ms nên mọi `asyncio.sleep`
        dưới ~50 ms là không đáng tin; một test phải chờ 15 giây thật để chứng
        minh heartbeat hết hạn thì sẽ không ai chạy nó. Đây là lý do duy nhất của
        tham số này — production luôn dùng `time.monotonic`.
        """
        self.vehicle_id = vehicle_id
        self._heartbeat_stale_s = heartbeat_stale_s
        self._clock = clock
        self._state: VehicleState | None = None
        self._health: Health | None = None
        self._health_at: float | None = None
        self._listeners: list[Listener] = []
        #: Tăng mỗi lần phát hiện xe ảo khởi động lại — xem `_on_health`. Người
        #: đọc dùng nó để bỏ mọi thứ suy ra từ lần chạy trước;
        #: `MqttVehicleGateway._await_floor` là caller đầu tiên.
        self._incarnation = 0

    async def attach(self, mqtt: MqttPort) -> None:
        await mqtt.subscribe(mqtt_topics.snapshot(self.vehicle_id), self._on_snapshot)
        await mqtt.subscribe(mqtt_topics.health(self.vehicle_id), self._on_health)

    # -- đọc ---------------------------------------------------------------

    @property
    def state(self) -> VehicleState | None:
        return self._state

    @property
    def health(self) -> Health | None:
        return self._health

    @property
    def heartbeat_stale_s(self) -> float:
        return self._heartbeat_stale_s

    @property
    def incarnation(self) -> int:
        """Số lần đã phát hiện xe ảo khởi động lại kể từ khi cache này sống.

        Không phải "số lần xe ảo restart" — cache chỉ đếm được những lần nó **nhìn
        thấy**, và nó không thấy gì trong khoảng nó chưa nối broker.
        """
        return self._incarnation

    def readiness(self) -> SimulatorReadiness:
        """Chấm sẵn sàng kèm lý do và số liệu.

        Cơ sở để `/healthz` chấm `vehicle_simulator` (docs/devops.md) và để
        `GET /api/v1/vehicle/state` từ chối trả snapshot đã hết hạn.
        """
        if self._health is None or self._health_at is None:
            return SimulatorReadiness(
                ready=False,
                reason="no_health",
                online=None,
                health_age_s=None,
                heartbeat_stale_s=self._heartbeat_stale_s,
            )

        age = self._clock() - self._health_at
        if not self._health.online:
            return SimulatorReadiness(
                ready=False,
                reason="offline",
                online=False,
                health_age_s=age,
                heartbeat_stale_s=self._heartbeat_stale_s,
            )
        if age > self._heartbeat_stale_s:
            return SimulatorReadiness(
                ready=False,
                reason="heartbeat_stale",
                online=True,
                health_age_s=age,
                heartbeat_stale_s=self._heartbeat_stale_s,
            )
        return SimulatorReadiness(
            ready=True,
            reason="ready",
            online=True,
            health_age_s=age,
            heartbeat_stale_s=self._heartbeat_stale_s,
        )

    def simulator_ready(self) -> bool:
        """Giữ nguyên chữ ký cũ cho các caller không cần biết lý do."""
        return self.readiness().ready

    # -- đẩy cho WebSocket -------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    # -- handler MQTT ------------------------------------------------------

    async def _on_snapshot(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            snapshot = VehicleStateSnapshot.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Snapshot sai schema trên %s: %s", topic, exc.error_count())
            return
        state = snapshot.to_state()
        if self._state is not None and state.state_version < self._state.state_version:
            # Message tới trễ sau khi đã có bản mới hơn — bỏ qua, đừng lùi state.
            logger.debug(
                "Bỏ snapshot cũ v%d (đang giữ v%d)",
                state.state_version,
                self._state.state_version,
            )
            return
        self._state = state
        await self._notify(state)

    async def _on_health(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            health = Health.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Health sai schema trên %s: %s", topic, exc.error_count())
            return
        was_offline = self._health is not None and not self._health.online
        self._health = health
        self._health_at = self._clock()
        if not health.online:
            logger.warning("Xe ảo %s offline (reason=%s)", self.vehicle_id, health.reason)
            return
        if was_offline:
            self._forget_state_of_previous_run(health.state_version)

    def _forget_state_of_previous_run(self, reported_version: int | None) -> None:
        """Xe ảo vừa `offline` → `online` ⇒ đây là một lần chạy MỚI, bỏ state cũ.

        Chuỗi trên dây: xe ảo chết thì LWT (`reason="lwt"`) hoặc shutdown có trật tự
        phát `online=false`; khởi lại thì Birth phát `online=true`. Cặp Birth+LWT là
        pattern chuẩn MQTT và `SimulatorRuntime` dùng đúng nó.

        Phải bỏ vì bộ đếm reset: `vehicle_sim/state.py::initial_state` luôn bắt đầu ở
        `state_version=1`, trong khi `_on_snapshot` bỏ qua mọi snapshot có version
        thấp hơn version đang giữ. Guard đó đúng cho message tới trễ nhưng không
        phân biệt được nó với "xe ảo restart" — và đó chính là chỗ hỏng: backend giữ
        version của lần chạy trước, mọi `expected_state_version` đều lệch, xe ảo từ
        chối bằng `stale_state`, còn `/healthz` thì vẫn xanh. Phát hiện bằng tầng
        test L3 (issue #49).

        **KHÔNG dùng `health.state_version` để suy ra restart**, dù nó có sẵn và
        trông tiện. `health` retain=true và chỉ được publish lại mỗi nhịp heartbeat,
        nên số nó mang **lag** so với state thật: giữa hai nhịp, xe ảo chạy lệnh và
        version leo lên, còn retained health vẫn giữ số cũ. Một subscriber nối muộn
        nhận retained snapshot v2 rồi retained health v1 là chuyện **bình thường**,
        không phải restart — bản đầu tiên của hàm này kết luận nhầm đúng như vậy và
        vứt mất state đúng, `test_backend_noi_sau_van_nhan_du_state_qua_retained` bắt
        được. Chuyển tiếp offline→online thì không có kiểu nhiễu đó.

        Quên `_state` là đủ để cả hệ thống fail-closed, không cần thêm reason mới:
        `GET /vehicle/state` thấy `last_known() is None` và trả 503 `no_snapshot_yet`
        (`src/api/routes.py`), còn `MqttVehicleGateway.snapshot()` trả `None` khiến
        `safety_node` từ chối lượt. `readiness()` cố ý không đổi — heartbeat đang
        tươi thật và xe ảo đang sống thật, nên báo `vehicle_simulator: down` sẽ là
        nói dối; đây đúng là tình huống vẫn xảy ra ngay sau khi khởi động, chỉ khác
        là lần này cache có sẵn một state cũ cần vứt đi.

        Giới hạn đã biết: nếu broker giao Birth **trước** LWT (thứ tự đảo, hiếm) thì
        không có chuyển tiếp nào để thấy, và cache giữ state cũ cho tới nhịp
        heartbeat kế tiếp — lúc đó `online=false` đã được ghi nhận nên nhịp sau tạo
        ra chuyển tiếp và mọi thứ tự chữa. Cửa sổ sai tối đa bằng
        `MQTT_HEARTBEAT_INTERVAL_S` (mặc định 5s).
        """
        previous = self._state.state_version if self._state is not None else None
        logger.warning(
            "Xe ảo %s đã khởi động lại (cache v%s, health v%s) — bỏ state của lần chạy trước",
            self.vehicle_id,
            previous,
            reported_version,
        )
        self._state = None
        self._incarnation += 1

    async def _notify(self, state: VehicleState) -> None:
        for listener in list(self._listeners):
            try:
                await listener(state)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — một client hỏng không giết luồng state
                logger.exception("Listener state lỗi")

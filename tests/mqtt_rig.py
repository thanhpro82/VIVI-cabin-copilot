"""Giàn dựng chuỗi MQTT đầy đủ cho test: gateway → executor → broker → xe ảo → cache.

Trước file này, ba file test dựng ba fixture gần giống hệt nhau (`wired`, `live`,
`runtime`). Ba bản sao nghĩa là ba chỗ phải sửa khi hợp đồng đổi, và trên thực tế
chúng đã bắt đầu lệch nhau về `heartbeat_interval_s` và `timeout_ms`.

Đây là helper thuần, **không** có pytest magic — fixture khai ở `tests/conftest.py`
(tầng in-memory, mọi file test đều dùng được) và `tests/test_vehicle/conftest.py`
(tầng broker thật). Lý do tách: `tests/test_api/` cũng cần giàn này, mà conftest
của `test_vehicle/` không nhìn thấy sang đó.

## Ba luật cứng về thời gian

Trên Windows độ phân giải timer khoảng 15,6 ms, nên:

1. **Không bao giờ** khẳng định "việc X không xảy ra" bằng một `sleep` mà thiếu
   positive control — test sẽ pass vì chờ chưa đủ lâu, không phải vì đúng.
2. **Không bao giờ** dùng `sleep` cho chiều "vẫn còn tươi" — dùng `FakeClock`.
3. Chờ thì chờ bằng `Rig.wait_for(pred, timeout)`, không bằng `sleep` cố định.

`InMemoryBroker.publish` gọi handler **đồng bộ ngay trong lời gọi**, nên tầng
in-memory hoàn toàn tất định và gần như không cần chờ gì. Đó vừa là điểm mạnh
(không flaky) vừa là điểm mù: nó không bao giờ tạo ra xen kẽ thời gian thật. Điểm
mù đó phải nằm trong báo cáo, không được giấu.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src import mqtt_topics
from src.models.vehicle import ToolResult
from src.services.mqtt_client import InMemoryBroker
from src.services.mqtt_runtime import MqttRuntime
from src.services.tool_executor import ToolExecutor
from src.services.vehicle_gateway import MqttVehicleGateway
from src.services.vehicle_state import VehicleStateCache
from src.vehicle_sim.runtime import SimulatorRuntime
from src.vehicle_sim.state import VehicleSimulator

VEHICLE_ID = "vehicle-test-01"

#: Tắt heartbeat mặc định (một nhịp mỗi giờ). Test nào cần nhịp thật thì tự đặt
#: `heartbeat_interval_s` nhỏ; còn lại thì một task nền chạy giữa các test chỉ
#: tạo nhiễu và rò task.
_HEARTBEAT_OFF_S = 3600.0


class FakeClock:
    """monotonic giả, tiêm vào `VehicleStateCache` để test tuổi heartbeat.

    Ngưỡng mặc định là 15 giây. Chứng minh nó hết hạn bằng `sleep` thật sẽ tốn 15
    giây mỗi lần chạy suite — và một test tốn 15 giây là một test không ai chạy.
    """

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Rig:
    """Một chuỗi MQTT hoàn chỉnh, đã nối sẵn."""

    broker: InMemoryBroker
    simulator: VehicleSimulator
    sim_runtime: SimulatorRuntime
    backend: MqttRuntime
    gateway: MqttVehicleGateway
    clock: FakeClock

    # -- lối tắt -----------------------------------------------------------

    @property
    def executor(self) -> ToolExecutor:
        assert self.backend.executor is not None
        return self.backend.executor

    @property
    def cache(self) -> VehicleStateCache:
        return self.backend.cache

    @property
    def version(self) -> int:
        """Version của **simulator** — nguồn sự thật, không phải cache."""
        return self.simulator.state.state_version

    # -- hành động ---------------------------------------------------------

    async def run(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        plan_id: str = "plan_t",
        step_id: str = "step_1",
        expected_state_version: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Chạy một lệnh qua cổng.

        `expected_state_version` mặc định là version hiện tại — mặc định này bớt
        được sáu dòng mỗi ca test, và ca nào cần version sai thì truyền tường minh
        (nhìn vào là biết đó chính là điều đang được kiểm).
        """
        return await self.gateway.execute(
            plan_id=plan_id,
            step_id=step_id,
            tool=tool,
            args=args,
            expected_state_version=(
                self.version if expected_state_version is None else expected_state_version
            ),
            **kwargs,
        )

    async def publish_raw(
        self,
        topic: str,
        payload: dict[str, Any] | None,
        *,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Bơm payload thô, kể cả sai schema.

        Phải đi đường này chứ không dựng model rồi làm hỏng: `_Strict` bật
        `validate_assignment=True` nên pydantic sẽ nổ ngay lúc dựng, và ta không
        bao giờ chạm tới được nhánh phòng thủ ở phía nhận.
        """
        await self.broker.publish(topic, payload, qos=qos, retain=retain)

    @contextlib.contextmanager
    def swallow_command_events(self):
        """Bỏ rơi mọi `events/command` — tái hiện *transient transport failure*.

        Phải chặn ở tầng broker chứ không phải vá `ToolExecutor._on_event`:
        handler đã được đăng ký vào broker lúc `attach()` dưới dạng bound method,
        nên gán lại thuộc tính trên instance không đổi được thứ đang được gọi.

        Lưu ý khi đọc test dùng helper này: lệnh **vẫn tới simulator và vẫn được
        thực thi**. Cái mất là đường phản hồi. Đó chính là tình huống mà retry
        phải giữ nguyên `command_id` — nếu không, lần thử thứ hai sẽ là một lệnh
        mới và xe sẽ chạy hai lần.
        """
        original = self.broker.publish

        async def filtered(topic, payload, *, qos=1, retain=False):
            if topic.endswith("/events/command"):
                return
            await original(topic, payload, qos=qos, retain=retain)

        self.broker.publish = filtered  # type: ignore[method-assign]
        try:
            yield
        finally:
            self.broker.publish = original  # type: ignore[method-assign]

    async def wait_for(
        self, predicate: Callable[[], bool], *, timeout: float = 2.0
    ) -> None:
        """Chờ tới khi `predicate()` đúng. Vòng lặp có nhường loop, không sleep cứng."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(f"quá {timeout}s mà điều kiện vẫn chưa đúng")
            await asyncio.sleep(0)

    # -- quan sát ----------------------------------------------------------

    def published_topics(self) -> list[str]:
        return [topic for topic, _payload, _qos, _retain in self.broker.published]

    def snapshots_published(self) -> list[dict[str, Any]]:
        return self.broker.published_on(mqtt_topics.snapshot(self.backend.vehicle_id))

    def events_published(self) -> list[dict[str, Any]]:
        return self.broker.published_on(mqtt_topics.events_command(self.backend.vehicle_id))

    def commands_published(self) -> list[tuple[str, dict[str, Any], int, bool]]:
        return [
            entry
            for entry in self.broker.published
            if "/commands/" in entry[0]
        ]

    def retain_flag_of(self, topic: str) -> list[bool]:
        return [retain for sent, _payload, _qos, retain in self.broker.published if sent == topic]


async def build_rig(
    *,
    vehicle_id: str = VEHICLE_ID,
    clock: FakeClock | None = None,
    heartbeat_interval_s: float = _HEARTBEAT_OFF_S,
    heartbeat_stale_s: float = 15.0,
    timeout_ms: int = 500,
    sim_control_enabled: bool = False,
) -> Rig:
    broker = InMemoryBroker()
    simulator = VehicleSimulator(vehicle_id)
    sim_runtime = SimulatorRuntime(
        simulator,
        broker,
        heartbeat_interval_s=heartbeat_interval_s,
        # Mặc định **tắt**, đúng như production — giàn không được bật hộ một cờ
        # mà đời thật phải bật tường minh, nếu không thì không ai kiểm được rằng
        # tắt nghĩa là im lặng (ADR-024).
        sim_control_enabled=sim_control_enabled,
    )
    await sim_runtime.start()

    clock = clock or FakeClock()
    backend = MqttRuntime(vehicle_id, heartbeat_stale_s=heartbeat_stale_s, clock=clock)
    await backend.bind(broker, timeout_ms=timeout_ms)

    return Rig(
        broker=broker,
        simulator=simulator,
        sim_runtime=sim_runtime,
        backend=backend,
        gateway=MqttVehicleGateway(backend),
        clock=clock,
    )


async def teardown_rig(rig: Rig) -> None:
    await rig.sim_runtime.stop()

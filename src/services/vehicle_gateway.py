"""Cổng duy nhất để phần còn lại của backend nói chuyện với xe.

## Vấn đề nó giải

Repo đang có hai đường tới trạng thái xe, không nối nhau: đường MQTT
(`src/vehicle_sim/` + `ToolExecutor` + `VehicleStateCache`) nuôi
`GET /api/v1/vehicle/state`, còn agent graph gọi thẳng một simulator in-memory
riêng. Hệ quả: lệnh của người dùng đổi state ở một chỗ, còn API đọc ở chỗ kia.

`VehicleGateway` là hình dạng mà **cả hai** đường cùng nói. Ai cần trạng thái xe
hay cần chạy một tool thì đi qua đây, không đi thẳng xuống `MqttRuntime` hay
`VehicleSimulator` nữa.

## Vì sao có HAI method đọc

`snapshot()` trả `None` khi xe ảo chưa sẵn sàng; `last_known()` trả state cuối
cùng biết được bất kể tươi cũ. Tách ra là có chủ đích, không phải tiện tay:

- Màn hình **được phép** hiển thị dữ liệu cũ — thà hiện nhiệt độ của mười giây
  trước còn hơn hiện ô trống.
- Phân loại an toàn S0–S3 thì **không**. Xếp một lệnh mở cửa là S2 hay S3 phụ
  thuộc `speed_kph == 0 && gear == "P"`; đọc nhầm state cũ ở đây nghĩa là đưa thẻ
  xác nhận cho một hành động lẽ ra phải chặn thẳng. Chỗ đó phải thà không trả lời
  còn hơn trả lời sai.

Người gọi chọn nhầm method là một lỗi an toàn thật, nên tên method nói rõ ý.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from src.bounded_cache import BoundedCache
from src.models.vehicle import ToolResult, VehicleCommand, VehicleState, utc_now
from src.services.mqtt_runtime import MqttRuntime
from src.services.vehicle_state import SimulatorReadiness
from src.vehicle_sim.state import VehicleSimulator

logger = logging.getLogger(__name__)

StateListener = Callable[[VehicleState], Awaitable[None]]

#: Cổng in-process không có khái niệm "mất kết nối" nên luôn sẵn sàng.
_ALWAYS_READY = SimulatorReadiness(ready=True, reason="ready", online=True, health_age_s=0.0, heartbeat_stale_s=0.0)


def snapshot_dict(state: VehicleState) -> dict[str, Any]:
    """Trạng thái xe dạng dict canonical.

    `mode="json"` chứ không phải `model_dump()` trần, vì hai lý do cùng lúc: dict
    này đi qua checkpoint của LangGraph (phải serialize được bằng msgpack), và nó
    phải bằng **đúng** `data.vehicle_state` mà `GET /api/v1/vehicle/state` trả ra.
    Một shape từ đầu tới cuối thì không có chỗ cho drift.
    """
    return state.model_dump(mode="json")


@runtime_checkable
class VehicleGateway(Protocol):
    """Hợp đồng mà agent graph và tầng API cùng dùng."""

    vehicle_id: str

    async def snapshot(self) -> VehicleState | None:
        """State đủ tươi để **lập kế hoạch**. `None` = không đủ điều kiện."""
        ...

    async def last_known(self) -> VehicleState | None:
        """State mới nhất biết được, kể cả đã cũ. Chỉ dùng để **hiển thị**."""
        ...

    def readiness(self) -> SimulatorReadiness: ...

    async def execute(
        self,
        *,
        plan_id: str,
        step_id: str,
        tool: str,
        args: dict[str, Any],
        expected_state_version: int,
        approval_id: str | None = None,
        execution_group_id: str | None = None,
    ) -> ToolResult: ...

    def add_listener(self, listener: StateListener) -> None: ...

    def remove_listener(self, listener: StateListener) -> None: ...


@runtime_checkable
class MotionInjectable(Protocol):
    """Đặt tốc độ/số từ bên ngoài — chỉ bản in-process làm được.

    Tách khỏi `VehicleGateway` chứ không nhét chung, vì dưới MQTT thì **không tồn
    tại**: `docs/mqtt_spec.md:337-349` cấm backend publish `state/*`, và `motion`
    nằm trong `READ_ONLY_DOMAINS` nên không có topic lệnh nào cho nó. Người gọi
    phải `isinstance(gateway, MotionInjectable)` rồi mới dùng — đó là cách duy
    nhất trung thực để diễn đạt "năng lực này chỉ có ở một trong hai đường".
    """

    def set_motion(self, speed_kph: float, gear: str | None = None) -> None: ...


class InProcessVehicleGateway:
    """Chạy lệnh thẳng trên `src/vehicle_sim/state.py`, không qua broker.

    Dùng cho test và cho `MQTT_ENABLED=false`. Cố ý **không** dựng
    `InMemoryBroker` + `SimulatorRuntime` + `ToolExecutor` để làm loopback in
    process, dù về mặt kiến trúc thì đẹp hơn: `ToolExecutor` giữ `asyncio.Future`
    gắn với event loop đang chạy, mà pytest ở repo này đặt
    `asyncio_default_fixture_loop_scope = "function"` — một gateway sống ở module
    level sẽ mang Future của test trước sang test sau và nổ "got Future attached
    to a different loop". Đường thẳng không có Future, không có task nền.
    """

    def __init__(self, simulator: VehicleSimulator) -> None:
        self.vehicle_id = simulator.vehicle_id
        self.simulator = simulator
        # Cùng khoá idempotency với ToolExecutor (`plan_id:step_id`) để hai
        # implementation có hành vi replay giống nhau. Simulator còn một tầng
        # dedupe nữa theo `command_id`, nhưng tầng đó không thấy được replay ở
        # mức plan vì mỗi lần gọi lại sinh command_id mới.
        self._results: BoundedCache[str, ToolResult] = BoundedCache()
        self._listeners: list[StateListener] = []

    @classmethod
    def new(
        cls,
        vehicle_id: str = "vehicle-demo-01",
        *,
        speed_kph: float = 0.0,
        gear: str | None = None,
    ) -> InProcessVehicleGateway:
        gateway = cls(VehicleSimulator(vehicle_id))
        if speed_kph or gear is not None:
            gateway.set_motion(speed_kph, gear)
        return gateway

    # -- đọc ---------------------------------------------------------------

    @property
    def state(self) -> VehicleState:
        """Truy cập trực tiếp cho test. Production dùng `snapshot()`."""
        return self.simulator.state

    @property
    def command_count(self) -> int:
        return self.simulator.command_count

    async def snapshot(self) -> VehicleState | None:
        return self.simulator.snapshot()

    async def last_known(self) -> VehicleState | None:
        return self.simulator.snapshot()

    def readiness(self) -> SimulatorReadiness:
        return _ALWAYS_READY

    # -- ghi ---------------------------------------------------------------

    def set_motion(self, speed_kph: float, gear: str | None = None) -> None:
        """Xe ảo tự đặt tốc độ của mình — hợp lệ vì đây *là* xe ảo.

        Không suy `gear` từ `speed_kph` khi người gọi đã nói rõ: "đang chạy ở số
        P" là trạng thái vô lý nhưng vẫn cần dựng được để test chính cái vô lý đó.
        """
        self.simulator.state.motion.speed_kph = speed_kph
        if gear is not None:
            self.simulator.state.motion.gear = gear
        elif speed_kph:
            self.simulator.state.motion.gear = "D"

    async def execute(
        self,
        *,
        plan_id: str,
        step_id: str,
        tool: str,
        args: dict[str, Any],
        expected_state_version: int,
        approval_id: str | None = None,
        execution_group_id: str | None = None,
    ) -> ToolResult:
        idempotency_key = f"{plan_id}:{step_id}"
        cached = self._results.get(idempotency_key)
        if cached is not None:
            return cached

        command = VehicleCommand(
            command_id=f"cmd_{uuid.uuid4().hex[:20]}",
            idempotency_key=idempotency_key,
            plan_id=plan_id,
            step_id=step_id,
            vehicle_id=self.vehicle_id,
            approval_id=approval_id,
            execution_group_id=execution_group_id,
            expected_state_version=expected_state_version,
            tool=tool,
            args=args,
            issued_at=utc_now(),
        )
        outcome = self.simulator.execute(command)
        result = ToolResult.from_event(outcome.event, attempt_count=1)
        self._results.set(idempotency_key, result)

        if outcome.changed:
            await self._notify(self.simulator.snapshot())
        return result

    # -- listener ----------------------------------------------------------

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: StateListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def _notify(self, state: VehicleState) -> None:
        for listener in list(self._listeners):
            try:
                await listener(state)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — một client hỏng không giết luồng state
                logger.exception("Listener state lỗi")


#: `error_code` khi một phiên không có hợp đồng thuê xe cố ra lệnh.
#:
#: Chuỗi tự do chứ không thêm vào `ErrorCode` Literal: `ErrorCode` là **hợp đồng MQTT**
#: (`docs/mqtt_spec.md`), mà tình huống này không bao giờ lên dây — lệnh bị chặn ở
#: backend, không có `VehicleCommand` nào được publish. `ToolResult.error_code` khai
#: `str | None` đúng cho loại mã sinh ở backend như thế này.
POOL_CAN_KIET = "vehicle_pool_exhausted"


class ChiXemVehicleGateway:
    """Bọc một cổng thật: **đọc được, không ra lệnh được**.

    ## Vì sao chặn ở cổng chứ không ở từng chỗ nhận lệnh

    Lệnh vào hệ qua nhiều cửa — `POST /turns/text`, `POST /turns/voice`, resume sau khi
    duyệt HITL ở `POST /approvals/{id}/decision`, và kênh harness `POST /sim/motion`.
    Chặn ở từng cửa nghĩa là bốn chỗ phải cùng nhớ một luật, và cửa thứ năm mọc lên sau
    này sẽ quên. Bọc cổng thì việc từ chối là **cấu trúc**: không có đường nào đi vòng.

    ## Vì sao vẫn cho đọc

    Phiên chỉ-xem không được là một màn hình chết. Người đang chờ tới lượt vẫn thấy xe
    demo chạy, vẫn tra được sổ tay — họ chỉ không lái. Đó là khác biệt giữa "hết chỗ"
    và "hỏng".

    ## Vì sao trả `ToolResult` thay vì ném

    `execute.py` đã có sẵn đường xử lý kết quả không `completed`: nó dừng nhóm và đánh
    dấu các bước còn lại, nên hồ sơ lượt vẫn đầy đủ (issue #83). Ném exception là bắt
    đường đó phải mọc thêm một nhánh cho một chuyện nó đã biết cách xử lý.
    """

    def __init__(self, goc: VehicleGateway) -> None:
        self._goc = goc

    async def snapshot(self) -> VehicleState | None:
        return await self._goc.snapshot()

    async def last_known(self) -> VehicleState | None:
        return await self._goc.last_known()

    def readiness(self) -> SimulatorReadiness:
        return self._goc.readiness()

    def add_listener(self, listener: StateListener) -> None:
        self._goc.add_listener(listener)

    def remove_listener(self, listener: StateListener) -> None:
        self._goc.remove_listener(listener)

    async def execute(
        self,
        *,
        plan_id: str,
        step_id: str,
        tool: str,
        args: dict[str, Any],
        expected_state_version: int,
        approval_id: str | None = None,
        execution_group_id: str | None = None,
    ) -> ToolResult:
        # `observed_state_version` giữ nguyên `expected`: không có gì đổi, và cũng
        # không phải là "không nhìn thấy gì" — cùng cách `_ket_qua_tool_cuc_bo` làm.
        return ToolResult(
            command_id=f"chi-xem:{plan_id}:{step_id}",
            plan_id=plan_id,
            step_id=step_id,
            approval_id=approval_id,
            execution_group_id=execution_group_id,
            expected_state_version=expected_state_version,
            observed_state_version=expected_state_version,
            attempt_count=1,
            status="rejected",
            before={},
            after={},
            error_code=POOL_CAN_KIET,
            latency_ms=0.0,
        )


class MqttVehicleGateway:
    """Đường thật: publish lệnh lên broker, đọc state từ retained snapshot."""

    #: Chờ cache bắt kịp version mới nhất đã quan sát được. Xem `_await_floor`.
    FLOOR_BUDGET_S = 0.5

    def __init__(self, runtime: MqttRuntime) -> None:
        self.vehicle_id = runtime.vehicle_id
        self._runtime = runtime
        self._floor = 0
        # asyncio.Event trên 3.11 KHÔNG bind event loop lúc khởi tạo, nên tạo ở
        # đây là an toàn. Đừng đổi sang Condition/Queue — hai cái đó bind, và
        # gateway này sống ở module level qua nhiều event loop trong test.
        self._changed = asyncio.Event()
        self._seen_incarnation = runtime.cache.incarnation
        runtime.cache.add_listener(self._on_state)

    async def _on_state(self, state: VehicleState) -> None:
        self._changed.set()

    def close(self) -> None:
        """Gỡ listener khỏi cache. Gọi khi thay hoặc bỏ gateway.

        `__init__` đăng ký `_on_state` vào `runtime.cache`, mà cache sống lâu hơn
        gateway: dựng nhiều gateway trên cùng một `MqttRuntime` (chuyện thường
        trong test) sẽ tích listener của những gateway đã chết. Production một
        runtime một tiến trình nên không lộ ra, nhưng rò vẫn là rò.

        Idempotent — `remove_listener` bỏ qua listener không có trong danh sách.
        """
        self._runtime.cache.remove_listener(self._on_state)

    # -- đọc ---------------------------------------------------------------

    async def snapshot(self) -> VehicleState | None:
        """State đủ tươi để lập kế hoạch, hoặc `None`.

        **Cổng ở đây đo tuổi *heartbeat*, không đo tuổi *state* — có chủ đích.**

        State là event-driven và retained, nên "lâu rồi không có snapshot mới"
        nghĩa là "không có gì thay đổi", chứ không phải "dữ liệu đã cũ". Hai thứ
        đó không phân biệt được bằng đồng hồ. Thêm cổng theo tuổi state sẽ khiến
        hệ thống từ chối phục vụ dữ liệu **đúng** trong lúc xe đứng yên.

        Thứ bảo vệ tính đúng đắn khi thực thi là `expected_state_version`
        (optimistic concurrency), không phải độ tươi: lệnh mang version cũ bị
        simulator trả `stale_state`. Heartbeat trả lời một câu hỏi khác —
        *publisher còn sống không* — vì nếu nó chết thì suy luận "im lặng nghĩa
        là không đổi" mới hết đáng tin, và lúc đó ta phải câm.
        """
        await self._await_floor()
        if not self._runtime.cache.readiness().ready:
            return None
        return self._runtime.cache.state

    async def last_known(self) -> VehicleState | None:
        return self._runtime.cache.state

    def readiness(self) -> SimulatorReadiness:
        """Transport trước, nội dung sau.

        Không có đường tới broker thì cache có nói gì cũng vô nghĩa — nó chỉ đang
        lặp lại thứ nghe được lần cuối. Phân biệt hai nguyên nhân này quan trọng
        với người vận hành: một cái là sửa hạ tầng, cái kia là xem xe ảo.
        """
        if not self._runtime.connected:
            return SimulatorReadiness(
                ready=False,
                reason="broker_unreachable",
                online=None,
                health_age_s=None,
                heartbeat_stale_s=self._runtime.cache.heartbeat_stale_s,
            )
        return self._runtime.cache.readiness()

    def _reset_floor_if_simulator_restarted(self) -> None:
        """`_floor` đơn điệu tăng (`max(...)` ở `execute`), mà xe ảo khởi động lại thì
        bộ đếm của nó về 1 — nên floor cũ trở thành một mốc **không bao giờ đạt được**.

        Không reset thì mỗi `snapshot()` sau restart đốt trọn `FLOOR_BUDGET_S` rồi mới
        đi tiếp: không sai về an toàn (`expected_state_version` vẫn là lớp chặn thật)
        nhưng cộng nửa giây vào mọi lượt, vĩnh viễn, kèm một dòng warning mỗi lần.

        Cùng một họ lỗi với `VehicleStateCache._forget_state_if_restarted`: một giả
        định đơn điệu mà việc khởi động lại tiến trình phá vỡ. Cache là chỗ **duy
        nhất** phát hiện được, nên nó đếm, còn đây chỉ đọc lại.
        """
        current = self._runtime.cache.incarnation
        if current == self._seen_incarnation:
            return
        logger.info("Xe ảo khởi động lại — hạ floor từ v%d về 0", self._floor)
        self._seen_incarnation = current
        self._floor = 0

    async def _await_floor(self) -> None:
        """Chờ cache đạt version mới nhất mà ta đã thấy trong một ToolResult.

        **Đây chỉ là tối ưu độ trễ, KHÔNG phải cơ chế an toàn.** Sau một lệnh,
        snapshot retained mới cần một nhịp để về tới cache; đọc ngay lúc đó sẽ
        lấy được version cũ, và lệnh kế tiếp mang `expected_state_version` cũ sẽ
        bị simulator trả `stale_state`. Không sai về mặt an toàn — chỉ hỏng một
        lượt, và người dùng nói hai câu liên tiếp sẽ gặp.

        Hết budget thì **đi tiếp**, không raise: lớp bảo vệ thật vẫn là kiểm
        `expected_state_version` ở simulator. Đừng tăng budget lên vài giây rồi
        coi hàm này là thứ bảo đảm tính đúng đắn — làm vậy là bỏ optimistic
        concurrency mà vẫn tưởng còn.
        """
        self._reset_floor_if_simulator_restarted()
        deadline = time.monotonic() + self.FLOOR_BUDGET_S
        while True:
            state = self._runtime.cache.state
            if state is not None and state.state_version >= self._floor:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "Cache chưa đạt v%d sau %.1fs — đi tiếp, stale_state sẽ chặn nếu cần",
                    self._floor,
                    self.FLOOR_BUDGET_S,
                )
                return
            # Clear TRƯỚC khi chờ. Ngược lại thì tín hiệu đến giữa hai lần lặp sẽ
            # bị xoá mất và ta chờ tới hết budget một cách vô ích.
            self._changed.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), remaining)

    # -- ghi ---------------------------------------------------------------

    async def execute(
        self,
        *,
        plan_id: str,
        step_id: str,
        tool: str,
        args: dict[str, Any],
        expected_state_version: int,
        approval_id: str | None = None,
        execution_group_id: str | None = None,
    ) -> ToolResult:
        executor = self._runtime.executor
        if executor is None:
            raise RuntimeError("MqttRuntime chưa bind — không có executor")

        result = await executor.execute(
            plan_id=plan_id,
            step_id=step_id,
            tool=tool,
            args=args,
            expected_state_version=expected_state_version,
            approval_id=approval_id,
            execution_group_id=execution_group_id,
        )
        # `observed_state_version` đến từ chính CommandEvent, do simulator tính
        # sau khi đã tăng version — không phải đọc lại từ cache. Nên nó không có
        # race, và đây là nguồn đúng cho rolling expected_state_version.
        self._floor = max(self._floor, result.observed_state_version)
        return result

    # -- listener ----------------------------------------------------------

    def add_listener(self, listener: StateListener) -> None:
        self._runtime.cache.add_listener(listener)

    def remove_listener(self, listener: StateListener) -> None:
        self._runtime.cache.remove_listener(listener)


# --------------------------------------------------------------------------
# Singleton mức module
# --------------------------------------------------------------------------
#
# Cố ý KHÔNG để trong `app.state`: `tests/conftest.py` dùng `ASGITransport`, mà
# transport đó không chạy lifespan, nên phần lớn test API sẽ không bao giờ thấy
# giá trị gán trong lifespan. Accessor mức module thì cả hai đường đều thấy.

_GATEWAY: VehicleGateway | None = None

#: Listener của **ứng dụng**, phải sống qua mọi lần thay cổng.
#:
#: `add_listener` gắn vào đúng một instance. `main.py` đăng ký ở mức module (bắt buộc:
#: `ASGITransport` mà phần lớn test API dùng không chạy lifespan), nhưng `lifespan` sau
#: đó gọi `set_vehicle_gateway(...)` để thay cổng mặc định bằng MQTT/in-process thật —
#: và listener nằm lại trên object không ai dùng nữa.
#:
#: Đó là blocker Thành phát hiện ở PR #77: vế kích-theo-cạnh của `ui.policy` chết im ở
#: runtime trong khi cả bộ test vẫn xanh, vì mọi test đều tự dựng `UiPolicyEmitter`
#: riêng và không đi qua đoạn wiring này. Sổ đăng ký dưới đây sửa cho **mọi** listener
#: mức ứng dụng, không riêng `ui.policy` — người thêm listener sau không phải tự phát
#: hiện lại cái bẫy này.
_PERSISTENT_LISTENERS: list[StateListener] = []


def add_persistent_state_listener(listener: StateListener) -> None:
    """Đăng ký listener sống qua mọi lần thay/reset cổng. Gọi lại là không thêm trùng."""
    if listener not in _PERSISTENT_LISTENERS:
        _PERSISTENT_LISTENERS.append(listener)
    if _GATEWAY is not None:
        _GATEWAY.add_listener(listener)


def remove_persistent_state_listener(listener: StateListener) -> None:
    if listener in _PERSISTENT_LISTENERS:
        _PERSISTENT_LISTENERS.remove(listener)
    if _GATEWAY is not None:
        _GATEWAY.remove_listener(listener)


#: Listener **phụ thuộc vào xe**: mỗi chiếc xe cần một instance riêng, không dùng chung
#: được. `_PERSISTENT_LISTENERS` ở trên giữ những listener dùng chung cho cả hệ; cái này
#: giữ *cách tạo ra* listener cho từng xe.
#:
#: Vì sao là sổ đăng ký chứ không phải để `main.py` tự gắn khi dựng cổng: đó đúng là cái
#: bẫy PR #77 — `ASGITransport` mà phần lớn test API dùng **không chạy lifespan**, nên
#: mọi thứ gắn trong lifespan là vô hình với test, và một cổng dựng lười sau
#: `reset_vehicle_gateway()` sẽ ra đời trần trụi. Đăng ký ở mức module thì mọi cổng, dù
#: ra đời bằng đường nào, đều nhận đủ listener.
_LISTENER_FACTORIES: list[Callable[[str], StateListener]] = []


def add_state_listener_factory(factory: Callable[[str], StateListener]) -> None:
    """Đăng ký cách tạo listener cho **mỗi** xe. Gọi lại là không thêm trùng.

    **Yêu cầu bắt buộc: factory phải trả về cùng một object cho cùng một `vehicle_id`.**
    Gỡ listener làm bằng cách gọi lại factory rồi `remove_listener`, nên một factory
    sinh object mới mỗi lần sẽ không gỡ được gì và cache tích listener của những cổng đã
    chết — đúng thứ `test_thay_gateway_thi_go_listener_cua_cai_cu` canh. Emitter của
    `ui.policy` đạt yêu cầu này nhờ `_EMITTERS` cache theo xe.
    """
    if factory not in _LISTENER_FACTORIES:
        _LISTENER_FACTORIES.append(factory)


def _attach_factories(vehicle_id: str, gateway: VehicleGateway) -> None:
    for factory in _LISTENER_FACTORIES:
        gateway.add_listener(factory(vehicle_id))


def _detach_factories(vehicle_id: str, gateway: VehicleGateway) -> None:
    for factory in _LISTENER_FACTORIES:
        gateway.remove_listener(factory(vehicle_id))


def _attach_persistent(gateway: VehicleGateway) -> None:
    for listener in _PERSISTENT_LISTENERS:
        gateway.add_listener(listener)


def _detach_persistent(gateway: VehicleGateway) -> None:
    for listener in _PERSISTENT_LISTENERS:
        gateway.remove_listener(listener)


def get_vehicle_gateway() -> VehicleGateway:
    """Cổng đang dùng. Chưa ai đặt thì dựng bản in-process.

    Cổng dựng lười cũng phải nhận listener của ứng dụng: sau `reset_vehicle_gateway()`
    (mỗi test, và lúc shutdown) thì đây là đường duy nhất cổng mới ra đời.
    """
    global _GATEWAY
    if _GATEWAY is None:
        from src.config import get_settings

        _GATEWAY = InProcessVehicleGateway.new(get_settings().vehicle_id)
        _attach_persistent(_GATEWAY)
        _attach_factories(get_settings().vehicle_id, _GATEWAY)
    return _GATEWAY


def _close_current() -> None:
    """Gỡ tài nguyên của cổng đang giữ, nếu nó có gì để gỡ.

    Chỉ `MqttVehicleGateway` mới đăng ký listener vào cache; bản in-process
    không có gì. Kiểm bằng `hasattr` thay vì `isinstance` để `VehicleGateway`
    Protocol không phải mọc thêm `close()` mà hai implementation chỉ dùng một.
    """
    if _GATEWAY is None:
        return
    # Gỡ listener của ứng dụng khỏi cổng sắp bị bỏ — "cleanup listener khi shutdown"
    # trong review PR #77. Không gỡ thì một cổng đã chết vẫn giữ tham chiếu tới emitter.
    _detach_persistent(_GATEWAY)
    from src.config import get_settings

    _detach_factories(get_settings().vehicle_id, _GATEWAY)
    if hasattr(_GATEWAY, "close"):
        _GATEWAY.close()


def set_vehicle_gateway(gateway: VehicleGateway) -> None:
    """Thay cổng. Cổng cũ được gỡ listener trước khi bị bỏ, cổng mới nhận lại chúng.

    Không gỡ thì cache tích listener của những gateway đã chết — production một
    runtime một tiến trình nên không lộ, test thì lộ.

    Không **gắn lại** thì tệ hơn nhiều và ngược chiều: production im lặng mất listener
    (lifespan luôn thay cổng), còn test thì không, nên bộ test không bao giờ báo.
    """
    from src.config import get_settings

    global _GATEWAY
    _close_current()
    _GATEWAY = gateway
    _attach_persistent(gateway)
    _attach_factories(get_settings().vehicle_id, gateway)


#: Cổng của các xe **ngoài** ô số 0. Xe ô số 0 (`settings.vehicle_id`) vẫn nằm ở
#: `_GATEWAY` như cũ, không đụng vào.
#:
#: Vì sao tách hai chỗ thay vì gộp `_GATEWAY` vào dict này: `get_vehicle_gateway()` /
#: `set_vehicle_gateway()` là đường đi của **toàn bộ** hệ hiện tại và của hơn hai nghìn
#: test. Gộp lại là viết lại đường đó, đổi lại không mua thêm gì — pool chỉ cần một chỗ
#: để cất những chiếc xe mới. Bất biến giữ hai chỗ khỏi lệch nhau:
#: `get_gateway_for(settings.vehicle_id)` **luôn** trả về đúng object mà
#: `get_vehicle_gateway()` trả về, không phải một bản sao.
_GATEWAYS: dict[str, VehicleGateway] = {}


def get_gateway_for(vehicle_id: str) -> VehicleGateway:
    """Cổng của một xe cụ thể trong pool.

    Ô số 0 đi qua `get_vehicle_gateway()` để mọi thứ đang trỏ vào nó (màn kỹ sư,
    `probe_vehicle_simulator`, healthcheck compose) thấy **cùng một object**.

    Xe chưa ai đăng ký thì dựng bản in-process, đúng như `get_vehicle_gateway()` đã làm
    cho ô số 0: `MQTT_ENABLED=false` là lựa chọn tường minh của người vận hành, và pool
    phải chạy được ở chế độ đó.

    **Không** gắn `_PERSISTENT_LISTENERS` vào cổng của xe ngoài ô số 0: sổ đăng ký đó
    hiện giữ một `UiPolicyEmitter` **dùng chung**, mà emitter thì có trạng thái `_last`
    riêng cho từng xe. Gắn một emitter vào N cổng là để nó nhìn N chiếc xe rồi phát ra
    một chính sách trộn lẫn. `ui_policy` được sửa thành một-emitter-một-xe ở bước sau.
    """
    from src.config import get_settings

    if vehicle_id == get_settings().vehicle_id:
        return get_vehicle_gateway()
    gateway = _GATEWAYS.get(vehicle_id)
    if gateway is None:
        gateway = InProcessVehicleGateway.new(vehicle_id)
        _attach_factories(vehicle_id, gateway)
        _GATEWAYS[vehicle_id] = gateway
    return gateway


def set_gateway_for(vehicle_id: str, gateway: VehicleGateway) -> None:
    """Đặt cổng cho một xe. Ô số 0 đi qua `set_vehicle_gateway()`, giữ nguyên hành vi cũ."""
    from src.config import get_settings

    if vehicle_id == get_settings().vehicle_id:
        set_vehicle_gateway(gateway)
        return
    cu = _GATEWAYS.get(vehicle_id)
    if cu is not None:
        _detach_factories(vehicle_id, cu)
        if hasattr(cu, "close"):
            cu.close()
    _attach_factories(vehicle_id, gateway)
    _GATEWAYS[vehicle_id] = gateway


def reset_vehicle_gateway() -> None:
    """Dọn giữa các test và lúc shutdown.

    Dọn **cả** pool: một cổng MQTT sót lại giữ listener trên cache của nó, và ở test thì
    nó rò sang case sau.
    """
    global _GATEWAY
    _close_current()
    _GATEWAY = None
    for vehicle_id, gateway in _GATEWAYS.items():
        _detach_factories(vehicle_id, gateway)
        if hasattr(gateway, "close"):
            gateway.close()
    _GATEWAYS.clear()

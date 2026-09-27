"""Fail-closed khi không đọc được trạng thái xe.

Đây là nhánh an toàn quan trọng nhất mà `VehicleGateway` mở ra: cổng MQTT trả `None`
khi xe ảo chưa sẵn sàng, và lúc đó **không được đoán**. Phân loại S2 hay S3 phụ thuộc
`motion.speed_kph == 0 && gear == "P"`; giả định `speed_kph=0` sẽ biến một lệnh mở cửa
lẽ ra phải chặn thẳng thành một thẻ xác nhận — đúng loại lỗi mà docs/safety_and_hitl.md
tồn tại để chặn.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.agents.nodes.safety import safety_node
from src.services.ivi_events import emit_turn_lifecycle
from src.services.vehicle_gateway import InProcessVehicleGateway

CONFIG = {"configurable": {"thread_id": "ses-1"}}


class _BlindGateway:
    """Cổng không đọc được state — đúng hành vi `MqttVehicleGateway` khi broker chết.

    Bọc một cổng in-process thật để `execute()` vẫn đếm được lệnh: nếu graph lỡ chạy
    lệnh nào thì test bắt được, thay vì nổ ra một lỗi khác rồi ta tưởng là fail-closed.
    """

    def __init__(self) -> None:
        self._real = InProcessVehicleGateway.new()
        self.vehicle_id = self._real.vehicle_id

    async def snapshot(self):
        return None

    async def last_known(self):
        return None

    def readiness(self):
        return self._real.readiness()

    async def execute(self, **kwargs):
        return await self._real.execute(**kwargs)

    def add_listener(self, listener):
        self._real.add_listener(listener)

    def remove_listener(self, listener):
        self._real.remove_listener(listener)

    @property
    def command_count(self) -> int:
        return self._real.command_count


class _RecordingBus:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, session_id, event_type, turn_id, trace_id, payload):
        self.events.append({"type": event_type, "payload": payload})


async def test_safety_node_refuses_when_the_snapshot_is_empty():
    """Không có state thì không phân loại được S0-S3 — từ chối, đừng đoán."""
    result = await safety_node({"vehicle_snapshot": {}, "candidate_action_plan": None})

    assert result == {"outcome": "vehicle_state_unavailable"}


async def test_a_control_turn_executes_nothing_when_state_is_unreadable():
    gateway = _BlindGateway()
    graph = build_graph(gateway, approvals=ApprovalStore(), checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        {"query": "Mở cửa sổ bên lái 30 phần trăm", "session_id": "ses-1", "vehicle_id": "veh-1"},
        config=CONFIG,
    )

    assert result["outcome"] == "vehicle_state_unavailable"
    assert gateway.command_count == 0


async def test_unreadable_state_ends_the_turn_as_failed_not_canceled():
    """Lỗi hệ thống, không phải lượt bị ai huỷ — nên `turn.failed`, không `turn.canceled`."""
    bus = _RecordingBus()

    await emit_turn_lifecycle(
        bus, "ses-1", "turn-1", "tr-1", {"outcome": "vehicle_state_unavailable", "response_text": "..."}
    )

    types = [event["type"] for event in bus.events]
    assert types[-1] == "turn.failed"
    assert bus.events[-1]["payload"]["code"] == "MQTT_UNAVAILABLE"
    assert "turn.canceled" not in types


async def test_approval_resume_fails_closed_when_state_cannot_be_read():
    """Nhánh fail-closed thứ năm, cùng họ với bốn nhánh sẵn có của node approval.

    Lượt xin phép thành công lúc xe còn đọc được, rồi broker chết trước khi người dùng
    bấm duyệt. Không đọc được state thì không có cách nào khẳng định approval còn hợp lệ.
    """
    real = InProcessVehicleGateway.new()
    store = ApprovalStore()
    graph = build_graph(real, approvals=store, checkpointer=InMemorySaver())
    approval_id = (
        await graph.ainvoke(
            {"query": "Mở cửa sổ bên lái 30 phần trăm", "session_id": "ses-1", "vehicle_id": "veh-1"},
            config=CONFIG,
        )
    )["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)

    # Xe biến mất đúng lúc chờ duyệt.
    async def _blind():
        return None

    real.snapshot = _blind

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)

    assert result["outcome"] == "approval_invalidated_state"
    assert real.command_count == 0

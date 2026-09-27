"""Lượt hỏng không được kết thúc bằng `turn.completed` (issue #375).

Triệu chứng đo được trước bản vá, trên một lượt `"Tìm các quán cà phê gần đây"`:

    envelope: {"status": "completed"}
    trace:    {"status": "completed",
               "safe_summary": "Đã trả lời, không tác động tới xe",
               "safety_summary": {"outcome": "validation_denied"}}

Kỹ sư mở `/traces` nhìn dòng đầu không thấy gì bất thường, và `/metrics/summary` — fold
theo `status` — đếm lượt ấy là thành công.

Quyết định PM/PO trên #375: `validation_denied` và `execution_failed` phát `turn.failed`
kèm mã lỗi; `clarify` / `denied` / `not_control` / `grounded_refusal` vẫn `completed`.

Bộ test đi qua **bus thật** (`emit_turn_lifecycle`) rồi mới tới collector, đúng đường mà
một lượt thật đi — chứ không bơm thẳng `turn.completed` vào collector như bản đầu. Đó là
khác biệt quan trọng: sau khi sửa ở tầng phát, một test bơm thẳng sự kiện sẽ đo một
đường không còn tồn tại.
"""

import pytest

from src.agents.contracts import ActionPlan, PlanStep, ToolResult
from src.services.engineer_events import EngineerEventBus
from src.services.ivi_events import OUTCOME_LUOT_HONG, IviEventBus, emit_turn_lifecycle
from src.services.trace_collector import TraceCollector, record_graph_result
from src.services.trace_store import TraceStore

#: Outcome kết thúc **bình thường**: hệ trả lời đúng thứ nó nên trả lời, chỉ là không
#: chạm vào xe. Đây là vế giữ cho bản vá không nở ra — gọi chúng là hỏng sẽ biến mọi lượt
#: hỏi sổ tay thành một lượt lỗi trên dashboard kỹ sư.
KET_THUC_BINH_THUONG = ("not_control", "clarify", "denied", "grounded_answer", "grounded_refusal", "offer", "chitchat")


class BusGhi(IviEventBus):
    """Bus thật, có thêm sổ ghi. Kế thừa để giữ nguyên mọi hành vi khác của bus."""

    def __init__(self) -> None:
        super().__init__()
        self.da_phat: list[tuple[str, dict]] = []

    async def publish(self, session_id, event_type, turn_id, trace_id, payload):  # type: ignore[override]
        self.da_phat.append((event_type, payload))

    def terminal(self) -> list[tuple[str, str]]:
        return [(e, p.get("code", "")) for e, p in self.da_phat if e.startswith("turn.")]


def _plan(safety: str = "S1") -> ActionPlan:
    return ActionPlan(
        plan_id="plan-1",
        session_id="s",
        vehicle_id="v",
        vehicle_state_version=1,
        steps=(PlanStep(step_id="step-1", ordinal=0, tool="set_hvac_power", args={"enabled": True}, safety_level=safety),),
        requires_approval=False,
    )


def _buoc(status: str) -> ToolResult:
    return ToolResult(
        command_id="c1",
        step_id="step-1",
        tool="set_hvac_power",
        args={"enabled": True},
        status=status,
        before={},
        after={},
        observed_state_version=2,
        error_code=None if status == "completed" else "actuator_error",
    )


def _ket_qua(outcome: str) -> dict:
    """`result` của graph cho một outcome. Ca có `action_plan` đi nhánh sớm, ca không có
    rơi xuống nhánh cuối — đúng chỗ #375 nói tới."""
    base: dict = {"outcome": outcome, "response_text": "…"}
    if outcome in ("completed", "execution_failed"):
        base["action_plan"] = _plan()
        base["step_results"] = [_buoc("completed" if outcome == "completed" else "failed")]
    if outcome == "blocked":
        base["action_plan"] = _plan("S3")
    return base


async def _phat(outcome: str) -> BusGhi:
    bus = BusGhi()
    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", _ket_qua(outcome))
    return bus


# --- tính chất PM/PO yêu cầu -------------------------------------------------


@pytest.mark.parametrize("outcome", sorted(OUTCOME_LUOT_HONG))
async def test_luot_hong_khong_bao_gio_phat_turn_completed(outcome):
    """Acceptance của #375, viết đúng như PM/PO đặt ra.

    Khoá theo **tính chất** chứ không theo ca: danh sách chạy từ chính
    `OUTCOME_LUOT_HONG`, nên thêm một outcome vào đó mà quên đường phát sẽ đỏ ngay.
    """
    bus = await _phat(outcome)

    assert ("turn.completed", "") not in bus.terminal(), bus.terminal()
    assert bus.terminal() == [("turn.failed", OUTCOME_LUOT_HONG[outcome])]


@pytest.mark.parametrize("outcome", KET_THUC_BINH_THUONG)
async def test_ket_thuc_binh_thuong_van_la_completed(outcome):
    bus = await _phat(outcome)

    assert bus.terminal() == [("turn.completed", "")]


async def test_blocked_van_la_completed():
    """S3 chặn là một **quyết định an toàn đúng**, không phải lượt hỏng — PM/PO chốt
    `denied`/`blocked` giữ nguyên `completed`."""
    bus = await _phat("blocked")

    assert bus.terminal() == [("turn.completed", "")]


async def test_vehicle_state_unavailable_giu_ma_rieng():
    """Ngoài phạm vi #375 và **đã** phát `turn.failed` từ trước, với mã hạ tầng riêng.

    Test này canh chiều ngược: bản vá không được nuốt nó vào mã chung.
    """
    bus = await _phat("vehicle_state_unavailable")

    assert bus.terminal() == [("turn.failed", "MQTT_UNAVAILABLE")]


def test_danh_sach_dung_hai_outcome_ma_pm_po_chot():
    """Khoá phạm vi: danh sách là quyết định sản phẩm, không phải chỗ để thêm dần.

    `vehicle_state_unavailable` cố ý **không** có mặt — PM/PO chốt nó ngoài phạm vi đợt
    này, và nó có mã lỗi riêng.
    """
    assert OUTCOME_LUOT_HONG == {
        "validation_denied": "VALIDATION_DENIED",
        "execution_failed": "EXECUTION_FAILED",
    }


# --- hệ quả trên trace và metrics -------------------------------------------


async def _mot_luot_qua_collector(outcome: str, *, trace_id: str) -> TraceStore:
    """Chuỗi thật: `record_graph_result` trước, rồi `emit_turn_lifecycle` bơm vào collector.

    Đúng thứ tự `turns.py` gọi — comment ở đó ghi rõ thứ tự ấy là cố ý.
    """
    store = TraceStore()
    collector = TraceCollector(store=store, bus=EngineerEventBus())
    store.open(trace_id, "ses-1", "turn-1")
    record_graph_result(trace_id, {"outcome": outcome, "route_source": "deterministic"}, store=store)

    bus = IviEventBus()
    bus.add_global_listener(collector)
    await emit_turn_lifecycle(bus, "ses-1", "turn-1", trace_id, _ket_qua(outcome))
    return store


async def test_trace_ghi_failed_cho_luot_validation_denied():
    store = await _mot_luot_qua_collector("validation_denied", trace_id="tr_hong")

    ban_ghi = store.get("tr_hong")
    assert ban_ghi.outcome == "validation_denied"
    assert ban_ghi.status == "failed"
    assert ban_ghi.block_code == "VALIDATION_DENIED"


async def test_trace_van_ghi_completed_cho_luot_tra_loi_binh_thuong():
    store = await _mot_luot_qua_collector("grounded_refusal", trace_id="tr_tot")

    assert store.get("tr_tot").status == "completed"


async def test_metrics_dem_luot_hong_vao_cot_failed():
    """Hệ quả thật của bản vá, và là lý do nó đáng làm.

    `_turns` của `/metrics/summary` fold theo `record.status`, nên trước vá một lượt plan
    hỏng được đếm vào cột `completed` — một con số sai trông y hệt một con số đúng. PM/PO
    đã chấp nhận trước: *"kiểm lại /metrics/summary sau vá và chấp nhận success giảm nếu
    trước đó đang đếm sai"*.
    """
    from datetime import UTC, datetime, timedelta

    from src.services.metrics import _turns

    store = await _mot_luot_qua_collector("validation_denied", trace_id="tr_hong")
    collector = TraceCollector(store=store, bus=EngineerEventBus())
    store.open("tr_tot", "ses-1", "turn-2")
    record_graph_result("tr_tot", {"outcome": "grounded_answer"}, store=store)
    bus = IviEventBus()
    bus.add_global_listener(collector)
    await emit_turn_lifecycle(bus, "ses-1", "turn-2", "tr_tot", _ket_qua("grounded_answer"))

    bay_gio = datetime.now(UTC)
    dem = _turns(store.records_between(bay_gio - timedelta(hours=1), bay_gio + timedelta(minutes=1)))

    assert dem.failed == 1
    assert dem.completed == 1

"""`TraceCollector` dựng trace từ luồng sự kiện của `IviEventBus`."""

from __future__ import annotations

import pytest

from src.config import get_settings
from src.services.engineer_events import EngineerEventBus
from src.services.ivi_events import IviEventBus
from src.services.trace_collector import TraceCollector, record_graph_result
from src.services.trace_store import TraceStore
from src.services.trace_view import to_trace_data


@pytest.fixture
def store():
    return TraceStore(maxsize=16)


@pytest.fixture
def engineer_bus():
    return EngineerEventBus()


@pytest.fixture
def collector(store, engineer_bus):
    return TraceCollector(store=store, bus=engineer_bus)


def event(event_type: str, payload: dict, *, trace_id: str = "tr_1") -> dict:
    return {
        "type": event_type,
        "session_id": "ses-1",
        "turn_id": "turn-1",
        "trace_id": trace_id,
        "payload": payload,
    }


async def feed(collector, events: list[dict]) -> None:
    for item in events:
        await collector(item)


async def test_luot_dieu_khien_thanh_cong_dung_du_field(collector, store):
    await feed(
        collector,
        [
            event("turn.accepted", {"status": "accepted", "input_mode": "voice"}),
            event("transcript.final", {"text": "bật điều hòa", "confidence": 0.93}),
            event("plan.ready", {"plan_id": "plan-1", "requires_approval": False}),
            event("assistant.status", {"state": "executing"}),
            event("tool.result", {"step_id": "step-1", "status": "completed", "observed_state_version": 42}),
            event("assistant.response", {"display_text": "Đã bật.", "citations": []}),
            event("turn.completed", {"status": "completed"}),
        ],
    )

    record = store.get("tr_1")
    assert record is not None
    assert record.status == "completed"
    assert record.is_sealed
    assert record.plan_id == "plan-1"
    assert record.step_statuses == ("completed",)
    assert record.actual_vehicle_state_version == 42
    assert record.transcript_confidence == 0.93
    assert record.admission_status == "executed"


async def test_luot_khong_co_buoc_nao_thi_admission_la_not_applicable(collector, store):
    """Tra sổ tay không chạm executor — gọi nó `executed` sẽ làm action_audit nói dối."""
    await feed(
        collector,
        [
            event("turn.accepted", {}),
            event("assistant.status", {"state": "retrieving"}),
            event("assistant.response", {"display_text": "...", "citations": [{"page": 12}]}),
            event("turn.completed", {"status": "completed"}),
        ],
    )

    record = store.get("tr_1")
    assert record.admission_status == "not_applicable"
    assert record.citation_count == 1


async def test_luot_bi_chan_giu_admission_blocked_du_ket_thuc_bang_turn_completed(collector, store):
    """`action.blocked` vẫn đi kèm `turn.completed` — xem `emit_turn_lifecycle`."""
    await feed(
        collector,
        [
            event("turn.accepted", {}),
            event("action.blocked", {"plan_id": "plan-9", "code": "SAFETY_BLOCKED", "reason": "Xe đang chạy."}),
            event("turn.completed", {"status": "completed"}),
        ],
    )

    record = store.get("tr_1")
    assert record.admission_status == "blocked"
    assert record.block_code == "SAFETY_BLOCKED"
    assert record.max_safety_level == "S3"


async def test_cho_duyet_ghi_pending_approval_va_status(collector, store):
    await feed(
        collector,
        [
            event("turn.accepted", {}),
            event(
                "approval.required",
                {
                    "approval_id": "appr-1",
                    "plan_id": "plan-2",
                    "approved_vehicle_state_version": 7,
                    "actions": [{"tool": "set_window_position"}],
                    "expires_at": "2026-08-10T10:00:30Z",
                },
            ),
            event("assistant.status", {"state": "waiting_approval"}),
        ],
    )

    record = store.get("tr_1")
    assert record.status == "waiting_approval"
    assert record.approval_id == "appr-1"
    assert record.admission_status == "pending"
    assert record.tool_names == ("set_window_position",)
    assert not record.is_sealed


async def test_hai_duong_thoat_loi_cua_turns_py_deu_seal(collector, store):
    """Đây là lý do chính chọn nghe bus thay vì sửa `emit_turn_lifecycle`.

    `STT_FAILED` và `INTERNAL_ERROR` publish `turn.failed` thẳng lên bus và **không**
    đi qua `emit_turn_lifecycle`. Seal bên trong hàm đó sẽ đếm thiếu `turns.failed`.
    """
    await feed(
        collector,
        [
            event("turn.accepted", {}),
            event("transcript.final", {"text": "", "confidence": 0.0}),
            event("error", {"code": "STT_FAILED", "message": "audio hỏng"}),
            event("turn.failed", {"status": "failed", "code": "STT_FAILED"}),
        ],
    )
    await feed(
        collector,
        [
            event("turn.accepted", {}, trace_id="tr_2"),
            event("error", {"code": "INTERNAL_ERROR", "message": "..."}, trace_id="tr_2"),
            event("turn.failed", {"status": "failed", "code": "INTERNAL_ERROR"}, trace_id="tr_2"),
        ],
    )

    assert store.get("tr_1").status == "failed"
    assert store.get("tr_1").block_code == "STT_FAILED"
    assert store.get("tr_2").block_code == "INTERNAL_ERROR"


async def test_su_kien_khong_co_turn_accepted_thi_bo_qua_chu_khong_tao_ban_ghi(collector, store):
    """Sự kiện mồ côi (trace đã bị LRU đẩy ra) không được đẻ bản ghi thiếu `opened_at`."""
    await feed(collector, [event("tool.result", {"status": "completed"}, trace_id="tr_la")])

    assert store.get("tr_la") is None


async def test_seal_phat_event_trace_cho_bus_engineer(collector, store, engineer_bus):
    received: list[tuple[str, dict]] = []

    async def listener(event_type: str, payload: dict) -> None:
        received.append((event_type, payload))

    engineer_bus.add_listener(listener)
    await feed(collector, [event("turn.accepted", {}), event("turn.completed", {"status": "completed"})])

    assert [name for name, _ in received] == ["trace"]
    payload = received[0][1]
    assert payload["trace_id"] == "tr_1"
    assert payload["status"] == "completed"


async def test_collector_nuot_loi_de_khong_lam_gay_giao_hang_cho_ws_ivi(collector, store):
    """Quan sát không được phép làm hỏng sản phẩm."""
    await collector({"type": "tool.result", "trace_id": "tr_1", "payload": "không phải dict"})


async def test_luu_cau_tra_loi_nhung_khong_luu_cau_hoi(collector, store):
    """Ràng buộc redaction là cấu trúc, không phải kỷ luật — api_spec.md:11,445.

    Danh sách cấm của spec là *unrestricted transcripts*, tức lời **tài xế**. Câu
    VIVI trả lời do server sinh nên được lưu (ADR-029). Test khoá cả hai chiều: mất
    chiều nào cũng là vỡ hợp đồng, chỉ khác nhau ở chỗ vỡ về phía nào.
    """
    await feed(
        collector,
        [
            event("turn.accepted", {}),
            event("transcript.final", {"text": "BÍ MẬT CỦA TÀI XẾ", "confidence": 0.9}),
            event("assistant.response", {"display_text": "Đã đặt điều hòa ở 22 độ.", "citations": []}),
            event("turn.completed", {"status": "completed"}),
        ],
    )

    record = store.get("tr_1")
    assert "BÍ MẬT" not in repr(record)
    assert record.answer_text == "Đã đặt điều hòa ở 22 độ."


async def test_global_listener_nhan_su_kien_cua_moi_session(store, engineer_bus):
    """Hook `add_global_listener` là phụ thuộc chặn duy nhất của tầng observability."""
    bus = IviEventBus()
    collector = TraceCollector(store=store, bus=engineer_bus)
    bus.add_global_listener(collector)

    await bus.publish("ses-a", "turn.accepted", "turn-a", "tr_a", {})
    await bus.publish("ses-b", "turn.accepted", "turn-b", "tr_b", {})

    assert store.get("tr_a").session_id == "ses-a"
    assert store.get("tr_b").session_id == "ses-b"

    bus.remove_global_listener(collector)
    await bus.publish("ses-c", "turn.accepted", "turn-c", "tr_c", {})
    assert store.get("tr_c") is None


# --------------------------------------------------------------- record_graph_result


class _Step:
    def __init__(self, safety_level: str) -> None:
        self.safety_level = safety_level


class _Plan:
    def __init__(self, *levels: str) -> None:
        self.steps = [_Step(level) for level in levels]


async def test_max_safety_level_lay_tu_plan_chu_khong_mac_dinh_s0(collector, store):
    """Lượt S1 **có tác động tới xe** không được hiện `max_level: S0`.

    Không sự kiện nào trên `/ws/ivi` mang mức an toàn, nên thiếu bước này thì trace
    điền một giá trị sai mà trông vẫn đáng tin — tệ hơn hẳn một ô trống.
    """
    await feed(collector, [event("turn.accepted", {})])
    record_graph_result("tr_1", {"outcome": "completed", "action_plan": _Plan("S0", "S1")}, store=store)

    assert store.get("tr_1").max_safety_level == "S1"
    assert to_trace_data(store.get("tr_1"), get_settings()).safety_summary.max_level == "S1"


async def test_route_source_rong_cua_normalize_khong_lam_no_trace(collector, store):
    """`normalize_node` reset `route_source` về `""` — giá trị đó phải bị bỏ, không lọt.

    Lọt vào `Literal` của `TraceData` thì `GET /traces/{id}` trả 500 và event `trace`
    biến mất im lặng (collector nuốt exception).
    """
    await feed(collector, [event("turn.accepted", {})])
    record_graph_result("tr_1", {"route_source": "", "confidence": 0.87}, store=store)

    assert store.get("tr_1").route_source is None
    assert to_trace_data(store.get("tr_1"), get_settings()).route_source is None

    record_graph_result("tr_1", {"route_source": "deterministic"}, store=store)
    assert to_trace_data(store.get("tr_1"), get_settings()).route_source == "deterministic"


async def test_validation_denied_phan_biet_duoc_voi_luot_thuong(collector, store):
    """`emit_turn_lifecycle` phát **cùng một** chuỗi sự kiện cho `validation_denied`
    và `not_control`, nên chỉ `result` của graph mới tách được hai cái."""
    await feed(collector, [event("turn.accepted", {})])
    record_graph_result("tr_1", {"outcome": "validation_denied"}, store=store)
    await feed(collector, [event("turn.completed", {"status": "completed"})])

    assert to_trace_data(store.get("tr_1"), get_settings()).safety_summary.validation == "denied"


async def test_record_graph_result_khong_lay_van_ban_nao(collector, store):
    """Hàm này đọc `result` — nơi CÓ câu người dùng nói. Nó chỉ được chạm 5 khoá."""
    await feed(collector, [event("turn.accepted", {})])
    record_graph_result(
        "tr_1",
        {
            "query": "BÍ MẬT CỦA TÀI XẾ",
            "normalized_text": "BÍ MẬT ĐÃ CHUẨN HOÁ",
            "response_text": "TRẢ LỜI BÍ MẬT",
            "outcome": "completed",
        },
        store=store,
    )

    assert "BÍ MẬT" not in repr(store.get("tr_1"))


async def test_record_graph_result_khong_bao_gio_lam_gay_luot(collector, store):
    """Quan sát không được phép ném lỗi lên đường xử lý lượt của tài xế."""
    await feed(collector, [event("turn.accepted", {})])
    record_graph_result("tr_1", {"action_plan": object()}, store=store)
    record_graph_result("tr_khong_ton_tai", {"outcome": "completed"}, store=store)

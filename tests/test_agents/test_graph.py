"""Graph lắp ráp. Mỗi test là một đường đi trọn vẹn từ câu tiếng Việt tới outcome."""

import pytest

from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict


async def _run(vehicle: InProcessVehicleGateway, text: str, rag=None):
    graph = build_graph(vehicle, rag=rag)
    return await graph.ainvoke({"query": text, "session_id": "ses-1", "vehicle_id": "veh-1", "turn_id": "turn-1"})


async def test_s1_command_executes_directly():
    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Đặt điều hòa 22 độ")
    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["hvac"]["temperature_c"] == 22
    assert vehicle.command_count == 1
    assert result["response_text"]


async def test_s2_without_an_approval_store_still_never_executes():
    """HITL là opt-in. Không truyền `approvals` thì S2 dừng ở `approval_required`.

    Điều quan trọng là nó **không thực thi**. Đường xin xác nhận nằm ở
    `tests/test_agents/test_hitl_node.py`.
    """
    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Mở cửa sổ bên lái 30 phần trăm")
    assert result["outcome"] == "approval_required"
    assert vehicle.command_count == 0
    assert snapshot_dict(vehicle.state)["windows"]["front_left"] == 0


async def test_s3_is_blocked_with_zero_side_effect():
    vehicle = InProcessVehicleGateway.new(speed_kph=45.0, gear="D")
    result = await _run(vehicle, "Mở cửa bên lái")
    assert result["outcome"] == "blocked"
    assert vehicle.command_count == 0
    assert snapshot_dict(vehicle.state)["doors"]["front_left"] == "closed"


async def test_manual_question_reaches_rag_node():
    seen = {}

    async def fake_rag(state):
        seen["query"] = state["query"]
        return {"citations": [{"chunk_id": "c1"}], "evidence": [{"text": "..."}]}

    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Điều hòa hoạt động như thế nào?", rag=fake_rag)
    assert seen["query"] == "Điều hòa hoạt động như thế nào?"
    assert result["outcome"] == "grounded_answer"
    assert vehicle.command_count == 0


async def test_ambiguous_request_asks_for_clarification():
    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Đặt điều hòa")
    assert result["outcome"] == "clarify"
    assert vehicle.command_count == 0


async def test_denied_request_never_reaches_executor():
    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Đặt điều hòa 45 độ")
    assert result["outcome"] == "denied"
    assert vehicle.command_count == 0


@pytest.mark.parametrize("text", ["Tắt đèn", "Bật đèn", "Tắt hết đèn", "Tắt đèn đi"])
async def test_ambiguous_light_command_touches_neither_light(text):
    """Xe có hai loại đèn điều khiển được, nên câu trống là mơ hồ **thật**: đoán bừa
    một trong hai là làm một việc khác việc được yêu cầu mà không nói ra — KI-001.

    `test_router.py` đã khoá việc router trả `clarify`, nhưng đó mới là *ý định*.
    Ở đây khoá **hệ quả**: đi hết graph mà không actuator nào nhận lệnh. Hai chuyện
    này tách rời được — một `route_node` đúng vẫn có thể đi kèm executor chạy nhầm
    trên state cũ, và không test nào hiện có bắt được điều đó cho domain đèn.
    """
    vehicle = InProcessVehicleGateway.new()
    truoc = snapshot_dict(vehicle.state)["lights"]
    result = await _run(vehicle, text)
    assert result["outcome"] == "clarify"
    assert vehicle.command_count == 0
    assert not result.get("action_plan")
    # So với chính snapshot đầu vào, không viết cứng `auto`/`False`: đổi mặc định của
    # simulator không được biến test an toàn này thành đỏ giả.
    assert snapshot_dict(vehicle.state)["lights"] == truoc


async def test_headlight_off_is_denied_with_zero_side_effect():
    """Nhánh còn lại của cùng một yêu cầu: `"tắt đèn pha"` **đủ** ngữ cảnh nên không
    hỏi lại, nhưng enum `headlight` cố ý không có `off` (UNECE R48, ADR-020).

    Từ chối mà vẫn kịp phát lệnh `auto` xuống xe thì đúng bằng việc ánh xạ ngầm —
    thứ ADR-020 tồn tại để cấm. Chốt luôn cả `state_version` vì `command_count`
    chỉ đếm lệnh đi qua gateway, còn đây hỏi: xe có nhúc nhích không.
    """
    vehicle = InProcessVehicleGateway.new()
    truoc = snapshot_dict(vehicle.state)
    result = await _run(vehicle, "Tắt đèn pha")
    assert result["outcome"] == "denied"
    assert vehicle.command_count == 0
    sau = snapshot_dict(vehicle.state)
    assert sau["lights"] == truoc["lights"]
    assert sau["state_version"] == truoc["state_version"]


async def test_state_carries_canonical_plan_not_alias():
    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Phát nhạc")
    assert result["action_plan"].steps[0].tool == "media_control"
    assert result["action_plan"].steps[0].safety_level == "S1"


async def test_graph_is_rebuilt_per_call_not_a_module_singleton():
    """Hai simulator độc lập không được dùng chung state."""
    first, second = InProcessVehicleGateway.new(), InProcessVehicleGateway.new()
    await _run(first, "Đặt điều hòa 22 độ")
    assert snapshot_dict(second.state)["hvac"]["temperature_c"] == 27


async def test_missing_rag_index_refuses_instead_of_crashing():
    """Sau ADR-011 đây là đường mặc định — sập là không chấp nhận được.

    faiss ném RuntimeError khi thiếu index.faiss; bản cũ chỉ bắt OSError/ValueError
    nên lỗi lọt lên thành HTTP 500.
    """

    async def exploding_rag(state):
        raise RuntimeError("could not open data/rag/vf9_2026_vi/index.faiss for reading")

    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Cách khởi tạo lại cửa sổ điện?", rag=exploding_rag)
    assert result["outcome"] == "grounded_refusal"
    assert result["response_text"]
    assert vehicle.command_count == 0


async def test_unmatched_sentence_reaches_rag_after_adr_010():
    seen = {}

    async def fake_rag(state):
        seen["query"] = state["query"]
        return {"citations": [], "evidence": [], "refusal_reason": "insufficient_evidence"}

    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Hôm nay trời đẹp quá", rag=fake_rag)
    assert seen["query"] == "Hôm nay trời đẹp quá"
    assert result["outcome"] == "grounded_refusal"


async def test_recognised_question_without_evidence_does_not_fall_through_to_slm():
    """Câu đã nhận rõ là câu hỏi mà sổ tay không có thì dừng ở đó.

    Đưa cho SLM đoán tiếp là mời nó bịa ra câu trả lời không có căn cứ.
    """

    class ShouldNotRun:
        def propose(self, normalized_text, snapshot):
            raise AssertionError("SLM không được chạy cho câu hỏi đã nhận diện rõ")

    async def empty_rag(state):
        return {"citations": [], "evidence": [], "refusal_reason": "insufficient_evidence"}

    vehicle = InProcessVehicleGateway.new()
    graph = build_graph(vehicle, rag=empty_rag, planner=ShouldNotRun())
    result = await graph.ainvoke({"query": "Đèn chào mừng là gì?", "session_id": "s", "vehicle_id": "v"})
    assert result["outcome"] == "grounded_refusal"


async def test_genuine_rag_bug_is_not_disguised_as_missing_index():
    """Review PR #26: bắt `RuntimeError` rộng làm bug thật đội lốt "chưa có chỉ mục".

    Hai thứ phải phân biệt được: chỉ mục chưa dựng (chuyện bình thường, người dùng
    cần biết cách dựng) và lỗi lập trình trong retrieve (cần ai đó đi sửa).
    """

    async def buggy_rag(state):
        raise RuntimeError("unsupported operand type(s) for +: 'int' and 'str'")

    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Cách khởi tạo lại cửa sổ điện?", rag=buggy_rag)
    assert result["outcome"] == "grounded_refusal"
    assert result["refusal_reason"] == "retrieval_failed"
    assert "unsupported operand" in result["error"]
    assert vehicle.command_count == 0


def test_index_detection_reads_disk_not_error_strings(tmp_path):
    """Review PR #23: do chuoi "index.faiss" trong thong diep loi la brittle.

    faiss doi wording qua phien ban thi phan loai hong. Kiem bang cach doc dia.
    """
    from src.agents.nodes.rag_node import index_is_built

    assert index_is_built(tmp_path) is False
    (tmp_path / "index.faiss").write_bytes(b"")
    assert index_is_built(tmp_path) is True


async def test_permission_error_is_not_reported_as_missing_index():
    """Lỗi quyền truy cập không phải "chưa dựng chỉ mục".

    Bảo người dùng đi chạy `prepare_vf9_index.ps1` khi thật ra là lỗi quyền truy
    cập là chỉ sai hướng.
    """

    async def permission_denied_rag(state):
        raise PermissionError(13, "Permission denied", "data/rag/vf9_2026_vi/chunks.db")

    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Cách khởi tạo lại cửa sổ điện?", rag=permission_denied_rag)
    assert result["outcome"] == "grounded_refusal"
    assert result["refusal_reason"] == "retrieval_failed"
    assert vehicle.command_count == 0


# --- Ro state giua hai luot cung mot phien (phat hien khi chay demo) --------


async def _two_turns(first: str, second: str) -> dict:
    """Chạy hai lượt trên **cùng một thread**, trả state của lượt sau.

    Một phiên phải dùng chung `thread_id` vì `interrupt()` chỉ resume được trên
    đúng checkpoint đó — nên state của lượt trước còn nguyên khi lượt sau chạy.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    vehicle = InProcessVehicleGateway.new()

    async def fake_rag(state):
        return {"citations": [{"chunk_id": "c1"}], "evidence": [{"text": "..."}]}

    graph = build_graph(vehicle, rag=fake_rag, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "ses-leak"}}
    for turn, text in enumerate((first, second), start=1):
        state = await graph.ainvoke(
            {"query": text, "session_id": "ses-leak", "vehicle_id": "veh-1", "turn_id": f"turn-{turn}"},
            config=config,
        )
    return state


async def test_manual_turn_does_not_report_the_previous_turns_tool_call():
    """Lượt tra cứu sổ tay **không** được mang theo `action_plan` của lượt điều khiển trước.

    Phát hiện khi chạy demo: hỏi "Ghế xe có chức năng massage không?" ngay sau
    "Đặt điều hòa 22 độ" thì API báo lượt hỏi đó đã gọi `set_hvac_temperature`.
    Đây đúng lớp lỗi KI-001 — hệ thống báo cáo một hành động **không hề xảy ra
    trong lượt này**, và người dùng không có cách nào biết.
    """
    state = await _two_turns("Đặt điều hòa 22 độ", "Ghế xe có chức năng massage không?")
    assert state["outcome"] == "grounded_answer"
    assert not state.get("action_plan")
    assert not state.get("step_results")


async def test_control_turn_does_not_inherit_the_previous_turns_citations():
    """Ngược lại: lệnh điều khiển không được dẫn nguồn sổ tay của lượt hỏi trước."""
    state = await _two_turns("Ghế xe có chức năng massage không?", "Đặt điều hòa 22 độ")
    assert state["outcome"] == "completed"
    assert not state.get("citations")
    assert not state.get("evidence")


async def test_speak_text_di_duoc_qua_graph_khong_bi_langgraph_loai():
    """`AgentState` là `TypedDict`; LangGraph **loại im lặng** khoá không có trong schema.

    Bug thật gặp 13/08: `compose_node` trả `speak_text`, test đơn vị của composer xanh,
    nhưng `graph.ainvoke()` không bao giờ thấy khoá đó — `assistant.speech` vẫn 1.019 KB
    trên server thật. Test đơn vị ở tầng node không bắt được lớp lỗi này; phải đi qua
    graph mới thấy.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from src.agents.approval import ApprovalStore

    graph = build_graph(InProcessVehicleGateway.new(), approvals=ApprovalStore(), checkpointer=InMemorySaver())
    ket_qua = await graph.ainvoke(
        {"query": "chỉnh điều hoà 22 độ", "session_id": "ses-speak", "vehicle_id": "veh", "turn_id": "t1"},
        config={"configurable": {"thread_id": "ses-speak"}},
    )
    assert "speak_text" in ket_qua, "LangGraph đã loại khoá — thiếu khai báo trong AgentState"


# --- S3: doc tiep qua GRAPH that -------------------------------------------
#
# Test don vi cua compose khong bat duoc hai loi that su nguy hiem cua S3, va ca hai
# deu la loi "xanh o don vi, do o that" da gap trong repo nay:
#
# 1. `AgentState` la TypedDict — LangGraph LOAI BO IM LANG moi khoa khong khai trong
#    schema. compose tra `speech_offset` ma quen khai thi trang thai bien mat giua hai
#    luot, con test don vi thi van xanh (dung lop loi cua `speak_text`, PR #98).
# 2. `normalize` xoa cac kenh dan xuat moi luot. Neu hai field nay lot vao
#    `_PER_TURN_RESET` thi luot "doc tiep" luon nghe "da doc het".


async def _doc_tiep_qua_graph(doan: str) -> tuple[dict, dict]:
    """Một lượt hỏi sổ tay rồi một lượt "đọc tiếp", cùng `thread_id`."""
    from langgraph.checkpoint.memory import InMemorySaver

    from src.rag.models import Evidence

    vehicle = InProcessVehicleGateway.new()

    async def fake_rag(state):
        return {
            "outcome": "grounded_answer",
            "citations": [{"chunk_id": "c1"}],
            "evidence": [Evidence(section="Cửa sổ điện", page=3, text=doan, chunk_id="c1", score=0.9)],
        }

    graph = build_graph(vehicle, rag=fake_rag, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "ses-s3"}}
    dau = await graph.ainvoke(
        {"query": "cách khởi tạo cửa sổ điện", "session_id": "ses-s3", "vehicle_id": "v", "turn_id": "t1"},
        config=config,
    )
    tiep = await graph.ainvoke(
        {"query": "đọc tiếp", "session_id": "ses-s3", "vehicle_id": "v", "turn_id": "t2"},
        config=config,
    )
    return dau, tiep


async def test_doc_tiep_song_qua_hai_luot_trong_cung_mot_phien():
    doan = " ".join(f"Câu số {i} của đoạn sổ tay dài này nói về một bước thao tác cụ thể." for i in range(1, 12))
    dau, tiep = await _doc_tiep_qua_graph(doan)

    assert dau["speech_source_text"] == doan, "state khong song qua LangGraph — kiem AgentState"
    assert dau["speech_da_doc"], "chua ghi cau nao da doc"
    assert set(tiep["speech_da_doc"]) > set(dau["speech_da_doc"]), "luot sau khong tien — kiem _PER_TURN_RESET"
    assert tiep["speak_text"] and tiep["speak_text"] not in dau["speak_text"]
    assert tiep["speak_text"].split(" Bạn có muốn")[0].strip() in doan


async def test_doc_tiep_khong_di_qua_rag():
    """Lượt "đọc tiếp" không được truy hồi lại — nó đã có đoạn nguồn rồi."""
    from langgraph.checkpoint.memory import InMemorySaver

    vehicle = InProcessVehicleGateway.new()
    da_goi = []

    async def rag_dem(state):
        da_goi.append(state.get("query"))
        return {"outcome": "grounded_refusal", "citations": [], "evidence": []}

    graph = build_graph(vehicle, rag=rag_dem, checkpointer=InMemorySaver())
    await graph.ainvoke(
        {"query": "đọc tiếp", "session_id": "s", "vehicle_id": "v", "turn_id": "t1"},
        config={"configurable": {"thread_id": "s"}},
    )
    assert da_goi == [], f"da tra so tay bang chinh chu 'doc tiep': {da_goi}"


class _FakeBus:
    """Ghi lại mọi lời gọi `publish()` — dùng để bắt `assistant.status` phát SỐNG
    ngay trong lúc `graph.ainvoke()` còn chạy (issue #346), không phải đợi
    `emit_turn_lifecycle()` dịch lại sau khi nó đã trả về.

    `order`: danh sách CHUNG, tuỳ chọn — node giả (vd. `rag`) cũng ghi nhãn của
    chính nó vào đây, để test so được thứ tự publish với thứ tự node thật chạy.
    """

    def __init__(self, order: list[str] | None = None):
        self.calls: list[tuple] = []
        self.order = order if order is not None else []

    async def publish(self, session_id, event_type, turn_id, trace_id, payload):
        self.calls.append((event_type, payload.get("state")))
        nhan = f"{event_type}:{payload.get('state')}" if event_type == "assistant.status" else event_type
        self.order.append(nhan)


def _thay_event_bus(monkeypatch, order: list[str] | None = None) -> _FakeBus:
    bus = _FakeBus(order)
    monkeypatch.setattr("src.services.ivi_events.get_event_bus", lambda: bus)
    return bus


async def test_manual_question_phat_retrieving_song_truoc_khi_rag_chay(monkeypatch):
    """`"retrieving"` phải phát TRƯỚC khi thân node `rag` chạy — không phải dịch
    lại sau khi `graph.ainvoke()` đã trả về (issue #346). Cả publish lẫn lần gọi
    rag đều ghi vào CÙNG một danh sách để so được thứ tự thật giữa hai bên."""
    thu_tu: list[str] = []
    _thay_event_bus(monkeypatch, thu_tu)

    async def rag_ghi_thu_tu(state):
        thu_tu.append("rag_dang_chay")
        return {"citations": [{"chunk_id": "c1"}], "evidence": [{"text": "..."}]}

    vehicle = InProcessVehicleGateway.new()
    result = await _run(vehicle, "Điều hòa hoạt động như thế nào?", rag=rag_ghi_thu_tu)

    assert result["outcome"] == "grounded_answer"
    assert "assistant.status:retrieving" in thu_tu
    assert thu_tu.index("assistant.status:retrieving") < thu_tu.index("rag_dang_chay")


async def test_manual_question_phat_composing_song_truoc_khi_compose_chay(monkeypatch):
    """`"composing"` phải phát ngay khi node `compose` bắt đầu chạy, cho lượt tra
    sổ tay (issue #346)."""
    bus = _thay_event_bus(monkeypatch)

    async def fake_rag(state):
        return {"citations": [{"chunk_id": "c1"}], "evidence": [{"text": "..."}]}

    vehicle = InProcessVehicleGateway.new()
    await _run(vehicle, "Điều hòa hoạt động như thế nào?", rag=fake_rag)

    assert ("assistant.status", "retrieving") in bus.calls
    assert ("assistant.status", "composing") in bus.calls
    # Đúng thứ tự: tra sổ tay xong rồi mới soạn câu trả lời.
    assert bus.calls.index(("assistant.status", "retrieving")) < bus.calls.index(("assistant.status", "composing"))


async def test_lenh_dieu_khien_khong_bao_gio_co_composing_song(monkeypatch):
    """Node `compose` cũng chạy cho lệnh điều khiển (execute → compose), nhưng
    KHÔNG được phát `"composing"` sống cho outcome đó — `docs/api_spec.md:620` quy
    định thứ tự `routing → plan.ready → executing`, và `plan.ready` chỉ tính được
    sau khi `graph.ainvoke()` trả về (issue #346)."""
    bus = _thay_event_bus(monkeypatch)
    vehicle = InProcessVehicleGateway.new()

    result = await _run(vehicle, "Đặt điều hòa 22 độ")

    assert result["outcome"] == "completed"
    assert ("assistant.status", "composing") not in bus.calls
    assert ("assistant.status", "retrieving") not in bus.calls


async def test_lenh_bi_chan_khong_bao_gio_co_composing_song(monkeypatch):
    """`compose` cũng chạy cho outcome `blocked` (S3) — cùng lý do loại trừ như lệnh
    điều khiển thành công (issue #346)."""
    bus = _thay_event_bus(monkeypatch)
    vehicle = InProcessVehicleGateway.new(speed_kph=45.0, gear="D")

    result = await _run(vehicle, "Mở cửa bên lái")

    assert result["outcome"] == "blocked"
    assert ("assistant.status", "composing") not in bus.calls


async def test_doc_tiep_khong_co_retrieving_song_vi_khong_qua_rag(monkeypatch):
    """"Đọc tiếp" không đụng node `rag` (xem `test_doc_tiep_khong_di_qua_rag` ở
    trên) — nên không có `"retrieving"` sống nào để phát, đúng thực tế: không có
    truy hồi nào xảy ra cho lượt này."""
    from langgraph.checkpoint.memory import InMemorySaver

    bus = _thay_event_bus(monkeypatch)
    vehicle = InProcessVehicleGateway.new()

    async def rag_dem(state):
        return {"outcome": "grounded_refusal", "citations": [], "evidence": []}

    graph = build_graph(vehicle, rag=rag_dem, checkpointer=InMemorySaver())
    await graph.ainvoke(
        {"query": "đọc tiếp", "session_id": "s2", "vehicle_id": "v", "turn_id": "t1"},
        config={"configurable": {"thread_id": "s2"}},
    )
    assert ("assistant.status", "retrieving") not in bus.calls

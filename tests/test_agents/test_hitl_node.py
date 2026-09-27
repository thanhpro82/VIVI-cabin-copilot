"""Node approval: mọi đường hỏng đều fail-closed với zero side effect."""

from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict

CONFIG = {"configurable": {"thread_id": "ses-1"}}
OPEN_WINDOW = "Mở cửa sổ bên lái 30 phần trăm"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _graph(vehicle: InProcessVehicleGateway, store: ApprovalStore):
    return build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())


async def _ask(graph, query: str = OPEN_WINDOW):
    return await graph.ainvoke(
        {"query": query, "session_id": "ses-1", "vehicle_id": "veh-1", "turn_id": "turn-1"},
        config=CONFIG,
    )


async def test_s2_interrupts_with_a_payload_the_ivi_can_render():
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    result = await _ask(_graph(vehicle, store))
    payload = result["__interrupt__"][0].value
    assert payload["approval_id"].startswith("appr-")
    assert payload["timeout_seconds"] == 30
    assert payload["prompt_text"]
    assert payload["steps_summary"][0]["tool"] == "set_window_position"
    assert payload["steps_summary"][0]["after"] == 30
    assert vehicle.command_count == 0


async def test_approve_executes_exactly_once():
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    interrupted = await _ask(graph)
    approval_id = interrupted["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["windows"]["front_left"] == 30
    assert vehicle.command_count == 1
    assert store.get(approval_id).status == "consumed"


async def test_reject_leaves_the_vehicle_untouched():
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=False)

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_rejected"
    assert vehicle.command_count == 0
    assert store.get(approval_id).status == "rejected"


async def test_expired_approval_never_executes():
    clock = FakeClock()
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore(clock=clock)
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]
    clock.advance(31)

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_expired"
    assert vehicle.command_count == 0


async def _ask_as(graph, session: str, turn: str = "turn-1", query: str = OPEN_WINDOW):
    return await graph.ainvoke(
        {"query": query, "session_id": session, "vehicle_id": "veh-1", "turn_id": turn},
        config={"configurable": {"thread_id": session}},
    )


async def test_two_sessions_asking_the_same_thing_get_separate_approvals():
    """Hai phiên cùng nói một câu vẫn là hai lần xin phép độc lập.

    Bản trước băm id chỉ từ `plan_digest` nên hai phiên ra chung một id; `create()`
    thấy id đã tồn tại thì trả lại bản ghi của phiên kia và **không** đăng ký pending
    cho phiên này — bất biến "tối đa một pending mỗi session" bị lách qua cửa sau.
    """
    store = ApprovalStore()
    vehicle_a, vehicle_b = InProcessVehicleGateway.new(), InProcessVehicleGateway.new()
    id_a = (await _ask_as(_graph(vehicle_a, store), "ses-a"))["__interrupt__"][0].value["approval_id"]
    id_b = (await _ask_as(_graph(vehicle_b, store), "ses-b"))["__interrupt__"][0].value["approval_id"]

    assert id_a != id_b
    assert store.pending_for_session("ses-a").approval_id == id_a
    assert store.pending_for_session("ses-b").approval_id == id_b


async def test_an_approval_owned_by_another_session_never_executes_here():
    """Ràng buộc quyền sở hữu nằm ở **phía server**.

    Node tra store bằng id client gửi, nên chỉ id khó đoán thôi là chưa đủ: bản ghi
    tìm được còn phải thuộc đúng phiên đang resume. Chốt digest không cứu được ca này
    vì hai plan giống hệt nhau thì digest giống hệt nhau.
    """
    store = ApprovalStore()
    vehicle_a, vehicle_b = InProcessVehicleGateway.new(), InProcessVehicleGateway.new()
    graph_b = _graph(vehicle_b, store)
    id_a = (await _ask_as(_graph(vehicle_a, store), "ses-a"))["__interrupt__"][0].value["approval_id"]
    await _ask_as(graph_b, "ses-b")
    store.decide(id_a, approve=True)  # chỉ phiên A được duyệt

    result = await graph_b.ainvoke(
        Command(resume={"approval_id": id_a}), config={"configurable": {"thread_id": "ses-b"}}
    )

    assert result["outcome"] == "approval_not_owned"
    assert vehicle_b.command_count == 0
    assert vehicle_a.command_count == 0
    # Approval của A không bị phiên B tiêu thụ mất.
    assert store.get(id_a).status == "approved"


async def test_a_command_refused_once_can_be_issued_again():
    """Từ chối rồi đổi ý là chuyện thường; lượt sau phải xin phép lại được.

    `plan_id`/`plan_digest` gồm `vehicle_state_version` nhưng **không** gồm `turn_id`.
    Lượt bị từ chối không đổi state nên lượt sau ra đúng digest cũ: `create()` trả lại
    bản ghi `rejected`, và người dùng kẹt vĩnh viễn với câu lệnh đó cho tới khi trạng
    thái xe tình cờ đổi.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    first_id = (await _ask_as(graph, "ses-1", turn="turn-1"))["__interrupt__"][0].value["approval_id"]
    store.decide(first_id, approve=False)
    await graph.ainvoke(Command(resume={"approval_id": first_id}), config={"configurable": {"thread_id": "ses-1"}})

    second_id = (await _ask_as(graph, "ses-1", turn="turn-2"))["__interrupt__"][0].value["approval_id"]
    assert second_id != first_id
    store.decide(second_id, approve=True)
    result = await graph.ainvoke(
        Command(resume={"approval_id": second_id}), config={"configurable": {"thread_id": "ses-1"}}
    )

    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["windows"]["front_left"] == 30


async def test_resume_without_a_decision_is_not_treated_as_approval():
    """Im lặng không phải đồng ý — `safety_and_hitl.md` mục Approval UX contract."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_rejected"
    assert vehicle.command_count == 0


async def test_external_state_change_invalidates_the_approval():
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    await vehicle.execute(
        plan_id="ngoai-luong",
        step_id="step-1",
        tool="set_hvac_power",
        args={"enabled": False},
        expected_state_version=snapshot_dict(vehicle.state)["state_version"],
    )

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_invalidated_state"
    assert snapshot_dict(vehicle.state)["windows"]["front_left"] == 0


async def test_car_moving_while_waiting_turns_the_action_into_s3():
    """Xe đứng yên → xin mở cửa (S2) → đang chờ thì xe lăn bánh → phải thành S3.

    Không có bước kiểm predicate lần cuối thì approval cũ hợp thức hoá một action
    mà policy hiện tại đã cấm.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph, "Mở cửa bên lái"))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    # Xe lăn bánh trong lúc chờ duyệt: lệnh mở cửa từ S2 thành S3.
    vehicle.set_motion(45.0, "D")

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    # Ghim đúng nhánh: nếu một thay đổi sau này khiến nó rơi sang
    # `approval_invalidated_state` thì kiểm tra predicate đã thành code chết — cần biết.
    assert result["outcome"] == "approval_predicate_failed"
    assert snapshot_dict(vehicle.state)["doors"]["front_left"] == "closed"
    assert vehicle.command_count == 0


async def test_second_pending_in_the_same_session_creates_nothing():
    """safety_and_hitl.md §Required safety test #17."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    await _ask(_graph(vehicle, store))
    other = await build_graph(vehicle, approvals=store, checkpointer=InMemorySaver()).ainvoke(
        {"query": "Mở cửa sổ bên phụ một nửa", "session_id": "ses-1", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-1-b"}},
    )
    assert other["outcome"] == "approval_already_pending"
    assert vehicle.command_count == 0


async def test_s3_is_blocked_before_any_approval_exists():
    """safety_and_hitl.md §Required safety test #4 — S3 không bao giờ hiện popup."""
    vehicle = InProcessVehicleGateway.new(speed_kph=45.0, gear="D")
    store = ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Mở cửa bên lái")
    assert result["outcome"] == "blocked"
    assert "__interrupt__" not in result
    assert store.pending_for_session("ses-1") is None


async def test_s1_still_runs_without_any_approval():
    """safety_and_hitl.md §Required safety test #1."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Đặt điều hòa 22 độ")
    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["hvac"]["temperature_c"] == 22
    assert store.pending_for_session("ses-1") is None


async def test_approval_of_another_plan_cannot_be_reused():
    """`safety_and_hitl.md` §Core invariants: "Approval không dùng lại cho plan khác".

    Kịch bản: hai phiên, mỗi phiên xin một lệnh S2 khác nhau. Lấy approval đã duyệt
    của phiên A đưa cho phiên B. Phải bị từ chối và nêu **đúng lý do**, không phải
    vì "không tìm thấy".

    Trước đây ca này rơi vào `approval_invalidated_plan` — đúng kết quả nhưng sai lý
    do: nó chỉ chặn được nhờ `session_id` tình cờ nằm trong `ActionPlan` nên digest
    lệch theo, và sẽ im lặng nếu hai phiên tình cờ cùng một plan. Giờ ràng buộc quyền
    sở hữu kiểm thẳng và chạy trước, nên lý do trả về là `approval_not_owned`.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()

    graph_a = build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())
    a_config = {"configurable": {"thread_id": "ses-A"}}
    a_interrupt = await graph_a.ainvoke(
        {"query": OPEN_WINDOW, "session_id": "ses-A", "vehicle_id": "veh-1"}, config=a_config
    )
    a_id = a_interrupt["__interrupt__"][0].value["approval_id"]
    store.decide(a_id, approve=True)

    graph_b = build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())
    b_config = {"configurable": {"thread_id": "ses-B"}}
    await graph_b.ainvoke(
        {"query": "Mở cửa sổ bên phụ một nửa", "session_id": "ses-B", "vehicle_id": "veh-1"}, config=b_config
    )

    # Phiên B resume bằng approval của phiên A.
    result = await graph_b.ainvoke(Command(resume={"approval_id": a_id}), config=b_config)
    assert result["outcome"] == "approval_not_owned"
    assert vehicle.command_count == 0
    assert snapshot_dict(vehicle.state)["windows"]["front_right"] == 0
    assert store.get(a_id).status == "approved"


async def test_resume_payload_cannot_grant_an_approval_that_was_never_decided():
    """Payload resume đi qua HTTP nên không được tin. Id lạ chỉ dùng để tra, không cấp quyền."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    await _ask(graph)

    result = await graph.ainvoke(Command(resume={"approval_id": "appr-bia-dat"}), config=CONFIG)
    assert result["outcome"] in {"approval_rejected", "approval_invalidated_state"}
    assert vehicle.command_count == 0


async def test_hitl_survives_strict_checkpoint_deserialisation():
    """LangGraph cảnh báo sẽ **chặn** việc khôi phục kiểu Pydantic từ checkpoint.

    Hiện tại nó chỉ warn, nhưng thông điệp ghi rõ "This will be blocked in a future
    version". Khi mặc định đổi, `state["action_plan"]` quay về là `dict` thay vì
    `ActionPlan`, và đường resume vỡ bằng `AttributeError: 'dict' object has no
    attribute 'model_dump'` — vỡ sâu bên trong, không phải lỗi rõ ràng ở biên.

    Test này ép chế độ đó ngay bây giờ để nâng cấp thư viện không âm thầm làm hỏng HITL.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    strict = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=None))
    graph = build_graph(vehicle, approvals=store, checkpointer=strict)

    interrupted = await graph.ainvoke(
        {"query": OPEN_WINDOW, "session_id": "ses-1", "vehicle_id": "veh-1"}, config=CONFIG
    )
    approval_id = interrupted["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["windows"]["front_left"] == 30
    assert vehicle.command_count == 1


# --- Plan nguồn SLM đi hết đường duyệt (BUG-01) -----------------------------
#
# Cả khối dưới đây tồn tại vì một điểm mù rất cụ thể: trước 21/08, `route_source=
# "slm"` chỉ xuất hiện trong `test_policy.py` — tức chỉ ở unit test của
# `materialize_action_plan`. **Không test nào** đi hết chuỗi
# *planner đề xuất → interrupt → duyệt → resume*, nên `approval.py` quên truyền
# `route_source` mà cả bộ 1356 test vẫn xanh suốt hai tuần.
#
# Đo trên máy Sơn 20/08: mọi lượt S0/S1 do planner đề xuất đều trả
# *"Xe không còn ở trạng thái an toàn cho lệnh này nữa."* khi tài xế bấm Đồng ý,
# trong khi xe đứng yên ở số P. Xem docs/reports/dieu-tra-bug-buoi-test-2026-08-21.md
# §BUG-01.


async def _fake_rag(state):
    """RAG rỗng, đủ để nhánh sổ tay không nuốt lượt và không phải nạp FAISS (~32 s)."""
    return {}


class _VolumePlanner:
    """Đúng plan mà planner thật sinh ra cho `"Tắt âm lượng"` trên máy Sơn."""

    def propose(self, normalized_text, snapshot):
        return (
            '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1",'
            '"ordinal":0,"tool":"media_control","args":{"action":"set_volume",'
            '"volume":0},"depends_on":[]}]}'
        )


class _WindowPlanner:
    def propose(self, normalized_text, snapshot):
        return (
            '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1",'
            '"ordinal":0,"tool":"set_window_position","args":{"window":"front_left",'
            '"percent":30},"depends_on":[]}]}'
        )


class _DoorPlanner:
    """Cửa, KHÔNG phải kính: chỉ cửa mới đổi mức an toàn theo tốc độ.

    Kính là S2 **luôn luôn** (ADR-010), nên dùng kính cho bài test "xe lăn bánh
    trong lúc chờ duyệt" thì không có gì thay đổi và lượt chạy tiếp một cách hoàn
    toàn đúng — bài test sẽ xanh vì lý do sai. Đo được lúc viết test này.
    """

    def propose(self, normalized_text, snapshot):
        return (
            '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1",'
            '"ordinal":0,"tool":"set_door_state","args":{"door":"front_left",'
            '"state":"open"},"depends_on":[]}]}'
        )


#: Router luật trả `default_to_manual` cho câu này, nên nó là câu ĐI TỚI nhánh SLM.
#: Đây là câu Sơn nói lúc 00:07 ngày 21/08.
#: Câu vào cho các test HITL dùng planner stub. Cố ý **không nhắc miền nào**.
#:
#: Trước #324 nó là `"Tắt âm lượng"`, và câu ấy vô hại đúng tới ngày có cổng
#: `cong_mien_slm`: các test dưới đây bơm stub trả plan cửa/kính, nên câu nói về *âm
#: lượng* mà plan chạm *cửa* chính là ca mà cổng ấy sinh ra để chặn. Cổng chặn đúng;
#: thứ sai là câu vào — nó vốn chỉ cần đưa lượt tới `slm_stage`, miền là ngẫu nhiên.
#:
#: Không đổi thành một câu **khớp** miền của từng stub, vì mỗi test dùng stub khác nhau
#: (cửa, kính) và một câu chung sẽ lại lệch với một trong hai. Câu không miền thì đúng
#: cho mọi stub, và giữ cho test này đo đúng thứ nó nói là đang đo: vòng đời phê duyệt.
CAU_KHONG_MIEN = "Làm gì đó giùm tôi"


async def _ask_slm(graph, query: str = CAU_KHONG_MIEN):
    return await graph.ainvoke(
        {"query": query, "session_id": "ses-1", "vehicle_id": "veh-1", "turn_id": "turn-1"},
        config=CONFIG,
    )


async def test_slm_s1_plan_can_actually_be_approved():
    """Plan S1 do planner đề xuất, tài xế đồng ý, xe đứng yên → PHẢI chạy.

    Đây là hồi quy trực tiếp của BUG-01. `materialize_action_plan` tính
    `requires_approval = any(S2) or route_source == "slm"`, mà `plan_digest` băm
    **toàn bộ** `model_dump()`. Nên nếu `approval.py` dựng lại plan mà không truyền
    `route_source`, digest lệch đúng một trường (`requires_approval: True → False`)
    và lượt rơi xuống `approval_predicate_failed` — 100% số lần, bất kể xe ở đâu.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = build_graph(vehicle, rag=_fake_rag, planner=_VolumePlanner(), approvals=store, checkpointer=InMemorySaver())

    interrupted = await _ask_slm(graph)
    payload = interrupted["__interrupt__"][0].value
    assert payload["steps_summary"][0]["tool"] == "media_control", "cổng #144 phải hỏi duyệt plan SLM"
    assert vehicle.command_count == 0

    approval_id = payload["approval_id"]
    store.decide(approval_id, approve=True)
    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)

    assert result["outcome"] != "approval_predicate_failed", (
        "BUG-01: xe đứng yên ở số P, không có gì đổi, nhưng lượt bị từ chối bằng câu "
        "'Xe không còn ở trạng thái an toàn cho lệnh này nữa.' — dấu hiệu `approval.py` "
        "lại quên truyền `route_source` vào `materialize_action_plan`."
    )
    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["media"]["volume"] == 0
    assert vehicle.command_count == 1
    assert store.get(approval_id).status == "consumed"


async def test_slm_s2_plan_still_approves():
    """Nhánh S2 vốn CHE MẤT BUG-01 — khoá lại để bản sửa không đánh đổi nó.

    Ở S2 cả hai phía đều tính ra `requires_approval=True` nên digest trùng kể cả khi
    `route_source` bị bỏ. Đó đúng là lý do lỗi sống sót: người test bấm duyệt cửa/kính
    thì thấy chạy ngon (Sơn, 00:38 *"mở hết cửa thì HITL lại được"*), nên không ai ngờ
    nhánh S1 đã chết.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = build_graph(vehicle, rag=_fake_rag, planner=_WindowPlanner(), approvals=store, checkpointer=InMemorySaver())

    approval_id = (await _ask_slm(graph))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)

    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["windows"]["front_left"] == 30
    assert vehicle.command_count == 1


async def test_slm_plan_still_fails_closed_when_the_car_starts_moving():
    """Bản sửa KHÔNG được làm mềm predicate: xe lăn bánh trong lúc chờ thì vẫn chặn.

    Đây là nửa còn lại của bài toán. `route_source` đi vào digest, nên truyền lại nó
    là điều kiện để hai bên **so đúng thứ**; nó không được biến bước so digest thành
    hình thức. Ở đây plan mở cửa sinh lúc xe đứng yên (S2), xe chạy 40 km/h trước khi
    tài xế bấm Đồng ý — hành động hoá S3 — và lượt phải fail-closed, zero side effect.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = build_graph(vehicle, rag=_fake_rag, planner=_DoorPlanner(), approvals=store, checkpointer=InMemorySaver())

    approval_id = (await _ask_slm(graph))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    vehicle.set_motion(speed_kph=40, gear="D")

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)

    assert result["outcome"] in {"approval_invalidated_state", "approval_predicate_failed"}
    assert vehicle.command_count == 0
    assert snapshot_dict(vehicle.state)["doors"]["front_left"] == "closed"

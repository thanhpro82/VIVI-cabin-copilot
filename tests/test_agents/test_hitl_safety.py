"""Ánh xạ trực tiếp `docs/safety_and_hitl.md` §Required safety tests.

Header cũ ghi "Phủ 7/19" — con số đó đếm **trong đúng file này**. Audit toàn suite
2026-08-12 cho thấy nhiều yêu cầu đã có mã kiểm ở nơi khác từ lâu; viết lại chúng ở
đây chỉ nhân đôi bảo trì và tạo tín hiệu giả là đã kiểm kỹ hơn thực tế. Bảng dưới là
hiện trạng thật, kiểm chứng được từng dòng.

Tiêu chí "đã phủ": nếu phá hành vi mà yêu cầu mô tả, có ít nhất một test đỏ.

| # | Trạng thái | Ở đâu |
|---|---|---|
| 1  | phủ | `test_safety_1_s1_runs_without_approval` (file này) |
| 2  | phủ | `test_safety_2_s2_without_approval_is_rejected` (file này) |
| 3  | phủ | `test_safety_3_validation_denied_happens_before_any_approval_exists` (file này, 2026-08-12) + `test_tools.py` cho phân loại |
| 4  | phủ | `test_safety_4_s3_is_blocked_before_the_approval_card_exists` (file này) |
| 5  | phủ | `test_safety_5_replayed_approval_cannot_execute_twice` (file này) |
| 6  | phủ | `test_safety_6_door_and_seat_are_s2_only_when_stationary` (file này) |
| 7  | phủ | `test_safety_7_two_s2_steps_share_one_approval` (file này, thêm 2026-08-12) |
| 8  | phủ | `test_safety_8_external_state_change_marks_the_rest_skipped_with_its_own_code` (file này) + `test_mqtt_idempotency.py::test_evict_phia_simulator_thi_version_check_chan_lai` cho vế chặn lệnh. Bug issue #83 đã sửa |
| 9  | phủ | `test_safety_9_a_failed_step_marks_the_rest_skipped` (file này). Từng `xfail(strict=True)` vì `execute_node` `break` làm các bước sau biến mất — issue #83 đã sửa, marker đã gỡ |
| 10 | phủ | `test_mqtt_idempotency.py`: `test_retry_dung_mot_lan_va_giu_nguyen_command_id`, `test_duplicate_delivery_qos1_chi_tao_mot_transition`, `test_replay_cung_plan_step_tra_ket_qua_cu`, `test_tool_ngoai_allowlist_khong_bao_gio_len_broker`, `test_args_sai_dai_khong_bao_gio_len_broker` |
| 11 | phủ | `test_mqtt_idempotency.py`: `test_chi_persist_dung_mot_terminal_result`, `test_replay_cung_plan_step_tra_ket_qua_cu`, `test_evict_phia_executor_sinh_command_id_moi_nhung_van_an_toan` |
| 12 | phủ | `test_safety_12_window_is_always_s2` (file này) |
| 13 | phủ | `test_agents/test_policy.py::test_s1_tools` |
| 14 | phủ | `test_agents/test_router.py`: `test_ambiguous_reference_asks_for_clarification`, `test_three_or_more_adjacent_numerals_stay_ambiguous`; cộng ràng buộc cấu trúc `test_contracts.py::test_route_decision_non_control_forbids_candidate_plan` |
| 15 | phủ | `test_safety_15_mixed_s1_s2_waits_for_one_bundled_approval` + `test_safety_15_any_s3_step_means_zero_side_effects` (file này, thêm 2026-08-12) |
| 16 | phủ | `test_safety_16_an_slm_sourced_plan_still_cannot_reach_the_executor` (file này, 2026-08-12) cho vế "không publish MQTT"; `test_router.py::test_injection_bait_...` cho injection; `test_contracts.py::test_candidate_step_refuses_safety_level` cho "không gán safety" |
| 17 | phủ | `test_safety_17_second_pending_creates_no_artifacts` (file này) |
| 18 | phủ | `test_api/test_approval_voice_intent.py` — cả ba nhánh terminal của `api_spec.md:643-644`, trong đó `test_handoff_khong_commit_quyet_dinh` khoá đúng vế "chỉ handoff". Mở chặn bởi issue #107 (15/08) |
| 19 | phủ | `test_agents/test_hitl_node.py` đủ năm nhánh: `test_reject_leaves_the_vehicle_untouched`, `test_expired_approval_never_executes`, `test_external_state_change_invalidates_the_approval`, `test_approval_of_another_plan_cannot_be_reused`, `test_car_moving_while_waiting_turns_the_action_into_s3` |

**Hiện trạng: 19/19 phủ.**

Không còn dòng "phủ một phần" và không còn `xfail` nào. #18 là cái cuối cùng, và nó
từng bị chặn vì **thiếu tính năng** chứ không thiếu test — issue #107 làm ra tính năng
thì test theo sau ngay.

Riêng #18 nằm ở `tests/test_api/`, không ở file này: nó là hợp đồng **HTTP + sự kiện**
(ba nhánh terminal, mỗi nhánh đúng một event terminal), không phải hợp đồng của tầng
graph mà file này kiểm.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.agents.policy import classify
from src.agents.router import DeterministicControlRouter
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict

CONFIG = {"configurable": {"thread_id": "ses-safety"}}


def _graph(vehicle, store):
    return build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())


async def _ask(graph, query):
    return await graph.ainvoke({"query": query, "session_id": "ses-safety", "vehicle_id": "veh-1"}, config=CONFIG)


async def test_safety_1_s1_runs_without_approval():
    """#1: S1 hợp lệ chạy không cần approval, nhưng vẫn qua policy."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Đặt điều hòa 22 độ")
    assert result["outcome"] == "completed"
    assert store.pending_for_session("ses-safety") is None


async def test_safety_2_s2_without_approval_is_rejected():
    """#2: S2 không có approval thì không chạy."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph, "Mở cửa sổ bên lái 30 phần trăm"))["__interrupt__"][0].value["approval_id"]
    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_rejected"
    assert vehicle.command_count == 0


async def test_safety_4_s3_is_blocked_before_the_approval_card_exists():
    """#4: S3 bị chặn trước khi tạo hoặc hiển thị approval."""
    vehicle, store = InProcessVehicleGateway.new(speed_kph=45.0, gear="D"), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Mở cửa bên lái")
    assert result["outcome"] == "blocked"
    assert "__interrupt__" not in result
    assert store.pending_for_session("ses-safety") is None


async def test_safety_5_replayed_approval_cannot_execute_twice():
    """#5: approval hết hạn/replay bị từ chối; không dùng lại cho lượt khác."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph, "Mở cửa sổ bên lái 30 phần trăm"))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert vehicle.command_count == 1
    assert store.get(approval_id).status == "consumed"
    assert store.consume(approval_id).status == "consumed"
    assert vehicle.command_count == 1


def test_safety_6_door_and_seat_are_s2_only_when_stationary():
    """#6: door/seat position là S2 chỉ khi speed_kph == 0 && gear == P."""
    stationary = snapshot_dict(InProcessVehicleGateway.new().state)
    moving = snapshot_dict(InProcessVehicleGateway.new(speed_kph=45.0, gear="D").state)
    for tool in ("set_door_state", "set_seat_position"):
        assert classify(tool, stationary) == "S2"
        assert classify(tool, moving) == "S3"


def test_safety_12_window_is_always_s2():
    """#12: window luôn S2, kể cả khi xe đứng yên."""
    for snapshot in (
        snapshot_dict(InProcessVehicleGateway.new().state),
        snapshot_dict(InProcessVehicleGateway.new(speed_kph=45.0, gear="D").state),
    ):
        assert classify("set_window_position", snapshot) == "S2"


async def test_safety_17_second_pending_creates_no_artifacts():
    """#17: tối đa một pending/session; request thứ hai tạo zero plan/approval/side effect."""
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    await _ask(_graph(vehicle, store), "Mở cửa sổ bên lái 30 phần trăm")
    second = await build_graph(vehicle, approvals=store, checkpointer=InMemorySaver()).ainvoke(
        {"query": "Mở cửa sổ bên phụ một nửa", "session_id": "ses-safety", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-safety-2"}},
    )
    assert second["outcome"] == "approval_already_pending"
    assert vehicle.command_count == 0
    assert snapshot_dict(vehicle.state)["windows"]["front_right"] == 0


class _TwoStepRouter:
    """Router stub sinh plan hai bước.

    Router tất định của P0 **không bao giờ** sinh plan nhiều bước (use case đa ý định
    chưa chạy — xem `docs/coverage_matrix.md`), nên hai yêu cầu an toàn về plan nhiều
    bước không thể kiểm bằng câu tiếng Việt. Stub ở đây chỉ thay phần *định tuyến*;
    toàn bộ validate → safety → HITL → execute vẫn là mã thật.
    """

    def __init__(self, steps):
        self._steps = steps

    def route(self, input_text: str):
        from src.agents.contracts import CandidateActionPlan, RouteDecision

        return RouteDecision(
            disposition="control",
            intent="window_position",
            reason="stub_two_step",
            candidate_plan=CandidateActionPlan(schema_version="1.0", steps=self._steps),
        )


def _step(ordinal: int, tool: str, args: dict) -> dict:
    return {"step_id": f"step-{ordinal + 1}", "ordinal": ordinal, "tool": tool, "args": args, "depends_on": []}


async def test_safety_15_mixed_s1_s2_waits_for_one_bundled_approval():
    """#15: mixed S1/S2 chờ một bundled approval trước **mọi** side effect.

    Đây là chỗ dễ rò rỉ nhất trong plan nhiều bước: bước S1 đứng trước rất dễ được
    chạy luôn "vì nó có phải S2 đâu", và lúc đó tài xế đã mất quyền từ chối một việc
    đã xảy ra rồi.
    """
    vehicle = InProcessVehicleGateway.new()
    store = ApprovalStore()
    graph = build_graph(
        vehicle,
        router=_TwoStepRouter([
            _step(0, "set_hvac_temperature", {"temperature_c": 22}),  # S1
            _step(1, "set_window_position", {"window": "front_left", "percent": 50}),  # S2
        ]),
        approvals=store,
        checkpointer=InMemorySaver(),
    )

    result = await _ask(graph, "bất kỳ câu nào, router đã bị stub")

    assert result["outcome"] == "approval_required"
    assert vehicle.command_count == 0, "bước S1 không được chạy trước khi có approval"


async def test_safety_15_any_s3_step_means_zero_side_effects():
    """#15 (vế hai): có S3 thì **không** side effect nào, kể cả bước S1 hợp lệ."""
    vehicle = InProcessVehicleGateway.new()
    vehicle.set_motion(speed_kph=40, gear="D")  # cửa lúc xe chạy là S3
    store = ApprovalStore()
    graph = build_graph(
        vehicle,
        router=_TwoStepRouter([
            _step(0, "set_hvac_temperature", {"temperature_c": 22}),  # S1
            _step(1, "set_door_state", {"door": "front_left", "state": "open"}),  # S3 khi đang chạy
        ]),
        approvals=store,
        checkpointer=InMemorySaver(),
    )

    result = await _ask(graph, "bất kỳ câu nào, router đã bị stub")

    assert result["outcome"] == "blocked"
    assert vehicle.command_count == 0


async def test_safety_7_two_s2_steps_share_one_approval():
    """#7: hai bước S2 dùng **một** approval, không phải mỗi bước một cái.

    Bắt tài xế xác nhận hai lần cho một câu lệnh vừa phiền vừa nguy hiểm: người ta
    sẽ bấm cho xong. Và nếu mỗi bước sinh một approval riêng thì bất biến "tối đa một
    pending mỗi session" (#17) sẽ chặn chính bước thứ hai của cùng một plan.
    """
    vehicle = InProcessVehicleGateway.new()
    store = ApprovalStore()
    graph = build_graph(
        vehicle,
        router=_TwoStepRouter([
            _step(0, "set_window_position", {"window": "front_left", "percent": 50}),
            _step(1, "set_window_position", {"window": "front_right", "percent": 50}),
        ]),
        approvals=store,
        checkpointer=InMemorySaver(),
    )

    result = await _ask(graph, "bất kỳ câu nào, router đã bị stub")

    assert result["outcome"] == "approval_required"
    assert vehicle.command_count == 0
    pending = store.pending_for_session("ses-safety")
    assert pending is not None, "phải có đúng một approval đang chờ cho cả plan"
    assert store.record_count == 1, "hai bước S2 phải dùng chung một approval, không phải mỗi bước một cái"
    # Approval buộc vào **plan**, không buộc vào bước — nên nó phủ cả hai bước S2.
    assert pending.plan_id == result["action_plan"].plan_id


async def test_safety_3_validation_denied_happens_before_any_approval_exists():
    """#3: unknown tool / args sai là `validation_denied` **trước** S0–S3/HITL.

    Điều cần chứng minh là *thứ tự*, không phải phân loại (phân loại đã có ở
    `test_agents/test_tools.py`). Nếu validate chạy sau safety thì một plan rác vẫn
    kịp sinh thẻ approval, và tài xế bị hỏi về một việc lẽ ra không bao giờ tồn tại.
    """
    vehicle = InProcessVehicleGateway.new()
    store = ApprovalStore()
    graph = build_graph(
        vehicle,
        # `percent` ngoài dải: nếu chạy được tới safety thì window sẽ thành S2 và
        # sinh approval — đúng thứ test này chứng minh là không xảy ra.
        router=_TwoStepRouter([_step(0, "set_window_position", {"window": "front_left", "percent": 999})]),
        approvals=store,
        checkpointer=InMemorySaver(),
    )

    result = await _ask(graph, "bất kỳ câu nào, router đã bị stub")

    assert result["outcome"] == "validation_denied"
    assert store.record_count == 0, "không được sinh approval cho plan chưa qua validate"
    assert vehicle.command_count == 0


async def test_safety_16_an_slm_sourced_plan_still_cannot_reach_the_executor():
    """#16 (vế "SLM không publish MQTT"): plan do SLM đề xuất vẫn phải qua cổng thật.

    `test_contracts.py::test_candidate_step_refuses_safety_level` đã khoá việc SLM
    **gán** safety ở mức kiểu. Vế còn lại là đường đi: một plan nguồn SLM chạm tới
    executor được hay không. Ở đây dựng đúng tình huống xấu nhất — SLM đề xuất mở
    cửa khi xe đang chạy — và chứng minh nó dừng ở `blocked` với zero side effect.
    """
    vehicle = InProcessVehicleGateway.new()
    vehicle.set_motion(speed_kph=40, gear="D")
    store = ApprovalStore()

    class _SlmPlanner:
        def propose(self, normalized_text, snapshot):
            return (
                '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1",'
                '"ordinal":0,"tool":"set_door_state","args":{"door":"front_left",'
                '"state":"open"},"depends_on":[]}]}'
            )

    graph = build_graph(vehicle, planner=_SlmPlanner(), approvals=store, checkpointer=InMemorySaver())

    result = await _ask(graph, "mở giùm cái gì đó bên trái")

    assert result["outcome"] == "blocked", "S3 phải chặn dù plan đến từ SLM"
    assert vehicle.command_count == 0
    assert store.record_count == 0, "S3 không được sinh approval"


async def test_safety_9_a_failed_step_marks_the_rest_skipped():
    """#9: bước fail/timeout/rejected làm các bước còn lại `skipped_due_to_prior_failure`."""

    class _FailingGateway(InProcessVehicleGateway):
        async def execute(self, **kwargs):
            result = await super().execute(**kwargs)
            return result.model_copy(update={"status": "failed", "error_code": "mqtt_unavailable"})

    vehicle = _FailingGateway.new()
    graph = build_graph(
        vehicle,
        router=_TwoStepRouter([
            _step(0, "set_hvac_temperature", {"temperature_c": 22}),
            _step(1, "set_hvac_power", {"enabled": True}),
        ]),
        checkpointer=InMemorySaver(),
    )

    result = await _ask(graph, "bất kỳ câu nào, router đã bị stub")

    assert result["outcome"] == "execution_failed"
    codes = [r.error_code for r in result["step_results"]]
    assert len(result["step_results"]) == 2, "bước thứ hai phải có ToolResult, không được biến mất"
    assert codes[1] == "skipped_due_to_prior_failure"


async def test_safety_8_external_state_change_marks_the_rest_skipped_with_its_own_code():
    """#8: version lệch do người/thứ khác đổi trạng thái xe → mã riêng, không lẫn với #9.

    Hai nguyên nhân dừng group phải phân biệt được trên hồ sơ: "bước trước hỏng" và
    "trạng thái xe đã bị đổi bên ngoài" dẫn tới hai hành động khác nhau của người vận
    hành. Gộp chung một mã là mất đúng thông tin đó.
    """

    class _StaleGateway(InProcessVehicleGateway):
        async def execute(self, **kwargs):
            result = await super().execute(**kwargs)
            return result.model_copy(update={"status": "rejected", "error_code": "stale_state"})

    vehicle = _StaleGateway.new()
    graph = build_graph(
        vehicle,
        router=_TwoStepRouter([
            _step(0, "set_hvac_temperature", {"temperature_c": 22}),
            _step(1, "set_hvac_power", {"enabled": True}),
        ]),
        checkpointer=InMemorySaver(),
    )

    result = await _ask(graph, "bất kỳ câu nào, router đã bị stub")

    assert result["outcome"] == "execution_failed"
    assert len(result["step_results"]) == 2
    assert result["step_results"][1].error_code == "skipped_external_state_change"


async def test_a_fully_completed_plan_is_still_reported_completed():
    """Lưới cho chính bản sửa issue #83.

    Sau khi mọi bước đều có bản ghi, `len(results) == len(plan.steps)` luôn đúng, nên
    nếu ai đó "dọn dẹp" vế `all(status == completed)` thì plan hỏng sẽ được báo
    `completed` mà không test nào kêu. Test này giữ đầu kia của cán cân.
    """
    vehicle = InProcessVehicleGateway.new()
    graph = build_graph(
        vehicle,
        router=_TwoStepRouter([
            _step(0, "set_hvac_temperature", {"temperature_c": 22}),
            _step(1, "set_hvac_power", {"enabled": True}),
        ]),
        checkpointer=InMemorySaver(),
    )

    result = await _ask(graph, "bất kỳ câu nào, router đã bị stub")

    assert result["outcome"] == "completed"
    assert [r.status for r in result["step_results"]] == ["completed", "completed"]
    assert vehicle.command_count == 2


async def test_guard_poi_not_in_fixture_chay_that_qua_graph():
    """Guard `poi_not_in_fixture` lần đầu được chứng minh ở **runtime**, không chỉ ở unit.

    Trước #171 `graph.py` khởi tạo `DeterministicControlRouter()` không tham số, nên
    `_poi_ids` luôn rỗng và guard này **chưa từng chạy một lần nào** ngoài test dựng
    router trực tiếp. Một guard chỉ sống trong test là một guard chưa được chứng minh.

    Ca kiểm: câu nói hoàn toàn hợp lệ, alias tra ra `poi-charge-01`, nhưng router này
    chỉ được phép đi tới `poi-cafe-01`. Kết quả phải là `denied` — không phải `clarify`,
    vì hệ thống *hiểu* câu nói, nó chỉ không được phép tới đó.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    han_che = DeterministicControlRouter(poi_fixture=[{"id": "poi-cafe-01"}])
    graph = build_graph(vehicle, approvals=store, checkpointer=InMemorySaver(), router=han_che)

    result = await graph.ainvoke(
        {"query": "Dẫn đường đến trạm sạc", "session_id": "ses-safety", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-poi-guard"}},
    )

    assert result["outcome"] == "denied"
    assert vehicle.command_count == 0


# ---- open_app: tool cục bộ, và ràng buộc PM khi duyệt ADR-023 ---------------


async def test_open_app_chay_het_duong_ma_khong_gui_lenh_nao_len_mqtt():
    """`open_app` đi hết graph nhưng **không** chạm cổng xe.

    `execute_node` rẽ nhánh cho bước có `get_spec(tool).domain is None` *trước* khi gọi
    `gateway.execute`, vì cổng dựng `VehicleCommand` rồi đưa vào simulator, nơi tool
    không có nhánh xử lý sẽ ném `ToolNotAllowedError`.

    `command_count == 0` là mệnh đề thật sự đáng khoá: nó chứng minh lựa chọn app không
    lọt vào MQTT, tức ADR-013 còn nguyên — snapshot của simulator vẫn là nguồn trạng
    thái xe duy nhất, không bị nhét thêm một domain cho thứ không phải trạng thái xe.
    """
    vehicle, store = InProcessVehicleGateway.new(), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Mở YouTube")

    assert result["outcome"] == "completed"
    assert vehicle.command_count == 0
    assert [r.tool for r in result["step_results"]] == ["open_app"]
    assert result["step_results"][0].status == "completed"
    assert store.pending_for_session("ses-safety") is None


async def test_open_app_khi_xe_dang_chay_bi_chan_s3_va_khong_duoc_hoi_phe_duyet():
    """Ràng buộc @thanhpro82 thêm lúc duyệt ADR-023: **S3 không được HITL override**.

    Xe không ở P thì lệnh mở video bị chặn thẳng, không được biến thành một hộp thoại
    *"bạn có chắc không"*. Hôm nay điều đó đúng nhờ cấu trúc — `safety_node` xét S3
    **trước** `requires_approval` nên S3 không bao giờ tới nhánh phê duyệt — nhưng
    "đúng nhờ cấu trúc" không phải "được bảo vệ": không có test này thì một lần refactor
    tầng an toàn sẽ mở lại cửa mà không ai thấy.

    Ba vế phải cùng đúng: bị chặn, không có interrupt, và không có approval nào tồn tại
    để mà bấm.
    """
    vehicle, store = InProcessVehicleGateway.new(speed_kph=45.0, gear="D"), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Mở YouTube")

    assert result["outcome"] == "blocked"
    assert "__interrupt__" not in result
    assert store.pending_for_session("ses-safety") is None
    assert vehicle.command_count == 0


async def test_open_app_bi_chan_ca_khi_dung_yen_nhung_chua_ve_so_p():
    """0 km/h ở số D vẫn bị chặn — `is_stationary` đòi cả tốc độ lẫn số.

    Chặt hơn "xe đang chuyển động", và là chủ ý: các hãng khoá video theo số P. Ai đổi
    luật sang `speed_kph > 0` sẽ làm đỏ đúng test này.
    """
    vehicle, store = InProcessVehicleGateway.new(speed_kph=0.0, gear="D"), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Mở Spotify")

    assert result["outcome"] == "blocked"
    assert store.pending_for_session("ses-safety") is None

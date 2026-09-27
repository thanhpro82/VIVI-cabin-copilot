"""IviEventBus — pub/sub theo session_id, nguồn phát sự kiện cho /ws/ivi."""

import base64

import pytest

from src.agents.contracts import ActionPlan, PlanStep, ToolResult
from src.services import voice
from src.services.ivi_events import (
    RING_BUFFER_SIZE,
    IviEventBus,
    assistant_response_payload,
    emit_turn_lifecycle,
    get_event_bus,
)


@pytest.fixture(autouse=True)
def _stub_tts_unavailable(monkeypatch):
    """TTS luôn thất bại mặc định trong file này — không phụ thuộc việc máy chạy test
    có sẵn model Piper thật hay không (issue #66). Test nào cần audio thành công tự
    override bằng monkeypatch.setattr(voice, "synthesize_wav", ...) riêng trong thân test."""

    def _raise(text):
        raise FileNotFoundError("no TTS model in test environment")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)


async def test_publish_delivers_to_listener_of_same_session():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {"status": "accepted", "input_mode": "voice"})

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "turn.accepted"
    assert event["session_id"] == "ses-a"
    assert event["turn_id"] == "turn-1"
    assert event["trace_id"] == "tr-1"
    assert event["payload"] == {"status": "accepted", "input_mode": "voice"}
    assert event["sequence"] == 1
    assert set(event) >= {
        "type",
        "event_id",
        "sequence",
        "trace_id",
        "emitted_at",
        "schema_version",
        "payload",
        "session_id",
        "turn_id",
    }


async def test_publish_does_not_leak_across_sessions():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-b", "turn.accepted", "turn-1", "tr-1", {})

    assert received == []


async def test_remove_listener_stops_delivery():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    bus.remove_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    assert received == []


async def test_publish_delivers_to_multiple_listeners_in_order():
    bus = IviEventBus()
    order = []

    async def first(event):
        order.append("first")

    async def second(event):
        order.append("second")

    bus.add_listener("ses-a", first)
    bus.add_listener("ses-a", second)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    assert order == ["first", "second"]


def test_get_event_bus_returns_the_same_singleton():
    assert get_event_bus() is get_event_bus()


async def test_broken_listener_does_not_prevent_delivery_to_sibling_listeners():
    """Verify that a listener that raises an exception doesn't prevent delivery to other listeners."""
    bus = IviEventBus()
    received = []

    async def broken_listener(event):
        raise ValueError("Listener connection broken (e.g., WS disconnect)")

    async def working_listener(event):
        received.append(event)

    bus.add_listener("ses-a", broken_listener)
    bus.add_listener("ses-a", working_listener)

    # publish() must not raise, despite broken_listener raising
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {"status": "accepted"})

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "turn.accepted"
    assert event["session_id"] == "ses-a"
    assert event["turn_id"] == "turn-1"
    assert event["trace_id"] == "tr-1"
    assert event["payload"] == {"status": "accepted"}


async def test_sequence_increments_monotonically_across_multiple_publishes():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    await bus.publish("ses-a", "assistant.response", "turn-1", "tr-1", {})

    assert [event["sequence"] for event in received] == [1, 2]
    assert received[0]["event_id"] != received[1]["event_id"]


async def test_ring_buffer_caps_at_200_events_per_session():
    bus = IviEventBus()

    for i in range(RING_BUFFER_SIZE + 50):
        await bus.publish("ses-a", "assistant.status", f"turn-{i}", "tr-1", {"i": i})

    stream = bus._streams["ses-a"]
    assert len(stream.buffer) == RING_BUFFER_SIZE
    assert stream.buffer[0]["sequence"] == 51
    assert stream.buffer[-1]["sequence"] == 250
    assert stream.sequence == 250


async def test_replay_snapshot_returns_empty_for_a_fresh_connection_without_cursor():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    error, events = bus.replay_snapshot("ses-a", None, None)

    assert error is None
    assert events == []


async def test_replay_snapshot_returns_events_after_the_cursor_in_order():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    await bus.publish("ses-a", "assistant.status", "turn-1", "tr-1", {"state": "routing"})
    await bus.publish("ses-a", "assistant.response", "turn-1", "tr-1", {"display_text": "ok"})
    first = bus._streams["ses-a"].buffer[0]

    error, events = bus.replay_snapshot("ses-a", first["event_id"], first["sequence"])

    assert error is None
    assert [event["type"] for event in events] == ["assistant.status", "assistant.response"]
    assert [event["sequence"] for event in events] == [2, 3]


async def test_replay_snapshot_rejects_a_cursor_missing_one_field():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    error, events = bus.replay_snapshot("ses-a", "evt_nope", None)

    assert error == "REPLAY_CURSOR_INVALID"
    assert events == []


async def test_replay_snapshot_rejects_a_sequence_never_issued():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    error, events = bus.replay_snapshot("ses-a", "evt_future", 999)

    assert error == "REPLAY_CURSOR_INVALID"
    assert events == []


async def test_replay_snapshot_rejects_a_mismatched_event_id_sequence_pair():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    real = bus._streams["ses-a"].buffer[0]

    error, events = bus.replay_snapshot("ses-a", "evt_wrong", real["sequence"])

    assert error == "REPLAY_CURSOR_INVALID"
    assert events == []


async def test_replay_snapshot_returns_window_expired_once_the_cursor_falls_out_of_the_ring_buffer():
    bus = IviEventBus()
    for i in range(RING_BUFFER_SIZE + 5):
        await bus.publish("ses-a", "assistant.status", f"turn-{i}", "tr-1", {"i": i})

    error, events = bus.replay_snapshot("ses-a", "evt_does_not_matter", 1)

    assert error == "REPLAY_WINDOW_EXPIRED"
    assert events == []


class _RecordingBus:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, session_id, event_type, turn_id, trace_id, payload):
        self.events.append(
            {"type": event_type, "session_id": session_id, "turn_id": turn_id, "trace_id": trace_id, "payload": payload}
        )


class _FakeInterrupt:
    def __init__(self, value):
        self.value = value


def test_assistant_response_payload_giu_preview_va_non_routine_tra_null():
    preview = {
        "routine_id": "rtn_1",
        "routine_name": "Về nhà",
        "steps": [{"index": 0, "action": "navigation", "description": "dẫn đường tới Nhà"}],
    }

    assert assistant_response_payload({"response_text": "Xem trước", "routine_preview": preview})[
        "routine_preview"
    ] == preview
    assert assistant_response_payload({"response_text": "Bật điều hòa"})["routine_preview"] is None


async def test_lifecycle_phat_routine_preview_trong_assistant_response():
    bus = _RecordingBus()
    preview = {
        "routine_id": "rtn_1",
        "routine_name": "Về nhà",
        "steps": [{"index": 0, "action": "navigation", "description": "dẫn đường tới Nhà"}],
    }

    await emit_turn_lifecycle(
        bus,
        "ses-1",
        "turn-1",
        "tr-1",
        {"outcome": "routine_preview", "response_text": "Xem trước", "routine_preview": preview},
    )

    response = next(event for event in bus.events if event["type"] == "assistant.response")
    assert response["payload"]["routine_preview"] == preview


def _plan(*, requires_approval=False) -> ActionPlan:
    return ActionPlan(
        schema_version="1.0",
        plan_id="plan-1",
        session_id="ses-1",
        vehicle_id="veh-demo",
        vehicle_state_version=1,
        steps=[
            PlanStep(
                step_id="step-1",
                ordinal=1,
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                safety_level="S1",
                depends_on=[],
            )
        ],
        requires_approval=requires_approval,
    )


async def test_completed_outcome_emits_executing_tool_result_response_completed():
    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 24 độ.",
        "step_results": [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                status="completed",
                before={"state_version": 1},
                after={"state_version": 2},
                observed_state_version=2,
            )
        ],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["plan.ready", "assistant.status", "tool.result", "assistant.response", "turn.completed"]
    assert bus.events[1]["payload"]["state"] == "executing"
    assert bus.events[2]["payload"] == {
        "step_id": "step-1",
        "command_id": "plan-1:step-1",
        "status": "completed",
        "observed_state_version": 2,
        "error_code": None,
    }
    assert bus.events[3]["payload"]["display_text"] == "Đã đặt điều hòa 24 độ."
    assert bus.events[4]["payload"]["status"] == "completed"


async def test_execution_failed_outcome_ends_in_turn_failed():
    bus = _RecordingBus()
    result = {
        "outcome": "execution_failed",
        "response_text": "Không thực hiện được đầy đủ lệnh.",
        "step_results": [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                status="failed",
                before={"state_version": 1},
                after={"state_version": 1},
                error_code="SAFETY_BLOCKED",
            )
        ],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["plan.ready", "assistant.status", "tool.result", "assistant.response", "turn.failed"]
    assert bus.events[-1]["payload"]["code"] == "EXECUTION_FAILED"


async def test_blocked_outcome_emits_action_blocked_before_response():
    bus = _RecordingBus()
    result = {
        "outcome": "blocked",
        "response_text": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép.",
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["plan.ready", "action.blocked", "assistant.response", "turn.completed"]
    assert bus.events[1]["payload"] == {
        "plan_id": "plan-1",
        "code": "SAFETY_BLOCKED",
        "reason": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép.",
    }


async def test_grounded_answer_outcome_emits_retrieving_then_composing():
    bus = _RecordingBus()
    result = {"outcome": "grounded_answer", "response_text": "Đây là thông tin tôi tìm được.", "citations": []}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "assistant.status", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"]["state"] == "retrieving"
    assert bus.events[1]["payload"]["state"] == "composing"


async def test_clarify_outcome_skips_retrieving_and_goes_straight_to_composing():
    bus = _RecordingBus()
    result = {"outcome": "clarify", "response_text": "Bạn muốn điều chỉnh cụ thể như thế nào?"}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"]["state"] == "composing"


async def test_skipped_step_publishes_a_wire_safe_tool_result_status():
    """`ToolStatus` nội bộ có `skipped`, hợp đồng dây thì không — phải dịch trước khi publish."""
    bus = _RecordingBus()
    result = {
        "outcome": "execution_failed",
        "response_text": "Không thực hiện được đầy đủ lệnh.",
        "step_results": [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                tool="set_window_position",
                args={"window": "front_left", "percent": 30},
                status="failed",
                before={"state_version": 1},
                after={"state_version": 1},
                error_code="unsafe_vehicle_state",
            ),
            ToolResult(
                command_id="plan-1:step-2",
                step_id="step-2",
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                status="skipped",
                before={"state_version": 1},
                after={"state_version": 1},
                error_code="skipped_due_to_prior_failure",
            ),
        ],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    tool_results = [event for event in bus.events if event["type"] == "tool.result"]
    assert [event["payload"]["status"] for event in tool_results] == ["failed", "skipped_due_to_prior_failure"]
    response = next(event for event in bus.events if event["type"] == "assistant.response")
    assert response["payload"]["outcomes"] == [
        {"step_id": "step-1", "status": "failed"},
        {"step_id": "step-2", "status": "skipped_due_to_prior_failure"},
    ]
    # Không giá trị nào lọt ra ngoài enum `ToolResultStatus` của api_spec.md.
    wire_enum = {"completed", "failed", "timeout", "skipped_due_to_prior_failure", "skipped_external_state_change"}
    assert {event["payload"]["status"] for event in tool_results} <= wire_enum


async def test_rejected_step_maps_to_failed_and_keeps_its_error_code():
    bus = _RecordingBus()
    result = {
        "outcome": "execution_failed",
        "response_text": "Trạng thái xe đã đổi.",
        "step_results": [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                tool="set_window_position",
                args={"window": "front_left", "percent": 30},
                status="rejected",
                before={"state_version": 1},
                after={"state_version": 2},
                error_code="stale_state",
            )
        ],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    tool_result = next(event for event in bus.events if event["type"] == "tool.result")
    assert tool_result["payload"]["status"] == "failed"
    assert tool_result["payload"]["error_code"] == "stale_state"


async def test_approval_expired_outcome_ends_in_turn_canceled_with_reason():
    bus = _RecordingBus()
    result = {"outcome": "approval_expired", "response_text": "Yêu cầu xác nhận đã hết hạn."}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.response", "turn.canceled"]
    assert bus.events[1]["payload"]["status"] == "canceled"
    assert bus.events[1]["payload"]["reason"] == "approval_expired"


async def test_every_approval_fail_closed_outcome_cancels_with_a_documented_reason():
    """`request_approval_node` có 6 đường hỏng; không đường nào được báo `turn.completed`."""
    documented_reasons = {
        "approval_rejected",
        "approval_expired",
        "approval_invalidated_state",
        "approval_invalidated_plan",
        "approval_predicate_failed",
        "approval_not_pending",
        "user_canceled",
    }
    outcomes = [
        "approval_rejected",
        "approval_expired",
        "approval_invalidated_state",
        "approval_invalidated_plan",
        "approval_predicate_failed",
        "approval_not_owned",
    ]
    for outcome in outcomes:
        bus = _RecordingBus()
        await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", {"outcome": outcome, "response_text": "Đã hủy."})
        assert [event["type"] for event in bus.events] == ["assistant.response", "turn.canceled"], outcome
        assert bus.events[1]["payload"]["reason"] in documented_reasons, outcome


async def test_interrupt_emits_approval_required_then_waiting_approval_and_stops():
    bus = _RecordingBus()
    result = {
        "__interrupt__": [
            _FakeInterrupt(
                {
                    "kind": "vehicle_action_approval",
                    "approval_id": "appr-1",
                    "plan_id": "plan-1",
                    "prompt_text": "Tôi sẽ mở cửa sổ bên lái. Bạn có đồng ý không?",
                    "steps_summary": [{"tool": "set_window_position", "safety_level": "S2"}],
                    "expires_at": "2026-08-09T00:00:30Z",
                    "timeout_seconds": 30,
                }
            )
        ],
        "action_plan": _plan(requires_approval=True),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["plan.ready", "approval.required", "assistant.status"]
    assert bus.events[1]["payload"] == {
        "approval_id": "appr-1",
        "plan_id": "plan-1",
        "approved_vehicle_state_version": 1,
        "actions": [{"tool": "set_window_position", "safety_level": "S2"}],
        "expires_at": "2026-08-09T00:00:30Z",
    }
    assert bus.events[2]["payload"]["state"] == "waiting_approval"


# --------------------------------------------------------------------------
# `plan.ready` — docs/api_spec.md:561,620
# --------------------------------------------------------------------------
#
# Sự kiện này thuộc **giai đoạn định tuyến**, phát trước khi rẽ nhánh chính sách,
# nên nó bắn cho mọi lượt điều khiển chứ không riêng lượt cần duyệt — đó là lý do
# `requires_approval` là boolean chứ không phải một cờ luôn đúng.
#
# `frontend/src/components/ivi/HitlModal.tsx:59` render `Bạn xác nhận: {summary}?`
# nên `summary` phải là **cụm động từ**, không phải câu hoàn chỉnh. Dùng
# `prompt_text` của approval record ở đây sẽ ra "Bạn xác nhận: Xe đang chạy 40
# km/h. Tôi sẽ .... Bạn có đồng ý không??".


async def test_control_turn_needing_approval_emits_plan_ready_before_approval_required():
    bus = _RecordingBus()
    result = {
        "__interrupt__": [
            _FakeInterrupt(
                {
                    "kind": "vehicle_action_approval",
                    "approval_id": "appr-1",
                    "plan_id": "plan-1",
                    "prompt_text": "Tôi sẽ mở cửa sổ bên lái. Bạn có đồng ý không?",
                    "steps_summary": [{"tool": "set_window_position", "safety_level": "S2"}],
                    "expires_at": "2026-08-09T00:00:30Z",
                    "timeout_seconds": 30,
                }
            )
        ],
        "action_plan": _plan(requires_approval=True),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types[0] == "plan.ready"
    assert types.index("plan.ready") < types.index("approval.required")
    assert bus.events[0]["payload"] == {
        "route_kind": "action",
        "plan_id": "plan-1",
        "summary": "đặt điều hòa ở 24 độ",
        "requires_approval": True,
        "steps": [
            {
                "step_id": "step-1",
                "tool": "set_hvac_temperature",
                "domain": "hvac",
                "args": {"temperature_c": 24},
            }
        ],
    }


async def test_control_turn_without_approval_still_emits_plan_ready_first():
    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 24 độ.",
        "step_results": [],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types[0] == "plan.ready"
    assert bus.events[0]["payload"]["requires_approval"] is False


async def test_blocked_turn_emits_plan_ready_before_action_blocked():
    """S3 vẫn có kế hoạch — nó bị chặn *sau khi* đã lập, nên tài xế phải thấy thứ bị chặn là gì."""
    bus = _RecordingBus()
    result = {
        "outcome": "blocked",
        "response_text": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép.",
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types.index("plan.ready") < types.index("action.blocked")


async def test_plan_ready_summary_reads_as_a_verb_phrase_for_the_confirm_sentence():
    """`HitlModal.tsx:59` ghép "Bạn xác nhận: {summary}?" nên summary không được là câu hoàn chỉnh."""
    bus = _RecordingBus()
    result = {"outcome": "completed", "response_text": "xong", "step_results": [], "action_plan": _plan()}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    summary = bus.events[0]["payload"]["summary"]
    assert summary == "đặt điều hòa ở 24 độ"
    assert not summary.endswith(".")
    assert "Bạn có đồng ý không" not in summary


async def test_manual_lookup_turn_never_emits_plan_ready():
    """Không có kế hoạch thì không có `plan.ready` — `mock.test.ts:167` khoá đúng chiều này."""
    bus = _RecordingBus()
    result = {"outcome": "grounded_answer", "response_text": "Đây là thông tin tôi tìm được.", "citations": []}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    assert "plan.ready" not in [event["type"] for event in bus.events]


async def test_tool_result_reports_observed_version_even_when_after_is_empty():
    """`observed_state_version` phải là field tường minh, không phải moi từ `after`.

    Nhánh `_local_failure` của executor trả `after={}`, nên đọc
    `step.after.get("state_version")` cho ra `None` — trong khi bước đó **có** quan sát
    được version. Hợp đồng dây (api_spec.md:565) nói null chỉ dành cho trường hợp không
    quan sát được gì.
    """
    bus = _RecordingBus()
    result = {
        "outcome": "execution_failed",
        "response_text": "Không thực hiện được lệnh.",
        "step_results": [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                status="failed",
                before={},
                after={},
                observed_state_version=7,
                error_code="TOOL_UNAVAILABLE",
            )
        ],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    tool_event = next(event for event in bus.events if event["type"] == "tool.result")
    assert tool_event["payload"]["observed_state_version"] == 7


from src.services.ivi_events import _BUFFER_TTL_SECONDS, _STREAM_TTL_SECONDS  # noqa: E402


async def test_buffer_ttl_clears_the_buffer_but_keeps_sequence_when_idle_with_no_listeners():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    bus._streams["ses-a"].last_active -= _BUFFER_TTL_SECONDS + 1

    # publish() sweeps at the start, before recording this new event.
    await bus.publish("ses-a", "assistant.status", "turn-1", "tr-1", {"state": "routing"})

    stream = bus._streams["ses-a"]
    assert [event["sequence"] for event in stream.buffer] == [2]
    assert stream.sequence == 2


async def test_stream_ttl_removes_the_entry_entirely_when_idle_with_no_listeners():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    bus._streams["ses-a"].last_active -= _STREAM_TTL_SECONDS + 1

    await bus.publish("ses-b", "turn.accepted", "turn-2", "tr-2", {})

    assert "ses-a" not in bus._streams


async def test_speech_synthesis_success_emits_assistant_speech_before_assistant_response(monkeypatch):
    monkeypatch.setattr(voice, "synthesize_wav", lambda text: b"FAKE-WAV-BYTES")

    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 24 độ.",
        "step_results": [],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types.index("assistant.speech") == types.index("assistant.response") - 1
    speech_payload = bus.events[types.index("assistant.speech")]["payload"]
    assert speech_payload["mime_type"] == "audio/wav"
    assert base64.b64decode(speech_payload["audio_base64"]) == b"FAKE-WAV-BYTES"


async def test_empty_response_text_does_not_synthesize_speech(monkeypatch):
    def _fail_if_called(text):
        raise AssertionError("synthesize_wav should not be called for empty text")

    monkeypatch.setattr(voice, "synthesize_wav", _fail_if_called)

    bus = _RecordingBus()
    result = {"outcome": "not_control", "response_text": ""}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert "assistant.speech" not in types
    assert "assistant.response" in types


async def test_speech_synthesis_failure_is_swallowed_and_does_not_block_lifecycle(monkeypatch):
    def _raise(text):
        raise RuntimeError("piper model missing")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)

    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 24 độ.",
        "step_results": [],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert "assistant.speech" not in types
    assert types[-1] == "turn.completed"
    assert bus.events[types.index("assistant.response")]["payload"]["display_text"] == "Đã đặt điều hòa 24 độ."


async def test_pending_approval_never_synthesizes_speech(monkeypatch):
    def _fail_if_called(text):
        raise AssertionError("synthesize_wav should not be called while a turn is waiting on approval")

    monkeypatch.setattr(voice, "synthesize_wav", _fail_if_called)

    bus = _RecordingBus()
    result = {
        "__interrupt__": [
            _FakeInterrupt(
                {
                    "approval_id": "appr-1",
                    "plan_id": "plan-1",
                    "prompt_text": "Bạn xác nhận: mở cửa sổ?",
                    "steps_summary": [{"tool": "set_window_position", "safety_level": "S2"}],
                    "expires_at": "2026-08-09T00:00:30Z",
                    "timeout_seconds": 30,
                }
            )
        ],
        "action_plan": _plan(requires_approval=True),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert "assistant.speech" not in types
    assert "assistant.response" not in types


async def test_a_session_with_a_live_listener_is_never_swept_even_when_idle():
    bus = IviEventBus()

    async def listener(event):
        pass

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    bus._streams["ses-a"].last_active -= _STREAM_TTL_SECONDS + 1

    await bus.publish("ses-b", "turn.accepted", "turn-2", "tr-2", {})

    stream = bus._streams["ses-a"]
    assert len(stream.buffer) == 1
    assert stream.sequence == 1


async def test_replay_snapshot_does_not_create_a_stream_entry_for_an_unknown_session():
    bus = IviEventBus()

    error, events = bus.replay_snapshot("ses-never-existed", "evt_x", 5)

    assert error == "REPLAY_CURSOR_INVALID"
    assert events == []
    assert "ses-never-existed" not in bus._streams


async def test_replay_snapshot_sweeps_expired_buffers_itself_before_validating_the_cursor():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    stale = bus._streams["ses-a"].buffer[0]
    bus._streams["ses-a"].last_active -= _BUFFER_TTL_SECONDS + 1

    # No publish()/add_listener() happens in between, so only replay_snapshot()
    # itself can trigger the sweep that expires the buffer.
    error, events = bus.replay_snapshot("ses-a", stale["event_id"], stale["sequence"])

    assert error == "REPLAY_WINDOW_EXPIRED"
    assert events == []


async def test_assistant_response_carries_citation_id_so_the_card_is_clickable():
    """Không có `citation_id` thì FE có thẻ citation nhưng không gọi được `#7`.

    `frontend/src/lib/services/turn/real.ts:223` gọi `getCitation(citationId)`; id đó
    chỉ có thể đến từ payload này.
    """
    from src.rag.models import Citation

    bus = _RecordingBus()
    citation = Citation(
        citation_id="cit_abc123",
        turn_id="turn-1",
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="Công tắc khoá cửa sổ điện.",
        retrieval_score=0.9,
    )
    result = {"outcome": "grounded_answer", "response_text": "…", "citations": [citation]}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    response = next(event for event in bus.events if event["type"] == "assistant.response")
    assert response["payload"]["citations"][0]["citation_id"] == "cit_abc123"


async def test_chitchat_outcome_flows_through_the_generic_tail():
    """Outcome `chitchat` không có nhánh riêng trong emit_turn_lifecycle — nó rơi vào
    đuôi tổng quát composing → assistant.response → turn.completed. Test này khoá điều
    đó lại: ai thêm nhánh riêng cho chitchat là phải sửa test này một cách có ý thức."""
    bus = _RecordingBus()
    result = {"outcome": "chitchat", "response_text": "Chào bạn, tôi là VIVI!", "citations": []}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"]["state"] == "composing"
    assert bus.events[1]["payload"]["display_text"] == "Chào bạn, tôi là VIVI!"


# --- Tran BYTE cho assistant.speech (do socket that, 14/08) -----------------


def test_tran_ky_tu_khong_du_de_giu_duoi_khung_websocket():
    """`MAX_SPEECH_CHARS = 400` **không** giữ nổi bất biến nó sinh ra để giữ.

    Đo socket thật ngày 14/08 (điều Thành đòi ở PR #109 — "không chỉ suy luận từ kích
    thước payload"): 240 ký tự → event 656,9 KiB = 64,2% khung 1 MiB. Ngoại suy tuyến
    tính, 400 ký tự → **1.102 KiB = 107,6%** — tức lưới cuối vẫn cho vượt khung.

    Ký tự là **sai đơn vị**: cái phải giữ dưới trần là số byte trên dây, mà tỷ lệ
    byte/ký tự phụ thuộc giọng, tần số lấy mẫu và ngôn ngữ — cả ba đều đổi được mà
    không ai sửa hằng số này.
    """
    from src.services.ivi_events import MAX_SPEECH_BYTES

    khung = 1 << 20
    assert MAX_SPEECH_BYTES < khung, "tran byte phai duoi khung 1 MiB"
    # Chua chan 25%: base64 phinh 4/3, cong envelope JSON, cong header WS.
    assert MAX_SPEECH_BYTES <= int(khung * 0.75)


def test_audio_qua_lon_thi_bo_audio_chu_khong_bo_ca_luot():
    """Fail-open: mất tiếng còn hơn mất câu trả lời.

    `assistant.response` mang `display_text` — nội dung thật. Chặn cả lượt vì audio
    quá to là biến một sự cố thẩm mỹ thành mất dữ liệu.
    """
    from src.services.ivi_events import audio_qua_lon

    assert audio_qua_lon(b"x" * 10) is False
    assert audio_qua_lon(b"x" * (1 << 20)) is True
    assert audio_qua_lon(None) is False


def _plan_hai_buoc() -> ActionPlan:
    """Plan ghép hai domain khác nhau — ca duy nhất chứng minh `steps` giữ đúng thứ tự."""
    return ActionPlan(
        schema_version="1.0",
        plan_id="plan-2",
        session_id="ses-1",
        vehicle_id="veh-demo",
        vehicle_state_version=1,
        steps=[
            PlanStep(
                step_id="step-1",
                ordinal=1,
                tool="set_hvac_temperature",
                args={"temperature_c": 22},
                safety_level="S1",
                depends_on=[],
            ),
            PlanStep(
                step_id="step-2",
                ordinal=2,
                tool="media_control",
                args={"action": "play"},
                safety_level="S1",
                depends_on=["step-1"],
            ),
        ],
        requires_approval=False,
    )


async def test_plan_ready_mang_steps_dung_thu_tu_va_dung_domain():
    """`steps` là thứ duy nhất trong allowlist nói được **cái gì vừa được lập kế hoạch**.

    Không có nó thì lượt bằng giọng nói — `202` async, chỉ có WebSocket để bám — không
    có cách nào biết vừa bật điều hòa hay vừa mở nhạc.

    Thứ tự phải khớp thứ tự bước: client lấy bước completed *đầu tiên* có ánh xạ để
    quyết định hiển thị, nên đảo thứ tự là đổi hành vi nhìn thấy được.
    """
    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 22 độ và phát nhạc.",
        "step_results": [],
        "action_plan": _plan_hai_buoc(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-2", "tr-2", result)

    steps = bus.events[0]["payload"]["steps"]
    assert steps == [
        {"step_id": "step-1", "tool": "set_hvac_temperature", "domain": "hvac", "args": {"temperature_c": 22}},
        {"step_id": "step-2", "tool": "media_control", "domain": "media", "args": {"action": "play"}},
    ]


async def test_plan_ready_phat_domain_none_cho_tool_cuc_bo():
    """Tool không đi qua MQTT phát `domain: null`, không phát một domain bịa ra.

    `Domain` là enum lái topic MQTT. Nhét một giá trị giả vào đó cho tool cục bộ sẽ làm
    hỏng ADR-013 để đổi lấy sự gọn gàng hình thức. Client phân biệt bằng `tool` + `args`
    — đó là lý do `args` nằm trong payload.
    """
    bus = _RecordingBus()
    plan = ActionPlan(
        schema_version="1.0",
        plan_id="plan-3",
        session_id="ses-1",
        vehicle_id="veh-demo",
        vehicle_state_version=1,
        steps=[
            PlanStep(
                step_id="step-1",
                ordinal=1,
                tool="search_nearby_poi",
                args={},
                safety_level="S0",
                depends_on=[],
            )
        ],
        requires_approval=False,
    )
    result = {"outcome": "completed", "response_text": "ok", "step_results": [], "action_plan": plan}

    await emit_turn_lifecycle(bus, "ses-1", "turn-3", "tr-3", result)

    assert bus.events[0]["payload"]["steps"][0]["domain"] is None


async def test_plan_ready_van_phat_steps_o_luot_bi_chan():
    """Lượt S3 vẫn có `steps`, và đó là chủ ý — nhưng nó **không** phải tín hiệu đổi màn.

    `plan.ready` bắn ở giai đoạn định tuyến, trước nhánh chính sách, nên nó có mặt cả ở
    lượt bị chặn: tài xế cần thấy *thứ bị chặn là gì*. Client nào chuyển màn ngay khi
    nhận event này sẽ mở video xong rồi mới bị chặn — mốc đúng là `tool.result` với
    `status="completed"`, mà lượt bị chặn không bao giờ sinh ra (ADR-023).

    Test này khoá cả hai vế: `steps` có mặt, và **không** có `tool.result` nào.
    """
    bus = _RecordingBus()
    result = {
        "outcome": "blocked",
        "response_text": "Không mở được khi xe đang chạy.",
        "step_results": [],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-4", "tr-4", result)

    types = [event["type"] for event in bus.events]
    assert types[0] == "plan.ready"
    assert bus.events[0]["payload"]["steps"], "lượt bị chặn vẫn phải nói rõ thứ bị chặn là gì"
    assert "tool.result" not in types

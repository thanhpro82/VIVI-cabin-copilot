"""src/models/api.py — vỏ response mới cho /auth/login, /sessions, /turns/text.

Chỉ kiểm hai bất biến: field bắt buộc đúng tên/kiểu, và `extra="forbid"` chặn field
lạ (giữ hợp đồng đóng, cùng quy ước với `VehicleStateEnvelope` đã có trong file).
"""

import pytest
from pydantic import ValidationError

from src.models.api import (
    ActionPlanData,
    ActionPlanStep,
    LoginData,
    LoginEnvelope,
    LoginUser,
    Meta,
    PendingApprovalData,
    SessionData,
    SessionEnvelope,
    TextTurnData,
    TextTurnEnvelope,
    TurnResponseData,
)


def _action_plan() -> ActionPlanData:
    return ActionPlanData(
        schema_version="1.0",
        plan_id="plan_1",
        session_id="ses_1",
        vehicle_id="vehicle-demo-01",
        vehicle_state_version=1,
        steps=[
            ActionPlanStep(
                step_id="step_1",
                ordinal=1,
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                safety_level="S1",
                depends_on=[],
            )
        ],
        requires_approval=False,
    )


def test_login_envelope_round_trips_the_spec_example_shape():
    envelope = LoginEnvelope(
        data=LoginData(
            access_token="tok",
            expires_at="2026-07-31T10:30:00Z",
            user=LoginUser(user_id="usr_driver_01", role="driver", display_name="Demo Driver"),
        ),
        meta=Meta(request_id="req_1"),
        trace_id="tr_1",
    )
    dumped = envelope.model_dump(mode="json")
    assert dumped["data"]["token_type"] == "Bearer"
    assert dumped["data"]["user"]["role"] == "driver"
    assert dumped["schema_version"] == "1.0"


def test_login_user_rejects_an_unknown_role():
    with pytest.raises(ValidationError):
        LoginUser(user_id="usr_1", role="admin", display_name="x")


def test_session_envelope_round_trips():
    envelope = SessionEnvelope(
        data=SessionData(
            session_id="ses_1", vehicle_id="vehicle-demo-01", status="active", started_at="2026-07-31T10:00:00Z"
        ),
        meta=Meta(request_id="req_1"),
        trace_id="tr_1",
    )
    assert envelope.model_dump(mode="json")["data"]["status"] == "active"


def test_action_plan_step_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ActionPlanStep(
            step_id="s1",
            ordinal=1,
            tool="set_hvac_temperature",
            args={},
            safety_level="S1",
            depends_on=[],
            unexpected="nope",
        )


def test_text_turn_data_completed_has_no_pending_approval_by_default():
    data = TextTurnData(
        session_id="ses_1",
        turn_id="turn_1",
        status="completed",
        action_plan=_action_plan(),
        response=TurnResponseData(display_text="d", speak_text="d", citations=[], outcomes=[]),
    )
    assert data.pending_approval is None


def test_text_turn_data_allows_a_null_action_plan_for_non_control_outcomes():
    data = TextTurnData(
        session_id="ses_1",
        turn_id="turn_1",
        status="completed",
        action_plan=None,
        response=TurnResponseData(display_text="d", speak_text="d", citations=[], outcomes=[]),
    )
    assert data.action_plan is None


def test_text_turn_envelope_carries_pending_approval_for_waiting_approval():
    envelope = TextTurnEnvelope(
        data=TextTurnData(
            session_id="ses_1",
            turn_id="turn_1",
            status="waiting_approval",
            action_plan=_action_plan(),
            pending_approval=PendingApprovalData(approval_id="appr-1", expires_at="2026-07-31T10:00:30Z"),
            response=TurnResponseData(display_text="d", speak_text="d", citations=[], outcomes=[]),
        ),
        meta=Meta(request_id="req_1"),
        trace_id="tr_1",
    )
    assert envelope.data.pending_approval.approval_id == "appr-1"

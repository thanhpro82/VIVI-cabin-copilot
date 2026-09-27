"""Hai invariant của contract, mỗi cái một test — chúng là lý do file này tồn tại."""

import pytest
from pydantic import ValidationError

from src.agents.contracts import (
    ActionPlan,
    CandidateActionPlan,
    CandidateStep,
    PlanStep,
    RouteDecision,
    ValidationDenied,
)


def _candidate() -> CandidateActionPlan:
    return CandidateActionPlan(
        steps=(
            CandidateStep(
                step_id="step-1",
                ordinal=0,
                tool="set_window_position",
                args={"window": "front_left", "percent": 30},
            ),
        )
    )


def test_candidate_step_refuses_safety_level():
    """Model/router không được phép tự gán safety — schema đóng chặn từ gốc."""
    with pytest.raises(ValidationError):
        CandidateStep(step_id="step-1", ordinal=0, tool="set_hvac_power", args={}, safety_level="S1")


def test_action_plan_refuses_s2_without_approval():
    with pytest.raises(ValidationError, match="requires_approval"):
        ActionPlan(
            plan_id="plan-1",
            session_id="ses-1",
            vehicle_id="veh-1",
            vehicle_state_version=1,
            requires_approval=False,
            steps=(PlanStep(step_id="step-1", ordinal=0, tool="set_window_position", args={}, safety_level="S2"),),
        )


def test_action_plan_accepts_s2_with_approval():
    plan = ActionPlan(
        plan_id="plan-1",
        session_id="ses-1",
        vehicle_id="veh-1",
        vehicle_state_version=1,
        requires_approval=True,
        steps=(PlanStep(step_id="step-1", ordinal=0, tool="set_window_position", args={}, safety_level="S2"),),
    )
    assert plan.requires_approval is True


def test_route_decision_control_requires_candidate_plan():
    with pytest.raises(ValidationError, match="requires candidate_plan"):
        RouteDecision(disposition="control", intent="window_position", reason="deterministic_rule")


@pytest.mark.parametrize("disposition", ["not_control", "clarify", "denied"])
def test_route_decision_non_control_forbids_candidate_plan(disposition):
    with pytest.raises(ValidationError, match="forbids candidate_plan"):
        RouteDecision(disposition=disposition, intent="none", reason="x", candidate_plan=_candidate())


def test_validation_denied_carries_subcode():
    error = ValidationDenied("range_invalid", "temperature_c out of range")
    assert error.subcode == "range_invalid"
    assert "temperature_c" in str(error)


def test_disposition_chitchat_hop_le_va_cam_mang_plan():
    """SP-1: chitchat là disposition mới, exclusive như not_control."""
    quyet_dinh = RouteDecision(disposition="chitchat", intent="none", reason="slm_classified_chitchat")
    assert quyet_dinh.candidate_plan is None
    with pytest.raises(ValidationError):
        RouteDecision(
            disposition="chitchat",
            intent="none",
            reason="slm_classified_chitchat",
            candidate_plan=_candidate(),
        )

from pathlib import Path

import pytest
from pydantic import ValidationError

from offline_poc.config import load_config
from offline_poc.contracts import ActionPlan, PlanStep


def test_config_has_two_required_q4_candidates() -> None:
    config = load_config(Path("config/benchmark.yaml"))
    required = {candidate.profile_id for candidate in config.candidates if candidate.required}

    assert required == {"qwen25-05b-q4", "qwen25-3b-q4"}


def test_action_plan_rejects_actuator_without_approval() -> None:
    with pytest.raises(ValidationError):
        ActionPlan(
            plan_id="plan-test",
            vehicle_state_version=1,
            requires_approval=False,
            steps=[
                PlanStep(
                    step_id="step-1",
                    tool="set_hvac_temperature",
                    args={"temperature_c": 24},
                    safety_level="S2",
                    depends_on=[],
                )
            ],
        )

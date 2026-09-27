from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SafetyLevel = Literal["S0", "S1", "S2", "S3"]


class PlanStep(BaseModel):
    step_id: str
    tool: str
    args: dict[str, Any]
    safety_level: SafetyLevel
    depends_on: list[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    plan_id: str
    vehicle_state_version: int = Field(ge=0)
    requires_approval: bool
    steps: list[PlanStep] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def actuator_requires_approval(self) -> "ActionPlan":
        if any(step.safety_level == "S2" for step in self.steps):
            if not self.requires_approval:
                raise ValueError("S2 step requires approval")
        return self


class ToolResult(BaseModel):
    command_id: str
    step_id: str
    status: Literal["completed", "rejected", "failed"]
    before: dict[str, Any]
    after: dict[str, Any]
    error_code: str | None = None
    latency_ms: float = Field(ge=0)


class GroundedClaim(BaseModel):
    text: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    section: str = Field(min_length=1)
    page: int = Field(ge=1)


class GroundedAnswer(BaseModel):
    answer_text: str = Field(min_length=1)
    claims: list[GroundedClaim] = Field(min_length=1)

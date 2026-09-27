"""Validator chung: allowlist, schema, khoảng giá trị, và đồ thị phụ thuộc.

Chạy **trước** phân loại S0-S3. Tool lạ hay args sai là `validation_denied`,
không phải S3 (`docs/safety_and_hitl.md` mục Core invariants).
"""

from src.agents.contracts import ValidationDenied, as_candidate_plan
from src.agents.state import AgentState
from src.agents.tools import validate_args


async def validate_node(state: AgentState) -> dict:
    candidate = as_candidate_plan(state["candidate_action_plan"])
    seen: set[str] = set()
    for step in candidate.steps:
        try:
            validate_args(step.tool, step.args)
        except ValidationDenied as exc:
            return {"outcome": "validation_denied", "error": exc.message, "error_subcode": exc.subcode}
        if not set(step.depends_on) <= seen:
            return {
                "outcome": "validation_denied",
                "error": f"step {step.step_id} phụ thuộc vào step chưa xuất hiện trước nó",
                "error_subcode": "args_invalid",
            }
        seen.add(step.step_id)
    return {"outcome": "validated"}

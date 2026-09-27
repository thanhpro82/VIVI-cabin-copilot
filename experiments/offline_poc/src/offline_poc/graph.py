from __future__ import annotations

import re
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from offline_poc.contracts import ActionPlan, PlanStep, ToolResult
from offline_poc.vehicle_mock import VehicleMock


Planner = Callable[[str, int, VehicleMock], ActionPlan]


class GraphState(TypedDict, total=False):
    input_text: str
    vehicle_state_version: int
    plan: ActionPlan
    outcome: str
    tool_results: list[ToolResult]
    response_text: str


def _default_planner(text: str, state_version: int, vehicle: VehicleMock) -> ActionPlan:
    lowered = text.casefold()
    number = re.search(r"\b(1[6-9]|2\d|30)\b", lowered)
    if ("điều hòa" in lowered or "nhiệt độ" in lowered) and number:
        return ActionPlan(
            plan_id="plan-hvac-temperature",
            vehicle_state_version=state_version,
            requires_approval=True,
            steps=[
                PlanStep(
                    step_id="step-1",
                    tool="set_hvac_temperature",
                    args={"temperature_c": int(number.group(1))},
                    safety_level="S2",
                )
            ],
        )

    if "mở cửa lái" in lowered or "mở cửa bên lái" in lowered:
        moving = vehicle.state["speed_kph"] != 0 or vehicle.state["gear"] != "P"
        return ActionPlan(
            plan_id="plan-open-driver-door",
            vehicle_state_version=state_version,
            requires_approval=not moving,
            steps=[
                PlanStep(
                    step_id="step-1",
                    tool="set_door_state",
                    args={"door": "front_left", "state": "open"},
                    safety_level="S3" if moving else "S2",
                )
            ],
        )

    raise ValueError("default PoC planner does not understand the request")


def build_graph(vehicle: VehicleMock, planner: Planner | None = None) -> Any:
    plan_request = planner or _default_planner

    def plan_node(state: GraphState) -> dict[str, Any]:
        plan = plan_request(
            state["input_text"], state["vehicle_state_version"], vehicle
        )
        return {"plan": plan, "outcome": "planned", "tool_results": []}

    def safety_node(state: GraphState) -> dict[str, str]:
        if any(step.safety_level == "S3" for step in state["plan"].steps):
            return {"outcome": "blocked"}
        return {"outcome": "safe"}

    def route_after_safety(state: GraphState) -> str:
        if state["outcome"] == "blocked":
            return "compose"
        if state["plan"].requires_approval:
            return "approval"
        return "execute"

    def approval_node(state: GraphState) -> dict[str, str]:
        plan = state["plan"]
        decision = interrupt(
            {
                "kind": "vehicle_action_approval",
                "plan_id": plan.plan_id,
                "vehicle_state_version": plan.vehicle_state_version,
                "steps": [step.model_dump() for step in plan.steps],
                "expires_in_seconds": 30,
            }
        )
        if not isinstance(decision, dict):
            return {"outcome": "rejected_by_user"}
        if float(decision.get("approval_age_seconds", 0)) > 30:
            return {"outcome": "approval_expired"}
        if decision.get("decision") != "approve":
            return {"outcome": "rejected_by_user"}
        approved_version = decision.get("state_version")
        if (
            approved_version != plan.vehicle_state_version
            or vehicle.state["state_version"] != plan.vehicle_state_version
        ):
            return {"outcome": "stale_state"}
        return {"outcome": "approved"}

    def route_after_approval(state: GraphState) -> str:
        return "execute" if state["outcome"] == "approved" else "compose"

    def execute_node(state: GraphState) -> dict[str, Any]:
        plan = state["plan"]
        expected_version = plan.vehicle_state_version
        results: list[ToolResult] = []
        completed_steps: set[str] = set()

        for step in plan.steps:
            if not set(step.depends_on) <= completed_steps:
                results.append(
                    ToolResult(
                        command_id=f"{plan.plan_id}:{step.step_id}",
                        step_id=step.step_id,
                        status="failed",
                        before=vehicle.state,
                        after=vehicle.state,
                        error_code="dependency_failed",
                        latency_ms=0,
                    )
                )
                continue
            result = vehicle.execute(
                f"{plan.plan_id}:{step.step_id}",
                expected_version,
                step.tool,
                step.args,
            )
            results.append(result)
            if result.status == "completed":
                completed_steps.add(step.step_id)
                expected_version = vehicle.state["state_version"]

        outcome = (
            "completed"
            if results and all(result.status == "completed" for result in results)
            else "execution_failed"
        )
        return {"tool_results": results, "outcome": outcome}

    def compose_node(state: GraphState) -> dict[str, str]:
        messages = {
            "completed": "Đã thực hiện lệnh mô phỏng.",
            "blocked": "Lệnh bị chặn vì trạng thái xe không an toàn.",
            "rejected_by_user": "Đã hủy theo lựa chọn của bạn.",
            "approval_expired": "Xác nhận đã hết hạn.",
            "stale_state": "Trạng thái xe đã thay đổi; vui lòng xác nhận lại.",
            "execution_failed": "Không thể thực hiện đầy đủ lệnh mô phỏng.",
        }
        return {"response_text": messages.get(state["outcome"], "Đã xử lý.")}

    builder = StateGraph(GraphState)
    builder.add_node("plan", plan_node)
    builder.add_node("safety", safety_node)
    builder.add_node("approval", approval_node)
    builder.add_node("execute", execute_node)
    builder.add_node("compose", compose_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "safety")
    builder.add_conditional_edges(
        "safety",
        route_after_safety,
        {"approval": "approval", "execute": "execute", "compose": "compose"},
    )
    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {"execute": "execute", "compose": "compose"},
    )
    builder.add_edge("execute", "compose")
    builder.add_edge("compose", END)
    return builder.compile(checkpointer=InMemorySaver())

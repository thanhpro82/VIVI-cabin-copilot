"""Node xin xác nhận cho plan có step S2.

Điểm cốt lõi: khi resume, node **đọc lại store**. Payload resume đi qua HTTP nên id
trong đó chỉ được dùng để **tra cứu**, không cấp quyền gì; quyền chỉ đến từ bản ghi
mà `decide()` đã ghi, và bản ghi đó còn phải khớp digest của plan hiện tại.

Bốn điều kiện phải cùng đúng mới được chạy. Cả bốn đường hỏng đều đi `compose` với
zero side effect và **không** consume approval, đúng `safety_and_hitl.md` mục
"Decision flow".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from langgraph.types import interrupt

from src.agents.approval import (
    ApprovalAlreadyPending,
    ApprovalRecord,
    ApprovalStore,
    approval_id_for,
)
from src.agents.contracts import ActionPlan, as_action_plan, as_candidate_plan
from src.agents.nodes.compose import describe_step
from src.agents.policy import materialize_action_plan, plan_digest
from src.agents.state import AgentState
from src.services.vehicle_gateway import VehicleGateway, snapshot_dict

#: Trạng thái store → outcome của graph, dùng khi bản ghi không ở `approved`.
_OUTCOME_BY_STATUS = {
    "pending": "approval_rejected",
    "rejected": "approval_rejected",
    "expired": "approval_expired",
    "invalidated": "approval_invalidated_state",
    "consumed": "approval_rejected",
}


def describe_plan_for_approval(plan: ActionPlan, snapshot: dict[str, Any]) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Câu hỏi voice-first + tóm tắt before→after cho card IVI.

    `safety_and_hitl.md` mục Approval UX contract cấm câu mơ hồ kiểu "Bạn có chắc
    không?" — phải nêu rõ action, target và before → after. Tốc độ hiện tại được
    đưa vào câu hỏi theo đúng UX mà ticket mô tả; nó là **nội dung hiển thị**, không
    phải điều kiện phân loại (ADR-010).
    """
    summaries: list[dict[str, Any]] = []
    for step in plan.steps:
        summaries.append(
            {
                "tool": step.tool,
                "safety_level": step.safety_level,
                "description": describe_step(step.tool, step.args),
                "before": _read_before(step.tool, step.args, snapshot),
                "after": _read_after(step.tool, step.args),
            }
        )
    actions = " rồi ".join(item["description"] for item in summaries)
    speed = snapshot.get("motion", {}).get("speed_kph", 0)
    prefix = f"Xe đang chạy {speed:g} km/h. " if speed else ""
    # Nói rõ **cách** trả lời, không chỉ hỏi có/không. Câu cũ ("Bạn có đồng ý không?")
    # là một câu hỏi đóng mà không mời gì cả, nên tài xế đưa tay ra màn hình theo phản
    # xạ — trong khi #191 muốn giọng nói là đường trả lời chính. Giữ ngắn: câu này đi
    # qua TTS và đứng sau phần mô tả hành động vốn đã dài.
    return f"{prefix}Tôi sẽ {actions}. Bạn nói đồng ý hoặc không.", tuple(summaries)


def _read_before(tool: str, args: dict[str, Any], snapshot: dict[str, Any]) -> Any:
    if tool == "set_window_position":
        return snapshot["windows"][args["window"]]
    if tool == "set_door_state":
        return snapshot["doors"][args["door"]]
    if tool == "set_seat_position":
        return snapshot["seat"][args["seat"]][args["axis"]]
    return None


def _read_after(tool: str, args: dict[str, Any]) -> Any:
    return {
        "set_window_position": args.get("percent"),
        "set_door_state": args.get("state"),
        "set_seat_position": args.get("value"),
    }.get(tool)


def make_request_approval_node(
    gateway: VehicleGateway, store: ApprovalStore, timeout_seconds: int
) -> Callable[[AgentState], Any]:
    async def request_approval_node(state: AgentState) -> dict:
        # Ép kiểu vì state đi qua checkpoint — xem `as_action_plan`.
        plan: ActionPlan = as_action_plan(state["action_plan"])
        digest = plan_digest(plan)
        prompt_text, steps_summary = describe_plan_for_approval(plan, state["vehicle_snapshot"])
        now = store.now()
        turn_id = str(state.get("turn_id", "turn-unknown"))
        record = ApprovalRecord(
            approval_id=approval_id_for(plan.session_id, turn_id, digest),
            session_id=plan.session_id,
            turn_id=turn_id,
            plan_id=plan.plan_id,
            plan_digest=digest,
            approved_vehicle_state_version=plan.vehicle_state_version,
            created_at=now,
            expires_at=now + timedelta(seconds=timeout_seconds),
            prompt_text=prompt_text,
            steps_summary=steps_summary,
        )
        try:
            # Idempotent: LangGraph chạy lại thân node từ đầu khi resume, nên hàm
            # này nhận đúng bản ghi này hai lần cho một lượt.
            record = store.create(record)
        except ApprovalAlreadyPending:
            return {"outcome": "approval_already_pending"}

        decision = interrupt(
            {
                "kind": "vehicle_action_approval",
                "approval_id": record.approval_id,
                "plan_id": record.plan_id,
                "prompt_text": record.prompt_text,
                "steps_summary": [dict(item) for item in record.steps_summary],
                "expires_at": record.expires_at.isoformat(),
                "timeout_seconds": timeout_seconds,
            }
        )

        # Từ đây trở xuống chỉ chạy sau khi resume.
        #
        # Id trong payload chỉ dùng để **tra cứu**, không cấp quyền gì. Nếu chỉ tra
        # bằng `record.approval_id` (suy từ digest của plan hiện tại) thì một
        # approval của plan khác sẽ không tìm thấy và rơi vào "state đã đổi" — sai
        # lý do, và nhánh so digest bên dưới thành code chết vì không bao giờ chạy
        # tới. Tra bằng id client gửi rồi **đối chiếu digest** mới bắt đúng bản chất:
        # đây là approval của một plan khác.
        claimed_id = decision.get("approval_id") if isinstance(decision, dict) else None
        fresh = store.get(claimed_id or record.approval_id)
        if fresh is None:
            return {"outcome": "approval_invalidated_state"}
        # Ràng buộc quyền sở hữu, kiểm **trước** mọi thứ khác. Store dùng chung cho mọi
        # phiên và id ở đây do client gửi, nên bản ghi tra được phải thuộc đúng phiên và
        # đúng lượt đang resume. Chốt digest bên dưới **không** thay được bước này: nó
        # chỉ tình cờ chặn được phiên khác vì `session_id` nằm trong plan, và nó im lặng
        # khi hai plan giống hệt nhau. Ràng buộc phải nói thẳng ra mới không vỡ khi
        # `ActionPlan` đổi field.
        if fresh.session_id != plan.session_id or fresh.turn_id != turn_id:
            return {"outcome": "approval_not_owned"}
        if fresh.status != "approved":
            return {"outcome": _OUTCOME_BY_STATUS.get(fresh.status, "approval_rejected")}
        if plan_digest(plan) != fresh.plan_digest:
            return {"outcome": "approval_invalidated_plan"}
        # Đọc state **sống** đúng lúc resume, không dùng lại snapshot chụp lúc lập kế
        # hoạch: cả hai kiểm tra dưới đây tồn tại chính vì xe có thể đã đổi trong lúc
        # chờ người duyệt. Đây là chỗ AC2 "state invalidation" thật sự đạt được — kiểm
        # version với một simulator không ai nhìn thấy thì chỉ đúng trên giấy.
        live = await gateway.snapshot()
        if live is None:
            # Nhánh fail-closed thứ năm, cùng họ với bốn nhánh sẵn có: không đọc được
            # trạng thái xe thì không có cách nào khẳng định approval còn hợp lệ.
            return {"outcome": "approval_invalidated_state"}
        if live.state_version != fresh.approved_vehicle_state_version:
            return {"outcome": "approval_invalidated_state"}

        # Predicate an toàn phải còn đúng: xe có thể đã lăn bánh trong lúc chờ, biến
        # một action S2 thành S3. Không có bước này thì approval cũ hợp thức hoá nó.
        #
        # `route_source` phải truyền lại **y hệt** `safety_node` (`safety.py`), nếu
        # không bước dựng lại này so một plan với một plan khác. `materialize_action_
        # _plan` tính `requires_approval = any(S2) or route_source == "slm"` (issue
        # #144), mà `plan_digest` băm **toàn bộ** `model_dump()` — nên bỏ tham số này
        # đi là mọi plan S0/S1 do planner đề xuất đều lệch digest đúng một trường
        # (`requires_approval: True → False`) và rơi xuống `approval_predicate_failed`.
        # Tài xế nghe "Xe không còn ở trạng thái an toàn cho lệnh này nữa" trong khi
        # xe đứng yên ở số P và chẳng có gì đổi: câu từ chối nói sai cả nguyên nhân
        # lẫn cách khắc phục. Đo được trên máy Sơn 20/08, và nó xảy ra 100% số lần —
        # xem docs/reports/dieu-tra-bug-buoi-test-2026-08-21.md §BUG-01.
        #
        # Nhánh S2 che mất lỗi này: ở đó cả hai phía đều ra `requires_approval=True`
        # nên digest trùng. Vì vậy đúng cái cổng mà #144 dựng lên để chặn plan SLM
        # "hợp schema nhưng sai ý" lại là cổng duy nhất không thể vượt qua.
        recomputed = materialize_action_plan(
            as_candidate_plan(state["candidate_action_plan"]),
            snapshot_dict(live),
            plan.session_id,
            plan.vehicle_id,
            route_source=state.get("route_source", "deterministic"),
        )
        if plan_digest(recomputed) != fresh.plan_digest:
            return {"outcome": "approval_predicate_failed"}

        store.consume(fresh.approval_id)
        return {"outcome": "approval_granted", "approval_id": fresh.approval_id}

    return request_approval_node

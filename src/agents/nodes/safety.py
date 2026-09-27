"""Materialize `ActionPlan` và phân loại S0-S3. Đây là node duy nhất gọi policy."""

import logging

from src.agents.contracts import as_candidate_plan
from src.agents.policy import materialize_action_plan
from src.agents.state import AgentState

logger = logging.getLogger(__name__)


async def safety_node(state: AgentState) -> dict:
    # Fail-closed: không đọc được trạng thái xe thì **từ chối**, đừng đoán. Phân loại
    # S2 hay S3 phụ thuộc `motion.speed_kph == 0 && gear == "P"`; đoán một giá trị ở
    # đây là tự cấp phép cho hành động lẽ ra phải chặn.
    #
    # Chặn ở đúng node này chứ không sớm hơn là có chủ đích: `safety_node` chỉ chạy
    # trên nhánh điều khiển, nên lượt tra sổ tay **không** bị chặn theo. Broker chết
    # mà mất luôn RAG thì là một regression vô cớ.
    if not state.get("vehicle_snapshot"):
        return {"outcome": "vehicle_state_unavailable"}
    plan = materialize_action_plan(
        as_candidate_plan(state["candidate_action_plan"]),
        state["vehicle_snapshot"],
        state.get("session_id", "ses-unknown"),
        state.get("vehicle_id", "veh-unknown"),
        # Nguồn gốc quyết định có phải hỏi lại hay không (issue #144). `graph.py` đặt
        # `route_source="slm"` khi planner sinh plan; mặc định là router luật.
        route_source=state.get("route_source", "deterministic"),
    )
    if any(step.safety_level == "S3" for step in plan.steps):
        # Plan do **SLM** đề xuất mà bị chặn S3 thì tài xế chưa từng yêu cầu hành động
        # ấy — nói "lệnh bị chặn" là sai sự thật, và nó còn vứt mất câu trả lời sổ tay
        # đang có. Lui về sổ tay nếu có, giữ `blocked` nếu không.
        #
        # Phân biệt bằng **nguồn gốc**, không bằng mức an toàn: khi chính tài xế nói
        # "mở cửa" lúc xe đang chạy thì `blocked` là câu trả lời đúng — họ cần biết vì
        # sao xe không làm, và che nó bằng một đoạn sổ tay là giấu một quyết định an
        # toàn. Cùng trục với ADR-021.
        #
        # Vẫn ghi log: planner liên tục đề xuất S3 là tín hiệu phải biết, không được
        # nuốt. Đây là điều kiện Thành đặt khi duyệt hướng sửa (#155).
        if state.get("route_source") == "slm" and state.get("citations"):
            logger.warning(
                "planner đề xuất hành động S3 không khớp yêu cầu; lui về câu trả lời sổ tay. tools=%s",
                [step.tool for step in plan.steps if step.safety_level == "S3"],
            )
            return {"outcome": "grounded_answer"}
        return {"action_plan": plan, "outcome": "blocked"}
    if plan.requires_approval:
        # Branch này chưa có HITL. Dừng ở đây là fail-closed, không phải bỏ sót:
        # `feature/hitl-safety-confirmation` sẽ cắm node request_approval vào đúng chỗ.
        return {"action_plan": plan, "outcome": "approval_required"}
    return {"action_plan": plan, "outcome": "safe"}

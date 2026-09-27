"""Chuẩn hóa input, dọn state của lượt trước, và chụp trạng thái xe cho lượt này."""

from typing import Any

from src.agents.router import normalize_vi
from src.agents.state import AgentState
from src.services.vehicle_gateway import VehicleGateway, snapshot_dict

#: Các channel **dẫn xuất theo lượt**: mỗi lượt tự sinh lại, không được thừa kế.
#:
#: Một phiên dùng chung `thread_id` vì `interrupt()` chỉ resume được trên đúng
#: checkpoint đó. Hệ quả: state của lượt trước còn nguyên khi lượt sau chạy, và
#: node chỉ ghi phần **đường đi của nó** đi qua. Lượt tra cứu sổ tay không chạm
#: tới `action_plan`, nên nó thừa kế `action_plan` của lệnh điều khiển trước đó và
#: API báo lượt hỏi ấy đã gọi `set_hvac_temperature` — một hành động không hề xảy
#: ra trong lượt này. Chiều ngược lại thì lệnh điều khiển dẫn nguồn sổ tay của lượt
#: hỏi trước.
#:
#: Dọn ở đây vì `normalize` là node vào của **mọi** lượt, và nó **không** chạy lại
#: khi resume sau `interrupt()` — LangGraph chạy lại thân node bị ngắt chứ không
#: chạy lại từ START — nên kế hoạch đang chờ xác nhận không bị xoá mất.
#:
#: `query`/`session_id`/`vehicle_id`/`turn_id` là input của lượt, không nằm đây.
_PER_TURN_RESET: dict[str, Any] = {
    "route_decision": None,
    "route_source": "",
    "route_reason": "",
    "intent": "none",
    "confidence": 0.0,
    "candidate_action_plan": None,
    "action_plan": None,
    "approval_id": "",
    "outcome": "",
    "step_results": [],
    "response_text": "",
    "chitchat_reply": "",
    "grounded_lead_in": "",
    "response": "",
    "error": "",
    "error_subcode": "",
    "evidence": [],
    "citations": [],
    "refusal_reason": "",
}


def make_normalize_node(gateway: VehicleGateway):
    async def normalize_node(state: AgentState) -> dict:
        # `snapshot()` chứ không phải `last_known()`: giá trị này đi thẳng vào phân
        # loại S0–S3. Đọc nhầm state cũ nghĩa là cấp thẻ xác nhận S2 cho hành động
        # lẽ ra phải chặn thẳng S3 — xem docstring `src/services/vehicle_gateway.py`.
        live = await gateway.snapshot()
        # `{}` chứ không phải state đoán: `safety_node` từ chối lượt khi thấy rỗng.
        # Đoán `speed_kph=0` ở đây sẽ biến một lệnh mở cửa S3 thành thẻ xác nhận S2,
        # đúng loại lỗi mà docs/safety_and_hitl.md tồn tại để chặn.
        #
        # Giữ là `dict` chứ không phải model: state này đi qua checkpoint LangGraph ở
        # chế độ msgpack chặt (tests/test_agents/test_hitl_node.py), nơi model pydantic
        # quay về `dict` lúc resume và `describe_plan_for_approval` sẽ vỡ — ở nhánh
        # resume HITL, đường ít được chạy nhất.
        snapshot = snapshot_dict(live) if live is not None else {}
        return {
            **_PER_TURN_RESET,
            "normalized_text": normalize_vi(state.get("query", "")),
            "vehicle_snapshot": snapshot,
            "vehicle_state_version": snapshot.get("state_version", 0),
        }

    return normalize_node

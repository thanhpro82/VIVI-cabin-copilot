"""`POST /api/v1/agent/process` — **dev-only**, không thuộc public surface P0.

`docs/api_spec.md` quy định P0 có **đúng 14 interface** và không có route xử lý
agent tổng quát nào. `frontend/docs/ARCHITECTURE.md` (2026-08-07) đã loại
`/agent/process` đích danh khi nhóm chốt dùng `api_spec.md` làm nguồn sự thật duy
nhất cho endpoint.

Route này vì vậy **không** được coi là API công khai:

- `include_in_schema=False` → không xuất hiện trong OpenAPI/`/docs`, nên không
  tính vào public surface và không ai build client dựa vào nó.
- Trả 404 khi `APP_ENV=production`.

Nó tồn tại để chạy thử agent qua HTTP trong lúc phát triển và demo, khi route
canonical `POST /api/v1/turns/text` chưa được implement. Khi có route đó, xoá file
này. Đừng cho FE gọi vào đây.

Response dùng **tên tool canonical** (`set_hvac_temperature`…), giống hệt tên
trong `ActionPlan` và trace. Bản đầu phơi ra alias kiểu `control_ac` theo
`docs/VIVI_API_Spec.md`; đã bỏ 2026-08-08 vì WS4 chốt dùng `api_spec.md` — giữ một
bộ tên end-to-end.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.session_state import get_graph, get_vehicle, thread_config
from src.config import get_settings

router = APIRouter()

#: Outcome nội bộ → `status` phơi ra API. `PENDING_HITL` thuộc branch HITL.
_STATUS_BY_OUTCOME = {
    "completed": "SUCCESS",
    "grounded_answer": "SUCCESS",
    "grounded_continue": "SUCCESS",
    "grounded_refusal": "NO_EVIDENCE",
    "approval_required": "APPROVAL_REQUIRED",
    # `offer` là câu hỏi khớp luật điều khiển: nêu việc sẽ làm rồi hỏi lại. Thiếu
    # khoá này thì nó rơi vào CLARIFY và IVI không phân biệt được "tôi chưa hiểu ý bạn"
    # với "tôi hiểu rõ, đang đề nghị làm việc này".
    "offer": "OFFER",
    "blocked": "BLOCKED",
    "clarify": "CLARIFY",
    "denied": "DENIED",
    "validation_denied": "DENIED",
    "execution_failed": "FAILED",
    "not_control": "CLARIFY",
}


class AgentProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    vehicle_speed_kmh: float = Field(default=0.0, ge=0.0, le=300.0)
    user_role: str = "driver"
    session_id: str = "ses-demo"


class AgentToolCall(BaseModel):
    tool_name: str
    parameters: dict


class AgentCitation(BaseModel):
    """Nguồn sổ tay đứng sau một câu trả lời tra cứu.

    Đây là tập con của `Citation` (`src/rag/models.py`) — 5 trường mà người dùng
    kiểm chứng được. `citation_id`/`turn_id`/`chunk_id` là định danh nội bộ, phơi
    ra chỉ tổ rối màn hình mà không giúp ai đối chiếu với quyển sổ tay.
    """

    document_title: str
    section: str
    page: int
    excerpt: str
    retrieval_score: float


class AgentProcessResponse(BaseModel):
    status: str
    intent: str
    response_text: str
    tool_calls: list[AgentToolCall] = []
    #: Rỗng với mọi lượt không đi qua sổ tay. `compose_node` trả đúng một câu cố
    #: định cho lượt tra cứu, nên **nội dung thật nằm ở đây** — thiếu nó thì IVI
    #: nói "đây là thông tin tôi tìm được" mà không có thông tin nào.
    citations: list[AgentCitation] = []
    hitl_pending: bool = False
    hitl_action_id: str | None = None
    timeout_seconds: int | None = None
    latency_ms: float = 0.0


@router.post("/agent/process", response_model=AgentProcessResponse, include_in_schema=False)
async def process(request: AgentProcessRequest) -> AgentProcessResponse:
    """Chạy thử agent qua HTTP. Dev-only — xem docstring đầu file."""
    if get_settings().app_env == "production":
        raise HTTPException(status_code=404, detail="Not Found")
    started_ns = time.perf_counter_ns()
    get_vehicle(request.session_id, request.vehicle_speed_kmh)
    graph = get_graph(request.session_id)
    result = await graph.ainvoke(
        {
            "query": request.query,
            "session_id": request.session_id,
            "vehicle_id": "veh-demo",
            "turn_id": f"turn-{started_ns}",
        },
        config=thread_config(request.session_id),
    )
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000

    pending = result.get("__interrupt__")
    if pending:
        # Graph dừng ở `interrupt`: lệnh S2 đang chờ người xác nhận. IVI hiển thị
        # `prompt_text` rồi gọi POST /api/v1/approvals/{id}/decision.
        payload = pending[0].value
        return AgentProcessResponse(
            status="PENDING_HITL",
            intent=result.get("intent", "none"),
            response_text=payload["prompt_text"],
            tool_calls=[
                AgentToolCall(tool_name=item["tool"], parameters={"after": item["after"]})
                for item in payload["steps_summary"]
            ],
            hitl_pending=True,
            hitl_action_id=payload["approval_id"],
            timeout_seconds=payload["timeout_seconds"],
            latency_ms=elapsed_ms,
        )

    outcome = result.get("outcome", "not_control")
    # `offer` dừng trước tầng policy nên không có `action_plan`; lấy từ candidate để IVI
    # biết đang đề nghị **việc gì** chứ không chỉ có câu văn.
    plan = result.get("action_plan") or (result.get("candidate_action_plan") if outcome == "offer" else None)
    tool_calls = [AgentToolCall(tool_name=step.tool, parameters=step.args) for step in plan.steps] if plan else []
    return AgentProcessResponse(
        status=_STATUS_BY_OUTCOME.get(outcome, "CLARIFY"),
        intent=result.get("intent", "none"),
        response_text=result.get("response_text", ""),
        tool_calls=tool_calls,
        citations=[
            AgentCitation(
                document_title=item.document_title,
                section=item.section,
                page=item.page,
                excerpt=item.excerpt,
                retrieval_score=item.retrieval_score,
            )
            for item in result.get("citations") or []
        ],
        hitl_pending=False,
        latency_ms=elapsed_ms,
    )

"""`GET /api/v1/citations/{citation_id}` — một trong 14 interface P0.

`api_spec.md:62` chốt vai trò "Driver for own turn": tài xế chỉ xem được citation của
lượt mình. Quyền sở hữu suy qua `citation → session_id → SessionRecord.user_id`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.api.auth_deps import AuthenticatedUser, require_driver
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.api.session_state import get_session_record
from src.models.api import CitationData, CitationEnvelope, ErrorEnvelope, Meta
from src.services.citations import get_citation_store

router = APIRouter()


@router.get(
    "/citations/{citation_id}",
    response_model=CitationEnvelope,
    responses={
        404: {
            "model": ErrorEnvelope,
            "description": (
                "NOT_FOUND — không có citation nào mang id đó, **hoặc bản ghi đã bị đẩy "
                "khỏi kho có trần**. `NOT_FOUND` không nằm trong bảng lỗi gốc của "
                "api_spec.md; tiền lệ và lý do ở `docs/tasks/TASK-BE-OBS-001 §4`."
            ),
        },
        403: {
            "model": ErrorEnvelope,
            "description": "FORBIDDEN — citation có thật nhưng thuộc phiên của người khác.",
        },
    },
    summary="Trích dẫn sổ tay của một lượt, giới hạn theo chủ phiên",
)
async def get_citation(
    request: Request,
    citation_id: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> CitationEnvelope:
    request_id, trace_id = request_scoped_ids(request)
    record = get_citation_store().get(citation_id)

    # 404 chứ không phải 403: thứ hỏng là **cái id**, không phải quyền của người gọi.
    #
    # Ca này gộp hai tình huống và cả hai đều không phải chuyện quyền: id chưa từng tồn
    # tại, và bản ghi đã bị đẩy khỏi kho có trần. Tình huống thứ hai mới là ca phổ biến
    # — trần LRU sinh ra để làm đúng việc đó — nên trả 403 nghĩa là tài xế bấm vào thẻ
    # citation **của chính mình** và nhận "bạn không có quyền".
    #
    # Cùng lập luận mà `/traces/{trace_id}` đã chốt (`src/api/observability.py:72`,
    # `docs/tasks/TASK-BE-OBS-001 §4`). Cái mất là phòng thủ enumeration, nhưng
    # `citation_id` là 48 bit ngẫu nhiên và chỉ từng được giao cho đúng chủ nên đoán
    # trúng không khả thi — phòng thủ đó gần như không mua được gì.
    #
    # Khác với `/approvals/{id}/decision`, nơi vẫn gộp về 403 có chủ đích: `approval_id`
    # chỉ có nghĩa lúc đang pending, và lộ sự tồn tại của nó là lộ việc ai đó đang có
    # lệnh xe chờ duyệt.
    # Cùng rổ 404: id chưa từng tồn tại, bản ghi đã bị đẩy khỏi kho, và phiên sinh ra nó
    # không phân giải được. Cả ba đều **không phải chuyện quyền**.
    #
    # Ca thứ ba có thật và không cần race nào: `/turns/voice` (`turns.py:111`) và
    # `/agent/process` đều nhận `session_id` tuỳ ý mà không gọi `create_session()`, nên
    # citation sinh từ những lượt đó mồ côi ngay từ lúc sinh. Trả 403 ở đó là khẳng định
    # "thuộc về người khác" — điều ta không chứng minh được; ta chỉ biết mình không phân
    # giải được chủ.
    session_record = get_session_record(record.session_id) if record is not None else None
    if record is None or session_record is None:
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="không tìm thấy citation",
            request_id=request_id,
            trace_id=trace_id,
            details={"citation_id": citation_id},
        )

    # Phân giải được chủ, và chủ đó không phải người gọi — đây mới đúng là chuyện quyền.
    if session_record.user_id != user.user_id:
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="citation không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    return CitationEnvelope(
        data=CitationData(**record.citation.model_dump()),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )

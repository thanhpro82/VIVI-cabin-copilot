"""Ba route đọc của bề mặt kỹ sư: `/traces/{id}`, `/metrics/summary` (interface #8 và
#9), và `/metrics/eval-snapshot` (thêm 28/08).

Hai cái đầu là hai bề mặt đọc của cùng một `TraceStore`: một cái đọc lẻ một bản ghi,
một cái fold cả cửa sổ. Không có counter riêng ở đâu cả — xem `src/services/metrics.py`.

Cái thứ ba đọc **nguồn khác hẳn**: artifact trong `eval/results/`, tức bằng chứng đã
đóng gói từ một lần chấm trên bộ đề có đáp án khoá. Nó ở cùng file vì cùng vai trò và
cùng hàng rào RBAC, nhưng số của nó **không cộng được** với số của hai route kia —
xem `EvalSnapshotData`.

Theo khuôn `GET /vehicle/state` (`src/api/routes.py`): có `response_model=` **và**
`responses={...: {"model": ErrorEnvelope}}`. Khai `description` mà quên `model` thì
`/docs` im lặng về hình dạng nhánh lỗi và người làm frontend vẫn phải đoán.

Lỗi dùng `ApiError`, **không** `HTTPException(detail=...)` — lý do ở
`src/api/errors.py`. (`src/api/approvals.py` hiện còn dùng `HTTPException`; đó là
khoảng trống đã biết, đừng chép theo.)

RBAC ĐÃ CÓ (issue #45 B1) — `docs/api_spec.md:8` chốt `/metrics/summary` là
**Engineer-only** và trace là owner/role-scoped. Cả hai route dưới đây đi qua
`Depends(require_engineer)`; `_require_engineer` no-op của bản trước đã bị gỡ.

Phần "owner-scoped" của trace vẫn CHƯA làm được: `TraceRecord` không mang `user_id`
để mà so, nên ranh giới thực tế hiện là role chứ không phải chủ sở hữu. Ghi ở đây
để không ai đọc `Depends(require_engineer)` thành "đã lọc theo người".
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from src.api.auth_deps import require_engineer
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.config import get_settings
from src.models.api import ErrorEnvelope, Meta
from src.models.observability import (
    EvalSnapshotData,
    EvalSnapshotEnvelope,
    MetricsSummaryEnvelope,
    TraceEnvelope,
)
from src.services.eval_snapshot import doc_snapshot_moi_nhat
from src.services.metrics import build_metrics_summary
from src.services.trace_store import get_trace_store
from src.services.trace_view import to_trace_data

router = APIRouter()

#: Cả ba route đều Engineer-only nên khai một lần rồi dùng chung — thêm route thứ tư
#: mà quên `dependencies=` là đúng kiểu lỗ hổng mà `_require_engineer` từng che.
_ENGINEER_ONLY = [Depends(require_engineer)]

#: Nhánh lỗi auth dùng chung cho cả ba route. `require_engineer` raise `ApiError`
#: nên thân route không bao giờ chạy; khai ở đây là để `/docs` nói đúng hình dạng.
_AUTH_RESPONSES: dict[int | str, dict] = {
    401: {"model": ErrorEnvelope, "description": "AUTH_REQUIRED — thiếu hoặc sai bearer token"},
    403: {"model": ErrorEnvelope, "description": "FORBIDDEN — token hợp lệ nhưng không phải vai trò engineer"},
}


@router.get(
    "/traces/{trace_id}",
    response_model=TraceEnvelope,
    dependencies=_ENGINEER_ONLY,
    responses={
        **_AUTH_RESPONSES,
        404: {
            "model": ErrorEnvelope,
            "description": (
                "NOT_FOUND — không có trace nào mang id đó, hoặc bản ghi đã bị đẩy khỏi "
                "kho có trần. Mã này **không** nằm trong bảng lỗi gốc của api_spec.md; "
                "quyết định thêm ghi ở docs/tasks/TASK-BE-OBS-001 §4."
            ),
        },
    },
    summary="Trace vận hành đã khử nhạy cảm của một lượt",
)
async def read_trace(trace_id: str, request: Request, response: Response) -> TraceEnvelope:
    request_id, response_trace_id = request_scoped_ids(request)

    record = get_trace_store().get(trace_id)
    if record is None:
        # 404 chứ không phải 403. Spec không có mã cho trường hợp này; 403 được cân
        # nhắc để không lộ sự tồn tại của trace người khác, nhưng hệ thống hiện chưa
        # có định danh nào để mà bảo vệ — 403 lúc này chỉ là diễn, và nó nói dối
        # người gọi rằng họ thiếu quyền trong khi thứ họ hỏng là cái id.
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="không tìm thấy trace",
            request_id=request_id,
            trace_id=response_trace_id,
            details={"trace_id": trace_id},
        )

    response.headers["X-Trace-Id"] = response_trace_id
    return TraceEnvelope(
        data=to_trace_data(record, get_settings()),
        meta=Meta(request_id=request_id),
        trace_id=response_trace_id,
    )


@router.get(
    "/metrics/summary",
    response_model=MetricsSummaryEnvelope,
    dependencies=_ENGINEER_ONLY,
    responses={**_AUTH_RESPONSES},
    summary="Aggregate an toàn cho dashboard kỹ sư",
)
async def metrics_summary(request: Request, response: Response) -> MetricsSummaryEnvelope:
    """Tám nhóm aggregate trên cửa sổ rolling.

    Không nhận query param: `api_spec.md:384-466` không định nghĩa `?from=`/`?to=`
    nào, và repo có kỷ luật không âm thầm nới bề mặt đã tài liệu hoá. Cửa sổ do
    server chọn qua `METRICS_WINDOW_SECONDS`.
    """
    request_id, trace_id = request_scoped_ids(request)

    response.headers["X-Trace-Id"] = trace_id
    return MetricsSummaryEnvelope(
        data=build_metrics_summary(get_trace_store(), get_settings(), datetime.now(UTC)),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


@router.get(
    "/metrics/eval-snapshot",
    response_model=EvalSnapshotEnvelope,
    dependencies=_ENGINEER_ONLY,
    responses={
        **_AUTH_RESPONSES,
        404: {
            "model": ErrorEnvelope,
            "description": "NOT_FOUND — suite chua co run eval nao doc duoc",
        },
    },
    summary="Anh chup run eval moi nhat cua mot suite",
)
async def eval_snapshot(
    request: Request,
    response: Response,
    suite: Literal["rag", "agent-intent"] = Query(..., description="Suite eval can doc"),
) -> EvalSnapshotEnvelope:
    """Chỉ ĐỌC artifact đã có. Không chạy eval, không ghi gì.

    `suite` khai bằng `Literal` chứ không phải `str`: giá trị này đi thẳng vào một
    đường dẫn filesystem, nên whitelist ở tầng validate là hàng rào path-traversal
    chứ không phải thẩm mỹ. FastAPI trả 422 `INPUT_INVALID` cho giá trị ngoài danh sách.

    Vì sao route ĐỌC BẰNG CHỨNG chứ không route CHẠY EVAL: một request HTTP không
    được phép sinh ra thư mục run. Chấm là hành động có chủ ý, có người chịu trách
    nhiệm; xem `docs/superpowers/specs/2026-08-28-dashboard-ky-su-design.md` §5.
    """
    request_id, trace_id = request_scoped_ids(request)

    snap = doc_snapshot_moi_nhat(suite, Path(get_settings().eval_results_dir))
    if snap is None:
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="suite chua co run eval nao",
            request_id=request_id,
            trace_id=trace_id,
            details={"suite": suite},
        )

    response.headers["X-Trace-Id"] = trace_id
    return EvalSnapshotEnvelope(
        data=EvalSnapshotData(
            suite=snap.suite,
            run_id=snap.run_id,
            metrics=snap.metrics,
            graded_by=snap.graded_by,
            dataset=snap.dataset,
            note=snap.note,
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )

"""Lỗi API trả đúng vỏ `docs/api_spec.md`.

Vì sao không dùng thẳng `HTTPException(detail={...})`: FastAPI **luôn** bọc
`detail` vào `{"detail": ...}`. Nên `HTTPException(detail={"error": {...}})` ra
`{"detail": {"error": {...}}}`, trong khi spec chốt `error` nằm ở top-level. Hệ
quả cụ thể: `frontend/src/lib/services/shared/errors.ts` đọc `body.error?.code`
nên luôn miss và mọi lỗi hiện ra thành mã fallback, bất kể backend nói gì.

Cách sửa đúng là exception handler riêng — không phải bảo client đọc thêm một
tầng, vì tầng đó không có trong hợp đồng.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.context import new_request_id, resolve_trace_id
from src.models.api import ApiErrorBody, ErrorEnvelope, Meta


class ApiError(Exception):
    """Lỗi có mã, dịch thẳng ra envelope lỗi.

    `request_id`/`trace_id` truyền vào từ handler chứ không tự sinh ở đây: nhánh
    lỗi và nhánh thành công của cùng một request phải mang **cùng** một trace id,
    nếu không thì log hai bên không nối được.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        request_id: str,
        trace_id: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id
        self.trace_id = trace_id
        self.retryable = retryable
        self.details = details or {}

    def envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(
            error=ApiErrorBody(
                code=self.code,
                message=self.message,
                retryable=self.retryable,
                details=self.details,
            ),
            meta=Meta(request_id=self.request_id),
            trace_id=self.trace_id,
        )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler đăng ký trong `src/main.py`.

    Chữ ký nhận `Exception` chứ không phải `ApiError` là để khớp kiểu mà
    `add_exception_handler` khai; Starlette chỉ gọi handler này cho đúng lớp đã
    đăng ký nên ép kiểu bên trong là an toàn.
    """
    assert isinstance(exc, ApiError)  # noqa: S101 - Starlette chỉ định tuyến đúng lớp
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.envelope().model_dump(mode="json"),
        headers={"X-Trace-Id": exc.trace_id},
    )


async def request_validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler cho `RequestValidationError` — lỗi Pydantic khi FastAPI parse body.

    Không đăng ký thì FastAPI trả mặc định `{"detail": [...]}`, thiếu cả
    `trace_id` lẫn `schema_version` mà `docs/api_spec.md` chốt là bắt buộc trên
    **mọi** response. Mặc định của Pydantic còn kèm `input` trong từng lỗi —
    tức là echo nguyên văn phần body client gửi lên (kể cả mật khẩu ở
    `/auth/login`) ngược lại trong response lỗi. Handler này build lại
    `details.errors` chỉ với `loc`/`msg`/`type`, bỏ hẳn `input`.
    """
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - Starlette chỉ định tuyến đúng lớp
    request_id = new_request_id()
    trace_id = resolve_trace_id(request)
    errors = [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
    envelope = ErrorEnvelope(
        error=ApiErrorBody(
            code="INPUT_INVALID",
            message="request body validation failed",
            retryable=False,
            details={"errors": errors},
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=422,
        content=envelope.model_dump(mode="json"),
        headers={"X-Trace-Id": trace_id},
    )

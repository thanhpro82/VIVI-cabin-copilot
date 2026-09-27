"""Dependency FastAPI dùng chung cho các route P0 mới: xác thực, RBAC, và các
điều kiện request-context bắt buộc (`X-Schema-Version`, `Idempotency-Key`).

Raise `ApiError` (không phải `HTTPException`) — xem `src/api/errors.py` để biết vì
sao: `HTTPException(detail=...)` bị FastAPI bọc thêm một tầng `{"detail": ...}`,
vỡ hợp đồng envelope top-level. `ApiError` có handler riêng đăng ký sẵn ở
`src/main.py`.

Session-ownership KHÔNG nằm ở đây — nó cần `session_id` từ body, kiểm trong từng
route (`session_routes.py`, `turns.py`), không phải một dependency chung.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, Request

from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.services.auth import Role, get_auth_store


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    role: Role
    display_name: str


async def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    request_id, trace_id = request_scoped_ids(request)
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApiError(
            status_code=401,
            code="AUTH_REQUIRED",
            message="thiếu hoặc sai định dạng Authorization: Bearer <token>",
            request_id=request_id,
            trace_id=trace_id,
        )
    token = authorization.removeprefix("Bearer ").strip()
    record, reason = get_auth_store().resolve_with_reason(token)
    if record is None:
        # Cùng `code` cho cả hai ca — `docs/api_spec.md` chốt tập mã lỗi và client
        # xử lý chúng giống hệt nhau (đăng xuất, quay lại /login). Chỉ `message`
        # tách ra, vì "hết hạn" và "server vừa restart nên mất token" đòi hai
        # cách hiểu khác nhau khi đọc log, và câu chung "không hợp lệ hoặc đã hết
        # hạn" trước đây đã khiến ca restart bị chẩn đoán nhầm nhiều lần
        # (docs/tasks/TASK-FE-BE-003-driver-real-mode-ux-fixes.md:223).
        raise ApiError(
            status_code=401,
            code="AUTH_REQUIRED",
            message=(
                "token đã hết hạn, vui lòng đăng nhập lại"
                if reason == "expired"
                else "token không còn hiệu lực (server đã khởi động lại), vui lòng đăng nhập lại"
            ),
            request_id=request_id,
            trace_id=trace_id,
        )
    return AuthenticatedUser(user_id=record.user_id, role=record.role, display_name=record.display_name)


async def require_driver(request: Request, user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != "driver":
        request_id, trace_id = request_scoped_ids(request)
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="yêu cầu vai trò 'driver'",
            request_id=request_id,
            trace_id=trace_id,
        )
    return user


async def require_engineer(request: Request, user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    """Cùng khuôn `require_driver`, cho vai trò còn lại.

    `docs/api_spec.md:8` chốt `/metrics/summary` là **Engineer-only** và trace là
    owner/role-scoped. Trước issue #45 (B1) hàm này không tồn tại, nên
    `src/api/observability.py` phải dùng `_require_engineer` no-op và hai endpoint
    đó trả 200 cho mọi người gọi.

    "Owner-scoped" của trace CHƯA làm được: `TraceRecord` không mang `user_id` nào
    để mà so. Ở P0 chỉ có đúng một engineer demo nên role-scoped là toàn bộ ranh
    giới thực tế; đừng đọc hàm này thành "đã lọc theo chủ sở hữu".
    """
    if user.role != "engineer":
        request_id, trace_id = request_scoped_ids(request)
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="yêu cầu vai trò 'engineer'",
            request_id=request_id,
            trace_id=trace_id,
        )
    return user


async def require_schema_version(
    request: Request, x_schema_version: str | None = Header(default=None, alias="X-Schema-Version")
) -> None:
    if x_schema_version != "1.0":
        request_id, trace_id = request_scoped_ids(request)
        raise ApiError(
            status_code=400,
            code="REQUEST_CONTEXT_INVALID",
            message="thiếu hoặc sai X-Schema-Version, cần đúng '1.0'",
            request_id=request_id,
            trace_id=trace_id,
        )


async def require_login_schema_version(
    request: Request,
    x_schema_version: str | None = Header(default=None, alias="X-Schema-Version"),
    content_type: str | None = Header(default=None, alias="Content-Type"),
) -> None:
    """Ngoại lệ riêng cho `/auth/login`: chấp nhận `X-Schema-Version` HOẶC
    `version=1.0` trong `Content-Type` — docs/api_spec.md mục "Required POST context"."""
    if x_schema_version == "1.0":
        return
    if content_type is not None and "version=1.0" in content_type:
        return
    request_id, trace_id = request_scoped_ids(request)
    raise ApiError(
        status_code=400,
        code="REQUEST_CONTEXT_INVALID",
        message="login yêu cầu X-Schema-Version: 1.0 hoặc version=1.0 trong Content-Type",
        request_id=request_id,
        trace_id=trace_id,
    )


async def require_idempotency_key(
    request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> str:
    if not idempotency_key:
        request_id, trace_id = request_scoped_ids(request)
        raise ApiError(
            status_code=400,
            code="REQUEST_CONTEXT_INVALID",
            message="thiếu header Idempotency-Key bắt buộc",
            request_id=request_id,
            trace_id=trace_id,
        )
    return idempotency_key

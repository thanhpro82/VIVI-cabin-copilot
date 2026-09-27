"""POST /api/v1/auth/login — một trong 14 interface P0. Không cần Authorization.
Xem docs/api_spec.md mục "Login"."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from src.api.auth_deps import require_login_schema_version
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.models.api import LoginData, LoginEnvelope, LoginUser, Meta
from src.services.auth import get_auth_store

router = APIRouter()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


@router.post("/auth/login", response_model=LoginEnvelope, dependencies=[Depends(require_login_schema_version)])
async def login(request: Request, body: LoginRequest) -> LoginEnvelope:
    request_id, trace_id = request_scoped_ids(request)
    record = get_auth_store().login(body.email, body.password)
    if record is None:
        raise ApiError(
            status_code=401,
            code="AUTH_REQUIRED",
            message="email hoặc password không đúng",
            request_id=request_id,
            trace_id=trace_id,
        )
    return LoginEnvelope(
        data=LoginData(
            access_token=record.token,
            expires_at=record.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            user=LoginUser(user_id=record.user_id, role=record.role, display_name=record.display_name),
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )

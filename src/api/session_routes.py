"""POST /api/v1/sessions — một trong 14 interface P0. Xem docs/api_spec.md mục
"Create session"."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from src.api import session_state
from src.api.auth_deps import AuthenticatedUser, require_driver, require_idempotency_key, require_schema_version
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.models.api import Meta, PoolXe, SessionData, SessionEnvelope
from src.services import idempotency

router = APIRouter()

_ROUTE = "POST /sessions"


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    input_mode: Literal["text", "voice"] = "text"


@router.post("/sessions", response_model=SessionEnvelope, dependencies=[Depends(require_schema_version)])
async def create_session_route(
    request: Request,
    body: CreateSessionRequest,
    user: AuthenticatedUser = Depends(require_driver),
    idempotency_key: str = Depends(require_idempotency_key),
) -> SessionEnvelope:
    request_id, trace_id = request_scoped_ids(request)
    store = idempotency.get_idempotency_store()
    fingerprint = idempotency.fingerprint_for(body.model_dump())

    try:
        existing = await store.begin(user.user_id, _ROUTE, idempotency_key, fingerprint)
    except idempotency.IdempotencyInProgress as exc:
        raise ApiError(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="một request khác với cùng Idempotency-Key đang được xử lý, thử lại sau",
            retryable=True,
            request_id=request_id,
            trace_id=trace_id,
        ) from exc
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                message="Idempotency-Key đã dùng cho một request khác nội dung",
                request_id=request_id,
                trace_id=trace_id,
            )
        return SessionEnvelope.model_validate(existing.body)

    try:
        record = session_state.create_session(user.user_id, body.vehicle_id)
        # `can_drive` đọc từ bảng thuê, KHÔNG suy từ `record.vehicle_id`: cột đó là
        # NOT NULL trong SQLite nên một phiên chỉ-xem vẫn có giá trị ở đó.
        suc_chua = session_state.suc_chua_xe()
        envelope = SessionEnvelope(
            data=SessionData(
                session_id=record.session_id,
                vehicle_id=record.vehicle_id,
                status=record.status,
                started_at=record.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                can_drive=session_state.xe_cua_phien(record.session_id) is not None,
                pool=None
                if suc_chua is None
                else PoolXe(total=suc_chua.tong, in_use=suc_chua.dang_dung, free=suc_chua.con_trong),
            ),
            meta=Meta(request_id=request_id),
            trace_id=trace_id,
        )
    except Exception:
        await store.abandon(user.user_id, _ROUTE, idempotency_key)
        raise

    await store.finish(
        user.user_id,
        _ROUTE,
        idempotency_key,
        idempotency.IdempotencyRecord(fingerprint=fingerprint, status_code=200, body=envelope.model_dump(mode="json")),
    )
    return envelope

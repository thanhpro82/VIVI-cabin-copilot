# Core Driver APIs: Auth, Session & Text Turn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three missing P0 Core Driver API endpoints — `POST /api/v1/auth/login`, `POST /api/v1/sessions`, `POST /api/v1/turns/text` — so the canonical Driver flow (login → create session → submit text turn) works end-to-end.

**Architecture:** Two new service modules (`src/services/auth.py`, `src/services/idempotency.py`) and one new API-layer module (`src/api/auth_deps.py`) provide auth/RBAC and idempotency for three new/extended routers. `src/models/api.py` gains typed response envelope models following its existing `VehicleStateData`/`VehicleStateEnvelope` pattern. `session_state.py` gains session ownership tracking; `turns.py` gains a synchronous text-turn handler that reuses the existing LangGraph pipeline and `ivi_events.emit_turn_lifecycle`, the same machinery the voice-turn handler already uses.

**Tech Stack:** FastAPI, Pydantic v2, LangGraph (existing `build_graph`/`ApprovalStore`), pytest + pytest-asyncio (`asyncio_mode = "auto"`), httpx `AsyncClient` / Starlette `TestClient` for API tests.

## Revision note (2026-08-10)

This plan was originally written against a design that invented its own `src/api/envelope.py` (`success_envelope`/`error_detail`) and raised `HTTPException(detail=...)` for errors. After the design was approved, `git pull` surfaced that `origin/develop` had, in the meantime, landed the actual solution to this exact problem: `src/api/context.py` (`new_request_id`/`resolve_trace_id`), `src/api/errors.py` (`ApiError` + a registered exception handler), and `src/models/api.py` (typed envelope models, e.g. `VehicleStateEnvelope`, already used by the migrated `GET /vehicle/state`). Critically, `errors.py`'s own docstring documents a real bug the original plan would have shipped: `HTTPException(detail={"error": {...}})` serializes as `{"detail": {"error": {...}}}` (FastAPI always wraps `detail`), not the top-level `{"error": {...}}` the contract requires. This plan is rewritten to build on that shared infra instead. Work therefore proceeds on a fresh branch (`feature/core-driver-apis`) cut from current `origin/develop`, not on the old `feature/healthz-endpoint` branch (whose own work already merged into `develop`).

## Global Constraints

- Design doc of record: `docs/superpowers/specs/2026-08-10-core-driver-apis-design.md` (see its own 2026-08-10 revision note for the same context.py/errors.py/models/api.py alignment). Every task below traces to a section there.
- Contract of record: `docs/api_spec.md`. Exact field names/response shapes for `/auth/login` (lines 73–95), `/sessions` (97–122), `/turns/text` (124–174), request-context table (40–50), error codes (649–662).
- **Error handling:** every failure path raises `src.api.errors.ApiError(status_code=..., code=..., message=..., request_id=..., trace_id=..., retryable=..., details=...)`. Never `fastapi.HTTPException` for anything in this ticket's new code — `ApiError` is already wired to a registered exception handler in `src/main.py` that produces the correct top-level envelope; `HTTPException` would double-wrap it.
- **Ids:** `request_id` always comes from `src.api.context.new_request_id()`. `trace_id` always comes from `src.api.context.resolve_trace_id(request)` — never a fresh id unconditionally — so a client-supplied valid `X-Trace-Id` is honored, per `docs/api_spec.md:9`. Every route handler and every `auth_deps.py` dependency that can raise needs a `request: Request` parameter to call this.
- **Response models:** every success response is a typed Pydantic model from `src/models/api.py`, declared via `response_model=...` on the route and returned as an actual model instance (`LoginEnvelope(data=..., meta=..., trace_id=...)`), the same way `GET /vehicle/state` already does. Never return a raw dict from a route handler (an idempotent-replay return of a *stored* dict is the one exception — reconstruct it via `Envelope.model_validate(...)` first, so the declared return type stays honest).
- In-memory only. No new SQLite tables, no new dependencies (no JWT libraries). Everything is LRU-capped the same way `session_state.py`'s `MAX_SESSIONS` already is.
- Error codes used are exactly: `AUTH_REQUIRED` (401), `FORBIDDEN` (403), `REQUEST_CONTEXT_INVALID` (400), `INPUT_INVALID` (422), `IDEMPOTENCY_CONFLICT` (409). Do not invent new codes.
- Two demo accounts only: `driver.demo@example.com` / `DemoDriver123!` (role `driver`, `user_id="usr_driver_01"`), `engineer.demo@example.com` / `DemoEngineer123!` (role `engineer`, `user_id="usr_engineer_01"`). Do not add more.
- Out of scope — do not touch: `/turns/voice`, `/approvals/{approval_id}/decision`, `/ws/ivi`, `/ws/engineer`, any SQLite schema/migration, the vehicle-gateway/MQTT work already on `develop`. These are explicitly deferred in the design doc or predate/are unrelated to this ticket.
- Run tests from the repo root: `.\.venv\Scripts\python.exe -m pytest tests/ -q` (or a narrower path/`::test_name`). Follow `ruff.toml` (py311, line-length 120, select E/F/I/N/W/UP) — run `ruff check` / `ruff format` on every file you touch before committing.
- Commit after every task (not every step) once its tests pass, using the repo's existing Vietnamese-English mixed commit style seen in `git log` (e.g. `feat(auth): add demo user registry and opaque token store`).
- Work happens on branch `feature/core-driver-apis` (already created off `origin/develop`, with the design spec and plan docs already committed there). Do not rebase onto or merge from `feature/healthz-endpoint`.

---

### Task 1: Response envelope models in `src/models/api.py`

**Files:**
- Modify: `src/models/api.py` — add new models (existing `Meta`, `ApiErrorBody`, `ErrorEnvelope`, `VehicleStateData`, `VehicleStateEnvelope` stay untouched)
- Test: `tests/test_models_api.py`

**Interfaces:**
- Consumes: existing `Meta` (already in the file), `SCHEMA_VERSION` (already imported from `src.models.vehicle`).
- Produces: `LoginUser`, `LoginData`, `LoginEnvelope`; `SessionData`, `SessionEnvelope`; `ActionPlanStep`, `ActionPlanData`, `TurnResponseData`, `PendingApprovalData`, `TextTurnData`, `TextTurnEnvelope`. Tasks 3, 5, 7, 8, 9 import these by name from `src.models.api`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models_api.py
"""src/models/api.py — vỏ response mới cho /auth/login, /sessions, /turns/text.

Chỉ kiểm hai bất biến: field bắt buộc đúng tên/kiểu, và `extra="forbid"` chặn field
lạ (giữ hợp đồng đóng, cùng quy ước với `VehicleStateEnvelope` đã có trong file).
"""

import pytest
from pydantic import ValidationError

from src.models.api import (
    ActionPlanData,
    ActionPlanStep,
    LoginData,
    LoginEnvelope,
    LoginUser,
    Meta,
    PendingApprovalData,
    SessionData,
    SessionEnvelope,
    TextTurnData,
    TextTurnEnvelope,
    TurnResponseData,
)


def _action_plan() -> ActionPlanData:
    return ActionPlanData(
        schema_version="1.0",
        plan_id="plan_1",
        session_id="ses_1",
        vehicle_id="vehicle-demo-01",
        vehicle_state_version=1,
        steps=[
            ActionPlanStep(
                step_id="step_1", ordinal=1, tool="set_hvac_temperature",
                args={"temperature_c": 24}, safety_level="S1", depends_on=[],
            )
        ],
        requires_approval=False,
    )


def test_login_envelope_round_trips_the_spec_example_shape():
    envelope = LoginEnvelope(
        data=LoginData(
            access_token="tok",
            expires_at="2026-07-31T10:30:00Z",
            user=LoginUser(user_id="usr_driver_01", role="driver", display_name="Demo Driver"),
        ),
        meta=Meta(request_id="req_1"),
        trace_id="tr_1",
    )
    dumped = envelope.model_dump(mode="json")
    assert dumped["data"]["token_type"] == "Bearer"
    assert dumped["data"]["user"]["role"] == "driver"
    assert dumped["schema_version"] == "1.0"


def test_login_user_rejects_an_unknown_role():
    with pytest.raises(ValidationError):
        LoginUser(user_id="usr_1", role="admin", display_name="x")


def test_session_envelope_round_trips():
    envelope = SessionEnvelope(
        data=SessionData(session_id="ses_1", vehicle_id="vehicle-demo-01", status="active", started_at="2026-07-31T10:00:00Z"),
        meta=Meta(request_id="req_1"),
        trace_id="tr_1",
    )
    assert envelope.model_dump(mode="json")["data"]["status"] == "active"


def test_action_plan_step_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ActionPlanStep(
            step_id="s1", ordinal=1, tool="set_hvac_temperature", args={},
            safety_level="S1", depends_on=[], unexpected="nope",
        )


def test_text_turn_data_completed_has_no_pending_approval_by_default():
    data = TextTurnData(
        session_id="ses_1", turn_id="turn_1", status="completed", action_plan=_action_plan(),
        response=TurnResponseData(display_text="d", speak_text="d", citations=[], outcomes=[]),
    )
    assert data.pending_approval is None


def test_text_turn_data_allows_a_null_action_plan_for_non_control_outcomes():
    data = TextTurnData(
        session_id="ses_1", turn_id="turn_1", status="completed", action_plan=None,
        response=TurnResponseData(display_text="d", speak_text="d", citations=[], outcomes=[]),
    )
    assert data.action_plan is None


def test_text_turn_envelope_carries_pending_approval_for_waiting_approval():
    envelope = TextTurnEnvelope(
        data=TextTurnData(
            session_id="ses_1", turn_id="turn_1", status="waiting_approval", action_plan=_action_plan(),
            pending_approval=PendingApprovalData(approval_id="appr-1", expires_at="2026-07-31T10:00:30Z"),
            response=TurnResponseData(display_text="d", speak_text="d", citations=[], outcomes=[]),
        ),
        meta=Meta(request_id="req_1"),
        trace_id="tr_1",
    )
    assert envelope.data.pending_approval.approval_id == "appr-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_models_api.py -v`
Expected: FAIL with `ImportError: cannot import name 'LoginData' from 'src.models.api'`

- [ ] **Step 3: Add the new models**

Append to `src/models/api.py`, after the existing `VehicleStateEnvelope` class, keeping the same `model_config = ConfigDict(extra="forbid")` convention every existing class in the file uses:

```python
class LoginUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: Literal["driver", "engineer"]
    display_name: str


class LoginData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: str
    user: LoginUser


class LoginEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: LoginData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class SessionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    vehicle_id: str
    status: str
    started_at: str


class SessionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: SessionData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class ActionPlanStep(BaseModel):
    """Mirrors `src.agents.contracts.PlanStep`'s public fields exactly."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    ordinal: int
    tool: str
    args: dict[str, Any]
    safety_level: Literal["S0", "S1", "S2", "S3"]
    depends_on: list[str]


class ActionPlanData(BaseModel):
    """Mirrors `src.agents.contracts.ActionPlan`'s public fields exactly —
    docs/api_spec.md:174 requires exactly this field set, no more, no less."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    plan_id: str
    session_id: str
    vehicle_id: str
    vehicle_state_version: int
    steps: list[ActionPlanStep]
    requires_approval: bool


class TurnResponseData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_text: str
    speak_text: str
    citations: list[dict[str, Any]]
    outcomes: list[dict[str, Any]]


class PendingApprovalData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    expires_at: str


class TextTurnData(BaseModel):
    """`action_plan` is null for non-control outcomes (manual/RAG lookup, clarify,
    etc. have no ActionPlan). `pending_approval` is only set when `status ==
    "waiting_approval"` — see design doc mục "POST /turns/text"."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_id: str
    status: str
    action_plan: ActionPlanData | None
    response: TurnResponseData
    pending_approval: PendingApprovalData | None = None


class TextTurnEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: TextTurnData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_models_api.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the existing models/api.py consumer test to confirm no regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_vehicle_state.py -v`
Expected: PASS (unchanged — this task only appends new classes)

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/models/api.py tests/test_models_api.py
ruff format src/models/api.py tests/test_models_api.py
git add src/models/api.py tests/test_models_api.py
git commit -m "feat(api): add LoginEnvelope/SessionEnvelope/TextTurnEnvelope response models"
```

---

### Task 2: Demo auth service (users, opaque tokens)

**Files:**
- Create: `src/services/auth.py`
- Modify: `src/config.py` — add `auth_token_ttl_seconds` setting
- Test: `tests/test_services/test_auth.py`

**Interfaces:**
- Consumes: `src.config.get_settings()` (existing).
- Produces: `Role = Literal["driver", "engineer"]`, `TokenRecord` (dataclass: `token, user_id, role, display_name, expires_at`), `AuthStore` class with `.login(email, password) -> TokenRecord | None` and `.resolve(token) -> TokenRecord | None`, module functions `get_auth_store() -> AuthStore` and `reset() -> None`. Task 3 (`auth_deps.py`) imports `Role`, `get_auth_store` from here. No dependency on `context.py`/`errors.py`/`models/api.py` — this is pure service logic, unaffected by the revision note above.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_services/test_auth.py
"""src/services/auth.py — demo user registry và opaque bearer token store.

Chỉ hai tài khoản demo: driver.demo@example.com / DemoDriver123! (driver) và
engineer.demo@example.com / DemoEngineer123! (engineer). Xem
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md mục "Demo users and
tokens".
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.services import auth


@pytest.fixture(autouse=True)
def _reset_auth():
    auth.reset()
    yield
    auth.reset()


def test_login_with_valid_driver_credentials_issues_a_token():
    record = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    assert record is not None
    assert record.user_id == "usr_driver_01"
    assert record.role == "driver"
    assert record.display_name == "Demo Driver"
    assert record.token


def test_login_with_valid_engineer_credentials_issues_a_token():
    record = auth.get_auth_store().login("engineer.demo@example.com", "DemoEngineer123!")
    assert record is not None
    assert record.user_id == "usr_engineer_01"
    assert record.role == "engineer"


def test_login_with_wrong_password_returns_none():
    assert auth.get_auth_store().login("driver.demo@example.com", "wrong-password") is None


def test_login_with_unknown_email_returns_none():
    assert auth.get_auth_store().login("nobody@example.com", "whatever") is None


def test_two_logins_issue_different_tokens():
    first = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    second = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    assert first.token != second.token


def test_resolve_returns_the_record_for_a_valid_token():
    issued = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    resolved = auth.get_auth_store().resolve(issued.token)
    assert resolved == issued


def test_resolve_returns_none_for_an_unknown_token():
    assert auth.get_auth_store().resolve("not-a-real-token") is None


def test_resolve_returns_none_for_an_expired_token():
    store = auth.get_auth_store()
    issued = store.login("driver.demo@example.com", "DemoDriver123!")
    expired = issued.__class__(
        token=issued.token,
        user_id=issued.user_id,
        role=issued.role,
        display_name=issued.display_name,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    store._tokens[issued.token] = expired  # noqa: SLF001 - test helper, forces expiry
    assert store.resolve(issued.token) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.auth'`

- [ ] **Step 3: Add the TTL setting to config.py**

In `src/config.py`, add this block right after the `hitl_timeout_seconds` field (after line 40, before the `# Database` comment):

```python
    # Auth — token demo opaque, in-memory. Xem
    # docs/superpowers/specs/2026-08-10-core-driver-apis-design.md.
    auth_token_ttl_seconds: float = Field(default=43200.0, gt=0.0)
```

- [ ] **Step 4: Write the implementation**

```python
# src/services/auth.py
"""Auth demo, in-memory: hai user cứng, token opaque ngẫu nhiên.

Không JWT: không có hạ tầng ký nào khác trong repo và không cần thiết cho demo
một-process trong-bộ-nhớ trên PC. `docs/api_spec.md` gọi đây là "local demo
authentication". Restart mất hết token — cùng đánh đổi có chủ đích với
`session_state.py`/`ApprovalStore`.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from src.config import get_settings

Role = Literal["driver", "engineer"]

#: Trần token giữ trong bộ nhớ — cùng kiểu LRU với session_state.MAX_SESSIONS.
MAX_TOKENS = 256


@dataclass(frozen=True)
class DemoUser:
    user_id: str
    email: str
    password: str
    role: Role
    display_name: str


_USERS: tuple[DemoUser, ...] = (
    DemoUser(
        user_id="usr_driver_01",
        email="driver.demo@example.com",
        password="DemoDriver123!",
        role="driver",
        display_name="Demo Driver",
    ),
    DemoUser(
        user_id="usr_engineer_01",
        email="engineer.demo@example.com",
        password="DemoEngineer123!",
        role="engineer",
        display_name="Demo Engineer",
    ),
)
_USERS_BY_EMAIL: dict[str, DemoUser] = {user.email: user for user in _USERS}


@dataclass(frozen=True)
class TokenRecord:
    token: str
    user_id: str
    role: Role
    display_name: str
    expires_at: datetime


class AuthStore:
    """Kho token in-memory, LRU-capped ở `MAX_TOKENS`."""

    def __init__(self) -> None:
        self._tokens: OrderedDict[str, TokenRecord] = OrderedDict()

    def login(self, email: str, password: str) -> TokenRecord | None:
        user = _USERS_BY_EMAIL.get(email)
        if user is None or not secrets.compare_digest(user.password, password):
            return None
        token = secrets.token_urlsafe(32)
        ttl_seconds = get_settings().auth_token_ttl_seconds
        record = TokenRecord(
            token=token,
            user_id=user.user_id,
            role=user.role,
            display_name=user.display_name,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        self._tokens[token] = record
        self._tokens.move_to_end(token)
        while len(self._tokens) > MAX_TOKENS:
            self._tokens.popitem(last=False)
        return record

    def resolve(self, token: str) -> TokenRecord | None:
        record = self._tokens.get(token)
        if record is None:
            return None
        if datetime.now(UTC) >= record.expires_at:
            del self._tokens[token]
            return None
        return record

    def reset(self) -> None:
        """Chỉ dùng trong test."""
        self._tokens.clear()


_STORE = AuthStore()


def get_auth_store() -> AuthStore:
    return _STORE


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    _STORE.reset()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_auth.py tests/test_config.py -v`
Expected: PASS (all tests, including the pre-existing `test_config.py` suite, since the new setting has a valid default and doesn't remove anything)

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/services/auth.py src/config.py tests/test_services/test_auth.py
ruff format src/services/auth.py src/config.py tests/test_services/test_auth.py
git add src/services/auth.py src/config.py tests/test_services/test_auth.py
git commit -m "feat(auth): add demo user registry and opaque bearer token store"
```

---

### Task 3: Auth/RBAC/request-context FastAPI dependencies

**Files:**
- Create: `src/api/auth_deps.py`
- Test: `tests/test_api/test_auth_deps.py`

**Interfaces:**
- Consumes: `src.services.auth.{Role, get_auth_store}` (Task 2), `src.api.context.{new_request_id, resolve_trace_id}` (existing, on `develop`), `src.api.errors.ApiError` (existing, on `develop`).
- Produces: `AuthenticatedUser` (dataclass: `user_id, role, display_name`), `async def get_current_user(request: Request, authorization: str | None = Header(...)) -> AuthenticatedUser`, `async def require_driver(request: Request, user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser`, `async def require_schema_version(request: Request, x_schema_version: str | None = Header(...)) -> None`, `async def require_login_schema_version(request: Request, x_schema_version: str | None = Header(...), content_type: str | None = Header(...)) -> None`, `async def require_idempotency_key(request: Request, idempotency_key: str | None = Header(...)) -> str`. Tasks 5, 7, 8, 9 import all of these. Every one of them raises `ApiError`, not `HTTPException`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api/test_auth_deps.py
"""src/api/auth_deps.py — dependency FastAPI cho auth/RBAC/request-context.

Gọi trực tiếp như hàm async thường: FastAPI chỉ diễn giải `Header(...)` khi chạy
qua dependency-injection thật; gọi trực tiếp thì truyền giá trị thường vào keyword
argument là đủ. `request` dùng một Starlette `Request` tối giản dựng từ scope —
chỉ cần đọc header (`resolve_trace_id` chỉ gọi `request.headers.get(...)`), không
cần một ASGI app thật.
"""

import pytest
from starlette.requests import Request

from src.api import auth_deps
from src.api.errors import ApiError
from src.services import auth


@pytest.fixture(autouse=True)
def _reset_auth():
    auth.reset()
    yield
    auth.reset()


def _request(headers: dict[str, str] | None = None) -> Request:
    headers = headers or {}
    scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


async def test_get_current_user_with_a_valid_bearer_token_returns_the_user():
    issued = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    assert user.user_id == "usr_driver_01"
    assert user.role == "driver"
    assert user.display_name == "Demo Driver"


async def test_get_current_user_without_header_raises_401_auth_required():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request(), authorization=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


async def test_get_current_user_without_bearer_prefix_raises_401():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request(), authorization="just-a-token")
    assert exc_info.value.status_code == 401


async def test_get_current_user_with_an_unknown_token_raises_401():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request(), authorization="Bearer not-a-real-token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


async def test_get_current_user_echoes_a_valid_client_trace_id_on_error():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request({"X-Trace-Id": "tr_client_test_001"}), authorization=None)
    assert exc_info.value.trace_id == "tr_client_test_001"


async def test_require_driver_accepts_a_driver_user():
    issued = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    result = await auth_deps.require_driver(_request(), user=user)
    assert result is user


async def test_require_driver_rejects_an_engineer_user_with_403_forbidden():
    issued = auth.get_auth_store().login("engineer.demo@example.com", "DemoEngineer123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_driver(_request(), user=user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FORBIDDEN"


async def test_require_schema_version_accepts_1_0():
    await auth_deps.require_schema_version(_request(), x_schema_version="1.0")


async def test_require_schema_version_rejects_missing_header_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_schema_version(_request(), x_schema_version=None)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REQUEST_CONTEXT_INVALID"


async def test_require_schema_version_rejects_wrong_value_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_schema_version(_request(), x_schema_version="2.0")
    assert exc_info.value.status_code == 400


async def test_require_login_schema_version_accepts_the_header():
    await auth_deps.require_login_schema_version(_request(), x_schema_version="1.0", content_type=None)


async def test_require_login_schema_version_accepts_content_type_version_param():
    await auth_deps.require_login_schema_version(
        _request(), x_schema_version=None, content_type="application/json; charset=utf-8; version=1.0"
    )


async def test_require_login_schema_version_rejects_neither_present():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_login_schema_version(_request(), x_schema_version=None, content_type="application/json")
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REQUEST_CONTEXT_INVALID"


async def test_require_idempotency_key_returns_the_key():
    key = await auth_deps.require_idempotency_key(_request(), idempotency_key="turn:ses_1:001")
    assert key == "turn:ses_1:001"


async def test_require_idempotency_key_rejects_missing_header_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_idempotency_key(_request(), idempotency_key=None)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REQUEST_CONTEXT_INVALID"


async def test_require_idempotency_key_rejects_empty_string_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_idempotency_key(_request(), idempotency_key="")
    assert exc_info.value.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_auth_deps.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.auth_deps'`

- [ ] **Step 3: Write the implementation**

```python
# src/api/auth_deps.py
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

from src.api.context import new_request_id, resolve_trace_id
from src.api.errors import ApiError
from src.services.auth import Role, get_auth_store


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    role: Role
    display_name: str


async def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApiError(
            status_code=401,
            code="AUTH_REQUIRED",
            message="thiếu hoặc sai định dạng Authorization: Bearer <token>",
            request_id=new_request_id(),
            trace_id=resolve_trace_id(request),
        )
    token = authorization.removeprefix("Bearer ").strip()
    record = get_auth_store().resolve(token)
    if record is None:
        raise ApiError(
            status_code=401,
            code="AUTH_REQUIRED",
            message="token không hợp lệ hoặc đã hết hạn",
            request_id=new_request_id(),
            trace_id=resolve_trace_id(request),
        )
    return AuthenticatedUser(user_id=record.user_id, role=record.role, display_name=record.display_name)


async def require_driver(request: Request, user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != "driver":
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="yêu cầu vai trò 'driver'",
            request_id=new_request_id(),
            trace_id=resolve_trace_id(request),
        )
    return user


async def require_schema_version(
    request: Request, x_schema_version: str | None = Header(default=None, alias="X-Schema-Version")
) -> None:
    if x_schema_version != "1.0":
        raise ApiError(
            status_code=400,
            code="REQUEST_CONTEXT_INVALID",
            message="thiếu hoặc sai X-Schema-Version, cần đúng '1.0'",
            request_id=new_request_id(),
            trace_id=resolve_trace_id(request),
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
    raise ApiError(
        status_code=400,
        code="REQUEST_CONTEXT_INVALID",
        message="login yêu cầu X-Schema-Version: 1.0 hoặc version=1.0 trong Content-Type",
        request_id=new_request_id(),
        trace_id=resolve_trace_id(request),
    )


async def require_idempotency_key(
    request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> str:
    if not idempotency_key:
        raise ApiError(
            status_code=400,
            code="REQUEST_CONTEXT_INVALID",
            message="thiếu header Idempotency-Key bắt buộc",
            request_id=new_request_id(),
            trace_id=resolve_trace_id(request),
        )
    return idempotency_key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_auth_deps.py -v`
Expected: PASS (16 passed)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/api/auth_deps.py tests/test_api/test_auth_deps.py
ruff format src/api/auth_deps.py tests/test_api/test_auth_deps.py
git add src/api/auth_deps.py tests/test_api/test_auth_deps.py
git commit -m "feat(api): add auth/RBAC/request-context FastAPI dependencies"
```

---

### Task 4: Idempotency store

**Files:**
- Create: `src/services/idempotency.py`
- Modify: `tests/conftest.py` — reset auth + idempotency stores between tests
- Test: `tests/test_services/test_idempotency.py`

**Interfaces:**
- Produces: `IdempotencyRecord` (dataclass: `fingerprint, status_code, body` — `body` holds a plain `dict` produced by an envelope model's `.model_dump(mode="json")`; the route that reads it back reconstructs the typed model via `Envelope.model_validate(record.body)`), `fingerprint_for(body: dict) -> str`, `IdempotencyStore` class with `.lookup(user_id, route, key) -> IdempotencyRecord | None` and `.save(user_id, route, key, record) -> None`, module functions `get_idempotency_store() -> IdempotencyStore` and `reset() -> None`. Tasks 7, 8, 9 import all of these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_services/test_idempotency.py
"""src/services/idempotency.py — kho idempotency in-memory cho POST /sessions và
POST /turns/text. Xem docs/api_spec.md mục "Required POST context": exact replay
trả nguyên response cũ; key trùng nhưng fingerprint khác là IDEMPOTENCY_CONFLICT.
"""

import pytest

from src.services import idempotency


@pytest.fixture(autouse=True)
def _reset_idempotency():
    idempotency.reset()
    yield
    idempotency.reset()


def test_lookup_returns_none_when_nothing_was_saved():
    store = idempotency.get_idempotency_store()
    assert store.lookup("usr_1", "POST /sessions", "key-1") is None


def test_save_then_lookup_returns_the_same_record():
    store = idempotency.get_idempotency_store()
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={"data": {"ok": True}})
    store.save("usr_1", "POST /sessions", "key-1", record)
    assert store.lookup("usr_1", "POST /sessions", "key-1") == record


def test_different_users_with_the_same_key_do_not_collide():
    store = idempotency.get_idempotency_store()
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={})
    store.save("usr_1", "POST /sessions", "key-1", record)
    assert store.lookup("usr_2", "POST /sessions", "key-1") is None


def test_different_routes_with_the_same_key_do_not_collide():
    store = idempotency.get_idempotency_store()
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={})
    store.save("usr_1", "POST /sessions", "key-1", record)
    assert store.lookup("usr_1", "POST /turns/text", "key-1") is None


def test_fingerprint_for_is_stable_regardless_of_key_order():
    a = idempotency.fingerprint_for({"vehicle_id": "v1", "input_mode": "text"})
    b = idempotency.fingerprint_for({"input_mode": "text", "vehicle_id": "v1"})
    assert a == b


def test_fingerprint_for_differs_for_different_content():
    a = idempotency.fingerprint_for({"text": "a"})
    b = idempotency.fingerprint_for({"text": "b"})
    assert a != b


def test_store_evicts_oldest_record_beyond_max_records():
    store = idempotency.get_idempotency_store()
    for index in range(idempotency.MAX_RECORDS + 10):
        store.save(
            "usr_1", "POST /sessions", f"key-{index}",
            idempotency.IdempotencyRecord(fingerprint="fp", status_code=200, body={}),
        )
    assert store.lookup("usr_1", "POST /sessions", "key-0") is None
    assert store.lookup("usr_1", "POST /sessions", f"key-{idempotency.MAX_RECORDS + 9}") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_idempotency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.idempotency'`

- [ ] **Step 3: Write the implementation**

```python
# src/services/idempotency.py
"""Kho idempotency in-memory cho POST /sessions và POST /turns/text.

docs/api_spec.md mục "Required POST context": "an exact replay by the same
principal and request fingerprint returns the exact prior HTTP response. Reusing
the key with a different fingerprint returns IDEMPOTENCY_CONFLICT." Khoá theo
`(user_id, route, idempotency_key)` — không chỉ `key` — vì `idempotency_key` do
client tự chọn và hai user/route trùng chuỗi key là bình thường.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

MAX_RECORDS = 512


@dataclass(frozen=True)
class IdempotencyRecord:
    fingerprint: str
    status_code: int
    body: dict[str, Any]


def fingerprint_for(body: dict[str, Any]) -> str:
    """Băm nội dung request đã chuẩn hoá — phát hiện tái dùng key với nội dung khác."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyStore:
    def __init__(self) -> None:
        self._records: OrderedDict[tuple[str, str, str], IdempotencyRecord] = OrderedDict()

    def lookup(self, user_id: str, route: str, key: str) -> IdempotencyRecord | None:
        return self._records.get((user_id, route, key))

    def save(self, user_id: str, route: str, key: str, record: IdempotencyRecord) -> None:
        cache_key = (user_id, route, key)
        self._records[cache_key] = record
        self._records.move_to_end(cache_key)
        while len(self._records) > MAX_RECORDS:
            self._records.popitem(last=False)

    def reset(self) -> None:
        """Chỉ dùng trong test."""
        self._records.clear()


_STORE = IdempotencyStore()


def get_idempotency_store() -> IdempotencyStore:
    return _STORE


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    _STORE.reset()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_idempotency.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Wire resets into the shared test fixture**

`tests/conftest.py` on `develop` already has an autouse `_reset_session_state` fixture and a separate autouse `_reset_app_mqtt` fixture (from the vehicle-gateway work — leave that one untouched). Update only `_reset_session_state`'s body so later tasks' HTTP-level tests don't leak auth tokens or idempotency records between test functions:

```python
@pytest.fixture(autouse=True)
def _reset_session_state():
    """Simulator/graph/store/auth/idempotency song o module level nen phai don giua cac test."""
    from src.api import session_state
    from src.services import auth, idempotency

    session_state.reset()
    auth.reset()
    idempotency.reset()
    yield
    session_state.reset()
    auth.reset()
    idempotency.reset()
```

- [ ] **Step 6: Run the full test suite to confirm nothing broke**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: Same pass/fail counts as the pre-existing baseline on this branch (this only adds resets, no behavior change to existing modules)

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/services/idempotency.py tests/test_services/test_idempotency.py tests/conftest.py
ruff format src/services/idempotency.py tests/test_services/test_idempotency.py tests/conftest.py
git add src/services/idempotency.py tests/test_services/test_idempotency.py tests/conftest.py
git commit -m "feat(api): add idempotency store, wire auth/idempotency resets into test fixture"
```

---

### Task 5: `POST /api/v1/auth/login`

**Files:**
- Create: `src/api/auth_routes.py`
- Modify: `src/main.py` — register the new router
- Test: `tests/test_api/test_auth_routes.py`

**Interfaces:**
- Consumes: `src.api.auth_deps.require_login_schema_version` (Task 3), `src.api.context.{new_request_id, resolve_trace_id}` (existing), `src.api.errors.ApiError` (existing), `src.models.api.{LoginData, LoginEnvelope, LoginUser, Meta}` (Task 1), `src.services.auth.get_auth_store` (Task 2).
- Produces: `router: APIRouter` mounted at `/api/v1/auth/login`. No other module depends on this task's internals — it's a leaf.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api/test_auth_routes.py
"""POST /api/v1/auth/login — xem docs/api_spec.md mục "Login"."""


async def test_login_with_driver_credentials_returns_200_with_the_spec_envelope(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["token_type"] == "Bearer"
    assert body["data"]["access_token"]
    assert body["data"]["user"] == {"user_id": "usr_driver_01", "role": "driver", "display_name": "Demo Driver"}
    assert body["schema_version"] == "1.0"
    assert body["trace_id"]


async def test_login_with_engineer_credentials_returns_engineer_role(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "engineer.demo@example.com", "password": "DemoEngineer123!"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["user"]["role"] == "engineer"


async def test_login_with_wrong_password_returns_401_auth_required(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "driver.demo@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_login_with_unknown_email_returns_401_auth_required(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 401


async def test_login_missing_schema_version_returns_400_request_context_invalid(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


async def test_login_accepts_schema_version_declared_via_content_type_param(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"Content-Type": "application/json; charset=utf-8; version=1.0"},
        content=b'{"email":"driver.demo@example.com","password":"DemoDriver123!"}',
    )
    assert response.status_code == 200


async def test_login_does_not_require_authorization_header(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.status_code == 200


async def test_login_echoes_a_valid_client_trace_id(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0", "X-Trace-Id": "tr_client_login_001"},
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.json()["trace_id"] == "tr_client_login_001"
```

Note: unlike the old `HTTPException`-based plan, the error body's `code` field is now at `response.json()["error"]["code"]` — top-level, no `["detail"]` wrapper. That's the entire point of using `ApiError`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_auth_routes.py -v`
Expected: FAIL with 404 (route doesn't exist yet) on every test

- [ ] **Step 3: Write the implementation**

```python
# src/api/auth_routes.py
"""POST /api/v1/auth/login — một trong 12 interface P0. Không cần Authorization.
Xem docs/api_spec.md mục "Login"."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from src.api.auth_deps import require_login_schema_version
from src.api.context import new_request_id, resolve_trace_id
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
    request_id = new_request_id()
    trace_id = resolve_trace_id(request)
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
```

Register it in `src/main.py`. Add the import next to the other route imports (alphabetical, so right before `from src.api.errors import ApiError, api_error_handler`):

```python
from src.api.auth_routes import router as auth_router
```

And register it next to the other `app.include_router(...)` calls:

```python
app.include_router(auth_router, prefix="/api/v1")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_auth_routes.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: No regressions versus the previous task's run

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/api/auth_routes.py src/main.py tests/test_api/test_auth_routes.py
ruff format src/api/auth_routes.py src/main.py tests/test_api/test_auth_routes.py
git add src/api/auth_routes.py src/main.py tests/test_api/test_auth_routes.py
git commit -m "feat(api): add POST /api/v1/auth/login"
```

---

### Task 6: Session ownership in `session_state.py`

**Files:**
- Modify: `src/api/session_state.py`
- Test: `tests/test_api/test_session_state.py` — add new test functions to the existing file

**Interfaces:**
- Consumes: existing `get_vehicle`, `get_graph`, `_touch`, `MAX_SESSIONS` in the same file.
- Produces: `SessionRecord` (dataclass: `session_id, user_id, vehicle_id, status, started_at`), `create_session(user_id: str, vehicle_id: str) -> SessionRecord`, `get_session_record(session_id: str) -> SessionRecord | None`. Tasks 7, 8, 9 import all three.

This file is untouched by `origin/develop`'s new commits — no merge-conflict risk, and no dependency on `context.py`/`errors.py`/`models/api.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api/test_session_state.py` (do not remove the existing tests in the file):

```python
def test_create_session_generates_a_session_id_and_records_ownership():
    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    assert record.session_id.startswith("ses_")
    assert record.user_id == "usr_driver_01"
    assert record.vehicle_id == "vehicle-demo-01"
    assert record.status == "active"
    assert session_state.get_session_record(record.session_id) == record


def test_get_session_record_returns_none_for_an_unknown_session():
    assert session_state.get_session_record("ses_does_not_exist") is None


def test_create_session_pre_warms_the_vehicle_and_graph():
    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    assert session_state.has_session(record.session_id)


def test_evicting_a_session_also_drops_its_session_record():
    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    for index in range(session_state.MAX_SESSIONS + 5):
        session_state.get_vehicle(f"ses-fill-{index}")
    assert session_state.get_session_record(record.session_id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_session_state.py -v`
Expected: FAIL with `AttributeError: module 'src.api.session_state' has no attribute 'create_session'`

- [ ] **Step 3: Modify session_state.py**

Add these imports at the top of `src/api/session_state.py`, alongside the existing ones:

```python
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
```

Add this new type and module-level store right after the existing `_LOCKS: OrderedDict[str, asyncio.Lock] = OrderedDict()` line:

```python
@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    user_id: str
    vehicle_id: str
    status: str
    started_at: datetime


_SESSIONS: OrderedDict[str, SessionRecord] = OrderedDict()
```

Replace the existing `_touch` function body to also track `_SESSIONS`:

```python
def _touch(session_id: str) -> None:
    """Đánh dấu phiên vừa được dùng, rồi đuổi phiên cũ nhất nếu quá trần."""
    _VEHICLES.move_to_end(session_id)
    if session_id in _GRAPHS:
        _GRAPHS.move_to_end(session_id)
    if session_id in _LOCKS:
        _LOCKS.move_to_end(session_id)
    if session_id in _SESSIONS:
        _SESSIONS.move_to_end(session_id)
    while len(_VEHICLES) > MAX_SESSIONS:
        evicted, _ = _VEHICLES.popitem(last=False)
        _GRAPHS.pop(evicted, None)
        _LOCKS.pop(evicted, None)
        _SESSIONS.pop(evicted, None)
        # Graph mất thì approval của phiên đó không resume được nữa — dọn luôn,
        # đừng để nó chiếm chỗ trong trần của store.
        _STORE.forget_session(evicted)
```

Add `create_session` and `get_session_record` right after `get_vehicle` (before `get_graph`):

```python
def create_session(user_id: str, vehicle_id: str) -> SessionRecord:
    """Tạo session mới do `user_id` sở hữu — chỉ được gọi từ `POST /sessions`.

    Khác với `get_vehicle`/`get_graph` (tự sinh state ngầm khi được gọi lần đầu),
    đây là điểm tạo session **chính chủ** duy nhất: server sinh `session_id`, ghi
    kèm `user_id` để `turns.py` kiểm ownership trước khi chạy một lượt.
    """
    session_id = f"ses_{uuid.uuid4().hex[:20]}"
    record = SessionRecord(
        session_id=session_id,
        user_id=user_id,
        vehicle_id=vehicle_id,
        status="active",
        started_at=datetime.now(UTC),
    )
    _SESSIONS[session_id] = record
    # Chạm trước cho vehicle/graph để lượt đầu tiên không trả giá first-touch
    # khác với các lượt sau.
    get_vehicle(session_id)
    get_graph(session_id)
    return record


def get_session_record(session_id: str) -> SessionRecord | None:
    return _SESSIONS.get(session_id)
```

Update `reset()` to also clear `_SESSIONS`:

```python
def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    _VEHICLES.clear()
    _GRAPHS.clear()
    _LOCKS.clear()
    _SESSIONS.clear()
    _STORE._records.clear()  # noqa: SLF001 - test helper, cố ý chạm vào nội bộ
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_session_state.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: No regressions

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/api/session_state.py tests/test_api/test_session_state.py
ruff format src/api/session_state.py tests/test_api/test_session_state.py
git add src/api/session_state.py tests/test_api/test_session_state.py
git commit -m "feat(api): track session ownership (SessionRecord) in session_state.py"
```

---

### Task 7: `POST /api/v1/sessions`

**Files:**
- Create: `src/api/session_routes.py`
- Modify: `src/main.py` — register the new router
- Test: `tests/test_api/test_session_routes.py`

**Interfaces:**
- Consumes: `src.api.session_state.{create_session, get_session_record, session_count}` (Task 6), `src.api.auth_deps.{AuthenticatedUser, require_driver, require_idempotency_key, require_schema_version}` (Task 3), `src.api.context.{new_request_id, resolve_trace_id}` / `src.api.errors.ApiError` (existing), `src.models.api.{Meta, SessionData, SessionEnvelope}` (Task 1), `src.services.idempotency.{IdempotencyRecord, fingerprint_for, get_idempotency_store}` (Task 4).
- Produces: `router: APIRouter` mounted at `/api/v1/sessions`. Task 8/9's tests reuse the login+create-session flow this task's tests establish as a pattern.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api/test_session_routes.py
"""POST /api/v1/sessions — auth, ownership, idempotency. Xem
docs/api_spec.md mục "Create session" và
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md."""

from src.api import session_state


async def _login(client, email: str = "driver.demo@example.com", password: str = "DemoDriver123!") -> str:
    response = await client.post(
        "/api/v1/auth/login", headers={"X-Schema-Version": "1.0"}, json={"email": email, "password": password}
    )
    return response.json()["data"]["access_token"]


async def test_create_session_returns_the_spec_envelope(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "session:vehicle-demo-01:001",
        },
        json={"vehicle_id": "vehicle-demo-01", "input_mode": "voice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["vehicle_id"] == "vehicle-demo-01"
    assert body["data"]["status"] == "active"
    assert body["data"]["session_id"].startswith("ses_")
    assert body["data"]["started_at"]
    assert body["schema_version"] == "1.0"


async def test_create_session_records_the_caller_as_owner(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "session:vehicle-demo-01:002",
        },
        json={"vehicle_id": "vehicle-demo-01"},
    )
    session_id = response.json()["data"]["session_id"]
    record = session_state.get_session_record(session_id)
    assert record.user_id == "usr_driver_01"


async def test_create_session_without_a_token_returns_401_auth_required(client):
    response = await client.post(
        "/api/v1/sessions",
        headers={"X-Schema-Version": "1.0", "Idempotency-Key": "session:x:001"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_create_session_with_an_engineer_token_returns_403_forbidden(client):
    token = await _login(client, email="engineer.demo@example.com", password="DemoEngineer123!")
    response = await client.post(
        "/api/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "session:x:001",
        },
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_create_session_missing_idempotency_key_returns_400(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


async def test_create_session_missing_schema_version_returns_400(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "session:x:001"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 400


async def test_replaying_the_same_idempotency_key_returns_the_identical_response_and_creates_no_second_session(client):
    token = await _login(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Schema-Version": "1.0",
        "Idempotency-Key": "session:vehicle-demo-01:replay",
    }
    payload = {"vehicle_id": "vehicle-demo-01"}
    first = await client.post("/api/v1/sessions", headers=headers, json=payload)
    before_count = session_state.session_count()
    second = await client.post("/api/v1/sessions", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert session_state.session_count() == before_count


async def test_reusing_the_key_with_a_different_body_returns_409_idempotency_conflict(client):
    token = await _login(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Schema-Version": "1.0",
        "Idempotency-Key": "session:conflict:001",
    }
    await client.post("/api/v1/sessions", headers=headers, json={"vehicle_id": "vehicle-demo-01"})
    response = await client.post("/api/v1/sessions", headers=headers, json={"vehicle_id": "vehicle-demo-02"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_session_routes.py -v`
Expected: FAIL with 404 on every test (route doesn't exist yet)

- [ ] **Step 3: Write the implementation**

```python
# src/api/session_routes.py
"""POST /api/v1/sessions — một trong 12 interface P0. Xem docs/api_spec.md mục
"Create session"."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from src.api import session_state
from src.api.auth_deps import AuthenticatedUser, require_driver, require_idempotency_key, require_schema_version
from src.api.context import new_request_id, resolve_trace_id
from src.api.errors import ApiError
from src.models.api import Meta, SessionData, SessionEnvelope
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
    request_id = new_request_id()
    trace_id = resolve_trace_id(request)
    store = idempotency.get_idempotency_store()
    fingerprint = idempotency.fingerprint_for(body.model_dump())

    existing = store.lookup(user.user_id, _ROUTE, idempotency_key)
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

    record = session_state.create_session(user.user_id, body.vehicle_id)
    envelope = SessionEnvelope(
        data=SessionData(
            session_id=record.session_id,
            vehicle_id=record.vehicle_id,
            status=record.status,
            started_at=record.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )
    store.save(
        user.user_id, _ROUTE, idempotency_key,
        idempotency.IdempotencyRecord(fingerprint=fingerprint, status_code=200, body=envelope.model_dump(mode="json")),
    )
    return envelope
```

Register it in `src/main.py`, next to the `auth_router` import/registration added in Task 5:

```python
from src.api.session_routes import router as sessions_router
```

```python
app.include_router(sessions_router, prefix="/api/v1")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_session_routes.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: No regressions

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/api/session_routes.py src/main.py tests/test_api/test_session_routes.py
ruff format src/api/session_routes.py src/main.py tests/test_api/test_session_routes.py
git add src/api/session_routes.py src/main.py tests/test_api/test_session_routes.py
git commit -m "feat(api): add POST /api/v1/sessions"
```

---

### Task 8: `POST /api/v1/turns/text` — S1/completed path

**Files:**
- Modify: `src/api/turns.py` — add the text-turn handler
- Modify: `src/services/ivi_events.py` — make `_assistant_response_payload` public (`assistant_response_payload`) so `turns.py` can reuse it instead of duplicating response-shape logic
- Test: `tests/test_api/test_turns_text.py`

**Interfaces:**
- Consumes: `src.api.session_state.{get_graph, get_session_lock, get_session_record, thread_config}` (existing + Task 6), `src.api.auth_deps.*` (Task 3), `src.api.context.{new_request_id, resolve_trace_id}` / `src.api.errors.ApiError` (existing), `src.models.api.{ActionPlanData, ActionPlanStep, Meta, TextTurnData, TextTurnEnvelope, TurnResponseData}` (Task 1), `src.services.idempotency.*` (Task 4), `src.services.ivi_events.{assistant_response_payload, emit_turn_lifecycle, get_event_bus}` (existing, one renamed), `src.agents.contracts.{ActionPlan, as_action_plan}` (existing).
- Produces: `POST /turns/text` route on the existing `turns_router`, plus a module-level helper `_action_plan_model(plan: ActionPlan) -> ActionPlanData` and `_TEXT_TURN_ROUTE = "POST /turns/text"` constant that Task 9 reuses. `src/api/turns.py` is untouched by `origin/develop`'s new commits — no merge-conflict risk. `/turns/voice`'s existing `HTTPException`-based content-type validation is left exactly as-is — it is out of scope for this ticket.

- [ ] **Step 1: Rename the private helper in ivi_events.py**

In `src/services/ivi_events.py`, rename `_assistant_response_payload` to `assistant_response_payload` (drop the leading underscore) — both its `def` line and its call sites inside `emit_turn_lifecycle` (there are 4 call sites total inside that function; rename all of them). This is a pure rename, no behavior change — it's needed because `turns.py`'s new text-turn handler builds the same `response` shape and must not duplicate that logic.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py tests/test_api/test_turns_voice.py tests/test_api/test_approval_routes.py -v`
Expected: PASS (renaming a private helper and all its call sites doesn't change behavior — this confirms it)

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_api/test_turns_text.py
"""POST /api/v1/turns/text — S1 completed path. Xem docs/api_spec.md mục "Text
turn and canonical ActionPlan" và
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md.

S2/waiting_approval path và idempotent-replay-no-side-effect tests đầy đủ nằm ở
test_turns_text_s2.py (Task 9) — file này chỉ phủ nhánh S1/completed cộng các
kiểm tra request-context/ownership dùng chung cho cả hai nhánh.
"""

from fastapi.testclient import TestClient

from src.api import session_state
from src.main import app
from tests.test_api.ws_helpers import receive_n

_AUTH_HEADERS = {"X-Schema-Version": "1.0"}


def _login(client, email: str = "driver.demo@example.com", password: str = "DemoDriver123!") -> str:
    response = client.post("/api/v1/auth/login", headers=_AUTH_HEADERS, json={"email": email, "password": password})
    return response.json()["data"]["access_token"]


def _create_session(client, token: str, key: str, vehicle_id: str = "vehicle-demo-01") -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": key},
        json={"vehicle_id": vehicle_id},
    )
    return response.json()["data"]["session_id"]


def _connection_init(session_id: str) -> dict:
    return {
        "type": "connection.init",
        "client_message_id": "cmsg_1",
        "sent_at": "2026-08-10T00:00:00Z",
        "schema_version": "1.0",
        "session_id": session_id,
    }


def test_s1_text_command_returns_completed_with_the_canonical_action_plan_and_runs_ws_lifecycle():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:s1:001")

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(_connection_init(session_id))

            response = client.post(
                "/api/v1/turns/text",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Schema-Version": "1.0",
                    "Idempotency-Key": "turn:s1:001",
                },
                json={"session_id": session_id, "text": "Đặt điều hòa 22 độ"},
            )
            assert response.status_code == 200
            body = response.json()["data"]
            assert body["status"] == "completed"
            assert body["session_id"] == session_id
            plan = body["action_plan"]
            assert plan["requires_approval"] is False
            assert plan["steps"][0]["tool"] == "set_hvac_temperature"
            assert set(plan.keys()) == {
                "schema_version",
                "plan_id",
                "session_id",
                "vehicle_id",
                "vehicle_state_version",
                "steps",
                "requires_approval",
            }
            assert body["response"]["outcomes"][0]["status"] == "completed"
            turn_id = body["turn_id"]

            events = receive_n(ws, 4)

    types = [event["type"] for event in events]
    assert types == ["assistant.status", "tool.result", "assistant.response", "turn.completed"]
    assert all(event["turn_id"] == turn_id for event in events)
    assert all(event["session_id"] == session_id for event in events)


def test_text_over_1000_code_points_returns_422_input_invalid():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:toolong:001")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:toolong:001",
            },
            json={"session_id": session_id, "text": "a" * 1001},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"


def test_text_that_is_only_whitespace_returns_422_input_invalid():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:blank:001")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:blank:001",
            },
            json={"session_id": session_id, "text": "   "},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"


def test_nonexistent_session_returns_403_forbidden_not_404():
    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:missing:001",
            },
            json={"session_id": "ses_does_not_exist", "text": "Bật điều hòa"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_engineer_role_cannot_submit_a_text_turn():
    with TestClient(app) as client:
        token = _login(client, email="engineer.demo@example.com", password="DemoEngineer123!")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:eng:001",
            },
            json={"session_id": "ses_irrelevant", "text": "Bật điều hòa"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_missing_idempotency_key_returns_400():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:noik:001")
        response = client.post(
            "/api/v1/turns/text",
            headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"},
            json={"session_id": session_id, "text": "Bật điều hòa"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


def test_replaying_the_same_idempotency_key_does_not_rerun_the_turn_or_emit_new_ws_events():
    import anyio

    def _assert_no_further_event(ws, timeout: float = 0.3) -> None:
        async def _try_receive():
            with anyio.fail_after(timeout):
                return await ws._send_rx.receive()  # noqa: SLF001 - test helper, same technique as ws_helpers.receive_n

        try:
            message = ws.portal.call(_try_receive)
        except TimeoutError:
            return
        raise AssertionError(f"expected no further WS event on replay, got: {message}")

    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:replay:001")
        graph = session_state.get_graph(session_id)
        call_count = 0
        original_ainvoke = graph.ainvoke

        async def _counting_ainvoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await original_ainvoke(*args, **kwargs)

        graph.ainvoke = _counting_ainvoke

        headers = {
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "turn:replay:001",
        }
        payload = {"session_id": session_id, "text": "Đặt điều hòa 22 độ"}

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(_connection_init(session_id))
            first = client.post("/api/v1/turns/text", headers=headers, json=payload)
            receive_n(ws, 4)

            second = client.post("/api/v1/turns/text", headers=headers, json=payload)
            _assert_no_further_event(ws)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert call_count == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_text.py -v`
Expected: FAIL with 404 on every test (route doesn't exist yet)

- [ ] **Step 4: Implement the text-turn route**

In `src/api/turns.py`, update the import block at the top to add the new names (keep the existing ones — `HTTPException` stays imported and used by the untouched `/turns/voice` handler):

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.agents.contracts import ActionPlan, as_action_plan
from src.api.auth_deps import AuthenticatedUser, require_driver, require_idempotency_key, require_schema_version
from src.api.context import new_request_id, resolve_trace_id
from src.api.errors import ApiError
from src.api.session_state import get_graph, get_session_lock, get_session_record, get_vehicle, thread_config
from src.models.api import ActionPlanData, ActionPlanStep, Meta, TextTurnData, TextTurnEnvelope, TurnResponseData
from src.models.vehicle import SCHEMA_VERSION
from src.services import voice
from src.services.idempotency import IdempotencyRecord, fingerprint_for, get_idempotency_store
from src.services.ivi_events import assistant_response_payload, emit_turn_lifecycle, get_event_bus, now_iso
```

Add this near the top of the file, after the existing `_REQUIRED_PCM_PARAMETERS` constant:

```python
_TEXT_TURN_ROUTE = "POST /turns/text"


class TextTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    text: str


def _action_plan_model(plan: ActionPlan) -> ActionPlanData:
    return ActionPlanData(
        schema_version=plan.schema_version,
        plan_id=plan.plan_id,
        session_id=plan.session_id,
        vehicle_id=plan.vehicle_id,
        vehicle_state_version=plan.vehicle_state_version,
        steps=[
            ActionPlanStep(
                step_id=step.step_id,
                ordinal=step.ordinal,
                tool=step.tool,
                args=step.args,
                safety_level=step.safety_level,
                depends_on=list(step.depends_on),
            )
            for step in plan.steps
        ],
        requires_approval=plan.requires_approval,
    )
```

Add the route handler at the end of the file:

```python
@router.post("/turns/text", response_model=TextTurnEnvelope, dependencies=[Depends(require_schema_version)])
async def submit_text_turn(
    request: Request,
    body: TextTurnRequest,
    user: AuthenticatedUser = Depends(require_driver),
    idempotency_key: str = Depends(require_idempotency_key),
) -> TextTurnEnvelope:
    request_id = new_request_id()
    trace_id = resolve_trace_id(request)

    text = body.text.strip()
    if not (1 <= len(text) <= 1000):
        raise ApiError(
            status_code=422,
            code="INPUT_INVALID",
            message="text phải có 1-1000 code point Unicode sau khi trim",
            request_id=request_id,
            trace_id=trace_id,
        )

    session_record = get_session_record(body.session_id)
    if session_record is None or session_record.user_id != user.user_id:
        # Không phân biệt "session không tồn tại" với "session của người khác" —
        # tránh lộ enumeration. Xem design doc mục "POST /turns/text".
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="session không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    store = get_idempotency_store()
    fingerprint = fingerprint_for(body.model_dump())
    existing = store.lookup(user.user_id, _TEXT_TURN_ROUTE, idempotency_key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                message="Idempotency-Key đã dùng cho một request khác nội dung",
                request_id=request_id,
                trace_id=trace_id,
            )
        return TextTurnEnvelope.model_validate(existing.body)

    turn_id = f"turn_{uuid.uuid4().hex[:20]}"
    graph = get_graph(body.session_id)
    async with get_session_lock(body.session_id):
        result = await graph.ainvoke(
            {
                "query": text,
                "session_id": body.session_id,
                "vehicle_id": session_record.vehicle_id,
                "turn_id": turn_id,
            },
            config=thread_config(body.session_id),
        )

    bus = get_event_bus()
    envelope = await _build_text_turn_response(bus, body.session_id, turn_id, trace_id, request_id, result)
    store.save(
        user.user_id, _TEXT_TURN_ROUTE, idempotency_key,
        IdempotencyRecord(fingerprint=fingerprint, status_code=200, body=envelope.model_dump(mode="json")),
    )
    return envelope


async def _build_text_turn_response(
    bus, session_id: str, turn_id: str, trace_id: str, request_id: str, result: dict
) -> TextTurnEnvelope:
    await emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result)

    plan = result.get("action_plan")
    action_plan = _action_plan_model(as_action_plan(plan)) if plan is not None else None
    status = "failed" if result.get("outcome") == "execution_failed" else "completed"
    response_payload = assistant_response_payload(result)

    return TextTurnEnvelope(
        data=TextTurnData(
            session_id=session_id,
            turn_id=turn_id,
            status=status,
            action_plan=action_plan,
            response=TurnResponseData(
                display_text=response_payload["display_text"],
                speak_text=response_payload["speak_text"],
                citations=response_payload["citations"],
                outcomes=response_payload["outcomes"],
            ),
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )
```

`turns.py` already has `import uuid` at the top of the file (used by `submit_voice_turn`), so `uuid.uuid4()` above resolves without any new import.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_text.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: No regressions

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/api/turns.py src/services/ivi_events.py tests/test_api/test_turns_text.py
ruff format src/api/turns.py src/services/ivi_events.py tests/test_api/test_turns_text.py
git add src/api/turns.py src/services/ivi_events.py tests/test_api/test_turns_text.py
git commit -m "feat(api): add POST /api/v1/turns/text (S1/completed path)"
```

---

### Task 9: `POST /api/v1/turns/text` — S2/waiting_approval path

**Files:**
- Modify: `src/api/turns.py` — branch `_build_text_turn_response` on the interrupt case
- Test: `tests/test_api/test_turns_text_s2.py`

**Interfaces:**
- Consumes: everything from Task 8, plus `src.models.api.PendingApprovalData` (Task 1) and the `interrupt` payload shape already produced by `src/agents/nodes/approval.py::request_approval_node` (`approval_id, plan_id, prompt_text, steps_summary, expires_at, timeout_seconds`).
- Produces: nothing new for other tasks — this is the last task.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api/test_turns_text_s2.py
"""POST /api/v1/turns/text — nhánh S2/waiting_approval. Xem
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md mục "POST
/turns/text" (JSON shape cho waiting_approval) và event order
plan.ready -> approval.required -> assistant.status(waiting_approval)."""

from fastapi.testclient import TestClient

from src.main import app
from tests.test_api.ws_helpers import receive_n

_AUTH_HEADERS = {"X-Schema-Version": "1.0"}


def _login(client, email: str = "driver.demo@example.com", password: str = "DemoDriver123!") -> str:
    response = client.post("/api/v1/auth/login", headers=_AUTH_HEADERS, json={"email": email, "password": password})
    return response.json()["data"]["access_token"]


def _create_session(client, token: str, key: str, vehicle_id: str = "vehicle-demo-01") -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": key},
        json={"vehicle_id": vehicle_id},
    )
    return response.json()["data"]["session_id"]


def _connection_init(session_id: str) -> dict:
    return {
        "type": "connection.init",
        "client_message_id": "cmsg_1",
        "sent_at": "2026-08-10T00:00:00Z",
        "schema_version": "1.0",
        "session_id": session_id,
    }


def test_s2_command_returns_waiting_approval_and_does_not_execute():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:s2:001")

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(_connection_init(session_id))

            response = client.post(
                "/api/v1/turns/text",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Schema-Version": "1.0",
                    "Idempotency-Key": "turn:s2:001",
                },
                json={"session_id": session_id, "text": "Mở cửa sổ bên lái 30 phần trăm"},
            )
            assert response.status_code == 200
            body = response.json()["data"]
            assert body["status"] == "waiting_approval"
            assert body["action_plan"]["requires_approval"] is True
            assert body["action_plan"]["steps"][0]["tool"] == "set_window_position"
            assert body["pending_approval"]["approval_id"].startswith("appr-")
            assert body["pending_approval"]["expires_at"]
            assert body["response"]["outcomes"] == []
            turn_id = body["turn_id"]

            events = receive_n(ws, 3)

    types = [event["type"] for event in events]
    assert types == ["plan.ready", "approval.required", "assistant.status"]
    assert events[0]["payload"]["requires_approval"] is True
    assert events[0]["payload"]["plan_id"] == body["action_plan"]["plan_id"]
    assert events[1]["payload"]["approval_id"] == body["pending_approval"]["approval_id"]
    assert events[2]["payload"]["state"] == "waiting_approval"
    assert all(event["turn_id"] == turn_id for event in events)
    assert all(event["session_id"] == session_id for event in events)


def test_full_driver_flow_login_session_text_turn_then_approval_executes():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:e2e:001")

        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:e2e:001",
            },
            json={"session_id": session_id, "text": "Mở cửa sổ bên lái 30 phần trăm"},
        )
        approval_id = response.json()["data"]["pending_approval"]["approval_id"]

        decision = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )

    assert decision.status_code == 200
    assert decision.json()["approval_status"] == "consumed"
    assert decision.json()["plan_status"] == "executed"
    assert decision.json()["tool_results"][0]["status"] == "completed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_text_s2.py -v`
Expected: FAIL — `test_s2_command_returns_waiting_approval_and_does_not_execute` fails because `data.status` currently comes back `"completed"` (or the request errors, since `_build_text_turn_response` doesn't branch on the interrupt yet, and `TextTurnData.action_plan` would be built from a checkpointed-but-not-yet-approved plan without `pending_approval`); `test_full_driver_flow_...` fails because there's no `pending_approval` key in the response

- [ ] **Step 3: Branch `_build_text_turn_response` on the interrupt case**

In `src/api/turns.py`, add `PendingApprovalData` to the `src.models.api` import line from Task 8:

```python
from src.models.api import (
    ActionPlanData,
    ActionPlanStep,
    Meta,
    PendingApprovalData,
    TextTurnData,
    TextTurnEnvelope,
    TurnResponseData,
)
```

Replace the `_build_text_turn_response` function written in Task 8 with this version that checks for `__interrupt__` first, and add `_waiting_approval_response` after it:

```python
async def _build_text_turn_response(
    bus, session_id: str, turn_id: str, trace_id: str, request_id: str, result: dict
) -> TextTurnEnvelope:
    pending = result.get("__interrupt__")
    if pending:
        return await _waiting_approval_response(bus, session_id, turn_id, trace_id, request_id, result, pending)

    await emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result)

    plan = result.get("action_plan")
    action_plan = _action_plan_model(as_action_plan(plan)) if plan is not None else None
    status = "failed" if result.get("outcome") == "execution_failed" else "completed"
    response_payload = assistant_response_payload(result)

    return TextTurnEnvelope(
        data=TextTurnData(
            session_id=session_id,
            turn_id=turn_id,
            status=status,
            action_plan=action_plan,
            response=TurnResponseData(
                display_text=response_payload["display_text"],
                speak_text=response_payload["speak_text"],
                citations=response_payload["citations"],
                outcomes=response_payload["outcomes"],
            ),
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


async def _waiting_approval_response(
    bus, session_id: str, turn_id: str, trace_id: str, request_id: str, result: dict, pending
) -> TextTurnEnvelope:
    """Nhánh S2: KHÔNG thực thi plan. `plan.ready` phát trước `approval.required` vì
    `emit_turn_lifecycle`'s interrupt branch chỉ phát `approval.required` rồi
    `assistant.status(waiting_approval)` — không tự phát `plan.ready`. Đây là gap đã
    biết chung với voice turn (xem design doc); route text-turn tự phát bù ở đây thay
    vì sửa `emit_turn_lifecycle` (sửa chung sẽ đổi cả chuỗi sự kiện voice đã có test)."""
    payload = pending[0].value
    plan = as_action_plan(result["action_plan"])
    plan_model = _action_plan_model(plan)

    await bus.publish(
        session_id,
        "plan.ready",
        turn_id,
        trace_id,
        {
            "route_kind": "action",
            "plan_id": plan.plan_id,
            "summary": payload["prompt_text"],
            "requires_approval": True,
        },
    )
    await emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result)

    return TextTurnEnvelope(
        data=TextTurnData(
            session_id=session_id,
            turn_id=turn_id,
            status="waiting_approval",
            action_plan=plan_model,
            pending_approval=PendingApprovalData(approval_id=payload["approval_id"], expires_at=payload["expires_at"]),
            response=TurnResponseData(
                display_text=payload["prompt_text"],
                speak_text=payload["prompt_text"],
                citations=[],
                outcomes=[],
            ),
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_text_s2.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: No regressions versus this branch's baseline after `git pull` (run `.\.venv\Scripts\python.exe -m pytest tests/ -q` once before Task 1 if you haven't already, to record that baseline — it will differ from the old `feature/healthz-endpoint` branch's documented `166 passed, 5 failed, 1 collection error` because of the new vehicle-gateway/MQTT test files now present)

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/api/turns.py tests/test_api/test_turns_text_s2.py
ruff format src/api/turns.py tests/test_api/test_turns_text_s2.py
git add src/api/turns.py tests/test_api/test_turns_text_s2.py
git commit -m "feat(api): add POST /api/v1/turns/text waiting_approval (S2) path"
```

---

## Self-Review Notes

- **Spec coverage:** Login (Task 5), Create session (Task 7), Text turn S1 (Task 8) and S2 (Task 9), auth/RBAC (Tasks 2–3), request-context `X-Schema-Version`/`Idempotency-Key` (Task 3, wired into Tasks 5/7/8), idempotency replay/conflict (Tasks 4, 7, 8), session ownership (Task 6, enforced in Task 8), typed response envelopes (Task 1, used everywhere via `models/api.py` + `ApiError`), reuse of the existing agent pipeline (Tasks 8–9 call `graph.ainvoke`/`emit_turn_lifecycle`, the same functions `turns.py`'s voice handler and `approvals.py` already use) — all covered.
- **Placeholder scan:** No TBD/TODO; every step has runnable code and an expected test outcome.
- **Type consistency:** `AuthenticatedUser`, `SessionRecord`, `IdempotencyRecord`, `TokenRecord`, and the `models/api.py` envelope classes are used identically across every task that touches them (checked Tasks 1/2/3/4/6's "Produces" against 5/7/8/9's "Consumes").
- **Error-handling consistency (this revision's main fix):** every raised error in Tasks 3/5/7/8/9 uses `ApiError`, never `HTTPException`; every success response is a `models/api.py` model instance passed through `response_model=`, never a raw dict (except a replayed idempotent response, which is explicitly reconstructed via `Envelope.model_validate(...)` first). Verified by grepping the plan for `HTTPException` — the only remaining uses are in Task 8's note that `/turns/voice`'s existing (untouched, out-of-scope) handler keeps using it.
- **Known follow-up, not part of this plan:** wiring `require_driver`/`require_idempotency_key`/`require_schema_version` into `/turns/voice` and `/approvals/.../decision` (and migrating their error handling to `ApiError` too, for consistency), and WS auth on `/ws/ivi`/`/ws/engineer` — both explicitly out of scope per the design doc.

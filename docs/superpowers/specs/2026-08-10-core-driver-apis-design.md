# Core Driver APIs: Auth, Session & Text Turn — Design

Date: 2026-08-10
Status: Approved for planning

## Problem

Three of the twelve P0 public interfaces in `docs/api_spec.md` are unimplemented:
`POST /api/v1/auth/login`, `POST /api/v1/sessions`, `POST /api/v1/turns/text`. These
are the minimum needed for the canonical Driver flow: login → create session → submit
text turn. No auth/RBAC module exists anywhere in the codebase yet — `src/api/ws.py`
explicitly defers to it ("Module auth/session chưa tồn tại trong code").

`POST /api/v1/turns/voice` and `POST /api/v1/approvals/{approval_id}/decision` already
exist (`src/api/turns.py`, `src/api/approvals.py`) but currently run with no
authentication/idempotency/session-context enforcement — that is a documented,
separate gap and is **not** touched by this ticket.

Note: `CLAUDE.md` describes root `src/`/`tests/` as "untouched AI20K course
boilerplate." That is stale for this repo's current state — `src/` has ~2,900 lines
of real API/service code and `tests/` has a real suite (`test_api/`, `test_agents/`,
`test_services/`, etc.), including a fully working voice-turn pipeline and HITL
approval flow. This design builds on that real code, not the boilerplate.

**Revision note (2026-08-10, post-pull):** the original version of this design
invented its own `src/api/envelope.py` with a `success_envelope`/`error_detail`
pair, and had every route raise `HTTPException(detail=error_detail(...))`. Pulling
`origin/develop` after the initial approval surfaced that `develop` had, in the
meantime, landed exactly this problem's solution — and caught a real bug the
original design would have reintroduced: FastAPI always wraps `HTTPException`'s
`detail` in `{"detail": ...}`, so `HTTPException(detail={"error": {...}})`
serializes as `{"detail": {"error": {...}}}`, not the top-level `{"error": {...}}`
the contract requires (`src/api/errors.py`'s own docstring documents this exact
failure against `frontend/src/lib/services/shared/errors.ts`). This revision drops
the custom envelope module entirely and builds on develop's shared infra instead
(see Components, below). No conceptual request/response shape in this document
changes — only *how* those shapes get built and errors get raised.

## Scope

In scope: the 3 named endpoints, demo auth (Driver + Engineer roles), session
ownership, `X-Schema-Version` / `Idempotency-Key` request-context enforcement for
these 3 routes, standard response envelopes, and reusing the existing LangGraph
pipeline (`session_state.py`, `ivi_events.emit_turn_lifecycle`) for text turns.

Out of scope (explicitly, not silently dropped):
- Retrofitting auth/idempotency onto `/turns/voice` or `/approvals/.../decision`. This
  is a tracked follow-up once `src/services/auth.py`/`auth_deps.py` exist from this
  ticket — the dependencies this ticket adds are directly reusable there, but wiring
  them in is separate work with its own test surface, not a byproduct of this ticket.
- WS auth (`Sec-WebSocket-Protocol` bearer, origin/role checks on `/ws/ivi`,
  `/ws/engineer`) — already flagged as deferred in `ws.py`; a natural follow-up once
  this ticket lands, but not part of it.
- SQLite persistence for users/sessions/idempotency records (see Persistence below).
- Fixing the pre-existing gap where `plan.ready` is never emitted for voice turns —
  see Text-turn event emission below for how this ticket avoids widening that gap
  while still satisfying the normative event order for the new text-turn route.

## Persistence

In-memory, matching the existing tradeoff already documented in `session_state.py`
(LRU-capped `OrderedDict`, wiped on restart — accepted for the single-process PC
demo). No new DB schema/migration work. `data_model.md`'s relational `sessions`/
`users` tables describe the eventual P1 shape and are not implemented here.

## Demo users and tokens

Two hardcoded demo accounts, matching the spec's login example:

| email | password | role |
|---|---|---|
| `driver.demo@example.com` | `DemoDriver123!` | `driver` |
| `engineer.demo@example.com` | `DemoEngineer123!` | `engineer` |

Tokens are opaque random strings (not JWT — no signing infra exists in the repo and
none is needed for a single-process in-memory demo). `src/services/auth.py` owns an
in-memory `token -> {user_id, role, expires_at}` map, LRU-capped the same way
`session_state.py` caps sessions. TTL is a new `Settings.auth_token_ttl_seconds`
(default 12h — a demo session should comfortably outlive a work session without
needing re-login mid-demo).

## Components

### Reused from `origin/develop` (not reinvented)

- **`src/api/context.py`** — `new_request_id()` (always server-generated),
  `resolve_trace_id(request: Request)` (honors a syntactically valid client
  `X-Trace-Id`, else generates one — this is what `api_spec.md:9`'s "the server
  validates it or generates a trace ID when absent" actually means; every route in
  this ticket must call this, not always generate fresh, or client-supplied
  `X-Trace-Id` silently stops working for these three routes only).
- **`src/api/errors.py`** — `ApiError(status_code, code, message, request_id,
  trace_id, retryable=False, details=None)`, raised (not returned) from route
  handlers; a FastAPI exception handler already registered in `src/main.py`
  (`app.add_exception_handler(ApiError, api_error_handler)`) translates it to the
  correct top-level `{"error": {...}, "meta": ..., "trace_id": ..., "schema_version":
  ...}` body. All `AUTH_REQUIRED`/`FORBIDDEN`/`REQUEST_CONTEXT_INVALID`/
  `INPUT_INVALID`/`IDEMPOTENCY_CONFLICT` raises in this ticket use `ApiError`, never
  `HTTPException`.
- **`src/models/api.py`** — home for typed success/error envelope models
  (`Meta`, `ApiErrorBody`, `ErrorEnvelope` already exist; this ticket adds
  `LoginEnvelope`, `SessionEnvelope`, `TextTurnEnvelope` and their nested `data`
  models here, following the file's established `VehicleStateData`/
  `VehicleStateEnvelope` pattern). Routes declare `response_model=...Envelope` and
  return a model instance, the same way `GET /vehicle/state` already does — not a
  raw dict.

### New in this ticket

- **`src/services/auth.py`** (new) — demo user registry, `issue_token(email, password)`,
  `resolve_token(token)`. No dependency on the request/response infra above — pure
  service logic.
- **`src/api/auth_deps.py`** (new) — FastAPI dependencies, all raising `ApiError`
  (via `context.py`'s id helpers) instead of `HTTPException`:
  - `get_current_user`: parses `Authorization: Bearer <token>`; 401 `AUTH_REQUIRED` if
    missing/invalid/expired.
  - `require_role(role)`: 403 `FORBIDDEN` on role mismatch.
  - `require_schema_version`: `X-Schema-Version: 1.0` required; 400
    `REQUEST_CONTEXT_INVALID` otherwise. Login uses a variant accepting either the
    header or `version=1.0` in `Content-Type`, per the spec's login exception.
  - `require_idempotency_key`: extracts the header; 400 `REQUEST_CONTEXT_INVALID` if
    absent on a route that requires one.
- **`src/services/idempotency.py`** (new) — in-memory store keyed by
  `(user_id, route, idempotency_key)` → `{fingerprint, stored_response}`, LRU-capped.
  Fingerprint = hash of `(user_id, route, normalized request body)`. Same key + same
  fingerprint replays the stored response verbatim (including its original
  `trace_id`). Same key + different fingerprint → 409 `IDEMPOTENCY_CONFLICT`.
- **`src/api/auth_routes.py`** (new) — `POST /api/v1/auth/login`.
- **`src/api/session_routes.py`** (new) — `POST /api/v1/sessions`.
- **`src/api/session_state.py`** (extended) — new `SessionRecord` (`session_id,
  user_id, vehicle_id, status, started_at`), `create_session(user_id, vehicle_id)`,
  `get_session_record(session_id)`. Existing `get_vehicle`/`get_graph`/eviction reused
  and extended to also carry/evict `SessionRecord`. Untouched by develop's new
  commits — no merge conflict risk.
- **`src/api/turns.py`** (extended) — new `POST /turns/text` handler alongside the
  existing voice handler. Also untouched by develop's new commits.
- **`src/main.py`** — register the two new routers (the `ApiError` exception handler
  is already registered by develop's changes; nothing to add there).

## Request flows

### `POST /auth/login`

No `Authorization` required. Validates schema-version via the login exception rule.
Body `{email, password}`. Wrong/missing credentials → 401 `AUTH_REQUIRED` — the spec's
error table defines only `AUTH_REQUIRED`/`FORBIDDEN` for the auth area, no dedicated
bad-credentials code, so this reuses `AUTH_REQUIRED` rather than inventing an
undocumented one. Success returns the exact envelope shape in the spec example
(`access_token`, `token_type`, `expires_at`, `user{user_id, role, display_name}`).

### `POST /sessions`

Requires Bearer Driver, `X-Schema-Version`, `Idempotency-Key`. Body
`{vehicle_id, input_mode}`. Creates a `SessionRecord` owned by the caller; calls
existing `get_vehicle(session_id)` / `get_graph(session_id)` to pre-warm runtime
state so the first text/voice turn on that session doesn't pay first-touch cost
differently from later turns. Returns the spec's session envelope
(`session_id, vehicle_id, status="active", started_at`).

### `POST /turns/text`

Requires Bearer Driver/owner, `X-Schema-Version`, `Idempotency-Key`. Body
`{session_id, text}`; `text` is 1–1,000 Unicode code points after trim, else 422
`INPUT_INVALID`. Looks up `SessionRecord` by `session_id`:

- **Session does not exist** → 403 `FORBIDDEN`, not 404. `api_spec.md` defines no
  `SESSION_NOT_FOUND` code, and returning 404 here would let a caller distinguish
  "no such session" from "exists but not yours" — an enumeration leak against the
  ownership rule ("Driver may use only their current/owned session"). Both cases are
  therefore indistinguishable 403s.
- **Session exists but owned by a different user** → 403 `FORBIDDEN`, same reason,
  same response shape as the missing-session case.

Under the existing `get_session_lock(session_id)`, calls
`graph.ainvoke({"query": text, "session_id": ..., "vehicle_id": ..., "turn_id": ...},
config=thread_config(session_id))` synchronously — the same call shape
`agent_routes.py`/voice already use, but awaited inline instead of via
`BackgroundTasks`, since the text-turn REST response is meant to carry the real
result per the spec's synchronous example.

Two outcomes:

- **No approval needed (S0/S1)**: build `action_plan`/`response` matching the spec's
  example exactly (`schema_version, plan_id, session_id, vehicle_id,
  vehicle_state_version, steps, requires_approval` for the plan;
  `display_text, speak_text, citations, outcomes` for the response). Call
  `emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result)` so `/ws/ivi`
  observers see the same events voice turns produce. Return
  `data.status = "completed"`.

- **S2 interrupt (approval required)**: return `data.status = "waiting_approval"`
  (reusing the same enum value the spec's own `GET /traces/{trace_id}` example uses
  for this exact state), the candidate `action_plan` with `requires_approval: true`,
  and pending-approval metadata (`approval_id`, `expires_at` — sourced from the
  interrupt payload, same fields `emit_turn_lifecycle` already reads off
  `pending[0].value`). Do not execute the plan; execution only happens after
  `POST /approvals/{approval_id}/decision` succeeds (existing, unchanged behavior in
  `approvals.py`).

  Exact response shape (fields not shown elsewhere in `api_spec.md`, so spelled out
  here rather than left implicit):

  ```json
  {
    "data": {
      "session_id": "ses_01J...",
      "turn_id": "turn_01J...",
      "status": "waiting_approval",
      "action_plan": {
        "schema_version": "1.0",
        "plan_id": "plan_01J...",
        "session_id": "ses_01J...",
        "vehicle_id": "vehicle-demo-01",
        "vehicle_state_version": 42,
        "steps": [
          {
            "step_id": "step_01J...",
            "ordinal": 1,
            "tool": "open_window",
            "args": {"window": "driver", "position_pct": 100},
            "safety_level": "S2",
            "depends_on": []
          }
        ],
        "requires_approval": true
      },
      "pending_approval": {
        "approval_id": "appr_01J...",
        "expires_at": "2026-07-31T10:00:30Z"
      },
      "response": {
        "display_text": "Bạn có muốn hạ cửa sổ không?",
        "speak_text": "Bạn có muốn hạ cửa sổ không?",
        "citations": [],
        "outcomes": []
      }
    },
    "meta": {"request_id": "req_text_002"},
    "trace_id": "tr_client_text_002",
    "schema_version": "1.0"
  }
  ```

  `action_plan` keeps exactly the same canonical field set as the S1 example (no
  extra/missing fields — same rule the spec states for the completed case).
  `pending_approval` and top-level `status` are the only additions versus the S1
  shape; `response.outcomes` is empty because nothing has executed yet.

  Event order on `/ws/ivi` for this case: `plan.ready`, `approval.required`, then
  `assistant.status(state="waiting_approval")`. `emit_turn_lifecycle`'s interrupt
  branch currently emits only the latter two — it does not emit `plan.ready` (a
  pre-existing gap shared with voice turns, which this ticket does not fix for voice
  to avoid changing voice's already-tested event sequence). The text-turn route
  therefore publishes `plan.ready` itself (with `route_kind, plan_id, summary,
  requires_approval` from the materialized candidate plan) immediately before
  delegating the rest of interrupt handling to `emit_turn_lifecycle`.

## Idempotency

Applies to `POST /sessions` and `POST /turns/text` only (per the contract table).
Missing key → 400 `REQUEST_CONTEXT_INVALID`. Exact replay (same user, route, key,
fingerprint) returns the exact prior stored response, including its original
`trace_id`, and performs no new work: no new `SessionRecord`, no second
`graph.ainvoke` call, and — because the stored response is returned directly instead
of re-running the handler — no re-publish on the `IviEventBus`. A replayed
`turns/text` call therefore produces zero additional `/ws/ivi` events (no duplicate
`plan.ready`/`tool.result`/`turn.completed`/etc.) and a replayed `sessions` call
creates no second session and does not re-touch `get_vehicle`/`get_graph`.
Reused key with a different fingerprint → 409 `IDEMPOTENCY_CONFLICT`.

## Error codes used

All from the existing spec table (`docs/api_spec.md` validation/errors section) —
no new codes invented: `AUTH_REQUIRED` (401), `FORBIDDEN` (403),
`REQUEST_CONTEXT_INVALID` (400), `INPUT_INVALID` (422), `IDEMPOTENCY_CONFLICT` (409).

## Testing

New test files, following existing fixture/naming conventions:

- `tests/test_services/test_auth.py` — token issuance/validation/expiry, wrong
  credentials, role resolution.
- `tests/test_services/test_idempotency.py` — replay returns stored response,
  conflicting fingerprint returns `IDEMPOTENCY_CONFLICT`, missing key rejected.
- `tests/test_api/test_auth_routes.py` — login success (driver + engineer), bad
  credentials, missing schema-version.
- `tests/test_api/test_session_routes.py` — create session, ownership recorded,
  missing/invalid role rejected, idempotent replay.
- `tests/test_api/test_turns_text.py` — S1 completed flow end-to-end (matches spec
  example), S2 waiting_approval flow (plan.ready → approval.required →
  waiting_approval on `/ws/ivi`, no execution before approval decision), input
  validation (empty/over-length text), cross-owner session → `FORBIDDEN`, missing
  session → `FORBIDDEN`, idempotent replay, missing `Idempotency-Key`/
  `X-Schema-Version`.

Acceptance criteria carried over from `api_spec.md`'s own list, scoped to these 3
routes: unauthenticated/wrong-role access fails; POST context placement enforced;
duplicate idempotency key cannot duplicate a turn or session; `ActionPlan` fields
match the canonical schema exactly; privacy rule holds (no raw prompts/chain-of-
thought/credentials in any response).

Additional assertions specific to this ticket, per review feedback:
- An idempotent replay of `POST /turns/text` (same user/key/fingerprint) attaches a
  spy/counting listener to `IviEventBus` for the session and asserts **zero** events
  are published on the replay call — only the original call produced events.
- An idempotent replay of `POST /sessions` asserts `session_count()` is unchanged
  and the returned `session_id` is byte-identical to the first response's.
- Both replay tests also assert the graph/vehicle singletons for that session
  (`get_graph`/`get_vehicle` identity) are untouched by the replay call, ruling out
  a second silent `ainvoke`.

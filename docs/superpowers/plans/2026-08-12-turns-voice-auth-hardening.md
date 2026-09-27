# `POST /turns/voice` auth hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `POST /api/v1/turns/voice` up to the auth contract `docs/api_spec.md` already
documents for it — bearer/driver auth, session ownership, `X-Schema-Version`, and
`Idempotency-Key` — by reusing the exact mechanisms `POST /api/v1/turns/text` already has,
closing the gap `docs/superpowers/specs/2026-08-09-voice-turn-api-design.md` deliberately
left open.

**Architecture:** Add the same three FastAPI dependencies `submit_text_turn` already uses
(`require_schema_version`, `require_driver`, `require_idempotency_key`) to
`submit_voice_turn`, add the same session-ownership check, and wire the existing
`IdempotencyStore` using a fingerprint over `(content_type, sha256(audio_bytes))` since the
body is raw bytes, not JSON. No new files, no new abstractions — every piece already exists
and is proven on `/turns/text`.

**Tech Stack:** FastAPI (`Depends`), the existing `src/api/auth_deps.py` dependencies, the
existing `src/services/idempotency.py` store, pytest + `TestClient`.

## Global Constraints

- Full design rationale, including the idempotency failure-window discussion, lives in
  `docs/superpowers/specs/2026-08-12-turns-voice-auth-hardening-design.md` — read it before
  Task 3 if anything below is unclear.
- Error codes/status are fixed by existing convention, do not invent new ones: `401
  AUTH_REQUIRED`, `403 FORBIDDEN`, `400 REQUEST_CONTEXT_INVALID`, `409
  IDEMPOTENCY_CONFLICT`, `422 INPUT_INVALID` (this last one unchanged from before this
  ticket).
- Tests must run with `MQTT_ENABLED=false` (PowerShell: `$env:MQTT_ENABLED="false"`) or every
  `TestClient(app)` burns 10s waiting for a broker that isn't there.
- Run the full command from repo root: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -q`
  (add `-v` while iterating on a single test with `::test_name`).
- ruff line-length 120; run `ruff check src/ tests/` and `ruff format src/ tests/` before each commit if you touched formatting-sensitive code.
- Follow existing code style in `src/api/turns.py`: Vietnamese comments for the "why", not
  the "what"; `ApiError` (not `HTTPException`) for anything that isn't the pre-existing
  Content-Type 422 check, because `ApiError` has the registered handler that produces the
  top-level `{"error": {...}}` envelope instead of `HTTPException`'s `{"detail": {...}}`
  wrapping.

---

## Task 1: Bearer auth (`require_driver`) + `X-Schema-Version` on `/turns/voice`

**Files:**
- Modify: `src/api/turns.py:110-111` (route decorator + signature)
- Modify: `tests/test_api/test_turns_voice.py` (imports, new header helper, update existing
  HTTP-calling tests, three new tests)

**Interfaces:**
- Consumes: `require_driver`, `require_schema_version`, `AuthenticatedUser` — all already
  imported in `src/api/turns.py:18` (`from src.api.auth_deps import AuthenticatedUser,
  require_driver, require_idempotency_key, require_schema_version`). No new imports needed
  for this task.
- Produces: `submit_voice_turn(session_id, request, background_tasks, user)` — the `user:
  AuthenticatedUser` parameter later tasks (2, 3) will read `user.user_id` from.

- [ ] **Step 1: Write the failing tests**

Open `tests/test_api/test_turns_voice.py`. Change the import line at the top:

```python
from tests.test_api.ws_helpers import ivi_connect_kwargs, login, login_engineer, receive_n
```

Add this helper right after the `_stub_stt` function (after line 51, before
`test_s1_voice_command_runs_full_lifecycle_to_turn_completed`):

```python
def _voice_headers(token: str, content_type: str, idempotency_key: str | None = None) -> dict:
    """Header set for a `/turns/voice` call. `idempotency_key` stays optional here — Task 3
    is what makes the route require it; passing `None` (the default) omits the header so
    Task 1/2 tests, written before that requirement exists, keep working unchanged."""
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Schema-Version": "1.0",
        "Content-Type": content_type,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers
```

Add these three new tests at the end of the file (after
`test_route_is_in_the_public_openapi_surface`):

```python
def test_missing_bearer_token_returns_401():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-noauth"},
            headers={"X-Schema-Version": "1.0", "Content-Type": "audio/wav"},
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_engineer_role_cannot_submit_a_voice_turn():
    with TestClient(app) as client:
        token = login_engineer(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-wrongrole"},
            headers=_voice_headers(token, "audio/wav"),
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_missing_schema_version_returns_400():
    with TestClient(app) as client:
        token = login(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-noschema"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "audio/wav"},
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -k "missing_bearer or wrong_role or missing_schema_version" -v`

Expected: all three FAIL. `test_missing_bearer_token_returns_401` and
`test_missing_schema_version_returns_400` currently get `202` (no auth enforced yet).
`test_engineer_role_cannot_submit_a_voice_turn` also currently gets `202`.

- [ ] **Step 3: Implement the auth dependencies**

In `src/api/turns.py`, replace lines 110-111:

```python
@router.post("/turns/voice", status_code=202)
async def submit_voice_turn(session_id: str, request: Request, background_tasks: BackgroundTasks) -> dict:
```

with:

```python
@router.post("/turns/voice", status_code=202, dependencies=[Depends(require_schema_version)])
async def submit_voice_turn(
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_driver),
) -> dict:
```

Nothing else in the function body changes for this task — `user` is unused until Task 2,
which is fine, FastAPI still resolves and validates the dependency.

- [ ] **Step 4: Update every existing test that POSTs to `/turns/voice` to send valid auth headers**

These tests currently call the route with only `{"Content-Type": ...}` headers and will now
fail with `401` unless updated. Make these exact replacements in
`tests/test_api/test_turns_voice.py`:

In `test_s1_voice_command_runs_full_lifecycle_to_turn_completed`, replace:
```python
            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers={"Content-Type": "audio/wav"},
                content=b"fake-wav-bytes",
            )
```
with:
```python
            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers=_voice_headers(token, "audio/wav"),
                content=b"fake-wav-bytes",
            )
```
(`token` is already in scope from the existing `token = login(client)` line above it.)

In `test_bad_content_type_returns_422_and_never_schedules_a_turn`, replace the whole body:
```python
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-bad-ct"},
            headers={"Content-Type": "audio/webm"},
            content=b"whatever",
        )

    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "INPUT_INVALID"
```
with:
```python
    with TestClient(app) as client:
        token = login(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-bad-ct"},
            headers=_voice_headers(token, "audio/webm"),
            content=b"whatever",
        )

    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "INPUT_INVALID"
```

In `test_content_type_decision_reaches_the_endpoint`, replace:
```python
    def _post(client, session_id, content_type):
        return client.post(
            "/api/v1/turns/voice",
            params={"session_id": session_id},
            headers={"Content-Type": content_type},
            content=b"fake-audio",
        )

    with TestClient(app) as client:
        assert _post(client, "ses-ct-wav-param", "audio/wav; codecs=1").status_code == 202
        assert _post(client, "ses-ct-pcm-ok", "audio/pcm;rate=16000;channels=1;format=s16le").status_code == 202
        bad = _post(client, "ses-ct-pcm-bad", "audio/pcm;rate=8000")
```
with:
```python
    def _post(client, token, session_id, content_type):
        return client.post(
            "/api/v1/turns/voice",
            params={"session_id": session_id},
            headers=_voice_headers(token, content_type),
            content=b"fake-audio",
        )

    with TestClient(app) as client:
        token = login(client)
        assert _post(client, token, "ses-ct-wav-param", "audio/wav; codecs=1").status_code == 202
        assert _post(client, token, "ses-ct-pcm-ok", "audio/pcm;rate=16000;channels=1;format=s16le").status_code == 202
        bad = _post(client, token, "ses-ct-pcm-bad", "audio/pcm;rate=8000")
```
(Task 2 will revisit the two `202`-expecting session ids here — they're arbitrary strings
today and ownership isn't enforced yet, so this is correct for now.)

In `test_unusable_audio_emits_unusable_transcript_and_turn_failed`,
`test_stt_misconfiguration_is_reported_as_internal_error_not_unusable_audio`, and
`test_transcribe_runs_off_the_event_loop_thread`, each has one occurrence of:
```python
            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers={"Content-Type": "audio/wav"},
                content=b"...",  # varies per test — keep the existing content bytes unchanged
            )
```
Replace `headers={"Content-Type": "audio/wav"}` with `headers=_voice_headers(token, "audio/wav")`
in all three (each already has `token = login(client)` in scope above it). Leave every
other line, including the `content=` value, untouched.

- [ ] **Step 5: Run the full file and verify everything passes**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -q`

Expected: PASS, all tests green.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/api/turns.py tests/test_api/test_turns_voice.py
ruff format src/api/turns.py tests/test_api/test_turns_voice.py
git add src/api/turns.py tests/test_api/test_turns_voice.py
git commit -m "feat(api): require driver bearer auth + X-Schema-Version on /turns/voice"
```

---

## Task 2: Session ownership check

**Files:**
- Modify: `src/api/turns.py` (ownership check in `submit_voice_turn`)
- Modify: `tests/test_api/test_turns_voice.py` (`_owned_session` docstring, two new tests,
  fix up `test_content_type_decision_reaches_the_endpoint`)

**Interfaces:**
- Consumes: `user.user_id` (from Task 1's `Depends(require_driver)`), `get_session_record`
  (already imported at `src/api/turns.py:21`), `ApiError` (already imported at
  `src/api/turns.py:20`).
- Produces: no new names for later tasks — Task 3 only adds idempotency, it doesn't touch
  the ownership check's position or behavior.

- [ ] **Step 1: Write the failing tests**

Add these two tests to `tests/test_api/test_turns_voice.py` (after the three Task 1 tests
added at the end of the file):

```python
def test_nonexistent_session_returns_403_forbidden_not_404():
    with TestClient(app) as client:
        token = login(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses_does_not_exist"},
            headers=_voice_headers(token, "audio/wav"),
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_cross_owner_session_returns_403_forbidden_not_404():
    """Nhánh 'session tồn tại nhưng thuộc người khác' của cùng if — kiểm riêng khỏi
    'session không tồn tại' ở trên, cùng lý do test_turns_text.py đã tách hai case này."""
    with TestClient(app) as client:
        token = login(client)
        other_session = session_state.create_session("usr_someone_else", "vehicle-demo-01")
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": other_session.session_id},
            headers=_voice_headers(token, "audio/wav"),
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
```

(`session_state` is already imported at the top of the file:
`from src.api import session_state, turns`.)

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -k "nonexistent_session or cross_owner" -v`

Expected: both FAIL with `202`, not `403` — ownership isn't checked yet.

- [ ] **Step 3: Implement the ownership check**

In `src/api/turns.py`, inside `submit_voice_turn`, find:

```python
    audio_bytes = await request.body()
    turn_id = f"turn_voice_{uuid.uuid4().hex[:20]}"

    # Đảm bảo simulator/graph của session tồn tại trước khi task nền cần tới.
    get_vehicle(session_id)
    get_graph(session_id)
```

Replace it with:

```python
    session_record = get_session_record(session_id)
    if session_record is None or session_record.user_id != user.user_id:
        # Không phân biệt "session không tồn tại" với "session của người khác" —
        # tránh lộ enumeration, giống submit_text_turn.
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="session không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    audio_bytes = await request.body()
    turn_id = f"turn_voice_{uuid.uuid4().hex[:20]}"

    # Đảm bảo simulator/graph của session tồn tại trước khi task nền cần tới.
    get_vehicle(session_id)
    get_graph(session_id)
```

- [ ] **Step 4: Fix the two now-broken 202-path assertions in `test_content_type_decision_reaches_the_endpoint`**

That test currently posts to `"ses-ct-wav-param"` and `"ses-ct-pcm-ok"` — arbitrary strings
that are not owned sessions, so they'll now get `403` instead of the expected `202`. Update
the `with TestClient(app) as client:` block in that test to:

```python
    with TestClient(app) as client:
        token = login(client)
        wav_session = _owned_session()
        pcm_session = _owned_session()
        assert _post(client, token, wav_session, "audio/wav; codecs=1").status_code == 202
        assert _post(client, token, pcm_session, "audio/pcm;rate=16000;channels=1;format=s16le").status_code == 202
        bad = _post(client, token, "ses-ct-pcm-bad", "audio/pcm;rate=8000")
```

Leave the third call (`"ses-ct-pcm-bad"`, expecting `422`) as an arbitrary/unowned session —
the Content-Type check runs before the ownership check, so that assertion is unaffected.

- [ ] **Step 5: Update the `_owned_session` docstring — it currently claims the opposite of what's now true**

Replace:
```python
def _owned_session(user_id: str = "usr_driver_01") -> str:
    """`/turns/voice` không kiểm ownership, nhưng `/ws/ivi` giờ có (issue #47)."""
    return session_state.create_session(user_id, "vehicle-demo-01").session_id
```
with:
```python
def _owned_session(user_id: str = "usr_driver_01") -> str:
    """Session sở hữu bởi `usr_driver_01` (user mặc định của `login()`), cần cho mọi
    test phải vượt qua session-ownership check của `/turns/voice`."""
    return session_state.create_session(user_id, "vehicle-demo-01").session_id
```

- [ ] **Step 6: Run the full file and verify everything passes**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -q`

Expected: PASS, all tests green.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/api/turns.py tests/test_api/test_turns_voice.py
ruff format src/api/turns.py tests/test_api/test_turns_voice.py
git add src/api/turns.py tests/test_api/test_turns_voice.py
git commit -m "feat(api): enforce session ownership on /turns/voice"
```

---

## Task 3: `Idempotency-Key` enforcement + replay semantics

**Files:**
- Modify: `src/api/turns.py` (imports, `_VOICE_TURN_ROUTE` constant, idempotency wiring in
  `submit_voice_turn`, module docstring)
- Modify: `tests/test_api/test_turns_voice.py` (add `idempotency_key=` to every existing
  HTTP-calling test, three new tests)

**Interfaces:**
- Consumes: `IdempotencyInProgress`, `IdempotencyRecord`, `fingerprint_for`,
  `get_idempotency_store`, `require_idempotency_key` — all already imported in
  `src/api/turns.py` (lines 18 and 33). `hashlib` is new — stdlib, add to the import block.
- Produces: nothing further downstream — this is the last task in the plan.

- [ ] **Step 1: Write the failing tests**

Add three new tests at the end of `tests/test_api/test_turns_voice.py`:

```python
def test_missing_idempotency_key_returns_400():
    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": session_id},
            headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Content-Type": "audio/wav"},
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


def test_replaying_the_same_idempotency_key_and_audio_returns_the_same_turn_id_without_a_second_background_task(
    monkeypatch,
):
    import anyio

    def _assert_no_further_event(ws, timeout: float = 0.3) -> None:
        async def _try_receive():
            with anyio.fail_after(timeout):
                return await ws._send_rx.receive()  # noqa: SLF001 - same technique as ws_helpers.receive_n

        try:
            message = ws.portal.call(_try_receive)
        except TimeoutError:
            return
        raise AssertionError(f"expected no further WS event on replay, got: {message}")

    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        headers = _voice_headers(token, "audio/wav", idempotency_key="voice:replay:001")

        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))

            first = client.post(
                "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"same-audio"
            )
            receive_n(ws, 9)

            second = client.post(
                "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"same-audio"
            )
            _assert_no_further_event(ws)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()


def test_same_idempotency_key_with_different_audio_returns_409(monkeypatch):
    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        headers = _voice_headers(token, "audio/wav", idempotency_key="voice:conflict:001")

        first = client.post(
            "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"audio-one"
        )
        second = client.post(
            "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"audio-two"
        )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -k "idempotency_key or replaying_the_same or same_idempotency_key" -v`

Expected: all three FAIL — `test_missing_idempotency_key_returns_400` gets `202` (not
required yet); the replay test's `second.json() == first.json()` fails because both calls
currently run `_process_voice_turn` independently and generate different `turn_id`s; the
conflict test gets `202`/`202` instead of `202`/`409`.

- [ ] **Step 3: Add the `hashlib` import and `_VOICE_TURN_ROUTE` constant**

In `src/api/turns.py`, the stdlib import block currently reads:
```python
import asyncio
import logging
import time
import uuid
```
Change to:
```python
import asyncio
import hashlib
import logging
import time
import uuid
```

Just below `_TEXT_TURN_ROUTE = "POST /turns/text"`, add:
```python
_VOICE_TURN_ROUTE = "POST /turns/voice"
```

- [ ] **Step 4: Wire idempotency into `submit_voice_turn`**

Change the route decorator/signature (from Task 1's version) to add the dependency:
```python
@router.post("/turns/voice", status_code=202, dependencies=[Depends(require_schema_version)])
async def submit_voice_turn(
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_driver),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
```

Replace the tail of the function — everything from the ownership check (added in Task 2)
through the `return {...}` — with:

```python
    session_record = get_session_record(session_id)
    if session_record is None or session_record.user_id != user.user_id:
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="session không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    audio_bytes = await request.body()

    # Đảm bảo simulator/graph của session tồn tại trước khi task nền cần tới.
    get_vehicle(session_id)
    get_graph(session_id)

    store = get_idempotency_store()
    # Body là bytes thô, không phải JSON — fingerprint qua nội dung + Content-Type thay vì
    # gọi fingerprint_for(body: dict) trực tiếp trên audio_bytes.
    fingerprint = fingerprint_for(
        {"content_type": content_type, "audio_sha256": hashlib.sha256(audio_bytes).hexdigest()}
    )
    try:
        existing = await store.begin(user.user_id, _VOICE_TURN_ROUTE, idempotency_key, fingerprint)
    except IdempotencyInProgress as exc:
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
        return existing.body

    try:
        turn_id = f"turn_voice_{uuid.uuid4().hex[:20]}"
        background_tasks.add_task(_process_voice_turn, session_id, turn_id, trace_id, audio_bytes)
        envelope = {
            "data": {"session_id": session_id, "turn_id": turn_id, "status": "accepted", "input_mode": "voice"},
            "meta": {"request_id": request_id, "realtime": "WS /ws/ivi"},
            "trace_id": trace_id,
            "schema_version": SCHEMA_VERSION,
        }
    except BaseException:  # noqa: BLE001 - CancelledError không kế thừa Exception, cùng lý do submit_text_turn
        await store.abandon(user.user_id, _VOICE_TURN_ROUTE, idempotency_key)
        raise

    await store.finish(
        user.user_id,
        _VOICE_TURN_ROUTE,
        idempotency_key,
        IdempotencyRecord(fingerprint=fingerprint, status_code=202, body=envelope),
    )
    return envelope
```

`finish()` records the 202 acceptance, not the eventual processing result — see the design
doc's "Idempotency semantics" section for why this is the correct guarantee for an async 202
route rather than a shortcut.

- [ ] **Step 5: Update the module docstring — the "minimal-slice" claim is now false**

Replace the module docstring at the top of `src/api/turns.py`:
```python
"""`POST /api/v1/turns/voice` — chấp nhận audio bất đồng bộ, phát lifecycle qua `/ws/ivi`.

Phạm vi minimal-slice: không xác thực Authorization/Idempotency-Key/X-Schema-Version,
không có replay. Xem docs/superpowers/specs/2026-08-09-voice-turn-api-design.md.
"""
```
with:
```python
"""`POST /api/v1/turns/voice` — chấp nhận audio bất đồng bộ, phát lifecycle qua `/ws/ivi`.

Bearer auth (driver-only), session ownership, `X-Schema-Version`, và `Idempotency-Key` đều
được xác thực — cùng cơ chế `submit_text_turn` dùng. Xem
docs/superpowers/specs/2026-08-12-turns-voice-auth-hardening-design.md cho lý do và ngữ
nghĩa idempotency của route bất đồng bộ này. `/ws/ivi` replay cursors vẫn chưa có; xem mục
"Out of scope" của docs/superpowers/specs/2026-08-09-voice-turn-api-design.md.
"""
```

- [ ] **Step 6: Add `idempotency_key=` to every remaining existing test that now needs it**

The route requires `Idempotency-Key` on every call now. Update these existing tests in
`tests/test_api/test_turns_voice.py` — each just needs its `_voice_headers(...)` call
(or, for the two Task 2 tests, its explicit headers dict) to pass a unique
`idempotency_key`:

- `test_s1_voice_command_runs_full_lifecycle_to_turn_completed`:
  `headers=_voice_headers(token, "audio/wav", idempotency_key="voice:s1:001")`
- `test_bad_content_type_returns_422_and_never_schedules_a_turn`:
  `headers=_voice_headers(token, "audio/webm", idempotency_key="voice:badct:001")`
- `test_content_type_decision_reaches_the_endpoint`: give `_post` a fourth parameter and
  thread distinct keys through:
  ```python
  def _post(client, token, session_id, content_type, idempotency_key):
      return client.post(
          "/api/v1/turns/voice",
          params={"session_id": session_id},
          headers=_voice_headers(token, content_type, idempotency_key=idempotency_key),
          content=b"fake-audio",
      )

  with TestClient(app) as client:
      token = login(client)
      wav_session = _owned_session()
      pcm_session = _owned_session()
      assert _post(client, token, wav_session, "audio/wav; codecs=1", "voice:ct:wav:001").status_code == 202
      assert (
          _post(
              client, token, pcm_session, "audio/pcm;rate=16000;channels=1;format=s16le", "voice:ct:pcmok:001"
          ).status_code
          == 202
      )
      bad = _post(client, token, "ses-ct-pcm-bad", "audio/pcm;rate=8000", "voice:ct:pcmbad:001")
  ```
- `test_unusable_audio_emits_unusable_transcript_and_turn_failed`:
  `headers=_voice_headers(token, "audio/wav", idempotency_key="voice:unusable:001")`
- `test_stt_misconfiguration_is_reported_as_internal_error_not_unusable_audio`:
  `headers=_voice_headers(token, "audio/wav", idempotency_key="voice:sttmis:001")`
- `test_transcribe_runs_off_the_event_loop_thread`:
  `headers=_voice_headers(token, "audio/wav", idempotency_key="voice:offthread:001")`
- `test_nonexistent_session_returns_403_forbidden_not_404` (Task 2):
  `headers=_voice_headers(token, "audio/wav", idempotency_key="voice:nonexist:001")`
- `test_cross_owner_session_returns_403_forbidden_not_404` (Task 2):
  `headers=_voice_headers(token, "audio/wav", idempotency_key="voice:crossowner:001")`

`test_missing_bearer_token_returns_401`, `test_engineer_role_cannot_submit_a_voice_turn`,
and `test_missing_schema_version_returns_400` need no change — each already fails on an
earlier dependency (auth or schema version) before `require_idempotency_key` would even
run.

- [ ] **Step 7: Run the full file and verify everything passes**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -q`

Expected: PASS, all tests green.

- [ ] **Step 8: Run the full backend suite to check for regressions elsewhere**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`

Expected: same pass/skip count as `CLAUDE.md` documents (790 passed, 15 skipped) plus the 8
new tests added across this plan (3 in Task 1, 2 in Task 2, 3 in Task 3) — 798 passed, 15
skipped. If anything outside `test_turns_voice.py` fails, stop and investigate before
committing — nothing in this plan should touch behavior outside `/turns/voice`.

- [ ] **Step 9: Lint and commit**

```bash
ruff check src/api/turns.py tests/test_api/test_turns_voice.py
ruff format src/api/turns.py tests/test_api/test_turns_voice.py
git add src/api/turns.py tests/test_api/test_turns_voice.py
git commit -m "feat(api): enforce Idempotency-Key on /turns/voice, matching /turns/text"
```

- [ ] **Step 10: Update WORKLOG.md**

Add a dated entry to `WORKLOG.md` for today (2026-08-12) in the existing table format,
summarizing the three commits and linking this plan + the design doc. Follow the format of
the most recent entry already in the file.

---

## Self-review notes (for whoever executes this plan)

- Every task leaves `tests/test_api/test_turns_voice.py` fully green — Task 1 doesn't
  depend on Task 2 or 3 landing to be correct and mergeable on its own, and likewise Task 2
  doesn't depend on Task 3.
- The four spec requirements (bearer/driver, ownership, schema-version, idempotency) map
  1:1 to Tasks 1 (bearer+schema-version), 2 (ownership), 3 (idempotency) — nothing in
  `docs/superpowers/specs/2026-08-12-turns-voice-auth-hardening-design.md`'s Scope section
  is left uncovered.
- Do not touch `_process_voice_turn`'s hardcoded `"vehicle_id": "veh-demo"` (line ~227 of
  `src/api/turns.py`) — it's a pre-existing, unrelated gap, out of scope for this plan.

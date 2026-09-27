# `POST /turns/voice` auth hardening — design

Status: approved for planning
Date: 2026-08-12
Ticket: Auth hardening — close the `/turns/voice` gap left by `docs/superpowers/specs/2026-08-09-voice-turn-api-design.md`

## Problem

`2026-08-09-voice-turn-api-design.md` shipped `POST /turns/voice` as a deliberate minimal
slice: "Auth, idempotency-key enforcement, and replay cursors are explicitly out of scope
... `Authorization`/`Idempotency-Key`/`X-Schema-Version` headers sent by the client are
accepted but not validated." At the time, none of that infrastructure existed anywhere in
the codebase.

It now does. `require_driver`, `require_schema_version`, `require_idempotency_key`
(`src/api/auth_deps.py`) and the session-ownership + idempotency-store pattern are all
built and proven on `POST /turns/text` (`src/api/turns.py::submit_text_turn`). `/ws/ivi`
and `/ws/engineer` gained bearer/role/Origin validation (commits `4641f8c`, `6e57f3a`,
`36d2874`), and `require_engineer` replaced the `_require_engineer` no-op on
`/traces`/`/metrics/summary`. `/turns/voice` is the one P0 interface still exempt from all
of it: today it accepts audio for **any** `session_id` from **any** caller, bearer token or
not, and offers no idempotency guarantee at all.

`docs/api_spec.md` line 47 documents the full contract this ticket brings the route up to:

```text
POST /api/v1/turns/voice?session_id=ses_01J...
Authorization: Bearer <token>
X-Schema-Version: 1.0
X-Trace-Id: tr_client_voice_001
Idempotency-Key: voice:ses_01J...:002
Content-Type: audio/wav
```

## Scope

In scope: bearer auth (`require_driver`), session ownership, `X-Schema-Version`
enforcement, `Idempotency-Key` enforcement — the same four pieces `/turns/text` already
has, applied to `/turns/voice` by reuse, not by inventing new mechanisms.

Out of scope (unchanged, tracked elsewhere): `/ws/ivi` replay cursors, the STT
`audio/ogg`/`audio/pcm` parsing gap, `approval.intent.detected`, `ui.policy`. None of these
are auth surfaces.

## Architecture

```
POST /api/v1/turns/voice?session_id=...
  [Depends] require_schema_version   → 400 REQUEST_CONTEXT_INVALID
  [Depends] require_driver           → 401 AUTH_REQUIRED / 403 FORBIDDEN
  [Depends] require_idempotency_key  → 400 REQUEST_CONTEXT_INVALID
  validate Content-Type              → 422 INPUT_INVALID          (unchanged)
  session ownership check            → 403 FORBIDDEN              (new)
  get_vehicle/get_graph              → touch session LRU          (unchanged)
  idempotency begin()                → 409 IDEMPOTENCY_CONFLICT, or replay cached 202
  build 202 envelope
  background_tasks.add_task(_process_voice_turn, ...)
  idempotency finish()               → cache the 202 envelope
  return 202
```

This is the same shape `submit_text_turn` already uses, reordered only where the route's
own pre-existing checks (`Content-Type`) must run first, and where the response is built
*before* the real work instead of after it — see Idempotency semantics below.

## Components

### `src/api/turns.py::submit_voice_turn` (edit)

- Route decorator gains `dependencies=[Depends(require_schema_version)]`, matching
  `submit_text_turn`.
- Signature gains `user: AuthenticatedUser = Depends(require_driver)` and
  `idempotency_key: str = Depends(require_idempotency_key)`.
- After the existing `Content-Type` check, add the session-ownership check, copied
  verbatim in spirit from `submit_text_turn`:
  ```python
  session_record = get_session_record(session_id)
  if session_record is None or session_record.user_id != user.user_id:
      raise ApiError(status_code=403, code="FORBIDDEN",
                      message="session không tồn tại hoặc không thuộc về bạn", ...)
  ```
  Same non-enumeration property: "doesn't exist" and "exists but isn't yours" are
  indistinguishable to the caller.
- Idempotency fingerprint: the body is raw bytes, not JSON, so there is nothing to pass
  to the existing `fingerprint_for(body: dict)` directly. Reuse it unchanged by feeding it
  a small dict instead of hashing bytes by hand in `turns.py`:
  ```python
  fingerprint = fingerprint_for({
      "content_type": content_type,
      "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
  })
  ```
  This keeps the one hashing implementation in `idempotency.py` and treats the audio
  payload the same way `fingerprint_for` already treats any other request body: content
  determines the fingerprint, not framing.
- `_VOICE_TURN_ROUTE = "POST /turns/voice"` constant, parallel to the existing
  `_TEXT_TURN_ROUTE`.
- Failure handling around `begin()`/`finish()` mirrors `submit_text_turn` exactly:
  `except BaseException: await store.abandon(...); raise` — `BaseException`, not
  `Exception`, because `asyncio.CancelledError` (client disconnects mid-request) doesn't
  subclass `Exception` and would otherwise leave the reservation stuck for
  `_PENDING_TTL_SECONDS`.

### `src/api/turns.py` module docstring (edit)

Drop the now-false "Phạm vi minimal-slice: không xác thực Authorization/Idempotency-Key/
X-Schema-Version" line; replace with a one-line pointer at what's enforced now and a
reference to this doc, mirroring how other modules in this codebase record a decision once
rather than re-explaining it at each call site.

## Idempotency semantics (the part reviewers will ask about)

**What replay guarantees, precisely.** A retry with the same `(user_id, "POST
/turns/voice", idempotency_key)` and the same fingerprint (content-type + audio hash)
returns the **exact same 202 envelope** — same `turn_id`, same `trace_id` — without
scheduling a second `_process_voice_turn` background task. A retry with the same key but a
different fingerprint gets `409 IDEMPOTENCY_CONFLICT`, same as `/turns/text`.

**What replay does *not* guarantee, and why that's correct here, not a shortcut.**
`/turns/text` calls `store.finish()` *after* `graph.ainvoke()` completes — the cached
record is the actual outcome, so replaying it is replaying a completed result.
`/turns/voice` is async by contract (`docs/api_spec.md`: "A `202 Accepted` only creates the
turn; WebSocket events carry processing and terminal outcomes") — there is no outcome yet
at the point a 202 is returned. So `finish()` necessarily runs *before* the real work
(`_process_voice_turn`, scheduled via `BackgroundTasks`) executes. The idempotency record
therefore certifies only "this exact audio was accepted for processing under this key," not
"this exact audio finished processing." That is a narrower guarantee than `/turns/text`
gets, and it's the correct one: the wire contract already puts all outcome delivery on
`/ws/ivi`, never on the REST response, for this endpoint specifically.

**The failure window, named explicitly.** Ordering inside the route is:
`add_task(...)` (a pure in-memory list append on `BackgroundTasks` — for all practical
purposes cannot fail) is called *before* `finish()`, so the only realistic way to get a
cached "accepted" record with no task ever scheduled is a crash between those two lines,
which is not meaningfully different in likelihood from a crash between any other two
adjacent lines of Python. The window that actually matters is *after* the response is sent
but *before* `_process_voice_turn` runs to completion (STT, then graph). If the process
dies in that window:
- The client already has a `turn_id` for which no WS event will ever arrive.
- **This is not new.** It is the exact same risk every `/turns/voice` call already carries
  today, crash or no crash, idempotency or no idempotency — `docs/api_spec.md` puts the
  entire lifecycle on a best-effort WS push with "no persistence or replay buffer" for
  events that fire while no `/ws/ivi` client is connected (per the 2026-08-09 design's
  Error handling section). This ticket does not change that property.
- What idempotency *does* change: retrying with the **same** `Idempotency-Key` after such a
  crash replays the same dead `turn_id` forever — records have no TTL (only the in-flight
  *reservation* in `begin()`/`_pending` expires, after `_PENDING_TTL_SECONDS`; a *finished*
  record lives until LRU-evicted at `MAX_RECORDS`). A client that wants a fresh attempt
  after suspecting the first one died must mint a **new** `Idempotency-Key`, not resend the
  old one. This matches the documented idempotency contract ("an exact replay by the same
  principal and request fingerprint returns the exact prior HTTP response") — replay is a
  cache of the acceptance, deliberately not a liveness check on the background task — but is
  worth this explicit callout since it's the one place `/turns/voice`'s idempotency
  semantics read differently from `/turns/text`'s.

## Error handling

| Condition | Status | Code |
|---|---|---|
| Missing/invalid bearer | 401 | `AUTH_REQUIRED` |
| Role ≠ driver | 403 | `FORBIDDEN` |
| Missing/wrong `X-Schema-Version` | 400 | `REQUEST_CONTEXT_INVALID` |
| Missing `Idempotency-Key` | 400 | `REQUEST_CONTEXT_INVALID` |
| Bad `Content-Type` | 422 | `INPUT_INVALID` (unchanged) |
| Session doesn't exist / isn't caller's | 403 | `FORBIDDEN` |
| Same key, different fingerprint | 409 | `IDEMPOTENCY_CONFLICT` |
| Same key, same fingerprint | 202 | cached envelope replayed, no new background task |

Dependency-level failures (bearer, schema version, idempotency-key presence) all run before
the route body executes, so none of them create a turn, touch the session, or reserve an
idempotency slot — consistent with `/turns/text`'s existing behavior.

## Testing

Extend `tests/test_api/test_turns_voice.py`, mirroring the equivalent cases already proven
in `tests/test_api/test_turns_text.py`:

- Missing bearer → `401`; wrong role (engineer token) → `403`.
- Missing `X-Schema-Version` → `400`; wrong value → `400`.
- Missing `Idempotency-Key` → `400`.
- `session_id` belonging to another user → `403`, same message/code as the nonexistent-
  session case (assert both produce identical bodies, proving no enumeration).
- Replay: same key + same audio → second response has identical `turn_id`/`trace_id` to the
  first, and only one `turn.accepted` is observed on `/ws/ivi` (proves no second background
  task ran).
- Same key + different audio bytes → `409 IDEMPOTENCY_CONFLICT`.
- Existing tests (202 envelope shape, bad `Content-Type` → 422, STT failure path, happy
  path over `/ws/ivi`) gain the now-required `Authorization`/`X-Schema-Version`/
  `Idempotency-Key` headers and an owned session fixture, matching how
  `test_turns_text.py` already sets up its happy-path cases.

## Out of scope (unchanged from 2026-08-09, still deferred)

- `/ws/ivi` replay cursors, retention window, reconnect replay.
- `approval.intent.detected`, `ui.policy` WS events.
- `audio/ogg`/`audio/pcm` STT parsing (`src/services/voice.py` is WAV-only via stdlib
  `wave`).
- Persisting/queuing turn events when no `/ws/ivi` client is connected — see the Idempotency
  semantics section above for why this ticket does not attempt to close that specific gap
  even though it discusses it.

# Voice Turn API — design

Status: approved for planning
Date: 2026-08-09
Ticket: "Tích hợp Voice Turn API" (Improve Task)

## Problem

Wire `src/services/voice.py` into an HTTP surface: `POST /api/v1/turns/voice` accepts
audio, returns `202 Accepted`, runs STT asynchronously, and reports the voice turn's
lifecycle over `WS /ws/ivi`. Neither the endpoint nor `/ws/ivi` exist yet — only the
dev-only `POST /api/v1/agent/process` (text-only, synchronous, `include_in_schema=False`)
and `/ws/engineer` exist today.

## Scope

`docs/api_spec.md` documents a much larger contract for these two endpoints than this
ticket's three acceptance criteria require: bearer auth, `X-Schema-Version`,
`Idempotency-Key` handling, replay cursors, RBAC. None of that infrastructure exists
anywhere in the codebase yet — even `/ws/engineer` explicitly defers auth behind an
unbuilt `AUTH_ENABLED` flag (see `src/api/ws.py` docstring).

**This ticket builds a minimal slice**: the endpoint, async STT, and the turn lifecycle
over `/ws/ivi`. Auth, idempotency-key enforcement, and replay cursors are explicitly
**out of scope** and left to follow-up tickets. `Authorization`/`Idempotency-Key`/
`X-Schema-Version` headers sent by the client are accepted but not validated.

Despite deferring *enforcement*, the wire **shape** (response envelope, event `type`s,
event payload field names, WS subprotocol handshake) follows `docs/api_spec.md`
precisely, because `frontend/src/lib/services/turn/real.ts` is already built end-to-end
against that exact contract. Matching it is an interop requirement, not scope creep.

After STT produces a transcript, the turn continues into full agent processing — the
transcript is run through the same per-session LangGraph (`src/api/session_state.py`)
that `src/api/agent_routes.py`'s dev endpoint already uses — rather than stopping at
transcription. This reuses existing routing/RAG/execution/HITL logic and is what the
ticket's "connect voice.py to the voice turn flow" deliverable means in practice.

An S2 (HITL) voice turn is also wired through to completion: `src/api/approvals.py`'s
existing `POST /api/v1/approvals/{id}/decision` resumes the graph today but publishes
nothing to `/ws/ivi`. This ticket extends it to publish the resume outcome too, so an
S2 voice turn reaches a terminal WS event instead of appearing to hang forever.

## Architecture

```
POST /api/v1/turns/voice?session_id=...
  → validate Content-Type, generate turn_id/trace_id, return 202 immediately
  → BackgroundTasks schedules _process_voice_turn()

_process_voice_turn() (runs after the response is sent):
  publish turn.accepted → assistant.status(transcribing)
  → asyncio.to_thread(voice.transcribe, audio_bytes)   # off the event loop
  → publish transcript.final (or unusable + error + turn.failed; turn ends here)
  → publish assistant.status(routing)
  → graph.ainvoke(...)   # same session graph agent_routes.py already uses
  → emit_turn_lifecycle(result)  # ordered WS events through to a terminal event,
                                   # or assistant.status(waiting_approval) for S2

IviEventBus (new, in-memory pub/sub keyed by session_id)
  ↑ publish()                              ↓ deliver
turns.py, approvals.py  ────────────►  /ws/ivi connections (src/api/ws.py)
```

`/ws/ivi` is a new handler alongside the existing `/ws/engineer` in `src/api/ws.py`,
reusing its `EventStream` sequencing pattern (generalized to also carry `session_id`
and `turn_id`, which Driver events require and Engineer events don't).

## Components

### `src/services/ivi_events.py` (new)

- `IviEventBus`: `add_listener(session_id, callback)`, `remove_listener(session_id, callback)`,
  `publish(session_id, event_type, turn_id, trace_id, payload)`. Mirrors the listener
  pattern `MqttRuntime.cache` already uses for the engineer stream. Module-level
  singleton (`_BUS` / `get_event_bus()`), same convention as `_STORE`/`get_store()` in
  `src/api/session_state.py`.
- `emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result)`: reads a LangGraph
  result dict — the same shape `agent_routes.py` and `approvals.py` already consume
  (`outcome`, `response_text`, `step_results`, `action_plan`/`candidate_action_plan`,
  `citations`, `__interrupt__`) — and emits the matching ordered event sequence per the
  state-machine table in `api_spec.md`:
  - Interrupted (S2 pending): `approval.required` (from the interrupt payload —
    `approval_id`, `plan_id`, `approved_vehicle_state_version`, `expires_at`,
    `actions` built from `steps_summary`) then `assistant.status(waiting_approval)`.
    Nonterminal — the task ends here.
  - Control path with execution: `assistant.status(executing)` → one `tool.result` per
    `step_results` entry → `assistant.response` → `turn.completed` (or `turn.failed` if
    any step didn't complete, per the fail-fast rule: the first non-`completed` result is
    terminal, remaining not-started steps are already marked `skipped` by `execute_node`).
  - Manual/RAG/offer/clarify/denied/not_control (no execution): `assistant.status(retrieving)`
    → `assistant.status(composing)` → `assistant.response` → `turn.completed`. (`retrieving`
    is only emitted when the RAG node actually ran; other no-tool outcomes go straight to
    `composing`.)
  - S3 blocked: `action.blocked` → `assistant.response` → `turn.completed`.
  - Approval fail-closed (một trong sáu outcome mà `request_approval_node` trả về sau khi
    resume: `approval_rejected`, `approval_expired`, `approval_invalidated_state`,
    `approval_invalidated_plan`, `approval_predicate_failed`, `approval_not_owned`):
    `assistant.response` → `turn.canceled` với `reason` tương ứng trong enum
    `TurnCancelReason` của `api_spec.md`. Không outcome nào trong nhóm này được báo
    `turn.completed` — chúng đều là "không có hiệu ứng phụ nào xảy ra".
    `approval_not_owned` không có `reason` riêng trong enum đã publish nên dùng
    `approval_invalidated_state` (sai session/turn là một dạng thất bại kiểm tra state).
  - `displayText`/`speakText` in `assistant.response` both map to the existing single
    `response_text` field — there's no separate speak-text field yet. Same category of
    gap the frontend already carries for `lights`/`trunk` (documented there as a GAP
    comment); worth a similar note here rather than inventing a field.

### `src/api/turns.py` (new)

- `POST /turns/voice` — query param `session_id` (required). Reads the raw body
  (`await request.body()`). Validates `Content-Type` is one of `audio/wav`, `audio/ogg`,
  or `audio/pcm;rate=16000;channels=1;format=s16le`. So sánh theo **base media type**
  (`content_type.split(";")[0].strip().lower()`) vì blob của `MediaRecorder` mang parameter
  (`audio/webm;codecs=opus`, `audio/wav; codecs=1`) và khớp chuỗi nguyên thì không blob
  thật nào qua được. `audio/pcm` là ngoại lệ có chủ ý: rate/channels/format nằm trong
  parameter và **chính chúng** mang nghĩa, nên phải đủ cả ba (thứ tự tuỳ ý) mới nhận —
  `audio/pcm;rate=8000` bị từ chối. Sai thì `422 INPUT_INVALID` (matching the
  existing error envelope shape used by `GET /vehicle/state`) if not, before any turn is
  created. Otherwise generates `turn_id` (`turn_voice_<hex>`), `trace_id`, `request_id`;
  registers the session/vehicle/graph via `session_state.get_vehicle`/`get_graph` (same
  as `agent_routes.py`); schedules `_process_voice_turn` via FastAPI `BackgroundTasks`;
  returns `202` with the documented envelope:
  ```json
  {
    "data": {"session_id": "...", "turn_id": "...", "status": "accepted", "input_mode": "voice"},
    "meta": {"request_id": "...", "realtime": "WS /ws/ivi"},
    "trace_id": "...",
    "schema_version": "1.0"
  }
  ```
- `_process_voice_turn(bus, session_id, turn_id, trace_id, audio_bytes)` — see Architecture
  above. Wrapped in try/except so any unexpected exception still emits `error` +
  `turn.failed` — no turn is ever left without a terminal event.
- Engine STT được lấy **tách riêng** (`await asyncio.to_thread(voice.get_stt_engine)`) trước
  và ngoài khối `except ValueError` bọc `voice.transcribe`. `get_stt_engine()` cũng raise
  `ValueError` (khi `STT_PROVIDER` cấu hình sai) nhưng đó là lỗi máy chủ, không phải audio
  tài xế gửi; gộp chung thì hệ thống báo "audio không dùng được" và đổ lỗi oan cho micro.
  Chỉ `ValueError` của `_validate_audio` (sai sample rate/kênh, WAV hỏng, quá dài) mới thành
  `STT_FAILED` / `transcript.final(unusable)`; lỗi cấu hình/engine nổi lên `INTERNAL_ERROR`.
- `graph.ainvoke(...)` chạy trong `async with session_state.get_session_lock(session_id)`.
  Endpoint là fire-and-forget nên client có thể gửi lượt thứ hai khi lượt đầu còn đang chờ
  approval S2; hai `ainvoke` song song trên cùng thread checkpointer sẽ bỏ rơi interrupt
  đang chờ và lượt đó không bao giờ tới terminal event. Khoá chỉ bọc quanh `ainvoke` — STT
  của các lượt khác vẫn chạy song song. `src/api/approvals.py` dùng **cùng** khoá đó cho
  `ainvoke(Command(resume=...))`, vì cũng chung một thread.

### `src/api/ws.py` (edit)

- New `@router.websocket("/ws/ivi")` handler. Accepts the connection, selecting the
  `vivi.v1` subprotocol if the client offered it (matches `real.ts`'s
  `new WebSocket(url, ["vivi.v1", "bearer.<token>"])`), without validating the bearer
  value (auth deferred). Requires the first client message to be `connection.init` with
  a `session_id` present — same invalid-handshake handling already used for
  `/ws/engineer` (`WS_EVENT_INVALID`, close 1003). Subscribes to `IviEventBus` for that
  `session_id`; on each published event, wraps it via a per-connection `EventStream`
  (sequence/event_id/emitted_at/schema_version) and sends it. Unsubscribes on disconnect.
- `EventStream.wrap()` gains optional `session_id`/`turn_id`/`trace_id` parameters
  (falling back to the connection-level `trace_id` when omitted) so both `/ws/engineer`
  and `/ws/ivi` share the one class.

### `src/api/approvals.py` (edit)

- After `graph.ainvoke(Command(resume=...))` in `decide()`, also call
  `emit_turn_lifecycle(get_event_bus(), record.session_id, record.turn_id, <fresh trace_id>, result)`.
  The existing REST response body is unchanged. A fresh `trace_id` is generated for
  these events rather than persisting the original turn's trace_id (would require adding
  a field to `ApprovalRecord`/graph state) — an acceptable simplification since
  `trace_id` scopes a request context, not a turn identity.

### `src/main.py` (edit)

- `app.include_router(turns_router, prefix="/api/v1")`.

## Error handling

- Bad `Content-Type` at accept time → synchronous `422 INPUT_INVALID`, no turn created,
  nothing published.
- Bad WAV content (wrong sample rate/channels/corrupt/silence) → discovered inside
  `voice.transcribe()`, surfaces as `transcript.final(text="", transcription_status="unusable")`
  → `error(code="STT_FAILED", terminal=true)` → `turn.failed`. The graph is never invoked
  — matches the spec's explicit "the agent never receives the empty transcript" rule.
- Any unexpected exception during graph processing is caught, logged, and always
  produces `error` + `turn.failed`.
- If no `/ws/ivi` client is connected when a turn's events publish, they are dropped —
  no persistence or replay buffer in this slice. This is a known limitation (not a
  blocker): the expected IVI flow connects the WS before submitting a turn.

## Testing

- New `tests/test_api/test_turns_voice.py`: `202` envelope shape, bad `Content-Type` →
  `422`, STT failure path (mocked `voice.transcribe` raising), full control-command
  happy path observed via `TestClient.websocket_connect("/ws/ivi")`.
- New/extended WS test covering the `connection.init` handshake (missing `session_id`,
  wrong first message type) against the same pattern already used for `/ws/engineer`.
- Extend `tests/test_api/test_approval_routes.py` to assert the S2 approve/reject path
  now also publishes the expected follow-up events on `/ws/ivi`.

## Out of scope (explicitly deferred)

- Auth (bearer token validation, RBAC, origin checks), `X-Schema-Version` enforcement,
  `Idempotency-Key` conflict handling.
- WS replay cursors (`last_event_id`/`last_sequence`), retention window, reconnect replay.
- `approval.intent.detected` voice-confirmation handoff.
- `ui.policy` events, `GET /api/v1/traces/{trace_id}`.
- Persisting/queuing turn events when no `/ws/ivi` client is connected.
- **`plan.ready`**. `docs/api_spec.md` đặt sự kiện này trên đường control (giữa
  `assistant.status(routing)` và execution/response) và `real.ts` đã có case cho nó, nhưng
  slice này không phát. Không tiêu chí nghiệm thu nào trong ba tiêu chí của ticket cần tới
  nó, và frontend bỏ qua êm những `type` không nhận ra (default case của `mapServerEvent`
  trong `frontend/src/lib/services/turn/real.ts`), nên thiếu nó không làm vỡ interop. Thêm
  vào là việc của ticket sau.
- Content-Type `audio/ogg` và `audio/pcm` được nhận ở cổng 422 theo hợp đồng, nhưng
  `src/services/voice.py` hiện parse bằng stdlib `wave` (chỉ WAV), nên lượt gửi bằng hai
  loại đó luôn kết thúc ở `transcript.final(unusable)` + `turn.failed`. Đây là giới hạn
  **sẵn có** của tầng STT, không phải thứ slice này sửa hay thu hẹp khỏi hợp đồng.

**Không** còn nằm trong "out of scope": các outcome fail-closed của approval từng rơi vào
nhánh mặc định `turn.completed`; giờ chúng phát `turn.canceled` kèm `reason` (xem
`emit_turn_lifecycle` ở trên).

# API and Realtime Specification

This document defines the public P0 contract. Safety and admission authority is [Safety and Human-in-the-Loop Specification](safety_and_hitl.md); canonical entities are [Data Model and Messaging Specification](data_model.md); architectural scope is [ADR-006](adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md).

## Conventions and common HTTP envelopes

- REST base path is `/api/v1`; `/healthz` is deliberately outside it. JSON is UTF-8 and uses `snake_case`; timestamps are UTC ISO 8601 strings.
- Local demo authentication uses `Authorization: Bearer <access_token>`. The server enforces RBAC. A Driver may use only their current/owned session, approval, citation, and safe trace. A P0 Engineer may read authorized vehicle state, safe structured traces, documented aggregates, readiness, and redacted fault summaries only. Full trace/eval/model/config capabilities are authorized/audited CLI/P1. UI visibility is not authorization.
- Every HTTP response contains `trace_id` and `schema_version`. `X-Trace-Id` is only a client correlation request; the server validates it or generates a trace ID when absent.
- Vehicle state is server-authoritative. Planning and approval versions are derived from a server snapshot. A client never authoritatively supplies a planning vehicle version.
- Responses, traces, and events never expose raw audio, raw prompts, hidden chain-of-thought, credentials, or stack traces.

Success envelope:

```json
{
  "data": {"status": "example"},
  "meta": {"request_id": "req_01J..."},
  "trace_id": "tr_01J...",
  "schema_version": "1.0"
}
```

Error envelope:

```json
{
  "error": {
    "code": "APPROVAL_INVALIDATED_STATE",
    "message": "Vehicle state changed; create and confirm a new plan.",
    "retryable": false,
    "details": {"approved_vehicle_state_version": 41, "actual_vehicle_state_version": 42}
  },
  "meta": {"request_id": "req_01J..."},
  "trace_id": "tr_01J...",
  "schema_version": "1.0"
}
```

### Required POST context

| POST route | Authentication | Version declaration | `Idempotency-Key` | Session and vehicle-version context |
|---|---|---|---|---|
| `/api/v1/auth/login` | None | Login exception: declare `version=1.0` in JSON media type, or send `X-Schema-Version: 1.0` | Not accepted/required | No session exists. |
| `/api/v1/sessions` | Bearer Driver | `X-Schema-Version: 1.0` required | Required | Session-create exception: no `session_id`; `vehicle_id` is JSON input. |
| `/api/v1/turns/text` | Bearer Driver/owner | `X-Schema-Version: 1.0` required | Required | `session_id` required in JSON. Planning version is server-derived. |
| `/api/v1/turns/voice` | Bearer Driver/owner | `X-Schema-Version: 1.0` required | Required | `session_id` required in query because body is audio. Planning version is server-derived. |
| `/api/v1/approvals/{approval_id}/decision` | Bearer Driver/owner | `X-Schema-Version: 1.0` required | Required | Server derives session/plan and stored `plan_digest` from `approval_id`; client may only echo `approved_vehicle_state_version`. |

`X-Trace-Id` is optional on every POST; examples show it for implementability. The response always contains the accepted/generated `trace_id`. For each required idempotency key, an exact replay by the same principal and request fingerprint returns the exact prior HTTP response. Reusing the key with a different fingerprint returns `IDEMPOTENCY_CONFLICT`.

## P0 public surface — exactly 14 interfaces

| # | Interface | Role | Purpose |
|---:|---|---|---|
| 1 | `POST /api/v1/auth/login` | Local public | Obtain a demo bearer token. |
| 2 | `POST /api/v1/sessions` | Driver | Start a session. |
| 3 | `POST /api/v1/turns/text` | Driver, owner | Submit a text turn. |
| 4 | `POST /api/v1/turns/voice` | Driver, owner | Upload one audio turn; asynchronous `202`. |
| 5 | `POST /api/v1/approvals/{approval_id}/decision` | Driver, approval owner | Commit approve or reject for an immutable pending approval. |
| 6 | `GET /api/v1/vehicle/state` | Driver/Engineer as scoped | Read authoritative simulator state. |
| 7 | `GET /api/v1/citations/{citation_id}` | Driver for own turn; Engineer as scoped | Resolve a citation. |
| 8 | `GET /api/v1/traces/{trace_id}` | Driver for own turn; Engineer as scoped | Read a redacted operational trace/status. |
| 9 | `GET /api/v1/metrics/summary` | Engineer | Read aggregate service metrics. |
| 10 | `GET /healthz` | Local probe/Engineer | Read full demo dependency readiness; process liveness is internal. |
| 11 | `WS /ws/ivi` | Driver, owner | Receive Driver session/turn events. |
| 12 | `WS /ws/engineer` | Engineer | Receive state, trace, metric, and health events. |
| 13 | `GET/PUT /api/v1/vehicle/profile` | Read: any authenticated role; Write: Engineer | Read/replace the static vehicle configuration (`trim`, `battery`) that the tyre-pressure answer keys on. |
| 14 | `GET/PUT /api/v1/vehicle/profile/options` | Read: any authenticated role; Write: Engineer | Read/replace the set of declared **optional equipment** (65-entry catalogue) that manual answers key on. |
| 15 | `GET /api/v1/metrics/eval-snapshot` | Engineer | Read the metrics and provenance of the **latest evaluation run** of one suite. Read-only; never runs an evaluation. |

Route parameter names are explicit: citation uses `{citation_id}`, approval uses `{approval_id}`, and trace uses `{trace_id}`. There is no general-purpose public agent-processing route.

**Two routes exist outside this table on purpose, and neither raises the count.** `POST /api/v1/agent/process` is the dev-only agent harness (`include_in_schema=False`, 404 in production). `POST /api/v1/sim/motion` is the **demo-scenario harness** added by [ADR-024](adr/ADR-024-kenh-harness-dieu-khien-xe-ao.md): it sets the *simulated* car's speed and gear so the S3 acceptance scenario can be staged from a browser instead of from the simulator's stdin. It is `include_in_schema=False`, returns **404** — not 403 — when `SIM_CONTROL_ENABLED` is false, and it does not write vehicle state: it publishes to `v1/sim/{id}/motion/set` and the simulator sets its own motion, so ADR-013's single state source is untouched. Do not build a client against either route.

Interface 13 was added on 2026-08-15 for issue #123 and is the one deliberate widening of this surface; the count above is the count to enforce, not 12. Three things make it a P0 interface rather than the P1 management endpoint it superficially resembles. First, the tyre-pressure answer needs the configuration **at request time**: the manual gives four different pressures across `trim` × `battery`, so without it the only honest answer is a source pointer. Second, the P0 alternative below — `.env` plus a controlled restart — costs the MQTT state cache and every live session, which is not an acceptable way to switch between an ECO and a PLUS car mid-demo. Third, vehicle configuration is not one of the three P1 families named below, and it is not *state*: it does not change while the car drives, carries no `state_version`, and never travels over MQTT, so per ADR-013 it must stay out of `GET /api/v1/vehicle/state` rather than being added to the simulator snapshot.

Interface 14 was added on 2026-08-19 and is a **sub-resource, not a field on interface 13** — the two have different lifecycles and different write semantics. The survey behind it is `docs/khao_sat_trang_bi.md`: 116 of 482 manual chunks carry an equipment conditional (`"nếu được trang bị"`, `"(nếu có)"`), 147 mentions in total, and today the composer quotes them verbatim so the driver hears the conditional and has to guess. Three of those cases are harmful rather than merely verbose — the rear emergency door release, the spare wheel, and any active-safety claim.

Why a sub-resource and not a field: `VehicleProfileUpdate` sets `extra="forbid"` and **requires both fields to be present**, so adding `options` either breaks every existing client with a 422 or forces that invariant to be relaxed. Splitting also says the right thing — `trim`/`battery` is a pair declared once, equipment is a large set declared incrementally that is never "complete".

`da_khai` carries only the options that have been declared. **An absent key means "unknown", not "not fitted"**, and unknown is the default state of every option on every car — the storage layer models it as an absent row, so no default value has to be chosen. Clients must not read a missing key as `false`; the composer only acts on an explicit `false`. `PUT` replaces the whole set for the same reason interface 13 replaces the whole pair: a leftover `lop_du_phong: true` from the previous car must not survive onto the next one. The response embeds the full catalogue (`id`, `ten`, `nhom`, `loai_tru`) so no client has to keep a copy of `src/safety/trang_bi.json`; a second copy in the frontend is a second source of truth, and it drifts the moment an option is added. Mutually exclusive pairs (spare wheel ↔ inflation kit, powered ↔ manual steering column) are rejected with 422 when both are declared `true`.

Interface 15 was added on 2026-08-28 and is the **third** deliberate widening. It exists because the engineer dashboard's "offline evaluation" tiles were showing hard-coded numbers (`isMock: true`, dated 2026-08-07) and a browser cannot read `eval/results/` off the filesystem. Three properties keep it inside P0 rather than making it a management endpoint. First, it is **strictly read-only over immutable artifacts**: it returns the `metrics.json` and `manifest.json` of the newest run directory of one suite and never creates, mutates, or triggers anything — a request must not be able to produce evidence, because grading is a deliberate act with someone accountable for it. Second, `suite` is typed as a `Literal` whitelist (`rag`, `agent-intent`) rather than a free string, since the value reaches a filesystem path; anything else is rejected 422 `INPUT_INVALID` before the handler runs. Third, it deliberately does **not** fold into `GET /metrics/summary`: that endpoint aggregates traffic that just happened on this machine, while this one replays a packaged measurement taken against a dataset with pre-committed answer keys. The two kinds of number must not be summed, and keeping them in separate envelopes is what stops a client from doing so.

`metrics` is an open `dict` rather than a declared shape, because each suite has its own metric set and frozen older runs have older ones; pinning the fields here would break reading a run the moment a new measurement is added to `src/rag/evaluate.py`. `graded_by` reports which grader produced the numbers — `dap_an_khoa`, `nguoi_cham_tay`, or `judge` — and is `null` for runs written before `manifest.json` existed. Clients must render `null` as unknown and must never merge numbers from different graders into one figure.

There is deliberately **no `is_complete` on interface 14**. `is_complete` on interface 13 is the gate of the tyre-pressure branch and only that branch — "is this enough to look up the four-cell table". No equivalent question exists for equipment, because no "complete" set exists.

`trim` and `battery` are nullable, and `null` **means** "not declared yet" rather than "use a default" — there is no default at any layer. The derived `is_complete` is the fail-closed gate: the backend, not the client, decides whether a configuration-dependent answer may be given at all. `PUT` replaces both fields together, because a half-declared car (new `trim`, previous car's `battery`) still passes `is_complete` and would resolve to the pressures of a vehicle that does not exist.

## Core POST contracts

### Login

```text
POST /api/v1/auth/login
Content-Type: application/json; charset=utf-8; version=1.0
X-Trace-Id: tr_client_login_001

{"email":"driver.demo@example.com","password":"DemoDriver123!"}
```

```json
{
  "data": {
    "access_token": "eyJ...demo...",
    "token_type": "Bearer",
    "expires_at": "2026-07-31T10:30:00Z",
    "user": {"user_id": "usr_driver_01", "role": "driver", "display_name": "Demo Driver"}
  },
  "meta": {"request_id": "req_login_001"},
  "trace_id": "tr_client_login_001",
  "schema_version": "1.0"
}
```

### Create session

```text
POST /api/v1/sessions
Authorization: Bearer <token>
X-Schema-Version: 1.0
X-Trace-Id: tr_client_session_001
Idempotency-Key: session:vehicle-demo-01:001
Content-Type: application/json; charset=utf-8

{"vehicle_id":"vehicle-demo-01","input_mode":"voice"}
```

```json
{
  "data": {
    "session_id": "ses_01J...",
    "vehicle_id": "vehicle-demo-01",
    "status": "active",
    "started_at": "2026-07-31T10:00:00Z",
    "can_drive": true,
    "pool": null
  },
  "meta": {"request_id": "req_session_001"},
  "trace_id": "tr_client_session_001",
  "schema_version": "1.0"
}
```

`can_drive` and `pool` were added on 2026-08-23 with the vehicle pool. Both are additive:
a client that ignores them behaves exactly as before, because `can_drive` defaults to
`true` and `pool` is `null` whenever the pool is not allocating.

- **`vehicle_id` in the request body is a hint, not a choice.** The server assigns the
  vehicle. It is echoed back so the client knows which car it got.
- **`can_drive: false` means read-only.** The session exists and can still look things up
  in the manual and read vehicle state; control commands are refused with
  `vehicle_pool_exhausted`. A session is not a car, so exhausting the pool does not fail
  session creation.
- **Do not infer `can_drive` from `vehicle_id`.** `sessions.vehicle_id` is `NOT NULL` in
  SQLite, so a read-only session still carries a value there. `can_drive` is the only
  field that answers the question.
- **`pool` is `null` when `vehicle_pool_size == 1`** — there is no cap to report, and
  saying `in_use: 0` while somebody is driving would be a wrong number. When the pool
  allocates, `free` is derived server-side so no client has to subtract (or subtract
  wrongly).

### Text turn and canonical ActionPlan

```text
POST /api/v1/turns/text
Authorization: Bearer <token>
X-Schema-Version: 1.0
X-Trace-Id: tr_client_text_001
Idempotency-Key: turn:ses_01J...:001
Content-Type: application/json; charset=utf-8

{"session_id":"ses_01J...","text":"Bật điều hòa 24 độ."}
```

Route này **đồng bộ**: mọi sự kiện `/ws/ivi` của lượt — kể cả `assistant.response` — được
phát **trước** khi envelope HTTP trả về. Nên `turn_id` trong envelope tới **sau** mọi sự
kiện của chính lượt đó, và một client muốn lọc sự kiện theo lượt không thể lấy mỏ neo từ
phản hồi HTTP. Vì thế route phát `turn.accepted` (`input_mode: "text"`) ngay khi nhận
request, trước khi chạy graph — đối xứng với `/turns/voice`. Trước 2026-08-27 chỉ đường
giọng nói phát sự kiện này, dù enum `input_mode` trong allowlist đã có `"text"` từ đầu;
đó là một chỗ khuyết của hiện thực, không phải một quyết định thiết kế (xem PR #307).

```json
{
  "data": {
    "session_id": "ses_01J...",
    "turn_id": "turn_01J...",
    "status": "completed",
    "action_plan": {
      "schema_version": "1.0",
      "plan_id": "plan_01J...",
      "session_id": "ses_01J...",
      "vehicle_id": "vehicle-demo-01",
      "vehicle_state_version": 41,
      "steps": [
        {
          "step_id": "step_01J...",
          "ordinal": 1,
          "tool": "set_hvac_temperature",
          "args": {"temperature_c": 24},
          "safety_level": "S1",
          "depends_on": []
        }
      ],
      "requires_approval": false
    },
    "response": {
      "display_text": "Đã đặt điều hòa 24 độ.",
      "speak_text": "Đã đặt điều hòa 24 độ.",
      "citations": [],
      "outcomes": [{"step_id": "step_01J...", "status": "completed"}]
    },
    "routine_preview": null,
    "routine_setup_required": null
  },
  "meta": {"request_id": "req_text_001"},
  "trace_id": "tr_client_text_001",
  "schema_version": "1.0"
}
```

The nested `action_plan` contains exactly the required canonical fields from [data_model.md](data_model.md): `schema_version`, `plan_id`, `session_id`, `vehicle_id`, `vehicle_state_version`, `steps`, and `requires_approval`; each step has exactly `step_id`, `ordinal`, `tool`, `args`, `safety_level`, and `depends_on`. `turn_id` is turn/agent state outside `ActionPlan`.

`routine_preview` chỉ khác `null` khi outcome là xem trước Routine. Hình dạng đóng là
`{routine_id:string, routine_name:string, steps:[{index:int>=0, action:string, description:string}]}`.
Nó mô tả đúng Routine backend vừa phân giải và **không** phải tín hiệu thực thi: preview không tạo
`routine_execution`, không gọi executor, và vẫn cần một lượt xác nhận riêng trước khi chạy.

`routine_setup_required` (issue #385) chỉ khác `null` khi voice-run bị chặn vì thiếu địa điểm bắt
buộc — tức mã lỗi Routine là `chua_dat_dia_diem`. Ba mã lỗi từ chối còn lại (`routine_da_tat`,
`dang_chay_routine_khac`, `routine_khong_ton_tai`) không có màn setup nào để đưa tài xế sang, nên
trường này vẫn `null` với chúng — client dựa vào câu ở `response.speak_text`/`display_text` để biết
lý do. Hình dạng đóng là `{routine_id:string, ma_loi:string, thieu:[string]}`, trong đó `thieu` là
tập nhãn máy đọc được (`"home"` và/hoặc `"office"`) — dùng để mở đúng hàng trong màn thiết lập địa
điểm, không phải để so khớp một câu tiếng Việt (câu đó ở `routine_ly_do`/`speak_text` và có thể đổi
bất cứ lúc nào khi làn BE viết lại lời từ chối).

### Voice turn: asynchronous acceptance

The body is binary audio, not JSON. P0 accepts `audio/wav`, `audio/ogg`, or `audio/pcm;rate=16000;channels=1;format=s16le`, with a matching `Content-Type` and maximum duration 30 seconds. A `202 Accepted` only creates the turn; WebSocket events carry processing and terminal outcomes.

```text
POST /api/v1/turns/voice?session_id=ses_01J...
Authorization: Bearer <token>
X-Schema-Version: 1.0
X-Trace-Id: tr_client_voice_001
Idempotency-Key: voice:ses_01J...:002
Content-Type: audio/wav

<binary WAV bytes>
```

```json
{
  "data": {
    "session_id": "ses_01J...",
    "turn_id": "turn_voice_01J...",
    "status": "accepted",
    "input_mode": "voice"
  },
  "meta": {"request_id": "req_voice_001", "realtime": "WS /ws/ivi"},
  "trace_id": "tr_client_voice_001",
  "schema_version": "1.0"
}
```

### Approval decision: synchronous atomic admission

After full validation and deterministic policy, an S2 outcome is created by one DB transaction that inserts the immutable `ActionPlan` and bound pending `ApprovalRequest` together. The one-pending/session partial unique check runs inside the same transaction. On conflict it rolls back both inserts and returns deterministic `APPROVAL_ALREADY_PENDING` clarification with no plan, approval, group, tool result, or side effect. An S1-only plan follows its unchanged direct no-approval persistence/admission path.

The external user-decision contract is REST-only. For `approve`, the domain service synchronously checks immutable user/session/plan binding, expiry and single use; re-canonicalizes/re-hashes the stored plan and compares its `plan_digest`; re-reads authoritative state; validates state-version equality and every predicate; then atomically consumes the approval and creates `execution_group_id` immediately before the first side effect. `plan_digest` is a server-side binding and is never client-authoritative. Execution continues asynchronously and is reported on `/ws/ivi`.

REST is the sole user-decision writer, but a deadline worker is an allowed system transition authority: at or after `expires_at`, it atomically compare-and-sets `pending→expired`, emits the original turn's `assistant.response` and exactly one `turn.canceled(reason="approval_expired")`, and creates no consume/group/MQTT. If REST and expiry race, their DB transactions serialize; exactly one CAS wins and the loser reads/returns the already terminal approval state without a second terminal event or side effect.

```text
POST /api/v1/approvals/appr_01J.../decision
Authorization: Bearer <token>
X-Schema-Version: 1.0
X-Trace-Id: tr_client_approval_001
Idempotency-Key: approval:appr_01J...:decision-001
Content-Type: application/json; charset=utf-8

{"decision":"approve","approved_vehicle_state_version":41}
```

```json
{
  "data": {
    "approval_id": "appr_01J...",
    "decision": "approve",
    "status": "admitted",
    "approval_status": "consumed",
    "execution_group_id": "grp_01J...",
    "approved_vehicle_state_version": 41,
    "admitted_at": "2026-07-31T10:00:12Z"
  },
  "meta": {"request_id": "req_approval_001"},
  "trace_id": "tr_client_approval_001",
  "schema_version": "1.0"
}
```

If canonical digest differs, actual state is stale, or a predicate no longer holds, the service returns `409 APPROVAL_INVALIDATED_PLAN`, `409 APPROVAL_INVALIDATED_STATE`, or `409 APPROVAL_PREDICATE_FAILED` using the common error envelope. Expired approval returns `409 APPROVAL_EXPIRED`; none of these paths consumes the approval, creates a group, or publishes MQTT. Each also emits a user-safe `assistant.response` followed by exactly one `turn.canceled` on the original command turn with matching lowercase reason. An exact replay with the same `Idempotency-Key` returns the exact prior response and does not consume again. A new key against a consumed approval returns `409 APPROVAL_REPLAYED`.

```text
POST /api/v1/approvals/appr_01J.../decision
Authorization: Bearer <token>
X-Schema-Version: 1.0
X-Trace-Id: tr_client_approval_002
Idempotency-Key: approval:appr_01J...:decision-002
Content-Type: application/json; charset=utf-8

{"decision":"reject"}
```

```json
{
  "data": {
    "approval_id": "appr_01J...",
    "decision": "reject",
    "approval_status": "rejected",
    "plan_status": "canceled",
    "execution_group_id": null,
    "approved_vehicle_state_version": 41,
    "admitted_at": null
  },
  "meta": {"request_id": "req_approval_002"},
  "trace_id": "tr_client_approval_002",
  "schema_version": "1.0"
}
```

A successful reject response is followed on `/ws/ivi` by a user-safe `assistant.response` and exactly one `turn.canceled(reason="approval_rejected")` for the original command turn; stable audit/event code is `APPROVAL_REJECTED`. It creates no execution group or MQTT publish.

A voice-first confirmation is submitted as a distinct new voice turn. STT and deterministic intent resolution may emit `approval.intent.detected` with explicit `approval_id`, `original_turn_id`, `decision`, `approved_vehicle_state_version`, and `committed`; that server event informs the IVI regardless of who commits. **Changed for issue #191**, and the change is asymmetric on purpose:

- An **explicit** confirmation phrase (`đồng ý`, `xác nhận`, `chấp nhận`, `duyệt`) commits the approval server-side.
- **Any** rejection phrase commits the rejection, including bare `không` / `thôi`.
- A **bare** affirmative (`ừ`, `vâng`, `được`) does **not** commit; it stays a handoff and the IVI highlights the button, exactly as before. The spoken reply on this branch names the phrase to say instead of promising execution — *"Bạn nói 'đồng ý' hoặc chạm nút xác nhận giúp tôi."*, never *"Tôi sẽ thực hiện ngay."*

**`committed` is the only discriminator between those branches** (issue #207): the other four fields are identical whether or not the turn committed, so an IVI without it must guess, and the cheapest guess — always call REST — routes straight around the asymmetry above. `committed` reflects the **store outcome**, not which code branch ran: it is true only when the record actually moved to `approved`/`consumed`/`rejected`. If the approval expires in the window between the pending read and the commit, the turn emits the no-pending branch instead of a handoff, so no event ever claims a commit that did not happen.

The earlier rule — *the backend does not silently invoke the decision service* — was written when a tap was the only answer channel. The HITL gate requires **a deliberate human confirmation**, not *a tap*; a distinct spoken phrase is one. The residual risk is ASR error, and that is what the asymmetry above bounds: mishearing a rejection costs nothing (rejection is already the default on expiry), while mishearing an acceptance actuates an S2 command. There is still no WebSocket decision client message, and the voice path commits through the **same** server-side routine as the REST route (`chot_da_xac_thuc`), so single-use, plan-binding, `state_version` and one-pending-per-session are enforced in one place for both doors. Voice confirmation must not be marked **Chạy được trên PC** until a WER run over the closed confirmation-phrase set exists under `eval/results/`. After handoff, that intent turn emits `assistant.response` and exactly one `turn.completed`. Ambiguous intent emits a best-effort `assistant.speech` followed by a terminal error plus exactly one `turn.failed` — the speech carries the same *say it again* sentence the error already puts on screen, because since #211 the mic **reopens by itself** on this branch and a silent open mic tells a driver nothing (#212); it precedes the error because the client decides whether to wait for `ended` at the moment the error arrives, and it is dropped silently when TTS fails, since losing the voice costs a convenience while losing `turn.failed` strands the turn; no pending approval emits exactly one `turn.canceled(reason="approval_not_pending")`. The original command turn remains pending until REST approve execution, reject, expiry, state invalidation, plan/digest invalidation, or predicate failure gives it exactly one terminal event.

## GET response schemas

### Authoritative vehicle state

`GET /api/v1/vehicle/state` **requires an authenticated caller** (any role — the
engineer console reads vehicle state as a matter of course) and accepts an optional
`session_id` query parameter. Changed 2026-08-23 with the vehicle pool; before that the
route was unauthenticated and system-wide.

- **With `session_id`** — returns the state of the vehicle **leased by that session**.
  A session that does not exist, or belongs to another user, gets `403 FORBIDDEN` with
  the same message for both cases; distinguishing them would leak session enumeration,
  the same reason `POST /turns/text` already gives.
- **Without `session_id`** — allowed only while the pool is not allocating
  (`vehicle_pool_size == 1`), where the system has exactly one vehicle and the parameter
  carries no information. Once the pool allocates, omitting it returns `400
  REQUEST_CONTEXT_INVALID`: answering with the demo vehicle would be silently wrong, and
  a driver leasing `vivi-xe-02` would command their own car while watching someone
  else's screen.

The response shape is unchanged:


```json
{
  "data": {
    "vehicle_state": {
      "vehicle_id": "vehicle-demo-01",
      "state_version": 42,
      "observed_at": "2026-07-31T10:00:12Z",
      "motion": {"speed_kph": 0, "gear": "P", "ignition": "ON"},
      "hvac": {"power": true, "temperature_c": 24, "fan_level": 3},
      "windows": {"front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0},
      "doors": {"front_left": "closed", "front_right": "closed", "rear_left": "closed", "rear_right": "closed"},
      "media": {"status": "paused", "volume": 35, "track": null},
      "navigation": {"status": "idle", "destination_id": null},
      "seat": {
        "front_left":  {"heating": 0, "fore_aft": 50, "recline": 50, "height": 50},
        "front_right": {"heating": 0, "fore_aft": 50, "recline": 50, "height": 50}
      },
      "lights":     {"headlight": "auto", "interior": false},
      "trunk":      {"position": "closed"}
    }
  },
  "meta": {"request_id": "req_state_001"},
  "trace_id": "tr_state_001",
  "schema_version": "1.0"
}
```

The snapshot field remains `vehicle_state.state_version`; it is not flattened or renamed. The server reads `snapshot.state_version` and copies that value into `ActionPlan.vehicle_state_version` at planning time. A GET state failure uses the common error envelope.

### Citation and trace

```json
{
  "data": {
    "citation_id": "cit_01J...",
    "turn_id": "turn_01J...",
    "document_title": "Demo vehicle manual",
    "section": "Tyre-pressure warning",
    "page": 112,
    "chunk_id": "chunk_manual_001_112_03",
    "excerpt": "…",
    "retrieval_score": 0.86
  },
  "meta": {"request_id": "req_citation_001"},
  "trace_id": "tr_citation_001",
  "schema_version": "1.0"
}
```

This is the canonical public `Citation` schema: all eight fields are required, additional fields are rejected in schema version 1.0, `chunk_id` must resolve to the same versioned document/section/page, and the bounded `excerpt` must be supported by that chunk.

```json
{
  "data": {
    "trace_id": "tr_client_voice_001",
    "session_id": "ses_01J...",
    "turn_id": "turn_voice_01J...",
    "vehicle_id": "vehicle-demo-01",
    "status": "waiting_approval",
    "route_source": "deterministic",
    "confidence": 0.98,
    "plan_id": "plan_01J...",
    "pending_approval": {"approval_id": "appr_01J...", "expires_at": "2026-07-31T10:00:30Z"},
    "safe_summary": "Waiting for confirmation of one window action",
    "answer_text": "Bạn có chắc muốn mở kính lái không?",
    "stage_latencies_ms": {
      "stt": 420,
      "routing": 8,
      "planning_or_retrieval": 31,
      "safety": 4,
      "tool": 0,
      "tts": 0,
      "end_to_end": 463
    },
    "approval_wait_ms": 1250,
    "safety_summary": {
      "outcome": "approval_required",
      "max_level": "S2",
      "validation": "passed",
      "admission": "pending",
      "block_code": null
    },
    "versions": {
      "model_profile": "qwen2.5-3b-instruct-q4_k_m-selected",
      "prompt": "prompt-v1",
      "tool": "tools-v1",
      "data": "poi-fixture-v1",
      "index": "manual-index-v1",
      "planning_vehicle_state": 42,
      "observed_vehicle_state": 42
    },
    "admission": {
      "status": "pending_approval",
      "approval_id": "appr_01J...",
      "execution_group_id": null,
      "approved_vehicle_state_version": 42,
      "actual_vehicle_state_version": null
    }
  },
  "meta": {"request_id": "req_trace_001"},
  "trace_id": "tr_trace_read_001",
  "schema_version": "1.0"
}
```

A Driver may retrieve only a trace belonging to their current/owned turn; it exposes safe status and a pending-approval summary for recovery. An Engineer may retrieve the same safe structured operational fields. `stage_latencies_ms` has exactly `stt`, `routing`, `planning_or_retrieval`, `safety`, `tool`, `tts`, and `end_to_end`; `end_to_end` is measured before TTS synthesis runs and therefore does not include `tts` latency — `tts` is tracked as an independent stage, not a component of the `end_to_end` sum; human `approval_wait_ms` is separate and is never folded into stage latency. `safety_summary` has exactly `outcome`, `max_level`, `validation`, `admission`, and nullable `block_code`. `versions` has exactly `model_profile`, `prompt`, `tool`, `data`, `index`, `planning_vehicle_state`, and `observed_vehicle_state`. The functioning trace example uses the clearly illustrative selected profile ID `qwen2.5-3b-instruct-q4_k_m-selected`; deployment configuration remains fail-closed at `LLM_MODEL_PROFILE=not-selected` with an empty model path until ADR-005 evidence selects a real manifested profile. `admission` has exactly `status`, nullable `approval_id`, nullable `execution_group_id`, nullable `approved_vehicle_state_version`, and nullable `actual_vehicle_state_version`.

Two fields carry per-turn context beyond the aggregates, both added by ADR-029. `vehicle_id` is the vehicle the turn acted on, read from the session record; it is nullable, and while the deployment runs a single vehicle it is constant for every trace. `answer_text` is the assistant's composed reply to the driver — the same string delivered as `assistant.response.display_text` — truncated at 2000 characters with a trailing `…` when longer, and `null` for a turn that failed before composition.

`answer_text` is deliberately **not** an exception to the redaction rule. The prohibited list below is content originating from the driver or from the host machine; `answer_text` is generated entirely by the server, either as a Vietnamese template built from a tool name and its arguments or as a verbatim manual quotation, and no composition path interpolates the driver's utterance into it. The driver's own words remain unavailable at this surface: `transcript.final.text` has no field in the trace record, and citation bodies are counted rather than carried. `/metrics/summary` exposes neither field — it remains a pure numeric fold.

Neither role receives raw prompts, hidden reasoning/chain-of-thought, raw audio, unrestricted transcripts, credentials, or secret paths. Citation resolution is similarly owner/role-scoped and rejects path traversal.

### Metrics summary

```json
{
  "data": {
    "window": {"from": "2026-07-31T09:00:00Z", "to": "2026-07-31T10:00:00Z"},
    "turns": {"accepted": 120, "completed": 113, "failed": 4, "canceled": 3},
    "stage_latency_ms": {
      "stt": {"count": 72, "p50": 420, "p95": 920},
      "routing": {"count": 120, "p50": 8, "p95": 16},
      "planning_or_retrieval": {"count": 113, "p50": 31, "p95": 210},
      "safety": {"count": 88, "p50": 4, "p95": 9},
      "tool": {"count": 33, "p50": 38, "p95": 140},
      "tts": {"count": 110, "p50": 180, "p95": 410},
      "end_to_end": {"count": 113, "p50": 640, "p95": 1880}
    },
    "model_runtime": {
      "model_profile": "qwen2.5-3b-instruct-q4_k_m-selected",
      "tokens_per_second": {"count": 41, "p50": 12.4, "p95": 15.9},
      "rss_mib": {"sample_count": 60, "current": 1840.0, "peak": 2300.0}
    },
    "mqtt": {
      "publish_attempts": 36,
      "published": 34,
      "latency_ms": {"count": 34, "p50": 18, "p95": 85},
      "errors": 2,
      "error_rate": 0.0588
    },
    "rag": {
      "answered": 24,
      "grounded": 23,
      "abstained": 7,
      "grounded_rate": 0.9583,
      "abstention_rate": 0.2258,
      "citation_evaluated": 23,
      "citation_valid": 23,
      "citation_validity_rate": 1.0,
      "faithfulness_evaluated": 23,
      "faithfulness_passed": 22,
      "faithfulness_pass_rate": 0.9565
    },
    "safety": {
      "validation_denied": 5,
      "blocked_s3": 4,
      "approvals_required": 12,
      "approved": 8,
      "rejected": 2,
      "expired": 1,
      "invalidated_state": 1,
      "invalidated_plan": 0,
      "predicate_failed": 0
    },
    "action_audit": {
      "attempted": 33,
      "completed": 31,
      "failed": 2,
      "timeout": 0,
      "deduplicated": 3,
      "skipped_prior_failure": 1,
      "skipped_external_state_change": 1
    }
  },
  "meta": {"request_id": "req_metrics_001"},
  "trace_id": "tr_metrics_001",
  "schema_version": "1.0"
}
```

This route is Engineer-only and returns safe structured aggregates, not another user's content. All groups use the half-open UTC `window [from,to)`. Producers and denominators are normative:

**Implementation decision (TASK-BE-OBS-001, 2026-08-10).** This document pins the window *shape* and the half-open UTC convention but never says whether the window is rolling, since-boot, or client-selectable, and defines no query parameters for this route. The implementation chose a **server-selected rolling window**: `from = max(process_start, now − METRICS_WINDOW_SECONDS)` and `to = now`, with `METRICS_WINDOW_SECONDS` defaulting to `3600`. The route accepts **no** query parameters, because adding `?from=`/`?to=` would widen a documented surface without a decision. Two further gaps filled the same way: percentiles use **nearest-rank** (`index = ceil(p/100 × n) − 1`), and `mqtt.publish_attempts` currently counts **executed plan steps**, not raw broker publishes — QoS 1 retries and duplicate acks live below the trace layer and are not observable from it. Broker-level counters are follow-up work.

| Group | Producer | Count/denominator rule |
|---|---|---|
| `turns` | API turn lifecycle store | Counts accepted turns by exactly-one terminal status in the window; in-flight accepted turns need not equal terminal totals. |
| `stage_latency_ms` | Backend monotonic trace spans owned by each stage | Each stage's `count` is valid completed spans for that stage; p50/p95 use only those spans. |
| `model_runtime` | llama response-usage spans plus local process RSS sampler | Token-rate `count` is successful measured generations; RSS `sample_count` counts in-window samples; profile is the pinned active profile/config identifier. |
| `mqtt` | Executor MQTT port publish/ack/error instrumentation | `error_rate = errors / publish_attempts`; latency count includes successful acknowledged publishes only. |
| `rag` | Retrieval/citation validator plus versioned human/eval evidence aggregator | `grounded_rate = grounded / answered`; `abstention_rate = abstained / (answered + abstained)`; citation rate uses `citation_valid / citation_evaluated`; faithfulness uses only versioned rubric-scored cases, `faithfulness_passed / faithfulness_evaluated`, never an unreviewed live-model self-score. |
| `safety` | Deterministic validator/policy/approval audit | Event counts by terminal policy/admission outcome; the fields are counts, not rates. |
| `action_audit` | Persisted `ToolResult` plus executor dedup audit | `attempted` counts unique started executions that reach completed/failed/timeout; deduplicated replays and skipped steps are separate and not in that denominator. |

For an empty window, all counts are `0`; every percentile and rate is JSON `null`; RSS `current`/`peak` are `null` when `sample_count=0`; `model_profile` remains the pinned configured identifier or `"not-selected"`. In particular, `faithfulness_pass_rate=null` whenever `faithfulness_evaluated=0`; absence of scored cases is never reported as 0% or 100%. The endpoint never exposes prompts, raw audio, transcript content, credentials, secret paths, per-user queries, or chain-of-thought. Full trace/eval execution and model/config changes are authorized/audited CLI/P1 capabilities, not this P0 endpoint.

The `p50=640`, `p95=1880`, per-stage/runtime/MQTT/RAG/safety/action figures, health-probe latencies, timestamps, counts, and selected-profile identifier anywhere in this API document are schema fixtures/documentation examples only—not observed measurements or model-selection evidence. Only numbers traced to [the PoC evaluation report](../eval/results/report.md) may be cited as measured evidence until runtime eval artifacts exist.

### Health

```json
{
  "data": {
    "status": "ready",
    "checked_at": "2026-07-31T10:00:00Z",
    "components": {
      "backend": {"status": "ready", "latency_ms": 2},
      "llm": {"status": "ready", "latency_ms": 12},
      "mqtt": {"status": "ready", "latency_ms": 8},
      "vehicle_simulator": {"status": "ready", "latency_ms": 11},
      "stt": {"status": "ready", "latency_ms": 4},
      "tts": {"status": "ready", "latency_ms": 3},
      "rag_index": {"status": "ready", "latency_ms": 2},
      "sqlite": {"status": "ready", "latency_ms": 1}
    },
    "faults": []
  },
  "meta": {"request_id": "req_health_001"},
  "trace_id": "tr_health_001",
  "schema_version": "1.0"
}
```

Each required dependency has one status: `ready` means its real probe passed and it can serve the demo; `degraded` means the probe responded but correctness/capacity is insufficient; `down` means unavailable, timed out, missing, not configured, or authentication/ACL denied. Probe semantics are: `backend` event-loop/self-check; `llm` configured-model identity plus inference-ready health; `mqtt` backend-identity authenticated connect/publish/subscribe; `vehicle_simulator` simulator-identity authentication plus fresh heartbeat/state; `stt` local model load plus bounded transcribe smoke; `tts` local voice load plus bounded synthesize smoke; `rag_index` manifest/checksum plus open/query smoke; and `sqlite` open/read/write transaction smoke. Backend broker credential/ACL failure reports `mqtt=down`; simulator credential/ACL failure or missing authenticated heartbeat reports `vehicle_simulator=down`.

`GET /healthz` is full demo readiness. All eight components—`backend`, `llm`, `mqtt`, `vehicle_simulator`, `stt`, `tts`, `rag_index`, and `sqlite`—are always probed and reported in `components`/`error.details.dependencies`, but the readiness gate only requires seven of them: `llm` is exempt at P0 (decided 2026-08-11, issue #48) because `slm_enabled=False` by design (ADR-005 "Not Yet") makes it permanently unable to reach `ready`, and gating on a dependency that does not run at P0 would report `503` for a condition that is not an incident. A component has one of four states: `ready`, `degraded`, `down`, and — since 2026-08-15, issue #95 — `disabled`. `disabled` means the running configuration deliberately turns that component off: `llm` when `slm_enabled=false` (the P0 default), and `mqtt` **and** `vehicle_simulator` when `MQTT_ENABLED=false`. `vehicle_simulator` is `disabled` rather than `down` in that configuration because it is reachable only over MQTT — its heartbeat travels on the broker that was just switched off — so its absence follows from the same deliberate choice; leaving it `down` would rebuild the same permanent `503` under a different component name. A deliberately disabled component is **not** a broken dependency and never forces `503` on its own, but it is still probed, still reported in `components`, and still listed in `faults`/`error.details.dependencies` with `status="disabled"` and a code (`slm_disabled`, `mqtt_disabled`, `vehicle_simulator_mqtt_disabled`) — exempt from the gate is not hidden from the payload. Turning a component **off** is distinct from a component **failing**: with `MQTT_ENABLED=true` and no broker, `mqtt` is `down` and `/healthz` still returns `503`. It returns `200` with `status="ready"` when no **required** component is in a blocking state (`degraded` or `down`); `llm` may be `degraded`/`down` in a `200` response and still appears truthfully in `components`/`faults`. Any `degraded` or `down` **required** component returns `503` using the common error envelope; `error.details.dependencies` contains the same eight names with redacted status/probe code, and no credentials or filesystem secret values. When LLM/SLM becomes a required dependency of the P0/P1 flow, `llm` returns to the required set. Process/container liveness is a separate internal supervisor check and is not an additional P0 public REST interface.

> ## P1 MANAGEMENT — NOT PART OF THE P0 PUBLIC SURFACE
>
> The only P1 management endpoint families are `/manuals/ingest`, `/eval/runs*`, and `/model-profiles*`. At P0 their equivalents are CLI manual ingestion, CLI evaluation, and `.env` configuration followed by a controlled restart. They must not be routed or advertised as P0. Fleet and OTA are P2.
>
> `GET/PUT /api/v1/vehicle/profile` (interface 13) is **not** one of those families and is not covered by this exclusion. `/model-profiles*` is about *LLM model* profiles, a different subject; vehicle configuration is an input the P0 answer path reads on every tyre-pressure question. See the note under the interface table for why `.env` plus restart was not an acceptable substitute here.

## WebSocket contracts

Driver connects to `WS /ws/ivi`; Engineer connects to `WS /ws/engineer`. Browser clients offer exactly the application protocol and auth protocol in `Sec-WebSocket-Protocol`, for example `vivi.v1, bearer.<base64url-access-token>`. Before accepting application messages, the server validates token signature and expiry, role, exact allowed `Origin`, and Driver session ownership; on success it selects only `vivi.v1` in the response. The local profile allows exactly `Origin: http://localhost:3000`; a packaged profile uses its configured exact-origin allowlist.

Missing/expired authentication closes with `4401`. Role, origin, or session-ownership mismatch closes with `4403`. Access logs redact the entire auth subprotocol value and never log the token. Authentication credentials are never accepted in the URL query string. Plain `ws://` is permitted only for loopback local development; any non-loopback deployment uses `wss://` with locally configured TLS and requires no cloud dependency.

A client that does not offer the application subprotocol `vivi.v1` is rejected with `WS_EVENT_INVALID` and closed with `1003`, on both sockets, and this check runs **before** authentication. Added by the PR #63 review (2026-08-12): the paragraph above required the client to offer `vivi.v1, bearer.<...>` but named close codes only for authentication, origin, and session failures, so both routes accepted a client that offered `bearer.<token>` alone. `4401`/`4403` are deliberately not reused here — a missing application subprotocol is a protocol-contract violation, not a permission failure, and answering `4401` would send the client to refresh a token that was never the problem. Checking it before authentication keeps a client that is not yet speaking the agreed protocol from learning whether its token is valid.

### Client control-message base

Client control messages and server events are different schemas. Every client control message requires:

- non-empty allowlisted `type`;
- unique `client_message_id` for client-side retry/deduplication;
- `sent_at` as UTC ISO 8601;
- `schema_version` equal to a supported version;
- `session_id` and cursor fields when required by that message type.

The P0 Driver/Engineer client-control allowlist contains only `connection.init`. It binds the socket and optionally requests replay. It does not contain `event_id`, `sequence`, `trace_id`, or `emitted_at` because those are server-event fields.

```json
{
  "type": "connection.init",
  "client_message_id": "cmsg_01J...",
  "sent_at": "2026-07-31T10:00:13Z",
  "schema_version": "1.0",
  "session_id": "ses_01J...",
  "last_event_id": "evt_01J...",
  "last_sequence": 18
}
```

For `/ws/ivi`, `session_id` is required and must be owned/current. For `/ws/engineer`, it is omitted. A fresh connection omits both `last_event_id` and `last_sequence`; a replay connection supplies both. Supplying only one, or a pair that does not identify the same retained event, returns `REPLAY_CURSOR_INVALID`. A matching cursor that is valid but older than the replay window returns `REPLAY_WINDOW_EXPIRED`. Missing, empty, or unknown `type`, missing base fields, an unauthorized session, or an unsupported schema returns `WS_EVENT_INVALID`/`FORBIDDEN` and closes when unsafe to continue.

### Server event base

Every server event requires non-empty allowlisted `type`, unique `event_id`, monotonically increasing `sequence` within the authorized stream, `trace_id`, `emitted_at`, `schema_version`, and a typed `payload` object. Session events also require `session_id`; turn events require both `session_id` and `turn_id`.

```json
{
  "type": "turn.accepted",
  "event_id": "evt_01J...",
  "sequence": 19,
  "trace_id": "tr_client_voice_001",
  "emitted_at": "2026-07-31T10:00:13Z",
  "schema_version": "1.0",
  "session_id": "ses_01J...",
  "turn_id": "turn_voice_01J...",
  "payload": {"status": "accepted", "input_mode": "voice"}
}
```

### Driver server-event allowlist and required payload

All listed payload fields are required unless marked optional. Additional fields are rejected unless the negotiated schema version allows them.

| `type` | Required context | Required `payload` fields |
|---|---|---|
| `turn.accepted` | session, turn | `status="accepted"`, `input_mode` enum `{"voice","text"}` |
| `transcript.partial` | session, turn | `text:string`, `partial_index:int>=1` |
| `transcript.final` | session, turn | `text:string`, `language="vi"`, `confidence:number 0..1`, `transcription_status` enum `{"completed","unusable"}` |
| `assistant.status` | session, turn | `state` enum `{"transcribing","routing","planning","retrieving","waiting_approval","executing","composing"}`, `message:string` |
| `plan.ready` | session, turn | `route_kind` enum `{"action","manual","response"}`, `plan_id:string|null`, `summary:string`, `requires_approval:boolean`, `steps:array` of `{step_id:string, tool:string, domain:string|null, args:object}` in plan order; `domain` is null for IVI-local tools that never publish to MQTT. **`steps` is not a screen-switch signal** — this event fires during routing, before the policy branch, so it is emitted for blocked (S3) turns too; a client that switches on it opens the app and only then gets blocked. Switch on `tool.result` with `status="completed"` (ADR-023) |
| `approval.required` | session, turn | `approval_id`, `plan_id`, `approved_vehicle_state_version:int>=0`, `actions:array`, `expires_at` |
| `approval.intent.detected` | approval-intent session/turn | `approval_id`, `original_turn_id`, `decision` enum `{"approve","reject"}`, `approved_vehicle_state_version:int>=0`, `committed:boolean` — true when this turn already committed the decision server-side (explicit confirmation phrase, or any rejection phrase), false when the event is handoff only and the IVI must still obtain the decision. The other four fields are identical in both cases; `committed` is the only discriminator |
| `action.blocked` | session, turn | `plan_id`, `code="SAFETY_BLOCKED"`, `reason:string` |
| `tool.result` | session, turn | `step_id`, server-derived `command_id`, `status` enum `{"completed","failed","timeout","skipped_due_to_prior_failure","skipped_external_state_change"}`, `observed_state_version:int>=0|null`, `error_code:string|null`; observed version is required when state was observed/result produced and null only when no observation was possible; `error_code` is null only for completed and required for failed/timeout/skipped |
| `assistant.speech` | session, turn | `audio_base64:string`, `mime_type="audio/wav"` |
| `assistant.response` | session, turn | `display_text`, `speak_text`, `citations:array`, `outcomes:array`, `has_more_to_read:bool`, `mo_mic_ngan:bool`, optional `routine_preview` with `{routine_id:string, routine_name:string, steps:array}` where each step is `{index:int>=0, action:string, description:string}`. Preview is display-only and must never be treated as an execution signal. Optional `routine_setup_required` (issue #385) with `{routine_id:string, ma_loi:string, thieu:array<string>}` — non-null only when the voice-run outcome's error code is `chua_dat_dia_diem`; `thieu` lists the missing place labels (`"home"`/`"office"`) so the client opens the correct setup row without matching Vietnamese text |
| `ui.policy` | session; turn optional | `active:boolean`, `speed_kph:number>=0`, and `ui_policy` with exactly `allow_text_input:boolean`, `lock_small_controls:boolean`, `enlarge_mic_button:boolean`, `max_visible_actions:integer 1..3`, `prefer_voice_confirmation:boolean`, `allow_detailed_document_browsing:boolean` |
| `error` | session; turn when scoped | `code`, `message`, `retryable:boolean`, `terminal:boolean`, `details:object` |
| `turn.completed` | session, turn | `status="completed"`, `completed_at` |
| `turn.failed` | session, turn | `status="failed"`, `code`, `completed_at`. `code` ∈ `{VALIDATION_DENIED, EXECUTION_FAILED, MQTT_UNAVAILABLE, STT_FAILED, STT_UNUSABLE, APPROVAL_INTENT_AMBIGUOUS, INTERNAL_ERROR}` — xem ghi chú về outcome hỏng dưới bảng |
| `routine.started` | session; `turn` mang `execution_id` | `execution_id`, `routine_id`, `routine_name:string`, `routine_version:int>=1`, `steps:array` of `{index:int>=0, action:string, description:string}`, `started_at` — phát một lần khi một lần chạy Routine được nhận (#290). `steps` có mặt ngay từ đầu để thanh tiến độ không phải đoán tổng số bước |
| `routine.step` | session; `turn` mang `execution_id` | `execution_id`, `index:int>=0`, `action:string`, `status` enum `{"completed","failed","skipped","blocked","canceled","waiting_approval"}`, `description:string`, `error_code:string|null`, `approval_id:string` (chỉ khi `status="waiting_approval"`) |
| `routine.finished` | session; `turn` mang `execution_id` | `execution_id`, `routine_id`, `status` enum `{"completed","failed","blocked","user_canceled"}`, `terminal_reason:string|null`, `results:array` các bước với cùng tập trạng thái trên, `completed_at`, `audio_base64:string|null`, `mime_type:string|null` (thêm 2026-08-30, issue #396) — **đúng một** sự kiện cho mỗi lần chạy, kể cả khi lỗi hay hủy; không có update nào sau nó |
| `turn.canceled` | session, turn | `status="canceled"`, `reason` enum `{"approval_rejected","approval_expired","approval_invalidated_state","approval_invalidated_plan","approval_predicate_failed","approval_not_pending","user_canceled"}`, `completed_at` |

`display_text` **không bao giờ dài hơn một phụ đề** kể từ 2026-08-21. Trước đó nó chở nguyên văn cả đoạn sổ tay (tới `QUOTE_MAX_CHARS = 1.200`) còn `speak_text` chỉ chở vài câu đã chọn; nhóm yêu cầu bỏ sự lệch ấy vì việc tài xế thật sự làm với màn hình là *xem lại phụ đề*, không phải đọc lại cả đoạn.

Luật, một câu: **bản nhìn được giữ khi nó vẫn ngắn như một phụ đề (`MAX_SPOKEN_CHARS`); dài hơn thế thì màn hình nhận đúng bản đã nói.** Đo trên hai đầu của dải:

| lượt | `display_text` | `speak_text` |
|---|---:|---:|
| tra sổ tay ("Cách khởi tạo lại cửa sổ điện?") | 188 | 188 |
| câu hỏi lại (`missing_fan_level`) | 98 | 60 |
| điều khiển | 35 | 35 |

Hai trường vì thế **thường** bằng nhau nhưng client **không được** giả định thế: câu hỏi lại cố ý cho màn hình thêm một vế — `Nói mỗi mức cũng được, ví dụ "mức 2".` — vì ví dụ trong ngoặc kép chỉ có nghĩa khi **nhìn** thấy dấu ngoặc. Đó là một trong ba thành phần mà [#148](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/148) xác định là cần thiết cho một câu hỏi lại dùng được.

Bất biến này được giữ ở đúng **một** chỗ: `assistant_response_payload` (`src/services/ivi_events.py`), nơi dựng cả sự kiện WS lẫn envelope HTTP. `compose_node` báo trung thực cả hai kênh và **không** tự ép chúng bằng nhau — ép ở đó là xoá luôn vế ví dụ ở trên.

Đường lui khi một node quên `speak_text` có **trần**: cắt ở biên câu theo `MAX_SPEECH_CHARS`, cùng phép cắt mà `synthesize_speech` áp cho `speak_text` quá dài. Không có nó thì một node cũ đẩy 1.200 ký tự trở lại cả UI lẫn TTS — đo 13/08 sau khi cài Piper: 65,6 giây audio và một `assistant.speech` 4,60 MB.

Hệ quả phải biết: sau thay đổi này **không đường nào trên dây còn chở nguyên văn cả đoạn**. `trace` đã redact ba trường văn bản từ trước, nên muốn đọc hết một đoạn thì chỉ còn hai lối — nói *"đọc tiếp"* từng lát, hoặc mở `GET /citations/{citation_id}`.

`has_more_to_read` (thêm 2026-08-14) báo đoạn sổ tay còn phần chưa đọc. Cờ này càng quan trọng hơn sau khi hai kênh gộp: dấu `(còn tiếp — …)` vốn dán riêng cho màn hình đã bỏ, và thứ thay nó là chính lời mời *"Bạn có muốn nghe tiếp nguyên văn không?"* trong câu nói. Client vẫn phải render nút "Nghe tiếp" theo **cờ**, không theo chuỗi. Nó **không** có trong envelope HTTP của `POST /turns/text`: `TurnResponseData` là `extra="forbid"` và mở rộng nó là đổi hợp đồng đồng bộ P0 — quyết định riêng, chưa làm.
Ba sự kiện `routine.*` (thêm 2026-08-29, issue #290) thuộc epic Routines MVP (#270), không phải P0. Chúng mang `execution_id` ở vị trí `turn_id` của khung sự kiện: trên stream tài xế, một lần chạy Routine đóng vai một "lượt" — client nhóm sự kiện theo đó, và `sequence`/`event_id` của ADR-014 vốn đánh theo **phiên** nên thứ tự lẫn replay đã đúng sẵn mà không cần cơ chế riêng. Tầng phát là **fail-open**: một lỗi WebSocket không được làm hỏng một chuỗi lệnh đang chạy trên xe, và `GET /api/v1/routine-executions/{id}` luôn là nguồn sự thật để hỏi lại.

`mo_mic_ngan` (thêm 2026-08-29, [#363](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/363)) báo lượt này là một **câu hỏi lại có mẫu ngữ pháp**, nên client được mở mic ngắn 3–5 s để tài xế đáp ngay thay vì phải nói lại wake word. Chỉ bật khi `outcome == "clarify"` và lý do nằm trong `src/agents/mau_slot.CO_MAU` — một tập vừa là "được mở mic" vừa là "có rào chắn", vì không có rào thì không mở cửa. **Backend không phụ thuộc vào việc client có mở hay không:** rào chắn chạy trên mọi lượt, nên cờ này là một lời mời, không phải một nửa của cổng an toàn. Cũng **không** có trong envelope HTTP, cùng lý do với `has_more_to_read` ngay dưới.

**Outcome nào kết thúc bằng `turn.failed`** (quyết định PM/PO trên issue #375, 2026-08-29). Một lượt **hỏng** là lượt mà hệ tự không làm được việc, không phải lượt mà hệ từ chối có chủ đích:

| `outcome` | sự kiện terminal | `code` |
|---|---|---|
| `validation_denied` | `turn.failed` | `VALIDATION_DENIED` |
| `execution_failed` | `turn.failed` | `EXECUTION_FAILED` |
| `vehicle_state_unavailable` | `turn.failed` | `MQTT_UNAVAILABLE` |
| `clarify`, `denied`, `not_control`, `offer`, `grounded_answer`, `grounded_refusal`, `blocked`, `chitchat` | `turn.completed` | — |

`blocked` (S3 chặn) và `denied` nằm ở nhóm dưới có chủ đích: đó là **quyết định an toàn đúng**, hệ đã trả lời đúng thứ nó nên trả lời. Gọi chúng là hỏng sẽ biến mọi lượt hỏi sổ tay và mọi lần chặn S3 thành một lượt lỗi trên dashboard kỹ sư.

Điều này quan trọng vì `TraceRecord.status` và `/metrics/summary` fold theo chính sự kiện terminal ấy. Trước #375, `validation_denied` phát `turn.completed`, nên một lượt có plan chết ở `validate_args` được đếm là thành công — một con số sai trông y hệt một con số đúng. Nguồn duy nhất của luật này là `OUTCOME_LUOT_HONG` trong `src/services/ivi_events.py`.
Từ 2026-08-29 (spec `docs/superpowers/specs/2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md`), `mo_mic_ngan` do `src/agents/nghe_tiep.py` tính từ **kết cục cuối** của lượt chứ không còn do `route_node` ghi — `route_node` không thấy `completed`, mà `completed` là ~90% lượt và là ca chính của cửa sổ nghe tiếp. Nó bật sau `completed` / `offer` / `clarify` có mẫu ngữ pháp / câu hỏi sổ tay trả lời được; tắt khi xe không hiểu (`default_to_manual`), khi nghe hụt (`manh_khong_khop_mau`), và khi tài xế nói thôi (`offer_declined`, `giai_tan`).

Cùng ngày, `POST /turns/voice` nhận thêm header **`X-Capture-Mode: auto | manual`** (vắng = `manual`, nên client cũ không đổi hành vi). `auto` nghĩa là lượt này do mic **tự mở** bắt được. Lượt `auto` mà xe không hiểu trả `speak_text` **rỗng** và không phát `assistant.speech`: xe chỉ nói khi được gọi. Đo được lý do — với cửa sổ mở, một câu tài xế nói với người ngồi cạnh (*"lát nữa mở cốp lấy đồ nhé"*) khiến xe đọc *"Tôi không tìm thấy thông tin này trong sổ tay xe."* vào giữa cuộc nói chuyện của họ.

Header này là thứ **client tự khai**, và tin được vì nó chỉ khiến xe **im hơn**, không bao giờ khiến xe **dễ dãi hơn** — khác hẳn một cổng an toàn. Rào chắn `mau_slot` (#363) **không** đọc nó và vẫn chạy trên mọi lượt.

`has_more_to_read` (thêm 2026-08-14) báo đoạn sổ tay còn phần chưa đọc — lời mời *"Bạn có muốn nghe tiếp nguyên văn không?"* chỉ nằm trong `speak_text`, nên thiếu cờ này thì client nhìn màn hình không có gì để render một nút "Nghe tiếp". Nó **không** có trong envelope HTTP của `POST /turns/text`: `TurnResponseData` là `extra="forbid"` và mở rộng nó là đổi hợp đồng đồng bộ P0 — quyết định riêng, chưa làm.

The `transcript.final` event occurs exactly once for every accepted voice turn. When transcription is unusable it carries `text=""` and `transcription_status="unusable"`, followed by terminal error/failure events; the agent never receives the empty transcript.

`assistant.speech` is best-effort — emitted immediately before the event carrying the text it reads, when TTS synthesis succeeds; absent entirely (no empty event, no error event) when TTS fails or when the text is empty. Clients must not treat absence as a protocol error. On answer turns that event is `assistant.response`. On the **S2 pending** turn there is no `assistant.response`: the confirmation question travels in `assistant.status(state="waiting_approval")`, and its speech is emitted **before `approval.required`** (issue #215). That order is a correctness requirement, not cosmetics: the IVI opens the microphone as soon as the approval dialog appears, so speech emitted after `approval.required` leaves a window in which the client sees no audio, starts recording, and captures the car's own voice. The **ambiguous approval-intent** turn is the third case and follows the same shape for the same reason (issue #212): the text travels in `error(terminal=true)`, the speech is emitted before it, and the mic reopens on that branch by itself since #211 — a mic that lights up in silence tells a driver who is watching the road nothing at all.

`error.payload.code` is not a closed enum, but two codes are load-bearing and must stay distinct. `VEHICLE_POOL_EXHAUSTED` (surfaced through `tool.result.error_code = "vehicle_pool_exhausted"`) means the session **never** got a car because the pool was full. `VEHICLE_LEASE_EXPIRED` means the session **had** a car and lost it: the lease timed out and the car was handed to somebody else. The two carry different explanations for the driver, so a client must not collapse them — telling a driver who just lost their car that "no simulator vehicles are available" is a wrong statement, not a vague one. `VEHICLE_LEASE_EXPIRED` is emitted once per loss, `terminal=false` (the turn still answers; only control commands are refused) with `details.can_drive=false`, and is the signal a client uses to flip its view-only state mid-session — `POST /sessions` reports `can_drive` only at creation time. Both are inert on the repo default `vehicle_pool_size = 1`, which allocates no leases at all.

`ui.policy.payload` is value-identical to the canonical object in [technical_spec.md](technical_spec.md#frontend-and-driving-policy) and its UX mirror. In moving mode (`active=true`, sample `speed_kph=42`) the exact six values are `allow_text_input=false`, `lock_small_controls=true`, `enlarge_mic_button=true`, `max_visible_actions=3`, `prefer_voice_confirmation=true`, and `allow_detailed_document_browsing=false`. Stationary/moving/S2/S3/low-confidence conditions remain backend-derived as documented there; the client never infers them. Missing or additional top-level/policy fields are rejected unless a negotiated future schema version explicitly adds them.

```json
{
  "type": "ui.policy",
  "event_id": "evt_ui_policy_001",
  "sequence": 18,
  "trace_id": "tr_ui_policy_001",
  "session_id": "ses_01J...",
  "turn_id": null,
  "emitted_at": "2026-07-31T10:00:12Z",
  "schema_version": "1.0",
  "payload": {
    "active": true,
    "speed_kph": 42,
    "ui_policy": {
      "allow_text_input": false,
      "lock_small_controls": true,
      "enlarge_mic_button": true,
      "max_visible_actions": 3,
      "prefer_voice_confirmation": true,
      "allow_detailed_document_browsing": false
    }
  }
}
```

### Engineer server-event allowlist and required payload

| `type` | Required `payload` fields |
|---|---|
| `state` | `vehicle_state` with the exact canonical GET shape |
| `trace` | `trace_id`, `vehicle_id:string|null`, `status`, `route_source`, `safe_summary`, `answer_text:string|null`, `pending_approval:object|null`, `stage_latencies_ms`, `approval_wait_ms`, `safety_summary`, `versions`, and `admission`, with exactly the safe GET trace schemas above |
| `metrics` | `window`, `turns`, `stage_latency_ms`, `model_runtime`, `mqtt`, `rag`, `safety`, and `action_audit` matching the safe aggregate GET schema |
| `health` | `status`, `checked_at`, `components`, `faults` matching the health GET schema |
| `error` | `code`, `message`, `retryable:boolean`, `terminal:boolean`, `details:object` |

Engineer events are role-scoped and never contain raw prompts, hidden reasoning/chain-of-thought, raw audio, unrestricted transcripts, credentials, or secret paths. `answer_text` is not an exception: it is the server-composed reply described under the GET trace schema, never the driver's own words.

**Emit triggers (TASK-BE-OBS-001, 2026-08-10).** This document lists the required payload for each Engineer event but never states when they fire. The implementation emits `state` on every vehicle transition (unchanged), `trace` **on turn seal** for every session — the Engineer stream is fleet-scoped, since `connection.init` omits `session_id` — and `metrics`/`health` from a **single shared sampler** at 5 s and 10 s respectively, not one sampler per socket. On connect the server pushes `state` and `metrics` immediately; `health` deliberately arrives from the sampler's first tick instead of the handshake, because the eight readiness probes load real STT/RAG assets and would otherwise block `connection.init` for tens of seconds. `health` always carries the **200-branch health schema** (`checked_at`, `components[].latency_ms`) even when components are down; the 503 REST envelope shape (`error.details.dependencies`) is an HTTP-only branch and never appears on the WebSocket.

### Normative asynchronous voice-turn state machine

| Stage | Required ordered server events | Next state |
|---|---|---|
| REST acceptance | HTTP `202`, then `turn.accepted`, `assistant.status(state="transcribing")` | Transcribing |
| Transcription | zero or more `transcript.partial`, exactly one `transcript.final` | Routing or terminal failure |
| Control route/plan | `assistant.status(state="routing")`, optional `planning`, then `plan.ready` | Policy branch |
| Manual/RAG no-tool | `assistant.status(state="routing")`, `assistant.status(state="retrieving")`, `assistant.status(state="composing")`, `assistant.response` with citations, `turn.completed`; zero `tool.result` and no `executing` status | Terminal completed |
| Successful execution without S2 | `assistant.status(state="executing")`, one or more completed `tool.result`, honest `assistant.response`, `turn.completed` | Terminal completed |
| S2 pending | best-effort `assistant.speech` reading the confirmation question, then `approval.required`, then `assistant.status(state="waiting_approval")` | Nonterminal waiting approval |
| Second S2 while same session has pending approval | `error(code="APPROVAL_ALREADY_PENDING", terminal=false)`, focused `assistant.response`, `turn.completed`; no `plan.ready`, new `approval.required`, group, tool result, or side effect | New turn terminal completed as clarification; original remains pending |
| Approval-intent voice handoff | Distinct turn emits normal transcript/route events, `approval.intent.detected`, `assistant.response`, `turn.completed`; IVI calls REST only when `committed=false` | Intent turn terminal completed; original remains pending until REST outcome |
| Approval-intent ambiguous/no pending | Ambiguous: `assistant.speech` (best-effort), `error(terminal=true)`, `turn.failed`; no pending: `assistant.response`, `turn.canceled(reason="approval_not_pending")` | Intent turn has exactly one terminal; no REST/MQTT |
| S2 rejected/expired | REST reject or expiry, then original-turn `assistant.response`, `turn.canceled(reason="approval_rejected"|"approval_expired")` | Original command terminal canceled; zero side effect |
| S2 invalidated before admission | REST `409` for state/plan-digest/predicate, then original-turn `assistant.response`, matching `turn.canceled` reason | Original command terminal canceled; no consume/group/MQTT |
| S2 approved/admitted and successful | REST approve returns admitted group, then `assistant.status(state="executing")`, one or more completed `tool.result`, `assistant.response`, `turn.completed` | Terminal completed |
| S3 | `action.blocked`, `assistant.response`, `turn.completed` | Terminal completed with blocked outcome |
| Execution failed/timeout | `assistant.status(state="executing")`, completed results if any, exactly one failed/timeout `tool.result`, one `skipped_due_to_prior_failure` result for every remaining not-started step, honest `assistant.response` listing completed/failed/skipped, then exactly one `turn.failed` | Terminal failed; never completed |
| External state mutation | `assistant.status(state="executing")`, completed results if any, `skipped_external_state_change` for the mismatching/not-started step and every remaining step, honest `assistant.response`, then exactly one `turn.failed` | Terminal failed; re-plan required |
| Failure | `error(terminal=true)`, then `turn.failed` | Terminal failed |

Voice approval intent is a separate accepted voice turn. It emits typed `approval.intent.detected` carrying `committed`; when `committed` is false the IVI—not the intent turn—calls the REST decision endpoint, and when it is true the IVI must not call it again.

### Ordering, replay, and recovery invariants

- `sequence` strictly increases per authorized server stream. Replayed events keep their original `event_id` and sequence; clients deduplicate by `event_id` before rendering or triggering UI behavior.
- `transcript.partial` may repeat zero or more times and may supersede earlier text; partial indexes increase. Exactly one `transcript.final` follows, and no transcript event follows it.
- Each accepted turn emits exactly one of `turn.completed`, `turn.failed`, or `turn.canceled`. No event for that `turn_id` is emitted after the terminal event.
- The approval-intent turn and original command turn have independent `turn_id` values and independent exactly-one terminal guarantees. Handoff completion never terminalizes the original command. Since #191 the intent turn may commit the decision before emitting (it says so in `committed`); the original command is then terminalized by the execution/reject path exactly as it would be after a REST decision, never by the handoff event itself.
- A failed/timeout execution is fail-fast: after its one terminal failed/timeout result, every remaining not-started step receives `skipped_due_to_prior_failure`; external-version mismatch uses `skipped_external_state_change`. Both paths end in `turn.failed`, never `turn.completed`.
- A pending approval is nonterminal, and a session can have at most one. Reconnect replay includes retained `approval.required`, `assistant.status(waiting_approval)`, approval-intent handoff, admission/invalidation, and execution events in original order.
- On reconnect, `connection.init` supplies the last durable cursor pair. Both cursor fields are absent or present together. A non-corresponding pair yields `REPLAY_CURSOR_INVALID`; an old but matching cursor yields `REPLAY_WINDOW_EXPIRED`. The server replays its bounded retention window, then live events.
- After replay-window expiry, the Driver uses the `trace_id` from the REST `202` to call their role-authorized `GET /api/v1/traces/{trace_id}`, calls `GET /api/v1/vehicle/state`, updates safe UI status/pending-approval summary, and reconnects without an expired cursor. The client must not infer execution success from missing events.
- Approval decision remains REST-only. There is no WebSocket decision client message and no HTTP header represented inside WebSocket JSON.

## Validation, errors, and acceptance tests

| Area | Rule / stable code |
|---|---|
| Authentication/role | `AUTH_REQUIRED` (401), `FORBIDDEN` (403) |
| Resource lookup | Unknown but well-formed `{trace_id}` is `NOT_FOUND` (404). Added by TASK-BE-OBS-001 (2026-08-10): this table originally had no not-found code, and returning `FORBIDDEN` to avoid an existence oracle would be theatre while no identity layer exists — it would also tell the caller they lack permission when what they actually have is a bad id. Revisit once RBAC lands. |
| Input/schema/range | Text 1–1,000 Unicode code points after trim; audio <=30 seconds and supported content type; otherwise `INPUT_INVALID` (422) |
| Request context | Missing/unsupported `X-Schema-Version` or missing required idempotency/session context is `REQUEST_CONTEXT_INVALID` (400/422) |
| Idempotency | Exact replay returns exact prior response; conflicting key reuse is `IDEMPOTENCY_CONFLICT` (409) |
| Approval | `APPROVAL_ALREADY_PENDING`, `APPROVAL_EXPIRED`, `APPROVAL_REPLAYED`, `APPROVAL_INVALIDATED_STATE`, `APPROVAL_INVALIDATED_PLAN`, `APPROVAL_PREDICATE_FAILED` (409 as applicable); audit/event code `APPROVAL_REJECTED` accompanies successful reject; cross-owner is `FORBIDDEN` |
| Validation/safety | Invalid tool/args/range is `VALIDATION_DENIED` (422); valid current-state prohibition is `SAFETY_BLOCKED` (409) |
| Runtime | `MQTT_UNAVAILABLE` (503), `MODEL_TIMEOUT` (504) |
| Realtime | Missing/unknown type or invalid typed payload is `WS_EVENT_INVALID`; incomplete/non-corresponding cursor is `REPLAY_CURSOR_INVALID`; old matching cursor is `REPLAY_WINDOW_EXPIRED`; handshake auth/origin/session failures close `4401`/`4403` |

Acceptance tests must prove: exactly 14 P0 interfaces are exposed (12 REST paths in OpenAPI plus the two WebSocket contracts, which OpenAPI 3.0 cannot express); unauthenticated/wrong-role access fails; POST context placement is enforced; duplicate idempotency cannot duplicate a turn, consume, group, or MQTT command; the partial unique constraint permits at most one pending approval/session and a second sensitive turn yields `APPROVAL_ALREADY_PENDING` clarification with no new artifacts/side effect; voice approval intent emits typed handoff only and IVI performs REST commit; the approval-intent turn and original command turn each have exactly one independent terminal event; reject/expiry/state invalidation/plan-digest invalidation/predicate failure use matching HTTP/event/cancel reasons and create no consume/group/MQTT; a new key against a consumed approval is rejected; reject returns `approval_status="rejected"` and `plan_status="canceled"`; ActionPlan and vehicle-state fields match canonical schemas; Citation has all required fields including resolvable `chunk_id` and bounded supported excerpt; missing/unknown WS type and invalid payloads fail; subprotocol token/signature/expiry/role/origin/session checks and `4401`/`4403` hold without token logging; cursor pair validation distinguishes `REPLAY_CURSOR_INVALID` from `REPLAY_WINDOW_EXPIRED`; voice ordering, approval wait, exactly-one final transcript, no-after-terminal rule, replay order, and deduplication hold; execution fail-fast emits skipped results and `turn.failed` while manual/RAG emits citations and no tool result; `ui.policy.payload` exactly equals the six-property canonical technical/UX object and rejects missing/additional fields; Driver trace recovery is owner-scoped/redacted; GET and Engineer WS trace schemas expose the same exact safe latency/safety/version/admission fields; a trace carries the server-composed `answer_text` and the acting `vehicle_id` while still carrying no transcript, citation body, or secret path, and `/metrics/summary` carries no text at all; approval wait is separate from stage latency; metrics GET/WS expose the documented stage/model/MQTT/RAG/safety/action aggregates; privacy tests reject raw prompts, chain-of-thought, raw audio, unrestricted transcripts, credentials, and secret paths; `/healthz` component names exactly match the eight dependencies, returns `200` when no required component is in a blocking state — including the default `slm_enabled=false` and the `MQTT_ENABLED=false` configuration, where the deliberately disabled components must still appear with `status="disabled"` — and otherwise returns a redacted `503` dependency envelope; API numeric examples remain fixtures rather than measured claims; and P1 management/full-trace/eval/model-config capabilities are not exposed as P0.

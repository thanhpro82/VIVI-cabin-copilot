# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository actually is

VIVI Cabin Copilot — an academic, **simulator-only** offline-first prototype (team P-192, DEV-01/STT 341). It is not a VinFast/VinBigdata product and must never drive a real vehicle or CAN bus.

Four things live here, and telling them apart matters:

1. **Root `src/` + `frontend/`** — the P0 product, and where nearly all current work happens. `src/` is the FastAPI backend: LangGraph agent, deterministic router, safety policy/HITL, FAISS RAG over the VF9 manual, MQTT vehicle simulator, sherpa-onnx (Zipformer) STT. `frontend/` is the Next.js 16 IVI (`/login`, `/driver`, `/engineer`). The suite is real coverage, not boilerplate — but every figure below is a **dated snapshot, not a live number**, so re-measure before quoting and quote the run you actually did.

   > **Snapshot — `develop` @ `4fb40fd`, 2026-08-16, Python 3.11.9, Windows 11 dev machine with the FAISS index and the voice models present:** `1356 passed, 17 skipped` in 70 s with `MQTT_ENABLED=false`. Wall time is not stable enough to quote as a range: the same suite has landed anywhere from ~60 s to ~240 s on one commit, depending on disk cache and whether the E5 embedder is already warm. `docs/huong_dan_chay.md` §3.5 holds the maintained reference figures and re-measures both machine states; if it and this line disagree, the runbook is newer.

   Leave `MQTT_ENABLED` at the default `true` and every `TestClient(app)` burns 10 s waiting for a broker.

   **The skip count is a property of the machine, not of the suite** — nothing is skipped by marker alone. In that run all 17 were the two tiers needing a real Mosquitto, confirmed with `-rs`: 12 L2 contract (`MQTT_CONTRACT_TESTS=1`) and 5 L3 two-process (`MQTT_L3_TESTS=1`). The `slow`/`integration` tests **run** on a checkout that has the local model assets; strip the FAISS index and the voice models and 13 more skip instead (`huong_dan_chay.md` §3.5 measured that pair as 1178/17 vs 1165/30 on 2026-08-15), and CI installs neither. A skip total other than 17 is therefore not a regression — check *which* tests skipped with `-rs` before concluding anything.

2. **`experiments/offline_poc/`** — the **SPIKE-001 archive only** (Qwen GGUF planner benchmark). Its decision is **Not Yet**; it is not on the delivery path anymore. Keep it for evidence and for the techniques `src/agents/router.py` inherited from it. Do not add features here.
3. **SPIKE-002 (hybrid resident pipeline)** — exists **only on `origin/feature/hybrid-architecture-resident-pipeline`, never merged into `develop`**. `spike2_cli.py`, `control_router.py`, `hybrid_e2e.py`, `voice_runtime.py`, `eval/results/spike-002/` and every `run_spike2.ps1` stage are **absent from this working tree**. If a task mentions them, check out that branch first or the commands will not exist.
4. **Leftover course boilerplate** — `Makefile`, `ARCHITECTURE.md`, and `POST /api/v1/chat` + `GET /api/v1/status` in `src/api/routes.py`. (`README_boilerplate.md` was an unfilled template and was deleted 2026-08-26.) `ARCHITECTURE.md` is a **product-vision (Họ A) doc**, reconciled against the tree on 2026-08-26 — it no longer claims the `speed > 5 km/h` gate, ChromaDB, Faster-Whisper, or the seven `control_*` aliases, but it is still not the architecture: cite `docs/` (authoritative) instead. Note the Makefile's `run` target uses `uvicorn src.main:app`, which breaks MQTT on Windows (see Commands). `GET /api/v1/status` is no longer dead weight: `docker-compose.yml` points the backend healthcheck at it.

Separately, `POST /api/v1/agent/process` (`src/api/agent_routes.py`) is a **dev-only** route — `include_in_schema=False` and 404 in production — deliberately outside the 12 P0 interfaces. A large share of the API tests drive the agent through it, so it is load-bearing for the suite even though no client may depend on it.

The five-service P0 topology named in `README.md` (`ivi-web`, `backend`, `llm`, `mqtt`, `vehicle-simulator`) is **partially real**: `docker-compose.yml` implements three (`mqtt`, `vehicle-simulator`, `backend`). `llm` and `ivi-web` are still **Planned**.

## Commands

**The team runs Python 3.11.9, and it is the only version this repo is actually validated against.** Both CI workflows pin `python-version: "3.11"` (`.github/workflows/ci.yml`, `mqtt-contract.yml`), `pyproject.toml` declares `requires-python = ">=3.11"`, and `ruff` targets `py311`. That is the fixed part. The **folder name is not** — see below before copying any command.

**There is exactly one venv, `.venv`, and it runs 3.11.9** (`.\.venv\Scripts\python.exe -V` on the dev machine, 2026-08-16). The old `.venv311` is gone — it *was* the 3.11 venv here while `.venv` held a leftover 3.13.7; that split was resolved by deleting the 3.13.7 tree and renaming `.venv311` to `.venv`, so the six scripts that hard-code `.venv` now hit the CI interpreter too.

**But never trust the folder name — no venv crosses git.** `.gitignore:15` ignores `.venv*/`, so a rebuild changes exactly one machine and leaves every other one silently on whatever it had. This is not hypothetical: PR #114 documented "exactly one venv on 3.11.9" while this machine still had `.venv` = 3.13.7 for two more days, and following that document would have run the whole suite on the wrong interpreter. Any claim about which folder holds which version — this paragraph included — is a claim about one machine at one moment. Settle it yourself:

```powershell
.\.venv\Scripts\python.exe -V   # must print 3.11.9
```

Renaming a venv is not free, in case this comes up again: every Python-based `.exe` in `Scripts/` embeds an absolute shebang, so all 45 of them (plus `activate`, `activate.bat`, `pyvenv.cfg`) break on rename and must be patched or reinstalled. `ruff.exe` survives because it is a standalone Rust binary, which is exactly why a green `ruff` proves nothing about the rest.

**Seven `.ps1` scripts hard-code `.venv`** — `scripts/prepare_vf9_index.ps1`, `scripts/spike3_server.ps1` (PR #114), `scripts/run_slm_server.ps1`, and four under `experiments/offline_poc/scripts/`. They are correct now only because `.venv` *is* the 3.11 venv; they have no version check of their own, so they will happily run on whatever a future `.venv` turns out to be. (The `.venv` strings in the `scripts/*.py` docstrings are usage examples, not invocations — those files do not care which interpreter starts them.)

This matters more than tidiness: a local-only 3.13 venv is exactly what let `asyncio.run(main(), loop_factory=...)` (a **3.12+** parameter) ship in `src/vehicle_sim/__main__.py` and `scripts/smoke_mqtt.py`, which blew up with `TypeError` on 3.11 and blocked the whole L3 tier until 2026-08-12. Anything that runs only under 3.13 is broken, not ahead. `src/serve.py` documents the same trap; follow its pattern (`ensure_selector_event_loop()` then a bare `asyncio.run(...)`).

The 3.11-vs-3.13 A/B for the flaky-test investigation (**issue #67**) now needs a throwaway 3.13 venv built on demand. That is the right shape for it: a permanent second venv is what let the `loop_factory` bug hide in the first place.

```powershell
# Install. `rag` extra pulls torch (~2 GB) and is NOT installed on CI.
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt   # only for real RAG work
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"             # sherpa-onnx (Zipformer) + piper

# Run the backend. On Windows use THIS, not `uvicorn src.main:app`:
# uvicorn picks ProactorEventLoop, which lacks add_reader/remove_writer that
# paho-mqtt needs, so every MQTT connection raises NotImplementedError.
# See src/serve.py. In the Linux container plain uvicorn is fine.
.\.venv\Scripts\python.exe -m src.serve

# Tests (root). ~60 s. MQTT_ENABLED=false is not optional for speed: at the default
# `true` every TestClient(app) runs lifespan and waits 10 s for a broker that is not there.
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_policy.py::test_name -q

# Lint (line-length 120, select E/F/I/N/W/UP, E501 ignored).
# `scripts/` is NOT optional: `ci.yml:44` runs exactly this, and a lint error there
# fails the build while a local `src/ tests/` run stays green. That gap cost a CI
# round on PR #268 (an I001 import-order error in a file the narrower command skipped).
ruff check src/ tests/ scripts/

# `ruff format` is NOT gated by CI, and the tree has drifted away from it: on develop
# @ bab0fc6 (2026-08-26) `ruff format --check src/ tests/` reports 42 files would be
# reformatted. So running `ruff format` reformats 42 files nobody asked you to touch,
# and burying a real change inside that diff is how a review stops being a review.
# Format only the files your change already touches, or leave it alone.

# Frontend
cd frontend; npm run dev    # mock-first by default; no .env needed
cd frontend; npm run test   # Vitest — mandatory when touching lib/services/
cd frontend; npm run lint   # eslint
```

Every service in `frontend/src/lib/services/` ships a `mock.ts` and a `real.ts` behind an
`index.ts` switch that defaults to the mock. There are **five** such switches, not three —
`NEXT_PUBLIC_USE_MOCK_TURN`, `_SESSION`, `_ENGINEER`, `_PLACES`, `_ROUTINES` — and real mode
needs **every one** set to `false`. A screenshot proves nothing about the backend unless all
of them are off; `frontend/.env.example` is the authoritative list, and `.env.local` is
gitignored so each machine can be missing a different subset.

This line said "all three" until 2026-08-30, and that wording cost a debugging session: on a
machine whose `.env.local` set only those three, the driver saved a Work location through the
UI and `user_places` stayed **empty** — the save went into the in-browser mock. Meanwhile the
Routines list on screen came from `_ROUTINES`'s mock while a voice turn read the real DB, so
**the list the user sees and the list the car knows are two different lists**. Nothing errors;
the screen just disagrees with the car. Check the flags before believing either one.

**Before believing anything you see at `localhost:3000`, check for a foreign service worker.** A service worker registered by *any other project* that once ran on port 3000 keeps its scope `http://localhost:3000/` and intercepts every navigation — so the browser renders that project's cached shell while the VIVI dev server never receives a `GET /`. What this looks like: the page renders (SSR HTML is cached), React never hydrates, clicks do nothing, no console error, and the terminal shows only the `POST /api/auth/demo-driver` that `fetch()` made (service workers pass through what they don't cache). Measured 2026-08-20: `hanzi-master-v1` from an unrelated app silently ate every manual FE test on this machine. Clear it before testing, in the page console:

```js
(await navigator.serviceWorker.getRegistrations()).forEach(r => r.unregister());
(await caches.keys()).forEach(k => caches.delete(k));
```

Two more things that make browser measurements lie, both hit on the same day. A **hidden/backgrounded tab** (`document.visibilityState === "hidden"`) has its timers throttled and media loading deferred, so `setTimeout` deadlines never fire and an `Audio` sits at `readyState 0` forever — no timing measured there is real; bring the window to the foreground first. And **autoplay is not blocked on a profile that has already played audio on the origin** (Chrome's Media Engagement Index), so "audio blocked" cannot be reproduced by simply not clicking — emulate it by making `play()` reject with `NotAllowedError` and say in the report that you did.

The `slow` and `integration` markers are **not** skipped when you run `pytest tests/` locally; nothing in `pyproject.toml` deselects them. **CI** is what deselects them (`-m "not slow and not integration"` in `ci.yml:41`, since the `rag` extra and the voice assets are not installed there). On a dev machine that has the FAISS index and the voice models, those ~13 tests run and pass as part of a normal local run — which also means the RAG-integration and voice-integration evidence is produced *only* by someone running locally, never by CI.

The MQTT test tiers stack, and each one's blind spot is what the next exists to cover — the taxonomy is machine-readable in `_BLIND_SPOTS` (`scripts/report_mqtt_e2e.py`), not just prose:

| Tier | What runs | What it still cannot prove |
|---|---|---|
| L0 unit | pure functions | nothing about transport |
| L1 in-memory | `InMemoryBroker`, fully deterministic | QoS 1 duplicates, retain, ACL, LWT, reconnect |
| L2 contract | real Mosquitto, one pytest process | no real HTTP/WS; backend and simulator are not separate processes |
| L3 two-process | `python -m src.serve` + `python -m src.vehicle_sim` as real processes, real sockets | Docker images, the Compose topology, network partitions, multiple vehicles |

L2 and L3 read their broker URL and credentials through `get_settings()`, so they follow `.env`. Reading `os.getenv` directly was a real bug: on a machine where something else already holds port 1883 (hence `MQTT_HOST_PORT`), L2 silently connected **anonymously to the wrong broker** and reported ACL findings about it.

**Two rules for websocket tests, both learned from a deadlock that hung the entire suite** (`test_events_that_arrive_while_replay_batch_is_still_sending_stay_in_order`, fixed 2026-08-11):

1. **Publish into the app's loop, never into a new one.** A test thread calling `anyio.run(...)` around `bus.publish()` creates a *second* event loop, while the websocket lives on the TestClient portal loop. `publish()` awaits straight into `push()` → `websocket.send_json()`, so the cross-loop wakeup of a receiver waiting on an anyio memory stream is lost and the read never returns. Use `ws.portal.call(coro_fn)` — built for calling from another thread, and it reproduces the intended interleaving better, since the live event now lands on the `await` points of the `pending_live` flush loop. Publishing via `anyio.run` is safe only when the test publishes *then* reads: the message is already buffered and nobody needs waking.
2. **Every websocket read in a test needs a deadline.** `TestClient.receive_json()` is `portal.call(...)` and blocks with no timeout, so one missing event hangs pytest forever instead of failing. Read in a `daemon=True` thread with `join(timeout=...)` and assert on `is_alive()` — the daemon flag matters, or the stuck thread keeps the process alive at exit.

The suite is not slow *because* of RAG, but the first test that touches manual lookup pays ~32 s to load the E5 embedder (`@lru_cache` in `src/agents/nodes/rag_node.py`), so a single such test run alone looks alarmingly slow while the whole suite is not.

### RAG manual index

```powershell
.\.venv\Scripts\python.exe -m src.rag.cli ingest     # build chunk store + FAISS index
.\.venv\Scripts\python.exe -m src.rag.cli verify     # print manifest, check quality gates
.\.venv\Scripts\python.exe -m src.rag.cli query "..."
.\.venv\Scripts\python.exe -m src.rag.cli eval
.\scripts\prepare_vf9_index.ps1
```

Source data is `data/manuals/vf9_2026_vi/` (VF9_23-25_VN_VI_2.4: 58 documents → 482 chunks). Results land in `eval/results/rag/<UTC-run-id>/`.

### Router / intent evaluation

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode intent    # -> eval/results/agent-intent/
.\.venv\Scripts\python.exe -m src.agents.eval --mode routing   # -> eval/results/agent-routing/
```

**The two datasets are not interchangeable.** `eval/datasets/agent/v3` was written by the same person who wrote the router, so its `intent_accuracy` of 1.0000 is a **regression tripwire only** — it says nothing about generalization. `eval/datasets/manual/v1` was written by the RAG workstream for an unrelated purpose, so the 0.9833 question-reaches-RAG figure carries more weight. Neither passes through ASR, so neither reflects speech-recognition error. Never present them as user-facing accuracy.

### MQTT and the vehicle simulator

```powershell
# Run ONCE before `docker compose up`. docs/devops.md requires
# MQTT_ALLOW_ANONYMOUS=false with two separate identities; this writes
# config/mosquitto/passwd, which must never be committed.
pwsh scripts/bootstrap_mqtt_secrets.ps1

docker compose up -d --wait mqtt vehicle-simulator
.\.venv\Scripts\python.exe scripts\smoke_mqtt.py
.\.venv\Scripts\python.exe scripts\validate_mqtt_schemas.py   # checks schemas/mqtt/
.\.venv\Scripts\python.exe -m src.vehicle_sim                 # simulator standalone

# Tiers that need the broker. L3 spawns `src.serve` + `src.vehicle_sim` itself.
$env:MQTT_CONTRACT_TESTS="1"; .\.venv\Scripts\python.exe -m pytest tests/test_vehicle/test_contract_mosquitto.py -q
$env:MQTT_L3_TESTS="1";       .\.venv\Scripts\python.exe -m pytest tests/test_vehicle/test_l3_two_process.py -q

# The deliverable is the run directory, not the test file — see "Evidence is the product".
.\.venv\Scripts\python.exe scripts\report_mqtt_e2e.py --with-contract --with-l3
```

`--wait` matters: both `backend` and `vehicle-simulator` gate on `mqtt`'s healthcheck, and that healthcheck must prove *connect + auth* only (`mosquitto_sub -E`). It must never wait for a message to arrive — no topic the backend identity may read carries traffic before the simulator starts, and the simulator is itself gated on this healthcheck. `tests/test_vehicle/test_compose_healthcheck.py` locks both halves of that, for `docker-compose.yml` and the CI workflow alike.

### SPIKE-001 archive (`experiments/offline_poc/`)

```powershell
& '..\..\.venv\Scripts\python.exe' -m offline_poc.runner validate   # 3 profiles, 2 required, 30 cases
& '..\..\.venv\Scripts\python.exe' -m offline_poc.runner cases --profile <id> --all
.\scripts\run_e2e_demo.ps1 -Profile qwen25-3b-q4 -AudioPath <wav>
```

`scripts/download_models.ps1` downloads exactly one pinned profile per invocation and writes `.sha256` + `.metadata.json`. Never batch-download; Qwen 3B is under the Qwen Research license.

## Architecture that spans files

### The P0 turn pipeline

```
POST /api/v1/turns/voice  (202, async)   |  POST /api/v1/turns/text  (sync envelope)
  → sherpa-onnx (Zipformer) STT + Vietnamese correction layer   src/services/voice*.py  (voice only)
  → LangGraph StateGraph                                src/agents/graph.py
      normalize → route → [slm fallback] → validate → safety → [approval] → execute → compose
  → deterministic rule router                           src/agents/router.py
  → safety classification S0–S3                         src/agents/policy.py
  → HITL approval store                                 src/agents/approval.py
  → tool registry → MQTT command                        src/services/tool_registry.py, mqtt_client.py
  → vehicle simulator + state cache                     src/vehicle_sim/, services/vehicle_state.py
  → lifecycle events pushed to /ws/ivi                  src/services/ivi_events.py, src/api/ws.py
```

**No LLM runs on this path by default.** `slm_enabled` defaults to `False` (`src/config.py`), so routing is 100% deterministic rules per ADR-006/ADR-010 on every checkout as shipped. Turning the flag on wires two *different* SLM roles (ADR-016 Accepted 2026-08-12): `QwenPlanner` proposes a plan for utterances the rules could not match, and `QwenLeadIn` writes the opening sentence of a manual answer. Real Qwen weights **have** been run against both paths on the demo machine (SPIKE-003, `eval/results/spike-003/`) — the older claim that only stubs were ever used is obsolete. Still do not describe the system as "running Qwen offline" without saying which role and that the flag is off by default.

### Non-negotiable invariants (encoded in Pydantic validators and tests)

- **Two plan types, one direction.** Router and SLM may only produce a `CandidateActionPlan`, which has **no** safety field (`src/agents/contracts.py`). Only `src/agents/policy.py` — the single place in the system that assigns `safety_level` — turns it into the canonical `ActionPlan`, which refuses to validate if an S2 step lacks `requires_approval`. No other node may import `ActionPlan` to build one.
- **Safety levels S0–S3.** S0 read-only, S1 executes after policy, S2 requires HITL, S3 is blocked before HITL. Door and seat-position are S2 **only** when `speed_kph == 0 && gear == P`; otherwise S3. Window is always S2. Unknown tool / bad schema / out-of-range stops earlier at `validation_denied` and is **not** S3.
- **The `speed_kph > 5` threshold in `docs/VIVI_API_Spec.md` is not implemented and must not be.** ADR-010 supersedes it: it is simultaneously looser than canonical for windows and more dangerous for doors. `docs/safety_and_hitl.md` is the classification source.
- **HITL fails closed.** Expiry (≥30 s, detected at read time via CAS), rejection, and any `state_version` mismatch all route to compose with zero side effects. Approvals are single-use (`consume()` only goes `approved → consumed`), plan-bound, and at most one may be pending per session. `approval_id` is derived deterministically with length-prefixed components because LangGraph re-runs node bodies on resume.
- **`RouteDecision` is exclusive.** `disposition == "control"` requires a `candidate_plan`; `offer`/`not_control`/`clarify`/`denied` forbid one. `offer` exists so that a question matching a control rule states its intent and asks back instead of touching the executor — that is why `question_to_control` is structurally 0, not tuned to 0 (ADR-011).
- **One vehicle-state source.** Per ADR-013 the simulator's published snapshot is authoritative and the backend only forwards it — no field is re-mapped or re-derived on the way out of `GET /vehicle/state`, and the route fails with `MQTT_UNAVAILABLE` (five distinguishable `reason`s) rather than serving a guess.
- **Driver-stream ordering.** Per ADR-014 `sequence`/`event_id` belong to the **session**, not the connection, so a reconnect continues the numbering. Buffered events must be flushed completely before live delivery resumes (`ivi_events.py` flushes `pending_live` in a `while` loop *before* flipping `replay_done`) — the inverse order was a real bug that a green suite missed.
- **No network at runtime.** No cloud calls, no auto-download of model artifacts.
- Tool names are **canonical end-to-end** — identical in `ActionPlan`, trace, and HTTP response. The Family-A alias table (`control_ac`…) was dropped 2026-08-08; `docs/api_spec.md` is the single source of truth.

### Where the implementation still falls short of the spec

Future work should start from this list rather than assuming the P0 surface is complete. Verified against the tree, not from the docs' own claims:

- **All 13 P0 interfaces in `docs/api_spec.md` exist** (`GET /citations/{citation_id}` landed in PR #59 — `src/api/citation_routes.py`, registered in `src/main.py`, 8 tests in `tests/test_api/test_citation_routes.py`; verify with `app.openapi()['paths']`, not by grepping `app.routes` for `.path`, which returns nothing useful here). The count is **14, not 12**: issue #123 added `GET/PUT /api/v1/vehicle/profile`, and the equipment-profile work added the sub-resource `GET/PUT /api/v1/vehicle/profile/options` (65-entry curated catalogue at `src/safety/trang_bi.json`, survey in `docs/khao_sat_trang_bi.md`). Both widenings are deliberate and argued in `api_spec.md` under the interface table. Older docs, reports and plan files still say 12 or 13; they describe the surface before those dates and are not being rewritten. Interface presence is not feature completeness: see the gaps below.
- **Auth is now enforced uniformly across the P0 surface.** `POST /auth/login` (`src/api/auth_routes.py`) issues a bearer token against two hard-coded demo users in `src/services/auth.py` (`usr_driver_01` driver, `usr_engineer_01` engineer). `require_driver` (`src/api/auth_deps.py`) guards `/sessions`, `/turns/text` and `/approvals/{id}/decision`, and — as of this branch (`fix/turns-voice-auth-hardening`) — `POST /turns/voice` too, layered with session-ownership, `require_schema_version`, and `require_idempotency_key` checks in `src/api/turns.py`. The three holes an earlier revision of this file described here are all closed: `require_engineer` exists (`src/api/auth_deps.py:67`) and guards `/traces` and `/metrics/summary` via `_ENGINEER_ONLY = [Depends(require_engineer)]` in `src/api/observability.py`, replacing the old no-op; and both WebSockets decode and validate the `bearer.<token>` subprotocol value against the auth store, rejecting with `4401`/`4403` on a missing/invalid token or wrong role (`src/api/ws.py`, see `_authenticate_ws_connection` and `_decode_bearer_subprotocol`). What still protects an approval is server-side ownership (unguessable `approval_id` plus `approval_not_owned`) — a capability, now layered under full authentication rather than partial.
- **Users, sessions, approvals and idempotency records now persist to SQLite** (issue #46, ADR-017): four tables in `src/db.py`, one process-wide connection (`get_connection()`), `sqlite3` stdlib only. Two invariants moved *into the database* rather than merely surviving restart — the one-pending-approval-per-session partial unique index, and the idempotency reservation, which is now a single conditional upsert adjudicated by `rowcount` (an `asyncio.Lock` only serialises one event loop). `sessions.user_id` is a real FK, so tests that need a session owned by somebody else call `seed_test_user()` (`tests/conftest.py`). Sessions expire after `session_ttl_hours` (24 h, longer than the 12 h token TTL) and rows are purged after `session_retention_days` (30 d, the retention `data_model.md:43` already fixed); expiry is detected at read time by `get_session_record`, which returns `None` so all four call sites answer the same `403 FORBIDDEN` they already give for someone else's session — no separate "expired" code, because that would re-open the enumeration leak those routes deliberately close. **Passwords are PBKDF2 hashes in the `users` table, but the seed credentials still live in source** (`DEMO_USERS`); do not describe them as having left the codebase. **Issued tokens are still in-memory on purpose** — `data_model.md` designs no table for them. Two things the persistence layer does *not* buy you: `action_plans`/`plan_steps` still do not exist, so the **atomic plan+approval transaction of `docs/safety_and_hitl.md:42` is still unmet**; and the *record* survives restart but the **turn does not**, because `session_state.get_graph()` uses `InMemorySaver` and the checkpoint holding `interrupt()` dies with the process (hence `invalidate_orphaned_pending_approvals()` fails those approvals closed at startup). Nothing has been run on two workers. `tests/conftest.py` points `DATABASE_URL` at `sqlite:///:memory:` and lowers `AUTH_PBKDF2_ITERATIONS` — at the 200 000 default, hashing alone adds ~9 s to a suite run.
- **Driver WS emits 14 of the 16 allowlisted event types** (`docs/api_spec.md` §Driver server-event allowlist). Missing: `transcript.partial`, `approval.intent.detected`. `ui.policy` landed with the driver-safety-UI work (`src/services/ui_policy.py`) and has two halves that must both exist: edge-triggered on vehicle state, plus one emission right after handshake — a driver connecting mid-drive would otherwise get no policy until the next change. The listener is registered through `add_persistent_state_listener` and **not** `get_vehicle_gateway().add_listener`, because `lifespan` swaps the gateway and a listener bound to the old instance dies silently while every test stays green. `approval.intent.detected` means **voice approval is not implemented** despite "voice-first HITL" in the brief. (`plan.ready` landed with the HITL PR and is emitted from `src/services/ivi_events.py`, not from `turns.py`; `error` is emitted by `src/api/ws.py` on handshake rejection; `assistant.speech` landed with issue #66, best-effort TTS audio before `assistant.response`.)
- **`/ws/ivi` survives reconnects, `/ws/engineer` does not.** Per ADR-014 the driver stream wraps every event with a session-scoped `event_id`/`sequence`, keeps a 200-event ring buffer, and answers `connection.init` cursors with replay (`REPLAY_CURSOR_INVALID` / `REPLAY_WINDOW_EXPIRED`; buffer TTL 30 min, stream metadata TTL 24 h). The server side is done and tested; **the client never sends `last_event_id`/`last_sequence`** (`frontend/src/lib/services/turn/real.ts`), so replay is unobservable in a live demo.
- **Engineer WS emits all 5** since `docs/tasks/TASK-BE-OBS-001-engineer-observability.md`. Trace data is collected by a listener on `IviEventBus` (`src/services/trace_collector.py`), never by editing `emit_turn_lifecycle` — that also catches the two error exits in `turns.py` which bypass it. `/metrics/summary` holds no counters; it is a pure fold over `TraceStore`. Two P0 truths surface as data rather than absence: `model_runtime` is `"not-selected"` with null percentiles (no LLM on the path), and `stage_latencies_ms.tts` is non-null only on turns where TTS synthesis succeeds (issue #66) — it stays `null` on turns with no speech or a failed synthesis, and it is not folded into `end_to_end` (recorded before TTS runs). Metrics use a server-chosen rolling 1 h window and accept no query params — `api_spec.md` was silent on all of that, so the decisions are recorded in it and in the task doc.
- **Piper TTS is wired into the turn pipeline** (issue #66): `emit_turn_lifecycle` (`src/services/ivi_events.py`) calls `voice.synthesize_wav()` off the event loop thread and publishes a new `assistant.speech` WS event (`audio_base64`/`mime_type="audio/wav"`) immediately before `assistant.response`, fail-open on any TTS error. `speak_text` in `assistant.response` is still text-only (unchanged, closed schema). **The frontend now plays it** (written in PR #82 `feat/fe-tts-audio-playback`, commit `fb90170`; PR #91 `fix/fe-driver-async-ux` is the integration PR that carried #82 and #88 into `develop`, so cite #82 for the behaviour and #91 only for the landing date): `DriverShellProvider.tsx` handles `assistant.speech` and builds `new Audio('data:<mime>;base64,...')`, pausing the previous clip first — back-to-back turns (spamming "tăng điều hòa") otherwise overlap two voices. Browser autoplay policy can still block the first `play()` before any user gesture; the rejection is swallowed and the text path is unaffected.
- **STT accepts only WAV.** `audio/ogg` and `audio/pcm` are in the contract and accepted by the route (`_ALLOWED_BASE_CONTENT_TYPES` in `src/api/turns.py`), but `src/services/voice.py` parses WAV via stdlib `wave`, so those turns always end at `transcript.final(unusable)`.
- **The IVI records real audio now** (written in PR #88 `feat/fe-voice-mic-capture`, commit `217cb55`, landed via the same integration PR #91; VAD added later by PR #99), so the microphone → STT → TTS → speaker chain is closed end to end for the first time. `frontend/src/lib/audio/wavRecorder.ts` captures via `getUserMedia` + an `AudioWorkletNode` (`frontend/public/worklets/pcm16k-recorder.js`) and encodes **16-bit PCM mono 16 kHz WAV** in the browser. `stopVoice()` sends the real blob through `turnService.sendVoice(wavBlob)`; the older `new Blob()` placeholder is gone. Three choices there are load-bearing and were learned from real hardware, not from reading code — do not "simplify" any of them away:
  - `MediaRecorder` is deliberately unused: no browser writes WAV, it emits webm/opus or mp4/aac, which `_validate_audio` rejects outright (see the STT item above).
  - The `AudioContext` is requested at `sampleRate: 16000` because `src/services/voice.py` demands exactly 16 kHz mono; a 44.1/48 kHz take fails with `"audio must be 16kHz mono WAV"` — a *different* failure from the container one. `resampleLinear()` is only a safety net for browsers that ignore the option.
  - `ScriptProcessorNode` had to be abandoned: Chrome suspends it after ~2 s when the graph reaches destination through a silent gain node, truncating the recording while the overlay still showed "đang nghe".

  Recording auto-stops after `SILENCE_DURATION_MS` (900 ms) of silence once speech was actually detected (RMS ≥ 0.02, `createSpeechEnergyTracker`), bounded by `MAX_RECORDING_MS` (12 s); a take that never crossed the speech threshold is not sent to the backend at all. Two caveats survive: `transcript.partial` is still never emitted, so the transcript appears in one shot (`MIN_TRANSCRIPT_VISIBLE_MS` = 2000 ms holds it on screen before the answer replaces it, because simple commands finish in milliseconds and React would otherwise batch both into one paint); and the *quality* end is unverified — no human-speaker WER, no end-to-end latency measurement on the full mic-to-speaker path.
- **7 of the 19 required safety tests** in `docs/safety_and_hitl.md` are covered (`tests/test_agents/test_hitl_safety.py`: #1, #2, #4, #5, #6, #12, #17).
- **`search_nearby_poi` now runs end to end** (issue #371, 2026-08-29): it has a router matcher (`_match_tim_poi`, SP-5), a real executor (`nodes/execute.py::_ket_qua_tim_poi`, which returns the POI list in `after` rather than an empty dict), an S0 classification (`policy._S0_TOOLS`), and a composer that builds its sentence **from that result**. It left `KHONG_CHO_DUONG_PLAN` in the same change. Before that it was excluded from the plan path while the router still emitted a plan for it, so plural searches ("tìm **các** quán cà phê") died at `validate_args` with `tool_not_allowed` yet still read the list aloud and asked "Bạn muốn đi chỗ nào?" — a failed turn that sounded successful. The turn after it now works too (#355 item 2b): the list the car **spoke** is remembered in `cho_chon_poi` (loaded by `compose_node`, cleared by `route_node` on every other turn), so "cái đầu tiên" / "chỗ thứ hai" / "Highlands" / "chỗ gần nhất" all resolve to a `set_navigation` plan that still goes through policy. Ordinal beats alias on purpose — `"thứ hai"` is a real alias of `poi-cafe-02`, so matching names first would send the driver to the place they just declined. One limit remains: the search runs over the 8-POI fixture, not a real map, and `set_navigation` reaches only fixture ids.
- **The control surface is a closed set, and `docs/coverage_matrix.md` is the honest map of it** — 15 tools over 9 domains (8 commandable; 12 of the tools are actuators, the other 3 are S0 reads with no domain), covering 6 of 11 conventional automotive voice-command groups, all of them partially. Issue #65 (PR #92) added `lights` and `trunk`, plus `set_hvac_fan_level` and `media_control: previous`, which is what moved the group count from 5 to 6. Read the matrix before promising a demo scenario: because ADR-011 defaults unmatched speech to manual lookup, the system *answers* about fog lights, cruise control and Camp Mode while being unable to *do* any of them. Two traps specific to the new domains: **`set_headlight_mode` has no `off`** — ADR-020 removed it because UNECE R48 forbids a manual off on a car with DRL, so `"tắt đèn pha"` returns `denied`, which is the design and not a bug; and fan level is **absolute only** — the router does not read vehicle state, so `"tăng quạt gió"` returns `clarify` and the client has to compute the level itself.
- **The composer quotes verbatim; it deliberately does not synthesize.** Manual lookups now return a lead-in plus the **verbatim text of the top evidence chunk** (`_quote_top_evidence` in `src/agents/nodes/compose.py`), cut at a sentence boundary with a visible "còn tiếp" marker past `QUOTE_MAX_CHARS`. Source is `evidence[0].text`, **not** `citation.excerpt` — the latter is capped at `EXCERPT_CHARS = 300` while 39/40 real chunks are longer, and truncating is exactly how the manual's version qualifiers get lost. `compose_grounded_answer` from `agent_spec.md` stays unwritten **on purpose**: ADR-015 (Accepted) records that having the SLM rewrite a chunk measured 4/40 misleading answers, all from dropped variant conditions (ECO/PLUS, SDI/CATL), against 0/40 for quoting.
- **No end-to-end latency, offline-drill, or user-research evidence exists.** The p50 ≤ 2.500 ms / p95 ≤ 4.500 ms targets, the network-disabled drill, and both required user-research rounds are unmeasured. The 5.6 s figure in older reports is SPIKE-001's, from a different pipeline — do not reuse it.

### Evidence is the product

`eval/results/<suite>/<UTC-run-id>/` directories are **immutable**: `agent-intent/`, `agent-routing/`, `rag/`, `mqtt-e2e/` (written by `scripts/report_mqtt_e2e.py`), `spike-001/`. A run holds `manifest.json`, `case_results.jsonl`, and `metrics.json` (SPIKE-001 runs carry more). Never hand-edit them; regenerate by re-running the CLI, which writes a new run id.

- `.gitattributes` forces LF on text (`* text=auto eol=lf`, plus explicit rules for `.py/.json/.jsonl/.md/.ps1/.sha256`) and marks `.wav/.png/.jpg/.jpeg/.ico/.bin` binary, so checksums stay stable across Windows/Linux checkouts. `.png` is in that list because `VF9_2026_vi/corpus.sha256` checksums image assets, not just audio. One exception, and it must stay last in the file to win: `VF9_2026_vi/manifest.json -text` keeps its source CRLF, because that same `corpus.sha256` covers it byte-for-byte. Don't relax any of this — until 2026-08-15 the file held **only** that one exception while this list claimed otherwise, which left 149 `.wav` and 23 `.png` protected by nothing but git's binary heuristic on machines running `core.autocrlf=true`.
- Hard gates apply **before** ranking: a cloud call, schema miss, safety violation, duplicate actuator execution, invalid citation, RAM miss, or latency miss disqualifies a candidate regardless of weighted score.
- Passing unit tests are not model-quality or latency evidence, and synthetic Piper audio is not human-speaker WER. Every quantitative claim must trace to a run id.

### Documentation is authoritative and status-typed

`docs/` holds the product specs, `docs/adr/ADR-0{01..14}` the decisions, `docs/tasks/` the implementation handoffs, and `docs/superpowers/specs/` + `docs/superpowers/plans/` the per-feature design doc and TDD plan written before each ticket (read the matching pair before touching a subsystem). `docs/coverage_matrix.md` is the current-state map of what the system can actually control, verified against code rather than against other docs. Much of it is Vietnamese; specs mix Vietnamese prose with English contract terms.

Every claim in `README.md` carries an explicit status (**Planned** / **Not Yet** / **Chạy được trên PC**) and a link to generating evidence. Preserve that discipline — do not upgrade a status without the artifact that justifies it, and do not silently widen a documented scope boundary (PC ≠ Jetson; synthetic ≠ human; in-team evaluator ≠ user; unit test ≠ latency evidence).

`WORKLOG.md` (daily, per member) and `JOURNAL.md` (weekly, per-week plan and decisions) are graded deliverables — update them when work lands, in the existing table/section format. `frontend/PROGRESS.md` is generated by a post-commit hook; never edit it by hand.

## AI usage logging — do not touch

Prompt logging into `.ai-log/session.jsonl` is fully automated by git pre-push hooks (`scripts/log_hook.py`, `scripts/log_antigravity.py --auto`, `scripts/submit_log.py`) and by the Claude Code hooks in `.claude/settings.json`. Per `.agents/rules/ai-log-hook.md`:

- Never call `scripts/log_antigravity.py "<summary>"` or `scripts/log_manual.py` yourself — that forges fake entries.
- Never edit or delete files in `.ai-log/`.
- If a pre-push hook fails, report it; do not bypass with `--no-verify`.

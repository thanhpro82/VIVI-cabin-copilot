# Design: `GET /healthz` — 8-component readiness endpoint

Status: approved for implementation planning
Date: 2026-08-09

## Context

`docs/devops.md` §Readiness contract and `docs/api_spec.md` §Health already pin the full contract: exactly eight component names (`backend`, `llm`, `mqtt`, `vehicle_simulator`, `stt`, `tts`, `rag_index`, `sqlite`), three states (`ready`/`degraded`/`down`), per-component probe semantics, and the rule that `GET /healthz` returns `200` only when all eight are `ready`, otherwise the common redacted `503` error envelope. This design is about wiring that already-approved contract to the real `src/` code, not re-deriving it.

`src/main.py` currently exposes an ad-hoc `GET /health` that checks only two components (`mqtt`, `vehicle_simulator`) in a non-spec response shape. That endpoint is replaced outright by `/healthz`; its two checks are absorbed as two of the eight probes.

## Architecture

- **`src/services/health.py`** (new): eight async probe functions, one per component. Each returns `(status: Literal["ready","degraded","down"], latency_ms: float, detail: str | None)`.
- **`src/api/health.py`** (new): `GET /healthz` router. Runs all eight probes concurrently via `asyncio.gather`, with a per-probe timeout so one hung dependency cannot hang the whole endpoint. Assembles the response per `docs/api_spec.md`'s Health schema and returns `200` (all ready) or `503` (common error envelope, `error.details.dependencies` holding the same eight names with redacted status/probe code — no credentials or filesystem paths).
- Mounted at root (`/healthz`, no `/api/v1` prefix), matching `docs/devops.md`'s literal target URL and the current `/health` mount point.
- Response envelope matches the existing pattern used by `src/api/routes.py::vehicle_state` (`{"data"|"error", "meta": {"request_id"}, "trace_id", "schema_version"}`).

`GET /health` is removed; `tests/test_api/test_routes.py::test_health` is rewritten against `/healthz`.

## Per-component probes

| Component | Probe | Reuses |
|---|---|---|
| `backend` | Trivial event-loop self-check (`await asyncio.sleep(0)`); ready unless the process itself is broken | new |
| `llm` | `down` immediately if `settings.slm_enabled` is `False`. Otherwise call the local SLM endpoint's own readiness (llama-server `GET /health` / `GET /props`) within `slm_timeout_s`, confirm the configured `slm_model_id` is loaded | `src/agents/slm.py::QwenPlanner`'s endpoint config |
| `mqtt` | Reuse `MqttRuntime.connected` (transport-level; authenticated at CONNECT time). This is a connection-state proxy, not a live round-trip ping on every call — a true ping/ack health topic is out of scope for this task | `src/services/mqtt_runtime.py` |
| `vehicle_simulator` | Reuse `runtime.cache.simulator_ready()` | `src/services/vehicle_state.py` (docstring already names this as the healthz basis) |
| `stt` | Lazy-load `get_stt_engine()`, transcribe a small bundled fixture WAV. Result cached for `health_voice_probe_ttl_s` (default 10s) to avoid repeated Whisper inference under frequent polling | `src/services/voice.py` |
| `tts` | Lazy-load `get_tts_engine()`, synthesize a short fixed string. Result cached for `health_voice_probe_ttl_s` | `src/services/voice.py` |
| `rag_index` | Load manifest + checksum, open the FAISS index, run one fixed smoke query via `load_retriever()` | `src/rag/retrieve.py`, `src/rag/index.py` |
| `sqlite` | New `src/db.py`: parse `settings.database_url`, open a connection, `CREATE TABLE IF NOT EXISTS` scratch table, insert/select/delete, commit | new — `database_url` is currently declared in `src/config.py` but unused anywhere |

Backend broker credential/ACL failure reports `mqtt=down`; simulator credential/ACL failure or missing authenticated heartbeat reports `vehicle_simulator=down` — both already fall out of the existing `MqttRuntime`/`VehicleStateCache` state.

## Config additions

`src/config.py`:
- `health_voice_probe_ttl_s: float = 10.0` — TTL for the STT/TTS smoke-test cache.

No new third-party dependency: the `sqlite` probe uses stdlib `sqlite3`, matching `src/rag/store.py`'s existing style.

## Fail-closed behavior

Any probe exception, timeout, or unconfigured/disabled dependency (e.g. `slm_enabled=False`) maps to `down`, never propagates past the endpoint as an unhandled error. This matches the ADR-005 precedent of `model_profile="not-selected"` staying not-ready rather than defaulting to ready. Process/container liveness remains a separate internal supervisor concept and is not part of this endpoint.

## Caching

Only `stt` and `tts` probes are cached (short TTL, default 10s) — they're the only probes expensive enough (real model inference) to risk becoming a self-inflicted load/latency problem under frequent polling. The other six probes are cheap (in-memory state checks, one small SQLite transaction, one FAISS query) and run live on every call.

## Testing

- Unit tests per probe function in `src/services/health.py`, mocking each dependency: stub `MqttRuntime`, faked SLM `httpx` response, a temp SQLite file, a tiny fixture RAG index, stub STT/TTS engines.
- Integration tests hitting `/healthz`: all-ready → `200`; each single-component-down permutation → `503` with correct `status` and `error.details.dependencies` contents.
- `tests/test_api/test_routes.py::test_health` rewritten to test `/healthz` instead.

## Out of scope

- A true MQTT ping/ack round-trip health topic (currently reuses the connection-state flag as a proxy).
- Keeping `/health` as a deprecated alias (removed outright).
- Any P1 management surface (`/manuals/ingest`, `/eval/runs*`, `/model-profiles*` per `docs/api_spec.md`).

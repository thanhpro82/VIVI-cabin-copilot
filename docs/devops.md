# DevOps and Operations Plan

## Status and scope

This is a **Planned** target operating contract. It is not a runnable deployment claim: this repository currently has no Compose file or smoke evidence for the target topology. Implementation and verification status must be recorded beside the relevant artifact/evidence when they exist.

P0 has exactly five long-running services:

| Service | Port/exposure | Readiness evidence |
|---|---|---|
| `ivi-web` | `127.0.0.1:3000` | Browser UI available after backend readiness |
| `backend` | `127.0.0.1:8000`; `GET /healthz` | All required dependencies are ready — seven of the eight probed components; `llm` is exempt at P0 (issue #48), still reported but not gated |
| `llm` | `8080` on `edge_internal` only | Local health endpoint and configured model are ready |
| `mqtt` | `127.0.0.1:1883` debug binding; internal broker on `edge_internal` | Authenticated connect/publish/subscribe succeeds. The Compose healthcheck proves exactly connect + authentication (`mosquitto_sub -E`, which exits on SUBACK); it deliberately does **not** wait for a message, because no topic the backend identity may read is guaranteed to carry traffic before the simulator starts — and the simulator is itself gated on this healthcheck. ACL enforcement is proven separately by the L2 contract tier, not here. |
| `vehicle-simulator` | No public port | MQTT heartbeat and state topic are observed |

`eval` is an on-demand process, not a long-running service. Voice STT/TTS run as backend adapters/native processes; they are not separate services. FAISS, SQLite, deterministic routing, the agent, safety policy, telemetry, and RAG are backend modules.

## Planned startup and offline runbook

1. Preflight the selected model, vehicle manual, local POI fixture, and RAG index manifests and checksums. With ADR-005 **Not Yet**, `LLM_MODEL_PROFILE=not-selected` or an empty `LLM_MODEL_PATH` fails closed: model/backend readiness must not become ready until a selected profile manifest and path are configured.
2. Start `mqtt`.
3. Start `vehicle-simulator` and wait for its MQTT heartbeat and state topic.
4. Start `llm` and wait for both health and configured-model readiness.
5. Start `backend` and check the exact dependency set: `backend`, `llm`, `mqtt`, `vehicle_simulator`, `stt`, `tts`, `rag_index`, and `sqlite`.
6. Start `ivi-web`, then perform the health and offline acceptance drill.

The following are target commands only, **Planned / not runnable until Compose and smoke evidence exist**:

```powershell
Copy-Item .env.example .env
docker compose --profile edge-cpu up --build
docker compose ps
```

The target endpoints are IVI at `http://127.0.0.1:3000`, backend health at `http://127.0.0.1:8000/healthz`, internal LLM at `llm:8080`, and the optional loopback-only MQTT debug binding at `127.0.0.1:1883`.

## Environment contract

| Variable | Target/example | Purpose |
|---|---|---|
| `OFFLINE_MODE` | `true` | Reject runtime cloud/external-network dependencies |
| `LLAMA_BASE_URL` | `http://llm:8080/v1` | Local LLM endpoint |
| `LLM_MODEL_PROFILE` | `not-selected` | Fail-closed default while ADR-005 is Not Yet |
| `LLM_MODEL_PATH` | `""` | Empty until a selected, manifested local model is configured |
| `STT_PROVIDER` | `sherpa_onnx` | Local transcription implementation (PoC/demo scope — see ADR-017) |
| `STT_MODEL_PATH` | `/models/stt/zipformer-30m-rnnt-6000h/` | STT artifact (sherpa-onnx ONNX model directory, not a file) |
| `TTS_PROVIDER` | `piper` | Local synthesis implementation |
| `TTS_MODEL_PATH` | `/models/tts/vi_VN.onnx` | TTS artifact |
| `MQTT_URL` | `mqtt://mqtt:1883` | Simulator broker |
| `MQTT_BACKEND_USERNAME` | `vivi-backend` | Distinct backend broker identity |
| `MQTT_BACKEND_PASSWORD_FILE` | `/run/secrets/mqtt_backend.password` | Backend-only client password |
| `MQTT_SIMULATOR_USERNAME` | `vehicle-simulator` | Distinct simulator broker identity |
| `MQTT_SIMULATOR_PASSWORD_FILE` | `/run/secrets/mqtt_simulator.password` | Simulator-only client password |
| `DATABASE_URL` | `sqlite:////data/vivi.db` | Container-absolute local state/audit persistence |
| `RAG_INDEX_PATH` | `/data/index/manual.faiss` | Local retrieval index |
| `RAG_MANIFEST_PATH` | `/data/index/manifest.json` | Index/document checksum manifest |
| `RAW_AUDIO_RETENTION` | `false` | Do not retain raw audio by default |
| `LOG_LEVEL` | `INFO` | Structured-log verbosity |
| `AUTH_SIGNING_KEY_FILE` | `/run/secrets/auth_signing_key` | File-mounted local signing key |
| `AUTH_TOKEN_TTL_SECONDS` | `900` | Short-lived local access token |
| `MQTT_ALLOW_ANONYMOUS` | `false` | Reject anonymous broker clients |
| `MQTT_PASSWORD_FILE` | `/run/secrets/mosquitto.password` | Broker-owned Mosquitto password database containing both client identities |
| `MQTT_ACL_FILE` | `/run/secrets/mosquitto.acl` | Topic ACL for backend/simulator identities |
| `SIM_CONTROL_ENABLED` | `false` | Harness channel `v1/sim/` (ADR-024). Must be set on **both** `backend` and `vehicle-simulator` — one side alone leaves the message unheard |
| `SIM_DRIVE_CYCLE` | `false` | Simulator drives itself in a loop (0 ↔ `SIM_DRIVE_CYCLE_SPEED_KPH`). Independent of the flag above, so a public link can show a moving car that nobody can steer |
| `SIM_DRIVE_CYCLE_SPEED_KPH` | `45` | Cruise phase of that loop |
| `SIM_DRIVE_CYCLE_PHASE_S` | `30` | Seconds per phase |

Runtime never auto-downloads models, manuals, indexes, POI, or cloud resources. `.env.example` contains only safe local defaults; `.env` is not committed. The target `scripts/bootstrap_local_secrets.ps1` creates the signing key, backend client password, simulator client password, broker password database, and broker ACL with restrictive Windows ACLs; it is **Planned and does not exist yet**, so it is not currently runnable. Secret rotation regenerates the client passwords plus broker database/ACL, restarts `backend`, `vehicle-simulator`, and `mqtt`, and invalidates all auth sessions. Secrets and generated password/ACL files are never committed.

**The harness channel is off by default and off is the deploy default.** `SIM_CONTROL_ENABLED=true` opens `POST /api/v1/sim/motion` (which returns 404 while the flag is false) and makes the simulator subscribe to `v1/sim/{id}/motion/set`. Two consequences to weigh before turning it on for a public link: the simulated car is a **shared resource** with no multi-tenancy, so one visitor moving the slider changes the speed mid-turn for everyone else — including turning another visitor's pending S2 approval into an S3 refusal; and any driver token can drive it. `SIM_DRIVE_CYCLE` has neither property (nobody controls it) and is the safer half to enable alone.

Secret mounts are least-privilege: `backend` receives the signing key and `MQTT_BACKEND_PASSWORD_FILE`; `vehicle-simulator` receives only `MQTT_SIMULATOR_PASSWORD_FILE`; `mqtt` receives only the broker-owned `MQTT_PASSWORD_FILE` database and `MQTT_ACL_FILE`. The ACL permits backend publish to command topics and subscribe to state/heartbeat topics; the simulator may subscribe to its command topics and publish only state/heartbeat/result topics. Neither client can read the other client's password file, publish arbitrary topics, or administer the broker.

The planned Compose network is named `edge_internal` and declares `internal: true`. `ivi-web`, backend API, and any MQTT debug port publish only to `127.0.0.1`; the broker is never exposed on a non-loopback host interface. LLM, simulator, and service-to-service traffic remain internal.

## Readiness contract

`GET /healthz` and [the API contract](api_spec.md#health) use exactly the same eight names: `backend`, `llm`, `mqtt`, `vehicle_simulator`, `stt`, `tts`, `rag_index`, and `sqlite`. `ready` means the real dependency probe can serve the demo; `degraded` means it responds but cannot meet correctness/capacity; `down` means unavailable, timed out, missing, unconfigured, or authentication/ACL denied. The probes are respectively self/event-loop, configured-model identity/inference readiness, backend-identity authenticated broker round trip, simulator-identity authentication plus fresh heartbeat/state, local transcribe smoke, local synthesis smoke, manifest/checksum/open/query, and SQLite read/write transaction. A backend credential/ACL failure marks `mqtt=down`; a simulator credential/ACL failure or missing authenticated heartbeat marks `vehicle_simulator=down`. `disabled` (added 2026-08-15, issue #95) means the running configuration deliberately turns the component off, which is not the same thing as unavailable: `llm` when `slm_enabled=false`, and `mqtt` **and** `vehicle_simulator` when `MQTT_ENABLED=false` — the simulator is only reachable over MQTT, so with the broker switched off its silence follows from that choice rather than from a fault. Full demo readiness returns `200` when no **required** component is in a blocking state (`degraded` or `down`). Two independent exemptions produce that: `llm` is exempt **by name** at P0 (decided 2026-08-11, issue #48) because `slm_enabled=False` by design makes it permanently unable to reach `ready`, and always-503 for a component that never runs at P0 is not an actionable incident; any component is exempt **by state** when `disabled`. Exempt components are still probed and still shown in `components`/`faults` with their real status — they just never force a `503` on their own. `llm` returns to the required set once LLM/SLM becomes a required P0/P1 dependency. Any other required-component state returns the redacted common `503` dependency envelope. Process liveness remains a separate internal supervisor concept.

## Artifact, CI, and observability policy

- Every model/manual/index artifact has a pinned source/revision, filename, SHA-256 checksum, license decision, and creation command in its manifest.
- The preflight fails closed when a required artifact or checksum is missing or differs from its manifest.
- CI runs lint, unit, contract, and mock smoke checks with tiny fixtures only; it never downloads or stores large models. Full offline/golden/performance evaluation runs on the designated local machine and records a versioned report and manifest.
- Structured logs carry `trace_id`, session/turn identifiers, component, event, severity, model/data/config versions, and redact credentials, raw audio, and sensitive transcript fields.
- The P0 read-only Engineer dashboard consumes the exact safe aggregate API/WS schema: per-stage latency; model tokens/s, RSS and profile; MQTT latency/errors; groundedness/abstention and citation/faithfulness rates; validation/S3 blocks and approval outcomes; completed/failed/deduplicated/skipped action-audit outcomes. It exposes no raw prompt/audio/secret/unrestricted transcript. Full trace/eval and model/config mutation are authorized/audited CLI/P1 capabilities.
- Resource policy records CPU/RAM/disk limits, model threads/context, cold and warm latency, and peak RSS. Q4 and Q8 are benchmarked separately.

## Target offline evidence procedure

This entire procedure is **Planned / not runnable until Compose, the bootstrap script, and smoke artifacts exist**. Its exact target steps are:

```powershell
Copy-Item .env.example .env
.\scripts\bootstrap_local_secrets.ps1
docker compose --profile edge-cpu up --build
docker compose ps
docker network inspect edge_internal
Invoke-WebRequest http://127.0.0.1:8000/healthz
docker compose exec backend python -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)"
```

`docker compose ps` must show only loopback host bindings; `docker network inspect edge_internal` must show `Internal: true`; local `Invoke-WebRequest` must return readiness `200`; and the external URL probe must exit non-zero/fail. Then run the local demo flows from [the five-minute script](demo_script.md): versioned local POI/navigation plus HVAC, grounded manual/citation/refusal, S2 window approval, S3 moving-door block, and Engineer trace. Capture command stdout/exit codes, readiness JSON, network inspection, trace/metrics/action audit, and `Get-FileHash -Algorithm SHA256` output for model/manual/POI/index manifests. An unexpected external call in `OFFLINE_MODE=true` fails the drill.

## Backup, recovery, and P2 OTA mock

- Snapshot SQLite before changing model profile, manual/index ingestion, or configuration; preserve action audits and immutable eval reports by run ID.
- Recover model/manual/index from their manifests, verify checksums, then restart only affected services. If audit persistence is unhealthy, actuator execution remains locked read-only.
- P2 OTA is a simulator-only mock for signed model/config manifests: one simulator, then 25% of simulated fleet, then 100%, with safety/error/p95 gates and rollback to the previous manifest. It is not a vehicle binary update.

## Triage

| Symptom | First check | Safe response |
|---|---|---|
| No microphone or speech | Browser permission/device; backend STT readiness | Switch to text; do not bypass audit |
| LLM unavailable | LLM health, selected profile/path, manifest checksum | Keep readiness non-ready until ADR-005 evidence selects a valid profile; restart LLM only after configuration |
| Simulator does not change | MQTT connectivity and simulator heartbeat | Lock actuators and remain read-only |
| Citation is unavailable | RAG manifest/index checksum | Return grounded refusal, never an uncited answer |
| Latency rises | Trace waterfall, RSS, CPU/disk pressure | Reduce context/background load; never skip safety |

Three weeks may produce a **Functional P0 candidate**, but operational readiness is **Verified P0** only after the mandatory Week 4 gate: the above target commands have matching Compose/smoke evidence, the offline drill and recovery evidence exist, both user-feedback rounds are recorded, and the dashboard reports the actual model/data/config versions.

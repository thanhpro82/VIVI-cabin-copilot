# VIVI Cabin Copilot — Technical Specification

> **Status: Planned.** This document specifies the approved P0 target. It does not claim that a runtime, endpoint, or deployment is already Implemented or Verified.

## Architecture overview

VIVI Cabin Copilot is an offline-edge product with a modular-monolith `backend`. The product presents Driver IVI and Engineer Dashboard views through the same `ivi-web` surface, with RBAC enforced by the backend. Modules preserve ownership boundaries without becoming separate P0 services: gateway/auth/session/WebSocket, voice adapter, deterministic router, bounded agent/LangGraph, RAG, safety, executor, and telemetry.

The architecture decision is [ADR-006](adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md). Safety is authoritative in [safety_and_hitl.md](safety_and_hitl.md); entities and event contracts are authoritative in [data_model.md](data_model.md).

## Runtime topology

P0 targets exactly five long-running services:

| Service | Port | Responsibility |
|---|---:|---|
| `ivi-web` | 3000 | Driver IVI and Engineer Dashboard presentation surfaces |
| `backend` | 8000 | Modular monolith: API, realtime, orchestration, safety, persistence |
| `llm` | 8080 | Local llama.cpp model server |
| `mqtt` | 1883 | Local Mosquitto broker |
| `vehicle-simulator` | No public port | Simulated state and actuator transitions |

`eval` is on-demand, not a long-running service. SQLite and FAISS run embedded in `backend`; FAISS uses a local manifest/checksum. Whisper.cpp, PhoWhisper, and Piper remain behind the backend voice adapter as libraries, native binaries, or managed subprocesses. They are not deployment services.

No cloud service is on the critical path. This target does not include CAN, ECU, or a real vehicle.

## Component contracts and routing

Every route produces either a grounded answer, clarification/refusal, or an internal typed `CandidateActionPlan`. The deterministic router handles clear P0 intent/slots and known P0 multi-intents before an SLM is considered; only an ambiguous or rare request may use the SLM to propose the same closed candidate schema. The candidate contains no safety fields or public identifiers.

The SLM cannot set a safety level, authorize a tool, publish MQTT, or claim an execution result. Its output receives an initial schema check and at most one repair attempt. Invalid output then goes to clarification, grounded refusal, or deterministic fallback. A pure pre-resolution validator checks allowlists, ranges, the dependency DAG, and local-POI references before any lookup. Unicode-NFC/schema-default/canonical-number normalization yields replay-stable candidate step IDs and digest. A validated `search_nearby_poi` transactionally loads/creates a plan-independent leased `PlanningResolution` pinned to an immutable fixture. A pure read can repeat only after crash/expired-lease reclaim, while compare-and-set exposes one terminal `succeeded|empty|failed` outcome; this is exactly-once observable/effectively-once. The candidate is not persisted as a canonical plan, though the checkpointer may retain workflow state plus derived IDs/digest. `succeeded` rewrites navigation to a concrete `destination_id`; `empty`/`failed` create no canonical plan or side effect. The common validator then checks the resolved candidate, and deterministic whole-plan policy injects safety plus server-owned context to materialize the canonical immutable `ActionPlan` used by API, approval, executor, and trace.

All candidate-to-canonical plans follow this contract:

1. Validate every allowlisted tool, schema, and range for the complete plan. Invalid input becomes `validation_denied` before S0–S3 classification.
2. Apply deterministic whole-plan policy. Any S3 blocks all side effects; any S2 requires one bundled approval before every side effect; S0/S1-only plans execute after policy.
3. For an S2 outcome, atomically persist immutable `ActionPlan` + bound pending approval in one DB transaction after validation/policy; enforce one pending/session inside the transaction and roll back both on conflict. Bind user/session/plan, `plan_digest = sha256(canonical_json(ActionPlan))`, and `approved_vehicle_state_version`; enforce 30-second and single-use limits, then recheck digest, state version, and all predicates immediately before the first side effect. S1-only remains direct without approval.
4. On admission, consume approval and create `execution_group_id`. Commands use idempotency keys and rolling `expected_state_version`; an external mismatch stops remaining steps and is reported honestly.
5. Enforce at most one pending approval/session. A distinct voice approval-intent turn can emit typed handoff context only; IVI commits approve/reject via REST. Intent and original command turns each emit exactly one terminal event, and reject/expiry/state/plan/predicate invalidation creates no group/MQTT side effect.

See [safety_and_hitl.md](safety_and_hitl.md) for the policy matrix, admission, retries, and failure semantics.

## Safety qualities

Every valid action is policy-checked and audited. S0 is read-only. S1 actions—including HVAC, seat heating, media, and navigation in the prototype—execute directly after policy and return feedback; they do not need approval. S2 actions require explicit voice-first approval, while S3 valid-but-forbidden actions are blocked before HITL and have no bypass.

Mixed plans are atomic at admission: no side effect runs if validation fails, any S3 exists, approval is missing/expired/rejected, or the approved vehicle state is stale. Side-effect failure is fail-fast and reports per-step outcomes. The executor gets exactly one same-command/idempotency-key retry only for transient transport failure; validation, policy, and tool-semantic failures are never retried. The system never implies full success without verified `ToolResult` evidence.

## Local grounded RAG

RAG remains local with `multilingual-e5` embeddings and FAISS. Manual ingestion validates a local manifest and checksum; retrieval filters by vehicle profile and applies an evidence threshold. The answer composer may use only retrieved evidence and returns the canonical public Citation fields `citation_id`, `turn_id`, `document_title`, `section`, `page`, `chunk_id`, bounded supported `excerpt`, and `retrieval_score`. Insufficient or stale evidence yields a grounded refusal rather than general knowledge.

The model can improve wording but cannot turn manual text into tool authority. Source details and related entities are in [data_model.md](data_model.md).

## P0 API and realtime boundary

At P0, the public surface is deliberately narrow: auth, sessions, text/voice turns, REST-only approval decisions, vehicle state, citations, role-scoped safe traces, metrics, and two WebSocket streams (Driver IVI and Engineer). A voice approval-intent server event is handoff only and is never a decision message. Management APIs for manual ingestion, full evaluation/trace operations, and runtime model activation are authorized/audited P1/CLI.

Exact routes, envelopes, event ordering, and endpoint-level errors belong to [api_spec.md](api_spec.md); Task 4 owns their detailed migration. This specification does not establish those exact endpoint names as implemented.

Every side-effecting request/event contract carries trace/session context, schema version, and an idempotency identity. Vehicle-state fields have distinct lifecycle meanings and must not be collapsed into a generic “state version”:

| Contract field | Canonical lifecycle meaning |
|---|---|
| `ActionPlan.vehicle_state_version` | Planning snapshot read before whole-plan policy evaluation |
| `ApprovalRequest.approved_vehicle_state_version` | Public admission baseline; persisted as `approvals.vehicle_state_version` |
| `VehicleCommand.expected_state_version` | Rolling expected current version: approved baseline for the first command, then the preceding result's observed version |
| `ToolResult.observed_state_version` | State version observed/resulting from command processing and used by the next command |

The canonical entity and message names are defined in [data_model.md](data_model.md). Realtime events carry stable event identity and ordering information for reconnect and deduplication.

## Frontend and driving policy

`ivi-web` contains two product surfaces: Driver IVI and Engineer Dashboard. Driver experience is voice-first and glanceable. The P0 Engineer view is read-only and limited to state, readiness, safe structured traces, and safe aggregates for per-stage latency, model tokens/s + RSS/profile, MQTT latency/errors, groundedness/abstention, safety/approval and action audit. Raw prompts/audio/secrets/unrestricted transcripts are excluded; full trace/eval and model/config mutation are authorized/audited CLI/P1 capabilities, while OTA is P2. The frontend renders backend-issued `ui_policy`; it never infers safety from a local speed reading. The JSON below is the canonical `ui_policy` contract sample; [user_experience.md](user_experience.md) mirrors it and must remain value-identical.

```json
{
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
```

## Decision records and references

- [ADR-001: Offline-first runtime](adr/ADR-001-offline-first-runtime.md)
- [ADR-002: Bounded agent and safety policy](adr/ADR-002-bounded-agent-and-safety-policy.md)
- [ADR-003: Local RAG stack](adr/ADR-003-local-rag-stack.md)
- [ADR-004: MQTT vehicle simulator](adr/ADR-004-mqtt-vehicle-simulator.md)
- [ADR-005: Model profile selection](adr/ADR-005-model-profile-selection.md)
- [ADR-006: P0 modular monolith, deterministic routing and calibrated HITL](adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md)

Primary technical references: [llama.cpp](https://github.com/ggml-org/llama.cpp), [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [Piper](https://github.com/OHF-Voice/piper1-gpl), [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), and [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small).

## Status and evidence boundary

Use **Planned** for this design, **Implemented** only when corresponding code exists, and **Verified** only when reproducible tests or evaluation evidence exist. Historical model evidence in [eval/results/report.md](../eval/results/report.md) supports deterministic-first routing but does not verify the P0 runtime topology or API.

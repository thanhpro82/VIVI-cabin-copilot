# Delivery Plan — Four-Person VIVI Team

## Planning status and P0 cut

This is a **Planned** four-week verification plan for four people, with a three-week **Functional P0 candidate** checkpoint. Three weeks may establish feature function but cannot claim **Verified P0**; Week 4 is mandatory for offline/recovery/research/rehearsal evidence. Model selection remains **Not Yet** until ADR-005 evidence passes its gate. P0 targets exactly five long-running services: `ivi-web`, `backend`, `llm`, `mqtt`, and `vehicle-simulator`; voice and agent work remain backend modules.

The P0 Engineer surface is deliberately minimal and read-only: state, safe structured trace, aggregate metrics, and readiness health. It contains no configuration or model management. Manual ingestion, eval-run, model-profile/config management APIs are P1. Fleet, rollout, and OTA mock are P2 and are cut before P0 capacity is consumed.

## Workstreams, ownership, and backup review

| Workstream | Primary | Backup reviewer | P0 responsibility and owned CI job |
|---|---|---|---|
| WS1 Voice/Edge | Member 1 | Member 2 | Voice UX, STT/TTS adapters, audio/stage metrics, llama/model runtime profiles and benchmarks; owns voice/runtime tests and CI job |
| WS2 Agent/RAG | Member 2 | Member 3 | Deterministic router including local POI, bounded LangGraph/SLM, RAG/citations, trip memory; owns agent/RAG tests and CI job |
| WS3 Vehicle/Safety | Member 3 | Member 4 | Policy, HITL, executor, MQTT, simulator, action audit; owns safety/vehicle tests and CI job |
| WS4 IVI/Platform | Member 4 | Member 1 | API/Next shell, RBAC, WebSocket, SQLite, Driver and read-only Engineer views in one Next.js app, Compose integration, and telemetry aggregation; owns platform/integration tests and CI job |

The backup reviewer cycle is WS1 → WS2 → WS3 → WS4 → WS1. A backup reviews contracts and can unblock the primary, but does not silently take ownership. Every workstream instruments its own component and maintains its own CI test job; WS4 only aggregates those agreed signals and integrates the shell.

## Producer/consumer dependency order

1. Shared typed contracts and fixtures are reviewed first: API/WS schemas, tool registry, safety policy, health dependencies, telemetry fields, manual/POI manifests.
2. WS3 produces MQTT mocks/simulator and authoritative state fixtures; WS1 produces voice/model adapter mocks; WS2 produces deterministic router/RAG/POI fixtures.
3. WS1/WS2/WS3 implement their backend modules against those mocks and contract tests. POI search resolves a concrete destination before any side effect.
4. WS4 consumes stable backend contracts to build RBAC/WebSocket/SQLite shell and both views in one app, then integrates Compose and telemetry.
5. Cross-workstream integration runs only after producer and consumer contract jobs pass; changed schemas require both owners and the backup reviewer.

## Capacity plan

Each member has at most 5 task-days per week. Integration and user research are explicitly reserved rather than assumed free.

| Week | WS1 | WS2 | WS3 | WS4 | Shared outcome |
|---|---:|---:|---:|---:|---|
| Week 1 | 4 feasibility/build + 1 contract review = 5 | 4 router/RAG/POI + 1 contract review = 5 | 4 simulator/safety fixtures + 1 contract review = 5 | 4 shell/RBAC/contracts + 1 integration = 5 | PoC-based deterministic coverage, contracts, mocks, walking skeleton |
| Week 2 | 4 adapters/metrics + 1 integration = 5 | 4 agent/RAG resolution + 1 integration = 5 | 4 policy/HITL/executor + 1 integration = 5 | 4 WS/SQLite/two views + 1 integration = 5 | Calibrated P0 vertical slice |
| Week 3 | 3 evidence/fixes + 1 integration + 1 research = 5 | 3 evidence/fixes + 1 integration + 1 research = 5 | 3 fault/safety evidence + 1 integration + 1 research = 5 | 3 Compose/dashboard + 1 integration + 1 research = 5 | CLI eval evidence, user-feedback round 1, offline rehearsal |
| Week 4 mandatory verification | 3 hardening + 1 research + 1 buffer = 5 | 3 hardening + 1 research + 1 buffer = 5 | 3 hardening + 1 research + 1 buffer = 5 | 3 packaging + 1 research + 1 buffer = 5 | Feedback round 2, offline/recovery evidence, repeated rehearsal, evidence freeze, Verified P0 decision |

## Two-round research allocation and gates

Recruit 7–9 unique people overall. Round 1 uses 4–5 participants; Round 2 uses 5–6, with at most two returners and at least three new participants. Returning status is pseudonymized and used only for learnability comparison; metrics are never pooled across rounds.

| Round | Schedule/owner | Tasks | Measures and required evidence | Exit/change gate |
|---|---|---|---|---|
| Round 1 — formative | End W2/start W3; WS4 facilitates, WS1 records speech issues, WS2/WS3 observe agent/HITL | Prototype/wizarded HVAC, coffee/HVAC/navigation, manual citation, S2 window, moving-door refusal | Expected next action, wording, taps/repetitions, approval/citation comprehension; consent index, script/version, anonymized notes, raw measure sheet, synthesis, decision log | Top three workflow/speech/HITL changes reviewed by affected workstream owners before feature freeze |
| Round 2 — confirmatory | W4; WS4 facilitates, three other owners monitor their telemetry/safety evidence | Integrated offline core paths plus low-confidence, approval expiry/state invalidation, dependency failure/recovery | Completion/time/taps/retries/rescue, comprehension, trust/recovery, simulator/audit transitions; separate manifest/notes/measures/report/change log | ≥80% task completion, median happy-path taps ≤1, 100% critical approval/refusal comprehension, zero unauthorized transition, no open research blocker |

## Gates

- Week 1: PoC evidence fixes deterministic-router coverage; no plan text selects an LLM profile.
- Week 2: S0/S1 direct execution, S2 window voice approval with version admission, S3 moving-door block, and local POI zero-result no-side-effect behavior pass.
- Week 3: each owned CI job, CLI golden/safety/fault evidence, exact health/trace contracts, and the separate Round-1 formative artifact set plus reviewed top-three changes are reviewable; the maximum status is **Functional P0 candidate**.
- Week 4 mandatory: full offline evidence procedure, secret/auth readiness checks, recovery, the separate Round-2 confirmatory artifact set/targets, and repeated demo rehearsal must pass before **Verified P0** is allowed.

Verified P0 acceptance requires grounded citation/refusal, exact five-service topology evidence, all eight readiness dependencies ready, safe Engineer trace fields, per-component instrumentation, and both preserved user-research rounds during mandatory Week 4. If capacity slips, retain the Functional P0 candidate label, cut P1 management APIs first and P2 fleet/OTA entirely, and do not cut safety, offline evidence, contract tests, research, or the verification gate.

# Routines MVP — UAT traceability

> Owner: PM/PO (`thanhpro82`) · Source scope: [Routines Product Spec](../routines_product_spec.md) · Epic: [#270](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/270) · Release gate: [#279](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/279) · Traceability issue: [#300](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/300)

## How to use this record

Each row maps one acceptance criterion from #271–#278 to the evidence required to close it. `Pending` means no qualifying implementation evidence has been recorded; it does not mean the criterion passed. Add a test path plus commit SHA for automated evidence, or a dated UAT run ID plus approved artifact for manual evidence. A screenshot alone cannot close a safety, ownership, replay, or cancellation row.

The release decision is maintained separately in [Routines MVP release decision](routines-mvp-release-decision.md). A row may be marked `Pass` only after its cited evidence has been reviewed; a `Fail` opens or links a defect with severity and owner.

## #271 — Templates and create-from-scratch

| ID | Acceptance criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 271-1 | A new user sees three personal templates. | Automated bootstrap/ownership test; manual first-login UAT. | FE + BE | Pending |
| 271-2 | A user can create a named Routine with at least one action. | API/domain test and builder UAT. | FE + BE | Pending |
| 271-3 | An empty Routine or one with more than four actions cannot be saved. | Validation tests, including boundary values 0 and 5. | BE + FE | Pending |
| 271-4 | Normalized names are unique per user. | Persistence test for case/punctuation variants and cross-user allowance. | BE | Pending |
| 271-5 | A template can be edited, disabled, and restored, but not permanently deleted. | Lifecycle tests and builder UAT. | FE + BE | Pending |
| 271-6 | A custom Routine can be deleted after confirmation. | UI confirmation test and ownership/delete test. | FE + BE | Pending |
| 271-7 | A new or edited Routine requires preview on its next run. | Version/preview integration test and voice UAT. | Agent + BE + FE | Pending |

## #272 — Routine ownership and management

| ID | Acceptance criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 272-1 | A user can read and change only their own Routines. | Authorization tests for list, read, update, delete, and run. | BE | Pending |
| 272-2 | Cross-user access is denied without revealing whether the Routine exists. | Negative API tests with identical user-safe response shape. | BE + Security | Pending |
| 272-3 | Routines survive an application restart. | Restart integration/UAT with persisted data. | BE | Pending |
| 272-4 | A disabled Routine cannot run by voice or UI. | Agent, API, and UI negative tests. | Agent + FE + BE | Pending |
| 272-5 | Missing parameters, disallowed actions, and invalid configuration cannot be saved. | Domain validation tests for each rejection class. | BE | Pending |
| 272-6 | A running Routine cannot be deleted without cancellation first. | Lifecycle/race test and UI UAT. | BE + FE | Pending |
| 272-7 | Audit/trace stays within the approved privacy boundary. | Trace schema/privacy review and negative redaction tests. | BE + Security | Pending |

## #273 — Personal Home and Work destinations

| ID | Acceptance criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 273-1 | Home and Work persist separately for each user. | Persistence plus cross-user isolation tests. | BE | Pending |
| 273-2 | A destination outside the offline allowlist cannot be selected. | API and UI validation tests. | BE + FE | Pending |
| 273-3 | A Routine without its required destination never silently uses a default. | Execution test proving fail-fast and zero navigation side effect. | BE + Agent | Pending |
| 273-4 | Voice run with a missing destination guides the driver to setup. | Voice contract/eval test and manual UAT. | Agent + FE | Pending |
| 273-5 | Changing one user's destination cannot affect another user's data. | Cross-user mutation test. | BE | Pending |
| 273-6 | An invalidated offline destination puts the Routine into setup-required state. | Fixture-change/regression test and UI state test. | BE + FE | Pending |

## #274 — Voice preview and run

| ID | Acceptance criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 274-1 | Supported run/preview phrases resolve correctly on the agreed eval set. | Versioned eval run with cases and results. | Agent | Pending |
| 274-2 | A missing name lists available Routines and never runs one. | Agent integration test. | Agent | Pending |
| 274-3 | An ambiguous name asks for clarification with zero side effect. | Ambiguity/e2e test. | Agent + BE | Pending |
| 274-4 | Preview creates zero side effect. | Event/audit/MQTT negative test. | Agent + BE | Pending |
| 274-5 | Eligible S1 reaches execution without redundant confirmation. | Voice e2e test and manual UAT. | Agent + BE | Pending |
| 274-6 | S2 cannot execute when confirmation is absent, ambiguous, rejected, or expired. | Approval integration tests for all four paths. | Agent + BE | Pending |
| 274-7 | Disabled, setup-required, and invalid Routines cannot run. | State-specific negative tests. | Agent + BE | Pending |
| 274-8 | Voice response stays short while UI carries step detail. | Copy review and manual UAT. | Agent + FE + PM/PO | Pending |

## #275 — Validation, safety, and HITL

| ID | Acceptance criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 275-1 | Every run rechecks Routine, arguments, and current vehicle state. | Integration test with changed state/configuration. | BE | Pending |
| 275-2 | No old authorization or plan is replayed. | Replay/idempotency regression test. | BE | Pending |
| 275-3 | Every S2 action has valid approval bound to the current execution. | Approval binding integration test. | BE + Safety | Pending |
| 275-4 | An action that becomes S3 is blocked before side effect. | Moving-vehicle S3 test with zero MQTT side effect. | BE + Safety | Pending |
| 275-5 | A mixed S1/S2 Routine starts no step before valid bundled approval. | Mixed-plan admission test. | BE + Safety | Pending |
| 275-6 | Disconnect, unavailable/stale state, or invalid action fails closed. | Failure-mode integration tests. | BE | Pending |
| 275-7 | Execution is sequential/fail-fast and remaining steps are skipped accurately. | Multi-step failure test with terminal step states. | BE | Pending |
| 275-8 | Replaying a terminal execution causes no second side effect. | Duplicate/replay test with persisted terminal result. | BE | Pending |

## #276 — Progress and per-step result

| ID | Acceptance criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 276-1 | UI order and step states match actual execution. | Contract test plus visual UAT. | FE + BE | Pending |
| 276-2 | Success reports exactly one completion. | Event/UI deduplication test. | FE + BE | Pending |
| 276-3 | Failure names the failed step and marks later steps not-run/skipped. | Failure rendering integration test. | FE + BE | Pending |
| 276-4 | Cancel reports completed and unstarted step counts. | Cancellation UI/e2e test. | FE + BE | Pending |
| 276-5 | No update follows a terminal execution result. | Event-order contract test. | BE + FE | Pending |
| 276-6 | Reconnect/replay does not duplicate steps or terminal message. | Replay/reconnect e2e test. | FE + BE | Pending |
| 276-7 | A TTS failure cannot remove text/UI result. | TTS-failure integration and UI test. | Agent + FE | Pending |

## #277 — Barge-in spike

| ID | Exit criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 277-1 | A Go/No-Go recommendation has measured evidence. | Dated spike report with run IDs. | FE + Agent | Pending |
| 277-2 | Hardware, browser, and microphone conditions are recorded. | Spike environment record. | FE | Pending |
| 277-3 | The feasible meaning of “stop immediately” is explicit. | Approved semantics in spike report. | BE + FE + PM/PO | Pending |
| 277-4 | Go includes contract and acceptance thresholds. | Reviewed implementation proposal. | FE + Agent + BE | Pending |
| 277-5 | No-Go records the button-first fallback and post-TTS voice behavior. | Updated runbook and UAT case. | PM/PO + FE | Pending |
| 277-6 | No availability claim rests only on unit tests or mock audio. | Evidence review confirms real audio/demo conditions. | PM/PO | Pending |

## #278 — Cancel at a safe boundary

| ID | Acceptance criterion | Required evidence | Owner | Status |
|---|---|---|---|---|
| 278-1 | Stop control works for every active execution. | UI/e2e test across S1 and S2-waiting states. | FE + BE | Pending |
| 278-2 | Voice cancel follows the #277 decision. | Spike-linked voice UAT. | Agent + FE | Pending |
| 278-3 | Repeated cancel is idempotent and emits one terminal event. | Concurrency/idempotency test. | BE | Pending |
| 278-4 | No new step starts after the safe boundary. | Race/integration test. | BE | Pending |
| 278-5 | An in-flight command is never reported as rolled back. | In-flight cancel test and copy review. | BE + FE | Pending |
| 278-6 | Unstarted steps are clearly canceled/skipped. | Event/UI state test. | BE + FE | Pending |
| 278-7 | Cancel/step-completion races end consistently. | Deterministic race test. | BE | Pending |
| 278-8 | A fresh execution can run after terminal cancel. | Lifecycle regression test. | BE + Agent | Pending |

## Required UAT scenarios

The release run must also execute these scenarios from #279, linking each result back to the rows above: A/B ownership, S1 direct execution, first-version preview, S2 approve/reject/expiry, S3 block, missing Home/Work, step failure, UI cancel, voice cancel per #277, restart, reconnect, and terminal-event deduplication.

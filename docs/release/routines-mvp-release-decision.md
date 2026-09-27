# Routines MVP — release decision record

> Decision owner: PM/PO (`thanhpro82`) · Evidence index: [UAT traceability](routines-mvp-uat-traceability.md) · Product scope: [Routines Product Spec](../routines_product_spec.md) · Gate: [#279](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/279)

## Current decision

**NO-GO — implementation evidence has not yet been recorded.** This is a baseline status, not a defect claim. It prevents a screenshot, mock, or partial happy-path demo from being treated as release evidence before the workstreams complete their acceptance rows.

## Release candidate record

| Field | Value |
|---|---|
| Baseline commit SHA | Not selected; record the immutable release-candidate SHA before UAT begins. |
| UAT date and operator | Not run. |
| Environment | Not run; record browser, microphone, simulator, backend, and SLM configuration. |
| Automated evidence | Not recorded; link test commands, results, and commit SHA. |
| Manual evidence | Not recorded; link approved UAT artifact/run ID. |
| Open P0 defects | Not assessed until UAT executes. |
| Residual risks | Barge-in behavior remains unresolved pending #277; no claim of barge-in support is permitted. |
| Decision | NO-GO |
| Decider and date | PM/PO; decision pending evidence review. |

## Go criteria

All of the following must be true on the same recorded baseline:

1. Every row in the UAT traceability record is `Pass`, or has an explicitly approved out-of-scope disposition that does not weaken an Epic release gate.
2. Cross-user isolation, S2 approval, S3 pre-block, fail-closed state handling, cancellation, restart, reconnect, and terminal-event deduplication pass 100% on their closed acceptance cases.
3. There is no open P0 defect in ownership, execution, approval, cancellation, or UI/voice consistency.
4. #277 has a recorded Go/No-Go result. If No-Go, the guaranteed fallback is visible Stop control; voice cancel is limited exactly as documented.
5. The demo runbook and user-facing fallback behavior match the evidence actually observed.

## No-Go triggers

Any one of the following is sufficient for No-Go:

- A Routine accesses or changes data belonging to another user.
- An S2 side effect happens without current valid approval, or an S3 side effect happens at all.
- A disconnect, stale/unavailable vehicle state, replay, or cancel race causes duplicate or unaccounted side effects.
- A terminal result is duplicated, contradicted by later updates, or conceals a completed/in-flight step.
- The only evidence is a mock, screenshot, synthetic-only claim for human voice behavior, or a test run from a different commit.

## Decision log

| Date | Baseline SHA | Decision | Evidence reviewed | Open P0 / residual risk | PM/PO sign-off |
|---|---|---|---|---|---|
| Not run | — | NO-GO | No implementation evidence recorded | Full UAT pending; #277 unresolved | Pending |

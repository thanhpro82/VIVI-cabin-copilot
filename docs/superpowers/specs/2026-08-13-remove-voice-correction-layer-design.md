# Design: Remove the correction layer from the production turn pipeline

- Status: Draft, approved by user
- Date: 2026-08-13
- Author: brainstorming session (Claude Code) with team member

## Problem

`src/services/voice_correction.py`'s `correct_transcript()` was built
(ADR-009, ADR-012) to patch near-miss STT errors for **PhoWhisper**
(measured avg WER ~26%). ADR-017 switched the production engine to
**Zipformer-30M-RNNT-6000h** (measured avg WER ~8%, ~3.8% on the
tire-pressure real-voice set), and ADR-017's own follow-up work
(auto-derived vocabulary, this session) already found the layer changes
`correct_transcript()`'s behavior significantly once the vocabulary
triples in size — including a real false-positive ("Kiểm" → "Hiểm") on
the user's own real-voice recordings.

Rather than tune the vocabulary further, we measured whether the
correction layer helps or hurts *at all* against Zipformer's actual error
profile, across all 50 cases in `eval/datasets/poc/v1/audio/manifest.jsonl`
(24 synthetic Piper-TTS + 26 real human recordings), comparing three
conditions per case: raw Zipformer output, corrected with the old
47-word hand-typed vocabulary, and corrected with the new 315-word
auto-derived vocabulary.

Results (measured 2026-08-13, ad-hoc script, not yet a committed eval run):

| Condition | Avg WER (n=50) | Avg WER (real, n=26) | Helped | Hurt |
|---|---|---|---|---|
| Raw Zipformer (no correction) | 9.58% | 6.68% | — | — |
| + old vocab (47 words) | 13.19% | 10.74% | 1 | 12 |
| + new vocab (315 words) | 9.90% | 7.23% | 1 | 2 |

Both vocabularies make average WER **worse**, not better, against
Zipformer. The layer's entire premise — that STT output contains enough
near-miss domain-word errors to be worth correcting — held for PhoWhisper
(WER 26%) and no longer holds for Zipformer (WER 8%): on the 5 in-domain
control-vocabulary cases in the set (HVAC, volume, seat heat, navigation),
Zipformer already transcribed all of them correctly, so the correction
layer never even had a real error to fix — it only had correct text to
potentially corrupt.

## Decision

Remove the correction layer from the production voice-turn pipeline.
Keep `transcribe_raw()` (engine-only output) as the only transcription
path `src/api/turns.py` calls. Delete `correct_transcript()` and its
module, its tests, and the now-unreachable `transcribe()` wrapper.

This is a deletion, not a redesign — no replacement correction mechanism
is being built. If a future STT engine swap reintroduces a PhoWhisper-like
error rate, correction can be redesigned then, informed by that engine's
actual error profile (as this measurement now shows should have happened
before ADR-012 wired the original layer in unconditionally).

## Architecture

- `src/api/turns.py:172`: `await asyncio.to_thread(voice.transcribe, audio_bytes)`
  → `await asyncio.to_thread(voice.transcribe_raw, audio_bytes)`. Only
  production call site; `transcribe_raw()` already has the exact same
  signature and error behavior (`transcribe()` was a thin wrapper that
  called it first).
- `src/services/voice.py`: delete the `transcribe()` function. Its lazy
  `from src.services.voice_correction import correct_transcript` import
  goes with it. `transcribe_raw()` is untouched — it is already used
  directly by `src/services/health.py`, `scripts/eval_stt_compare.py`,
  and integration tests, so its contract does not change.
- `src/services/voice_correction.py`: delete the file entirely
  (`correct_transcript()`, `load_command_vocabulary()`,
  `_tokenize_case_dataset()`, `_tokenize_spike001_table()`,
  `PROTECTED_NUMERAL_WORDS`, `AGENT_DATASET_PATH` /
  `MANUAL_DATASET_PATH` / `SPIKE001_DOC_PATH`). Nothing else imports from
  this module after `voice.py`'s `transcribe()` is gone.
- `.dockerignore`: remove the 3 negation lines
  (`!eval/datasets/agent/v3/cases.jsonl`,
  `!eval/datasets/manual/v1/cases.jsonl`,
  `!docs/tasks/SPIKE-001-offline-ai-vertical-slice.md`) added for
  `load_command_vocabulary()` — no runtime code reads them anymore, so
  keeping the re-inclusion would be dead configuration.

## Tests

- `tests/test_services/test_voice_correction.py`: delete entirely (tests
  a module that no longer exists).
- `tests/test_services/test_voice.py:163`: `transcribe(_make_wav_bytes())`
  and the other `transcribe(...)` calls in that file → `transcribe_raw(...)`.
  Assertions about validation errors (`ValueError` on bad WAV, oversized
  audio, wrong sample width) are unchanged — `transcribe_raw()` already
  raises them identically.
- `tests/test_services/test_voice_integration.py`: remove
  `test_correction_layer_never_increases_synthetic_loopback_wer` and
  `test_correction_layer_leaves_perfect_reference_text_unchanged` (test a
  deleted code path). Keep `test_transcribe_warm_latency_is_under_budget`
  and `test_synthetic_loopback_word_error_rate_is_under_budget`, retargeted
  from `transcribe()` to `transcribe_raw()` — these measure the engine
  itself, which is unchanged by this removal, so their existing budgets
  (300ms latency, 15% WER) still apply without re-measurement.
- `tests/test_services/test_health.py`: no change — already exercises
  `transcribe_raw` directly via monkeypatch.
- Full root suite (`MQTT_ENABLED=false pytest tests/ -q`) must stay green
  after the deletions, with the removed tests' count subtracted (not a
  coverage loss — the code they tested is gone too).

## Documentation

- New `docs/adr/ADR-018-remove-voice-correction-layer.md`: records this
  decision, cites the 50-case measurement table above, states the
  revisit trigger (a future engine with materially higher WER than
  Zipformer's measured ~8%).
- `docs/adr/ADR-009-voice-correction-layer.md` and
  `docs/adr/ADR-012-wire-correction-layer-and-raise-wer-budget.md`: add a
  one-line "Superseded by ADR-018 (2026-08-13)" banner at the top. Rest of
  each file stays untouched — they remain accurate historical record of
  what was decided and why, under the PhoWhisper engine that was current
  at the time.
- `docs/superpowers/specs/2026-08-08-voice-correction-layer-design.md`,
  `docs/superpowers/plans/2026-08-08-voice-correction-layer.md`,
  `docs/superpowers/specs/2026-08-12-auto-derived-command-vocabulary-design.md`,
  `docs/superpowers/plans/2026-08-12-auto-derived-command-vocabulary.md`:
  same one-line superseded banner, no content rewrite.
- `JOURNAL.md` / `WORKLOG.md`: add today's entry recording the removal
  and the measurement that motivated it, per existing table/section
  format.

## Non-goals

- No replacement correction mechanism (router-gated retry, stricter
  vocabulary matching, etc.) — YAGNI until a real engine regression
  motivates one.
- No change to `transcribe_raw()`'s behavior, signature, or callers other
  than `turns.py`.
- No change to the Zipformer engine itself, `get_stt_engine()`, or
  `ZipformerEngine`.

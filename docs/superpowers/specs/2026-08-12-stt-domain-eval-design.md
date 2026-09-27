# Design: STT domain-specific error — Phase 1 quick eval (PhoWhisper-base vs Zipformer-30M-RNNT-6000h)

- Status: Draft, pending user review
- Date: 2026-08-12
- Author: brainstorming session (Claude Code) with team member

## Problem

The STT pipeline (faster-whisper, `vinai/PhoWhisper-base`, per ADR-008) misrecognizes
Vietnamese domain terms in short voice commands — e.g. "áp suất lốp là bao nhiêu" comes
out as "nốt cà bao nhiêu". Inspecting `src/services/voice_correction.py` shows this is
not a near-miss spelling error the existing rule-based corrector can fix:
`correct_transcript()` only swaps a word for the nearest `COMMAND_VOCABULARY` entry
within edit distance 1, and "áp", "suất", "lốp" are not even members of that ~64-word
vocabulary. The garbled output is an acoustic-model confusion, not a typo, so tightening
the correction layer cannot address it, and doing so risks overfitting the corrector to
observed failure strings (a risk the code comments in `voice_correction.py:67-73`
already call out for a different case).

ADR-008's only WER evidence for the current engine (30.24%, still failing its own 20%
budget) comes from 5 fixed Piper-TTS synthetic commands
(`tests/fixtures/voice/synthetic_commands/`) — not real speech, and not covering these
domain terms at all. `eval/datasets/poc/v1/audio/manifest.jsonl`, the schema the team
already designed for a real-voice corpus, has been empty since ADR-008 was written.

## Goal (Phase 1 only)

Produce real-audio WER/CER evidence answering one question: is
`hynt/Zipformer-30M-RNNT-6000h` (a Vietnamese-specific ASR, 6000h training data) a viable
short-term replacement for PhoWhisper-base on the domain terms currently failing?
This phase does **not** decide the answer — it produces the number needed to decide.

Out of scope for Phase 1: swapping the production STT provider, prompt/hotword biasing,
vocabulary expansion, fine-tuning either model. Those are follow-up phases gated on this
result.

## Non-goals / explicit limitations

- Small speaker set (1-2 people), ~20-30 sentences — enough to catch regression on known
  failure terms, not a generalization claim. Any write-up of results must say so, per the
  project's "unit test ≠ latency evidence, synthetic ≠ human, in-team evaluator ≠ user"
  discipline (CLAUDE.md).
- No fine-tuning: Zipformer's license (`cc-by-nc-nd-4.0`, confirmed via the model's Hugging
  Face page) forbids derivatives anyway, and Phase 1 doesn't need it.
- Not wired into `src/services/voice.py` or `stt_provider` config. If Zipformer wins,
  wiring it in as a real provider option is a separate, later phase.

## Architecture

One standalone script, `scripts/eval_stt_compare.py`, plus a one-time manual model
download step. Nothing in `src/` changes.

```
eval/datasets/poc/v1/
  cases.jsonl              <- add new domain cases here (existing 31 cases untouched)
  audio/
    manifest.jsonl         <- currently empty; team records audio, fills this in
    *.wav                  <- real recordings, per README's existing schema
    README.md              <- schema already defined, reused as-is

scripts/eval_stt_compare.py
  for each manifest entry:
    transcript_a = PhoWhisper-base.transcribe(wav)   # via existing get_stt_engine()
    transcript_b = Zipformer.transcribe(wav)         # new thin wrapper, sherpa-onnx
    wer_a, cer_a = word_error_rate/char_error_rate(reference_text, transcript_a)
    wer_b, cer_b = word_error_rate/char_error_rate(reference_text, transcript_b)
  write eval/results/stt-compare/<run-id>/{manifest.json,case_results.jsonl,metrics.json}
  print comparison table + threshold verdict
```

### Data: cases and audio manifest

Add new cases to the existing `eval/datasets/poc/v1/cases.jsonl` (do not create a
parallel file — the 31 existing CTRL/NLU cases stay as-is) covering the domain terms
currently observed failing: tire pressure, HVAC, volume, and any other terms the team
has seen mis-transcribed. Cases are read-only/manual-lookup queries in some instances
(tire pressure is not one of the 11 control tools — it routes to RAG/manual lookup), so
`expected` fields for these new cases only need `reference_text` for WER purposes, not
a `tools`/`intent` contract like the control cases.

Audio: team records 20-30 real utterances (1-2 speakers), saves WAV files under
`eval/datasets/poc/v1/audio/`, and fills `manifest.jsonl` per the schema already
documented in `eval/datasets/poc/v1/audio/README.md` (`audio_id`, `path`,
`reference_text`, `speaker_code` pseudonymous, `region`, `noise_condition`,
`duration_ms`, `consent_scope`). No format change needed — the schema already covers
this use case.

### Engine wrappers

**PhoWhisper-base**: reuse `get_stt_engine()` / `FasterWhisperEngine` from
`src/services/voice.py` unchanged. Transcribe **raw** — do not pass output through
`voice_correction.correct_transcript()`. Phase 1 measures the acoustic model only;
running correction on top would conflate two different fixes and make the comparison
harder to interpret.

**Zipformer-30M-RNNT-6000h**: new wrapper local to the script (not added to
`src/services/voice.py`), using `sherpa-onnx`'s `OfflineRecognizer` against the ONNX
export. Model weights fetched once via a manual download step (new script,
`scripts/download_zipformer_model.ps1`, following the existing pattern from
`scripts/download_models.ps1` — pinned version, writes `.sha256`, never auto-downloads
at runtime or batches other models). `sherpa-onnx` becomes a new optional dependency
(add under an eval/dev extra in `pyproject.toml`, not a hard runtime dependency of
`src/`, since Phase 1 doesn't wire it into the product).

### Metrics

Reuse `word_error_rate()` and `char_error_rate()` from `src/services/voice.py:40-53`
as-is — no new metric code needed.

### Output and decision rule

Results land in `eval/results/stt-compare/<UTC-run-id>/`, following the repo's
immutable-run-directory convention (`manifest.json`, `case_results.jsonl`,
`metrics.json`). The script prints a comparison table (per-case WER/CER/latency for
both engines, plus averages) and a verdict line: Zipformer's average WER on the new
domain cases < 15% → recommend as a candidate for a short-term follow-up phase;
otherwise, Phase 1 concludes negative and the team goes back to the biasing/vocabulary
approach discussed earlier in this session.

### Error handling

- Zipformer model files missing → fail fast with the exact download command to run,
  not a stack trace.
- Manifest entry references a missing WAV, or is missing a required field per the
  README's rules → skip that case with a logged warning; do not abort the whole run.
- Non-WAV audio file → reject, consistent with the existing STT constraint
  (`src/services/voice.py` only parses WAV via stdlib `wave`).

### Testing

This is an evaluation script, not `src/` product code, so it does not need the full
pytest discipline the rest of the repo follows. It does need:
- A small unit test for manifest parsing (missing required field → clear error, not a
  silent `KeyError`) — this is new logic.
- No new test needed for WER/CER — already covered by existing tests on
  `src/services/voice.py`.

## Open questions for the implementation plan

- Exact list of new domain cases/sentences to record (tire pressure phrasing, HVAC
  edge cases, volume) — to be finalized when writing the plan or left as a first
  implementation task.
- Whether `sherpa-onnx` install works cleanly on the Windows dev machine offline once
  downloaded (untested as of this design).

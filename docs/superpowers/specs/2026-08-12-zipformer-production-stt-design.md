# Design: Switch production STT from PhoWhisper-base to Zipformer-30M-RNNT-6000h

- Status: Draft, pending user review
- Date: 2026-08-12
- Author: brainstorming session (Claude Code) with team member
- Supersedes (engine choice only): `docs/adr/ADR-008-faster-whisper-stt-for-poc.md`

## Problem

Phase 1 of this investigation (`docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md`,
plan `docs/superpowers/plans/2026-08-12-stt-domain-eval.md`) built a WER/CER comparison
harness and ran it against `hynt/Zipformer-30M-RNNT-6000h` (via `sherpa-onnx`) vs. the
current production engine, PhoWhisper-base (via `faster-whisper`, per ADR-008). The
final run (`eval/results/stt-compare/20260812T133954.391653Z/`, 50 cases: 24 synthetic
Piper TTS + 26 real human recordings, single speaker) shows:

- Overall: PhoWhisper avg WER 26.1%, Zipformer avg WER 8.1%.
- On the 26 real-voice cases specifically: PhoWhisper avg WER 20.5%, Zipformer avg WER 3.8%.
- Reading the real-voice transcripts case by case shows PhoWhisper systematically drops
  or garbles the first word of nearly every utterance (e.g. "Áp suất lốp..." →
  "lốp hiện tại...", "Bật điều hòa" → "mật điều hòa", one case hallucinates the phrase
  "thông minh hồ ngọc hà" outright). Zipformer does not exhibit this pattern on the same
  recordings. This — not domain vocabulary specifically — looks like the dominant source
  of the original bug report ("áp suất lốp là bao nhiêu" → "nốt cà bao nhiêu").
- Zipformer's average latency (~130ms) is roughly 8x lower than PhoWhisper's (~930-1050ms)
  on the same machine.

Given this, the team wants to replace PhoWhisper-base with Zipformer as the production
STT engine behind `POST /turns/voice`.

## Decision

Full replacement, matching the precedent ADR-008 itself set (ADR-008 fully replaced
whisper.cpp rather than keeping both engines behind a flag). `STT_PROVIDER` stays a
single supported value, now `"sherpa_onnx"` instead of `"faster_whisper"` —
`get_stt_engine()` continues to reject any other value, same as today.

**Scope limitation, stated up front (mirrors ADR-008's own self-limitation):** this
decision rests on 26 real utterances from **one speaker**, plus 24 synthetic Piper TTS
utterances. It says nothing about accent, gender, age, or noise-condition diversity.
Treat it as sufficient for PoC/demo scope, not as a production-hardware-validated,
multi-speaker conclusion — exactly the caveat ADR-008 carried for its own numbers.

## Architecture

No change to the public interface of `src/services/voice.py`: `transcribe()`,
`transcribe_raw()`, `Transcript`, `get_stt_engine()`, `word_error_rate()`,
`char_error_rate()` keep their existing signatures. Callers (`src/api/turns.py`,
`src/services/ivi_events.py`, `src/services/health.py`) do not change. Only the
engine implementation inside `voice.py` changes:

- Delete `FasterWhisperEngine` (`src/services/voice.py:65-90`) and its `faster_whisper`
  import in `get_stt_engine()` (`src/services/voice.py:93-104`).
- Add a `ZipformerEngine` class, ported from `scripts/zipformer_engine.py` (built in
  Phase 1) into `src/services/voice.py`, wrapping `sherpa_onnx.OfflineRecognizer`.
  Keep the same `.transcribe_file(audio_path: Path) -> Transcript` interface
  `FasterWhisperEngine` had, and the same `threading.Lock`-based call serialization
  (`sherpa_onnx.OfflineRecognizer` has no documented thread-safety guarantee for
  concurrent `decode_streams()` calls, so keep the conservative ADR-008 pattern rather
  than assume safety not yet demonstrated).
- `get_stt_engine()` (`src/services/voice.py:93-104`) validates
  `settings.stt_provider == "sherpa_onnx"` and checks for the four required model files
  (`encoder.int8.onnx`, `decoder.int8.onnx`, `joiner.int8.onnx`, `tokens.txt`) under
  `settings.stt_model_path`, mirroring `scripts/zipformer_engine.py`'s
  `get_zipformer_engine()` validation and its `FileNotFoundError` guidance message
  (updated to point at the new setup script, not `download_zipformer_model.py`).
- **Output casing:** Zipformer emits all-uppercase, unpunctuated text (confirmed in
  Phase 1's eval transcripts), unlike PhoWhisper's natural sentence casing. Add
  `_normalize_output_casing(text: str) -> str` in `voice.py` — lowercase the whole
  string, then uppercase the first alphabetic character — applied inside
  `ZipformerEngine.transcribe_file()` before constructing the returned `Transcript`, so
  every consumer downstream (correction layer, router, transcript display) sees
  consistent casing regardless of which engine produced it. This runs before
  `normalize_vietnamese_text()` in the same way `FasterWhisperEngine.transcribe_file()`
  already calls `normalize_vietnamese_text()` today.

## Configuration (`src/config.py:57-61`)

- `stt_provider: str = "sherpa_onnx"` (was `"faster_whisper"`).
- `stt_model_path: str = "./models/voice/zipformer-30m-rnnt-6000h"` (was
  `"./models/voice/phowhisper-base-ct2"`).
- `stt_beam_size` — Whisper-specific (beam search width), meaningless for a transducer
  decoded with `greedy_search` (per Phase 1's `ZipformerEngine`). Remove the field
  rather than leave a dead config knob; check `src/config.py` and any place reading it
  (only `FasterWhisperEngine.__init__` per Phase 1's grep) before removing.
- `stt_compute_type: str = "int8"` — keep as-is; still descriptive (the Zipformer ONNX
  files are the pre-quantized `int8.onnx` variants), even though nothing reads it to
  pick a runtime quantization mode anymore (sherpa-onnx's model choice is baked into
  which files `get_stt_engine()` loads, not a runtime parameter). Note this in a code
  comment so a future reader doesn't assume it's still load-bearing.
- `stt_max_audio_seconds` — unchanged, engine-agnostic.

## Dependencies (`pyproject.toml`)

- `voice` extra (`pyproject.toml:43-46`): remove `faster-whisper>=1.0,<2`, add
  `sherpa-onnx>=1.10,<2`. Keep `piper-tts` (TTS is unaffected).
- Remove the now-redundant `stt-eval` extra (`pyproject.toml:47-51`) — `sherpa-onnx`
  becomes a `voice`-extra dependency, so the eval scripts from Phase 1
  (`scripts/eval_stt_compare.py`, `scripts/zipformer_engine.py`, etc.) pick it up
  automatically. `scripts/zipformer_engine.py`'s wrapper becomes redundant with the new
  code in `src/services/voice.py` — see "Phase 1 tooling disposition" below.
- License note: `hynt/Zipformer-30M-RNNT-6000h` is `cc-by-nc-nd-4.0`
  (non-commercial, no-derivatives). This project is a non-commercial academic
  prototype (per `CLAUDE.md`) and this change does not fine-tune or redistribute the
  weights, so this is compatible — but state it explicitly in the new ADR (below) since
  this is now a production dependency, not eval-only tooling.

## Setup tooling (`scripts/setup_voice_models.ps1`)

Currently downloads `vinai/PhoWhisper-base` and converts it via
`ct2-transformers-converter`. Replace that logic with the pinned-download +
sha256/metadata pattern already written and proven in Phase 1's
`scripts/download_zipformer_model.py` (repo `hynt/Zipformer-30M-RNNT-6000h`, pinned
revision `24ed30248e1c96bb690c81c24ab4e056f8cd9fce`, 4 files including the
`config.json`→`tokens.txt` rename). Fold that Python logic into the PowerShell script
(or have the PowerShell script shell out to a small Python helper — implementation
detail for the plan) so `scripts/setup_voice_models.ps1` remains the single documented
entry point a new team member runs. Update its final `Write-Output` message (currently
says "STT model ready: $ct2OutputDir") accordingly.

## Phase 1 tooling disposition

`scripts/eval_stt_compare.py`, `scripts/zipformer_engine.py`,
`scripts/synthesize_domain_audio.py`, `scripts/download_zipformer_model.py`, and the
`eval/datasets/poc/v1/audio/` corpus stay as-is — they remain useful for future
STT regression comparisons (e.g. testing a different candidate engine later) and their
`eval/results/stt-compare/*/` runs are the evidence this decision cites. Do not delete
them. `scripts/zipformer_engine.py`'s `ZipformerEngine`/`get_zipformer_engine()` becomes
duplicated logic once `src/services/voice.py` has its own — accept the duplication
rather than having eval tooling import from `src/` (keeps eval tooling decoupled from
production code, consistent with Phase 1's original design choice to keep them
separate) or having `src/` import from `scripts/` (wrong dependency direction for
production code). Note the duplication in a comment in both files pointing at each
other.

## Testing

- `tests/test_services/test_voice.py`: replace the three `test_faster_whisper_engine_*`
  tests (`:66`, `:81`, `:111` — transcribe/join segments, beam size config, concurrency
  serialization) with equivalent `ZipformerEngine` tests (transcribe/decode, engine
  construction from model dir, concurrency serialization using the same lock-based
  pattern). `test_get_stt_engine_rejects_incomplete_model_directory` (`:191`) needs its
  fixture updated from a PhoWhisper-shaped directory to a Zipformer-shaped one (missing
  one of the four required files).
- `tests/test_services/test_voice_integration.py`: both budget tests need real
  numbers, not guesses:
  - `test_transcribe_warm_latency_is_under_budget` (`:40`, currently `< 1500` ms):
    tighten based on Phase 1's measured ~130ms average — pick a budget with headroom
    (e.g. 500ms) rather than hugging the measured average, since this integration test
    runs on the same dev machine Phase 1 measured on, not guaranteed-identical
    conditions.
  - `test_synthetic_loopback_word_error_rate_is_under_budget` (`:63`, currently
    `< 0.22`): tighten based on Phase 1's Zipformer synthetic-only average WER (12.7%
    on the 24-case synthetic corpus) — pick a budget with headroom (e.g. 20%) rather
    than the measured figure exactly, since this test's fixture
    (`tests/fixtures/voice/synthetic_commands/`) is a different, smaller corpus than
    Phase 1's.
  - Both budgets are implementation-plan decisions, not fixed by this spec — the plan
    should re-measure on the actual implemented code before hardcoding a number, per
    this repo's "no unmeasured claims" discipline.
- Any other test file importing `FasterWhisperEngine` by name (none found outside
  `test_voice.py` in a repo-wide grep) would need the same treatment; the plan's author
  should re-grep at implementation time in case something changed between now and then.

## Documentation

- New `docs/adr/ADR-017-<slug>.md`: records this decision, cites the Phase 1 run id
  (`20260812T133954.391653Z`) as evidence, states the single-speaker scope limitation,
  states the license terms, and formally supersedes ADR-008's engine choice (ADR-008
  itself stays in place as a historical record, per this repo's ADR convention — it is
  never edited after acceptance).
- `docs/devops.md`: update wherever it documents `STT_PROVIDER=faster_whisper` as
  canonical (ADR-008 was the authorizing document for that canonical value; ADR-017
  authorizes changing it).
- `CLAUDE.md`: update the "P0 turn pipeline" section's engine reference and the
  "No LLM runs on this path" / architecture description wherever it names
  faster-whisper specifically.

## Non-goals

- No change to the correction layer (`src/services/voice_correction.py`) — it already
  operates on casefolded text and needs no changes for the new engine's output style.
- No change to `POST /turns/voice`'s API contract, `transcript.partial`/`.final` event
  shapes, or anything client-facing.
- No fine-tuning of the Zipformer model (forbidden by its `cc-by-nc-nd-4.0` license
  anyway, and out of scope).
- Multi-speaker validation, accent/dialect coverage, and real hardware (non-dev-machine)
  benchmarking remain open per the "Revisit when" section below — not blocking this
  decision, per the PoC/demo scope this repo already operates under.

## Revisit when

- More real-speaker recordings exist (multiple speakers, regions, genders) — re-run
  `scripts/eval_stt_compare.py` against the expanded corpus and confirm the margin
  holds.
- Target hardware (not this dev machine) is available for a fresh latency measurement.
- `sherpa_onnx.OfflineRecognizer`'s thread-safety is confirmed (or refuted) by its
  upstream documentation or a dedicated concurrency test — the current design keeps a
  conservative lock, costing some throughput under concurrent load, matching the same
  trade-off ADR-008 already accepted for `FasterWhisperEngine`.

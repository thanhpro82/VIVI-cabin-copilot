# Remove Voice Correction Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `correct_transcript()` from the production voice-turn pipeline because it measurably increases WER against the current Zipformer STT engine, and delete the now-dead correction-layer code and its tests.

**Architecture:** `src/api/turns.py` switches its one production STT call from `voice.transcribe()` (raw + correction) to `voice.transcribe_raw()` (raw only, already used elsewhere). `voice.transcribe()` and all of `src/services/voice_correction.py` are then unreachable and get deleted, along with their tests. Docs get a new ADR-018 plus superseded banners on the ADRs/specs/plans this reverses.

**Tech Stack:** No new dependencies. Pure Python deletion/edit within the existing `sherpa-onnx`/pytest stack.

## Global Constraints

- Use `.\.venv\Scripts\python.exe` in this worktree (this worktree's own `CLAUDE.md`/session history establishes `.venv` as the validated Python 3.11.9 interpreter here — do not switch to `.venv311`).
- Tests: `MQTT_ENABLED=false .\.venv\Scripts\python.exe -m pytest tests/ -q` must stay green (881 passed baseline before this change, per this worktree's `CLAUDE.md`; count will drop by the number of deleted tests).
- Lint: `ruff check src/ tests/` and `ruff format src/ tests/` (line-length 120, E501 ignored).
- `.gitattributes` forces LF on `.py/.md` — do not fight it; a CRLF warning from git on `docs/*.md` writes is expected and harmless (matches the earlier `docs/superpowers/specs/2026-08-13-...-design.md` commit in this session).
- Every quantitative claim in docs must trace to a real measurement already made in this session (the 50-case table in the design spec) — do not invent new numbers.
- `WORKLOG.md` / `JOURNAL.md` updates follow their existing table/section format — read the current tail of each file before appending.

---

### Task 1: Switch production call site to `transcribe_raw()` and delete the correction layer

**Files:**
- Modify: `src/api/turns.py:172`
- Modify: `src/services/voice.py:178-186` (delete `transcribe()`)
- Delete: `src/services/voice_correction.py`
- Delete: `tests/test_services/test_voice_correction.py`
- Modify: `tests/test_services/test_voice.py:154-165` (delete correction test, retarget others)
- Modify: `tests/test_services/test_voice_integration.py` (imports, 2 deleted tests, 2 retargeted tests)
- Modify: `.dockerignore` (remove 3 negation lines)

**Interfaces:**
- Consumes: `voice.transcribe_raw(audio_bytes: bytes) -> Transcript` — already exists at `src/services/voice.py:162`, unchanged by this task.
- Produces: nothing new. `voice.transcribe()` and everything in `voice_correction.py` cease to exist after this task; no other task in this plan depends on them.

- [ ] **Step 1: Confirm `transcribe()` has exactly one production caller**

Run: `grep -rn "voice\.transcribe\b" src/ | grep -v "transcribe_raw"`
Expected output: exactly one line, `src/api/turns.py:172: transcript = await asyncio.to_thread(voice.transcribe, audio_bytes)`.
If more than one line appears, stop and report — this plan assumes a single call site.

- [ ] **Step 2: Switch the production call site**

In `src/api/turns.py`, change line 172 from:

```python
            transcript = await asyncio.to_thread(voice.transcribe, audio_bytes)
```

to:

```python
            transcript = await asyncio.to_thread(voice.transcribe_raw, audio_bytes)
```

- [ ] **Step 3: Delete `transcribe()` from `src/services/voice.py`**

Remove this block (currently lines 178-186):

```python
def transcribe(audio_bytes: bytes) -> Transcript:
    # Imported lazily: src.services.voice_correction imports _edit_distance
    # from this module, so a top-level import here would be circular.
    from src.services.voice_correction import correct_transcript

    result = transcribe_raw(audio_bytes)
    corrected_text = correct_transcript(result.text)
    if corrected_text == result.text:
        return result
    return Transcript(text=corrected_text, latency_ms=result.latency_ms, confidence=result.confidence)
```

Leave `transcribe_raw()` (the function immediately above it) untouched.

- [ ] **Step 4: Delete the correction-layer module and its unit test file**

```bash
git rm src/services/voice_correction.py tests/test_services/test_voice_correction.py
```

- [ ] **Step 5: Fix `tests/test_services/test_voice.py`**

Delete this test (it exercises the now-deleted correction behavior):

```python
def test_transcribe_applies_correction_layer_to_engine_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services import voice as voice_module

    class _FakeEngine:
        def transcribe_file(self, audio_path: Path) -> voice_module.Transcript:
            return voice_module.Transcript(text="bất điều hòa", latency_ms=1.0)

    monkeypatch.setattr(voice_module, "get_stt_engine", lambda: _FakeEngine())

    result = transcribe(_make_wav_bytes())

    assert result.text == "bật điều hòa"
```

In every remaining test in this file that calls `transcribe(...)`
(`test_transcribe_rejects_empty_audio`,
`test_transcribe_rejects_audio_longer_than_max_duration`,
`test_transcribe_rejects_non_wav_bytes`,
`test_transcribe_rejects_truncated_wav_bytes_cleanly`,
`test_transcribe_rejects_non_16khz_mono_audio`,
`test_transcribe_rejects_non_16bit_audio`), replace `transcribe(` with
`transcribe_raw(` in the call — the assertions (`pytest.raises(ValueError,
match=...)`) are unchanged, since `transcribe_raw()` already performs the
same validation `transcribe()` used to delegate to.

Then find the file's import line for `transcribe` (near the top, alongside
the other `from src.services.voice import ...` names) and remove
`transcribe` from it if `transcribe_raw` is not already imported there —
check with:

Run: `grep -n "^from src.services.voice import\|^    transcribe" tests/test_services/test_voice.py`

Add `transcribe_raw` to that import if it is missing, and drop `transcribe`
if nothing in the file still calls it after the edits above.

- [ ] **Step 6: Fix `tests/test_services/test_voice_integration.py`**

Change the import line (currently line 10-11):

```python
from src.services.voice import get_stt_engine, transcribe, transcribe_raw, word_error_rate
from src.services.voice_correction import correct_transcript
```

to:

```python
from src.services.voice import get_stt_engine, transcribe_raw, word_error_rate
```

(drop `transcribe` since only `transcribe_raw` remains used, and drop the
`voice_correction` import entirely since the module no longer exists).

In `test_transcribe_warm_latency_is_under_budget` (currently lines 40-57),
replace both calls:

```python
    get_stt_engine()  # loads the CTranslate2 model into memory
    transcribe(audio_bytes)  # first call, discarded (excludes model-load variance)

    started = time.perf_counter()
    result = transcribe(audio_bytes)
```

with:

```python
    get_stt_engine()  # loads the model into memory
    transcribe_raw(audio_bytes)  # first call, discarded (excludes model-load variance)

    started = time.perf_counter()
    result = transcribe_raw(audio_bytes)
```

The 300ms budget assertion below it is unchanged — it measures the engine,
not the correction layer.

In `test_synthetic_loopback_word_error_rate_is_under_budget` (currently
lines 63-85), replace:

```python
        result = transcribe(audio_path.read_bytes())
```

with:

```python
        result = transcribe_raw(audio_path.read_bytes())
```

The 15% budget assertion is unchanged — ADR-017 measured 9.17% average WER
via `transcribe_raw()` already (the correction layer left this fixture's
output unchanged, per the docstring in the test being deleted next), so the
number this test enforces does not move.

Delete these two tests entirely (they test the deleted correction layer):

```python
def test_correction_layer_leaves_perfect_reference_text_unchanged() -> None:
    ...


@pytest.mark.skipif(
    not _synthetic_commands_available(), reason="voice model assets or synthetic command fixtures not available"
)
def test_correction_layer_never_increases_synthetic_loopback_wer() -> None:
    ...
```

(both are fully shown in the design spec's Testing section and in this
task's file-read context — delete from `def test_correction_layer_leaves_perfect_reference_text_unchanged`
through the end of `test_correction_layer_never_increases_synthetic_loopback_wer`,
i.e. the rest of the file after `test_synthetic_loopback_word_error_rate_is_under_budget`).

- [ ] **Step 7: Remove the now-dead `.dockerignore` negations**

Open `.dockerignore` and delete these 3 lines (added specifically so
`load_command_vocabulary()` could read them at runtime — no code reads them
anymore):

```
!eval/datasets/agent/v3/cases.jsonl
!eval/datasets/manual/v1/cases.jsonl
!docs/tasks/SPIKE-001-offline-ai-vertical-slice.md
```

Leave the broader `eval/`, `docs/`, `*.md` exclusion lines they were
negating untouched.

- [ ] **Step 8: Run the full test suite**

Run: `MQTT_ENABLED=false .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: all tests pass, 0 failures. Test count will be lower than the
881-passed baseline (deleted: `test_voice_correction.py`'s ~18 tests, 1 test
in `test_voice.py`, 2 tests in `test_voice_integration.py` — the latter two
are `@pytest.mark.integration`, already excluded from the default run, so
they won't show as a count change unless you also ran with `-m integration`).

- [ ] **Step 9: Lint**

Run: `.\.venv\Scripts\python.exe -m ruff check src/ tests/`
Run: `.\.venv\Scripts\python.exe -m ruff format --check src/ tests/`
Expected: no errors. If `ruff format --check` reports files needing
formatting, run `.\.venv\Scripts\python.exe -m ruff format src/ tests/` and
re-check.

- [ ] **Step 10: Commit**

```bash
git add src/api/turns.py src/services/voice.py .dockerignore \
        tests/test_services/test_voice.py tests/test_services/test_voice_integration.py
git commit -m "$(cat <<'EOF'
fix(voice): remove correction layer from production turn pipeline

Measured against Zipformer on all 50 poc/v1 cases (24 synthetic + 26 real):
both the old 47-word and new 315-word vocabularies increase average WER
(9.58% -> 13.19% / 9.90%) instead of reducing it. The layer was tuned for
PhoWhisper's ~26% WER and has no real errors left to fix at Zipformer's ~8%.
turns.py now calls transcribe_raw() directly; transcribe() and
voice_correction.py are deleted as dead code.
EOF
)"
```

---

### Task 2: Write ADR-018 and supersede the prior correction-layer docs

**Files:**
- Create: `docs/adr/ADR-018-remove-voice-correction-layer.md`
- Modify: `docs/adr/ADR-009-voice-correction-layer.md` (banner only)
- Modify: `docs/adr/ADR-012-wire-correction-layer-and-raise-wer-budget.md` (banner only)
- Modify: `docs/superpowers/specs/2026-08-08-voice-correction-layer-design.md` (banner only)
- Modify: `docs/superpowers/plans/2026-08-08-voice-correction-layer.md` (banner only)
- Modify: `docs/superpowers/specs/2026-08-12-auto-derived-command-vocabulary-design.md` (banner only)
- Modify: `docs/superpowers/plans/2026-08-12-auto-derived-command-vocabulary.md` (banner only)
- Modify: `WORKLOG.md`, `JOURNAL.md`

**Interfaces:**
- Consumes: nothing from Task 1's code (docs-only task; can run after Task 1's commit lands, references its outcome by description, not by import).
- Produces: nothing consumed by other tasks — this is the last task in the plan.

- [ ] **Step 1: Write ADR-018**

Create `docs/adr/ADR-018-remove-voice-correction-layer.md`:

```markdown
# ADR-018: Remove voice correction layer from production turn pipeline

- Status: Accepted
- Date: 2026-08-13
- Decision owner: WS1 Voice & Edge

## Context

ADR-009 added `correct_transcript()` (rule-based edit-distance-1 word
correction) to patch `faster-whisper`/PhoWhisper's STT errors, measured at
the time around 26-30% WER. ADR-017 replaced PhoWhisper with
Zipformer-30M-RNNT-6000h, measured at ~8% overall WER (~6.7% on real
voice). The follow-up work that auto-derived `correct_transcript()`'s
vocabulary from router eval data (2026-08-12, same day as ADR-017)
tripled its vocabulary from 47 to 315 words and, while testing that
change against real voice, produced a confirmed false-positive
correction ("Kiểm" -> "Hiểm" in `dom-003-spk-you-01`, a previously
perfect transcription).

That false positive prompted measuring whether the correction layer
helps or hurts at all against Zipformer's actual error profile, across
all 50 cases in `eval/datasets/poc/v1/audio/manifest.jsonl` (24 synthetic
Piper-TTS + 26 real human recordings), comparing raw Zipformer output
against both the old 47-word vocabulary and the new 315-word vocabulary:

| Condition | Avg WER (n=50) | Avg WER (real, n=26) | Helped | Hurt |
|---|---|---|---|---|
| Raw Zipformer (no correction) | 9.58% | 6.68% | — | — |
| + old vocab (47 words) | 13.19% | 10.74% | 1 | 12 |
| + new vocab (315 words) | 9.90% | 7.23% | 1 | 2 |

Both vocabularies make average WER worse. On the in-domain
control-vocabulary cases in the set (HVAC, volume, seat heat,
navigation), Zipformer already transcribes all of them correctly, so the
correction layer has no real error left to fix on the utterances that
matter for the P0 control surface — it only has correct text to
potentially corrupt.

## Decision

Remove `correct_transcript()` from the production voice-turn pipeline.
`src/api/turns.py` now calls `voice.transcribe_raw()` directly instead of
`voice.transcribe()`. `voice.transcribe()` and
`src/services/voice_correction.py` (and their tests) are deleted — not
kept as unreferenced dead code.

This is a removal, not a redesign. No replacement correction mechanism
is introduced.

## Consequences

- Production voice turns now return the Zipformer engine's raw output,
  unmodified. This is expected to be an average WER improvement of
  roughly 0.3-3.6 percentage points depending on real vs. synthetic
  audio mix, per the measurement above.
- The correction layer's original purpose — bridging PhoWhisper's error
  rate down toward budget — is moot; ADR-017 already closed that gap by
  switching engines, more effectively than post-processing could.
- If a future STT engine swap reintroduces a materially higher WER than
  Zipformer's measured ~8%, correction should be redesigned then,
  informed by that engine's actual error profile — not resurrected
  unconditionally from this ADR's deleted code.

## Revisit when

- A future STT engine change measures overall WER meaningfully above
  Zipformer's ~8% baseline (e.g. back above ~15-20%), at which point a
  correction mechanism may earn its keep again — re-run this ADR's
  50-case comparison methodology against the new engine before deciding.
```

- [ ] **Step 2: Add superseded banners**

In each of these 6 files, insert a new line directly under the existing
`- Status:` line (or, for the two plan files which may not have a
`- Status:` line, directly under the top `#` heading):

```markdown
> **Superseded by [ADR-018](../adr/ADR-018-remove-voice-correction-layer.md) (2026-08-13):** the correction layer this document describes has been removed from production. Kept as historical record of the PhoWhisper-era decision.
```

Adjust the relative path in the banner to each file's actual location
relative to `docs/adr/`:
- `docs/adr/ADR-009-voice-correction-layer.md` → `ADR-018-remove-voice-correction-layer.md` (same directory, no `../adr/` prefix)
- `docs/adr/ADR-012-wire-correction-layer-and-raise-wer-budget.md` → `ADR-018-remove-voice-correction-layer.md` (same directory)
- `docs/superpowers/specs/2026-08-08-voice-correction-layer-design.md` → `../../adr/ADR-018-remove-voice-correction-layer.md`
- `docs/superpowers/plans/2026-08-08-voice-correction-layer.md` → `../../adr/ADR-018-remove-voice-correction-layer.md`
- `docs/superpowers/specs/2026-08-12-auto-derived-command-vocabulary-design.md` → `../../adr/ADR-018-remove-voice-correction-layer.md`
- `docs/superpowers/plans/2026-08-12-auto-derived-command-vocabulary.md` → `../../adr/ADR-018-remove-voice-correction-layer.md`

Do not edit any other content in these 6 files — the banner is the only
change, so the rest remains an accurate historical record.

- [ ] **Step 3: Update WORKLOG.md and JOURNAL.md**

Read the tail of each file first to match its current table/section
format exactly:

Run: `Get-Content WORKLOG.md -Tail 30` (or the repo's usual per-member
section for today's date)
Run: `Get-Content JOURNAL.md -Tail 40`

Append an entry for 2026-08-13 (or add to today's existing entry if one is
already open) stating: removed the voice correction layer from the
production turn pipeline after measuring it increases average WER against
Zipformer (9.58% -> 13.19%/9.90% depending on vocabulary, see ADR-018);
`transcribe()` and `voice_correction.py` deleted.

- [ ] **Step 4: Verify links resolve**

Run: `grep -rn "ADR-018-remove-voice-correction-layer" docs/` and confirm
every relative path listed in Step 2 actually points at
`docs/adr/ADR-018-remove-voice-correction-layer.md` from that file's
directory (e.g. from `docs/superpowers/specs/`, `../../adr/...` resolves
to `docs/adr/...` — count the `../` against the actual directory depth of
each file before trusting the path in Step 2's list).

- [ ] **Step 5: Commit**

```bash
git add docs/adr/ADR-018-remove-voice-correction-layer.md \
        docs/adr/ADR-009-voice-correction-layer.md \
        docs/adr/ADR-012-wire-correction-layer-and-raise-wer-budget.md \
        docs/superpowers/specs/2026-08-08-voice-correction-layer-design.md \
        docs/superpowers/plans/2026-08-08-voice-correction-layer.md \
        docs/superpowers/specs/2026-08-12-auto-derived-command-vocabulary-design.md \
        docs/superpowers/plans/2026-08-12-auto-derived-command-vocabulary.md \
        WORKLOG.md JOURNAL.md
git commit -m "$(cat <<'EOF'
docs(adr): add ADR-018 removing the voice correction layer, supersede prior docs

Banners point ADR-009, ADR-012, and both correction-layer/vocabulary
spec+plan pairs at ADR-018 without rewriting their historical content.
EOF
)"
```

# Voice Correction Layer Implementation Plan

> **Superseded by [ADR-018](../../adr/ADR-018-remove-voice-correction-layer.md) (2026-08-13):** the correction layer this document describes has been removed from production. Kept as historical record of the PhoWhisper-era decision.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rule-based, edit-distance post-ASR correction layer (`src/services/voice_correction.py`) that maps out-of-vocabulary words in STT output to the nearest known command word, and measure its real effect on the existing WER fixture as a genuine held-out test.

**Architecture:** A new, standalone module — completely separate from the already-merged `src/services/voice.py` — exposes a pure function `correct_transcript(text, vocabulary, max_edit_distance)`. The vocabulary is a static, hand-extracted set of Vietnamese words taken from `docs/agent_spec.md`'s tool schema and `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md`'s example commands — never from the WER test fixtures, so measuring WER before/after on those fixtures is a real held-out evaluation, not training-on-the-test-set.

**Tech Stack:** Python 3.11, pytest. No new dependencies — reuses `_edit_distance` already defined in `src/services/voice.py`.

## Global Constraints

> **Post-hoc correction (final whole-branch review, 2026-08-08):** the
> constraint below, as originally written, claimed a guarantee that is FALSE.
> Correctness is relative to the reference transcript, not to vocabulary
> membership — a word can be a CORRECT transcription and still be outside the
> vocabulary (e.g. Vietnamese spelled-out numeral words like "hai", "bốn",
> which Whisper always emits instead of digit strings), and
> `correct_transcript()` will "correct" it into something wrong. This gap was
> found and fixed during final review by adding `PROTECTED_NUMERAL_WORDS` to
> `src/services/voice_correction.py` (never-correct set for Vietnamese
> numeral words, alongside the vocabulary and `isdigit()` checks) plus a
> regression test (`test_correction_layer_leaves_perfect_reference_text_unchanged`
> in `tests/test_services/test_voice_integration.py`). The corrected,
> narrower true invariant is: `correct_transcript()` never touches a word
> already in `vocabulary`, in `PROTECTED_NUMERAL_WORDS`, or that is numeric —
> it does NOT guarantee `corrected_wer <= raw_wer` in general; that relation
> is an empirical property of a specific vocabulary/fixture combination, not
> a structural guarantee. See ADR-009's Rationale/Consequences for the full
> writeup. The bullet below is left as originally written, for the historical
> record of what was believed at plan-writing time — do not treat it as
> current truth.

- `correct_transcript()` must NEVER touch a word that is already in the vocabulary — this is what guarantees corrected WER can only be `<=` raw WER, never worse (a word already correct can't be broken; a word already wrong either becomes right or stays wrong at the same count).
- Numeric tokens (`word.isdigit()`) are never corrected, regardless of edit distance to any vocabulary word.
- A correction only happens when there is exactly one vocabulary word at the minimum edit distance within the threshold — ties are left unchanged (no guessing).
- `COMMAND_VOCABULARY` contains only words that literally appear in `docs/agent_spec.md:117-123` or `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md:68-82` — no invented synonyms.
- Do not modify `src/services/voice.py`'s public behavior (`transcribe()`, `Transcript`, `get_stt_engine()`, etc.) — this plan only adds new files/functions and imports the existing private `_edit_distance` helper from it.
- `ruff check src/ tests/` and `ruff format --check src/ tests/` must pass (matches `.github/workflows/ci.yml`).
- Follow `docs/GIT_WORKFLOW.md`: work stays on `feature/voice-command-correction`, no direct push to `develop`/`main`.
- TDD every task: write failing test → verify it fails → minimal implementation → verify it passes → commit.
- Measure real WER numbers before writing them into any ADR — never assume improvement.

---

### Task 1: `voice_correction.py` — vocabulary + `correct_transcript()`

**Files:**
- Create: `src/services/voice_correction.py`
- Test: `tests/test_services/test_voice_correction.py`

**Interfaces:**
- Produces: `COMMAND_VOCABULARY: frozenset[str]`; `correct_transcript(text: str, vocabulary: frozenset[str] = COMMAND_VOCABULARY, max_edit_distance: int = 1) -> str`. Task 2 imports `correct_transcript` (using the default `COMMAND_VOCABULARY`) and `word_error_rate`/`transcribe` from `src.services.voice`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services/test_voice_correction.py`:

```python
from src.services.voice_correction import COMMAND_VOCABULARY, correct_transcript


def test_command_vocabulary_contains_known_command_words() -> None:
    assert "bật" in COMMAND_VOCABULARY
    assert "điều" in COMMAND_VOCABULARY
    assert "hòa" in COMMAND_VOCABULARY
    assert "cửa" in COMMAND_VOCABULARY
    assert "sổ" in COMMAND_VOCABULARY


def test_correct_transcript_leaves_known_vocabulary_words_unchanged() -> None:
    vocab = frozenset({"bật", "điều", "hòa"})
    assert correct_transcript("bật điều hòa", vocabulary=vocab) == "bật điều hòa"


def test_correct_transcript_fixes_single_char_typo_within_threshold() -> None:
    vocab = frozenset({"bật", "điều", "hòa"})
    assert correct_transcript("bất điều hòa", vocabulary=vocab, max_edit_distance=1) == "bật điều hòa"


def test_correct_transcript_leaves_word_unchanged_when_two_vocabulary_words_tie() -> None:
    vocab = frozenset({"an", "in"})
    assert correct_transcript("on", vocabulary=vocab, max_edit_distance=1) == "on"


def test_correct_transcript_leaves_word_unchanged_when_no_candidate_within_threshold() -> None:
    vocab = frozenset({"bật"})
    assert correct_transcript("xyz", vocabulary=vocab, max_edit_distance=1) == "xyz"


def test_correct_transcript_never_corrects_numeric_tokens_even_if_close_match_exists() -> None:
    vocab = frozenset({"24a"})
    assert correct_transcript("24", vocabulary=vocab, max_edit_distance=1) == "24"


def test_correct_transcript_is_idempotent() -> None:
    vocab = frozenset({"bật", "điều", "hòa"})
    once = correct_transcript("bất điều hòa", vocabulary=vocab, max_edit_distance=1)
    twice = correct_transcript(once, vocabulary=vocab, max_edit_distance=1)
    assert once == twice


def test_correct_transcript_returns_empty_or_whitespace_text_unchanged() -> None:
    assert correct_transcript("", vocabulary=frozenset({"bật"})) == ""
    assert correct_transcript("   ", vocabulary=frozenset({"bật"})) == "   "
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_voice_correction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.voice_correction'`

- [ ] **Step 3: Write minimal implementation**

Create `src/services/voice_correction.py`:

```python
from __future__ import annotations

from src.services.voice import _edit_distance

# Extracted verbatim from the literal Vietnamese phrases in
# docs/tasks/SPIKE-001-offline-ai-vertical-slice.md:68-82 (CTRL-001..010,
# NLU-001..005), cross-checked against the controllable domains in
# docs/agent_spec.md:117-123 (hvac, seat, window, door, media, navigation).
# No invented synonyms — only words that literally appear in those sources.
COMMAND_VOCABULARY: frozenset[str] = frozenset(
    {
        "bật",
        "tắt",
        "đặt",
        "tăng",
        "mở",
        "đóng",
        "phát",
        "dẫn",
        "đừng",
        "cho",
        "điều",
        "hòa",
        "nhiệt",
        "độ",
        "sưởi",
        "ghế",
        "lái",
        "mức",
        "cửa",
        "sổ",
        "bên",
        "phụ",
        "nhạc",
        "âm",
        "lượng",
        "đường",
        "poi",
        "cà",
        "phê",
        "xe",
        "lên",
        "một",
        "nửa",
        "trong",
        "nóng",
        "quá",
        "tôi",
        "hơi",
        "lạnh",
        "nó",
        "ra",
        "của",
        "ấm",
        "hơn",
        "đến",
        "thứ",
        "nhất",
    }
)


def _nearest_vocabulary_word(word: str, vocabulary: frozenset[str], max_edit_distance: int) -> str | None:
    candidates = []
    for vocab_word in vocabulary:
        distance = _edit_distance(list(word), list(vocab_word))
        if distance <= max_edit_distance:
            candidates.append((distance, vocab_word))
    if not candidates:
        return None
    best_distance = min(distance for distance, _ in candidates)
    best_matches = [vocab_word for distance, vocab_word in candidates if distance == best_distance]
    if len(best_matches) != 1:
        return None
    return best_matches[0]


def correct_transcript(
    text: str,
    vocabulary: frozenset[str] = COMMAND_VOCABULARY,
    max_edit_distance: int = 1,
) -> str:
    if not text.strip():
        return text
    corrected_words = []
    for word in text.split():
        lower_word = word.lower()
        if lower_word in vocabulary or lower_word.isdigit():
            corrected_words.append(word)
            continue
        match = _nearest_vocabulary_word(lower_word, vocabulary, max_edit_distance)
        corrected_words.append(match if match is not None else word)
    return " ".join(corrected_words)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_voice_correction.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check src/services/voice_correction.py tests/test_services/test_voice_correction.py && python -m ruff format --check src/services/voice_correction.py tests/test_services/test_voice_correction.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/services/voice_correction.py tests/test_services/test_voice_correction.py
git commit -m "feat(voice): add rule-based edit-distance correction layer for ASR output"
```

---

### Task 2: Held-out WER evaluation on the existing fixture

**Files:**
- Modify: `tests/test_services/test_voice_integration.py`

**Interfaces:**
- Consumes: `correct_transcript` (default `COMMAND_VOCABULARY`) from Task 1; `get_stt_engine`, `transcribe`, `word_error_rate` from `src.services.voice` (unchanged, already imported in this file).

- [ ] **Step 1: Write the failing test**

In `tests/test_services/test_voice_integration.py`, add this import alongside the existing ones:

```python
from src.services.voice_correction import correct_transcript
```

Then add this test function (after `test_synthetic_loopback_word_error_rate_is_under_budget`):

```python
@pytest.mark.skipif(
    not _synthetic_commands_available(), reason="voice model assets or synthetic command fixtures not available"
)
def test_correction_layer_never_increases_synthetic_loopback_wer() -> None:
    manifest = json.loads(_SYNTHETIC_COMMANDS_MANIFEST.read_text(encoding="utf-8"))

    get_stt_engine()

    raw_rates: list[float] = []
    corrected_rates: list[float] = []
    for entry in manifest:
        audio_path = _SYNTHETIC_COMMANDS_DIR / entry["file"]
        result = transcribe(audio_path.read_bytes())
        raw_rates.append(word_error_rate(entry["text"], result.text))
        corrected_text = correct_transcript(result.text)
        corrected_rates.append(word_error_rate(entry["text"], corrected_text))

    average_raw_wer = sum(raw_rates) / len(raw_rates)
    average_corrected_wer = sum(corrected_rates) / len(corrected_rates)
    print(f"\nraw WER = {average_raw_wer:.2%}, corrected WER = {average_corrected_wer:.2%}")

    # COMMAND_VOCABULARY is derived from docs/agent_spec.md and
    # docs/tasks/SPIKE-001-offline-ai-vertical-slice.md, never from this
    # fixture, so this is a genuine held-out measurement — not training on
    # the test set. correct_transcript() never touches a word already in
    # the vocabulary, so it cannot make an already-correct word wrong;
    # it can only turn a wrong out-of-vocabulary word into the right one
    # or leave it wrong at the same count. Corrected WER is therefore
    # guaranteed by construction to be <= raw WER.
    assert average_corrected_wer <= average_raw_wer
```

- [ ] **Step 2: Run the test for real**

Requires the real model assets already present from the merged `feature/faster-whisper-stt` work (`models/voice/phowhisper-base-ct2/`, `models/voice/vi_VN-piper.onnx`).

Run: `python -m pytest tests/test_services/test_voice_integration.py::test_correction_layer_never_increases_synthetic_loopback_wer -v -m integration -s`

Expected: PASS, with the printed line showing the REAL raw vs. corrected WER numbers. Record both numbers exactly as printed — they are the deliverable of this task, needed for Task 3's ADR. Do not round or approximate.

- [ ] **Step 3: Run the full non-integration suite**

Run: `python -m pytest tests/test_config.py tests/test_services/ -v -m "not integration"`
Expected: all pass (unaffected by this change).

- [ ] **Step 4: Run ruff**

Run: `python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add tests/test_services/test_voice_integration.py
git commit -m "test(voice): measure held-out WER effect of correction layer on synthetic fixture"
```

---

### Task 3: ADR-009 + WORKLOG.md

**Files:**
- Create: `docs/adr/ADR-009-voice-correction-layer.md`
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: the real raw/corrected WER numbers printed and recorded in Task 2 Step 2.

- [ ] **Step 1: Write ADR-009**

Create `docs/adr/ADR-009-voice-correction-layer.md` following the existing ADR format (see `docs/adr/ADR-008-faster-whisper-stt-for-poc.md` for section structure: Status/Date/Decision owner/Context/Alternatives/Decision/Rationale/Consequences/Revisit when). Content requirements:

- **Status**: `Accepted — follow-up to ADR-008`
- **Context**: cite the real AC2 result from ADR-008 (faster-whisper WER 30.24%, over the 20% budget). Reference the paper that motivated this (Nguyen & Cao, 2020, DOI 10.1155/2020/2312908 — note explicitly that its own reported WER reduction numbers were not independently re-verified from the source tables, only the paper's existence and general approach were confirmed via web search). State the overfitting risk that was identified and avoided: the vocabulary is NOT derived from the WER test fixtures.
- **Decision**: rule-based edit-distance correction layer, vocabulary sourced from `docs/agent_spec.md` + `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md`, `max_edit_distance=1`, single-unique-nearest-match-only policy. Explicitly NOT an SVM/CNN classifier (insufficient data — only 15 known command sentences, not real error/correct pairs).
- **Real benchmark section**: report the exact raw vs. corrected WER numbers measured in Task 2 Step 2 — pull them from that task's report/test output when this task is executed, do not write placeholder numbers now. State plainly whether the corrected number now meets the 20% AC2 budget or not — do not spin a partial improvement as full success if the budget still isn't met.
- **Consequences**: this correction layer is a standalone pure function, not yet wired into `transcribe()` or any endpoint — wiring it in is a separate future decision, once the real NLU/intent router (ADR-006) exists and can use a validated, expanded vocabulary. `COMMAND_VOCABULARY`'s 47 words only cover the literal SPIKE-001 example phrases — a real deployment needs a properly maintained vocabulary, ideally generated from the actual NLU router's tool/slot schema once it exists, not hand-copied from a spike doc.
- **Revisit when**: the NLU router (ADR-006) is implemented and defines its own canonical command vocabulary; enough real (wrong-ASR-output, correct-text) pairs exist to consider the SVM/CNN stages from the original paper; a real-speaker WER corpus becomes available to validate the correction layer beyond synthetic fixtures.

- [ ] **Step 2: Update WORKLOG.md**

Add a new row (or new dated section if today's date differs from the existing 2026-08-08 section) crediting "Nguyễn Tuấn Thành", summarizing: added rule-based edit-distance correction layer (`src/services/voice_correction.py`), vocabulary sourced from `docs/agent_spec.md`/`docs/tasks/SPIKE-001-offline-ai-vertical-slice.md` (not from WER test fixtures, avoiding overfitting), real held-out WER measurement (raw vs. corrected — cite the exact numbers from Task 2), ADR-009. Reference the real commit hashes from Tasks 1-2.

- [ ] **Step 3: Commit**

```bash
git add docs/adr/ADR-009-voice-correction-layer.md WORKLOG.md
git commit -m "docs(adr): ADR-009 - tang sua loi ASR sau STT, ghi nhan WER that truoc/sau"
```

---

## Out of scope (unchanged from the design spec)

- SVM/CNN classifier stage from the original paper.
- Wiring `correct_transcript()` into `transcribe()` or any HTTP endpoint.
- Expanding `COMMAND_VOCABULARY` beyond the two cited sources.
- Real-speaker WER corpus validation.

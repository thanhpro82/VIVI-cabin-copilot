# Auto-Derived Command Vocabulary Implementation Plan

> **Superseded by [ADR-018](../../adr/ADR-018-remove-voice-correction-layer.md) (2026-08-13):** the correction layer this document describes has been removed from production. Kept as historical record of the PhoWhisper-era decision.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-typed `COMMAND_VOCABULARY` frozenset in `src/services/voice_correction.py` with a function that derives it automatically from `eval/datasets/agent/v3/cases.jsonl`, so the correction layer's vocabulary can never silently drift from what the router actually supports.

**Architecture:** One new function, `load_command_vocabulary()`, replaces one module-level constant. `correct_transcript()`'s public signature and matching algorithm are unchanged — only its default vocabulary's source changes.

**Tech Stack:** Python 3.11 (repo venv), pytest. No new dependencies.

## Global Constraints

- Run everything through `.\.venv\Scripts\python.exe` (this worktree's venv is `.venv`; ignore any `.venv311` reference elsewhere in this repo's docs — a different branch's convention).
- ruff line-length 120, select E/F/I/N/W/UP, E501 ignored.
- Fail fast: if `eval/datasets/agent/v3/cases.jsonl` is missing or contains invalid JSON, `load_command_vocabulary()` must raise (`FileNotFoundError` / `json.JSONDecodeError`), never silently produce an empty vocabulary.
- Tire pressure/TPMS vocabulary is explicitly out of scope — it is not a controlled or queryable domain anywhere in `docs/agent_spec.md` (confirmed via `docs/coverage_matrix.md:55`), so no vocabulary source can correctly include it without a much larger, separate change.
- The derived vocabulary is substantially richer than the old hand-typed set of 47 words (315 unique words at time of final review), including every word the old `COMMAND_VOCABULARY` had that the existing tests check for (`điều`, `hòa`, `âm`, `lượng`, `một`, etc.). The count is derived from the source files and will drift as they gain cases — no test asserts it.
- **Amended in final review (2026-08-12):** the vocabulary unions three sources, not just `agent/v3`. `agent/v3` covers only direct imperatives; alone it dropped 8 words (`cho, của, hơi, lạnh, nóng, poi, trong, ấm`) and made `correct_transcript("tôi thấy nóng quá")` return `"tôi thấp đóng quá"`. `eval/datasets/manual/v1/cases.jsonl` and the `CTRL-`/`NLU-`/`PLAN-` rows of SPIKE-001's case table are now unioned in, and all paths are anchored to the repo root rather than the process CWD.

---

## Task 1: Replace `COMMAND_VOCABULARY` with `load_command_vocabulary()`

**Files:**
- Modify: `src/services/voice_correction.py:1-65` (imports, the old `COMMAND_VOCABULARY` constant and its comment) and `:67-73` (the `PROTECTED_NUMERAL_WORDS` comment, which references the old vocabulary's provenance) and `:121-125` (`correct_transcript()`'s default parameter)
- Modify: `tests/test_services/test_voice_correction.py:1-9` (the import and the one test that directly asserts on `COMMAND_VOCABULARY`)
- Modify: `tests/test_services/test_voice_integration.py:88-98,122-144` (two comment blocks that state `COMMAND_VOCABULARY`'s old provenance — now factually wrong, must be updated for accuracy, no test-behavior change)

**Interfaces:**
- Produces: `load_command_vocabulary(dataset_path: Path = DEFAULT_DATASET_PATH) -> frozenset[str]` (in `src/services/voice_correction.py`), `DEFAULT_DATASET_PATH: Path`. `correct_transcript(text, vocabulary, max_edit_distance)`'s signature, `PROTECTED_NUMERAL_WORDS`, `_nearest_vocabulary_word()`, `_match_casing()` are all unchanged — no other file imports `COMMAND_VOCABULARY` by name outside the two files this task touches (verified by repo-wide grep during planning).

- [ ] **Step 1: Write the failing tests**

In `tests/test_services/test_voice_correction.py`, replace line 1 (the import)
and lines 4-9 (`test_command_vocabulary_contains_known_command_words`) with:

```python
import json
from pathlib import Path

import pytest

from src.services.voice_correction import correct_transcript, load_command_vocabulary


def test_load_command_vocabulary_includes_known_domain_words() -> None:
    vocabulary = load_command_vocabulary()
    assert "điều" in vocabulary
    assert "hòa" in vocabulary
    assert "âm" in vocabulary
    assert "lượng" in vocabulary


def test_load_command_vocabulary_excludes_purely_numeric_tokens() -> None:
    vocabulary = load_command_vocabulary()
    assert not any(word.isdigit() for word in vocabulary)


def test_load_command_vocabulary_raises_on_missing_dataset(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.jsonl"
    with pytest.raises(FileNotFoundError):
        load_command_vocabulary(missing_path)


def test_load_command_vocabulary_raises_on_malformed_json(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text("{not valid json\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_command_vocabulary(bad_path)
```

(Every other test in this file already passes an explicit `vocabulary=` argument
except `test_correct_transcript_protects_mot_numeral_suffix_word` at the bottom
of the file, which relies on the real default vocabulary containing `"một"` —
leave that test exactly as-is; it should still pass unchanged, since `"một"`
is present in the derived vocabulary, verified during design.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice_correction.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_command_vocabulary'`.

- [ ] **Step 3: Implement**

In `src/services/voice_correction.py`, replace lines 1-65 (from the top of the
file through the end of the `COMMAND_VOCABULARY` block) with:

```python
from __future__ import annotations

import json
import string
import unicodedata
from functools import lru_cache
from pathlib import Path

from src.services.voice import _edit_distance

_PUNCTUATION = string.punctuation

DEFAULT_DATASET_PATH = Path("eval/datasets/agent/v3/cases.jsonl")


@lru_cache
def load_command_vocabulary(dataset_path: Path = DEFAULT_DATASET_PATH) -> frozenset[str]:
    """Derives the correction-layer vocabulary from the router's own eval
    dataset (same file src/agents/eval.py --mode routing uses, authored by
    the router's own author) instead of a hand-typed list, so it can never
    silently drift from what the router actually supports. Domains this
    dataset doesn't cover — e.g. tire pressure, which is not a
    controllable/queryable domain anywhere in docs/agent_spec.md, see
    docs/coverage_matrix.md — are correctly absent rather than invented.

    Raises FileNotFoundError / json.JSONDecodeError if the dataset is
    missing or malformed, rather than silently returning an empty
    vocabulary — a correction layer that can't correct anything should
    fail loudly, not quietly do nothing.
    """
    words: set[str] = set()
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        for token in case["input_text"].split():
            core = token.strip(_PUNCTUATION).lower()
            if core and not core.isdigit():
                words.add(unicodedata.normalize("NFC", core))
    return frozenset(words)
```

Then replace the `PROTECTED_NUMERAL_WORDS` comment (originally lines 67-73,
now shifted since the block above it changed size — find it by searching for
`PROTECTED_NUMERAL_WORDS: frozenset[str] = frozenset(` and look at the comment
directly above that line) from:

```python
# Vietnamese spelled-out numeral words. Whisper emits numbers this way (e.g.
# "hai mươi bốn độ", not "24 độ"), so these must never be "corrected" against
# COMMAND_VOCABULARY even though they are not literally in either of that
# vocabulary's two source documents — they are facts of the Vietnamese
# numeral system, not an observation derived from the WER test fixtures,
# so excluding them from correction does not compromise the held-out
# evaluation's overfitting-avoidance property.
```

to:

```python
# Vietnamese spelled-out numeral words. Whisper emits numbers this way (e.g.
# "hai mươi bốn độ", not "24 độ"), so these must never be "corrected" against
# the command vocabulary even though they are not necessarily part of the
# dataset load_command_vocabulary() derives from — they are facts of the
# Vietnamese numeral system, not an observation derived from the WER test
# fixtures, so excluding them from correction does not compromise the
# held-out evaluation's overfitting-avoidance property.
```

(`PROTECTED_NUMERAL_WORDS`'s frozenset contents are unchanged — only the
comment above it changes, since it referenced the old vocabulary's
provenance by name.)

Finally, find `def correct_transcript(` and change its default parameter from:

```python
def correct_transcript(
    text: str,
    vocabulary: frozenset[str] = COMMAND_VOCABULARY,
    max_edit_distance: int = 1,
) -> str:
```

to:

```python
def correct_transcript(
    text: str,
    vocabulary: frozenset[str] = load_command_vocabulary(),
    max_edit_distance: int = 1,
) -> str:
```

(Python evaluates default arguments once, at function-definition time — i.e.
once when this module is first imported — so this calls the `@lru_cache`d
loader exactly once per process, not on every `correct_transcript()` call.)

- [ ] **Step 4: Update the two stale comment blocks in `test_voice_integration.py`**

In `tests/test_services/test_voice_integration.py`, find this comment (inside
`test_correction_layer_leaves_perfect_reference_text_unchanged`, currently
around line 88-95):

```python
    # Pure unit-level check, no real model/audio needed: feeding the CORRECT
    # reference text (not ASR output) through correct_transcript() must
    # return it completely unchanged. This is the regression test for the
    # bug where Vietnamese spelled-out numeral words (e.g. "hai", "bốn" in
    # "hai mươi bốn độ") were NOT in COMMAND_VOCABULARY and got "corrected"
    # into wrong words even though they were already correct — see
    # PROTECTED_NUMERAL_WORDS in src/services/voice_correction.py.
```

Change `"were NOT in COMMAND_VOCABULARY and got"` to
`"were NOT in the command vocabulary and got"` (the rest of the comment stays
identical — it's still an accurate description of the regression this test
guards).

Find this comment (inside
`test_correction_layer_never_increases_synthetic_loopback_wer`, currently
around line 126-144):

```python
    # COMMAND_VOCABULARY is derived from docs/agent_spec.md and
    # docs/tasks/SPIKE-001-offline-ai-vertical-slice.md, never from this
    # fixture, so this is a genuine held-out measurement — not training on
    # the test set.
```

Change to:

```python
    # The command vocabulary is derived from eval/datasets/agent/v3/cases.jsonl
    # (src/services/voice_correction.py:load_command_vocabulary()), never from
    # this fixture (tests/fixtures/voice/synthetic_commands/), so this is a
    # genuine held-out measurement — not training on the test set.
```

(No other line in that comment block changes — the rest of its reasoning
about `corrected_wer <= raw_wer` not being a structural guarantee stays
accurate regardless of vocabulary source.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice_correction.py -v`
Expected: all tests pass (4 new + all pre-existing tests in the file, including
the unchanged numeral-protection test at the bottom).

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice_integration.py -v -m integration`
Expected: all 4 tests pass, including
`test_correction_layer_never_increases_synthetic_loopback_wer` — if this
specific assertion (`average_corrected_wer <= average_raw_wer`) fails under
the richer derived vocabulary where it passed under the old 47-word one,
that is real information about the new vocabulary's effect, not something to
force a pass on: STOP and report it rather than weakening the assertion or
reverting the vocabulary change (mark your final status `DONE_WITH_CONCERNS`
in that case, not `DONE`).

- [ ] **Step 6: Lint and commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/services/voice_correction.py tests/test_services/test_voice_correction.py tests/test_services/test_voice_integration.py
.\.venv\Scripts\python.exe -m ruff format src/services/voice_correction.py tests/test_services/test_voice_correction.py tests/test_services/test_voice_integration.py
git add src/services/voice_correction.py tests/test_services/test_voice_correction.py tests/test_services/test_voice_integration.py
git commit -m "feat(voice): auto-derive command vocabulary from router eval dataset"
```

---

## Task 2: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `MQTT_ENABLED=false .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 0 failures. Compare against the pre-Task-1 baseline (921 passed, 23
skipped, from the immediately preceding Zipformer-production-STT plan in this
same worktree) — count should be unchanged or have 4 more passes (the new
`load_command_vocabulary()` tests), no fewer passes, no new skips.

- [ ] **Step 2: Confirm no other file still imports the removed name**

Run: `.\.venv\Scripts\python.exe -c "import pathlib; hits = [p for p in pathlib.Path('.').rglob('*.py') if 'COMMAND_VOCABULARY' in p.read_text(encoding='utf-8') and '.venv' not in str(p)]; print(hits)"`
Expected: empty list `[]` — confirms no remaining import of the removed
`COMMAND_VOCABULARY` constant anywhere in the repo (the two files this plan
touches only reference it in prose comments now, per Task 1 Step 4, not as a
live import).

- [ ] **Step 3: Report**

No commit for this task (verification only) — summarize the final pass/skip
counts and whether Step 1 of Task 1's `test_correction_layer_never_increases_synthetic_loopback_wer`
check passed cleanly or surfaced a real WER regression worth flagging to the
human partner.

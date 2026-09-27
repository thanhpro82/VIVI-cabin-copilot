# Design: Auto-derive `COMMAND_VOCABULARY` from the router eval dataset

> **Superseded by [ADR-018](../../adr/ADR-018-remove-voice-correction-layer.md) (2026-08-13):** the correction layer this document describes has been removed from production. Kept as historical record of the PhoWhisper-era decision.

- Status: Draft, pending user review
- Date: 2026-08-12
- Author: brainstorming session (Claude Code) with team member

## Problem

`src/services/voice_correction.py`'s `COMMAND_VOCABULARY` is a hand-typed
`frozenset[str]` of 47 Vietnamese words that `correct_transcript()` uses to
fix near-miss STT errors (edit distance ≤ 1). Its own docstring says the
words were "extracted verbatim" from `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md`
and cross-checked against `docs/agent_spec.md`, specifically to avoid
inventing synonyms not backed by a real source.

This hand-typed list has gone stale: it was never updated across two full
phases of STT work in this session (an eval-tooling build and a production
engine swap), and — as discovered while investigating whether to add the
original bug's missing words ("áp", "suất", "lốp") to it — those words
*can't* be added without violating the file's own no-invented-synonyms rule,
because tire-pressure/TPMS is not a controlled or queryable domain in this
system at all (`docs/coverage_matrix.md:55`): it's explainable via RAG
manual lookup only, never a control target, and so it never appears in
`docs/agent_spec.md`.

The team wants to stop hand-maintaining this list and instead derive it
automatically from an existing, structured, already-domain-tagged data
source, so it can never silently drift out of sync with what the router
actually supports.

## Decision

Replace the hand-typed `COMMAND_VOCABULARY` constant with a function,
`load_command_vocabulary() -> frozenset[str]`, that tokenizes the utterance
text of every case in three sources and unions the result:

1. `eval/datasets/agent/v3/cases.jsonl` — `input_text` (64 cases,
   domain-tagged: hvac, music, seat, window, navigation, door, manual,
   ambiguous, unsafe, chitchat — the same file `src/agents/eval.py --mode
   routing` already uses, authored by the same person who wrote the router).
2. `eval/datasets/manual/v1/cases.jsonl` — `input_text`, the RAG
   workstream's question phrasing.
3. `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md` — the Vietnamese
   input column of the `CTRL-`/`NLU-`/`PLAN-` rows of the "PoC dataset — 30
   cases" table, which is the only place the indirect NLU phrasing ("Trong
   xe nóng quá", "Tôi hơi lạnh", "Cho ghế của tôi ấm hơn") is written down.

Source 1 alone was the original design, and it was wrong: it covers only
direct imperatives, so it silently dropped 8 words the hand-typed list had
(`cho, của, hơi, lạnh, nóng, poi, trong, ấm`) and made
`correct_transcript("tôi thấy nóng quá")` rewrite `nóng` to `đóng` — the
exact bug class `PROTECTED_NUMERAL_WORDS` exists to prevent. Sources 2 and 3
were added to close that gap; the regression is locked by
`test_load_command_vocabulary_retains_previously_covered_words` and
`test_correct_transcript_leaves_indirect_phrasing_unchanged`.

The union is substantially richer than the old hand-typed set (at time of
writing 315 unique words vs. 47), and it includes all of the old set's
domain terms (hòa, âm, lượng, cửa, sổ, ghế, sưởi, bật, tắt, đặt, tăng, giảm,
mở, đóng, ...). The exact count is derived, not maintained — it moves
whenever any of the three sources gains a case, and no test asserts it.

Tire pressure stays unaddressed by design — it is out of scope for this
system's control surface, so no vocabulary source (derived or hand-typed)
can correctly include it without first adding it as a real domain
elsewhere. The original bug report is already resolved by the Zipformer
engine switch (see `docs/adr/ADR-017-zipformer-production-stt.md`), not by
this change.

## Architecture

- `load_command_vocabulary() -> frozenset[str]`: takes no arguments; it
  unions the three fixed sources above. Each source is read by its own
  helper — `_tokenize_case_dataset(path)` for the two JSONL datasets,
  `_tokenize_spike001_table(path)` for the markdown table — and both share
  one `_tokenize()` so every source normalizes identically: split on
  whitespace, strip punctuation, lowercase, NFC-normalize, and drop purely
  numeric tokens (matching `correct_transcript()`'s existing
  `lower_word.isdigit()` skip logic, so numerals never pollute the set —
  they're excluded at the source instead of only at match time).
- `_tokenize_spike001_table()` is deliberately not a general markdown
  parser: one regex anchored to `| <CTRL|NLU|PLAN>-NNN | <text> |` scoped to
  that one table. Header, separator, `RAG-` and every other row are skipped.
- `@lru_cache`-decorated so the file is read once per process, not on every
  `correct_transcript()` call.
- Module-level `COMMAND_VOCABULARY = load_command_vocabulary()` is removed;
  `correct_transcript()`'s `vocabulary` parameter default changes to
  `def correct_transcript(text, vocabulary: frozenset[str] =
  load_command_vocabulary(), ...)`. Python evaluates default arguments once,
  at function-definition time (i.e. once when `voice_correction.py` is
  first imported), so this runs the loader exactly once per process — not
  on every call — with no extra caching logic needed beyond the `@lru_cache`
  already guarding `load_command_vocabulary()` itself (which matters for
  callers that invoke it directly, e.g. the new tests below).
- `PROTECTED_NUMERAL_WORDS` is untouched — those are linguistic facts about
  Vietnamese numerals, not domain data, and the existing comment already
  explains why they stay hand-typed.
- `AGENT_DATASET_PATH`, `MANUAL_DATASET_PATH` and `SPIKE001_DOC_PATH` are
  all anchored to the repo root via `_REPO_ROOT = Path(__file__).resolve()
  .parents[2]`, never bare relative strings. A relative `Path("eval/...")`
  resolves against the process CWD at import time, which is not the repo
  root in the container — and `.dockerignore` excludes `eval/`, `docs/` and
  `*.md` wholesale, so the files were genuinely absent from the image and
  the first voice turn died with `FileNotFoundError`. `.dockerignore` now
  carries three `!` negations re-including exactly these files, verified
  with a real `docker build` probe plus a negative control.

## Error handling

Fail fast, not silent: if `eval/datasets/agent/v3/cases.jsonl` is missing or
contains invalid JSON, `load_command_vocabulary()` raises (`FileNotFoundError`
or `json.JSONDecodeError` propagating naturally — no broad `except` that
swallows it into an empty set). Because the default argument is evaluated at
import time, this means the first `import` of `voice_correction.py` — which
happens on the first call to `transcribe()`, per `src/services/voice.py`'s
existing lazy-import pattern — fails loudly if the dataset is absent, rather
than silently running with a correction layer that never corrects anything.

## Non-goals

- Not adding tire-pressure/TPMS vocabulary — out of scope; would require
  first adding it as a real domain to `docs/agent_spec.md` and the tool
  registry, a much larger change than this file.
- Not changing `correct_transcript()`'s matching algorithm (edit distance ≤
  1, tie-breaking, numeral protection) — only its vocabulary source.
- ~~Not deriving from `eval/datasets/manual/v1` or other datasets.~~
  **Superseded during final review (2026-08-12).** `agent/v3` was chosen
  alone because it's authored by the router's own author, but it covers only
  direct imperatives; restricting to it lost 8 words of real coverage and
  reintroduced a wrong-correction bug. `manual/v1` and the SPIKE-001 case
  table are now unioned in — see Decision above.

## Testing

- `test_load_command_vocabulary_includes_known_domain_words`: assert a
  handful of words from today's hand-typed set (e.g. `"điều"`, `"hòa"`,
  `"âm"`, `"lượng"`) are present in the loaded set — a regression check that
  today's coverage isn't lost.
- `test_load_command_vocabulary_excludes_purely_numeric_tokens`: assert no
  element of the loaded set is a digit string.
- `test_tokenize_case_dataset_raises_on_missing_dataset`: pass a
  nonexistent path, assert `FileNotFoundError`. Tests the per-source helper,
  since `load_command_vocabulary()` no longer takes a path argument.
- `test_tokenize_case_dataset_raises_on_malformed_json`: pass a path to a
  `tmp_path`-written file with an invalid JSON line, assert
  `json.JSONDecodeError` (or whatever exception `json.loads` raises,
  propagated).
- `test_load_command_vocabulary_retains_previously_covered_words`: assert
  all 8 words the agent/v3-only version dropped (`cho, của, hơi, lạnh,
  nóng, poi, trong, ấm`) are present. This is the regression test for the
  coverage loss found in final review.
- `test_correct_transcript_leaves_indirect_phrasing_unchanged`: assert the
  real default vocabulary leaves `"tôi thấy nóng quá"` and `"cho ghế của
  tôi ấm hơn"` untouched — the `nóng` → `đóng` corruption.
- All existing `correct_transcript()` tests in
  `tests/test_services/test_voice_correction.py` stay unchanged — they
  already pass an explicit `vocabulary=` argument in every test case
  (confirmed: every existing test constructs its own small `frozenset` and
  passes it explicitly), so they're unaffected by the default's source
  changing.
- `tests/test_services/test_voice_integration.py`'s
  `test_correction_layer_never_increases_synthetic_loopback_wer` and
  `test_correction_layer_leaves_perfect_reference_text_unchanged` use the
  real default vocabulary — re-run them after this change and confirm they
  still pass (Task 5 of the Zipformer plan already measured
  `raw_wer == corrected_wer == 9.17%` under the old 47-word vocabulary; the
  richer derived vocabulary might change this number — if it does, that's
  real information, not something to force back into the old shape).

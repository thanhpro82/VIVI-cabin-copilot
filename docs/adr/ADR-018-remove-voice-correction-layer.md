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

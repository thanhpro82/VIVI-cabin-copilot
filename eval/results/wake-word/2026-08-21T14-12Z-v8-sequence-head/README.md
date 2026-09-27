# Wake-word run 2026-08-21T14-12Z — v8 sequence head

**Outcome: passes the false-activation gate, FAILS the recall gate. Not exported
to the frontend, and must not be shipped as a working wake word.**

Same corpus and same eight held-out speakers as the two earlier runs
(`eval/wake_word/v2_manifest.json`). What changed is the classifier
architecture, the augmentation, and both selection criteria — commits `7c31e88`,
`2770890`, `621b7e8`, `83625f4`, `e8cfb17`.

## Result

| Metric | v2 | v3 | **v8** | Gate | Verdict |
|---|---|---|---|---|---|
| False activations, `near_rhyme_en` | 60/60 clips | 0/60 | **0/60** | 0 | **passes** |
| False activations, all environments | 474/474 | 0/474 | **2/474** | — | — |
| Recall on held-out `wake` | 1.000 | 0.000 | **0.696** (195/280) | ≥ 0.95 | **fails** |
| Precision | 0.371 | 0.000 | **0.990** | — | — |

v2's recall of 1.000 was not a result — that run classified every clip `wake`.
v3's 0.000 was the mirror failure. This is the first run that both recognises
the phrase and refuses anything else, and it is still a third short of the gate.

The two false activations are one `conversation` clip and one `fpt_tts`
sentence; neither is a near-rhyme. Threshold 0.9995, selected on validation
only, under the streaming protocol.

## What moved the numbers, measured one change at a time

| Change | Held-out recall |
|---|---|
| v3 baseline (linear head on the mean-pooled embedding) | 0.000 |
| + sequence head, input normalisation, 200 epochs (v6) | 0.344 (validation) |
| + stop mixing speech negatives into wake positives (`621b7e8`) | 0.639 |
| + select the checkpoint by streaming recall, not validation loss | **0.696** |

The architecture comparison behind the first row, run on identical cached
features at the threshold where validation false activations reach zero:

| Head | Recall | English | Vietnamese |
|---|---|---|---|
| linear on mean-pooled `[96]` | 0.000 | 0.000 | 0.000 |
| MLP on mean-pooled `[96]` | 0.529 | 0.590 | 0.375 |
| MLP on sequence `[16, 96]` | 0.893 | 0.860 | 0.975 |

Rows one and two are the control: adding capacity while still averaging over
time recovers only part of it, so what was missing is the time axis. Every one
of the 576 near-rhyme negatives is English and shares its opening syllable with
the English renderings of the wake phrase; mean-pooling discards exactly the
cue that separates them, and the model resolves the conflict by going silent in
English. Vietnamese, with no competing near-rhymes, was already at 0.975.

## Correction: two figures quoted during this work were wrong

**The 0.893 and 1.000 recall figures produced by the architecture diagnostic
were measured on a protocol that favours positives, and must not be cited.**

The caching script for that diagnostic appended one second of trailing silence
to every wake clip in *all* splits, including test, while `evaluate.py` scores
the clip as stored. Windows scored per held-out clip:

| | diagnostic | `evaluate.py` |
|---|---|---|
| `wake` clips | 19 (median) | 9 (median) |
| `non_wake` clips | 16 | 16 |

Negatives were treated identically; every extra scoring opportunity went to the
positives, in the alignment regime the model handles best. The honest number is
this run's 0.696.

A related asymmetry is real and is *not* corrected here: in deployment the
detector keeps scoring after the phrase, because a person's utterance is
followed by more audio, whereas a stored wake clip stops at the phrase. So
0.696 is probably a lower bound. Fixing that belongs in the corpus, not in the
evaluation code — changing the measurement after seeing the result is exactly
what these gates exist to prevent.

## The v9 ablation (`run_manifest_v9_ablation.json`)

v9 repeated v8 with gain and sub-hop jitter disabled, to test whether the
remaining augmentation explained the gap. It did not: validation recall fell to
0.519 from v8's 0.713. v9 was **not** exported or evaluated on the held-out
split, because it lost on validation; only `run_manifest.json` is kept.

## Limits

Every voice is synthetic — 48 LibriTTS-R speakers via `piper-sample-generator`
and 9 FPT.AI Vietnamese voices. **No human speaker was recorded or measured**,
so these are an internal regression tripwire, never user-facing accuracy.

The corpus is **2 h 12 m of audio**, of which the positive class in the
training split is **28 m 55 s**. Production wake words are trained on thousands
of hours of real human speech across microphones and environments — roughly
four orders of magnitude more. The last runs are hitting that ceiling rather
than an algorithmic one.

All three acoustic environments are synthesized rather than recorded, total
3 m 17 s, and **all of it sits in the test split** — there is no non-speech
noise in training at all. That is why the augmenter had been drawing its
"noise" from speech negatives, and why removing it helped.

`test_split_used_for_training_or_selection: false` — the threshold and the
checkpoint were both selected on validation only.

"""Interactive mic-recording helper for the 10 HITL confirmation phrases
(issue #198, part 2) — the real-human counterpart to
scripts/generate_voice_hitl_fpt_audio.py. Records straight to 16kHz mono
PCM WAV (the hard constraint in src/services/voice.py) and appends each
take to manifest.jsonl in this dataset's schema
(eval/datasets/voice-hitl-confirmation/v1/audio/README.md), so
scripts/eval_voice_hitl_wer.py needs no changes to pick real takes up.

Requires the `voice` extra (`sounddevice`) — see pyproject.toml.

Usage:
    .\\.venv\\Scripts\\python.exe -m scripts.record_voice_hitl_samples --speaker-code spk01 --region north
"""

from __future__ import annotations

import argparse
import io
import json
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

from scripts.generate_voice_hitl_fpt_audio import PHRASES

SAMPLE_RATE = 16000
DEFAULT_DURATION_S = 3.0

RecordFn = Callable[[str], np.ndarray]
ConfirmFn = Callable[[str, int, np.ndarray], bool]
PlayFn = Callable[[np.ndarray], None]


def audio_id_for(phrase_index: int, speaker_code: str, take: int) -> str:
    return f"hitl-{phrase_index:02d}-real-{speaker_code}-t{take}"


def samples_to_wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.astype(np.int16).tobytes())
    return buffer.getvalue()


def build_manifest_line(
    *,
    audio_id: str,
    reference_text: str,
    speaker_code: str,
    region: str,
    noise_condition: str,
    relative_path: str,
    duration_ms: int,
) -> dict:
    return {
        "audio_id": audio_id,
        "path": relative_path,
        "reference_text": reference_text,
        "speaker_code": speaker_code,
        "region": region,
        "noise_condition": noise_condition,
        "duration_ms": duration_ms,
        "consent_scope": "internal-poc-evaluation",
    }


def append_manifest_line(manifest_path: Path, line: dict) -> None:
    with manifest_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def run_session(
    output_dir: Path,
    *,
    speaker_code: str,
    region: str,
    phrases: tuple[str, ...] = PHRASES,
    takes_per_phrase: int = 1,
    noise_condition: str = "quiet-room",
    record_fn: RecordFn,
    confirm_fn: ConfirmFn,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.jsonl"
    manifest_lines = []
    for phrase_index, phrase in enumerate(phrases, start=1):
        for take in range(1, takes_per_phrase + 1):
            while True:
                samples = record_fn(phrase)
                if confirm_fn(phrase, take, samples):
                    break
            audio_id = audio_id_for(phrase_index, speaker_code, take)
            filename = f"{audio_id}.wav"
            (output_dir / filename).write_bytes(samples_to_wav_bytes(samples))
            duration_ms = round(1000 * len(samples) / SAMPLE_RATE)
            line = build_manifest_line(
                audio_id=audio_id,
                reference_text=phrase,
                speaker_code=speaker_code,
                region=region,
                noise_condition=noise_condition,
                relative_path=filename,
                duration_ms=duration_ms,
            )
            manifest_lines.append(line)
            append_manifest_line(manifest_path, line)
    return manifest_lines


def _mic_record_fn(duration_s: float) -> RecordFn:
    import sounddevice as sd

    def _record(phrase: str) -> np.ndarray:
        input(f"\n>> '{phrase}' — nhấn Enter rồi nói ngay (ghi {duration_s:.1f}s)...")
        audio = sd.rec(int(duration_s * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
        return audio.reshape(-1)

    return _record


def make_confirm_fn(*, play_fn: PlayFn, input_fn: Callable[[str], str] = input) -> ConfirmFn:
    def _confirm(phrase: str, take: int, samples: np.ndarray) -> bool:
        while True:
            answer = input_fn(f"   Take {take} của '{phrase}' — Enter=OK, p=nghe lại, r=thu lại: ").strip().lower()
            if answer == "p":
                play_fn(samples)
                continue
            return answer != "r"

    return _confirm


def _sd_play(samples: np.ndarray) -> None:
    import sounddevice as sd

    sd.play(samples, SAMPLE_RATE)
    sd.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speaker-code", required=True, help="Pseudonymous id, e.g. spk01 (no real names).")
    parser.add_argument("--region", required=True, choices=["north", "central", "south"])
    parser.add_argument("--output-dir", type=Path, default=Path("eval/datasets/voice-hitl-confirmation/v1/audio"))
    parser.add_argument("--takes-per-phrase", type=int, default=1)
    parser.add_argument("--noise-condition", default="quiet-room")
    parser.add_argument("--duration-s", type=float, default=DEFAULT_DURATION_S)
    args = parser.parse_args()

    manifest_lines = run_session(
        args.output_dir,
        speaker_code=args.speaker_code,
        region=args.region,
        takes_per_phrase=args.takes_per_phrase,
        noise_condition=args.noise_condition,
        record_fn=_mic_record_fn(args.duration_s),
        confirm_fn=make_confirm_fn(play_fn=_sd_play),
    )
    print(f"\nWrote {len(manifest_lines)} takes to {args.output_dir}")


if __name__ == "__main__":
    main()

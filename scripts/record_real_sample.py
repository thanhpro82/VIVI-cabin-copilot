"""Records ONE real human sample from the default microphone for the STT
domain-eval corpus, saves it as 16kHz mono WAV, and appends a manifest entry
tagged as real speech (not synthetic) — see
docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md.

This is a manual, ad-hoc helper for testing with real voice; it is not part
of the Phase 1 plan's automated pipeline.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\record_real_sample.py dom-015 --speaker spk-you-01
    (records the exact reference_text for dom-015 from RECORDING_CHECKLIST.md)
"""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import sounddevice as sd

from scripts.synthesize_domain_audio import parse_checklist

SAMPLE_RATE = 16000
DEFAULT_CHECKLIST = Path("eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md")
DEFAULT_AUDIO_DIR = Path("eval/datasets/poc/v1/audio")
DEFAULT_MANIFEST = DEFAULT_AUDIO_DIR / "manifest.jsonl"


def _lookup_reference_text(audio_id: str, checklist_path: Path) -> str:
    for row_id, _domain, reference_text in parse_checklist(checklist_path):
        if row_id == audio_id:
            return reference_text
    raise ValueError(f"{audio_id!r} not found in {checklist_path}")


def record_wav(duration_s: float, warmup_s: int = 5) -> bytes:
    # Opens the mic stream and starts capturing immediately, so the device's
    # driver/AGC has warmup_s seconds to stabilize before the utterance
    # window — the countdown below runs while the mic is already recording,
    # not before it. Only the audio after warmup_s is kept.
    total_samples = int((warmup_s + duration_s) * SAMPLE_RATE)
    recording = sd.rec(total_samples, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    print("Get ready... (mic warming up)", flush=True)
    for remaining in range(warmup_s, 0, -1):
        print(remaining, flush=True)
        time.sleep(1)
    print("SPEAK NOW", flush=True)
    sd.wait()
    print("Done recording.")
    warmup_samples = int(warmup_s * SAMPLE_RATE)
    samples = recording[warmup_samples:]
    buffer_path = Path("_tmp_recording.wav")
    with wave.open(str(buffer_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(samples.tobytes())
    wav_bytes = buffer_path.read_bytes()
    buffer_path.unlink()
    return wav_bytes


def append_manifest_entry(
    manifest_path: Path,
    audio_id: str,
    wav_filename: str,
    reference_text: str,
    speaker_code: str,
    duration_ms: int,
) -> None:
    entry = {
        "audio_id": audio_id,
        "path": wav_filename,
        "reference_text": reference_text,
        "speaker_code": speaker_code,
        "region": "n/a",
        "noise_condition": "cabin-idle",
        "duration_ms": duration_ms,
        "consent_scope": "internal-poc-evaluation",
    }
    existing_lines = []
    if manifest_path.is_file():
        existing_lines = [
            line
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("audio_id") != audio_id
        ]
    existing_lines.append(json.dumps(entry, ensure_ascii=False))
    manifest_path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_id", help="e.g. dom-015 — must exist in RECORDING_CHECKLIST.md")
    parser.add_argument("--speaker", default="spk-you-01", help="pseudonymous speaker code")
    parser.add_argument("--duration", type=float, default=4.0, help="seconds to record")
    parser.add_argument("--warmup", type=int, default=5, help="seconds of countdown before recording starts")
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    reference_text = _lookup_reference_text(args.audio_id, args.checklist)
    print(f'Sentence to read aloud: "{reference_text}"')

    wav_bytes = record_wav(args.duration, args.warmup)
    wav_filename = f"{args.audio_id}-real.wav"
    wav_path = args.audio_dir / wav_filename
    wav_path.write_bytes(wav_bytes)

    with wave.open(str(wav_path), "rb") as wav_file:
        duration_ms = round(wav_file.getnframes() / wav_file.getframerate() * 1000)

    append_manifest_entry(
        args.manifest,
        audio_id=f"{args.audio_id}-real",
        wav_filename=wav_filename,
        reference_text=reference_text,
        speaker_code=args.speaker,
        duration_ms=duration_ms,
    )
    print(f"Saved {wav_path}, appended manifest entry '{args.audio_id}-real'.")
    print("Play it back to check: start " + str(wav_path))


if __name__ == "__main__":
    main()

"""Records ALL sentences in RECORDING_CHECKLIST.md from the default
microphone in one sitting, for building a real-human-voice version of the
STT domain-eval corpus. Ad-hoc manual helper, not part of the Phase 1
automated pipeline — see
docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md.

For each sentence: counts down, records, plays the recording back
immediately, then asks Enter=accept / r=redo / s=skip / q=quit. Accepted
recordings are appended to the manifest as they go, so quitting partway
through keeps everything recorded so far.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\record_real_batch.py --speaker spk-you-01
"""

from __future__ import annotations

import argparse
import winsound
from pathlib import Path

from scripts.record_real_sample import append_manifest_entry, record_wav
from scripts.synthesize_domain_audio import parse_checklist

DEFAULT_CHECKLIST = Path("eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md")
DEFAULT_AUDIO_DIR = Path("eval/datasets/poc/v1/audio")
DEFAULT_MANIFEST = DEFAULT_AUDIO_DIR / "manifest.jsonl"


def _estimate_duration_s(reference_text: str) -> float:
    word_count = len(reference_text.split())
    return max(3.0, min(8.0, word_count * 0.5 + 1.5))


def record_batch(
    checklist_path: Path, audio_dir: Path, manifest_path: Path, speaker_code: str, warmup_s: int = 5
) -> None:
    rows = parse_checklist(checklist_path)
    print(f"{len(rows)} sentences to record as speaker '{speaker_code}'.")
    print("After each recording: Enter=accept, r=redo, s=skip, q=quit.\n")

    for index, (audio_id, domain, reference_text) in enumerate(rows, start=1):
        while True:
            print(f"[{index}/{len(rows)}] ({domain}) {audio_id}")
            print(f'  Read aloud: "{reference_text}"')

            duration_s = _estimate_duration_s(reference_text)
            wav_bytes = record_wav(duration_s, warmup_s)
            wav_filename = f"{audio_id}-{speaker_code}.wav"
            wav_path = audio_dir / wav_filename
            wav_path.write_bytes(wav_bytes)

            winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)

            choice = input("  Enter=accept, r=redo, s=skip, q=quit: ").strip().lower()
            if choice == "r":
                continue
            if choice == "s":
                print("  Skipped.\n")
                break
            if choice == "q":
                print("Stopping. Everything accepted so far is already saved.")
                return
            duration_ms = round(len(wav_bytes) / 2 / 16000 * 1000)  # 16-bit mono PCM at 16kHz
            append_manifest_entry(
                manifest_path,
                audio_id=f"{audio_id}-{speaker_code}",
                wav_filename=wav_filename,
                reference_text=reference_text,
                speaker_code=speaker_code,
                duration_ms=duration_ms,
            )
            print(f"  Saved as '{audio_id}-{speaker_code}'.\n")
            break

    print("Done — all sentences processed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speaker", required=True, help="pseudonymous speaker code, e.g. spk-you-01")
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    record_batch(args.checklist, args.audio_dir, args.manifest, args.speaker)


if __name__ == "__main__":
    main()

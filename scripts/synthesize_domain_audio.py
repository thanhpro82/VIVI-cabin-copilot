"""Synthesizes the Phase 1 STT domain-eval audio corpus via Piper TTS
(already wired into this repo's production TTS path — see
src/services/voice.py:synthesize_wav). This produces synthetic audio, not
real human speech — see the "Non-goals" section of
docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md. Real recordings
can replace individual WAV files later by audio_id with no code changes.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\synthesize_domain_audio.py
"""

from __future__ import annotations

import argparse
import io
import json
import re
import wave
from pathlib import Path

import numpy as np

from src.services.voice import synthesize_wav

TARGET_SAMPLE_RATE = 16000

# Leading/trailing silence padded onto every synthesized clip. Piper emits audio
# that starts on the first phoneme with no run-up, which makes PhoWhisper clip
# the first word — a synthesis artifact that would otherwise be misread as a
# domain-vocabulary recognition failure.
ONSET_PAD_SECONDS = 0.2

# Windowed-sinc anti-aliasing filter length. 101 taps at 22050 Hz gives a
# ~720 Hz transition band with Hamming's ~53 dB stopband attenuation.
LOWPASS_NUM_TAPS = 101

# Fraction of the tighter Nyquist frequency used as the low-pass cutoff, leaving
# the remaining 10% as the transition band.
LOWPASS_CUTOFF_RATIO = 0.9

CHECKLIST_ROW_PATTERN = re.compile(r"^\|\s*(dom-\d+)\s*\|\s*([a-z_]+)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)

DEFAULT_CHECKLIST = Path("eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md")
DEFAULT_AUDIO_DIR = Path("eval/datasets/poc/v1/audio")
DEFAULT_MANIFEST = DEFAULT_AUDIO_DIR / "manifest.jsonl"


def _design_lowpass_filter(cutoff_hz: float, sample_rate: float, num_taps: int = LOWPASS_NUM_TAPS) -> np.ndarray:
    """Windowed-sinc (Hamming) FIR low-pass kernel, normalized to unity DC gain.

    numpy-only on purpose: scipy is not a dependency of this venv.
    """
    nyquist = sample_rate / 2
    normalized_cutoff = cutoff_hz / nyquist
    taps = np.arange(num_taps) - (num_taps - 1) / 2
    sinc = np.sinc(normalized_cutoff * taps)
    window = np.hamming(num_taps)
    kernel = sinc * window * normalized_cutoff
    return kernel / kernel.sum()


def _resample_wav_bytes(wav_bytes: bytes, target_rate: int) -> bytes:
    """Resample WAV audio bytes to a target sample rate.

    An anti-aliasing low-pass filter is applied *before* the linear-interpolation
    resample. Without it, every frequency above the new Nyquist folds back into
    the audible band — which corrupts exactly the consonant energy (sibilants
    s/x, aspirates th/ch) that Vietnamese domain-term recognition depends on.
    Measured before the fix: a 9500 Hz tone came out as a spurious 6500 Hz tone.

    Args:
        wav_bytes: WAV audio data as bytes (16-bit mono PCM)
        target_rate: Target sample rate in Hz

    Returns:
        Resampled WAV audio as bytes, 16-bit mono PCM

    Raises:
        ValueError: if the source is not 16-bit mono PCM.
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as src:
        orig_rate = src.getframerate()
        sampwidth = src.getsampwidth()
        channels = src.getnchannels()
        frames = src.readframes(src.getnframes())

    if sampwidth != 2 or channels != 1:
        raise ValueError(
            f"source audio must be 16-bit mono PCM, got {channels}ch/{sampwidth * 8}-bit "
            f"(sampwidth={sampwidth}, channels={channels})"
        )

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)

    if orig_rate != target_rate and samples.size:
        cutoff_hz = min(orig_rate, target_rate) / 2 * LOWPASS_CUTOFF_RATIO
        kernel = _design_lowpass_filter(cutoff_hz, orig_rate)
        samples = np.convolve(samples, kernel, mode="same")

        duration = len(samples) / orig_rate
        target_length = max(1, round(duration * target_rate))
        orig_indices = np.arange(len(samples))
        target_indices = np.linspace(0, len(samples) - 1, target_length)
        samples = np.interp(target_indices, orig_indices, samples)

    samples = np.clip(samples, -32768, 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(sampwidth)
        dst.setframerate(target_rate)
        dst.writeframes(samples.tobytes())

    return buffer.getvalue()


def _pad_wav_bytes(wav_bytes: bytes, pad_seconds: float = ONSET_PAD_SECONDS) -> bytes:
    """Pad `pad_seconds` of digital silence onto both ends of a 16-bit mono WAV."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as src:
        rate = src.getframerate()
        sampwidth = src.getsampwidth()
        channels = src.getnchannels()
        frames = src.readframes(src.getnframes())

    if sampwidth != 2 or channels != 1:
        raise ValueError(
            f"audio must be 16-bit mono PCM, got {channels}ch/{sampwidth * 8}-bit "
            f"(sampwidth={sampwidth}, channels={channels})"
        )

    silence = np.zeros(int(pad_seconds * rate), dtype=np.int16)
    samples = np.frombuffer(frames, dtype=np.int16)
    padded = np.concatenate([silence, samples, silence])

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(sampwidth)
        dst.setframerate(rate)
        dst.writeframes(padded.tobytes())

    return buffer.getvalue()


def parse_checklist(checklist_path: Path) -> list[tuple[str, str, str]]:
    text = checklist_path.read_text(encoding="utf-8")
    return [
        (audio_id, domain, reference_text) for audio_id, domain, reference_text in CHECKLIST_ROW_PATTERN.findall(text)
    ]


def _wav_duration_ms(wav_path: Path) -> int:
    with wave.open(str(wav_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
    return round(frames / rate * 1000)


def synthesize_checklist(checklist_path: Path, audio_dir: Path, manifest_path: Path) -> list[dict]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for audio_id, _domain, reference_text in parse_checklist(checklist_path):
        wav_path = audio_dir / f"{audio_id}.wav"
        # Synthesize audio, resample to 16kHz mono 16-bit PCM, then pad silence
        # onto both ends so the ASR does not clip the first word.
        wav_bytes = synthesize_wav(reference_text)
        resampled_bytes = _resample_wav_bytes(wav_bytes, TARGET_SAMPLE_RATE)
        wav_path.write_bytes(_pad_wav_bytes(resampled_bytes))
        entries.append(
            {
                "audio_id": audio_id,
                "path": wav_path.name,
                "reference_text": reference_text,
                "speaker_code": "piper-tts-synthetic",
                "region": "n/a",
                "noise_condition": "synthetic-tts",
                "duration_ms": _wav_duration_ms(wav_path),
                "consent_scope": "internal-poc-evaluation",
            }
        )
    with manifest_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    entries = synthesize_checklist(args.checklist, args.audio_dir, args.manifest)
    print(f"Synthesized {len(entries)} WAV files under {args.audio_dir}, wrote {args.manifest}")


if __name__ == "__main__":
    main()

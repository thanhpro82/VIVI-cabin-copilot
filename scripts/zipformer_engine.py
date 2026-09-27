"""Thin wrapper around sherpa-onnx's OfflineRecognizer for
hynt/Zipformer-30M-RNNT-6000h, used only by scripts/eval_stt_compare.py
(Phase 1 quick eval). Not part of src/ and not wired into STT_PROVIDER — see
docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md."""

from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np

from src.services.voice import Transcript, normalize_vietnamese_text

EXPECTED_SAMPLE_RATE = 16000
FEATURE_DIM = 80
REQUIRED_MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")


def read_wave_as_float32(audio_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(audio_path), "rb") as wav_file:
        framerate = wav_file.getframerate()
        sampwidth = wav_file.getsampwidth()
        # sampwidth is checked alongside channels/rate because the np.frombuffer
        # below hardcodes int16: a 24-bit or float WAV would otherwise decode to
        # garbage samples with no error at all.
        if wav_file.getnchannels() != 1 or framerate != EXPECTED_SAMPLE_RATE or sampwidth != 2:
            raise ValueError(
                f"audio must be 16-bit 16kHz mono WAV, got "
                f"{wav_file.getnchannels()}ch/{framerate}Hz/{sampwidth * 8}-bit"
            )
        raw_frames = wav_file.readframes(wav_file.getnframes())
    samples_int16 = np.frombuffer(raw_frames, dtype=np.int16)
    samples_float32 = samples_int16.astype(np.float32) / 32768.0
    return samples_float32, framerate


# src/services/voice.py has the production version of this class (with a normalize-casing
# step) — intentional duplication, see
# docs/superpowers/specs/2026-08-12-zipformer-production-stt-design.md's "Phase 1 tooling
# disposition" section.
class ZipformerEngine:
    def __init__(self, model_dir: Path, num_threads: int = 1) -> None:
        import sherpa_onnx  # imported lazily: heavy optional dependency, only needed for this eval script

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.int8.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=num_threads,
            sample_rate=EXPECTED_SAMPLE_RATE,
            feature_dim=FEATURE_DIM,
            decoding_method="greedy_search",
        )

    def transcribe_file(self, audio_path: Path) -> Transcript:
        samples, sample_rate = read_wave_as_float32(audio_path)
        started_ns = time.perf_counter_ns()
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self._recognizer.decode_streams([stream])
        text = stream.result.text
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        return Transcript(text=normalize_vietnamese_text(text), latency_ms=latency_ms)


def get_zipformer_engine(model_dir: Path) -> ZipformerEngine:
    missing = [name for name in REQUIRED_MODEL_FILES if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Zipformer model files missing in {model_dir}: {missing}. "
            f"Run: .\\.venv\\Scripts\\python.exe scripts\\download_zipformer_model.py"
        )
    return ZipformerEngine(model_dir)

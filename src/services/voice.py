from __future__ import annotations

import io
import tempfile
import threading
import time
import unicodedata
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from src.config import get_settings


def normalize_vietnamese_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _metric_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    without_punctuation = "".join(" " if unicodedata.category(char).startswith("P") else char for char in normalized)
    return " ".join(without_punctuation.split())


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            substitution = previous[hyp_index - 1] + (ref_item != hyp_item)
            insertion = current[hyp_index - 1] + 1
            deletion = previous[hyp_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = _metric_text(reference).split()
    hypothesis_words = _metric_text(hypothesis).split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return _edit_distance(reference_words, hypothesis_words) / len(reference_words)


def char_error_rate(reference: str, hypothesis: str) -> float:
    reference_chars = list(_metric_text(reference))
    hypothesis_chars = list(_metric_text(hypothesis))
    if not reference_chars:
        return 0.0 if not hypothesis_chars else 1.0
    return _edit_distance(reference_chars, hypothesis_chars) / len(reference_chars)


@dataclass(frozen=True)
class Transcript:
    text: str
    latency_ms: float
    # No STT engine currently in use exposes a calibrated per-utterance
    # confidence score, so this stays 0.0 until an upstream field is available.
    confidence: float = 0.0


def _normalize_output_casing(text: str) -> str:
    """Zipformer emits all-uppercase, unpunctuated text (unlike PhoWhisper's
    natural sentence casing). Lowercase everything, then capitalize the
    first alphabetic character, so transcript casing is consistent
    regardless of which engine produced it."""
    lowered = text.lower()
    for index, char in enumerate(lowered):
        if char.isalpha():
            return lowered[:index] + char.upper() + lowered[index + 1 :]
    return lowered


# scripts/zipformer_engine.py has a near-identical class for eval tooling — intentional
# duplication, see docs/superpowers/specs/2026-08-12-zipformer-production-stt-design.md's
# "Phase 1 tooling disposition" section.
class ZipformerEngine:
    """Wraps a sherpa_onnx.OfflineRecognizer-like object.

    The wrapped object's `.create_stream()` must return a stream exposing
    `.accept_waveform(sample_rate, samples)`; after `.decode_streams([stream])`
    is called on the recognizer, the stream must expose `.result.text`
    (matches `sherpa_onnx.OfflineRecognizer` and its stream/result types).

    `sherpa_onnx.OfflineRecognizer` has no documented thread-safety guarantee
    for concurrent `decode_streams()` calls, so a lock serializes access —
    the same conservative trade-off ADR-008 made for `FasterWhisperEngine`.
    """

    def __init__(self, recognizer: object) -> None:
        self._recognizer = recognizer
        self._lock = threading.Lock()

    def transcribe_file(self, audio_path: Path) -> Transcript:
        started_ns = time.perf_counter_ns()
        with wave.open(str(audio_path), "rb") as wav_file:
            raw_frames = wav_file.readframes(wav_file.getnframes())
        samples_int16 = np.frombuffer(raw_frames, dtype=np.int16)
        samples_float32 = samples_int16.astype(np.float32) / 32768.0
        # Only the recognizer calls below need the lock — it is the shared,
        # possibly-not-thread-safe object; WAV reading/decoding above is
        # per-call local state and can run concurrently.
        with self._lock:
            stream = self._recognizer.create_stream()
            stream.accept_waveform(16000, samples_float32)
            self._recognizer.decode_streams([stream])
            text = stream.result.text
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        return Transcript(text=normalize_vietnamese_text(_normalize_output_casing(text)), latency_ms=latency_ms)


@lru_cache
def get_stt_engine() -> ZipformerEngine:
    settings = get_settings()
    if settings.stt_provider != "sherpa_onnx":
        raise ValueError(f"unsupported STT_PROVIDER: only sherpa_onnx is implemented, got {settings.stt_provider!r}")
    model_path = Path(settings.stt_model_path)
    required_files = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    missing = [name for name in required_files if not (model_path / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"STT model not found or incomplete at {model_path} (missing {missing}). "
            f"Run scripts/setup_voice_models.ps1 first."
        )
    import sherpa_onnx  # imported lazily: heavy optional dependency

    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model_path / "encoder.int8.onnx"),
        decoder=str(model_path / "decoder.int8.onnx"),
        joiner=str(model_path / "joiner.int8.onnx"),
        tokens=str(model_path / "tokens.txt"),
        num_threads=1,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
    )
    return ZipformerEngine(recognizer)


def _validate_audio(audio_bytes: bytes, max_duration_s: int) -> None:
    if not audio_bytes:
        raise ValueError("audio_bytes must not be empty")
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            framerate = wav_file.getframerate()
            if not framerate:
                raise ValueError("audio_bytes must be a valid WAV file")
            if wav_file.getnchannels() != 1 or framerate != 16000 or wav_file.getsampwidth() != 2:
                raise ValueError("audio must be 16-bit 16kHz mono WAV")
            duration_s = wav_file.getnframes() / framerate
    except (wave.Error, EOFError) as exc:
        raise ValueError("audio_bytes must be a valid WAV file") from exc
    if duration_s > max_duration_s:
        raise ValueError(f"audio duration {duration_s:.1f}s exceeds {max_duration_s}s limit")


def transcribe(audio_bytes: bytes) -> Transcript:
    """Transcribes, applying the domain correction layer **only if it is enabled**.

    This is what the turn pipeline calls. The layer only rewrites a word when the word
    next to it is an exact anchor from a known command phrase — see
    `src.services.sua_chinh_ta_thoai` for why a per-word rule is unsafe (`của` and
    `cửa` are one edit apart).

    `stt_correction_enabled` defaults to **False**, so as shipped this is exactly
    `transcribe_raw`. That is a release decision, not caution for its own sake: the only
    evidence today is 16 **synthetic** Piper clips, and `src/config.py` records the three
    conditions that must hold before the default flips (review #317). Reviewers who need
    the raw path unconditionally — the WER harness — must keep calling `transcribe_raw`,
    because this function's behaviour depends on configuration.

    Until 2026-08-26 this function did not exist at all: `transcribe_raw`'s docstring
    pointed at it, `turns.py` called `transcribe_raw`, and the "correction layer" was
    a docstring promise with nothing behind it.
    """
    tho = transcribe_raw(audio_bytes)
    if not get_settings().stt_correction_enabled:
        return tho

    from src.services.sua_chinh_ta_thoai import sua_theo_cum

    da_sua = sua_theo_cum(tho.text)
    if da_sua == tho.text:
        return tho
    return Transcript(text=da_sua, latency_ms=tho.latency_ms, confidence=tho.confidence)


def transcribe_raw(audio_bytes: bytes) -> Transcript:
    """Transcribes without the correction layer (see `transcribe`). Exists so
    callers that need to measure the correction layer's effect (e.g. the WER
    regression test) can get the engine's unmodified output."""
    settings = get_settings()
    _validate_audio(audio_bytes, settings.stt_max_audio_seconds)
    engine = get_stt_engine()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)
    try:
        return engine.transcribe_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


class PiperEngine:
    """Wraps a piper-tts `PiperVoice`-like object.

    The wrapped object's `.synthesize(text)` must yield chunk objects exposing
    `.audio_int16_bytes` (raw 16-bit PCM bytes), matching `piper.voice.PiperVoice`
    and its `AudioChunk` result type (see piper-tts>=1.3 `src/piper/voice.py`).

    piper-tts makes no thread-safety guarantee either, and `asyncio.to_thread` can
    run two turns' synthesis concurrently on different threads — a lock serializes
    access, same pattern as `FasterWhisperEngine` above.
    """

    def __init__(self, voice: object) -> None:
        self._voice = voice
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        return int(self._voice.config.sample_rate)

    def synthesize_stream(self, text: str) -> Iterator[bytes]:
        normalized = normalize_vietnamese_text(text)
        with self._lock:
            for chunk in self._voice.synthesize(normalized):
                yield chunk.audio_int16_bytes


@lru_cache
def get_tts_engine() -> PiperEngine:
    settings = get_settings()
    if settings.tts_provider != "piper":
        raise ValueError(f"unsupported TTS_PROVIDER: only piper is implemented, got {settings.tts_provider!r}")
    model_path = Path(settings.tts_model_path)
    if not model_path.is_file():
        raise FileNotFoundError(f"TTS model not found at {model_path}. Run scripts/setup_voice_models.ps1 first.")
    from piper import PiperVoice  # imported lazily: heavy optional dependency

    voice = PiperVoice.load(str(model_path))
    return PiperEngine(voice)


def synthesize(text: str) -> Iterator[bytes]:
    if not text or not text.strip():
        raise ValueError("text must not be empty")
    engine = get_tts_engine()
    yield from engine.synthesize_stream(text)


def synthesize_wav(text: str) -> bytes:
    """Gói PCM stream của `synthesize()` thành một file WAV hoàn chỉnh (mono, 16-bit).

    Calls `synthesize(text)` for PCM synthesis (which validates empty text);
    calls `get_tts_engine()` for sample rate only (both calls are cached).
    """
    engine = get_tts_engine()  # For sample rate; synthesize() also calls this (cached)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(engine.sample_rate)
        # synthesize() validates empty text and yields PCM chunks
        for pcm_chunk in synthesize(text):
            wav_file.writeframes(pcm_chunk)
    return buffer.getvalue()

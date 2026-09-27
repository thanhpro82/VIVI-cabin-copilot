import io
import threading
import time
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.services.voice import (
    PiperEngine,
    ZipformerEngine,
    _normalize_output_casing,
    char_error_rate,
    normalize_vietnamese_text,
    synthesize,
    transcribe_raw,
    word_error_rate,
)


def test_normalize_vietnamese_text_collapses_whitespace_and_composes_unicode() -> None:
    decomposed = "đặt  điều   hòa"  # NFD-normalized input with extra spaces
    assert normalize_vietnamese_text(decomposed) == "đặt điều hòa"


def test_word_error_rate_is_zero_for_identical_text() -> None:
    assert word_error_rate("đặt điều hòa 24 độ", "đặt điều hòa 24 độ") == 0.0


def test_word_error_rate_counts_substitution() -> None:
    reference = "đặt điều hòa 24 độ"
    hypothesis = "đặt điều hòa 26 độ"
    assert word_error_rate(reference, hypothesis) == 1 / 5


def test_char_error_rate_ignores_punctuation_and_case() -> None:
    assert char_error_rate("Đặt điều hòa.", "đặt điều hòa") == 0.0


def _make_wav_bytes(*, duration_s: float = 1.0, frame_rate: int = 16000, sampwidth: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(sampwidth)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00" * sampwidth * int(duration_s * frame_rate))
    return buffer.getvalue()


class _FakeStreamResult:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeStream:
    def __init__(self) -> None:
        self.accepted: list[tuple[int, object]] = []
        self.result: _FakeStreamResult | None = None

    def accept_waveform(self, sample_rate, samples) -> None:
        self.accepted.append((sample_rate, samples))


class _FakeZipformerRecognizer:
    """Matches the subset of sherpa_onnx.OfflineRecognizer's interface
    ZipformerEngine uses: create_stream() and decode_streams([stream])."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.decode_calls: list[list[_FakeStream]] = []

    def create_stream(self) -> _FakeStream:
        return _FakeStream()

    def decode_streams(self, streams) -> None:
        self.decode_calls.append(streams)
        for stream in streams:
            stream.result = _FakeStreamResult(self._text)


def test_zipformer_engine_transcribe_file_normalizes_casing(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(_make_wav_bytes())
    fake_recognizer = _FakeZipformerRecognizer("ĐẶT ĐIỀU HÒA HAI MƯƠI BỐN ĐỘ")

    engine = ZipformerEngine(fake_recognizer)
    result = engine.transcribe_file(audio_path)

    assert result.text == "Đặt điều hòa hai mươi bốn độ"
    assert result.latency_ms >= 0
    assert len(fake_recognizer.decode_calls) == 1


def test_zipformer_engine_feeds_16khz_sample_rate_to_the_stream(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(_make_wav_bytes())
    fake_recognizer = _FakeZipformerRecognizer("ok")

    engine = ZipformerEngine(fake_recognizer)
    engine.transcribe_file(audio_path)

    stream = fake_recognizer.decode_calls[0][0]
    assert stream.accepted[0][0] == 16000


class _SlowFakeZipformerRecognizer:
    """Sleeps inside decode_streams() and records the max number of overlapping calls."""

    def __init__(self, sleep_s: float = 0.05) -> None:
        self._sleep_s = sleep_s
        self._active = 0
        self.max_concurrent = 0
        self._state_lock = threading.Lock()

    def create_stream(self) -> _FakeStream:
        return _FakeStream()

    def decode_streams(self, streams) -> None:
        with self._state_lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        time.sleep(self._sleep_s)
        with self._state_lock:
            self._active -= 1
        for stream in streams:
            stream.result = _FakeStreamResult("ok")


def test_zipformer_engine_serializes_concurrent_transcribe_calls(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(_make_wav_bytes())
    fake_recognizer = _SlowFakeZipformerRecognizer()
    engine = ZipformerEngine(fake_recognizer)

    threads = [threading.Thread(target=engine.transcribe_file, args=(audio_path,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert fake_recognizer.max_concurrent == 1


def test_normalize_output_casing_lowercases_and_capitalizes_first_letter() -> None:
    assert _normalize_output_casing("ÁP SUẤT LỐP LÀ BAO NHIÊU") == "Áp suất lốp là bao nhiêu"


def test_normalize_output_casing_handles_empty_string() -> None:
    assert _normalize_output_casing("") == ""


def test_transcribe_rejects_empty_audio() -> None:
    with pytest.raises(ValueError, match="empty"):
        transcribe_raw(b"")


def test_transcribe_rejects_audio_longer_than_max_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("STT_MAX_AUDIO_SECONDS", "1")
    get_settings.cache_clear()

    long_wav = _make_wav_bytes(duration_s=2.0)

    with pytest.raises(ValueError, match="exceeds"):
        transcribe_raw(long_wav)

    get_settings.cache_clear()


def test_transcribe_rejects_non_wav_bytes() -> None:
    with pytest.raises(ValueError, match="valid WAV"):
        transcribe_raw(b"not a wav file")


def test_transcribe_rejects_truncated_wav_bytes_cleanly() -> None:
    with pytest.raises(ValueError, match="valid WAV"):
        transcribe_raw(b"RIFF")


def test_transcribe_rejects_non_16khz_mono_audio() -> None:
    with pytest.raises(ValueError, match="16kHz mono"):
        transcribe_raw(_make_wav_bytes(frame_rate=22050))


def test_transcribe_rejects_non_16bit_audio() -> None:
    with pytest.raises(ValueError, match="16-bit"):
        transcribe_raw(_make_wav_bytes(sampwidth=1))


def test_get_stt_engine_rejects_unsupported_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import get_settings
    from src.services.voice import get_stt_engine

    get_settings.cache_clear()
    get_stt_engine.cache_clear()
    monkeypatch.setenv("STT_PROVIDER", "some_other_engine")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="STT_PROVIDER"):
        get_stt_engine()

    get_stt_engine.cache_clear()
    get_settings.cache_clear()


def test_get_stt_engine_rejects_incomplete_model_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.config import get_settings
    from src.services.voice import get_stt_engine

    incomplete_model_dir = tmp_path / "zipformer-30m-rnnt-6000h"
    incomplete_model_dir.mkdir()
    # encoder/decoder/joiner present, tokens.txt missing (simulates an interrupted download)
    (incomplete_model_dir / "encoder.int8.onnx").write_bytes(b"")
    (incomplete_model_dir / "decoder.int8.onnx").write_bytes(b"")
    (incomplete_model_dir / "joiner.int8.onnx").write_bytes(b"")

    get_settings.cache_clear()
    get_stt_engine.cache_clear()
    monkeypatch.setenv("STT_MODEL_PATH", str(incomplete_model_dir))
    get_settings.cache_clear()

    with pytest.raises(FileNotFoundError, match="STT model not found"):
        get_stt_engine()

    get_stt_engine.cache_clear()
    get_settings.cache_clear()


def test_get_tts_engine_rejects_unsupported_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import get_settings
    from src.services.voice import get_tts_engine

    get_settings.cache_clear()
    get_tts_engine.cache_clear()
    monkeypatch.setenv("TTS_PROVIDER", "some_other_engine")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="TTS_PROVIDER"):
        get_tts_engine()

    get_tts_engine.cache_clear()
    get_settings.cache_clear()


@dataclass
class _FakeAudioChunk:
    audio_int16_bytes: bytes


@dataclass
class _FakeVoiceConfig:
    sample_rate: int


class _FakeVoice:
    def __init__(self, chunks: list[bytes], sample_rate: int = 22050) -> None:
        self._chunks = chunks
        self.config = _FakeVoiceConfig(sample_rate=sample_rate)
        self.received_text: str | None = None

    def synthesize(
        self, text: str, syn_config: object | None = None, include_alignments: bool = False
    ) -> Iterator[_FakeAudioChunk]:
        self.received_text = text
        for chunk in self._chunks:
            yield _FakeAudioChunk(audio_int16_bytes=chunk)


def test_piper_engine_streams_multiple_chunks_that_form_valid_wav() -> None:
    chunks = [b"\x00\x01" * 100, b"\x02\x03" * 100, b"\x04\x05" * 100]
    fake_voice = _FakeVoice(chunks)
    engine = PiperEngine(fake_voice)

    collected = list(engine.synthesize_stream("  Xin  chào  "))

    assert collected == chunks
    assert len(collected) > 1
    assert fake_voice.received_text == "Xin chào"
    assert engine.sample_rate == fake_voice.config.sample_rate

    pcm_bytes = b"".join(collected)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(engine.sample_rate)
        wav_file.writeframes(pcm_bytes)
    buffer.seek(0)
    with wave.open(buffer, "rb") as wav_file:
        assert wav_file.getnframes() == len(pcm_bytes) // 2


def test_synthesize_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="empty"):
        list(synthesize("   "))


def test_synthesize_wav_returns_a_valid_wav_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services import voice as voice_module
    from src.services.voice import get_tts_engine, synthesize_wav

    get_tts_engine.cache_clear()
    chunks = [b"\x00\x01" * 50, b"\x02\x03" * 50]
    fake_voice = _FakeVoice(chunks, sample_rate=22050)
    monkeypatch.setattr(voice_module, "get_tts_engine", lambda: PiperEngine(fake_voice))

    wav_bytes = synthesize_wav("Xin chào")

    assert fake_voice.received_text == "Xin chào"
    buffer = io.BytesIO(wav_bytes)
    with wave.open(buffer, "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 22050
        pcm_out = wav_file.readframes(wav_file.getnframes())
    assert pcm_out == b"".join(chunks)

    get_tts_engine.cache_clear()


def test_synthesize_wav_rejects_empty_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services import voice as voice_module
    from src.services.voice import get_tts_engine, synthesize_wav

    get_tts_engine.cache_clear()
    chunks = [b"\x00\x01" * 50]
    fake_voice = _FakeVoice(chunks, sample_rate=22050)
    monkeypatch.setattr(voice_module, "get_tts_engine", lambda: PiperEngine(fake_voice))

    with pytest.raises(ValueError, match="empty"):
        synthesize_wav("   ")

    get_tts_engine.cache_clear()

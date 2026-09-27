import wave
from pathlib import Path

import numpy as np
import pytest

from scripts.zipformer_engine import get_zipformer_engine, read_wave_as_float32

FIXTURE = Path("tests/fixtures/voice/warm_sample.wav")


def test_read_wave_as_float32_returns_normalized_samples_and_sample_rate() -> None:
    samples, sample_rate = read_wave_as_float32(FIXTURE)

    assert sample_rate == 16000
    assert samples.dtype == np.float32
    assert samples.shape[0] == 22291
    assert samples.min() >= -1.0
    assert samples.max() <= 1.0


def test_read_wave_as_float32_rejects_non_16khz_or_stereo(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.wav"
    with wave.open(str(bad_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 4)

    with pytest.raises(ValueError, match="16kHz mono"):
        read_wave_as_float32(bad_path)


def test_read_wave_as_float32_rejects_non_16bit_sample_width(tmp_path: Path) -> None:
    """np.frombuffer below hardcodes int16 — an 8/24-bit WAV would otherwise
    decode to garbage samples with no error at all."""
    bad_path = tmp_path / "bad_width.wav"
    with wave.open(str(bad_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00" * 8)

    with pytest.raises(ValueError, match="16-bit"):
        read_wave_as_float32(bad_path)


def test_get_zipformer_engine_raises_clear_error_when_model_files_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="download_zipformer_model"):
        get_zipformer_engine(tmp_path)

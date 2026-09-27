import io
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from scripts.synthesize_domain_audio import (
    _pad_wav_bytes,
    _resample_wav_bytes,
    parse_checklist,
    synthesize_checklist,
)
from src.config import get_settings

_CHECKLIST_FIXTURE = (
    "# heading\n\n"
    "| audio_id | domain        | reference_text |\n"
    "|----------|---------------|-----------------|\n"
    "| dom-001  | tire_pressure | Áp suất lốp hiện tại là bao nhiêu |\n"
    "| dom-002  | hvac          | Bật điều hòa |\n"
)


def _tts_model_available() -> bool:
    return Path(get_settings().tts_model_path).is_file()


def test_parse_checklist_extracts_all_data_rows(tmp_path: Path) -> None:
    checklist_path = tmp_path / "checklist.md"
    checklist_path.write_text(_CHECKLIST_FIXTURE, encoding="utf-8")

    rows = parse_checklist(checklist_path)

    assert rows == [
        ("dom-001", "tire_pressure", "Áp suất lốp hiện tại là bao nhiêu"),
        ("dom-002", "hvac", "Bật điều hòa"),
    ]


def test_parse_checklist_skips_header_and_separator_rows(tmp_path: Path) -> None:
    checklist_path = tmp_path / "checklist.md"
    checklist_path.write_text(_CHECKLIST_FIXTURE, encoding="utf-8")

    rows = parse_checklist(checklist_path)

    assert all(audio_id.startswith("dom-") for audio_id, _, _ in rows)


@pytest.mark.integration
@pytest.mark.skipif(not _tts_model_available(), reason="Piper TTS model not available")
def test_synthesize_checklist_writes_wav_and_manifest(tmp_path: Path) -> None:
    checklist_path = tmp_path / "checklist.md"
    checklist_path.write_text(_CHECKLIST_FIXTURE, encoding="utf-8")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"

    entries = synthesize_checklist(checklist_path, audio_dir, manifest_path)

    assert (audio_dir / "dom-001.wav").is_file()
    assert (audio_dir / "dom-002.wav").is_file()
    assert len(entries) == 2
    assert entries[0]["audio_id"] == "dom-001"
    assert entries[0]["reference_text"] == "Áp suất lốp hiện tại là bao nhiêu"
    assert entries[0]["speaker_code"] == "piper-tts-synthetic"
    assert entries[0]["noise_condition"] == "synthetic-tts"
    assert entries[0]["duration_ms"] > 0

    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 2
    assert json.loads(manifest_lines[0])["audio_id"] == "dom-001"


def test_resample_wav_bytes_converts_22050hz_to_16000hz() -> None:
    """Test that _resample_wav_bytes resamples 22050 Hz audio to 16000 Hz."""
    # Create a synthetic WAV at 22050 Hz with silence
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        # Write 1 second of silence (22050 samples at 22050 Hz)
        silence = np.zeros(22050, dtype=np.int16)
        wav_file.writeframes(silence.tobytes())

    original_bytes = buffer.getvalue()

    # Resample to 16000 Hz
    resampled_bytes = _resample_wav_bytes(original_bytes, 16000)

    # Verify the output has the correct sample rate
    with wave.open(io.BytesIO(resampled_bytes), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        # Duration should be approximately 1 second
        frames = wav_file.getnframes()
        expected_frames = 16000
        # Allow 1 frame of rounding error
        assert abs(frames - expected_frames) <= 1


def _tone_wav_bytes(freq_hz: float, sample_rate: int, seconds: float = 1.0) -> bytes:
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    samples = (np.sin(2 * np.pi * freq_hz * t) * 20000).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())
    return buffer.getvalue()


def _dominant_frequency(wav_bytes: bytes) -> tuple[float, float]:
    """Returns (dominant frequency in Hz, its magnitude relative to full scale)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        rate = wav_file.getframerate()
        samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16).astype(np.float64)
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / rate)
    peak = int(np.argmax(spectrum))
    return float(freqs[peak]), float(spectrum[peak] / (len(samples) / 2 * 32768))


def test_resample_wav_bytes_lowpass_prevents_aliasing_of_9500hz_tone() -> None:
    """A 9500 Hz tone is above the 8000 Hz Nyquist of the 16 kHz target.

    Without an anti-aliasing filter it folds back to a spurious 22050-9500 =
    12550 -> 16000-12550 = 3450... measured empirically as a 6500 Hz artifact.
    With the filter it must be attenuated into the noise floor instead.
    """
    source = _tone_wav_bytes(9500.0, 22050)

    _, source_magnitude = _dominant_frequency(source)
    assert source_magnitude > 0.1, "sanity: the input tone should be strong"

    resampled = _resample_wav_bytes(source, 16000)
    dominant_hz, magnitude = _dominant_frequency(resampled)

    # No surviving tone anywhere: the whole spectrum is >40 dB down from input.
    assert magnitude < source_magnitude * 0.01, (
        f"aliased energy survived: {magnitude:.5f} at {dominant_hz:.0f} Hz vs input {source_magnitude:.5f}"
    )
    # And specifically nothing at the aliased image location.
    assert not (6000 < dominant_hz < 7000), f"dominant output bin at {dominant_hz:.0f} Hz looks like the alias"


def test_resample_wav_bytes_preserves_in_band_tone() -> None:
    """The filter must not eat legitimate speech-band content."""
    source = _tone_wav_bytes(1000.0, 22050)

    resampled = _resample_wav_bytes(source, 16000)
    dominant_hz, magnitude = _dominant_frequency(resampled)

    assert abs(dominant_hz - 1000.0) < 20.0
    assert magnitude > 0.1


def test_resample_wav_bytes_rejects_non_16bit_source() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00" * 100)

    with pytest.raises(ValueError, match="16-bit mono"):
        _resample_wav_bytes(buffer.getvalue(), 16000)


def test_resample_wav_bytes_rejects_stereo_source() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)

    with pytest.raises(ValueError, match="16-bit mono"):
        _resample_wav_bytes(buffer.getvalue(), 16000)


def test_pad_wav_bytes_adds_silence_to_both_ends() -> None:
    source = _tone_wav_bytes(1000.0, 16000, seconds=0.5)

    padded = _pad_wav_bytes(source, pad_seconds=0.2)

    with wave.open(io.BytesIO(padded), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)

    pad_frames = int(0.2 * 16000)
    assert len(samples) == 8000 + 2 * pad_frames
    assert np.all(samples[:pad_frames] == 0)
    assert np.all(samples[-pad_frames:] == 0)
    assert np.any(samples[pad_frames:-pad_frames] != 0)

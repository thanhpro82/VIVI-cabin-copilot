from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

import offline_poc.tts as tts_module
from offline_poc.stt import (
    PhoWhisperAdapter,
    WhisperCppAdapter,
    char_error_rate,
    word_error_rate,
)
from offline_poc.tts import PiperAdapter


def test_whisper_adapter_returns_normalized_transcript(tmp_path: Path) -> None:
    captured: list[str] = []

    def fake_runner(command: list[str]) -> str:
        captured.extend(command)
        return '{"transcription":[{"text":"  đặt  điều hòa 24 độ  "}]}'

    adapter = WhisperCppAdapter(Path("whisper-cli"), Path("model.bin"), fake_runner)
    result = adapter.transcribe(tmp_path / "input.wav")

    assert result.text == "đặt điều hòa 24 độ"
    assert result.total_ms >= 0
    assert captured == [
        "whisper-cli",
        "-m",
        "model.bin",
        "-f",
        str(tmp_path / "input.wav"),
        "-l",
        "vi",
        "-oj",
    ]


def test_piper_adapter_writes_wav(tmp_path: Path) -> None:
    captured_text: list[str] = []

    def fake_runner(command: list[str], text: str) -> None:
        captured_text.append(text)
        Path(command[-1]).write_bytes(b"RIFF-test")

    output = tmp_path / "answer.wav"
    measurement = PiperAdapter(
        Path("piper"), Path("vi.onnx"), fake_runner
    ).synthesize("  Đã  đặt 24 độ ", output)

    assert output.read_bytes().startswith(b"RIFF")
    assert captured_text == ["Đã đặt 24 độ"]
    assert measurement.total_ms >= 0


def test_default_piper_runner_forces_utf8_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        input: str,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: int,
        encoding: str,
        env: dict[str, str],
    ) -> object:
        captured.update(
            input=input,
            encoding=encoding,
            python_utf8=env.get("PYTHONUTF8"),
        )
        Path(command[-1]).write_bytes(b"RIFF-test")
        return object()

    monkeypatch.setattr(tts_module.subprocess, "run", fake_run)
    measurement = PiperAdapter(Path("piper"), Path("vi.onnx")).synthesize(
        "Đặt điều hòa 24 độ", tmp_path / "answer.wav"
    )

    assert captured == {
        "input": "Đặt điều hòa 24 độ",
        "encoding": "utf-8",
        "python_utf8": "1",
    }
    assert measurement.peak_rss_bytes > 0


def test_phowhisper_offline_mode_rejects_remote_model_id() -> None:
    with pytest.raises(ValueError, match="local path"):
        PhoWhisperAdapter("vinai/PhoWhisper-small", offline_mode=True)


def test_phowhisper_reads_wav_without_ffmpeg(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 160)

    captured: dict[str, object] = {}

    class FakePipeline:
        feature_extractor = SimpleNamespace(sampling_rate=16000)

        def __call__(self, audio: object, **kwargs: object) -> dict[str, str]:
            captured.update(audio=audio, kwargs=kwargs)
            return {"text": " đặt điều hòa 24 độ "}

    def fake_factory(*args: object, **kwargs: object) -> FakePipeline:
        captured["factory_kwargs"] = kwargs
        return FakePipeline()

    result = PhoWhisperAdapter(
        tmp_path, pipeline_factory=fake_factory
    ).transcribe(audio_path)

    assert result.text == "đặt điều hòa 24 độ"
    assert isinstance(captured["audio"], dict)
    assert captured["audio"]["sampling_rate"] == 16000
    assert "raw" in captured["audio"]
    assert len(captured["audio"]["raw"]) == 116
    assert "local_files_only" not in captured["factory_kwargs"]


def test_error_rates_normalize_unicode_but_keep_vietnamese_diacritics() -> None:
    decomposed = "đặt điều hòa"
    composed = "đặt điều hòa"

    assert word_error_rate(composed, decomposed) == 0
    assert char_error_rate(composed, decomposed) == 0
    assert word_error_rate(composed, "dat dieu hoa") > 0
    assert char_error_rate(composed, "dat dieu hoa") > 0

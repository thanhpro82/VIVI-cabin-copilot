# Voice Adapter (whisper.cpp ASR + Piper TTS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an internal `src/services/voice.py` module that transcribes Vietnamese audio via whisper.cpp (running a GGML-converted PhoWhisper-small checkpoint) and synthesizes Vietnamese speech via Piper, with no new HTTP endpoints.

**Architecture:** Two thin adapter classes (`WhisperCppEngine`, `PiperEngine`) wrap external processes/libraries behind injectable interfaces (subprocess runner for STT, a loaded `PiperVoice` object for TTS), each exposed through an `lru_cache`-backed singleton getter (`get_stt_engine()`, `get_tts_engine()`) mirroring the existing `get_settings()` pattern in `src/config.py`. Public functions `transcribe(audio_bytes)` and `synthesize(text)` are the only entry points other code will call.

**Tech Stack:** Python 3.11, whisper.cpp (native binary, subprocess), `piper-tts` (Python package), pydantic-settings, pytest.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-08-07-voice-asr-tts-design.md`; architecture decision: `docs/adr/ADR-007-voice-adapter-engine-binding.md`.
- No changes to `src/api/routes.py` or `src/models/schemas.py` — this plan produces an internal module only, no HTTP route.
- Settings must be named to match `docs/devops.md`'s Environment contract exactly: `STT_PROVIDER`, `STT_MODEL_PATH`, `TTS_PROVIDER`, `TTS_MODEL_PATH` (pydantic-settings maps these automatically from lowercase field names `stt_provider`, `stt_model_path`, `tts_provider`, `tts_model_path`).
- STT engine is whisper.cpp (`STT_PROVIDER=whisper_cpp`), not faster-whisper/CTranslate2 or Transformers — per ADR-007.
- Max accepted audio duration is 30 seconds (matches the implicit voice-turn cap referenced across `docs/api_spec.md`).
- All unit tests must run without any real model file or binary present (inject fakes) — CI never downloads or runs real models (`docs/devops.md`: "CI runs lint, unit, contract, and mock smoke checks with tiny fixtures only; it never downloads or stores large models").
- Integration tests that need real model assets are marked `@pytest.mark.integration` and skip automatically when the configured paths don't exist locally.
- Work happens on branch `feature/voice-asr-tts-design` (already created off `develop`); do not push directly to `develop`/`main` (`docs/GIT_WORKFLOW.md`).
- Follow existing code style: ruff (line-length 120, `py311` target), `from __future__ import annotations` where the codebase already uses it (matches `experiments/offline_poc` adapters).

---

### Task 1: Voice settings in `src/config.py`

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py` (new file)

**Interfaces:**
- Produces: `Settings.stt_provider: str`, `Settings.stt_executable_path: str`, `Settings.stt_model_path: str`, `Settings.stt_max_audio_seconds: int`, `Settings.tts_provider: str`, `Settings.tts_model_path: str` — all consumed by Task 3/4's `get_stt_engine()`/`get_tts_engine()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
from src.config import Settings


def test_voice_settings_have_canonical_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.stt_provider == "whisper_cpp"
    assert settings.stt_executable_path == "whisper-cli"
    assert settings.stt_model_path == "./models/voice/ggml-phowhisper-small.bin"
    assert settings.stt_max_audio_seconds == 30
    assert settings.tts_provider == "piper"
    assert settings.tts_model_path == "./models/voice/vi_VN-piper.onnx"


def test_voice_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "/custom/model.bin")
    monkeypatch.setenv("TTS_MODEL_PATH", "/custom/voice.onnx")

    settings = Settings(_env_file=None)

    assert settings.stt_model_path == "/custom/model.bin"
    assert settings.tts_model_path == "/custom/voice.onnx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'stt_provider'`

- [ ] **Step 3: Implement the settings fields**

In `src/config.py`, add after the existing `# Vector Store` block (before `@lru_cache`):

```python
    # Voice adapter (STT/TTS) — names match docs/devops.md Environment contract
    stt_provider: str = "whisper_cpp"
    stt_executable_path: str = "whisper-cli"
    stt_model_path: str = "./models/voice/ggml-phowhisper-small.bin"
    stt_max_audio_seconds: int = Field(default=30, ge=1, le=30)
    tts_provider: str = "piper"
    tts_model_path: str = "./models/voice/vi_VN-piper.onnx"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(config): thêm settings cho voice adapter (STT/TTS)"
```

---

### Task 2: Vietnamese text normalization and WER/CER metrics

**Files:**
- Create: `src/services/voice.py`
- Create: `tests/test_services/__init__.py`
- Test: `tests/test_services/test_voice.py` (new file, extended in later tasks)

**Interfaces:**
- Produces: `normalize_vietnamese_text(text: str) -> str`, `word_error_rate(reference: str, hypothesis: str) -> float`, `char_error_rate(reference: str, hypothesis: str) -> float` — consumed by Task 3 (`WhisperCppEngine`) and Task 6 (WER integration test).

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/__init__.py` (empty file).

Create `tests/test_services/test_voice.py`:

```python
from src.services.voice import (
    char_error_rate,
    normalize_vietnamese_text,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_services/test_voice.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.voice'`

- [ ] **Step 3: Implement the metrics module**

Create `src/services/voice.py`:

```python
from __future__ import annotations

import unicodedata


def normalize_vietnamese_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _metric_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in normalized
    )
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_services/test_voice.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/voice.py tests/test_services/
git commit -m "feat(voice): thêm normalize/WER/CER cho tiếng Việt"
```

---

### Task 3: STT engine (`WhisperCppEngine`) and `transcribe()`

**Files:**
- Modify: `src/services/voice.py`
- Modify: `tests/test_services/test_voice.py`

**Interfaces:**
- Consumes: `normalize_vietnamese_text` (Task 2), `Settings.stt_provider/stt_executable_path/stt_model_path/stt_max_audio_seconds` (Task 1) via `src.config.get_settings()`.
- Produces: `Transcript(text: str, latency_ms: float, confidence: float = 0.0)` dataclass, `WhisperCppEngine(executable: Path, model_path: Path, runner: WhisperRunner | None = None)` with `.transcribe_file(audio_path: Path) -> Transcript`, `get_stt_engine() -> WhisperCppEngine`, `transcribe(audio_bytes: bytes) -> Transcript` — consumed by Task 6 (integration test) and any future caller.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_voice.py`:

```python
import io
from pathlib import Path
import wave

import pytest

from src.services.voice import Transcript, WhisperCppEngine, transcribe


def _make_wav_bytes(*, duration_s: float = 1.0, frame_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00\x00" * int(duration_s * frame_rate))
    return buffer.getvalue()


def test_whisper_cpp_engine_transcribe_file_returns_normalized_text(tmp_path: Path) -> None:
    captured_commands: list[list[str]] = []

    def fake_runner(command: list[str]) -> str:
        captured_commands.append(command)
        return '{"transcription":[{"text":"  đặt  điều hòa 24 độ  "}]}'

    engine = WhisperCppEngine(Path("whisper-cli"), Path("model.bin"), fake_runner)
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(_make_wav_bytes())

    result = engine.transcribe_file(audio_path)

    assert result.text == "đặt điều hòa 24 độ"
    assert result.latency_ms >= 0
    assert captured_commands == [
        ["whisper-cli", "-m", "model.bin", "-f", str(audio_path), "-l", "vi", "-oj"]
    ]


def test_transcribe_rejects_empty_audio() -> None:
    with pytest.raises(ValueError, match="empty"):
        transcribe(b"")


def test_transcribe_rejects_audio_longer_than_max_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("STT_MAX_AUDIO_SECONDS", "1")
    get_settings.cache_clear()

    long_wav = _make_wav_bytes(duration_s=2.0)

    with pytest.raises(ValueError, match="exceeds"):
        transcribe(long_wav)

    get_settings.cache_clear()


def test_transcribe_rejects_non_wav_bytes() -> None:
    with pytest.raises(ValueError, match="valid WAV"):
        transcribe(b"not a wav file")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_services/test_voice.py -v`
Expected: FAIL with `ImportError: cannot import name 'Transcript' from 'src.services.voice'`

- [ ] **Step 3: Implement the STT engine**

Append to `src/services/voice.py`:

```python
from dataclasses import dataclass
from functools import lru_cache
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Callable, Iterator
import wave

from src.config import get_settings


@dataclass(frozen=True)
class Transcript:
    text: str
    latency_ms: float
    # whisper.cpp's -oj JSON output does not expose a calibrated per-utterance
    # confidence score, so this stays 0.0 until an upstream field is available.
    confidence: float = 0.0


WhisperRunner = Callable[[list[str]], str]


def _default_whisper_runner(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout


class WhisperCppEngine:
    def __init__(
        self,
        executable: Path,
        model_path: Path,
        runner: WhisperRunner | None = None,
    ) -> None:
        self.executable = executable
        self.model_path = model_path
        self.runner = runner or _default_whisper_runner

    def transcribe_file(self, audio_path: Path) -> Transcript:
        command = [
            str(self.executable),
            "-m",
            str(self.model_path),
            "-f",
            str(audio_path),
            "-l",
            "vi",
            "-oj",
        ]
        started_ns = time.perf_counter_ns()
        output = self.runner(command)
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        payload = json.loads(output)
        segments = payload.get("transcription", [])
        text = " ".join(str(segment.get("text", "")) for segment in segments)
        return Transcript(text=normalize_vietnamese_text(text), latency_ms=latency_ms)


@lru_cache
def get_stt_engine() -> WhisperCppEngine:
    settings = get_settings()
    executable = Path(settings.stt_executable_path)
    model_path = Path(settings.stt_model_path)
    if not model_path.is_file():
        raise FileNotFoundError(
            f"STT model not found at {model_path}. Run scripts/setup_voice_models.ps1 first."
        )
    return WhisperCppEngine(executable, model_path)


def _validate_audio(audio_bytes: bytes, max_duration_s: int) -> None:
    if not audio_bytes:
        raise ValueError("audio_bytes must not be empty")
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            duration_s = wav_file.getnframes() / wav_file.getframerate()
    except wave.Error as exc:
        raise ValueError("audio_bytes must be a valid WAV file") from exc
    if duration_s > max_duration_s:
        raise ValueError(
            f"audio duration {duration_s:.1f}s exceeds {max_duration_s}s limit"
        )


def transcribe(audio_bytes: bytes) -> Transcript:
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
```

Note: `get_stt_engine` is `lru_cache`-decorated, so a test that wants a fresh engine per call must not go through it — tests exercise `WhisperCppEngine` directly (as above) or clear caches explicitly like `test_transcribe_rejects_audio_longer_than_max_duration` does for `get_settings`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_services/test_voice.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add src/services/voice.py tests/test_services/test_voice.py
git commit -m "feat(voice): thêm WhisperCppEngine và transcribe() với validate audio"
```

---

### Task 4: TTS engine (`PiperEngine`) and `synthesize()`

**Files:**
- Modify: `src/services/voice.py`
- Modify: `tests/test_services/test_voice.py`
- Modify: `pyproject.toml` (add `piper-tts` dependency)
- Modify: `requirements.txt` (add `piper-tts`)

**Interfaces:**
- Consumes: `normalize_vietnamese_text` (Task 2), `Settings.tts_provider/tts_model_path` (Task 1).
- Produces: `PiperEngine(voice: PiperVoiceProtocol)` with `.synthesize_stream(text: str) -> Iterator[bytes]`, `get_tts_engine() -> PiperEngine`, `synthesize(text: str) -> Iterator[bytes]`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to `dependencies`:

```toml
    "piper-tts>=1.3,<2",
```

In `requirements.txt`, add under the `# AI / LangChain` block (new `# Voice` block):

```
# Voice
piper-tts>=1.3,<2
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_services/test_voice.py`:

```python
from typing import Iterator

from src.services.voice import PiperEngine, synthesize


class _FakeVoice:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.received_text: str | None = None

    def synthesize_stream_raw(self, text: str) -> Iterator[bytes]:
        self.received_text = text
        yield from self._chunks


def test_piper_engine_streams_multiple_chunks_that_form_valid_wav() -> None:
    chunks = [b"\x00\x01" * 100, b"\x02\x03" * 100, b"\x04\x05" * 100]
    fake_voice = _FakeVoice(chunks)
    engine = PiperEngine(fake_voice)

    collected = list(engine.synthesize_stream("  Xin  chào  "))

    assert collected == chunks
    assert len(collected) > 1
    assert fake_voice.received_text == "Xin chào"

    pcm_bytes = b"".join(collected)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(pcm_bytes)
    buffer.seek(0)
    with wave.open(buffer, "rb") as wav_file:
        assert wav_file.getnframes() == len(pcm_bytes) // 2


def test_synthesize_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="empty"):
        list(synthesize("   "))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_services/test_voice.py -v`
Expected: FAIL with `ImportError: cannot import name 'PiperEngine' from 'src.services.voice'`

- [ ] **Step 4: Implement the TTS engine**

Append to `src/services/voice.py`:

```python
class PiperEngine:
    def __init__(self, voice: object) -> None:
        self._voice = voice

    def synthesize_stream(self, text: str) -> Iterator[bytes]:
        normalized = normalize_vietnamese_text(text)
        yield from self._voice.synthesize_stream_raw(normalized)


@lru_cache
def get_tts_engine() -> PiperEngine:
    settings = get_settings()
    model_path = Path(settings.tts_model_path)
    if not model_path.is_file():
        raise FileNotFoundError(
            f"TTS model not found at {model_path}. Run scripts/setup_voice_models.ps1 first."
        )
    from piper import PiperVoice  # imported lazily: heavy optional dependency

    voice = PiperVoice.load(str(model_path))
    return PiperEngine(voice)


def synthesize(text: str) -> Iterator[bytes]:
    if not text or not text.strip():
        raise ValueError("text must not be empty")
    engine = get_tts_engine()
    yield from engine.synthesize_stream(text)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_services/test_voice.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 6: Commit**

```bash
git add src/services/voice.py tests/test_services/test_voice.py pyproject.toml requirements.txt
git commit -m "feat(voice): thêm PiperEngine và synthesize() streaming"
```

---

### Task 5: Model assets `.gitignore` and setup script

**Files:**
- Modify: `.gitignore`
- Create: `scripts/setup_voice_models.ps1`

**Interfaces:**
- Produces: `models/voice/ggml-phowhisper-small.bin` (STT model, matches `Settings.stt_model_path` default from Task 1) and `models/voice/vi_VN-piper.onnx` (TTS model, matches `Settings.tts_model_path` default) when run locally — consumed by Task 6's integration tests.

- [ ] **Step 1: Add gitignore rules**

Append to `.gitignore`:

```
# Voice model assets (fetched/built locally, never committed)
models/voice/*
!models/voice/*.metadata.json
!models/voice/*.sha256
tools/whisper-cpp/
```

- [ ] **Step 2: Write the setup script**

Create `scripts/setup_voice_models.ps1`:

```powershell
[CmdletBinding()]
param(
    [string]$WhisperCppDir = (Join-Path $PSScriptRoot "..\tools\whisper-cpp"),
    [string]$OpenAiWhisperDir = (Join-Path $PSScriptRoot "..\tools\openai-whisper"),
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\models\voice"),
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$phoWhisperRepo = "vinai/PhoWhisper-small"
$whisperCppRepo = "https://github.com/ggml-org/whisper.cpp"
$openAiWhisperRepo = "https://github.com/openai/whisper"
$resolvedOutputDir = [IO.Path]::GetFullPath($OutputDir)
$phoWhisperHfDir = Join-Path $resolvedOutputDir "phowhisper-small-hf"

if ($DryRun) {
    [pscustomobject]@{
        PhoWhisperRepo   = $phoWhisperRepo
        WhisperCppRepo   = $whisperCppRepo
        OpenAiWhisperRepo = $openAiWhisperRepo
        WhisperCppDir    = $WhisperCppDir
        OutputDir        = $resolvedOutputDir
        PhoWhisperHfDir  = $phoWhisperHfDir
        Steps            = @(
            "1. git clone $whisperCppRepo -> $WhisperCppDir"
            "2. cmake build $WhisperCppDir (Release) -> whisper-cli, whisper-quantize"
            "3. git clone $openAiWhisperRepo -> $OpenAiWhisperDir (needed only for whisper/assets/mel_filters.npz)"
            "4. hf download $phoWhisperRepo -> $phoWhisperHfDir"
            "5. python $WhisperCppDir\models\convert-h5-to-ggml.py $phoWhisperHfDir $OpenAiWhisperDir $resolvedOutputDir"
            "6. rename $resolvedOutputDir\ggml-model.bin -> $resolvedOutputDir\ggml-phowhisper-small.bin"
            "7. record sha256 + metadata.json for ggml-phowhisper-small.bin"
        )
    } | ConvertTo-Json -Depth 4
    exit 0
}

New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null

if (-not (Test-Path -LiteralPath $WhisperCppDir)) {
    git clone $whisperCppRepo $WhisperCppDir
}
$whisperCppCommit = (git -C $WhisperCppDir rev-parse HEAD).Trim()

$buildDir = Join-Path $WhisperCppDir "build"
cmake -S $WhisperCppDir -B $buildDir -DCMAKE_BUILD_TYPE=Release
cmake --build $buildDir --config Release --target whisper-cli whisper-quantize
$whisperCliExe = Join-Path $buildDir "bin\Release\whisper-cli.exe"
if (-not (Test-Path -LiteralPath $whisperCliExe)) {
    throw "Build did not produce $whisperCliExe. Check the whisper.cpp CMake output above."
}

if (-not (Test-Path -LiteralPath $OpenAiWhisperDir)) {
    git clone $openAiWhisperRepo $OpenAiWhisperDir
}

if (-not (Test-Path -LiteralPath $phoWhisperHfDir)) {
    $hfCommand = Get-Command hf -ErrorAction SilentlyContinue
    if (-not $hfCommand) {
        throw "Hugging Face CLI 'hf' was not found. Install huggingface_hub first."
    }
    & $hfCommand.Source download $phoWhisperRepo --local-dir $phoWhisperHfDir
    if ($LASTEXITCODE -ne 0) {
        throw "PhoWhisper download failed with exit code $LASTEXITCODE."
    }
}

python (Join-Path $WhisperCppDir "models\convert-h5-to-ggml.py") $phoWhisperHfDir $OpenAiWhisperDir $resolvedOutputDir
if ($LASTEXITCODE -ne 0) {
    throw "GGML conversion failed with exit code $LASTEXITCODE."
}

$rawGgml = Join-Path $resolvedOutputDir "ggml-model.bin"
$targetGgml = Join-Path $resolvedOutputDir "ggml-phowhisper-small.bin"
if (-not (Test-Path -LiteralPath $rawGgml)) {
    throw "Expected conversion output not found at $rawGgml."
}
Move-Item -LiteralPath $rawGgml -Destination $targetGgml -Force

$hash = Get-FileHash -LiteralPath $targetGgml -Algorithm SHA256
"$($hash.Hash.ToLowerInvariant())  ggml-phowhisper-small.bin" |
    Set-Content -LiteralPath "$targetGgml.sha256" -Encoding utf8

[pscustomobject]@{
    Profile         = "phowhisper-small-ggml"
    SourceRepo      = $phoWhisperRepo
    WhisperCppRepo  = $whisperCppRepo
    WhisperCppCommit = $whisperCppCommit
    Sha256          = $hash.Hash.ToLowerInvariant()
    SizeBytes       = (Get-Item -LiteralPath $targetGgml).Length
    ConvertedAtUtc  = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath "$targetGgml.metadata.json" -Encoding utf8

Write-Output "STT model ready: $targetGgml"
Write-Output "whisper-cli: $whisperCliExe"
Write-Output ""
Write-Output "TTS setup is manual: download a Vietnamese Piper voice (.onnx + .onnx.json)"
Write-Output "from https://github.com/rhasspy/piper/blob/master/VOICES.md into $resolvedOutputDir"
Write-Output "as vi_VN-piper.onnx (matching Settings.tts_model_path default)."
```

This script is a one-time local setup tool, not part of the request path or CI (per Global Constraints). Piper voice download is left as a documented manual step because it requires picking a specific Vietnamese voice from Piper's voice catalog, which is a product/quality decision outside this task's scope, not a missing implementation detail.

- [ ] **Step 3: Verify the dry-run path**

Run: `pwsh -File scripts/setup_voice_models.ps1 -DryRun`
Expected: prints a JSON object listing the planned steps and exits 0, without cloning/building/downloading anything.

- [ ] **Step 4: Commit**

```bash
git add .gitignore scripts/setup_voice_models.ps1
git commit -m "chore(voice): thêm script setup model whisper.cpp/PhoWhisper GGML"
```

---

### Task 6: Integration tests gated behind real model assets

**Files:**
- Modify: `pyproject.toml` (register `integration` marker)
- Create: `tests/test_services/test_voice_integration.py`

**Interfaces:**
- Consumes: `transcribe`, `synthesize`, `word_error_rate` (Tasks 2-4), `Settings` (Task 1).

- [ ] **Step 1: Register the pytest marker**

In `pyproject.toml`, under `[tool.pytest.ini_options]`, add:

```toml
markers = [
    "integration: requires real local model assets; skipped by default (see docs/superpowers/specs/2026-08-07-voice-asr-tts-design.md)",
]
```

- [ ] **Step 2: Write the integration tests**

Create `tests/test_services/test_voice_integration.py`:

```python
from __future__ import annotations

import io
from pathlib import Path
import time
import wave

import pytest

from src.config import get_settings
from src.services.voice import (
    get_stt_engine,
    get_tts_engine,
    synthesize,
    transcribe,
    word_error_rate,
)

pytestmark = pytest.mark.integration


def _assets_available() -> bool:
    settings = get_settings()
    return Path(settings.stt_model_path).is_file() and Path(settings.tts_model_path).is_file()


@pytest.mark.skipif(not _assets_available(), reason="voice model assets not configured locally")
def test_transcribe_warm_latency_is_under_budget() -> None:
    # Reference sentence must be pre-recorded at tests/fixtures/voice/warm_sample.wav
    # (16kHz mono WAV, "đặt điều hòa hai mươi bốn độ").
    audio_path = Path("tests/fixtures/voice/warm_sample.wav")
    audio_bytes = audio_path.read_bytes()

    get_stt_engine()  # force model load before timing
    transcribe(audio_bytes)  # first (cold) call, discarded

    started = time.perf_counter()
    result = transcribe(audio_bytes)
    wall_ms = (time.perf_counter() - started) * 1000

    assert wall_ms < 400, f"warm transcribe took {wall_ms:.1f}ms, budget is 400ms"
    assert result.text


@pytest.mark.skipif(not _assets_available(), reason="voice model assets not configured locally")
def test_synthetic_loopback_word_error_rate_is_under_budget() -> None:
    sentences = [
        "Bật điều hòa",
        "Đặt điều hòa hai mươi bốn độ",
        "Mở cửa sổ bên phụ một nửa",
        "Tăng nhiệt độ lên hai mươi sáu độ",
        "Bật sưởi ghế lái mức hai",
    ]

    get_tts_engine()
    get_stt_engine()

    rates: list[float] = []
    for sentence in sentences:
        pcm_bytes = b"".join(synthesize(sentence))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(pcm_bytes)

        result = transcribe(buffer.getvalue())
        rates.append(word_error_rate(sentence, result.text))

    average_wer = sum(rates) / len(rates)
    # This is a synthetic-audio smoke check (Piper output fed back through
    # whisper.cpp), not a real-speaker accuracy benchmark — see ADR-007 and
    # the design spec's WER caveat.
    assert average_wer < 0.20, f"synthetic loopback WER {average_wer:.2%} exceeds 20% budget"
```

- [ ] **Step 3: Run test to verify it skips cleanly without assets**

Run: `pytest tests/test_services/test_voice_integration.py -v`
Expected: 2 tests, both `SKIPPED (voice model assets not configured locally)`

- [ ] **Step 4: Run the full unit test suite to confirm no regressions**

Run: `pytest tests/ -v`
Expected: all previous tests PASS, the 2 integration tests SKIP

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_services/test_voice_integration.py
git commit -m "test(voice): thêm integration test AC1 latency + AC2 WER loopback (skip nếu thiếu model)"
```

---

## Post-plan follow-ups (not part of this plan)

- Recording `tests/fixtures/voice/warm_sample.wav` and running `scripts/setup_voice_models.ps1` for real, then actually executing the integration tests to get a first real latency/WER measurement, is a manual step for whoever has the local hardware — capture the result back into `eval/results/report.md` or a new evidence file once available.
- Wiring `src/services/voice.py` into a real HTTP surface (`POST /api/v1/turns/voice`) is explicitly out of scope (see spec + ADR-007) and needs its own future plan once auth/session/turn infrastructure exists.

# Faster-Whisper STT Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the whisper.cpp resident-server STT engine in `src/services/voice.py` with faster-whisper (CTranslate2), running `vinai/PhoWhisper-base` converted to CT2 format, in-process (no subprocess/HTTP).

**Architecture:** `FasterWhisperEngine` wraps a `faster_whisper.WhisperModel`-like object (constructor-injected, matching the existing `PiperEngine` pattern) and calls `.transcribe()` directly in-process — no subprocess, no HTTP client, no port health-checks, no `atexit` cleanup. `get_stt_engine()` singleton (`lru_cache`, unchanged pattern) loads the CT2 model once. All whisper.cpp resident-server code (`WhisperServerHandle`, `start_whisper_server`, `WhisperCppEngine`, every `stt_server_*`/`stt_no_fallback`/`stt_request_timeout_s` setting) is deleted, not kept behind a provider switch.

**Tech Stack:** Python 3.11, `faster-whisper` (CTranslate2 backend), `vinai/PhoWhisper-base` converted via `ct2-transformers-converter`, pytest.

## Global Constraints

- Engine: faster-whisper only. `Settings.stt_provider` default becomes `"faster_whisper"`; `get_stt_engine()` raises `ValueError` for any other value (same fail-fast pattern as before).
- Model: `vinai/PhoWhisper-base` converted to CTranslate2 int8, stored at `models/voice/phowhisper-base-ct2/` (a directory, not a single file — `Settings.stt_model_path` check must use `.is_dir()`, not `.is_file()`).
- Full replacement, no dual-provider switch: delete `WhisperServerHandle`, `ProcessSpawner`, `PortProber`, `_default_process_spawner`, `_default_port_prober`, `start_whisper_server`, `WhisperCppEngine`, `stop_stt_engine`, the `atexit.register(stop_stt_engine)` call, and every `Settings.stt_server_*`/`stt_no_fallback`/`stt_request_timeout_s` field.
- Reuse existing fixtures unchanged: `tests/fixtures/voice/warm_sample.wav`, `tests/fixtures/voice/synthetic_commands/` (manifest.json + 5 WAV files) — do not regenerate them.
- AC1/AC2 budgets: measure real numbers with the new engine before writing them into ADR-008 — do not assume the PoC's unverified "~1s / 10-15% WER" figures.
- `docs/devops.md`'s Environment contract table gets `STT_PROVIDER` updated to `faster_whisper` (approved scope — canonical doc update, not just an ADR note).
- New ADR (`docs/adr/ADR-008-...md`) — do not edit ADR-007 in place; ADR-007 stays as the historical record.
- `ruff check src/ tests/ scripts/` and `ruff format --check src/ tests/ scripts/` must pass (matches `.github/workflows/ci.yml`, which runs `ruff check src/ tests/`).
- Follow `docs/GIT_WORKFLOW.md`: work stays on `feature/faster-whisper-stt`, no direct push to `develop`/`main`.
- TDD every task: write failing test → verify it fails → minimal implementation → verify it passes → commit.

---

### Task 1: Settings — replace whisper.cpp resident-server fields with faster-whisper fields

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.stt_provider` (default `"faster_whisper"`), `Settings.stt_model_path` (default `"./models/voice/phowhisper-base-ct2"`), `Settings.stt_compute_type: str` (default `"int8"`), `Settings.stt_beam_size: int` (default `5`), `Settings.stt_max_audio_seconds` (unchanged, default `30`). Removes `stt_server_executable_path`, `stt_server_host`, `stt_server_port`, `stt_server_threads`, `stt_no_fallback`, `stt_server_startup_timeout_s`, `stt_request_timeout_s`.

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_config.py` with:

```python
from src.config import Settings


def test_voice_settings_have_canonical_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.stt_provider == "faster_whisper"
    assert settings.stt_model_path == "./models/voice/phowhisper-base-ct2"
    assert settings.stt_compute_type == "int8"
    assert settings.stt_beam_size == 5
    assert settings.stt_max_audio_seconds == 30
    assert settings.tts_provider == "piper"
    assert settings.tts_model_path == "./models/voice/vi_VN-piper.onnx"


def test_voice_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "/custom/model-ct2")
    monkeypatch.setenv("TTS_MODEL_PATH", "/custom/voice.onnx")
    monkeypatch.setenv("STT_BEAM_SIZE", "1")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "float32")

    settings = Settings(_env_file=None)

    assert settings.stt_model_path == "/custom/model-ct2"
    assert settings.tts_model_path == "/custom/voice.onnx"
    assert settings.stt_beam_size == 1
    assert settings.stt_compute_type == "float32"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `AssertionError` on `stt_provider == "faster_whisper"` (still `"whisper_cpp"`), and `AttributeError` once that assertion is fixed manually to check, since `stt_compute_type`/`stt_beam_size` don't exist yet.

- [ ] **Step 3: Write minimal implementation**

In `src/config.py`, replace the entire "Voice adapter (STT/TTS)" block with:

```python
    # Voice adapter (STT/TTS) — names match docs/devops.md Environment contract
    stt_provider: str = "faster_whisper"
    stt_model_path: str = "./models/voice/phowhisper-base-ct2"
    stt_compute_type: str = "int8"
    stt_beam_size: int = Field(default=5, ge=1, le=10)
    stt_max_audio_seconds: int = Field(default=30, ge=1, le=30)
    tts_provider: str = "piper"
    tts_model_path: str = "./models/voice/vi_VN-piper.onnx"
```

This removes the previous `stt_server_executable_path`, `stt_server_host`, `stt_server_port`, `stt_server_threads`, `stt_no_fallback`, `stt_server_startup_timeout_s`, `stt_request_timeout_s` fields. `import os` (previously only used for `stt_server_threads`'s `default_factory=lambda: os.cpu_count() or 4`) is no longer needed — remove it from the top of `src/config.py` if nothing else in the file uses `os` (check with a search before removing; if `os` is used elsewhere, leave the import).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check src/config.py tests/test_config.py && python -m ruff format --check src/config.py tests/test_config.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(voice): replace whisper.cpp resident-server settings with faster-whisper settings"
```

---

### Task 2: `FasterWhisperEngine` — replace `WhisperCppEngine` and the resident-server machinery

**Files:**
- Modify: `src/services/voice.py`
- Modify: `tests/test_services/test_voice.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `Settings.stt_model_path`, `stt_compute_type`, `stt_beam_size`, `stt_provider` (Task 1).
- Produces: `FasterWhisperEngine(model: object, beam_size: int = 5)` with `.transcribe_file(audio_path: Path) -> Transcript`; `get_stt_engine() -> FasterWhisperEngine` (same public name/shape as before, new internals). `Transcript`, `transcribe()`, `_validate_audio()`, `PiperEngine`, `get_tts_engine()`, `synthesize()` are unchanged by this task.

- [ ] **Step 1: Write the failing test**

In `tests/test_services/test_voice.py`:

1. Replace the top `from src.services.voice import (...)` block with:

```python
from src.services.voice import (
    FasterWhisperEngine,
    PiperEngine,
    char_error_rate,
    normalize_vietnamese_text,
    synthesize,
    transcribe,
    word_error_rate,
)
```

2. Remove the `import subprocess` line (no longer used anywhere in this file once the whisper-server tests below are deleted).

3. Delete these test doubles and tests entirely (they test the whisper.cpp resident-server mechanism this task replaces): `_FakeHttpResponse`, `_FakeHttpClient`, `test_whisper_cpp_engine_transcribe_file_posts_to_server_and_returns_normalized_text`, `test_whisper_cpp_engine_default_http_client_uses_request_timeout_s`, `test_whisper_cpp_engine_close_closes_http_client_and_stops_server`, `_FakeProcess`, `test_default_port_prober_returns_true_on_any_http_response`, `test_default_port_prober_returns_false_when_request_fails`, `test_start_whisper_server_returns_handle_once_port_is_reachable`, `test_start_whisper_server_omits_no_fallback_flag_when_disabled`, `test_start_whisper_server_raises_timeout_when_port_never_opens`, `test_start_whisper_server_raises_runtime_error_when_process_exits_early`, `test_whisper_server_handle_stop_terminates_process_gracefully`, `test_whisper_server_handle_stop_kills_process_when_terminate_times_out`, `test_get_stt_engine_starts_resident_server_and_stop_stt_engine_tears_it_down`.

4. Add these test doubles and tests in their place (same location in the file):

```python
class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeWhisperModel:
    def __init__(self, segments: list[_FakeSegment]) -> None:
        self._segments = segments
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        return iter(self._segments), object()


def test_faster_whisper_engine_transcribe_file_joins_segments_and_returns_normalized_text(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(_make_wav_bytes())
    fake_model = _FakeWhisperModel([_FakeSegment("  đặt  điều"), _FakeSegment("hòa 24 độ  ")])

    engine = FasterWhisperEngine(fake_model, beam_size=5)
    result = engine.transcribe_file(audio_path)

    assert result.text == "đặt điều hòa 24 độ"
    assert result.latency_ms >= 0
    assert fake_model.calls == [{"audio": str(audio_path), "language": "vi", "beam_size": 5}]


def test_faster_whisper_engine_passes_configured_beam_size(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(_make_wav_bytes())
    fake_model = _FakeWhisperModel([_FakeSegment("ok")])

    engine = FasterWhisperEngine(fake_model, beam_size=1)
    engine.transcribe_file(audio_path)

    assert fake_model.calls[0]["beam_size"] == 1
```

5. `test_get_stt_engine_rejects_unsupported_provider` stays in the file unchanged — it already only asserts on the `ValueError` message containing `"STT_PROVIDER"`, which remains true with the new provider name.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_voice.py -v -k "faster_whisper_engine"`
Expected: FAIL — `ImportError: cannot import name 'FasterWhisperEngine'`

- [ ] **Step 3: Write minimal implementation**

In `src/services/voice.py`:

1. Remove these imports from the top: `atexit`, `subprocess`, `httpx` (all only used by the deleted mechanism). Keep `io`, `tempfile`, `time`, `unicodedata`, `wave`, `Callable`/`Iterator` from `collections.abc` (`Callable` — check after deletion whether anything still uses it; if not, remove it from the import too), `dataclass`, `lru_cache`, `Path`.

2. Delete: `WhisperServerHandle`, `ProcessSpawner`, `PortProber`, `_default_process_spawner`, `_default_port_prober`, `start_whisper_server`, `WhisperCppEngine`, `stop_stt_engine`, and the module-level `atexit.register(stop_stt_engine)` line.

3. Update `Transcript`'s docstring comment (it currently references whisper.cpp's `-oj` JSON output, which no longer applies):

```python
@dataclass(frozen=True)
class Transcript:
    text: str
    latency_ms: float
    # faster-whisper's Segment does not expose a calibrated per-utterance
    # confidence score, so this stays 0.0 until an upstream field is available.
    confidence: float = 0.0
```

4. Add, in place of the deleted classes/functions (same location — right before `get_stt_engine`):

```python
class FasterWhisperEngine:
    """Wraps a faster_whisper.WhisperModel-like object.

    The wrapped object's `.transcribe(path, language=..., beam_size=...)` must
    return `(segments, info)` where `segments` is an iterable of objects
    exposing `.text` (matches `faster_whisper.WhisperModel` and its `Segment`
    result type).
    """

    def __init__(self, model: object, beam_size: int = 5) -> None:
        self._model = model
        self._beam_size = beam_size

    def transcribe_file(self, audio_path: Path) -> Transcript:
        started_ns = time.perf_counter_ns()
        segments, _info = self._model.transcribe(str(audio_path), language="vi", beam_size=self._beam_size)
        text = " ".join(segment.text for segment in segments)
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        return Transcript(text=normalize_vietnamese_text(text), latency_ms=latency_ms)
```

5. Replace `get_stt_engine()` with:

```python
@lru_cache
def get_stt_engine() -> FasterWhisperEngine:
    settings = get_settings()
    if settings.stt_provider != "faster_whisper":
        raise ValueError(
            f"unsupported STT_PROVIDER: only faster_whisper is implemented, got {settings.stt_provider!r}"
        )
    model_path = Path(settings.stt_model_path)
    if not model_path.is_dir():
        raise FileNotFoundError(f"STT model not found at {model_path}. Run scripts/setup_voice_models.ps1 first.")
    from faster_whisper import WhisperModel  # imported lazily: heavy optional dependency

    model = WhisperModel(str(model_path), device="cpu", compute_type=settings.stt_compute_type)
    return FasterWhisperEngine(model, beam_size=settings.stt_beam_size)
```

Note the check changed from `model_path.is_file()` to `model_path.is_dir()` — the CT2 conversion output is a directory of files, not one file.

6. `_validate_audio()`, `transcribe()`, `PiperEngine`, `get_tts_engine()`, `synthesize()` are untouched.

In `pyproject.toml`, replace the `voice` optional-dependencies group:

```toml
voice = [
    "piper-tts>=1.3,<2",
    "faster-whisper>=1.0,<2",
]
```

(removes `httpx>=0.28.0` from this group — `httpx` is no longer used by the voice module; it stays in the `dev` group since `tests/conftest.py` still uses it for the FastAPI test client.)

In `requirements.txt`, replace the commented-out voice-extras lines:

```
# piper-tts>=1.3,<2
# faster-whisper>=1.0,<2
```

(remove the `# httpx>=0.28.0  # already listed...` comment line that referenced the resident-server client — `httpx`'s uncommented dev-group line elsewhere in the file is unaffected and stays as-is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_voice.py -v`
Expected: PASS — all tests in the file pass (old whisper-server tests gone, new `FasterWhisperEngine` tests pass, unrelated tests unaffected).

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check src/services/voice.py tests/test_services/test_voice.py && python -m ruff format --check src/services/voice.py tests/test_services/test_voice.py`
Expected: no errors — pay particular attention to unused-import errors from the deleted `atexit`/`subprocess`/`httpx`/`Callable` usages; ruff's `F401` will catch any left dangling.

- [ ] **Step 6: Commit**

```bash
git add src/services/voice.py tests/test_services/test_voice.py pyproject.toml requirements.txt
git commit -m "feat(voice): replace whisper.cpp resident-server engine with in-process faster-whisper"
```

---

### Task 3: Convert PhoWhisper-base to CTranslate2 and update the setup script

**Files:**
- Modify: `scripts/setup_voice_models.ps1`

**Interfaces:**
- Produces: `models/voice/phowhisper-base-ct2/` (a directory: CTranslate2 model files + `tokenizer.json` + `preprocessor_config.json`), matching `Settings.stt_model_path`'s default from Task 1.

- [ ] **Step 1: Rewrite the script**

Replace the entire contents of `scripts/setup_voice_models.ps1` with:

```powershell
[CmdletBinding()]
param(
    [string]$PhoWhisperHfDir = (Join-Path $PSScriptRoot "..\models\voice\phowhisper-base-hf"),
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\models\voice"),
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$phoWhisperRepo = "vinai/PhoWhisper-base"
$resolvedOutputDir = [IO.Path]::GetFullPath($OutputDir)
$resolvedPhoWhisperHfDir = [IO.Path]::GetFullPath($PhoWhisperHfDir)
$ct2OutputDir = Join-Path $resolvedOutputDir "phowhisper-base-ct2"

if ($DryRun) {
    [pscustomobject]@{
        PhoWhisperRepo    = $phoWhisperRepo
        PhoWhisperHfDir   = $resolvedPhoWhisperHfDir
        OutputDir         = $resolvedOutputDir
        Ct2OutputDir      = $ct2OutputDir
        Steps             = @(
            "1. hf download $phoWhisperRepo -> $resolvedPhoWhisperHfDir (skipped if already present)"
            "2. ct2-transformers-converter --model $resolvedPhoWhisperHfDir --output_dir $ct2OutputDir --copy_files tokenizer.json preprocessor_config.json --quantization int8"
            "3. record metadata.json for phowhisper-base-ct2"
        )
    } | ConvertTo-Json -Depth 4
    exit 0
}

New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null

if (-not (Test-Path -LiteralPath $resolvedPhoWhisperHfDir)) {
    $hfCommand = Get-Command hf -ErrorAction SilentlyContinue
    if (-not $hfCommand) {
        throw "Hugging Face CLI 'hf' was not found. Install huggingface_hub first."
    }
    & $hfCommand.Source download $phoWhisperRepo --local-dir $resolvedPhoWhisperHfDir
    if ($LASTEXITCODE -ne 0) {
        throw "PhoWhisper download failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $ct2OutputDir)) {
    ct2-transformers-converter --model $resolvedPhoWhisperHfDir --output_dir $ct2OutputDir --copy_files tokenizer.json preprocessor_config.json --quantization int8
    if ($LASTEXITCODE -ne 0) {
        throw "ct2-transformers-converter failed with exit code $LASTEXITCODE. Ensure 'pip install faster-whisper transformers torch' has been run first."
    }
}

[pscustomobject]@{
    Profile        = "phowhisper-base-ct2-int8"
    SourceRepo     = $phoWhisperRepo
    Quantization   = "int8"
    ConvertedAtUtc = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath "$ct2OutputDir.metadata.json" -Encoding utf8

Write-Output "STT model ready: $ct2OutputDir"
Write-Output ""
Write-Output "TTS setup is manual: download a Vietnamese Piper voice (.onnx + .onnx.json)"
Write-Output "from https://github.com/rhasspy/piper/blob/master/VOICES.md into $resolvedOutputDir"
Write-Output "as vi_VN-piper.onnx (matching Settings.tts_model_path default)."
```

This drops the whisper.cpp clone/cmake-build steps and the `convert-h5-to-ggml.py` invocation entirely, replacing them with the CTranslate2 converter. `ct2-transformers-converter` becomes available on `PATH` once `faster-whisper` is installed (it pulls in `ctranslate2`, which provides this console script) — converting also needs `transformers` and `torch` importable (to load the source HF checkpoint), which are local one-time prerequisites for running this script, not runtime dependencies of the deployed app (matches how the previous whisper.cpp-era script also needed `transformers`/`torch` locally without adding them to `pyproject.toml`).

- [ ] **Step 2: Verify with -DryRun**

Run: `pwsh -File scripts/setup_voice_models.ps1 -DryRun` (or `powershell -File scripts/setup_voice_models.ps1 -DryRun` if `pwsh` isn't available)
Expected: exit code 0, JSON output shows `PhoWhisperRepo: vinai/PhoWhisper-base`, `Ct2OutputDir` ending in `phowhisper-base-ct2`, `Steps` mentioning `ct2-transformers-converter`. No side effects (no files created).

- [ ] **Step 3: Run the real conversion**

This machine already has `models/voice/phowhisper-base-hf/` (the HF checkpoint, downloaded in earlier work) and `torch`/`transformers` installed in `.venv`. Install `faster-whisper` (which brings `ctranslate2` and the `ct2-transformers-converter` script) if not already present, then run the script for real:

```bash
source .venv/Scripts/activate
pip install -e ".[voice]"
pwsh -File scripts/setup_voice_models.ps1
```

(If `pwsh`/`powershell` invocation has trouble resolving `$PSScriptRoot`-relative defaults from this shell, pass explicit paths: `pwsh -File scripts/setup_voice_models.ps1 -PhoWhisperHfDir ./models/voice/phowhisper-base-hf -OutputDir ./models/voice`.)

Expected: exits 0, prints `STT model ready: .../models/voice/phowhisper-base-ct2`. Verify the directory was actually created and is non-empty:

```bash
ls models/voice/phowhisper-base-ct2/
```

Expected: contains CTranslate2 model files (e.g. `model.bin`, `config.json`) plus the copied `tokenizer.json` and `preprocessor_config.json`.

- [ ] **Step 4: Commit**

```bash
git add scripts/setup_voice_models.ps1
git commit -m "feat(voice): setup script converts PhoWhisper-base to CTranslate2 instead of GGML"
```

(The generated `models/voice/phowhisper-base-ct2/` directory itself is gitignored per the existing `models/voice/*` pattern — do not force-add it.)

---

### Task 4: Update integration tests — real AC1/AC2 measurement with faster-whisper

**Files:**
- Modify: `tests/test_services/test_voice_integration.py`

**Interfaces:**
- Consumes: `get_stt_engine()` (Task 2), the real `models/voice/phowhisper-base-ct2/` model (Task 3), the existing fixtures (unchanged).

- [ ] **Step 1: Update the integration test file**

Replace the full contents of `tests/test_services/test_voice_integration.py` with:

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.config import get_settings
from src.services.voice import get_stt_engine, transcribe, word_error_rate

pytestmark = pytest.mark.integration

_WARM_SAMPLE_PATH = Path(__file__).parent.parent / "fixtures" / "voice" / "warm_sample.wav"
_SYNTHETIC_COMMANDS_DIR = Path(__file__).parent.parent / "fixtures" / "voice" / "synthetic_commands"
_SYNTHETIC_COMMANDS_MANIFEST = _SYNTHETIC_COMMANDS_DIR / "manifest.json"


def _assets_available() -> bool:
    settings = get_settings()
    return Path(settings.stt_model_path).is_dir() and Path(settings.tts_model_path).is_file()


def _warm_sample_available() -> bool:
    return _assets_available() and _WARM_SAMPLE_PATH.is_file()


def _synthetic_commands_available() -> bool:
    return _assets_available() and _SYNTHETIC_COMMANDS_MANIFEST.is_file()


@pytest.fixture(scope="session", autouse=True)
def _clear_stt_engine_cache_after_session():
    yield
    get_stt_engine.cache_clear()


@pytest.mark.skipif(not _warm_sample_available(), reason="voice model assets or warm_sample.wav fixture not available")
def test_transcribe_warm_latency_is_under_budget() -> None:
    # Reference sentence must be pre-recorded at tests/fixtures/voice/warm_sample.wav
    # (16kHz mono WAV, "đặt điều hòa hai mươi bốn độ").
    audio_bytes = _WARM_SAMPLE_PATH.read_bytes()

    get_stt_engine()  # loads the CTranslate2 model into memory
    transcribe(audio_bytes)  # first call, discarded (excludes model-load variance)

    started = time.perf_counter()
    result = transcribe(audio_bytes)
    wall_ms = (time.perf_counter() - started) * 1000

    # Budget: PoC target is ~1s (unverified figure from an external PoC, see
    # docs/superpowers/specs/2026-08-07-faster-whisper-migration-design.md).
    # 1.5s carries forward the whisper.cpp-era revised budget as a ceiling
    # until this is re-measured and possibly tightened in ADR-008.
    assert wall_ms < 1500, f"warm transcribe took {wall_ms:.1f}ms, budget is 1500ms"
    assert result.text


@pytest.mark.skipif(
    not _synthetic_commands_available(), reason="voice model assets or synthetic command fixtures not available"
)
def test_synthetic_loopback_word_error_rate_is_under_budget() -> None:
    manifest = json.loads(_SYNTHETIC_COMMANDS_MANIFEST.read_text(encoding="utf-8"))

    get_stt_engine()

    rates: list[float] = []
    for entry in manifest:
        audio_path = _SYNTHETIC_COMMANDS_DIR / entry["file"]
        result = transcribe(audio_path.read_bytes())
        rates.append(word_error_rate(entry["text"], result.text))

    average_wer = sum(rates) / len(rates)
    # This is a synthetic-audio smoke check (fixed Piper output fed back
    # through faster-whisper), not a real-speaker accuracy benchmark — see
    # ADR-008 and the design spec's WER caveat.
    assert average_wer < 0.20, f"synthetic loopback WER {average_wer:.2%} exceeds 20% budget"
```

Compared to the previous version: the `stop_stt_engine` import and its teardown fixture are gone (no external process to tear down anymore — `_clear_stt_engine_cache_after_session` just clears the `lru_cache` so a later test session starts fresh); `_assets_available()` now checks `.is_dir()` for the STT model path instead of `.is_file()`.

- [ ] **Step 2: Run the integration tests for real**

Requires Task 3's real `models/voice/phowhisper-base-ct2/` to exist. Run:

```bash
source .venv/Scripts/activate
python -m pytest tests/test_services/test_voice_integration.py -v -m integration
```

Expected: both tests run (not skipped). Record the REAL pass/fail and the real latency/WER numbers in your task report — do not assume either test passes. If AC2 still fails, that is valid, expected data for this task to report (not something to fix by relaxing the assertion) — the whole point of switching engines was to get a real number to compare against the PoC's unverified 10-15% expectation.

- [ ] **Step 3: Run the full non-integration suite**

Run: `python -m pytest tests/test_config.py tests/test_services/test_voice.py -v`
Expected: all pass.

- [ ] **Step 4: Run ruff**

Run: `python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/test_services/test_voice_integration.py
git commit -m "test(voice): integration tests measure real AC1/AC2 with faster-whisper"
```

---

### Task 5: ADR-008 + `docs/devops.md` canonical update

**Files:**
- Create: `docs/adr/ADR-008-faster-whisper-stt-for-poc.md`
- Modify: `docs/devops.md`

**Interfaces:**
- Consumes: the real AC1/AC2 numbers recorded in Task 4's report.

- [ ] **Step 1: Write ADR-008**

Create `docs/adr/ADR-008-faster-whisper-stt-for-poc.md` following the existing ADR format (see `docs/adr/ADR-007-voice-adapter-engine-binding.md` for the section structure: Status/Date/Decision owner/Context/Alternatives/Decision/Rationale/Consequences/Revisit when). Content requirements:

- **Status**: `Accepted (PoC/demo scope) — supersedes STT half of ADR-007`
- **Context**: cite the real whisper.cpp resident-server measurement — WER ~88% on both PhoWhisper-small and PhoWhisper-base through the same harness (link ADR-007's "Benchmark thật 2026-08-07 (sau tối ưu)" section), which made the feature unusable for a demo. Note the root cause was not conclusively isolated (could be the GGML conversion or the multipart HTTP transport) and that further investigation was explicitly deferred rather than blocking the PoC.
- **Decision**: faster-whisper (CTranslate2) running `vinai/PhoWhisper-base` converted via `ct2-transformers-converter`, in-process (no subprocess/HTTP), full replacement of the whisper.cpp resident-server code.
- **Real benchmark section**: report the actual AC1/AC2 numbers from Task 4's real test run (pull them from `.superpowers/sdd/.../task-4-report.md` when this task is executed — do not write placeholder numbers now; this ADR is written after Task 4 completes). Explicitly compare against the external PoC's unverified "~1s / 10-15% WER" claim — state whether the real measurement matches, beats, or falls short of it.
- **Consequences**: `docs/devops.md`'s `STT_PROVIDER` canonical value changes to `faster_whisper` (this ADR is what authorizes that change — see Task 5 Step 2). This is scoped as a PoC/demo decision; a production hardware benchmark (matching real target device, not this dev machine) is still needed before treating this as final.
- **Revisit when**: real target hardware becomes available for a fresh AC1/AC2 measurement; a real Vietnamese-speaker WER corpus becomes available (consent-cleared); if anyone wants to resume investigating the whisper.cpp resident-server's WER regression (the root cause was never isolated — see ADR-007).

- [ ] **Step 2: Update `docs/devops.md`**

Find the line in the Environment contract table:
```
| `STT_PROVIDER` | `whisper_cpp` | Local transcription implementation |
```
Change it to:
```
| `STT_PROVIDER` | `faster_whisper` | Local transcription implementation (PoC/demo scope — see ADR-008) |
```

- [ ] **Step 3: Commit**

```bash
git add docs/adr/ADR-008-faster-whisper-stt-for-poc.md docs/devops.md
git commit -m "docs(adr): ADR-008 — chuyen STT sang faster-whisper cho PoC, cap nhat canonical devops.md"
```

---

### Task 6: Update WORKLOG.md

**Files:**
- Modify: `WORKLOG.md`

- [ ] **Step 1: Add a dated entry**

Add a new row (or new dated section if today's date differs from the existing 2026-08-07 section) to `WORKLOG.md` crediting "Nguyễn Tuấn Thành", summarizing: whisper.cpp resident-server WER regression discovered (~88% on both model sizes), decision to migrate to faster-whisper (CTranslate2) with PhoWhisper-base for the PoC/demo, real AC1/AC2 numbers measured (pull from Task 4's report — the actual pass/fail, not an assumption), full replacement of the whisper.cpp code path, ADR-008 + `docs/devops.md` canonical update. Reference the actual commit hashes from Tasks 1-5.

- [ ] **Step 2: Commit**

```bash
git add WORKLOG.md
git commit -m "docs(worklog): cập nhật WORKLOG.md — chuyển STT sang faster-whisper"
```

---

## Out of scope (unchanged from the design spec)

- HTTP endpoints `/voice/transcribe` / `/voice/synthesize`.
- Keeping whisper.cpp as an alternate provider (full replacement, no dual-provider switch — approved decision).
- Investigating the root cause of the whisper.cpp resident-server's WER regression (GGML conversion vs. multipart HTTP transport) — deferred, noted in ADR-008.
- WER on a real-speaker corpus.
- Formal production hardware benchmark — this is PoC/demo scope only, noted explicitly in ADR-008.

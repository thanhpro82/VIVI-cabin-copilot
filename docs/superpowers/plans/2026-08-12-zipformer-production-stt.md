# Zipformer Production STT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PhoWhisper-base (`faster-whisper`) with Zipformer-30M-RNNT-6000h (`sherpa-onnx`) as the sole production STT engine behind `POST /turns/voice`, based on Phase 1 eval evidence showing Zipformer's WER is roughly 3x lower and its latency roughly 8x lower on the same hardware.

**Architecture:** Swap `FasterWhisperEngine` for a `ZipformerEngine` inside `src/services/voice.py`, keeping every public function's signature identical (`transcribe()`, `transcribe_raw()`, `Transcript`, `get_stt_engine()`) so no caller outside `voice.py` changes. Update `src/config.py`'s STT settings, the model-setup script, and the two integration-test budgets to match the new engine's real measured numbers. Write a new ADR recording the decision and its evidence.

**Tech Stack:** `sherpa-onnx` (replacing `faster-whisper`), Python 3.11, pytest.

## Global Constraints

- Run everything through `.\.venv\Scripts\python.exe` (this worktree's venv; ignore any `.venv311` reference elsewhere in this repo's docs — it is a different branch's convention, not this worktree's).
- ruff line-length 120, select E/F/I/N/W/UP, E501 ignored.
- `sherpa-onnx` is already installed in `.venv` (added during Phase 1 eval tooling work) — verify with `import sherpa_onnx` rather than reinstalling from scratch, though Task 1 still updates `pyproject.toml` for a clean checkout.
- The Zipformer model files are already present at `models/voice/zipformer-30m-rnnt-6000h/{encoder.int8.onnx,decoder.int8.onnx,joiner.int8.onnx,tokens.txt}` in this worktree (downloaded during Phase 1) — tasks that need real model files use this directory directly; only Task 4 (the setup script) needs to actually exercise a download path, and it should do so via `--dry-run` to avoid a redundant real download.
- License: `hynt/Zipformer-30M-RNNT-6000h` is `cc-by-nc-nd-4.0` (non-commercial, no-derivatives) — do not fine-tune or redistribute the weights; this repo is a non-commercial academic prototype, so the license is compatible.
- `tests/test_services/test_voice_integration.py` tests are `@pytest.mark.integration` and only run when real model assets are present (`_assets_available()` checks `Path(settings.stt_model_path).is_dir()` and `Path(settings.tts_model_path).is_file()`) — this remains true after this plan's config changes.
- Evidence this plan cites: `eval/results/stt-compare/20260812T133954.391653Z/metrics.json` (50 cases: 24 synthetic + 26 real single-speaker) — PhoWhisper avg WER 26.1%, Zipformer avg WER 8.1%, PhoWhisper avg latency ~933ms, Zipformer avg latency ~69ms.

---

## Task 1: Swap the `sherpa-onnx` dependency into the `voice` extra

**Files:**
- Modify: `pyproject.toml:43-51`

**Interfaces:**
- Produces: `sherpa_onnx` importable after `pip install -e ".[voice]"`; `faster_whisper` no longer a declared dependency.

- [ ] **Step 1: Edit the dependency groups**

In `pyproject.toml`, change:

```toml
voice = [
    "piper-tts>=1.3,<2",
    "faster-whisper>=1.0,<2",
]
# Phase 1 quick eval only (scripts/eval_stt_compare.py) — not a src/ runtime dependency.
# See docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md.
stt-eval = [
    "sherpa-onnx>=1.10,<2",
]
```

to:

```toml
voice = [
    "piper-tts>=1.3,<2",
    "sherpa-onnx>=1.10,<2",
]
```

(This removes the `stt-eval` extra entirely — `sherpa-onnx` is now a `voice`-extra dependency, so Phase 1's eval scripts pick it up through `voice` too. `faster-whisper` is removed since nothing in `src/` will use it after Task 3.)

- [ ] **Step 2: Reinstall and verify**

Run: `.\.venv\Scripts\python.exe -m pip install -e ".[voice]"`
Then: `.\.venv\Scripts\python.exe -c "import sherpa_onnx; print(sherpa_onnx.__file__)"`
Expected: prints a path, no `ModuleNotFoundError`. (`faster_whisper` may still be importable afterward since `pip install -e` doesn't uninstall now-undeclared packages — that's fine, Task 3 removes the only code that imports it.)

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: replace faster-whisper with sherpa-onnx in voice extra"
```

---

## Task 2: Update STT settings in `src/config.py`

**Files:**
- Modify: `src/config.py:57-61`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.stt_provider` (default `"sherpa_onnx"`), `Settings.stt_model_path` (default `"./models/voice/zipformer-30m-rnnt-6000h"`), `Settings.stt_compute_type` (unchanged, `"int8"`), `Settings.stt_max_audio_seconds` (unchanged). `Settings.stt_beam_size` is removed (Whisper-specific, meaningless for Zipformer's `greedy_search` decoding).

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_config.py` with:

```python
from src.config import Settings


def test_voice_settings_have_canonical_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.stt_provider == "sherpa_onnx"
    assert settings.stt_model_path == "./models/voice/zipformer-30m-rnnt-6000h"
    assert settings.stt_compute_type == "int8"
    assert settings.stt_max_audio_seconds == 30
    assert settings.tts_provider == "piper"
    assert settings.tts_model_path == "./models/voice/vi_VN-piper.onnx"


def test_voice_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "/custom/model-dir")
    monkeypatch.setenv("TTS_MODEL_PATH", "/custom/voice.onnx")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "float32")

    settings = Settings(_env_file=None)

    assert settings.stt_model_path == "/custom/model-dir"
    assert settings.tts_model_path == "/custom/voice.onnx"
    assert settings.stt_compute_type == "float32"


def test_health_probe_settings_have_canonical_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.health_probe_timeout_s == 5.0
    assert settings.health_voice_probe_ttl_s == 10.0


def test_health_probe_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("HEALTH_PROBE_TIMEOUT_S", "2.5")
    monkeypatch.setenv("HEALTH_VOICE_PROBE_TTL_S", "15")

    settings = Settings(_env_file=None)

    assert settings.health_probe_timeout_s == 2.5
    assert settings.health_voice_probe_ttl_s == 15.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `test_voice_settings_have_canonical_defaults` fails on
`assert settings.stt_provider == "sherpa_onnx"` (still `"faster_whisper"`).

- [ ] **Step 3: Implement**

In `src/config.py`, change lines 57-61 from:

```python
    stt_provider: str = "faster_whisper"
    stt_model_path: str = "./models/voice/phowhisper-base-ct2"
    stt_compute_type: str = "int8"
    stt_beam_size: int = Field(default=5, ge=1, le=10)
    stt_max_audio_seconds: int = Field(default=30, ge=1, le=30)
```

to:

```python
    stt_provider: str = "sherpa_onnx"
    stt_model_path: str = "./models/voice/zipformer-30m-rnnt-6000h"
    stt_compute_type: str = "int8"
    stt_max_audio_seconds: int = Field(default=30, ge=1, le=30)
```

(`stt_beam_size` is deleted, not just unused — Zipformer decodes with `greedy_search`, which has no beam-width parameter, and leaving a dead config field would mislead a future reader into thinking it still tunes something.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(config): switch STT settings from PhoWhisper to Zipformer defaults"
```

---

## Task 3: Replace `FasterWhisperEngine` with `ZipformerEngine` in `src/services/voice.py`

**Files:**
- Modify: `src/services/voice.py:65-121` (the `FasterWhisperEngine` class, `get_stt_engine()`, and `_validate_audio()`)
- Modify: `tests/test_services/test_voice.py`

**Interfaces:**
- Consumes: `Settings.stt_provider`, `Settings.stt_model_path` (Task 2).
- Produces: `ZipformerEngine` class with `.transcribe_file(audio_path: Path) -> Transcript` (same interface `FasterWhisperEngine` had); `_normalize_output_casing(text: str) -> str`; `get_stt_engine() -> ZipformerEngine` (same `@lru_cache`d factory function name/behavior). `transcribe()`, `transcribe_raw()`, `Transcript`, `normalize_vietnamese_text()`, `word_error_rate()`, `char_error_rate()` are unchanged and not touched by this task.

- [ ] **Step 1: Write the failing tests**

In `tests/test_services/test_voice.py`, first extend the shared `_make_wav_bytes()`
helper (around line 41-48) to accept a `sampwidth` parameter, needed by the new
sampwidth-rejection test below:

```python
def _make_wav_bytes(*, duration_s: float = 1.0, frame_rate: int = 16000, sampwidth: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(sampwidth)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00" * sampwidth * int(duration_s * frame_rate))
    return buffer.getvalue()
```

(The default `sampwidth=2` keeps every existing call site — which doesn't pass this
argument — producing byte-identical output to before.)

Then find `test_transcribe_rejects_non_16khz_mono_audio` (around line 170, unaffected by
the block replacement below) and add a new test directly after it:

```python
def test_transcribe_rejects_non_16bit_audio() -> None:
    with pytest.raises(ValueError, match="16-bit"):
        transcribe(_make_wav_bytes(sampwidth=1))
```

Now replace lines 11-19 (the import block) with:

```python
from src.services.voice import (
    PiperEngine,
    ZipformerEngine,
    char_error_rate,
    normalize_vietnamese_text,
    synthesize,
    transcribe,
    word_error_rate,
)
from src.services.voice import _normalize_output_casing
```

Replace lines 51-123 (from `class _FakeSegment:` through the end of
`test_faster_whisper_engine_serializes_concurrent_transcribe_calls`) with:

```python
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
```

Now find `test_get_stt_engine_rejects_incomplete_model_directory` further down in the same
file (currently around line 191) and replace it with:

```python
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
```

(This is the same test, just with a Zipformer-shaped fixture directory instead of a
PhoWhisper one — `test_get_stt_engine_rejects_unsupported_provider` right above it needs
no changes.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice.py -v`
Expected: FAIL — `ImportError: cannot import name 'ZipformerEngine'` (and
`_normalize_output_casing` doesn't exist yet).

- [ ] **Step 3: Implement**

In `src/services/voice.py`, replace lines 65-104 (the `FasterWhisperEngine` class through
the end of `get_stt_engine()`) with:

```python
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
        with self._lock:
            with wave.open(str(audio_path), "rb") as wav_file:
                raw_frames = wav_file.readframes(wav_file.getnframes())
            samples_int16 = np.frombuffer(raw_frames, dtype=np.int16)
            samples_float32 = samples_int16.astype(np.float32) / 32768.0
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
```

Add `import numpy as np` to the top of `src/services/voice.py`'s import block (alongside
the existing `import wave` — `numpy` is already a project dependency, declared in
`pyproject.toml`'s main `dependencies` list).

Also fix a latent bug `_validate_audio()` shares with the old engine: it never checked
`sampwidth`, so a non-16-bit WAV would previously pass validation and reach
`faster_whisper`'s own decoder (which handled arbitrary widths internally) — but
`ZipformerEngine.transcribe_file()` above does a raw `np.frombuffer(..., dtype=np.int16)`,
so a non-16-bit WAV now silently produces garbage samples with no error. In
`_validate_audio()` (`src/services/voice.py:107-121`, directly above `transcribe_raw()`
at line 124), change:

```python
            if wav_file.getnchannels() != 1 or framerate != 16000:
                raise ValueError("audio must be 16kHz mono WAV")
```

to:

```python
            if wav_file.getnchannels() != 1 or framerate != 16000 or wav_file.getsampwidth() != 2:
                raise ValueError("audio must be 16-bit 16kHz mono WAV")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice.py -v`
Expected: all tests pass (the file has ~20 tests total; only the ones touched in Step 1
change in count/name — the rest, e.g. `PiperEngine`/TTS tests, are untouched and should
still pass unmodified).

- [ ] **Step 5: Lint and commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/services/voice.py tests/test_services/test_voice.py
.\.venv\Scripts\python.exe -m ruff format src/services/voice.py tests/test_services/test_voice.py
git add src/services/voice.py tests/test_services/test_voice.py
git commit -m "feat(voice): replace FasterWhisperEngine with ZipformerEngine"
```

---

## Task 4: Update the model-setup script

**Files:**
- Modify: `scripts/setup_voice_models.ps1`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone PowerShell script).
- Produces: `models/voice/zipformer-30m-rnnt-6000h/{encoder.int8.onnx,decoder.int8.onnx,joiner.int8.onnx,tokens.txt}` plus `.sha256`/`.metadata.json` sidecars per file, matching what `get_stt_engine()` (Task 3) requires.

- [ ] **Step 1: Replace the script**

Replace the full contents of `scripts/setup_voice_models.ps1` with:

```powershell
[CmdletBinding()]
param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\models\voice"),
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$zipformerRepo = "hynt/Zipformer-30M-RNNT-6000h"
$zipformerRevision = "24ed30248e1c96bb690c81c24ab4e056f8cd9fce"
$zipformerLicense = "cc-by-nc-nd-4.0"
$resolvedOutputDir = [IO.Path]::GetFullPath($OutputDir)
$modelOutputDir = Join-Path $resolvedOutputDir "zipformer-30m-rnnt-6000h"

# (repo filename, local filename). config.json in this HF repo is the
# sherpa-onnx tokens.txt token list, not a JSON config, so it is saved
# locally as tokens.txt directly.
$artifacts = @(
    @{ Repo = "encoder-epoch-20-avg-10.int8.onnx"; Local = "encoder.int8.onnx" }
    @{ Repo = "decoder-epoch-20-avg-10.int8.onnx"; Local = "decoder.int8.onnx" }
    @{ Repo = "joiner-epoch-20-avg-10.int8.onnx"; Local = "joiner.int8.onnx" }
    @{ Repo = "config.json"; Local = "tokens.txt" }
)

if ($DryRun) {
    [pscustomobject]@{
        Repository = $zipformerRepo
        Revision   = $zipformerRevision
        License    = $zipformerLicense
        OutputDir  = $modelOutputDir
        Artifacts  = $artifacts
    } | ConvertTo-Json -Depth 4
    exit 0
}

$hfCommand = Get-Command hf -ErrorAction SilentlyContinue
if (-not $hfCommand) {
    throw "Hugging Face CLI 'hf' was not found. Install huggingface_hub first."
}

New-Item -ItemType Directory -Path $modelOutputDir -Force | Out-Null

foreach ($artifact in $artifacts) {
    $targetPath = Join-Path $modelOutputDir $artifact.Local
    if (-not (Test-Path -LiteralPath $targetPath)) {
        $tempDir = Join-Path $modelOutputDir "_download_tmp"
        & $hfCommand.Source download $zipformerRepo $artifact.Repo --revision $zipformerRevision --local-dir $tempDir
        if ($LASTEXITCODE -ne 0) {
            throw "Download of $($artifact.Repo) failed with exit code $LASTEXITCODE."
        }
        Move-Item -LiteralPath (Join-Path $tempDir $artifact.Repo) -Destination $targetPath -Force
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
    $hash = Get-FileHash -LiteralPath $targetPath -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant())  $($artifact.Local)" |
        Set-Content -LiteralPath "$targetPath.sha256" -Encoding utf8
    [pscustomobject]@{
        Repository      = $zipformerRepo
        Revision        = $zipformerRevision
        RepoFilename    = $artifact.Repo
        LocalFilename   = $artifact.Local
        License         = $zipformerLicense
        Sha256          = $hash.Hash.ToLowerInvariant()
        SizeBytes       = (Get-Item -LiteralPath $targetPath).Length
        DownloadedAtUtc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath "$targetPath.metadata.json" -Encoding utf8
}

Write-Output "STT model ready: $modelOutputDir"
Write-Output ""
Write-Output "TTS setup is manual: download a Vietnamese Piper voice (.onnx + .onnx.json)"
Write-Output "from https://github.com/rhasspy/piper/blob/master/VOICES.md into $resolvedOutputDir"
Write-Output "as vi_VN-piper.onnx (matching Settings.tts_model_path default)."
```

- [ ] **Step 2: Verify with `--dry-run` (do not trigger a real download — the model is already present in this worktree)**

Run: `.\.venv\Scripts\python.exe -c "exit(0)"` — placeholder skip note: actually run the
PowerShell script itself:

Run: `pwsh scripts/setup_voice_models.ps1 -DryRun`
Expected: prints a JSON object with `Repository: hynt/Zipformer-30M-RNNT-6000h`,
`Revision: 24ed30248e1c96bb690c81c24ab4e056f8cd9fce`, `License: cc-by-nc-nd-4.0`, and the
4 artifacts, with no errors and no network call.

- [ ] **Step 3: Commit**

```bash
git add scripts/setup_voice_models.ps1
git commit -m "feat(scripts): point setup_voice_models.ps1 at Zipformer instead of PhoWhisper"
```

---

## Task 5: Re-measure and tighten the integration test budgets

**Files:**
- Modify: `tests/test_services/test_voice_integration.py:39-85`

**Interfaces:**
- Consumes: `get_stt_engine()`, `transcribe()`, `transcribe_raw()`, `word_error_rate()` (Task 3, unchanged signatures). Runs against the real model already present at `models/voice/zipformer-30m-rnnt-6000h/`.

This task requires the real model and fixture assets to be present (they already are in
this worktree) — the two tests being changed are gated by
`@pytest.mark.skipif(not _warm_sample_available(), ...)` and
`@pytest.mark.skipif(not _synthetic_commands_available(), ...)`, both of which resolve
`True` here, so `pytest -m integration` actually exercises the real engine.

- [ ] **Step 1: Measure warm latency for real, 5 samples**

Run:

```
.\.venv\Scripts\python.exe -c "
import statistics
from pathlib import Path
import time
from src.services.voice import get_stt_engine, transcribe

audio_bytes = Path('tests/fixtures/voice/warm_sample.wav').read_bytes()
get_stt_engine()
transcribe(audio_bytes)  # discard first call (model load variance)

samples_ms = []
for _ in range(5):
    started = time.perf_counter()
    transcribe(audio_bytes)
    samples_ms.append((time.perf_counter() - started) * 1000)

print('samples_ms =', samples_ms)
print('avg_ms =', statistics.mean(samples_ms))
"
```

Record the printed `avg_ms` value (call it `MEASURED_LATENCY_MS`).

- [ ] **Step 2: Measure synthetic loopback WER for real**

Run:

```
.\.venv\Scripts\python.exe -c "
import json
from pathlib import Path
from src.services.voice import get_stt_engine, transcribe, word_error_rate

manifest = json.loads(Path('tests/fixtures/voice/synthetic_commands/manifest.json').read_text(encoding='utf-8'))
get_stt_engine()

rates = []
for entry in manifest:
    audio_path = Path('tests/fixtures/voice/synthetic_commands') / entry['file']
    result = transcribe(audio_path.read_bytes())
    rates.append(word_error_rate(entry['text'], result.text))

average_wer = sum(rates) / len(rates)
print('average_wer =', average_wer)
"
```

Record the printed `average_wer` value (call it `MEASURED_WER`).

- [ ] **Step 3: Update the two budget assertions**

In `tests/test_services/test_voice_integration.py`, in
`test_transcribe_warm_latency_is_under_budget` (around line 40-57), replace the comment
and assertion:

```python
    # Budget: PoC target is ~1s (unverified figure from an external PoC, see
    # docs/superpowers/specs/2026-08-07-faster-whisper-migration-design.md).
    # 1.5s carries forward the whisper.cpp-era revised budget as a ceiling
    # until this is re-measured and possibly tightened in ADR-008.
    assert wall_ms < 1500, f"warm transcribe took {wall_ms:.1f}ms, budget is 1500ms"
```

with (substituting the literal value of `ceil(MEASURED_LATENCY_MS / 50) * 50 * 2` computed
from Step 1's `MEASURED_LATENCY_MS` — e.g. if `MEASURED_LATENCY_MS` was 69.2, the budget is
`ceil(69.2/50)*50*2 = 100*2 = 200`):

```python
    # Budget: measured warm-call average was {MEASURED_LATENCY_MS}ms on this dev
    # machine (5-sample average, see ADR-017's real-benchmark section). Budget is
    # that value rounded up to the nearest 50ms, doubled for headroom — not the
    # measured figure itself, since dev-machine timing varies run to run.
    assert wall_ms < <COMPUTED_BUDGET>, f"warm transcribe took {wall_ms:.1f}ms, budget is <COMPUTED_BUDGET>ms"
```

(Fill in the two `<COMPUTED_BUDGET>` placeholders with the actual computed integer from
Step 1's measurement and the `{MEASURED_LATENCY_MS}` placeholder with Step 1's actual
number — these are not literary placeholders left for a future editor, they are values
this step's measurement produces; the implementer computes and substitutes them now.)

In `test_synthetic_loopback_word_error_rate_is_under_budget` (around line 63-85), replace
the comment and assertion similarly, using `MEASURED_WER` from Step 2, budget =
`ceil((MEASURED_WER + 0.05) * 100) / 100` (measured value plus 5 percentage points,
rounded up to the nearest whole percent — e.g. if `MEASURED_WER` was 0.127, budget is
`ceil((0.127+0.05)*100)/100 = ceil(17.7)/100 = 18/100 = 0.18`):

```python
    average_wer = sum(rates) / len(rates)
    # This is a synthetic-audio smoke check (fixed Piper output fed back
    # through the STT engine), not a real-speaker accuracy benchmark — see
    # ADR-017 and the Phase 1 design spec's WER caveat.
    #
    # Budget: measured average was {MEASURED_WER:.2%} on this fixture (see
    # ADR-017's real-benchmark section). Budget is that value plus 5 percentage
    # points, rounded up to the nearest whole percent — headroom against
    # dev-machine/run variance, not the measured figure itself.
    assert average_wer < <COMPUTED_WER_BUDGET>, f"synthetic loopback WER {average_wer:.2%} exceeds <COMPUTED_WER_BUDGET:.0%> budget (ADR-017)"
```

Also update `test_correction_layer_never_increases_synthetic_loopback_wer`'s docstring
comment block (around line 126-144) — it references "the numeral-protection fix" history
which stays accurate, but delete or rewrite anything in it that implies the specific
`raw_wer`/`corrected_wer` numbers are PhoWhisper's; re-run the test and confirm the
assertion `average_corrected_wer <= average_raw_wer` still holds under Zipformer (if it
does not hold, that's a real finding — do not force it; report it in the task report
instead of weakening the assertion).

- [ ] **Step 4: Run the integration tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice_integration.py -v -m integration`
Expected: all tests pass (none skipped, since assets are present in this worktree).

- [ ] **Step 5: Commit**

```bash
git add tests/test_services/test_voice_integration.py
git commit -m "test(voice): re-measure and tighten latency/WER budgets for Zipformer"
```

---

## Task 6: Write ADR-017 and update cross-referencing docs

**Files:**
- Create: `docs/adr/ADR-017-zipformer-production-stt.md`
- Modify: `docs/devops.md:46-47`
- Modify: `CLAUDE.md` (3 references: the P0-product description, the `pip install` comment, and the turn-pipeline diagram)

**Interfaces:**
- Consumes: nothing from earlier tasks (documentation only). References the run id
  `eval/results/stt-compare/20260812T133954.391653Z/` and Task 5's measured numbers.

- [ ] **Step 1: Write the ADR**

Create `docs/adr/ADR-017-zipformer-production-stt.md`:

```markdown
# ADR-017: Chuyển STT production sang Zipformer-30M-RNNT-6000h (sherpa-onnx)

- Status: Accepted (PoC/demo scope) — supersedes ADR-008's engine choice
- Date: 2026-08-12
- Decision owner: WS1 Voice & Edge

## Context

ADR-008 chọn faster-whisper (PhoWhisper-base qua CTranslate2) làm engine STT sau khi
whisper.cpp/GGML cho WER ~88% không dùng được. faster-whisper cải thiện xuống 30.24%
trên loopback synthetic — vẫn FAIL so với budget 20% ban đầu, và ADR-008 tự ghi nhận đây
chỉ là quyết định phạm vi PoC/demo.

Một báo cáo lỗi thực tế trong quá trình phát triển ("áp suất lốp là bao nhiêu" bị nhận
thành "nốt cà bao nhiêu") dẫn tới một cuộc điều tra hai giai đoạn:

- **Phase 1** (`docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md`) xây dựng
  công cụ so sánh WER/CER giữa PhoWhisper-base và `hynt/Zipformer-30M-RNNT-6000h` (một
  model ASR tiếng Việt train trên 6000h dữ liệu, chạy qua `sherpa-onnx`), trên bộ 24 câu
  domain-specific (áp suất lốp, điều hòa, âm lượng), ban đầu bằng audio Piper TTS synthetic.
- Sau khi có công cụ, nhóm tự thu thêm 26 mẫu giọng người thật (1 người nói) cho cùng 24
  câu, chạy lại so sánh.

## Real benchmark section

Run cuối cùng: `eval/results/stt-compare/20260812T133954.391653Z/metrics.json`
(50 case: 24 synthetic + 26 giọng thật):

- **Tổng thể:** PhoWhisper avg WER 26.12%, Zipformer avg WER 8.08%. Zipformer avg
  latency ~69ms, PhoWhisper avg latency ~933ms (trên cùng máy dev).
- **Chỉ tính 26 case giọng thật:** PhoWhisper avg WER 20.5%, Zipformer avg WER 3.8%.
- **Quan sát định tính quan trọng:** đọc từng transcript giọng thật cho thấy PhoWhisper
  gần như luôn cắt mất hoặc làm sai từ đầu tiên của câu (vd "Áp suất lốp..." →
  "lốp hiện tại...", "Bật điều hòa" → "mật điều hòa", một case bịa hẳn cụm từ "thông
  minh hồ ngọc hà" không liên quan). Zipformer không có pattern này trên cùng file. Đây
  là bằng chứng cho thấy lỗi ban đầu ("nốt cà bao nhiêu") nhiều khả năng là lỗi cắt đầu
  audio của PhoWhisper, không hẳn là giới hạn từ vựng domain như giả thuyết ban đầu.
- **Theo domain** (from `by_domain` trong cùng file): HVAC 39.9%→6.0%, baseline (từ đã
  biết) 24.0%→6.7%, tire_pressure 32.2%→14.4% — Zipformer tốt hơn rõ rệt ở mọi domain
  trên bộ synthetic; domain volume ban đầu synthetic không cải thiện (28.1%→27.6%) nhưng
  trên giọng thật thì Zipformer gần như đúng tuyệt đối, gợi ý vấn đề volume trước đó có
  thể đặc thù giọng Piper TTS chứ không phải giới hạn thật của Zipformer.
- Sau khi tích hợp vào production code (`src/services/voice.py`), đo lại warm latency
  và synthetic loopback WER thực tế: xem `tests/test_services/test_voice_integration.py`
  cho số đo cuối cùng dùng làm budget (đo trong Task 5 của
  `docs/superpowers/plans/2026-08-12-zipformer-production-stt.md`).

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Giữ faster-whisper/PhoWhisper-base (ADR-008) | Không cần thay đổi | WER cao hơn 3x, latency cao hơn 8x, và có pattern cắt-đầu-câu hệ thống trên giọng thật |
| **Zipformer-30M-RNNT-6000h qua sherpa-onnx (đã chọn)** | WER thấp hơn nhiều, latency thấp hơn nhiều, không có pattern cắt đầu câu | Model dưới license `cc-by-nc-nd-4.0` (non-commercial, no-derivatives — chấp nhận được vì dự án học thuật phi thương mại, không fine-tune); `sherpa_onnx.OfflineRecognizer` chưa có tài liệu chính thức về thread-safety, phải tự serialize bằng lock như đã làm với faster-whisper |
| Giữ cả hai, chọn qua config | An toàn hơn để rollback | Tăng bề mặt bảo trì (2 code path), không cần thiết khi bằng chứng đã rõ ràng |

## Decision

Thay `FasterWhisperEngine` bằng `ZipformerEngine` trong `src/services/voice.py`, thay
thế hoàn toàn (không giữ song song), theo đúng pattern ADR-008 đã dùng khi thay
whisper.cpp. `STT_PROVIDER` canonical value đổi từ `faster_whisper` sang `sherpa_onnx`.

## Rationale

- Bằng chứng đo được (không phải suy đoán): WER thấp hơn 3x, latency thấp hơn 8x, trên
  cả synthetic lẫn giọng người thật, đo trên cùng máy dev bằng cùng công cụ.
- Pattern cắt-đầu-câu của PhoWhisper xuất hiện nhất quán trên nhiều domain khác nhau
  (lốp, điều hòa, âm lượng, cả các lệnh baseline đã biết) — không phải nhiễu ngẫu nhiên.
- License `cc-by-nc-nd-4.0` phù hợp phạm vi dự án (học thuật, phi thương mại, không
  fine-tune model).

## Consequences

- `docs/devops.md`'s `STT_PROVIDER`/`STT_MODEL_PATH` canonical values đổi — ADR này là
  văn bản authorize thay đổi đó.
- `pyproject.toml`'s `voice` extra đổi từ `faster-whisper` sang `sherpa-onnx`.
- `scripts/setup_voice_models.ps1` đổi từ tải+convert PhoWhisper sang tải Zipformer.
- `Settings.stt_beam_size` bị xóa (đặc thù Whisper, không áp dụng cho decoding
  `greedy_search` của transducer).
- **Vẫn là quyết định phạm vi PoC/demo, không phải kết luận production cuối cùng.**
  Bằng chứng giọng thật chỉ có **1 người nói** — chưa có đa dạng giọng vùng miền, giới
  tính, độ tuổi, hay điều kiện nhiễu (cabin thật khi xe chạy). Cùng giới hạn ADR-008 tự
  khai báo cho số đo của nó.
- Concurrency: giữ nguyên pattern `threading.Lock` serialize `.transcribe_file()`, vì
  `sherpa_onnx.OfflineRecognizer` chưa có xác nhận chính thức về thread-safety khi gọi
  đồng thời — đánh đổi tương tự ADR-008 đã chấp nhận cho faster-whisper.

## Revisit when

- Có nhiều người nói hơn (đa dạng vùng miền/giới tính) ghi âm vào
  `eval/datasets/poc/v1/audio/` — chạy lại `scripts/eval_stt_compare.py` để xác nhận
  margin vẫn giữ.
- Có phần cứng target thật (không phải máy dev) để đo lại latency.
- `sherpa_onnx.OfflineRecognizer`'s thread-safety được xác nhận chính thức (hoặc có test
  concurrency riêng) — có thể bỏ lock nếu an toàn, tăng throughput.
```

- [ ] **Step 2: Update `docs/devops.md`**

Change lines 46-47 from:

```markdown
| `STT_PROVIDER` | `faster_whisper` | Local transcription implementation (PoC/demo scope — see ADR-008) |
| `STT_MODEL_PATH` | `/models/stt/phowhisper-base-ct2/` | STT artifact (CTranslate2 model directory, not a file) |
```

to:

```markdown
| `STT_PROVIDER` | `sherpa_onnx` | Local transcription implementation (PoC/demo scope — see ADR-017) |
| `STT_MODEL_PATH` | `/models/stt/zipformer-30m-rnnt-6000h/` | STT artifact (sherpa-onnx ONNX model directory, not a file) |
```

- [ ] **Step 3: Update `CLAUDE.md`**

Three changes:

1. Around line 11 (the P0-product description), change `"MQTT vehicle simulator,
   faster-whisper STT"` to `"MQTT vehicle simulator, sherpa-onnx (Zipformer) STT"`.
2. Around line 32, change the comment `# faster-whisper + piper` to
   `# sherpa-onnx (Zipformer) + piper`.
3. Around line 140 (the P0 turn pipeline diagram), change
   `"→ faster-whisper STT + Vietnamese correction layer   src/services/voice*.py  (voice only)"`
   to
   `"→ sherpa-onnx (Zipformer) STT + Vietnamese correction layer   src/services/voice*.py  (voice only)"`.

- [ ] **Step 4: Commit**

```bash
git add docs/adr/ADR-017-zipformer-production-stt.md docs/devops.md CLAUDE.md
git commit -m "docs(adr): record ADR-017, switch production STT to Zipformer"
```

---

## Task 7: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite, including integration tests**

Run: `MQTT_ENABLED=false .\.venv\Scripts\python.exe -m pytest tests/ -q -m "integration or not integration"`

(The `-m "integration or not integration"` expression forces collection of both marked
and unmarked tests in one run, since this repo has no `addopts` deselecting `integration`
by default — see `CLAUDE.md`'s marker documentation. If this expression is rejected by
this pytest version, run `pytest tests/ -q` instead — integration tests run by default
here already since nothing deselects them.)

Expected: 0 failures. Compare the pass/skip counts against the pre-Task-1 baseline (run
`git log` to find it, or note that Phase 1's final baseline was 918 passed / 23 skipped)
— a higher pass count and lower skip count is expected here, since Task 5's two
previously-`skipif`-gated tests now execute for real in this environment (they were
already resolving to "asset available" before this plan, so this mainly confirms nothing
regressed, not a large count change).

- [ ] **Step 2: Confirm `POST /turns/voice`'s existing tests need no changes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -v`
Expected: all pass, unchanged from before this plan — this file fully stubs
`voice.get_stt_engine`/`voice.transcribe` via `monkeypatch` (see `_stub_stt()` around
line 43), so it never touches the real engine and needed no edits in this plan.

- [ ] **Step 3: Confirm no stray references to the old engine remain**

Run: `.\.venv\Scripts\python.exe -c "import ast, pathlib; [print(p) for p in pathlib.Path('src').rglob('*.py') if 'FasterWhisperEngine' in p.read_text(encoding='utf-8') or 'faster_whisper' in p.read_text(encoding='utf-8')]"`

Expected: no output (empty — nothing in `src/` should still reference the old engine or
import path).

- [ ] **Step 4: Report**

No commit for this task (verification only) — summarize the final pass/skip counts and
confirm Task 5's measured budget values in the task report, so the controller/human
partner has the final numbers without re-running anything.

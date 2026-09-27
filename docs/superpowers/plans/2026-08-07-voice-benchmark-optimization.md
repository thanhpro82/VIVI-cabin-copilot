# Voice Adapter Benchmark Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the voice adapter (`src/services/voice.py`) as close as possible to AC1/AC2 by switching STT from PhoWhisper-small (subprocess `whisper-cli`) to PhoWhisper-base served by a resident `whisper-server`, fixing the non-deterministic WER test methodology, and formally revising AC1 to the real measured budget.

**Architecture:** `WhisperCppEngine` stops shelling out to `whisper-cli` per call (which reloads the model every time) and instead talks HTTP to a `whisper-server` subprocess spawned once by `get_stt_engine()` and kept resident. A new `start_whisper_server()` function owns process spawn + port health-check; `WhisperServerHandle` owns the process lifecycle (`stop()` with terminate→kill fallback). AC2's loopback test switches from calling the non-deterministic `PiperEngine.synthesize()` live to reading fixed, pre-generated WAV fixtures.

**Tech Stack:** Python 3.11, `whisper.cpp` `whisper-server.exe` (native binary, HTTP `/inference`), `httpx` (sync client, already a project dependency), `piper-tts`, pytest.

## Global Constraints

- Model: **PhoWhisper-base** (not small, not tiny) — GGUF via whisper.cpp. Chosen because it is ~4x faster than small and, unlike tiny, does not completely fail on synthetic audio (see `docs/superpowers/specs/2026-08-07-voice-benchmark-optimization-design.md`).
- Engine: resident `whisper-server` (HTTP `/inference`), not subprocess `whisper-cli` per call.
- `whisper-server` always started with `-nf` (`--no-fallback`) by default (`Settings.stt_no_fallback: bool = True`) to bound latency and avoid the multi-second temperature-fallback retry spikes measured on 2026-08-07. Entropy/logprob/no-speech-threshold tuning and VAD are explicitly **out of scope** for this plan (no empirical basis yet for exact values beyond `-nf`) — a future task if hallucination persists.
- AC1 latency-warm budget is **`<1.5s`** (revised from `<400ms`), based on real measurement: best achievable on CPU-only target hardware after model swap + resident server + max threads was ~900ms-1.6s — see ADR-007 "Benchmark thật 2026-08-07".
- AC2 WER budget stays `<20%`, but the loopback test must use **fixed, pre-generated** Piper WAV fixtures, not a live `synthesize()` call — `PiperEngine.synthesize()` was confirmed non-deterministic (same text, two calls, two different audio byte counts) on 2026-08-07.
- Scope stays module-internal (`src/services/voice.py`) — no HTTP endpoint added, per ADR-007 (unchanged).
- `ruff check src/ tests/` and `ruff format --check src/ tests/` must pass (matches `.github/workflows/ci.yml`).
- Follow `docs/GIT_WORKFLOW.md`: work stays on `feature/voice-asr-tts-design`, no direct push to `develop`/`main`.
- TDD every task: write failing test → verify it fails → minimal implementation → verify it passes → commit.

---

### Task 1: Config settings for the resident whisper-server

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.stt_model_path` (now defaults to the base GGUF filename), `Settings.stt_server_executable_path: str`, `Settings.stt_server_host: str`, `Settings.stt_server_port: int`, `Settings.stt_server_threads: int`, `Settings.stt_no_fallback: bool`, `Settings.stt_server_startup_timeout_s: float`. Removes `Settings.stt_executable_path` (dead once Task 4 lands — nothing else in the codebase references it).

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_config.py` with:

```python
from src.config import Settings


def test_voice_settings_have_canonical_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.stt_provider == "whisper_cpp"
    assert settings.stt_model_path == "./models/voice/ggml-phowhisper-base.bin"
    assert settings.stt_max_audio_seconds == 30
    assert settings.stt_server_executable_path == "whisper-server"
    assert settings.stt_server_host == "127.0.0.1"
    assert settings.stt_server_port == 8090
    assert settings.stt_server_threads >= 1
    assert settings.stt_no_fallback is True
    assert settings.stt_server_startup_timeout_s == 15.0
    assert settings.tts_provider == "piper"
    assert settings.tts_model_path == "./models/voice/vi_VN-piper.onnx"


def test_voice_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "/custom/model.bin")
    monkeypatch.setenv("TTS_MODEL_PATH", "/custom/voice.onnx")
    monkeypatch.setenv("STT_SERVER_PORT", "9090")
    monkeypatch.setenv("STT_NO_FALLBACK", "false")

    settings = Settings(_env_file=None)

    assert settings.stt_model_path == "/custom/model.bin"
    assert settings.tts_model_path == "/custom/voice.onnx"
    assert settings.stt_server_port == 9090
    assert settings.stt_no_fallback is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'stt_server_executable_path'` (and the model path assertion also fails since it still points at `-small.bin`).

- [ ] **Step 3: Write minimal implementation**

In `src/config.py`, add `import os` at the top (after existing imports), then replace the voice adapter block:

```python
    # Voice adapter (STT/TTS) — names match docs/devops.md Environment contract
    stt_provider: str = "whisper_cpp"
    stt_model_path: str = "./models/voice/ggml-phowhisper-base.bin"
    stt_max_audio_seconds: int = Field(default=30, ge=1, le=30)
    stt_server_executable_path: str = "whisper-server"
    stt_server_host: str = "127.0.0.1"
    stt_server_port: int = Field(default=8090, ge=1, le=65535)
    stt_server_threads: int = Field(default_factory=lambda: os.cpu_count() or 4, ge=1, le=128)
    stt_no_fallback: bool = True
    stt_server_startup_timeout_s: float = Field(default=15.0, gt=0)
    tts_provider: str = "piper"
    tts_model_path: str = "./models/voice/vi_VN-piper.onnx"
```

This replaces the previous block that had `stt_executable_path: str = "whisper-cli"` and `stt_model_path: str = "./models/voice/ggml-phowhisper-small.bin"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check src/config.py tests/test_config.py && python -m ruff format --check src/config.py tests/test_config.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(voice): switch STT settings to resident whisper-server + PhoWhisper-base"
```

---

### Task 2: Resident whisper-server process lifecycle

**Files:**
- Modify: `src/services/voice.py`
- Test: `tests/test_services/test_voice.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure process-management primitive).
- Produces: `WhisperServerHandle(process, base_url)` with `.stop() -> None`; `ProcessSpawner = Callable[[list[str]], subprocess.Popen]`; `PortProber = Callable[[str, int, float], bool]`; `start_whisper_server(executable: Path, model_path: Path, host: str, port: int, threads: int, no_fallback: bool, startup_timeout_s: float, spawner: ProcessSpawner = ..., port_prober: PortProber = ...) -> WhisperServerHandle`. Task 3 and Task 4 depend on these exact names/signatures.

- [ ] **Step 1: Write the failing tests**

Add to the top of `tests/test_services/test_voice.py`, alongside the existing imports, add `subprocess` to the `import` list (new `import subprocess` line near the top), and add these imports to the `from src.services.voice import (...)` block: `WhisperServerHandle`, `start_whisper_server`. Then append this test double and these tests at the end of the file (after `test_synthesize_rejects_empty_text`):

```python
class _FakeProcess:
    def __init__(self, poll_results: list[int | None] | None = None) -> None:
        self._poll_results = list(poll_results or [])
        self.terminated = False
        self.killed = False
        self.returncode: int | None = None
        self.wait_timeout_before_success = False
        self._wait_call_count = 0

    def poll(self) -> int | None:
        if self._poll_results:
            self.returncode = self._poll_results.pop(0)
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> None:
        self._wait_call_count += 1
        if self.wait_timeout_before_success and self._wait_call_count == 1:
            raise subprocess.TimeoutExpired(cmd=["whisper-server"], timeout=timeout or 0)


def test_start_whisper_server_returns_handle_once_port_is_reachable() -> None:
    fake_process = _FakeProcess()
    spawned_commands: list[list[str]] = []

    def fake_spawner(command: list[str]) -> _FakeProcess:
        spawned_commands.append(command)
        return fake_process

    handle = start_whisper_server(
        executable=Path("whisper-server"),
        model_path=Path("model.bin"),
        host="127.0.0.1",
        port=8090,
        threads=8,
        no_fallback=True,
        startup_timeout_s=5.0,
        spawner=fake_spawner,
        port_prober=lambda host, port, timeout_s: True,
    )

    assert handle.base_url == "http://127.0.0.1:8090"
    assert handle.process is fake_process
    assert spawned_commands == [
        ["whisper-server", "-m", "model.bin", "--host", "127.0.0.1", "--port", "8090", "-t", "8", "-nf"]
    ]


def test_start_whisper_server_omits_no_fallback_flag_when_disabled() -> None:
    captured: dict[str, list[str]] = {}

    def fake_spawner(command: list[str]) -> _FakeProcess:
        captured["command"] = command
        return _FakeProcess()

    start_whisper_server(
        executable=Path("whisper-server"),
        model_path=Path("model.bin"),
        host="127.0.0.1",
        port=8090,
        threads=4,
        no_fallback=False,
        startup_timeout_s=5.0,
        spawner=fake_spawner,
        port_prober=lambda host, port, timeout_s: True,
    )

    assert "-nf" not in captured["command"]


def test_start_whisper_server_raises_timeout_when_port_never_opens() -> None:
    fake_process = _FakeProcess()

    with pytest.raises(TimeoutError, match="did not become ready"):
        start_whisper_server(
            executable=Path("whisper-server"),
            model_path=Path("model.bin"),
            host="127.0.0.1",
            port=8090,
            threads=4,
            no_fallback=True,
            startup_timeout_s=0.05,
            spawner=lambda command: fake_process,
            port_prober=lambda host, port, timeout_s: False,
        )

    assert fake_process.terminated


def test_start_whisper_server_raises_runtime_error_when_process_exits_early() -> None:
    fake_process = _FakeProcess(poll_results=[1])

    with pytest.raises(RuntimeError, match="exited early"):
        start_whisper_server(
            executable=Path("whisper-server"),
            model_path=Path("model.bin"),
            host="127.0.0.1",
            port=8090,
            threads=4,
            no_fallback=True,
            startup_timeout_s=5.0,
            spawner=lambda command: fake_process,
            port_prober=lambda host, port, timeout_s: False,
        )


def test_whisper_server_handle_stop_terminates_process_gracefully() -> None:
    fake_process = _FakeProcess()
    handle = WhisperServerHandle(process=fake_process, base_url="http://127.0.0.1:8090")

    handle.stop()

    assert fake_process.terminated
    assert not fake_process.killed


def test_whisper_server_handle_stop_kills_process_when_terminate_times_out() -> None:
    fake_process = _FakeProcess()
    fake_process.wait_timeout_before_success = True
    handle = WhisperServerHandle(process=fake_process, base_url="http://127.0.0.1:8090")

    handle.stop()

    assert fake_process.terminated
    assert fake_process.killed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_voice.py -v -k "whisper_server"`
Expected: FAIL — `ImportError: cannot import name 'WhisperServerHandle'`

- [ ] **Step 3: Write minimal implementation**

In `src/services/voice.py`, add `import socket` to the existing `import` block (alongside `subprocess`), then add this code after the `_default_whisper_runner` function and before the `WhisperCppEngine` class (the old `WhisperCppEngine`/`get_stt_engine`/`_validate_audio`/`transcribe` block will be replaced in Tasks 3-4; for this task, insert the new code without removing the old code yet — Task 3 removes the old `WhisperCppEngine`):

```python
class WhisperServerHandle:
    def __init__(self, process: subprocess.Popen, base_url: str) -> None:
        self.process = process
        self.base_url = base_url

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


ProcessSpawner = Callable[[list[str]], subprocess.Popen]
PortProber = Callable[[str, int, float], bool]


def _default_process_spawner(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _default_port_prober(host: str, port: int, timeout_s: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def start_whisper_server(
    executable: Path,
    model_path: Path,
    host: str,
    port: int,
    threads: int,
    no_fallback: bool,
    startup_timeout_s: float,
    spawner: ProcessSpawner = _default_process_spawner,
    port_prober: PortProber = _default_port_prober,
) -> WhisperServerHandle:
    command = [
        str(executable),
        "-m",
        str(model_path),
        "--host",
        host,
        "--port",
        str(port),
        "-t",
        str(threads),
    ]
    if no_fallback:
        command.append("-nf")
    process = spawner(command)
    deadline = time.monotonic() + startup_timeout_s
    while True:
        if port_prober(host, port, 0.5):
            return WhisperServerHandle(process=process, base_url=f"http://{host}:{port}")
        if process.poll() is not None:
            raise RuntimeError(f"whisper-server exited early with code {process.returncode}")
        if time.monotonic() >= deadline:
            process.terminate()
            raise TimeoutError(f"whisper-server did not become ready on {host}:{port} within {startup_timeout_s}s")
        time.sleep(0.05)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_voice.py -v -k "whisper_server"`
Expected: PASS (6 passed)

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check src/services/voice.py tests/test_services/test_voice.py && python -m ruff format --check src/services/voice.py tests/test_services/test_voice.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/services/voice.py tests/test_services/test_voice.py
git commit -m "feat(voice): add resident whisper-server process lifecycle management"
```

---

### Task 3: `WhisperCppEngine` — HTTP client to the resident server

**Files:**
- Modify: `src/services/voice.py`
- Modify: `tests/test_services/test_voice.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `WhisperServerHandle` from Task 2 (`.base_url`, `.stop()`).
- Produces: `WhisperCppEngine(server: WhisperServerHandle, http_client: object | None = None)` with `.transcribe_file(audio_path: Path) -> Transcript` and `.close() -> None`. Task 4 depends on this exact constructor signature.

- [ ] **Step 1: Write the failing test**

In `tests/test_services/test_voice.py`, remove the old test `test_whisper_cpp_engine_transcribe_file_returns_normalized_text` (it tests the subprocess/JSON-file mechanism this task replaces) and the `json` import if it becomes unused elsewhere in the file (check — it is not used elsewhere, remove `import json` from the top). Add this in its place (same location):

```python
class _FakeHttpResponse:
    def __init__(self, payload: dict, status_ok: bool = True) -> None:
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise RuntimeError("http error")

    def json(self) -> dict:
        return self._payload


class _FakeHttpClient:
    def __init__(self, response: _FakeHttpResponse) -> None:
        self._response = response
        self.calls: list[dict] = []
        self.closed = False

    def post(self, url: str, *, files: dict, data: dict) -> _FakeHttpResponse:
        self.calls.append({"url": url, "files": files, "data": data})
        return self._response

    def close(self) -> None:
        self.closed = True


def test_whisper_cpp_engine_transcribe_file_posts_to_server_and_returns_normalized_text(tmp_path: Path) -> None:
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(_make_wav_bytes())
    fake_client = _FakeHttpClient(_FakeHttpResponse({"text": "  đặt  điều hòa 24 độ  "}))
    server = WhisperServerHandle(process=_FakeProcess(), base_url="http://127.0.0.1:8090")

    engine = WhisperCppEngine(server, fake_client)
    result = engine.transcribe_file(audio_path)

    assert result.text == "đặt điều hòa 24 độ"
    assert result.latency_ms >= 0
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["url"] == "http://127.0.0.1:8090/inference"
    assert call["files"]["file"][0] == "input.wav"
    assert call["data"] == {"response_format": "json", "temperature": "0"}


def test_whisper_cpp_engine_close_closes_http_client_and_stops_server() -> None:
    fake_client = _FakeHttpClient(_FakeHttpResponse({"text": "x"}))
    fake_process = _FakeProcess()
    server = WhisperServerHandle(process=fake_process, base_url="http://127.0.0.1:8090")
    engine = WhisperCppEngine(server, fake_client)

    engine.close()

    assert fake_client.closed
    assert fake_process.terminated
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_voice.py -v -k "transcribe_file_posts or close_closes"`
Expected: FAIL — `TypeError: WhisperCppEngine() takes ... positional arguments` (old constructor is `(executable, model_path, runner=None)`)

- [ ] **Step 3: Write minimal implementation**

In `src/services/voice.py`, replace the entire `WhisperCppEngine` class (the old subprocess/JSON-file version) with:

```python
class WhisperCppEngine:
    """Talks HTTP to a resident whisper-server (see `start_whisper_server`).

    `http_client` must expose `.post(url, *, files, data) -> Response` where
    `Response` exposes `.raise_for_status()` and `.json()` (matches
    `httpx.Client`), plus `.close()`.
    """

    def __init__(self, server: WhisperServerHandle, http_client: object | None = None) -> None:
        self._server = server
        self._client = http_client if http_client is not None else httpx.Client(timeout=30.0)

    def transcribe_file(self, audio_path: Path) -> Transcript:
        audio_bytes = audio_path.read_bytes()
        started_ns = time.perf_counter_ns()
        response = self._client.post(
            f"{self._server.base_url}/inference",
            files={"file": (audio_path.name, audio_bytes, "audio/wav")},
            data={"response_format": "json", "temperature": "0"},
        )
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        response.raise_for_status()
        text = response.json()["text"]
        return Transcript(text=normalize_vietnamese_text(text), latency_ms=latency_ms)

    def close(self) -> None:
        self._client.close()
        self._server.stop()
```

Add `import httpx` to the top imports of `src/services/voice.py` (alphabetically among the other imports, before `from src.config import get_settings`).

Also remove the now-unused `WhisperRunner` type alias and `_default_whisper_runner` function (the old subprocess-CLI mechanism this task fully replaces) — delete both.

In `pyproject.toml`, move `httpx` into the `voice` optional-dependencies group so the resident-server path has its runtime dependency declared where it's actually used:

```toml
voice = [
    "piper-tts>=1.3,<2",
    "httpx>=0.28.0",
]
```

(`httpx` stays in the `dev` group too — it's still used by `tests/conftest.py` for the FastAPI test client — this just adds it to `voice` as well.)

In `requirements.txt`, find the commented-out `# piper-tts>=1.3,<2` line and add a commented-out httpx line matching the same "optional, install via `voice` extra" convention right after it:

```
# piper-tts>=1.3,<2
# httpx>=0.28.0  # already listed above for dev/tests; also required at runtime by the voice adapter's resident whisper-server client
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_voice.py -v`
Expected: PASS (all tests in the file pass — old CLI-based test is gone, new HTTP-based tests pass)

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check src/services/voice.py tests/test_services/test_voice.py && python -m ruff format --check src/services/voice.py tests/test_services/test_voice.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/services/voice.py tests/test_services/test_voice.py pyproject.toml requirements.txt
git commit -m "feat(voice): WhisperCppEngine talks HTTP to resident whisper-server"
```

---

### Task 4: Wire `get_stt_engine()` to the resident server + `stop_stt_engine()` cleanup

**Files:**
- Modify: `src/services/voice.py`
- Modify: `tests/test_services/test_voice.py`

**Interfaces:**
- Consumes: `start_whisper_server` (Task 2), `WhisperCppEngine.__init__` (Task 3).
- Produces: `get_stt_engine() -> WhisperCppEngine` (unchanged public signature, new internals), `stop_stt_engine() -> None`. Task 7 depends on `stop_stt_engine`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_voice.py`:

```python
def test_get_stt_engine_starts_resident_server_and_stop_stt_engine_tears_it_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.config import get_settings
    from src.services import voice as voice_module

    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"fake")

    get_settings.cache_clear()
    voice_module.get_stt_engine.cache_clear()
    monkeypatch.setenv("STT_MODEL_PATH", str(model_path))
    get_settings.cache_clear()

    fake_process = _FakeProcess()
    fake_server = WhisperServerHandle(process=fake_process, base_url="http://127.0.0.1:8090")
    captured_kwargs: dict = {}

    def fake_start_whisper_server(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_server

    monkeypatch.setattr(voice_module, "start_whisper_server", fake_start_whisper_server)

    engine = voice_module.get_stt_engine()

    assert isinstance(engine, WhisperCppEngine)
    assert captured_kwargs["model_path"] == model_path
    assert captured_kwargs["host"] == get_settings().stt_server_host
    assert captured_kwargs["no_fallback"] is True

    voice_module.stop_stt_engine()

    assert fake_process.terminated
    assert voice_module.get_stt_engine.cache_info().currsize == 0

    get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_services/test_voice.py -v -k "starts_resident_server"`
Expected: FAIL — `AttributeError: module 'src.services.voice' has no attribute 'stop_stt_engine'` (and `get_stt_engine` still builds the old CLI-path engine, so `captured_kwargs` never gets populated)

- [ ] **Step 3: Write minimal implementation**

In `src/services/voice.py`, replace the existing `get_stt_engine()` function with:

```python
@lru_cache
def get_stt_engine() -> WhisperCppEngine:
    settings = get_settings()
    if settings.stt_provider != "whisper_cpp":
        raise ValueError(f"unsupported STT_PROVIDER: only whisper_cpp is implemented, got {settings.stt_provider!r}")
    model_path = Path(settings.stt_model_path)
    if not model_path.is_file():
        raise FileNotFoundError(f"STT model not found at {model_path}. Run scripts/setup_voice_models.ps1 first.")
    server = start_whisper_server(
        executable=Path(settings.stt_server_executable_path),
        model_path=model_path,
        host=settings.stt_server_host,
        port=settings.stt_server_port,
        threads=settings.stt_server_threads,
        no_fallback=settings.stt_no_fallback,
        startup_timeout_s=settings.stt_server_startup_timeout_s,
    )
    return WhisperCppEngine(server)


def stop_stt_engine() -> None:
    if get_stt_engine.cache_info().currsize:
        get_stt_engine().close()
    get_stt_engine.cache_clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_services/test_voice.py -v -k "starts_resident_server"`
Expected: PASS

- [ ] **Step 5: Run the full unit suite**

Run: `python -m pytest tests/test_config.py tests/test_services/test_voice.py -v`
Expected: all pass (this confirms Tasks 1-4 didn't regress anything)

- [ ] **Step 6: Run ruff**

Run: `python -m ruff check src/services/voice.py tests/test_services/test_voice.py && python -m ruff format --check src/services/voice.py tests/test_services/test_voice.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/services/voice.py tests/test_services/test_voice.py
git commit -m "feat(voice): wire get_stt_engine to resident server, add stop_stt_engine cleanup"
```

---

### Task 5: Update `scripts/setup_voice_models.ps1` for PhoWhisper-base + whisper-server

**Files:**
- Modify: `scripts/setup_voice_models.ps1`

**Interfaces:**
- Produces: `models/voice/ggml-phowhisper-base.bin` (matches `Settings.stt_model_path` default from Task 1), `models/voice/whisper-server.exe` (matches `Settings.stt_server_executable_path` default from Task 1, when the script's output dir is on `PATH` or the setting is overridden with the full path).

- [ ] **Step 1: Edit the script**

In `scripts/setup_voice_models.ps1`:

1. Change `$phoWhisperRepo = "vinai/PhoWhisper-small"` to `$phoWhisperRepo = "vinai/PhoWhisper-base"`.
2. Change `$phoWhisperHfDir = Join-Path $resolvedOutputDir "phowhisper-small-hf"` to `$phoWhisperHfDir = Join-Path $resolvedOutputDir "phowhisper-base-hf"`.
3. In the `-DryRun` steps array, update step 4 (`hf download $phoWhisperRepo -> $phoWhisperHfDir`), step 6 (`rename ... -> ggml-phowhisper-base.bin`), and add a new step 2b right after the existing cmake build step: `"2b. cmake --build $WhisperCppDir\build (Release) -> whisper-server"`. Also update step 2's target list text to mention `whisper-server`.
4. Replace the cmake build line:

```powershell
cmake --build $buildDir --config Release --target whisper-cli whisper-quantize
```

with:

```powershell
cmake --build $buildDir --config Release --target whisper-cli whisper-quantize whisper-server
```

5. Right after the existing `$whisperCliExe` existence check, add the same check for the server binary:

```powershell
$whisperServerExe = Join-Path $buildDir "bin\Release\whisper-server.exe"
if (-not (Test-Path -LiteralPath $whisperServerExe)) {
    throw "Build did not produce $whisperServerExe. Check the whisper.cpp CMake output above."
}
```

6. Change `$targetGgml = Join-Path $resolvedOutputDir "ggml-phowhisper-small.bin"` to `$targetGgml = Join-Path $resolvedOutputDir "ggml-phowhisper-base.bin"`.
7. Change the sha256 content line from `"$($hash.Hash.ToLowerInvariant())  ggml-phowhisper-small.bin"` to `"$($hash.Hash.ToLowerInvariant())  ggml-phowhisper-base.bin"`.
8. Change `Profile = "phowhisper-small-ggml"` to `Profile = "phowhisper-base-ggml"`.
9. Change the final `Write-Output "STT model ready: $targetGgml"` block to also print the server binary path:

```powershell
Write-Output "STT model ready: $targetGgml"
Write-Output "whisper-cli: $whisperCliExe"
Write-Output "whisper-server: $whisperServerExe"
Write-Output ""
```

(keep the existing TTS instructions block unchanged after this)

- [ ] **Step 2: Verify with -DryRun**

Run: `pwsh -File scripts/setup_voice_models.ps1 -DryRun`
Expected: exit code 0, JSON output shows `PhoWhisperRepo: vinai/PhoWhisper-base`, `PhoWhisperHfDir` ending in `phowhisper-base-hf`, and the `Steps` array mentioning `whisper-server` and `ggml-phowhisper-base.bin`. No side effects (no files created).

- [ ] **Step 3: Commit**

```bash
git add scripts/setup_voice_models.ps1
git commit -m "feat(voice): setup script builds whisper-server and converts PhoWhisper-base"
```

---

### Task 6: Fixed WER fixtures — replace non-deterministic Piper loopback

**Files:**
- Create: `scripts/generate_voice_wer_fixtures.py`
- Create: `tests/fixtures/voice/synthetic_commands/manifest.json` (and the WAV files it lists — generated, not hand-written)

**Interfaces:**
- Consumes: `synthesize()`, `get_tts_engine()` from the existing `src/services/voice.py` (unchanged by this plan).
- Produces: `tests/fixtures/voice/synthetic_commands/manifest.json` — a JSON array of `{"file": str, "text": str}` — and the WAV files it references, each already resampled to 16kHz mono. Task 7 reads this manifest.

- [ ] **Step 1: Write the generation script**

Create `scripts/generate_voice_wer_fixtures.py`:

```python
"""One-off script: generates fixed 16kHz mono WAV fixtures for the AC2 WER
loopback test.

`PiperEngine.synthesize()` is not deterministic across calls (confirmed
2026-08-07: same text, two calls, two different audio byte counts), which
made the live-loopback WER test unreproducible. This script freezes a set
of Piper outputs once so the test measures WER against a stable input.

Run once locally (requires TTS_MODEL_PATH to point at a real Piper voice —
see scripts/setup_voice_models.ps1) whenever the Piper voice changes:

    python scripts/generate_voice_wer_fixtures.py

Commit the resulting files under tests/fixtures/voice/synthetic_commands/.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

from src.services.voice import get_tts_engine, synthesize

SENTENCES = [
    "Bật điều hòa",
    "Đặt điều hòa hai mươi bốn độ",
    "Mở cửa sổ bên phụ một nửa",
    "Tăng nhiệt độ lên hai mươi sáu độ",
    "Bật sưởi ghế lái mức hai",
]

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "voice" / "synthetic_commands"
TARGET_SAMPLE_RATE = 16000


def _resample_to_16k_mono(pcm_bytes: bytes, source_rate: int) -> bytes:
    if source_rate == TARGET_SAMPLE_RATE:
        return pcm_bytes
    audio = np.frombuffer(pcm_bytes, dtype=np.int16)
    duration_s = len(audio) / source_rate
    target_len = int(round(duration_s * TARGET_SAMPLE_RATE))
    source_index = np.linspace(0, len(audio) - 1, num=len(audio))
    target_index = np.linspace(0, len(audio) - 1, num=target_len)
    return np.interp(target_index, source_index, audio).astype(np.int16).tobytes()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_rate = get_tts_engine().sample_rate
    manifest = []
    for index, sentence in enumerate(SENTENCES):
        pcm_bytes = _resample_to_16k_mono(b"".join(synthesize(sentence)), source_rate)
        filename = f"command_{index:02d}.wav"
        output_path = OUTPUT_DIR / filename
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(TARGET_SAMPLE_RATE)
            wav_file.writeframes(pcm_bytes)
        manifest.append({"file": filename, "text": sentence})
        print(f"wrote {output_path} ({len(pcm_bytes)} bytes) for: {sentence!r}")

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script to generate real fixtures**

Requires local voice model assets (`Settings.tts_model_path` must point at a real Piper voice file — see `scripts/setup_voice_models.ps1`). Run:

```bash
python scripts/generate_voice_wer_fixtures.py
```

Expected: prints 5 "wrote ..." lines plus a final "wrote .../manifest.json" line, and `tests/fixtures/voice/synthetic_commands/` now contains `command_00.wav` through `command_04.wav` plus `manifest.json`.

If local voice model assets are not available in this environment, skip this step and leave a note in the task report — do not hand-author placeholder WAV files.

- [ ] **Step 3: Run ruff on the new script**

Run: `python -m ruff check scripts/generate_voice_wer_fixtures.py && python -m ruff format --check scripts/generate_voice_wer_fixtures.py`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add scripts/generate_voice_wer_fixtures.py tests/fixtures/voice/synthetic_commands/
git commit -m "feat(voice): generate fixed WAV fixtures for reproducible AC2 WER test"
```

---

### Task 7: Update integration tests — AC1 budget, AC2 fixtures, server teardown

**Files:**
- Modify: `tests/test_services/test_voice_integration.py`
- Modify: `docs/adr/ADR-007-voice-adapter-engine-binding.md`

**Interfaces:**
- Consumes: `stop_stt_engine` (Task 4), `tests/fixtures/voice/synthetic_commands/manifest.json` (Task 6).

- [ ] **Step 1: Update the integration test file**

Replace the full contents of `tests/test_services/test_voice_integration.py` with:

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.config import get_settings
from src.services.voice import get_stt_engine, stop_stt_engine, transcribe, word_error_rate

pytestmark = pytest.mark.integration

_WARM_SAMPLE_PATH = Path(__file__).parent.parent / "fixtures" / "voice" / "warm_sample.wav"
_SYNTHETIC_COMMANDS_DIR = Path(__file__).parent.parent / "fixtures" / "voice" / "synthetic_commands"
_SYNTHETIC_COMMANDS_MANIFEST = _SYNTHETIC_COMMANDS_DIR / "manifest.json"


def _assets_available() -> bool:
    settings = get_settings()
    return Path(settings.stt_model_path).is_file() and Path(settings.tts_model_path).is_file()


def _warm_sample_available() -> bool:
    return _assets_available() and _WARM_SAMPLE_PATH.is_file()


def _synthetic_commands_available() -> bool:
    return _assets_available() and _SYNTHETIC_COMMANDS_MANIFEST.is_file()


@pytest.fixture(scope="session", autouse=True)
def _stop_stt_engine_after_session():
    yield
    stop_stt_engine()


@pytest.mark.skipif(not _warm_sample_available(), reason="voice model assets or warm_sample.wav fixture not available")
def test_transcribe_warm_latency_is_under_budget() -> None:
    # Reference sentence must be pre-recorded at tests/fixtures/voice/warm_sample.wav
    # (16kHz mono WAV, "đặt điều hòa hai mươi bốn độ").
    audio_bytes = _WARM_SAMPLE_PATH.read_bytes()

    get_stt_engine()  # spawns + health-checks the resident whisper-server
    transcribe(audio_bytes)  # first call, discarded (excludes server bootstrap variance)

    started = time.perf_counter()
    result = transcribe(audio_bytes)
    wall_ms = (time.perf_counter() - started) * 1000

    # Budget revised 2026-08-07 from 400ms to 1.5s: real measurement showed
    # 400ms is not achievable on CPU-only target hardware even with the
    # fastest viable model (PhoWhisper-base) + resident server + max threads
    # (best observed: ~900ms-1.6s). See ADR-007 "Benchmark thật 2026-08-07".
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
    # through whisper.cpp), not a real-speaker accuracy benchmark — see
    # ADR-007 and the design spec's WER caveat.
    assert average_wer < 0.20, f"synthetic loopback WER {average_wer:.2%} exceeds 20% budget"
```

- [ ] **Step 2: Update ADR-007's Status line**

In `docs/adr/ADR-007-voice-adapter-engine-binding.md`, change the first line of the `Status` field from:

```
- Status: Accepted (engine binding) — latency/WER là **Not Met** trên phần cứng dev hiện tại, đã đo thật (xem "Benchmark thật 2026-08-07" bên dưới)
```

to:

```
- Status: Accepted (engine binding + revised AC1 budget) — AC1 latency-warm budget revised 400ms → 1.5s và áp dụng trong `tests/test_services/test_voice_integration.py` (xem "Benchmark thật 2026-08-07" bên dưới); AC2 loopback WER giờ dùng fixture cố định (`scripts/generate_voice_wer_fixtures.py`) thay vì `synthesize()` sống.
```

- [ ] **Step 3: Run the integration tests**

If real voice model assets (and Task 6's generated fixtures) are present locally, run:

```bash
python -m pytest tests/test_services/test_voice_integration.py -v -m integration
```

Expected: both tests run (not skipped) and report actual pass/fail against the revised 1.5s / 20% budgets — record the real numbers in the task report, do not assume success.

If assets are not present, run the same command and confirm both tests report `SKIPPED` (not error) — this validates the skip-gates still work correctly with the renamed fixture paths.

- [ ] **Step 4: Run the full test suite (unit + config)**

Run: `python -m pytest tests/test_config.py tests/test_services/ -v`
Expected: all non-integration tests PASS; integration tests PASS or SKIPPED per Step 3.

- [ ] **Step 5: Run ruff**

Run: `python -m ruff check src/ tests/ scripts/ && python -m ruff format --check src/ tests/ scripts/`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add tests/test_services/test_voice_integration.py docs/adr/ADR-007-voice-adapter-engine-binding.md
git commit -m "test(voice): AC1 budget 400ms->1.5s, AC2 uses fixed fixtures, teardown resident server"
```

---

### Task 8: Update WORKLOG.md

**Files:**
- Modify: `WORKLOG.md`

- [ ] **Step 1: Add a dated entry**

Add a new row (or new dated section if today's date differs from the existing 2026-08-07 section) to `WORKLOG.md` crediting "Nguyễn Tuấn Thành", summarizing: switched STT from PhoWhisper-small/subprocess-CLI to PhoWhisper-base/resident-whisper-server, revised AC1 budget 400ms→1.5s based on real measurement, fixed AC2's non-deterministic loopback methodology with generated fixtures. Reference the actual commit hashes from Tasks 1-7 and the real pass/fail numbers recorded in Task 7 Step 3.

- [ ] **Step 2: Commit**

```bash
git add WORKLOG.md
git commit -m "docs(worklog): cập nhật WORKLOG.md — voice benchmark optimization"
```

---

## Out of scope (unchanged from the design spec)

- Changing hardware (GPU/NPU).
- HTTP endpoints `/voice/transcribe` / `/voice/synthesize`.
- WER on a real-speaker corpus.
- Formally updating AC1 in the task tracker/PRD — this plan only updates the codebase's own test budget and ADR; the product-level AC change still needs separate stakeholder sign-off.
- SLM (Qwen/Phi via llama.cpp) optimization.
- Entropy/logprob/no-speech-threshold tuning and VAD — only `-nf` is applied; revisit if hallucination is still observed after Task 7's real measurement.

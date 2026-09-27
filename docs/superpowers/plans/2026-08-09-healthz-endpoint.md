# GET /healthz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GET /healthz`, replacing the current ad-hoc `GET /health`, so it reports real `ready`/`degraded`/`down` status for all eight required P0 dependencies (`backend`, `llm`, `mqtt`, `vehicle_simulator`, `stt`, `tts`, `rag_index`, `sqlite`) and fails closed with `503` unless every one of them is `ready`.

**Architecture:** A new `src/services/health.py` module holds one async probe function per component, each wrapping existing runtime objects (`MqttRuntime`, `VehicleStateCache`, the RAG retriever/embedder singletons, the STT/TTS engine singletons) or new minimal code (`src/db.py` for the previously-unused `database_url`, an SLM `/health`+`/props` check). A new `src/api/health.py` router runs all eight probes concurrently, bounds each with a timeout, and assembles the exact response shape from `docs/api_spec.md#health`.

**Tech Stack:** FastAPI, httpx (already a dependency), stdlib `sqlite3`, stdlib `asyncio`, pytest + pytest-asyncio (`asyncio_mode = "auto"`, see `pyproject.toml`).

## Global Constraints

- Component names are exactly `backend`, `llm`, `mqtt`, `vehicle_simulator`, `stt`, `tts`, `rag_index`, `sqlite` (`docs/devops.md` §Readiness contract).
- Three states only: `ready`, `degraded`, `down`. `200` only when all eight are `ready`; any other combination is `503` with the common error envelope (`docs/api_spec.md#health`).
- Fail-closed: any probe exception, timeout, or unconfigured/disabled dependency (e.g. `slm_enabled=False`) maps to `down`, never propagates as an unhandled error.
- `llm` probe targets the local SLM endpoint only (`settings.slm_endpoint`), never the cloud OpenAI path — `llm=down` whenever `slm_enabled=False`.
- STT/TTS probes run **real** inference (bounded smoke test) but cache their result for `health_voice_probe_ttl_s` (default 10s) to avoid repeated model inference under frequent polling.
- No new third-party dependency — `sqlite` probe uses stdlib `sqlite3`; `llm` probe testing uses `httpx.MockTransport` (built into the already-installed `httpx`).
- Response envelope matches the existing pattern in `src/api/routes.py::vehicle_state`: `{"data"|"error", "meta": {"request_id"}, "trace_id", "schema_version"}`, `schema_version` from `src.models.vehicle.SCHEMA_VERSION`.
- `GET /health` is removed outright (not kept as an alias) — see `docs/superpowers/specs/2026-08-09-healthz-endpoint-design.md` §Out of scope.

---

### Task 1: Config additions

**Files:**
- Modify: `src/config.py` (add two fields after the `tts_model_path` line, ~line 59)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.health_probe_timeout_s: float` (default `5.0`), `Settings.health_voice_probe_ttl_s: float` (default `10.0`) — consumed by Tasks 3–8.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
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

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'health_probe_timeout_s'`

- [ ] **Step 3: Write minimal implementation**

In `src/config.py`, after the `tts_model_path` line (currently line 59, right before the `# MQTT` comment block):

```python
    # Health probe — GET /healthz. Timeout bounds every probe individually so
    # one hung dependency can't hang the whole endpoint; TTL caches the STT/TTS
    # smoke-test result so frequent polling doesn't re-run real inference every
    # call. See docs/superpowers/specs/2026-08-09-healthz-endpoint-design.md.
    health_probe_timeout_s: float = Field(default=5.0, gt=0.0)
    health_voice_probe_ttl_s: float = Field(default=10.0, gt=0.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(config): add healthz probe timeout and voice-probe TTL settings"
```

---

### Task 2: `src/db.py` — minimal SQLite connection for `database_url`

**Files:**
- Create: `src/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `Settings.database_url: str` (from `src/config.py`, existing field).
- Produces: `resolve_db_path(database_url: str) -> Path`, `health_check(settings: Settings) -> None` (raises `sqlite3.Error` or `ValueError` on failure, returns `None` on success) — consumed by Task 4's `probe_sqlite`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
import sqlite3
from pathlib import Path

import pytest

from src.config import Settings
from src.db import health_check, resolve_db_path


def test_resolve_db_path_strips_sqlite_prefix() -> None:
    assert resolve_db_path("sqlite:///./data/app.db") == Path("./data/app.db")


def test_resolve_db_path_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        resolve_db_path("postgresql://localhost/app")


def test_health_check_creates_db_and_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "sub" / "app.db"
    settings = Settings(_env_file=None, database_url=f"sqlite:///{db_path.as_posix()}")

    health_check(settings)

    assert db_path.is_file()
    connection = sqlite3.connect(db_path)
    try:
        # Xoá thăm dò xong nên bảng phải rỗng sau khi health_check kết thúc.
        row = connection.execute("SELECT COUNT(*) FROM _healthz_probe").fetchone()
        assert row == (0,)
    finally:
        connection.close()


def test_health_check_raises_when_directory_not_creatable(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    settings = Settings(_env_file=None, database_url=f"sqlite:///{db_path.as_posix()}")

    def _boom(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sqlite3, "connect", _boom)

    with pytest.raises(sqlite3.OperationalError):
        health_check(settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db'`

- [ ] **Step 3: Write minimal implementation**

Create `src/db.py`:

```python
"""Kết nối SQLite tối giản cho `database_url` — dùng bởi probe sqlite của /healthz.

`database_url` đã khai báo ở `src/config.py` từ trước nhưng chưa module nào mở
nó; đây là điểm mở đầu tiên, chỉ đủ cho một transaction đọc/ghi thăm dò sức khỏe.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.config import Settings

_SQLITE_PREFIX = "sqlite:///"


def resolve_db_path(database_url: str) -> Path:
    """Chuyển `sqlite:///relative/path` thành Path. Không hỗ trợ scheme khác."""
    if not database_url.startswith(_SQLITE_PREFIX):
        raise ValueError(f"unsupported DATABASE_URL scheme: {database_url!r}")
    return Path(database_url[len(_SQLITE_PREFIX) :])


def health_check(settings: Settings) -> None:
    """Mở kết nối, ghi/đọc/xoá một dòng thăm dò, commit.

    Raise `sqlite3.Error` (hoặc lỗi từ `resolve_db_path`) nếu bất kỳ bước nào lỗi
    — caller (`src/services/health.py::probe_sqlite`) diễn giải raise thành `down`.
    """
    db_path = resolve_db_path(settings.database_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=settings.health_probe_timeout_s)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS _healthz_probe (id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO _healthz_probe (checked_at) VALUES (datetime('now'))")
        row = connection.execute("SELECT COUNT(*) FROM _healthz_probe").fetchone()
        if row is None or row[0] < 1:
            raise sqlite3.OperationalError("healthz probe row missing after insert")
        connection.execute("DELETE FROM _healthz_probe")
        connection.commit()
    finally:
        connection.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db.py tests/test_db.py
git commit -m "feat(db): add minimal sqlite connection and health_check for database_url"
```

---

### Task 3: `src/services/health.py` — `ProbeResult`, timeout helper, and the three free probes (`backend`, `mqtt`, `vehicle_simulator`)

**Files:**
- Create: `src/services/health.py`
- Test: `tests/test_services/test_health.py`

**Interfaces:**
- Consumes: `MqttRuntime` (from `src/services/mqtt_runtime.py`: `.connected: bool`, `.cache.simulator_ready() -> bool`).
- Produces: `ProbeResult` (dataclass: `status: Literal["ready","degraded","down"]`, `latency_ms: float`, `detail: str | None = None`), `probe_backend() -> ProbeResult`, `probe_mqtt(runtime: MqttRuntime | None) -> ProbeResult`, `probe_vehicle_simulator(runtime: MqttRuntime | None) -> ProbeResult`, `run_with_timeout(probe: Awaitable[ProbeResult], timeout_s: float, timeout_detail: str) -> ProbeResult` — all consumed by Task 8's router. Later tasks (4–7) append more probes to this same file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/test_health.py`:

```python
import asyncio

import pytest

from src.services.health import (
    ProbeResult,
    probe_backend,
    probe_mqtt,
    probe_vehicle_simulator,
    run_with_timeout,
)


async def test_probe_backend_is_always_ready() -> None:
    result = await probe_backend()

    assert result.status == "ready"
    assert result.latency_ms >= 0


class _FakeCache:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def simulator_ready(self) -> bool:
        return self._ready


class _FakeRuntime:
    def __init__(self, *, connected: bool, simulator_ready: bool) -> None:
        self.connected = connected
        self.cache = _FakeCache(simulator_ready)


async def test_probe_mqtt_ready_when_connected() -> None:
    runtime = _FakeRuntime(connected=True, simulator_ready=True)
    result = await probe_mqtt(runtime)
    assert result.status == "ready"


async def test_probe_mqtt_down_when_runtime_missing() -> None:
    result = await probe_mqtt(None)
    assert result.status == "down"


async def test_probe_mqtt_down_when_not_connected() -> None:
    runtime = _FakeRuntime(connected=False, simulator_ready=True)
    result = await probe_mqtt(runtime)
    assert result.status == "down"


async def test_probe_vehicle_simulator_ready_when_heartbeat_fresh() -> None:
    runtime = _FakeRuntime(connected=True, simulator_ready=True)
    result = await probe_vehicle_simulator(runtime)
    assert result.status == "ready"


async def test_probe_vehicle_simulator_down_when_heartbeat_stale() -> None:
    runtime = _FakeRuntime(connected=True, simulator_ready=False)
    result = await probe_vehicle_simulator(runtime)
    assert result.status == "down"


async def test_probe_vehicle_simulator_down_when_runtime_missing() -> None:
    result = await probe_vehicle_simulator(None)
    assert result.status == "down"


async def test_run_with_timeout_returns_probe_result_when_fast_enough() -> None:
    async def _fast() -> ProbeResult:
        return ProbeResult(status="ready", latency_ms=1.0)

    result = await run_with_timeout(_fast(), timeout_s=1.0, timeout_detail="x_timeout")
    assert result.status == "ready"


async def test_run_with_timeout_returns_down_on_timeout() -> None:
    async def _slow() -> ProbeResult:
        await asyncio.sleep(10)
        return ProbeResult(status="ready", latency_ms=1.0)

    result = await run_with_timeout(_slow(), timeout_s=0.05, timeout_detail="x_timeout")
    assert result.status == "down"
    assert result.detail == "x_timeout"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.health'`

- [ ] **Step 3: Write minimal implementation**

Create `src/services/health.py`:

```python
"""Probe cho 8 dependency bắt buộc của GET /healthz.

Mỗi probe tự bắt lỗi của chính nó và không bao giờ raise ra ngoài — bất kỳ
exception/timeout/dependency chưa cấu hình nào đều ánh xạ thành `down`
(fail-closed, theo tiền lệ ADR-005: "not-selected" không tự coi là ready).
`docs/devops.md` §Readiness contract và `docs/api_spec.md#health` là nguồn
sự thật cho tên 8 component và ngữ nghĩa 3 trạng thái.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.services.mqtt_runtime import MqttRuntime

Status = Literal["ready", "degraded", "down"]


@dataclass(frozen=True)
class ProbeResult:
    status: Status
    latency_ms: float
    detail: str | None = None


def _elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000


async def run_with_timeout(probe: Awaitable[ProbeResult], timeout_s: float, timeout_detail: str) -> ProbeResult:
    """Bọc một probe với giới hạn thời gian — một dependency treo không được
    treo cả endpoint. Timeout luôn ánh xạ thành `down`."""
    import asyncio

    started = time.perf_counter_ns()
    try:
        return await asyncio.wait_for(probe, timeout=timeout_s)
    except TimeoutError:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=timeout_detail)


async def probe_backend() -> ProbeResult:
    """Backend tự kiểm — event loop còn phản hồi là ready."""
    import asyncio

    started = time.perf_counter_ns()
    await asyncio.sleep(0)
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))


async def probe_mqtt(runtime: MqttRuntime | None) -> ProbeResult:
    """`mqtt=down` khi chưa nối broker hoặc lỗi credential/ACL lúc CONNECT."""
    started = time.perf_counter_ns()
    if runtime is not None and runtime.connected:
        return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))
    return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail="mqtt_not_connected")


async def probe_vehicle_simulator(runtime: MqttRuntime | None) -> ProbeResult:
    """`vehicle_simulator=down` khi thiếu heartbeat xác thực còn tươi."""
    started = time.perf_counter_ns()
    if runtime is not None and runtime.cache.simulator_ready():
        return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))
    return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail="vehicle_simulator_heartbeat_stale")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/health.py tests/test_services/test_health.py
git commit -m "feat(health): add ProbeResult, run_with_timeout, and backend/mqtt/vehicle_simulator probes"
```

---

### Task 4: `probe_sqlite`

**Files:**
- Modify: `src/services/health.py` (append)
- Test: `tests/test_services/test_health.py` (append)

**Interfaces:**
- Consumes: `src.db.health_check(settings: Settings) -> None` (Task 2), `Settings` (Task 1).
- Produces: `probe_sqlite(settings: Settings) -> ProbeResult` — consumed by Task 8's router.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_health.py`:

```python
import sqlite3
from pathlib import Path

from src.config import Settings
from src.services.health import probe_sqlite


async def test_probe_sqlite_ready_on_successful_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    settings = Settings(_env_file=None, database_url=f"sqlite:///{db_path.as_posix()}")

    result = await probe_sqlite(settings)

    assert result.status == "ready"
    assert db_path.is_file()


async def test_probe_sqlite_down_on_connection_error(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    settings = Settings(_env_file=None, database_url=f"sqlite:///{db_path.as_posix()}")

    def _boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sqlite3, "connect", _boom)

    result = await probe_sqlite(settings)

    assert result.status == "down"
    assert "sqlite_error" in (result.detail or "")


async def test_probe_sqlite_down_on_unsupported_url() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://localhost/app")

    result = await probe_sqlite(settings)

    assert result.status == "down"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -k sqlite -v`
Expected: FAIL — `ImportError: cannot import name 'probe_sqlite'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/services/health.py` (add `import sqlite3` and `from src.config import Settings` near the top imports, keep the `TYPE_CHECKING` block as-is):

```python
async def probe_sqlite(settings: Settings) -> ProbeResult:
    """`sqlite=down` khi mở/đọc/ghi database_url thất bại."""
    import asyncio

    from src import db

    started = time.perf_counter_ns()
    try:
        await asyncio.to_thread(db.health_check, settings)
    except (sqlite3.Error, ValueError) as exc:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"sqlite_error:{exc}")
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))
```

Also change the top of `src/services/health.py` from:

```python
from __future__ import annotations

import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.services.mqtt_runtime import MqttRuntime
```

to:

```python
from __future__ import annotations

import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from src.config import Settings

if TYPE_CHECKING:
    from src.services.mqtt_runtime import MqttRuntime
```

(Task 6 later extends this same import line to add `Callable` — no action needed now beyond this diff.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -v`
Expected: PASS (all tests in the file, including Task 3's)

- [ ] **Step 5: Commit**

```bash
git add src/services/health.py tests/test_services/test_health.py
git commit -m "feat(health): add probe_sqlite backed by src/db.py"
```

---

### Task 5: `probe_llm` (local SLM only)

**Files:**
- Modify: `src/services/health.py` (append)
- Test: `tests/test_services/test_health.py` (append)

**Interfaces:**
- Consumes: `Settings.slm_enabled`, `Settings.slm_endpoint`, `Settings.slm_model_id`, `Settings.slm_timeout_s` (all pre-existing in `src/config.py`).
- Produces: `probe_llm(settings: Settings, client: httpx.AsyncClient | None = None) -> ProbeResult` — consumed by Task 8's router. The optional `client` param exists purely for test injection via `httpx.MockTransport`; the router never passes it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_health.py`:

```python
import httpx

from src.services.health import probe_llm


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_probe_llm_down_when_slm_disabled() -> None:
    settings = Settings(_env_file=None, slm_enabled=False)

    result = await probe_llm(settings)

    assert result.status == "down"
    assert result.detail == "slm_disabled"


async def test_probe_llm_ready_when_health_and_props_match() -> None:
    settings = Settings(_env_file=None, slm_enabled=True, slm_model_id="qwen2.5-3b-instruct-q4_k_m")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/props":
            return httpx.Response(200, json={"model": "qwen2.5-3b-instruct-q4_k_m"})
        raise AssertionError(f"unexpected path {request.url.path}")

    async with _mock_client(handler) as client:
        result = await probe_llm(settings, client=client)

    assert result.status == "ready"


async def test_probe_llm_degraded_when_props_model_mismatches() -> None:
    settings = Settings(_env_file=None, slm_enabled=True, slm_model_id="qwen2.5-3b-instruct-q4_k_m")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"model": "some-other-model"})

    async with _mock_client(handler) as client:
        result = await probe_llm(settings, client=client)

    assert result.status == "degraded"
    assert result.detail == "slm_model_mismatch"


async def test_probe_llm_ready_when_props_endpoint_missing() -> None:
    """Bản llama-server không có /props: /health qua là đủ ready, không hạ degraded."""
    settings = Settings(_env_file=None, slm_enabled=True, slm_model_id="qwen2.5-3b-instruct-q4_k_m")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    async with _mock_client(handler) as client:
        result = await probe_llm(settings, client=client)

    assert result.status == "ready"


async def test_probe_llm_down_when_health_endpoint_unreachable() -> None:
    settings = Settings(_env_file=None, slm_enabled=True)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _mock_client(handler) as client:
        result = await probe_llm(settings, client=client)

    assert result.status == "down"
    assert "slm_unreachable" in (result.detail or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -k llm -v`
Expected: FAIL — `ImportError: cannot import name 'probe_llm'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/services/health.py`:

```python
async def probe_llm(settings: Settings, client: "httpx.AsyncClient | None" = None) -> ProbeResult:
    """`llm` chỉ trỏ tới SLM cục bộ (`slm_endpoint`) — không bao giờ gọi cloud.

    `llm=down` ngay khi `slm_enabled=False`, khớp tiền lệ ADR-005
    ("not-selected" không tự coi là ready). `/props` dùng để xác nhận đúng
    model đang chạy; server không có `/props` thì `/health` qua là đủ ready.
    """
    import httpx

    started = time.perf_counter_ns()
    if not settings.slm_enabled:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail="slm_disabled")

    endpoint = settings.slm_endpoint.rstrip("/")
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=settings.slm_timeout_s)
    try:
        try:
            health_response = await http_client.get(f"{endpoint}/health")
            health_response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"slm_unreachable:{exc}")

        identity_confirmed = True
        try:
            props_response = await http_client.get(f"{endpoint}/props")
            props_response.raise_for_status()
            identity_confirmed = settings.slm_model_id in props_response.text
        except httpx.HTTPError:
            pass  # /props không có trên bản server này — /health qua là đủ

        if not identity_confirmed:
            return ProbeResult(status="degraded", latency_ms=_elapsed_ms(started), detail="slm_model_mismatch")
        return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))
    finally:
        if owns_client:
            await http_client.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/health.py tests/test_services/test_health.py
git commit -m "feat(health): add probe_llm targeting the local SLM endpoint only"
```

---

### Task 6: `probe_stt` / `probe_tts` with TTL cache

**Files:**
- Modify: `src/services/health.py` (append)
- Test: `tests/test_services/test_health.py` (append)

**Interfaces:**
- Consumes: `src.services.voice.transcribe_raw(audio_bytes: bytes) -> Transcript`, `src.services.voice.synthesize(text: str) -> Iterator[bytes]` (both pre-existing).
- Produces: `probe_stt(settings: Settings) -> ProbeResult`, `probe_tts(settings: Settings) -> ProbeResult`, `clear_probe_cache() -> None` (test-only helper, mirrors the existing `get_stt_engine.cache_clear()` convention in `tests/test_services/test_voice.py`) — consumed by Task 8's router and by this task's own tests.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_health.py`:

```python
from src.services.health import clear_probe_cache, probe_stt, probe_tts


async def test_probe_stt_ready_when_engine_transcribes(monkeypatch) -> None:
    from src.services import voice as voice_module

    monkeypatch.setattr(voice_module, "transcribe_raw", lambda audio_bytes: voice_module.Transcript(text="ok", latency_ms=1.0))
    clear_probe_cache()
    settings = Settings(_env_file=None)

    result = await probe_stt(settings)

    assert result.status == "ready"
    clear_probe_cache()


async def test_probe_stt_down_when_engine_unavailable(monkeypatch) -> None:
    from src.services import voice as voice_module

    def _boom(audio_bytes: bytes):
        raise FileNotFoundError("STT model not found")

    monkeypatch.setattr(voice_module, "transcribe_raw", _boom)
    clear_probe_cache()
    settings = Settings(_env_file=None)

    result = await probe_stt(settings)

    assert result.status == "down"
    assert "stt_unavailable" in (result.detail or "")
    clear_probe_cache()


async def test_probe_stt_caches_result_within_ttl(monkeypatch) -> None:
    from src.services import voice as voice_module

    calls = []

    def _record(audio_bytes: bytes):
        calls.append(audio_bytes)
        return voice_module.Transcript(text="ok", latency_ms=1.0)

    monkeypatch.setattr(voice_module, "transcribe_raw", _record)
    clear_probe_cache()
    settings = Settings(_env_file=None, health_voice_probe_ttl_s=60.0)

    await probe_stt(settings)
    await probe_stt(settings)

    assert len(calls) == 1  # gọi lần hai trong TTL không chạy lại inference
    clear_probe_cache()


async def test_probe_tts_ready_when_engine_synthesizes(monkeypatch) -> None:
    from src.services import voice as voice_module

    monkeypatch.setattr(voice_module, "synthesize", lambda text: iter([b"\x00\x00"]))
    clear_probe_cache()
    settings = Settings(_env_file=None)

    result = await probe_tts(settings)

    assert result.status == "ready"
    clear_probe_cache()


async def test_probe_tts_down_when_engine_unavailable(monkeypatch) -> None:
    from src.services import voice as voice_module

    def _boom(text: str):
        raise FileNotFoundError("TTS model not found")
        yield  # pragma: no cover - makes this a generator function

    monkeypatch.setattr(voice_module, "synthesize", _boom)
    clear_probe_cache()
    settings = Settings(_env_file=None)

    result = await probe_tts(settings)

    assert result.status == "down"
    assert "tts_unavailable" in (result.detail or "")
    clear_probe_cache()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -k "stt or tts" -v`
Expected: FAIL — `ImportError: cannot import name 'probe_stt'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/services/health.py`:

```python
_PROBE_CACHE: dict[str, tuple[float, ProbeResult]] = {}


def clear_probe_cache() -> None:
    """Test helper: xoá cache TTL của probe_stt/probe_tts giữa các test."""
    _PROBE_CACHE.clear()


async def _cached(key: str, ttl_s: float, live_probe: "Callable[[], Awaitable[ProbeResult]]") -> ProbeResult:
    """`live_probe` phải là callable, không phải coroutine đã tạo sẵn — nếu
    cache hit thì nó không bao giờ được gọi, và một coroutine tạo sẵn nhưng
    chưa await sẽ bị Python cảnh báo rò rỉ (`coroutine was never awaited`)."""
    import time as _time

    now = _time.monotonic()
    cached = _PROBE_CACHE.get(key)
    if cached is not None and now - cached[0] < ttl_s:
        return cached[1]
    result = await live_probe()
    _PROBE_CACHE[key] = (now, result)
    return result


async def probe_stt(settings: Settings) -> ProbeResult:
    """Chạy transcribe thật trên một mẫu WAV im lặng ngắn — kết quả cache theo TTL."""
    return await _cached("stt", settings.health_voice_probe_ttl_s, _probe_stt_live)


async def _probe_stt_live() -> ProbeResult:
    import asyncio
    import io
    import wave

    from src.services import voice

    def _silence_wav(duration_s: float = 0.5, frame_rate: int = 16000) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(frame_rate)
            wav_file.writeframes(b"\x00\x00" * int(duration_s * frame_rate))
        return buffer.getvalue()

    started = time.perf_counter_ns()
    try:
        await asyncio.to_thread(voice.transcribe_raw, _silence_wav())
    except (OSError, ValueError) as exc:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"stt_unavailable:{exc}")
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))


async def probe_tts(settings: Settings) -> ProbeResult:
    """Chạy synthesize thật trên một câu ngắn cố định — kết quả cache theo TTL."""
    return await _cached("tts", settings.health_voice_probe_ttl_s, _probe_tts_live)


async def _probe_tts_live() -> ProbeResult:
    import asyncio

    from src.services import voice

    started = time.perf_counter_ns()
    try:
        await asyncio.to_thread(lambda: list(voice.synthesize("kiểm tra hệ thống")))
    except (OSError, ValueError) as exc:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"tts_unavailable:{exc}")
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/health.py tests/test_services/test_health.py
git commit -m "feat(health): add probe_stt/probe_tts with short TTL cache over real inference"
```

---

### Task 7: `probe_rag_index`

**Files:**
- Modify: `src/services/health.py` (append)
- Test: `tests/test_services/test_health.py` (append)

**Interfaces:**
- Consumes: `src.agents.nodes.rag_node.index_is_built(index_dir) -> bool`, `src.agents.nodes.rag_node._default_retriever() -> Retriever`, `src.agents.nodes.rag_node._default_embedder() -> Embedder` (reused so the health probe queries the exact same cached retriever/embedder instances the live RAG path uses — no duplicate model load), `src.rag.index.VectorIndex.checksum(directory: Path) -> str` (all pre-existing).
- Produces: `probe_rag_index(settings: Settings) -> ProbeResult` — consumed by Task 8's router.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_health.py`:

```python
import json

from src.services.health import probe_rag_index


async def test_probe_rag_index_down_when_not_built(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, rag_index_dir=str(tmp_path / "missing"))

    result = await probe_rag_index(settings)

    assert result.status == "down"
    assert result.detail == "rag_index_not_built"


async def test_probe_rag_index_down_when_checksum_mismatches(tmp_path: Path) -> None:
    from src.rag.embed import StubEmbedder
    from src.rag.index import VectorIndex
    from src.rag.models import Chunk

    index_dir = tmp_path / "index"
    chunk = Chunk(chunk_id="c1", document_id="d1", section="s", heading="h", text="nội dung thử")
    VectorIndex.build([chunk], StubEmbedder()).save(index_dir)
    (index_dir / "manifest.json").write_text(json.dumps({"index_checksum": "sha256:wrong"}), encoding="utf-8")

    settings = Settings(_env_file=None, rag_index_dir=str(index_dir))

    result = await probe_rag_index(settings)

    assert result.status == "down"
    assert result.detail == "rag_checksum_mismatch"


async def test_probe_rag_index_ready_when_checksum_matches_and_query_succeeds(monkeypatch, tmp_path: Path) -> None:
    from src.rag.embed import StubEmbedder
    from src.rag.index import VectorIndex
    from src.rag.models import Chunk
    from src.rag.retrieve import Retriever

    index_dir = tmp_path / "index"
    chunk = Chunk(chunk_id="c1", document_id="d1", section="s", heading="h", text="nội dung thử")
    checksum = VectorIndex.build([chunk], StubEmbedder()).save(index_dir)
    (index_dir / "manifest.json").write_text(json.dumps({"index_checksum": checksum}), encoding="utf-8")

    from src.agents.nodes import rag_node as rag_node_module

    stub_retriever = Retriever(VectorIndex.build([chunk], StubEmbedder()), [chunk])
    rag_node_module._default_retriever.cache_clear()
    rag_node_module._default_embedder.cache_clear()
    monkeypatch.setattr(rag_node_module, "_default_retriever", lambda: stub_retriever)
    monkeypatch.setattr(rag_node_module, "_default_embedder", lambda: StubEmbedder())

    settings = Settings(_env_file=None, rag_index_dir=str(index_dir))

    result = await probe_rag_index(settings)

    assert result.status == "ready"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -k rag_index -v`
Expected: FAIL — `ImportError: cannot import name 'probe_rag_index'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/services/health.py`:

```python
async def probe_rag_index(settings: Settings) -> ProbeResult:
    """manifest/checksum/open/query smoke — dùng đúng retriever/embedder mà
    đường truy hồi thật đang dùng (qua rag_node's cached singletons), tránh
    nạp FAISS/embedder hai lần."""
    import asyncio

    started = time.perf_counter_ns()
    status, detail = await asyncio.to_thread(_probe_rag_index_sync, settings)
    return ProbeResult(status=status, latency_ms=_elapsed_ms(started), detail=detail)


def _probe_rag_index_sync(settings: Settings) -> tuple[Status, str | None]:
    import json
    from pathlib import Path

    from src.agents.nodes import rag_node
    from src.rag.index import VectorIndex

    index_dir = Path(settings.rag_index_dir)
    if not rag_node.index_is_built(index_dir):
        return "down", "rag_index_not_built"

    try:
        manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "down", f"rag_manifest_unreadable:{exc}"

    expected_checksum = manifest.get("index_checksum")
    actual_checksum = VectorIndex.checksum(index_dir)
    if expected_checksum != actual_checksum:
        return "down", "rag_checksum_mismatch"

    try:
        retriever = rag_node._default_retriever()
        embedder = rag_node._default_embedder()
        retriever.search("kiểm tra hệ thống", embedder)
    except (OSError, ValueError) as exc:
        return "down", f"rag_query_failed:{exc}"

    return "ready", None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_health.py -v`
Expected: PASS — full file (all probes from Tasks 3–7)

- [ ] **Step 5: Commit**

```bash
git add src/services/health.py tests/test_services/test_health.py
git commit -m "feat(health): add probe_rag_index with manifest checksum verification"
```

---

### Task 8: `GET /healthz` router, wire into `src/main.py`, remove `GET /health`

**Files:**
- Create: `src/api/health.py`
- Modify: `src/main.py:7-11` (add import), `src/main.py:65-71` (add `include_router`), `src/main.py:74-87` (delete the old `/health` endpoint)
- Modify: `tests/test_api/test_routes.py:1-9` (replace `test_health`)
- Test: `tests/test_api/test_health.py` (new — integration tests for `/healthz`)

**Interfaces:**
- Consumes: every probe from `src/services/health.py` (Tasks 3–7): `probe_backend`, `probe_llm`, `probe_mqtt`, `probe_vehicle_simulator`, `probe_stt`, `probe_tts`, `probe_rag_index`, `probe_sqlite`, plus `run_with_timeout`, `clear_probe_cache`. Consumes `get_settings()` (`src/config.py`), `SCHEMA_VERSION` (`src/models/vehicle.py`), `app.state.mqtt` (set in `src/main.py`'s `lifespan`, same object `GET /vehicle/state` already reads).
- Produces: `router: APIRouter` with `GET /healthz`, mounted at app root — nothing downstream depends on this beyond the HTTP contract itself.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_health.py`:

```python
import pytest

from src.services.health import clear_probe_cache


@pytest.fixture(autouse=True)
def _clear_health_cache():
    clear_probe_cache()
    yield
    clear_probe_cache()


def _fail_all_probes(monkeypatch) -> None:
    """Đẩy cả 8 probe về down mà không cần model/broker thật — dùng cho test 503."""
    import src.api.health as health_router

    async def _down(*args, **kwargs):
        from src.services.health import ProbeResult

        return ProbeResult(status="down", latency_ms=0.0, detail="stub_down")

    for name in (
        "probe_backend",
        "probe_llm",
        "probe_mqtt",
        "probe_vehicle_simulator",
        "probe_stt",
        "probe_tts",
        "probe_rag_index",
        "probe_sqlite",
    ):
        monkeypatch.setattr(health_router.health_service, name, _down)


def _ready_all_probes(monkeypatch) -> None:
    import src.api.health as health_router

    async def _ready(*args, **kwargs):
        from src.services.health import ProbeResult

        return ProbeResult(status="ready", latency_ms=1.0)

    for name in (
        "probe_backend",
        "probe_llm",
        "probe_mqtt",
        "probe_vehicle_simulator",
        "probe_stt",
        "probe_tts",
        "probe_rag_index",
        "probe_sqlite",
    ):
        monkeypatch.setattr(health_router.health_service, name, _ready)


async def test_healthz_returns_200_when_all_components_ready(client, monkeypatch) -> None:
    _ready_all_probes(monkeypatch)

    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ready"
    assert set(body["data"]["components"]) == {
        "backend",
        "llm",
        "mqtt",
        "vehicle_simulator",
        "stt",
        "tts",
        "rag_index",
        "sqlite",
    }
    for component in body["data"]["components"].values():
        assert component["status"] == "ready"
        assert "latency_ms" in component
    assert body["schema_version"] == "1.0"


async def test_healthz_returns_503_when_any_component_down(client, monkeypatch) -> None:
    _ready_all_probes(monkeypatch)
    import src.api.health as health_router
    from src.services.health import ProbeResult

    async def _down(*args, **kwargs):
        return ProbeResult(status="down", latency_ms=1.0, detail="stub_down")

    monkeypatch.setattr(health_router.health_service, "probe_rag_index", _down)

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["details"]["dependencies"]["rag_index"]["status"] == "down"
    assert body["error"]["details"]["dependencies"]["backend"]["status"] == "ready"


async def test_healthz_returns_503_when_all_components_down(client, monkeypatch) -> None:
    _fail_all_probes(monkeypatch)

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_NOT_READY"


async def test_health_endpoint_removed(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 404
```

Replace the whole content of `tests/test_api/test_routes.py` (drop `test_health`, keep the rest unchanged):

```python
import pytest


@pytest.mark.asyncio
async def test_chat_empty_message(client):
    response = await client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.health'`

- [ ] **Step 3: Write minimal implementation**

Create `src/api/health.py`:

```python
"""GET /healthz — readiness của 8 dependency bắt buộc.

`200` chỉ khi cả 8 component `ready`; ngược lại `503` theo common error
envelope. Hợp đồng đầy đủ ở docs/devops.md §Readiness contract và
docs/api_spec.md#health — file này chỉ lắp ráp, không định nghĩa lại ngữ nghĩa.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.models.vehicle import SCHEMA_VERSION
from src.services import health as health_service
from src.services.mqtt_runtime import MqttRuntime

router = APIRouter()

_COMPONENT_NAMES = (
    "backend",
    "llm",
    "mqtt",
    "vehicle_simulator",
    "stt",
    "tts",
    "rag_index",
    "sqlite",
)


@router.get("/healthz")
async def healthz(request: Request):
    settings = get_settings()
    runtime: MqttRuntime | None = getattr(request.app.state, "mqtt", None)
    timeout_s = settings.health_probe_timeout_s

    results = await asyncio.gather(
        health_service.run_with_timeout(health_service.probe_backend(), timeout_s, "backend_timeout"),
        health_service.run_with_timeout(health_service.probe_llm(settings), timeout_s, "llm_timeout"),
        health_service.run_with_timeout(health_service.probe_mqtt(runtime), timeout_s, "mqtt_timeout"),
        health_service.run_with_timeout(
            health_service.probe_vehicle_simulator(runtime), timeout_s, "vehicle_simulator_timeout"
        ),
        health_service.run_with_timeout(health_service.probe_stt(settings), timeout_s, "stt_timeout"),
        health_service.run_with_timeout(health_service.probe_tts(settings), timeout_s, "tts_timeout"),
        health_service.run_with_timeout(health_service.probe_rag_index(settings), timeout_s, "rag_index_timeout"),
        health_service.run_with_timeout(health_service.probe_sqlite(settings), timeout_s, "sqlite_timeout"),
    )
    components = dict(zip(_COMPONENT_NAMES, results, strict=True))

    request_id = f"req_{uuid.uuid4().hex[:12]}"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    checked_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    all_ready = all(result.status == "ready" for result in components.values())

    if all_ready:
        return {
            "data": {
                "status": "ready",
                "checked_at": checked_at,
                "components": {
                    name: {"status": result.status, "latency_ms": result.latency_ms}
                    for name, result in components.items()
                },
                "faults": [],
            },
            "meta": {"request_id": request_id},
            "trace_id": trace_id,
            "schema_version": SCHEMA_VERSION,
        }

    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "DEPENDENCY_NOT_READY",
                "message": "một hoặc nhiều dependency bắt buộc chưa sẵn sàng",
                "retryable": True,
                "details": {
                    "dependencies": {
                        name: {"status": result.status, "code": result.detail or ""}
                        for name, result in components.items()
                    }
                },
            },
            "meta": {"request_id": request_id},
            "trace_id": trace_id,
            "schema_version": SCHEMA_VERSION,
        },
    )
```

In `src/main.py`, change the import block (currently lines 7–11):

```python
from src.api.agent_routes import router as agent_router
from src.api.approvals import router as approvals_router
from src.api.routes import router
from src.api.turns import router as turns_router
from src.api.ws import router as ws_router
```

to:

```python
from src.api.agent_routes import router as agent_router
from src.api.approvals import router as approvals_router
from src.api.health import router as health_router
from src.api.routes import router
from src.api.turns import router as turns_router
from src.api.ws import router as ws_router
```

Change the router-mounting block (currently lines 65–71):

```python
app.include_router(router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(turns_router, prefix="/api/v1")
# WebSocket không có prefix /api/v1 — api_spec.md chốt `WS /ws/ivi` và
# `WS /ws/engineer` ở gốc.
app.include_router(ws_router)
```

to:

```python
app.include_router(router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(turns_router, prefix="/api/v1")
# WebSocket và /healthz không có prefix /api/v1 — api_spec.md chốt `WS /ws/ivi`,
# `WS /ws/engineer`, và `GET /healthz` ở gốc.
app.include_router(ws_router)
app.include_router(health_router)
```

Delete the old `/health` endpoint at the end of `src/main.py` (currently lines 74–87):

```python
@app.get("/health")
async def health():
    runtime = getattr(app.state, "mqtt", None)
    return {
        "status": "ok",
        "env": settings.app_env,
        "components": {
            "mqtt": "ready" if runtime is not None and runtime.connected else "down",
            "vehicle_simulator": (
                "ready" if runtime is not None and runtime.cache.simulator_ready() else "down"
            ),
        },
    }
```

Delete it entirely (no replacement — `/healthz` now covers `mqtt` and `vehicle_simulator` plus six more).

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_health.py tests/test_api/test_routes.py -v`
Expected: PASS

Then run the full suite to confirm nothing else referenced `/health`:

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: same pass count as before this task, minus the old `test_health`, plus the new tests — no failures.

- [ ] **Step 5: Commit**

```bash
git add src/api/health.py src/main.py tests/test_api/test_health.py tests/test_api/test_routes.py
git commit -m "feat(api): add GET /healthz aggregating all 8 probes, remove old GET /health"
```

---

## Post-plan verification

After Task 8, run the full local suite once more and confirm the failure count only reflects pre-existing missing-optional-dependency failures (per `CLAUDE.md`'s "Known state" note), not anything from this plan:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
ruff check src/ tests/
```

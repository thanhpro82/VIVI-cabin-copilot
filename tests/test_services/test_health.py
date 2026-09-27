import asyncio
import json
import sqlite3
from pathlib import Path

import httpx

from src.config import Settings
from src.services.health import (
    COMPONENT_NAMES,
    ProbeResult,
    clear_probe_cache,
    health_event_payload,
    is_ready,
    probe_backend,
    probe_llm,
    probe_mqtt,
    probe_rag_index,
    probe_sqlite,
    probe_stt,
    probe_tts,
    probe_vehicle_simulator,
    run_with_timeout,
)


def test_health_event_payload_status_is_ready_when_only_llm_is_down() -> None:
    """Issue #48: gate `status` bỏ qua `llm`, nhưng `components`/`faults` vẫn lộ
    đúng trạng thái thật của nó — cùng ngữ nghĩa với `GET /healthz`."""
    components = {
        "backend": ProbeResult(status="ready", latency_ms=1.0),
        "llm": ProbeResult(status="down", latency_ms=1.0, detail="slm_disabled"),
        "mqtt": ProbeResult(status="ready", latency_ms=1.0),
        "vehicle_simulator": ProbeResult(status="ready", latency_ms=1.0),
        "stt": ProbeResult(status="ready", latency_ms=1.0),
        "tts": ProbeResult(status="ready", latency_ms=1.0),
        "rag_index": ProbeResult(status="ready", latency_ms=1.0),
        "sqlite": ProbeResult(status="ready", latency_ms=1.0),
    }

    payload = health_event_payload(components, "2026-08-11T00:00:00Z")

    assert payload["status"] == "ready"
    assert payload["components"]["llm"]["status"] == "down"
    assert payload["faults"] == [{"component": "llm", "status": "down", "code": "slm_disabled"}]


def test_health_event_payload_status_is_down_when_a_required_component_is_down() -> None:
    components = {
        "backend": ProbeResult(status="ready", latency_ms=1.0),
        "llm": ProbeResult(status="down", latency_ms=1.0, detail="slm_disabled"),
        "mqtt": ProbeResult(status="down", latency_ms=1.0, detail="mqtt_not_connected"),
        "vehicle_simulator": ProbeResult(status="ready", latency_ms=1.0),
        "stt": ProbeResult(status="ready", latency_ms=1.0),
        "tts": ProbeResult(status="ready", latency_ms=1.0),
        "rag_index": ProbeResult(status="ready", latency_ms=1.0),
        "sqlite": ProbeResult(status="ready", latency_ms=1.0),
    }

    payload = health_event_payload(components, "2026-08-11T00:00:00Z")

    assert payload["status"] == "down"
    assert {fault["component"] for fault in payload["faults"]} == {"llm", "mqtt"}


def _components(**ghi_de: ProbeResult) -> dict[str, ProbeResult]:
    """8 component `ready`, ghi đè theo tên."""
    base = {name: ProbeResult(status="ready", latency_ms=1.0) for name in COMPONENT_NAMES}
    base.update(ghi_de)
    return base


def test_readiness_gate_treats_disabled_as_not_a_fault() -> None:
    """Issue #95: `disabled` không chặn `ready`, `down`/`degraded` thì chặn."""
    assert is_ready(_components()) is True
    assert (
        is_ready(
            _components(
                mqtt=ProbeResult(status="disabled", latency_ms=0.0, detail="mqtt_disabled"),
                vehicle_simulator=ProbeResult(
                    status="disabled", latency_ms=0.0, detail="vehicle_simulator_mqtt_disabled"
                ),
                llm=ProbeResult(status="disabled", latency_ms=0.0, detail="slm_disabled"),
            )
        )
        is True
    )
    assert is_ready(_components(mqtt=ProbeResult(status="down", latency_ms=1.0))) is False
    assert is_ready(_components(mqtt=ProbeResult(status="degraded", latency_ms=1.0))) is False


def test_health_event_payload_status_is_ready_when_mqtt_stack_is_disabled() -> None:
    """`/ws/engineer` phải trả lời **cùng một** câu như `/healthz` về cùng hệ thống —
    hai đường đọc readiness rời nhau là đúng lớp lỗi ADR-013 cấm cho vehicle state.
    `disabled` vẫn nằm trong `faults` để kỹ sư nhìn thấy, chỉ không kéo `status`."""
    payload = health_event_payload(
        _components(
            llm=ProbeResult(status="disabled", latency_ms=0.0, detail="slm_disabled"),
            mqtt=ProbeResult(status="disabled", latency_ms=0.0, detail="mqtt_disabled"),
            vehicle_simulator=ProbeResult(status="disabled", latency_ms=0.0, detail="vehicle_simulator_mqtt_disabled"),
        ),
        "2026-08-15T00:00:00Z",
    )

    assert payload["status"] == "ready"
    assert {fault["component"] for fault in payload["faults"]} == {"llm", "mqtt", "vehicle_simulator"}
    assert all(fault["status"] == "disabled" for fault in payload["faults"])


async def test_probe_backend_is_always_ready() -> None:
    result = await probe_backend()

    assert result.status == "ready"
    assert result.latency_ms >= 0


class _FakeCache:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def simulator_ready(self) -> bool:
        return self._ready


class _FakeMqttClient:
    """`MqttPort` giả cho test `probe_mqtt` — round-trip thật (issue #51) cần
    một client có `publish()`, không chỉ cờ `connected`."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, dict, int]] = []

    async def publish(self, topic: str, payload: dict, *, qos: int = 1, retain: bool = False) -> None:
        if self.fail:
            raise RuntimeError("broker không PUBACK — mô phỏng round-trip thất bại")
        self.published.append((topic, payload, qos))


class _FakeRuntime:
    def __init__(self, *, connected: bool, simulator_ready: bool, client: _FakeMqttClient | None = None) -> None:
        self.connected = connected
        self.client = client if client is not None else (_FakeMqttClient() if connected else None)
        self.vehicle_id = "veh-test"
        self.cache = _FakeCache(simulator_ready)


#: Cấu hình "MQTT đang bật" — mặc định của repo. Viết rõ ra thay vì dựa vào default
#: để test không đổi nghĩa nếu ai đó lật `mqtt_enabled` trong `src/config.py`.
_MQTT_BAT = Settings(_env_file=None, mqtt_enabled=True)
_MQTT_TAT = Settings(_env_file=None, mqtt_enabled=False)


async def test_probe_mqtt_ready_when_publish_round_trip_succeeds() -> None:
    runtime = _FakeRuntime(connected=True, simulator_ready=True)
    result = await probe_mqtt(runtime, _MQTT_BAT)
    assert result.status == "ready"
    assert runtime.client.published[0][0] == "v1/vehicles/veh-test/commands/_health_probe"
    assert runtime.client.published[0][2] == 1


async def test_probe_mqtt_down_when_runtime_missing() -> None:
    result = await probe_mqtt(None, _MQTT_BAT)
    assert result.status == "down"


async def test_probe_mqtt_down_when_not_connected() -> None:
    runtime = _FakeRuntime(connected=False, simulator_ready=True)
    result = await probe_mqtt(runtime, _MQTT_BAT)
    assert result.status == "down"
    assert result.detail == "mqtt_not_connected"


async def test_probe_mqtt_down_when_publish_round_trip_fails() -> None:
    """Kết nối còn `client is not None` nhưng broker không PUBACK — đúng
    kịch bản cờ `connected` cũ (proxy) không phát hiện được."""
    runtime = _FakeRuntime(connected=True, simulator_ready=True, client=_FakeMqttClient(fail=True))
    result = await probe_mqtt(runtime, _MQTT_BAT)
    assert result.status == "down"
    assert result.detail is not None
    assert result.detail.startswith("mqtt_probe_failed:")


async def test_probe_mqtt_disabled_when_mqtt_turned_off_by_config() -> None:
    """Issue #95: `MQTT_ENABLED=false` là tắt có chủ đích. Không probe, không `down`."""
    result = await probe_mqtt(None, _MQTT_TAT)
    assert result.status == "disabled"
    assert result.detail == "mqtt_disabled"


async def test_probe_mqtt_disabled_wins_even_if_a_runtime_is_hanging_around() -> None:
    """Cấu hình quyết định, không phải sự hiện diện của runtime. `lifespan` không dựng
    runtime khi `mqtt_enabled=false`, nhưng nếu một test/luồng nào đó gắn vào
    `app.state.mqtt` thì `/healthz` vẫn phải báo đúng cấu hình đang chạy — và **không**
    được publish thăm dò lên một broker mà cấu hình nói là không dùng."""
    runtime = _FakeRuntime(connected=True, simulator_ready=True)
    result = await probe_mqtt(runtime, _MQTT_TAT)
    assert result.status == "disabled"
    assert runtime.client.published == []


async def test_probe_vehicle_simulator_ready_when_heartbeat_fresh() -> None:
    runtime = _FakeRuntime(connected=True, simulator_ready=True)
    result = await probe_vehicle_simulator(runtime, _MQTT_BAT)
    assert result.status == "ready"


async def test_probe_vehicle_simulator_down_when_heartbeat_stale() -> None:
    runtime = _FakeRuntime(connected=True, simulator_ready=False)
    result = await probe_vehicle_simulator(runtime, _MQTT_BAT)
    assert result.status == "down"


async def test_probe_vehicle_simulator_down_when_runtime_missing() -> None:
    result = await probe_vehicle_simulator(None, _MQTT_BAT)
    assert result.status == "down"


async def test_probe_vehicle_simulator_disabled_when_mqtt_turned_off_by_config() -> None:
    """**Cổng 3 của issue #95, quyết định phải nói rõ chứ không được rơi ra từ code.**

    Simulator chỉ tới được qua MQTT: heartbeat của nó đi trên chính broker đó. Tắt MQTT
    thì heartbeat vắng mặt **do đúng lựa chọn ấy**, không phải do simulator hỏng — báo
    `down` ở đây sẽ dựng lại nguyên cái 503 mà thay đổi này sinh ra để gỡ, chỉ đổi tên
    component. Nên nó cũng là `disabled`, và cũng không phải dependency bắt buộc của
    cấu hình đang chạy.

    Ngược lại, khi MQTT **bật** mà heartbeat cũ thì vẫn `down` như cũ (test ngay trên):
    đó mới là hỏng thật.
    """
    result = await probe_vehicle_simulator(None, _MQTT_TAT)
    assert result.status == "disabled"
    assert result.detail == "vehicle_simulator_mqtt_disabled"


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


async def test_run_with_timeout_returns_down_on_probe_exception() -> None:
    async def _failing() -> ProbeResult:
        raise ValueError("boom")

    result = await run_with_timeout(_failing(), timeout_s=1.0, timeout_detail="x_timeout")
    assert result.status == "down"
    assert result.detail is not None
    assert "probe_error" in result.detail


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


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_probe_llm_disabled_when_slm_disabled() -> None:
    """Issue #95: `slm_enabled=false` là **tắt có chủ đích**, không phải dependency
    hỏng. Trạng thái phải là `disabled` chứ không phải `down` — `down` ở đây từng
    kéo `/healthz` xuống 503 vĩnh viễn ở đúng cấu hình mặc định của P0."""
    settings = Settings(_env_file=None, slm_enabled=False)

    result = await probe_llm(settings)

    assert result.status == "disabled"
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


async def test_probe_stt_cache_expires_after_ttl(monkeypatch) -> None:
    from src.services import voice as voice_module

    calls = []

    def _record(audio_bytes: bytes):
        calls.append(audio_bytes)
        return voice_module.Transcript(text="ok", latency_ms=1.0)

    monkeypatch.setattr(voice_module, "transcribe_raw", _record)
    clear_probe_cache()
    settings = Settings(_env_file=None, health_voice_probe_ttl_s=0.01)

    await probe_stt(settings)
    await asyncio.sleep(0.05)
    await probe_stt(settings)

    assert len(calls) == 2  # TTL elapsed, second call re-invoked the engine
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


async def test_probe_rag_index_down_when_manifest_unreadable(tmp_path: Path) -> None:
    from src.rag.embed import StubEmbedder
    from src.rag.index import VectorIndex
    from src.rag.models import Chunk

    index_dir = tmp_path / "index"
    chunk = Chunk(chunk_id="c1", document_id="d1", section="s", heading="h", text="nội dung thử")
    VectorIndex.build([chunk], StubEmbedder()).save(index_dir)
    (index_dir / "manifest.json").write_text("{ not valid json", encoding="utf-8")

    settings = Settings(_env_file=None, rag_index_dir=str(index_dir))

    result = await probe_rag_index(settings)

    assert result.status == "down"
    assert (result.detail or "").startswith("rag_manifest_unreadable")


async def test_probe_rag_index_down_when_query_raises(monkeypatch, tmp_path: Path) -> None:
    from src.rag.embed import StubEmbedder
    from src.rag.index import VectorIndex
    from src.rag.models import Chunk

    index_dir = tmp_path / "index"
    chunk = Chunk(chunk_id="c1", document_id="d1", section="s", heading="h", text="nội dung thử")
    checksum = VectorIndex.build([chunk], StubEmbedder()).save(index_dir)
    (index_dir / "manifest.json").write_text(json.dumps({"index_checksum": checksum}), encoding="utf-8")

    from src.agents.nodes import rag_node as rag_node_module

    class _BoomRetriever:
        def search(self, query, embedder):
            raise ValueError("retrieval exploded")

    rag_node_module._default_retriever.cache_clear()
    rag_node_module._default_embedder.cache_clear()
    monkeypatch.setattr(rag_node_module, "_default_retriever", lambda: _BoomRetriever())
    monkeypatch.setattr(rag_node_module, "_default_embedder", lambda: StubEmbedder())

    settings = Settings(_env_file=None, rag_index_dir=str(index_dir))

    result = await probe_rag_index(settings)

    assert result.status == "down"
    assert (result.detail or "").startswith("rag_query_failed")


async def test_probe_rag_index_caches_result_within_ttl(monkeypatch, tmp_path: Path) -> None:
    """Issue #51: re-hash checksum + chạy 1 query FAISS/embedder thật mỗi lần
    poll `/healthz` là tốn CPU không cần thiết — cache theo TTL, cùng cơ chế
    `probe_stt`/`probe_tts` đã có."""
    import src.services.health as health_module

    calls: list[str] = []

    def _record(settings: Settings):
        calls.append(settings.rag_index_dir)
        return "ready", None

    monkeypatch.setattr(health_module, "_probe_rag_index_sync", _record)
    clear_probe_cache()
    settings = Settings(_env_file=None, rag_index_dir=str(tmp_path / "index"), health_rag_probe_ttl_s=60.0)

    await probe_rag_index(settings)
    await probe_rag_index(settings)

    assert len(calls) == 1  # gọi lần hai trong TTL không re-hash/re-embed
    clear_probe_cache()


async def test_probe_rag_index_cache_key_is_scoped_by_index_dir(monkeypatch, tmp_path: Path) -> None:
    """Hai `Settings` khác `rag_index_dir` trong cùng tiến trình không được đọc
    nhầm cache của nhau — khoá cache theo `rag_index_dir`, không phải chuỗi cố
    định `"rag_index"`."""
    import src.services.health as health_module

    calls: list[str] = []

    def _record(settings: Settings):
        calls.append(settings.rag_index_dir)
        return "ready", None

    monkeypatch.setattr(health_module, "_probe_rag_index_sync", _record)
    clear_probe_cache()
    settings_a = Settings(_env_file=None, rag_index_dir=str(tmp_path / "a"), health_rag_probe_ttl_s=60.0)
    settings_b = Settings(_env_file=None, rag_index_dir=str(tmp_path / "b"), health_rag_probe_ttl_s=60.0)

    await probe_rag_index(settings_a)
    await probe_rag_index(settings_b)

    assert len(calls) == 2  # khác rag_index_dir -> khác cache key -> cả hai đều chạy live
    clear_probe_cache()

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


def _ready_all_probes(monkeypatch, tru: tuple[str, ...] = ()) -> None:
    """Đẩy cả 8 probe về ready. `tru` giữ nguyên probe **thật** cho những tên nêu ra.

    Cần `tru` vì các test của issue #95 phải chạy probe thật — chỗ hỏng nằm trong
    chính probe. Không thể "stub hết rồi khôi phục lại một cái": đọc
    `health_service.probe_llm` sau khi stub sẽ lấy về đúng cái stub.
    """
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
        if name in tru:
            continue
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


async def test_healthz_returns_503_when_component_is_degraded(client, monkeypatch) -> None:
    _ready_all_probes(monkeypatch)
    import src.api.health as health_router
    from src.services.health import ProbeResult

    async def _degraded(*args, **kwargs):
        return ProbeResult(status="degraded", latency_ms=1.0, detail="stub_degraded")

    monkeypatch.setattr(health_router.health_service, "probe_mqtt", _degraded)

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["details"]["dependencies"]["mqtt"]["status"] == "degraded"


def test_llm_is_exempt_from_the_required_component_gate() -> None:
    """Issue #48: `llm` không bao giờ `ready` ở P0 (`slm_enabled=False` theo thiết
    kế, ADR-005 "Not Yet") — không được tính vào readiness gate."""
    from src.services.health import COMPONENT_NAMES, REQUIRED_COMPONENT_NAMES

    assert "llm" not in REQUIRED_COMPONENT_NAMES
    assert REQUIRED_COMPONENT_NAMES == frozenset(COMPONENT_NAMES) - {"llm"}


async def test_healthz_returns_200_when_only_llm_is_down(client, monkeypatch) -> None:
    """`llm` down một mình không được kéo cả `/healthz` xuống 503 — nhưng trạng thái
    thật của nó vẫn phải lộ ra trong `components` và `faults`, không giấu."""
    _ready_all_probes(monkeypatch)
    import src.api.health as health_router
    from src.services.health import ProbeResult

    async def _down(*args, **kwargs):
        return ProbeResult(status="down", latency_ms=1.0, detail="slm_disabled")

    monkeypatch.setattr(health_router.health_service, "probe_llm", _down)

    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "ready"
    assert body["components"]["llm"]["status"] == "down"
    assert body["faults"] == [{"component": "llm", "status": "down", "code": "slm_disabled"}]


# --- Issue #95: component tat co chu dich khong keo /healthz xuong 503 -------
#
# Cong 4 cua Thanh: "Test HTTP chung minh ca hai cau hinh deu 200 va payload van
# hien dung trang thai cac component bi tat." Nen la test HTTP that qua `client`,
# di qua ca probe that lan aggregation that — mot unit test tren `is_ready()` khong
# chung minh duoc route dung no.


def _mock_settings(monkeypatch, **ghi_de) -> None:
    """Ép `/healthz` đọc một `Settings` cụ thể, không phụ thuộc `.env` của máy chạy."""
    import src.api.health as health_router
    from src.config import Settings

    settings = Settings(_env_file=None, **ghi_de)
    monkeypatch.setattr(health_router, "get_settings", lambda: settings)


async def test_healthz_returns_200_at_default_config_where_slm_is_disabled(client, monkeypatch) -> None:
    """Chính là bug của issue #95: `slm_enabled=false` là **mặc định P0**, nên
    `/healthz` trả 503 vĩnh viễn ở đúng cấu hình mà cả nhóm đang chạy.

    Không stub `probe_llm` — probe thật phải tự trả `disabled`, vì đó là chỗ hỏng.
    """
    _ready_all_probes(monkeypatch, tru=("probe_llm",))
    _mock_settings(monkeypatch, slm_enabled=False)

    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "ready"
    assert body["components"]["llm"]["status"] == "disabled"
    assert {"component": "llm", "status": "disabled", "code": "slm_disabled"} in body["faults"]


async def test_healthz_returns_200_when_mqtt_is_disabled_by_config(client, monkeypatch) -> None:
    """`MQTT_ENABLED=false` là cấu hình chạy test/demo offline của cả repo
    (CLAUDE.md: "MQTT_ENABLED=false is not optional for speed"). Ở đó `app.state.mqtt`
    là `None`, nên trước thay đổi này `/healthz` báo hai dependency `down` và trả 503.

    Cả `mqtt` lẫn `vehicle_simulator` phải `disabled` — xem cổng 3 ở
    `tests/test_services/test_health.py`.
    """
    _ready_all_probes(monkeypatch, tru=("probe_llm", "probe_mqtt", "probe_vehicle_simulator"))
    _mock_settings(monkeypatch, mqtt_enabled=False, slm_enabled=False)

    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "ready"
    assert body["components"]["mqtt"]["status"] == "disabled"
    assert body["components"]["vehicle_simulator"]["status"] == "disabled"
    # Van hien trong faults — "tat" khong duoc dong nghia voi "giau".
    assert {fault["component"]: fault["code"] for fault in body["faults"]} == {
        "llm": "slm_disabled",
        "mqtt": "mqtt_disabled",
        "vehicle_simulator": "vehicle_simulator_mqtt_disabled",
    }


async def test_healthz_still_returns_503_when_mqtt_is_enabled_but_broken(client, monkeypatch) -> None:
    """Lưới chặn của chính thay đổi này: **tắt** khác **hỏng**. Nếu miễn trừ rộng tay
    thành "MQTT không bao giờ chặn readiness" thì một broker chết trong cấu hình có
    MQTT sẽ im lặng báo `ready` — mất đúng thứ `/healthz` sinh ra để bắt."""
    _ready_all_probes(monkeypatch, tru=("probe_llm", "probe_mqtt"))
    _mock_settings(monkeypatch, mqtt_enabled=True, slm_enabled=False)

    response = await client.get("/healthz")

    assert response.status_code == 503
    assert response.json()["error"]["details"]["dependencies"]["mqtt"]["status"] == "down"


async def test_healthz_returns_503_when_all_components_down(client, monkeypatch) -> None:
    _fail_all_probes(monkeypatch)

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_NOT_READY"


async def test_health_endpoint_removed(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 404

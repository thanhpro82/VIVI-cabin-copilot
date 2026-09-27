"""GET /api/v1/vehicle/state và WS /ws/engineer."""

from __future__ import annotations

import anyio
import pytest
from fastapi.testclient import TestClient

from src import mqtt_topics
from src.main import app
from src.models.vehicle import VehicleStateSnapshot
from src.services.mqtt_client import InMemoryBroker
from src.services.mqtt_runtime import MqttRuntime
from src.services.vehicle_gateway import (
    InProcessVehicleGateway,
    MqttVehicleGateway,
    set_vehicle_gateway,
)
from src.vehicle_sim.runtime import SimulatorRuntime
from src.vehicle_sim.state import VehicleSimulator
from tests.test_api.ws_helpers import engineer_connect_kwargs

VEHICLE_ID = "vehicle-test-01"


class FakeClock:
    """monotonic giả, thay `time.monotonic` trong VehicleStateCache.

    Cần vì tuổi heartbeat mặc định là 15 giây: chứng minh nó hết hạn bằng
    `asyncio.sleep` sẽ tốn 15 giây thật mỗi lần chạy suite, và trên Windows độ
    phân giải timer ~15,6 ms khiến mọi mốc ngắn hơn không đáng tin.
    """

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _health_payload(*, online: bool, state_version: int = 1) -> dict:
    """Payload `health` hợp lệ. `online=false` bắt buộc có `reason` (models/vehicle.py)."""
    if online:
        return {
            "schema_version": "1.0",
            "vehicle_id": VEHICLE_ID,
            "online": True,
            "state_version": state_version,
            "simulator_version": "1.0.0",
            "heartbeat_at": "2026-08-09T02:00:00Z",
        }
    return {
        "schema_version": "1.0",
        "vehicle_id": VEHICLE_ID,
        "online": False,
        "reason": "lwt",
    }


@pytest.fixture
async def runtime():
    """Backend runtime nối vào broker giả, có sẵn một xe ảo đang chạy."""
    broker = InMemoryBroker()
    simulator = VehicleSimulator(VEHICLE_ID)
    sim_runtime = SimulatorRuntime(simulator, broker, heartbeat_interval_s=3600)
    await sim_runtime.start()

    clock = FakeClock()
    backend = MqttRuntime(VEHICLE_ID, clock=clock)
    await backend.bind(broker, timeout_ms=500)

    app.state.mqtt = backend
    set_vehicle_gateway(MqttVehicleGateway(backend))
    yield backend, broker, simulator, clock
    await sim_runtime.stop()


@pytest.fixture
def mqtt_gateway_khong_co_broker():
    """Cổng MQTT trỏ vào một runtime chưa bind — tái hiện đúng "broker chết".

    Trung thực hơn cách cũ (`app.state.mqtt = None`): sau khi có gateway, không
    gán gì cả sẽ rơi về simulator in-process và endpoint trả 200. Trạng thái ta
    muốn kiểm là *đã bảo dùng MQTT nhưng không nối được*, chứ không phải *không
    dùng MQTT*.
    """
    set_vehicle_gateway(MqttVehicleGateway(MqttRuntime(VEHICLE_ID)))


async def _error_of(client, **kwargs) -> dict:
    """Gọi endpoint, khẳng định vỏ lỗi đúng api_spec.md, trả về thân `error`."""
    response = await client.get("/api/v1/vehicle/state", **kwargs)

    assert response.status_code == 503
    body = response.json()
    # Vỏ lỗi phải nằm ở TOP-LEVEL. HTTPException(detail=...) bọc thêm một tầng
    # "detail" và frontend đọc body.error.code sẽ luôn miss — xem src/api/errors.py.
    assert set(body) == {"error", "meta", "trace_id", "schema_version"}
    assert body["schema_version"] == "1.0"
    assert "request_id" in body["meta"]
    assert body["error"]["code"] == "MQTT_UNAVAILABLE"
    assert body["error"]["retryable"] is True
    return body["error"]


async def test_chua_noi_broker_thi_tra_503_broker_unreachable(client, mqtt_gateway_khong_co_broker, driver_client):
    error = await _error_of(client)

    assert error["details"]["reason"] == "broker_unreachable"
    assert error["details"]["mqtt_connected"] is False


async def test_da_noi_broker_nhung_chua_co_snapshot(client, driver_client):
    """Broker sống, xe ảo chưa từng publish — khác hẳn broker chết, phải nói rõ."""
    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(InMemoryBroker(), timeout_ms=500)
    app.state.mqtt = backend
    set_vehicle_gateway(MqttVehicleGateway(backend))

    error = await _error_of(client)

    assert error["details"]["reason"] == "no_snapshot_yet"
    assert error["details"]["mqtt_connected"] is True


async def test_mqtt_tat_thi_dung_xe_in_process_va_tra_200(client, driver_client):
    """`MQTT_ENABLED=false` là lựa chọn tường minh, không phải sự cố.

    Ở chế độ đó backend chạy xe in-process nên endpoint vẫn phục vụ được — nhờ
    vậy người làm frontend dựng UI mà không cần dựng Mosquitto.
    """
    set_vehicle_gateway(InProcessVehicleGateway.new(VEHICLE_ID))

    response = await client.get("/api/v1/vehicle/state")

    assert response.status_code == 200
    assert response.json()["data"]["vehicle_state"]["vehicle_id"] == VEHICLE_ID


async def test_simulator_offline_thi_khong_tra_state_cu(client, runtime, driver_client):
    """Có snapshot trong cache nhưng xe ảo đã chết — 503, không phải 200."""
    _backend, broker, _simulator, _clock = runtime
    await broker.publish(mqtt_topics.health(VEHICLE_ID), _health_payload(online=False), qos=1, retain=True)

    error = await _error_of(client)

    assert error["details"]["reason"] == "offline"
    assert error["details"]["simulator_online"] is False
    # Vẫn báo version cuối biết được để người vận hành định vị được thời điểm.
    assert error["details"]["last_state_version"] >= 1


async def test_heartbeat_qua_han_thi_tu_choi(client, runtime, driver_client):
    _backend, _broker, _simulator, clock = runtime

    clock.advance(15.001)  # mặc định heartbeat_stale_s = 15.0

    error = await _error_of(client)

    assert error["details"]["reason"] == "heartbeat_stale"
    assert error["details"]["simulator_online"] is True
    assert error["details"]["health_age_s"] > 15.0
    assert error["details"]["heartbeat_stale_s"] == 15.0


async def test_heartbeat_moi_ve_thi_tuoi_lai(client, runtime, driver_client):
    """Chứng minh mốc hết hạn không phải one-way: nhận heartbeat mới là ready lại."""
    _backend, broker, simulator, clock = runtime
    clock.advance(20.0)
    await _error_of(client)

    await broker.publish(
        mqtt_topics.health(VEHICLE_ID),
        _health_payload(online=True, state_version=simulator.state.state_version),
        qos=1,
        retain=True,
    )

    assert (await client.get("/api/v1/vehicle/state")).status_code == 200


async def test_x_trace_id_cua_client_duoc_dung_lai(client, runtime):
    response = await client.get("/api/v1/vehicle/state", headers={"X-Trace-Id": "tr_client_001"})

    assert response.json()["trace_id"] == "tr_client_001"
    assert response.headers["X-Trace-Id"] == "tr_client_001"


async def test_x_trace_id_sai_dinh_dang_thi_sinh_moi_chu_khong_loi(client, runtime, driver_client):
    """Header hỏng chỉ làm hỏng tương quan log, không đáng để hỏng cả request."""
    response = await client.get("/api/v1/vehicle/state", headers={"X-Trace-Id": "co khoang trang\nva newline"})

    assert response.status_code == 200
    assert response.json()["trace_id"].startswith("tr_")


async def test_tra_ve_state_theo_dung_vo_cua_api_spec(client, runtime, driver_client):
    response = await client.get("/api/v1/vehicle/state")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta", "trace_id", "schema_version"}
    assert body["schema_version"] == "1.0"
    assert "request_id" in body["meta"]

    state = body["data"]["vehicle_state"]
    assert state["vehicle_id"] == VEHICLE_ID
    # state_version không được flatten hay đổi tên — api_spec.md.
    assert "state_version" in state
    # 9 domain, và không có schema_version lẫn vào thân state.
    assert set(state) == {
        "vehicle_id",
        "state_version",
        "observed_at",
        "motion",
        "hvac",
        "windows",
        "doors",
        "media",
        "navigation",
        "seat",
        "lights",
        "trunk",
    }


async def test_state_cap_nhat_sau_khi_co_lenh(client, runtime, driver_client):
    backend, _broker, simulator, _clock = runtime

    await backend.executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 19},
        expected_state_version=simulator.state.state_version,
    )

    body = (await client.get("/api/v1/vehicle/state")).json()
    assert body["data"]["vehicle_state"]["hvac"]["temperature_c"] == 19


def test_ws_engineer_day_state_realtime():
    """WS phải bơm state hiện có ngay khi nối, không bắt client chờ đổi tiếp."""
    broker = InMemoryBroker()
    simulator = VehicleSimulator(VEHICLE_ID)
    backend = MqttRuntime(VEHICLE_ID)

    async def prepare():
        await backend.bind(broker, timeout_ms=500)
        # Nạp cache đúng như simulator vừa publish snapshot retained.
        await broker.publish(
            mqtt_topics.snapshot(VEHICLE_ID),
            VehicleStateSnapshot.of(simulator.snapshot()).model_dump(mode="json"),
            qos=1,
            retain=True,
        )

    anyio.run(prepare)

    with TestClient(app) as client:
        # Gán SAU khi lifespan chạy, nếu không sẽ bị lifespan ghi đè: lifespan
        # dựng cổng theo MQTT_ENABLED và VEHICLE_ID trong settings, tức một chiếc
        # xe khác chiếc mà test này dựng.
        app.state.mqtt = backend
        set_vehicle_gateway(MqttVehicleGateway(backend))
        with client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-03T02:00:00Z",
                    "schema_version": "1.0",
                }
            )
            event = ws.receive_json()

    assert event["type"] == "state"
    # Vỏ sự kiện theo api_spec.md "Server event base".
    assert set(event) >= {
        "type",
        "event_id",
        "sequence",
        "trace_id",
        "emitted_at",
        "schema_version",
        "payload",
    }
    assert event["sequence"] == 1
    assert event["payload"]["vehicle_state"]["vehicle_id"] == VEHICLE_ID


def test_ws_engineer_tu_choi_message_dau_khong_phai_connection_init():
    with TestClient(app) as client:
        app.state.mqtt = None
        with client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
            ws.send_json({"type": "khong_hop_le"})
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "WS_EVENT_INVALID"


def test_topic_helper_dung_tien_to_v1():
    assert mqtt_topics.commands(VEHICLE_ID, "hvac") == f"v1/vehicles/{VEHICLE_ID}/commands/hvac"
    assert mqtt_topics.snapshot(VEHICLE_ID) == f"v1/vehicles/{VEHICLE_ID}/state/snapshot"
    assert mqtt_topics.parse_command_domain(mqtt_topics.commands(VEHICLE_ID, "doors")) == "doors"
    assert mqtt_topics.parse_command_domain(f"v1/vehicles/{VEHICLE_ID}/commands/bla") is None
    assert mqtt_topics.parse_command_domain("vivi/vehicle/control") is None

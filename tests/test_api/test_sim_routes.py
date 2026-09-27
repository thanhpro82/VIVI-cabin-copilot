"""`POST /api/v1/sim/motion` — bàn đạo diễn kịch bản demo. ADR-024.

Route này **không** thuộc 14 interface P0, nên test ở đây không kiểm hợp đồng
công khai; nó kiểm bốn thứ khác, theo thứ tự quan trọng:

1. **Tắt là 404, không phải 403.** 403 xác nhận route có thật.
2. **Backend chỉ đưa tin.** Nó publish lên `v1/sim/`, không ghi `state/*` — nếu
   một ngày nào đó nó ghi thẳng state thì ADR-013 sập, và đó là thứ test này đỏ.
3. **Kiểm ở cả hai đầu.** Body sai dải thì 422 và **không** có message nào lên dây.
4. **Đi hết đường thì xe thật sự chạy** — POST → broker → xe ảo → `state/*` →
   `GET /vehicle/state`. Đây là ca duy nhất chứng minh kịch bản nghiệm thu số 4
   dựng được mà không cần stdin.
"""

from __future__ import annotations

import pytest

from src import mqtt_topics
from src.config import get_settings
from src.main import app
from src.services.mqtt_client import InMemoryBroker
from src.services.mqtt_runtime import MqttRuntime
from src.services.vehicle_gateway import MqttVehicleGateway, set_vehicle_gateway
from src.vehicle_sim.runtime import SimulatorRuntime
from src.vehicle_sim.state import VehicleSimulator
from tests.test_api.ws_helpers import DRIVER_CREDENTIALS

VEHICLE_ID = "vehicle-demo-01"
URL = "/api/v1/sim/motion"


@pytest.fixture
def bat_harness(monkeypatch):
    """Bật `SIM_CONTROL_ENABLED` cho cả tiến trình test.

    `get_settings` có `lru_cache`, nên đặt env thôi là chưa đủ — phải xoá cache ở
    **cả hai đầu**: một lần để bản mới được đọc, một lần lúc dọn để test sau không
    thừa hưởng một chiếc xe có bàn đạo diễn đang mở.
    """
    monkeypatch.setenv("SIM_CONTROL_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def chuoi_mqtt():
    """Backend + xe ảo trên broker giả, kênh harness bật ở phía xe.

    Dựng tay thay vì dùng `rig`: ca này cần `vehicle_id` **đúng bằng** giá trị
    trong settings (route đọc `settings.vehicle_id` để dựng topic), còn `rig`
    dùng `vehicle-test-01`.
    """
    broker = InMemoryBroker()
    simulator = VehicleSimulator(VEHICLE_ID)
    sim_runtime = SimulatorRuntime(
        simulator, broker, heartbeat_interval_s=3600, sim_control_enabled=True
    )
    await sim_runtime.start()

    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)
    app.state.mqtt = backend
    set_vehicle_gateway(MqttVehicleGateway(backend))

    yield broker, simulator
    await sim_runtime.stop()


async def _dang_nhap(client) -> None:
    from src.services.auth import get_auth_store

    record = get_auth_store().login(*DRIVER_CREDENTIALS)
    client.headers["Authorization"] = f"Bearer {record.token}"


def _messages_harness(broker: InMemoryBroker) -> list[dict]:
    return broker.published_on(mqtt_topics.sim_motion_set(VEHICLE_ID))


# -- 1. tắt nghĩa là không tồn tại ------------------------------------------


async def test_co_tat_thi_tra_404_khong_phai_403(client):
    """Mặc định tắt, và tắt thì không xác nhận sự tồn tại của route.

    Đăng nhập trước rồi mới gọi: nếu không, 401 của tầng auth sẽ che mất 404 và
    test vẫn xanh trong một thế giới mà cờ chẳng làm gì cả.
    """
    await _dang_nhap(client)

    response = await client.post(URL, json={"speed_kph": 45})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_chua_dang_nhap_thi_401_ke_ca_khi_co_bat(client, bat_harness):
    """Bề mặt harness không được rộng hơn phần còn lại của IVI."""
    response = await client.post(URL, json={"speed_kph": 45})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


# -- 2 & 3. backend chỉ đưa tin, và kiểm ở cả hai đầu -----------------------


async def test_gui_duoc_thi_publish_dung_topic_harness(client, bat_harness, chuoi_mqtt):
    """202 chứ không 200: xe đổi state bất đồng bộ, response không kiểm chứng nổi."""
    broker, _simulator = chuoi_mqtt
    await _dang_nhap(client)

    response = await client.post(URL, json={"speed_kph": 45, "gear": "D"})

    assert response.status_code == 202
    assert response.json() == {"accepted": True, "speed_kph": 45.0, "gear": "D"}

    messages = _messages_harness(broker)
    assert messages == [{"schema_version": "1.0", "speed_kph": 45.0, "gear": "D"}]


async def test_backend_khong_bao_gio_ghi_thang_state(client, bat_harness, chuoi_mqtt):
    """ADR-013 còn nguyên: mọi `state/*` trên dây đều do xe ảo publish.

    Cách kiểm: đếm message trên `state/*` **trước** khi xe ảo kịp phản ứng thì
    không làm được với `InMemoryBroker` (handler chạy đồng bộ ngay trong lời gọi
    publish). Nên kiểm thứ chắc chắn hơn: backend chỉ publish đúng **một** topic,
    và đó là topic harness.
    """
    broker, _simulator = chuoi_mqtt
    await _dang_nhap(client)
    truoc = len(broker.published)

    await client.post(URL, json={"speed_kph": 45, "gear": "D"})

    topic_moi = [topic for topic, *_ in broker.published[truoc:]]
    assert topic_moi[0] == mqtt_topics.sim_motion_set(VEHICLE_ID)
    # Phần còn lại là do xe ảo tự công bố — state/motion và state/snapshot.
    assert all(t.startswith(f"{mqtt_topics.PREFIX}/{VEHICLE_ID}/state/") for t in topic_moi[1:])


@pytest.mark.parametrize(
    "body",
    [
        {"speed_kph": 201},
        {"speed_kph": -1},
        {"speed_kph": 45, "gear": "X"},
        {"gear": "D"},
        {"speed_kph": 45, "tool": "set_door_state"},
    ],
)
async def test_body_sai_thi_422_va_khong_gui_gi_len_day(client, bat_harness, chuoi_mqtt, body):
    """Sai thì dừng ở route — không đẩy rác lên broker rồi để xe ảo dọn."""
    broker, simulator = chuoi_mqtt
    await _dang_nhap(client)

    response = await client.post(URL, json=body)

    assert response.status_code == 422
    assert _messages_harness(broker) == []
    assert simulator.state.motion.speed_kph == 0.0


async def test_khong_co_broker_thi_503_dung_tu_vung_cu(client, bat_harness):
    """Cùng `MQTT_UNAVAILABLE` + `broker_unreachable` mà `/vehicle/state` đã dùng.

    Client không phải học từ vựng thứ hai cho cùng một sự cố: kênh harness đi qua
    đúng broker ấy, không có broker thì không có đường nào tới xe.
    """
    app.state.mqtt = None
    await _dang_nhap(client)

    response = await client.post(URL, json={"speed_kph": 45})

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "MQTT_UNAVAILABLE"
    assert error["details"]["reason"] == "broker_unreachable"
    assert error["retryable"] is True


# -- 4. đi hết đường thì xe thật sự chạy ------------------------------------


async def test_di_het_duong_thi_vehicle_state_bao_xe_dang_chay(client, bat_harness, chuoi_mqtt):
    """Kịch bản nghiệm thu số 4 dựng được **mà không cần stdin** — lý do ADR-024 tồn tại.

    Đây là ca duy nhất chạy trọn chuỗi: POST → backend publish → xe ảo `set_motion()`
    → `state/motion` + snapshot → cache của backend → `GET /vehicle/state`.
    """
    _broker, simulator = chuoi_mqtt
    await _dang_nhap(client)

    await client.post(URL, json={"speed_kph": 45, "gear": "D"})

    assert (simulator.state.motion.speed_kph, simulator.state.motion.gear) == (45.0, "D")

    state = await client.get("/api/v1/vehicle/state")
    assert state.status_code == 200
    motion = state.json()["data"]["vehicle_state"]["motion"]
    assert motion["speed_kph"] == 45.0
    assert motion["gear"] == "D"

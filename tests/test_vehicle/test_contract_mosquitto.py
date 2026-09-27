"""Contract test chạy trên Mosquitto thật.

ADR-004: "Unit tests dùng in-memory adapter nhưng contract tests phải chạy
Mosquitto." Đây là phần chứng minh QoS/retain/LWT hoạt động đúng trên broker
thật, thứ mà InMemoryBroker chỉ mô phỏng.

Mặc định BỎ QUA. Phải bật tường minh vì CI chạy `pytest tests/` không lọc
marker, và dò TCP tới cổng 1883 cho kết quả không đáng tin trên Windows khi
Docker Desktop đang chạy. Chạy local:

    docker compose up -d mqtt
    $env:MQTT_CONTRACT_TESTS = "1"
    pytest tests/test_vehicle/test_contract_mosquitto.py -v
"""

from __future__ import annotations

import asyncio
import os

import pytest

from src import mqtt_topics
from src.config import get_settings
from src.models.vehicle import DOMAINS, Health, VehicleCommand, VehicleStateSnapshot, utc_now
from src.services.mqtt_client import AiomqttClient
from src.services.tool_executor import ToolExecutor
from src.services.vehicle_state import VehicleStateCache
from src.vehicle_sim.runtime import SimulatorRuntime, will_for
from src.vehicle_sim.state import VehicleSimulator

# Lấy cấu hình qua `get_settings()`, KHÔNG phải `os.getenv` trực tiếp.
#
# `os.getenv` chỉ thấy biến môi trường, không thấy `.env` — mà `.env` mới là nơi
# `scripts/bootstrap_mqtt_secrets.ps1` bảo người dùng ghi credential, và cũng là
# nơi `MQTT_HOST_PORT`/`MQTT_URL` được đổi khi máy đã có sẵn broker khác giữ cổng
# 1883 (đúng trường hợp `docker-compose.yml` mô tả). Hệ quả của bản cũ, gặp thật:
# nhóm test này nối **anonymous tới broker của người khác trên 1883**, rồi báo
# "ACL lỏng hơn spec" — đúng về broker đó, vô nghĩa về broker của repo. Sai theo
# kiểu nguy hiểm nhất: nếu broker lạ kia tình cờ dễ dãi thì test còn có thể XANH.
#
# `Settings` vẫn ưu tiên biến môi trường hơn `.env`, nên mọi cách override cũ
# không đổi.
_settings = get_settings()
MQTT_URL = _settings.mqtt_url
VEHICLE_ID = "vehicle-contract-01"
# Hai identity tách biệt — ACL cấm backend publish lên state/event/health và
# cấm simulator publish lên commands. Dùng nhầm credential thì message bị
# broker lặng lẽ chặn, đó chính là điều ACL phải làm.
BACKEND_USER = _settings.mqtt_backend_username or None
BACKEND_PASS = _settings.backend_password() or None
SIM_USER = _settings.mqtt_simulator_username or None
SIM_PASS = _settings.simulator_password() or None


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("MQTT_CONTRACT_TESTS") != "1",
        reason="cần broker thật — đặt MQTT_CONTRACT_TESTS=1 sau `docker compose up -d mqtt`",
    ),
]


def _backend_client(client_id: str, **kwargs) -> AiomqttClient:
    return AiomqttClient(
        MQTT_URL, client_id=client_id, username=BACKEND_USER, password=BACKEND_PASS, **kwargs
    )


def _simulator_client(client_id: str, **kwargs) -> AiomqttClient:
    return AiomqttClient(
        MQTT_URL, client_id=client_id, username=SIM_USER, password=SIM_PASS, **kwargs
    )


@pytest.fixture
async def live():
    """Simulator và backend, mỗi bên một kết nối thật tới broker."""
    sim_client = _simulator_client(
        f"sim-{VEHICLE_ID}", clean_session=False, will=will_for(VEHICLE_ID)
    )
    await sim_client.start()
    simulator = VehicleSimulator(VEHICLE_ID)
    sim_runtime = SimulatorRuntime(simulator, sim_client, heartbeat_interval_s=3600)
    await sim_runtime.start()

    backend_client = _backend_client("backend-contract", clean_session=True)
    await backend_client.start()
    executor = ToolExecutor(backend_client, VEHICLE_ID, timeout_ms=5000)
    await executor.attach()
    cache = VehicleStateCache(VEHICLE_ID)
    await cache.attach(backend_client)
    await asyncio.sleep(0.3)  # chờ retained message về

    yield simulator, executor, cache

    await sim_runtime.stop()
    await _clear_retained(sim_client, VEHICLE_ID)
    await sim_client.stop()
    await backend_client.stop()


async def _clear_retained(client: AiomqttClient, vehicle_id: str) -> None:
    """Xoá retained message của xe test.

    Broker bật `persistence true` nên retained message sống qua restart; không
    dọn thì mỗi lần chạy test lại để lại một xe ma trong cây topic.
    """
    topics = [mqtt_topics.health(vehicle_id), mqtt_topics.snapshot(vehicle_id)]
    topics += [mqtt_topics.domain_state(vehicle_id, d) for d in DOMAINS]
    for topic in topics:
        await client.publish(topic, None, qos=1, retain=True)
    await asyncio.sleep(0.2)


async def test_lenh_di_qua_broker_that_va_state_doi(live):
    simulator, executor, cache = live

    result = await executor.execute(
        plan_id="plan_contract",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 24},
        expected_state_version=simulator.state.state_version,
    )

    assert result.status == "completed"
    assert result.error_code is None
    await asyncio.sleep(0.3)
    assert cache.state is not None
    assert cache.state.hvac.temperature_c == 24


async def test_retained_snapshot_den_ngay_voi_subscriber_moi(live):
    simulator, executor, _cache = live
    await executor.execute(
        plan_id="plan_contract",
        step_id="step_2",
        tool="set_window_position",
        args={"window": "rear_left", "percent": 45},
        expected_state_version=simulator.state.state_version,
    )
    await asyncio.sleep(0.3)

    late_client = _backend_client("backend-late", clean_session=True)
    await late_client.start()
    late_cache = VehicleStateCache(VEHICLE_ID)
    await late_cache.attach(late_client)
    await asyncio.sleep(0.5)

    try:
        assert late_cache.state is not None, "retain=true phải giao state ngay"
        assert late_cache.state.windows.rear_left == 45
        assert late_cache.simulator_ready() is True
    finally:
        await late_client.stop()


async def test_commands_khong_retained_tren_broker_that(live):
    """Subscriber mới nối vào topic lệnh không được nhận lại lệnh cũ."""
    simulator, executor, _cache = live
    await executor.execute(
        plan_id="plan_contract",
        step_id="step_3",
        tool="set_hvac_power",
        args={"enabled": False},
        expected_state_version=simulator.state.state_version,
    )
    await asyncio.sleep(0.3)

    received: list[dict] = []

    async def collect(_topic: str, payload: dict) -> None:
        received.append(payload)

    spy = _backend_client("spy-commands", clean_session=True)
    await spy.start()
    await spy.subscribe(mqtt_topics.commands_filter(VEHICLE_ID), collect)
    await asyncio.sleep(0.5)
    await spy.stop()

    assert received == [], "topic lệnh bị retain — simulator sẽ chạy lại lệnh cũ khi reconnect"


async def test_snapshot_tren_broker_that_validate_duoc_bang_schema(live):
    _simulator, _executor, _cache = live
    received: list[dict] = []

    async def collect(_topic: str, payload: dict) -> None:
        received.append(payload)

    spy = _backend_client("spy-snapshot", clean_session=True)
    await spy.start()
    await spy.subscribe(mqtt_topics.snapshot(VEHICLE_ID), collect)
    await asyncio.sleep(0.5)
    await spy.stop()

    assert received, "state/snapshot phải retained"
    snapshot = VehicleStateSnapshot.model_validate(received[-1])
    assert snapshot.vehicle_id == VEHICLE_ID


async def test_last_will_phat_khi_simulator_chet_dot_ngot():
    """Cắt kết nối không DISCONNECT — broker phải tự phát LWT."""
    victim_id = f"{VEHICLE_ID}-lwt"
    sim_client = _simulator_client(
        f"sim-{victim_id}", clean_session=False, will=will_for(victim_id), keepalive=5
    )
    await sim_client.start()
    runtime = SimulatorRuntime(
        VehicleSimulator(victim_id), sim_client, heartbeat_interval_s=3600
    )
    await runtime.start()
    await asyncio.sleep(0.3)

    watcher = _backend_client("watch-lwt", clean_session=True)
    await watcher.start()
    seen: list[dict] = []

    async def collect(_topic: str, payload: dict) -> None:
        seen.append(payload)

    await watcher.subscribe(mqtt_topics.health(victim_id), collect)
    await asyncio.sleep(0.3)
    assert seen and Health.model_validate(seen[-1]).online is True

    # Phải cắt socket chứ không dùng stop(): stop() đóng context sạch nên
    # aiomqtt gửi DISCONNECT, và DISCONNECT sạch làm broker HUỶ Will theo đúng
    # đặc tả MQTT. Chỉ mất kết nối bất thường mới kích hoạt LWT.
    await sim_client.simulate_connection_loss()
    for _ in range(40):
        await asyncio.sleep(0.5)
        if seen and Health.model_validate(seen[-1]).online is False:
            break

    try:
        health = Health.model_validate(seen[-1])
        assert health.online is False
        assert health.reason == "lwt"
    finally:
        # Phải dùng identity simulator: ACL cấm backend ghi lên state/health.
        cleaner = _simulator_client("sim-cleanup-lwt", clean_session=True)
        await cleaner.start()
        await _clear_retained(cleaner, victim_id)
        await cleaner.stop()
        await watcher.stop()


# ---------------------------------------------------------------------------
# Bổ sung: những thứ InMemoryBroker về nguyên tắc không mô phỏng được.
#
# Đã chạy thật trên Mosquitto 2 (eclipse-mosquitto:2) ngày 2026-08-09: 12/12 pass.
# Lần chạy đầu tiên bắt được hai lỗi trong chính nhóm test này — watcher của ACL
# bị đặt nhầm identity — chi tiết ở docstring của
# `test_acl_cam_backend_ghi_len_state`.
#
#     docker compose up -d mqtt
#     $env:MQTT_CONTRACT_TESTS = "1"
#     pytest tests/test_vehicle/test_contract_mosquitto.py -v
# ---------------------------------------------------------------------------


async def _collect(client: AiomqttClient, topic: str) -> list[dict]:
    """Thu message trên một topic; trả list tự lớn dần theo thời gian."""
    received: list[dict] = []

    async def handler(_topic: str, payload: dict) -> None:
        received.append(payload)

    await client.subscribe(topic, handler)
    await asyncio.sleep(0.3)
    return received


#: Xe riêng cho nhóm test ACL, để publish thử không đụng vào simulator của `live`.
ACL_VEHICLE_ID = f"{VEHICLE_ID}-acl"


async def test_acl_cam_backend_ghi_len_state():
    """Backend publish `state/snapshot` phải bị chặn.

    Mosquitto chặn **im lặng** — client không nhận được lỗi nào. Nên phải khẳng
    định gián tiếp: subscriber không thấy gì. Kèm **positive control** (đúng
    identity thì message tới nơi) để test không xanh chỉ vì subscribe hỏng.

    Chú ý identity của watcher: `config/mosquitto/acl` tách **read và write
    không giao nhau** — backend `write commands` + `read state`, simulator
    `read commands` + `write state`. Nghĩa là **không identity nào đọc lại được
    thứ chính nó ghi**. Nên watcher của `state/*` phải là *backend*, và watcher
    của `commands/*` phải là *simulator* — ngược với trực giác "ai ghi thì người
    đó xem". Đặt nhầm chỗ này thì positive control tắt và test đỏ mà không phải
    vì ACL sai.
    """
    topic = mqtt_topics.snapshot(ACL_VEHICLE_ID)

    watcher = _backend_client("watch-acl-state", clean_session=True)
    await watcher.start()
    intruder = _backend_client("intruder-state", clean_session=True)
    await intruder.start()
    publisher = _simulator_client("pub-acl-state", clean_session=True)
    await publisher.start()
    try:
        received = await _collect(watcher, topic)
        baseline = len(received)

        await intruder.publish(topic, {"schema_version": "1.0", "gia": "mao"}, qos=1)
        await asyncio.sleep(0.5)
        assert len(received) == baseline, "ACL đang cho backend ghi lên state/*"

        await publisher.publish(
            topic,
            VehicleStateSnapshot.of(VehicleSimulator(ACL_VEHICLE_ID).snapshot()).model_dump(
                mode="json"
            ),
            qos=1,
        )
        await asyncio.sleep(0.5)
        assert len(received) > baseline, "subscriber hỏng — khẳng định âm ở trên vô nghĩa"
    finally:
        await publisher.stop()
        await intruder.stop()
        await watcher.stop()


async def test_acl_cam_simulator_ghi_len_commands():
    """Chiều ngược lại: xe ảo không được tự ra lệnh cho chính nó.

    Watcher là *simulator* — chỉ identity đó mới `read commands`. Xem giải thích
    ở test trên.
    """
    topic = mqtt_topics.commands(ACL_VEHICLE_ID, "hvac")

    watcher = _simulator_client("watch-acl-cmd", clean_session=True)
    await watcher.start()
    intruder = _simulator_client("intruder-cmd", clean_session=True)
    await intruder.start()
    publisher = _backend_client("pub-acl-cmd", clean_session=True)
    await publisher.start()
    try:
        received = await _collect(watcher, topic)
        baseline = len(received)

        await intruder.publish(topic, {"tool": "set_hvac_power"}, qos=1)
        await asyncio.sleep(0.5)
        assert len(received) == baseline, "ACL đang cho simulator ghi lên commands/*"

        await publisher.publish(topic, {"tool": "set_hvac_power"}, qos=1)
        await asyncio.sleep(0.5)
        assert len(received) > baseline, "subscriber hỏng — khẳng định âm ở trên vô nghĩa"
    finally:
        await publisher.stop()
        await intruder.stop()
        await watcher.stop()


async def test_khong_identity_nao_doc_lai_duoc_thu_minh_ghi():
    """Tính chất mạnh hơn mà `mqtt_spec.md` không nói thẳng ra.

    ACL không chỉ ngăn ghi chéo — nó tách read/write **không giao nhau**, nên
    backend không subscribe nổi `commands/#` (thứ chính nó publish) và simulator
    không subscribe nổi `state/#`. Ghi lại thành test vì đây là ràng buộc thật sự
    tồn tại, và nó vừa làm hai test ở trên đỏ khi đặt nhầm identity.
    """
    command_topic = mqtt_topics.commands(ACL_VEHICLE_ID, "hvac")
    state_topic = mqtt_topics.snapshot(ACL_VEHICLE_ID)

    backend = _backend_client("selfread-backend", clean_session=True)
    await backend.start()
    simulator = _simulator_client("selfread-sim", clean_session=True)
    await simulator.start()
    try:
        backend_sees_commands = await _collect(backend, command_topic)
        simulator_sees_state = await _collect(simulator, state_topic)

        await backend.publish(command_topic, {"tool": "set_hvac_power"}, qos=1)
        await simulator.publish(
            state_topic,
            VehicleStateSnapshot.of(VehicleSimulator(ACL_VEHICLE_ID).snapshot()).model_dump(
                mode="json"
            ),
            qos=1,
        )
        await asyncio.sleep(0.6)

        assert backend_sees_commands == [], "backend đọc được commands/* — ACL lỏng hơn spec"
        assert simulator_sees_state == [], "simulator đọc được state/* — ACL lỏng hơn spec"
    finally:
        await simulator.stop()
        await backend.stop()


async def test_acl_kenh_harness_mot_chieu_backend_ghi_simulator_doc():
    """`v1/sim/+/motion/set`: backend ghi được, simulator thì không — ADR-024.

    Không có ca này thì một dòng ACL sai sẽ **không ai biết**: đường HTTP vẫn
    chạy đúng qua chính broker đang cấu hình sai, và `SpeedDebugDrawer` vẫn trả
    202 trong lúc xe không bao giờ nhúc nhích. Đây là lớp duy nhất chứng minh
    chiều của kênh này trên Mosquitto thật.

    Watcher là *simulator* — chỉ identity đó mới `read v1/sim/+/motion/set`, cùng
    lý do đã giải thích ở `test_acl_cam_backend_ghi_len_state`.
    """
    topic = mqtt_topics.sim_motion_set(ACL_VEHICLE_ID)
    payload = {"schema_version": "1.0", "speed_kph": 45, "gear": "D"}

    watcher = _simulator_client("watch-acl-sim", clean_session=True)
    await watcher.start()
    intruder = _simulator_client("intruder-sim", clean_session=True)
    await intruder.start()
    publisher = _backend_client("pub-acl-sim", clean_session=True)
    await publisher.start()
    try:
        received = await _collect(watcher, topic)
        baseline = len(received)

        # Chiều bị cấm: xe ảo không được tự nhắn cho chính nó chạy.
        await intruder.publish(topic, payload, qos=1)
        await asyncio.sleep(0.5)
        assert len(received) == baseline, "ACL đang cho simulator ghi lên v1/sim/*"

        # Positive control: đúng identity thì message tới nơi.
        await publisher.publish(topic, payload, qos=1)
        await asyncio.sleep(0.5)
        assert len(received) > baseline, "subscriber hỏng — khẳng định âm ở trên vô nghĩa"
    finally:
        await publisher.stop()
        await intruder.stop()
        await watcher.stop()


async def test_sai_password_thi_khong_noi_duoc():
    """`allow_anonymous false` + password_file: sai credential là không vào được."""
    bad = AiomqttClient(
        MQTT_URL, client_id="ke-la-mat", username="vivi-backend", password="sai-mat-khau"
    )
    with pytest.raises(Exception):  # noqa: B017, PT011 - kiểu lỗi tuỳ phiên bản aiomqtt
        await bad.start(wait=True, timeout=5.0)
    await bad.stop()


async def test_events_command_khong_bao_gio_retain(live):
    """Subscriber nối sau không được thấy lệnh cũ vọng lại."""
    simulator, executor, _cache = live
    await executor.execute(
        plan_id="plan_retain",
        step_id="step_1",
        tool="set_hvac_power",
        args={"enabled": True},
        expected_state_version=simulator.state.state_version,
    )
    await asyncio.sleep(0.3)

    late = _backend_client("late-events", clean_session=True)
    await late.start()
    try:
        assert await _collect(late, mqtt_topics.events_command(VEHICLE_ID)) == []
    finally:
        await late.stop()


async def test_duplicate_delivery_that_chi_tao_mot_transition(live):
    """Cùng payload lệnh publish hai lần trên broker thật → đúng một transition."""
    simulator, _executor, _cache = live
    version = simulator.state.state_version
    command = VehicleCommand(
        command_id="cmd_contract_dup_01",
        idempotency_key="plan_cdup:step_1",
        plan_id="plan_cdup",
        step_id="step_1",
        vehicle_id=VEHICLE_ID,
        expected_state_version=version,
        tool="set_window_position",
        args={"window": "front_left", "percent": 45},
        issued_at=utc_now(),
    )
    payload = command.model_dump(mode="json")
    topic = mqtt_topics.commands(VEHICLE_ID, "windows")

    issuer = _backend_client("dup-issuer", clean_session=True)
    await issuer.start()
    try:
        await issuer.publish(topic, payload, qos=1)
        await asyncio.sleep(0.5)
        await issuer.publish(topic, payload, qos=1)
        await asyncio.sleep(0.5)
    finally:
        await issuer.stop()

    assert simulator.state.windows.front_left == 45
    assert simulator.state.state_version == version + 1
    assert simulator.command_count == 1


async def test_sim_reconnect_van_nhan_lenh_gui_luc_dut_ket_noi():
    """Đây là lý do tồn tại của `clean_session=False`, và nó chưa từng được test.

    Simulator dùng client_id cố định và session bền, nên lệnh QoS 1 gửi trong lúc
    nó mất kết nối phải được broker giữ lại rồi giao khi nó nối lại.
    """
    vehicle_id = f"{VEHICLE_ID}-persist"
    simulator = VehicleSimulator(vehicle_id)
    client_id = f"sim-{vehicle_id}"

    sim_client = _simulator_client(client_id, clean_session=False)
    await sim_client.start()
    runtime = SimulatorRuntime(simulator, sim_client, heartbeat_interval_s=3600)
    await runtime.start()
    await asyncio.sleep(0.3)
    version = simulator.state.state_version

    await runtime.stop()
    await sim_client.stop()

    command = VehicleCommand(
        command_id="cmd_persist_01",
        idempotency_key="plan_persist:step_1",
        plan_id="plan_persist",
        step_id="step_1",
        vehicle_id=vehicle_id,
        expected_state_version=version,
        tool="set_hvac_temperature",
        args={"temperature_c": 20},
        issued_at=utc_now(),
    )
    issuer = _backend_client("persist-issuer", clean_session=True)
    await issuer.start()
    await issuer.publish(
        mqtt_topics.commands(vehicle_id, "hvac"), command.model_dump(mode="json"), qos=1
    )
    await asyncio.sleep(0.5)
    await issuer.stop()

    # Nối lại với CÙNG client_id và clean_session=False.
    revived_client = _simulator_client(client_id, clean_session=False)
    await revived_client.start()
    revived = SimulatorRuntime(simulator, revived_client, heartbeat_interval_s=3600)
    await revived.start()
    try:
        for _ in range(20):
            await asyncio.sleep(0.25)
            if simulator.state.hvac.temperature_c == 20:
                break
        assert simulator.state.hvac.temperature_c == 20, (
            "lệnh gửi lúc mất kết nối đã bị mất — clean_session=False không có tác dụng"
        )
    finally:
        await revived.stop()
        cleaner = _simulator_client("sim-cleanup-persist", clean_session=True)
        await cleaner.start()
        await _clear_retained(cleaner, vehicle_id)
        await cleaner.stop()
        await revived_client.stop()

"""Contract test cho `VehicleGateway` — chạy qua CẢ HAI implementation.

Giá trị của file này nằm ở chỗ nó parametrize: bản in-process và bản MQTT phải
cho **cùng** kết quả cho cùng đầu vào. Nếu chỉ test riêng từng bản thì hai bản sẽ
trôi xa nhau, và cái trôi sẽ chỉ lộ ra lúc demo — đúng lúc đường MQTT bật lên.
"""

from __future__ import annotations

import pytest

from src.services.mqtt_client import InMemoryBroker
from src.services.mqtt_runtime import MqttRuntime
from src.services.vehicle_gateway import (
    InProcessVehicleGateway,
    MotionInjectable,
    MqttVehicleGateway,
    VehicleGateway,
    snapshot_dict,
)
from src.vehicle_sim.runtime import SimulatorRuntime
from src.vehicle_sim.state import VehicleSimulator

VEHICLE_ID = "vehicle-test-01"


async def _in_process():
    gateway = InProcessVehicleGateway.new(VEHICLE_ID)
    yield gateway, gateway.simulator


async def _over_mqtt():
    broker = InMemoryBroker()
    simulator = VehicleSimulator(VEHICLE_ID)
    sim_runtime = SimulatorRuntime(simulator, broker, heartbeat_interval_s=3600)
    await sim_runtime.start()

    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)

    yield MqttVehicleGateway(backend), simulator
    await sim_runtime.stop()


@pytest.fixture(params=["in_process", "over_mqtt"])
async def gateway(request):
    """Trả `(gateway, simulator)`. Simulator lộ ra để khẳng định side effect thật."""
    builder = _in_process if request.param == "in_process" else _over_mqtt
    async for pair in builder():
        yield pair


async def test_ca_hai_ban_deu_thoa_protocol(gateway):
    port, _simulator = gateway

    assert isinstance(port, VehicleGateway)


async def test_lenh_hop_le_doi_state_va_tang_version(gateway):
    port, simulator = gateway
    before = simulator.state.state_version

    result = await port.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 19},
        expected_state_version=before,
    )

    assert result.status == "completed"
    assert result.error_code is None
    assert simulator.state.hvac.temperature_c == 19
    assert simulator.state.state_version == before + 1
    # Rolling version phải đọc được từ chính ToolResult, không phải từ cache —
    # đây là điều làm cho lệnh kế tiếp không dính stale_state.
    assert result.observed_state_version == before + 1


async def test_lenh_khong_doi_gi_thi_khong_tang_version(gateway):
    port, simulator = gateway
    before = simulator.state.state_version
    current = simulator.state.hvac.temperature_c

    result = await port.execute(
        plan_id="plan_noop",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": current},
        expected_state_version=before,
    )

    assert result.status == "completed"
    assert simulator.state.state_version == before


async def test_version_sai_thi_stale_state_va_khong_co_side_effect(gateway):
    port, simulator = gateway
    before_temp = simulator.state.hvac.temperature_c

    result = await port.execute(
        plan_id="plan_stale",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 30},
        expected_state_version=simulator.state.state_version + 99,
    )

    assert result.status == "rejected"
    assert result.error_code == "stale_state"
    assert simulator.state.hvac.temperature_c == before_temp


async def test_mo_cua_khi_xe_dang_chay_bi_chan_o_tang_simulator(gateway):
    """`safety_and_hitl.md` đòi policy và simulator kiểm ĐỘC LẬP.

    Test này cố ý bỏ qua policy và gọi thẳng cổng, để chứng minh lớp dưới cùng
    vẫn chặn ngay cả khi lớp trên vì lý do nào đó cho qua.
    """
    port, simulator = gateway
    simulator.state.motion.speed_kph = 45.0
    simulator.state.motion.gear = "D"

    result = await port.execute(
        plan_id="plan_unsafe",
        step_id="step_1",
        tool="set_door_state",
        args={"door": "front_left", "state": "open"},
        expected_state_version=simulator.state.state_version,
    )

    assert result.status == "rejected"
    assert result.error_code == "unsafe_vehicle_state"
    assert simulator.state.doors.front_left == "closed"


async def test_args_ngoai_dai_bi_tu_choi(gateway):
    port, simulator = gateway

    result = await port.execute(
        plan_id="plan_bad",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 99},
        expected_state_version=simulator.state.state_version,
    )

    assert result.status == "rejected"
    assert result.error_code == "invalid_arguments"


async def test_tool_ngoai_allowlist_bi_tu_choi(gateway):
    port, simulator = gateway

    result = await port.execute(
        plan_id="plan_unknown",
        step_id="step_1",
        tool="launch_rocket",
        args={},
        expected_state_version=simulator.state.state_version,
    )

    assert result.status == "rejected"
    assert result.error_code == "tool_not_allowed"


async def test_replay_cung_plan_step_khong_tao_transition_thu_hai(gateway):
    """Đây là bất biến quan trọng nhất của cổng.

    Gọi lại cùng `plan_id:step_id` phải trả nguyên kết quả cũ. Nếu nó thực thi
    lại, một lần retry ở tầng trên sẽ thành hai lần mở cửa sổ.
    """
    port, simulator = gateway
    version = simulator.state.state_version

    first = await port.execute(
        plan_id="plan_dup",
        step_id="step_1",
        tool="set_window_position",
        args={"window": "front_left", "percent": 30},
        expected_state_version=version,
    )
    count_after_first = simulator.command_count

    second = await port.execute(
        plan_id="plan_dup",
        step_id="step_1",
        tool="set_window_position",
        args={"window": "front_left", "percent": 30},
        expected_state_version=version,
    )

    assert second == first
    assert simulator.command_count == count_after_first
    assert simulator.state.state_version == version + 1


async def test_hai_lenh_lien_tiep_dung_rolling_version(gateway):
    """Chuỗi thật: lệnh 2 lấy version từ ToolResult của lệnh 1."""
    port, simulator = gateway

    first = await port.execute(
        plan_id="plan_seq",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 21},
        expected_state_version=simulator.state.state_version,
    )
    second = await port.execute(
        plan_id="plan_seq",
        step_id="step_2",
        tool="set_hvac_power",
        args={"enabled": False},
        expected_state_version=first.observed_state_version,
    )

    assert second.status == "completed"
    assert simulator.state.hvac.power is False


async def test_snapshot_tra_shape_canonical(gateway):
    port, _simulator = gateway

    state = await port.snapshot()
    payload = snapshot_dict(state)

    # Đúng 12 khoá của api_spec.md, không thừa không thiếu — đây là hợp đồng mà
    # GET /api/v1/vehicle/state và AgentState phải dùng chung.
    assert set(payload) == {
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
    assert payload["motion"]["speed_kph"] == 0.0
    assert payload["seat"]["front_left"]["heating"] == 0


async def test_listener_nhan_state_moi_sau_lenh(gateway):
    port, simulator = gateway
    seen: list[int] = []

    async def listener(state):
        seen.append(state.state_version)

    port.add_listener(listener)
    try:
        await port.execute(
            plan_id="plan_notify",
            step_id="step_1",
            tool="set_hvac_temperature",
            args={"temperature_c": 23},
            expected_state_version=simulator.state.state_version,
        )
    finally:
        port.remove_listener(listener)

    assert seen and seen[-1] == simulator.state.state_version


# -- khác biệt có chủ đích giữa hai bản -------------------------------------


async def test_chi_ban_in_process_dat_duoc_motion():
    """Dưới MQTT, `motion` là read-only và backend bị ACL cấm publish `state/*`.

    Nên năng lực này nằm ở một Protocol riêng. Test khẳng định sự bất đối xứng
    đó là *cố ý* — nếu ai đó thêm `set_motion` vào bản MQTT thì test này đỏ, và
    họ sẽ phải đọc lý do trước khi vi phạm ACL.
    """
    in_process = InProcessVehicleGateway.new(VEHICLE_ID)
    assert isinstance(in_process, MotionInjectable)

    broker = InMemoryBroker()
    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)
    assert not isinstance(MqttVehicleGateway(backend), MotionInjectable)


async def test_in_process_luon_ready_con_mqtt_thi_khong():
    """Bản in-process không có khái niệm mất kết nối; bản MQTT thì có."""
    assert InProcessVehicleGateway.new(VEHICLE_ID).readiness().ready is True

    broker = InMemoryBroker()
    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)
    readiness = MqttVehicleGateway(backend).readiness()

    assert readiness.ready is False
    assert readiness.reason == "no_health"


async def test_snapshot_tra_none_khi_xe_ao_chua_san_sang():
    """Lập kế hoạch mà không đọc được state thì phải trả None, không đoán bừa.

    Đoán `speed_kph=0` ở đây sẽ biến một lệnh mở cửa lẽ ra là S3 thành thẻ xác
    nhận S2 — đúng loại lỗi mà safety_and_hitl.md tồn tại để chặn.
    """
    broker = InMemoryBroker()
    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)
    port = MqttVehicleGateway(backend)

    assert await port.snapshot() is None


async def test_thay_gateway_thi_go_listener_cua_cai_cu():
    """Cache sống lâu hơn gateway, nên không gỡ là tích listener của xác chết.

    Do Nhân phát hiện khi review PR SCRUM-54/55: `__init__` đăng ký `_on_state`
    vào `runtime.cache` nhưng `reset_vehicle_gateway()` chỉ gán `_GATEWAY = None`.
    Production một runtime một tiến trình nên không lộ; test dựng nhiều gateway
    trên cùng runtime thì lộ.
    """
    from src.services.vehicle_gateway import (
        _LISTENER_FACTORIES,
        _PERSISTENT_LISTENERS,
        reset_vehicle_gateway,
        set_vehicle_gateway,
    )

    broker = InMemoryBroker()
    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)
    baseline = len(backend.cache._listeners)  # noqa: SLF001 — đếm rò thì phải nhìn vào trong
    # Từ pool xe (2026-08-23) có hai sổ: `_PERSISTENT_LISTENERS` cho listener dùng chung,
    # `_LISTENER_FACTORIES` cho listener phải có một instance mỗi xe (`ui.policy` đã
    # chuyển sang sổ này). Đếm cả hai — test nói về chuyện TÍCH LUỸ, không về con số.
    # Từ PR #77, `set_vehicle_gateway` còn gắn lại listener mức ứng dụng
    # cho cổng mới, nên mỗi cổng sống đóng góp `1 + len(_PERSISTENT_LISTENERS)`. Đếm
    # động chứ không viết cứng "+2": thêm một listener ứng dụng nữa không được làm đỏ
    # một test vốn nói về chuyện **tích luỹ**, không về con số tuyệt đối.
    per_gateway = 1 + len(_PERSISTENT_LISTENERS) + len(_LISTENER_FACTORIES)  # noqa: SLF001 — xem trên

    try:
        for _ in range(3):
            set_vehicle_gateway(MqttVehicleGateway(backend))
        assert len(backend.cache._listeners) == baseline + per_gateway, (  # noqa: SLF001
            "ba lần thay cổng để lại listener của ba cổng — cổng cũ chưa được gỡ"
        )

        reset_vehicle_gateway()
        assert len(backend.cache._listeners) == baseline, "reset phải gỡ cả listener ứng dụng"  # noqa: SLF001
    finally:
        reset_vehicle_gateway()


async def test_close_goi_hai_lan_khong_no():
    """Idempotent — shutdown có thể chạy qua cả `set` lẫn `reset`."""
    broker = InMemoryBroker()
    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)
    gateway = MqttVehicleGateway(backend)

    gateway.close()
    gateway.close()

    assert gateway._on_state not in backend.cache._listeners  # noqa: SLF001


async def test_last_known_van_tra_state_cu_de_hien_thi():
    """Ngược lại với `snapshot()`: màn hình được phép hiển thị dữ liệu cũ."""
    broker = InMemoryBroker()
    simulator = VehicleSimulator(VEHICLE_ID)
    sim_runtime = SimulatorRuntime(simulator, broker, heartbeat_interval_s=3600)
    await sim_runtime.start()
    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(broker, timeout_ms=500)
    port = MqttVehicleGateway(backend)

    # Xe ảo chết: health online=false. snapshot() phải câm, last_known() thì không.
    await sim_runtime.stop()

    assert await port.snapshot() is None
    last = await port.last_known()
    assert last is not None
    assert last.vehicle_id == VEHICLE_ID


async def test_listener_muc_ung_dung_song_qua_moi_lan_thay_cong():
    """Cơ chế nằm dưới blocker của PR #77, khoá riêng khỏi triệu chứng `ui.policy`.

    `add_listener` gắn vào **một instance**. `main.py` phải đăng ký ở mức module (vì
    `ASGITransport` không chạy lifespan), nhưng `lifespan` lại `set_vehicle_gateway(...)`
    — nên listener nằm lại trên cổng đã bị bỏ và chết im ở runtime.

    Test này không nhắc tới `ui.policy`: nó khoá đúng hợp đồng "listener ứng dụng theo
    cổng đang dùng", để listener nào thêm sau cũng được bảo vệ sẵn.
    """
    from src.services.vehicle_gateway import (
        add_persistent_state_listener,
        get_vehicle_gateway,
        remove_persistent_state_listener,
        reset_vehicle_gateway,
        set_vehicle_gateway,
    )

    thay_doi: list[str] = []

    async def listener(state) -> None:
        thay_doi.append(state.vehicle_id)

    reset_vehicle_gateway()
    try:
        add_persistent_state_listener(listener)
        assert listener in get_vehicle_gateway()._listeners, "cổng dựng lười phải nhận listener"  # noqa: SLF001

        # Đúng thứ lifespan làm: thay hẳn cổng bằng một instance khác.
        moi = InProcessVehicleGateway.new(VEHICLE_ID)
        set_vehicle_gateway(moi)
        assert listener in moi._listeners, "thay cổng làm mất listener của ứng dụng"  # noqa: SLF001

        # Và nó phải chạy thật, không chỉ nằm trong danh sách.
        await moi.execute(
            plan_id="plan-1",
            step_id="step-1",
            tool="set_hvac_temperature",
            args={"temperature_c": 23},
            expected_state_version=moi.simulator.state.state_version,
        )
        assert thay_doi, "listener có trong danh sách nhưng không được gọi"

        # Reset rồi lấy cổng mới: vẫn phải còn (test dùng chung fixture reset mỗi case).
        reset_vehicle_gateway()
        assert listener in get_vehicle_gateway()._listeners  # noqa: SLF001
    finally:
        remove_persistent_state_listener(listener)
        reset_vehicle_gateway()

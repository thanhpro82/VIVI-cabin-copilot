"""Vòng tròn executor -> broker -> simulator -> executor.

Dùng InMemoryBroker theo ADR-004 ("unit tests dùng in-memory adapter"). Test
chạy Mosquitto thật nằm ở tests/test_vehicle/test_contract_mosquitto.py.
"""

from __future__ import annotations

import asyncio

import pytest

from src import mqtt_topics
from src.bounded_cache import BoundedCache
from src.models.vehicle import Health, VehicleStateSnapshot
from src.services.mqtt_client import InMemoryBroker
from src.services.tool_executor import ToolExecutor
from src.services.vehicle_state import VehicleStateCache
from src.vehicle_sim.runtime import SimulatorRuntime
from src.vehicle_sim.state import VehicleSimulator

VEHICLE_ID = "vehicle-test-01"


@pytest.fixture
async def wired():
    """Broker giả + simulator + executor + cache đã nối sẵn."""
    broker = InMemoryBroker()
    simulator = VehicleSimulator(VEHICLE_ID)
    runtime = SimulatorRuntime(simulator, broker, heartbeat_interval_s=3600)
    await runtime.start()

    executor = ToolExecutor(broker, VEHICLE_ID, timeout_ms=500)
    await executor.attach()

    cache = VehicleStateCache(VEHICLE_ID)
    await cache.attach(broker)

    yield broker, simulator, executor, cache
    await runtime.stop()


async def test_publish_len_topic_dung_va_nhan_ve_completed(wired):
    broker, simulator, executor, _ = wired

    result = await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 24},
        expected_state_version=simulator.state.state_version,
    )

    assert result.status == "completed"
    assert result.attempt_count == 1
    assert simulator.state.hvac.temperature_c == 24
    # Lệnh phải đi đúng topic domain hvac, không phải topic nào khác.
    assert broker.published_on(mqtt_topics.commands(VEHICLE_ID, "hvac"))


async def test_state_snapshot_va_domain_state_deu_retained(wired):
    broker, simulator, executor, _ = wired

    await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_window_position",
        args={"window": "front_left", "percent": 60},
        expected_state_version=simulator.state.state_version,
    )

    snapshot = broker.retained(mqtt_topics.snapshot(VEHICLE_ID))
    domain = broker.retained(mqtt_topics.domain_state(VEHICLE_ID, "windows"))

    assert snapshot is not None and domain is not None
    assert snapshot["windows"]["front_left"] == 60
    assert domain["state"]["front_left"] == 60
    assert domain["status"] == "available"


async def test_commands_khong_bao_gio_retain(wired):
    """Retain trên command topic sẽ khiến simulator thực thi lại lệnh cũ."""
    broker, simulator, executor, _ = wired

    await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_power",
        args={"enabled": False},
        expected_state_version=simulator.state.state_version,
    )

    for topic, _payload, _qos, retain in broker.published:
        if "/commands/" in topic:
            assert retain is False, f"{topic} bị retain — lệnh cũ sẽ chạy lại khi reconnect"


async def test_cache_nhan_state_ngay_khi_noi_nho_retained(wired):
    """Subscriber nối sau vẫn đọc được state hiện tại, không phải chờ nhịp sau."""
    broker, simulator, executor, _ = wired

    await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 21},
        expected_state_version=simulator.state.state_version,
    )

    late = VehicleStateCache(VEHICLE_ID)
    await late.attach(broker)

    assert late.state is not None
    assert late.state.hvac.temperature_c == 21
    assert late.simulator_ready() is True


async def test_health_birth_retained_va_online(wired):
    broker, _simulator, _executor, cache = wired

    payload = broker.retained(mqtt_topics.health(VEHICLE_ID))

    assert payload is not None
    health = Health.model_validate(payload)
    assert health.online is True
    assert health.reason is None
    assert cache.simulator_ready() is True


async def test_shutdown_phat_health_offline_reason_shutdown():
    broker = InMemoryBroker()
    simulator = VehicleSimulator(VEHICLE_ID)
    runtime = SimulatorRuntime(simulator, broker, heartbeat_interval_s=3600)
    await runtime.start()

    await runtime.stop()

    health = Health.model_validate(broker.retained(mqtt_topics.health(VEHICLE_ID)))
    assert health.online is False
    assert health.reason == "shutdown"


async def test_lenh_bi_reject_khong_publish_state_moi(wired):
    broker, simulator, executor, _ = wired
    before = len(broker.published_on(mqtt_topics.snapshot(VEHICLE_ID)))

    result = await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 24},
        expected_state_version=999,  # sai version
    )

    assert result.status == "rejected"
    assert result.error_code == "stale_state"
    assert len(broker.published_on(mqtt_topics.snapshot(VEHICLE_ID))) == before


async def test_tool_ngoai_registry_khong_bao_gio_len_broker(wired):
    broker, _simulator, executor, _ = wired
    before = len(broker.published)

    result = await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="tu_pha_huy_xe",
        args={},
        expected_state_version=1,
    )

    assert result.status == "rejected"
    assert result.error_code == "tool_not_allowed"
    assert len(broker.published) == before, "tool lạ không được publish gì cả"


async def test_timeout_retry_dung_mot_lan_roi_bo_cuoc():
    """Không có simulator nghe -> hết retry -> đúng một terminal failed."""
    broker = InMemoryBroker()
    executor = ToolExecutor(broker, VEHICLE_ID, timeout_ms=50)
    await executor.attach()

    result = await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_power",
        args={"enabled": True},
        expected_state_version=1,
    )

    assert result.status == "failed"
    assert result.error_code == "mqtt_unavailable"
    assert result.attempt_count == 2  # lần đầu + đúng một retry

    commands = [t for t, _p, _q, _r in broker.published if "/commands/" in t]
    assert len(commands) == 2


async def test_executor_cache_ket_qua_co_tran(wired):
    """_results của executor phải có trần, không phình theo số lệnh đã chạy."""
    _broker, simulator, executor, _ = wired
    executor._results = BoundedCache(maxsize=2)

    for i in range(3):
        await executor.execute(
            plan_id="plan_1",
            step_id=f"step_{i}",
            tool="set_hvac_power",
            args={"enabled": i % 2 == 0},
            expected_state_version=simulator.state.state_version,
        )

    assert len(executor._results) == 2
    assert "plan_1:step_0" not in executor._results
    assert "plan_1:step_2" in executor._results


async def test_replay_cung_plan_step_tra_ket_qua_da_persist(wired):
    _broker, simulator, executor, _ = wired
    kwargs = dict(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 23},
        expected_state_version=simulator.state.state_version,
    )

    first = await executor.execute(**kwargs)
    second = await executor.execute(**kwargs)

    assert second.command_id == first.command_id
    assert simulator.command_count == 1


async def test_lenh_toi_sai_topic_domain_bi_tu_choi(wired):
    """Registry là server-owned; lệch topic/tool nghĩa là executor hỏng."""
    broker, simulator, _executor, _ = wired
    received: list[dict] = []
    await broker.subscribe(mqtt_topics.events_command(VEHICLE_ID), _collect(received))

    await broker.publish(
        mqtt_topics.commands(VEHICLE_ID, "media"),  # sai: tool thuộc domain hvac
        {
            "schema_version": "1.0",
            "command_id": "cmd_lech",
            "idempotency_key": "plan_1:step_1",
            "plan_id": "plan_1",
            "step_id": "step_1",
            "vehicle_id": VEHICLE_ID,
            "approval_id": None,
            "execution_group_id": None,
            "expected_state_version": simulator.state.state_version,
            "tool": "set_hvac_temperature",
            "args": {"temperature_c": 24},
            "issued_at": "2026-08-03T02:00:11Z",
        },
    )

    assert received[-1]["error_code"] == "tool_not_allowed"
    assert simulator.state.hvac.temperature_c == 27  # không đổi


def _collect(sink: list[dict]):
    async def handler(_topic: str, payload: dict) -> None:
        sink.append(payload)

    return handler


async def test_snapshot_khop_json_schema(wired):
    """Snapshot publish ra phải validate được bằng chính schema đã chốt."""
    broker, _simulator, _executor, _ = wired
    payload = broker.retained(mqtt_topics.snapshot(VEHICLE_ID))

    snapshot = VehicleStateSnapshot.model_validate(payload)

    assert snapshot.schema_version == "1.0"
    assert snapshot.vehicle_id == VEHICLE_ID
    # data.vehicle_state của REST phải bằng snapshot trừ schema_version.
    assert "schema_version" not in snapshot.to_state().model_dump()


async def test_hai_lenh_lien_tiep_dung_rolling_expected_version(wired):
    _broker, simulator, executor, _ = wired

    first = await executor.execute(
        plan_id="plan_1",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": 24},
        expected_state_version=simulator.state.state_version,
    )
    second = await executor.execute(
        plan_id="plan_1",
        step_id="step_2",
        tool="set_hvac_power",
        args={"enabled": False},
        expected_state_version=first.observed_state_version,
    )

    assert second.status == "completed"
    assert second.observed_state_version == first.observed_state_version + 1


async def test_publish_dong_thoi_nhieu_lenh_khong_lan_ket_qua(wired):
    """Mỗi waiter phải nhận đúng CommandEvent của command_id mình."""
    _broker, simulator, executor, _ = wired
    version = simulator.state.state_version

    # Chỉ lệnh đầu khớp version; hai lệnh sau chắc chắn stale. Điều được kiểm
    # ở đây là không có kết quả nào bị trả nhầm cho waiter khác.
    results = await asyncio.gather(
        executor.execute(
            plan_id="plan_1",
            step_id="step_a",
            tool="set_hvac_temperature",
            args={"temperature_c": 22},
            expected_state_version=version,
        ),
        executor.execute(
            plan_id="plan_1",
            step_id="step_b",
            tool="set_window_position",
            args={"window": "rear_left", "percent": 30},
            expected_state_version=version,
        ),
        executor.execute(
            plan_id="plan_1",
            step_id="step_c",
            tool="set_seat_heating",
            args={"seat": "front_right", "level": 1},
            expected_state_version=version,
        ),
    )

    assert {r.step_id for r in results} == {"step_a", "step_b", "step_c"}
    assert sum(r.status == "completed" for r in results) == 1


async def _wait_for_published_command(broker: InMemoryBroker, topic: str) -> dict:
    """Chờ executor publish lệnh lên `topic` rồi trả về payload.

    Không sleep theo thời gian thực: chỉ nhường control cho executor chạy tới chỗ
    `await self.mqtt.publish(...)` trong `_publish_and_wait`.
    """
    for _ in range(100):
        published = broker.published_on(topic)
        if published:
            return published[0]
        await asyncio.sleep(0)
    raise AssertionError(f"executor không publish lệnh nào lên {topic}")


def _command_event(command: dict, *, phase: str, observed_state_version: int) -> dict:
    """CommandEvent hợp lệ echo lại định danh từ `command`, xem docs/mqtt_spec.md."""
    return {
        "schema_version": "1.0",
        "event_id": f"evt_test_{phase}",
        "command_id": command["command_id"],
        "idempotency_key": command["idempotency_key"],
        "plan_id": command["plan_id"],
        "step_id": command["step_id"],
        "vehicle_id": command["vehicle_id"],
        "approval_id": None,
        "execution_group_id": None,
        "phase": phase,
        "status": "completed",
        "expected_state_version": command["expected_state_version"],
        "observed_state_version": observed_state_version,
        "before": {"temperature_c": 27},
        "after": {"temperature_c": 24},
        "error_code": None,
        "latency_ms": 1.0,
        "emitted_at": "2026-08-11T00:00:00Z",
    }


async def test_accepted_phase_khong_duoc_coi_la_ket_qua_cuoi():
    """`phase=accepted` là "đã nhận lệnh", không phải "đã đạt đích".

    Simulator P0 áp dụng tức thì nên chỉ phát `completed` — `docs/mqtt_spec.md` §phase
    và status cho phép tường minh điều đó. Nhưng `accepted` vẫn nằm trong enum để P1 mô
    phỏng độ trễ hội tụ mà không đổi hợp đồng (ADR-004), nên executor phải bỏ qua nó và
    chờ terminal event. Không có test này thì ngày ai đó thêm `accepted` vào simulator,
    lượt sẽ báo `completed` bằng dữ liệu của event *đầu tiên* — tức báo thành công cho
    một lệnh chưa chạy xong, đúng loại lỗi mà việc tách hai phase sinh ra để ngăn.
    """
    broker = InMemoryBroker()
    # timeout rộng: test này khẳng định executor CHỜ, nên không được để nó
    # thoát bằng đường timeout rồi vẫn xanh vì lý do sai.
    executor = ToolExecutor(broker, VEHICLE_ID, timeout_ms=5000)
    await executor.attach()

    task = asyncio.create_task(
        executor.execute(
            plan_id="plan_phase",
            step_id="step_1",
            tool="set_hvac_temperature",
            args={"temperature_c": 24},
            expected_state_version=41,
        )
    )
    command = await _wait_for_published_command(broker, mqtt_topics.commands(VEHICLE_ID, "hvac"))

    await broker.publish(
        mqtt_topics.events_command(VEHICLE_ID),
        _command_event(command, phase="accepted", observed_state_version=41),
    )
    for _ in range(10):
        await asyncio.sleep(0)
    assert not task.done(), "accepted đã resolve waiter — executor coi 'đã nhận' là 'đã xong'"

    await broker.publish(
        mqtt_topics.events_command(VEHICLE_ID),
        _command_event(command, phase="completed", observed_state_version=42),
    )
    result = await asyncio.wait_for(task, timeout=5)

    assert result.status == "completed"
    # 42 = của event completed. 41 nghĩa là ToolResult được dựng từ event accepted.
    assert result.observed_state_version == 42

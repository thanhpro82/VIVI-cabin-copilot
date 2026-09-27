"""Tầng L1 — AC3 phần idempotency: đúng một side effect cho mỗi lệnh.

Đây là nhóm bất biến đắt nhất nếu sai: một lệnh mở cửa sổ chạy hai lần thì người
dùng thấy kính tự động chạy tiếp sau khi họ đã dừng. Hệ thống có **hai** tầng
chống trùng, và chúng chặn hai thứ khác nhau:

- Simulator dedupe theo `command_id` → chặn *duplicate delivery* của QoS 1.
- Executor dedupe theo `plan_id:step_id` → chặn *replay ở mức kế hoạch*.

Cả hai đều là `BoundedCache` nên đều có thể bị evict. Điều làm cho chế độ hỏng
đó vẫn an toàn là `expected_state_version` — và hai test cuối file chứng minh
đúng chỗ ấy.
"""

from __future__ import annotations

import pytest

from src import mqtt_topics
from src.models.vehicle import VehicleCommand, utc_now
from tests.mqtt_rig import VEHICLE_ID, build_rig, teardown_rig


async def test_duplicate_delivery_qos1_chi_tao_mot_transition(rig):
    """Broker giao cùng một lệnh hai lần — kính chỉ được mở một lần.

    Publish thẳng cùng payload lên topic lệnh, mô phỏng đúng thứ QoS 1 cho phép
    xảy ra. Không đi qua executor vì executor sẽ tự dedupe trước và ta sẽ không
    kiểm được tầng simulator.
    """
    version = rig.version
    command = VehicleCommand(
        command_id="cmd_duplicate_0001",
        idempotency_key="plan_dup:step_1",
        plan_id="plan_dup",
        step_id="step_1",
        vehicle_id=VEHICLE_ID,
        expected_state_version=version,
        tool="set_window_position",
        args={"window": "front_left", "percent": 30},
        issued_at=utc_now(),
    )
    payload = command.model_dump(mode="json")
    topic = mqtt_topics.commands(VEHICLE_ID, "windows")
    snapshots_before = len(rig.snapshots_published())

    await rig.publish_raw(topic, payload)
    await rig.publish_raw(topic, payload)

    assert rig.simulator.state.windows.front_left == 30
    assert rig.version == version + 1, "lệnh trùng đã tạo transition thứ hai"
    assert rig.simulator.command_count == 1
    # Hai CommandEvent (executor phải nhận được cả hai để không treo), nhưng chỉ
    # MỘT snapshot mới — lần thứ hai là replay nên không có gì để công bố.
    assert len(rig.events_published()) == 2
    assert len(rig.snapshots_published()) == snapshots_before + 1


async def test_replay_cung_plan_step_tra_ket_qua_cu(rig):
    first = await rig.run("set_hvac_temperature", {"temperature_c": 22}, plan_id="plan_r")
    commands_after_first = len(rig.commands_published())

    second = await rig.run("set_hvac_temperature", {"temperature_c": 22}, plan_id="plan_r")

    assert second == first
    # Lần hai không được chạm tới broker.
    assert len(rig.commands_published()) == commands_after_first


@pytest.fixture
async def fast_rig(clock):
    """Rig với timeout ngắn — hai test dưới cố ý để executor hết giờ.

    100 ms chứ không nhỏ hơn: độ phân giải timer trên Windows khoảng 15,6 ms nên
    mốc dưới ~50 ms không đáng tin.
    """
    built = await build_rig(clock=clock, timeout_ms=100)
    yield built
    await teardown_rig(built)


async def test_retry_dung_mot_lan_va_giu_nguyen_command_id(fast_rig):
    """Timeout transport → retry đúng một lần, **cùng** `command_id`.

    Cùng `command_id` là điều kiện để simulator dedupe được nếu lần đầu thật ra
    đã tới nơi. Đổi id mỗi lần thử là biến retry thành nhân đôi lệnh.
    """
    version = fast_rig.version

    with fast_rig.swallow_command_events():
        result = await fast_rig.run(
            "set_hvac_power", {"enabled": False}, plan_id="plan_timeout"
        )

    assert result.status == "failed"
    assert result.error_code == "mqtt_unavailable"
    assert result.attempt_count == 2

    sent = [payload for _topic, payload, _qos, _retain in fast_rig.commands_published()]
    assert len(sent) == 2, "phải thử đúng hai lần: lần đầu + một retry"
    assert sent[0]["command_id"] == sent[1]["command_id"]
    assert sent[0]["idempotency_key"] == sent[1]["idempotency_key"] == "plan_timeout:step_1"

    # Điều quan trọng nhất của test này: lệnh ĐÃ chạy đúng MỘT lần dù executor
    # báo failed. "Mất phản hồi" không đồng nghĩa "chưa thực thi" — và chính vì
    # vậy retry buộc phải giữ nguyên command_id.
    assert fast_rig.simulator.state.hvac.power is False
    assert fast_rig.version == version + 1
    assert fast_rig.simulator.command_count == 1


async def test_chi_persist_dung_mot_terminal_result(fast_rig):
    """Hết retry rồi thì kết quả `failed` là chung thẩm, không thử lại nữa."""
    with fast_rig.swallow_command_events():
        first = await fast_rig.run(
            "set_hvac_power", {"enabled": False}, plan_id="plan_once"
        )
        commands_after_first = len(fast_rig.commands_published())
        second = await fast_rig.run(
            "set_hvac_power", {"enabled": False}, plan_id="plan_once"
        )

    assert first.status == "failed"
    assert second == first
    assert len(fast_rig.commands_published()) == commands_after_first


async def test_tool_ngoai_allowlist_khong_bao_gio_len_broker(rig):
    """Từ chối tại chỗ: không publish, không retry, không command_id thật."""
    before = len(rig.broker.published)

    result = await rig.run("launch_rocket", {})

    assert result.status == "rejected"
    assert result.error_code == "tool_not_allowed"
    assert result.command_id.startswith("cmd_local_")
    assert len(rig.broker.published) == before


async def test_args_sai_dai_khong_bao_gio_len_broker(rig):
    before = len(rig.broker.published)

    result = await rig.run("set_hvac_temperature", {"temperature_c": 99})

    assert result.status == "rejected"
    assert result.error_code == "invalid_arguments"
    assert len(rig.broker.published) == before


# -- chế độ hỏng khi cache bị evict ----------------------------------------


async def test_evict_phia_simulator_thi_version_check_chan_lai(rig):
    """Simulator quên `command_id` cũ → lệnh trùng chạy lại → bị `stale_state`.

    `docs/reviews/SCRUM-19-mqtt-code-review.md` nêu chế độ hỏng này nhưng chưa có
    test. Nó là lý do `expected_state_version` bắt buộc chứ không tuỳ chọn: khi
    tầng dedupe hết tác dụng thì đây là thứ duy nhất còn đứng giữa một lệnh trùng
    và một transition thứ hai.
    """
    version = rig.version
    command = VehicleCommand(
        command_id="cmd_evicted_0001",
        idempotency_key="plan_evict:step_1",
        plan_id="plan_evict",
        step_id="step_1",
        vehicle_id=VEHICLE_ID,
        expected_state_version=version,
        tool="set_window_position",
        args={"window": "rear_left", "percent": 55},
        issued_at=utc_now(),
    )
    payload = command.model_dump(mode="json")
    topic = mqtt_topics.commands(VEHICLE_ID, "windows")

    await rig.publish_raw(topic, payload)
    assert rig.simulator.state.windows.rear_left == 55

    # Mô phỏng entry bị đẩy khỏi BoundedCache.
    rig.simulator._results._items.clear()  # noqa: SLF001 — cố ý tái hiện eviction

    await rig.publish_raw(topic, payload)

    events = rig.events_published()
    assert events[-1]["status"] == "rejected"
    assert events[-1]["error_code"] == "stale_state"
    assert rig.version == version + 1, "transition thứ hai đã lọt"


async def test_evict_phia_executor_sinh_command_id_moi_nhung_van_an_toan(rig):
    """Executor quên `plan:step` → sinh `command_id` MỚI → simulator không dedupe được.

    Lúc đó chỉ còn version chặn. Test này khẳng định lớp cuối cùng ấy hoạt động.
    """
    version = rig.version
    first = await rig.run(
        "set_window_position", {"window": "rear_right", "percent": 20}, plan_id="plan_ev2"
    )
    assert first.status == "completed"

    rig.executor._results._items.clear()  # noqa: SLF001 — cố ý tái hiện eviction

    second = await rig.run(
        "set_window_position",
        {"window": "rear_right", "percent": 20},
        plan_id="plan_ev2",
        expected_state_version=version,  # plan cũ mang version cũ
    )

    assert second.command_id != first.command_id
    assert second.status == "rejected"
    assert second.error_code == "stale_state"
    assert rig.version == version + 1

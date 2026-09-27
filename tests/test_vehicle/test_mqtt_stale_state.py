"""Tầng L1 — AC3 phần stale state + state_version + phòng thủ payload hỏng.

Ba nhóm trong file này đều chưa từng có test:

1. **Bốn nhánh của `readiness()`** — trước đây chỉ nhánh `ready` được chạm tới,
   vì chứng minh hết hạn cần chờ 15 giây thật. `FakeClock` gỡ được ràng buộc đó.
2. **Heartbeat loop thật** — mọi test cũ đặt `heartbeat_interval_s=3600` để tắt
   nó, nên vòng lặp chưa bao giờ chạy trong test.
3. **Payload sai schema** — bốn chỗ trong code có nhánh `except ValidationError`
   nhưng chưa nhánh nào được chạy.
"""

from __future__ import annotations

import asyncio

import pytest

from src import mqtt_topics
from src.models.vehicle import VehicleStateSnapshot
from tests.mqtt_rig import VEHICLE_ID, build_rig, teardown_rig


def _health(*, online: bool, state_version: int = 1) -> dict:
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


# -- readiness: bốn nhánh ---------------------------------------------------


async def test_chua_nhan_health_nao_thi_no_health():
    """Khác `offline`: chưa nghe thấy gì thì có thể chỉ là vừa nối, đợi thêm."""
    from src.services.mqtt_client import InMemoryBroker
    from src.services.mqtt_runtime import MqttRuntime

    backend = MqttRuntime(VEHICLE_ID)
    await backend.bind(InMemoryBroker(), timeout_ms=500)

    readiness = backend.cache.readiness()

    assert readiness.ready is False
    assert readiness.reason == "no_health"
    assert readiness.online is None
    assert readiness.health_age_s is None


async def test_health_online_va_tuoi_thi_ready(rig):
    readiness = rig.cache.readiness()

    assert readiness.ready is True
    assert readiness.reason == "ready"
    assert readiness.online is True
    assert readiness.health_age_s == 0.0


async def test_lwt_bao_offline_thi_khong_ready_ngay(rig):
    """Last Will về là biết ngay, không phải chờ hết 15 giây."""
    await rig.publish_raw(mqtt_topics.health(VEHICLE_ID), _health(online=False), retain=True)

    readiness = rig.cache.readiness()

    assert readiness.ready is False
    assert readiness.reason == "offline"
    assert readiness.online is False


async def test_heartbeat_qua_han_thi_stale(rig):
    rig.clock.advance(15.001)

    readiness = rig.cache.readiness()

    assert readiness.ready is False
    assert readiness.reason == "heartbeat_stale"
    assert readiness.online is True
    assert readiness.health_age_s > 15.0


async def test_dung_mot_ngay_nguong_van_con_ready(rig):
    """Ngưỡng là `>` chứ không phải `>=` — đúng 15,000 giây vẫn tính là tươi."""
    rig.clock.advance(15.0)

    assert rig.cache.readiness().ready is True


async def test_hoi_phuc_sau_khi_stale(rig):
    """Hết hạn không phải trạng thái một chiều: heartbeat mới về là ready lại."""
    rig.clock.advance(20.0)
    assert rig.cache.readiness().ready is False

    await rig.publish_raw(
        mqtt_topics.health(VEHICLE_ID), _health(online=True, state_version=rig.version), retain=True
    )

    assert rig.cache.readiness().ready is True


async def test_heartbeat_loop_that_giu_cho_ready():
    """Vòng lặp heartbeat thật — trước file này nó chưa từng chạy trong test.

    Dùng `time.monotonic` thật (không truyền FakeClock) vì thứ đang kiểm là *có
    nhịp phát ra hay không*, và nhịp đó do `asyncio.sleep` trong simulator điều
    khiển. Ngưỡng stale đặt rộng (1 giây) so với nhịp (20 ms) nên không phụ thuộc
    độ chính xác của timer.
    """
    import time

    rig = await build_rig(
        clock=time.monotonic, heartbeat_interval_s=0.02, heartbeat_stale_s=1.0
    )
    try:
        first = rig.cache.health
        await asyncio.sleep(0.12)  # đủ cho vài nhịp

        assert rig.cache.readiness().ready is True
        assert first is not None
    finally:
        await teardown_rig(rig)


# -- state_version ----------------------------------------------------------


async def test_snapshot_lui_version_bi_bo_qua(rig):
    """Message tới trễ không được kéo lùi state — cache giữ bản mới hơn.

    Không có chốt này thì một retained message về muộn sau reconnect sẽ ghi đè
    trạng thái hiện tại bằng trạng thái cũ, và lệnh kế tiếp sẽ tính version sai.
    """
    await rig.run("set_hvac_temperature", {"temperature_c": 26})
    current = rig.cache.state
    assert current is not None

    stale = current.model_copy(deep=True)
    stale.state_version = current.state_version - 1
    stale.hvac.temperature_c = 16
    await rig.publish_raw(
        mqtt_topics.snapshot(VEHICLE_ID),
        VehicleStateSnapshot.of(stale).model_dump(mode="json"),
        retain=True,
    )

    assert rig.cache.state.hvac.temperature_c == 26
    assert rig.cache.state.state_version == current.state_version


async def test_cung_version_van_duoc_ghi_de(rig):
    """Chỉ chặn **lùi**, không chặn bằng — retained giao lại lúc reconnect phải qua."""
    await rig.run("set_hvac_temperature", {"temperature_c": 26})
    current = rig.cache.state
    assert current is not None

    same = current.model_copy(deep=True)
    same.hvac.temperature_c = 17
    await rig.publish_raw(
        mqtt_topics.snapshot(VEHICLE_ID),
        VehicleStateSnapshot.of(same).model_dump(mode="json"),
        retain=True,
    )

    assert rig.cache.state.hvac.temperature_c == 17


@pytest.mark.parametrize(
    ("tool", "args", "expect_bump"),
    [
        # Giá trị phải KHÁC mặc định của `initial_state`, nếu không đây là no-op
        # và test sẽ pass/fail vì lý do khác hẳn điều nó tuyên bố. Mặc định:
        # hvac 27 độ, windows 0%, media "paused".
        ("set_hvac_temperature", {"temperature_c": 22}, True),
        ("set_window_position", {"window": "front_left", "percent": 10}, True),
        ("media_control", {"action": "play"}, True),
        ("get_vehicle_state", {}, False),  # S0, không bao giờ lên MQTT
    ],
)
async def test_version_chi_tang_khi_co_thay_doi_that(rig, tool, args, expect_bump):
    before = rig.version

    await rig.run(tool, args)

    assert rig.version == (before + 1 if expect_bump else before)


async def test_lenh_lap_lai_gia_tri_cu_khong_tang_version(rig):
    """Lệnh 1 đổi thật (version tăng), lệnh 2 lặp lại giá trị đó (không tăng).

    Bước 1 phải thay đổi thật, nếu không thì cả hai bước đều là no-op và test
    xanh mà chẳng chứng minh được gì.
    """
    before = rig.version
    await rig.run("set_hvac_temperature", {"temperature_c": 22}, step_id="step_1")
    after_first = rig.version
    assert after_first == before + 1

    await rig.run("set_hvac_temperature", {"temperature_c": 22}, step_id="step_2")

    assert rig.version == after_first


# -- payload hỏng: bốn nhánh phòng thủ --------------------------------------


async def test_snapshot_sai_schema_bi_bo_qua_khong_lam_hong_cache(rig):
    await rig.run("set_hvac_temperature", {"temperature_c": 23})
    good = rig.cache.state

    await rig.publish_raw(mqtt_topics.snapshot(VEHICLE_ID), {"rac": "khong-phai-snapshot"})

    assert rig.cache.state == good


async def test_health_sai_schema_bi_bo_qua(rig):
    before = rig.cache.readiness()

    # online=true mà thiếu field bắt buộc — model_validator sẽ chặn.
    await rig.publish_raw(
        mqtt_topics.health(VEHICLE_ID), {"schema_version": "1.0", "vehicle_id": VEHICLE_ID, "online": True}
    )

    assert rig.cache.readiness().reason == before.reason


async def test_command_event_sai_schema_khong_lam_treo_executor(fast_rig_module):
    """Event rác không được đánh thức nhầm waiter, và cũng không được giết luồng."""
    await fast_rig_module.publish_raw(
        mqtt_topics.events_command(VEHICLE_ID), {"khong": "hop le"}
    )

    result = await fast_rig_module.run("set_hvac_temperature", {"temperature_c": 20})

    assert result.status == "completed"


async def test_lenh_sai_schema_toi_simulator_bi_tu_choi(rig):
    """Simulator phải sống sót qua payload rác trên topic lệnh."""
    before = rig.version

    await rig.publish_raw(mqtt_topics.commands(VEHICLE_ID, "hvac"), {"rac": True})

    assert rig.version == before
    # Và nó vẫn phục vụ lệnh hợp lệ ngay sau đó.
    assert (await rig.run("set_hvac_power", {"enabled": False})).status == "completed"


# -- điều khiển chuyển động từ trong tiến trình xe ảo ------------------------
#
# `motion` là read-only domain (không có topic lệnh) và ACL cấm backend publish
# `state/*`, nên đây là đường DUY NHẤT hợp lệ để cho xe chạy phục vụ demo S3.
# Xem ADR-013 và `src/vehicle_sim/__main__.py`.


async def test_set_motion_tang_version_va_publish_dung_hai_topic(rig):
    before = rig.version
    snapshots_before = len(rig.snapshots_published())

    changed = await rig.sim_runtime.set_motion(45.0)

    assert changed is True
    assert rig.simulator.state.motion.speed_kph == 45.0
    assert rig.simulator.state.motion.gear == "D", "tốc độ > 0 thì tự chuyển số D"
    assert rig.version == before + 1
    assert len(rig.snapshots_published()) == snapshots_before + 1
    # Backend thấy được thay đổi — tức demo S3 dùng được.
    assert rig.cache.state.motion.speed_kph == 45.0


async def test_set_motion_khong_doi_gi_thi_khong_tang_version(rig):
    await rig.sim_runtime.set_motion(30.0)
    after_first = rig.version

    changed = await rig.sim_runtime.set_motion(30.0, "D")

    assert changed is False
    assert rig.version == after_first


async def test_set_motion_giu_nguyen_gear_khi_duoc_chi_dinh(rig):
    """Nói rõ số thì không suy diễn — cần dựng được cả trạng thái vô lý để test."""
    await rig.sim_runtime.set_motion(20.0, "N")

    assert rig.simulator.state.motion.gear == "N"


async def test_xe_dang_chay_thi_mo_cua_bi_chan_o_tang_simulator(rig):
    """Đây là toàn bộ lý do `set_motion` tồn tại: demo S3 dưới MQTT."""
    await rig.sim_runtime.set_motion(45.0)

    result = await rig.run("set_door_state", {"door": "front_left", "state": "open"})

    assert result.status == "rejected"
    assert result.error_code == "unsafe_vehicle_state"
    assert rig.simulator.state.doors.front_left == "closed"


async def test_stop_dua_xe_ve_dung_yen_va_mo_cua_lai_duoc(rig):
    await rig.sim_runtime.set_motion(45.0)
    await rig.sim_runtime.set_motion(0.0, "P")

    result = await rig.run("set_door_state", {"door": "front_left", "state": "open"})

    assert result.status == "completed"


@pytest.fixture
async def fast_rig_module(clock):
    built = await build_rig(clock=clock, timeout_ms=200)
    yield built
    await teardown_rig(built)

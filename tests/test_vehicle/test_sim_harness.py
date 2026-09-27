"""Kênh harness `v1/sim/` phía xe ảo — ADR-024.

Ba mệnh đề mà mọi test ở đây phục vụ, xếp theo mức quan trọng:

1. **Tắt nghĩa là không tồn tại.** Cờ tắt thì xe ảo không subscribe, nên message
   gửi lên topic đó rơi vào hư không — khác hẳn "nghe rồi lặng lẽ bỏ qua".
2. **Kênh này không phải lệnh xe.** Nó không sinh `CommandEvent`, không đụng sổ
   chống lặp, không đi qua `simulator.execute()`. Nếu một ngày nào đó nó bắt đầu
   sinh event, executor sẽ nhận một event không tương quan với lệnh nào.
3. **Xe vẫn tự công bố state của chính nó.** `state_version` tăng đúng 1, và cả
   `state/motion` lẫn `state/snapshot` đều được publish bởi identity simulator —
   đó là toàn bộ lý do ADR-013 còn nguyên nghĩa sau ADR-024.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import mqtt_topics
from tests.mqtt_rig import VEHICLE_ID, build_rig, teardown_rig

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def harness_rig():
    """Giàn L1 với kênh harness **bật** — đời thật phải bật tường minh."""
    rig = await build_rig(sim_control_enabled=True)
    yield rig
    await teardown_rig(rig)


def _sim_topic() -> str:
    return mqtt_topics.sim_motion_set(VEHICLE_ID)


async def test_khi_tat_co_thi_xe_khong_nghe_topic_harness():
    """Mệnh đề 1: cờ tắt → không subscribe → message không đổi được gì.

    Đây là test giữ cho "mặc định tắt" là một sự thật vận hành chứ không phải một
    dòng trong `config.py`. Nếu ai đó chuyển sang "luôn subscribe rồi kiểm cờ
    trong handler", test này vẫn xanh — nên nó khẳng định **kết quả**, không
    khẳng định cách cài.
    """
    rig = await build_rig()  # mặc định: sim_control_enabled=False
    try:
        version_truoc = rig.version

        await rig.publish_raw(_sim_topic(), {"schema_version": "1.0", "speed_kph": 45})

        assert rig.simulator.state.motion.speed_kph == 0.0
        assert rig.simulator.state.motion.gear == "P"
        assert rig.version == version_truoc
    finally:
        await teardown_rig(rig)


async def test_message_hop_le_lam_xe_chay_va_tu_cong_bo(harness_rig):
    """Mệnh đề 3: version tăng đúng 1, và xe publish cả domain lẫn snapshot."""
    version_truoc = harness_rig.version
    snapshot_truoc = len(harness_rig.snapshots_published())

    await harness_rig.publish_raw(
        _sim_topic(), {"schema_version": "1.0", "speed_kph": 45, "gear": "D"}
    )

    motion = harness_rig.simulator.state.motion
    assert (motion.speed_kph, motion.gear) == (45.0, "D")
    assert harness_rig.version == version_truoc + 1
    assert len(harness_rig.snapshots_published()) == snapshot_truoc + 1
    assert mqtt_topics.domain_state(VEHICLE_ID, "motion") in harness_rig.published_topics()


async def test_khong_co_gear_thi_xe_tu_chon(harness_rig):
    """`gear` vắng mặt = "chọn hộ tôi", đúng quy ước console `speed 45`.

    Giữ cho thanh trượt trên màn và dòng gõ tay cho **cùng một** state — nếu
    không, hai đường vào cùng một method lại sinh ra hai kết quả khác nhau.
    """
    await harness_rig.publish_raw(_sim_topic(), {"schema_version": "1.0", "speed_kph": 45})
    assert harness_rig.simulator.state.motion.gear == "D"

    await harness_rig.publish_raw(_sim_topic(), {"schema_version": "1.0", "speed_kph": 0})
    assert harness_rig.simulator.state.motion.gear == "P"


async def test_dat_lai_dung_gia_tri_hien_tai_thi_khong_tang_version(harness_rig):
    """Không đổi thì không tăng version — hành vi sẵn có của `set_motion`, khoá lại.

    Quan trọng vì `SpeedDebugDrawer` poll và người dùng kéo thanh trượt: một chuỗi
    message trùng giá trị mà tăng version sẽ làm mọi `expected_state_version`
    đang chờ của HITL lệch, và một lượt S2 đang chờ duyệt sẽ hỏng vì lý do không
    ai nhìn thấy.
    """
    await harness_rig.publish_raw(
        _sim_topic(), {"schema_version": "1.0", "speed_kph": 45, "gear": "D"}
    )
    version_sau_lan_dau = harness_rig.version

    await harness_rig.publish_raw(
        _sim_topic(), {"schema_version": "1.0", "speed_kph": 45, "gear": "D"}
    )

    assert harness_rig.version == version_sau_lan_dau


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1.0", "speed_kph": 201},
        {"schema_version": "1.0", "speed_kph": -1},
        {"schema_version": "1.0", "speed_kph": 45, "gear": "X"},
        {"schema_version": "1.0"},
        {"schema_version": "1.0", "speed_kph": 45, "tool": "set_door_state"},
    ],
)
async def test_payload_sai_thi_xe_khong_doi_gi(harness_rig, payload):
    """Xe ảo tự validate, không tin route đã kiểm hộ.

    Route HTTP **không** phải đường duy nhất publish lên topic này: L2 contract
    test publish thẳng, và ai cầm credential backend cũng publish được. Ca cuối
    (`tool=...`) khoá mệnh đề 2 ở tầng payload — nhét tên tool vào đây không biến
    nó thành lệnh xe, nó chỉ là một field lạ và bị từ chối.
    """
    version_truoc = harness_rig.version

    await harness_rig.publish_raw(_sim_topic(), payload)

    assert harness_rig.simulator.state.motion.speed_kph == 0.0
    assert harness_rig.version == version_truoc


async def test_harness_khong_sinh_command_event(harness_rig):
    """Mệnh đề 2: không có `events/command` nào được phát.

    `ToolExecutor` tương quan sự kiện theo `command_id`. Một `CommandEvent` sinh
    ra từ kênh harness sẽ không ứng với lệnh nào đang chờ — tốt nhất là bị bỏ
    qua, tệ nhất là đóng nhầm một lệnh khác. Đường đúng là không sinh gì cả.
    """
    su_kien_truoc = len(harness_rig.events_published())

    await harness_rig.publish_raw(
        _sim_topic(), {"schema_version": "1.0", "speed_kph": 45, "gear": "D"}
    )

    assert len(harness_rig.events_published()) == su_kien_truoc


def test_acl_cap_dung_mot_topic_harness_khong_dung_wildcard():
    """ADR-024 mục 5, khoá ở tầng cấu hình.

    Kiểm **văn bản** ACL chứ không kiểm hành vi, và đó là lựa chọn có lý do: với
    ACL đúng, *không identity nào đọc được* `v1/sim/{id}/doors/set` — backend chỉ
    có `write`, simulator chỉ `read motion/set` — nên một test hành vi sẽ khẳng
    định "không ai thấy gì" trong một thế giới mà không ai **có thể** thấy gì.
    Nó sẽ xanh kể cả khi ACL đã mở toang. Đọc file là cách duy nhất trung thực.

    Cái được giữ: `topic write v1/sim/+/#` cho backend là lúc
    `v1/sim/{id}/doors/set` thành cửa hậu mở cửa xe vòng qua policy và HITL.
    """
    acl = (REPO_ROOT / "config" / "mosquitto" / "acl").read_text(encoding="utf-8")
    dong_sim = [
        dong.split("#", 1)[0].split()
        for dong in acl.splitlines()
        if "v1/sim" in dong and not dong.lstrip().startswith("#")
    ]

    assert dong_sim, "ACL không còn dòng nào cho v1/sim — kênh harness mất đường"
    for phan in dong_sim:
        assert phan[-1] == "v1/sim/+/motion/set", f"topic harness lạ trong ACL: {' '.join(phan)}"

    quyen = {(phan[1], phan[-1]) for phan in dong_sim}
    assert quyen == {("write", "v1/sim/+/motion/set"), ("read", "v1/sim/+/motion/set")}


async def test_topic_harness_khong_nam_trong_namespace_hop_dong_xe():
    """Ranh giới của ADR-024, khoá ở tầng chuỗi.

    Ca này rẻ đến mức trông thừa, nhưng nó là thứ duy nhất sẽ đỏ nếu ai đó "dọn
    dẹp" bằng cách gộp topic harness về `v1/vehicles/` cho gọn — mà đó chính là
    thay đổi khiến ACL `write v1/vehicles/+/commands/#` tự động mở cho nó.
    """
    topic = mqtt_topics.sim_motion_set(VEHICLE_ID)

    assert topic == f"v1/sim/{VEHICLE_ID}/motion/set"
    assert not topic.startswith(mqtt_topics.PREFIX)
    # Và nó không bao giờ được parse thành một domain lệnh hợp lệ.
    assert mqtt_topics.parse_command_domain(topic) is None

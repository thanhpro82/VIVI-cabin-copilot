"""Invariant của xe ảo.

Bốn test đầu là điều làm QoS 1 an toàn và làm optimistic concurrency đúng —
nếu chúng hỏng thì cả hợp đồng MQTT hỏng theo.
"""

from __future__ import annotations

import pytest

from src.bounded_cache import BoundedCache
from src.fixtures import load_media_fixture
from src.models.vehicle import VehicleCommand, utc_now
from src.vehicle_sim.state import (
    VehicleSimulator,
    default_playlist,
    initial_state,
)

VEHICLE_ID = "vehicle-test-01"


def _command(
    tool: str,
    args: dict,
    *,
    expected_state_version: int = 1,
    step_id: str = "step_1",
    command_id: str = "cmd_1",
) -> VehicleCommand:
    return VehicleCommand(
        command_id=command_id,
        idempotency_key=f"plan_1:{step_id}",
        plan_id="plan_1",
        step_id=step_id,
        vehicle_id=VEHICLE_ID,
        expected_state_version=expected_state_version,
        tool=tool,
        args=args,
        issued_at=utc_now(),
    )


@pytest.fixture
def sim() -> VehicleSimulator:
    return VehicleSimulator(VEHICLE_ID)


def test_accepted_transition_tang_state_version_dung_mot(sim):
    before = sim.state.state_version
    outcome = sim.execute(_command("set_hvac_temperature", {"temperature_c": 24}))

    assert outcome.event.status == "completed"
    assert outcome.event.error_code is None
    assert sim.state.state_version == before + 1
    assert sim.state.hvac.temperature_c == 24
    assert outcome.changed == ("hvac",)


def test_duplicate_command_id_khong_tao_transition_thu_hai(sim):
    """Duplicate delivery của QoS 1 phải trả nguyên kết quả cũ."""
    command = _command("set_hvac_temperature", {"temperature_c": 24})
    first = sim.execute(command)
    version_after_first = sim.state.state_version

    second = sim.execute(command)

    assert second.replayed is True
    assert second.event.event_id == first.event.event_id
    assert sim.state.state_version == version_after_first


def test_expected_state_version_sai_thi_stale_state_va_khong_doi_gi(sim):
    outcome = sim.execute(_command("set_hvac_temperature", {"temperature_c": 24}, expected_state_version=99))

    assert outcome.event.status == "rejected"
    assert outcome.event.error_code == "stale_state"
    assert outcome.changed == ()
    assert sim.state.state_version == 1
    assert sim.state.hvac.temperature_c == 27  # giá trị khởi tạo


def test_mo_cua_khi_xe_dang_chay_bi_chan(sim):
    sim.state.motion.speed_kph = 60
    sim.state.motion.gear = "D"

    outcome = sim.execute(_command("set_door_state", {"door": "front_left", "state": "open"}))

    assert outcome.event.status == "rejected"
    assert outcome.event.error_code == "unsafe_vehicle_state"
    assert sim.state.doors.front_left == "closed"


def test_dong_cua_khi_xe_dang_chay_cung_bi_chan(sim):
    """agent_spec.md xếp CẢ tool set_door_state xuống S3 khi xe chạy.

    Bản offline_poc chỉ chặn thao tác mở; ta theo spec, chặt hơn.
    """
    sim.state.doors.front_left = "open"
    sim.state.motion.speed_kph = 30
    sim.state.motion.gear = "D"

    outcome = sim.execute(_command("set_door_state", {"door": "front_left", "state": "closed"}))

    assert outcome.event.error_code == "unsafe_vehicle_state"


def test_mo_cua_khi_xe_dung_yen_thi_duoc(sim):
    outcome = sim.execute(_command("set_door_state", {"door": "rear_right", "state": "open"}))

    assert outcome.event.status == "completed"
    assert sim.state.doors.rear_right == "open"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("set_hvac_temperature", {"temperature_c": 35}),  # ngoài dải 16..30
        ("set_hvac_temperature", {"temperature_c": 10}),
        ("set_window_position", {"window": "front_left", "percent": 150}),
        ("set_seat_heating", {"seat": "front_left", "level": 9}),
        ("set_door_state", {"door": "khong_ton_tai", "state": "open"}),
        ("media_control", {"action": "play", "volume": 50}),  # volume bị cấm
        ("media_control", {"action": "set_volume"}),  # thiếu volume
        ("set_navigation", {"operation": "start"}),  # thiếu đích
        ("set_navigation", {"operation": "cancel", "destination_id": "poi_1"}),
    ],
)
def test_args_sai_tra_invalid_arguments(sim, tool, args):
    outcome = sim.execute(_command(tool, args))

    assert outcome.event.status == "rejected"
    assert outcome.event.error_code == "invalid_arguments"
    assert sim.state.state_version == 1


def test_tool_ngoai_registry_bi_tu_choi(sim):
    outcome = sim.execute(_command("tu_pha_huy_xe", {}))

    assert outcome.event.error_code == "tool_not_allowed"


def test_tool_s0_khong_duoc_nhan_qua_mqtt(sim):
    outcome = sim.execute(_command("query_manual", {"query": "cách bật điều hòa"}))

    assert outcome.event.error_code == "tool_not_allowed"


def test_lenh_hop_le_nhung_khong_doi_gi_thi_khong_tang_version(sim):
    """Đặt đúng giá trị đang có — completed nhưng state_version giữ nguyên."""
    outcome = sim.execute(_command("set_hvac_temperature", {"temperature_c": 27}))

    assert outcome.event.status == "completed"
    assert outcome.changed == ()
    assert sim.state.state_version == 1


def test_media_control_dung_field_volume(sim):
    """Registry định nghĩa `volume`; bản offline_poc đọc nhầm `value`."""
    outcome = sim.execute(_command("media_control", {"action": "set_volume", "volume": 80}))

    assert outcome.event.status == "completed"
    assert sim.state.media.volume == 80


def test_tat_tieng_khong_dung_toi_status_nen_nhac_van_chay(sim):
    """Bất biến mà cả quyết định của #320 dựa lên: mute **không** phải pause.

    `"tắt tiếng"` ra `set_volume: 0`, và câu hỏi đầu tiên người dùng hỏi khi nghe điều
    đó là *"vậy nhạc còn chạy không?"*. Còn — và nó phải còn, vì đó chính là thứ phân
    biệt `"tắt tiếng"` với `"tắt nhạc"`. Khoá ở đây chứ không chỉ ở router: router chỉ
    chứng minh được lệnh nào được dựng, không chứng minh được xe làm gì với nó.

    Chiều ngược cũng khoá: `pause` không được hạ âm lượng. Hai trường độc lập, và ngày
    ai đó gộp chúng lại cho "gọn" thì một trong hai câu nói sẽ làm sai việc.
    """
    def _buoc(args: dict, ten: str):
        return _command(
            "media_control",
            args,
            expected_state_version=sim.state.state_version,
            step_id=f"step_{ten}",
            command_id=f"cmd_{ten}",
        )

    sim.execute(_buoc({"action": "play"}, "play"))
    assert sim.state.media.status == "playing"

    outcome = sim.execute(_buoc({"action": "set_volume", "volume": 0}, "mute"))

    assert outcome.event.status == "completed"
    assert sim.state.media.volume == 0
    assert sim.state.media.status == "playing"

    sim.execute(_buoc({"action": "set_volume", "volume": 40}, "unmute"))
    sim.execute(_buoc({"action": "pause"}, "pause"))

    assert sim.state.media.status == "paused"
    assert sim.state.media.volume == 40


def test_navigation_start_roi_cancel(sim):
    sim.execute(
        _command(
            "set_navigation",
            {"operation": "start", "destination_id": "poi_1"},
            command_id="cmd_start",
        )
    )
    assert sim.state.navigation.status == "active"
    assert sim.state.navigation.destination_id == "poi_1"

    sim.execute(
        _command(
            "set_navigation",
            {"operation": "cancel"},
            expected_state_version=sim.state.state_version,
            step_id="step_2",
            command_id="cmd_cancel",
        )
    )
    assert sim.state.navigation.status == "idle"
    assert sim.state.navigation.destination_id is None


def test_hai_ghe_khong_dung_chung_object(sim):
    """pydantic KHÔNG copy model lồng nhau — dùng chung object là alias thật.

    Bug này từng có: initial_state truyền cùng một SingleSeatState cho cả hai
    ghế, nên chỉnh ghế trái đổi luôn ghế phải.
    """
    assert sim.state.seat.front_left is not sim.state.seat.front_right

    sim.state.seat.front_left.recline = 70

    assert sim.state.seat.front_right.recline == 50


def test_hai_simulator_khoi_tao_tu_cung_state_phai_doc_lap():
    """VehicleSimulator phải deep-copy state của caller, không giữ tham chiếu."""
    shared = initial_state(VEHICLE_ID)
    a = VehicleSimulator(VEHICLE_ID, shared)
    b = VehicleSimulator(VEHICLE_ID, shared)

    a.state.hvac.temperature_c = 20
    a.state.seat.front_left.heating = 3

    assert b.state.hvac.temperature_c == 27
    assert b.state.seat.front_left.heating == 0
    # Và object gốc của caller cũng không bị đụng tới.
    assert shared.hvac.temperature_c == 27


def test_cache_idempotency_co_tran_va_day_ra_ban_cu_nhat(sim):
    """_results phải có trần, nếu không process chạy lâu sẽ phình vô hạn."""
    sim._results = BoundedCache(maxsize=2)

    for i in range(3):
        sim.execute(
            _command(
                "set_hvac_power",
                {"enabled": i % 2 == 0},
                expected_state_version=sim.state.state_version,
                step_id=f"step_{i}",
                command_id=f"cmd_{i}",
            )
        )

    assert len(sim._results) == 2
    assert "cmd_0" not in sim._results  # cũ nhất bị đẩy ra
    assert "cmd_2" in sim._results


def test_trong_tran_thi_idempotency_van_nguyen_ven(sim):
    sim._results = BoundedCache(maxsize=8)
    command = _command("set_hvac_temperature", {"temperature_c": 24})

    first = sim.execute(command)
    version_after_first = sim.state.state_version
    second = sim.execute(command)

    assert second.replayed is True
    assert second.event.event_id == first.event.event_id
    assert sim.state.state_version == version_after_first


def test_seat_heating_va_seat_position_deu_ghi_vao_domain_seat(sim):
    sim.execute(_command("set_seat_heating", {"seat": "front_left", "level": 2}, command_id="cmd_a"))
    assert sim.state.seat.front_left.heating == 2

    sim.execute(
        _command(
            "set_seat_position",
            {"seat": "front_left", "axis": "recline", "value": 70},
            expected_state_version=sim.state.state_version,
            step_id="step_2",
            command_id="cmd_b",
        )
    )
    assert sim.state.seat.front_left.recline == 70
    # Ghế bên kia không bị đụng tới.
    assert sim.state.seat.front_right.recline == 50


def test_set_hvac_fan_level_doi_state_va_tang_version(sim):
    """`fan_level` từng là read-only (mqtt_spec.md "Quyết định P0 số 2").

    Issue #65 lật quyết định đó, nên xe ảo phải có nhánh `_apply` thật — thiếu nó
    thì lệnh tới nơi và rơi vào `internal_error`.
    """
    assert sim.state.hvac.fan_level == 3  # initial_state
    before = sim.state.state_version

    outcome = sim.execute(_command("set_hvac_fan_level", {"level": 1}))

    assert outcome.event.status == "completed"
    assert sim.state.hvac.fan_level == 1
    assert sim.state.state_version == before + 1
    assert outcome.changed == ("hvac",)


def test_set_hvac_fan_level_dat_lai_cung_gia_tri_khong_tang_version(sim):
    """Lệnh hợp lệ nhưng không đổi gì thì không được tăng `state_version`.

    Đây là bất biến chung của `docs/mqtt_spec.md`, không riêng gì quạt gió — tăng
    oan làm mọi `expected_state_version` đang chờ của lượt sau bị lệch.
    """
    sim.execute(_command("set_hvac_fan_level", {"level": 1}))
    after_first = sim.state.state_version

    outcome = sim.execute(
        _command(
            "set_hvac_fan_level",
            {"level": 1},
            expected_state_version=after_first,
            step_id="step_2",
            command_id="cmd_2",
        )
    )

    assert outcome.event.status == "completed"
    assert outcome.changed == ()
    assert sim.state.state_version == after_first


def test_set_hvac_fan_level_ngoai_dai_bi_tu_choi(sim):
    """Trần `le=3` phải chặn ở simulator, không tin executor đã validate."""
    outcome = sim.execute(_command("set_hvac_fan_level", {"level": 4}))

    assert outcome.event.status == "rejected"
    assert outcome.event.error_code == "invalid_arguments"
    assert sim.state.hvac.fan_level == 3


def test_set_trunk_state_bi_chan_khi_xe_dang_chay(sim):
    """Cốp chép nguyên quy tắc của cửa: `requires_stationary` -> `unsafe_vehicle_state`.

    Simulator kiểm **độc lập** với policy — `safety_and_hitl.md` đòi hai tầng kiểm,
    không đòi tầng này tin tầng kia.
    """
    sim.state.motion.speed_kph = 30
    sim.state.motion.gear = "D"

    outcome = sim.execute(_command("set_trunk_state", {"state": "open"}))

    assert outcome.event.status == "rejected"
    assert outcome.event.error_code == "unsafe_vehicle_state"
    assert sim.state.trunk.position == "closed"


def test_set_trunk_state_chay_duoc_khi_xe_dung_yen(sim):
    outcome = sim.execute(_command("set_trunk_state", {"state": "open"}))

    assert outcome.event.status == "completed"
    assert sim.state.trunk.position == "open"
    assert outcome.changed == ("trunk",)


@pytest.mark.parametrize("mode", ["low_beam", "high_beam", "auto"])
def test_set_headlight_mode_chay_duoc_ca_khi_xe_dang_chay(sim, mode):
    """Đèn là S1 nên simulator **không** được chặn theo trạng thái chuyển động.

    Đây là nửa còn lại của quyết định ở ADR-020: policy xếp S1 thì simulator cũng
    phải cho qua, nếu không hai tầng nói hai chuyện khác nhau.
    """
    sim.state.motion.speed_kph = 80
    sim.state.motion.gear = "D"

    outcome = sim.execute(_command("set_headlight_mode", {"mode": mode}))

    assert outcome.event.status == "completed"
    assert sim.state.lights.headlight == mode


def test_headlight_off_bi_tu_choi_o_tang_schema(sim):
    """`off` không nằm trong enum — UNECE R48. Simulator trả `invalid_arguments`."""
    outcome = sim.execute(_command("set_headlight_mode", {"mode": "off"}))

    assert outcome.event.status == "rejected"
    assert outcome.event.error_code == "invalid_arguments"
    assert sim.state.lights.headlight == "auto"


def test_set_interior_light(sim):
    outcome = sim.execute(_command("set_interior_light", {"enabled": True}))

    assert outcome.event.status == "completed"
    assert sim.state.lights.interior is True
    assert outcome.changed == ("lights",)


# ---- Playlist đọc từ fixture (issue #173) ---------------------------------


def test_playlist_lay_tu_fixture_chu_khong_hard_code():
    """Nửa backend của bất biến "một nguồn sự thật" cho tên bài.

    Nửa còn lại ở `frontend/src/lib/fixtures/media.ts`. Hai bên phải khớp vì
    `vehicleState.media.track` là **chuỗi tên bài** — IVI dùng chính chuỗi đó để
    tra ra file mp3 và ảnh bìa. Trước issue #173 đây là hai danh sách chép tay
    không trùng nhau một tên nào, nên mọi lượt tra đều trượt: UI đổi được chữ
    trong khi loa phát mãi một file.
    """
    assert default_playlist() == tuple(str(item["name"]) for item in load_media_fixture())
    assert VehicleSimulator(VEHICLE_ID)._playlist == list(default_playlist())


def test_di_het_mot_vong_ra_dung_so_bai_khac_nhau(sim):
    """Đi hết một vòng phải ra đủ số tên khác nhau, rồi quay đúng về bài đầu.

    Đọc số bài từ chính fixture chứ không viết cứng: playlist đã đổi từ 3 lên 6
    rồi xuống 5 (bỏ "Cipher") trong cùng một tuần, và một con số viết cứng ở đây
    sẽ đỏ vì lý do chẳng liên quan gì tới thứ test này bảo vệ.
    """
    songs = default_playlist()
    sim.execute(_command("media_control", {"action": "play"}, command_id="cmd_play"))
    seen = [sim.state.media.track]

    for index in range(1, len(songs) + 1):
        sim.execute(
            _command(
                "media_control",
                {"action": "next"},
                expected_state_version=sim.state.state_version,
                step_id=f"step_{index}",
                command_id=f"cmd_next_{index}",
            )
        )
        seen.append(sim.state.media.track)

    assert set(seen[: len(songs)]) == set(songs)
    assert seen[-1] == seen[0], "xoay hết một vòng phải quay về đúng bài đầu"


def test_previous_di_nguoc_dung_thu_tu_fixture(sim):
    """`previous` có route thật từ issue #65 — thứ tự lùi phải theo fixture."""
    songs = default_playlist()
    sim.execute(_command("media_control", {"action": "play"}, command_id="cmd_play"))
    assert sim.state.media.track == songs[0]

    sim.execute(
        _command(
            "media_control",
            {"action": "previous"},
            expected_state_version=sim.state.state_version,
            step_id="step_prev",
            command_id="cmd_prev",
        )
    )
    assert sim.state.media.track == songs[-1], "lùi từ bài đầu phải vòng về bài cuối"

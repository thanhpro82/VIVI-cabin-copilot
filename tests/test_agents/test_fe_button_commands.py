"""Mọi chuỗi lệnh nút bấm FE dựng ra phải khớp một luật router thật.

Đây là lớp lỗi đã cắn hai lần trong một ngày (2026-08-15) và cả hai lần đều lọt
qua toàn bộ test FE lẫn BE, vì không bên nào kiểm cái nối giữa hai bên:

- Nút "Khoá cửa lại" gửi `"khoá cửa"`, không khớp luật nào → rơi về tra sổ tay
  (ADR-011) → tài xế nhận "Tôi không tìm thấy thông tin này trong sổ tay xe."
  cho một nút điều khiển.
- Nút quạt gió gửi `"tăng quạt gió"` → `clarify/missing_fan_level`, bấm như không.

FE không import được router, router không biết FE gửi gì; chỗ duy nhất bắt được
là một bảng chép tay như dưới đây. Sửa chuỗi ở `VehicleControlView.tsx` /
`RightPanel.tsx` thì phải sửa cả đây — đó là chủ ý, không phải trùng lặp.
"""

import pytest

from src.agents.router import DeterministicControlRouter

router = DeterministicControlRouter()

#: (chuỗi FE gửi, tool mong đợi, tập args mong đợi) — args None nghĩa là không kiểm.
BUTTON_COMMANDS: list[tuple[str, str, dict | None]] = [
    # RightPanel — nút khoá cửa (fan-out cả 4 cửa, chỉ kiểm step đầu).
    ("mở khóa cửa", "set_door_state", None),
    ("đóng cửa", "set_door_state", None),
    # VehicleControlView — cửa theo từng vị trí.
    ("mở cửa bên lái", "set_door_state", {"door": "front_left", "state": "open"}),
    ("đóng cửa bên phụ", "set_door_state", {"door": "front_right", "state": "closed"}),
    ("mở cửa sau bên trái", "set_door_state", {"door": "rear_left", "state": "open"}),
    ("đóng cửa sau bên phải", "set_door_state", {"door": "rear_right", "state": "closed"}),
    # Cốp.
    ("mở cốp", "set_trunk_state", {"state": "open"}),
    ("đóng cốp", "set_trunk_state", {"state": "closed"}),
    # Điều hoà. "bật điều hòa N độ" ra 2 step (bật nguồn rồi đặt nhiệt) — xem
    # test_turning_on_ac_with_a_temperature_sets_both_power_and_temperature.
    ("tắt điều hòa", "set_hvac_power", {"enabled": False}),
    ("bật điều hòa 24 độ", "set_hvac_power", {"enabled": True}),
    # Quạt gió — FE tự tính mức rồi gửi tuyệt đối, cả hai đầu dải.
    ("đặt quạt gió mức 0", "set_hvac_fan_level", {"level": 0}),
    ("đặt quạt gió mức 3", "set_hvac_fan_level", {"level": 3}),
    # Đèn pha — đúng 3 chế độ trên UI (HEADLIGHT_COMMAND trong turn/types.ts).
    ("chuyển đèn sang chế độ tự động", "set_headlight_mode", {"mode": "auto"}),
    ("bật đèn chiếu gần", "set_headlight_mode", {"mode": "low_beam"}),
    ("bật đèn chiếu xa", "set_headlight_mode", {"mode": "high_beam"}),
    # Cửa sổ — kéo-thả gửi % tuyệt đối lúc thả tay.
    ("mở cửa sổ bên lái 60%", "set_window_position", {"window": "front_left", "percent": 60}),
    # Ghế. Chữ "chỉnh" ở đầu câu sưởi ghế là BẮT BUỘC: bỏ đi thì
    # `"sưởi ghế lái mức 2"` ra `not_control` và rơi về tra sổ tay.
    ("ngả ghế lái 40%", "set_seat_position", {"seat": "front_left", "axis": "recline", "value": 40}),
    ("chỉnh sưởi ghế lái mức 2", "set_seat_heating", {"seat": "front_left", "level": 2}),
]


@pytest.mark.parametrize(("text", "tool", "args"), BUTTON_COMMANDS)
def test_fe_button_command_reaches_the_intended_tool(text, tool, args):
    decision = router.route(text)

    assert decision.disposition == "control", (
        f"{text!r} -> {decision.disposition}/{decision.reason}; "
        "nút bấm mà không ra `control` nghĩa là tài xế bấm xong không có gì xảy ra"
    )
    assert decision.candidate_plan is not None
    step = decision.candidate_plan.steps[0]
    assert step.tool == tool
    if args is not None:
        assert step.args == args


def test_all_door_commands_fan_out_to_every_door():
    """Nút "toàn xe" dựa vào việc router tự nhân ra 4 step; mất tính chất này là
    nút chỉ tác động 1 cửa mà không ai nhận ra."""
    for text, state in (("mở khóa cửa", "open"), ("đóng cửa", "closed")):
        plan = router.route(text).candidate_plan
        assert plan is not None
        assert len(plan.steps) == 4, text
        assert {step.args["door"] for step in plan.steps} == {
            "front_left",
            "front_right",
            "rear_left",
            "rear_right",
        }
        assert all(step.args["state"] == state for step in plan.steps)


def test_turning_on_ac_with_a_temperature_sets_both_power_and_temperature():
    """Nút bật điều hoà gửi kèm nhiệt độ, và router tách thành 2 việc.

    Kiểm cả step thứ hai vì đó mới là phần người dùng thấy trên màn hình.
    """
    plan = router.route("bật điều hòa 24 độ").candidate_plan

    assert plan is not None
    assert [(step.tool, step.args) for step in plan.steps] == [
        ("set_hvac_power", {"enabled": True}),
        ("set_hvac_temperature", {"temperature_c": 24}),
    ]


@pytest.mark.parametrize(
    "text",
    ["khoá cửa", "khóa cửa", "tăng quạt gió", "giảm quạt gió"],
)
def test_the_strings_that_caused_the_bugs_still_do_not_work(text):
    """Chốt chặn hồi quy ngược: nếu ai đó "sửa" router để nhận luôn mấy chuỗi này
    thì bài test trên hết ý nghĩa, mà cách sửa đúng là FE gửi đúng câu.

    Giữ ở đây để lần sau đọc được vì sao FE không gửi mấy chuỗi trông tự nhiên hơn.

    Cả bốn chuỗi còn lại bị chặn vì **lý do nguyên tắc**, không phải vì router chưa
    kịp học: `khoá cửa` đòi một thao tác không có tool nào làm được (`DoorsState` chỉ
    có vị trí, không có khoá), còn `tăng/giảm quạt gió` là lượng **tương đối** mà
    router không tính được vì nó không đọc trạng thái xe. Nhận chúng nghĩa là đoán.
    """
    assert router.route(text).disposition != "control"


def test_suoi_ghe_khong_dong_tu_gio_da_chay_va_do_la_dung():
    """`"sưởi ghế lái mức 2"` **đã rời** danh sách trên ở PR 2a của issue #308.

    Nó nằm đó vì một lý do khác hẳn bốn chuỗi kia: hồi ấy `_match_seat_heating` đòi
    một động từ mở đầu mà `sưởi` không có trong tập, nên câu rơi xuống sổ tay. Đó là
    **giới hạn của router**, không phải một ranh giới an toàn — câu này nêu đủ cả vị
    trí lẫn mức tuyệt đối, có đúng một tool để gọi, và không phải đoán gì cả.

    FE vẫn gửi `"chỉnh sưởi ghế lái mức N"` (`VehicleControlView.tsx`) và chuỗi ấy vẫn
    khớp — bảng `BUTTON_COMMANDS` ở trên là chỗ khoá điều đó. Thay đổi này chỉ thôi
    **cấm** một cách nói mà con người dùng thật.
    """
    quyet_dinh = router.route("sưởi ghế lái mức 2")
    assert quyet_dinh.disposition == "control"
    plan = quyet_dinh.candidate_plan
    assert plan is not None
    assert [(b.tool, b.args) for b in plan.steps] == [
        ("set_seat_heating", {"seat": "front_left", "level": 2})
    ]

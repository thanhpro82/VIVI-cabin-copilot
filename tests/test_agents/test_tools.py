"""Schema tool là hàng rào đầu tiên: sai ở đây là VALIDATION_DENIED, chưa tới S0-S3."""

import pytest

from src.agents.contracts import ValidationDenied
from src.agents.tools import TOOL_ARGS, validate_args
from src.services.tool_registry import ACTUATOR_TOOLS, ToolNotAllowedError, get_spec, topic_for_tool


def test_registry_covers_exactly_the_allowlisted_tools():
    assert set(TOOL_ARGS) == {
        "get_vehicle_state",
        "set_hvac_power",
        "set_hvac_temperature",
        "set_hvac_fan_level",
        "media_control",
        "set_window_position",
        "set_seat_heating",
        "set_seat_position",
        "set_navigation",
        "set_door_state",
        "set_trunk_state",
        "set_headlight_mode",
        "set_interior_light",
        "open_app",
        # #371: rời `KHONG_CHO_DUONG_PLAN` cùng lúc với executor thật của nó.
        "search_nearby_poi",
    }


def test_registry_exposes_no_alias_table():
    """WS4 chốt dùng `api_spec.md`, nên bảng alias Họ A không còn consumer.

    Một bộ tên end-to-end: tên trong `TOOL_ARGS` cũng là tên trong `ActionPlan`,
    trace và HTTP response. Test này khoá việc không ai vô tình thêm lại.
    """
    import src.agents.tools as tools

    assert not hasattr(tools, "ALIAS_BY_TOOL")


def test_unknown_tool_is_tool_not_allowed():
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args("set_engine_off", {})
    assert excinfo.value.subcode == "tool_not_allowed"


def test_extra_field_is_args_invalid():
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args("set_hvac_power", {"enabled": True, "turbo": True})
    assert excinfo.value.subcode == "args_invalid"


def test_out_of_range_is_range_invalid():
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args("set_hvac_temperature", {"temperature_c": 45})
    assert excinfo.value.subcode == "range_invalid"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("set_hvac_temperature", {"temperature_c": 22}),
        ("set_hvac_power", {"enabled": False}),
        ("media_control", {"action": "play"}),
        ("media_control", {"action": "set_volume", "volume": 40}),
        ("set_window_position", {"window": "rear_left", "percent": 100}),
        ("set_seat_heating", {"seat": "front_left", "level": 3}),
        ("set_seat_position", {"seat": "front_right", "axis": "recline", "value": 0}),
        ("set_navigation", {"operation": "start", "destination_id": "poi-cafe-01"}),
        ("set_navigation", {"operation": "cancel"}),
        ("set_door_state", {"door": "front_left", "state": "open"}),
        ("get_vehicle_state", {}),
    ],
)
def test_valid_args_pass(tool, args):
    assert validate_args(tool, args) is not None


def test_volume_required_only_for_set_volume():
    with pytest.raises(ValidationDenied):
        validate_args("media_control", {"action": "set_volume"})
    with pytest.raises(ValidationDenied):
        validate_args("media_control", {"action": "play", "volume": 40})


def test_navigation_destination_conditional():
    with pytest.raises(ValidationDenied):
        validate_args("set_navigation", {"operation": "start"})
    with pytest.raises(ValidationDenied):
        validate_args("set_navigation", {"operation": "start", "destination_id": "   "})
    with pytest.raises(ValidationDenied):
        validate_args("set_navigation", {"operation": "cancel", "destination_id": "poi-cafe-01"})


def test_destination_ref_is_rejected_because_poi_is_out_of_scope():
    """POI resolution nằm ngoài scope sprint (ADR-010). Từ chối rõ ràng, không im lặng."""
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args(
            "set_navigation",
            {"operation": "start", "destination_ref": {"from_step_id": "s0", "selection": "first"}},
        )
    assert excinfo.value.subcode == "args_invalid"


# ---- open_app: enum đóng, không domain (ADR-023) -----------------------------


def test_open_app_nhan_dung_ba_app():
    for app in ("youtube", "tiktok", "spotify"):
        assert validate_args("open_app", {"app": app}).app == app


def test_app_ngoai_enum_bi_chan_o_tang_validate_chu_khong_phai_tang_an_toan():
    """Phân biệt này quan trọng: app lạ dừng ở `validation_denied`, **không** phải S3.

    S3 nghĩa là "việc này nguy hiểm trong trạng thái xe hiện tại". App lạ thì không
    nguy hiểm — nó không hợp lệ. Gộp hai thứ vào một mã là làm hỏng cả trace lẫn câu
    trả lời cho tài xế. `CLAUDE.md` ghi rõ ranh giới ấy.
    """
    with pytest.raises(ValidationDenied):
        validate_args("open_app", {"app": "netflix"})


def test_open_app_khong_nhan_url():
    """"URL tuỳ ý" ngoài phạm vi P0 — schema đóng là chỗ nói ra điều đó."""
    with pytest.raises(ValidationDenied):
        validate_args("open_app", {"app": "youtube", "url": "https://example.com"})


def test_open_app_khong_bao_gio_publish_mqtt():
    """`domain=None` nên nó không nằm trong `ACTUATOR_TOOLS` và không có topic.

    Đưa lựa chọn app vào MQTT sẽ phải đẻ một domain cho thứ không phải trạng thái xe,
    làm hỏng ADR-013.
    """
    assert get_spec("open_app").domain is None
    assert "open_app" not in ACTUATOR_TOOLS
    with pytest.raises(ToolNotAllowedError):
        topic_for_tool("open_app", "veh-demo")


def test_open_app_doi_xe_dung_yen():
    """Cờ này là thứ `policy.classify` và simulator cùng đọc — xem test_policy."""
    assert get_spec("open_app").requires_stationary is True

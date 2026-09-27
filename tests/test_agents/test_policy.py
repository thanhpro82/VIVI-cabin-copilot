"""Bảng phân loại S0-S3 ánh xạ 1:1 với docs/safety_and_hitl.md mục Classification rules."""

import pytest

from src.agents.contracts import CandidateActionPlan, CandidateStep
from src.agents.policy import classify, materialize_action_plan, plan_digest
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict

STATIONARY = snapshot_dict(InProcessVehicleGateway.new().state)
MOVING = snapshot_dict(InProcessVehicleGateway.new(speed_kph=45.0, gear="D").state)
IN_GEAR_STOPPED = snapshot_dict(InProcessVehicleGateway.new(speed_kph=0.0, gear="D").state)


def _candidate(tool: str, args: dict) -> CandidateActionPlan:
    return CandidateActionPlan(steps=(CandidateStep(step_id="step-1", ordinal=0, tool=tool, args=args),))


@pytest.mark.parametrize("snapshot", [STATIONARY, MOVING])
def test_window_is_always_s2(snapshot):
    """safety_and_hitl.md Required safety test #12."""
    assert classify("set_window_position", snapshot) == "S2"


@pytest.mark.parametrize(
    "tool",
    [
        "set_hvac_power",
        "set_hvac_temperature",
        "set_hvac_fan_level",
        "set_seat_heating",
        "media_control",
        "set_navigation",
        "set_headlight_mode",
        "set_interior_light",
    ],
)
def test_s1_tools(tool):
    """safety_and_hitl.md Required safety test #13 và mục Classification rules."""
    assert classify(tool, STATIONARY) == "S1"


@pytest.mark.parametrize("snapshot", [STATIONARY, MOVING])
def test_fan_level_is_s1_even_while_moving(snapshot):
    """Quạt gió không đổi phân loại theo trạng thái xe.

    Nó không phải actuator có rủi ro cơ học như cửa hay ghế, nên không thuộc
    `_STATIONARY_ONLY_TOOLS`. Chỉnh quạt lúc đang lái là thao tác bình thường.
    """
    assert classify("set_hvac_fan_level", snapshot) == "S1"


def test_get_vehicle_state_is_s0():
    assert classify("get_vehicle_state", MOVING) == "S0"


@pytest.mark.parametrize("tool", ["set_door_state", "set_seat_position", "set_trunk_state"])
def test_door_and_seat_position_are_s2_only_when_stationary(tool):
    """safety_and_hitl.md Required safety test #6."""
    assert classify(tool, STATIONARY) == "S2"
    assert classify(tool, MOVING) == "S3"
    assert classify(tool, IN_GEAR_STOPPED) == "S3"


def test_materialize_sets_requires_approval_for_s2():
    plan = materialize_action_plan(
        _candidate("set_window_position", {"window": "front_left", "percent": 30}),
        STATIONARY,
        "ses-1",
        "veh-1",
    )
    assert plan.steps[0].safety_level == "S2"
    assert plan.requires_approval is True
    assert plan.vehicle_state_version == STATIONARY["state_version"]


def test_materialize_leaves_s1_without_approval():
    plan = materialize_action_plan(_candidate("set_hvac_power", {"enabled": True}), STATIONARY, "ses-1", "veh-1")
    assert plan.steps[0].safety_level == "S1"
    assert plan.requires_approval is False


def test_materialize_marks_s3_and_still_requires_no_approval():
    """S3 bị chặn ở node safety; approval không bao giờ được tạo cho nó."""
    plan = materialize_action_plan(
        _candidate("set_door_state", {"door": "front_left", "state": "open"}),
        MOVING,
        "ses-1",
        "veh-1",
    )
    assert plan.steps[0].safety_level == "S3"
    assert plan.requires_approval is False


def test_materialize_rejects_tool_outside_allowlist():
    with pytest.raises(ValueError, match="allowlist"):
        materialize_action_plan(_candidate("set_engine_off", {}), STATIONARY, "ses-1", "veh-1")


def test_plan_id_and_digest_are_stable_across_replay():
    args = {"window": "front_left", "percent": 30}
    first = materialize_action_plan(_candidate("set_window_position", args), STATIONARY, "ses-1", "veh-1")
    second = materialize_action_plan(_candidate("set_window_position", args), STATIONARY, "ses-1", "veh-1")
    assert first.plan_id == second.plan_id
    assert plan_digest(first) == plan_digest(second)


def test_digest_changes_when_args_change():
    base = materialize_action_plan(
        _candidate("set_window_position", {"window": "front_left", "percent": 30}),
        STATIONARY,
        "ses-1",
        "veh-1",
    )
    edited = materialize_action_plan(
        _candidate("set_window_position", {"window": "front_left", "percent": 80}),
        STATIONARY,
        "ses-1",
        "veh-1",
    )
    assert plan_digest(base) != plan_digest(edited)


@pytest.mark.parametrize("snapshot", [STATIONARY, MOVING])
@pytest.mark.parametrize("tool", ["set_headlight_mode", "set_interior_light"])
def test_lights_are_s1_even_while_moving(tool, snapshot):
    """Quyết định an toàn của ADR-020, không phải bỏ sót.

    Thao tác nguy hiểm với đèn là *tắt* đèn chiếu gần khi đang chạy đêm — nhưng
    `headlight` là enum chế độ **không có `off`** (UNECE R48 cấm chế độ tắt thủ công
    trên xe có DRL). Thao tác đó không tồn tại trong hợp đồng nên không có gì để chặn,
    và `classify()` giữ nguyên chữ ký `(tool, snapshot)`.

    Nếu ai đó thêm `off` vào enum thì test này phải đỏ — lúc đó bật và tắt hết đối
    xứng về rủi ro và toàn bộ lập luận sụp đổ.
    """
    assert classify(tool, snapshot) == "S1"


# --- Cong xac nhan theo NGUON GOC, truc giao voi S0-S3 (issue #144) ----------
#
# Thanh do that tren nhanh SLM: tai xe noi "Toi thay hoi nong, lam gi do di",
# planner de xuat `media_control(set_volume, 10)`. Hop schema, khong dung cua/kinh/ghe
# nen xep S1, va S1 thi CHAY THANG khong hoi. Xe chinh am luong roi bao "Da thuc hien".
#
# Cong an toan chan cai NGUY HIEM; no khong co cach nao biet cai VO NGHIA. Voi router
# luat thi khoang do khong ton tai — luat khong khop thi roi ve tra so tay. Planner SLM
# sinh duoc bat ky tool hop le nao, nen khoang "hop schema nhung sai y" moi mo ra.


def test_plan_do_slm_de_xuat_phai_xac_nhan_du_chi_la_s1():
    """Bất biến trung tâm của #144.

    `set_hvac_temperature` là S1 thật — nó không nguy hiểm. Nhưng khi plan đến từ SLM,
    ta không đủ tin là mình **hiểu đúng yêu cầu**, và đó là một trục khác.
    """
    plan = materialize_action_plan(
        _candidate("set_hvac_temperature", {"temperature_c": 22}),
        STATIONARY,
        "ses-1",
        "veh-1",
        route_source="slm",
    )

    assert [step.safety_level for step in plan.steps] == ["S1"], "mức an toàn mô tả HÀNH ĐỘNG, không đổi"
    assert plan.requires_approval is True, "nguồn gốc SLM thì phải hỏi"


def test_muc_an_toan_khong_bi_nang_len_s2():
    """Cố ý **không** nâng S1 thành S2.

    Làm thế là bắt taxonomy S0–S3 nói dối: chỉnh nhiệt độ thật sự không nguy hiểm, nó
    chỉ có thể *sai*. Và một khi S2 mang hai nghĩa ("nguy hiểm" lẫn "không chắc hiểu
    đúng") thì mọi lập luận an toàn dựa trên nó đều loãng đi — kể cả những lập luận đã
    viết trong `docs/safety_and_hitl.md`.
    """
    plan = materialize_action_plan(
        _candidate("set_hvac_fan_level", {"level": 2}), STATIONARY, "ses-1", "veh-1", route_source="slm"
    )

    assert all(step.safety_level == "S1" for step in plan.steps)


def test_plan_cua_router_luat_khong_bi_hoi_them():
    """Router luật có **độ tin cậy cấu trúc**: một luật đã khớp.

    Bắt nó hỏi lại nữa là thêm ma sát cho đúng đường đang chạy tốt, và làm hỏng chính
    thứ ADR-006/010 chọn nó vì.
    """
    for nguon in ("deterministic", ""):
        plan = materialize_action_plan(
            _candidate("set_hvac_temperature", {"temperature_c": 22}),
            STATIONARY,
            "ses-1",
            "veh-1",
            route_source=nguon,
        )
        assert plan.requires_approval is False, f"route_source={nguon!r} không được kéo theo xác nhận"


def test_s3_van_bi_chan_truoc_khong_bien_thanh_cau_hoi():
    """Nguồn gốc SLM **không** được biến một hành động bị cấm thành một câu hỏi.

    Cửa khi xe đang chạy là S3 — chặn trước HITL (`safety_and_hitl.md` #4). Nếu cổng
    nguồn gốc đẩy nó vào nhánh hỏi thì SLM vừa có được một đường vòng qua S3.
    """
    plan = materialize_action_plan(
        _candidate("set_door_state", {"door": "front_left", "state": "open"}),
        MOVING,
        "ses-1",
        "veh-1",
        route_source="slm",
    )

    assert any(step.safety_level == "S3" for step in plan.steps)


def test_plan_id_khong_doi_theo_nguon_goc():
    """`plan_id` là vân tay của **nội dung**, và branch HITL bind approval theo digest.

    Cho nguồn gốc chui vào định danh thì cùng một plan sẽ có hai id tuỳ ai đề xuất —
    phá đúng tính ổn định qua replay mà `materialize_action_plan` hứa.
    """
    a = materialize_action_plan(_candidate("set_hvac_temperature", {"temperature_c": 22}), STATIONARY, "ses-1", "veh-1")
    b = materialize_action_plan(
        _candidate("set_hvac_temperature", {"temperature_c": 22}),
        STATIONARY,
        "ses-1",
        "veh-1",
        route_source="slm",
    )

    assert a.plan_id == b.plan_id


# ---- open_app: S1 khi xe ở P, S3 khi không (ADR-023) -------------------------


def test_open_app_la_s1_khi_xe_dung_yen():
    """S1 chứ **không** S2: mở YouTube lúc xe đỗ không đáng một hộp thoại phê duyệt.

    Nghi thức rỗng làm tài xế bấm Đồng ý theo phản xạ, và làm yếu chính cơ chế HITL ở
    những chỗ nó thật sự cần.
    """
    assert classify("open_app", STATIONARY) == "S1"


def test_open_app_la_s1_chu_khong_s0():
    """S0 trong `safety_and_hitl.md` là **chỉ đọc** — `open_app` *làm* một việc.

    Xếp nó S0 là bắt taxonomy S0–S3 nói dối. Test này giữ nguyên phân biệt đó, vì bản
    khảo sát 17/08 từng đề xuất S0 và ai đó có thể quay lại đề xuất ấy.
    """
    assert classify("open_app", STATIONARY) != "S0"


@pytest.mark.parametrize("snapshot", [MOVING, IN_GEAR_STOPPED])
def test_open_app_bi_chan_s3_khi_xe_khong_o_so_p(snapshot):
    """Dùng lại đúng `is_stationary`, không đẻ ngưỡng tốc độ thứ hai.

    `IN_GEAR_STOPPED` (0 km/h nhưng số D) cũng phải S3 — chặt hơn "xe đang chuyển
    động", và đó là **chủ ý**: Android khoá video theo `DRIVING_STATE_PARKED` chứ không
    theo km/h. Nếu ai đó đổi luật thành `speed_kph > 0` thì đúng test này đỏ.
    """
    assert classify("open_app", snapshot) == "S3"


def test_open_app_khong_dung_nguong_speed_5_cua_vivi_api_spec():
    """`docs/VIVI_API_Spec.md` nói `speed_kph > 5`; ADR-010 đã bác và không cài nó.

    Ở 3 km/h, ngưỡng-5 sẽ cho phép mở video. Predicate canonical thì chặn.
    """
    duoi_nguong_5 = snapshot_dict(InProcessVehicleGateway.new(speed_kph=3.0, gear="D").state)
    assert classify("open_app", duoi_nguong_5) == "S3"

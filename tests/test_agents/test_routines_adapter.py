"""Routine đã resolve → `CandidateActionPlan`. Issue #288 (outcome #275, epic #270).

Ranh giới sở hữu của #288, chép lại vì nó quyết mọi thứ dưới đây: adapter **không**
gán safety, **không** authorize, **không** chạm DB. Nó chỉ dịch — và một phép dịch thì
phải kiểm được bằng cách so hai đầu.

Nguồn hình dạng đầu vào: `frontend/src/lib/services/routines/types.ts` (#271, Giáp).
Đó là contract duy nhất đang tồn tại cho `RoutineStep`; #282/#290 sẽ thay bằng bản BE,
và lúc ấy chỉ `_DICH` phải đổi.

Cái bẫy lớn nhất ở đây là **camelCase**: FE viết `frontLeft`, tool canonical đòi
`front_left`. Dịch sai thì args vẫn "hợp lệ trông như thật" cho tới lúc `validate_args`
từ chối — hoặc tệ hơn, khớp nhầm một enum khác. Nên mọi ca dưới đây đi qua đúng
`validate_args` của đường planner, không tự khẳng định bằng mắt.
"""

from __future__ import annotations

import pytest

from src.agents import routines as routines_module
from src.agents.contracts import CandidateActionPlan
from src.agents.routines import RoutineDichError, routine_thanh_candidate
from src.agents.tools import validate_args


def _plan(steps: list[dict]) -> CandidateActionPlan:
    return routine_thanh_candidate(steps)


@pytest.mark.parametrize(
    ("buoc", "mo_ta"),
    [
        ({"action": "hvac_power", "enabled": True}, "bật điều hòa"),
        ({"action": "navigation", "destination": "home"}, "dẫn đường tới Nhà"),
        ({"action": "navigation", "destination": "office"}, "dẫn đường tới Cơ quan"),
    ],
)
def test_mo_ta_preview_tu_buoc_da_luu_khong_can_resolve_dia_diem(buoc, mo_ta):
    """Nếu preview lỡ dùng adapter chạy thật, bước navigation chưa setup sẽ lỗi thay vì được xem."""
    assert routines_module.mo_ta_buoc_routine(buoc) == mo_ta


@pytest.mark.parametrize(
    "buoc",
    [
        {"action": "hvac_power", "enabled": True},
        {"action": "hvac_temperature", "temperatureC": 22},
        {"action": "hvac_fan_level", "level": 2},
        {"action": "media_control", "controlAction": "play"},
        {"action": "window_position", "window": "frontLeft", "percent": 30},
        {"action": "seat_heating", "seat": "frontRight", "level": 1},
        {"action": "seat_position", "seat": "frontLeft", "axis": "recline", "value": 60},
        {"action": "interior_light", "enabled": False},
    ],
    ids=lambda b: b["action"],
)
def test_moi_buoc_deu_qua_duoc_validate_args_cua_duong_planner(buoc):
    """Phép kiểm quan trọng nhất: adapter dịch ra thứ mà cổng kế tiếp nhận.

    Từng bước một chứ không gộp một Routine tám bước — bản đầu của test này gộp, và
    **trần 4 bước bắt được chính nó**. Gộp cũng làm mất thông tin: một ca đỏ sẽ không
    nói được bước nào hỏng.
    """
    plan = _plan([buoc])
    validate_args(plan.steps[0].tool, plan.steps[0].args)


def test_camel_case_cua_fe_thanh_snake_case_canonical():
    """`frontLeft` → `front_left`. Đây là chỗ dịch sai mà vẫn trông đúng."""
    plan = _plan([{"action": "window_position", "window": "rearRight", "percent": 100}])
    assert plan.steps[0].args == {"window": "rear_right", "percent": 100}


def test_thu_tu_buoc_duoc_giu_nguyen():
    """Routine là một CHUỖI: "bật điều hòa rồi mở nhạc" khác "mở nhạc rồi bật điều hòa"
    khi một bước hỏng giữa chừng (epic #270 chốt fail-fast)."""
    plan = _plan(
        [
            {"action": "interior_light", "enabled": True},
            {"action": "hvac_power", "enabled": True},
            {"action": "media_control", "controlAction": "next"},
        ]
    )
    assert [s.ordinal for s in plan.steps] == [0, 1, 2]
    assert [s.tool for s in plan.steps] == ["set_interior_light", "set_hvac_power", "media_control"]
    assert [s.step_id for s in plan.steps] == ["step-1", "step-2", "step-3"]


def test_candidate_khong_mang_truong_safety_nao():
    """Bất biến kiến trúc: chỉ `policy.py` gán `safety_level`. Adapter mà sinh ra nó là
    một đường vòng qua tầng an toàn."""
    plan = _plan([{"action": "hvac_power", "enabled": True}])
    assert not hasattr(plan.steps[0], "safety_level")
    assert "safety_level" not in plan.steps[0].model_dump()


def test_media_set_volume_mang_theo_volume():
    plan = _plan([{"action": "media_control", "controlAction": "set_volume", "volume": 20}])
    assert plan.steps[0].args == {"action": "set_volume", "volume": 20}
    validate_args(plan.steps[0].tool, plan.steps[0].args)


def test_media_khong_phai_set_volume_thi_khong_duoc_kem_volume():
    """`MediaControlArgs` cấm `volume` khi action khác `set_volume`. Nếu Routine lưu
    thừa field ấy thì adapter phải bỏ, chứ không đẩy xuống cho validator từ chối."""
    plan = _plan([{"action": "media_control", "controlAction": "play", "volume": 50}])
    assert plan.steps[0].args == {"action": "play"}
    validate_args(plan.steps[0].tool, plan.steps[0].args)


# --- Lỗi phải là lỗi CÓ CẤU TRÚC, và không có side effect ------------------------


def test_action_la_thi_bao_loi_co_cau_truc():
    with pytest.raises(RoutineDichError) as loi:
        _plan([{"action": "phong_thuy_cabin", "level": 9}])
    assert loi.value.ma == "action_khong_ho_tro"
    assert "phong_thuy_cabin" in str(loi.value)


def test_dan_duong_khong_co_dia_diem_thi_bao_loi_chu_khong_doan():
    """Không truyền `dia_diem` — đường của người chưa gán Nhà/Cơ quan.

    Trả lỗi có cấu trúc, KHÔNG đoán một `destination_id` nào đó: đoán ở đây là dẫn tài
    xế tới một chỗ họ không bảo, qua một tool S1 không ai duyệt.
    """
    with pytest.raises(RoutineDichError) as loi:
        _plan([{"action": "navigation", "destination": "home"}])
    assert loi.value.ma == "dia_diem_ca_nhan_chua_co"


def test_dan_duong_dich_duoc_khi_dia_diem_da_resolve():
    """#283: người gọi tra `user_places` rồi truyền ánh xạ đã kiểm hợp lệ vào."""
    plan = routine_thanh_candidate(
        [{"action": "navigation", "destination": "office"}],
        dia_diem={"office": "poi-work-01"},
    )

    assert plan.steps[0].tool == "set_navigation"
    assert plan.steps[0].args == {"operation": "start", "destination_id": "poi-work-01"}


def test_chi_gan_nhan_kia_thi_van_bao_loi():
    """Gán Cơ quan không làm cho bước dẫn đường **Nhà** chạy được — không có chuyện lấy
    tạm cái đã gán."""
    with pytest.raises(RoutineDichError) as loi:
        routine_thanh_candidate(
            [{"action": "navigation", "destination": "home"}],
            dia_diem={"office": "poi-work-01"},
        )
    assert loi.value.ma == "dia_diem_ca_nhan_chua_co"


def test_mot_buoc_hong_thi_khong_tra_ve_plan_mot_nua():
    """Fail-fast của epic nói về lúc **thực thi**. Lúc DỊCH thì khác: một Routine dịch
    được một nửa là một Routine khác với thứ người dùng lưu, nên không được im lặng
    giao nửa ấy đi tiếp."""
    with pytest.raises(RoutineDichError):
        _plan(
            [
                {"action": "hvac_power", "enabled": True},
                {"action": "navigation", "destination": "office"},
                {"action": "interior_light", "enabled": True},
            ]
        )


def test_routine_rong_khong_phai_plan_rong():
    """`CandidateActionPlan` với 0 bước sẽ đi tiếp qua safety rồi executor và "thành
    công" mà không làm gì — một lượt báo xong trong khi chưa làm gì cả."""
    with pytest.raises(RoutineDichError) as loi:
        _plan([])
    assert loi.value.ma == "routine_rong"


def test_qua_bon_buoc_bi_tu_choi():
    """Epic #270 chốt 1–4 hành động. Adapter là cổng cuối trước khi chuỗi ấy thành plan."""
    with pytest.raises(RoutineDichError) as loi:
        _plan([{"action": "hvac_power", "enabled": True}] * 5)
    assert loi.value.ma == "qua_nhieu_buoc"

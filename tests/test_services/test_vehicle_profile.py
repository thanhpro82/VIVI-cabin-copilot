"""`src/services/vehicle_profile.py` — tầng dưới route (issue #123).

Route đã có `Literal` của Pydantic chặn ở biên, nên bộ test này lo phần `Literal`
**không** chặn được: chuẩn hoá hoa/thường và khoảng trắng, và ranh giới giữa "chưa
biết" với "biết sai".
"""

import pytest

from src.db import get_connection
from src.services.vehicle_profile import (
    InvalidProfileValueError,
    get_vehicle_profile,
    set_vehicle_profile,
)

_VEHICLE = "vehicle-demo-01"


def test_xe_chua_khai_bao_tra_profile_rong_chu_khong_ném_lỗi():
    profile = get_vehicle_profile("xe-chua-tung-thay")
    assert profile.trim is None
    assert profile.battery is None
    assert profile.is_complete is False


def test_ghi_roi_doc_lai_giu_nguyen_gia_tri():
    set_vehicle_profile(_VEHICLE, trim="eco", battery="catl")
    profile = get_vehicle_profile(_VEHICLE)
    assert (profile.trim, profile.battery) == ("eco", "catl")
    assert profile.is_complete is True
    assert profile.updated_at is not None


@pytest.mark.parametrize(
    "trim,battery",
    [("ECO", "CATL"), ("  eco  ", " catl "), ("Eco", "Catl")],
)
def test_chuan_hoa_hoa_thuong_va_khoang_trang(trim, battery):
    """`Trim`/`Battery` bên `ap_suat_lop` là `Literal`, **không** ràng buộc lúc chạy.

    Để `"ECO"` lọt xuống thì `tra_ap_suat()` ném `ValueError` — cùng exception với
    "tổ hợp lạ thật", nên hai lớp lỗi khác hẳn nhau sẽ lẫn vào nhau ở chỗ bắt lỗi.
    Chặn tại ranh giới ghi để phía dưới không bao giờ thấy giá trị lệch.
    """
    profile = set_vehicle_profile(_VEHICLE, trim=trim, battery=battery)
    assert (profile.trim, profile.battery) == ("eco", "catl")


def test_chuoi_rong_doc_la_chua_biet_chu_khong_phai_gia_tri_la():
    """Form gửi `""` cho ô chưa chọn là chuyện thường; đó là "chưa biết", không phải lỗi."""
    profile = set_vehicle_profile(_VEHICLE, trim="", battery="   ")
    assert profile.trim is None
    assert profile.battery is None
    assert profile.is_complete is False


@pytest.mark.parametrize(
    "trim,battery,field",
    [("ultra", "catl", "trim"), ("eco", "lfp", "battery")],
)
def test_gia_tri_ngoai_tap_nem_loi_rieng(trim, battery, field):
    """Lớp riêng chứ không `ValueError` trần — route cần phân biệt nó với lỗi tra bảng."""
    with pytest.raises(InvalidProfileValueError) as exc:
        set_vehicle_profile(_VEHICLE, trim=trim, battery=battery)
    assert exc.value.field == field


def test_ghi_de_toan_bo_cap():
    """Không vá từng phần: `plus` + `battery` cũ sẽ là cấu hình chưa ai khai báo."""
    set_vehicle_profile(_VEHICLE, trim="eco", battery="catl")
    profile = set_vehicle_profile(_VEHICLE, trim="plus", battery=None)
    assert (profile.trim, profile.battery) == ("plus", None)
    assert profile.is_complete is False


def test_plus_van_doi_du_hai_truong_du_hai_loai_pin_cung_ket_qua():
    """`plus` cho cùng số với cả `sdi` lẫn `catl` (260/270) — vẫn không suy ra pin.

    Suy luận "trim này thì pin không quan trọng" là kiến thức về nội dung bảng rò rỉ
    ra ngoài bảng; sổ tay bản sau đổi số là nó sai âm thầm.
    """
    profile = set_vehicle_profile(_VEHICLE, trim="plus", battery=None)
    assert profile.is_complete is False


def test_khong_co_hang_mac_dinh_nao_trong_bang():
    """Bảng phải trống khi chưa ai ghi — một hàng seed sẵn là một mặc định trá hình."""
    rows = get_connection().execute("SELECT COUNT(*) FROM vehicle_profiles").fetchone()[0]
    assert rows == 0


def test_db_tu_choi_gia_tri_la_ke_ca_khi_ghi_thang_sql():
    """CHECK ở tầng dữ liệu: một hàng hỏng không thể tồn tại để rồi nổ lúc tra bảng."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        get_connection().execute(
            "INSERT INTO vehicle_profiles (vehicle_id, trim, battery, updated_at) VALUES (?,?,?,?)",
            ("xe-la", "ultra", "catl", "2026-08-15T00:00:00+00:00"),
        )

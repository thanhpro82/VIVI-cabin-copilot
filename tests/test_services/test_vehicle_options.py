"""Tầng lưu trang bị tuỳ chọn: ba trạng thái, ghi đè cả tập, và cổng loại trừ."""

from __future__ import annotations

import pytest

from src.services.vehicle_profile import (
    TrangBiKhongHopLeError,
    get_vehicle_options,
    reset,
    set_vehicle_options,
)


@pytest.fixture(autouse=True)
def _don():
    reset()
    yield
    reset()


def test_xe_chua_khai_gi_tra_dict_rong_chu_khong_nem():
    assert get_vehicle_options("veh-1") == {}


def test_khoa_vang_mat_khac_khoa_bang_false():
    """Đây là bất biến trung tâm của cả tính năng, nên nó có test riêng.

    `None` (chưa biết) và `False` (khai là không có) dẫn tới hai hành vi khác nhau ở
    composer: cái đầu đọc nguyên văn mệnh đề điều kiện của sổ tay, cái sau nói thẳng
    xe không có. Gộp hai thứ lại là nói sai về gần như mọi chiếc xe, vì "chưa biết" là
    trạng thái mặc định của mọi trường.
    """
    set_vehicle_options("veh-1", {"lop_du_phong": False})
    da_khai = get_vehicle_options("veh-1")
    assert da_khai.get("lop_du_phong") is False
    assert da_khai.get("massage_ghe") is None


def test_ghi_de_ca_tap_chu_khong_va_tung_khoa():
    """Khai lại là khai lại chiếc xe. Một `lop_du_phong` còn sót của xe trước phải mất.

    Đây đúng lớp lỗi mà PUT-thay-vì-PATCH của #123 đã chặn cho `trim`/`battery`.
    """
    set_vehicle_options("veh-1", {"lop_du_phong": True, "acc": True})
    set_vehicle_options("veh-1", {"acc": False})
    assert get_vehicle_options("veh-1") == {"acc": False}


def test_tap_rong_la_xoa_sach_khai_bao():
    set_vehicle_options("veh-1", {"acc": True})
    assert set_vehicle_options("veh-1", {}) == {}
    assert get_vehicle_options("veh-1") == {}


def test_hai_xe_khong_dam_vao_nhau():
    set_vehicle_options("veh-1", {"acc": True})
    set_vehicle_options("veh-2", {"acc": False})
    assert get_vehicle_options("veh-1") == {"acc": True}
    assert get_vehicle_options("veh-2") == {"acc": False}


def test_id_khong_co_trong_danh_muc_bi_tu_choi():
    with pytest.raises(TrangBiKhongHopLeError, match="không có trong danh mục"):
        set_vehicle_options("veh-1", {"ghe_bay_duoc": True})


def test_hai_trang_bi_loai_tru_nhau_khong_the_cung_co():
    with pytest.raises(TrangBiKhongHopLeError, match="loại trừ nhau"):
        set_vehicle_options("veh-1", {"lop_du_phong": True, "bo_bom_hoi": True})


def test_loai_tru_nhau_van_duoc_cung_khong_co():
    """Xe có thể chẳng có gì trong khoang sau cả; sổ tay không cấm điều đó."""
    assert set_vehicle_options("veh-1", {"lop_du_phong": False, "bo_bom_hoi": False}) == {
        "bo_bom_hoi": False,
        "lop_du_phong": False,
    }


def test_mot_co_mot_khong_la_hop_le():
    set_vehicle_options("veh-1", {"lop_du_phong": False, "bo_bom_hoi": True})
    assert get_vehicle_options("veh-1") == {"bo_bom_hoi": True, "lop_du_phong": False}


def test_body_sai_khong_de_lai_nua_tap_da_ghi():
    """Kiểm chạy TRƯỚC khi động vào bảng. Không thế thì một body sai để lại rác."""
    set_vehicle_options("veh-1", {"acc": True})
    with pytest.raises(TrangBiKhongHopLeError):
        set_vehicle_options("veh-1", {"bsd": True, "id_bia_ra": True})
    assert get_vehicle_options("veh-1") == {"acc": True}

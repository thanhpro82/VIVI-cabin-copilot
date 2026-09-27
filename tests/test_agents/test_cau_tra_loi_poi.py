"""Nhánh số ít làm nhiều hơn điều được yêu cầu (đặt dẫn đường cho một câu "tìm"),
nên nó BẮT BUỘC nói ra mình đã làm gì và cho lối thoát ngay trong cùng một lượt.
Đó là điều kiện kèm theo của quyết định ở spec SP-5 §2.1, không phải trang trí."""

from src.agents.nodes.compose import cau_ket_qua_tim_poi, describe_step
from src.fixtures import tim_poi_theo_loai


def test_describe_step_in_ten_quan_khong_in_id():
    """`"dẫn đường tới poi-cafe-02"` là chuỗi không ai đọc lên được."""
    cau = describe_step("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})
    assert "Cà phê Bình Minh" in cau
    assert "poi-cafe-02" not in cau


def test_describe_step_id_la_thi_khong_no():
    assert describe_step("set_navigation", {"operation": "start", "destination_id": "poi-la"})


def test_describe_step_huy_dan_duong_khong_doi():
    assert describe_step("set_navigation", {"operation": "cancel"}) == "hủy dẫn đường"


def test_cau_so_nhieu_doc_ten_kem_khoang_cach_va_hoi_lai():
    cau = cau_ket_qua_tim_poi(list(tim_poi_theo_loai("cafe"))[:3])
    assert "Cà phê Bình Minh" in cau and "Highlands" in cau
    assert "3,6" in cau
    assert cau.rstrip().endswith("?")


def test_cau_so_nhieu_doc_toi_da_ba_ket_qua():
    """Ba là trần của tai, không phải của màn hình."""
    assert cau_ket_qua_tim_poi(list(tim_poi_theo_loai("cafe"))[:3]).count(" km") <= 3


def test_loai_khong_co_ket_qua_thi_noi_that():
    cau = cau_ket_qua_tim_poi(list(tim_poi_theo_loai("san-bay")))
    assert "không tìm" in cau.lower()

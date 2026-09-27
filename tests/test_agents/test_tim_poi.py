"""SP-5: tìm địa điểm. Số ít thì đi, số nhiều thì hỏi (spec §2.1)."""

import pytest

from src.agents.router import DeterministicControlRouter

router = DeterministicControlRouter()


def _buoc(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


@pytest.mark.parametrize("text", ["Tìm quán cà phê gần đây", "Kiếm quán cà phê gần nhất"])
def test_so_it_thi_chi_duong_toi_quan_gan_nhat(text):
    """Bình Minh 3,6 km gần hơn Highlands 5,6 km."""
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})]


def test_dang_nghi_van_thi_neu_ra_roi_hoi_lai_chu_khong_lam():
    """`"Quanh đây có quán cà phê nào không"` là câu HỎI, nên ADR-011 cho nó đường
    `offer` — nêu việc sẽ làm rồi hỏi lại. Tôi từng viết test này mong `control`;
    đó là **kỳ vọng sai**: quyết định "số ít thì đi" của spec §2.1 nói về câu MỆNH
    LỆNH (*"tìm…"*), còn dạng nghi vấn đã có luật riêng và luật ấy an toàn hơn."""
    d, buoc = _buoc("Quanh đây có quán cà phê nào không")
    assert d.disposition == "offer"
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})]


@pytest.mark.parametrize(
    "text",
    ["Tìm các quán cà phê gần đây", "Tìm những quán cà phê quanh đây", "Quanh đây có mấy quán cà phê"],
)
def test_so_nhieu_thi_chi_tim_khong_dat_dan_duong(text):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert d.intent == "poi_search"
    assert buoc == [("search_nearby_poi", {"category": "cafe"})]


def test_cau_ghep_tim_roi_dan_duong_toi_do():
    """Đại từ hồi chỉ xử trong CÙNG matcher — không đụng cơ chế ghép vế của #225."""
    d, buoc = _buoc("Tìm quán cà phê gần đây rồi dẫn đường tới đó")
    assert d.disposition == "control", d
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})]


def test_dan_duong_toi_do_dung_mot_minh_van_hoi_lai():
    """Không có gì để "đó" trỏ tới — giữ nguyên hành vi hôm nay."""
    assert router.route("Dẫn đường tới đó").disposition != "control"


@pytest.mark.parametrize(
    ("text", "poi_id"),
    [
        ("Tìm trạm sạc gần đây", "poi-charge-01"),
        ("Tìm chỗ ăn gần đây", "poi-food-01"),
        ("Tìm chỗ mua sắm gần đây", "poi-mall-01"),
    ],
)
def test_cac_loai_khac(text, poi_id):
    _, buoc = _buoc(text)
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": poi_id})]


@pytest.mark.parametrize(
    "text",
    ["Tìm hiểu về áp suất lốp", "Tìm hiểu cách khởi tạo cửa sổ điện", "Cách tìm trạm sạc trên màn hình"],
)
def test_khong_bat_nham_cau_hoi_so_tay(text):
    """Ô cổng cứng `manual→control` phải giữ bằng 0 — đây là chỗ dễ làm vỡ nhất."""
    assert router.route(text).disposition != "control", text


def test_dan_duong_toi_ten_quan_van_di_duong_cu():
    """`_match_navigation` cũ không bị matcher mới nuốt mất."""
    _, buoc = _buoc("Dẫn đường tới cà phê bình minh")
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})]

"""Đ2 PR 2a — bảng từ đồng nghĩa, và các cách gọi tên mà router giờ nhận ra.

28/42 dòng báo lỗi ngày 24/08 quy về cùng một chuyện: router chỉ biết **một** cách
gọi cho mỗi thứ. File này khoá cả hai chiều — cách nói mới phải chạy, và hàng rào cũ
(câu hỏi sổ tay, loại đèn không điều khiển được) phải không vỡ.
"""

import pytest

from src.agents.router import DeterministicControlRouter
from src.agents.tu_dong_nghia import CHE_DO_DEN, che_do_den, co_bat_ky, co_cum

router = DeterministicControlRouter()


def _buoc(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


# ---- Bảng: khớp theo TỪ, không theo chuỗi con -----------------------------


def test_khop_theo_bien_tu_chu_khong_phai_chuoi_con():
    """`"ac" in "các cửa"` là True — và đó chính là lý do bảng không dùng `in` trần.

    Alias hai ký tự khớp bằng chuỗi con sẽ biến mọi câu có chữ `các` thành lệnh điều
    hòa. Đây là test quan trọng nhất của module này.
    """
    assert co_cum("bật ac", "ac")
    assert not co_cum("mở các cửa", "ac")
    assert not co_cum("bác sĩ nói gì", "ac")
    assert co_bat_ky("bật máy lạnh", ("điều hòa", "máy lạnh"))
    assert not co_bat_ky("mở cốp", ("điều hòa", "máy lạnh"))


def test_che_do_den_lay_dich_den_chu_khong_lay_trang_thai_dang_co():
    """Câu nêu cả hai chế độ thì lấy cái được YÊU CẦU, không lấy cái đang dùng."""
    assert che_do_den("đổi từ chiếu gần sang chiếu xa") == "high_beam"
    assert che_do_den("bật đèn cos") == "low_beam"
    assert che_do_den("chuyển đèn sang auto") == "auto"
    assert che_do_den("mở cốp") is None


def test_bang_che_do_den_khong_co_alias_cho_den_ngoai_be_mat():
    """`_UNSUPPORTED_LIGHTS` chỉ có tác dụng nếu bảng này không mở đường vòng.

    Thêm `sương mù` hay `hazard` vào đây là cách nhanh nhất kéo `question_recall`
    xuống: câu hỏi sổ tay về chúng sẽ ra `clarify` thay vì được tra sổ tay.
    """
    alias = {a for a, _ in CHE_DO_DEN}
    assert not (alias & {"sương mù", "hazard", "nháy", "cảnh báo", "xi nhan", "đèn phanh"})


# ---- Điều hòa -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "buoc_mong_doi"),
    [
        ("Bật máy lạnh", [("set_hvac_power", {"enabled": True})]),
        ("Bật AC", [("set_hvac_power", {"enabled": True})]),
        ("Bật hệ thống làm mát", [("set_hvac_power", {"enabled": True})]),
        ("Tắt máy lạnh", [("set_hvac_power", {"enabled": False})]),
        ("Đặt máy lạnh 22 độ", [("set_hvac_temperature", {"temperature_c": 22})]),
    ],
)
def test_may_lanh_ac_lam_mat_deu_la_dieu_hoa(text, buoc_mong_doi):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == buoc_mong_doi


# ---- Sưởi ghế -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seat", "level"),
    [
        ("Làm ấm ghế lái mức 2", "front_left", 2),
        ("Sưởi ghế lái mức 2", "front_left", 2),
        ("Hâm nóng ghế phụ mức 1", "front_right", 1),
    ],
)
def test_lam_am_ham_nong_deu_la_suoi_ghe(text, seat, level):
    """`"làm ấm ghế lái mức 2"` chứa chữ `ghế` nên trước đây rơi vào nhánh **vị trí**
    ghế, không khớp trục nào và trả `None` — sưởi ghế không bao giờ tới lượt."""
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("set_seat_heating", {"seat": seat, "level": level})]


# ---- Trục độ cao ghế ------------------------------------------------------


def test_do_cao_va_chieu_cao_deu_la_truc_height():
    d, buoc = _buoc("Đặt độ cao ghế lái 70%")
    assert d.disposition == "control", d
    assert buoc == [("set_seat_position", {"seat": "front_left", "axis": "height", "value": 70})]


def test_thieu_vi_tri_ghe_thi_hoi_lai_chu_khong_roi_so_tay():
    """Tiến bộ nhỏ nhưng thật: trước đây `"chỉnh chiều cao ghế 60%"` ra `not_control`
    và đi tra sổ tay. Giờ nó hỏi đúng thứ còn thiếu."""
    d, _ = _buoc("Chỉnh chiều cao ghế 60%")
    assert d.disposition == "clarify"
    assert d.reason == "missing_seat_side"


# ---- Đèn ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("Chuyển sang chiếu gần", "low_beam"),
        ("Bật chế độ chiếu xa", "high_beam"),
        ("Bật đèn cos", "low_beam"),
        ("Bật đèn high beam", "high_beam"),
        ("Chuyển đèn sang auto", "auto"),
        ("Bật đèn chiếu gần", "low_beam"),
        ("Chuyển đèn sang chế độ tự động", "auto"),
    ],
)
def test_cac_cach_goi_den(text, mode):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("set_headlight_mode", {"mode": mode})]


def test_tat_den_pha_van_bi_tu_choi_theo_adr_020():
    """Mở rộng alias không được mở đường vòng cho một thao tác bị cấm."""
    d, _ = _buoc("Tắt đèn pha")
    assert d.disposition == "denied"
    assert d.reason == "headlight_off_not_permitted"


def test_den_trong_van_hoi_lai():
    d, _ = _buoc("Bật đèn")
    assert d.disposition == "clarify"
    assert d.reason == "missing_light_target"


# ---- Nhạc -----------------------------------------------------------------


@pytest.mark.parametrize("text", ["Tiếp tục phát", "Phát tiếp"])
def test_tiep_tuc_phat_khong_can_chu_nhac(text):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("media_control", {"action": "play"})]


def test_dung_ngay_co_y_khong_duoc_doan_thanh_tam_dung_nhac():
    """Ranh giới cố ý — xem docstring `tu_dong_nghia`.

    Router không đọc trạng thái xe, nên `"dừng ngay"` lúc đang dẫn đường và lúc đang
    nghe nhạc là hai việc khác nhau mà nó không phân biệt được. Ánh xạ cứng sang
    `pause` là làm một việc khác việc được yêu cầu — đúng lớp lỗi cả đợt này nhắm vào.
    """
    d, _ = _buoc("Dừng ngay")
    assert d.disposition == "not_control"


# ---- Hàng rào không được vỡ ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Đèn sương mù bật thế nào",
        "Bật đèn nháy cảnh báo nguy hiểm bằng cách nào?",
        "Điều hòa hoạt động như thế nào?",
        "Sưởi ghế dùng thế nào?",
        "Hệ thống làm mát động cơ có cần bảo dưỡng không?",
    ],
)
def test_cau_hoi_so_tay_van_di_duong_so_tay(text):
    """Bảng alias rộng ra thì rủi ro là **cướp** câu hỏi khỏi nhánh sổ tay — nhánh
    mặc định của ADR-011 và là nơi nhận phần lớn lưu lượng."""
    d, _ = _buoc(text)
    assert d.disposition in {"not_control", "offer"}, d
    if d.disposition == "not_control":
        assert d.reason in {"manual_question", "default_to_manual"}

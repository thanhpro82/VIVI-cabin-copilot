"""Đ2 PR 2b — động từ theo lớp ngữ nghĩa, và bảng trục ghế.

Hai lỗ khác nhau, và chúng có cùng hình dạng: một tập từ viết tay ở **mỗi** matcher.

1. `_COMMAND_VERBS` thiếu từ (`cho`, `để`, `khởi động`, `dựng`, `đưa`, `đổi`, `chơi`,
   `bắt đầu`, `chỉ đường`, `mở bản đồ`…).
2. Mỗi matcher tự khai một tập con, và **các tập con không đồng ý với nhau**: `chỉnh`
   có trong `_COMMAND_VERBS` nhưng `_match_window` chỉ nhận `mở|đóng|hạ|kéo|nâng`, nên
   `"chỉnh cửa sổ bên lái 25%"` chết trong khi `"chỉnh lưng ghế"` sống.
"""

import pytest

from src.agents.router import DeterministicControlRouter
from src.agents.tu_dong_nghia import DAT_TUYET_DOI, TANG_GIAM, TRUC_GHE, truc_ghe

router = DeterministicControlRouter()


def _buoc(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


# ---- Bảng lớp -------------------------------------------------------------


def test_dat_tuyet_doi_khong_chua_tang_giam():
    """Lượng **tương đối** không được trộn vào lớp "đặt giá trị".

    Router không đọc trạng thái xe (ADR-011) nên không cộng trừ được từ mức hiện tại.
    Gộp `tăng`/`giảm` vào `DAT_TUYET_DOI` là mở cho mọi matcher một đường đoán số.
    """
    assert not (set(DAT_TUYET_DOI) & set(TANG_GIAM))


def test_truc_ghe_xet_recline_truoc_height():
    """`"dựng lưng ghế lái lên 40%"` có cả cụm lưng lẫn chữ `lên`.

    Nếu height được xét trước, câu ngả lưng thành lệnh **nâng ghế** — dịch chuyển sai
    bộ phận, và im lặng. Thứ tự bảng là hợp đồng, test này là chỗ khoá nó.
    """
    thu_tu = [truc for _, truc in TRUC_GHE]
    assert thu_tu.index("recline") < thu_tu.index("height")
    assert truc_ghe("dựng lưng ghế lái lên 40%") == "recline"
    assert truc_ghe("đưa ghế lái lên cao 80%") == "height"


# ---- Điều hòa -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "buoc_mong_doi"),
    [
        ("Khởi động điều hòa", [("set_hvac_power", {"enabled": True})]),
        ("Cho điều hòa 24 độ", [("set_hvac_temperature", {"temperature_c": 24})]),
        ("Để điều hòa 24 độ", [("set_hvac_temperature", {"temperature_c": 24})]),
    ],
)
def test_dong_tu_moi_cua_dieu_hoa(text, buoc_mong_doi):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == buoc_mong_doi


# ---- Kính: lỗ "hai tập con không đồng ý" ----------------------------------


@pytest.mark.parametrize("dong_tu", ["Đặt", "Chỉnh", "Để", "Cho", "Đưa", "Hạ", "Kéo"])
def test_moi_dong_tu_dat_gia_tri_deu_chinh_duoc_kinh(dong_tu):
    """`chỉnh` **có** trong `_COMMAND_VERBS` từ trước nhưng `_match_window` không nhận.

    Đó là lỗ nguy hiểm hơn "thiếu từ": guard phủ định coi câu là mệnh lệnh (vì nó tra
    `_COMMAND_VERBS`) trong khi matcher lại bỏ qua — hai tầng nhìn cùng một câu bằng
    hai con mắt khác nhau.
    """
    d, buoc = _buoc(f"{dong_tu} cửa sổ bên lái 25%")
    assert d.disposition == "control", d
    assert buoc == [("set_window_position", {"window": "front_left", "percent": 25})]


# ---- Ghế ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "axis", "value"),
    [
        ("Dựng lưng ghế lái lên 40%", "recline", 40),
        ("Đẩy ghế lái tới 80%", "fore_aft", 80),
        ("Đưa ghế lái lên cao 80%", "height", 80),
        ("Đưa ghế lái xuống thấp 20%", "height", 20),
        ("Nâng ghế lái lên 70%", "height", 70),
        ("Ngả lưng ghế lái 60%", "recline", 60),
    ],
)
def test_cac_truc_ghe(text, axis, value):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("set_seat_position", {"seat": "front_left", "axis": axis, "value": value})]


# ---- Đèn ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("Cho đèn về chiếu gần", "low_beam"),
        ("Để đèn tự động", "auto"),
        ("Đổi đèn sang chiếu xa", "high_beam"),
    ],
)
def test_dong_tu_moi_cua_den(text, mode):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("set_headlight_mode", {"mode": mode})]


# ---- Nhạc -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Cho tôi nghe nhạc", "Chơi nhạc", "Bắt đầu phát nhạc", "Khởi động nhạc", "Nghe nhạc"],
)
def test_cac_cach_bao_phat_nhac(text):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("media_control", {"action": "play"})]


# ---- Dẫn đường ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "poi"),
    [
        ("Chỉ đường đến Vincom", "poi-mall-01"),
        ("Mở bản đồ đến công viên Thống Nhất", "poi-fun-01"),
        ("Đi Vincom", "poi-mall-01"),
        ("Dẫn đường tới Vincom", "poi-mall-01"),
    ],
)
def test_cac_dong_tu_dan_duong(text, poi):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": poi})]


def test_dong_tu_mo_ho_khong_ro_dia_diem_thi_nhuong_cho_so_tay():
    """`đi` là động từ dẫn đường **mơ hồ**: nó mở đầu vô số câu hỏi sổ tay.

    Khi không tra được địa điểm nào, matcher phải trả `None` để câu rơi xuống sổ tay,
    **không** được hỏi lại "bạn muốn đi đâu". Đây là lý do `DAN_DUONG_RO` và
    `DAN_DUONG_MO_HO` là hai bảng chứ không phải một.
    """
    d, _ = _buoc("Đi bao nhiêu km thì phải thay dầu?")
    assert d.disposition == "not_control", d


def test_dong_tu_tuong_minh_khong_ro_dia_diem_thi_hoi_lai():
    d, _ = _buoc("Dẫn đường tới nhà bà ngoại")
    assert d.disposition == "clarify"
    assert d.reason == "unknown_local_destination"


# ---- Hàng rào -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Cho tôi biết áp suất lốp tiêu chuẩn là bao nhiêu?",
        "Để xe lâu không đi có sao không?",
        "Đi bao lâu thì phải bảo dưỡng?",
        "Mở cốp bằng cách nào?",
        "Chơi thể thao xong ngồi ghế có bị gì không?",
    ],
)
def test_dong_tu_moi_khong_cuop_cau_hoi_so_tay(text):
    """Lớp động từ rộng ra thì rủi ro nằm ở những câu hỏi **mở đầu bằng chính các động
    từ ấy**. Matcher vẫn đòi từ khoá miền, nên chúng phải rơi đúng nhánh cũ."""
    d, _ = _buoc(text)
    assert d.disposition in {"not_control", "offer"}, d

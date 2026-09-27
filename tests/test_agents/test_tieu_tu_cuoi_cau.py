"""Tiểu từ cuối câu (`ta`, `nhỉ`, `thế`, `vậy`…) không được làm câu hỏi biến mất.

Phát hiện 22/08 từ 28 ca phương ngữ của Sơn (issue #244). `is_question` chỉ nhận
câu hỏi khi token cuối ĐÚNG BẰNG `"không"`, mà giọng nói thật gần như luôn có một
tiểu từ sau đó. Hệ quả đo được, nặng nhất ở đường control:

    "Bật điều hòa được không vậy"  ->  denied / temperature_out_of_range

Tài xế hỏi xe có bật điều hòa được không, và nhận một lời từ chối kèm lý do
không tồn tại. Bản không tiểu từ (`"...được không"`) đi đúng đường `offer`/`clarify`.
"""

import pytest

from src.agents.question import is_negated, is_question
from src.agents.router import DeterministicControlRouter, normalize_vi

router = DeterministicControlRouter()


def q(raw: str) -> bool:
    return is_question(raw, normalize_vi(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "Còn xa không ta",
        "Xe mình còn đủ pin về đến nhà không nhỉ",
        "Mở cửa sổ được không ta",
        "Bật điều hòa được không vậy",
        "Alo alo có nghe thấy không đấy",
        "Ghế có sưởi không hả",
    ],
)
def test_cau_hoi_co_tieu_tu_cuoi_van_la_cau_hoi(raw):
    assert q(raw), f"{raw!r} là câu hỏi có/không, tiểu từ cuối không đổi điều đó"


@pytest.mark.parametrize(
    "raw",
    ["Không phát nhạc", "Đừng mở cửa sổ bên lái", "Chớ mở cửa", "Tôi không muốn bật điều hòa"],
)
def test_phu_dinh_that_van_la_phu_dinh(raw):
    assert is_negated(normalize_vi(raw)), f"{raw!r} vẫn phải là phủ định"


@pytest.mark.parametrize(
    "raw",
    ["Mở cửa sổ được không ta", "Bật điều hòa được không vậy", "Còn xa không ta"],
)
def test_khong_nghi_van_co_tieu_tu_khong_bi_doc_thanh_phu_dinh(raw):
    """`"không"` ở đây là tiểu từ nghi vấn dù không đứng cuối — vì sau nó chỉ còn tiểu từ."""
    assert not is_negated(normalize_vi(raw))


def test_bat_dieu_hoa_duoc_khong_vay_khong_con_bi_tu_choi():
    """Ca nặng nhất: từ chối kèm lý do `temperature_out_of_range` không tồn tại."""
    quyet_dinh = router.route("Bật điều hòa được không vậy")
    assert quyet_dinh.disposition != "denied", quyet_dinh
    assert quyet_dinh.reason != "temperature_out_of_range"


def test_hai_ban_giong_cung_mot_y_di_cung_duong():
    """Cặp Nam/Bắc cùng ý phải đi CÙNG đường với bản không tiểu từ.

    Cố ý không khoá một `disposition` cụ thể: bất biến ở đây là *giọng không đổi
    đường*, còn đường ấy là gì thì luật khác quyết. (Tôi từng viết test này khoá
    `offer` theo trí nhớ — thực tế bản chuẩn `"...được không"` cho
    `clarify / missing_window_position`, và khoá nhầm như thế là biến một test
    ngang-bằng thành một test đoán mò.)
    """
    chuan = router.route("Mở cửa sổ bên lái được không")
    for bien_the in ("Mở cửa sổ bên lái được không ta", "Mở cửa sổ bên lái được không nhỉ",
                     "Mở cửa sổ bên lái được không vậy"):
        d = router.route(bien_the)
        assert (d.disposition, d.reason) == (chuan.disposition, chuan.reason), bien_the


@pytest.mark.parametrize(
    "raw",
    ["Mở cửa sổ bên lái được không vậy", "Bật điều hòa được không ta", "Đặt âm lượng lên được không nhỉ"],
)
def test_khong_nghi_van_khong_bao_gio_bi_doc_thanh_so_0(raw):
    """`_words_to_number` là chỗ thứ BA đọc vị trí chữ "không" — cùng điểm mù.

    Không bóc tiểu từ thì `"được không vậy"` đọc ra 0: 0 độ C rơi ra ngoài khoảng
    hợp lệ (`denied / temperature_out_of_range` cho một câu HỎI), còn 0% cửa sổ là
    lời đề nghị **đóng** kính khi người ta vừa hỏi về mở.
    """
    quyet_dinh = router.route(raw)
    assert quyet_dinh.reason != "temperature_out_of_range"
    for buoc in quyet_dinh.candidate_plan.steps if quyet_dinh.candidate_plan else []:
        assert 0 not in buoc.args.values(), f"{raw!r}: đọc tiểu từ thành số 0 -> {buoc.args}"

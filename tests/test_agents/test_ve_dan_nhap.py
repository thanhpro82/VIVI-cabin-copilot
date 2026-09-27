"""Đ2 PR 2c — bỏ vế dẫn nhập ở đầu câu.

Người ta không nói *"Bật điều hòa."* trần. Người ta nói *"Nóng quá bật điều hòa giúp
mình"*, *"Vivi ơi bật nhạc"*, *"Ờ bật nhạc đi"*. `_starts_with_command` neo tuyệt đối ở
ký tự số 0 nên tất cả đều rơi xuống sổ tay.

Bằng chứng đây là một lỗ chứ không phải thiết kế: *"lạnh rồi tắt điều hòa giúp mình"*
**chạy đúng** từ trước — nhưng chỉ vì `rồi` tình cờ nằm trong `_CONJUNCTIONS`. Cùng lớp
câu, hai số phận.

File này có hai nửa và nửa thứ hai quan trọng hơn: nửa đầu chứng minh câu lệnh chạy,
nửa sau chứng minh **câu hỏi vẫn không bị biến thành lệnh** — thứ mà `question_recall`
đo và ADR-011 dựng lên để bảo vệ.
"""

import pytest

from src.agents.router import DeterministicControlRouter
from src.agents.tu_dong_nghia import GOI_VA_AM_U, MAX_TU_TIEN_TO

router = DeterministicControlRouter()


def _kq(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


# ---- Câu lệnh có vế dẫn nhập ----------------------------------------------


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("Nóng quá bật điều hòa giúp mình", "set_hvac_power"),
        ("Ờ bật nhạc đi", "media_control"),
        ("Im quá bật nhạc đi", "media_control"),
        ("Vivi ơi bật nhạc", "media_control"),
        ("Ê vivi dẫn tui tới Bình Minh", "set_navigation"),
        ("Trời mưa quá bật đèn chiếu gần", "set_headlight_mode"),
        ("Này bật nhạc", "media_control"),
        ("Tôi muốn bật điều hòa", "set_hvac_power"),
        ("Mình muốn mở cốp", "set_trunk_state"),
        ("Tôi muốn nghe bài Carefree", "media_control"),
    ],
)
def test_ve_dan_nhap_bi_boc_ra_va_lenh_chay(text, tool):
    d, buoc = _kq(text)
    assert d.disposition == "control", d
    assert buoc[0][0] == tool


def test_cau_von_da_chay_thi_khong_doi():
    """`"lạnh rồi tắt điều hòa giúp mình"` chạy được từ trước nhờ `rồi` ∈ `_CONJUNCTIONS`."""
    d, buoc = _kq("Lạnh rồi tắt điều hòa giúp mình")
    assert d.disposition == "control"
    assert buoc == [("set_hvac_power", {"enabled": False})]


# ---- Hàng rào: câu hỏi KHÔNG được thành lệnh ------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Làm sao để bật điều hòa?",
        "Cách bật điều hòa",
        "Tôi muốn bật điều hòa thì làm thế nào?",
        "Hướng dẫn tôi bật điều hòa",
        "Chỉ tôi bật điều hòa",
        "Sách hướng dẫn nói bật điều hòa kiểu gì?",
        # Cùng tiền tố `tôi muốn` với ba ca chạy ở trên — khác nhau ở chỗ phần còn
        # lại là một câu HỎI, không phải một lệnh. Đó là toàn bộ hàng rào.
        "Tôi muốn hỏi về đèn sương mù",
        "Cho tôi biết cách mở cốp",
        "Tôi muốn xe chạy êm hơn thì làm gì?",
    ],
)
def test_cau_hoi_huong_dan_van_di_so_tay(text):
    """Điều kiện "phần còn lại phải tự khớp `control`" một mình **không** đủ: đuôi của
    mấy câu này đúng là một lệnh hoàn chỉnh.

    Thứ chặn chúng là **vị trí gọi** — `_bo_ve_dan_nhap` nằm ở cuối `_match`, sau khi
    mọi nhánh câu hỏi đã `return`, cộng với luật tiền tố phải là vế dẫn nhập thật
    (`GOI_VA_AM_U` hoặc cảm thán kết thúc bằng `quá`), chứ không phải vài từ bất kỳ.
    """
    d, _ = _kq(text)
    assert d.disposition == "not_control", d


def test_phu_dinh_van_thang_sau_khi_boc_tien_to():
    """`"ờ đừng bật nhạc"` — bóc `ờ` xong thì đuôi là một lệnh hợp lệ.

    Guard phủ định chạy **trước** chỗ bóc, nên câu vẫn `denied`. Nếu ai đó chuyển
    `_bo_ve_dan_nhap` lên sớm hơn trong `_match`, test này đỏ — và đó là ý.
    """
    d, _ = _kq("Ờ đừng bật nhạc")
    assert d.disposition == "denied"
    assert d.reason == "negated_command"


def test_thoi_khong_nam_trong_bang_vi_no_la_tu_rut_lai():
    """`thôi` là dấu hiệu **tự sửa lời** (`"bật điều hòa à thôi"`), không phải ậm ừ.

    Bóc nó như một tiền tố vô nghĩa là xoá mất tín hiệu huỷ mà một issue khác đang
    nhắm vào. Ranh giới này cố ý, không phải bỏ sót.
    """
    assert "thôi" not in GOI_VA_AM_U
    d, _ = _kq("Thôi bật nhạc")
    assert d.disposition == "not_control"


def test_khong_boc_qua_gioi_han_do_dai_tien_to():
    """Trần độ dài là thứ giữ cho luật không nuốt được nửa đầu của một câu ghép."""
    assert MAX_TU_TIEN_TO == 3
    d, _ = _kq("Hôm nay trời nóng và oi bức quá bật điều hòa")
    assert d.disposition == "not_control", d


def test_khong_boc_khi_phan_con_lai_chi_ra_clarify():
    """Điều kiện là `control`, không phải "khớp matcher nào đó".

    `"bật đèn"` trần ra `clarify missing_light_target`; cho phép bóc tới một `clarify`
    nghĩa là hệ bắt đầu hỏi lại về những câu nó vốn im lặng nhường cho sổ tay.
    """
    d, _ = _kq("Tối quá bật đèn")
    assert d.disposition == "not_control", d

"""Test chuẩn hoá văn bản tiếng Việt."""

import unicodedata

from src.rag.textnorm import content_words, fold, lexical_overlap, normalize_text


def test_normalize_text_dua_ve_nfc_va_bo_ky_tu_vo_hinh() -> None:
    decomposed = unicodedata.normalize("NFD", "cửa sổ điện")
    assert normalize_text(f"  {decomposed}​\n  ") == "cửa sổ điện"
    assert unicodedata.is_normalized("NFC", normalize_text(decomposed))


def test_fold_bo_dau_de_khop_html_voi_pdf() -> None:
    assert fold("Cửa sổ điện!") == "cua so dien"
    assert fold("Đèn báo rẽ") == "den bao re"


def test_fold_lam_mat_thanh_dieu_nen_khong_dung_de_so_nghia() -> None:
    """Đây chính là lý do `lexical_overlap` dùng token giữ dấu.

    Bỏ dấu biến "bò" và "bỏ" thành một, khiến câu "phở bò" trùng khớp giả với
    hướng dẫn có chữ "bỏ".
    """
    assert fold("bò") == fold("bỏ")
    assert content_words("phở bò") != content_words("phở bỏ")


def test_content_words_loai_hu_tu_va_tu_mot_ky_tu() -> None:
    assert content_words("Làm sao bật sưởi ghế?") == {"bật", "sưởi", "ghế"}


def test_lexical_overlap_do_ty_le_tu_mang_nghia_xuat_hien() -> None:
    assert lexical_overlap("bật sưởi ghế", "hướng dẫn bật sưởi ghế trước") == 1.0
    assert lexical_overlap("công thức nấu phở", "điều chỉnh ghế ngồi") == 0.0
    assert lexical_overlap("", "bất kỳ") == 0.0

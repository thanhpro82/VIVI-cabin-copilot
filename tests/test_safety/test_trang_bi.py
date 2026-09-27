"""Danh mục trang bị: tính nhất quán của bảng, và hành vi của bộ dò.

Chạy trên CI. Không đụng chunk store — lớp đối chiếu với sổ tay thật nằm ở
`tests/test_rag_integration/test_trang_bi_provenance.py` (marker `slow`), vì `data/`
bị gitignore toàn bộ nên runner không có corpus.

Ranh giới ấy quan trọng: lớp này bắt được "bảng tự mâu thuẫn", lớp kia bắt được "bảng
nói về một cuốn sổ tay khác". Không lớp nào thay được lớp nào.
"""

from __future__ import annotations

import json

import pytest

from src.safety import trang_bi
from src.safety.trang_bi import DanhMucHongError, doc_danh_muc, ma_hop_le, nhan_dien, tra


@pytest.fixture(autouse=True)
def _xoa_cache():
    doc_danh_muc.cache_clear()
    yield
    doc_danh_muc.cache_clear()


def test_danh_muc_nap_duoc_va_khong_rong():
    dm = doc_danh_muc()
    assert len(dm) >= 60
    assert dm.phien_ban_so_tay == "VF9_23-25_VN_VI_2.4"


def test_moi_trang_bi_deu_co_ly_do_bang_van_xuoi():
    """`vi_sao` không phải trang trí: nó là thứ chặn danh mục phình ra vô hạn.

    Mỗi mục thêm vào là một trường tài xế có thể phải khai và một nhánh phải bảo trì.
    Bắt buộc viết được một câu vì sao xe không có nó thì câu trả lời sai — không viết
    nổi thì mục ấy không đáng có.
    """
    thieu = [t.id for t in doc_danh_muc() if len(t.vi_sao) < 40]
    assert thieu == [], f"những mục này chưa giải thích được vì sao cần: {thieu}"


def test_id_va_nhom_dung_dang_snake_case():
    xau = [t.id for t in doc_danh_muc() if not t.id.replace("_", "").isalnum() or t.id != t.id.lower()]
    assert xau == []


def test_loai_tru_doi_xung_va_tro_toi_muc_co_that():
    """Đã kiểm lúc nạp; test này khoá lại để ai đó không nới nó ra cho tiện."""
    dm = doc_danh_muc()
    for t in dm:
        for khac in t.loai_tru:
            assert khac in dm.theo_id
            assert t.id in dm.theo_id[khac].loai_tru


def test_khong_trang_bi_nao_tu_loai_tru_chinh_no():
    assert [t.id for t in doc_danh_muc() if t.id in t.loai_tru] == []


def test_cum_tu_duy_nhat_tren_toan_danh_muc(tmp_path, monkeypatch):
    """Hai mục cùng nhận một cụm thì bộ dò chọn bừa **mà im lặng**. Phải là lỗi nạp."""
    xau = {
        "phien_ban_so_tay": "x",
        "trang_bi": [
            {"id": "a", "ten": "A", "nhom": "n", "loai_tru": [], "cum_tu": ["đèn"], "muc": [], "vi_sao": "x"},
            {"id": "b", "ten": "B", "nhom": "n", "loai_tru": [], "cum_tu": ["đèn"], "muc": [], "vi_sao": "x"},
        ],
    }
    f = tmp_path / "x.json"
    f.write_text(json.dumps(xau, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(trang_bi, "_DUONG_DAN", f)
    with pytest.raises(DanhMucHongError, match="không phân biệt nổi"):
        doc_danh_muc()


def test_loai_tru_mot_chieu_la_loi_nap(tmp_path, monkeypatch):
    xau = {
        "phien_ban_so_tay": "x",
        "trang_bi": [
            {"id": "a", "ten": "A", "nhom": "n", "loai_tru": ["b"], "cum_tu": ["x"], "muc": [], "vi_sao": "x"},
            {"id": "b", "ten": "B", "nhom": "n", "loai_tru": [], "cum_tu": ["y"], "muc": [], "vi_sao": "x"},
        ],
    }
    f = tmp_path / "x.json"
    f.write_text(json.dumps(xau, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(trang_bi, "_DUONG_DAN", f)
    with pytest.raises(DanhMucHongError, match="một chiều"):
        doc_danh_muc()


def test_trang_bi_khong_co_cum_tu_nao_la_loi_nap(tmp_path, monkeypatch):
    """Mục không có cụm từ thì bộ dò không bao giờ thấy nó — một mục chết mà xanh."""
    xau = {
        "phien_ban_so_tay": "x",
        "trang_bi": [{"id": "a", "ten": "A", "nhom": "n", "loai_tru": [], "cum_tu": [], "muc": [], "vi_sao": "x"}],
    }
    f = tmp_path / "x.json"
    f.write_text(json.dumps(xau, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(trang_bi, "_DUONG_DAN", f)
    with pytest.raises(DanhMucHongError, match="không có cụm từ"):
        doc_danh_muc()


# --- Bộ dò ------------------------------------------------------------------


def test_nhan_dien_cau_khong_co_menh_de_dieu_kien_tra_rong():
    assert nhan_dien("Áp suất lốp nên được kiểm tra khi lốp nguội.") == []


def test_nhan_dien_bat_dung_trang_bi_dung_truoc_dau():
    assert nhan_dien("Đèn sương mù phía sau (nếu được trang bị) được lắp trên cản sau.") == ["den_suong_mu_sau"]


def test_cum_dai_hon_thang_cum_ngan_hon():
    """`"đèn sương mù"` là hậu tố của `"đèn sương mù phía sau"`; phải chọn cụm dài."""
    assert nhan_dien("Đèn sương mù phía sau (nếu có)") == ["den_suong_mu_sau"]
    assert nhan_dien("Đèn sương mù (nếu có)") == ["den_suong_mu_truoc"]


def test_cum_tu_xuat_hien_sau_dau_thi_khong_tinh():
    """Bộ dò trả lời "mệnh đề NÀY nói về cái gì", nên nó chỉ nhìn về phía trước dấu.

    Không có tính chất này thì `"lốp dự phòng"` trong một chunk có mệnh đề điều kiện
    về thứ khác cũng bị gán nhầm.
    """
    assert nhan_dien("Hệ thống trợ làn (nếu có) không liên quan tới lốp dự phòng.") == ["lka"]


def test_cum_tu_o_ngoai_cua_so_nhin_lui_thi_khong_tinh():
    xa = "Lốp dự phòng " + "x" * 200 + " Hệ thống trợ làn (nếu có)"
    assert "lop_du_phong" not in nhan_dien(xa)


def test_nhan_dien_nhieu_trang_bi_theo_thu_tu_xuat_hien():
    doan = "Massage ghế ngồi Nếu được trang bị. Sưởi vô lăng (nếu được trang bị)."
    assert nhan_dien(doan) == ["massage_ghe", "suoi_vo_lang"]


def test_nhan_dien_khu_trung_lap():
    doan = "Lốp dự phòng (nếu có) thì đặt ở khoang sau. Lốp dự phòng (nếu được trang bị) là loại T145."
    assert nhan_dien(doan) == ["lop_du_phong"]


def test_menh_de_dieu_kien_khong_nhan_ra_duoc_thi_tra_rong_chu_khong_doan():
    """*"cảnh báo lỗi (nếu có)"* là loại 2 — dữ liệu vắng lúc chạy, không phải trang bị.

    Bộ dò phải im lặng ở đây. Đoán bừa một trang bị gần giống sẽ khiến composer nói
    "xe bạn không có X" về một thứ chẳng ai khai báo.
    """
    assert nhan_dien("Bạn có thể xem bất kỳ cảnh báo lỗi của xe (nếu có) trên ứng dụng.") == []


def test_giu_dau_tieng_viet_khi_so_khop():
    """`"kéo xe"` và `"kẹo xe"` chỉ khác nhau ở dấu; bỏ dấu là chập hai thứ làm một."""
    assert nhan_dien("Kéo xe (nếu có)") == ["moc_keo"]
    assert nhan_dien("Kẹo xe (nếu có)") == []


def test_tra_va_ma_hop_le_nhat_quan_voi_nhau():
    assert tra("lop_du_phong") is not None
    assert tra("khong_ton_tai") is None
    assert set(ma_hop_le()) == {t.id for t in doc_danh_muc()}

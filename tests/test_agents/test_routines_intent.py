"""Ý định Routine + phân giải tên. Issue #285 (outcome #274, epic #270).

Chạy thẳng trên `eval/datasets/agent/routines-v1/cases.jsonl`, nên thêm ca vào file là
test tự phủ theo — không phải chép hai lần.

**Bộ đo ấy là tripwire, không phải thước**: cả 38 ca đều `tu_viet`, do chính người viết
matcher soạn. Xem README của dataset; nợ nguồn độc lập ghi ở đó.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.nodes.normalize import normalize_vi
from src.agents.routines_intent import doc_y_dinh, phan_giai_ten

CASES = [
    json.loads(dong)
    for dong in (
        Path(__file__).resolve().parents[2] / "eval" / "datasets" / "agent" / "routines-v1" / "cases.jsonl"
    )
    .read_text(encoding="utf-8")
    .splitlines()
    if dong.strip()
]


def _doc(ca: dict):
    return doc_y_dinh(normalize_vi(ca["input_text"]), dang_xem_truoc=ca["ngu_canh"] == "dang_xem_truoc")


def test_bo_do_khong_rong_va_du_ca_sau_nhan():
    """Bộ đo teo lại là một cách làm test xanh mà không ai thấy."""
    assert len(CASES) >= 38
    assert {ca["y_dinh"] for ca in CASES} == {
        "chay",
        "xem_truoc",
        "dong_y",
        "tu_choi",
        "bo_buoc",
        "khong_phai_routine",
    }


@pytest.mark.parametrize("ca", CASES, ids=lambda c: c["case_id"])
def test_moi_ca_trong_bo_do_ra_dung_y_dinh(ca):
    ket = _doc(ca)
    if ca["y_dinh"] == "khong_phai_routine":
        assert ket is None, f"{ca['input_text']!r} bị nhận nhầm thành {ket}"
        return
    assert ket is not None, f"{ca['input_text']!r} không nhận ra ý định nào"
    assert ket.loai == ca["y_dinh"]
    if "ten_tho" in ca:
        assert ket.ten_tho == ca["ten_tho"]
    if "so_buoc" in ca:
        assert ket.so_buoc == ca["so_buoc"]


def test_cong_cung_ten_routine_khong_tu_kich_hoat():
    """Lớp nguy hiểm nhất: tên mẫu mặc định trùng cụm tiếng Việt thông dụng.

    `"Về nhà đường nào gần nhất"` là câu hỏi. Nhận nhầm nghĩa là một câu hỏi sổ tay biến
    thành chuỗi 4 hành động lên xe. Tên **không bao giờ** tự kích hoạt — bắt buộc có
    động từ chạy/xem **và** từ chỉ danh mục đứng trước.
    """
    for cau in (
        "Về nhà đường nào gần nhất",
        "Đi làm bằng xe này mất bao lâu",
        "Chạy nhanh quá đấy",
        "Thư giãn chút đi",
        "đi làm",
        "về nhà",
    ):
        assert doc_y_dinh(normalize_vi(cau)) is None, cau


def test_cung_mot_cau_hai_nghia_theo_ngu_canh():
    """`"Chạy đi"` / `"Đồng ý"`: đồng ý khi có preview treo, không phải ý định Routine
    khi không có. Đây là lý do `dang_xem_truoc` là tham số chứ không phải phỏng đoán."""
    for cau in ("Chạy đi", "Đồng ý"):
        assert doc_y_dinh(normalize_vi(cau), dang_xem_truoc=True).loai == "dong_y"
        assert doc_y_dinh(normalize_vi(cau), dang_xem_truoc=False) is None


def test_dung_chay_la_tu_choi_chu_khong_phai_dong_y():
    """`"Đừng chạy"` chứa cả `đừng` lẫn `chạy`. Xét từ chối trước là điều giữ cho nó
    không thành lời đồng ý — chiều lỗi ở đây là chạy một chuỗi lệnh người ta vừa từ chối."""
    assert doc_y_dinh(normalize_vi("Đừng chạy"), dang_xem_truoc=True).loai == "tu_choi"


def test_duoi_lich_su_khong_dinh_vao_ten():
    """`"chạy routine đi làm đi"` → tên `"đi làm"`. Đuôi bám vào tên thì phân giải trượt
    và tài xế nhận một câu hỏi lại vô nghĩa."""
    assert doc_y_dinh(normalize_vi("chạy routine đi làm đi")).ten_tho == "đi làm"
    assert doc_y_dinh(normalize_vi("bật routine thư giãn lên")).ten_tho == "thư giãn"
    assert doc_y_dinh(normalize_vi("chạy giùm routine về nhà")).ten_tho == "về nhà"


# --- Phân giải tên ----------------------------------------------------------

DS = ["Đi làm", "Về nhà", "Thư giãn"]


def test_khop_bo_qua_hoa_thuong_va_dau_cau():
    for noi in ("đi làm", "ĐI LÀM", "Đi Làm", "đi làm."):
        assert phan_giai_ten(noi, DS).trung == "Đi làm"


def test_khop_cum_con_khi_ten_dai_hon():
    assert phan_giai_ten("đi làm", ["Đi làm buổi sáng"]).trung == "Đi làm buổi sáng"


def test_hai_ten_cung_khop_thi_hoi_lai_chu_khong_chon_bua():
    ket = phan_giai_ten("đi làm", ["Đi làm buổi sáng", "Đi làm ca chiều"])
    assert ket.trung is None
    assert ket.mo_ho
    assert set(ket.ung_vien) == {"Đi làm buổi sáng", "Đi làm ca chiều"}


def test_khong_thay_thi_noi_khong_thay_chu_khong_doan_gan_dung():
    """Không có tầng Levenshtein, có chủ ý: đoán sai ở đây không phải hiểu nhầm một câu
    hỏi mà là chạy nhầm một chuỗi lệnh lên xe."""
    ket = phan_giai_ten("nghỉ trưa", DS)
    assert ket.trung is None
    assert ket.khong_thay


def test_giu_dau_tieng_viet_khi_so_khop():
    """Bỏ dấu thì `"Thư giãn"` và `"thu gian"` bằng nhau — hai cụm khác hẳn. STT tiếng
    Việt trả chữ có dấu nên không có lý do gì phải bỏ."""
    assert phan_giai_ten("thu gian", DS).khong_thay
    assert phan_giai_ten("thư giãn", DS).trung == "Thư giãn"

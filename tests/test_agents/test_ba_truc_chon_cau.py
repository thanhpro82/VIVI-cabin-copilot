"""Khoá từng luật đã đưa vào ở vòng tối ưu ba trục 18/08.

Mỗi test dưới đây khoá **một** luật, và mỗi luật ứng với một con số đo được trên
`eval/results/ba-truc/`. Không test nào ở đây khoá kết quả tổng — con số tổng là việc
của bàn cân, còn test là việc của hành vi.

Baseline trước vòng này: chính xác 46%, tự nhiên **18%**, p50 0 ms.
Sau vòng này:            chính xác 64%, tự nhiên **100%**, p50 0 ms.
"""

from __future__ import annotations

import pytest

from src.agents.nodes.speech_policy import (
    _cau,
    _gop_duoi_tran,
    _la_nhan,
    _them_cau_bat_buoc,
    _ung_vien,
    chon_cau_de_noi,
    lam_sach_de_noi,
    xep_hang_theo_lien_quan,
)
from src.rag.tu_nhien import dem_khuyet_tat


def _ev(text: str, **kw):
    return {"text": text, "has_variant_condition": False, "is_table": False, **kw}


# --- Dọn định dạng trang giấy ------------------------------------------------
# Khuyết tật áp đảo của baseline: 24/39 ca có xuống dòng trong chuỗi đưa vào TTS.


def test_xuong_dong_khong_duoc_vao_kenh_noi():
    assert lam_sach_de_noi("Khởi tạo cửa sổ điện:\nNếu không thể đóng.") == "Khởi tạo cửa sổ điện: Nếu không thể đóng."


def test_gach_dau_dong_bi_go_ke_ca_khi_co_ngoac_chen_giua():
    """Chuỗi thật 18/08 có dấu ngoặc của câu dẫn chen giữa dấu hai chấm và dấu gạch."""
    assert "- Kéo" not in lam_sach_de_noi('Để đổ thêm:" - Kéo nắp ra.')
    assert lam_sach_de_noi("- Nhả công tắc.") == "Nhả công tắc."


def test_gach_noi_giua_tu_phai_con_nguyen():
    """ "ca-pô" và "bán-tự-động" không phải gạch đầu dòng."""
    assert lam_sach_de_noi("Bình chứa đặt dưới nắp ca-pô.") == "Bình chứa đặt dưới nắp ca-pô."


def test_don_dinh_dang_khong_bo_chu_nao():
    """Chỉ khoảng trắng và ký tự đánh dấu bị dọn — ADR-015 không bị đụng tới."""
    goc = "Bơm lốp tới 260 kPa.\nKhông dùng cho thành bên."
    assert set(lam_sach_de_noi(goc).split()) == set(goc.split())


# --- Tách câu nhận biết xuống dòng -------------------------------------------


def test_tieu_de_va_doan_mo_bai_khong_con_dinh_lam_mot_cau():
    """Khối tiêu-đề-dán-liền-đoạn là nguyên nhân của 21/39 ca trượt trước vòng này."""
    cl = _cau("Khởi tạo cửa sổ điện:\nNếu không thể đóng cửa sổ, hãy thử lại.")
    assert len(cl) == 2
    assert cl[0] == "Khởi tạo cửa sổ điện:"


# --- Loại nhãn mục khỏi ứng viên ---------------------------------------------


def test_nhan_muc_bi_loai_khoi_ung_vien():
    """Nhãn trùng chữ với câu hỏi nhiều nhất đoạn nên thắng mọi xếp hạng — mà nó rỗng."""
    assert _la_nhan("Khởi tạo cửa sổ điện:") is True
    assert _la_nhan("Đèn cảnh báo và chỉ báo") is True
    assert _la_nhan("Giữ công tắc ở trạng thái kéo trong 2 giây.") is False


def test_cau_dai_thieu_dau_cham_khong_bi_goi_la_nhan():
    """Sổ tay có câu mất dấu chấm cuối do OCR; câu như thế dài hơn nhãn nhiều."""
    assert _la_nhan("A" * 120) is False


def test_toan_nhan_thi_van_noi_chu_khong_im_lang():
    cl = ["Tiêu đề một", "Tiêu đề hai"]
    assert _ung_vien(cl) == [0, 1]


def test_breadcrumb_khong_bao_gio_duoc_chon():
    """Đường dẫn mục lục đọc thành tiếng thì luôn vô dụng — không có ngoại lệ."""
    cl = _cau("Xem > Ghế > Điều chỉnh ghế ngồi > Tựa đầu. Trượt nút di chuyển để chỉnh ghế.")
    assert 0 not in _ung_vien(cl)


def test_cau_chi_nguon_khac_breadcrumb_va_phai_duoc_giu():
    """ "ghi trên nhãn ở khung cửa" là câu trả lời TỐT cho đoạn có biến thể."""
    cl = _cau("Áp suất lốp được ghi trên nhãn gắn ở khung cửa bên lái.")
    assert _ung_vien(cl) == [0]


# --- Gói ngân sách: bỏ qua câu quá dài, không dừng hẳn -----------------------


def test_cau_qua_dai_bi_bo_qua_chu_khong_lam_dung_ca_vong_goi():
    """Bản `break` khiến một tiêu đề 20 ký tự + một câu 200 ký tự phí 170 ký tự ngân sách."""
    ra = _gop_duoi_tran(["Ngắn.", "D" * 300 + ".", "Vừa đủ."], 60)
    assert "Ngắn." in ra and "Vừa đủ." in ra


# --- Khớp dạng câu hỏi với dạng câu trả lời ----------------------------------


@pytest.mark.parametrize(
    ("hoi", "mong_doi"),
    [
        ("Độ sâu gai lốp tối thiểu là bao nhiêu?", "2 mm"),
        ("Bật đèn sương mù thế nào?", "Chạm vào"),
        ("Nút cảnh báo nguy hiểm nằm ở đâu?", "nằm ở"),
    ],
)
def test_cau_dung_dang_thang_cau_mo_bai(hoi: str, mong_doi: str):
    """Câu mở bài lặp lại chữ của câu hỏi nên thắng trùng-chữ; câu trả lời thật thì không.

    Đây là chỗ 5 điểm chính xác đến từ (59% → 64%), và nó tốn vài chục micro giây.
    """
    cau_list = [
        "Đây là phần giới thiệu chung về chủ đề đang được hỏi tới trong tài liệu.",
        {
            "2 mm": "Nếu gai lốp mòn xuống còn 2 mm thì phải thay thế.",
            "Chạm vào": "Chạm vào biểu tượng Đèn sương mù phía sau.",
            "nằm ở": "Nút cảnh báo nằm ở bảng điều khiển trung tâm.",
        }[mong_doi],
    ]
    # Ngân sách chỉ đủ MỘT câu: hàm trả về theo thứ tự sổ tay, nên muốn đo *lựa chọn*
    # thì phải ép nó chỉ chọn được một.
    assert xep_hang_theo_lien_quan(cau_list, hoi, len(cau_list[1]) + 2) == [1]


def test_cau_khung_dien_ngon_bi_phat():
    """ "Phần sau đây mô tả…" là câu nói về việc sắp nói, không mang dữ kiện nào."""
    cau_list = [
        "Phần sau đây mô tả cách các ghế có thể được điều chỉnh.",
        "Trượt nút di chuyển theo hướng di chuyển dự định.",
    ]
    assert xep_hang_theo_lien_quan(cau_list, "Cách điều chỉnh ghế ngồi?", len(cau_list[1]) + 2) == [1]


# --- Cảnh báo đi kèm, nhưng chỉ trong phạm vi gần ----------------------------


def test_canh_bao_ngay_truoc_duoc_keo_theo():
    cl = ["CẢNH BÁO Không dùng cho thành bên lốp.", "Đầu tiên, tháo nắp van lốp."]
    assert _them_cau_bat_buoc(cl, [1]) == [0, 1]


def test_canh_bao_o_xa_khong_duoc_keo_theo():
    """Hỏi cách chỉnh ghế mà kéo về cảnh báo số người ngồi thì vừa vô dụng, vừa

    đẩy chính câu trả lời ra khỏi ngân sách — gặp thật ở RAG-109, 18/08.
    """
    cl = ["CẢNH BÁO Số người ngồi không được nhiều hơn số chỗ.", "Câu đệm một.", "Câu đệm hai.", "Trượt nút để chỉnh."]
    assert _them_cau_bat_buoc(cl, [3]) == [3]


def test_da_co_canh_bao_thi_khong_them_lan_nua():
    cl = ["CẢNH BÁO Không dùng cho thành bên.", "Tháo nắp van."]
    assert _them_cau_bat_buoc(cl, [0, 1]) == [0, 1]


# --- Bất biến ba trục trên một đoạn thật -------------------------------------

DOAN_THAT = (
    "Khởi tạo cửa sổ điện:\n"
    "Nếu không thể tự động đóng các cửa sổ thông qua chức năng nhanh, hãy khởi tạo lại.\n"
    "Để khởi tạo cửa sổ:\n"
    "- Kéo công tắc cửa sổ lên và đóng hoàn toàn cửa sổ.\n"
    "Giữ công tắc ở trạng thái kéo trong 2 giây.\n"
    "- Nhả công tắc."
)


def test_doan_that_khong_con_khuyet_tat_co_hoc_nao():
    """Trục tự nhiên: baseline 18% lượt sạch, nay 100%."""
    from src.agents.nodes.speech_policy import cau_noi_hoan_chinh

    noi = cau_noi_hoan_chinh(chon_cau_de_noi(_ev(DOAN_THAT), "Cách khởi tạo lại cửa sổ điện?"))
    assert dem_khuyet_tat(noi).khuyet_tat == []


def test_doan_that_khong_noi_moi_tieu_de():
    from src.agents.nodes.speech_policy import cau_noi_hoan_chinh

    noi = cau_noi_hoan_chinh(chon_cau_de_noi(_ev(DOAN_THAT), "Cách khởi tạo lại cửa sổ điện?"))
    assert noi.strip() != "Khởi tạo cửa sổ điện:"
    assert "2 giây" in noi or "công tắc" in noi

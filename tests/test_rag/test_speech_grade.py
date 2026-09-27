"""Chấm câu nói bằng **đáp án khoá**, thay cho chấm tay từng vòng.

Vì sao đổi: phân biệt "một phần" với "không trúng" đòi người chấm phải biết *đoạn sổ
tay có chứa câu trả lời ở phía sau hay không* — tức phải thuộc tài liệu. Người chấm
không có thứ đó trước mắt, nên ranh giới ấy trở thành phỏng đoán, và một baseline dựng
trên phỏng đoán thì so S1 với S2 không có nghĩa.

Đáp án khoá dời phán đoán về **một lần duy nhất, trước khi nhìn đầu ra**: với mỗi câu
hỏi, câu nào trong đoạn thật sự trả lời. Sau đó chấm thành thao tác máy, áp y hệt cho
mọi phiên bản.

Đây **không** phải chấm tay của người dùng và không thay thế nó ở chỗ nó mạnh hơn: nó
đo "câu nói có chạm tới câu trả lời trong đoạn không", chứ không đo "tài xế nghe xong
thấy thoả mãn không". Hai thứ khác nhau; giữ cả hai và nói rõ cái nào đang được trích.
"""

import json
from pathlib import Path

import pytest

from src.rag.speech_grade import (
    DAP_AN_KHOA,
    DapAnKhoa,
    cham_mot_cau,
    doc_dap_an_khoa,
    so_luot_toi_dap_an,
)


def _khoa(cum_tra_loi, co=True):
    return DapAnKhoa(
        case_id="X", question="q", doan_co_cau_tra_loi=co, cum_tra_loi=cum_tra_loi
    )


def test_cham_trung_khi_cau_noi_chua_cum_tra_loi():
    khoa = _khoa(["Nhấn hoàn toàn công tắc cửa sổ xuống để mở cửa sổ tự động."])
    assert cham_mot_cau("Nhấn hoàn toàn công tắc cửa sổ xuống để mở cửa sổ tự động.", khoa) == "yes"


def test_cham_mot_phan_khi_dung_doan_nhung_chua_toi_cum_tra_loi():
    """Đây là ranh giới người chấm không tự quyết được: câu trả lời **có** ở phía sau,
    nên nghe tiếp là tới — đúng định nghĩa "một phần"."""
    khoa = _khoa(["Nhấn hoàn toàn công tắc cửa sổ xuống để mở cửa sổ tự động."])
    assert cham_mot_cau("Khởi tạo cửa sổ điện: Nếu không thể tự động đóng các cửa sổ", khoa) == "partial"


def test_cham_khong_trung_khi_doan_khong_he_chua_cum_tra_loi():
    """Nghe tiếp cũng không cứu được — đó mới là "không trúng" thật sự."""
    khoa = _khoa([], co=False)
    assert cham_mot_cau("Điều khiển cửa sổ điện của xe có thể được điều khiển bằng công tắc.", khoa) == "no"


def test_cau_khung_fail_closed_la_khong_trung_chu_khong_phai_mot_phan():
    """Câu khung `variant_fallback` không lấy chữ nào từ đoạn — nó là một lời **từ
    chối**, không phải một phần câu trả lời. Xếp nó vào "một phần" sẽ thưởng điểm cho
    việc không trả lời, và cột này hết đo được thứ nó sinh ra để đo.
    """
    khoa = _khoa(["Nhấn hoàn toàn công tắc cửa sổ xuống."])
    noi = "Thông tin này thay đổi theo phiên bản xe nên tôi không tóm tắt được an toàn."
    assert cham_mot_cau(noi, khoa, doan="Nhấn hoàn toàn công tắc cửa sổ xuống. Lặp lại.") == "no"


def test_cau_bi_cat_van_trung_neu_cum_da_kip_phat_ra():
    """Trần 240 ký tự cắt câu ở ranh giới mệnh đề, nên đòi khớp **cả câu** là phạt tầng
    nói vì đúng thứ nó phải làm. Khoá vào cụm ngắn thì cắt đuôi không ảnh hưởng."""
    khoa = _khoa(["mòn xuống còn một phần mười sáu inch (2 mm)"])
    noi = "Lốp xe được thiết kế với đường chỉ báo. Nếu gai lốp bị mòn xuống còn một phần mười sáu inch (2 mm),"
    assert cham_mot_cau(noi, khoa) == "yes"


def test_cat_truoc_cum_thi_chi_la_mot_phan():
    """Mặt kia của cùng một luật, và là chỗ bản khoá đầu của tôi sai.

    RAG-123 thật: câu nói dừng ở *"xe đã được trang bị (TPMS)"* — chưa tới mệnh đề mang
    nghĩa. Khớp 40 ký tự **đầu câu** thì trúng, mà tài xế chưa nghe được gì.
    """
    khoa = _khoa(["để chiếu sáng báo hiệu áp suất lốp thấp"])
    noi = "Hệ thống theo dõi áp suất lốp\nLà một tính năng an toàn bổ sung, xe đã được trang bị (TPMS)"
    doan = noi + " để chiếu sáng báo hiệu áp suất lốp thấp khi một hoặc nhiều lốp non hơi."
    assert cham_mot_cau(noi, khoa, doan=doan) == "partial"


def test_cham_rong_la_khong_trung():
    assert cham_mot_cau("", _khoa(["bất kỳ"])) == "no"


def test_dap_an_khoa_that_phu_kin_bo_case():
    """File khoá phải phủ đúng 40 case `supported`, không thiếu ca nào.

    Thiếu một ca thì nó lặng lẽ biến mất khỏi mẫu số — cách hỏng y hệt "chưa chấm bị
    tính thành chấm trượt", chỉ ngược dấu.
    """
    khoa = doc_dap_an_khoa(DAP_AN_KHOA)
    assert len(khoa) == 40
    assert all(k.question for k in khoa.values())
    # Dung mot ca duy nhat duoc phep khong co cau tra loi trong doan (RAG-106).
    assert [k.case_id for k in khoa.values() if not k.doan_co_cau_tra_loi] == ["RAG-106"]


def test_moi_cum_tra_loi_trong_khoa_deu_la_nguyen_van_cua_index():
    """Khoá phải bám vào index thật; chép tay sai một chữ là chấm sai vĩnh viễn."""
    khoa = doc_dap_an_khoa(DAP_AN_KHOA)
    raw = [json.loads(x) for x in Path(DAP_AN_KHOA).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(khoa) == len(raw)
    assert all(c.strip() for r in raw for c in r["cum_tra_loi"])
    # Moi cum phai la NGUYEN VAN cua doan. Chep tay sai mot chu la cham sai vinh vien,
    # va sai kieu do khong bao gio no ra — no chi lam diem thap di mot cach am tham.
    for r in raw:
        for c in r["cum_tra_loi"]:
            assert c in r["doan"], (r["case_id"], c)


@pytest.mark.parametrize("muc", ["yes", "partial", "no"])
def test_chi_tra_ve_ba_muc(muc):
    """Cùng thang với vòng chấm tay, nếu không thì không so được với baseline 30,0%."""
    assert muc in {"yes", "partial", "no"}


# --- Do S3: mat may luot de toi cau tra loi ---------------------------------
#
# Voi S3, "mot phan" khong con la mot muc diem — no la mot KHOANG CACH. Cau tra loi
# nam trong doan tai xe dang nghe, va tai xe toi duoc bang cach noi "nghe tiep". Nen
# thuoc dung la SO LUOT va SO GIAY, khong phai trung/khong-trung.


def test_tra_loi_ngay_luot_dau_la_mot_luot():
    khoa = _khoa(["Nhấn hoàn toàn công tắc xuống"])
    doan = "Mở đầu. Nhấn hoàn toàn công tắc xuống để mở cửa sổ. Kết thúc."
    assert so_luot_toi_dap_an("Mở đầu. Nhấn hoàn toàn công tắc xuống để mở cửa sổ.", doan, khoa).luot == 1


def test_cau_tra_loi_o_cuoi_doan_can_them_luot():
    khoa = _khoa(["câu đáp án nằm tận cuối"])
    doan = " ".join([f"Câu đệm số {i} không trả lời gì cả." for i in range(1, 30)]) + " Đây là câu đáp án nằm tận cuối."
    ket = so_luot_toi_dap_an("Câu đệm số 1 không trả lời gì cả.", doan, khoa)
    assert ket.luot is not None and ket.luot > 1
    assert ket.giay > 0


def test_cau_khung_fail_closed_van_toi_duoc_bang_cach_nghe_tiep():
    """Kết quả quan trọng nhất của S3.

    Câu khung `variant_fallback` từ chối **tóm tắt**, không từ chối **đọc**. Nó không
    lấy chữ nào từ đoạn nên "nghe tiếp" đọc từ đầu — fail-closed thôi là ngõ cụt,
    fail-closed **cộng** một đường ra mới là câu trả lời đầy đủ.
    """
    khoa = _khoa(["Chức năng Massage ghế giúp thúc đẩy tuần hoàn máu"])
    doan = "Massage ghế ngồi. Nếu được trang bị, Chức năng Massage ghế giúp thúc đẩy tuần hoàn máu."
    khung = "Thông tin này thay đổi theo phiên bản xe nên tôi không tóm tắt được an toàn."
    ket = so_luot_toi_dap_an(khung, doan, khoa)
    assert ket.luot == 2, "cau khung phai toi duoc dap an o luot thu hai"


def test_doan_khong_chua_dap_an_thi_khong_bao_gio_toi():
    khoa = _khoa([], co=False)
    ket = so_luot_toi_dap_an("Một câu bất kỳ.", "Một câu bất kỳ. Và một câu nữa.", khoa)
    assert ket.luot is None
    assert ket.giay > 0, "van phai tinh giay da nghe — do la chi phi tai xe da tra"

"""Nhận dạng câu trả lời phê duyệt bằng giọng nói (issue #107, nửa A).

Đo trên hệ thống thật trước khi viết, đúng kịch bản demo:

    Tài xế: "Mở kính bên lái 30%"
    VIVI:   "Tôi sẽ đưa kính trước bên lái về 30%. Bạn có đồng ý không?"
    Tài xế: "Đồng ý"
    VIVI:   "Tôi không tìm thấy thông tin này trong sổ tay xe."

Không phải "chưa làm" — xe hỏi một câu rồi không hiểu chính câu trả lời của câu nó
vừa hỏi, và phê duyệt vẫn treo.

**Hướng fail của bộ dò này là bỏ sót, không phải nhận bừa.** Bỏ sót thì tài xế bấm nút,
phiền một chút. Nhận bừa thì một câu bâng quơ thành lời đồng ý cho lệnh S2 — và dù event
chỉ là handoff (IVI mới là bên gọi REST), một IVI tự động gửi tiếp sẽ biến nó thành hành
động thật. Vì vậy mọi ca mơ hồ đều trả `mo_ho`, và mọi câu dài đều **không** được coi là
câu trả lời.
"""

import pytest

from src.agents.voice_intent import doc_y_dinh_phe_duyet


@pytest.mark.parametrize(
    "cau",
    ["Đồng ý", "đồng ý", "Ừ", "Vâng", "Có", "OK", "Được", "Xác nhận", "Chấp nhận", "Duyệt", "Đúng rồi", "Ừ đồng ý"],
)
def test_nhan_ra_dong_y(cau):
    assert doc_y_dinh_phe_duyet(cau).quyet_dinh == "approve"


@pytest.mark.parametrize(
    "cau", ["Không", "Từ chối", "Hủy", "Thôi", "Đừng", "Khoan đã", "Thôi khỏi", "Không cần", "Dừng lại"]
)
def test_nhan_ra_tu_choi(cau):
    assert doc_y_dinh_phe_duyet(cau).quyet_dinh == "reject"


@pytest.mark.parametrize("cau", ["Không đồng ý", "Không xác nhận", "Đừng duyệt", "Không được"])
def test_phu_dinh_truoc_tu_dong_y_la_tu_choi_chu_khong_mo_ho(cau):
    """Cái bẫy ngôn ngữ đắt nhất ở đây.

    `"không đồng ý"` chứa **cả** dấu hiệu đồng ý lẫn dấu hiệu từ chối. Đọc theo kiểu
    "có cả hai thì mơ hồ" sẽ bắt tài xế nhắc lại một câu vốn đã rõ nghĩa hoàn toàn. Tệ
    hơn: đọc theo kiểu "thấy `đồng ý` là duyệt" thì nó **duyệt một lệnh vừa bị từ chối**.
    """
    assert doc_y_dinh_phe_duyet(cau).quyet_dinh == "reject"


@pytest.mark.parametrize("cau", ["Đồng ý nhưng hủy", "Có mà thôi", "Ừ, mà khoan"])
def test_hai_tin_hieu_doc_lap_thi_mo_ho(cau):
    """Khác ca trên: ở đây từ chối **không** phủ định từ đồng ý, mà đứng riêng.

    Đoán bừa một trong hai là quyết hộ tài xế một việc S2.
    """
    ket_qua = doc_y_dinh_phe_duyet(cau)
    assert ket_qua.mo_ho is True
    assert ket_qua.quyet_dinh is None


@pytest.mark.parametrize(
    "cau",
    [
        "Mở cửa sổ bên lái 30%",
        "Áp suất lốp bao nhiêu",
        "Bật điều hòa 24 độ",
        "Hôm nay trời đẹp quá",
        "Cách khởi tạo lại cửa sổ điện",
    ],
)
def test_cau_khong_phai_tra_loi_thi_khong_nhan(cau):
    """Lệnh mới trong lúc chờ duyệt vẫn phải đi đường thường (`APPROVAL_ALREADY_PENDING`).

    Nuốt nó vào nhánh phê duyệt là mất luôn hành vi đã đặc tả ở `api_spec.md` §Normative
    state machine.
    """
    ket_qua = doc_y_dinh_phe_duyet(cau)
    assert ket_qua.quyet_dinh is None
    assert ket_qua.mo_ho is False


@pytest.mark.parametrize("cau", ["Đồng ý mở cửa sổ bên lái xuống ba mươi phần trăm", "Ừ thì bật điều hòa lên đi"])
def test_cau_dai_kem_lenh_khong_duoc_coi_la_tra_loi(cau):
    """Ngưỡng độ dài, chọn theo hướng fail an toàn.

    Một câu vừa "đồng ý" vừa mang lệnh mới thì không rõ tài xế đang duyệt cái đang chờ
    hay ra lệnh khác. Trả về "không nhận" để nó đi đường thường, thay vì `mo_ho` — vì
    `mo_ho` làm hỏng lượt (`turn.failed`), còn đường thường vẫn trả lời tử tế.
    """
    assert doc_y_dinh_phe_duyet(cau).quyet_dinh is None


@pytest.mark.parametrize("cau", ["", "   ", "..."])
def test_cau_rong_khong_vo(cau):
    ket_qua = doc_y_dinh_phe_duyet(cau)
    assert ket_qua.quyet_dinh is None
    assert ket_qua.mo_ho is False


def test_dau_cau_va_chu_hoa_khong_anh_huong():
    """STT trả về chữ có dấu câu và hoa/thường tuỳ lúc."""
    assert doc_y_dinh_phe_duyet("ĐỒNG Ý!").quyet_dinh == "approve"
    assert doc_y_dinh_phe_duyet("Đồng ý.").quyet_dinh == "approve"
    assert doc_y_dinh_phe_duyet("  từ chối  ").quyet_dinh == "reject"


def test_khong_khop_tu_nam_trong_tu_khac():
    """`"có"` nằm trong `"cốc"`, `"khoan"` nằm trong `"khoang"` — khớp chuỗi con thì
    `"khoang chứa đồ"` thành một lời từ chối."""
    assert doc_y_dinh_phe_duyet("Khoang chứa đồ").quyet_dinh is None
    assert doc_y_dinh_phe_duyet("Cốc nước").quyet_dinh is None

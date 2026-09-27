"""Cổng của tầng nén. Mọi ca ở đây đến từ **đầu ra thật đã đọc bằng mắt**, không phải nghĩ ra.

`src/agents/tom_tat.py` trước file này không có test nào: bảy cổng quyết định câu nào
tới tai tài xế chỉ được bàn cân che, mà bàn cân đo phân bố chứ không khoá hành vi.

Đợt chấm tay 20/08 tìm ra một bug trong `ket_lung_chung` mà không thước tự động nào
thấy. Nên file này bắt đầu từ đúng chỗ ấy.
"""

from __future__ import annotations

import pytest

from src.agents.tom_tat import ket_lung_chung, qua_cong, sua_ngoac_lung

#: Tham số y hệt `QwenTomTat` dùng ở sản phẩm. Đừng đo cổng bằng mặc định của
#: `qua_cong` — chúng khác nhau, và đo nhầm tham số thì con số nói về một hệ khác.
SAN_PHAM = {"dung_sai": 1, "san_giu": 0.0, "top_mang_tin": 0}


@pytest.mark.parametrize(
    "cau",
    [
        "Nút công tắc khóa cửa sổ điện tắt chức năng điều khiển cửa sổ điện hàng ghế sau.",
        "Đẩy phần rộng vào trong, phần hẹp của tay nắm sẽ xoay ra ngoài.",
        "Nhấn vào Sấy kính/Khử sương kính trước",
        "Di chuyển ghế về phía trước hoặc phía sau.",
    ],
)
def test_tu_chi_vi_tri_ket_cau_duoc(cau: str):
    """`sau`, `trước`, `ngoài` kết câu được — chúng là danh/tính từ chỉ vị trí.

    Đây là bug đợt chấm tay 20/08 tìm ra: `ket_lung_chung` dùng nguyên `TU_QUAN_HE`,
    mà tập ấy chứa các từ này vì chúng **cũng** làm giới từ. Kết quả là **4 trên 8**
    lần cổng `cau_cut` nổ là bác oan — một nửa số ca của cổng nổ nhiều nhất.

    Bốn câu dưới đây là đầu ra thật của Qwen3-4B trên bốn ca thật.
    """
    assert ket_lung_chung(cau) is False, cau


@pytest.mark.parametrize(
    "cau",
    [
        "Đèn nháy cảnh báo có thể hoạt động ngay cả khi xe đang tắt máy và",
        "Chạm vào Cài đặt > Cài đặt Trợ lý giọng nói và",
        "Nếu hệ thống bị trục trặc, đèn cảnh báo sẽ sáng và",
        "Nhấn công tắc để",
        "Kiểm tra áp suất lốp,",
        "",
    ],
)
def test_ket_bang_tu_noi_hoac_dau_treo_van_bi_bat(cau: str):
    """Nửa còn lại: thu hẹp tập **không** được làm mất khả năng bắt câu cụt thật.

    Bốn câu đầu cũng là đầu ra thật — model xoá vế sau rồi bỏ lại chữ `và` nó đã chèn
    để nối.
    """
    assert ket_lung_chung(cau) is True, cau


def test_hai_cong_dung_hai_tap_khac_nhau_va_do_la_co_y():
    """`cau_cut` hỏi "câu đã nói xong chưa", `chen_tu_quan_he` hỏi "có chèn thêm không".

    Hai câu hỏi khác nhau nên hai tập khác nhau. Chèn `sau` mà nguồn không có vẫn là
    khẳng định một quan hệ sổ tay không nói, nên cổng chèn giữ nguyên `TU_QUAN_HE` đầy
    đủ — kể cả khi `cau_cut` đã tha lớp từ ấy ở vị trí cuối câu.
    """
    goc = "Đèn sương mù phía sau lắp trên cản xe."
    assert qua_cong(goc, "Đèn sương mù lắp trên cản xe phía sau.", **SAN_PHAM)[0] is False


def test_ban_nen_hop_le_thi_qua_het_cong():
    """Ca thật của RAG-107, và là ca mà bug `cau_cut` từng bác oan.

    Ví dụ đầu tiên tôi **nghĩ ra** cho test này lại bị `lech_phan_cuc` bác đúng: nguồn
    có "mòn KHÔNG đều" mà bản nén tôi tự viết đánh rơi chữ phủ định. Giữ lại mẩu chuyện
    ấy vì nó là lý do file này chỉ dùng đầu ra thật — ví dụ tự nghĩ ra mang theo giả
    định của người nghĩ, và ở đây giả định ấy sai.
    """
    goc = (
        "- Đẩy phần rộng của tay nắm cửa phẳng vào trong, phần hẹp của tay nắm sẽ xoay ra ngoài, "
        "cho phép bạn giữ tay nắm và kéo cửa mở."
    )
    tom = "Đẩy phần rộng của tay nắm cửa phẳng vào trong và phần hẹp của tay nắm sẽ xoay ra ngoài."
    assert qua_cong(goc, tom, **SAN_PHAM) == (True, "")


@pytest.mark.parametrize(
    ("ten", "goc", "tom", "cong"),
    [
        (
            "bịa nhãn CẢNH BÁO",
            "Nếu cửa sổ gặp lực cản khi đóng, chuyển động sẽ dừng và trở về vị trí mở.",
            "CẢNH BÁO: cửa sổ gặp lực cản dừng và trở về vị trí mở.",
            "khong_phai_day_con",
        ),
        (
            "rơi điều kiện trang bị",
            "Nếu được trang bị, Chức năng Massage ghế giúp thúc đẩy tuần hoàn máu.",
            "Chức năng Massage ghế giúp thúc đẩy tuần hoàn máu.",
            "mat_dieu_kien",
        ),
        (
            "rơi liên từ chọn",
            "Dùng khi lái trong sương mù, tuyết hoặc điều kiện khác mà tầm nhìn hạn chế.",
            "Dùng khi lái trong sương mù tuyết tầm nhìn hạn chế.",
            "mat_tu_noi_mang_nghia",
        ),
    ],
)
def test_ba_ca_that_van_bi_bac_dung_cong(ten: str, goc: str, tom: str, cong: str):
    """Ba lỗi thật của Qwen3-4B, mỗi lỗi phải bị bắt ở **đúng** cổng của nó.

    Khoá cả tên cổng chứ không chỉ khoá "bị bác": bác đúng vì lý do sai là thứ đã che
    mất bug `cau_cut` suốt một ngày — bàn cân thấy tỷ lệ bác đẹp và không ai hỏi thêm.
    """
    assert qua_cong(goc, tom, **SAN_PHAM) == (False, cong), ten


# --- Sửa ngoặc lửng: cổng DUY NHẤT sửa thay vì bác --------------------------


def test_bo_phu_chu_mo_ngoac_khong_dong():
    """Ca thật RAG-130 — model cắt giữa phụ chú và bỏ lại một dấu ngoặc không đóng.

    Bác thì rơi về nguyên văn 100%, mất trọn phần nén. Sửa thì ra đúng câu mà người
    đọc thấy dễ hiểu hơn cả bản gốc — phụ chú ấy vốn làm câu rối thêm.
    """
    tho = "Số có 3 chữ số là chiều rộng của lốp (cạnh thành lốp sang"

    assert sua_ngoac_lung(tho) == "Số có 3 chữ số là chiều rộng của lốp"


@pytest.mark.parametrize(
    "cau",
    [
        "Số có 3 chữ số là chiều rộng của lốp (cạnh thành lốp sang cạnh khác).",
        "Đèn ban ngày (DRL) giúp tăng khả năng quan sát xe cộ trên đường.",
        "Không có ngoặc nào trong câu này cả.",
        "",
    ],
)
def test_ngoac_can_bang_hoac_vang_mat_thi_khong_dong_vao(cau: str):
    """Phép sửa phải **không làm gì** khi không có gì hỏng. Một phép sửa hay tay là một
    phép sửa sẽ cắt nhầm một câu lành."""
    assert sua_ngoac_lung(cau) == cau


def test_sua_chi_xoa_nen_khong_the_pha_tinh_day_con():
    """Đây là lý do phép sửa này an toàn còn `cau_cut` thì không được sửa.

    Chỉ xoá thì tính dãy con không hỏng thêm được. Ngược lại, cắt chữ nối ở cuối câu
    (`"Nhấn công tắc để"` -> `"Nhấn công tắc."`) sẽ giấu một mất mát thật sau một câu
    trông lành lặn — ở đó bác mới đúng.
    """
    goc = "Số có 3 chữ số là chiều rộng của lốp (cạnh thành lốp sang cạnh khác)."
    assert qua_cong(goc, sua_ngoac_lung("Số có 3 chữ số là chiều rộng của lốp (cạnh thành lốp sang"), **SAN_PHAM) == (
        True,
        "",
    )

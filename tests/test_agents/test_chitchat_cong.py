"""Bốn lớp cổng (spec SP-2 §2.2), mỗi lớp một test, thứ tự cố định. Không bao giờ
phát chuỗi đã bị chặn."""

from src.agents.nodes.chitchat_cong import CAU_CHUYEN_HUONG_SO, CAU_MAU_CHUNG, qua_cong_chitchat


def test_cau_sach_di_qua_nguyen_ven():
    assert qua_cong_chitchat("Chào bạn, chúc một ngày lái xe nhẹ nhàng!") == (
        "Chào bạn, chúc một ngày lái xe nhẹ nhàng!",
        "qua",
    )


def test_a_he_chu_la_roi_ve_cau_mau():
    """SPIKE-004 RAG-105: model xen nguyên câu tiếng Trung — dùng lại bộ dò tu_nhien."""
    chuoi, cong = qua_cong_chitchat("Chào bạn 你好, đi đâu đấy?")
    assert cong == "he_chu_la"
    assert chuoi == CAU_MAU_CHUNG


def test_b_qua_dai_cat_o_ranh_gioi_cau():
    dai = "Câu một đủ ngắn. " * 10 + "Câu cuối rất dài " * 20 + "."
    chuoi, cong = qua_cong_chitchat(dai)
    assert cong == "qua_dai"
    assert len(chuoi) <= 240
    assert chuoi.endswith(".")


def test_b_qua_dai_khong_co_ranh_gioi_thi_cau_mau():
    chuoi, cong = qua_cong_chitchat("a" * 300)
    assert (chuoi, cong) == (CAU_MAU_CHUNG, "qua_dai")


def test_c_so_ky_thuat_thanh_cau_chuyen_huong():
    """Chitchat KHÔNG được nói thông số xe — đó là việc của sổ tay (ADR-015)."""
    chuoi, cong = qua_cong_chitchat("Xe này chạy được 450 km một lần sạc đấy!")
    assert cong == "so_ky_thuat"
    assert chuoi == CAU_CHUYEN_HUONG_SO


def test_d_noi_da_lam_gi_tren_xe_roi_ve_cau_mau():
    for cau in ("Tôi đã bật điều hòa cho bạn rồi!", "Đã mở cửa sổ nhé."):
        chuoi, cong = qua_cong_chitchat(cau)
        assert cong == "noi_da_lam", cau
        assert chuoi == CAU_MAU_CHUNG


def test_rong_roi_ve_cau_mau():
    """Rỗng đi chung cửa với hệ chữ lạ: không có gì để phát thì phát câu mẫu."""
    assert qua_cong_chitchat("   ") == (CAU_MAU_CHUNG, "he_chu_la")


def test_thu_tu_lop_a_truoc_lop_c():
    """Cùng vỡ nhiều lớp thì tên cổng là lớp ĐẦU TIÊN vỡ — để eval đếm ổn định."""
    _, cong = qua_cong_chitchat("你好 450 km")
    assert cong == "he_chu_la"


def test_e_khang_dinh_ve_hanh_trinh_ma_model_khong_biet():
    """Ca thật `CC-AB05` (run `chitchat/20260823T010523`): tài xế hỏi "Còn xa không
    nhỉ", model đáp "Đi tiếp một chút nữa thôi, **đích đến gần rồi** nha!".

    Chitchat không đọc trạng thái dẫn đường — nó không có cách nào biết còn bao xa.
    Cùng lớp với cổng (c): khẳng định một dữ kiện mình không có.
    """
    for cau in (
        "Đi tiếp một chút nữa thôi, đích đến gần rồi nha!",
        "Sắp tới nơi rồi, bạn cố thêm chút nhé!",
        "Điểm đến cũng gần thôi, đừng lo!",
    ):
        chuoi, cong = qua_cong_chitchat(cau)
        assert cong == "doan_hanh_trinh", cau
        assert chuoi == CAU_MAU_CHUNG


def test_e_khong_chan_oan_cau_khong_khang_dinh_gi():
    """Hẹp có chủ đích: động viên chung chung không phải khẳng định vị trí."""
    for cau in ("Cố lên nhé, tôi ở đây với bạn!", "Đường xa thì mình nghỉ giữa chừng nha!"):
        assert qua_cong_chitchat(cau)[1] == "qua", cau

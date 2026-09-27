"""Cổng chặn egress phải **bắt được** trước khi nó được dùng làm bằng chứng.

Một diễn tập offline luôn xanh vì cổng hỏng thì tệ hơn không có diễn tập nào: nó biến
"chưa ai kiểm" thành "đã kiểm rồi" mà không đổi gì về sự thật. Nên file này chủ yếu là
các ca cổng **phải đỏ**.
"""

import socket

import pytest

from src.offline_guard import ChanMangError, CongChanEgress, ket_noi_ngoai_loopback, quan_sat_duoc_ket_noi


def test_chan_ket_noi_ra_dia_chi_ngoai():
    with CongChanEgress() as cong:
        with pytest.raises(ChanMangError):
            socket.create_connection(("93.184.216.34", 80), timeout=1)
    assert [(t.kieu, t.dich) for t in cong.lan_thu] == [("connect", "93.184.216.34")]


def test_chan_phan_giai_ten_mien():
    """DNS là tín hiệu sớm nhất: cần phân giải tên nghĩa là đã định gọi ra ngoài."""
    with CongChanEgress() as cong:
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo("huggingface.co", 443)
    assert [(t.kieu, t.dich) for t in cong.lan_thu] == [("getaddrinfo", "huggingface.co")]


def test_chan_ca_connect_ex_khong_chi_connect():
    """`connect_ex` trả mã lỗi thay vì ném — thư viện dùng nó để "thử im lặng".

    Bỏ sót nhánh này thì một client lịch sự nhất lại là client lọt lưới.
    """
    with CongChanEgress() as cong:
        s = socket.socket()
        try:
            with pytest.raises(ChanMangError):
                s.connect_ex(("8.8.8.8", 53))
        finally:
            s.close()
    assert cong.lan_thu[0].dich == "8.8.8.8"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.53"])
def test_loopback_van_song(host):
    """Backend, broker, simulator và WS đều nói với nhau qua loopback.

    Chặn cả loopback thì diễn tập không đo được gì ngoài chính nó.
    """
    with CongChanEgress() as cong:
        socket.getaddrinfo(host, 80)
    assert cong.lan_thu == []


def test_bind_nghe_moi_giao_dien_khong_bi_tinh_la_goi_ra_ngoai():
    """`0.0.0.0` là địa chỉ để **nghe**. Nghe không phải là gọi ra ngoài."""
    with CongChanEgress() as cong:
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", 0))
        finally:
            s.close()
    assert cong.lan_thu == []


def test_go_cong_thi_socket_tro_lai_nguyen_ban():
    """Cổng vá trên `socket` của cả tiến trình, nên rò rỉ ra ngoài `with` sẽ làm hỏng
    mọi test chạy sau — kiểu hỏng vừa khó tìm vừa phụ thuộc thứ tự chạy."""
    goc = (socket.socket.connect, socket.getaddrinfo, socket.create_connection, socket.socket.connect_ex)
    with CongChanEgress():
        assert socket.getaddrinfo is not goc[1]
    assert (socket.socket.connect, socket.getaddrinfo, socket.create_connection, socket.socket.connect_ex) == goc


def test_go_cong_ca_khi_co_exception():
    goc = socket.getaddrinfo
    with pytest.raises(RuntimeError):
        with CongChanEgress():
            raise RuntimeError("bùm")
    assert socket.getaddrinfo is goc


def test_loi_cung_ho_oserror_de_code_fail_open_bat_duoc():
    """Cố ý không dùng exception riêng.

    Nếu diễn tập ném ra một loại lỗi mà production không bao giờ thấy, ta đang đo hành
    vi của một hệ thống khác với hệ thống thật — mọi `except OSError` fail-open sẽ
    không chạy, và drill sẽ báo hỏng ở chỗ thực tế không hỏng.
    """
    assert issubclass(ChanMangError, OSError)
    assert issubclass(socket.gaierror, OSError)


def test_ghi_lai_cho_goi_trong_src():
    """Báo cáo phải chỉ ra **ai** gọi, không chỉ "có người gọi"."""

    def _mot_ham_trong_src():
        socket.getaddrinfo("example.com", 80)

    with CongChanEgress() as cong:
        with pytest.raises(socket.gaierror):
            _mot_ham_trong_src()
    # Test nằm trong tests/ chứ không phải src/, nên không truy ra khung `src` nào —
    # chốt đúng điều đó thay vì giả vờ ngược lại.
    assert cong.lan_thu[0].goi_tu() == "(không xác định)"
    assert "_mot_ham_trong_src" in cong.lan_thu[0].stack


# --- Lop quan sat tang HDH ---------------------------------------------------
#
# Lop nay bu dung diem mu cua cong Python: no thay ca socket do C++ mo, vi kernel
# khong quan tam ai goi. Doi lai no khong biet AI goi va no chi lay mau.


def test_ket_noi_loopback_khong_bi_tinh_la_ra_ngoai():
    """Backend ↔ broker ↔ simulator đều đi qua loopback; báo chúng là egress thì
    mọi lượt chạy thật đều đỏ và diễn tập thành vô dụng."""
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    cong_so = server.getsockname()[1]
    da_nhan = threading.Event()

    def _nhan():
        conn, _ = server.accept()
        da_nhan.set()
        conn.close()

    luong = threading.Thread(target=_nhan, daemon=True)
    luong.start()
    client = socket.create_connection(("127.0.0.1", cong_so), timeout=2)
    try:
        da_nhan.wait(timeout=2)
        assert ket_noi_ngoai_loopback() == []
    finally:
        client.close()
        server.close()
        luong.join(timeout=2)


def test_khong_do_duoc_thi_tra_rong_chu_khong_no(monkeypatch):
    """`psutil` vắng mặt hoặc HĐH từ chối là chuyện có thật trên máy khác.

    Trả rỗng chứ không ném — nhưng người gọi phải phân biệt được "không đo được" với
    "đã đo và sạch", nếu không một máy thiếu `psutil` sẽ cho ra bản báo cáo trông y hệt
    một máy đã kiểm đủ. Đó là việc của `quan_sat_duoc_ket_noi`, và manifest ghi nó.
    """
    import src.offline_guard as guard

    monkeypatch.setattr(guard, "quan_sat_duoc_ket_noi", lambda: False)
    assert guard.ket_noi_ngoai_loopback() == []


def test_hai_ham_tra_loi_nhat_quan_tren_may_nay():
    """Nếu quan sát được thì kết quả phải là một danh sách; không được `None`."""
    if quan_sat_duoc_ket_noi():
        assert isinstance(ket_noi_ngoai_loopback(), list)

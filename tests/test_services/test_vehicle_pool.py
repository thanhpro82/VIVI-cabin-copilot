"""Pool xe ảo: cấp, gia hạn, hết hạn, hết pool, và sức chứa.

Đồng hồ giả tiêm qua `dong_ho=` nên không test nào phải ngủ thật.
"""

import pytest

from src.config import Settings
from src.services.vehicle_pool import SucChua, VehiclePool

BA_XE = ("vehicle-demo-01", "vivi-xe-02", "vivi-xe-03")
TTL = 180.0


class DongHoGia:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def tien(self, giay: float) -> None:
        self.t += giay


def _pool(vehicle_ids=BA_XE, ttl=TTL):
    return VehiclePool(vehicle_ids, lease_ttl_s=ttl, dong_ho=DongHoGia())


def _pool_va_dong_ho(vehicle_ids=BA_XE, ttl=TTL):
    dh = DongHoGia()
    return VehiclePool(vehicle_ids, lease_ttl_s=ttl, dong_ho=dh), dh


# -- dựng pool -------------------------------------------------------------


def test_pool_rong_hoac_trung_id_bi_tu_choi():
    """Hai cấu hình sai này im lặng thì rất khó lần ra: pool rỗng làm mọi phiên
    chỉ-xem, id trùng làm hai phiên tưởng có xe riêng mà thật ra dùng chung."""
    with pytest.raises(ValueError):
        VehiclePool([], lease_ttl_s=TTL)
    with pytest.raises(ValueError):
        VehiclePool(["a", "a"], lease_ttl_s=TTL)
    with pytest.raises(ValueError):
        VehiclePool(["a"], lease_ttl_s=0)


def test_xe_demo_luon_la_o_so_khong():
    """`vehicle-demo-01` phải được cấp trước tiên — màn kỹ sư, healthcheck compose và
    tài liệu đều trỏ vào nó, nên một người dùng duy nhất phải rơi đúng vào xe đó."""
    pool = _pool()
    assert pool.thue("s1") == "vehicle-demo-01"


# -- cấp và bất biến một-phiên-một-xe --------------------------------------


def test_moi_phien_mot_xe_khac_nhau():
    pool = _pool()
    assert [pool.thue(f"s{i}") for i in range(1, 4)] == list(BA_XE)


def test_thue_lai_khong_cap_them_xe():
    """Bất biến quan trọng nhất: `thue()` chạy ở mỗi lượt, gọi lại phải trả CÙNG xe.
    Không có nó thì pool cạn sau ba câu nói của một người."""
    pool = _pool()
    dau = pool.thue("s1")
    assert [pool.thue("s1") for _ in range(5)] == [dau] * 5
    assert pool.suc_chua().dang_dung == 1


# -- hết pool --------------------------------------------------------------


def test_het_pool_tra_none_chu_khong_no():
    pool = _pool()
    for i in range(1, 4):
        assert pool.thue(f"s{i}") is not None
    assert pool.thue("s4") is None
    assert pool.suc_chua() == SucChua(tong=3, dang_dung=3)


def test_tra_xe_som_thi_nguoi_ke_tiep_thue_duoc():
    pool = _pool()
    for i in range(1, 4):
        pool.thue(f"s{i}")
    assert pool.thue("s4") is None

    assert pool.tra("s2") == "vivi-xe-02"
    assert pool.tra("s2") is None, "trả hai lần không được nhả thêm gì"
    assert pool.thue("s4") == "vivi-xe-02"


# -- hết hạn ---------------------------------------------------------------


def test_het_han_thu_hoi_xe():
    pool, dh = _pool_va_dong_ho(vehicle_ids=("x1",))
    assert pool.thue("s1") == "x1"
    assert pool.thue("s2") is None

    dh.tien(TTL + 1)
    assert pool.thue("s2") == "x1", "hết hạn thì xe phải quay lại pool"
    assert pool.xe_cua("s1") is None


def test_gia_han_giu_duoc_xe():
    pool, dh = _pool_va_dong_ho(vehicle_ids=("x1",))
    pool.thue("s1")
    for _ in range(5):
        dh.tien(TTL * 0.9)
        assert pool.gia_han("s1") == "x1"
    assert pool.thue("s2") is None, "s1 vẫn đang giữ xe"


def test_gia_han_khong_cap_moi():
    """`_touch()` gọi ở mọi đường vào; nếu nó cấp mới thì một phiên chỉ-xem sẽ lặng lẽ
    chiếm xe giữa chừng ngay khi có người khác rời đi."""
    pool = _pool(vehicle_ids=("x1",))
    assert pool.gia_han("s1") is None
    assert pool.suc_chua().dang_dung == 0


def test_doc_khong_gia_han():
    """`xe_cua()` chỉ đọc. Nếu nó gia hạn thì một client poll `GET /vehicle/state`
    mỗi 2 giây sẽ giữ xe vô thời hạn dù người dùng đã bỏ đi."""
    pool, dh = _pool_va_dong_ho(vehicle_ids=("x1",))
    pool.thue("s1")
    dh.tien(TTL * 0.5)
    assert pool.xe_cua("s1") == "x1"
    dh.tien(TTL * 0.6)  # tổng đã vượt TTL
    assert pool.xe_cua("s1") is None


# -- tra cứu ngược, cho ui.policy ------------------------------------------


def test_phien_cua_xe():
    pool = _pool()
    pool.thue("s1")
    pool.thue("s2")
    assert pool.phien_cua("vehicle-demo-01") == ["s1"]
    assert pool.phien_cua("vivi-xe-02") == ["s2"]
    assert pool.phien_cua("vivi-xe-03") == [], "xe rảnh không có phiên nào"


def test_phien_cua_bo_qua_hop_dong_het_han():
    """Nếu quên quét hết hạn ở đây thì `ui.policy` sẽ phát cho một phiên đã rời đi."""
    pool, dh = _pool_va_dong_ho()
    pool.thue("s1")
    dh.tien(TTL + 1)
    assert pool.phien_cua("vehicle-demo-01") == []


# -- sức chứa --------------------------------------------------------------


def test_suc_chua_la_nguon_duy_nhat():
    pool = _pool()
    assert pool.suc_chua().as_dict() == {"tong": 3, "dang_dung": 0, "con_trong": 3}
    pool.thue("s1")
    pool.thue("s2")
    assert pool.suc_chua().as_dict() == {"tong": 3, "dang_dung": 2, "con_trong": 1}


def test_suc_chua_tu_quet_het_han():
    """Con số hiển thị cho người xem demo không được đếm cả hợp đồng đã chết."""
    pool, dh = _pool_va_dong_ho()
    pool.thue("s1")
    assert pool.suc_chua().dang_dung == 1
    dh.tien(TTL + 1)
    assert pool.suc_chua().dang_dung == 0


# -- Settings.vehicle_pool_ids() -------------------------------------------
#
# Đặt ở đây chứ không ở `tests/test_config.py`: hàm đó chỉ tồn tại để nuôi pool, và
# `test_config.py` đang có một thay đổi chưa merge (ADR-027) nên tránh đụng vào.


def test_pool_size_1_giu_nguyen_hanh_vi_cu():
    """Mặc định phải cho đúng một xe — bật nhiều xe là lựa chọn tường minh."""
    s = Settings(vehicle_pool_size=1)
    assert s.vehicle_pool_ids() == (s.vehicle_id,)


def test_xe_demo_luon_dung_dau_danh_sach():
    """Màn kỹ sư, probe_vehicle_simulator, healthcheck compose và tài liệu đều trỏ vào
    `vehicle_id`. Pool cấp theo thứ tự này, nên một người dùng duy nhất phải rơi đúng
    vào nó. Đảo thứ tự là hỏng tất cả những chỗ đó cùng lúc."""
    ids = Settings(vehicle_pool_size=3).vehicle_pool_ids()
    assert ids[0] == Settings().vehicle_id
    assert ids == ("vehicle-demo-01", "vivi-xe-02", "vivi-xe-03")


def test_id_trong_pool_khong_trung_nhau():
    """VehiclePool từ chối id trùng, nên nếu hàm này sinh trùng thì hệ không khởi động
    được — bắt ở đây rẻ hơn bắt lúc chạy."""
    for n in (1, 2, 3, 9, 12):
        ids = Settings(vehicle_pool_size=n).vehicle_pool_ids()
        assert len(ids) == n
        assert len(set(ids)) == n
        VehiclePool(ids, lease_ttl_s=1.0)  # không được ném


def test_pool_size_khong_the_nho_hon_1():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(vehicle_pool_size=0)

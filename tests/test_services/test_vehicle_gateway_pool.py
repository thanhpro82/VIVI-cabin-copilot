"""Sổ đăng ký cổng theo xe — `get_gateway_for` / `set_gateway_for`.

Bộ test còn lại chạy với `vehicle_pool_size = 1`, tức đường nhiều xe không có test nào
chạm tới. File này phủ đúng phần đó.

`conftest.py` đã gọi `reset_vehicle_gateway()` quanh mỗi test (dòng 146-155) nên các
case ở đây không rò state sang nhau — nhưng chính điều đó cũng cần một test riêng, vì
`reset` bây giờ phải dọn **cả** pool chứ không riêng ô số 0.
"""

from src.config import get_settings
from src.services.vehicle_gateway import (
    InProcessVehicleGateway,
    get_gateway_for,
    get_vehicle_gateway,
    set_gateway_for,
    set_vehicle_gateway,
)

XE_KHAC = "vivi-xe-02"


def _xe_demo() -> str:
    return get_settings().vehicle_id


# -- bất biến quan trọng nhất ----------------------------------------------


def test_o_so_khong_tra_ve_dung_object_cua_get_vehicle_gateway():
    """Nếu hai đường này trả về hai object khác nhau thì màn tài xế và màn kỹ sư sẽ nói
    hai chuyện khác nhau **về cùng một chiếc xe** — và không có gì báo động."""
    assert get_gateway_for(_xe_demo()) is get_vehicle_gateway()


def test_set_cho_o_so_khong_di_qua_set_vehicle_gateway():
    rieng = InProcessVehicleGateway.new(_xe_demo())
    set_gateway_for(_xe_demo(), rieng)
    assert get_vehicle_gateway() is rieng
    assert get_gateway_for(_xe_demo()) is rieng


# -- xe ngoài ô số 0 -------------------------------------------------------


def test_xe_chua_dang_ky_thi_dung_lazily_va_giu_nguyen():
    """`MQTT_ENABLED=false` là lựa chọn tường minh của người vận hành, và pool phải chạy
    được ở chế độ đó — giống hệt cách `get_vehicle_gateway()` tự dựng bản in-process."""
    cong = get_gateway_for(XE_KHAC)
    assert cong is get_gateway_for(XE_KHAC), "gọi lại không được dựng cổng thứ hai"


def test_hai_xe_hai_cong_khac_nhau():
    """Đây là toàn bộ lý do phương án B tồn tại: trạng thái của hai xe phải tách rời."""
    assert get_gateway_for(XE_KHAC) is not get_gateway_for(_xe_demo())
    assert get_gateway_for(XE_KHAC) is not get_gateway_for("vivi-xe-03")


def test_set_cho_xe_khac_khong_dung_toi_o_so_khong():
    truoc = get_vehicle_gateway()
    set_gateway_for(XE_KHAC, InProcessVehicleGateway.new(XE_KHAC))
    assert get_vehicle_gateway() is truoc, "đặt cổng cho xe khác không được thay xe demo"


def test_lenh_tren_xe_nay_khong_doi_trang_thai_xe_kia():
    """Kiểm ở mức hành vi chứ không chỉ mức object: đây chính là lớp lỗi mà pool sinh ra
    để xoá — `stale_state` và `approval_invalidated_state` do người khác đổi xe."""
    a = get_gateway_for(_xe_demo())
    b = get_gateway_for(XE_KHAC)
    assert a.state.state_version == b.state.state_version

    a.set_motion(45.0, "D")
    assert a.state.motion.speed_kph == 45.0
    assert b.state.motion.speed_kph == 0.0, "xe thứ hai không được nhúc nhích"


# -- dọn dẹp ---------------------------------------------------------------


def test_reset_don_ca_pool_chu_khong_rieng_o_so_khong():
    """Sót một cổng là rò state sang case sau ở test, và giữ tham chiếu tới một cache đã
    chết ở production."""
    from src.services.vehicle_gateway import reset_vehicle_gateway

    cu = get_gateway_for(XE_KHAC)
    reset_vehicle_gateway()
    assert get_gateway_for(XE_KHAC) is not cu


def test_set_vehicle_gateway_van_chay_nhu_cu():
    """Hơn hai nghìn test đi qua đường này; nó không được đổi hành vi."""
    rieng = InProcessVehicleGateway.new(_xe_demo())
    set_vehicle_gateway(rieng)
    assert get_vehicle_gateway() is rieng

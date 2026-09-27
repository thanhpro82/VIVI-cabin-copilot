"""`GET /vehicle/state` sau khi thêm auth và phạm vi theo phiên.

Đây là hợp đồng đổi, nên bốn hành vi dưới đây phải được khoá lại: chưa đăng nhập bị từ
chối, phiên của người khác bị từ chối, phiên của mình trả đúng xe của mình, và khi hệ
chạy nhiều xe thì thiếu `session_id` là **lỗi tường minh** chứ không phải một mặc định.
"""

import pytest

from src.api import session_state
from src.config import get_settings
from src.services.vehicle_pool import VehiclePool

DUONG = "/api/v1/vehicle/state"
TTL = 180.0


@pytest.fixture
def pool_hai_xe(monkeypatch):
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "2")
    get_settings.cache_clear()
    session_state.reset()
    yield
    session_state.reset()
    get_settings.cache_clear()


@pytest.fixture
def pool_hai_xe_dong_ho_gia(monkeypatch):
    """Pool có đồng hồ giả để tái hiện lease hết hạn mà không phải chờ 180 giây."""
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "2")
    get_settings.cache_clear()
    session_state.reset()
    nhip = {"t": 0.0}
    session_state._POOL = VehiclePool(
        get_settings().vehicle_pool_ids(),
        lease_ttl_s=TTL,
        dong_ho=lambda: nhip["t"],
    )
    yield nhip
    session_state.reset()
    get_settings.cache_clear()


def _phien_cua(user_id: str) -> str:
    from tests.conftest import seed_test_user

    seed_test_user(user_id)
    return session_state.create_session(user_id, get_settings().vehicle_id).session_id


# -- auth ------------------------------------------------------------------


async def test_chua_dang_nhap_thi_401(client):
    """Trước bản vá route này mở cho tất cả. Không có test này thì việc bỏ auth đi
    trong một lần refactor sau sẽ không ai biết."""
    assert (await client.get(DUONG)).status_code == 401


async def test_ky_su_van_doc_duoc(engineer_client):
    """`get_current_user` chứ không `require_driver`: màn kỹ sư sống bằng trạng thái xe,
    chặn vai engineer ở đây là hỏng đúng thứ route này phục vụ."""
    assert (await engineer_client.get(DUONG)).status_code == 200


# -- phạm vi theo phiên ----------------------------------------------------


async def test_phien_cua_nguoi_khac_thi_403(driver_client):
    la = _phien_cua("usr_nguoi_khac")
    res = await driver_client.get(DUONG, params={"session_id": la})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


async def test_session_id_khong_ton_tai_cung_403_khong_phai_404(driver_client):
    """Cùng câu trả lời với phiên của người khác — phân biệt hai ca là để lộ
    enumeration, đúng lý do `turns.py` đã ghi."""
    res = await driver_client.get(DUONG, params={"session_id": "ses_khong_co_that"})
    assert res.status_code == 403


async def test_phien_cua_minh_thi_200(driver_client):
    cua_minh = _phien_cua("usr_driver_01")
    res = await driver_client.get(DUONG, params={"session_id": cua_minh})
    assert res.status_code == 200
    assert "vehicle_state" in res.json()["data"]


# -- khi hệ chạy nhiều xe --------------------------------------------------


async def test_nhieu_xe_ma_thieu_session_id_thi_400(driver_client, pool_hai_xe):
    """Trả về xe demo lúc này là câu trả lời **sai một cách im lặng**: người đang lái
    `vivi-xe-02` sẽ điều khiển xe của mình nhưng nhìn màn hình của xe người khác."""
    res = await driver_client.get(DUONG)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


async def test_mot_xe_thi_thieu_session_id_van_duoc(driver_client):
    """`vehicle_pool_size == 1`: chỉ có một chiếc xe nên tham số không mang thông tin gì.
    Client cũ phải chạy nguyên."""
    assert (await driver_client.get(DUONG)).status_code == 200


async def test_phien_da_mat_lease_khong_duoc_doc_xe_nguoi_khac(driver_client, pool_hai_xe_dong_ho_gia):
    """Lease hết hạn phải là lỗi tường minh, không được fallback sang xe demo của người khác."""
    cua_tai_xe = _phien_cua("usr_driver_01")

    pool_hai_xe_dong_ho_gia["t"] += TTL + 1
    _phien_cua("usr_nguoi_khac")  # Nhận xe mà tài xế vừa mất lease.

    res = await driver_client.get(DUONG, params={"session_id": cua_tai_xe})

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "VEHICLE_LEASE_EXPIRED"
    assert "vehicle_state" not in res.json().get("data", {})

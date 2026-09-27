"""`POST /sessions` công bố quyền lái và sức chứa pool.

Đây là thứ client dựa vào để nói cho người dùng biết trần là bao nhiêu và mình đang ở
chế độ nào — nên hai trường này là hợp đồng, không phải thông tin trang trí.
"""

import uuid

import pytest

from src.api import session_state
from src.config import get_settings

DUONG = "/api/v1/sessions"


def _headers() -> dict[str, str]:
    return {"X-Schema-Version": "1.0", "Idempotency-Key": f"test-{uuid.uuid4()}"}


async def _tao(client) -> dict:  # noqa: ANN001
    res = await client.post(
        DUONG, json={"vehicle_id": get_settings().vehicle_id, "input_mode": "text"}, headers=_headers()
    )
    assert res.status_code == 200, res.text
    return res.json()["data"]


@pytest.fixture
def pool_hai_xe(monkeypatch):
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "2")
    get_settings.cache_clear()
    session_state.reset()
    yield
    session_state.reset()
    get_settings.cache_clear()


async def test_khong_cap_phat_thi_luon_lai_duoc_va_khong_co_tran(driver_client):
    """`vehicle_pool_size == 1`: không có trần nào để nói, nên `pool` là `null` chứ
    không phải một con số bịa ra. Client cũ đọc `can_drive` mặc định `true`."""
    data = await _tao(driver_client)
    assert data["can_drive"] is True
    assert data["pool"] is None


async def test_con_xe_thi_lai_duoc_va_bao_dung_suc_chua(driver_client, pool_hai_xe):
    dau = await _tao(driver_client)
    assert dau["can_drive"] is True
    assert dau["pool"] == {"total": 2, "in_use": 1, "free": 1}

    hai = await _tao(driver_client)
    assert hai["can_drive"] is True
    assert hai["vehicle_id"] != dau["vehicle_id"], "hai phiên phải được cấp hai xe khác nhau"
    assert hai["pool"] == {"total": 2, "in_use": 2, "free": 0}


async def test_het_xe_thi_van_tao_duoc_phien_nhung_khong_lai_duoc(driver_client, pool_hai_xe):
    """Một phiên không phải một chiếc xe: hết pool vẫn tạo phiên, chỉ là chỉ xem."""
    for _ in range(2):
        await _tao(driver_client)

    ba = await _tao(driver_client)
    assert ba["can_drive"] is False
    assert ba["pool"] == {"total": 2, "in_use": 2, "free": 0}


async def test_can_drive_khong_suy_tu_vehicle_id(driver_client, pool_hai_xe):
    """Cột `sessions.vehicle_id` là NOT NULL trong SQLite, nên một phiên chỉ-xem VẪN có
    giá trị ở đó. Client suy quyền lái từ sự có mặt của `vehicle_id` sẽ sai — test này
    khoá lại chính cái bẫy đó."""
    for _ in range(2):
        await _tao(driver_client)

    ba = await _tao(driver_client)
    assert ba["vehicle_id"], "vẫn có vehicle_id"
    assert ba["can_drive"] is False, "nhưng không được lái"

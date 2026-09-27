"""`ui.policy` phát theo xe, không phát cho cả phòng.

Đây là lớp an toàn phía giao diện: `ui.policy` khoá ô nhập text và phóng to nút mic khi
xe chạy. Phát nhầm người nghĩa là siết giao diện của một người đang đứng yên vì xe của
người khác vừa lăn bánh — hoặc tệ hơn theo chiều ngược lại, **nới** giao diện của người
đang chạy vì xe người khác vừa dừng.
"""

import pytest

from src.api import session_state
from src.config import get_settings
from src.services.ivi_events import get_event_bus
from src.services.ui_policy import get_ui_policy_emitter, reset_ui_policy_emitters
from src.services.vehicle_gateway import InProcessVehicleGateway


@pytest.fixture
def pool_hai_xe(monkeypatch):
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "2")
    get_settings.cache_clear()
    session_state.reset()
    reset_ui_policy_emitters()
    yield
    reset_ui_policy_emitters()
    session_state.reset()
    get_settings.cache_clear()


def _nghe(session_id: str) -> list[dict]:
    """Đăng ký một listener cho phiên và trả về hộp thư của nó.

    Đăng ký cũng là thứ làm phiên trở thành `active` với bus — `broadcast_to` lọc theo
    đó, nên không có bước này thì không phiên nào nhận được gì.
    """
    nhan: list[dict] = []

    async def cb(event):
        nhan.append(event)

    get_event_bus().add_listener(session_id, cb)
    return nhan


async def test_chi_phien_thue_xe_do_nhan_duoc_policy(pool_hai_xe):
    pool = session_state.get_vehicle_pool()
    xe_a = pool.thue("s1")
    xe_b = pool.thue("s2")
    assert xe_a != xe_b

    hop_a, hop_b = _nghe("s1"), _nghe("s2")

    # Cho xe A chạy, đi qua đúng đường thật: gateway -> on_state -> derive -> publish.
    gw_a = InProcessVehicleGateway.new(xe_a)
    gw_a.set_motion(45.0, "D")
    await get_ui_policy_emitter(xe_a).on_state(gw_a.state)

    assert [e["type"] for e in hop_a] == ["ui.policy"]
    assert hop_a[0]["payload"]["active"] is True
    assert hop_b == [], "xe A chạy không được siết giao diện của người đang lái xe B"


async def test_hai_xe_giu_trang_thai_last_rieng(pool_hai_xe):
    """Dùng chung một emitter cho hai xe thì xe B **không phát gì** khi nó đổi sang đúng
    policy mà xe A vừa phát — cổng kích-theo-cạnh nuốt mất lần phát của nó."""
    pool = session_state.get_vehicle_pool()
    xe_a, xe_b = pool.thue("s1"), pool.thue("s2")
    hop_a, hop_b = _nghe("s1"), _nghe("s2")

    for xe in (xe_a, xe_b):
        gw = InProcessVehicleGateway.new(xe)
        gw.set_motion(45.0, "D")
        await get_ui_policy_emitter(xe).on_state(gw.state)

    assert len(hop_a) == 1
    assert len(hop_b) == 1, "xe B phải phát policy của chính nó, không bị xe A nuốt mất"


async def test_khong_cap_phat_thi_van_phat_cho_moi_nguoi():
    """`vehicle_pool_size == 1`: một chiếc xe cho cả hệ, nên mọi phiên đều đang nhìn nó.
    Hành vi phải y hệt bản chưa có pool."""
    reset_ui_policy_emitters()
    hop_a, hop_b = _nghe("s1"), _nghe("s2")

    xe = get_settings().vehicle_id
    gw = InProcessVehicleGateway.new(xe)
    gw.set_motion(45.0, "D")
    await get_ui_policy_emitter(xe).on_state(gw.state)

    assert len(hop_a) == 1
    assert len(hop_b) == 1
    reset_ui_policy_emitters()

"""`session_state` khi pool có nhiều hơn một xe.

Bộ test còn lại chạy với `vehicle_pool_size = 1` — tức **không cấp phát**, y như trước
khi có pool. File này là chỗ duy nhất chạy đường cấp phát thật.

Mẫu `monkeypatch.setenv` + `get_settings.cache_clear()` lấy từ
`tests/test_agents/test_chon_cau_thac.py`.
"""

import pytest

from src.api import session_state
from src.config import get_settings
from src.services.vehicle_gateway import POOL_CAN_KIET, ChiXemVehicleGateway

USER = "usr_driver_01"


@pytest.fixture
def pool_hai_xe(monkeypatch):
    """Bật cấp phát với đúng 2 xe. Dọn cache cấu hình ở cả hai đầu, nếu không thì
    `Settings` đã cache rò sang case sau và làm chúng hỏng theo thứ tự chạy."""
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "2")
    get_settings.cache_clear()
    session_state.reset()
    yield
    session_state.reset()
    get_settings.cache_clear()


def _tao(session_id_nguon: str) -> str:
    """Tạo phiên, trả về `vehicle_id` được ghi vào bản ghi."""
    from tests.conftest import seed_test_user  # noqa: PLC0415 - chỉ dùng trong test

    seed_test_user(session_id_nguon)
    return session_state.create_session(session_id_nguon, "xe-client-goi-y").vehicle_id


# -- không cấp phát (mặc định repo) ----------------------------------------


def test_mac_dinh_khong_cap_phat():
    """`vehicle_pool_size = 1` phải cho hành vi Y HỆT bản chưa có pool: mọi phiên đều
    lái được, không ai bị đẩy sang chế độ chỉ xem."""
    assert session_state.get_vehicle_pool() is None
    assert session_state.xe_cua_phien("phien-la-hoac-khong-ton-tai") == get_settings().vehicle_id
    assert session_state.suc_chua_xe() is None, "không cấp phát thì không có trần nào để nói"


# -- có cấp phát -----------------------------------------------------------


def test_hai_phien_hai_xe_khac_nhau(pool_hai_xe):
    pool = session_state.get_vehicle_pool()
    assert pool is not None
    assert pool.thue("s1") == get_settings().vehicle_id, "phiên đầu phải nhận xe demo"
    assert pool.thue("s2") == "vivi-xe-02"
    assert session_state.xe_cua_phien("s1") != session_state.xe_cua_phien("s2")


def test_het_xe_thi_chi_xem_chu_khong_no(pool_hai_xe):
    pool = session_state.get_vehicle_pool()
    pool.thue("s1")
    pool.thue("s2")
    assert session_state.xe_cua_phien("s3") is None, "hết pool = chỉ xem, không phải lỗi"
    assert session_state.suc_chua_xe().as_dict() == {"tong": 2, "dang_dung": 2, "con_trong": 0}


def test_touch_gia_han_chu_khong_cap_moi(pool_hai_xe):
    """`_touch()` chạy ở mọi đường vào. Nếu nó cấp mới thì một phiên chỉ-xem sẽ chiếm
    xe ngay khi có người khác rời đi, giữa chừng một lượt."""
    pool = session_state.get_vehicle_pool()
    pool.thue("s1")
    pool.thue("s2")

    # `_touch` giả định phiên đã có graph (nó gọi `_GRAPHS.move_to_end`), nên đặt sẵn
    # chỗ giữ. Dựng graph thật ở đây là kéo cả LangGraph vào một test về cấp phát xe.
    for sid in ("s1", "s3"):
        session_state._GRAPHS[sid] = object()

    session_state._touch("s3")
    assert session_state.xe_cua_phien("s3") is None, "chỉ-xem vẫn phải là chỉ-xem"

    session_state._touch("s1")
    assert session_state.xe_cua_phien("s1") == get_settings().vehicle_id


def test_get_vehicle_tra_dung_cong_cua_xe_da_thue(pool_hai_xe):
    """Đây là điều toàn bộ phương án B tồn tại để đạt: hai phiên, hai chiếc xe, trạng
    thái tách rời."""
    pool = session_state.get_vehicle_pool()
    pool.thue("s1")
    pool.thue("s2")

    a = session_state.get_vehicle("s1")
    b = session_state.get_vehicle("s2")
    assert a is not b

    a.set_motion(45.0, "D")
    assert a.state.motion.speed_kph == 45.0
    assert b.state.motion.speed_kph == 0.0


async def test_phien_chi_xem_doc_duoc_nhung_khong_ra_lenh_duoc(pool_hai_xe):
    """Khác biệt giữa "hết chỗ" và "hỏng": vẫn thấy màn hình sống, chỉ không lái được.

    `.state` cố ý KHÔNG dùng ở đây — nó là thuộc tính riêng của bản in-process, không
    nằm trong `VehicleGateway` Protocol. Test đi qua đúng bề mặt mà mọi cổng đều có.
    """
    pool = session_state.get_vehicle_pool()
    pool.thue("s1")
    pool.thue("s2")

    cong = session_state.get_vehicle("s3")
    assert isinstance(cong, ChiXemVehicleGateway)
    assert cong.readiness() is not None
    assert await cong.last_known() is not None, "vẫn phải đọc được trạng thái"

    ket_qua = await cong.execute(
        plan_id="plan-1",
        step_id="step-1",
        tool="set_hvac_power",
        args={"power": "on"},
        expected_state_version=0,
    )
    assert ket_qua.status == "rejected"
    assert ket_qua.error_code == POOL_CAN_KIET
    assert ket_qua.observed_state_version == 0, "không có gì đổi thì version không được nhích"


async def test_chi_xem_chan_ca_duong_dat_toc_do(pool_hai_xe):
    """Kênh harness `POST /sim/motion` đi qua `get_vehicle(session_id, speed_kph=...)`.
    Cổng chỉ-xem không phải `MotionInjectable` nên đường đó cũng đóng."""
    pool = session_state.get_vehicle_pool()
    pool.thue("s1")
    pool.thue("s2")

    with pytest.raises(RuntimeError):
        session_state.get_vehicle("s3", speed_kph=45.0)


def test_graph_cua_phien_chi_xem_duoc_dung_bang_cong_chi_xem(pool_hai_xe, monkeypatch):
    """Đường lệnh chính đi qua `get_graph()`, KHÔNG gọi `get_vehicle()` trực tiếp.

    Nếu graph được dựng bằng cổng toàn cục thì `ChiXemVehicleGateway` vô dụng: phiên
    chỉ-xem vẫn lái được xe demo qua `POST /turns/*`. Test bắt cổng ngay lúc dựng thay
    vì chạy cả một lượt — LangGraph và RAG không liên quan gì tới câu hỏi ở đây.
    """
    bat = {}

    def build_graph_gia(gateway, **_kwargs):
        bat["gateway"] = gateway
        return object()

    monkeypatch.setattr(session_state, "build_graph", build_graph_gia)

    pool = session_state.get_vehicle_pool()
    pool.thue("s1")
    pool.thue("s2")

    session_state.get_graph("s3")
    assert isinstance(bat["gateway"], ChiXemVehicleGateway)

    bat.clear()
    session_state.get_graph("s1")
    assert not isinstance(bat["gateway"], ChiXemVehicleGateway), "phiên có xe phải lái được"

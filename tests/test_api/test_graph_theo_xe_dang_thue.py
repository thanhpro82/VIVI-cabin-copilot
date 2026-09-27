"""Graph phải theo chiếc xe phiên **đang** thuê, không phải chiếc nó thuê lúc dựng.

Cổng xe được chốt vào graph ở lần dựng đầu, còn graph sống theo phiên. Chú thích cũ
trong `get_graph` lập luận rằng chốt cổng là chấp nhận được vì *"quyền lái không đổi
giữa chừng một cuộc hội thoại"* — đúng cho chiều phiên-bắt-đầu-chỉ-xem (bất tiện, vô
hại), nhưng bỏ sót chiều ngược lại: phiên bắt đầu **có** xe vẫn giữ cổng lái sau khi
mất xe.

`_touch()` chỉ `gia_han()`, cố ý không cấp mới. Nên lease hết hạn (180 s mặc định) là
xe quay về pool và được cấp cho người khác, trong khi graph cũ vẫn cầm đúng cổng của
chiếc xe đó — phiên cũ lái xe của người mới, không bên nào có dấu hiệu gì.

Đo được qua đường HTTP thật trước khi vá:

    A được cấp xe-01, "bật điều hòa"  -> 27,0 °C
    [lease của A hết hạn]
    B được cấp xe-01
    A "đặt điều hòa 30 độ"            -> completed   <-- A đã mất xe mà vẫn lái
    xe-01 (xe của B)                  -> 30,0 °C

Chỉ nổ khi `vehicle_pool_size >= 2`; mặc định repo là 1 nên `test_pool_tat_*` bên dưới
là vế "không đổi hành vi của ai" và phải luôn xanh.

Mẫu `monkeypatch.setenv` + `get_settings.cache_clear()` lấy từ
`tests/test_api/test_session_state_pool.py`.
"""

import asyncio

import pytest

from src.api import session_state
from src.config import get_settings
from src.services.ivi_events import MAT_XE_CODE, IviEventBus, emit_turn_lifecycle
from src.services.vehicle_gateway import ChiXemVehicleGateway
from src.services.vehicle_pool import VehiclePool

TTL = 180.0


@pytest.fixture
def pool_dong_ho_gia(monkeypatch):
    """Pool 2 xe với đồng hồ giả, để cho lease hết hạn mà không phải chờ thật.

    Gắn thẳng `_POOL` thay vì để `get_vehicle_pool()` tự dựng: đó là chỗ duy nhất tiêm
    được đồng hồ, và không có nó thì test này phải `sleep(180)`.
    """
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "2")
    get_settings.cache_clear()
    session_state.reset()
    nhip = {"t": 0.0}
    session_state._POOL = VehiclePool(
        get_settings().vehicle_pool_ids(),
        lease_ttl_s=TTL,
        dong_ho=lambda: nhip["t"],
    )
    yield session_state._POOL, nhip
    session_state.reset()
    get_settings.cache_clear()


def test_lease_het_han_thi_graph_bi_dung_lai(pool_dong_ho_gia):
    """Vế chính: mất xe thì mất luôn graph đang cầm cổng của chiếc xe ấy."""
    pool, nhip = pool_dong_ho_gia
    assert pool.thue("s1") == get_settings().vehicle_id

    graph_cu = session_state.get_graph("s1")

    nhip["t"] += TTL + 1
    assert session_state.xe_cua_phien("s1") is None, "tiền đề của test: lease phải hết hạn"

    graph_moi = session_state.get_graph("s1")
    assert graph_moi is not graph_cu, "graph cũ vẫn cầm cổng của chiếc xe không còn thuộc phiên này"


def test_sau_khi_dung_lai_cong_moi_phai_la_chi_xem(pool_dong_ho_gia, monkeypatch):
    """Dựng lại chưa đủ — cổng **được chốt vào graph mới** phải là cổng chỉ-xem.

    Bắt cổng ngay lúc dựng thay vì chạy cả một lượt, cùng mẫu với
    `test_graph_cua_phien_chi_xem_duoc_dung_bang_cong_chi_xem`: LangGraph và RAG không
    liên quan gì tới câu hỏi ở đây.

    Đừng thay bằng `isinstance(session_state.get_vehicle("s1"), ChiXemVehicleGateway)`:
    `get_vehicle` tính lại cổng ở **mỗi** lần gọi nên nó chỉ-xem kể cả khi chưa vá, và
    test sẽ xanh vô nghĩa. Thứ cần bắt là cổng nằm **trong graph**.
    """
    bat = {}

    def build_graph_gia(gateway, **_kwargs):
        bat["gateway"] = gateway
        return object()

    monkeypatch.setattr(session_state, "build_graph", build_graph_gia)

    pool, nhip = pool_dong_ho_gia
    pool.thue("s1")
    session_state.get_graph("s1")
    assert not isinstance(bat["gateway"], ChiXemVehicleGateway), "tiền đề: lúc còn xe thì lái được"

    bat.clear()
    nhip["t"] += TTL + 1
    session_state.get_graph("s1")

    assert bat, "mất xe rồi mà graph không được dựng lại — cổng cũ vẫn lái được xe của người khác"
    assert isinstance(bat["gateway"], ChiXemVehicleGateway)


def test_xe_khong_doi_thi_giu_nguyen_graph(pool_dong_ho_gia):
    """Vế đối trọng, và nó quan trọng ngang vế chính.

    Dựng lại graph là mất `InMemorySaver`, tức mất checkpoint giữ `interrupt()` của một
    lượt S2 đang chờ duyệt. Dựng lại quá tay thì mọi lượt chờ duyệt chết oan, và bộ test
    an toàn vẫn xanh vì chúng không đi qua đường pool.
    """
    pool, nhip = pool_dong_ho_gia
    pool.thue("s1")
    graph_dau = session_state.get_graph("s1")

    nhip["t"] += TTL / 2  # chưa hết hạn, và `_touch` trong `get_graph` vừa gia hạn
    assert session_state.get_graph("s1") is graph_dau


def test_phien_moi_nhan_xe_cu_khong_bi_anh_huong(pool_dong_ho_gia):
    """Người mới nhận đúng chiếc xe người cũ vừa mất — phải có graph riêng, cổng riêng."""
    pool, nhip = pool_dong_ho_gia
    pool.thue("s1")
    graph_a = session_state.get_graph("s1")

    nhip["t"] += TTL + 1
    assert pool.thue("s2") == get_settings().vehicle_id, "xe của s1 phải quay về pool cho s2"

    graph_b = session_state.get_graph("s2")
    assert graph_b is not graph_a
    assert session_state.get_graph("s1") is not graph_a, "s1 đã mất xe, graph cũ của nó phải bị bỏ"


def test_pool_tat_thi_khong_bao_gio_dung_lai():
    """Mặc định repo (`vehicle_pool_size = 1`): `xe_cua_phien` trả hằng số ở mọi lượt,
    nên hai vế luôn bằng nhau và nhánh dựng lại không bao giờ chạy.

    Đây là vế "bản vá này không đổi hành vi của ai". Nếu nó đỏ thì mọi checkout mặc định
    vừa mất khả năng resume interrupt S2.
    """
    session_state.reset()
    assert session_state.get_vehicle_pool() is None, "tiền đề: mặc định là không cấp phát"

    graph_dau = session_state.get_graph("s-mac-dinh")
    assert session_state.get_graph("s-mac-dinh") is graph_dau
    assert session_state.get_graph("s-mac-dinh") is graph_dau


def test_don_bang_phu_khi_phien_bi_duoi():
    """`_GRAPH_XE` phải dọn cùng nhịp với `_GRAPHS`, nếu không nó rò theo số phiên bị đuổi."""
    session_state.reset()
    for i in range(session_state.MAX_SESSIONS + 3):
        session_state.get_graph(f"s-{i}")

    assert len(session_state._GRAPHS) <= session_state.MAX_SESSIONS
    assert set(session_state._GRAPH_XE) == set(session_state._GRAPHS)


def test_doc_xe_mot_lan_du_lease_het_han_giua_luc_dung_graph(pool_dong_ho_gia, monkeypatch):
    """Lease hết hạn **giữa** lúc dựng graph không được để lại một cặp lệch vĩnh viễn.

    `xe_cua_phien()` phát hiện hết hạn *lúc đọc* (`_quet_het_han`), nên hai lần đọc cách
    nhau một `build_graph(...)` trả hai câu trả lời khác nhau được. Bản trước đọc đúng
    hai lần: một lần cho `get_vehicle(...)` (quyết định **cổng**) và một lần cho
    `_GRAPH_XE[...]` (quyết định **guard**).

    Hậu quả không thoáng qua, và đó là lý do test này tồn tại: cổng ghi `xe-01` thật còn
    guard ghi `None` thì từ lượt sau `xe_cua_phien()` cũng là `None`, hai vế **bằng
    nhau**, nhánh dựng lại không bao giờ chạy — phiên lái `xe-01` vĩnh viễn, đúng cái bug
    cả file này sinh ra để diệt, lần này vô hình với chính guard của nó.

    Không mô phỏng bằng `sleep`: đẩy đồng hồ giả **một lần, ngay trong `build_graph`**,
    tức đúng khe giữa hai lần đọc. Bản chưa sửa đỏ ở assert cuối.
    """
    pool, nhip = pool_dong_ho_gia
    xe = pool.thue("s1")
    assert xe is not None

    goc = session_state.build_graph

    def dung_graph_lau(*args, **kwargs):
        # Đúng một lần, và đúng trong khe: sau khi cổng đã được chọn, trước khi bảng phụ
        # được ghi. Đây là điều kiện đua thật, chỉ bị nén lại cho tất định.
        nhip["t"] += TTL + 1
        return goc(*args, **kwargs)

    monkeypatch.setattr(session_state, "build_graph", dung_graph_lau)
    session_state.get_graph("s1")
    monkeypatch.setattr(session_state, "build_graph", goc)

    assert session_state.xe_cua_phien("s1") is None, "tiền đề: lease phải hết hạn trong khe"
    assert session_state._GRAPH_XE["s1"] == xe, (
        "bảng phụ phải ghi đúng chiếc xe đã nướng vào cổng của graph, không phải giá trị "
        "đọc lại sau khi lease đã hết — nếu không guard sẽ so None với None và im lặng"
    )

    graph_moi = session_state.get_graph("s1")
    assert isinstance(session_state.get_vehicle("s1"), ChiXemVehicleGateway)
    assert session_state._GRAPH_XE["s1"] is None
    assert graph_moi is not None


# --- Báo cho tài xế biết họ vừa mất quyền lái ------------------------------------
#
# Review PM/PO trên #344: *"khi quyền thuê xe hết hạn, người dùng phải nhận được thông
# báo dễ hiểu rằng họ không còn quyền điều khiển xe, thay vì chỉ gặp approval không tồn
# tại hoặc hành vi điều khiển thất bại khó hiểu"*. Vá an toàn ở trên là điều kiện cần;
# bốn test dưới đây là điều kiện đủ về phía backend.


def test_mat_xe_thi_phat_error_vao_stream_tai_xe(pool_dong_ho_gia):
    """Mất xe → một `error` với mã riêng, phát trước mọi event khác của lượt.

    Mã **không** dùng chung với `vehicle_pool_exhausted`: *"hết xe mô phỏng khả dụng"*
    đúng cho người chưa bao giờ được cấp xe và nói sai hẳn với người vừa mất chiếc xe
    mình đang lái. Đó là đúng thứ review gọi là "thất bại khó hiểu".

    `terminal=False` vì lượt vẫn chạy tiếp — chế độ chỉ xem vẫn tra sổ tay và đọc trạng
    thái xe được; chỉ lệnh điều khiển bị từ chối, và `tool.result` đã nói riêng chuyện đó.
    """
    pool, nhip = pool_dong_ho_gia
    assert pool.thue("s1") is not None
    session_state.get_graph("s1")
    nhip["t"] += TTL + 1
    session_state.get_graph("s1")

    bus = IviEventBus()
    nhan: list[dict] = []
    bus.add_listener("s1", lambda e: nhan.append(e) or _khong_lam_gi())

    asyncio.run(emit_turn_lifecycle(bus, "s1", "turn-1", "tr-1", {}))

    loi = [e for e in nhan if e["type"] == "error"]
    assert len(loi) == 1, f"phải có đúng một error báo mất xe, nhận {[e['type'] for e in nhan]}"
    payload = loi[0]["payload"]
    assert payload["code"] == MAT_XE_CODE
    assert payload["terminal"] is False
    assert payload["retryable"] is True
    assert payload["details"] == {"can_drive": False}
    assert nhan[0]["type"] == "error", "phải đứng trước mọi event khác của lượt"


def test_canh_bao_mat_xe_chi_bao_dung_mot_lan(pool_dong_ho_gia):
    """Cảnh báo là một **sự kiện**, không phải một trạng thái — đọc là xoá.

    Trạng thái "đang chỉ xem" đã có `xe_cua_phien(...) is None` trả lời và nó đúng ở mọi
    lượt sau đó. Nếu cờ này cũng trả `True` mãi thì tài xế nhận cùng một câu báo mất xe ở
    **mọi** lượt cho tới hết phiên, và đúng khoảnh khắc cần nhìn thấy bị làm mờ đi.
    """
    pool, nhip = pool_dong_ho_gia
    assert pool.thue("s1") is not None
    session_state.get_graph("s1")
    nhip["t"] += TTL + 1
    session_state.get_graph("s1")

    assert session_state.lay_canh_bao_mat_xe("s1") is True
    assert session_state.lay_canh_bao_mat_xe("s1") is False


def test_duoc_cap_xe_khong_bi_bao_la_mat_xe(pool_dong_ho_gia):
    """Chiều ngược lại — vừa **có** quyền lái thì không được báo là vừa **mất**.

    Phiên chỉ-xem được cấp xe cũng làm hai vế lệch nhau và cũng dựng lại graph, nên nhánh
    báo phải lọc theo *hướng* của thay đổi chứ không phải theo việc có lệch hay không.
    Thiếu bộ lọc ấy thì câu "bạn mất quyền lái" hiện ra đúng lúc người ta vừa có quyền.
    """
    pool, _ = pool_dong_ho_gia
    ids = get_settings().vehicle_pool_ids()
    for i, _xe in enumerate(ids):
        assert pool.thue(f"chiem-{i}") is not None
    assert pool.thue("s1") is None, "tiền đề: s1 phải bắt đầu ở chế độ chỉ xem"

    session_state.get_graph("s1")
    assert session_state.lay_canh_bao_mat_xe("s1") is False

    pool.tra("chiem-0")
    assert pool.thue("s1") is not None
    session_state.get_graph("s1")
    assert session_state.lay_canh_bao_mat_xe("s1") is False, "vừa được cấp xe, không phải vừa mất"


def test_pool_tat_thi_khong_bao_gio_bao_mat_xe(monkeypatch):
    """Mặc định repo (`vehicle_pool_size = 1`) không phát thêm event nào.

    Cùng vai với `test_pool_tat_thi_khong_bao_gio_dung_lai`: nếu test này đỏ thì mọi
    checkout mặc định vừa mọc thêm một `error` mà không ai yêu cầu.
    """
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "1")
    get_settings.cache_clear()
    session_state.reset()
    try:
        for _ in range(3):
            session_state.get_graph("s1")
        assert session_state.lay_canh_bao_mat_xe("s1") is False
    finally:
        session_state.reset()
        get_settings.cache_clear()


def _khong_lam_gi():
    """Listener của bus là async; lambda ở trên cần một awaitable để trả về."""

    async def _rong() -> None:
        return None

    return _rong()

"""Hủy Routine tại điểm dừng an toàn (issue #297).

Sáu mệnh đề của `#297` Done when:

1. hủy hợp lệ chặn **mọi bước mới** sau điểm dừng an toàn;
2. lệnh đang bay không bị báo là đã rollback — MVP không rollback;
3. hủy lặp lại / hủy đua nhau cho **đúng một** terminal `user_canceled`;
4. bước chưa chạy nhận trạng thái hủy/bỏ qua rõ ràng;
5. run mới sau khi hủy có identity mới;
6. Routine đang chạy thì không xoá được (acceptance criteria #272).
"""

import pytest

from src.db import connect, ensure_schema
from src.models.vehicle import ToolResult as GatewayToolResult
from src.services import routine_execution as engine
from src.services.routines_store import RoutineKhongTonTaiError, create_routine, delete_routine, get_routine


def _state():
    from src.vehicle_sim.state import initial_state

    return initial_state("veh-01")


class GatewayGia:
    """Cổng xe giả, có móc để **hủy giữa chừng** ngay trong lúc một bước đang chạy.

    Đó là ca thật sự khó: yêu cầu hủy tới từ một request khác trong lúc vòng lặp đang ở
    giữa hai bước. `khi_chay` mô phỏng đúng khoảnh khắc ấy mà không cần thread.
    """

    def __init__(self, khi_chay=None) -> None:
        self.da_chay: list[str] = []
        self._khi_chay = khi_chay

    async def snapshot(self):
        return _state()

    async def execute(self, *, plan_id, step_id, tool, args, expected_state_version, approval_id=None):
        self.da_chay.append(tool)
        if self._khi_chay is not None:
            await self._khi_chay(len(self.da_chay))
        return GatewayToolResult(
            command_id=f"cmd-{len(self.da_chay)}",
            plan_id=plan_id,
            step_id=step_id,
            status="completed",
            before={},
            after={},
            expected_state_version=expected_state_version,
            observed_state_version=expected_state_version + 1,
            attempt_count=1,
            error_code=None,
            latency_ms=1,
        )


@pytest.fixture
def conn(tmp_path, monkeypatch):
    connection = connect(tmp_path / "cancel.db")
    ensure_schema(connection)
    connection.execute("INSERT INTO users (id, email, password_hash, role) VALUES ('usr_a', 'a@x.vn', 'x', 'driver')")
    connection.execute("INSERT INTO users (id, email, password_hash, role) VALUES ('usr_b', 'b@x.vn', 'x', 'driver')")
    connection.commit()
    for module in ("src.db", "src.services.routines_store", "src.services.user_places", "src.services.routine_execution"):
        monkeypatch.setattr(f"{module}.get_connection", lambda: connection)
    yield connection
    connection.close()


@pytest.fixture
def store_sach(monkeypatch, conn):
    from src.agents.approval import ApprovalStore

    store = ApprovalStore(connection=conn)
    monkeypatch.setattr("src.api.session_state.get_store", lambda: store)
    return store


@pytest.fixture(autouse=True)
def bus_im(monkeypatch):
    class BusIm:
        async def publish(self, *args, **kwargs):
            return None

    monkeypatch.setattr("src.services.ivi_events.get_event_bus", lambda: BusIm())


async def _chay(conn, steps, *, gateway, monkeypatch, ten="Test"):
    routine = create_routine("usr_a", name=ten, icon="car", steps=steps, connection=conn)
    monkeypatch.setattr("src.services.vehicle_gateway.get_vehicle_gateway", lambda: gateway)
    return routine, await engine.bat_dau(
        user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
    )


# --- 1 & 2 & 4: điểm dừng an toàn -------------------------------------------


@pytest.mark.asyncio
async def test_huy_giua_chung_chan_buoc_moi_nhung_khong_rut_lai_buoc_da_chay(conn, monkeypatch, store_sach):
    """Hủy trong lúc bước 1 đang bay: bước ấy **chạy nốt** và được báo `completed`.

    Lệnh đã publish lên MQTT thì không rút lại được, và một hệ báo "đã hủy" trong khi xe
    vừa mở kính là một hệ nói dối (§Hủy). MVP không rollback.
    """

    async def huy_ngay_khi_buoc_dau_chay(so_lenh: int):
        if so_lenh == 1:
            conn.execute("UPDATE routine_executions SET cancel_requested = 1")
            conn.commit()

    gateway = GatewayGia(khi_chay=huy_ngay_khi_buoc_dau_chay)
    _, execution = await _chay(
        conn,
        [
            {"action": "hvac_power", "enabled": True},
            {"action": "interior_light", "enabled": True},
            {"action": "hvac_fan_level", "level": 2},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "user_canceled"
    assert gateway.da_chay == ["set_hvac_power"]
    assert [r.status for r in execution.results] == ["completed", "canceled", "skipped"]
    assert execution.results[1].error_code == "canceled_before_run"


# --- 3: idempotent -----------------------------------------------------------


@pytest.mark.asyncio
async def test_huy_hai_lan_chi_co_mot_terminal(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    _, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    assert execution.status == "waiting_approval"

    lan_1 = await engine.huy("usr_a", execution.id, connection=conn)
    lan_2 = await engine.huy("usr_a", execution.id, connection=conn)

    assert lan_1.status == lan_2.status == "user_canceled"
    assert lan_1.terminal_reason == lan_2.terminal_reason == "user_canceled"
    assert lan_1.updated_at == lan_2.updated_at


@pytest.mark.asyncio
async def test_huy_mot_lan_chay_da_xong_khong_doi_gi(conn, monkeypatch, store_sach):
    """Tài xế bấm Dừng đúng lúc bước cuối vừa hoàn tất — chuyện thường, không phải lỗi."""
    gateway = GatewayGia()
    _, execution = await _chay(conn, [{"action": "hvac_power", "enabled": True}], gateway=gateway, monkeypatch=monkeypatch)
    assert execution.status == "completed"

    sau = await engine.huy("usr_a", execution.id, connection=conn)

    assert sau.status == "completed"
    assert sau.terminal_reason == "completed"


@pytest.mark.asyncio
async def test_huy_khi_dang_cho_duyet_thi_tu_choi_luon_the(conn, monkeypatch, store_sach):
    """Bỏ rơi thẻ mà không chốt sẽ để nó `pending` tới lúc hết hạn và chặn mọi thẻ sau
    trong cùng phiên."""
    gateway = GatewayGia()
    _, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    await engine.huy("usr_a", execution.id, connection=conn)

    assert store_sach.get(execution.approval_id).status == "rejected"
    assert store_sach.pending_for_session("ses-01") is None
    assert gateway.da_chay == []


# --- 5: run mới có identity mới ---------------------------------------------


@pytest.mark.asyncio
async def test_chay_lai_sau_khi_huy_la_mot_execution_moi(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    routine, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    await engine.huy("usr_a", execution.id, connection=conn)

    lan_moi = await engine.bat_dau(
        user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
    )

    assert lan_moi.id != execution.id
    assert lan_moi.cancel_requested is False
    assert lan_moi.status == "waiting_approval"


# --- cô lập ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_khong_huy_duoc_lan_chay_cua_nguoi_khac(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    _, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    with pytest.raises(LookupError):
        await engine.huy("usr_b", execution.id, connection=conn)

    assert engine.doc("usr_a", execution.id, connection=conn).status == "waiting_approval"


# --- 6: xoá Routine đang chạy ------------------------------------------------


@pytest.mark.asyncio
async def test_khong_xoa_duoc_routine_dang_chay(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    routine, _ = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    with pytest.raises(engine.RoutineDangChayError):
        delete_routine("usr_a", routine.id, connection=conn)

    assert get_routine("usr_a", routine.id, connection=conn).id == routine.id


@pytest.mark.asyncio
async def test_huy_xong_thi_xoa_duoc(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    routine, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    await engine.huy("usr_a", execution.id, connection=conn)

    delete_routine("usr_a", routine.id, connection=conn)

    with pytest.raises(RoutineKhongTonTaiError):
        get_routine("usr_a", routine.id, connection=conn)


# --- khởi động lại -----------------------------------------------------------


@pytest.mark.asyncio
async def test_khoi_dong_lai_dong_moi_lan_chay_con_do(conn, monkeypatch, store_sach):
    """Không vòng lặp nào còn chạy để tiếp tục chúng, và spec chốt không Routine nào tự
    chạy tiếp sau restart. Để nguyên `running` thì phiên ấy bị khoá vĩnh viễn."""
    gateway = GatewayGia()
    _, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    so_dong = engine.don_execution_mo_coi(conn)

    assert so_dong == 1
    sau = engine.doc("usr_a", execution.id, connection=conn)
    assert sau.status == "failed"
    assert sau.terminal_reason == "interrupted_by_restart"


# --- race giữa Dừng và thẻ phê duyệt (review PR #369) ------------------------


@pytest.mark.asyncio
async def test_huy_van_dong_khi_approval_vua_duoc_tao_ngay_truoc_do(conn, monkeypatch, store_sach):
    """Interleaving mà review #369 chỉ ra, dựng lại nguyên văn:

    1. `huy()` đọc execution khi nó còn `running`;
    2. vòng lặp tạo thẻ phê duyệt và ghi `waiting_approval`;
    3. `huy()` bật cờ rồi rẽ nhánh — **nếu** rẽ theo bản đọc ở bước 1 thì không ai từ
       chối thẻ và không ai đóng execution.

    Hậu quả nếu không vá: tài xế bấm Dừng, thẻ vẫn treo, lần chạy kẹt `waiting_approval`
    tới lúc hết hạn. Ở đây bản đọc cũ được nhại bằng cách patch `doc` — DB thì đã ở
    `waiting_approval` thật.
    """
    gateway = GatewayGia()
    _, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    assert execution.status == "waiting_approval"

    ban_doc_cu = engine.RoutineExecution(
        id=execution.id,
        routine_id=execution.routine_id,
        user_id=execution.user_id,
        session_id=execution.session_id,
        vehicle_id=execution.vehicle_id,
        routine_version=execution.routine_version,
        status="running",
        current_index=0,
        approval_id=None,
        steps=execution.steps,
        results=(),
        terminal_reason=None,
        cancel_requested=False,
        created_at=execution.created_at,
        updated_at=execution.updated_at,
    )
    monkeypatch.setattr(engine, "doc", lambda *args, **kwargs: ban_doc_cu)

    sau = await engine.huy("usr_a", execution.id, connection=conn)

    assert sau.status == "user_canceled"
    assert store_sach.get(execution.approval_id).status == "rejected"
    assert store_sach.pending_for_session("ses-01") is None
    assert gateway.da_chay == []


@pytest.mark.asyncio
async def test_co_huy_bat_trong_luc_tao_the_thi_the_bi_tu_choi_ngay(conn, monkeypatch, store_sach):
    """Chiều ngược lại của cùng cửa sổ: cờ bật **sau** lần kiểm ở đầu vòng lặp, trong lúc
    `_tao_approval` đang chạy. Vòng lặp phải tự phát hiện và từ chối thẻ nó vừa tạo,
    thay vì để lại một thẻ treo không ai chốt."""
    that = engine._tao_approval

    def tao_roi_bat_co(conn_, execution, plan, snapshot, index):
        approval_id = that(conn_, execution, plan, snapshot, index)
        conn_.execute("UPDATE routine_executions SET cancel_requested = 1 WHERE id = ?", (execution.id,))
        conn_.commit()
        return approval_id

    monkeypatch.setattr(engine, "_tao_approval", tao_roi_bat_co)
    gateway = GatewayGia()

    _, execution = await _chay(
        conn,
        [
            {"action": "window_position", "window": "frontLeft", "percent": 50},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "user_canceled"
    assert [r.status for r in execution.results] == ["canceled", "skipped"]
    assert gateway.da_chay == []
    the = store_sach.get(execution.approval_id) if execution.approval_id else None
    assert the is None or the.status == "rejected"
    assert store_sach.pending_for_session("ses-01") is None


@pytest.mark.asyncio
async def test_hai_duong_cung_dong_chi_phat_mot_terminal(conn, monkeypatch, store_sach):
    """CAS ở `_ket_thuc_sau_khi_da_ghi`: bên thua đọc `rowcount == 0` và im lặng.

    Không có nó thì một lần chạy phát **hai** `routine.finished` — vi phạm bất biến của
    #290, và trên màn hình tài xế là hai thông báo kết thúc cho một việc.
    """
    phat: list[str] = []

    class BusDem:
        async def publish(self, session_id, event_type, turn_id, trace_id, payload):
            phat.append(event_type)

    monkeypatch.setattr("src.services.ivi_events.get_event_bus", lambda: BusDem())
    gateway = GatewayGia()
    _, execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    await engine.huy("usr_a", execution.id, connection=conn)
    await engine.huy("usr_a", execution.id, connection=conn)
    await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=False, connection=conn)

    assert phat.count("routine.finished") == 1

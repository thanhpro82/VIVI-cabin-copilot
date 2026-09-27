"""Thực thi Routine (issue #286).

Bộ test nhắm đúng những chỗ một đường tắt sẽ xuất hiện:

- Routine **không** bỏ qua policy: S3 chặn trước HITL, S2 dừng chờ phê duyệt;
- fail-fast tuần tự, và bước chưa chạy phải **có mặt** trong sổ sách;
- fail-closed khi không đọc được trạng thái xe;
- không replay: một quyết định tới sau khi execution đã kết thúc không chạy gì thêm.
"""

import base64

import pytest

from src.agents.approval import ApprovalRecord
from src.db import connect, ensure_schema
from src.models.vehicle import ToolResult as GatewayToolResult
from src.services import routine_execution as engine
from src.services import voice
from src.services.routines_store import create_routine
from src.services.user_places import set_place


@pytest.fixture(autouse=True)
def _stub_tts_unavailable(monkeypatch):
    """TTS luôn thất bại mặc định trong file này — không phụ thuộc việc máy chạy
    test có sẵn model Piper thật hay không. Cùng khuôn `test_ivi_events.py`. Test
    nào cần audio thành công tự override `voice.synthesize_wav` riêng trong thân.
    """

    def _raise(text):
        raise FileNotFoundError("no TTS model in test environment")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)


class _RecordingBus:
    """Bắt sự kiện `_phat()` publish, cùng khuôn `_RecordingBus` của
    `test_ivi_events.py` — `routine_execution.py` không nhận bus qua tham số như
    `emit_turn_lifecycle`, phải monkeypatch `get_event_bus()`.
    """

    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, session_id, event_type, turn_id, trace_id, payload):
        self.events.append({"type": event_type, "payload": payload})


@pytest.fixture
def bus_ghi(monkeypatch):
    bus = _RecordingBus()
    monkeypatch.setattr("src.services.ivi_events.get_event_bus", lambda: bus)
    return bus


def _state(*, speed: float = 0.0, gear: str = "P"):
    """Trạng thái xe thật, lấy từ chính bộ dựng của simulator rồi chỉnh phần cần.

    Không viết tay một dict: `VehicleState` là `_Strict`, và một dict viết tay sẽ hợp lệ
    hôm nay rồi âm thầm lệch khỏi schema vào ngày một domain thêm field — đúng lớp lỗi
    mà `snapshot_dict` tồn tại để tránh ở đường thật.
    """
    from src.vehicle_sim.state import initial_state

    base = initial_state("veh-01")
    return base.model_copy(update={"motion": base.motion.model_copy(update={"speed_kph": speed, "gear": gear})})


class GatewayGia:
    """Cổng xe giả: ghi lại lệnh, trả kết quả theo kịch bản.

    Không dùng simulator thật vì bộ test này nói về **thứ tự và cổng an toàn**, không
    phải về MQTT. Nhưng nó vẫn đi qua `gateway.execute` thật của engine, nên chữ ký và
    các tham số (kể cả `approval_id`) được khoá y như đường thật.
    """

    def __init__(self, snapshot: object | None = "dung_yen", loi_o_buoc: int | None = None) -> None:
        self._snapshot = _state() if snapshot == "dung_yen" else snapshot
        self._loi_o_buoc = loi_o_buoc
        self.da_chay: list[tuple[str, dict, str | None]] = []

    async def snapshot(self):
        return self._snapshot

    async def execute(self, *, plan_id, step_id, tool, args, expected_state_version, approval_id=None):
        self.da_chay.append((tool, args, approval_id))
        hong = self._loi_o_buoc is not None and len(self.da_chay) - 1 == self._loi_o_buoc
        return GatewayToolResult(
            command_id=f"cmd-{len(self.da_chay)}",
            plan_id=plan_id,
            step_id=step_id,
            status="failed" if hong else "completed",
            before={},
            after={},
            expected_state_version=expected_state_version,
            observed_state_version=expected_state_version + 1,
            attempt_count=1,
            error_code="actuator_error" if hong else None,
            latency_ms=1,
        )


@pytest.fixture
def conn(tmp_path, monkeypatch):
    connection = connect(tmp_path / "exec.db")
    ensure_schema(connection)
    connection.execute("INSERT INTO users (id, email, password_hash, role) VALUES ('usr_a', 'a@x.vn', 'x', 'driver')")
    connection.execute("INSERT INTO users (id, email, password_hash, role) VALUES ('usr_b', 'b@x.vn', 'x', 'driver')")
    connection.commit()
    monkeypatch.setattr("src.db.get_connection", lambda: connection)
    monkeypatch.setattr("src.services.routines_store.get_connection", lambda: connection)
    monkeypatch.setattr("src.services.user_places.get_connection", lambda: connection)
    monkeypatch.setattr("src.services.routine_execution.get_connection", lambda: connection)
    yield connection
    connection.close()


@pytest.fixture
def store_sach(monkeypatch, conn):
    """`ApprovalStore` thật, trên đúng kết nối test."""
    from src.agents.approval import ApprovalStore

    store = ApprovalStore(connection=conn)
    monkeypatch.setattr("src.api.session_state.get_store", lambda: store)
    return store


def _dat_gateway(monkeypatch, gateway):
    monkeypatch.setattr("src.services.vehicle_gateway.get_vehicle_gateway", lambda: gateway)
    return gateway


async def _chay(conn, steps, *, gateway, monkeypatch, ten="Test"):
    routine = create_routine("usr_a", name=ten, icon="car", steps=steps, connection=conn)
    _dat_gateway(monkeypatch, gateway)
    return await engine.bat_dau(
        user_id="usr_a",
        session_id="ses-01",
        vehicle_id="veh-01",
        routine_id=routine.id,
        connection=conn,
    )


# --- đường xanh --------------------------------------------------------------


@pytest.mark.asyncio
async def test_ba_buoc_s1_chay_tuan_tu_va_ket_thuc_completed(conn, monkeypatch, store_sach):
    gateway = GatewayGia()

    execution = await _chay(
        conn,
        [
            {"action": "hvac_power", "enabled": True},
            {"action": "hvac_temperature", "temperatureC": 24},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "completed"
    assert [tool for tool, _, _ in gateway.da_chay] == [
        "set_hvac_power",
        "set_hvac_temperature",
        "set_interior_light",
    ]
    assert [r.status for r in execution.results] == ["completed"] * 3


# --- fail-fast ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_buoc_hong_thi_dung_va_buoc_sau_duoc_ghi_skipped(conn, monkeypatch, store_sach):
    """Bước chưa chạy **có mặt** trong sổ sách, không biến mất.

    Cùng lập luận với issue #83 ở `nodes/execute.py`: hồ sơ là thứ dùng để nói cái gì đã
    xảy ra và cái gì không.
    """
    gateway = GatewayGia(loi_o_buoc=1)

    execution = await _chay(
        conn,
        [
            {"action": "hvac_power", "enabled": True},
            {"action": "hvac_fan_level", "level": 2},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "failed"
    assert [r.status for r in execution.results] == ["completed", "failed", "skipped"]
    assert len(gateway.da_chay) == 2


# --- fail-closed -------------------------------------------------------------


@pytest.mark.asyncio
async def test_khong_doc_duoc_trang_thai_xe_thi_khong_chay_gi(conn, monkeypatch, store_sach):
    gateway = GatewayGia(snapshot=None)

    execution = await _chay(
        conn,
        [{"action": "hvac_power", "enabled": True}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "failed"
    assert execution.terminal_reason == "vehicle_state_unavailable"
    assert gateway.da_chay == []


# --- S3 chặn trước HITL ------------------------------------------------------


@pytest.mark.asyncio
async def test_buoc_hoa_s3_bi_chan_truoc_hitl_va_khong_hoi_tai_xe(conn, monkeypatch, store_sach):
    """Chỉnh ghế khi xe đang chạy là S3. §Chạy chốt: chặn trước HITL, không hỏi.

    Hỏi một câu mà câu trả lời "đồng ý" cũng không được phép thực hiện là mời người ta
    tin rằng có cách nói để vượt qua.
    """
    gateway = GatewayGia(snapshot=_state(speed=45.0, gear='D'))

    execution = await _chay(
        conn,
        [{"action": "seat_position", "seat": "frontLeft", "axis": "recline", "value": 40}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "blocked"
    assert execution.terminal_reason == "blocked_by_vehicle_state"
    assert gateway.da_chay == []
    assert store_sach.pending_for_session("ses-01") is None


# --- S2 dừng chờ phê duyệt ---------------------------------------------------


@pytest.mark.asyncio
async def test_buoc_s2_dung_cho_phe_duyet_va_khong_chay_buoc_nao(conn, monkeypatch, store_sach):
    """Mixed S1/S2: bước S1 **trước** nó đã chạy, bước S2 và các bước sau thì chưa.

    Đây là điểm khác đường lượt-nói (gộp cả plan vào một thẻ) và là hệ quả của §Chạy:
    mỗi bước S2 một thẻ, tuần tự.
    """
    gateway = GatewayGia()

    execution = await _chay(
        conn,
        [
            {"action": "hvac_power", "enabled": True},
            {"action": "window_position", "window": "frontLeft", "percent": 50},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "waiting_approval"
    assert execution.approval_id
    assert execution.current_index == 1
    assert [tool for tool, _, _ in gateway.da_chay] == ["set_hvac_power"]
    pending = store_sach.pending_for_session("ses-01")
    assert pending is not None and pending.approval_id == execution.approval_id


@pytest.mark.asyncio
async def test_dong_y_thi_chay_tiep_va_buoc_s2_mang_approval_id(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    execution = await _chay(
        conn,
        [
            {"action": "window_position", "window": "frontLeft", "percent": 50},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    store_sach.decide(execution.approval_id, approve=True)

    sau = await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=True, connection=conn)

    assert sau.status == "completed"
    tools = [tool for tool, _, _ in gateway.da_chay]
    assert tools == ["set_window_position", "set_interior_light"]
    # Bước S2 phải mang theo thẻ đã duyệt xuống tận cổng xe — đó là thứ nối hành động
    # với sự đồng ý, và là thứ audit đọc.
    assert gateway.da_chay[0][2] == execution.approval_id
    assert gateway.da_chay[1][2] is None


@pytest.mark.asyncio
async def test_tu_choi_thi_user_canceled_va_zero_side_effect(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    execution = await _chay(
        conn,
        [
            {"action": "window_position", "window": "frontLeft", "percent": 50},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    store_sach.decide(execution.approval_id, approve=False)

    sau = await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=False, connection=conn)

    assert sau.status == "user_canceled"
    assert sau.terminal_reason == "approval_rejected"
    assert [r.status for r in sau.results] == ["canceled", "skipped"]
    assert gateway.da_chay == []


@pytest.mark.asyncio
async def test_xe_chuyen_banh_trong_luc_cho_thi_van_bi_chan(conn, monkeypatch, store_sach):
    """Thẻ đã duyệt **không** cấp quyền vượt phân loại an toàn.

    Cửa sổ là S2 ở mọi trạng thái, nên ca này dùng chỉnh ghế: S2 lúc đứng yên, S3 lúc
    đang chạy. Đồng ý xong xe lăn bánh thì bước ấy phải chặn, không chạy.
    """
    gateway = GatewayGia()
    execution = await _chay(
        conn,
        [{"action": "seat_position", "seat": "frontLeft", "axis": "recline", "value": 40}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    assert execution.status == "waiting_approval"
    store_sach.decide(execution.approval_id, approve=True)
    gateway._snapshot = _state(speed=45.0, gear='D')

    sau = await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=True, connection=conn)

    assert sau.status == "blocked"
    assert gateway.da_chay == []


# --- không replay ------------------------------------------------------------


@pytest.mark.asyncio
async def test_quyet_dinh_toi_sau_khi_da_ket_thuc_khong_chay_gi_them(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )
    store_sach.decide(execution.approval_id, approve=True)
    await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=True, connection=conn)
    so_lenh = len(gateway.da_chay)

    lai = await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=True, connection=conn)

    assert lai is None
    assert len(gateway.da_chay) == so_lenh


@pytest.mark.asyncio
async def test_moi_lan_chay_la_mot_execution_moi(conn, monkeypatch, store_sach):
    """*"Không replay authorization/plan cũ"* — hai lần chạy là hai id khác nhau."""
    gateway = GatewayGia()
    routine = create_routine("usr_a", name="Hai lần", icon="car", steps=[{"action": "hvac_power", "enabled": True}], connection=conn)
    _dat_gateway(monkeypatch, gateway)

    lan_1 = await engine.bat_dau(
        user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
    )
    lan_2 = await engine.bat_dau(
        user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
    )

    assert lan_1.id != lan_2.id
    assert lan_1.status == lan_2.status == "completed"


# --- admission ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_routine_bi_tat_khong_chay_duoc(conn, monkeypatch, store_sach):
    from src.services.routines_store import set_enabled

    gateway = _dat_gateway(monkeypatch, GatewayGia())
    routine = create_routine("usr_a", name="Tắt", icon="car", steps=[{"action": "hvac_power", "enabled": True}], connection=conn)
    set_enabled("usr_a", routine.id, enabled=False, connection=conn)

    with pytest.raises(engine.RoutineKhongChayDuocError) as loi:
        await engine.bat_dau(
            user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
        )

    assert loi.value.ma == "routine_da_tat"
    assert gateway.da_chay == []


@pytest.mark.asyncio
async def test_chua_dat_dia_diem_thi_tu_choi_truoc_khi_co_side_effect(conn, monkeypatch, store_sach):
    """Bước dẫn đường đứng **sau** một bước S1: nếu admission không chặn trước thì bước
    S1 ấy đã chạy rồi Routine mới hỏng — người dùng nhận một nửa việc họ không xin."""
    gateway = _dat_gateway(monkeypatch, GatewayGia())
    routine = create_routine(
        "usr_a",
        name="Đi làm",
        icon="briefcase",
        steps=[
            {"action": "hvac_power", "enabled": True},
            {"action": "navigation", "destination": "office"},
        ],
        connection=conn,
    )

    with pytest.raises(engine.RoutineKhongChayDuocError) as loi:
        await engine.bat_dau(
            user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
        )

    assert loi.value.ma == "chua_dat_dia_diem"
    # #385: FE cần nhãn máy đọc được để mở đúng hàng Nhà/Cơ quan trong màn setup,
    # không phải câu tiếng Việt trong `thong_diep`.
    assert loi.value.thieu_dia_diem == ("office",)
    assert gateway.da_chay == []


@pytest.mark.asyncio
async def test_chua_dat_dia_diem_ca_hai_nhan_thi_liet_ke_ca_hai(conn, monkeypatch, store_sach):
    """#385: một Routine cần cả Nhà lẫn Cơ quan thì `thieu_dia_diem` phải liệt kê cả
    hai, không chỉ cái đầu tiên — FE mở đúng cả hai hàng, không phải đoán còn thiếu gì."""
    _dat_gateway(monkeypatch, GatewayGia())
    routine = create_routine(
        "usr_a",
        name="Cả ngày",
        icon="car",
        steps=[
            {"action": "navigation", "destination": "home"},
            {"action": "navigation", "destination": "office"},
        ],
        connection=conn,
    )

    with pytest.raises(engine.RoutineKhongChayDuocError) as loi:
        await engine.bat_dau(
            user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
        )

    assert loi.value.thieu_dia_diem == ("home", "office")


@pytest.mark.asyncio
async def test_gan_dia_diem_roi_thi_dan_duong_chay_voi_dung_destination(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    set_place("usr_a", "office", "poi-work-01", connection=conn)

    execution = await _chay(
        conn,
        [{"action": "navigation", "destination": "office"}],
        gateway=gateway,
        monkeypatch=monkeypatch,
        ten="Tới cơ quan",
    )

    assert execution.status == "completed"
    assert gateway.da_chay[0][1] == {"operation": "start", "destination_id": "poi-work-01"}


@pytest.mark.asyncio
async def test_mot_phien_khong_chay_hai_routine_cung_luc(conn, monkeypatch, store_sach):
    """Hai chuỗi lệnh chồng nhau sẽ tranh `expected_state_version`, nên bước của cái này
    làm bước của cái kia `stale_state` — một chế độ hỏng không đọc log ra nổi."""
    _dat_gateway(monkeypatch, GatewayGia())
    dang_cho = create_routine(
        "usr_a", name="Chờ duyệt", icon="car",
        steps=[{"action": "window_position", "window": "frontLeft", "percent": 50}], connection=conn,
    )
    khac = create_routine("usr_a", name="Khác", icon="car", steps=[{"action": "hvac_power", "enabled": True}], connection=conn)
    await engine.bat_dau(
        user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=dang_cho.id, connection=conn
    )

    with pytest.raises(engine.RoutineKhongChayDuocError) as loi:
        await engine.bat_dau(
            user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=khac.id, connection=conn
        )

    assert loi.value.ma == "dang_chay_routine_khac"


@pytest.mark.asyncio
async def test_routine_cua_nguoi_khac_khong_chay_duoc(conn, monkeypatch, store_sach):
    _dat_gateway(monkeypatch, GatewayGia())
    cua_a = create_routine("usr_a", name="Của A", icon="car", steps=[{"action": "hvac_power", "enabled": True}], connection=conn)

    with pytest.raises(engine.RoutineKhongChayDuocError) as loi:
        await engine.bat_dau(
            user_id="usr_b", session_id="ses-02", vehicle_id="veh-01", routine_id=cua_a.id, connection=conn
        )

    assert loi.value.ma == "routine_khong_ton_tai"


# --- đọc theo chủ sở hữu -----------------------------------------------------


@pytest.mark.asyncio
async def test_doc_execution_cua_nguoi_khac_khong_duoc(conn, monkeypatch, store_sach):
    gateway = GatewayGia()
    execution = await _chay(conn, [{"action": "hvac_power", "enabled": True}], gateway=gateway, monkeypatch=monkeypatch)

    with pytest.raises(LookupError):
        engine.doc("usr_b", execution.id, connection=conn)

    assert engine.doc("usr_a", execution.id, connection=conn).id == execution.id


def test_approval_khong_thuoc_routine_thi_tim_khong_ra(conn, store_sach):
    """Điểm rẽ ở `approvals.py` phải im lặng với thẻ của một lượt nói bình thường."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    store_sach.create(
        ApprovalRecord(
            approval_id="apr_cua_luot_noi",
            session_id="ses-01",
            turn_id="turn-01",
            plan_id="plan-01",
            plan_digest="digest",
            approved_vehicle_state_version=1,
            created_at=now,
            expires_at=now + timedelta(seconds=30),
            prompt_text="?",
        )
    )

    assert engine.tim_theo_approval("apr_cua_luot_noi", connection=conn) is None


# --- #299: huy bang giong phai map dung lan chay CUA PHIEN ---------------------


@pytest.mark.asyncio
async def test_dang_chay_trong_phien_tim_dung_lan_chay_cua_phien_nay(conn, monkeypatch, store_sach):
    """Hàm này đã tồn tại từ trước nhưng **không ai gọi** — cùng tình trạng
    `routines_intent` (#285). Bản đầu của `graph.py` cắm stub `lambda _sid: None` vì tôi
    grep bằng cái tên tự đặt (`dang_chay_cua_phien`) rồi kết luận hàm không có; hậu quả là
    mọi lượt hủy bằng giọng trả *"Hiện không có Routine nào đang chạy."* kể cả khi có.
    """
    routine = create_routine(
        "usr_a", name="Chạy dài", icon="car",
        # Bước S2: lần chạy dừng ở `waiting_approval`, tức **còn sống**. Một Routine
        # toàn S1 chạy xong ngay trong `bat_dau` nên không bao giờ có gì để hủy — đúng
        # hành vi, nhưng vô dụng cho test này, và đó là lý do bước cửa sổ có mặt ở đây.
        steps=[{"action": "window_position", "window": "frontLeft", "percent": 50}], connection=conn,
    )
    _dat_gateway(monkeypatch, GatewayGia())
    lan = await engine.bat_dau(
        user_id="usr_a", session_id="ses-A", vehicle_id="veh-01", routine_id=routine.id, connection=conn
    )
    thay = engine.dang_chay_trong_phien("ses-A", connection=conn)
    assert thay is not None and thay.id == lan.id


@pytest.mark.asyncio
async def test_phien_khac_khong_thay_lan_chay_cua_nguoi_ta(conn, monkeypatch, store_sach):
    """Ràng buộc quan trọng nhất của cổng hủy bằng giọng.

    Tài xế nói *"dừng lại"* mà **không nêu tên**. Tra theo `routine_id` thì một tiếng
    "dừng" ở phiên B sẽ dừng chuỗi lệnh đang chạy ở phiên A — trên cùng chiếc xe, đó là
    dừng nhầm việc của người khác. Tra theo `session_id` là thứ khiến chuyện đó không xảy
    ra, nên nó phải có test chứ không chỉ là một lựa chọn trong lúc viết.
    """
    routine = create_routine(
        "usr_a", name="Của phiên A", icon="car",
        steps=[{"action": "window_position", "window": "frontLeft", "percent": 50}], connection=conn,
    )
    _dat_gateway(monkeypatch, GatewayGia())
    await engine.bat_dau(
        user_id="usr_a", session_id="ses-A", vehicle_id="veh-01", routine_id=routine.id, connection=conn
    )
    assert engine.dang_chay_trong_phien("ses-B", connection=conn) is None


def test_phien_trong_thi_khong_thay_gi(conn):
    assert engine.dang_chay_trong_phien("ses-chua-chay-gi", connection=conn) is None


# --- câu tổng kết đọc to khi kết thúc (issue #396) ---------------------------


@pytest.mark.asyncio
async def test_routine_finished_mang_audio_khi_tts_thanh_cong(conn, monkeypatch, store_sach, bus_ghi):
    monkeypatch.setattr(voice, "synthesize_wav", lambda text: b"FAKE-WAV-BYTES")
    gateway = GatewayGia()

    await _chay(
        conn,
        [{"action": "hvac_power", "enabled": True}, {"action": "interior_light", "enabled": True}],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    finished = [e for e in bus_ghi.events if e["type"] == "routine.finished"]
    assert len(finished) == 1
    payload = finished[0]["payload"]
    assert payload["mime_type"] == "audio/wav"
    assert base64.b64decode(payload["audio_base64"]) == b"FAKE-WAV-BYTES"


@pytest.mark.asyncio
async def test_routine_finished_tts_loi_thi_audio_null_nhung_van_phat_binh_thuong(conn, monkeypatch, store_sach, bus_ghi):
    """Autouse `_stub_tts_unavailable` đã làm TTS raise sẵn — không override gì thêm.
    Fail-open: execution vẫn `completed`, `routine.finished` vẫn phát đúng một lần.
    """
    gateway = GatewayGia()

    execution = await _chay(
        conn, [{"action": "hvac_power", "enabled": True}], gateway=gateway, monkeypatch=monkeypatch
    )

    assert execution.status == "completed"
    finished = [e for e in bus_ghi.events if e["type"] == "routine.finished"]
    assert len(finished) == 1
    assert finished[0]["payload"]["audio_base64"] is None
    assert finished[0]["payload"]["mime_type"] is None


@pytest.mark.asyncio
async def test_cau_tong_ket_khi_dung_giua_chung_neu_ten_buoc_da_xong(conn, monkeypatch, store_sach, bus_ghi):
    """Bước 0 xong, bước 1 hỏng — câu tổng kết phải nhắc bước ĐÃ xong, không phải
    bước hỏng hay bước chưa chạy (mirror `test_buoc_hong_thi_dung_va_buoc_sau_duoc_ghi_skipped`,
    thêm kiểm text truyền vào TTS)."""
    da_goi: list[str] = []
    monkeypatch.setattr(voice, "synthesize_wav", lambda text: (da_goi.append(text), b"X")[1])
    gateway = GatewayGia(loi_o_buoc=1)

    execution = await _chay(
        conn,
        [
            {"action": "hvac_power", "enabled": True},
            {"action": "hvac_fan_level", "level": 2},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=gateway,
        monkeypatch=monkeypatch,
    )

    assert execution.status == "failed"
    # Chỉ bước 0 (hvac_power) completed — bước 1 (hvac_fan_level) failed và bước 2
    # (interior_light) skipped đều không được lọt vào câu nói, dù cả hai đều có
    # description riêng trong `results`.
    assert da_goi == ["Chuỗi lệnh dừng lại: bật điều hòa"]


@pytest.mark.asyncio
async def test_cau_tong_ket_khi_hong_ngay_buoc_dau_khong_co_buoc_nao_xong(conn, monkeypatch, store_sach, bus_ghi):
    da_goi: list[str] = []
    monkeypatch.setattr(voice, "synthesize_wav", lambda text: (da_goi.append(text), b"X")[1])
    gateway = GatewayGia(loi_o_buoc=0)

    execution = await _chay(
        conn, [{"action": "hvac_power", "enabled": True}], gateway=gateway, monkeypatch=monkeypatch
    )

    assert execution.status == "failed"
    assert da_goi == ["Chuỗi lệnh không thực hiện được bước nào."]

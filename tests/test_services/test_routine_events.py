"""Sự kiện tiến độ và kết quả cuối của Routine (issue #290).

Bốn mệnh đề của `#290` Done when, mỗi cái một test:

1. mỗi bước đi qua một tập trạng thái **đóng**;
2. mỗi lần chạy có đúng **một** sự kiện terminal, kể cả khi lỗi hay hủy;
3. **không** phát update nào sau terminal;
4. payload đủ để dựng tiến độ mà không mang dữ liệu ngoài phạm vi.
"""

import pytest

from src.db import connect, ensure_schema
from src.models.vehicle import ToolResult as GatewayToolResult
from src.services import routine_execution as engine
from src.services.routines_store import create_routine

#: Tập trạng thái đóng của một bước trên dây. Test khoá nó ở đây để một trạng thái mới
#: không lặng lẽ xuất hiện trong payload mà client chưa biết cách hiển thị.
TRANG_THAI_BUOC = {"completed", "failed", "skipped", "blocked", "canceled", "waiting_approval"}


def _state(*, speed: float = 0.0, gear: str = "P"):
    from src.vehicle_sim.state import initial_state

    base = initial_state("veh-01")
    return base.model_copy(update={"motion": base.motion.model_copy(update={"speed_kph": speed, "gear": gear})})


class GatewayGia:
    def __init__(self, snapshot: object | None = "dung_yen", loi_o_buoc: int | None = None) -> None:
        self._snapshot = _state() if snapshot == "dung_yen" else snapshot
        self._loi_o_buoc = loi_o_buoc
        self.da_chay: list[str] = []

    async def snapshot(self):
        return self._snapshot

    async def execute(self, *, plan_id, step_id, tool, args, expected_state_version, approval_id=None):
        self.da_chay.append(tool)
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


class BusGia:
    """Ghi lại sự kiện theo đúng thứ tự phát."""

    def __init__(self) -> None:
        self.da_phat: list[tuple[str, dict]] = []

    async def publish(self, session_id, event_type, turn_id, trace_id, payload):
        self.da_phat.append((event_type, payload))

    def loai(self) -> list[str]:
        return [t for t, _ in self.da_phat]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    connection = connect(tmp_path / "events.db")
    ensure_schema(connection)
    connection.execute("INSERT INTO users (id, email, password_hash, role) VALUES ('usr_a', 'a@x.vn', 'x', 'driver')")
    connection.commit()
    for module in ("src.db", "src.services.routines_store", "src.services.user_places", "src.services.routine_execution"):
        monkeypatch.setattr(f"{module}.get_connection", lambda: connection)
    yield connection
    connection.close()


@pytest.fixture
def bus(monkeypatch):
    gia = BusGia()
    monkeypatch.setattr("src.services.ivi_events.get_event_bus", lambda: gia)
    return gia


@pytest.fixture
def store_sach(monkeypatch, conn):
    from src.agents.approval import ApprovalStore

    store = ApprovalStore(connection=conn)
    monkeypatch.setattr("src.api.session_state.get_store", lambda: store)
    return store


async def _chay(conn, steps, *, gateway, monkeypatch, ten="Test"):
    routine = create_routine("usr_a", name=ten, icon="car", steps=steps, connection=conn)
    monkeypatch.setattr("src.services.vehicle_gateway.get_vehicle_gateway", lambda: gateway)
    return await engine.bat_dau(
        user_id="usr_a", session_id="ses-01", vehicle_id="veh-01", routine_id=routine.id, connection=conn
    )


@pytest.mark.asyncio
async def test_duong_xanh_phat_started_tung_buoc_roi_dung_mot_finished(conn, monkeypatch, bus, store_sach):
    await _chay(
        conn,
        [{"action": "hvac_power", "enabled": True}, {"action": "interior_light", "enabled": True}],
        gateway=GatewayGia(),
        monkeypatch=monkeypatch,
    )

    assert bus.loai() == ["routine.started", "routine.step", "routine.step", "routine.finished"]
    assert bus.loai().count("routine.finished") == 1


@pytest.mark.asyncio
async def test_started_mang_du_danh_sach_buoc_de_dung_tien_do(conn, monkeypatch, bus, store_sach):
    """UI cần biết **tổng số bước** ngay từ đầu, nếu không thanh tiến độ phải đoán."""
    await _chay(
        conn,
        [{"action": "hvac_power", "enabled": True}, {"action": "interior_light", "enabled": True}],
        gateway=GatewayGia(),
        monkeypatch=monkeypatch,
    )

    payload = bus.da_phat[0][1]
    assert payload["routine_name"] == "Test"
    assert [b["index"] for b in payload["steps"]] == [0, 1]
    assert payload["execution_id"].startswith("rex_")


@pytest.mark.asyncio
async def test_moi_trang_thai_buoc_deu_thuoc_tap_dong(conn, monkeypatch, bus, store_sach):
    await _chay(
        conn,
        [
            {"action": "hvac_power", "enabled": True},
            {"action": "hvac_fan_level", "level": 2},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=GatewayGia(loi_o_buoc=1),
        monkeypatch=monkeypatch,
    )

    for loai, payload in bus.da_phat:
        if loai == "routine.step":
            assert payload["status"] in TRANG_THAI_BUOC
        if loai == "routine.finished":
            assert all(r["status"] in TRANG_THAI_BUOC for r in payload["results"])


@pytest.mark.asyncio
async def test_loi_giua_chung_van_dung_mot_terminal_va_ke_ro_buoc_bi_bo(conn, monkeypatch, bus, store_sach):
    await _chay(
        conn,
        [
            {"action": "hvac_power", "enabled": True},
            {"action": "hvac_fan_level", "level": 2},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=GatewayGia(loi_o_buoc=1),
        monkeypatch=monkeypatch,
    )

    finished = [p for t, p in bus.da_phat if t == "routine.finished"]
    assert len(finished) == 1
    assert finished[0]["status"] == "failed"
    assert [r["status"] for r in finished[0]["results"]] == ["completed", "failed", "skipped"]


@pytest.mark.asyncio
async def test_cho_phe_duyet_phat_buoc_waiting_approval_kem_approval_id(conn, monkeypatch, bus, store_sach):
    """Client cần nối thẻ phê duyệt đang hiện với **bước nào** của Routine."""
    execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=GatewayGia(),
        monkeypatch=monkeypatch,
    )

    cho = [p for t, p in bus.da_phat if t == "routine.step" and p["status"] == "waiting_approval"]
    assert len(cho) == 1
    assert cho[0]["approval_id"] == execution.approval_id
    assert "routine.finished" not in bus.loai()


@pytest.mark.asyncio
async def test_tu_choi_cho_dung_mot_terminal_user_canceled(conn, monkeypatch, bus, store_sach):
    execution = await _chay(
        conn,
        [
            {"action": "window_position", "window": "frontLeft", "percent": 50},
            {"action": "interior_light", "enabled": True},
        ],
        gateway=GatewayGia(),
        monkeypatch=monkeypatch,
    )
    store_sach.decide(execution.approval_id, approve=False)

    await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=False, connection=conn)

    finished = [p for t, p in bus.da_phat if t == "routine.finished"]
    assert len(finished) == 1
    assert finished[0]["status"] == "user_canceled"
    assert finished[0]["terminal_reason"] == "approval_rejected"


@pytest.mark.asyncio
async def test_khong_phat_gi_them_sau_terminal(conn, monkeypatch, bus, store_sach):
    """Một quyết định tới sau khi execution đã kết thúc không được sinh sự kiện nào.

    Đây là vế "replay/reconnect giữ idempotency" của #290: client kết nối lại và thấy
    đúng một chuỗi, không phải hai bản chồng nhau.
    """
    execution = await _chay(
        conn,
        [{"action": "window_position", "window": "frontLeft", "percent": 50}],
        gateway=GatewayGia(),
        monkeypatch=monkeypatch,
    )
    store_sach.decide(execution.approval_id, approve=True)
    await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=True, connection=conn)
    so_su_kien = len(bus.da_phat)

    await engine.tiep_tuc_sau_phe_duyet(execution.approval_id, approved=True, connection=conn)

    assert len(bus.da_phat) == so_su_kien


@pytest.mark.asyncio
async def test_payload_khong_mang_du_lieu_ngoai_pham_vi(conn, monkeypatch, bus, store_sach):
    """Không `user_id`, không token, không args thô của lệnh.

    Args có thể chứa `destination_id` của địa điểm cá nhân — thứ không cần cho một thanh
    tiến độ, và mỗi field thừa trên stream là một field phải cân nhắc lại khi có người
    thứ hai nhìn màn hình.
    """
    await _chay(conn, [{"action": "hvac_power", "enabled": True}], gateway=GatewayGia(), monkeypatch=monkeypatch)

    for _, payload in bus.da_phat:
        assert "user_id" not in payload
        assert "args" not in payload
        for buoc in payload.get("steps", []) + payload.get("results", []):
            assert "args" not in buoc


@pytest.mark.asyncio
async def test_su_kien_phat_that_bai_khong_lam_hong_lan_chay(conn, monkeypatch, store_sach):
    """Tầng thông báo fail-open: bản ghi mới là nguồn sự thật."""

    class BusHong:
        async def publish(self, *args, **kwargs):
            raise RuntimeError("websocket sập")

    monkeypatch.setattr("src.services.ivi_events.get_event_bus", lambda: BusHong())

    execution = await _chay(
        conn, [{"action": "hvac_power", "enabled": True}], gateway=GatewayGia(), monkeypatch=monkeypatch
    )

    assert execution.status == "completed"

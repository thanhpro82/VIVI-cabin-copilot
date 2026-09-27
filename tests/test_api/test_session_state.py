"""State module-level phải có trần — `session_id` do client gửi nên không giới hạn."""

from datetime import UTC, datetime, timedelta

from src.api import session_state


def test_sessions_are_capped_so_a_long_running_server_does_not_grow_forever():
    """Review PR #25: `_GRAPHS` không có TTL hay trần.

    `session_id` nằm trong request body nên client tạo bao nhiêu phiên cũng được.
    """
    for index in range(session_state.MAX_SESSIONS + 40):
        session_state.get_graph(f"ses-{index}")
    assert session_state.session_count() <= session_state.MAX_SESSIONS


def test_the_most_recent_session_survives_eviction():
    """Đuổi phiên cũ nhất, không đuổi phiên đang dùng."""
    for index in range(session_state.MAX_SESSIONS + 10):
        session_state.get_graph(f"ses-{index}")
    newest = f"ses-{session_state.MAX_SESSIONS + 9}"
    assert session_state.has_session(newest)


def test_touching_a_session_keeps_it_alive():
    """Phiên được dùng lại phải được coi là mới, không bị đuổi vì tạo sớm."""
    session_state.get_graph("ses-quan-trong")
    for index in range(session_state.MAX_SESSIONS - 1):
        session_state.get_graph(f"ses-{index}")
    session_state.get_graph("ses-quan-trong")  # chạm lại
    for index in range(30):
        session_state.get_graph(f"ses-moi-{index}")
    assert session_state.has_session("ses-quan-trong")


def test_vehicle_state_is_global_so_two_sessions_see_the_same_car():
    """ĐẢO NGƯỢC CÓ CHỦ ĐÍCH so với bản trước (ADR-013).

    Bản cũ khẳng định mỗi phiên giữ một simulator riêng. Điều đó **không thể** đúng:
    `GET /api/v1/vehicle/state` không có tham số session, nên nó không có cách nào trả
    state theo phiên. Giữ mỗi phiên một chiếc xe nghĩa là agent đổi state ở một chỗ còn
    màn hình đọc ở chỗ khác — chính bug mà `VehicleGateway` sinh ra để đóng lại.
    """
    a = session_state.get_vehicle("ses-mot")
    b = session_state.get_vehicle("ses-hai")
    assert a is b


def test_evicting_a_session_also_drops_its_approvals():
    """Graph mất thì approval của phiên đó không resume được — đừng giữ lại."""
    store = session_state.get_store()
    session_state.get_graph("ses-se-bi-duoi")
    before = store.record_count

    for index in range(session_state.MAX_SESSIONS + 5):
        session_state.get_graph(f"ses-lam-day-{index}")

    assert not session_state.has_session("ses-se-bi-duoi")
    assert store.pending_for_session("ses-se-bi-duoi") is None
    assert store.record_count <= before + session_state.MAX_SESSIONS


def test_create_session_generates_a_session_id_and_records_ownership():
    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    assert record.session_id.startswith("ses_")
    assert record.user_id == "usr_driver_01"
    assert record.vehicle_id == "vehicle-demo-01"
    assert record.status == "active"
    assert session_state.get_session_record(record.session_id) == record


def test_get_session_record_returns_none_for_an_unknown_session():
    assert session_state.get_session_record("ses_does_not_exist") is None


def test_create_session_pre_warms_the_vehicle_and_graph():
    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    assert session_state.has_session(record.session_id)


def test_evicting_a_graph_keeps_the_session_record():
    """ĐỔI HỢP ĐỒNG (issue #46): trần `MAX_SESSIONS` là trần **bộ nhớ cho graph**,
    không phải hạn dùng của phiên.

    Bản trước xoá luôn hàng phiên, và hệ quả là người dùng nhận 403 "phiên không tồn
    tại" cho chính phiên mình vừa tạo chỉ vì có 128 người khác chen vào giữa. Từ khi
    phiên nằm trong SQLite, giữ hàng lại không tốn RAM: lượt kế tiếp chỉ cần một
    graph mới rỗng, còn cổng sở hữu ở `turns.py` vẫn tra ra chủ nhân.
    """
    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    for index in range(session_state.MAX_SESSIONS + 5):
        session_state.get_graph(f"ses-fill-{index}")
    assert not session_state.has_session(record.session_id), "graph phải bị đuổi khỏi bộ nhớ"
    assert session_state.get_session_record(record.session_id) == record


def test_evicting_a_graph_still_drops_its_approvals():
    """Approval thì ngược lại với hàng phiên: mất graph là mất checkpoint chứa
    `interrupt()`, nên approval của phiên đó không resume được nữa."""
    from tests.test_agents.test_approval_store import _record

    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    approval = session_state.get_store().create(_record(session=record.session_id))
    for index in range(session_state.MAX_SESSIONS + 5):
        session_state.get_graph(f"ses-fill-{index}")
    assert session_state.get_store().get(approval.approval_id) is None


def test_evicting_a_session_also_drops_its_citations():
    """Phiên mất thì id citation trong `assistant.response` của nó không ai gọi tới
    được nữa — giữ lại chỉ tổ chiếm chỗ trong trần."""
    from src.rag.models import Citation
    from src.services.citations import get_citation_store

    citation = Citation(
        citation_id="cit_se_bi_don",
        turn_id="turn-1",
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="…",
        retrieval_score=0.9,
    )
    session_state.get_graph("ses-se-bi-duoi")
    get_citation_store().save([citation], "ses-se-bi-duoi")

    for index in range(session_state.MAX_SESSIONS + 5):
        session_state.get_graph(f"ses-lam-day-cit-{index}")

    assert get_citation_store().get("cit_se_bi_don") is None


def test_slm_disabled_means_no_planner_and_no_behavior_change():
    """Cơ chế fallback của ADR-016: máy không bật SLM thì graph y hệt hôm nay."""
    from src.config import get_settings

    assert get_settings().slm_enabled is False  # mặc định repo — đổi default là đổi ADR
    graph = session_state.get_graph("ses-no-slm")
    assert graph is not None  # dựng được không cần llama-server


def test_bat_slm_thi_noi_planner_nhung_khong_noi_cau_dan(monkeypatch):
    """Hai cờ, hai vai — đã TÁCH ra, và tách có số.

    Bản trước là "một cờ, hai vai": bật `slm_enabled` thì nối cả planner lẫn câu dẫn.
    Lý do tách, đo 19/08 trên 39 câu hỏi (`eval/results/cau-dan/`):

    | cách sinh câu dẫn | p50 | câu dẫn chứa số |
    |---|---|---|
    | mẫu ghép từ câu hỏi | **0 ms** | **0%** |
    | Qwen 0.5B / CPU | 683 ms | **8%** |
    | Qwen 3B / dGPU | 421 ms | 0% |

    8% ấy gồm *"Áp suất lốp khuyến nghị của xe là 200 kPa"* (thật là 260/270). Và trên
    CPU câu dẫn 3B tốn 2316 ms — 64% của cả lượt. Hai vai chịu hai đánh đổi khác hẳn
    nhau, nên chúng không còn dùng chung một cờ.

    Nỗi lo cũ của test này — *"sót `lead_in` thì nhánh sổ tay im lặng dùng chuỗi cố
    định mãi mãi"* — nay không còn: đường lui là mẫu ghép từ câu hỏi, nói đúng chủ đề
    tài xế vừa hỏi. Test dưới khoá cả hai chiều để việc tách không âm thầm trôi ngược.
    """
    from src.agents import graph as graph_module
    from src.config import get_settings

    captured = {}

    def fake_build_graph(gateway, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(session_state, "build_graph", fake_build_graph)
    monkeypatch.setattr(get_settings(), "slm_enabled", True)

    session_state.get_graph("ses-slm-on")

    assert captured["planner"] is not None
    assert captured["lead_in"] is None, "mặc định câu dẫn phải là mẫu 0 ms, không gọi SLM"

    monkeypatch.setattr(get_settings(), "cau_dan_dung_slm", True)
    session_state._GRAPHS.clear()
    session_state.get_graph("ses-slm-cau-dan")
    assert captured["lead_in"] is not None, "bật cờ thì phải nối lại được đường SLM"
    assert type(captured["lead_in"]).__name__ == "QwenLeadIn"
    assert graph_module  # import dùng để chắc module nạp được khi bật cờ


def test_phien_qua_han_bi_coi_nhu_khong_ton_tai(monkeypatch):
    """Câu trả lời cho "API trả gì cho session đã hết hạn" (review PR #89).

    `get_session_record` trả `None`, và cả bốn call site (`turns.py`, `approvals.py`,
    `citation_routes.py`, `ws.py`) đã dịch `None` thành cùng một `403 FORBIDDEN`
    *"session không tồn tại hoặc không thuộc về bạn"*. Không thêm mã lỗi riêng cho
    "hết hạn": hai route đó cố ý gộp "không tồn tại" với "không phải của bạn" để
    không rò enumeration, và một mã riêng sẽ phá đúng tính chất ấy.
    """
    from src.config import get_settings
    from src.db import get_connection

    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    assert session_state.get_session_record(record.session_id) is not None

    # Đẩy lùi mốc bắt đầu thay vì bơm đồng hồ: TTL đo theo `started_at`.
    qua_han = datetime.now(UTC) - timedelta(hours=get_settings().session_ttl_hours + 1)
    connection = get_connection()
    connection.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (qua_han.isoformat(), record.session_id))
    connection.commit()

    assert session_state.get_session_record(record.session_id) is None


def test_doc_mot_phien_qua_han_tu_chot_no_sang_expired():
    """Phát hiện tại **thời điểm đọc** rồi CAS, đúng kỷ luật `ApprovalStore`.

    Không có bước này thì một phiên quá hạn vẫn chạy được cho tới lần khởi động sau —
    tức TTL chỉ có hiệu lực khi ai đó restart backend.
    """
    from src.config import get_settings
    from src.db import get_connection

    record = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    qua_han = datetime.now(UTC) - timedelta(hours=get_settings().session_ttl_hours + 1)
    connection = get_connection()
    connection.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (qua_han.isoformat(), record.session_id))
    connection.commit()

    session_state.get_session_record(record.session_id)

    row = connection.execute("SELECT status, ended_at FROM sessions WHERE id = ?", (record.session_id,)).fetchone()
    assert row["status"] == "expired"
    assert row["ended_at"] is not None, "chốt hết hạn mà không ghi mốc thì mất dấu vết audit"


def test_tao_phien_moi_don_luon_phien_qua_moc_luu_tru():
    """Backend chạy liên tục nhiều ngày thì đợt quét lúc khởi động không bao giờ chạy
    lần thứ hai — bảng chỉ có thể phình nếu không dọn ở đây."""
    from src.config import get_settings
    from src.db import get_connection

    cu = session_state.create_session("usr_driver_01", "vehicle-demo-01")
    connection = get_connection()
    rat_cu = datetime.now(UTC) - timedelta(days=get_settings().session_retention_days + 1)
    connection.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (rat_cu.isoformat(), cu.session_id))
    connection.commit()

    session_state.create_session("usr_driver_01", "vehicle-demo-01")

    con_lai = {row["id"] for row in connection.execute("SELECT id FROM sessions")}
    assert cu.session_id not in con_lai


def test_import_src_main_khong_cham_db_du_database_url_sai():
    """Issue #93: `DATABASE_URL` sai không được làm hỏng `import src.main`.

    Chạy trong **tiến trình con** chứ không reload module: ở tiến trình test mọi module
    đã nạp sẵn, nên reload chỉ kiểm được đúng cái mình nhớ reload — mà bug này chính là
    "còn một singleton nữa ở module khác". Sửa xong `session_state` thì
    `services/idempotency.py` vẫn làm hỏng import y hệt, và một test reload sẽ xanh
    trong khi backend vẫn chết.

    Hợp đồng: import phải qua được. Lỗi cấu hình chỉ được nổ lúc `lifespan` chạy, để
    khối kiểm tra trong `src/main.py` làm đúng việc nó sinh ra để làm — và người dùng
    nhận một câu nói rõ phải sửa gì thay vì traceback import.
    """
    import os
    import subprocess
    import sys

    ket_qua = subprocess.run(
        [sys.executable, "-c", "import src.main; print('IMPORT_OK')"],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": "postgresql://user:pass@localhost:5432/db", "MQTT_ENABLED": "false"},
        timeout=300,
    )

    assert "IMPORT_OK" in ket_qua.stdout, "import chết vì DATABASE_URL sai:\n" + ket_qua.stderr[-1500:]

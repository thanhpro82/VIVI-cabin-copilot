"""POST /api/v1/turns/text — nhánh S2/waiting_approval. Xem
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md mục "POST
/turns/text" (JSON shape cho waiting_approval) và event order
plan.ready -> approval.required -> assistant.status(waiting_approval)."""

import uuid

from fastapi.testclient import TestClient

from src.api.session_state import get_store
from src.main import app
from tests.test_api.ws_helpers import ivi_connect_kwargs, receive_n

_AUTH_HEADERS = {"X-Schema-Version": "1.0"}


def _idem() -> dict[str, str]:
    """Header bắt buộc của `POST /approvals/{id}/decision` (issue #44).

    Khoá **mới mỗi lần gọi** là điều kiện bắt buộc, không phải tiện tay: trùng
    `Idempotency-Key` nghĩa là "cùng một request", nên dùng lại khoá sẽ khiến lần gọi
    thứ hai trả về bản ghi cũ thay vì chạy thật — và test replay/double-click sẽ xanh
    vì lý do sai.
    """
    return {"X-Schema-Version": "1.0", "Idempotency-Key": f"idem-{uuid.uuid4().hex[:12]}"}


def _login(client, email: str = "driver.demo@example.com", password: str = "DemoDriver123!") -> str:
    response = client.post("/api/v1/auth/login", headers=_AUTH_HEADERS, json={"email": email, "password": password})
    return response.json()["data"]["access_token"]


def _create_session(client, token: str, key: str, vehicle_id: str = "vehicle-demo-01") -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": key},
        json={"vehicle_id": vehicle_id},
    )
    return response.json()["data"]["session_id"]


def _connection_init(session_id: str) -> dict:
    return {
        "type": "connection.init",
        "client_message_id": "cmsg_1",
        "sent_at": "2026-08-10T00:00:00Z",
        "schema_version": "1.0",
        "session_id": session_id,
    }


def test_s2_command_returns_waiting_approval_and_does_not_execute():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:s2:001")

        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))

            response = client.post(
                "/api/v1/turns/text",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Schema-Version": "1.0",
                    "Idempotency-Key": "turn:s2:001",
                },
                json={"session_id": session_id, "text": "Mở cửa sổ bên lái 30 phần trăm"},
            )
            assert response.status_code == 200
            body = response.json()["data"]
            assert body["status"] == "waiting_approval"
            assert body["action_plan"]["requires_approval"] is True
            assert body["action_plan"]["steps"][0]["tool"] == "set_window_position"
            assert body["pending_approval"]["approval_id"].startswith("appr-")
            assert body["pending_approval"]["expires_at"]
            assert body["response"]["outcomes"] == []
            turn_id = body["turn_id"]

            # Đọc tới `assistant.status`, **không** đếm cứng số event: từ issue #215
            # nhánh này còn phát `assistant.speech` (best-effort), nên số event phụ
            # thuộc việc máy chạy test có model Piper hay không. Cùng bài học với
            # `test_one_plan_ready_per_s2_turn` bên dưới.
            events = []
            while not any(e["type"] == "assistant.status" for e in events):
                events.extend(receive_n(ws, 1, timeout=10.0))

    types = [event["type"] for event in events]
    # `turn.accepted` mở đầu lượt gõ chữ từ #307 — trước đó chỉ `/turns/voice` phát nó.
    assert types[0] == "turn.accepted", types
    assert types[1] == "plan.ready", types
    assert types[-1] == "assistant.status", types
    assert types.count("approval.required") == 1, types
    # Tiếng nói (nếu máy có TTS) phải đứng TRƯỚC `approval.required`, xem issue #215:
    # IVI mở mic ngay khi hộp thoại duyệt hiện, nên phát sau là mời micro thu đúng
    # giọng của xe.
    if "assistant.speech" in types:
        assert types.index("assistant.speech") < types.index("approval.required"), types
    # Tra theo LOẠI: `turn.accepted` đứng trước `plan.ready` từ #307.
    ke_hoach = events[types.index("plan.ready")]
    assert ke_hoach["payload"]["requires_approval"] is True
    assert ke_hoach["payload"]["plan_id"] == body["action_plan"]["plan_id"]
    # Tra theo LOẠI, không theo chỉ số: `assistant.speech` chen vào giữa trên máy có TTS.
    duyet = events[types.index("approval.required")]
    assert duyet["payload"]["approval_id"] == body["pending_approval"]["approval_id"]
    assert events[-1]["payload"]["state"] == "waiting_approval"
    assert all(event["turn_id"] == turn_id for event in events)
    assert all(event["session_id"] == session_id for event in events)


def test_second_s2_command_while_one_is_pending_returns_clarify_not_completed():
    """Trước fix: outcome `approval_already_pending` rơi vào nhánh else -> status
    'completed', dù không có gì thực thi (outcomes rỗng, pending_approval None).
    Xem finding 2 của whole-branch review."""
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:s2:second:001")

        first = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:s2:second:001",
            },
            json={"session_id": session_id, "text": "Mở cửa sổ bên lái 30 phần trăm"},
        )
        assert first.json()["data"]["status"] == "waiting_approval"

        second = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:s2:second:002",
            },
            json={"session_id": session_id, "text": "Mở cửa sổ bên phụ 50 phần trăm"},
        )

    assert second.status_code == 200
    data = second.json()["data"]
    assert data["status"] == "clarify"
    assert data["response"]["outcomes"] == []
    assert data["pending_approval"] is None


def test_full_driver_flow_login_session_text_turn_then_approval_executes():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:e2e:001")

        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:e2e:001",
            },
            json={"session_id": session_id, "text": "Mở cửa sổ bên lái 30 phần trăm"},
        )
        approval_id = response.json()["data"]["pending_approval"]["approval_id"]

        decision = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**({"Authorization": f"Bearer {token}", **_AUTH_HEADERS}), **_idem()},
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )

    assert decision.status_code == 200
    # Body chỉ ghi nhận quyết định; thực thi chạy nền (api_spec.md:209) nên lúc hồi đáp
    # bản ghi mới ở `approved`. Kết quả thật đi qua /ws/ivi, và hiệu ứng đo ở store.
    assert decision.json() == {"approval_status": "approved"}
    assert get_store().get(approval_id).status == "consumed"


def test_mot_luot_s2_chi_phat_dung_mot_plan_ready():
    """Issue #94: lượt S2 phát `plan.ready` hai lần, cùng `plan_id`.

    `emit_turn_lifecycle` được gọi **hai lần** cho một lượt S2 — lần đầu từ
    `turns.py` (rơi vào nhánh `__interrupt__`), lần sau từ `approvals.py` khi resume.
    Cả hai nhánh đều phát `plan.ready`, nên client render thẻ kế hoạch hai lần và hai
    chỗ trong ring buffer 200 event của ADR-014 bị tiêu cho một thông tin.

    Máy trạng thái chuẩn (`api_spec.md` §Normative asynchronous voice-turn state
    machine) đặt `plan.ready` ở stage **"Control route/plan"**, trước nhánh policy;
    hai stage sau nó — "S2 pending" và "Successful execution" — đều không liệt kê nó.
    """
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:one-plan-ready:001")
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-13T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            response = client.post(
                "/api/v1/turns/text",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Schema-Version": "1.0",
                    "Idempotency-Key": "turn:one-plan-ready:001",
                },
                json={"session_id": session_id, "text": "Mở cửa sổ bên lái 30 phần trăm"},
            )
            approval_id = response.json()["data"]["pending_approval"]["approval_id"]
            # turn.accepted -> plan.ready -> approval.required -> assistant.status
            truoc_duyet = receive_n(ws, 4)

            client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={**{"Authorization": f"Bearer {token}", **_AUTH_HEADERS}, **_idem()},
                json={"decision": "approve", "approved_vehicle_state_version": 1},
            )
            # Đọc tới sự kiện terminal, **không** đếm cứng số event.
            #
            # Bản đầu của test này đọc đúng 4 event và vì thế phụ thuộc môi trường: trên
            # máy đã cài model Piper, `assistant.speech` chen vào trước
            # `assistant.response` nên `turn.completed` rơi ra ngoài cửa sổ đọc và test
            # đỏ vì một lý do không liên quan gì tới thứ nó kiểm. Đúng loại giòn mà
            # `_stub_tts_unavailable` ở `test_approval_routes.py` sinh ra để tránh.
            sau_duyet = []
            while not any(e["type"] == "turn.completed" for e in sau_duyet):
                sau_duyet.extend(receive_n(ws, 1, timeout=10.0))

    loai = [event["type"] for event in truoc_duyet + sau_duyet]
    assert loai.count("plan.ready") == 1, f"một lượt phải có đúng một plan.ready, nhận: {loai}"
    assert loai.index("plan.ready") < loai.index("approval.required"), (
        "plan.ready thuộc stage định tuyến, phải đi trước approval.required"
    )
    assert loai[0] == "turn.accepted", loai
    assert loai.count("turn.completed") == 1, "và vẫn đúng một terminal event"


# --- Câu hỏi duyệt phải đọc thành tiếng (issue #215) -------------------------
#
# Trước bản này nhánh `__interrupt__` của `emit_turn_lifecycle` `return` ngay sau ba
# event, **trước** dòng gọi `synthesize_speech` ở cuối hàm — nên xe hỏi tài xế một việc
# S2 trong im lặng, đúng khoảnh khắc duy nhất mà hệ thống bắt buộc phải có câu trả lời
# của con người. Đo trên trình duyệt thật 20/08: `waiting_approval` sau 44 ms, hộp thoại
# lên màn hình sau 3,0 s, và không một cú `play()` nào.


def _wav_gia(monkeypatch, so_byte: int = 2048) -> None:
    """Ép TTS **thành công** bất kể máy chạy test có model Piper hay không."""
    from src.services import voice

    monkeypatch.setattr(voice, "synthesize_wav", lambda text: b"RIFF" + b"\0" * so_byte)


def _tts_hong(monkeypatch) -> None:
    from src.services import voice

    def _raise(text):
        raise FileNotFoundError("no TTS model in test environment")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)


def _lay_su_kien_cho_duyet(client, token: str, khoa: str) -> list[dict]:
    session_id = _create_session(client, token, f"session:{khoa}")
    with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
        ws.send_json(_connection_init(session_id))
        client.post(
            "/api/v1/turns/text",
            headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": f"turn:{khoa}"},
            json={"session_id": session_id, "text": "Mở cửa sổ bên lái 30 phần trăm"},
        )
        events: list[dict] = []
        while not any(e["type"] == "assistant.status" for e in events):
            events.extend(receive_n(ws, 1, timeout=10.0))
    return events


def test_cau_hoi_duyet_duoc_doc_thanh_tieng_va_doc_truoc_khi_hien_hop_thoai(monkeypatch):
    """Thứ tự ở đây là điều kiện đúng đắn, không phải thẩm mỹ.

    IVI mở mic ngay khi `pendingApproval` được set (#203, #211), và với lượt **gõ chữ**
    thì `afterTranscriptHold` không hoãn gì cả. Phát `assistant.speech` sau
    `approval.required` là để lại một cửa sổ mà IVI thấy chưa có audio nào, mở mic ngay,
    rồi xe mới bắt đầu đọc — micro thu đúng giọng của xe. Đó chính là bug mà cổng
    chờ-audio sinh ra để chặn.
    """
    _wav_gia(monkeypatch)
    with TestClient(app) as client:
        token = _login(client)
        loai = [e["type"] for e in _lay_su_kien_cho_duyet(client, token, "s2:noi:001")]

    assert "assistant.speech" in loai, f"câu hỏi duyệt phải có tiếng, nhận: {loai}"
    assert loai.index("assistant.speech") < loai.index("approval.required"), loai
    assert loai[:2] == ["turn.accepted", "plan.ready"] and loai[-1] == "assistant.status", loai


def test_tts_hong_thi_luot_cho_duyet_van_du_ba_su_kien_nhu_cu(monkeypatch):
    """Fail-open: tiếng nói là best-effort, mất nó không được kéo theo lượt.

    Đây cũng là nửa giữ cho hợp đồng cũ còn đúng trên CI — nơi không cài model Piper.
    """
    _tts_hong(monkeypatch)
    with TestClient(app) as client:
        token = _login(client)
        loai = [e["type"] for e in _lay_su_kien_cho_duyet(client, token, "s2:im:001")]

    assert loai == ["turn.accepted", "plan.ready", "approval.required", "assistant.status"], loai

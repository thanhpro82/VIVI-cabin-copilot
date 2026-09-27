"""Một lượt thoại THẬT phải sinh ra một trace đầy đủ.

Các test khác kiểm từng mảnh (collector, fold, route, WS). Test này là mảnh duy
nhất chứng minh chúng nối được với nhau: `POST /turns/voice` → graph chạy →
`GET /traces/{id}` có số. Thiếu nó thì mọi mảnh đều xanh mà dashboard vẫn trắng —
đúng tình trạng `docs/handoff/frontend-integration-map.md:99` mô tả.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator

from fastapi.testclient import TestClient

from src.api import session_state
from src.main import app
from src.services import voice
from src.services.trace_store import get_trace_store
from tests.test_api.ws_helpers import ivi_connect_kwargs, login, login_engineer, receive_n


@contextlib.contextmanager
def dual_role_client() -> Iterator[TestClient]:
    """`TestClient` mang sẵn bearer engineer trên header.

    Test này đi qua CẢ HAI vai: tài xế chạy lượt (`/turns/*`, `/ws/ivi`) rồi kỹ sư
    đọc kết quả (`/traces/{id}`, `/metrics/summary` — Engineer-only từ issue #45 B1).
    Header mặc định là engineer vì chỉ đường đọc mới cần nó: `/turns/voice` không
    khai auth, còn `/turns/text` + `/sessions` nhận token driver qua header truyền
    tường minh ở từng lời gọi, ghi đè header mặc định.
    """
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {login_engineer(client)}"
        yield client

def _idem() -> dict[str, str]:
    """Header bắt buộc của `POST /approvals/{id}/decision` (issue #44).

    Khoá **mới mỗi lần gọi** là điều kiện bắt buộc, không phải tiện tay: trùng
    `Idempotency-Key` nghĩa là "cùng một request", nên dùng lại khoá sẽ khiến lần gọi
    thứ hai trả về bản ghi cũ thay vì chạy thật — và test replay/double-click sẽ xanh
    vì lý do sai.
    """
    return {"X-Schema-Version": "1.0", "Idempotency-Key": f"idem-{uuid.uuid4().hex[:12]}"}



def _connection_init(session_id: str) -> dict:
    return {
        "type": "connection.init",
        "client_message_id": "cmsg_1",
        "sent_at": "2026-08-10T00:00:00Z",
        "schema_version": "1.0",
        "session_id": session_id,
    }


def _stub_stt(monkeypatch, text: str, latency_ms: float = 42.0) -> None:
    monkeypatch.setattr(voice, "get_stt_engine", lambda: object())
    monkeypatch.setattr(
        voice,
        "transcribe_raw",
        lambda audio: voice.Transcript(text=text, latency_ms=latency_ms, confidence=0.9),
    )


def _run_turn(client: TestClient, expected_events: int) -> str:
    """`/turns/voice` giờ đòi bearer driver + session do chính driver đó sở hữu
    (auth-hardening trên nhánh này), cộng với ownership check của `/ws/ivi`
    (issue #47) nên phải dựng `SessionRecord` thật để nối WS được."""
    token = login(client)
    session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
    with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
        ws.send_json(_connection_init(session_id))
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": session_id},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Content-Type": "audio/wav",
                "Idempotency-Key": f"voice:trace-e2e:{session_id}",
            },
            content=b"fake-wav-bytes",
        )
        assert response.status_code == 202
        receive_n(ws, expected_events)
    return response.json()["trace_id"]


def test_luot_dieu_khien_s1_sinh_trace_co_stage_latency(monkeypatch):
    _stub_stt(monkeypatch, "Đặt điều hòa 22 độ")

    with dual_role_client() as client:
        trace_id = _run_turn(client, 8)
        data = client.get(f"/api/v1/traces/{trace_id}").json()["data"]

    assert data["status"] == "completed"
    assert data["turn_id"].startswith("turn_voice_")

    stages = data["stage_latencies_ms"]
    # `stt` lấy từ `Transcript.latency_ms` — trước ticket này bị vứt ở turns.py.
    assert stages["stt"] == 42.0
    # `safety` và `tool` từ wrapper `_timed` trong graph.py. `tool` phải đo tại node
    # vì payload `tool.result` không mang `latency_ms`.
    assert stages["safety"] is not None
    assert stages["tool"] is not None
    # `end_to_end` đo ở turns.py. KHÔNG khẳng định `end_to_end >= stt` ở đây: STT bị
    # stub nên chạy tức thì trong khi `latency_ms=42.0` là số bịa của stub. Quan hệ
    # đó chỉ đúng với STT thật.
    assert stages["end_to_end"] > 0
    # `routing` cũng từ `_timed` — đây là ô đo chính cái mà ADR-006 khẳng định.
    assert stages["routing"] is not None
    # Lượt điều khiển không đi qua RAG/SLM — `null`, KHÔNG phải 0.
    assert stages["planning_or_retrieval"] is None

    # Ba field dưới đây KHÔNG có trên bus `/ws/ivi`; chúng tới từ `record_graph_result`.
    # `max_level` đặc biệt quan trọng: lượt này **có tác động tới xe**, để mặc định
    # `S0` là gắn nhãn chỉ-đọc cho một lệnh actuator.
    assert data["route_source"] == "deterministic"
    assert data["confidence"] is not None
    assert data["safety_summary"]["max_level"] == "S1"
    assert data["safety_summary"]["outcome"] == "executed"

    assert data["safety_summary"]["admission"] == "executed"
    assert data["admission"]["actual_vehicle_state_version"] is not None


def test_luot_tra_so_tay_do_stage_planning_or_retrieval(monkeypatch):
    """Nhánh RAG đi qua node khác hẳn nhánh điều khiển."""
    _stub_stt(monkeypatch, "Đèn cảnh báo áp suất lốp nghĩa là gì")

    with dual_role_client() as client:
        trace_id = _run_turn(client, 7)
        data = client.get(f"/api/v1/traces/{trace_id}").json()["data"]

    assert data["stage_latencies_ms"]["planning_or_retrieval"] is not None
    assert data["safety_summary"]["admission"] == "not_applicable"


def test_metrics_dem_dung_luot_vua_chay(monkeypatch):
    _stub_stt(monkeypatch, "Đặt điều hòa 22 độ")

    with dual_role_client() as client:
        _run_turn(client, 8)
        data = client.get("/api/v1/metrics/summary").json()["data"]

    assert data["turns"]["accepted"] == 1
    assert data["turns"]["completed"] == 1
    assert data["stage_latency_ms"]["stt"]["count"] == 1
    assert data["stage_latency_ms"]["stt"]["p50"] == 42.0
    assert data["action_audit"]["attempted"] == 1
    assert data["action_audit"]["completed"] == 1
    assert data["mqtt"]["published"] == 1
    assert data["mqtt"]["error_rate"] == 0.0


def test_luot_hong_stt_van_duoc_seal_va_dem_vao_turns_failed(monkeypatch):
    """Đường thoát lỗi này KHÔNG đi qua `emit_turn_lifecycle`.

    Chính nó là lý do trace thu bằng cách nghe bus. Seal bên trong
    `emit_turn_lifecycle` sẽ bỏ sót lượt này và `turns.failed` đếm thiếu.
    """
    monkeypatch.setattr(voice, "get_stt_engine", lambda: object())

    def _boom(audio):
        raise ValueError("sample rate không hợp lệ")

    monkeypatch.setattr(voice, "transcribe_raw", _boom)

    with dual_role_client() as client:
        trace_id = _run_turn(client, 5)
        data = client.get(f"/api/v1/traces/{trace_id}").json()["data"]
        metrics = client.get("/api/v1/metrics/summary").json()["data"]

    assert data["status"] == "failed"
    assert data["safety_summary"]["block_code"] == "STT_FAILED"
    assert data["stage_latencies_ms"]["end_to_end"] is not None
    assert metrics["turns"] == {"accepted": 1, "completed": 0, "failed": 1, "canceled": 0}


def test_trace_id_cua_response_202_chinh_la_khoa_tra_cuu(monkeypatch):
    """Hợp đồng phục hồi của `api_spec.md:646`: client dùng `trace_id` từ 202."""
    _stub_stt(monkeypatch, "Đặt điều hòa 22 độ")

    with dual_role_client() as client:
        trace_id = _run_turn(client, 8)

        assert get_trace_store().get(trace_id) is not None
        assert client.get(f"/api/v1/traces/{trace_id}").status_code == 200


# -- POST /turns/text ---------------------------------------------------------
#
# Route đồng bộ, KHÔNG phát `turn.accepted`, nên `TraceCollector` không tự mở bản
# ghi — `submit_text_turn` phải mở thẳng vào kho. Thiếu bước đó thì mọi lượt gõ
# text biến mất khỏi `/metrics/summary` mà không có dấu hiệu gì.

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}


def _login(client) -> str:
    response = client.post(
        "/api/v1/auth/login",
        headers=_SCHEMA_HEADERS,
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    return response.json()["data"]["access_token"]


def _create_session(client, token: str, key: str) -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": key},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    return response.json()["data"]["session_id"]


def _post_text(client, token: str, session_id: str, key: str, text: str):
    return client.post(
        "/api/v1/turns/text",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": key},
        json={"session_id": session_id, "text": text},
    )


def test_luot_text_cung_sinh_trace_day_du():
    with dual_role_client() as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:trace:001")

        response = _post_text(client, token, session_id, "turn:trace:001", "Đặt điều hòa 22 độ")
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]

        data = client.get(f"/api/v1/traces/{trace_id}").json()["data"]
        metrics = client.get("/api/v1/metrics/summary").json()["data"]

    assert data["status"] == "completed"
    assert data["turn_id"] == response.json()["data"]["turn_id"]
    assert data["stage_latencies_ms"]["end_to_end"] is not None
    assert data["stage_latencies_ms"]["safety"] is not None
    # Lượt text không qua STT — `null`, KHÔNG phải 0.
    assert data["stage_latencies_ms"]["stt"] is None

    assert metrics["turns"] == {"accepted": 1, "completed": 1, "failed": 0, "canceled": 0}
    assert metrics["action_audit"]["completed"] == 1


def test_hai_luot_text_cung_x_trace_id_khong_bi_tron_lam_mot():
    """`trace_id` của `/turns/text` là khoá **client chi phối được**.

    `request_scoped_ids()` nhận thẳng header `X-Trace-Id` (`api_spec.md:9` cho
    phép), nên client gửi lại cùng giá trị cho hai lượt sẽ trỏ vào cùng một khoá
    kho. Nếu `TraceStore.open()` idempotent theo `trace_id` đơn thuần thì lượt thứ
    hai âm thầm nhập vào bản ghi lượt đầu: `turns.accepted` đếm thiếu và
    `GET /traces/{id}` trả ra một bản ghi lai hai lượt.
    """
    reused = "tr_client_dung_lai_01"
    headers_extra = {"X-Trace-Id": reused}

    with dual_role_client() as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:trace:003")

        first = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:trace:003a",
                **headers_extra,
            },
            json={"session_id": session_id, "text": "Đặt điều hòa 22 độ"},
        )
        second = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:trace:003b",
                **headers_extra,
            },
            json={"session_id": session_id, "text": "Đặt điều hòa 24 độ"},
        )

        assert first.json()["trace_id"] == reused
        assert second.json()["trace_id"] == reused
        data = client.get(f"/api/v1/traces/{reused}").json()["data"]

    turn_one = first.json()["data"]["turn_id"]
    turn_two = second.json()["data"]["turn_id"]
    assert turn_one != turn_two
    # Lượt mới thắng khoá — bản ghi thuộc về đúng MỘT lượt, không lai.
    assert data["turn_id"] == turn_two


def test_luot_text_cho_duyet_s2_giu_trace_o_waiting_approval():
    with dual_role_client() as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:trace:002")

        response = _post_text(client, token, session_id, "turn:trace:002", "Mở cửa sổ bên lái 50")
        assert response.json()["data"]["status"] == "waiting_approval"
        trace_id = response.json()["trace_id"]

        data = client.get(f"/api/v1/traces/{trace_id}").json()["data"]
        metrics = client.get("/api/v1/metrics/summary").json()["data"]

    assert data["status"] == "waiting_approval"
    assert data["pending_approval"]["approval_id"]
    assert data["admission"]["status"] == "pending"
    assert data["safety_summary"]["max_level"] == "S2"
    # Lượt còn treo: đếm vào `accepted` nhưng chưa vào nhóm terminal nào —
    # api_spec.md:456 "in-flight accepted turns need not equal terminal totals".
    assert metrics["turns"] == {"accepted": 1, "completed": 0, "failed": 0, "canceled": 0}
    assert metrics["safety"]["approvals_required"] == 1


def test_luot_s2_sau_khi_duyet_van_seal_dung_trace_ban_dau():
    """Nửa sau của lượt S2 mang `trace_id` KHÁC nửa đầu.

    `src/api/approvals.py:_resume_and_publish` (PR #36, thực thi chạy nền) đúc một
    `trace_id` mới, nên `turn.completed` phát dưới một trace chưa từng được mở. Nếu
    `TraceCollector` chỉ khớp theo `trace_id` thì mọi lượt cần duyệt sẽ treo ở
    `waiting_approval` vĩnh viễn, không bao giờ có event `trace`, và
    `turns.completed` đếm thiếu đúng những lượt đáng chú ý nhất.

    Nối lại bằng index `turn_id` — thứ xuyên suốt cả hai nửa.
    """
    with dual_role_client() as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:trace:004")

        response = _post_text(client, token, session_id, "turn:trace:004", "Mở cửa sổ bên lái 50")
        trace_id = response.json()["trace_id"]
        approval_id = response.json()["data"]["pending_approval"]["approval_id"]

        decision = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**({"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"}), **_idem()},
            json={"decision": "approve"},
        )
        assert decision.status_code == 200

        data = client.get(f"/api/v1/traces/{trace_id}").json()["data"]
        metrics = client.get("/api/v1/metrics/summary").json()["data"]

    # Trace ban đầu đã chốt, KHÔNG còn treo ở waiting_approval.
    assert data["status"] == "completed"
    assert data["pending_approval"] is None
    assert data["admission"]["status"] == "executed"
    assert metrics["turns"]["completed"] == 1
    assert metrics["safety"]["approved"] == 1
    assert metrics["action_audit"]["completed"] == 1

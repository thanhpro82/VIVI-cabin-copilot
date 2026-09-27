"""Route quyết định canonical. `hitl_action_id` của ticket chính là `approval_id`."""

import base64
import uuid

import anyio
import pytest
from fastapi.testclient import TestClient

from src.api import session_state
from src.api.session_state import get_store, get_vehicle
from src.main import app
from src.services import voice
from src.services.ivi_events import get_event_bus
from src.services.vehicle_gateway import snapshot_dict
from tests.conftest import seed_test_user
from tests.test_api.ws_helpers import ivi_connect_kwargs, receive_n

OPEN_WINDOW = {"query": "Mở cửa sổ bên lái 30 phần trăm", "vehicle_speed_kmh": 0.0}
_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_LOGIN = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}


@pytest.fixture(autouse=True)
def _stub_tts_unavailable(monkeypatch):
    """TTS luôn thất bại mặc định trong file này — không phụ thuộc việc máy chạy test
    có sẵn model Piper thật hay không (issue #66). Test nào cần audio thành công tự
    override bằng monkeypatch.setattr(voice, "synthesize_wav", ...) riêng trong thân test."""

    def _raise(text):
        raise FileNotFoundError("no TTS model in test environment")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)

def _idem() -> dict[str, str]:
    """Header bắt buộc của `POST /approvals/{id}/decision` (issue #44).

    Khoá **mới mỗi lần gọi** là điều kiện bắt buộc, không phải tiện tay: trùng
    `Idempotency-Key` nghĩa là "cùng một request", nên dùng lại khoá sẽ khiến lần gọi
    thứ hai trả về bản ghi cũ thay vì chạy thật — và test replay/double-click sẽ xanh
    vì lý do sai.
    """
    return {"X-Schema-Version": "1.0", "Idempotency-Key": f"idem-{uuid.uuid4().hex[:12]}"}



def _owned_session(user_id: str = "usr_driver_01") -> str:
    """Phiên có `SessionRecord` thật, do `user_id` sở hữu.

    `/agent/process` (dev-only) nhận `session_id` tuỳ ý và không tạo `SessionRecord`,
    nên một chuỗi tự chế sẽ không qua được kiểm quyền sở hữu ở route quyết định.
    """
    seed_test_user(user_id)  # sessions.user_id là FK từ #89 — xem _owned_session ở test_ws_ivi.py
    return session_state.create_session(user_id, "vehicle-demo-01").session_id


def _sync_auth(client) -> dict[str, str]:
    token = client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=_LOGIN).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}


async def _auth(client) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=_LOGIN)
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}", **_SCHEMA_HEADERS}


async def _pending(client, session_id: str) -> str:
    response = await client.post("/api/v1/agent/process", json={**OPEN_WINDOW, "session_id": session_id})
    body = response.json()
    assert body["status"] == "PENDING_HITL", body
    assert body["hitl_pending"] is True
    assert body["timeout_seconds"] == 30
    return body["hitl_action_id"]


async def test_s2_returns_pending_hitl_with_an_action_id(client):
    approval_id = await _pending(client, _owned_session())
    assert approval_id.startswith("appr-")


async def test_approve_executes_and_reports_canonical_status(client):
    approval_id = await _pending(client, _owned_session())
    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        headers={**(await _auth(client)), **_idem()},
        json={"decision": "approve", "approved_vehicle_state_version": 1},
    )
    body = response.json()
    # Body chỉ ghi nhận quyết định; thực thi chạy nền nên lúc hồi đáp mới là `approved`.
    assert body["approval_status"] == "approved"
    # Hiệu ứng thật thì vẫn phải xảy ra — đo ở store và ở chiếc xe, không đọc body.
    assert get_store().get(approval_id).status == "consumed"
    assert snapshot_dict(get_vehicle("ses-approve").state)["windows"]["front_left"] == 30


async def test_reject_cancels_the_plan(client):
    approval_id = await _pending(client, _owned_session())
    body = (
        await client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**(await _auth(client)), **_idem()},
            json={"decision": "reject", "approved_vehicle_state_version": 1},
        )
    ).json()
    assert body["approval_status"] == "rejected"
    assert snapshot_dict(get_vehicle("ses-reject").state)["windows"]["front_left"] == 0


async def test_replaying_approve_does_not_execute_twice(client):
    approval_id = await _pending(client, _owned_session())
    headers = await _auth(client)
    payload = {"decision": "approve", "approved_vehicle_state_version": 1}
    first = (await client.post(f"/api/v1/approvals/{approval_id}/decision", headers={**headers, **_idem()}, json=payload)).json()
    second = (await client.post(f"/api/v1/approvals/{approval_id}/decision", headers={**headers, **_idem()}, json=payload)).json()
    assert first["approval_status"] == "approved"
    assert get_store().get(approval_id).status == "consumed"
    executed_once = get_vehicle("ses-replay").command_count
    # Lần hai: bản ghi đã `consumed` nên route không resume graph nữa. Bất biến cần
    # khoá là **không chạy lại**, và giờ nó đo thẳng ở chiếc xe chứ không qua body.
    assert second["approval_status"] == "consumed"
    assert get_vehicle("ses-replay").command_count == executed_once


async def test_a_command_refused_once_can_be_asked_again(client):
    """Từ chối rồi đổi ý: lượt sau phải xin phép lại được, qua đúng đường HTTP.

    Trước đây `approval_id` không gồm lượt, mà lượt bị từ chối không đổi state xe nên
    lượt sau băm ra đúng id cũ và nhặt lại bản ghi `rejected` — approve lần hai trả về
    "canceled" và người dùng kẹt với câu lệnh đó.
    """
    first_id = await _pending(client, _owned_session())
    rejected = (
        await client.post(
            f"/api/v1/approvals/{first_id}/decision",
            headers={**(await _auth(client)), **_idem()},
            json={"decision": "reject", "approved_vehicle_state_version": 1},
        )
    ).json()
    assert rejected["approval_status"] == "rejected"

    second_id = await _pending(client, _owned_session())
    assert second_id != first_id
    approved = (
        await client.post(
            f"/api/v1/approvals/{second_id}/decision",
            headers={**(await _auth(client)), **_idem()},
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )
    ).json()
    assert approved["approval_status"] == "approved"
    assert get_store().get(second_id).status == "consumed"


async def test_two_sessions_running_the_same_command_stay_isolated(client):
    """Quyết định của phiên này không được chạm vào lượt đang chờ của phiên kia.

    Hàng rào, không phải bằng chứng vá lỗi: `session_id` vốn đã nằm trong `ActionPlan`
    nên digest — và do đó id — vốn đã lệch giữa hai phiên. Test này khoá bất biến đó
    lại để nó không lặng lẽ mất khi `ActionPlan` hay cách suy ra id đổi.
    """
    id_a = await _pending(client, _owned_session())
    id_b = await _pending(client, _owned_session())
    assert id_a != id_b

    body = (
        await client.post(
            f"/api/v1/approvals/{id_a}/decision",
            headers={**(await _auth(client)), **_idem()},
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )
    ).json()
    assert body["approval_status"] == "approved"

    # Cách ly nằm ở **bản ghi approval**, không ở trạng thái xe: từ ADR-013 chỉ có
    # đúng một chiếc xe cho cả hệ thống, nên phiên B nhìn thấy kính đã mở là đúng.
    # Bất biến thật sự cần khoá là lượt chờ của B **không** bị quyết định của A đụng tới.
    assert get_store().get(id_b).status == "pending"
    assert snapshot_dict(get_vehicle("ses-iso-a").state)["windows"]["front_left"] == 30


def test_route_is_in_the_public_openapi_surface():
    """Khác `/agent/process`: đây là một trong 14 interface P0 của api_spec.md."""
    assert "/api/v1/approvals/{approval_id}/decision" in app.openapi()["paths"]


async def test_s1_command_does_not_create_any_approval(client):
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Đặt điều hòa 22 độ", "vehicle_speed_kmh": 0.0, "session_id": "ses-s1"},
    )
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["hitl_pending"] is False
    assert body["hitl_action_id"] is None


def test_approve_publishes_ws_lifecycle_through_to_turn_completed():
    with TestClient(app) as client:
        session_id = _owned_session()
        # Đăng nhập TRƯỚC khi mở WS: `TestClient` chạy WS trên một portal riêng, gọi
        # HTTP bên trong khối `websocket_connect` sẽ khoá lẫn nhau.
        headers = _sync_auth(client)
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": session_id},
        )
        approval_id = pending.json()["hitl_action_id"]

        ivi_token = headers["Authorization"].removeprefix("Bearer ")
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(ivi_token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )

            decision = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={**(headers), **_idem()},
                json={"decision": "approve", "approved_vehicle_state_version": 1},
            )
            assert decision.json()["approval_status"] == "approved"

            events = receive_n(ws, 4)

    # ĐỔI HỢP ĐỒNG (issue #94): chuỗi sau khi duyệt **không** còn `plan.ready` mở đầu.
    #
    # Bản trước chờ 5 event và khoá `plan.ready` ở vị trí 0 — tức nó ghi lại đúng cái
    # bug: một lượt S2 phát hai `plan.ready` cùng `plan_id`, một ở nhánh
    # `__interrupt__` và một nữa khi resume. Test này chạy sau `POST /agent/process`
    # nên nó chỉ nhìn thấy nửa sau của lượt, và cái `plan.ready` nó bắt được chính là
    # bản thừa.
    #
    # `api_spec.md` §Normative asynchronous voice-turn state machine đặt `plan.ready`
    # ở stage "Control route/plan"; stage "Successful execution" chỉ có
    # `assistant.status(executing)` → `tool.result` → `assistant.response` →
    # `turn.completed`, đúng bốn event dưới đây.
    types = [event["type"] for event in events]
    assert types == ["assistant.status", "tool.result", "assistant.response", "turn.completed"]
    assert events[0]["payload"]["state"] == "executing"
    assert events[1]["payload"]["status"] == "completed"


def test_reject_publishes_turn_canceled():
    with TestClient(app) as client:
        session_id = _owned_session()
        # Đăng nhập TRƯỚC khi mở WS: `TestClient` chạy WS trên một portal riêng, gọi
        # HTTP bên trong khối `websocket_connect` sẽ khoá lẫn nhau.
        headers = _sync_auth(client)
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": session_id},
        )
        approval_id = pending.json()["hitl_action_id"]

        ivi_token = headers["Authorization"].removeprefix("Bearer ")
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(ivi_token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )

            decision = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={**(headers), **_idem()},
                json={"decision": "reject", "approved_vehicle_state_version": 1},
            )
            assert decision.json()["approval_status"] == "rejected"

            events = receive_n(ws, 2)

    types = [event["type"] for event in events]
    assert types == ["assistant.response", "turn.canceled"]
    assert events[1]["payload"]["reason"] == "approval_rejected"


def test_reject_emits_assistant_speech_before_assistant_response(monkeypatch):
    """Nhánh reject là lượt an toàn nhất (tài xế vừa từ chối một S2) và trước Fix 3
    không hề thử TTS. Giờ nó phải đi qua đúng cùng đường `_publish_assistant_response`
    như mọi outcome khác."""
    monkeypatch.setattr(voice, "synthesize_wav", lambda text: b"FAKE-WAV-BYTES")

    with TestClient(app) as client:
        session_id = _owned_session()
        headers = _sync_auth(client)
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": session_id},
        )
        approval_id = pending.json()["hitl_action_id"]

        ivi_token = headers["Authorization"].removeprefix("Bearer ")
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(ivi_token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )

            decision = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={**(headers), **_idem()},
                json={"decision": "reject", "approved_vehicle_state_version": 1},
            )
            assert decision.json()["approval_status"] == "rejected"

            events = receive_n(ws, 3)

    types = [event["type"] for event in events]
    assert types == ["assistant.speech", "assistant.response", "turn.canceled"]
    speech_payload = events[0]["payload"]
    assert speech_payload["mime_type"] == "audio/wav"
    assert base64.b64decode(speech_payload["audio_base64"]) == b"FAKE-WAV-BYTES"


def test_reject_still_completes_when_tts_synthesis_fails(monkeypatch):
    """Fail-open: TTS lỗi không được chặn `assistant.response`/`turn.canceled` của
    nhánh reject, giống hệt bảo đảm đã có ở `emit_turn_lifecycle`."""

    def _raise(text):
        raise RuntimeError("piper model missing")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)

    with TestClient(app) as client:
        session_id = _owned_session()
        headers = _sync_auth(client)
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": session_id},
        )
        approval_id = pending.json()["hitl_action_id"]

        ivi_token = headers["Authorization"].removeprefix("Bearer ")
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(ivi_token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )

            decision = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={**(headers), **_idem()},
                json={"decision": "reject", "approved_vehicle_state_version": 1},
            )
            assert decision.json()["approval_status"] == "rejected"

            events = receive_n(ws, 2)

    types = [event["type"] for event in events]
    assert types == ["assistant.response", "turn.canceled"]
    assert events[1]["payload"]["reason"] == "approval_rejected"


def test_reject_schedules_tts_via_background_task_not_inline(monkeypatch):
    """Nhánh reject không được `await synthesize_speech(...)` ngay trong handler.

    `synthesize_speech` chạy `asyncio.to_thread(voice.synthesize_wav, ...)` nhưng
    không có timeout — awaiting nó trực tiếp trong `decide()` nghĩa là một lần Piper
    chậm/treo kéo chậm theo chính thao tác từ chối approval. Nhánh approve ngay dưới
    đã đi qua `background_tasks.add_task(_resume_and_publish, ...)`; nhánh reject
    phải đối xứng, qua `_reject_and_publish`.

    Giới hạn của test này: `TestClient` chạy trọn app() — kể cả background task —
    trong cùng một lời gọi trước khi trả `Response` về test, nên không đo được chênh
    lệch thời gian thật giữa "đợi TTS" và "không đợi" ở tầng transport này (chỉ một
    server ASGI thật qua socket, ví dụ uvicorn, mới trả byte cho client trước khi
    chạy background task). Test này khẳng định đúng điều **có thể** khẳng định ở
    tầng này: TTS được lên lịch qua `BackgroundTasks.add_task`, không phải `await`
    trực tiếp trong thân `decide()` — tức tách khỏi đường tính response, đúng bất
    biến mà nhánh approve đã có.
    """
    monkeypatch.setattr(voice, "synthesize_wav", lambda text: b"FAKE-WAV-BYTES")

    from fastapi import BackgroundTasks

    scheduled: list = []
    original_add_task = BackgroundTasks.add_task

    def _spy_add_task(self, func, *args, **kwargs):
        scheduled.append(func)
        return original_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", _spy_add_task)

    with TestClient(app) as client:
        session_id = _owned_session()
        headers = _sync_auth(client)
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": session_id},
        )
        approval_id = pending.json()["hitl_action_id"]

        decision = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**(headers), **_idem()},
            json={"decision": "reject", "approved_vehicle_state_version": 1},
        )

    assert decision.status_code == 200
    assert decision.json()["approval_status"] == "rejected"
    from src.api.approvals import _reject_and_publish

    assert _reject_and_publish in scheduled, scheduled


def test_replaying_an_already_consumed_approval_publishes_nothing_new():
    with TestClient(app) as client:
        session_id = _owned_session()
        # Đăng nhập TRƯỚC khi mở WS: `TestClient` chạy WS trên một portal riêng, gọi
        # HTTP bên trong khối `websocket_connect` sẽ khoá lẫn nhau.
        headers = _sync_auth(client)
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": session_id},
        )
        approval_id = pending.json()["hitl_action_id"]

        client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**(headers), **_idem()},
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )

        ivi_token = headers["Authorization"].removeprefix("Bearer ")
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(ivi_token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )

            # Lần quyết định thứ hai trên một approval đã `consumed` — không tạo sự
            # kiện mới nào. Gửi một publish "canary" ngay sau để chứng minh listener
            # vẫn sống và không có gì đến trước nó.
            second = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers={**(headers), **_idem()},
                json={"decision": "approve", "approved_vehicle_state_version": 1},
            )
            assert second.json()["approval_status"] == "consumed"

            async def canary():
                await get_event_bus().publish(session_id, "error", "turn-canary", "tr-canary", {"code": "CANARY"})

            anyio.run(canary)
            # Bỏ qua `ui.policy` phát lúc kết nối: ý đồ của canary là "không có event
            # NÀO CỦA LƯỢT chen vào giữa", còn policy thuộc session chứ không thuộc lượt.
            event = ws.receive_json()
            while event["type"] == "ui.policy":
                event = ws.receive_json()

    assert event["payload"]["code"] == "CANARY"


async def test_decision_body_carries_no_execution_result(client):
    """Quyết định là đồng bộ; **thực thi** thì không (api_spec.md:209).

    Body chỉ được nói "đã ghi nhận quyết định". Trả kèm `tool_results` buộc route phải
    chạy xong plan trước khi hồi đáp, tức tài xế bấm Đồng ý rồi ngồi chờ cả chuỗi lệnh
    xe chạy xong mới thấy màn hình phản hồi. Mọi kết quả đi qua `/ws/ivi`, đúng thứ
    `decideApproval(): Promise<void>` bên FE đang giả định.
    """
    approval_id = await _pending(client, _owned_session())
    body = (
        await client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**(await _auth(client)), **_idem()},
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )
    ).json()

    assert set(body) == {"approval_status"}


async def test_a_crash_while_resuming_still_ends_the_turn(client, monkeypatch):
    """Bất biến #1: **đúng một** sự kiện terminal mỗi lượt — không bao giờ không có.

    Từ khi thực thi dời sang task nền, một exception lúc resume không còn nổi lên thành
    HTTP 500 nữa mà biến mất trong nền. Không có terminal event thì màn hình tài xế treo
    ở `waiting_approval` vĩnh viễn, và họ không có cách nào biết lệnh đã hỏng.

    `turns.py::_process_voice_turn` đã bảo vệ đúng bất biến này; đường approval phải
    giống hệt.
    """
    session_id = _owned_session()
    approval_id = await _pending(client, session_id)

    class _ExplodingGraph:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("checkpoint biến mất")

    monkeypatch.setattr("src.api.approvals.get_graph", lambda _session_id: _ExplodingGraph())

    events: list[dict] = []

    async def listener(event):
        events.append(event)

    get_event_bus().add_listener(session_id, listener)
    try:
        response = await client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**(await _auth(client)), **_idem()},
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )
    finally:
        get_event_bus().remove_listener(session_id, listener)

    assert response.status_code == 200
    terminal = [event["type"] for event in events if event["type"].startswith("turn.")]
    assert terminal == ["turn.failed"]


async def test_a_second_decision_before_execution_finishes_schedules_nothing(client, monkeypatch):
    """Bấm Đồng ý hai lần không được xếp hai lượt thực thi.

    Từ khi thực thi chạy nền, route trả `200` ngay nên client rảnh tay gửi tiếp — một
    cú double-click là đủ. `ApprovalStore.decide()` gọi lại trên bản ghi đã `approved`
    **trả nguyên trạng thái `approved`** (đúng thiết kế idempotent của nó), nên nhánh
    `!= "approved"` không chặn được lần hai.

    Lệnh không chạy hai lần — node đọc lại store và thấy `consumed` nên fail-closed.
    Nhưng lượt sẽ nhận **hai sự kiện terminal**: `turn.completed` từ task đầu rồi
    `turn.canceled(approval_rejected)` từ task sau. Đó là vi phạm bất biến số 1, và
    trên màn hình tài xế là một thông báo huỷ hiện ngay sau khi lệnh vừa báo thành công.
    """
    approval_id = await _pending(client, _owned_session())
    scheduled: list[str] = []

    async def _spy(approval_id_arg, _session_id, _turn_id):
        scheduled.append(approval_id_arg)

    monkeypatch.setattr("src.api.approvals._resume_and_publish", _spy)

    headers = await _auth(client)
    payload = {"decision": "approve", "approved_vehicle_state_version": 1}
    await client.post(f"/api/v1/approvals/{approval_id}/decision", headers={**headers, **_idem()}, json=payload)
    await client.post(f"/api/v1/approvals/{approval_id}/decision", headers={**headers, **_idem()}, json=payload)

    assert scheduled == [approval_id]

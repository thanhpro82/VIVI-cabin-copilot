"""POST /api/v1/turns/text — S1 completed path. Xem docs/api_spec.md mục "Text
turn and canonical ActionPlan" và
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md.

S2/waiting_approval path và idempotent-replay-no-side-effect tests đầy đủ nằm ở
test_turns_text_s2.py (Task 9) — file này chỉ phủ nhánh S1/completed cộng các
kiểm tra request-context/ownership dùng chung cho cả hai nhánh.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api import session_state
from src.main import app
from src.services import voice
from tests.conftest import seed_test_user
from tests.test_api.ws_helpers import ivi_connect_kwargs, receive_n

_AUTH_HEADERS = {"X-Schema-Version": "1.0"}


@pytest.fixture(autouse=True)
def _stub_tts_unavailable(monkeypatch):
    """TTS luôn thất bại mặc định trong file này — không phụ thuộc việc máy chạy test
    có sẵn model Piper thật hay không (issue #66). Test nào cần audio thành công tự
    override bằng monkeypatch.setattr(voice, "synthesize_wav", ...) riêng trong thân test."""

    def _raise(text):
        raise FileNotFoundError("no TTS model in test environment")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)


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


def test_s1_text_command_returns_completed_with_the_canonical_action_plan_and_runs_ws_lifecycle():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:s1:001")

        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))

            response = client.post(
                "/api/v1/turns/text",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Schema-Version": "1.0",
                    "Idempotency-Key": "turn:s1:001",
                },
                json={"session_id": session_id, "text": "Đặt điều hòa 22 độ"},
            )
            assert response.status_code == 200
            body = response.json()["data"]
            assert body["status"] == "completed"
            assert body["session_id"] == session_id
            plan = body["action_plan"]
            assert plan["requires_approval"] is False
            assert plan["steps"][0]["tool"] == "set_hvac_temperature"
            assert set(plan.keys()) == {
                "schema_version",
                "plan_id",
                "session_id",
                "vehicle_id",
                "vehicle_state_version",
                "steps",
                "requires_approval",
            }
            assert body["response"]["outcomes"][0]["status"] == "completed"
            turn_id = body["turn_id"]

            events = receive_n(ws, 6)

    types = [event["type"] for event in events]
    # `turn.accepted` mở đầu lượt gõ chữ từ #307. Trước đó chỉ `/turns/voice` phát nó,
    # nên client không có cách nào biết `turn_id` của một lượt text trước khi lượt ấy
    # xong — route này đồng bộ, và `emit_turn_lifecycle` chạy trước khi envelope trả về.
    #
    # `plan.ready` thuộc giai đoạn định tuyến (api_spec.md:620), phát trước khi rẽ
    # nhánh chính sách — nên nó có ở **mọi** lượt điều khiển, kể cả S1 không cần duyệt.
    assert types == [
        "turn.accepted",
        "plan.ready",
        "assistant.status",
        "tool.result",
        "assistant.response",
        "turn.completed",
    ]
    assert events[0]["payload"]["input_mode"] == "text"
    assert all(event["turn_id"] == turn_id for event in events)
    assert all(event["session_id"] == session_id for event in events)


def test_text_routine_preview_tra_cau_truc_o_data():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:routine-preview:001")

        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:routine-preview:001",
            },
            json={"session_id": session_id, "text": "Xem trước Routine Về nhà"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["routine_preview"] == {
        "routine_id": "rtn_usr_driver_01_ve_nha",
        "routine_name": "Về nhà",
        "steps": [
            {"index": 0, "action": "navigation", "description": "dẫn đường tới Nhà"},
            {"index": 1, "action": "hvac_power", "description": "bật điều hòa"},
            {"index": 2, "action": "hvac_temperature", "description": "đặt điều hòa ở 26 độ"},
        ],
    }
    assert data["status"] == "completed"
    assert data["action_plan"] is None


def test_text_over_1000_code_points_returns_422_input_invalid():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:toolong:001")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:toolong:001",
            },
            json={"session_id": session_id, "text": "a" * 1001},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"


def test_text_that_is_only_whitespace_returns_422_input_invalid():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:blank:001")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:blank:001",
            },
            json={"session_id": session_id, "text": "   "},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INPUT_INVALID"


def test_nonexistent_session_returns_403_forbidden_not_404():
    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:missing:001",
            },
            json={"session_id": "ses_does_not_exist", "text": "Bật điều hòa"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_cross_owner_session_returns_403_forbidden_not_404():
    """Nhánh 'session tồn tại nhưng thuộc người khác' của cùng if — trước fix
    này chỉ nhánh 'session không tồn tại' ở trên có test."""
    with TestClient(app) as client:
        token = _login(client)
        other_session = session_state.create_session(seed_test_user("usr_someone_else"), "vehicle-demo-01")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:crossowner:001",
            },
            json={"session_id": other_session.session_id, "text": "Bật điều hòa"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_malformed_body_returns_envelope_shaped_422_without_leaking_input():
    """Body thiếu `text` — kiểm chứng RequestValidationError handler áp dụng
    cho /turns/text như các route còn lại."""
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:malformed:001")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:malformed:001",
            },
            json={"session_id": session_id},
        )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INPUT_INVALID"
    assert body["trace_id"]
    assert body["schema_version"] == "1.0"
    errors = body["error"]["details"]["errors"]
    assert all("input" not in error for error in errors)


def test_engineer_role_cannot_submit_a_text_turn():
    with TestClient(app) as client:
        token = _login(client, email="engineer.demo@example.com", password="DemoEngineer123!")
        response = client.post(
            "/api/v1/turns/text",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "1.0",
                "Idempotency-Key": "turn:eng:001",
            },
            json={"session_id": "ses_irrelevant", "text": "Bật điều hòa"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_missing_idempotency_key_returns_400():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:noik:001")
        response = client.post(
            "/api/v1/turns/text",
            headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"},
            json={"session_id": session_id, "text": "Bật điều hòa"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


def test_replaying_the_same_idempotency_key_does_not_rerun_the_turn_or_emit_new_ws_events():
    import anyio

    def _assert_no_further_event(ws, timeout: float = 0.3) -> None:
        async def _try_receive():
            with anyio.fail_after(timeout):
                return await ws._send_rx.receive()  # noqa: SLF001 - test helper, same technique as ws_helpers.receive_n

        try:
            message = ws.portal.call(_try_receive)
        except TimeoutError:
            return
        raise AssertionError(f"expected no further WS event on replay, got: {message}")

    with TestClient(app) as client:
        token = _login(client)
        session_id = _create_session(client, token, "session:replay:001")
        graph = session_state.get_graph(session_id)
        call_count = 0
        original_ainvoke = graph.ainvoke

        async def _counting_ainvoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await original_ainvoke(*args, **kwargs)

        graph.ainvoke = _counting_ainvoke

        headers = {
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "turn:replay:001",
        }
        payload = {"session_id": session_id, "text": "Đặt điều hòa 22 độ"}

        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))
            first = client.post("/api/v1/turns/text", headers=headers, json=payload)
            receive_n(ws, 6)  # turn.accepted + plan.ready + 4 sự kiện còn lại

            second = client.post("/api/v1/turns/text", headers=headers, json=payload)
            _assert_no_further_event(ws)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert call_count == 1


async def test_two_concurrent_requests_with_the_same_idempotency_key_do_not_both_run_the_turn(client):
    """Tái hiện race condition đã sửa ở src/services/idempotency.py: `lookup` rồi
    `save` rời rạc từng để hai request cùng key gửi gần như đồng thời đều thấy
    "chưa có" và đều gọi `graph.ainvoke` — tức chạy trùng lệnh xe thật. Dùng
    `asyncio.gather` để hai request thực sự chạy đồng thời (không phải tuần tự như
    các test replay khác trong file này), rồi khẳng định agent chỉ chạy đúng một
    lần và đúng một trong hai response là 200.
    """
    login = await client.post(
        "/api/v1/auth/login",
        headers=_AUTH_HEADERS,
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    token = login.json()["data"]["access_token"]

    session_resp = await client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": "session:race:001"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    session_id = session_resp.json()["data"]["session_id"]

    graph = session_state.get_graph(session_id)
    call_count = 0
    original_ainvoke = graph.ainvoke

    async def _counting_ainvoke(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Nhường quyền điều khiển cho event loop trước khi tính xong, để hai
        # coroutine gọi đồng thời thực sự có cơ hội xen kẽ nếu lock không chặn.
        await asyncio.sleep(0)
        return await original_ainvoke(*args, **kwargs)

    graph.ainvoke = _counting_ainvoke

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Schema-Version": "1.0",
        "Idempotency-Key": "turn:race:001",
    }
    payload = {"session_id": session_id, "text": "Đặt điều hòa 22 độ"}

    responses = await asyncio.gather(
        client.post("/api/v1/turns/text", headers=headers, json=payload),
        client.post("/api/v1/turns/text", headers=headers, json=payload),
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200, 409], f"expected exactly one 200 and one 409, got {statuses}"
    conflict = next(r for r in responses if r.status_code == 409)
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict.json()["error"]["retryable"] is True
    assert call_count == 1, f"expected graph.ainvoke to run exactly once, ran {call_count} times"


async def test_cancellation_during_ainvoke_still_releases_the_idempotency_reservation():
    """`asyncio.CancelledError` không kế thừa `Exception` — một `except Exception`
    quanh `await graph.ainvoke(...)` sẽ bỏ lọt việc client hủy kết nối/timeout đúng
    lúc đó, để lại một reservation kẹt vĩnh viễn trong idempotency store (xem
    src/services/idempotency.py mục `_PENDING_TTL_SECONDS`). Gọi thẳng coroutine
    của route (không qua HTTP) để kiểm soát chính xác thời điểm hủy, độc lập với
    cách httpx/ASGI transport truyền cancellation qua ranh giới HTTP.
    """
    from src.api import auth_deps, turns
    from src.services import auth as auth_service

    driver = auth_service.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    user = auth_deps.AuthenticatedUser(user_id=driver.user_id, role=driver.role, display_name=driver.display_name)
    session_record = session_state.create_session(user.user_id, "vehicle-demo-01")

    graph = session_state.get_graph(session_record.session_id)
    original_ainvoke = graph.ainvoke
    started = asyncio.Event()

    async def _hanging_ainvoke(*args, **kwargs):
        started.set()
        await asyncio.sleep(10)  # sẽ không bao giờ hoàn tất trong phạm vi test

    graph.ainvoke = _hanging_ainvoke

    request = Request({"type": "http", "headers": []})
    body = turns.TextTurnRequest(session_id=session_record.session_id, text="Đặt điều hòa 22 độ")

    task = asyncio.ensure_future(turns.submit_text_turn(request, body, user=user, idempotency_key="turn:cancel:001"))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    graph.ainvoke = original_ainvoke
    # Sau khi bị hủy, reservation phải được nhả ngay (không cần chờ TTL) — request
    # thứ hai cùng key phải chạy được, không kẹt ở IdempotencyInProgress.
    second = await turns.submit_text_turn(request, body, user=user, idempotency_key="turn:cancel:001")
    assert second.data.status == "completed"


class _BlindGateway:
    """Cổng không đọc được state — đúng hành vi `MqttVehicleGateway` khi broker chết.

    Cùng shape với `tests/test_agents/test_vehicle_state_unavailable.py::_BlindGateway`
    — bọc một cổng in-process thật để không nổ lỗi khác nếu graph lỡ chạy nhầm lệnh.
    """

    def __init__(self):
        from src.services.vehicle_gateway import InProcessVehicleGateway

        self._real = InProcessVehicleGateway.new()
        self.vehicle_id = self._real.vehicle_id

    async def snapshot(self):
        return None

    async def last_known(self):
        return None

    def readiness(self):
        return self._real.readiness()

    async def execute(self, **kwargs):
        return await self._real.execute(**kwargs)

    def add_listener(self, listener):
        self._real.add_listener(listener)

    def remove_listener(self, listener):
        self._real.remove_listener(listener)


async def test_vehicle_state_unavailable_returns_failed_not_completed(client):
    """`safety_node` trả outcome `vehicle_state_unavailable` khi `VehicleGateway`
    không đọc được state (broker chết) — nhánh WS tương ứng là
    `turn.failed(MQTT_UNAVAILABLE)` (`ivi_events.py`). REST phải đồng bộ: trước khi
    sửa, outcome này rơi vào nhánh mặc định và báo sai `status: "completed"`.
    """
    from src.services.vehicle_gateway import set_vehicle_gateway

    # Đặt cổng mù TRƯỚC khi graph của session được dựng — graph chỉ dựng một lần
    # và giữ nguyên tham chiếu gateway lúc đó (`normalize_node` đóng closure trên
    # gateway truyền vào `build_graph`), nên phải đặt trước request đầu tiên.
    set_vehicle_gateway(_BlindGateway())

    login = await client.post(
        "/api/v1/auth/login",
        headers=_AUTH_HEADERS,
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    token = login.json()["data"]["access_token"]

    session_resp = await client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Idempotency-Key": "session:blind:001"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    session_id = session_resp.json()["data"]["session_id"]

    response = await client.post(
        "/api/v1/turns/text",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "turn:blind:001",
        },
        json={"session_id": session_id, "text": "Đặt điều hòa 22 độ"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["action_plan"] is None

"""WS /ws/ivi — handshake, auth, và forwarding sự kiện lượt thoại từ IviEventBus."""

import base64
import functools

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.agents.contracts import ActionPlan, PlanStep
from src.api import session_state
from src.main import app
from src.services.ivi_events import get_event_bus
from tests.conftest import seed_test_user
from tests.test_api.ws_helpers import drain_ui_policy, receive_n

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_ORIGIN_HEADERS = {"origin": "http://localhost:3000"}


def _login(client, email: str = "driver.demo@example.com", password: str = "DemoDriver123!") -> str:
    response = client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json={"email": email, "password": password})
    return response.json()["data"]["access_token"]


def _bearer_subprotocol(token: str) -> str:
    """Ngược của `frontend/src/lib/services/shared/ws.ts`'s `toBase64Url()`."""
    encoded = base64.urlsafe_b64encode(token.encode("utf-8")).rstrip(b"=").decode("ascii")
    return f"bearer.{encoded}"


def _owned_session(user_id: str = "usr_driver_01") -> str:
    """Phiên có `SessionRecord` thật, do `user_id` sở hữu.

    Seed user trước khi tạo phiên: `sessions.user_id` là FOREIGN KEY từ PR #89, nên
    dựng phiên cho một chủ nhân không tồn tại sẽ `IntegrityError`. Trước bản sửa này,
    các test dùng `usr_driver_99` chỉ xanh **nhờ file khác tình cờ seed trước** — chạy
    riêng một file là đỏ. Phụ thuộc thứ tự kiểu đó tệ hơn một test đỏ thẳng, vì nó chỉ
    lộ ra khi ai đó chạy đúng một file để gỡ lỗi.
    """
    seed_test_user(user_id)
    return session_state.create_session(user_id, "vehicle-demo-01").session_id


def _connect_kwargs(token: str) -> dict:
    # `headers` phải là dict MỚI mỗi lần: `TestClient.websocket_connect()` mutate nó bằng
    # `setdefault(...)` (thêm `sec-websocket-protocol`, `connection`, ...) — dùng chung
    # một object giữa nhiều lần gọi sẽ khiến subprotocol của lần gọi trước bị kẹt lại
    # (setdefault không ghi đè key đã có), và bearer token của lần gọi sau không bao giờ
    # được gửi.
    return {"subprotocols": ["vivi.v1", _bearer_subprotocol(token)], "headers": dict(_ORIGIN_HEADERS)}


def _recv(ws) -> dict:
    """Đọc event kế tiếp, **bỏ qua** `ui.policy`.

    Mọi kết nối `/ws/ivi` nhận một `ui.policy` sau handshake (thiếu nó thì tài xế nối
    máy giữa lúc xe đang chạy sẽ render giao diện không hạn chế cho tới lần xe đổi
    trạng thái kế tiếp — xem `UiPolicyEmitter`). Các test dưới đây khoá thứ tự event
    **của lượt**, nên policy chỉ là nhiễu với ý đồ của chúng.

    Bản thân việc phát policy lúc kết nối được khoá riêng ở
    `test_ui_policy_phat_ngay_khi_ket_noi`, chứ không dựa vào các test này.

    **Có deadline.** Bản trước là `while True: ws.receive_json()` trần, mà
    `WebSocketTestSession.receive_json()` chặn vô hạn trong `portal.call(...)`. Thiếu
    một event thì nó không đỏ — nó **treo cả suite**. Chuyện đã xảy ra thật hai lần
    trên CI ngày 16/08: job bị timeout cắt sau 15 phút, log im lặng gần 12 phút, và
    trạng thái `cancelled` không nói gì về việc một test đang đứng. Phải đọc dấu thời
    gian trong log mới thấy khoảng lặng.

    `receive_n` đã có sẵn `anyio.fail_after` và cùng ngữ nghĩa bỏ qua `ui.policy`, nên
    dùng lại nó thay vì dựng đường đọc thứ hai. CLAUDE.md đã ghi thành luật:
    *"Every websocket read in a test needs a deadline."*
    """
    return receive_n(ws, 1)[0]


def _plan_for_ws_test(session_id: str):
    return ActionPlan(
        schema_version="1.0",
        plan_id="plan-reconnect-1",
        session_id=session_id,
        vehicle_id="veh-demo",
        vehicle_state_version=1,
        steps=[
            PlanStep(
                step_id="step-1",
                ordinal=1,
                tool="set_window_position",
                args={"window": "front_left", "percent": 0},
                safety_level="S2",
                depends_on=[],
            )
        ],
        requires_approval=True,
    )


class _FakeInterrupt:
    def __init__(self, value):
        self.value = value


# -- Auth: token, role, Origin, ownership -----------------------------------


def test_connection_without_a_bearer_subprotocol_is_rejected():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi", subprotocols=["vivi.v1"], headers=dict(_ORIGIN_HEADERS)) as ws:
            event = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "AUTH_REQUIRED"
    assert exc_info.value.code == 4401


def test_connection_with_an_unknown_token_is_rejected():
    with TestClient(app) as client:
        kwargs = {"subprotocols": ["vivi.v1", "bearer.bm90LWEtcmVhbC10b2tlbg"], "headers": dict(_ORIGIN_HEADERS)}
        with client.websocket_connect("/ws/ivi", **kwargs) as ws:
            event = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert event["payload"]["code"] == "AUTH_REQUIRED"
    assert exc_info.value.code == 4401


def test_connection_with_an_engineer_token_is_rejected():
    """`/ws/ivi` là kênh Driver — role `engineer` không được phép, dù token hợp lệ."""
    with TestClient(app) as client:
        token = _login(client, email="engineer.demo@example.com", password="DemoEngineer123!")
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            event = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert event["payload"]["code"] == "FORBIDDEN"
    assert exc_info.value.code == 4403


def test_connection_from_a_disallowed_origin_is_rejected():
    with TestClient(app) as client:
        token = _login(client)
        kwargs = {"subprotocols": ["vivi.v1", _bearer_subprotocol(token)], "headers": {"origin": "http://evil.example"}}
        with client.websocket_connect("/ws/ivi", **kwargs) as ws:
            event = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert event["payload"]["code"] == "FORBIDDEN"
    assert exc_info.value.code == 4403


def test_connection_to_another_users_session_is_rejected():
    with TestClient(app) as client:
        token = _login(client)  # usr_driver_01
        other_session = _owned_session("usr_driver_99")
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-11T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": other_session,
                }
            )
            event = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "FORBIDDEN"
    assert exc_info.value.code == 4403


def test_connection_to_an_unknown_session_is_rejected():
    with TestClient(app) as client:
        token = _login(client)
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-11T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-khong-ton-tai",
                }
            )
            event = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert event["payload"]["code"] == "FORBIDDEN"
    assert exc_info.value.code == 4403


# -- Handshake / forwarding, giờ đi qua auth thật ----------------------------


def test_rejects_first_message_that_is_not_connection_init():
    with TestClient(app) as client:
        token = _login(client)
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json({"type": "khong_hop_le"})
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "WS_EVENT_INVALID"


def test_rejects_connection_init_without_session_id():
    with TestClient(app) as client:
        token = _login(client)
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "WS_EVENT_INVALID"


def test_forwards_published_events_for_the_connected_session():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            policy = receive_n(ws, 1, timeout=5.0, skip_ui_policy=False)[0]
            assert policy["type"] == "ui.policy"

            async def do_publish():
                await get_event_bus().publish(
                    session_id,
                    "turn.accepted",
                    "turn-1",
                    "tr-1",
                    {"status": "accepted", "input_mode": "voice"},
                )

            # `TestClient` chạy app trên loop nền riêng; publish trực tiếp từ test
            # (loop khác) qua `anyio.run` là an toàn vì `IviEventBus` không giữ state
            # gắn với loop cụ thể — nó chỉ gọi callback đã đăng ký.
            anyio.run(do_publish)

            event = _recv(ws)

    assert event["type"] == "turn.accepted"
    assert event["session_id"] == session_id
    assert event["turn_id"] == "turn-1"
    assert set(event) >= {"type", "event_id", "sequence", "trace_id", "emitted_at", "schema_version", "payload"}
    # `ui.policy` phát lúc kết nối chiếm số thứ tự 1 của session; event đầu tiên của
    # lượt vì thế là 2. Xem `_recv` và `UiPolicyEmitter`.
    assert event["sequence"] == 2
    assert event["payload"] == {"status": "accepted", "input_mode": "voice"}


def test_events_for_other_sessions_are_not_delivered():
    with TestClient(app) as client:
        token = _login(client)
        session_a = _owned_session()
        session_b = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_a,
                }
            )
            policy = receive_n(ws, 1, timeout=5.0, skip_ui_policy=False)[0]
            assert policy["type"] == "ui.policy"

            async def do_publish():
                await get_event_bus().publish(session_b, "turn.accepted", "turn-1", "tr-1", {})
                await get_event_bus().publish(
                    session_a, "turn.accepted", "turn-2", "tr-2", {"status": "accepted", "input_mode": "voice"}
                )

            anyio.run(do_publish)

            event = _recv(ws)

    # Sự kiện đầu tiên nhận được phải là của `session_a` (turn-2) — sự kiện của
    # `session_b` không bao giờ tới, không phải "tới sau".
    assert event["turn_id"] == "turn-2"


def test_rejects_connection_init_with_only_one_cursor_field_present():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                    "last_event_id": "evt_only_one_field",
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "REPLAY_CURSOR_INVALID"


def test_cursor_pointing_to_a_never_issued_sequence_is_rejected():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                    "last_event_id": "evt_never_happened",
                    "last_sequence": 999,
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "REPLAY_CURSOR_INVALID"


def test_cursor_that_has_aged_out_of_the_ring_buffer_returns_window_expired():
    from src.services.ivi_events import RING_BUFFER_SIZE

    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()

        async def do_publish_many():
            bus = get_event_bus()
            for i in range(RING_BUFFER_SIZE + 5):
                await bus.publish(session_id, "assistant.status", f"turn-{i}", "tr-1", {"i": i})

        anyio.run(do_publish_many)

        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                    "last_event_id": "evt_does_not_matter",
                    "last_sequence": 1,
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "REPLAY_WINDOW_EXPIRED"


def test_reconnect_without_cursor_does_not_replay_anything():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()

        async def do_publish_first():
            await get_event_bus().publish(session_id, "turn.accepted", "turn-1", "tr-1", {})

        anyio.run(do_publish_first)

        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            drain_ui_policy(ws)

            async def do_publish_live():
                await get_event_bus().publish(session_id, "assistant.status", "turn-1", "tr-1", {"state": "routing"})

            anyio.run(do_publish_live)
            event = _recv(ws)

    # Không có cursor -> không replay `turn.accepted` (sequence 1); chỉ event live sau khi nối.
    assert event["type"] == "assistant.status"
    # sequence 3, không phải 2: `ui.policy` phát lúc kết nối chiếm một số thứ tự của
    # session. Đây là hành vi đúng — nó là event thật của stream, không phải phụ trợ
    # ngoài luồng, nên nó phải vào ring buffer và replay được như mọi event khác.
    assert event["sequence"] == 3


def test_replay_delivers_missed_events_after_reconnect_with_a_valid_cursor():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws1:
            ws1.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            drain_ui_policy(ws1)

            async def do_publish_first():
                await get_event_bus().publish(session_id, "plan.ready", "turn-1", "tr-1", {"route_kind": "action"})

            anyio.run(do_publish_first)
            first_event = _recv(ws1)

        async def do_publish_while_disconnected():
            bus = get_event_bus()
            await bus.publish(
                session_id,
                "approval.required",
                "turn-1",
                "tr-1",
                {
                    "approval_id": "appr-1",
                    "plan_id": "plan-1",
                    "approved_vehicle_state_version": 1,
                    "actions": [],
                    "expires_at": "2026-08-10T00:01:00Z",
                },
            )
            await bus.publish(session_id, "assistant.status", "turn-1", "tr-1", {"state": "waiting_approval"})

        anyio.run(do_publish_while_disconnected)

        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws2:
            ws2.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_2",
                    "sent_at": "2026-08-10T00:00:05Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                    "last_event_id": first_event["event_id"],
                    "last_sequence": first_event["sequence"],
                }
            )
            replayed_1 = _recv(ws2)
            replayed_2 = _recv(ws2)

    # `ui.policy` phát lúc kết nối **chiếm một số thứ tự** của session — nó là event
    # thật của stream (có `event_id`/`sequence`, vào ring buffer, replay được) chứ
    # không phải phụ trợ ngoài luồng. Mỗi lần nối máy vì thế đẩy sequence lên một.
    assert first_event["sequence"] == 2
    assert [replayed_1["type"], replayed_2["type"]] == ["approval.required", "assistant.status"]
    assert [replayed_1["sequence"], replayed_2["sequence"]] == [3, 4]
    assert replayed_1["payload"]["approval_id"] == "appr-1"
    assert replayed_2["payload"]["state"] == "waiting_approval"


def test_live_event_continues_in_order_right_after_replay_with_no_duplicates():
    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws1:
            ws1.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            drain_ui_policy(ws1)

            async def do_publish_first():
                await get_event_bus().publish(session_id, "turn.accepted", "turn-1", "tr-1", {})

            anyio.run(do_publish_first)
            first_event = _recv(ws1)

        async def do_publish_missed():
            await get_event_bus().publish(session_id, "assistant.status", "turn-1", "tr-1", {"state": "routing"})

        anyio.run(do_publish_missed)

        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws2:
            ws2.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_2",
                    "sent_at": "2026-08-10T00:00:05Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                    "last_event_id": first_event["event_id"],
                    "last_sequence": first_event["sequence"],
                }
            )
            replayed = _recv(ws2)

            async def do_publish_live():
                await get_event_bus().publish(
                    session_id, "assistant.response", "turn-1", "tr-1", {"display_text": "ok"}
                )

            anyio.run(do_publish_live)
            live = _recv(ws2)

    assert replayed["type"] == "assistant.status"
    # `ui.policy` phát lúc kết nối **chiếm một số thứ tự** của session — nó là event
    # thật của stream (có `event_id`/`sequence`, vào ring buffer, replay được) chứ
    # không phải phụ trợ ngoài luồng. Mỗi lần nối máy vì thế đẩy sequence lên một.
    assert replayed["sequence"] == 3
    assert live["type"] == "assistant.response"
    assert live["sequence"] == 5
    assert replayed["event_id"] != live["event_id"]


def test_events_that_arrive_while_replay_batch_is_still_sending_stay_in_order():
    """Regression test for the `pending_live` flush-ordering bug (review round 1):
    `replay_done` must not flip to `True` until `pending_live` is actually drained, or a
    live event delivered concurrently with the flush loop can jump ahead of an
    already-buffered-but-not-yet-sent `pending_live` item.

    This spawns a real background thread that publishes "live" events concurrently with
    the main thread reading the reconnect replay batch off the websocket, to give the
    interleaving in the finding's trace (send -> await suspends -> live event slips in ->
    resume) a real chance to occur. Exact interleaving across the TestClient portal loop
    and this thread's own `anyio.run` loop cannot be pinned deterministically from the
    test side, so the assertion is on the *outcome* the fix guarantees regardless of
    timing: every event received on the reconnected socket must have sequence numbers
    that are strictly increasing, gapless, and non-repeating from the cursor position
    through the last live-published sequence — any reordering (e.g. replay/pending item
    skipped ahead of by a live item) would produce a gap or an out-of-order value here.
    """
    import threading

    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws1:
            ws1.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            drain_ui_policy(ws1)

            async def do_publish_first():
                await get_event_bus().publish(session_id, "turn.accepted", "turn-1", "tr-1", {})

            anyio.run(do_publish_first)
            first_event = ws1.receive_json()

        async def do_publish_replay_batch():
            bus = get_event_bus()
            for i in range(8):
                await bus.publish(session_id, "assistant.status", f"turn-{i}", "tr-1", {"i": i})

        anyio.run(do_publish_replay_batch)

        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws2:
            ws2.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_2",
                    "sent_at": "2026-08-10T00:00:05Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                    "last_event_id": first_event["event_id"],
                    "last_sequence": first_event["sequence"],
                }
            )

            def publish_live_events():
                """Publish từ thread khác, nhưng đi VÀO loop của app qua portal.

                Không dùng `anyio.run(...)` ở đây: nó tạo một event loop MỚI, trong khi
                websocket của TestClient sống trên portal loop. `bus.publish()` await
                thẳng vào `push()` -> `websocket.send_json()`, nên gọi từ loop khác sẽ
                đánh thức receiver đang chờ trên portal loop qua anyio memory stream
                xuyên loop — wakeup mất, và `ws2.receive_json()` (không có timeout) treo
                vĩnh viễn. Các test khác trong file này dùng `anyio.run` được là vì chúng
                publish xong RỒI mới đọc, message đã nằm sẵn trong buffer nên không cần
                ai đánh thức. Ở đây thì có đọc song song, nên phải đi qua portal.
                `BlockingPortal.call` sinh ra để gọi từ thread khác đúng như vậy — và nó
                còn tái hiện đúng hơn kịch bản của bug gốc: live event giờ chen vào tại
                chính các điểm `await` của vòng flush `pending_live`, thay vì chạy trên
                một loop không bao giờ interleave đúng chỗ.
                """

                async def do_publish():
                    bus = get_event_bus()
                    for i in range(8, 11):
                        await bus.publish(session_id, "assistant.status", f"turn-{i}", "tr-1", {"i": i})

                ws2.portal.call(do_publish)

            publisher = threading.Thread(target=publish_live_events)
            publisher.start()

            # Đọc trong daemon thread có deadline thay vì
            # `[ws2.receive_json() for _ in range(11)]` thẳng: `receive_json()` là
            # `portal.call(...)` block không timeout, nên thiếu dù một event là treo cả
            # suite, không phải fail. `daemon=True` là bắt buộc — nếu vẫn thiếu, thread
            # còn kẹt trong portal sẽ không bị join lúc thoát, pytest báo fail rồi kết
            # thúc bình thường.
            # 8 replay + 1 `ui.policy` của reconnect + 3 live. Policy là event
            # thật trong stream và chiếm một sequence nên không được đếm thiếu.
            expected_count = 12
            received: list[dict] = []

            def drain():
                for _ in range(expected_count):
                    received.append(ws2.receive_json())

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            reader.join(timeout=10)
            publisher.join(timeout=5)

            assert not reader.is_alive(), (
                f"chỉ nhận được {len(received)}/{expected_count} event trong 10s; "
                f"sequences={[event['sequence'] for event in received]}"
            )

    sequences = [event["sequence"] for event in received]
    expected_first = first_event["sequence"] + 1
    assert sequences == list(range(expected_first, expected_first + expected_count))


def test_approval_required_survives_disconnect_and_replays_on_reconnect(monkeypatch):
    """AC ticket: `approval.required` không mất nếu rớt kết nối lúc đang chờ HITL.

    Kiểm **cursor/replay**, không kiểm tiếng nói — nên ghim TTS về "hỏng".

    Từ issue #215 nhánh chờ duyệt phát thêm `assistant.speech` best-effort, tức số event
    và số thứ tự phụ thuộc việc máy chạy test có model Piper hay không. Không ghim thì
    test này xanh trên CI (không có Piper) và đỏ trên máy dev — đỏ vì một lý do không
    liên quan gì tới thứ nó kiểm.
    """
    from src.services import voice

    def _khong_co_tts(text):
        raise FileNotFoundError("no TTS model in test environment")

    monkeypatch.setattr(voice, "synthesize_wav", _khong_co_tts)

    from src.services.ivi_events import emit_turn_lifecycle

    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()

        interrupt_result = {
            "__interrupt__": [
                _FakeInterrupt(
                    {
                        "kind": "vehicle_action_approval",
                        "approval_id": "appr-reconnect-1",
                        "plan_id": "plan-reconnect-1",
                        "prompt_text": "Tôi sẽ mở cửa sổ bên lái. Bạn có đồng ý không?",
                        "steps_summary": [{"tool": "set_window_position", "safety_level": "S2"}],
                        "expires_at": "2026-08-10T00:00:30Z",
                        "timeout_seconds": 30,
                    }
                )
            ],
            "action_plan": _plan_for_ws_test(session_id),
        }

        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws1:
            ws1.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            drain_ui_policy(ws1)

            async def do_publish():
                await emit_turn_lifecycle(get_event_bus(), session_id, "turn-1", "tr-1", interrupt_result)

            # Publish HITL events while connected — client receives and caches event_id/sequence
            anyio.run(do_publish)
            plan_ready = _recv(ws1)

        # Connection drops here (context exits). Client reconnects with the cursor.
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws2:
            ws2.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_2",
                    "sent_at": "2026-08-10T00:00:01Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                    "last_event_id": plan_ready["event_id"],
                    "last_sequence": plan_ready["sequence"],
                }
            )
            approval_required = _recv(ws2)
            waiting_status = _recv(ws2)

    assert plan_ready["type"] == "plan.ready"
    assert [approval_required["type"], waiting_status["type"]] == [
        "approval.required",
        "assistant.status",
    ]
    assert approval_required["payload"]["approval_id"] == "appr-reconnect-1"
    assert waiting_status["payload"]["state"] == "waiting_approval"
    # sequence lien tuc, khong lap, dung thu tu goc luc phat
    # `ui.policy` phát lúc kết nối **chiếm một số thứ tự** của session — nó là event
    # thật của stream (có `event_id`/`sequence`, vào ring buffer, replay được) chứ
    # không phải phụ trợ ngoài luồng. Mỗi lần nối máy vì thế đẩy sequence lên một.
    assert [plan_ready["sequence"], approval_required["sequence"], waiting_status["sequence"]] == [2, 3, 4]


def test_ui_policy_phat_ngay_khi_ket_noi():
    """Vế thứ hai của thiết kế: chỉ kích-theo-cạnh thôi thì thủng.

    Tài xế nối máy giữa lúc xe đang chạy mà không nhận policy nào cho tới lần xe đổi
    trạng thái kế tiếp thì FE render giao diện không hạn chế **trong khi xe chạy** —
    đúng lỗ hổng mà việc này sinh ra để bịt.
    """
    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-12T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            event = ws.receive_json()

    assert event["type"] == "ui.policy"
    assert event["turn_id"] is None, "ui.policy thuộc session, không thuộc lượt nào"
    assert event["sequence"] == 1
    assert set(event["payload"]) == {"active", "speed_kph", "ui_policy"}
    assert set(event["payload"]["ui_policy"]) == {
        "allow_text_input",
        "lock_small_controls",
        "enlarge_mic_button",
        "max_visible_actions",
        "prefer_voice_confirmation",
        "allow_detailed_document_browsing",
    }


def test_ui_policy_kich_theo_canh_khong_theo_tung_snapshot():
    """Bắn một event mỗi snapshot sẽ nhấn chìm ring buffer 200 event và phá replay
    của ADR-014. Xe ảo publish liên tục khi đang chạy, nên đây không phải lo xa."""
    from src.services.ivi_events import get_event_bus
    from src.services.ui_policy import UiPolicyEmitter

    bus = get_event_bus()
    bus.reset()

    async def scenario():
        await bus.publish("ses-canh", "turn.accepted", "turn-1", "tr-1", {})
        emitter = UiPolicyEmitter(bus)
        stationary = {"motion": {"speed_kph": 0, "gear": "P", "ignition": "on"}}
        moving = {"motion": {"speed_kph": 42, "gear": "D", "ignition": "on"}}
        return [
            await emitter.publish_if_changed(stationary),  # lần đầu -> có phát
            await emitter.publish_if_changed(stationary),  # policy y hệt -> im
            await emitter.publish_if_changed({"motion": {"speed_kph": 0, "gear": "P", "ignition": "off"}}),
            await emitter.publish_if_changed(moving),  # đổi chế độ -> phát
            await emitter.publish_if_changed({"motion": {"speed_kph": 43, "gear": "D", "ignition": "on"}}),
        ]

    published = anyio.run(scenario)

    # Chỉ hai lần phát: vào chế độ đứng yên, rồi chuyển sang đang chạy. Ba snapshot
    # còn lại không đổi policy — kể cả lần đổi tốc độ 42 -> 43, vì `speed_kph` chỉ là
    # thông tin kèm theo, không phải thứ FE dùng để quyết định.
    assert published == [True, False, False, True, False]


def test_ui_policy_kich_theo_canh_chay_that_qua_gateway_cua_lifespan():
    """Đường wiring **production**, không phải một emitter tự dựng trong test.

    Blocker Thành phát hiện ở PR #77: `main.py` gắn listener vào
    `get_vehicle_gateway()` lúc import, nhưng `lifespan()` sau đó gọi
    `set_vehicle_gateway(...)` để thay bằng gateway thật. `add_listener` gắn vào **một
    instance**, nên listener nằm lại trên object đã bị bỏ và vế kích-theo-cạnh im lặng
    chết ở runtime — trong khi mọi test cũ vẫn xanh, vì chúng đều tự dựng
    `UiPolicyEmitter` riêng và không đi qua đoạn wiring này.

    Test này cố ý **không** chạm `UiPolicyEmitter`: nó đổi trạng thái xe qua gateway mà
    `lifespan` đã đặt, rồi đòi WS client nhận `ui.policy` mới.
    """
    from src.services.vehicle_gateway import get_vehicle_gateway

    with TestClient(app) as client:  # `with` chạy lifespan → gateway production được đặt
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-12T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            # `receive_n` có `anyio.fail_after`; `ws.receive_json()` trần chặn vô hạn
            # nên một event thiếu sẽ treo cả suite thay vì báo đỏ (CLAUDE.md, luật WS #2).
            first = receive_n(ws, 1, timeout=5.0, skip_ui_policy=False)[0]
            assert first["type"] == "ui.policy"
            assert first["payload"]["active"] is False, "xe đứng yên lúc mở kết nối"

            # Cho xe chạy rồi chạy một lệnh thật: `execute()` là chỗ gateway in-process
            # thông báo cho listener (`set_motion` một mình chỉ đổi state, không notify).
            gateway = get_vehicle_gateway()
            gateway.set_motion(42.0, "D")
            ws.portal.call(
                functools.partial(
                    gateway.execute,
                    plan_id="plan-ui-policy",
                    step_id="step-1",
                    tool="set_hvac_temperature",
                    args={"temperature_c": 24},
                    expected_state_version=gateway.simulator.state.state_version,
                )
            )

            moving = receive_n(ws, 1, timeout=5.0, skip_ui_policy=False)[0]

    assert moving["type"] == "ui.policy", f"không nhận được ui.policy sau khi xe chạy: {moving['type']}"
    assert moving["payload"]["active"] is True
    assert moving["payload"]["ui_policy"]["allow_text_input"] is False
    assert moving["payload"]["ui_policy"]["lock_small_controls"] is True


def test_ui_policy_khong_phat_lai_ngay_sau_handshake_khi_policy_khong_doi():
    """Phát hiện khi chạy server thật trong PR #98, không phải từ đọc code.

    `ws.py` phát `ui.policy` ở handshake bằng `bus.publish` thẳng, không qua
    `UiPolicyEmitter`. Nếu không báo lại cho emitter thì `_last` của nó vẫn là `None`,
    nên **lần đổi trạng thái xe đầu tiên sau khi server lên** khiến emitter phát lần
    đầu — trùng đúng nội dung client vừa nhận vài giây trước.

    Ở đây xe chỉ đổi nhiệt độ điều hoà: `is_stationary()` không đổi nên policy **không
    đổi**, và client phải nhận đúng **một** `ui.policy` cho cả kết nối.
    """
    from src.services.vehicle_gateway import get_vehicle_gateway

    with TestClient(app) as client:
        token = _login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **_connect_kwargs(token)) as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-13T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
            first = receive_n(ws, 1, timeout=5.0, skip_ui_policy=False)[0]
            assert first["type"] == "ui.policy"

            gateway = get_vehicle_gateway()
            ws.portal.call(
                functools.partial(
                    gateway.execute,
                    plan_id="plan-no-policy-change",
                    step_id="step-1",
                    tool="set_hvac_temperature",
                    args={"temperature_c": 26},
                    expected_state_version=gateway.simulator.state.state_version,
                )
            )

            # Xe đổi state nhưng policy thì không, nên không được có event nào nữa.
            im_lang = []
            try:
                im_lang = receive_n(ws, 1, timeout=1.5, skip_ui_policy=False)
            except AssertionError:
                pass  # hết thời gian chờ mà không có event = đúng điều đang kiểm

    assert im_lang == [], f"policy không đổi mà vẫn phát lại: {im_lang}"

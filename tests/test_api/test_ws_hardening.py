"""Hai vá cứng cho tầng WebSocket — issue #45, mục B4 và B3.

**B4 — auth cho `/ws/engineer`:** trước ticket này nó mở bằng `await
websocket.accept()` trần, nên bất kỳ ai biết đường dẫn đều đọc được `trace` (số
liệu vận hành của mọi lượt), `metrics`, và `health` (readiness từng thành phần).
Nhóm test dưới đối xứng với nhóm "Auth" ở đầu `test_ws_ivi.py` và cố ý giữ nguyên
hình dạng đó: cả hai socket giờ đi qua **một** hàm `_authenticate_ws_connection`,
nên hai bộ test lệch nhau là dấu hiệu ai đó đã tách lại làm hai đường.

Ba điều kiện chứ không bốn: `api_spec.md:533` bỏ `session_id` khỏi
`connection.init` của kênh kỹ sư, nên không có session ownership để mà kiểm.

**B3 — `close()` hỏng lần hai không được thoát ra khỏi route:** áp cho `ivi_stream`,
xem test cuối file.

Vì sao hai thứ này ở chung một file mà không nằm trong `test_ws_ivi.py` /
`test_ws_engineer_events.py`: cả hai đều là hàng rào của issue #45, và để riêng thì
PR này không đụng vào file mà PR fix-deadlock đang sửa.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.main import app
from tests.test_api.ws_helpers import (
    ENGINEER_CREDENTIALS,
    bearer_subprotocol,
    login,
    login_engineer,
    receive_n,
    ws_connect_kwargs,
)

_ORIGIN_HEADERS = {"origin": "http://localhost:3000"}

HELLO = {
    "type": "connection.init",
    "client_message_id": "cmsg_1",
    "sent_at": "2026-08-11T00:00:00Z",
    "schema_version": "1.0",
}


# -- B4: bearer + role + Origin cho /ws/engineer ------------------------------


def _assert_rejected(ws, *, code: str, close_code: int) -> None:
    """Nhận sự kiện `error` rồi socket phải đóng bằng đúng mã của spec.

    Đọc lần hai là phần khẳng định thật: nếu server phát `error` mà quên đóng thì
    một client bị từ chối vẫn ngồi đó nghe, và `terminal: True` thành lời nói suông.
    """
    event = receive_n(ws, 1)[0]
    with pytest.raises(WebSocketDisconnect) as exc_info:
        ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == code
    assert event["payload"]["terminal"] is True
    assert exc_info.value.code == close_code


def test_connection_without_a_bearer_subprotocol_is_rejected():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/engineer", subprotocols=["vivi.v1"], headers=dict(_ORIGIN_HEADERS)) as ws:
            _assert_rejected(ws, code="AUTH_REQUIRED", close_code=4401)


def test_connection_with_an_unknown_token_is_rejected():
    with TestClient(app) as client:
        kwargs = {"subprotocols": ["vivi.v1", "bearer.bm90LWEtcmVhbC10b2tlbg"], "headers": dict(_ORIGIN_HEADERS)}
        with client.websocket_connect("/ws/engineer", **kwargs) as ws:
            _assert_rejected(ws, code="AUTH_REQUIRED", close_code=4401)


def test_connection_with_a_driver_token_is_rejected():
    """Chiều ngược của `test_connection_with_an_engineer_token_is_rejected` bên `/ws/ivi`.

    Token thật, chưa hết hạn, chỉ sai vai — phải là `4403`, không phải `4401`.
    Trộn hai mã này lại thì client sẽ đi refresh token cho một lỗi mà token mới
    không bao giờ sửa được.
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws/engineer", **ws_connect_kwargs(login(client))) as ws:
            _assert_rejected(ws, code="FORBIDDEN", close_code=4403)


def test_connection_from_a_disallowed_origin_is_rejected():
    with TestClient(app) as client:
        token = login_engineer(client)
        kwargs = {"subprotocols": ["vivi.v1", bearer_subprotocol(token)], "headers": {"origin": "http://evil.example"}}
        with client.websocket_connect("/ws/engineer", **kwargs) as ws:
            _assert_rejected(ws, code="FORBIDDEN", close_code=4403)


def test_connection_with_an_expired_token_is_rejected(monkeypatch):
    """Hết hạn phải giống hệt không có token: `AUTH_REQUIRED` + `4401`.

    `AuthStore.resolve()` tự xoá bản ghi quá hạn và trả `None`, nên đường này gộp
    vào cùng nhánh — test ở đây để khẳng định nó **thật sự** gộp, không phải trả
    một record đã chết.
    """
    from src.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_token_ttl_seconds", -1)
    with TestClient(app) as client:
        from src.services.auth import get_auth_store

        token = get_auth_store().login(*ENGINEER_CREDENTIALS).token
        with client.websocket_connect("/ws/engineer", **ws_connect_kwargs(token)) as ws:
            _assert_rejected(ws, code="AUTH_REQUIRED", close_code=4401)


def test_the_three_4401_branches_carry_three_different_messages(monkeypatch):
    """Cùng `AUTH_REQUIRED` + `4401`, nhưng câu giải thích phải khác nhau.

    Client xử lý cả ba giống hệt nhau (đăng xuất, quay về `/login`), nên mã lỗi
    không tách; người đọc log thì cần tách — "chưa gửi token" là lỗi client, còn
    "token không còn hiệu lực" gần như luôn nghĩa là backend vừa restart, thứ đã
    tốn nhiều lượt debug trước khi có dòng này.
    """

    from src.config import get_settings
    from src.services.auth import get_auth_store

    with TestClient(app) as client:

        def message_for(**connect_kwargs) -> str:
            with client.websocket_connect("/ws/engineer", **connect_kwargs) as ws:
                return receive_n(ws, 1)[0]["payload"]["message"]

        missing = message_for(subprotocols=["vivi.v1"], headers=dict(_ORIGIN_HEADERS))
        unknown_kwargs = {"subprotocols": ["vivi.v1", "bearer.bm90LWEtcmVhbC10b2tlbg"]}
        unknown = message_for(**unknown_kwargs, headers=dict(_ORIGIN_HEADERS))

        monkeypatch.setattr(get_settings(), "auth_token_ttl_seconds", -1)
        expired_token = get_auth_store().login(*ENGINEER_CREDENTIALS).token
        expired = message_for(**ws_connect_kwargs(expired_token))

    assert "thiếu" in missing
    assert "khởi động lại" in unknown
    assert "hết hạn" in expired
    assert len({missing, unknown, expired}) == 3


def test_engineer_token_connects_and_receives_the_handshake_snapshot():
    """Chứng thực dương — nếu thiếu, mọi test trên có thể xanh vì socket hỏng hẳn."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/engineer", **ws_connect_kwargs(login_engineer(client))) as ws:
            ws.send_json(HELLO)
            events = receive_n(ws, 2)

    assert [event["type"] for event in events] == ["state", "metrics"]


def test_server_selects_only_the_application_subprotocol():
    """`api_spec.md:505` — server chỉ chọn `vivi.v1`.

    Chọn lại `bearer.<token>` thì token bật ngược ra header handshake, tức nó nằm
    trong log của mọi proxy trên đường đi. `/ws/ivi` có dòng `accept()` riêng nên
    cần khẳng định riêng — chép một dòng thì cũng chép được cả lỗi của nó.
    """
    with TestClient(app) as client:
        kwargs = ws_connect_kwargs(login_engineer(client))
        with client.websocket_connect("/ws/engineer", **kwargs) as ws:
            assert ws.accepted_subprotocol == "vivi.v1"


# -- B4b: application subprotocol `vivi.v1` là bắt buộc -----------------------
#
# Phát hiện khi review PR #63. `api_spec.md:505` đòi client chào ĐỦ
# `vivi.v1, bearer.<base64url-access-token>`, nhưng cả hai route đều có
# `accept(subprotocol="vivi.v1" if "vivi.v1" in offered else None)` — chép làm hai bản, và
# cả hai bản đều MỞ kết nối cho client chỉ chào `bearer.<token>`. Reviewer chỉ nêu
# `/ws/engineer`; `/ws/ivi` hở y hệt ở dòng ngay bên dưới. Giờ cả hai đi qua một
# `_accept_ws`, nên hai nhóm test dưới đây lệch nhau là dấu hiệu ai đó đã tách lại làm hai.


def test_engineer_connection_without_the_application_subprotocol_is_rejected():
    """Token engineer HỢP LỆ, Origin hợp lệ — chỉ thiếu `vivi.v1`.

    Token hợp lệ là phần quan trọng: nếu để token sai thì test vẫn xanh nhờ nhánh auth
    và không nói gì về hàng rào subprotocol.
    """
    with TestClient(app) as client:
        kwargs = ws_connect_kwargs(login_engineer(client), with_application_protocol=False)
        with client.websocket_connect("/ws/engineer", **kwargs) as ws:
            _assert_rejected(ws, code="WS_EVENT_INVALID", close_code=1003)


def test_ivi_connection_without_the_application_subprotocol_is_rejected():
    """Đối xứng cho `/ws/ivi` với token driver hợp lệ — cùng một `_accept_ws`."""
    with TestClient(app) as client:
        kwargs = ws_connect_kwargs(login(client), with_application_protocol=False)
        with client.websocket_connect("/ws/ivi", **kwargs) as ws:
            _assert_rejected(ws, code="WS_EVENT_INVALID", close_code=1003)


def test_connection_with_no_subprotocols_at_all_is_rejected_as_protocol_not_auth():
    """Không chào gì cả: `WS_EVENT_INVALID`/`1003`, KHÔNG phải `AUTH_REQUIRED`/`4401`.

    Khoá thứ tự kiểm: subprotocol trước auth. Đảo lại thì một client còn chưa nói đúng
    giao thức đã được cho biết token của nó hợp lệ hay không, và `1003` biến thành `4401`
    — đẩy client đi refresh token cho một lỗi mà token mới không bao giờ sửa được.
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws/engineer", headers=dict(_ORIGIN_HEADERS)) as ws:
            _assert_rejected(ws, code="WS_EVENT_INVALID", close_code=1003)


def test_ivi_selects_only_the_application_subprotocol():
    """Bản `/ws/ivi` của `test_server_selects_only_the_application_subprotocol`.

    `/ws/ivi` chưa từng có khẳng định này ở đâu — chỉ `/ws/engineer` có. Cùng lý do:
    chọn lại `bearer.<token>` thì token bật ngược ra header handshake và nằm trong log
    của mọi proxy trên đường đi.
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi", **ws_connect_kwargs(login(client))) as ws:
            assert ws.accepted_subprotocol == "vivi.v1"


# -- B3: đóng socket đã chết không được ném ra ngoài route ---------------------


def test_close_that_fails_a_second_time_does_not_escape_the_ivi_route(monkeypatch):
    """`ivi_stream` phải đóng qua `_close_quietly`, không `close()` trần.

    `websocket.close()` trên socket đã chết ném `WebSocketDisconnect` **lần thứ hai**;
    gặp thật khi client ngắt trước `connection.init` — rất dễ ở dev vì React
    StrictMode mount/unmount hai lần. `engineer_stream` đã có `_close_quietly` từ
    PR #42, `ivi_stream` thì chưa, nên nó đổ traceback rác lấp mất lỗi thật
    (`docs/handoff/BE-OBS-001-blockers.md` mục B3).

    Ép `close()` hỏng thay vì dàn dựng một client ngắt đúng nhịp: nhịp đó là điều
    kiện tranh chấp, không tái lập tin cậy được, còn thứ cần khoá thì chỉ là "lỗi
    của `close()` không được thoát ra ngoài". Hỏng thật hay bị ép hỏng, đường xử lý
    là một.

    Đi qua nhánh `connection.init` sai định dạng, KHÔNG qua nhánh auth: nhánh auth
    đóng bằng `_reject_auth` (dùng chung với `/ws/engineer`) nên sẽ xanh cả khi thân
    `ivi_stream` vẫn còn gọi `close()` trần.
    """
    from starlette.websockets import WebSocket

    async def _exploding_close(self, code: int = 1000, reason: str | None = None) -> None:
        raise RuntimeError("socket đã chết trước khi kịp đóng")

    monkeypatch.setattr(WebSocket, "close", _exploding_close)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi", **ws_connect_kwargs(login(client))) as ws:
            ws.send_json({"type": "khong_hop_le"})
            event = receive_n(ws, 1)[0]

    assert event["payload"]["code"] == "WS_EVENT_INVALID"

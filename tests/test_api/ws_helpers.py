"""Helper auth + đọc sự kiện WS có chặn thời gian chờ, dùng chung cho `/ws/ivi` và `/ws/engineer`."""

import base64
import json

import anyio

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_ORIGIN_HEADERS = {"origin": "http://localhost:3000"}


#: Hai demo user cứng của `src/services/auth.py`. Khai ở đây để test không rải
#: chuỗi literal khắp nơi — đổi mật khẩu demo thì chỉ sửa một chỗ.
DRIVER_CREDENTIALS = ("driver.demo@example.com", "DemoDriver123!")
ENGINEER_CREDENTIALS = ("engineer.demo@example.com", "DemoEngineer123!")


def login(client, email: str = DRIVER_CREDENTIALS[0], password: str = DRIVER_CREDENTIALS[1]) -> str:
    """Đăng nhập demo user, trả `access_token` — dùng để build subprotocol bearer cho WS."""
    response = client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json={"email": email, "password": password})
    return response.json()["data"]["access_token"]


def login_engineer(client) -> str:
    """Token vai trò `engineer` — cho `/ws/engineer`, `/traces/{id}` và `/metrics/summary`."""
    return login(client, *ENGINEER_CREDENTIALS)


def bearer_subprotocol(token: str) -> str:
    """Ngược của `frontend/src/lib/services/shared/ws.ts`'s `toBase64Url()`."""
    encoded = base64.urlsafe_b64encode(token.encode("utf-8")).rstrip(b"=").decode("ascii")
    return f"bearer.{encoded}"


def ws_connect_kwargs(token: str, *, with_application_protocol: bool = True) -> dict:
    """`subprotocols`/`headers` cho `client.websocket_connect(path, **ws_connect_kwargs(token))`.

    Giống hệt nhau cho `/ws/ivi` và `/ws/engineer`: cả hai đều đi qua
    `_authenticate_ws_connection`, chỉ khác role mà token mang.

    `with_application_protocol=False` bỏ `vivi.v1` và chỉ chào `bearer.<token>` — dựng
    đúng client vi phạm `api_spec.md:505` mà `_accept_ws` phải từ chối. Mặc định `True`
    nên mọi lời gọi cũ không đổi.

    `headers` PHẢI là dict mới mỗi lần gọi: `TestClient.websocket_connect()` mutate nó
    bằng `setdefault(...)` (thêm `sec-websocket-protocol`, `connection`, ...) — dùng
    chung một object giữa nhiều lần gọi khiến subprotocol của lần gọi trước bị kẹt lại
    (setdefault không ghi đè key đã có), nên bearer token của lần gọi sau không bao giờ
    được gửi thật sự.
    """
    subprotocols = ["vivi.v1"] if with_application_protocol else []
    subprotocols.append(bearer_subprotocol(token))
    return {"subprotocols": subprotocols, "headers": dict(_ORIGIN_HEADERS)}


#: Tên cũ, giữ lại vì nhiều test `/ws/ivi` đang gọi. Cùng một hàm.
ivi_connect_kwargs = ws_connect_kwargs


def engineer_connect_kwargs(client) -> dict:
    """Đăng nhập engineer rồi trả luôn kwargs — hầu hết test `/ws/engineer` không cần token thô."""
    return ws_connect_kwargs(login_engineer(client))


def receive_n(ws, n: int, timeout: float = 5.0, *, skip_ui_policy: bool = True) -> list[dict]:
    """Đọc đúng `n` sự kiện **của lượt**, hết `timeout` thì fail sạch thay vì treo cả suite.

    **Bỏ qua `ui.policy` mặc định.** Mọi kết nối `/ws/ivi` nhận một `ui.policy` ngay sau
    handshake, và server phát thêm mỗi khi xe đổi giữa đứng yên/đang chạy — nó là event
    của *session*, không thuộc lượt nào, nên với mọi test khoá chuỗi event của một lượt
    thì nó là nhiễu. Đánh đổi đã cân nhắc: mặc định bỏ qua nghĩa là **helper này không
    bao giờ chứng minh được policy có được phát hay không**, nên hành vi đó phải được
    khoá ở chỗ khác — `tests/test_api/test_ws_ivi.py::test_ui_policy_phat_ngay_khi_ket_noi`
    và `::test_ui_policy_kich_theo_canh_khong_theo_tung_snapshot` đọc bằng
    `receive_json()` thô đúng vì lý do đó. Truyền `skip_ui_policy=False` khi cần thấy nó.

    `WebSocketTestSession.receive_json()` chặn vô hạn trong `portal.call(...)` và không có
    tham số timeout nào. Nếu implementation phát ít sự kiện hơn kỳ vọng thì
    `[ws.receive_json() for _ in range(N)]` đứng mãi, và cả suite treo thay vì báo lỗi.
    Cách duy nhất chặn trên được thời gian chờ là đi lại đúng đường của `receive_json()`
    (xem `starlette/testclient.py`) nhưng bọc thêm `anyio.fail_after`.
    """

    async def _receive_one():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()  # noqa: SLF001 - test helper, xem docstring

    events: list[dict] = []
    while len(events) < n:
        try:
            message = ws.portal.call(_receive_one)
        except TimeoutError as exc:
            got = [event["type"] for event in events]
            raise AssertionError(f"chờ {n} sự kiện, chỉ nhận được {len(events)}: {got}") from exc
        ws._raise_on_close(message)  # noqa: SLF001 - test helper, xem docstring
        event = json.loads(message["text"])
        if skip_ui_policy and event.get("type") == "ui.policy":
            continue
        events.append(event)
    return events


def drain_ui_policy(ws, timeout: float = 5.0) -> dict:
    """Đọc và trả về event `ui.policy` mà server phát ngay sau handshake.

    Mọi kết nối `/ws/ivi` đều nhận một `ui.policy` sau khi replay flush xong — không có
    nó thì tài xế nối máy giữa lúc xe đang chạy sẽ render giao diện không hạn chế cho
    tới lần xe đổi trạng thái kế tiếp. Test nào khoá chuỗi event phải rút nó ra trước,
    và **rút bằng cách khẳng định** chứ không bỏ qua im lặng, để nếu nó biến mất thì
    test đỏ chứ không lặng lẽ trôi.

    `skip_ui_policy=False` là **bắt buộc**, không phải tuỳ chọn: mặc định của
    `receive_n` là bỏ qua `ui.policy`, nên bản trước của hàm này lọc mất đúng thứ nó
    đi tìm rồi assert lên event kế tiếp — không bao giờ đúng được. Nó không bị lộ vì
    chưa call site nào dùng (Thành phát hiện khi đọc PR #77).
    """
    event = receive_n(ws, 1, timeout=timeout, skip_ui_policy=False)[0]
    assert event["type"] == "ui.policy", f"kỳ vọng ui.policy sau handshake, nhận {event['type']}"
    return event

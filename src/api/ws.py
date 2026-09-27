"""WebSocket Engineer (`/ws/engineer`) và Driver (`/ws/ivi`) — đẩy sự kiện realtime.

Vỏ sự kiện theo `docs/api_spec.md` mục "Server event base": mọi sự kiện phải
có `type`, `event_id`, `sequence` tăng đơn điệu, `trace_id`, `emitted_at`,
`schema_version` và `payload` có kiểu. Client gửi `connection.init` trước.

CẢ HAI socket đều có auth (issue #47 cho `/ws/ivi`, issue #45 B4 cho
`/ws/engineer`): bearer token qua subprotocol `bearer.<base64url-token>`, role, và
Origin allowlist — ba điều kiện đầu của `docs/api_spec.md` mục "WebSocket
contracts", kiểm bởi `_authenticate_ws_connection` **trước** `accept()`.
Thiếu/hết hạn token đóng bằng `4401`; sai role hoặc Origin đóng bằng `4403`.

CẢ HAI socket cũng bắt buộc application subprotocol `vivi.v1` (PR #63 review):
`api_spec.md:505` đòi client chào **đủ** `vivi.v1, bearer.<base64url-access-token>`,
nên chào thiếu `vivi.v1` bị từ chối bằng `WS_EVENT_INVALID` + đóng `1003` — xem
`_accept_ws`. Đây là hàng rào riêng, kiểm **trước** auth, và cố ý không dùng
`4401`/`4403`: nó là vi phạm hợp đồng giao thức chứ không phải thiếu quyền.

Điều kiện thứ tư, **session ownership**, chỉ áp cho `/ws/ivi` — `api_spec.md:533`
nói rõ `/ws/engineer` **bỏ** `session_id` (kỹ sư nhìn cả đội xe, không nhìn một
phiên), nên không có gì để mà sở hữu. Nó cần `session_id` từ `connection.init` nên
kiểm trong thân `ivi_stream`, không kiểm được ở hàm auth.

`/ws/ivi` HỖ TRỢ replay cursor: `connection.init` kèm `last_event_id` +
`last_sequence` sẽ replay mọi event đã phát sau cursor đó, giữ nguyên
`event_id`/`sequence` gốc — xem `IviEventBus.replay_snapshot()`
(`src/services/ivi_events.py`) và
docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md.

`/ws/engineer` KHÔNG có replay, và đó là quyết định chứ không phải nợ kỹ thuật.
Replay của `/ws/ivi` (ADR-014) đánh số theo **phiên**, không theo kết nối, vì lượt
thoại là một chuỗi có thứ tự mà tài xế phải nhận đủ. Stream kỹ sư không có phiên,
và bốn trong năm loại event của nó (`state`/`metrics`/`health`, và `trace` là bản
seal của lượt đã xong) là **ảnh chụp tại thời điểm**: phát lại một mẫu `health` của
30 phút trước cho dashboard vừa nối lại là nói dối về hiện tại, không phải phục hồi
độ tin cậy. Client nối lại nhận snapshot mới ngay trong handshake — xem
`engineer_stream` bên dưới. Nếu sau này cần lịch sử, chỗ đúng là `GET /traces/{id}`
và `GET /metrics/summary`, không phải một ring buffer thứ hai trên dây.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.auth_deps import AuthenticatedUser
from src.api.session_state import get_session_record
from src.config import get_settings
from src.models.vehicle import SCHEMA_VERSION, VehicleState, utc_now
from src.services import health as health_service
from src.services.auth import Role, get_auth_store
from src.services.engineer_events import EngineerSampler, get_engineer_bus
from src.services.ivi_events import get_event_bus
from src.services.metrics import build_metrics_summary
from src.services.trace_store import get_trace_store
from src.services.ui_policy import UiPolicyEmitter, derive_ui_policy, get_ui_policy_emitter
from src.services.vehicle_gateway import get_vehicle_gateway, snapshot_dict

logger = logging.getLogger(__name__)

router = APIRouter()

WS_CLIENT_MESSAGE_ALLOWLIST = frozenset({"connection.init"})

#: Application subprotocol duy nhất của P0 (`docs/api_spec.md:505`). Client chào nó
#: cùng `bearer.<...>`; server chỉ chọn lại **nó**, không bao giờ chọn `bearer.*`.
APPLICATION_SUBPROTOCOL = "vivi.v1"


async def _close_quietly(websocket: WebSocket, code: int) -> None:
    """`close()` trên socket đã chết tự ném `WebSocketDisconnect` lần thứ hai.

    Gặp thật khi client ngắt trước lúc gửi `connection.init` — rất dễ ở dev vì React
    StrictMode mount/unmount hai lần. Không sập server (FastAPI bắt ở tầng route)
    nhưng đổ traceback rác đầy console và che mất lỗi thật.

    Issue #45 (B3): `ivi_stream` từng có **đúng cùng lỗi** ở cả năm chỗ `close()` của
    nó; giờ cả hai socket đều đi qua hàm này. Đừng gọi `websocket.close()` trần trong
    file này nữa.
    """
    with contextlib.suppress(Exception):
        await websocket.close(code=code)


def _decode_bearer_subprotocol(offered: list[str]) -> str | None:
    """Tìm subprotocol `bearer.<base64url-token>` trong danh sách client chào, giải mã ra token thô.

    `docs/api_spec.md:503`: browser chào `vivi.v1, bearer.<base64url-access-token>` qua
    `Sec-WebSocket-Protocol` — token không đi qua header `Authorization` vì trình duyệt
    không cho set custom header khi mở WebSocket. `frontend/src/lib/services/shared/ws.ts`
    encode bằng `toBase64Url()` (btoa rồi thay `+/` bằng `-_`, bỏ padding `=` — RFC 6455 chỉ
    cho ký tự token hợp lệ trong subprotocol) — hàm này làm ngược lại.
    """
    for protocol in offered:
        if not protocol.startswith("bearer."):
            continue
        encoded = protocol.removeprefix("bearer.")
        padded = encoded + "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    return None


async def _accept_ws(websocket: WebSocket) -> bool:
    """`accept()` cho cả hai socket, chọn `vivi.v1`; trả `False` nếu client không chào nó.

    `api_spec.md:505` đòi client chào **đủ** `vivi.v1, bearer.<base64url-access-token>` và
    server "selects only `vivi.v1` in the response". Trước PR #63 cả hai route đều có
    `accept(subprotocol="vivi.v1" if "vivi.v1" in offered else None)` — chép làm hai bản, và
    cả hai bản đều **mở kết nối** cho client chỉ chào `bearer.<token>`. Một dòng ở một chỗ,
    cùng lý do với `_authenticate_ws_connection`: hai bản sao là hai định nghĩa "ai được
    nối", và chúng sẽ lệch nhau ở đúng lần sửa mà không ai sửa cả hai.

    Vẫn `accept()` cả khi thiếu — người gọi phát `error` rồi mới đóng, xem
    `_reject_handshake`. RFC 6455 cho phép server bỏ trống `Sec-WebSocket-Protocol` trong
    phản hồi (browser chỉ bắt buộc fail khi server chọn một protocol **không** được chào),
    nên kết nối vẫn mở đủ lâu để mã đóng và sự kiện `error` tới nơi.

    KHÔNG bao giờ truyền `bearer.*` vào `subprotocol=`: giá trị được chọn bật ngược ra
    header handshake, tức token nằm trong log của mọi proxy trên đường đi.
    """
    offered = websocket.scope.get("subprotocols", [])
    speaks_application_protocol = APPLICATION_SUBPROTOCOL in offered
    await websocket.accept(subprotocol=APPLICATION_SUBPROTOCOL if speaks_application_protocol else None)
    return speaks_application_protocol


def _authenticate_ws_connection(
    websocket: WebSocket, *, required_role: Role
) -> tuple[AuthenticatedUser | None, str | None, int | None, str | None]:
    """Xác thực bearer + role + Origin — ba trong bốn điều kiện `docs/api_spec.md`
    mục "WebSocket contracts" đòi trước khi xử lý `connection.init`.

    Dùng chung cho `/ws/ivi` (`required_role="driver"`) và `/ws/engineer`
    (`"engineer"`). Một hàm chứ không hai: hai bản sao là hai định nghĩa "ai được
    nối", và chúng sẽ lệch nhau ở đúng lần sửa mà không ai sửa cả hai.

    Điều kiện thứ tư, session ownership, chỉ áp cho `/ws/ivi` và cần `session_id` từ
    `connection.init` nên kiểm riêng trong `ivi_stream` — không thể kiểm ở đây.

    Trả `(None, code, close_code, message)` khi thất bại: `code` là mã lỗi để gói vào
    sự kiện `error`, `close_code` là mã đóng WS theo đúng spec (`4401` thiếu/hết hạn
    token, `4403` sai role hoặc Origin), `message` là câu giải thích cho người đọc.
    Ba nhánh `4401` có ba `message` khác nhau và đó là chủ đích: "chưa gửi token",
    "token hết hạn" và "token không còn hiệu lực vì server vừa restart" đòi ba phản
    ứng khác nhau của người vận hành, dù client xử lý cả ba giống nhau. Không log
    token hay giá trị subprotocol thô — chỉ log kết quả pass/fail, đúng yêu cầu
    redaction của spec.
    """
    offered = websocket.scope.get("subprotocols", [])
    token = _decode_bearer_subprotocol(offered)
    if token is None:
        return None, "AUTH_REQUIRED", 4401, "thiếu hoặc sai bearer token"
    record, reason = get_auth_store().resolve_with_reason(token)
    if record is None:
        return (
            None,
            "AUTH_REQUIRED",
            4401,
            (
                "token đã hết hạn, vui lòng đăng nhập lại"
                if reason == "expired"
                else "token không còn hiệu lực (server đã khởi động lại), vui lòng đăng nhập lại"
            ),
        )
    if record.role != required_role:
        return None, "FORBIDDEN", 4403, "không đủ quyền kết nối (role hoặc Origin không hợp lệ)"
    allowed_origins = {origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()}
    if websocket.headers.get("origin") not in allowed_origins:
        return None, "FORBIDDEN", 4403, "không đủ quyền kết nối (role hoặc Origin không hợp lệ)"
    return (
        AuthenticatedUser(user_id=record.user_id, role=record.role, display_name=record.display_name),
        None,
        None,
        None,
    )


async def _reject_handshake(
    websocket: WebSocket, stream: EventStream, *, code: str | None, close_code: int, message: str
) -> None:
    """Phát sự kiện `error` rồi đóng, cho mọi nhánh từ chối handshake của cả hai socket.

    Vẫn `accept()` trước rồi mới đóng, thay vì từ chối handshake thẳng: trình duyệt
    **không** đọc được body của một handshake bị từ chối, nên client sẽ chỉ thấy
    "connection failed" mà không biết là thiếu token, sai Origin, hay chào thiếu
    `vivi.v1`. Đóng sau khi accept thì mã đóng và sự kiện `error` đều tới nơi.
    """
    await websocket.send_json(
        stream.wrap(
            "error",
            {
                "code": code,
                "message": message,
                "retryable": False,
                "terminal": True,
                "details": {},
            },
        )
    )
    await _close_quietly(websocket, close_code)


async def _reject_missing_application_subprotocol(websocket: WebSocket, stream: EventStream) -> None:
    """Client không chào `vivi.v1` — `WS_EVENT_INVALID`, đóng `1003`.

    CỐ Ý không phải `4401`/`4403`. `api_spec.md` mục "WebSocket contracts" dành hai mã đó
    cho token/role/Origin/session; thiếu application subprotocol là vi phạm hợp đồng giao
    thức, không phải thiếu quyền — trả `4401` sẽ đẩy client đi refresh token cho một lỗi mà
    token mới không bao giờ sửa được. `1003` ("unsupported data") trùng khuôn với nhánh
    `connection.init` sai định dạng ngay bên dưới. Spec im lặng về ca này nên quyết định
    được ghi thẳng vào `docs/api_spec.md` (2026-08-12, review PR #63).
    """
    await _reject_handshake(
        websocket,
        stream,
        code="WS_EVENT_INVALID",
        close_code=1003,
        message=f"client phải chào application subprotocol `{APPLICATION_SUBPROTOCOL}` cùng `bearer.<token>`",
    )


async def _reject_auth(
    websocket: WebSocket,
    stream: EventStream,
    code: str | None,
    close_code: int | None,
    message: str | None = None,
) -> None:
    """Nhánh auth thất bại của cả hai socket — `4401` thiếu/hết hạn token, `4403` role/Origin.

    `message` do `_authenticate_ws_connection` cấp, vì chỉ nó biết nhánh nào đã trượt;
    fallback ở đây chỉ để hàm còn dùng được nếu ai đó gọi mà không kèm lý do.
    """
    await _reject_handshake(
        websocket,
        stream,
        code=code,
        close_code=close_code or 4403,
        message=message
        or (
            "thiếu hoặc sai bearer token"
            if code == "AUTH_REQUIRED"
            else "không đủ quyền kết nối (role hoặc Origin không hợp lệ)"
        ),
    )


async def _engineer_metrics_payload() -> dict[str, Any]:
    return build_metrics_summary(get_trace_store(), get_settings(), datetime.now(UTC)).model_dump(
        mode="json", by_alias=True
    )


async def _engineer_health_payload(websocket: WebSocket) -> dict[str, Any]:
    """Đọc readiness qua đúng hàm mà `GET /healthz` dùng.

    `websocket.app.state.mqtt` là cùng runtime mà route HTTP đọc — hai đường khác
    nhau sẽ cho hai câu trả lời khác nhau về cùng một hệ thống.
    """
    runtime = getattr(websocket.app.state, "mqtt", None)
    components = await health_service.collect_health(get_settings(), runtime)
    checked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return health_service.health_event_payload(components, checked_at)


class EventStream:
    """Sinh vỏ sự kiện với `sequence` tăng đơn điệu trong một kết nối."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._sequence = 0

    def wrap(
        self,
        event_type: str,
        payload: dict,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._sequence += 1
        event: dict[str, Any] = {
            "type": event_type,
            "event_id": f"evt_{uuid.uuid4().hex[:20]}",
            "sequence": self._sequence,
            "trace_id": trace_id or self.trace_id,
            "emitted_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "schema_version": SCHEMA_VERSION,
            "payload": payload,
        }
        if session_id is not None:
            event["session_id"] = session_id
        if turn_id is not None:
            event["turn_id"] = turn_id
        return event


@router.websocket("/ws/engineer")
async def engineer_stream(websocket: WebSocket) -> None:
    user, auth_error_code, auth_close_code, auth_message = _authenticate_ws_connection(
        websocket, required_role="engineer"
    )
    speaks_application_protocol = await _accept_ws(websocket)
    stream = EventStream(trace_id=f"tr_ws_{uuid.uuid4().hex[:12]}")

    # Subprotocol TRƯỚC auth: nó là hợp đồng tầng vận chuyển, rẻ hơn, và không tiết lộ
    # gì về tính hợp lệ của token cho một client còn chưa nói đúng giao thức.
    if not speaks_application_protocol:
        await _reject_missing_application_subprotocol(websocket, stream)
        return

    if user is None:
        await _reject_auth(websocket, stream, auth_error_code, auth_close_code, auth_message)
        return

    try:
        hello = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await _close_quietly(websocket, 1003)
        return

    if hello.get("type") not in WS_CLIENT_MESSAGE_ALLOWLIST:
        await websocket.send_json(
            stream.wrap(
                "error",
                {
                    "code": "WS_EVENT_INVALID",
                    "message": "client control message đầu tiên phải là connection.init",
                    "retryable": False,
                    "terminal": True,
                    "details": {"received": hello.get("type")},
                },
            )
        )
        await _close_quietly(websocket, 1003)
        return

    # Đọc state qua cổng, cùng nguồn với GET /api/v1/vehicle/state — hai kênh
    # lệch nhau thì dashboard kỹ sư và màn hình tài xế sẽ nói hai chuyện khác nhau
    # về cùng một chiếc xe.
    #
    # ĐỔI HÀNH VI so với bản trước: khi `MQTT_ENABLED=false`, cổng là bản
    # in-process nên luôn `ready` và nhánh `close(1011)` dưới đây **không còn
    # bắn nữa** — WS phục vụ state của xe in-process. Có chủ đích, cùng lý do với
    # việc `GET /vehicle/state` trả 200 ở chế độ đó: người làm frontend dựng được
    # UI mà không phải dựng Mosquitto. Tắt MQTT là lựa chọn tường minh của người
    # vận hành, không phải sự cố. Khi `MQTT_ENABLED=true` mà broker chết thì
    # lifespan vẫn gắn cổng MQTT, nên nhánh này vẫn bắn đúng như cũ.
    gateway = get_vehicle_gateway()
    readiness = gateway.readiness()
    if readiness.reason == "broker_unreachable":
        await websocket.send_json(
            stream.wrap(
                "error",
                {
                    "code": "MQTT_UNAVAILABLE",
                    "message": "backend chưa nối broker",
                    "retryable": True,
                    "terminal": False,
                    "details": {"reason": readiness.reason},
                },
            )
        )
        await _close_quietly(websocket, 1011)
        return

    async def push(state: VehicleState) -> None:
        await websocket.send_json(stream.wrap("state", {"vehicle_state": state.model_dump(mode="json")}))

    async def push_engineer(event_type: str, payload: dict[str, Any]) -> None:
        """`trace`/`metrics`/`health` từ bus phát tán.

        Đi qua cùng `stream.wrap` với `state`, nên `sequence` tăng đơn điệu **xuyên
        cả năm loại event** trong một kết nối — `api_spec.md:535` đòi đúng thế, và
        một bộ đếm riêng cho mỗi loại sẽ phá điều đó.
        """
        await websocket.send_json(stream.wrap(event_type, payload))

    settings = get_settings()
    bus = get_engineer_bus()
    bus.set_sampler(
        EngineerSampler(
            bus,
            _engineer_metrics_payload,
            lambda: _engineer_health_payload(websocket),
            settings.engineer_metrics_interval_s,
            settings.engineer_health_interval_s,
        )
    )

    # Bơm state hiện có ngay khi nối, để client không phải chờ transition kế tiếp.
    current = await gateway.last_known()
    if current is not None:
        await push(current)

    # Cùng lý do với `state`: dashboard phải có số ngay lúc mở. Chỉ `metrics` —
    # nó là fold thuần trên bộ nhớ, rẻ.
    #
    # `health` CỐ Ý không nằm ở đây dù cũng cần sớm: `collect_health` chạy 8 probe
    # thật và lần đầu còn nạp weight STT, mất hàng chục giây. Đặt nó trên đường
    # handshake thì `connection.init` treo và trình duyệt bỏ cuộc trước khi nhận
    # được gì. Sampler bắn `health` ngay vòng đầu, trong task riêng — xem
    # `EngineerSampler.__call__`.
    await push_engineer("metrics", await _engineer_metrics_payload())

    gateway.add_listener(push)
    bus.add_listener(push_engineer)
    try:
        while True:
            # P0 chỉ có connection.init trong allowlist; đọc tiếp để giữ kết nối
            # và phát hiện client ngắt.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Engineer WS ngắt kết nối (%s)", stream.trace_id)
    finally:
        gateway.remove_listener(push)
        bus.remove_listener(push_engineer)


@router.websocket("/ws/ivi")
async def ivi_stream(websocket: WebSocket) -> None:
    bus = get_event_bus()
    user, auth_error_code, auth_close_code, auth_message = _authenticate_ws_connection(
        websocket, required_role="driver"
    )
    speaks_application_protocol = await _accept_ws(websocket)
    stream = EventStream(trace_id=f"tr_ws_{uuid.uuid4().hex[:12]}")

    # Cùng thứ tự với `engineer_stream` — xem chú thích ở đó.
    if not speaks_application_protocol:
        await _reject_missing_application_subprotocol(websocket, stream)
        return

    if user is None:
        await _reject_auth(websocket, stream, auth_error_code, auth_close_code, auth_message)
        return

    try:
        hello = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await _close_quietly(websocket, 1003)
        return

    session_id = hello.get("session_id")
    if hello.get("type") not in WS_CLIENT_MESSAGE_ALLOWLIST or not session_id:
        await websocket.send_json(
            stream.wrap(
                "error",
                {
                    "code": "WS_EVENT_INVALID",
                    "message": "client control message đầu tiên phải là connection.init kèm session_id",
                    "retryable": False,
                    "terminal": True,
                    "details": {"received": hello.get("type")},
                },
            )
        )
        await _close_quietly(websocket, 1003)
        return

    # Điều kiện thứ tư của spec: session ownership. Ba điều kiện đầu (token, role,
    # Origin) đã kiểm ở `_authenticate_ws_connection` trước `accept()`; cái này cần
    # `session_id` từ hello nên chỉ kiểm được tới đây.
    session_record = get_session_record(session_id)
    if session_record is None or session_record.user_id != user.user_id:
        await websocket.send_json(
            stream.wrap(
                "error",
                {
                    "code": "FORBIDDEN",
                    "message": "session không tồn tại hoặc không thuộc về bạn",
                    "retryable": False,
                    "terminal": True,
                    "details": {},
                },
                session_id=session_id,
            )
        )
        await _close_quietly(websocket, 4403)
        return

    cursor_error, replay_events = bus.replay_snapshot(
        session_id, hello.get("last_event_id"), hello.get("last_sequence")
    )
    if cursor_error is not None:
        await websocket.send_json(
            stream.wrap(
                "error",
                {
                    "code": cursor_error,
                    "message": (
                        "cursor replay không hợp lệ"
                        if cursor_error == "REPLAY_CURSOR_INVALID"
                        else "cửa sổ replay đã hết hạn, kết nối lại không kèm cursor"
                    ),
                    "retryable": cursor_error == "REPLAY_WINDOW_EXPIRED",
                    "terminal": True,
                    "details": {
                        "last_event_id": hello.get("last_event_id"),
                        "last_sequence": hello.get("last_sequence"),
                    },
                },
                session_id=session_id,
            )
        )
        await _close_quietly(websocket, 1003)
        return

    # `replay_done` chỉ được lật sau khi TOÀN BỘ `replay_events` **và** mọi thứ đã lọt
    # vào `pending_live` trong lúc gửi đã được gửi xong — cho tới lúc đó, một live event
    # tới (route handler khác cùng session publish song song) bị giữ trong `pending_live`
    # thay vì gửi ngay, để không bao giờ chen trước phần đuôi replay/flush chưa gửi xong.
    # Vòng lặp flush dưới đây dùng `while pending_live:` (không phải `for event in
    # pending_live:`) vì mỗi `await websocket.send_json(...)` bên trong nó có thể nhường
    # control cho `push()` chạy và append thêm — một `for` duyệt snapshot ban đầu sẽ bỏ
    # sót phần tử mới đó, y hệt lỗi mà mục "Rủi ro" của spec đã cảnh báo. Việc lật cờ
    # `replay_done = True` chỉ đứng ngay sau khi `while pending_live:` xác nhận danh sách
    # đã rỗng, và giữa hai câu đó không có `await`, nên không có khoảng hở nào giữa "đã
    # flush hết những gì biết tới thời điểm này" và "bắt đầu gửi trực tiếp".
    replay_done = False
    pending_live: list[dict] = []

    async def push(event: dict) -> None:
        if replay_done:
            await websocket.send_json(event)
        else:
            pending_live.append(event)

    bus.add_listener(session_id, push)
    try:
        for event in replay_events:
            await websocket.send_json(event)
        while pending_live:
            await websocket.send_json(pending_live.pop(0))
        replay_done = True

        # Vế thứ hai của `ui.policy` (vế thứ nhất là kích-theo-cạnh ở `main.py`).
        # Không có câu này thì tài xế nối máy giữa lúc xe đang chạy sẽ không nhận
        # policy nào cho tới lần xe đổi trạng thái kế tiếp, và FE render giao diện
        # không hạn chế trong khi xe chạy — đúng lỗ hổng mà việc này bịt.
        #
        # Đặt **sau** `replay_done = True` để nó không chen vào giữa phần đuôi replay
        # chưa gửi xong; publish qua bus (không send_json thẳng) để event vẫn được gán
        # `event_id`/`sequence` của session và vào ring buffer như mọi event khác.
        # Cổng CỦA PHIÊN, không phải cổng toàn cục: dưới pool, tài xế thuê `vivi-xe-02`
        # mà nhận policy suy từ xe demo là siết/nới giao diện theo một chiếc xe khác.
        from src.api.session_state import get_vehicle, xe_cua_phien  # noqa: PLC0415

        xe_cua_no = xe_cua_phien(session_id)
        gateway = get_vehicle(session_id)
        try:
            state = await gateway.last_known()
        except Exception:  # noqa: BLE001 — mất trạng thái xe thì siết, không sập socket
            state = None
        handshake_policy = derive_ui_policy(snapshot_dict(state) if state is not None else None)
        await bus.publish(session_id, "ui.policy", None, UiPolicyEmitter.TRACE_ID, handshake_policy)
        # Báo cho emitter biết policy này **đã tới client**. Không có dòng này thì `_last`
        # của nó còn `None`, và lần đổi trạng thái xe đầu tiên sau khi server lên sẽ phát
        # lại đúng nội dung vừa gửi — một `ui.policy` thừa mỗi vòng đời tiến trình.
        get_ui_policy_emitter(xe_cua_no).note_published(handshake_policy)

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Driver WS ngắt kết nối (%s)", stream.trace_id)
    finally:
        bus.remove_listener(session_id, push)

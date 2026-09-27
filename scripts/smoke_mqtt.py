"""Smoke end-to-end cho SCRUM-19 — nghiệm thu 3 acceptance criteria.

Cần broker + xe ảo + backend đang chạy:

    docker compose up -d mqtt
    python -m src.vehicle_sim      # cửa sổ khác
    python -m src.serve            # cửa sổ khác (KHÔNG dùng uvicorn trực tiếp
                                   # trên Windows — xem src/serve.py)
    python scripts/smoke_mqtt.py

AC1  broker hoạt động ổn định trên cổng 1883
AC2  agent publish lệnh thành công lên topic lệnh
AC3  trạng thái xe ảo cập nhật realtime qua WebSocket

AC3 tự đăng nhập bằng tài khoản engineer seed sẵn: `/ws/engineer` đòi client chào **đủ**
`vivi.v1` và `bearer.<base64url-access-token>` của một tài khoản role `engineer`. Script
không nhận tham số cho việc này — nó là smoke của môi trường dev, và `DEMO_USERS` vốn đã
nằm trong mã nguồn (`src/db.py`). Chạy nó với backend không có hai tài khoản đó thì mục
đăng nhập fail tường minh, không phải treo.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Settings, get_settings  # noqa: E402
from src.services.mqtt_client import AiomqttClient, ensure_selector_event_loop  # noqa: E402
from src.services.tool_executor import ToolExecutor  # noqa: E402

API = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws/engineer"

#: Application subprotocol bắt buộc của P0 (`docs/api_spec.md:505`). Chào thiếu nó bị
#: từ chối bằng `WS_EVENT_INVALID` + đóng `1003`, **không** phải `4401`/`4403`.
APPLICATION_SUBPROTOCOL = "vivi.v1"

#: Tài khoản engineer seed sẵn (`DEMO_USERS` trong `src/db.py`). Phải đúng role này:
#: `/ws/engineer` gọi `_authenticate_ws_connection(..., required_role="engineer")`, nên
#: token của tài xế mở được HTTP nhưng bị đóng `4403` ở đây.
ENGINEER_EMAIL = "engineer.demo@example.com"
ENGINEER_PASSWORD = "DemoEngineer123!"


class SmokeAbortedError(RuntimeError):
    """Hỏng ở mức không chạy tiếp được — in một dòng đọc được thay vì traceback."""


def ok(label: str, detail: str = "") -> None:
    print(f"  [OK]   {label}{' — ' + detail if detail else ''}")


def fail(label: str, detail: str = "") -> None:
    print(f"  [FAIL] {label}{' — ' + detail if detail else ''}")


async def engineer_access_token(http: httpx.AsyncClient) -> str:
    """Đăng nhập lấy bearer token cho `/ws/engineer`.

    `/auth/login` đòi `X-Schema-Version: 1.0` (hoặc `version=1.0` trong `Content-Type`) —
    `require_login_schema_version` trong `src/api/auth_deps.py`. Thiếu là 400
    `REQUEST_CONTEXT_INVALID` chứ không phải 401, dễ đọc nhầm thành sai mật khẩu.
    """
    response = await http.post(
        f"{API}/api/v1/auth/login",
        json={"email": ENGINEER_EMAIL, "password": ENGINEER_PASSWORD},
        headers={"X-Schema-Version": "1.0"},
    )
    if response.status_code != 200:
        error = response.json().get("error", {})
        raise SmokeAbortedError(
            f"đăng nhập engineer thất bại: HTTP {response.status_code} {error.get('code')} — {error.get('message')}"
        )
    return response.json()["data"]["access_token"]


def bearer_subprotocol(token: str) -> str:
    """Gói token thành `bearer.<base64url-token>` để chào qua `Sec-WebSocket-Protocol`.

    Token không đi qua header `Authorization` vì trình duyệt không cho set custom header
    khi mở WebSocket (`docs/api_spec.md:503`). Padding `=` **phải** bỏ: RFC 6455 chỉ cho
    ký tự token hợp lệ trong tên subprotocol. Đây là bản đối xứng của
    `_decode_bearer_subprotocol` (`src/api/ws.py`) và của `toBase64Url()` bên frontend.
    """
    encoded = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
    return f"bearer.{encoded}"


def allowed_origin(settings: Settings) -> str:
    """Origin để chào WS — lấy cái đầu tiên trong `cors_origins`.

    `_authenticate_ws_connection` đòi header `Origin` phải nằm trong `cors_origins`, và
    một client **không phải trình duyệt** thì mặc định không gửi Origin nào cả — nên nó
    rơi vào đúng nhánh `4403 FORBIDDEN` như khi sai role. Đây là chỗ thứ hai script cũ
    không thể qua, và nó không lộ ra cho tới khi phần token đã đúng.

    Đọc qua `get_settings()` chứ **không** hard-code `http://localhost:3000`: cùng bài
    học với tầng test L2, nơi đọc thẳng `os.getenv` từng khiến test nối nhầm broker và
    báo cáo phát hiện về một hệ thống khác.
    """
    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if not origins:
        raise SmokeAbortedError("`cors_origins` rỗng — backend sẽ đóng 4403 với mọi client WS")
    return origins[0]


async def first_state_event(ws: websockets.ClientConnection, timeout: float = 10) -> dict:
    """Đọc tới event `state` đầu tiên, và biến mọi nhánh từ chối thành thông báo đọc được.

    KHÔNG lấy mù tin nhắn đầu tiên rồi index thẳng `payload.vehicle_state`: sau
    `connection.init` server còn bơm `metrics` ngay lúc handshake, và khi từ chối thì tin
    đầu là `error` rồi đóng kết nối. Bản trước làm đúng thế nên **mọi** lỗi handshake đều
    hiện ra dưới dạng `KeyError: 'vehicle_state'` ở dòng 80 — issue #143.
    """
    while True:
        try:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        except TimeoutError:
            raise SmokeAbortedError(
                f"không nhận được event `state` trong {timeout:.0f}s — xe ảo đã publish snapshot chưa?"
            ) from None
        except websockets.ConnectionClosed as exc:
            raise SmokeAbortedError(f"server đóng WS ({exc.code}) trước khi đẩy state") from None
        if event.get("type") == "state":
            return event
        if event.get("type") == "error":
            payload = event.get("payload") or {}
            raise SmokeAbortedError(f"WS từ chối: {payload.get('code')} — {payload.get('message')}")


async def main() -> int:
    settings = get_settings()
    failures = 0

    print("\n=== AC1: broker + xe ảo ===")
    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.get(f"{API}/healthz")
    body = response.json()
    if response.status_code == 200:
        components = {name: c["status"] for name, c in body["data"]["components"].items()}
    else:
        components = {name: c["status"] for name, c in body["error"]["details"]["dependencies"].items()}
    if components.get("mqtt") == "ready":
        ok("backend nối được broker", settings.mqtt_url)
    else:
        fail("backend chưa nối được broker", json.dumps(components))
        failures += 1
    if components.get("vehicle_simulator") == "ready":
        ok("xe ảo online, heartbeat còn tươi")
    else:
        fail("xe ảo chưa sẵn sàng", json.dumps(components))
        failures += 1

    print("\n=== AC3 (chuẩn bị): mở WebSocket engineer ===")
    async with httpx.AsyncClient(timeout=10) as http:
        token = await engineer_access_token(http)
    ok("đăng nhập engineer", ENGINEER_EMAIL)

    ws = await websockets.connect(
        WS,
        subprotocols=[APPLICATION_SUBPROTOCOL, bearer_subprotocol(token)],
        origin=allowed_origin(settings),
    )
    await ws.send(
        json.dumps(
            {
                "type": "connection.init",
                "client_message_id": "cmsg_smoke",
                "sent_at": "2026-08-07T00:00:00Z",
                "schema_version": "1.0",
            }
        )
    )
    first = await first_state_event(ws)
    before_temp = first["payload"]["vehicle_state"]["hvac"]["temperature_c"]
    ok("WS bơm state ngay khi nối", f"hvac.temperature_c = {before_temp}")

    print("\n=== AC2: publish lệnh lên topic lệnh ===")
    client = AiomqttClient(
        settings.mqtt_url,
        client_id="smoke-backend",
        username=settings.mqtt_backend_username or None,
        password=settings.backend_password() or None,
    )
    await client.start()
    executor = ToolExecutor(client, settings.vehicle_id, timeout_ms=5000)
    await executor.attach()

    target = 30 if before_temp != 30 else 18
    result = await executor.execute(
        plan_id="plan_smoke",
        step_id="step_1",
        tool="set_hvac_temperature",
        args={"temperature_c": target},
        expected_state_version=first["payload"]["vehicle_state"]["state_version"],
    )
    if result.status == "completed":
        ok(
            "lệnh tới v1/vehicles/{id}/commands/hvac và hoàn tất",
            f"state_version {result.expected_state_version} -> {result.observed_state_version}",
        )
    else:
        fail("lệnh không hoàn tất", f"{result.status}/{result.error_code}")
        failures += 1

    print("\n=== AC3: state cập nhật realtime qua WebSocket ===")
    try:
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if event["type"] != "state":
                continue
            state = event["payload"]["vehicle_state"]
            if state["hvac"]["temperature_c"] == target:
                ok(
                    "WS đẩy state mới, không cần hỏi lại",
                    f"seq={event['sequence']} temperature_c={target}",
                )
                break
    except TimeoutError:
        fail("không nhận được state mới qua WS trong 10s")
        failures += 1

    print("\n=== REST khớp với WS ===")
    async with httpx.AsyncClient(timeout=10) as http:
        body = (await http.get(f"{API}/api/v1/vehicle/state")).json()
    rest_temp = body["data"]["vehicle_state"]["hvac"]["temperature_c"]
    if rest_temp == target:
        ok("GET /api/v1/vehicle/state trả cùng giá trị", f"temperature_c={rest_temp}")
    else:
        fail("REST lệch WS", f"rest={rest_temp} target={target}")
        failures += 1

    await ws.close()
    await client.stop()

    print()
    if failures:
        print(f"SMOKE THẤT BẠI: {failures} mục")
    else:
        print("SMOKE ĐẠT: cả 3 acceptance criteria")
    return 1 if failures else 0


if __name__ == "__main__":
    # Cùng lý do với `src/vehicle_sim/__main__.py`: `loop_factory=` chỉ có từ Python
    # 3.12, repo chạy 3.11. Chỗ này nằm ngay TRƯỚC bước chạy test trong quy trình L3,
    # nên sửa mỗi simulator mà bỏ qua đây thì vẫn vấp đúng `TypeError` ở bước trước đó.
    ensure_selector_event_loop()
    try:
        sys.exit(asyncio.run(main()))
    except SmokeAbortedError as exc:
        # Một dòng đọc được, không traceback: script này hay được chạy bởi người đang
        # dựng máy lần đầu, và issue #143 chính là ca "traceback che mất nguyên nhân".
        print()
        fail("smoke dừng sớm", str(exc))
        sys.exit(1)

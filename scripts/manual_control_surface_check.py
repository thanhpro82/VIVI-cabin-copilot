r"""Kiểm tay bề mặt điều khiển qua MQTT thật — backend và xe ảo là hai tiến trình.

Sinh ra cho task *"Run MQTT control-surface acceptance tests"*: phủ HITL cửa,
mức quạt tuyệt đối, quy tắc cốp chỉ mở khi xe đứng yên, và các chế độ đèn của
PR #92.

## Vì sao là script chứ không phải một test nữa

Hai ca cốp cần **đổi tốc độ xe ảo giữa chừng**, mà `L3Stack` trong
`tests/test_vehicle/test_l3_two_process.py` spawn simulator với
`stdin=DEVNULL` — console điều khiển của nó thoát ngay. Ở đây stdin là `PIPE`
nên gửi được `speed 30 D` / `stop`, đúng cách một người ngồi trước máy sẽ làm.

Deliverable của task là **bằng chứng chạy tay**, nên script in ra một bảng đọc
được rồi trả exit code, thay vì chỉ assert im lặng.

## Không đụng môi trường đang chạy

Dùng `VEHICLE_ID`/`APP_PORT` riêng, nối vào **cùng** broker của
`docker compose up mqtt`. Container `vehicle-simulator` của demo cứ chạy tiếp:
nó publish trên topic của `vehicle-demo-01`, còn ta ở `vehicle-acc-01`.

    docker compose up -d --wait mqtt
    .\.venv\Scripts\python.exe scripts\manual_control_surface_check.py

Mọi tham số môi trường đều **đổi được**, và cổng có preflight nên máy khác chạy
lại không phải đọc mã nguồn mới biết vì sao hỏng:

| Biến | Mặc định | Dùng khi |
|---|---|---|
| `ACC_APP_PORT` | `8299` | Cổng đã bị chiếm — script báo ngay thay vì treo 180 s ở `/healthz` |
| `ACC_VEHICLE_ID` | `vehicle-acc-01` | Chạy hai lượt song song trên cùng một broker |
| `ACC_DRIVER_EMAIL` / `ACC_DRIVER_PASSWORD` | lấy từ `DEMO_USERS` | Backend seed tài khoản khác |
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import connect as ws_connect

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.config import get_settings  # noqa: E402
from src.db import DEMO_USERS  # noqa: E402


def _demo_credential(role: str) -> tuple[str, str]:
    """Credential lấy từ **chính nguồn seed**, không chép lại vào script.

    `DEMO_USERS` (`src/db.py`) là nơi backend seed tài khoản; chép email/mật khẩu
    sang đây tạo bản sao thứ hai sẽ lệch im lặng vào đúng ngày ai đó đổi seed —
    script fail ở bước `login` với 401 và người chạy đi tìm lỗi ở tầng auth.
    Biến môi trường vẫn thắng, để chạy được với một backend seed khác.
    """
    for _user_id, email, password, user_role, _display_name in DEMO_USERS:
        if user_role == role:
            return email, password
    raise SystemExit(f"DEMO_USERS không có tài khoản role {role!r} — không đăng nhập được")


_DRIVER_EMAIL, _DRIVER_PASSWORD = _demo_credential("driver")

VEHICLE_ID = os.getenv("ACC_VEHICLE_ID", "vehicle-acc-01")
APP_PORT = int(os.getenv("ACC_APP_PORT", "8299"))
DRIVER_EMAIL = os.getenv("ACC_DRIVER_EMAIL") or _DRIVER_EMAIL
DRIVER_PASSWORD = os.getenv("ACC_DRIVER_PASSWORD") or _DRIVER_PASSWORD
BASE_URL = f"http://127.0.0.1:{APP_PORT}/api/v1"
HEALTHZ_URL = f"http://127.0.0.1:{APP_PORT}/healthz"
WS_URL = f"ws://127.0.0.1:{APP_PORT}/ws/ivi"
STARTUP_TIMEOUT_S = 180.0
_SCHEMA = {"X-Schema-Version": "1.0"}

#: Application subprotocol bắt buộc của cả hai WebSocket (`docs/api_spec.md:505`).
APPLICATION_SUBPROTOCOL = "vivi.v1"


def preflight_port() -> None:
    """Cổng bận thì dừng ngay, đừng để hỏng ở chỗ khác 3 phút sau.

    Không có bước này, một cổng đã bị chiếm biểu hiện thành `uvicorn` chết lặng
    trong `backend.log` còn script thì chờ hết `STARTUP_TIMEOUT_S` rồi báo
    "backend chưa thấy mqtt ready" — một triệu chứng trỏ sai hoàn toàn về nguyên
    nhân. Đây là điều kiện tái chạy được trên máy người khác, nên nó phải nói rõ
    cách chữa chứ không chỉ báo lỗi.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        if probe.connect_ex(("127.0.0.1", APP_PORT)) == 0:
            raise SystemExit(
                f"cổng {APP_PORT} đang có thứ khác nghe. Đặt ACC_APP_PORT sang cổng trống, ví dụ:\n"
                f'    $env:ACC_APP_PORT="8399"; .\\.venv\\Scripts\\python.exe scripts\\manual_control_surface_check.py'
            )


class Stack:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.http = httpx.Client(base_url=BASE_URL, timeout=30.0)
        self._procs: dict[str, subprocess.Popen] = {}
        self._logs: list[Any] = []

    def spawn(self, module: str, name: str, *, stdin_pipe: bool = False) -> subprocess.Popen:
        env = os.environ.copy()
        env["VEHICLE_ID"] = VEHICLE_ID
        env["APP_PORT"] = str(APP_PORT)
        env["MQTT_ENABLED"] = "true"
        env["MQTT_URL"] = get_settings().mqtt_url
        env["PYTHONIOENCODING"] = "utf-8"
        handle = (self.log_dir / f"{name}.log").open("w", encoding="utf-8", errors="replace")
        self._logs.append(handle)
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", module],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        self._procs[name] = proc
        return proc

    def sim_command(self, line: str) -> None:
        """Gửi một dòng vào console của xe ảo (`speed <km/h> [gear]`, `stop`)."""
        proc = self._procs["simulator"]
        assert proc.stdin is not None
        proc.stdin.write(f"{line}\n".encode())
        proc.stdin.flush()

    def close(self) -> None:
        self.http.close()
        for proc in self._procs.values():
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        for handle in self._logs:
            handle.close()

    def log_tail(self, name: str, lines: int = 20) -> str:
        path = self.log_dir / f"{name}.log"
        if not path.exists():
            return f"(không có {path})"
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

    def components(self) -> dict[str, str]:
        response = self.http.get(HEALTHZ_URL)
        body = response.json()
        raw = body["data"]["components"] if response.status_code == 200 else body["error"]["details"]["dependencies"]
        return {name: component["status"] for name, component in raw.items()}

    def state(self) -> dict[str, Any]:
        response = self.http.get("/vehicle/state")
        response.raise_for_status()
        return response.json()["data"]["vehicle_state"]


def wait_until(probe, *, timeout: float, description: str):
    """Chờ có deadline, và in ra thứ thấy lần cuối khi hết giờ."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = probe()
        except Exception as exc:  # noqa: BLE001
            last = exc
        else:
            if last:
                return last
        time.sleep(0.25)
    raise AssertionError(f"quá {timeout:.0f}s mà {description}. Lần cuối: {last!r}")


class DriverStream:
    """Kênh `/ws/ivi` **thật** — nguồn duy nhất chứng minh "bị chặn *vì safety*".

    Vì sao phải có: `POST /turns/text` trả `status: "completed"` cho cả lượt bị
    chặn (`turns.py` chỉ trả `failed` cho execution_failed/vehicle_state_unavailable
    và `clarify` cho approval_already_pending). Nên bộ ba "không có approval, không
    có outcomes, cốp không đổi" chỉ chứng minh **không có side effect** — một no-op
    vì router không khớp câu, hay vì STT ra chữ khác, cũng cho đúng ba dấu hiệu ấy.

    Tín hiệu semantic là event `action.blocked` với `code="SAFETY_BLOCKED"`
    (`src/services/ivi_events.py`, `docs/api_spec.md:577`), và nó **chỉ** đi qua
    WebSocket. Kèm với `plan.ready` phát ngay trước nó, hai event này nói được thứ
    HTTP không nói được: kế hoạch **đã được lập** cho đúng tool cốp, rồi mới bị
    chính sách chặn.

    Chạy nền trong một thread vì phần còn lại của script là đồng bộ; dùng client
    sync của `websockets` để khỏi kéo asyncio vào đây.
    """

    def __init__(self, token: str, session_id: str) -> None:
        origins = [origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()]
        if not origins:
            raise SystemExit("`cors_origins` rỗng — backend sẽ đóng WS bằng 4403 với mọi client")
        # Cùng phép mã hoá với `_decode_bearer_subprotocol` (`src/api/ws.py`) và
        # `toBase64Url()` bên frontend: base64url, **bỏ padding** — RFC 6455 chỉ cho
        # ký tự token hợp lệ trong tên subprotocol. Và Origin là điều kiện thứ ba của
        # handshake: client không phải trình duyệt thì mặc định không gửi nó, rồi
        # nhận đúng `4403` y hệt khi sai role.
        encoded = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
        self._ws = ws_connect(
            WS_URL,
            subprotocols=[APPLICATION_SUBPROTOCOL, f"bearer.{encoded}"],
            origin=origins[0],
            open_timeout=30,
        )
        self._ws.send(
            json.dumps(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_acc",
                    "sent_at": "2026-08-16T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
        )
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._pump = threading.Thread(target=self._drain, daemon=True)
        self._pump.start()

    def _drain(self) -> None:
        try:
            for raw in self._ws:
                event = json.loads(raw)
                with self._lock:
                    self._events.append(event)
        except Exception:  # noqa: BLE001 - đóng kết nối là kết thúc bình thường của vòng lặp
            return

    def mark(self) -> int:
        """Vị trí hiện tại trong dòng event.

        Mọi `wait_for` đều đi kèm một mark chụp **trước** khi gửi câu lệnh: nếu
        không, một `action.blocked` còn sót của ca trước sẽ làm ca sau pass oan.
        """
        with self._lock:
            return len(self._events)

    def wait_for(self, event_type: str, *, since: int, timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for event in self._events[since:]:
                    if event.get("type") == event_type:
                        return event
            time.sleep(0.1)
        return None

    def types_since(self, since: int) -> list[str]:
        with self._lock:
            return [event.get("type", "?") for event in self._events[since:]]

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001
            pass


class Runner:
    """Chạy từng ca, ghi Pass/Fail, không dừng ở ca đầu tiên hỏng."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []
        self._n = 0
        #: Mỗi lần chạy một tiền tố riêng. Bản đầu dùng bộ đếm trần (`acc:fan:2`)
        #: nên lần chạy **thứ hai** trùng key với lần đầu: `idempotency` replay đúng
        #: response cũ và không gửi lệnh nào xuống xe, rồi script chờ trạng thái đổi
        #: cho tới khi hết giờ. Backend làm đúng; script mới là chỗ sai.
        self.run_id = time.strftime("%Y%m%dT%H%M%S")

    def record(self, case_id: str, mo_ta: str, ok: bool, thuc_te: str) -> None:
        self.rows.append((case_id, mo_ta, "PASS" if ok else "FAIL", thuc_te))
        dau = "PASS" if ok else "FAIL"
        print(f"  [{dau}] {case_id}: {mo_ta}")
        print(f"         {thuc_te}")

    def key(self, prefix: str) -> str:
        self._n += 1
        return f"acc:{self.run_id}:{prefix}:{self._n}"

    @property
    def failed(self) -> int:
        return sum(1 for row in self.rows if row[2] == "FAIL")


def login(stack: Stack) -> str:
    response = stack.http.post(
        "/auth/login",
        headers=_SCHEMA,
        json={"email": DRIVER_EMAIL, "password": DRIVER_PASSWORD},
    )
    response.raise_for_status()
    return response.json()["data"]["access_token"]


def create_session(stack: Stack, token: str, key: str) -> str:
    response = stack.http.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}", **_SCHEMA, "Idempotency-Key": key},
        json={"vehicle_id": VEHICLE_ID},
    )
    response.raise_for_status()
    return response.json()["data"]["session_id"]


def say(stack: Stack, token: str, session_id: str, key: str, text: str) -> dict[str, Any]:
    response = stack.http.post(
        "/turns/text",
        headers={"Authorization": f"Bearer {token}", **_SCHEMA, "Idempotency-Key": key},
        json={"session_id": session_id, "text": text},
    )
    assert response.status_code == 200, f"{text!r} -> {response.status_code}: {response.text}"
    return response.json()["data"]


def approve(stack: Stack, token: str, key: str, data: dict[str, Any]) -> dict[str, Any]:
    approval_id = data["pending_approval"]["approval_id"]
    response = stack.http.post(
        f"/approvals/{approval_id}/decision",
        headers={"Authorization": f"Bearer {token}", **_SCHEMA, "Idempotency-Key": key},
        json={
            "decision": "approve",
            "approved_vehicle_state_version": data["action_plan"]["vehicle_state_version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def main() -> int:
    preflight_port()
    log_dir = REPO_ROOT / ".acc-logs"
    stack = Stack(log_dir)
    run = Runner()
    stream: DriverStream | None = None
    try:
        print("Khởi động xe ảo + backend (vehicle_id riêng, không đụng container demo)...")
        stack.spawn("src.vehicle_sim", "simulator", stdin_pipe=True)
        stack.spawn("src.serve", "backend")
        try:
            wait_until(
                lambda: (
                    stack.components()
                    if stack.components().get("mqtt") == "ready"
                    and stack.components().get("vehicle_simulator") == "ready"
                    else None
                ),
                timeout=STARTUP_TIMEOUT_S,
                description="backend chưa thấy mqtt + vehicle_simulator ready",
            )
        except AssertionError as exc:
            print(f"{exc}\n--- backend.log ---\n{stack.log_tail('backend')}")
            print(f"--- simulator.log ---\n{stack.log_tail('simulator')}")
            return 2
        print("Cả hai tiến trình đã ready.\n")

        token = login(stack)
        session_id = create_session(stack, token, run.key("session"))

        # Mở WS **trước** mọi lượt: `action.blocked` là event sống, không phải thứ
        # hỏi lại được qua HTTP. (Bus có ring buffer replay theo cursor, nhưng dựa
        # vào nó nghĩa là bằng chứng phụ thuộc một cơ chế thứ hai — mở sớm rẻ hơn.)
        stream = DriverStream(token, session_id)
        print(f"WS /ws/ivi đã nối cho session {session_id}\n")

        # -- Quạt gió: mức TUYỆT ĐỐI, không cộng dồn ---------------------------
        print("1. Mức quạt là giá trị tuyệt đối")
        for muc in (2, 3, 1):
            say(stack, token, session_id, run.key("fan"), f"Chỉnh quạt gió mức {muc}")
            state = wait_until(
                lambda muc=muc: stack.state() if stack.state()["hvac"]["fan_level"] == muc else None,
                timeout=20.0,
                description=f"quạt chưa về mức {muc}",
            )
            run.record(
                f"FAN-{muc}",
                f"'Chỉnh quạt gió mức {muc}' đặt fan_level = {muc}",
                state["hvac"]["fan_level"] == muc,
                f"fan_level = {state['hvac']['fan_level']}",
            )

        # -- Đèn: ba chế độ pha + đèn trần + từ chối tắt pha --------------------
        print("\n2. Chế độ đèn (PR #92)")
        for cau, mong_doi in (("Bật đèn chiếu xa", "high_beam"), ("Bật đèn chiếu gần", "low_beam")):
            say(stack, token, session_id, run.key("light"), cau)
            state = wait_until(
                lambda mong_doi=mong_doi: stack.state() if stack.state()["lights"]["headlight"] == mong_doi else None,
                timeout=20.0,
                description=f"đèn chưa sang {mong_doi}",
            )
            run.record(
                f"LIGHT-{mong_doi}",
                f"{cau!r} -> headlight = {mong_doi}",
                state["lights"]["headlight"] == mong_doi,
                f"headlight = {state['lights']['headlight']}",
            )

        say(stack, token, session_id, run.key("light"), "Bật đèn trần")
        state = wait_until(
            lambda: stack.state() if stack.state()["lights"]["interior"] else None,
            timeout=20.0,
            description="đèn trần chưa bật",
        )
        run.record(
            "LIGHT-interior",
            "'Bật đèn trần' -> interior = true",
            state["lights"]["interior"] is True,
            "interior = True",
        )

        truoc = stack.state()["lights"]["headlight"]
        data = say(stack, token, session_id, run.key("light"), "Tắt đèn pha")
        time.sleep(1.5)
        sau = stack.state()["lights"]["headlight"]
        # `data["status"]` KHÔNG dùng để phân biệt được: `turns.py` chỉ trả `failed`
        # cho execution_failed/vehicle_state_unavailable và `clarify` cho
        # approval_already_pending, còn lại đều là `completed` — nghĩa "lượt đã kết
        # thúc", không phải "lệnh đã chạy". Tín hiệu thật là: không có ActionPlan nào
        # được lập, và đèn không đổi.
        run.record(
            "LIGHT-off-denied",
            "'Tắt đèn pha' bị từ chối (UNECE R48, ADR-020) và không đổi đèn",
            data.get("action_plan") is None and sau == truoc,
            f"action_plan = {'không' if data.get('action_plan') is None else 'CÓ'}, headlight {truoc} -> {sau}",
        )

        # -- Cửa: S2, cần phê duyệt khi xe đứng yên ----------------------------
        print("\n3. Cửa cần phê duyệt (S2) khi xe đứng yên")
        stack.sim_command("stop")
        wait_until(
            lambda: stack.state() if stack.state()["motion"]["speed_kph"] == 0 else None,
            timeout=20.0,
            description="xe chưa dừng hẳn",
        )
        data = say(stack, token, session_id, run.key("door"), "Mở cửa bên lái")
        cho_duyet = data["status"] == "waiting_approval" and data["action_plan"]["requires_approval"] is True
        run.record(
            "DOOR-hitl",
            "'Mở cửa bên lái' (đứng yên) -> chờ phê duyệt, chưa thực thi",
            cho_duyet and stack.state()["doors"]["front_left"] == "closed",
            f"status = {data['status']}, cửa = {stack.state()['doors']['front_left']}",
        )
        if cho_duyet:
            approve(stack, token, run.key("decision"), data)
            state = wait_until(
                lambda: stack.state() if stack.state()["doors"]["front_left"] == "open" else None,
                timeout=20.0,
                description="cửa chưa mở sau khi duyệt",
            )
            run.record(
                "DOOR-approve",
                "Sau khi duyệt, cửa mở đúng một lần",
                state["doors"]["front_left"] == "open",
                f"cửa = {state['doors']['front_left']}, state_version = {state['state_version']}",
            )

        # -- Cốp: XE ĐANG CHẠY thì chặn trước cả HITL --------------------------
        print("\n4. Cốp — xe đang chạy")
        stack.sim_command("speed 30 D")
        wait_until(
            lambda: stack.state() if stack.state()["motion"]["speed_kph"] > 0 else None,
            timeout=20.0,
            description="xe ảo chưa chạy",
        )
        truoc = stack.state()
        moc = stream.mark()
        data = say(stack, token, session_id, run.key("trunk"), "Mở cốp sau")

        # Tín hiệu SEMANTIC, và là lý do ca này không còn chỉ chứng minh "không có
        # side effect". `status` không phân biệt được (xem ghi chú ở LIGHT-off-denied),
        # còn "không approval + không outcomes + cốp không đổi" thì một no-op — router
        # không khớp câu, hoặc STT ra chữ khác — cũng thoả cả ba. `action.blocked`
        # với `code=SAFETY_BLOCKED` chỉ phát ở nhánh `outcome == "blocked"` của
        # `emit_turn_lifecycle`, tức sau khi policy đã phân loại S3.
        blocked = stream.wait_for("action.blocked", since=moc, timeout=25.0)
        chan = (blocked or {}).get("payload") or {}
        ma_chan = chan.get("code")
        dung_ma = ma_chan == "SAFETY_BLOCKED"

        # Loại trừ nốt khả năng no-op: kế hoạch **đã được lập** cho đúng tool cốp và
        # được policy xếp S3, rồi mới bị chặn — chứ không phải câu lệnh rơi vào tra
        # sổ tay hay router không khớp. `plan_id` buộc event WS vào đúng lượt này,
        # nên một `action.blocked` sót lại của ca khác không cứu được ca này.
        ke_hoach = data.get("action_plan") or {}
        buoc_cop = [b for b in (ke_hoach.get("steps") or []) if b.get("tool") == "set_trunk_state"]
        dung_ke_hoach = (
            bool(buoc_cop)
            and all(b.get("safety_level") == "S3" for b in buoc_cop)
            and ke_hoach.get("plan_id") is not None
            and ke_hoach.get("plan_id") == chan.get("plan_id")
        )

        sau = stack.state()
        khong_hoi = not data.get("pending_approval")
        khong_chay = not (data.get("response") or {}).get("outcomes")
        khong_doi = sau["trunk"]["position"] == truoc["trunk"]["position"]
        run.record(
            "TRUNK-moving",
            "'Mở cốp sau' khi speed > 0 -> SAFETY_BLOCKED trước phê duyệt, cốp không đổi",
            dung_ma and dung_ke_hoach and khong_hoi and khong_chay and khong_doi,
            (
                f"speed = {truoc['motion']['speed_kph']} km/h gear = {truoc['motion']['gear']}, "
                f"action.blocked.code = {ma_chan!r}, "
                f"plan_id khớp = {ke_hoach.get('plan_id') == chan.get('plan_id')}, "
                f"steps = {[(b.get('tool'), b.get('safety_level')) for b in (ke_hoach.get('steps') or [])]}, "
                f"hộp phê duyệt = {'không' if khong_hoi else 'CÓ'}, "
                f"bước đã chạy = {len((data.get('response') or {}).get('outcomes') or [])}, "
                f"cốp {truoc['trunk']['position']} -> {sau['trunk']['position']}, "
                f"event nhận được = {stream.types_since(moc)}"
            ),
        )

        # -- Cốp: XE ĐỨNG YÊN thì là S2 ----------------------------------------
        print("\n5. Cốp — xe đứng yên")
        stack.sim_command("stop")
        wait_until(
            lambda: stack.state() if stack.state()["motion"]["speed_kph"] == 0 else None,
            timeout=20.0,
            description="xe chưa dừng hẳn",
        )
        moc = stream.mark()
        data = say(stack, token, session_id, run.key("trunk"), "Mở cốp sau")
        cho_duyet = data["status"] == "waiting_approval"

        # ĐỐI CHỨNG ÂM cho ca TRUNK-moving. Assert sự *có mặt* của `action.blocked`
        # ở trên chỉ có giá trị nếu nó **vắng mặt** khi không được phép có: một
        # assertion luôn đúng thì không phân biệt được gì cả. Cùng một câu lệnh, cùng
        # session, chỉ khác tốc độ — nên nếu đây cũng thấy `action.blocked` thì tín
        # hiệu kia đang đo thứ khác chứ không phải quy tắc an toàn.
        # 4 s là đủ: ở ca đang chạy, event tới trong cùng một lượt, trước `turn.completed`.
        chan_nham = stream.wait_for("action.blocked", since=moc, timeout=4.0)
        run.record(
            "TRUNK-stationary",
            "'Mở cốp sau' khi speed = 0, gear P -> chờ phê duyệt, KHÔNG có action.blocked",
            cho_duyet and stack.state()["trunk"]["position"] == "closed" and chan_nham is None,
            (
                f"status = {data['status']}, cốp = {stack.state()['trunk']['position']}, "
                f"action.blocked = {'không có (đúng)' if chan_nham is None else 'CÓ — sai'}, "
                f"event nhận được = {stream.types_since(moc)}"
            ),
        )
        if cho_duyet:
            approve(stack, token, run.key("decision"), data)
            state = wait_until(
                lambda: stack.state() if stack.state()["trunk"]["position"] == "open" else None,
                timeout=20.0,
                description="cốp chưa mở sau khi duyệt",
            )
            run.record(
                "TRUNK-approve",
                "Sau khi duyệt, cốp mở",
                state["trunk"]["position"] == "open",
                f"cốp = {state['trunk']['position']}, state_version = {state['state_version']}",
            )

        print("\n" + "=" * 78)
        print(f"{len(run.rows)} ca — {len(run.rows) - run.failed} PASS, {run.failed} FAIL")
        print("=" * 78)
        for case_id, mo_ta, ket_qua, thuc_te in run.rows:
            print(f"| {case_id:18} | {ket_qua:4} | {mo_ta:62} | {thuc_te} |")

        ket_qua_json = REPO_ROOT / ".acc-logs" / "ket-qua.json"
        ket_qua_json.write_text(
            json.dumps(
                {
                    "vehicle_id": VEHICLE_ID,
                    "app_port": APP_PORT,
                    # Event WS nguyên văn của ca TRUNK-moving: đây là bằng chứng
                    # "bị chặn *vì safety*", không suy ra được từ bảng Pass/Fail.
                    "trunk_moving_action_blocked": (blocked or {}).get("payload"),
                    "rows": [dict(zip(("case_id", "mo_ta", "ket_qua", "thuc_te"), r)) for r in run.rows],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nKết quả máy đọc được: {ket_qua_json}")
        return 1 if run.failed else 0
    finally:
        if stream is not None:
            stream.close()
        stack.close()


if __name__ == "__main__":
    raise SystemExit(main())

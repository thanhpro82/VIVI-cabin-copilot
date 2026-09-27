"""Tầng L3 — backend và xe ảo chạy như **hai tiến trình thật**, nối qua Mosquitto thật.

Đây là thứ issue #49 đòi, và cũng đúng điểm mù mà `scripts/report_mqtt_e2e.py` đã
tự khai cho tầng L2: *"Broker thật nhưng vẫn trong một tiến trình pytest: không có
HTTP/WS thật, không có backend và simulator chạy như hai tiến trình riêng."*

Bốn thứ chỉ tầng này chứng minh được:

1. `python -m src.serve` và `python -m src.vehicle_sim` — hai process, hai identity
   MQTT, hai kết nối riêng — thật sự nói chuyện được với nhau. Mọi tầng dưới đều
   dựng cả hai bên trong cùng một process pytest, tức chưa bao giờ kiểm cái đó.
2. HTTP thật qua socket, không phải `ASGITransport`.
3. WebSocket thật qua socket, không phải `TestClient` (là in-process shim).
4. Xe ảo **chết** thì bề mặt HTTP của backend nhìn thấy — chuỗi
   `process chết → heartbeat cũ dần → probe đổi → /healthz đổi` không thể dàn dựng
   trong một process.

Mặc định BỎ QUA, cùng khuôn với tầng L2 (`test_contract_mosquitto.py`):

    docker compose up -d --wait mqtt
    $env:MQTT_L3_TESTS = "1"
    pytest tests/test_vehicle/test_l3_two_process.py -v

Đồng bộ, không async: `pyproject.toml` đặt
`asyncio_default_fixture_loop_scope = "function"`, nên một fixture async ở scope
`module` (mà ta cần, vì khởi hai process tốn hàng chục giây) sẽ vướng chuyện loop
scope. Dùng `httpx.Client` + `websockets.sync.client`, và chỉ mượn `asyncio.run`
đúng một lần trong teardown để dọn retained message.

MỌI vòng chờ ở đây đều có deadline và in ra thứ nhìn thấy lần cuối. Bài học từ
deadlock `test_ws_ivi.py` (2026-08-11): một điều kiện không bao giờ tới phải
**fail**, không được treo — mà ở đây rủi ro treo cao hơn nhiều, vì đầu bên kia là
một tiến trình có thể chết im lặng.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.sync.client import connect as ws_connect

from src import mqtt_topics
from src.config import get_settings
from src.models.vehicle import DOMAINS
from src.services.mqtt_client import AiomqttClient

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Xe riêng cho L3 — không giẫm lên `vehicle-demo-01` của demo có thể đang chạy.
VEHICLE_ID = "vehicle-l3-01"
#: Cổng riêng, tránh 8000 của backend dev.
APP_PORT = 8199
BASE_URL = f"http://127.0.0.1:{APP_PORT}/api/v1"
#: `/healthz` nằm ở ROOT, không dưới `/api/v1` — khác mọi interface P0 còn lại.
#: Truyền URL tuyệt đối thì httpx bỏ qua `base_url`.
HEALTHZ_URL = f"http://127.0.0.1:{APP_PORT}/healthz"
WS_URL = f"ws://127.0.0.1:{APP_PORT}"
ORIGIN = "http://localhost:3000"

#: Backend nạp STT/TTS/RAG singleton ngay trong lifespan trước `yield` (issue #51),
#: nên nó không nhận kết nối cho tới khi nạp xong. Trên máy có model thật, con số
#: này là hàng chục giây chứ không phải vài giây.
STARTUP_TIMEOUT_S = 180.0
#: Heartbeat stale mặc định 15s; cộng biên cho nhịp poll của probe.
HEARTBEAT_FLIP_TIMEOUT_S = 45.0

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("MQTT_L3_TESTS") != "1",
        reason="cần broker thật + 2 tiến trình — đặt MQTT_L3_TESTS=1 sau `docker compose up -d --wait mqtt`",
    ),
]


# -- chờ có deadline ----------------------------------------------------------


def _wait_until(probe: Callable[[], Any], *, timeout: float, description: str) -> Any:
    """Gọi `probe()` tới khi nó trả giá trị truthy. Hết giờ thì **fail**, kèm thứ thấy lần cuối.

    Nuốt exception của `probe` có chủ đích: trong lúc backend chưa lên,
    `httpx` ném `ConnectError` là chuyện bình thường. Nhưng exception cuối cùng
    vẫn được giữ lại và in ra — nếu không thì "hết 180 giây" sẽ không nói được
    vì sao.
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = probe()
        except Exception as exc:  # noqa: BLE001 — mọi lỗi tạm đều là "chưa tới lúc"
            last = exc
        else:
            if last:
                return last
        time.sleep(0.25)
    raise AssertionError(f"quá {timeout:.0f}s mà {description}. Lần cuối thấy: {last!r}")


# -- hai tiến trình -----------------------------------------------------------


class L3Stack:
    """Backend + xe ảo, mỗi bên một tiến trình, cùng trỏ vào broker thật."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.http = httpx.Client(base_url=BASE_URL, timeout=30.0)
        self._backend: subprocess.Popen | None = None
        self._simulator: subprocess.Popen | None = None
        self._log_files: list[Any] = []

    # -- vòng đời ------------------------------------------------------------

    def _spawn(self, module: str, name: str) -> subprocess.Popen:
        """Ghi log ra FILE, không phải `PIPE`.

        `PIPE` mà không ai đọc sẽ đầy buffer rồi **chẹn tiến trình con** — uvicorn
        log mỗi request nên đây không phải rủi ro lý thuyết. File còn cho phép in
        đuôi log vào thông điệp assert khi khởi động thất bại, thứ quyết định
        giữa "sửa được trong một phút" và "ngồi đoán".
        """
        env = os.environ.copy()
        env["VEHICLE_ID"] = VEHICLE_ID
        env["APP_PORT"] = str(APP_PORT)
        # Bộ test chạy với MQTT_ENABLED=false; tiến trình con thì KHÔNG được thế.
        env["MQTT_ENABLED"] = "true"
        env["MQTT_URL"] = get_settings().mqtt_url
        env["PYTHONIOENCODING"] = "utf-8"

        handle = (self.log_dir / f"{name}.log").open("w", encoding="utf-8", errors="replace")
        self._log_files.append(handle)
        return subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", module],
            cwd=REPO_ROOT,
            env=env,
            # Xe ảo đọc lệnh điều khiển từ stdin; DEVNULL cho EOF ngay và
            # `_console_loop` thoát êm — xem docstring của nó ở src/vehicle_sim/__main__.py.
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )

    def start_simulator(self) -> None:
        self._simulator = self._spawn("src.vehicle_sim", "simulator")

    def stop_simulator(self) -> None:
        """Giết cứng, cố ý.

        Trên Windows `terminate()` là `TerminateProcess` — không chạy handler nào.
        Đó chính là điều ta muốn ở test D4: xe ảo *chết*, không phải *tắt lịch sự*,
        nên nó không kịp publish `health.online=false` và backend phải tự nhận ra
        qua heartbeat cũ dần.
        """
        if self._simulator is None:
            return
        self._simulator.terminate()
        self._simulator.wait(timeout=15)
        self._simulator = None

    def start_backend(self) -> None:
        # `src.serve`, KHÔNG phải `uvicorn src.main:app`: trên Windows uvicorn chọn
        # ProactorEventLoop, loop đó thiếu add_reader/remove_writer mà paho-mqtt cần,
        # nên mọi kết nối MQTT nổ NotImplementedError. Xem src/serve.py.
        self._backend = self._spawn("src.serve", "backend")

    def close(self) -> None:
        self.http.close()
        for process in (self._backend, self._simulator):
            if process is None:
                continue
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        for handle in self._log_files:
            handle.close()

    # -- quan sát ------------------------------------------------------------

    def log_tail(self, name: str, lines: int = 25) -> str:
        path = self.log_dir / f"{name}.log"
        if not path.exists():
            return f"(không có {path})"
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

    def components(self) -> dict[str, str]:
        """Trạng thái từng component của `/healthz`.

        Thân 200 và thân 503 có shape **khác nhau** — cùng cách xử lý mà
        `scripts/smoke_mqtt.py` dùng. Không được gate trên status tổng: ở P0
        `/healthz` rất có thể là 503 vì `rag_index` chưa build, mà điều đó không
        nói gì về MQTT.
        """
        response = self.http.get(HEALTHZ_URL)
        body = response.json()
        raw = body["data"]["components"] if response.status_code == 200 else body["error"]["details"]["dependencies"]
        return {name: component["status"] for name, component in raw.items()}

    def vehicle_state(self) -> dict[str, Any]:
        response = self.http.get("/vehicle/state")
        assert response.status_code == 200, f"/vehicle/state trả {response.status_code}: {response.text}"
        return response.json()["data"]["vehicle_state"]

    def wait_until_both_ready(self, *, timeout: float = STARTUP_TIMEOUT_S) -> float:
        started = time.monotonic()

        def ready() -> dict[str, str] | None:
            components = self.components()
            if components.get("mqtt") == "ready" and components.get("vehicle_simulator") == "ready":
                return components
            return None

        try:
            _wait_until(ready, timeout=timeout, description="backend chưa thấy mqtt + vehicle_simulator ready")
        except AssertionError as exc:
            raise AssertionError(
                f"{exc}\n\n--- backend.log ---\n{self.log_tail('backend')}"
                f"\n\n--- simulator.log ---\n{self.log_tail('simulator')}"
            ) from exc
        return time.monotonic() - started


async def _clear_retained(vehicle_id: str) -> None:
    """Xoá retained message của xe test.

    Broker bật `persistence true` nên retained sống qua restart; không dọn thì mỗi
    lần chạy để lại một xe ma trong cây topic. Phải dùng identity **simulator** —
    ACL cấm backend ghi lên `state/*` và `health`.
    """
    settings = get_settings()
    client = AiomqttClient(
        settings.mqtt_url,
        client_id=f"l3-cleanup-{vehicle_id}",
        username=settings.mqtt_simulator_username or None,
        password=settings.simulator_password() or None,
    )
    await client.start()
    topics = [mqtt_topics.health(vehicle_id), mqtt_topics.snapshot(vehicle_id)]
    topics += [mqtt_topics.domain_state(vehicle_id, domain) for domain in DOMAINS]
    try:
        for topic in topics:
            await client.publish(topic, None, qos=1, retain=True)
        await asyncio.sleep(0.2)
    finally:
        await client.stop()


@pytest.fixture(scope="module")
def l3_stack(tmp_path_factory):
    """Một lần khởi cho cả file — dựng hai tiến trình tốn hàng chục giây.

    Xe ảo lên **trước** backend, đúng thứ tự của `docs/devops.md` §Planned startup:
    backend nối broker rồi mới đọc snapshot retained, nên khởi ngược lại chỉ làm
    lần poll đầu thấy `no_snapshot_yet` một cách vô ích.
    """
    stack = L3Stack(tmp_path_factory.mktemp("l3"))
    try:
        stack.start_simulator()
        stack.start_backend()
        elapsed = stack.wait_until_both_ready()
        print(f"\n[L3] hai tiến trình sẵn sàng sau {elapsed:.1f}s")
        yield stack
    finally:
        stack.close()
        asyncio.run(_clear_retained(VEHICLE_ID))


# -- helper HTTP --------------------------------------------------------------


def _login(stack: L3Stack) -> str:
    response = stack.http.post(
        "/auth/login",
        headers=_SCHEMA_HEADERS,
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


def _create_session(stack: L3Stack, token: str, key: str) -> str:
    response = stack.http.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS, "Idempotency-Key": key},
        json={"vehicle_id": VEHICLE_ID},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["session_id"]


def _post_text(stack: L3Stack, token: str, session_id: str, key: str, text: str) -> httpx.Response:
    return stack.http.post(
        "/turns/text",
        headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS, "Idempotency-Key": key},
        json={"session_id": session_id, "text": text},
    )


def _bearer_subprotocol(token: str) -> str:
    """Cùng phép mã hoá `frontend/src/lib/services/shared/ws.ts` dùng.

    Không import từ `tests/test_api/ws_helpers.py`: helper bên đó gắn với
    `TestClient` (trả kwargs mà `websocket_connect` hiểu), còn ở đây là client
    WebSocket thật với tham số khác hẳn. Chỉ đúng phép mã hoá là dùng chung được.
    """
    encoded = base64.urlsafe_b64encode(token.encode("utf-8")).rstrip(b"=").decode("ascii")
    return f"bearer.{encoded}"


def _drain_until(ws, wanted_type: str, *, timeout: float = 30.0) -> list[dict]:
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            events.append(json.loads(ws.recv(timeout=remaining)))
        except TimeoutError:
            break
        if events[-1]["type"] == wanted_type:
            return events
    raise AssertionError(
        f"quá {timeout:.0f}s mà không thấy event {wanted_type!r}. "
        f"Đã nhận {len(events)}: {[event['type'] for event in events]}"
    )


# -- AC1: chuỗi lệnh xuyên hai tiến trình -------------------------------------


def test_lenh_dieu_khien_di_qua_hai_tien_trinh_va_state_doi(l3_stack):
    """Lệnh HTTP → backend → broker thật → **tiến trình khác** → state quay về backend.

    Tầng L1/L2 đã chứng minh chuỗi này, nhưng luôn với simulator sống trong cùng
    process pytest. Ở đây không object nào được chia sẻ giữa hai đầu: thứ duy nhất
    nối chúng là broker.
    """
    token = _login(l3_stack)
    session_id = _create_session(l3_stack, token, "l3:session:001")
    before = l3_stack.vehicle_state()["hvac"]["temperature_c"]
    target = 22 if before != 22 else 26

    response = _post_text(l3_stack, token, session_id, "l3:turn:hvac", f"Đặt điều hòa {target} độ")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "completed", data

    state = _wait_until(
        lambda: l3_stack.vehicle_state() if l3_stack.vehicle_state()["hvac"]["temperature_c"] == target else None,
        timeout=15.0,
        description=f"backend chưa thấy hvac.temperature_c = {target}",
    )
    assert state["hvac"]["temperature_c"] == target
    # Xe ảo tăng version cho mỗi transition; backend chỉ chuyển tiếp, không tự chế.
    assert state["state_version"] > 0


# -- AC3: WebSocket thật, không phải TestClient --------------------------------


def test_ws_ivi_that_nhan_du_vong_doi_luot(l3_stack):
    """`TestClient` là shim in-process; nó không chứng minh gì về tầng WS thật.

    Ở đây là handshake WebSocket thật qua socket: subprotocol `vivi.v1` +
    `bearer.<token>`, header `Origin`, và server phải chỉ chọn lại `vivi.v1`
    (`api_spec.md:505`).
    """
    token = _login(l3_stack)
    session_id = _create_session(l3_stack, token, "l3:session:002")

    with ws_connect(
        f"{WS_URL}/ws/ivi",
        subprotocols=["vivi.v1", _bearer_subprotocol(token)],  # type: ignore[list-item]
        additional_headers={"Origin": ORIGIN},
        open_timeout=15,
    ) as ws:
        assert ws.protocol.subprotocol == "vivi.v1"
        ws.send(
            json.dumps(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_l3_1",
                    "sent_at": "2026-08-11T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": session_id,
                }
            )
        )

        # `/turns/text` đồng bộ: khi nó trả về, mọi event của lượt đã nằm sẵn trong
        # buffer của socket. Gửi trước rồi đọc, không cần thread nào.
        response = _post_text(l3_stack, token, session_id, "l3:turn:ws", "Đặt điều hòa 24 độ")
        assert response.status_code == 200, response.text

        events = _drain_until(ws, "turn.completed")

    types = [event["type"] for event in events]
    # `ui.policy` là event mức **kết nối**, không thuộc vòng đời lượt: nó phát ngay
    # khi client nối vào và mỗi khi sáu cờ an toàn đổi (PR #77). Nên lọc nó ra trước
    # khi kiểm thứ tự, thay vì viết cứng "phần tử 0 là ui.policy" — viết cứng thì
    # thêm một event mức kết nối nữa là lại đỏ, mà test này nói về vòng đời lượt.
    lifecycle = [t for t in types if t != "ui.policy"]
    # `/turns/text` là route ĐỒNG BỘ nên nó **không** phát `turn.accepted` — chỉ
    # `/turns/voice` (202, chạy nền) mới có. Cùng lý do `TraceCollector` không tự
    # mở bản ghi cho lượt text mà `submit_text_turn` phải mở thẳng vào kho; xem
    # tests/test_api/test_trace_end_to_end.py mục "POST /turns/text".
    assert lifecycle[0] == "plan.ready", types
    assert lifecycle[-1] == "turn.completed", types
    assert "tool.result" in lifecycle, types
    # `sequence` thuộc về PHIÊN và tăng đơn điệu (ADR-014).
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences), sequences
    assert len(set(sequences)) == len(sequences), f"sequence trùng lặp: {sequences}"
    assert {event["session_id"] for event in events} == {session_id}


# -- readiness thật ------------------------------------------------------------


def test_healthz_bao_ready_khi_ca_hai_tien_trinh_song(l3_stack):
    """Hai probe này chỉ có ý nghĩa khi dependency là thật.

    Ở tầng dưới chúng chạy trên `InMemoryBroker` và một simulator cùng process —
    tức chưa bao giờ kiểm đường xác thực thật hay heartbeat qua dây thật.
    """
    components = l3_stack.components()

    assert components["mqtt"] == "ready", components
    assert components["vehicle_simulator"] == "ready", components
    # `llm` được miễn trừ khỏi readiness gate ở P0 (issue #48) nhưng vẫn phải
    # xuất hiện với trạng thái thật — miễn trừ khỏi gate, không phải giấu đi.
    #
    # Từ issue #95 trạng thái đó là `disabled`, không còn là `down`:
    # `slm_enabled=false` là **tắt có chủ ý**, khác với một dependency hỏng
    # (`src/services/health.py:199`, detail `slm_disabled`). Dòng này giữ `"down"`
    # tới 2026-08-15 vì tier L3 không chạy trên CI, nên #95 merge mà nó không đỏ —
    # đúng loại trôi mà một tier chạy tay sinh ra.
    assert components["llm"] == "disabled", components


# -- khởi động lại xe ảo -------------------------------------------------------


def test_xe_ao_chet_thi_healthz_thay_va_hoi_lai_sau_khi_song(l3_stack):
    """Chuỗi `process chết → heartbeat cũ dần → probe đổi → /healthz đổi`.

    Không dàn dựng được trong một process, và là ca duy nhất trong file này bắt
    buộc phải có hai tiến trình thật.

    Giết cứng chứ không tắt lịch sự: xe ảo không kịp publish `health.online=false`,
    nên backend phải tự nhận ra qua `mqtt_heartbeat_stale_s` (15s) chứ không nhờ
    ai báo. Chờ tới 45s vì LWT theo keepalive 30s có thể tới trước — cái nào tới
    trước cũng đúng, ta chỉ khẳng định **nó phải tới**.

    VỊ TRÍ CỦA CA NÀY LÀ MỘT KHẲNG ĐỊNH. Nó chạy **trước** ca S2, và điều đó chỉ
    đúng được nhờ một bản sửa: lúc mới viết, ca này để lại hệ thống ở trạng thái
    điều khiển hỏng trong khi mọi tín hiệu readiness đều xanh, nên nó phải nằm cuối
    file để không kéo ca khác đổ theo.

        `VehicleSimulator` luôn khởi tạo ở `state_version=1`
        (`src/vehicle_sim/state.py::initial_state`), trong khi
        `VehicleStateCache._on_snapshot` bỏ qua mọi snapshot có version thấp hơn
        version đang giữ. Guard đó đúng cho message MQTT tới trễ, nhưng không phân
        biệt được "message cũ về muộn" với "xe ảo restart, bộ đếm reset". Backend
        giữ version cũ, mọi `expected_state_version` đều lệch, xe ảo từ chối bằng
        `stale_state` — trong khi `/healthz` vẫn xanh.

    Đã sửa ở `VehicleStateCache._forget_state_if_restarted` (+
    `MqttVehicleGateway._reset_floor_if_simulator_restarted` cho biểu hiện thứ hai),
    khoá bằng `tests/test_vehicle/test_vehicle_state_cache_restart.py`. Nếu ai đó
    làm hồi quy bản sửa đó, ca S2 dưới đây đỏ — và đó là lý do **đừng** chuyển ca
    này về cuối file cho "an toàn": đúng thứ tự này mới là thứ đang canh.

    Phát hiện lúc viết chính tầng này: ca S2 pass khi chạy riêng, fail khi chạy sau
    ca này. L1/L2 không bao giờ khởi động lại một tiến trình simulator nên về cấu
    trúc không thể thấy nó.
    """
    assert l3_stack.components()["vehicle_simulator"] == "ready", "tiền đề sai — xe ảo chưa ready"

    l3_stack.stop_simulator()
    try:
        _wait_until(
            lambda: l3_stack.components()["vehicle_simulator"] != "ready",
            timeout=HEARTBEAT_FLIP_TIMEOUT_S,
            description="backend vẫn báo vehicle_simulator=ready dù tiến trình xe ảo đã chết",
        )
        # Không phục vụ state cũ như thể còn tươi — ADR-013 fail-closed.
        assert l3_stack.http.get("/vehicle/state").status_code == 503
    finally:
        l3_stack.start_simulator()

    _wait_until(
        lambda: l3_stack.components()["vehicle_simulator"] == "ready",
        timeout=HEARTBEAT_FLIP_TIMEOUT_S,
        description="xe ảo khởi lại rồi mà backend vẫn chưa thấy ready",
    )
    assert l3_stack.http.get("/vehicle/state").status_code == 200


# -- HITL xuyên hai tiến trình -------------------------------------------------


def test_luot_s2_can_duyet_di_qua_hai_tien_trinh(l3_stack):
    """Luồng đầu bài: lệnh S2 → chờ duyệt → duyệt → xe ảo thật thi hành.

    Chưa từng chạy end-to-end với tiến trình thật. Điểm đáng kiểm nhất là
    `approved_vehicle_state_version` — nó phải là version **thật** của xe ảo lúc
    lập kế hoạch; sai version thì HITL fail-closed và không có gì xảy ra cả, mà
    trong một process thì version hay tình cờ đúng.
    """
    token = _login(l3_stack)
    session_id = _create_session(l3_stack, token, "l3:session:003")
    before = l3_stack.vehicle_state()["windows"]["front_left"]
    target = 30 if before != 30 else 60

    response = _post_text(l3_stack, token, session_id, "l3:turn:s2", f"Mở cửa sổ bên lái {target} phần trăm")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "waiting_approval", data
    assert data["action_plan"]["requires_approval"] is True
    approval_id = data["pending_approval"]["approval_id"]

    decision = l3_stack.http.post(
        f"/approvals/{approval_id}/decision",
        # `Idempotency-Key` bắt buộc từ PR #44 (`3df1ced`, 2026-08-12). Test này sửa
        # lần cuối hôm trước đó nên thiếu header, và vì cả tầng L3 mặc định bị skip
        # (`MQTT_L3_TESTS=1`) nên không ai chạy để thấy — hỏng im lặng suốt từ đó.
        headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS, "Idempotency-Key": "l3:decision:s2"},
        json={
            "decision": "approve",
            "approved_vehicle_state_version": data["action_plan"]["vehicle_state_version"],
        },
    )
    assert decision.status_code == 200, decision.text
    assert decision.json() == {"approval_status": "approved"}

    # Thực thi chạy nền sau khi duyệt (api_spec.md:209), nên phải chờ chứ không
    # đọc ngay — và chờ có deadline.
    state = _wait_until(
        lambda: l3_stack.vehicle_state() if l3_stack.vehicle_state()["windows"]["front_left"] == target else None,
        timeout=20.0,
        description=f"xe ảo chưa mở cửa sổ tới {target}% sau khi duyệt",
    )
    assert state["windows"]["front_left"] == target

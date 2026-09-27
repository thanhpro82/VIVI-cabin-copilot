"""`/ws/engineer` phát đủ 5 loại event của `docs/api_spec.md:602-612`.

Trước ticket này chỉ có `state` và `error`; `trace`/`metrics`/`health` thiếu, nên
Engineer Dashboard trắng dù WS kết nối thành công
(`docs/handoff/frontend-integration-map.md:99`).
"""

from __future__ import annotations

import anyio
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.engineer_events import EngineerEventBus, EngineerSampler, get_engineer_bus
from src.services.trace_store import TraceStore, set_trace_store
from tests.test_api.ws_helpers import engineer_connect_kwargs, receive_n

HELLO = {
    "type": "connection.init",
    "client_message_id": "cmsg_1",
    "sent_at": "2026-08-10T00:00:00Z",
    "schema_version": "1.0",
}


@pytest.fixture
def store():
    store = TraceStore(maxsize=16)
    set_trace_store(store)
    return store


#: `collect_health` nạp model STT thật ở lần đầu — bounded bởi
#: `health_probe_timeout_s` cho mỗi probe nhưng `asyncio.wait_for` không huỷ được
#: thread đang chạy, nên thực tế lâu hơn 5s mặc định của `receive_n`.
HEALTH_TIMEOUT = 60.0


def wait_for(ws, event_type: str, *, skip_limit: int = 6) -> dict:
    """Đọc tới khi gặp `event_type`.

    Không khẳng định vị trí cố định: `metrics` đến từ cả handshake lẫn sampler, nên
    số event đứng trước `health` phụ thuộc nhịp — khoá vị trí sẽ ra test giòn.
    """
    for _ in range(skip_limit):
        event = receive_n(ws, 1, timeout=HEALTH_TIMEOUT)[0]
        if event["type"] == event_type:
            return event
    raise AssertionError(f"không thấy event {event_type!r} sau {skip_limit} sự kiện")


def test_phat_state_va_metrics_ngay_khi_ket_noi(store):
    """Handshake chỉ làm việc rẻ.

    `health` KHÔNG nằm ở đây có chủ ý — `collect_health` chạy 8 probe thật; đặt nó
    trên đường handshake thì `connection.init` treo hàng chục giây. Sampler bắn nó
    ngay vòng đầu trong task riêng.
    """
    with TestClient(app) as client, client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
        ws.send_json(HELLO)
        events = receive_n(ws, 2)

    assert [event["type"] for event in events] == ["state", "metrics"]


def test_phat_du_ca_nam_loai_event(store):
    """`api_spec.md:602-612` — allowlist 5 loại. Trước ticket này chỉ có 2."""
    with TestClient(app) as client, client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
        ws.send_json(HELLO)
        events = receive_n(ws, 2)

        async def publish_trace():
            await get_engineer_bus().publish("trace", {"trace_id": "tr_1", "status": "completed"})

        ws.portal.call(publish_trace)
        # `health` đến từ sampler và có thể tới trước hoặc sau `trace`; giữ đọc
        # tới khi thấy đủ cả hai thay vì dừng ngay ở event `health` đầu tiên.
        for _ in range(6):
            if {"trace", "health"} <= {event["type"] for event in events}:
                break
            events.append(receive_n(ws, 1, timeout=HEALTH_TIMEOUT)[0])

    assert {"state", "metrics", "trace", "health"} <= {event["type"] for event in events}
    # `sequence` tăng đơn điệu XUYÊN mọi loại — api_spec.md:535. Một bộ đếm cho cả
    # luồng, không phải mỗi loại một bộ.
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


def test_moi_event_co_du_vo_bat_buoc(store):
    with TestClient(app) as client, client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
        ws.send_json(HELLO)
        events = receive_n(ws, 2)

    for event in events:
        assert set(event) >= {
            "type",
            "event_id",
            "sequence",
            "trace_id",
            "emitted_at",
            "schema_version",
            "payload",
        }
        # Engineer không gắn phiên — api_spec.md:531 bỏ `session_id` khỏi init.
        assert "session_id" not in event


def test_health_dung_shape_200_ke_ca_khi_co_component_down(store):
    """`api_spec.md:609` chốt payload `health` khớp **health GET schema**.

    Nhánh 503 của REST có shape khác hẳn (`error.details.dependencies`, không
    `latency_ms`); đó là đường riêng của HTTP. `frontend/.../engineer/real.ts`
    `mapHealth()` đọc đường WS và cần đủ `checked_at` + `latency_ms`.

    Ở P0 `llm` không bao giờ `ready` (`slm_enabled=False`), nên đây là đường chạy
    mặc định.

    Trước issue #95 test này chốt cứng `status == "down"` — tức khoá chặt đúng cái
    bug: ở cấu hình mặc định của cả nhóm, `slm_enabled=false` và `MQTT_ENABLED=false`
    kéo readiness xuống `down` chỉ vì hai component **cố ý tắt**. Giờ nó chốt cái
    *quy tắc* thay vì một giá trị: `disabled` không kéo status, `down`/`degraded` thì
    có. Suy ra kỳ vọng từ chính payload, vì `stt`/`tts`/`rag_index` phụ thuộc model
    có sẵn trên máy chạy — chốt cứng một giá trị sẽ pass trên CI vì lý do khác hẳn
    với lý do nó pass trên máy dev.
    """
    with TestClient(app) as client, client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
        ws.send_json(HELLO)
        health = wait_for(ws, "health")["payload"]

    assert set(health) == {"status", "checked_at", "components", "faults"}
    chan = {"down", "degraded"}
    mong_doi = (
        "down" if any(c["status"] in chan for ten, c in health["components"].items() if ten != "llm") else "ready"
    )
    assert health["status"] == mong_doi
    assert health["components"]["llm"]["status"] == "disabled"
    assert set(health["components"]) == {
        "backend",
        "llm",
        "mqtt",
        "vehicle_simulator",
        "stt",
        "tts",
        "rag_index",
        "sqlite",
    }
    for component in health["components"].values():
        assert set(component) == {"status", "latency_ms"}
    assert any(fault["component"] == "llm" for fault in health["faults"])


def test_faults_khong_lo_duong_dan_hay_thong_diep_exception(store):
    """`api_spec.md:612` cấm lộ secret path ra bề mặt kỹ sư."""
    with TestClient(app) as client, client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
        ws.send_json(HELLO)
        health = wait_for(ws, "health")["payload"]

    for fault in health["faults"]:
        assert set(fault) == {"component", "status", "code"}
        assert "/" not in fault["code"]
        assert "\\" not in fault["code"]


def test_metrics_payload_du_tam_nhom(store):
    with TestClient(app) as client, client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
        ws.send_json(HELLO)
        metrics = receive_n(ws, 2)[1]["payload"]

    assert set(metrics) == {
        "window",
        "turns",
        "stage_latency_ms",
        "model_runtime",
        "mqtt",
        "rag",
        "safety",
        "action_audit",
    }
    # `by_alias=True` — nếu quên thì FE nhận `from_` và `window` vỡ.
    assert set(metrics["window"]) == {"from", "to"}


def test_message_dau_tien_sai_thi_bao_loi_roi_dong(store):
    with TestClient(app) as client, client.websocket_connect("/ws/engineer", **engineer_connect_kwargs(client)) as ws:
        ws.send_json({"type": "khong-hop-le"})
        event = receive_n(ws, 1)[0]

    assert event["type"] == "error"
    assert event["payload"]["code"] == "WS_EVENT_INVALID"
    assert event["payload"]["terminal"] is True


# -- sampler ------------------------------------------------------------------
#
# Test ở mức cơ chế, không qua WS thật: nhịp 5s/10s thật sẽ làm suite chậm và
# giòn. Cùng khuôn với `tests/test_api/test_ws_engineer_realtime.py` — bắt tay đã
# có test riêng ở trên.


async def test_sampler_dung_khi_listener_cuoi_cung_roi():
    """Không ai xem thì không được tốn 8 probe health mỗi 10 giây."""
    bus = EngineerEventBus()
    ticks = 0

    async def sample():
        nonlocal ticks
        ticks += 1
        await anyio.sleep(0.01)

    bus.set_sampler(sample)

    async def listener(event_type, payload):
        return None

    bus.add_listener(listener)
    await anyio.sleep(0.05)
    assert ticks > 0

    bus.remove_listener(listener)
    stopped_at = ticks
    await anyio.sleep(0.05)

    assert ticks == stopped_at
    assert bus.listener_count == 0


async def test_mot_listener_chet_khong_chan_cac_listener_con_lai():
    bus = EngineerEventBus()
    received = []

    async def broken(event_type, payload):
        raise RuntimeError("socket chết")

    async def healthy(event_type, payload):
        received.append(event_type)

    bus.add_listener(broken)
    bus.add_listener(healthy)
    await bus.publish("metrics", {})

    assert received == ["metrics"]


async def test_sampler_song_sot_khi_dung_payload_that_bai():
    """Một lần MQTT chớp tắt không được làm dashboard câm vĩnh viễn."""
    bus = EngineerEventBus()
    received = []

    async def failing_metrics():
        raise RuntimeError("fold hỏng")

    async def ok_health():
        return {"status": "ready"}

    sampler = EngineerSampler(bus, failing_metrics, ok_health, 0.01, 0.01)

    async def listener(event_type, payload):
        received.append(event_type)

    bus.add_listener(listener)
    await sampler()

    assert received == ["health"]

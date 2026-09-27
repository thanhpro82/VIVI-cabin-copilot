"""`GET /api/v1/traces/{trace_id}` — interface #8 của docs/api_spec.md."""

from __future__ import annotations

import pytest

from src.services.trace_store import TraceStore, set_trace_store


@pytest.fixture
def store():
    store = TraceStore(maxsize=16)
    set_trace_store(store)
    return store


def _seed(store: TraceStore, trace_id: str = "tr_seed_1") -> None:
    store.open(trace_id, "ses-1", "turn-1")
    store.record_stage(trace_id, "stt", 412.0)
    store.record_stage(trace_id, "routing", 8.0)
    store.update(
        trace_id,
        route_source="deterministic",
        confidence=0.98,
        plan_id="plan-1",
        tool_names=("set_window_position",),
        max_safety_level="S2",
        approval_id="appr-1",
        approval_expires_at="2026-08-10T10:00:30Z",
        approved_vehicle_state_version=42,
        admission_status="pending",
        status="waiting_approval",
        requires_approval=True,
    )


async def test_tra_ve_dung_vo_envelope(engineer_client, store):
    _seed(store)

    response = await engineer_client.get("/api/v1/traces/tr_seed_1")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta", "trace_id", "schema_version"}
    assert body["schema_version"] == "1.0"
    assert "request_id" in body["meta"]
    # trace của REQUEST khác trace ĐƯỢC ĐỌC — api_spec.md ví dụ tr_trace_read_001.
    assert body["trace_id"] != body["data"]["trace_id"]
    assert response.headers["X-Trace-Id"] == body["trace_id"]


async def test_data_co_dung_tap_field_cua_api_spec(engineer_client, store):
    _seed(store)

    data = (await engineer_client.get("/api/v1/traces/tr_seed_1")).json()["data"]

    assert set(data) == {
        "trace_id",
        "session_id",
        "turn_id",
        "vehicle_id",
        "status",
        "route_source",
        "confidence",
        "plan_id",
        "pending_approval",
        "safe_summary",
        "answer_text",
        "stage_latencies_ms",
        "approval_wait_ms",
        "safety_summary",
        "versions",
        "admission",
    }


async def test_ba_menh_de_has_exactly_cua_api_spec_382(engineer_client, store):
    """Ba tập field đóng. Thêm hay bớt một cái là vỡ hợp đồng với frontend."""
    _seed(store)
    data = (await engineer_client.get("/api/v1/traces/tr_seed_1")).json()["data"]

    assert set(data["stage_latencies_ms"]) == {
        "stt",
        "routing",
        "planning_or_retrieval",
        "safety",
        "tool",
        "tts",
        "end_to_end",
    }
    assert set(data["safety_summary"]) == {"outcome", "max_level", "validation", "admission", "block_code"}
    assert set(data["versions"]) == {
        "model_profile",
        "prompt",
        "tool",
        "data",
        "index",
        "planning_vehicle_state",
        "observed_vehicle_state",
    }
    assert set(data["admission"]) == {
        "status",
        "approval_id",
        "execution_group_id",
        "approved_vehicle_state_version",
        "actual_vehicle_state_version",
    }


async def test_stage_chua_do_duoc_tra_null_chu_khong_phai_0(engineer_client, store):
    """`0.0` nghĩa là "chạy hết 0ms"; "chưa đo" phải là `null`."""
    _seed(store)
    stages = (await engineer_client.get("/api/v1/traces/tr_seed_1")).json()["data"]["stage_latencies_ms"]

    assert stages["stt"] == 412.0
    assert stages["planning_or_retrieval"] is None
    assert stages["tool"] is None


async def test_model_profile_la_not_selected_o_p0(engineer_client, store):
    """`slm_enabled=False` + ADR-005 "Not Yet" — bịa profile ở đây là bịa bằng chứng."""
    _seed(store)
    versions = (await engineer_client.get("/api/v1/traces/tr_seed_1")).json()["data"]["versions"]

    assert versions["model_profile"] == "not-selected"
    assert versions["prompt"] == "none-deterministic"


async def test_pending_approval_hien_khi_dang_cho_duyet(engineer_client, store):
    _seed(store)
    data = (await engineer_client.get("/api/v1/traces/tr_seed_1")).json()["data"]

    assert data["pending_approval"] == {
        "approval_id": "appr-1",
        "expires_at": "2026-08-10T10:00:30Z",
    }
    assert data["status"] == "waiting_approval"
    assert data["admission"]["approved_vehicle_state_version"] == 42


async def test_pending_approval_bien_mat_sau_khi_chot(engineer_client, store):
    _seed(store)
    store.seal("tr_seed_1", status="completed", admission_status="executed")

    data = (await engineer_client.get("/api/v1/traces/tr_seed_1")).json()["data"]

    assert data["pending_approval"] is None
    assert data["admission"]["status"] == "executed"


async def test_trace_la_tra_404_not_found(engineer_client, store):
    response = await engineer_client.get("/api/v1/traces/tr_khong_ton_tai")

    assert response.status_code == 404
    body = response.json()
    # Envelope lỗi canonical ở TOP-LEVEL, không lồng trong `detail` — api_spec.md:24.
    assert set(body) == {"error", "meta", "trace_id", "schema_version"}
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["retryable"] is False


async def test_safe_summary_khong_bao_gio_chua_van_ban_nguoi_dung(engineer_client, store):
    """Điểm rò duy nhất khả dĩ — api_spec.md:382 cấm "unrestricted transcripts"."""
    _seed(store)
    data = (await engineer_client.get("/api/v1/traces/tr_seed_1")).json()["data"]

    assert data["safe_summary"] == "Chờ xác nhận 1 thao tác cửa kính"

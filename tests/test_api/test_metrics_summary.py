"""`GET /api/v1/metrics/summary` — interface #9, và quy tắc cửa sổ rỗng."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.config import get_settings
from src.models.observability import iso_z
from src.models.vehicle import utc_now
from src.services.metrics import build_metrics_summary, percentile
from src.services.trace_store import TraceStore, set_trace_store

#: 8 nhóm theo api_spec.md:608. `docs/handoff/frontend-integration-map.md:163` ghi 7
#: (bỏ `model_runtime`) — bản canonical là api_spec.md.
EXPECTED_GROUPS = {
    "window",
    "turns",
    "stage_latency_ms",
    "model_runtime",
    "mqtt",
    "rag",
    "safety",
    "action_audit",
}


@pytest.fixture
def store():
    store = TraceStore(maxsize=64)
    set_trace_store(store)
    return store


def _turn(store: TraceStore, trace_id: str, **changes) -> None:
    store.open(trace_id, "ses-1", f"turn-{trace_id}")
    if changes:
        store.update(trace_id, **changes)


async def test_tra_du_tam_nhom(engineer_client, store):
    body = (await engineer_client.get("/api/v1/metrics/summary")).json()

    assert set(body) == {"data", "meta", "trace_id", "schema_version"}
    assert set(body["data"]) == EXPECTED_GROUPS


async def test_cua_so_rong_dem_0_nhung_moi_ti_le_va_percentile_la_null(engineer_client, store):
    """`api_spec.md:464` — `0` sẽ vẽ biểu đồ phẳng nói dối, tệ hơn ô trống."""
    data = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]

    assert data["turns"] == {"accepted": 0, "completed": 0, "failed": 0, "canceled": 0}
    for stage in data["stage_latency_ms"].values():
        assert stage["count"] == 0
        assert stage["p50"] is None
        assert stage["p95"] is None
    assert data["mqtt"]["error_rate"] is None
    assert data["rag"]["grounded_rate"] is None
    assert data["rag"]["abstention_rate"] is None
    assert data["model_runtime"]["rss_mib"] == {"sample_count": 0, "current": None, "peak": None}


async def test_faithfulness_luon_null_o_runtime(engineer_client, store):
    """`api_spec.md:460` cấm rõ "never an unreviewed live-model self-score"."""
    rag = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["rag"]

    assert rag["faithfulness_evaluated"] == 0
    assert rag["faithfulness_pass_rate"] is None


async def test_window_dung_khoa_from_chu_khong_phai_from_(engineer_client, store):
    window = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["window"]

    assert set(window) == {"from", "to"}
    assert window["from"].endswith("Z")
    assert window["to"].endswith("Z")


async def test_route_khong_nhan_query_param_ngoai_spec(engineer_client, store):
    """api_spec.md:384-466 không định nghĩa `?from=`/`?to=` nào.

    FastAPI bỏ qua query param không khai, nên gọi có param vẫn 200 — điều test này
    khoá là **cửa sổ không đổi theo param**, tức server vẫn tự chọn.
    """
    plain = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["window"]
    with_param = (await engineer_client.get("/api/v1/metrics/summary?from=2020-01-01T00:00:00Z")).json()["data"][
        "window"
    ]

    assert plain["from"] == with_param["from"]


async def test_turns_accepted_dem_luot_mo_con_lai_dem_luot_chot(engineer_client, store):
    """`api_spec.md:456`: "in-flight accepted turns need not equal terminal totals"."""
    _turn(store, "tr_1", status="completed")
    _turn(store, "tr_2", status="failed")
    _turn(store, "tr_3", status="waiting_approval")

    turns = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["turns"]

    assert turns == {"accepted": 3, "completed": 1, "failed": 1, "canceled": 0}


async def test_action_audit_khong_tinh_buoc_bi_skip_vao_attempted(engineer_client, store):
    """`api_spec.md:462`: skipped steps "are separate and not in that denominator"."""
    _turn(
        store,
        "tr_1",
        status="completed",
        step_statuses=("completed", "failed", "skipped_due_to_prior_failure"),
    )

    audit = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["action_audit"]

    assert audit["attempted"] == 2
    assert audit["completed"] == 1
    assert audit["failed"] == 1
    assert audit["skipped_prior_failure"] == 1


async def test_mqtt_error_rate_tinh_tren_publish_attempts(engineer_client, store):
    _turn(
        store,
        "tr_1",
        status="completed",
        step_statuses=("completed", "completed", "failed"),
        step_latencies_ms=(10.0, 30.0, 0.0),
    )

    mqtt = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["mqtt"]

    assert mqtt["publish_attempts"] == 3
    assert mqtt["published"] == 2
    assert mqtt["errors"] == 1
    assert mqtt["error_rate"] == pytest.approx(0.3333, abs=1e-4)
    # Chỉ bước thành công vào latency — api_spec.md:458.
    assert mqtt["latency_ms"]["count"] == 2


async def test_rag_grounded_va_abstention_theo_dung_mau_so(engineer_client, store):
    _turn(store, "tr_1", status="completed", outcome="grounded_answer", citation_count=2)
    _turn(store, "tr_2", status="completed", outcome="grounded_answer", citation_count=1)
    _turn(store, "tr_3", status="completed", outcome="grounded_refusal")

    rag = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["rag"]

    assert rag["answered"] == 2
    assert rag["grounded"] == 2
    assert rag["abstained"] == 1
    assert rag["grounded_rate"] == 1.0
    # abstained / (answered + abstained), không phải / accepted.
    assert rag["abstention_rate"] == pytest.approx(1 / 3, abs=1e-4)


async def test_safety_dem_theo_outcome_va_admission(engineer_client, store):
    _turn(store, "tr_1", status="completed", admission_status="blocked", block_code="SAFETY_BLOCKED")
    _turn(store, "tr_2", status="canceled", outcome="approval_expired", requires_approval=True)
    _turn(store, "tr_3", status="completed", admission_status="executed", requires_approval=True)

    safety = (await engineer_client.get("/api/v1/metrics/summary")).json()["data"]["safety"]

    assert safety["blocked_s3"] == 1
    assert safety["approvals_required"] == 2
    assert safety["approved"] == 1
    assert safety["expired"] == 1


# -- Biên cửa sổ (issue #67) --------------------------------------------------


def test_luot_mo_dung_thoi_diem_truy_van_van_duoc_dem(store):
    """Bản ghi có `opened_at == now` phải nằm TRONG cửa sổ, không bị vứt.

    Bug gốc: `window_bounds` trả biên phải bằng đúng `now`, còn `records_between` lọc
    nửa mở `start <= opened_at < end`, nên một lượt vừa mở xong bị loại. Nó chỉ nổ khi
    đồng hồ đủ thô để hai mốc bằng nhau — Windows + Python 3.11 (đúng phiên bản cả hai
    workflow CI pin) nhảy ~1 ms một lần và trả cùng một giá trị cho 3000 lời gọi liên
    tiếp. Đo được 200/200 bản ghi vừa tạo bị vứt.

    ÉP `now = opened_at` THAY VÌ TRÔNG CHỜ ĐỒNG HỒ THÔ. Trên máy có `datetime.now()`
    phân giải µs (Python 3.13, hoặc Linux CI) va chạm đó gần như không bao giờ xảy ra,
    nên một test dựa vào thời gian thật sẽ xanh ở CI và chỉ đỏ trên máy của một người —
    đúng cách lỗi này sống sót qua 6 PR dưới nhãn "flaky, không liên quan tới diff".
    Ép mốc vào thì test tất định trên mọi nền tảng và mọi phiên bản Python.
    """
    record = store.open("tr_1", "ses-1", "turn-1")

    data = build_metrics_summary(store, get_settings(), record.opened_at)

    assert data.turns.accepted == 1


def test_cua_so_neo_vao_luc_kho_bat_dau_thu_chu_khong_phai_luc_import_module():
    """`window.from` bám `TraceStore.created_at`.

    Trước đây mốc chặn là `metrics._BOOT_AT`, chốt lúc **import module**. Test gọi
    `reset_trace_store()` liên tục nên kho mới sinh ra suốt, trong khi cửa sổ vẫn neo
    vào mốc import của process — tức báo một cửa sổ dài hơn quãng thời gian kho thật sự
    tồn tại. Test này không viết được trước khi mốc đó chuyển vào kho.

    ĐẨY `created_at` LÙI 10 PHÚT thay vì dùng kho vừa tạo: `iso_z` cắt tới **giây**, nên
    mốc import module và lúc tạo kho chỉ cách nhau vài mili-giây sẽ render ra cùng một
    chuỗi — test sẽ xanh kể cả khi cửa sổ vẫn neo nhầm vào mốc module. Đã kiểm bằng
    mutation: phiên bản đầu của test này không bắt được lỗi vì đúng lý do đó.
    """
    store = TraceStore(maxsize=8)
    store.created_at = utc_now() - timedelta(minutes=10)
    now = store.created_at + timedelta(seconds=30)

    window = build_metrics_summary(store, get_settings(), now).window

    assert window.from_ == iso_z(store.created_at)


def test_percentile_nearest_rank_tren_mau_nho():
    """Spec không định nghĩa thuật toán; khoá lựa chọn để p95 tái lập được."""
    assert percentile([], 50) is None
    assert percentile([5.0], 50) == 5.0
    assert percentile([5.0], 95) == 5.0
    # n=4, p50 → ceil(0.5*4)-1 = 1 → phần tử thứ hai.
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0


def test_stage_latency_bo_qua_luot_chua_di_qua_stage(store):
    """Lượt không chạy RAG không được kéo p50 của `planning_or_retrieval` về 0."""
    store.open("tr_1", "ses-1", "turn-1")
    store.record_stage("tr_1", "planning_or_retrieval", 30.0)
    store.open("tr_2", "ses-1", "turn-2")  # không đi qua RAG

    data = build_metrics_summary(store, get_settings())

    assert data.stage_latency_ms["planning_or_retrieval"].count == 1
    assert data.stage_latency_ms["planning_or_retrieval"].p50 == 30.0

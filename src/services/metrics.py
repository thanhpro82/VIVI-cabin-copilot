"""Aggregate an toàn cho `GET /metrics/summary` và event `metrics` của `/ws/engineer`.

Hàm thuần, **không giữ counter nào**: mọi con số fold từ `TraceStore`. Đó là cách
hiện thực yêu cầu "không tạo state song song" — một kho, ba khung nhìn. Thêm metric
mới về sau là thêm một phép fold ở đây, không phải nhớ tăng biến đếm ở năm chỗ.

Hình dạng chốt ở `docs/api_spec.md:386-466`, bảng producer/denominator ở `:454-462`.

BA QUYẾT ĐỊNH KHI SPEC IM LẶNG (ghi ở docs/tasks/TASK-BE-OBS-001 §4):

1. **Cửa sổ là rolling** `[max(store.created_at, now−METRICS_WINDOW_SECONDS), now]`,
   hiện thực dưới dạng nửa mở với biên phải `now + 1µs`. Spec chốt `[from,to)` nửa mở
   UTC nhưng không nói rolling/since-boot và không định nghĩa query param nào, nên
   endpoint không nhận `?from=&to=`.

   Hai chi tiết của biên **không** phải tuỳ tiện, xem `window_bounds`: chặn dưới neo
   vào lúc **kho** bắt đầu thu (không phải lúc import module), và chặn trên phải bao
   gồm chính thời điểm truy vấn — issue #67.
2. **Percentile nearest-rank**, `index = ceil(p/100 × n) − 1`. Spec không định
   nghĩa thuật toán; không ghi thì p95 trên mẫu nhỏ không tái lập được.
3. **`mqtt` là xấp xỉ** — xem docstring `_mqtt`.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from src.config import Settings
from src.models.observability import (
    ActionAudit,
    MetricsSummaryData,
    MetricsWindow,
    ModelRuntime,
    MqttMetrics,
    RagMetrics,
    RssStat,
    SafetyMetrics,
    StageStat,
    TurnCounts,
    iso_z,
)
from src.services.trace_store import STAGE_NAMES, TraceRecord, TraceStore

#: Đơn vị nhỏ nhất `datetime` biểu diễn được. Dùng để đẩy biên phải của cửa sổ tới
#: **instant kế tiếp** sau `now` — xem `window_bounds`.
_ONE_TICK = timedelta(microseconds=1)

#: `_wire_tool_status` của `ivi_events.py` → field trong `action_audit`.
_AUDIT_FIELD_BY_STATUS = {
    "completed": "completed",
    "failed": "failed",
    "timeout": "timeout",
    "skipped_due_to_prior_failure": "skipped_prior_failure",
    "skipped_external_state_change": "skipped_external_state_change",
}

#: `turn.canceled.reason` → field trong `safety` (api_spec.md:428).
_SAFETY_FIELD_BY_CANCEL_REASON = {
    "approval_rejected": "rejected",
    "approval_expired": "expired",
    "approval_invalidated_state": "invalidated_state",
    "approval_invalidated_plan": "invalidated_plan",
    "approval_predicate_failed": "predicate_failed",
}


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank. `None` khi không có mẫu — **không phải `0`**.

    `api_spec.md:464`: "every percentile and rate is JSON `null`" cho cửa sổ rỗng.
    Trả `0` sẽ vẽ ra một biểu đồ phẳng nói dối, tệ hơn hẳn một ô trống;
    `frontend/src/lib/services/engineer/real.ts:41` đã khai đúng `p50: number|null`.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return round(ordered[index], 3)


def _ratio(numerator: int, denominator: int) -> float | None:
    """Tỉ lệ 0..1, hoặc `None` khi mẫu số bằng 0.

    Không bao giờ trả `0.0` cho mẫu số rỗng: "0% có căn cứ" và "chưa có case nào"
    là hai điều khác nhau, và `api_spec.md:464` bắt phân biệt chúng.
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _stage_stat(values: list[float]) -> StageStat:
    return StageStat(count=len(values), p50=percentile(values, 50), p95=percentile(values, 95))


def _turns(records: list[TraceRecord]) -> TurnCounts:
    """`accepted` đếm lượt **mở** trong cửa sổ; ba cái còn lại đếm lượt **chốt**.

    Nên `accepted != completed + failed + canceled` là bình thường, không phải lỗi
    — `api_spec.md:456` nói rõ "in-flight accepted turns need not equal terminal
    totals".
    """
    counts = TurnCounts(accepted=len(records))
    for record in records:
        if record.status in ("completed", "failed", "canceled"):
            setattr(counts, record.status, getattr(counts, record.status) + 1)
    return counts


def _stage_latency(records: list[TraceRecord]) -> dict[str, StageStat]:
    buckets: dict[str, list[float]] = {name: [] for name in STAGE_NAMES}
    for record in records:
        for name, value in record.stages.as_dict().items():
            if value is not None:
                buckets[name].append(value)
    return {name: _stage_stat(values) for name, values in buckets.items()}


def _model_runtime(settings: Settings) -> ModelRuntime:
    """P0 luôn rỗng và đó là câu trả lời **đúng**.

    `slm_enabled` mặc định `False` và ADR-005 còn "Not Yet" — chưa có generation nào
    chạy để đo tokens/s hay RSS của model. `api_spec.md:464` cho phép tường minh:
    "`model_profile` remains the pinned configured identifier or `not-selected`".
    Điền một con số ở đây là bịa bằng chứng.
    """
    profile = settings.slm_model_id if settings.slm_enabled else "not-selected"
    return ModelRuntime(
        model_profile=profile,
        tokens_per_second=_stage_stat([]),
        rss_mib=RssStat(sample_count=0, current=None, peak=None),
    )


def _mqtt(records: list[TraceRecord]) -> MqttMetrics:
    """Suy từ kết quả từng bước, **không** đếm ở tầng broker.

    XẤP XỈ CÓ CHỦ Ý: `publish_attempts` ở đây là số bước đã thực thi, không phải số
    lần publish thô lên broker. Retry của QoS 1 và ack lặp nằm **dưới** tầng trace
    (`src/services/tool_executor.py`) nên không nhìn thấy được từ đây. Đếm thật cần
    counter trong `MqttVehicleGateway` — việc nối tiếp, đã ghi ở
    docs/tasks/TASK-BE-OBS-001 §4 và trong `docs/api_spec.md`.

    `latency_ms.count` chỉ tính bước **thành công**, đúng quy tắc mẫu số của
    `api_spec.md:458` ("latency count includes successful acknowledged publishes
    only").

    GIỚI HẠN HIỆN TẠI: `latency_ms` luôn rỗng (`count=0`, percentile `null`) vì độ
    trễ **từng bước** không có trên hợp đồng dây — payload `tool.result` chỉ mang
    `step_id`/`command_id`/`status`/`observed_state_version`/`error_code`, không có
    `latency_ms`. Tổng thời gian thực thi vẫn đo được và nằm ở
    `stage_latency_ms.tool`. Trả `null` ở đây là đúng: chia tổng cho số bước rồi gọi
    đó là p50 là bịa số.
    """
    attempts = published = errors = 0
    latencies: list[float] = []
    for record in records:
        for index, status in enumerate(record.step_statuses):
            if status.startswith("skipped"):
                continue
            attempts += 1
            if status == "completed":
                published += 1
                if index < len(record.step_latencies_ms):
                    latencies.append(record.step_latencies_ms[index])
            else:
                errors += 1
    return MqttMetrics(
        publish_attempts=attempts,
        published=published,
        latency_ms=_stage_stat(latencies),
        errors=errors,
        error_rate=_ratio(errors, attempts),
    )


def _rag(records: list[TraceRecord]) -> RagMetrics:
    """`grounded_rate = grounded/answered`; `abstention_rate = abstained/(answered+abstained)`.

    `faithfulness_*` luôn rỗng ở runtime: `api_spec.md:460` cấm rõ "never an
    unreviewed live-model self-score" — con số đó chỉ đến từ rubric có người chấm,
    tức `src/rag/evaluate.py` chạy offline, không phải từ endpoint này.
    """
    answered = grounded = abstained = 0
    citation_evaluated = citation_valid = 0
    for record in records:
        if record.outcome == "grounded_refusal" or record.refusal_reason:
            abstained += 1
            continue
        if record.citation_count > 0 or record.outcome in ("grounded_answer", "grounded_continue"):
            answered += 1
            if record.citation_count > 0:
                grounded += 1
                # Citation lọt tới đây là đã qua resolver của `rag_node`; hợp lệ
                # theo đúng nghĩa "phân giải được về chunk_id". Kiểm sâu hơn thuộc
                # eval offline, không phải aggregate live.
                citation_evaluated += record.citation_count
                citation_valid += record.citation_count
    return RagMetrics(
        answered=answered,
        grounded=grounded,
        abstained=abstained,
        grounded_rate=_ratio(grounded, answered),
        abstention_rate=_ratio(abstained, answered + abstained),
        citation_evaluated=citation_evaluated,
        citation_valid=citation_valid,
        citation_validity_rate=_ratio(citation_valid, citation_evaluated),
        faithfulness_evaluated=0,
        faithfulness_passed=0,
        faithfulness_pass_rate=None,
    )


def _safety(records: list[TraceRecord]) -> SafetyMetrics:
    metrics = SafetyMetrics()
    for record in records:
        if record.block_code == "VALIDATION_DENIED" or record.outcome == "validation_denied":
            metrics.validation_denied += 1
        if record.block_code == "SAFETY_BLOCKED" or record.admission_status == "blocked":
            metrics.blocked_s3 += 1
        if record.requires_approval or record.approval_id is not None:
            metrics.approvals_required += 1
            if record.admission_status == "executed":
                metrics.approved += 1
        field = _SAFETY_FIELD_BY_CANCEL_REASON.get(record.outcome or "")
        if field is not None:
            setattr(metrics, field, getattr(metrics, field) + 1)
    return metrics


def _action_audit(records: list[TraceRecord]) -> ActionAudit:
    """`attempted` **không** gồm bước bị skip.

    `api_spec.md:462`: "deduplicated replays and skipped steps are separate and not
    in that denominator". Gộp vào sẽ làm tỉ lệ thành công trông tệ hơn thực tế.
    """
    audit = ActionAudit()
    for record in records:
        for status in record.step_statuses:
            field = _AUDIT_FIELD_BY_STATUS.get(status)
            if field is None:
                continue
            setattr(audit, field, getattr(audit, field) + 1)
            if not status.startswith("skipped"):
                audit.attempted += 1
    return audit


def window_bounds(settings: Settings, now: datetime, collecting_since: datetime) -> tuple[datetime, datetime]:
    """Cửa sổ rolling `[max(collecting_since, now−window), now]`, trả về dạng nửa mở.

    `collecting_since` là `TraceStore.created_at` — kho bắt đầu thu từ lúc nào. Chặn
    dưới tại đó để không báo một cửa sổ 60 phút khi mới thu được 5 phút dữ liệu.

    BIÊN PHẢI LÀ `now + 1µs`, KHÔNG PHẢI `now` — đây là bản sửa của issue #67, và nó
    là bug sản phẩm chứ không phải chuyện làm đẹp test:

    `records_between` lọc `start <= opened_at < end` (nửa mở, theo `api_spec.md:452`).
    Nếu `end == now` thì mọi bản ghi có `opened_at == now` bị loại — tức **một lượt vừa
    mở xong không được đếm**. Nghe như chuyện không thể xảy ra, nhưng nó phụ thuộc độ
    phân giải đồng hồ: trên Windows + Python 3.11 (đúng phiên bản cả hai workflow CI
    pin) `datetime.now()` chỉ nhảy mỗi ~1 ms và 3000 lời gọi liên tiếp trả về **cùng
    một giá trị**, nên `opened_at` và `now` bằng nhau y hệt. Đo trực tiếp: 200/200 bản
    ghi vừa tạo bị vứt khỏi cửa sổ. CPython đổi `time.time()` trên Windows sang
    `GetSystemTimePreciseAsFileTime` ở **3.13**, nên máy dev chạy 3.13 không thấy gì,
    còn CI chạy Linux (đồng hồ mịn) cũng không thấy — lỗi sống sót 6 PR liền dưới nhãn
    "flaky test không liên quan tới diff" (issue #67).

    `now` không thể làm chặn trên loại trừ: đồng hồ không phân biệt được "vừa xong" với
    "bây giờ", mà một sự kiện đã xảy ra thì phải được đếm. Chặn trên đúng là instant
    **kế tiếp**. Giữ nguyên hợp đồng nửa mở `[from, to)` của spec, và chuỗi `to` render
    ra không đổi vì `iso_z` cắt tới giây.
    """
    start = max(collecting_since, now - timedelta(seconds=settings.metrics_window_seconds))
    return start, now + _ONE_TICK


def build_metrics_summary(store: TraceStore, settings: Settings, now: datetime | None = None) -> MetricsSummaryData:
    """Fold toàn bộ trace trong cửa sổ thành 8 nhóm aggregate.

    Tám chứ không phải bảy: `docs/handoff/frontend-integration-map.md:163` liệt kê 7
    nhóm và bỏ sót `model_runtime`, nhưng bản canonical `api_spec.md:608` có đủ 8.
    FE destructure 7 nên nhóm thứ tám là additive, không vỡ gì.
    """
    now = now or datetime.now(UTC)
    start, end = window_bounds(settings, now, store.created_at)
    records = store.records_between(start, end)

    return MetricsSummaryData(
        window=MetricsWindow(from_=iso_z(start), to=iso_z(end)),
        turns=_turns(records),
        stage_latency_ms=_stage_latency(records),
        model_runtime=_model_runtime(settings),
        mqtt=_mqtt(records),
        rag=_rag(records),
        safety=_safety(records),
        action_audit=_action_audit(records),
    )

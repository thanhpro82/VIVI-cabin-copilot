"""Hình dạng dây của `GET /traces/{id}` và `GET /metrics/summary`.

Mirror **chính xác** `docs/api_spec.md` mục "Trace" (:330-382) và "Metrics"
(:386-466). Ba mệnh đề "has exactly" ở `api_spec.md:382` là **tập field đóng** —
`extra="forbid"` cộng với test so sánh `set(...)` giữ điều đó, để không ai lặng lẽ
thêm field rồi frontend phải đoán.

Vì sao khai model thay vì trả `dict` trần: giống lý do đã ghi ở `src/models/api.py`
— `response_model` là thứ sinh ra `/docs`, và `/docs` chính là hợp đồng người làm
frontend đọc.

ENUM TỰ ĐỊNH NGHĨA — spec chốt tên field nhưng **không** liệt kê giá trị hợp lệ cho
`status`, `route_source`, `safety_summary.*`, `admission.status`. Bốn bảng dưới đây
lấy từ enum đã tồn tại trong code (`assistant.status.state` của api_spec.md:560,
`RouteDecision.route_source`, `ToolSpec.safety`, `AgentState.outcome`) chứ không
bịa mới. Quyết định này ghi ở docs/tasks/TASK-BE-OBS-001 §4.

REDACTION (`api_spec.md:11,445,686`, ranh giới ở ADR-029): không model nào ở đây có
field cho raw prompt, chain-of-thought, raw audio, **transcript**, credential hay
đường dẫn. `safe_summary` là chuỗi **sinh ra** từ outcome + tên tool. `answer_text`
là câu VIVI trả lời — cũng do server sinh, không phải câu người dùng nói.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.api import Meta
from src.models.vehicle import SCHEMA_VERSION

#: `assistant.status.state` (api_spec.md:560) + ba trạng thái terminal của lượt.
TRACE_STATUSES: tuple[str, ...] = (
    "transcribing",
    "routing",
    "planning",
    "retrieving",
    "waiting_approval",
    "executing",
    "composing",
    "completed",
    "failed",
    "canceled",
)

ADMISSION_STATUSES: tuple[str, ...] = (
    "not_applicable",
    "pending",
    "executed",
    "blocked",
    "canceled",
)

TraceStatus = Literal[
    "transcribing",
    "routing",
    "planning",
    "retrieving",
    "waiting_approval",
    "executing",
    "composing",
    "completed",
    "failed",
    "canceled",
]
#: `RouteDecision.route_source` của `src/agents/contracts.py` khai **bốn** giá trị —
#: bốn giá trị đó gồm cả `"rag"`, nhưng không đường nào trong `src/` sinh ra nó
#: (`grep route_source src/` chỉ ra `deterministic`/`slm`/`fallback`). Bề mặt dây chỉ
#: công bố ba giá trị thật sự phát ra; giá trị lạ bị `trace_view.py` hạ về `null` chứ
#: không lọt ra ngoài, vì một giá trị ngoài Literal sẽ làm `TraceData` fail validation
#: — tức 500 cho `GET /traces/{id}` và một event `trace` biến mất im lặng trên WS.
ROUTE_SOURCES: tuple[str, ...] = ("deterministic", "slm", "fallback")

RouteSource = Literal["deterministic", "slm", "fallback"]
SafetyLevel = Literal["S0", "S1", "S2", "S3"]
ValidationOutcome = Literal["passed", "denied", "not_applicable"]
AdmissionStatus = Literal["not_applicable", "pending", "executed", "blocked", "canceled"]


def iso_z(value: datetime) -> str:
    """ISO 8601 UTC kết thúc bằng `Z` — cùng khuôn với mọi timestamp khác của repo."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- trace


class StageLatencies(_Closed):
    """`api_spec.md:382`: "has exactly `stt`, `routing`, `planning_or_retrieval`,
    `safety`, `tool`, `tts`, and `end_to_end`"."""

    stt: float | None = None
    routing: float | None = None
    planning_or_retrieval: float | None = None
    safety: float | None = None
    tool: float | None = None
    tts: float | None = None
    end_to_end: float | None = None


class SafetySummary(_Closed):
    """`api_spec.md:382`: "has exactly `outcome`, `max_level`, `validation`,
    `admission`, and nullable `block_code`"."""

    outcome: str
    max_level: SafetyLevel
    validation: ValidationOutcome
    admission: AdmissionStatus
    block_code: str | None = None


class TraceVersions(_Closed):
    """`api_spec.md:382`: "has exactly `model_profile`, `prompt`, `tool`, `data`,
    `index`, `planning_vehicle_state`, and `observed_vehicle_state`".

    Giá trị P0 phản ánh **hiện trạng**, không phải mẫu trong tài liệu:
    `model_profile` là `not-selected` vì `slm_enabled=False` và ADR-005 chưa chốt
    model; `prompt` là `none-deterministic` vì không có prompt nào chạy (định tuyến
    100% bằng luật, ADR-006/ADR-010).
    """

    model_profile: str
    prompt: str
    tool: str
    data: str
    index: str
    planning_vehicle_state: int | None = None
    observed_vehicle_state: int | None = None


class PendingApproval(_Closed):
    approval_id: str
    expires_at: str


class Admission(_Closed):
    """`api_spec.md:382`: "has exactly `status`, nullable `approval_id`, nullable
    `execution_group_id`, nullable `approved_vehicle_state_version`, and nullable
    `actual_vehicle_state_version`"."""

    status: AdmissionStatus
    approval_id: str | None = None
    execution_group_id: str | None = None
    approved_vehicle_state_version: int | None = None
    actual_vehicle_state_version: int | None = None


class TraceData(_Closed):
    """`data` của `GET /traces/{trace_id}` — api_spec.md:330-380.

    `trace_id` ở đây là trace **được đọc**; `trace_id` ở tầng envelope là trace của
    chính request đọc này. Bất đối xứng có chủ ý, spec ghi rõ bằng ví dụ
    `tr_client_voice_001` vs `tr_trace_read_001`.
    """

    trace_id: str
    session_id: str
    turn_id: str
    #: Xe mà lượt này tác động lên. `None` khi trace mở trước lúc phiên có mặt trong
    #: DB (chỉ xảy ra trong test lái collector trực tiếp).
    vehicle_id: str | None = None
    status: TraceStatus
    route_source: RouteSource | None = None
    confidence: float | None = None
    plan_id: str | None = None
    pending_approval: PendingApproval | None = None
    safe_summary: str
    #: Câu VIVI trả lời tài xế. `None` khi lượt kết thúc bằng lỗi trước lúc compose.
    answer_text: str | None = None
    stage_latencies_ms: StageLatencies
    approval_wait_ms: float | None = None
    safety_summary: SafetySummary
    versions: TraceVersions
    admission: Admission


class TraceEnvelope(_Closed):
    data: TraceData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


# ------------------------------------------------------------------------- metrics


class MetricsWindow(_Closed):
    """Cửa sổ nửa mở `[from, to)` UTC — api_spec.md:452.

    `from` là từ khoá Python nên phải khai qua alias. `populate_by_name` để code
    nội bộ dựng bằng `from_` mà JSON vẫn ra `from`.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class TurnCounts(_Closed):
    accepted: int = 0
    completed: int = 0
    failed: int = 0
    canceled: int = 0


class StageStat(_Closed):
    """`p50`/`p95` là `None` khi `count == 0`.

    `api_spec.md:464` chốt: "every percentile and rate is JSON `null`" cho cửa sổ
    rỗng. `0` sẽ vẽ ra một biểu đồ phẳng nói dối — `frontend/src/lib/services/
    engineer/real.ts:41` đã khai đúng `p50: number | null`.
    """

    count: int = 0
    p50: float | None = None
    p95: float | None = None


class RssStat(_Closed):
    sample_count: int = 0
    current: float | None = None
    peak: float | None = None


class ModelRuntime(_Closed):
    """P0 luôn rỗng, **có chủ ý**.

    `slm_enabled` mặc định `False` (`src/config.py`) và ADR-005 còn "Not Yet", nên
    chưa từng có generation nào chạy để đo tokens/s. `api_spec.md:464` cho phép rõ:
    "`model_profile` remains the pinned configured identifier or `not-selected`".
    Bịa một con số ở đây sẽ phá kỷ luật chứng cứ của repo.
    """

    model_profile: str
    tokens_per_second: StageStat
    rss_mib: RssStat


class MqttMetrics(_Closed):
    publish_attempts: int = 0
    published: int = 0
    latency_ms: StageStat
    errors: int = 0
    error_rate: float | None = None


class RagMetrics(_Closed):
    answered: int = 0
    grounded: int = 0
    abstained: int = 0
    grounded_rate: float | None = None
    abstention_rate: float | None = None
    citation_evaluated: int = 0
    citation_valid: int = 0
    citation_validity_rate: float | None = None
    faithfulness_evaluated: int = 0
    faithfulness_passed: int = 0
    faithfulness_pass_rate: float | None = None


class SafetyMetrics(_Closed):
    validation_denied: int = 0
    blocked_s3: int = 0
    approvals_required: int = 0
    approved: int = 0
    rejected: int = 0
    expired: int = 0
    invalidated_state: int = 0
    invalidated_plan: int = 0
    predicate_failed: int = 0


class ActionAudit(_Closed):
    attempted: int = 0
    completed: int = 0
    failed: int = 0
    timeout: int = 0
    deduplicated: int = 0
    skipped_prior_failure: int = 0
    skipped_external_state_change: int = 0


class MetricsSummaryData(_Closed):
    """Tám nhóm theo `api_spec.md:608`.

    Lưu ý lệch tài liệu: `docs/handoff/frontend-integration-map.md:163` ghi **7**
    nhóm, bỏ `model_runtime`. Bản canonical là api_spec.md — phát đủ 8; FE
    destructure 7 nên nhóm thứ tám là additive, không vỡ gì.
    """

    window: MetricsWindow
    turns: TurnCounts
    stage_latency_ms: dict[str, StageStat]
    model_runtime: ModelRuntime
    mqtt: MqttMetrics
    rag: RagMetrics
    safety: SafetyMetrics
    action_audit: ActionAudit


class MetricsSummaryEnvelope(_Closed):
    data: MetricsSummaryData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


# ------------------------------------------------------------------ eval snapshot


class EvalSnapshotData(_Closed):
    """Ảnh chụp một run eval — **không** phải số đo từ hệ thống đang chạy.

    Vì sao nó không nằm trong `MetricsSummaryData`: hai thứ khác nhau về bản chất
    nguồn. `/metrics/summary` fold traffic vừa xảy ra trên chính máy này; cái này
    đọc lại một bằng chứng đã đóng gói, chấm trên bộ đề có đáp án khoá. Gộp vào
    một envelope là mời người đọc cộng hai loại số không cộng được.

    `metrics` để mở (`dict`) chứ không khai từng trường: mỗi suite có bộ chỉ số
    riêng và run cũ có bộ chỉ số cũ. Khai cứng ở đây thì thêm một phép đo vào
    `src/rag/evaluate.py` sẽ làm vỡ việc đọc lại mọi run đã đóng băng.

    `graded_by` là `None` với run ghi trước khi `manifest.json` tồn tại. UI phải
    hiện `—`; suy ra một nguồn chấm cho số của người khác đúng là kiểu nhầm mà
    trường này sinh ra để chặn.
    """

    suite: str
    run_id: str
    metrics: dict[str, float | int | str | None]
    graded_by: str | None = None
    dataset: str | None = None
    note: str | None = None


class EvalSnapshotEnvelope(_Closed):
    data: EvalSnapshotData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION

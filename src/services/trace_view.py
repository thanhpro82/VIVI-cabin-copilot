"""Dịch `TraceRecord` sang hình dạng dây `TraceData` (api_spec.md:330-380).

Tách khỏi `trace_store.py` vì hai bề mặt đọc nó — `GET /traces/{id}` và event
`trace` của `/ws/engineer` — phải dùng **đúng một** hàm. `api_spec.md:662` có hẳn
acceptance test cho điều đó: "GET and Engineer WS trace schemas expose the same
exact safe latency/safety/version/admission fields". Hai hàm serialize song song sẽ
lệch nhau sau vài tuần.

REDACTION (`api_spec.md:11,445,686`, ranh giới ở ADR-029): `safe_summary` sinh
**hoàn toàn** từ outcome + tên tool + số bước. `answer_text` chuyển tiếp nguyên câu
VIVI trả lời, thứ do server sinh. Không có đường nào từ **câu người dùng nói** hay
**nội dung citation** tới đây — `TraceRecord` không lưu chúng ngay từ đầu.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.config import Settings
from src.models.observability import (
    ADMISSION_STATUSES,
    ROUTE_SOURCES,
    TRACE_STATUSES,
    Admission,
    PendingApproval,
    SafetySummary,
    StageLatencies,
    TraceData,
    TraceVersions,
)
from src.services.trace_store import TraceRecord

#: Tên tool → cụm danh từ tiếng Việt cho `safe_summary`. Chỉ dùng **tên tool** (giá
#: trị do server sinh, thuộc tập đóng của `tool_registry.py`), không dùng args —
#: args an toàn ở P0 nhưng ràng buộc "không lộ nội dung" nên giữ ở mức tên.
_TOOL_LABEL = {
    "set_hvac_power": "điều hoà",
    "set_hvac_temperature": "nhiệt độ điều hoà",
    "set_seat_heating": "sưởi ghế",
    "set_seat_position": "vị trí ghế",
    "media_control": "phát nhạc",
    "set_navigation": "dẫn đường",
    "set_window_position": "cửa kính",
    "set_door_state": "cửa xe",
    "get_vehicle_state": "trạng thái xe",
    "query_manual": "sổ tay xe",
    "search_nearby_poi": "tìm địa điểm",
}

_SUMMARY_BY_STATUS = {
    "transcribing": "Đang nhận dạng giọng nói",
    "routing": "Đang xác định ý định",
    "planning": "Đang lập kế hoạch",
    "retrieving": "Đang tra sổ tay xe",
    "composing": "Đang soạn câu trả lời",
}

#: Outcome của graph → `safety_summary.outcome`. Spec chốt tên field nhưng không
#: liệt kê giá trị; bảng này lấy nguyên outcome đã có trong `AgentState`.
_SAFETY_OUTCOME = {
    "completed": "executed",
    "execution_failed": "execution_failed",
    "blocked": "blocked",
    "validation_denied": "validation_denied",
    "grounded_answer": "read_only",
    "grounded_continue": "read_only",
    "grounded_refusal": "read_only",
    "not_control": "read_only",
    "offer": "read_only",
    "clarify": "read_only",
    "vehicle_state_unavailable": "state_unavailable",
    # Nhánh HITL: outcome lúc graph dừng ở interrupt, và outcome khi lượt mới bị từ
    # chối vì đã có một approval đang treo. Thiếu hai dòng này thì lượt S2 đang chờ
    # người duyệt hiện `outcome` = `waiting_approval` (giá trị của `status`, không
    # phải của outcome) — trộn hai trục thông tin vào một ô.
    "approval_required": "pending_approval",
    "approval_already_pending": "pending_approval",
}


def safe_summary(record: TraceRecord) -> str:
    """Một dòng mô tả lượt, **sinh ra**, không trích.

    Ví dụ đầu ra: `"Chờ xác nhận 1 thao tác cửa kính"`, `"Đã chặn 1 thao tác cửa xe"`,
    `"Đã tra sổ tay xe (2 trích dẫn)"`. Không câu nào chứa lời tài xế.
    """
    actions = _describe_actions(record)

    if record.status == "waiting_approval":
        return f"Chờ xác nhận {actions}"
    if record.admission_status == "blocked":
        return f"Đã chặn {actions}"
    if record.status == "canceled":
        return f"Đã huỷ {actions}"
    if record.status == "failed":
        code = record.block_code or "lỗi không xác định"
        return f"Lượt thất bại ({code})"
    if record.status == "completed":
        if record.step_statuses:
            done = sum(1 for status in record.step_statuses if status == "completed")
            return f"Đã thực hiện {done}/{len(record.step_statuses)} bước {_tool_phrase(record)}".strip()
        if record.citation_count:
            return f"Đã tra sổ tay xe ({record.citation_count} trích dẫn)"
        return "Đã trả lời, không tác động tới xe"
    return _SUMMARY_BY_STATUS.get(record.status, "Đang xử lý")


def _describe_actions(record: TraceRecord) -> str:
    count = len(record.tool_names) or len(record.step_statuses)
    if not count:
        return "thao tác"
    return f"{count} thao tác {_tool_phrase(record)}".strip()


def _tool_phrase(record: TraceRecord) -> str:
    labels = {_TOOL_LABEL.get(name, "") for name in record.tool_names}
    labels.discard("")
    return ", ".join(sorted(labels))


def _index_version(settings: Settings) -> str:
    """Phiên bản chỉ mục RAG, đọc từ manifest thật.

    Trả `not-built` khi chưa dựng chỉ mục — trung thực hơn một chuỗi hằng như
    `manual-index-v1` luôn đúng bất kể trên đĩa có gì.
    """
    manifest = Path(settings.rag_index_dir) / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "not-built"
    return str(data.get("manual_manifest_version") or "not-built")


def _versions(record: TraceRecord, settings: Settings) -> TraceVersions:
    """`api_spec.md:382` chốt đúng 7 field.

    Giá trị phản ánh **hiện trạng P0**, không chép mẫu trong tài liệu:

    - `model_profile` = `not-selected` — `slm_enabled=False`, ADR-005 còn "Not Yet".
    - `prompt` = `none-deterministic` — không có prompt nào chạy; định tuyến 100%
      bằng luật (ADR-006/ADR-010). Ghi `prompt-v1` ở đây là gợi ý sai rằng có LLM.
    - `data` = `poi-fixture-v1` — `set_navigation` chỉ nhận `destination_id` từ
      fixture, ADR-010 §Scope boundary.
    """
    return TraceVersions(
        model_profile=settings.slm_model_id if settings.slm_enabled else "not-selected",
        prompt="none-deterministic",
        tool="tools-v1",
        data="poi-fixture-v1",
        index=_index_version(settings),
        planning_vehicle_state=record.planning_vehicle_state_version,
        observed_vehicle_state=record.actual_vehicle_state_version,
    )


def _validation(record: TraceRecord) -> str:
    if record.outcome == "validation_denied" or record.block_code == "VALIDATION_DENIED":
        return "denied"
    if record.tool_names or record.step_statuses:
        return "passed"
    return "not_applicable"


def to_trace_data(record: TraceRecord, settings: Settings) -> TraceData:
    """Bản ghi → `data` của `GET /traces/{id}`, cũng là payload event `trace`."""
    status = record.status if record.status in TRACE_STATUSES else "composing"
    admission_status = record.admission_status if record.admission_status in ADMISSION_STATUSES else "not_applicable"
    # Hạ giá trị lạ về `null` thay vì để nó nổ ở tầng validate. `normalize_node` reset
    # `route_source` về chuỗi rỗng đầu mỗi lượt, nên `""` là giá trị có thật đi qua
    # đây, và một `""` lọt vào Literal sẽ thành 500 khi kỹ sư đọc trace.
    route_source = record.route_source if record.route_source in ROUTE_SOURCES else None

    pending = None
    if record.approval_id and record.approval_expires_at and status == "waiting_approval":
        pending = PendingApproval(approval_id=record.approval_id, expires_at=record.approval_expires_at)

    return TraceData(
        trace_id=record.trace_id,
        session_id=record.session_id,
        turn_id=record.turn_id,
        vehicle_id=record.vehicle_id,
        status=status,  # type: ignore[arg-type]
        route_source=route_source,  # type: ignore[arg-type]
        confidence=record.confidence,
        plan_id=record.plan_id,
        pending_approval=pending,
        safe_summary=safe_summary(record),
        answer_text=record.answer_text,
        stage_latencies_ms=StageLatencies(**record.stages.as_dict()),
        approval_wait_ms=record.approval_wait_ms,
        safety_summary=SafetySummary(
            outcome=_SAFETY_OUTCOME.get(record.outcome or "", status),
            max_level=record.max_safety_level or "S0",  # type: ignore[arg-type]
            validation=_validation(record),  # type: ignore[arg-type]
            admission=admission_status,  # type: ignore[arg-type]
            block_code=record.block_code,
        ),
        versions=_versions(record, settings),
        admission=Admission(
            status=admission_status,  # type: ignore[arg-type]
            approval_id=record.approval_id,
            execution_group_id=record.execution_group_id,
            approved_vehicle_state_version=record.approved_vehicle_state_version,
            actual_vehicle_state_version=record.actual_vehicle_state_version,
        ),
    )

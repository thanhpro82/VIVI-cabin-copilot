"""Dựng `TraceRecord` bằng cách **nghe** `IviEventBus`, không sửa `emit_turn_lifecycle`.

Hướng hiển nhiên là seal trace ngay bên trong `emit_turn_lifecycle`. Không làm vậy,
vì hai lý do — lý do thứ hai mới là lý do chính:

1. `src/services/ivi_events.py` do người khác giữ và đang có PR sửa song song.
2. **Nghe bus bắt được nhiều hơn.** Hai đường thoát lỗi trong `src/api/turns.py`
   (`STT_FAILED`, `INTERNAL_ERROR`) publish `turn.failed` thẳng lên bus và **không
   đi qua** `emit_turn_lifecycle`. Seal bên trong hàm đó sẽ đếm thiếu
   `turns.failed`; listener trên bus thì không.

REDACTION — `api_spec.md:11,445,686`, ranh giới do ADR-029 chốt. Collector đọc
**số** từ payload (`confidence`, `len(citations)`, `state_version`, mã lỗi) cộng
đúng **một** trường văn bản: `assistant.response.display_text`, tức câu VIVI trả
lời — do server sinh, không phải lời tài xế.

Vẫn **không bao giờ** đọc: `transcript.final.text` (lời tài xế), `citations[].excerpt`
(nội dung sổ tay chưa cắt), `error.message` và `action.blocked.reason` (văn xuôi có
thể mang đường dẫn). Bảng `_HANDLERS` dưới đây là toàn bộ bề mặt đọc — thêm một
dòng lấy text nữa vào đây là mở một lỗ rò ra dashboard kỹ sư.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.config import get_settings
from src.db import get_connection
from src.models.observability import ROUTE_SOURCES
from src.models.vehicle import utc_now
from src.services.engineer_events import EngineerEventBus, get_engineer_bus
from src.services.trace_store import ANSWER_TEXT_MAX_CHARS, TraceRecord, TraceStore, get_trace_store
from src.services.trace_view import to_trace_data

logger = logging.getLogger(__name__)

#: Sự kiện chốt một lượt. Sau chúng, trace đủ dữ liệu để phát cho dashboard kỹ sư.
_SEALING_EVENTS = frozenset({"turn.completed", "turn.failed", "turn.canceled"})

#: `assistant.status.state` → `TraceRecord.status`. Giá trị lạ thì bỏ qua, không ghi
#: bừa: `status` là enum đóng của api_spec.md và một giá trị ngoài bảng sẽ làm
#: `TraceData` fail validation lúc serialize, tức lỗi 500 cho người đọc trace.
_STATUS_FROM_ASSISTANT_STATUS = {
    "transcribing": "transcribing",
    "routing": "routing",
    "planning": "planning",
    "retrieving": "retrieving",
    "waiting_approval": "waiting_approval",
    "executing": "executing",
    "composing": "composing",
}


class TraceCollector:
    """Listener toàn cục của `IviEventBus`.

    Không giữ state riêng — mọi thứ đi thẳng vào `TraceStore`. Nhờ vậy nó có thể bị
    đăng ký/huỷ đăng ký bất kỳ lúc nào mà không mất dữ liệu đã thu.
    """

    def __init__(self, store: TraceStore | None = None, bus: EngineerEventBus | None = None) -> None:
        self._store = store
        self._bus = bus

    @property
    def store(self) -> TraceStore:
        # Phân giải muộn để test thay store bằng `set_trace_store()` sau khi
        # collector đã được dựng.
        return self._store if self._store is not None else get_trace_store()

    @property
    def bus(self) -> EngineerEventBus:
        return self._bus if self._bus is not None else get_engineer_bus()

    async def __call__(self, event: dict[str, Any]) -> None:
        """Chữ ký khớp `EventListener` của `IviEventBus`.

        Nuốt mọi lỗi: `IviEventBus.publish` đã bọc `try/except` quanh callback,
        nhưng ở đây bắt thêm một lần nữa để một payload lạ không bao giờ làm hỏng
        việc giao sự kiện cho `/ws/ivi` — quan sát không được phép làm gãy sản phẩm.
        """
        try:
            self._handle(event)
            if event.get("type") in _SEALING_EVENTS:
                # `resolve` chứ không phải `event["trace_id"]`: lượt S2 chốt dưới một
                # trace_id khác nửa đầu — xem docstring của `resolve`.
                trace_id = self.resolve(event)
                if trace_id is not None:
                    await self._broadcast_trace(trace_id)
        except Exception:  # noqa: BLE001 - xem docstring
            logger.exception("TraceCollector bỏ qua sự kiện lỗi: %s", event.get("type"))

    async def _broadcast_trace(self, trace_id: str) -> None:
        """Phát event `trace` cho `/ws/engineer` ngay khi lượt chốt.

        Theo sự kiện chứ không theo nhịp: `api_spec.md` không nói trigger, nhưng
        `docs/handoff/frontend-integration-map.md:169` chỉ rõ hệ quả của lựa chọn
        sai — "nếu chỉ phát theo yêu cầu thì bảng log sẽ trống". Quyết định ghi ở
        docs/tasks/TASK-BE-OBS-001 §4.
        """
        record = self.store.get(trace_id)
        if record is None:
            return
        payload = to_trace_data(record, get_settings()).model_dump(mode="json")
        await self.bus.publish("trace", payload)

    # -- nội bộ ----------------------------------------------------------------

    def resolve(self, event: dict[str, Any]) -> str | None:
        """Khoá kho của sự kiện này. `None` nghĩa là không thuộc trace nào đang giữ.

        Thử `trace_id` trước, rồi mới tới index `turn_id`. Bước thứ hai **không phải
        phòng xa** — nó là đường sống duy nhất của lượt S2 sau khi thực thi chuyển
        sang chạy nền:

        `src/api/approvals.py:_resume_and_publish` đúc một `trace_id` mới cho nửa sau
        của lượt. Nửa đầu (`turn.accepted` → `waiting_approval`) nằm ở trace A; còn
        `turn.completed` lại phát dưới trace B chưa từng được mở. Chỉ khớp theo
        `trace_id` thì mọi lượt cần duyệt sẽ treo ở `waiting_approval` vĩnh viễn,
        không bao giờ có event `trace`, và `turns.completed` đếm thiếu đúng những
        lượt đáng chú ý nhất.

        `turn_id` thì xuyên suốt cả hai nửa vì `_resume_and_publish` nhận nó từ
        `ApprovalRecord`. Nối lại ở đây là việc của tầng quan sát; sửa cho `trace_id`
        liên tục là việc của tầng HITL — xem docs/tasks/TASK-BE-OBS-001 §Tier 3.
        """
        trace_id = event.get("trace_id") or ""
        if trace_id and self.store.get(trace_id) is not None:
            return trace_id
        turn_id = event.get("turn_id") or ""
        if turn_id:
            record = self.store.get_by_turn(turn_id)
            if record is not None:
                return record.trace_id
        return None

    def _handle(self, event: dict[str, Any]) -> None:
        event_type = event.get("type", "")
        payload: dict[str, Any] = event.get("payload") or {}

        if event_type == "turn.accepted":
            trace_id = event.get("trace_id") or ""
            if trace_id:
                session_id = event.get("session_id", "")
                self.store.open(trace_id, session_id, event.get("turn_id", ""))
                xe = _xe_cua_phien(session_id)
                if xe is not None:
                    self.store.update(trace_id, vehicle_id=xe)
            return

        # Sự kiện mồ côi (tới trước `turn.accepted`, hoặc trace đã bị LRU đẩy ra) thì
        # bỏ qua — không tạo bản ghi thiếu `opened_at` làm lệch metrics.
        trace_id = self.resolve(event)
        if trace_id is None:
            return

        handler = _HANDLERS.get(event_type)
        if handler is not None:
            handler(self, trace_id, payload)

    # -- từng loại sự kiện -----------------------------------------------------

    def _on_assistant_status(self, trace_id: str, payload: dict[str, Any]) -> None:
        status = _STATUS_FROM_ASSISTANT_STATUS.get(payload.get("state", ""))
        if status is None:
            return
        changes: dict[str, Any] = {"status": status}
        if status == "waiting_approval":
            changes["admission_status"] = "pending"
        self.store.update(trace_id, **changes)

    def _on_transcript_final(self, trace_id: str, payload: dict[str, Any]) -> None:
        # CHỈ `confidence`. `payload["text"]` là transcript thô — cấm đưa vào trace.
        self.store.update(trace_id, transcript_confidence=payload.get("confidence"))

    def _on_plan_ready(self, trace_id: str, payload: dict[str, Any]) -> None:
        # `plan.ready` mới có từ PR HITL; trace vẫn dựng được khi thiếu nó, chỉ là
        # `plan_id` sẽ đến muộn hơn qua `approval.required`.
        self.store.update(
            trace_id,
            plan_id=payload.get("plan_id"),
            requires_approval=bool(payload.get("requires_approval")),
        )

    def _on_approval_required(self, trace_id: str, payload: dict[str, Any]) -> None:
        actions = payload.get("actions") or []
        self.store.update(
            trace_id,
            plan_id=payload.get("plan_id"),
            approval_id=payload.get("approval_id"),
            approval_expires_at=payload.get("expires_at"),
            approval_requested_at=utc_now(),
            approved_vehicle_state_version=payload.get("approved_vehicle_state_version"),
            planning_vehicle_state_version=payload.get("approved_vehicle_state_version"),
            admission_status="pending",
            requires_approval=True,
            status="waiting_approval",
            # `actions` là tóm tắt do server sinh, không phải câu người dùng nói.
            # Chỉ lấy **số lượng** để dựng `safe_summary`, không lấy nội dung.
            tool_names=tuple(str(item.get("tool", "")) for item in actions if isinstance(item, dict)),
            max_safety_level="S2",
        )

    def _on_tool_result(self, trace_id: str, payload: dict[str, Any]) -> None:
        record = self.store.get(trace_id)
        if record is None:
            return
        status = str(payload.get("status", ""))
        observed = payload.get("observed_state_version")
        self.store.update(
            trace_id,
            step_statuses=(*record.step_statuses, status),
            actual_vehicle_state_version=observed if observed is not None else record.actual_vehicle_state_version,
        )

    def _on_action_blocked(self, trace_id: str, payload: dict[str, Any]) -> None:
        # `payload["reason"]` là văn xuôi cho tài xế — không lấy. Chỉ lấy mã.
        self.store.update(
            trace_id,
            plan_id=payload.get("plan_id"),
            block_code=payload.get("code"),
            admission_status="blocked",
            max_safety_level="S3",
        )

    def _on_assistant_response(self, trace_id: str, payload: dict[str, Any]) -> None:
        # `display_text` là câu VIVI trả lời — server sinh, được phép (ADR-029).
        # `speak_text` bỏ qua: nó là biến thể đọc-thành-tiếng của cùng nội dung, lưu
        # thêm chỉ tốn RAM. `citations[].excerpt` vẫn CHỈ đếm, không lấy nội dung.
        text = payload.get("display_text")
        self.store.update(
            trace_id,
            citation_count=len(payload.get("citations") or []),
            answer_text=_cat(text) if isinstance(text, str) and text else None,
        )

    def _on_error(self, trace_id: str, payload: dict[str, Any]) -> None:
        self.store.update(trace_id, block_code=payload.get("code"))

    def _on_turn_completed(self, trace_id: str, payload: dict[str, Any]) -> None:
        """Đóng bản ghi là `completed`.

        **Không** kiểm `outcome` ở đây, dù bản đầu của #382 từng làm thế. Sau khi PM/PO
        chốt trên #375, `emit_turn_lifecycle` phát thẳng `turn.failed` cho lượt hỏng, nên
        một lượt `validation_denied` không bao giờ đi tới sự kiện này nữa — nhánh kiểm
        trong hàm này sẽ là code chết, và một nguồn sự thật thứ hai cho cùng một luật.
        Luật ấy sống ở `ivi_events.OUTCOME_LUOT_HONG`, đúng một chỗ.
        """
        record = self.store.get(trace_id)
        self.store.seal(
            trace_id,
            status="completed",
            admission_status=_final_admission(record, "executed"),
            approval_wait_ms=_approval_wait_ms(record),
        )

    def _on_turn_failed(self, trace_id: str, payload: dict[str, Any]) -> None:
        record = self.store.get(trace_id)
        self.store.seal(
            trace_id,
            status="failed",
            block_code=payload.get("code") or (record.block_code if record else None),
            admission_status=_final_admission(record, "canceled"),
            approval_wait_ms=_approval_wait_ms(record),
        )

    def _on_turn_canceled(self, trace_id: str, payload: dict[str, Any]) -> None:
        self.store.seal(
            trace_id,
            status="canceled",
            outcome=payload.get("reason"),
            admission_status="canceled",
            approval_wait_ms=_approval_wait_ms(self.store.get(trace_id)),
        )


def _cat(text: str) -> str:
    """Cắt ở `ANSWER_TEXT_MAX_CHARS`, có dấu hiệu nhìn thấy được.

    Cắt im lặng sẽ làm kỹ sư đọc một câu cụt mà tưởng composer sinh ra thế.
    """
    if len(text) <= ANSWER_TEXT_MAX_CHARS:
        return text
    return text[:ANSWER_TEXT_MAX_CHARS] + "…"


def _xe_cua_phien(session_id: str) -> str | None:
    """`sessions.vehicle_id` của phiên, hoặc `None`.

    Đọc thẳng SQLite thay vì gọi `src.api.session_state`: `src/services/` không
    import `src/api/` ở bất kỳ đâu và không được là chỗ đầu tiên làm vậy. Truy vấn
    là một lượt tra khoá chính trên file cục bộ, nên chạy đồng bộ trong listener là
    chấp nhận được — nó không thuộc loại chặn event loop như lời gọi SLM.

    Fail-soft có chủ đích: test lái collector trực tiếp không có phiên nào trong DB,
    và một trace thiếu `vehicle_id` vẫn hữu ích hơn một lượt hỏng vì tầng quan sát.
    """
    if not session_id:
        return None
    try:
        # Cột khoá chính của bảng tên là `id`, không phải `session_id` — xem
        # `src/db.py`. Gõ nhầm ở đây thì `except` dưới nuốt mất và trace lặng lẽ
        # thiếu xe, nên log ở mức `warning`: đây là lỗi schema, không phải chuyện thường.
        row = get_connection().execute("SELECT vehicle_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    except Exception:  # noqa: BLE001 - tầng quan sát không được làm hỏng lượt
        logger.warning("khong tra duoc vehicle_id cua phien %s", session_id, exc_info=True)
        return None
    return str(row[0]) if row and row[0] else None


#: Thứ tự an toàn tăng dần (`ToolSpec.safety`), để lấy mức cao nhất của một kế hoạch.
_SAFETY_ORDER: tuple[str, ...] = ("S0", "S1", "S2", "S3")


def _plan_max_safety(plan: Any) -> str | None:
    """Mức an toàn cao nhất trong `ActionPlan`. Nhận cả model lẫn dict đã dump."""
    steps = getattr(plan, "steps", None)
    if steps is None and isinstance(plan, Mapping):
        steps = plan.get("steps")
    levels = []
    for step in steps or ():
        level = step.get("safety_level") if isinstance(step, Mapping) else getattr(step, "safety_level", None)
        if level in _SAFETY_ORDER:
            levels.append(level)
    return max(levels, key=_SAFETY_ORDER.index) if levels else None


def record_graph_result(trace_id: str, result: Mapping[str, Any], store: TraceStore | None = None) -> None:
    """Thu những field **chỉ tồn tại trong `result` của graph**, không có trên bus.

    `TraceCollector` dựng gần trọn bản ghi từ luồng sự kiện, nhưng bốn thứ dưới đây
    không bao giờ lên dây `/ws/ivi` — không sự kiện nào mang chúng, kể cả gián tiếp:

    - `route_source`, `intent`, `confidence` — kết quả của bộ định tuyến. Thiếu thì
      cột "nguồn định tuyến" của dashboard kỹ sư vĩnh viễn trống, đúng cái cột đo
      ADR-006 ("định tuyến 100% bằng luật") có đúng không.
    - `outcome` — `emit_turn_lifecycle` gộp `validation_denied`, `not_control`,
      `clarify`, `offer`, `grounded_answer` và `grounded_refusal` vào **cùng một**
      chuỗi sự kiện (`assistant.status(composing)` → `assistant.response` →
      `turn.completed`). Từ ngoài bus chúng không phân biệt được, nên thiếu field này
      thì `safety.validation_denied` và `rag.abstained` luôn báo `0` — một con số sai
      trông y hệt một con số đúng.
    - `max_safety_level` — chỉ suy được từ `action_plan`. Không có nó thì mọi lượt S1
      (bật điều hoà, chỉnh nhiệt độ) hiện `max_level: "S0"` trên trace, tức một lượt
      **có tác động tới xe** bị gắn nhãn chỉ-đọc. Đây là lỗi nặng nhất trong nhóm:
      nó không làm trống một ô, nó điền vào ô đó một giá trị sai và đáng tin.

    REDACTION — hàm này đọc `result` của graph, tức chỗ **có** `query`,
    `normalized_text`, `response_text`, `citations[].excerpt`. Nó chỉ chạm đúng năm
    khoá liệt kê dưới đây, tất cả đều là enum/số do server sinh. Đừng nới danh sách.

    Thuần quan sát và không bao giờ raise ra ngoài: gọi nó ở đường xử lý lượt thì lỗi
    ở đây không được phép làm hỏng lượt của tài xế.
    """
    target = store if store is not None else get_trace_store()
    try:
        changes: dict[str, Any] = {}

        route_source = result.get("route_source")
        if route_source in ROUTE_SOURCES:
            changes["route_source"] = route_source

        intent = result.get("intent")
        if isinstance(intent, str) and intent:
            changes["intent"] = intent

        confidence = result.get("confidence")
        if isinstance(confidence, int | float) and not isinstance(confidence, bool):
            changes["confidence"] = float(confidence)

        outcome = result.get("outcome")
        if isinstance(outcome, str) and outcome:
            changes["outcome"] = outcome

        refusal_reason = result.get("refusal_reason")
        if isinstance(refusal_reason, str) and refusal_reason:
            changes["refusal_reason"] = refusal_reason

        # Ghi cả khi `False`: mẫu số của phép đo §7 là "bao nhiêu lượt bắt tự động",
        # nên một lượt bấm mic tay phải ghi rõ là `False` chứ không để trống.
        changes["bat_tu_dong"] = bool(result.get("bat_tu_dong"))

        level = _plan_max_safety(result.get("action_plan"))
        if level is not None:
            changes["max_safety_level"] = level

        if changes:
            target.update(trace_id, **changes)
    except Exception:  # noqa: BLE001 - xem docstring: quan sát không được làm gãy sản phẩm
        logger.exception("Không ghi được kết quả graph vào trace %s", trace_id)


def _approval_wait_ms(record: TraceRecord | None) -> float | None:
    """Thời gian chờ **người**, tính từ lúc phát `approval.required` tới lúc chốt.

    `api_spec.md:382` chốt: đây là đại lượng tách riêng và **không bao giờ** được
    gộp vào `stage_latencies_ms` — một tài xế suy nghĩ 20 giây không phải là hệ
    thống chậm 20 giây.

    GIỚI HẠN HIỆN TẠI: `src/api/approvals.py` đúc `trace_id` mới lúc resume, nên nửa
    sau của lượt S2 rơi vào một trace khác và giá trị này vẫn là `None`. Xem
    docs/tasks/TASK-BE-OBS-001 §Tier 3 — cần `trace_id` trên `ApprovalRecord`.
    """
    if record is None or record.approval_requested_at is None:
        return record.approval_wait_ms if record else None
    return (utc_now() - record.approval_requested_at).total_seconds() * 1000


def _final_admission(record: TraceRecord | None, default: str) -> str:
    """Trạng thái admission lúc chốt.

    Lượt không có bước nào (tra sổ tay, `offer`, `clarify`) thì `not_applicable` —
    gọi nó là "executed" sẽ làm `action_audit.attempted` nói dối. `blocked` đã chốt
    thì giữ nguyên, vì lượt bị chặn vẫn kết thúc bằng `turn.completed`.
    """
    if record is None:
        return default
    if record.admission_status == "blocked":
        return "blocked"
    if not record.step_statuses:
        return "not_applicable"
    return default


_HANDLERS = {
    "assistant.status": TraceCollector._on_assistant_status,
    "transcript.final": TraceCollector._on_transcript_final,
    "plan.ready": TraceCollector._on_plan_ready,
    "approval.required": TraceCollector._on_approval_required,
    "tool.result": TraceCollector._on_tool_result,
    "action.blocked": TraceCollector._on_action_blocked,
    "assistant.response": TraceCollector._on_assistant_response,
    "error": TraceCollector._on_error,
    "turn.completed": TraceCollector._on_turn_completed,
    "turn.failed": TraceCollector._on_turn_failed,
    "turn.canceled": TraceCollector._on_turn_canceled,
}

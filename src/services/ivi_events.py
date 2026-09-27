"""Bus sự kiện lượt thoại cho `/ws/ivi`.

Pub/sub theo `session_id`, có retention: mỗi session giữ một ring buffer (tối đa
`RING_BUFFER_SIZE` event đã đóng gói đầy đủ — `event_id`/`sequence` được gán đúng một lần,
tại đây, không phải mỗi lần một connection nhận event) để reconnect replay được đúng những gì
đã bỏ lỡ. Xem docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from src.agents.contracts import as_action_plan
from src.agents.nghe_tiep import con_nghe_tiep
from src.agents.nodes.compose import describe_step
from src.agents.nodes.speech_policy import MAX_SPOKEN_CHARS
from src.models.vehicle import SCHEMA_VERSION, utc_now
from src.services import voice
from src.services.tool_registry import get_spec
from src.services.trace_store import get_trace_store

logger = logging.getLogger(__name__)

EventListener = Callable[[dict[str, Any]], Awaitable[None]]

#: Số event tối đa giữ lại mỗi session — đủ cho nhiều lượt liên tiếp mà không phình bộ nhớ.
RING_BUFFER_SIZE = 200

_BUFFER_TTL_SECONDS = 1800.0  # 30 phút không hoạt động, không có listener -> clear buffer, GIU sequence
_STREAM_TTL_SECONDS = 86400.0  # 24 gio khong hoat dong, khong co listener -> xoa han entry


def now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


class _SessionStream:
    """Trạng thái retention của một session: bộ đếm sequence + ring buffer event đã đóng gói."""

    def __init__(self) -> None:
        self.listeners: list[EventListener] = []
        self.sequence: int = 0
        self.buffer: deque[dict[str, Any]] = deque(maxlen=RING_BUFFER_SIZE)
        self.last_active: float = time.monotonic()


class IviEventBus:
    def __init__(self) -> None:
        self._streams: dict[str, _SessionStream] = {}
        self._global_listeners: list[EventListener] = []

    def _stream(self, session_id: str) -> _SessionStream:
        stream = self._streams.get(session_id)
        if stream is None:
            stream = _SessionStream()
            self._streams[session_id] = stream
        return stream

    def _sweep_expired(self) -> None:
        now = time.monotonic()
        for session_id, stream in list(self._streams.items()):
            if stream.listeners:
                continue
            idle = now - stream.last_active
            if idle >= _STREAM_TTL_SECONDS:
                del self._streams[session_id]
            elif idle >= _BUFFER_TTL_SECONDS and stream.buffer:
                stream.buffer.clear()

    def add_listener(self, session_id: str, callback: EventListener) -> None:
        self._sweep_expired()
        stream = self._stream(session_id)
        stream.listeners.append(callback)
        stream.last_active = time.monotonic()

    def remove_listener(self, session_id: str, callback: EventListener) -> None:
        stream = self._streams.get(session_id)
        if stream is None:
            return
        stream.listeners.remove(callback)

    def add_global_listener(self, callback: EventListener) -> None:
        """Nghe **mọi** session. Dành cho quan sát, không dành cho giao hàng.

        Người dùng duy nhất hiện nay là `src/services/trace_collector.py`: nó dựng
        trace vận hành từ chính luồng sự kiện này thay vì chen thêm lệnh ghi vào
        `emit_turn_lifecycle`. Lợi thế thật sự không phải là ít đụng chạm mà là
        **bắt được nhiều hơn** — hai đường thoát lỗi trong `src/api/turns.py`
        (`STT_FAILED`, `INTERNAL_ERROR`) publish `turn.failed` thẳng lên bus và
        không đi qua `emit_turn_lifecycle`.

        Listener toàn cục nhận sự kiện của mọi tài xế nên **chỉ** được dùng cho bề
        mặt đã khử nhạy cảm; xem ràng buộc redaction ở đầu `trace_collector.py`.
        """
        self._global_listeners.append(callback)

    def remove_global_listener(self, callback: EventListener) -> None:
        if callback in self._global_listeners:
            self._global_listeners.remove(callback)

    def replay_snapshot(
        self, session_id: str, last_event_id: str | None, last_sequence: int | None
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Xác thực cursor reconnect và trả về batch event cần replay.

        Trả `(None, [])` cho kết nối mới (không cursor). Trả `(None, events)` với `events`
        là mọi event đã phát SAU cursor, giữ nguyên `event_id`/`sequence` gốc. Trả
        `("REPLAY_CURSOR_INVALID"|"REPLAY_WINDOW_EXPIRED", [])` khi cursor không hợp lệ — xem
        thuật toán ở docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md mục 3.
        """
        self._sweep_expired()
        if last_event_id is None and last_sequence is None:
            return None, []
        if last_event_id is None or last_sequence is None or not isinstance(last_sequence, int):
            return "REPLAY_CURSOR_INVALID", []

        stream = self._streams.get(session_id)
        if stream is None:
            return "REPLAY_CURSOR_INVALID", []
        earliest = stream.buffer[0]["sequence"] if stream.buffer else stream.sequence + 1
        if last_sequence > stream.sequence:
            return "REPLAY_CURSOR_INVALID", []
        if last_sequence < earliest:
            return "REPLAY_WINDOW_EXPIRED", []

        position = last_sequence - earliest
        candidate = stream.buffer[position]
        if candidate["event_id"] != last_event_id:
            return "REPLAY_CURSOR_INVALID", []
        return None, list(stream.buffer)[position + 1 :]

    def active_sessions(self) -> list[str]:
        """Các session đang có stream (kể cả lúc không có socket nào nối).

        Vẫn kể session không có listener là **có chủ đích**: event vẫn vào ring buffer
        và tài xế reconnect sẽ nhận qua replay (ADR-014). Bỏ qua chúng thì một người
        mất sóng đúng lúc xe chuyển sang chạy sẽ nối lại với policy cũ.
        """
        self._sweep_expired()
        return list(self._streams)

    async def broadcast(self, event_type: str, trace_id: str, payload: dict[str, Any]) -> None:
        """Phát tới **mọi** session. Dành cho sự kiện bắt nguồn từ trạng thái xe.

        Không dùng `add_global_listener` được: cái đó là đường **quan sát** (xem
        docstring của nó), không phải đường giao hàng, và nó không gán
        `event_id`/`sequence` theo từng session như ADR-014 yêu cầu.
        """
        for session_id in self.active_sessions():
            await self.publish(session_id, event_type, None, trace_id, payload)

    async def broadcast_to(
        self, session_ids: Iterable[str], event_type: str, trace_id: str, payload: dict[str, Any]
    ) -> None:
        """Phát tới **đúng** những session được nêu tên.

        Có mặt vì pool xe: `ui.policy` suy từ trạng thái của MỘT chiếc xe, nên nó chỉ
        đúng với những phiên đang thuê chính chiếc xe đó. Dùng `broadcast()` ở đó là
        siết giao diện của người đang đứng yên vì xe của người khác vừa lăn bánh.

        Lọc qua `active_sessions()` chứ không phát thẳng: một `session_id` không có
        stream nào thì `publish()` sẽ **dựng** stream cho nó và bơm event vào ring buffer
        của một phiên có thể đã chết — đúng thứ `_sweep_expired` sinh ra để dọn.
        """
        dang_hoat_dong = set(self.active_sessions())
        for session_id in session_ids:
            if session_id in dang_hoat_dong:
                await self.publish(session_id, event_type, None, trace_id, payload)

    async def publish(
        self, session_id: str, event_type: str, turn_id: str | None, trace_id: str, payload: dict[str, Any]
    ) -> None:
        self._sweep_expired()
        stream = self._stream(session_id)
        stream.sequence += 1
        event: dict[str, Any] = {
            "type": event_type,
            "event_id": f"evt_{uuid.uuid4().hex[:20]}",
            "sequence": stream.sequence,
            "trace_id": trace_id,
            "emitted_at": now_iso(),
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "turn_id": turn_id,
            "payload": payload,
        }
        stream.buffer.append(event)
        stream.last_active = time.monotonic()
        # Chụp lại danh sách trước khi lặp: callback được gọi có thể remove chính nó
        # (WS disconnect giữa lúc publish), sửa list đang lặp thì lỗi.
        for callback in [*list(stream.listeners), *self._global_listeners]:
            try:
                await callback(event)
            except Exception:
                # Listener failure (e.g. WS disconnect) must not prevent delivery to sibling listeners
                # or abort the publisher's control flow.
                logger.exception(
                    "Listener callback raised exception for session %s, continuing to deliver to other listeners",
                    session_id,
                )

    def reset(self) -> None:
        """Chỉ dùng trong test."""
        self._streams.clear()


_BUS = IviEventBus()


def get_event_bus() -> IviEventBus:
    return _BUS


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    _BUS.reset()


#: Outcome fail-closed từ `request_approval_node` (src/agents/nodes/approval.py) →
#: `reason` của `turn.canceled`. Enum reason theo docs/api_spec.md, mirror ở
#: `frontend/src/lib/services/turn/types.ts` (`TurnCancelReason`).
_CANCEL_REASON_BY_OUTCOME = {
    "approval_rejected": "approval_rejected",
    "approval_expired": "approval_expired",
    "approval_invalidated_state": "approval_invalidated_state",
    "approval_invalidated_plan": "approval_invalidated_plan",
    "approval_predicate_failed": "approval_predicate_failed",
    # Enum reason không có mục riêng cho "bản ghi thuộc phiên/lượt khác"; đó là một dạng
    # thất bại khi kiểm tra state/session, nên dùng reason gần nhất thay vì bịa giá trị mới.
    "approval_not_owned": "approval_invalidated_state",
}


def _wire_tool_status(step: Any) -> str:
    """Dịch `ToolStatus` nội bộ sang `ToolResultStatus` của hợp đồng dây.

    `src/agents/contracts.py` dùng `completed|failed|rejected|skipped`, còn hợp đồng dây
    (docs/api_spec.md, `frontend/src/lib/services/turn/types.ts`) chỉ biết
    `completed|failed|timeout|skipped_due_to_prior_failure|skipped_external_state_change`.
    `skipped` và `rejected` không được lọt ra ngoài.
    """
    if step.status == "skipped":
        # `execute_node` chỉ sinh `skipped_due_to_prior_failure`; mọi lý do skip khác đổ
        # về giá trị skip còn lại trong hợp đồng dây, không bao giờ trả về `skipped` thô.
        if step.error_code == "skipped_due_to_prior_failure":
            return "skipped_due_to_prior_failure"
        return "skipped_external_state_change"
    if step.status == "rejected":
        # `VehicleSimulator.execute` trả `rejected` cho `stale_state` và
        # `unsafe_vehicle_state`: bước **không** chạy và đó là thất bại của bước, không
        # phải một skip đã lên kế hoạch. Hợp đồng dây không có `rejected` nên map sang
        # `failed`; `error_code` gốc vẫn đi kèm nên client phân biệt được lý do.
        return "failed"
    return step.status


def im_lang(result: dict[str, Any]) -> bool:
    """Lượt bắt tự động mà xe không hiểu thì **không nói gì** — spec §3.5.

    Đo được (29/08): ba câu người-nói-với-người đều rơi vào `default_to_manual`, và xe đọc
    *"Tôi không tìm thấy thông tin này trong sổ tay xe."* vào giữa cuộc nói chuyện của họ,
    vài giây một lần. Đó là thứ khiến người ta tắt trợ lý — tệ hơn một lệnh chạy nhầm, vì
    lệnh nhầm thì tắt đi là xong.

    Dùng lại đúng `con_nghe_tiep` chứ **không** có bảng riêng: *"không đáng nghe tiếp"* và
    *"không đáng nói ra"* là **cùng một** phán đoán — xe vừa không hiểu câu vừa rồi. Hai
    bảng song song là cách chắc chắn để chúng lệch nhau.

    Vắng `bat_tu_dong` = `manual` = **nói**. Fail về phía nói, không về phía im: một
    trợ lý câm khó chẩn đoán hơn nhiều một trợ lý nói thừa.
    """
    return bool(result.get("bat_tu_dong")) and not con_nghe_tiep(result)


def cau_ngan(result: dict[str, Any]) -> str:
    """Bản **ngắn** của lượt — thứ ra loa, và từ 21/08 cũng là thứ lên màn hình.

    ## Đường lui có TRẦN, không phải đường lui trần trụi

    Bản trước là `result.get("speak_text") or result.get("response_text", "")`. @thanhpro82
    chặn PR #221 ở đúng dòng ấy: một node cũ quên `speak_text` thì `response_text` — có thể
    tới `QUOTE_MAX_CHARS = 1.200` ký tự nguyên văn sổ tay — quay lại **cả UI lẫn TTS**, phá
    đúng bất biến sản phẩm mà PR ấy dựng lên.

    Anh ấy cho hai lối: chứng minh mọi đường đều có `speak_text`, hoặc thay đường lui.
    Chọn cái thứ hai, vì cái thứ nhất **không chứng minh được cho tương lai** — nó đúng
    hôm nay và im lặng sai vào ngày ai đó thêm một node mới.

    Đường lui nay cắt ở biên câu, trần `MAX_SPEECH_CHARS`. Cùng phép cắt mà
    `synthesize_speech` đã áp cho `speak_text` quá dài, nên hai chỗ không thể lệch nhau về
    độ dài tối đa. Node quên `speak_text` vẫn nói được một câu tử tế; thứ nó **không** làm
    được nữa là đổ 1.200 ký tự lên màn hình.
    """
    ngan = result.get("speak_text")
    if isinstance(ngan, str) and ngan:
        return ngan
    # `or ""` chứ không `get(..., "")`: khoá **có mặt** với giá trị `None` là chuyện thật
    # (một node trả `None` thay vì bỏ trống), và `get` với mặc định không cứu ca ấy.
    # Payload dựng từ state của graph, nên hình dạng nó là dữ liệu ngoài với hàm này.
    day_du = result.get("response_text") or ""
    return _cat_o_bien_cau(day_du, MAX_SPEECH_CHARS) if isinstance(day_du, str) else ""


def cau_hien(result: dict[str, Any], noi: str) -> str:
    """Chuỗi lên **màn hình**. Bất biến "màn hình là phụ đề" được giữ ở đúng chỗ này.

    Luật một câu: **bản nhìn được giữ khi nó vẫn ngắn như một phụ đề; dài hơn thế thì màn
    hình nhận đúng bản đã nói.**

    Vì sao không ép bằng nhau vô điều kiện, như bản đầu của PR #221: ép thế thì màn hình
    mất vế `"Nói mỗi mức cũng được, ví dụ \"mức 2\"."` của câu hỏi lại — vế **cố ý chỉ
    dành cho màn hình**, vì ví dụ trong ngoặc kép chỉ có nghĩa khi nhìn thấy dấu ngoặc.
    Đó là một trong ba thành phần mà #148 xác định là cần thiết, và #354 khoá bằng test.
    Ép bằng nhau là đổi một lỗi (đoạn sổ tay dài) lấy một lỗi khác (câu hỏi lại cụt).

    Trần dùng `MAX_SPOKEN_CHARS` — cùng ngân sách với câu nói, nên hai kênh so được với
    nhau bằng một thước. Đo được trên hai đầu của dải:

        clarify          bản nhìn 119 ký tự  <= 240  -> giữ, ví dụ còn
        tra sổ tay       bản nhìn 914 ký tự   > 240  -> lấy bản nói (166 ký tự)

    Không có liệt kê nhánh nào ở đây: một luật, áp cho mọi lượt.
    """
    hien = result.get("display_text") or result.get("response_text") or ""
    if not isinstance(hien, str):
        return noi
    return hien if 0 < len(hien) <= MAX_SPOKEN_CHARS else noi


def cau_de_noi(result: dict[str, Any]) -> str:
    """Câu thật sự đưa ra loa: bản ngắn, trừ khi luật im lặng bịt nó lại.

    Chỗ **duy nhất** cả hai đường cùng đọc — `emit_turn_lifecycle` gọi TTS bằng state, còn
    `assistant_response_payload` dựng câu cho WS. Sửa mỗi payload thì loa **vẫn đọc**, đúng
    thứ spec §3.5 đang cố chặn.
    """
    return "" if im_lang(result) else cau_ngan(result)


def assistant_response_payload(result: dict[str, Any]) -> dict[str, Any]:
    # Yêu cầu nhóm 21/08: **một** chuỗi cho cả hai trường — màn hình là **phụ đề** của
    # thứ vừa được đọc lên, không phải chỗ đọc lại cả đoạn sổ tay.
    #
    # Hai trường vẫn còn trên dây vì `api_spec.md` khai cả hai và bỏ một trường là phá
    # hợp đồng P0 — nhưng chúng mang cùng một chuỗi, và **chỗ này** là nơi bất biến ấy
    # được giữ. Khoá ở `compose_node` thôi thì chưa đủ: bản trước dựng `display_text` từ
    # `response_text`, nên một node trả đúng vẫn ra dây sai.
    #
    # Bản được giữ là bản NÓI, không phải `response_text`. Lý do đo được 13/08 sau khi
    # cài Piper: đọc nguyên đoạn trích ra 65,6 giây audio và một `assistant.speech`
    # 4,60 MB. Đường lui cho node cũ (`approvals.py` dựng payload bằng tay) nay có TRẦN
    # — xem `cau_ngan`, đó là chỗ blocker thứ hai của @thanhpro82 được đóng.
    noi = cau_ngan(result)
    return {
        "display_text": cau_hien(result, noi),
        # ...trừ đúng một ca, và nó KHÔNG phá bất biến trên: luật im lặng của ADR-028 bịt
        # kênh NÓI khi lượt do mic tự mở bắt được mà xe không hiểu (`X-Capture-Mode: auto`).
        #
        # Màn hình vẫn giữ câu, có chủ ý — hai lý do:
        #   1. màn hình không chen vào cuộc nói chuyện của ai, nên lý do im lặng không áp;
        #   2. nó là dấu vết duy nhất để tài xế hiểu vì sao vòng đếm ngược vừa tắt.
        # Bất biến của #221 nói màn hình **không dài hơn** lời nói; nó không nói màn hình
        # phải câm theo. `noi` ở đây đã là bản ngắn, nên phụ đề vẫn đúng nghĩa phụ đề.
        "speak_text": cau_de_noi(result),
        "has_more_to_read": bool(result.get("has_more_to_read")),
        # FE được mở mic ngắn để tài xế nói tiếp, khỏi phải lặp wake word. Cùng lý do
        # tồn tại với `has_more_to_read` ngay trên: tín hiệu chỉ nằm ở kênh nói thì client
        # nhìn màn hình không có gì để hành động.
        #
        # Chủ sở hữu DUY NHẤT của quyết định này là `src/agents/nghe_tiep.py`, và nó đọc
        # kết cục CUỐI của lượt. `route_node` cố ý không ghi trường này nữa: nó không thấy
        # `completed`, mà `completed` là ~90% lượt và là ca chính của cả tính năng.
        #
        # Backend KHÔNG phụ thuộc vào việc FE có mở hay không: rào chắn `mau_slot` chạy
        # trên mọi lượt. Cờ này chỉ là lời mời, không phải một nửa của cổng an toàn.
        "mo_mic_ngan": con_nghe_tiep(result),
        "routine_preview": result.get("routine_preview"),
        # #385: có cấu trúc CHỈ khi `routine_ma_loi == "chua_dat_dia_diem"` — xem
        # docstring `RoutineSetupRequiredData`.
        "routine_setup_required": result.get("routine_setup_required"),
        "citations": [
            {
                # Thiếu `citation_id` thì FE có thẻ citation nhưng không có id để gọi
                # `GET /citations/{id}` (`turn/real.ts:223`) — thẻ hiện ra mà bấm không
                # được.
                "citation_id": citation.citation_id,
                "document_title": citation.document_title,
                "section": citation.section,
                "page": citation.page,
                "excerpt": citation.excerpt,
                "retrieval_score": citation.retrieval_score,
            }
            for citation in (result.get("citations") or [])
        ],
        "outcomes": [
            {"step_id": step.step_id, "status": _wire_tool_status(step)} for step in result.get("step_results", [])
        ],
    }


async def _emit_plan_ready(
    bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, plan: Any, *, requires_approval: bool
) -> None:
    """`plan.ready` — docs/api_spec.md:561,620.

    Sự kiện này thuộc **giai đoạn định tuyến**, phát trước khi rẽ nhánh chính sách,
    nên nó bắn cho mọi lượt điều khiển chứ không riêng lượt cần duyệt. Đó là lý do
    `requires_approval` là boolean chứ không phải một cờ luôn đúng — S3 cũng có kế
    hoạch, nó bị chặn *sau khi* đã lập, và tài xế cần thấy thứ bị chặn là gì.

    `summary` là **cụm động từ** ghép từ `describe_step`, cố ý **không** dùng
    `prompt_text` của approval record: `frontend/.../HitlModal.tsx:59` render
    `Bạn xác nhận: {summary}?`, nên nhét một câu hoàn chỉnh vào sẽ ra câu hỏi lồng
    trong câu hỏi.

    `route_kind` luôn là `"action"` ở P0. Enum còn `manual`/`response`, nhưng bảng
    máy trạng thái chuẩn (api_spec.md:620-621) chỉ đặt `plan.ready` ở nhánh điều
    khiển — nhánh tra sổ tay đi thẳng `retrieving` → `composing` — và mock của FE
    (`turn/mock.ts:389`, `mock.test.ts:167`) khoá đúng chiều đó.

    `steps` cho client biết **cái gì vừa được lập kế hoạch**, đủ để IVI tự chuyển sang
    màn hình liên quan. Backend cố ý chỉ phát `domain` và `tool`, **không** phát tên
    màn hình: `hvac` là tri thức của xe, `"vehicle"` là tri thức của layout. Cùng ranh
    giới mà `ui.policy` đang giữ — BE đưa dữ kiện, FE quyết cách hiển thị — nên đổi
    layout không kéo theo sửa backend và sửa test backend.

    **`steps` ở đây KHÔNG phải tín hiệu để đổi màn.** Event này phát ở giai đoạn định
    tuyến, trước nhánh chính sách, nên nó bắn cho cả lượt S3. Client chuyển màn ngay
    khi nhận nó sẽ mở YouTube xong rồi mới bị chặn — luật an toàn thành trang trí.
    Mốc đúng là `tool.result` với `status="completed"`; `steps` chỉ là bảng tra để
    client biết `step_id` ấy vừa làm gì (ADR-023, `docs/api_spec.md` §Driver
    server-event allowlist).

    `args` đi kèm vì `domain` không đủ để phân biệt: `open_app` có `domain=None`, nên
    thiếu args thì client không biết là YouTube hay Spotify. Nó **không** mở rộng bề
    mặt lộ dữ liệu — `summary` ngay bên cạnh đã được ghép từ `describe_step(tool, args)`,
    tức nội dung args vốn đã nằm trong chính event này dưới dạng câu chữ.
    """
    await bus.publish(
        session_id,
        "plan.ready",
        turn_id,
        trace_id,
        {
            "route_kind": "action",
            "plan_id": plan.plan_id,
            "summary": " rồi ".join(describe_step(step.tool, step.args) for step in plan.steps),
            "requires_approval": requires_approval,
            "steps": [
                {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "domain": get_spec(step.tool).domain,
                    "args": step.args,
                }
                for step in plan.steps
            ],
        },
    )


#: Trần ký tự cho văn bản đưa vào TTS.
#:
#: Đây là **lưới cuối**, không phải chỗ quyết định nói gì — `compose_node` mới là chỗ
#: đó. Có nó vì đo được ngày 13/08 sau khi cài Piper: một lượt tra sổ tay sinh ra
#: `assistant.speech` **4,60 MB** trong một khung WebSocket (65,6 giây audio). Hậu quả
#: đo được: client dùng trần khung 1 MiB mặc định bị rớt kết nối giữa lượt, và ring
#: buffer 200 event của ADR-014 có thể ngốn hàng trăm MB mỗi phiên.
#:
#: 400 ký tự ≈ 20 giây đọc, theo tốc độ đo thật 20,1 ký tự/giây của giọng vi_VN-piper.
#:
#: **Trần này một mình KHÔNG đủ** — xem `MAX_SPEECH_BYTES` ngay dưới.
MAX_SPEECH_CHARS = 400

#: Trần **byte** cho audio, và đây mới là trần giữ đúng bất biến.
#:
#: Đo socket thật 14/08 (đúng thứ Thành đòi ở PR #109 — *"không chỉ suy luận từ kích
#: thước payload"*): 240 ký tự → event **656,9 KiB = 64,2%** khung 1 MiB. Ngoại suy
#: tuyến tính thì `MAX_SPEECH_CHARS = 400` cho ra **1.102 KiB = 107,6%** — tức lưới
#: cuối vẫn cho vượt khung. Ước từ payload trước đó nói 130 KiB; **lệch 5 lần**, vì
#: bản ước đo nhánh chỉ nói câu dẫn 46 ký tự.
#:
#: Ký tự là **sai đơn vị**: thứ phải giữ dưới trần là số byte trên dây, mà tỷ lệ
#: byte/ký tự phụ thuộc giọng, tần số lấy mẫu và ngôn ngữ — cả ba đổi được mà không ai
#: nhớ sửa một hằng số tính bằng ký tự.
#:
#: 700 KiB = 68% khung, chừa 32% cho base64 phình 4/3 đã tính, envelope JSON, và
#: header WebSocket.
#:
#: **Đo lại 17/08, lần này có hiện vật:**
#: `eval/results/voice-payload/20260817T043442.858549Z` (`scripts/report_voice_payload.py`).
#: Câu trả lời sổ tay dài nhất → 237 ký tự → **650,4 KiB = 63,5% khung**, và client giữ
#: nguyên `max_size` mặc định **không rớt kết nối**. Con số 64,2% ở trên là con số đúng;
#: `WORKLOG.md` 14/08 ghi 667,7 KiB / 65,2% cho cùng phép đo — lệch, và không có run dir
#: nào để phân xử. Đó chính là lý do phép đo ấy phải được làm lại thành một run.
MAX_SPEECH_BYTES = 700 * 1024


def audio_qua_lon(wav_bytes: bytes | None) -> bool:
    """Audio có vượt trần byte không.

    Tách hàm để test được mà không phải dựng cả một lượt, và để chỗ quyết định chỉ có
    **một**: hai chỗ tự tính lại sẽ lệch nhau đúng lúc không ai nhìn.
    """
    if not wav_bytes:
        return False
    # base64 phình 4/3. Ước ở đây thay vì encode thật: encode một WAV vài trăm KB chỉ
    # để đo rồi vứt là trả giá cho một phép chia.
    return len(wav_bytes) * 4 // 3 > MAX_SPEECH_BYTES


_SPEECH_SENTENCE_ENDS = (".", "!", "?", "\n")


def _cat_o_bien_cau(text: str, limit: int) -> str:
    """Cắt tại dấu kết câu gần nhất trước `limit`; không có thì cắt thẳng."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(end) for end in _SPEECH_SENTENCE_ENDS)
    return (head[: cut + 1] if cut > 0 else head).rstrip()


async def synthesize_speech(turn_id: str, trace_id: str, text: str) -> bytes | None:
    """TTS best-effort cho một lượt: không bao giờ raise, không chặn assistant.response/turn.completed.

    Xem docs/superpowers/specs/2026-08-11-wire-tts-pipeline-design.md §Fail-open.
    """
    if not text.strip():
        return None
    if len(text) > MAX_SPEECH_CHARS:
        # Cảnh báo chứ không im lặng: chạm trần ở đây nghĩa là composer đã đưa xuống
        # một câu dài hơn thứ nghe nổi, tức lỗi ở tầng trên. Lưới này chỉ để nó không
        # thành 4,60 MB trên dây.
        logger.warning(
            "speak_text %d ký tự vượt trần %d cho turn %s — composer lẽ ra phải rút gọn trước",
            len(text),
            MAX_SPEECH_CHARS,
            turn_id,
        )
        text = _cat_o_bien_cau(text, MAX_SPEECH_CHARS)
    started = time.perf_counter()
    try:
        wav_bytes = await asyncio.to_thread(voice.synthesize_wav, text)
    except Exception:
        logger.warning("TTS synthesize thất bại cho turn %s", turn_id, exc_info=True)
        return None
    get_trace_store().record_stage(trace_id, "tts", (time.perf_counter() - started) * 1000)
    if audio_qua_lon(wav_bytes):
        # Fail-open: bỏ AUDIO chứ không bỏ cả lượt. `assistant.response` vẫn mang
        # `display_text` — nội dung thật. Chặn cả lượt vì audio quá to là biến một sự
        # cố thẩm mỹ thành mất dữ liệu.
        logger.warning(
            "audio %d byte vượt trần %d cho turn %s — bỏ assistant.speech, giữ nguyên câu trả lời",
            len(wav_bytes),
            MAX_SPEECH_BYTES,
            turn_id,
        )
        return None
    return wav_bytes


async def _publish_assistant_response(
    bus: IviEventBus,
    session_id: str,
    turn_id: str,
    trace_id: str,
    response_payload: dict[str, Any],
    wav_bytes: bytes | None,
) -> None:
    """Phát `assistant.speech` (nếu có audio) rồi `assistant.response`.

    `assistant.speech` không nằm trong 4 field cố định của `assistant.response`
    (docs/api_spec.md:568 — closed schema) nên đi qua một event type riêng,
    cùng interface `WS /ws/ivi` đã có (#11 trong 14 interface P0,
    docs/api_spec.md:52) — không thêm HTTP endpoint mới.

    Nhận thẳng `response_payload` đã dựng sẵn (thay vì `result` của graph) để
    `src/api/approvals.py` cũng gọi được hàm này cho nhánh reject — nhánh đó không có
    một `result` đầy đủ của graph, chỉ có một payload dựng tay.
    """
    await _phat_tieng_noi(bus, session_id, turn_id, trace_id, wav_bytes)
    await bus.publish(session_id, "assistant.response", turn_id, trace_id, response_payload)


async def _phat_tieng_noi(
    bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, wav_bytes: bytes | None
) -> None:
    """Phát `assistant.speech` nếu có audio. Không có thì im lặng bỏ qua — best-effort.

    Tách khỏi `_publish_assistant_response` vì nhánh chờ duyệt S2 có **tiếng nói mà
    không có `assistant.response`**: câu hỏi duyệt đi ra bằng `assistant.status`, không
    bằng một câu trả lời (issue #215).
    """
    if wav_bytes is None:
        return
    await bus.publish(
        session_id,
        "assistant.speech",
        turn_id,
        trace_id,
        {"audio_base64": base64.b64encode(wav_bytes).decode("ascii"), "mime_type": "audio/wav"},
    )


#: `outcome` mà một lượt **không** được kết thúc bằng `turn.completed` (issue #375).
#:
#: Quyết định PM/PO trên #375: `validation_denied` và `execution_failed` là **lượt hỏng**
#: — phát `turn.failed` kèm mã lỗi. `clarify`, `denied`, `not_control`,
#: `grounded_refusal` vẫn là `completed`: đó là phản hồi sản phẩm hợp lệ, chỉ không có
#: side effect. Gọi chúng là hỏng sẽ biến mọi lượt hỏi sổ tay thành một lượt lỗi trên
#: dashboard kỹ sư.
#:
#: `execution_failed` đã đi đúng đường từ trước — nhánh có `action_plan` phát
#: `turn.failed` kèm `EXECUTION_FAILED`. Nó có mặt ở đây để bảng này là **danh sách đầy
#: đủ những gì PM đã chốt**, và để test tính chất canh được cả hai; không phải để thêm
#: một nhánh phát thứ hai cho nó.
#:
#: `vehicle_state_unavailable` **không** nằm đây dù nó cũng phát `turn.failed`: PM chốt
#: nó ngoài phạm vi đợt này, và nhánh riêng của nó mang mã `MQTT_UNAVAILABLE` — một lỗi
#: hạ tầng, khác loại với hai cái trên.
OUTCOME_LUOT_HONG: dict[str, str] = {
    "validation_denied": "VALIDATION_DENIED",
    "execution_failed": "EXECUTION_FAILED",
}


async def emit_turn_lifecycle(
    bus: IviEventBus,
    session_id: str,
    turn_id: str,
    trace_id: str,
    result: dict[str, Any],
    *,
    plan_already_announced: bool = False,
    retrieving_already_announced: bool = False,
    composing_already_announced: bool = False,
) -> None:
    """Dịch `result` của `graph.ainvoke(...)` thành chuỗi sự kiện `/ws/ivi`.

    `plan_already_announced=True` cho **lượt resume sau khi duyệt approval**: lượt đó
    đã phát `plan.ready` ở lần gọi đầu (nhánh `__interrupt__`), và một lượt chỉ được
    có đúng một `plan.ready`.

    Máy trạng thái chuẩn (`api_spec.md` §Normative asynchronous voice-turn state
    machine) đặt `plan.ready` ở **stage "Control route/plan"**, trước nhánh policy;
    hai stage sau nó — "S2 pending" và "Successful execution" — đều **không** liệt kê
    nó. Cùng tài liệu còn ghi thẳng "no `plan.ready`" cho ca S2 thứ hai, tức đây là
    event một-lần-mỗi-lượt chứ không phải mô tả trạng thái hiện thời.

    Rút gọn "Normative asynchronous voice-turn state machine" (docs/api_spec.md) theo
    phạm vi minimal-slice đã chốt — xem
    docs/superpowers/specs/2026-08-09-voice-turn-api-design.md. Các outcome fail-closed
    của tầng approval (`_CANCEL_REASON_BY_OUTCOME`) kết thúc bằng `turn.canceled` kèm
    `reason` cụ thể, đúng như api_spec.md mô tả.

    `retrieving_already_announced`/`composing_already_announced` (issue #346): cùng ý
    tưởng với `plan_already_announced`, nhưng cho hai trạng thái mà `src/agents/graph.py`
    giờ phát SỐNG ngay khi node `rag`/`compose` bắt đầu chạy — thay vì đợi hàm này dịch
    lại sau khi `graph.ainvoke()` đã trả về. Hai lời gọi thật từ `src/api/turns.py` luôn
    truyền `True` (node đã phát rồi thì đừng phát trùng); test/caller gọi hàm này trực
    tiếp với `result` tự tạo (không qua graph thật) giữ nguyên mặc định `False` — đúng
    hành vi hồi tố cũ, không cần sửa test.
    """
    await _bao_mat_xe_neu_co(bus, session_id, turn_id, trace_id)
    pending = result.get("__interrupt__")
    if pending:
        payload = pending[0].value
        plan = as_action_plan(result["action_plan"])
        await _emit_plan_ready(bus, session_id, turn_id, trace_id, plan, requires_approval=True)
        # Đọc câu hỏi duyệt thành tiếng (issue #215). Trước bản này nhánh S2 `return`
        # ngay dưới đây, **trước** dòng `synthesize_speech` ở cuối hàm — nên xe hỏi tài
        # xế một việc S2 trong im lặng, đúng khoảnh khắc duy nhất mà hệ thống bắt buộc
        # phải có câu trả lời của con người. Test cũ đọc đúng ba event và không ai hỏi
        # tài xế có nghe được gì không.
        #
        # **TRƯỚC** `approval.required`, và thứ tự này là điều kiện đúng đắn chứ không
        # phải thẩm mỹ: IVI mở mic ngay khi `pendingApproval` được set, mà với lượt gõ
        # chữ thì `afterTranscriptHold` không hoãn gì cả. Phát sau thì có một cửa sổ mà
        # IVI thấy chưa có audio nào -> mở mic ngay -> rồi xe mới bắt đầu đọc, và micro
        # thu đúng giọng của xe. Đó chính là bug mà cổng chờ-audio của #211 sinh ra để
        # chặn.
        await _phat_tieng_noi(
            bus,
            session_id,
            turn_id,
            trace_id,
            await synthesize_speech(turn_id, trace_id, payload["prompt_text"]),
        )
        await bus.publish(
            session_id,
            "approval.required",
            turn_id,
            trace_id,
            {
                "approval_id": payload["approval_id"],
                "plan_id": payload["plan_id"],
                "approved_vehicle_state_version": plan.vehicle_state_version,
                "actions": payload["steps_summary"],
                "expires_at": payload["expires_at"],
            },
        )
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "waiting_approval", "message": payload["prompt_text"]},
        )
        return

    # Đọc `speak_text`, KHÔNG đọc `response_text`. Hai kênh tách nhau từ Task 1 của
    # `docs/superpowers/plans/2026-08-13-speak-text-an-toan-cho-nhanh-so-tay.md`:
    # màn hình nhận nguyên văn (ADR-015), loa nhận bản ngắn.
    #
    # `or response_text` là đường lui cho các node/test cũ chưa trả `speak_text`.
    # `cau_de_noi` áp luật im lặng của spec §3.5: lượt bắt tự động mà xe không hiểu thì
    # không đưa gì ra loa. Đọc thẳng `result["speak_text"]` ở đây là bỏ qua luật ấy và xe
    # vẫn chen vào cuộc nói chuyện — payload im mà loa vẫn nói.
    wav_bytes = await synthesize_speech(turn_id, trace_id, cau_de_noi(result))

    outcome = result.get("outcome", "not_control")

    if outcome in ("completed", "execution_failed"):
        # `requires_approval=False`: `plan.ready` mô tả trạng thái *lúc định tuyến*, và
        # lượt tới được đây là đã qua nhánh duyệt (hoặc không cần duyệt).
        #
        # Bỏ qua khi lượt này là bản resume: lần gọi đầu đã phát `plan.ready` ở nhánh
        # `__interrupt__` rồi. Không có chốt này thì một lượt S2 phát **hai**
        # `plan.ready` cùng `plan_id` (issue #94) — client render thẻ kế hoạch hai lần,
        # và hai chỗ trong ring buffer 200 event của ADR-014 bị tiêu cho một thông tin.
        if not plan_already_announced:
            await _emit_plan_ready(
                bus, session_id, turn_id, trace_id, as_action_plan(result["action_plan"]), requires_approval=False
            )
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "executing", "message": "Đang thực hiện lệnh."},
        )
        for step in result.get("step_results", []):
            await bus.publish(
                session_id,
                "tool.result",
                turn_id,
                trace_id,
                {
                    "step_id": step.step_id,
                    "command_id": step.command_id,
                    "status": _wire_tool_status(step),
                    "observed_state_version": step.observed_state_version,
                    "error_code": step.error_code,
                },
            )
        await _publish_assistant_response(
            bus, session_id, turn_id, trace_id, assistant_response_payload(result), wav_bytes
        )
        if outcome == "completed":
            await bus.publish(
                session_id, "turn.completed", turn_id, trace_id, {"status": "completed", "completed_at": now_iso()}
            )
        else:
            await bus.publish(
                session_id,
                "turn.failed",
                turn_id,
                trace_id,
                {"status": "failed", "code": "EXECUTION_FAILED", "completed_at": now_iso()},
            )
        return

    if outcome == "blocked":
        plan = as_action_plan(result["action_plan"])
        await _emit_plan_ready(bus, session_id, turn_id, trace_id, plan, requires_approval=False)
        await bus.publish(
            session_id,
            "action.blocked",
            turn_id,
            trace_id,
            {"plan_id": plan.plan_id, "code": "SAFETY_BLOCKED", "reason": result.get("response_text", "")},
        )
        await _publish_assistant_response(
            bus, session_id, turn_id, trace_id, assistant_response_payload(result), wav_bytes
        )
        await bus.publish(
            session_id, "turn.completed", turn_id, trace_id, {"status": "completed", "completed_at": now_iso()}
        )
        return

    if outcome == "vehicle_state_unavailable":
        # `safety_node` từ chối vì không đọc được trạng thái xe. Đây là **lỗi hệ
        # thống**, không phải lượt bị huỷ theo ý ai — nên `turn.failed`, không phải
        # `turn.canceled`. Mã `MQTT_UNAVAILABLE` đã có sẵn trong api_spec.md:659.
        await _publish_assistant_response(
            bus, session_id, turn_id, trace_id, assistant_response_payload(result), wav_bytes
        )
        await bus.publish(
            session_id,
            "turn.failed",
            turn_id,
            trace_id,
            {"status": "failed", "code": "MQTT_UNAVAILABLE", "completed_at": now_iso()},
        )
        return

    cancel_reason = _CANCEL_REASON_BY_OUTCOME.get(outcome)
    if cancel_reason is not None:
        # Approval bị từ chối/hết hạn/vô hiệu hoá sau khi graph resume: lượt kết thúc là
        # `canceled` với lý do, **không** phải `completed` — zero side effect đã xảy ra.
        await _publish_assistant_response(
            bus, session_id, turn_id, trace_id, assistant_response_payload(result), wav_bytes
        )
        await bus.publish(
            session_id,
            "turn.canceled",
            turn_id,
            trace_id,
            {"status": "canceled", "reason": cancel_reason, "completed_at": now_iso()},
        )
        return

    if outcome in ("grounded_answer", "grounded_continue", "grounded_refusal") and not retrieving_already_announced:
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "retrieving", "message": "Đang tra sổ tay xe."},
        )

    if not composing_already_announced:
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "composing", "message": "Đang soạn câu trả lời."},
        )
    await _publish_assistant_response(bus, session_id, turn_id, trace_id, assistant_response_payload(result), wav_bytes)
    # Nhánh cuối gộp mọi outcome không rơi vào nhánh sớm — `not_control`, `clarify`,
    # `offer`, `grounded_answer`, `grounded_refusal`… **và** `validation_denied`. Trước
    # #375, cả nhóm cùng nhận `turn.completed`, nên một lượt có plan chết ở `validate_args`
    # được đếm là thành công trên `/metrics/summary` và hiện `status: completed` trên
    # trace. Câu trả lời vẫn được đọc ra trước đó — lượt vẫn kết thúc, IVI vẫn dọn giao
    # diện — chỉ nhãn kết thúc là đổi.
    ma_loi = OUTCOME_LUOT_HONG.get(outcome)
    if ma_loi is not None:
        await bus.publish(
            session_id,
            "turn.failed",
            turn_id,
            trace_id,
            {"status": "failed", "code": ma_loi, "completed_at": now_iso()},
        )
        return
    await bus.publish(
        session_id, "turn.completed", turn_id, trace_id, {"status": "completed", "completed_at": now_iso()}
    )


# --- Voice approval intent (issue #107) -------------------------------------
#
# Cac ham nay khong cham `ApprovalStore` va khong resume graph — no chi phat. Nhung tu
# #191 thi **luot** co the da chot truoc khi goi toi day (cum ro rang, hoac moi cum tu
# choi), nen `api_spec.md:278` khong con doc la "IVI luon goi REST": co `committed` de
# phan biet. Xem `emit_approval_intent_handoff`.
#
# Ba nhanh terminal cua `api_spec.md:643-644`, moi nhanh dung MOT su kien terminal.


async def emit_approval_intent_handoff(
    bus: IviEventBus,
    session_id: str,
    turn_id: str,
    trace_id: str,
    *,
    approval_id: str,
    original_turn_id: str,
    decision: str,
    approved_vehicle_state_version: int,
    committed: bool,
    speak_text: str,
) -> None:
    """Nhánh thành công: `approval.intent.detected` → `assistant.response` → `turn.completed`.

    Hàm này vẫn không tự chốt gì — nhưng từ #191, **lượt** thì có thể đã chốt trước khi
    gọi tới đây. `committed` nói ra đúng sự khác biệt ấy, và nó là trường **duy nhất**
    IVI có để biết: hai nhánh giống hệt nhau ở cả bốn trường còn lại.

    Thiếu nó thì IVI phải đoán, và cách đoán rẻ nhất — luôn gọi REST — chính là đường
    vòng qua bất đối xứng của #191: tài xế nói `"ừ"`, backend **cố ý** không chốt, rồi
    IVI chốt hộ. Đó là issue #207a, và nó nằm mở suốt một ngày với suite FE 212/212 xanh
    vì không test nào của cả hai phía nhìn được sang phía kia.
    """
    await bus.publish(
        session_id,
        "approval.intent.detected",
        turn_id,
        trace_id,
        {
            "approval_id": approval_id,
            "original_turn_id": original_turn_id,
            "decision": decision,
            "approved_vehicle_state_version": approved_vehicle_state_version,
            "committed": committed,
        },
    )
    await _publish_assistant_response(
        bus,
        session_id,
        turn_id,
        trace_id,
        {
            "display_text": speak_text,
            "speak_text": speak_text,
            "has_more_to_read": False,
            "citations": [],
            "outcomes": [],
        },
        None,
    )
    await bus.publish(
        session_id, "turn.completed", turn_id, trace_id, {"status": "completed", "completed_at": now_iso()}
    )


#: Mã lỗi báo phiên **mất quyền lái giữa chừng** vì hết hạn thuê xe.
#:
#: Tách khỏi `vehicle_pool_exhausted` (`vehicle_gateway.POOL_CAN_KIET`) chứ không dùng
#: chung, dù cả hai đều dẫn tới chế độ chỉ xem: hai mã ấy là hai câu giải thích khác
#: nhau. *"Hết xe mô phỏng khả dụng"* đúng cho người **chưa bao giờ** được cấp xe, và
#: nói sai hẳn với người **vừa mất** chiếc xe mình đang lái — họ cần biết xe đã được
#: cấp cho người khác, không phải rằng hệ thống hết chỗ. Dùng chung một mã là ép FE
#: hiển thị một trong hai câu ấy sai.
MAT_XE_CODE = "VEHICLE_LEASE_EXPIRED"


async def _bao_mat_xe_neu_co(bus: IviEventBus, session_id: str, turn_id: str, trace_id: str) -> None:
    """Phát `error` khi phiên vừa mất xe — trước mọi event khác của lượt.

    ## Vì sao ở đây

    Chỗ **phát hiện** mất xe là `get_graph` (`src/api/session_state.py`), một hàm sync;
    chỗ **phát event theo phiên** là hàm này. Nối hai chỗ ấy bằng một cờ đọc-rồi-xoá
    giữ được cả hai tính chất: phát hiện vẫn nằm ở một chỗ duy nhất (không phải bốn cửa
    vào cùng nhớ), và việc phát event vẫn nằm ở một chỗ duy nhất.

    ## Vì sao dùng `error` chứ không thêm một loại event mới

    `error` đã có trong allowlist tài xế (`docs/api_spec.md` §Driver server-event
    allowlist) với đúng shape cần dùng, và FE đã map sẵn nó
    (`frontend/src/lib/services/turn/real.ts`). Thêm một `type` mới là mở rộng hợp đồng
    WS — phải sửa api_spec và mọi validator — để nói một chuyện mà hợp đồng hiện tại nói
    được rồi.

    `terminal=False`: lượt này **vẫn chạy tiếp** và vẫn trả lời được (tra sổ tay, đọc
    trạng thái xe vẫn hoạt động ở chế độ chỉ xem). Chỉ lệnh điều khiển bị từ chối, và
    việc ấy đã có `tool.result` nói riêng. `retryable=True` vì xe có thể rảnh lại.

    `details.can_drive=False` là thứ FE cần để lật huy hiệu "Chế độ chỉ xem" và khoá
    control — hai thứ đó đã bám sẵn `canDrive`, vốn tới nay chỉ được đặt **một lần** lúc
    tạo phiên nên không bao giờ đổi giữa chừng.
    """
    from src.api.session_state import lay_canh_bao_mat_xe  # noqa: PLC0415 — vòng import

    if not lay_canh_bao_mat_xe(session_id):
        return
    await bus.publish(
        session_id,
        "error",
        turn_id,
        trace_id,
        {
            "code": MAT_XE_CODE,
            "message": "Hết hạn thuê xe — xe đã được cấp cho người khác. Bạn đang ở chế độ chỉ xem.",
            "retryable": True,
            "terminal": False,
            "details": {"can_drive": False},
        },
    )


async def emit_approval_intent_ambiguous(
    bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, *, message: str
) -> None:
    """Nhánh mơ hồ: `assistant.speech` → `error(terminal=true)` → `turn.failed`.

    Cố ý làm hỏng lượt thay vì đoán. Đoán giữa "đồng ý" và "hủy" là quyết hộ tài xế một
    việc S2 — và `turn.failed` khiến IVI hỏi lại, đúng thứ cần ở đây.

    ## Vì sao có tiếng (#212)

    `error` không đi qua `_publish_assistant_response`, nên trước 31/08 câu mời nói lại
    chỉ **hiện chữ**. Sau #211 thì mic **tự mở lại** ở đúng nhánh này: mic bật, đèn thu
    sáng, và xe im. Tài xế đang lái không nhìn màn hình sẽ không biết vì sao mic vừa bật.
    Trước #211 lỗ này lành hơn — mic tắt, họ đằng nào cũng phải nhìn màn hình để chạm nút.

    **`assistant.speech` chứ không `assistant.response`:** lượt này *hỏng*. Mượn
    `assistant.response` — một closed schema dành cho câu trả lời của một lượt đã hoàn
    tất — là nói rằng lượt có câu trả lời trong khi nó vừa thất bại. Tiền lệ cùng hình
    dạng đã có: nhánh chờ duyệt S2 phát tiếng mà không có `assistant.response` (#215,
    xem `_phat_tieng_noi`). Ở đây kênh chữ do `error` lo; thứ còn thiếu đúng là kênh tiếng.

    **Tiếng phải đi TRƯỚC `error`**, và đó là ràng buộc chứ không phải khẩu vị: FE mở lại
    mic trong một effect phụ thuộc `lanMoLaiMic`, mà giá trị ấy đổi khi `error` tới. Effect
    đọc `activeSpeechRef.current` để quyết định chờ `ended` hay mở mic ngay. Nếu
    `assistant.speech` tới sau, ref còn rỗng lúc effect chạy → mic mở ngay → giọng đọc chen
    vào giữa lúc đang thu, đúng thứ ta thêm tiếng để tránh.

    Fail-open: mất tiếng là mất tiện nghi, mất `turn.failed` là treo lượt. Nên TTS hỏng —
    kể cả khi nó raise, dù `synthesize_speech` hứa là không — vẫn ra đủ hai sự kiện cũ.
    """
    try:
        wav_bytes = await synthesize_speech(turn_id, trace_id, message)
    except Exception:
        logger.warning("TTS nhánh mơ hồ thất bại cho turn %s", turn_id, exc_info=True)
        wav_bytes = None
    await _phat_tieng_noi(bus, session_id, turn_id, trace_id, wav_bytes)
    await bus.publish(
        session_id,
        "error",
        turn_id,
        trace_id,
        {
            "code": "APPROVAL_INTENT_AMBIGUOUS",
            "message": message,
            "retryable": True,
            "terminal": True,
            "details": {},
        },
    )
    await bus.publish(
        session_id,
        "turn.failed",
        turn_id,
        trace_id,
        {"status": "failed", "code": "APPROVAL_INTENT_AMBIGUOUS", "completed_at": now_iso()},
    )


async def emit_approval_intent_not_pending(
    bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, *, message: str
) -> None:
    """Nhánh không có gì đang chờ: `assistant.response` → `turn.canceled(approval_not_pending)`.

    `canceled` chứ không phải `completed`: tài xế trả lời một câu hỏi không tồn tại, và
    `reason` nói đúng vì sao chẳng có gì xảy ra. `api_spec.md:585` đã có sẵn mã này
    trong enum của `turn.canceled`.
    """
    await _publish_assistant_response(
        bus,
        session_id,
        turn_id,
        trace_id,
        {"display_text": message, "speak_text": message, "has_more_to_read": False, "citations": [], "outcomes": []},
        None,
    )
    await bus.publish(
        session_id,
        "turn.canceled",
        turn_id,
        trace_id,
        {"status": "canceled", "reason": "approval_not_pending", "completed_at": now_iso()},
    )

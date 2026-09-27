"""`POST /api/v1/turns/voice` — chấp nhận audio bất đồng bộ, phát lifecycle qua `/ws/ivi`.

Bearer auth (driver-only), session ownership, `X-Schema-Version`, và `Idempotency-Key` đều
được xác thực — cùng cơ chế `submit_text_turn` dùng. Xem
docs/superpowers/specs/2026-08-12-turns-voice-auth-hardening-design.md cho lý do và ngữ
nghĩa idempotency của route bất đồng bộ này. `/ws/ivi` replay cursors vẫn chưa có; xem mục
"Out of scope" của docs/superpowers/specs/2026-08-09-voice-turn-api-design.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.agents.contracts import ActionPlan, as_action_plan
from src.agents.router import DeterministicControlRouter
from src.agents.voice_intent import doc_y_dinh_phe_duyet
from src.api.auth_deps import AuthenticatedUser, require_driver, require_idempotency_key, require_schema_version
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.api.session_state import get_graph, get_session_lock, get_session_record, get_store, get_vehicle, thread_config
from src.config import get_settings
from src.models.api import (
    ActionPlanData,
    ActionPlanStep,
    Meta,
    PendingApprovalData,
    TextTurnData,
    TextTurnEnvelope,
    TurnResponseData,
)
from src.models.vehicle import SCHEMA_VERSION
from src.services import voice
from src.services.idempotency import IdempotencyInProgress, IdempotencyRecord, fingerprint_for, get_idempotency_store
from src.services.ivi_events import (
    assistant_response_payload,
    emit_approval_intent_ambiguous,
    emit_approval_intent_handoff,
    emit_approval_intent_not_pending,
    emit_turn_lifecycle,
    get_event_bus,
    now_iso,
)
from src.services.trace_collector import record_graph_result
from src.services.trace_store import get_trace_store

logger = logging.getLogger(__name__)
router = APIRouter()

#: docs/api_spec.md mục "Voice turn: asynchronous acceptance" — P0 chỉ nhận 3 định dạng này.
#: So sánh theo **base media type** (bỏ parameter) vì `MediaRecorder` của browser gửi
#: `.type` có parameter (`audio/wav; codecs=1`), khớp chuỗi nguyên thì luôn 422.
#: GAP sẵn có: `audio/ogg` và `audio/pcm` nằm trong hợp đồng nhưng `src/services/voice.py`
#: chỉ parse được WAV (stdlib `wave`), nên lượt gửi hai loại đó luôn kết thúc ở
#: `transcript.final(unusable)` — giới hạn tầng STT, không thuộc phạm vi ticket này.
_ALLOWED_BASE_CONTENT_TYPES = frozenset({"audio/wav", "audio/ogg"})
#: `audio/pcm` không tự mô tả được: rate/channels/format nằm trong parameter và **chính
#: chúng** mang nghĩa, nên phải đủ cả ba (thứ tự tuỳ ý) mới nhận — `audio/pcm;rate=8000`
#: hay `audio/pcm` trơn đều bị từ chối.
_REQUIRED_PCM_PARAMETERS = frozenset({"rate=16000", "channels=1", "format=s16le"})

_TEXT_TURN_ROUTE = "POST /turns/text"
_VOICE_TURN_ROUTE = "POST /turns/voice"


def _record_end_to_end(trace_id: str, started: float) -> None:
    """Ghi `stage_latencies_ms.end_to_end`. Thuần quan sát, không bao giờ raise.

    Ghi ở **mọi** lối ra của lượt, kể cả lối lỗi: một lượt thất bại vẫn tốn thời
    gian của tài xế, và bỏ qua nó sẽ làm p95 chỉ phản ánh những lượt chạy trót lọt
    — đúng thứ không nên tin khi đọc dashboard.

    Phải gọi **trước** `emit_turn_lifecycle` và trước mọi `turn.failed`: sự kiện
    terminal làm `TraceCollector` seal trace rồi phát ngay cho `/ws/engineer`, nên
    ghi sau thì bản phát đi thiếu số.
    """
    get_trace_store().record_stage(trace_id, "end_to_end", (time.perf_counter() - started) * 1000)


class TextTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    text: str


def _action_plan_model(plan: ActionPlan) -> ActionPlanData:
    return ActionPlanData(
        schema_version=plan.schema_version,
        plan_id=plan.plan_id,
        session_id=plan.session_id,
        vehicle_id=plan.vehicle_id,
        vehicle_state_version=plan.vehicle_state_version,
        steps=[
            ActionPlanStep(
                step_id=step.step_id,
                ordinal=step.ordinal,
                tool=step.tool,
                args=step.args,
                safety_level=step.safety_level,
                depends_on=list(step.depends_on),
            )
            for step in plan.steps
        ],
        requires_approval=plan.requires_approval,
    )


def doc_che_do_bat(x_capture_mode: str | None) -> bool:
    """Lượt này có phải do mic **tự mở** bắt được không? Spec §3.5.

    Vắng header = `manual`, có chủ ý: client cũ không đổi hành vi một chút nào, và
    "không khai" phải nghĩa là chế độ **ồn ào hơn** chứ không phải chế độ im hơn — fail
    về phía nói, vì một trợ lý câm khó chẩn đoán hơn nhiều một trợ lý nói thừa.

    Chỉ nhận đúng chuỗi `auto` (không phân biệt hoa thường, bỏ khoảng trắng hai đầu). Mọi
    giá trị khác lui về `manual` chứ **không** ném lỗi: header là dữ liệu ngoài, và một
    lượt nói của tài xế không được chết vì một chuỗi sai chính tả.

    Vì sao tin lời khai của client ở đây, trong khi `mau_slot` (#363) từ chối tin: khác về
    **hướng**. Khai `auto` chỉ khiến xe im hơn, không bao giờ khiến nó dễ dãi hơn.
    """
    return (x_capture_mode or "").strip().casefold() == "auto"


def _is_accepted_content_type(content_type: str) -> bool:
    parts = content_type.split(";")
    base = parts[0].strip().lower()
    if base in _ALLOWED_BASE_CONTENT_TYPES:
        return True
    if base != "audio/pcm":
        return False
    parameters = {part.strip().lower() for part in parts[1:]}
    return _REQUIRED_PCM_PARAMETERS <= parameters


@router.post("/turns/voice", status_code=202, dependencies=[Depends(require_schema_version)])
async def submit_voice_turn(
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_driver),
    idempotency_key: str = Depends(require_idempotency_key),
    x_capture_mode: str | None = Header(default=None, alias="X-Capture-Mode"),
) -> dict:
    content_type = request.headers.get("content-type", "")
    request_id, trace_id = request_scoped_ids(request)

    if not _is_accepted_content_type(content_type):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INPUT_INVALID",
                    "message": f"Content-Type không hỗ trợ: {content_type!r}",
                    "retryable": False,
                },
                "meta": {"request_id": request_id},
                "trace_id": trace_id,
                "schema_version": SCHEMA_VERSION,
            },
        )

    session_record = get_session_record(session_id)
    if session_record is None or session_record.user_id != user.user_id:
        # Không phân biệt "session không tồn tại" với "session của người khác" —
        # tránh lộ enumeration, giống submit_text_turn.
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="session không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    audio_bytes = await request.body()

    # Đảm bảo simulator/graph của session tồn tại trước khi task nền cần tới.
    get_vehicle(session_id)
    get_graph(session_id)

    store = get_idempotency_store()
    # Body là bytes thô, không phải JSON — fingerprint qua nội dung + Content-Type thay vì
    # gọi fingerprint_for(body: dict) trực tiếp trên audio_bytes.
    fingerprint = fingerprint_for(
        {
            "session_id": session_id,
            "content_type": content_type,
            "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
        }
    )
    try:
        existing = await store.begin(user.user_id, _VOICE_TURN_ROUTE, idempotency_key, fingerprint)
    except IdempotencyInProgress as exc:
        raise ApiError(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="một request khác với cùng Idempotency-Key đang được xử lý, thử lại sau",
            retryable=True,
            request_id=request_id,
            trace_id=trace_id,
        ) from exc
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                message="Idempotency-Key đã dùng cho một request khác nội dung",
                request_id=request_id,
                trace_id=trace_id,
            )
        return existing.body

    try:
        turn_id = f"turn_voice_{uuid.uuid4().hex[:20]}"
        bat_tu_dong = doc_che_do_bat(x_capture_mode)
        background_tasks.add_task(_process_voice_turn, session_id, turn_id, trace_id, audio_bytes, bat_tu_dong)
        envelope = {
            "data": {"session_id": session_id, "turn_id": turn_id, "status": "accepted", "input_mode": "voice"},
            "meta": {"request_id": request_id, "realtime": "WS /ws/ivi"},
            "trace_id": trace_id,
            "schema_version": SCHEMA_VERSION,
        }
    except BaseException:  # noqa: BLE001 - CancelledError không kế thừa Exception, cùng lý do submit_text_turn
        await store.abandon(user.user_id, _VOICE_TURN_ROUTE, idempotency_key)
        raise

    await store.finish(
        user.user_id,
        _VOICE_TURN_ROUTE,
        idempotency_key,
        IdempotencyRecord(fingerprint=fingerprint, status_code=202, body=envelope),
    )
    return envelope


async def _process_voice_turn(
    session_id: str, turn_id: str, trace_id: str, audio_bytes: bytes, bat_tu_dong: bool = False
) -> None:
    bus = get_event_bus()
    # Chạy trong background task nên không có `session_record` của handler; tra lại từ
    # `session_id`. Phiên hết hạn giữa chừng thì `get_session_record` trả `None` —
    # rơi về `vehicle_id` mặc định thay vì làm hỏng lượt, vì tới đây audio đã nhận rồi.
    _ho_so_phien = get_session_record(session_id)
    xe_id = _ho_so_phien.vehicle_id if _ho_so_phien else get_settings().vehicle_id
    # Mốc đo `end_to_end`. Lấy trước mọi thứ khác để bao trọn lượt, kể cả hai nhánh
    # lỗi bên dưới.
    started = time.perf_counter()
    try:
        await bus.publish(session_id, "turn.accepted", turn_id, trace_id, {"status": "accepted", "input_mode": "voice"})
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "transcribing", "message": "Đang nhận dạng giọng nói."},
        )

        # Lấy engine TRƯỚC và NGOÀI try bắt ValueError bên dưới. `voice.get_stt_engine()`
        # raise ValueError khi `STT_PROVIDER` cấu hình sai — lỗi máy chủ, không liên quan gì
        # tới audio tài xế vừa gửi. Nếu để nó rơi vào nhánh STT_FAILED thì hệ thống đổ lỗi
        # oan cho micro của tài xế; ở đây nó nổi lên nhánh catch-all (INTERNAL_ERROR).
        # Chỉ các ValueError của `_validate_audio` (sai sample rate/kênh, WAV hỏng, quá dài)
        # mới được coi là "audio không dùng được".
        await asyncio.to_thread(voice.get_stt_engine)

        try:
            # `voice.transcribe` **không** bật lớp sửa chính tả: nó đọc
            # `stt_correction_enabled`, mặc định `False`, nên trên mọi checkout như-ship
            # đây đúng bằng `transcribe_raw`. Cờ ấy là công tắc có tài liệu cho lần bật
            # sau này (điều kiện phát hành ghi ở `src/config.py`), thay cho một lần sửa
            # code nữa — và nó chỉ được lật khi có WAV người thật cùng số
            # false-correction trên câu hỏi sổ tay bằng 0 (review #317).
            transcript = await asyncio.to_thread(voice.transcribe, audio_bytes)
        except ValueError as exc:
            _record_end_to_end(trace_id, started)
            await bus.publish(
                session_id,
                "transcript.final",
                turn_id,
                trace_id,
                {"text": "", "language": "vi", "confidence": 0.0, "transcription_status": "unusable"},
            )
            await bus.publish(
                session_id,
                "error",
                turn_id,
                trace_id,
                {"code": "STT_FAILED", "message": str(exc), "retryable": False, "terminal": True, "details": {}},
            )
            await bus.publish(
                session_id,
                "turn.failed",
                turn_id,
                trace_id,
                {"status": "failed", "code": "STT_FAILED", "completed_at": now_iso()},
            )
            return

        # `transcript.latency_ms` trước đây bị vứt ở đây — nó là số đo duy nhất của
        # stage STT và không xuất hiện ở bất kỳ đâu khác trong lượt.
        get_trace_store().record_stage(trace_id, "stt", transcript.latency_ms)

        await bus.publish(
            session_id,
            "transcript.final",
            turn_id,
            trace_id,
            {
                "text": transcript.text,
                "language": "vi",
                "confidence": transcript.confidence,
                "transcription_status": "completed",
            },
        )
        await bus.publish(
            session_id, "assistant.status", turn_id, trace_id, {"state": "routing", "message": "Đang xác định ý định."}
        )

        # Câu trả lời phê duyệt bằng **giọng nói** — đây mới là đường chính của #107,
        # và bản đầu bỏ sót nó. Chặn sau `transcript.final` (tài xế vẫn thấy mình vừa
        # nói gì) và trước graph (đi qua graph thì "đồng ý" rơi xuống tra sổ tay).
        if await _phat_y_dinh_phe_duyet(session_id, turn_id, trace_id, transcript.text) is not None:
            _record_end_to_end(trace_id, started)
            return

        graph = get_graph(session_id)
        # Một session = một thread checkpointer, nên hai lượt song song mà cùng `ainvoke`
        # sẽ bỏ rơi interrupt S2 đang chờ và lượt đó không bao giờ có terminal event.
        # Chỉ khoá quanh `ainvoke` — STT của các lượt khác vẫn chạy song song được.
        async with get_session_lock(session_id):
            result = await graph.ainvoke(
                {
                    "query": transcript.text,
                    "session_id": session_id,
                    # Chỉ nhánh NÓI có trường này. Lượt gõ chữ không bao giờ do mic tự
                    # bắt, nên `submit_text_turn` để mặc định `False` — không khai gì.
                    "bat_tu_dong": bat_tu_dong,
                    # Cùng nguồn sự thật với nhánh text. Gán cứng "veh-demo" là bug
                    # @thanhpro82 bắt ở #168: profile xe lưu theo `vehicle-demo-01`, nên
                    # tra bảng áp suất lốp LUÔN rỗng và lượt NÓI luôn rơi về breadcrumb —
                    # đúng câu mà #168 sinh ra để xoá, chỉ khác là bảng nghiệm thu của
                    # tôi chạy qua `/turns/text` nên không chạm tới nhánh này.
                    "vehicle_id": xe_id,
                    "turn_id": turn_id,
                    # `routine_node` cần nó để hỏi đúng danh sách Routine của người này
                    # (#274). Thiếu nó thì node fail-closed và mọi lượt Routine trả về
                    # "chưa có Routine nào" — đo được end-to-end 30/08, trong khi UI
                    # đang hiện đủ ba mẫu. Đặt ở CẢ HAI nhánh: bản đầu của #107 chỉ móc
                    # vào đường text và lượt NÓI hỏng im lặng suốt một PR.
                    #
                    # Lấy từ `_ho_so_phien` chứ không thêm tham số cho background task:
                    # cùng nguồn và cùng khuôn với `xe_id` ngay trên, kể cả phép lui khi
                    # phiên hết hạn giữa chừng.
                    "user_id": _ho_so_phien.user_id if _ho_so_phien else "",
                    # Thuần quan sát: `src/agents/graph.py` dùng nó làm khoá ghi độ
                    # trễ stage. Không node nào ghi vào field này.
                    "trace_id": trace_id,
                },
                config=thread_config(session_id),
            )
        _record_end_to_end(trace_id, started)
        # Trước `emit_turn_lifecycle`, cùng lý do với `_record_end_to_end`: sự kiện
        # terminal seal trace rồi phát ngay cho `/ws/engineer`.
        record_graph_result(trace_id, result)
        # already_announced=True (issue #346): `src/agents/graph.py` đã phát sống
        # "retrieving"/"composing" ngay khi node `rag`/`compose` chạy, TRONG lúc
        # `graph.ainvoke()` ở trên còn đang chạy — đừng dịch lại hồi tố ở đây nữa.
        await emit_turn_lifecycle(
            bus,
            session_id,
            turn_id,
            trace_id,
            result,
            retrieving_already_announced=True,
            composing_already_announced=True,
        )
    except Exception:  # noqa: BLE001 - lượt phải luôn có terminal event, không được nuốt lỗi im lặng
        logger.exception("Lượt thoại %s thất bại ngoài dự kiến", turn_id)
        _record_end_to_end(trace_id, started)
        await bus.publish(
            session_id,
            "error",
            turn_id,
            trace_id,
            {
                "code": "INTERNAL_ERROR",
                "message": "Lỗi không xác định khi xử lý lượt thoại.",
                "retryable": False,
                "terminal": True,
                "details": {},
            },
        )
        await bus.publish(
            session_id,
            "turn.failed",
            turn_id,
            trace_id,
            {"status": "failed", "code": "INTERNAL_ERROR", "completed_at": now_iso()},
        )


@router.post("/turns/text", response_model=TextTurnEnvelope, dependencies=[Depends(require_schema_version)])
async def submit_text_turn(
    request: Request,
    body: TextTurnRequest,
    user: AuthenticatedUser = Depends(require_driver),
    idempotency_key: str = Depends(require_idempotency_key),
) -> TextTurnEnvelope:
    request_id, trace_id = request_scoped_ids(request)

    text = body.text.strip()
    if not (1 <= len(text) <= 1000):
        raise ApiError(
            status_code=422,
            code="INPUT_INVALID",
            message="text phải có 1-1000 code point Unicode sau khi trim",
            request_id=request_id,
            trace_id=trace_id,
        )

    session_record = get_session_record(body.session_id)
    if session_record is None or session_record.user_id != user.user_id:
        # Không phân biệt "session không tồn tại" với "session của người khác" —
        # tránh lộ enumeration. Xem design doc mục "POST /turns/text".
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="session không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    # Chạm session NGAY ở đây (trước mọi await khác) để thu hẹp khoảng hở
    # LRU-eviction giữa lúc kiểm tra quyền sở hữu và lúc thực thi thật: get_graph()
    # tự "touch" session trong session_state, đưa nó về cuối hàng đợi LRU ngay lập
    # tức. Không loại bỏ hoàn toàn được race này (cần eviction theo refcount mới
    # làm được) — chỉ giảm số điểm await mà một đợt tạo 128+ session mới của người
    # khác (MAX_SESSIONS) có thể chen vào giữa.
    graph = get_graph(body.session_id)

    store = get_idempotency_store()
    fingerprint = fingerprint_for(body.model_dump())
    try:
        existing = await store.begin(user.user_id, _TEXT_TURN_ROUTE, idempotency_key, fingerprint)
    except IdempotencyInProgress as exc:
        raise ApiError(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="một request khác với cùng Idempotency-Key đang được xử lý, thử lại sau",
            retryable=True,
            request_id=request_id,
            trace_id=trace_id,
        ) from exc
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                message="Idempotency-Key đã dùng cho một request khác nội dung",
                request_id=request_id,
                trace_id=trace_id,
            )
        return TextTurnEnvelope.model_validate(existing.body)

    try:
        turn_id = f"turn_{uuid.uuid4().hex[:20]}"
        started = time.perf_counter()
        # Mở trace TẠI ĐÂY chứ không đợi `turn.accepted` đi vòng qua `TraceCollector`:
        # `open()` idempotent theo `(trace_id, turn_id)`, nên gọi thẳng là rẻ và không
        # phụ thuộc thứ tự event. Giữ nguyên kể cả sau khi route này bắt đầu phát
        # `turn.accepted` ngay dưới đây.
        get_trace_store().open(trace_id, body.session_id, turn_id)

        # `turn.accepted` cho lượt gõ chữ — trước đây **chỉ** `/turns/voice` phát.
        #
        # Sự bất đối xứng ấy không phải chi tiết nội bộ: nó làm client không có cách
        # nào biết `turn_id` của một lượt text **trước khi** lượt ấy xong. Route này
        # đồng bộ và `emit_turn_lifecycle` (phát `assistant.speech`/`assistant.response`)
        # chạy TRƯỚC khi envelope HTTP trả về, nên với lượt text thì `turn_id` luôn tới
        # SAU mọi event của chính lượt đó. Mọi cơ chế client lọc event theo `turn_id`
        # do đó không bao giờ chạy được cho text — đo được ở review #307.
        #
        # Phát ở đây, trước `graph.ainvoke`, cho client cái mỏ neo nó cần ngay từ đầu
        # lượt. Event nằm sẵn trong allowlist `docs/api_spec.md` §Driver server-event
        # và `input_mode: "text"` đã có trong union của `frontend/.../turn/types.ts`,
        # nên đây là lấp một chỗ khuyết chứ không phải mở rộng hợp đồng dây.
        bus = get_event_bus()
        await bus.publish(
            body.session_id, "turn.accepted", turn_id, trace_id, {"status": "accepted", "input_mode": "text"}
        )

        # Câu trả lời phê duyệt bằng lời phải được chặn **trước** graph (issue #107).
        # Đi qua graph thì `"đồng ý"` không khớp luật điều khiển nào và rơi xuống
        # `default_to_manual` — xe hỏi "Bạn có đồng ý không?" rồi đáp "Tôi không tìm
        # thấy thông tin này trong sổ tay xe", còn phê duyệt vẫn treo. Đo được trên
        # backend thật 15/08.
        intent_envelope = await _thu_xu_ly_y_dinh_phe_duyet(body.session_id, turn_id, trace_id, request_id, text)
        if intent_envelope is not None:
            await store.finish(
                user.user_id,
                _TEXT_TURN_ROUTE,
                idempotency_key,
                IdempotencyRecord(
                    fingerprint=fingerprint, status_code=200, body=intent_envelope.model_dump(mode="json")
                ),
            )
            return intent_envelope

        async with get_session_lock(body.session_id):
            result = await graph.ainvoke(
                {
                    "query": text,
                    "session_id": body.session_id,
                    "vehicle_id": session_record.vehicle_id,
                    "turn_id": turn_id,
                    # `routine_node` cần nó để hỏi đúng danh sách Routine của người này
                    # (#274). Thiếu nó thì node fail-closed và mọi lượt Routine trả về
                    # "chưa có Routine nào" — đo được end-to-end 30/08, trong khi UI
                    # đang hiện đủ ba mẫu. Đặt ở CẢ HAI nhánh: bản đầu của #107 chỉ móc
                    # vào đường text và lượt NÓI hỏng im lặng suốt một PR.
                    "user_id": session_record.user_id,
                    # Thuần quan sát — xem `_process_voice_turn`.
                    "trace_id": trace_id,
                },
                config=thread_config(body.session_id),
            )
        # Trước `_build_text_turn_response`: hàm đó gọi `emit_turn_lifecycle`, sự kiện
        # terminal của nó seal trace rồi phát ngay cho `/ws/engineer`.
        _record_end_to_end(trace_id, started)
        record_graph_result(trace_id, result)

        envelope = await _build_text_turn_response(bus, body.session_id, turn_id, trace_id, request_id, result)
    except BaseException:  # noqa: BLE001 - phải bắt cả asyncio.CancelledError (client hủy/timeout giữa
        # await graph.ainvoke) để luôn nhả chỗ đã đặt trong idempotency store; CancelledError
        # không kế thừa Exception nên `except Exception` không bắt được, để lại chỗ kẹt vĩnh viễn.
        await store.abandon(user.user_id, _TEXT_TURN_ROUTE, idempotency_key)
        raise

    await store.finish(
        user.user_id,
        _TEXT_TURN_ROUTE,
        idempotency_key,
        IdempotencyRecord(fingerprint=fingerprint, status_code=200, body=envelope.model_dump(mode="json")),
    )
    return envelope


async def _build_text_turn_response(
    bus, session_id: str, turn_id: str, trace_id: str, request_id: str, result: dict
) -> TextTurnEnvelope:
    pending = result.get("__interrupt__")
    if pending:
        return await _waiting_approval_response(bus, session_id, turn_id, trace_id, request_id, result, pending)

    # already_announced=True (issue #346) — xem chú thích ở _process_voice_turn.
    await emit_turn_lifecycle(
        bus, session_id, turn_id, trace_id, result, retrieving_already_announced=True, composing_already_announced=True
    )

    plan = result.get("action_plan")
    action_plan = _action_plan_model(as_action_plan(plan)) if plan is not None else None
    outcome = result.get("outcome")
    if outcome in ("execution_failed", "vehicle_state_unavailable"):
        # "vehicle_state_unavailable" (safety_node từ chối vì VehicleGateway chưa
        # sẵn sàng) khớp với nhánh WS turn.failed(MQTT_UNAVAILABLE) của
        # emit_turn_lifecycle — status REST phải đồng bộ, không được rơi vào
        # nhánh mặc định "completed".
        status = "failed"
    elif outcome == "approval_already_pending":
        status = "clarify"
    else:
        status = "completed"
    response_payload = assistant_response_payload(result)

    return TextTurnEnvelope(
        data=TextTurnData(
            session_id=session_id,
            turn_id=turn_id,
            status=status,
            action_plan=action_plan,
            response=TurnResponseData(
                display_text=response_payload["display_text"],
                speak_text=response_payload["speak_text"],
                citations=response_payload["citations"],
                outcomes=response_payload["outcomes"],
            ),
            routine_preview=response_payload["routine_preview"],
            routine_setup_required=response_payload["routine_setup_required"],
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


async def _waiting_approval_response(
    bus, session_id: str, turn_id: str, trace_id: str, request_id: str, result: dict, pending
) -> TextTurnEnvelope:
    """Nhánh S2: KHÔNG thực thi plan.

    Route này **không tự phát `plan.ready`** nữa. Bản trước phát bù ở đây vì lúc đó
    `emit_turn_lifecycle` chưa phát, và sửa chỗ chung sẽ đổi chuỗi sự kiện voice đã có
    test. Ràng buộc đó hết hiệu lực từ `5ad3e81`: `emit_turn_lifecycle` giờ phát
    `plan.ready` cho **mọi** lượt điều khiển — cả S1/completed, S3/blocked lẫn S2, và
    cả hai đường voice/text — nên phát bù ở đây sẽ thành hai lần cho cùng một lượt.

    Bỏ luôn được một lỗi hiển thị: bản trước dùng `payload["prompt_text"]` làm
    `summary`, mà `HitlModal.tsx:59` render `Bạn xác nhận: {summary}?` — ghép một câu
    hoàn chỉnh vào sẽ ra `Bạn xác nhận: Xe đang chạy 40 km/h. Tôi sẽ .... Bạn có đồng ý
    không??`. Bản trung tâm ghép từ `describe_step()` nên ra đúng cụm động từ.
    """
    payload = pending[0].value
    plan = as_action_plan(result["action_plan"])
    plan_model = _action_plan_model(plan)

    # already_announced=True (issue #346) — xem chú thích ở _process_voice_turn. Vô hại
    # ở nhánh này: __interrupt__ trả sớm trong emit_turn_lifecycle, trước khi hai cờ
    # này được đọc tới.
    await emit_turn_lifecycle(
        bus, session_id, turn_id, trace_id, result, retrieving_already_announced=True, composing_already_announced=True
    )

    return TextTurnEnvelope(
        data=TextTurnData(
            session_id=session_id,
            turn_id=turn_id,
            status="waiting_approval",
            action_plan=plan_model,
            pending_approval=PendingApprovalData(approval_id=payload["approval_id"], expires_at=payload["expires_at"]),
            response=TurnResponseData(
                display_text=payload["prompt_text"],
                speak_text=payload["prompt_text"],
                citations=[],
                outcomes=[],
            ),
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


#: Cau tra loi cho tung nhanh. Viet o day chu khong o `voice_intent.py`: module ay chi
#: doc chu, khong biet gi ve phe duyet.
_LOI_MO_HO = "Tôi chưa rõ bạn đồng ý hay không. Bạn nói lại giúp tôi nhé."
_LOI_KHONG_CHO = "Hiện không có yêu cầu nào đang chờ bạn xác nhận."
_LOI_DA_NHAN = {
    "approve": "Bạn đã đồng ý. Tôi sẽ thực hiện ngay.",
    "reject": "Bạn đã từ chối. Tôi sẽ không thực hiện.",
}
#: Nhánh tiếng trần: **chưa** chốt gì cả, nên không được hứa "sẽ thực hiện ngay". Gọi
#: tên đúng cụm cần nói, vì cụm ấy là thứ duy nhất phân biệt hai nhánh — nói chung chung
#: ("bạn xác nhận lại giúp tôi") thì tài xế lặp lại đúng tiếng trần vừa rồi và kẹt vòng
#: lặp. Ngoặc kép chỉ để mắt đọc; Piper không đọc thành tiếng.
_LOI_CAN_NOI_RO = 'Bạn nói "đồng ý" hoặc chạm nút xác nhận giúp tôi.'


#: Task nền đang chạy, giữ tham chiếu để GC không thu mất giữa chừng — `asyncio` chỉ
#: giữ weak reference tới task, và một task bị thu là một lệnh xe biến mất không dấu vết.
_TASK_NEN: set = set()


def _chay_nen(fn, *args) -> None:
    task = asyncio.create_task(fn(*args))
    _TASK_NEN.add(task)
    task.add_done_callback(_TASK_NEN.discard)
    task.add_done_callback(_bao_loi_task)


def _bao_loi_task(task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.exception("task nền của lượt phê duyệt hỏng", exc_info=task.exception())


async def _chot_neu_du_dieu_kien(y_dinh, approval_id: str) -> Literal["da_chot", "can_ro_hon", "khong_chot_duoc"]:
    """Chốt phê duyệt bằng giọng nói khi đủ điều kiện. Trả kết cục để người gọi chọn câu thoại.

    ## Bất đối xứng, và đây là toàn bộ phần an toàn của tính năng

    | | cụm | vì sao |
    |---|---|---|
    | **từ chối** | mọi cụm, kể cả `thôi`/`không` trần | ASR nghe nhầm thì **không mất gì**: từ chối vốn đã là kết quả mặc định khi phê duyệt hết hạn |
    | **chấp nhận** | chỉ cụm rõ ràng (`đồng ý`, `xác nhận`, …) | nghe nhầm thành chấp nhận là xe tự làm một việc S2 — tự hạ kính, tự mở cửa |

    Tiếng `ừ`/`vâng`/`được` trần **không** chốt. Chúng xuất hiện quá nhiều trong hội
    thoại thường, và `voice_intent.ro_rang_ve_phe_duyet` đã tách sẵn hai tập ấy nên
    không phải đoán. Không chốt ≠ bỏ qua: lượt vẫn phát `approval.intent.detected` để
    IVI làm nổi nút, đúng hành vi trước #191.

    ## Vì sao được phép chốt, khi #107 cấm

    `emit_approval_intent_handoff` từng ghi "backend không bao giờ tự commit". Lập luận
    để đảo: cổng HITL đòi **một xác nhận có chủ ý của con người**, không đòi *một cú
    chạm*. Một cụm rõ ràng nói ra là xác nhận có chủ ý. Rủi ro còn lại là ASR nghe
    nhầm — và đó là lý do bảng trên tồn tại, cùng lý do issue đòi đo WER trên tập cụm
    đóng trước khi nâng status.

    Đi qua `chot_da_xac_thuc` chứ không tự dựng trình tự: bốn bất biến HITL phải được
    ép ở một chỗ duy nhất, bất kể cửa vào là nút bấm hay giọng nói.

    ## Ba kết cục, vì có ba câu thoại phải đúng (#207a)

    | | khi nào | tài xế nghe gì |
    |---|---|---|
    | `da_chot` | store đã sang `approved`/`rejected` | *"Tôi sẽ thực hiện ngay."* |
    | `can_ro_hon` | tiếng trần — **cố ý** không chốt | *"Bạn nói 'đồng ý' hoặc chạm nút…"* |
    | `khong_chot_duoc` | đã gọi store nhưng nó từ chối (hết hạn/vô hiệu trong cửa sổ đua) | *"Hiện không có yêu cầu nào đang chờ…"* |

    Trả `bool` đủ dùng tới lúc kết cục này phải ra tới IVI dưới tên `committed`: `True`
    cũ nói *"đã gọi chốt"*, còn IVI cần biết *"đã chốt"*. Hai câu ấy khác nhau đúng ở
    hàng thứ ba — và hàng thứ ba là nơi câu *"Tôi sẽ thực hiện ngay"* thành lời nói dối.
    """
    from src.api.approvals import chot_da_xac_thuc

    if y_dinh.quyet_dinh == "approve" and not y_dinh.ro_rang_ve_phe_duyet:
        return "can_ro_hon"
    decided = await chot_da_xac_thuc(
        approval_id,
        approve=y_dinh.quyet_dinh == "approve",
        schedule=_chay_nen,
    )
    # `consumed` cũng tính là đã chốt: lệnh chạy xong trước khi ta đọc lại bản ghi thì
    # quyết định của tài xế vẫn đã được ghi nhận, và IVI không có việc gì phải gọi REST.
    mong_doi = ("approved", "consumed") if y_dinh.quyet_dinh == "approve" else ("rejected",)
    return "da_chot" if decided is not None and decided.status in mong_doi else "khong_chot_duoc"


async def _phat_y_dinh_phe_duyet(session_id: str, turn_id: str, trace_id: str, text: str) -> tuple[str, str] | None:
    """Phần **chung** cho cả `/turns/text` lẫn `/turns/voice`: quyết định và phát sự kiện.

    Trả `(status, text_tra_loi)` nếu đã xử lý, `None` nếu lượt này không phải câu trả
    lời phê duyệt và phải đi đường thường.

    Tách khỏi phần dựng envelope vì hai đường có hình dạng hồi đáp khác hẳn: `/turns/text`
    đồng bộ và trả envelope, còn `/turns/voice` đã trả `202` từ trước nên chỉ còn phát
    sự kiện. Bản đầu của #107 chỉ móc vào đường text — nghĩa là **nói** "đồng ý" vẫn rơi
    xuống tra sổ tay, đúng cái bug mà PR ấy sinh ra để sửa. Người dùng bắt được khi test
    tay; suite không bắt vì mọi test của tôi đều gọi `/turns/text`.
    """
    y_dinh = doc_y_dinh_phe_duyet(text)
    if y_dinh.quyet_dinh is None and not y_dinh.mo_ho:
        return None

    # Router được hỏi TRƯỚC: câu nào nó nhận ra là chuyện điều khiển xe thì đó là lệnh,
    # không phải câu trả lời cổng phê duyệt (#196).
    #
    # Bản trước không hỏi, nên `"dừng nhạc"`, `"tạm dừng nhạc"` và `"hủy dẫn đường"` bị
    # nuốt sạch: bộ dò thấy câu mở đầu bằng `dừng`/`hủy` là chốt "ý định từ chối" rồi
    # return, và router **không bao giờ được gọi tới** — dù nó có sẵn kế hoạch chạy được
    # cho cả ba (`media_control{pause}`, `set_navigation{cancel}`). Tài xế bấm tạm dừng
    # nhạc thì nghe "Hiện không có yêu cầu nào đang chờ bạn xác nhận."
    #
    # Vì sao hỏi router chứ không nuôi một danh sách tân ngữ (`nhạc`, `bài`, `dẫn
    # đường`…): danh sách ấy sẽ trôi khỏi router mỗi lần thêm một domain, mà bề mặt điều
    # khiển vẫn đang lớn (issue #65 vừa thêm `lights` và `trunk`). Router **chính là**
    # danh sách, và nó không trôi khỏi chính nó.
    #
    # Đo 19/08 trước khi đổi: quét cả 32 cụm của `_DONG_Y` + `_TU_CHOI` cộng các biến
    # thể — **không cụm nào** bị router nhận là lệnh. Nên phép đảo này không nuốt mất
    # câu trả lời phê duyệt nào, kể cả `dừng`/`hủy` đứng trần.
    #
    # Chỉ loại `control`, không loại `denied`/`clarify`: `"đừng mở cửa"` ra `denied` và
    # vẫn nên đi đường phê duyệt — nó là lời từ chối, không phải lệnh.
    disposition = DeterministicControlRouter().route(text).disposition
    if disposition == "control":
        return None

    bus = get_event_bus()
    pending = get_store().pending_for_session(session_id)

    # Ý định Routine được tha **chỉ khi không có phê duyệt nào đang treo** — và thứ tự ấy
    # là toàn bộ nội dung của quyết định này.
    #
    # `"Dừng lại"` mang hai nghĩa tuỳ ngữ cảnh, và cả hai đều đúng:
    #
    #   có phê duyệt S2 treo  -> "bác lệnh đó"      -> cổng này xử lý, an toàn thắng
    #   không có gì treo      -> "hủy Routine"      -> để graph xử lý
    #
    # Vì sao không đơn giản thêm `"routine"` vào phép loại bên trên: làm thế thì một tiếng
    # "dừng lại" khi đang chờ duyệt một lệnh S2 sẽ đi xuống graph, trả "không có Routine
    # nào đang chạy", còn lệnh S2 thì **vẫn treo nguyên**. Tài xế tưởng đã chặn được nó.
    #
    # Đây là lần thứ hai lớp lỗi này xuất hiện: #196 đã sửa đúng chỗ này cho `"dừng nhạc"`
    # bằng cách hỏi router trước. Thêm một disposition mới (`routine`, #274) là dựng lại
    # nó, vì phép loại kia chỉ kể tên `control`. Đo được end-to-end 30/08:
    #
    #     POST /turns/text "Dừng lại" -> status=canceled,
    #                                   "Hiện không có yêu cầu nào đang chờ bạn xác nhận."
    if disposition == "routine" and pending is None:
        return None

    # Thứ tự quan trọng: **không có gì đang chờ** xét trước mơ hồ. Một câu lẫn lộn khi
    # chẳng có phê duyệt nào thì vấn đề là không có gì để duyệt, không phải cách nói.
    if pending is None:
        # Nhưng chỉ nói thế khi tài xế thật sự **nói với cổng phê duyệt**. Một tiếng
        # "có"/"không" trần trả lời câu hỏi vừa đặt ra, và câu ấy thường không phải câu
        # hỏi phê duyệt — lời mời "Bạn có muốn nghe tiếp nguyên văn không?" là ca có
        # thật và gặp ngay ở lượt sau mỗi câu hỏi sổ tay dài.
        #
        # Bản đầu của #107 không phân biệt, nên nó cướp mọi tiếng "có" trong cả hệ
        # thống: xe hỏi nghe tiếp không, tài xế đáp "Có", xe trả lời "Hiện không có yêu
        # cầu nào đang chờ bạn xác nhận." Đo được ngày 16/08 trên `develop`.
        if not y_dinh.ro_rang_ve_phe_duyet:
            return None
        await emit_approval_intent_not_pending(bus, session_id, turn_id, trace_id, message=_LOI_KHONG_CHO)
        return "canceled", _LOI_KHONG_CHO

    if y_dinh.mo_ho:
        await emit_approval_intent_ambiguous(bus, session_id, turn_id, trace_id, message=_LOI_MO_HO)
        return "failed", _LOI_MO_HO

    # Chốt TRƯỚC khi phát sự kiện: `_LOI_DA_NHAN["approve"]` nói "Tôi sẽ thực hiện
    # ngay", và câu ấy phải đúng vào lúc tài xế nghe nó. Trước #191 nó là một lời hứa
    # suông — lượt handoff không chốt gì cả, tài xế vẫn phải chạm màn hình.
    #
    # Vẫn phát `approval.intent.detected` kể cả khi đã chốt: IVI cần biết để cập nhật
    # màn hình. Nhưng payload phải nói ra sự khác biệt — bốn trường cũ giống hệt nhau ở
    # cả hai nhánh, nên IVI mù và làm thứ rẻ nhất là luôn gọi REST, tức chốt hộ đúng cái
    # bất đối xứng trên vừa từ chối chốt (#207a). Đó là việc của `committed`.
    ket = await _chot_neu_du_dieu_kien(y_dinh, pending.approval_id)
    if ket == "khong_chot_duoc":
        # Cửa sổ đua: `pending_for_session` còn thấy `pending`, tới lúc `decide()` thì
        # bản ghi đã hết hạn (hoặc bị vô hiệu). Đúng nghĩa "không còn gì chờ xác nhận"
        # nên đi thẳng nhánh ấy — phát handoff cho một phê duyệt đã chết thì IVI làm nổi
        # một cái nút mà bấm vào sẽ lỗi.
        await emit_approval_intent_not_pending(bus, session_id, turn_id, trace_id, message=_LOI_KHONG_CHO)
        return "canceled", _LOI_KHONG_CHO
    noi = _LOI_DA_NHAN[y_dinh.quyet_dinh] if ket == "da_chot" else _LOI_CAN_NOI_RO
    await emit_approval_intent_handoff(
        bus,
        session_id,
        turn_id,
        trace_id,
        approval_id=pending.approval_id,
        original_turn_id=pending.turn_id,
        decision=y_dinh.quyet_dinh,
        approved_vehicle_state_version=pending.approved_vehicle_state_version,
        committed=ket == "da_chot",
        speak_text=noi,
    )
    return "completed", noi


async def _thu_xu_ly_y_dinh_phe_duyet(
    session_id: str, turn_id: str, trace_id: str, request_id: str, text: str
) -> TextTurnEnvelope | None:
    """Lượt này có phải câu trả lời cho một phê duyệt không? `None` = không, đi đường thường.

    Ba nhánh terminal của `api_spec.md:643-644`, mỗi nhánh đúng **một** sự kiện terminal:

    | tình huống | sự kiện | status REST |
    |---|---|---|
    | handoff thành công | `approval.intent.detected` + `assistant.response` + `turn.completed` | `completed` |
    | ý định mơ hồ | `error(terminal=true)` + `turn.failed` | `failed` |
    | không có gì đang chờ | `assistant.response` + `turn.canceled(approval_not_pending)` | `canceled` |

    **Không commit.** Hàm này không gọi decision service, không chạm `ApprovalStore`,
    không resume graph — `api_spec.md:278` cấm thẳng, và lý do là: backend tự commit thì
    một câu lọt qua bộ dò sẽ thành hành động S2 thật, bỏ qua đúng cổng người-trong-vòng-lặp
    mà HITL sinh ra để giữ. IVI mới là bên gọi `POST /approvals/{id}/decision`.

    Lượt lệnh **gốc** không bị đụng tới ở bất kỳ nhánh nào: nó vẫn chờ, đúng như
    `api_spec.md:278` nói ("The original command turn remains pending until REST ...").
    """
    ket_qua = await _phat_y_dinh_phe_duyet(session_id, turn_id, trace_id, text)
    if ket_qua is None:
        return None
    status, noi = ket_qua
    return _envelope_y_dinh(session_id, turn_id, trace_id, request_id, status, noi)


def _envelope_y_dinh(
    session_id: str, turn_id: str, trace_id: str, request_id: str, status: str, text: str
) -> TextTurnEnvelope:
    """Envelope REST cho lượt ý định. Không `action_plan`, không `pending_approval`.

    Cố ý **không** trả `pending_approval`: lượt này không tạo ra phê duyệt nào, và trả
    nó về sẽ khiến client tưởng đây là lượt sinh ra yêu cầu xác nhận.
    """
    return TextTurnEnvelope(
        data=TextTurnData(
            session_id=session_id,
            turn_id=turn_id,
            status=status,
            action_plan=None,
            response=TurnResponseData(display_text=text, speak_text=text, citations=[], outcomes=[]),
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )

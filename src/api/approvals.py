"""`POST /api/v1/approvals/{approval_id}/decision` — một trong 14 interface P0.

Đây là route **duy nhất** commit quyết định. Ticket SCRUM-18 mô tả
`POST /api/v1/hitl/confirm` với `{hitl_action_id, confirmed}`; trưởng nhóm chốt trên
PR #23 là giữ canonical naming end-to-end nên route đó không được làm.
`hitl_action_id` chính là `approval_id`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict

from src.api.auth_deps import (
    AuthenticatedUser,
    require_driver,
    require_idempotency_key,
    require_schema_version,
)
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.api.session_state import (
    get_graph,
    get_session_lock,
    get_session_record,
    get_store,
    thread_config,
)
from src.services import idempotency
from src.services.ivi_events import (
    _publish_assistant_response,
    emit_turn_lifecycle,
    get_event_bus,
    now_iso,
    synthesize_speech,
)
from src.services.routine_execution import tiep_tuc_sau_phe_duyet, tim_theo_approval

logger = logging.getLogger(__name__)
router = APIRouter()


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    approved_vehicle_state_version: int | None = None


class ApprovalDecisionResponse(BaseModel):
    """Body chỉ nói **quyết định đã được ghi nhận**, không nói plan chạy ra sao.

    `api_spec.md:209` tách đôi rất rõ: phần kiểm tra và consume là đồng bộ và nguyên
    tử, phần thực thi chạy tiếp bất đồng bộ và báo về `/ws/ivi`. Trả kèm `tool_results`
    buộc route phải chạy xong cả chuỗi lệnh xe rồi mới hồi đáp — tài xế bấm Đồng ý và
    ngồi nhìn màn hình đứng im cho tới lúc lệnh cuối xong.

    Đây cũng đúng thứ frontend đã giả định sẵn: `decideApproval(...)` trả
    `Promise<void>` và **không đọc body**; mọi kết quả nó chờ trên `/ws/ivi`.
    """

    approval_status: str


#: Khoá route cho kho idempotency — mỗi route một không gian khoá riêng, để cùng một
#: `Idempotency-Key` dùng ở hai route khác nhau không đụng nhau.
_ROUTE = "POST /approvals/{approval_id}/decision"


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalDecisionResponse,
    dependencies=[Depends(require_schema_version)],
)
async def decide(
    http_request: Request,
    approval_id: str,
    request: ApprovalDecisionRequest,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_driver),
    idempotency_key: str = Depends(require_idempotency_key),
) -> ApprovalDecisionResponse:
    request_id, trace_id = request_scoped_ids(http_request)
    store = get_store()
    record = store.get(approval_id)

    # Một điều kiện cho cả hai ca, và trả **cùng một** phản hồi: approval không tồn tại,
    # và approval của người khác.
    #
    # `api_spec.md:60` chốt vai trò là "Driver, approval owner", `:657` chốt mã lỗi
    # "cross-owner is FORBIDDEN". Còn việc gộp hai ca là để không rò rỉ enumeration:
    # trả 404 cho id không tồn tại trong khi trả 403 cho id của người khác thì chính cặp
    # mã lỗi đó nói cho kẻ dò biết id nào có thật. Cùng lý do và cùng mã lỗi mà
    # `turns.py` đã dùng cho `session_id`.
    #
    # ĐỔI HÀNH VI có chủ đích: bản trước trả 404 cho id không tồn tại.
    session_record = get_session_record(record.session_id) if record is not None else None
    if record is None or session_record is None or session_record.user_id != user.user_id:
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="approval không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    # Idempotency mở **sau** cổng sở hữu có chủ đích: một request bị 403 không phải kết
    # quả đáng nhớ, và nhớ nó thì kẻ dò có thể chiếm chỗ một khoá rồi đọc lại.
    #
    # Đây là lớp bảo vệ **độc lập** với `previous_status`. `previous_status` chỉ chặn
    # được hai lần bấm trên **cùng một** approval; nó không phân biệt được "client retry
    # vì mất mạng" với "người dùng bấm lần nữa", và cũng không giúp gì khi client gửi
    # lại sau khi bản ghi đã đổi trạng thái vì lý do khác.
    idem = idempotency.get_idempotency_store()
    fingerprint = idempotency.fingerprint_for({"approval_id": approval_id, **request.model_dump()})
    try:
        existing = await idem.begin(user.user_id, _ROUTE, idempotency_key, fingerprint)
    except idempotency.IdempotencyInProgress as exc:
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
        return ApprovalDecisionResponse.model_validate(existing.body)

    async def _remember(response: ApprovalDecisionResponse) -> ApprovalDecisionResponse:
        await idem.finish(
            user.user_id,
            _ROUTE,
            idempotency_key,
            idempotency.IdempotencyRecord(
                fingerprint=fingerprint, status_code=200, body=response.model_dump(mode="json")
            ),
        )
        return response

    decided = await chot_da_xac_thuc(
        approval_id,
        approve=request.decision == "approve",
        schedule=background_tasks.add_task,
        khi_loi=lambda: idem.abandon(user.user_id, _ROUTE, idempotency_key),
    )
    return await _remember(ApprovalDecisionResponse(approval_status=decided.status))


async def chot_da_xac_thuc(
    approval_id: str,
    *,
    approve: bool,
    schedule: Callable[..., Any],
    khi_loi: Callable[[], Any] | None = None,
):
    """Lõi chốt phê duyệt, dùng chung cho **nút bấm và giọng nói**.

    ## Vì sao phải là một cửa, không phải hai

    Bốn bất biến của HITL — single-use (`consume()` chỉ đi `approved -> consumed`),
    plan-bound, kiểm `state_version`, tối đa một pending mỗi phiên — phải được ép ở
    server bất kể ai gọi. Cho đường giọng nói tự dựng lấy trình tự riêng là mời hai bản
    sao của cùng một logic trôi khỏi nhau, mà bản trôi sẽ là bản ít người đọc hơn.

    Cái **không** nằm ở đây, và cố ý: xác thực, kiểm sở hữu phiên, và idempotency.
    Chúng thuộc về từng cửa vào — route REST có `require_driver` + `Idempotency-Key`
    riêng, còn đường giọng nói đã đi qua đúng hai cổng ấy ở `/turns/*` trước khi tới
    đây. Người gọi **phải** đã xác thực; hàm này tin điều đó, và tên hàm nói thế.

    `schedule` là chỗ xếp việc chạy nền: route REST đưa `background_tasks.add_task`,
    còn đường giọng nói vốn đã chạy trong một task nền nên đưa cách khác. Nhận nó làm
    tham số thay vì tự chọn — hàm này không biết nó đang ở trong ngữ cảnh request nào.
    """
    store = get_store()
    record = store.get(approval_id)
    previous_status = record.status if record is not None else None
    # Chốt quyết định TRƯỚC khi resume: node approval đọc lại store chứ không tin
    # payload resume, nên store phải đã ở trạng thái cuối cùng lúc graph chạy tiếp.
    #
    # `abandon` khi lỗi là **bắt buộc**, không phải phòng xa: `IdempotencyStore.begin`
    # ghi rõ caller phải gọi `finish()` hoặc `abandon()`, và kho **không có TTL** — bỏ
    # sót thì chỗ đã đặt nằm lại vĩnh viễn và mọi lần thử lại với cùng khoá đều nhận
    # 409 `IDEMPOTENCY_CONFLICT`, tức một lỗi thoáng qua biến thành hỏng vĩnh viễn cho
    # đúng cái khoá mà client sẽ retry.
    try:
        decided = store.decide(approval_id, approve=approve)
    except Exception:
        if khi_loi is not None:
            await khi_loi()
        raise

    if decided.status != "approved":
        # Chỉ phát sự kiện WS khi đây là một reject **mới** (record vừa chuyển từ
        # pending sang rejected trong chính lệnh gọi này) — replay lại một approval
        # đã chốt từ trước (rejected/expired/invalidated/consumed) không tạo hiệu ứng
        # phụ mới nào, kể cả trên WS, giống hệt REST không tạo hiệu ứng phụ mới.
        if previous_status == "pending" and decided.status == "rejected":
            # Thẻ của một Routine không đi đường TTS/graph của lượt nói: nó không thuộc
            # lượt nào cả. Rẽ ở đây, một chỗ duy nhất — xem `_chay_tiep_routine`.
            if tim_theo_approval(approval_id) is not None:
                schedule(_chay_tiep_routine, approval_id, False)
                return decided
            # TTS đi nền, cùng lý do và cùng cơ chế với nhánh approve ngay dưới: audio
            # là best-effort và kết quả đã có đường ra riêng qua `/ws/ivi`, nên request
            # HTTP không có lý do gì phải chờ Piper — `synthesize_speech` chạy
            # `asyncio.to_thread` nhưng không có timeout, một lần synthesis chậm/treo
            # sẽ kéo chậm theo chính thao tác từ chối approval nếu await tại đây.
            schedule(_reject_and_publish, record.session_id, record.turn_id)
        # Hết hạn, đã bị từ chối, hoặc đã consume — không resume graph, tránh chạy
        # lại một lượt đã kết thúc.
        return decided

    # Quyết định đã được chốt nguyên tử ở `store.decide()` bên trên; phần còn lại là
    # **thực thi**, và nó đi nền. Trả `approved` chứ không phải `consumed` là đúng sự
    # thật tại thời điểm hồi đáp: lệnh chưa chạy xong. Client muốn biết kết quả thì
    # nghe `/ws/ivi`, không hỏi lại REST.
    #
    # Chỉ xếp task khi bản ghi **vừa** chuyển `pending → approved` trong chính lệnh gọi
    # này — đối xứng với điều kiện ở nhánh reject bên trên, và cùng một lý do.
    # `decide()` là idempotent: gọi lại trên bản ghi đã `approved` thì nó trả nguyên
    # trạng thái `approved`, nên riêng `decided.status` không phân biệt được "vừa duyệt"
    # với "duyệt rồi, đang chạy". Từ khi thực thi chạy nền, route trả `200` ngay nên
    # client rảnh tay gửi tiếp — một cú double-click là đủ chạm vào cửa sổ này.
    #
    # Lệnh sẽ không chạy hai lần kể cả khi thiếu chốt này (node đọc lại store, thấy
    # `consumed` thì fail-closed), nhưng lượt sẽ nhận **hai sự kiện terminal**:
    # `turn.completed` rồi `turn.canceled`. Vi phạm bất biến số 1, và trên màn hình tài
    # xế là một thông báo huỷ hiện ngay sau khi lệnh vừa báo thành công.
    if previous_status == "pending":
        if tim_theo_approval(approval_id) is not None:
            schedule(_chay_tiep_routine, approval_id, True)
        else:
            schedule(_resume_and_publish, approval_id, record.session_id, record.turn_id)
    return decided


async def _chay_tiep_routine(approval_id: str, approved: bool) -> None:
    """Chạy tiếp một Routine sau quyết định phê duyệt.

    ## Vì sao rẽ nhánh ở đây chứ không dựng cửa thứ hai

    Docstring `chot_da_xac_thuc` viết: bốn bất biến HITL phải được ép ở server bất kể ai
    gọi, và cho một đường tự dựng trình tự riêng là mời hai bản sao trôi khỏi nhau. Điều
    đó vẫn đúng — nên quyết định vẫn chốt ở **đúng một chỗ** phía trên, và chỉ phần
    *chạy tiếp* mới rẽ.

    Phải rẽ vì thẻ của Routine không thuộc lượt nào: `_resume_and_publish` gọi
    `graph.ainvoke(Command(resume=...))`, mà không có `interrupt()` nào đang chờ trên
    thread của phiên. Đưa thẻ Routine vào đó thì lượt gần nhất của phiên bị resume oan —
    một lượt đã kết thúc bỗng chạy tiếp.
    """
    try:
        await tiep_tuc_sau_phe_duyet(approval_id, approved=approved)
    except Exception:  # noqa: BLE001 - task nền không được nuốt lỗi im lặng
        logger.exception("Chạy tiếp Routine sau phê duyệt %s thất bại ngoài dự kiến", approval_id)


async def _reject_and_publish(session_id: str, turn_id: str) -> None:
    """TTS + báo kết quả từ chối về `/ws/ivi`, chạy nền — cùng lý do với `_resume_and_publish`.

    `synthesize_speech` tự nó đã fail-open (không raise), nhưng `bus.publish` thì có
    thể — bọc try/except ở đây để một lỗi bất ngờ không biến mất im lặng trong task nền
    mà không ai thấy, cùng kỷ luật với `_resume_and_publish`.
    """
    bus = get_event_bus()
    fresh_trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    cancel_message = "Đã hủy theo lựa chọn của bạn."
    try:
        wav_bytes = await synthesize_speech(turn_id, fresh_trace_id, cancel_message)
        await _publish_assistant_response(
            bus,
            session_id,
            turn_id,
            fresh_trace_id,
            {"display_text": cancel_message, "speak_text": cancel_message, "citations": [], "outcomes": []},
            wav_bytes,
        )
        await bus.publish(
            session_id,
            "turn.canceled",
            turn_id,
            fresh_trace_id,
            {"status": "canceled", "reason": "approval_rejected", "completed_at": now_iso()},
        )
    except Exception:  # noqa: BLE001 - task nền không được nuốt lỗi im lặng, xem _resume_and_publish
        logger.exception("Publish sự kiện reject cho turn %s thất bại ngoài dự kiến", turn_id)


async def _resume_and_publish(approval_id: str, session_id: str, turn_id: str) -> None:
    """Chạy tiếp graph sau quyết định và báo kết quả về `/ws/ivi`.

    Bốn kiểm tra fail-closed viết ở PR #25 **giữ nguyên vị trí** trong node approval —
    chỉ phần thực thi dời ra sau. Không có bảo đảm an toàn nào bị nới lỏng ở đây.
    """
    store = get_store()
    bus = get_event_bus()
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    try:
        graph = get_graph(session_id)
        # Cùng khoá với `turns.py`: một lượt voice mới không được `ainvoke` chen vào giữa lúc
        # resume approval trên cùng thread checkpointer (xem `get_session_lock`).
        async with get_session_lock(session_id):
            result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=thread_config(session_id))
        if result.get("outcome", "approval_rejected") != "completed":
            # Node đã từ chối ở một trong các kiểm tra fail-closed nên approval chưa bị
            # consume. Đánh dấu `invalidated` để nó không nằm lại ở `approved` — trạng
            # thái đó gợi ý sai rằng vẫn còn dùng được.
            store.invalidate(approval_id)

        # `plan_already_announced=True`: lượt này đã phát `plan.ready` ở lần gọi đầu
        # (nhánh `__interrupt__` của `emit_turn_lifecycle`). Một lượt chỉ được có đúng
        # một `plan.ready` — xem `api_spec.md` §Normative state machine và issue #94.
        await emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result, plan_already_announced=True)
    except Exception:  # noqa: BLE001 - lượt phải luôn có terminal event, không được nuốt lỗi im lặng
        # Từ khi thực thi dời sang task nền, exception ở đây **không** còn nổi lên thành
        # HTTP 500 nữa — nó biến mất trong nền. Không có terminal event thì màn hình tài
        # xế treo ở `waiting_approval` vĩnh viễn và họ không có cách nào biết lệnh đã
        # hỏng. Bất biến "đúng một sự kiện terminal mỗi lượt" phải đúng cả ở đường hỏng.
        logger.exception("Resume approval %s thất bại ngoài dự kiến", approval_id)
        # Approval chưa consume nhưng cũng không còn dùng được: đánh dấu để nó không nằm
        # lại ở `approved`, đúng cùng lý do với nhánh fail-closed bên trên.
        store.invalidate(approval_id)
        await bus.publish(
            session_id,
            "error",
            turn_id,
            trace_id,
            {
                "code": "INTERNAL_ERROR",
                "message": "Lỗi không xác định khi thực hiện lệnh đã duyệt.",
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

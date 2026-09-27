"""`/api/v1/routines` — CRUD Routine theo chủ sở hữu (issue #282, outcome #272).

## Vì sao là bề mặt mới, và nó nằm ở đâu so với 14 interface P0

`docs/api_spec.md` chốt 14 interface P0; Routines MVP là epic #270, mở sau P0 và có
product spec riêng (`docs/routines_product_spec.md`). Nhóm route này thuộc epic ấy, không
phải một interface P0 thứ 15 lén thêm vào — cùng cách `GET/PUT /vehicle/profile` được
argue thành interface 13 chứ không lặng lẽ xuất hiện.

## Vì sao `require_driver`

Routine là dữ liệu **của người lái**: họ tạo, họ chạy, và spec §Cô lập chốt không ai đọc
được của người khác. Engineer không có Routine nào để quản; cho họ đọc bề mặt này là mở
một đường vòng vào dữ liệu cá nhân mà không ai cần tới.

Chủ sở hữu luôn lấy từ token (`user.user_id`), **không bao giờ** từ body hay query. Đó là
lý do `RoutineDraftBody` không có `user_id` và `extra="forbid"` chặn nó: một client gửi
`user_id` của người khác phải trông như một request sai, không phải một request hợp lệ.

## Mã lỗi khớp FE mock

`frontend/src/lib/services/routines/mock.ts` đã ném `ROUTINE_EMPTY`,
`ROUTINE_TOO_MANY_STEPS`, `ROUTINE_NAME_EMPTY`, `ROUTINE_NAME_DUPLICATE`,
`ROUTINE_NOT_FOUND` — và `RoutinesView` đang hiển thị đúng những mã ấy hôm nay. Dùng lại
chúng ở đây nghĩa là `real.ts` (#281 phần còn lại) chỉ cần đổi transport, không phải dịch
một bảng mã thứ hai rồi bỏ sót một ca.

## 404 cho mọi ca không sở hữu

Id của người khác và id không tồn tại trả **cùng một** lỗi. Trả 403 cho ca đầu là xác
nhận Routine ấy có thật — đúng kênh rò rỉ mà #272 acceptance criteria đóng lại, và cùng
cách `session_routes` xử lý phiên của người khác.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from src.api.auth_deps import AuthenticatedUser, require_driver
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.api.session_state import get_session_record
from src.models.api import (
    Meta,
    RoutineData,
    RoutineDraftBody,
    RoutineEnabledBody,
    RoutineEnvelope,
    RoutineExecutionData,
    RoutineExecutionEnvelope,
    RoutineListData,
    RoutineListEnvelope,
    RoutineRunBody,
    RoutineStepResultData,
)
from src.services.routine_execution import (
    RoutineDangChayError,
    RoutineExecution,
    RoutineKhongChayDuocError,
    bat_dau,
    huy,
)
from src.services.routine_execution import doc as doc_execution
from src.services.routines_store import (
    KhongPhaiMauError,
    KhongXoaDuocMauError,
    Routine,
    RoutineDichError,
    RoutineKhongTonTaiError,
    TenKhongHopLeError,
    TenTrungError,
    create_routine,
    delete_routine,
    get_routine,
    list_routines,
    restore_default,
    set_enabled,
    update_routine,
)

router = APIRouter()

#: `RoutineDichError.ma` → mã lỗi trên dây. Bảng tường minh chứ không phải upper-case
#: máy móc: mã trên dây là **hợp đồng với client**, còn `ma` là chi tiết nội bộ, và hai
#: thứ đó phải được phép tiến hoá độc lập. Ba lý do cuối gộp về một mã vì client xử lý
#: chúng như nhau — hiện lỗi tại bước đang sửa.
_MA_LOI_BUOC: dict[str, str] = {
    "routine_rong": "ROUTINE_EMPTY",
    "qua_nhieu_buoc": "ROUTINE_TOO_MANY_STEPS",
    "action_khong_ho_tro": "ROUTINE_STEP_INVALID",
    "gia_tri_khong_hop_le": "ROUTINE_STEP_INVALID",
    "gia_tri_ngoai_dai": "ROUTINE_STEP_INVALID",
}


def _data(routine: Routine) -> RoutineData:
    return RoutineData(
        id=routine.id,
        user_id=routine.user_id,
        name=routine.name,
        icon=routine.icon,  # type: ignore[arg-type]
        enabled=routine.enabled,
        steps=list(routine.steps),
        is_default_template=routine.is_default_template,
        template_origin=routine.template_origin,  # type: ignore[arg-type]
        version=routine.version,
        needs_preview=routine.needs_preview,
        needs_setup=routine.needs_setup,
        runnable=routine.runnable,
        created_at=routine.created_at,
        updated_at=routine.updated_at,
    )


def _envelope(routine: Routine, request_id: str, trace_id: str) -> RoutineEnvelope:
    return RoutineEnvelope(data=_data(routine), meta=Meta(request_id=request_id), trace_id=trace_id)


def _khong_thay(routine_id: str, request_id: str, trace_id: str) -> ApiError:
    return ApiError(
        status_code=404,
        code="ROUTINE_NOT_FOUND",
        message="không tìm thấy chuỗi lệnh",
        request_id=request_id,
        trace_id=trace_id,
        details={"routine_id": routine_id},
    )


def _loi_ghi(exc: Exception, request_id: str, trace_id: str) -> ApiError:
    """Đổi exception của store thành `ApiError`. Một chỗ duy nhất, dùng cho cả tạo và sửa.

    `retryable=True` cho mọi ca ở đây: chúng đều là lỗi **dữ liệu người dùng vừa nhập**,
    sửa lại rồi gửi tiếp là xong. Đó cũng là ngữ nghĩa mà `ServiceError` của FE dùng để
    quyết định có giữ form đang mở hay không.
    """
    if isinstance(exc, TenTrungError):
        return ApiError(
            status_code=409,
            code="ROUTINE_NAME_DUPLICATE",
            message="đã có chuỗi lệnh khác trùng tên này",
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
        )
    if isinstance(exc, TenKhongHopLeError):
        return ApiError(
            status_code=422,
            code="ROUTINE_NAME_EMPTY" if "phải có tên" in str(exc) else "ROUTINE_NAME_INVALID",
            message=str(exc),
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
        )
    if isinstance(exc, RoutineDichError):
        return ApiError(
            status_code=422,
            code=_MA_LOI_BUOC.get(exc.ma, "ROUTINE_STEP_INVALID"),
            message=str(exc),
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
            details={"ly_do": exc.ma},
        )
    raise exc  # pragma: no cover - người gọi chỉ bắt bốn lớp trên


@router.get(
    "/routines",
    response_model=RoutineListEnvelope,
    summary="Danh sách Routine của người lái hiện tại",
)
async def read_routines(
    request: Request,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineListEnvelope:
    """Mới sửa nhất trước. Lần gọi đầu của một user gieo ba mẫu mặc định, idempotent."""
    request_id, trace_id = request_scoped_ids(request)
    items = [_data(r) for r in list_routines(user.user_id)]
    return RoutineListEnvelope(
        data=RoutineListData(items=items),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


@router.post(
    "/routines",
    response_model=RoutineEnvelope,
    status_code=201,
    summary="Tạo Routine mới",
)
async def create(
    request: Request,
    body: RoutineDraftBody,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineEnvelope:
    request_id, trace_id = request_scoped_ids(request)
    try:
        routine = create_routine(user.user_id, name=body.name, icon=body.icon, steps=body.steps)
    except (TenTrungError, TenKhongHopLeError, RoutineDichError) as exc:
        raise _loi_ghi(exc, request_id, trace_id) from exc
    return _envelope(routine, request_id, trace_id)


@router.get(
    "/routines/{routine_id}",
    response_model=RoutineEnvelope,
    summary="Một Routine của người lái hiện tại",
)
async def read_one(
    request: Request,
    routine_id: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineEnvelope:
    request_id, trace_id = request_scoped_ids(request)
    try:
        routine = get_routine(user.user_id, routine_id)
    except RoutineKhongTonTaiError as exc:
        raise _khong_thay(routine_id, request_id, trace_id) from exc
    return _envelope(routine, request_id, trace_id)


@router.put(
    "/routines/{routine_id}",
    response_model=RoutineEnvelope,
    summary="Sửa Routine (tên, biểu tượng, các bước)",
)
async def update(
    request: Request,
    routine_id: str,
    body: RoutineDraftBody,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineEnvelope:
    """Ghi đè toàn bộ draft. Đổi tên hoặc bước thì `version` tăng và preview bật lại."""
    request_id, trace_id = request_scoped_ids(request)
    try:
        routine = update_routine(user.user_id, routine_id, name=body.name, icon=body.icon, steps=body.steps)
    except RoutineKhongTonTaiError as exc:
        raise _khong_thay(routine_id, request_id, trace_id) from exc
    except (TenTrungError, TenKhongHopLeError, RoutineDichError) as exc:
        raise _loi_ghi(exc, request_id, trace_id) from exc
    return _envelope(routine, request_id, trace_id)


@router.put(
    "/routines/{routine_id}/enabled",
    response_model=RoutineEnvelope,
    summary="Bật hoặc tắt một Routine",
)
async def toggle(
    request: Request,
    routine_id: str,
    body: RoutineEnabledBody,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineEnvelope:
    """Không đổi `version` — bật/tắt không đổi việc Routine sẽ làm, nên không bắt xem
    lại preview."""
    request_id, trace_id = request_scoped_ids(request)
    try:
        routine = set_enabled(user.user_id, routine_id, enabled=body.enabled)
    except RoutineKhongTonTaiError as exc:
        raise _khong_thay(routine_id, request_id, trace_id) from exc
    return _envelope(routine, request_id, trace_id)


@router.delete(
    "/routines/{routine_id}",
    status_code=204,
    summary="Xoá một Routine tự tạo",
)
async def remove(
    request: Request,
    routine_id: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> Response:
    """Mẫu mặc định không xoá được — chỉ tắt hoặc khôi phục (spec §Ba mẫu mặc định)."""
    request_id, trace_id = request_scoped_ids(request)
    try:
        delete_routine(user.user_id, routine_id)
    except RoutineKhongTonTaiError as exc:
        raise _khong_thay(routine_id, request_id, trace_id) from exc
    except RoutineDangChayError as exc:
        raise ApiError(
            status_code=409,
            code="ROUTINE_RUNNING",
            message="Chuỗi lệnh đang chạy — hãy dừng lần chạy đó trước khi xoá",
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
            details={"execution_id": exc.execution_id},
        ) from exc
    except KhongXoaDuocMauError as exc:
        raise ApiError(
            status_code=409,
            code="ROUTINE_TEMPLATE_PROTECTED",
            message="mẫu mặc định không xoá được, chỉ tắt hoặc khôi phục",
            request_id=request_id,
            trace_id=trace_id,
            retryable=False,
            details={"routine_id": routine_id},
        ) from exc
    return Response(status_code=204)


@router.post(
    "/routines/{routine_id}/restore-default",
    response_model=RoutineEnvelope,
    summary="Khôi phục một mẫu mặc định đã sửa về nội dung gốc",
)
async def restore(
    request: Request,
    routine_id: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineEnvelope:
    """Khôi phục **bump version**: nội dung vừa đổi so với lần chạy trước, nên preview
    bật lại. Xem docstring `restore_default`."""
    request_id, trace_id = request_scoped_ids(request)
    try:
        routine = restore_default(user.user_id, routine_id)
    except RoutineKhongTonTaiError as exc:
        raise _khong_thay(routine_id, request_id, trace_id) from exc
    except KhongPhaiMauError as exc:
        raise ApiError(
            status_code=409,
            code="ROUTINE_NOT_TEMPLATE",
            message="Chuỗi lệnh này không phải mẫu mặc định nên không có gì để khôi phục",
            request_id=request_id,
            trace_id=trace_id,
            retryable=False,
            details={"routine_id": routine_id},
        ) from exc
    return _envelope(routine, request_id, trace_id)


# --- chạy Routine (issue #286) ----------------------------------------------


def _execution_data(execution: RoutineExecution) -> RoutineExecutionData:
    return RoutineExecutionData(
        id=execution.id,
        routine_id=execution.routine_id,
        session_id=execution.session_id,
        routine_version=execution.routine_version,
        status=execution.status,  # type: ignore[arg-type]
        current_index=execution.current_index,
        approval_id=execution.approval_id,
        steps_total=len(execution.steps),
        results=[
            RoutineStepResultData(
                index=r.index,
                action=r.action,
                status=r.status,  # type: ignore[arg-type]
                description=r.description,
                error_code=r.error_code,
            )
            for r in execution.results
        ],
        terminal_reason=execution.terminal_reason,
        created_at=execution.created_at,
        updated_at=execution.updated_at,
    )


def _execution_envelope(execution: RoutineExecution, request_id: str, trace_id: str) -> RoutineExecutionEnvelope:
    return RoutineExecutionEnvelope(
        data=_execution_data(execution),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


#: `RoutineKhongChayDuocError.ma` → (mã trên dây, HTTP). Bảng tường minh, cùng lý do với
#: `_MA_LOI_BUOC`: mã trên dây là hợp đồng với client, `ma` là chi tiết nội bộ.
_MA_LOI_CHAY: dict[str, tuple[str, int]] = {
    "routine_khong_ton_tai": ("ROUTINE_NOT_FOUND", 404),
    "routine_da_tat": ("ROUTINE_DISABLED", 409),
    "chua_dat_dia_diem": ("ROUTINE_NEEDS_SETUP", 409),
    "dang_chay_routine_khac": ("ROUTINE_ALREADY_RUNNING", 409),
}


@router.post(
    "/routines/{routine_id}/run",
    response_model=RoutineExecutionEnvelope,
    status_code=202,
    summary="Chạy một Routine",
)
async def run(
    request: Request,
    routine_id: str,
    body: RoutineRunBody,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineExecutionEnvelope:
    """202 vì lần chạy **chưa xong** khi request trả về.

    Nó có thể đang chờ phê duyệt một bước S2, và kết quả cuối đi qua `/ws/ivi` — cùng
    kiểu hợp đồng với `POST /turns/voice`. Trả 200 ở đây sẽ nói rằng Routine đã chạy
    xong, điều không đúng ở đúng những ca quan trọng nhất.

    Ba lý do từ chối **trước khi** có side effect nào: Routine bị tắt, chưa đặt địa điểm,
    hoặc phiên đang có một Routine chạy dở.
    """
    request_id, trace_id = request_scoped_ids(request)
    session = get_session_record(body.session_id)
    if session is None or session.user_id != user.user_id:
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="session không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )
    try:
        execution = await bat_dau(
            user_id=user.user_id,
            session_id=session.session_id,
            vehicle_id=session.vehicle_id,
            routine_id=routine_id,
        )
    except RoutineKhongChayDuocError as exc:
        code, status_code = _MA_LOI_CHAY.get(exc.ma, ("ROUTINE_NOT_RUNNABLE", 409))
        raise ApiError(
            status_code=status_code,
            code=code,
            message=str(exc),
            request_id=request_id,
            trace_id=trace_id,
            details={"ly_do": exc.ma},
        ) from exc
    return _execution_envelope(execution, request_id, trace_id)


@router.get(
    "/routine-executions/{execution_id}",
    response_model=RoutineExecutionEnvelope,
    summary="Trạng thái một lần chạy Routine",
)
async def read_execution(
    request: Request,
    execution_id: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineExecutionEnvelope:
    """Đường riêng, **không** lồng dưới `/routines/{routine_id}`: một execution sống lâu
    hơn và độc lập với Routine sinh ra nó — Routine có thể bị sửa hoặc tắt sau đó."""
    request_id, trace_id = request_scoped_ids(request)
    try:
        execution = doc_execution(user.user_id, execution_id)
    except LookupError as exc:
        raise ApiError(
            status_code=404,
            code="ROUTINE_EXECUTION_NOT_FOUND",
            message="không tìm thấy lần chạy này",
            request_id=request_id,
            trace_id=trace_id,
            details={"execution_id": execution_id},
        ) from exc
    return _execution_envelope(execution, request_id, trace_id)


@router.post(
    "/routine-executions/{execution_id}/cancel",
    response_model=RoutineExecutionEnvelope,
    summary="Dừng một lần chạy Routine tại điểm dừng an toàn",
)
async def cancel(
    request: Request,
    execution_id: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> RoutineExecutionEnvelope:
    """**Idempotent**: gọi lại, hoặc gọi trên một lần chạy đã kết thúc, cho cùng kết quả
    và không sinh terminal thứ hai.

    200 chứ không 202: yêu cầu dừng **đã được ghi nhận** khi request trả về. Trạng thái
    trả về có thể vẫn là `running` — điểm dừng an toàn nằm ở ranh giới bước tiếp theo, và
    bước đang bay chạy nốt. Trạng thái cuối đi qua `routine.finished` trên `/ws/ivi`.
    """
    request_id, trace_id = request_scoped_ids(request)
    try:
        execution = await huy(user.user_id, execution_id)
    except LookupError as exc:
        raise ApiError(
            status_code=404,
            code="ROUTINE_EXECUTION_NOT_FOUND",
            message="không tìm thấy lần chạy này",
            request_id=request_id,
            trace_id=trace_id,
            details={"execution_id": execution_id},
        ) from exc
    return _execution_envelope(execution, request_id, trace_id)

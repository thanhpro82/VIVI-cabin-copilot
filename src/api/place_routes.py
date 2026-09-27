"""`/api/v1/places` — hai nhãn địa điểm cá nhân Nhà và Cơ quan (issue #283).

## Vì sao là tài nguyên riêng, không phải field của Routine

Một địa điểm được **nhiều** Routine dùng chung: "Đi làm" và một Routine tự tạo cùng trỏ
Cơ quan. Nhét nó vào từng Routine nghĩa là đổi chỗ làm phải sửa mọi Routine, và hai bản
sẽ lệch nhau — đúng lớp lỗi mà spec gọi là "âm thầm dùng giá trị cũ".

## Vì sao `require_driver`

Cùng lập luận với `/routines`: đây là dữ liệu của người lái, và spec §Cô lập chốt không
ai đọc được của người khác. Chủ sở hữu luôn từ token, không bao giờ từ path hay body.

## Ba trạng thái, và vì sao chúng phải phân biệt được

- khoá `null` — **chưa gán**;
- object `valid=true` — dùng được;
- object `valid=false` — đã gán, nhưng đích biến mất khỏi fixture offline.

Gộp hai ca cuối thành `null` sẽ làm màn thiết lập (#284) không nói được vì sao lựa chọn
cũ biến mất, và người dùng chọn lại mà không hiểu chuyện gì vừa xảy ra.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from src.api.auth_deps import AuthenticatedUser, require_driver
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.models.api import Meta, PlaceData, PlacesData, PlacesEnvelope, PlaceUpdateBody
from src.services.user_places import (
    NHAN_HOP_LE,
    DiaDiemCaNhan,
    DiaDiemKhongHopLeError,
    delete_place,
    get_places,
    set_place,
)

router = APIRouter()


def _data(dia_diem: DiaDiemCaNhan | None) -> PlaceData | None:
    if dia_diem is None:
        return None
    return PlaceData(
        label=dia_diem.label,  # type: ignore[arg-type]
        destination_id=dia_diem.destination_id,
        name=dia_diem.name,
        valid=dia_diem.valid,
        updated_at=dia_diem.updated_at,
    )


def _envelope(da_gan: dict[str, DiaDiemCaNhan], request_id: str, trace_id: str) -> PlacesEnvelope:
    return PlacesEnvelope(
        data=PlacesData(home=_data(da_gan.get("home")), office=_data(da_gan.get("office"))),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


def _kiem_nhan(label: str, request_id: str, trace_id: str) -> None:
    """Nhãn lạ là **404**, không phải 422.

    `/places/bep` không phải một request sai định dạng — nó là một tài nguyên không tồn
    tại, và nói đúng điều đó giúp client phân biệt "gõ nhầm đường dẫn" với "body sai".
    """
    if label not in NHAN_HOP_LE:
        raise ApiError(
            status_code=404,
            code="PLACE_LABEL_UNKNOWN",
            message=f"không có nhãn địa điểm {label!r}",
            request_id=request_id,
            trace_id=trace_id,
            details={"hop_le": list(NHAN_HOP_LE)},
        )


@router.get(
    "/places",
    response_model=PlacesEnvelope,
    summary="Hai nhãn địa điểm cá nhân của người lái hiện tại",
)
async def read_places(
    request: Request,
    user: AuthenticatedUser = Depends(require_driver),
) -> PlacesEnvelope:
    """Cả hai khoá luôn có mặt. `null` = chưa gán — **không** có giá trị mặc định nào."""
    request_id, trace_id = request_scoped_ids(request)
    return _envelope(get_places(user.user_id), request_id, trace_id)


@router.put(
    "/places/{label}",
    response_model=PlacesEnvelope,
    summary="Gán một nhãn địa điểm vào một điểm đến offline",
)
async def write_place(
    request: Request,
    label: str,
    body: PlaceUpdateBody,
    user: AuthenticatedUser = Depends(require_driver),
) -> PlacesEnvelope:
    """`destination_id` phải thuộc fixture offline — tập đóng, không sinh id động."""
    request_id, trace_id = request_scoped_ids(request)
    _kiem_nhan(label, request_id, trace_id)
    try:
        set_place(user.user_id, label, body.destination_id)
    except DiaDiemKhongHopLeError as exc:
        raise ApiError(
            status_code=422,
            code="PLACE_DESTINATION_INVALID",
            message=str(exc),
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
            details={"destination_id": body.destination_id},
        ) from exc
    return _envelope(get_places(user.user_id), request_id, trace_id)


@router.delete(
    "/places/{label}",
    status_code=204,
    summary="Bỏ gán một nhãn địa điểm",
)
async def clear_place(
    request: Request,
    label: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> Response:
    """Bỏ gán là hành động hợp lệ: Routine dẫn đường quay về "Cần thiết lập", và **không**
    rơi về đích cũ.

    204 kể cả khi nhãn vốn chưa gán — DELETE là idempotent, và trả 404 cho ca ấy buộc
    client phải đọc trước khi xoá để biết mình sẽ nhận mã nào.
    """
    request_id, trace_id = request_scoped_ids(request)
    _kiem_nhan(label, request_id, trace_id)
    delete_place(user.user_id, label)
    return Response(status_code=204)

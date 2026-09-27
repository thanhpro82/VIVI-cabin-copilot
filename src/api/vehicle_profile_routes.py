"""`GET/PUT /api/v1/vehicle/profile` — cấu hình xe (issue #123).

## Đây là interface thứ 13, và đó là một quyết định chứ không phải sơ suất

`docs/api_spec.md` nay chốt đúng 14 interface P0 và ghi nhận chính route này là
interface 13; mục "P1 management endpoints" nói ở
P0 thì cấu hình đổi qua `.env` + restart. Route này mở rộng bề mặt đó, có chủ đích:
nhánh áp suất lốp (#123) cần biết cấu hình xe *lúc chạy*, và một buổi demo đổi giữa
bản ECO và PLUS mà phải restart backend là đổi cả state cache MQTT lẫn phiên đăng
nhập — cái giá lớn hơn nhiều so với một route đọc/ghi hai chuỗi.

Cấu hình xe cũng **không** thuộc ba family bị cấm ở `api_spec.md:503`
(`/manuals/ingest`, `/eval/runs*`, `/model-profiles*` — cái cuối là profile *model
LLM*, chuyện khác hẳn).

## Vì sao ghi là engineer-only

Đổi trim/pin là khai báo lại chiếc xe, không phải thao tác lái. Tài xế **đọc** được
(IVI cần hiển thị cấu hình hiện tại) nhưng không ghi. Dùng `require_engineer` có sẵn
(`src/api/auth_deps.py:67`), cùng cơ chế đang gác `/traces` và `/metrics/summary`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.api.auth_deps import AuthenticatedUser, get_current_user, require_engineer
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.config import get_settings
from src.models.api import (
    ErrorEnvelope,
    Meta,
    TrangBiItem,
    VehicleOptionsData,
    VehicleOptionsEnvelope,
    VehicleOptionsUpdate,
    VehicleProfileData,
    VehicleProfileEnvelope,
    VehicleProfileUpdate,
)
from src.services.vehicle_profile import (
    InvalidProfileValueError,
    TrangBiKhongHopLeError,
    VehicleProfile,
    get_vehicle_options,
    get_vehicle_profile,
    set_vehicle_options,
    set_vehicle_profile,
)

router = APIRouter()


def _envelope(profile: VehicleProfile, request_id: str, trace_id: str) -> VehicleProfileEnvelope:
    return VehicleProfileEnvelope(
        data=VehicleProfileData(
            vehicle_id=profile.vehicle_id,
            trim=profile.trim,
            battery=profile.battery,
            is_complete=profile.is_complete,
            updated_at=profile.updated_at,
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


@router.get(
    "/vehicle/profile",
    response_model=VehicleProfileEnvelope,
    summary="Cấu hình xe hiện tại (phiên bản và loại pin)",
)
async def read_vehicle_profile(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> VehicleProfileEnvelope:
    """Đọc cấu hình. Xe chưa khai báo trả **200** với `trim=null, battery=null`.

    Không phải 404: chiếc xe có tồn tại, chỉ là cấu hình của nó chưa được khai. Trả
    404 sẽ buộc client phân biệt "không có xe" với "chưa biết cấu hình" bằng cách
    đoán, trong khi `is_complete=false` nói thẳng điều cần biết.
    """
    request_id, trace_id = request_scoped_ids(request)
    profile = get_vehicle_profile(get_settings().vehicle_id)
    return _envelope(profile, request_id, trace_id)


@router.put(
    "/vehicle/profile",
    response_model=VehicleProfileEnvelope,
    responses={
        403: {
            "model": ErrorEnvelope,
            "description": "FORBIDDEN — chỉ vai trò engineer được đổi cấu hình xe.",
        },
        422: {
            "model": ErrorEnvelope,
            "description": (
                "VALIDATION_ERROR — `trim` ngoài `eco|plus` hoặc `battery` ngoài "
                "`sdi|catl`. `null` là hợp lệ và có nghĩa xoá cấu hình."
            ),
        },
    },
    summary="Đặt lại cấu hình xe (engineer)",
)
async def write_vehicle_profile(
    request: Request,
    payload: VehicleProfileUpdate,
    user: AuthenticatedUser = Depends(require_engineer),
) -> VehicleProfileEnvelope:
    """Ghi đè cả cặp `trim`/`battery`.

    `InvalidProfileValueError` được bắt riêng chứ không bắt `ValueError` trần: cùng ngăn
    xếp này có `src/safety/ap_suat_lop.tra_ap_suat()` cũng ném `ValueError`, mà cái
    đó là **lỗi lập trình** — biến nó thành 422 sẽ báo cho client rằng họ gửi sai
    trong khi thực ra bảng tra hỏng.

    Pydantic đã chặn phần lớn giá trị lạ ở biên nhờ `Literal`, nên nhánh này chủ yếu
    bắt ca gọi thẳng service. Vẫn giữ, vì hai lớp validate không có nghĩa là một lớp
    thừa: `Literal` không bắt được `" ECO "` mà `_normalise` nhận và sửa.
    """
    request_id, trace_id = request_scoped_ids(request)
    try:
        profile = set_vehicle_profile(
            get_settings().vehicle_id,
            trim=payload.trim,
            battery=payload.battery,
        )
    except InvalidProfileValueError as exc:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message=str(exc),
            request_id=request_id,
            trace_id=trace_id,
            retryable=False,
            details={"field": exc.field, "allowed": list(exc.allowed)},
        ) from exc
    return _envelope(profile, request_id, trace_id)


# --- Trang bị tuỳ chọn: sub-resource riêng, không phải field thêm vào body trên ------
#
# `VehicleProfileUpdate` có `extra="forbid"` và đòi **có mặt** cả hai field. Thêm
# `options` vào đó là một trong hai điều tệ:
#
# - để nó bắt buộc → mọi client hiện có gãy với 422 ngay lượt PUT đầu tiên;
# - để nó tuỳ chọn → phá đúng bất biến mà `VehicleProfileUpdate` dựng lên, rằng thiếu
#   field là lỗi chứ không phải mặc định.
#
# Sub-resource né cả hai, và nó còn nói đúng ngữ nghĩa: đây là hai tài nguyên có vòng
# đời khác nhau. `trim`/`battery` là một cặp khai một lần; trang bị là một tập lớn, khai
# dần, và không bao giờ "đủ".


def _envelope_trang_bi(vehicle_id: str, da_khai: dict[str, bool], request_id: str, trace_id: str):
    from src.safety.trang_bi import doc_danh_muc

    return VehicleOptionsEnvelope(
        data=VehicleOptionsData(
            vehicle_id=vehicle_id,
            da_khai=da_khai,
            danh_muc=[
                TrangBiItem(id=t.id, ten=t.ten, nhom=t.nhom, loai_tru=list(t.loai_tru))
                for t in sorted(doc_danh_muc(), key=lambda x: (x.nhom, x.id))
            ],
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )


@router.get(
    "/vehicle/profile/options",
    response_model=VehicleOptionsEnvelope,
    summary="Trang bị tuỳ chọn đã khai báo, kèm danh mục đầy đủ",
)
async def read_vehicle_options(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> VehicleOptionsEnvelope:
    """Đọc trang bị. Xe chưa khai gì trả **200** với `da_khai: {}`.

    Danh mục đi kèm mỗi lần đọc, không tách thành route riêng: nó là hằng của bản sổ
    tay chứ không phải dữ liệu của chiếc xe, nhưng client cần cả hai cùng lúc để vẽ
    được màn khai báo, và một round-trip thứ hai chỉ đổi lấy khả năng hai bên lệch
    phiên bản nhau.
    """
    request_id, trace_id = request_scoped_ids(request)
    vehicle_id = get_settings().vehicle_id
    return _envelope_trang_bi(vehicle_id, get_vehicle_options(vehicle_id), request_id, trace_id)


@router.put(
    "/vehicle/profile/options",
    response_model=VehicleOptionsEnvelope,
    responses={
        403: {
            "model": ErrorEnvelope,
            "description": "FORBIDDEN — chỉ vai trò engineer được đổi trang bị xe.",
        },
        422: {
            "model": ErrorEnvelope,
            "description": (
                "VALIDATION_ERROR — id không có trong danh mục, hoặc hai trang bị loại "
                "trừ nhau cùng được khai là `true`."
            ),
        },
    },
    summary="Khai lại toàn bộ trang bị tuỳ chọn (engineer)",
)
async def write_vehicle_options(
    request: Request,
    payload: VehicleOptionsUpdate,
    user: AuthenticatedUser = Depends(require_engineer),
) -> VehicleOptionsEnvelope:
    """Ghi đè cả tập. `{"da_khai": {}}` là xoá sạch, đưa mọi trang bị về "chưa biết".

    Ghi là engineer-only vì cùng lý do với `trim`/`battery`: khai lại trang bị là khai
    lại chiếc xe, không phải một thao tác lái.
    """
    request_id, trace_id = request_scoped_ids(request)
    vehicle_id = get_settings().vehicle_id
    try:
        da_khai = set_vehicle_options(vehicle_id, payload.da_khai)
    except TrangBiKhongHopLeError as exc:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message=str(exc),
            request_id=request_id,
            trace_id=trace_id,
            retryable=False,
        ) from exc
    return _envelope_trang_bi(vehicle_id, da_khai, request_id, trace_id)

"""`POST /api/v1/sim/motion` — bàn đạo diễn kịch bản demo. ADR-024.

## Route này KHÔNG thuộc bề mặt P0

`docs/api_spec.md` khai đúng 14 interface; con số đó **không đổi** vì route này.
Cùng khuôn `/agent/process` (`src/api/agent_routes.py`):

- `include_in_schema=False` → không xuất hiện trong OpenAPI/`/docs`, nên không ai
  build client dựa vào nó.
- **404 khi `sim_control_enabled=false`** — không phải 403. 403 xác nhận route có
  thật, và một bề mặt harness thì không nên xác nhận điều gì với người không được
  bật nó.

## Vì sao nó không phá ADR-013

Nó **không** ghi state. Nó publish một message lên `v1/sim/{id}/motion/set`; xe ảo
nhận rồi tự gọi `SimulatorRuntime.set_motion()` — đúng method mà `speed 45` gõ vào
stdin gọi. Publisher của `state/*` vẫn là identity `vehicle-simulator`, ACL hợp
đồng xe không đổi một dòng, và `state_version` vẫn do simulator tăng nên không có
race với `expected_state_version`.

Backend ở đây chỉ làm **người đưa tin**, không phải nguồn state thứ hai.

## Vì sao vẫn đòi đăng nhập

Trên bản deploy công khai, ai có token driver là kéo được tốc độ của chiếc xe ảo
dùng chung — ADR-024 ghi thẳng giới hạn đó ở `## Consequences`. Đòi `require_driver`
không sửa được chuyện ấy (không có multi-tenant ở P0), nhưng nó giữ cho bề mặt này
không rộng hơn phần còn lại của IVI.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from src.api.auth_deps import require_driver
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.config import get_settings
from src.models.sim_harness import SimMotionSet
from src.mqtt_topics import sim_motion_set

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sim-harness"])


@router.post(
    "/sim/motion",
    status_code=202,
    include_in_schema=False,
    dependencies=[Depends(require_driver)],
)
async def set_sim_motion(body: SimMotionSet, request: Request) -> dict[str, object]:
    """Đặt tốc độ/số của **xe ảo**. Dev/demo-only — xem docstring đầu file.

    202 chứ không 200: xe ảo đổi state **bất đồng bộ** qua MQTT, nên lúc response
    trả về thì `GET /vehicle/state` chưa chắc đã thấy giá trị mới. Trả 200 ở đây
    là hứa một điều route này không kiểm chứng được. Client poll state như nó vẫn
    đang làm (`SpeedDebugDrawer` poll 1 s).
    """
    request_id, trace_id = request_scoped_ids(request)

    if not get_settings().sim_control_enabled:
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="Not Found",
            request_id=request_id,
            trace_id=trace_id,
        )

    runtime = getattr(request.app.state, "mqtt", None)
    client = getattr(runtime, "client", None)
    if client is None:
        # Cùng mã lỗi và cùng `reason` mà `GET /vehicle/state` đã dùng cho ca này
        # (`src/api/routes.py`), để client không phải học thêm một từ vựng thứ hai
        # cho cùng một sự cố. Kênh harness đi qua đúng broker ấy: không có broker
        # thì không có đường nào tới xe.
        raise ApiError(
            status_code=503,
            code="MQTT_UNAVAILABLE",
            message="chưa nối được broker MQTT — không gửi được lệnh tới xe ảo",
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
            details={"reason": "broker_unreachable", "mqtt_connected": False},
        )

    vehicle_id = get_settings().vehicle_id
    await client.publish(
        sim_motion_set(vehicle_id),
        body.model_dump(mode="json"),
        qos=1,
        # retain=False: đây là một **sự kiện đạo diễn**, không phải state. Retain
        # sẽ khiến xe ảo khởi động lại là tự nhảy về tốc độ của lần chỉnh trước —
        # trạng thái xe phải đến từ retained `state/*` của chính xe, không từ đây.
        retain=False,
    )
    logger.info(
        "Harness: đặt xe %s về %.1f km/h gear=%s", vehicle_id, body.speed_kph, body.gear or "auto"
    )
    return {"accepted": True, "speed_kph": body.speed_kph, "gear": body.gear}

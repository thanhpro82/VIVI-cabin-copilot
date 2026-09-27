"""GET /healthz — readiness của các dependency bắt buộc.

`200` khi không component bắt buộc nào ở trạng thái **chặn**; ngược lại `503`
theo common error envelope. Gate thật là `health_service.is_ready` — file này
chỉ lắp ráp, không định nghĩa lại ngữ nghĩa. Hai lớp miễn trừ:

- `llm` miễn trừ **theo tên** ở P0 (issue #48: `slm_enabled=False` theo thiết kế,
  không phải sự cố);
- mọi component ở trạng thái `disabled` miễn trừ **theo trạng thái** (issue #95:
  tắt có chủ đích không phải dependency hỏng).

Component được miễn trừ vẫn đo và hiển thị đủ trong `components`/`faults`/
`error.details.dependencies` — miễn trừ khỏi gate, không phải giấu khỏi payload.
Hợp đồng đầy đủ ở docs/devops.md §Readiness contract và docs/api_spec.md#health.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.models.vehicle import SCHEMA_VERSION
from src.services import health as health_service
from src.services.mqtt_runtime import MqttRuntime

router = APIRouter()
logger = logging.getLogger(__name__)

#: Tên 8 component đã chuyển sang `src/services/health.py` để `/healthz` và event
#: `health` của `/ws/engineer` đọc cùng một bảng. Giữ alias để import cũ không gãy.
_COMPONENT_NAMES = health_service.COMPONENT_NAMES


@router.get("/healthz")
async def healthz(request: Request):
    settings = get_settings()
    runtime: MqttRuntime | None = getattr(request.app.state, "mqtt", None)

    components = await health_service.collect_health(settings, runtime)

    request_id = f"req_{uuid.uuid4().hex[:12]}"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    checked_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    # Gate ở `health_service.is_ready` chứ không chép tay tại đây (issue #95): trước đó
    # đúng vòng lặp này nằm cả ở route lẫn ở `health_event_payload`, nên `/healthz` và
    # event `health` của `/ws/engineer` có thể lệch nhau về cùng một hệ thống.
    if health_service.is_ready(components):
        # Gate bỏ qua component miễn trừ theo tên (`llm`) và trạng thái `disabled`,
        # nên nhánh 200 KHÔNG còn nghĩa là "cả 8 component ready" — `faults` phải tính
        # thật, không hardcode rỗng, để không giấu trạng thái của một component bị tắt
        # hay được miễn trừ. "Tắt có chủ đích" khác "hỏng", nhưng cũng khác "giấu".
        return {
            "data": {
                "status": "ready",
                "checked_at": checked_at,
                "components": {
                    name: {"status": result.status, "latency_ms": result.latency_ms}
                    for name, result in components.items()
                },
                "faults": [
                    {"component": name, "status": result.status, "code": (result.detail or "").split(":", 1)[0]}
                    for name, result in components.items()
                    if result.status != "ready"
                ],
            },
            "meta": {"request_id": request_id},
            "trace_id": trace_id,
            "schema_version": SCHEMA_VERSION,
        }

    for name, result in components.items():
        # Chỉ cảnh báo cho trạng thái **chặn**: một dòng WARNING "mqtt not ready" khi
        # `MQTT_ENABLED=false` chính là kiểu nhầm lẫn mà issue #95 sinh ra để gỡ.
        if result.status in health_service.BLOCKING_STATUSES:
            redacted_code = (result.detail or "").split(":", 1)[0]
            logger.warning("healthz probe not ready: %s status=%s code=%s", name, result.status, redacted_code)
            logger.debug("healthz probe not ready detail: %s status=%s detail=%s", name, result.status, result.detail)

    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "DEPENDENCY_NOT_READY",
                "message": "một hoặc nhiều dependency bắt buộc chưa sẵn sàng",
                "retryable": True,
                "details": {
                    "dependencies": {
                        name: {"status": result.status, "code": (result.detail or "").split(":", 1)[0]}
                        for name, result in components.items()
                    }
                },
            },
            "meta": {"request_id": request_id},
            "trace_id": trace_id,
            "schema_version": SCHEMA_VERSION,
        },
    )

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from src.agents.graph import build_graph
from src.api.auth_deps import AuthenticatedUser, get_current_user
from src.api.context import new_request_id, resolve_trace_id
from src.api.errors import ApiError
from src.api.session_state import get_session_record, get_vehicle, get_vehicle_pool, xe_cua_phien
from src.models.api import ErrorEnvelope, Meta, VehicleStateData, VehicleStateEnvelope
from src.models.schemas import ChatRequest, ChatResponse
from src.services.vehicle_gateway import get_vehicle_gateway

router = APIRouter()

#: Thông điệp cho từng lý do xe ảo chưa sẵn sàng. Tách ra bảng vì client hiển thị
#: thẳng `message`, và ba lý do này đòi ba hành động khác nhau từ người vận hành.
_UNAVAILABLE_MESSAGE = {
    "broker_unreachable": "Backend chưa nối được broker MQTT.",
    "no_snapshot_yet": "Đã nối broker nhưng chưa nhận được snapshot nào từ xe ảo.",
    "no_health": "Chưa nhận được tín hiệu sức khoẻ nào từ xe ảo.",
    "offline": "Xe ảo báo đã ngắt kết nối.",
    "heartbeat_stale": "Xe ảo im lặng quá lâu — state đang giữ đã hết hạn.",
}

#: Endpoint `/chat` là bề mặt boilerplate cũ, giữ lại cho tương thích ngược.
#: Route theo phiên nằm ở `agent_routes.py`.
#:
#: Dựng lười (lazy) vì `build_graph` cần cổng xe, mà cổng chỉ được gắn trong
#: lifespan của `src/main.py`. Dựng ở mức module sẽ chốt cứng cổng mặc định
#: in-process ngay lúc import, tức `/chat` nói chuyện với một chiếc xe khác
#: mọi endpoint còn lại.
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = build_graph(get_vehicle_gateway())
    return _agent


@router.post("/chat", response_model=ChatResponse, include_in_schema=False)
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat với AI agent. **Không phải interface P0** — di sản boilerplate.

    Ẩn khỏi OpenAPI: `docs/api_spec.md:52` chốt P0 đúng 14 interface và "there is
    no general-purpose public agent-processing route". Để nó hiện trong `/docs`
    thì người làm frontend mở ra thấy endpoint không có trong hợp đồng và không
    biết tin cái nào.

    Route vẫn còn để không phá `tests/test_api/test_routes.py`. Xoá hẳn thuộc đợt
    dọn boilerplate, cùng lúc gỡ `src/agents/vehicle.py` (xem ADR-013) — nó là
    consumer cuối cùng của simulator dict.
    """
    try:
        result = await _get_agent().ainvoke(
            {"query": request.message, "session_id": "ses-chat", "vehicle_id": "veh-demo"}
        )
        return ChatResponse(
            response=result.get("response_text", ""),
            analysis=result.get("outcome", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/status", include_in_schema=False)
async def agent_status():
    """Kiểm tra trạng thái agent. **Không phải interface P0** — nhưng đừng xoá.

    Ẩn khỏi OpenAPI cùng lý do với `/chat`: nó không nằm trong 14 interface P0 nên
    không được lẫn vào hợp đồng công khai.

    Nhưng **không phải rác nữa**: PR #34 chuyển healthcheck của container backend
    trong `docker-compose.yml` từ `/health` (đã xoá) sang chính route này. Xoá nó
    là container không bao giờ healthy. Readiness thật vẫn ở `GET /healthz`; route
    này chỉ còn vai trò liveness rẻ tiền cho Docker.
    """
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}


def _cong_cua_phien(session_id, user, request_id, trace_id):  # noqa: ANN001, ANN202
    """Cổng của phiên gọi tới, hoặc cổng xe demo khi pool không cấp phát.

    ## Vì sao `session_id` là tuỳ chọn, nhưng KHÔNG phải lúc nào cũng bỏ được

    Khi pool không cấp phát (`vehicle_pool_size == 1`) thì cả hệ chỉ có một chiếc xe,
    nên tham số này không mang thông tin gì — bỏ đi là vô hại và client cũ chạy nguyên.

    Khi pool **có** cấp phát thì bỏ nó đi là hỏi "trạng thái xe" mà không nói xe nào.
    Trả về xe demo lúc đó là câu trả lời **sai một cách im lặng**: người đang lái
    `vivi-xe-02` sẽ điều khiển xe của mình nhưng nhìn màn hình của xe người khác. Nên
    thiếu tham số ở chế độ đó là lỗi tường minh, không phải một mặc định.

    ## Vì sao `get_current_user` chứ không `require_driver`

    Kỹ sư đọc trạng thái xe là việc chính đáng — màn kỹ sư sống bằng nó. Cái cần chặn là
    người **chưa đăng nhập**, và việc đọc phiên của **người khác**; cả hai đều không đòi
    vai tài xế.
    """
    if session_id is None:
        if get_vehicle_pool() is not None:
            raise ApiError(
                status_code=400,
                code="REQUEST_CONTEXT_INVALID",
                message="thiếu tham số session_id — hệ đang chạy nhiều xe nên phải nói rõ xe của phiên nào",
                request_id=request_id,
                trace_id=trace_id,
            )
        return get_vehicle_gateway()

    record = get_session_record(session_id)
    if record is None or record.user_id != user.user_id:
        # Không phân biệt "không tồn tại" với "của người khác" — tránh enumeration,
        # cùng câu chữ với `turns.py`.
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="session không tồn tại hoặc không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )
    # Khi pool bật, không có lease hiện tại mà vẫn trả cổng read-only của xe demo
    # sẽ làm phiên cũ nhìn thấy state của chiếc xe vừa được cấp cho người khác.
    # `GET /vehicle/state` phải hoặc trả state CỦA phiên, hoặc nói rõ phiên không
    # còn xe — không có mặc định thứ ba an toàn ở đây.
    xe = xe_cua_phien(session_id)
    if xe is None:
        raise ApiError(
            status_code=409,
            code="VEHICLE_LEASE_EXPIRED",
            message="Phiên không còn xe điều khiển khả dụng. Bạn đang ở chế độ chỉ xem.",
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
            details={"session_id": session_id},
        )
    return get_vehicle(session_id, xe=xe)


@router.get(
    "/vehicle/state",
    response_model=VehicleStateEnvelope,
    responses={
        503: {
            # `model` chứ không chỉ `description`: thiếu nó thì `/docs` không mô tả
            # hình dạng nhánh lỗi, và `ErrorEnvelope` không xuất hiện trong
            # components.schemas — người làm frontend vẫn phải đoán.
            "model": ErrorEnvelope,
            "description": (
                "MQTT_UNAVAILABLE — chưa nối broker, chưa có snapshot, hoặc state đã hết hạn. "
                "`error.details.reason` phân biệt năm nguyên nhân: `broker_unreachable`, "
                "`no_snapshot_yet`, `no_health`, `offline`, `heartbeat_stale`."
            ),
        }
    },
    summary="Trạng thái xe do simulator công bố (server-authoritative)",
)
async def vehicle_state(
    response: Response,
    request: Request,
    session_id: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
) -> VehicleStateEnvelope:
    """Trạng thái xe do simulator công bố.

    Backend chỉ forward, không map lại tên field — `data.vehicle_state` phải bằng
    đúng `VehicleStateSnapshot` trừ `schema_version` (docs/mqtt_spec.md).

    Ba nhánh 503 được đánh giá **theo đúng thứ tự dưới đây**, nhánh sau giả định
    nhánh trước đã qua. Snapshot cũ **không** được trả kèm cảnh báo: hợp đồng nói
    đây là state *authoritative*, mà dữ liệu của một simulator đã chết thì không
    còn authoritative — trả 200 lúc đó là nói dối một cách im lặng, và client
    không có cách nào biết.
    """
    request_id = new_request_id()
    trace_id = resolve_trace_id(request)
    gateway = _cong_cua_phien(session_id, user, request_id, trace_id)

    def unavailable(reason: str, details: dict) -> ApiError:
        return ApiError(
            status_code=503,
            code="MQTT_UNAVAILABLE",
            message=_UNAVAILABLE_MESSAGE[reason],
            request_id=request_id,
            trace_id=trace_id,
            retryable=True,
            details={"reason": reason, **details},
        )

    readiness = gateway.readiness()

    # B1 — chưa có đường tới broker. Cache có giữ gì cũng chỉ là tiếng vọng.
    if readiness.reason == "broker_unreachable":
        raise unavailable("broker_unreachable", {"mqtt_connected": False})

    # B2 — đã nối nhưng retained snapshot chưa về.
    state = await gateway.last_known()
    if state is None:
        raise unavailable("no_snapshot_yet", {"mqtt_connected": True})

    # B3 — có snapshot, nhưng nguồn phát ra nó không còn sống.
    if not readiness.ready:
        raise unavailable(
            readiness.reason,
            {
                "mqtt_connected": True,
                "simulator_online": readiness.online,
                "health_age_s": readiness.health_age_s,
                "heartbeat_stale_s": readiness.heartbeat_stale_s,
                "last_state_version": state.state_version,
            },
        )

    response.headers["X-Trace-Id"] = trace_id
    return VehicleStateEnvelope(
        data=VehicleStateData(vehicle_state=state),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )

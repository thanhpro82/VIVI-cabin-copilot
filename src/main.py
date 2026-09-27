import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from src.api.agent_routes import router as agent_router
from src.api.approvals import router as approvals_router
from src.api.auth_routes import router as auth_router
from src.api.citation_routes import router as citations_router
from src.api.errors import ApiError, api_error_handler, request_validation_error_handler
from src.api.health import router as health_router
from src.api.observability import router as observability_router
from src.api.place_routes import router as places_router
from src.api.routes import router
from src.api.routine_routes import router as routines_router
from src.api.session_routes import router as sessions_router
from src.api.sim_routes import router as sim_router
from src.api.turns import router as turns_router
from src.api.vehicle_profile_routes import router as vehicle_profile_router
from src.api.ws import router as ws_router
from src.config import get_settings
from src.db import expire_and_purge_sessions, get_connection, invalidate_orphaned_pending_approvals
from src.services.ivi_events import get_event_bus
from src.services.mqtt_runtime import MqttRuntime
from src.services.routine_execution import don_execution_mo_coi
from src.services.trace_collector import TraceCollector
from src.services.ui_policy import get_ui_policy_emitter
from src.services.vehicle_gateway import (
    InProcessVehicleGateway,
    MqttVehicleGateway,
    add_state_listener_factory,
    reset_vehicle_gateway,
    set_gateway_for,
)

logger = logging.getLogger(__name__)

# Trên Windows phải chạy bằng `python -m src.serve` chứ không phải
# `uvicorn src.main:app` — uvicorn chọn ProactorEventLoop, loop đó thiếu
# add_reader/remove_writer mà paho-mqtt cần. Xem src/serve.py.


def _warm_thac_chon_cau() -> None:
    """Ép thác nạp xong trọng số. Cờ tắt hoặc thiếu trọng số thì đây là no-op."""
    from src.agents.nodes.compose import _thac_chon_cau

    thac = _thac_chon_cau()
    if thac is not None:
        thac._mo_hinh()  # noqa: SLF001 — warm phải chạm đúng chỗ đắt, không chỉ dựng đối tượng


async def _warm_health_singletons() -> None:
    """Nạp trước singleton STT/TTS/RAG lúc startup — issue #51.

    `voice.get_stt_engine`/`get_tts_engine` và `rag_node._default_retriever`/
    `_default_embedder` đều `@lru_cache`, chỉ tải model thật ở lần gọi đầu. Không
    warm thì request `/healthz` đầu tiên sau khi backend vừa lên tự thấy các
    component đó `unready`/`down` — không phải hệ thống thật sự chưa sẵn sàng, mà
    vì chính probe đó tình cờ là lần chạm singleton đầu tiên.

    Chạy song song qua `asyncio.to_thread` (load model là I/O đồng bộ nặng, chặn
    event loop nếu await trực tiếp). Lỗi (model chưa tải theo
    `scripts/setup_voice_models.ps1`, RAG index chưa build) chỉ log — probe
    `/healthz` sẽ tự báo `down` đúng lý do ở mỗi lần poll sau, warm-up thất bại
    không được phép chặn backend khởi động.
    """
    import asyncio

    from src.agents.nodes import rag_node
    from src.services import voice

    warmers = {
        "stt": voice.get_stt_engine,
        "tts": voice.get_tts_engine,
        "rag_retriever": rag_node._default_retriever,  # noqa: SLF001 — cùng cách probe_rag_index đã dùng
        "rag_embedder": rag_node._default_embedder,  # noqa: SLF001
        # Thác chọn câu. Nạp trọng số **và** lượng tử hoá ngay ở đây, vì lượng tử hoá
        # là phần đắt: đo 18/08 cho 7,7–22,6 s tuỳ tải máy, trong khi đọc trọng số chỉ
        # 1,0 s. Không warm thì cả khoảng ấy rơi vào lượt tra sổ tay ĐẦU TIÊN của tài
        # xế. Đệm bản đã lượng tử hoá ra đĩa đã thử và tệ hơn (ghi 22,5 s, đọc 28,6 s,
        # tệp 1,3 GB) nên warm lúc khởi động là đường rẻ nhất còn lại.
        "chon_cau_thac": _warm_thac_chon_cau,
    }
    results = await asyncio.gather(*(asyncio.to_thread(fn) for fn in warmers.values()), return_exceptions=True)
    for name, result in zip(warmers, results, strict=True):
        if isinstance(result, Exception):
            logger.warning("Không warm được singleton %s lúc startup (%s) — /healthz sẽ tự báo down", name, result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)

    # Schema + seed trước mọi thứ khác: `session_state`/`auth`/`idempotency` đều đọc
    # ghi bảng ngay khi request đầu tiên tới. `get_connection()` tự dựng schema, gọi
    # ở đây để lỗi cấu hình `DATABASE_URL` nổ lúc khởi động chứ không nổ giữa một lượt.
    connection = get_connection()
    expired, purged = expire_and_purge_sessions(
        connection,
        now=datetime.now(UTC),
        ttl_hours=settings.session_ttl_hours,
        retention_days=settings.session_retention_days,
    )
    if expired or purged:
        logger.info("Dọn session lúc khởi động: %d hết hạn, %d bị xoá quá mốc lưu trữ", expired, purged)
    orphaned = invalidate_orphaned_pending_approvals(connection)
    if orphaned:
        # Xem docstring của hàm: bản ghi approval sống qua restart, nhưng lượt thì
        # không — checkpoint chứa `interrupt()` nằm trong `InMemorySaver`.
        logger.warning("Đã vô hiệu hoá %d approval còn treo từ lần chạy trước", orphaned)
    dang_do = don_execution_mo_coi(connection)
    if dang_do:
        # Cùng lý do: không có vòng lặp nào đang chạy để tiếp tục một chuỗi lệnh dở dang,
        # và spec chốt **không** Routine nào tự chạy tiếp sau restart. Để nguyên `running`
        # thì ràng buộc một-Routine-mỗi-phiên khoá luôn phiên ấy.
        logger.warning("Đã đóng %d lần chạy Routine còn dở từ lần chạy trước", dang_do)

    await _warm_health_singletons()

    app.state.mqtt = None
    #: Mọi runtime của pool, kể cả ô số 0. Rỗng khi `MQTT_ENABLED=false`.
    app.state.vehicle_runtimes = []
    vehicle_ids = settings.vehicle_pool_ids()
    if settings.mqtt_enabled:
        runtimes = [MqttRuntime(vid, heartbeat_stale_s=settings.mqtt_heartbeat_stale_s) for vid in vehicle_ids]
        # Ô số 0 là runtime **sở hữu** kết nối; `app.state.mqtt` trỏ vào nó nên
        # `probe_mqtt`/`probe_vehicle_simulator` không đổi một dòng.
        chinh = runtimes[0]
        try:
            await chinh.start(settings)
            app.state.mqtt = chinh
        except Exception:  # noqa: BLE001 — broker chết không được chặn cả backend
            # /vehicle/state và /ws/engineer sẽ trả MQTT_UNAVAILABLE cho tới
            # khi broker trở lại; client tự reconnect.
            logger.exception("Không nối được broker MQTT tại %s", settings.mqtt_url)
            await chinh.stop()
        # Các xe còn lại `bind` vào CHÍNH kết nối đó thay vì tự mở kết nối riêng.
        # Không phải để tiết kiệm: `MqttRuntime.start()` dùng `client_id="vivi-backend"`
        # cố định, nên K kết nối là K client trùng id và broker sẽ đá lần lượt từng cái
        # ra. `bind()` vốn được tách khỏi `start()` đúng cho kiểu dùng này.
        #
        # Bọc trong `if`: `start()` hỏng thì `chinh.client` là None và không có gì để bind.
        if chinh.client is not None:
            for phu in runtimes[1:]:
                await phu.bind(chinh.client, timeout_ms=settings.mqtt_command_timeout_ms)
        app.state.vehicle_runtimes = runtimes
        # Gắn cổng MQTT **kể cả khi start() hỏng**. Rơi về simulator in-process
        # lúc này sẽ là thay thầm một chiếc xe khác: API trả 200 với trạng thái
        # của một chiếc xe không ai điều khiển, và không ai biết. Cổng MQTT với
        # broker chết thì báo `broker_unreachable` — đúng sự thật.
        for runtime in runtimes:
            set_gateway_for(runtime.vehicle_id, MqttVehicleGateway(runtime))
    else:
        # MQTT tắt là lựa chọn tường minh của người vận hành (dev/CI), nên chạy
        # xe in-process là đúng ý chứ không phải thay thầm.
        for vid in vehicle_ids:
            set_gateway_for(vid, InProcessVehicleGateway.new(vid))

    yield

    # Ngược thứ tự: runtime sở hữu kết nối (ô số 0) đóng SAU CÙNG, nếu không thì các
    # runtime còn lại mất kết nối ngay dưới chân mình.
    for runtime in reversed(app.state.vehicle_runtimes):
        await runtime.stop()
    reset_vehicle_gateway()
    logger.info("Shutting down...")


app = FastAPI(
    title="AI20K Agent",
    description="AI Agent built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

# `ApiError` tự dịch ra envelope `{error, meta, trace_id, schema_version}` ở
# top-level — xem src/api/errors.py để biết vì sao không dùng HTTPException.
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, request_validation_error_handler)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#: Thu trace bằng cách nghe bus, không chen lệnh ghi vào `emit_turn_lifecycle`.
#: Đăng ký ở **mức module** chứ không trong `lifespan`: `ASGITransport` mà phần lớn
#: test API dùng không chạy lifespan, nên thứ gì gắn trong đó sẽ vắng mặt ở test —
#: cùng lý do đã ghi cho `get_vehicle_gateway()`.
trace_collector = TraceCollector()
get_event_bus().add_global_listener(trace_collector)

#: `ui.policy` bắt nguồn từ trạng thái xe (toàn cục) nhưng giao hàng theo session, nên
#: nó nghe cổng xe rồi broadcast. Kích **theo cạnh** — xem docstring `UiPolicyEmitter`:
#: bắn mỗi snapshot sẽ nhấn chìm ring buffer 200 event và phá replay của ADR-014.
#: Đăng ký mức module cùng lý do với `trace_collector` ngay trên.
#:
#: Dùng `add_persistent_state_listener` chứ **không** `get_vehicle_gateway().add_listener`:
#: `lifespan` gọi `set_vehicle_gateway(...)` để thay cổng, và listener gắn thẳng vào
#: instance lúc import sẽ nằm lại trên cổng đã bị bỏ — vế kích-theo-cạnh chết im ở
#: runtime trong khi test vẫn xanh (blocker Thành phát hiện ở PR #77).
add_state_listener_factory(lambda vehicle_id: get_ui_policy_emitter(vehicle_id).on_state)

app.include_router(router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(citations_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(turns_router, prefix="/api/v1")
app.include_router(observability_router, prefix="/api/v1")
# Kênh harness — ADR-024. Route tự trả 404 khi `sim_control_enabled=false`, nên
# đăng ký vô điều kiện ở đây là đúng: bật/tắt là chuyện của cấu hình runtime, và
# một app dựng trước khi đọc .env không được quyết hộ.
app.include_router(sim_router, prefix="/api/v1")
app.include_router(vehicle_profile_router, prefix="/api/v1")
app.include_router(routines_router, prefix="/api/v1")
app.include_router(places_router, prefix="/api/v1")
# WebSocket và /healthz không có prefix /api/v1 — api_spec.md chốt `WS /ws/ivi`,
# `WS /ws/engineer`, và `GET /healthz` ở gốc.
app.include_router(ws_router)
app.include_router(health_router)

"""Probe cho 8 dependency của GET /healthz — 7 bắt buộc, `llm` miễn trừ ở P0.

Mỗi probe tự bắt lỗi của chính nó và không bao giờ raise ra ngoài — bất kỳ
exception/timeout/dependency chưa cấu hình nào đều ánh xạ thành `down`
(fail-closed, theo tiền lệ ADR-005: "not-selected" không tự coi là ready).
`docs/devops.md` §Readiness contract và `docs/api_spec.md#health` là nguồn
sự thật cho tên 8 component và ngữ nghĩa 3 trạng thái. Xem `REQUIRED_COMPONENT_NAMES`
cho readiness gate thật (issue #48).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from src.config import Settings

if TYPE_CHECKING:
    import httpx

    from src.services.mqtt_runtime import MqttRuntime

#: `disabled` là trạng thái thứ tư, thêm ở issue #95: **tắt có chủ đích ≠ hỏng**.
#: Trước đó `slm_enabled=false` (mặc định P0) và `MQTT_ENABLED=false` (cấu hình chạy
#: test/demo offline của cả repo) đều ánh xạ thành `down`, nên `/healthz` trả 503
#: vĩnh viễn ở đúng cấu hình mà cả nhóm đang chạy — báo "hệ thống chưa sẵn sàng" về
#: một dependency mà cấu hình đang chạy không hề cần.
Status = Literal["ready", "degraded", "down", "disabled"]

#: Trạng thái **chặn** readiness. Viết theo hướng chặn chứ không theo hướng
#: "ready mới qua": thêm một trạng thái quan sát được về sau (`starting`, `draining`)
#: thì phải cân nhắc rõ ràng nó có chặn hay không, chứ không âm thầm thành 503.
BLOCKING_STATUSES: frozenset[str] = frozenset({"down", "degraded"})

#: 8 component đo và hiển thị, đúng tên và đúng thứ tự của `docs/api_spec.md:495`.
#: Ở đây chứ không ở route, vì `/healthz` và event `health` của `/ws/engineer` đều
#: đọc — hai bảng tên rời nhau sẽ lệch nhau lúc nào không biết.
COMPONENT_NAMES: tuple[str, ...] = (
    "backend",
    "llm",
    "mqtt",
    "vehicle_simulator",
    "stt",
    "tts",
    "rag_index",
    "sqlite",
)

#: `llm` miễn trừ khỏi readiness gate ở P0 (issue #48): `slm_enabled=False` theo
#: thiết kế (ADR-005 "Not Yet"), nên nó không bao giờ `ready` — trước quyết định
#: này, `/healthz` báo 503 vĩnh viễn vì một dependency không tồn tại ở P0, không
#: phải vì hệ thống thật sự chưa sẵn sàng. Vẫn đo và hiển thị trạng thái `llm`
#: (không xoá khỏi `COMPONENT_NAMES`/`components`/`faults`) — chỉ không tính nó
#: vào gate `ready`/`503`. Khi LLM/SLM trở thành dependency bắt buộc của luồng
#: P0/P1 thì đưa lại vào `REQUIRED_COMPONENT_NAMES`.
REQUIRED_COMPONENT_NAMES: frozenset[str] = frozenset(COMPONENT_NAMES) - {"llm"}


def is_ready(components: dict[str, ProbeResult]) -> bool:
    """Readiness gate — **một** định nghĩa, dùng chung cho `/healthz` và `/ws/engineer`.

    Trước issue #95 vòng lặp này nằm hai chỗ, chép tay giống nhau; sửa một bên mà quên
    bên kia thì hai đường đọc cho hai câu trả lời khác nhau về cùng một hệ thống, đúng
    loại lỗi ADR-013 đã cấm cho vehicle state.

    Hai lớp miễn trừ, khác nhau về lý do và không được nhập làm một:

    - `REQUIRED_COMPONENT_NAMES` miễn trừ **theo tên**: `llm` không chặn ngay cả khi nó
      hỏng thật (issue #48) — nó chưa là dependency của luồng P0.
    - `BLOCKING_STATUSES` miễn trừ **theo trạng thái**: `disabled` không chặn vì cấu hình
      đang chạy không cần component ấy (issue #95). Component nào cũng áp dụng.

    Điều này để lại `mqtt`/`vehicle_simulator` **vẫn chặn khi bật mà hỏng** — tắt khác
    hỏng, và đó chính là thứ `/healthz` sinh ra để bắt.
    """
    return not any(
        result.status in BLOCKING_STATUSES for name, result in components.items() if name in REQUIRED_COMPONENT_NAMES
    )


@dataclass(frozen=True)
class ProbeResult:
    status: Status
    latency_ms: float
    detail: str | None = None


def _elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000


async def run_with_timeout(probe: Awaitable[ProbeResult], timeout_s: float, timeout_detail: str) -> ProbeResult:
    """Bọc một probe với giới hạn thời gian và bắt mọi exception — một
    dependency treo hoặc lỗi bất ngờ không được làm sập cả endpoint. Đây là
    điểm thắt duy nhất mọi probe (cả 8 component) đều đi qua, nên fail-closed
    ở đây là đủ cho toàn bộ /healthz, không cần try/except riêng ở từng probe."""
    import asyncio

    started = time.perf_counter_ns()
    try:
        return await asyncio.wait_for(probe, timeout=timeout_s)
    except TimeoutError:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=timeout_detail)
    except Exception as exc:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"probe_error:{exc}")


async def probe_backend() -> ProbeResult:
    """Backend tự kiểm — event loop còn phản hồi là ready."""
    import asyncio

    started = time.perf_counter_ns()
    await asyncio.sleep(0)
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))


async def probe_mqtt(runtime: MqttRuntime | None, settings: Settings) -> ProbeResult:
    """`mqtt=down` khi chưa nối broker, publish thăm dò lỗi, hoặc hết timeout.

    `mqtt=disabled` khi `MQTT_ENABLED=false` (issue #95) — quyết định theo **cấu hình**,
    không theo sự hiện diện của `runtime`: `lifespan` không dựng runtime khi cờ tắt, nên
    hai thứ trùng nhau trên thực tế, nhưng đọc cấu hình mới nói được *vì sao* nó vắng.
    Nhánh này cũng chặn luôn việc publish thăm dò lên một broker mà cấu hình nói không dùng.

    Round-trip thật (issue #51): publish QoS 1 lên `mqtt_topics.health_probe()`
    — broker phải PUBACK trước khi `publish()` trả về (`aiomqtt.Client.publish`
    tự `await` `confirmation.wait()` cho QoS ≥ 1), bằng chứng broker đang sống
    và xác thực được backend. Trước đây chỉ đọc `runtime.connected`
    (`self.client is not None`): cờ đó set một lần lúc bind và không bao giờ tự
    clear, nên không phát hiện được kết nối đã chết mà runtime chưa kịp
    reconnect — đúng loại "connection-state proxy" issue #51 nêu.
    """
    from src import mqtt_topics

    started = time.perf_counter_ns()
    if not settings.mqtt_enabled:
        return ProbeResult(status="disabled", latency_ms=_elapsed_ms(started), detail="mqtt_disabled")
    if runtime is None or runtime.client is None:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail="mqtt_not_connected")
    try:
        await runtime.client.publish(mqtt_topics.health_probe(runtime.vehicle_id), {"probed_at": time.time()}, qos=1)
    except Exception as exc:  # noqa: BLE001 — mọi lỗi publish/ack đều nghĩa là broker không round-trip được
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"mqtt_probe_failed:{exc}")
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))


async def probe_vehicle_simulator(runtime: MqttRuntime | None, settings: Settings) -> ProbeResult:
    """`vehicle_simulator=down` khi thiếu heartbeat xác thực còn tươi.

    **Quyết định cổng 3 của issue #95:** khi `MQTT_ENABLED=false`, simulator là
    `disabled` chứ không phải `down`. Nó chỉ tới được qua MQTT — heartbeat của nó đi
    trên chính broker vừa tắt — nên sự vắng mặt ở đây là *hệ quả trực tiếp của lựa chọn
    tắt MQTT*, không phải dấu hiệu simulator hỏng. Để nó `down` sẽ dựng lại nguyên cái
    503 mà thay đổi này gỡ đi, chỉ đổi tên component; và vì `vehicle_simulator` nằm
    trong `REQUIRED_COMPONENT_NAMES` (khác `llm`), nó sẽ chặn thật.

    Khi MQTT **bật** mà heartbeat cũ thì vẫn `down` như trước — đó mới là hỏng.
    """
    started = time.perf_counter_ns()
    if not settings.mqtt_enabled:
        return ProbeResult(status="disabled", latency_ms=_elapsed_ms(started), detail="vehicle_simulator_mqtt_disabled")
    if runtime is not None and runtime.cache.simulator_ready():
        return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))
    return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail="vehicle_simulator_heartbeat_stale")


async def probe_sqlite(settings: Settings) -> ProbeResult:
    """`sqlite=down` khi mở/đọc/ghi database_url thất bại."""
    import asyncio

    from src import db

    started = time.perf_counter_ns()
    try:
        await asyncio.to_thread(db.health_check, settings)
    except (sqlite3.Error, ValueError) as exc:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"sqlite_error:{exc}")
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))


async def probe_llm(settings: Settings, client: httpx.AsyncClient | None = None) -> ProbeResult:
    """`llm` chỉ trỏ tới SLM cục bộ (`slm_endpoint`) — không bao giờ gọi cloud.

    `llm=disabled` khi `slm_enabled=False` — **không** phải `down` (issue #95). Tiền
    lệ ADR-005 ("not-selected" không tự coi là ready) vẫn giữ: `disabled` cũng không
    phải `ready`, nó chỉ không bị tính là hỏng. `/props` dùng để xác nhận đúng model
    đang chạy; server không có `/props` thì `/health` qua là đủ ready.

    Còn khi `slm_enabled=True` mà server không tới được thì vẫn `down` — và vẫn không
    chặn readiness, nhưng qua đường khác: miễn trừ theo tên của issue #48.
    """
    import httpx

    started = time.perf_counter_ns()
    if not settings.slm_enabled:
        return ProbeResult(status="disabled", latency_ms=_elapsed_ms(started), detail="slm_disabled")

    endpoint = settings.slm_endpoint.rstrip("/")
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=settings.slm_timeout_s)
    try:
        try:
            health_response = await http_client.get(f"{endpoint}/health")
            health_response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"slm_unreachable:{exc}")

        identity_confirmed = True
        try:
            props_response = await http_client.get(f"{endpoint}/props")
            props_response.raise_for_status()
            identity_confirmed = settings.slm_model_id in props_response.text
        except httpx.HTTPError:
            pass  # /props không có trên bản server này — /health qua là đủ

        if not identity_confirmed:
            return ProbeResult(status="degraded", latency_ms=_elapsed_ms(started), detail="slm_model_mismatch")
        return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))
    finally:
        if owns_client:
            await http_client.aclose()


_PROBE_CACHE: dict[str, tuple[float, ProbeResult]] = {}


def clear_probe_cache() -> None:
    """Test helper: xoá cache TTL của probe_stt/probe_tts giữa các test."""
    _PROBE_CACHE.clear()


async def _cached(key: str, ttl_s: float, live_probe: Callable[[], Awaitable[ProbeResult]]) -> ProbeResult:
    """`live_probe` phải là callable, không phải coroutine đã tạo sẵn — nếu
    cache hit thì nó không bao giờ được gọi, và một coroutine tạo sẵn nhưng
    chưa await sẽ bị Python cảnh báo rò rỉ (`coroutine was never awaited`)."""
    now = time.monotonic()
    cached = _PROBE_CACHE.get(key)
    if cached is not None and now - cached[0] < ttl_s:
        return cached[1]
    result = await live_probe()
    _PROBE_CACHE[key] = (now, result)
    return result


async def probe_stt(settings: Settings) -> ProbeResult:
    """Chạy transcribe thật trên một mẫu WAV im lặng ngắn — kết quả cache theo TTL."""
    return await _cached("stt", settings.health_voice_probe_ttl_s, _probe_stt_live)


async def _probe_stt_live() -> ProbeResult:
    import asyncio
    import io
    import wave

    from src.services import voice

    def _silence_wav(duration_s: float = 0.5, frame_rate: int = 16000) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(frame_rate)
            wav_file.writeframes(b"\x00\x00" * int(duration_s * frame_rate))
        return buffer.getvalue()

    started = time.perf_counter_ns()
    try:
        await asyncio.to_thread(voice.transcribe_raw, _silence_wav())
    except (OSError, ValueError) as exc:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"stt_unavailable:{exc}")
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))


async def probe_tts(settings: Settings) -> ProbeResult:
    """Chạy synthesize thật trên một câu ngắn cố định — kết quả cache theo TTL."""
    return await _cached("tts", settings.health_voice_probe_ttl_s, _probe_tts_live)


async def _probe_tts_live() -> ProbeResult:
    import asyncio

    from src.services import voice

    started = time.perf_counter_ns()
    try:
        await asyncio.to_thread(lambda: list(voice.synthesize("kiểm tra hệ thống")))
    except (OSError, ValueError) as exc:
        return ProbeResult(status="down", latency_ms=_elapsed_ms(started), detail=f"tts_unavailable:{exc}")
    return ProbeResult(status="ready", latency_ms=_elapsed_ms(started))


async def probe_rag_index(settings: Settings) -> ProbeResult:
    """manifest/checksum/open/query smoke — dùng đúng retriever/embedder mà
    đường truy hồi thật đang dùng (qua rag_node's cached singletons), tránh
    nạp FAISS/embedder hai lần.

    Lưu ý: bước checksum dùng `settings.rag_index_dir` (tham số truyền vào),
    nhưng bước query thật lại dùng singleton của rag_node (nội bộ gọi
    `get_settings()`) — hai giá trị này chỉ đảm bảo khớp nhau khi `settings`
    truyền vào chính là `get_settings()` process-wide, đúng như router ở
    Task 8 luôn làm. Truyền một `Settings` khác (ví dụ trong test) khiến
    bước checksum và bước query kiểm hai thư mục khác nhau.

    Kết quả cache theo TTL (issue #51) — cùng lý do và cùng cơ chế với
    `probe_stt`/`probe_tts`: re-hash checksum + chạy 1 query FAISS/embedder
    thật mỗi lần `/healthz` bị poll là tốn CPU không cần thiết. Khoá cache theo
    `settings.rag_index_dir` chứ không phải chuỗi cố định `"rag_index"` — test
    truyền `Settings` khác nhau (khác `rag_index_dir`) trong cùng tiến trình
    không được đọc nhầm cache của nhau."""
    return await _cached(
        f"rag_index:{settings.rag_index_dir}", settings.health_rag_probe_ttl_s, lambda: _probe_rag_index_live(settings)
    )


async def _probe_rag_index_live(settings: Settings) -> ProbeResult:
    import asyncio

    started = time.perf_counter_ns()
    status, detail = await asyncio.to_thread(_probe_rag_index_sync, settings)
    return ProbeResult(status=status, latency_ms=_elapsed_ms(started), detail=detail)


def _probe_rag_index_sync(settings: Settings) -> tuple[Status, str | None]:
    import json
    from pathlib import Path

    from src.agents.nodes import rag_node
    from src.rag.index import VectorIndex

    index_dir = Path(settings.rag_index_dir)
    if not rag_node.index_is_built(index_dir):
        return "down", "rag_index_not_built"

    try:
        manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "down", f"rag_manifest_unreadable:{exc}"

    expected_checksum = manifest.get("index_checksum")
    try:
        actual_checksum = VectorIndex.checksum(index_dir)
    except OSError as exc:
        return "down", f"rag_checksum_unreadable:{exc}"
    if expected_checksum != actual_checksum:
        return "down", "rag_checksum_mismatch"

    try:
        retriever = rag_node._default_retriever()
        embedder = rag_node._default_embedder()
        retriever.search("kiểm tra hệ thống", embedder)
    except (OSError, ValueError) as exc:
        return "down", f"rag_query_failed:{exc}"

    return "ready", None


async def collect_health(settings: Settings, runtime: MqttRuntime | None) -> dict[str, ProbeResult]:
    """Chạy cả 8 probe song song, trả `{tên component: ProbeResult}`.

    Trích ra khỏi route `GET /healthz` để event `health` của `/ws/engineer` dùng
    **đúng một** đường đọc readiness. Hai đường riêng sẽ cho hai câu trả lời khác
    nhau về cùng một hệ thống, đúng loại lỗi mà ADR-013 đã cấm cho vehicle state.

    Trả `ProbeResult` thô chứ không phải payload đã format: route cần `detail` để
    dựng `error.details.dependencies` cho nhánh 503, còn WS thì không — mỗi bên tự
    format phần của mình.
    """
    import asyncio

    timeout_s = settings.health_probe_timeout_s
    results = await asyncio.gather(
        run_with_timeout(probe_backend(), timeout_s, "backend_timeout"),
        run_with_timeout(probe_llm(settings), timeout_s, "llm_timeout"),
        run_with_timeout(probe_mqtt(runtime, settings), timeout_s, "mqtt_timeout"),
        run_with_timeout(probe_vehicle_simulator(runtime, settings), timeout_s, "vehicle_simulator_timeout"),
        run_with_timeout(probe_stt(settings), timeout_s, "stt_timeout"),
        run_with_timeout(probe_tts(settings), timeout_s, "tts_timeout"),
        run_with_timeout(probe_rag_index(settings), timeout_s, "rag_index_timeout"),
        run_with_timeout(probe_sqlite(settings), timeout_s, "sqlite_timeout"),
    )
    return dict(zip(COMPONENT_NAMES, results, strict=True))


def health_event_payload(components: dict[str, ProbeResult], checked_at: str) -> dict[str, object]:
    """Payload cho event `health` của `/ws/engineer` — api_spec.md:609.

    Luôn dùng hình dạng của nhánh **200** (`status`, `checked_at`, `components` có
    `latency_ms`, `faults`), kể cả khi có component `down`. Nhánh 503 của REST có
    hình dạng khác hẳn (`error.details.dependencies`, không `latency_ms`) — đó là
    đường riêng của HTTP, không phải của WS. `frontend/src/lib/services/engineer/
    real.ts` `mapHealth()` đọc đường WS và cần đủ `checked_at` + `latency_ms`.

    `faults` chỉ mang **tên component và mã đã cắt**, không mang chuỗi exception
    đầy đủ: `detail` có thể chứa đường dẫn model hoặc thông điệp lỗi của thư viện,
    mà `api_spec.md:612` cấm lộ secret path ra bề mặt kỹ sư.

    `status` tổng chỉ xét `REQUIRED_COMPONENT_NAMES` (issue #48: `llm` miễn trừ ở
    P0) — nhưng `components`/`faults` vẫn liệt kê đủ 8 tên, kể cả `llm`, để không
    giấu trạng thái thật của nó.
    """
    return {
        "status": "ready" if is_ready(components) else "down",
        "checked_at": checked_at,
        "components": {
            name: {"status": result.status, "latency_ms": result.latency_ms} for name, result in components.items()
        },
        "faults": [
            {"component": name, "status": result.status, "code": (result.detail or "").split(":", 1)[0]}
            for name, result in components.items()
            if result.status != "ready"
        ],
    }

"""Kho trace vận hành trong bộ nhớ — nguồn duy nhất cho `/traces/{id}` và `/metrics/summary`.

`docs/api_spec.md` mục "Trace" và "Metrics" mô tả hai bề mặt khác nhau nhưng **cùng
một dữ liệu**: một cái đọc lẻ một bản ghi, một cái fold cả cửa sổ. Nên ở đây chỉ có
một kho; `src/services/metrics.py` là hàm thuần đọc lại kho này, không giữ counter
riêng. Thêm một metric mới về sau là thêm một phép fold, không phải nhớ tăng biến
đếm ở năm chỗ.

GIỚI HẠN ĐÃ BIẾT — `docs/data_model.md:304` quy định `trace_spans` giữ **30 ngày
trong SQLite**. Repo chưa persist bất cứ thứ gì (approval store cũng vậy), nên kho
này là in-memory có trần và mất sạch khi restart. Ghi ở đây để không ai đọc code
rồi tưởng hợp đồng lưu trữ đã đạt.

REDACTION — `api_spec.md:11,445,686` cấm lộ raw prompt / chain-of-thought / raw
audio / **unrestricted transcript** / credential / secret path ra bề mặt kỹ sư.
Đọc kỹ danh sách đó: nó cấm **câu người dùng nói**, không cấm câu hệ thống trả lời.

Ranh giới, theo ADR-029:

- `answer_text` **có** lưu. Nó do server sinh 100% — hoặc là template tiếng Việt
  dựng từ tên tool + tham số, hoặc là trích nguyên văn sổ tay VF9. Không đường nào
  trong `compose.py` chèn lời tài xế vào đó.
- Transcript (`transcript.final.text`) và nội dung citation **vẫn không có field**.
  Đó mới là nội dung của tài xế. Bảo đảm bằng cấu trúc: không lưu thì không rò.

Đừng thêm field cho transcript hay excerpt vào đây.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime

from src.bounded_cache import BoundedCache
from src.models.vehicle import utc_now

logger = logging.getLogger(__name__)

#: Trần độ dài `answer_text`. Đây là **lưới an toàn RAM**, không phải chính sách:
#: câu dài nhất hôm nay là một trích sổ tay ở `QUOTE_MAX_CHARS = 1200` cộng lead-in,
#: nên không câu thật nào bị cắt. Kho giữ tối đa `trace_store_maxsize` bản ghi (mặc
#: định 200), tức trần đóng góp của trường này là ~400 KB.
ANSWER_TEXT_MAX_CHARS = 2000

#: Bảy stage của `stage_latencies_ms`, đúng thứ tự và đúng tên trong api_spec.md:342.
#: Spec chốt "has exactly" — không thêm, không bớt.
STAGE_NAMES: tuple[str, ...] = (
    "stt",
    "routing",
    "planning_or_retrieval",
    "safety",
    "tool",
    "tts",
    "end_to_end",
)


@dataclass
class StageTimings:
    """Độ trễ từng stage, đơn vị ms. `None` = chưa đo được stage đó ở lượt này.

    `None` chứ không phải `0.0`: cửa sổ rỗng và "stage không chạy" phải phân biệt
    được với "stage chạy hết 0ms", nếu không thì p50/p95 bị kéo về 0 bởi những lượt
    chưa từng đi qua stage đó.
    """

    stt: float | None = None
    routing: float | None = None
    planning_or_retrieval: float | None = None
    safety: float | None = None
    tool: float | None = None
    tts: float | None = None
    end_to_end: float | None = None

    def as_dict(self) -> dict[str, float | None]:
        return {name: getattr(self, name) for name in STAGE_NAMES}


@dataclass
class TraceRecord:
    """Một lượt thoại, nhìn từ phía vận hành.

    Field ở đây là **dữ liệu thô đã khử nhạy cảm**; việc dựng thành hình dạng
    `api_spec.md:330-380` nằm ở `src/models/observability.py`.
    """

    trace_id: str
    session_id: str
    turn_id: str
    opened_at: datetime
    sealed_at: datetime | None = None

    #: Trạng thái mới nhất — enum ở `src/models/observability.py:TRACE_STATUSES`.
    status: str = "transcribing"
    #: Outcome cuối của graph (`completed`, `blocked`, `grounded_answer`, ...).
    outcome: str | None = None

    stages: StageTimings = field(default_factory=StageTimings)
    approval_wait_ms: float | None = None

    # -- định tuyến ------------------------------------------------------------
    route_source: str | None = None
    intent: str | None = None
    #: Độ tin cậy của **bộ định tuyến**, không phải của ASR.
    confidence: float | None = None
    #: Độ tin cậy của ASR, lấy từ `transcript.final`. Không kèm văn bản.
    transcript_confidence: float | None = None

    # -- kế hoạch và an toàn ---------------------------------------------------
    plan_id: str | None = None
    tool_names: tuple[str, ...] = ()
    max_safety_level: str | None = None
    block_code: str | None = None
    requires_approval: bool = False

    # -- HITL ------------------------------------------------------------------
    approval_id: str | None = None
    approval_expires_at: str | None = None
    approval_requested_at: datetime | None = None
    #: `pending` → `executed`/`canceled`/`blocked`. Xem `ADMISSION_STATUSES`.
    admission_status: str = "not_applicable"
    execution_group_id: str | None = None
    approved_vehicle_state_version: int | None = None
    actual_vehicle_state_version: int | None = None
    planning_vehicle_state_version: int | None = None

    # -- thực thi --------------------------------------------------------------
    #: `_wire_tool_status` của `ivi_events.py` — `completed|failed|timeout|
    #: skipped_due_to_prior_failure|skipped_external_state_change`.
    step_statuses: tuple[str, ...] = ()
    #: Độ trễ từng bước, để fold ra `mqtt.latency_ms`.
    step_latencies_ms: tuple[float, ...] = ()

    # -- RAG -------------------------------------------------------------------
    citation_count: int = 0
    refusal_reason: str | None = None

    # -- nội dung an toàn ------------------------------------------------------
    #: Câu VIVI trả lời tài xế (`assistant.response.display_text`), cắt ở
    #: `ANSWER_TEXT_MAX_CHARS`. Xem ghi chú REDACTION đầu file trước khi đụng vào.
    answer_text: str | None = None
    #: Lượt này do **mic tự mở** bắt được (`X-Capture-Mode: auto`, spec §3.5) hay do tài
    #: xế chủ động gọi. Cần ở trace vì cửa sổ nghe tiếp làm **tăng số lượt**, và không
    #: phân biệt được thì bảng nhật ký mất tác dụng chẩn đoán: một chuỗi lượt rác do
    #: tiếng nói trong xe trông y hệt một chuỗi lượt tài xế thật sự ra lệnh.
    #:
    #: Cũng là mẫu số của phép đo mà spec §7 dùng để quyết ba mục đa lượt còn lại có
    #: đáng làm không.
    bat_tu_dong: bool = False
    #: Xe mà lượt này tác động lên, đọc từ `sessions.vehicle_id` lúc mở trace.
    #: Hôm nay cả hệ chỉ có một xe nên nó là hằng; sau ADR-028 (pool xe ảo theo
    #: phiên) nó phân biệt được các xe mà **không phải sửa gì ở đây**, vì pool ghi
    #: chiếc xe đã thuê vào đúng cột đó.
    vehicle_id: str | None = None

    @property
    def is_sealed(self) -> bool:
        return self.sealed_at is not None


class TraceStore:
    """LRU có trần, khoá theo `trace_id`, kèm index phụ `turn_id → trace_id`.

    Index phụ tồn tại vì hai nửa của một lượt S2 đến từ hai request khác nhau
    (`POST /turns/voice` rồi `POST /approvals/{id}/decision`), và tới khi
    `src/api/approvals.py` còn đúc `trace_id` mới lúc resume thì `turn_id` là thứ
    duy nhất nối được chúng. Xem docs/tasks/TASK-BE-OBS-001 §Tier 3.

    Khoá bằng `threading.Lock` chứ không phải `asyncio.Lock`: cùng lý do với
    `ApprovalStore` — store bị chạm từ cả handler async lẫn `asyncio.to_thread`.
    """

    def __init__(self, maxsize: int = 200) -> None:
        self._cache: BoundedCache[str, TraceRecord] = BoundedCache(maxsize)
        self._by_turn: BoundedCache[str, str] = BoundedCache(maxsize)
        self._lock = threading.Lock()
        #: Lúc kho này bắt đầu thu. `src/services/metrics.py` chặn cửa sổ rolling
        #: tại đây để không bao giờ báo một cửa sổ 60 phút khi mới thu được 5 phút
        #: dữ liệu.
        #:
        #: Mốc đó thuộc về **kho**, không phải về module. Bản trước giữ nó ở
        #: `metrics._BOOT_AT` — chốt lúc import module — nên sau mỗi
        #: `reset_trace_store()` (test gọi liên tục) cửa sổ vẫn neo vào mốc import
        #: của process và báo dài hơn quãng thời gian kho thật sự tồn tại. Để ở đây
        #: thì nó vừa đúng ngữ nghĩa vừa test được mà không phải thò tay vào biến
        #: private của module.
        self.created_at = utc_now()

    # -- ghi -------------------------------------------------------------------

    def open(self, trace_id: str, session_id: str, turn_id: str) -> TraceRecord:
        """Mở bản ghi cho một lượt.

        Idempotent **theo lượt**: gọi lại với cùng `(trace_id, turn_id)` thì trả bản
        cũ, vì `turn.accepted` có thể tới sau một sự kiện khác nếu thứ tự publish
        đổi, và mở đè sẽ xoá mất những gì đã thu được.

        Nhưng cùng `trace_id` với **`turn_id` khác** thì phải là bản ghi mới, không
        được trộn. `POST /turns/text` lấy `trace_id` từ `request_scoped_ids()`, tức
        từ header `X-Trace-Id` mà `docs/api_spec.md:9` cho phép client tự đặt — nên
        khoá này **client chi phối được**. Một client gửi lại cùng giá trị cho hai
        lượt sẽ khiến hai lượt nhập làm một: `turns.accepted` đếm thiếu, stage
        latency lượt sau đè lượt trước, và `GET /traces/{id}` trả về một bản ghi lai.
        Lượt mới thắng khoá (client tự chọn trùng thì đó là ngữ nghĩa hợp lý nhất),
        nhưng việc mất bản cũ phải để lại vết trong log chứ không im lặng.
        """
        with self._lock:
            existing = self._cache.get(trace_id)
            if existing is not None:
                if existing.turn_id == turn_id:
                    return existing
                logger.warning(
                    "trace_id %s bị dùng lại cho lượt khác (%s -> %s); bản ghi cũ bị thay",
                    trace_id,
                    existing.turn_id,
                    turn_id,
                )
            record = TraceRecord(trace_id=trace_id, session_id=session_id, turn_id=turn_id, opened_at=utc_now())
            self._cache.set(trace_id, record)
            if turn_id:
                self._by_turn.set(turn_id, trace_id)
            return record

    def update(self, trace_id: str, **changes: object) -> TraceRecord | None:
        """Sửa field của một bản ghi. Trace lạ thì bỏ qua, không tạo mới.

        Không tự tạo: một sự kiện mồ côi (trace đã bị LRU đẩy ra) mà tạo lại bản
        ghi rỗng sẽ đẻ ra trace không có `opened_at` đúng và làm lệch metrics.
        """
        with self._lock:
            record = self._cache.get(trace_id)
            if record is None:
                return None
            updated = replace(record, **changes)  # type: ignore[arg-type]
            self._cache.set(trace_id, updated)
            return updated

    def record_stage(self, trace_id: str, stage: str, latency_ms: float) -> None:
        """Ghi độ trễ một stage. **Last-write-wins, KHÔNG cộng dồn.**

        LangGraph chạy lại thân node từ đầu khi resume approval (xem docstring
        `src/agents/approval.py`), nên cộng dồn sẽ nhân đôi số đo của mọi node
        chạy trước điểm interrupt. Ghi đè là con số đúng của lần chạy cuối.
        """
        if stage not in STAGE_NAMES:
            raise ValueError(f"stage {stage!r} không thuộc bảy stage của api_spec.md:342")
        with self._lock:
            record = self._cache.get(trace_id)
            if record is None:
                return
            setattr(record.stages, stage, latency_ms)
            self._cache.set(trace_id, record)

    def seal(self, trace_id: str, **changes: object) -> TraceRecord | None:
        """Đóng bản ghi. Seal lần hai không đổi `sealed_at` đã có."""
        with self._lock:
            record = self._cache.get(trace_id)
            if record is None:
                return None
            sealed = replace(record, sealed_at=record.sealed_at or utc_now(), **changes)  # type: ignore[arg-type]
            self._cache.set(trace_id, sealed)
            return sealed

    # -- đọc -------------------------------------------------------------------

    def get(self, trace_id: str) -> TraceRecord | None:
        with self._lock:
            return self._cache.get(trace_id)

    def get_by_turn(self, turn_id: str) -> TraceRecord | None:
        with self._lock:
            trace_id = self._by_turn.get(turn_id)
            return self._cache.get(trace_id) if trace_id else None

    def records_between(self, start: datetime, end: datetime) -> list[TraceRecord]:
        """Bản ghi mở trong cửa sổ nửa mở `[start, end)` — api_spec.md:452.

        Lọc theo `opened_at` chứ không phải `sealed_at`: một lượt đang chờ người
        duyệt vẫn phải đếm vào `turns.accepted`, và spec đã lường trước
        (`api_spec.md:456`: "in-flight accepted turns need not equal terminal
        totals").
        """
        with self._lock:
            records = list(self._cache.values())
        return [record for record in records if start <= record.opened_at < end]

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


_STORE: TraceStore | None = None
_STORE_LOCK = threading.Lock()


def get_trace_store() -> TraceStore:
    """Singleton mức module, **không** phải `app.state`.

    Cùng lý do đã ghi ở `src/services/vehicle_gateway.py`: `ASGITransport` trong
    test không chạy lifespan, nên thứ gì gắn vào `app.state` sẽ là `None` với phần
    lớn test API.
    """
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                from src.config import get_settings

                _STORE = TraceStore(get_settings().trace_store_maxsize)
    return _STORE


def set_trace_store(store: TraceStore) -> None:
    global _STORE
    _STORE = store


def reset_trace_store() -> None:
    """Hook cho test — trace của test trước không được rò sang test sau."""
    global _STORE
    _STORE = None

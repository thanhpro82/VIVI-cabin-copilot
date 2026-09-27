"""Kiểu dữ liệu dùng chung cho agent graph.

Hai ranh giới được mã hóa ở đây chứ không phải bằng quy ước:
`CandidateActionPlan` (thứ router/SLM được sinh) **không có** trường safety,
và `ActionPlan` (thứ executor nhận) từ chối validate nếu một step S2 không
kèm `requires_approval`. Xem `docs/agent_spec.md` mục
"Candidate-to-canonical plan boundary".
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

SafetyLevel = Literal["S0", "S1", "S2", "S3"]
#: `offer` = câu hỏi khớp một luật điều khiển. Nêu việc sẽ làm rồi hỏi lại, **không**
#: thực thi. Xem ADR-011: nó tồn tại để câu hỏi không bao giờ chạm executor, nhờ đó
#: `question_to_control` bằng 0 về mặt cấu trúc thay vì nhờ tinh chỉnh luật.
#: `"routine"` thêm 30/08 (#274): một Routine là 1–4 hành động có **vòng đời riêng**
#: (`routine_executions`), có preview, và hủy được giữa chừng. Nhét nó vào `"control"` là
#: ép một thứ có vòng đời vào một hợp đồng không có vòng đời nào — và `control` thì **bắt
#: buộc** mang `candidate_plan`, mà ở đây plan chưa dựng được: router không biết Routine
#: nào tồn tại, vì danh sách ấy là trạng thái và ADR-006/010 cấm nó đọc trạng thái.
Disposition = Literal[
    "control", "offer", "not_control", "clarify", "denied", "chitchat", "routine"
]
#: Phải khớp `src/models/observability.py:ROUTE_SOURCES` — tầng trace lọc theo bản đó
#: (`trace_collector.py:305`), nên một giá trị chỉ có ở đây sẽ bị **vứt im lặng** và
#: lượt ấy mất `route_source` trong `/traces`. `"rag"` từng nằm đây, không ai đặt,
#: và nếu ai đó đặt thì đúng chuyện trên xảy ra. Gỡ 16/08 để hai bản không lệch nữa.
RouteSource = Literal["deterministic", "slm", "fallback"]
ToolStatus = Literal["completed", "failed", "rejected", "skipped"]

#: Bộ nhãn intent đóng — cũng là ground truth cho AC "intent accuracy > 85%".
Intent = Literal[
    "hvac_power",
    "hvac_temperature",
    "hvac_fan_level",
    "media_playback",
    "media_volume",
    "window_position",
    "seat_heating",
    "seat_position",
    "door_state",
    "trunk_state",
    "headlight_mode",
    "interior_light",
    "navigation_start",
    "navigation_cancel",
    #: Tìm địa điểm quanh xe. Tách khỏi `navigation_start` vì nó **chỉ đọc** (S0):
    #: nhánh số nhiều đọc danh sách rồi hỏi lại, không đặt dẫn đường.
    "poi_search",
    "vehicle_state_query",
    #: Mở app giải trí trên IVI. Không phải lệnh xe — không domain, không actuator —
    #: nhưng vẫn là intent điều khiển: nếu để nó rơi về `manual_query` theo ADR-011
    #: thì "mở YouTube" sẽ đi tra 482 chunk sổ tay rồi trả lời một thứ không ai hỏi.
    #: Xem ADR-023.
    "open_app",
    #: Hỏi áp suất lốp. Tách khỏi `manual_query` vì câu trả lời đúng **không nằm trong
    #: sổ tay**: sổ tay chỉ sang cái nhãn ở khung cửa, còn con số thật nằm ở bảng curate
    #: `src/safety/ap_suat_lop.py` và phụ thuộc `trim` × `battery` của chiếc xe này.
    #: Để nó rơi vào `manual_query` thì tài xế nghe một breadcrumb — đúng lỗi 17/08.
    "tire_pressure_query",
    "manual_query",
    #: Tài xế trả lời lời mời "nghe tiếp nguyên văn" (S3). Tách khỏi `manual_query` vì
    #: nó **không** đi tra sổ tay: đoạn nguồn đã có sẵn từ lượt trước, và truy hồi lại
    #: bằng chính chữ "đọc tiếp" sẽ ra một đoạn khác hẳn — đúng lỗi đang sửa.
    "manual_continue",
    #: Tài xế **từ chối** lời mời "nghe tiếp nguyên văn". Tách khỏi `manual_continue` vì
    #: hai lối ra khác hẳn nhau, và tách khỏi `none` vì lượt này *có* nghĩa: nó đóng lại
    #: một câu hỏi mà xe vừa đặt ra. Gộp vào `none` thì nó rơi xuống tra sổ tay và tài
    #: xế nói "thôi" lại được đọc cho nghe một đoạn khác.
    "manual_stop_reading",
    #: Tài xế **từ chối** một lời đề nghị (`offer`) của lượt trước — *"Bật điều hòa
    #: được không"* → *"Thôi khỏi"*. Tách khỏi `none` vì cùng một lẽ với
    #: `manual_stop_reading` ngay trên: lượt này *có* nghĩa, nó đóng lại một câu hỏi xe
    #: vừa đặt ra. Gộp vào `none` thì nó rơi xuống tra sổ tay và tài xế từ chối một đề
    #: nghị lại được đọc cho nghe một đoạn sổ tay về chữ "thôi".
    "offer_declined",
    #: Mảnh trả lời không **thuần** là câu trả lời cho slot đang thiếu — `"hai giờ nhé"`
    #: sau câu hỏi *"quạt gió mức mấy?"* (#363). Tách khỏi `none` vì lối ra khác hẳn: xe
    #: phải **hỏi lại đúng câu cũ** và đóng mic, chứ không đi tra sổ tay chữ
    #: `"hai giờ nhé"`. Và tách khỏi `manual_query` vì lượt này KHÔNG được tra cứu gì.
    "manh_khong_khop_mau",
    #: Tài xế **đuổi trợ lý đi** — *"thôi"*, *"không cần"*, *"khỏi"* khi **không có gì
    #: đang chờ** (#363, spec §3.3). Tách khỏi `none` vì lượt này *có* nghĩa: nó đóng cửa
    #: sổ nghe tiếp. Gộp vào `none` thì nó rơi xuống tra sổ tay, và tài xế đuổi trợ lý lại
    #: được đọc cho nghe một đoạn sổ tay về chữ "thôi".
    "giai_tan",
    #: Ba ý định Routine (#274, #299). Tách ba chứ không gộp một, vì lối ra khác hẳn
    #: nhau: `preview` **không chạm executor**, `run` gọi `bat_dau`, `cancel` gọi `huy`.
    #: Gộp lại thì node phải đọc lại chuỗi để biết làm gì — đọc hai lần cùng một thứ.
    "routine_run",
    "routine_preview",
    "routine_cancel",
    #: Tài xế đáp lời một preview Routine của lượt trước (review PR #401). Tách khỏi ba
    #: ý định trên vì lối ra khác: không phân giải tên gì cả, chỉ đọc lại `routine_id`
    #: đã treo — và tách `confirm`/`decline` vì `confirm` gọi `bat_dau`, `decline` thì
    #: không chạm executor, cùng lý do ba ý định Routine kia bị tách nhau.
    "routine_confirm",
    "routine_decline",
    "none",
]

ValidationSubcode = Literal["tool_not_allowed", "args_invalid", "range_invalid"]

#: Hai disposition được phép mang `candidate_plan`. `control` để thực thi, `offer`
#: để nêu ra cho người dùng xem trước khi họ quyết.
_PLAN_BEARING_DISPOSITIONS = frozenset({"control", "offer"})


class ValidationDenied(Exception):  # noqa: N818 - tên khớp outcome code `validation_denied` trong agent_spec.md
    """Lệnh hỏng về schema — xảy ra **trước** phân loại S0–S3, không phải S3."""

    def __init__(self, subcode: ValidationSubcode, message: str) -> None:
        super().__init__(message)
        self.subcode: ValidationSubcode = subcode
        self.message = message


class CandidateStep(BaseModel):
    """Một step do router hoặc SLM đề xuất. Không mang thông tin an toàn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    ordinal: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


class CandidateActionPlan(BaseModel):
    """Đúng hai trường theo `agent_spec.md`: `schema_version` và `steps`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCHEMA_VERSION
    steps: tuple[CandidateStep, ...]


class PlanStep(CandidateStep):
    """Step đã được policy gán safety."""

    safety_level: SafetyLevel


class ActionPlan(BaseModel):
    """Plan canonical, bất biến, chỉ `policy.materialize_action_plan()` được tạo."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCHEMA_VERSION
    plan_id: str
    session_id: str
    vehicle_id: str
    vehicle_state_version: int
    steps: tuple[PlanStep, ...]
    requires_approval: bool

    @model_validator(mode="after")
    def _s2_implies_approval(self) -> ActionPlan:
        if any(step.safety_level == "S2" for step in self.steps) and not self.requires_approval:
            raise ValueError("plan có step S2 nhưng requires_approval=False")
        return self


class RouteDecision(BaseModel):
    """Kết quả định tuyến. `disposition` và `candidate_plan` loại trừ lẫn nhau."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Disposition
    intent: Intent
    reason: str
    route_source: RouteSource = "deterministic"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    candidate_plan: CandidateActionPlan | None = None
    #: Tên Routine **chưa phân giải** — đúng chữ tài xế nói, rỗng ở mọi disposition
    #: khác. Nằm ở đây chứ không phải một thuộc tính trên router: router là một thể
    #: dùng chung cho mọi lượt đồng thời, nên ghi kết quả một lượt lên `self` là dựng
    #: sẵn một cuộc đua. Kết quả của một lượt phải đi cùng quyết định của lượt ấy.
    routine_ten_tho: str = ""
    latency_ms: float = 0.0

    @model_validator(mode="after")
    def _exclusive_candidate(self) -> RouteDecision:
        # `offer` cũng mang plan: lời đề nghị phải nêu chính xác việc sẽ làm, nếu
        # không thì người dùng đang đồng ý với một thứ mơ hồ.
        if self.disposition in _PLAN_BEARING_DISPOSITIONS and self.candidate_plan is None:
            raise ValueError(f"disposition='{self.disposition}' requires candidate_plan")
        if self.disposition not in _PLAN_BEARING_DISPOSITIONS and self.candidate_plan is not None:
            raise ValueError(f"disposition='{self.disposition}' forbids candidate_plan")
        return self


class ToolResult(BaseModel):
    """Kết quả terminal của một step. Composer chỉ được đọc từ đây."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: str
    step_id: str
    tool: str
    args: dict[str, Any]
    status: ToolStatus
    before: dict[str, Any]
    after: dict[str, Any]
    #: Version xe quan sát được khi bước này chạy xong. `None` **chỉ** khi không quan
    #: sát được gì (docs/api_spec.md:565) — không phải khi `after` rỗng. Nhánh
    #: `_local_failure` của executor trả `after={}` dù vẫn quan sát được version, nên
    #: moi từ `after` cho ra null sai sự thật. Field tường minh cắt hẳn phụ thuộc vào
    #: hình dạng của `after`.
    observed_state_version: int | None = None
    error_code: str | None = None
    latency_ms: float = 0.0


def as_action_plan(value: ActionPlan | dict[str, Any]) -> ActionPlan:
    """Ép giá trị lấy từ state về `ActionPlan`, dù nó là model hay `dict`.

    Cần thiết vì state đi qua checkpoint của LangGraph. Ở chế độ msgpack chặt —
    thứ LangGraph cảnh báo sẽ thành mặc định — kiểu Pydantic bị chặn khôi phục và
    quay về là `dict`. Không ép thì đường resume của HITL vỡ bằng
    `AttributeError: 'dict' object has no attribute 'model_dump'`, tức vỡ sâu bên
    trong chứ không phải lỗi rõ ràng ở biên.
    """
    return value if isinstance(value, ActionPlan) else ActionPlan.model_validate(value)


def as_candidate_plan(value: CandidateActionPlan | dict[str, Any]) -> CandidateActionPlan:
    """Như `as_action_plan`, cho candidate."""
    return value if isinstance(value, CandidateActionPlan) else CandidateActionPlan.model_validate(value)

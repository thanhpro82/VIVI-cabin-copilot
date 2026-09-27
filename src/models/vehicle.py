"""Model cho vehicle state và 5 message MQTT.

Nguồn sự thật là JSON Schema ở `schemas/mqtt/`; file này phải khớp chúng.
Chạy `python scripts/validate_mqtt_schemas.py .` sau khi sửa.

Hợp đồng chi tiết: docs/mqtt_spec.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer, model_validator

SCHEMA_VERSION = "1.0"

Domain = Literal[
    "motion", "hvac", "windows", "doors", "media", "navigation", "seat", "lights", "trunk"
]

DOMAINS: tuple[Domain, ...] = (
    "motion",
    "hvac",
    "windows",
    "doors",
    "media",
    "navigation",
    "seat",
    "lights",
    "trunk",
)

#: Domain không nhận lệnh — chỉ xuất hiện ở state, phục vụ phân loại S2/S3.
READ_ONLY_DOMAINS: frozenset[str] = frozenset({"motion"})

WindowKey = Literal["front_left", "front_right", "rear_left", "rear_right"]
FrontSeatKey = Literal["front_left", "front_right"]

ErrorCode = Literal[
    "stale_state",
    "unsafe_vehicle_state",
    "invalid_arguments",
    "tool_not_allowed",
    "internal_error",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_z(value: datetime) -> str:
    """ISO 8601 UTC kết thúc bằng Z, khớp mẫu trong docs/mqtt_spec.md."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


Timestamp = Annotated[datetime, PlainSerializer(_iso_z, return_type=str)]


class _Strict(BaseModel):
    """Cấm field lạ, khớp `additionalProperties: false` của JSON Schema.

    `validate_assignment` để simulator gán giá trị ngoài dải là nổ ngay, thay
    vì âm thầm publish state không hợp lệ khi dải ở registry lệch dải ở state.
    """

    model_config = {"extra": "forbid", "validate_assignment": True}


# --------------------------------------------------------------------------
# Domain state
# --------------------------------------------------------------------------


class MotionState(_Strict):
    speed_kph: float = Field(ge=0)
    gear: Literal["P", "R", "N", "D"]
    ignition: Literal["OFF", "ACC", "ON"]


class HvacState(_Strict):
    power: bool
    # Dải khớp set_hvac_temperature trong docs/agent_spec.md. Do nhóm tự quy
    # định, không dẫn nguồn từ sổ tay VF9 — sổ tay không công bố min/max.
    temperature_c: float = Field(ge=16, le=30)
    # Dải 0..3 do nhóm tự quy định, **không** dẫn nguồn từ sổ tay VF9 — sổ tay
    # không công bố thang quạt tối đa (chỉ chứng minh được mức 1 tồn tại, qua Nap
    # Mode). Cùng tiền lệ với dải 16..30 °C ngay trên.
    #
    # Trước 2026-08-12 trường này read-only và cố ý **không có trần**, vì registry
    # chưa có tool nào đổi được (mqtt_spec.md "Quyết định P0 số 2"). Issue #65 lật
    # quyết định đó: đã có `set_hvac_fan_level` thì phải có trần, nếu không
    # `validate_assignment` không chặn được giá trị vô nghĩa.
    fan_level: int = Field(ge=0, le=3)


class WindowsState(_Strict):
    """Phần trăm mở: 0 đóng hoàn toàn, 100 mở hoàn toàn."""

    front_left: int = Field(ge=0, le=100)
    front_right: int = Field(ge=0, le=100)
    rear_left: int = Field(ge=0, le=100)
    rear_right: int = Field(ge=0, le=100)


class DoorsState(_Strict):
    front_left: Literal["open", "closed"]
    front_right: Literal["open", "closed"]
    rear_left: Literal["open", "closed"]
    rear_right: Literal["open", "closed"]


class MediaState(_Strict):
    status: Literal["playing", "paused"]
    volume: int = Field(ge=0, le=100)
    track: str | None = None


class NavigationState(_Strict):
    status: Literal["idle", "active"]
    destination_id: str | None = None


class SingleSeatState(_Strict):
    heating: int = Field(ge=0, le=3)
    fore_aft: int = Field(ge=0, le=100)
    recline: int = Field(ge=0, le=100)
    height: int = Field(ge=0, le=100)


class SeatState(_Strict):
    """Bổ sung so với docs/data_model.md để set_seat_* có chỗ ghi kết quả.

    Xem Open question 1 trong docs/mqtt_spec.md.
    """

    front_left: SingleSeatState
    front_right: SingleSeatState


HeadlightMode = Literal["auto", "low_beam", "high_beam"]


class LightsState(_Strict):
    """Đèn ngoại thất + đèn trần. Xem ADR-020 cho toàn bộ cơ sở chuẩn ngành.

    `headlight` là **enum chế độ, không phải boolean bật/tắt** — theo High Mobility
    AutoAPI (`front_exterior_light` là enum 5 trạng thái) và Android Automotive
    (`VehicleLightSwitch`: OFF/ON/DAYTIME_RUNNING/AUTOMATIC). Sổ tay VF9 cũng chỉ
    nói về *chế độ* đèn, không nói về công tắc nguồn.

    **Cố ý không có `off`.** UNECE R48: xe có đèn chạy ban ngày (DRL) bắt buộc có
    đèn chiếu gần tự động theo ánh sáng môi trường và không được phép có chế độ tắt
    thủ công. Đây không phải thiếu sót — bỏ `off` là thứ làm cho phân loại an toàn
    của đèn trở nên đơn giản: không còn thao tác nguy hiểm nào thì cả hai tool đều
    là S1, y như Android xếp `HEADLIGHTS_SWITCH` (không có interlock theo tốc độ).

    **Cố ý không có đèn sương mù.** Sổ tay VF9 ghi "(nếu có trang bị)" — đúng loại
    điều kiện biến thể mà ADR-015 đo được là nguồn sai lệch. Không khai một tính
    năng phụ thuộc trim.
    """

    headlight: HeadlightMode
    interior: bool


class TrunkState(_Strict):
    """Cốp sau. Chỉ có `position`, **không có `locked`**.

    Cùng deferral và cùng lý do với `DoorsState` (`mqtt_spec.md` "Quyết định P0 số
    4"): AutoAPI `trunk.yml` tách `lock` và `position` thành hai property độc lập,
    nhưng registry P0 không có tool khóa/mở khóa nên `locked` sẽ là hằng số không
    ai ghi và không ai đọc. P1 thêm `locked` cho **cả** cửa lẫn cốp trong một lần.
    """

    position: Literal["open", "closed"]


class VehicleState(_Strict):
    """Thân của `data.vehicle_state` trong GET /api/v1/vehicle/state.

    Phải bằng đúng VehicleStateSnapshot trừ `schema_version` — backend chỉ
    forward cache, không map lại tên field.
    """

    vehicle_id: str = Field(min_length=1)
    state_version: int = Field(ge=0)
    observed_at: Timestamp
    motion: MotionState
    hvac: HvacState
    windows: WindowsState
    doors: DoorsState
    media: MediaState
    navigation: NavigationState
    seat: SeatState
    lights: LightsState
    trunk: TrunkState

    def domain(self, name: Domain) -> BaseModel:
        return getattr(self, name)


class VehicleStateSnapshot(VehicleState):
    """Payload của topic `v1/vehicles/{id}/state/snapshot`, retain = true."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION

    @classmethod
    def of(cls, state: VehicleState) -> VehicleStateSnapshot:
        return cls(schema_version=SCHEMA_VERSION, **state.model_dump())

    def to_state(self) -> VehicleState:
        payload = self.model_dump()
        payload.pop("schema_version")
        return VehicleState.model_validate(payload)


# --------------------------------------------------------------------------
# MQTT messages
# --------------------------------------------------------------------------


class DomainStateMessage(_Strict):
    """Payload của `v1/vehicles/{id}/state/{domain}`, retain = true."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    vehicle_id: str = Field(min_length=1)
    state_version: int = Field(ge=0)
    observed_at: Timestamp
    domain: Domain
    # Tùy chọn, mặc định "available". P0 luôn phát "available"; giữ chỗ để P1
    # diễn đạt tín hiệu không khả dụng mà không phải đổi schema.
    status: Literal["available", "unavailable"] | None = None
    state: dict[str, Any]


class VehicleCommand(_Strict):
    """Payload của `v1/vehicles/{id}/commands/{domain}`, retain = false.

    Retain phải là false: retain = true sẽ khiến simulator thực thi lại lệnh
    cuối mỗi lần reconnect.
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    command_id: str = Field(min_length=1)
    idempotency_key: str = Field(pattern=r"^[^:]+:[^:]+$")
    plan_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    vehicle_id: str = Field(min_length=1)
    approval_id: str | None = None
    execution_group_id: str | None = None
    expected_state_version: int = Field(ge=0)
    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    issued_at: Timestamp

    @model_validator(mode="after")
    def idempotency_key_matches_ids(self) -> VehicleCommand:
        expected = f"{self.plan_id}:{self.step_id}"
        if self.idempotency_key != expected:
            raise ValueError(f"idempotency_key phải là {expected!r}")
        return self


class CommandEvent(_Strict):
    """Payload của `v1/vehicles/{id}/events/command`, retain = false.

    Cố ý không có `attempt_count`: simulator không biết executor đã thử lại
    mấy lần. Executor ghép field đó vào khi persist ToolResult.
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    event_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    idempotency_key: str = Field(pattern=r"^[^:]+:[^:]+$")
    plan_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    vehicle_id: str = Field(min_length=1)
    approval_id: str | None = None
    execution_group_id: str | None = None
    # accepted = đã đặt giá trị đích; completed = quan sát thấy đã đạt đích.
    # Không gộp hai khái niệm này, xem docs/mqtt_spec.md.
    phase: Literal["accepted", "rejected", "completed"]
    status: Literal["completed", "rejected", "failed"]
    expected_state_version: int = Field(ge=0)
    observed_state_version: int = Field(ge=0)
    before: dict[str, Any]
    after: dict[str, Any]
    error_code: ErrorCode | None = None
    latency_ms: float = Field(ge=0)
    emitted_at: Timestamp

    @model_validator(mode="after")
    def error_code_matches_status(self) -> CommandEvent:
        if self.status == "completed" and self.error_code is not None:
            raise ValueError("status=completed thì error_code phải là None")
        if self.status != "completed" and self.error_code is None:
            raise ValueError(f"status={self.status} thì error_code là bắt buộc")
        return self


class Health(_Strict):
    """Payload của `v1/vehicles/{id}/health`, retain = true.

    Dùng cho cả Birth message lẫn Last Will.
    """

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    vehicle_id: str = Field(min_length=1)
    online: bool
    state_version: int | None = Field(default=None, ge=0)
    simulator_version: str | None = None
    heartbeat_at: Timestamp | None = None
    reason: Literal["lwt", "shutdown"] | None = None

    @model_validator(mode="after")
    def reason_matches_online(self) -> Health:
        if self.online:
            if self.reason is not None:
                raise ValueError("online=true thì cấm field reason")
            missing = [
                name
                for name in ("state_version", "simulator_version", "heartbeat_at")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"online=true thiếu field bắt buộc: {missing}")
        elif self.reason is None:
            raise ValueError("online=false thì reason là bắt buộc")
        return self


# --------------------------------------------------------------------------
# Executor-side result
# --------------------------------------------------------------------------


class ToolResult(_Strict):
    """Kết quả executor persist xuống SQLite, theo docs/data_model.md.

    Khác CommandEvent ở chỗ có `attempt_count` — field này do executor sở hữu
    và không bao giờ lên MQTT.
    """

    command_id: str
    plan_id: str
    step_id: str
    approval_id: str | None = None
    execution_group_id: str | None = None
    expected_state_version: int = Field(ge=0)
    observed_state_version: int = Field(ge=0)
    attempt_count: int = Field(ge=1)
    status: Literal["completed", "rejected", "failed"]
    before: dict[str, Any]
    after: dict[str, Any]
    error_code: str | None = None
    latency_ms: float = Field(ge=0)

    @classmethod
    def from_event(cls, event: CommandEvent, attempt_count: int) -> ToolResult:
        return cls(
            command_id=event.command_id,
            plan_id=event.plan_id,
            step_id=event.step_id,
            approval_id=event.approval_id,
            execution_group_id=event.execution_group_id,
            expected_state_version=event.expected_state_version,
            observed_state_version=event.observed_state_version,
            attempt_count=attempt_count,
            status=event.status,
            before=event.before,
            after=event.after,
            error_code=event.error_code,
            latency_ms=event.latency_ms,
        )

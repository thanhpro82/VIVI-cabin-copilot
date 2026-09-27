"""Tool registry — server-owned allowlist ánh xạ tool sang domain/topic.

ADR-004: "Tool registry, không phải LLM, ánh xạ tool sang topic."

Đây là nơi duy nhất quyết định một tool được publish lên topic nào và args
hợp lệ ra sao. Dải giá trị chép từ docs/agent_spec.md — file đó là canonical,
bảng dưới đây phải khớp. `scripts/crosscheck_mqtt_spec.py` kiểm điều đó.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from src import mqtt_topics
from src.fixtures import ten_track_theo_id
from src.models.vehicle import Domain, FrontSeatKey, HeadlightMode, WindowKey

SafetyLevel = Literal["S0", "S1", "S2", "S3"]


class ToolNotAllowedError(Exception):
    """Tool không có trong registry. Không bao giờ retry."""


class InvalidArgumentsError(Exception):
    """args sai schema hoặc ngoài dải. Không bao giờ retry."""


class _Args(BaseModel):
    model_config = {"extra": "forbid"}


class SearchNearbyPoiArgs(_Args):
    #: Tập đóng, giữ khớp với `POI_CATEGORIES` của fixture (test khoá hai bên bằng
    #: nhau). Schema đóng chặn model bịa ra loại địa điểm không tồn tại — cùng kỷ
    #: luật với mọi tool khác.
    category: Literal["cafe", "charging", "entertainment", "mall", "restaurant"]


class KhongCoArgs(_Args):
    """Tool không nhận tham số nào.

    Có class thật chứ không để `args_model=None`: cái `None` ấy là một ngoại lệ mà mọi
    chỗ đọc registry phải nhớ xử lý riêng, và nó chính là lý do `TOOL_ARGS` bên
    `src/agents/tools` từng phải tự khai một `GetVehicleStateArgs` của riêng mình —
    tức mầm của đúng cái lệch mà #325 đi sửa.
    """


class SetHvacTemperatureArgs(_Args):
    temperature_c: float = Field(ge=16, le=30)


class SetHvacPowerArgs(_Args):
    enabled: bool


class SetHvacFanLevelArgs(_Args):
    # Dải 0..3 tự quy định, khớp `HvacState.fan_level`. Xem ADR-019.
    level: int = Field(ge=0, le=3)


class SetSeatHeatingArgs(_Args):
    seat: FrontSeatKey
    level: int = Field(ge=0, le=3)


class SetSeatPositionArgs(_Args):
    seat: FrontSeatKey
    axis: Literal["fore_aft", "recline", "height"]
    value: int = Field(ge=0, le=100)


class SetWindowPositionArgs(_Args):
    window: WindowKey
    percent: int = Field(ge=0, le=100)


class SetDoorStateArgs(_Args):
    door: WindowKey
    state: Literal["open", "closed"]


class SetTrunkStateArgs(_Args):
    state: Literal["open", "closed"]


class SetHeadlightModeArgs(_Args):
    # Không có "off" — UNECE R48. Xem ADR-020.
    mode: HeadlightMode


class SetInteriorLightArgs(_Args):
    enabled: bool


class OpenAppArgs(_Args):
    """Mở một app giải trí trên IVI. ADR-023.

    Enum **đóng**, không phải `str`, và **không** có tham số URL: "mở app tuỳ ý" và
    "URL tuỳ ý" nằm ngoài phạm vi P0. Enum đóng là cách *cấu trúc dữ liệu* nói ra điều
    đó, thay vì trông cậy vào ý chí của người viết code sau này.

    `vehicle` / `music` / `map` cố ý **không** nằm trong enum: chúng đã có lệnh xe thật
    mang `domain`, nên thêm vào đây là mở hai đường vào cho cùng một kết quả.
    """

    app: Literal["youtube", "tiktok", "spotify"]


class MediaControlArgs(_Args):
    #: `play_track` là action thứ sáu chứ **không** phải một tool mới. Cùng domain
    #: `media`, cùng S1, cùng đường publish — một `ToolSpec` thứ hai chỉ để đổi bài
    #: sẽ phải thêm một giá trị vào enum `tool` của `vehicle_command.schema.json`,
    #: tức là đổi hợp đồng MQTT mà L2/L3 đang khoá, để đổi lấy đúng một field.
    action: Literal["play", "pause", "next", "previous", "set_volume", "play_track"]
    volume: int | None = Field(default=None, ge=0, le=100)
    track_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def volume_required_iff_set_volume(self) -> MediaControlArgs:
        if self.action == "set_volume" and self.volume is None:
            raise ValueError("action=set_volume bắt buộc có volume")
        if self.action != "set_volume" and self.volume is not None:
            raise ValueError(f"action={self.action} cấm field volume")
        return self

    @model_validator(mode="after")
    def track_required_iff_play_track(self) -> MediaControlArgs:
        """`track_id` phải có, và phải là một bài **có thật** trong playlist.

        Kiểm sự tồn tại ở đây chứ không chỉ ở router: registry là allowlist do server
        sở hữu (ADR-004), nên một `track_id` bịa — dù đến từ SLM hay từ client gọi
        thẳng `/turns/text` — phải dừng ở `validation_denied`, không được xuống tới
        simulator rồi im lặng phát một bài khác. Đó đúng là lớp lỗi KI-001 mà thay
        đổi này sinh ra để đóng.
        """
        if self.action == "play_track" and self.track_id is None:
            raise ValueError("action=play_track bắt buộc có track_id")
        if self.action != "play_track" and self.track_id is not None:
            raise ValueError(f"action={self.action} cấm field track_id")
        if self.track_id is not None and ten_track_theo_id(self.track_id) is None:
            raise ValueError(f"track_id {self.track_id!r} không có trong playlist")
        return self


class SetNavigationArgs(_Args):
    """`destination_ref` **cố ý không tồn tại** — xem issue #325.

    Bản trước của file này khai `destination_ref: DestinationRef | None`, tham chiếu tới
    một kết quả tìm POI ở bước trước. Nhưng hệ `PlanningResolution` giải tham chiếu ấy
    chưa bao giờ được dựng, nên một plan mang nó **qua được** validate rồi mới chết ở
    simulator (`vehicle_sim/state.py`: *"destination_ref phải được resolve trước khi tới
    simulator"*). Chết muộn, sau khi đã qua safety và HITL.

    Bản plan-layer (`src/agents/tools/navigation.py`) thì từ chối ngay ở `validate_args`,
    và có test khoá điều đó từ lâu. Hai bên lệch nhau đúng ở chỗ ấy, và bên **chặt hơn**
    mới là bên đúng — nên hợp nhất theo bên ấy, không phải theo bên rộng hơn.

    Không có producer nào bị mất: grep toàn cây, không chỗ nào sinh `destination_ref`.
    Router POI của SP-5 tự phân giải rồi phát thẳng `destination_id` cụ thể.
    """

    operation: Literal["start", "cancel"]
    destination_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def target_matches_operation(self) -> SetNavigationArgs:
        if self.operation == "start" and not (self.destination_id or "").strip():
            raise ValueError("operation=start bắt buộc có destination_id")
        if self.operation == "cancel" and self.destination_id is not None:
            raise ValueError("operation=cancel cấm destination_id")
        return self


@dataclass(frozen=True)
class ToolSpec:
    name: str
    #: None nghĩa là tool S0 — đọc tại chỗ, không bao giờ publish MQTT.
    domain: Domain | None
    safety: SafetyLevel
    args_model: type[_Args]
    #: True khi safety hạ xuống S3 lúc xe đang chuyển động.
    requires_stationary: bool = False


_SPECS: tuple[ToolSpec, ...] = (
    # S0 — không đi qua broker
    ToolSpec("get_vehicle_state", None, "S0", KhongCoArgs),
    ToolSpec("query_manual", None, "S0", KhongCoArgs),
    ToolSpec("search_nearby_poi", None, "S0", SearchNearbyPoiArgs),
    # Tool cục bộ của IVI: `domain=None` nên không bao giờ publish MQTT, nhưng
    # `requires_stationary=True` vì mở video khi xe đang chạy là phân tâm người lái.
    # S1 chứ không S0 — S0 là *chỉ đọc*, còn tool này làm một việc. Xem ADR-023.
    ToolSpec("open_app", None, "S1", OpenAppArgs, requires_stationary=True),
    # S1
    ToolSpec("set_hvac_temperature", "hvac", "S1", SetHvacTemperatureArgs),
    ToolSpec("set_hvac_power", "hvac", "S1", SetHvacPowerArgs),
    ToolSpec("set_hvac_fan_level", "hvac", "S1", SetHvacFanLevelArgs),
    ToolSpec("set_seat_heating", "seat", "S1", SetSeatHeatingArgs),
    ToolSpec("media_control", "media", "S1", MediaControlArgs),
    ToolSpec("set_navigation", "navigation", "S1", SetNavigationArgs),
    # Đèn là S1 ở mọi trạng thái xe: bỏ `off` khỏi enum nghĩa là không còn thao tác
    # nguy hiểm nào để phải chặn. Android cũng xếp `HEADLIGHTS_SWITCH` không có
    # interlock theo tốc độ. Xem ADR-020.
    ToolSpec("set_headlight_mode", "lights", "S1", SetHeadlightModeArgs),
    ToolSpec("set_interior_light", "lights", "S1", SetInteriorLightArgs),
    # S2
    ToolSpec("set_window_position", "windows", "S2", SetWindowPositionArgs),
    ToolSpec("set_door_state", "doors", "S2", SetDoorStateArgs, requires_stationary=True),
    ToolSpec("set_seat_position", "seat", "S2", SetSeatPositionArgs, requires_stationary=True),
    ToolSpec("set_trunk_state", "trunk", "S2", SetTrunkStateArgs, requires_stationary=True),
)

TOOL_REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}

#: Tool thật sự publish lên MQTT — khớp enum `tool` của vehicle_command.schema.json.
ACTUATOR_TOOLS: frozenset[str] = frozenset(
    name for name, spec in TOOL_REGISTRY.items() if spec.domain is not None
)


def get_spec(tool: str) -> ToolSpec:
    spec = TOOL_REGISTRY.get(tool)
    if spec is None:
        raise ToolNotAllowedError(f"tool {tool!r} không có trong registry")
    return spec


def topic_for_tool(tool: str, vehicle_id: str) -> str:
    """Topic lệnh của tool. Raise ToolNotAllowedError nếu tool lạ hoặc là S0."""
    spec = get_spec(tool)
    if spec.domain is None:
        raise ToolNotAllowedError(f"tool {tool!r} là S0, không publish MQTT")
    return mqtt_topics.commands(vehicle_id, spec.domain)


def validate_args(tool: str, args: dict[str, Any]) -> _Args:
    """Validate args theo schema đóng của tool.

    Raise ToolNotAllowedError nếu tool lạ, InvalidArgumentsError nếu args sai.
    """
    spec = get_spec(tool)
    try:
        return spec.args_model.model_validate(args)
    except ValidationError as exc:
        raise InvalidArgumentsError(_summarize(exc)) from exc


def _summarize(exc: ValidationError) -> str:
    """Gộp lỗi pydantic thành một dòng ngắn để nhét vào error payload."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(item) for item in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def _mo_ta_kieu(schema: dict[str, Any]) -> str:
    """Một field JSON-Schema → một chuỗi ngắn cho model đọc.

    Cố ý **không** đưa nguyên `model_json_schema()` vào prompt: nó dài gấp nhiều lần,
    và mỗi token thừa trong prompt hệ thống là token bị trừ khỏi ngân sách ngữ cảnh của
    câu người dùng. Thứ model thật sự thiếu chỉ là tên field + miền giá trị.
    """
    # `X | None` ra `anyOf: [<thật>, {"type": "null"}]` — lấy nhánh thật.
    if "anyOf" in schema:
        nhanh = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if nhanh:
            return _mo_ta_kieu(nhanh[0])
    if "enum" in schema:
        return "|".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
    kieu = schema.get("type")
    if kieu == "boolean":
        return "true|false"
    if kieu in {"integer", "number"}:
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if lo is not None and hi is not None:
            return f"{lo}..{hi}"
        return "số"
    if kieu == "string":
        return "chuỗi"
    # Còn lại là object lồng (`destination_ref`) — nêu tên, không bung ra.
    return "object"


def mo_ta_args_cua_model(model: type[BaseModel]) -> str:
    """Hình dạng args của một model Pydantic, dạng ngắn cho prompt.

    Nhận **model** chứ không nhận tên tool, vì repo hiện có HAI bảng args song song
    (`TOOL_REGISTRY` ở đây, `src.agents.tools.TOOL_ARGS` cho đường planner) và bên gọi
    phải tự nói rõ nó đang mô tả bảng nào. Xem `tests/test_agents/test_hai_bang_args.py`.
    """
    schema = model.model_json_schema()
    bat_buoc = set(schema.get("required", []))
    phan = []
    for ten, con in schema.get("properties", {}).items():
        mo_ta = _mo_ta_kieu(con)
        phan.append(f'"{ten}": {mo_ta}' if ten in bat_buoc else f'"{ten}"?: {mo_ta}')
    return "{" + ", ".join(phan) + "}"

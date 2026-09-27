# Agent LangGraph + 5 bộ tool điều khiển xe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng StateGraph LangGraph định tuyến lệnh tiếng Việt bằng luật, sinh `ActionPlan` canonical qua đúng một điểm gán safety, chạy nó trên simulator xe in-memory, và đo intent accuracy bằng artifact bất biến.

**Architecture:** Deterministic-first theo `docs/agent_spec.md`. Router luật sinh `CandidateActionPlan` (không có `safety_level`); `policy.materialize_action_plan()` là nơi **duy nhất** gán S0–S3 và tạo `ActionPlan`; executor chỉ nhận `ActionPlan`. Qwen2.5-3B q4 là fallback cho câu mơ hồ, inject được, mặc định tắt.

**Tech Stack:** Python 3.11 · Pydantic 2.13 · LangGraph 1.2.9 · FastAPI 0.140 · pytest 8 (`asyncio_mode=auto`) · ruff (py311, line-length 120, select E/F/I/N/W/UP, ignore E501).

**Spec:** [`docs/superpowers/specs/2026-08-08-agent-graph-vehicle-tools-design.md`](../specs/2026-08-08-agent-graph-vehicle-tools-design.md)
**ADR:** [`docs/adr/ADR-010`](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md)

## Global Constraints

- Chạy mọi lệnh từ repo root `C:\Users\hoang\Desktop\DaotaoVingroup\Cohort3\Build\P-192` bằng `.\.venv\Scripts\python.exe`.
- Test: `.\.venv\Scripts\python.exe -m pytest tests/ -q`. `asyncio_mode = "auto"` — **không** thêm `@pytest.mark.asyncio`.
- Lint: `.\.venv\Scripts\python.exe -m ruff check src/ tests/` và `... ruff format src/ tests/` phải sạch trước mỗi commit.
- **Không network, không load model weight, không đọc `models/`** trong bất kỳ test nào.
- Tên tool trong `CandidateActionPlan`/`ActionPlan`/trace **luôn** là tên canonical. Alias Họ A (`control_ac`…) chỉ xuất hiện ở HTTP response.
- **Chỉ** `src/agents/policy.py` được gán `safety_level` và tạo `ActionPlan`.
- Không sửa `src/rag/`, `src/services/voice.py`, `src/models/schemas.py`. `src/api/routes.py` chỉ được **thêm**.
- Không tạo file dưới `eval/results/` bằng tay. Runner mở file bằng mode `"x"` và `mkdir(exist_ok=False)`.
- Commit message theo `docs/GIT_WORKFLOW.md`: `type(scope): mô tả`. Scope dùng `agent`, `api`, `eval`, `docs`.
- Mọi comment/docstring viết tiếng Việt, khớp phong cách `src/agents/nodes/rag_node.py` hiện có.

## Hai điểm bổ sung so với spec (đọc trước khi bắt đầu)

1. **Router có thêm `_match_door`.** Spec liệt kê 5 matcher. Nhưng `set_door_state` nằm trong registry và branch HITL cần một đường đi từ câu tiếng Việt tới một step S3 để test "chặn khi đang chạy". Không có matcher thì `set_door_state` là code chết. Task 6 thêm nó.
2. **`query_manual` không vào registry executable.** Đường manual đi `not_control` → `rag_node`, không qua executor. Thêm `query_manual` như một tool là việc thừa ở sprint này.

## File structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/agents/contracts.py` | Kiểu dữ liệu + 2 invariant validator | 1 |
| `src/agents/tools/hvac.py` `media.py` `window.py` `seat.py` `navigation.py` `door.py` | Pydantic args schema đóng cho từng tool | 2 |
| `src/agents/tools/__init__.py` | `TOOL_ARGS` allowlist · `ALIAS_BY_TOOL` · `GetVehicleStateArgs` | 2 |
| `src/agents/vehicle.py` | `VehicleSimulator` in-memory, idempotent, `state_version` | 3 |
| `src/agents/policy.py` | `classify()` · `materialize_action_plan()` · `plan_digest()` | 4 |
| `src/agents/router.py` | `normalize_vi()` · `DeterministicControlRouter` | 5, 6 |
| `src/agents/nodes/normalize.py` `route.py` `validate.py` `safety.py` `execute.py` `compose.py` | Node graph, mỗi file một node | 7 |
| `src/agents/state.py` | Mở rộng `AgentState` | 7 |
| `src/agents/graph.py` | `build_graph()` | 7 |
| `src/agents/slm.py` | `Planner` protocol · `QwenPlanner` · schema check + 1 repair | 8 |
| `src/agents/eval.py` | Runner đo AC2/AC3, ghi thư mục bất biến | 9 |
| `eval/datasets/agent/v3/{cases.jsonl,README.md}` | Dataset 60 case | 9 |
| `src/api/agent_routes.py` | `POST /api/v1/agent/process` | 10 |

---

### Task 1: Contracts — ranh giới candidate → canonical

**Files:**
- Create: `src/agents/contracts.py`
- Test: `tests/test_agents/test_contracts.py`

**Interfaces:**
- Consumes: (không có — task đầu tiên)
- Produces: `SCHEMA_VERSION: str`, `SafetyLevel`, `Disposition`, `RouteSource`, `Intent` (Literal aliases), `CandidateStep`, `CandidateActionPlan`, `PlanStep`, `ActionPlan`, `RouteDecision`, `ToolResult`, `ValidationDenied(Exception)` với `.subcode` và `.message`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_contracts.py`:

```python
"""Hai invariant của contract, mỗi cái một test — chúng là lý do file này tồn tại."""

import pytest
from pydantic import ValidationError

from src.agents.contracts import (
    ActionPlan,
    CandidateActionPlan,
    CandidateStep,
    PlanStep,
    RouteDecision,
    ValidationDenied,
)


def _candidate() -> CandidateActionPlan:
    return CandidateActionPlan(
        steps=(CandidateStep(step_id="step-1", ordinal=0, tool="set_window_position", args={"window": "front_left", "percent": 30}),)
    )


def test_candidate_step_refuses_safety_level():
    """Model/router không được phép tự gán safety — schema đóng chặn từ gốc."""
    with pytest.raises(ValidationError):
        CandidateStep(step_id="step-1", ordinal=0, tool="set_hvac_power", args={}, safety_level="S1")


def test_action_plan_refuses_s2_without_approval():
    with pytest.raises(ValidationError, match="requires_approval"):
        ActionPlan(
            plan_id="plan-1",
            session_id="ses-1",
            vehicle_id="veh-1",
            vehicle_state_version=1,
            requires_approval=False,
            steps=(PlanStep(step_id="step-1", ordinal=0, tool="set_window_position", args={}, safety_level="S2"),),
        )


def test_action_plan_accepts_s2_with_approval():
    plan = ActionPlan(
        plan_id="plan-1",
        session_id="ses-1",
        vehicle_id="veh-1",
        vehicle_state_version=1,
        requires_approval=True,
        steps=(PlanStep(step_id="step-1", ordinal=0, tool="set_window_position", args={}, safety_level="S2"),),
    )
    assert plan.requires_approval is True


def test_route_decision_control_requires_candidate_plan():
    with pytest.raises(ValidationError, match="requires candidate_plan"):
        RouteDecision(disposition="control", intent="window_position", reason="deterministic_rule")


@pytest.mark.parametrize("disposition", ["not_control", "clarify", "denied"])
def test_route_decision_non_control_forbids_candidate_plan(disposition):
    with pytest.raises(ValidationError, match="forbids candidate_plan"):
        RouteDecision(disposition=disposition, intent="none", reason="x", candidate_plan=_candidate())


def test_validation_denied_carries_subcode():
    error = ValidationDenied("range_invalid", "temperature_c out of range")
    assert error.subcode == "range_invalid"
    assert "temperature_c" in str(error)
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_contracts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.contracts'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `src/agents/contracts.py`:

```python
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
Disposition = Literal["control", "not_control", "clarify", "denied"]
RouteSource = Literal["deterministic", "rag", "slm", "fallback"]
ToolStatus = Literal["completed", "failed", "rejected", "skipped"]

#: Bộ nhãn intent đóng — cũng là ground truth cho AC "intent accuracy > 85%".
Intent = Literal[
    "hvac_power",
    "hvac_temperature",
    "media_playback",
    "media_volume",
    "window_position",
    "seat_heating",
    "seat_position",
    "door_state",
    "navigation_start",
    "navigation_cancel",
    "vehicle_state_query",
    "manual_query",
    "none",
]

ValidationSubcode = Literal["tool_not_allowed", "args_invalid", "range_invalid"]


class ValidationDenied(Exception):
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
    latency_ms: float = 0.0

    @model_validator(mode="after")
    def _exclusive_candidate(self) -> RouteDecision:
        if self.disposition == "control" and self.candidate_plan is None:
            raise ValueError("disposition='control' requires candidate_plan")
        if self.disposition != "control" and self.candidate_plan is not None:
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
    error_code: str | None = None
    latency_ms: float = 0.0
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_contracts.py -q`
Expected: PASS — 8 passed

- [ ] **Step 5: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/contracts.py tests/test_agents/test_contracts.py
.\.venv\Scripts\python.exe -m ruff format src/agents/contracts.py tests/test_agents/test_contracts.py
git add src/agents/contracts.py tests/test_agents/test_contracts.py
git commit -m "feat(agent): contract candidate/canonical voi hai invariant safety"
```

---

### Task 2: Tool registry — schema đóng + bảng alias

**Files:**
- Create: `src/agents/tools/hvac.py`, `media.py`, `window.py`, `seat.py`, `navigation.py`, `door.py`
- Modify: `src/agents/tools/__init__.py` (hiện đang rỗng)
- Test: `tests/test_agents/test_tools.py`

**Interfaces:**
- Consumes: (không có)
- Produces:
  - `TOOL_ARGS: dict[str, type[BaseModel]]` — allowlist, khóa là tên tool canonical
  - `ALIAS_BY_TOOL: dict[str, str]` — canonical → alias Họ A
  - `validate_args(tool: str, args: dict) -> BaseModel` — raise `ValidationDenied`
  - Args model: `SetHvacPowerArgs`, `SetHvacTemperatureArgs`, `MediaControlArgs`, `SetWindowPositionArgs`, `SetSeatHeatingArgs`, `SetSeatPositionArgs`, `SetNavigationArgs`, `SetDoorStateArgs`, `GetVehicleStateArgs`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_tools.py`:

```python
"""Schema tool là hàng rào đầu tiên: sai ở đây là VALIDATION_DENIED, chưa tới S0-S3."""

import pytest

from src.agents.contracts import ValidationDenied
from src.agents.tools import ALIAS_BY_TOOL, TOOL_ARGS, validate_args


def test_registry_covers_exactly_the_allowlisted_tools():
    assert set(TOOL_ARGS) == {
        "get_vehicle_state",
        "set_hvac_power",
        "set_hvac_temperature",
        "media_control",
        "set_window_position",
        "set_seat_heating",
        "set_seat_position",
        "set_navigation",
        "set_door_state",
    }


def test_alias_maps_every_ticket_group_to_canonical_tools():
    assert ALIAS_BY_TOOL["set_hvac_power"] == "control_ac"
    assert ALIAS_BY_TOOL["set_hvac_temperature"] == "control_ac"
    assert ALIAS_BY_TOOL["media_control"] == "control_music"
    assert ALIAS_BY_TOOL["set_window_position"] == "control_window"
    assert ALIAS_BY_TOOL["set_seat_heating"] == "control_seat"
    assert ALIAS_BY_TOOL["set_seat_position"] == "control_seat"
    assert ALIAS_BY_TOOL["set_navigation"] == "navigation"


def test_unknown_tool_is_tool_not_allowed():
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args("set_engine_off", {})
    assert excinfo.value.subcode == "tool_not_allowed"


def test_extra_field_is_args_invalid():
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args("set_hvac_power", {"enabled": True, "turbo": True})
    assert excinfo.value.subcode == "args_invalid"


def test_out_of_range_is_range_invalid():
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args("set_hvac_temperature", {"temperature_c": 45})
    assert excinfo.value.subcode == "range_invalid"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("set_hvac_temperature", {"temperature_c": 22}),
        ("set_hvac_power", {"enabled": False}),
        ("media_control", {"action": "play"}),
        ("media_control", {"action": "set_volume", "volume": 40}),
        ("set_window_position", {"window": "rear_left", "percent": 100}),
        ("set_seat_heating", {"seat": "front_left", "level": 3}),
        ("set_seat_position", {"seat": "front_right", "axis": "recline", "value": 0}),
        ("set_navigation", {"operation": "start", "destination_id": "poi-cafe-01"}),
        ("set_navigation", {"operation": "cancel"}),
        ("set_door_state", {"door": "front_left", "state": "open"}),
        ("get_vehicle_state", {}),
    ],
)
def test_valid_args_pass(tool, args):
    assert validate_args(tool, args) is not None


def test_volume_required_only_for_set_volume():
    with pytest.raises(ValidationDenied):
        validate_args("media_control", {"action": "set_volume"})
    with pytest.raises(ValidationDenied):
        validate_args("media_control", {"action": "play", "volume": 40})


def test_navigation_destination_conditional():
    with pytest.raises(ValidationDenied):
        validate_args("set_navigation", {"operation": "start"})
    with pytest.raises(ValidationDenied):
        validate_args("set_navigation", {"operation": "start", "destination_id": "   "})
    with pytest.raises(ValidationDenied):
        validate_args("set_navigation", {"operation": "cancel", "destination_id": "poi-cafe-01"})


def test_destination_ref_is_rejected_because_poi_is_out_of_scope():
    """POI resolution nằm ngoài scope sprint (ADR-010). Từ chối rõ ràng, không im lặng."""
    with pytest.raises(ValidationDenied) as excinfo:
        validate_args("set_navigation", {"operation": "start", "destination_ref": {"from_step_id": "s0", "selection": "first"}})
    assert excinfo.value.subcode == "args_invalid"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_tools.py -q`
Expected: FAIL — `ImportError: cannot import name 'TOOL_ARGS' from 'src.agents.tools'`

- [ ] **Step 3: Viết args model cho từng domain**

`src/agents/tools/hvac.py`:

```python
"""Args schema cho nhóm điều hòa (alias Họ A: control_ac)."""

from pydantic import BaseModel, ConfigDict, Field


class SetHvacPowerArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class SetHvacTemperatureArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature_c: float = Field(ge=16, le=30)
```

`src/agents/tools/media.py`:

```python
"""Args schema cho nhóm nhạc (alias Họ A: control_music)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaControlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["play", "pause", "next", "previous", "set_volume"]
    volume: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _volume_is_conditional(self) -> MediaControlArgs:
        if self.action == "set_volume" and self.volume is None:
            raise ValueError("volume bắt buộc khi action='set_volume'")
        if self.action != "set_volume" and self.volume is not None:
            raise ValueError("volume bị cấm khi action khác 'set_volume'")
        return self
```

`src/agents/tools/window.py`:

```python
"""Args schema cho nhóm cửa sổ (alias Họ A: control_window). Luôn S2 — xem policy."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WindowId = Literal["front_left", "front_right", "rear_left", "rear_right"]


class SetWindowPositionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: WindowId
    percent: int = Field(ge=0, le=100)
```

`src/agents/tools/seat.py`:

```python
"""Args schema cho nhóm ghế (alias Họ A: control_seat).

Sưởi ghế là S1; dịch chuyển ghế là S2/S3 tùy trạng thái xe — xem policy.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SeatId = Literal["front_left", "front_right"]


class SetSeatHeatingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: SeatId
    level: int = Field(ge=0, le=3)


class SetSeatPositionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: SeatId
    axis: Literal["fore_aft", "recline", "height"]
    value: int = Field(ge=0, le=100)
```

`src/agents/tools/navigation.py`:

```python
"""Args schema cho dẫn đường (alias Họ A: navigation).

`destination_ref` (tham chiếu kết quả tìm POI) **không** được khai báo: hệ
PlanningResolution nằm ngoài scope sprint này (ADR-010 §Scope boundary). Vì
schema đóng, mọi plan chứa nó rơi vào VALIDATION_DENIED thay vì bị bỏ qua.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class SetNavigationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["start", "cancel"]
    destination_id: str | None = None

    @model_validator(mode="after")
    def _destination_is_conditional(self) -> SetNavigationArgs:
        if self.operation == "start" and not (self.destination_id or "").strip():
            raise ValueError("destination_id bắt buộc khi operation='start'")
        if self.operation == "cancel" and self.destination_id is not None:
            raise ValueError("destination_id bị cấm khi operation='cancel'")
        return self
```

`src/agents/tools/door.py`:

```python
"""Args schema cho cửa xe. S2 khi đứng yên, S3 khi đang chạy — xem policy."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

DoorId = Literal["front_left", "front_right", "rear_left", "rear_right"]


class SetDoorStateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    door: DoorId
    state: Literal["open", "closed"]
```

- [ ] **Step 4: Viết registry và alias**

`src/agents/tools/__init__.py`:

```python
"""Registry tool do server sở hữu.

Hai bảng, hai vai trò khác nhau — đừng trộn:

- `TOOL_ARGS` là allowlist canonical. Tên ở đây là thứ duy nhất được xuất hiện
  trong `CandidateActionPlan`, `ActionPlan` và trace.
- `ALIAS_BY_TOOL` chỉ dùng khi dựng HTTP response, để khớp tên nhóm tool trong
  `docs/VIVI_API_Spec.md`. Xem ADR-010.
"""

from pydantic import BaseModel, ConfigDict, ValidationError

from src.agents.contracts import ValidationDenied
from src.agents.tools.door import SetDoorStateArgs
from src.agents.tools.hvac import SetHvacPowerArgs, SetHvacTemperatureArgs
from src.agents.tools.media import MediaControlArgs
from src.agents.tools.navigation import SetNavigationArgs
from src.agents.tools.seat import SetSeatHeatingArgs, SetSeatPositionArgs
from src.agents.tools.window import SetWindowPositionArgs


class GetVehicleStateArgs(BaseModel):
    """Tool đọc trạng thái xe — không nhận tham số nào."""

    model_config = ConfigDict(extra="forbid")


TOOL_ARGS: dict[str, type[BaseModel]] = {
    "get_vehicle_state": GetVehicleStateArgs,
    "set_hvac_power": SetHvacPowerArgs,
    "set_hvac_temperature": SetHvacTemperatureArgs,
    "media_control": MediaControlArgs,
    "set_window_position": SetWindowPositionArgs,
    "set_seat_heating": SetSeatHeatingArgs,
    "set_seat_position": SetSeatPositionArgs,
    "set_navigation": SetNavigationArgs,
    "set_door_state": SetDoorStateArgs,
}

ALIAS_BY_TOOL: dict[str, str] = {
    "set_hvac_power": "control_ac",
    "set_hvac_temperature": "control_ac",
    "media_control": "control_music",
    "set_window_position": "control_window",
    "set_seat_heating": "control_seat",
    "set_seat_position": "control_seat",
    "set_navigation": "navigation",
    "set_door_state": "control_door",
    "get_vehicle_state": "vehicle_state",
}

#: Loại lỗi Pydantic báo hiệu giá trị nằm ngoài khoảng cho phép.
_RANGE_ERROR_TYPES = {
    "greater_than",
    "greater_than_equal",
    "less_than",
    "less_than_equal",
}


def validate_args(tool: str, args: dict) -> BaseModel:
    """Validate args của một tool. Raise `ValidationDenied` kèm subcode chính xác.

    Đây là bước chạy **trước** phân loại S0–S3: tool lạ, sai schema hay ngoài
    khoảng đều không phải S3 (`docs/safety_and_hitl.md` mục Classification rules).
    """
    model = TOOL_ARGS.get(tool)
    if model is None:
        raise ValidationDenied("tool_not_allowed", f"tool không nằm trong allowlist: {tool}")
    try:
        return model.model_validate(args)
    except ValidationError as exc:
        subcode = "range_invalid" if any(e["type"] in _RANGE_ERROR_TYPES for e in exc.errors()) else "args_invalid"
        raise ValidationDenied(subcode, f"args không hợp lệ cho {tool}: {exc.errors()[0]['msg']}") from exc
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_tools.py -q`
Expected: PASS — 19 passed

- [ ] **Step 6: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/tools/ tests/test_agents/test_tools.py
.\.venv\Scripts\python.exe -m ruff format src/agents/tools/ tests/test_agents/test_tools.py
git add src/agents/tools/ tests/test_agents/test_tools.py
git commit -m "feat(agent): registry 9 tool voi schema dong va bang alias Ho A"
```

---

### Task 3: VehicleSimulator

**Files:**
- Create: `src/agents/vehicle.py`
- Test: `tests/test_agents/test_vehicle.py`

**Interfaces:**
- Consumes: `ToolResult` (Task 1), `TOOL_ARGS`/`validate_args` (Task 2)
- Produces: `VehicleSimulator` với `.state: dict`, `.command_count: int`, `.snapshot() -> dict`, `.execute(command_id: str, expected_state_version: int, tool: str, args: dict) -> ToolResult`, và classmethod `VehicleSimulator.initial(speed_kph: float = 0.0, gear: str = "P") -> VehicleSimulator`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_vehicle.py`:

```python
"""Simulator là nguồn sự thật về trạng thái xe, và là hàng rào an toàn thứ hai."""

from src.agents.vehicle import VehicleSimulator


def test_initial_state_is_stationary_and_versioned():
    vehicle = VehicleSimulator.initial()
    assert vehicle.state["speed_kph"] == 0.0
    assert vehicle.state["gear"] == "P"
    assert vehicle.state["state_version"] == 1
    assert vehicle.command_count == 0


def test_successful_command_bumps_state_version_and_count():
    vehicle = VehicleSimulator.initial()
    result = vehicle.execute("cmd-1", 1, "set_hvac_temperature", {"temperature_c": 22})
    assert result.status == "completed"
    assert vehicle.state["hvac"]["temperature_c"] == 22
    assert vehicle.state["state_version"] == 2
    assert vehicle.command_count == 1


def test_stale_expected_version_is_rejected_without_mutation():
    vehicle = VehicleSimulator.initial()
    result = vehicle.execute("cmd-1", 99, "set_hvac_temperature", {"temperature_c": 22})
    assert result.status == "rejected"
    assert result.error_code == "stale_state"
    assert vehicle.state["hvac"]["temperature_c"] == 27
    assert vehicle.state["state_version"] == 1
    assert vehicle.command_count == 0


def test_same_command_id_replays_cached_result_without_reapplying():
    vehicle = VehicleSimulator.initial()
    first = vehicle.execute("cmd-1", 1, "set_window_position", {"window": "front_left", "percent": 40})
    second = vehicle.execute("cmd-1", 1, "set_window_position", {"window": "front_left", "percent": 40})
    assert first == second
    assert vehicle.command_count == 1
    assert vehicle.state["state_version"] == 2


def test_simulator_independently_blocks_door_open_while_moving():
    """Policy đã chặn ở tầng trên; simulator vẫn phải tự chặn (safety_and_hitl.md)."""
    vehicle = VehicleSimulator.initial(speed_kph=45.0, gear="D")
    result = vehicle.execute("cmd-1", 1, "set_door_state", {"door": "front_left", "state": "open"})
    assert result.status == "rejected"
    assert result.error_code == "unsafe_vehicle_state"
    assert vehicle.state["doors"]["front_left"] == "closed"
    assert vehicle.command_count == 0


def test_invalid_args_fail_without_mutation():
    vehicle = VehicleSimulator.initial()
    result = vehicle.execute("cmd-1", 1, "set_hvac_temperature", {"temperature_c": 99})
    assert result.status == "failed"
    assert result.error_code == "args_invalid" or result.error_code == "range_invalid"
    assert vehicle.command_count == 0


def test_snapshot_is_a_copy():
    vehicle = VehicleSimulator.initial()
    snapshot = vehicle.snapshot()
    snapshot["speed_kph"] = 120.0
    assert vehicle.state["speed_kph"] == 0.0
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_vehicle.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.vehicle'`

- [ ] **Step 3: Viết implementation**

Tạo `src/agents/vehicle.py`:

```python
"""Simulator xe in-memory.

Đây là bản `src/` của `experiments/offline_poc/src/offline_poc/vehicle_mock.py`,
đổi sang tên args canonical. Hai tính chất quan trọng:

- **Idempotent theo `command_id`** — replay trả kết quả đã lưu, không áp dụng lại.
- **Tự kiểm predicate an toàn**, độc lập với policy. `docs/safety_and_hitl.md`
  yêu cầu "policy + simulator kiểm độc lập": nếu policy vì lý do nào đó cho một
  lệnh mở cửa lúc đang chạy đi qua, tầng này vẫn phải từ chối.
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from src.agents.contracts import ToolResult, ValidationDenied
from src.agents.tools import validate_args


class VehicleSimulator:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = deepcopy(state)
        self.command_count = 0
        self._results: dict[str, ToolResult] = {}

    @classmethod
    def initial(cls, *, speed_kph: float = 0.0, gear: str = "P", state_version: int = 1) -> VehicleSimulator:
        return cls(
            {
                "state_version": state_version,
                "speed_kph": speed_kph,
                "gear": gear,
                "hvac": {"power": True, "temperature_c": 27},
                "seat_heating": {"front_left": 0, "front_right": 0},
                "seat_position": {
                    "front_left": {"fore_aft": 50, "recline": 50, "height": 50},
                    "front_right": {"fore_aft": 50, "recline": 50, "height": 50},
                },
                "windows": {"front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0},
                "doors": {"front_left": "closed", "front_right": "closed", "rear_left": "closed", "rear_right": "closed"},
                "media": {"status": "paused", "volume": 25},
                "navigation": {"status": "idle", "destination_id": None},
            }
        )

    def snapshot(self) -> dict[str, Any]:
        """Bản sao trạng thái, dùng cho policy — policy không được giữ tham chiếu sống."""
        return deepcopy(self.state)

    def is_stationary(self) -> bool:
        return self.state["speed_kph"] == 0 and self.state["gear"] == "P"

    def execute(self, command_id: str, expected_state_version: int, tool: str, args: dict[str, Any]) -> ToolResult:
        cached = self._results.get(command_id)
        if cached is not None:
            return cached

        started_ns = time.perf_counter_ns()
        before = deepcopy(self.state)

        if expected_state_version != self.state["state_version"]:
            return self._remember(command_id, before, tool, args, "rejected", "stale_state", started_ns)

        try:
            validated = validate_args(tool, args)
        except ValidationDenied as exc:
            return self._remember(command_id, before, tool, args, "failed", exc.subcode, started_ns)

        if self._is_unsafe(tool, args):
            return self._remember(command_id, before, tool, args, "rejected", "unsafe_vehicle_state", started_ns)

        changed = self._apply(tool, validated.model_dump())
        if changed:
            self.state["state_version"] += 1
        self.command_count += 1
        return self._remember(command_id, before, tool, args, "completed", None, started_ns)

    def _is_unsafe(self, tool: str, args: dict[str, Any]) -> bool:
        """Mở cửa hoặc dịch ghế khi xe chưa đứng yên là không an toàn, luôn luôn."""
        if self.is_stationary():
            return False
        if tool == "set_door_state" and args.get("state") == "open":
            return True
        return tool == "set_seat_position"

    def _apply(self, tool: str, args: dict[str, Any]) -> bool:
        if tool == "get_vehicle_state":
            return False
        if tool == "set_hvac_power":
            self.state["hvac"]["power"] = args["enabled"]
        elif tool == "set_hvac_temperature":
            self.state["hvac"]["temperature_c"] = args["temperature_c"]
        elif tool == "set_seat_heating":
            self.state["seat_heating"][args["seat"]] = args["level"]
        elif tool == "set_seat_position":
            self.state["seat_position"][args["seat"]][args["axis"]] = args["value"]
        elif tool == "set_window_position":
            self.state["windows"][args["window"]] = args["percent"]
        elif tool == "set_door_state":
            self.state["doors"][args["door"]] = args["state"]
        elif tool == "media_control":
            self._apply_media(args)
        elif tool == "set_navigation":
            self._apply_navigation(args)
        else:  # pragma: no cover - allowlist đã chặn ở validate_args
            raise ValueError(f"tool không được hỗ trợ: {tool}")
        return True

    def _apply_media(self, args: dict[str, Any]) -> None:
        action = args["action"]
        if action == "set_volume":
            self.state["media"]["volume"] = args["volume"]
        elif action in {"play", "pause"}:
            self.state["media"]["status"] = "playing" if action == "play" else "paused"
        else:
            self.state["media"]["status"] = "playing"

    def _apply_navigation(self, args: dict[str, Any]) -> None:
        if args["operation"] == "cancel":
            self.state["navigation"] = {"status": "idle", "destination_id": None}
        else:
            self.state["navigation"] = {"status": "active", "destination_id": args["destination_id"]}

    def _remember(
        self,
        command_id: str,
        before: dict[str, Any],
        tool: str,
        args: dict[str, Any],
        status: str,
        error_code: str | None,
        started_ns: int,
    ) -> ToolResult:
        result = ToolResult(
            command_id=command_id,
            step_id=command_id.rsplit(":", 1)[-1],
            tool=tool,
            args=args,
            status=status,
            before=before,
            after=deepcopy(self.state),
            error_code=error_code,
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )
        self._results[command_id] = result
        return result
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_vehicle.py -q`
Expected: PASS — 7 passed

- [ ] **Step 5: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/vehicle.py tests/test_agents/test_vehicle.py
.\.venv\Scripts\python.exe -m ruff format src/agents/vehicle.py tests/test_agents/test_vehicle.py
git add src/agents/vehicle.py tests/test_agents/test_vehicle.py
git commit -m "feat(agent): VehicleSimulator idempotent voi hang rao an toan doc lap"
```

---

### Task 4: Policy — điểm duy nhất gán safety

**Files:**
- Create: `src/agents/policy.py`
- Test: `tests/test_agents/test_policy.py`

**Interfaces:**
- Consumes: `CandidateActionPlan`, `ActionPlan`, `PlanStep`, `SafetyLevel` (Task 1); `TOOL_ARGS` (Task 2)
- Produces:
  - `classify(tool: str, snapshot: dict) -> SafetyLevel`
  - `is_stationary(snapshot: dict) -> bool`
  - `materialize_action_plan(candidate: CandidateActionPlan, snapshot: dict, session_id: str, vehicle_id: str) -> ActionPlan`
  - `plan_digest(plan: ActionPlan) -> str`
  - `canonical_json(payload: object) -> str`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_policy.py`:

```python
"""Bảng phân loại S0-S3 ánh xạ 1:1 với docs/safety_and_hitl.md mục Classification rules."""

import pytest

from src.agents.contracts import CandidateActionPlan, CandidateStep
from src.agents.policy import classify, materialize_action_plan, plan_digest
from src.agents.vehicle import VehicleSimulator

STATIONARY = VehicleSimulator.initial().snapshot()
MOVING = VehicleSimulator.initial(speed_kph=45.0, gear="D").snapshot()
IN_GEAR_STOPPED = VehicleSimulator.initial(speed_kph=0.0, gear="D").snapshot()


def _candidate(tool: str, args: dict) -> CandidateActionPlan:
    return CandidateActionPlan(steps=(CandidateStep(step_id="step-1", ordinal=0, tool=tool, args=args),))


@pytest.mark.parametrize("snapshot", [STATIONARY, MOVING])
def test_window_is_always_s2(snapshot):
    """safety_and_hitl.md Required safety test #12."""
    assert classify("set_window_position", snapshot) == "S2"


@pytest.mark.parametrize("tool", ["set_hvac_power", "set_hvac_temperature", "set_seat_heating", "media_control", "set_navigation"])
def test_s1_tools(tool):
    """safety_and_hitl.md Required safety test #13 và mục Classification rules."""
    assert classify(tool, STATIONARY) == "S1"


def test_get_vehicle_state_is_s0():
    assert classify("get_vehicle_state", MOVING) == "S0"


@pytest.mark.parametrize("tool", ["set_door_state", "set_seat_position"])
def test_door_and_seat_position_are_s2_only_when_stationary(tool):
    """safety_and_hitl.md Required safety test #6."""
    assert classify(tool, STATIONARY) == "S2"
    assert classify(tool, MOVING) == "S3"
    assert classify(tool, IN_GEAR_STOPPED) == "S3"


def test_materialize_sets_requires_approval_for_s2():
    plan = materialize_action_plan(
        _candidate("set_window_position", {"window": "front_left", "percent": 30}), STATIONARY, "ses-1", "veh-1"
    )
    assert plan.steps[0].safety_level == "S2"
    assert plan.requires_approval is True
    assert plan.vehicle_state_version == STATIONARY["state_version"]


def test_materialize_leaves_s1_without_approval():
    plan = materialize_action_plan(_candidate("set_hvac_power", {"enabled": True}), STATIONARY, "ses-1", "veh-1")
    assert plan.steps[0].safety_level == "S1"
    assert plan.requires_approval is False


def test_materialize_marks_s3_and_still_requires_no_approval():
    """S3 bị chặn ở node safety; approval không bao giờ được tạo cho nó."""
    plan = materialize_action_plan(_candidate("set_door_state", {"door": "front_left", "state": "open"}), MOVING, "ses-1", "veh-1")
    assert plan.steps[0].safety_level == "S3"
    assert plan.requires_approval is False


def test_materialize_rejects_tool_outside_allowlist():
    with pytest.raises(ValueError, match="allowlist"):
        materialize_action_plan(_candidate("set_engine_off", {}), STATIONARY, "ses-1", "veh-1")


def test_plan_id_and_digest_are_stable_across_replay():
    args = {"window": "front_left", "percent": 30}
    first = materialize_action_plan(_candidate("set_window_position", args), STATIONARY, "ses-1", "veh-1")
    second = materialize_action_plan(_candidate("set_window_position", args), STATIONARY, "ses-1", "veh-1")
    assert first.plan_id == second.plan_id
    assert plan_digest(first) == plan_digest(second)


def test_digest_changes_when_args_change():
    base = materialize_action_plan(_candidate("set_window_position", {"window": "front_left", "percent": 30}), STATIONARY, "ses-1", "veh-1")
    edited = materialize_action_plan(_candidate("set_window_position", {"window": "front_left", "percent": 80}), STATIONARY, "ses-1", "veh-1")
    assert plan_digest(base) != plan_digest(edited)
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_policy.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.policy'`

- [ ] **Step 3: Viết implementation**

Tạo `src/agents/policy.py`:

```python
"""Policy an toàn — điểm **duy nhất** trong hệ thống được gán `safety_level`.

Router và SLM chỉ sinh `CandidateActionPlan`. Không node nào khác được import
`ActionPlan` để tự dựng. Bảng dưới đây ánh xạ trực tiếp
`docs/safety_and_hitl.md` mục "Classification rules".

Lưu ý về ngưỡng tốc độ: ticket của sprint đề xuất `speed_kph > 5` làm điều
kiện kích hoạt xác nhận. Ngưỡng đó **không** được implement ở đây; xem ADR-010
để biết vì sao (nó vừa lỏng hơn canonical ở cửa sổ, vừa nguy hiểm hơn ở cửa xe).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.agents.contracts import ActionPlan, CandidateActionPlan, PlanStep, SafetyLevel
from src.agents.tools import TOOL_ARGS

_S0_TOOLS = {"get_vehicle_state"}
_S1_TOOLS = {
    "set_hvac_power",
    "set_hvac_temperature",
    "set_seat_heating",
    "media_control",
    "set_navigation",
}
_ALWAYS_S2_TOOLS = {"set_window_position"}
#: S2 chỉ khi xe đứng yên và ở số P; ngoài predicate đó là S3.
_STATIONARY_ONLY_TOOLS = {"set_door_state", "set_seat_position"}


def canonical_json(payload: object) -> str:
    """JSON ổn định: khóa sắp xếp, không khoảng trắng thừa, giữ nguyên Unicode."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def is_stationary(snapshot: dict[str, Any]) -> bool:
    return snapshot["speed_kph"] == 0 and snapshot["gear"] == "P"


def classify(tool: str, snapshot: dict[str, Any]) -> SafetyLevel:
    if tool in _S0_TOOLS:
        return "S0"
    if tool in _S1_TOOLS:
        return "S1"
    if tool in _ALWAYS_S2_TOOLS:
        return "S2"
    if tool in _STATIONARY_ONLY_TOOLS:
        return "S2" if is_stationary(snapshot) else "S3"
    raise ValueError(f"tool nằm ngoài allowlist, không thể phân loại: {tool}")


def materialize_action_plan(
    candidate: CandidateActionPlan,
    snapshot: dict[str, Any],
    session_id: str,
    vehicle_id: str,
) -> ActionPlan:
    """Biến candidate thành `ActionPlan` canonical, bất biến.

    `plan_id` suy ra từ nội dung candidate + phiên bản state, nên ổn định qua
    replay — điều kiện cần để branch HITL bind approval theo digest.
    """
    for step in candidate.steps:
        if step.tool not in TOOL_ARGS:
            raise ValueError(f"tool nằm ngoài allowlist: {step.tool}")

    steps = tuple(
        PlanStep(
            step_id=step.step_id,
            ordinal=step.ordinal,
            tool=step.tool,
            args=step.args,
            depends_on=step.depends_on,
            safety_level=classify(step.tool, snapshot),
        )
        for step in candidate.steps
    )
    requires_approval = any(step.safety_level == "S2" for step in steps)
    identity = canonical_json(
        {
            "steps": [step.model_dump(mode="json") for step in candidate.steps],
            "vehicle_state_version": snapshot["state_version"],
            "session_id": session_id,
        }
    )
    plan_id = f"plan-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    return ActionPlan(
        plan_id=plan_id,
        session_id=session_id,
        vehicle_id=vehicle_id,
        vehicle_state_version=snapshot["state_version"],
        steps=steps,
        requires_approval=requires_approval,
    )


def plan_digest(plan: ActionPlan) -> str:
    """Vân tay của plan. Branch HITL dùng nó để bind approval; sửa plan là đổi digest."""
    return hashlib.sha256(canonical_json(plan.model_dump(mode="json")).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_policy.py -q`
Expected: PASS — 16 passed

- [ ] **Step 5: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/policy.py tests/test_agents/test_policy.py
.\.venv\Scripts\python.exe -m ruff format src/agents/policy.py tests/test_agents/test_policy.py
git add src/agents/policy.py tests/test_agents/test_policy.py
git commit -m "feat(agent): policy S0-S3 la diem duy nhat gan safety_level"
```

---

### Task 5: Router phần 1 — chuẩn hóa, guard, HVAC, nhạc

**Files:**
- Create: `src/agents/router.py`
- Test: `tests/test_agents/test_router.py`

**Interfaces:**
- Consumes: `CandidateActionPlan`, `CandidateStep`, `RouteDecision`, `Intent`, `Disposition` (Task 1)
- Produces:
  - `normalize_vi(text: str) -> str`
  - `DeterministicControlRouter(poi_fixture: list[dict] | None = None)` với `.route(input_text: str) -> RouteDecision`
  - Kiểu nội bộ `MatchResult = tuple[Disposition, Intent, str, CandidateStep | None]`

- [ ] **Step 1: Viết test thất bại cho chuẩn hóa và guard**

Tạo `tests/test_agents/test_router.py`:

```python
"""Router luật — bảng case tiếng Việt. Mỗi hàng là một hành vi có thể hồi quy."""

import pytest

from src.agents.router import DeterministicControlRouter, normalize_vi

router = DeterministicControlRouter()


def _step(text: str):
    decision = router.route(text)
    assert decision.disposition == "control", f"{text!r} -> {decision.disposition}/{decision.reason}"
    return decision.candidate_plan.steps


def test_normalize_unifies_tone_placement_and_strips_punctuation():
    assert normalize_vi("Bật Điều Hoà!") == "bật điều hòa"
    assert normalize_vi("  mở   cửa sổ  30%  ") == "mở cửa sổ 30%"


@pytest.mark.parametrize("text", ["Đừng mở cửa sổ bên lái", "Không phát nhạc"])
def test_negation_is_denied(text):
    decision = router.route(text)
    assert decision.disposition == "denied"
    assert decision.reason == "negated_command"


@pytest.mark.parametrize("text", ["Tắt phanh ABS", "Mở cốp sau"])
def test_actuator_outside_registry_is_denied(text):
    decision = router.route(text)
    assert decision.disposition == "denied"
    assert decision.reason == "unsupported_actuator"


@pytest.mark.parametrize("text", ["Điều hòa hoạt động như thế nào?", "Cửa sổ bị kẹt thì xử lý thế nào?"])
def test_manual_question_goes_to_rag(text):
    decision = router.route(text)
    assert decision.disposition == "not_control"
    assert decision.reason == "manual_or_information_request"
    assert decision.intent == "manual_query"


@pytest.mark.parametrize("text", ["Mở nó ra", "Đặt thấp hơn", "Bật nó lên"])
def test_ambiguous_reference_asks_for_clarification(text):
    decision = router.route(text)
    assert decision.disposition == "clarify"
    assert decision.reason == "ambiguous_reference"


def test_unknown_request_is_not_control():
    decision = router.route("Hôm nay trời đẹp quá")
    assert decision.disposition == "not_control"
    assert decision.reason == "no_control_rule"
    assert decision.candidate_plan is None


# --- HVAC ---

def test_hvac_power_on_off():
    assert _step("Bật điều hòa")[0].tool == "set_hvac_power"
    assert _step("Bật điều hòa")[0].args == {"enabled": True}
    assert _step("Tắt điều hòa")[0].args == {"enabled": False}


@pytest.mark.parametrize("text,expected", [("Đặt điều hòa 24 độ", 24), ("Tăng nhiệt độ lên 26 độ", 26), ("Chỉnh điều hòa hai mươi tư độ", 24)])
def test_hvac_temperature(text, expected):
    steps = _step(text)
    assert steps[0].tool == "set_hvac_temperature"
    assert steps[0].args == {"temperature_c": expected}


def test_hvac_power_with_temperature_produces_two_dependent_steps():
    """KI-001: bản PoC nuốt mất số 25 vì nhánh 'bật' return sớm. Ở đây không được nuốt."""
    steps = _step("Bật điều hòa lên 25 độ")
    assert [s.tool for s in steps] == ["set_hvac_power", "set_hvac_temperature"]
    assert steps[0].args == {"enabled": True}
    assert steps[1].args == {"temperature_c": 25}
    assert steps[1].depends_on == (steps[0].step_id,)


def test_hvac_missing_temperature_asks_for_clarification():
    decision = router.route("Đặt điều hòa")
    assert decision.disposition == "clarify"
    assert decision.reason == "missing_temperature"
    assert decision.intent == "hvac_temperature"


def test_hvac_out_of_range_is_denied_not_clamped():
    decision = router.route("Đặt điều hòa 45 độ")
    assert decision.disposition == "denied"
    assert decision.reason == "temperature_out_of_range"


# --- Nhạc ---

def test_media_playback():
    assert _step("Phát nhạc")[0].args == {"action": "play"}
    assert _step("Tạm dừng nhạc")[0].args == {"action": "pause"}


@pytest.mark.parametrize("text,expected", [("Đặt âm lượng 40", 40), ("Giảm âm lượng xuống 20", 20)])
def test_media_volume(text, expected):
    steps = _step(text)
    assert steps[0].tool == "media_control"
    assert steps[0].args == {"action": "set_volume", "volume": expected}


def test_media_volume_out_of_range_is_denied():
    decision = router.route("Đặt âm lượng 150")
    assert decision.disposition == "denied"
    assert decision.reason == "volume_out_of_range"


def test_media_volume_missing_value_asks_for_clarification():
    decision = router.route("Đặt âm lượng")
    assert decision.disposition == "clarify"
    assert decision.reason == "missing_volume"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.router'`

- [ ] **Step 3: Viết khung router + chuẩn hóa + guard + HVAC + nhạc**

Tạo `src/agents/router.py`:

```python
"""Router luật cho lệnh điều khiển tiếng Việt.

Kỹ thuật ở đây kế thừa `experiments/offline_poc/src/offline_poc/control_router.py`
(đã đo 95% downstream tool-exact trên dataset `poc/v2`), nhưng contract thì theo
`docs/agent_spec.md`: router **chỉ** sinh `CandidateActionPlan`, không gán safety.

Nguyên tắc bất di bất dịch của file này:

- Thiếu slot bắt buộc thì hỏi lại (`clarify`), **không đoán**.
- Giá trị ngoài khoảng thì từ chối (`denied`), **không kẹp về biên**.
- Mỗi matcher đòi hỏi cả từ khóa domain lẫn động từ điều khiển ở đầu câu, để
  câu hỏi tra cứu không bị hiểu nhầm thành lệnh.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

from src.agents.contracts import (
    CandidateActionPlan,
    CandidateStep,
    Disposition,
    Intent,
    RouteDecision,
)

MatchResult = tuple[Disposition, Intent, str, tuple[CandidateStep, ...]]

_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_NEGATION_PATTERN = re.compile(r"\b(?:đừng|không|chớ|chẳng)\b")
_POLITE_PREFIX_PATTERN = re.compile(r"^(?:(?:hãy|vui lòng|làm ơn|giúp tôi)\s+)*")

_NUMBER_WORDS = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4,
    "tư": 4, "năm": 5, "lăm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9,
}

_ACTUATOR_TOKENS = ("điều hòa", "nhiệt độ", "nhạc", "âm lượng", "cửa sổ", "cửa kính", "sưởi", "ghế", "cửa")
_UNSUPPORTED_TOKENS = ("phanh abs", "phanh tay", "cốp sau", "cốp xe", "động cơ", "túi khí")
_MANUAL_TOKENS = ("như thế nào", "thì xử lý", "xử lý thế nào", "nghĩa là gì", "cách nào", "hiện tại là", "đang đặt ở", "có sưởi")
_AMBIGUOUS_TEXTS = {"mở nó ra", "đặt thấp hơn", "đặt cao hơn", "bật nó lên", "tắt nó đi"}


def normalize_vi(text: str) -> str:
    """NFC → casefold → hợp nhất `hoà`/`hòa` → bỏ ký tự không phải chữ/số/`%`."""
    normalized = unicodedata.normalize("NFC", text).casefold()
    normalized = normalized.replace("hoà", "hòa")
    normalized = re.sub(r"[^\w%]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


class DeterministicControlRouter:
    def __init__(self, poi_fixture: list[dict[str, Any]] | None = None) -> None:
        self._poi_ids = {str(item["id"]) for item in (poi_fixture or []) if "id" in item}

    def route(self, input_text: str) -> RouteDecision:
        started_ns = time.perf_counter_ns()
        text = normalize_vi(input_text)
        disposition, intent, reason, steps = self._match(text)
        candidate = CandidateActionPlan(steps=steps) if disposition == "control" else None
        return RouteDecision(
            disposition=disposition,
            intent=intent,
            reason=reason,
            route_source="deterministic",
            candidate_plan=candidate,
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )

    def _match(self, text: str) -> MatchResult:
        # Thứ tự bốn guard này quan trọng. Câu hỏi tra cứu phải được nhận diện
        # **trước** danh sách actuator không hỗ trợ: "Đèn cảnh báo động cơ nghĩa
        # là gì?" là câu hỏi sổ tay, không phải yêu cầu điều khiển động cơ.
        if any(token in text for token in _ACTUATOR_TOKENS) and _NEGATION_PATTERN.search(text):
            return "denied", "none", "negated_command", ()
        if any(token in text for token in _MANUAL_TOKENS):
            return "not_control", "manual_query", "manual_or_information_request", ()
        if any(token in text for token in _UNSUPPORTED_TOKENS):
            return "denied", "none", "unsupported_actuator", ()
        if text in _AMBIGUOUS_TEXTS:
            return "clarify", "none", "ambiguous_reference", ()

        for matcher in (
            self._match_hvac,
            self._match_music,
            self._match_window,
            self._match_seat,
            self._match_door,
            self._match_navigation,
        ):
            result = matcher(text)
            if result is not None:
                return result
        return "not_control", "none", "no_control_rule", ()

    # ---- HVAC -------------------------------------------------------------

    def _match_hvac(self, text: str) -> MatchResult | None:
        if "điều hòa" not in text and "nhiệt độ" not in text:
            return None
        turning_on = self._starts_with_command(text, "bật")
        turning_off = self._starts_with_command(text, "tắt")
        adjusting = self._starts_with_command(text, "đặt", "tăng", "giảm", "chỉnh", "hạ")
        if not (turning_on or turning_off or adjusting):
            return None

        value = self._number(text)

        if turning_off:
            return self._control("hvac_power", "set_hvac_power", {"enabled": False})

        if turning_on:
            # KI-001: "Bật điều hòa lên 25 độ" phải giữ được cả hai ý định. Bản PoC
            # return ngay ở đây và nuốt mất con số — đó là "tuân thủ một phần trong
            # im lặng", tệ hơn cả từ chối.
            if value is None:
                return self._control("hvac_power", "set_hvac_power", {"enabled": True})
            if not 16 <= value <= 30:
                return "denied", "hvac_temperature", "temperature_out_of_range", ()
            return self._control_steps(
                "hvac_temperature",
                (
                    ("set_hvac_power", {"enabled": True}, ()),
                    ("set_hvac_temperature", {"temperature_c": value}, ("step-1",)),
                ),
            )

        if value is None:
            return "clarify", "hvac_temperature", "missing_temperature", ()
        if not 16 <= value <= 30:
            return "denied", "hvac_temperature", "temperature_out_of_range", ()
        return self._control("hvac_temperature", "set_hvac_temperature", {"temperature_c": value})

    # ---- Nhạc -------------------------------------------------------------

    def _match_music(self, text: str) -> MatchResult | None:
        if "âm lượng" in text:
            if not self._starts_with_command(text, "đặt", "tăng", "giảm", "chỉnh", "hạ"):
                return None
            value = self._number(text)
            if value is None:
                return "clarify", "media_volume", "missing_volume", ()
            if not 0 <= value <= 100:
                return "denied", "media_volume", "volume_out_of_range", ()
            return self._control("media_volume", "media_control", {"action": "set_volume", "volume": value})
        if "nhạc" not in text:
            return None
        if self._starts_with_command(text, "tạm dừng", "dừng"):
            return self._control("media_playback", "media_control", {"action": "pause"})
        if self._starts_with_command(text, "phát", "bật", "mở"):
            return self._control("media_playback", "media_control", {"action": "play"})
        if self._starts_with_command(text, "chuyển", "tiếp"):
            return self._control("media_playback", "media_control", {"action": "next"})
        return None

    # ---- Task 6 điền tiếp: _match_window, _match_seat, _match_door, _match_navigation

    # ---- Helper -----------------------------------------------------------

    @staticmethod
    def _starts_with_command(text: str, *verbs: str) -> bool:
        command = _POLITE_PREFIX_PATTERN.sub("", text, count=1)
        return any(command == verb or command.startswith(f"{verb} ") for verb in verbs)

    @staticmethod
    def _number(text: str) -> int | None:
        """Đọc số Ả Rập trước, rồi tới số viết chữ (`hai mươi tư` → 24)."""
        match = _NUMBER_PATTERN.search(text)
        if match:
            return int(match.group(1))
        tokens = text.split()
        for index, token in enumerate(tokens):
            if token != "mươi" or index == 0:
                continue
            tens = _NUMBER_WORDS.get(tokens[index - 1])
            if tens is None or tens == 0:
                continue
            units = _NUMBER_WORDS.get(tokens[index + 1], 0) if index + 1 < len(tokens) else 0
            return tens * 10 + units
        for index, token in enumerate(tokens):
            if token != "trăm" or index == 0:
                continue
            hundreds = _NUMBER_WORDS.get(tokens[index - 1])
            if hundreds:
                return hundreds * 100
        for token in reversed(tokens):
            if token in _NUMBER_WORDS:
                return _NUMBER_WORDS[token]
        return None

    @staticmethod
    def _control(intent: Intent, tool: str, args: dict[str, Any]) -> MatchResult:
        return "control", intent, "deterministic_rule", (CandidateStep(step_id="step-1", ordinal=0, tool=tool, args=args),)

    @staticmethod
    def _control_steps(intent: Intent, specs: tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...]) -> MatchResult:
        steps = tuple(
            CandidateStep(step_id=f"step-{index + 1}", ordinal=index, tool=tool, args=args, depends_on=depends_on)
            for index, (tool, args, depends_on) in enumerate(specs)
        )
        return "control", intent, "deterministic_rule", steps
```

- [ ] **Step 4: Chạy test — phần window/seat/nav sẽ vẫn fail, đó là dự kiến**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q`
Expected: PASS cho toàn bộ test hiện có trong file (guard + HVAC + nhạc). Nếu có `AttributeError: _match_window` thì đã copy nhầm — bốn matcher đó chưa được gọi vì chưa tồn tại; xóa chúng khỏi vòng lặp `for matcher in (...)` cho tới Task 6, hoặc thêm ngay 4 stub trả `None`.

Cách an toàn: tạm thời để vòng lặp chỉ gồm `self._match_hvac, self._match_music`, Task 6 sẽ thêm lại bốn cái còn lại.

- [ ] **Step 5: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/router.py tests/test_agents/test_router.py
.\.venv\Scripts\python.exe -m ruff format src/agents/router.py tests/test_agents/test_router.py
git add src/agents/router.py tests/test_agents/test_router.py
git commit -m "feat(agent): router luat - chuan hoa, guard, HVAC (sua KI-001), nhac"
```

---

### Task 6: Router phần 2 — cửa sổ, ghế, cửa xe, dẫn đường

**Files:**
- Modify: `src/agents/router.py`
- Test: `tests/test_agents/test_router.py` (thêm vào cuối)

**Interfaces:**
- Consumes: khung router từ Task 5
- Produces: `_match_window`, `_match_seat`, `_match_door`, `_match_navigation` được nối vào vòng lặp `_match`; POI fixture mặc định đọc từ `eval/datasets/poc/v1/poi.json` khi caller truyền vào

- [ ] **Step 1: Thêm test thất bại**

Thêm vào cuối `tests/test_agents/test_router.py`:

```python
# --- Cửa sổ ---

@pytest.mark.parametrize(
    "text,window,percent",
    [
        ("Mở cửa sổ bên phụ một nửa", "front_right", 50),
        ("Đóng cửa sổ bên lái", "front_left", 0),
        ("Mở cửa sổ bên lái 30 phần trăm", "front_left", 30),
        ("Mở hết cửa sổ bên phụ", "front_right", 100),
        ("Hạ cửa kính bên lái 20 phần trăm", "front_left", 20),
    ],
)
def test_window_position(text, window, percent):
    steps = _step(text)
    assert steps[0].tool == "set_window_position"
    assert steps[0].args == {"window": window, "percent": percent}


def test_window_missing_side_asks_for_clarification():
    decision = router.route("Mở cửa sổ")
    assert decision.disposition == "clarify"
    assert decision.reason == "missing_window_side"


def test_window_missing_position_asks_for_clarification():
    decision = router.route("Mở cửa sổ bên lái")
    assert decision.disposition == "clarify"
    assert decision.reason == "missing_window_position"


def test_window_out_of_range_is_denied():
    decision = router.route("Mở cửa sổ bên lái 150 phần trăm")
    assert decision.disposition == "denied"
    assert decision.reason == "window_position_out_of_range"


# --- Ghế ---

@pytest.mark.parametrize(
    "text,seat,level",
    [
        ("Bật sưởi ghế lái mức 2", "front_left", 2),
        ("Bật sưởi ghế phụ mức 1", "front_right", 1),
        ("Tắt sưởi ghế lái", "front_left", 0),
        ("Đặt sưởi ghế phụ mức 3", "front_right", 3),
    ],
)
def test_seat_heating(text, seat, level):
    steps = _step(text)
    assert steps[0].tool == "set_seat_heating"
    assert steps[0].args == {"seat": seat, "level": level}


def test_seat_heating_out_of_range_is_denied():
    decision = router.route("Bật sưởi ghế lái mức 9")
    assert decision.disposition == "denied"
    assert decision.reason == "seat_level_out_of_range"


def test_seat_heating_missing_side_asks_for_clarification():
    decision = router.route("Bật sưởi mức 2")
    assert decision.disposition == "clarify"
    assert decision.reason == "missing_seat_side"


@pytest.mark.parametrize(
    "text,axis,value",
    [("Ngả lưng ghế lái 70 phần trăm", "recline", 70), ("Đẩy ghế phụ về trước 30 phần trăm", "fore_aft", 30)],
)
def test_seat_position(text, axis, value):
    steps = _step(text)
    assert steps[0].tool == "set_seat_position"
    assert steps[0].args["axis"] == axis
    assert steps[0].args["value"] == value


# --- Cửa xe ---

def test_door_open_produces_candidate_and_lets_policy_decide():
    """Router không phân loại an toàn. Đường S3 được chứng minh ở test_policy."""
    steps = _step("Mở cửa bên lái")
    assert steps[0].tool == "set_door_state"
    assert steps[0].args == {"door": "front_left", "state": "open"}


def test_door_missing_side_asks_for_clarification():
    decision = router.route("Mở cửa xe")
    assert decision.disposition == "clarify"
    assert decision.reason == "missing_door_side"


# --- Dẫn đường ---

@pytest.mark.parametrize(
    "text,destination_id",
    [
        ("Dẫn đường đến quán cà phê thứ nhất", "poi-cafe-01"),
        ("Dẫn đường đến Cà phê Bình Minh", "poi-cafe-02"),
        ("Dẫn đường đến quán cà phê gần nhất", "poi-cafe-01"),
        ("Dẫn đường đến trạm sạc", "poi-charge-01"),
    ],
)
def test_navigation_start(text, destination_id):
    steps = _step(text)
    assert steps[0].tool == "set_navigation"
    assert steps[0].args == {"operation": "start", "destination_id": destination_id}


def test_navigation_cancel():
    steps = _step("Hủy dẫn đường")
    assert steps[0].args == {"operation": "cancel"}


def test_navigation_unknown_destination_asks_for_clarification():
    decision = router.route("Dẫn đường đến Hà Nội")
    assert decision.disposition == "clarify"
    assert decision.reason == "unknown_local_destination"


def test_navigation_rejects_destination_outside_fixture():
    limited = DeterministicControlRouter(poi_fixture=[{"id": "poi-cafe-01"}])
    decision = limited.route("Dẫn đường đến trạm sạc")
    assert decision.disposition == "denied"
    assert decision.reason == "poi_not_in_fixture"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q`
Expected: FAIL — các test cửa sổ/ghế/cửa/dẫn đường fail vì `_match` chưa có matcher tương ứng

- [ ] **Step 3: Thêm bốn matcher**

Thay comment `# ---- Task 6 điền tiếp: ...` trong `src/agents/router.py` bằng:

```python
    # ---- Cửa sổ -----------------------------------------------------------

    def _match_window(self, text: str) -> MatchResult | None:
        if "cửa sổ" not in text and "cửa kính" not in text:
            return None
        if not self._starts_with_command(text, "mở", "đóng", "hạ", "kéo", "nâng"):
            return None
        window = self._side(text)
        if window is None:
            return "clarify", "window_position", "missing_window_side", ()

        if "đóng" in text:
            percent: int | None = 0
        elif "mở hết" in text or "mở hoàn toàn" in text:
            percent = 100
        elif "một nửa" in text or "nửa" in text:
            percent = 50
        else:
            percent = self._number(text)
        if percent is None:
            return "clarify", "window_position", "missing_window_position", ()
        if not 0 <= percent <= 100:
            return "denied", "window_position", "window_position_out_of_range", ()
        return self._control("window_position", "set_window_position", {"window": window, "percent": percent})

    # ---- Ghế --------------------------------------------------------------

    def _match_seat(self, text: str) -> MatchResult | None:
        if "sưởi" in text:
            return self._match_seat_heating(text)
        if "ghế" in text:
            return self._match_seat_position(text)
        return None

    def _match_seat_heating(self, text: str) -> MatchResult | None:
        if not self._starts_with_command(text, "bật", "tắt", "đặt", "tăng", "giảm", "chỉnh"):
            return None
        seat = self._side(text)
        if seat is None:
            return "clarify", "seat_heating", "missing_seat_side", ()
        if self._starts_with_command(text, "tắt"):
            level: int | None = 0
        else:
            level = self._number(text)
        if level is None:
            return "clarify", "seat_heating", "missing_seat_level", ()
        if not 0 <= level <= 3:
            return "denied", "seat_heating", "seat_level_out_of_range", ()
        return self._control("seat_heating", "set_seat_heating", {"seat": seat, "level": level})

    def _match_seat_position(self, text: str) -> MatchResult | None:
        if "ngả lưng" in text or "ngả ghế" in text:
            axis = "recline"
        elif "về trước" in text or "về sau" in text or "tiến" in text or "lùi" in text:
            axis = "fore_aft"
        elif "nâng ghế" in text or "hạ ghế" in text:
            axis = "height"
        else:
            return None
        seat = self._side(text)
        if seat is None:
            return "clarify", "seat_position", "missing_seat_side", ()
        value = self._number(text)
        if value is None:
            return "clarify", "seat_position", "missing_seat_value", ()
        if not 0 <= value <= 100:
            return "denied", "seat_position", "seat_value_out_of_range", ()
        return self._control("seat_position", "set_seat_position", {"seat": seat, "axis": axis, "value": value})

    # ---- Cửa xe -----------------------------------------------------------

    def _match_door(self, text: str) -> MatchResult | None:
        """Sinh candidate mở/đóng cửa. Việc chặn khi xe đang chạy là của policy."""
        if "cửa" not in text or "cửa sổ" in text or "cửa kính" in text:
            return None
        if not self._starts_with_command(text, "mở", "đóng"):
            return None
        door = self._side(text)
        if door is None:
            return "clarify", "door_state", "missing_door_side", ()
        state = "closed" if self._starts_with_command(text, "đóng") else "open"
        return self._control("door_state", "set_door_state", {"door": door, "state": state})

    # ---- Dẫn đường --------------------------------------------------------

    def _match_navigation(self, text: str) -> MatchResult | None:
        if "dẫn đường" not in text:
            return None
        if self._starts_with_command(text, "hủy", "dừng", "tắt"):
            return self._control("navigation_cancel", "set_navigation", {"operation": "cancel"})
        if not self._starts_with_command(text, "dẫn đường"):
            return None
        if "trạm sạc" in text:
            destination_id = "poi-charge-01"
        elif "bình minh" in text or "thứ hai" in text:
            destination_id = "poi-cafe-02"
        elif "cà phê" in text or "cafe" in text:
            destination_id = "poi-cafe-01"
        else:
            return "clarify", "navigation_start", "unknown_local_destination", ()
        if self._poi_ids and destination_id not in self._poi_ids:
            return "denied", "navigation_start", "poi_not_in_fixture", ()
        return self._control(
            "navigation_start", "set_navigation", {"operation": "start", "destination_id": destination_id}
        )
```

Thêm helper `_side` vào phần Helper:

```python
    @staticmethod
    def _side(text: str) -> str | None:
        """`bên lái`/`ghế lái` → front_left; `bên phụ`/`ghế phụ` → front_right."""
        if "bên lái" in text or "ghế lái" in text or "sưởi lái" in text:
            return "front_left"
        if "bên phụ" in text or "ghế phụ" in text or "sưởi phụ" in text:
            return "front_right"
        if "sau bên trái" in text:
            return "rear_left"
        if "sau bên phải" in text:
            return "rear_right"
        return None
```

Khôi phục vòng lặp `_match` về đủ sáu matcher:

```python
        for matcher in (
            self._match_hvac,
            self._match_music,
            self._match_window,
            self._match_seat,
            self._match_door,
            self._match_navigation,
        ):
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q`
Expected: PASS — toàn bộ file

Nếu `"Hủy dẫn đường"` fail: `_match_navigation` kiểm `"dẫn đường" in text` trước rồi mới kiểm động từ hủy — đúng thứ tự đó, đừng đảo.

- [ ] **Step 5: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/router.py tests/test_agents/test_router.py
.\.venv\Scripts\python.exe -m ruff format src/agents/router.py tests/test_agents/test_router.py
git add src/agents/router.py tests/test_agents/test_router.py
git commit -m "feat(agent): router luat - cua so, ghe, cua xe, dan duong"
```

---

### Task 7: Node và StateGraph

**Files:**
- Modify: `src/agents/state.py`, `src/agents/graph.py`
- Create: `src/agents/nodes/normalize.py`, `route.py`, `validate.py`, `safety.py`, `execute.py`, `compose.py`
- Modify: `tests/test_agents/test_graph.py` (thay 2 test boilerplate)

**Interfaces:**
- Consumes: `DeterministicControlRouter` (5, 6), `materialize_action_plan`/`classify` (4), `VehicleSimulator` (3), `validate_args` (2), contracts (1), `rag_node` có sẵn tại `src/agents/nodes/rag_node.py`
- Produces:
  - `AgentState` mở rộng (`src/agents/state.py`)
  - `build_graph(vehicle: VehicleSimulator, *, router=None, rag=None, planner=None, checkpointer=None) -> CompiledStateGraph`
  - Node async: `normalize_node`, `route_node`, `validate_node`, `safety_node`, `execute_node`, `compose_node`
  - `OUTCOME_MESSAGES: dict[str, str]`

- [ ] **Step 1: Viết test thất bại**

Ghi đè `tests/test_agents/test_graph.py`:

```python
"""Graph lắp ráp. Mỗi test là một đường đi trọn vẹn từ câu tiếng Việt tới outcome."""

import pytest

from src.agents.graph import build_graph
from src.agents.vehicle import VehicleSimulator


async def _run(vehicle: VehicleSimulator, text: str, rag=None):
    graph = build_graph(vehicle, rag=rag)
    return await graph.ainvoke({"query": text, "session_id": "ses-1", "vehicle_id": "veh-1", "turn_id": "turn-1"})


async def test_s1_command_executes_directly():
    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Đặt điều hòa 22 độ")
    assert result["outcome"] == "completed"
    assert vehicle.state["hvac"]["temperature_c"] == 22
    assert vehicle.command_count == 1
    assert result["response_text"]


async def test_s2_stops_before_execution_in_this_branch():
    """Cửa sổ luôn S2. Branch này chưa có HITL nên dừng lại, tuyệt đối không chạy."""
    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Mở cửa sổ bên lái 30 phần trăm")
    assert result["outcome"] == "approval_required"
    assert vehicle.command_count == 0
    assert vehicle.state["windows"]["front_left"] == 0


async def test_s3_is_blocked_with_zero_side_effect():
    vehicle = VehicleSimulator.initial(speed_kph=45.0, gear="D")
    result = await _run(vehicle, "Mở cửa bên lái")
    assert result["outcome"] == "blocked"
    assert vehicle.command_count == 0
    assert vehicle.state["doors"]["front_left"] == "closed"


async def test_manual_question_reaches_rag_node():
    seen = {}

    async def fake_rag(state):
        seen["query"] = state["query"]
        return {"citations": [{"chunk_id": "c1"}], "evidence": [{"text": "..."}]}

    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Điều hòa hoạt động như thế nào?", rag=fake_rag)
    assert seen["query"] == "Điều hòa hoạt động như thế nào?"
    assert result["outcome"] == "grounded_answer"
    assert vehicle.command_count == 0


async def test_ambiguous_request_asks_for_clarification():
    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Đặt điều hòa")
    assert result["outcome"] == "clarify"
    assert vehicle.command_count == 0


async def test_denied_request_never_reaches_executor():
    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Đặt điều hòa 45 độ")
    assert result["outcome"] == "denied"
    assert vehicle.command_count == 0


async def test_state_carries_canonical_plan_not_alias():
    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Phát nhạc")
    assert result["action_plan"].steps[0].tool == "media_control"
    assert result["action_plan"].steps[0].safety_level == "S1"


async def test_graph_is_rebuilt_per_call_not_a_module_singleton():
    """Hai simulator độc lập không được dùng chung state."""
    first, second = VehicleSimulator.initial(), VehicleSimulator.initial()
    await _run(first, "Đặt điều hòa 22 độ")
    assert second.state["hvac"]["temperature_c"] == 27
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_graph.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_graph' from 'src.agents.graph'`

- [ ] **Step 3: Mở rộng state**

Ghi đè `src/agents/state.py`:

```python
from __future__ import annotations

from typing import Any, TypedDict

from src.agents.contracts import ActionPlan, CandidateActionPlan, RouteDecision, ToolResult


class AgentState(TypedDict, total=False):
    """State schema cho LangGraph agent.

    `total=False` nên mọi field là optional; node chỉ ghi phần nó sở hữu.
    Nhóm field RAG giữ nguyên tên cũ để `nodes/rag_node.py` không phải sửa.
    """

    # Ngữ cảnh phiên
    query: str
    session_id: str
    vehicle_id: str
    turn_id: str

    # Định tuyến
    normalized_text: str
    route_decision: RouteDecision
    route_source: str
    intent: str
    confidence: float

    # Kế hoạch
    vehicle_snapshot: dict[str, Any]
    vehicle_state_version: int
    candidate_action_plan: CandidateActionPlan
    action_plan: ActionPlan

    # Thực thi và kết quả
    outcome: str
    step_results: list[ToolResult]
    response_text: str
    error: str
    error_subcode: str

    # RAG sổ tay xe (giữ nguyên contract cũ)
    context: str
    analysis: str
    response: str
    metadata: dict
    evidence: list
    citations: list
    refusal_reason: str
```

- [ ] **Step 4: Viết sáu node**

`src/agents/nodes/normalize.py`:

```python
"""Chuẩn hóa input và chụp trạng thái xe cho lượt này."""

from src.agents.router import normalize_vi
from src.agents.state import AgentState
from src.agents.vehicle import VehicleSimulator


def make_normalize_node(vehicle: VehicleSimulator):
    async def normalize_node(state: AgentState) -> dict:
        snapshot = vehicle.snapshot()
        return {
            "normalized_text": normalize_vi(state.get("query", "")),
            "vehicle_snapshot": snapshot,
            "vehicle_state_version": snapshot["state_version"],
        }

    return normalize_node
```

`src/agents/nodes/route.py`:

```python
"""Định tuyến bằng luật. Không gọi model cho lệnh P0 rõ ràng."""

from src.agents.router import DeterministicControlRouter
from src.agents.state import AgentState


def make_route_node(router: DeterministicControlRouter):
    async def route_node(state: AgentState) -> dict:
        decision = router.route(state.get("query", ""))
        update = {
            "route_decision": decision,
            "route_source": decision.route_source,
            "intent": decision.intent,
            "confidence": decision.confidence,
            "outcome": decision.disposition,
        }
        if decision.candidate_plan is not None:
            update["candidate_action_plan"] = decision.candidate_plan
        return update

    return route_node
```

`src/agents/nodes/validate.py`:

```python
"""Validator chung: allowlist, schema, khoảng giá trị, và đồ thị phụ thuộc.

Chạy **trước** phân loại S0-S3. Tool lạ hay args sai là `validation_denied`,
không phải S3 (`docs/safety_and_hitl.md` mục Core invariants).
"""

from src.agents.contracts import ValidationDenied
from src.agents.state import AgentState
from src.agents.tools import validate_args


async def validate_node(state: AgentState) -> dict:
    candidate = state["candidate_action_plan"]
    seen: set[str] = set()
    for step in candidate.steps:
        try:
            validate_args(step.tool, step.args)
        except ValidationDenied as exc:
            return {"outcome": "validation_denied", "error": exc.message, "error_subcode": exc.subcode}
        if not set(step.depends_on) <= seen:
            return {
                "outcome": "validation_denied",
                "error": f"step {step.step_id} phụ thuộc vào step chưa xuất hiện trước nó",
                "error_subcode": "args_invalid",
            }
        seen.add(step.step_id)
    return {"outcome": "validated"}
```

`src/agents/nodes/safety.py`:

```python
"""Materialize `ActionPlan` và phân loại S0-S3. Đây là node duy nhất gọi policy."""

from src.agents.policy import materialize_action_plan
from src.agents.state import AgentState


async def safety_node(state: AgentState) -> dict:
    plan = materialize_action_plan(
        state["candidate_action_plan"],
        state["vehicle_snapshot"],
        state.get("session_id", "ses-unknown"),
        state.get("vehicle_id", "veh-unknown"),
    )
    if any(step.safety_level == "S3" for step in plan.steps):
        return {"action_plan": plan, "outcome": "blocked"}
    if plan.requires_approval:
        # Branch này chưa có HITL. Dừng ở đây là fail-closed, không phải bỏ sót:
        # `feature/hitl-safety-confirmation` sẽ cắm node request_approval vào đúng chỗ.
        return {"action_plan": plan, "outcome": "approval_required"}
    return {"action_plan": plan, "outcome": "safe"}
```

`src/agents/nodes/execute.py`:

```python
"""Executor tuần tự, fail-fast, dùng rolling expected_state_version."""

from src.agents.contracts import ToolResult
from src.agents.state import AgentState
from src.agents.vehicle import VehicleSimulator


def make_execute_node(vehicle: VehicleSimulator):
    async def execute_node(state: AgentState) -> dict:
        plan = state["action_plan"]
        expected_version = plan.vehicle_state_version
        results: list[ToolResult] = []
        completed: set[str] = set()

        for step in plan.steps:
            if not set(step.depends_on) <= completed:
                results.append(
                    ToolResult(
                        command_id=f"{plan.plan_id}:{step.step_id}",
                        step_id=step.step_id,
                        tool=step.tool,
                        args=step.args,
                        status="skipped",
                        before=vehicle.snapshot(),
                        after=vehicle.snapshot(),
                        error_code="skipped_due_to_prior_failure",
                    )
                )
                continue
            result = vehicle.execute(f"{plan.plan_id}:{step.step_id}", expected_version, step.tool, step.args)
            results.append(result)
            if result.status != "completed":
                break
            completed.add(step.step_id)
            expected_version = vehicle.state["state_version"]

        done = len(results) == len(plan.steps) and all(r.status == "completed" for r in results)
        return {"step_results": results, "outcome": "completed" if done else "execution_failed"}

    return execute_node
```

`src/agents/nodes/compose.py`:

```python
"""Composer: chỉ báo cáo outcome đã verify. Không suy đoán thành công."""

from src.agents.state import AgentState

OUTCOME_MESSAGES: dict[str, str] = {
    "completed": "Đã thực hiện lệnh trên xe mô phỏng.",
    "execution_failed": "Không thực hiện được đầy đủ lệnh; xem chi tiết từng bước.",
    "blocked": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép.",
    "approval_required": "Lệnh này cần bạn xác nhận trước khi thực hiện.",
    "clarify": "Bạn muốn điều chỉnh cụ thể như thế nào?",
    "denied": "Xin lỗi, tôi không thực hiện được yêu cầu này.",
    "validation_denied": "Yêu cầu không hợp lệ nên tôi chưa thực hiện.",
    "not_control": "Tôi chưa rõ bạn muốn điều khiển gì.",
    "grounded_answer": "Đây là thông tin tôi tìm được trong sổ tay xe.",
    "grounded_refusal": "Tôi không tìm thấy thông tin này trong sổ tay xe.",
}


async def compose_node(state: AgentState) -> dict:
    outcome = state.get("outcome", "not_control")
    return {"response_text": OUTCOME_MESSAGES.get(outcome, "Đã xử lý yêu cầu."), "response": OUTCOME_MESSAGES.get(outcome, "")}
```

- [ ] **Step 5: Lắp graph**

Ghi đè `src/agents/graph.py`:

```python
"""StateGraph của agent VIVI.

Định tuyến ưu tiên luật theo `docs/agent_spec.md`. Mọi phụ thuộc đều inject
được — không có singleton mức module, vì test cần nhiều simulator độc lập
trong cùng một tiến trình.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from src.agents.nodes.compose import compose_node
from src.agents.nodes.execute import make_execute_node
from src.agents.nodes.normalize import make_normalize_node
from src.agents.nodes.route import make_route_node
from src.agents.nodes.safety import safety_node
from src.agents.nodes.validate import validate_node
from src.agents.router import DeterministicControlRouter
from src.agents.state import AgentState
from src.agents.vehicle import VehicleSimulator

RagNode = Callable[[AgentState], Any]


def _route_after_routing(state: AgentState) -> str:
    outcome = state.get("outcome")
    if outcome == "control":
        return "validate"
    if outcome == "not_control" and state.get("intent") == "manual_query":
        return "rag"
    return "compose"


def _route_after_validate(state: AgentState) -> str:
    return "safety" if state.get("outcome") == "validated" else "compose"


def _route_after_safety(state: AgentState) -> str:
    return "execute" if state.get("outcome") == "safe" else "compose"


def build_graph(
    vehicle: VehicleSimulator,
    *,
    router: DeterministicControlRouter | None = None,
    rag: RagNode | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Dựng graph cho một phiên. `rag=None` thì nhánh sổ tay dùng node thật.

    Import `rag_node` bị hoãn tới **lúc nhánh sổ tay thực sự chạy**, không phải
    lúc dựng graph. Nó kéo theo `src.rag` → `faiss`/`bs4`; nếu import sớm thì
    một checkout thiếu extra RAG sẽ không dựng nổi graph, và cả `src.main` sập
    theo. Câu lệnh điều khiển không cần RAG nên không được trả giá đó.
    """

    async def rag_stage(state: AgentState) -> dict:
        if rag is None:
            from src.agents.nodes.rag_node import rag_node

            rag_impl: RagNode = rag_node
        else:
            rag_impl = rag
        update = dict(await rag_impl(state))
        if update.get("refusal_reason"):
            update["outcome"] = "grounded_refusal"
        elif update.get("error"):
            update["outcome"] = "validation_denied"
        else:
            update["outcome"] = "grounded_answer"
        return update

    builder = StateGraph(AgentState)
    builder.add_node("normalize", make_normalize_node(vehicle))
    builder.add_node("route", make_route_node(router or DeterministicControlRouter()))
    builder.add_node("validate", validate_node)
    builder.add_node("safety", safety_node)
    builder.add_node("execute", make_execute_node(vehicle))
    builder.add_node("rag", rag_stage)
    builder.add_node("compose", compose_node)

    builder.add_edge(START, "normalize")
    builder.add_edge("normalize", "route")
    builder.add_conditional_edges("route", _route_after_routing, {"validate": "validate", "rag": "rag", "compose": "compose"})
    builder.add_conditional_edges("validate", _route_after_validate, {"safety": "safety", "compose": "compose"})
    builder.add_conditional_edges("safety", _route_after_safety, {"execute": "execute", "compose": "compose"})
    builder.add_edge("rag", "compose")
    builder.add_edge("execute", "compose")
    builder.add_edge("compose", END)
    return builder.compile(checkpointer=checkpointer)
```

- [ ] **Step 6: Xóa boilerplate không còn dùng**

`src/agents/nodes/example_node.py` và `src/agents/tools/example_tool.py` không còn ai gọi sau khi `graph.py` bị thay. Xóa cả hai. `src/api/routes.py` đang `from src.agents.graph import agent` — sửa thành dựng graph trong request (Task 10 làm route mới; ở bước này chỉ cần giữ `/chat` chạy được):

Sửa `src/api/routes.py` dòng 3 và hàm `chat`:

```python
from src.agents.graph import build_graph
from src.agents.vehicle import VehicleSimulator

_vehicle = VehicleSimulator.initial()
_agent = build_graph(_vehicle)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat với AI agent."""
    try:
        result = await _agent.ainvoke({"query": request.message, "session_id": "ses-chat", "vehicle_id": "veh-demo"})
        return ChatResponse(response=result.get("response_text", ""), analysis=result.get("outcome", ""))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
```

- [ ] **Step 7: Chạy toàn bộ suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS — toàn bộ, kể cả `tests/test_api/test_routes.py` cũ

Nếu `test_routes.py` cũ assert nội dung `analysis` là f-string boilerplate thì cập nhật assert đó cho khớp contract mới, và ghi lý do trong commit message.

- [ ] **Step 8: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/ tests/
.\.venv\Scripts\python.exe -m ruff format src/ tests/
git add -A src/agents tests/test_agents src/api/routes.py
git commit -m "feat(agent): StateGraph 7 node voi dinh tuyen uu tien luat"
```

---

### Task 8: SLM planner — Qwen làm fallback

**Files:**
- Create: `src/agents/slm.py`
- Modify: `src/agents/graph.py`, `src/config.py`
- Test: `tests/test_agents/test_slm.py`

**Interfaces:**
- Consumes: `CandidateActionPlan` (1), `validate_args` (2), `build_graph` (7)
- Produces:
  - `Planner` Protocol với `propose(normalized_text: str, snapshot: dict) -> str` (trả JSON thô)
  - `QwenPlanner(endpoint: str, model_id: str, timeout_s: float)`
  - `parse_candidate(raw: str) -> CandidateActionPlan` — raise `SlmSchemaError`
  - `SlmSchemaError(Exception)`
  - `build_graph(..., planner: Planner | None = None)`
  - Settings mới: `slm_enabled: bool = False`, `slm_endpoint: str`, `slm_model_id: str`, `slm_timeout_s: float`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_slm.py`:

```python
"""SLM là fallback, không phải planner chính. Nó không được chạm tới safety."""

import pytest

from src.agents.graph import build_graph
from src.agents.slm import SlmSchemaError, parse_candidate
from src.agents.vehicle import VehicleSimulator


class StubPlanner:
    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.calls: list[str] = []

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        self.calls.append(normalized_text)
        return self._replies.pop(0) if self._replies else "{}"


VALID = '{"schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,"tool":"set_hvac_power","args":{"enabled":true}}]}'
WITH_SAFETY = '{"schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,"tool":"set_hvac_power","args":{"enabled":true},"safety_level":"S1"}]}'


def test_parse_accepts_valid_candidate():
    candidate = parse_candidate(VALID)
    assert candidate.steps[0].tool == "set_hvac_power"


def test_parse_rejects_planner_supplied_safety_level():
    """agent_spec.md: SLM cấp safety_level thì fail ngay closed-schema check."""
    with pytest.raises(SlmSchemaError):
        parse_candidate(WITH_SAFETY)


def test_parse_rejects_non_json():
    with pytest.raises(SlmSchemaError):
        parse_candidate("Tôi nghĩ bạn muốn bật điều hòa")


def test_parse_rejects_tool_outside_allowlist():
    with pytest.raises(SlmSchemaError):
        parse_candidate('{"schema_version":"1.0","steps":[{"step_id":"s","ordinal":0,"tool":"set_engine_off","args":{}}]}')


async def test_graph_falls_back_to_planner_on_ambiguous_input():
    planner = StubPlanner(VALID)
    vehicle = VehicleSimulator.initial()
    graph = build_graph(vehicle, planner=planner)
    result = await graph.ainvoke({"query": "Làm cho tôi dễ chịu hơn đi", "session_id": "s", "vehicle_id": "v"})
    assert planner.calls, "planner phải được gọi cho câu không khớp luật nào"
    assert result["route_source"] == "slm"
    assert result["outcome"] == "completed"


async def test_planner_gets_exactly_one_repair_attempt():
    planner = StubPlanner("không phải json", VALID)
    vehicle = VehicleSimulator.initial()
    graph = build_graph(vehicle, planner=planner)
    result = await graph.ainvoke({"query": "Làm cho tôi dễ chịu hơn đi", "session_id": "s", "vehicle_id": "v"})
    assert len(planner.calls) == 2
    assert result["outcome"] == "completed"


async def test_two_failures_end_in_clarify_not_a_third_attempt():
    planner = StubPlanner("hỏng", "vẫn hỏng")
    vehicle = VehicleSimulator.initial()
    graph = build_graph(vehicle, planner=planner)
    result = await graph.ainvoke({"query": "Làm cho tôi dễ chịu hơn đi", "session_id": "s", "vehicle_id": "v"})
    assert len(planner.calls) == 2
    assert result["outcome"] == "clarify"
    assert vehicle.command_count == 0


async def test_no_planner_means_ambiguous_goes_straight_to_clarify():
    vehicle = VehicleSimulator.initial()
    graph = build_graph(vehicle)
    result = await graph.ainvoke({"query": "Làm cho tôi dễ chịu hơn đi", "session_id": "s", "vehicle_id": "v"})
    assert result["outcome"] == "not_control"
    assert vehicle.command_count == 0
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.slm'`

- [ ] **Step 3: Viết slm.py**

Tạo `src/agents/slm.py`:

```python
"""Planner SLM — chỉ cho câu mơ hồ hoặc hiếm.

Vai trò của Qwen2.5-3B q4 ở đây là **fallback**, không phải planner chính:
`docs/agent_spec.md` chốt định tuyến ưu tiên luật, và SPIKE-001 kết luận
**Not Yet** cho cả hai ứng viên Q4 (fail hard gate). Xem ADR-010.

Vòng đời cứng, không có vòng lặp: đề xuất → kiểm schema → **đúng một** lần sửa
schema → nếu vẫn hỏng thì hỏi lại. Không ReAct, không retry mở.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import ValidationError

from src.agents.contracts import CandidateActionPlan, ValidationDenied
from src.agents.tools import TOOL_ARGS, validate_args

_ALLOWED_TOOLS = ", ".join(sorted(TOOL_ARGS))

SYSTEM_PROMPT = f"""Bạn là bộ lập kế hoạch cho trợ lý trong xe. Chỉ trả về JSON đúng schema:
{{"schema_version":"1.0","steps":[{{"step_id":"step-1","ordinal":0,"tool":"<tên tool>","args":{{}},"depends_on":[]}}]}}
Tool hợp lệ: {_ALLOWED_TOOLS}
Tuyệt đối không thêm trường "safety_level", "plan_id" hay "requires_approval".
Không giải thích, không văn bản ngoài JSON."""


class SlmSchemaError(Exception):
    """Output của SLM không qua được closed-schema check."""


class Planner(Protocol):
    def propose(self, normalized_text: str, snapshot: dict[str, Any]) -> str: ...


def parse_candidate(raw: str) -> CandidateActionPlan:
    """Kiểm schema đóng. Thừa trường (kể cả `safety_level`) là hỏng, không phải cảnh báo."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SlmSchemaError(f"output không phải JSON: {exc}") from exc
    try:
        candidate = CandidateActionPlan.model_validate(payload)
    except ValidationError as exc:
        raise SlmSchemaError(f"output sai schema: {exc.errors()[0]['msg']}") from exc
    for step in candidate.steps:
        try:
            validate_args(step.tool, step.args)
        except ValidationDenied as exc:
            raise SlmSchemaError(exc.message) from exc
    return candidate


class QwenPlanner:
    """Client llama-server cục bộ. Không tự tải model, không gọi cloud.

    Chưa có bằng chứng chạy weight thật trong sprint này — mọi test dùng stub.
    """

    def __init__(self, endpoint: str, model_id: str, timeout_s: float = 8.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._timeout_s = timeout_s

    def propose(self, normalized_text: str, snapshot: dict[str, Any]) -> str:
        import httpx

        prompt = f"{SYSTEM_PROMPT}\n\nTrạng thái xe: {json.dumps(snapshot, ensure_ascii=False)}\nYêu cầu: {normalized_text}\nJSON:"
        response = httpx.post(
            f"{self._endpoint}/completion",
            json={"prompt": prompt, "temperature": 0.0, "n_predict": 256, "stop": ["\n\n"]},
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return str(response.json().get("content", "")).strip()
```

- [ ] **Step 4: Nối planner vào graph**

Trong `src/agents/graph.py`, thêm import và node:

```python
from src.agents.slm import Planner, SlmSchemaError, parse_candidate
```

Thêm vào `build_graph` (trước khi dựng `builder`):

```python
    async def slm_stage(state: AgentState) -> dict:
        """Đề xuất → kiểm schema → đúng một lần sửa → hết thì hỏi lại."""
        if planner is None:
            return {"outcome": "not_control", "route_source": "fallback"}
        snapshot = state["vehicle_snapshot"]
        text = state.get("normalized_text", "")
        for attempt in range(2):
            try:
                raw = planner.propose(text if attempt == 0 else f"{text}\n{REPAIR_HINT}", snapshot)
                candidate = parse_candidate(raw)
            except (SlmSchemaError, OSError):
                continue
            return {"candidate_action_plan": candidate, "outcome": "control", "route_source": "slm"}
        return {"outcome": "clarify", "route_source": "fallback"}
```

Thêm hằng số ở đầu `graph.py`:

```python
REPAIR_HINT = "JSON trước không hợp lệ. Trả lại đúng một object JSON theo schema."
```

Đổi `_route_after_routing` để câu không khớp luật đi qua SLM:

```python
def _route_after_routing(state: AgentState) -> str:
    outcome = state.get("outcome")
    if outcome == "control":
        return "validate"
    if state.get("intent") == "manual_query":
        return "rag"
    if outcome == "not_control":
        return "slm"
    return "compose"


def _route_after_slm(state: AgentState) -> str:
    return "validate" if state.get("outcome") == "control" else "compose"
```

Thêm tham số và node:

```python
def build_graph(
    vehicle: VehicleSimulator,
    *,
    router: DeterministicControlRouter | None = None,
    rag: RagNode | None = None,
    planner: Planner | None = None,
    checkpointer: Any | None = None,
) -> Any:
```

```python
    builder.add_node("slm", slm_stage)
    builder.add_conditional_edges(
        "route", _route_after_routing, {"validate": "validate", "rag": "rag", "slm": "slm", "compose": "compose"}
    )
    builder.add_conditional_edges("slm", _route_after_slm, {"validate": "validate", "compose": "compose"})
```

- [ ] **Step 5: Thêm settings**

Thêm vào `src/config.py`, ngay sau khối `# LLM`:

```python
    # SLM planner — Qwen2.5-3B q4 là fallback cho câu mơ hồ, KHÔNG phải planner
    # chính. Xem ADR-010 và docs/agent_spec.md. Mặc định tắt: sprint này chưa có
    # bằng chứng chạy weight thật, và test không được phụ thuộc model.
    slm_enabled: bool = False
    slm_endpoint: str = "http://127.0.0.1:8080"
    slm_model_id: str = "qwen2.5-3b-instruct-q4_k_m"
    slm_timeout_s: float = Field(default=8.0, gt=0.0)
```

- [ ] **Step 6: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS toàn bộ

Nếu `test_no_planner_means_ambiguous_goes_straight_to_clarify` cho `outcome == "not_control"`: đúng như assert đã viết — không planner thì `slm_stage` trả `not_control` rồi đi `compose`.

- [ ] **Step 7: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/ tests/
.\.venv\Scripts\python.exe -m ruff format src/ tests/
git add src/agents/slm.py src/agents/graph.py src/config.py tests/test_agents/test_slm.py
git commit -m "feat(agent): Qwen2.5-3B q4 lam fallback voi dung mot lan sua schema"
```

---

### Task 9: Dataset v3 + runner đo AC

**Files:**
- Create: `eval/datasets/agent/v3/cases.jsonl`, `eval/datasets/agent/v3/README.md`, `src/agents/eval.py`
- Test: `tests/test_agents/test_eval.py`

**Interfaces:**
- Consumes: `DeterministicControlRouter` (5, 6)
- Produces:
  - `load_cases(path: Path) -> list[dict]`
  - `score_case(router, case) -> dict` với khóa `case_id`, `intent_ok`, `disposition_ok`, `tool_exact`, `predicted`, `expected`
  - `run_eval(dataset: Path, results_root: Path) -> Path` — trả về thư mục run vừa tạo
  - CLI: `python -m src.agents.eval`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_eval.py`:

```python
"""Runner sinh bằng chứng. Thư mục kết quả bất biến — đó là điểm quan trọng nhất."""

import json

import pytest

from src.agents.eval import load_cases, run_eval, score_case
from src.agents.router import DeterministicControlRouter

CASE = {
    "case_id": "T-001",
    "domain": "hvac",
    "input_text": "Đặt điều hòa 24 độ",
    "expected": {
        "disposition": "control",
        "intent": "hvac_temperature",
        "tools": [{"tool": "set_hvac_temperature", "args": {"temperature_c": 24}}],
    },
}


def _write_dataset(tmp_path, cases):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    return path


def test_load_cases_reads_jsonl(tmp_path):
    assert len(load_cases(_write_dataset(tmp_path, [CASE, CASE]))) == 2


def test_score_case_marks_full_match():
    scored = score_case(DeterministicControlRouter(), CASE)
    assert scored["disposition_ok"] is True
    assert scored["intent_ok"] is True
    assert scored["tool_exact"] is True


def test_score_case_marks_wrong_args_as_not_exact():
    wrong = json.loads(json.dumps(CASE))
    wrong["expected"]["tools"][0]["args"]["temperature_c"] = 30
    scored = score_case(DeterministicControlRouter(), wrong)
    assert scored["disposition_ok"] is True
    assert scored["tool_exact"] is False


def test_run_eval_writes_immutable_run_directory(tmp_path):
    dataset = _write_dataset(tmp_path, [CASE])
    run_dir = run_eval(dataset, tmp_path / "results")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["total"] == 1
    assert metrics["intent_accuracy"] == 1.0
    assert metrics["tool_exact"] == 1.0
    assert (run_dir / "case_results.jsonl").exists()
    assert (run_dir / "manifest.json").exists()


def test_run_eval_refuses_to_overwrite_an_existing_run(tmp_path):
    dataset = _write_dataset(tmp_path, [CASE])
    run_dir = run_eval(dataset, tmp_path / "results")
    with pytest.raises(FileExistsError):
        run_eval(dataset, tmp_path / "results", run_id=run_dir.name)


def test_metrics_break_down_by_domain(tmp_path):
    dataset = _write_dataset(tmp_path, [CASE])
    run_dir = run_eval(dataset, tmp_path / "results")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["by_domain"]["hvac"]["total"] == 1
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.eval'`

- [ ] **Step 3: Viết runner**

Tạo `src/agents/eval.py`:

```python
"""Đo intent accuracy và tool-exact của router, ghi ra thư mục run bất biến.

Vì sao không dùng test pass làm bằng chứng: `CLAUDE.md` ghi rõ "Passing unit
tests are not model-quality evidence. Claims must trace to a run ID." Con số
trong README/WORKLOG phải kèm run-id sinh ra nó.

Chạy: `.\\.venv\\Scripts\\python.exe -m src.agents.eval`
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents.router import DeterministicControlRouter

DEFAULT_DATASET = Path("eval/datasets/agent/v3/cases.jsonl")
DEFAULT_RESULTS_ROOT = Path("eval/results/agent-intent")


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score_case(router: DeterministicControlRouter, case: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected"]
    decision = router.route(case["input_text"])
    predicted_tools = (
        [{"tool": step.tool, "args": step.args} for step in decision.candidate_plan.steps]
        if decision.candidate_plan is not None
        else []
    )
    disposition_ok = decision.disposition == expected["disposition"]
    intent_ok = disposition_ok and decision.intent == expected["intent"]
    return {
        "case_id": case["case_id"],
        "domain": case.get("domain", "unknown"),
        "input_text": case["input_text"],
        "disposition_ok": disposition_ok,
        "intent_ok": intent_ok,
        "tool_exact": predicted_tools == expected.get("tools", []),
        "predicted": {"disposition": decision.disposition, "intent": decision.intent, "reason": decision.reason, "tools": predicted_tools},
        "expected": expected,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_domain: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "intent_ok": 0, "tool_exact": 0})
    for row in rows:
        bucket = by_domain[row["domain"]]
        bucket["total"] += 1
        bucket["intent_ok"] += int(row["intent_ok"])
        bucket["tool_exact"] += int(row["tool_exact"])
    total = len(rows) or 1
    return {
        "total": len(rows),
        "intent_accuracy": sum(r["intent_ok"] for r in rows) / total,
        "disposition_accuracy": sum(r["disposition_ok"] for r in rows) / total,
        "tool_exact": sum(r["tool_exact"] for r in rows) / total,
        "by_domain": {k: dict(v) for k, v in sorted(by_domain.items())},
    }


def run_eval(dataset: Path, results_root: Path, run_id: str | None = None) -> Path:
    """Chạy toàn bộ dataset và ghi một thư mục run mới.

    Thư mục là **bất biến**: `mkdir(exist_ok=False)` và mở file bằng mode `"x"`.
    Muốn số mới thì chạy lại, không sửa file cũ.
    """
    cases = load_cases(dataset)
    router = DeterministicControlRouter()
    rows = [score_case(router, case) for case in cases]
    metrics = _aggregate(rows)

    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "run_id": run_id,
                "dataset": str(dataset).replace("\\", "/"),
                "case_count": len(cases),
                "router": "DeterministicControlRouter",
                "slm_used": False,
                "note": "Router luật, không gọi model. Không phải bằng chứng chất lượng SLM.",
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir


def main() -> None:
    run_dir = run_eval(DEFAULT_DATASET, DEFAULT_RESULTS_ROOT)
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    print(f"run_id={run_dir.name}")
    print(f"intent_accuracy={metrics['intent_accuracy']:.4f}  tool_exact={metrics['tool_exact']:.4f}  n={metrics['total']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval.py -q`
Expected: PASS — 6 passed

- [ ] **Step 5: Viết dataset v3**

Tạo `eval/datasets/agent/v3/cases.jsonl` với đúng 60 dòng dưới đây, không thêm dòng trống, encoding UTF-8, kết thúc dòng LF.

Case 1–30 port từ `eval/datasets/poc/v2/cases.jsonl` (branch `feature/hybrid-architecture-resident-pipeline`, commit `c76c7ee`) — args đã viết lại sang tên canonical và mọi case đã được gắn thêm nhãn `intent`. Case 31–60 viết mới.

```jsonl
{"case_id":"A3-AC-001","domain":"hvac","input_text":"Bật điều hòa","expected":{"disposition":"control","intent":"hvac_power","tools":[{"tool":"set_hvac_power","args":{"enabled":true}}]}}
{"case_id":"A3-AC-002","domain":"hvac","input_text":"Tắt điều hòa","expected":{"disposition":"control","intent":"hvac_power","tools":[{"tool":"set_hvac_power","args":{"enabled":false}}]}}
{"case_id":"A3-AC-003","domain":"hvac","input_text":"Đặt điều hòa 24 độ","expected":{"disposition":"control","intent":"hvac_temperature","tools":[{"tool":"set_hvac_temperature","args":{"temperature_c":24}}]}}
{"case_id":"A3-AC-004","domain":"hvac","input_text":"Tăng nhiệt độ lên 26 độ","expected":{"disposition":"control","intent":"hvac_temperature","tools":[{"tool":"set_hvac_temperature","args":{"temperature_c":26}}]}}
{"case_id":"A3-MUSIC-001","domain":"music","input_text":"Phát nhạc","expected":{"disposition":"control","intent":"media_playback","tools":[{"tool":"media_control","args":{"action":"play"}}]}}
{"case_id":"A3-MUSIC-002","domain":"music","input_text":"Tạm dừng nhạc","expected":{"disposition":"control","intent":"media_playback","tools":[{"tool":"media_control","args":{"action":"pause"}}]}}
{"case_id":"A3-MUSIC-003","domain":"music","input_text":"Đặt âm lượng 40","expected":{"disposition":"control","intent":"media_volume","tools":[{"tool":"media_control","args":{"action":"set_volume","volume":40}}]}}
{"case_id":"A3-MUSIC-004","domain":"music","input_text":"Giảm âm lượng xuống 20","expected":{"disposition":"control","intent":"media_volume","tools":[{"tool":"media_control","args":{"action":"set_volume","volume":20}}]}}
{"case_id":"A3-WIN-001","domain":"window","input_text":"Mở cửa sổ bên phụ một nửa","expected":{"disposition":"control","intent":"window_position","tools":[{"tool":"set_window_position","args":{"window":"front_right","percent":50}}]}}
{"case_id":"A3-WIN-002","domain":"window","input_text":"Đóng cửa sổ bên lái","expected":{"disposition":"control","intent":"window_position","tools":[{"tool":"set_window_position","args":{"window":"front_left","percent":0}}]}}
{"case_id":"A3-WIN-003","domain":"window","input_text":"Mở cửa sổ bên lái 30 phần trăm","expected":{"disposition":"control","intent":"window_position","tools":[{"tool":"set_window_position","args":{"window":"front_left","percent":30}}]}}
{"case_id":"A3-WIN-004","domain":"window","input_text":"Mở hết cửa sổ bên phụ","expected":{"disposition":"control","intent":"window_position","tools":[{"tool":"set_window_position","args":{"window":"front_right","percent":100}}]}}
{"case_id":"A3-SEAT-001","domain":"seat","input_text":"Bật sưởi ghế lái mức 2","expected":{"disposition":"control","intent":"seat_heating","tools":[{"tool":"set_seat_heating","args":{"seat":"front_left","level":2}}]}}
{"case_id":"A3-SEAT-002","domain":"seat","input_text":"Bật sưởi ghế phụ mức 1","expected":{"disposition":"control","intent":"seat_heating","tools":[{"tool":"set_seat_heating","args":{"seat":"front_right","level":1}}]}}
{"case_id":"A3-SEAT-003","domain":"seat","input_text":"Tắt sưởi ghế lái","expected":{"disposition":"control","intent":"seat_heating","tools":[{"tool":"set_seat_heating","args":{"seat":"front_left","level":0}}]}}
{"case_id":"A3-SEAT-004","domain":"seat","input_text":"Đặt sưởi ghế phụ mức 3","expected":{"disposition":"control","intent":"seat_heating","tools":[{"tool":"set_seat_heating","args":{"seat":"front_right","level":3}}]}}
{"case_id":"A3-NAV-001","domain":"navigation","input_text":"Dẫn đường đến quán cà phê thứ nhất","expected":{"disposition":"control","intent":"navigation_start","tools":[{"tool":"set_navigation","args":{"operation":"start","destination_id":"poi-cafe-01"}}]}}
{"case_id":"A3-NAV-002","domain":"navigation","input_text":"Dẫn đường đến Cà phê Bình Minh","expected":{"disposition":"control","intent":"navigation_start","tools":[{"tool":"set_navigation","args":{"operation":"start","destination_id":"poi-cafe-02"}}]}}
{"case_id":"A3-NAV-003","domain":"navigation","input_text":"Dẫn đường đến quán cà phê gần nhất","expected":{"disposition":"control","intent":"navigation_start","tools":[{"tool":"set_navigation","args":{"operation":"start","destination_id":"poi-cafe-01"}}]}}
{"case_id":"A3-NAV-004","domain":"navigation","input_text":"Dẫn đường đến trạm sạc","expected":{"disposition":"control","intent":"navigation_start","tools":[{"tool":"set_navigation","args":{"operation":"start","destination_id":"poi-charge-01"}}]}}
{"case_id":"A3-GUARD-NEG-001","domain":"window","input_text":"Đừng mở cửa sổ bên lái","expected":{"disposition":"denied","intent":"none","tools":[]}}
{"case_id":"A3-GUARD-NEG-002","domain":"music","input_text":"Không phát nhạc","expected":{"disposition":"denied","intent":"none","tools":[]}}
{"case_id":"A3-GUARD-AMB-001","domain":"ambiguous","input_text":"Mở nó ra","expected":{"disposition":"clarify","intent":"none","tools":[]}}
{"case_id":"A3-GUARD-AMB-002","domain":"ambiguous","input_text":"Đặt thấp hơn","expected":{"disposition":"clarify","intent":"none","tools":[]}}
{"case_id":"A3-GUARD-RAG-001","domain":"manual","input_text":"Điều hòa hoạt động như thế nào?","expected":{"disposition":"not_control","intent":"manual_query","tools":[]}}
{"case_id":"A3-GUARD-RAG-002","domain":"manual","input_text":"Cửa sổ bị kẹt thì xử lý thế nào?","expected":{"disposition":"not_control","intent":"manual_query","tools":[]}}
{"case_id":"A3-GUARD-RANGE-001","domain":"hvac","input_text":"Đặt điều hòa 45 độ","expected":{"disposition":"denied","intent":"hvac_temperature","tools":[]}}
{"case_id":"A3-GUARD-RANGE-002","domain":"music","input_text":"Đặt âm lượng 150","expected":{"disposition":"denied","intent":"media_volume","tools":[]}}
{"case_id":"A3-GUARD-DOOR-001","domain":"door","input_text":"Mở cửa xe","expected":{"disposition":"clarify","intent":"door_state","tools":[]}}
{"case_id":"A3-GUARD-UNSAFE-001","domain":"unsafe","input_text":"Tắt phanh ABS","expected":{"disposition":"denied","intent":"none","tools":[]}}
{"case_id":"A3-SEATPOS-001","domain":"seat","input_text":"Ngả lưng ghế lái 70 phần trăm","expected":{"disposition":"control","intent":"seat_position","tools":[{"tool":"set_seat_position","args":{"seat":"front_left","axis":"recline","value":70}}]}}
{"case_id":"A3-SEATPOS-002","domain":"seat","input_text":"Đẩy ghế phụ về trước 30 phần trăm","expected":{"disposition":"control","intent":"seat_position","tools":[{"tool":"set_seat_position","args":{"seat":"front_right","axis":"fore_aft","value":30}}]}}
{"case_id":"A3-SEATPOS-003","domain":"seat","input_text":"Ngả lưng ghế lái","expected":{"disposition":"clarify","intent":"seat_position","tools":[]}}
{"case_id":"A3-SEATPOS-004","domain":"seat","input_text":"Ngả lưng ghế 50 phần trăm","expected":{"disposition":"clarify","intent":"seat_position","tools":[]}}
{"case_id":"A3-DOOR-001","domain":"door","input_text":"Mở cửa bên lái","expected":{"disposition":"control","intent":"door_state","tools":[{"tool":"set_door_state","args":{"door":"front_left","state":"open"}}]}}
{"case_id":"A3-DOOR-002","domain":"door","input_text":"Đóng cửa bên phụ","expected":{"disposition":"control","intent":"door_state","tools":[{"tool":"set_door_state","args":{"door":"front_right","state":"closed"}}]}}
{"case_id":"A3-DOOR-003","domain":"door","input_text":"Mở cửa sau bên trái","expected":{"disposition":"control","intent":"door_state","tools":[{"tool":"set_door_state","args":{"door":"rear_left","state":"open"}}]}}
{"case_id":"A3-DOOR-004","domain":"door","input_text":"Đóng cửa","expected":{"disposition":"clarify","intent":"door_state","tools":[]}}
{"case_id":"A3-NAV-005","domain":"navigation","input_text":"Hủy dẫn đường","expected":{"disposition":"control","intent":"navigation_cancel","tools":[{"tool":"set_navigation","args":{"operation":"cancel"}}]}}
{"case_id":"A3-NAV-006","domain":"navigation","input_text":"Dẫn đường đến Hà Nội","expected":{"disposition":"clarify","intent":"navigation_start","tools":[]}}
{"case_id":"A3-NAV-007","domain":"navigation","input_text":"Dẫn đường về nhà","expected":{"disposition":"clarify","intent":"navigation_start","tools":[]}}
{"case_id":"A3-KI001-001","domain":"hvac","input_text":"Bật điều hòa lên 25 độ","expected":{"disposition":"control","intent":"hvac_temperature","tools":[{"tool":"set_hvac_power","args":{"enabled":true}},{"tool":"set_hvac_temperature","args":{"temperature_c":25}}]}}
{"case_id":"A3-KI001-002","domain":"hvac","input_text":"Bật điều hòa lên 45 độ","expected":{"disposition":"denied","intent":"hvac_temperature","tools":[]}}
{"case_id":"A3-KI001-003","domain":"hvac","input_text":"Bật điều hòa lên 16 độ","expected":{"disposition":"control","intent":"hvac_temperature","tools":[{"tool":"set_hvac_power","args":{"enabled":true}},{"tool":"set_hvac_temperature","args":{"temperature_c":16}}]}}
{"case_id":"A3-NUM-001","domain":"hvac","input_text":"Chỉnh điều hòa hai mươi tư độ","expected":{"disposition":"control","intent":"hvac_temperature","tools":[{"tool":"set_hvac_temperature","args":{"temperature_c":24}}]}}
{"case_id":"A3-NUM-002","domain":"music","input_text":"Đặt âm lượng ba mươi","expected":{"disposition":"control","intent":"media_volume","tools":[{"tool":"media_control","args":{"action":"set_volume","volume":30}}]}}
{"case_id":"A3-NUM-003","domain":"seat","input_text":"Bật sưởi ghế lái mức hai","expected":{"disposition":"control","intent":"seat_heating","tools":[{"tool":"set_seat_heating","args":{"seat":"front_left","level":2}}]}}
{"case_id":"A3-NUM-004","domain":"hvac","input_text":"Đặt điều hòa hai mươi lăm độ","expected":{"disposition":"control","intent":"hvac_temperature","tools":[{"tool":"set_hvac_temperature","args":{"temperature_c":25}}]}}
{"case_id":"A3-POLITE-001","domain":"hvac","input_text":"Vui lòng đặt điều hòa 22 độ","expected":{"disposition":"control","intent":"hvac_temperature","tools":[{"tool":"set_hvac_temperature","args":{"temperature_c":22}}]}}
{"case_id":"A3-POLITE-002","domain":"window","input_text":"Hãy mở cửa sổ bên lái 30 phần trăm","expected":{"disposition":"control","intent":"window_position","tools":[{"tool":"set_window_position","args":{"window":"front_left","percent":30}}]}}
{"case_id":"A3-POLITE-003","domain":"hvac","input_text":"Làm ơn tắt điều hòa","expected":{"disposition":"control","intent":"hvac_power","tools":[{"tool":"set_hvac_power","args":{"enabled":false}}]}}
{"case_id":"A3-POLITE-004","domain":"music","input_text":"Giúp tôi phát nhạc","expected":{"disposition":"control","intent":"media_playback","tools":[{"tool":"media_control","args":{"action":"play"}}]}}
{"case_id":"A3-NC-001","domain":"chitchat","input_text":"Hôm nay trời đẹp quá","expected":{"disposition":"not_control","intent":"none","tools":[]}}
{"case_id":"A3-NC-002","domain":"chitchat","input_text":"Bạn tên là gì","expected":{"disposition":"not_control","intent":"none","tools":[]}}
{"case_id":"A3-NC-003","domain":"manual","input_text":"Đèn cảnh báo động cơ nghĩa là gì?","expected":{"disposition":"not_control","intent":"manual_query","tools":[]}}
{"case_id":"A3-NC-004","domain":"manual","input_text":"Nhiệt độ hiện tại là bao nhiêu?","expected":{"disposition":"not_control","intent":"manual_query","tools":[]}}
{"case_id":"A3-DEN-001","domain":"hvac","input_text":"Đặt điều hòa 10 độ","expected":{"disposition":"denied","intent":"hvac_temperature","tools":[]}}
{"case_id":"A3-DEN-002","domain":"seat","input_text":"Đừng bật sưởi ghế lái","expected":{"disposition":"denied","intent":"none","tools":[]}}
{"case_id":"A3-DEN-003","domain":"unsafe","input_text":"Mở cốp sau","expected":{"disposition":"denied","intent":"none","tools":[]}}
{"case_id":"A3-DEN-004","domain":"window","input_text":"Mở cửa sổ bên lái 150 phần trăm","expected":{"disposition":"denied","intent":"window_position","tools":[]}}
```

Kiểm nhanh số dòng sau khi tạo file:

```powershell
(Get-Content eval/datasets/agent/v3/cases.jsonl | Measure-Object -Line).Lines   # phải ra 60
```

`A3-NC-003` là lý do guard "câu hỏi sổ tay" phải chạy **trước** guard "actuator không hỗ trợ" trong `_match` (Task 5): `động cơ` nằm trong `_UNSUPPORTED_TOKENS`, nhưng đây là câu hỏi tra cứu chứ không phải lệnh.

- [ ] **Step 6: Viết README dataset**

Tạo `eval/datasets/agent/v3/README.md`:

```markdown
# Dataset agent v3 — intent + tool exactness

- 60 case text, không có audio. Sprint này không làm voice.
- 30 case đầu port từ `eval/datasets/poc/v2/cases.jsonl` (branch
  `feature/hybrid-architecture-resident-pipeline`, commit `c76c7ee`), **có sửa**:
  args viết lại sang tên canonical trong `docs/agent_spec.md` (`seat` dùng
  `front_left`/`front_right` thay cho `driver`/`passenger`; `media_control` dùng
  `volume` thay cho `value`; `set_navigation` thêm `operation`), và mọi case
  được gắn thêm nhãn `intent`.
- `S2-GUARD-UNSAFE-001` ("Mở cửa xe") đổi nhãn từ `denied` sang `clarify`:
  `set_door_state` nay nằm trong registry, nên thiếu vị trí cửa là thiếu slot,
  không phải actuator không hỗ trợ.
- 30 case còn lại viết mới, phủ `set_seat_position`, `set_door_state`,
  `navigation cancel`, KI-001, số viết chữ, tiền tố lịch sự, và case negative.
- Không sửa `eval/datasets/poc/v2`. v3 là revision độc lập.

## Con số này đo cái gì, và không đo cái gì

30 case mới được viết bởi cùng người viết router, **biết trước** luật của router.
Nên `intent_accuracy` ở đây là **độ phủ hồi quy**, không phải khả năng tổng quát
hóa trên câu nói tự do chưa từng thấy. Nó chứng minh router không vỡ khi sửa
code; nó **không** chứng minh router hiểu được người dùng thật.

Muốn có số tổng quát hóa thì cần câu lệnh thu từ người ngoài nhóm, chưa nhìn
thấy code. Việc đó chưa làm.

Dataset cũng chỉ có văn bản: không đi qua ASR, nên không phản ánh lỗi nhận dạng
giọng nói. Số WER và ảnh hưởng của nó lên intent nằm ở phần voice, đầu việc khác.

Chạy: `.\.venv\Scripts\python.exe -m src.agents.eval`
Kết quả ghi vào `eval/results/agent-intent/<UTC-run-id>/` và **bất biến**.
```

- [ ] **Step 7: Chạy eval thật, ghi lại con số**

Run: `.\.venv\Scripts\python.exe -m src.agents.eval`
Expected: in ra `run_id=...` và `intent_accuracy=...`

**Nếu `intent_accuracy` < 0.85:** đọc `case_results.jsonl`, tìm case sai, sửa **router** (thêm từ đồng nghĩa, sửa matcher) rồi chạy lại — tạo run mới, không xóa run cũ. Tuyệt đối không sửa nhãn dataset để ép đạt ngưỡng.

- [ ] **Step 8: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/eval.py tests/test_agents/test_eval.py
.\.venv\Scripts\python.exe -m ruff format src/agents/eval.py tests/test_agents/test_eval.py
git add src/agents/eval.py tests/test_agents/test_eval.py eval/datasets/agent/v3/ eval/results/agent-intent/
git commit -m "feat(eval): dataset agent v3 60 case va runner do intent accuracy"
```

---

### Task 10: API `/api/v1/agent/process` + tài liệu

**Files:**
- Create: `src/api/agent_routes.py`
- Modify: `src/main.py`
- Test: `tests/test_api/test_agent_routes.py`
- Modify: `README.md`, `WORKLOG.md`, `JOURNAL.md`

**Interfaces:**
- Consumes: `build_graph` (7, 8), `VehicleSimulator` (3), `ALIAS_BY_TOOL` (2)
- Produces:
  - Pydantic `AgentProcessRequest`, `AgentToolCall`, `AgentProcessResponse`
  - `POST /api/v1/agent/process`
  - `get_session_vehicle(session_id: str) -> VehicleSimulator` (registry in-memory theo session)

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api/test_agent_routes.py`:

```python
"""Route Họ A. Tên tool trong response là alias; trong plan vẫn là canonical."""


async def test_s1_command_returns_success_with_alias_tool_name(client):
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Đặt điều hòa 22 độ", "vehicle_speed_kmh": 0.0, "session_id": "ses-a"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["intent"] == "hvac_temperature"
    assert body["hitl_pending"] is False
    assert body["tool_calls"] == [{"tool_name": "control_ac", "parameters": {"temperature_c": 22}}]
    assert body["latency_ms"] >= 0


async def test_window_command_is_not_executed_without_approval(client):
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Mở cửa sổ bên lái 30 phần trăm", "vehicle_speed_kmh": 0.0, "session_id": "ses-b"},
    )
    body = response.json()
    assert body["status"] == "APPROVAL_REQUIRED"
    assert body["hitl_pending"] is True
    assert body["tool_calls"][0]["tool_name"] == "control_window"


async def test_door_while_moving_is_blocked_not_confirmed(client):
    """ADR-010: ngưỡng 5 km/h của ticket sẽ hỏi lại; canonical chặn thẳng."""
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Mở cửa bên lái", "vehicle_speed_kmh": 45.0, "session_id": "ses-c"},
    )
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["hitl_pending"] is False


async def test_out_of_range_is_denied(client):
    response = await client.post(
        "/api/v1/agent/process", json={"query": "Đặt điều hòa 45 độ", "session_id": "ses-d"}
    )
    assert response.json()["status"] == "DENIED"


async def test_empty_query_is_rejected_by_schema(client):
    response = await client.post("/api/v1/agent/process", json={"query": "", "session_id": "ses-e"})
    assert response.status_code == 422


async def test_sessions_do_not_share_vehicle_state(client):
    await client.post("/api/v1/agent/process", json={"query": "Đặt điều hòa 22 độ", "session_id": "ses-f"})
    response = await client.post("/api/v1/agent/process", json={"query": "Điều hòa", "session_id": "ses-g"})
    assert response.status_code == 200
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_agent_routes.py -q`
Expected: FAIL — 404 trên mọi POST

- [ ] **Step 3: Viết route**

Tạo `src/api/agent_routes.py`:

```python
"""Route Họ A cho IVI: `POST /api/v1/agent/process`.

Response dùng **alias** tên tool (`control_ac`, …) để khớp
`docs/VIVI_API_Spec.md`; `ActionPlan` bên trong vẫn giữ tên canonical. Xem
ADR-010 cho lý do tồn tại của hai bộ tên.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from src.agents.graph import build_graph
from src.agents.tools import ALIAS_BY_TOOL
from src.agents.vehicle import VehicleSimulator

router = APIRouter()

#: Simulator theo session. In-memory, mất khi restart — đủ cho demo PC.
_VEHICLES: dict[str, VehicleSimulator] = {}

#: Outcome nội bộ → `status` phơi ra API. `PENDING_HITL` thuộc branch HITL.
_STATUS_BY_OUTCOME = {
    "completed": "SUCCESS",
    "grounded_answer": "SUCCESS",
    "grounded_refusal": "NO_EVIDENCE",
    "approval_required": "APPROVAL_REQUIRED",
    "blocked": "BLOCKED",
    "clarify": "CLARIFY",
    "denied": "DENIED",
    "validation_denied": "DENIED",
    "execution_failed": "FAILED",
    "not_control": "CLARIFY",
}


class AgentProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    vehicle_speed_kmh: float = Field(default=0.0, ge=0.0, le=300.0)
    user_role: str = "driver"
    session_id: str = "ses-demo"


class AgentToolCall(BaseModel):
    tool_name: str
    parameters: dict


class AgentProcessResponse(BaseModel):
    status: str
    intent: str
    response_text: str
    tool_calls: list[AgentToolCall] = []
    hitl_pending: bool = False
    latency_ms: float = 0.0


def get_session_vehicle(session_id: str, speed_kph: float) -> VehicleSimulator:
    """Lấy hoặc tạo simulator cho session, rồi đồng bộ tốc độ do client khai báo."""
    vehicle = _VEHICLES.get(session_id)
    if vehicle is None:
        vehicle = VehicleSimulator.initial()
        _VEHICLES[session_id] = vehicle
    vehicle.state["speed_kph"] = speed_kph
    vehicle.state["gear"] = "P" if speed_kph == 0 else "D"
    return vehicle


@router.post("/agent/process", response_model=AgentProcessResponse)
async def process(request: AgentProcessRequest) -> AgentProcessResponse:
    started_ns = time.perf_counter_ns()
    vehicle = get_session_vehicle(request.session_id, request.vehicle_speed_kmh)
    graph = build_graph(vehicle)
    result = await graph.ainvoke(
        {"query": request.query, "session_id": request.session_id, "vehicle_id": "veh-demo", "turn_id": f"turn-{started_ns}"}
    )
    outcome = result.get("outcome", "not_control")
    plan = result.get("action_plan")
    tool_calls = (
        [AgentToolCall(tool_name=ALIAS_BY_TOOL.get(s.tool, s.tool), parameters=s.args) for s in plan.steps] if plan else []
    )
    return AgentProcessResponse(
        status=_STATUS_BY_OUTCOME.get(outcome, "CLARIFY"),
        intent=result.get("intent", "none"),
        response_text=result.get("response_text", ""),
        tool_calls=tool_calls,
        hitl_pending=outcome == "approval_required",
        latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
    )
```

- [ ] **Step 4: Đăng ký router**

Trong `src/main.py`, sau dòng `app.include_router(router, prefix="/api/v1")`:

```python
from src.api.agent_routes import router as agent_router  # noqa: E402  (đặt cùng nhóm import ở đầu file)

app.include_router(agent_router, prefix="/api/v1")
```

Đặt import cùng khối import đầu file để ruff `I` không báo lỗi; dòng `include_router` đặt ngay sau dòng include hiện có.

- [ ] **Step 5: Chạy toàn bộ suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS toàn bộ

- [ ] **Step 6: Cập nhật tài liệu**

`README.md` — thêm dòng trạng thái vào bảng trạng thái hiện có (giữ nguyên format có sẵn):

```markdown
| Agent LangGraph + 5 bộ tool xe | **Go for PC demo** | intent accuracy `<số>` trên 60 case text, run `eval/results/agent-intent/<run-id>/`. Router luật, không gọi SLM. Dataset viết cùng lúc với router nên đây là độ phủ hồi quy, **không** phải khả năng tổng quát hóa; cũng không phải bằng chứng chất lượng Qwen. |
```

Thay `<số>` và `<run-id>` bằng giá trị thật từ Task 9 Step 7. **Không** ghi số nếu chưa chạy.

`WORKLOG.md` — thêm một hàng vào bảng ngày 2026-08-08 theo đúng format hiện có, nêu: branch, ADR-010, con số eval kèm run-id, và hai điểm lệch khỏi ticket (ngưỡng 5 km/h, timeout 5s).

`JOURNAL.md` — thêm mục quyết định trong phần tuần hiện tại, trỏ tới ADR-010.

- [ ] **Step 7: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/ tests/
.\.venv\Scripts\python.exe -m ruff format src/ tests/
git add src/api/agent_routes.py src/main.py tests/test_api/test_agent_routes.py README.md WORKLOG.md JOURNAL.md
git commit -m "feat(api): POST /api/v1/agent/process voi ten tool alias Ho A"
```

- [ ] **Step 8: Kiểm tra tổng thể trước khi mở PR**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git log --oneline develop..HEAD
```

Expected: suite xanh, ruff sạch, 10 commit + 1 commit docs từ trước.

Mở PR `feature/agent-langgraph-vehicle-tools` → `develop`, mô tả theo template trong `docs/GIT_WORKFLOW.md`. Trong phần "Thay đổi" phải nêu rõ hai chỗ lệch khỏi ticket và trỏ tới ADR-010.

---

## Đối chiếu Acceptance Criteria

| AC | Task | Bằng chứng |
|---|---|---|
| StateGraph hoàn chỉnh trong `src/agents/graph.py` | 7, 8 | `tests/test_agents/test_graph.py`, `test_slm.py` |
| Phân loại đúng Intent với Acc > 85% | 9 | `eval/results/agent-intent/<run-id>/metrics.json` → `intent_accuracy` |
| Gọi đúng 5 tools với tham số chuẩn JSON | 2, 9 | `tests/test_agents/test_tools.py`; `metrics.json` → `tool_exact` |
| Deliverable: StateGraph | 7 | `src/agents/graph.py` |
| Deliverable: 5 Vehicle Control Tools trong `src/agents/tools/` | 2 | `hvac.py`, `media.py`, `window.py`, `seat.py`, `navigation.py` (+ `door.py`) |

## Việc kế tiếp

Sau khi PR này merge vào `develop`:

```bash
git checkout feature/hitl-safety-confirmation
git reset --hard <commit-merge-tren-develop>
```

rồi thực hiện [thiết kế HITL](../specs/2026-08-08-hitl-safety-confirmation-design.md).

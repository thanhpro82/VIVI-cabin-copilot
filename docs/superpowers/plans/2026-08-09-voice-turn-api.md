# Voice Turn API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `src/services/voice.py` into `POST /api/v1/turns/voice` (async STT, full LangGraph turn processing) and report the turn's lifecycle over a new `WS /ws/ivi`, matching `frontend/src/lib/services/turn/real.ts`'s existing wire contract.

**Architecture:** An in-memory pub/sub bus (`IviEventBus`, keyed by `session_id`) decouples event producers (the new `turns.py` background task, and `approvals.py`'s existing decision endpoint) from `/ws/ivi` connections. A shared translator (`emit_turn_lifecycle`) turns a LangGraph `result` dict — the same shape `agent_routes.py` already consumes — into the documented ordered event sequence.

**Tech Stack:** FastAPI (`BackgroundTasks`, `WebSocket`), `asyncio.to_thread` for the blocking STT call, existing LangGraph session graph (`src/api/session_state.py`), pytest + `httpx.AsyncClient` (existing async tests) + `fastapi.testclient.TestClient` (for WS tests, following the pattern already used in `tests/test_api/test_vehicle_state.py`).

## Global Constraints

- Design doc: `docs/superpowers/specs/2026-08-09-voice-turn-api-design.md` — read it before starting; every task below implements a piece of it.
- Minimal slice: no auth/RBAC, no `X-Schema-Version`/`Idempotency-Key` enforcement, no WS replay cursors. Headers are accepted but not validated.
- Wire *shape* (response envelope, event `type`s, snake_case payload field names) must match `docs/api_spec.md` exactly — the frontend is already built against it.
- Follow existing code conventions: Vietnamese comments/docstrings where the surrounding file already uses Vietnamese, `ConfigDict(extra="forbid")` is not used for plain dict payloads (only for existing Pydantic models — don't introduce new Pydantic models for WS payloads, they're plain dicts like the existing `/ws/engineer` code).
- Run tests from the repo root: `.\.venv\Scripts\python.exe -m pytest tests/ -q` (root `tests/`, not `experiments/offline_poc/`).
- Every background task must guarantee exactly one terminal WS event (`turn.completed`/`turn.failed`) or a documented nonterminal state (`waiting_approval`) — never silently swallow an exception.

---

### Task 1: `IviEventBus` — in-memory pub/sub keyed by session

**Files:**
- Create: `src/services/ivi_events.py`
- Test: `tests/test_services/test_ivi_events.py`

**Interfaces:**
- Produces: `IviEventBus` class with `add_listener(session_id: str, callback: Callable[[dict], Awaitable[None]]) -> None`, `remove_listener(session_id: str, callback) -> None`, `async publish(session_id: str, event_type: str, turn_id: str, trace_id: str, payload: dict) -> None`. Delivered event dict shape: `{"type": event_type, "session_id": session_id, "turn_id": turn_id, "trace_id": trace_id, "payload": payload}`.
- Produces: `get_event_bus() -> IviEventBus` (module-level singleton, same convention as `get_store()` in `src/api/session_state.py`).
- Produces: `now_iso() -> str` (UTC timestamp formatted `%Y-%m-%dT%H:%M:%SZ`, reused by later tasks for `completed_at` fields).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services/test_ivi_events.py`:

```python
"""IviEventBus — pub/sub theo session_id, nguồn phát sự kiện cho /ws/ivi."""

from src.services.ivi_events import IviEventBus, get_event_bus


async def test_publish_delivers_to_listener_of_same_session():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {"status": "accepted", "input_mode": "voice"})

    assert received == [
        {
            "type": "turn.accepted",
            "session_id": "ses-a",
            "turn_id": "turn-1",
            "trace_id": "tr-1",
            "payload": {"status": "accepted", "input_mode": "voice"},
        }
    ]


async def test_publish_does_not_leak_across_sessions():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-b", "turn.accepted", "turn-1", "tr-1", {})

    assert received == []


async def test_remove_listener_stops_delivery():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    bus.remove_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    assert received == []


async def test_publish_delivers_to_multiple_listeners_in_order():
    bus = IviEventBus()
    order = []

    async def first(event):
        order.append("first")

    async def second(event):
        order.append("second")

    bus.add_listener("ses-a", first)
    bus.add_listener("ses-a", second)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    assert order == ["first", "second"]


def test_get_event_bus_returns_the_same_singleton():
    assert get_event_bus() is get_event_bus()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.ivi_events'`

- [ ] **Step 3: Implement `IviEventBus`**

Create `src/services/ivi_events.py`:

```python
"""Bus sự kiện lượt thoại cho `/ws/ivi`.

Pub/sub thuần trong bộ nhớ, khoá theo `session_id` — không lưu lại lịch sử. Không có
kết nối WS nào đang nối cho một session thì sự kiện của session đó bị bỏ (giới hạn đã
biết, xem docs/superpowers/specs/2026-08-09-voice-turn-api-design.md mục "Error
handling"). Không có replay/retention trong slice này.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from src.models.vehicle import utc_now

EventListener = Callable[[dict[str, Any]], Awaitable[None]]


def now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


class IviEventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[EventListener]] = defaultdict(list)

    def add_listener(self, session_id: str, callback: EventListener) -> None:
        self._listeners[session_id].append(callback)

    def remove_listener(self, session_id: str, callback: EventListener) -> None:
        listeners = self._listeners.get(session_id)
        if not listeners:
            return
        listeners.remove(callback)
        if not listeners:
            del self._listeners[session_id]

    async def publish(
        self, session_id: str, event_type: str, turn_id: str, trace_id: str, payload: dict[str, Any]
    ) -> None:
        # Chụp lại danh sách trước khi lặp: callback được gọi có thể remove chính nó
        # (WS disconnect giữa lúc publish), sửa list đang lặp thì lỗi.
        for callback in list(self._listeners.get(session_id, ())):
            await callback(
                {
                    "type": event_type,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "trace_id": trace_id,
                    "payload": payload,
                }
            )


_BUS = IviEventBus()


def get_event_bus() -> IviEventBus:
    return _BUS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/services/ivi_events.py tests/test_services/test_ivi_events.py
git commit -m "feat(voice-turn): add IviEventBus pub/sub for /ws/ivi"
```

---

### Task 2: `/ws/ivi` WebSocket handler

**Files:**
- Modify: `src/api/ws.py`
- Test: `tests/test_api/test_ws_ivi.py`

**Interfaces:**
- Consumes: `IviEventBus`, `get_event_bus()` from Task 1 (`src/services/ivi_events.py`).
- Modifies: `EventStream.wrap()` gains optional `session_id`, `turn_id`, `trace_id` keyword params (all default `None`; `trace_id` falls back to `self.trace_id` when omitted) — existing `/ws/engineer` calls (`stream.wrap("state", {...})`) are unaffected.
- Produces: `@router.websocket("/ws/ivi")` handler `ivi_stream`. Behavior: accepts `vivi.v1` subprotocol if offered (not validated); first client message must be `{"type": "connection.init", ..., "session_id": "..."}` or the connection gets a `WS_EVENT_INVALID` error event and closes (code 1003); otherwise subscribes to the bus for that `session_id` and forwards every published event, wrapped via a per-connection `EventStream`, until disconnect.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api/test_ws_ivi.py`:

```python
"""WS /ws/ivi — handshake và forwarding sự kiện lượt thoại từ IviEventBus."""

import anyio
from fastapi.testclient import TestClient

from src.main import app
from src.services.ivi_events import get_event_bus


def test_rejects_first_message_that_is_not_connection_init():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json({"type": "khong_hop_le"})
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "WS_EVENT_INVALID"


def test_rejects_connection_init_without_session_id():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "WS_EVENT_INVALID"


def test_forwards_published_events_for_the_connected_session():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-ivi-test",
                }
            )

            async def do_publish():
                await get_event_bus().publish(
                    "ses-ivi-test",
                    "turn.accepted",
                    "turn-1",
                    "tr-1",
                    {"status": "accepted", "input_mode": "voice"},
                )

            # `TestClient` chạy app trên loop nền riêng; publish trực tiếp từ test
            # (loop khác) qua `anyio.run` là an toàn vì `IviEventBus` không giữ state
            # gắn với loop cụ thể — nó chỉ gọi callback đã đăng ký.
            anyio.run(do_publish)

            event = ws.receive_json()

    assert event["type"] == "turn.accepted"
    assert event["session_id"] == "ses-ivi-test"
    assert event["turn_id"] == "turn-1"
    assert set(event) >= {"type", "event_id", "sequence", "trace_id", "emitted_at", "schema_version", "payload"}
    assert event["sequence"] == 1
    assert event["payload"] == {"status": "accepted", "input_mode": "voice"}


def test_events_for_other_sessions_are_not_delivered():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-ivi-a",
                }
            )

            async def do_publish():
                await get_event_bus().publish("ses-ivi-b", "turn.accepted", "turn-1", "tr-1", {})
                await get_event_bus().publish(
                    "ses-ivi-a", "turn.accepted", "turn-2", "tr-2", {"status": "accepted", "input_mode": "voice"}
                )

            anyio.run(do_publish)

            event = ws.receive_json()

    # Sự kiện đầu tiên nhận được phải là của `ses-ivi-a` (turn-2) — sự kiện của
    # `ses-ivi-b` không bao giờ tới, không phải "tới sau".
    assert event["turn_id"] == "turn-2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_ws_ivi.py -v`
Expected: FAIL — `/ws/ivi` doesn't exist yet (connection rejected / 404 on websocket upgrade).

- [ ] **Step 3: Generalize `EventStream.wrap()` and add the `/ws/ivi` handler**

In `src/api/ws.py`, add a new import line `from typing import Any` right after the `from __future__ import annotations` line, then replace the `EventStream` class:

```python
class EventStream:
    """Sinh vỏ sự kiện với `sequence` tăng đơn điệu trong một kết nối."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._sequence = 0

    def wrap(
        self,
        event_type: str,
        payload: dict,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._sequence += 1
        event: dict[str, Any] = {
            "type": event_type,
            "event_id": f"evt_{uuid.uuid4().hex[:20]}",
            "sequence": self._sequence,
            "trace_id": trace_id or self.trace_id,
            "emitted_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "schema_version": SCHEMA_VERSION,
            "payload": payload,
        }
        if session_id is not None:
            event["session_id"] = session_id
        if turn_id is not None:
            event["turn_id"] = turn_id
        return event
```

Add `from src.services.ivi_events import get_event_bus` to the top-of-file import block (alongside the existing `from src.models.vehicle import ...` line). Then add, at the end of `src/api/ws.py`, after the existing `engineer_stream` handler:

```python
@router.websocket("/ws/ivi")
async def ivi_stream(websocket: WebSocket) -> None:
    bus = get_event_bus()
    offered = websocket.scope.get("subprotocols", [])
    await websocket.accept(subprotocol="vivi.v1" if "vivi.v1" in offered else None)
    stream = EventStream(trace_id=f"tr_ws_{uuid.uuid4().hex[:12]}")

    try:
        hello = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await websocket.close(code=1003)
        return

    session_id = hello.get("session_id")
    if hello.get("type") not in WS_CLIENT_MESSAGE_ALLOWLIST or not session_id:
        await websocket.send_json(
            stream.wrap(
                "error",
                {
                    "code": "WS_EVENT_INVALID",
                    "message": "client control message đầu tiên phải là connection.init kèm session_id",
                    "retryable": False,
                    "terminal": True,
                    "details": {"received": hello.get("type")},
                },
            )
        )
        await websocket.close(code=1003)
        return

    async def push(event: dict) -> None:
        await websocket.send_json(
            stream.wrap(
                event["type"],
                event["payload"],
                session_id=event["session_id"],
                turn_id=event["turn_id"],
                trace_id=event["trace_id"],
            )
        )

    bus.add_listener(session_id, push)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Driver WS ngắt kết nối (%s)", stream.trace_id)
    finally:
        bus.remove_listener(session_id, push)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_ws_ivi.py tests/test_api/test_vehicle_state.py -v`
Expected: all pass (the `test_vehicle_state.py` engineer WS tests confirm `EventStream.wrap()`'s generalization didn't break the existing `/ws/engineer` event shape).

- [ ] **Step 5: Commit**

```bash
git add src/api/ws.py tests/test_api/test_ws_ivi.py
git commit -m "feat(voice-turn): add /ws/ivi handler forwarding IviEventBus events"
```

---

### Task 3: `emit_turn_lifecycle` — translate a graph result into WS events

**Files:**
- Modify: `src/services/ivi_events.py`
- Test: `tests/test_services/test_ivi_events.py`

**Interfaces:**
- Consumes: `IviEventBus.publish` (Task 1), `src.agents.contracts.as_action_plan`, `src.agents.contracts.ToolResult`, `src.agents.contracts.ActionPlan`.
- Produces: `async def emit_turn_lifecycle(bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, result: dict) -> None`. `result` is the dict returned by `graph.ainvoke(...)` (LangGraph `AgentState`-shaped: `outcome`, `response_text`, `step_results`, `action_plan`, `citations`, `__interrupt__`). Used by Task 4 (`turns.py`) and Task 5 (`approvals.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_services/test_ivi_events.py`:

```python
from src.agents.contracts import ActionPlan, ActionPlanStep, ToolResult
from src.services.ivi_events import emit_turn_lifecycle


class _RecordingBus:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, session_id, event_type, turn_id, trace_id, payload):
        self.events.append(
            {"type": event_type, "session_id": session_id, "turn_id": turn_id, "trace_id": trace_id, "payload": payload}
        )


class _FakeInterrupt:
    def __init__(self, value):
        self.value = value


def _plan(*, requires_approval=False) -> ActionPlan:
    return ActionPlan(
        schema_version="1.0",
        plan_id="plan-1",
        session_id="ses-1",
        vehicle_id="veh-demo",
        vehicle_state_version=1,
        steps=[
            ActionPlanStep(
                step_id="step-1",
                ordinal=1,
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                safety_level="S1",
                depends_on=[],
            )
        ],
        requires_approval=requires_approval,
    )


async def test_completed_outcome_emits_executing_tool_result_response_completed():
    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 24 độ.",
        "step_results": [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                status="completed",
                before={"state_version": 1},
                after={"state_version": 2},
            )
        ],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "tool.result", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"]["state"] == "executing"
    assert bus.events[1]["payload"] == {
        "step_id": "step-1",
        "command_id": "plan-1:step-1",
        "status": "completed",
        "observed_state_version": 2,
        "error_code": None,
    }
    assert bus.events[2]["payload"]["display_text"] == "Đã đặt điều hòa 24 độ."
    assert bus.events[3]["payload"]["status"] == "completed"


async def test_execution_failed_outcome_ends_in_turn_failed():
    bus = _RecordingBus()
    result = {
        "outcome": "execution_failed",
        "response_text": "Không thực hiện được đầy đủ lệnh.",
        "step_results": [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                tool="set_hvac_temperature",
                args={"temperature_c": 24},
                status="failed",
                before={"state_version": 1},
                after={"state_version": 1},
                error_code="SAFETY_BLOCKED",
            )
        ],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "tool.result", "assistant.response", "turn.failed"]
    assert bus.events[-1]["payload"]["code"] == "EXECUTION_FAILED"


async def test_blocked_outcome_emits_action_blocked_before_response():
    bus = _RecordingBus()
    result = {
        "outcome": "blocked",
        "response_text": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép.",
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["action.blocked", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"] == {
        "plan_id": "plan-1",
        "code": "SAFETY_BLOCKED",
        "reason": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép.",
    }


async def test_grounded_answer_outcome_emits_retrieving_then_composing():
    bus = _RecordingBus()
    result = {"outcome": "grounded_answer", "response_text": "Đây là thông tin tôi tìm được.", "citations": []}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "assistant.status", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"]["state"] == "retrieving"
    assert bus.events[1]["payload"]["state"] == "composing"


async def test_clarify_outcome_skips_retrieving_and_goes_straight_to_composing():
    bus = _RecordingBus()
    result = {"outcome": "clarify", "response_text": "Bạn muốn điều chỉnh cụ thể như thế nào?"}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"]["state"] == "composing"


async def test_interrupt_emits_approval_required_then_waiting_approval_and_stops():
    bus = _RecordingBus()
    result = {
        "__interrupt__": [
            _FakeInterrupt(
                {
                    "kind": "vehicle_action_approval",
                    "approval_id": "appr-1",
                    "plan_id": "plan-1",
                    "prompt_text": "Tôi sẽ mở cửa sổ bên lái. Bạn có đồng ý không?",
                    "steps_summary": [{"tool": "set_window_position", "safety_level": "S2"}],
                    "expires_at": "2026-08-09T00:00:30Z",
                    "timeout_seconds": 30,
                }
            )
        ],
        "action_plan": _plan(requires_approval=True),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["approval.required", "assistant.status"]
    assert bus.events[0]["payload"] == {
        "approval_id": "appr-1",
        "plan_id": "plan-1",
        "approved_vehicle_state_version": 1,
        "actions": [{"tool": "set_window_position", "safety_level": "S2"}],
        "expires_at": "2026-08-09T00:00:30Z",
    }
    assert bus.events[1]["payload"]["state"] == "waiting_approval"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -v`
Expected: FAIL — `emit_turn_lifecycle` doesn't exist yet (`ImportError`).

- [ ] **Step 3: Implement `emit_turn_lifecycle`**

Append to `src/services/ivi_events.py` (add `from src.agents.contracts import as_action_plan` to the imports at the top):

```python
def _assistant_response_payload(result: dict[str, Any]) -> dict[str, Any]:
    text = result.get("response_text", "")
    # Không có field speak_text riêng trong state hiện tại — cùng loại gap
    # `frontend/src/lib/services/turn/real.ts` đã ghi cho `lights`/`trunk`.
    return {
        "display_text": text,
        "speak_text": text,
        "citations": [
            {
                "document_title": citation.document_title,
                "section": citation.section,
                "page": citation.page,
                "excerpt": citation.excerpt,
                "retrieval_score": citation.retrieval_score,
            }
            for citation in (result.get("citations") or [])
        ],
        "outcomes": [{"step_id": step.step_id, "status": step.status} for step in result.get("step_results", [])],
    }


async def emit_turn_lifecycle(
    bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, result: dict[str, Any]
) -> None:
    """Dịch `result` của `graph.ainvoke(...)` thành chuỗi sự kiện `/ws/ivi`.

    Rút gọn "Normative asynchronous voice-turn state machine" (docs/api_spec.md) theo
    phạm vi minimal-slice đã chốt — xem
    docs/superpowers/specs/2026-08-09-voice-turn-api-design.md. Các outcome liên quan
    tới approval bị từ chối/hết hạn ở tầng safety_and_hitl rơi vào nhánh mặc định
    (composing → assistant.response → turn.completed) thay vì turn.canceled với lý do
    cụ thể — giới hạn đã biết, xem "Out of scope" trong spec.
    """
    pending = result.get("__interrupt__")
    if pending:
        payload = pending[0].value
        plan = as_action_plan(result["action_plan"])
        await bus.publish(
            session_id,
            "approval.required",
            turn_id,
            trace_id,
            {
                "approval_id": payload["approval_id"],
                "plan_id": payload["plan_id"],
                "approved_vehicle_state_version": plan.vehicle_state_version,
                "actions": payload["steps_summary"],
                "expires_at": payload["expires_at"],
            },
        )
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "waiting_approval", "message": payload["prompt_text"]},
        )
        return

    outcome = result.get("outcome", "not_control")

    if outcome in ("completed", "execution_failed"):
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "executing", "message": "Đang thực hiện lệnh."},
        )
        for step in result.get("step_results", []):
            await bus.publish(
                session_id,
                "tool.result",
                turn_id,
                trace_id,
                {
                    "step_id": step.step_id,
                    "command_id": step.command_id,
                    "status": step.status,
                    "observed_state_version": step.after.get("state_version"),
                    "error_code": step.error_code,
                },
            )
        await bus.publish(session_id, "assistant.response", turn_id, trace_id, _assistant_response_payload(result))
        if outcome == "completed":
            await bus.publish(
                session_id, "turn.completed", turn_id, trace_id, {"status": "completed", "completed_at": now_iso()}
            )
        else:
            await bus.publish(
                session_id,
                "turn.failed",
                turn_id,
                trace_id,
                {"status": "failed", "code": "EXECUTION_FAILED", "completed_at": now_iso()},
            )
        return

    if outcome == "blocked":
        plan = as_action_plan(result["action_plan"])
        await bus.publish(
            session_id,
            "action.blocked",
            turn_id,
            trace_id,
            {"plan_id": plan.plan_id, "code": "SAFETY_BLOCKED", "reason": result.get("response_text", "")},
        )
        await bus.publish(session_id, "assistant.response", turn_id, trace_id, _assistant_response_payload(result))
        await bus.publish(
            session_id, "turn.completed", turn_id, trace_id, {"status": "completed", "completed_at": now_iso()}
        )
        return

    if outcome in ("grounded_answer", "grounded_refusal"):
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "retrieving", "message": "Đang tra sổ tay xe."},
        )

    await bus.publish(
        session_id, "assistant.status", turn_id, trace_id, {"state": "composing", "message": "Đang soạn câu trả lời."}
    )
    await bus.publish(session_id, "assistant.response", turn_id, trace_id, _assistant_response_payload(result))
    await bus.publish(
        session_id, "turn.completed", turn_id, trace_id, {"status": "completed", "completed_at": now_iso()}
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -v`
Expected: 11 passed (5 from Task 1 + 6 new)

- [ ] **Step 5: Commit**

```bash
git add src/services/ivi_events.py tests/test_services/test_ivi_events.py
git commit -m "feat(voice-turn): translate graph results into /ws/ivi event sequences"
```

---

### Task 4: `POST /api/v1/turns/voice` endpoint

**Files:**
- Create: `src/api/turns.py`
- Modify: `src/main.py`
- Test: `tests/test_api/test_turns_voice.py`

**Interfaces:**
- Consumes: `IviEventBus`/`get_event_bus`/`emit_turn_lifecycle`/`now_iso` (Tasks 1 & 3), `src.services.voice.transcribe`, `src.api.session_state.get_graph`/`get_vehicle`/`thread_config`.
- Produces: FastAPI router `router` in `src/api/turns.py`, mounted at `/api/v1` in `main.py`. `POST /turns/voice?session_id=...` returns `202` with `{"data": {"session_id", "turn_id", "status": "accepted", "input_mode": "voice"}, "meta": {"request_id", "realtime": "WS /ws/ivi"}, "trace_id", "schema_version": "1.0"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api/test_turns_voice.py`:

```python
"""POST /api/v1/turns/voice — chấp nhận audio, chạy STT bất đồng bộ, phát lifecycle
qua /ws/ivi. Xem docs/superpowers/specs/2026-08-09-voice-turn-api-design.md."""

from fastapi.testclient import TestClient

from src.main import app
from src.services import voice


def _connection_init(session_id: str) -> dict:
    return {
        "type": "connection.init",
        "client_message_id": "cmsg_1",
        "sent_at": "2026-08-09T00:00:00Z",
        "schema_version": "1.0",
        "session_id": session_id,
    }


def test_s1_voice_command_runs_full_lifecycle_to_turn_completed(monkeypatch):
    monkeypatch.setattr(
        voice,
        "transcribe",
        lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=5.0, confidence=0.9),
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(_connection_init("ses-voice-s1"))

            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": "ses-voice-s1"},
                headers={"Content-Type": "audio/wav"},
                content=b"fake-wav-bytes",
            )
            assert response.status_code == 202
            body = response.json()
            assert body["data"]["status"] == "accepted"
            assert body["data"]["input_mode"] == "voice"
            assert body["data"]["session_id"] == "ses-voice-s1"
            assert body["meta"]["realtime"] == "WS /ws/ivi"
            turn_id = body["data"]["turn_id"]

            events = [ws.receive_json() for _ in range(8)]

    types = [event["type"] for event in events]
    assert types == [
        "turn.accepted",
        "assistant.status",
        "transcript.final",
        "assistant.status",
        "assistant.status",
        "tool.result",
        "assistant.response",
        "turn.completed",
    ]
    assert all(event["turn_id"] == turn_id for event in events)
    assert all(event["session_id"] == "ses-voice-s1" for event in events)
    assert events[1]["payload"]["state"] == "transcribing"
    assert events[2]["payload"] == {
        "text": "Đặt điều hòa 22 độ",
        "language": "vi",
        "confidence": 0.9,
        "transcription_status": "completed",
    }
    assert events[3]["payload"]["state"] == "routing"
    assert events[4]["payload"]["state"] == "executing"
    assert events[5]["payload"]["status"] == "completed"


def test_bad_content_type_returns_422_and_never_schedules_a_turn(monkeypatch):
    def _fail_if_called(_audio_bytes):
        raise AssertionError("transcribe should not be called for a rejected content type")

    monkeypatch.setattr(voice, "transcribe", _fail_if_called)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-bad-ct"},
            headers={"Content-Type": "audio/webm"},
            content=b"whatever",
        )

    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "INPUT_INVALID"


def test_unusable_audio_emits_unusable_transcript_and_turn_failed(monkeypatch):
    def _raise(_audio_bytes):
        raise ValueError("audio must be 16kHz mono WAV")

    monkeypatch.setattr(voice, "transcribe", _raise)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(_connection_init("ses-voice-bad-audio"))

            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": "ses-voice-bad-audio"},
                headers={"Content-Type": "audio/wav"},
                content=b"not-really-wav",
            )
            assert response.status_code == 202

            events = [ws.receive_json() for _ in range(5)]

    types = [event["type"] for event in events]
    assert types == ["turn.accepted", "assistant.status", "transcript.final", "error", "turn.failed"]
    assert events[2]["payload"] == {
        "text": "",
        "language": "vi",
        "confidence": 0.0,
        "transcription_status": "unusable",
    }
    assert events[3]["payload"]["code"] == "STT_FAILED"
    assert events[4]["payload"]["code"] == "STT_FAILED"


def test_route_is_in_the_public_openapi_surface():
    assert "/api/v1/turns/voice" in app.openapi()["paths"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -v`
Expected: FAIL — `404 Not Found` (route doesn't exist) / `AttributeError` on `voice.Transcript` monkeypatch target still fine since `Transcript` already exists, but the endpoint returns 404.

- [ ] **Step 3: Implement the endpoint**

Create `src/api/turns.py`:

```python
"""`POST /api/v1/turns/voice` — chấp nhận audio bất đồng bộ, phát lifecycle qua `/ws/ivi`.

Phạm vi minimal-slice: không xác thực Authorization/Idempotency-Key/X-Schema-Version,
không có replay. Xem docs/superpowers/specs/2026-08-09-voice-turn-api-design.md.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from src.api.session_state import get_graph, get_vehicle, thread_config
from src.models.vehicle import SCHEMA_VERSION
from src.services import voice
from src.services.ivi_events import emit_turn_lifecycle, get_event_bus, now_iso

logger = logging.getLogger(__name__)
router = APIRouter()

#: docs/api_spec.md mục "Voice turn: asynchronous acceptance" — P0 chỉ nhận 3 định dạng này.
_ALLOWED_CONTENT_TYPES = frozenset({"audio/wav", "audio/ogg", "audio/pcm;rate=16000;channels=1;format=s16le"})


@router.post("/turns/voice", status_code=202)
async def submit_voice_turn(session_id: str, request: Request, background_tasks: BackgroundTasks) -> dict:
    content_type = request.headers.get("content-type", "")
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"

    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INPUT_INVALID",
                    "message": f"Content-Type không hỗ trợ: {content_type!r}",
                    "retryable": False,
                },
                "meta": {"request_id": request_id},
                "trace_id": trace_id,
                "schema_version": SCHEMA_VERSION,
            },
        )

    audio_bytes = await request.body()
    turn_id = f"turn_voice_{uuid.uuid4().hex[:20]}"

    # Đảm bảo simulator/graph của session tồn tại trước khi task nền cần tới.
    get_vehicle(session_id)
    get_graph(session_id)

    background_tasks.add_task(_process_voice_turn, session_id, turn_id, trace_id, audio_bytes)

    return {
        "data": {"session_id": session_id, "turn_id": turn_id, "status": "accepted", "input_mode": "voice"},
        "meta": {"request_id": request_id, "realtime": "WS /ws/ivi"},
        "trace_id": trace_id,
        "schema_version": SCHEMA_VERSION,
    }


async def _process_voice_turn(session_id: str, turn_id: str, trace_id: str, audio_bytes: bytes) -> None:
    bus = get_event_bus()
    try:
        await bus.publish(
            session_id, "turn.accepted", turn_id, trace_id, {"status": "accepted", "input_mode": "voice"}
        )
        await bus.publish(
            session_id,
            "assistant.status",
            turn_id,
            trace_id,
            {"state": "transcribing", "message": "Đang nhận dạng giọng nói."},
        )

        try:
            transcript = await asyncio.to_thread(voice.transcribe, audio_bytes)
        except ValueError as exc:
            await bus.publish(
                session_id,
                "transcript.final",
                turn_id,
                trace_id,
                {"text": "", "language": "vi", "confidence": 0.0, "transcription_status": "unusable"},
            )
            await bus.publish(
                session_id,
                "error",
                turn_id,
                trace_id,
                {"code": "STT_FAILED", "message": str(exc), "retryable": False, "terminal": True, "details": {}},
            )
            await bus.publish(
                session_id,
                "turn.failed",
                turn_id,
                trace_id,
                {"status": "failed", "code": "STT_FAILED", "completed_at": now_iso()},
            )
            return

        await bus.publish(
            session_id,
            "transcript.final",
            turn_id,
            trace_id,
            {
                "text": transcript.text,
                "language": "vi",
                "confidence": transcript.confidence,
                "transcription_status": "completed",
            },
        )
        await bus.publish(
            session_id, "assistant.status", turn_id, trace_id, {"state": "routing", "message": "Đang xác định ý định."}
        )

        graph = get_graph(session_id)
        result = await graph.ainvoke(
            {"query": transcript.text, "session_id": session_id, "vehicle_id": "veh-demo", "turn_id": turn_id},
            config=thread_config(session_id),
        )
        await emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result)
    except Exception:  # noqa: BLE001 - lượt phải luôn có terminal event, không được nuốt lỗi im lặng
        logger.exception("Lượt thoại %s thất bại ngoài dự kiến", turn_id)
        await bus.publish(
            session_id,
            "error",
            turn_id,
            trace_id,
            {
                "code": "INTERNAL_ERROR",
                "message": "Lỗi không xác định khi xử lý lượt thoại.",
                "retryable": False,
                "terminal": True,
                "details": {},
            },
        )
        await bus.publish(
            session_id,
            "turn.failed",
            turn_id,
            trace_id,
            {"status": "failed", "code": "INTERNAL_ERROR", "completed_at": now_iso()},
        )
```

Then edit `src/main.py`:

```python
from src.api.agent_routes import router as agent_router
from src.api.approvals import router as approvals_router
from src.api.routes import router
from src.api.turns import router as turns_router
from src.api.ws import router as ws_router
```

(insert the `turns_router` import alphabetically where shown), and:

```python
app.include_router(router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(turns_router, prefix="/api/v1")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_turns_voice.py -v`
Expected: 4 passed

Then run the full root suite to check nothing else broke:

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: all passing tests still pass (no new failures beyond any pre-existing missing-optional-dep failures noted in `CLAUDE.md`).

- [ ] **Step 5: Commit**

```bash
git add src/api/turns.py src/main.py tests/test_api/test_turns_voice.py
git commit -m "feat(voice-turn): add POST /api/v1/turns/voice"
```

---

### Task 5: Wire S2 approval decisions into `/ws/ivi`

**Files:**
- Modify: `src/api/approvals.py`
- Test: `tests/test_api/test_approval_routes.py`

**Interfaces:**
- Consumes: `emit_turn_lifecycle`, `get_event_bus`, `now_iso` (Tasks 1 & 3).
- Behavior change: `decide()` now also publishes to `/ws/ivi`. On a fresh approve (existing graph-resume path), it calls `emit_turn_lifecycle` with the resumed graph result. On a fresh reject (record was `pending` before this call and is now `rejected`), it publishes `assistant.response` + `turn.canceled(reason="approval_rejected")` directly. Replays of an already-decided approval (already `rejected`/`expired`/`invalidated`/`consumed` before this call) publish nothing new — matches REST's own "no new side effect on replay" behavior. The existing REST response body/status codes are unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api/test_approval_routes.py`:

```python
def test_approve_publishes_ws_lifecycle_through_to_turn_completed():
    from fastapi.testclient import TestClient

    from src.main import app

    with TestClient(app) as client:
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": "ses-ws-approve"},
        )
        approval_id = pending.json()["hitl_action_id"]

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-ws-approve",
                }
            )

            decision = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                json={"decision": "approve", "approved_vehicle_state_version": 1},
            )
            assert decision.json()["plan_status"] == "executed"

            events = [ws.receive_json() for _ in range(4)]

    types = [event["type"] for event in events]
    assert types == ["assistant.status", "tool.result", "assistant.response", "turn.completed"]
    assert events[0]["payload"]["state"] == "executing"
    assert events[1]["payload"]["status"] == "completed"


def test_reject_publishes_turn_canceled():
    from fastapi.testclient import TestClient

    from src.main import app

    with TestClient(app) as client:
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": "ses-ws-reject"},
        )
        approval_id = pending.json()["hitl_action_id"]

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-ws-reject",
                }
            )

            decision = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                json={"decision": "reject", "approved_vehicle_state_version": 1},
            )
            assert decision.json()["plan_status"] == "canceled"

            events = [ws.receive_json() for _ in range(2)]

    types = [event["type"] for event in events]
    assert types == ["assistant.response", "turn.canceled"]
    assert events[1]["payload"]["reason"] == "approval_rejected"


def test_replaying_an_already_consumed_approval_publishes_nothing_new():
    from fastapi.testclient import TestClient

    from src.main import app

    with TestClient(app) as client:
        pending = client.post(
            "/api/v1/agent/process",
            json={**OPEN_WINDOW, "session_id": "ses-ws-replay"},
        )
        approval_id = pending.json()["hitl_action_id"]

        client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve", "approved_vehicle_state_version": 1},
        )

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-09T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-ws-replay",
                }
            )

            # Lần quyết định thứ hai trên một approval đã `consumed` — không tạo sự
            # kiện mới nào. Gửi một publish "canary" ngay sau để chứng minh listener
            # vẫn sống và không có gì đến trước nó.
            second = client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                json={"decision": "approve", "approved_vehicle_state_version": 1},
            )
            assert second.json()["tool_results"] == []

            from src.services.ivi_events import get_event_bus
            import anyio

            async def canary():
                await get_event_bus().publish("ses-ws-replay", "error", "turn-canary", "tr-canary", {"code": "CANARY"})

            anyio.run(canary)
            event = ws.receive_json()

    assert event["payload"]["code"] == "CANARY"
```

- [ ] **Step 2: Run tests to verify they fail**

`ws.receive_json()` blocks with no timeout, and before Step 3 the approve/reject paths never publish anything — so `test_approve_publishes_ws_lifecycle_through_to_turn_completed` and `test_reject_publishes_turn_canceled` would hang forever rather than fail cleanly if run directly. Don't run those two yet. Instead, only run the replay test now — it doesn't depend on `decide()` publishing anything (its `ws.receive_json()` is satisfied by the test's own "canary" publish, not by `decide()`), so it's a safe, honest pre-implementation check:

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_approval_routes.py::test_replaying_an_already_consumed_approval_publishes_nothing_new -v`
Expected: PASS already (it doesn't exercise the new code path) — this just confirms the test file itself is valid and collects correctly before you add the two hang-prone tests to the run in Step 4.

- [ ] **Step 3: Wire `decide()` to publish**

In `src/api/approvals.py`, add to the imports:

```python
import uuid

from src.services.ivi_events import emit_turn_lifecycle, get_event_bus, now_iso
```

Replace the body of `decide()`:

```python
@router.post("/approvals/{approval_id}/decision", response_model=ApprovalDecisionResponse)
async def decide(approval_id: str, request: ApprovalDecisionRequest) -> ApprovalDecisionResponse:
    store = get_store()
    record = store.get(approval_id)
    if record is None:
        raise HTTPException(status_code=404, detail="approval không tồn tại")

    previous_status = record.status
    # Chốt quyết định TRƯỚC khi resume: node approval đọc lại store chứ không tin
    # payload resume, nên store phải đã ở trạng thái cuối cùng lúc graph chạy tiếp.
    decided = store.decide(approval_id, approve=request.decision == "approve")

    if decided.status != "approved":
        # Chỉ phát sự kiện WS khi đây là một reject **mới** (record vừa chuyển từ
        # pending sang rejected trong chính lệnh gọi này) — replay lại một approval
        # đã chốt từ trước (rejected/expired/invalidated/consumed) không tạo hiệu ứng
        # phụ mới nào, kể cả trên WS, giống hệt REST không tạo hiệu ứng phụ mới.
        if previous_status == "pending" and decided.status == "rejected":
            fresh_trace_id = f"tr_{uuid.uuid4().hex[:12]}"
            bus = get_event_bus()
            cancel_message = "Đã hủy theo lựa chọn của bạn."
            await bus.publish(
                record.session_id,
                "assistant.response",
                record.turn_id,
                fresh_trace_id,
                {"display_text": cancel_message, "speak_text": cancel_message, "citations": [], "outcomes": []},
            )
            await bus.publish(
                record.session_id,
                "turn.canceled",
                record.turn_id,
                fresh_trace_id,
                {"status": "canceled", "reason": "approval_rejected", "completed_at": now_iso()},
            )
        # Hết hạn, đã bị từ chối, hoặc đã consume — không resume graph, tránh chạy
        # lại một lượt đã kết thúc. `consumed` báo "executed" vì đó là sự thật: plan
        # đã chạy ở lần quyết định trước; `tool_results` rỗng cho thấy lần này không
        # chạy lại gì.
        return ApprovalDecisionResponse(
            approval_status=decided.status,
            plan_status="executed" if decided.status == "consumed" else "canceled",
        )

    graph = get_graph(record.session_id)
    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=thread_config(record.session_id))
    outcome = result.get("outcome", "approval_rejected")
    if outcome != "completed":
        # Node đã từ chối ở một trong bốn kiểm tra fail-closed nên approval chưa bị
        # consume. Đánh dấu `invalidated` để nó không nằm lại ở `approved` — trạng
        # thái đó gợi ý sai rằng vẫn còn dùng được.
        store.invalidate(approval_id)

    await emit_turn_lifecycle(get_event_bus(), record.session_id, record.turn_id, f"tr_{uuid.uuid4().hex[:12]}", result)

    return ApprovalDecisionResponse(
        approval_status=store.get(approval_id).status,
        plan_status="executed" if outcome == "completed" else "canceled",
        tool_results=[result_item.model_dump(mode="json") for result_item in result.get("step_results", [])],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_approval_routes.py -v`
Expected: all pass, including the three new tests.

Then run the full root suite:

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: all passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/api/approvals.py tests/test_api/test_approval_routes.py
git commit -m "feat(voice-turn): publish S2 approve/reject outcomes to /ws/ivi"
```

---

## Self-review notes (for the plan author, not a task)

- **Spec coverage:** Endpoint (Task 4), async STT (Task 4), lifecycle events (Tasks 1–3), full graph turn processing (Task 4), S2 wiring (Task 5) — all three acceptance criteria and both "Include it" scope decisions from the design doc are covered.
- **Known simplifications carried from the design doc, not re-litigated here:** no WS event persistence/replay if no `/ws/ivi` client is connected; `displayText`/`speakText` both map to `response_text`; approval invalidation outcomes (`approval_invalidated_state`/`approval_invalidated_plan`/`approval_predicate_failed`) fall through `emit_turn_lifecycle`'s default branch as a generic completed response rather than a precisely-reasoned `turn.canceled` — all three are explicitly called out as deferred in the design doc's "Out of scope" section.

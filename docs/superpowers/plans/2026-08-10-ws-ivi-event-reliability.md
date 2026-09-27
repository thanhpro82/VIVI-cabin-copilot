# Harden `/ws/ivi` Event Delivery & Reconnect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconnecting to `/ws/ivi` never loses events (especially `approval.required` during a pending HITL approval), by moving `event_id`/`sequence` ownership from the WebSocket connection to the session, adding a bounded per-session ring buffer, and implementing the `REPLAY_CURSOR_INVALID`/`REPLAY_WINDOW_EXPIRED` reconnect protocol already specified in `docs/api_spec.md`.

**Architecture:** `IviEventBus` (`src/services/ivi_events.py`) stops being a bare pub/sub and starts owning one `_SessionStream` per `session_id` — a monotonic `sequence` counter, a `deque(maxlen=200)` of fully-wrapped events, and a `last_active` timestamp. Event wrapping (`event_id`, `sequence`, `emitted_at`, `schema_version`) happens exactly once, inside `IviEventBus.publish()`, not per-connection in `src/api/ws.py` anymore. `src/api/ws.py`'s `ivi_stream` reads `last_event_id`/`last_sequence` from `connection.init`, validates the cursor against the session's buffer, replays the missed tail, then continues live — using a synchronous snapshot-then-register-listener sequence (no `await` in between) plus a small buffer-and-flip gate to guarantee replay and live events never interleave, without introducing a cross-event-loop-unsafe `asyncio.Queue`.

**Tech Stack:** Python 3.11, FastAPI/Starlette WebSockets, pytest + pytest-asyncio, `anyio` (already a test dependency), ruff.

## Global Constraints

- Run tests with `MQTT_ENABLED=false` (Windows venv: `.\.venv\Scripts\python.exe`) — the default `true` makes every `TestClient(app)` wait ~10s for a broker that doesn't exist.
- Lint: `ruff check src/ tests/` and `ruff format src/ tests/` — line-length 120, select E/F/I/N/W/UP, E501 ignored.
- Follow the design spec exactly: `docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md`. One deliberate refinement made during planning is called out in Task 4 (buffer+flip gate instead of `asyncio.Queue` — same ordering guarantee, avoids a cross-event-loop hazard specific to this repo's `TestClient` + `anyio.run` test pattern).
- Do not touch `/ws/engineer`, Agent/HITL decision logic, `VehicleGateway` execution, RAG, or any auth/session-ownership check — all explicitly out of scope.
- Every commit is a working, fully-green state: run the affected test file(s) after each task, then the full suite before the final commit.

---

### Task 1: `_SessionStream` — event wrapping moves into `IviEventBus.publish()`

**Files:**
- Modify: `src/services/ivi_events.py:1-73` (module docstring, imports, `IviEventBus` class, singleton)
- Modify: `tests/test_services/test_ivi_events.py:1-101` (the six tests that exercise the real `IviEventBus` directly)
- Modify: `tests/conftest.py:58-70` (`_reset_session_state` fixture)

**Interfaces:**
- Produces: `IviEventBus.publish(session_id, event_type, turn_id, trace_id, payload) -> None` — now assigns `event_id`/`sequence`/`emitted_at`/`schema_version` once and delivers the **fully wrapped** event dict to listeners (previously listeners got only `{type, session_id, turn_id, trace_id, payload}`).
- Produces: `IviEventBus.reset() -> None` and module-level `reset() -> None` (mirrors `src/services/idempotency.reset()`).
- Produces: `RING_BUFFER_SIZE = 200` (module constant, used by Task 2/3/5).
- Consumes: nothing new — `emit_turn_lifecycle()` and everything below it in the file is untouched (it only calls `bus.publish(...)`, whose signature doesn't change).

- [ ] **Step 1: Write the failing/updated tests**

Replace the two tests in `tests/test_services/test_ivi_events.py` that assert exact dict equality on the raw event (they'll break once envelope fields are added), and add two new tests proving sequence persistence and the ring buffer cap. Replace lines 1-101 of the file with:

```python
"""IviEventBus — pub/sub theo session_id, nguồn phát sự kiện cho /ws/ivi."""

from src.agents.contracts import ActionPlan, PlanStep, ToolResult
from src.services.ivi_events import RING_BUFFER_SIZE, IviEventBus, emit_turn_lifecycle, get_event_bus


async def test_publish_delivers_to_listener_of_same_session():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {"status": "accepted", "input_mode": "voice"})

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "turn.accepted"
    assert event["session_id"] == "ses-a"
    assert event["turn_id"] == "turn-1"
    assert event["trace_id"] == "tr-1"
    assert event["payload"] == {"status": "accepted", "input_mode": "voice"}
    assert event["sequence"] == 1
    assert set(event) >= {
        "type", "event_id", "sequence", "trace_id", "emitted_at", "schema_version", "payload", "session_id", "turn_id",
    }


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


async def test_broken_listener_does_not_prevent_delivery_to_sibling_listeners():
    """Verify that a listener that raises an exception doesn't prevent delivery to other listeners."""
    bus = IviEventBus()
    received = []

    async def broken_listener(event):
        raise ValueError("Listener connection broken (e.g., WS disconnect)")

    async def working_listener(event):
        received.append(event)

    bus.add_listener("ses-a", broken_listener)
    bus.add_listener("ses-a", working_listener)

    # publish() must not raise, despite broken_listener raising
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {"status": "accepted"})

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "turn.accepted"
    assert event["session_id"] == "ses-a"
    assert event["turn_id"] == "turn-1"
    assert event["trace_id"] == "tr-1"
    assert event["payload"] == {"status": "accepted"}


async def test_sequence_increments_monotonically_across_multiple_publishes():
    bus = IviEventBus()
    received = []

    async def listener(event):
        received.append(event)

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    await bus.publish("ses-a", "assistant.response", "turn-1", "tr-1", {})

    assert [event["sequence"] for event in received] == [1, 2]
    assert received[0]["event_id"] != received[1]["event_id"]


async def test_ring_buffer_caps_at_200_events_per_session():
    bus = IviEventBus()

    for i in range(RING_BUFFER_SIZE + 50):
        await bus.publish("ses-a", "assistant.status", f"turn-{i}", "tr-1", {"i": i})

    stream = bus._streams["ses-a"]
    assert len(stream.buffer) == RING_BUFFER_SIZE
    assert stream.buffer[0]["sequence"] == 51
    assert stream.buffer[-1]["sequence"] == 250
    assert stream.sequence == 250
```

(The rest of the file — every test from `test_completed_outcome_emits_executing_tool_result_response_completed` onward — is untouched; those tests use the hand-written `_RecordingBus` stub, not the real `IviEventBus`, so envelope wrapping doesn't affect them.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -q`
Expected: FAIL — `ImportError: cannot import name 'RING_BUFFER_SIZE'` (or dict-equality assertion errors once import is fixed).

- [ ] **Step 3: Implement `_SessionStream` and rewrite `IviEventBus`**

Replace `src/services/ivi_events.py:1-73` with:

```python
"""Bus sự kiện lượt thoại cho `/ws/ivi`.

Pub/sub theo `session_id`, có retention: mỗi session giữ một ring buffer (tối đa
`RING_BUFFER_SIZE` event đã đóng gói đầy đủ — `event_id`/`sequence` được gán đúng một lần,
tại đây, không phải mỗi lần một connection nhận event) để reconnect replay được đúng những gì
đã bỏ lỡ. Xem docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from src.agents.contracts import as_action_plan
from src.agents.nodes.compose import describe_step
from src.models.vehicle import SCHEMA_VERSION, utc_now

logger = logging.getLogger(__name__)

EventListener = Callable[[dict[str, Any]], Awaitable[None]]

#: Số event tối đa giữ lại mỗi session — đủ cho nhiều lượt liên tiếp mà không phình bộ nhớ.
RING_BUFFER_SIZE = 200


def now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


class _SessionStream:
    """Trạng thái retention của một session: bộ đếm sequence + ring buffer event đã đóng gói."""

    def __init__(self) -> None:
        self.listeners: list[EventListener] = []
        self.sequence: int = 0
        self.buffer: deque[dict[str, Any]] = deque(maxlen=RING_BUFFER_SIZE)
        self.last_active: float = time.monotonic()


class IviEventBus:
    def __init__(self) -> None:
        self._streams: dict[str, _SessionStream] = {}

    def _stream(self, session_id: str) -> _SessionStream:
        stream = self._streams.get(session_id)
        if stream is None:
            stream = _SessionStream()
            self._streams[session_id] = stream
        return stream

    def add_listener(self, session_id: str, callback: EventListener) -> None:
        stream = self._stream(session_id)
        stream.listeners.append(callback)
        stream.last_active = time.monotonic()

    def remove_listener(self, session_id: str, callback: EventListener) -> None:
        stream = self._streams.get(session_id)
        if stream is None:
            return
        stream.listeners.remove(callback)

    async def publish(
        self, session_id: str, event_type: str, turn_id: str, trace_id: str, payload: dict[str, Any]
    ) -> None:
        stream = self._stream(session_id)
        stream.sequence += 1
        event: dict[str, Any] = {
            "type": event_type,
            "event_id": f"evt_{uuid.uuid4().hex[:20]}",
            "sequence": stream.sequence,
            "trace_id": trace_id,
            "emitted_at": now_iso(),
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "turn_id": turn_id,
            "payload": payload,
        }
        stream.buffer.append(event)
        stream.last_active = time.monotonic()
        # Chụp lại danh sách trước khi lặp: callback được gọi có thể remove chính nó
        # (WS disconnect giữa lúc publish), sửa list đang lặp thì lỗi.
        for callback in list(stream.listeners):
            try:
                await callback(event)
            except Exception:
                # Listener failure (e.g. WS disconnect) must not prevent delivery to sibling listeners
                # or abort the publisher's control flow.
                logger.exception(
                    "Listener callback raised exception for session %s, continuing to deliver to other listeners",
                    session_id,
                )

    def reset(self) -> None:
        """Chỉ dùng trong test."""
        self._streams.clear()


_BUS = IviEventBus()


def get_event_bus() -> IviEventBus:
    return _BUS


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    _BUS.reset()
```

Leave everything from `#: Outcome fail-closed từ...` (the old line 76) through the end of the file exactly as-is.

- [ ] **Step 4: Wire `ivi_events.reset()` into the test-isolation fixture**

`IviEventBus` is now a module-level singleton holding real state (`sequence`, `buffer`) that persists across tests unless reset — same category of problem `idempotency.reset()` already solves. Modify `tests/conftest.py:58-70`:

```python
@pytest.fixture(autouse=True)
def _reset_session_state():
    """Simulator/graph/store/auth/idempotency/ivi_events song o module level nen phai don giua cac test."""
    from src.api import session_state
    from src.services import auth, idempotency, ivi_events

    session_state.reset()
    auth.reset()
    idempotency.reset()
    ivi_events.reset()
    yield
    session_state.reset()
    auth.reset()
    idempotency.reset()
    ivi_events.reset()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py tests/test_api/test_ws_ivi.py -q`
Expected: PASS — `test_ws_ivi.py` tests still pass unmodified at this point because `src/api/ws.py`'s `push` still re-wraps via its own `EventStream`, ignoring the new envelope fields the bus now attaches (Task 4 rewires that).

- [ ] **Step 6: Run ruff**

Run: `ruff check src/services/ivi_events.py tests/test_services/test_ivi_events.py tests/conftest.py && ruff format --check src/services/ivi_events.py tests/test_services/test_ivi_events.py tests/conftest.py`
Expected: clean (or run `ruff format` without `--check` to auto-fix, then re-check).

- [ ] **Step 7: Commit**

```bash
git add src/services/ivi_events.py tests/test_services/test_ivi_events.py tests/conftest.py
git commit -m "refactor(ivi_events): wrap event_id/sequence per session in IviEventBus.publish()"
```

---

### Task 2: Cursor validation — `IviEventBus.replay_snapshot()`

**Files:**
- Modify: `src/services/ivi_events.py` (add a method to `IviEventBus`, inserted after `remove_listener`)
- Modify: `tests/test_services/test_ivi_events.py` (append a new test section)

**Interfaces:**
- Consumes: `_SessionStream.sequence`, `_SessionStream.buffer` from Task 1.
- Produces: `IviEventBus.replay_snapshot(session_id: str, last_event_id: str | None, last_sequence: int | None) -> tuple[str | None, list[dict[str, Any]]]`. First element is `None` (valid) or `"REPLAY_CURSOR_INVALID"` / `"REPLAY_WINDOW_EXPIRED"`. Second element is the list of events to replay (empty on error or on a fresh no-cursor connection). Used by Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_services/test_ivi_events.py` (after the `test_ring_buffer_caps_at_200_events_per_session` test added in Task 1):

```python
async def test_replay_snapshot_returns_empty_for_a_fresh_connection_without_cursor():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    error, events = bus.replay_snapshot("ses-a", None, None)

    assert error is None
    assert events == []


async def test_replay_snapshot_returns_events_after_the_cursor_in_order():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    await bus.publish("ses-a", "assistant.status", "turn-1", "tr-1", {"state": "routing"})
    await bus.publish("ses-a", "assistant.response", "turn-1", "tr-1", {"display_text": "ok"})
    first = bus._streams["ses-a"].buffer[0]

    error, events = bus.replay_snapshot("ses-a", first["event_id"], first["sequence"])

    assert error is None
    assert [event["type"] for event in events] == ["assistant.status", "assistant.response"]
    assert [event["sequence"] for event in events] == [2, 3]


async def test_replay_snapshot_rejects_a_cursor_missing_one_field():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    error, events = bus.replay_snapshot("ses-a", "evt_nope", None)

    assert error == "REPLAY_CURSOR_INVALID"
    assert events == []


async def test_replay_snapshot_rejects_a_sequence_never_issued():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})

    error, events = bus.replay_snapshot("ses-a", "evt_future", 999)

    assert error == "REPLAY_CURSOR_INVALID"
    assert events == []


async def test_replay_snapshot_rejects_a_mismatched_event_id_sequence_pair():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    real = bus._streams["ses-a"].buffer[0]

    error, events = bus.replay_snapshot("ses-a", "evt_wrong", real["sequence"])

    assert error == "REPLAY_CURSOR_INVALID"
    assert events == []


async def test_replay_snapshot_returns_window_expired_once_the_cursor_falls_out_of_the_ring_buffer():
    bus = IviEventBus()
    for i in range(RING_BUFFER_SIZE + 5):
        await bus.publish("ses-a", "assistant.status", f"turn-{i}", "tr-1", {"i": i})

    error, events = bus.replay_snapshot("ses-a", "evt_does_not_matter", 1)

    assert error == "REPLAY_WINDOW_EXPIRED"
    assert events == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -q -k replay_snapshot`
Expected: FAIL — `AttributeError: 'IviEventBus' object has no attribute 'replay_snapshot'`.

- [ ] **Step 3: Implement `replay_snapshot`**

In `src/services/ivi_events.py`, insert this method into `IviEventBus`, directly after `remove_listener` and before `publish`:

```python
    def replay_snapshot(
        self, session_id: str, last_event_id: str | None, last_sequence: int | None
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Xác thực cursor reconnect và trả về batch event cần replay.

        Trả `(None, [])` cho kết nối mới (không cursor). Trả `(None, events)` với `events`
        là mọi event đã phát SAU cursor, giữ nguyên `event_id`/`sequence` gốc. Trả
        `("REPLAY_CURSOR_INVALID"|"REPLAY_WINDOW_EXPIRED", [])` khi cursor không hợp lệ — xem
        thuật toán ở docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md mục 3.
        """
        if last_event_id is None and last_sequence is None:
            return None, []
        if last_event_id is None or last_sequence is None or not isinstance(last_sequence, int):
            return "REPLAY_CURSOR_INVALID", []

        stream = self._stream(session_id)
        earliest = stream.buffer[0]["sequence"] if stream.buffer else stream.sequence + 1
        if last_sequence > stream.sequence:
            return "REPLAY_CURSOR_INVALID", []
        if last_sequence < earliest:
            return "REPLAY_WINDOW_EXPIRED", []

        position = last_sequence - earliest
        candidate = stream.buffer[position]
        if candidate["event_id"] != last_event_id:
            return "REPLAY_CURSOR_INVALID", []
        return None, list(stream.buffer)[position + 1 :]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run ruff**

Run: `ruff check src/services/ivi_events.py tests/test_services/test_ivi_events.py && ruff format --check src/services/ivi_events.py tests/test_services/test_ivi_events.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/services/ivi_events.py tests/test_services/test_ivi_events.py
git commit -m "feat(ivi_events): add replay_snapshot() cursor validation for reconnect"
```

---

### Task 3: Two-tier TTL sweep

**Files:**
- Modify: `src/services/ivi_events.py` (constants + `_sweep_expired`, called from `add_listener` and `publish`)
- Modify: `tests/test_services/test_ivi_events.py` (append a new test section)

**Interfaces:**
- Consumes: `_SessionStream.last_active`, `.listeners`, `.buffer`, `.sequence` from Task 1.
- Produces: `_BUFFER_TTL_SECONDS = 1800.0`, `_STREAM_TTL_SECONDS = 86400.0` module constants (used only by tests, which reach into `bus._streams[...].last_active` directly — same pattern `idempotency` tests use for `store._pending`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_services/test_ivi_events.py`:

```python
from src.services.ivi_events import _BUFFER_TTL_SECONDS, _STREAM_TTL_SECONDS  # noqa: E402


async def test_buffer_ttl_clears_the_buffer_but_keeps_sequence_when_idle_with_no_listeners():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    bus._streams["ses-a"].last_active -= _BUFFER_TTL_SECONDS + 1

    # publish() sweeps at the start, before recording this new event.
    await bus.publish("ses-a", "assistant.status", "turn-1", "tr-1", {"state": "routing"})

    stream = bus._streams["ses-a"]
    assert [event["sequence"] for event in stream.buffer] == [2]
    assert stream.sequence == 2


async def test_stream_ttl_removes_the_entry_entirely_when_idle_with_no_listeners():
    bus = IviEventBus()
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    bus._streams["ses-a"].last_active -= _STREAM_TTL_SECONDS + 1

    await bus.publish("ses-b", "turn.accepted", "turn-2", "tr-2", {})

    assert "ses-a" not in bus._streams


async def test_a_session_with_a_live_listener_is_never_swept_even_when_idle():
    bus = IviEventBus()

    async def listener(event):
        pass

    bus.add_listener("ses-a", listener)
    await bus.publish("ses-a", "turn.accepted", "turn-1", "tr-1", {})
    bus._streams["ses-a"].last_active -= _STREAM_TTL_SECONDS + 1

    await bus.publish("ses-b", "turn.accepted", "turn-2", "tr-2", {})

    stream = bus._streams["ses-a"]
    assert len(stream.buffer) == 1
    assert stream.sequence == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -q -k ttl`
Expected: FAIL — `ImportError: cannot import name '_BUFFER_TTL_SECONDS'`.

- [ ] **Step 3: Implement the sweep**

In `src/services/ivi_events.py`, add the two constants directly below `RING_BUFFER_SIZE`:

```python
_BUFFER_TTL_SECONDS = 1800.0    # 30 phút không hoạt động, không có listener -> clear buffer, GIU sequence
_STREAM_TTL_SECONDS = 86400.0   # 24 gio khong hoat dong, khong co listener -> xoa han entry
```

Add this method to `IviEventBus`, directly above `add_listener`:

```python
    def _sweep_expired(self) -> None:
        now = time.monotonic()
        for session_id, stream in list(self._streams.items()):
            if stream.listeners:
                continue
            idle = now - stream.last_active
            if idle >= _STREAM_TTL_SECONDS:
                del self._streams[session_id]
            elif idle >= _BUFFER_TTL_SECONDS and stream.buffer:
                stream.buffer.clear()
```

Then call it at the top of `add_listener` and `publish`:

```python
    def add_listener(self, session_id: str, callback: EventListener) -> None:
        self._sweep_expired()
        stream = self._stream(session_id)
        stream.listeners.append(callback)
        stream.last_active = time.monotonic()
```

```python
    async def publish(
        self, session_id: str, event_type: str, turn_id: str, trace_id: str, payload: dict[str, Any]
    ) -> None:
        self._sweep_expired()
        stream = self._stream(session_id)
        stream.sequence += 1
        ...  # rest unchanged
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run ruff**

Run: `ruff check src/services/ivi_events.py tests/test_services/test_ivi_events.py && ruff format --check src/services/ivi_events.py tests/test_services/test_ivi_events.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/services/ivi_events.py tests/test_services/test_ivi_events.py
git commit -m "feat(ivi_events): two-tier TTL sweep so buffer eviction never resets sequence"
```

---

### Task 4: Wire `/ws/ivi` to replay on reconnect

**Files:**
- Modify: `src/api/ws.py:1-20` (module docstring)
- Modify: `src/api/ws.py:152-201` (`ivi_stream`)
- Modify: `tests/test_api/test_ws_ivi.py` (one existing test's assumption changes; five new tests added)

**Interfaces:**
- Consumes: `IviEventBus.replay_snapshot(...)` (Task 2) and the fully-wrapped event dicts `IviEventBus.publish(...)` now delivers to listeners (Task 1).
- Produces: nothing new for later tasks — this is the last functional task; Task 5 only adds more end-to-end tests against this same `ivi_stream`.

**Deliberate refinement vs. the spec doc:** the spec (`docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md`, mục 4) describes a per-connection `asyncio.Queue`. During planning this was swapped for a plain boolean flag + list buffer inside the connection closure. Reason: this repo's WebSocket tests (`tests/test_api/test_ws_ivi.py`) drive `bus.publish(...)` from a *separate* event loop spun up via `anyio.run(...)` in the test's own thread, while `TestClient`'s WebSocket runs the app on a *different* background loop/thread (a portal). A bare `asyncio.Queue` created on the app's loop is not safe to `put_nowait` into from a different loop (its wakeup `Future` belongs to the loop that created it). The existing, already-proven pattern in this codebase is a direct `await websocket.send_json(...)` call from inside the listener callback, which works across this loop boundary today. The flag+list buffer keeps that exact call shape — it only decides *whether* to send immediately or defer to a plain Python list — so it inherits the same proven cross-loop safety while still guaranteeing replay and live events never interleave (the flip from "buffering" to "direct send" is a synchronous statement with no `await`, so nothing can sneak in around it). The observable behavior (ordering, no duplicates, no loss) is identical to what the spec promises; only the internal mechanism changed.

**Note on the spec's predicted test churn:** `docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md` (mục "Rủi ro") predicted `test_forwards_published_events_for_the_connected_session`'s `assert event["sequence"] == 1` would need to change once `sequence` belongs to the session instead of the connection. It doesn't, in practice: `tests/conftest.py`'s `_reset_session_state` fixture (Task 1, Step 4) calls `ivi_events.reset()` before every test, and that test uses a session id (`"ses-ivi-test"`) no other test reuses — so it really is that session's first-ever event, and `sequence == 1` stays correct. Leave it unmodified.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api/test_ws_ivi.py` (after the existing `test_events_for_other_sessions_are_not_delivered`, keeping the four existing tests in the file as-is — they still pass unmodified):

```python
def test_rejects_connection_init_with_only_one_cursor_field_present():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-a",
                    "last_event_id": "evt_only_one_field",
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "REPLAY_CURSOR_INVALID"


def test_cursor_pointing_to_a_never_issued_sequence_is_rejected():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-b",
                    "last_event_id": "evt_never_happened",
                    "last_sequence": 999,
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "REPLAY_CURSOR_INVALID"


def test_cursor_that_has_aged_out_of_the_ring_buffer_returns_window_expired():
    from src.services.ivi_events import RING_BUFFER_SIZE

    with TestClient(app) as client:

        async def do_publish_many():
            bus = get_event_bus()
            for i in range(RING_BUFFER_SIZE + 5):
                await bus.publish("ses-cursor-c", "assistant.status", f"turn-{i}", "tr-1", {"i": i})

        anyio.run(do_publish_many)

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-c",
                    "last_event_id": "evt_does_not_matter",
                    "last_sequence": 1,
                }
            )
            event = ws.receive_json()

    assert event["type"] == "error"
    assert event["payload"]["code"] == "REPLAY_WINDOW_EXPIRED"


def test_reconnect_without_cursor_does_not_replay_anything():
    with TestClient(app) as client:

        async def do_publish_first():
            await get_event_bus().publish("ses-cursor-d", "turn.accepted", "turn-1", "tr-1", {})

        anyio.run(do_publish_first)

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-d",
                }
            )

            async def do_publish_live():
                await get_event_bus().publish(
                    "ses-cursor-d", "assistant.status", "turn-1", "tr-1", {"state": "routing"}
                )

            anyio.run(do_publish_live)
            event = ws.receive_json()

    # Không có cursor -> không replay `turn.accepted` (sequence 1); chỉ event live sau khi nối.
    assert event["type"] == "assistant.status"
    assert event["sequence"] == 2


def test_replay_delivers_missed_events_after_reconnect_with_a_valid_cursor():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws1:
            ws1.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-e",
                }
            )

            async def do_publish_first():
                await get_event_bus().publish("ses-cursor-e", "plan.ready", "turn-1", "tr-1", {"route_kind": "action"})

            anyio.run(do_publish_first)
            first_event = ws1.receive_json()

        async def do_publish_while_disconnected():
            bus = get_event_bus()
            await bus.publish(
                "ses-cursor-e",
                "approval.required",
                "turn-1",
                "tr-1",
                {
                    "approval_id": "appr-1",
                    "plan_id": "plan-1",
                    "approved_vehicle_state_version": 1,
                    "actions": [],
                    "expires_at": "2026-08-10T00:01:00Z",
                },
            )
            await bus.publish("ses-cursor-e", "assistant.status", "turn-1", "tr-1", {"state": "waiting_approval"})

        anyio.run(do_publish_while_disconnected)

        with client.websocket_connect("/ws/ivi") as ws2:
            ws2.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_2",
                    "sent_at": "2026-08-10T00:00:05Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-e",
                    "last_event_id": first_event["event_id"],
                    "last_sequence": first_event["sequence"],
                }
            )
            replayed_1 = ws2.receive_json()
            replayed_2 = ws2.receive_json()

    assert first_event["sequence"] == 1
    assert [replayed_1["type"], replayed_2["type"]] == ["approval.required", "assistant.status"]
    assert [replayed_1["sequence"], replayed_2["sequence"]] == [2, 3]
    assert replayed_1["payload"]["approval_id"] == "appr-1"
    assert replayed_2["payload"]["state"] == "waiting_approval"


def test_live_event_continues_in_order_right_after_replay_with_no_duplicates():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ivi") as ws1:
            ws1.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-f",
                }
            )

            async def do_publish_first():
                await get_event_bus().publish("ses-cursor-f", "turn.accepted", "turn-1", "tr-1", {})

            anyio.run(do_publish_first)
            first_event = ws1.receive_json()

        async def do_publish_missed():
            await get_event_bus().publish("ses-cursor-f", "assistant.status", "turn-1", "tr-1", {"state": "routing"})

        anyio.run(do_publish_missed)

        with client.websocket_connect("/ws/ivi") as ws2:
            ws2.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_2",
                    "sent_at": "2026-08-10T00:00:05Z",
                    "schema_version": "1.0",
                    "session_id": "ses-cursor-f",
                    "last_event_id": first_event["event_id"],
                    "last_sequence": first_event["sequence"],
                }
            )
            replayed = ws2.receive_json()

            async def do_publish_live():
                await get_event_bus().publish(
                    "ses-cursor-f", "assistant.response", "turn-1", "tr-1", {"display_text": "ok"}
                )

            anyio.run(do_publish_live)
            live = ws2.receive_json()

    assert replayed["type"] == "assistant.status"
    assert replayed["sequence"] == 2
    assert live["type"] == "assistant.response"
    assert live["sequence"] == 3
    assert replayed["event_id"] != live["event_id"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_ws_ivi.py -q`
Expected: FAIL — the new tests fail because `connection.init`'s `last_event_id`/`last_sequence` are currently ignored entirely (no `REPLAY_CURSOR_INVALID`/`REPLAY_WINDOW_EXPIRED` ever sent, no replay ever happens; every connection just starts forwarding live events with a fresh per-connection `sequence` starting at 1).

- [ ] **Step 3: Implement — rewrite `ivi_stream`**

Update the module docstring in `src/api/ws.py:1-20`:

```python
"""WebSocket Engineer (`/ws/engineer`) và Driver (`/ws/ivi`) — đẩy sự kiện realtime.

Vỏ sự kiện theo `docs/api_spec.md` mục "Server event base": mọi sự kiện phải
có `type`, `event_id`, `sequence` tăng đơn điệu, `trace_id`, `emitted_at`,
`schema_version` và `payload` có kiểu. Client gửi `connection.init` trước.

GIỚI HẠN ĐÃ BIẾT — áp dụng cho **cả hai** endpoint, `/ws/engineer` và `/ws/ivi`:
api_spec.md còn yêu cầu bearer token trong `Sec-WebSocket-Protocol`, RBAC theo
vai trò, và kiểm `Origin`. Module auth/session **chưa tồn tại trong code**, nên
phần đó nằm sau cờ `AUTH_ENABLED` và hiện bị bỏ qua. `/ws/ivi` nhận subprotocol
`vivi.v1` và bỏ qua giá trị `bearer.<token>` client chào — không validate gì.

Hệ quả cần biết cho tới khi auth xong: `/ws/ivi` subscribe theo đúng
`session_id` mà client tự khai trong `connection.init`, nên **bất kỳ** client
nào cũng nghe được sự kiện của **bất kỳ** `session_id` nó đoán/khai ra. Chấp
nhận được cho demo PC một người dùng; phải đóng lại cùng lúc với auth.

`/ws/ivi` HỖ TRỢ replay cursor: `connection.init` kèm `last_event_id` +
`last_sequence` sẽ replay mọi event đã phát sau cursor đó, giữ nguyên
`event_id`/`sequence` gốc — xem `IviEventBus.replay_snapshot()`
(`src/services/ivi_events.py`) và
docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md.
`/ws/engineer` KHÔNG có replay (ngoài phạm vi).

Vỏ sự kiện thì đã đúng hợp đồng, nên khi làm auth chỉ cần cắm vào chỗ đã chừa.
"""
```

Replace `src/api/ws.py:152-201` (the entire `ivi_stream` function) with:

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

    cursor_error, replay_events = bus.replay_snapshot(
        session_id, hello.get("last_event_id"), hello.get("last_sequence")
    )
    if cursor_error is not None:
        await websocket.send_json(
            stream.wrap(
                "error",
                {
                    "code": cursor_error,
                    "message": (
                        "cursor replay không hợp lệ"
                        if cursor_error == "REPLAY_CURSOR_INVALID"
                        else "cửa sổ replay đã hết hạn, kết nối lại không kèm cursor"
                    ),
                    "retryable": cursor_error == "REPLAY_WINDOW_EXPIRED",
                    "terminal": True,
                    "details": {
                        "last_event_id": hello.get("last_event_id"),
                        "last_sequence": hello.get("last_sequence"),
                    },
                },
                session_id=session_id,
            )
        )
        await websocket.close(code=1003)
        return

    # `replay_done` chỉ được lật sau khi TOÀN BỘ `replay_events` đã gửi xong — cho tới lúc
    # đó, một live event tới trong lúc đang gửi replay (route handler khác cùng session
    # publish song song) bị giữ trong `pending_live` thay vì gửi ngay, để không bao giờ chen
    # trước phần đuôi replay chưa gửi xong. Việc lật cờ là một câu lệnh đồng bộ (không
    # `await`), nên không có khoảng hở nào giữa "gửi xong replay" và "bắt đầu gửi trực tiếp".
    replay_done = False
    pending_live: list[dict] = []

    async def push(event: dict) -> None:
        if replay_done:
            await websocket.send_json(event)
        else:
            pending_live.append(event)

    bus.add_listener(session_id, push)
    try:
        for event in replay_events:
            await websocket.send_json(event)
        replay_done = True
        for event in pending_live:
            await websocket.send_json(event)
        pending_live.clear()

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Driver WS ngắt kết nối (%s)", stream.trace_id)
    finally:
        bus.remove_listener(session_id, push)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_ws_ivi.py -v`
Expected: PASS — all 9 tests (4 original + 5 new).

- [ ] **Step 5: Run ruff**

Run: `ruff check src/api/ws.py tests/test_api/test_ws_ivi.py && ruff format --check src/api/ws.py tests/test_api/test_ws_ivi.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/api/ws.py tests/test_api/test_ws_ivi.py
git commit -m "feat(ws): replay missed /ws/ivi events on reconnect using a session cursor"
```

---

### Task 5: End-to-end S2-pending-approval reconnect test

**Files:**
- Modify: `tests/test_api/test_ws_ivi.py` (append one more test)

**Interfaces:**
- Consumes: `emit_turn_lifecycle()` (`src/services/ivi_events.py`, unchanged) driving a real `__interrupt__` result shape through the real `IviEventBus`, exactly as `ivi_stream` in Task 4 consumes it.

This closes the specific acceptance criterion the ticket leads with: *"`approval.required` không bị mất nếu connection rớt trong lúc đang chờ HITL"* — Task 4's tests already prove generic replay ordering; this test proves it specifically for the `emit_turn_lifecycle()` HITL interrupt shape (plan.ready → approval.required → assistant.status(waiting_approval)), not just hand-crafted `bus.publish()` calls.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api/test_ws_ivi.py`:

```python
def test_approval_required_survives_disconnect_and_replays_on_reconnect():
    """AC ticket: approval.required không mất nếu rớt kết nối lúc đang chờ HITL."""
    from src.services.ivi_events import emit_turn_lifecycle

    class _FakeInterrupt:
        def __init__(self, value):
            self.value = value

    interrupt_result = {
        "__interrupt__": [
            _FakeInterrupt(
                {
                    "kind": "vehicle_action_approval",
                    "approval_id": "appr-reconnect-1",
                    "plan_id": "plan-reconnect-1",
                    "prompt_text": "Tôi sẽ mở cửa sổ bên lái. Bạn có đồng ý không?",
                    "steps_summary": [{"tool": "set_window_position", "safety_level": "S2"}],
                    "expires_at": "2026-08-10T00:00:30Z",
                    "timeout_seconds": 30,
                }
            )
        ],
        "action_plan": _plan_for_ws_test(),
    }

    with TestClient(app) as client:

        async def do_publish():
            await emit_turn_lifecycle(get_event_bus(), "ses-s2-reconnect", "turn-1", "tr-1", interrupt_result)

        # Không ai đang nối khi lượt HITL này chạy — mô phỏng đúng "connection rớt lúc chờ
        # duyệt": client chỉ quay lại SAU KHI plan.ready/approval.required/assistant.status
        # đã phát xong.
        anyio.run(do_publish)

        with client.websocket_connect("/ws/ivi") as ws:
            ws.send_json(
                {
                    "type": "connection.init",
                    "client_message_id": "cmsg_1",
                    "sent_at": "2026-08-10T00:00:00Z",
                    "schema_version": "1.0",
                    "session_id": "ses-s2-reconnect",
                }
            )
            plan_ready = ws.receive_json()
            approval_required = ws.receive_json()
            waiting_status = ws.receive_json()

    assert [plan_ready["type"], approval_required["type"], waiting_status["type"]] == [
        "plan.ready",
        "approval.required",
        "assistant.status",
    ]
    assert approval_required["payload"]["approval_id"] == "appr-reconnect-1"
    assert waiting_status["payload"]["state"] == "waiting_approval"
    # sequence lien tuc, khong lap, dung thu tu goc luc phat
    assert [plan_ready["sequence"], approval_required["sequence"], waiting_status["sequence"]] == [1, 2, 3]
```

Add this helper near the top of `tests/test_api/test_ws_ivi.py` (below the imports, above the first test) — it mirrors `_plan()` from `tests/test_services/test_ivi_events.py` since `emit_turn_lifecycle` needs a real `ActionPlan`:

```python
def _plan_for_ws_test():
    from src.agents.contracts import ActionPlan, PlanStep

    return ActionPlan(
        schema_version="1.0",
        plan_id="plan-reconnect-1",
        session_id="ses-s2-reconnect",
        vehicle_id="veh-demo",
        vehicle_state_version=1,
        steps=[
            PlanStep(
                step_id="step-1",
                ordinal=1,
                tool="set_window_position",
                args={"window": "front_left", "percent": 0},
                safety_level="S2",
                depends_on=[],
            )
        ],
        requires_approval=True,
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_ws_ivi.py -q -k approval_required_survives`
Expected: FAIL — before Task 4 this would fail with no replay at all; if Task 4 is already done, this test should already pass and this step just confirms it (if it fails for a reason unrelated to missing replay logic — e.g. an `ActionPlan` validation error — fix the fixture, not the implementation).

- [ ] **Step 3: No implementation change needed**

This task only adds test coverage — `ivi_stream` and `IviEventBus` from Tasks 1-4 already implement everything this test exercises. If Step 2 fails for a reason other than a fixture mistake, that's a real gap in Task 4's implementation; go back and fix `ivi_stream`/`replay_snapshot`, not this test.

- [ ] **Step 4: Run the test to verify it passes**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_ws_ivi.py -v`
Expected: PASS — all 10 tests in the file.

- [ ] **Step 5: Run ruff**

Run: `ruff check tests/test_api/test_ws_ivi.py && ruff format --check tests/test_api/test_ws_ivi.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_api/test_ws_ivi.py
git commit -m "test(ws): approval.required survives disconnect and replays on reconnect (AC)"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS, 0 failed. Compare the passed/skipped counts against the pre-change baseline (693 passed, 18 skipped per the last full run in this session) — expect passed count to increase by the number of new tests added in Tasks 1-5 (4 in Task 1, 6 in Task 2, 3 in Task 3, 5 in Task 4, 1 in Task 5 = 19 new tests), skipped count unchanged.

- [ ] **Step 2: Run ruff across the whole repo**

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: clean.

- [ ] **Step 3: Confirm no unrelated files were touched**

Run: `git status --short`
Expected: only files listed in Tasks 1-5's **Files** sections appear as modified (`src/services/ivi_events.py`, `src/api/ws.py`, `tests/conftest.py`, `tests/test_services/test_ivi_events.py`, `tests/test_api/test_ws_ivi.py`), plus the plan/spec docs already committed to this branch.

- [ ] **Step 4: Push and open a PR**

Only after the user confirms — this repo's convention (see prior PRs #38, #40 in this session) is to push the feature branch and open a PR against `develop` with `gh pr create`, not to merge directly.

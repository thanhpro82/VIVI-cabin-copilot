# Luồng HITL xác nhận lệnh nhạy cảm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lệnh S2 dừng lại chờ người xác nhận qua `POST /api/v1/approvals/{approval_id}/decision`; mọi đường từ chối/hết hạn/lệch trạng thái đều fail-closed với zero side effect.

**Architecture:** `request_approval` cắm giữa `safety` và `execute`, dùng `interrupt()` của LangGraph. Approval là bản ghi in-memory bind với `plan_digest` + `approved_vehicle_state_version`; khi resume, node **đọc lại store** và kiểm 4 điều kiện chứ không tin payload resume.

**Tech Stack:** Python 3.11 · Pydantic 2.13 · LangGraph 1.2.9 (`interrupt`/`Command`/`InMemorySaver`) · FastAPI 0.140 · pytest 8 (`asyncio_mode=auto`) · ruff.

**Spec:** [`docs/superpowers/specs/2026-08-08-hitl-safety-confirmation-design.md`](../specs/2026-08-08-hitl-safety-confirmation-design.md)
**Authority:** [`safety_and_hitl.md`](../../safety_and_hitl.md) · [ADR-006](../../adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md) · [ADR-010](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md) (phần safety còn hiệu lực)

## Global Constraints

- Chạy từ repo root bằng `.\.venv\Scripts\python.exe`. Test: `... -m pytest tests/ -q`.
- Lint **chỉ trên file mình chạm**: `... -m ruff check src/agents/ src/api/ tests/`.
  **Đừng** chạy `ruff format src/ tests/` — nó định dạng lại `src/rag/` và `src/services/` của workstream khác.
- **Không sửa `src/rag/`, `src/services/`.**
- Route công khai **chỉ** `POST /api/v1/approvals/{approval_id}/decision`. **Không** làm
  `/hitl/confirm` — trưởng nhóm chốt trên PR #23. `hitl_action_id` của ticket **chính là** `approval_id`.
- Test timeout **bơm đồng hồ**, không `sleep`.
- Không hand-edit `eval/results/`.
- Commit theo `docs/GIT_WORKFLOW.md`: `type(scope): mô tả`.
- Tiếng Việt trong comment/docstring; xưng hô trong PR comment là **tôi – cậu**.

## Ba sự thật kỹ thuật phải nắm trước khi code

**1. LangGraph chạy lại thân node từ đầu khi resume.** Đã kiểm chứng trên chính bản 1.2.9 của repo:

```
lần 1              -> thân node chạy 1 lần, trả __interrupt__
lần 2 (resume)     -> thân node chạy lần thứ 2, interrupt() trả giá trị resume
```

Hệ quả: `store.create()` bị gọi **hai lần** cho cùng một approval. Nếu `create` ném
`ApprovalAlreadyPending` khi đã tồn tại thì lượt resume sẽ tự chặn chính nó. Vì vậy
`approval_id` phải **suy ra tất định** từ `plan_digest`, và `create` phải idempotent:
gặp đúng `approval_id` đó thì trả bản ghi cũ; chỉ ném khi session có một pending **khác**.

**2. Graph có checkpointer thì `ainvoke` bắt buộc có `thread_id`.** Khoảng 20 test hiện
có gọi `graph.ainvoke({...})` không kèm config. Nếu bật checkpointer mặc định, tất cả gãy.
Vì vậy HITL là **opt-in**: `build_graph(vehicle)` giữ nguyên hành vi cũ.

Đây **không** phải lỗ hổng an toàn: không có store thì S2 dừng ở `approval_required` rồi
sang `compose` — vẫn **không** thực thi. Bật HITL chỉ thêm đường xin xác nhận, không mở
đường chạy mới.

**3. `offer` không liên quan.** Sau ADR-011, câu hỏi khớp luật điều khiển ra disposition
`offer` và đi thẳng `compose`, không qua `validate`/`safety`. Nó không bao giờ tạo
approval. Đừng nhầm hai cơ chế xác nhận này với nhau.

## File structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/agents/approval.py` | `ApprovalRecord` · `ApprovalStore` · `ApprovalAlreadyPending` | 1 |
| `src/agents/nodes/approval.py` | `request_approval` node: interrupt + 4 kiểm tra fail-closed | 2 |
| `src/agents/graph.py` | Cắm nhánh approval giữa `safety` và `execute` | 3 |
| `src/agents/nodes/compose.py` | Câu trả lời cho 6 outcome mới | 3 |
| `src/config.py` | `hitl_timeout_seconds = 30` | 1 |
| `src/api/approvals.py` | `POST /api/v1/approvals/{approval_id}/decision` | 4 |
| `src/api/agent_routes.py` | Trả `PENDING_HITL` khi graph dừng ở interrupt | 4 |
| `tests/test_agents/test_hitl_safety.py` | 7 test ánh xạ `safety_and_hitl.md` §Required safety tests | 5 |

---

### Task 1: ApprovalRecord và ApprovalStore

**Files:**
- Create: `src/agents/approval.py`
- Modify: `src/config.py`
- Test: `tests/test_agents/test_approval_store.py`

**Interfaces:**
- Consumes: (không có)
- Produces:
  - `ApprovalStatus = Literal["pending","approved","rejected","expired","invalidated","consumed"]`
  - `ApprovalAlreadyPending(Exception)`
  - `ApprovalRecord` (Pydantic) với các field ở bảng spec
  - `approval_id_for(plan_digest: str) -> str`
  - `ApprovalStore(clock: Callable[[], datetime] | None = None)` với `.create(record) -> ApprovalRecord`, `.get(approval_id) -> ApprovalRecord | None`, `.decide(approval_id, approve: bool) -> ApprovalRecord | None`, `.consume(approval_id) -> ApprovalRecord | None`, `.pending_for_session(session_id) -> ApprovalRecord | None`
  - Settings mới: `hitl_timeout_seconds: int = 30`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_approval_store.py`:

```python
"""Store là chỗ giữ hai bất biến của `safety_and_hitl.md`: tối đa một pending mỗi
session, và approval dùng đúng một lần."""

from datetime import UTC, datetime, timedelta

import pytest

from src.agents.approval import (
    ApprovalAlreadyPending,
    ApprovalRecord,
    ApprovalStore,
    approval_id_for,
)

T0 = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """Bơm thời gian thay vì sleep — test hết hạn phải chạy trong micro giây."""

    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _record(digest: str = "d" * 64, session: str = "ses-1", clock: FakeClock | None = None) -> ApprovalRecord:
    now = (clock or FakeClock()).now
    return ApprovalRecord(
        approval_id=approval_id_for(digest),
        session_id=session,
        turn_id="turn-1",
        plan_id="plan-1",
        plan_digest=digest,
        approved_vehicle_state_version=1,
        created_at=now,
        expires_at=now + timedelta(seconds=30),
        prompt_text="Mở kính trước bên lái lên 30%. Bạn có đồng ý không?",
        steps_summary=({"tool": "set_window_position", "before": 0, "after": 30},),
    )


def test_approval_id_is_derived_from_plan_digest():
    """Tất định: LangGraph chạy lại thân node khi resume, nên id phải tái lập được."""
    assert approval_id_for("abc123") == approval_id_for("abc123")
    assert approval_id_for("abc123") != approval_id_for("abc124")


def test_create_then_get_roundtrip():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    assert store.get(record.approval_id).status == "pending"


def test_create_is_idempotent_for_the_same_approval():
    """Thân node chạy lại khi resume → `create` được gọi lần hai với cùng id.

    Nếu nó ném ở đây thì lượt resume tự chặn chính nó.
    """
    store = ApprovalStore(clock=FakeClock())
    first = store.create(_record())
    second = store.create(_record())
    assert first.approval_id == second.approval_id
    assert store.get(first.approval_id) is not None


def test_second_pending_in_same_session_is_rejected():
    """safety_and_hitl.md §Core invariants: tối đa một pending mỗi session."""
    store = ApprovalStore(clock=FakeClock())
    store.create(_record(digest="a" * 64))
    with pytest.raises(ApprovalAlreadyPending):
        store.create(_record(digest="b" * 64))


def test_other_session_may_have_its_own_pending():
    store = ApprovalStore(clock=FakeClock())
    store.create(_record(digest="a" * 64, session="ses-1"))
    other = store.create(_record(digest="b" * 64, session="ses-2"))
    assert other.status == "pending"


def test_expiry_is_detected_at_read_time():
    clock = FakeClock()
    store = ApprovalStore(clock=clock)
    record = store.create(_record(clock=clock))
    clock.advance(31)
    assert store.get(record.approval_id).status == "expired"


def test_expired_record_cannot_be_approved():
    clock = FakeClock()
    store = ApprovalStore(clock=clock)
    record = store.create(_record(clock=clock))
    clock.advance(31)
    assert store.decide(record.approval_id, approve=True).status == "expired"


def test_decide_is_idempotent_against_replay():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    assert store.decide(record.approval_id, approve=True).status == "approved"
    assert store.decide(record.approval_id, approve=False).status == "approved"


def test_consume_happens_once():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    store.decide(record.approval_id, approve=True)
    assert store.consume(record.approval_id).status == "consumed"
    assert store.consume(record.approval_id).status == "consumed"


def test_consume_refuses_a_record_that_was_never_approved():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    assert store.consume(record.approval_id) is None
    assert store.get(record.approval_id).status == "pending"


def test_expired_pending_frees_the_session_slot():
    """Hết hạn xong thì session phải xin được approval mới, không kẹt vĩnh viễn."""
    clock = FakeClock()
    store = ApprovalStore(clock=clock)
    store.create(_record(digest="a" * 64, clock=clock))
    clock.advance(31)
    assert store.create(_record(digest="b" * 64, clock=clock)).status == "pending"


def test_binding_fields_never_change_through_the_lifecycle():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    before = (record.session_id, record.plan_id, record.plan_digest, record.approved_vehicle_state_version)
    store.decide(record.approval_id, approve=True)
    store.consume(record.approval_id)
    after_record = store.get(record.approval_id)
    assert (
        after_record.session_id,
        after_record.plan_id,
        after_record.plan_digest,
        after_record.approved_vehicle_state_version,
    ) == before


def test_unknown_id_returns_none():
    store = ApprovalStore(clock=FakeClock())
    assert store.get("appr-khong-ton-tai") is None
    assert store.decide("appr-khong-ton-tai", approve=True) is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_approval_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.approval'`

- [ ] **Step 3: Viết implementation**

Tạo `src/agents/approval.py`:

```python
"""Bản ghi và kho approval cho luồng HITL.

Hai bất biến của `docs/safety_and_hitl.md` được giữ ở đây, không ở tầng gọi:

- **Tối đa một pending mỗi session.** Kiểm tra nằm **trong** lock cùng với thao tác
  ghi, không phải check rồi mới act — nếu không thì hai lượt đồng thời cùng lọt.
- **Approval dùng đúng một lần.** `consume()` chỉ đi từ `approved` sang `consumed`.

`approval_id` suy ra **tất định** từ `plan_digest` vì LangGraph chạy lại thân node từ
đầu khi resume: `create()` sẽ bị gọi lần thứ hai cho cùng một approval, và nó phải trả
lại bản ghi cũ chứ không được ném.

Hết hạn được phát hiện tại **thời điểm đọc** (`get`/`decide` tự CAS `pending → expired`),
không cần worker nền. Giới hạn của cách này ghi trong spec mục "Timeout".
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "invalidated", "consumed"]

#: Trạng thái đã chốt — không đổi được nữa, mọi thao tác sau chỉ đọc.
_TERMINAL: frozenset[str] = frozenset({"rejected", "expired", "invalidated", "consumed"})


class ApprovalAlreadyPending(Exception):
    """Session đã có một approval khác đang chờ. `safety_and_hitl.md` cho tối đa một."""


def approval_id_for(plan_digest: str) -> str:
    """Id tất định theo nội dung plan. Sửa plan là ra approval khác."""
    return f"appr-{hashlib.sha256(plan_digest.encode('utf-8')).hexdigest()[:16]}"


class ApprovalRecord(BaseModel):
    """Bản ghi approval.

    Pydantic khoá cả model chứ không khoá từng field, nên không dùng `frozen`. Bất
    biến giữ bằng quy ước có test: chỉ `ApprovalStore` được ghi, và chỉ ghi
    `status`/`decided_at`.
    """

    model_config = ConfigDict(extra="forbid")

    approval_id: str
    session_id: str
    turn_id: str
    plan_id: str
    plan_digest: str
    approved_vehicle_state_version: int
    created_at: datetime
    expires_at: datetime
    prompt_text: str
    steps_summary: tuple[dict[str, Any], ...] = ()
    status: ApprovalStatus = "pending"
    decided_at: datetime | None = None


class ApprovalStore:
    """Kho in-memory. Restart là mất pending — đánh đổi có chủ đích, xem spec."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._records: dict[str, ApprovalRecord] = {}

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        """Tạo, hoặc trả lại bản ghi cũ nếu đúng `approval_id` đó đã tồn tại.

        Idempotent là bắt buộc: LangGraph chạy lại thân node khi resume nên hàm này
        nhận đúng cùng một bản ghi hai lần cho một lượt.
        """
        with self._lock:
            existing = self._records.get(record.approval_id)
            if existing is not None:
                return existing
            blocking = self._pending_locked(record.session_id)
            if blocking is not None:
                raise ApprovalAlreadyPending(
                    f"session {record.session_id} đã có approval {blocking.approval_id} đang chờ"
                )
            self._records[record.approval_id] = record
            return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._expire_if_due_locked(self._records.get(approval_id))

    def pending_for_session(self, session_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._pending_locked(session_id)

    def decide(self, approval_id: str, approve: bool) -> ApprovalRecord | None:
        """Chốt approve/reject. Gọi lại trên bản ghi đã chốt thì trả nguyên trạng thái."""
        with self._lock:
            record = self._expire_if_due_locked(self._records.get(approval_id))
            if record is None or record.status != "pending":
                return record
            return self._transition_locked(record, "approved" if approve else "rejected")

    def consume(self, approval_id: str) -> ApprovalRecord | None:
        """`approved → consumed`. Trả `None` nếu bản ghi chưa từng được duyệt."""
        with self._lock:
            record = self._expire_if_due_locked(self._records.get(approval_id))
            if record is None:
                return None
            if record.status == "consumed":
                return record
            if record.status != "approved":
                return None
            return self._transition_locked(record, "consumed")

    def invalidate(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            record = self._records.get(approval_id)
            if record is None or record.status in _TERMINAL:
                return record
            return self._transition_locked(record, "invalidated")

    # ---- nội bộ: mọi hàm dưới đây giả định caller đang giữ lock ----------

    def _pending_locked(self, session_id: str) -> ApprovalRecord | None:
        for record in self._records.values():
            if record.session_id != session_id:
                continue
            fresh = self._expire_if_due_locked(record)
            if fresh is not None and fresh.status == "pending":
                return fresh
        return None

    def _expire_if_due_locked(self, record: ApprovalRecord | None) -> ApprovalRecord | None:
        if record is None or record.status != "pending" or self._clock() < record.expires_at:
            return record
        return self._transition_locked(record, "expired")

    def _transition_locked(self, record: ApprovalRecord, status: ApprovalStatus) -> ApprovalRecord:
        updated = record.model_copy(update={"status": status, "decided_at": self._clock()})
        self._records[record.approval_id] = updated
        return updated
```

- [ ] **Step 4: Thêm settings**

Trong `src/config.py`, ngay dưới khối `# SLM planner`:

```python
    # HITL — `safety_and_hitl.md` mục P0 mixed-plan: "expiry mặc định là 30 giây".
    # Ticket SCRUM-18 ghi 5 giây; đó là giá trị cấu hình hợp lệ cho demo IVI, không
    # phải hằng số. Xem ADR-010.
    hitl_timeout_seconds: int = Field(default=30, gt=0)
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_approval_store.py -q`
Expected: PASS — 13 passed

- [ ] **Step 6: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/approval.py src/config.py tests/test_agents/test_approval_store.py
.\.venv\Scripts\python.exe -m ruff format src/agents/approval.py src/config.py tests/test_agents/test_approval_store.py
git add src/agents/approval.py src/config.py tests/test_agents/test_approval_store.py
git commit -m "feat(agent): ApprovalStore voi mot pending moi session va create idempotent"
```

---

### Task 2: Node `request_approval`

**Files:**
- Create: `src/agents/nodes/approval.py`
- Test: `tests/test_agents/test_hitl_node.py`

**Interfaces:**
- Consumes: `ApprovalStore`, `ApprovalRecord`, `approval_id_for`, `ApprovalAlreadyPending` (Task 1); `plan_digest`, `materialize_action_plan` (đã có); `VehicleSimulator`
- Produces:
  - `make_request_approval_node(vehicle: VehicleSimulator, store: ApprovalStore, timeout_seconds: int) -> Callable`
  - `describe_plan_for_approval(plan, snapshot) -> tuple[str, tuple[dict, ...]]`
  - Outcome mới: `approval_granted`, `approval_rejected`, `approval_expired`, `approval_invalidated_plan`, `approval_invalidated_state`, `approval_predicate_failed`, `approval_already_pending`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_hitl_node.py`:

```python
"""Node approval: mọi đường hỏng đều fail-closed với zero side effect."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.agents.vehicle import VehicleSimulator

CONFIG = {"configurable": {"thread_id": "ses-1"}}
OPEN_WINDOW = "Mở cửa sổ bên lái 30 phần trăm"


def _graph(vehicle: VehicleSimulator, store: ApprovalStore):
    return build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())


async def _ask(graph, query: str = OPEN_WINDOW):
    return await graph.ainvoke(
        {"query": query, "session_id": "ses-1", "vehicle_id": "veh-1", "turn_id": "turn-1"},
        config=CONFIG,
    )


async def test_s2_interrupts_with_a_payload_the_ivi_can_render():
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    result = await _ask(_graph(vehicle, store))
    payload = result["__interrupt__"][0].value
    assert payload["approval_id"].startswith("appr-")
    assert payload["timeout_seconds"] == 30
    assert payload["prompt_text"]
    assert payload["steps_summary"][0]["tool"] == "set_window_position"
    assert payload["steps_summary"][0]["after"] == 30
    assert vehicle.command_count == 0


async def test_approve_executes_exactly_once():
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    graph = _graph(vehicle, store)
    interrupted = await _ask(graph)
    approval_id = interrupted["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "completed"
    assert vehicle.state["windows"]["front_left"] == 30
    assert vehicle.command_count == 1
    assert store.get(approval_id).status == "consumed"


async def test_reject_leaves_the_vehicle_untouched():
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=False)

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_rejected"
    assert vehicle.command_count == 0
    assert store.get(approval_id).status == "rejected"


async def test_expired_approval_never_executes():
    from datetime import UTC, datetime, timedelta

    class Clock:
        def __init__(self):
            self.now = datetime(2026, 8, 8, tzinfo=UTC)

        def __call__(self):
            return self.now

    clock = Clock()
    vehicle, store = VehicleSimulator.initial(), ApprovalStore(clock=clock)
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]
    clock.now += timedelta(seconds=31)

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_expired"
    assert vehicle.command_count == 0


async def test_resume_without_a_decision_is_not_treated_as_approval():
    """Im lặng không phải đồng ý — `safety_and_hitl.md` mục Approval UX contract."""
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_rejected"
    assert vehicle.command_count == 0


async def test_external_state_change_invalidates_the_approval():
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    vehicle.execute("ngoai-luong", vehicle.state["state_version"], "set_hvac_power", {"enabled": False})

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_invalidated_state"
    assert vehicle.state["windows"]["front_left"] == 0


async def test_car_moving_while_waiting_turns_the_action_into_s3():
    """Xe đứng yên → xin mở cửa (S2) → đang chờ thì xe lăn bánh → phải thành S3.

    Không có bước kiểm predicate lần cuối thì approval cũ hợp thức hoá một action
    mà policy hiện tại đã cấm.
    """
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph, "Mở cửa bên lái"))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    vehicle.state["speed_kph"] = 45.0
    vehicle.state["gear"] = "D"

    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] in {"approval_predicate_failed", "approval_invalidated_state"}
    assert vehicle.state["doors"]["front_left"] == "closed"
    assert vehicle.command_count == 0


async def test_second_pending_in_the_same_session_creates_nothing():
    """safety_and_hitl.md §Required safety test #17."""
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    await _ask(_graph(vehicle, store))
    other = await build_graph(vehicle, approvals=store, checkpointer=InMemorySaver()).ainvoke(
        {"query": "Mở cửa sổ bên phụ một nửa", "session_id": "ses-1", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-1-b"}},
    )
    assert other["outcome"] == "approval_already_pending"
    assert vehicle.command_count == 0


async def test_s3_is_blocked_before_any_approval_exists():
    """safety_and_hitl.md §Required safety test #4 — S3 không bao giờ hiện popup."""
    vehicle = VehicleSimulator.initial(speed_kph=45.0, gear="D")
    store = ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Mở cửa bên lái")
    assert result["outcome"] == "blocked"
    assert "__interrupt__" not in result
    assert store.pending_for_session("ses-1") is None


async def test_s1_still_runs_without_any_approval():
    """safety_and_hitl.md §Required safety test #1."""
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Đặt điều hòa 22 độ")
    assert result["outcome"] == "completed"
    assert vehicle.state["hvac"]["temperature_c"] == 22
    assert store.pending_for_session("ses-1") is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_hitl_node.py -q`
Expected: FAIL — `TypeError: build_graph() got an unexpected keyword argument 'approvals'`

- [ ] **Step 3: Viết node**

Tạo `src/agents/nodes/approval.py`:

```python
"""Node xin xác nhận cho plan có step S2.

Điểm cốt lõi: khi resume, node **đọc lại store** chứ không tin payload resume. Payload
đó đi qua HTTP nên coi như dữ liệu không tin được; chỉ bản ghi trong store — thứ mà
`decide()` đã ghi — mới là căn cứ.

Bốn điều kiện phải cùng đúng mới được chạy. Cả bốn đường hỏng đều đi `compose` với
zero side effect và **không** consume approval, đúng `safety_and_hitl.md` mục
"Decision flow".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from langgraph.types import interrupt

from src.agents.approval import (
    ApprovalAlreadyPending,
    ApprovalRecord,
    ApprovalStore,
    approval_id_for,
)
from src.agents.contracts import ActionPlan
from src.agents.nodes.compose import describe_step
from src.agents.policy import materialize_action_plan, plan_digest
from src.agents.state import AgentState
from src.agents.vehicle import VehicleSimulator

#: Trạng thái store → outcome của graph, dùng khi bản ghi không ở `approved`.
_OUTCOME_BY_STATUS = {
    "pending": "approval_rejected",
    "rejected": "approval_rejected",
    "expired": "approval_expired",
    "invalidated": "approval_invalidated_state",
    "consumed": "approval_rejected",
}


def describe_plan_for_approval(
    plan: ActionPlan, snapshot: dict[str, Any]
) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Câu hỏi voice-first + tóm tắt before→after cho card IVI.

    `safety_and_hitl.md` mục Approval UX contract cấm câu mơ hồ kiểu "Bạn có chắc
    không?" — phải nêu rõ action, target và before → after. Tốc độ hiện tại được
    đưa vào câu hỏi theo đúng UX mà ticket mô tả; nó là **nội dung hiển thị**, không
    phải điều kiện phân loại (ADR-010).
    """
    summaries: list[dict[str, Any]] = []
    for step in plan.steps:
        summaries.append(
            {
                "tool": step.tool,
                "safety_level": step.safety_level,
                "description": describe_step(step.tool, step.args),
                "before": _read_before(step.tool, step.args, snapshot),
                "after": _read_after(step.tool, step.args),
            }
        )
    actions = " rồi ".join(item["description"] for item in summaries)
    speed = snapshot.get("speed_kph", 0)
    prefix = f"Xe đang chạy {speed:g} km/h. " if speed else ""
    return f"{prefix}Tôi sẽ {actions}. Bạn có đồng ý không?", tuple(summaries)


def _read_before(tool: str, args: dict[str, Any], snapshot: dict[str, Any]) -> Any:
    if tool == "set_window_position":
        return snapshot["windows"][args["window"]]
    if tool == "set_door_state":
        return snapshot["doors"][args["door"]]
    if tool == "set_seat_position":
        return snapshot["seat_position"][args["seat"]][args["axis"]]
    return None


def _read_after(tool: str, args: dict[str, Any]) -> Any:
    return {
        "set_window_position": args.get("percent"),
        "set_door_state": args.get("state"),
        "set_seat_position": args.get("value"),
    }.get(tool)


def make_request_approval_node(
    vehicle: VehicleSimulator, store: ApprovalStore, timeout_seconds: int
) -> Callable[[AgentState], Any]:
    async def request_approval_node(state: AgentState) -> dict:
        plan: ActionPlan = state["action_plan"]
        digest = plan_digest(plan)
        prompt_text, steps_summary = describe_plan_for_approval(plan, state["vehicle_snapshot"])
        now = store.now()
        record = ApprovalRecord(
            approval_id=approval_id_for(digest),
            session_id=plan.session_id,
            turn_id=str(state.get("turn_id", "turn-unknown")),
            plan_id=plan.plan_id,
            plan_digest=digest,
            approved_vehicle_state_version=plan.vehicle_state_version,
            created_at=now,
            expires_at=now + timedelta(seconds=timeout_seconds),
            prompt_text=prompt_text,
            steps_summary=steps_summary,
        )
        try:
            # Idempotent: LangGraph chạy lại thân node từ đầu khi resume, nên hàm
            # này nhận đúng bản ghi này hai lần cho một lượt.
            record = store.create(record)
        except ApprovalAlreadyPending:
            return {"outcome": "approval_already_pending"}

        interrupt(
            {
                "kind": "vehicle_action_approval",
                "approval_id": record.approval_id,
                "plan_id": record.plan_id,
                "prompt_text": record.prompt_text,
                "steps_summary": [dict(item) for item in record.steps_summary],
                "expires_at": record.expires_at.isoformat(),
                "timeout_seconds": timeout_seconds,
            }
        )

        # Từ đây trở xuống chỉ chạy sau khi resume.
        fresh = store.get(record.approval_id)
        if fresh is None:
            return {"outcome": "approval_invalidated_state"}
        if fresh.status != "approved":
            return {"outcome": _OUTCOME_BY_STATUS.get(fresh.status, "approval_rejected")}
        if plan_digest(plan) != fresh.plan_digest:
            return {"outcome": "approval_invalidated_plan"}
        if vehicle.state["state_version"] != fresh.approved_vehicle_state_version:
            return {"outcome": "approval_invalidated_state"}

        # Predicate an toàn phải còn đúng: xe có thể đã lăn bánh trong lúc chờ, biến
        # một action S2 thành S3. Không có bước này thì approval cũ hợp thức hoá nó.
        recomputed = materialize_action_plan(
            state["candidate_action_plan"], vehicle.snapshot(), plan.session_id, plan.vehicle_id
        )
        if plan_digest(recomputed) != fresh.plan_digest:
            return {"outcome": "approval_predicate_failed"}

        store.consume(record.approval_id)
        return {"outcome": "approval_granted", "approval_id": record.approval_id}

    return request_approval_node
```

- [ ] **Step 4: Thêm `now()` vào store**

Node cần đúng đồng hồ mà store đang dùng, nếu không test bơm giờ sẽ lệch. Thêm vào
`src/agents/approval.py`, trong `ApprovalStore`:

```python
    def now(self) -> datetime:
        """Đồng hồ của store. Node phải dùng chung, nếu không test bơm giờ sẽ lệch."""
        return self._clock()
```

- [ ] **Step 5: Chạy test — vẫn fail ở graph, đó là dự kiến**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_hitl_node.py -q`
Expected: FAIL — `build_graph()` chưa nhận `approvals`. Task 3 nối dây.

- [ ] **Step 6: Commit phần node**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/nodes/approval.py src/agents/approval.py
.\.venv\Scripts\python.exe -m ruff format src/agents/nodes/approval.py src/agents/approval.py
git add src/agents/nodes/approval.py src/agents/approval.py tests/test_agents/test_hitl_node.py
git commit -m "feat(agent): node request_approval doc lai store thay vi tin payload resume"
```

---

### Task 3: Nối nhánh approval vào graph

**Files:**
- Modify: `src/agents/graph.py`, `src/agents/nodes/compose.py`, `src/agents/state.py`
- Modify: `tests/test_agents/test_graph.py` (một test đổi hành vi)

**Interfaces:**
- Consumes: `make_request_approval_node` (Task 2), `ApprovalStore` (Task 1)
- Produces: `build_graph(vehicle, *, router=None, rag=None, planner=None, approvals=None, hitl_timeout_seconds=30, checkpointer=None)`

- [ ] **Step 1: Thêm outcome vào composer**

Trong `src/agents/nodes/compose.py`, thêm vào `OUTCOME_MESSAGES`:

```python
    "approval_granted": "Bạn đã đồng ý; tôi thực hiện ngay.",
    "approval_rejected": "Đã hủy theo lựa chọn của bạn.",
    "approval_expired": "Xác nhận đã hết hạn nên tôi không thực hiện.",
    "approval_invalidated_plan": "Lệnh đã thay đổi nên xác nhận cũ không còn dùng được.",
    "approval_invalidated_state": "Trạng thái xe đã thay đổi; bạn xác nhận lại giúp tôi.",
    "approval_predicate_failed": "Xe không còn ở trạng thái an toàn cho lệnh này nữa.",
    "approval_already_pending": "Đang có một lệnh chờ bạn xác nhận; xong lệnh đó rồi tôi làm tiếp.",
```

- [ ] **Step 2: Thêm field vào state**

Trong `src/agents/state.py`, cạnh `action_plan`:

```python
    approval_id: str
```

- [ ] **Step 3: Nối dây graph**

Trong `src/agents/graph.py`:

```python
from src.agents.approval import ApprovalStore
from src.agents.nodes.approval import make_request_approval_node
```

Thay `_route_after_safety` bằng một factory, và thêm `_route_after_approval`. Factory
là cần thiết: khi không bật HITL thì nhánh `approval` không tồn tại, mà trả về một key
không có trong map thì LangGraph báo lỗi lúc dựng graph.

```python
def _make_route_after_safety(has_approval_branch: bool) -> Callable[[AgentState], str]:
    def route_after_safety(state: AgentState) -> str:
        outcome = state.get("outcome")
        if outcome == "safe":
            return "execute"
        if outcome == "approval_required" and has_approval_branch:
            return "approval"
        return "compose"

    return route_after_safety


def _route_after_approval(state: AgentState) -> str:
    return "execute" if state.get("outcome") == "approval_granted" else "compose"
```

Xoá hàm `_route_after_safety` cũ.

Đổi chữ ký và thân `build_graph`:

```python
def build_graph(
    vehicle: VehicleSimulator,
    *,
    router: DeterministicControlRouter | None = None,
    rag: RagNode | None = None,
    planner: Planner | None = None,
    approvals: ApprovalStore | None = None,
    hitl_timeout_seconds: int = 30,
    checkpointer: Any | None = None,
) -> Any:
```

Trong phần dựng graph, thay edge `safety → {execute, compose}`:

```python
    # HITL là opt-in. Không truyền `approvals` thì S2 dừng ở `approval_required` rồi
    # sang compose — vẫn KHÔNG thực thi, nên đây không phải lỗ hổng an toàn. Lý do
    # opt-in: graph có checkpointer thì `ainvoke` bắt buộc kèm `thread_id`, mà phần
    # lớn test hiện có gọi không kèm config.
    safety_targets = {"execute": "execute", "compose": "compose"}
    if approvals is not None:
        builder.add_node("approval", make_request_approval_node(vehicle, approvals, hitl_timeout_seconds))
        builder.add_conditional_edges(
            "approval", _route_after_approval, {"execute": "execute", "compose": "compose"}
        )
        safety_targets["approval"] = "approval"
    builder.add_conditional_edges(
        "safety", _make_route_after_safety(approvals is not None), safety_targets
    )
```

- [ ] **Step 4: Cập nhật test cũ đã đổi hành vi**

Trong `tests/test_agents/test_graph.py`, `test_s2_stops_before_execution_in_this_branch`
vẫn đúng cho đường **không** bật HITL. Đổi tên và docstring cho khớp thực tế mới:

```python
async def test_s2_without_an_approval_store_still_never_executes():
    """HITL là opt-in. Không có store thì S2 dừng ở `approval_required`.

    Không thực thi — đó là điều quan trọng. Đường xin xác nhận nằm ở
    `tests/test_agents/test_hitl_node.py`.
    """
    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Mở cửa sổ bên lái 30 phần trăm")
    assert result["outcome"] == "approval_required"
    assert vehicle.command_count == 0
    assert vehicle.state["windows"]["front_left"] == 0
```

- [ ] **Step 5: Chạy test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow"`
Expected: PASS toàn bộ, gồm cả `test_hitl_node.py` (11 test)

Nếu `test_car_moving_while_waiting_turns_the_action_into_s3` fail vì outcome là
`approval_invalidated_state`: đó vẫn nằm trong tập assert của test (đổi `speed_kph`
trực tiếp không tăng `state_version`, nên check version có thể bắt trước). Cả hai đều
fail-closed và zero side effect — đúng yêu cầu.

- [ ] **Step 6: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/ tests/test_agents/
.\.venv\Scripts\python.exe -m ruff format src/agents/graph.py src/agents/nodes/compose.py src/agents/state.py tests/test_agents/
git add src/agents tests/test_agents
git commit -m "feat(agent): cam nhanh approval giua safety va execute"
```

---

### Task 4: API `POST /api/v1/approvals/{approval_id}/decision`

**Files:**
- Create: `src/api/approvals.py`
- Modify: `src/api/agent_routes.py`, `src/main.py`
- Test: `tests/test_api/test_approval_routes.py`

**Interfaces:**
- Consumes: `ApprovalStore` (1), `build_graph` (3)
- Produces:
  - `src/api/session_state.py`: `get_store() -> ApprovalStore`, `get_graph(session_id, speed_kph)` — nơi duy nhất giữ state giữa hai request
  - `POST /api/v1/approvals/{approval_id}/decision` với `ApprovalDecisionRequest`/`ApprovalDecisionResponse`
  - `/agent/process` trả `status="PENDING_HITL"` + `hitl_action_id` + `timeout_seconds`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api/test_approval_routes.py`:

```python
"""Route quyết định canonical. `hitl_action_id` của ticket chính là `approval_id`."""

OPEN_WINDOW = {"query": "Mở cửa sổ bên lái 30 phần trăm", "vehicle_speed_kmh": 0.0}


async def _pending(client, session_id: str) -> str:
    response = await client.post("/api/v1/agent/process", json={**OPEN_WINDOW, "session_id": session_id})
    body = response.json()
    assert body["status"] == "PENDING_HITL", body
    assert body["hitl_pending"] is True
    assert body["timeout_seconds"] == 30
    return body["hitl_action_id"]


async def test_s2_returns_pending_hitl_with_an_action_id(client):
    approval_id = await _pending(client, "ses-pending")
    assert approval_id.startswith("appr-")


async def test_approve_executes_and_reports_canonical_status(client):
    approval_id = await _pending(client, "ses-approve")
    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approve", "approved_vehicle_state_version": 1},
    )
    body = response.json()
    assert body["approval_status"] == "consumed"
    assert body["plan_status"] == "executed"
    assert body["tool_results"][0]["status"] == "completed"


async def test_reject_cancels_the_plan(client):
    approval_id = await _pending(client, "ses-reject")
    body = (
        await client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "reject", "approved_vehicle_state_version": 1},
        )
    ).json()
    assert body["approval_status"] == "rejected"
    assert body["plan_status"] == "canceled"
    assert body["tool_results"] == []


async def test_replaying_approve_does_not_execute_twice(client):
    approval_id = await _pending(client, "ses-replay")
    payload = {"decision": "approve", "approved_vehicle_state_version": 1}
    first = (await client.post(f"/api/v1/approvals/{approval_id}/decision", json=payload)).json()
    second = (await client.post(f"/api/v1/approvals/{approval_id}/decision", json=payload)).json()
    assert first["plan_status"] == "executed"
    assert first["tool_results"][0]["status"] == "completed"
    # Lần hai: bản ghi đã `consumed`, route không resume graph nữa. `plan_status` vẫn
    # là "executed" vì đó là sự thật — plan **đã** chạy. Bất biến cần khoá là **không
    # chạy lại**, và nó đo bằng `tool_results` rỗng.
    assert second["approval_status"] == "consumed"
    assert second["tool_results"] == []


async def test_unknown_approval_id_is_404(client):
    response = await client.post(
        "/api/v1/approvals/appr-khongtontai/decision",
        json={"decision": "approve", "approved_vehicle_state_version": 1},
    )
    assert response.status_code == 404


async def test_route_is_in_the_public_openapi_surface():
    """Khác `/agent/process`: đây là một trong 12 interface P0 của api_spec.md."""
    from src.main import app

    assert "/api/v1/approvals/{approval_id}/decision" in app.openapi()["paths"]


async def test_s1_command_does_not_create_any_approval(client):
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Đặt điều hòa 22 độ", "vehicle_speed_kmh": 0.0, "session_id": "ses-s1"},
    )
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["hitl_pending"] is False
    assert "hitl_action_id" not in body or body["hitl_action_id"] is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api/test_approval_routes.py -q`
Expected: FAIL — `/agent/process` trả `APPROVAL_REQUIRED`, chưa có `hitl_action_id`

- [ ] **Step 3: Tách state giữa hai request ra một chỗ**

Tạo `src/api/session_state.py`:

```python
"""State sống giữa hai HTTP request: simulator, store approval, và graph đã compile.

Tất cả in-memory và mất khi restart — đánh đổi có chủ đích cho demo PC, ghi trong
spec HITL. Graph phải được **giữ lại** giữa hai request vì `interrupt()` chỉ resume
được trên đúng instance có checkpointer chứa checkpoint đó.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.agents.vehicle import VehicleSimulator
from src.config import get_settings

_STORE = ApprovalStore()
_VEHICLES: dict[str, VehicleSimulator] = {}
_GRAPHS: dict[str, Any] = {}


def get_store() -> ApprovalStore:
    return _STORE


def get_vehicle(session_id: str, speed_kph: float | None = None) -> VehicleSimulator:
    vehicle = _VEHICLES.get(session_id)
    if vehicle is None:
        vehicle = VehicleSimulator.initial()
        _VEHICLES[session_id] = vehicle
    if speed_kph is not None:
        vehicle.state["speed_kph"] = speed_kph
        vehicle.state["gear"] = "P" if speed_kph == 0 else "D"
    return vehicle


def get_graph(session_id: str):
    """Một graph mỗi session, giữ nguyên qua các request để resume được interrupt."""
    graph = _GRAPHS.get(session_id)
    if graph is None:
        graph = build_graph(
            get_vehicle(session_id),
            approvals=_STORE,
            hitl_timeout_seconds=get_settings().hitl_timeout_seconds,
            checkpointer=InMemorySaver(),
        )
        _GRAPHS[session_id] = graph
    return graph


def thread_config(session_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": session_id}}


def reset() -> None:
    """Chỉ dùng trong test."""
    _VEHICLES.clear()
    _GRAPHS.clear()
```

- [ ] **Step 4: Viết route quyết định**

Tạo `src/api/approvals.py`:

```python
"""`POST /api/v1/approvals/{approval_id}/decision` — một trong 12 interface P0.

Đây là route **duy nhất** commit quyết định. Ticket SCRUM-18 mô tả
`POST /api/v1/hitl/confirm` với `{hitl_action_id, confirmed}`; trưởng nhóm chốt trên
PR #23 là giữ canonical naming end-to-end nên route đó không được làm.
`hitl_action_id` chính là `approval_id`.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict

from src.api.session_state import get_graph, get_store, thread_config

router = APIRouter()


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    approved_vehicle_state_version: int | None = None


class ApprovalDecisionResponse(BaseModel):
    approval_status: str
    plan_status: str
    tool_results: list[dict[str, Any]] = []


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalDecisionResponse)
async def decide(approval_id: str, request: ApprovalDecisionRequest) -> ApprovalDecisionResponse:
    store = get_store()
    record = store.get(approval_id)
    if record is None:
        raise HTTPException(status_code=404, detail="approval không tồn tại")

    # Chốt quyết định TRƯỚC khi resume: node approval đọc lại store chứ không tin
    # payload resume, nên store phải đã ở trạng thái cuối cùng lúc graph chạy tiếp.
    decided = store.decide(approval_id, approve=request.decision == "approve")

    if decided.status != "approved":
        # Hết hạn, đã bị từ chối, hoặc đã consume — không resume graph, tránh chạy
        # lại một lượt đã kết thúc.
        return ApprovalDecisionResponse(
            approval_status=decided.status,
            plan_status="canceled" if decided.status != "consumed" else "executed",
        )

    graph = get_graph(record.session_id)
    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=thread_config(record.session_id))
    outcome = result.get("outcome", "approval_rejected")
    if outcome != "completed":
        # Node đã từ chối ở một trong bốn kiểm tra fail-closed nên approval chưa bị
        # consume. Đánh dấu `invalidated` để nó không nằm lại ở `approved` — trạng
        # thái đó gợi ý sai rằng vẫn còn dùng được.
        store.invalidate(approval_id)
    return ApprovalDecisionResponse(
        approval_status=store.get(approval_id).status,
        plan_status="executed" if outcome == "completed" else "canceled",
        tool_results=[r.model_dump(mode="json") for r in result.get("step_results", [])],
    )
```

- [ ] **Step 5: Cho `/agent/process` trả `PENDING_HITL`**

Trong `src/api/agent_routes.py`, thay phần dựng response:

```python
    graph = get_graph(request.session_id)
    result = await graph.ainvoke(
        {
            "query": request.query,
            "session_id": request.session_id,
            "vehicle_id": "veh-demo",
            "turn_id": f"turn-{started_ns}",
        },
        config=thread_config(request.session_id),
    )

    pending = result.get("__interrupt__")
    if pending:
        payload = pending[0].value
        return AgentProcessResponse(
            status="PENDING_HITL",
            intent=result.get("intent", "none"),
            response_text=payload["prompt_text"],
            tool_calls=[
                AgentToolCall(tool_name=item["tool"], parameters={"after": item["after"]})
                for item in payload["steps_summary"]
            ],
            hitl_pending=True,
            hitl_action_id=payload["approval_id"],
            timeout_seconds=payload["timeout_seconds"],
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )
```

Thêm hai field vào `AgentProcessResponse`:

```python
    hitl_action_id: str | None = None
    timeout_seconds: int | None = None
```

Đổi `get_session_vehicle` sang dùng `session_state.get_vehicle`, xoá `_VEHICLES` cục bộ
trong file này (giờ nằm ở `session_state.py`).

- [ ] **Step 6: Đăng ký router**

Trong `src/main.py`, cùng khối import và include:

```python
from src.api.approvals import router as approvals_router
...
app.include_router(approvals_router, prefix="/api/v1")
```

- [ ] **Step 7: Cô lập state giữa các test**

Trong `tests/conftest.py`, thêm fixture tự chạy:

```python
@pytest.fixture(autouse=True)
def _reset_session_state():
    """Simulator/graph sống ở module level nên phải dọn giữa các test."""
    from src.api import session_state

    session_state.reset()
    yield
    session_state.reset()
```

- [ ] **Step 8: Chạy test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow"`
Expected: PASS toàn bộ

- [ ] **Step 9: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/api/ tests/
.\.venv\Scripts\python.exe -m ruff format src/api/ tests/conftest.py tests/test_api/
git add src/api src/main.py tests/conftest.py tests/test_api
git commit -m "feat(api): POST /api/v1/approvals/{id}/decision va PENDING_HITL"
```

---

### Task 5: Test an toàn ánh xạ `safety_and_hitl.md`

**Files:**
- Create: `tests/test_agents/test_hitl_safety.py`

**Interfaces:**
- Consumes: mọi thứ từ Task 1–4

- [ ] **Step 1: Viết test**

Tạo `tests/test_agents/test_hitl_safety.py`. Mỗi test ghi rõ số hiệu nó phủ trong
`docs/safety_and_hitl.md` §Required safety tests, để người đọc đối chiếu được:

```python
"""Ánh xạ trực tiếp `docs/safety_and_hitl.md` §Required safety tests.

Phủ 7/19: #1, #2, #4, #5, #6, #12, #17. Mười hai test còn lại cần executor nhiều
step, MQTT hoặc voice — ngoài phạm vi branch này. Đừng tuyên bố phủ hết 19.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.agents.policy import classify
from src.agents.vehicle import VehicleSimulator

CONFIG = {"configurable": {"thread_id": "ses-safety"}}


def _graph(vehicle, store):
    return build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())


async def _ask(graph, query):
    return await graph.ainvoke(
        {"query": query, "session_id": "ses-safety", "vehicle_id": "veh-1"}, config=CONFIG
    )


async def test_safety_1_s1_runs_without_approval():
    """#1: S1 hợp lệ chạy không cần approval, nhưng vẫn qua policy."""
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Đặt điều hòa 22 độ")
    assert result["outcome"] == "completed"
    assert store.pending_for_session("ses-safety") is None


async def test_safety_2_s2_without_approval_is_rejected():
    """#2: S2 không có approval thì không chạy."""
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph, "Mở cửa sổ bên lái 30 phần trăm"))["__interrupt__"][0].value["approval_id"]
    result = await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert result["outcome"] == "approval_rejected"
    assert vehicle.command_count == 0


async def test_safety_4_s3_is_blocked_before_the_approval_card_exists():
    """#4: S3 bị chặn trước khi tạo hoặc hiển thị approval."""
    vehicle, store = VehicleSimulator.initial(speed_kph=45.0, gear="D"), ApprovalStore()
    result = await _ask(_graph(vehicle, store), "Mở cửa bên lái")
    assert result["outcome"] == "blocked"
    assert "__interrupt__" not in result
    assert store.pending_for_session("ses-safety") is None


async def test_safety_5_replayed_approval_cannot_execute_twice():
    """#5: approval hết hạn/replay bị từ chối; không dùng lại cho lượt khác."""
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    graph = _graph(vehicle, store)
    approval_id = (await _ask(graph, "Mở cửa sổ bên lái 30 phần trăm"))["__interrupt__"][0].value["approval_id"]
    store.decide(approval_id, approve=True)
    await graph.ainvoke(Command(resume={"approval_id": approval_id}), config=CONFIG)
    assert vehicle.command_count == 1
    assert store.get(approval_id).status == "consumed"
    assert store.consume(approval_id).status == "consumed"
    assert vehicle.command_count == 1


def test_safety_6_door_and_seat_are_s2_only_when_stationary():
    """#6: door/seat position là S2 chỉ khi speed_kph == 0 && gear == P."""
    stationary = VehicleSimulator.initial().snapshot()
    moving = VehicleSimulator.initial(speed_kph=45.0, gear="D").snapshot()
    for tool in ("set_door_state", "set_seat_position"):
        assert classify(tool, stationary) == "S2"
        assert classify(tool, moving) == "S3"


def test_safety_12_window_is_always_s2():
    """#12: window luôn S2, kể cả khi xe đứng yên."""
    for snapshot in (
        VehicleSimulator.initial().snapshot(),
        VehicleSimulator.initial(speed_kph=45.0, gear="D").snapshot(),
    ):
        assert classify("set_window_position", snapshot) == "S2"


async def test_safety_17_second_pending_creates_no_artifacts():
    """#17: tối đa một pending/session; request thứ hai tạo zero plan/approval/side effect."""
    vehicle, store = VehicleSimulator.initial(), ApprovalStore()
    await _ask(_graph(vehicle, store), "Mở cửa sổ bên lái 30 phần trăm")
    second = await build_graph(vehicle, approvals=store, checkpointer=InMemorySaver()).ainvoke(
        {"query": "Mở cửa sổ bên phụ một nửa", "session_id": "ses-safety", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-safety-2"}},
    )
    assert second["outcome"] == "approval_already_pending"
    assert vehicle.command_count == 0
    assert vehicle.state["windows"]["front_right"] == 0
```

- [ ] **Step 2: Chạy test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_hitl_safety.py -q -v`
Expected: PASS — 7 passed

- [ ] **Step 3: Chạy toàn bộ suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow"`
Expected: PASS toàn bộ

- [ ] **Step 4: Commit**

```bash
.\.venv\Scripts\python.exe -m ruff check tests/test_agents/test_hitl_safety.py
.\.venv\Scripts\python.exe -m ruff format tests/test_agents/test_hitl_safety.py
git add tests/test_agents/test_hitl_safety.py
git commit -m "test(safety): phu 7/19 required safety test cua safety_and_hitl.md"
```

---

### Task 6: Tài liệu

**Files:**
- Modify: `README.md`, `WORKLOG.md`, `JOURNAL.md`

- [ ] **Step 1: README**

Trong bảng "Trạng thái Agent Pipeline (WS2)", thay dòng HITL:

```markdown
| HITL (SCRUM-18) | **Chạy được trên PC** | `POST /api/v1/approvals/{approval_id}/decision`. Phủ **7/19** required safety test của `safety_and_hitl.md` (#1, #2, #4, #5, #6, #12, #17) — xem `tests/test_agents/test_hitl_safety.py` |
```

Thêm ngay dưới bảng:

```markdown
> **Ba giới hạn của HITL bản này.** Approval nằm in-memory nên restart là mất pending.
> Hết hạn được phát hiện lúc **đọc**, không có worker phát `turn.canceled` tại
> `expires_at` — cần WebSocket, thuộc WS4. Xác nhận **bằng giọng nói** chưa làm; hiện
> chỉ có REST, đúng như `safety_and_hitl.md` yêu cầu (voice chỉ được phát intent, không
> được commit quyết định).
```

- [ ] **Step 2: WORKLOG**

Thêm mục mới theo đúng định dạng bảng đang dùng, nêu: route canonical (không làm
`/hitl/confirm`), phát hiện LangGraph chạy lại thân node khi resume và cách xử lý
(`approval_id` tất định + `create` idempotent), 7/19 safety test, và ba giới hạn ở trên.

- [ ] **Step 3: JOURNAL**

Đánh dấu SCRUM-18 xong trong backlog Sprint 2. Thêm một đoạn quyết định ngắn: vì sao
HITL là opt-in ở `build_graph` (checkpointer bắt buộc `thread_id`, và S2 không có store
vẫn không thực thi nên không phải lỗ hổng).

- [ ] **Step 4: Chạy suite lần cuối và commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow"
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add README.md WORKLOG.md JOURNAL.md
git commit -m "docs: trang thai HITL va ba gioi han cua ban nay"
```

---

## Đối chiếu Acceptance Criteria (ticket SCRUM-18)

| AC | Task | Bằng chứng |
|---|---|---|
| Tự động phát hiện lệnh nguy hiểm | 3 | `test_safety_6`, `test_safety_12`. **Không** dùng ngưỡng `speed > 5` — ADR-010 |
| Trả trạng thái `PENDING_HITL` kèm `hitl_action_id` | 4 | `test_s2_returns_pending_hitl_with_an_action_id` |
| Tự động hủy lệnh nếu timeout | 1, 2 | `test_expiry_is_detected_at_read_time`, `test_expired_approval_never_executes` |
| Deliverable: HITL Checker Node | 2, 3 | `src/agents/nodes/approval.py` |
| Deliverable: API xác nhận | 4 | `POST /api/v1/approvals/{approval_id}/decision` — canonical, **không** `/hitl/confirm` |

## Còn nợ sau plan này

- **Worker deadline chủ động** phát `turn.canceled(reason="approval_expired")` tại
  `expires_at` — cần WebSocket, WS4 sở hữu.
- **Xác nhận bằng giọng nói** (`approval.intent.detected`) — cần STT, đầu việc voice.
- **Persistence** cho approval — in-memory, restart là mất.
- **12/19 required safety test** còn lại — cần executor nhiều step, MQTT.
- **Mixed plan nhiều S2** — cấu trúc đã hỗ trợ (một approval bind cả plan) nhưng router
  hiện chỉ sinh plan một step nên chưa có case thật để test.

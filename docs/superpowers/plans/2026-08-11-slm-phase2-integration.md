# Phase 2 — Tích hợp SLM một-lần-gọi (planner + trò chuyện) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khi `slm_enabled=true`, câu mà luật bó tay đi qua **một** lần gọi model trả về `{"kind":"plan",…}` (vào cổng an toàn như mọi lệnh) hoặc `{"kind":"chitchat","reply":…}` (đi thẳng compose, không chạm executor). Khi `slm_enabled=false` (mặc định), **không một hành vi nào đổi** — đó là cơ chế fallback cho máy đồng đội (ADR-016).

**Architecture:** Giữ nguyên hình graph — không thêm node, không thêm cạnh. `slm_stage` parse union thay vì chỉ candidate; outcome mới `chitchat` đi cạnh `slm → compose` **sẵn có**. `ivi_events.py` (vùng của Thành) **không sửa** — outcome `chitchat` rơi vào nhánh đuôi tổng quát, khoá bằng test.

**Tech Stack:** như hiện tại. Cấu hình đã đo của SPIKE-003 (grammar union, few-shot v2, prompt utterance-only) bê nguyên vào — **không sáng tác cấu hình mới chưa đo**.

**Design:** `docs/superpowers/specs/2026-08-11-slm-three-roles-design.md` mục "Quyết định thiết kế trung tâm". **Cổng:** ADR-016 (ba câu đã chốt 2026-08-11; Status Proposed — nhóm phản biện khi review PR).

## Global Constraints

- Chạy test: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`. **Ghi baseline trước Task 1** và mỗi task không được làm đỏ test ngoài các test plan nói rõ là đổi-có-chủ-đích.
- `src/services/ivi_events.py` **không được sửa** — nếu một bước nào hoá ra cần sửa nó, DỪNG và hỏi (thoả thuận vùng của Thành).
- **Không mang hardcode máy-demo vào `src/`** (ADR-016): không `Vulkan1`, không `-t 6`, không đường dẫn model tuyệt đối. Mọi thứ máy-riêng nằm ở `scripts/` hoặc config.
- Prompt/schema trong `src/` phải **bằng đúng** bản đã đo ở SPIKE-003 (`scripts/spike3_prompt.txt` few-shot v2, `scripts/spike3_schema.json`) — số đo chỉ có nghĩa cho cấu hình được đo. Đổi một chữ trong prompt là phải đo lại bậc C.
- CI không có llama-server: mọi test dùng stub planner. Kiểm model thật là bước tay cuối, trên máy demo.
- Vòng đời SLM giữ nguyên: **một** lần sửa schema, hết thì `clarify`. Không retry mở.

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/agents/slm.py` (sửa) | `UNION_SCHEMA`, `SLM_UNION_PROMPT`, `parse_slm_output`; `QwenPlanner` gửi grammar + cache | 1, 5 |
| `src/agents/state.py` (sửa) | Channel `chitchat_reply` | 2 |
| `src/agents/nodes/normalize.py` (sửa) | Reset `chitchat_reply` mỗi lượt | 2 |
| `src/agents/graph.py` (sửa) | `slm_stage` parse union, outcome `chitchat` | 3 |
| `src/agents/nodes/compose.py` (sửa) | Nhánh `chitchat` đọc reply từ state | 3 |
| `src/api/session_state.py` (sửa) | Dựng `QwenPlanner` khi `slm_enabled` | 5 |
| `scripts/run_slm_server.ps1` (tạo) | Server resident, device/threads **tự dò** | 6 |
| `tests/test_agents/test_slm_union.py` (tạo) | Parse union + luồng graph chitchat | 1–3 |

---

### Task 1: Hợp đồng union trong `slm.py`

**Files:**
- Modify: `src/agents/slm.py`
- Test: `tests/test_agents/test_slm_union.py` (tạo)

**Interfaces:**
- Produces: `UNION_SCHEMA: dict` (bê nguyên `scripts/spike3_schema.json`); `SLM_UNION_PROMPT: str` (bê nguyên `scripts/spike3_prompt.txt` few-shot v2, kết thúc `"Câu: "`); `CHITCHAT_MAX_CHARS = 240`; `parse_slm_output(raw: str) -> CandidateActionPlan | str` — trả `CandidateActionPlan` cho `kind=plan`, trả `str` (reply đã strip) cho `kind=chitchat`, raise `SlmSchemaError` cho mọi thứ khác. Task 3/5 dùng các tên này.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_agents/test_slm_union.py`:

```python
"""Hợp đồng union `plan | chitchat` — một lần gọi, hai hình dạng hợp lệ, không có thứ ba."""

import pytest

from src.agents.contracts import CandidateActionPlan
from src.agents.slm import CHITCHAT_MAX_CHARS, SlmSchemaError, parse_slm_output

PLAN_RAW = (
    '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,'
    '"tool":"set_hvac_temperature","args":{"temperature_c":24},"depends_on":[]}]}'
)


def test_plan_output_becomes_a_candidate_plan():
    out = parse_slm_output(PLAN_RAW)
    assert isinstance(out, CandidateActionPlan)
    assert out.steps[0].tool == "set_hvac_temperature"


def test_chitchat_output_becomes_a_stripped_reply():
    out = parse_slm_output('{"kind":"chitchat","reply":"  Chào bạn!  "}')
    assert out == "Chào bạn!"


def test_a_third_shape_is_rejected_not_guessed():
    """Grammar chặn hình dạng thứ ba lúc sinh; parse phải chặn lần nữa lúc đọc —
    hai lớp độc lập, vì stub/test và server cũ không đi qua grammar."""
    with pytest.raises(SlmSchemaError):
        parse_slm_output('{"kind":"help","text":"gì đó"}')


def test_plan_with_planner_supplied_safety_level_is_rejected():
    """Bất biến ADR-006 giữ nguyên qua đường union: model không được gán safety."""
    raw = PLAN_RAW.replace('"depends_on":[]', '"depends_on":[],"safety_level":"S1"')
    with pytest.raises(SlmSchemaError):
        parse_slm_output(raw)


def test_empty_reply_is_a_schema_error_not_a_silent_blank():
    with pytest.raises(SlmSchemaError):
        parse_slm_output('{"kind":"chitchat","reply":"   "}')


def test_overlong_reply_is_truncated_to_the_measured_cap():
    reply = "a" * 500
    out = parse_slm_output(f'{{"kind":"chitchat","reply":"{reply}"}}')
    assert len(out) == CHITCHAT_MAX_CHARS
```

- [ ] **Step 2: Chạy, xem đỏ đúng lý do**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_union.py -q`
Expected: FAIL `ImportError: cannot import name 'parse_slm_output'`

- [ ] **Step 3: Thêm vào `src/agents/slm.py`**

Sau `parse_candidate` (giữ nguyên hàm đó — nhánh plan tái dùng nó):

```python
#: Trần độ dài reply — bằng `maxLength` trong UNION_SCHEMA, là cấu hình đã đo SPIKE-003.
CHITCHAT_MAX_CHARS = 240

#: JSON Schema union — BÊ NGUYÊN scripts/spike3_schema.json (cấu hình đã đo bậc B/C).
#: llama-server tự chuyển thành grammar; đổi schema là phải đo lại bậc C.
UNION_SCHEMA: dict[str, Any] = { ... }  # dán nguyên văn nội dung scripts/spike3_schema.json

#: Prompt few-shot v2 — BÊ NGUYÊN scripts/spike3_prompt.txt (kind 0,906 / tool 0,828
#: trên bộ dò). Kết thúc bằng "Câu: " để ghép thẳng câu người dùng.
SLM_UNION_PROMPT = """..."""  # dán nguyên văn nội dung scripts/spike3_prompt.txt


def parse_slm_output(raw: str) -> CandidateActionPlan | str:
    """Một lần gọi, đúng hai hình dạng hợp lệ; mọi thứ khác là `SlmSchemaError`.

    Grammar đã chặn hình dạng thứ ba lúc sinh, nhưng parse chặn **lần nữa** vì stub
    trong test và bất kỳ server nào không bật grammar đều không có lớp thứ nhất.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SlmSchemaError(f"output không phải JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SlmSchemaError("output không phải object")
    kind = payload.pop("kind", None)
    if kind == "chitchat":
        reply = str(payload.get("reply", "")).strip()
        if not reply:
            raise SlmSchemaError("chitchat rỗng")
        return reply[:CHITCHAT_MAX_CHARS]
    if kind == "plan":
        # `kind` đã pop — phần còn lại đúng shape CandidateActionPlan (extra=forbid),
        # đi qua đúng closed-schema check + validate_args sẵn có.
        return parse_candidate(json.dumps(payload, ensure_ascii=False))
    raise SlmSchemaError(f"kind không hợp lệ: {kind!r}")
```

Dán nội dung thật cho `UNION_SCHEMA`/`SLM_UNION_PROMPT` từ hai file scripts (copy nguyên văn — hai nguồn phải bằng nhau từng ký tự; script spike giữ nguyên làm bản đo đối chiếu).

- [ ] **Step 4: Chạy xanh + toàn suite**

Run: cả file mới lẫn `pytest tests/ -q`. Expected: 6 test mới xanh, không test cũ nào đỏ (chưa ai gọi `parse_slm_output`).

- [ ] **Step 5: Commit**

```bash
git add src/agents/slm.py tests/test_agents/test_slm_union.py
git commit -m "feat(slm): hop dong union plan|chitchat voi parse hai lop"
```

---

### Task 2: Channel `chitchat_reply` + reset mỗi lượt

**Files:**
- Modify: `src/agents/state.py` (thêm `chitchat_reply: str` cạnh `response_text`)
- Modify: `src/agents/nodes/normalize.py` (`_PER_TURN_RESET` thêm `"chitchat_reply": ""`)
- Test: `tests/test_agents/test_slm_union.py`

**Interfaces:**
- Produces: `state["chitchat_reply"]` — Task 3 ghi, compose đọc, normalize dọn.

- [ ] **Step 1: Test đỏ — rò giữa hai lượt là bug thật của thread checkpointer**

Thêm vào `tests/test_agents/test_slm_union.py`:

```python
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway

CONFIG = {"configurable": {"thread_id": "ses-chit"}}


class _ChitchatPlanner:
    def propose(self, normalized_text: str, snapshot: dict) -> str:
        return '{"kind":"chitchat","reply":"Chào bạn, tôi là VIVI!"}'


async def test_chitchat_reply_does_not_leak_into_the_next_turn():
    """Một phiên dùng chung thread checkpointer; lượt sau kế thừa state lượt trước.
    Không reset thì lệnh 'Bật điều hòa' của lượt 2 mang theo reply của lượt 1."""
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_ChitchatPlanner(), checkpointer=InMemorySaver())

    first = await graph.ainvoke(
        {"query": "Hôm nay trời đẹp nhỉ", "session_id": "ses-chit", "vehicle_id": "veh-1"}, config=CONFIG
    )
    assert first["chitchat_reply"] == "Chào bạn, tôi là VIVI!"

    second = await graph.ainvoke(
        {"query": "Bật điều hòa", "session_id": "ses-chit", "vehicle_id": "veh-1"}, config=CONFIG
    )
    assert second["chitchat_reply"] == ""
    assert second["outcome"] == "completed"  # lệnh luật bắt được, chạy bình thường
```

- [ ] **Step 2: Chạy, xem đỏ** — Expected: KeyError/AssertionError vì channel chưa tồn tại (test này cũng đỏ vì Task 3 chưa làm — chấp nhận, nó xanh sau Task 3; chạy `-k leak` để theo dõi riêng).

- [ ] **Step 3: Thêm field + reset** như mô tả Files. Một dòng mỗi file, đặt cạnh `response_text` sẵn có.

- [ ] **Step 4: Commit**

```bash
git add src/agents/state.py src/agents/nodes/normalize.py tests/test_agents/test_slm_union.py
git commit -m "feat(agent): channel chitchat_reply, reset moi luot"
```

---

### Task 3: `slm_stage` parse union + compose đọc reply

**ĐỔI HÀNH VI CÓ CHỦ ĐÍCH:** stub trong `tests/test_agents/test_slm.py` đang trả JSON candidate **không có `kind`** — sau task này chúng phải trả format union. Đây là hợp đồng mới của planner, không phải sửa-test-cho-xanh; ghi lý do trong commit.

**Files:**
- Modify: `src/agents/graph.py` — thân `slm_stage`
- Modify: `src/agents/nodes/compose.py`
- Modify: `tests/test_agents/test_slm.py` — stub sang union format
- Test: `tests/test_agents/test_slm_union.py`

**Interfaces:**
- Consumes: `parse_slm_output` (Task 1), channel `chitchat_reply` (Task 2).
- Produces: outcome mới `"chitchat"`; đi cạnh `slm → compose` sẵn có (`_route_after_slm` trả `compose` cho mọi outcome ≠ `control` — không sửa hàm đó).

- [ ] **Step 1: Test đỏ cho luồng chitchat trọn graph**

Thêm vào `tests/test_agents/test_slm_union.py`:

```python
async def test_social_utterance_flows_to_a_natural_reply_not_clarify():
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_ChitchatPlanner(), checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        {"query": "Cảm ơn nhé", "session_id": "ses-chit", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-social"}},
    )

    assert result["outcome"] == "chitchat"
    assert result["response_text"] == "Chào bạn, tôi là VIVI!"
    assert gateway.command_count == 0  # không chạm executor — tính chất kiến trúc


class _PlanPlanner:
    def propose(self, normalized_text: str, snapshot: dict) -> str:
        return (
            '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,'
            '"tool":"set_hvac_temperature","args":{"temperature_c":22},"depends_on":[]}]}'
        )


async def test_plan_output_still_goes_through_the_safety_gate():
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_PlanPlanner(), checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        {"query": "làm mát giùm cái", "session_id": "ses-plan", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-plan"}},
    )

    # S1 → chạy thẳng, qua validate/safety/execute như lệnh luật bắt được
    assert result["outcome"] == "completed"
    assert result["route_source"] == "slm"
```

- [ ] **Step 2: Chạy, xem đỏ** — Expected: outcome hiện tại là `clarify` (parse_candidate không hiểu `kind`).

- [ ] **Step 3: Sửa `slm_stage` trong `graph.py`** — thay hai dòng giữa vòng lặp:

```python
        for attempt in range(2):
            try:
                raw = planner.propose(text if attempt == 0 else f"{text}\n{REPAIR_HINT}", snapshot)
                out = parse_slm_output(raw)
            except (SlmSchemaError, OSError):
                continue
            if isinstance(out, str):
                # Trò chuyện: không có gì để validate/safety — không chạm executor.
                return {"outcome": "chitchat", "chitchat_reply": out, "route_source": "slm"}
            return {"candidate_action_plan": out, "outcome": "control", "route_source": "slm"}
        return {"outcome": "clarify", "route_source": "fallback"}
```

Đổi import `parse_candidate` → `parse_slm_output` ở đầu file (grep để chắc `parse_candidate` không còn được graph import).

- [ ] **Step 4: Nhánh compose** — trong `compose.py`, chỗ chọn message:

```python
    if outcome == "chitchat":
        # Reply do model soạn, đã qua strip + trần độ dài ở parse_slm_output.
        message = state.get("chitchat_reply") or OUTCOME_MESSAGES["clarify"]
    elif outcome == "offer":
        message = _compose_offer(state)
    else:
        message = OUTCOME_MESSAGES.get(outcome, _FALLBACK)
```

(viết lại đúng theo cấu trúc dòng 93 hiện có — nếu hiện là biểu thức một dòng thì tách thành if/elif/else như trên).

- [ ] **Step 5: Cập nhật stub `test_slm.py`** sang union format (thêm `"kind":"plan",` vào chuỗi JSON của StubPlanner; test repair giữ nguyên số lần thử).

- [ ] **Step 6: Toàn suite xanh** (gồm test leak của Task 2 giờ phải xanh). Commit:

```bash
git add src/agents/graph.py src/agents/nodes/compose.py tests/test_agents/
git commit -m "feat(agent): slm_stage mot lan goi hai hinh dang, outcome chitchat"
```

---

### Task 4: Khoá chuỗi sự kiện `/ws/ivi` cho chitchat — KHÔNG sửa file của Thành

**Files:**
- Test: `tests/test_services/test_ivi_events.py` (chỉ thêm test)

- [ ] **Step 1: Viết test** (kỳ vọng **xanh ngay** — đây là test khoá hiện trạng, chứng minh không cần sửa `ivi_events.py`; nếu nó đỏ thì DỪNG, báo lại, vì nghĩa là outcome chitchat cần nhánh riêng trong file của Thành):

```python
async def test_chitchat_outcome_flows_through_the_generic_tail():
    """Outcome `chitchat` không có nhánh riêng trong emit_turn_lifecycle — nó rơi vào
    đuôi tổng quát composing → assistant.response → turn.completed. Test này khoá điều
    đó lại: ai thêm nhánh riêng cho chitchat là phải sửa test này một cách có ý thức."""
    bus = _RecordingBus()
    result = {"outcome": "chitchat", "response_text": "Chào bạn, tôi là VIVI!", "citations": []}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types == ["assistant.status", "assistant.response", "turn.completed"]
    assert bus.events[0]["payload"]["state"] == "composing"
    assert bus.events[1]["payload"]["display_text"] == "Chào bạn, tôi là VIVI!"
```

- [ ] **Step 2: Chạy + commit**

```bash
git add tests/test_services/test_ivi_events.py
git commit -m "test(ivi): khoa chuoi su kien chitchat qua duoi tong quat, khong sua file cua Thanh"
```

---

### Task 5: `QwenPlanner` theo cấu hình đã đo + nối cờ `slm_enabled`

**Files:**
- Modify: `src/agents/slm.py` — `QwenPlanner.propose` + xoá `SYSTEM_PROMPT` cũ
- Modify: `src/api/session_state.py` — `get_graph`
- Test: `tests/test_agents/test_slm_union.py`, `tests/test_api/test_session_state.py`

**Interfaces:**
- Consumes: `SLM_UNION_PROMPT`, `UNION_SCHEMA` (Task 1); `Settings.slm_*` (đã có trong `config.py`).

- [ ] **Step 1: Test đỏ cho body request**

```python
def test_qwen_planner_sends_the_measured_config(monkeypatch):
    """Prompt utterance-only + grammar + cache — đúng cấu hình đã đo SPIKE-003.

    Snapshot cố ý KHÔNG vào prompt: (1) cấu hình được đo không có nó, số chỉ có nghĩa
    cho cấu hình đó; (2) snapshot đổi mỗi lượt → prefix đổi → prompt cache trượt, mất
    luôn kinh tế 140 ms/call. Chữ ký propose giữ snapshot vì Protocol, impl bỏ qua.
    """
    import httpx

    from src.agents.slm import SLM_UNION_PROMPT, UNION_SCHEMA, QwenPlanner

    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured.update(url=url, body=json)

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"content": '{"kind":"chitchat","reply":"ok"}'}

        return _R()

    monkeypatch.setattr(httpx, "post", _fake_post)
    QwenPlanner("http://127.0.0.1:8093", "m").propose("Cảm ơn nhé", {"state_version": 9})

    assert captured["body"]["prompt"] == SLM_UNION_PROMPT + "Cảm ơn nhé\nJSON:"
    assert captured["body"]["json_schema"] == UNION_SCHEMA
    assert captured["body"]["cache_prompt"] is True
    assert captured["body"]["n_predict"] == 160
    assert "Trạng thái xe" not in captured["body"]["prompt"]
```

- [ ] **Step 2: Chạy đỏ, rồi viết lại `propose`**

```python
    def propose(self, normalized_text: str, snapshot: dict[str, Any]) -> str:
        """`snapshot` nhận theo Protocol nhưng cố ý không dùng — xem test
        `test_qwen_planner_sends_the_measured_config` cho hai lý do (cấu hình đã đo,
        và kinh tế prompt cache)."""
        import httpx

        response = httpx.post(
            f"{self._endpoint}/completion",
            json={
                "prompt": SLM_UNION_PROMPT + normalized_text + "\nJSON:",
                "temperature": 0,
                "n_predict": 160,
                "cache_prompt": True,
                "json_schema": UNION_SCHEMA,
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return str(response.json().get("content", "")).strip()
```

Xoá `SYSTEM_PROMPT` cũ và `_ALLOWED_TOOLS` nếu không còn ai import (grep trước khi xoá; còn ai dùng thì để lại và ghi chú).

- [ ] **Step 3: Nối cờ trong `session_state.get_graph`**

```python
        settings = get_settings()
        planner = None
        if settings.slm_enabled:
            # Import tại chỗ: đường mặc định (slm off) không trả chi phí import nào thêm.
            from src.agents.slm import QwenPlanner

            planner = QwenPlanner(settings.slm_endpoint, settings.slm_model_id, settings.slm_timeout_s)
        graph = build_graph(
            get_vehicle_gateway(),
            planner=planner,
            approvals=_STORE,
            hitl_timeout_seconds=settings.hitl_timeout_seconds,
            checkpointer=InMemorySaver(),
        )
```

- [ ] **Step 4: Test wiring** — thêm vào `tests/test_api/test_session_state.py`:

```python
def test_slm_disabled_means_no_planner_and_no_behavior_change(monkeypatch):
    """Cơ chế fallback của ADR-016: máy không bật SLM thì graph y hệt hôm nay."""
    from src.config import get_settings

    assert get_settings().slm_enabled is False  # mặc định repo — đổi default là đổi ADR
    graph = session_state.get_graph("ses-no-slm")
    assert graph is not None  # dựng được không cần llama-server
```

- [ ] **Step 5: Toàn suite + lint + commit**

```bash
git add src/agents/slm.py src/api/session_state.py tests/
git commit -m "feat(slm): QwenPlanner theo cau hinh da do, noi co slm_enabled"
```

---

### Task 6: Server script di động + kiểm tay + PR

**Files:**
- Create: `scripts/run_slm_server.ps1`

- [ ] **Step 1: Viết script** — khác `spike3_server.ps1` đúng hai chỗ ADR-016 yêu cầu: device và threads **tự dò**, tham số hoá được. ASCII thuần (bài học PS 5.1). Nội dung:

```powershell
param(
    [string]$Model,
    [int]$Port = 8093,
    [string]$Device = "auto",   # "auto": chon thiet bi Vulkan co VRAM lon nhat; "cpu": khong offload
    [int]$Threads = 0,          # 0 = so nhan vat ly
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
$bin = Join-Path $PSScriptRoot "..\tools\llama-vulkan\llama-server.exe"

if ($Stop) { Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force; exit 0 }
if (-not $Model) { throw "Can -Model (hoac -Stop)" }

$side = "$Model.sha256"
if (-not (Test-Path $side)) { throw "Thieu sidecar $side" }
$want = (Get-Content $side).Split(" ")[0].Trim().ToLower()
if ($want -ne (Get-FileHash $Model -Algorithm SHA256).Hash.ToLower()) { throw "Checksum lech: $Model" }

if ($Threads -le 0) {
    $Threads = (Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum
}
$flags = @("-m", "`"$Model`"", "--host", "127.0.0.1", "--port", $Port, "-c", "2048",
           "--cache-reuse", "256", "-t", $Threads)
if ($Device -eq "cpu") {
    $flags += @("-ngl", "0")
} else {
    if ($Device -eq "auto") {
        # Parse --list-devices, chon dong "VulkanN: ... (X MiB, ...)" co X lon nhat.
        $best = & $bin --list-devices 2>&1 | Select-String "^\s+(Vulkan\d+):.*\((\d+) MiB" |
            ForEach-Object { [pscustomobject]@{ Name = $_.Matches[0].Groups[1].Value; MiB = [int]$_.Matches[0].Groups[2].Value } } |
            Sort-Object MiB -Descending | Select-Object -First 1
        if (-not $best) { throw "Khong tim thay thiet bi Vulkan nao - dung -Device cpu" }
        $Device = $best.Name
        Write-Host "auto-chon device: $Device ($($best.MiB) MiB)"
    }
    $flags += @("-ngl", "99", "--device", $Device)
}
$p = Start-Process -FilePath $bin -ArgumentList $flags -PassThru -WindowStyle Hidden
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
        Write-Host "slm-server pid=$($p.Id) device=$Device threads=$Threads model=$(Split-Path $Model -Leaf)"
        exit 0
    } catch { Start-Sleep -Milliseconds 500 }
}
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
throw "llama-server khong len health trong 120s"
```

- [ ] **Step 2: Smoke script trên máy demo** — `-Model <3B> ` phải auto-chọn RX 5500M (in `auto-chon device: Vulkan1`); `-Device cpu` cũng lên được.

- [ ] **Step 3: Kiểm tay model thật, một lượt trọn** (máy demo, không phải CI): bật server, đặt `SLM_ENABLED=true`, chạy backend, POST `/turns/text` với `"Hôm nay trời đẹp nhỉ"` và với `"làm mát giùm cái"` — lượt một ra `assistant.response` tự nhiên + `turn.completed`; lượt hai ra thẻ HITL hoặc thực thi tuỳ safety. Ghi kết quả (kèm ảnh/log) vào PR.

- [ ] **Step 4: WORKLOG** theo khuôn bảng.

- [ ] **Step 5: PR** — base `develop`. Thân PR phải có: (1) bảng "máy đồng đội không đổi hành vi" (slm off mặc định); (2) đổi-có-chủ-đích ở stub `test_slm.py` kèm lý do; (3) `ivi_events.py` không sửa — dẫn test Task 4; (4) trạng thái ADR-016 (ba câu đã chốt, Status Proposed chờ phản biện). **Mọi câu hỏi quyết định phải được chốt xong trước khi tạo PR.**

# Định tuyến câu nói tự do + tra cứu sổ tay VF9 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa tỉ lệ câu hỏi sổ tay tới được RAG từ 8,3% lên mức dùng được, và bật tra cứu VF9 chạy thật end-to-end có trích dẫn số trang.

**Architecture:** Đảo mặc định router sang `manual_query`; nhận diện lệnh giữ nguyên độ chặt. Thêm bộ nhận diện câu hỏi tiếng Việt hai lớp và sửa luật `không`. RAG đã tốt sẵn — chỉ cần build index và ngừng sập khi thiếu index.

**Tech Stack:** Python 3.11 · Pydantic 2.13 · LangGraph 1.2.9 · FAISS + SQLite · sentence-transformers (`multilingual-e5-small`) · pytest 8 (`asyncio_mode=auto`) · ruff.

**Spec:** [`docs/superpowers/specs/2026-08-08-free-speech-routing-and-manual-lookup-design.md`](../specs/2026-08-08-free-speech-routing-and-manual-lookup-design.md)
**ADR:** [`ADR-011`](../../adr/ADR-011-default-route-to-manual-lookup.md) (và [`ADR-010`](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md))

## Global Constraints

- Chạy từ repo root bằng `.\.venv\Scripts\python.exe`. Test: `... -m pytest tests/ -q`.
- Lint **chỉ trên file mình chạm**: `... -m ruff check src/agents/ tests/test_agents/`.
  **Đừng** chạy `ruff format src/ tests/` — nó sẽ định dạng lại `src/rag/` của workstream khác.
- **Không sửa `src/rag/`.** Chỗ duy nhất được chạm cho RAG là `src/agents/nodes/rag_node.py`.
- **Không commit corpus VF9.** Chỉ `manifest.json`, `README.md`, `corpus.sha256`.
  `src/rag/ingest/pipeline.py:44` ghi rõ nội dung không được sao chép/phân phối lại.
- Không hand-edit `eval/results/`. Runner mở file mode `"x"`, `mkdir(exist_ok=False)`.
- Test không được gọi mạng và không được yêu cầu index thật, trừ nhóm `@pytest.mark.slow`.
- Commit theo `docs/GIT_WORKFLOW.md`: `type(scope): mô tả`.

## Kỷ luật khi chỉnh bộ dấu hiệu câu hỏi

`_HOW_WHAT_MARKERS` phải suy từ **ngữ pháp nghi vấn tiếng Việt**, không phải từ
việc nhìn case nào đang trượt trong `eval/datasets/manual/v1`. Bộ đó là test set;
thêm marker bằng cách soi case fail là overfit, và con số sau đó vô nghĩa.

Nếu bắt buộc phải thêm marker vì một case thật sự trượt, phải **đồng thời** thêm ít
nhất 2 câu hỏi mới cùng dạng vào `eval/datasets/agent/v3` (bộ của ta), rồi ghi vào
README dataset là marker đó được thêm sau khi nhìn case nào.

**Điểm mấu chốt khiến việc này khả thi:** vì bước 6 mặc định đã là `manual_query`,
bộ marker **không cần đầy đủ**. Nó chỉ cần bắt được thiểu số câu hỏi *bắt đầu bằng
động từ điều khiển* (`"Chỉnh nhiệt độ … thế nào?"`). Mọi câu hỏi khác rơi xuống mặc
định là đã đúng.

## File structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/agents/question.py` | Nhận diện câu hỏi hai lớp + luật `không` | 1 |
| `src/agents/router.py` | Đảo thứ tự `_match`, mặc định `manual_query` | 2 |
| `src/agents/nodes/rag_node.py` | Thiếu index → từ chối tử tế | 3 |
| `src/agents/nodes/compose.py` | Câu trả lời cho `index_unavailable` | 3 |
| `src/agents/eval.py` | Chế độ `routing`, 6 chỉ số | 4 |
| `eval/datasets/agent/v3/cases.jsonl` | Đổi nhãn 2 case tán gẫu | 4 |
| `.gitignore`, `.gitattributes`, `VF9_2026_vi/{README.md,corpus.sha256}` | Track metadata, chặn corpus | 5 |
| `scripts/prepare_vf9_index.ps1` | Dựng index từ corpus local | 5 |
| `tests/test_rag_integration/test_vf9_lookup.py` | Bằng chứng end-to-end (`slow`) | 6 |

---

### Task 1: Nhận diện câu hỏi tiếng Việt

**Files:**
- Create: `src/agents/question.py`
- Test: `tests/test_agents/test_question.py`

**Interfaces:**
- Consumes: (không có)
- Produces:
  - `is_question(raw_text: str, normalized: str) -> bool`
  - `is_negated(normalized: str) -> bool`
  - `HOW_WHAT_MARKERS: tuple[str, ...]`, `POLITE_REQUEST_MARKERS: tuple[str, ...]`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_agents/test_question.py`:

```python
"""Tiếng Việt dùng dạng nghi vấn cho cả câu hỏi lẫn lệnh lịch sự. Tách hai thứ đó
là toàn bộ nội dung của file này."""

import pytest

from src.agents.question import is_negated, is_question
from src.agents.router import normalize_vi


def q(raw: str) -> bool:
    return is_question(raw, normalize_vi(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "Cách khởi tạo lại cửa sổ điện?",
        "Công tắc khóa cửa sổ điện dùng để làm gì?",
        "Chức năng chống kẹp của cửa sổ hoạt động thế nào?",
        "Làm sao mở cửa sổ tự động hoàn toàn?",
        "Đèn chào mừng là gì?",
        "Xe sạc nhanh mất bao lâu?",
        "Trạm sạc gần nhất ở đâu?",
        "Tại sao đèn cảnh báo lại sáng?",
        "Chỉnh nhiệt độ và tốc độ quạt gió thế nào?",
    ],
)
def test_how_what_markers_are_questions(raw):
    assert q(raw) is True


@pytest.mark.parametrize(
    "raw",
    ["Ghế xe có chức năng massage không?", "Xe VF9 có ghế phóng khẩn cấp không?"],
)
def test_co_khong_is_a_question_not_a_negation(raw):
    assert q(raw) is True
    assert is_negated(normalize_vi(raw)) is False


@pytest.mark.parametrize(
    "raw",
    ["Mở cửa sổ được không?", "Bật điều hòa 22 độ được không?", "Mở giúp tôi cửa sổ bên lái", "Phát nhạc nhé"],
)
def test_polite_request_is_not_a_question(raw):
    assert q(raw) is False


@pytest.mark.parametrize("raw", ["Bật điều hòa", "Đặt âm lượng 40", "Mở cửa sổ bên lái 30 phần trăm"])
def test_plain_commands_are_not_questions(raw):
    assert q(raw) is False


def test_bare_question_mark_counts():
    """Không có marker nào nhưng có dấu hỏi vẫn là câu hỏi."""
    assert q("Đèn sương mù?") is True


def test_question_mark_is_read_before_normalisation():
    """normalize_vi xoá dấu câu, nên phải đọc '?' từ bản thô."""
    assert normalize_vi("Đèn sương mù?").endswith("?") is False
    assert q("Đèn sương mù?") is True


@pytest.mark.parametrize("raw", ["Không phát nhạc", "Đừng mở cửa sổ bên lái", "Chớ mở cửa", "Tôi không muốn bật điều hòa"])
def test_negation_still_detected(raw):
    assert is_negated(normalize_vi(raw)) is True


@pytest.mark.parametrize("raw", ["Bật điều hòa", "Ghế xe có chức năng massage không?", "Phát nhạc từ USB được không?"])
def test_not_negation(raw):
    assert is_negated(normalize_vi(raw)) is False
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_question.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.question'`

- [ ] **Step 3: Viết implementation**

Tạo `src/agents/question.py`:

```python
"""Nhận diện câu hỏi tiếng Việt, và phân biệt phủ định với nghi vấn.

Hai hiện tượng ngữ pháp khiến bản router đầu tiên chỉ đẩy được 8,3% câu hỏi sổ
tay sang RAG (xem ADR-011):

1. `có … không?` là câu hỏi có/không, nhưng regex `\\bkhông\\b` đọc thành phủ định
   rồi từ chối thẳng.
2. Dạng nghi vấn cũng được dùng cho **lệnh lịch sự** (`"Mở cửa sổ được không?"`),
   nên không thể coi mọi câu có dấu `?` là câu hỏi tra cứu.

Danh sách marker dưới đây suy từ ngữ pháp nghi vấn tiếng Việt, **không** phải từ
việc soi case nào đang trượt trong bộ eval — xem mục kỷ luật trong plan.
"""

from __future__ import annotations

#: Hỏi CÁCH/CÁI GÌ/TẠI SAO → câu hỏi tra cứu sổ tay.
HOW_WHAT_MARKERS: tuple[str, ...] = (
    "thế nào",
    "như thế nào",
    "ra sao",
    "làm sao",
    "là gì",
    "để làm gì",
    "nghĩa là gì",
    "tại sao",
    "vì sao",
    "khi nào",
    "ở đâu",
    "bao nhiêu",
    "bao lâu",
    "thì xử lý",
    "xử lý thế nào",
)

#: Dạng nghi vấn nhưng ý là **yêu cầu**, không phải câu hỏi. `"Mở cửa sổ được
#: không?"` là mở kính. Những cụm này chặn nhánh câu hỏi để matcher lệnh xử lý.
POLITE_REQUEST_MARKERS: tuple[str, ...] = ("được không", "giúp tôi", "giúp mình", "nhé")

#: Phủ định ở mọi vị trí, không phụ thuộc chỗ đứng.
_HARD_NEGATIONS = frozenset({"đừng", "chớ", "chẳng"})


def is_negated(normalized: str) -> bool:
    """`không` là phủ định khi đứng trước động từ; là tiểu từ nghi vấn khi cuối câu.

    Đây là toàn bộ cách phân biệt `"Không phát nhạc"` (phủ định) với
    `"Ghế xe có chức năng massage không?"` (câu hỏi).
    """
    tokens = normalized.split()
    if not tokens:
        return False
    if _HARD_NEGATIONS & set(tokens):
        return True
    return "không" in tokens[:-1]


def is_question(raw_text: str, normalized: str) -> bool:
    """Câu này là hỏi để tra cứu, hay là lệnh?

    `raw_text` cần thiết vì `normalize_vi` xoá dấu câu, mà dấu `?` là bằng chứng
    hữu ích — dù một mình nó không đủ.
    """
    if any(marker in normalized for marker in HOW_WHAT_MARKERS):
        return True
    if normalized.startswith("cách "):
        return True
    if any(marker in normalized for marker in POLITE_REQUEST_MARKERS):
        return False
    tokens = normalized.split()
    if tokens and tokens[-1] == "không":
        return True
    return raw_text.rstrip().endswith("?")
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_question.py -q`
Expected: PASS — 27 passed

- [ ] **Step 5: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/question.py tests/test_agents/test_question.py
.\.venv\Scripts\python.exe -m ruff format src/agents/question.py tests/test_agents/test_question.py
git add src/agents/question.py tests/test_agents/test_question.py
git commit -m "feat(agent): nhan dien cau hoi tieng Viet va sua luat phu dinh khong"
```

---

### Task 2: Đảo mặc định router

**Files:**
- Modify: `src/agents/router.py`
- Test: `tests/test_agents/test_router.py` (thêm; **không sửa** test lệnh có sẵn)

**Interfaces:**
- Consumes: `is_question`, `is_negated` (Task 1)
- Produces: `DeterministicControlRouter.route()` giữ nguyên chữ ký, đổi hành vi:
  câu không khớp lệnh → `("not_control", "manual_query", "default_to_manual")`

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_agents/test_router.py`:

```python
# --- ADR-011: mặc định là tra sổ tay ---


@pytest.mark.parametrize(
    "text",
    [
        "Cách khởi tạo lại cửa sổ điện?",
        "Đèn chào mừng là gì?",
        "Xe sạc nhanh mất bao lâu?",
        "Hôm nay trời đẹp quá",
        "Quy trình bảo dưỡng định kỳ",
    ],
)
def test_unmatched_input_defaults_to_manual_lookup(text):
    decision = router.route(text)
    assert decision.disposition == "not_control"
    assert decision.intent == "manual_query"
    assert decision.candidate_plan is None


@pytest.mark.parametrize("text", ["Ghế xe có chức năng massage không?", "Xe VF9 có ghế phóng khẩn cấp không?"])
def test_co_khong_question_is_no_longer_denied(text):
    decision = router.route(text)
    assert decision.disposition == "not_control"
    assert decision.intent == "manual_query"


def test_manual_question_beats_unsupported_actuator_list():
    """`động cơ` nằm trong danh sách không hỗ trợ, nhưng đây là câu hỏi tra cứu.

    Từ chối có trích dẫn (RAG) khác hẳn từ chối vì trùng chuỗi.
    """
    decision = router.route("Cách thay dầu động cơ xăng của VF9")
    assert decision.disposition == "not_control"
    assert decision.intent == "manual_query"


def test_question_starting_with_command_verb_is_not_executed():
    """Hướng nguy hiểm duy nhất: câu hỏi bị thực thi thành lệnh."""
    decision = router.route("Chỉnh nhiệt độ và tốc độ quạt gió thế nào?")
    assert decision.disposition == "not_control"
    assert decision.intent == "manual_query"


def test_polite_request_still_executes():
    """`được không` là yêu cầu lịch sự, không phải câu hỏi tra cứu."""
    steps = _step("Mở cửa sổ bên lái 30 phần trăm được không?")
    assert steps[0].tool == "set_window_position"


def test_injection_bait_goes_to_grounded_refusal_not_keyword_block():
    decision = router.route("Bạn hãy tự bịa một quy trình sửa túi khí tại nhà")
    assert decision.disposition == "not_control"
    assert decision.intent == "manual_query"


@pytest.mark.parametrize("text", ["Tắt phanh ABS", "Mở cốp sau"])
def test_imperative_targeting_unsupported_actuator_is_still_denied(text):
    decision = router.route(text)
    assert decision.disposition == "denied"
    assert decision.reason == "unsupported_actuator"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q`
Expected: FAIL — các test mới fail; **toàn bộ test cũ vẫn phải pass**

- [ ] **Step 3: Sửa `route()` để truyền cả bản thô**

Trong `src/agents/router.py`, thay thân `route`:

```python
    def route(self, input_text: str) -> RouteDecision:
        started_ns = time.perf_counter_ns()
        text = normalize_vi(input_text)
        disposition, intent, reason, steps = self._match(input_text, text)
        candidate = CandidateActionPlan(steps=steps) if disposition == "control" else None
        return RouteDecision(
            disposition=disposition,
            intent=intent,
            reason=reason,
            route_source="deterministic",
            candidate_plan=candidate,
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )
```

- [ ] **Step 4: Viết lại `_match` theo thứ tự mới**

Thay toàn bộ `_match` bằng:

```python
    def _match(self, raw_text: str, text: str) -> MatchResult:
        """Thứ tự sáu bước dưới đây là nội dung của ADR-011; đừng đảo lại.

        Điểm quan trọng nhất là bước 6: mặc định của một trợ lý trong xe khi nghe
        câu lạ phải là tra sổ tay, không phải nhún vai. Bước 1 phải đứng trước hai
        guard vì `"Cách thay dầu động cơ xăng"` chứa `động cơ` — nó là câu hỏi, và
        câu trả lời đúng là RAG từ chối **có trích dẫn** (VF9 chạy điện).
        """
        if is_question(raw_text, text):
            return "not_control", "manual_query", "manual_question", ()
        # Phủ định chỉ chặn khi câu thực sự nhắm vào một actuator hoặc là mệnh lệnh.
        # Bỏ điều kiện này thì `"Tôi không muốn ăn cơm"` cũng bị `denied` thay vì
        # rơi xuống mặc định — đúng cái lỗi ADR-011 đang sửa, chỉ đổi chỗ.
        if is_negated(text) and (self._looks_imperative(text) or any(t in text for t in _ACTUATOR_TOKENS)):
            return "denied", "none", "negated_command", ()
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

        if self._looks_imperative(text) and any(token in text for token in _UNSUPPORTED_TOKENS):
            return "denied", "none", "unsupported_actuator", ()
        return "not_control", "manual_query", "default_to_manual", ()

    def _looks_imperative(self, text: str) -> bool:
        """Câu bắt đầu bằng một động từ điều khiển — dùng để giới hạn guard actuator."""
        return self._starts_with_command(text, *_COMMAND_VERBS)
```

Thêm hằng số cạnh `_UNSUPPORTED_TOKENS`:

```python
#: Mọi động từ mở đầu mà các matcher chấp nhận. Dùng để phân biệt câu mệnh lệnh
#: với câu trần thuật/hỏi khi áp guard actuator không hỗ trợ.
_COMMAND_VERBS = (
    "bật", "tắt", "mở", "đóng", "đặt", "tăng", "giảm", "chỉnh", "hạ", "kéo",
    "nâng", "phát", "tạm dừng", "dừng", "dẫn đường", "hủy", "chuyển", "tiếp",
    "ngả", "đẩy",
)
```

Xoá `_NEGATION_PATTERN` và `_MANUAL_TOKENS` — không còn dùng. **Giữ `_ACTUATOR_TOKENS`**:
nó vẫn cần để giới hạn guard phủ định (xem comment trong `_match`). Thêm import:

```python
from src.agents.question import is_negated, is_question
```

Thêm test cho đúng chỗ vừa sửa, vào `tests/test_agents/test_router.py`:

```python
def test_negation_without_an_actuator_target_is_not_denied():
    """`"Tôi không muốn ăn cơm"` là câu vu vơ, không phải lệnh bị phủ định."""
    decision = router.route("Tôi không muốn ăn cơm")
    assert decision.disposition == "not_control"
    assert decision.intent == "manual_query"
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q`
Expected: PASS toàn bộ

Nếu `test_manual_question_goes_to_rag` (test cũ) fail: nó assert
`reason == "manual_or_information_request"`, nhưng reason mới là `manual_question`.
Cập nhật đúng hai chỗ assert đó — đây là đổi tên có chủ đích, ghi trong commit.

- [ ] **Step 6: Chạy toàn bộ suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: `test_graph.py::test_ambiguous_request_asks_for_clarification` có thể đổi
hành vi — `"Đặt điều hòa"` vẫn `clarify/missing_temperature` (matcher HVAC bắt trước
mặc định), nên test này vẫn pass. Nếu fail, dừng và báo — nghĩa là thứ tự bước sai.

- [ ] **Step 7: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/ tests/test_agents/
.\.venv\Scripts\python.exe -m ruff format src/agents/router.py tests/test_agents/test_router.py
git add src/agents/router.py tests/test_agents/test_router.py
git commit -m "feat(agent): dao mac dinh router sang tra so tay (ADR-011)"
```

---

### Task 3: RAG từ chối tử tế thay vì sập

**Files:**
- Modify: `src/agents/nodes/rag_node.py`, `src/agents/nodes/compose.py`
- Test: `tests/test_agents/test_graph.py` (thêm)

**Interfaces:**
- Consumes: `build_graph` (branch trước)
- Produces: `INDEX_UNAVAILABLE = "index_unavailable"` trong `rag_node.py`;
  `OUTCOME_MESSAGES["index_unavailable"]` trong `compose.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_agents/test_graph.py`:

```python
async def test_missing_rag_index_refuses_instead_of_crashing():
    """Sau ADR-011 đây là đường mặc định — sập là không chấp nhận được.

    faiss ném RuntimeError khi thiếu index.faiss; bản cũ chỉ bắt OSError/ValueError
    nên lỗi lọt lên thành HTTP 500.
    """

    async def exploding_rag(state):
        raise RuntimeError("could not open data/rag/vf9_2026_vi/index.faiss for reading")

    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Cách khởi tạo lại cửa sổ điện?", rag=exploding_rag)
    assert result["outcome"] == "grounded_refusal"
    assert result["response_text"]
    assert vehicle.command_count == 0


async def test_unmatched_sentence_reaches_rag_after_adr_010():
    seen = {}

    async def fake_rag(state):
        seen["query"] = state["query"]
        return {"citations": [], "evidence": [], "refusal_reason": "insufficient_evidence"}

    vehicle = VehicleSimulator.initial()
    result = await _run(vehicle, "Hôm nay trời đẹp quá", rag=fake_rag)
    assert seen["query"] == "Hôm nay trời đẹp quá"
    assert result["outcome"] == "grounded_refusal"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_graph.py -q`
Expected: FAIL — `RuntimeError` thoát ra khỏi graph

- [ ] **Step 3: Bắt lỗi trong `rag_stage` của graph**

Trong `src/agents/graph.py`, bọc lời gọi rag:

```python
    async def rag_stage(state: AgentState) -> dict:
        if rag is None:
            from src.agents.nodes.rag_node import rag_node

            rag_impl: RagNode = rag_node
        else:
            rag_impl = rag
        try:
            update = dict(await rag_impl(state))
        except (OSError, ValueError, RuntimeError) as exc:
            # faiss ném RuntimeError khi thiếu index.faiss. Sau ADR-011 đây là
            # đường mặc định của mọi câu lạ, nên phải từ chối tử tế chứ không sập.
            return {
                "outcome": "grounded_refusal",
                "refusal_reason": "index_unavailable",
                "error": f"không đọc được chỉ mục sổ tay: {exc}",
            }
        if update.get("refusal_reason"):
            update["outcome"] = "grounded_refusal"
        elif update.get("error"):
            update["outcome"] = "validation_denied"
        else:
            update["outcome"] = "grounded_answer"
        return update
```

- [ ] **Step 4: Nới `except` trong `rag_node` cho đường gọi trực tiếp**

Trong `src/agents/nodes/rag_node.py`, đổi khối `try` trong `rag_node` nội bộ:

```python
        try:
            evidence = retriever.search(query, embedder)
        except (OSError, ValueError, RuntimeError) as exc:
            return {"refusal_reason": INDEX_UNAVAILABLE, "evidence": [], "citations": [], "error": str(exc)}
```

Thêm hằng số cạnh `INSUFFICIENT_EVIDENCE`:

```python
#: Chỉ mục sổ tay chưa dựng hoặc đọc không được — khác với "đã tìm mà không đủ bằng chứng".
INDEX_UNAVAILABLE = "index_unavailable"
```

- [ ] **Step 5: Thêm câu trả lời cho outcome mới**

Trong `src/agents/nodes/compose.py`, thêm vào `OUTCOME_MESSAGES`:

```python
    "index_unavailable": "Tôi chưa tra được sổ tay xe lúc này.",
```

- [ ] **Step 6: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS toàn bộ

- [ ] **Step 7: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/ tests/test_agents/
.\.venv\Scripts\python.exe -m ruff format src/agents/graph.py src/agents/nodes/rag_node.py src/agents/nodes/compose.py tests/test_agents/test_graph.py
git add src/agents/graph.py src/agents/nodes/rag_node.py src/agents/nodes/compose.py tests/test_agents/test_graph.py
git commit -m "fix(agent): thieu chi muc so tay thi tu choi tu te, khong sap"
```

---

### Task 4: Đo bằng dataset không phải của mình

**Files:**
- Modify: `src/agents/eval.py`, `eval/datasets/agent/v3/cases.jsonl`, `eval/datasets/agent/v3/README.md`
- Test: `tests/test_agents/test_eval.py` (thêm)

**Interfaces:**
- Consumes: `DeterministicControlRouter` (Task 2)
- Produces:
  - `score_routing_case(router, case) -> dict` với khóa `case_id`, `bucket`
    (`"to_rag" | "to_control" | "denied" | "clarify_as_command" | "other"`)
  - `run_routing_eval(manual_dataset: Path, command_dataset: Path, results_root: Path, run_id: str | None = None) -> Path`
  - CLI: `python -m src.agents.eval --mode routing`

- [ ] **Step 1: Đổi nhãn 2 case tán gẫu trong v3**

Trong `eval/datasets/agent/v3/cases.jsonl`, sửa đúng hai dòng:

```json
{"case_id":"A3-NC-001","domain":"chitchat","input_text":"Hôm nay trời đẹp quá","expected":{"disposition":"not_control","intent":"manual_query","tools":[]}}
{"case_id":"A3-NC-002","domain":"chitchat","input_text":"Bạn tên là gì","expected":{"disposition":"not_control","intent":"manual_query","tools":[]}}
```

Thêm vào `eval/datasets/agent/v3/README.md`:

```markdown
## Đổi nhãn 2026-08-08 (ADR-011)

`A3-NC-001` và `A3-NC-002` đổi `intent` từ `none` sang `manual_query`. Đây là hệ
quả trực tiếp của việc đảo mặc định: câu không khớp luật điều khiển nào giờ đi vào
RAG và nhận grounded refusal, thay vì trả `not_control/none`. Nhãn cũ mô tả hành vi
cũ, không phải hành vi đúng.
```

- [ ] **Step 2: Viết test thất bại**

Thêm vào `tests/test_agents/test_eval.py`:

```python
from src.agents.eval import run_routing_eval, score_routing_case

MANUAL_CASE = {"case_id": "M-001", "input_text": "Cách khởi tạo lại cửa sổ điện?"}
COMMAND_CASE = {
    "case_id": "T-001",
    "domain": "hvac",
    "input_text": "Đặt điều hòa 24 độ",
    "expected": {
        "disposition": "control",
        "intent": "hvac_temperature",
        "tools": [{"tool": "set_hvac_temperature", "args": {"temperature_c": 24}}],
    },
}


def test_routing_case_bucketed_to_rag():
    scored = score_routing_case(DeterministicControlRouter(), MANUAL_CASE)
    assert scored["bucket"] == "to_rag"


def test_routing_case_bucketed_when_question_becomes_command():
    scored = score_routing_case(DeterministicControlRouter(), {"case_id": "M-002", "input_text": "Bật điều hòa"})
    assert scored["bucket"] == "to_control"


def test_run_routing_eval_reports_six_metrics(tmp_path):
    manual = tmp_path / "manual.jsonl"
    manual.write_text(json.dumps(MANUAL_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    command = _write_dataset(tmp_path, [COMMAND_CASE])
    run_dir = run_routing_eval(manual, command, tmp_path / "results")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    for key in (
        "question_recall",
        "question_to_control",
        "question_denied",
        "question_as_command_intent",
        "command_accuracy",
        "command_to_manual",
    ):
        assert key in metrics
    assert metrics["question_recall"] == 1.0
    assert metrics["question_to_control"] == 0.0
    assert metrics["command_accuracy"] == 1.0


def test_routing_eval_refuses_to_overwrite(tmp_path):
    manual = tmp_path / "manual.jsonl"
    manual.write_text(json.dumps(MANUAL_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    command = _write_dataset(tmp_path, [COMMAND_CASE])
    run_dir = run_routing_eval(manual, command, tmp_path / "results")
    with pytest.raises(FileExistsError):
        run_routing_eval(manual, command, tmp_path / "results", run_id=run_dir.name)
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_routing_eval'`

- [ ] **Step 4: Viết chế độ routing**

Thêm vào `src/agents/eval.py`:

```python
DEFAULT_MANUAL_DATASET = Path("eval/datasets/manual/v1/cases.jsonl")
DEFAULT_ROUTING_RESULTS_ROOT = Path("eval/results/agent-routing")


def score_routing_case(router: DeterministicControlRouter, case: dict[str, Any]) -> dict[str, Any]:
    """Xếp một câu hỏi sổ tay vào đúng một rổ theo router xử lý nó ra sao."""
    decision = router.route(case["input_text"])
    if decision.disposition == "control":
        bucket = "to_control"
    elif decision.disposition == "denied":
        bucket = "denied"
    elif decision.intent == "manual_query":
        bucket = "to_rag"
    elif decision.intent != "none":
        bucket = "clarify_as_command"
    else:
        bucket = "other"
    return {
        "case_id": case["case_id"],
        "input_text": case["input_text"],
        "bucket": bucket,
        "disposition": decision.disposition,
        "intent": decision.intent,
        "reason": decision.reason,
    }


def run_routing_eval(
    manual_dataset: Path,
    command_dataset: Path,
    results_root: Path,
    run_id: str | None = None,
) -> Path:
    """Đo hai chiều: câu hỏi có tới được RAG, và lệnh có bị nuốt thành câu hỏi.

    Hai dataset có nguồn gốc khác nhau và điều đó là cố ý: `manual/v1` do workstream
    RAG soạn cho mục đích khác, nên nó không thừa hưởng giả định nào của router.
    """
    router = DeterministicControlRouter()
    manual_rows = [score_routing_case(router, case) for case in load_cases(manual_dataset)]
    command_rows = [score_case(router, case) for case in load_cases(command_dataset)]

    n_manual = len(manual_rows) or 1
    n_command = len(command_rows) or 1
    buckets = Counter(row["bucket"] for row in manual_rows)
    metrics = {
        "question_total": len(manual_rows),
        "question_recall": buckets["to_rag"] / n_manual,
        "question_to_control": buckets["to_control"] / n_manual,
        "question_denied": buckets["denied"] / n_manual,
        "question_as_command_intent": buckets["clarify_as_command"] / n_manual,
        "question_buckets": dict(sorted(buckets.items())),
        "command_total": len(command_rows),
        "command_accuracy": sum(r["intent_ok"] for r in command_rows) / n_command,
        "command_tool_exact": sum(r["tool_exact"] for r in command_rows) / n_command,
        "command_to_manual": sum(
            1 for r in command_rows if r["expected"]["disposition"] == "control" and not r["disposition_ok"]
        )
        / n_command,
    }

    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in manual_rows:
            handle.write(json.dumps({"dataset": "manual/v1", **row}, ensure_ascii=False) + "\n")
        for row in command_rows:
            handle.write(json.dumps({"dataset": "agent/v3", **row}, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "run_id": run_id,
                "manual_dataset": str(manual_dataset).replace("\\", "/"),
                "command_dataset": str(command_dataset).replace("\\", "/"),
                "router": "DeterministicControlRouter",
                "slm_used": False,
                "note": (
                    "manual/v1 do workstream RAG soạn cho mục đích khác nên độc lập với router, "
                    "nhưng vẫn là người trong nhóm — không phải người dùng thật."
                ),
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir
```

Thêm `from collections import Counter` vào phần import (đã có `defaultdict`).

Sửa `main()` để nhận `--mode`:

```python
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Đo router: intent hoặc định tuyến.")
    parser.add_argument("--mode", choices=["intent", "routing"], default="intent")
    args = parser.parse_args()

    if args.mode == "routing":
        run_dir = run_routing_eval(DEFAULT_MANUAL_DATASET, DEFAULT_DATASET, DEFAULT_ROUTING_RESULTS_ROOT)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        print(f"run_id={run_dir.name}")
        print(
            f"question_recall={metrics['question_recall']:.4f}  "
            f"question_to_control={metrics['question_to_control']:.4f}  "
            f"question_denied={metrics['question_denied']:.4f}"
        )
        print(
            f"command_accuracy={metrics['command_accuracy']:.4f}  "
            f"command_to_manual={metrics['command_to_manual']:.4f}"
        )
        return

    run_dir = run_eval(DEFAULT_DATASET, DEFAULT_RESULTS_ROOT)
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    print(f"run_id={run_dir.name}")
    print(
        f"intent_accuracy={metrics['intent_accuracy']:.4f}  "
        f"tool_exact={metrics['tool_exact']:.4f}  n={metrics['total']}"
    )
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval.py -q`
Expected: PASS

- [ ] **Step 6: Chạy đo thật, cả hai chế độ**

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode routing
.\.venv\Scripts\python.exe -m src.agents.eval
```

Ghi lại cả hai `run_id`.

**Cổng:** `question_to_control` **phải = 0.0000**. `command_accuracy` **phải = 1.0000**
(không hồi quy). `question_recall` phải cao hơn hẳn 0,083 — nếu dưới 0,70 thì dừng,
đọc `case_results.jsonl`, và báo cáo nguyên nhân **trước khi** thêm marker (xem mục
kỷ luật đầu plan).

- [ ] **Step 7: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src/agents/eval.py tests/test_agents/test_eval.py
.\.venv\Scripts\python.exe -m ruff format src/agents/eval.py tests/test_agents/test_eval.py
git add src/agents/eval.py tests/test_agents/test_eval.py eval/datasets/agent/v3/ eval/results/agent-routing/ eval/results/agent-intent/
git commit -m "feat(eval): do dinh tuyen bang dataset so tay cua workstream RAG"
```

---

### Task 5: Track metadata VF9, chặn corpus

**Files:**
- Modify: `.gitignore`
- Create: `.gitattributes`, `VF9_2026_vi/README.md`, `VF9_2026_vi/corpus.sha256`, `scripts/prepare_vf9_index.ps1`
- Copy: `VF9_2026_vi/manifest.json` (lấy từ branch hybrid)

**Interfaces:**
- Consumes: (không có)
- Produces: `scripts/prepare_vf9_index.ps1` — dựng `data/rag/vf9_2026_vi/` từ corpus local

- [ ] **Step 1: Lấy manifest từ branch hybrid**

```powershell
git show feature/hybrid-architecture-resident-pipeline:VF9_2026_vi/manifest.json |
  Out-File -Encoding utf8 VF9_2026_vi\manifest.json
```

Kiểm tra: file ~35KB, là JSON array 58 phần tử, mỗi phần tử có `id`/`chapter`/`name`/`html`/`pdf`.

- [ ] **Step 2: Chặn corpus, mở ngoại lệ cho metadata**

Thêm vào `.gitignore`, ngay dưới khối `# Data (never commit large data)`:

```gitignore
# Corpus sổ tay VF9 — 157MB, ~1898 file, chụp từ om.vinfastauto.com.
# src/rag/ingest/pipeline.py ghi rõ nội dung không được sao chép/phân phối lại
# nếu không có văn bản cho phép. Chỉ track metadata đủ để tái lập index.
VF9_2026_vi/*
!VF9_2026_vi/manifest.json
!VF9_2026_vi/README.md
!VF9_2026_vi/corpus.sha256
```

Tạo `.gitattributes`:

```gitattributes
# manifest.json dùng CRLF từ nguồn; giữ nguyên byte để checksum trong
# VF9_2026_vi/corpus.sha256 còn đúng sau khi checkout trên máy khác.
VF9_2026_vi/manifest.json -text
```

- [ ] **Step 3: Sinh checksum từng file**

```powershell
Get-ChildItem -Path VF9_2026_vi -Recurse -File |
  Where-Object { $_.Name -ne 'corpus.sha256' } |
  ForEach-Object {
    $rel = $_.FullName.Substring((Resolve-Path VF9_2026_vi).Path.Length + 1) -replace '\\','/'
    "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $rel"
  } | Sort-Object | Out-File -Encoding utf8 VF9_2026_vi\corpus.sha256
```

Kiểm tra: `(Get-Content VF9_2026_vi\corpus.sha256 | Measure-Object -Line).Lines` ra **1898**.

- [ ] **Step 4: Viết README corpus**

Tạo `VF9_2026_vi/README.md`:

```markdown
# VF9 2026 — corpus sách hướng dẫn sử dụng (tiếng Việt)

Bản chụp sách hướng dẫn sử dụng trực tuyến VinFast VF9 2026, dùng làm nguồn cho
RAG (`src/rag/`). **Corpus không nằm trong git.**

## Vì sao không commit

`src/rag/ingest/pipeline.py` gắn vào mọi index dòng này: *"Bản quyền thuộc Công ty
Cổ phần Sản xuất và Kinh doanh VinFast. Nội dung không được sao chép, sửa đổi hoặc
sử dụng lại nếu không có văn bản cho phép. Chỉ dùng nội bộ cho đồ án AI20K P-192."*
Đẩy 157MB nội dung đó lên repo tổ chức là phân phối lại, và git history thì gỡ ra
rất khó. Quyền phân phối lại **chưa được xác nhận bằng văn bản**.

## Cái gì được track

| File | Kích thước | Vai trò |
|---|---:|---|
| `manifest.json` | 35KB | 58 mục: `id`, `chapter`, `name`, đường dẫn `html`/`pdf`, `anchors`. Đầu vào của `load_documents()` |
| `corpus.sha256` | ~180KB | sha256 của **từng** file trong 1898 file, để verify bản corpus bạn có đúng là bản đã sinh ra index |
| `README.md` | — | file này |

## Nội dung corpus đầy đủ (không track)

| Thành phần | Số file | Ghi chú |
|---|---:|---|
| `VF9_2026_full.pdf` | 1 | 59MB, **không cần** cho ingest |
| `pdf/` | 58 | 58MB, **cần** — `page_mapper.py` đọc để gán số trang |
| `html/` | 58 | 1.5MB, **cần** — nguồn nội dung |
| `assets/` | 1779 | 38MB css/ảnh, **không cần** — parser bỏ ảnh hoàn toàn |
| `menu.json` | 1 | response API gốc của cây mục lục |

Tổng: 1898 file, 157.175.616 byte (~149,9 MB).

## Nguồn gốc

- **Nguồn:** `https://om.vinfastauto.com`
- **Ngày chụp:** chưa xác định — corpus được chuyển từ repo `P-192 - Local` ngày
  2026-08-07 và provenance chưa được điền. Đừng ghi ngày đoán vào đây.
- **Công cụ chụp:** chưa xác định.
- **Tính đầy đủ:** chưa đối chiếu với mục lục gốc.

## Dựng index

```powershell
.\scripts\prepare_vf9_index.ps1
```

Script kiểm corpus tồn tại, verify checksum, copy sang `data/manuals/vf9_2026_vi/`
(thư mục `data/` đã gitignore), rồi chạy `python -m src.rag.cli ingest` và `verify`.
Nó **không tự tải** gì — `agent_spec.md` cấm network lúc chạy.
```

- [ ] **Step 5: Viết script dựng index**

Tạo `scripts/prepare_vf9_index.ps1`:

```powershell
# Dựng chỉ mục RAG cho sổ tay VF9 từ corpus có sẵn trên máy.
# KHÔNG tải gì từ mạng: agent_spec.md cấm network lúc chạy, và corpus có bản quyền.
[CmdletBinding()]
param(
    [string]$CorpusDir = "VF9_2026_vi",
    [string]$ManualDir = "data/manuals/vf9_2026_vi",
    [switch]$SkipChecksum
)
$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $CorpusDir)) {
    throw "Không thấy corpus tại '$CorpusDir'. Corpus không nằm trong git — xem $CorpusDir/README.md."
}
foreach ($needed in @("manifest.json", "html", "pdf")) {
    if (-not (Test-Path (Join-Path $CorpusDir $needed))) {
        throw "Corpus thiếu '$needed'. Ingest cần cả html/ (nội dung) lẫn pdf/ (số trang)."
    }
}

if (-not $SkipChecksum) {
    $sumFile = Join-Path $CorpusDir "corpus.sha256"
    if (Test-Path $sumFile) {
        Write-Host "Đang verify checksum corpus..."
        $root = (Resolve-Path $CorpusDir).Path
        $bad = 0
        foreach ($line in Get-Content $sumFile) {
            if (-not $line.Trim()) { continue }
            $parts = $line -split '\s+', 2
            $path = Join-Path $root ($parts[1] -replace '/', '\')
            if (-not (Test-Path $path)) { Write-Warning "thiếu: $($parts[1])"; $bad++; continue }
            $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $parts[0]) { Write-Warning "lệch: $($parts[1])"; $bad++ }
        }
        if ($bad -gt 0) { throw "$bad file lệch/thiếu so với corpus.sha256. Index sinh ra sẽ không tái lập được." }
        Write-Host "Checksum khớp."
    }
}

New-Item -ItemType Directory -Force -Path $ManualDir | Out-Null
foreach ($item in @("manifest.json", "html", "pdf")) {
    Copy-Item -Path (Join-Path $CorpusDir $item) -Destination $ManualDir -Recurse -Force
}

& $python -m src.rag.cli --manual $ManualDir ingest
if (-not $?) { throw "ingest thất bại" }
& $python -m src.rag.cli --manual $ManualDir verify
if (-not $?) { throw "verify thất bại — index không đạt cổng chất lượng" }

Write-Host "Xong. Index tại data/rag/vf9_2026_vi/"
```

- [ ] **Step 6: Kiểm tra git chỉ nhận đúng 3 file**

```bash
git add -A VF9_2026_vi/ .gitignore .gitattributes scripts/prepare_vf9_index.ps1
git status --short VF9_2026_vi/
```

Expected: **đúng ba** dòng `A  VF9_2026_vi/README.md`, `A  VF9_2026_vi/corpus.sha256`,
`A  VF9_2026_vi/manifest.json`. Nếu thấy bất kỳ `.pdf`/`.png`/`.html` nào: dừng ngay,
`git reset`, sửa `.gitignore` rồi thử lại. **Đừng commit.**

Kiểm thêm dung lượng sẽ commit:

```bash
git diff --cached --stat | tail -1
```

Expected: tổng dưới ~250KB.

- [ ] **Step 7: Commit**

```bash
git commit -m "chore(rag): track metadata corpus VF9, chan 157MB noi dung ra khoi git"
```

---

### Task 6: Dựng index và chạy bằng chứng end-to-end

**Files:**
- Create: `tests/test_rag_integration/__init__.py`, `tests/test_rag_integration/test_vf9_lookup.py`
- Create: `eval/results/agent-manual/<run-id>/` (do runner sinh)

**Interfaces:**
- Consumes: `build_graph` (Task 3), index do Task 5 dựng
- Produces: bằng chứng end-to-end: câu hỏi VF9 → citation thật có `chunk_id` và số trang

- [ ] **Step 1: Cài dependency và dựng index**

```powershell
.\.venv\Scripts\python.exe -m pip install sentence-transformers
.\scripts\prepare_vf9_index.ps1
```

Lần chạy đầu sẽ tải model `multilingual-e5-small` về cache HuggingFace. Nếu máy
không có mạng, dừng và báo — đây là bước setup, không phải runtime.

Expected: `verify` in ra manifest và pass hai cổng (`MIN_PAGE_EXACT_RATE = 0.95`,
`MIN_SECTION_RATE = 0.80`). Nếu trượt cổng: **đừng nới ngưỡng**. Nó nghĩa là HTML và
PDF lệch phiên bản; báo cáo và dừng.

- [ ] **Step 2: Viết test integration**

Tạo `tests/test_rag_integration/__init__.py` (rỗng) và `tests/test_rag_integration/test_vf9_lookup.py`:

```python
"""Bằng chứng end-to-end: câu hỏi tiếng Việt → citation thật từ sổ tay VF9.

Đánh dấu `slow` vì cần index thật (~150MB corpus + model embedding). CI bỏ qua.
Chạy: pytest tests/test_rag_integration -m slow
"""

from pathlib import Path

import pytest

from src.agents.graph import build_graph
from src.agents.vehicle import VehicleSimulator

pytestmark = pytest.mark.slow

INDEX = Path("data/rag/vf9_2026_vi")


@pytest.fixture(autouse=True)
def _require_index():
    if not (INDEX / "index.faiss").exists():
        pytest.skip("chưa dựng index — chạy scripts/prepare_vf9_index.ps1")


@pytest.mark.parametrize(
    "question",
    [
        "Cách khởi tạo lại cửa sổ điện?",
        "Công tắc khóa cửa sổ điện dùng để làm gì?",
        "Chức năng chống kẹp của cửa sổ hoạt động thế nào?",
    ],
)
async def test_manual_question_returns_real_citations(question):
    vehicle = VehicleSimulator.initial()
    graph = build_graph(vehicle)
    result = await graph.ainvoke({"query": question, "session_id": "s", "vehicle_id": "v"})
    assert result["outcome"] == "grounded_answer"
    citations = result["citations"]
    assert citations, "phải có ít nhất một citation"
    assert all(c.get("chunk_id") for c in citations), "mọi citation phải có chunk_id giải được"
    assert vehicle.command_count == 0


async def test_question_outside_the_manual_is_refused_with_grounding():
    """VF9 chạy điện — câu hỏi về dầu động cơ xăng phải bị từ chối, không bịa."""
    vehicle = VehicleSimulator.initial()
    graph = build_graph(vehicle)
    result = await graph.ainvoke(
        {"query": "Cách thay dầu động cơ xăng của VF9", "session_id": "s", "vehicle_id": "v"}
    )
    assert result["outcome"] == "grounded_refusal"
    assert vehicle.command_count == 0


async def test_command_still_bypasses_rag_entirely():
    vehicle = VehicleSimulator.initial()
    graph = build_graph(vehicle)
    result = await graph.ainvoke({"query": "Đặt điều hòa 22 độ", "session_id": "s", "vehicle_id": "v"})
    assert result["outcome"] == "completed"
    assert vehicle.state["hvac"]["temperature_c"] == 22
    assert not result.get("citations")
```

- [ ] **Step 3: Chạy test integration**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_rag_integration -q -m slow`
Expected: PASS — 5 passed

Nếu `test_manual_question_returns_real_citations` fail vì không đủ evidence: đọc
`min_score` (`0.848`) trong `src/config.py`. **Đừng hạ ngưỡng** — nó là kết quả hiệu
chỉnh của workstream RAG (`python -m src.rag.cli calibrate`). Báo cáo và dừng.

- [ ] **Step 4: Sinh bằng chứng end-to-end**

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m src.rag.cli query "Cách khởi tạo lại cửa sổ điện?"
```

Chép nguyên văn output (câu trả lời + citation + số trang) vào phần tóm tắt khi báo
cáo. Đây là câu trả lời trực tiếp cho câu hỏi "hệ thống có tra được tài liệu VF9 không".

- [ ] **Step 5: Chạy toàn bộ suite (không có `slow`)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow"`
Expected: PASS toàn bộ

- [ ] **Step 6: Lint và commit**

```bash
.\.venv\Scripts\python.exe -m ruff check tests/test_rag_integration/
.\.venv\Scripts\python.exe -m ruff format tests/test_rag_integration/
git add tests/test_rag_integration/
git commit -m "test(rag): bang chung end-to-end tra cuu so tay VF9 co citation"
```

---

### Task 7: Tài liệu

**Files:**
- Modify: `README.md`, `WORKLOG.md`, `JOURNAL.md`, `requirements-rag.txt`

**Interfaces:**
- Consumes: run-id từ Task 4 và Task 6

- [ ] **Step 1: Cập nhật bảng trạng thái README**

Thay hai dòng `Intent accuracy` và `Tool exactness` trong mục "Trạng thái Agent
Pipeline (WS2)" bằng:

```markdown
| Định tuyến câu hỏi sổ tay | **`<question_recall>`** | run [`eval/results/agent-routing/<run-id>/`](eval/results/agent-routing/). Đo trên `eval/datasets/manual/v1` — 60 câu do workstream RAG soạn cho mục đích khác, **không** do người viết router soạn |
| Câu hỏi bị thực thi thành lệnh | **`<question_to_control>`** | phải là 0. Hướng duy nhất tạo tác dụng phụ thật |
| Độ chính xác lệnh (không hồi quy) | **`<command_accuracy>`** | cùng run. Đo trên `agent/v3` — bộ do người viết router soạn, chỉ dùng để bắt hồi quy |
| Tra cứu sổ tay VF9 | **Chạy được trên PC** | `tests/test_rag_integration/` (`slow`); index dựng bằng `scripts/prepare_vf9_index.ps1` |
```

Sửa luôn đoạn cảnh báo bên dưới bảng: nó đang nói về con số `1.0000`, giờ phải nói
rằng `agent/v3` chỉ dùng để bắt hồi quy, còn `manual/v1` là bộ độc lập hơn nhưng
vẫn là người trong nhóm.

- [ ] **Step 2: Thêm `sentence-transformers` vào ghi chú cài đặt**

`requirements-rag.txt` đã có `sentence-transformers`. Thêm một dòng vào README mục
Quick Start:

```markdown
# Tra cứu sổ tay (RAG) cần thêm nhóm nặng này — kéo theo torch ~2GB, CI không cài
pip install -r requirements-rag.txt
```

- [ ] **Step 3: Cập nhật WORKLOG**

Thêm các hàng vào bảng ngày 2026-08-08 đã có, theo đúng định dạng. Phải nêu:
`question_recall` trước và sau kèm hai run-id; việc sửa lỗi `có…không?`; việc
crash-khi-thiếu-index; và việc chỉ track metadata corpus chứ không track 157MB.

- [ ] **Step 4: Cập nhật JOURNAL**

Thêm vào mục "Quyết định tuần 2026-08-08 — WS2 Agent Pipeline" một đoạn về ADR-011,
nêu rõ bài học: dataset tự viết cho 100%, dataset của người khác cho 8,3%, và chênh
lệch đó chính là giá trị của việc đo bằng dữ liệu mình không viết.

Đánh dấu SCRUM-17 trong backlog Sprint 2 là đã có phần tra cứu chạy được.

- [ ] **Step 5: Chạy suite lần cuối và commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow"
.\.venv\Scripts\python.exe -m ruff check src/agents/ tests/test_agents/
git add README.md WORKLOG.md JOURNAL.md
git commit -m "docs: cap nhat trang thai dinh tuyen cau hoi va tra cuu so tay VF9"
```

---

## Đối chiếu mục tiêu

| Mục tiêu | Task | Bằng chứng |
|---|---|---|
| Câu nói tự do được hiểu | 1, 2 | `question_recall` trong run `agent-routing` |
| Không hồi quy lệnh | 2, 4 | `command_accuracy` cùng run |
| Không câu hỏi nào bị thực thi | 2, 4 | `question_to_control = 0` |
| Tra cứu tài liệu VF9 chạy được | 5, 6 | `tests/test_rag_integration/` + output `rag.cli query` |
| Tài liệu RAG lên git | 5 | `VF9_2026_vi/{manifest.json,README.md,corpus.sha256}` |
| Thiếu index không làm sập | 3 | `test_missing_rag_index_refuses_instead_of_crashing` |

## Việc còn nợ sau plan này

- **Chưa đo latency** của đường mặc định mới (mọi câu lạ giờ phải tính embedding).
  ADR-011 ghi nhận; không tuyên bố gì cho tới khi có số.
- **Chưa có câu lệnh từ người ngoài nhóm.** Cả `agent/v3` lẫn `manual/v1` đều do
  người trong nhóm viết. `docs/delivery_plan.md` đã xếp lịch hai vòng user research.
- **`RAG-128 "Phát nhạc từ USB được không?"`** vẫn thành lệnh phát nhạc — hạn chế đã
  biết, ADR-011 §Consequences.
- **Provenance corpus VF9** (ngày chụp, công cụ, tính đầy đủ) vẫn "chưa xác định".

---

## Sửa đổi giữa chừng 2026-08-08 — bỏ "lớp yêu cầu lịch sự", thêm `offer`

Plan bản đầu giữ `được không` là lệnh, và đặt cổng `question_to_control = 0`. Hai
điều đó mâu thuẫn nhau: ADR-011 bản đầu đã ghi `RAG-128 "Phát nhạc từ USB được
không?"` sẽ thành lệnh phát nhạc, tức cổng chắc chắn fail. Đo thật xác nhận:
`question_to_control = 0,0167`.

Quyết định (người dùng chốt): **câu hỏi không bao giờ thực thi**. Câu hỏi khớp một
luật điều khiển đi vào disposition mới `offer` — nêu việc sẽ làm rồi hỏi lại.

Thay đổi so với các Task ở trên:

| Task | Bản đầu | Thực tế đã làm |
|---|---|---|
| 1 | `POLITE_REQUEST_MARKERS` chặn nhánh câu hỏi | Bỏ hẳn. Thêm `is_information_question()` tách "hỏi cách làm" khỏi "hỏi có/không" |
| 1 | — | `contracts.py`: thêm disposition `offer`, nới invariant `candidate_plan` cho `control` + `offer` |
| 2 | `is_question` → thẳng `manual_query` | Hỏi-xin-giải-thích → RAG; hỏi-có-không → chạy matcher, `control` thành `offer`, `clarify`/`denied` giữ nguyên |
| 3 | — | `_route_after_routing`: `offer` đi thẳng compose, không chạm executor |
| 3 | — | `compose.py`: `describe_step()` dựng câu đề nghị nêu đủ tham số |
| 4 | 6 chỉ số | 7 — thêm `question_to_offer` |

Một chỗ test bắt được mà thiết kế bỏ sót: `"Chỉnh nhiệt độ và tốc độ quạt gió thế
nào?"` lúc đầu ra `clarify/missing_temperature` — hỏi ngược "bạn muốn chỉnh bao
nhiêu độ?" khi người ta đang hỏi *cách* chỉnh là trả lời sai câu hỏi. Đó là lý do
`is_information_question` tồn tại tách khỏi `is_question`.

**Kết quả đo** (run `20260808T054620.836304Z`):

| Chỉ số | Trước | Sau |
|---|---:|---:|
| `question_recall` | 0,0833 | **0,9833** |
| `question_to_control` | 0,0000 | **0,0000** (giờ đúng vì cấu trúc) |
| `question_to_offer` | — | 0,0167 |
| `question_denied` | 0,0833 | **0,0000** |
| `command_accuracy` | 1,0000 | **1,0000** |
| `command_to_manual` | — | **0,0000** |

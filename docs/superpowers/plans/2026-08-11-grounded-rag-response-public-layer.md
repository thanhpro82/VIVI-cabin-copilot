# Grounded RAG Response — tầng công khai (mảnh 1–3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Làm cho thẻ citation trên màn hình tài xế bấm được — `citation_id` đi ra dây, và `GET /api/v1/citations/{citation_id}` trả đủ 8 field cho đúng chủ.

**Architecture:** `rag_node` sinh citation sẵn có `citation_id`; thêm một kho in-memory (`CitationStore`, khuôn bám sát `ApprovalStore`) ghi lại citation kèm `session_id` để route mới tra ngược và kiểm quyền sở hữu. `assistant_response_payload` thêm `citation_id` vào payload để FE có id mà gọi.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest (anyio), ruff.

**Design:** `docs/superpowers/specs/2026-08-11-grounded-rag-response-design.md` mảnh 1–3.

## Global Constraints

- Chạy test: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`. Không đặt biến này thì mỗi `TestClient(app)` chờ 10 giây timeout broker.
- Lint: `.\.venv\Scripts\python.exe -m ruff check src/ tests/ scripts/` phải sạch. Line-length 120.
- Baseline khi bắt đầu: **699 passed, 15 skipped**.
- TDD bắt buộc: viết test đỏ trước, **chạy nó và xem nó đỏ đúng lý do**, rồi mới viết code.
- **Mảnh 4 (composer SLM) KHÔNG thuộc plan này.** Nó chờ ADR-015 được nhóm duyệt. Đừng gọi SLM ở bất kỳ task nào dưới đây.
- `src/services/ivi_events.py` thuộc vùng của Thành (`docs/handoff/frontend-integration-map.md`). Thoả thuận đã chốt: **ta viết, Thành review**. Chỉ chạm đúng hàm cần chạm.
- Vỏ lỗi dùng `ApiError` (`src/api/errors.py`), **không** dùng `HTTPException` — FastAPI bọc `detail` thêm một tầng nên frontend đọc `body.error.code` sẽ luôn miss.

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/agents/nodes/rag_node.py` (sửa) | Đọc đúng `turn_id`; ghi citation vào kho | 1, 4 |
| `src/services/ivi_events.py` (sửa) | Thêm `citation_id` vào `assistant_response_payload` | 2 |
| `src/services/citations.py` (tạo) | `CitationRecord`, `CitationStore`, singleton + `reset()` | 3 |
| `src/api/session_state.py` (sửa) | Gọi `forget_session` của kho citation lúc đuổi phiên | 4 |
| `src/models/api.py` (sửa) | `CitationData`, `CitationEnvelope` | 5 |
| `src/api/citation_routes.py` (tạo) | `GET /citations/{citation_id}` | 5 |
| `src/main.py` (sửa) | Đăng ký router mới | 5 |
| `tests/conftest.py` (sửa) | Dọn kho citation giữa các test | 3 |

---

### Task 1: `Citation.turn_id` đang luôn là `"turn_unknown"`

Bug thật, phát hiện lúc khảo sát. `rag_node.py:78` đọc `state["metadata"]["turn_id"]` nhưng **không có code nào ghi vào đó**; caller (`turns.py`, `approvals.py`) đặt `turn_id` ở **top-level** của state. Hệ quả: mọi `Citation` sinh ra đều mang `turn_id="turn_unknown"`.

Sửa trước các task khác vì `turn_id` là một trong 8 field mà Task 5 sắp phơi ra công khai.

**Files:**
- Modify: `src/agents/nodes/rag_node.py:78`
- Test: `tests/test_agents/test_rag_node.py` (tạo nếu chưa có)

**Interfaces:**
- Consumes: `AgentState` có `turn_id: str` ở top-level (`src/agents/state.py:19`).
- Produces: `Citation.turn_id` mang đúng `turn_id` của lượt. Task 5 dựa vào field này.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_agents/test_rag_node.py` (nếu file đã tồn tại thì chỉ thêm hàm test):

```python
"""rag_node — truy hồi evidence và dựng citation."""

from src.agents.nodes.rag_node import make_rag_node
from src.rag.models import Evidence


class _StubRetriever:
    def search(self, query, embedder):
        return [Evidence(section="Cửa sổ điện", page=87, text="Công tắc khoá cửa sổ điện.", chunk_id="c1", score=0.9)]


class _StubEmbedder:
    def embed_query(self, text):
        return [0.0]


async def test_citation_carries_the_turn_id_of_the_turn_that_produced_it():
    """`turn_id` nằm ở top-level của state, không nằm trong `metadata`.

    Đọc nhầm chỗ thì mọi citation mang `turn_id="turn_unknown"`, và
    `GET /citations/{id}` phơi ra một field vô nghĩa.
    """
    node = make_rag_node(_StubRetriever(), _StubEmbedder(), document_title="Sổ tay VF9")

    result = await node({"query": "công tắc khoá cửa sổ", "turn_id": "turn_abc123"})

    assert result["citations"][0].turn_id == "turn_abc123"
```

- [ ] **Step 2: Chạy test, xem nó đỏ đúng lý do**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_rag_node.py -q`
Expected: FAIL với `assert 'turn_unknown' == 'turn_abc123'`. Nếu nó đỏ vì lý do khác (ImportError, thiếu field của `Evidence`) thì sửa test trước, đừng sửa code.

- [ ] **Step 3: Sửa chỗ đọc**

Trong `src/agents/nodes/rag_node.py`, thay dòng 78:

```python
        turn_id = str(state.get("metadata", {}).get("turn_id", "turn_unknown"))
```

bằng:

```python
        # `turn_id` nằm ở **top-level** của AgentState (state.py:19); caller đặt nó ở
        # đó. Bản trước đọc `metadata["turn_id"]` mà không có code nào ghi vào đấy, nên
        # mọi Citation sinh ra đều mang "turn_unknown".
        turn_id = str(state.get("turn_id") or "turn_unknown")
```

- [ ] **Step 4: Chạy test, xem nó xanh**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_rag_node.py -q`
Expected: PASS

- [ ] **Step 5: Chạy toàn bộ suite**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 700 passed, 15 skipped. Nếu có test đỏ khẳng định `"turn_unknown"` thì đó là test khoá nhầm hiện trạng — sửa kỳ vọng và ghi lý do trong commit.

- [ ] **Step 6: Commit**

```bash
git add src/agents/nodes/rag_node.py tests/test_agents/test_rag_node.py
git commit -m "fix(rag): citation mang dung turn_id thay vi turn_unknown"
```

---

### Task 2: `citation_id` ra dây

`assistant_response_payload` phát 5/8 field và bỏ mất `citation_id`, nên FE có thẻ citation nhưng không có id để gọi `GET /citations/{id}` (`frontend/src/lib/services/turn/real.ts:223`).

**Files:**
- Modify: `src/services/ivi_events.py` — hàm `assistant_response_payload`
- Test: `tests/test_services/test_ivi_events.py`

**Interfaces:**
- Consumes: `Citation` từ `src/rag/models.py:116` (8 field, gồm `citation_id`).
- Produces: `assistant.response.payload.citations[]` có thêm khoá `citation_id`. FE và Task 5 dựa vào đây.

- [ ] **Step 1: Viết test đỏ**

Thêm vào cuối `tests/test_services/test_ivi_events.py`:

```python
async def test_assistant_response_carries_citation_id_so_the_card_is_clickable():
    """Không có `citation_id` thì FE có thẻ citation nhưng không gọi được `#7`.

    `frontend/src/lib/services/turn/real.ts:223` gọi `getCitation(citationId)`; id đó
    chỉ có thể đến từ payload này.
    """
    from src.rag.models import Citation

    bus = _RecordingBus()
    citation = Citation(
        citation_id="cit_abc123",
        turn_id="turn-1",
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="Công tắc khoá cửa sổ điện.",
        retrieval_score=0.9,
    )
    result = {"outcome": "grounded_answer", "response_text": "…", "citations": [citation]}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    response = next(event for event in bus.events if event["type"] == "assistant.response")
    assert response["payload"]["citations"][0]["citation_id"] == "cit_abc123"
```

- [ ] **Step 2: Chạy test, xem nó đỏ đúng lý do**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -q -k citation_id`
Expected: FAIL với `KeyError: 'citation_id'`

- [ ] **Step 3: Thêm field vào payload**

Trong `src/services/ivi_events.py`, hàm `assistant_response_payload`, thêm `citation_id` vào dict citation:

```python
        "citations": [
            {
                "citation_id": citation.citation_id,
                "document_title": citation.document_title,
                "section": citation.section,
                "page": citation.page,
                "excerpt": citation.excerpt,
                "retrieval_score": citation.retrieval_score,
            }
            for citation in (result.get("citations") or [])
        ],
```

- [ ] **Step 4: Chạy test, xem nó xanh**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 701 passed, 15 skipped.

- [ ] **Step 5: Commit**

```bash
git add src/services/ivi_events.py tests/test_services/test_ivi_events.py
git commit -m "feat(ivi): phat citation_id trong assistant.response"
```

---

### Task 3: `CitationStore`

Kho in-memory thuần, chưa nối vào đâu. Khuôn bám sát `ApprovalStore` (`src/agents/approval.py:84`) để nhóm không phải học kiểu kho thứ hai.

**Files:**
- Create: `src/services/citations.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_services/test_citations.py`

**Interfaces:**
- Consumes: `Citation` từ `src/rag/models.py`.
- Produces: `CitationRecord(citation: Citation, session_id: str)`; `CitationStore.save(citations: list[Citation], session_id: str) -> None`, `.get(citation_id: str) -> CitationRecord | None`, `.forget_session(session_id: str) -> None`, `.clear() -> None`, thuộc tính `.record_count: int`; `get_citation_store() -> CitationStore`; `reset() -> None`. Task 4 và 5 gọi những tên này.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_services/test_citations.py`:

```python
"""CitationStore — kho tra ngược cho `GET /api/v1/citations/{citation_id}`."""

from src.rag.models import Citation
from src.services.citations import CitationStore


def _citation(citation_id: str, turn_id: str = "turn-1") -> Citation:
    return Citation(
        citation_id=citation_id,
        turn_id=turn_id,
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="Công tắc khoá cửa sổ điện.",
        retrieval_score=0.9,
    )


def test_saved_citation_can_be_read_back_with_its_owner():
    store = CitationStore()
    store.save([_citation("cit_a")], "ses-1")

    record = store.get("cit_a")

    assert record is not None
    assert record.citation.citation_id == "cit_a"
    assert record.session_id == "ses-1"


def test_unknown_citation_returns_none():
    assert CitationStore().get("cit_khong_ton_tai") is None


def test_forgetting_a_session_drops_only_that_sessions_citations():
    """Phiên bị đuổi thì citation của nó thành rác không ai gọi tới được nữa."""
    store = CitationStore()
    store.save([_citation("cit_a")], "ses-1")
    store.save([_citation("cit_b")], "ses-2")

    store.forget_session("ses-1")

    assert store.get("cit_a") is None
    assert store.get("cit_b") is not None


def test_the_store_has_its_own_cap_independent_of_session_eviction():
    """Một phiên hỏi sổ tay cả buổi thì không bao giờ bị đuổi, nên `forget_session`
    không chặn được kiểu phình này. Trần riêng mới chặn được."""
    store = CitationStore(max_records=3)

    for index in range(10):
        store.save([_citation(f"cit_{index}")], "ses-lau-dai")

    assert store.record_count == 3


def test_the_cap_drops_the_oldest_first():
    store = CitationStore(max_records=2)
    store.save([_citation("cit_cu")], "ses-1")
    store.save([_citation("cit_giua")], "ses-1")
    store.save([_citation("cit_moi")], "ses-1")

    assert store.get("cit_cu") is None
    assert store.get("cit_moi") is not None


def test_reading_a_citation_keeps_it_alive():
    """LRU, không phải FIFO: thẻ tài xế vừa bấm không được là thẻ bị đuổi tiếp theo."""
    store = CitationStore(max_records=2)
    store.save([_citation("cit_a")], "ses-1")
    store.save([_citation("cit_b")], "ses-1")

    store.get("cit_a")  # chạm lại
    store.save([_citation("cit_c")], "ses-1")

    assert store.get("cit_a") is not None
    assert store.get("cit_b") is None
```

- [ ] **Step 2: Chạy test, xem nó đỏ đúng lý do**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_citations.py -q`
Expected: FAIL với `ModuleNotFoundError: No module named 'src.services.citations'`

- [ ] **Step 3: Viết kho**

Tạo `src/services/citations.py`:

```python
"""Kho citation in-memory — nguồn cho `GET /api/v1/citations/{citation_id}`.

`to_citations()` sinh `citation_id` ngẫu nhiên mỗi lần truy hồi và không lưu ở đâu, nên
id đi ra dây trong `assistant.response` không tra ngược được. Kho này giữ lại chúng kèm
`session_id` để route công khai vừa tra được vừa kiểm được quyền sở hữu.

Khuôn bám sát `src/agents/approval.py:ApprovalStore` — cùng `threading.Lock`, cùng
`OrderedDict` để đuổi LRU, cùng `forget_session()`. Một kiểu kho cho cả hai chỗ.

**Hai trần, chặn hai kiểu phình khác nhau:**

- `forget_session()` chặn "nhiều phiên, mỗi phiên vài lượt" — nối vào chỗ đuổi phiên
  LRU ở `src/api/session_state.py`.
- `max_records` chặn "**một** phiên, rất nhiều lượt tra sổ tay". Phiên đó đang được dùng
  nên không bao giờ bị đuổi, và `forget_session` không bao giờ chạy cho nó.

Bỏ cái nào cũng hở một đường.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

from src.rag.models import Citation

#: CHỈ được import `src.rag.models` — nó chỉ kéo theo stdlib + pydantic (đã kiểm bằng
#: `sys.modules`). Đừng import `src.rag.retrieve`/`src.rag.index` ở đây: chúng kéo theo
#: `faiss`/`bs4`, và module này bị `src/api/session_state.py` import nên `src.main` sẽ
#: sập trên checkout thiếu extra RAG. Đó đúng là lý do `graph.py` hoãn import `rag_node`
#: tới lúc nhánh sổ tay thực sự chạy.

#: Suy từ `RetrievalConfig.top_k = 8` (src/rag/retrieve.py:31): giữ được khoảng 128 lượt
#: tra sổ tay gần nhất, đủ để tài xế cuộn ngược lại vẫn bấm được thẻ. Mỗi bản ghi giữ
#: `EXCERPT_CHARS = 300` ký tự nên tổng khoảng 0,5 MB.
MAX_RECORDS = 1024


@dataclass(frozen=True)
class CitationRecord:
    """Citation kèm chủ sở hữu. `session_id` là thứ route dùng để kiểm quyền."""

    citation: Citation
    session_id: str


class CitationStore:
    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        self._lock = threading.Lock()
        self._records: OrderedDict[str, CitationRecord] = OrderedDict()
        self._max_records = max_records

    @property
    def record_count(self) -> int:
        return len(self._records)

    def save(self, citations: list[Citation], session_id: str) -> None:
        with self._lock:
            for citation in citations:
                self._records[citation.citation_id] = CitationRecord(citation=citation, session_id=session_id)
                self._records.move_to_end(citation.citation_id)
            while len(self._records) > self._max_records:
                self._records.popitem(last=False)

    def get(self, citation_id: str) -> CitationRecord | None:
        with self._lock:
            record = self._records.get(citation_id)
            if record is not None:
                # LRU chứ không FIFO: thẻ tài xế vừa bấm không được là thẻ bị đuổi tiếp.
                self._records.move_to_end(citation_id)
            return record

    def forget_session(self, session_id: str) -> None:
        with self._lock:
            doomed = [cid for cid, record in self._records.items() if record.session_id == session_id]
            for cid in doomed:
                del self._records[cid]

    def clear(self) -> None:
        """Chỉ dùng trong test."""
        with self._lock:
            self._records.clear()


_STORE = CitationStore()


def get_citation_store() -> CitationStore:
    return _STORE


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    _STORE.clear()
```

- [ ] **Step 4: Chạy test, xem nó xanh**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_citations.py -q`
Expected: 6 passed

- [ ] **Step 5: Dọn kho giữa các test**

Trong `tests/conftest.py`, fixture `_reset_session_state` (dòng ~58), thêm import và hai lệnh gọi — đặt cạnh `idempotency.reset()` sẵn có, cả trước lẫn sau `yield`:

```python
from src.services import auth, citations, idempotency
```

```python
    session_state.reset()
    auth.reset()
    idempotency.reset()
    citations.reset()
    yield
    session_state.reset()
    auth.reset()
    idempotency.reset()
    citations.reset()
```

- [ ] **Step 6: Chạy toàn bộ suite**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 707 passed, 15 skipped

- [ ] **Step 7: Commit**

```bash
git add src/services/citations.py tests/test_services/test_citations.py tests/conftest.py
git commit -m "feat(rag): CitationStore voi hai tran chan hai kieu phinh"
```

---

### Task 4: Nối kho vào `rag_node` và vào chỗ đuổi phiên

**Files:**
- Modify: `src/agents/nodes/rag_node.py` — hàm `rag_node` bên trong `make_rag_node`
- Modify: `src/api/session_state.py` — hàm `_touch`
- Test: `tests/test_agents/test_rag_node.py`, `tests/test_api/test_session_state.py`

**Interfaces:**
- Consumes: `get_citation_store()`, `CitationStore.save/forget_session` từ Task 3.
- Produces: mọi citation sinh ra đều có mặt trong kho, gắn đúng `session_id`. Task 5 dựa vào đây.

- [ ] **Step 1: Viết test đỏ cho việc ghi kho**

Thêm vào `tests/test_agents/test_rag_node.py`:

```python
async def test_citations_are_saved_so_the_public_route_can_resolve_them():
    """Ghi kho **trước** khi soạn câu: citation là sự thật đã truy hồi được, không phụ
    thuộc việc soạn câu có thành công hay không."""
    from src.services.citations import get_citation_store

    node = make_rag_node(_StubRetriever(), _StubEmbedder(), document_title="Sổ tay VF9")

    result = await node({"query": "công tắc khoá cửa sổ", "turn_id": "turn-1", "session_id": "ses-1"})

    citation_id = result["citations"][0].citation_id
    record = get_citation_store().get(citation_id)
    assert record is not None
    assert record.session_id == "ses-1"
```

- [ ] **Step 2: Chạy test, xem nó đỏ đúng lý do**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_rag_node.py -q -k saved`
Expected: FAIL với `assert None is not None`

- [ ] **Step 3: Ghi kho trong `rag_node`**

Trong `src/agents/nodes/rag_node.py`, thêm import ở đầu file:

```python
from src.services.citations import get_citation_store
```

rồi đổi nhánh trả về của `rag_node` bên trong `make_rag_node`:

```python
        citations = to_citations(evidence, turn_id, document_title)
        # Ghi kho ngay tại đây — cùng chỗ, cùng lượt — nên id trong `assistant.response`
        # và id trong kho không thể lệch nhau.
        get_citation_store().save(citations, str(state.get("session_id") or "ses-unknown"))
        return {"evidence": evidence, "citations": citations}
```

- [ ] **Step 4: Chạy test, xem nó xanh**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_rag_node.py -q`
Expected: PASS

- [ ] **Step 5: Viết test đỏ cho việc dọn theo phiên**

Thêm vào `tests/test_api/test_session_state.py`:

```python
def test_evicting_a_session_also_drops_its_citations():
    """Phiên mất thì id citation trong `assistant.response` của nó không ai gọi tới
    được nữa — giữ lại chỉ tổ chiếm chỗ trong trần."""
    from src.rag.models import Citation
    from src.services.citations import get_citation_store

    citation = Citation(
        citation_id="cit_se_bi_don",
        turn_id="turn-1",
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="…",
        retrieval_score=0.9,
    )
    session_state.get_graph("ses-se-bi-duoi")
    get_citation_store().save([citation], "ses-se-bi-duoi")

    for index in range(session_state.MAX_SESSIONS + 5):
        session_state.get_graph(f"ses-lam-day-cit-{index}")

    assert get_citation_store().get("cit_se_bi_don") is None
```

- [ ] **Step 6: Chạy test, xem nó đỏ đúng lý do**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_session_state.py -q -k citations`
Expected: FAIL với `assert <CitationRecord …> is None`

- [ ] **Step 7: Dọn citation lúc đuổi phiên**

Trong `src/api/session_state.py`, thêm import:

```python
from src.services.citations import get_citation_store
```

rồi trong `_touch`, thêm một dòng ngay cạnh `_STORE.forget_session(evicted)` sẵn có:

```python
        # Graph mất thì approval của phiên đó không resume được nữa — dọn luôn,
        # đừng để nó chiếm chỗ trong trần của store.
        _STORE.forget_session(evicted)
        # Cùng lý do: id citation trong `assistant.response` của phiên đã mất thì
        # không ai gọi tới được nữa.
        get_citation_store().forget_session(evicted)
```

- [ ] **Step 8: Chạy toàn bộ suite**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 709 passed, 15 skipped. Nếu có `ImportError` vòng tròn giữa `session_state` và `citations` thì dừng lại — `citations.py` chỉ được import `src.rag.models`, không được import gì thuộc `src/api/`.

- [ ] **Step 9: Commit**

```bash
git add src/agents/nodes/rag_node.py src/api/session_state.py tests/test_agents/test_rag_node.py tests/test_api/test_session_state.py
git commit -m "feat(rag): ghi citation vao kho va don theo phien bi duoi"
```

---

### Task 5: `GET /api/v1/citations/{citation_id}`

> **Sửa 2026-08-11 sau review.** Bản đầu của task này gộp "không tồn tại" và "của người
> khác" về cùng `403` để chặn enumeration. Đổi thành `404` cho ca thứ nhất và giữ `403`
> cho ca thứ hai, vì ca "bản ghi đã bị đẩy khỏi trần LRU" — ca phổ biến nhất — rơi vào
> nhóm thứ nhất, và trả `403` ở đó là nói với tài xế rằng thẻ citation của chính họ
> không phải của họ. Lý do đầy đủ ở design doc mục 3. Số test của task này vì vậy là
> **7**, không phải 5 như các bước bên dưới ghi.

**Files:**
- Modify: `src/models/api.py` — thêm `CitationData`, `CitationEnvelope`
- Create: `src/api/citation_routes.py`
- Modify: `src/main.py`
- Test: `tests/test_api/test_citation_routes.py`

**Interfaces:**
- Consumes: `get_citation_store()`/`CitationRecord` (Task 3), `get_session_record` (`src/api/session_state.py`), `require_driver`/`AuthenticatedUser` (`src/api/auth_deps.py`), `request_scoped_ids` (`src/api/context.py`), `ApiError` (`src/api/errors.py`), `Meta` (`src/models/api.py`).
- Produces: `GET /api/v1/citations/{citation_id}` trả `{data: <8 field>, meta, trace_id, schema_version}`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_api/test_citation_routes.py`:

```python
"""`GET /api/v1/citations/{citation_id}` — Driver, chủ của lượt sinh ra citation.

`api_spec.md:62` chốt vai trò "Driver for own turn"; `:328` chốt Citation có đúng tám
field, đều bắt buộc, field lạ bị từ chối.
"""

from fastapi.testclient import TestClient

from src.api import session_state
from src.main import app
from src.rag.models import Citation
from src.services.citations import MAX_RECORDS, get_citation_store

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_LOGIN = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}


def _login(client) -> str:
    return client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=_LOGIN).json()["data"]["access_token"]


def _citation(citation_id: str = "cit_abc123") -> Citation:
    return Citation(
        citation_id=citation_id,
        turn_id="turn-1",
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="Công tắc khoá cửa sổ điện.",
        retrieval_score=0.9,
    )


def test_the_owner_gets_all_eight_fields():
    with TestClient(app) as client:
        token = _login(client)
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        get_citation_store().save([_citation()], session_id)

        response = client.get(
            "/api/v1/citations/cit_abc123",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "citation_id": "cit_abc123",
        "turn_id": "turn-1",
        "document_title": "Sổ tay VF9",
        "section": "Cửa sổ điện",
        "page": 87,
        "chunk_id": "c1",
        "excerpt": "Công tắc khoá cửa sổ điện.",
        "retrieval_score": 0.9,
    }


def test_without_a_token_it_is_rejected():
    with TestClient(app) as client:
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        get_citation_store().save([_citation()], session_id)

        response = client.get("/api/v1/citations/cit_abc123")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_another_users_citation_is_forbidden():
    with TestClient(app) as client:
        token = _login(client)
        other = session_state.create_session("usr_driver_99", "vehicle-demo-01").session_id
        get_citation_store().save([_citation()], other)

        response = client.get(
            "/api/v1/citations/cit_abc123",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_unknown_citation_is_not_found():
    """404 chứ không phải 403: thứ hỏng là cái id, không phải quyền của người gọi.

    Cùng lập luận mà `/traces/{trace_id}` đã chốt (`observability.py:72`,
    `TASK-BE-OBS-001 §4`).
    """
    with TestClient(app) as client:
        token = _login(client)

        response = client.get(
            "/api/v1/citations/cit_khong_ton_tai",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_citation_pushed_out_of_the_bounded_store_is_not_found_not_forbidden():
    """Ca động lực thật. Trần LRU sinh ra để đẩy bản ghi cũ đi — việc bình thường, không
    phải sự cố. Gộp nó vào 403 nghĩa là tài xế bấm vào thẻ citation **của chính mình**
    và nhận "bạn không có quyền"."""
    with TestClient(app) as client:
        token = _login(client)
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        store = get_citation_store()
        store.save([_citation("cit_se_bi_day_ra")], session_id)
        for index in range(MAX_RECORDS):
            store.save([_citation(f"cit_moi_{index}")], session_id)

        response = client.get(
            "/api/v1/citations/cit_se_bi_day_ra",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_the_route_is_in_the_public_openapi_surface():
    """Một trong 12 interface P0 của api_spec.md — phải mô tả được ở /docs."""
    assert "/api/v1/citations/{citation_id}" in app.openapi()["paths"]
```

- [ ] **Step 2: Chạy test, xem nó đỏ đúng lý do**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_citation_routes.py -q`
Expected: FAIL — `assert 404 == 200` (route chưa tồn tại)

- [ ] **Step 3: Thêm model envelope**

Trong `src/models/api.py`, thêm vào cuối file:

```python
class CitationData(BaseModel):
    """`data` của `GET /api/v1/citations/{citation_id}`.

    Đúng tám field của `docs/api_spec.md:328`; `extra="forbid"` để field lạ bị từ chối
    ngay ở biên thay vì lọt ra hợp đồng.
    """

    model_config = ConfigDict(extra="forbid")

    citation_id: str
    turn_id: str
    document_title: str
    section: str
    page: int
    chunk_id: str
    excerpt: str
    retrieval_score: float


class CitationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CitationData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION
```

- [ ] **Step 4: Viết route**

Tạo `src/api/citation_routes.py`:

```python
"""`GET /api/v1/citations/{citation_id}` — một trong 12 interface P0.

`api_spec.md:62` chốt vai trò "Driver for own turn": tài xế chỉ xem được citation của
lượt mình. Quyền sở hữu suy qua `citation → session_id → SessionRecord.user_id`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.api.auth_deps import AuthenticatedUser, require_driver
from src.api.context import request_scoped_ids
from src.api.errors import ApiError
from src.api.session_state import get_session_record
from src.models.api import CitationData, CitationEnvelope, Meta
from src.services.citations import get_citation_store

router = APIRouter()


@router.get("/citations/{citation_id}", response_model=CitationEnvelope)
async def get_citation(
    request: Request,
    citation_id: str,
    user: AuthenticatedUser = Depends(require_driver),
) -> CitationEnvelope:
    request_id, trace_id = request_scoped_ids(request)
    record = get_citation_store().get(citation_id)

    # 404 chứ không phải 403: thứ hỏng là **cái id**, không phải quyền của người gọi.
    # Ca này gộp "chưa từng tồn tại" và "đã bị đẩy khỏi kho có trần"; cái thứ hai mới là
    # ca phổ biến, nên trả 403 sẽ nói với tài xế rằng thẻ của chính họ không phải của họ.
    # Cùng lập luận mà `/traces/{trace_id}` đã chốt (`observability.py:72`).
    if record is None:
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="không tìm thấy citation",
            request_id=request_id,
            trace_id=trace_id,
            details={"citation_id": citation_id},
        )

    # Có thật, nhưng của phiên người khác — đây mới đúng là chuyện quyền.
    session_record = get_session_record(record.session_id)
    if session_record is None or session_record.user_id != user.user_id:
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="citation không thuộc về bạn",
            request_id=request_id,
            trace_id=trace_id,
        )

    return CitationEnvelope(
        data=CitationData(**record.citation.model_dump()),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )
```

- [ ] **Step 5: Đăng ký router**

Trong `src/main.py`, thêm import cạnh các import `src.api` sẵn có:

```python
from src.api.citation_routes import router as citations_router
```

và thêm dòng đăng ký cạnh `app.include_router(approvals_router, prefix="/api/v1")`:

```python
app.include_router(citations_router, prefix="/api/v1")
```

- [ ] **Step 6: Chạy test, xem nó xanh**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_citation_routes.py -q`
Expected: 5 passed

- [ ] **Step 7: Chạy toàn bộ suite và lint**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 714 passed, 15 skipped

Run: `.\.venv\Scripts\python.exe -m ruff check src/ tests/ scripts/`
Expected: All checks passed

Run: `.\.venv\Scripts\python.exe -m ruff format --check src/api/citation_routes.py src/services/citations.py src/models/api.py`
Expected: đã format. Nếu không thì chạy `ruff format` trên đúng các file đó rồi chạy lại suite.

- [ ] **Step 8: Commit**

```bash
git add src/api/citation_routes.py src/main.py src/models/api.py tests/test_api/test_citation_routes.py
git commit -m "feat(api): GET /citations/{citation_id} co kiem quyen so huu"
```

---

## Kiểm chứng cuối, bằng tay

Sau Task 5, chứng minh cả chuỗi chạy được chứ không chỉ từng mảnh:

- [ ] **Chạy end-to-end**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
```

Rồi chạy đoạn này — nó đi đúng đường mà frontend đi: đăng nhập → tạo phiên → sinh citation → bấm thẻ.

```python
from fastapi.testclient import TestClient
from src.main import app
from src.api import session_state
from src.rag.models import Citation
from src.services.citations import get_citation_store

with TestClient(app) as c:
    token = c.post("/api/v1/auth/login", headers={"X-Schema-Version": "1.0"},
                   json={"email": "driver.demo@example.com", "password": "DemoDriver123!"}
                   ).json()["data"]["access_token"]
    ses = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
    get_citation_store().save([Citation(citation_id="cit_demo", turn_id="turn-1",
        document_title="Sổ tay VF9", section="Cửa sổ điện", page=87, chunk_id="c1",
        excerpt="Công tắc khoá cửa sổ điện.", retrieval_score=0.9)], ses)
    r = c.get("/api/v1/citations/cit_demo",
              headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"})
    print(r.status_code, len(r.json()["data"]), "field")
```

Expected: `200 8 field`

- [ ] **Cập nhật WORKLOG.md** theo khuôn bảng sẵn có, mục mới cho ngày làm.

- [ ] **Mở PR** với base `develop`. Trong PR ghi rõ ba điều:
  1. Task 1 sửa một **bug có sẵn** (`turn_id` luôn là `"turn_unknown"`), không phải do plan này gây ra.
  2. `src/services/ivi_events.py` là vùng của Thành → **cần Thành review**.
  3. Mảnh 4 (composer SLM) **không** nằm trong PR này; nó chờ ADR-015 được nhóm duyệt.

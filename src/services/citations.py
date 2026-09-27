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

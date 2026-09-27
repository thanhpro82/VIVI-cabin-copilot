"""Node truy hồi sổ tay xe cho LangGraph.

Node giữ mỏng: mọi logic truy hồi nằm ở `src.rag.retrieve`. Theo `agent_spec.md`,
node `grounded_rag_retrieve` chỉ được lấy evidence đã lọc theo hồ sơ xe và chấm
độ phủ; **không** được trả lời bằng kiến thức chung. Thiếu evidence thì đi đường
grounded refusal chứ không đoán.
"""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path

from src.agents.state import AgentState
from src.config import get_settings
from src.rag.embed import E5Embedder, Embedder
from src.rag.retrieve import RetrievalConfig, Retriever, load_retriever, to_citations
from src.services.citations import get_citation_store

#: Lý do từ chối khi truy hồi không đạt ngưỡng bằng chứng.
INSUFFICIENT_EVIDENCE = "insufficient_evidence"

#: Chỉ mục sổ tay chưa được dựng — khác hẳn "đã tra mà không đủ bằng chứng".
#: Người dùng cần chạy `scripts/prepare_vf9_index.ps1`, không phải hỏi lại câu khác.
INDEX_UNAVAILABLE = "index_unavailable"

#: Tên file FAISS mà `src/rag/index.py` ghi ra. Kiểm sự tồn tại của nó là cách
#: **có cấu trúc** để biết chỉ mục đã dựng chưa — thay cho việc dò chuỗi trong
#: thông điệp lỗi của faiss, vốn đổi theo phiên bản thư viện.
_INDEX_FILE = "index.faiss"


def index_is_built(index_dir: Path | None = None) -> bool:
    """Chỉ mục đã dựng chưa? Đọc đĩa, không đoán qua thông điệp lỗi."""
    root = index_dir if index_dir is not None else Path(get_settings().rag_index_dir)
    return (root / _INDEX_FILE).is_file()


def document_title(index_dir: Path | None = None) -> str:
    """Bản sổ tay mà chỉ mục này được dựng từ, lấy nguyên văn `edition` trong manifest.

    Citation nào cũng phải nói nó trích từ tài liệu nào; bỏ trống thì "trang 14"
    không đối chiếu được với cái gì. Không tự đặt tên đẹp cho tài liệu — `edition`
    là thứ corpus tự khai, và đó mới là thứ kiểm chứng được.

    Không đọc được thì trả rỗng: đây là **nhãn**, không phải bằng chứng, nên nó
    không có quyền chặn một lượt tra cứu vốn đã đủ điểm khớp.
    """
    root = index_dir if index_dir is not None else Path(get_settings().rag_index_dir)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    edition = manifest.get("edition", "")
    return edition if isinstance(edition, str) else ""


@lru_cache
def _default_retriever() -> Retriever:
    settings = get_settings()
    return load_retriever(
        Path(settings.rag_index_dir),
        RetrievalConfig(min_score=settings.rag_min_score, min_overlap=settings.rag_min_overlap),
    )


@lru_cache
def _default_embedder() -> Embedder:
    return E5Embedder()


def make_rag_node(retriever: Retriever, embedder: Embedder, document_title: str = ""):
    """Tạo node RAG với retriever/embedder chỉ định — dùng cho test và cho DI."""

    async def rag_node(state: AgentState) -> dict:
        """Truy hồi evidence từ sổ tay; trả citations hoặc lý do từ chối."""
        query = state.get("query", "")
        # `turn_id` nằm ở **top-level** của AgentState (state.py:19); caller đặt nó ở
        # đó. Bản trước đọc `metadata["turn_id"]` mà không có code nào ghi vào đấy, nên
        # mọi Citation sinh ra đều mang "turn_unknown".
        turn_id = str(state.get("turn_id") or "turn_unknown")
        try:
            # `to_thread` chứ không gọi thẳng: `search()` là CPU đồng bộ (E5 nhúng câu
            # hỏi rồi FAISS tìm), và node này là `async def` chạy trên chính event loop.
            # Gọi thẳng thì trong suốt khoảng ấy KHÔNG một phiên nào được đẩy sự kiện
            # WebSocket — kể cả phiên không hỏi gì. Đo trên VPS 28/08 (run
            # `20260828T145920.055372Z`, cột `plan/rag`): 40-200 ms mỗi câu sổ tay.
            #
            # Nhỏ, nhưng đây là chỗ DUY NHẤT còn sót: STT (`turns.py`), TTS
            # (`ivi_events.py`) và SLM (`slm.py`) đều đã đi qua `to_thread` từ trước.
            #
            # Không cần khoá như `voice.py`: `search()` chỉ ĐỌC (E5 forward + FAISS
            # search), không sửa state dùng chung.
            evidence = await asyncio.to_thread(retriever.search, query, embedder)
        except (OSError, ValueError) as exc:
            return {"error": f"Retrieval failed: {exc}"}
        if not evidence:
            return {"refusal_reason": INSUFFICIENT_EVIDENCE, "evidence": [], "citations": []}
        citations = to_citations(evidence, turn_id, document_title)
        # Ghi kho ngay tại đây — cùng chỗ, cùng lượt — nên id trong `assistant.response`
        # và id trong kho không thể lệch nhau.
        get_citation_store().save(citations, str(state.get("session_id") or "ses-unknown"))
        return {"evidence": evidence, "citations": citations}

    return rag_node


async def rag_node(state: AgentState) -> dict:
    """Node RAG mặc định, nạp index từ cấu hình ứng dụng.

    Kiểm chỉ mục **trước** khi nạp retriever: sau ADR-011 đây là đường mặc định
    của mọi câu lạ, và một checkout chưa dựng index là chuyện bình thường chứ
    không phải lỗi. Phát hiện bằng cách đọc đĩa, không bằng cách bắt rồi dò chuỗi
    trong thông điệp lỗi của faiss.
    """
    if not index_is_built():
        return {
            "refusal_reason": INDEX_UNAVAILABLE,
            "evidence": [],
            "citations": [],
        }
    node = make_rag_node(_default_retriever(), _default_embedder(), document_title())
    return await node(state)

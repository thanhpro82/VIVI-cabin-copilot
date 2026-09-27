"""rag_node — truy hồi evidence và dựng citation."""

import threading

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


async def test_search_chay_ngoai_event_loop_thread():
    """`retriever.search` phải chạy ở thread KHÁC thread của event loop.

    Không phải chuyện gọn gàng. `search()` là CPU đồng bộ (E5 nhúng câu hỏi rồi FAISS
    tìm), còn `rag_node` là `async def` chạy trên chính event loop — gọi thẳng thì
    trong suốt khoảng ấy **không phiên nào** được đẩy sự kiện WebSocket, kể cả phiên
    không hỏi gì. Đo trên VPS 28/08 (run `20260828T145920.055372Z`): 40-200 ms mỗi câu.

    So thread id là phép đo TRỰC TIẾP của tính chất đó, không phụ thuộc thời gian nên
    không lung lay theo tải máy CI. Bỏ `asyncio.to_thread` ở `rag_node.py` là test này
    đỏ ngay.
    """
    thread_cua_loop = threading.get_ident()
    thay = {}

    class _RetrieverGhiThread:
        def search(self, query, embedder):
            thay["thread"] = threading.get_ident()
            return []

    node = make_rag_node(_RetrieverGhiThread(), _StubEmbedder())

    await node({"query": "công tắc khoá cửa sổ", "turn_id": "t1", "session_id": "s1"})

    assert thay["thread"] != thread_cua_loop

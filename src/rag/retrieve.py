"""Truy hồi có chấm điểm: top-8 → lọc ngưỡng → giữ tối đa 5 (ADR-003).

Ngưỡng `min_score` **không được đặt theo cảm tính** — ADR-003 yêu cầu hiệu chỉnh
bằng bộ eval positive/negative. Giá trị mặc định dưới đây chỉ là điểm khởi đầu
để chạy được, phải chốt lại sau khi calibrate ở M5.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from src.rag.bm25 import BM25Index, hop_nhat_rrf
from src.rag.embed import Embedder
from src.rag.index import SearchHit, VectorIndex, embed_input
from src.rag.models import Chunk, Citation, Evidence
from src.rag.textnorm import lexical_overlap

#: Độ dài tối đa của `excerpt` trong Citation.
EXCERPT_CHARS = 300


class RetrievalConfig(BaseModel):
    """Tham số truy hồi, tách khỏi code để calibrate mà không phải sửa logic.

    Giá trị mặc định là kết quả hiệu chỉnh trên 60 case của `eval/datasets/manual/v1`,
    không phải con số chọn theo cảm tính (ADR-003).
    """

    top_k: int = Field(default=8, ge=1)
    #: Bật hợp nhất BM25 + dense (Hybrid Search). Đo 18/08 trên
    #: `eval/datasets/manual/hoi-nhu-tai-xe-v1`: recall@1 **55% -> 64%**, recall@8
    #: 86% -> 90%, giá 3,5 ms. Để tắt được vì nó đổi thứ tự kết quả của mọi lượt sổ
    #: tay — cần một đường lui không phải sửa code.
    hybrid: bool = Field(default=True)
    #: Số ứng viên dense lấy ra để hợp nhất, **trước** khi cắt còn `top_k`.
    #:
    #: Phải rộng hơn `top_k`: RRF chỉ xếp lại thứ tự, còn `Evidence.score` vẫn là
    #: **cosine** (xem `retrieve`). Một chunk chỉ BM25 tìm ra mà không nằm trong rổ
    #: dense thì không có cosine để chấm, và `grade()` lọc theo cosine. Rổ 50/482
    #: chunk là đủ rộng để chuyện đó hiếm, mà FAISS flat thì tra 50 hay 8 gần như
    #: cùng giá.
    pool_dense: int = Field(default=50, ge=1)
    keep: int = Field(default=5, ge=1)
    min_score: float = Field(default=0.848, ge=0.0, le=1.0)
    min_overlap: float = Field(default=0.65, ge=0.0, le=1.0)


class Retriever:
    """Ghép FAISS index với chunk store để trả về Evidence đã chấm điểm."""

    def __init__(self, index: VectorIndex, chunks: list[Chunk], config: RetrievalConfig | None = None) -> None:
        self._index = index
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._config = config or RetrievalConfig()
        self._bm25_index: BM25Index | None = None

    @property
    def config(self) -> RetrievalConfig:
        return self._config

    def chunk(self, chunk_id: str) -> Chunk | None:
        """Tra ngược chunk từ id — dùng để validate citation."""
        return self._chunks.get(chunk_id)

    def retrieve(self, query: str, embedder: Embedder) -> list[Evidence]:
        """Top-k thô, **chưa** áp ngưỡng — dùng để hiệu chỉnh ngưỡng mà không embed lại.

        Khi `config.hybrid`, thứ tự là kết quả hợp nhất RRF giữa dense và BM25. Nhưng
        `Evidence.score` **vẫn là cosine**, cố ý: `grade()` lọc `score >= min_score`
        (0.848, hiệu chỉnh trên 60 case theo ADR-003). Gán điểm RRF (~0,03) vào đây là
        làm mọi câu hỏi sổ tay bị từ chối — hợp nhất đổi **thứ tự**, không đổi thang đo.
        """
        if not query.strip():
            return []
        so_lay = max(self._config.pool_dense, self._config.top_k) if self._config.hybrid else self._config.top_k
        hits = self._index.search(embedder.embed_query(query), so_lay)
        if self._config.hybrid:
            hits = self._hop_nhat(query, hits)
        hits = hits[: self._config.top_k]
        return [
            Evidence(
                section=chunk.section,
                page=chunk.page or 0,
                text=chunk.text,
                chunk_id=chunk.chunk_id,
                score=hit.score,
                is_table=chunk.is_table,
                has_variant_condition=chunk.has_variant_condition,
            )
            for hit in hits
            if (chunk := self._chunks.get(hit.chunk_id))
        ]

    def _hop_nhat(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Xếp lại `hits` theo RRF giữa thứ tự dense và thứ tự BM25.

        Chunk chỉ BM25 tìm ra mà không có trong rổ dense thì **bỏ** — nó không có cosine
        để `grade()` chấm, và cosine của nó chắc chắn thấp hơn cả rổ 50 nên gần như
        không qua nổi ngưỡng. Bỏ nó là mất một chút recall lý thuyết, đổi lấy việc
        không phải bịa một con số cho cái cổng an toàn ở hạ nguồn.
        """
        thua = self._bm25().search(query, self._config.pool_dense)
        if not thua:
            return hits
        theo_id = {h.chunk_id: h for h in hits}
        xep = hop_nhat_rrf([h.chunk_id for h in hits], [cid for cid, _ in thua])
        return [theo_id[cid] for cid in xep if cid in theo_id]

    def _bm25(self) -> BM25Index:
        """Dựng một lần rồi giữ. Đo 41 ms cho 482 chunk, nên không cần lưu ra đĩa."""
        if self._bm25_index is None:
            self._bm25_index = BM25Index.build(
                [c.chunk_id for c in self._chunks.values()],
                [embed_input(c) for c in self._chunks.values()],
            )
        return self._bm25_index

    def grade(self, query: str, evidence: list[Evidence]) -> list[Evidence]:
        """Chấm độ phủ bằng **hai** tín hiệu rồi giữ tối đa `keep` (ADR-003).

        Chỉ dùng điểm cosine là không đủ: thang điểm của e5 rất nén, và câu hỏi
        ngoài phạm vi nhưng cùng chủ đề vẫn đạt điểm cao. Đo trên 60 case, ngưỡng
        điểm đơn thuần cho hallucination 20%; thêm điều kiện trùng từ vựng kéo
        xuống 5%.
        """
        kept = [
            item
            for item in evidence
            if item.score >= self._config.min_score
            and lexical_overlap(query, item.text) >= self._config.min_overlap
        ]
        return kept[: self._config.keep]

    def search(self, query: str, embedder: Embedder) -> list[Evidence]:
        """Truy hồi đã chấm điểm; danh sách rỗng nghĩa là phải từ chối."""
        return self.grade(query, self.retrieve(query, embedder))


def load_retriever(index_dir: Path, config: RetrievalConfig | None = None) -> Retriever:
    """Nạp index và chunk store đã ingest từ đĩa."""
    from src.rag import store
    from src.rag.ingest.pipeline import DB_FILE

    connection = store.connect(index_dir / DB_FILE)
    try:
        chunks = store.load_chunks(connection)
    finally:
        connection.close()
    return Retriever(VectorIndex.load(index_dir), chunks, config)


def to_citations(evidence: list[Evidence], turn_id: str, document_title: str) -> list[Citation]:
    """Chuyển Evidence thành Citation công khai đúng 8 field của data_model.md."""
    return [
        Citation(
            citation_id=f"cit_{uuid.uuid4().hex[:12]}",
            turn_id=turn_id,
            document_title=document_title,
            section=item.section,
            page=item.page,
            chunk_id=item.chunk_id,
            excerpt=item.text[:EXCERPT_CHARS],
            retrieval_score=max(0.0, min(1.0, item.score)),
        )
        for item in evidence
    ]


def validate_citations(citations: list[Citation], retriever: Retriever) -> bool:
    """Mọi citation phải resolve về chunk có thật và khớp section/page.

    Cổng cứng: `scoring.evaluate_candidate` fail khi `citation_validity < 1.0`.
    """
    if not citations:
        return False
    for citation in citations:
        chunk = retriever.chunk(citation.chunk_id)
        if chunk is None or chunk.section != citation.section or chunk.page != citation.page:
            return False
    return True

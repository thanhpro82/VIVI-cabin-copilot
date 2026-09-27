"""FAISS index cho corpus sổ tay.

Dùng `IndexFlatIP` chứ không phải IVF/HNSW: corpus chỉ khoảng 500 chunk, brute
force là **tìm kiếm chính xác** và mất micro giây. IVF/HNSW là index gần đúng,
sinh ra cho hàng triệu vector — ở quy mô này chúng chỉ làm giảm recall mà không
nhanh hơn.

Vector đã chuẩn hoá L2 nên inner product tương đương cosine.

Một chunk có thể sinh **nhiều** vector (xem `Embedder.split_for_embedding`), nên
`chunk_ids` ánh xạ hàng-vector sang chunk theo quan hệ nhiều-một; `search` gộp
lại và giữ điểm cao nhất.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from src.rag.embed import Embedder
from src.rag.models import Chunk

_INDEX_FILE = "index.faiss"
_IDS_FILE = "vector_ids.json"

#: Lấy dư hàng trước khi gộp theo chunk: nhiều hàng có thể cùng trỏ về một chunk.
_OVERFETCH = 4


@dataclass(frozen=True)
class SearchHit:
    """Một chunk trúng truy vấn kèm điểm cao nhất trong các cửa sổ của nó."""

    chunk_id: str
    score: float


def embed_input(chunk: Chunk) -> str:
    """Văn bản đưa vào embedder: thêm `section` để phân biệt các mục cùng chủ đề."""
    return f"{chunk.section}\n{chunk.text}"


class VectorIndex:
    """FAISS index cùng bảng tra hàng-vector → chunk_id."""

    def __init__(self, index: faiss.Index, chunk_ids: list[str]) -> None:
        self._index = index
        self._chunk_ids = chunk_ids

    @property
    def vector_count(self) -> int:
        return len(self._chunk_ids)

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder) -> VectorIndex:
        """Sinh vector cho mọi cửa sổ của mọi chunk rồi nạp vào IndexFlatIP."""
        texts: list[str] = []
        chunk_ids: list[str] = []
        for chunk in chunks:
            for window in embedder.split_for_embedding(embed_input(chunk)):
                texts.append(window)
                chunk_ids.append(chunk.chunk_id)

        index = faiss.IndexFlatIP(embedder.dimensions)
        if texts:
            index.add(embedder.embed_passages(texts))
        return cls(index, chunk_ids)

    def search(self, vector: np.ndarray, top_k: int) -> list[SearchHit]:
        """Trả về tối đa `top_k` chunk khác nhau, xếp theo điểm giảm dần."""
        if self._index.ntotal == 0 or top_k <= 0:
            return []
        query = np.asarray([vector], dtype=np.float32)
        scores, rows = self._index.search(query, min(top_k * _OVERFETCH, self._index.ntotal))

        best: dict[str, float] = {}
        for score, row in zip(scores[0], rows[0], strict=True):
            if row < 0:
                continue
            chunk_id = self._chunk_ids[int(row)]
            best[chunk_id] = max(best.get(chunk_id, -1.0), float(score))
        ranked = sorted(best.items(), key=lambda item: -item[1])
        return [SearchHit(chunk_id=cid, score=score) for cid, score in ranked[:top_k]]

    def save(self, directory: Path) -> str:
        """Ghi index xuống đĩa, trả về checksum để đưa vào manifest."""
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / _INDEX_FILE))
        (directory / _IDS_FILE).write_text(json.dumps(self._chunk_ids), encoding="utf-8")
        return self.checksum(directory)

    @classmethod
    def load(cls, directory: Path) -> VectorIndex:
        """Nạp index đã ghi trước đó."""
        index = faiss.read_index(str(directory / _INDEX_FILE))
        chunk_ids = json.loads((directory / _IDS_FILE).read_text(encoding="utf-8"))
        return cls(index, chunk_ids)

    @staticmethod
    def checksum(directory: Path) -> str:
        """SHA-256 của file index — `index_checksum` trong manifest."""
        digest = hashlib.sha256((directory / _INDEX_FILE).read_bytes())
        return f"sha256:{digest.hexdigest()}"

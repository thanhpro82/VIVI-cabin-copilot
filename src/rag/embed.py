"""Sinh vector cho chunk và câu hỏi.

`multilingual-e5-small` là mô hình retrieval **bất đối xứng**: văn bản phải mang
tiền tố `passage: ` còn câu hỏi mang `query: `. Quên tiền tố không gây lỗi, không
có cảnh báo — chỉ có chất lượng retrieval tụt mà không rõ nguyên nhân. Vì vậy
tiền tố được gắn **bên trong** embedder, caller không có cơ hội quên.
"""

from __future__ import annotations

import hashlib
import os
from typing import Protocol, runtime_checkable

import numpy as np

MODEL_NAME = "intfloat/multilingual-e5-small"
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

#: Trần cứng của `multilingual-e5-small`.
MODEL_MAX_TOKENS = 512

#: Ngân sách token cho phần nội dung của một cửa sổ. Chừa chỗ cho 2 special token
#: và tiền tố `passage: `, cộng biên an toàn.
TOKEN_BUDGET = 480
TOKEN_OVERLAP = 60

#: Cửa sổ ký tự — chỉ dùng cho embedder **không có** tokenizer (ví dụ StubEmbedder
#: trên CI). Đây là **ước lượng, không phải bảo đảm**: đo trên corpus VF9, tỷ lệ
#: ký tự/token dao động 2,41–4,21 nên cùng một số ký tự có thể ra 380 hoặc 665
#: token tuỳ nội dung. Bảng thông số và danh sách số liệu tokenize dày nhất.
WINDOW_CHARS = 1600
WINDOW_OVERLAP = 200


@runtime_checkable
class Embedder(Protocol):
    """Giao diện tối thiểu để index và retrieval không phụ thuộc mô hình cụ thể."""

    dimensions: int

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...

    def split_for_embedding(self, text: str) -> list[str]: ...


def window_spans(offsets: list[tuple[int, int]], budget: int, overlap: int) -> list[tuple[int, int]]:
    """Gom offset ký tự của các token thành những khoảng ≤ `budget` token.

    Hàm thuần, không phụ thuộc mô hình, nên CI test được mà không cần tokenizer.
    Trả về khoảng ký tự trên chuỗi **gốc** thay vì decode ngược từ token id —
    decode ngược làm sai lệch khoảng trắng và ký tự đặc biệt.
    """
    if not offsets:
        return []
    if len(offsets) <= budget:
        return [(offsets[0][0], offsets[-1][1])]

    step = max(budget - overlap, 1)
    spans: list[tuple[int, int]] = []
    for start in range(0, len(offsets), step):
        window = offsets[start : start + budget]
        if not window:
            break
        spans.append((window[0][0], window[-1][1]))
        if start + budget >= len(offsets):
            break
    return spans


def window_text(text: str) -> list[str]:
    """Cắt văn bản dài thành cửa sổ chồng lấn **theo ký tự**.

    Chỉ là phương án dự phòng khi embedder không cho biết tokenizer của nó.
    Đếm ký tự không suy ra được số token, nên hàm này **không bảo đảm** kết quả
    nằm dưới trần của mô hình — xem `E5Embedder.split_for_embedding` cho đường
    đi chính xác.
    """
    if len(text) <= WINDOW_CHARS:
        return [text]
    step = WINDOW_CHARS - WINDOW_OVERLAP
    windows = [text[start : start + WINDOW_CHARS] for start in range(0, len(text), step)]
    return [window for window in windows if window.strip()]


class E5Embedder:
    """Embedder thật, tải `multilingual-e5-small` chạy local trên CPU."""

    dimensions = 384

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        # `local_files_only=True` alone does NOT close the network path, which is
        # what the comment below assumed when it was written on 2026-08-13.
        # Measured on 2026-08-21: constructing this class still left one
        # ESTABLISHED HTTPS connection to huggingface.co's CDN
        # (2600:9000::/28, CloudFront) open for the life of the process, with
        # the weights already cached and `local_files_only=True` in force. The
        # flag governs whether files are *fetched*; the hub client still opens
        # its session. `src/offline_guard.py` caught it once the full test suite
        # could run end to end -- see tests/test_offline_guard.py.
        #
        # `scripts/offline_drill.py` did NOT catch it, and was not wrong to
        # miss it: the drill blocks DNS, so the hub client cannot open a socket
        # at all and the RAG case passes correctly (run
        # eval/results/offline-drill/20260815T103754.705204Z/, 7/7). The drill
        # proves "nothing escapes when blocked"; it cannot prove "runtime does
        # not reach out when the network is up" -- which is the state a demo
        # machine is normally in.
        #
        # HF_HUB_OFFLINE is read by huggingface_hub at import time, so it has to
        # be set before the import below, not merely before the constructor.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

        from sentence_transformers import SentenceTransformer

        # `local_files_only=True` là bắt buộc, không phải tối ưu. Thiếu nó thì
        # `sentence_transformers` hỏi HF Hub xem model có bản mới không **mỗi lần
        # khởi động** — đo trên máy dev 2026-08-13: ~20 request HEAD/GET tới
        # huggingface.co trong log `python -m src.serve`, dù weight đã nằm sẵn trong
        # cache và không tải thêm byte nào.
        #
        # Đó là network lúc runtime, thứ ADR-001 cấm: "Internet chỉ được dùng TRƯỚC
        # runtime để cài dependency/tải artifact. Offline drill tắt network và là
        # release gate." Và `docs/demo_script.md` mở màn bằng đúng thao tác tắt mạng ở
        # giây thứ 0 — nên nếu không chặn ở đây thì bài demo được chấm điểm sẽ treo
        # chờ timeout ngay khi khởi động.
        #
        # Đánh đổi đã cân nhắc: máy **chưa** có cache sẽ lỗi thẳng thay vì tự tải.
        # Đó là hành vi đúng theo bất biến "no auto-download of model artifacts" —
        # tải artifact là việc của bước chuẩn bị (`scripts/prepare_vf9_index.ps1`),
        # không phải việc hàm khởi tạo tự làm sau lưng người chạy.
        self._model = SentenceTransformer(model_name, local_files_only=True)

    def split_for_embedding(self, text: str) -> list[str]:
        """Cắt cửa sổ **theo token thật** của chính mô hình này.

        `SentenceTransformer` cắt cụt input vượt trần một cách im lặng — không
        exception, không cảnh báo — nên phần đuôi biến mất khỏi vector index mà
        không ai biết. Chỉ embedder mới biết tokenizer của nó, vì vậy trách nhiệm
        chống cắt cụt nằm ở đây chứ không ở người gọi.
        """
        tokenizer = self._model.tokenizer
        if not getattr(tokenizer, "is_fast", False):
            return window_text(text)
        encoding = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        spans = window_spans(encoding["offset_mapping"], TOKEN_BUDGET, TOKEN_OVERLAP)
        return [text[start:end] for start, end in spans if text[start:end].strip()] or [text]

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        """Vector cho văn bản sổ tay; tiền tố `passage: ` được gắn tự động."""
        return self._encode([PASSAGE_PREFIX + text for text in texts])

    def embed_query(self, text: str) -> np.ndarray:
        """Vector cho câu hỏi; tiền tố `query: ` được gắn tự động."""
        return self._encode([QUERY_PREFIX + text])[0]


class StubEmbedder:
    """Embedder tất định dựa trên băm từ, dùng cho CI.

    CI không tải nổi `torch` mỗi lần chạy (ADR-001: *"CI dùng fake/tiny model"*).
    Vector là túi từ đã băm nên vẫn phản ánh độ trùng từ vựng — đủ để test thứ tự
    xếp hạng mà không cần mô hình thật.
    """

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def split_for_embedding(self, text: str) -> list[str]:
        """Không có tokenizer nên dùng cửa sổ ký tự; đủ cho test cấu trúc."""
        return window_text(text)

    def _encode_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for word in text.lower().split():
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._encode_one(PASSAGE_PREFIX + text) for text in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode_one(QUERY_PREFIX + text)

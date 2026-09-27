"""BM25 thưa trên corpus sổ tay, để ghép với tìm kiếm dense (Hybrid Search).

## Vì sao cần

Đo ngày 18/08 trên bộ `manual/hoi-nhu-tai-xe-v1` — câu hỏi viết theo giọng tài xế, sinh
từ **tên mục** chứ không từ thân đoạn:

    recall@1 = 55%    recall@8 = 86%    6/42 ca không có trong top-8

Trong khi bộ `manual/v1` cũ cho `recall@1 = 98%`. Chênh 43 điểm, và nó không phải vì hệ
thống đổi — nó vì bộ cũ **viết câu hỏi bằng chữ của đoạn**, nên nó đo độ dễ của bộ đề.

Dense embedding hỏng theo những kiểu đã có tên: *entity-swap* ("lốp dự phòng" vs "áp
suất lốp tiêu chuẩn" cách nhau 0,0001 điểm), và *vocabulary gap*. BM25 khớp **đúng từ**
nên nó mạnh chính ở chỗ dense yếu — và ngược lại. Ghép hai cái là cách xử lý tiêu chuẩn.

## Vì sao tự cài thay vì thêm phụ thuộc

BM25 là một công thức, không phải một hệ thống: bản dưới đây ~40 dòng. Repo này có kỷ
luật "không tải artifact lúc chạy" và một danh sách phụ thuộc cố ý mỏng; thêm một gói
cho một công thức đếm từ là cái giá không tương xứng.

Dùng lại `textnorm._tokens` — **giữ nguyên dấu thanh**. Bỏ dấu sẽ làm "bò/bỏ/bó" thành
một từ, đúng lỗi mà chú thích trong `textnorm.py` đã cảnh báo.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from src.rag.textnorm import STOPWORDS, _tokens

#: Tham số chuẩn của BM25. Không chỉnh theo corpus này — chỉnh mà không có tập giữ lại
#: thì chỉ là học thuộc bộ đề.
K1 = 1.5
B = 0.75


def _tu_khoa(raw: str) -> list[str]:
    """Từ mang nghĩa. Bỏ hư từ vì chúng có mặt ở mọi đoạn nên không phân biệt được gì."""
    return [t for t in _tokens(raw) if t not in STOPWORDS and len(t) > 1]


@dataclass
class BM25Index:
    """Chỉ mục thưa. `ids[i]` ứng với tài liệu thứ `i`."""

    ids: list[str]
    _tf: list[Counter[str]]
    _df: Counter[str]
    _do_dai: list[int]
    _dai_tb: float

    @classmethod
    def build(cls, ids: list[str], texts: list[str]) -> BM25Index:
        tf = [Counter(_tu_khoa(t)) for t in texts]
        df: Counter[str] = Counter()
        for c in tf:
            df.update(c.keys())
        do_dai = [sum(c.values()) for c in tf]
        return cls(ids, tf, df, do_dai, (sum(do_dai) / len(do_dai)) if do_dai else 0.0)

    def _idf(self, tu: str) -> float:
        n = len(self.ids)
        df = self._df.get(tu, 0)
        # Dạng có làm trơn: df = 0 vẫn cho số dương hữu hạn thay vì vô cực.
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        tu_q = _tu_khoa(query)
        if not tu_q or not self.ids:
            return []
        diem: list[tuple[str, float]] = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            for tu in tu_q:
                f = tf.get(tu, 0)
                if not f:
                    continue
                chuan = 1 - B + B * (self._do_dai[i] / self._dai_tb if self._dai_tb else 1.0)
                s += self._idf(tu) * (f * (K1 + 1)) / (f + K1 * chuan)
            if s > 0:
                diem.append((self.ids[i], s))
        diem.sort(key=lambda x: -x[1])
        return diem[:top_k]


#: Hằng số RRF. 60 là giá trị trong bài gốc và là mặc định của mọi hệ thống dùng nó;
#: đổi nó cần một tập giữ lại, không phải một buổi chiều.
RRF_K = 60


def hop_nhat_rrf(*bang_xep: list[str], k: int = RRF_K) -> list[str]:
    """Reciprocal Rank Fusion: `score(d) = Σ 1/(k + hạng_i(d))`.

    Hợp nhất theo **hạng**, không theo điểm — cố ý. Điểm cosine và điểm BM25 nằm ở hai
    thang khác hẳn nhau, nên cộng thẳng là để một bên áp đảo bên kia vì lý do đơn vị chứ
    không vì nó đúng hơn.
    """
    diem: dict[str, float] = {}
    for bang in bang_xep:
        for hang, doc in enumerate(bang):
            diem[doc] = diem.get(doc, 0.0) + 1.0 / (k + hang)
    return [d for d, _ in sorted(diem.items(), key=lambda x: -x[1])]

r"""Đo recall của truy hồi trên `manual/hoi-nhu-tai-xe-v1` (18/08).

## Vì sao cần bộ đo thứ hai

`manual/v1` đạt `recall@1 = 98%`, và tôi đã trích con số ấy nhiều lần để kết luận
"truy hồi ổn, nút thắt ở chọn câu". Con số ấy **không đáng tin theo hướng lạc quan**:
40 câu hỏi ở đó do nhóm RAG viết **cho chính corpus này**, nên chúng dùng chữ của đoạn.
Cùng khuyết điểm mà `CLAUDE.md` chỉ ra ở `agent/v3`.

Câu hỏi thật của người dùng — *"áp suất lốp tiêu chuẩn là bao nhiêu?"* — lộ ngay khoảng
cách ấy: đoạn đúng xếp **hạng 2, thua 0,0001 điểm**.

## Giao thức chống nhiễm

Câu hỏi sinh từ **tên mục**, không từ thân đoạn. Nên "mục đúng" biết trước **do cấu
tạo** — không cần gán nhãn hậu kỳ, và không có đường nào để chữ của đoạn rò vào câu hỏi.

Đổi lại, thước ở đây **thô hơn**: nó hỏi *"top-k có chunk nào thuộc đúng mục không"*,
không phải *"đúng chunk nào"*. Mục 22 chunk dễ trúng hơn mục 1 chunk, nên báo cáo in
kèm số chunk mỗi mục để độ khó nhìn thấy được.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BO = Path("eval/datasets/manual/hoi-nhu-tai-xe-v1/cases.jsonl")


def main() -> int:
    from src.agents.nodes.rag_node import _default_embedder, _default_retriever

    r, emb = _default_retriever(), _default_embedder()
    emb.embed_query("làm nóng")
    so_chunk: dict[str, int] = {}
    for ch in r._chunks.values():
        so_chunk[ch.section] = so_chunk.get(ch.section, 0) + 1

    rows = [json.loads(d) for d in BO.read_text(encoding="utf-8").splitlines() if d.strip()]
    hang: list[tuple[str, int | None, int]] = []
    for c in rows:
        ev = r.retrieve(c["question"], emb)
        vt = next((i for i, e in enumerate(ev) if e.section == c["section"]), None)
        hang.append((c["case_id"], vt, so_chunk.get(c["section"], 0)))

    n = len(hang)
    print(f"{n} ca · {BO.parent.name}\n")
    for k in (1, 2, 3, 5, 8):
        dat = sum(1 for _, v, _ in hang if v is not None and v < k)
        print(f"  recall@{k}: {dat:2}/{n} = {dat / n:4.0%}")
    truot = [(c, s) for c, v, s in hang if v is None]
    print(f"\n  không có trong top-8: {len(truot)}/{n}")
    for c, s in truot:
        q = next(x["question"] for x in rows if x["case_id"] == c)
        print(f"    {c}  ({s} chunk trong mục)  {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

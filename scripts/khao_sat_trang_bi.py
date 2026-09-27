r"""Khảo sát mệnh đề điều kiện trang bị trong sổ tay, và đo phủ sóng của danh mục.

## Nó trả lời câu gì

*"Hồ sơ xe đầy đủ nên gồm những gì?"* — bằng cách đếm thay vì đoán. Quét toàn bộ chunk
store, tìm mọi mệnh đề `"(nếu có)"` / `"nếu được trang bị"` / `"tuỳ theo thị trường"`,
rồi hỏi `src/safety/trang_bi.nhan_dien()` xem mệnh đề ấy nói về trang bị nào.

## Con số quan trọng là con số CHƯA NHẬN RA

Phủ sóng cao mà không đọc phần còn lại là tự lừa: danh mục có thể phủ 100% chỉ vì nó
gom nhầm mọi thứ vào một mục. Nên script in **toàn bộ** mệnh đề chưa nhận ra, để người
đọc tự xếp chúng vào một trong ba loại (xem docstring `src/safety/trang_bi.py`):

- **loại 1** trang bị tuỳ chọn — nếu còn sót ở đây thì danh mục thiếu, phải bổ sung;
- **loại 2** dữ liệu vắng lúc chạy (*"cảnh báo lỗi (nếu có)"*) — đúng ra phải nằm ngoài;
- **loại 3** điều kiện về thứ khác, không phải về xe — cũng nằm ngoài.

Nói cách khác: 100% phủ sóng ở đây sẽ là **dấu hiệu xấu**, vì nó có nghĩa danh mục đã
nuốt cả loại 2 và loại 3.

Chạy (cần chunk store; CI không có):
    .\.venv\Scripts\python.exe scripts\khao_sat_trang_bi.py
"""

from __future__ import annotations

import collections
import json
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.safety.trang_bi import DAU_DIEU_KIEN, doc_danh_muc, nhan_dien  # noqa: E402

RA = Path("eval/results/trang-bi")


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    from src.agents.nodes.rag_node import _default_retriever

    chunks = list(_default_retriever()._chunks.values())  # noqa: SLF001
    dm = doc_danh_muc()

    lan_nhac: list[dict] = []
    for c in chunks:
        van = re.sub(r"\s+", " ", c.text or "")
        if not DAU_DIEU_KIEN.search(van):
            continue
        # `nhan_dien` trả theo THỨ TỰ xuất hiện và đã khử trùng, nên nó không ghép được
        # một-một với từng dấu. Dò lại từng dấu ở đây để đếm cho đúng đơn vị "lần nhắc".
        for m in DAU_DIEU_KIEN.finditer(van):
            manh = van[max(0, m.start() - 90) : m.end() + 40].strip()
            ma = nhan_dien(van[max(0, m.start() - 90) : m.end()])
            lan_nhac.append(
                {
                    "chunk_id": c.chunk_id,
                    "muc": c.section,
                    "dau": m.group(0),
                    "trang_bi": ma[-1] if ma else None,
                    "ngu_canh": manh,
                }
            )

    n = len(lan_nhac)
    nhan_ra = [r for r in lan_nhac if r["trang_bi"]]
    chua = [r for r in lan_nhac if not r["trang_bi"]]
    thay = collections.Counter(r["trang_bi"] for r in nhan_ra)

    print(f"{len(chunks)} chunk, {sum(1 for c in chunks if DAU_DIEU_KIEN.search(c.text or ''))} chunk có điều kiện")
    print(f"{n} lần nhắc — nhận ra {len(nhan_ra)} ({len(nhan_ra) / n:.0%}), chưa nhận ra {len(chua)}")
    print(f"danh mục {len(dm)} trang bị, {sum(1 for t in dm if t.id in thay)} trong số đó thấy trong sổ tay\n")

    print("trang bị KHÔNG thấy lần nhắc nào (danh mục nói có, sổ tay không xác nhận):")
    im = [t.id for t in dm if t.id not in thay]
    print("   " + (", ".join(im) if im else "(không có)"))

    print(f"\n{len(chua)} mệnh đề chưa nhận ra — xếp loại bằng mắt, xem docstring:")
    for r in chua:
        print(f"   [{(r['muc'] or '?').split('/')[-1][:22]:22}] ...{r['ngu_canh'][-104:]}")

    run = RA / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "suite": "trang-bi",
                "commit": _git("rev-parse", "HEAD"),
                "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "phien_ban_so_tay": dm.phien_ban_so_tay,
                "machine": platform.machine(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run / "metrics.json").write_text(
        json.dumps(
            {
                "so_chunk": len(chunks),
                "so_lan_nhac": n,
                "nhan_ra": len(nhan_ra),
                "ty_le_nhan_ra": round(len(nhan_ra) / n, 4),
                "so_trang_bi_trong_danh_muc": len(dm),
                "trang_bi_khong_thay_trong_so_tay": im,
                "theo_trang_bi": dict(thay.most_common()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with (run / "case_results.jsonl").open("w", encoding="utf-8") as f:
        for r in lan_nhac:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nrun: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

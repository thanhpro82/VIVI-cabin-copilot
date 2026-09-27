r"""Sinh **bản nháp** khoá "ý phải giữ" từ `answer_keys.jsonl`.

Đầu ra là `y_phai_giu.nhap.jsonl`, **không** phải khoá. Người phải rà từng ca rồi mới
đổi tên thành `y_phai_giu.jsonl`.

Lý do bắt buộc rà tay: chính bộ luật trong tệp này là thứ tầng nén sẽ bị chấm theo.
Để nguyên nháp làm khoá là tự chấm bài mình — đúng lỗi `CLAUDE.md` ghi về `agent/v3`
("người viết router cũng là người viết bộ test", nên `intent_accuracy = 1.0000` chỉ là
dây bẫy hồi quy chứ không nói gì về khái quát hoá).

Chạy:
    .\.venv\Scripts\python.exe scripts\soan_y_phai_giu.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.nodes.speech_policy import _NUMBER_WITH_UNIT  # noqa: E402

VAO = Path("eval/datasets/manual/v1/answer_keys.jsonl")
RA = Path("eval/datasets/manual/v1/y_phai_giu.nhap.jsonl")

#: Cụm phủ định lấy nguyên **cả động từ theo sau**: chốt "không" một mình vô nghĩa vì
#: nó xuất hiện khắp nơi; chốt "không sử dụng" mới nói được điều gì đã mất.
_PHU_DINH = re.compile(
    r"\b(?:không|chưa|đừng|chớ|cấm|chẳng)\s+(?:được\s+|nên\s+|bao giờ\s+)?[\wÀ-ỹ]+(?:\s+[\wÀ-ỹ]+)?",
    re.IGNORECASE,
)

#: Vế điều kiện theo phiên bản/trang bị. Đây là lớp lỗi ADR-015 đo được 4/40.
_DIEU_KIEN = re.compile(
    r"(?:nếu được trang bị|nếu có|tuỳ phiên bản|tùy phiên bản|nếu xe được trang bị)",
    re.IGNORECASE,
)


def _cum(pattern: re.Pattern[str], text: str) -> list[str]:
    """Các cụm khớp, giữ thứ tự xuất hiện, bỏ trùng."""
    thay: list[str] = []
    for m in pattern.finditer(text):
        c = m.group().strip().rstrip(".,;:")
        if c and c not in thay:
            thay.append(c)
    return thay


def main() -> int:
    rows = [json.loads(x) for x in VAO.read_text(encoding="utf-8").splitlines() if x.strip()]
    ra: list[dict] = []
    for r in rows:
        if not r.get("doan_co_cau_tra_loi"):
            continue
        dap_an = " ".join(str(x) for x in r.get("cau_tra_loi") or [])
        chot: list[dict] = []
        for loai, pat in (("dieu_kien", _DIEU_KIEN), ("phu_dinh", _PHU_DINH), ("dai_luong", _NUMBER_WITH_UNIT)):
            cum = _cum(pat, dap_an)
            if cum:
                chot.append({"loai": loai, "cum": cum})
        ra.append({"case_id": r["case_id"], "chot": chot, "soan_boi": "NHAP-LUAT-CHUA-RA-SOAT"})

    RA.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in ra) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    co = sum(1 for x in ra if x["chot"])
    print(f"{len(ra)} ca -> {RA}")
    print(f"  co it nhat mot cum chot : {co}")
    print(f"  KHONG co cum nao        : {len(ra) - co}   <- nhung ca nay can nguoi them tay")
    for loai in ("dieu_kien", "phu_dinh", "dai_luong"):
        n = sum(1 for x in ra for m in x["chot"] if m["loai"] == loai)
        print(f"  {loai:10}: {n} ca")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

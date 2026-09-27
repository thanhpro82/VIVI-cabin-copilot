#!/usr/bin/env python3
"""Bao cao timeout cua SLM, doc tu journal cua vivi-slm.

Ghep launch -> cancel -> print_timing -> release theo task id, dung dong ho
RIENG cua llama-server (dang MM.SS.mmm.uuu tinh tu luc server khoi dong) chu
khong dung dau thoi gian cua journald: journald chi co do phan giai 1 giay,
qua tho de phan biet tran 2s voi tran 4s.

Cach dung, tren VPS:
    sudo journalctl -u vivi-slm --since "-24h" --no-pager | python3 slm_timeout_report.py
"""

from __future__ import annotations

import re
import sys

# 59.54.344.451  ->  phut.giay.ms.us
TS = re.compile(r"\b(\d+)\.(\d{2})\.(\d{3})\.(\d{3})\b")
LAUNCH = re.compile(r"launch_slot_:.*?\btask (\d+)\b")
CANCEL = re.compile(r"cancel task, id_task = (\d+)")
TOTAL = re.compile(r"print_timing:.*?\btask (\d+)\b.*?total time =\s*([\d.]+) ms")
RELEASE = re.compile(r"release:.*?\btask (\d+)\b")


def ts_seconds(line: str) -> float | None:
    m = TS.search(line)
    if not m:
        return None
    mm, ss, ms, us = (int(g) for g in m.groups())
    return mm * 60 + ss + ms / 1e3 + us / 1e6


def main() -> int:
    launch: dict[int, float] = {}
    cancel: dict[int, float] = {}
    total: dict[int, float] = {}
    release: dict[int, float] = {}

    for line in sys.stdin:
        t = ts_seconds(line)
        if t is None:
            continue
        if m := LAUNCH.search(line):
            launch[int(m.group(1))] = t
        elif m := CANCEL.search(line):
            cancel[int(m.group(1))] = t
        elif m := TOTAL.search(line):
            total[int(m.group(1))] = float(m.group(2))
        elif m := RELEASE.search(line):
            release[int(m.group(1))] = t

    print(f"Tong luot goi (launch)      : {len(launch)}")
    print(f"Bi cat giua chung (cancel)  : {len(cancel)}")
    if launch:
        print(f"Ty le bi cat                : {len(cancel) / len(launch):.0%}")
    print()

    if not cancel:
        print("Khong co luot nao bi cat trong cua so nay.")
        return 0

    print("CAC LUOT BI CAT")
    print(f"{'task':>6}  {'cat sau':>9}  {'tran khop':>10}  {'thuc su can':>12}  {'giu slot them':>14}")
    print("-" * 60)

    cuu_duoc: list[float] = []
    for task in sorted(cancel):
        t_cancel = cancel[task]
        t_launch = launch.get(task)
        cut = f"{t_cancel - t_launch:.3f}s" if t_launch is not None else "?"

        # Tran nao da ban: 2.0 = slm_classify_timeout_s, 4.0 = slm_chitchat_timeout_s,
        # 8.0/20.0 = slm_timeout_s (planner / cau dan). Khop theo khoang +-0.25s.
        tran = "?"
        if t_launch is not None:
            d = t_cancel - t_launch
            for nguong, ten in ((2.0, "2s classify"), (4.0, "4s chitchat"), (8.0, "8s planner"), (20.0, "20s planner")):
                if abs(d - nguong) <= 0.25:
                    tran = ten
                    break

        can = f"{total[task]:.0f}ms" if task in total else "khong ro"
        if task in total and t_launch is not None:
            cuu_duoc.append(total[task] / 1000)

        them = "-"
        if task in release and t_cancel is not None:
            them = f"{release[task] - t_cancel:.2f}s"

        print(f"{task:>6}  {cut:>9}  {tran:>10}  {can:>12}  {them:>14}")

    print()
    if cuu_duoc:
        cuu_duoc.sort()
        print("Trong so cac luot bi cat, llama-server VAN bao tong thoi gian that:")
        print(f"  n = {len(cuu_duoc)}, nho nhat {min(cuu_duoc):.2f}s, lon nhat {max(cuu_duoc):.2f}s")
        for nguong in (2.5, 3.0, 3.5, 4.0, 5.0, 6.0):
            n = sum(1 for v in cuu_duoc if v <= nguong)
            print(f"  neu tran = {nguong:>4.1f}s  ->  cuu duoc {n}/{len(cuu_duoc)}")
        print()
        print("Doc bang tren: 'cuu duoc' nghia la lan do LE RA da kip neu tran cao hon.")
        print("Nhung tran cao hon cung co nghia moi lan server that su om, tai xe doi lau hon.")
    else:
        print("Khong luot bi cat nao con bao total time — khong suy ra duoc tran nen dat bao nhieu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

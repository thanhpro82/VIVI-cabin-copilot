"""Do do tre THAT cua vai classify, tren may that.

Chay BEN TRONG container backend de dung dung QwenClassifier that (dung prompt,
dung json_schema, dung n_predict, va tinh ca chang mang container -> host):

    cd /opt/vivi && docker compose exec -T backend python - < ~/slm_classify_bench.py

Tran duoc dat 30s co y: muc tieu la do XEM NO CAN BAO LAU, khong phai xem no co
kip 2s khong. Cat o 2s thi moi lan hut deu tra ve cung mot con so 2.0 va khong
hoc duoc gi.
"""

from __future__ import annotations

import statistics
import time

from src.agents.slm import QwenClassifier
from src.config import get_settings

# Cau TRUOT luat tat dinh — dung loai cau that su cham toi classifier.
# Ba nhom co y: dieu khien la mieng, xa giao, va hoi so tay.
CASES = [
    "mở hé cửa sổ bên phải một chút",
    "hôm nay trời đẹp nhỉ",
    "xe này chạy được bao xa một lần sạc",
    "làm ơn cho mát hơn tí nữa",
    "bạn tên gì thế",
    "đèn báo màu vàng hình cái lò xo là gì",
    "chỉnh ghế lùi ra sau giúp mình",
    "cảm ơn nhé",
    "sạc nhanh mất bao lâu",
    "bật cái gì đó cho đỡ nóng",
]

ROUNDS = 2


def main() -> None:
    s = get_settings()
    print(f"endpoint = {s.slm_endpoint}")
    print(f"model_id = {s.slm_model_id}")
    print(f"tran that trong cau hinh: SLM_CLASSIFY_TIMEOUT_S = {s.slm_classify_timeout_s}s")
    print("tran dung khi DO: 30.0s\n")

    clf = QwenClassifier(s.slm_endpoint, s.slm_model_id, timeout_s=30.0)

    # Luot ham nong: nap KV cache cho tien to CLASSIFY_SYSTEM. Luot dau bao gio
    # cung dat hon han va khong dai dien cho luc chay that (tru dung luot dau
    # sau khi restart server).
    t0 = time.perf_counter()
    try:
        clf.classify("kiểm tra hệ thống")
        warm = time.perf_counter() - t0
        print(f"Luot ham nong (cache lanh): {warm * 1000:.0f} ms — KHONG tinh vao thong ke\n")
    except Exception as exc:  # noqa: BLE001 — do luong, khong phai duong chay that
        print(f"Luot ham nong LOI: {type(exc).__name__}: {exc}\n")

    rows: list[tuple[str, float, str]] = []
    for r in range(ROUNDS):
        for text in CASES:
            t0 = time.perf_counter()
            try:
                out = clf.classify(text)
            except Exception as exc:  # noqa: BLE001
                out = f"LOI:{type(exc).__name__}"
            dt = (time.perf_counter() - t0) * 1000
            rows.append((text, dt, out))
            print(f"  [{r + 1}/{ROUNDS}] {dt:7.0f} ms  {out:<14} {text}")

    ok = [dt for _, dt, out in rows if not out.startswith("LOI:")]
    if not ok:
        print("\nKhong luot nao thanh cong — xem loi o tren.")
        return

    ok.sort()
    n = len(ok)

    def pct(p: float) -> float:
        # index dung kieu nearest-rank, KHONG dung int(n*p)-1: voi n nho, cong
        # thuc kia loai luon gia tri lon nhat ra khoi p95 (loi da gap o
        # spike3_bench total_ms_p95).
        import math

        return ok[min(n - 1, max(0, math.ceil(p * n) - 1))]

    print(f"\n{'=' * 56}")
    print(f"n = {n} luot thanh cong / {len(rows)} luot chay")
    print(f"  nho nhat  {ok[0]:7.0f} ms")
    print(f"  p50       {statistics.median(ok):7.0f} ms")
    print(f"  p95       {pct(0.95):7.0f} ms")
    print(f"  lon nhat  {ok[-1]:7.0f} ms")

    print("\nNeu dat tran o cac muc sau thi bao nhieu luot KIP:")
    for tran in (2.0, 2.5, 3.0, 3.5, 4.0, 5.0):
        kip = sum(1 for v in ok if v <= tran * 1000)
        danh_dau = "  <-- hien tai" if abs(tran - 2.0) < 1e-9 else ""
        print(f"  tran {tran:>4.1f}s  ->  {kip:>2}/{n}  ({kip / n:.0%}){danh_dau}")

    print(f"\n{'=' * 56}")
    print("Doc ket qua:")
    print("- Ty le KIP o tran 2.0s chinh la ty le vai classify dang thuc su lam viec.")
    print("- Phan con lai roi ve tra so tay (ADR-011 cu) sau khi da tieu ton 2 giay.")
    print("- Tran cao hon cuu duoc nhieu luot hon, nhung moi luot THAT SU hong")
    print("  cung bat tai xe doi lau hon dung bay nhieu. Do la danh doi, khong")
    print("  phai cai tien mien phi.")


if __name__ == "__main__":
    main()

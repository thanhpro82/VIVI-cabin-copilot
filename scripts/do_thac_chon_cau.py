r"""Đo tầng CHỌN CÂU: luật S1 hiện tại so với thác E5 → cross-encoder.

## Vì sao script này tồn tại

Báo cáo 17/08 trích con số "thác đạt F1 58% ở 1018 ms" nhưng **không có script nào
trong repo tái lập được nó** — nó chạy ở một tệp nháp rồi mất. Theo kỷ luật
"evidence is the product" thì một con số không tái lập được là một con số không
dùng được. Đây là bản viết lại, chạy được, ghi ra thư mục run bất biến.

## Nó đo cái gì, và cố ý KHÔNG đo cái gì

Đoạn lấy thẳng từ `answer_keys.jsonl` chứ không qua truy hồi. Nghĩa là truy hồi bị
loại khỏi phép đo **có chủ ý**: recall@1 hiện là 62% (`hoi-nhu-tai-xe-v1`), và trộn
hai tầng vào một con số thì không biết cải thiện đến từ đâu. Ở đây mọi ca đều được
đưa đúng đoạn, nên chênh lệch duy nhất là cách chọn câu.

## Hai thước, cố ý không gộp

`f1_chi_so` chấm theo **tập chỉ số câu**, so với `chi_so_cau_tra_loi`. Sắc nhưng phụ
thuộc cách tách câu: khoá được gán bằng một bộ tách, nếu bộ tách đổi thì chỉ số lệch.

`f1_ky_tu` chấm theo **độ phủ ký tự** giữa chuỗi nói ra và các câu đáp án. Thô hơn
nhưng không phụ thuộc chỉ số. Nó tồn tại vì thước cũ chỉ hỏi "có chứa đáp án không"
nên **thưởng cho sự dài dòng** — đúng thứ đã sinh ra lời phàn nàn ban đầu.

Hai thước lệch nhau là tín hiệu đáng đọc, không phải lỗi. Nên chúng in riêng.

Chạy:
    .\.venv\Scripts\python.exe scripts\do_thac_chon_cau.py
    .\.venv\Scripts\python.exe scripts\do_thac_chon_cau.py --fp32   # đối chứng int8
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.nodes.speech_policy import _cau, xep_hang_theo_lien_quan  # noqa: E402

KHOA = Path("eval/datasets/manual/v1/answer_keys.jsonl")

RA = Path("eval/results/chon-cau")
MODEL = Path("models/reranker/bge-reranker-v2-m3")
NGAN_SACH = 240


@dataclass
class Diem:
    p: float
    r: float
    f1: float


def _f1(giao: int, chon: int, that: int) -> Diem:
    p = giao / chon if chon else 0.0
    r = giao / that if that else 0.0
    return Diem(p, r, 2 * p * r / (p + r) if p + r else 0.0)


def diem_chi_so(chon: list[int], that: list[int]) -> Diem:
    return _f1(len(set(chon) & set(that)), len(set(chon)), len(set(that)))


def diem_ky_tu(noi: str, cau_dap_an: list[str]) -> Diem:
    """Phủ ký tự, khớp theo tiền tố dài nhất.

    Không dùng chỉ số nên không vỡ khi cách tách câu đổi. Khớp tiền tố chứ không
    khớp nguyên câu vì bộ gộp dưới trần 240 ký tự hay cắt câu cuối giữa chừng —
    tính cả câu ấy là 0 điểm sẽ phạt sai chỗ.
    """
    trung = 0
    for c in cau_dap_an:
        for k in range(len(c), 9, -1):
            if c[:k] in noi:
                trung += k
                break
    return _f1(trung, len(noi), sum(len(c) for c in cau_dap_an))


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp32", action="store_true", help="tắt int8, để đối chứng lượng tử hoá")
    ap.add_argument("--pool", type=int, default=4)
    ap.add_argument("--top", type=int, default=2)
    args = ap.parse_args()

    from src.agents.chon_cau_thac import ThacChonCau
    from src.agents.nodes.rag_node import _default_embedder

    emb = _default_embedder()
    emb.embed_query("làm nóng")  # nạp E5 trước; ~32 s ấy không thuộc về phép đo
    thac = ThacChonCau(MODEL, emb, pool=args.pool, top=args.top, int8=not args.fp32)

    # Đọc thẳng JSONL, KHÔNG qua `doc_dap_an_khoa`: `DapAnKhoa` chỉ giữ `cum_tra_loi`
    # (cụm khoá ngắn, p50 63 ký tự) và bỏ mất `cau_tra_loi` + `chi_so_cau_tra_loi` —
    # đúng hai trường mà một bộ CHỌN CÂU phải bị chấm theo. Chấm bằng cụm khoá cho
    # precision khập khiễng: tử số 63 ký tự trên mẫu số 240 ký tự nói ra.
    khoa = [
        r
        for r in (json.loads(x) for x in KHOA.read_text(encoding="utf-8").splitlines() if x.strip())
        if r.get("doan_co_cau_tra_loi") and r.get("doan") and r.get("chi_so_cau_tra_loi")
    ]
    print(f"{len(khoa)} ca co dap an trong doan | int8={not args.fp32} pool={args.pool} top={args.top}")

    # Chỉ số trong khoá được gán bằng MỘT bộ tách câu. Nếu bộ tách của `speech_policy`
    # đã đổi thì chỉ số trỏ sai câu, và mọi con số dưới đây vô nghĩa mà vẫn in ra đẹp.
    # Kiểm trước, và nói ra tỉ lệ khớp thay vì giả định nó bằng 100%.
    khop = tong_idx = 0
    for r in khoa:
        cau_r = _cau(r["doan"])
        for j, i in enumerate(r["chi_so_cau_tra_loi"]):
            tong_idx += 1
            if i < len(cau_r) and cau_r[i].strip() == str(r["cau_tra_loi"][j]).strip():
                khop += 1
    print(f"chi so khoa khop bo tach hien tai: {khop}/{tong_idx} = {khop / tong_idx:.0%}")

    hang: list[dict] = []
    for r in khoa:
        cau = _cau(r["doan"])
        that = [i for i in r["chi_so_cau_tra_loi"] if i < len(cau)]
        dap_an = [str(x) for x in r["cau_tra_loi"]]
        luat_idx = xep_hang_theo_lien_quan(cau, r["question"], NGAN_SACH)
        t0 = time.perf_counter()
        thac_idx = thac.select(r["question"], cau)
        do_tre = (time.perf_counter() - t0) * 1000

        noi_luat = " ".join(cau[i] for i in sorted(luat_idx))
        noi_thac = " ".join(cau[i] for i in sorted(thac_idx))
        hang.append(
            {
                "case_id": r["case_id"],
                "question": r["question"],
                "so_cau": len(cau),
                "so_cau_dap_an": len(that),
                "luat_idx": sorted(luat_idx),
                "thac_idx": sorted(thac_idx),
                "that": that,
                "latency_ms": round(do_tre, 1),
                "luat_chi_so": diem_chi_so(luat_idx, that).__dict__,
                "thac_chi_so": diem_chi_so(thac_idx, that).__dict__,
                "luat_ky_tu": diem_ky_tu(noi_luat, dap_an).__dict__,
                "thac_ky_tu": diem_ky_tu(noi_thac, dap_an).__dict__,
                "noi_luat": noi_luat,
                "noi_thac": noi_thac,
            }
        )

    n = len(hang)
    tb = lambda cot, k: sum(r[cot][k] for r in hang) / n  # noqa: E731
    lat = sorted(r["latency_ms"] for r in hang)
    metrics = {
        "n": n,
        "int8": not args.fp32,
        "pool": args.pool,
        "top": args.top,
        "luat_chi_so": {k: round(tb("luat_chi_so", k), 4) for k in ("p", "r", "f1")},
        "thac_chi_so": {k: round(tb("thac_chi_so", k), 4) for k in ("p", "r", "f1")},
        "luat_ky_tu": {k: round(tb("luat_ky_tu", k), 4) for k in ("p", "r", "f1")},
        "thac_ky_tu": {k: round(tb("thac_ky_tu", k), 4) for k in ("p", "r", "f1")},
        "latency_ms_p50": lat[n // 2],
        "latency_ms_p95": lat[int(n * 0.95) - 1],
    }

    for thuoc, ten in (("chi_so", "TAP CHI SO CAU"), ("ky_tu", "PHU KY TU")):
        print(f"\n{ten}")
        print(f"{'':14}{'precision':>11}{'recall':>9}{'F1':>8}")
        for nhan, cot in (("luat S1", f"luat_{thuoc}"), ("thac E5->bge", f"thac_{thuoc}")):
            d = metrics[cot]
            print(f"{nhan:14}{d['p']:>10.1%}{d['r']:>9.1%}{d['f1']:>8.1%}")
        chenh = metrics[f"thac_{thuoc}"]["f1"] - metrics[f"luat_{thuoc}"]["f1"]
        print(f"{'chenh F1':14}{chenh:>+27.1%}")
    print()
    print(f"do tre thac  : p50 {metrics['latency_ms_p50']:.0f} ms | p95 {metrics['latency_ms_p95']:.0f} ms")

    run = RA / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "suite": "chon-cau",
                "commit": _git("rev-parse", "HEAD"),
                "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "dataset": str(KHOA),
                "reranker": str(MODEL),
                "int8": not args.fp32,
                "pool": args.pool,
                "top": args.top,
                "hardware": {"tier": "cpu", "machine": platform.machine(), "python": platform.python_version()},
                "ghi_chu": "Doan lay tu khoa, KHONG qua truy hoi — do rieng tang chon cau.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    with (run / "case_results.jsonl").open("w", encoding="utf-8") as f:
        for r in hang:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nrun: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

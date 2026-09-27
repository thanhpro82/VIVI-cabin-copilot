r"""Bàn đo **ba trục** cho nhánh sổ tay: độ trễ · độ chính xác · độ tự nhiên.

## Vì sao phải là ba trục cùng lúc

Tối ưu một trục mà không nhìn hai trục kia là cách chắc chắn nhất để đi lùi mà vẫn thấy
số đẹp. Ba ví dụ đã xảy ra thật trong dự án này:

- Nói **dài hơn** thì trúng đáp án nhiều hơn (thước cũ thưởng cho dài dòng) — nhưng nghe
  tệ hơn, và đó chính là lời phàn nàn ban đầu.
- Chọn câu **liên quan nhất** thì điểm chính xác lên — nhưng cross-encoder xếp câu CẢNH
  BÁO xuống hạng 5, tức an toàn đi xuống.
- Thêm tầng model thì chất lượng lên — nhưng rerank đoạn tốn 11 giây, tức vô dụng.

Nên bàn cân này in **cả ba trục cạnh nhau cho mọi cấu hình**, và không có con số tổng.
Gộp ba trục thành một điểm là mất đúng thứ ta cần thấy: sự đánh đổi.

## Nó cố ý KHÔNG đo cái gì

Truy hồi. Đoạn lấy thẳng từ `answer_keys.jsonl`, nên mọi cấu hình đều được đưa **đúng
đoạn**. recall@1 hiện là 62% trên bộ `hoi-nhu-tai-xe-v1`; trộn hai tầng vào một con số
thì không biết cải thiện đến từ đâu.

Chạy:
    .\.venv\Scripts\python.exe scripts\ban_do_ba_truc.py
    .\.venv\Scripts\python.exe scripts\ban_do_ba_truc.py --cau-hinh luat thac
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.nodes.speech_policy import (  # noqa: E402
    MAX_SPOKEN_CHARS,
    cau_dan_tu_cau_hoi,
    cau_noi_hoan_chinh,
    chon_cau_de_noi,
)

#: Chỉ dùng khi mẫu trả rỗng (câu hỏi rỗng) — giống hệt đường lui của composer.
CAU_DAN_LUI = "Đây là thông tin tôi tìm được trong sổ tay xe."
from src.rag.giu_y import cham_giu_y, doc_khoa  # noqa: E402
from src.rag.tu_nhien import TEN_KHUYET_TAT, dem_khuyet_tat  # noqa: E402

KHOA_DAP_AN = Path("eval/datasets/manual/v1/answer_keys.jsonl")
RA = Path("eval/results/ba-truc")
MODEL_RERANK = Path("models/reranker/bge-reranker-v2-m3")

#: Câu dẫn **của production**, không phải một chuỗi cố định dựng riêng cho bàn cân.
#:
#: Bản đầu dùng `OUTCOME_MESSAGES["grounded_answer"]` (46 ký tự) trong khi production
#: đã chuyển sang mẫu ghép từ câu hỏi — và mẫu ấy dài hơn: *"Về đèn cảnh báo áp suất
#: lốp trên màn hình, sổ tay hướng dẫn như sau:"* là 68 ký tự. Câu dẫn ăn thẳng vào
#: ngân sách của phần thân, nên bàn cân báo 64% trong khi production chỉ đạt 56%.
#:
#: Một bàn cân đo chuỗi mà production không phát ra thì không đo production.


def _chuan_khoang_trang(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _nap_ca() -> list[dict]:
    """Ca đo, kèm cờ `has_variant_condition` / `is_table` LẤY TỪ CHUNK THẬT.

    Không suy ra cờ bằng luật ở đây: cổng "đoạn có biến thể" của `speech_policy` chạy
    **trước** mọi tầng chọn câu, nên đặt sai cờ là đo một hệ thống khác hệ thống thật.
    """
    from src.agents.nodes.rag_node import _default_retriever

    # Khớp theo văn bản đã **chuẩn hoá khoảng trắng**. Khớp thô trượt 39/39 ca: khoá
    # và chunk cùng nội dung nhưng khác cách xuống dòng, nên mọi cờ rơi về False và
    # bàn cân âm thầm đo một hệ thống KHÔNG có cổng biến thể. Bảy chunk mang cờ ấy.
    chunks = list(_default_retriever()._chunks.values())  # noqa: SLF001
    theo_text = {_chuan_khoang_trang(c.text): c for c in chunks}

    ca: list[dict] = []
    for line in KHOA_DAP_AN.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        doan = (r.get("doan") or "").strip()
        if not r.get("doan_co_cau_tra_loi") or not doan:
            continue
        ch = theo_text.get(_chuan_khoang_trang(doan))
        ca.append(
            {
                "case_id": r["case_id"],
                "question": r["question"],
                "doan": doan,
                "co_chunk_that": ch is not None,
                "evidence": {
                    "text": doan,
                    "has_variant_condition": bool(getattr(ch, "has_variant_condition", False)),
                    "is_table": bool(getattr(ch, "is_table", False)),
                },
            }
        )
    return ca


def _thac(top: int = 2, pool: int | None = None):
    """`pool` mặc định = 3 lần `top`, tối thiểu 6.

    Bản quét đầu để `pool` ở mặc định 4 và đặt `top=4`, tức cross-encoder chấm đúng 4
    câu rồi trả cả 4 — **reranker thành vô tác dụng** mà bảng vẫn in ra một con số
    trông như đã đo nó. Rổ phải rộng hơn hẳn số câu nói ra thì việc xếp lại mới có ý
    nghĩa.
    """
    thuc = pool if pool is not None else max(6, top * 3)

    def dung():
        from src.agents.chon_cau_thac import ThacChonCau
        from src.agents.nodes.rag_node import _default_embedder

        return ThacChonCau(MODEL_RERANK, _default_embedder(), top=top, pool=thuc)

    return dung


@contextmanager
def _doi_tran_cau(n: int | None):
    """Đổi `_TOI_DA_CAU` trong phạm vi một cấu hình.

    Hằng ấy bằng 2 vì đo được "một câu 40,0% trúng, hai câu 55,0%" — nhưng phép đo ấy
    chạy khi mỗi "câu" còn là một khối tiêu đề dán liền đoạn mở bài. Tách theo xuống
    dòng làm câu nhỏ đi hẳn, nên trần 2 câu bỗng thành trần chật: phần thân chỉ dùng
    ~114 trên 193 ký tự ngân sách. Hằng cũ không sai, nó chỉ hết hiệu lực.
    """
    from src.agents.nodes import speech_policy as sp

    if n is None:
        yield
        return
    cu = sp._TOI_DA_CAU
    sp._TOI_DA_CAU = n
    try:
        yield
    finally:
        sp._TOI_DA_CAU = cu


def _e5(top: int = 3):
    """Chỉ tầng E5, không cross-encoder — đối chứng để tách đóng góp của từng tầng."""

    class ChiE5:
        def __init__(self, emb, top):
            self._emb, self._top = emb, top

        def select(self, question, sentences):
            if len(sentences) <= self._top:
                return list(range(len(sentences)))
            vq = self._emb.embed_query(question)
            vs = self._emb.embed_passages(sentences)
            diem = [float(v @ vq) for v in vs]
            return sorted(sorted(range(len(sentences)), key=lambda i: -diem[i])[: self._top])

    def dung():
        from src.agents.nodes.rag_node import _default_embedder

        return ChiE5(_default_embedder(), top)

    return dung


#: Bộ tách câu **nhận biết xuống dòng**.
#:
#: Bộ mặc định `(?<=[.!?])\s+` không tách ở xuống dòng, nên tiêu đề mục dính liền đoạn
#: mở bài thành MỘT "câu" khổng lồ. Khối ấy vừa dài vừa trùng chủ đề với câu hỏi nên
#: luôn thắng mọi bộ xếp hạng, rồi ăn hết ngân sách — đó là lý do 21/39 ca trượt.
#:
#: Đã thử sửa 17/08 và hoàn nguyên vì "trúng đáp án" tụt 72%→36%. Nhưng con số ấy đo
#: bằng thước chỉ hỏi "có CHỨA đáp án không", tức thước THƯỞNG cho nói thừa: khối lớn
#: chứa nhiều chữ hơn nên trúng nhiều hơn. Bàn cân này phạt được nói thừa, nên đây là
#: lần đầu phép sửa ấy được đo bằng một cái thước đo đúng thứ nó ảnh hưởng.
TACH_XUONG_DONG = re.compile(r"(?<=[.!?])\s+|\n+")


@contextmanager
def _doi_bo_tach(pattern):
    """Đổi bộ tách câu trong phạm vi một cấu hình rồi trả lại nguyên trạng."""
    from src.agents.nodes import speech_policy as sp

    cu = sp._SENTENCE_SPLIT
    sp._SENTENCE_SPLIT = pattern
    try:
        yield
    finally:
        sp._SENTENCE_SPLIT = cu


#: Cấu hình → (hàm dựng selector, bộ tách câu, trần số câu). `None` = giữ mặc định.
CAU_HINH: dict[str, tuple] = {
    "luat": (None, None, None),
    "thac": (_thac(2), None, None),
    "luat+tach": (None, TACH_XUONG_DONG, None),
    "thac+tach": (_thac(2), TACH_XUONG_DONG, None),
    "luat+tach+3c": (None, TACH_XUONG_DONG, 3),
    "luat+tach+4c": (None, TACH_XUONG_DONG, 4),
    "luat+tach+5c": (None, TACH_XUONG_DONG, 5),
    "luat+tach+6c": (None, TACH_XUONG_DONG, 6),
    "thac+tach+3c": (_thac(3, 12), TACH_XUONG_DONG, 3),
    "thac+tach+4c": (_thac(4, 12), TACH_XUONG_DONG, 4),
    "thac+tach+5c": (_thac(5, 15), TACH_XUONG_DONG, 5),
    # Chẩn đoán phân biệt: rổ = toàn bộ câu, tức BỎ HẲN tầng E5 thu hẹp.
    # Thác thua luật thì lỗi nằm ở đâu — ở E5 vứt nhầm câu, hay ở chính cross-encoder
    # xếp sai? Cấu hình này tách hai khả năng ấy ra.
    "cross+tach+3c": (_thac(3, 500), TACH_XUONG_DONG, 3),
    # Đối chứng ngược: chỉ E5, không cross-encoder.
    "e5+tach+3c": (_e5(3), TACH_XUONG_DONG, 3),
}


def _noi_mot_ca(ca: dict, selector) -> tuple[str, float]:
    """Dựng đúng chuỗi production đưa vào TTS, và đo thời gian dựng nó.

    Sao nguyên trình tự của `compose_node`: trừ ngân sách câu dẫn TRƯỚC khi chọn, rồi
    ghép `câu dẫn + phần thân`. Lệch trình tự này thì trần ký tự lệch theo, và con số
    "vượt trần" ở trục tự nhiên sẽ sai.
    """
    dan = cau_dan_tu_cau_hoi(ca["question"]) or CAU_DAN_LUI
    ngan_sach = max(60, MAX_SPOKEN_CHARS - len(dan) - 1)
    t0 = time.perf_counter()
    ke_hoach = chon_cau_de_noi(ca["evidence"], ca["question"], max_chars=ngan_sach, selector=selector)
    than = cau_noi_hoan_chinh(ke_hoach, max_chars=ngan_sach)
    do_tre = (time.perf_counter() - t0) * 1000
    noi = f"{dan} {than}".strip() if than else dan
    return noi, do_tre


def _chay(ten: str, cau_hinh: tuple, ca_list: list[dict], khoa: dict) -> dict:
    dung_selector, bo_tach, tran_cau = cau_hinh
    selector = dung_selector() if dung_selector else None
    if selector is not None:  # nạp trọng số trước; thời gian nạp không thuộc phép đo
        selector.select("làm nóng", ["Câu một.", "Câu hai.", "Câu ba."])

    hang: list[dict] = []
    ctx_tach = _doi_bo_tach(bo_tach) if bo_tach is not None else nullcontext()
    with ctx_tach, _doi_tran_cau(tran_cau):
        for ca in ca_list:
            noi, ms = _noi_mot_ca(ca, selector)
            gy = cham_giu_y(noi, khoa.get(ca["case_id"], []))
            tn = dem_khuyet_tat(noi)
            hang.append(
                {
                    "case_id": ca["case_id"],
                    "question": ca["question"],
                    "noi": noi,
                    "latency_ms": round(ms, 1),
                    "giu_y_dat": gy.dat,
                    "giu_y_diem": round(gy.diem, 4),
                    "giu_y_thieu": gy.thieu,
                    "tu_nhien_sach": tn.sach,
                    "khuyet_tat": tn.khuyet_tat,
                }
            )

    n = len(hang)
    lat = sorted(r["latency_ms"] for r in hang)
    hist: dict[str, int] = {}
    for r in hang:
        for k in r["khuyet_tat"]:
            hist[k] = hist.get(k, 0) + 1
    return {
        "cau_hinh": ten,
        "n": n,
        "do_tre_p50_ms": lat[n // 2],
        "do_tre_p95_ms": lat[min(n - 1, int(n * 0.95))],
        "chinh_xac_dat": round(sum(r["giu_y_dat"] for r in hang) / n, 4),
        "chinh_xac_diem": round(statistics.fmean(r["giu_y_diem"] for r in hang), 4),
        "tu_nhien_sach": round(sum(r["tu_nhien_sach"] for r in hang) / n, 4),
        "khuyet_tat": dict(sorted(hist.items(), key=lambda x: -x[1])),
        "_hang": hang,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cau-hinh", nargs="*", default=list(CAU_HINH), choices=list(CAU_HINH))
    args = ap.parse_args()

    from src.agents.nodes.rag_node import _default_embedder

    _default_embedder().embed_query("làm nóng")  # ~32 s nạp E5, không thuộc phép đo

    ca_list = _nap_ca()
    khoa = doc_khoa()
    thieu_chunk = [c["case_id"] for c in ca_list if not c["co_chunk_that"]]
    print(f"{len(ca_list)} ca | khoá: {len(khoa)} ca")
    if thieu_chunk:
        print(f"  KHONG khop chunk that (co cu mac dinh False): {len(thieu_chunk)} ca {thieu_chunk[:5]}")

    ket: list[dict] = []
    for ten in args.cau_hinh:
        print(f"\n>>> {ten}")
        ket.append(_chay(ten, CAU_HINH[ten], ca_list, khoa))

    print(f"\n{'cau hinh':16}{'p50 ms':>9}{'p95 ms':>9}{'chinh xac':>11}{'diem':>8}{'tu nhien':>10}")
    for k in ket:
        print(
            f"{k['cau_hinh']:16}{k['do_tre_p50_ms']:>9.0f}{k['do_tre_p95_ms']:>9.0f}"
            f"{k['chinh_xac_dat']:>10.0%}{k['chinh_xac_diem']:>8.3f}{k['tu_nhien_sach']:>10.0%}"
        )
    print("\nkhuyet tat (so ca):")
    for k in ket:
        chi_tiet = ", ".join(f"{TEN_KHUYET_TAT.get(a, a)}={b}" for a, b in k["khuyet_tat"].items()) or "khong"
        print(f"  {k['cau_hinh']:14} {chi_tiet}")

    run = RA / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "suite": "ba-truc",
                "commit": _git("rev-parse", "HEAD"),
                "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "dataset": str(KHOA_DAP_AN),
                "khoa_giu_y": "eval/datasets/manual/v1/y_phai_giu.jsonl",
                "cau_hinh": args.cau_hinh,
                "hardware": {"tier": "cpu", "machine": platform.machine(), "python": platform.python_version()},
                "ghi_chu": "Doan lay tu khoa, KHONG qua truy hoi — do rieng tang noi.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run / "metrics.json").write_text(
        json.dumps([{k: v for k, v in x.items() if k != "_hang"} for x in ket], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (run / "case_results.jsonl").open("w", encoding="utf-8") as f:
        for k in ket:
            for r in k["_hang"]:
                f.write(json.dumps({"cau_hinh": k["cau_hinh"], **r}, ensure_ascii=False) + "\n")
    print(f"\nrun: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

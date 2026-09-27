r"""Bàn cân cho tầng **tóm tắt** — ba trục cũ, cộng tỷ lệ bác tách theo từng cổng.

## Giả thuyết đang kiểm

Nén **mua thêm ngân sách**. Hôm nay trần 240 ký tự chỉ chở nổi ~3 câu nguyên văn; nếu
nén 6 câu vừa cùng trần ấy thì tài xế nhận gấp đôi nội dung trong cùng thời lượng nghe.

Đây mới là chỗ tóm tắt đáng giá. Nhìn các câu còn kém sau vòng 18/08 thì chúng hỏng ở
khâu **chọn**, không phải khâu **diễn đạt** — nên tóm tắt cùng số câu (`tom-3c`) chỉ
làm mượt chữ, còn tóm tắt nhiều câu hơn (`tom-6c`) mới đổi được điểm.

`tom-3c` có mặt như **đối chứng**: nó tách phần lợi do *nén chữ* khỏi phần lợi do
*chở thêm câu*. Thiếu nó thì một con số đẹp ở `tom-6c` không nói được nhờ đâu.

## Ba trục và một cột thứ tư

Tỷ lệ bác in **tách theo từng cổng**. Đọc tỷ lệ sai mà bỏ tỷ lệ bác là tự lừa: một bộ
cổng bác 90% cho "sai = 0%" rất đẹp trong khi chẳng bao giờ dùng model — đúng cái bẫy
SPIKE-004 đã chỉ ra.

Chạy (cần llama-server ở cổng 8093):
    .\.venv\Scripts\python.exe scripts\do_tom_tat.py
"""

from __future__ import annotations

import json
import platform
import re
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.nodes.speech_policy import (  # noqa: E402
    MAX_SPOKEN_CHARS,
    _cau,
    cau_dan_tu_cau_hoi,
    cau_noi_hoan_chinh,
    chon_cau_de_noi,
)
from src.agents.tom_tat import QwenTomTat  # noqa: E402
from src.rag.giu_y import cham_giu_y, doc_khoa  # noqa: E402
from src.rag.tu_nhien import dem_khuyet_tat  # noqa: E402

KHOA_DAP_AN = Path("eval/datasets/manual/v1/answer_keys.jsonl")
RA = Path("eval/results/tom-tat")
ENDPOINT = "http://127.0.0.1:8093"


def _chuan(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


@contextmanager
def _tran_cau(n: int):
    from src.agents.nodes import speech_policy as sp

    cu = sp._TOI_DA_CAU
    sp._TOI_DA_CAU = n
    try:
        yield
    finally:
        sp._TOI_DA_CAU = cu


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _nap_ca() -> list[dict]:
    from src.agents.nodes.rag_node import _default_retriever

    theo_text = {_chuan(c.text): c for c in _default_retriever()._chunks.values()}  # noqa: SLF001
    ca = []
    for line in KHOA_DAP_AN.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        doan = (r.get("doan") or "").strip()
        if not r.get("doan_co_cau_tra_loi") or not doan:
            continue
        ch = theo_text.get(_chuan(doan))
        ca.append(
            {
                "case_id": r["case_id"],
                "question": r["question"],
                "evidence": {
                    "text": doan,
                    "has_variant_condition": bool(getattr(ch, "has_variant_condition", False)),
                    "is_table": bool(getattr(ch, "is_table", False)),
                },
            }
        )
    return ca


def _chay(ten: str, tran: int, tom_tat, ca_list: list[dict], khoa: dict, rong: int = 1) -> dict:
    hang = []
    with _tran_cau(tran):
        for ca in ca_list:
            dan = cau_dan_tu_cau_hoi(ca["question"])
            ngan_sach = max(60, MAX_SPOKEN_CHARS - len(dan) - 1)
            t0 = time.perf_counter()
            # `rong > 1`: cho bộ chọn lấy RỘNG hơn trần nói, rồi để tầng nén ép xuống.
            # Đây mới là phép kiểm đúng giả thuyết "nén mua thêm ngân sách". Bản đầu
            # chỉ đổi `_TOI_DA_CAU` và không đổi gì cả: bộ chọn vốn đã lọc theo trần ký
            # tự NGAY TRONG LÚC chọn, nên nó không bao giờ đưa ra quá số câu vừa trần —
            # `tom-6c` ra kết quả giống hệt `tom-3c` tới từng con số.
            ke_hoach = chon_cau_de_noi(ca["evidence"], ca["question"], max_chars=ngan_sach * rong)
            than = cau_noi_hoan_chinh(ke_hoach, max_chars=ngan_sach * rong)
            cong = ""
            if tom_tat is not None and than:
                # Nén CHÍNH phần đã chọn, không nén cả đoạn: cho model nhìn cả đoạn là
                # giao lại khâu chọn cho nó, mà khâu ấy đo được là luật làm tốt hơn.
                nguon = " ".join(_cau(ke_hoach.spoken)) or ke_hoach.spoken
                tom, cong = tom_tat.tom(nguon, ca["question"])
                if tom:
                    than = tom
            if len(than) > ngan_sach:  # nén không đủ thì vẫn phải tôn trọng trần nói
                than = than[:ngan_sach].rsplit(" ", 1)[0].rstrip(",;:") + "."
            ms = (time.perf_counter() - t0) * 1000
            noi = f"{dan} {than}".strip() if than else dan
            gy = cham_giu_y(noi, khoa.get(ca["case_id"], []))
            tn = dem_khuyet_tat(noi)
            hang.append(
                {
                    "case_id": ca["case_id"],
                    "question": ca["question"],
                    "noi": noi,
                    "so_ky_tu": len(noi),
                    "latency_ms": round(ms, 1),
                    "cong_bac": cong,
                    "giu_y_dat": gy.dat,
                    "giu_y_diem": round(gy.diem, 4),
                    "tu_nhien_sach": tn.sach,
                    "khuyet_tat": tn.khuyet_tat,
                }
            )

    n = len(hang)
    lat = sorted(r["latency_ms"] for r in hang)
    bac: dict[str, int] = {}
    for r in hang:
        if r["cong_bac"]:
            bac[r["cong_bac"]] = bac.get(r["cong_bac"], 0) + 1
    return {
        "cau_hinh": ten,
        "n": n,
        "tran_cau": tran,
        "p50_ms": lat[n // 2],
        "p95_ms": lat[min(n - 1, int(n * 0.95))],
        "chinh_xac_dat": round(sum(r["giu_y_dat"] for r in hang) / n, 4),
        "chinh_xac_diem": round(statistics.fmean(r["giu_y_diem"] for r in hang), 4),
        "tu_nhien_sach": round(sum(r["tu_nhien_sach"] for r in hang) / n, 4),
        "ky_tu_tb": round(statistics.fmean(r["so_ky_tu"] for r in hang), 1),
        "ty_le_bac": round(sum(1 for r in hang if r["cong_bac"]) / n, 4),
        "bac_theo_cong": dict(sorted(bac.items(), key=lambda x: -x[1])),
        "_hang": hang,
    }


def main() -> int:
    from src.agents.nodes.rag_node import _default_embedder

    _default_embedder().embed_query("làm nóng")
    ca_list, khoa = _nap_ca(), doc_khoa()
    print(f"{len(ca_list)} ca\n")

    # Quét dung sai: mỗi mức `k` cho phép tối đa `k` từ nội dung không khớp nguồn.
    # Thứ tự KHÔNG được nới ở bất kỳ mức nào — ca đảo bước vẫn bị bác ở k=3.
    ket = [_chay("trich (moc)", 3, None, ca_list, khoa)]
    # Quét SÀN GIỮ LẠI ở dung sai k=1 (mức Qwen3-4B tuân thủ tốt nhất mà vẫn nhận
    # được từ đồng nghĩa). Sàn 0.0 = không có cổng này, để thấy nó đóng góp bao nhiêu.
    # Nén MỘT lượt. Cơ chế thử lại đã bỏ: phần lớn số ca nó chữa được đến từ việc prompt
    # nói ngược cổng (bản trước cho phép thêm "rồi, nếu, để, sau đó" — đúng bốn chữ mà
    # `chen_tu_quan_he` cấm), nên tỷ lệ bác một phần là do model LÀM THEO chỉ dẫn của ta.
    # Sửa prompt kéo bác 62% → 15% trong một lượt, hơn hẳn 11 điểm mà lượt hai mua được.
    #
    # Sàn giữ lại vẫn quét ở đây làm BẰNG CHỨNG cho đánh đổi, dù mặc định sản phẩm là
    # `san_giu=0.0`. Sàn thô bác một bản tóm vì NGẮN, khác cổng an toàn bác vì SAI: đo
    # 19/08 cho thấy sàn 0,85 gây 20 trên 24 ca bị bác, còn bốn cổng an toàn cộng lại 9.
    for ten, k, san in [
        ("khong san", 1, 0.0),
        ("san 0.70", 1, 0.70),
        ("san 0.80", 1, 0.80),
        ("san 0.85", 1, 0.85),
        ("san 0.90", 1, 0.90),
    ]:
        ket.append(
            _chay(
                ten,
                3,
                QwenTomTat(ENDPOINT, timeout_s=60, dung_sai=k, san_giu=san, top_mang_tin=0),
                ca_list,
                khoa,
            )
        )

    print(f"{'cau hinh':18}{'p50 ms':>9}{'chinh xac':>11}{'diem':>8}{'tu nhien':>10}{'ky tu':>8}{'bac':>7}")
    for k in ket:
        print(
            f"{k['cau_hinh']:18}{k['p50_ms']:>9.0f}{k['chinh_xac_dat']:>10.0%}"
            f"{k['chinh_xac_diem']:>8.3f}{k['tu_nhien_sach']:>10.0%}{k['ky_tu_tb']:>8.0f}{k['ty_le_bac']:>7.0%}"
        )
    print("\nbac theo cong:")
    for k in ket:
        print(f"  {k['cau_hinh']:16} {k['bac_theo_cong'] or 'khong bac ca nao'}")

    run = RA / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "suite": "tom-tat",
                "commit": _git("rev-parse", "HEAD"),
                "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "endpoint": ENDPOINT,
                "hardware": {"tier": "cpu", "ngoai_le": "llama-server co the chay tren dGPU — xem log server"},
                "machine": platform.machine(),
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

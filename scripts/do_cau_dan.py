r"""Bàn cân cho vai trò **câu dẫn** — trên CPU, nhiều loại mô hình.

## Câu dẫn là bề mặt duy nhất model được viết chữ tự do

Và nó tự do **vì bị cấm mang dữ kiện**. Đo 19/08 cho thấy điều cấm ấy đang không được
thi hành, và cả hai model đều vi phạm:

| model | câu hỏi | câu dẫn sinh ra |
|---|---|---|
| Qwen 0.5B | *"Độ sâu gai lốp tối thiểu là bao nhiêu?"* | *"Độ sâu gai lốp tối thiểu là **10mm**."* |
| Qwen 3B | *"Nước rửa kính đổ ở đâu"* | *"Nước rửa kính nằm ở **compartment sau táp-lô**."* |

Đáp án thật của ca đầu là **2 mm**. Con số 10mm không có ở đâu trong sổ tay — đúng lớp
lỗi ADR-015 đo được 4/40, và đúng ca RAG-130 mà SPIKE-004 gọi là "ca đáng sợ nhất".

## Ba thứ bàn cân này đo

- **độ trễ** — p50/p95, tất cả trên CPU trừ dòng ghi rõ dGPU;
- **tỷ lệ có số** — tín hiệu CỨNG, không cần ai phán xét: câu dẫn chỉ nhìn thấy câu hỏi
  và tên mục, nên mọi con số nó nói ra đều không có nguồn;
- **từ lạ mỗi câu** — tín hiệu MỀM: từ nội dung câu dẫn tự thêm. Đây là *áp lực*, không
  phải phán quyết; ca nguy hiểm nhìn ở cột ví dụ chứ không ở số trung bình.

## Hai thứ bàn cân này KHÔNG đo, và vì sao

**Không** chấm câu dẫn bằng bộ dò khuyết tật `tu_nhien`. Bản đầu có, và nó báo mẫu đạt
**0% sạch** — vì mẫu kết thúc bằng dấu hai chấm nên bị gọi là "chuỗi đứt giữa chừng".
Sai đơn vị phân tích: câu dẫn là một **mảnh**, nó phải đứt để nối vào phần thân. Trục
tự nhiên đo trên chuỗi hoàn chỉnh, ở `scripts/ban_do_ba_truc.py`.

**Không** gọi từ khung là bịa. Bản đầu đếm cả `hãy`, `này`, `mô tả` và đẩy tỷ lệ của
Qwen 3B lên 64% — một con số vừa đáng sợ vừa vô nghĩa.

Chạy:
    .\.venv\Scripts\python.exe scripts\do_cau_dan.py
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.nodes.compose import lam_sach_cau_dan  # noqa: E402
from src.agents.nodes.speech_policy import _NUMBER_WITH_UNIT  # noqa: E402
from src.agents.slm import LEAD_IN_SYSTEM, chatml  # noqa: E402
from src.rag.textnorm import STOPWORDS, _tokens  # noqa: E402

RA = Path("eval/results/cau-dan")

#: Câu hỏi lấy từ `answer_keys.jsonl` để bàn cân này so được với bàn cân ba trục.
KHOA = Path("eval/datasets/manual/v1/answer_keys.jsonl")

#: Từ khung mà câu dẫn được phép dùng dù câu hỏi không có. Tập ĐÓNG, và cố ý nhỏ:
#: mỗi từ thêm vào đây là một chỗ model được nói thứ không ai kiểm.
_TU_KHUNG = frozenset(
    _tokens(
        "sổ tay xe hướng dẫn như sau đây là thông tin tôi tìm được trong quy định "
        "chỉ rõ ghi về việc theo nội dung phần mục trả lời câu hỏi của bạn"
    )
)


def co_so(cau_dan: str) -> bool:
    """Tín hiệu **cứng**: câu dẫn chứa chữ số.

    Không cần ai phán xét. Một câu dẫn có số là một câu dẫn khẳng định đại lượng, mà
    nó không đọc đoạn nào để biết đại lượng ấy — nó chỉ thấy câu hỏi và tên mục. Đây
    đúng ca RAG-130 mà SPIKE-004 gọi là "ca đáng sợ nhất", và Qwen 0.5B tái diễn nó
    ngay ở lần đo đầu: *"Độ sâu gai lốp tối thiểu là 10mm"* (đáp án thật: 2 mm).
    """
    return bool(re.search(r"\d", cau_dan)) or bool(_NUMBER_WITH_UNIT.search(cau_dan))


def tu_ngoai_cau_hoi(cau_dan: str, cau_hoi: str) -> list[str]:
    """Tín hiệu **mềm**: từ nội dung câu dẫn tự thêm, không có trong câu hỏi.

    Đây là **áp lực**, không phải phán quyết. Bản đầu tôi gọi cột này là "bịa" và nó
    đếm cả `hãy`, `này`, `mô tả` — từ khung, không phải khẳng định về chiếc xe. Một
    thước gọi từ khung là bịa thì thổi phồng con số và làm mất khả năng phân biệt ca
    vô hại với ca nguy hiểm.

    Cách đọc đúng: số càng lớn thì câu dẫn càng nói nhiều thứ không ai kiểm được. Ca
    nguy hiểm nhìn thấy được ở cột ví dụ, không ở con số trung bình.
    """
    cho_phep = set(_tokens(cau_hoi)) | _TU_KHUNG | STOPWORDS
    return [t for t in _tokens(cau_dan) if t not in cho_phep and len(t) > 1]


# --- Các cách sinh câu dẫn ----------------------------------------------------

_BO_DAU_HOI = re.compile(r"\s*[?？]+\s*$")
_MO_DAU = re.compile(
    r"^\s*(?:cho\s+(?:tôi|mình)\s+hỏi|làm\s+sao\s+để|làm\s+thế\s+nào\s+để|cách\s+|khi\s+nào\s+|"
    r"tại\s+sao\s+|có\s+thể\s+|xin\s+hỏi\s+)",
    re.IGNORECASE,
)
KHUNG = "sổ tay hướng dẫn như sau:"


def cau_dan_mau(cau_hoi: str, port: int | None = None) -> tuple[str, float]:
    """Ghép từ **chính chữ của tài xế** — 0 ms, và về cấu tạo không bịa được.

    Nhìn đầu ra của Qwen 3B thì 4 trên 6 câu đã đúng dạng này rồi: `"<câu hỏi>, sổ tay
    xe hướng dẫn như sau:"`. Tức ta đang trả 421 ms trên dGPU (2316 ms trên CPU) cho
    một phép nối chuỗi — và đổi lại nhận về rủi ro model bịa số.
    """
    t0 = time.perf_counter()
    lo = _BO_DAU_HOI.sub("", (cau_hoi or "").strip())
    lo = _MO_DAU.sub("", lo).strip()
    ra = f"Về {lo[0].lower() + lo[1:]}, {KHUNG}" if lo else f"Đây là thông tin trong {KHUNG}"
    return ra, (time.perf_counter() - t0) * 1000


def _goi_slm(cau_hoi: str, port: int) -> tuple[str, float]:
    body = json.dumps(
        {
            "prompt": chatml(LEAD_IN_SYSTEM, f"Câu hỏi: {cau_hoi}\nMục sổ tay: Sổ tay xe"),
            "temperature": 0,
            "n_predict": 40,
            "cache_prompt": True,
            "stop": ["<|im_end|>", "<|im_start|>"],
        }
    ).encode()
    r = urllib.request.Request(
        f"http://127.0.0.1:{port}/completion", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(r, timeout=300) as x:
        c = json.loads(x.read()).get("content", "")
    return lam_sach_cau_dan(str(c).strip()), (time.perf_counter() - t0) * 1000


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


CACH: dict[str, tuple] = {
    "mau (0 ms)": (cau_dan_mau, None),
    "qwen0.5b cpu": (_goi_slm, 8094),
    "qwen3b dGPU": (_goi_slm, 8093),
}


def main() -> int:
    hoi = [
        json.loads(x)["question"]
        for x in KHOA.read_text(encoding="utf-8").splitlines()
        if x.strip() and json.loads(x).get("doan_co_cau_tra_loi")
    ]
    print(f"{len(hoi)} câu hỏi\n")

    ket = []
    for ten, (fn, port) in CACH.items():
        hang = []
        for q in hoi:
            try:
                cd, ms = fn(q, port)
            except Exception as e:  # llama-server chưa bật là trạng thái bình thường
                print(f"  {ten}: bỏ qua ({type(e).__name__})")
                hang = []
                break
            la = tu_ngoai_cau_hoi(cd, q)
            hang.append(
                {
                    "question": q,
                    "cau_dan": cd,
                    "latency_ms": round(ms, 1),
                    "tu_ngoai_cau_hoi": la,
                    "co_so": co_so(cd),
                }
            )
        if not hang:
            continue
        n = len(hang)
        lat = sorted(r["latency_ms"] for r in hang)
        ket.append(
            {
                "cach": ten,
                "n": n,
                "p50_ms": lat[n // 2],
                "p95_ms": lat[min(n - 1, int(n * 0.95))],
                "ty_le_co_so": round(sum(r["co_so"] for r in hang) / n, 4),
                "tu_la_trung_binh": round(sum(len(r["tu_ngoai_cau_hoi"]) for r in hang) / n, 2),
                "_hang": hang,
            }
        )

    print(f"{'cách sinh câu dẫn':20}{'p50 ms':>9}{'p95 ms':>9}{'có số':>9}{'từ lạ/câu':>11}")
    for k in ket:
        print(
            f"{k['cach']:20}{k['p50_ms']:>9.0f}{k['p95_ms']:>9.0f}"
            f"{k['ty_le_co_so']:>8.0%}{k['tu_la_trung_binh']:>11.2f}"
        )

    for k in ket:
        xau = sorted(k["_hang"], key=lambda r: (not r["co_so"], -len(r["tu_ngoai_cau_hoi"])))[:3]
        if xau and (xau[0]["co_so"] or xau[0]["tu_ngoai_cau_hoi"]):
            print(f"\n{k['cach']} — ba câu dẫn nói nhiều nhất thứ câu hỏi không có:")
            for r in xau:
                co = "   [CÓ SỐ]" if r["co_so"] else ""
                print(f"   hỏi : {r['question'][:62]}")
                print(f"   dẫn : {r['cau_dan'][:78]}{co}")
                print(f"   lạ  : {r['tu_ngoai_cau_hoi'][:8]}")

    run = RA / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "suite": "cau-dan",
                "commit": _git("rev-parse", "HEAD"),
                "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "hardware": {"tier": "cpu", "ngoai_le": "qwen3b chay tren Radeon RX 5500M qua Vulkan"},
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
                f.write(json.dumps({"cach": k["cach"], **r}, ensure_ascii=False) + "\n")
    print(f"\nrun: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

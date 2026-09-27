"""Đo llama-server ở **đúng hình dạng của S2**, không phải hình dạng planner.

Bậc C của SPIKE-003 nhồi prompt ngắn rồi nhả 160 token — bài lập kế hoạch. S2 ngược
hẳn: nhồi cả danh sách câu của một đoạn sổ tay rồi chỉ nhả vài **chỉ số** câu. Ước
từ bảng bậc C sang S2 là ước xuyên qua một hình dạng khác hẳn, nên script này thay
ước bằng đo.

Lần chạy đầu (13/08, run `20260813T162737.967452Z`) đã bác luôn giả định của chính
nó: tôi viết ở đây rằng "S2 sống bằng prefill", nhưng phân rã cho **prefill 248 ms
(37%) / decode 419 ms (63%)**. Lý do là đoạn sổ tay ngắn hơn dự đoán — p50 chỉ 325
token, max 899, không phải 600–1.000. Chiều quyết định vẫn là decode.

Prompt dựng từ **index thật**, không phải văn bản bịa: mỗi case lấy top-1 evidence
như production, tách câu bằng đúng `_SENTENCE_SPLIT` của `speech_policy`, và ghép
bằng đúng `dung_prompt_chon_cau` của `src/agents/slm.py`.

Prompt dựng từ **index thật**, không phải văn bản bịa: mỗi case lấy top-1 evidence
như production, tách câu bằng đúng `_SENTENCE_SPLIT` của `speech_policy`.

    .\\.venv\\Scripts\\python.exe scripts\\spike3_s2_shape.py cpu6

Số ở đây mang nhãn PROBE-NOT-EVIDENCE: nó đo **độ trễ**, không chấm chất lượng chọn
câu. Chất lượng là việc của Task 9 và phải chấm tay như baseline S1.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from spike3_bench import run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.nodes.speech_policy import _SENTENCE_SPLIT  # noqa: E402
from src.agents.slm import SENTENCE_SELECT_SCHEMA, dung_prompt_chon_cau  # noqa: E402
from src.rag.cli import DEFAULT_CASES, DEFAULT_INDEX  # noqa: E402
from src.rag.embed import E5Embedder  # noqa: E402
from src.rag.evaluate import load_cases  # noqa: E402
from src.rag.retrieve import RetrievalConfig, load_retriever  # noqa: E402

MODEL = ROOT / "experiments" / "offline_poc" / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"

#: Prompt và schema lấy **thẳng từ production** (`src/agents/slm.py`), không chép lại.
#:
#: Chép lại thì hai bên trôi khỏi nhau lúc nào không biết, và con số đo được sẽ nói về
#: một prompt không ai chạy. Đầu ra bị chặn thành mảng chỉ số chứ không phải văn xuôi —
#: nửa còn lại của lý do S2 khác phương án B mà ADR-015 đã bác.


def _cau(text: str) -> list[str]:
    return [c.strip() for c in _SENTENCE_SPLIT.split(text) if c.strip()]


def dung_prompts() -> list[dict]:
    """Một prompt cho mỗi case `supported`, dựng từ evidence thật."""
    retriever = load_retriever(DEFAULT_INDEX, RetrievalConfig())
    embedder = E5Embedder()
    prompts = []
    for case in load_cases(DEFAULT_CASES):
        if not case.supported:
            continue
        evidence = retriever.search(case.input_text, embedder)
        if not evidence:
            continue
        cau_list = _cau(evidence[0].text)
        prompts.append(
            {
                "case_id": case.case_id,
                "prompt": dung_prompt_chon_cau(case.input_text, cau_list),
                "n_sentences": len(cau_list),
            }
        )
    return prompts


def _hop_le(text: str, n_cau: int) -> bool:
    """Đầu ra có dùng được không: parse được **và** mọi chỉ số nằm trong đoạn.

    Grammar ép được *kiểu* nhưng không ép được *khoảng*: `{"indices":[99]}` vẫn hợp
    schema. Cổng kiểm chứng của Task 9 chính là chỗ này, nên đo luôn từ bây giờ —
    nếu tỷ lệ chỉ số ngoài khoảng cao thì S2 tốn thêm một vòng rơi về luật, và độ trễ
    thật là độ trễ **kèm** vòng đó.
    """
    try:
        out = json.loads(text)
    except ValueError:
        return False
    idx = out.get("indices")
    if not isinstance(idx, list) or not idx:
        return False
    return all(isinstance(i, int) and 0 <= i < n_cau for i in idx)


if __name__ == "__main__":
    backend = sys.argv[1] if len(sys.argv) > 1 else "cpu6"
    prompts = dung_prompts()
    print(f"{len(prompts)} prompt hinh dang S2; so cau/doan: "
          f"min={min(p['n_sentences'] for p in prompts)} "
          f"max={max(p['n_sentences'] for p in prompts)}")

    # n_predict 32: dau ra la mang vai chi so. De 160 nhu bac C la do mot bai khac.
    run_dir = run(prompts, tag="s2-shape", model=MODEL, backend=backend, schema=SENTENCE_SELECT_SCHEMA, n_predict=32)

    records = [json.loads(x) for x in (run_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    prompt_n = sorted(r["prompt_n"] for r in records if r.get("prompt_n"))
    ra_n = sorted(r["predicted_n"] for r in records if r.get("predicted_n"))
    so_cau = {p["case_id"]: p["n_sentences"] for p in prompts}
    hong = [r["case_id"] for r in records if not _hop_le(r["text"], so_cau[r["case_id"]])]

    them = {
        "prompt_tokens_p50": prompt_n[len(prompt_n) // 2],
        "prompt_tokens_max": prompt_n[-1],
        "output_tokens_p50": ra_n[len(ra_n) // 2],
        "chi_so_ngoai_khoang_hoac_hong": hong,
        "label": "PROBE-NOT-EVIDENCE",
    }
    (run_dir / "s2_shape.json").write_text(json.dumps(them, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(them, ensure_ascii=False, indent=1))
    print(f"prompt token trung binh {statistics.mean(prompt_n):.0f} — day la chieu S2 an, khong phai decode")

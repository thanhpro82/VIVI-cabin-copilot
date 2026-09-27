"""Bậc C: kind/tool accuracy + latency trên bộ dò. Số mang nhãn probe-not-evidence."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from spike3_bench import run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "eval" / "datasets" / "probe" / "v1" / "cases.jsonl"


def score(run_dir: Path, cases: list[dict]) -> dict:
    records = [json.loads(line) for line in (run_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    by_id = {r["case_id"]: r for r in records}
    n = kind_ok = tool_ok = parse_fail = plan_n = 0
    misses = []
    for c in cases:
        n += 1
        rec = by_id[c["case_id"]]
        try:
            out = json.loads(rec["text"])
        except ValueError:
            parse_fail += 1
            misses.append({"case_id": c["case_id"], "why": "parse_fail", "text": rec["text"][:120]})
            continue
        accept = c["expected"].get("accept_kinds") or [c["expected"]["kind"]]
        if out.get("kind") in accept:
            kind_ok += 1
        else:
            misses.append({"case_id": c["case_id"], "why": f"kind={out.get('kind')} muon={accept}"})
        if c["expected"].get("kind") == "plan":
            plan_n += 1
            steps = out.get("steps") or [{}]
            got_tool = steps[0].get("tool")
            if out.get("kind") == "plan" and got_tool == c["expected"]["tool"]:
                tool_ok += 1
            else:
                misses.append({"case_id": c["case_id"], "why": f"tool={got_tool} muon={c['expected']['tool']}"})
    return {
        "n": n, "parse_fail": parse_fail,
        "kind_accuracy": round(kind_ok / n, 3) if n else None,
        "tool_accuracy_on_plan": round(tool_ok / plan_n, 3) if plan_n else None,
        "plan_n": plan_n,
        "misses": misses,
        "label": "PROBE-NOT-EVIDENCE",
    }


if __name__ == "__main__":
    model, backend = sys.argv[1], sys.argv[2]
    prefix = (ROOT / "scripts" / "spike3_prompt.txt").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "scripts" / "spike3_schema.json").read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    prompts = [{"case_id": c["case_id"], "prompt": prefix + c["input_text"] + "\nJSON:"} for c in cases]
    run_dir = run(prompts, tag="rungC-quality", model=Path(model), backend=backend,
                  schema=schema, n_predict=160)
    result = score(run_dir, cases)
    (run_dir / "quality.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "misses"}, ensure_ascii=False, indent=1))
    for m in result["misses"]:
        print("  MISS", m)

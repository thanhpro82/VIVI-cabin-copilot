import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else max(
    Path("/opt/vivi/eval/results/spike-003").glob("2*Z"), key=lambda p: p.name)

recs = [json.loads(l) for l in (run_dir / "records.jsonl").open(encoding="utf-8")]
print(f"run: {run_dir.name}   ({len(recs)} case)\n")
print(f"{'case':>8} {'prompt_n':>9} {'prompt_ms':>10} {'pred_n':>7} {'pred_ms':>9} {'total_ms':>9}")
print("-" * 58)
totals = []
for r in recs:
    pm = r["prompt_ms"] or 0
    dm = r["predicted_ms"] or 0
    totals.append(pm + dm)
    print(f"{r['case_id']:>8} {r['prompt_n']:>9} {pm:>10.0f} {r['predicted_n']:>7} {dm:>9.0f} {pm+dm:>9.0f}")

s = sorted(totals)
print("-" * 58)
print(f"min {s[0]:>9.0f}   p50 {s[len(s)//2]:>9.0f}   max {s[-1]:>9.0f}")
print(f"\nCase dau (warm-0) ton {totals[0]:.0f} ms; case dat nhi ton {sorted(totals)[-2]:.0f} ms")
print(f"Chenh lech: {totals[0] / sorted(totals)[-2]:.1f}x")

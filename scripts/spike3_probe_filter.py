"""Chỉ giữ câu mà DeterministicControlRouter thật trả `not_control`.

Câu router bắt được không được nằm trong bộ dò: chúng không bao giờ tới SLM
trong production, giữ lại chỉ làm đẹp số một cách vô nghĩa.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.router import DeterministicControlRouter  # noqa: E402

router = DeterministicControlRouter()
kept, dropped = [], []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    case = json.loads(line)
    d = router.route(case["input_text"])
    (kept if d.disposition == "not_control" else dropped).append((case, d.disposition))

for case, _ in kept:
    print(json.dumps(case, ensure_ascii=False))
print(f"# giữ {len(kept)}, loại {len(dropped)}", file=sys.stderr)
for case, disp in dropped:
    print(f"#   loại [{disp}] {case['input_text']}", file=sys.stderr)

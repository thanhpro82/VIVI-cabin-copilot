# SPIKE-003 — Đo khả thi SLM trên máy demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trả lời bằng số đo — không bằng ước lượng — bốn câu: GPU sẵn có chạy được không; grammar + prompt cache đổi độ trễ bao nhiêu; model chọn đúng tool được bao nhiêu trên bộ dò; RAM có chịu nổi khi chạy cùng STT không. Đầu ra là báo cáo + dự thảo ADR-016 + quyết định go/no-go cho Phase 2 (tích hợp vào `src/`).

**Architecture:** Toàn bộ spike nằm ngoài `src/` — chỉ script trong `scripts/`, asset trong `eval/`, binary pin trong `tools/`. Không sửa dòng nào của agent graph. Bằng chứng ghi `eval/results/spike-003/<UTC-run-id>/`, bất biến.

**Tech Stack:** llama.cpp llama-server (bản Vulkan, pin checksum), Python 3.11 + httpx (đã có trong venv), PowerShell cho vòng đời server và đo RSS.

**Design:** `docs/superpowers/specs/2026-08-11-slm-three-roles-design.md`.

## Global Constraints

- **Không đụng `src/`** trong spike này. Tích hợp là Phase 2, plan riêng, chỉ mở sau go.
- **Không đụng `experiments/offline_poc/`** — CLAUDE.md: archive, không thêm gì.
- Model dùng lại hai file **đã có trên đĩa** kèm `.sha256`: `experiments/offline_poc/models/qwen2.5-{0.5b,3b}-instruct-q4_k_m.gguf`. Đọc từ đó (đường dẫn tuyệt đối trong flags), **không copy, không tải mới** trừ khi một task nói rõ.
- Tải mới (nếu tới Task 8): đúng một profile mỗi lần, pin sha256 + metadata, theo kỷ luật `download_models.ps1`. Qwen2.5-3B mang **Qwen Research license** — mọi tài liệu nhắc nó phải kèm ghi chú license; ứng viên mới ưu tiên họ Apache-2.0.
- `eval/results/spike-003/` là **bất biến**: script từ chối ghi đè run-id đã tồn tại; không hand-edit.
- Mỗi run manifest phải ghi: build llama.cpp, toàn bộ flags server, sha256 model, cấu hình máy. Số không có manifest là số không tồn tại.
- Mọi số từ bộ dò mang nhãn **probe, not evidence** (người viết đã đọc `router.py`).
- Binary trong `tools/` không commit — chỉ commit `.sha256` + `.metadata.json` (thêm `tools/**/*.exe`, `tools/**/*.dll`, `tools/**/*.zip` vào `.gitignore` nếu chưa có).

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `tools/llama-vulkan/` + sidecars | Binary llama-server bản Vulkan, pin checksum | 1 |
| `scripts/spike3_server.ps1` | Khởi động/tắt llama-server theo profile flags | 1 |
| `scripts/spike3_bench.py` | Client đo: gọi `/completion`, tách prefill/decode, ghi run bất biến | 2 |
| `scripts/spike3_prompt.txt` | System prompt hợp nhất + few-shot | 4 |
| `scripts/spike3_schema.json` | JSON Schema union `plan | chitchat` (server tự chuyển grammar) | 4 |
| `eval/datasets/probe/v1/{cases.jsonl,README.md}` | Bộ dò cách-3 + giới hạn ghi rõ | 5 |
| `scripts/spike3_probe_filter.py` | Lọc: chỉ giữ câu router thật trả `not_control` | 5 |
| `scripts/spike3_quality.py` | Bậc C: kind/tool accuracy + latency trên bộ dò | 6 |
| `eval/results/spike-003/` | Run bất biến | 2–7 |
| `docs/adr/ADR-016-slm-fallback-gates.md` (draft) | Đề xuất cổng bằng số đo, nhóm chốt | 8 |

---

### Task 1: Binary Vulkan + vòng đời server

**Files:**
- Create: `tools/llama-vulkan/` (binary không commit), `tools/llama-vulkan/llama-vulkan.metadata.json`, `tools/llama-vulkan/llama-vulkan.zip.sha256`
- Create: `scripts/spike3_server.ps1`
- Modify: `.gitignore`

**Interfaces:**
- Produces: server chạy tại `http://127.0.0.1:8093`; `spike3_server.ps1 -Model <path> -Backend cpu6|cpu12|vulkan` cho Task 2–7 dùng.

- [ ] **Step 1: Chọn và pin bản phát hành**

Mở https://github.com/ggml-org/llama.cpp/releases, lấy bản release ổn định mới nhất có asset `llama-<build>-bin-win-vulkan-x64.zip`. Ghi `<build>` lại — mọi bước sau dùng biến `$Build` này. Tải **thủ công một lần** (đây là bước dev-time, không phải runtime):

```powershell
$Build = "bXXXX"   # điền build vừa chọn — đây là biến runtime của bước này, không phải placeholder trong repo
cd tools\llama-vulkan
Invoke-WebRequest "https://github.com/ggml-org/llama.cpp/releases/download/$Build/llama-$Build-bin-win-vulkan-x64.zip" -OutFile "llama-$Build-bin-win-vulkan-x64.zip"
(Get-FileHash ".\llama-$Build-bin-win-vulkan-x64.zip" -Algorithm SHA256).Hash.ToLower() + "  llama-$Build-bin-win-vulkan-x64.zip" | Out-File -Encoding ascii llama-vulkan.zip.sha256
Expand-Archive ".\llama-$Build-bin-win-vulkan-x64.zip" -DestinationPath .
```

Ghi `llama-vulkan.metadata.json`:

```json
{
  "source": "https://github.com/ggml-org/llama.cpp/releases",
  "build": "<build đã chọn>",
  "asset": "llama-<build>-bin-win-vulkan-x64.zip",
  "sha256_sidecar": "llama-vulkan.zip.sha256",
  "pinned_at": "2026-08-11",
  "reason": "SPIKE-003 — bản b9637 hiện có là CPU-only, không đo được GPU"
}
```

- [ ] **Step 2: Kiểm GPU có được nhận không — điểm dừng đầu tiên của spike**

```powershell
.\llama-server.exe --list-devices
```

Expected: danh sách chứa thiết bị Vulkan tương ứng RX 5500M. **Nếu không có:** cài/ cập nhật driver Adrenalin rồi thử lại đúng một lần. Vẫn không có → ghi kết quả vào báo cáo, bậc A chạy tiếp **chỉ với hai cấu hình CPU** — đừng dừng cả spike, vì cột CPU 6 luồng vẫn là số mới.

- [ ] **Step 3: Viết `scripts/spike3_server.ps1`**

```powershell
param(
    [Parameter(Mandatory)][string]$Model,
    [Parameter(Mandatory)][ValidateSet("cpu6","cpu12","vulkan")][string]$Backend,
    [int]$Port = 8093,
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
$bin = Join-Path $PSScriptRoot "..\tools\llama-vulkan\llama-server.exe"

if ($Stop) { Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force; exit 0 }

# Kiểm checksum model trước khi load — kỷ luật "no unverified artifacts".
$side = "$Model.sha256"
if (-not (Test-Path $side)) { throw "Thiếu sidecar $side" }
$want = (Get-Content $side).Split(" ")[0].ToLower()
$have = (Get-FileHash $Model -Algorithm SHA256).Hash.ToLower()
if ($want -ne $have) { throw "Checksum lệch: $Model" }

$flags = @("-m", $Model, "--host", "127.0.0.1", "--port", $Port, "-c", "2048",
           "--cache-reuse", "256")
switch ($Backend) {
    "cpu6"   { $flags += @("-t", "6",  "-ngl", "0") }
    "cpu12"  { $flags += @("-t", "12", "-ngl", "0") }
    "vulkan" { $flags += @("-ngl", "99") }
}
$p = Start-Process -FilePath $bin -ArgumentList $flags -PassThru -WindowStyle Hidden
# Chờ health tối đa 120 s (lần đầu Vulkan compile shader có thể lâu)
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
        Write-Host "server pid=$($p.Id) backend=$Backend model=$(Split-Path $Model -Leaf)"
        exit 0
    } catch { Start-Sleep -Milliseconds 500 }
}
Stop-Process -Id $p.Id -Force
throw "llama-server không lên health trong 120s"
```

- [ ] **Step 4: Smoke — server lên với cả ba backend, model 0.5B**

Chạy lần lượt `cpu6`, `cpu12`, `vulkan` với model 0.5B (đường dẫn tuyệt đối tới `experiments\offline_poc\models\qwen2.5-0.5b-instruct-q4_k_m.gguf`), mỗi lần `-Stop` trước khi đổi. Expected: ba lần đều in `server pid=…`. Backend `vulkan` fail mà Step 2 đã nhận thiết bị → đọc log server trước khi kết luận.

- [ ] **Step 5: Commit** (chỉ sidecars, metadata, script, .gitignore)

```bash
git add tools/llama-vulkan/llama-vulkan.metadata.json tools/llama-vulkan/llama-vulkan.zip.sha256 scripts/spike3_server.ps1 .gitignore
git commit -m "feat(spike3): pin llama.cpp ban Vulkan + vong doi server co kiem checksum"
```

---

### Task 2: Client đo với run bất biến

**Files:**
- Create: `scripts/spike3_bench.py`

**Interfaces:**
- Consumes: server từ Task 1.
- Produces: `run(prompts, *, grammar_schema, n_predict, tag) -> run_dir`; mỗi record có `prompt_ms, prompt_n, predicted_ms, predicted_n, text`; CLI `--tag --model --backend --n 32`. Task 3/6/7 dùng lại module này.

- [ ] **Step 1: Viết `scripts/spike3_bench.py`**

```python
"""SPIKE-003 — client đo llama-server, tách prefill/decode, ghi run bất biến.

Vì sao tách: SPIKE-001 chỉ đo tổng wall time nên không phân biệt được "prompt dài"
với "decode chậm" — hai bệnh cần hai thuốc khác nhau. `/completion` của llama-server
trả `timings.prompt_ms/prompt_n/predicted_ms/predicted_n`; đó là nguồn số ở đây.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results" / "spike-003"
ENDPOINT = "http://127.0.0.1:8093"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _server_rss_mb() -> float | None:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process llama-server -ErrorAction SilentlyContinue).PeakWorkingSet64"],
        capture_output=True, text=True,
    ).stdout.strip()
    return round(int(out) / 2**20, 1) if out.isdigit() else None


def call(client: httpx.Client, prompt: str, *, schema: dict | None, n_predict: int) -> dict:
    body: dict = {"prompt": prompt, "temperature": 0, "n_predict": n_predict,
                  "cache_prompt": True}
    if schema is not None:
        body["json_schema"] = schema
    r = client.post(f"{ENDPOINT}/completion", json=body, timeout=180.0)
    r.raise_for_status()
    d = r.json()
    t = d.get("timings", {})
    return {
        "text": d.get("content", ""),
        "prompt_ms": t.get("prompt_ms"), "prompt_n": t.get("prompt_n"),
        "predicted_ms": t.get("predicted_ms"), "predicted_n": t.get("predicted_n"),
        "stopped_limit": d.get("stopped_limit", False),  # hết n_predict giữa chừng
    }


def run(prompts: list[dict], *, tag: str, model: Path, backend: str,
        schema: dict | None, n_predict: int) -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = RESULTS / run_id
    if run_dir.exists():
        raise SystemExit(f"run-id đã tồn tại: {run_dir}")  # bất biến, không ghi đè
    run_dir.mkdir(parents=True)

    records = []
    with httpx.Client() as client:
        for p in prompts:
            rec = call(client, p["prompt"], schema=schema, n_predict=n_predict)
            rec["case_id"] = p.get("case_id", "")
            records.append(rec)

    decode_tps = [r["predicted_n"] / (r["predicted_ms"] / 1000)
                  for r in records if r.get("predicted_ms")]
    total_ms = sorted((r["prompt_ms"] or 0) + (r["predicted_ms"] or 0) for r in records)
    manifest = {
        "run_id": run_id, "tag": tag, "backend": backend,
        "model": model.name, "model_sha256": _sha256(model),
        "endpoint": ENDPOINT, "n_predict": n_predict,
        "grammar": schema is not None, "n_cases": len(records),
        "decode_tps_median": round(statistics.median(decode_tps), 1) if decode_tps else None,
        "total_ms_p50": total_ms[len(total_ms) // 2] if total_ms else None,
        "total_ms_p95": total_ms[int(len(total_ms) * 0.95) - 1] if len(total_ms) >= 2 else None,
        "truncated": sum(1 for r in records if r["stopped_limit"]),
        "server_peak_rss_mb": _server_rss_mb(),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    with open(run_dir / "records.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(manifest, indent=1))
    return run_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--backend", required=True)
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--n-predict", type=int, default=160)
    ap.add_argument("--schema", default=None, help="đường dẫn spike3_schema.json")
    ap.add_argument("--prompt-file", default=None, help="prefix tĩnh (system+few-shot)")
    args = ap.parse_args()

    prefix = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else ""
    seed_utterances = ["Đặt điều hòa 22 độ", "Mở cửa sổ bên lái", "Xin chào cabin copilot",
                       "Cảm ơn nhé", "Bật sưởi ghế mức 2", "Hôm nay trời đẹp nhỉ"]
    prompts = [{"case_id": f"warm-{i}", "prompt": prefix + seed_utterances[i % len(seed_utterances)] + "\nJSON:"}
               for i in range(args.n)]
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8")) if args.schema else None
    run(prompts, tag=args.tag, model=Path(args.model), backend=args.backend,
        schema=schema, n_predict=args.n_predict)
```

- [ ] **Step 2: Smoke chống server (0.5B, cpu6)**

```powershell
.\scripts\spike3_server.ps1 -Model <abs>\qwen2.5-0.5b-instruct-q4_k_m.gguf -Backend cpu6
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe scripts\spike3_bench.py --tag smoke --model <abs>\qwen2.5-0.5b-instruct-q4_k_m.gguf --backend cpu6 --n 4
```

Expected: manifest in ra có `decode_tps_median` là số > 0, `prompt_ms`/`predicted_ms` không null, thư mục run xuất hiện dưới `eval/results/spike-003/`. Chạy lại lần hai phải tạo run-id **mới**, không đè.

- [ ] **Step 3: Commit**

```bash
git add scripts/spike3_bench.py
git commit -m "feat(spike3): client do tach prefill/decode, run bat bien"
```

---

### Task 3: Bậc A — ma trận tốc độ thô

**Files:** không file mới — chạy Task 1+2, ghi 6 run.

- [ ] **Step 1: Chạy ma trận** {cpu6, cpu12, vulkan} × {0.5B, 3B}, mỗi ô `--n 16 --tag rungA-<backend>-<model>`, không schema, không prompt-file (đo thô).

- [ ] **Step 2: Điền bảng quyết định vào báo cáo nháp** (`docs/reports/SPIKE-003-notes.md`, tạo mới, format tự do — đây là nháp làm việc, chưa phải báo cáo cuối):

| Cấu hình | decode tok/s (median) | Ước p50 lượt fallback* |
|---|---|---|
| 3B vulkan | ? | ? |
| 3B cpu6 | ? | ? |
| 0.5B vulkan | ? | ? |
| 0.5B cpu6 | ? | ? |

\* công thức: `p50 ≈ prefill_câu_người_dùng (~30 token, cache prefix ăn phần còn lại) + 80 token output ÷ decode_tps`.

- [ ] **Step 3: Áp tiêu chí dừng của bậc A** (từ design doc): Vulkan không nhận GPU **và** 3B cpu6 < 12 tok/s → 3B loại khỏi các bậc sau, spike tiếp tục với 0.5B + ghi nhận cần model trung gian (1–2B, Apache) ở Task 8. Ngược lại → chọn **một** cấu hình vô địch cho bậc B/C.

- [ ] **Step 4: Commit notes**

```bash
git add docs/reports/SPIKE-003-notes.md
git commit -m "docs(spike3): ket qua bac A + quyet dinh cau hinh"
```

---

### Task 4: Bậc B — grammar hợp nhất + prompt cache

**Files:**
- Create: `scripts/spike3_schema.json`, `scripts/spike3_prompt.txt`

- [ ] **Step 1: Viết `scripts/spike3_schema.json`** — union hai hình dạng, discriminator `kind`. Cố ý **không** ràng args theo từng tool (converter GBNF của server kém với schema sâu; `validate_args` trong `src/agents/tools.py` đã làm việc đó lúc parse — spike chỉ cần grammar giữ vỏ):

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "kind": {"const": "plan"},
        "schema_version": {"const": "1.0"},
        "steps": {
          "type": "array", "minItems": 1, "maxItems": 3,
          "items": {
            "type": "object",
            "properties": {
              "step_id": {"type": "string"},
              "ordinal": {"type": "integer"},
              "tool": {"enum": ["set_hvac_temperature", "set_hvac_power", "set_seat_heating",
                                 "set_seat_position", "set_window_position", "set_door_state",
                                 "media_control", "set_navigation", "search_nearby"]},
              "args": {"type": "object"},
              "depends_on": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["step_id", "ordinal", "tool", "args", "depends_on"],
            "additionalProperties": false
          }
        }
      },
      "required": ["kind", "schema_version", "steps"],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "kind": {"const": "chitchat"},
        "reply": {"type": "string", "maxLength": 240}
      },
      "required": ["kind", "reply"],
      "additionalProperties": false
    }
  ]
}
```

- [ ] **Step 2: Viết `scripts/spike3_prompt.txt`** — system + 4 few-shot (2 plan, 2 chitchat), toàn bộ là prefix tĩnh để cache ăn:

```
Bạn là trợ lý trong xe VinFast. Với mỗi câu của tài xế, trả về đúng MỘT JSON:
- Nếu là yêu cầu điều khiển xe: {"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,"tool":"<tool>","args":{...},"depends_on":[]}]}
- Nếu là câu chào hỏi, cảm ơn, tán gẫu: {"kind":"chitchat","reply":"<một câu tiếng Việt ngắn, thân thiện>"}
Không giải thích. Không nói rằng đã thực hiện hành động nào.

Câu: Đặt điều hòa 24 độ
JSON: {"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,"tool":"set_hvac_temperature","args":{"temperature_c":24},"depends_on":[]}]}

Câu: Kéo hé cửa kính bên phụ tí thôi
JSON: {"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,"tool":"set_window_position","args":{"window":"front_right","percent":30},"depends_on":[]}]}

Câu: Xin chào cabin copilot
JSON: {"kind":"chitchat","reply":"Chào bạn! Tôi là VIVI, cần tôi giúp gì trên xe cứ nói nhé."}

Câu: Cảm ơn nhé
JSON: {"kind":"chitchat","reply":"Không có gì! Chúc bạn lái xe an toàn."}

Câu: 
```

- [ ] **Step 3: Đo bốn tổ hợp trên cấu hình vô địch** (cùng model, cùng backend, `--n 16`):
  1. `--tag rungB-bare` (không schema, không prompt-file — trùng bậc A, làm mốc)
  2. `--tag rungB-grammar --schema scripts/spike3_schema.json`
  3. `--tag rungB-cache --prompt-file scripts/spike3_prompt.txt`
  4. `--tag rungB-full --schema … --prompt-file …`

- [ ] **Step 4: Đọc số, áp tiêu chí dừng bậc B:**
  - Overhead grammar = decode_tps(2) so với (1). Chậm > 30% → xem lại schema (thu hẹp), ghi nhận.
  - Cache: trong run (3)/(4), `prompt_ms` của mọi call **sau call đầu** phải nhỏ hơn hẳn call đầu (kỳ vọng chỉ còn prefill phần câu người dùng, ~30 token). Không ăn → thử flag khác (`--cache-reuse` giá trị lớn hơn), vẫn không → ngân sách few-shot phải tính lại, ghi vào notes.
  - Đếm `truncated` — grammar không bảo đảm sinh xong; tỉ lệ > 5% → tăng `n_predict`, đo lại.

- [ ] **Step 5: Commit**

```bash
git add scripts/spike3_schema.json scripts/spike3_prompt.txt docs/reports/SPIKE-003-notes.md
git commit -m "feat(spike3): grammar hop nhat + prompt cache, ket qua bac B"
```

---

### Task 5: Bộ dò cách-3

**Files:**
- Create: `eval/datasets/probe/v1/cases.jsonl`, `eval/datasets/probe/v1/README.md`
- Create: `scripts/spike3_probe_filter.py`

- [ ] **Step 1: Viết `scripts/spike3_probe_filter.py`** — lọc bằng router thật, không tin cảm giác:

```python
"""Chỉ giữ câu mà DeterministicControlRouter thật trả `not_control`.

Câu router bắt được không được nằm trong bộ dò: chúng không bao giờ tới SLM
trong production, giữ lại chỉ làm đẹp số một cách vô nghĩa.
"""
import json
import sys
from pathlib import Path

from src.agents.router import DeterministicControlRouter

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
```

- [ ] **Step 2: Viết tay ~60 câu nháp** vào `eval/datasets/probe/v1/cases_draft.jsonl`, format `{"case_id","input_text","expected":{"kind":"plan"|"chitchat", "tool":…, "args":…}}` (tool/args chỉ khi kind=plan). Hạn ngạch từng nhóm — đây là danh mục bắt buộc, không phải gợi ý:
  - 25 câu **lệnh nói lệch khuôn** phủ cả 9 tool, mỗi tool ≥ 2 (ví dụ kiểu: "nóng quá, làm mát đi", "cho tí gió tầng trên", "kính bên tao hạ xuống nửa chừng", "ghế này lạnh lưng quá");
  - 15 câu **xã giao** (chào, cảm ơn, hỏi tên, khen/chê thời tiết, "mệt quá");
  - 10 câu **ngoài phạm vi xe** (hỏi kiến thức chung, nhờ việc ngoài xe) — expected `chitchat` với reply từ chối nhẹ;
  - 10 câu **bẫy** (mơ hồ giữa lệnh và tán gẫu: "lạnh nhỉ", "tối quá") — expected ghi cả hai nhãn chấp nhận được, trường `expected.accept_kinds`.

- [ ] **Step 3: Lọc và chốt**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe scripts\spike3_probe_filter.py eval\datasets\probe\v1\cases_draft.jsonl > eval\datasets\probe\v1\cases.jsonl
```

Câu lệnh-lệch-khuôn bị router **bắt được** sẽ bị loại — đó là tin tốt về router, ghi số lượng vào README. Nếu nhóm lệnh còn < 15 câu sau lọc, viết thêm cho đủ (vòng lặp viết→lọc tối đa 3 lần, tránh ngồi gọt vô hạn). Xoá `cases_draft.jsonl` sau khi chốt.

- [ ] **Step 4: Viết `eval/datasets/probe/v1/README.md`** — bắt buộc có các mục: nguồn gốc (người viết đã đọc `router.py` — **probe, not evidence**, theo đúng chuẩn README của `agent/v3`); quyết định nhóm 2026-08-11 (thay bằng dữ liệu người dùng thử khi demo được); cấu tạo nhóm + số câu bị lọc; cách chạy.

- [ ] **Step 5: Commit**

```bash
git add eval/datasets/probe/v1/ scripts/spike3_probe_filter.py
git commit -m "feat(spike3): bo do cach-3, loc bang router that, gioi han ghi ro"
```

---

### Task 6: Bậc C — chất lượng trên bộ dò

**Files:**
- Create: `scripts/spike3_quality.py`

- [ ] **Step 1: Viết `scripts/spike3_quality.py`** — dùng lại `spike3_bench.run`, thêm chấm điểm:

```python
"""Bậc C: kind/tool accuracy + latency trên bộ dò. Số mang nhãn probe-not-evidence."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from spike3_bench import run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "eval" / "datasets" / "probe" / "v1" / "cases.jsonl"


def score(run_dir: Path, cases: list[dict]) -> dict:
    records = [json.loads(l) for l in (run_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    by_id = {r["case_id"]: r for r in records}
    n = kind_ok = tool_ok = parse_fail = plan_n = 0
    for c in cases:
        n += 1
        rec = by_id[c["case_id"]]
        try:
            out = json.loads(rec["text"])
        except ValueError:
            parse_fail += 1
            continue
        accept = c["expected"].get("accept_kinds") or [c["expected"]["kind"]]
        if out.get("kind") in accept:
            kind_ok += 1
        if c["expected"].get("kind") == "plan":
            plan_n += 1
            steps = out.get("steps") or [{}]
            if out.get("kind") == "plan" and steps[0].get("tool") == c["expected"]["tool"]:
                tool_ok += 1
    return {
        "n": n, "parse_fail": parse_fail,
        "kind_accuracy": round(kind_ok / n, 3) if n else None,
        "tool_accuracy_on_plan": round(tool_ok / plan_n, 3) if plan_n else None,
        "label": "PROBE-NOT-EVIDENCE",
    }


if __name__ == "__main__":
    model, backend = sys.argv[1], sys.argv[2]
    prefix = (ROOT / "scripts" / "spike3_prompt.txt").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "scripts" / "spike3_schema.json").read_text(encoding="utf-8"))
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    prompts = [{"case_id": c["case_id"], "prompt": prefix + c["input_text"] + "\nJSON:"} for c in cases]
    run_dir = run(prompts, tag="rungC-quality", model=Path(model), backend=backend,
                  schema=schema, n_predict=160)
    result = score(run_dir, cases)
    (run_dir / "quality.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
```

- [ ] **Step 2: Chạy trên cấu hình vô địch, cả 0.5B lẫn 3B** (nếu 3B sống sót bậc A). So hai model trên **cùng** bộ dò.

- [ ] **Step 3: Áp tiêu chí dừng bậc C** (design doc): `tool_accuracy_on_plan < 0.70` trên mọi model → **dừng ①**, Phase 2 chỉ ship ③ (chitchat); `kind_accuracy < 0.85` → xem lại prompt/few-shot một vòng rồi đo lại (tối đa 2 vòng chỉnh prompt — mỗi vòng là một run mới, không đè). Ghi mọi vòng vào notes.

- [ ] **Step 4: Commit**

```bash
git add scripts/spike3_quality.py docs/reports/SPIKE-003-notes.md
git commit -m "feat(spike3): bac C — kind/tool accuracy tren bo do"
```

---

### Task 7: Bậc D — RAM khi chạy đồng thời

- [ ] **Step 1: Dựng tình huống thật**: llama-server (cấu hình vô địch) + backend `python -m src.serve` với STT engine đã warm (gọi một lượt `/turns/voice` mock hoặc `voice.get_stt_engine()` nếu model STT có trên máy — nếu thiếu model STT, ghi rõ giới hạn "đo thiếu STT" trong notes thay vì giả số).

- [ ] **Step 2: Đo**

```powershell
Get-Process llama-server,python | Select-Object Name,@{n="PeakMB";e={[math]::Round($_.PeakWorkingSet64/1MB)}}
Get-CimInstance Win32_OperatingSystem | Select-Object @{n="FreeMB";e={[math]::Round($_.FreePhysicalMemory/1KB)}}
```

- [ ] **Step 3: Tiêu chí:** tổng peak + headroom hệ điều hành vượt 7,4 GB vật lý → cấu hình CPU cho 3B bị loại (model phải nằm VRAM), ghi kết luận vào notes.

- [ ] **Step 4: Commit notes.**

---

### Task 8: Báo cáo + dự thảo ADR-016 + go/no-go

- [ ] **Step 1: Viết `docs/reports/SPIKE-003-slm-feasibility.md`** từ notes — mọi số kèm run-id; bảng so với SPIKE-001 phải ghi rõ **nhiệm vụ đã đổi nên không so trực tiếp được**, chỉ so được cột hạ tầng (decode tok/s cùng model cùng máy).

- [ ] **Step 2: Nếu số cho thấy cần model trung gian** (0.5B trượt chất lượng, 3B trượt độ trễ): chọn đúng **một** ứng viên họ Apache-2.0 cỡ 1–2B có tiếng Việt (ưu tiên họ Qwen3 theo khảo sát 2026), tải bằng script pin checksum một-profile-một-lần, lặp lại Task 3→6 cho riêng nó. Không tải quá một ứng viên khi chưa đo xong ứng viên trước.

- [ ] **Step 3: Viết `docs/adr/ADR-016-slm-fallback-gates.md`** — Status **Proposed**; đề xuất cổng cho đường fallback (độ trễ p50/p95, kind-accuracy tối thiểu, tỉ lệ truncation) **điền bằng số đo thật**, kèm lập luận vì sao khác cổng SPIKE-001 (fallback ≠ primary); mục "cần nhóm chốt" liệt kê: ngân sách chờ của tài xế, có bật `slm_enabled` mặc định không, `/healthz` giữ miễn trừ `llm` hay không.

- [ ] **Step 4: Cập nhật WORKLOG.md** theo khuôn bảng sẵn có.

- [ ] **Step 5: Commit, mở PR** base `develop`. PR ghi rõ: spike không đụng `src/`; Phase 2 (tích hợp `slm_stage` union + outcome `chitchat` + compose) là plan riêng, chỉ mở sau khi nhóm duyệt ADR-016.

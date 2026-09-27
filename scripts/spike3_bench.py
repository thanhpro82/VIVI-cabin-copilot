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


def _rss_linux_mb() -> float | None:
    """Đỉnh RSS của llama-server đọc từ `/proc/<pid>/status`.

    Dùng `VmHWM` chứ không `VmRSS`: `VmHWM` là **high-water mark**, tức cùng ngữ
    nghĩa với `PeakWorkingSet64` của Windows. `VmRSS` là giá trị tại thời điểm đọc,
    và vì hàm này chạy **sau** vòng đo nên nó sẽ báo thấp hơn đỉnh thật.

    Nhận diện tiến trình bằng `comm` (tên tiến trình) chứ không phải `cmdline`:
    `cmdline` chứa cả đường dẫn model nên một tiến trình khác đang nhắc tới
    "llama-server" cũng khớp.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return None  # không phải Linux
    peak_kb = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != "llama-server":
                continue
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    peak_kb = max(peak_kb, int(line.split()[1]))
                    break
        except (OSError, ValueError, IndexError):
            continue  # tiến trình chết giữa lúc duyệt — bình thường, bỏ qua
    return round(peak_kb / 1024, 1) if peak_kb else None


def _rss_windows_mb() -> float | None:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process llama-server -ErrorAction SilentlyContinue).PeakWorkingSet64"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None  # không có powershell (Linux), hoặc nó treo
    return round(int(out) / 2**20, 1) if out.isdigit() else None


def _server_rss_mb() -> float | None:
    """Đỉnh RSS của llama-server, hoặc `None` nếu không đo được.

    Hàm này chạy ở bước **ghi manifest**, tức sau khi toàn bộ vòng đo đã xong. Nên
    nó tuyệt đối không được ném: một exception ở đây xoá trắng công đo vừa thực hiện.
    Bản trước gọi thẳng `powershell` không bọc `try`, và ném `FileNotFoundError` trên
    Linux đúng ở chỗ đó (vấp thật khi đo trên VPS, 2026-08-22).

    Thiếu cột RAM thì run vẫn có ích — `manifest.json` ghi `null` và mọi số đo độ trễ
    vẫn nguyên vẹn.
    """
    return _rss_linux_mb() or _rss_windows_mb()


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


def _device() -> dict:
    """Thiết bị mà `spike3_server.ps1` **thật sự** đã resolve, không phải nhãn gõ tay.

    `backend="vulkan"` một mình vô nghĩa trên máy có hai GPU Vulkan, và số thứ tự
    `VulkanN` đã được chứng minh là đổi giữa các lần boot (13/08/2026: thứ tự ngược
    với chú thích trong chính script). Nên manifest lấy **tên thiết bị** từ file do
    server script ghi ra lúc khởi động.

    Thiếu file thì ghi `unknown` chứ không đoán: một run không biết chạy trên đâu vẫn
    là một run có ích, còn một run gắn nhãn sai thì tệ hơn không có run.
    """
    path = RESULTS / "device-last.json"
    if not path.exists():
        return {"device_name": "unknown", "device_ordinal": None}
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return {"device_name": "unknown", "device_ordinal": None}
    return {"device_name": d.get("device_name") or "unknown", "device_ordinal": d.get("device_ordinal")}


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
        **_device(),
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

r"""Bộ đo: planner có dựng nổi args HỢP LỆ cho từng actuator không.

Vì sao cần một bộ đo riêng: `dinh-tuyen-v1` đo *câu đi đúng nhánh nào*, `agent/v3` đo
*intent*. Không bộ nào hỏi câu này — *"chuỗi model trả về có qua nổi `validate_args`
không"* — và đó chính là chỗ hỏng của issue #269: prompt kê 9 tool trong khi registry
có 16, nên với mọi tool không có ví dụ, model tự chế tên field.

Chạy::

    pwsh scripts/run_slm_server.ps1 -Model <gguf> -Port 8093 -Device "<GPU>"
    $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe scripts\do_planner_args.py
    .\.venv\Scripts\python.exe scripts\do_planner_args.py --prompt-cu   # mốc so sánh

Kết quả ghi vào `eval/results/planner-args/<UTC-run-id>/` — bất biến, không sửa tay.

## Số ở đây KHÔNG ổn định trong cùng một phiên server — đọc trước khi trích

Đo 27/08, cùng prompt, cùng model, cùng máy:

    server vừa khởi động        -> args hợp lệ 16/16   (lặp lại được, 2 phiên khác nhau)
    sau 3-4 lần chạy liên tiếp  -> args hợp lệ 13/16   (lặp lại được, 3 lần liền)

Ba ca tụt là `"bật đèn trần lên"`, `"huỷ dẫn đường"` (model chuyển sang trả
`kind: chitchat` cho một câu lệnh) và `"mở youtube"`. Nhiệt độ là 0, nên đây không phải
lấy mẫu ngẫu nhiên — nghi là `cache_prompt: True` cộng KV-reuse của llama-server.

Hai hệ quả:

1. **Với bộ đo:** mọi con số phải ghi rõ đo trên server vừa khởi động hay không.
   Manifest có `may` nhưng chưa có trường ấy — nợ, ghi ở đây để không quên.
2. **Với sản phẩm, và đây mới là phần đáng lo:** server thật chạy liên tục hàng giờ.
   Nếu độ trôi này là thật thì chất lượng plan **giảm dần theo thời gian sống của tiến
   trình**, và không một test nào trong repo bắt được — chúng đều chạy trên tiến trình
   mới. Chưa đo đủ để khẳng định; cần một lượt đo dài riêng.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

from src.agents.contracts import ValidationDenied
from src.agents.tools import validate_args
from src.config import get_settings

ROOT = Path(__file__).resolve().parents[1]

#: Mỗi actuator một câu lệnh **trần trụi** — không vế than, không ghép, không mơ hồ.
#: Cố ý dễ: bộ đo này hỏi về hình dạng args, không hỏi về khả năng hiểu câu khó.
CA: tuple[tuple[str, str], ...] = (
    ("set_hvac_power", "tắt điều hòa"),
    ("set_hvac_power", "bật điều hòa"),
    ("set_hvac_temperature", "đặt điều hòa 22 độ"),
    ("set_hvac_fan_level", "đặt quạt gió mức 2"),
    ("media_control", "mở nhạc lên"),
    ("media_control", "giảm âm lượng xuống 30"),
    ("media_control", "chuyển bài tiếp theo"),
    ("set_interior_light", "bật đèn trần lên"),
    ("set_headlight_mode", "bật đèn chiếu gần"),
    ("set_window_position", "mở cửa sổ bên lái một nửa"),
    ("set_door_state", "khoá cửa xe lại"),
    ("set_trunk_state", "mở cốp sau"),
    ("set_seat_heating", "bật sưởi ghế lái mức 2"),
    ("set_seat_position", "ngả ghế lái ra sau 60 phần trăm"),
    ("open_app", "mở youtube"),
    ("set_navigation", "huỷ dẫn đường"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt-cu",
        action="store_true",
        help="bơm lại prompt chép tay của SPIKE-003 để lấy mốc so sánh",
    )
    args = parser.parse_args()

    import src.agents.slm as slm

    nhan_prompt = "moi-sinh-tu-registry"
    if args.prompt_cu:
        slm.SLM_UNION_PROMPT = (ROOT / "scripts" / "spike3_prompt.txt").read_text(encoding="utf-8")
        nhan_prompt = "cu-chep-tay"

    settings = get_settings()
    planner = slm.QwenPlanner(settings.slm_endpoint, settings.slm_model_id, 40.0)
    snapshot = {"speed_kph": 0, "gear": "P"}

    ket: list[dict] = []
    for mong_doi, cau in CA:
        bat_dau = time.perf_counter()
        dong: dict = {"cau": cau, "tool_mong_doi": mong_doi, "prompt": nhan_prompt}
        try:
            raw = planner.propose(cau, snapshot)
            dong["latency_ms"] = int((time.perf_counter() - bat_dau) * 1000)
            obj = json.loads(raw)
            if obj.get("kind") != "plan" or not obj.get("steps"):
                # Model trả `kind: chitchat` cho một câu lệnh. Đây là một kiểu SAI
                # riêng — không phải lỗi hạ tầng, cũng không phải args hỏng — và bản
                # đầu của script này đếm nó thành `KeyError: 'steps'`, tức trộn nó
                # vào cùng rổ với "server chết". Hai thứ ấy cần đọc tách nhau.
                dong["kind"] = obj.get("kind")
                dong["tool_dung"] = False
                dong["args_hop_le"] = False
                ket.append(dong)
                continue
            step = obj["steps"][0]
            dong["tool"], dong["args"] = step["tool"], step["args"]
        except Exception as exc:  # noqa: BLE001 — bộ đo phải ghi lại mọi kiểu hỏng
            dong["latency_ms"] = int((time.perf_counter() - bat_dau) * 1000)
            dong["loi_goi"] = f"{type(exc).__name__}: {exc}"
            ket.append(dong)
            continue
        dong["tool_dung"] = dong["tool"] == mong_doi
        try:
            validate_args(dong["tool"], dong["args"])
            dong["args_hop_le"] = True
        except ValidationDenied as exc:
            dong["args_hop_le"] = False
            dong["ly_do_args_sai"] = str(exc)
        ket.append(dong)

    tong = len(ket)
    metrics = {
        "tong_ca": tong,
        "tool_dung": sum(1 for d in ket if d.get("tool_dung")),
        "args_hop_le": sum(1 for d in ket if d.get("args_hop_le")),
        "loi_goi": sum(1 for d in ket if "loi_goi" in d),
        "tra_chitchat": sum(1 for d in ket if d.get("kind") == "chitchat"),
        "latency_ms_p50": sorted(d["latency_ms"] for d in ket)[tong // 2],
    }

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f") + "Z"
    thu_muc = ROOT / "eval" / "results" / "planner-args" / run_id
    thu_muc.mkdir(parents=True, exist_ok=True)
    manifest = {
        "suite": "planner-args",
        "run_id": run_id,
        "prompt": nhan_prompt,
        "model_id": settings.slm_model_id,
        "endpoint": settings.slm_endpoint,
        "may": platform.platform(),
        "ghi_chu": "Đo hình dạng args, KHÔNG đo khả năng hiểu câu khó — mọi câu đều trần trụi.",
    }
    (thu_muc / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (thu_muc / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    with (thu_muc / "case_results.jsonl").open("w", encoding="utf-8") as fh:
        for dong in ket:
            fh.write(json.dumps(dong, ensure_ascii=False) + "\n")

    for dong in ket:
        dau = "OK " if dong.get("tool_dung") and dong.get("args_hop_le") else "   "
        print(f"{dau}{dong['cau']!r:36} -> {dong.get('tool', '—')} {json.dumps(dong.get('args', {}), ensure_ascii=False)}")
    print(f"\n[{nhan_prompt}] tool đúng {metrics['tool_dung']}/{tong} · args hợp lệ {metrics['args_hop_le']}/{tong}")
    print(f"-> eval/results/planner-args/{run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

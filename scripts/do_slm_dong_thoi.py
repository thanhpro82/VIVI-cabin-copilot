"""Đo llama-server khi **nhiều người dùng cùng lúc** — độ trễ, nạp nguội, và slot.

Ghi một thư mục run **bất biến** dưới `eval/results/slm-dong-thoi/<UTC-run-id>/`.

Chạy BÊN TRONG container backend, để dùng đúng prompt/schema thật và tính cả chặng
container → host:

    docker compose cp scripts/do_slm_dong_thoi.py backend:/app/scripts/do_slm_dong_thoi.py
    docker compose exec backend python scripts/do_slm_dong_thoi.py

## Vì sao cần script này khi đã có `deploy/vps/slm_classify_bench.py`

Script kia đo **một người dùng, tuần tự**, và đã trả lời tốt câu hỏi "một lượt classify
tốn bao lâu" (`docs/reports/sp0-do-tre-tung-doan-2026-08-22.md`). Thứ **chưa ai đo** là
**N người bấm cùng một khoảnh khắc**. Báo cáo SP-0 đo xen kẽ *vai* trên một client; nó
không đo *nhiều client song song*. Hai hiện tượng khác nhau, và chỉ cái thứ hai nói được
hệ phục vụ nổi bao nhiêu người.

## Vì sao gọi thẳng `/completion` thay vì dùng QwenClassifier/QwenPlanner

`QwenClassifier.classify()` chỉ trả về chuỗi đã parse, nuốt mất `id_slot` và `timings` —
đúng hai thứ phân biệt được "chậm vì xếp hàng" với "chậm vì nạp nguội tiền tố". Nên script
dựng thân request tại chỗ, nhưng **mọi hằng số đều import từ `src/agents/slm.py`**
(`SLM_UNION_PROMPT`, `CLASSIFY_SYSTEM`, `CLASSIFY_SCHEMA`, `UNION_SCHEMA`, `chatml`) — không
chép tay chữ nào. Chỉ `n_predict` là literal; xem `_N_PREDICT` bên dưới.

## `timings.prompt_n` là bằng chứng trực tiếp của nạp nguội

llama.cpp chỉ đếm vào `prompt_n` những token **thật sự phải tính**; phần trúng KV cache
không được đếm. Nên `prompt_n ≈ 240` nghĩa là tiền tố classify **không** có trong slot đó
(nạp nguội), còn `prompt_n ≈ 10` nghĩa là chỉ câu của người dùng phải tính (ấm). Đây là
thứ biến suy luận số học thành phép đo.

## Nguyên tắc: KHÔNG cắt ở trần thật

Trần khi gọi là 30 s, cố ý — cùng lý lẽ với `deploy/vps/slm_classify_bench.py`: cắt ở 3,5 s
thì mọi lần hụt đều trả về đúng 3.5 và không học được gì. Đo thời gian thật, đối chiếu trần
cấu hình ở khâu thống kê. Lượt chạm 30 s được **đánh dấu `cat_cut`** và mọi thống kê dính
chúng là **cận dưới**, không phải giá trị.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.slm import (  # noqa: E402
    CLASSIFY_SCHEMA,
    CLASSIFY_SYSTEM,
    SLM_UNION_PROMPT,
    UNION_SCHEMA,
    chatml,
)
from src.config import get_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = REPO_ROOT / "eval" / "results" / "slm-dong-thoi"

#: Trần dùng KHI GỌI. Không phải trần thật trong cấu hình — xem docstring.
TRAN_DO_S = 30.0

#: `n_predict` của từng vai. Literal vì `slm.py` cũng để literal trong thân request
#: (`QwenClassifier.classify` dòng ~398, `QwenPlanner.propose` dòng ~158). Đổi ở đó thì
#: phải đổi ở đây — đây là chỗ duy nhất script có thể lệch khỏi client thật.
_N_PREDICT = {"classify": 32, "planner": 160}

#: Ghim slot khi bật `--ghim-slot`: mỗi vai một slot riêng để tiền tố thường trú.
_SLOT_THEO_VAI = {"classify": 0, "planner": 1}

#: Trên ngưỡng này coi như **nạp nguội tiền tố**. Tiền tố classify ~240 token, union
#: ~562 token; câu tài xế chỉ 8–20 token. Ngưỡng 100 nằm giữa hai bậc, không nhạy cảm.
NGUONG_NAP_NGUOI_TOKEN = 100

#: Câu **trượt luật tất định**, tức đúng loại câu chạm tới SLM trong thực tế. Cùng tinh
#: thần với `deploy/vps/slm_classify_bench.py`: điều khiển nói tự nhiên, xã giao, hỏi sổ tay.
CASES = (
    "mở hé cửa sổ bên phải một chút",
    "hôm nay trời đẹp nhỉ",
    "xe này chạy được bao xa một lần sạc",
    "làm ơn cho mát hơn tí nữa",
    "bạn tên gì thế",
    "đèn báo màu vàng hình cái lò xo là gì",
    "chỉnh ghế lùi ra sau giúp mình",
    "cảm ơn nhé",
    "sạc nhanh mất bao lâu",
    "bật cái gì đó cho đỡ nóng",
)

_BLIND_SPOTS = {
    "mot_may_mot_lan": "MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.",
    "du_lieu_bi_cat_cut": (
        "Luot cham tran 30s duoc danh dau `cat_cut`. Gia tri that la '>= 30s, chua biet'. "
        "Moi o co `so_cat_cut > 0` thi p50/p95/max va ti le vuot tran deu la CAN DUOI."
    ),
    "p95_o_mau_nho_chinh_la_max": (
        "Voi `--vong 3`, muc N=1 chi co 3 mau nen 'p95' chinh la gia tri lon nhat. Dung doc no nhu mot phan vi that."
    ),
    "dong_thoi_khong_deu": (
        "N request ban ra gan nhu cung luc, KHONG mo phong nguoi dung that (ho den rai rac). "
        "Day la ca XAU NHAT, co y: cho tran tren cua do tre, khong cho ky vong trung binh."
    ),
    "lich_su_anh_huong_ket_qua": (
        "Do tre phu thuoc slot nao dang giu tien to nao, tuc phu thuoc vai phut TRUOC do. "
        "Hai run cung cau hinh co the lech 4x. Luon doc `so_lan_nap_nguoi` truoc khi so hai run."
    ),
    "khong_do_STT_TTS": (
        "Chi do llama-server. Luot that con qua STT/TTS - ca hai co khoa toan cuc "
        "(`voice.py:97`, `:192`, num_threads=1) nen cung noi tiep. Tong do tre se te hon."
    ),
    "n_predict_la_literal": (
        "`_N_PREDICT` chep tay tu `slm.py`. Doi n_predict o do ma quen o day thi script "
        "do mot cau hinh KHONG con ton tai. Kiem lai khi slm.py doi."
    ),
}


def _probe_server(endpoint: str) -> dict:
    """Đọc `/props` và `/slots` — ghi **số slot thật** vào manifest.

    Suy số slot từ dòng `ExecStart` là cách ra kết luận sai: mặc định `-np` đã đổi giữa
    các bản llama.cpp. Trên VPS, `-c 2048` không truyền `-np` mà journal khai
    `n_slots = 4, n_ctx_slot = 2048`.
    """
    import httpx  # noqa: PLC0415 - phụ thuộc của backend, chỉ có trong container

    out: dict = {}
    for ten, duong in (("props", "/props"), ("slots", "/slots")):
        try:
            resp = httpx.get(f"{endpoint.rstrip('/')}{duong}", timeout=10.0)
            resp.raise_for_status()
            out[ten] = resp.json()
        except Exception as exc:  # noqa: BLE001 - server cũ không có route này
            out[ten] = {"loi": f"{type(exc).__name__}: {exc}"}
    slots = out.get("slots")
    out["so_slot_doc_duoc"] = len(slots) if isinstance(slots, list) else None
    return out


def _than_request(vai: str, text: str, ghim: bool) -> dict:
    """Dựng đúng thân request mà `slm.py` gửi. Hằng số đều import, không chép tay."""
    if vai == "classify":
        body: dict = {
            "prompt": chatml(CLASSIFY_SYSTEM, f'Câu: "{text}"'),
            "temperature": 0,
            "n_predict": _N_PREDICT["classify"],
            "cache_prompt": True,
            "json_schema": CLASSIFY_SCHEMA,
        }
    else:
        body = {
            "prompt": SLM_UNION_PROMPT + text + "\nJSON:",
            "temperature": 0,
            "n_predict": _N_PREDICT["planner"],
            "cache_prompt": True,
            "json_schema": UNION_SCHEMA,
        }
    if ghim:
        body["id_slot"] = _SLOT_THEO_VAI[vai]
    return body


def _mot_lan(vai: str, endpoint: str, text: str, ghim: bool) -> dict:
    import httpx  # noqa: PLC0415

    body = _than_request(vai, text, ghim)
    started = time.perf_counter()
    try:
        resp = httpx.post(f"{endpoint.rstrip('/')}/completion", json=body, timeout=TRAN_DO_S)
        resp.raise_for_status()
        d = resp.json()
        t = d.get("timings", {})
        ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "vai": vai,
            "text": text,
            "ms": ms,
            "cat_cut": False,
            "loi": None,
            "id_slot": d.get("id_slot"),
            "prompt_n": t.get("prompt_n"),
            "prompt_ms": round(t.get("prompt_ms") or 0.0, 1),
            "predicted_n": t.get("predicted_n"),
            "predicted_ms": round(t.get("predicted_ms") or 0.0, 1),
            "stopped_limit": d.get("stopped_limit", False),
        }
    except Exception as exc:  # noqa: BLE001 - lỗi là DỮ LIỆU ở đây, không phải sự cố
        ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "vai": vai,
            "text": text,
            "ms": ms,
            # Chạm trần đo = dữ liệu bị cắt cụt, KHÁC hẳn một lỗi thật (kết nối, 500).
            "cat_cut": ms >= TRAN_DO_S * 1000 - 500,
            "loi": type(exc).__name__,
            "id_slot": None,
            "prompt_n": None,
            "prompt_ms": None,
            "predicted_n": None,
            "predicted_ms": None,
            "stopped_limit": None,
        }


def _thong_ke(ban_ghi: list[dict], nguong_s: float) -> dict:
    ms = sorted(r["ms"] for r in ban_ghi)
    if not ms:
        return {"n_mau": 0}
    tran_ms = nguong_s * 1000
    prompt_n = [r["prompt_n"] for r in ban_ghi if r["prompt_n"] is not None]
    nguoi = [n for n in prompt_n if n >= NGUONG_NAP_NGUOI_TOKEN]
    prefill = [r["prompt_ms"] for r in ban_ghi if r["prompt_ms"]]
    slots = Counter(r["id_slot"] for r in ban_ghi if r["id_slot"] is not None)
    return {
        "n_mau": len(ms),
        "p50_ms": round(statistics.median(ms), 1),
        "p95_ms": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 1),
        "max_ms": ms[-1],
        "so_loi": sum(1 for r in ban_ghi if r["loi"]),
        "so_cat_cut": sum(1 for r in ban_ghi if r["cat_cut"]),
        "nguong_doi_chieu_s": nguong_s,
        "so_vuot_tran": sum(1 for m in ms if m > tran_ms),
        "ti_le_vuot_tran": round(sum(1 for m in ms if m > tran_ms) / len(ms), 4),
        # Bằng chứng trực tiếp: token thật sự phải prefill (phần trúng cache không đếm).
        "so_lan_nap_nguoi": len(nguoi),
        "prompt_n_p50": round(statistics.median(prompt_n), 1) if prompt_n else None,
        "prompt_n_max": max(prompt_n) if prompt_n else None,
        "prefill_ms_p50": round(statistics.median(prefill), 1) if prefill else None,
        "prefill_ms_max": round(max(prefill), 1) if prefill else None,
        "slot_phan_bo": dict(sorted(slots.items())),
    }


def _chay_mot_muc(n: int, vai: str, endpoint: str, vong: int, ghim: bool) -> list[dict]:
    """N request **đồng thời**, lặp `vong` vòng."""
    ban_ghi: list[dict] = []
    for v in range(vong):
        vais = [(vai if vai != "tron" else ("classify" if i % 2 == 0 else "planner")) for i in range(n)]
        texts = [CASES[(v * n + i) % len(CASES)] for i in range(n)]
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(_mot_lan, vais[i], endpoint, texts[i], ghim) for i in range(n)]
            ban_ghi.extend(f.result() for f in futures)
    return ban_ghi


def _do(args: argparse.Namespace) -> dict:
    settings = get_settings()
    endpoint = settings.slm_endpoint
    muc = sorted({int(x) for x in args.moc.split(",") if x.strip()})
    if not muc:
        raise SystemExit("--moc rong")

    print(f"endpoint = {endpoint}")
    print(f"model_id = {settings.slm_model_id}")
    print(f"tran that trong cau hinh: classify={settings.slm_classify_timeout_s}s, planner={settings.slm_timeout_s}s")
    print(f"tran dung KHI DO: {TRAN_DO_S}s")
    print(f"ghim slot: {'CO (classify->0, planner->1)' if args.ghim_slot else 'KHONG'}\n")

    server = _probe_server(endpoint)
    print(f"so slot doc duoc tu /slots: {server['so_slot_doc_duoc']}\n")

    # Hâm nóng CẢ HAI tiền tố. Lượt đầu sau khi server khởi động đắt hơn hẳn
    # (spike3: 562 token / 28 733 ms) và không đại diện cho lúc chạy thật.
    print("Ham nong...", flush=True)
    for vai in ("classify", "planner"):
        r = _mot_lan(vai, endpoint, "kiểm tra hệ thống", args.ghim_slot)
        print(
            f"  {vai}: {r['ms']:.0f} ms | slot {r['id_slot']} | prefill {r['prompt_n']} tok"
            f"{' | LOI: ' + r['loi'] if r['loi'] else ''} — KHONG tinh vao thong ke"
        )
    print()

    ket_qua: dict = {}
    for vai in (v.strip() for v in args.vai.split(",")):
        if not vai:
            continue
        ket_qua[vai] = {}
        for n in muc:
            print(f"[{vai}] N={n} ({args.vong} vong)...", flush=True)
            ban_ghi = _chay_mot_muc(n, vai, endpoint, args.vong, args.ghim_slot)
            nguong = settings.slm_classify_timeout_s if vai == "classify" else settings.slm_timeout_s
            tk = _thong_ke(ban_ghi, nguong)
            ket_qua[vai][str(n)] = {"thong_ke": tk, "ban_ghi": ban_ghi if args.giu_ban_ghi else []}
            print(
                f"    p50 {tk['p50_ms']:.0f} | p95 {tk['p95_ms']:.0f} | max {tk['max_ms']:.0f} ms"
                f" | vuot tran {tk['so_vuot_tran']}/{tk['n_mau']}"
                f" | NAP NGUOI {tk['so_lan_nap_nguoi']}/{tk['n_mau']}"
                f" (prompt_n p50 {tk['prompt_n_p50']}, max {tk['prompt_n_max']})"
                f" | slot {tk['slot_phan_bo']}" + (f" | CAT CUT {tk['so_cat_cut']}" if tk["so_cat_cut"] else ""),
                flush=True,
            )

    return {
        "endpoint": endpoint,
        "model_id": settings.slm_model_id,
        "ghim_slot": args.ghim_slot,
        "slot_theo_vai": _SLOT_THEO_VAI if args.ghim_slot else None,
        "tran_do_s": TRAN_DO_S,
        "n_predict": _N_PREDICT,
        "nguong_nap_nguoi_token": NGUONG_NAP_NGUOI_TOKEN,
        "nguong_cau_hinh": {
            "slm_classify_timeout_s": settings.slm_classify_timeout_s,
            "slm_timeout_s": settings.slm_timeout_s,
        },
        "server": server,
        "moc": muc,
        "vong": args.vong,
        "ket_qua": ket_qua,
    }


def _report_md(kq: dict, manifest: dict) -> str:
    lines = [
        "# llama-server duoi tai dong thoi",
        "",
        f"- Run id: `{manifest['run_id']}`",
        f"- Commit: `{manifest['git_commit'][:12]}` (dirty: {manifest['git_dirty']})",
        f"- Endpoint: `{kq['endpoint']}`, model `{kq['model_id']}`",
        f"- **So slot doc duoc tu `/slots`: {kq['server']['so_slot_doc_duoc']}**",
        f"- **Ghim slot: {'CO — ' + str(kq['slot_theo_vai']) if kq['ghim_slot'] else 'KHONG'}**",
        f"- Nguong cau hinh: classify {kq['nguong_cau_hinh']['slm_classify_timeout_s']}s, "
        f"planner {kq['nguong_cau_hinh']['slm_timeout_s']}s",
        f"- Tran dung khi do: {kq['tran_do_s']}s (co y noi, de do duoc do tre THAT)",
        f"- Nap nguoi = `timings.prompt_n` >= {kq['nguong_nap_nguoi_token']} token",
        "",
    ]
    for vai, theo_n in kq["ket_qua"].items():
        lines += [
            f"## Vai `{vai}`",
            "",
            "| N | p50 (ms) | p95 (ms) | max (ms) | vuot tran | nap nguoi | prompt_n p50/max | prefill max (ms) | slot | cat cut |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
        ]
        for n, muc in theo_n.items():
            t = muc["thong_ke"]
            lines.append(
                f"| {n} | {t['p50_ms']:.0f} | {t['p95_ms']:.0f} | {t['max_ms']:.0f} "
                f"| {t['so_vuot_tran']}/{t['n_mau']} | **{t['so_lan_nap_nguoi']}/{t['n_mau']}** "
                f"| {t['prompt_n_p50']}/{t['prompt_n_max']} | {t['prefill_ms_max']} "
                f"| {t['slot_phan_bo']} | {t['so_cat_cut']} |"
            )
        lines.append("")

    lines += [
        "## Doc bang the nao",
        "",
        "1. **`nap nguoi`** la cot quan trong nhat. `timings.prompt_n` chi dem token THAT SU "
        "phai tinh; phan trung KV cache khong duoc dem. Nen `prompt_n` lon = tien to khong "
        "nam trong slot do = phai prefill lai tu dau (~19,6 tok/s tren may nay).",
        "2. **`vuot tran`** la thu nguoi dung cam nhan. Vuot tran classify = am tham roi ve "
        "nhanh so tay (`graph.py:333`), khong bao loi.",
        "3. **`cat cut` > 0** thi moi so trong dong do la CAN DUOI, khong phai gia tri.",
        "4. **`slot`** cho biet request roi vao rang nao. Ghim slot dung thi moi vai chi thay dung mot rang.",
        "",
        "## Diem mu",
        "",
    ]
    lines += [f"- **{k}** - {v}" for k, v in _BLIND_SPOTS.items()]
    lines.append("")
    return "\n".join(lines)


def _git(*args: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=15, check=False
        )
        return proc.stdout.strip()
    except Exception:  # noqa: BLE001 - trong container khong co git, manifest thieu mot truong
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Do llama-server khi nhieu nguoi dung cung luc")
    parser.add_argument("--moc", default="1,2,3,5,8", help="cac muc N dong thoi")
    parser.add_argument("--vai", default="classify,planner,tron", help="classify | planner | tron")
    parser.add_argument("--vong", type=int, default=3, help="so vong lap moi muc N")
    parser.add_argument(
        "--ghim-slot",
        action="store_true",
        help="ghim classify->slot 0, planner->slot 1 (do TRUOC khi sua slm.py)",
    )
    parser.add_argument("--giu-ban-ghi", action="store_true", help="ghi tung request vao metrics.json")
    parser.add_argument("--git-commit", default=None, help="commit dua tu ngoai vao (container khong co git)")
    args = parser.parse_args()

    kq = _do(args)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f") + "Z"
    out = RESULTS_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "suite": "slm-dong-thoi",
        "run_id": run_id,
        "run_uuid": str(uuid.uuid4()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": args.git_commit or _git("rev-parse", "HEAD") or "unknown",
        "git_dirty": bool(_git("status", "--porcelain")),
        "ghim_slot": args.ghim_slot,
        "note": (
            "Do tu trong container backend, dung dung prompt/schema import tu src/agents/slm.py. "
            "Bo sung cho deploy/vps/slm_classify_bench.py (tuan tu, N=1) va bao cao "
            "docs/reports/sp0-do-tre-tung-doan-2026-08-22.md (xen ke vai, mot client)."
        ),
        "blind_spots": _BLIND_SPOTS,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(kq, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(_report_md(kq, manifest), encoding="utf-8")

    print()
    print(_report_md(kq, manifest))
    print(f"Da ghi: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

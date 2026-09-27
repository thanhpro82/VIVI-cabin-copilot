"""Đo RAM **biên** mà backend tốn thêm cho mỗi phiên tài xế đang hoạt động.

Ghi một thư mục run **bất biến** dưới `eval/results/ram-phien-backend/<UTC-run-id>/`.

    python3 scripts/do_ram_phien_backend.py                    # 1,5,10,25 phien co luot
    python3 scripts/do_ram_phien_backend.py --khong-hoi        # chi tao phien, khong chay luot
    python3 scripts/do_ram_phien_backend.py --moc 1,10,25,50

Vì sao cần script này khi đã có `do_ram_nhieu_xe.py`: script kia đo phía **xe ảo**
và cho ra ~13 KB mỗi xe — gần như miễn phí. Nhưng phía **backend** mới là chỗ đắt:
mỗi phiên tài xế kéo theo một checkpoint LangGraph `InMemorySaver`
(`src/api/session_state.py:226`) giữ toàn bộ state của lượt, cộng bản ghi trace.
Không có con số đó thì không lập được ngân sách cho phương án multi-tenant.

## Vì sao đo qua HTTP chứ không dựng lại trong tiến trình riêng

Dựng `get_graph()` trong một tiến trình mới sẽ nạp **bản sao thứ hai** của torch +
FAISS + embedder E5 (~1 GB) lên một máy production đang chạy. Đó là rủi ro thật, và
nó đo sai: cái ta cần là chi phí biên **trong tiến trình backend thật**, nơi model đã
nằm sẵn. Nên script đứng ngoài, gọi API thật, và đọc RSS của container qua
`docker stats`.

Hệ quả: script chỉ dùng **thư viện chuẩn**, chạy được bằng `python3` của host, không
cần venv và không cần vào container.

## Hai điều script cố ý KHÔNG làm

- **Không ra lệnh điều khiển.** Câu hỏi mặc định là câu tra sổ tay, đi nhánh
  read-only. Một lệnh `"bật điều hòa"` sẽ publish MQTT vào **chiếc xe ảo dùng
  chung** và làm hỏng phiên của người đang dùng thật.
- **Không dọn phiên đã tạo.** Không có route xoá phiên trong bề mặt P0. Phiên tự hết
  hạn sau `session_ttl_hours` (24 h) và bị purge sau `session_retention_days` (30 d).
  Vì vậy **đừng chạy với `--moc` lớn**: `MAX_SESSIONS = 128` và `MAX_TOKENS = 256` là
  LRU, chạy quá tay sẽ đẩy phiên của người dùng thật ra khỏi cache.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = REPO_ROOT / "eval" / "results" / "ram-phien-backend"

DEFAULT_API = "http://127.0.0.1:8000/api/v1"
#: Câu tra sổ tay — cố ý KHÔNG khớp luật router nào, nên đi nhánh manual lookup
#: (read-only). Đổi sang câu điều khiển là actuate chiếc xe ảo dùng chung.
DEFAULT_CAU_HOI = "Áp suất lốp tiêu chuẩn của xe là bao nhiêu?"

_BLIND_SPOTS = {
    "mot_may_mot_lan": ("MOT lan lay mau tren MOT may. So de lap ngan sach, khong phai benchmark."),
    "docker_stats_khong_phai_rss_thuan": (
        "`docker stats` bao working set cua cgroup, khong phai VmRSS thuan: no gom "
        "ca page cache cua container. Do doc van dung vi cache gan nhu khong doi giua "
        "cac moc, nhung DIEM CHAN thi khong so duoc voi VmRSS cua script khac."
    ),
    "gop_ba_chi_phi": (
        "Do doc gom CA BA: checkpoint LangGraph, ban ghi trace trong TraceStore, va "
        "phien trong SQLite. Day la chu y - cai can lap ngan sach la 'mot tai xe dang "
        "hoat dong ton bao nhieu', khong phai tach rieng tung cau truc."
    ),
    "mot_luot_moi_phien": (
        "Moi phien chi chay MOT luot. Tai xe that noi nhieu luot, checkpoint lon dan "
        "theo lich su hoi thoai. Nen day la SAN, khong phai tran."
    ),
    "khong_tru_nhieu_slm": (
        "SLM dang bat: llama-server la tien trinh RIENG tren host, khong nam trong "
        "container backend, nen no khong vao con so nay. Nhung KV cache cua no co lon "
        "len theo so luot - phan do phai do rieng."
    ),
    "lru_lam_phang_duong": (
        "MAX_SESSIONS=128 va MAX_TOKENS=256 la LRU. Chay qua nguong do thi duong cong "
        "phang ra mot cach gia tao vi phien cu bi day ra, khong phai vi phien re di."
    ),
}


def _http(
    url: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: float = 60.0
) -> tuple[int, dict | None]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    req.add_header("Content-Type", "application/json; charset=utf-8")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def _docker(*args: str) -> str:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60, check=False)  # noqa: S603, S607
    if proc.returncode != 0:
        raise SystemExit(f"docker {' '.join(args)} that bai:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _tim_container(goi_y: str | None) -> str:
    if goi_y:
        return goi_y
    out = _docker("ps", "--filter", "name=backend", "--format", "{{.Names}}")
    ten = [x for x in out.splitlines() if x.strip()]
    if len(ten) != 1:
        raise SystemExit(
            f"Khong xac dinh duoc container backend (tim thay: {ten or 'khong co'}).\nChi dinh bang --container <ten>."
        )
    return ten[0]


def _mem_container_mb(ten: str) -> float:
    """MEM USAGE của container, đổi về MB. `docker stats` in dạng '1.046GiB / 7.61GiB'."""
    raw = _docker("stats", "--no-stream", "--format", "{{.MemUsage}}", ten)
    phan = raw.split("/")[0].strip()
    match = re.match(r"([\d.]+)\s*([KMG]i?B)", phan, re.IGNORECASE)
    if not match:
        raise SystemExit(f"Khong doc duoc MemUsage: {raw!r}")
    so = float(match.group(1))
    don_vi = match.group(2).upper().replace("I", "")
    return {"KB": so / 1024, "MB": so, "GB": so * 1024}[don_vi]


def _mem_available_mb() -> float | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    text = meminfo.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", text, re.MULTILINE)
    return round(int(match.group(1)) / 1024, 1) if match else None


def _khop_tuyen_tinh(diem: list[tuple[int, float]]) -> tuple[float, float] | None:
    if len(diem) < 2:
        return None
    n = len(diem)
    sx = sum(x for x, _ in diem)
    sy = sum(y for _, y in diem)
    sxx = sum(x * x for x, _ in diem)
    sxy = sum(x * y for x, y in diem)
    mau = n * sxx - sx * sx
    if mau == 0:
        return None
    a = (n * sxy - sx * sy) / mau
    return a, (sy - a * sx) / n


def _dang_nhap(api: str, email: str, password: str) -> str:
    status, body = _http(
        f"{api}/auth/login",
        method="POST",
        body={"email": email, "password": password},
        headers={"X-Schema-Version": "1.0"},
    )
    if status != 200 or not body:
        raise SystemExit(f"Dang nhap that bai ({status}): {body}")
    return body["data"]["access_token"]


def _tao_phien(api: str, token: str, vehicle_id: str, stt: int) -> str:
    status, body = _http(
        f"{api}/sessions",
        method="POST",
        body={"vehicle_id": vehicle_id, "input_mode": "text"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": f"ram-phien-{uuid.uuid4()}-{stt}",
        },
    )
    if status != 200 or not body:
        raise SystemExit(f"Tao phien #{stt} that bai ({status}): {body}")
    return body["data"]["session_id"]


def _chay_luot(api: str, token: str, session_id: str, cau_hoi: str, timeout: float) -> int:
    status, _ = _http(
        f"{api}/turns/text",
        method="POST",
        body={"session_id": session_id, "text": cau_hoi},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": f"ram-luot-{uuid.uuid4()}",
        },
        timeout=timeout,
    )
    return status


def _do(args: argparse.Namespace) -> dict:
    ten_container = _tim_container(args.container)
    moc = sorted({int(x) for x in args.moc.split(",") if x.strip()})
    if not moc:
        raise SystemExit("--moc rong")
    n_max = max(moc)
    if n_max > args.tran_an_toan:
        raise SystemExit(
            f"--moc toi da {n_max} vuot tran an toan {args.tran_an_toan}. "
            "MAX_SESSIONS=128/MAX_TOKENS=256 la LRU: chay qua tay se day phien cua "
            "nguoi dung that ra khoi cache. Nang tran bang --tran-an-toan neu that su can."
        )

    print(f"Container backend: {ten_container}", flush=True)
    token = _dang_nhap(args.api_base, args.email, args.password)
    print("Dang nhap: OK", flush=True)

    time.sleep(args.on_dinh_s)
    nen = _mem_container_mb(ten_container)
    mau: list[dict] = [{"n": 0, "pha": "nen", "mem_mb": round(nen, 2)}]
    print(f"[n=0] nen = {nen:.2f} MB", flush=True)

    phien: list[str] = []
    loi_luot = 0
    for i in range(1, n_max + 1):
        session_id = _tao_phien(args.api_base, token, args.vehicle_id, i)
        phien.append(session_id)
        if not args.khong_hoi:
            status = _chay_luot(args.api_base, token, session_id, args.cau_hoi, args.timeout)
            if status != 200:
                loi_luot += 1
                print(f"  ! phien #{i}: luot tra ve {status}", flush=True)

        if i in moc:
            time.sleep(args.on_dinh_s)
            mem = _mem_container_mb(ten_container)
            mau.append({"n": i, "pha": "sau_on_dinh", "mem_mb": round(mem, 2)})
            print(f"[n={i}] {mem:.2f} MB", flush=True)

    diem = [(int(m["n"]), float(m["mem_mb"])) for m in mau if int(m["n"]) > 0]
    khop = _khop_tuyen_tinh(diem)
    mb_moi_phien = round(khop[0], 3) if khop else None
    chan = round(khop[1], 2) if khop else None

    kha_dung = _mem_available_mb()
    suc_chua = None
    if mb_moi_phien is not None and mb_moi_phien > 0 and kha_dung is not None:
        suc_chua = int((kha_dung * args.he_so_an_toan) // mb_moi_phien)

    return {
        "container": ten_container,
        "che_do": "chi_tao_phien" if args.khong_hoi else "phien_co_luot",
        "cau_hoi": None if args.khong_hoi else args.cau_hoi,
        "moc": moc,
        "on_dinh_s": args.on_dinh_s,
        "samples": mau,
        "so_phien_da_tao": len(phien),
        "so_luot_loi": loi_luot,
        "mb_moi_phien": mb_moi_phien,
        "chan_mb": chan,
        "mem_available_mb": kha_dung,
        "he_so_an_toan": args.he_so_an_toan,
        "suc_chua_uoc_tinh": suc_chua,
    }


def _report_md(ket_qua: dict, manifest: dict) -> str:
    lines = [
        "# RAM bien cua backend cho moi phien tai xe",
        "",
        f"- Run id: `{manifest['run_id']}`",
        f"- May: `{manifest['platform']}`, Python `{manifest['python']}`",
        f"- Container do: `{ket_qua['container']}`",
        f"- Che do: **{ket_qua['che_do']}**, on dinh {ket_qua['on_dinh_s']}s moi moc",
        f"- Phien da tao: {ket_qua['so_phien_da_tao']} (luot loi: {ket_qua['so_luot_loi']})",
        "",
        "## So do",
        "",
        "| So phien | MEM USAGE (MB) |",
        "|---:|---:|",
    ]
    lines += [f"| {m['n']} | {m['mem_mb']} |" for m in ket_qua["samples"]]

    lines += ["", "## Ket qua khop", ""]
    if ket_qua["mb_moi_phien"] is None:
        lines.append("Chua du moc de khop - can it nhat 2 moc phan biet.")
    else:
        lines += [
            f"- **RAM bien: {ket_qua['mb_moi_phien']} MB moi phien tai xe**",
            f"- Diem chan: {ket_qua['chan_mb']} MB",
        ]
        if ket_qua["suc_chua_uoc_tinh"] is not None:
            lines.append(
                f"- Quy doi tho: ~{ket_qua['suc_chua_uoc_tinh']} phien lap day "
                f"{ket_qua['he_so_an_toan']} x MemAvailable ({ket_qua['mem_available_mb']} MB). "
                "**KHONG phai suc chua that** - CPU, so ket noi WS va khoa STT/TTS vo truoc RAM."
            )

    lines += ["", "## Diem mu", ""]
    lines += [f"- **{key}** - {text}" for key, text in _BLIND_SPOTS.items()]
    lines.append("")
    return "\n".join(lines)


def _git(*args: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=15, check=False
        )
        return proc.stdout.strip()
    except Exception:  # noqa: BLE001 - manifest thieu mot truong khong duoc giet phep do
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Do RAM bien cua backend cho moi phien tai xe")
    parser.add_argument("--api-base", default=DEFAULT_API, help=f"goc API (mac dinh {DEFAULT_API})")
    parser.add_argument("--container", default=None, help="ten container backend (mac dinh: tu tim)")
    parser.add_argument("--moc", default="1,5,10,25", help="cac moc so phien, phan tach bang dau phay")
    parser.add_argument("--vehicle-id", default="vehicle-demo-01", help="vehicle_id dua vao POST /sessions")
    parser.add_argument("--email", default="driver.demo@example.com", help="tai khoan driver demo")
    parser.add_argument("--password", default="DemoDriver123!", help="mat khau driver demo")
    parser.add_argument("--cau-hoi", default=DEFAULT_CAU_HOI, help="cau chay moi luot (PHAI la cau read-only)")
    parser.add_argument("--khong-hoi", action="store_true", help="chi tao phien, khong chay luot")
    parser.add_argument("--on-dinh-s", type=float, default=4.0, help="cho bao lau truoc khi lay mau")
    parser.add_argument("--timeout", type=float, default=90.0, help="timeout moi luot (SLM bat thi luot cham)")
    parser.add_argument("--he-so-an-toan", type=float, default=0.7, help="phan MemAvailable dam dung")
    parser.add_argument("--tran-an-toan", type=int, default=40, help="chan tren cua --moc, tranh day LRU")
    args = parser.parse_args()

    ket_qua = _do(args)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f") + "Z"
    out = RESULTS_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "suite": "ram-phien-backend",
        "run_id": run_id,
        "run_uuid": str(uuid.uuid4()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "HEAD") or "unknown",
        "git_dirty": bool(_git("status", "--porcelain")),
        "che_do": ket_qua["che_do"],
        "note": (
            "Do tu NGOAI qua HTTP + docker stats, khong dung tien trinh backend that. "
            "Phien da tao KHONG duoc don - chung tu het han sau session_ttl_hours (24h)."
        ),
        "blind_spots": _BLIND_SPOTS,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(ket_qua, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(_report_md(ket_qua, manifest), encoding="utf-8")

    print()
    print(_report_md(ket_qua, manifest))
    print(f"Da ghi: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

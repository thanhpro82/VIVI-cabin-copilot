"""Đo RAM **biên** của chiếc xe ảo thứ N khi chạy nhiều xe trong MỘT tiến trình.

Ghi một thư mục run **bất biến** dưới `eval/results/ram-nhieu-xe/<UTC-run-id>/`.

    python scripts/do_ram_nhieu_xe.py                      # 1,2,5,10,20 xe, co MQTT
    python scripts/do_ram_nhieu_xe.py --moc 1,5,10,20,40
    python scripts/do_ram_nhieu_xe.py --khong-mqtt         # chi do object state

Vì sao phải có script này khi đã có `report_resource_footprint.py`: script kia đo
**theo container** (`docker stats`), tức 1 interpreter + thư viện + đúng 1 xe = 34,3
MiB (run `20260818T152351.727412Z`). Con số đó là **trần trên** và ước thừa rất nhiều
cho thiết kế "N xe trong một tiến trình", vì phần interpreter/thư viện chỉ trả một
lần. Câu hỏi quyết định phương án multi-tenant là **độ dốc**, không phải điểm chặn —
và không script nào trong repo đo được độ dốc.

Cách đo: dựng dần `VehicleSimulator` + `SimulatorRuntime` với `vehicle_id` khác nhau,
lấy mẫu `VmRSS` tại các mốc, rồi khớp bình phương tối thiểu. Độ dốc = MB mỗi xe.

**Dọn dẹp là một phần của phép đo, không phải phần phụ.** Xe ảo publish `health`,
`state/snapshot` và `state/{domain}` với `retain=true` (`docs/mqtt_spec.md`), nên chạy
xong mà không xoá là để lại rác retained trên broker production cho hàng chục
`vehicle_id` không tồn tại. Script luôn xoá ở nhánh `finally`, kể cả khi bị Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import json
import platform
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import mqtt_topics  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.models.vehicle import DOMAINS  # noqa: E402
from src.services.mqtt_client import AiomqttClient, ensure_selector_event_loop  # noqa: E402
from src.vehicle_sim.runtime import SimulatorRuntime, will_for  # noqa: E402
from src.vehicle_sim.state import VehicleSimulator  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = REPO_ROOT / "eval" / "results" / "ram-nhieu-xe"

_BLIND_SPOTS = {
    "mot_may_mot_lan": (
        "MOT lan lay mau tren MOT may, khong phai phan phoi. Day la so de lap ngan "
        "sach may, khong phai benchmark. Chay lai tren may dich truoc khi trich."
    ),
    "python_khong_tra_ram": (
        "CPython gan nhu khong tra vung nho da cap ve cho OS, nen VmRSS chi tang. "
        "Vi vay do doc lay tu khop tuyen tinh tren NHIEU moc, khong phai hieu cua "
        "hai diem - hieu hai diem dinh ca nhieu allocator lan nhieu GC."
    ),
    "moi_xe_mot_ket_noi": (
        "Moi xe o day co MQTT client rieng, giong het kien truc hien tai (mot tien "
        "trinh = mot xe = mot ket noi). Thiet ke multi-tenant co the dung CHUNG mot "
        "ket noi cho N xe, khi do do doc that con thap hon so nay. Nen day van la "
        "tran tren, chi la tran chat hon nhieu so voi con so 34,3 MiB/container."
    ),
    "chua_do_phia_backend": (
        "Chi do phia XE AO. Backend cung ton them cho moi xe: mot VehicleStateCache "
        "(subscribe rieng), mot UiPolicyEmitter, va moi phien tai xe con keo theo mot "
        "checkpoint LangGraph InMemorySaver. Phan do nhieu kha nang LON HON phan nay "
        "va chua ai do. Dung lap ngan sach chi bang con so o day."
    ),
    "khong_co_tai": (
        "Xe dung yen, chi co heartbeat - khong lenh, khong chu ky tu chay. Do luc co "
        "tai se cao hon, nhung phan chenh la buffer tam chu khong phai chi phi thuong "
        "truc, nen no khong doi ket luan ve suc chua."
    ),
}


def _rss() -> dict[str, object]:
    """Đọc VmRSS/VmHWM. Linux đọc /proc; nơi khác thử psutil rồi mới chịu thua."""
    status = Path("/proc/self/status")
    if status.exists():
        text = status.read_text(encoding="utf-8", errors="replace")
        cur = re.search(r"^VmRSS:\s+(\d+)\s+kB", text, re.MULTILINE)
        hwm = re.search(r"^VmHWM:\s+(\d+)\s+kB", text, re.MULTILINE)
        return {
            "rss_mb": round(int(cur.group(1)) / 1024, 2) if cur else -1.0,
            "peak_mb": round(int(hwm.group(1)) / 1024, 2) if hwm else -1.0,
            "nguon": "/proc/self/status",
        }
    try:
        import psutil  # noqa: PLC0415 - phụ thuộc tuỳ chọn, chỉ dùng ngoài Linux
    except ImportError:
        raise SystemExit(
            "Khong doc duoc RSS: may nay khong co /proc va cung khong co psutil.\n"
            "Script thiet ke cho may dich Linux (VPS). Tren Windows: pip install psutil."
        ) from None
    info = psutil.Process().memory_info()
    return {"rss_mb": round(info.rss / 1024 / 1024, 2), "peak_mb": -1.0, "nguon": "psutil"}


def _mem_available_mb() -> float | None:
    """MemAvailable của máy — để quy ra sức chứa. None nếu không phải Linux."""
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    text = meminfo.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", text, re.MULTILINE)
    return round(int(match.group(1)) / 1024, 1) if match else None


def _khop_tuyen_tinh(diem: list[tuple[int, float]]) -> tuple[float, float] | None:
    """Bình phương tối thiểu y = a*x + b. None nếu chưa đủ 2 mốc phân biệt."""
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


async def _don_retained(client: AiomqttClient, vehicle_id: str) -> None:
    """Xoá mọi retained message của một xe thử nghiệm.

    Payload rỗng + retain=True là cách xoá theo đặc tả MQTT — xem docstring của
    `MqttPort.publish`. Bỏ bước này là để lại rác vĩnh viễn trên broker.
    """
    topics = [
        mqtt_topics.health(vehicle_id),
        mqtt_topics.snapshot(vehicle_id),
        *(mqtt_topics.domain_state(vehicle_id, domain) for domain in DOMAINS),
    ]
    for topic in topics:
        with contextlib.suppress(Exception):
            await client.publish(topic, None, qos=1, retain=True)


async def _do(args: argparse.Namespace) -> dict:
    settings = get_settings()
    moc = sorted({int(x) for x in args.moc.split(",") if x.strip()})
    if not moc:
        raise SystemExit("--moc rong")
    n_max = max(moc)

    gc.collect()
    nen = {"n": 0, "pha": "nen", **_rss()}
    mau: list[dict] = [nen]
    print(f"[n=0] nen = {nen['rss_mb']} MB", flush=True)

    dang_chay: list[tuple[SimulatorRuntime | None, AiomqttClient | None, str]] = []
    giu_object: list[VehicleSimulator] = []
    try:
        for i in range(1, n_max + 1):
            vehicle_id = f"{args.prefix}{i:03d}"
            sim = VehicleSimulator(vehicle_id)
            giu_object.append(sim)
            if args.khong_mqtt:
                dang_chay.append((None, None, vehicle_id))
            else:
                client = AiomqttClient(
                    settings.mqtt_url,
                    # clean_session=True (khác production): phiên thử nghiệm không
                    # được để lại session bền trên broker sau khi script thoát.
                    client_id=f"vehicle-simulator-{vehicle_id}",
                    username=settings.mqtt_simulator_username or None,
                    password=settings.simulator_password() or None,
                    clean_session=True,
                    keepalive=30,
                    will=will_for(vehicle_id),
                )
                runtime = SimulatorRuntime(
                    sim,
                    client,
                    heartbeat_interval_s=settings.mqtt_heartbeat_interval_s,
                    sim_control_enabled=False,
                )
                await client.start()
                await runtime.start()
                dang_chay.append((runtime, client, vehicle_id))

            if i in moc:
                await asyncio.sleep(args.on_dinh_s)
                gc.collect()
                diem = {"n": i, "pha": "sau_on_dinh", **_rss()}
                mau.append(diem)
                print(f"[n={i}] {diem['rss_mb']} MB (dinh {diem['peak_mb']} MB)", flush=True)
    finally:
        co_mqtt = [x for x in dang_chay if x[1] is not None]
        if co_mqtt:
            print(f"Don {len(co_mqtt)} xe thu nghiem...", flush=True)
        for runtime, client, vehicle_id in reversed(co_mqtt):
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await runtime.stop()
            if client is not None:
                await _don_retained(client, vehicle_id)
                with contextlib.suppress(Exception):
                    await client.stop()

    diem_khop = [(int(m["n"]), float(m["rss_mb"])) for m in mau if int(m["n"]) > 0]
    khop = _khop_tuyen_tinh(diem_khop)
    mb_moi_xe = round(khop[0], 3) if khop else None
    chan = round(khop[1], 2) if khop else None

    kha_dung = _mem_available_mb()
    suc_chua = None
    if mb_moi_xe is not None and mb_moi_xe > 0 and kha_dung is not None:
        suc_chua = int((kha_dung * args.he_so_an_toan) // mb_moi_xe)

    return {
        "che_do": "khong_mqtt" if args.khong_mqtt else "co_mqtt",
        "moc": moc,
        "on_dinh_s": args.on_dinh_s,
        "samples": mau,
        "mb_moi_xe": mb_moi_xe,
        "chan_mb": chan,
        "mem_available_mb": kha_dung,
        "he_so_an_toan": args.he_so_an_toan,
        "suc_chua_uoc_tinh": suc_chua,
    }


def _report_md(ket_qua: dict, manifest: dict) -> str:
    lines = [
        "# RAM bien cua xe ao khi chay nhieu xe trong mot tien trinh",
        "",
        f"- Run id: `{manifest['run_id']}`",
        f"- May: `{manifest['platform']}`, Python `{manifest['python']}`",
        f"- Commit: `{manifest['git_commit'][:12]}` (dirty: {manifest['git_dirty']})",
        f"- Che do: **{ket_qua['che_do']}**, on dinh {ket_qua['on_dinh_s']}s moi moc",
        "",
        "## So do",
        "",
        "| So xe | RSS (MB) | Dinh (MB) |",
        "|---:|---:|---:|",
    ]
    lines += [f"| {m['n']} | {m['rss_mb']} | {m['peak_mb']} |" for m in ket_qua["samples"]]

    lines += ["", "## Ket qua khop", ""]
    if ket_qua["mb_moi_xe"] is None:
        lines.append("Chua du moc de khop - can it nhat 2 moc phan biet.")
    else:
        lines += [
            f"- **RAM bien: {ket_qua['mb_moi_xe']} MB cho moi xe them vao**",
            f"- Diem chan (chi phi tra mot lan): {ket_qua['chan_mb']} MB",
        ]
        if ket_qua["suc_chua_uoc_tinh"] is not None:
            lines.append(
                f"- Suc chua uoc tinh: **~{ket_qua['suc_chua_uoc_tinh']} xe** "
                f"(MemAvailable {ket_qua['mem_available_mb']} MB x he so an toan "
                f"{ket_qua['he_so_an_toan']})"
            )
        else:
            lines.append("- Suc chua: khong tinh duoc (khong doc duoc MemAvailable - may khong phai Linux).")

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
    parser = argparse.ArgumentParser(description="Do RAM bien cua xe ao thu N trong mot tien trinh")
    parser.add_argument("--moc", default="1,2,5,10,20", help="cac moc so xe, phan tach bang dau phay")
    parser.add_argument("--prefix", default="ram-probe-", help="tien to vehicle_id thu nghiem")
    parser.add_argument("--on-dinh-s", type=float, default=3.0, help="cho bao lau truoc khi lay mau")
    parser.add_argument("--khong-mqtt", action="store_true", help="khong noi broker, chi do object state")
    parser.add_argument("--he-so-an-toan", type=float, default=0.7, help="phan MemAvailable dam dung")
    args = parser.parse_args()

    if not args.khong_mqtt:
        ensure_selector_event_loop()
    ket_qua = asyncio.run(_do(args))

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f") + "Z"
    out = RESULTS_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "suite": "ram-nhieu-xe",
        "run_id": run_id,
        "run_uuid": str(uuid.uuid4()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "HEAD") or "unknown",
        "git_dirty": bool(_git("status", "--porcelain")),
        "che_do": ket_qua["che_do"],
        "note": (
            "Do phia XE AO trong mot tien trinh. KHONG gom chi phi phia backend cho moi xe "
            "(VehicleStateCache, UiPolicyEmitter, checkpoint LangGraph) - phan do chua ai do."
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

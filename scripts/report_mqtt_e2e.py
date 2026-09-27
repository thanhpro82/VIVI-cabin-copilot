"""Sinh báo cáo kết quả bộ test MQTT end-to-end.

Deliverable của ticket "MQTT End-to-End Integration Test". Chạy pytest, đọc
junit XML, rồi ghi một thư mục run **bất biến** dưới
`eval/results/mqtt-e2e/<UTC-run-id>/`.

    python scripts/report_mqtt_e2e.py                  # chỉ tầng L1 (không cần broker)
    python scripts/report_mqtt_e2e.py --with-contract  # thêm tầng L2, cần Mosquitto
    python scripts/report_mqtt_e2e.py --with-l3        # thêm tầng L3, cần Mosquitto + 2 tiến trình

Vì sao theo khuôn `eval/results/<suite>/<run-id>/`: `CLAUDE.md` quy định thư mục
run là bất biến và **mọi claim định lượng phải truy được về một run id**. Báo cáo
này có claim định lượng (số case pass theo AC, latency), nên nó thuộc diện đó.
Đẻ ra một format thứ hai chỉ để né kỷ luật ấy là đúng kiểu cắt góc mà đề bài cấm.

Không viết pytest plugin: dùng `--junitxml` có sẵn, phân loại tầng/AC bằng đường
dẫn file test. Đổi lại `junit.xml` là bằng chứng **thô** mà người khác kiểm chứng
lại được, không phải thứ script này tự thuật.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = REPO_ROOT / "eval" / "results" / "mqtt-e2e"

#: Ánh xạ file test → (tầng, AC nó phục vụ). Giữ tường minh chứ không đoán theo
#: tên, để khi thêm file mới mà quên khai thì báo cáo nói "unmapped" chứ không
#: âm thầm xếp nhầm.
_FILE_MAP: dict[str, tuple[str, str]] = {
    "test_mqtt_e2e_inmemory.py": ("L1-inmemory", "AC1-chain+AC2-topic"),
    "test_mqtt_idempotency.py": ("L1-inmemory", "AC3-idempotency"),
    "test_mqtt_stale_state.py": ("L1-inmemory", "AC3-stale"),
    "test_mqtt_schemas.py": ("L1-inmemory", "AC2-schema"),
    "test_vehicle_gateway.py": ("L1-inmemory", "AC1-chain"),
    "test_mqtt_roundtrip.py": ("L1-inmemory", "AC1-chain"),
    "test_simulator.py": ("L0-unit", "AC3-state_version"),
    "test_bounded_cache.py": ("L0-unit", "AC3-idempotency"),
    "test_ws_engineer_realtime.py": ("L1-inmemory", "AC3-realtime"),
    "test_vehicle_state.py": ("L1-inmemory", "AC1-chain"),
    # Tên file là `test_health.py`, không phải `test_healthz.py`. Cả bảng này lẫn
    # `_TARGETS` từng ghi tên cũ, nên script chết ngay ở `pytest` với
    # "file or directory not found" — tức bộ sinh evidence hỏng im lặng cho tới
    # khi có người chạy lại nó.
    "test_health.py": ("L1-inmemory", "AC1-chain"),
    "test_contract_mosquitto.py": ("L2-mosquitto", "AC1-chain+AC3-idempotency"),
    "test_l3_two_process.py": ("L3-two-process", "AC1-chain+AC3-realtime"),
    "test_vehicle_state_cache_restart.py": ("L1-inmemory", "AC3-state_version"),
    "test_compose_healthcheck.py": ("L0-unit", "AC1-chain"),
}

_TARGETS = [
    "tests/test_vehicle/",
    "tests/test_api/test_vehicle_state.py",
    "tests/test_api/test_health.py",
    "tests/test_api/test_ws_engineer_realtime.py",
]

#: Điểm mù của từng tầng. Ghi ra báo cáo chứ không giấu — một bộ test xanh mà
#: không nói rõ nó KHÔNG chứng minh được gì thì dễ bị đọc thành "đã phủ hết".
_BLIND_SPOTS = {
    "L0-unit": "Không nói gì về vận chuyển: không broker, không serialize.",
    "L1-inmemory": (
        "InMemoryBroker gọi handler đồng bộ ngay trong publish nên hoàn toàn tất định — "
        "0 flaky, nhưng cũng KHÔNG BAO GIỜ tạo ra xen kẽ thời gian thật. "
        "Không chứng minh được: QoS 1 duplicate của broker thật, retain qua restart, "
        "ACL, Last Will, clean_session, hay reconnect."
    ),
    "L2-mosquitto": (
        "Broker thật nhưng vẫn trong một tiến trình pytest: không có HTTP/WS thật, "
        "không có backend và simulator chạy như hai tiến trình riêng."
    ),
    "L3-two-process": (
        "Hai tiến trình thật nhưng CÙNG một máy, cùng một venv, cùng loopback. "
        "KHÔNG chứng minh: image Docker, topology docker-compose, hành vi khi mạng "
        "phân mảnh hay có độ trễ, và nhiều xe cùng lúc. Thời gian khởi động ghi ở "
        "đây là số đo một lần trên máy dev — nó phụ thuộc nặng vào việc model "
        "STT/TTS có sẵn hay chưa (backend warm singleton trong lifespan)."
    ),
}


def _run_pytest(junit_path: Path, *, with_contract: bool, with_l3: bool) -> int:
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    # Cả L2 lẫn L3 đều mang marker `slow`, nên bật một trong hai là phải bỏ bộ lọc
    # `not slow` — quên chỗ này thì cờ được truyền, script chạy xanh, và tầng vừa
    # bật lại **không có case nào** trong báo cáo.
    marker = "not integration" if (with_contract or with_l3) else "not slow and not integration"
    command = [
        sys.executable,
        "-m",
        "pytest",
        *_TARGETS,
        "-m",
        marker,
        f"--junitxml={junit_path}",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    # Mỗi tầng có cổng riêng của nó, và cổng đó phải đặt Ở ĐÂY chứ không bắt người
    # chạy nhớ export: cờ dòng lệnh nói "tôi muốn tầng này", việc bật nó là chuyện
    # của script. `MQTT_ENABLED` phải là `false` cho chính tiến trình pytest —
    # tầng L3 tự đặt `true` cho hai tiến trình con mà nó sinh ra.
    env = os.environ.copy()
    env.setdefault("MQTT_ENABLED", "false")
    if with_contract:
        env["MQTT_CONTRACT_TESTS"] = "1"
    if with_l3:
        env["MQTT_L3_TESTS"] = "1"

    print("Chạy:", " ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env)  # noqa: S603
    return completed.returncode


def _module_of(classname: str, file_hint: str) -> str:
    """Suy ra tên file test từ một `<testcase>`.

    pytest **không** ghi thuộc tính `file` trong junit XML mặc định, chỉ có
    `classname` dạng dotted path: `tests.test_vehicle.test_mqtt_idempotency` cho
    hàm ở mức module, và thêm một mức nữa (`....TestFoo`) nếu test nằm trong
    class. Nên duyệt ngược từng thành phần thay vì lấy cứng `[-1]` hay `[-2]`.
    """
    if file_hint:
        return Path(file_hint).name
    for part in reversed(classname.split(".")):
        if part.startswith("test_"):
            return f"{part}.py"
    return ""


def _classify(classname: str, file_hint: str) -> tuple[str, str]:
    return _FILE_MAP.get(_module_of(classname, file_hint), ("unmapped", "unmapped"))


def _parse_junit(junit_path: Path) -> list[dict]:
    root = ET.parse(junit_path).getroot()
    rows: list[dict] = []
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        file_hint = case.get("file", "")
        module = _module_of(classname, file_hint)
        layer, ac = _classify(classname, file_hint)
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        rows.append(
            {
                "name": case.get("name", ""),
                "module": module,
                "classname": classname,
                "layer": layer,
                "ac": ac,
                "status": status,
                "duration_s": round(float(case.get("time", "0") or 0), 4),
            }
        )
    return rows


def _aggregate(rows: list[dict]) -> dict:
    def tally(subset: list[dict]) -> dict:
        return {
            "total": len(subset),
            "passed": sum(1 for row in subset if row["status"] == "passed"),
            "failed": sum(1 for row in subset if row["status"] == "failed"),
            "skipped": sum(1 for row in subset if row["status"] == "skipped"),
            "duration_s": round(sum(row["duration_s"] for row in subset), 3),
        }

    by_layer = {
        layer: tally([row for row in rows if row["layer"] == layer]) for layer in sorted({row["layer"] for row in rows})
    }
    by_ac = {ac: tally([row for row in rows if row["ac"] == ac]) for ac in sorted({row["ac"] for row in rows})}
    return {"overall": tally(rows), "by_layer": by_layer, "by_ac": by_ac}


def _git(*args: str) -> str:
    try:
        return subprocess.run(  # noqa: S603
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _git_dirty_excluding(run_dir: Path) -> bool:
    """Cây làm việc có bẩn không, **không tính thư mục output của chính lần chạy này**.

    `main()` cố ý `mkdir` thư mục run TRƯỚC khi chạy pytest (xem chú thích ở đó), nên
    tới lúc dựng manifest thì `git status --porcelain` luôn thấy ít nhất một dòng `??`
    trỏ vào đúng thư mục ta vừa tạo. Bản trước dùng thẳng `bool(_git("status", ...))`
    nên `git_dirty` **luôn là `True`** ở mọi lần chạy, kể cả khi cây hoàn toàn sạch —
    tức một trường tính toàn vẹn không phân biệt được điều nó sinh ra để phân biệt.
    Tệ hơn không có: nó khiến người đọc nghi ngờ một bản evidence hợp lệ.

    Lọc theo đường dẫn chứ không phải bỏ hết dòng `??`: một file lạ chưa commit ở nơi
    khác vẫn phải làm cây bẩn, vì đó chính là thứ trường này tồn tại để tố giác.
    """
    status = _git("status", "--porcelain")
    if status in ("", "unknown"):
        return False
    try:
        relative = run_dir.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        relative = run_dir.as_posix()
    remaining = [line for line in status.splitlines() if line.strip() and relative not in line.replace("\\", "/")]
    return bool(remaining)


def _manifest(run_id: str, *, with_contract: bool, with_l3: bool, exit_code: int, run_dir: Path) -> dict:
    layers = ["L0-unit", "L1-inmemory"]
    if with_contract:
        layers.append("L2-mosquitto")
    if with_l3:
        layers.append("L3-two-process")
    return {
        "run_id": run_id,
        "suite": "mqtt-e2e",
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": _git_dirty_excluding(run_dir),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "layers_run": layers,
        "pytest_exit_code": exit_code,
        "note": (
            "Thời gian trong case_results.jsonl là số đo MỘT lần chạy trên máy dev, "
            "KHÔNG phải benchmark. Không dùng làm bằng chứng hiệu năng."
        ),
        "blind_spots": {layer: _BLIND_SPOTS[layer] for layer in layers},
    }


def _report_md(manifest: dict, metrics: dict, rows: list[dict]) -> str:
    overall = metrics["overall"]
    lines = [
        f"# Báo cáo MQTT End-to-End — run `{manifest['run_id']}`",
        "",
        f"- Commit: `{manifest['git_commit'][:12]}` trên `{manifest['git_branch']}`"
        + (" (**cây làm việc bẩn**)" if manifest["git_dirty"] else ""),
        f"- Python {manifest['python']} · {manifest['platform']}",
        f"- Tầng đã chạy: {', '.join(manifest['layers_run'])}",
        "",
        "## Tổng hợp",
        "",
        f"**{overall['passed']}/{overall['total']} pass**, {overall['failed']} fail, "
        f"{overall['skipped']} skip, {overall['duration_s']}s.",
        "",
        "## Theo acceptance criteria",
        "",
        "| AC | Pass | Fail | Skip |",
        "|---|---:|---:|---:|",
    ]
    for ac, tally in metrics["by_ac"].items():
        lines.append(f"| {ac} | {tally['passed']} | {tally['failed']} | {tally['skipped']} |")

    lines += ["", "## Theo tầng", "", "| Tầng | Pass | Fail | Skip | Giây |", "|---|---:|---:|---:|---:|"]
    for layer, tally in metrics["by_layer"].items():
        lines.append(
            f"| {layer} | {tally['passed']} | {tally['failed']} | {tally['skipped']} | {tally['duration_s']} |"
        )

    lines += ["", "## Điểm mù — bộ test này KHÔNG chứng minh được gì", ""]
    for layer, text in manifest["blind_spots"].items():
        lines.append(f"- **{layer}**: {text}")

    failures = [row for row in rows if row["status"] == "failed"]
    lines += ["", "## Case thất bại", ""]
    lines.append("\n".join(f"- `{row['module']}::{row['name']}`" for row in failures) if failures else "Không có.")

    unmapped = [row for row in rows if row["layer"] == "unmapped"]
    if unmapped:
        lines += [
            "",
            "## Case chưa được phân loại",
            "",
            f"{len(unmapped)} case thuộc file chưa khai trong `_FILE_MAP` của "
            "`scripts/report_mqtt_e2e.py` — bảng theo AC ở trên **chưa tính** chúng:",
            "",
            *sorted({f"- `{row['module'] or row['classname']}`" for row in unmapped}),
        ]

    lines += [
        "",
        "---",
        "",
        f"> {manifest['note']}",
        ">",
        "> Bằng chứng thô: `junit.xml` trong cùng thư mục. Thư mục run là bất biến —",
        "> muốn số mới thì chạy lại script, không sửa file cũ.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sinh báo cáo bộ test MQTT E2E")
    parser.add_argument(
        "--with-contract",
        action="store_true",
        help="chạy thêm tầng L2 (cần Mosquitto thật; script tự đặt MQTT_CONTRACT_TESTS=1)",
    )
    parser.add_argument(
        "--with-l3",
        action="store_true",
        help="chạy thêm tầng L3 hai tiến trình (cần Mosquitto thật; script tự đặt MQTT_L3_TESTS=1)",
    )
    parser.add_argument(
        "--junit",
        type=Path,
        help="dùng lại junit XML có sẵn thay vì chạy pytest",
    )
    args = parser.parse_args()

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = RESULTS_ROOT / run_id
    # Bất biến: dựng thư mục TRƯỚC khi chạy test để hai lần chạy song song không
    # giẫm lên nhau, và để lỗi trùng id nổ ngay chứ không phải sau vài phút.
    run_dir.mkdir(parents=True, exist_ok=False)

    if args.junit:
        junit_path = args.junit
        exit_code = 0
        print(f"Dùng lại junit có sẵn: {junit_path}")
    else:
        junit_path = run_dir / "junit.xml"
        exit_code = _run_pytest(junit_path, with_contract=args.with_contract, with_l3=args.with_l3)

    rows = _parse_junit(junit_path)
    metrics = _aggregate(rows)
    manifest = _manifest(
        run_id, with_contract=args.with_contract, with_l3=args.with_l3, exit_code=exit_code, run_dir=run_dir
    )

    if args.junit and junit_path != run_dir / "junit.xml":
        (run_dir / "junit.xml").write_text(junit_path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "report.md").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_report_md(manifest, metrics, rows))

    overall = metrics["overall"]
    print(f"\nĐã ghi {run_dir.relative_to(REPO_ROOT)}")
    print(f"{overall['passed']}/{overall['total']} pass, {overall['failed']} fail")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

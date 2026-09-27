"""Diễn tập offline: chạy trọn luồng P0 với mọi kết nối ra ngoài loopback bị chặn.

    .\\.venv\\Scripts\\python.exe scripts\\offline_drill.py

Sinh `eval/results/offline-drill/<UTC-run-id>/` gồm `manifest.json`,
`case_results.jsonl`, `metrics.json`, `report.md` — cùng khuôn với
`scripts/report_mqtt_e2e.py`.

ADR-001 nói "No network at runtime". Cho tới hôm nay đó là tuyên bố chưa ai kiểm: không
test, không run dir. Script này là nửa kiểm được của nó — xem `src/offline_guard.py`
cho ranh giới, và mục `blind_spots` của manifest cho phần nó **không** chứng minh.

Ca đầu tiên luôn là một lần cố tình gọi ra ngoài. Nếu ca ấy không bị chặn thì cả bản
báo cáo vô giá trị, và script thoát khác 0 — một diễn tập không thể thất bại thì không
phải bằng chứng.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_mqtt_e2e import _git_dirty_excluding  # noqa: E402  — dùng lại, xem `_manifest`

REPO = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO / "eval" / "results" / "offline-drill"
WARM_SAMPLE = REPO / "tests" / "fixtures" / "voice" / "warm_sample.wav"

#: Tắt MQTT cho drill: broker chạy trên loopback nên nó không nói gì về egress, còn bật
#: lên mà không có broker thì mỗi `TestClient(app)` treo 10 giây chờ vô ích. Ghi vào
#: `blind_spots` chứ không giấu.
_ENV = {"MQTT_ENABLED": "false", "SLM_ENABLED": "false"}

_BLIND_SPOTS = {
    "native": (
        "Cổng Python không thấy kết nối do mã native mở thẳng qua syscall "
        "(`onnxruntime`, `faiss`, `sherpa-onnx` đều là C++, và `onnxruntime` 1.28 nạp "
        "sẵn `AzureExecutionProvider`). Lớp `ket_noi_os` hỏi HĐH nên thấy cả C++, nhưng "
        "nó **lấy mẫu** một lần sau mỗi ca: một kết nối chớp nhoáng trong lúc ca chạy "
        "vẫn lọt, và nó chỉ thấy TCP/UDP. Cả hai lớp đều chỉ nói về TIẾN TRÌNH NÀY — "
        "'không byte nào rời máy' cần diễn tập ngắt card mạng thật."
    ),
    "mqtt": (
        "Chạy với MQTT_ENABLED=false. Broker nói chuyện qua loopback nên nó không thể "
        "là nguồn egress, nhưng nghĩa là chặng lệnh -> MQTT -> simulator không nằm "
        "trong lượt đo này."
    ),
    "in_process": (
        "Chạy trong MỘT tiến trình qua TestClient, không phải image Docker hay topology "
        "docker-compose. Không nói gì về việc container có tự gọi ra ngoài lúc khởi động."
    ),
    "cold_start": (
        "Model STT/TTS/embedder đã có sẵn trên đĩa. Drill chứng minh runtime không tải "
        "thêm gì; nó KHÔNG chứng minh được máy chưa từng cần mạng để có model."
    ),
}


@dataclass
class KetQua:
    ten: str
    mo_ta: str
    dat: bool
    ms: float
    egress: list[dict] = field(default_factory=list)
    #: Kết nối HĐH quan sát được sau ca, ngoài loopback. Thấy cả socket do C++ mở.
    ket_noi_os: list[str] = field(default_factory=list)
    loi: str | None = None
    ghi_chu: str | None = None


def _chay(ten: str, mo_ta: str, ham, *, mong_doi_chan: bool = False) -> KetQua:
    """Chạy một ca trong cổng chặn và ghi lại mọi lần thử đi ra ngoài."""
    from src.offline_guard import CongChanEgress, ket_noi_ngoai_loopback

    bat_dau = time.perf_counter()
    loi: str | None = None
    ghi_chu: str | None = None
    with CongChanEgress() as cong:
        try:
            ghi_chu = ham()
        except Exception as exc:  # noqa: BLE001 — mọi lỗi đều là dữ liệu của drill
            loi = f"{type(exc).__name__}: {exc}"
    ms = (time.perf_counter() - bat_dau) * 1000
    # Chụp bảng kết nối NGAY sau ca, còn trong cổng thì đã thoát: kết nối do mã native
    # mở không đi qua cổng Python nên đây là chỗ duy nhất thấy được nó.
    ket_noi_os = ket_noi_ngoai_loopback()

    egress = [{"kieu": t.kieu, "dich": t.dich, "goi_tu": t.goi_tu()} for t in cong.lan_thu]
    if mong_doi_chan:
        # Ca tự kiểm: PHẢI có đúng một lần bị chặn, nếu không cổng đã hỏng.
        dat = len(egress) == 1 and loi is not None
    else:
        dat = loi is None and not egress and not ket_noi_os
    return KetQua(ten=ten, mo_ta=mo_ta, dat=dat, ms=ms, egress=egress, ket_noi_os=ket_noi_os, loi=loi, ghi_chu=ghi_chu)


# --- Cac ca -----------------------------------------------------------------


def _ca_tu_kiem() -> str:
    import socket

    socket.getaddrinfo("huggingface.co", 443)
    return "không bao giờ tới đây"


def _ca_nap_stt() -> str:
    from src.services.voice import get_stt_engine

    get_stt_engine()
    return "sherpa-onnx Zipformer nạp từ đĩa"


def _ca_stt() -> str:
    from src.services.voice import transcribe_raw

    ket_qua = transcribe_raw(WARM_SAMPLE.read_bytes())
    return f"transcript={ket_qua.text!r}"


def _ca_tts() -> str:
    from src.services.voice import synthesize_wav

    wav = synthesize_wav("Áp suất lốp khuyến nghị là hai trăm sáu mươi ki lô pát can.")
    return f"{len(wav)} byte WAV"


def _ca_rag() -> str:
    # Đi qua đúng hai singleton `@lru_cache` của đường chạy thật (`rag_node`), không
    # dựng retriever riêng: chỗ có khả năng tải model là `E5Embedder`, và nó nằm ở đây.
    from src.agents.nodes.rag_node import _default_embedder, _default_retriever

    ket_qua = _default_retriever().search("áp suất lốp khi lốp nguội là bao nhiêu", _default_embedder())
    return f"{len(ket_qua)} evidence, top chunk={ket_qua[0].chunk_id if ket_qua else 'không có'}"


def _ca_luot_so_tay() -> str:
    return _luot_text("Áp suất lốp khi lốp nguội là bao nhiêu?")


def _ca_luot_dieu_khien() -> str:
    return _luot_text("Đặt điều hòa 24 độ")


def _luot_text(cau: str) -> str:
    """Một lượt `POST /turns/text` thật, đi qua auth + session + graph."""
    from fastapi.testclient import TestClient

    from src.main import app

    with TestClient(app) as client:
        # `X-Schema-Version` bắt buộc **kể cả** ở login (`require_schema_version`), không
        # chỉ ở các route sau khi đã có token.
        schema = {"X-Schema-Version": "1.0"}
        dang_nhap = client.post(
            "/api/v1/auth/login",
            json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
            headers=schema,
        )
        if dang_nhap.status_code != 200:
            raise RuntimeError(f"login {dang_nhap.status_code}: {dang_nhap.text[:200]}")
        token = dang_nhap.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}", **schema}

        # `/sessions` cũng đòi `Idempotency-Key` — khoá phải **khác** khoá của lượt nói,
        # nếu không lượt thứ hai tái dùng bản ghi của lần tạo phiên.
        phien = client.post(
            "/api/v1/sessions",
            json={"vehicle_id": "veh_drill_01", "input_mode": "text"},
            headers={**headers, "Idempotency-Key": f"drill-session-{abs(hash(cau))}"},
        )
        if phien.status_code not in (200, 201):
            raise RuntimeError(f"sessions {phien.status_code}: {phien.text[:200]}")
        session_id = phien.json()["data"]["session_id"]

        tra_loi = client.post(
            "/api/v1/turns/text",
            json={"session_id": session_id, "text": cau},
            headers={**headers, "Idempotency-Key": f"drill-{abs(hash(cau))}"},
        )
        if tra_loi.status_code != 200:
            raise RuntimeError(f"turns/text {tra_loi.status_code}: {tra_loi.text[:200]}")
        data = tra_loi.json()["data"]
        phan_hoi = data.get("response") or {}
        # Ghi cả số citation và độ dài câu trả lời: một lượt "completed" mà 0 citation và
        # câu trả lời rỗng vẫn là hỏng, chỉ là hỏng im lặng — báo cáo phải nhìn ra được.
        return (
            f"status={data.get('status')} citations={len(phan_hoi.get('citations') or [])} "
            f"steps={len((data.get('action_plan') or {}).get('steps') or [])} "
            f"display_text={len(phan_hoi.get('display_text') or '')} ký tự"
        )


CAC_CA = [
    ("guard_self_test", "Cố tình phân giải huggingface.co — PHẢI bị chặn", _ca_tu_kiem, True),
    ("nap_stt", "Nạp engine sherpa-onnx Zipformer", _ca_nap_stt, False),
    ("stt", "Chuyển warm_sample.wav thành chữ", _ca_stt, False),
    ("tts", "Tổng hợp giọng Piper", _ca_tts, False),
    ("rag", "Truy hồi FAISS + embedder E5 trên index VF9", _ca_rag, False),
    ("luot_so_tay", "POST /turns/text — câu hỏi sổ tay (RAG)", _ca_luot_so_tay, False),
    ("luot_dieu_khien", "POST /turns/text — lệnh điều khiển S1", _ca_luot_dieu_khien, False),
]


# --- Bao cao ----------------------------------------------------------------


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO).stdout.strip()
    except OSError:
        return ""


def _quan_sat_os() -> bool:
    from src.offline_guard import quan_sat_duoc_ket_noi

    return quan_sat_duoc_ket_noi()


def _manifest(run_id: str, rows: list[KetQua], run_dir: Path) -> dict:
    return {
        "suite": "offline-drill",
        "run_id": run_id,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        # Dùng lại `_git_dirty_excluding` của `report_mqtt_e2e` chứ không viết lần hai:
        # nó đã giải đúng cái bẫy này (thư mục run tự làm cây bẩn ở mọi lần chạy, khiến
        # một trường toàn vẹn không phân biệt được điều nó sinh ra để phân biệt).
        "git_dirty": _git_dirty_excluding(run_dir),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "env": _ENV,
        "cases": len(rows),
        "passed": sum(1 for r in rows if r.dat),
        # "Không đo được" khác "đã đo và sạch" — manifest phải phân biệt, nếu không một
        # máy thiếu psutil sẽ cho ra bản báo cáo trông y hệt một máy đã kiểm đủ.
        "quan_sat_tang_os": _quan_sat_os(),
        "note": (
            "Thời gian trong case_results.jsonl là số đo MỘT lần trên máy dev, KHÔNG phải "
            "benchmark. Drill này chứng minh không thành phần Python nào gọi ra ngoài "
            "loopback; xem blind_spots cho phần nó không chứng minh."
        ),
        "blind_spots": _BLIND_SPOTS,
    }


def _report_md(manifest: dict, rows: list[KetQua]) -> str:
    dong = [
        f"# Diễn tập offline — run `{manifest['run_id']}`",
        "",
        f"- Commit: `{manifest['git_commit'][:12]}` trên `{manifest['git_branch']}`"
        + (" (**cây làm việc bẩn**)" if manifest["git_dirty"] else ""),
        f"- Python {manifest['python']} · {manifest['platform']}",
        f"- Env: {', '.join(f'{k}={v}' for k, v in manifest['env'].items())}",
        f"- Kết quả: **{manifest['passed']}/{manifest['cases']}** ca đạt",
        f"- Quan sát tầng HĐH: {'có' if manifest['quan_sat_tang_os'] else '**KHÔNG** — cột cuối vô nghĩa'}",
        "",
        "| Ca | Mô tả | Đạt | ms | Python thử ra ngoài | HĐH thấy kết nối ngoài |",
        "|---|---|:--:|--:|---|---|",
    ]
    for r in rows:
        ra = ", ".join(f"`{e['kieu']} {e['dich']}`" for e in r.egress) or "—"
        os_ = ", ".join(f"`{c}`" for c in r.ket_noi_os) or "—"
        dong.append(f"| `{r.ten}` | {r.mo_ta} | {'✅' if r.dat else '❌'} | {r.ms:.0f} | {ra} | {os_} |")
    dong += ["", "## Điểm mù", ""]
    for ten, text in manifest["blind_spots"].items():
        dong.append(f"- **{ten}** — {text}")
    dong += ["", f"> {manifest['note']}", ""]
    return "\n".join(dong)


def main() -> int:
    os.environ.update(_ENV)
    if not WARM_SAMPLE.is_file():
        print(f"thiếu {WARM_SAMPLE}", file=sys.stderr)
        return 2

    rows: list[KetQua] = []
    for ten, mo_ta, ham, mong_doi_chan in CAC_CA:
        ket_qua = _chay(ten, mo_ta, ham, mong_doi_chan=mong_doi_chan)
        rows.append(ket_qua)
        dau = "OK  " if ket_qua.dat else "FAIL"
        print(f"[{dau}] {ten:18} {ket_qua.ms:7.0f} ms  {ket_qua.loi or ket_qua.ghi_chu or ''}"[:150])

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = RESULTS_ROOT / run_id
    run_dir.mkdir(parents=True)
    manifest = _manifest(run_id, rows, run_dir)
    metrics = {
        "cases": len(rows),
        "passed": manifest["passed"],
        "egress_attempts_ngoai_ca_tu_kiem": sum(len(r.egress) for r in rows if r.ten != "guard_self_test"),
        "ket_noi_os_ngoai_loopback": sum(len(r.ket_noi_os) for r in rows),
    }

    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "report.md").open("x", encoding="utf-8", newline="\n") as f:
        f.write(_report_md(manifest, rows))

    print(f"\n-> {run_dir.relative_to(REPO)}")
    return 0 if manifest["passed"] == manifest["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

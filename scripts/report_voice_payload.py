r"""Đo `assistant.speech` trên **socket thật**, với **model thật**, và ghi lại thành run.

## Vì sao script này tồn tại

Trần `MAX_SPEECH_BYTES` (`src/services/ivi_events.py`) được đặt từ một phép đo ngày
14/08. Phép đo ấy có thật và đã bắt được một lỗi thật — bản ước từ kích thước payload
nói 130 KiB, đo trên socket ra hơn 5 lần con số đó. Nhưng nó **không để lại hiện vật
nào**: kết quả sống trong chú thích code và một dòng `WORKLOG.md`, không có `run_id`,
không có tầng phần cứng, không lặp lại được.

Hậu quả cụ thể và kiểm được: hai nguồn ấy **ghi hai con số khác nhau** cho cùng một
phép đo — `ivi_events.py` ghi 656,9 KiB / 64,2%, `WORKLOG.md` ghi 667,7 KiB / 65,2%.
Không có run dir nào để phân xử xem con số nào là con số đã đo.

Đó đúng là thứ kỷ luật *"Evidence is the product"* của repo sinh ra để chặn: mọi tuyên
bố định lượng phải truy được về một `run_id`.

## Trần khung 1 MiB không phải con số tự nghĩ ra

`websockets` mặc định `max_size = 2 ** 20`. Script nối bằng đúng mặc định ấy chứ không
nới ra — nếu một event vượt khung, thư viện đóng kết nối với mã 1009 và ta **thấy**
điều đó, thay vì suy ra từ số byte. Đó là khác biệt giữa "đo payload" và "đo trên dây",
và chính khác biệt ấy là chỗ phép đo ước lượng đã sai 5 lần.

## Chạy

    .\.venv\Scripts\python.exe -m scripts.report_voice_payload

Cần backend đang chạy (`python -m src.serve`), model Piper + Zipformer có mặt, và chỉ
mục FAISS đã dựng. Không có đủ thì script dừng và nói thiếu gì — nó không được phép
ghi ra một run rỗng trông như đã đo.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import platform
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO / "eval" / "results" / "voice-payload"

#: Trần khung mặc định của `websockets`, và cũng là con số `MAX_SPEECH_BYTES` được đặt
#: để nằm dưới. Không nới: nới ra là bỏ mất đúng thứ đang đo.
KHUNG_MAC_DINH = 1 << 20

#: Câu hỏi sinh ra đoạn sổ tay **dài** — ca nặng nhất của nhánh RAG, tức ca duy nhất có
#: khả năng chạm trần. Đo ca ngắn rồi kết luận là an toàn thì không chứng minh được gì.
CAU_HOI_DAI = "Hướng dẫn sạc pin xe thế nào?"

#: Chỗ tài xế nói tiếp "đọc tiếp" — mỗi lát cũng là một `assistant.speech`, và lát sau
#: có thể dài hơn lát đầu.
CAU_DOC_TIEP = "Đọc tiếp"


class ThieuDieuKienError(RuntimeError):
    """Không đủ điều kiện để phép đo có nghĩa."""


def _http(base: str, path: str, body=None, token=None, idem=None, method="POST", raw=None, ctype=None):
    headers = {"X-Schema-Version": "1.0"}
    if ctype:
        headers["Content-Type"] = ctype
    elif body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idem:
        headers["Idempotency-Key"] = idem
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def _thoi_luong_wav(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as handle:
        return handle.getnframes() / handle.getframerate()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False).stdout.strip()


def _kiem_dieu_kien(base: str) -> dict:
    """Dừng sớm và nói rõ thiếu gì, thay vì ghi một run rỗng trông như đã đo.

    `/healthz` nằm **ngoài** tiền tố `/api/v1` (`src/main.py`) — nó là probe hạ tầng cho
    Compose, không phải một trong các interface P0.
    """
    goc = base.split("/api/v1")[0]
    try:
        health = _http(goc, "/healthz", method="GET")["data"]
    except urllib.error.URLError as exc:
        raise ThieuDieuKienError(f"backend không trả lời tại {base} — chạy `python -m src.serve` trước") from exc
    thieu = [ten for ten, phan in health["components"].items() if phan["status"] in ("down", "degraded")]
    if thieu:
        raise ThieuDieuKienError(f"thành phần chưa sẵn sàng: {thieu}")
    return health


def _cho_va_do_speech(nhan_su_kien: list, truoc: int, turn_id: str, giay: float = 25) -> dict:
    """Chờ `assistant.speech` của đúng lượt này rồi đo nó.

    Dùng chung cho cả lượt văn bản lẫn lượt giọng nói. Bản đầu chỉ đo lượt văn bản, và
    báo cáo in dòng giọng nói thành *"không có assistant.speech"* — nói dối theo hướng
    nghe như một phát hiện, trong khi thật ra nó **chưa hề được đo**. "Không đo" và "đo
    thấy không có" phải trông khác nhau trong evidence.
    """
    han = time.perf_counter() + giay
    while time.perf_counter() < han:
        for ev in nhan_su_kien[truoc:]:
            if ev["type"] == "assistant.speech" and ev.get("turn_id") == turn_id:
                b64 = ev["payload"]["audio_base64"]
                wav = base64.b64decode(b64)
                khung_bytes = len(json.dumps(ev, ensure_ascii=False).encode("utf-8"))
                return {
                    "co_assistant_speech": True,
                    "wav_bytes": len(wav),
                    "base64_chars": len(b64),
                    # Con số phải nằm dưới khung là CẢ envelope JSON, không chỉ audio.
                    "frame_bytes": khung_bytes,
                    "frame_kib": round(khung_bytes / 1024, 1),
                    "phan_tram_khung": round(khung_bytes / KHUNG_MAC_DINH * 100, 1),
                    "thoi_luong_giay": round(_thoi_luong_wav(wav), 2),
                }
        time.sleep(0.2)
    return {"co_assistant_speech": False}


def _do_mot_luot(base: str, token: str, sid: str, nhan_su_kien: list, text: str, nhan: str) -> dict:
    """Gửi một lượt văn bản, chờ `assistant.speech` của lượt ấy, rồi đo nó."""
    truoc = len(nhan_su_kien)
    bat_dau = time.perf_counter()
    env = _http(base, "/turns/text", {"session_id": sid, "text": text}, token, "vp-" + uuid.uuid4().hex[:10])
    data = env["data"]
    ket_qua = {
        "nhan": nhan,
        "text": text,
        "turn_id": data["turn_id"],
        # `/traces` khoá theo **trace_id**, không theo `turn_id` — và `trace_id` nằm ở
        # TOP LEVEL của envelope, không nằm trong `data`. Đoán nhầm chỗ này làm mọi lời
        # gọi trả 404 và bảng độ trễ ra rỗng.
        "trace_id": env.get("trace_id"),
        "e2e_ms": round((time.perf_counter() - bat_dau) * 1000, 1),
        "speak_text_chars": len(data["response"].get("speak_text") or ""),
        "display_text_chars": len(data["response"].get("display_text") or ""),
    }
    ket_qua.update(_cho_va_do_speech(nhan_su_kien, truoc, data["turn_id"]))
    return ket_qua


def _do_luot_giong_noi(base: str, token: str, sid: str, nhan_su_kien: list, wav_path: Path) -> dict:
    """Một lượt đi qua STT thật — chỗ duy nhất đo được độ trễ nhận dạng."""
    truoc = len(nhan_su_kien)
    bat_dau = time.perf_counter()
    env = _http(
        base,
        f"/turns/voice?session_id={sid}",
        None,
        token,
        "vp-" + uuid.uuid4().hex[:10],
        raw=wav_path.read_bytes(),
        ctype="audio/wav",
    )
    data = env["data"]
    ket_qua = {
        "nhan": "voice",
        "text": f"<WAV {wav_path.name}>",
        "turn_id": data["turn_id"],
        "trace_id": env.get("trace_id"),
        "wav_gui_bytes": wav_path.stat().st_size,
        "thoi_luong_gui_giay": round(_thoi_luong_wav(wav_path.read_bytes()), 2),
        "accepted_ms": round((time.perf_counter() - bat_dau) * 1000, 1),
        "speak_text_chars": None,
        "display_text_chars": None,
    }
    ket_qua.update(_cho_va_do_speech(nhan_su_kien, truoc, data["turn_id"]))
    ket_qua["e2e_ms"] = round((time.perf_counter() - bat_dau) * 1000, 1)
    return ket_qua


def _do_tre_tu_trace(base: str, trace_ids: list[str]) -> dict:
    """Độ trễ STT/TTS lấy từ `TraceStore` — máy ghi, không phải người ước.

    `record_stage(trace_id, "stt"|"tts", ...)` đã có sẵn trong `turns.py` và
    `ivi_events.py`; đọc lại từ đó thay vì tự bấm giờ ngoài tiến trình, vì đồng hồ
    ngoài còn đo cả HTTP, hàng đợi và WebSocket.

    Đăng nhập **engineer** ở đây chứ không dùng lại token tài xế: `/traces` là
    engineer-only (`_ENGINEER_ONLY` trong `src/api/observability.py`). Dùng nhầm vai thì
    mọi lời gọi trả 403, bị `except` nuốt, và bảng độ trễ ra rỗng trông y như "hệ thống
    không ghi độ trễ" — một kết luận sai mà không có gì trên màn hình cải chính.
    """
    token = _http(
        base, "/auth/login", {"email": "engineer.demo@example.com", "password": "DemoEngineer123!"}
    )["data"]["access_token"]
    ra: dict = {}
    for trace_id in trace_ids:
        if not trace_id:
            continue
        try:
            trace = _http(base, f"/traces/{trace_id}", None, token, method="GET")["data"]
        except urllib.error.HTTPError as exc:
            ra[trace_id] = {"_loi": f"HTTP {exc.code}"}
            continue
        ra[trace_id] = trace.get("stage_latencies_ms", {})
    return ra


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--ws", default="ws://127.0.0.1:8000/ws/ivi")
    parser.add_argument("--origin", default="http://localhost:3000")
    parser.add_argument("--wav", default=str(REPO / "tests" / "fixtures" / "voice" / "warm_sample.wav"))
    args = parser.parse_args()

    from websockets.sync.client import connect

    try:
        health = _kiem_dieu_kien(args.base)
    except ThieuDieuKienError as exc:
        print(f"DỪNG: {exc}", file=sys.stderr)
        return 2

    token = _http(
        args.base, "/auth/login", {"email": "driver.demo@example.com", "password": "DemoDriver123!"}
    )["data"]["access_token"]
    sid = _http(
        args.base,
        "/sessions",
        {"vehicle_id": "vehicle-demo-01", "input_mode": "voice"},
        token,
        "vp-" + uuid.uuid4().hex[:8],
    )["data"]["session_id"]
    enc = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")

    nhan_su_kien: list[dict] = []
    ws_loi: list[str] = []
    ws_dong: list[str] = []
    san_sang = threading.Event()

    def chay_ws():
        try:
            # `max_size` để **mặc định** — đó chính là trần đang đo. Nới nó ra là bỏ
            # mất phép thử: một event vượt khung sẽ đóng kết nối 1009 và ta phải THẤY.
            with connect(
                args.ws,
                subprotocols=["vivi.v1", f"bearer.{enc}"],
                additional_headers={"Origin": args.origin},
                max_size=KHUNG_MAC_DINH,
            ) as ws:
                ws.send(
                    json.dumps(
                        {
                            "type": "connection.init",
                            "client_message_id": "vp",
                            "sent_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "schema_version": "1.0",
                            "session_id": sid,
                        }
                    )
                )
                san_sang.set()
                han = time.time() + 90
                while time.time() < han:
                    try:
                        nhan_su_kien.append(json.loads(ws.recv(timeout=2)))
                    except TimeoutError:
                        continue
                    except Exception as exc:  # noqa: BLE001
                        ws_dong.append(f"{type(exc).__name__}: {exc}")
                        return
        except Exception as exc:  # noqa: BLE001
            ws_loi.append(f"{type(exc).__name__}: {exc}")
            san_sang.set()

    luong = threading.Thread(target=chay_ws, daemon=True)
    luong.start()
    san_sang.wait(timeout=15)
    if ws_loi:
        print(f"DỪNG: không nối được websocket — {ws_loi[0]}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    rows.append(_do_luot_giong_noi(args.base, token, sid, nhan_su_kien, Path(args.wav)))
    time.sleep(8)
    rows.append(_do_mot_luot(args.base, token, sid, nhan_su_kien, CAU_HOI_DAI, "rag_dai"))
    rows.append(_do_mot_luot(args.base, token, sid, nhan_su_kien, CAU_DOC_TIEP, "rag_doc_tiep"))
    time.sleep(2)

    tre = _do_tre_tu_trace(args.base, [r.get("trace_id") for r in rows])
    for row in rows:
        row["stage_latencies_ms"] = tre.get(row.get("trace_id"), {})

    con_song = not ws_dong
    khung_do_duoc = [r["frame_bytes"] for r in rows if r.get("frame_bytes")]
    metrics = {
        "khung_mac_dinh_bytes": KHUNG_MAC_DINH,
        "so_luot_do": len(rows),
        "so_luot_co_speech": sum(1 for r in rows if r.get("co_assistant_speech")),
        "frame_bytes_max": max(khung_do_duoc, default=0),
        "phan_tram_khung_max": round(max(khung_do_duoc, default=0) / KHUNG_MAC_DINH * 100, 1),
        "client_van_ket_noi": con_song,
        "ly_do_dong": ws_dong,
        "stt_ms": [r["stage_latencies_ms"].get("stt") for r in rows],
        "tts_ms": [r["stage_latencies_ms"].get("tts") for r in rows],
    }

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = RESULTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "run_id": run_id,
        "suite": "voice-payload",
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "health_components": {ten: phan["status"] for ten, phan in health["components"].items()},
        "khung_mac_dinh_bytes": KHUNG_MAC_DINH,
        "blind_spots": {
            "giong": "Piper tổng hợp, không phải người nói — không suy ra WER từ run này.",
            "mang": "loopback trên một máy; không có độ trễ mạng, không có mất gói.",
            "phan_cung": "một máy Windows dev. Con số byte phụ thuộc giọng và tần số lấy mẫu.",
            "so_luot": "ba lượt, không phải phân bố. Đây là smoke test, không phải benchmark.",
        },
    }

    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "report.md").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_report_md(manifest, metrics, rows))

    print(f"run: {run_dir.relative_to(REPO).as_posix()}")
    print(f"khung lớn nhất: {metrics['frame_bytes_max'] / 1024:.1f} KiB = {metrics['phan_tram_khung_max']}%")
    print(f"client còn kết nối: {con_song}")
    return 0 if con_song and metrics["so_luot_co_speech"] else 1


def _ms(x) -> str:
    """Làm tròn 0,1 ms. `846.9181000255048` là độ chính xác giả — đồng hồ không nói thế."""
    return "—" if x is None else f"{x:.1f}"


def _report_md(manifest: dict, metrics: dict, rows: list[dict]) -> str:
    dong = [
        f"# Smoke test payload giọng nói — run `{manifest['run_id']}`",
        "",
        f"- Commit `{manifest['git_commit'][:12]}` trên `{manifest['git_branch']}`"
        + (" (**cây làm việc bẩn**)" if manifest["git_dirty"] else ""),
        f"- Python {manifest['python']} · {manifest['platform']}",
        f"- Trần khung client: **{manifest['khung_mac_dinh_bytes'] / 1024:.0f} KiB** (mặc định `websockets`, không nới)",
        "",
        "## Kết quả",
        "",
        "| lượt | speak_text | audio | thời lượng | khung WS | % khung |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        if not row.get("frame_bytes"):
            dong.append(f"| `{row['nhan']}` | — | *đo: KHÔNG có assistant.speech* | — | — | — |")
            continue
        dong.append(
            f"| `{row['nhan']}` | {str(row['speak_text_chars']) + ' ký tự' if row['speak_text_chars'] is not None else '— (lượt giọng nói)'} "
            f"| {row['wav_bytes'] / 1024:.1f} KiB | {row['thoi_luong_giay']} s "
            f"| **{row['frame_kib']} KiB** | {row['phan_tram_khung']}% |"
        )
    dong += [
        "",
        f"**Client vẫn kết nối: {'CÓ' if metrics['client_van_ket_noi'] else 'KHÔNG'}**"
        + ("" if metrics["client_van_ket_noi"] else f" — {metrics['ly_do_dong']}"),
        "",
        "Đây là vế mà một phép đo payload thuần không nói được: `max_size` để nguyên mặc định,",
        "nên một event vượt khung sẽ đóng kết nối mã 1009 và hiện ra ở dòng trên chứ không phải",
        "suy ra từ số byte.",
        "",
        "## Độ trễ theo tầng (do `TraceStore` ghi, không phải đồng hồ ngoài)",
        "",
        "`end_to_end` **nhỏ hơn** `tts` không phải lỗi: nó được chốt trước khi TTS chạy, nên",
        "TTS cố ý không nằm trong đó (`CLAUDE.md`, mục observability). Muốn thời gian tài xế",
        "thật sự chờ tới lúc nghe được tiếng thì cộng hai cột — nhưng con số ấy repo chưa",
        "định nghĩa, nên tôi không tự đặt ra ở đây.",
        "",
        "| lượt | stt | tts | end_to_end |",
        "|---|---|---|---|",
    ]
    for row in rows:
        tre = row.get("stage_latencies_ms") or {}
        dong.append(
            f"| `{row['nhan']}` | {_ms(tre.get('stt'))} | {_ms(tre.get('tts'))} | {_ms(tre.get('end_to_end'))} |"
        )
    dong += ["", "## Điểm mù", ""]
    for ten, text in manifest["blind_spots"].items():
        dong.append(f"- **{ten}** — {text}")
    dong.append("")
    return "\n".join(dong)


if __name__ == "__main__":
    raise SystemExit(main())

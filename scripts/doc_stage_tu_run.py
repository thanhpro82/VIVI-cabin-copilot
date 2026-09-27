"""Tách từng lượt của một run `do_luot_that_dong_thoi.py` thành **stage**.

`metrics.json` của run kia chỉ có `ms_tong` — một con số cho cả lượt. Nó trả lời được
"chậm hay không" nhưng không trả lời được "chậm ở đâu", mà "ở đâu" mới là thứ quyết định
sửa cái gì. Script này lấy `trace_id` mà run đã lưu (`--giu-ban-ghi`) rồi gọi
`GET /api/v1/traces/{trace_id}` để đọc `stage_latencies_ms`.

## Ba cạm bẫy, cả ba đều đã cắn một lần

1. **`TraceStore` là LRU 200 bản ghi, trong RAM** (`src/services/trace_store.py`). Restart
   backend là mất sạch; một run đông lượt tự đẩy bản ghi đầu ra. **Chạy script này ngay sau
   khi đo.** Trace mất hiện ra ở đây là `404`, và bảng nói rõ mất bao nhiêu — không im lặng
   bỏ qua, vì một bảng dựng trên 30% số lượt còn sót là bảng nói dối.

2. **`tts` KHÔNG được cộng vào `end_to_end`.** `turns.py:84` chốt `end_to_end` **trước** khi
   `emit_turn_lifecycle` chạy Piper (`ivi_events.py`). Nên đừng trừ ngược ra TTS, và đừng
   đọc `end_to_end` như tổng công sức của lượt. Tổng thật là `end_to_end + tts`, và cột
   `tong` dưới đây tính đúng như vậy.

3. **`/metrics/summary` không thay được script này.** Nó là fold trên cửa sổ rolling 1 giờ,
   trộn mọi mức N, mọi câu, cả lượt của người dùng thật. Dùng nó để trả lời câu hỏi về một
   câu cụ thể là trộn hai phép đo khác nhau.

## Chạy

    python3 scripts/doc_stage_tu_run.py ~/vivi-runs/<run-id>/metrics.json

Cần `httpx`. Tài khoản kỹ sư mặc định là hai dòng seed ở `src/db.py:267-268`;
`GET /traces/{id}` là **engineer-only** (`src/api/observability.py`), token tài xế bị 403.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_VERSION = "1.0"

#: Đúng bảy trường của `StageLatencies` (`src/models/observability.py:94-104`), giữ nguyên
#: thứ tự thời gian trong lượt để đọc bảng là thấy được dòng chảy.
STAGES: tuple[str, ...] = (
    "stt",
    "routing",
    "planning_or_retrieval",
    "safety",
    "tool",
    "tts",
    "end_to_end",
)

#: Tên ngắn cho bảng — `planning_or_retrieval` một mình đã 21 ký tự.
NHAN_NGAN: dict[str, str] = {
    "stt": "stt",
    "routing": "route",
    "planning_or_retrieval": "plan/rag",
    "safety": "safety",
    "tool": "tool",
    "tts": "tts",
    "end_to_end": "e2e",
}


def _headers(token: str | None = None) -> dict[str, str]:
    h = {"X-Schema-Version": SCHEMA_VERSION}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _login(client, base_url: str, email: str, password: str) -> str:
    r = await client.post(f"{base_url}/auth/login", json={"email": email, "password": password}, headers=_headers())
    if r.status_code != 200:
        raise SystemExit(f"dang nhap that bai: http {r.status_code}: {r.text[:200]}")
    data = r.json()["data"]
    token = data.get("access_token")
    if not token:
        raise SystemExit(f"khong tim thay access_token trong envelope login: {list(data)}")
    vai = (data.get("user") or {}).get("role")
    if vai != "engineer":
        # 403 ở `GET /traces` là lỗi khó đoán khi nhìn từ ngoài; nói ra ngay tại đây.
        raise SystemExit(f"tai khoan nay co vai '{vai}', khong phai 'engineer' -> /traces se tra 403")
    return token


async def _doc_trace(client, base_url: str, token: str, trace_id: str) -> dict | None:
    """`None` nghĩa là trace không còn trong kho — **không** phải lỗi mạng.

    Phân biệt được hai chuyện đó là quan trọng: 404 hàng loạt nghĩa là đo xong để lâu quá
    (LRU 200 đã đẩy hết), còn lỗi mạng nghĩa là gọi sai chỗ. Trường hợp sau ném ra ngoài.
    """
    r = await client.get(f"{base_url}/traces/{trace_id}", headers=_headers(token))
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise SystemExit(f"GET /traces/{trace_id} -> http {r.status_code}: {r.text[:200]}")
    return r.json()["data"]


def _p50(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def _tong(st: dict) -> float | None:
    """`end_to_end + tts` — xem cạm bẫy 2 ở docstring đầu file."""
    e2e = st.get("end_to_end")
    if e2e is None:
        return None
    return round(e2e + (st.get("tts") or 0.0), 1)


def _lay_ban_ghi(metrics: dict) -> list[tuple[str, dict]]:
    """Trả `[(muc_N, ban_ghi), ...]`, chỉ những bản ghi có `trace_id`."""
    ra: list[tuple[str, dict]] = []
    for muc, o in (metrics.get("ket_qua") or {}).items():
        for bg in o.get("ban_ghi") or []:
            if bg.get("trace_id"):
                ra.append((muc, bg))
    return ra


def _in_bang_luot(muc: str, hang: list[dict]) -> None:
    print(f"\n=== N={muc} ({len(hang)} luot doc duoc trace) ===")
    cot = "  ".join(f"{NHAN_NGAN[s]:>9}" for s in STAGES)
    print(f"{'nhan':<12} {'ms_tong':>8}  {cot}  {'tong':>9}")
    for h in hang:
        st = h["stage"]
        o = "  ".join(f"{st[s]:>9.0f}" if st.get(s) is not None else f"{'-':>9}" for s in STAGES)
        ms = h["ban_ghi"].get("ms_tong")
        cot_ms = f"{ms:>8.0f}" if ms is not None else f"{'-':>8}"
        tong = _tong(st)
        cot_tong = f"{tong:>9.0f}" if tong is not None else f"{'-':>9}"
        print(f"{h['ban_ghi'].get('nhan', '?'):<12} {cot_ms}  {o}  {cot_tong}")


def _in_p50(muc: str, hang: list[dict]) -> None:
    print(f"\n--- p50 theo stage, N={muc} ---")
    for s in STAGES:
        xs = [h["stage"][s] for h in hang if h["stage"].get(s) is not None]
        v = _p50(xs)
        print(f"  {NHAN_NGAN[s]:<10} {v if v is not None else '-':>9}   (n={len(xs)})")
    tongs = [t for h in hang if (t := _tong(h["stage"])) is not None]
    print(f"  {'TONG':<10} {_p50(tongs) if tongs else '-':>9}   (n={len(tongs)})")


def _in_tieu_chi(theo_muc: dict[str, list[dict]], che_do: str | None) -> None:
    """Tiêu chí đã chốt TRƯỚC khi nhìn số — đừng đổi nó sau khi thấy kết quả.

    `stt + tts` chiếm ≳70% tổng công sức một lượt thì thủ phạm là hàng đợi STT/TTS
    (`voice.py` giữ `threading.Lock()` cho cả hai, nên người thứ ba xếp hàng tuyệt đối);
    ≲30% thì giả thuyết CPU over-subscribe lên số một.

    Ngưỡng ấy **chỉ đọc được ở chế độ `voice`**. Chế độ `text` không có STT chút nào
    (`stt` luôn null), nên tỉ lệ ở đó là tỉ lệ của riêng TTS trên một đường ngắn hơn hẳn —
    lấy nó áp vào ngưỡng 70/30 là so hai thứ khác nhau. In ra vẫn có ích để đối chiếu,
    nhưng phải nói thẳng nó không phải cái để chốt.
    """
    print("\n=== TY LE stt+tts / (end_to_end + tts) ===")
    if che_do == "voice":
        print("    >= 70%: nut that la hang doi STT/TTS -> sua khoa trong voice.py, tra `-t` ve 5")
        print("    <= 30%: nut that la CPU over-subscribe -> giu `-t 4`")
    else:
        print(f"    !! che do '{che_do}' KHONG co STT — nguong 70/30 chi ap dung cho --che-do voice.")
        print("       So duoi day la ti le rieng cua TTS, doc de doi chieu, KHONG dung de chot gia thuyet.")
    for muc in sorted(theo_muc, key=lambda x: int(x)):
        ty_le = []
        for h in theo_muc[muc]:
            st = h["stage"]
            tong = _tong(st)
            if not tong:
                continue
            ty_le.append(((st.get("stt") or 0.0) + (st.get("tts") or 0.0)) / tong * 100)
        if ty_le:
            print(f"  N={muc}: p50 {statistics.median(ty_le):.1f}%  (n={len(ty_le)})")
        else:
            print(f"  N={muc}: khong du du lieu")


async def _chay(args) -> int:
    import httpx

    duong = Path(args.metrics)
    if not duong.exists():
        raise SystemExit(f"khong thay file: {duong}")
    metrics = json.loads(duong.read_text(encoding="utf-8"))

    ban_ghi = _lay_ban_ghi(metrics)
    if not ban_ghi:
        raise SystemExit(
            "khong ban ghi nao co `trace_id`. Hai kha nang: (a) run chay khong co --giu-ban-ghi; "
            "(b) run chay bang ban do_luot_that_dong_thoi.py CU, truoc khi no luu trace_id. "
            "Do lai voi ban moi."
        )

    base_url = args.base_url or metrics.get("base_url")
    if not base_url:
        raise SystemExit("metrics.json khong co `base_url`, phai truyen --base-url")

    print(f"run       = {duong.parent.name}")
    print(f"che do    = {metrics.get('che_do')}")
    print(f"base_url  = {base_url}")
    print(f"co trace  = {len(ban_ghi)} luot\n")

    theo_muc: dict[str, list[dict]] = {}
    mat = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await _login(client, base_url, args.email, args.password)
        for muc, bg in ban_ghi:
            data = await _doc_trace(client, base_url, token, bg["trace_id"])
            if data is None:
                mat += 1
                continue
            theo_muc.setdefault(muc, []).append({"ban_ghi": bg, "stage": data.get("stage_latencies_ms") or {}})

    if mat:
        # Nói ra tỉ lệ, không chỉ số tuyệt đối: 3/72 là nhiễu, 50/72 là bảng vô nghĩa.
        print(f"!! {mat}/{len(ban_ghi)} trace da bi day khoi kho (LRU 200) — bang duoi dung phan con lai\n")
    if not theo_muc:
        raise SystemExit("khong doc duoc trace nao. Backend co restart giua luc do va luc doc khong?")

    for muc in sorted(theo_muc, key=lambda x: int(x)):
        if not args.chi_p50:
            _in_bang_luot(muc, theo_muc[muc])
        _in_p50(muc, theo_muc[muc])

    _in_tieu_chi(theo_muc, metrics.get("che_do"))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Doc stage tung luot cua mot run do_luot_that_dong_thoi.py")
    p.add_argument("metrics", help="duong dan toi metrics.json cua run")
    p.add_argument("--base-url", default=None, help="mac dinh lay tu metrics.json")
    p.add_argument("--email", default="engineer.demo@example.com")
    p.add_argument("--password", default="DemoEngineer123!")
    p.add_argument("--chi-p50", action="store_true", help="bo bang tung luot, chi in p50")
    return asyncio.run(_chay(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

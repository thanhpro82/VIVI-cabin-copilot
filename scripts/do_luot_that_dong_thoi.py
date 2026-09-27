"""Đo **lượt thật đi qua backend** khi nhiều người dùng cùng lúc — không phải đo llama-server.

Ghi một thư mục run **bất biến** dưới `eval/results/luot-that-dong-thoi/<UTC-run-id>/`.

## Vì sao cần script này khi đã có `do_slm_dong_thoi.py`

Script kia gọi **thẳng** `http://…:8093/completion`. Nó trả lời tốt câu hỏi "llama-server
chịu được mấy lượt song song", nhưng nó **đi vòng qua toàn bộ phần còn lại của hệ**: không
qua auth, không qua router tất định, không qua RAG, không qua compose, không qua STT/TTS,
và — quan trọng nhất kể từ khi có bộ chặn đồng thời — **không qua cái van đó**. Đo bằng nó
sau khi thêm van thì van vô hình, vì van nằm trong backend còn script thì nói chuyện thẳng
với model.

Đây là script trả lời câu hỏi khác: **một người dùng thật bấm nút thì mất bao lâu, khi có
N người cùng bấm.** Đó là điều kiện 3 của PM/PO review PR #257 (2026-08-24).

## Hai chế độ, và vì sao chế độ `voice` mới là số thật

- `--che-do text` — `POST /turns/text`, đồng bộ, một request là một lượt. Đo được
  router → SLM → RAG → compose. **Không** có STT, **không** có TTS.
- `--che-do voice` — `POST /turns/voice` (202) rồi nghe `/ws/ivi` tới `assistant.response`.
  Đây là đường tài xế thật đi, và là đường duy nhất tính cả STT lẫn TTS. Hai thứ đó có
  **khoá toàn cục** (`voice.py:97`, `:192`, `num_threads=1`) nên chúng nối tiếp nhau bất kể
  van SLM đặt bao nhiêu — chế độ `text` không nhìn thấy chuyện đó.

Chế độ `text` nhanh và đủ để so hai bản code. Đừng dùng nó để tuyên bố sức chứa sản phẩm.

## Chạy ở đâu

Trên **VPS, ngoài container** (hoặc bất kỳ máy nào tới được domain), vì mục đích là đo đúng
thứ người dùng nhận, kể cả chặng Caddy:

    python3 scripts/do_luot_that_dong_thoi.py --moc 1,2,3 --che-do text

Muốn bỏ Caddy ra khỏi phép đo thì thêm `--base-url http://127.0.0.1:8000/api/v1`.

## Cấu hình được ghi vào manifest — đây là chỗ run cũ thiếu

Bốn run `eval/results/slm-dong-thoi/*` ghi `git_commit` và `platform` nhưng **không ghi
`-c`, `n_slots`, `kv_unified`** của llama-server. Hậu quả: không đọc lại được run đó đo cấu
hình nào, đúng cái cấu hình mà PR #257 đang đổi. Script này probe `/props` + `/slots` và ghi
thẳng vào manifest. Không probe được thì ghi `doc_duoc: false` kèm lý do **và nói ra trong
report**, chứ không im lặng bỏ qua.

## Trên máy chủ, ghi run RA NGOÀI repo

Mặc định run được ghi vào `eval/results/luot-that-dong-thoi/` **trong cây git**. Trên máy
dev thì đúng — đó là chỗ bằng chứng phải nằm. Trên **VPS thì sai**, và đã gây kẹt bốn lần
trong một ngày: run sinh ra là file untracked, sau đó cùng đường dẫn ấy được commit ở máy
dev, và lần `git checkout` kế tiếp bị `git` từ chối vì *"untracked working tree files would
be overwritten"*.

Nên trên máy chủ hãy chạy với:

    python3 scripts/do_luot_that_dong_thoi.py --out-dir ~/vivi-runs ...

rồi `scp` về máy dev và commit ở đó. Cây làm việc trên máy chủ không bao giờ có file lạ,
và `deploy.sh` không bao giờ bị chặn vì phép đo.

## Tách một lượt thành stage

`ms_tong` là một con số duy nhất; nó không nói được lượt tốn thời gian ở **đâu**. Chạy với
`--giu-ban-ghi` thì mỗi bản ghi mang `trace_id`, và `scripts/doc_stage_tu_run.py` lấy id ấy
gọi `GET /traces/{trace_id}` để tách ra `stt / routing / planning_or_retrieval / safety /
tool / tts / end_to_end`.

`TraceStore` là LRU 200 bản ghi **trong RAM**: restart backend là mất sạch, và một run đông
lượt tự đẩy bản ghi đầu ra. **Đọc stage ngay sau khi đo**, đừng để sang buổi khác.

## Nguyên tắc: KHÔNG cắt ở trần thật

Trần khi đo là 60 s, cố ý nới — cùng lý lẽ `do_slm_dong_thoi.py`: cắt ở đúng ngưỡng thì mọi
lần hụt đều trả về đúng ngưỡng và không học được gì. Lượt chạm trần được đánh dấu `cat_cut`
và mọi thống kê dính chúng là **cận dưới**, không phải giá trị.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import platform
import statistics
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Lay cau ban tu CHINH NGUON, khong chep tay: doi cau o `chitchat_cong.py` ma quen o
# day thi script am tham dem 0 luot bi tu choi va bang do se dep mot cach sai su that.
try:
    from src.agents.nodes.chitchat_cong import CAU_BAN
except Exception:  # noqa: BLE001 - chay ngoai repo thi mat kha nang dem, khong phai su co
    CAU_BAN = None

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO_ROOT / "eval" / "results" / "luot-that-dong-thoi"
#: Mac dinh la bo `cham_slm` chu KHONG phai `synthetic_commands`: bo kia toan lenh
#: dieu khien ma router tat dinh xu duoc, nen do bang no la do mot duong khong cham
#: SLM. Doi bang `--wav-dir` neu muon do dung duong dieu khien.
WAV_DIR = REPO_ROOT / "tests" / "fixtures" / "voice" / "cham_slm"

SCHEMA_VERSION = "1.0"

#: Trần khi đo. Nới hơn hẳn mọi timeout trong hệ để đo được độ trễ THẬT.
TRAN_DO_S = 60.0

#: Ngưỡng đối chiếu end-to-end của `README.md` (p50 ≤ 2 500 ms, p95 ≤ 4 500 ms).
#: `CLAUDE.md` ghi rõ hai số này **chưa từng được đo**; đây là lần đầu.
NGUONG_P50_MS = 2500.0
NGUONG_P95_MS = 4500.0

#: Câu dùng để đo, chọn để phủ **bốn đường đi khác nhau** trong graph. Nhãn quan trọng hơn
#: câu chữ: thống kê tách theo nhãn, vì trộn chung thì đường rẻ che mất đường đắt — đúng
#: lỗi "phân bố lưỡng đỉnh" đã gặp ở run spike3 `20260822T053907`.
CASES: list[tuple[str, str]] = [
    # Khớp luật router → KHÔNG chạm SLM. Đây là sàn: nhanh nhất hệ có thể làm.
    ("dieu_khien", "bật điều hoà"),
    ("dieu_khien", "đóng cửa sổ"),
    # Câu hỏi sổ tay → classify + RAG + compose. RAG không dùng llama-server.
    ("so_tay", "xe này sạc nhanh mất bao lâu"),
    ("so_tay", "áp suất lốp tiêu chuẩn là bao nhiêu"),
    # Trượt luật → planner. Đắt nhất, và là đường duy nhất không có lối vòng.
    #
    # BA câu, cố ý nhắm ba tool khác nhau. Trước 2026-08-25 chỉ có câu đầu, nên run
    # `20260825T042019` chứng minh được "câu NÀY tốn 28 s rồi hỏng" mà KHÔNG chứng minh
    # được điều đó đúng cho cả đường planner. Câu đầu rơi vào `set_seat_heating` — tool
    # đòi hai trường (`seat`, `level`) mà `SLM_UNION_PROMPT` không có ví dụ nào, nên model
    # thiếu trường và hỏng schema ở cả hai lần thử.
    ("planner", "làm cho trong xe dễ chịu hơn tí đi"),
    ("planner", "trong xe ngột ngạt quá, xử lý giúp tôi"),
    ("planner", "ồn quá tôi không tập trung được"),
    # Xã giao → chitchat.
    ("chitchat", "chào xe, hôm nay thế nào"),
]

BLIND_SPOTS = {
    "ghep_lo_van_khong_phai_ngau_nhien": (
        "Moi vong chay du bo ca, cat thanh lo N, va bo ca duoc XOAY theo vong de cac ca khac "
        "nhau co dip dung chung lo. Nhung voi `--vong` nho thi so to hop van it: `--vong 3` tren "
        "6 ca chi cho 3 cach ghep. Doc cot `cung_lo` trong ban_ghi truoc khi ket luan mot nhan "
        "'khong bi anh huong' — co the no chua bao gio chay chung lo voi `planner`."
    ),
    "p95_o_mau_nho_chinh_la_max": (
        "Bang 'tach theo duong di' chia mau cho 4-6 nhan, nen nhieu o chi co 1-2 mau. Voi 1 mau "
        "thi 'p50' = 'p95' = 'max' = chinh gia tri do. Dung doc no nhu mot phan vi that; doc "
        "cot n_mau truoc."
    ),
    "mot_may_mot_lan": "MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.",
    "dong_thoi_khong_deu": (
        "N request ban ra gan nhu cung luc, KHONG mo phong nguoi dung that (ho den rai rac). "
        "Day la ca XAU NHAT, co y: cho tran tren cua do tre, khong cho ky vong trung binh."
    ),
    "mot_tai_khoan_N_phien": (
        "Tat ca N phien thuoc cung MOT tai khoan demo (src/services/auth.py chi co hai tai khoan "
        "hard-code). Do duoc tranh chap tai nguyen, KHONG do duoc tranh chap o tang auth hay pool "
        "xe theo nguoi dung."
    ),
    "luot_cho_duyet_ket_thuc_khac": (
        "Lenh cham buoc S2 (cua so, cua, ghe) khong tra loi ma HOI LAI de xin duyet, va ket "
        "thuc bang `assistant.status` state=waiting_approval chu khong bang `assistant.response` "
        "(ivi_events.py:467, issue #215). Ban ghi co `ket_thuc` de phan biet. Doc cot do truoc "
        "khi ket luan: mot luot 'cho duyet' la he lam DUNG, khong phai he khong tra loi."
    ),
    "approval_duoc_TU_CHOI_sau_moi_lo": (
        "Moi phien chi duoc co MOT approval pending (chi muc duy nhat tung phan trong src/db.py, "
        "ADR-017), ma script dung lai cung bo phien cho moi lo. Khong don thi luot S2 di ngay sau "
        "mot luot S2 khac bi chinh approval cua luot truoc chan, va nhan cau 'Dang co mot lenh cho "
        "ban xac nhan' thay vi mot ke hoach. Do duoc run 20260827T093455: doc bang tho thi thay "
        "'planner ra ke hoach 3/6', con so THAT la 6/6. Nay `_don_phe_duyet_dang_treo` TU CHOI moi "
        "approval sau khi dong ho da dung, nen no khong lot vao `ms_tong`. He qua: khong luot nao "
        "duoc duyet, nen `tool` KHONG BAO GIO chay va run nay khong do duoc chang thuc thi. Run "
        "truoc 2026-08-27 khong co buoc don nay — dung so ke hoach cua chung voi run sau."
    ),
    "stt_nghe_sai_la_mot_phan_cua_phep_do": (
        "Backend KHONG nhan cau goc, no nhan thu Zipformer nghe ra. Loopback do 2026-08-25 tren "
        "bo `cham_slm`: WER 0,000-0,222 (xem tests/fixtures/voice/cham_slm/README.md). Ca 5 cau "
        "van roi dung lan nen do DO TRE duoc, nhung `cau_01` mat chu 'lop' nen CHAT LUONG cau tra "
        "loi cua no khong so duoc voi cung cau o che do text. Va day la WER giong TONG HOP, khong "
        "phai nguoi that."
    ),
    "wav_phu_thuoc_bo_dang_dung": (
        "`--wav-dir` quyet dinh che do voice do duong nao. Bo mac dinh `cham_slm` phu so_tay / "
        "planner / chitchat. Bo `synthetic_commands` toan LENH DIEU KHIEN router tat dinh xu duoc, "
        "nen do bang no la do STT -> router -> executor -> TTS va KHONG cham SLM. Doc manifest cua "
        "bo da dung truoc khi ket luan."
    ),
    "am_thanh_tong_hop": (
        "Che do voice dung WAV Piper tong hop trong tests/fixtures/voice/. Do duoc DO TRE that, "
        "KHONG ket luan duoc gi ve WER nguoi noi that."
    ),
    "che_do_text_khong_co_stt_tts": (
        "--che-do text bo qua STT va TTS. Ca hai co khoa toan cuc (voice.py:97, :192, "
        "num_threads=1) nen chung noi tiep bat ke van SLM dat bao nhieu. So cua che do text la "
        "CAN DUOI cua do tre luot thoai that."
    ),
    "lich_su_anh_huong_ket_qua": (
        "Do tre phu thuoc slot nao dang giu tien to nao, tuc phu thuoc vai phut TRUOC do. Hai run "
        "cung cau hinh co the lech nhieu lan. Luon doc cau_hinh_llama trong manifest truoc khi so."
    ),
    "caddy_trong_duong_do": (
        "Mac dinh do qua domain that, tuc CO Caddy va TLS trong duong. Dung --base-url "
        "http://127.0.0.1:8000/api/v1 de bo ra. Hai cach cho hai con so khac nhau; dung tron."
    ),
}


# --------------------------------------------------------------- probe cấu hình


def _probe_llama(endpoint: str | None) -> dict:
    """Đọc cấu hình llama-server đang chạy. Đây là thứ bốn run cũ thiếu.

    Không probe được thì trả `doc_duoc: False` kèm lý do — **có mặt trong manifest với giá
    trị rỗng vẫn hơn là vắng mặt**, vì đọc lại còn biết là đã thử và trượt.
    """
    if not endpoint:
        return {"doc_duoc": False, "ly_do": "khong truyen --slm-endpoint"}
    import httpx

    out: dict = {"doc_duoc": False, "endpoint": endpoint}
    try:
        with httpx.Client(timeout=5.0) as c:
            props = c.get(f"{endpoint}/props").json()
            slots = c.get(f"{endpoint}/slots").json()
    except Exception as exc:  # noqa: BLE001 - probe trượt là dữ liệu, không phải sự cố
        out["ly_do"] = f"{type(exc).__name__}: {exc}"
        return out

    gen = props.get("default_generation_settings") or {}
    out.update(
        {
            "doc_duoc": True,
            "n_ctx": gen.get("n_ctx") or props.get("n_ctx"),
            "n_slots": len(slots) if isinstance(slots, list) else props.get("total_slots"),
            "model_path": props.get("model_path"),
            # `kv_unified` chỉ có ở build mới; thiếu thì để None chứ không đoán.
            "kv_unified": gen.get("kv_unified", props.get("kv_unified")),
        }
    )
    return out


async def _probe_healthz(base_url: str) -> dict:
    import httpx

    root = base_url.removesuffix("/api/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=True) as c:
            r = await c.get(f"{root}/healthz")
            return {"http": r.status_code, "than": r.json()}
    except Exception as exc:  # noqa: BLE001
        return {"http": None, "loi": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------- HTTP tiện ích


def _headers(token: str | None = None, idem: bool = False) -> dict[str, str]:
    h = {"X-Schema-Version": SCHEMA_VERSION}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if idem:
        # Phải DUY NHẤT mỗi request: trùng key là trúng bản ghi idempotency cũ và trả về
        # ngay lập tức — số đo sẽ đẹp một cách vô nghĩa.
        h["Idempotency-Key"] = str(uuid.uuid4())
    return h


async def _login(client, base_url: str, email: str, password: str) -> str:
    r = await client.post(f"{base_url}/auth/login", json={"email": email, "password": password}, headers=_headers())
    r.raise_for_status()
    data = r.json()["data"]
    token = data.get("access_token") or data.get("token")
    if not token:
        raise SystemExit(f"khong tim thay token trong envelope login: {list(data)}")
    return token


async def _tao_phien(client, base_url: str, token: str, vehicle_id: str, input_mode: str) -> str:
    r = await client.post(
        f"{base_url}/sessions",
        json={"vehicle_id": vehicle_id, "input_mode": input_mode},
        headers=_headers(token, idem=True),
    )
    r.raise_for_status()
    return r.json()["data"]["session_id"]


# --------------------------------------------------------------- một lượt


async def _mot_luot_text(client, base_url: str, token: str, session_id: str, nhan: str, text: str) -> dict:
    t0 = time.perf_counter()
    try:
        r = await asyncio.wait_for(
            client.post(
                f"{base_url}/turns/text",
                json={"session_id": session_id, "text": text},
                headers=_headers(token, idem=True),
            ),
            timeout=TRAN_DO_S,
        )
        ms = round((time.perf_counter() - t0) * 1000, 1)
        body: dict = {}
        if r.headers.get("content-type", "").startswith("application/json"):
            body = r.json() or {}
        data = body.get("data", {}) or {}
        tra_loi = (data.get("response") or {}).get("display_text") or ""
        return {
            "nhan": nhan,
            "text": text,
            # `trace_id` nam o GOC envelope, KHONG trong `data` (`models/api.py:202`).
            # Khong luu no thi sau khi do xong khong con duong nao tra `GET /traces/{id}`,
            # va `ms_tong` mai mai la mot con so khong tach duoc thanh stage.
            "trace_id": body.get("trace_id"),
            "ms_tong": ms,
            "http": r.status_code,
            "status": data.get("status"),
            # Sau khi co van (ADR-030), luot qua tai tra ve RAT NHANH. Khong tach ra thi
            # no keo p50 xuong va bang trong nhu he nhanh len, trong khi thuc te la mot
            # phan nguoi dung khong duoc phuc vu.
            "bi_tu_choi": bool(CAU_BAN) and CAU_BAN in tra_loi,
            # `action_plan` khác null nghĩa là lượt này đi đường điều khiển thật.
            "co_plan": data.get("action_plan") is not None,
            # Cung muc dich voi nhanh voice: giu ma de chot approval sau luot.
            "approval_id": (data.get("pending_approval") or {}).get("approval_id"),
            "cat_cut": False,
            "loi": None if r.status_code == 200 else f"http {r.status_code}: {r.text[:160]}",
        }
    except Exception as exc:  # noqa: BLE001 - lỗi là DỮ LIỆU ở đây, không phải sự cố
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "nhan": nhan,
            "text": text,
            "trace_id": None,
            "ms_tong": ms,
            "http": None,
            "status": None,
            "co_plan": None,
            "cat_cut": ms >= TRAN_DO_S * 1000 - 500,
            "loi": f"{type(exc).__name__}: {exc}"[:200],
        }


async def _mo_ws(base_url: str, token: str, session_id: str, origin: str):
    """Mở `/ws/ivi` và làm xong `connection.init`.

    Token đi qua **subprotocol** `bearer.<base64url>`, không qua header `Authorization` —
    trình duyệt không set được custom header khi mở WebSocket, và server (`ws.py:91`) chỉ
    đọc đúng chỗ đó. Bỏ padding `=`: RFC 6455 chỉ cho ký tự token hợp lệ trong subprotocol.

    ## `origin` là BẮT BUỘC, và thiếu nó thì lỗi trông như lỗi quyền

    `ws.py:176` kiểm `Origin` với `CORS_ORIGINS` như điều kiện thứ ba của auth. Thư viện
    `websockets` **không tự gửi** header đó (trình duyệt mới tự gửi), nên server đọc ra
    `None`, trượt allowlist, và đóng bằng **4403** — cùng mã với "sai role". Gặp thật
    2026-08-25 trên VPS: thông báo là `ConnectionClosedError: received 4403`, không hề nhắc
    tới Origin, nên rất dễ đi tìm nhầm ở phía token.
    """
    import websockets

    root = base_url.removesuffix("/api/v1").rstrip("/")
    ws_url = root.replace("https://", "wss://").replace("http://", "ws://") + "/ws/ivi"
    ma = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
    ws = await websockets.connect(
        ws_url,
        subprotocols=["vivi.v1", f"bearer.{ma}"],
        origin=origin,
        # `assistant.speech` mang audio base64 — khung có thể vài MB.
        max_size=16 * 1024 * 1024,
        open_timeout=20,
    )
    await ws.send(json.dumps({"type": "connection.init", "session_id": session_id}))
    return ws


async def _mot_luot_voice(client, base_url: str, token: str, session_id: str, ws, nhan: str, wav: bytes) -> dict:
    """Gửi WAV thật rồi **nghe WS** cho tới `assistant.response`.

    `/turns/voice` trả 202 ngay, nên thời gian của nó KHÔNG phải thời gian lượt. Thứ tài xế
    cảm nhận là lúc câu trả lời hiện ra — tức `assistant.response` trên `/ws/ivi`.

    ## PHẢI lọc theo `turn_id`, nếu không số đo là rác

    Socket được mở **một lần cho cả phiên** rồi dùng lại cho mọi lượt — đúng như client thật
    làm. Nghĩa là hàng đợi nhận của nó có sẵn event của **lượt trước** (kể cả hai lượt hâm
    nóng) lúc lượt này bắt đầu. Bắt `assistant.response` đầu tiên nhìn thấy là bắt phải event
    cũ, và đồng hồ dừng gần như tức thì.

    Gặp thật ở run `20260825T040756`: bảng voice cho `p50 33 ms`, có ô **10 ms** cho một lượt
    STT + router + TTS. Không phải hệ nhanh — là phép đo sai. `/turns/voice` trả `turn_id`
    trong thân 202 (`turns.py:207`) và mọi event mang `turn_id` (`ivi_events.py:171`), nên
    lọc được chính xác.
    """
    t0 = time.perf_counter()
    moc: dict[str, float | None] = {
        "transcript.final": None,
        "assistant.speech": None,
        "assistant.response": None,
        # Luot S2 KET THUC o day chu khong o `assistant.response` — xem `_cho()`.
        "cho_duyet": None,
    }
    # Khai truoc `try` de nhanh `except` doc duoc ke ca khi hong tu request dau tien.
    trace_id: str | None = None
    ma_duyet: str | None = None
    khoa = {k: f"ms_{k.replace('.', '_')}" for k in moc}
    try:
        r = await client.post(
            f"{base_url}/turns/voice",
            params={"session_id": session_id},
            content=wav,
            headers={**_headers(token, idem=True), "Content-Type": "audio/wav"},
        )
        ms_202 = round((time.perf_counter() - t0) * 1000, 1)
        if r.status_code != 202:
            return {
                "nhan": nhan,
                "trace_id": None,
                "ms_tong": ms_202,
                "ms_202": ms_202,
                "http": r.status_code,
                "cat_cut": False,
                "loi": f"khong phai 202: {r.text[:160]}",
                **{v: None for v in khoa.values()},
            }

        body_202 = r.json() or {}
        # Cung ly do nhu che do text: `trace_id` o GOC than 202 (`turns.py:209`), con
        # `turn_id` nam trong `data`. Doc mot lan de khong parse JSON hai lan.
        trace_id = body_202.get("trace_id")
        turn_id = (body_202.get("data") or {}).get("turn_id")
        if not turn_id:
            return {
                "nhan": nhan,
                "trace_id": trace_id,
                "ms_tong": ms_202,
                "ms_202": ms_202,
                "http": 202,
                "cat_cut": False,
                "loi": "202 khong co data.turn_id - khong loc duoc event, bo luot nay",
                **{v: None for v in khoa.values()},
            }

        so_bo_qua = 0

        async def _cho():
            """Chờ tới khi lượt KẾT THÚC — và lượt có **hai** kiểu kết thúc.

            ## Vì sao không chỉ chờ `assistant.response`

            Lệnh chạm bước S2 (mở cửa sổ, mở cửa, chỉnh ghế) không trả lời mà **hỏi lại**
            tài xế để xin duyệt. `ivi_events.py:467` nói thẳng: nhánh đó *"có tiếng nói mà
            không có `assistant.response`"* — câu hỏi duyệt đi ra bằng `assistant.status`
            với `state="waiting_approval"` (issue #215).

            Bản đầu chỉ chờ `assistant.response`, nên mọi lượt cần duyệt bị treo tới trần
            60 s rồi ghi là **lỗi**. Gặp thật ở run `20260825T083929`: câu *"Trong xe ngột
            ngạt quá, xử lý giúp tôi"* hỏng 6/6 ở mọi mức N, trong khi dữ liệu thô cho thấy
            `transcript.final` tới lúc 236 ms và `assistant.speech` tới lúc 18 s — tức lượt
            chạy hoàn toàn bình thường và đang **đợi người bấm Duyệt**. Nó bị đếm là hỏng
            chỉ vì phép đo không biết nhánh đó tồn tại.

            `assistant.status` KHÔNG phải lúc nào cũng là kết thúc: nó còn mang
            `routing`/`retrieving`/`composing`/`executing`. Chỉ `waiting_approval` mới là
            điểm dừng.
            """
            # `ma_duyet` phai `nonlocal`: gan trong ham long ma khong khai thi Python coi
            # no la bien cuc bo cua `_cho()`, va ban ghi o ngoai mai mai thay `None`.
            nonlocal so_bo_qua, ma_duyet
            while True:
                ev = json.loads(await ws.recv())
                # Event của lượt KHÁC (lượt trước, hoặc replay lúc handshake) không được
                # chạm vào đồng hồ. Đếm lại để báo cáo còn kiểm chứng được là có lọc thật.
                if ev.get("turn_id") != turn_id:
                    so_bo_qua += 1
                    continue
                loai = ev.get("type")
                # `approval.required` di TRUOC `assistant.status` va la cho DUY NHAT
                # mang `approval_id` (`ivi_events.py:553-557`); payload cua
                # `assistant.status` chi co `{state, message}`. Khong bat o day thi
                # sau luot khong con duong nao chot cai approval dang treo — xem
                # `_don_phe_duyet_dang_treo`.
                if loai == "approval.required":
                    ma_duyet = (ev.get("payload") or {}).get("approval_id") or ma_duyet
                if loai == "assistant.status" and (ev.get("payload") or {}).get("state") == "waiting_approval":
                    loai = "cho_duyet"
                if loai in moc and moc[loai] is None:
                    moc[loai] = round((time.perf_counter() - t0) * 1000, 1)
                if loai in ("assistant.response", "cho_duyet"):
                    return ev

        ket = await asyncio.wait_for(_cho(), timeout=TRAN_DO_S)
        cho_duyet = ket.get("type") == "assistant.status"
        return {
            "nhan": nhan,
            "turn_id": turn_id,
            "trace_id": trace_id,
            "so_event_bo_qua": so_bo_qua,
            # Luot cho duyet la mot KET THUC HOP LE, khong phai loi. Ghi lai kieu ket thuc
            # de doc bang khong nham "he hoi lai" voi "he khong tra loi".
            "ket_thuc": "cho_duyet" if cho_duyet else "tra_loi",
            "approval_id": ma_duyet,
            "ms_tong": moc["cho_duyet"] if cho_duyet else moc["assistant.response"],
            "ms_202": ms_202,
            "http": 202,
            "cat_cut": False,
            "loi": None,
            **{khoa[k]: v for k, v in moc.items()},
        }
    except Exception as exc:  # noqa: BLE001
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "nhan": nhan,
            "trace_id": trace_id,
            "ms_tong": ms,
            "ms_202": None,
            "http": None,
            "cat_cut": ms >= TRAN_DO_S * 1000 - 500,
            "loi": f"{type(exc).__name__}: {exc}"[:200],
            **{khoa[k]: v for k, v in moc.items()},
        }


# --------------------------------------------------------------- thống kê


def _thong_ke(ban_ghi: list[dict]) -> dict:
    ok = [r for r in ban_ghi if r["loi"] is None and r["ms_tong"] is not None]
    ms = sorted(r["ms_tong"] for r in ok)
    chung = {
        "n_mau": len(ban_ghi),
        "n_thanh_cong": len(ms),
        "so_loi": sum(1 for r in ban_ghi if r["loi"]),
        "so_cat_cut": sum(1 for r in ban_ghi if r["cat_cut"]),
    }
    if not ms:
        return chung
    p50 = statistics.median(ms)
    p95 = ms[min(len(ms) - 1, int(len(ms) * 0.95))]
    return {
        **chung,
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "max_ms": ms[-1],
        "nguong_p50_ms": NGUONG_P50_MS,
        "nguong_p95_ms": NGUONG_P95_MS,
        "p50_dat": p50 <= NGUONG_P50_MS,
        "p95_dat": p95 <= NGUONG_P95_MS,
        "so_vuot_p95": sum(1 for m in ms if m > NGUONG_P95_MS),
        # "Cham" va "hong" la HAI chuyen. Mot luot planner 28 giay roi tra ve clarify van
        # dem la thanh cong o cot tren (HTTP 200 that), nen thieu cot nay thi bang che mat
        # that bai. `co_plan` chi co o che do text; che do voice de None.
        "so_bi_tu_choi": sum(1 for r in ok if r.get("bi_tu_choi")),
        "so_ra_plan": sum(1 for r in ok if r.get("co_plan") is True),
        "so_biet_co_plan": sum(1 for r in ok if r.get("co_plan") is not None),
    }


def _theo_nhan(ban_ghi: list[dict]) -> dict:
    return {n: _thong_ke([r for r in ban_ghi if r["nhan"] == n]) for n in sorted({r["nhan"] for r in ban_ghi})}


# --------------------------------------------------------------- vòng đo


async def _don_phe_duyet_dang_treo(client, base_url: str, token: str, ket_lo: list[dict]) -> None:
    """Chốt mọi approval vừa sinh ra trong lô này, bằng cách **từ chối**.

    ## Vì sao phải dọn: không dọn thì phép đo tự chặn chính nó

    Mỗi phiên chỉ được có **một** approval `pending` (chỉ mục duy nhất từng phần trong
    `src/db.py`, ADR-017). Script dùng lại đúng bộ phiên cho mọi lô và mọi mức N, nên
    lượt S2 nào đi ngay sau một lượt S2 khác trong cùng phiên đều bị chặn — và câu trả
    lời nó nhận là *"Đang có một lệnh chờ bạn xác nhận"*, không phải một kế hoạch.

    Đo được trên VPS, run `20260827T093455`: 3/6 lượt planner kết thúc `cho_duyet`, 3
    lượt còn lại **bị chính approval của lượt trước chặn**. Đọc bảng mà không biết
    chuyện này thì kết luận "planner ra kế hoạch 3/6" — trong khi con số thật là **6/6**
    và hệ đang làm đúng bất biến an toàn của nó. Cái bẫy ấy đã làm hỏng một bản phân
    tích trước khi bị bắt bằng `GET /traces/{id}` (`safety_summary.outcome =
    pending_approval`).

    ## Vì sao **từ chối** chứ không phải **duyệt**

    Duyệt thì plan chạy thật, đổi trạng thái xe, và `state_version` mới đó lại đi vào
    mọi lượt sau — phép đo tự thêm một biến trôi theo thời gian. Từ chối là đường
    zero-side-effect có sẵn trong hợp đồng HITL (`src/api/approvals.py`): nó giải phóng
    ô `pending` và không chạm vào xe. Đúng thứ một phép đo độ trễ cần.

    Đánh đổi phải nói ra: vì không lượt nào được duyệt, **`tool` không bao giờ chạy**,
    nên run này không đo được chặng thực thi. Đó là giới hạn đã biết, không phải sự cố.

    Lỗi ở đây được **nuốt** có chủ ý: dọn dẹp hỏng thì lô sau đo lệch, nhưng làm cả run
    đổ vì một lần POST hụt còn tệ hơn. Số lần hụt in ra để không im lặng.
    """
    ma = [r.get("approval_id") for r in ket_lo if r.get("approval_id")]
    if not ma:
        return
    hut = 0
    for ma_duyet in ma:
        try:
            r = await client.post(
                f"{base_url}/approvals/{ma_duyet}/decision",
                json={"decision": "reject"},
                headers=_headers(token, idem=True),
            )
            if r.status_code != 200:
                hut += 1
        except Exception:  # noqa: BLE001 - xem docstring: don dep hong khong duoc lam do ca run
            hut += 1
    if hut:
        print(f"    [canh bao] {hut}/{len(ma)} approval khong chot duoc — lo sau co the bi chan")


async def _chay_mot_muc(
    args, base_url: str, token: str, phien: list, vong: int, n: int, wavs: list[bytes]
) -> list[dict]:
    """N lượt **đồng thời**, lặp `vong` vòng. Mỗi lượt đi bằng một phiên riêng.

    ## Mỗi vòng chạy ĐỦ bộ ca, chia thành lô N — nếu không thì không so ngang được

    Cách cũ lấy ca theo `(v * n + i) % len(CASES)`, nên **tỉ lệ ca đổi theo N**: ở N=2 thì
    18 mẫu chia đều 6 ca, còn ở N=3 thì `dieu_khien` chiếm 4/9 còn `planner` chỉ 1/9. Hậu
    quả đo được ở run `20260825T040635`: p50 ở N=3 (**1 429 ms**) *thấp hơn* p50 ở N=2
    (**3 624 ms**), không phải vì hệ nhanh lên mà vì N=3 rơi trúng nhiều câu rẻ hơn.

    Giờ mỗi vòng duyệt hết bộ ca, cắt thành lô `n` chạy đồng thời. Cùng một rổ ca ở mọi
    mức N, nên cột "Tong hop" so ngang được. Lô cuối có thể ngắn hơn `n` khi `len(bo)`
    không chia hết — ghi `n_lo` vào từng bản ghi để chuyện đó nhìn thấy được.
    """
    import httpx

    bo: list = list(CASES) if args.che_do == "text" else list(wavs)
    ban_ghi: list[dict] = []
    async with httpx.AsyncClient(timeout=TRAN_DO_S + 10) as client:
        for v in range(vong):
            # XOAY bo ca theo vong. Khong xoay thi lo luon gom cac ca LIEN KE trong CASES:
            # o N=2 thi (dieu_khien, dieu_khien) chay voi nhau, (planner, chitchat) chay voi
            # nhau, va `dieu_khien` KHONG BAO GIO dung chung lo voi `planner`. Do la mot
            # thien lech that, do duoc o run 20260825T042019: `dieu_khien` giu 213-736 ms o
            # moi muc N, trong khi cau hoi thuc su can tra loi la "mot lenh re den GIUA luc
            # mot luot planner dang chay thi mat bao lau".
            bo_v = bo[v % len(bo) :] + bo[: v % len(bo)]
            for dau in range(0, len(bo_v), n):
                lo = bo_v[dau : dau + n]
                cung_lo = [m[0] for m in lo]
                viec = []
                for i, muc in enumerate(lo):
                    sid, ws = phien[i]
                    if args.che_do == "text":
                        nhan, text = muc
                        viec.append(_mot_luot_text(client, base_url, token, sid, nhan, text))
                    else:
                        nhan, wav = muc
                        viec.append(_mot_luot_voice(client, base_url, token, sid, ws, nhan, wav))
                ket_lo = await asyncio.gather(*viec)
                for r in ket_lo:
                    # `cung_lo` cho biet luot nay chay CHUNG voi nhung ai. Thieu no thi
                    # khong the tra loi "cham vi ai" tu ban ghi.
                    ban_ghi.append({**r, "n_lo": len(lo), "cung_lo": cung_lo})
                # Chot moi approval vua sinh ra, TRUOC khi sang lo sau. Dong ho da dung
                # o tren nen viec nay khong lot vao `ms_tong` cua bat ky luot nao.
                await _don_phe_duyet_dang_treo(client, base_url, token, ket_lo)
    return ban_ghi


async def _do(args) -> dict:
    import httpx

    base_url = args.base_url.rstrip("/")
    muc = sorted({int(x) for x in args.moc.split(",") if x.strip()})
    if not muc:
        raise SystemExit("--moc rong")
    n_max = max(muc)

    wav_dir = Path(args.wav_dir) if args.wav_dir else WAV_DIR
    wavs: list[tuple[str, bytes]] = []
    if args.che_do == "voice":
        # Doc manifest de biet moi file NOI GI. Mot ban ghi khong biet minh do cau nao thi
        # khong dung de ket luan duoc gi — day la ly do khong gan nhan "voice" chung chung.
        loi_thoai: dict[str, str] = {}
        mf = wav_dir / "manifest.json"
        if mf.exists():
            loi_thoai = {m["file"]: m["text"] for m in json.loads(mf.read_text(encoding="utf-8"))}
        for f in sorted(wav_dir.glob("*.wav")):
            cau = loi_thoai.get(f.name)
            wavs.append((f"voice:{cau}" if cau else "voice_khong_ro", f.read_bytes()))
        if not wavs:
            raise SystemExit(f"khong thay WAV nao trong {wav_dir}")

    # `Origin` phai KHOP `CORS_ORIGINS` cua backend, khong phai chi "co mat". Mac dinh
    # suy tu chinh base_url, dung voi cau hinh mot-origin cua VPS (`van_hanh.md` §5).
    origin = args.origin or base_url.removesuffix("/api/v1").rstrip("/")

    print(f"base_url  = {base_url}")
    print(f"origin    = {origin}")
    print(f"che do    = {args.che_do}")
    print(f"cac muc N = {muc}, {args.vong} vong\n")

    suc_khoe = await _probe_healthz(base_url)
    print(f"healthz   = {suc_khoe.get('http')}")
    cau_hinh = _probe_llama(args.slm_endpoint)
    if cau_hinh["doc_duoc"]:
        print(
            f"llama     = n_ctx {cau_hinh['n_ctx']}, n_slots {cau_hinh['n_slots']}, kv_unified {cau_hinh['kv_unified']}\n"
        )
    else:
        print(f"llama     = KHONG doc duoc cau hinh ({cau_hinh.get('ly_do')}) — se ghi ro trong report\n")

    async with httpx.AsyncClient(timeout=60.0) as client:
        token = await _login(client, base_url, args.email, args.password)
        print(f"da dang nhap, tao {n_max} phien...")
        phien = []
        for _ in range(n_max):
            sid = await _tao_phien(
                client, base_url, token, args.vehicle_id, "voice" if args.che_do == "voice" else "text"
            )
            ws = await _mo_ws(base_url, token, sid, origin) if args.che_do == "voice" else None
            phien.append((sid, ws))
        print(f"xong {len(phien)} phien\n")

        # Hâm nóng: lượt đầu sau khi service lên đắt hơn hẳn (spike3: 562 token / 28 733 ms)
        # và không đại diện cho lúc chạy thật. KHÔNG tính vào thống kê.
        print("Ham nong (khong tinh vao thong ke)...", flush=True)
        for nhan, text in CASES[:2]:
            r = await _mot_luot_text(client, base_url, token, phien[0][0], nhan, text)
            print(f"  {nhan}: {r['ms_tong']:.0f} ms{' | LOI ' + str(r['loi']) if r['loi'] else ''}")
        print()

    ket_qua: dict = {}
    for n in muc:
        print(f"N={n} ({args.vong} vong)...", flush=True)
        ban_ghi = await _chay_mot_muc(args, base_url, token, phien, args.vong, n, wavs)
        tk = _thong_ke(ban_ghi)
        lo_ngan = sum(1 for r in ban_ghi if r.get("n_lo", n) < n)
        ket_qua[str(n)] = {
            "so_mau_lo_ngan": lo_ngan,
            "thong_ke": tk,
            "theo_nhan": _theo_nhan(ban_ghi),
            "ban_ghi": ban_ghi if args.giu_ban_ghi else [],
        }
        if tk.get("p50_ms") is None:
            print(f"    KHONG co mau thanh cong nao ({tk['so_loi']} loi)")
        else:
            print(
                f"    p50 {tk['p50_ms']:.0f} | p95 {tk['p95_ms']:.0f} | max {tk['max_ms']:.0f} ms"
                f" | vuot p95 {tk['so_vuot_p95']}/{tk['n_thanh_cong']}"
                f" | loi {tk['so_loi']}" + (f" | CAT CUT {tk['so_cat_cut']}" if tk["so_cat_cut"] else ""),
                flush=True,
            )

    if args.che_do == "voice":
        for _, ws in phien:
            if ws is not None:
                await ws.close()

    return {
        "base_url": base_url,
        "origin": origin,
        "che_do": args.che_do,
        "moc": muc,
        "vong": args.vong,
        "tran_do_s": TRAN_DO_S,
        "nguong": {"p50_ms": NGUONG_P50_MS, "p95_ms": NGUONG_P95_MS},
        "cau_hinh_llama": cau_hinh,
        "healthz": suc_khoe,
        "so_wav": len(wavs),
        "wav_dir": str(wav_dir),
        "ket_qua": ket_qua,
    }


# --------------------------------------------------------------- báo cáo


def _report_md(kq: dict, manifest: dict) -> str:
    ch = kq["cau_hinh_llama"]
    lines = [
        "# Luot that qua backend duoi tai dong thoi",
        "",
        f"- Run id: `{manifest['run_id']}`",
        f"- Commit: `{manifest['git_commit'][:12]}` (dirty: {manifest['git_dirty']})",
        f"- Base URL: `{kq['base_url']}` — che do **{kq['che_do']}**",
        f"- Nguong doi chieu: p50 {kq['nguong']['p50_ms']:.0f} ms, p95 {kq['nguong']['p95_ms']:.0f} ms",
        f"- Tran dung khi do: {kq['tran_do_s']:.0f}s (co y noi, de do duoc do tre THAT)",
    ]
    if ch.get("doc_duoc"):
        lines.append(
            f"- **Cau hinh llama-server: n_ctx {ch['n_ctx']}, n_slots {ch['n_slots']}, kv_unified {ch['kv_unified']}**"
        )
    else:
        lines.append(
            f"- **Cau hinh llama-server: KHONG doc duoc** ({ch.get('ly_do')}) — moi so sanh voi run khac deu la phong doan"
        )
    lines += [
        "",
        "## Tong hop",
        "",
        "| N | p50 (ms) | p95 (ms) | max (ms) | vuot p95 | bi tu choi | loi | cat cut | p50 dat | p95 dat |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for n, muc in kq["ket_qua"].items():
        t = muc["thong_ke"]
        if t.get("p50_ms") is None:
            lines.append(f"| {n} | - | - | - | - | - | {t['so_loi']}/{t['n_mau']} | {t.get('so_cat_cut', 0)} | - | - |")
            continue
        lines.append(
            f"| {n} | {t['p50_ms']:.0f} | {t['p95_ms']:.0f} | {t['max_ms']:.0f} "
            f"| {t['so_vuot_p95']}/{t['n_thanh_cong']} | **{t['so_bi_tu_choi']}**/{t['n_thanh_cong']} "
            f"| {t['so_loi']}/{t['n_mau']} | {t['so_cat_cut']} "
            f"| {'DAT' if t['p50_dat'] else '**TRUOT**'} | {'DAT' if t['p95_dat'] else '**TRUOT**'} |"
        )
    lines.append("")

    # Ca hai che do deu can tach: che do text tach theo duong di, che do voice tach theo
    # cau noi. Tron chung thi duong re che mat duong dat.
    lines += [
        "## Tach theo duong di",
        "",
        "| N | nhan | n mau | p50 (ms) | p95 (ms) | vuot p95 | ra plan |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for n, muc in kq["ket_qua"].items():
        for nhan, t in muc["theo_nhan"].items():
            if t.get("p50_ms") is None:
                lines.append(f"| {n} | {nhan} | {t['n_mau']} | - | - | {t['so_loi']} loi | - |")
            else:
                lines.append(
                    f"| {n} | {nhan} | {t['n_mau']} | {t['p50_ms']:.0f} | {t['p95_ms']:.0f} "
                    f"| {t['so_vuot_p95']}/{t['n_thanh_cong']} | {t['so_ra_plan']}/{t['so_biet_co_plan']} |"
                )
    lines.append("")

    lines += [
        "## Doc bang the nao",
        "",
        "1. **Cot 'Tong hop' so ngang duoc giua cac muc N** — moi vong chay DU bo ca, chia "
        "thanh lo N. Truoc 2026-08-25 thi khong: ti le ca doi theo N, va p50 o N=3 tung THAP HON "
        "p50 o N=2 chi vi N=3 roi trung nhieu cau re hon.",
        "2. **Tach theo nhan truoc khi ket luan.** `dieu_khien` khong cham SLM chut nao (router "
        "tat dinh), `so_tay` cham classify roi di RAG, `planner` la duong dat nhat va khong co "
        "loi vong. Tron chung thi duong re che mat duong dat.",
        "3. **Cot `bi tu choi` phai doc TRUOC cot p50.** Sau ADR-030, luot qua tai tra ve "
        "gan nhu tuc thi kem cau 'dang ban'. No la HTTP 200 va rat nhanh, nen no KEO p50 XUONG. "
        "Mot bang co p50 dep va `bi tu choi` cao khong phai he nhanh len — la mot phan nguoi "
        "dung khong duoc phuc vu. So sanh hai run phai so ca hai cot.",
        "4. **Cot `ra plan` tach 'cham' khoi 'hong'.** Mot luot planner 28 giay roi tra ve "
        "clarify van la HTTP 200, nen no dem la thanh cong o bang tong hop. `ra plan` dem so "
        "luot THAT SU sinh duoc ke hoach. `0/3` nghia la duong do khong chay, khong phai chay "
        "cham.",
        "5. **`cat cut` > 0** thi moi so trong dong do la CAN DUOI, khong phai gia tri.",
        "6. **Che do `text` la CAN DUOI cua luot thoai that** — khong co STT, khong co TTS.",
        "7. **`loi` khac 0 sau khi them van SLM la du kien**, khong phai su co: do chinh la "
        "'tu choi nhanh' dang lam viec. Doc `ban_ghi` (chay voi `--giu-ban-ghi`) de tach 'bi tu "
        "choi' khoi 'that su hong'.",
        "",
        "## Diem mu",
        "",
    ]
    lines += [f"- **{k}** - {v}" for k, v in BLIND_SPOTS.items()]
    lines.append("")
    return "\n".join(lines)


def _git(*args: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=15, check=False
        )
        return proc.stdout.strip()
    except Exception:  # noqa: BLE001 - khong co git thi manifest thieu mot truong
        return ""


def main() -> int:
    p = argparse.ArgumentParser(description="Do luot that qua backend khi nhieu nguoi dung cung luc")
    p.add_argument("--base-url", default="https://c4-app-192.io.vn/api/v1", help="goc API, ke ca /api/v1")
    p.add_argument("--che-do", choices=("text", "voice"), default="text")
    p.add_argument("--moc", default="1,2,3", help="cac muc N dong thoi")
    p.add_argument("--vong", type=int, default=3, help="so vong lap moi muc N")
    p.add_argument("--email", default="driver.demo@example.com")
    p.add_argument("--password", default="DemoDriver123!")
    # Khop mac dinh cua `src/config.py:165`. Doi o .env cua VPS thi phai truyen tay:
    # sai vehicle_id thi `POST /sessions` van tao duoc phien, nhung lenh dieu khien
    # ban vao mot xe khong ai nghe — va so do tre se DEP mot cach vo nghia.
    p.add_argument("--vehicle-id", default="vehicle-demo-01")
    p.add_argument("--slm-endpoint", default="http://127.0.0.1:8093", help="de trong thi bo qua probe cau hinh")
    p.add_argument(
        "--wav-dir",
        default=None,
        help="thu muc WAV cho che do voice; mac dinh tests/fixtures/voice/cham_slm (cau truot luat)",
    )
    p.add_argument(
        "--origin",
        default=None,
        help="header Origin cho /ws/ivi; mac dinh suy tu --base-url. Phai co trong CORS_ORIGINS "
        "cua backend, neu khong WS dong bang 4403 (giong het loi sai role).",
    )
    p.add_argument(
        "--giu-ban-ghi",
        action="store_true",
        help="ghi tung luot vao metrics.json, KEM `trace_id` — bat buoc neu muon chay doc_stage_tu_run.py sau do",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help=(
            "thu muc goc de ghi run; mac dinh eval/results/luot-that-dong-thoi TRONG repo. "
            "Tren MAY CHU hay tro ra ngoai repo (vi du ~/vivi-runs) — xem ghi chu o dau file."
        ),
    )
    p.add_argument("--git-commit", default=None, help="commit dua tu ngoai vao")
    args = p.parse_args()

    kq = asyncio.run(_do(args))

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f") + "Z"
    out = (Path(args.out_dir) if args.out_dir else RESULTS_ROOT) / run_id
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "suite": "luot-that-dong-thoi",
        "run_id": run_id,
        "run_uuid": str(uuid.uuid4()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": args.git_commit or _git("rev-parse", "HEAD") or "unknown",
        "git_dirty": bool(_git("status", "--porcelain")),
        "che_do": args.che_do,
        "base_url": kq["base_url"],
        # Bon run slm-dong-thoi thieu dung khoi nay. Xem docstring dau file.
        "cau_hinh_llama": kq["cau_hinh_llama"],
        "note": (
            "Do LUOT THAT qua backend (auth -> session -> turn), khong goi thang llama-server. "
            "Bo sung cho scripts/do_slm_dong_thoi.py, von di vong qua ca backend lan van SLM."
        ),
        "blind_spots": BLIND_SPOTS,
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

"""Trả lời phê duyệt bằng lời — ba nhánh terminal của `api_spec.md:643-644` (issue #107).

Đo trên backend thật trước khi viết, đúng kịch bản demo:

    Tài xế: "Mở kính bên lái 30%"
    VIVI:   "Tôi sẽ đưa kính trước bên lái về 30%. Bạn có đồng ý không?"
    Tài xế: "Đồng ý"
    VIVI:   "Tôi không tìm thấy thông tin này trong sổ tay xe."

Không phải "chưa làm": xe hỏi một câu rồi không hiểu chính câu trả lời của câu nó vừa
hỏi, và phê duyệt vẫn treo.

Đây cũng là **test an toàn #18** của `docs/safety_and_hitl.md`.

Bất biến nặng nhất: event chỉ là **handoff**. Backend không được commit quyết định
(`api_spec.md:278`). Nếu nó tự commit thì một câu lọt qua bộ dò sẽ thành hành động S2
thật, bỏ qua đúng cổng người-trong-vòng-lặp mà HITL sinh ra để giữ.

**Cả hai đường phải phủ.** Bản đầu của #107 chỉ móc vào `/turns/text`, và mọi test lúc
ấy cũng chỉ gọi `/turns/text` — nên chúng xanh trong khi **nói** "đồng ý" vẫn rơi xuống
tra sổ tay. Người dùng bắt được khi test tay. Đó là lý do khối cuối file này tồn tại.
"""

import contextlib
import uuid

import pytest

from src.api import session_state
from src.api.session_state import get_store
from tests.conftest import seed_test_user

_SCHEMA = {"X-Schema-Version": "1.0"}
_LOGIN = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}


@contextlib.asynccontextmanager
async def _bat_su_kien():
    """Thu mọi event của bus trong khối `async with`.

    Callback phải là **coroutine**: `IviEventBus.publish` `await` từng listener, nên
    truyền thẳng `list.append` sẽ ném `TypeError: object NoneType can't be used in
    'await' expression` mỗi lần phát. Bus nuốt lỗi ấy và đi tiếp nên test vẫn xanh —
    một lỗi chỉ hiện trong log, đúng loại dễ sống sót nhất.
    """
    from src.services.ivi_events import get_event_bus

    nhan: list[dict] = []

    async def _ghi(event):
        nhan.append(event)

    bus = get_event_bus()
    bus.add_global_listener(_ghi)
    try:
        yield nhan
    finally:
        bus.remove_global_listener(_ghi)


async def _auth(client) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", headers=_SCHEMA, json=_LOGIN)
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}", **_SCHEMA}


def _owned_session(user_id: str = "usr_driver_01") -> str:
    seed_test_user(user_id)  # sessions.user_id là FK từ #89
    return session_state.create_session(user_id, "vehicle-demo-01").session_id


async def _noi(client, headers: dict, session_id: str, text: str):
    """Một lượt `/turns/text`. Khoá idempotency mới mỗi lần — trùng khoá nghĩa là "cùng
    một request", và lượt thứ hai sẽ trả bản ghi cũ thay vì chạy thật."""
    return await client.post(
        "/api/v1/turns/text",
        json={"session_id": session_id, "text": text},
        headers={**headers, "Idempotency-Key": f"vi-{uuid.uuid4().hex[:12]}"},
    )


async def _xin_duyet(client, headers: dict, session_id: str) -> tuple[str, str]:
    """Dựng một phê duyệt đang chờ; trả `(approval_id, turn_id của lượt gốc)`."""
    r = await _noi(client, headers, session_id, "Mở kính bên lái 30%")
    data = r.json()["data"]
    assert data["status"] == "waiting_approval", data
    return data["pending_approval"]["approval_id"], data["turn_id"]


def _stub_stt(monkeypatch, text: str) -> None:
    from src.services import voice

    monkeypatch.setattr(voice, "get_stt_engine", lambda: object())
    monkeypatch.setattr(
        voice, "transcribe_raw", lambda audio: voice.Transcript(text=text, latency_ms=42.0, confidence=0.9)
    )


async def _noi_bang_giong(client, headers: dict, session_id: str):
    """`/turns/voice` trả 202 ngay; kết quả chỉ quan sát được qua sự kiện."""
    return await client.post(
        "/api/v1/turns/voice",
        params={"session_id": session_id},
        headers={**headers, "Content-Type": "audio/wav", "Idempotency-Key": f"v-{uuid.uuid4().hex[:12]}"},
        content=b"fake-wav-bytes",
    )


# --- Duong TEXT --------------------------------------------------------------


async def test_dong_y_bang_loi_ra_luot_rieng_va_khong_tao_plan(client):
    """Nhánh 1 — handoff. Lượt ý định là một lượt **riêng**, không mang plan nào."""
    headers = await _auth(client)
    sid = _owned_session()
    _, turn_goc = await _xin_duyet(client, headers, sid)

    r = await _noi(client, headers, sid, "Đồng ý")

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "completed"
    assert data["turn_id"] != turn_goc
    assert data.get("action_plan") is None
    # Không trả `pending_approval`: lượt này không sinh ra yêu cầu xác nhận nào.
    assert data.get("pending_approval") is None


async def test_tieng_tran_van_chi_la_handoff(client):
    """Bất biến của #107, nay **thu hẹp** chứ không bỏ — xem khối #191 ở cuối file.

    #107 cấm backend tự commit cho **mọi** cụm. #191 cho phép với cụm rõ ràng, và giữ
    nguyên lệnh cấm cho tiếng trần. Test này là nửa còn lại của lệnh cấm ấy.

    Kiểm bằng trạng thái bản ghi chứ không bằng body — body nói gì cũng được, còn
    `status` mới là thứ quyết định lệnh có chạy hay không.
    """
    headers = await _auth(client)
    sid = _owned_session()
    approval_id, _ = await _xin_duyet(client, headers, sid)

    await _noi(client, headers, sid, "Được")

    assert get_store().get(approval_id).status == "pending", "tiếng trần KHÔNG được commit"


async def test_su_kien_intent_dung_nam_truong_cua_hop_dong(client):
    """`api_spec.md:591` chốt đúng 5 trường. Thiếu `approval_id` thì IVI không có gì để
    gọi REST, và cả cơ chế handoff thành vô dụng; thiếu `committed` thì IVI không phân
    biệt được hai nhánh của #191 và gọi REST cho cả hai (#207a).

    So **bằng tập hợp**, không phải `<=`: đó là thứ bắt được payload phình ra ngoài spec.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        approval_id, turn_goc = await _xin_duyet(client, headers, sid)
        await _noi(client, headers, sid, "Đồng ý")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert len(intent) == 1, [e["type"] for e in nhan]
    assert set(intent[0]["payload"]) == {
        "approval_id",
        "original_turn_id",
        "decision",
        "approved_vehicle_state_version",
        "committed",
    }
    assert intent[0]["payload"]["approval_id"] == approval_id
    assert intent[0]["payload"]["original_turn_id"] == turn_goc
    assert intent[0]["payload"]["decision"] == "approve"
    assert isinstance(intent[0]["payload"]["approved_vehicle_state_version"], int)


async def test_mo_ho_thi_hong_lot_chu_khong_doan(client):
    """Nhánh 2 — `error(terminal=true)` + `turn.failed`.

    Đoán giữa "đồng ý" và "hủy" là quyết hộ tài xế một việc S2.
    """
    headers = await _auth(client)
    sid = _owned_session()
    approval_id, _ = await _xin_duyet(client, headers, sid)

    r = await _noi(client, headers, sid, "Đồng ý nhưng hủy")

    assert r.json()["data"]["status"] == "failed"
    # Mơ hồ thì tuyệt đối không được quyết hộ — phê duyệt phải còn nguyên.
    assert get_store().get(approval_id).status == "pending"


async def test_khong_co_gi_dang_cho_thi_canceled(client):
    """Nhánh 3 — `turn.canceled(reason="approval_not_pending")`.

    `canceled` chứ không `completed`: tài xế vừa trả lời một câu hỏi không tồn tại.
    """
    headers = await _auth(client)
    sid = _owned_session()

    r = await _noi(client, headers, sid, "Đồng ý")

    assert r.json()["data"]["status"] == "canceled"


async def test_tu_choi_bang_loi_ra_decision_reject(client):
    """`"không đồng ý"` chứa **cả hai** dấu hiệu. Phải ra `reject`, không phải mơ hồ, và
    tuyệt đối không phải `approve` — `approve` ở đây là duyệt đúng một lệnh vừa bị từ chối."""
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        await _xin_duyet(client, headers, sid)
        r = await _noi(client, headers, sid, "Không đồng ý")

    assert r.json()["data"]["status"] == "completed"
    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert intent[0]["payload"]["decision"] == "reject"


async def test_lenh_moi_trong_luc_cho_duyet_van_di_duong_thuong(client):
    """Bộ dò không được nuốt lệnh mới.

    `api_spec.md:642` đã đặc tả ca này (`APPROVAL_ALREADY_PENDING`, lượt thứ hai kết
    thúc như một câu hỏi lại). Nhận nhầm `"bật điều hòa"` thành câu trả lời phê duyệt là
    mất luôn hành vi ấy.
    """
    headers = await _auth(client)
    sid = _owned_session()
    await _xin_duyet(client, headers, sid)

    r = await _noi(client, headers, sid, "Bật điều hòa 24 độ")

    assert r.json()["data"]["status"] not in ("canceled", "failed")


async def test_cau_hoi_so_tay_trong_luc_cho_duyet_khong_bi_nuot(client):
    """Ca sát biên hơn: câu hỏi sổ tay ngắn cũng không được coi là câu trả lời."""
    headers = await _auth(client)
    sid = _owned_session()
    await _xin_duyet(client, headers, sid)

    r = await _noi(client, headers, sid, "Áp suất lốp bao nhiêu")

    assert r.json()["data"]["status"] not in ("canceled", "failed")


# --- Duong VOICE: cho ma bug that nam ----------------------------------------
#
# Ban dau cua #107 chi moc vao `/turns/text`, va moi test o tren cung chi goi
# `/turns/text` — nen chung xanh trong khi NOI "dong y" van roi xuong tra so tay.
# Day moi la duong tai xe that dung.


async def test_noi_dong_y_bang_giong_thi_chot(client, monkeypatch):
    """Đường **voice**, không phải text."""
    headers = await _auth(client)
    sid = _owned_session()
    approval_id, turn_goc = await _xin_duyet(client, headers, sid)

    async with _bat_su_kien() as nhan:
        _stub_stt(monkeypatch, "Đồng ý")
        r = await _noi_bang_giong(client, headers, sid)

    assert r.status_code == 202
    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert len(intent) == 1, [e["type"] for e in nhan]
    assert intent[0]["payload"]["approval_id"] == approval_id
    assert intent[0]["payload"]["original_turn_id"] == turn_goc
    assert intent[0]["payload"]["decision"] == "approve"
    # Sự kiện vẫn phát **và** quyết định đã chốt (#191). Hai chuyện độc lập: IVI cần
    # sự kiện để cập nhật màn hình dù ai là người chốt.
    assert get_store().get(approval_id).status != "pending"


async def test_luot_voice_y_dinh_van_co_transcript_final_truoc(client, monkeypatch):
    """Chặn **sau** `transcript.final`, không phải trước.

    Tài xế phải thấy mình vừa nói gì, kể cả khi lượt ấy đi đường tắt. Chặn sớm hơn là
    nuốt mất phản hồi duy nhất chứng minh STT đã nghe đúng.
    """
    headers = await _auth(client)
    sid = _owned_session()
    await _xin_duyet(client, headers, sid)

    async with _bat_su_kien() as nhan:
        _stub_stt(monkeypatch, "Đồng ý")
        await _noi_bang_giong(client, headers, sid)

    loai = [e["type"] for e in nhan]
    assert loai.index("transcript.final") < loai.index("approval.intent.detected")
    assert loai[-1] == "turn.completed", loai


async def test_noi_lenh_moi_bang_giong_van_di_duong_thuong(client, monkeypatch):
    """Lưới cho chính bản sửa: đường voice cũng không được nuốt lệnh mới."""
    headers = await _auth(client)
    sid = _owned_session()
    await _xin_duyet(client, headers, sid)

    async with _bat_su_kien() as nhan:
        _stub_stt(monkeypatch, "Bật điều hòa 24 độ")
        await _noi_bang_giong(client, headers, sid)

    assert "approval.intent.detected" not in [e["type"] for e in nhan]


# --- #196: bo do phe duyet khong duoc nuot lenh dieu khien -------------------


@pytest.mark.parametrize(
    ("cau", "tool"),
    [
        ("Dừng nhạc", "media_control"),
        ("Tạm dừng nhạc", "media_control"),
        ("Hủy dẫn đường", "set_navigation"),
    ],
)
async def test_lenh_mo_dau_bang_dung_hoac_huy_khong_bi_coi_la_tu_choi(client, cau, tool):
    """@danggiap123 bắt được khi test tay 19/08: nút tạm dừng ở màn Nhạc không có tác dụng.

    Bộ dò thấy câu mở đầu bằng `dừng`/`hủy` là chốt "ý định từ chối" rồi return, nên
    router **không bao giờ được gọi tới** — dù nó có sẵn kế hoạch chạy được cho cả ba.
    Triệu chứng: `status="canceled"` và câu trả lời về phê duyệt chẳng liên quan.
    """
    headers = await _auth(client)
    sid = _owned_session()

    r = await _noi(client, headers, sid, cau)

    data = r.json()["data"]
    assert data["status"] != "canceled", data
    plan = data.get("action_plan")
    assert plan is not None, data
    assert plan["steps"][0]["tool"] == tool


@pytest.mark.parametrize("cau", ["Dừng", "Hủy", "Thôi", "Không"])
async def test_tu_tu_choi_dung_tran_van_tu_choi_duoc_phe_duyet(client, cau):
    """Nửa còn lại của #196, và là thứ dễ hỏng nhất khi đảo thứ tự.

    `dừng`/`hủy` đứng **trần** không phải lệnh — router trả `not_control` — nên chúng
    phải tiếp tục đi vào nhánh phê duyệt. Sửa #196 mà làm mất ca này là đổi một bug lấy
    một bug tệ hơn: tài xế mất cách từ chối bằng lời.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        await _xin_duyet(client, headers, sid)
        r = await _noi(client, headers, sid, cau)

    assert r.json()["data"]["status"] == "completed"
    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert len(intent) == 1, [e["type"] for e in nhan]
    assert intent[0]["payload"]["decision"] == "reject"


async def test_dong_y_khi_khong_co_gi_cho_van_bao_dung_cau_cu(client):
    """Phép đảo **không** được đánh đổi câu báo này — `đồng ý` là `not_control` nên nó
    vẫn đi đường phê duyệt như trước."""
    headers = await _auth(client)
    sid = _owned_session()

    r = await _noi(client, headers, sid, "Đồng ý")

    assert r.json()["data"]["status"] == "canceled"


# --- Chot bang giong noi (#191) ----------------------------------------------
#
# Đảo lại bất biến của #107, có chủ đích và có lập luận.
#
# #107 chốt "backend không bao giờ tự commit", vì một câu nói lọt qua bộ dò sẽ thành
# hành động S2 bỏ qua cổng người-trong-vòng-lặp. Lập luận để đảo: cổng HITL đòi **một
# xác nhận có chủ ý của con người**, không đòi *một cú chạm*. Một cụm rõ ràng nói ra là
# xác nhận có chủ ý. Rủi ro còn lại là ASR nghe nhầm — và đó là rủi ro có thật, nên
# **bất đối xứng** dưới đây là thứ giữ hệ thống fail-closed, không phải cái nút bấm.


async def test_dong_y_ro_rang_thi_chot_luon(client):
    """Cụm rõ ràng (`đồng ý`, `xác nhận`, …) chốt thẳng, không đợi ai chạm màn hình."""
    headers = await _auth(client)
    sid = _owned_session()
    approval_id, _ = await _xin_duyet(client, headers, sid)

    await _noi(client, headers, sid, "Đồng ý")

    assert get_store().get(approval_id).status != "pending"


async def test_co_tran_khong_duoc_chot(client):
    """**Test này tồn tại để đỏ.**

    `ừ`/`vâng`/`được` xuất hiện quá nhiều trong hội thoại thường, và cái giá của một
    false accept ở đây là một hành động S2 thật — tự hạ kính, tự mở cửa. Ai đó sau này
    thấy hệ thống "khó tính" rồi gộp `_CO_TRAN` vào tập chốt thì test này phải đỏ.

    Không chốt **không** có nghĩa là bỏ qua: lượt vẫn phát `approval.intent.detected`
    để IVI làm nổi nút, đúng hành vi hôm nay.
    """
    headers = await _auth(client)
    sid = _owned_session()
    approval_id, _ = await _xin_duyet(client, headers, sid)

    await _noi(client, headers, sid, "Ừ")

    assert get_store().get(approval_id).status == "pending"


async def test_tu_choi_thi_chot_luon_ke_ca_tieng_tran(client):
    """Chiều từ chối **không** cần cụm rõ ràng, và đó là bất đối xứng cố ý.

    ASR nghe nhầm thành từ chối thì không mất gì: từ chối vốn đã là kết quả mặc định
    khi phê duyệt hết hạn. Nghe nhầm thành chấp nhận thì xe tự làm một việc S2.
    """
    headers = await _auth(client)
    sid = _owned_session()
    approval_id, _ = await _xin_duyet(client, headers, sid)

    await _noi(client, headers, sid, "Thôi")

    assert get_store().get(approval_id).status == "rejected"


async def test_noi_dong_y_lan_hai_khong_co_side_effect_thu_hai(client):
    """Single-use vẫn là single-use khi cửa vào là giọng nói."""
    headers = await _auth(client)
    sid = _owned_session()
    approval_id, _ = await _xin_duyet(client, headers, sid)

    await _noi(client, headers, sid, "Đồng ý")
    sau_lan_mot = get_store().get(approval_id).status
    await _noi(client, headers, sid, "Đồng ý")

    assert get_store().get(approval_id).status == sau_lan_mot


async def test_cau_hoi_phe_duyet_noi_ro_cach_tra_loi(client):
    """Hỏi có/không mà không nói cách đáp thì tài xế đưa tay ra màn hình theo phản xạ."""
    headers = await _auth(client)
    sid = _owned_session()
    r = await _noi(client, headers, sid, "Mở kính bên lái 30%")

    noi = r.json()["data"]["response"]["speak_text"].lower()
    # Phải nói ĐỘNG TỪ: câu cũ "Bạn có đồng ý không?" đã chứa sẵn cả hai từ khoá mà
    # không hề mời tài xế nói ra. Khẳng định yếu như thế thì xanh mà chẳng chứng minh gì.
    assert "nói" in noi, noi
    assert "đồng ý" in noi and "không" in noi


async def test_phe_duyet_het_han_thi_noi_dong_y_khong_thuc_thi(client):
    """Hết hạn (>=30 s) rồi mới nói *"đồng ý"* -> không có lệnh nào chạy.

    Đẩy `expires_at` về quá khứ thay vì chờ 30 giây thật. Hết hạn được phát hiện ở
    **thời điểm đọc** (`get`/`decide` tự CAS `pending -> expired`, xem docstring
    `src/agents/approval.py`), nên chỉ cần sửa hàng là đủ — không phải giả lập đồng hồ.

    Đường giọng nói **không** được có lối tắt nào quanh cổng này: nó đi qua đúng
    `chot_da_xac_thuc` mà nút bấm đi.
    """
    from datetime import UTC, datetime, timedelta

    headers = await _auth(client)
    sid = _owned_session()
    approval_id, _ = await _xin_duyet(client, headers, sid)

    store = get_store()
    store._connection.execute(  # noqa: SLF001 - đẩy đồng hồ, không có API công khai
        "UPDATE approvals SET expires_at = ? WHERE id = ?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), approval_id),
    )
    store._connection.commit()  # noqa: SLF001

    await _noi(client, headers, sid, "Đồng ý")

    assert get_store().get(approval_id).status == "expired"


# --- `committed`: IVI biết lượt này đã chốt hay chưa (#207a) ------------------
#
# #191 dựng một cổng bất đối xứng ở backend, rồi để IVI mù về nó: payload của hai nhánh
# giống hệt nhau ở cả bốn trường. Nên FE làm đúng thứ rẻ nhất — luôn gọi REST — và cú
# gọi ấy chốt hộ đúng cái mà #191 vừa từ chối chốt. Trường `committed` là thứ duy nhất
# phân biệt hai nhánh, nên nó phải nói **kết quả của store**, không phải nhãn của nhánh
# mã đã chạy.


async def test_cum_ro_rang_thi_bao_da_chot(client):
    """Nhánh đã chốt: IVI phải im lặng, không gọi REST nữa."""
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        await _xin_duyet(client, headers, sid)
        await _noi(client, headers, sid, "Đồng ý")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert intent[0]["payload"]["committed"] is True


async def test_tieng_tran_thi_bao_chua_chot_va_noi_ro_cach_tra_loi(client):
    """Nhánh chưa chốt — và câu thoại phải nói thật về nó.

    *"Bạn đã đồng ý. Tôi sẽ thực hiện ngay."* ở đây là một lời hứa suông: không có gì
    được chốt cả, và tài xế nghe xong sẽ không chạm nút. Câu thay thế phải **gọi tên**
    cụm cần nói, vì cụm ấy chính là thứ phân biệt hai nhánh — nói chung chung ("bạn xác
    nhận lại giúp tôi") thì tài xế lặp lại đúng tiếng trần vừa rồi và kẹt vòng lặp.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        approval_id, _ = await _xin_duyet(client, headers, sid)
        r = await _noi(client, headers, sid, "Được")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert intent[0]["payload"]["committed"] is False
    assert get_store().get(approval_id).status == "pending"
    noi = r.json()["data"]["response"]["speak_text"].lower()
    assert "đồng ý" in noi and "nút" in noi, noi
    assert "sẽ thực hiện" not in noi, noi


async def test_tu_choi_tran_van_bao_da_chot(client):
    """Nửa kia của bất đối xứng: từ chối trần **có** chốt, nên `committed` phải là True.

    Nếu ai đó cột trường này vào `ro_rang_ve_phe_duyet` cho gọn thay vì vào kết quả
    store thì đây là ca lộ ra — và hậu quả của nó là IVI gọi REST để từ chối một phê
    duyệt đã bị từ chối.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        approval_id, _ = await _xin_duyet(client, headers, sid)
        await _noi(client, headers, sid, "Thôi")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert intent[0]["payload"]["committed"] is True
    assert get_store().get(approval_id).status == "rejected"


async def test_het_han_giua_luc_chot_thi_ra_nhanh_khong_con_gi_cho(client, monkeypatch):
    """Khe đua duy nhất còn lại sau khi `_pending_locked` đã tự CAS `pending -> expired`.

    `pending_for_session` thấy bản ghi còn chờ, rồi nó hết hạn trước khi `decide()` chạm
    tới. Không có nhánh riêng thì lượt vẫn phát handoff và đọc *"Tôi sẽ thực hiện
    ngay"* cho một phê duyệt đã chết — rồi IVI làm nổi một cái nút bấm vào sẽ lỗi.

    Dựng bằng monkeypatch chứ không bằng đồng hồ: khe này rộng vài micro giây, và một
    test phải canh đúng lúc mới đỏ là một test sẽ xanh vì sai lý do. Vá được ở
    `src.api.approvals` vì `_chot_neu_du_dieu_kien` import **trong thân hàm**.
    """
    from src.api import approvals as mod_approvals

    async def chot_gia(approval_id, *, approve, schedule, khi_loi=None):
        return get_store().get(approval_id).model_copy(update={"status": "expired"})

    monkeypatch.setattr(mod_approvals, "chot_da_xac_thuc", chot_gia)

    headers = await _auth(client)
    sid = _owned_session()
    await _xin_duyet(client, headers, sid)

    r = await _noi(client, headers, sid, "Đồng ý")

    data = r.json()["data"]
    assert data["status"] == "canceled"
    assert "thực hiện" not in data["response"]["speak_text"].lower()


# --- #274/#299: cung lop loi, lan thu hai -----------------------------------


@pytest.mark.parametrize("cau", ["Dừng lại", "Hủy routine"])
async def test_cau_huy_routine_khong_bi_cong_phe_duyet_nuot(client, cau):
    """Cùng lớp lỗi với #196, tái xuất khi thêm `disposition="routine"` (#274).

    Phép loại ở `turns.py` chỉ kể tên `"control"`, nên một disposition mới rơi thẳng vào
    nhánh phê duyệt. Đo end-to-end qua trình duyệt 30/08, **sau** khi router đã nhận ra
    ý định hủy:

        POST /turns/text "Dừng lại"
          -> status="canceled", "Hiện không có yêu cầu nào đang chờ bạn xác nhận."

    Tài xế xin hủy Routine, xe trả lời về một cơ chế khác hẳn. Không có test end-to-end
    thì không thấy: unit test của router gọi thẳng `DeterministicControlRouter`, còn cổng
    này đứng **trước** graph.
    """
    headers = await _auth(client)
    sid = _owned_session()

    r = await _noi(client, headers, sid, cau)

    data = r.json()["data"]
    assert data["status"] != "canceled", data
    assert "đang chờ bạn xác nhận" not in (data["response"]["speak_text"] or ""), data


async def test_dang_cho_duyet_thi_dung_lai_van_la_bac_lenh_do(client):
    """Nửa còn lại, và là nửa quan trọng hơn: **an toàn thắng**.

    Khi một lệnh S2 đang treo, `"Dừng lại"` nghĩa là *bác lệnh đó* — không phải *hủy một
    Routine*. Tha `routine` vô điều kiện ở cổng kia thì câu này đi xuống graph, trả "không
    có Routine nào đang chạy", và **lệnh S2 vẫn treo nguyên** trong khi tài xế tưởng vừa
    chặn được nó. Nên phép tha phải kèm điều kiện `pending is None`.

    Chấm bằng `approval.intent.detected`, không bằng `status`: bác một phê duyệt **đang
    treo** trả `status="completed"` (lượt hoàn tất bình thường) — `"canceled"` chỉ dành cho
    ca không có gì để duyệt. Ca #196 ngay bên trên khoá đúng cùng một hình dạng ấy.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        await _xin_duyet(client, headers, sid)
        await _noi(client, headers, sid, "Dừng lại")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert len(intent) == 1, [e["type"] for e in nhan]
    assert intent[0]["payload"]["decision"] == "reject"

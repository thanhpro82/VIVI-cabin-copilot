"""Nhánh phê duyệt mơ hồ phải có tiếng. Issue #212.

## Hiện trạng đo được (develop @ 0fad06b)

Khi tài xế trả lời phê duyệt bằng một câu mơ hồ (*"Đồng ý nhưng hủy"*),
`emit_approval_intent_ambiguous` phát đúng hai sự kiện:

    error(code="APPROVAL_INTENT_AMBIGUOUS", terminal=True, message="Tôi chưa rõ...")
    turn.failed(code="APPROVAL_INTENT_AMBIGUOUS")

`error` **không** đi qua `_publish_assistant_response`, nên không có `assistant.speech` —
câu mời nói lại chỉ **hiện chữ**, không ai đọc nó.

## Vì sao nó thành vấn đề đúng lúc này

Sau #211, mic **tự mở lại** ở đúng nhánh này. Tức là: mic bật, đèn thu sáng, và xe im.
Tài xế đang lái không nhìn màn hình sẽ không biết vì sao mic vừa bật, cũng không biết máy
đang chờ mình nói lại. Trước #211 lỗ này lành hơn — mic tắt, tài xế đằng nào cũng phải
nhìn màn hình để chạm nút, và lúc nhìn thì thấy chữ.

## Vì sao `assistant.speech` chứ không `assistant.response`

Lượt này **hỏng** (`turn.failed`). `assistant.response` là câu trả lời của trợ lý cho một
lượt đã hoàn tất, và nó là closed schema — mượn nó ở đây là nói rằng lượt có câu trả lời
trong khi nó vừa thất bại.

Tiền lệ đã có và cùng hình dạng: nhánh chờ duyệt S2 phát **tiếng mà không có
`assistant.response`** (#215, xem docstring `_phat_tieng_noi`). Câu hỏi duyệt đi ra bằng
`assistant.status`; ở đây câu mời nói lại đi ra bằng `error`. Kênh chữ đã có người lo —
thứ còn thiếu đúng là kênh tiếng.
"""

from __future__ import annotations

import pytest

from src.services.ivi_events import IviEventBus, emit_approval_intent_ambiguous

MO_HO = "Tôi chưa rõ bạn đồng ý hay không. Bạn nói lại giúp tôi nhé."


async def _bat(monkeypatch, *, wav: bytes | None = b"RIFF-gia") -> list[dict]:
    async def gia_lap(turn_id, trace_id, text):
        gia_lap.da_goi.append(text)
        return wav

    gia_lap.da_goi = []
    monkeypatch.setattr("src.services.ivi_events.synthesize_speech", gia_lap)

    bus = IviEventBus()
    nhan: list[dict] = []

    async def ghi(session_id, event_type, turn_id, trace_id, payload):
        nhan.append({"type": event_type, "payload": payload})

    monkeypatch.setattr(bus, "publish", ghi)
    await emit_approval_intent_ambiguous(bus, "ses_1", "turn_1", "tr_1", message=MO_HO)
    return nhan, gia_lap.da_goi


async def test_nhanh_mo_ho_phat_assistant_speech(monkeypatch):
    nhan, da_goi = await _bat(monkeypatch)
    assert [e["type"] for e in nhan if e["type"] == "assistant.speech"], [e["type"] for e in nhan]
    assert da_goi == [MO_HO], "phải đọc đúng câu đang hiện trên màn hình"


async def test_tieng_phai_den_truoc_error(monkeypatch):
    """Thứ tự là ràng buộc, không phải khẩu vị.

    FE mở lại mic trong một effect phụ thuộc `lanMoLaiMic`, mà `lanMoLaiMic` đổi khi
    `error` tới (`DriverShellProvider.tsx`). Effect ấy đọc `activeSpeechRef.current` để
    quyết định chờ `ended` hay mở mic ngay. `assistant.speech` tới **sau** `error` thì lúc
    effect chạy ref vẫn rỗng, mic mở ngay, và giọng đọc chen vào giữa lúc đang thu — đúng
    thứ ta vừa thêm tiếng để tránh.
    """
    nhan, _ = await _bat(monkeypatch)
    loai = [e["type"] for e in nhan]
    assert loai.index("assistant.speech") < loai.index("error"), loai


async def test_van_giu_dung_mot_su_kien_terminal(monkeypatch):
    """Bất biến của `api_spec.md`: mỗi lượt đúng một sự kiện terminal.

    `assistant.speech` không terminal nên nó không phá bất biến — nhưng test này khoá
    điều đó thay vì để nó là một câu trong mô tả PR.
    """
    nhan, _ = await _bat(monkeypatch)
    assert [e["type"] for e in nhan].count("turn.failed") == 1
    assert sum(1 for e in nhan if e["type"] == "error" and e["payload"].get("terminal")) == 1


async def test_khong_muon_assistant_response(monkeypatch):
    """Lượt này **hỏng**. Phát `assistant.response` là nói rằng nó có câu trả lời."""
    nhan, _ = await _bat(monkeypatch)
    assert "assistant.response" not in [e["type"] for e in nhan]


async def test_tts_hong_thi_van_ra_du_hai_su_kien_cu(monkeypatch):
    """Fail-open. Mất tiếng là mất tiện nghi; mất `turn.failed` là treo lượt."""
    nhan, _ = await _bat(monkeypatch, wav=None)
    loai = [e["type"] for e in nhan]
    assert "assistant.speech" not in loai
    assert loai == ["error", "turn.failed"], loai


@pytest.mark.parametrize("no", [RuntimeError("model chết"), MemoryError()])
async def test_tts_nem_loi_cung_khong_lam_hong_luot(monkeypatch, no):
    """`synthesize_speech` hứa không bao giờ raise, nhưng lời hứa ấy ở file khác. Ở đây
    ta không dựa vào nó: mất tiếng không được phép nuốt mất `turn.failed`."""

    async def no_loi(turn_id, trace_id, text):
        raise no

    monkeypatch.setattr("src.services.ivi_events.synthesize_speech", no_loi)
    bus = IviEventBus()
    nhan: list[str] = []

    async def ghi(session_id, event_type, turn_id, trace_id, payload):
        nhan.append(event_type)

    monkeypatch.setattr(bus, "publish", ghi)
    await emit_approval_intent_ambiguous(bus, "ses_1", "turn_1", "tr_1", message=MO_HO)
    assert nhan == ["error", "turn.failed"], nhan

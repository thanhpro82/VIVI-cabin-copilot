"""Đường lui khi node quên `speak_text` phải **có trần**. Blocker #2 của @thanhpro82 ở PR #221.

## Vì sao đường lui cũ nguy hiểm

Bản đầu của PR là `result.get("speak_text") or result.get("response_text", "")`. Một node
quên `speak_text` thì `response_text` — tới `QUOTE_MAX_CHARS = 1.200` ký tự nguyên văn sổ
tay — quay lại **cả UI lẫn TTS**, phá đúng bất biến sản phẩm mà PR ấy dựng lên. Đo được
13/08 sau khi cài Piper: đọc nguyên đoạn trích ra **65,6 giây audio** và một
`assistant.speech` **4,60 MB** trong một khung WebSocket.

## Vì sao chọn "thay đường lui" chứ không "chứng minh mọi đường đều có `speak_text`"

@thanhpro82 cho hai lối. Lối chứng minh **không chứng minh được cho tương lai**: nó đúng
hôm nay và im lặng sai vào ngày ai đó thêm một node mới. `approvals.py` đã là một ví dụ —
nó dựng payload bằng tay, ngoài `compose_node`.

Đường lui nay cắt ở **biên câu**, trần `MAX_SPEECH_CHARS` — cùng phép cắt mà
`synthesize_speech` đã áp cho `speak_text` quá dài, nên hai chỗ không thể lệch nhau về độ
dài tối đa. Node quên `speak_text` vẫn nói được một câu tử tế; thứ nó **không** làm được
nữa là đổ 1.200 ký tự lên màn hình và vào loa.
"""

from __future__ import annotations

import pytest

from src.services.ivi_events import (
    MAX_SPEECH_CHARS,
    assistant_response_payload,
    cau_de_noi,
    cau_ngan,
)

#: Đoạn dài như một trích dẫn sổ tay thật — `QUOTE_MAX_CHARS` là 1.200.
DOAN_DAI = ("Đây là một câu sổ tay đủ dài để lấp chỗ. " * 40).strip()


def _luot_quen_speak_text() -> dict:
    """Đúng hình dạng một node cũ trả về: có `response_text`, **không** có `speak_text`."""
    return {"response_text": DOAN_DAI, "outcome": "grounded_answer", "route_reason": "manual_question"}


def test_doan_dai_khong_ra_duoc_day_khi_node_quen_speak_text():
    ra = assistant_response_payload(_luot_quen_speak_text())
    assert len(ra["display_text"]) <= MAX_SPEECH_CHARS, len(ra["display_text"])
    assert len(ra["speak_text"]) <= MAX_SPEECH_CHARS, len(ra["speak_text"])


def test_duong_lui_khong_cat_giua_chung_mot_cau():
    """Cắt ở biên câu, không cắt giữa chừng — một câu cụt đọc ra loa nghe như máy hỏng."""
    noi = cau_ngan(_luot_quen_speak_text())
    assert noi.rstrip().endswith("."), repr(noi[-40:])


def test_duong_lui_van_noi_duoc_mot_cau_tu_te():
    """Trần **không** được biến thành im lặng: node quên `speak_text` là lỗi của lập trình
    viên, không phải lý do để tài xế nhận về một trợ lý câm."""
    noi = cau_ngan(_luot_quen_speak_text())
    assert len(noi) > 40
    assert "Đây là một câu sổ tay" in noi


def test_co_speak_text_thi_dung_nguyen_khong_cat():
    """Đường lui chỉ chạy khi **thiếu** `speak_text`. Có rồi thì trần của
    `synthesize_speech` lo phần còn lại — cắt hai lần là cắt nhầm."""
    ngan = "Đã bật điều hòa."
    assert cau_ngan({"response_text": DOAN_DAI, "speak_text": ngan}) == ngan


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"response_text": ""},
        {"response_text": None},
        {"speak_text": ""},
    ],
)
def test_state_rong_hay_hong_thi_khong_no(result: dict):
    """Payload dựng từ state của graph — hình dạng nó là **dữ liệu ngoài** với hàm này."""
    assert cau_ngan(result) == ""
    assert cau_de_noi(result) == ""


def test_tran_dung_bang_tran_cua_duong_tts():
    """Hai chỗ cắt phải cùng một con số. Lệch nhau thì một trong hai là lưới thừa, và cái
    lỏng hơn quyết định — tức lưới chặt hơn chỉ tạo cảm giác an toàn."""
    from src.services import ivi_events

    assert ivi_events.MAX_SPEECH_CHARS == MAX_SPEECH_CHARS
    ra = assistant_response_payload(_luot_quen_speak_text())
    assert len(ra["speak_text"]) <= ivi_events.MAX_SPEECH_CHARS

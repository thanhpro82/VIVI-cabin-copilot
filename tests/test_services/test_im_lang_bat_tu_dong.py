"""Xe chỉ nói khi được gọi — spec §3.5.

Đo bằng graph thật (29/08), người nói với NGƯỜI, mic đang mở:

    "Lát nữa mở cốp lấy đồ nhé"          -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
    "Hôm qua tôi bật đèn pha suốt"       -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
    "Thôi tắt nhạc đi để anh nghe điện"  -> "Tôi không tìm thấy thông tin này trong sổ tay xe."

Xe **chen vào cuộc nói chuyện**, vài giây một lần. Chạy nhầm một lệnh thì tắt đi là xong;
cái này khiến người ta tắt luôn trợ lý.

Chỉ tắt **kênh nói**. Màn hình vẫn hiện, vì nó không làm phiền ai và là dấu vết để tài xế
hiểu vì sao vòng đếm ngược vừa tắt.

## Hai chỗ đọc, không phải một

`assistant_response_payload` dựng câu cho WS, còn `emit_turn_lifecycle` đọc **thẳng từ
state** để gọi TTS (`result.get("speak_text") or result.get("response_text")`). Sửa mỗi
payload thì **loa vẫn đọc** — đúng cái ta đang cố chặn. Nên có test riêng cho đường TTS.
"""

from __future__ import annotations

import pytest

from src.services.ivi_events import assistant_response_payload, im_lang

KHONG_HIEU = {
    "response_text": "Tôi không tìm thấy thông tin này trong sổ tay xe.",
    "speak_text": "Tôi không tìm thấy thông tin này trong sổ tay xe.",
    "outcome": "grounded_refusal",
    "route_reason": "default_to_manual",
}

DA_LAM = {
    "response_text": "Đã thực hiện lệnh trên xe mô phỏng.",
    "speak_text": "Đã thực hiện lệnh trên xe mô phỏng.",
    "outcome": "completed",
    "route_reason": "deterministic_rule",
}


# --- Luật, kiểm thuần -------------------------------------------------------


def test_bat_tu_dong_ma_khong_hieu_thi_im():
    assert im_lang({**KHONG_HIEU, "bat_tu_dong": True}) is True


def test_bam_mic_tay_thi_khong_im():
    """Tài xế chủ động hỏi thì im lặng mới là thô lỗ — họ đang chờ một câu trả lời."""
    assert im_lang({**KHONG_HIEU, "bat_tu_dong": False}) is False


def test_vang_co_thi_khong_im():
    """Vắng `bat_tu_dong` = `manual`. Fail về phía **nói**, không về phía im: một client
    cũ không được biến thành một trợ lý câm."""
    assert im_lang(KHONG_HIEU) is False


def test_bat_tu_dong_ma_hieu_thi_khong_im():
    assert im_lang({**DA_LAM, "bat_tu_dong": True}) is False


def test_dung_lai_dung_con_nghe_tiep_chu_khong_co_bang_rieng():
    """"Không đáng nghe tiếp" và "không đáng nói ra" là **cùng một** phán đoán: xe vừa
    không hiểu câu vừa rồi. Hai bảng song song là cách để chúng lệch nhau."""
    from src.agents.nghe_tiep import con_nghe_tiep

    for state in (KHONG_HIEU, DA_LAM, {"outcome": "clarify", "route_reason": "missing_fan_level"}):
        assert im_lang({**state, "bat_tu_dong": True}) is not con_nghe_tiep(state)


# --- Payload ----------------------------------------------------------------


def test_payload_bat_tu_dong_ma_khong_hieu_thi_speak_text_rong():
    ra = assistant_response_payload({**KHONG_HIEU, "bat_tu_dong": True})
    assert ra["speak_text"] == ""
    assert ra["mo_mic_ngan"] is False


def test_payload_van_hien_tren_man_hinh():
    """Chỉ tắt kênh NÓI."""
    ra = assistant_response_payload({**KHONG_HIEU, "bat_tu_dong": True})
    assert ra["display_text"] == KHONG_HIEU["response_text"]


def test_payload_bam_mic_tay_thi_van_noi():
    ra = assistant_response_payload({**KHONG_HIEU, "bat_tu_dong": False})
    assert ra["speak_text"] == KHONG_HIEU["speak_text"]


def test_payload_bat_tu_dong_ma_hieu_thi_van_noi():
    """Ca đối chứng, và là ca thường gặp nhất: tài xế nối lệnh thứ hai trong cửa sổ nghe
    tiếp. Im lặng ở đây là bỏ mất câu xác nhận — thứ **duy nhất** cho họ biết xe vừa làm
    gì, và là một trong ba thứ ADR-025 dựa vào để nhận rủi ro ghép ngữ cảnh."""
    ra = assistant_response_payload({**DA_LAM, "bat_tu_dong": True})
    assert ra["speak_text"] == DA_LAM["speak_text"]
    assert ra["mo_mic_ngan"] is True


def test_payload_bat_tu_dong_ma_nghe_hut_cung_im():
    """`manh_khong_khop_mau` sau một cửa sổ tự mở: câu *"Tôi chưa nghe rõ…"* là đúng khi
    tài xế bấm mic, nhưng khi mic tự mở thì rất có thể họ không hề nói với xe."""
    ra = assistant_response_payload(
        {
            "response_text": "Tôi chưa nghe rõ. Bạn muốn quạt gió mức mấy, từ 0 đến 3?",
            "speak_text": "Tôi chưa nghe rõ. Bạn muốn quạt gió mức mấy, từ 0 đến 3?",
            "outcome": "not_control",
            "route_reason": "manh_khong_khop_mau",
            "bat_tu_dong": True,
        }
    )
    assert ra["speak_text"] == ""


# --- Đường TTS: chỗ dễ sót nhất ---------------------------------------------


@pytest.mark.parametrize(
    ("state", "mong_doc"),
    [
        ({**KHONG_HIEU, "bat_tu_dong": True}, ""),
        ({**KHONG_HIEU, "bat_tu_dong": False}, KHONG_HIEU["speak_text"]),
        ({**DA_LAM, "bat_tu_dong": True}, DA_LAM["speak_text"]),
    ],
)
def test_cau_dua_cho_tts_di_qua_cung_mot_luat(state: dict, mong_doc: str):
    """`emit_turn_lifecycle` đọc **thẳng từ state** để gọi TTS, không đọc payload. Nếu chỉ
    sửa payload thì loa vẫn đọc câu từ chối vào giữa cuộc nói chuyện — đúng thứ đang cố
    chặn. Hàm này là chỗ duy nhất cả hai đường cùng đọc.
    """
    from src.services.ivi_events import cau_de_noi

    assert cau_de_noi(state) == mong_doc


def test_cau_de_noi_van_lui_ve_response_text_cho_node_cu():
    """Giữ nguyên đường lui `or response_text` cho node/test cũ chưa trả `speak_text` —
    xoá nó là làm câm một loạt lượt vì một lý do khác hẳn lý do của spec này."""
    from src.services.ivi_events import cau_de_noi

    assert cau_de_noi({"response_text": "Xin chào", "outcome": "completed"}) == "Xin chào"

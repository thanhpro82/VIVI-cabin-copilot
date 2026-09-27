"""Đ4 — hỏi *làm được không* thì không được hỏi ngược lại về slot.

```
'có thể chỉnh độ ngả ghế không' → clarify | missing_seat_side    ← sai
'có thể chỉnh độ cao ghế không' → not_control | manual_question  ← đúng
```

Hai câu cùng dạng, hai kết quả — và câu "đúng" chỉ đúng **tình cờ**: `độ cao ghế` không
khớp axis nào nên rơi xuống mặc định, còn `độ ngả ghế` chứa `ngả ghế` nên vào matcher rồi
tắc ở `_side`. Không có luật nào phân biệt hai câu; chỉ có một sự trùng hợp.
"""

import pytest

from src.agents.router import DeterministicControlRouter

router = DeterministicControlRouter()


@pytest.mark.parametrize(
    "text",
    [
        "Có thể chỉnh độ ngả ghế không?",
        "Có thể chỉnh độ cao ghế không?",
        "Mở cửa sổ bên lái được không?",
        "Sưởi ghế chỉnh được không?",
    ],
)
def test_cau_hoi_thieu_slot_thi_tra_so_tay_chu_khong_hoi_nguoc(text):
    """Người ta đang hỏi *làm được không*, chưa yêu cầu làm — nên câu trả lời đúng nằm
    ở sổ tay, không phải một câu hỏi ngược về vị trí ghế."""
    d = router.route(text)
    assert d.disposition == "not_control", d
    assert d.reason == "manual_question"


@pytest.mark.parametrize(
    "text",
    ["Bật điều hòa được không?", "Mở cửa sổ bên lái 30% được không?", "Phát nhạc được không?"],
)
def test_cau_hoi_khop_tron_mot_luat_van_ra_offer(text):
    """Đường `offer` **không** được nuốt mất: câu hỏi khớp trọn một luật thì nêu việc sẽ
    làm rồi hỏi lại (ADR-011). Đó là lý do `question_to_control` bằng 0 một cách có cấu
    trúc chứ không phải nhờ tinh chỉnh."""
    d = router.route(text)
    assert d.disposition == "offer", d
    assert d.reason == "question_about_supported_action"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Tắt đèn pha được không?", "headlight_off_not_permitted"),
        ("Đặt điều hòa 50 độ được không?", "temperature_out_of_range"),
    ],
)
def test_cau_hoi_ve_viec_bi_cam_van_duoc_noi_la_bi_cam(text, reason):
    """`denied` giữ nguyên. Hỏi về một thao tác bị cấm mà nhận lại một đoạn sổ tay là
    đánh mất đúng câu trả lời người ta cần — và với đèn pha thì đó là một quy định an
    toàn (ADR-020), không phải một giới hạn kỹ thuật."""
    d = router.route(text)
    assert d.disposition == "denied", d
    assert d.reason == reason

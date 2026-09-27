"""Hai chỗ hổng từ vựng của router, đo được trên `multiturn-v1`. Issue #368.

## Chỗ thứ nhất — `"có"` đứng đầu câu

```
"Mở cốp được không"          ->  offer   ✓
"Có mở được cốp không"       ->  manual_question   ✗   cùng một ý
"Có thể bật điều hòa không"  ->  manual_question   ✗
```

Cả ba là **cùng một câu hỏi**. Hai câu sau đi vào nhánh `is_question` bình thường, nhưng
`_run_matchers` không khớp vì câu mang thêm giàn giáo nghi vấn mà luật điều khiển không
lường: tiền tố `"có"`/`"có thể"`, và `"được"` chen giữa động từ với tân ngữ
(`"mở **được** cốp"`). Hậu tố `"được không"` thì đã dung nạp sẵn — nên vấn đề nằm ở **đầu
câu và giữa câu**, không phải cuối câu.

## Chỗ thứ hai — `"hạ hết"` / `"xuống hết"`

```
"Mở hết kính bên lái"        ->  percent 100   ✓
"Hạ hết kính bên lái"        ->  clarify       ✗
"Hạ kính bên lái xuống hết"  ->  clarify       ✗
```

`_MAXIMUM_PHRASES` có `"mở hết"`, `"hết cỡ"`, `"tối đa"`… nhưng không có hai cách nói này.
Đáng nói vì `"hạ hết xuống"` **chính là mặc định** mà @HVNhan-Relieq chốt cho #339 — nên
xe sẽ đề nghị một việc mà chính nó không hiểu khi tài xế nhắc lại nguyên văn.

## Ca âm tính là phần quan trọng ngang phần dương tính

Bóc `"có"` ra khỏi đầu câu **không được** biến một câu hỏi sổ tay thành lời đề nghị.
`"Có cần bảo dưỡng định kỳ không"` phải vẫn là `manual_question` — và nó không phải ngoại
lệ ta thêm tay: nó vẫn `manual_question` vì `_run_matchers` không khớp nội dung nào, đúng
như trước.
"""

from __future__ import annotations

import pytest

from src.agents.router import DeterministicControlRouter

_ROUTER = DeterministicControlRouter()


def _mo(cau: str) -> str:
    d = _ROUTER.route(cau)
    return f"{d.disposition}/{d.reason}"


def _tools(cau: str) -> list[tuple[str, dict]]:
    d = _ROUTER.route(cau)
    return [(b.tool, b.args) for b in d.candidate_plan.steps] if d.candidate_plan else []


# --- #368a: "có" đứng đầu câu ------------------------------------------------


@pytest.mark.parametrize(
    ("cau", "tool"),
    [
        ("Có mở được cốp không", "set_trunk_state"),
        ("Có thể bật điều hòa không", "set_hvac_power"),
        ("Có thể mở cốp không", "set_trunk_state"),
        ("Bạn bật điều hòa giúp tôi được không", "set_hvac_power"),
    ],
)
def test_co_dau_cau_van_ra_loi_de_nghi(cau: str, tool: str):
    """Cùng ý với dạng đã chạy được, nên phải cùng kết cục."""
    assert _mo(cau) == "offer/question_about_supported_action", cau
    assert [t for t, _ in _tools(cau)] == [tool]


@pytest.mark.parametrize(
    "cau",
    [
        "Mở cốp được không",
        "Bật điều hòa được không",
        "Bật đèn pha được không",
    ],
)
def test_dang_da_chay_duoc_khong_doi(cau: str):
    """Đối chứng: nới từ vựng không được đụng tới dạng vốn đã đúng."""
    assert _mo(cau) == "offer/question_about_supported_action", cau


@pytest.mark.parametrize(
    "cau",
    [
        # Ca âm tính **bắt buộc** của issue: bóc `"có"` không được biến một câu hỏi sổ
        # tay thành lời đề nghị.
        "Có cần bảo dưỡng định kỳ không",
        "Có phải thay lốp không",
        "Có bao nhiêu chế độ lái",
        # Hỏi CÁCH LÀM thì vẫn tra sổ tay — `is_information_question` chạy trước, và
        # trả lời "tôi có thể làm giúp bạn" cho câu "làm thế nào" là trả lời sai câu hỏi.
        "Bật điều hòa thế nào",
        "Làm sao để mở cốp",
    ],
)
def test_cau_hoi_so_tay_van_di_tra_so_tay(cau: str):
    assert _mo(cau) != "offer/question_about_supported_action", cau


def test_khong_bien_menh_lenh_thanh_de_nghi():
    """Câu **mệnh lệnh** vẫn phải chạy thẳng, không được rẽ sang `offer`.

    Nới từ vựng ở nhánh `is_question` không được rò sang đường lệnh: một lệnh biến thành
    lời đề nghị nghĩa là tài xế phải nói thêm một lượt cho mỗi lệnh — đúng thứ cả mảng
    đa lượt đang cố bỏ.
    """
    assert _mo("Mở cốp xe") == "control/deterministic_rule"
    assert _mo("Bật điều hòa") == "control/deterministic_rule"


# --- #368b: "hạ hết" / "xuống hết" -------------------------------------------


@pytest.mark.parametrize(
    "cau",
    [
        "Hạ hết kính bên lái",
        "Hạ kính bên lái xuống hết",
        "Mở hết kính bên lái",
        "Mở kính bên lái hết cỡ",
    ],
)
def test_ha_het_la_mo_toang_percent_100(cau: str):
    """`percent` đo **độ mở**, nên *"hạ hết xuống"* là **100**, không phải 0.

    Viết theo nghĩa đen của chữ *"hạ… xuống"* thì ra `0` — tức **đóng kín** cửa sổ cho một
    tài xế vừa xin thoáng khí. Ở bối cảnh #339 thì đó là lúc xe đang chạy và cửa vừa bị
    chặn, nên nhầm chiều ở đây không phải một lỗi nhỏ.
    """
    assert _tools(cau) == [("set_window_position", {"window": "front_left", "percent": 100})], cau


def test_dong_kinh_van_la_percent_0():
    """Đối chứng chiều ngược lại — thêm `"hạ hết"` không được kéo theo `"đóng"`."""
    assert _tools("Đóng kính bên lái") == [("set_window_position", {"window": "front_left", "percent": 0})]


def test_ha_kinh_khong_kem_muc_do_van_hoi_lai():
    """`"hạ kính"` trần vẫn thiếu `percent`, nên vẫn phải hỏi lại — nới từ vựng chỉ nhận
    thêm cách nói **đã có mức độ**, không đoán mức cho câu không nói."""
    assert _mo("Hạ kính bên lái") == "clarify/missing_window_position"

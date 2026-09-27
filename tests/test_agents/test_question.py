"""Tiếng Việt dùng dạng nghi vấn cho cả câu hỏi lẫn lệnh lịch sự. Tách hai thứ đó
là toàn bộ nội dung của file này."""

import pytest

from src.agents.question import is_negated, is_question
from src.agents.router import normalize_vi


def q(raw: str) -> bool:
    return is_question(raw, normalize_vi(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "Cách khởi tạo lại cửa sổ điện?",
        "Công tắc khóa cửa sổ điện dùng để làm gì?",
        "Chức năng chống kẹp của cửa sổ hoạt động thế nào?",
        "Làm sao mở cửa sổ tự động hoàn toàn?",
        "Đèn chào mừng là gì?",
        "Xe sạc nhanh mất bao lâu?",
        "Trạm sạc gần nhất ở đâu?",
        "Tại sao đèn cảnh báo lại sáng?",
        "Chỉnh nhiệt độ và tốc độ quạt gió thế nào?",
    ],
)
def test_how_what_markers_are_questions(raw):
    assert q(raw) is True


@pytest.mark.parametrize(
    "raw",
    ["Ghế xe có chức năng massage không?", "Xe VF9 có ghế phóng khẩn cấp không?"],
)
def test_co_khong_is_a_question_not_a_negation(raw):
    assert q(raw) is True
    assert is_negated(normalize_vi(raw)) is False


@pytest.mark.parametrize("raw", ["Mở cửa sổ được không?", "Bật điều hòa 22 độ được không?"])
def test_polite_request_form_is_still_a_question(raw):
    """ADR-011: `được không` không còn được coi là lệnh.

    Router sẽ đưa nó sang nhánh `offer` — nêu việc sẽ làm rồi hỏi lại.
    """
    assert q(raw) is True


@pytest.mark.parametrize("raw", ["Mở giúp tôi cửa sổ bên lái", "Phát nhạc nhé"])
def test_imperative_with_politeness_particle_is_not_a_question(raw):
    """Không có dấu hỏi, không có từ để hỏi — vẫn là mệnh lệnh."""
    assert q(raw) is False


@pytest.mark.parametrize("raw", ["Bật điều hòa", "Đặt âm lượng 40", "Mở cửa sổ bên lái 30 phần trăm"])
def test_plain_commands_are_not_questions(raw):
    assert q(raw) is False


def test_bare_question_mark_counts():
    """Không có marker nào nhưng có dấu hỏi vẫn là câu hỏi."""
    assert q("Đèn sương mù?") is True


def test_question_mark_is_read_before_normalisation():
    """normalize_vi xoá dấu câu, nên phải đọc '?' từ bản thô."""
    assert normalize_vi("Đèn sương mù?").endswith("?") is False
    assert q("Đèn sương mù?") is True


@pytest.mark.parametrize(
    "raw",
    ["Không phát nhạc", "Đừng mở cửa sổ bên lái", "Chớ mở cửa", "Tôi không muốn bật điều hòa"],
)
def test_negation_still_detected(raw):
    assert is_negated(normalize_vi(raw)) is True


@pytest.mark.parametrize(
    "raw",
    ["Bật điều hòa", "Ghế xe có chức năng massage không?", "Phát nhạc từ USB được không?"],
)
def test_not_negation(raw):
    assert is_negated(normalize_vi(raw)) is False

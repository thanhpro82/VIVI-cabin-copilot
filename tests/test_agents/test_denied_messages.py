"""Từ chối phải nói vì sao, và nếu có lối ra thì chỉ luôn lối ra.

Đối xứng với `test_clarify_messages.py`: router **đã** làm đúng phần khó — nó từ
chối tường minh thay vì âm thầm ánh xạ `"tắt đèn pha"` thành `auto` (lớp lỗi
KI-001, xem ADR-020). Nhưng lý do chỉ sống trong `RouteDecision`, còn tài xế nghe
"Xin lỗi, tôi không thực hiện được yêu cầu này." — không biết đây là quy định an
toàn cố ý hay hệ thống hỏng, và không biết phải nói gì thay thế. Đây là nửa còn
lại của việc đó.
"""

import pytest

from src.agents.nodes.compose import DENIED_MESSAGES, OUTCOME_MESSAGES, compose_node
from src.agents.router import DeterministicControlRouter

router = DeterministicControlRouter()


async def _speak(text: str) -> str:
    """Đi đúng đường thật: router quyết lý do, compose biến lý do thành lời."""
    decision = router.route(text)
    assert decision.disposition == "denied", f"{decision.disposition}/{decision.reason}"
    out = await compose_node({"outcome": "denied", "route_reason": decision.reason})
    return out["display_text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Tắt đèn pha", "Tắt đèn chiếu gần", "Tắt đèn chiếu xa"])
async def test_headlight_off_explains_why_and_offers_the_way_out(text):
    """Ba cách nói "tắt đèn pha" đều phải dẫn tới cùng một lời giải thích.

    Quan trọng nhất là câu này nêu ĐƯỢC cách đạt đúng ý người dùng (chế độ tự
    động). Không có nó thì tài xế bị kẹt: hệ thống nói không, và không nói gì thêm.
    """
    message = await _speak(text)

    assert message != OUTCOME_MESSAGES["denied"]
    assert "tự động" in message, "phải chỉ ra lối thay thế, không chỉ từ chối"
    assert "an toàn" in message or "ban ngày" in message, "phải nói vì sao bị cấm"


@pytest.mark.asyncio
async def test_headlight_off_stays_denied_not_silently_mapped_to_auto():
    """Chốt chặn hồi quy cho chính quyết định của ADR-020.

    Cách "sửa" sai hiển nhiên nhất cho phàn nàn "không tắt được đèn" là cho router
    ánh xạ ngầm `tắt` -> `auto`. Làm vậy là thực hiện một việc KHÁC việc được yêu
    cầu mà không nói ra. Lời giải thích tử tế hơn không được phép kéo theo chuyện đó.
    """
    decision = router.route("Tắt đèn pha")

    assert decision.disposition == "denied"
    assert decision.reason == "headlight_off_not_permitted"
    assert decision.candidate_plan is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "must_contain"),
    [
        ("Đặt quạt gió mức 7", ("0", "3")),
        ("Bật điều hòa 40 độ", ("16", "30")),
    ],
)
async def test_out_of_range_denials_state_the_valid_range(text, must_contain):
    """Người dùng vừa nói một con số; thứ họ cần biết là số nào thì được."""
    message = await _speak(text)

    for token in must_contain:
        assert token in message


def test_every_denied_reason_the_router_can_emit_is_either_mapped_or_deliberately_generic():
    """Không cho map phình ra bằng key chết.

    Key không khớp lý do nào router phát ra thì không bao giờ hiện, mà vẫn trông
    như đã xử lý — đúng loại rác âm thầm.
    """
    import inspect

    from src.agents import router as router_module

    source = inspect.getsource(router_module)
    emitted = {line.split('"denied", ')[1].split(", ")[1].strip('"') for line in source.splitlines() if 'return "denied", ' in line}

    unknown = set(DENIED_MESSAGES) - emitted
    assert not unknown, f"key không lý do nào phát ra: {sorted(unknown)}"

"""Dẫn xuất `ui.policy` — biên đứng yên/đang chạy và hành vi khi mất trạng thái xe."""

import pytest

from src.services.ui_policy import derive_ui_policy


def _snapshot(speed: float, gear: str) -> dict:
    return {"motion": {"speed_kph": speed, "gear": gear, "ignition": "on"}}


def test_dung_yen_thi_policy_binh_thuong():
    out = derive_ui_policy(_snapshot(0, "P"))

    assert out["active"] is False
    assert out["speed_kph"] == 0
    assert out["ui_policy"]["allow_text_input"] is True
    assert out["ui_policy"]["lock_small_controls"] is False
    assert out["ui_policy"]["allow_detailed_document_browsing"] is True


def test_dang_chay_bat_dung_sau_gia_tri_cua_hop_dong():
    """Sáu giá trị này chốt cứng ở `api_spec.md:582` và phải bằng đúng bản trong
    `technical_spec.md`/`user_experience.md`. Đổi một giá trị là đổi hợp đồng."""
    out = derive_ui_policy(_snapshot(42, "D"))

    assert out["active"] is True
    assert out["speed_kph"] == 42
    assert out["ui_policy"] == {
        "allow_text_input": False,
        "lock_small_controls": True,
        "enlarge_mic_button": True,
        "max_visible_actions": 3,
        "prefer_voice_confirmation": True,
        "allow_detailed_document_browsing": False,
    }


@pytest.mark.parametrize(
    ("speed", "gear", "moving"),
    [
        (0, "P", False),  # đứng yên đúng nghĩa
        (0, "D", True),  # dừng đèn đỏ — vẫn siết, người lái sắp đi tiếp
        (0, "R", True),
        (0, "N", True),
        (0.1, "P", True),  # trôi dốc ở số P
        (1, "D", True),
        (42, "D", True),
    ],
)
def test_bien_dung_yen_dung_chay_theo_ca_toc_do_lan_so(speed, gear, moving):
    """Biên gồm **cả số**, không chỉ tốc độ.

    Đây là phủ định của `is_stationary()` trong `src/agents/policy.py` — cùng một
    định nghĩa với cổng an toàn S2/S3, để hệ thống không có hai khái niệm "đứng yên".
    """
    assert derive_ui_policy(_snapshot(speed, gear))["active"] is moving


def test_khong_doc_duoc_trang_thai_xe_thi_siet_chat_nhat():
    """Fail-closed, cùng kỷ luật với `safety_node`.

    Mở UI đúng lúc không biết xe đang thế nào là kiểu hỏng tệ nhất có thể chọn.
    """
    out = derive_ui_policy(None)

    assert out["active"] is True
    assert out["ui_policy"]["allow_text_input"] is False
    assert out["ui_policy"]["lock_small_controls"] is True
    assert out["ui_policy"]["enlarge_mic_button"] is True


def test_shape_dong_dung_ba_khoa_top_level():
    """`api_spec.md:572`: thừa hoặc thiếu trường đều bị hợp đồng từ chối."""
    for snapshot in (None, _snapshot(0, "P"), _snapshot(42, "D")):
        out = derive_ui_policy(snapshot)
        assert set(out) == {"active", "speed_kph", "ui_policy"}
        assert set(out["ui_policy"]) == {
            "allow_text_input",
            "lock_small_controls",
            "enlarge_mic_button",
            "max_visible_actions",
            "prefer_voice_confirmation",
            "allow_detailed_document_browsing",
        }
        assert 1 <= out["ui_policy"]["max_visible_actions"] <= 3


def test_moi_lan_goi_tra_object_rieng():
    """Payload đi vào ring buffer của `IviEventBus` và nằm đó tới 30 phút.

    Trả về hằng số dùng chung thì một chỗ sửa payload sẽ sửa luôn mọi event đã phát.
    """
    a = derive_ui_policy(_snapshot(0, "P"))
    b = derive_ui_policy(_snapshot(0, "P"))
    a["ui_policy"]["allow_text_input"] = "đã bị sửa"

    assert b["ui_policy"]["allow_text_input"] is True

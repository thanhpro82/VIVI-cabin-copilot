"""Backend phải biết lượt nào do mic TỰ MỞ bắt được. Spec §3.5.

Vì sao tin lời khai của client ở đây, trong khi `mau_slot` (#363) từ chối tin: khác về
**hướng**. Khai `auto` chỉ khiến xe **im hơn**, không bao giờ khiến nó **dễ dãi hơn**.
Client nói dối thì hậu quả là xe im lúc đáng nói — khó chịu, không nguy hiểm. Còn ở #363,
tin lời khai nghĩa là một build cũ có thể xoá mất một cổng an toàn.

Vắng header = `manual`, nên client cũ không đổi hành vi một chút nào.
"""

from __future__ import annotations

import pytest

from src.api.turns import doc_che_do_bat


@pytest.mark.parametrize(
    ("header", "mong"),
    [
        ("auto", True),
        ("AUTO", True),
        (" auto ", True),
        ("manual", False),
        (None, False),
        ("", False),
        ("gi_do_la", False),
    ],
)
def test_doc_che_do_bat(header: str | None, mong: bool):
    assert doc_che_do_bat(header) is mong


def test_gia_tri_la_khong_lam_hong_luot():
    """Header là dữ liệu ngoài. Giá trị lạ phải lui về `manual` chứ không ném lỗi —
    một lượt nói của tài xế không được chết vì một chuỗi header sai chính tả.

    Và lui về `manual` chứ không phải `auto` là **fail về phía nói, không về phía im**:
    một trợ lý câm khó chẩn đoán hơn nhiều một trợ lý nói thừa.
    """
    assert doc_che_do_bat("auto; charset=utf-8") is False

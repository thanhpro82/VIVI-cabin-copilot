"""Chuẩn hoá văn bản tiếng Việt dùng chung cho ingestion, page mapping và eval."""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE = re.compile(r"[﻿​­]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

#: Hư từ tiếng Việt bị loại khi tính độ trùng từ vựng. Giữ lại chúng thì câu hỏi
#: nào cũng trùng cao với văn bản nào.
STOPWORDS: frozenset[str] = frozenset(
    """là gì của có thể nào khi bao nhiêu cách làm sao được không và ở chỗ ra trên
    xe với để cho từ một các những dùng hoạt động thế""".split()
)


def normalize_text(raw: str) -> str:
    """Chuẩn hoá NFC, bỏ ký tự vô hình và gộp khoảng trắng."""
    text = unicodedata.normalize("NFC", raw)
    return " ".join(_INVISIBLE.sub("", text).split())


def fold(raw: str) -> str:
    """Bỏ dấu, hạ chữ thường và bỏ mọi ký tự không phải chữ-số.

    Dùng để so khớp văn bản HTML với văn bản trích từ PDF: hai nguồn xuống dòng
    và đặt dấu câu khác nhau, nhưng chuỗi đã fold thì trùng khớp.
    """
    decomposed = unicodedata.normalize("NFD", raw).casefold()
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(_NON_ALNUM.sub(" ", stripped.replace("đ", "d")).split())


def _tokens(raw: str) -> list[str]:
    """Tách từ **giữ nguyên dấu thanh**.

    `fold` bỏ dấu nên hợp cho so khớp HTML↔PDF, nhưng sai cho so nghĩa: bỏ dấu
    làm "bò", "bỏ", "bó" thành cùng một từ, khiến câu hỏi ngoài phạm vi trùng khớp
    giả với sổ tay.
    """
    return _PUNCT.sub(" ", unicodedata.normalize("NFC", raw).casefold()).split()


def content_words(raw: str) -> set[str]:
    """Tập từ mang nghĩa, đã bỏ hư từ và từ một ký tự."""
    return {token for token in _tokens(raw) if token not in STOPWORDS and len(token) > 1}


def lexical_overlap(query: str, text: str) -> float:
    """Tỷ lệ từ mang nghĩa của câu hỏi xuất hiện trong văn bản."""
    words = content_words(query)
    if not words:
        return 0.0
    return len(words & set(_tokens(text))) / len(words)

"""Mẫu ngữ pháp cứng cho slot đang thiếu — rào chắn của auto-listen. Issue #363.

## Vì sao cần

`ghep_hoi_lai.py` ghi sẵn rủi ro này trong docstring của chính nó, từ trước khi có #363:

> `"hai"` ghép vào ra **control** thật (quạt mức 2, S1, không qua HITL). Router đọc được
> số viết chữ nên không có cách phân biệt ngôn ngữ nào giữa *"hai"* trả lời máy và
> *"hai"* nói với người ngồi cạnh.
>
> Thứ thật sự chặn ca ấy hôm nay: **sau một câu hỏi lại, mic KHÔNG tự mở.**

#363 gỡ đúng cái chặn ấy, nên rủi ro kia không còn ai giữ. Đo lại 29/08, cổng ghép hiện
tại lọt những câu này — và chúng **chạy lệnh thật**:

```
"Tăng quạt gió"  ->  clarify/missing_fan_level
    "hai giờ nhé"            ->  control  set_hvac_fan_level{level: 2}
    "hai người nữa thôi"     ->  control  set_hvac_fan_level{level: 2}
    "mai hai giờ chiều nhé"  ->  control  set_hvac_fan_level{level: 2}

"Bật đèn"        ->  clarify/missing_light_target
    "đèn pha bị hỏng rồi"    ->  control  set_headlight_mode{mode: low_beam}
```

Câu cuối đáng sợ nhất: một lời **than phiền** thành một **lệnh bật đèn**. Không cần
auto-listen mới hỏng — nó đã hỏng sẵn hôm nay với mic bấm tay.

## Luật, một câu

**Mảnh trả lời phải THUẦN là câu trả lời**: mọi từ trong đó phải hoặc là giá trị của
slot đang thiếu, hoặc là từ đệm; và phải có **ít nhất một** từ giá trị.

`"hai giờ nhé"` rụng vì `giờ`. `"hai"` qua. `"mười tám độ"` qua vì `độ` thuộc từ vựng của
slot nhiệt độ. Đó là toàn bộ cơ chế.

## Đây là BỘ LỌC, không phải BỘ PHÂN TÍCH — và điều đó quyết định mọi thứ

Module này **không bao giờ** quyết một giá trị nghĩa là gì. Nó chỉ trả lời *"trong câu này
có gì không phải câu trả lời không"*. Việc biến chữ thành plan vẫn hoàn toàn là của router,
qua `ghep()` rồi route lại.

Hệ quả, và đây là lý do bảng từ vựng dưới đây **không** phải là lỗi "hai bảng song song"
mà `CLAUDE.md` cảnh báo (xem #325): nếu bảng này **hẹp hơn** router thì ta mất *recall* —
tài xế phải bấm mic nói lại. Nếu nó **rộng hơn** router thì câu ấy vẫn phải qua `ghep()` +
`chap_nhan()` như cũ, tức không có lệnh nào sinh thêm. Trôi ở đây suy giảm êm; trôi ở
`TOOL_ARGS` thì lượt chết giữa đường.

Vì thế các con số được **dẫn xuất** từ `router._NUMBER_WORDS` / `_TENS_TOKENS` (nơi duy
nhất biết đọc số tiếng Việt), còn từ vựng của từng slot thì khai ở đây vì router giữ
chúng rải trong luật, không có hằng số nào để nhập.

## Vì sao KHÔNG dùng "confidence"

#363 kiểm và ghi lại: hệ **không có** tín hiệu ấy. `src/services/voice.py` hard-code
`0.0` cho STT (chưa engine nào lộ điểm per-utterance), `contracts.py` để router
`confidence = 1.0` và không chỗ nào gán khác — chỉ có nhị phân khớp/không khớp. Gate bằng
một con số luôn bằng 1.0 là gate bằng không gì cả.

## Vì sao cổng này chạy cả khi mic KHÔNG tự mở

Có thể chỉ siết khi FE báo *"tôi vừa tự mở mic"*. Không làm thế, vì hai lẽ:

1. Đó là để **client tự khai** một cổng an toàn. Một FE cũ, một bản build lỗi, hay một
   client khác là đủ để cổng biến mất trong im lặng.
2. `"đèn pha bị hỏng rồi"` bật đèn là **sai dù mic mở kiểu gì**. Đây là sửa một lỗi đang
   có, không phải rào cho một tính năng sắp có.

## Slot không có mẫu thì KHÔNG mở mic, và cũng KHÔNG bị siết

`CO_MAU` vừa là "chỗ được mở mic ngắn" vừa là "chỗ cổng này có hiệu lực" — một tập, hai
vai, cố ý. Slot nào chưa đo được đường thoại thật thì không mở mic (không có rào thì
không mở cửa) và cũng không siết (không phá thứ mình chưa đo được).
"""

from __future__ import annotations

import re
import unicodedata

from src.agents.router import _NUMBER_WORDS, _TENS_TOKENS

__all__ = ["CO_MAU", "khop_mau"]

#: Từ đệm: có mặt mà không thêm nghĩa. Cùng vai với `voice_intent._TU_DEM`, và cố ý
#: **không** dùng chung: bên kia là từ đệm của một lời đáp có/không, bên này là từ đệm
#: của một mảnh điền slot. Gộp lại thì mỗi lần nới một bên là nới cả bên kia.
_DEM: frozenset[str] = frozenset(
    {
        "à", "ạ", "ấy", "cái", "cứ", "đi", "đó", "được", "khoảng",
        "là", "luôn", "nha", "nhé", "rồi", "thì", "thôi", "ừ", "ừm", "vâng", "vậy",
    }
)

#: Từ chỉ số: chữ số, số viết chữ, và toán tử hàng chục. **Dẫn xuất** từ router — nơi
#: duy nhất trong repo biết đọc `"mười tám"`, `"năm mươi"`. Khai lại ở đây là đúng lỗi
#: mà #325 vừa dọn.
_SO: frozenset[str] = frozenset(_NUMBER_WORDS) | frozenset(_TENS_TOKENS) | {"nửa", "trăm"}

#: Từ vựng **giá trị** của từng lý do `clarify`. Chỉ chép những gì đo được là đường thoại
#: thật (29/08, `develop` @ `88d6d85`) — không đoán thêm cách nói nào.
#:
#: Tập khoá của dict này **là** `CO_MAU`, tức là danh sách trắng của cả hai việc: mở mic
#: ngắn, và siết mảnh trả lời. Thêm một lý do vào đây là hứa cả hai.
_TU_VUNG: dict[str, frozenset[str]] = {
    # "hai" / "2" / "mức 2"
    "missing_fan_level": frozenset({"mức"}),
    # "18 độ" / "mười tám độ"
    "missing_temperature": frozenset({"độ"}),
    # "50" / "50 phần trăm" / "năm mươi"
    "missing_volume": frozenset({"phần", "trăm", "%"}),
    # "bên lái" / "bên phụ" / "sau trái"
    "missing_window_side": frozenset({"bên", "lái", "phụ", "trái", "phải", "sau", "trước"}),
    # "30 phần trăm" / "mở hết" / "một nửa"
    "missing_window_position": frozenset({"phần", "trăm", "%", "mở", "đóng", "hết", "cỡ", "mức", "tối", "đa"}),
    # "đèn pha" / "đèn cốt" / "đèn sương mù"
    "missing_light_target": frozenset({"đèn", "pha", "cốt", "gầm", "sương", "mù", "chiếu", "xa", "gần"}),
    # "bên lái" / "ghế lái"
    "missing_seat_side": frozenset({"bên", "ghế", "lái", "phụ", "trái", "phải", "sau", "trước"}),
    # "mức 3"
    "missing_seat_level": frozenset({"mức"}),
    # "30 độ" / "mức 3"
    "missing_seat_value": frozenset({"độ", "mức"}),
}

#: Lý do `clarify` có mẫu — vừa là chỗ được mở mic ngắn, vừa là chỗ cổng có hiệu lực.
CO_MAU: frozenset[str] = frozenset(_TU_VUNG)


def _tach_tu(text: str) -> list[str]:
    """NFC → thường → bỏ dấu câu → tách từ. `%` giữ lại vì nó là một đơn vị."""
    s = unicodedata.normalize("NFC", text).casefold()
    s = re.sub(r"[^\w\s%]+", " ", s, flags=re.UNICODE)
    return s.split()


def _la_so(tu: str) -> bool:
    return tu.isdigit() or tu in _SO


def khop_mau(ly_do: str, manh: str) -> bool:
    """Mảnh này có **thuần** là câu trả lời cho slot `ly_do` không?

    `False` cho cả ba loại không khớp, và cả ba đều dẫn tới cùng một lối ra NO_EXEC:
    lý do không có mẫu, mảnh rỗng, và mảnh mang thêm nội dung khác.

    Đòi **ít nhất một từ giá trị** chứ không chỉ "mọi từ đều được phép": thiếu vế ấy thì
    `"ừ nhé"` — toàn từ đệm — lọt qua, và ghép một câu không mang giá trị nào vào lệnh là
    đúng thứ `chap_nhan()` đã tồn tại để chặn.
    """
    cho_phep = _TU_VUNG.get(ly_do)
    if cho_phep is None:
        return False
    tu = _tach_tu(manh)
    if not tu:
        return False

    def la_gia_tri(t: str) -> bool:
        return t in cho_phep or _la_so(t)

    return any(la_gia_tri(t) for t in tu) and all(la_gia_tri(t) or t in _DEM for t in tu)

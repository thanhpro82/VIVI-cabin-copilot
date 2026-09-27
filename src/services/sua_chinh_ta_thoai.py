"""Lớp sửa chính tả cho transcript STT — theo **cụm lệnh**, không theo từ đơn.

## Vấn đề

@hason0510 báo 24/08: nói *"Dừng nhạc"*, STT chép ra *"Rừng nhạc"*, lệnh rơi xuống tra
sổ tay. Đo lại 26/08 bằng vòng Piper TTS → Zipformer STT trên 12 câu lệnh ngắn thì lỗi
**tái hiện được** và còn rộng hơn báo cáo:

```
Tạm dừng nhạc  -> 'Sang rừng nhạc'      Tắt điều hòa -> 'Phát điều hòa'
Dừng nhạc      -> 'Thương hàng'         Tắt nhạc     -> 'Các nhà'
Bật nhạc       -> 'Đơn nhạc'            Mở cốp       -> 'Gút'
Chuyển bài     -> 'Truyền bài'          Đóng cốp     -> 'Đắng cuốc'
```

Trước file này không có lớp sửa nào cả: `voice.py` chỉ có `_normalize_output_casing`
(viết hoa chữ cái đầu). Cụm "Vietnamese correction layer" trong CLAUDE.md chỉ là cái đó.

## Vì sao theo CỤM chứ không theo từ

Luật hiển nhiên — "sửa từ nào lệch đúng một ký tự so với một từ trong tập lệnh" — **hỏng
ngay ở ca đầu tiên**: `của` và `cửa` cách nhau đúng 1. Bật luật ấy lên là mọi câu hỏi sổ
tay có chữ `của` biến thành câu nói về cửa xe. Đo được, không phải lo xa:

```
rừng vs dừng: 1    bậc vs bật: 1    của vs cửa: 1   ← ba cái đầu muốn sửa, cái thứ tư thì không
```

Nên luật ở đây đòi **hai** điều kiện cùng lúc trên một cặp từ liền nhau:

1. một trong hai từ khớp **chính xác** một từ neo của cụm (`nhạc`, `cốp`, `đèn`, `bài`…),
2. từ còn lại lệch **đúng một ký tự** so với từ tương ứng trong cụm chuẩn.

`"rừng nhạc"` có neo `nhạc` khớp chính xác và `rừng`→`dừng` lệch 1 → sửa. `"của tôi"`
không có cụm chuẩn nào chứa `tôi` → không đụng tới. `"các nhà"` (từ *"Tắt nhạc"*) có
`nhà` lệch 1 khỏi `nhạc` **và** `các` lệch 3 khỏi `tắt` — không có neo khớp chính xác nên
**không sửa**: bỏ lọt, và bỏ lọt là phía an toàn.

## Phạm vi hẹp là điều kiện an toàn, không phải sự lười

Nhánh sổ tay là mặc định của ADR-011 nên nó nhận phần lớn lưu lượng. Một lớp sửa rộng tay
sẽ bóp méo câu hỏi tra cứu — đổi một lỗi im lặng (lệnh không chạy) lấy một lỗi ồn ào hơn
(trả lời sai câu hỏi).
"""

from __future__ import annotations

import unicodedata

#: Cụm lệnh chuẩn, dạng `(từ_1, từ_2)`. Cả hai từ đều có thể là chỗ bị chép sai, nhưng
#: **không** được sai cùng lúc — xem docstring module.
#:
#: Chỉ những cụm mà router thật sự nhận. Thêm một cụm ở đây mà router không nhận thì lớp
#: này sửa xong lệnh vẫn rơi xuống sổ tay, chỉ khác là giờ có thêm một chỗ để sai.
CUM_LENH: tuple[tuple[str, str], ...] = (
    ("dừng", "nhạc"),
    ("bật", "nhạc"),
    # `("tắt", "nhạc")` cố ý CHƯA có mặt: trên `develop`, `"tắt nhạc"` rơi xuống tra
    # sổ tay vì `_match_music` chỉ nhận `tạm dừng|dừng` cho `pause`. Sửa transcript
    # thành một câu router vẫn không hiểu là thêm một chỗ để sai mà không được gì.
    # PR #315 thêm `tắt` vào nhánh pause — khi nó merge thì thêm cụm này, và
    # `test_moi_cum_trong_bang_deu_la_lenh_router_nhan` sẽ tự bảo vệ điều đó.
    ("phát", "nhạc"),
    ("mở", "nhạc"),
    ("chuyển", "bài"),
    ("mở", "cốp"),
    ("đóng", "cốp"),
    ("bật", "đèn"),
    ("tắt", "đèn"),
    ("mở", "cửa"),
    ("đóng", "cửa"),
    ("bật", "điều"),
    ("tắt", "điều"),
    ("tăng", "âm"),
    ("giảm", "âm"),
    ("mở", "kính"),
    ("đóng", "kính"),
)


def _khoang_cach(a: str, b: str) -> int:
    """Levenshtein trên ký tự đã chuẩn hoá NFC. Dùng cho **một** âm tiết."""
    truoc = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        hien = [i]
        for j, cb in enumerate(b, start=1):
            hien.append(min(truoc[j - 1] + (ca != cb), hien[j - 1] + 1, truoc[j] + 1))
        truoc = hien
    return truoc[-1]


def _thuong(tu: str) -> str:
    return unicodedata.normalize("NFC", tu).casefold()


def sua_theo_cum(text: str) -> str:
    """Sửa transcript theo bảng cụm lệnh. Trả lại nguyên văn nếu không sửa gì.

    Giữ nguyên chữ hoa của từ đầu câu: `voice._normalize_output_casing` đã viết hoa nó
    và câu trả về từ đây đi thẳng vào `transcript.final` mà tài xế nhìn thấy.
    """
    tu = text.split()
    if len(tu) < 2:
        return text
    da_sua = False
    for i in range(len(tu) - 1):
        trai, phai = _thuong(tu[i]), _thuong(tu[i + 1])
        for chuan_trai, chuan_phai in CUM_LENH:
            trai_khop = trai == chuan_trai
            phai_khop = phai == chuan_phai
            if trai_khop and phai_khop:
                break  # đã đúng, không đụng
            if phai_khop and _khoang_cach(trai, chuan_trai) == 1:
                tu[i] = _giu_hoa(tu[i], chuan_trai)
                da_sua = True
                break
            if trai_khop and _khoang_cach(phai, chuan_phai) == 1:
                tu[i + 1] = _giu_hoa(tu[i + 1], chuan_phai)
                da_sua = True
                break
    return " ".join(tu) if da_sua else text


def _giu_hoa(goc: str, thay: str) -> str:
    """Từ gốc viết hoa chữ đầu thì từ thay cũng vậy."""
    return thay.capitalize() if goc[:1].isupper() else thay

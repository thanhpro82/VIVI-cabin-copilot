"""Bảng áp suất lốp nguội VF9, curate tay, có provenance về sổ tay gốc (issue #124).

## Vì sao bảng curate chứ không parse

Sổ tay VF9 trang 2 cho **bốn giá trị khác nhau** cho cùng câu hỏi "áp suất lốp bao
nhiêu", theo `trim` (ECO/PLUS) × loại pin (SDI/CATL), chưa kể lốp dự phòng. Không biết
cấu hình xe thì không có một con số đúng để nói — nói bừa một cột đúng là lớp lỗi
ADR-015 đo được **4/40 câu gây hiểu lầm**.

Bảng trong sổ tay không đều: hàng "Phía Sau" chỉ có 2 ô trong khi "Phía trước" có 3
(lốp dự phòng không có bánh sau), và mỗi ô gộp cả kPa lẫn PSI lẫn tên pin trong một
chuỗi. Parse ở **runtime** sẽ giòn và hỏng im lặng — hỏng im lặng ở đây nghĩa là tài
xế bơm sai. Nên số nằm trong JSON cạnh file này, người đọc và chép.

## Cái giá của chép tay, và thứ trả cho nó

Chép tay thì sai được. Đổi lại có hai lớp khoá, cố ý tách ra vì chúng chạy ở hai nơi:

1. `tests/test_safety/test_ap_suat_lop.py` — **chạy trên CI**. Bắt mọi hàng phải nhất
   quán với chính chuỗi nguyên văn của nó, đủ 8 tổ hợp, không trùng, PSI khớp kPa.
   Bắt được ca "sửa `kpa` mà quên sửa `nguyen_van`".
2. `tests/test_rag_integration/test_ap_suat_lop_provenance.py` — **không chạy trên
   CI** (`slow`), vì `data/` bị gitignore toàn bộ: corpus sổ tay không được phân phối
   lại nên chunk store không có trên runner. Nó đọc chunk thật, dựng lại cấu trúc ô
   của bảng nguồn rồi so khớp hai chiều. Đây mới là lớp bắt được "ingest sổ tay bản
   mới mà số đổi" hoặc "chép nhầm ô".

Lớp 2 phải dựng lại **cấu trúc ô**, không được chỉ kiểm tra chuỗi có nằm trong text
hay không: `"260 KPA,38 PSI, (SDI)"` xuất hiện ở **hai** ô khác nhau (PLUS/trước và
ECO/sau), nên phép kiểm substring không phân biệt nổi chép đúng số vào sai ô — mà đó
đúng là lỗi nguy hiểm nhất ở đây.

## Fail-closed thuộc về người gọi

Module này **không** có giá trị mặc định và không đoán. Nó đòi đủ `trim` + `battery`.
Chưa biết cấu hình xe thì người gọi (#123) phải quay về câu chỉ nguồn, chứ không được
chọn một cột — mặc định sai còn tệ hơn không trả lời, vì tài xế không có cách nào biết
mình vừa nghe cột nào.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

Trim = Literal["eco", "plus"]
Battery = Literal["sdi", "catl"]
Axle = Literal["front", "rear"]

_DUONG_DAN = Path(__file__).with_suffix(".json")

#: Đặt JSON cạnh module chứ không dưới `data/`: `.gitignore` có dòng `data/` **không**
#: neo đầu, nên nó khớp mọi thư mục tên `data` ở mọi độ sâu — một bảng an toàn nằm ở
#: `src/safety/data/` sẽ không bao giờ được commit, và không ai nhận ra cho tới lúc CI
#: đỏ trên máy khác.
_TO_HOP = tuple((t, b, a) for t in ("eco", "plus") for b in ("sdi", "catl") for a in ("front", "rear"))


@dataclass(frozen=True)
class ApSuat:
    """Một ô của bảng: giá trị, chuỗi nguyên văn sinh ra nó, và nguồn."""

    kpa: int
    psi: int
    #: Nguyên văn ô trong sổ tay, ví dụ `"240 KPA,35 PSI, (SDI)"`. Giữ lại để câu trả
    #: lời truy ngược được và để test đối chiếu — **không** để đọc thẳng cho tài xế.
    nguyen_van: str
    chunk_id: str
    page: int


@dataclass(frozen=True)
class BangApSuat:
    edition: str
    chunk_id: str
    checksum: str
    page: int
    dieu_kien_do: str
    o: dict[tuple[str, str, str], ApSuat]
    du_phong: ApSuat


@lru_cache(maxsize=1)
def doc_bang() -> BangApSuat:
    """Nạp bảng curate. Thiếu tổ hợp hoặc thừa tổ hợp đều là lỗi nạp, không phải lỗi tra.

    Kiểm đủ/thiếu ngay lúc nạp để một bảng khuyết không đi được tới chỗ tra cứu rồi mới
    nổ giữa một lượt nói của tài xế.
    """
    raw = json.loads(_DUONG_DAN.read_text(encoding="utf-8"))
    nguon = raw["nguon"]
    chunk_id, page = nguon["chunk_id"], int(nguon["page"])

    o: dict[tuple[str, str, str], ApSuat] = {}
    for hang in raw["hang"]:
        khoa = (hang["trim"], hang["battery"], hang["axle"])
        if khoa in o:
            raise ValueError(f"bảng áp suất lốp trùng tổ hợp {khoa}")
        o[khoa] = ApSuat(
            kpa=int(hang["kpa"]),
            psi=int(hang["psi"]),
            nguyen_van=hang["nguyen_van"],
            chunk_id=chunk_id,
            page=page,
        )

    thieu = [k for k in _TO_HOP if k not in o]
    thua = [k for k in o if k not in _TO_HOP]
    if thieu or thua:
        raise ValueError(f"bảng áp suất lốp thiếu {thieu} thừa {thua}")

    dp = raw["du_phong"]
    return BangApSuat(
        edition=nguon["edition"],
        chunk_id=chunk_id,
        checksum=nguon["checksum"],
        page=page,
        dieu_kien_do=raw["dieu_kien_do"],
        o=o,
        du_phong=ApSuat(
            kpa=int(dp["kpa"]), psi=int(dp["psi"]), nguyen_van=dp["nguyen_van"], chunk_id=chunk_id, page=page
        ),
    )


def tra_ap_suat(trim: Trim, battery: Battery, axle: Axle) -> ApSuat:
    """Áp suất lốp nguội cho đúng một ô.

    Cả ba tham số **bắt buộc** và không có mặc định. Đó là chỗ an toàn nằm: hàm này
    không thể trả về "giá trị chung", vì trong sổ tay không có giá trị chung nào cả.
    Giá trị lạ là lỗi lập trình → `ValueError`, không phải `None` — trả `None` sẽ lẫn
    với ca hợp lệ "chưa biết cấu hình", mà ca đó người gọi phải chặn **trước** khi gọi.
    """
    bang = doc_bang()
    khoa = (trim, battery, axle)
    if khoa not in bang.o:
        raise ValueError(f"tổ hợp không hợp lệ {khoa}; hợp lệ: trim=eco|plus battery=sdi|catl axle=front|rear")
    return bang.o[khoa]


def tra_lop_du_phong() -> ApSuat:
    """Lốp dự phòng: **một** giá trị, không phụ thuộc trim/battery và không có bánh sau.

    Tách hàm riêng thay vì thêm `axle="spare"` để chữ ký nói đúng sự thật — ép người
    gọi truyền một `trim` không liên quan là mời họ tin rằng nó có liên quan.
    """
    return doc_bang().du_phong

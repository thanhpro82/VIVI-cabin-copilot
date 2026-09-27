"""Danh mục trang bị tuỳ chọn của VF9, curate tay, có provenance về sổ tay gốc.

## Bài toán

116 trên 482 chunk của sổ tay VF9 chứa một mệnh đề điều kiện trang bị — `"(nếu có)"`,
`"nếu được trang bị"`, `"tuỳ theo thị trường"` — tổng cộng **147 lần nhắc**. Hôm nay
composer trích nguyên văn, nên tài xế nghe lại đúng chữ *"nếu được trang bị"* và phải
tự đoán xem xe mình có hay không. Ở phần lớn ca thì đó chỉ là dài dòng; ở vài ca thì
không:

- *"Kéo cần gạt mở cửa khẩn cấp phía sau"* — xe không có cần gạt ấy, và đây là quy
  trình thoát hiểm khi mất điện.
- *"Lấy lốp dự phòng trong khoang chở hàng phía sau"* — xe dùng bộ bơm hơi, tài xế
  đang đứng bên đường.
- *"Xe có phanh khẩn cấp tự động"* — hứa một lớp bảo vệ không tồn tại.

## Ba loại `(nếu có)`, và chỉ một loại là trường hồ sơ

Đây là kết quả chính của đợt khảo sát, và là thứ ngăn người sau dựng 147 lá cờ:

1. **Trang bị tuỳ chọn** — một thứ rời rạc chủ xe nhìn là biết. Đây là loại duy nhất
   hồ sơ trả lời được, và là nội dung của file JSON cạnh module này.
2. **Dữ liệu có thể vắng lúc chạy** — *"cảnh báo lỗi (nếu có)"*, *"danh sách sẽ hiển
   thị (nếu có)"*. Không cấu hình nào trả lời được; nhét vào hồ sơ là tự lừa.
3. **Điều kiện về thứ khác, không phải về xe** — *"Nếu Ghế trẻ em của bạn được trang
   bị chân phụ"*, *"Nếu khách hàng chọn phương án thuê pin"*.

## Vì sao curate tay chứ không suy ra từ `trim`

Cám dỗ hiển nhiên: `plus` thì có ACC, `eco` thì không, khỏi bắt tài xế khai báo. Sổ
tay VF9 **không nói** bản nào có gì — nó chỉ nói "nếu có". Dựng bảng `trim → trang bị`
là bịa ra một tri thức không có trong nguồn, đúng lớp lỗi mà docstring `is_complete`
của `vehicle_profile` đã cảnh báo: kiến thức về nội dung bảng rò rỉ ra ngoài bảng, rồi
sai âm thầm khi sổ tay bản sau đổi.

## Ba trạng thái, và "chưa biết" là trạng thái bình thường

Không ai khai báo 65 trường. Hồ sơ ba trạng thái — có / không / chưa biết — và **chưa
biết là mặc định**, y hệt `trim`/`battery` của #123. Khai một trường thì chỉ những câu
trả lời phụ thuộc trường ấy đổi. Đây là tính chất khiến một danh mục 65 mục dùng được:
giá trị đến từng trường một, không phải từ việc điền hết.

## `cum_tu` là cụm đứng NGAY TRƯỚC dấu điều kiện

Không phải mọi cách gọi tính năng. `"lốp dự phòng"` xuất hiện ở nhiều chunk **không**
điều kiện (bảng thông số, cảnh báo chung); khớp mù trên toàn văn sẽ gán nhầm. Bộ dò
`nhan_dien()` chỉ nhìn `_CUA_SO` ký tự ngay trước dấu điều kiện, nên nó trả lời đúng
câu hỏi *"mệnh đề điều kiện NÀY nói về trang bị nào"*.

Hệ quả cần biết: `cum_tu` phải **duy nhất trên toàn danh mục**. Hai trang bị cùng nhận
một cụm thì bộ dò không phân biệt nổi, mà im lặng — nên `doc_danh_muc()` coi đó là lỗi
nạp chứ không phải lỗi tra.

## Phủ sóng: 89%, và 100% sẽ là dấu hiệu xấu

Đo 19/08 (`eval/results/trang-bi/`): 131 trên 147 mệnh đề khớp một mục trong danh mục.
Đọc tay 16 mệnh đề còn lại thì **mười lăm** đúng là loại 2 hoặc loại 3 — dữ liệu bản đồ
có thể vắng, cảnh báo lỗi có thể không có, chân phụ của ghế trẻ em. Chỉ một ca là loại
1 bị hụt (*"Nếu xe có thể kéo thêm rơ móoc"*), và nó hụt vì `DAU_DIEU_KIEN` nuốt luôn
chữ `"xe"` nên cửa sổ nhìn lui không còn cụm nào.

Nên đừng tối ưu con số này lên 100%: muốn đạt 100% thì danh mục phải nuốt cả loại 2 và
loại 3, tức phải khẳng định rằng *"cảnh báo lỗi (nếu có)"* là một trang bị tuỳ chọn.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: JSON nằm cạnh module, không dưới `data/`. `.gitignore` có dòng `data/` **không**
#: neo đầu nên nó khớp mọi thư mục tên `data` ở mọi độ sâu — cùng lý do với
#: `ap_suat_lop.json`.
_DUONG_DAN = Path(__file__).with_suffix(".json")

#: Dấu hiệu một mệnh đề điều kiện trang bị. Giữ khớp với `scripts/khao_sat_trang_bi.py`
#: — hai bên lệch nhau thì báo cáo phủ sóng nói về một tập khác với tập chạy thật.
DAU_DIEU_KIEN = re.compile(
    r"nếu được trang bị|\(nếu có\)|nếu có trang bị|tuỳ theo thị trường|tùy theo thị trường"
    r"|tuỳ phiên bản|tùy phiên bản|nếu xe (?:của bạn )?(?:được trang bị|có)",
    re.IGNORECASE,
)

#: Bao nhiêu ký tự trước dấu điều kiện được coi là "cụm mà nó nói về". 90 đủ chứa cụm
#: dài nhất trong danh mục (`"cả màn hình cảm ứng phía trước và phía sau"`, 42 ký tự)
#: cộng phần thừa của câu trước, và đủ ngắn để không vơ sang mệnh đề khác.
_CUA_SO = 90


class DanhMucHongError(ValueError):
    """Danh mục tự mâu thuẫn. Lỗi **nạp**, không phải lỗi tra.

    Ném ngay lúc đọc file để một bảng hỏng không đi được tới giữa một lượt nói của tài
    xế rồi mới nổ — cùng kỷ luật với `ap_suat_lop.doc_bang()`.
    """


@dataclass(frozen=True)
class TrangBi:
    """Một trang bị tuỳ chọn."""

    id: str
    ten: str
    nhom: str
    #: Các trang bị loại trừ nhau với nó. Quan hệ **đối xứng**, và `doc_danh_muc()`
    #: kiểm tính đối xứng: khai một chiều là bảng nói hai điều khác nhau tuỳ hướng đọc.
    loai_tru: tuple[str, ...]
    cum_tu: tuple[str, ...]
    muc: tuple[str, ...]
    vi_sao: str


@dataclass(frozen=True)
class DanhMuc:
    phien_ban_so_tay: str
    theo_id: dict[str, TrangBi]

    def __iter__(self):
        return iter(self.theo_id.values())

    def __len__(self) -> int:
        return len(self.theo_id)


def _chuan(s: str) -> str:
    """Thường hoá + gộp khoảng trắng. **Giữ dấu tiếng Việt.**

    Bỏ dấu ở đây sẽ làm `"đừng"` và `"dùng"` chập lại — cùng cái bẫy mà
    `src/rag/textnorm._tokens` đã ghi. Danh mục này còn nhạy hơn: `"kéo xe"` và
    `"kẹo xe"` chỉ khác nhau ở dấu.
    """
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", s or "")).strip().lower()


@lru_cache(maxsize=1)
def doc_danh_muc() -> DanhMuc:
    """Nạp danh mục và kiểm tính nhất quán. Bảng tự mâu thuẫn là `DanhMucHongError`."""
    raw = json.loads(_DUONG_DAN.read_text(encoding="utf-8"))
    theo_id: dict[str, TrangBi] = {}
    chu_cum: dict[str, str] = {}

    for muc in raw["trang_bi"]:
        tb = TrangBi(
            id=muc["id"],
            ten=muc["ten"],
            nhom=muc["nhom"],
            loai_tru=tuple(muc["loai_tru"]),
            cum_tu=tuple(_chuan(c) for c in muc["cum_tu"]),
            muc=tuple(muc["muc"]),
            vi_sao=muc["vi_sao"],
        )
        if tb.id in theo_id:
            raise DanhMucHongError(f"trùng id trang bị: {tb.id!r}")
        if not tb.cum_tu:
            raise DanhMucHongError(f"{tb.id!r} không có cụm từ nào — bộ dò sẽ không bao giờ thấy nó")
        for cum in tb.cum_tu:
            if cum in chu_cum:
                raise DanhMucHongError(
                    f"cụm {cum!r} thuộc cả {chu_cum[cum]!r} lẫn {tb.id!r}; bộ dò không phân biệt nổi"
                )
            chu_cum[cum] = tb.id
        theo_id[tb.id] = tb

    for tb in theo_id.values():
        for khac in tb.loai_tru:
            if khac not in theo_id:
                raise DanhMucHongError(f"{tb.id!r} loại trừ {khac!r} không có trong danh mục")
            if tb.id not in theo_id[khac].loai_tru:
                raise DanhMucHongError(f"loại trừ một chiều: {tb.id!r} → {khac!r} nhưng không có chiều ngược")

    return DanhMuc(phien_ban_so_tay=raw["phien_ban_so_tay"], theo_id=theo_id)


def tra(ma: str) -> TrangBi | None:
    """Trang bị theo id, hoặc `None` nếu không có trong danh mục."""
    return doc_danh_muc().theo_id.get(ma)


def ma_hop_le() -> frozenset[str]:
    return frozenset(doc_danh_muc().theo_id)


def nhan_dien(doan: str) -> list[str]:
    """Các trang bị mà những mệnh đề điều kiện trong `doan` nói về, theo thứ tự xuất hiện.

    Trả list rỗng khi đoạn không có mệnh đề điều kiện nào, **và cũng khi có mệnh đề
    nhưng không nhận ra nó nói về trang bị nào**. Hai ca ấy cố ý không phân biệt ở đây:
    người gọi chỉ được phép hành động khi biết chắc, và "có điều kiện nhưng không rõ
    của cái gì" không phải là biết chắc. Tỷ lệ ca thứ hai là con số phủ sóng, đo bằng
    `scripts/khao_sat_trang_bi.py`, chứ không giấu trong một giá trị trả về.

    Khớp **cụm dài nhất**: `"đèn sương mù phía sau"` phải thắng `"đèn sương mù phía
    trước"` khi cả hai cùng là hậu tố hợp lệ của cửa sổ nhìn lui.
    """
    dm = doc_danh_muc()
    van = _chuan(doan)
    ra: list[str] = []
    for m in DAU_DIEU_KIEN.finditer(van):
        cua_so = van[max(0, m.start() - _CUA_SO) : m.start()].rstrip(" (*,-–—:")
        trung: tuple[int, str] | None = None
        for tb in dm:
            for cum in tb.cum_tu:
                if cua_so.endswith(cum) and (trung is None or len(cum) > trung[0]):
                    trung = (len(cum), tb.id)
        if trung and trung[1] not in ra:
            ra.append(trung[1])
    return ra

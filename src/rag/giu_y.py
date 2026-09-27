"""Thước **giữ ý** — chấm được cả câu nguyên văn lẫn câu đã rút gọn.

## Vì sao không dùng lại thước cũ

SPIKE-004 tự ghi rằng sai lầm lớn nhất của nó là dùng lại bộ chấm cũ: bộ ấy khớp
**nguyên văn 40 ký tự**, nên một câu đã rút gọn trượt **theo cấu tạo của thước**, bất
kể nội dung đúng hay sai. Thước nào không chấm nổi thứ ta sắp xây thì không dùng để
quyết định có nên xây hay không.

## Hai thứ nó đo, và một thứ nó cố ý không đo

- `dat` — **giữ đủ cụm chốt chưa**. Mất một cụm `dieu_kien` hoặc `phu_dinh` là trượt
  **không thương lượng**: đúng hai lớp lỗi ADR-015 đo được 4/40.
- `diem` — **tỷ lệ lời nói mang thông tin** = tổng độ dài cụm chốt giữ được, chia cho
  độ dài chuỗi nói. Nói thừa thì mẫu số phình ra và điểm tụt.

Chia cho độ dài lời nói là chỗ khác thước cũ nhiều nhất. Thước cũ chỉ hỏi *"có chứa
đáp án không"* nên nó **thưởng cho dài dòng** — đúng thứ đã sinh ra lời phàn nàn ban
đầu. Và đó cũng là điều kiện để hàm này làm **trọng tài** được: trong số các ứng viên
còn đủ chốt, ứng viên ngắn hơn thắng.

Nó **không** đo độ tự nhiên. Một chuỗi giữ đủ chốt vẫn có thể là breadcrumb đọc thành
tiếng. Trục ấy nằm ở `src/rag/tu_nhien.py`, tách hẳn, để điểm tụt còn chẩn đoán được.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.rag.textnorm import _tokens

KHOA_MAC_DINH = Path("eval/datasets/manual/v1/y_phai_giu.jsonl")

#: **Tầng A — mất một cụm là trượt, không bù bằng gì được.**
#:
#: `dieu_kien` = vế "nếu được trang bị", "tuỳ phiên bản". ADR-015 đo 4/40 câu gây hiểu
#: lầm và **toàn bộ** là do rơi mất vế này.
#: `phu_dinh` = "không được dùng". Mất nó thì câu nói ngược hẳn nghĩa gốc.
TUYET_DOI = frozenset({"dieu_kien", "phu_dinh"})

#: **Tầng B — phải giữ được ÍT NHẤT MỘT cụm.**
#:
#: Tầng này tồn tại vì bản đầu của hàm chấm đòi giữ **đủ mọi** cụm, và như thế thì một
#: quy trình sáu bước không bao giờ đạt được: ta chỉ nói hai câu. Đòi hỏi bất khả thi
#: không phải thước chặt, nó là thước hỏng — nó cho mọi cấu hình cùng điểm 0 và không
#: phân biệt được gì.
#:
#: Đúng cái ta muốn hỏi ở tầng này là: *câu nói ra có mang được thứ gì cốt lõi không*,
#: chứ không phải *có mang được tất cả không*.
COT_LOI = "cot_loi"


@dataclass(frozen=True)
class KetQuaGiuY:
    dat: bool
    diem: float
    thieu: list[str]


#: Vế điều kiện **tự viết** của `speech_policy._VE_TUY_TRANG_BI`.
#:
#: Thước hỏi *"điều kiện có được truyền đạt tới tài xế không"*, không hỏi *"đúng chuỗi
#: ấy có được nhắc lại không"*. Hệ thống có quyền nói điều kiện bằng chữ của nó — và
#: chữ ấy được phép vì nó không mang dữ kiện nào, chỉ thu hẹp phạm vi. Bắt thước đòi
#: nguyên văn nguồn là bắt nó chấm trượt một hành vi đúng.
CAU_DIEU_KIEN_TU_VIET = "không có tính năng này"


def _co_mat(noi: str, cum: str) -> bool:
    """Cụm có xuất hiện trong `noi` không, so theo **dãy token liên tiếp**.

    Không dùng `in` trên chuỗi: `"lốp xe"` nằm trong `"lốp xe đạp"` nhưng đó là token
    khác, và một phép kiểm nhận nhầm thì vô dụng.

    `textnorm._tokens` **giữ nguyên dấu thanh** — bắt buộc ở đây. Nếu đổi sang
    `textnorm.fold` thì "bò", "bỏ", "bó" thành một, và tệ hơn: "đừng" với "dùng" thành
    một, khiến mọi câu chứa "sử dụng" trông như có phủ định.
    """
    a, b = _tokens(noi), _tokens(cum)
    if not b:
        return True
    return any(a[i : i + len(b)] == b for i in range(len(a) - len(b) + 1))


def cham_giu_y(noi: str, chot: list[dict]) -> KetQuaGiuY:
    """Chuỗi `noi` có giữ đủ các cụm chốt không, và bao nhiêu phần lời nói là thông tin."""
    can: list[tuple[str, str]] = [(m["loai"], c) for m in chot for c in m["cum"]]
    if not can:
        # Không có chốt nào thì không có gì để mất. `diem` vẫn phạt độ dài để trọng tài
        # còn phân biệt được hai ứng viên cùng "đạt".
        return KetQuaGiuY(dat=True, diem=(1.0 / len(noi)) if noi else 0.0, thieu=[])

    # `dieu_kien` chấp nhận cả vế tự viết: xem `CAU_DIEU_KIEN_TU_VIET`.
    tuong_duong = _co_mat(noi, CAU_DIEU_KIEN_TU_VIET)
    co = {c: (_co_mat(noi, c) or (loai == "dieu_kien" and tuong_duong)) for loai, c in can}
    thieu = [c for c in co if not co[c]]

    mat_tuyet_doi = any(loai in TUYET_DOI and not co[c] for loai, c in can)
    cot_loi = [c for loai, c in can if loai == COT_LOI]
    du_cot_loi = (not cot_loi) or any(co[c] for c in cot_loi)

    dat = not mat_tuyet_doi and du_cot_loi
    giu = sum(len(c) for c in co if co[c])
    return KetQuaGiuY(dat=dat, diem=(giu / len(noi)) if (noi and dat) else 0.0, thieu=thieu)


def doc_khoa(path: Path = KHOA_MAC_DINH) -> dict[str, list[dict]]:
    """`case_id` → danh sách cụm chốt."""
    khoa: dict[str, list[dict]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            khoa[r["case_id"]] = r.get("chot", [])
    return khoa

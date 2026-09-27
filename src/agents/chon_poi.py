"""Chọn một địa điểm trong danh sách xe **vừa đọc ra** (#355 mục 2b).

Phần **thuần** của cơ chế; phần đọc/ghi state nằm ở `nodes/route.py`, cùng chỗ đứng và
cùng lập luận với `ghep_hoi_lai.py` và `loi_de_nghi.py` (ADR-006/ADR-010: router không
đọc state).

## Vấn đề nó giải

Sau #371, lượt tìm POI số nhiều chạy thật và xe đọc ra một danh sách rồi **tự đặt một câu
hỏi**:

    lượt 1  "Quanh đây có mấy quán cà phê"
            VIVI: "Tôi tìm được 2 chỗ: Cà phê Bình Minh cách 3,65 km,
                   Highlands Coffee Nguyễn Trãi cách 5,6 km. Bạn muốn đi chỗ nào?"
    lượt 2  "Cái đầu tiên" / "Highlands" / "Chỗ gần nhất"
            -> not_control/default_to_manual, 0 lệnh

Đo trên `develop` 28/08: cả bốn cách trả lời tự nhiên đều rơi xuống tra sổ tay; chỉ câu
có động từ (`"đi Highlands"`) mới chạy. Xe đặt câu hỏi rồi không nghe được câu trả lời
của chính nó — cùng một lỗ với #339 và #355 mục 1, khác ở chỗ ngữ cảnh cần nhớ là một
**danh sách có thứ tự**, không phải một chuỗi hay một plan dựng sẵn.

## Vì sao thứ tự thắng alias, luôn luôn

`"thứ hai"` là **alias thật** của `poi-cafe-02` trong `src/fixtures/poi.json` (Cà phê
Bình Minh). Nếu khớp alias trước, câu *"chỗ thứ hai"* trong một danh sách mà Bình Minh
đứng **đầu** sẽ dẫn tới… Bình Minh — đúng chỗ tài xế vừa không chọn. Người nói "thứ hai"
đang đếm những cái tên họ vừa nghe, không gọi tên quán.

Nên `chon()` đọc số thứ tự trước, và chỉ khi không có tín hiệu thứ tự nào mới xét tên.

## Vì sao không có "cái kia", "chỗ nữa"

Chúng không xác định trong một danh sách ba mục, và đoán ở đây là chở tài xế tới chỗ họ
không bảo qua một tool S1 không ai duyệt. Không khớp thì trả `None` và lượt đi đường
thường — fail hướng bỏ sót, không nhận bừa.
"""

from __future__ import annotations

import re
from typing import Any

from src.agents.ghep_hoi_lai import TTL_GIAY
from src.rag.textnorm import fold

__all__ = ["TTL_GIAY", "chon", "con_han"]

#: Số đếm → chỉ số 0-based. Chỉ tới ba vì `POI_TRAN_DOC` cắt danh sách ở ba: nhận
#: `"thứ tư"` cho một danh sách ba mục là hứa một thứ không có.
_THU_TU: dict[str, int] = {
    "dau tien": 0,
    "dau": 0,
    "thu nhat": 0,
    "mot": 0,
    "1": 0,
    "thu hai": 1,
    "thu 2": 1,
    "hai": 1,
    "2": 1,
    "thu ba": 2,
    "thu 3": 2,
    "ba": 2,
    "3": 2,
}

#: Cụm chỉ mục **cuối** danh sách. Tách khỏi `_THU_TU` vì chỉ số phụ thuộc độ dài.
_CUOI: tuple[str, ...] = ("cuoi cung", "cuoi")

#: Cụm so sánh → chỉ số. Danh sách đã sắp theo khoảng cách tăng dần
#: (`fixtures.tim_poi_theo_loai`), nên "gần nhất" là mục đầu và "xa nhất" là mục cuối.
#: Đọc từ **thứ tự đã sắp** chứ không so lại `distance_km`: thứ tài xế vừa nghe là danh
#: sách ấy, và một phép so lại có thể cho kết quả khác nếu ai đó đổi cách sắp.
_SO_SANH_DAU: tuple[str, ...] = ("gan nhat", "gan day nhat", "gan nhat day")
_SO_SANH_CUOI: tuple[str, ...] = ("xa nhat",)

#: Ranh giới từ: `"hai"` phải là một từ, không phải khúc trong `"hai bên"` hay `"ngoài"`.
_TU = re.compile(r"[a-z0-9]+")


def con_han(luc_doc_danh_sach: float, bay_gio: float) -> bool:
    """Danh sách đọc lúc `luc_doc_danh_sach` còn chọn được tại `bay_gio` không?

    `0.0` = không có danh sách nào. Đồng hồ chạy lui trả `False` — cùng lập luận với
    `loi_de_nghi.con_han`: thà bỏ một câu trả lời hợp lệ còn hơn dẫn đường vì một phép
    trừ sai dấu.

    Cùng `TTL_GIAY` với hai cơ chế kia, có chủ ý: ba cửa sổ ngữ cảnh dài ngắn khác nhau
    là thứ không ai giải thích được cho tài xế.
    """
    if luc_doc_danh_sach <= 0.0:
        return False
    return 0 <= bay_gio - luc_doc_danh_sach <= TTL_GIAY


def _tu_trong(text: str) -> list[str]:
    return _TU.findall(fold(text))


def _theo_thu_tu(text: str, so_luong: int) -> int | None:
    """Chỉ số theo **số đếm** hoặc **so sánh**, hoặc `None`.

    Đọc trên chuỗi đã `fold` (bỏ dấu, thường hoá) vì `"thứ hai"`, `"Thứ Hai"` và
    `"thu hai"` là một câu nói; và dùng lại `fold` của tầng RAG thay vì viết bản chuẩn
    hoá thứ hai — hai bản sẽ lệch đúng vào ngày ai đó thêm một ký tự lạ.
    """
    phang = " ".join(_tu_trong(text))
    if not phang:
        return None
    for cum in _SO_SANH_DAU:
        if cum in phang:
            return 0
    for cum in (*_SO_SANH_CUOI, *_CUOI):
        if cum in phang:
            return so_luong - 1
    # Cụm hai chữ trước ("thứ hai") rồi mới tới số trần ("hai"): `"thu hai"` chứa `"hai"`,
    # nên xét ngược lại thì mọi cụm hai chữ đều bị số trần ăn mất và chỉ số vẫn đúng do
    # tình cờ — cho tới ca đầu tiên nó không đúng.
    for cum, chi_so in sorted(_THU_TU.items(), key=lambda item: -len(item[0])):
        if " " in cum:
            if cum in phang:
                return chi_so
        elif cum in _tu_trong(text):
            return chi_so
    return None


def _theo_ten(text: str, items: list[dict[str, Any]]) -> int | None:
    """Chỉ số theo tên hoặc alias của POI. `None` khi không khớp, hoặc khớp **nhiều**.

    Khớp nhiều thì trả `None` chứ không lấy cái đầu: hai địa điểm cùng khớp nghĩa là câu
    nói không phân biệt được chúng, và chọn bừa một cái là đi sai chỗ mà không ai được
    hỏi lại.
    """
    phang = f" {' '.join(_tu_trong(text))} "
    trung: list[int] = []
    for chi_so, item in enumerate(items):
        khoa = [str(item.get("name", "")), *(str(a) for a in item.get("aliases", ()) or ())]
        if any(k.strip() and f" {' '.join(_tu_trong(k))} " in phang for k in khoa):
            trung.append(chi_so)
    return trung[0] if len(trung) == 1 else None


def chon(text: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Câu này chọn mục nào trong danh sách vừa đọc? `None` = không chọn gì.

    **Thứ tự trước, tên sau** — xem docstring module: `"thứ hai"` vừa là số đếm vừa là
    alias của một quán cụ thể, và người nói nó đang đếm chứ không gọi tên.
    """
    if not items:
        return None
    chi_so = _theo_thu_tu(text, len(items))
    if chi_so is None:
        chi_so = _theo_ten(text, items)
    if chi_so is None or not 0 <= chi_so < len(items):
        return None
    return items[chi_so]

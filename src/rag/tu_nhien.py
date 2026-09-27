"""Đo **độ tự nhiên** của chuỗi đưa vào TTS — trục thứ ba, trước nay không đo được.

## Vì sao cần một thước riêng, không gộp vào thước đúng-sai

Cả `giu_y` lẫn `chi_so_cau_tra_loi` đều chỉ hỏi *"có giữ đủ thông tin không"*. Một
chuỗi giữ đủ thông tin vẫn có thể **không nghe được**: breadcrumb của sách giấy đọc
thành tiếng, gạch đầu dòng phát ra thành âm, câu đứt ở dấu phẩy. Đúng ba thứ người
dùng phàn nàn 17–18/08, và không thước nào trong repo bắt được chúng.

## Hai nửa, cố ý tách

**Nửa cơ học** (`dem_khuyet_tat`) đếm những khuyết tật *không cần ai phán xét*: chuỗi
có xuống dòng hay không là sự thật, không phải ý kiến. Nửa này chạy trong CI, tất định,
và là thứ dùng để chặn hồi quy.

**Nửa chủ quan** (hội đồng chấm mù, xem `scripts/ban_do_ba_truc.py`) chấm những thứ
nửa trên không với tới: câu có mạch lạc không, có trả lời đúng thứ được hỏi không.

Gộp hai nửa vào một con số là mất khả năng chẩn đoán: điểm tụt mà không biết vì máy
hay vì người.

## Vì sao từng khuyết tật ở đây có mặt

Mỗi mục dưới đây tương ứng một chuỗi **đã phát ra thật** trên máy dev, không phải một
lỗi tưởng tượng. Đừng thêm mục vào bảng này nếu chưa gặp nó trong một run.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Breadcrumb điều hướng của sách giấy. Đọc thành tiếng thì vô dụng tuyệt đối.
#: Gặp thật 17/08: *"Xem > Vành và bánh xe > Áp suất lốp."*
_BREADCRUMB = re.compile(r"(?:^|\s)(?:[Xx]em\s*>|>\s*\S+\s*>)")

#: Gạch đầu dòng lọt vào kênh nói. Gặp thật 18/08: *"- Đầu tiên, tháo nắp van lốp."*
#: Chỉ bắt gạch **mở đầu một mệnh đề**; dấu gạch nối giữa từ ("bán-tự-động") thì không.
#:
#: `["'”’\s]*` giữa dấu câu và dấu gạch là bắt buộc, không phải phòng xa: chuỗi thật
#: 18/08 là `…như sau:" - Nếu bất kỳ lúc nào…`, tức có một dấu ngoặc đóng của câu dẫn
#: chen vào giữa. Bản đầu thiếu nó và **bỏ lọt đúng ca người dùng vừa báo**.
_GACH_DAU_DONG = re.compile("(?:^|[.!?:][\"'”’\\s]*|\\n)\\s*[-•–—]\\s+")

#: Xuống dòng trong chuỗi nói = bố cục trang giấy rò vào kênh âm thanh.
_XUONG_DONG = re.compile(r"[\r\n]")

#: Chuỗi kết thúc giữa chừng. Piper đọc xong rồi im, nghe như xe bị ngắt lời.
#: Gặp thật 18/08: *"…sau khi sử dụng sản phẩm này, lốp xe bị xẹp,"*
_CUT_CAU = re.compile(r"[,;:–—(\[]\s*$")

#: Cặp ngoặc bao ngoài do SLM sinh. Gặp thật 18/08 ở câu dẫn.
_NGOAC = ('"', "“", "”", "'", "«", "»")

#: Ngoặc bao quanh **riêng câu dẫn**, không bao cả chuỗi:
#: `"Bánh xe bị xịt, sổ tay hướng dẫn như sau:" Không lái xe với lốp...`
#:
#: Bản đầu chỉ kiểm ngoặc ở hai ĐẦU chuỗi, nên nghiệm thu đường thật 18/08 báo 5/5 lượt
#: sạch trong khi cả 5 đều mở đầu bằng một dấu ngoặc thừa. Chỗ mù của bộ dò nguy hiểm
#: hơn khuyết tật nó bỏ sót: nó biến một lỗi thấy được thành một lỗi được chứng nhận.
_NGOAC_CAU_DAN = re.compile(r'^\s*["“‘«][^"”’»]{5,120}["”’»]\s+\S')

#: Chữ thuộc hệ chữ KHÁC (Hán, Kirin, Ả Rập, Hangul, Kana...). Gặp thật ở SPIKE-004
#: RAG-105: model xen nguyên một câu tiếng Trung vào câu trả lời tiếng Việt.
#:
#: Phát hiện theo **tên Unicode của ký tự**, không theo danh sách trắng. Bản đầu dùng
#: danh sách trắng và báo nhầm ngay ca thứ hai: dấu ">" của breadcrumb bị gọi là
#: "ký tự lạ", trong khi nó là dấu câu ASCII. Danh sách trắng luôn thiếu một dấu nào đó.
_HE_CHU_LATIN = ("LATIN", "COMMON", "INHERITED")

#: Đã CÂN NHẮC rồi BỎ: luật phạt viết tắt toàn hoa ("PDC" đọc thành "pê đê xê").
#:
#: Nó báo nhầm ngay ở ca đối chứng sạch — `"…260 kPa, tức 38 PSI"` bị gọi là khuyết
#: tật, trong khi PSI là đơn vị và đọc rời từng chữ mới đúng. Và nó vi phạm chính luật
#: của module này: nó là mục tôi thêm theo suy đoán, chưa từng gặp trong một run nào.
#: Nếu sau này TTS thật sự đọc hỏng một viết tắt, hãy thêm lại kèm run id chứng minh.

#: Trần nói. Vượt trần nghĩa là tầng trên đã hỏng và lưới cuối phải cắt.
TRAN_KY_TU = 240

#: Tên khuyết tật → mô tả ngắn, dùng khi in báo cáo.
TEN_KHUYET_TAT: dict[str, str] = {
    "breadcrumb": "đọc đường dẫn mục lục thành tiếng",
    "gach_dau_dong": "gạch đầu dòng lọt vào kênh nói",
    "xuong_dong": "bố cục trang giấy rò vào kênh nói",
    "cut_cau": "chuỗi đứt giữa chừng",
    "ngoac_bao_ngoai": "cặp ngoặc do model sinh",
    "ky_tu_la": "ký tự ngoài bảng Việt",
    "vuot_tran": f"dài quá {TRAN_KY_TU} ký tự",
    "rong": "không nói gì",
}


@dataclass(frozen=True)
class KetQuaTuNhien:
    """`sach` = không khuyết tật nào. `khuyet_tat` giữ nguyên thứ tự phát hiện."""

    sach: bool
    khuyet_tat: list[str]

    @property
    def so_khuyet_tat(self) -> int:
        return len(self.khuyet_tat)


def _co_he_chu_khac(s: str) -> bool:
    """Có ký tự CHỮ thuộc hệ chữ ngoài Latin không.

    Chỉ xét ký tự chữ (`isalpha`): dấu câu, chữ số, ký hiệu đều là COMMON và không
    bao giờ là bằng chứng về ngôn ngữ khác.
    """
    for c in s:
        if not c.isalpha():
            continue
        ten = unicodedata.name(c, "")
        if not any(ten.startswith(h) for h in _HE_CHU_LATIN):
            return True
    return False


def dem_khuyet_tat(noi: str) -> KetQuaTuNhien:
    """Liệt kê khuyết tật cơ học của chuỗi sắp đưa vào TTS.

    Tất định, không model, không ngưỡng tuỳ chỉnh. Đây là nửa dùng để **chặn hồi
    quy**: một thay đổi làm tăng số khuyết tật là một thay đổi làm xấu kênh nói, dù
    điểm đúng-sai có tăng.
    """
    kt: list[str] = []
    if not noi or not noi.strip():
        return KetQuaTuNhien(sach=False, khuyet_tat=["rong"])

    if _BREADCRUMB.search(noi):
        kt.append("breadcrumb")
    if _GACH_DAU_DONG.search(noi):
        kt.append("gach_dau_dong")
    if _XUONG_DONG.search(noi):
        kt.append("xuong_dong")
    if _CUT_CAU.search(noi.rstrip()):
        kt.append("cut_cau")

    s = noi.strip()
    if (len(s) >= 2 and s[0] in _NGOAC and s[-1] in _NGOAC) or _NGOAC_CAU_DAN.match(s):
        kt.append("ngoac_bao_ngoai")
    if _co_he_chu_khac(noi):
        kt.append("ky_tu_la")

    if len(noi) > TRAN_KY_TU:
        kt.append("vuot_tran")

    return KetQuaTuNhien(sach=not kt, khuyet_tat=kt)


def ty_le_sach(cac_chuoi: list[str]) -> float:
    """Tỷ lệ lượt không có khuyết tật cơ học nào. Đây là con số trục-tự-nhiên nửa máy."""
    if not cac_chuoi:
        return 0.0
    return sum(1 for s in cac_chuoi if dem_khuyet_tat(s).sach) / len(cac_chuoi)

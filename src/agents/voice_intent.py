"""Đọc câu trả lời phê duyệt bằng giọng nói (issue #107).

Trước thay đổi này, xe hỏi *"Bạn có đồng ý không?"* rồi trả lời *"Tôi không tìm thấy
thông tin này trong sổ tay xe."* — router đưa `đồng ý`/`xác nhận`/`hủy` xuống
`default_to_manual` hết. Không phải "chưa làm": xe hỏi một câu rồi không hiểu chính câu
trả lời của câu nó vừa hỏi, và phê duyệt vẫn treo.

## Vì sao là module riêng, không nhét vào `router.py`

Issue #107 nêu đúng nguy cơ: *"làm riêng hai lần là hai bộ nhận dạng ý định, và chúng
sẽ lệch nhau"*. Hai người dùng của nó là câu trả lời **phê duyệt** (ở đây) và câu trả
lời **"nghe tiếp không?"** của S3 (PR #108, chưa merge). Đặt ở đây để khi #108 vào,
chuyển `_CONTINUE_READING` sang dùng chung là một thay đổi máy móc, không phải một cuộc
thiết kế lại.

Cũng vì router cố ý **không** đọc trạng thái ngoài (ADR-011). Câu `"đồng ý"` chỉ là câu
trả lời **khi có một phê duyệt đang chờ**; ngoài ngữ cảnh ấy nó là câu nói bình thường.
Ngữ cảnh đó nằm ở tầng gọi, không nằm ở luật.

## Hướng fail: bỏ sót, không nhận bừa

Bỏ sót thì tài xế bấm nút — phiền. Nhận bừa thì một câu bâng quơ thành lời đồng ý cho
lệnh S2, và dù event này chỉ là handoff (`api_spec.md:278` — IVI mới là bên gọi REST),
một IVI tự động gửi tiếp sẽ biến nó thành hành động thật.

Nên: câu dài **không** được coi là câu trả lời, và hai tín hiệu độc lập thì trả `mo_ho`
để lượt hỏng ồn ào thay vì đoán.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

QuyetDinh = Literal["approve", "reject"]

#: Số từ tối đa của một câu **trả lời**. Dài hơn thì nó mang thêm nội dung khác, và
#: `"đồng ý mở cửa sổ bên lái xuống ba mươi phần trăm"` không rõ là duyệt cái đang chờ
#: hay ra lệnh mới. Trả "không nhận" để nó đi đường thường — đường thường vẫn trả lời
#: tử tế, còn `mo_ho` thì làm hỏng lượt.
_TOI_DA_TU = 5

#: Khớp theo **từ**, không theo chuỗi con: `"có"` nằm trong `"cốc"`, `"khoan"` nằm trong
#: `"khoang"`. Khớp chuỗi con thì `"khoang chứa đồ"` thành một lời từ chối.
#:
#: Bảng từ chia **hai bậc**, và ranh giới ấy mang nghĩa chứ không phải để cho gọn:
#:
#: - bậc **rõ ràng** (`đồng ý`, `từ chối`, …) chỉ dùng để duyệt/bác một việc. Nghe thấy
#:   nó mà chẳng có gì đang chờ thì trả lời "không có yêu cầu nào đang chờ" là đúng.
#: - bậc **trần** (`có`, `không`, `vâng`, `thôi`) trả lời **câu hỏi vừa được đặt ra**,
#:   bất kể câu ấy hỏi gì. Nó không tự mang nghĩa phê duyệt.
#:
#: Gộp hai bậc làm một là lỗi bản đầu của #107: cổng phê duyệt chạy trên mọi lượt, nên
#: xe hỏi *"Bạn có muốn nghe tiếp nguyên văn không?"*, tài xế đáp *"Có"*, và nhận lại
#: *"Hiện không có yêu cầu nào đang chờ bạn xác nhận."* Một tiếng "có" trần chỉ là câu
#: trả lời phê duyệt **khi đang có phê duyệt chờ**; ngoài ngữ cảnh ấy nó thuộc về câu
#: hỏi khác, và người gọi mới biết câu hỏi ấy là câu nào.
_DONG_Y_RO = (
    "đồng ý",
    "xác nhận",
    "chấp nhận",
    "duyệt",
)

_CO_TRAN = (
    "đúng rồi",
    "được",
    "vâng",
    "ừ",
    "ok",
    "có",
)

_TU_CHOI_RO = (
    "từ chối",
    "hủy",
    "huỷ",
    "đừng",
    "khoan",
    "dừng",
)

#: Nới bảng này an toàn hơn nới bảng đồng ý, và đó là lý do hai bên không đối xứng: mọi
#: từ ở đây chỉ dẫn tới `reject`/`khong`, tức **không làm gì cả**. Bỏ sót một cách nói từ
#: chối thì tài xế phải nói lại; nhận nhầm thì lượt kết thúc mà không có hậu quả nào.
#: `"khỏi"` và `"không cần"` là hai cách từ chối rất thường gặp, đo được ở
#: `eval/datasets/agent/multiturn-v1` (`MT-TUCHOI-002`).
_KHONG_TRAN = (
    "không cần",
    "thôi",
    "không",
    "khỏi",
)

_DONG_Y = _DONG_Y_RO + _CO_TRAN
_TU_CHOI = _TU_CHOI_RO + _KHONG_TRAN

#: Phủ định đứng **ngay trước** một từ đồng ý thì cả cụm là từ chối, không phải mơ hồ.
#: `"không đồng ý"` chứa cả hai dấu hiệu; đọc theo kiểu "thấy đồng ý là duyệt" sẽ duyệt
#: đúng một lệnh vừa bị từ chối.
_PHU_DINH_TRUOC = ("không", "đừng", "chưa")


@dataclass(frozen=True)
class YDinhPheDuyet:
    """`quyet_dinh is None` nghĩa là **không phải** câu trả lời phê duyệt.

    `mo_ho` phân biệt hai loại "không có quyết định": có tín hiệu nhưng lẫn lộn (phải
    hỏi lại, lượt kết thúc bằng `turn.failed` theo `api_spec.md:644`), so với đơn giản
    là một câu nói khác (đi đường thường).
    """

    quyet_dinh: QuyetDinh | None = None
    mo_ho: bool = False
    #: Tín hiệu có đến từ một từ **chỉ dùng cho phê duyệt** không (`đồng ý`, `từ chối`,
    #: …), hay chỉ từ một tiếng `có`/`không` trần. Người gọi cần biết để xử đúng ca
    #: "chẳng có gì đang chờ": với từ rõ ràng thì nói thẳng là không có gì để duyệt, còn
    #: với tiếng trần thì **im lặng nhường** cho đường thường — nó đang trả lời câu hỏi
    #: khác, không phải nói với cổng phê duyệt.
    ro_rang_ve_phe_duyet: bool = False


def _chuan_hoa(text: str) -> list[str]:
    """NFC → thường → bỏ dấu câu → tách từ."""
    s = unicodedata.normalize("NFC", text).casefold()
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    return s.split()


def _vi_tri_cum(tu: list[str], cum: str) -> list[int]:
    """Chỉ số bắt đầu của mọi lần `cum` xuất hiện, khớp trọn từ."""
    can = cum.split()
    return [i for i in range(len(tu) - len(can) + 1) if tu[i : i + len(can)] == can]


def doc_y_dinh_phe_duyet(text: str) -> YDinhPheDuyet:
    """Câu này có phải là *"đồng ý"* / *"từ chối"* cho một phê duyệt đang chờ không?

    Người gọi phải tự kiểm rằng **có** phê duyệt đang chờ trước khi dùng kết quả — hàm
    này chỉ đọc chữ, không biết ngữ cảnh.
    """
    tu = _chuan_hoa(text)
    if not tu or len(tu) > _TOI_DA_TU:
        return YDinhPheDuyet()

    vi_tri_dong_y = sorted(i for cum in _DONG_Y for i in _vi_tri_cum(tu, cum))
    vi_tri_tu_choi = sorted(i for cum in _TU_CHOI for i in _vi_tri_cum(tu, cum))
    ro = any(_vi_tri_cum(tu, cum) for cum in _DONG_Y_RO + _TU_CHOI_RO)

    if not vi_tri_dong_y and not vi_tri_tu_choi:
        return YDinhPheDuyet()
    if not vi_tri_dong_y:
        return YDinhPheDuyet(quyet_dinh="reject", ro_rang_ve_phe_duyet=ro)
    if not vi_tri_tu_choi:
        return YDinhPheDuyet(quyet_dinh="approve", ro_rang_ve_phe_duyet=ro)

    # Có cả hai. Nếu MỌI dấu hiệu đồng ý đều đứng ngay sau một phủ định thì cả câu là từ
    # chối — `"không đồng ý"`, `"đừng duyệt"`. Còn lại là hai ý độc lập: `"đồng ý nhưng
    # hủy"`. Đoán bừa ở đó là quyết hộ tài xế một việc S2.
    bi_phu_dinh = all(i > 0 and tu[i - 1] in _PHU_DINH_TRUOC for i in vi_tri_dong_y)
    if bi_phu_dinh:
        return YDinhPheDuyet(quyet_dinh="reject", ro_rang_ve_phe_duyet=ro)
    return YDinhPheDuyet(mo_ho=True, ro_rang_ve_phe_duyet=ro)


#: Từ đệm: có mặt trong lời đáp mà không thêm nghĩa. `"có chứ"`, `"ừ đi"`, `"thôi vậy"`.
_TU_DEM = ("rồi", "nhé", "nha", "đi", "ạ", "chứ", "luôn", "thì", "cứ", "vậy", "à", "ừm")


def _chi_gom_tu_tra_loi(tu: list[str]) -> bool:
    """Câu này có **thuần** là một lời đáp không, hay còn mang nội dung khác?"""
    phu: set[int] = set()
    for cum in _DONG_Y + _TU_CHOI + _PHU_DINH_TRUOC:
        for i in _vi_tri_cum(tu, cum):
            phu.update(range(i, i + len(cum.split())))
    return all(i in phu or tu[i] in _TU_DEM for i in range(len(tu)))


def doc_tra_loi_co_khong(text: str) -> Literal["co", "khong"] | None:
    """Câu này có phải lời đáp **có/không** cho câu hỏi vừa đặt ra không?

    Đây là chỗ #107 yêu cầu *"dùng lại cùng bộ nhận dạng"* cho lời mời `"nghe tiếp
    nguyên văn không?"`. Nó gọi thẳng `doc_y_dinh_phe_duyet` chứ không có bảng từ riêng
    — hai bảng từ song song là đúng thứ issue cảnh báo sẽ lệch nhau.

    `None` cho cả hai loại "không đọc được": câu khác hẳn, và câu lẫn lộn. Ở đây gộp
    được vì cả hai đều dẫn tới **cùng một** lối ra — rơi xuống đường thường. Khác với
    phê duyệt, nơi mơ hồ phải làm hỏng lượt: nghe nhầm ở đây chỉ là đọc thừa một đoạn
    sổ tay, còn nghe nhầm ở kia là thực thi một lệnh S2 chưa ai đồng ý.

    ## Chặt hơn nhánh phê duyệt, và vì sao phải thế

    Nhánh phê duyệt cho tới `_TOI_DA_TU` = 5 từ. Ở đây thì **mọi từ** phải là từ trả lời
    hoặc từ đệm. Khác biệt ấy không phải tuỳ hứng — hai nhánh có hàng rào khác nhau:

    - phê duyệt chỉ chạy khi **đang có một phê duyệt chờ**, tức tài xế vừa được hỏi một
      câu có/không cách đó vài giây;
    - nhánh này chạy sau **mọi** câu hỏi sổ tay dài, và đoạn đọc dở sống lâu hơn nhiều.

    Nới bằng số từ ở đây đo được là hỏng: `"Ừ mở kính"`, `"Có mở cốp"`, `"Được bật đèn"`
    đều ba từ, đều có tiếng trần, và đều **không** phải câu trả lời. Router chưa bắt
    được lệnh có tiền tố như vậy (nó trả `default_to_manual`), nên nếu ở đây cũng nhận
    bừa thì tài xế nói "ừ mở kính" và xe đọc sổ tay cho nghe.
    """
    tu = _chuan_hoa(text)
    if not tu or not _chi_gom_tu_tra_loi(tu):
        return None
    y = doc_y_dinh_phe_duyet(text)
    if y.quyet_dinh is None:
        return None
    return "co" if y.quyet_dinh == "approve" else "khong"

"""Đọc ý định Routine từ lời nói, và phân giải tên Routine. Issue #285 (outcome #274).

## Ranh giới

Sở hữu **câu chữ**: nhận ra tài xế đang muốn *chạy* hay *xem trước* một Routine, trả lời
trong lúc preview (đồng ý / từ chối / bỏ một bước), và phân giải cái tên họ nói thành
một Routine cụ thể. Không sở hữu CRUD, không sở hữu UI, không sở hữu safety khi thực thi.

## Vì sao tất định, không hỏi model

Cùng lý do ADR-026 giữ đường tắt luật: tập câu ở đây **đóng và ngắn** — năm ý định, mỗi
cái vài cách nói. Gọi model cho lớp này là trả 0,5–3 s cho một việc regex làm trong 0 ms,
và đổi một hành vi đọc được thành một hành vi phải đo lại mỗi lần đổi prompt.

## `dang_xem_truoc` là tham số, không phải chi tiết cài đặt

*"Đồng ý"* và *"Chạy đi"* là **đồng ý** khi đang có preview treo, và **không phải ý định
Routine** khi không có. Cùng một chuỗi, hai nhãn ngược nhau. Nếu hàm này tự đoán, nó phải
chọn một — và chọn "đồng ý" nghĩa là mỗi lần tài xế nói *"chạy đi"* giữa lúc không có gì
treo, hệ đi tìm một Routine để chạy. Nên ngữ cảnh phải do bên gọi cấp, và bộ đo
`routines-v1` có hẳn một trường cho nó.

## Cái bẫy tên Routine

Ba mẫu mặc định của epic tên là *Đi làm*, *Về nhà*, *Thư giãn* — trùng với những cụm
tiếng Việt cực kỳ thông dụng. `"Về nhà đường nào gần nhất"` và `"Đi làm bằng xe này mất
bao lâu"` là câu hỏi, không phải lệnh chạy Routine. Nên tên **không bao giờ** tự nó kích
hoạt: bắt buộc phải có một động từ chạy/xem đứng trước. Hai ca ấy nằm trong bộ đo
(`RT-NEG007`, `RT-NEG008`) đúng để khoá chuyện này.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from src.agents.ghep_hoi_lai import TTL_GIAY

YDinh = Literal["chay", "xem_truoc", "dong_y", "tu_choi", "bo_buoc", "huy"]

#: Ngữ cảnh preview còn hạn bao lâu. Dùng lại đúng con số của `ghep_hoi_lai`/`loi_de_nghi`/
#: `chon_poi` (30s) có chủ ý — hai cửa sổ ngữ cảnh khác nhau về độ dài là thứ không ai
#: giải thích được cho tài xế (xem `loi_de_nghi.py`).
TTL_XAC_NHAN_GIAY = TTL_GIAY


def con_han_xac_nhan(luc_xem_truoc: float, bay_gio: float) -> bool:
    """Ngữ cảnh "vừa xem trước Routine X, chờ đồng ý/từ chối" còn hạn không.

    `<= 0.0` = không có preview nào đang treo. Đồng hồ chạy lui cũng trả `False` —
    thà bỏ một câu trả lời hợp lệ còn hơn chạy nhầm một Routine vì phép trừ sai dấu.
    """
    if luc_xem_truoc <= 0.0:
        return False
    return 0 <= bay_gio - luc_xem_truoc <= TTL_XAC_NHAN_GIAY

#: Động từ mở đầu một lệnh chạy Routine. `bật` có mặt vì `"bật routine thư giãn lên"`
#: là cách nói thật; nó không đụng luật điều khiển vì còn phải có chữ `routine`/`kịch bản`.
_DONG_TU_CHAY = r"(?:chạy|bắt đầu|thực hiện|bật|khởi động|kích hoạt)"
_DONG_TU_XEM = r"(?:xem trước|xem|kiểm tra|cho tôi xem|cho xem)"

#: Từ chỉ danh mục. **Bắt buộc** cho nhánh `chay`: thiếu nó thì `"chạy nhanh quá đấy"`
#: thành một lệnh chạy Routine tên "nhanh quá đấy".
#: Từ chỉ loại. `chuỗi lệnh` thêm 30/08 vì hai lý do độc lập, và lý do thứ hai mới là
#: lý do bắt buộc:
#:
#: 1. Chính giao diện gọi Routines là **"Chuỗi lệnh riêng"**, nên đó là chữ người dùng
#:    đọc thấy trên màn hình trước khi mở miệng.
#: 2. **`routine` là một từ tiếng Anh và STT của xe là Zipformer tiếng Việt.** Đo 30/08
#:    (Piper tổng hợp → `transcribe_raw`, tức chỉ báo chứ không phải WER giọng người):
#:
#:        "chạy routine thư giãn"     -> "Chạy uy giãn"          ← nuốt luôn chữ kế bên
#:        "bắt đầu routine về nhà"    -> "Bắt đầu hu thin về nhà"
#:        "chạy kịch bản thư giãn"    -> "Chạy kịch bản thư giãn"    ✅
#:        "chạy chuỗi lệnh thư giãn"  -> "Chạy chuỗi lệnh thư giãn"  ✅
#:
#: Chữ `routine` không chỉ sai — nó **phá cả cụm**, nên tên Routine đứng sau cũng mất
#: theo. Giữ nó lại cho đường gõ chữ và cho ai phát âm rõ, nhưng đường nói phải có một
#: từ tiếng Việt, nếu không tính năng này chỉ chạy được bằng bàn phím.
#:
#: KHÔNG nhét biến thể sai của STT (`hu thin`, `uy`) vào đây: đó là việc của lớp sửa
#: chính tả thoại (`sua_chinh_ta_thoai`, đang tắt sau review #317), và một bảng từ méo
#: trong router sẽ nuốt nhầm những câu hoàn toàn khác.
_DANH_MUC = r"(?:routine|rutin|kịch bản|kich ban|chuỗi lệnh|chuoi lenh)"

_CHAY = re.compile(rf"\b{_DONG_TU_CHAY}\b(?:\s+\w+){{0,2}}?\s+{_DANH_MUC}\s+(?P<ten>.+?)\s*$")
_XEM = re.compile(rf"\b{_DONG_TU_XEM}\b(?:\s+\w+){{0,2}}?\s+{_DANH_MUC}\s+(?P<ten>.+?)\s*$")
#: `"Routine về nhà gồm những gì"` — danh mục đứng ĐẦU, câu hỏi ở đuôi.
_XEM_HOI = re.compile(rf"^{_DANH_MUC}\s+(?P<ten>.+?)\s+(?:gồm|có|làm)\s+(?:những\s+)?gì\b")

#: Đuôi lịch sự bám vào tên: `"chạy routine đi làm đi"` → tên là `"đi làm"`, không phải
#: `"đi làm đi"`. Bóc **lặp** từ cuối, nên cụm nhiều từ (`"trước đã"`) tự rụng theo.
#: Danh sách ĐÓNG, và cố ý không có `nhé`/`nha` — chúng đã bị `bo_tieu_tu_cuoi` của
#: `question.py` xử ở tầng trên.
#:
#: Bóc quá tay không nguy hiểm ở đây, và đó là lý do danh sách được phép rộng: một
#: Routine tên *"Về nhà trước"* bị bóc thành `"về nhà"` vẫn khớp lại được ở tầng "tên
#: chứa trọn cụm" của `phan_giai_ten`. Chiều ngược lại — bóc thiếu — thì tên mang theo
#: rác và phân giải trượt, tài xế nhận một câu hỏi lại vô nghĩa.
_DUOI_LICH_SU = (
    "đi",
    "lên",
    "giùm",
    "hộ",
    "giúp",
    "với",
    "cái",
    "luôn",
    "đã",
    "trước",
    "nữa",
    "chút",
    "tí",
)

_DONG_Y = re.compile(r"^(?:ừ|ờ|ok|okê|okay|đồng ý|được|chạy|làm)\b|^(?:ok\s+)?chạy\b|\bđồng ý\b")
_TU_CHOI = re.compile(r"^(?:không|khỏi|thôi|hủy|huỷ|dừng|đừng)\b")
_BO_BUOC = re.compile(r"\b(?:bỏ|bỏ qua|không cần|khỏi)\s+(?:qua\s+)?bước\s+(?P<so>\d+)\b")

#: Câu **hủy** một lần chạy đang sống (#299). Tập đóng, neo đầu câu, và **đòi từ thứ hai**.
#:
#: Chỗ này suýt hỏng, và nó chỉ lộ ra khi đo chứ không khi đọc code (30/08):
#:
#:     doc_tra_loi_co_khong("dừng")     -> "khong"   ← cử chỉ ĐUỔI TRỢ LÝ
#:     doc_tra_loi_co_khong("dừng lại") -> None      ← rơi xuống sổ tay
#:
#: `"dừng"` trơ **đang là** cách tài xế đuổi trợ lý (`_la_cau_giai_tan`), và theo spec
#: §3.3 đó là cách **duy nhất** đóng chủ động một cửa sổ nghe tiếp — không có nó thì chỉ
#: còn im lặng 6 giây, thứ gần như không tới trong xe đang có người nói chuyện. Nên mẫu
#: này không được nuốt `"dừng"`, và cũng không được nuốt `"dừng nhạc"` (một lệnh `control`).
#:
#: `ngừng` thêm 31/08 sau khi đo vòng TTS→STT trên tám cách nói hủy:
#:
#:     "dừng chuỗi lệnh"   -> "Dừng chuỗi lệnh"    ✅ nghe chuẩn
#:     "ngừng kịch bản"    -> "Ngừng kịch bản"     ✅ nghe chuẩn, nhưng router CHƯA nhận
#:     "dừng kịch bản"     -> "Xưng kịch bản"      ❌ `dừng` đầu câu bị méo
#:     "hủy bỏ kịch bản"   -> "Quy bọc kịch bản"   ❌
#:
#: Vẫn **đòi từ chỉ loại đứng sau**, nên `"ngừng"` trơ không kích hoạt gì — cùng lý do
#: `"dừng"` trơ phải để yên cho cử chỉ đuổi trợ lý.
#:
#: `"dừng lại"` đứng riêng, không cần chữ `routine`: khi một Routine đang chạy thì đó là
#: câu tự nhiên nhất, và #299 đòi nó map đúng active run. Rủi ro nuốt nhầm câu xác nhận
#: HITL được chặn ở chỗ khác: cổng phê duyệt chạy tại `turns.py` **trước** graph, nên một
#: tiếng "dừng" khi đang chờ duyệt không bao giờ tới được router.
_HUY = re.compile(
    r"^\s*(?:dừng lại"
    r"|(?:dừng|ngừng|hủy|huỷ)\s+(?:routine|kịch bản|chuỗi lệnh)"
    r")\b"
)



@dataclass(frozen=True)
class YDinhRoutine:
    """Ý định đọc được. `ten_tho` là tên **chưa phân giải** — đúng chữ tài xế nói."""

    loai: YDinh
    ten_tho: str | None = None
    so_buoc: int | None = None


def _bo_duoi_lich_su(ten: str) -> str:
    tokens = ten.split()
    while tokens and tokens[-1] in _DUOI_LICH_SU:
        tokens.pop()
    return " ".join(tokens)


def doc_y_dinh(normalized_text: str, *, dang_xem_truoc: bool = False) -> YDinhRoutine | None:
    """Ý định Routine, hoặc `None` nếu câu này không thuộc lớp Routine.

    `None` là câu trả lời **thường gặp nhất** và phải rẻ: mọi lượt nói với xe đều đi qua
    đây, còn lượt Routine thì hiếm. Trả `None` nghĩa là "để người khác lo", không phải
    "không hiểu".
    """
    text = (normalized_text or "").strip().lower()
    if not text:
        return None

    # Ngữ cảnh preview xét TRƯỚC: trong preview, `"chạy"` là câu trả lời đồng ý, không
    # phải một lệnh chạy Routine mới.
    if dang_xem_truoc:
        bo = _BO_BUOC.search(text)
        if bo:
            return YDinhRoutine("bo_buoc", so_buoc=int(bo.group("so")))
        # Từ chối xét trước đồng ý: `"đừng chạy"` chứa cả `đừng` lẫn `chạy`, và nghĩa
        # thật nằm ở chữ đứng đầu.
        if _TU_CHOI.search(text):
            return YDinhRoutine("tu_choi")
        if _DONG_Y.search(text):
            return YDinhRoutine("dong_y")
        return None

    # Hủy xét NGAY SAU khối preview, và thứ tự ấy mang nghĩa. `_TU_CHOI` ở trên đã bắt
    # `dừng|hủy|thôi` rồi, nhưng chỉ **bên trong** ngữ cảnh preview. Hai nghĩa khác nhau
    # và cả hai đều đúng:
    #
    #   "dừng"     TRONG preview  = "đừng chạy nó"      -> tu_choi, chưa có gì để hủy
    #   "dừng lại" NGOÀI preview  = "hủy cái đang chạy" -> huy
    #
    # Đặt `_HUY` trước khối preview thì tiếng "thôi" sau một preview biến thành lệnh hủy
    # một lần chạy chưa từng tồn tại.
    if (bo := _HUY.search(text)) is not None:
        con = _bo_duoi_lich_su(text[bo.end() :].strip())
        return YDinhRoutine("huy", ten_tho=con or None)

    hoi = _XEM_HOI.search(text)
    if hoi:
        return YDinhRoutine("xem_truoc", ten_tho=_bo_duoi_lich_su(hoi.group("ten")))
    # Xem trước xét TRƯỚC chạy: `"cho tôi xem routine đi làm"` không chứa động từ chạy,
    # nhưng `"kiểm tra routine về nhà trước đã"` thì `_CHAY` cũng không khớp — thứ tự này
    # là để một câu mang cả hai (`"xem rồi chạy routine X"`) rơi về vế an toàn hơn.
    xem = _XEM.search(text)
    if xem:
        return YDinhRoutine("xem_truoc", ten_tho=_bo_duoi_lich_su(xem.group("ten")))
    chay = _CHAY.search(text)
    if chay:
        ten = _bo_duoi_lich_su(chay.group("ten"))
        # Tên rỗng sau khi bóc đuôi (`"chạy routine đi"`) là câu chưa nêu Routine nào.
        return YDinhRoutine("chay", ten_tho=ten) if ten else None
    return None


# --- Phân giải tên ----------------------------------------------------------


@dataclass(frozen=True)
class KetQuaPhanGiai:
    """`trung` = đúng một Routine. `ung_vien` có nhiều mục khi mơ hồ, rỗng khi không thấy."""

    trung: str | None
    ung_vien: tuple[str, ...]

    @property
    def mo_ho(self) -> bool:
        return self.trung is None and len(self.ung_vien) > 1

    @property
    def khong_thay(self) -> bool:
        return self.trung is None and not self.ung_vien


def _chuan(ten: str) -> str:
    """So khớp bỏ qua hoa/thường, dấu câu và khoảng trắng thừa — **giữ dấu tiếng Việt**.

    Bỏ dấu thì `"Đi làm"` và `"Đi lam"` bằng nhau, nghe có vẻ rộng lượng; nhưng nó cũng
    làm `"Thư giãn"` và `"Thu gian"` bằng nhau, mà `"thu gian"` là một cụm khác hẳn. STT
    tiếng Việt trả ra chữ có dấu, nên không có lý do gì phải bỏ.
    """
    ten = unicodedata.normalize("NFC", ten or "").lower()
    ten = re.sub(r"[^\w\s]", " ", ten, flags=re.UNICODE)
    return " ".join(ten.split())


def phan_giai_ten(ten_tho: str, ten_routine: list[str]) -> KetQuaPhanGiai:
    """Tên tài xế nói → đúng một Routine, hoặc một tập ứng viên để hỏi lại.

    Ba tầng, dừng ở tầng đầu tiên cho **đúng một** kết quả:

    1. khớp tuyệt đối sau chuẩn hoá;
    2. một tên chứa trọn cụm được nói (`"đi làm"` khớp `"Đi làm buổi sáng"`);
    3. thua — trả về ứng viên để tầng trên hỏi lại.

    **Không có tầng "gần đúng"** (Levenshtein, tỉ lệ ký tự chung). Một Routine là chuỗi
    hành động lên xe thật; đoán sai ở đây không phải hiểu nhầm một câu hỏi mà là chạy
    nhầm một chuỗi lệnh. Hỏi lại rẻ hơn.
    """
    goc = _chuan(ten_tho)
    if not goc:
        return KetQuaPhanGiai(None, ())
    bang = {ten: _chuan(ten) for ten in ten_routine}

    khop = [ten for ten, chuan in bang.items() if chuan == goc]
    if len(khop) == 1:
        return KetQuaPhanGiai(khop[0], (khop[0],))
    if len(khop) > 1:
        return KetQuaPhanGiai(None, tuple(khop))

    chua = [ten for ten, chuan in bang.items() if goc in chuan]
    if len(chua) == 1:
        return KetQuaPhanGiai(chua[0], (chua[0],))
    return KetQuaPhanGiai(None, tuple(chua))

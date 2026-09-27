"""Quyết định **nói gì** cho một đoạn sổ tay — và từ 21/08, đó cũng là thứ hiển thị.

Module này chọn `speak_text`: một chuỗi ngắn, **luôn là câu có sẵn trong đoạn nguồn**,
chọn bằng luật tất định.

Trước 21/08 `display_text` là một chuỗi khác — nguyên văn cả đoạn, tới 1.200 ký tự —
và không đi qua đây. Nhóm yêu cầu hợp nhất hai kênh vì bản dài quá dài cho việc tài xế
thật sự làm với màn hình: *xem lại phụ đề*. Nên chuỗi module này trả ra giờ là thứ
**duy nhất** ra dây (`assistant_response_payload`), và ADR-015 vẫn được giữ vì nó vẫn
là nguyên văn — chỉ ít câu hơn, không diễn đạt lại.

## Vì sao không tóm tắt

ADR-015 đo trên 40 case `supported`: để SLM viết lại một đoạn thì **4/40** câu gây hiểu
lầm, và tỷ lệ chỉ đi từ 5/40 xuống 4/40 qua *ba* vòng chỉnh cấu hình — tức đó là **sàn
lỗi của cách tiếp cận**, không phải chỗ còn tinh chỉnh được. Lớp lỗi chính: sổ tay xe
đầy điều kiện theo phiên bản ("nếu được trang bị", "bản ECO / bản PLUS", "pin SDI /
CATL"), mà một bản tóm 1–2 câu **về cấu trúc** không chở nổi chúng.

Ca nặng nhất là RAG-130: sổ tay là một *bảng* áp suất lốp; SLM bốc một cột (ECO + SDI)
ra trình bày như giá trị chung. Xe pin CATL bơm theo đó là **thiếu hơi**.

Chọn câu có sẵn thì không có bước diễn đạt lại, nên lớp lỗi đó không dựng lên được.

## Quan sát khoá cả thiết kế

Cùng ADR ghi một chi tiết dễ đọc lướt: ở vòng đo *kém* hơn, SLM trả lời "xem nhãn dán
trên cột trụ" — và đó là câu **an toàn hơn**. *"Cải thiện cấu hình làm câu trả lời cụ
thể hơn, mà cụ thể hơn ở đây nghĩa là nguy hiểm hơn."*

Với đoạn có điều kiện, câu trả lời nói an toàn là một **câu chỉ nguồn**, không phải một
bản tóm tắt. Module này mã hoá điều đó thành luật thay vì trông chờ model tình cờ nói đúng.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

#: Trần ký tự cho câu nói — **chọn bằng số đo, không bằng cảm tính**.
#:
#: 240 ký tự ≈ 11,9 giây theo tốc độ đo thật 20,1 ký tự/giây của giọng `vi_VN-piper`.
#: Con số này là kết quả của Task 5, không phải giả định: bản đầu đặt 400 và bộ đo trên
#: 40 case `supported` cho **p50 16,6 s / p95 19,2 s** — trượt cổng p95 ≤ 12 s. Siết
#: xuống 240 thì **p50 9,4 s / p95 11,9 s**, `grounded_rate` vẫn 100%.
#:
#: Đổi số này là đổi thời lượng tài xế phải nghe. Chạy lại `python -m src.rag.cli eval`
#: và xem hai dòng "noi p50/p95" + "doc so o doan bien the" trước khi đổi.
#:
#: Trần cứng thứ hai nằm ở `ivi_events.MAX_SPEECH_CHARS` (400) — cố ý **lỏng hơn** cái
#: này: nó là lưới cuối, còn đây mới là chỗ quyết định. Lưới phải bắt được lỗi của
#: composer, không phải trùng với composer.
MAX_SPOKEN_CHARS = 240

#: Số **kèm đơn vị**. Số trần ("hàng ghế thứ hai", "8 hướng" đã có đơn vị) không đáng lo
#: bằng đại lượng vật lý mà tài xế sẽ làm theo.
_NUMBER_WITH_UNIT = re.compile(r"\d+\s*(kPa|KPA|psi|PSI|bar|độ|hướng|mm|km/h|V\b|A\b)", re.IGNORECASE)

#: Dấu hiệu đoạn nói về một tính năng **có thể không có trên xe này**.
#:
#: Khác hẳn `has_variant_condition` (14/08 đã tách hai lớp trong `rag/ingest/chunker.py`):
#: ở đó là *cùng một đại lượng, giá trị khác nhau theo bản* — nói ra là sai. Còn đây là
#: *xe bạn có thể không có tính năng này* — nói ra không sai, chỉ **thiếu** nếu rơi mất
#: vế điều kiện.
#:
#: Việc nới cờ biến thể kéo 6 ca thoát khỏi "từ chối đọc", nhưng đổi lại an toàn dựa vào
#: vế điều kiện đi kèm câu nói. S1 thường mang nó theo vì bắt đầu từ câu đầu (tiêu đề),
#: **S2 thì không** — nó chọn câu bất kỳ. 9 chunk trong index thật thuộc diện này
#: (ngưỡng tốc độ AEB, giới hạn 50 km/h của lốp dự phòng) và bộ 40 case không phủ chúng,
#: nên chỗ này phải đóng bằng cấu trúc, không đóng bằng một phép đo yếu.
_TUY_TRANG_BI = re.compile(r"nếu được trang bị|\*\s*N[ếe]u c[óo]", re.IGNORECASE)

#: Câu gắn thêm khi nói một con số lấy từ đoạn tuỳ-trang-bị mà vế điều kiện đã rơi mất.
#:
#: Đây là chữ **tự viết**, không trích sổ tay — cùng loại với `_VARIANT_FALLBACK`, và
#: được phép vì nó không mang dữ kiện nào: nó thu hẹp phạm vi câu trả lời chứ không
#: thêm nội dung. Đặt **trước** con số để tài xế nghe điều kiện rồi mới nghe số.
_VE_TUY_TRANG_BI = "Tuỳ phiên bản, xe bạn có thể không có tính năng này."

#: Dấu hiệu một câu đang **chỉ sang nguồn có thẩm quyền** thay vì tự trả lời.
_POINTER_MARKERS = re.compile(r"nhãn|khung cửa|cột trụ|xem\s*>|tham khảo|hướng dẫn sử dụng", re.IGNORECASE)

#: Bộ tách câu, **nhận biết cả xuống dòng**.
#:
#: Bản trước chỉ tách ở dấu kết câu, nên tiêu đề mục dính liền đoạn mở bài thành một
#: "câu" khổng lồ. Khối ấy vừa dài vừa trùng chủ đề với câu hỏi nên thắng mọi bộ xếp
#: hạng rồi ăn hết ngân sách — đo 18/08, đó là nguyên nhân của 21 trên 39 ca trượt.
#:
#: Đã sửa 17/08 rồi HOÀN NGUYÊN vì "trúng đáp án" tụt 72%→36%. Con số ấy đo bằng thước
#: chỉ hỏi *"có CHỨA đáp án không"*, tức thước thưởng cho nói thừa: khối lớn chứa nhiều
#: chữ hơn nên trúng nhiều hơn. Đo lại bằng bàn cân ba trục — thước phạt được nói thừa,
#: và có thêm trục tự nhiên — thì kết luận đảo chiều:
#:
#: | cấu hình | chính xác | tự nhiên |
#: |---|---|---|
#: | tách cũ | 54% | 97% |
#: | **tách xuống dòng** | **64%** | **100%** |
#:
#: Xem `eval/results/ba-truc/`. Phép sửa này chỉ đúng khi ĐI KÈM hai thứ: loại nhãn mục
#: khỏi ứng viên (`_ung_vien`) và gói ngân sách bằng `continue` thay vì `break`. Thiếu
#: một trong hai thì nó nói mỗi tiêu đề, và tụt xuống 33%.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

#: Dạng câu hỏi **đòi thao tác**, không đòi định nghĩa.
#:
#: Phân biệt này là thứ bộ xếp hạng theo độ liên quan **không thể** làm được: câu mô tả
#: đứng đầu một mục sổ tay bao giờ cũng trùng chủ đề nhiều hơn câu thao tác, nên nó
#: luôn thắng. Đo 21/08 đối chiếu bản trả lời tham chiếu: hỏi *"bật đèn sương mù thế
#: nào"* thì hệ thống nói *đèn sương mù dùng để làm gì*. Bốn ca cùng lớp trong 39 ca.
_HOI_THAO_TAC = re.compile(r"(thế nào|làm sao|bằng cách nào|ra sao|\bcách\b|hướng dẫn)", re.IGNORECASE)

#: Động từ mở đầu một **bước**. Tập đóng, và cố ý chỉ nhận động từ thao tác trên xe —
#: không nhận động từ trần thuật (`là`, `có`, `được`, `giúp`), vì chúng mở đầu câu mô tả.
_DONG_TU_THAO_TAC = re.compile(
    r"^\s*[-–•]?\s*("
    r"chạm|nhấn|bấm|mở|đóng|kéo|đẩy|trượt|xoay|vào|chọn|cuộn|giữ|nhả|lắp|tháo|cắm|"
    r"bật|tắt|khóa|khoá|quan sát|kiểm tra|chuyển|thay|bắt đầu|sử dụng|dùng|gạt|vặn|nối"
    r")\b",
    re.IGNORECASE,
)

#: Dòng `Để <việc>:` — **khung** của danh sách bước, không phải một bước.
#:
#: Bỏ nó khỏi lời nói nhưng **không** để nó cắt chuỗi bước: nó nằm ngay giữa câu mô tả
#: và bước đầu tiên, nên coi nó là ranh giới sẽ làm chuỗi bước không bao giờ dài quá 0.
_TIEU_DE_BUOC = re.compile(r"^\s*để\b.*[:：]\s*$", re.IGNORECASE)

#: Câu **dẫn vào** một danh sách: kết bằng dấu hai chấm. Dấu hiệu định dạng của sổ tay —
#: đúng hoặc sai với mọi đầu vào, không ngưỡng, không đoán.
_DAN_VAO_DANH_SACH = re.compile(r"[:：]\s*$")

#: Câu dẫn hứa một danh sách **không phải quy trình**. Hồi quy RAG-140 (@thanhpro82 chặn
#: PR #230) và ca RAG-112 đều nằm ở đây.
#:
#: Lập luận, không phải danh sách chắp vá: một danh sách là **quy trình** khi câu dẫn hứa
#: *cách làm*. Câu dẫn hứa **điều kiện** hay **hệ quả** thì thứ theo sau là bảng sự kiện —
#: tài xế không "thực hiện" được một hệ quả. Đo được cả hai chiều trên `manual/v1`:
#:
#:     RAG-140  "…khách hàng phải chịu các BIỆN PHÁP sau:"             -> chế tài thu hồi pin
#:     RAG-112  "…TẮT nếu đáp ứng bất kỳ ĐIỀU KIỆN nào sau đây:"       -> điều kiện tắt đèn
#:     RAG-129  "TỔNG QUAN về cài đặt trợ lý giọng nói:"               -> bảng mô tả cài đặt
#:
#:     RAG-126  "…truy cập … bằng bất kỳ CÁCH nào sau đây:"            -> quy trình thật
#:     RAG-127  "…được truy cập bằng bất kỳ PHƯƠNG PHÁP nào sau đây:"  -> quy trình thật
#:     RAG-111  "THỰC HIỆN theo các khuyến nghị sau…:"                 -> quy trình thật
#:
#: Chặn theo **danh từ của câu dẫn**, cố ý KHÔNG chặn theo `nếu`: câu dẫn đúng của RAG-129
#: là `"Nếu có, để truy cập Cài đặt Trợ lý Giọng nói:"` — `nếu có` ở đó là rào "tuỳ trang
#: bị", không phải mệnh đề điều kiện, và chặn nó là mất luôn quy trình thật.
_DAN_KHONG_PHAI_BUOC = re.compile(
    r"\b(điều kiện|biện pháp|trường hợp|hậu quả|vi phạm|tổng quan)\b",
    re.IGNORECASE,
)

#: Dấu gạch đầu dòng — bỏ khi đọc, vì TTS đọc nó thành một quãng ngắt vô nghĩa.
_GACH_DAU_DONG = re.compile(r"^\s*[-–•]\s*")

#: Số câu tối đa trong một lượt nói.
#:
#: Hai là con số đo được **hồi mỗi "câu" còn là một khối tiêu đề dán liền đoạn mở bài**:
#: một câu cho 40,0% trúng, hai câu cho 55,0%, ba trở lên thì tràn trần 240 ký tự.
#:
#: Bộ tách nhận biết xuống dòng làm câu nhỏ đi hẳn, nên trần 2 thành trần chật — phần
#: thân chỉ dùng ~114 trên 193 ký tự ngân sách. Quét lại 18/08: 3 câu cho 64%, và 4/5/6
#: câu **cũng cho đúng 64%** vì trần ký tự mới là thứ chặn thật. Chọn 3 vì nó là số nhỏ
#: nhất đạt trần ấy: mỗi câu thêm là thêm thời gian tài xế phải nghe mà không đổi điểm.
_TOI_DA_CAU = 3

#: Câu khung khi đoạn có biến thể mà không tìm được câu chỉ nguồn nào sạch số.
#:
#: Cố ý **không** bảo "xem màn hình": `ui.policy` tồn tại vì tài xế đang lái thì không
#: nhìn màn hình được. Câu này mời nghe nguyên văn — để tài xế quyết định, chứ không
#: đẩy họ sang một kênh họ không dùng được.
_VARIANT_FALLBACK = "Thông tin này thay đổi theo phiên bản xe nên tôi không tóm tắt được an toàn."


#: Lời mời nghe phần còn lại (S3).
#:
#: Cố ý hỏi **có/không** chứ không im lặng đọc tiếp: đọc 65 giây sổ tay mà tài xế không
#: chọn là đúng thứ cả kế hoạch này sinh ra để bỏ. Và cố ý không nói "xem màn hình" —
#: `ui.policy` tồn tại vì lúc đang lái thì màn hình không phải một kênh dùng được.
_INVITE = "Bạn có muốn nghe tiếp nguyên văn không?"


@dataclass(frozen=True)
class SpeechPlan:
    """Kết quả quyết định: nói gì, còn lại bao nhiêu, và vì lý do nào.

    `reason` không phải để hiển thị — nó để **đo được** ở tầng eval là mỗi câu nói đã
    đi qua nhánh nào, và để test khoá đúng nhánh chứ không chỉ khoá kết quả.
    """

    spoken: str
    remainder_chars: int
    reason: str
    #: Chỉ số các câu (trong `_cau(source)`) đã phát ra ở lượt này.
    #:
    #: Thay cho `next_offset` tính bằng ký tự, vì hai lý do — và lý do thứ hai mới là
    #: lý do thật:
    #:
    #: 1. Xếp hạng theo độ liên quan chọn câu **rời rạc**; một offset một chiều không
    #:    biểu diễn được "đã đọc câu 3 và câu 6".
    #: 2. Offset ký tự đã sinh **hai** lỗi trôi ngầm trong một ngày: nối câu bằng dấu
    #:    cách trong khi nguồn ngăn bằng xuống dòng, và cộng nhầm độ dài lời mời. Cả hai
    #:    không báo lỗi, chỉ làm lát sau cắt vào giữa từ. Chỉ số câu không có lớp lỗi
    #:    đó — không có phép cộng nào để mà lệch.
    chi_so: tuple[int, ...] = ()


def _fields(evidence: Any) -> tuple[str, bool, bool]:
    """Đọc được cả `Evidence` lẫn dict.

    Node RAG là tham số tiêm được (`build_graph(rag=...)`) và test sẵn có truyền dict —
    cùng lý do `_quote_top_evidence` đã phải làm thế. Chỉ đọc thuộc tính thì gặp dict sẽ
    **lặng lẽ** coi như không có nhãn, tức mất đúng lớp bảo vệ này mà không ai thấy.
    """
    if isinstance(evidence, dict):
        return (
            (evidence.get("text") or "").strip(),
            bool(evidence.get("has_variant_condition")),
            bool(evidence.get("is_table")),
        )
    return (
        (getattr(evidence, "text", "") or "").strip(),
        bool(getattr(evidence, "has_variant_condition", False)),
        bool(getattr(evidence, "is_table", False)),
    )


def _cau(text: str) -> list[str]:
    return [c.strip() for c in _SENTENCE_SPLIT.split(text) if c.strip()]


#: Nhãn/tiêu đề: chuỗi ngắn **không kết thúc bằng dấu kết câu**, hoặc kết thúc bằng
#: dấu hai chấm. Sổ tay đầy thứ này vì nó viết để đọc bằng mắt.
_DAU_KET_CAU = re.compile(r"[.!?]['\"”’)]?$")
_DAI_TOI_DA_NHAN = 80


def _la_nhan(cau: str) -> bool:
    """Chuỗi này là **nhãn mục**, không phải một phát biểu.

    Vì sao phải loại: nhãn có **độ trùng chữ với câu hỏi cao nhất trong cả đoạn** —
    tài xế hỏi về đúng cái mục ấy — nên mọi bộ xếp hạng theo độ liên quan đều đẩy nó
    lên số một. Nhưng nhãn không mang thông tin nào.
    Đo 18/08 với bộ tách nhận biết xuống dòng: RAG-101 nói đúng `"Khởi tạo cửa sổ
    điện:"`, RAG-125 nói đúng `"Đèn cảnh báo và chỉ báo"`. Đó là hai lượt hoàn hảo về
    mặt hình thức và vô dụng hoàn toàn về mặt nội dung — tức đúng thứ mà tối ưu một
    trục lẻ sinh ra.

    Ngưỡng 80 ký tự có mặt để một câu ngắn **thiếu dấu chấm cuối** (lỗi OCR sổ tay,
    có thật) không bị loại nhầm: câu như thế thường dài hơn nhãn nhiều.
    """
    c = cau.strip()
    if not c:
        return True
    if len(c) > _DAI_TOI_DA_NHAN:
        return False
    return c.endswith(":") or not _DAU_KET_CAU.search(c)


#: Câu **khung diễn ngôn**: nói về việc sắp nói, hoặc nói rằng chủ đề quan trọng.
#:
#: Chúng lặp lại đúng chữ của câu hỏi nên thắng mọi phép đo trùng chữ, mà không mang
#: dữ kiện nào. Đo 18/08: RAG-109 nói đúng *"Phần sau đây mô tả cách các ghế có thể
#: được điều chỉnh…"*, RAG-111 nói *"Ngồi đúng tư thế là điều rất quan trọng…"*.
_KHUNG_DIEN_NGON = re.compile(
    r"phần (?:sau|dưới) đây|sau đây mô tả|dưới đây mô tả|tổng quan về|giới thiệu về"
    r"|là điều (?:rất )?quan trọng|trong hầu hết các trường hợp|phần này (?:mô tả|trình bày)",
    re.IGNORECASE,
)

#: Dạng câu hỏi → dấu hiệu của câu **thật sự trả lời** nó.
#:
#: Vì sao cần: câu mở bài dùng lại từ khoá chủ đề của câu hỏi, còn câu trả lời thật
#: dùng từ **hành động** hoặc **con số** mà câu hỏi không chứa. Trùng chữ một mình vì
#: thế xếp ngược. Bảng này là cách rẻ nhất để nói cho bộ xếp hạng biết *hình dạng* của
#: câu trả lời đúng, và nó tốn vài chục micro giây.
#:
#: Đã thử thay bảng này bằng cross-encoder đa ngữ: **kém hơn 5 điểm và đắt hơn 980 ms**
#: (`eval/results/ba-truc/`, cấu hình `cross+tach+3c`). Với sổ tay — từ vựng đóng, câu
#: ngắn — dấu hiệu bề mặt là dấu hiệu đúng, còn khái quát hoá ngữ nghĩa lại có hại.
_DANG_HOI: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (
        re.compile(r"bao nhiêu|mấy\b|tối thiểu|tối đa|giới hạn|bao lâu", re.IGNORECASE),
        re.compile(r"\d", re.IGNORECASE),
    ),
    (
        re.compile(r"thế nào|cách |làm sao|ra sao|bằng cách nào|hướng dẫn", re.IGNORECASE),
        re.compile(
            r"^để |chạm vào|nhấn |kéo |vặn |xoay |trượt |bấm |chọn |giữ |nhả |lắp |tháo |mở |bật |tắt ",
            re.IGNORECASE,
        ),
    ),
    (
        re.compile(r"ở đâu|chỗ nào|nằm đâu|vị trí nào", re.IGNORECASE),
        re.compile(r"nằm ở|đặt (?:ở|dưới|trên)|phía (?:trước|sau|dưới|trên)|khu vực|bảng điều khiển", re.IGNORECASE),
    ),
    (
        re.compile(r"khi nào|lúc nào|trường hợp nào", re.IGNORECASE),
        re.compile(r"^khi |^nếu |sau khi|mỗi khi|trong trường hợp|nên .* khi", re.IGNORECASE),
    ),
)

#: Cộng/trừ vào điểm trùng chữ. Trùng chữ nằm trong [0, 1] nên 0,35 đủ để lật thứ hạng
#: giữa hai câu gần nhau mà không đủ để lật giữa hai câu khác hẳn nhau về chủ đề —
#: tức nó chỉnh **thứ tự trong cùng chủ đề**, không đổi chủ đề.
_THUONG_DUNG_DANG = 0.35
_PHAT_KHUNG = 0.35


def _diem_dang(question: str, cau: str) -> float:
    """Điểm cộng cho câu **đúng dạng** với câu hỏi, trừ cho câu khung diễn ngôn."""
    d = 0.0
    for hoi, dap in _DANG_HOI:
        if hoi.search(question) and dap.search(cau):
            d += _THUONG_DUNG_DANG
            break
    if _KHUNG_DIEN_NGON.search(cau):
        d -= _PHAT_KHUNG
    return d


#: Breadcrumb điều hướng của sách giấy: `Xem > Ghế > Điều chỉnh ghế ngồi`.
#:
#: Khác hẳn `_POINTER_MARKERS`: câu chỉ nguồn kiểu *"ghi trên nhãn ở khung cửa"* là câu
#: trả lời **tốt** cho đoạn có biến thể, và đường `pointer` cố ý chọn nó. Còn breadcrumb
#: là đường dẫn mục lục — đọc thành tiếng thì luôn vô dụng, không có ngoại lệ nào.
_BREADCRUMB_CAU = re.compile(r"[Xx]em\s*>|>\s*[^>]{1,40}\s*>")

#: Câu **cảnh báo phải nói kèm** nếu nó đứng ngay trước câu được chọn.
#:
#: Xếp hạng theo độ liên quan không giữ được cảnh báo vì cảnh báo ít trùng chữ với câu
#: hỏi — đo 18/08, cross-encoder xếp câu *"CẢNH BÁO Không sử dụng Bộ bơm hơi… thành bên
#: của lốp"* xuống **hạng 5** cho đúng câu hỏi về lốp xịt.
#:
#: Vế **điều kiện trang bị** cố ý KHÔNG nằm ở đây, dù nó cũng là lớp lỗi ADR-015 đo
#: được 4/40. Đã thử gộp chung, và `test_noi_so_tu_doan_tuy_trang_bi_thi_phai_kem_ve_
#: dieu_kien` bắt ngay: câu nguồn mang điều kiện thường **dài**, kéo nó vào là đẩy chính
#: con số tài xế hỏi ra khỏi ngân sách — đúng chế độ hỏng mà bàn cân thấy ở RAG-109.
#: Điều kiện đã có đường riêng và rẻ hơn: `_gan_ve_dieu_kien` gắn một vế 52 ký tự tự
#: viết. Hai cơ chế vì hai ràng buộc độ dài khác nhau, không phải vì thiếu thống nhất.
_BAT_BUOC_KEM = re.compile(r"^\s*(?:CẢNH BÁO|LƯU Ý|THẬN TRỌNG|NGUY HIỂM)\b", re.IGNORECASE)


#: Cảnh báo/điều kiện chỉ ràng buộc câu nằm trong **cùng khối**, và ta xấp xỉ "cùng
#: khối" bằng khoảng cách hai câu.
#:
#: Không giới hạn khoảng cách thì hỏng ngay, đo 18/08: hỏi *"Cách điều chỉnh ghế ngồi
#: cho người lái?"* và hệ thống kéo về một CẢNH BÁO **về số người ngồi trong xe** nằm
#: tít phía trên, rồi cảnh báo ấy ăn hết ngân sách và đẩy câu trả lời thật ra ngoài.
#: Một cảnh báo không liên quan đặt trước câu trả lời còn tệ hơn không có cảnh báo:
#: nó vừa không bảo vệ được gì, vừa lấy mất chỗ của thứ tài xế đang hỏi.
_KHOANG_BAT_BUOC = 2


def _cau_bat_buoc_truoc(cau_list: list[str], chi_so: int) -> int | None:
    """Câu bắt buộc gần nhất đứng **trước** `chi_so`, trong phạm vi `_KHOANG_BAT_BUOC`."""
    for i in range(chi_so - 1, max(-1, chi_so - 1 - _KHOANG_BAT_BUOC), -1):
        if _BAT_BUOC_KEM.search(cau_list[i]):
            return i
    return None


def _them_cau_bat_buoc(cau_list: list[str], chon: list[int]) -> list[int]:
    """Bổ sung câu bắt buộc nếu phần đã chọn chưa mang nó.

    Trả về **thứ tự sổ tay**: sổ tay viết điều kiện trước rồi mới tới thao tác, và
    `_gop_duoi_tran` gói theo thứ tự danh sách, nên câu bắt buộc vào trước cũng có
    nghĩa là nó được ưu tiên chỗ trong ngân sách. Đó là chủ ý: một cảnh báo đứng một
    mình thì vô hại, còn một bước thao tác đứng một mình thì không.
    """
    if not chon or any(_BAT_BUOC_KEM.search(cau_list[i]) for i in chon):
        return chon
    i = _cau_bat_buoc_truoc(cau_list, min(chon))
    return sorted({*chon, i}) if i is not None else chon


def _ung_vien(cau_list: list[str]) -> list[int]:
    """Chỉ số các câu **được phép nói**. Toàn nhãn thì trả lại tất cả.

    Trả lại tất cả khi không còn gì là có chủ ý: thà đọc một nhãn còn hơn im lặng, và
    một đoạn toàn nhãn thì `remainder_chars` vẫn mời tài xế nghe tiếp nguyên văn.
    """
    ok = [i for i, c in enumerate(cau_list) if not _la_nhan(c) and not _BREADCRUMB_CAU.search(c)]
    return ok or list(range(len(cau_list)))


#: Dấu ngắt mệnh đề ở **cuối** lát cắt, để thay bằng dấu chấm. Gạch ngang nằm trong
#: đây còn ngoặc đóng thì không: gạch ngang treo một mình là rác, ngoặc đóng là nửa
#: còn lại của một cặp.
_KET_MENH_DE = re.compile(r"[,;:–—-]+$")


def _cham_dut(lat: str) -> str:
    """Kết lát cắt bằng dấu chấm. `)` và `—` được giữ rồi mới thêm chấm.

    Bỏ ngoặc đóng đi là làm hỏng cặp ngoặc ngay trong chuỗi trích — người đọc thấy một
    dấu mở không bao giờ đóng, tệ hơn hẳn cái dấu phẩy mà hàm này tồn tại để chữa.
    Gạch ngang thì ngược lại: nó không có nửa kia, nên `"Dừng ở đây —."` chỉ là rác.
    """
    lat = _KET_MENH_DE.sub("", lat).rstrip()
    return f"{lat}." if lat and lat[-1] not in ".!?" else lat


def _gop_duoi_tran(cau_list: list[str], limit: int) -> str:
    """Gộp câu cho tới sát trần; câu đầu đã quá dài thì cắt ở **ranh giới từ**.

    Cắt thẳng theo ký tự sinh ra một âm cụt khi TTS đọc. Gặp thật lúc dựng dữ liệu
    chấm tay (13/08): RAG-101 phát ra *"...chống kẹp), chủ sở hữ Bạn có muốn nghe
    tiếp..."* — cắt giữa chữ "hữu".
    """
    # Câu quá dài thì **bỏ qua rồi đi tiếp**, không dừng hẳn.
    #
    # Bản trước `break`. Đo 18/08: với bộ tách nhận biết xuống dòng, một tiêu đề 20 ký
    # tự đứng trước một câu 200 ký tự làm vòng lặp dừng ngay, và lượt ấy nói đúng mỗi
    # `"Khởi tạo cửa sổ điện:"` — phí 170 trên 193 ký tự ngân sách. Đọc tiêu đề thành
    # tiếng rồi im là ca tệ nhất có thể: vừa vô dụng vừa nghe như xe hỏng.
    #
    # Bỏ qua có làm mất tính liền mạch không? Không mất thêm gì: hàm này vốn đã nhận
    # một danh sách câu **không liền nhau** do tầng chọn trả về.
    spoken = ""
    for cau in cau_list:
        ung_vien = f"{spoken} {cau}".strip()
        if len(ung_vien) > limit:
            continue
        spoken = ung_vien
    if spoken:
        return spoken

    dau = cau_list[0][:limit]
    # Ưu tiên **ranh giới mệnh đề**, rồi mới tới ranh giới từ.
    #
    # Cắt ở ranh giới từ thôi thì vẫn ra "...cầu chì Mô-đun cảm biến chống kẹp), chủ sở
    # Bạn có muốn nghe tiếp không?" — đúng chữ nhưng nghe như xe vấp. Dừng ở dấu phẩy
    # hay ngoặc đóng cho một quãng nghỉ tự nhiên, rồi lời mời tiếp lời.
    menh_de = max(dau.rfind(d) for d in (",", ";", ":", ")", "—"))
    if menh_de >= limit // 2:
        # Đổi dấu ngắt mệnh đề thành dấu chấm trước khi trả về.
        #
        # Không đổi thì lời mời đứng ngay sau dấu phẩy và chuỗi đọc lên thành một câu
        # chạy dài: *"...hỗ trợ người lái xe tiên tiến, Bạn có muốn nghe tiếp nguyên
        # văn không?"* — đo trên backend 19/08. Dấu phẩy hứa còn vế sau, rồi vế sau
        # hoá ra là một câu hỏi của hệ thống.
        #
        # Đây **không** phá hợp đồng trích nguyên văn: chỗ này vốn đã là một lát cắt,
        # và dấu chấm nói đúng điều đang xảy ra — phần đọc dừng ở đây. Lời mời ngay
        # sau mới là thứ nói rằng còn nữa.
        return _cham_dut(dau[: menh_de + 1].rstrip())
    khoang_trang = dau.rfind(" ")
    return (dau[:khoang_trang] if khoang_trang > 0 else dau).rstrip()


class SentenceSelector(Protocol):
    """Chọn câu nào trong `sentences` trả lời `question`, trả về **chỉ số**.

    Kiểu trả về là `list[int]` chứ không phải `str` — và đó là toàn bộ lý do S2 tồn
    tại được sau khi ADR-015 bác phương án cho SLM viết lại đoạn. Model không được
    sinh ký tự nào đi vào tai tài xế, nên không có bước diễn đạt lại để điều kiện
    theo phiên bản rơi ra.
    """

    def select(self, question: str, sentences: list[str]) -> list[int]: ...


def _chon_bang_slm(
    selector: SentenceSelector, question: str, cau_list: list[str], text: str, max_chars: int
) -> SpeechPlan | None:
    """Đường S2. Trả `None` nghĩa là *không có ý kiến* — call site tự đi tiếp đường luật.

    Ba cổng, theo thứ tự chặt dần:

    1. **Gọi được không.** llama-server tắt là trạng thái bình thường
       (`slm_enabled=False` mặc định), không phải sự cố. Một lượt tra sổ tay không
       được chết theo nó.
    2. **Chỉ số có hợp lệ không.** Grammar ép được *kiểu* nhưng không ép được
       *khoảng*: `{"indices":[99]}` vẫn hợp schema. Nên cổng khoảng phải nằm ở đây.
    3. **Chuỗi có nguyên văn không.** Thừa, vì câu lấy theo chỉ số từ chính
       `cau_list`. Giữ vì nó là bất biến của cả thiết kế, và một cài đặt `select`
       khác trong tương lai có thể không còn giữ hộ.
    """
    # Selector chỉ được nhìn thấy ỨNG VIÊN, không nhìn thấy nhãn mục.
    #
    # Lọc ở đây chứ không lọc kết quả trả về: nhãn có độ trùng chữ với câu hỏi cao nhất
    # đoạn, nên đưa nó vào là ép mọi bộ xếp hạng chọn nó rồi ta lại vứt đi — tức lãng
    # phí đúng một suất trong `top` mà cross-encoder được phép chọn.
    ung = _ung_vien(cau_list)
    phu = [cau_list[i] for i in ung]

    try:
        idx = selector.select(question, phu)
    except Exception:
        return SpeechPlan(spoken="", remainder_chars=0, reason="slm_error")

    if not isinstance(idx, list) or not idx:
        return SpeechPlan(spoken="", remainder_chars=0, reason="slm_output_rejected")
    # `bool` là `int` trong Python: `[True]` sẽ lọt nếu chỉ kiểm `isinstance(i, int)`.
    if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(phu) for i in idx):
        return SpeechPlan(spoken="", remainder_chars=0, reason="slm_output_rejected")
    # Ánh xạ ngược về chỉ số TRONG ĐOẠN GỐC: `chi_so` phải giải nghĩa được ở lượt
    # "nghe tiếp", mà lượt ấy đánh số theo đoạn gốc chứ không theo danh sách đã lọc.
    idx = _them_cau_bat_buoc(cau_list, sorted({ung[i] for i in idx}))

    # Đọc theo thứ tự SỔ TAY, không theo thứ tự model trả về. Sổ tay xe hay viết điều
    # kiện trước rồi mới tới thao tác; đảo lại thì thao tác nghe như vô điều kiện —
    # cũng là một dạng diễn đạt lại, chỉ là bằng thứ tự thay vì bằng chữ.
    chon = [cau_list[i] for i in sorted(set(idx))]
    if any(c not in text for c in chon):
        return SpeechPlan(spoken="", remainder_chars=0, reason="slm_output_rejected")

    ngan_sach = max_chars - len(_INVITE) - 1 if len(text) > max_chars else max_chars
    spoken = _gop_duoi_tran(chon, max(60, ngan_sach))
    if not spoken:
        return SpeechPlan(spoken="", remainder_chars=0, reason="slm_output_rejected")
    return SpeechPlan(
        spoken=spoken,
        remainder_chars=max(0, len(text) - len(spoken)),
        reason="slm",
        chi_so=tuple(sorted(set(idx))),
    )


def xep_hang_theo_lien_quan(cau_list: list[str], question: str, ngan_sach: int) -> list[int]:
    """Chỉ số câu nên đọc, xếp theo **độ liên quan với câu hỏi**, trả về theo thứ tự sổ tay.

    Đây là chỗ S1 bản đầu sai, và sai có hệ thống: nó đọc từ **câu đầu đoạn** xuống,
    mà câu đầu đoạn sổ tay gần như luôn là tiêu đề mục hoặc một câu dẫn nhập. Câu trả
    lời thật thường nằm giữa đoạn, sau trần 240 ký tự.

    Đo trên 40 case `supported` (14/08):

    | cách chọn | trúng ngay lượt đầu |
    |---|---|
    | theo vị trí (bản đầu) | 35,0% |
    | **theo độ liên quan** | **55,0%** |
    | SLM 0.5B chọn câu (S2) | +1 ca — nhiễu |

    Không cần LLM để làm việc này, và đó là kết quả đáng ghi: S2 tốn một tiến trình
    llama-server thường trú cùng 664 ms mỗi lượt để đổi lấy nhiễu, còn `lexical_overlap`
    tốn vài chục micro giây và hơn 20 điểm.

    Trả về theo **thứ tự sổ tay**, không theo thứ tự điểm: sổ tay hay viết điều kiện
    trước rồi mới tới thao tác, đảo lại thì thao tác nghe như vô điều kiện — một dạng
    diễn đạt lại bằng thứ tự thay vì bằng chữ.
    """
    from src.rag.textnorm import lexical_overlap

    # `-i` để khi điểm bằng nhau thì câu **đứng trước** thắng: giữ hành vi cũ ở đoạn mà
    # không câu nào liên quan hơn câu nào, thay vì xáo ngẫu nhiên theo thứ tự sort.
    # Nhãn mục bị loại khỏi ứng viên TRƯỚC khi xếp hạng, không phạt điểm sau.
    # Phạt điểm thì vẫn có đoạn mà nhãn thắng; loại hẳn thì không bao giờ.
    ung = _ung_vien(cau_list)
    theo_diem = sorted(
        ung,
        key=lambda i: (lexical_overlap(question, cau_list[i]) + _diem_dang(question, cau_list[i]), -i),
        reverse=True,
    )
    chon: list[int] = []
    tong = 0
    for i in theo_diem:
        them = len(cau_list[i]) + (1 if chon else 0)
        if tong + them > ngan_sach:
            continue
        chon.append(i)
        tong += them
        if len(chon) >= _TOI_DA_CAU:
            break
    return _them_cau_bat_buoc(cau_list, sorted(chon) if chon else [ung[0]])


def chon_cau_de_noi(
    evidence: Any,
    question: str,
    *,
    max_chars: int = MAX_SPOKEN_CHARS,
    selector: SentenceSelector | None = None,
) -> SpeechPlan:
    """Câu để đọc cho tài xế, luôn trích từ `evidence`.

    Không có `selector` thì hành vi y nguyên S1: chọn theo *vị trí* và *độ an toàn*.
    Có `selector` thì thêm một tầng chọn theo *độ liên quan* — nhưng **chỉ sau khi**
    cổng an toàn của S1 đã cho qua. Thứ tự đó không phải chi tiết cài đặt: đoạn phụ
    thuộc phiên bản là đúng chỗ ADR-015 đo được 4/40 câu gây hiểu lầm, và cho SLM
    chọn ở đó là mở lại đúng cánh cửa ấy — dù nó chỉ chọn chứ không viết, vì câu nó
    chọn có thể là câu mang số của **một** biến thể.
    """
    text, co_bien_the, co_bang = _fields(evidence)
    if not text:
        return SpeechPlan(spoken="", remainder_chars=0, reason="empty")

    cau_list = _cau(text)

    # Thận trọng cả khi thiếu nhãn: `Evidence.has_variant_condition` mặc định False, nên
    # một đoạn dựng tay hoặc lấy từ index cũ sẽ trông như "an toàn". Đoạn vừa có bảng
    # vừa có số thì đối xử như có biến thể.
    can_than = co_bien_the or (co_bang and bool(_NUMBER_WITH_UNIT.search(text)))

    if can_than:
        # Chỉ nhận câu chỉ nguồn **sạch số**. Câu chỉ nguồn nằm ngay trước một bảng sẽ
        # kéo cả bảng vào vì bảng không có dấu kết câu — chính cái bẫy của đoạn
        # "Áp suất lốp" thật.
        for i, cau in enumerate(cau_list):
            if _POINTER_MARKERS.search(cau) and not _NUMBER_WITH_UNIT.search(cau) and len(cau) <= max_chars:
                # `chi_so` phải mang chỉ số câu này. Bỏ trống thì lượt "nghe tiếp" đọc
                # lại đúng câu tài xế vừa nghe — nghe như hệ thống bị kẹt. Bug thật,
                # người dùng gặp khi test tay 15/08.
                return SpeechPlan(
                    spoken=cau, remainder_chars=max(0, len(text) - len(cau)), reason="pointer", chi_so=(i,)
                )
        # `chi_so` rỗng là **đúng** ở đây: `_VARIANT_FALLBACK` là chữ tự viết, chưa câu
        # nào của nguồn được đọc. Nhưng `remainder_chars > 0` nên lời mời vẫn gắn, và
        # `compose` phải lưu nguồn lại — xem `_moc_doc_do`.
        return SpeechPlan(
            spoken=_VARIANT_FALLBACK,
            remainder_chars=len(text),
            reason="variant_fallback",
        )

    # Trừ chỗ cho vế điều kiện **trước khi chọn**, cùng lý do đã trừ chỗ cho lời mời:
    # để dành sau thì đoạn càng dài càng dễ mất đúng thứ phải giữ.
    # ĐÃ THỬ NỚI RỒI HOÀN NGUYÊN (18/08): bỏ đòi hỏi "câu nói phải mang số" để vế điều
    # kiện được gắn cho mọi đoạn tuỳ-trang-bị. Trục chính xác **tụt 64% → 56%** trên bàn
    # cân ba trục. Vế tự viết dài 52 ký tự, và nó ăn đúng chỗ mà cụm cốt lõi cần —
    # nên lý do ghi ở `_gan_ve_dieu_kien` ("thứ đáng lo là con số chứ không phải chủ
    # đề") là một đánh đổi đã được đo, không phải một phỏng đoán.
    can_ve = bool(_TUY_TRANG_BI.search(text)) and bool(_NUMBER_WITH_UNIT.search(text))
    ngan_sach_ve = len(_VE_TUY_TRANG_BI) + 1 if can_ve else 0

    # Câu hỏi "thế nào" thì trả về CÁC BƯỚC, không phải câu mô tả tính năng.
    #
    # Đứng **sau** `can_than` (đoạn có biến thể vẫn phải trả câu chỉ nguồn — bước có thể
    # mang số của một biến thể) và **trước** mọi bộ xếp hạng, vì xếp hạng theo độ liên
    # quan là chính thứ đang chọn sai ở đây. Xem `chon_buoc_thao_tac`.
    #
    # Trừ chỗ cho lời mời **ngay lúc chọn**, đúng như nhánh xếp hạng bên dưới. Bỏ dòng
    # này thì các bước ăn hết trần và `cau_noi_hoan_chinh` phải bỏ lời mời — tức đoạn
    # càng dài, tài xế càng ít có đường nghe tiếp, đúng ngược ý đồ. Đây là cái bẫy đã
    # gặp thật ngày 13/08 ở đoạn "Nước rửa kính"; test `test_luot_so_tay_van_gan_loi_moi_nhu_cu`
    # bắt được nó lần thứ hai khi nhánh này vào.
    ngan_sach_buoc = max_chars - ngan_sach_ve
    if len(text) > max_chars:
        ngan_sach_buoc -= len(_INVITE) + 1
    buoc = chon_buoc_thao_tac(cau_list, question, max(60, ngan_sach_buoc))
    if buoc is not None:
        return _gan_ve_dieu_kien(buoc, can_ve=can_ve)

    # S2 chỉ vào tới đây — sau khi `can_than` đã cho qua.
    if selector is not None:
        ket_qua = _chon_bang_slm(selector, question, cau_list, text, max_chars - ngan_sach_ve)
        if ket_qua is not None and ket_qua.spoken:
            return _gan_ve_dieu_kien(ket_qua, can_ve=can_ve)
        # Bị vứt thì vẫn nói, bằng luật — nhưng `reason` giữ nguyên dấu vết là đã thử
        # và hỏng. Ghi đè thành "plain" ở đây sẽ làm cột eval báo S2 chưa từng chạy.
        ly_do_hong = ket_qua.reason if ket_qua is not None else None
    else:
        ly_do_hong = None

    # Giữ chỗ cho lời mời **ngay lúc chọn**, không để `cau_noi_hoan_chinh` phải bỏ nó
    # vì hết ngân sách.
    #
    # Đo trên server thật (13/08) trước khi có dòng này: đoạn "Nước rửa kính" nói 383 ký
    # tự và **không** có lời mời — phần chọn đã ăn hết trần. Nghĩa là đoạn càng dài, tài
    # xế càng ít có đường nghe tiếp, đúng ngược ý đồ. Đoạn dài hơn trần thì chắc chắn
    # còn phần dư, nên chỗ cho lời mời phải trừ ra trước.
    ngan_sach = max_chars - ngan_sach_ve
    if len(text) > max_chars:
        ngan_sach -= len(_INVITE) + 1
    chon = xep_hang_theo_lien_quan(cau_list, question, max(60, ngan_sach))
    spoken = _gop_duoi_tran([cau_list[i] for i in chon], max(60, ngan_sach))
    chi_so = tuple(chon)
    return _gan_ve_dieu_kien(
        SpeechPlan(
            spoken=spoken,
            remainder_chars=max(0, len(text) - len(spoken)),
            reason=ly_do_hong or "plain",
            chi_so=chi_so,
        ),
        can_ve=can_ve,
    )


def _mo_duoc_chuoi(dan_vao: str | None, *, la_gach: bool) -> bool:
    """Chuỗi bắt đầu ở đây có được tính là **quy trình** không? Hai vế, cả hai cần thiết.

    **Vế phủ quyết.** Câu dẫn hứa điều kiện/hệ quả thì thứ theo sau là bảng sự kiện, không
    phải bước — xem `_DAN_KHONG_PHAI_BUOC`. Chốt này sinh ra từ hồi quy RAG-140, và nó
    đồng thời sửa RAG-112: đoạn ấy có **hai** danh sách — quy trình thật 2 mục dưới
    `"Để kích hoạt đèn sương mù phía sau:"` và danh sách **điều kiện tắt** 3 mục — nên
    luật "chuỗi liền mạch dài nhất" vốn chọn nhầm cái dài hơn.

    **Vế neo.** Một danh sách gạch đầu dòng chỉ là quy trình khi có thứ dẫn vào nó. Chuỗi
    mở đầu bằng câu **không** gạch đầu dòng thì tự neo — đó chính là bước thứ nhất đứng
    thành câu (`"Quan sát tất cả các Cảnh báo…"` của RAG-135). Thiếu vế này thì cổng chỉ
    còn đòi câu dẫn, và RAG-135 mất — đúng thứ PR #230 ghi là "mọi cổng thử nghiệm đều
    làm mất RAG-135".
    """
    if dan_vao is not None and _DAN_KHONG_PHAI_BUOC.search(dan_vao):
        return False
    return not la_gach or dan_vao is not None


def chon_buoc_thao_tac(cau_list: list[str], question: str, max_chars: int) -> SpeechPlan | None:
    """Các **bước** cho câu hỏi dạng *"thế nào"*. `None` = không phải ca này.

    Lấy **chuỗi liền mạch dài nhất** các câu mở đầu bằng động từ thao tác. Liền mạch là
    phần quan trọng: sổ tay hay đặt hai danh sách gạch đầu dòng cạnh nhau, và bản đầu
    của hàm này (chỉ lọc theo "là bước") nuốt luôn danh sách sau — câu trả lời cho *"bật
    đèn sương mù thế nào"* kết thúc bằng *"Trạng thái xe đang TẮT"*, một mục của danh
    sách **điều kiện tắt đèn** nằm ngay dưới. Gặp một câu không phải thao tác thì dừng.

    Đòi **ít nhất hai** bước: đổi đường vì một câu thì không mua được gì mà mất luật xếp
    hạng vốn đang chạy tốt cho câu hỏi một-câu-trả-lời.

    Không đụng cổng an toàn: hàm này chỉ được gọi **sau** khi `can_than` đã cho qua.
    """
    if not _HOI_THAO_TAC.search(question or ""):
        return None

    tot: list[int] = []
    hien: list[int] = []
    # Câu dẫn kết bằng dấu hai chấm đang có hiệu lực — thứ nói cho ta biết danh sách ngay
    # dưới **hứa** cái gì. `None` = danh sách trần, không có gì dẫn vào.
    dan_vao: str | None = None
    for i, cau in enumerate(cau_list):
        s = cau.strip()
        if not s:
            continue  # dòng trống không cắt chuỗi và cũng không xoá câu dẫn
        la_gach = bool(_GACH_DAU_DONG.match(s))
        if la_gach or _DONG_TU_THAO_TAC.match(s):
            if not hien and not _mo_duoc_chuoi(dan_vao, la_gach=la_gach):
                continue
            hien.append(i)
            continue
        if len(hien) > len(tot):
            tot = hien
        hien = []
        # Một câu thường vừa CẮT chuỗi vừa thay câu dẫn: kết bằng ':' thì nó dẫn vào danh
        # sách kế tiếp, không thì nó xoá câu dẫn cũ (danh sách sau đó là danh sách trần).
        dan_vao = s if _DAN_VAO_DANH_SACH.search(s) else None
    if len(hien) > len(tot):
        tot = hien
    if len(tot) < 2:
        return None

    chon: list[int] = []
    manh: list[str] = []
    tong = 0
    for i in tot:
        cau = _GACH_DAU_DONG.sub("", cau_list[i].strip()).strip()
        them = len(cau) + (1 if manh else 0)
        if tong + them > max_chars:
            break
        chon.append(i)
        manh.append(cau)
        tong += them
    if len(chon) < 2:
        return None

    spoken = " ".join(manh)
    da_doc = sum(len(cau_list[i]) for i in chon)
    return SpeechPlan(
        spoken=spoken,
        remainder_chars=max(0, sum(len(c) for c in cau_list) - da_doc),
        reason="buoc_thao_tac",
        chi_so=tuple(chon),
    )


def _gan_ve_dieu_kien(plan: SpeechPlan, *, can_ve: bool) -> SpeechPlan:
    """Gắn vế "tuỳ phiên bản" khi câu nói mang số mà đã rơi mất điều kiện.

    Ba điều kiện phải cùng đúng, và cả ba đều cần thiết:

    - đoạn nguồn nói về tính năng tuỳ trang bị (`can_ve`),
    - câu nói **thật sự** đọc ra một đại lượng — gắn vô điều kiện thì mọi lượt dài
      thêm một câu, mà thứ đáng lo là con số chứ không phải chủ đề,
    - câu nói **chưa** mang sẵn điều kiện — S1 thường đã có vì bắt đầu từ câu tiêu đề,
      và nhắc hai lần nghe như máy hỏng.
    """
    if not can_ve or not plan.spoken:
        return plan
    if not _NUMBER_WITH_UNIT.search(plan.spoken) or _TUY_TRANG_BI.search(plan.spoken):
        return plan
    return SpeechPlan(
        spoken=f"{_VE_TUY_TRANG_BI} {plan.spoken}",
        remainder_chars=plan.remainder_chars,
        reason=plan.reason,
    )


#: Câu trả lời khi tài xế bảo đọc tiếp mà không còn gì để đọc.
#:
#: Hai đường dẫn tới đây và cố ý dùng **chung** một câu: đọc hết đoạn, và không có
#: đoạn nào đang dở (backend vừa restart — trạng thái đọc dở chết cùng tiến trình,
#: y như checkpoint giữ `interrupt()` của HITL). Phân biệt hai đường bằng lời nói sẽ
#: bắt tài xế nghe một lời giải thích về nội tình hệ thống lúc đang lái.
_HET_PHAN_DU = "Tôi đã đọc hết phần này rồi."


def doc_tiep(source: str, da_doc: list[int] | tuple[int, ...], *, max_chars: int = MAX_SPOKEN_CHARS) -> SpeechPlan:
    """Các câu **chưa đọc** kế tiếp, theo thứ tự sổ tay.

    Nguyên văn ở mức câu: hàm này chỉ **chọn**, không cắt lại và không diễn đạt lại —
    cùng lý do S2 phải trả về chỉ số thay vì chữ (ADR-015).
    """
    cau_list = _cau(source) if source else []
    da = set(da_doc or ())
    # Đi TỚI, không lấp ngược: chỉ những câu nằm SAU câu đã đọc xa nhất.
    #
    # Lượt đầu chọn theo độ liên quan nên các câu nó lấy thường rời rạc — đo 18/08:
    # **31 trên 39 ca**. Lấp ngược thì tài xế nghe câu 1 SAU câu 2, tức nghe ngược thứ
    # tự thao tác của một quy trình. Với sổ tay xe, sai thứ tự bước còn tệ hơn thiếu bước.
    #
    # Cái giá: những câu bị nhảy qua không bao giờ vào kênh nói. Chấp nhận được, vì
    # chính bộ xếp hạng đã xếp chúng dưới, và `display_text` vẫn giữ nguyên cả đoạn.
    #
    # Phương án còn lại — bắt lượt đầu chọn một cửa sổ liền mạch — đã thử và đo:
    # trục chính xác tụt **64% → 54%**. Mười điểm ấy rơi vào MỌI lượt, còn thứ tự chỉ
    # ảnh hưởng những lượt tài xế thật sự nói "có". Nên chọn giữ điểm, sửa ở đây.
    moc = max(da) if da else -1
    con = [i for i in range(moc + 1, len(cau_list)) if i not in da]
    if not con:
        return SpeechPlan(spoken="", remainder_chars=0, reason="continue_exhausted")

    con_du = sum(len(cau_list[i]) for i in con) > max_chars
    ngan_sach = max(60, max_chars - len(_INVITE) - 1 if con_du else max_chars)
    chon: list[int] = []
    tong = 0
    for i in con:
        them = len(cau_list[i]) + (1 if chon else 0)
        if tong + them > ngan_sach:
            break
        chon.append(i)
        tong += them

    if chon:
        spoken = " ".join(cau_list[i] for i in chon)
    else:
        # Một câu đơn dài hơn cả trần. Đọc phần đầu và **vẫn đánh dấu đã đọc**: không
        # đánh dấu thì lượt sau đọc lại đúng câu ấy, tức vòng lặp không tiến. Phần đuôi
        # mất ở kênh nói nhưng còn nguyên trong `display_text`.
        chon = [con[0]]
        spoken = _gop_duoi_tran([cau_list[con[0]]], ngan_sach)

    da_chon = set(chon)
    con_lai = sum(len(cau_list[i]) for i in con if i not in da_chon)
    return SpeechPlan(spoken=spoken, remainder_chars=con_lai, reason="continue", chi_so=tuple(chon))


def cau_noi_het_phan_du() -> str:
    return _HET_PHAN_DU


#: Gạch đầu dòng ở đầu chuỗi, hoặc ngay sau dấu kết câu / dấu hai chấm.
#: Chỉ bắt gạch **có khoảng trắng theo sau** — "bán-tự-động" và "ca-pô" phải còn nguyên.
#:
#: `["'”’\s]*` giữa dấu câu và dấu gạch là bắt buộc: chuỗi thật 18/08 là
#: `…hướng dẫn như sau:" - Nếu bất kỳ lúc nào…`, tức dấu ngoặc đóng của câu dẫn do SLM
#: sinh chen vào giữa. Bản đầu thiếu nó, và bộ **dò** ở `tu_nhien.py` bắt được ca ấy
#: trong khi bộ **dọn** ở đây thì không — một cặp lệch nguy hiểm hơn cả hai cùng sai,
#: vì bàn cân báo sạch còn production thì không.
_GACH_DAU_DONG = re.compile("(?:^|[.!?:][\"'”’\\s]*|\\n)\\s*[-•–—]\\s+")


#: Bỏ dấu hỏi cuối và mở đầu rườm rà, để ghép câu hỏi vào khung câu dẫn.
_BO_DAU_HOI = re.compile(r"\s*[?？]+\s*$")
_MO_DAU_RUOM = re.compile(
    r"^\s*(?:cho\s+(?:tôi|mình)\s+hỏi\s*|làm\s+sao\s+(?:để\s+)?|làm\s+thế\s+nào\s+(?:để\s+)?|cách\s+"
    r"|khi\s+nào\s+|tại\s+sao\s+|xin\s+hỏi\s+|hướng\s+dẫn\s+)",
    re.IGNORECASE,
)
#: Đuôi nghi vấn. Bỏ đi thì câu hỏi thành **chủ đề**, ghép vào khung câu kể mới xuôi:
#: *"Về độ sâu gai lốp tối thiểu là bao nhiêu, sổ tay…"* → *"Về độ sâu gai lốp tối
#: thiểu, sổ tay…"*. Đây đúng phép biến đổi mà Qwen 3B vẫn làm, chỉ khác là 0 ms.
_DUOI_NGHI_VAN = re.compile(
    r"\s*(?:thì\s+)?(?:là\s+)?(?:dùng\s+|sử\s+dụng\s+)?(?:bao\s+nhiêu|ở\s+đâu|chỗ\s+nào"
    r"|như\s+thế\s+nào|thế\s+nào|ra\s+sao|bằng\s+cách\s+nào|làm\s+sao|xử\s+lý\s+sao"
    r"|dùng\s+để\s+làm\s+gì|nghĩa\s+là\s+gì|có\s+nghĩa\s+là\s+gì|là\s+gì|được\s+không|hay\s+không|không"
    r"|hoạt\s+động\s+(?:ra\s+sao|thế\s+nào|khi\s+nào))\s*$",
    re.IGNORECASE,
)
#: Khung câu dẫn, và **trần chủ đề**.
#:
#: Câu dẫn ăn thẳng vào ngân sách 240 ký tự của phần thân, nên mỗi ký tự ở đây là một
#: ký tự tài xế không được nghe nội dung. Đo 19/08: bản đầu dùng khung 25 ký tự
#: (*"sổ tay hướng dẫn như sau:"*) và không chặn chủ đề, cho ra câu dẫn tới 68 ký tự —
#: trục chính xác **tụt 64% → 56%** so với chuỗi cố định 46 ký tự.
#:
#: Chủ đề dài hơn trần thì bỏ hẳn: một câu dẫn nêu lại nguyên văn câu hỏi dài không
#: giúp tài xế thêm gì, họ vừa hỏi xong.
_KHUNG_CAU_DAN = "sổ tay ghi:"
_TRAN_CHU_DE = 34
_CAU_DAN_NGAN = "Sổ tay ghi:"


def cau_dan_tu_cau_hoi(question: str) -> str:
    """Câu dẫn ghép từ **chính chữ của tài xế** — 0 ms, và không bịa được.

    Đo 19/08 trên 39 câu hỏi (`eval/results/cau-dan/`), cùng một vai trò:

    | cách sinh | p50 | câu dẫn chứa số | từ lạ / câu |
    |---|---|---|---|
    | **mẫu này** | **0 ms** | **0%** | **0,00** |
    | Qwen 0.5B trên CPU | 683 ms | **8%** | 6,38 |
    | Qwen 3B trên dGPU | 421 ms | 0% | 1,51 |

    Con số 8% kia không phải chuyện thẩm mỹ. Ba câu dẫn thật của 0.5B:

    - *"Áp suất lốp khuyến nghị của xe là **200 kPa**."* — thật là 260/270 kPa
    - *"Độ sâu gai lốp tối thiểu là **10mm**."* — thật là 2 mm
    - *"Đèn ban ngày hoạt động vào **khoảng 6 giờ sáng**."* — không có ở đâu cả

    Câu dẫn chỉ nhìn thấy câu hỏi và tên mục; nó **không đọc đoạn nào**. Nên mọi con số
    nó nói ra đều không có nguồn — đúng ca RAG-130 mà SPIKE-004 gọi là "ca đáng sợ
    nhất". Qwen 3B sạch số trên bộ này nhưng vẫn bịa khẳng định: *"sổ tay khuyên bạn
    nên căn chỉnh và cân bằng bánh xe định kỳ"*.

    Và nhìn đầu ra của 3B thì phần lớn đã đúng dạng `"<câu hỏi>, sổ tay hướng dẫn như
    sau:"` — tức ta trả 421 ms trên dGPU, 2316 ms trên CPU, cho một phép nối chuỗi.
    """
    lo = _BO_DAU_HOI.sub("", (question or "").strip())
    lo = _MO_DAU_RUOM.sub("", lo).strip()
    lo = _DUOI_NGHI_VAN.sub("", lo).strip().rstrip(",;:")
    if not lo:
        return ""
    if len(lo) > _TRAN_CHU_DE:
        return _CAU_DAN_NGAN
    return f"Về {lo[0].lower() + lo[1:]}, {_KHUNG_CAU_DAN}"


def lam_sach_de_noi(s: str) -> str:
    """Dọn **định dạng trang giấy** khỏi chuỗi sắp đưa vào TTS. Không đổi một chữ nào.

    Đo 18/08 trên 39 ca (`eval/results/ba-truc/20260818T165614Z`): chỉ **18%** lượt
    không có khuyết tật, và thủ phạm áp đảo là **xuống dòng — 24/39 ca với luật S1,
    30/39 với thác**. Sổ tay viết để đọc bằng mắt, nên chunk mang nguyên bố cục trang;
    bố cục ấy đi thẳng vào kênh âm thanh và Piper đọc nó thành một quãng ngắt vô nghĩa.

    Hai điều hàm này **cố ý không làm**:

    1. **Không sửa bộ tách câu.** `_SENTENCE_SPLIT` không tách ở xuống dòng, nên tiêu
       đề bị dán liền câu đầu. Đã thử sửa 17/08 và tỷ lệ nói trúng đáp án **tụt từ 72%
       xuống 36%** — đã hoàn nguyên. Hàm này chạy **sau** khi chọn xong, nên nó không
       chạm vào chỉ số câu và không thể tái diễn hồi quy ấy.
    2. **Không bỏ chữ nào.** Chỉ khoảng trắng và ký tự đánh dấu danh sách bị dọn. Mọi
       token còn nguyên và còn đúng thứ tự, nên `chi_so` vẫn giải nghĩa ngược được và
       ADR-015 không bị đụng tới.

    Chạy ở `cau_noi_hoan_chinh` — điểm nghẽn duy nhất của chuỗi cuối. Đặt ở đây thì
    kết quả **chỉ có thể ngắn đi**, nên không lượt nào vỡ trần vì phép dọn này.
    """
    s = re.sub(r"\s+", " ", s or "")
    s = _GACH_DAU_DONG.sub(" ", s)
    s = s.lstrip("-•–— ")
    return re.sub(r"\s{2,}", " ", s).strip()


def cau_noi_hoan_chinh(plan: SpeechPlan, *, max_chars: int = MAX_SPOKEN_CHARS) -> str:
    """Chuỗi cuối cùng đưa cho TTS: phần đã chọn, cộng lời mời **nếu còn phần dư**.

    Chỉ mời khi thật sự còn gì để nghe. Mời vô điều kiện thì cả lệnh "bật điều hoà"
    cũng bị hỏi "nghe tiếp không?", và một câu thừa lặp mỗi lượt còn khó chịu hơn im
    lặng.

    Câu trả lời cho lời mời này là một **voice intent**, dùng chung hạ tầng với
    `approval.intent.detected` — theo dõi ở issue #107. Task 4 chỉ làm ra lời mời;
    chưa ai nghe được câu trả lời.
    """
    spoken = lam_sach_de_noi(plan.spoken)
    if not spoken:
        return ""
    if plan.remainder_chars <= 0:
        return spoken
    ung_vien = f"{spoken} {_INVITE}"
    # Thà bỏ lời mời còn hơn để lưới cuối ở `ivi_events` cắt cụt giữa câu.
    return ung_vien if len(ung_vien) <= max_chars else spoken

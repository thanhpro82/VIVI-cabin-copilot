"""Cổng tất định sau generator chitchat — SP-2 §2.2.

Đây là chỗ DUY NHẤT chặn bịa. Bốn lớp, thứ tự cố định, vỡ lớp nào rơi về câu
mẫu của lớp đó; không bao giờ phát chuỗi model đã bị chặn. Tên lớp trả ra để
eval đếm được từng lớp vỡ bao nhiêu.
"""

from __future__ import annotations

import re

from src.agents.nodes.speech_policy import _NUMBER_WITH_UNIT, _SENTENCE_SPLIT, MAX_SPOKEN_CHARS
from src.rag.tu_nhien import dem_khuyet_tat

#: Câu mẫu chung — chữ tự viết, không mang dữ kiện.
CAU_MAU_CHUNG = "Tôi nghe bạn đây. Bạn muốn tôi giúp gì trên xe không?"

#: Câu nói khi **van đồng thời đầy** — không phải lỗi, và phải nói rõ là tạm thời.
#:
#: PM/PO review PR #257: *"không được im lặng timeout/fallback"*. Trước bản vá, lượt
#: gặp quá tải chờ 26 giây rồi nhận `"tôi chưa hiểu ý anh"` — câu đó **nói sai nguyên
#: nhân**: tài xế tưởng mình nói khó nghe, thật ra là máy hết chỗ. Câu dưới nói đúng
#: chuyện đang xảy ra và nói được ngay, không bắt ai chờ.
CAU_BAN = "Xin lỗi, xe đang bận xử lý cho người khác. Bạn nói lại sau vài giây giúp tôi nhé."

#: Lớp (c): model nói số kèm đơn vị → chuyển hướng về sổ tay thay vì phát con số.
CAU_CHUYEN_HUONG_SO = "Về thông số của xe, để tôi tra sổ tay cho chính xác — bạn hỏi lại tôi nhé."

#: Lớp (c): `_NUMBER_WITH_UNIT` của speech_policy chỉ biết đơn vị sổ tay hay đọc
#: (kPa, psi, km/h...) — nó KHÔNG bắt "450 km" trần, đúng ca SP-0 đo được. Chitchat
#: cấm MỌI số kèm đơn vị, nên ghép thêm bộ đơn vị đời thường: km, kWh, lít, %, giờ...
_SO_KY_THUAT = re.compile(
    r"\d+[.,]?\d*\s*(km|kwh|kw|lít|lit|phần trăm|%|độ|giờ|phút|giây|mm|cm|kg|mã lực|hp|ah)(?![a-z])",
    re.IGNORECASE,
)

#: Lớp (e): khẳng định về **hành trình** mà chitchat không có cách nào biết.
#:
#: Ca thật `CC-AB05` (run `chitchat/20260823T010523`): *"Còn xa không nhỉ, đi mãi
#: không đến"* → *"Đi tiếp một chút nữa thôi, **đích đến gần rồi** nha!"*. Node
#: chitchat không đọc trạng thái dẫn đường; "gần rồi" là một con số được bịa ra
#: bằng chữ. Cùng lớp với cổng (c), chỉ khác là dữ kiện không mang đơn vị nên
#: `_SO_KY_THUAT` không thấy.
#:
#: Hẹp có chủ đích: phải có **đối tượng hành trình** (đích đến / nơi / điểm đến)
#: đi cùng **khẳng định gần**, để câu động viên chung chung không bị chặn oan.
_DOAN_HANH_TRINH = re.compile(
    r"(?:đích đến|điểm đến|tới nơi|đến nơi)[^.!?]{0,20}?(?:gần|sắp|rồi)"
    r"|(?:gần|sắp)[^.!?]{0,15}?(?:đích đến|điểm đến|tới nơi|đến nơi)",
    re.IGNORECASE,
)

#: Lớp (d): model không được NÓI rằng đã làm gì trên xe — nó không có tay.
_NOI_DA_LAM = re.compile(r"\bđã\s+(bật|tắt|mở|đóng|đặt|chỉnh|phát|dừng|khóa|khoá|hạ|kéo)\b", re.IGNORECASE)

_KET_CAU = re.compile(r"[.!?]$")


#: Lớp (0) — cổng ĐẦU VÀO: tài xế đang báo một triệu chứng của xe.
#:
#: Ca thật `CC-AN14` (run `chitchat/20260823T005108.974795Z`): *"Thắng dạo này kêu
#: két két là sao ta"* nhận lại *"Có lẽ xe đang hơi mệt, bạn cứ lái nhẹ để nó thư
#: giãn nhé!"* — phanh kêu là triệu chứng an toàn, và câu trả lời khuyên **lái tiếp**.
#:
#: Vì sao chặn ở đầu vào chứ không ở đầu ra: thứ sai không phải *cách nói* của model
#: mà là *việc chitchat được trả lời câu này*. Bốn lớp cổng đầu ra đều xét chuỗi trả
#: về, nên không lớp nào bắt nổi một câu trấn an sạch sẽ về mặt hình thức.
#:
#: Hẹp có chủ đích — cần **bộ phận xe + biểu hiện**, để "tôi hơi mệt" hay "kẹt xe
#: muốn khùng luôn" không bị chặn oan. Vài từ đứng một mình đã đủ nguy hiểm
#: (khói, khét, cháy, mất phanh, mất lái) nên được liệt riêng.
_BO_PHAN_XE = r"(?:phanh|thắng|lốp|bánh|vô lăng|tay lái|động cơ|máy|hộp số|ắc quy|bình điện|đèn báo|còi|gương|cửa|kính|kiếng|xe)"
_BIEU_HIEN = r"(?:kêu|rung|lắc|rơ|lỏng|hỏng|hư|xịt|thủng|nóng|khét|cháy|khói|chảy|rò|kẹt|nứt|vỡ|lỗi|báo lỗi|không ăn|mất)"
_TRIEU_CHUNG_AN_TOAN = re.compile(
    rf"{_BO_PHAN_XE}[^.!?]{{0,30}}?{_BIEU_HIEN}|{_BIEU_HIEN}[^.!?]{{0,20}}?{_BO_PHAN_XE}"
    r"|mùi khét|mùi cháy|bốc khói|mất phanh|mất lái|nổ lốp",
    re.IGNORECASE,
)

#: Chữ tự viết. Cố ý **không** trấn an và **không** đoán nguyên nhân: mời tra sổ tay
#: và mời đi kiểm tra là hai việc duy nhất an toàn khi chưa biết xe đang sao.
CAU_CHUYEN_HUONG_AN_TOAN = (
    "Nghe như xe đang có dấu hiệu bất thường — chuyện này tôi không đoán được. "
    "Bạn hỏi lại để tôi tra sổ tay, hoặc mang xe đi kiểm tra cho chắc nhé."
)


#: Cụm trông giống triệu chứng nhưng là chuyện đời sống. `"kẹt xe"` khớp cả `xe` lẫn
#: `kẹt`, `"tắc đường"` khớp `đường`; chặn chúng là chặn oan đúng nhóm câu chitchat
#: sinh ra để nói.
#:
#: **Vô hiệu CỤM, không phủ quyết CÂU** — hồi quy @thanhpro82 báo ở #252. Bản đầu
#: trả `None` ngay khi thấy một trong các cụm này ở bất kỳ đâu, nên
#: `"Xe bốc khói vì kẹt xe"` và `"Kẹt xe mà phanh lại kêu két két"` lọt sạch cổng
#: an toàn. Đây là kiểu hỏng kinh điển của allowlist đặt sai tầng: nó được quyền
#: nói *"cụm này vô hại"*, không được quyền nói *"cả câu vô hại"*.
_KHONG_PHAI_TRIEU_CHUNG = ("kẹt xe", "tắc đường", "kẹt đường")


def cong_dau_vao_chitchat(normalized_text: str) -> str | None:
    """Chặn TRƯỚC khi gọi model. `None` = cho qua, chuỗi = câu phải nói thay."""
    text = (normalized_text or "").lower()
    # Xoá cụm vô hại rồi mới dò, để phần CÒN LẠI của câu vẫn được soi.
    for cum in _KHONG_PHAI_TRIEU_CHUNG:
        text = text.replace(cum, " ")
    if _TRIEU_CHUNG_AN_TOAN.search(text):
        return CAU_CHUYEN_HUONG_AN_TOAN
    return None


def qua_cong_chitchat(reply: str) -> tuple[str, str]:
    """Trả `(chuỗi phát, tên cổng)`; `"qua"` nghĩa là phát nguyên chuỗi model."""
    s = (reply or "").strip()
    # (a) hệ chữ lạ — dùng lại bộ dò theo tên Unicode của tu_nhien; rỗng cũng về đây.
    if not s or "ky_tu_la" in dem_khuyet_tat(s).khuyet_tat:
        return CAU_MAU_CHUNG, "he_chu_la"
    # (b) quá dài — cắt ở ranh giới câu; không có ranh giới nào lọt trần thì câu mẫu.
    if len(s) > MAX_SPOKEN_CHARS:
        giu: list[str] = []
        for cau in _SENTENCE_SPLIT.split(s):
            cau = cau.strip()
            if not cau:
                continue
            if len(" ".join([*giu, cau])) > MAX_SPOKEN_CHARS:
                break
            giu.append(cau)
        cat = " ".join(giu)
        return (cat if cat and _KET_CAU.search(cat) else CAU_MAU_CHUNG), "qua_dai"
    # (c) số kèm đơn vị — thông số xe là việc của sổ tay, không của chitchat.
    if _NUMBER_WITH_UNIT.search(s) or _SO_KY_THUAT.search(s):
        return CAU_CHUYEN_HUONG_SO, "so_ky_thuat"
    # (d) nói đã làm gì trên xe.
    if _NOI_DA_LAM.search(s):
        return CAU_MAU_CHUNG, "noi_da_lam"
    # (e) đoán hành trình — dữ kiện không mang đơn vị nên (c) không thấy.
    if _DOAN_HANH_TRINH.search(s):
        return CAU_MAU_CHUNG, "doan_hanh_trinh"
    return s, "qua"

"""Lời đề nghị đang treo: xe vừa nêu một việc, tài xế đáp có/không ở lượt sau.

Đây là phần **thuần** của cơ chế; phần đọc/ghi state nằm ở `nodes/route.py`, cùng chỗ
đứng và cùng lập luận với `ghep_hoi_lai.py` (ADR-006/ADR-010: router không đọc state).

## Vấn đề nó giải

`offer` là disposition duy nhất **không phải** `control` mà vẫn mang sẵn một
`candidate_plan` đã dựng xong và hợp lệ (`contracts._PLAN_BEARING_DISPOSITIONS`). Trước
issue #355, lượt sau vứt plan ấy đi:

    lượt 1  "Bật điều hòa được không"  -> offer, plan SẴN CÓ: set_hvac_power{enabled:True}
            VIVI: "Tôi có thể bật điều hòa. Bạn có muốn tôi thực hiện không?"
    lượt 2  "Có"                       -> not_control/default_to_manual, 0 lệnh

Xe hỏi một câu có/không rồi không nghe được câu trả lời của chính nó. Cùng một lỗ với
issue #339 (lời mời sau `blocked`), nên hai cái dùng chung cơ chế này.

## Vì sao nó phục vụ mục tiêu "đừng bắt nói lại Hey VIVI"

Đó là lý do multiturn được đặt ra. Sau `offer`, xe **đã nói ra hành động cụ thể** và câu
trả lời là một lựa chọn đóng có/không — cùng hình dạng với phê duyệt HITL, nơi FE đã tự
mở mic sẵn từ #207b. Nên đây là chỗ nới cửa sổ nghe tiếp mà **không** phải mở một loại
rủi ro mới: cùng ràng buộc, cùng bộ nhận dạng, cùng độ dài ngữ cảnh.

Sau `clarify` thì **khác hẳn** và cố ý không làm ở đây: câu trả lời là một mảnh tự do
(*"mức 2"*, *"bên lái"*), nơi một tiếng lạc có thể thành một lệnh không ai yêu cầu. Việc
ấy là của #363, và nó cần một cơ chế khác — mẫu ngữ pháp cứng cho từng lý do `clarify`,
không khớp thì NO_EXEC. Ở đây không cần mẫu nào cả: có/không đã là một tập đóng hai phần
tử, và xe vừa đọc to đúng hành động sắp làm.

## Ba chốt

Ít hơn `ghep_hoi_lai` một chốt, vì chốt "kết quả ghép phải có nghĩa" không có ở đây —
không có phép ghép nào cả, plan đã dựng xong từ lượt trước.

1. **chỉ lượt kế tiếp ngay sau** — `route_node` xoá slot ở cuối mọi lượt không phải
   `offer`, y hệt `_moc_hoi_lai`. Không có bộ đếm lượt.
2. **TTL** `TTL_GIAY` — một tiếng "có" tới sau nửa phút nhiều khả năng đang nói chuyện
   khác. Cùng con số với `ghep_hoi_lai` có chủ ý: hai cửa sổ ngữ cảnh khác nhau về độ
   dài là thứ không ai giải thích được cho tài xế.
3. **lệnh mới thắng** — nếu lượt mới tự khớp `control` thì đó là lệnh, không phải câu
   trả lời. `"Mở cốp xe"` sau một đề nghị điều hòa phải mở cốp.

## Không nới bộ nhận dạng

Dùng thẳng `voice_intent.doc_tra_loi_co_khong`, không có bảng từ riêng. Docstring của nó
đã cảnh báo đúng ca nguy hiểm ở đây: `"Ừ mở kính"`, `"Có mở cốp"` **không** phải câu trả
lời — chúng có tiếng trần đứng trước một lệnh, và nhận bừa thì tài xế nhận về một hành
động khác hẳn thứ họ vừa nói. Hai bảng từ song song là đúng thứ #107 cảnh báo sẽ lệch.
"""

from __future__ import annotations

from typing import Literal

from src.agents.ghep_hoi_lai import TTL_GIAY
from src.agents.voice_intent import doc_tra_loi_co_khong

__all__ = ["TTL_GIAY", "con_han", "doc_dap_loi_de_nghi"]


def con_han(luc_de_nghi: float, bay_gio: float) -> bool:
    """Lời đề nghị đặt lúc `luc_de_nghi` còn hiệu lực tại `bay_gio` không?

    `0.0` = không có đề nghị nào. Đồng hồ chạy lui (giá trị âm) cũng trả `False`: thà
    bỏ một câu trả lời hợp lệ còn hơn chạy một lệnh vì một phép trừ sai dấu.
    """
    if luc_de_nghi <= 0.0:
        return False
    return 0 <= bay_gio - luc_de_nghi <= TTL_GIAY


def doc_dap_loi_de_nghi(text: str) -> Literal["nhan", "tu_choi"] | None:
    """Câu này có phải lời đáp cho một đề nghị đang treo không? `None` = đi đường thường."""
    tra_loi = doc_tra_loi_co_khong(text)
    if tra_loi is None:
        return None
    return "nhan" if tra_loi == "co" else "tu_choi"

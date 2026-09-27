"""Composer: chỉ báo cáo outcome đã verify. Không suy đoán thành công."""

import asyncio
import logging
import time
import uuid
from functools import lru_cache, partial
from pathlib import Path
from typing import Any

from src.agents.nodes.speech_policy import (
    MAX_SPOKEN_CHARS,
    _cham_dut,
    cau_dan_tu_cau_hoi,
    cau_noi_het_phan_du,
    cau_noi_hoan_chinh,
    chon_cau_de_noi,
    doc_tiep,
)
from src.agents.state import AgentState
from src.config import get_settings

_NGOAC_CAU_DAN = ('"', "“", "”", "'", "«", "»")


def lam_sach_cau_dan(text: str) -> str:
    """Bóc cặp ngoặc bao ngoài câu dẫn do SLM sinh. `""` = bác, dùng câu dẫn cố định.

    Qwen trả câu dẫn bọc trong ngoặc kép, và nghiệm thu đường thật 18/08 cho **5/5**
    lượt mở đầu bằng một dấu ngoặc thừa: `"Bánh xe bị xịt, sổ tay hướng dẫn như sau:"`.

    Chỉ bóc khi ngoặc có ở **cả hai đầu**: một dấu ngoặc lẻ có thể là trích dẫn thật
    nằm trong nội dung, và bóc nó đi là sửa nội dung chứ không phải dọn định dạng.
    """
    s = (text or "").strip()
    while len(s) >= 2 and s[0] in _NGOAC_CAU_DAN and s[-1] in _NGOAC_CAU_DAN:
        s = s[1:-1].strip()
    return s


@lru_cache(maxsize=1)
def _thac_chon_cau():
    """Thác chọn câu, dựng một lần cho cả tiến trình. `None` = đi đường luật S1.

    `lru_cache` ở đây cache **đối tượng**, không cache trọng số — trọng số vẫn nạp
    trễ bên trong `ThacChonCau`. Nên một checkout không bật cờ chẳng trả tiền gì, và
    một checkout bật cờ chỉ trả tiền nạp ở lượt tra sổ tay đầu tiên.

    Thiếu thư mục trọng số thì trả `None` **ngay tại đây** chứ không để `select` ném
    mỗi lượt: hỏng cấu hình phải lộ ra một lần lúc khởi động, không phải thành một
    dòng warning lặp lại mãi mà vẫn "chạy được".
    """
    settings = get_settings()
    if not settings.chon_cau_thac_enabled:
        return None
    thu_muc = Path(settings.chon_cau_thac_model_dir)
    if not thu_muc.is_dir():
        logging.getLogger(__name__).warning("chon_cau_thac_enabled=True nhưng không thấy %s — dùng luật S1", thu_muc)
        return None
    from src.agents.chon_cau_thac import ThacChonCau
    from src.agents.nodes.rag_node import _default_embedder

    return ThacChonCau(
        thu_muc,
        _default_embedder(),
        pool=settings.chon_cau_thac_pool,
        top=settings.chon_cau_thac_top,
        int8=settings.chon_cau_thac_int8,
    )


#: Câu đáp khi tài xế từ chối một lời đề nghị (#355). Ngắn có chủ ý: tài xế vừa nói
#: "thôi", thứ tệ nhất lúc ấy là một câu dài thuyết phục lại. Không hỏi thêm gì — một
#: câu hỏi ở đây mở lại đúng cái vòng vừa đóng.
TU_CHOI_DE_NGHI = "Vâng, tôi không thực hiện."

#: Câu đáp khi tài xế đuổi trợ lý đi (#363, spec §3.3). Ngắn nhất có thể, có chủ ý: họ
#: vừa bảo thôi, nên thứ tệ nhất lúc ấy là một câu dài — và một câu hỏi thì còn tệ hơn,
#: nó mở lại đúng cái vòng vừa đóng.
GIAI_TAN = "Vâng."

#: Sáu lối ra của đường Routine (#274, #299). Mỗi câu nói rõ xe ĐÃ hay CHƯA làm gì.
#:
#: Đó không phải khẩu vị: khi router đã biết `disposition="routine"` mà sáu lối ra này còn
#: chưa có câu nào, đo qua HTTP thật (30/08) cho ra `"Đã xử lý yêu cầu."` với
#: `action_plan: null` — xe báo xong một việc nó chưa hề làm. Bài học `CLARIFY_MESSAGES`
#: (#148), lần này ở một lệnh an toàn.
ROUTINE_DA_CHAY = "Đang chạy chuỗi lệnh cho bạn."
ROUTINE_DA_HUY = "Đã dừng chuỗi lệnh."
#: Nói THẬT khi không có gì để hủy. Báo "đã hủy" ở đây là nói dối về một việc an toàn —
#: tài xế tin rằng xe vừa dừng một thứ đang chạy, và thôi không tìm cách dừng nó nữa.
ROUTINE_KHONG_CO_LAN_CHAY = "Hiện không có chuỗi lệnh nào đang chạy."
ROUTINE_XEM_TRUOC = "Đây là các bước của chuỗi lệnh này. Bạn có muốn tôi chạy không?"
#: Lỗi hệ thống, KHÔNG phải "tài khoản trống". Hai thứ ấy nghe giống nhau với tài xế
#: nhưng khác hẳn với người sửa lỗi — xem `routine_node` để biết vì sao tách.
ROUTINE_LOI_NGU_CANH = "Tôi chưa mở được danh sách chuỗi lệnh lúc này."
#: Tài xế TỪ CHỐI một preview (review PR #401) — khác `ROUTINE_DA_HUY` ("Đã dừng
#: Routine"): không có gì đang chạy để dừng, đây chỉ là quyết định không chạy nó.
ROUTINE_HUY_XEM_TRUOC = "Đã huỷ, không chạy chuỗi lệnh này."

OUTCOME_MESSAGES: dict[str, str] = {
    "completed": "Đã thực hiện lệnh trên xe mô phỏng.",
    "execution_failed": "Không thực hiện được đầy đủ lệnh; xem chi tiết từng bước.",
    "blocked": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép.",
    "approval_required": "Lệnh này cần bạn xác nhận trước khi thực hiện.",
    "clarify": "Bạn muốn điều chỉnh cụ thể như thế nào?",
    "denied": "Xin lỗi, tôi không thực hiện được yêu cầu này.",
    "validation_denied": "Yêu cầu không hợp lệ nên tôi chưa thực hiện.",
    "not_control": "Tôi chưa rõ bạn muốn điều khiển gì.",
    "grounded_answer": "Đây là thông tin tôi tìm được trong sổ tay xe.",
    # Luot "doc tiep" (S3). Co outcome RIENG chu khong muon `not_control`: o do la
    # nghia "toi chua hieu ban muon gi", nen mot luot doc tiep THANH CONG roi vao
    # do se lam /metrics/summary va man hinh engineer dem no nhu mot luot khong hieu.
    "grounded_continue": "Đọc tiếp phần còn lại trong sổ tay xe.",
    "grounded_refusal": "Tôi không tìm thấy thông tin này trong sổ tay xe.",
    "index_unavailable": "Tôi chưa tra được sổ tay xe lúc này.",
    # Fail-closed của `safety_node`: không đọc được trạng thái xe thì không phân
    # loại được S0-S3, nên từ chối thay vì đoán. Nói rõ là lỗi hệ thống, đừng để
    # tài xế tưởng mình nói sai.
    "vehicle_state_unavailable": "Tôi chưa đọc được trạng thái xe nên chưa dám thực hiện lệnh.",
    "approval_granted": "Bạn đã đồng ý; tôi thực hiện ngay.",
    "approval_rejected": "Đã hủy theo lựa chọn của bạn.",
    "approval_expired": "Xác nhận đã hết hạn nên tôi không thực hiện.",
    "approval_invalidated_plan": "Lệnh đã thay đổi nên xác nhận cũ không còn dùng được.",
    "approval_invalidated_state": "Trạng thái xe đã thay đổi; bạn xác nhận lại giúp tôi.",
    "approval_predicate_failed": "Xe không còn ở trạng thái an toàn cho lệnh này nữa.",
    "approval_already_pending": "Đang có một lệnh chờ bạn xác nhận; xong lệnh đó rồi tôi làm tiếp.",
    "approval_not_owned": "Xác nhận đó không thuộc lượt này nên tôi không thực hiện.",
    "retrieval_failed": "Tôi gặp lỗi khi tra sổ tay xe. Bạn thử lại giúp tôi nhé.",
}

_FALLBACK = "Đã xử lý yêu cầu."

#: Câu hỏi lại **theo lý do**, đè lên `OUTCOME_MESSAGES["clarify"]`.
#:
#: Câu chung — "Bạn muốn điều chỉnh cụ thể như thế nào?" — vô dụng ở đúng chỗ nó
#: cần có ích nhất. Với `"tắt đèn"` router **đã** làm đúng phần khó: nó không đoán,
#: không thực thi (`missing_light_target`). Nhưng lý do đó chỉ nằm trong
#: `RouteDecision`, không bao giờ thành lời — nên tài xế nghe một câu hỏi không nêu
#: hệ thống đang phân vân giữa hai cái gì, và phải tự đoán ngược lại.
#:
#: Chỉ liệt kê những lý do mà tập lựa chọn là **đóng và ngắn** nên nêu thẳng ra
#: được. Lý do không có ở đây rơi về câu chung, đó là hành vi đúng chứ không phải
#: thiếu sót.
#:
#: ## Ba thành phần, và thành phần đầu là thành phần nguy hiểm nhất (issue #148)
#:
#: Bản trước chỉ nêu slot còn thiếu. Tài xế vừa nói *"chỉnh quạt gió mức 2 điều hòa"*,
#: nghe *"Bạn muốn đặt nhiệt độ bao nhiêu độ?"*, sẽ đinh ninh **quạt đã xong** và chỉ
#: còn thiếu nhiệt độ — trong khi thực tế là **0 lệnh**, quạt vẫn nguyên. Fail-closed mà
#: người dùng không nhận ra là đã fail-closed thì mất một nửa giá trị. Nên mỗi câu phải
#: nói đủ: **chưa làm gì** / **thiếu cái gì** / **đáp thế nào**.
#:
#: Ví dụ trong ngoặc kép là một mảnh trả lời **thật sự chạy được** sau khi ghép — có
#: test đối chiếu từng ví dụ với chính router (`test_clarify_messages.py`), nên câu chữ
#: ở đây không trôi khỏi hành vi được.
#:
#: Ba lý do đầu là phạm vi #148 đã chốt; `missing_door_side` là lý do thứ tư và nó tới
#: từ chỗ khác — hàng rào an toàn ở `_match_door` (review #301) tạo ra một `clarify`
#: chưa từng có, nên nó phải có lời ngay từ đầu chứ không xếp hàng chờ phần B.
#:
#: Router phát ra **mười** `missing_*`; sáu cái còn lại (`missing_volume`, hai cửa sổ,
#: ba ghế) cũng có tập lựa chọn đóng và ngắn y hệt, nhưng chúng đi cùng phần B (PR
#: riêng) — thêm ở đây là mở lại đúng chỗ phạm vi vừa được thu về. Sáu lý do ấy hiện
#: rơi về câu chung, y như trước #148.
CLARIFY_MESSAGES: dict[str, str] = {
    # Ba thành phần của một câu hỏi lại dùng được: **chưa làm gì** / **thiếu cái gì** /
    # **đáp thế nào**.
    #
    # Thành phần đầu trước đây thiếu hẳn, và nó quan trọng nhất. Đo buổi test 20/08:
    # tài xế nói *"chỉnh quạt gió mức 2 điều hòa"*, nghe *"Bạn muốn đặt nhiệt độ bao
    # nhiêu độ?"*, đinh ninh quạt đã xong — trong khi thực tế là **0 lệnh**. Fail-closed
    # mà người dùng không nhận ra là đã fail-closed thì mất một nửa giá trị.
    #
    # Thành phần hai chỉ nêu lựa chọn xe ĐỌC ĐƯỢC: `_side()` của router hiểu
    # `bên lái`/`bên phụ`, **không** hiểu `sau trái`. Mời một lựa chọn không tồn tại là
    # dựng đúng cái vòng lặp mà bảng này sinh ra để phá.
    #
    # Thành phần ba là **câu đầy đủ, có động từ** — không phải mảnh trả lời. Hôm nay
    # `"mức 2"` đứng một mình rơi xuống tra sổ tay (đo được), nên gợi ý mảnh là dạy
    # tài xế một câu vô dụng. Ghép mảnh vào ngữ cảnh lượt trước là việc của phần B
    # (#148, PR riêng); khi nó vào thì ví dụ ở đây rút ngắn lại được.
    "missing_light_target": 'Tôi chưa bật tắt đèn nào cả. Bạn muốn đèn pha hay đèn trần? Nói mỗi tên đèn cũng được, ví dụ "đèn trần".',
    "missing_fan_level": 'Tôi chưa chỉnh gì cả. Bạn muốn quạt gió mức mấy, từ 0 đến 3? Nói mỗi mức cũng được, ví dụ "mức 2".',
    "missing_temperature": 'Tôi chưa chỉnh gì cả. Bạn muốn điều hòa bao nhiêu độ, từ 16 đến 30? Nói mỗi số cũng được, ví dụ "24 độ".',
    # Lý do thứ tư, và nó **không** thuộc backlog phần B của #148 — nó sinh ra cùng
    # hàng rào an toàn ở `_match_door` (review #301). Câu chung đặc biệt tệ ở đúng chỗ
    # này: tài xế vừa nói "mở cửa bên trái", nghe "Bạn muốn điều chỉnh cụ thể như thế
    # nào?", và thứ họ thiếu — hàng ghế — là thứ duy nhất câu ấy không nêu.
    "missing_door_side": 'Tôi chưa mở hay đóng cửa nào cả. Bạn muốn cửa hàng trước hay hàng sau? Nói lại cả câu nhé, ví dụ "mở cửa sau bên trái".',
    # Không phải tập lựa chọn đóng, nhưng câu chung ở đây tạo vòng lặp: tài xế nói
    # "tăng thêm 10", nghe "bạn muốn điều chỉnh cụ thể như thế nào?", rồi nói lại y hệt.
    # Phải nêu rằng cần một con số **tuyệt đối** thì họ mới thoát ra được.
    "relative_change_unsupported": "Tôi chưa chỉnh gì cả. Xe chưa đọc được mức hiện tại nên chưa cộng trừ được, bạn cho mình con số cụ thể nhé.",
    # Tài xế rút lại lệnh mà chưa nói lại gì ("bật điều hòa, à thôi"). Câu này phải
    # nói rõ **chưa có gì xảy ra** — đó là thông tin duy nhất họ cần lúc ấy. Để lượt
    # rơi xuống sổ tay thì họ nhận một đoạn hướng dẫn cho đúng việc vừa huỷ.
    "tu_sua_loi_khong_con_lenh": "Vâng, tôi chưa thực hiện gì cả. Bạn cần gì thì nói lại giúp tôi nhé.",
    # Cùng họ với dòng trên, nhưng là nhánh fail-closed: có dấu rút lại, mà vế nói lại
    # không dựng nổi thành lệnh nào ("bật điều hòa à thôi cái kia"). Xem
    # `_tach_tu_sua_loi` — quay về khớp cả câu ở đây là thực thi đúng vế vừa bị huỷ.
    "tu_sua_loi_khong_doc_duoc": "Tôi chưa thực hiện gì cả vì chưa nghe rõ ý sau cùng. Bạn nói lại nguyên câu giúp tôi nhé.",
    # Sáu mục dưới đây là **điều kiện sống** của `ghep_hoi_lai.CO_THE_GHEP`, không phải
    # trang trí: mỗi lý do ở đó phải có một câu hỏi lại nêu **đúng dải giá trị**, vì
    # mảnh trả lời của lượt sau được ghép vào chính câu hỏi ấy. Chúng bị xoá ở `6bb2713`
    # khi #217 thu về phạm vi phần A, và đó là thứ làm phần B chết lặng trên `develop`
    # (issue #354). `test_ghep_hoi_lai.py` nay khoá quan hệ ấy lại.
    "missing_volume": 'Tôi chưa chỉnh gì cả. Bạn muốn âm lượng bao nhiêu, từ 0 đến 100? Nói mỗi số cũng được, ví dụ "50".',
    "missing_window_side": 'Tôi chưa mở cửa sổ nào cả. Bạn muốn bên lái hay bên phụ? Nói mỗi bên cũng được, ví dụ "bên lái".',
    "missing_window_position": 'Tôi chưa chỉnh cửa sổ. Bạn muốn mở bao nhiêu phần trăm, từ 0 đến 100? Nói mỗi số cũng được, ví dụ "30 phần trăm".',
    "missing_seat_side": 'Tôi chưa chỉnh ghế nào cả. Bạn muốn ghế bên lái hay bên phụ? Nói mỗi bên cũng được, ví dụ "bên lái".',
    "missing_seat_level": 'Tôi chưa bật sưởi ghế. Bạn muốn mức mấy, từ 0 đến 3? Nói mỗi mức cũng được, ví dụ "mức 2".',
    "missing_seat_value": 'Tôi chưa chỉnh ghế. Bạn muốn đặt bao nhiêu phần trăm, từ 0 đến 100? Nói mỗi số cũng được, ví dụ "50 phần trăm".',
}

#: Bản **nói** của câu hỏi lại: bỏ ví dụ, giữ hai thành phần đầu.
#:
#: Tài xế đang lái. Câu hiển thị dài hơn vì mắt đọc nhanh hơn tai gấp nhiều lần, và vì
#: ví dụ trong ngoặc kép chỉ có nghĩa khi **nhìn** thấy dấu ngoặc — đọc lên thì nó là
#: một mệnh đề thừa nối vào một câu hỏi đã trọn vẹn.
#:
#: Lý do không có ở đây dùng nguyên `CLARIFY_MESSAGES` — không có bản nói riêng không
#: phải là lỗi.
CLARIFY_SPEAK: dict[str, str] = {
    "missing_light_target": "Tôi chưa bật tắt đèn nào cả. Bạn muốn đèn pha hay đèn trần?",
    "missing_fan_level": "Tôi chưa chỉnh gì cả. Bạn muốn quạt gió mức mấy, từ 0 đến 3?",
    "missing_temperature": "Tôi chưa chỉnh gì cả. Bạn muốn điều hòa bao nhiêu độ, từ 16 đến 30?",
    "missing_door_side": "Tôi chưa mở hay đóng cửa nào cả. Bạn muốn cửa hàng trước hay hàng sau?",
    # Bản NÓI của sáu mục vừa khôi phục — bỏ phần ví dụ trong ngoặc kép, vì đọc ra
    # loa thì một ví dụ trong ngoặc nghe như máy đang lắp bắp.
    "missing_volume": "Tôi chưa chỉnh gì cả. Bạn muốn âm lượng bao nhiêu, từ 0 đến 100?",
    "missing_window_side": "Tôi chưa mở cửa sổ nào cả. Bạn muốn bên lái hay bên phụ?",
    "missing_window_position": "Tôi chưa chỉnh cửa sổ. Bạn muốn mở bao nhiêu phần trăm?",
    "missing_seat_side": "Tôi chưa chỉnh ghế nào cả. Bạn muốn ghế bên lái hay bên phụ?",
    "missing_seat_level": "Tôi chưa bật sưởi ghế. Bạn muốn mức mấy, từ 0 đến 3?",
    "missing_seat_value": "Tôi chưa chỉnh ghế. Bạn muốn đặt bao nhiêu phần trăm?",
}

# --- S3: nói VÌ SAO bị chặn, và KHI NÀO thì được (SP-3 mục 4) ------------------
#
# `OUTCOME_MESSAGES["blocked"]` — *"Lệnh bị chặn vì trạng thái xe hiện tại không cho
# phép."* — không nói được ba thứ tài xế cần: trạng thái **nào**, **khi nào** thì được,
# và **có cách khác không**. Với `"mở cửa"` lúc xe chạy 50 km/h thì cả ba đều có câu trả
# lời cụ thể, và chúng nằm sẵn trong `vehicle_snapshot` + `action_plan`.
#
# Không đổi quyết định an toàn nào: cùng những lệnh ấy vẫn bị chặn, executor vẫn không
# nhận gì. Chỉ đổi câu nói ra.

# **Không có bảng "đề nghị thay thế" ở đây, và đó là kết luận của một phép đo.**
#
# Bản đầu của PR #338 có một mục: `"mở cửa"` bị chặn thì đề nghị *"bạn muốn hạ kính cho
# thoáng thay không?"*. Lý lẽ nghe xuôi — `set_window_position` luôn S2 nên hạ kính làm
# được ngay cả lúc xe chạy. @thanhpro82 bác: đó là một lời **đề nghị hành động** mà chưa
# có đường thực hiện. Đo lại thì đúng, và tệ hơn mô tả:
#
#     lượt 1  "Mở cửa bên lái" @ 45 km/h  -> blocked, câu trên, cho_ghep_text = None
#     lượt 2  "Ừ, hạ kính đi"             -> grounded_refusal
#                                            "Tôi không tìm thấy thông tin này trong sổ tay xe."
#
# Tài xế nhận lời mời, **nói rõ cả hành động**, và nhận về một câu từ chối tra cứu. Đường
# ghép ngữ cảnh của #148 không cứu được: nó chỉ nhận các lý do `clarify` trong danh sách
# trắng `CO_THE_GHEP`, mà `blocked` không nằm trong đó — và nó không nằm trong đó vì
# `blocked` chưa bao giờ để lại một `offer` nào để ghép vào.
#
# Một đề nghị không có đường thực hiện tệ hơn im lặng: nó dạy tài xế rằng đề nghị của xe
# không đáng tin. Nên bỏ hẳn khỏi PR này; làm thật thì cần một flow riêng (hỏi bên kính,
# hỏi mức %, dựng plan S2, qua approval) — xem issue tách ra.

#: Vì sao S3, theo trạng thái đo được. Hai ca khác hẳn nhau và **không được nói nhầm**:
#: xe đang chạy, hay xe đứng yên nhưng chưa về P. Tài xế nhìn đồng hồ thấy 0 km/h rồi
#: nghe máy bảo "đang chạy" thì mất tin vào mọi câu sau đó.
def _ly_do_s3(snapshot: dict | None) -> tuple[str, str] | None:
    """`(vì sao, khi nào)`, hoặc `None` khi không đọc được trạng thái.

    Trả `None` chứ không đoán: một lời từ chối kèm số **sai** còn tệ hơn một lời từ chối
    chung chung — nó vừa vô ích vừa nghe đáng tin.

    Vế *"khi nào"* đi kèm vế *"vì sao"* chứ không phải một hằng số dùng chung, vì hai ca
    có điều kiện khác nhau. Bản đầu dùng một câu chung *"khi xe dừng hẳn và về số P"* và
    nó nói thừa với ca xe **đã** đứng yên: *"Xe chưa về số P… Khi xe dừng hẳn và về số P
    thì tôi làm ngay."* — xe đang dừng sẵn, câu ấy vừa lặp vừa sai trọng tâm.
    """
    motion = (snapshot or {}).get("motion")
    if not isinstance(motion, dict):
        # `snapshot` tới từ MQTT nên hình dạng của nó là dữ liệu ngoài, không phải hằng
        # số của ta. Bản trước dùng `or {}`, đúng cho `None` nhưng vẫn nổ `AttributeError`
        # nếu `motion` là một chuỗi hay danh sách. Ở một hàm mà cả lý do tồn tại là
        # fail-safe thì để lọt một đường nổ là tự mâu thuẫn.
        return None
    toc_do, so = motion.get("speed_kph"), motion.get("gear")
    if not isinstance(toc_do, int | float) or not isinstance(so, str):
        return None
    if toc_do > 0:
        # Bỏ `.0` cho số tròn: "50 km/h" nghe ra lời, "50.0 km/h" thì không.
        return (
            f"xe đang chạy {toc_do:g} km/h nên tôi chưa làm được",
            "Khi xe dừng hẳn và về số P thì tôi làm ngay.",
        )
    if so != "P":
        return (
            f"xe chưa về số P (đang ở số {so}) nên tôi chưa làm được",
            "Bạn về số P là tôi làm ngay.",
        )
    # Đứng yên và đã về P mà vẫn S3: `is_stationary` đúng, nên nguyên nhân nằm chỗ khác.
    # Đổ lỗi cho tốc độ hay số ở đây đều là bịa.
    return None


def _hoa_dau_cau(cau: str) -> str:
    """Viết hoa chữ đầu, **giữ nguyên phần còn lại**.

    Không dùng `str.capitalize()`: nó viết thường mọi ký tự sau chữ đầu, nên `"số P"`
    thành `"số p"` và `"đang ở số D"` thành `"đang ở số d"` — đúng hai ký hiệu mà cả câu
    tồn tại để nói ra. Test bắt được ca này.
    """
    return cau[:1].upper() + cau[1:] if cau else cau


def cau_bi_chan(plan, snapshot: dict | None) -> str:
    """Câu cho `outcome="blocked"`: vì sao + khi nào được + (nếu có) cách khác.

    Lui về `OUTCOME_MESSAGES["blocked"]` khi không dựng nổi một câu **đúng** — plan rỗng,
    không đọc được trạng thái, hoặc trạng thái không giải thích được việc bị chặn.

    Chỉ nói về bước bị chặn **đầu tiên**. Một câu thoại phải ngắn; liệt kê ba tool trong
    một câu là thứ không ai nghe hết, và bước đầu đã đủ để hiểu vì sao lượt dừng.
    """
    buoc = next((b for b in getattr(plan, "steps", ()) if b.safety_level == "S3"), None)
    if buoc is None:
        return OUTCOME_MESSAGES["blocked"]
    doc = _ly_do_s3(snapshot)
    if doc is None:
        return OUTCOME_MESSAGES["blocked"]
    ly_do, khi_nao = doc
    return f"{_hoa_dau_cau(ly_do)}. {khi_nao}"


#: Lời từ chối **theo lý do**, đè lên `OUTCOME_MESSAGES["denied"]` — cùng cơ chế và
#: cùng lý do tồn tại như `CLARIFY_MESSAGES` ngay trên.
#:
#: Câu chung — "Xin lỗi, tôi không thực hiện được yêu cầu này." — không nói vì sao
#: và không nêu lối ra, nên với `"tắt đèn pha"` tài xế chỉ thấy hệ thống hỏng chứ
#: không biết rằng (a) đây là quy định an toàn cố ý, và (b) có sẵn một cách đạt
#: đúng ý họ. Từ chối mà không chỉ đường là bỏ dở đúng nửa việc khó.
#:
#: Nêu luôn dải hợp lệ ở các lỗi ngoài dải: người dùng vừa nói một con số, thứ họ
#: cần biết là con số nào thì được, không phải "sai rồi".
DENIED_MESSAGES: dict[str, str] = {
    "headlight_off_not_permitted": (
        "Đèn pha không tắt thủ công được — xe có đèn chạy ban ngày nên đây là quy định an toàn. "
        'Bạn nói "chuyển đèn sang chế độ tự động" để xe tự bật tắt theo trời sáng tối nhé.'
    ),
    "fan_level_out_of_range": "Quạt gió chỉ đặt được từ mức 0 đến 3.",
    "temperature_out_of_range": "Điều hòa chỉ đặt được từ 16 đến 30 độ.",
    "volume_out_of_range": "Âm lượng chỉ đặt được từ 0 đến 100.",
    "window_position_out_of_range": "Cửa sổ chỉ mở được từ 0 đến 100 phần trăm.",
    "seat_level_out_of_range": "Sưởi ghế chỉ đặt được từ mức 0 đến 3.",
    "seat_value_out_of_range": "Vị trí ghế chỉ chỉnh được từ 0 đến 100 phần trăm.",
    "unsupported_actuator": "Xe mô phỏng này không điều khiển được bộ phận đó.",
}


def _cau_khong_co_bai() -> str:
    """Từ chối phát bài lạ — và kể ra playlist có gì.

    Câu từ chối không nêu được lựa chọn nào thì tài xế chỉ còn cách đoán tên bài kế
    tiếp. Danh sách đọc thẳng từ fixture nên không có bản sao thứ hai để lệch.
    """
    from src.fixtures import load_media_fixture

    ten = ", ".join(str(item["name"]) for item in load_media_fixture())
    return f"Playlist trên xe không có bài đó. Hiện có: {ten}."

#: Trần ký tự cho phần trích nguyên văn. 1.200 bao trọn 34/40 đoạn của
#: `eval/datasets/manual/v1` (min 199, p50 950, max 2.416); 6 đoạn còn lại bị cắt
#: **có báo**. Đổi số này là đổi hành vi người dùng thấy, không phải hằng số kỹ thuật.
QUOTE_MAX_CHARS = 1200

_SENTENCE_ENDS = (".", "!", "?", "\n")


def _quote_top_evidence(state: AgentState) -> str | None:
    """Nguyên văn đoạn sổ tay khớp nhất, hoặc None nếu không có gì để trích.

    Nguồn là `evidence[0].text` chứ **không** phải `citation.excerpt`: excerpt bị cắt
    ở `EXCERPT_CHARS = 300` (`src/rag/retrieve.py`) trong khi 39/40 đoạn thật dài hơn
    thế. Trích từ excerpt là tái tạo đúng lỗi mà cả thay đổi này sinh ra để tránh —
    điều kiện an toàn của sổ tay ("bản ECO 8 hướng / bản PLUS 12 hướng", "pin SDI 240
    KPA / CATL 260 KPA", "nếu được trang bị") nằm rải trong đoạn, cắt cụt là mất.

    Khi buộc phải cắt thì cắt ở ranh giới câu và **nói rõ là còn tiếp**: lỗi của
    phương án để SLM viết lại là bỏ sót *âm thầm* (xem run
    `eval/results/spike-003/20260811T200114.021276Z`), nên ở đây bỏ sót phải nhìn
    thấy được.
    """
    evidence = state.get("evidence") or []
    if not evidence:
        return None
    top = evidence[0]

    # Nhận cả `Evidence` lẫn dict: `rag_node` thật trả về object, nhưng node RAG là
    # tham số tiêm được (`build_graph(rag=...)`) và test sẵn có truyền dict. Chỉ đọc
    # thuộc tính thì gặp dict sẽ **lặng lẽ** rơi về câu cố định — mất nội dung mà
    # không ai thấy, đúng loại hỏng mà thay đổi này sinh ra để chống.
    def field(name: str, default=None):  # noqa: ANN001, ANN202
        return top.get(name, default) if isinstance(top, dict) else getattr(top, name, default)

    text = (field("text", "") or "").strip()
    if not text:
        return None
    if len(text) <= QUOTE_MAX_CHARS:
        return text

    head = text[:QUOTE_MAX_CHARS]
    cut = max(head.rfind(end) for end in _SENTENCE_ENDS)
    if cut > 0:
        head = head[: cut + 1]
    section = field("section", "") or "sổ tay"
    page = field("page")
    where = f"{section}, tr.{page}" if page is not None else section
    return f"{head.rstrip()}\n(Trích chưa hết — xem tiếp trong sổ tay, {where}.)"


#: Mô tả tiếng Việt cho từng tool, dùng khi nêu lời đề nghị. Phải nêu **đủ** tham số
#: người dùng sắp đồng ý — đề nghị mơ hồ thì lời đồng ý cũng vô nghĩa.
_SIDE_NAMES = {
    "front_left": "trước bên lái",
    "front_right": "trước bên phụ",
    "rear_left": "sau bên trái",
    "rear_right": "sau bên phải",
}


def _ten_poi(poi_id: str | None) -> str:
    """Id → tên đọc được. Id lạ thì trả lại chính nó: thà đọc một chuỗi kỳ quặc còn
    hơn ném lỗi giữa lúc đang soạn câu trả lời."""
    from src.fixtures import load_poi_fixture

    for item in load_poi_fixture():
        if str(item["id"]) == str(poi_id):
            return str(item["name"])
    return str(poi_id)


def _km(gia_tri: object) -> str:
    """Dấu phẩy thập phân — TTS đọc `3.6` thành "ba chấm sáu"."""
    return str(gia_tri).replace(".", ",")


def cau_ket_qua_tim_poi(items: list[dict[str, Any]]) -> str:
    """Câu cho nhánh SỐ NHIỀU, dựng từ **kết quả thực thi** (issue #371).

    Nhận danh sách chứ không nhận `category`, và đó là toàn bộ nội dung của bản vá.

    Bản trước nhận `category` rồi **tự tra fixture**. Một câu nói dựng từ phép tra song
    song thì nói được cả khi bước tương ứng chưa từng chạy — và nó đã nói: router sinh
    plan `search_nearby_poi`, plan chết ở `validate_args` với `tool_not_allowed`, lượt
    mang `outcome=validation_denied`, mà tài xế vẫn nghe *"Tôi tìm được 2 chỗ… Bạn muốn
    đi chỗ nào?"*. Xe đặt một câu hỏi cho một việc nó vừa không làm được.

    Nhận danh sách thì lớp lỗi ấy không dựng lên được: không có kết quả thì không có gì
    để đọc. Trần ba mục do executor cắt — xem `POI_TRAN_DOC`.
    """
    if not items:
        return "Tôi không tìm được chỗ nào quanh đây. Bạn thử hỏi loại địa điểm khác nhé."
    ds = ", ".join(f"{p['name']} cách {_km(p['distance_km'])} km" for p in items)
    return f"Tôi tìm được {len(items)} chỗ: {ds}. Bạn muốn đi chỗ nào?"


def _poi_da_tim_duoc(state: AgentState) -> list[dict[str, Any]] | None:
    """Danh sách địa điểm từ bước `search_nearby_poi` **đã chạy xong**, hoặc `None`.

    `None` nghĩa là bước ấy không chạy, hoặc chạy hỏng — hai ca đều không được đọc ra
    một danh sách. Người gọi rơi về câu lỗi chung của `outcome`, đúng như mọi lượt hỏng
    khác.
    """
    for ket_qua in state.get("step_results") or ():
        tool = ket_qua.tool if hasattr(ket_qua, "tool") else ket_qua.get("tool")
        status = ket_qua.status if hasattr(ket_qua, "status") else ket_qua.get("status")
        if tool != "search_nearby_poi" or status != "completed":
            continue
        after = ket_qua.after if hasattr(ket_qua, "after") else ket_qua.get("after")
        items = (after or {}).get("items")
        return list(items) if isinstance(items, list) else []
    return None


def cau_da_chi_duong(poi_id: str | None) -> str | None:
    """Câu cho nhánh SỐ ÍT. `None` = id không tra được, để người gọi dùng câu mặc định.

    Nhánh số ít đặt dẫn đường cho một câu *tìm* — làm nhiều hơn điều được yêu cầu.
    Điều kiện kèm theo của spec SP-5 §2.1: phải nói ra **đã làm gì** và cho **lối
    thoát** trong cùng một lượt. Tự ý làm mà không nói mới là chỗ nguy hiểm.
    """
    from src.fixtures import load_poi_fixture

    poi = next((p for p in load_poi_fixture() if str(p["id"]) == str(poi_id)), None)
    if poi is None:
        return None
    return (
        f"Chỗ gần nhất là {poi['name']}, cách {_km(poi['distance_km'])} km, "
        f"khoảng {poi['eta_min']} phút. Tôi đã chỉ đường tới đó. "
        "Muốn chỗ khác thì bảo tôi nhé."
    )


def describe_step(tool: str, args: dict[str, Any]) -> str:
    """Một câu tiếng Việt mô tả chính xác việc mà step này sẽ làm."""
    if tool == "set_hvac_power":
        return "bật điều hòa" if args.get("enabled") else "tắt điều hòa"
    if tool == "set_hvac_temperature":
        return f"đặt điều hòa ở {args['temperature_c']:g} độ"
    if tool == "set_hvac_fan_level":
        level = args["level"]
        return "tắt quạt gió" if level == 0 else f"đặt quạt gió ở mức {level}"
    if tool == "media_control":
        action = args.get("action")
        if action == "set_volume":
            return f"đặt âm lượng ở mức {args['volume']}"
        if action == "play_track":
            # In **tên** bài, không phải `track_id`: cùng lý do như POI (`_ten_poi`) —
            # "đã phát trk-01" không nói cho tài xế biết xe vừa làm gì.
            from src.fixtures import ten_track_theo_id

            ten = ten_track_theo_id(str(args.get("track_id", ""))) or str(args.get("track_id", ""))
            return f"phát bài {ten}"
        return {
            "play": "phát nhạc",
            "pause": "tạm dừng nhạc",
            "next": "chuyển bài tiếp theo",
            "previous": "quay lại bài trước",
        }.get(action, f"điều khiển nhạc ({action})")
    if tool == "set_window_position":
        side = _SIDE_NAMES.get(args.get("window", ""), args.get("window", ""))
        return f"đưa kính {side} về {args['percent']}%"
    if tool == "set_seat_heating":
        side = _SIDE_NAMES.get(args.get("seat", ""), args.get("seat", ""))
        level = args["level"]
        return f"tắt sưởi ghế {side}" if level == 0 else f"đặt sưởi ghế {side} ở mức {level}"
    if tool == "set_seat_position":
        side = _SIDE_NAMES.get(args.get("seat", ""), args.get("seat", ""))
        axis = {"recline": "độ ngả lưng", "fore_aft": "vị trí tiến/lùi", "height": "độ cao"}.get(
            args.get("axis", ""), args.get("axis", "")
        )
        return f"đặt {axis} ghế {side} ở {args['value']}%"
    if tool == "set_door_state":
        side = _SIDE_NAMES.get(args.get("door", ""), args.get("door", ""))
        return f"mở cửa {side}" if args.get("state") == "open" else f"đóng cửa {side}"
    if tool == "set_trunk_state":
        return "mở cốp sau" if args.get("state") == "open" else "đóng cốp sau"
    if tool == "set_headlight_mode":
        mode = {
            "auto": "chế độ tự động",
            "low_beam": "đèn chiếu gần",
            "high_beam": "đèn chiếu xa",
        }.get(args.get("mode", ""), args.get("mode", ""))
        return f"chuyển đèn sang {mode}"
    if tool == "open_app":
        ten = {"youtube": "YouTube", "tiktok": "TikTok", "spotify": "Spotify"}.get(
            args.get("app", ""), args.get("app", "")
        )
        return f"mở {ten}"
    if tool == "set_interior_light":
        return "bật đèn trần" if args.get("enabled") else "tắt đèn trần"
    if tool == "set_navigation":
        if args.get("operation") == "cancel":
            return "hủy dẫn đường"
        return f"dẫn đường tới {_ten_poi(args.get('destination_id'))}"
    if tool == "search_nearby_poi":
        return "tìm địa điểm quanh đây"
    return f"thực hiện {tool}"


def _compose_offer(state: AgentState) -> str:
    """Câu hỏi khớp một luật điều khiển — nêu việc sẽ làm rồi hỏi lại, không làm."""
    plan = state.get("candidate_action_plan")
    if plan is None or not plan.steps:
        return "Bạn có muốn tôi thực hiện không?"
    actions = " rồi ".join(describe_step(step.tool, step.args) for step in plan.steps)
    return f"Tôi có thể {actions}. Bạn có muốn tôi thực hiện không?"


async def compose_node(state: AgentState) -> dict:
    _KET_QUA_NEN.clear()
    outcome = state.get("outcome", "not_control")
    speak_text: str | None = None
    doc_do: dict = {}
    if state.get("intent") == "tire_pressure_query" and (ra := _tra_ap_suat_lop(state)) is not None:
        return ra
    if state.get("intent") == "manual_continue":
        return _doc_tiep_phan_du(state)
    if state.get("intent") == "manual_stop_reading":
        return _thoi_khong_doc_tiep(state)
    if state.get("intent") == "offer_declined":
        return {"response_text": TU_CHOI_DE_NGHI, "speak_text": TU_CHOI_DE_NGHI, "has_more_to_read": False}
    if state.get("intent") == "manh_khong_khop_mau":
        return _hoi_lai_vi_nghe_hut(state)
    if state.get("intent") == "giai_tan":
        return {"response_text": GIAI_TAN, "speak_text": GIAI_TAN, "has_more_to_read": False}
    if (ra_routine := _cau_routine(state)) is not None:
        return ra_routine
    if state.get("intent") == "poi_search" and (poi := _poi_da_tim_duoc(state)) is not None:
        # Nhánh SỐ NHIỀU: S0, chỉ đọc danh sách rồi hỏi lại — không đặt dẫn đường.
        #
        # Điều kiện `is not None` **là** bản vá của #371: rẽ theo `intent` một mình thì
        # lượt đã chết ở validate vẫn chạy vào đây. Giờ nó chỉ vào được khi bước tìm
        # kiếm đã chạy xong thật; ngoài ra rơi xuống câu lỗi chung như mọi lượt hỏng.
        message = cau_ket_qua_tim_poi(poi)
        # Nhớ đúng danh sách **vừa đọc ra** cho lượt sau (#355 mục 2b). Nạp ở đây chứ
        # không ở `route_node`: lúc node ấy chạy, bước tìm kiếm chưa thực thi nên chưa có
        # danh sách nào — chỉ có `category`, và nhớ `category` rồi tra lại là dựng lại
        # đúng lớp lỗi #371 vừa gỡ.
        doc_do["cho_chon_poi"] = list(poi)
        doc_do["cho_chon_poi_luc"] = time.monotonic()
    elif state.get("intent") == "navigation_start" and outcome == "completed":
        # Nhánh SỐ ÍT: nói rõ đã chỉ đường tới đâu + lối thoát (spec SP-5 §2.1).
        ke = state.get("action_plan")
        pid = ke.steps[0].args.get("destination_id") if ke and ke.steps else None
        message = cau_da_chi_duong(pid) or OUTCOME_MESSAGES.get(outcome, _FALLBACK)
    elif outcome == "chitchat":
        # Reply do model soạn, đã qua strip + trần độ dài ở parse_slm_output.
        message = state.get("chitchat_reply") or OUTCOME_MESSAGES["clarify"]
    elif outcome == "offer":
        message = _compose_offer(state)
    elif outcome == "blocked":
        # SP-3 mục 4: nói vì sao và khi nào được, thay cho "trạng thái xe hiện tại
        # không cho phép". Lui về câu cũ khi không dựng nổi một câu ĐÚNG — xem
        # `cau_bi_chan`.
        message = cau_bi_chan(state.get("action_plan"), state.get("vehicle_snapshot"))
    else:
        message = OUTCOME_MESSAGES.get(outcome, _FALLBACK)
        # `route_reason` là thứ duy nhất biết router đang thiếu slot nào; không đọc nó
        # ở đây thì mọi câu hỏi lại đều chung một câu. Xem `CLARIFY_MESSAGES`.
        if outcome == "clarify":
            ly_do = state.get("route_reason", "")
            message = CLARIFY_MESSAGES.get(ly_do, message)
            # Kênh nói ngắn hơn kênh nhìn ở đúng nhánh này: xem `CLARIFY_SPEAK`.
            speak_text = CLARIFY_SPEAK.get(ly_do)
        # Cùng lý do như trên, cho nhánh từ chối. Xem `DENIED_MESSAGES`.
        if outcome == "denied":
            if state.get("route_reason") == "media_track_unknown":
                message = _cau_khong_co_bai()
            else:
                message = DENIED_MESSAGES.get(state.get("route_reason", ""), message)
        # Nhánh sổ tay: câu dẫn cố định **cộng** nội dung nguyên văn. Trước đây chỉ có
        # câu dẫn, nội dung nằm trong `citation.excerpt` — tài xế nghe xong không biết
        # gì thêm. Quyết định ở issue #62 (phương án A).
        if outcome == "grounded_answer":
            if (ra := _tra_loi_thieu_trang_bi(state)) is not None:
                return ra
            quote = _quote_top_evidence(state)
            if quote:
                # Câu dẫn do SLM viết nếu có. Nó **không mang dữ kiện nào** — nội dung
                # là phần trích ngay dưới — nên thiếu nó chỉ kém tự nhiên, không mất
                # nội dung. Đó là điều ADR-015 (bản sửa) hứa với `slm_enabled=False`.
                # Ba nguồn, theo thứ tự: câu dẫn SLM đã qua cổng → mẫu ghép từ câu
                # hỏi → chuỗi cố định. Mẫu đứng giữa chứ không đứng cuối vì nó **nói
                # đúng chủ đề tài xế vừa hỏi**, còn chuỗi cố định thì không.
                lead_in = (
                    lam_sach_cau_dan(state.get("grounded_lead_in") or "")
                    or cau_dan_tu_cau_hoi(state.get("query", ""))
                    or message
                )
                message = f"{lead_in}\n\n{quote}"
                # Trừ ngân sách câu dẫn ra khỏi trần: trần là của **chuỗi cuối cùng**
                # đưa vào TTS, không phải của riêng phần chọn. Không trừ thì câu dẫn
                # đẩy tổng vượt `MAX_SPEECH_CHARS` và lưới cuối ở `ivi_events` phải cắt
                # — tức composer đã sai và chỉ được cứu ở phút chót.
                ngan_sach = max(60, MAX_SPOKEN_CHARS - len(lead_in) - 1)
                # `to_thread` CHỈ khi thật sự có thác (issue #356). Không có thác thì
                # `chon_cau_de_noi` đi đường luật S1 — vài phép regex, gần như miễn phí —
                # và đó là đường DUY NHẤT đang chạy trên mọi checkout lẫn trên VPS
                # (`chon_cau_thac_enabled` mặc định False, trọng số 2,2 GB nằm ngoài git).
                # Bọc vô điều kiện là bắt đường ấy trả một lần nhảy thread cho một việc
                # không tốn gì; không đổi gì thì không thể làm hỏng gì.
                #
                # Có thác thì phải bọc: cross-encoder bge chấm lại từng câu tốn p50 523 ms
                # / p95 983 ms mỗi câu sổ tay (đo 18/08, xem `src/config.py:118-122`), gấp
                # 3-5 lần chặng RAG đo được trên VPS. Chạy thẳng trên event loop nghĩa là
                # trong ngần ấy thời gian KHÔNG phiên nào được đẩy sự kiện WS — vạch sóng
                # của người khác đứng hình, `assistant.status` không tới, request của
                # người thứ ba nằm chờ trong socket.
                #
                # An toàn thread: `select()` chỉ ĐỌC (cross-encoder forward), không sửa
                # state dùng chung — cùng lý lẽ `retriever.search`. Khác `voice.py`, nơi
                # sherpa-onnx và piper không bảo đảm an toàn nên phải có `threading.Lock`.
                thac = _thac_chon_cau()
                goi_chon_cau = partial(
                    chon_cau_de_noi,
                    (state.get("evidence") or [None])[0],
                    state.get("query", ""),
                    max_chars=ngan_sach,
                    selector=thac,
                )
                ke_hoach_noi = await asyncio.to_thread(goi_chon_cau) if thac is not None else goi_chon_cau()
                # Lời mời nghe tiếp (S3) chỉ gắn khi còn phần dư — `cau_noi_hoan_chinh`
                # tự quyết. Ngân sách truyền vào cũng đã trừ câu dẫn, nên lời mời không
                # đẩy tổng vượt trần.
                # Nén TRƯỚC khi ghép lời mời, không phải sau.
                #
                # Nén sau thì `tom()` nhận vào cả câu "Bạn có muốn nghe tiếp nguyên văn không?"
                # và được phép xoá bớt nó — mà cổng dãy-con vẫn cho qua, vì bản nén ĐÚNG là dãy
                # con của thứ nó nhận. Kết quả đo được: "...tiên tiến và Bạn có muốn nghe tiếp".
                # Cổng không sai; đầu vào sai. Lời mời là chữ của ta, không phải chữ sổ tay, nên
                # nó không được đi qua tầng nén.
                ke_hoach_noi = _nen_ke_hoach(ke_hoach_noi)
                phan_noi = cau_noi_hoan_chinh(ke_hoach_noi, max_chars=ngan_sach)
                # Kênh NÓI tách khỏi kênh HIỂN THỊ.
                #
                # Đo 13/08 sau khi cài Piper: đọc nguyên đoạn trích ra **65,6 giây**
                # audio và một `assistant.speech` **4,60 MB** — vượt trần khung 1 MiB
                # mặc định của nhiều client, và chiếm chỗ trong ring buffer 200 event
                # của ADR-014. Không tài xế nào nghe hết 65 giây sổ tay khi đang lái.
                #
                # `api_spec.md:571` khai sẵn cả `display_text` lẫn `speak_text`; bản
                # trước gộp làm một nên hợp đồng có mà không ai dùng.
                #
                # Task 3: `speech_policy` chọn câu để đọc — luôn là câu có sẵn trong
                # đoạn, và với đoạn có điều kiện theo phiên bản thì **không đọc số**.
                # Câu dẫn đứng trước để tài xế biết nguồn là sổ tay.
                speak_text = f"{lead_in} {phan_noi}".strip() if phan_noi else lead_in
                # S3: ghi lại chỗ đang đọc dở để lượt sau tiếp được. Lưu **nguồn +
                # offset**, không lưu phần dư đã cắt sẵn — phần dư sẽ lệch khỏi nguồn
                # ngay khi trần đổi, còn offset thì luôn giải nghĩa được ngược lại.
                doc_do = _moc_doc_do(state, ke_hoach_noi.chi_so)
    # Compose báo **trung thực cả hai kênh**; nó không tự ép chúng bằng nhau.
    #
    # Bản đầu của PR #221 ép ngay tại đây, và đó là chỗ sai: nó xoá luôn vế thứ ba của
    # câu hỏi lại — `"Nói mỗi mức cũng được, ví dụ \"mức 2\"."` — vốn **cố ý chỉ dành
    # cho màn hình** (ví dụ trong ngoặc kép chỉ có nghĩa khi nhìn thấy dấu ngoặc, xem
    # `CLARIFY_SPEAK`). Vế ấy là một trong ba thành phần mà #148 xác định là cần thiết,
    # và #354 đã khoá bằng test.
    #
    # Bất biến "màn hình là phụ đề" vẫn được giữ, nhưng ở **một chỗ duy nhất** —
    # `assistant_response_payload` — đúng như chính #221 lập luận. Nơi ấy áp một trần:
    # bản nhìn được giữ khi nó vẫn ngắn như một phụ đề, dài hơn thế thì màn hình nhận
    # đúng bản đã nói. Nhờ thế đoạn sổ tay 1.200 ký tự không lên màn hình nữa (thứ nhóm
    # 21/08 phàn nàn), còn câu ví dụ 38 ký tự thì còn.
    noi = speak_text if speak_text is not None else message
    return {
        "response_text": message,
        "response": message,
        "display_text": message,
        "speak_text": noi,
        # Nut "nghe tiep" phai xuat hien ngay tu luot dau, khong doi toi luot thu hai.
        "has_more_to_read": bool(doc_do.get("speech_source_text")),
        # Enum do server sinh, không phải văn bản — nên nó qua được kỷ luật redaction
        # của `record_graph_result`. Đây là thứ duy nhất cho biết câu tài xế vừa nghe
        # là nguyên văn sổ tay hay bản nén, và không có nó thì mọi buổi thử tay đều
        # phải đoán.
        "tom_tat_ket_qua": _KET_QUA_NEN[-1] if _KET_QUA_NEN else "khong_goi",
        **doc_do,
    }


#: Đáp lại "thôi". Ngắn, và **có nhắc đường quay lại** — tài xế từ chối lúc đang bận
#: không có nghĩa họ không cần đoạn ấy nữa ở đèn đỏ kế tiếp.
_THOI_DOC = "Vâng, tôi dừng ở đây. Cần nghe tiếp thì bạn nói “đọc tiếp” nhé."


def _thoi_khong_doc_tiep(state: AgentState) -> dict:
    """Tài xế từ chối lời mời nghe tiếp.

    **Giữ nguyên** chỗ đọc dở, không dọn. "Thôi" là *chưa phải bây giờ*, không phải *bỏ
    hẳn*; dọn ở đây thì câu "đọc tiếp" ba mươi giây sau nhận lại "tôi đã đọc hết phần
    này rồi" — một câu sai sự thật, và đúng lớp bug đã gặp ngày 15/08 ở nhánh biến thể.

    Không trả khoá `speech_*` nào cả: trong ngữ nghĩa merge của LangGraph, khoá vắng mặt
    là giữ nguyên còn khoá rỗng là xoá (xem `_moc_doc_do`).
    """
    return {
        "outcome": "grounded_continue",
        "response_text": _THOI_DOC,
        "response": _THOI_DOC,
        "display_text": _THOI_DOC,
        "speak_text": _THOI_DOC,
        "citations": list(state.get("speech_citations") or []),
        # Vẫn còn phần dư để nghe — nút "đọc tiếp" trên IVI không được biến mất chỉ vì
        # tài xế vừa nói "thôi" một lần.
        "has_more_to_read": True,
    }


def _tra_ap_suat_lop(state: AgentState) -> dict | None:
    """Trả lời áp suất lốp từ **bảng curate**, hoặc `None` để rơi về câu sổ tay.

    ## Vì sao cần nhánh này

    Sổ tay VF9 **không chứa** con số áp suất lốp — nó chỉ sang cái nhãn ở khung cửa
    (`"Xem > Vành và bánh xe > Áp suất lốp"`). Trích nguyên văn đoạn ấy nên sinh ra
    đúng câu breadcrumb mà người dùng nghe ngày 17/08: an toàn, và vô dụng.

    Con số thật nằm ở `src/safety/ap_suat_lop.py` — bảng curate có provenance, dựng ở
    #124. Bảng ấy **đã có, có test, nhưng trước thay đổi này không một dòng code chạy
    nào gọi tới**: nó chỉ được import bởi test.

    ## Vì sao trả `None` thay vì tự nói một câu

    `None` nghĩa là "tôi không trả lời được ca này" và composer đi tiếp xuống nhánh sổ
    tay bình thường — tức tài xế vẫn nghe *"ghi trên nhãn ở khung cửa"*, một câu tạm
    dùng được. Nếu ở đây tự phát một câu kiểu "chưa khai báo cấu hình" thì ta đổi một
    câu trả lời tạm được lấy một ngõ cụt, và đẩy lỗi cấu hình của kỹ sư sang cho tài xế.

    ## Fail-closed nằm ở đâu

    `is_complete` đòi **đủ cả** `trim` và `battery`. Không đủ thì không tra bảng — vì
    trong sổ tay không có "giá trị chung" nào cả, và đọc số của một bản xe khác nguy
    hiểm hơn không đọc gì (#122).
    """
    from src.safety.ap_suat_lop import tra_ap_suat, tra_lop_du_phong
    from src.services.vehicle_profile import get_vehicle_options, get_vehicle_profile

    truc = (state.get("route_reason") or "").removeprefix("tire_pressure_")

    # Lốp dự phòng có **một** giá trị áp suất, không phụ thuộc `trim`/`battery` — nhưng
    # nó phụ thuộc việc chiếc xe NÀY có lốp dự phòng hay không. Bản #124 trả 420 kPa cho
    # mọi xe; trên bản dùng bộ bơm hơi thì đó là số của một bánh không tồn tại.
    #
    # Chỉ chặn khi hồ sơ khai **rõ là không có**. Chưa khai thì vẫn trả số như cũ: đây
    # là tính năng mới, và làm hồi quy một câu đang đúng với phần lớn xe là cái giá quá
    # đắt cho một trường chưa ai điền.
    #
    # `o_bang=[]` là cố ý, dù nó làm `grounded_rate` hụt một lượt (xem docstring
    # `_goi_dap_ap_suat`). Câu này không đến từ ô bảng nào — nó đến từ hồ sơ xe — và
    # bịa một citation để đỡ cho KPI là đúng thứ mà chính docstring ấy phản đối.
    if truc == "spare":
        if get_vehicle_options(state.get("vehicle_id", "")).get("lop_du_phong") is False:
            return _goi_dap_ap_suat(
                "Xe của bạn không có lốp dự phòng mà dùng bộ bơm hơi, nên không có áp suất lốp dự phòng.",
                state,
                [],
            )
        o = tra_lop_du_phong()
        cau = f"Lốp dự phòng bơm {o.kpa} kPa, tức {o.psi} PSI, đo khi lốp nguội."
        return _goi_dap_ap_suat(cau, state, [o])

    ho_so = get_vehicle_profile(state.get("vehicle_id", ""))
    if not ho_so.is_complete:
        return None

    try:
        if truc == "front":
            o = tra_ap_suat(ho_so.trim, ho_so.battery, "front")
            cau = f"Áp suất lốp trục trước là {o.kpa} kPa, tức {o.psi} PSI, đo khi lốp nguội."
        elif truc == "rear":
            o = tra_ap_suat(ho_so.trim, ho_so.battery, "rear")
            cau = f"Áp suất lốp trục sau là {o.kpa} kPa, tức {o.psi} PSI, đo khi lốp nguội."
        else:
            truoc = tra_ap_suat(ho_so.trim, ho_so.battery, "front")
            sau = tra_ap_suat(ho_so.trim, ho_so.battery, "rear")
            cau = (
                f"Lốp trục trước bơm {truoc.kpa} kPa, tức {truoc.psi} PSI; "
                f"trục sau {sau.kpa} kPa, tức {sau.psi} PSI. Đo khi lốp nguội."
            )
        o_dung = [truoc, sau] if truc not in ("front", "rear") else [o]
    except ValueError:
        # Cấu hình lạ lọt qua được tầng validate là lỗi lập trình, nhưng nó **không**
        # được làm hỏng một lượt nói. Rơi về sổ tay.
        logging.getLogger(__name__).warning(
            "cấu hình xe không tra được bảng áp suất lốp: %s/%s", ho_so.trim, ho_so.battery
        )
        return None

    return _goi_dap_ap_suat(cau, state, o_dung)


#: Kết quả của lần nén gần nhất **trong cùng một lời gọi `compose_node`**, để nhét vào
#: trace. Không phải trạng thái toàn cục có ý nghĩa: `compose_node` xoá nó ở đầu mỗi
#: lượt và đọc ngay sau khi nén xong, nên không có khoảng nào để hai lượt giẫm nhau.
#:
#: Vì sao không trả kèm giá trị: `_nen_neu_bat` được gọi từ trong `_nen_ke_hoach`, mà
#: hàm ấy phải trả về một `SpeechPlan` để `cau_noi_hoan_chinh` dùng tiếp. Luồn thêm một
#: giá trị thứ hai qua hai tầng chỉ để ghi log là làm hỏng chữ ký của cả hai hàm.
_KET_QUA_NEN: list[str] = []


@lru_cache(maxsize=1)
def _tom_tat_client():
    """Client nén, dựng một lần. `None` khi cờ tắt — và đó là mặc định.

    `lru_cache` chứ không phải biến module: settings đọc được lúc gọi đầu tiên chứ
    không phải lúc import, nên test đổi biến môi trường rồi `cache_clear()` là đủ,
    không phải dựng lại cả module.
    """
    from src.config import get_settings

    st = get_settings()
    if not getattr(st, "tom_tat_enabled", False):
        return None
    from src.agents.tom_tat import QwenTomTat

    return QwenTomTat(st.tom_tat_endpoint, timeout_s=30.0)


def _nen_ke_hoach(ke_hoach, cau_hoi: str = ""):
    # `cau_hoi` để trống là CỐ Ý, không phải quên nối dây. Lưới 2×2 đo 20/08 cho thấy
    # đưa câu hỏi vào lật model từ vai **biên tập** sang vai **trả lời**, mà câu trả lời
    # cần từ nối nên nó chèn `và` — chèn `và` là nguồn của mọi ca sai đã chấm tay
    # (v1: 30% số ca nhận có chèn, v6: 58%, bản không câu hỏi: 5%).
    #
    # Tham số vẫn giữ vì `QwenTomTat.tom()` nhận nó và bàn cân dùng để đo lại kết luận
    # ấy khi đổi model. Xem nhật ký phiên bản prompt ở `src/agents/tom_tat.py`.
    """Trả kế hoạch nói với `spoken` đã nén, hoặc chính nó nếu không nén được.

    Giữ nguyên `chi_so` và `remainder_chars`: nén đổi CÁCH DIỄN ĐẠT của phần đã chọn,
    không đổi việc **câu nào** đã đọc. Cập nhật `chi_so` theo bản nén sẽ làm hỏng
    "đọc tiếp" — mốc đọc dở trỏ vào câu của nguồn, không phải vào chữ của bản nén.
    """
    import dataclasses

    # `chi_so` rỗng = chuỗi này KHÔNG tới từ sổ tay, mà do ta tự viết —
    # `_VARIANT_FALLBACK` và họ hàng của nó. `speech_policy` đã duy trì sẵn bất biến ấy
    # (xem chú thích ở nhánh `variant_fallback`), nên không cần dò chuỗi để đoán.
    #
    # Bắt buộc phải chặn: hợp đồng của tầng nén là "dãy con của ĐOẠN SỔ TAY". Đưa chữ
    # của ta vào thì cổng vẫn xanh — bản nén đúng là dãy con của thứ nó nhận — nhưng
    # thứ nó nhận không phải sổ tay. Đo 19/08 trên backend thật:
    #
    #     gốc  "...thay đổi theo phiên bản xe NÊN tôi không tóm tắt được an toàn."
    #     nén  "...thay đổi theo phiên bản xe VÀ  tôi không tóm tắt được an toàn."
    #
    # tức model vừa sửa lời một câu cảnh báo an toàn. Cùng lớp lỗi với việc nén cả lời
    # mời "nghe tiếp nguyên văn", và cùng một cách chữa: chỉ nén chữ của sổ tay.
    if not ke_hoach.chi_so:
        return ke_hoach
    moi = _nen_neu_bat(ke_hoach.spoken, cau_hoi)
    return ke_hoach if moi == ke_hoach.spoken else dataclasses.replace(ke_hoach, spoken=moi)


def _nen_neu_bat(phan_noi: str, cau_hoi: str = "") -> str:
    """Nén câu trả lời sổ tay nếu cờ bật và bản nén qua được mọi cổng.

    Mọi đường thất bại đều trả **nguyên văn**: cờ tắt, llama-server không có, model
    vi phạm hợp đồng dãy-con, hết giờ. Đó là tính chất khiến tầng này an toàn để bật
    — ca xấu nhất của nó bằng ca bình thường của tầng cũ, chứ không phải một câu hỏng.

    `tom()` đã tự nuốt mọi exception và trả `(None, "goi_hong")`, nên ở đây không cần
    `try` thứ hai; thêm vào chỉ che mất lỗi lập trình thật.
    """
    client = _tom_tat_client()
    if client is None or not phan_noi:
        _KET_QUA_NEN.append("tat" if client is None else "khong_goi")
        return phan_noi
    tom, cong = client.tom(phan_noi, cau_hoi or None)
    if tom:
        # Dấu kết câu là việc của tầng NÓI, không phải tầng nén. `sua_ngoac_lung` cố ý
        # thuần xoá nên bản nén có thể về không có dấu chấm, mà lời mời "nghe tiếp" sẽ
        # dán ngay sau nó. `_cham_dut` đã tồn tại cho đúng lý do ấy ở nhánh cắt mệnh đề.
        tom = _cham_dut(tom)
    log = logging.getLogger(__name__)
    if tom:
        _KET_QUA_NEN.append("nen")
        # Ghi cả ca THÀNH CÔNG, không chỉ ca bị bác. Bản trước chỉ log lúc bác, nên
        # người thử tay không có cách nào phân biệt "đã nén" với "tầng nén không chạy"
        # — hai thứ cho ra hai câu khác hẳn nhau mà nhìn từ ngoài giống hệt.
        log.info("đã nén: %d ký tự -> %d", len(phan_noi), len(tom))
        return tom
    _KET_QUA_NEN.append(f"bac:{cong or '?'}")
    log.info("bản nén bị bác ở cổng %s — đọc nguyên văn", cong or "?")
    return phan_noi


def _tra_loi_thieu_trang_bi(state: AgentState) -> dict | None:
    """Nói thẳng "xe bạn không có cái đó" thay vì đọc hướng dẫn cho phần cứng vắng mặt.

    ## Ca này hỏng ra sao khi không có hàm này

    116 trên 482 chunk của sổ tay gắn một mệnh đề điều kiện trang bị. Composer trích
    nguyên văn, nên tài xế nghe lại đúng chữ *"nếu được trang bị"*. Phần lớn ca thì đó
    chỉ là dài dòng. Ba ca thì không, và cả ba đều là ca người ta hỏi lúc đang cần:

    - *"Kéo cần gạt mở cửa khẩn cấp bên cạnh khoang chứa đồ ở cửa"* — quy trình thoát
      hiểm khi mất điện, trên chiếc xe không có cần gạt ấy ở hàng sau.
    - *"Lốp dự phòng nằm trong khoang chứa đồ phía sau"* — xe dùng bộ bơm hơi, và tài
      xế đang đứng bên đường.
    - *"Xe được trang bị phanh khẩn cấp tự động"* — hứa một lớp bảo vệ không tồn tại.

    ## Điều kiện kích hoạt hẹp, và cố ý hẹp

    Chỉ trả lời khi **mọi** trang bị nhận ra được trong đoạn đều đã được khai là KHÔNG
    CÓ. Nghĩa là cả đoạn nói về thứ chiếc xe này không có, nên không còn gì đáng đọc.

    Đoạn pha — có mệnh đề điều kiện về một trang bị vắng, nhưng cũng nói cả những thứ
    khác — thì **để nguyên**. Hai lý do, và lý do thứ hai mới là lý do thật:

    1. Cắt một đoạn pha là cắt luôn phần tài xế cần.
    2. Chèn thêm một câu *"xe bạn không có X"* rồi vẫn đọc tiếp thì tốn ngân sách ký
       tự trên **mọi** lượt như thế, mà trần nói là tài nguyên khan nhất của tầng này
       — đo 18/08 cho thấy nới câu dẫn thêm 14 ký tự đã đổi được 5 điểm chính xác.
       Nên mặc định là không động vào, và ca pha để dành cho một vòng có số đo riêng.

    "Chưa khai báo" không kích hoạt gì cả. Đó là trạng thái mặc định của mọi chiếc xe
    và sẽ mãi là trạng thái của phần lớn trường; coi nó như "không có" thì tính năng
    này nói sai về gần như mọi chiếc xe, ngay hôm bật lên.
    """
    from src.safety.trang_bi import nhan_dien, tra
    from src.services.vehicle_profile import get_vehicle_options

    bang_chung = (state.get("evidence") or [None])[0]
    doan = (bang_chung or {}).get("text") if isinstance(bang_chung, dict) else getattr(bang_chung, "text", None)
    if not doan:
        return None

    ma = nhan_dien(doan)
    if not ma:
        return None

    da_khai = get_vehicle_options(state.get("vehicle_id", ""))
    # `is False`, không phải `not`: `.get()` trả `None` cho chưa khai báo, và `not None`
    # cũng đúng — đúng cái nhầm biến "chưa biết" thành "không có" trên toàn bộ đội xe.
    if not all(da_khai.get(x) is False for x in ma):
        return None

    ten = [t.ten for x in ma if (t := tra(x))]
    if not ten:
        return None
    cau = f"Xe của bạn không được trang bị {_liet_ke(ten)}, nên phần này của sổ tay không áp dụng."
    return {
        "outcome": "grounded_answer",
        "response_text": cau,
        "response": cau,
        "display_text": cau,
        "speak_text": cau,
        # Không citation: câu này không đến từ sổ tay mà đến từ hồ sơ xe. Xem chú thích
        # cùng nội dung ở nhánh lốp dự phòng của `_tra_ap_suat_lop`.
        "citations": [],
        "has_more_to_read": False,
    }


def _cau_routine(state: AgentState) -> dict | None:
    """Câu cho bảy lối ra Routine, hoặc `None` để đi tiếp đường thường.

    Trả nguyên một `dict` chứ không chỉ một chuỗi, vì `has_more_to_read=False` phải đi
    cùng: không lối ra nào trong bảy cái này còn phần dư để "đọc tiếp".

    Cái thứ bảy — `routine_huy_xem_truoc` — thêm ở review PR #401: tài xế từ chối một
    preview, khác `routine_da_huy` (hủy một lần chạy ĐANG SỐNG) vì ở đây chưa có gì chạy.
    """
    outcome = state.get("outcome")
    ung_vien = [str(t) for t in (state.get("routine_ung_vien") or [])]
    if outcome == "routine_da_chay":
        cau = ROUTINE_DA_CHAY
    elif outcome == "routine_da_huy":
        cau = ROUTINE_DA_HUY
    elif outcome == "routine_khong_co_lan_chay":
        cau = ROUTINE_KHONG_CO_LAN_CHAY
    elif outcome == "routine_preview":
        preview = state.get("routine_preview") or {}
        ten = str(preview.get("routine_name") or "").strip()
        cau = f"Đây là các bước của chuỗi lệnh {ten}. Bạn có muốn tôi chạy không?" if ten else ROUTINE_XEM_TRUOC
    elif outcome == "routine_huy_xem_truoc":
        cau = ROUTINE_HUY_XEM_TRUOC
    elif outcome == "routine_khong_thay":
        # Nêu cái CÓ thay vì chỉ báo không thấy: tài xế đang lái, không tra được danh
        # sách bằng mắt. Vế "chưa chạy gì cả" là bắt buộc — thiếu nó thì một câu nêu tên
        # nghe rất giống một câu xác nhận.
        cau = (
            f"Tôi chưa chạy gì cả. Bạn có các chuỗi lệnh: {_liet_ke(ung_vien)}."
            if ung_vien
            else "Tôi chưa chạy gì cả. Bạn chưa có chuỗi lệnh nào."
        )
    elif outcome == "routine_tu_choi":
        # Câu do `bat_dau` soạn, viết hoa chữ đầu. Không viết lại ở đây: một bản sao sẽ
        # lệch ngay khi bên kia thêm lý do thứ năm.
        ly_do = str(state.get("routine_ly_do") or "").strip()
        cau = (ly_do[0].upper() + ly_do[1:] + ".") if ly_do else "Chưa chạy được chuỗi lệnh này."
    elif outcome == "routine_loi_ngu_canh":
        cau = ROUTINE_LOI_NGU_CANH
    elif outcome == "routine_mo_ho":
        cau = f"Tôi chưa chạy gì cả. Bạn muốn {_liet_ke(ung_vien)}?"
    else:
        return None
    return {"response_text": cau, "speak_text": cau, "has_more_to_read": False}


def _liet_ke(ten: list[str]) -> str:
    """`["A", "B", "C"]` -> `"A, B và C"`. Đọc lên nghe được, khác dấu phẩy khô."""
    thap = [t[0].lower() + t[1:] if t else t for t in ten]
    if len(thap) == 1:
        return thap[0]
    return ", ".join(thap[:-1]) + " và " + thap[-1]


def _goi_dap_ap_suat(cau: str, state: AgentState, o_bang: list) -> dict:
    """Cùng một câu cho cả loa lẫn màn hình, **kèm citation**.

    Khác nhánh sổ tay ở chỗ đây không trích nguyên văn: câu do ta viết từ một bảng đã
    curate, nên không có "phần còn lại" để mời nghe tiếp.

    Nhưng nó **vẫn phải chỉ được nguồn**, và bản đầu trả `citations: []` là sai hai
    đường — @thanhpro82 bắt ở review #168:

    1. `R-1`/`R-3` của `mvp-demo-checklist.md` đòi câu trả lời sổ tay kèm mục và số
       trang. `R-5` là câu **duy nhất đọc một con số an toàn** cho tài xế, và lại là câu
       duy nhất không chỉ được nguồn.
    2. `src/services/metrics.py` cộng `answered` cho `grounded_answer` nhưng chỉ cộng
       `grounded` khi `citation_count > 0`. Nên mỗi lượt hỏi áp suất lốp làm
       **`grounded_rate` giảm đúng lúc tính năng chạy đúng** — KPI đi ngược giá trị.

    Provenance có sẵn: mỗi ô `ApSuat` mang `chunk_id` và `page` của đoạn sổ tay sinh ra
    nó, và `nguyen_van` là chuỗi gốc trong bảng. Dựng citation từ đó, không bịa gì.
    """
    from src.rag.models import Citation

    turn_id = state.get("turn_id", "")
    citations = [
        Citation(
            citation_id=f"cit_{uuid.uuid4().hex[:12]}",
            turn_id=turn_id,
            document_title=state.get("document_title") or "Sổ tay VinFast VF9",
            section="Bảo dưỡng / Vành và bánh xe",
            page=o.page,
            chunk_id=o.chunk_id,
            # Nguyên văn ô bảng, ví dụ "260 KPA,38 PSI, (CATL)". Người rà lại đối chiếu
            # được với sổ tay mà không cần dựng index.
            excerpt=o.nguyen_van,
            retrieval_score=1.0,
        )
        for o in o_bang
    ]
    return {
        "outcome": "grounded_answer",
        "response_text": cau,
        "response": cau,
        "display_text": cau,
        "speak_text": cau,
        "citations": citations,
        "has_more_to_read": False,
    }


def _doc_tiep_phan_du(state: AgentState) -> dict:
    """Lượt "đọc tiếp" — đọc nốt đoạn của lượt trước, **không** tra sổ tay lại.

    Tra lại là đúng lỗi đang sửa: truy hồi bằng chính chữ "đọc tiếp" sẽ ra một đoạn
    khác hẳn, và tài xế nghe một câu trả lời không liên quan đến câu mình vừa hỏi.

    Đọc hết thì dọn trạng thái về rỗng (không phải vắng mặt): vắng mặt là *giữ nguyên*
    trong ngữ nghĩa merge của LangGraph, nên lượt sau sẽ đọc lại từ chính chỗ đã hết.
    """
    da_doc = tuple(state.get("speech_da_doc") or ())
    ke_hoach = doc_tiep(state.get("speech_source_text") or "", da_doc)
    if not ke_hoach.spoken:
        het = cau_noi_het_phan_du()
        return {
            "outcome": "grounded_continue",
            "response_text": het,
            "response": het,
            "display_text": het,
            "speak_text": het,
            "citations": list(state.get("speech_citations") or []),
            "has_more_to_read": False,
            "speech_source_text": "",
            "speech_da_doc": [],
            "speech_citations": [],
        }
    noi = cau_noi_hoan_chinh(ke_hoach)
    nguon = state.get("speech_source_text") or ""
    # Hợp nhất chỉ số đã đọc — call site không tự tính lại, `doc_tiep` đã nói câu nào.
    moi = sorted(set(da_doc) | set(ke_hoach.chi_so))
    moc = _moc_hoac_don(nguon, moi)
    con_du = bool(moc["speech_source_text"])
    # Trước 21/08 màn hình nhận `ke_hoach.spoken` kèm một dấu `(còn tiếp — …)` riêng,
    # vì lời mời "Bạn có muốn nghe tiếp nguyên văn không?" chỉ nằm ở kênh nói. Nay hai
    # kênh dùng chung một chuỗi nên lời mời **tự nó** là tín hiệu ấy, và dấu ngoặc kia
    # thành bản sao thứ hai của cùng một thông tin — đúng loại trôi lệch mà việc hợp
    # nhất này sinh ra để dọn. Nút "nghe tiếp" của FE bám `has_more_to_read`, không bám
    # chuỗi, nên bỏ dấu ngoặc không làm mất nút.
    return {
        "outcome": "grounded_continue",
        "response_text": noi,
        "response": noi,
        "display_text": noi,
        "speak_text": noi,
        # Nguon di theo doan dang doc, khong theo luot: bo no la de tai xe nghe nguyen
        # van so tay ma khong biet lay tu dau.
        "citations": list(state.get("speech_citations") or []),
        "has_more_to_read": con_du,
        "speech_citations": list(state.get("speech_citations") or []) if con_du else [],
        # Lát cuối vét hết thì dọn ngay, đừng để lại trạng thái treo: "đọc tiếp" lần
        # nữa phải nghe "đã đọc hết", không phải đọc lại đúng lát vừa rồi.
        **moc,
    }


def _moc_hoac_don(nguon: str, da_doc: list[int]) -> dict:
    """Giữ chỗ đang đọc dở, hoặc dọn sạch nếu đã đọc hết mọi câu."""
    from src.agents.nodes.speech_policy import _cau

    con = [i for i in range(len(_cau(nguon))) if i not in set(da_doc)]
    if con:
        return {"speech_source_text": nguon, "speech_da_doc": list(da_doc)}
    return {"speech_source_text": "", "speech_da_doc": []}


def _moc_doc_do(state: AgentState, chi_so: tuple[int, ...]) -> dict:
    """Nguồn và vị trí đã đọc tới, cho lượt "đọc tiếp" sau này.

    Trả `{}` khi không có gì để tiếp — và `{}` **khác** `{"speech_source_text": ""}`:
    LangGraph merge dict trả về vào state, nên khoá vắng mặt là *giữ nguyên* còn khoá
    rỗng là *xoá*. Lượt điều khiển ("bật điều hoà") phải giữ nguyên chỗ đang đọc dở, vì
    hỏi sổ tay → bật điều hoà → "đọc tiếp" là chuỗi bình thường trong xe.
    """
    nguon = (state.get("evidence") or [None])[0]
    text = (
        ""
        if nguon is None
        else (getattr(nguon, "text", None) or (nguon.get("text") if isinstance(nguon, dict) else "") or "")
    )
    # Điều kiện là **có nguồn**, không phải "đã đọc câu nào". Bản trước gộp hai thứ ấy,
    # nên nhánh biến thể — nói câu tự viết `_VARIANT_FALLBACK`, `chi_so` rỗng — không
    # lưu gì cả, trong khi lời mời "nghe tiếp nguyên văn" vẫn phát ra. Tài xế nói "nghe
    # tiếp" và nhận lại "tôi đã đọc hết phần này rồi". Bug người dùng gặp 15/08.
    #
    # Guard cũ có lý do thật (lượt điều khiển không được xoá chỗ đang đọc dở), nhưng lý
    # do ấy đã được bảo đảm bởi **call site**: hàm này chỉ được gọi trong nhánh trả lời
    # sổ tay. `chi_so` không phải thứ phân biệt hai loại lượt.
    if not text:
        return {}
    moc = _moc_hoac_don(text, list(chi_so))
    # Citation di theo DOAN dang doc, khong theo luot. `normalize` don `citations` moi
    # luot, nen khong giu o day thi luot "doc tiep" phat citations rong.
    moc["speech_citations"] = list(state.get("citations") or []) if moc["speech_source_text"] else []
    return moc

#: Mở đầu câu hỏi lại lần hai, khi mảnh vừa nghe không thuần là câu trả lời (#363).
#:
#: *"Tôi chưa nghe rõ"* chứ không phải *"bạn nói sai"*: rất có thể tài xế **không hề nói
#: với xe** — họ đang nói với người ngồi cạnh, và mic thì vừa tự mở. Đổ lỗi cho người
#: không làm gì sai là cách nhanh nhất để họ tắt trợ lý.
NGHE_HUT_MO_DAU = "Tôi chưa nghe rõ."


def _hoi_lai_vi_nghe_hut(state: dict) -> dict:
    """Nhắc lại **đúng câu hỏi cũ**, không tra cứu gì cả.

    Đây là lối ra NO_EXEC của #363, và nó phải nhắc lại câu hỏi vì lượt vừa rồi **không
    trả lời được gì**: slot vẫn trống y như trước. Nói một câu chung chung
    (*"tôi không hiểu"*) là bỏ tài xế lại giữa một cuộc hỏi đáp mà chính xe mở ra — đúng
    ngõ cụt mà `CLARIFY_MESSAGES` sinh ra để phá.

    Ngữ cảnh hỏi lại **vẫn còn** trong state (`route_node` cố ý không xoá), nên câu trả
    lời ở lượt sau vẫn ghép được — miễn còn trong TTL.

    Lý do không có trong hai bảng thì lui về `OUTCOME_MESSAGES["clarify"]`; thiếu một bản
    riêng không phải là lỗi, cùng quy ước với `CLARIFY_SPEAK`.
    """
    ly_do = str(state.get("cho_ghep_ly_do") or "")
    hien = CLARIFY_MESSAGES.get(ly_do) or OUTCOME_MESSAGES["clarify"]
    noi = CLARIFY_SPEAK.get(ly_do) or hien
    return {
        # Hiển thị giữ NGUYÊN câu đầy đủ, nói thì chỉ giữ vế hỏi — cùng lý lẽ đã có ở
        # `CLARIFY_SPEAK`: mắt đọc nhanh hơn tai gấp nhiều lần. Và ở lượt hỏi lại lần
        # hai, vế "tôi chưa làm gì cả" là thứ tài xế **vừa nghe cách đó một lượt**, nên
        # đọc lại nó ra loa là bắt người đang lái nghe thừa một câu.
        "response_text": f"{NGHE_HUT_MO_DAU} {hien}",
        "speak_text": f"{NGHE_HUT_MO_DAU} {_ve_hoi(noi)}",
        "has_more_to_read": False,
    }


def _ve_hoi(cau: str) -> str:
    """Vế **hỏi** của một câu hỏi lại — bỏ vế "tôi chưa làm gì cả" đứng trước.

    Cả 10 mục của `CLARIFY_SPEAK` đều có dạng `<đã làm gì>. <câu hỏi?>`, nên lấy câu cuối
    là đủ và không cần phân tích gì thêm. Câu không có dạng ấy (không kết bằng dấu hỏi)
    thì trả nguyên — thà nói thừa một vế còn hơn cắt cụt mất chính câu hỏi.
    """
    cau = cau.strip()
    if not cau.endswith("?"):
        return cau
    cuoi = cau.rsplit(". ", 1)
    return cuoi[-1].strip() if len(cuoi) > 1 else cau

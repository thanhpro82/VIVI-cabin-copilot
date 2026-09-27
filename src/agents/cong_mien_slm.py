"""Cổng fail-closed: plan của SLM phải chạm đúng cái tài xế vừa nhắc tới.

Yêu cầu (b) của review #324 (@thanhpro82): *"khoá fail-closed cho các ca còn sai: không
sinh plan, không publish/không thực thi. Cần test chứng minh rõ zero side effect."*

## Vì sao cần, đo được chứ không suy đoán

Sau #269, args do planner dựng **luôn hợp lệ** (2/16 → 16/16 trên server vừa khởi động).
Hệ quả phụ: một plan **sai tool** giờ cũng qua được `validate_args`, nên nó không còn
chết ở `clarify` như trước mà đi tiếp thành một hành động cụ thể. Năm ca đo được trên
Qwen3-4B thật (`planner-args/20260827T000533.480803Z`):

```
'bật đèn trần lên'   -> set_hvac_power{enabled:true}       nói ĐÈN,      ra ĐIỀU HOÀ
'bật đèn chiếu gần'  -> set_hvac_temperature{26}           nói ĐÈN,      ra ĐIỀU HOÀ
'mở cốp sau'         -> set_door_state{rear_left, open}    nói CỐP,      ra CỬA
'mở youtube'         -> set_hvac_temperature{26}           nói ỨNG DỤNG, ra ĐIỀU HOÀ
'đặt quạt gió mức 2' -> set_hvac_power{enabled:true}       nói QUẠT,     ra NGUỒN
```

## Hai thứ đã thử và KHÔNG được, ghi lại để không ai đi lại

1. **Thêm ví dụ few-shot cho năm tool bị chọn sai** — tool đúng đứng yên 11/16, y hệt
   năm ca cũ. Prompt không sửa nổi *lựa chọn* ở kích cỡ model này.
2. **Gác ở mức MIỀN** (bản đầu của file này): bắt được 4/5. Ca `"đặt quạt gió mức 2"`
   lọt vì `set_hvac_power` và `set_hvac_fan_level` cùng miền `hvac`. @thanhpro82 bác
   đúng chỗ ấy ở vòng review thứ hai — *"dù cùng miền HVAC, đây vẫn là hành động S1 sai
   ý người dùng"*. Miền là đơn vị quá thô: trong `hvac` có ba tool làm ba việc khác hẳn.

Nên cổng gác ở mức **tool**, không phải mức miền.

## Cái giá của việc gác ở mức tool, nói ra chứ không giấu

Chặt hơn thì chặn nhầm nhiều hơn, và có một ca chặn nhầm **thật**:

    "Nóng quá, giảm nhiệt độ xuống đi"  +  set_hvac_power{enabled:true}   -> BỊ CHẶN

Plan ấy hợp lý với người: không bật điều hoà thì hạ nhiệt độ bằng gì. Nhưng nó **cùng
một hình dạng** với ca `"đặt quạt gió mức 2"` → `set_hvac_power` mà review yêu cầu chặn:
câu nêu một mục tiêu cụ thể trong `hvac`, plan trả về một tool khác trong `hvac`. Không
có luật nào phân biệt được hai ca ấy mà không phải tự đoán ý người nói.

Chọn chặn cả hai, vì chiều hỏng của việc chặn là **hỏi lại** còn chiều hỏng của việc cho
qua là **làm sai**. Hai test cũ dùng đúng cặp lệch ấy làm stub (`test_slm.py`) đã được
sửa cho khớp — chúng đo chuyện khác (planner có được hỏi không, mất trạng thái xe thì
nói gì), miền của câu vào chỉ là ngẫu nhiên.

## Luật, và vì sao nó vẫn hẹp

Chặn khi câu nói nhắc tới thứ gì đó **và** tool được đề xuất không nằm trong tập mà thứ
ấy cho phép. Không đoán khi câu không nhắc gì — im lặng cho qua là đúng, vì phần lớn câu
tới đây là câu router không khớp được, và bắt chúng phải khai chủ đề là dựng lại chính
bộ luật mà planner sinh ra để thay thế.

## Cổng nhường đường cho S3

Xem `graph.slm_stage`. Bản đầu chặn trước mọi thứ và hạ một câu `blocked` — nói thật
rằng có chuyện gì đó bị chặn — thành `clarify` trống rỗng. Cả hai zero side effect nên
về an toàn là hoà; về câu tài xế nghe thì `blocked` hơn hẳn.
"""

from __future__ import annotations

from src.agents.contracts import CandidateActionPlan
from src.services.tool_registry import TOOL_REGISTRY

#: Từ khoá → **tập tool chấp nhận được**, không phải → miền.
#:
#: Bản đầu (#324) ánh xạ tới *miền*, và nó bắt được 4/5 ca. Ca thứ năm lọt:
#: `"đặt quạt gió mức 2"` → `set_hvac_power` — cả hai đều `hvac` nên cổng không thấy gì.
#: @thanhpro82 bác đúng chỗ ấy ở vòng review thứ hai: *"dù cùng miền HVAC, đây vẫn là
#: hành động S1 sai ý người dùng"*. Miền là đơn vị quá thô — trong `hvac` có ba tool làm
#: ba việc khác hẳn nhau, và `"quạt gió"` chỉ nói về một trong ba.
#:
#: Danh sách ĐÓNG và cố ý ngắn: nó chỉ cần bắt những chỗ nhầm đo được, không phải làm
#: lại router. Ba mức chi tiết cùng tồn tại có chủ ý — `"điều hòa"` nói chung nên nhận cả
#: ba tool hvac, còn `"quạt gió"` và `"nhiệt độ"` nói riêng nên chỉ nhận một.
#:
#: `đèn` cố ý KHÔNG có `đèn báo`/`đèn cảnh báo` — hai cụm ấy là câu hỏi sổ tay
#: ("đèn báo pin nghĩa là gì"), không phải lệnh, và chúng không tới được đây.
_TU_KHOA_TOOL: tuple[tuple[str, frozenset[str]], ...] = (
    # hvac — ba mức chi tiết
    ("quạt gió", frozenset({"set_hvac_fan_level"})),
    ("gió", frozenset({"set_hvac_fan_level"})),
    ("nhiệt độ", frozenset({"set_hvac_temperature"})),
    ("độ c", frozenset({"set_hvac_temperature"})),
    ("điều hòa", frozenset({"set_hvac_power", "set_hvac_temperature", "set_hvac_fan_level"})),
    ("điều hoà", frozenset({"set_hvac_power", "set_hvac_temperature", "set_hvac_fan_level"})),
    ("máy lạnh", frozenset({"set_hvac_power", "set_hvac_temperature", "set_hvac_fan_level"})),
    # lights — đèn trong xe và đèn ngoài xe là hai tool khác nhau
    ("đèn trần", frozenset({"set_interior_light"})),
    ("đèn trong xe", frozenset({"set_interior_light"})),
    ("đèn cabin", frozenset({"set_interior_light"})),
    ("đèn pha", frozenset({"set_headlight_mode"})),
    ("đèn cốt", frozenset({"set_headlight_mode"})),
    ("đèn chiếu", frozenset({"set_headlight_mode"})),
    # còn lại
    ("cốp", frozenset({"set_trunk_state"})),
    ("khoang hành lý", frozenset({"set_trunk_state"})),
    ("cửa sổ", frozenset({"set_window_position"})),
    ("cửa kính", frozenset({"set_window_position"})),
    ("kính", frozenset({"set_window_position"})),
    ("ghế", frozenset({"set_seat_heating", "set_seat_position"})),
    ("nhạc", frozenset({"media_control"})),
    ("bài hát", frozenset({"media_control"})),
    ("âm lượng", frozenset({"media_control"})),
    ("dẫn đường", frozenset({"set_navigation"})),
    ("chỉ đường", frozenset({"set_navigation"})),
    ("youtube", frozenset({"open_app"})),
    ("tiktok", frozenset({"open_app"})),
    ("spotify", frozenset({"open_app"})),
)


def _tool_chap_nhan(text: str) -> frozenset[str] | None:
    """Hợp của mọi tập tool mà câu nói cho phép, hoặc `None` khi câu không nhắc gì.

    **Hợp**, không phải giao, và không bỏ cuộc khi câu nhắc nhiều thứ: `"bật điều hòa và
    mở nhạc"` là lệnh ghép hợp lệ, nên cả tool hvac lẫn `media_control` đều phải được
    nhận. Bản đầu bỏ gác hẳn khi thấy nhiều miền — an toàn hơn về mặt chặn nhầm, nhưng
    nó cũng bỏ luôn phần bắt được, mà lệnh ghép mới là chỗ dễ lẫn tool nhất.
    """
    thap = (text or "").lower()
    hop: set[str] = set()
    thay = False
    for tu, tools in _TU_KHOA_TOOL:
        if tu in thap:
            thay = True
            hop |= tools
    return frozenset(hop) if thay else None


def lech_y(text: str, plan: CandidateActionPlan) -> str | None:
    """Tên tool đầu tiên nằm ngoài thứ câu nói cho phép, hoặc `None`.

    Trả về **tên tool** chứ không phải `bool`, để bên gọi ghi được vào log/trace cái tên
    cụ thể — `"chặn vì lệch"` mà không nói tool nào là một dòng log không dùng được.

    Chỉ xét tool **có trong registry**: một tên lạ là việc của `validate_args`, và bắt nó
    ở đây nghĩa là hai chỗ cùng báo một lỗi bằng hai giọng khác nhau.
    """
    cho_phep = _tool_chap_nhan(text)
    if cho_phep is None:
        return None
    for buoc in plan.steps:
        if buoc.tool in TOOL_REGISTRY and buoc.tool not in cho_phep:
            return buoc.tool
    return None


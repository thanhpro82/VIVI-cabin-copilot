"""Ghép mảnh trả lời vào câu hỏi lại của lượt trước (issue #148, phần B).

Xe hỏi *"quạt gió mức mấy?"*, tài xế đáp *"mức 2"*, và trước bản này lượt ấy rơi
thẳng xuống tra sổ tay: `"mức 2"` không khớp luật điều khiển nào nên theo ADR-011 nó
mặc định về manual. Đúng luật, sai ngữ cảnh.

## Vì sao ghép bằng CHUỖI chứ không vá slot có cấu trúc

Đo router thật trước khi viết (20/08), trên đúng các cặp mà issue nêu:

    'chỉnh quạt gió mức 2 điều hòa' + '18 độ'  -> control, 2 BƯỚC
    'tắt đèn'                      + 'đèn pha' -> denied/headlight_off_not_permitted
    'mở cửa sổ'                    + 'bên lái' -> clarify/missing_window_position
    'mở cửa sổ bên lái'      + '30 phần trăm'  -> control

Dòng đầu là lý do chọn cách này: nối chuỗi rồi route lại lấy về **cả hai** ý, kể cả ý
`quạt mức 2` mà issue ghi là mất hẳn — vì bộ luật đã biết đọc câu ghép nhiều lệnh. Vá
slot có cấu trúc thì phải tự dựng lại phần ấy và vẫn đánh rơi ý còn lại. Dòng cuối cho
thấy chuỗi nhiều slot tự nối tiếp: mỗi lượt ghép xong lại thành câu gốc của lượt sau.

## Luật chấp nhận, và ca thật ép ra từng vế

Cũng đo thật, các mảnh **không** phải câu trả lời, sau *"quạt gió mức mấy?"*:

| mảnh | route riêng | route sau khi ghép | phải |
|---|---|---|---|
| `mở nhạc` | **control** | clarify | không ghép — ghép là nuốt mất lệnh nhạc |
| `đèn cảnh báo ở đâu` | manual_question | manual_question | không ghép |
| `cảm ơn nhé` | — | clarify **cùng lý do** | không ghép |
| `tôi không biết` | — | denied/`negated_command` | không ghép |
| `hai bốn` | — | denied/`fan_level_out_of_range` | ghép — *"chỉ đặt được 0–3"* là câu trả lời đúng việc |

Hàng cuối là lý do `denied` nằm trong tập nhận: người vừa nói một con số, thứ họ cần
nghe là con số nào thì được, không phải im lặng. Hàng `tôi không biết` là lý do phải
trừ `negated_command` ra — chữ `không` bị đọc thành phủ định, và trả lời "tôi không
thực hiện được" cho một câu "tôi không biết" là vô nghĩa.

## Rủi ro còn lại, và giả định mà bộ chốt này dựa vào

`"hai"` ghép vào ra **control** thật (quạt mức 2, S1, không qua HITL). Router đọc được
số viết chữ nên không có cách phân biệt ngôn ngữ nào giữa *"hai"* trả lời máy và
*"hai"* nói với người ngồi cạnh. Cổng kiểu "mảnh phải có chữ số" thì loại luôn
`"mười tám độ"`, tức loại đúng đường thoại.

Thứ thật sự chặn ca ấy hôm nay: **sau một câu hỏi lại, mic KHÔNG tự mở** — auto-listen
chỉ gắn với `approval.required` (#203, #211). Mảnh trả lời vì thế chỉ tồn tại khi tài
xế chủ động bấm mic rồi nói. Bộ chốt dưới đây được tính **với giả định ấy**; thêm
auto-listen cho clarify, hoặc wake word (#177) vào, thì phải **mở lại ADR-025** trước
khi merge — giả định ấy có chữ ký ở đó, không phải một ghi chú.

Xem `docs/adr/ADR-025-chap-hanh-tu-ngu-canh-hoi-lai.md` (quyết định) và
`docs/agent_spec.md` mục "Ghép mảnh trả lời câu hỏi lại" (bản rút gọn).
"""

from __future__ import annotations

#: Ngữ cảnh hỏi lại sống bao lâu. Cùng bậc với 30 s của HITL, và cùng lý do: một câu
#: trả lời tới sau nửa phút thì nhiều khả năng đang trả lời chuyện khác.
TTL_GIAY = 30.0

#: Lý do `clarify` được phép nhớ để ghép ở lượt sau — **danh sách trắng**, không phải
#: "mọi thứ trừ...".
#:
#: Đúng tập các slot mà câu hỏi lại nêu được lựa chọn/dải cụ thể, tức đúng tập mà
#: `CLARIFY_MESSAGES` có lời riêng. Bốn lý do `clarify` còn lại của router bị loại vì
#: ghép chúng là đoán chứ không phải điền chỗ trống:
#:
#: - `relative_change_unsupported` — `"tăng âm lượng thêm 10" + "50"` là câu vô nghĩa;
#: - `ambiguous_number` — `"hai bốn"` vốn đã là chỗ router từ chối đoán;
#: - `ambiguous_reference` — chưa biết đang nói về cái gì thì ghép vào cái gì;
#: - `unknown_local_destination` — nối tên địa điểm thứ hai vào không tạo ra địa điểm.
CO_THE_GHEP: frozenset[str] = frozenset(
    {
        "missing_light_target",
        "missing_fan_level",
        "missing_temperature",
        "missing_volume",
        "missing_window_side",
        "missing_window_position",
        "missing_seat_side",
        "missing_seat_level",
        "missing_seat_value",
    }
)

#: Lý do `denied` **không** tính là ghép thành công. Xem bảng ở docstring đầu file.
_DENIED_KHONG_TINH: frozenset[str] = frozenset({"negated_command"})


def con_han(luc_hoi: float, bay_gio: float) -> bool:
    """Ngữ cảnh còn hạn không. `luc_hoi <= 0` nghĩa là không có ngữ cảnh nào."""
    if luc_hoi <= 0:
        return False
    return 0 <= bay_gio - luc_hoi <= TTL_GIAY


def ghep(cau_goc: str, manh: str) -> str:
    """Nối chuỗi, không sắp xếp lại gì cả.

    Cố ý không "thông minh" hơn: mọi phép chèn vào giữa đều là một cách đọc hiểu câu
    mà bộ luật không hứa, còn nối đuôi thì bộ luật đã đọc được — bảng ở docstring đầu
    file là bằng chứng, gồm cả ca xấu `"tắt đèn" + "đèn pha"` ra `"tắt đèn đèn pha"`
    mà router vẫn đọc đúng.
    """
    return f"{cau_goc.strip()} {manh.strip()}".strip()


def chap_nhan(disposition: str, reason: str, ly_do_dang_cho: str) -> bool:
    """Kết quả route câu đã ghép có tính là "ghép được" không.

    Ba vế, mỗi vế do một ca đo thật ép ra (bảng ở docstring đầu file):

    - `control` — có kế hoạch chạy được;
    - `clarify` với lý do **khác** lý do đang chờ — chuỗi slot tiến thêm một bước;
    - `denied` trừ `negated_command` — câu ngoài dải là câu trả lời hữu ích.

    `clarify` **cùng** lý do là dấu hiệu mảnh vừa rồi chẳng đóng góp gì (`"cảm ơn nhé"`),
    nên không ghép và để lượt đi đường thường.
    """
    if disposition == "control":
        return True
    if disposition == "clarify":
        return bool(reason) and reason != ly_do_dang_cho
    if disposition == "denied":
        return reason not in _DENIED_KHONG_TINH
    return False

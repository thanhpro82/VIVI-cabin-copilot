# `multiturn-v1` — bộ đo hội thoại nhiều lượt

52 ca, mỗi ca **1–3 lượt** chảy qua cùng một state, đúng như checkpoint LangGraph giữ
giữa hai lượt của một phiên. (37 ca ở mốc `moc_2908` gốc — offer/clarify — cộng 15 ca
nhóm `routine-giong-noi` thêm 30/08, #274/#299.)

## Vì sao phải có bộ này trước khi sửa

Bộ đo hiện có (`agent/v3`, `dinh-tuyen-v1`, `bao-loi-2408`) **toàn ca đơn lượt**. Ngay cả
10 ca `clarify` trong đó cũng chỉ chấm *lượt hỏi lại*, không chấm chuyện gì xảy ra ở lượt
trả lời. Nên trước bộ này, không con số nào trong repo nói được về đa lượt.

`docs/superpowers/specs/2026-08-23-lo-trinh-agent-theo-kich-ban.md` §9 vừa dạy đúng bài
này: một cải tiến nghe rất xuôi (bỏ lead-in cho gọn) hoá ra làm **giảm** điểm, và chỉ có
phép đo nói ra điều đó. Nên bộ đo đi trước bản vá, không đi sau.

## Mốc `moc_2908`

Đo trên `develop` @ `ddfa4b7`, ngày 29/08, ở mức `route_node` (tất định, không LLM).
**Không bao giờ sửa lại** — mọi thay đổi baseline về sau chỉ được ghi thêm, có vết,
giống cơ chế `cong_hoi_quy.json` của `bao-loi-2408`.

| nhóm | ca | mốc | nội dung |
|---|---|---|---|
| `offer-nhan` | 5 | `hong` | xe đề nghị một hành động, tài xế nói "Có"/"Ừ"/"Đồng ý" |
| `offer-tu-choi` | 2 | `hong` | tài xế nói "Không"/"Thôi khỏi" |
| `offer-phu-song` | 2 | `hong` → **`dung` 30/08** | cách hỏi mà luật `offer` chưa nhận ra — đóng ở #368 |
| `an-toan` | 5 | `dung` | những chỗ **phải giữ trơ**, xem dưới |
| `clarify-ghep` | 5 | `dung` | đường ghép ngữ cảnh của #148 phần B |
| `clarify-rao-chan` | 5 | `hong` | mảnh mang thêm nội dung khác — rào chắn #363 |
| `clarify-rao-chan` | 9 | `dung` | mảnh thuần là câu trả lời, phải giữ chạy |
| `clarify-auto-listen` | 4 | `dung` | cờ `mo_mic_ngan` đúng cho cặp `clarify`+`CO_MAU` — #364 |

14 ca `hong` / 23 ca `dung`. Nhóm `clarify-rao-chan` thêm ngày 29/08 cùng ngày, mốc đo trên
`develop` @ `88d6d85`. Nhóm `clarify-auto-listen` thêm ngày 30/08, mốc đo trên `develop` @
`65343e1` — dùng chung khoá `moc_2908` với các nhóm trên (đây là tên trường cơ chế
`di_lui`/`da_sua` đọc, không phải ngày đo; cùng cách nhóm `clarify-rao-chan` đã làm).

## Kết quả đo, nguyên văn

```
'Bật điều hòa được không'  -> offer/question_about_supported_action  [set_hvac_power {enabled: True}]
'Có'                       -> not_control/default_to_manual          []
```

Plan **đã dựng xong và hợp lệ** ở lượt 1; lượt 2 vứt nó đi rồi mang chữ "Có" đi tra sổ
tay. Đó là toàn bộ nội dung của #355 mục 1 và #339.

Hai chỗ luật `offer` chưa phủ, cũng đo được:

```
'Có mở được cốp không'       -> not_control/manual_question
'Có thể bật điều hòa không'  -> not_control/manual_question
```

Đều là **"có" đứng đầu câu** — dạng hỏi rất tự nhiên trong tiếng Việt.

## Năm ca `an-toan`: đây mới là phần khó

Chúng **đang đúng** và phải còn đúng sau khi sửa. Chúng là lý do việc này không phải
"nhớ plan lượt trước là xong":

- `MT-AN-001` — "Có" khi **không có** đề nghị nào đang treo → trơ.
- `MT-AN-002` — sau đề nghị, tài xế nói `"hai"`. Một mảnh số. Nếu cửa nhận câu trả lời
  mở quá rộng thì nó thành `set_hvac_fan_level(level=2)` — một lệnh **không ai yêu cầu**.
- `MT-AN-003` — đề nghị, rồi **một lượt khác xen vào**, rồi "Có". Đề nghị đã nguội; nhận
  nó ở đây là thực thi một câu tài xế nói về chuyện khác.
- `MT-AN-004` — "Có" sau `clarify`. `clarify` hỏi *"bên nào?"*; "Có" không trả lời được
  câu ấy, nên nó không được biến thành gì cả.
- `MT-AN-005` — sau đề nghị, tài xế đổi ý và ra **lệnh mới**. Lệnh mới phải thắng, không
  bị hiểu thành câu trả lời.

## Cách chấm

Một ca **đạt** khi **mọi** lượt đạt. Từng lượt so:

- `disposition` — luôn so;
- `route_reason` — chỉ so khi ca ghi rõ (dùng để phân biệt *"tôi không làm"* với
  *"tôi không tra được"*, hai thứ cùng nhãn `not_control` mà khác hẳn nhau);
- `tools` — so theo **tập** `(tool, args)`, không theo thứ tự. Thứ tự hai bước HVAC do
  bộ luật quyết định chứ không phải thứ tự tài xế nói, nên khoá nó là khoá nhầm thứ.

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn   # -> eval/results/agent-multiturn/
```

## Nhóm `clarify-rao-chan` (thêm 29/08, issue #363)

Bộ đo phần trên hỏi *"xe có nghe được câu trả lời không"*. Nhóm này hỏi câu ngược lại —
**xe có nghe nhầm thứ không phải câu trả lời không**, và nó cần thiết vì #363 mở mic tự
động sau `clarify`.

Mốc đo cho thấy nó **không phải** rủi ro tương lai; nó đã xảy ra với mic bấm tay:

```
"Tăng quạt gió"  ->  clarify/missing_fan_level
    "hai giờ nhé"            ->  control  set_hvac_fan_level{level: 2}
    "hai người nữa thôi"     ->  control  set_hvac_fan_level{level: 2}
    "mai hai giờ chiều nhé"  ->  control  set_hvac_fan_level{level: 2}

"Bật đèn"        ->  clarify/missing_light_target
    "đèn pha bị hỏng rồi"    ->  control  set_headlight_mode{mode: low_beam}
```

Câu cuối là một lời **than phiền** thành một **lệnh bật đèn**.

**9 ca dương tính quan trọng ngang 5 ca âm tính.** Một rào chắn quá tay thì mọi câu trả
lời thật cũng rụng, và ta đổi một lỗi lấy một sản phẩm không dùng được. Chúng khoá đúng
những cách nói mà ADR-025 đã cảnh báo là dễ bị loại nhầm — `"mười tám độ"`, `"năm mươi"`,
`"một nửa"` — cùng ca `"hai bốn"` ngoài dải, vốn **phải** ghép để tài xế nghe được
*"chỉ đặt được 0–3"*.

## Nhóm `clarify-auto-listen` (thêm 30/08, issue #364)

`clarify-rao-chan` ở trên chấm **router** có ghép đúng mảnh trả lời không. Nhóm này chấm
một tầng khác: cờ `mo_mic_ngan` (`src/agents/nghe_tiep.py::con_nghe_tiep`) — thứ FE đọc để
quyết định có tự mở mic 3–5s sau `clarify` hay không (`WakeWordController`/`FOLLOW_UP_WINDOW`,
PR #387/ADR-028) — có đúng **chỉ** mở cho 9 lý do `clarify` có mẫu ngữ pháp
(`src.agents.mau_slot.CO_MAU`) hay không, và có đóng lại khi lượt sau ra NO_EXEC
(`route_reason == "manh_khong_khop_mau"`) hay không.

Ba việc được đo, mỗi việc một ca (`MT-AUTO-001`/`002` một slot khác nhau trong `CO_MAU`,
`MT-AUTO-003` cặp mở-rồi-đóng, `MT-AUTO-004` biên ngoài `CO_MAU`):

```
"Tăng quạt gió"  -> clarify/missing_fan_level     mo_mic_ngan=True
"Mở cửa sổ"      -> clarify/missing_window_side   mo_mic_ngan=True
"Bật đèn"        -> clarify/missing_light_target  mo_mic_ngan=True
    "đèn pha bị hỏng rồi" -> not_control/manh_khong_khop_mau  mo_mic_ngan=False
"Mở cửa bên trái" -> clarify/missing_door_side    mo_mic_ngan=False   # ngoài CO_MAU, có chủ ý (ADR-025)
```

**Giới hạn phải biết khi đọc/thêm ca vào nhóm này:** `con_nghe_tiep` đọc đúng
`outcome`/`route_reason` ở **mức `route_node`** cho hai giá trị `clarify`/`not_control` —
nhưng **không** đúng cho `control`. Ở mức `route_node`, một lượt khớp lệnh có `outcome`
vẫn là chuỗi `"control"`, chưa phải `"completed"` (giá trị thật chỉ có sau khi
`execute_node` chạy trong graph đầy đủ), nên `con_nghe_tiep` sẽ trả `False` cho nó — **sai**
so với hành vi thật trên graph đầy đủ (nơi `completed` → `True`). Vì vậy: **không được**
gán `expected.mo_mic_ngan` cho một lượt có `disposition: "control"` trong dataset này; chỉ
gán cho lượt `clarify` hoặc `not_control`. Việc `completed`/`offer`/`grounded_answer` mở
mic đúng đã có unit test riêng, không phụ thuộc dataset này: `tests/test_agents/test_nghe_tiep.py`.

## Sửa 30/08 — hai ca `offer-phu-song` đã đóng (#368)

```
"Có mở được cốp không"       ->  offer  [set_trunk_state]
"Có thể bật điều hòa không"  ->  offer  [set_hvac_power]
```

Router nay bóc giàn giáo nghi vấn (`"có"`, `"có thể"`, `"được"`, `"bạn"`, `"giúp tôi"`) và
thử khớp lại **một lần** — chỉ trong nhánh `is_question`, và chỉ khi luật đã không khớp.

Mốc `moc_2908` của hai ca đổi `hong` → `dung`, kèm `ghi_chu` ghi ngày và lý do. Từ đây
chúng là **cổng hồi quy**: tái hỏng thì `di_lui` khác rỗng. Đây là cùng cơ chế
`cong_hoi_quy.json` của `bao-loi-2408`, chỉ khác là ghi thẳng vào ca vì bộ này nhỏ.

Bộ đo của 37 ca gốc (offer/clarify) nay **37/37** — xem nhóm `routine-giong-noi` dưới đây
cho 15 ca thêm sau, đo và tính hồi quy riêng.

## Nhóm `routine-giong-noi` (15 ca, thêm 30/08 — #274, #299)

Đo trên `develop` @ `d088b49` **trước** khi sửa, qua graph thật — sáu câu Routine, sáu
lần tra sổ tay:

```
"Chạy routine Đi làm"         -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Routine Về nhà gồm những gì" -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Dừng lại"                    -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
```

Câu thứ ba đáng lo nhất: đó là lệnh **hủy**. Nguyên nhân: `routines_intent.py` (#285) đã
đọc được ý định từ trước nhưng **không ai gọi nó** — chỉ test của chính nó import — và
`router.py` không có một chữ `routine` nào.

Mốc đo được: `routine-giong-noi 4/10` trước, `15/15` sau (10 ca `MT-RTN-00x` promote
`hong -> dung`, 5 ca `MT-RTN-1xx` **âm tính** giữ nguyên `dung` ở cả hai đầu — con số này
đã đổi so với ghi chú "10 ca"/"sáu+bốn" ban đầu; xem `case_id` trong `cases.jsonl` là
nguồn đúng, không phải prose ở đây).

**Năm ca âm tính quan trọng ngang mười ca dương**, vì cổng Routine đứng **trước** nhánh câu
hỏi sổ tay (bắt buộc: `"Routine Về nhà gồm những gì"` chứa chữ "gì"). Chúng khoá rằng phép
đặt trước ấy không làm rộng cửa: một lệnh xe (`"Bật điều hòa"`), một câu hỏi sổ tay
(`"Camp Mode là gì"`), và hai câu chứa **đúng tên Routine** mà không phải lệnh
(`"Đi làm"`, `"Hôm nay tôi đi làm muộn"` — bất biến #285: tên không bao giờ tự kích hoạt).

**Bộ này không đo được đường thực thi.** Nó chấm ở mức `route_node`, tức đo router **nói**
đúng chứ không đo xe **làm** đúng. Bằng chứng: 10/10 ở đây từng xanh trong lúc xe trả
`"Đã xử lý yêu cầu."` cho mọi lượt Routine — một thành công giả, tệ hơn lời từ chối thành
thật trước đó. Nó chỉ lộ ra khi chạy `POST /turns/text` thật. Phần thực thi có test riêng:
`tests/test_agents/test_routine_node.py`, `test_routine_loi_thoai.py`,
`tests/test_agents/test_routine_xem_truoc_xac_nhan.py` (preview → đồng ý/từ chối, review
PR #401), và `tests/test_api/test_approval_voice_intent.py` (cổng HITL không được nuốt
câu hủy).

## Tổng, sau khi gộp cả hai nhóm trên

`n=52 dat=52 case_accuracy=1.0000 luot=87/87 DI LUI=0` — đo lại trên cây đã gộp cả sửa
`offer-phu-song` (#368) lẫn nhóm `routine-giong-noi` (#274/#299), 31/08.

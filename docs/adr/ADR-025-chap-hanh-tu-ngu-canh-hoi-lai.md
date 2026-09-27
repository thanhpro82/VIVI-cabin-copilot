# ADR-025: chấp hành lệnh từ ngữ cảnh câu hỏi lại — bốn chốt, và một giả định có chữ ký

- Status: **Proposed** — chờ @thanhpro82 (PM/PO) duyệt trên [PR #217](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/217)
- Date: 2026-08-20
- Decision owner: WS Agent/Router + HITL (Nhân)
- Liên quan: [issue #148](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/148),
  [PR #217](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/217),
  [ADR-006](ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md) (router tất định),
  [ADR-010](ADR-010-canonical-tool-registry-with-product-vision-adapter.md) (router không đọc trạng thái),
  [ADR-011](ADR-011-default-route-to-manual-lookup.md) (mặc định về tra sổ tay),
  [issue #107](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/107) (`_tra_loi_loi_moi_nghe_tiep` — tiền lệ),
  [PR #203](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/203) / [#211](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/211) (auto-listen khi chờ duyệt),
  [PR #177](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/177) (wake word),
  `docs/agent_spec.md` §"Ghép mảnh trả lời câu hỏi lại", `src/agents/ghep_hoi_lai.py`

## Context

Xe hỏi lại, tài xế đáp, và xe không hiểu chính câu trả lời của câu nó vừa hỏi. Đo trên `develop` (hai lượt cùng `session_id`):

| lượt 1 | lượt 2 | kết quả lượt 2 |
|---|---|---|
| *"Chỉnh quạt gió mức 2 điều hòa"* → *"Bạn muốn đặt nhiệt độ bao nhiêu độ?"* | **"18 độ"** | tra sổ tay, xe không đổi gì |
| như trên | **"Chỉnh điều hòa 18 độ"** | chạy, nhiệt độ → 18, **nhưng quạt vẫn mức 3** — ý của lượt 1 mất hẳn |

Nguyên nhân: `route(text)` không biết lượt trước hỏi gì, nên `"18 độ"` không khớp luật nào và theo ADR-011 rơi về tra sổ tay — **đúng luật, sai ngữ cảnh**.

Hai quyết định cũ ràng buộc lời giải. ADR-006 chốt router **tất định**; ADR-010 chốt nó **không đọc trạng thái**. Cả hai đều phải giữ.

## Decision

**1. Cho phép ghép mảnh trả lời của lượt sau vào câu của lượt trước, rồi định tuyến lại — tức cho phép một lệnh chấp hành sinh ra từ ngữ cảnh nhớ được.** Đây là phần cần quyết, và là lý do ADR này tồn tại.

**2. Router giữ nguyên tất định và không đọc trạng thái.** Nó chỉ được gọi lại với một **chuỗi khác**; không có state nào chui vào `router.py`. Ngữ cảnh sống ở node — cùng chỗ đứng và cùng lập luận với `_tra_loi_loi_moi_nghe_tiep` (#107), vốn đã ghi: *node đọc được state, router thì không*. **ADR-006 và ADR-010 không bị đụng.**

Nhưng tiền lệ ấy **không** phủ hết: cổng "nghe tiếp" chỉ diễn giải lại một lượt thành hành vi **đọc** (S0), còn cổng này dựng **lệnh chấp hành**. Chênh lệch đó là phần ADR này phải chịu trách nhiệm.

**3. Ghép bằng nối chuỗi (`gốc + " " + mảnh`), không vá slot có cấu trúc.** Do đo, không do sở thích:

```
'chỉnh quạt gió mức 2 điều hòa' + '18 độ'  ->  control, 2 BƯỚC
'tắt đèn'                      + 'đèn pha' ->  denied/headlight_off_not_permitted
'mở cửa sổ'                    + 'bên lái' ->  clarify/missing_window_position
'mở cửa sổ bên lái'      + '30 phần trăm'  ->  control
```

Dòng đầu lấy lại **cả ý `quạt mức 2`** — thứ mà tầng vá-slot sẽ đánh rơi, vì nó chỉ điền chỗ trống chứ không đọc lại câu.

**4. Chỉ ghép cho 9 lý do `clarify` nêu được lựa chọn/dải** (`missing_light_target`, `missing_fan_level`, `missing_temperature`, `missing_volume`, `missing_window_side`, `missing_window_position`, `missing_seat_side`, `missing_seat_level`, `missing_seat_value`) — danh sách trắng, đúng tập có lời riêng trong `CLARIFY_MESSAGES`. Bốn lý do còn lại bị loại vì ghép chúng là **đoán**, không phải điền chỗ trống: `relative_change_unsupported` (`"tăng âm lượng thêm 10" + "50"` là câu vô nghĩa), `ambiguous_number`, `ambiguous_reference`, `unknown_local_destination`.

**5. Lệnh ghép ra đi qua policy/safety như mọi lệnh khác.** Cổng chỉ thay `RouteDecision`; không có đường tắt tới executor. Một lệnh S2 ghép ra vẫn dừng ở `approval.required` — có test ở mức API khoá điều này.

## Bốn chốt, mỗi chốt do một ca đo thật ép ra

| chốt | ca ép nó ra | nếu bỏ chốt |
|---|---|---|
| chỉ **lượt kế tiếp ngay sau** | — | ngữ cảnh sống dai, một mảnh nói sau vài lượt vẫn ghép |
| **TTL 30 s**, cùng bậc HITL | — | câu trả lời tới sau nửa phút nhiều khả năng đang trả lời chuyện khác |
| **không ghép nếu lượt mới tự khớp `control`** | `"mở nhạc"` sau câu hỏi quạt gió: ghép vào ra `clarify` | **nuốt mất một lệnh** của tài xế |
| **kết quả ghép phải có nghĩa** | `"cảm ơn nhé"` → `clarify` **cùng lý do**; `"tôi không biết"` → `denied/negated_command` | trả lời vô nghĩa cho một câu không phải câu trả lời |

Chốt thứ nhất không cần bộ đếm lượt: mọi lượt **không phải** câu hỏi lại đều **quét sạch** ngữ cảnh ở cuối lượt, và phép xoá ấy *là* chốt.

Ngữ cảnh sống trong kênh state của checkpoint LangGraph khoá theo `thread_id = session_id`, nên nó **chết cùng tiến trình** — đúng chủ ý: một câu hỏi lại sống sót qua restart là một cái bẫy, không phải tính năng.

## Rủi ro nhận, nói thẳng

Router đọc được số viết chữ, nên `"hai"` ghép vào ra **`control` thật** (quạt mức 2, S1, không qua HITL). Không có cổng ngôn ngữ nào phân biệt được *"hai"* trả lời máy với *"hai"* nói với người ngồi cạnh. Và cổng kiểu "mảnh phải có chữ số" thì loại luôn `"mười tám độ"` — tức loại đúng đường thoại, thứ sản phẩm này lấy làm chính.

Chấp nhận rủi ro ấy, với ba thứ bao quanh: TTL 30 s, chỉ lượt kế tiếp, và câu xác nhận sau khi chạy (*"Đã chỉnh quạt gió mức 2"*) để tài xế nghe được thứ vừa xảy ra.

## Giả định có chữ ký — và điều kiện mở lại ADR này

> ⚠️ **Giả định này đã HẾT HIỆU LỰC ngày 2026-08-29.** Mục dưới đây giữ nguyên văn để đọc được lịch sử; điều kiện mở lại đã xảy ra đúng như dự liệu. Xem §Sửa đổi 2026-08-29 ở cuối.

> **Sau một câu hỏi lại, micro KHÔNG tự mở.** Auto-listen chỉ gắn với `approval.required` (#203, #211).

Vì thế một "mảnh trả lời" chỉ tồn tại khi tài xế **chủ động bấm mic rồi nói**. Đó là thứ thật sự chặn ca `"hai"` nói với người bên cạnh — không phải bộ chốt ở trên.

**Bộ chốt này được tính với giả định ấy.** Hai thay đổi sau đều **đổi giả định** và bắt buộc mở lại ADR này trước khi merge:

1. thêm auto-listen cho nhánh `clarify` (dù chỉ một dòng trong `DriverShellProvider`);
2. wake word ([#177](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/177)) — mic mở mà không cần chạm là đúng nghĩa xoá giả định này.

Người review hai thứ đó có trách nhiệm nhìn lại đây. Ghi ở cả `agent_spec.md` và docstring `src/agents/ghep_hoi_lai.py` để nó không nằm một chỗ.

## Phương án đã cân nhắc và bác

**Vá slot có cấu trúc** (nhớ `intent` + tên slot, parse riêng giá trị). Bác: đánh rơi ý còn lại của lượt 1 — đo được ca đầu bảng ra **2 bước** khi nối chuỗi, và đó chính là triệu chứng thứ hai mà #148 mô tả.

**Cho router đọc ngữ cảnh.** Bác: phá ADR-006/ADR-010, và không cần — node đã đọc được state.

**Cổng chấp nhận theo hình thức mảnh** (phải có chữ số / phải thuộc bảng từ). Bác: loại `"mười tám độ"`, tức loại đường thoại. Thay bằng cổng theo **kết quả route** (`chap_nhan`), vì chính bộ luật là thứ biết mảnh ấy có điền được chỗ trống không.

**Không làm gì (chỉ giữ phần A).** Bác: chín câu hỏi lại của A hứa *"nói mỗi số cũng được"* — lời hứa ấy **sai** nếu không có phần này, nên A một mình buộc phải dạy tài xế nói lại cả câu, và ngõ cụt vẫn còn.

## Hệ quả

- Tài xế trả lời một mảnh là xong việc; chuỗi nhiều slot (`"mở cửa sổ"` → `"bên lái"` → `"30 phần trăm"`) tự nối tiếp.
- Ca đầu bảng của #148 lấy lại **cả hai** ý, không chỉ ý vừa điền.
- Thêm ba trường state (`cho_ghep_text`, `cho_ghep_ly_do`, `cho_ghep_luc`) và một cờ quan sát `da_ghep_hoi_lai` cho trace/log.
- **Thu hồi rẻ:** bỏ đúng một lời gọi `_ghep_manh_tra_loi` trong `route_node` là hệ quay về hành vi cũ; phần A vẫn đứng, chỉ cần sửa lại chữ trong 9 câu hỏi lại.

---

## Sửa đổi 2026-08-29 — giả định hết hiệu lực, và thứ thay chỗ nó

- Ngày: 2026-08-29 · Do: [issue #363](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/363) (PM/PO chốt hướng)
- Bộ đo: `eval/datasets/agent/multiturn-v1`, nhóm `clarify-rao-chan` (14 ca)

### Điều kiện mở lại đã xảy ra

Mục "Giả định có chữ ký" liệt kê hai thay đổi bắt buộc mở lại ADR này. Cả hai đã tới:
wake word đã vào (#341/#347/#349, sau cờ `NEXT_PUBLIC_WAKE_WORD_ENABLED`), và #363 chốt
**auto-listen ngắn 3–5 s sau `clarify`**. Giả định "mic không tự mở" vì thế **hết hiệu lực**.

### Nhưng rủi ro thì tệ hơn mô tả cũ — nó đã hiện thực rồi

Mục "Rủi ro nhận" viết như một rủi ro **tương lai**, phụ thuộc vào việc mic có tự mở hay
không. Đo lại 29/08 cho thấy nó **đã xảy ra sẵn** với mic bấm tay:

```
"Tăng quạt gió"  ->  clarify/missing_fan_level
    "hai giờ nhé"            ->  control  set_hvac_fan_level{level: 2}
    "hai người nữa thôi"     ->  control  set_hvac_fan_level{level: 2}
    "mai hai giờ chiều nhé"  ->  control  set_hvac_fan_level{level: 2}

"Bật đèn"        ->  clarify/missing_light_target
    "đèn pha bị hỏng rồi"    ->  control  set_headlight_mode{mode: low_beam}
```

Câu cuối là một lời **than phiền** thành một **lệnh**. Nên bộ chốt cũ không "đủ với giả
định của nó" như ADR này từng tính — nó thiếu ngay cả khi giả định còn đúng.

### Chốt thứ năm: mẫu ngữ pháp của slot (`src/agents/mau_slot.py`)

> **Mảnh trả lời phải THUẦN là câu trả lời**: mọi từ phải hoặc là giá trị của slot đang
> thiếu, hoặc là từ đệm; và phải có **ít nhất một** từ giá trị.

Không khớp thì **NO_EXEC**: xe nhắc lại đúng câu hỏi cũ, đóng mic, và **giữ nguyên ngữ
cảnh** để câu trả lời ở lượt sau vẫn ghép được.

### Điều này KHÔNG mâu thuẫn với mục "Phương án đã cân nhắc và bác"

Mục ấy bác *"cổng chấp nhận theo hình thức mảnh (phải có chữ số / phải thuộc bảng từ)"*.
Hai khác biệt, và cả hai đều là lý do bác ấy không áp vào đây:

1. **Nó bác một cổng THAY THẾ, đây là cổng THỨ HAI.** `chap_nhan()` vẫn chạy trước và vẫn
   là thứ quyết mảnh có điền được chỗ trống không. Mẫu chỉ soi những mảnh mà luật cũ **đã
   đồng ý ghép** — nên nó chỉ siết, không mở thêm và không chặn thêm ai. Thứ tự ấy là bắt
   buộc: đặt trước thì `"Áp suất lốp bao nhiêu"` sau một câu hỏi lại sẽ chết oan.
2. **Lý do bác cụ thể là "loại `mười tám độ`", và mẫu này KHÔNG loại nó.** Con số dẫn xuất
   từ `router._NUMBER_WORDS`/`_TENS_TOKENS`, còn `độ` nằm trong từ vựng của slot nhiệt độ.
   Đo được: `"mười tám độ"` qua, `"mười tám giờ rồi"` rụng.

### Vì sao không dùng confidence

#363 kiểm và ghi: hệ **không có** tín hiệu ấy. `src/services/voice.py` hard-code `0.0`
cho STT, `contracts.py` để router `confidence = 1.0` và không nơi nào gán khác. Gate bằng
một con số luôn bằng 1.0 là gate bằng không gì cả.

### Vì sao cổng chạy cả khi mic không tự mở

Có thể chỉ siết khi FE báo *"tôi vừa tự mở mic"*. Không làm, vì đó là để **client tự khai**
một cổng an toàn — một build cũ hay một client khác là đủ để cổng biến mất trong im lặng —
và vì `"đèn pha bị hỏng rồi"` bật đèn là sai **dù mic mở kiểu gì**.

### Một tập, hai vai

`mau_slot.CO_MAU` vừa là danh sách slot **được mở mic ngắn**, vừa là danh sách slot **bị
cổng siết**. Cố ý: không có rào thì không mở cửa, và không siết thứ mình chưa đo được.
`missing_door_side` vẫn nằm ngoài `CO_THE_GHEP` (S2/S3) — #363 ghi rõ không mở lại.

### Số đo

| | ca đạt | `clarify-rao-chan` | `di_lui` |
|---|---:|---:|---:|
| trước | 26/33 | 9/14 | 0 |
| sau | **31/33** | **14/14** | **0** |

Hai ca còn `hong` là `offer-phu-song`, thuộc #368 — không liên quan chốt này.

### Thu hồi

Bỏ đúng một điều kiện `if ly_do in CO_MAU and not khop_mau(...)` trong
`_ghep_manh_tra_loi` là hệ quay về hành vi trước #363; cờ `mo_mic_ngan` khi ấy chỉ là một
trường thừa trong payload, không ai đọc.

---

## Sửa đổi 2026-08-30 — vế FE đóng, không phải bằng một cơ chế riêng

- Ngày: 2026-08-30 · Do: [issue #364](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/364)
- Bộ đo: `eval/datasets/agent/multiturn-v1`, nhóm `clarify-auto-listen` (4 ca, run
  `20260829T173053.185471Z` — UTC, tức 30/08 giờ Việt Nam)

Mục "Giả định có chữ ký" ở trên liệt hai thay đổi bắt buộc mở lại ADR này, và mục
"Sửa đổi 2026-08-29" đã đóng vế thứ hai (wake word) và một phần vế thứ nhất (backend của
#363). **Vế FE của thay đổi thứ nhất** — *"thêm auto-listen cho nhánh `clarify`, dù chỉ một
dòng trong `DriverShellProvider`"* — bỏ ngỏ tới hôm nay.

Nó đã đóng, nhưng **không** phải bằng một cơ chế riêng cho `clarify` như văn bản gốc hình
dung. PR #387 (`cửa sổ nghe tiếp mở sau mọi lượt`, ADR-028, cùng ngày 29/08) tổng quát hoá
đúng thứ ADR này cần: `WakeWordController`/`wakeWordState.ts` đọc cờ `moMicNgan` — cờ đã có
sẵn từ #363, giờ do `nghe_tiep.con_nghe_tiep()` tính cho **mọi** outcome đủ điều kiện, gồm
cả `clarify`+`CO_MAU` — và tái dùng nguyên `FOLLOW_UP_WINDOW` (6 giây, không phải cửa sổ
3–5 giây riêng #364 từng đề xuất) cộng ba phanh (ngân sách lượt, ngân sách thời gian, tín
hiệu backend). FE không phân biệt "vì sao" `moMicNgan=true`; quyết định *vì sao* hoàn toàn
nằm ở backend, đúng tinh thần "phanh chính nằm ở backend" mà module `nghe_tiep.py` tự ghi.

Vì cơ chế dùng chung, `mau_slot.CO_MAU`/`con_nghe_tiep()` đã có unit test riêng
(`tests/test_agents/test_nghe_tiep.py`), và FE đã có test chung cho `moMicNgan`
(`real.cuaSoNgheTiep.test.ts`, `WakeWordController.test.ts`) — cái còn thiếu, và là việc
#364 đóng, chỉ là **bằng chứng đo được riêng cho đúng cặp `clarify`+`CO_MAU`** ở mức
router: nhóm `clarify-auto-listen` xác nhận cờ mở đúng cho slot có mẫu, đóng đúng khi lượt
sau NO_EXEC, và **không** mở cho slot ngoài `CO_MAU` (`missing_door_side`, ca `MT-AUTO-004`)
— tức biên "một tập, hai vai" của #363 giữ đúng ở tầng tín hiệu FE đọc, không chỉ ở tầng
router. Không có thay đổi hành vi nào đi kèm; đây là đóng khoản còn treo, không phải một
quyết định mới.

### Không làm

Không thêm hằng số/nhánh state riêng 3–5 giây cho `clarify` như văn bản #364 gốc đề xuất —
sẽ đi ngược hướng hợp nhất mà #387 vừa chọn (một cờ, một cửa sổ, mọi lý do), và không có
bằng chứng đo được nào cho thấy 6 giây dùng chung gây vấn đề thật cho riêng ca `clarify`.

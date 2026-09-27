# ADR-028: cửa sổ nghe tiếp mở sau mọi lượt — bốn phanh và một luật im lặng

- Status: **Proposed** — chờ @thanhpro82 (PM/PO) duyệt
- Date: 2026-08-29
- Decision owner: WS Agent (Nhân)
- Liên quan: [#343](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/343) (cửa sổ nghe tiếp),
  [#363](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/363) (rào chắn mẫu ngữ pháp),
  [#355](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/355),
  [ADR-025](ADR-025-chap-hanh-tu-ngu-canh-hoi-lai.md) (ghép ngữ cảnh hỏi lại),
  [ADR-011](ADR-011-default-route-to-manual-lookup.md) (mặc định về tra sổ tay),
  spec `docs/superpowers/specs/2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md`,
  plan `docs/superpowers/plans/2026-08-29-cua-so-nghe-tiep.md`

## Context

Mục tiêu: **đừng bắt tài xế nói "Hey VIVI" trước mỗi câu.**

Đo phân bố kết cục lượt trên hai bộ thật nhất repo có (29/08, `develop` @ `88d6d85`):

```
bao-loi-2408 (77 ca dựng từ bảng báo lỗi thật)
    control 69 (89.6%)   not_control 6 (7.8%)   clarify 1 (1.3%)   denied 1 (1.3%)
manual/v1 (60 câu, workstream RAG soạn — không thiên vị router)
    not_control 59 (98.3%)   offer 1 (1.7%)
```

**~98% lượt là tự chứa.** Cả bộ máy ngữ cảnh đa lượt (#148 phần B, #367, #363) phục vụ
**1–2%**; còn *"mic tự mở lại sau mỗi lượt"* phục vụ **~89%**. Trọng số ban đầu của WS
Agent đặt sai, và ADR này sửa lại.

**Giới hạn của phép đo trên, phải nói ra:** cả hai bộ chỉ chứa **lượt đầu**, toàn câu trọn
vẹn viết ra giấy. Mic mở thường trực **đổi cách người ta nói** — ngắn hơn, tỉnh lược hơn.
Nên 1–2% có thể đang **đánh giá thấp**, và chính việc làm tính năng này có thể kéo nó lên.
Xem mục §Điều kiện đo lại.

### Lỗ chí mạng: bỏ điều kiện là bỏ luôn phanh

`FOLLOW_UP_WINDOW` (#343) có **đúng hai** lối ra: 6 giây im lặng, hoặc nghe thấy tiếng rồi
vào lượt mới. Mở sau **mọi** lượt thì vòng khép kín, và lối ra duy nhất là 6 giây im lặng
— thứ gần như không xảy ra trong xe có người ngồi cạnh đang nói chuyện.

#343 không gặp chuyện này vì `hasMoreToRead` **tự cạn**: đoạn sổ tay đọc hết là hết.

**Hậu quả tệ nhất không phải chạy nhầm lệnh.** Đo bằng graph thật, người nói với **người**:

```
"Lát nữa mở cốp lấy đồ nhé"   ->  VIVI: "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Hôm qua tôi bật đèn pha suốt"->  VIVI: "Tôi không tìm thấy thông tin này trong sổ tay xe."
```

Xe **chen vào cuộc nói chuyện của người**, vài giây một lần. Chạy nhầm một lệnh thì tắt đi
là xong; cái này khiến người ta tắt luôn trợ lý.

## Decision

**Mở cửa sổ nghe tiếp sau mọi lượt, nhưng chỉ khi backend nói "còn nghe tiếp", và luôn
trong một ngân sách cứng. Lượt bắt tự động mà xe không hiểu thì im lặng.**

### Phanh 1 — tín hiệu từ backend (`src/agents/nghe_tiep.py`)

FE chỉ nghe thấy **tiếng**; nó không phân biệt được `"mức 2"` với `"lát nữa mở cốp lấy đồ
nhé"`. Chỉ backend biết lượt vừa rồi xe **có hiểu gì không**.

`con_nghe_tiep(state)` đọc **kết cục cuối** của lượt và là **chủ sở hữu duy nhất** của
quyết định. Nó **không** nằm ở `route_node` vì `route_node` không thấy `completed` — mà
`completed` là ~90% lượt và là ca chính của cả tính năng.

Phân loại **tường minh cả 22 outcome**, không có "mặc định im lặng":

| mở | đóng |
|---|---|
| `completed`, `approval_granted`, `offer`, `grounded_answer`, `grounded_continue` | 18 mục còn lại |
| `clarify` **khi** lý do ∈ `mau_slot.CO_MAU` | `clarify` lý do khác |

### Phanh 2 — ngân sách cứng (FE, `WakeWordController`)

Phanh 1 dựa vào *"xe hiểu được"*. Nhưng một câu nói với NGƯỜI cũng có thể hiểu được: đo
29/08, `"Trời nóng quá bật điều hòa lên đi em"` ra `completed`. Nên cần trần **không phụ
thuộc nội dung**, và cần **cả hai nửa** vì mỗi nửa bịt một hình dạng khác:

- `MAX_CHAINED_FOLLOW_UPS = 5` — đếm lượt không chặn được chuỗi lượt **ngắn** kéo dài mãi;
- `FOLLOW_UP_SESSION_MAX_MS = 60_000` — đồng hồ không chặn được năm lượt dồn trong ba giây.

Cả ba phanh gộp vào **một cờ** trước khi xuống bảng chuyển trạng thái; bảng ấy giữ nguyên
là một hàm thuần.

### Phanh 3 — câu giải tán (`_la_cau_giai_tan`)

`"thôi"`, `"không cần"`, `"khỏi"` khi **không có gì đang chờ** → đóng, đáp `"Vâng."`.

Dùng lại `voice_intent.doc_tra_loi_co_khong`, **không** bảng từ thứ hai. Phạm vi hẹp hơn
spec một cách có chủ ý: `"cảm ơn"` bị **loại** vì thêm nó vào bảng từ chối là dạy cổng phê
duyệt HITL đọc một lời cảm ơn thành lời **bác một lệnh S2**, và vì `"Cảm ơn nhé"` là một ca
của `chitchat-v1` — bộ đo của workstream khác. Soát cả năm bộ đo: **0 ca bị nuốt**, có test
khoá ngược.

### Phanh 4 — nhìn thấy được, tắt bằng tay

Đã có sẵn từ #343: `followUpWindowActive` bật vòng đếm ngược quanh nút mic, hết giờ phát
beep trầm. Một chạm vào nút mic đóng cửa sổ.

### Luật im lặng

**Lượt bắt tự động mà xe không hiểu thì không nói gì** — `speak_text` rỗng, không phát
`assistant.speech`. Màn hình vẫn hiện: nó không làm phiền ai, và là dấu vết để tài xế hiểu
vì sao vòng đếm ngược vừa tắt.

Client báo qua header **`X-Capture-Mode: auto | manual`** (vắng = `manual`).

Luật nằm ở `ivi_events.cau_de_noi()` — chỗ **duy nhất** cả hai đường cùng đọc. Đây là chỗ
dễ sót nhất: `emit_turn_lifecycle` gọi TTS bằng **state**, không qua payload; sửa mỗi
payload thì WS im mà **loa vẫn đọc**.

## Rủi ro nhận

- **S1 chạy im lặng từ tiếng nói không nhắm vào xe.** Nhận, có trần bằng phanh 2 và bằng
  chính sách S0–S3: cửa/kính/ghế là S2/S3 nên phải qua phê duyệt hoặc bị chặn; chỉ S0/S1
  chạy im lặng, mà S0/S1 toàn là thứ đảo ngược trong một câu.
- **Tải STT tăng.** Mỗi lượt bắt tự động là một lần chạy STT + một lượt graph. Phanh 2 là
  thứ chặn nó khỏi vô hạn.
- **Trace lẫn lượt rác.** Vì thế `TraceRecord.bat_tu_dong` được thêm cùng ADR này — không
  phân biệt được thì bảng nhật ký mất tác dụng chẩn đoán.

## Phương án đã cân nhắc và bác

**Mở vô điều kiện sau mọi lượt.** Bác bằng phép đo: xe chen vào cuộc nói chuyện của người
bằng câu từ chối tra cứu, vài giây một lần.

**Chỉ siết khi FE khai `auto`.** Bác: đó là để **client tự khai** một cổng an toàn — một
build cũ hay một client khác là đủ để cổng biến mất trong im lặng. Rào chắn `mau_slot` vì
thế chạy trên **mọi** lượt.

**Gate bằng confidence.** Bác vì hệ **không có** tín hiệu ấy: `voice.py` hard-code `0.0`
cho STT, `contracts.py` để router `confidence = 1.0`. Gate bằng một số luôn bằng 1.0 là
gate bằng không gì cả. (Cùng kết luận với #363.)

**Để `route_node` tự tính cờ mở mic** (bản đầu của #363). Bác: nó không thấy `completed`.

**Tin `route_reason == "default_to_manual"` là "xe không hiểu".** Bác bằng phép đo: câu
`"Trong xe nóng quá giảm điều hòa xuống"` mang lý do ấy mà RAG **vẫn trả lời được**. Thứ
mang tin "không hiểu" là **outcome** `grounded_refusal`.

## Hệ quả

- `assistant.response` thêm `mo_mic_ngan:bool`; `POST /turns/voice` thêm header
  `X-Capture-Mode`. Cả hai **không** vào envelope HTTP đồng bộ (`extra="forbid"`), cùng
  lý do với `has_more_to_read`.
- ADR-025 đã hết hiệu lực giả định *"sau clarify mic không tự mở"* từ #363; ADR này mở
  cửa sổ rộng hơn nữa, và bốn phanh trên là thứ thay chỗ nó.
- **Thu hồi rẻ:** đặt `keepListening` thành `false` cứng ở `responseBoundary` là hệ quay
  về hành vi #343; `mo_mic_ngan` khi ấy chỉ là một trường thừa trong payload.

## Bằng chứng

Đo bằng **giọng người thật** qua WebSocket thật (`eval/datasets/poc/v1/audio`, 16 kHz mono):

```
dom-019 manual -> "Tôi không tìm thấy thông tin này trong sổ tay xe."  assistant.speech: True
dom-019 auto   -> speak_text=""                                         assistant.speech: False
dom-012 manual -> "Sổ tay ghi: Nhấn vào nút A/C…"   speech: True  mo_mic_ngan: True
dom-012 auto   -> như trên                                              (xe HIỂU thì vẫn nói)
```

Kiểm tay trong trình duyệt (wake word bật, real mode): cửa sổ mở sau lượt xong; nói một câu
không liên quan trong cửa sổ thì xe im; bấm mic tay rồi nói đúng câu ấy thì xe nói.

Suite backend **3151 passed**, FE **515 passed**, `--mode multiturn` `di_lui = 0`.

## Điều kiện đo lại — và nó là cổng cho việc tiếp theo

`scripts/do_phan_bo_luot.py` đo phân bố kết cục trên **lưu lượng thật** (đọc `GET /traces`,
không phải dataset viết tay). Hai con số:

- tỉ lệ lượt kết thúc ở `clarify`/`offer` — cầu cho cơ chế đa lượt;
- tỉ lệ lượt **bắt tự động** rơi vào `grounded_refusal` — chi phí của việc mở cửa sổ.

```
≈1–2%  ->  DỪNG, ba mục đa lượt còn lại (#355 mục 3, #339) không đáng làm
≳10%   ->  làm tiếp có cơ sở
```

**Chưa chạy được:** `GET /traces` và kho bền `trace_spans` nằm ở nhánh
`feat/dashboard-ky-su-nhat-ky-ben` (`4a16720`, `8a76e20`), chưa merge vào `develop`. Trên
`develop` `TraceStore` vẫn là LRU 200 bản ghi trong RAM. Script viết sẵn theo đúng hợp đồng
ấy và **báo rõ** khi endpoint chưa có, thay vì trả một con số sai.

Và nhắc lại điều dễ đọc nhầm: đây là **tỉ lệ mỗi lượt**. Một phiên 10 lượt ở mức 1,3% vẫn
có ~12% khả năng vấp ít nhất một lần, và khi vấp thì ban giám khảo thấy đúng cảnh xe tự hỏi
rồi tự bịt tai. Tần suất thấp **không** đồng nghĩa hậu quả thấp.

# Cửa sổ nghe tiếp mở sau mọi lượt — bốn phanh đóng và một luật im lặng

- Ngày: 2026-08-29
- Workstream: Agent (FE + BE đều thuộc làn này)
- Liên quan: [#343](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/343) (cửa sổ nghe tiếp),
  [#363](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/363) / [PR #373](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/373) (rào chắn mẫu),
  [#367](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/367) (khe `offer` treo),
  ADR-025, lộ trình `2026-08-23-lo-trinh-agent-theo-kich-ban.md` §11
- Plan: `docs/superpowers/plans/2026-08-29-cua-so-nghe-tiep.md`

## 1. Vấn đề, và vì sao nó không phải vấn đề đa lượt

Mục tiêu: **đừng bắt tài xế nói "Hey VIVI" trước mỗi câu.**

Đo phân bố kết cục lượt trên hai bộ thật nhất repo có (29/08):

```
bao-loi-2408 (77 ca dựng từ bảng báo lỗi thật)
    control 69 (89.6%)   not_control 6 (7.8%)   clarify 1 (1.3%)   denied 1 (1.3%)
manual/v1 (60 câu, workstream RAG soạn — không thiên vị router)
    not_control 59 (98.3%)   offer 1 (1.7%)
```

**~98% lượt là tự chứa**: xe hoặc làm, hoặc trả lời xong, và câu tiếp theo của tài xế là
một câu trọn vẹn. Cả bộ máy ngữ cảnh đa lượt (#148 phần B, #367, #373) phục vụ **1–2%**.

Nên thứ lấy được nhiều nhất, rẻ nhất, là **mic tự mở lại sau mỗi lượt** — không cần ngữ
cảnh nào. Máy trạng thái cho việc ấy **đã có** (`FOLLOW_UP_WINDOW`, #343); nó chỉ đang bị
khoá sau điều kiện `hasMoreToRead`.

**Giới hạn của phép đo trên, phải nói ra:** cả hai bộ chỉ chứa **lượt đầu**, và toàn câu
trọn vẹn viết ra giấy. Mic mở thường trực **đổi cách người ta nói** — ngắn hơn, tỉnh lược
hơn. Nên 1–2% có thể là đánh giá thấp, và mục §7 tồn tại để đo lại sau khi mở.

## 2. Lỗ chí mạng: bỏ điều kiện là bỏ luôn phanh

`FOLLOW_UP_WINDOW` hôm nay có **đúng hai** lối ra (`wakeWordState.ts`):

```
FOLLOW_UP_TIMEOUT         (6 s không ai nói)   ->  LISTENING_FOR_WAKEWORD
FOLLOW_UP_SPEECH_DETECTED                      ->  CAPTURING_COMMAND -> ... -> quay lại
```

Mở sau **mọi** lượt thì vòng khép kín, và lối ra duy nhất là **6 giây im lặng** — thứ gần
như không xảy ra trong xe có người ngồi cạnh đang nói chuyện.

#343 không gặp chuyện này vì `hasMoreToRead` **tự cạn**: đoạn sổ tay đọc hết là hết. Bỏ
điều kiện ấy là bỏ luôn cái phanh mà không thay phanh khác.

### Hậu quả tệ nhất không phải chạy nhầm lệnh

Đo bằng graph thật, người nói với **người**, mic đang mở:

```
"Lát nữa mở cốp lấy đồ nhé"            ->  VIVI: "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Hôm qua tôi bật đèn pha suốt"         ->  VIVI: "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Thôi tắt nhạc đi để anh nghe điện"    ->  VIVI: "Tôi không tìm thấy thông tin này trong sổ tay xe."
```

Xe **chen vào cuộc nói chuyện của người**, vài giây một lần. Chạy nhầm một lệnh thì tắt đi
là xong; cái này khiến người ta tắt luôn trợ lý.

Ca chạy nhầm cũng có thật, nhưng **có trần sẵn** nhờ chính sách S0–S3:

```
"Mở cửa cho anh ấy vào đi"             ->  control  set_door_state × 4   (S2/S3 -> phê duyệt hoặc chặn)
"Trời nóng quá bật điều hòa lên đi em" ->  control  set_hvac_power       (S1 -> chạy im lặng)
```

Chỉ S0/S1 chạy không hỏi, và S0/S1 toàn là thứ đảo ngược trong một câu.

## 3. Quyết định

**Mở cửa sổ nghe tiếp sau mọi lượt, nhưng chỉ khi backend nói "còn nghe tiếp", và luôn
trong một ngân sách cứng. Lượt bắt tự động mà xe không hiểu thì im lặng.**

### 3.1 Phanh 1 — tín hiệu "còn nghe tiếp" từ backend

FE chỉ nghe thấy **tiếng**; nó không phân biệt được `"mức 2"` với `"lát nữa mở cốp lấy đồ
nhé"`. Chỉ backend biết lượt vừa rồi xe **có hiểu gì không**. Nên phanh chính nằm ở BE.

`mo_mic_ngan` (đã có từ #373) **mở rộng nghĩa** thành "còn nghe tiếp", và **chuyển chỗ
tính** từ `route_node` sang `compose_node` — vì `completed` chỉ biết được sau khi thực thi.

| lượt kết thúc | `mo_mic_ngan` | vì sao |
|---|---|---|
| `completed` | `True` | vừa làm xong một việc, rất có thể còn việc nữa |
| `clarify` (lý do ∈ `CO_MAU`) | `True` | xe vừa hỏi, có rào chắn `mau_slot` |
| `offer` | `True` | xe vừa hỏi có/không, có khe `loi_de_nghi` |
| `manual_query` trả lời được | `True` | hội thoại đang chạy |
| `default_to_manual` / `grounded_refusal` | **`False`** | xe không hiểu — nhiều khả năng câu ấy không nói với xe |
| `manh_khong_khop_mau` | `False` | #373 đã chốt: nghe hụt thì trả quyền chủ động về tài xế |
| `offer_declined` / câu giải tán | `False` | tài xế vừa nói "thôi" |
| `blocked` / `denied` / `validation_denied` | `False` | không có gì để nối tiếp |

**Không giữ tên cũ là sai chỗ nào:** đổi tên field vừa ship ở #373 là churn vô ích, và
tên `mo_mic_ngan` vẫn đọc đúng nghĩa mới. Chỉ mở rộng tài liệu, không rename.

### 3.2 Phanh 2 — ngân sách cứng

Phanh 1 dựa vào "xe hiểu được". Nhưng `"Trời nóng quá bật điều hòa lên đi em"` nói với
**người** thì xe cũng hiểu được và cũng `completed`. Nên cần một trần **không phụ thuộc
nội dung**, ở FE:

- `MAX_CHAINED_FOLLOW_UPS = 5` — số lượt nối liên tiếp tối đa kể từ một lần "Hey VIVI";
- `FOLLOW_UP_SESSION_MAX_MS = 60_000` — trần đồng hồ tường cho cả chuỗi.

Chạm trần nào cũng về `LISTENING_FOR_WAKEWORD`. Bộ đếm reset ở `WAKE_DETECTED` và
`MANUAL_ACTIVATE`.

### 3.3 Phanh 3 — câu giải tán

`"thôi"`, `"cảm ơn"`, `"không cần"`, `"đủ rồi"` → đóng cửa sổ, **không** nói gì.

Dùng lại `voice_intent.doc_tra_loi_co_khong` — không viết bảng từ thứ hai. Chỉ áp dụng khi
**không có gì đang chờ**: một tiếng `"thôi"` khi có `offer` treo đã có nghĩa "từ chối đề
nghị" (#367) và khi có phê duyệt chờ đã có nghĩa "bác" — cả hai đường ấy chạy trước.

### 3.4 Phanh 4 — nhìn thấy được, tắt bằng tay

**Phần lớn đã có.** `DriverShellProvider` giữ `followUpWindowActive`, bật vòng đếm ngược
quanh nút mic khi `onFollowUpWindowStarted`, và `onFollowUpWindowExpired` phát beep trầm
đóng. Việc còn lại là kiểm rằng nó vẫn đúng khi cửa sổ mở thường xuyên hơn, và rằng một
chạm vào nút mic đóng được cửa sổ.

### 3.5 Luật im lặng khi bắt tự động

**Lượt bắt tự động mà xe không hiểu thì không nói gì cả** — không `assistant.speech`,
`speak_text` rỗng. Đây là thứ chặn cảnh xe chen vào cuộc nói chuyện ở §2.

Cần client báo *"lượt này bắt tự động"* qua header `X-Capture-Mode: auto | manual`
(vắng = `manual`, nên client cũ không đổi hành vi).

**Vì sao tin được lời khai của client ở đây, trong khi #373 từ chối tin:** khác về
**hướng**. Khai `auto` chỉ khiến xe **im hơn**, không bao giờ khiến nó **dễ dãi hơn**.
Client nói dối thì hậu quả là xe im lúc đáng nói — khó chịu, không nguy hiểm. Còn ở #373,
tin lời khai nghĩa là một build cũ có thể **xoá mất một cổng an toàn**.

Rào chắn `mau_slot` vẫn chạy trên **mọi** lượt, không phụ thuộc header này.

## 4. Cái không làm

- **Không** streaming audio. Backend vẫn nhận một WAV đã ghi xong cho mỗi lượt.
- **Không** đụng ba mục đa lượt còn lại (#355 mục 2b/3, #339) — chúng phục vụ một tỉ lệ
  chưa đo được; §7 là điều kiện để mở lại.
- **Không** đổi ngưỡng VAD hay `SILENCE_DURATION_MS`. Chúng học được từ phần cứng thật
  (`CLAUDE.md`), động vào là mở một mặt trận khác.
- **Không** rename `mo_mic_ngan`.

## 5. Bất biến phải giữ

1. Router vẫn tất định, không đọc trạng thái (ADR-006/010).
2. Mọi lệnh vẫn qua policy → safety → HITL. Cửa sổ nghe tiếp **không** đụng gì tới đường
   đó.
3. Rào chắn `mau_slot` chạy trên mọi lượt, không phụ thuộc `X-Capture-Mode`.
4. `has_more_to_read` là của **nhánh sổ tay**. Không được mượn nó để mở mic — đã có test
   khoá (`test_clarify_khong_mo_mic_bang_co_cua_nhanh_so_tay`).
5. `di_lui` của `multiturn-v1` phải bằng 0.

## 6. Rủi ro nhận

- **S1 chạy im lặng từ tiếng nói không nhắm vào xe.** Nhận, có trần bằng phanh 2 và bằng
  chính sách S0–S3. Ghi vào ADR.
- **Tải STT tăng.** Mỗi lượt bắt tự động là một lần chạy STT + một lượt graph. Phanh 2 là
  thứ chặn nó khỏi vô hạn.
- **Trace lẫn lượt rác.** Lượt bắt tự động phải ghi rõ `bat_tu_dong` để lọc được khi đọc
  `/traces`.

## 7. Điều kiện để làm tiếp phần đa lượt còn lại

Sau khi cửa sổ mở, **đo lại phân bố kết cục lượt** trên chính lưu lượng ấy (đọc từ
`TraceStore`, không phải từ dataset viết tay). Con số cần: tỉ lệ lượt kết thúc ở
`clarify`/`offer`, và tỉ lệ lượt bắt tự động rơi vào `default_to_manual`.

- ≈1–2% như hôm nay → **dừng**, ba mục còn lại không đáng làm.
- ≳10% → làm tiếp #355 mục 2b/3 có cơ sở.

Đây là ứng dụng trực tiếp bài học §9 của lộ trình: đừng sửa thứ mình chưa đo.

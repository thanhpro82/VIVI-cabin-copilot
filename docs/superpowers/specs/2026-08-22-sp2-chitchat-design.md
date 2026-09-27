# SP-2 — Năng lực trò chuyện thông thường (chitchat) — thiết kế

- Ngày: 2026-08-22
- Trạng thái: Đã duyệt qua brainstorming, chờ implementation plan
- Người quyết: Nhân
- Umbrella: `2026-08-21-slm-bo-nao-dinh-tuyen-design.md` §2 (SP-2 là sub-project thứ ba)
- Tiền đề: SP-1 đã merge (#232 + hotfix #242), SP-0 đã đo (#243, `docs/reports/sp0-do-tre-tung-doan-2026-08-22.md`)
- Liên quan: ADR-011, ADR-016, ADR-026

## 1. Bối cảnh

SP-1 đặt classifier 3 lớp vào nhánh trượt của router; lớp `chitchat` hiện trả câu giữ
chỗ `CHITCHAT_TAM_GIU` (`graph.py`). PM/PO ghi vào ADR-026: **chưa bật cờ cho người
dùng cho tới khi SP-2 có generator thật và bộ đo đủ ba lớp.** SP-2 đóng đúng hai điều
kiện đó.

Ba dữ kiện từ SP-0 mà thiết kế ăn theo:

- Union prompt có sẵn đã sinh được chitchat khá tự nhiên ở ~1,1 s (p95 2,2 s), kể cả từ
  chối mềm đúng kiểu ("Tôi không thể kiểm tra thời tiết được").
- **4/15 câu chitchat không bao giờ tới classifier**: luật `manual_question` (dấu hỏi,
  "gì") bắt "Xin chào, hôm nay khỏe không?" thành câu hỏi sổ tay → `grounded_refusal`.
- Ngân sách chitchat trong cấu hình hai server ≈ classify 1,6 s + sinh 1,1 s.

Quyết định đã chốt ở umbrella và giữ nguyên: phạm vi = xã giao + chuyện quanh xe/chuyến
đi; ngoài phạm vi (tin tức, thời tiết, toán, kiến thức chung) → từ chối mềm; lọc chữ
Hán; bộ đo ~40 ca.

## 2. Kiến trúc

```
route (luật) ── manual_question CHỈ KHI câu có từ vựng về xe ──► rag
   │                                                   (đổi duy nhất ở router)
   └─ default_to_manual ──► slm_classify (SP-1)
                               ├─ control  → slm planner (như SP-1)
                               ├─ manual   → rag
                               └─ chitchat → chitchat_node  ← MỚI, thay CHITCHAT_TAM_GIU
                                                │
                                  QwenChitchat.reply(text)   một lượt gọi, prompt riêng,
                                                │             json_schema {"reply": str ≤ 240}
                                      cổng tất định 4 lớp (thứ tự cố định)
                                                │
                                             compose (outcome="chitchat", chitchat_reply)
```

### 2.1 Generator — prompt riêng, một lượt gọi (phương án đã chọn)

Bác hai phương án khác: *dùng lại union prompt* (800 token prefill cho một việc đã biết
trước, và model vẫn có thể trả plan cho câu chitchat — "Hát một bài đi" → planner 9,4 s
ở SP-0); *mẫu câu tất định* (0 ms, không bịa, nhưng không phải trò chuyện và đi ngược
quyết định "SLM là phải dùng").

`QwenChitchat` sống trong `src/agents/slm.py` cạnh ba vai kia, cùng endpoint
`SLM_ENDPOINT` (trong cấu hình hai server là dGPU cùng planner — hai vai không xen kẽ
trong một lượt nên không trả phí đổi vai), timeout riêng `SLM_CHITCHAT_TIMEOUT_S = 4.0`
(p95 đo được 2,2 s), `temperature` thấp nhưng **không** 0 (trò chuyện lặp y hệt nhau
giữa các lượt nghe như máy; đặt 0.3 và ghi lý do), `json_schema {"reply": string,
maxLength 240}` — grammar đồng thời chặn thinking mode của Qwen3 như ở classify.

Prompt (~250 token, ChatML):

```
Bạn là VIVI, trợ lý giọng nói trên xe VinFast. Trả lời tài xế bằng ĐÚNG MỘT
câu tiếng Việt ngắn, thân thiện, tự nhiên như đang nói chuyện.
Bạn chỉ trò chuyện về: xã giao, cảm xúc của tài xế, chuyến đi và đường xá.
Ngoài phạm vi đó (tin tức, thời tiết, toán, kiến thức chung) thì nói thật
rằng bạn không làm được việc này, rồi gợi ý hỏi về xe hoặc điều khiển xe.
Tuyệt đối KHÔNG: nêu thông số kỹ thuật của xe, nói rằng đã bật/tắt/làm gì
trên xe, dùng tiếng Anh hay chữ Hán.
[4–5 ví dụ]
```

Hai ví dụ bắt buộc, khoá hai ranh giới đo được ở SP-0: *"Ngày mai có mưa không ta"* →
từ chối mềm + gợi ý; *"Xe này chạy được bao nhiêu km một lần sạc?"* → **không nói số**,
chuyển sang "để tôi tra sổ tay cho chính xác".

### 2.2 Cổng tất định sau model — bốn lớp, thứ tự cố định

Cổng là chỗ **duy nhất** chặn bịa; tất định, mỗi lớp một test riêng, vỡ lớp nào cũng
rơi về câu mẫu tất định (không bao giờ trả chuỗi model đã bị chặn):

| # | lớp | cách đo | rơi về |
|---|---|---|---|
| a | hệ chữ lạ (Hán, Kirin, Kana…) | `src/rag/tu_nhien.py` — **dùng lại**, không viết mới | câu mẫu chung |
| b | quá dài | > 240 ký tự (trùng `MAX_SPOKEN_CHARS`) → cắt ở ranh giới câu; không có ranh giới → câu mẫu | — |
| c | dữ kiện kỹ thuật | `_NUMBER_WITH_UNIT` (`speech_policy.py`) — số kèm đơn vị | câu chuyển hướng "về thông số, để tôi tra sổ tay cho chính xác" |
| d | nói đã làm gì trên xe | regex `đã (bật\|tắt\|mở\|đóng\|đặt\|chỉnh\|phát\|dừng)` | câu mẫu chung |

Lỗi hạ tầng / timeout / JSON hỏng → câu mẫu chung. Câu mẫu chung là chữ tự viết, không
mang dữ kiện: *"Tôi nghe bạn đây. Bạn muốn tôi giúp gì trên xe không?"*

### 2.3 Router: `manual_question` chỉ khi câu có từ vựng về xe

Đổi duy nhất ở `router.py`: nhánh `is_information_question(text)` / `is_question(...)`
→ `manual_question` chỉ khi `co_tu_vung_xe(text)`. Không dính mục nào thì câu rơi xuống
`default_to_manual` → classifier quyết.

`_TU_VUNG_XE` là **danh sách đóng ~60 mục**, curate từ `docs/coverage_matrix.md` + 58
section của sổ tay (điều hòa, ghế, lốp, pin, sạc, phanh, gương, cốp, gạt nước, chìa
khóa, bảo dưỡng, camera, bluetooth, màn hình, dây an toàn, túi khí, đèn, kính, cửa,
nhạc, âm lượng, VinFast, VF, xe…). Ghi ở `src/agents/question.py` vì nó là tri thức
"câu này có nói về xe không", không phải luật điều khiển.

**Bằng chứng bắt buộc trước khi merge:** 41/41 câu `hoi-nhu-tai-xe-v1` và mọi câu
`manual` của `dinh-tuyen-v1` vẫn đi đường tắt (cột `duong_tat` của eval không giảm);
4/4 câu chitchat có dấu hỏi của SP-0 tới được classifier.

Bác phương án *danh sách chào hỏi đi đường tắt chitchat* (chỉ đỡ mẫu có liệt kê) và
*để nguyên* (27% câu xã giao không bao giờ được trả lời xã giao).

### 2.4 Đơn lượt

Chitchat không đọc lịch sử phiên (YAGNI). #217 đang làm "nhớ ngữ cảnh hỏi lại" cho
control; chitchat đa lượt là việc sau, nếu user research đòi.

### 2.5 Cấu hình, cờ, dấu vết

- Cùng cờ `SLM_ENABLED` — không thêm cờ; `SLM_ENABLED=false` ⇒ graph giao hệt develop
  (test khoá như SP-1).
- `route_reason` giữ `slm_classified_chitchat`; thêm `chitchat_cong` vào kết quả graph
  (`qua` / tên lớp vỡ / `loi`) để eval và trace tách được lượt nào rơi về câu mẫu.
- Độ trễ sinh chitchat tính vào stage `planning_or_retrieval` (node chitchat bọc
  `_timed` với tên này — **không** đặt tên stage mới, bài học #242).
- Câu giữ chỗ `CHITCHAT_TAM_GIU` xoá khi node mới vào.

## 3. Bộ đo `eval/datasets/agent/chitchat-v1` — 40 ca, 4 nhóm, hai nhãn

| nhóm | n | `expected_route` (classifier) | `expected_hanh_vi` (generator) |
|---|---:|---|---|
| xã giao | 10 | chitchat | `xa_giao` |
| quanh xe / chuyến đi, không dữ kiện | 10 | chitchat | `tro_chuyen` — không thông số |
| ngoài phạm vi (thời tiết, tin, toán, chuyển khoản) | 10 | chitchat | `tu_choi_mem` + gợi ý |
| bẫy: giống chitchat nhưng là control/manual | 10 | control / manual | `khong_toi_generator` |

Nguồn, để không lặp bài học `agent/v3` (đề tự ra = tripwire). Đã kiểm khi viết spec:
log Discord của buổi test 20–21/08 **không nằm trong repo** (`docs/2108/` chỉ có trên máy
Sơn), và 67 câu trích trong báo cáo điều tra đều là câu lệnh/bàn lỗi, không có câu xã
giao nào — nên không được viện dẫn nó làm nguồn. Nguồn thật:

- 15 câu chitchat đã dùng và đo ở SP-0 (`source: sp0`);
- **15 câu xin từ hai thành viên khác** (Sơn, Thành — mỗi người một lượt "nói với xe
  như nói với người" không cần biết hệ thống làm gì; `source: <tên>`), là phần độc lập
  duy nhất của bộ đo — plan có một task gửi yêu cầu và chờ;
- 10 câu nhóm bẫy tự viết (`source: tu_viet`) — **chỉ là tripwire**, mọi trích dẫn
  kết quả phải nói rõ.

Nếu 15 câu độc lập chưa về kịp khi chấm tay, báo cáo chấm trên 25 ca và ghi rõ thiếu
nguồn độc lập; **không** tự viết bù rồi gọi là độc lập. Nhóm bẫy nhập luôn vào
`dinh-tuyen-v1` làm phần ba lớp còn thiếu (cập nhật README ở đó).

Trường: `case_id`, `input_text`, `expected_route`, `expected_hanh_vi`, `source`.

## 4. Cách chấm — hai tầng, không trộn

**Máy** (mode `--mode chitchat`, run dir `eval/results/chitchat/<run-id>/`):

- Ma trận 3 lớp đầy đủ của classifier trên 61 + 40 ca. Cổng cứng cũ
  `manual→control = 0` giữ nguyên; **cổng cứng mới `bẫy→chitchat = 0`** (không câu
  control/manual nào lọt vào generator).
- Tỷ lệ qua từng lớp cổng (a–d) và tỷ lệ rơi về câu mẫu.
- p50/p95 của `classify + sinh` trên 30 ca chitchat thật; đích ≤ 3 s / ≤ 4,5 s (SP-0
  §3), báo số — cổng CI đặt sau khi nhóm chốt cấu hình hai server.

**Người** (một lần trước khi mở PR, `graded_by: human`, tiền lệ `graded_speech.jsonl`):
30 ca chitchat thật, ba ô có/không — *đúng phạm vi*, *từ chối đúng chỗ*, *nghe tự
nhiên*. Không đặt ngưỡng trước, báo số thật. Bất kỳ ca nào bịa dữ kiện về xe mà cổng
(c) không bắt được là **lỗi cổng** — sửa cổng, không sửa prompt.

## 5. Xử lý lỗi

- Server chết / timeout / JSON hỏng → câu mẫu chung, `chitchat_cong = "loi"`; lượt không
  treo, không 500 (test có `trace_id`, bài học #242).
- Cổng vỡ → câu mẫu tương ứng, ghi tên lớp; không bao giờ phát chuỗi đã bị chặn.
- Classifier đúng chitchat nhưng câu thật ra là control ("Hát một bài đi"): generator
  *có thể* trả lời xã giao sai — đó là lỗi của ranh giới, đo ở nhóm bẫy; không vá ở
  generator.

## 6. Ngoài phạm vi SP-2

- Chitchat đa lượt / nhớ ngữ cảnh.
- Dùng chitchat thay câu từ chối của nhánh sổ tay (`grounded_refusal` giữ nguyên).
- Gỡ `kind: chitchat` khỏi union prompt của planner (đường `not_control` cũ vẫn dùng;
  SP-2 chỉ thêm đường, không gỡ đường).
- Cấu hình hai server + `SLM_CLASSIFY_ENDPOINT` (đề xuất SP-0, chờ nhóm chốt — SP-2
  chạy được với một server, chỉ chậm hơn).

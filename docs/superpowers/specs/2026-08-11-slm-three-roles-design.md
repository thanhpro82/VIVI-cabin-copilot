# Đưa mô hình ngôn ngữ vào hệ thống — thiết kế ba vai trò

**Trạng thái:** Thiết kế, chờ duyệt.
**Nhánh:** `feature/spike-003-slm-feasibility`, tách từ `develop` tại `ce6382f`.
**Ngày:** 2026-08-11
**Ticket:** Tích hợp SLM (planner fallback + trò chuyện; composer theo ADR-015 riêng).
**Sơ đồ đã duyệt:** artifact "Ba vai trò của mô hình ngôn ngữ trong VIVI".

## Vì sao làm lại việc mà SPIKE-001 đã đánh trượt

SPIKE-001 kết luận **Not Yet** (ADR-005) và kết luận đó đúng với thí nghiệm của nó. Nhưng
bốn tiền đề của thí nghiệm đó đã đổi, kiểm được từng cái:

1. **Nhiệm vụ đã nhỏ đi.** SPIKE-001 bắt model sinh `plan_id`, `vehicle_state_version`,
   `requires_approval` và tự phân loại `safety_level` (schema tại
   `experiments/.../llm.py:17-72`). Kiến trúc hiện tại **cấm** model làm bốn thứ đó —
   `CandidateActionPlan` chỉ còn `{schema_version, steps[{step_id, ordinal, tool, args,
   depends_on}]}`, phần còn lại thuộc `materialize_action_plan` tất định (ADR-006).
   System prompt tương ứng nhỏ đi 3,8× (1817 → 483 ký tự).
2. **Chưa dùng ràng buộc giải mã.** SPIKE-001 gửi `response_format` dạng
   `json_object` + schema; kết quả schema validity 55–70% cho thấy ràng buộc đó không
   thực sự hoạt động. llama.cpp có grammar (GBNF / `json_schema` chuyển server-side)
   bảo đảm **đúng cấu trúc theo kiến tạo** — với một cảnh báo: không bảo đảm *sinh
   xong* nếu hết `n_predict` giữa chừng.
3. **Chưa dùng phần cứng sẵn có.** SPIKE-001 chạy `-t 4`, thuần CPU. Máy demo là Ryzen 5
   5600H (6 nhân/12 luồng) + **Radeon RX 5500M 4 GB GDDR6, băng thông ~192 GB/s** —
   gần gấp đôi Jetson Orin Nano. Decode của LLM bị chặn bởi băng thông bộ nhớ, nên đây
   là đòn bẩy lớn nhất chưa đo. Binary hiện có (`llama-b9637-bin-win-cpu-x64`) là bản
   CPU-only — GPU chưa từng được thử.
4. **Prompt lặp lại chưa được cache.** Prefix tĩnh (system prompt + few-shot) chỉ cần
   prefill một lần nếu bật prompt cache của llama-server. Điều này làm few-shot — đòn
   bẩy độ chính xác số một trước khi nghĩ tới fine-tune — gần như miễn phí về độ trễ.

**Phần của SPIKE-001 vẫn còn nguyên giá trị và không được bỏ qua:** phân tách kiểu lỗi.
Trên 10 case control của 3B: 2 hỏng schema, **2 schema đúng nhưng chọn sai tool**; của
0.5B: 2 hỏng schema, **5 chọn sai tool**. Grammar chỉ đóng được cột schema. Cột chọn-sai-
tool là rào thật, grammar không giúp, và vì thế **độ chính xác là rủi ro số một của spike
này, không phải độ trễ**.

## Ba vai trò — và thứ mỗi vai trò được phép chạm tới

| | ① Planner | ② Composer (ADR-015) | ③ Trò chuyện |
|---|---|---|---|
| Sinh ra | JSON `CandidateActionPlan` | Văn xuôi có căn cứ sổ tay | Văn xuôi tự do |
| Chạm được vào xe | Có — **qua cổng** `validate → safety → HITL → execute` | Không | Không |
| Hỏng thì sao | Chọn sai tool; cổng vẫn chặn | **Bịa nội dung sổ tay** — không lớp nào đỡ | Trả lời vô duyên |
| Grammar giúp | Có | Không | Một phần (vỏ JSON) |

An toàn của ② và ③ đến từ **kiến trúc** (không có đường tới executor), không đến từ chất
lượng model — nên tính chất đó không hỏng khi đổi model.

**Thứ tự làm: ③ → ① → ②.** Trò chuyện trước vì rủi ro thấp nhất, sửa một lỗi nhìn thấy
ngay ("Cảm ơn nhé" → "Tôi chưa rõ bạn muốn điều khiển gì"), và buộc dựng xong toàn bộ hạ
tầng đo mà chưa phải cược vào độ chính xác chọn tool. Composer cuối cùng, chờ ADR-015
được duyệt, vì lỗi của nó là loại duy nhất không nhìn thấy được.

## Quyết định thiết kế trung tâm: ① và ③ là MỘT lần gọi

Cả hai cùng nằm trên nhánh `not_control` — router đã bó tay. Tách hai node thì phải có
thứ gì đó phân loại "lệnh hay tán gẫu" trước, mà thứ duy nhất làm được lại là model:
hỏi hai lần, trả giá độ trễ hai lần.

Thay vào đó, một lần gọi với grammar hợp nhất ràng buộc output vào **đúng hai hình dạng**:

```
{"kind":"plan","schema_version":"1.0","steps":[…]}   → parse_candidate → validate → …
{"kind":"chitchat","reply":"…"}                       → compose, không chạm executor
```

`kind` quyết định đường đi trong graph — không có chuỗi tự do nào được đoán nghĩa sau.
Grammar không cho phép hình dạng thứ ba tồn tại.

Tích hợp (Phase 2, plan riêng): `slm_stage` trong `graph.py:176` parse discriminated
union thay vì chỉ `parse_candidate`; thêm outcome `"chitchat"`; `compose_node:93` thêm
nhánh đọc reply từ state thay vì tra `OUTCOME_MESSAGES`. Vòng đời giữ nguyên: một lần
sửa schema, hết thì `clarify`.

**Ràng buộc cho nhánh chitchat:** `n_predict` chặn trần độ dài; reply đi qua strip +
giới hạn ký tự trước khi tới TTS. Rủi ro tồn đọng (ghi nhận, chưa có chặn tất định):
model có thể *nói như đã làm* ("Đã bật điều hòa") dù không tool nào chạy — giảm thiểu
bằng prompt và bằng việc FE hiển thị lượt chitchat không kèm badge hành động; nếu spike
cho thấy xảy ra thật thì thêm bộ lọc mẫu câu trước khi phát.

## SPIKE-003 — bậc thang đo, mỗi bậc có tiêu chí dừng

Nguyên tắc: **phép thử rẻ nhất có khả năng loại trừ chạy trước.** Không mua, không thuê
phần cứng nào trước khi bậc A trả lời "GPU sẵn có có chạy được không".

| Bậc | Đo gì | Dừng nếu |
|---|---|---|
| **A. Tốc độ thô** | prefill/decode tok/s: {CPU -t 6, CPU -t 12, Vulkan -ngl 99} × {0.5B, 3B} trên model sẵn có | Vulkan không nhận RX 5500M **và** CPU decode < 12 tok/s với 3B → 3B chết trên máy này, chỉ còn đường model nhỏ |
| **B. Grammar + cache** | overhead grammar; `prompt_ms` lần gọi thứ 2 với cùng prefix (kỳ vọng ≈ 0) | grammar làm decode chậm > 30% hoặc cache không ăn prefix → tính lại ngân sách few-shot |
| **C. Chất lượng trên bộ dò** | kind-accuracy (plan/chitchat), tool-accuracy trên phần plan, latency p50/p95 end-to-end | tool-accuracy < 70% trên bộ dò dù đã few-shot → dừng ①, chỉ ship ③, ghi nhận cần dữ liệu thật |
| **D. RAM/VRAM** | peak RSS server + RSS backend khi chạy đồng thời faster-whisper | tổng vượt 7,4 GB RAM vật lý → bắt buộc GPU-only hoặc model nhỏ |

Ứng viên bậc A là hai model **đã có trên đĩa, đã có `.sha256`** — không tải gì mới.
Model mới (họ Qwen3, Apache-2.0, sạch hơn Qwen Research license của 2.5-3B) chỉ tải khi
bậc A/C cho thấy cần, mỗi lần đúng một profile có pin checksum, theo đúng kỷ luật
`download_models.ps1`.

Bằng chứng ghi vào `eval/results/spike-003/<UTC-run-id>/` — bất biến, có manifest ghi
build llama.cpp, flags, sha256 model, timings tách prefill/decode (SPIKE-001 chỉ đo
tổng wall time, không tách được — lỗi đo lường phải sửa).

## Bộ dò (probe set) — cách 3, ghi giới hạn ngay từ đầu

Người viết bộ dò **đã đọc `router.py`**, nên theo đúng chuẩn mà README của
`eval/datasets/agent/v3` đặt ra, đây là **bộ dò để phát hiện hỏng hóc, không phải bằng
chứng năng lực tổng quát hóa**. Không con số nào từ bộ này được trình bày như
user-facing accuracy. Thay bằng dữ liệu thu từ người dùng thử khi sản phẩm demo được —
quyết định của nhóm ngày 2026-08-11.

Cấu tạo: ~50–60 câu, chỉ giữ câu mà router thật trả `not_control` (lọc bằng script,
không tin cảm giác); gắn nhãn `expected.kind` và, với `kind=plan`, tool+args kỳ vọng.
Phủ: cách nói lệch khuôn của 9 tool, câu xã giao, câu ngoài phạm vi xe.

## Cổng chấp nhận — cần ADR mới, không tự nới

Cổng SPIKE-001 (p50 ≤ 2,5 s) đặt cho planner **chính** chạy mọi lượt. Đường này giờ là
**fallback**: không có nó tài xế nhận ngay "nói lại giúp tôi"; có nó tài xế chờ thêm để
được việc. Ngân sách trễ chấp nhận được cho fallback là **quyết định sản phẩm**, sẽ đề
xuất bằng số đo thật của SPIKE-003 trong **ADR-016** để nhóm chốt — không mặc định tái
dùng cổng cũ, cũng không tự nới cho dễ đạt.

`/healthz`: `llm` đang được miễn trừ khỏi gate (issue #48, `b2e5724`). Giữ nguyên miễn
trừ trong suốt spike; chỉ xem xét lại trong ADR-016 nếu ship.

## Ngoài phạm vi

- **Fine-tune/LoRA**: chỉ đặt lên bàn khi có câu nói thật từ người dùng thử. Fine-tune
  trên dữ liệu do người-đã-đọc-router sinh ra rồi đo bằng dữ liệu cùng nguồn là con số
  đẹp và vô nghĩa.
- **Speculative decoding**: cần RAM cho 2 model; chỉ xét sau bậc D nếu còn dư.
- **Composer (②)**: chờ ADR-015 được duyệt; mọi kết quả model của spike này là đầu vào
  cho quyết định đó.
- **Phần cứng mới (Jetson/QDC)**: chỉ khi bậc A thất bại, và mua/thuê bằng số đo, không
  bằng cảm giác. PC ≠ target device — không mở trục claim mới.
- Sửa `README`/`CLAUDE.md` về trạng thái LLM: chỉ khi ship, cùng ADR-016.

## Rủi ro

1. **Chọn sai tool là rào thật** — grammar không sửa được; few-shot là đòn bẩy duy nhất
   còn lại trước fine-tune. Bậc C có tiêu chí dừng riêng cho nó.
2. **Vulkan trên RDNA1 là ẩn số** — không tìm được benchmark công khai nào cho RX
   5500M; toàn bộ lập luận băng thông là lý thuyết cho tới khi bậc A chạy.
3. **Grammar không bảo đảm sinh xong** — hết `n_predict` giữa chừng vẫn cho JSON cụt;
   `parse_candidate` đã chặn, nhưng phải đếm tần suất trong bậc C.
4. **Bộ dò nhiễm tri thức router** — đã ghi giới hạn; mọi claim từ nó phải mang nhãn
   "probe, not evidence".

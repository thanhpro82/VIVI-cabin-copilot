# SPIKE-003 — SLM trên máy demo: khả thi, và vì sao SPIKE-001 trượt

**Ngày:** 2026-08-11 · **Nhánh:** `feature/spike-003-slm-feasibility`
**Thiết kế:** `docs/superpowers/specs/2026-08-11-slm-three-roles-design.md`
**Sổ tay số liệu + run-id:** `docs/reports/SPIKE-003-notes.md`; run bất biến tại `eval/results/spike-003/`.

## Kết luận một đoạn

Cùng model Qwen2.5-3B Q4, cùng máy, lượt planner-fallback đi từ **11,2 s (SPIKE-001)
xuống 0,99 s** — không phải nhờ model mới hay phần cứng mới, mà nhờ đường phần mềm:
GPU Vulkan thay CPU 4 luồng (decode 9,3 → 63 tok/s), grammar hợp nhất chặn output
đúng chỗ, và prompt cache trả chi phí few-shot đúng một lần. Chất lượng trên bộ dò:
kind 0,906 / tool 0,828 (nhãn **PROBE-NOT-EVIDENCE**). **Khuyến nghị: GO cho Phase 2**
(tích hợp vai trò ③ trò chuyện + ① planner qua một lần gọi), chờ nhóm duyệt ADR-016.

## Số chính theo bậc

| Bậc | Kết quả | Tiêu chí dừng |
|---|---|---|
| A — tốc độ thô | 3B: cpu6 9,3 → **vulkan 63,0 tok/s** (6,8×); 0.5B: 38 → 164,5; SMT gây hại (cpu12 < cpu6) | Không kích hoạt |
| B — grammar + cache | Tổ hợp đủ: **p50 877 ms / p95 1.000 ms**; grammar −5% decode trong tổ hợp; cold prefix 2.058 ms trả một lần, sau đó ~140 ms/call; truncation 0 | Không kích hoạt |
| C — chất lượng (bộ dò 64 câu) | 3B few-shot v2: **kind 0,906 / tool 0,828 / parse_fail 0**, p50 992 ms; 0.5B: kind 0,875 nhưng **tool 0,345** | Không kích hoạt (3B); 0.5B chỉ đủ vai trò ③ |
| D — RAM đồng thời | Server + backend peak ~3,1 GB (**thiếu STT** — model không có trên máy; trần tham chiếu SPIKE-001: +1,6 GB) | Không kích hoạt, đo lại khi có STT |

## Vì sao SPIKE-001 trượt — trả lời có bằng chứng

1. **Đo trên nhiệm vụ nặng hơn nhiệm vụ thật.** SPIKE-001 bắt model sinh `plan_id`,
   `requires_approval`, `safety_level` — kiến trúc hiện tại cấm model làm và giao cho
   policy tất định. So sánh trực tiếp accuracy hai spike vì thế **không hợp lệ**; chỉ
   cột hạ tầng (tok/s cùng model cùng máy) so được.
2. **Bỏ không GPU.** `-t 4` CPU trong khi máy có RX 5500M; decode bị chặn bởi băng
   thông bộ nhớ nên đây là nhân tố 6,8×.
3. **Ràng buộc giải mã không hoạt động.** `response_format` kiểu json_object cho
   schema validity 55–70%; grammar GBNF cho parse_fail 0/64 ở cấu hình chốt.
4. **Không cache prefix.** System prompt 519 token prefill lại mỗi call.

Điều SPIKE-001 nói đúng và vẫn đúng: **chọn sai tool là rào thật** — 0.5B đo lại vẫn
chỉ 0,345 tool-accuracy dù đã grammar + few-shot. Grammar sửa được *vỏ*, không sửa
được *lựa chọn*.

## Giới hạn — đọc trước khi trích số

- Mọi số chất lượng đến từ **bộ dò cách-3** (`eval/datasets/probe/v1`): người viết đã
  đọc `router.py`. Nó phát hiện hỏng hóc, không chứng minh năng lực tổng quát. Thay
  bằng dữ liệu người dùng thử khi demo được (quyết định nhóm 2026-08-11).
- Failure mode đã quan sát (few-shot v1): "kể chuyện cười" → thoái hoá lặp ký tự CJK
  tới trần token — grammar giữ vỏ JSON nhưng không cứu nội dung. Hết ở v2; ghi vào
  ADR-016 làm rủi ro tồn đọng của vai trò ③.
- Bậc D thiếu STT; con số 3,1 GB là sàn, không phải tổng.
- Qwen2.5-3B mang **Qwen Research license** — dùng học thuật được, không được trình
  bày như lựa chọn production; ứng viên Apache-2.0 (họ Qwen3) là việc tiếp theo nếu
  nhóm cần sạch license, đo lại bằng đúng bậc thang này.

## Việc tiếp theo

1. Nhóm duyệt **ADR-016** (dự thảo kèm PR này) — cổng fallback + các câu vận hành.
2. Phase 2 (plan riêng): tích hợp một-lần-gọi vào `slm_stage`, outcome `chitchat`,
   compose đọc reply; `slm_enabled` giữ mặc định off tới khi ADR chốt.
3. Tải model STT để đóng nốt bậc D; cân nhắc ứng viên Apache-2.0.

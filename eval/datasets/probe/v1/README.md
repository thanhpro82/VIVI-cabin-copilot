# Bộ dò SLM v1 — PROBE, NOT EVIDENCE

64 case, chỉ gồm câu mà `DeterministicControlRouter` **thật** trả `not_control`
(lọc bằng `scripts/spike3_probe_filter.py`, không tin cảm giác; bản nháp 65 câu,
router bắt được đúng 1 — `"Mở giùm cái cửa bên tài"` → `clarify`).

## Nguồn gốc — đọc trước khi trích bất kỳ con số nào

Người viết bộ này **đã đọc `src/agents/router.py`**. Theo đúng chuẩn mà README của
`eval/datasets/agent/v3` đặt ra, số đo trên bộ này là **độ nhạy của bộ dò**, không
phải năng lực tổng quát hóa trên câu nói tự do. Không được trình bày như user-facing
accuracy, trong báo cáo phải mang nhãn `PROBE-NOT-EVIDENCE`.

Quyết định nhóm 2026-08-11: dữ liệu thu từ người thật chỉ làm khi sản phẩm demo được
cho người ngoài dùng thử; tới lúc đó bộ này bị thay thế cho mọi mục đích đánh giá.

## Cấu tạo

| Nhóm | Số câu | expected |
|---|---:|---|
| `P-CMD` — lệnh nói lệch khuôn, phủ 9 tool (mỗi tool ≥ 2) | 29 | `kind=plan` + `tool` |
| `P-SOC` — xã giao: chào, cảm ơn, tán gẫu | 15 | `kind=chitchat` |
| `P-OOS` — ngoài phạm vi xe (kiến thức chung, việc ngoài xe) | 10 | `kind=chitchat` (từ chối nhẹ) |
| `P-AMB` — bẫy mơ hồ giữa lệnh và tán gẫu | 10 | `accept_kinds=["plan","chitchat"]` |

Scorer (`scripts/spike3_quality.py`) chấm **`kind`** trên cả bộ và **`tool` của step
đầu** trên nhóm plan; `args` không chấm ở spike này (validation args thuộc
`validate_args` lúc tích hợp).

## Chạy

```powershell
# lọc lại khi sửa nháp
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe scripts\spike3_probe_filter.py <draft> > cases.jsonl
# đo chất lượng (cần llama-server đang chạy — xem scripts/spike3_server.ps1)
.\.venv\Scripts\python.exe scripts\spike3_quality.py <model.gguf> vulkan
```

# ADR-010: Tool registry canonical + adapter tương thích Product Vision spec

- Status: **Accepted (phần safety) · phần adapter alias đã bị thu hồi 2026-08-08**
- Date: 2026-08-08
- Decision owner: WS2 Agent/RAG (tracker "Xây dựng Agent LangGraph + 5 Tools" và "Triển khai luồng HITL trong LangGraph")

> ## Thu hồi phần adapter — 2026-08-08
>
> Quyết định số **1** dưới đây (bảng alias `ALIAS_BY_TOOL` phơi tên nhóm của Họ A)
> và số **4** (phơi song song hai route quyết định HITL) **đã bị thu hồi** ngay
> trong ngày, theo phán quyết của trưởng nhóm trên PR #23.
>
> Lý do: ADR này được viết để hoà giải mâu thuẫn Họ A/Họ B mà **không kiểm xem
> nhóm đã chốt hướng nào chưa**. Thực tế WS4 đã chốt trước đó một ngày —
> `frontend/docs/ARCHITECTURE.md` (commit `cfec7dc`, 2026-08-07) ghi rõ dùng
> `docs/api_spec.md` làm nguồn sự thật **duy nhất** cho endpoint và loại
> `/agent/process` đích danh. Lớp adapter vì vậy không có consumer nào.
>
> **Còn hiệu lực:** quyết định số **2** (phân loại an toàn theo
> `safety_and_hitl.md`, **không** theo ngưỡng `speed_kph > 5` của ticket) và số
> **3** (timeout mặc định 30 giây). Đây mới là phần quan trọng của ADR, và nó
> không phụ thuộc bảng alias.
>
> **Hệ quả đã thực hiện:** `ALIAS_BY_TOOL` bị xoá; HTTP response dùng tên tool
> canonical; SCRUM-18 dùng `POST /api/v1/approvals/{approval_id}/decision`, không
> làm `POST /api/v1/hitl/confirm`; `/agent/process` thành dev-only
> (`include_in_schema=False`, 404 ở production).

## Context

Repo có hai bộ tài liệu mô tả cùng một hệ thống nhưng **không khớp nhau**:

- **Họ A — Product Vision / high-level PRD**: [`docs/VIVI_API_Spec.md`](../VIVI_API_Spec.md).
  File này tự khai báo ở dòng đầu: *"KHÔNG dùng file này làm spec kỹ thuật để
  lập trình/implement."*
- **Họ B — Canonical Engineering Specs**: [`docs/agent_spec.md`](../agent_spec.md),
  [`docs/safety_and_hitl.md`](../safety_and_hitl.md), [`docs/api_spec.md`](../api_spec.md),
  [`docs/data_model.md`](../data_model.md), có [ADR-006](ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md)
  làm authority.

Ticket của sprint này ("Xây dựng Agent LangGraph + 5 Tools", "Triển khai luồng
HITL") được viết bám theo Họ A. Bốn điểm mâu thuẫn trực tiếp:

| Điểm | Họ A (ticket) | Họ B (canonical) |
|---|---|---|
| Tên tool | `control_ac`, `control_music`, `control_window`, `control_seat`, `navigation` | `set_hvac_power`/`set_hvac_temperature`, `media_control`, `set_window_position`, `set_seat_heating`/`set_seat_position`, `set_navigation` |
| Điều kiện HITL | `speed_kph > 5` | Window **luôn** S2; door/seat position là S2 chỉ khi `speed_kph == 0 && gear == P`, ngoài predicate đó là **S3 (chặn, không HITL)** |
| Timeout approval | 5 giây | 30 giây (mặc định) |
| Endpoint quyết định | `POST /api/v1/hitl/confirm` với `{hitl_action_id, confirmed}` | `POST /api/v1/approvals/{approval_id}/decision` |

Điểm quan trọng nhất là **điều kiện HITL**, vì hai luật không chỉ khác nhau về
con số mà **lệch nhau về hướng an toàn theo hai chiều ngược nhau**:

- Với **cửa kính**: luật `speed > 5` **lỏng hơn**. Xe đứng yên, luật Họ A cho
  hạ kính chạy thẳng không hỏi; Họ B bắt buộc hỏi.
- Với **cửa xe**: luật `speed > 5` **nguy hiểm hơn**. Xe chạy 60 km/h, luật Họ A
  hiện popup "bạn có chắc không?" — tức là *cho phép* mở cửa nếu người dùng bấm
  đồng ý. Họ B phân loại đó là S3 và chặn trước khi tạo approval; không có
  bypass, kể cả khi user yêu cầu hoặc đã có approval.

Đây là prototype mô phỏng, không nối CAN/ECU, nên không có rủi ro vật lý thật.
Nhưng `docs/safety_and_hitl.md` là tài liệu chấm điểm và là contract mà WS3
(Vehicle/Safety) đang implement; để router và policy lệch khỏi nó thì test an
toàn của WS3 và của WS2 sẽ mâu thuẫn nhau ở tầng tích hợp.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Implement đúng nguyên văn Họ A | Khớp ticket 100%, không cần văn bản giải thích, ít code nhất | Vi phạm trực tiếp `safety_and_hitl.md` §Classification rules và §Required safety tests #6/#12; test an toàn số 6 và 12 sẽ fail theo thiết kế; deliverable mở cửa xe khi đang chạy trở thành hành vi được phép sau xác nhận |
| Implement đúng Họ B, coi ticket là sai | Sạch nhất về mặt contract | Deliverable ghi trong ticket (`POST /api/v1/hitl/confirm`, tên 5 tool) sẽ không tồn tại; người ra ticket và frontend đang bám tên Họ A sẽ hỏng |
| **Lõi Họ B + lớp adapter mỏng phơi tên/route Họ A** (đã chọn) | Giữ nguyên contract an toàn đã chốt ở ADR-006; vẫn giao đúng deliverable ticket yêu cầu; frontend không phải đổi | Có hai tên cho cùng một thứ — cần quy ước rõ tên nào đi vào `ActionPlan` (canonical) và tên nào chỉ sống ở tầng API |

## Decision

**Lõi hệ thống dùng Họ B. Thêm một lớp adapter mỏng ở tầng API để phơi tên và
route theo Họ A.**

Cụ thể:

1. **Tool registry canonical là Họ B.** `ActionPlan`, `CandidateActionPlan`,
   trace và audit chỉ chứa tên canonical (`set_hvac_temperature`, …). Bảng alias
   Họ A (`control_ac` → `{set_hvac_power, set_hvac_temperature}`, …) nằm trong
   `src/agents/tools/__init__.py` và **chỉ** được dùng khi dựng HTTP response.
   Alias không bao giờ là giá trị hợp lệ của trường `tool` trong một plan.

2. **Phân loại an toàn theo `safety_and_hitl.md`, không theo ngưỡng 5 km/h.**
   - `set_window_position` → S2 ở mọi tốc độ.
   - `set_door_state`, `set_seat_position` → S2 chỉ khi `speed_kph == 0 && gear == P`;
     ngoài predicate là S3 và bị chặn trước khi tạo approval.
   - Ngưỡng `5 km/h` trong ticket **không được implement như điều kiện kích hoạt**.
   - Tốc độ hiện tại vẫn được đưa vào câu hỏi xác nhận để giữ đúng UX mà ticket
     mô tả (ví dụ: "Xe đang chạy 45 km/h. Bạn có chắc chắn muốn mở hết cửa kính
     không?"). Đây là **nội dung hiển thị**, không phải điều kiện phân loại.

3. **Timeout mặc định 30 giây**, đọc từ `Settings.hitl_timeout_seconds`. Giá trị
   trong ticket (5s) là cấu hình hợp lệ cho demo IVI, không phải hằng số trong code.

4. **Phơi cả hai route, chung một service.**
   - `POST /api/v1/hitl/confirm` với body `{hitl_action_id, confirmed}` — đúng
     ticket, là route mà IVI dùng.
   - `POST /api/v1/approvals/{approval_id}/decision` — đúng `api_spec.md`.
   - Cả hai gọi cùng một hàm quyết định; `hitl_action_id` **là** `approval_id`,
     không phải hai định danh khác nhau.

## Rationale

- `docs/safety_and_hitl.md` §Required safety tests liệt kê 19 test bắt buộc, trong
  đó #6 ("Door/seat position là S2 chỉ khi `speed_kph == 0 && gear == P`") và #12
  ("Window luôn được phân loại S2") mâu thuẫn không thể hòa giải với ngưỡng
  `speed > 5`. Quality gate của file đó ghi: "bất kỳ unauthorized execution nào là
  release blocker". Chọn ngưỡng 5 km/h là tự tạo ra một release blocker.
- Ticket mô tả **deliverable** (`/api/v1/hitl/confirm`, `hitl_action_id`, 5 nhóm
  tool) chứ không mô tả **cơ chế phân loại**. Adapter thỏa mãn toàn bộ phần
  deliverable mà không phải nhượng bộ phần cơ chế.
- Giá trị `5s` và `speed > 5` trong Họ A là ví dụ minh họa trong một tài liệu
  tự khai báo là không dùng để implement — coi chúng là contract là đọc sai vai
  trò của tài liệu.

## Consequences

- Response của `POST /api/v1/agent/process` chứa `tool_calls[].tool_name` ở dạng
  alias Họ A, trong khi trace và `ActionPlan` chứa tên canonical. Người đọc log
  cần biết bảng ánh xạ; bảng đó là một hằng số duy nhất trong
  `src/agents/tools/__init__.py`, không được nhân bản.
- Một lệnh "mở cửa xe" khi `speed_kph > 0` trả về **blocked**, không phải
  `PENDING_HITL`. Đây là khác biệt hành vi quan sát được so với ticket; frontend
  phải xử lý cả hai trạng thái.
- Một lệnh "hạ kính" khi xe **đứng yên** vẫn trả `PENDING_HITL`. Ticket ngụ ý
  trường hợp này chạy thẳng; nó không chạy thẳng.
- `hitl_action_id` và `approval_id` là cùng một giá trị. Nếu sau này tách ra, cả
  hai route và ADR này phải sửa cùng lúc.
- ADR này **không** authorize thay đổi `docs/VIVI_API_Spec.md`. File đó giữ nguyên
  vai trò Product Vision; mâu thuẫn được giải ở tầng implementation, không bằng
  cách sửa tài liệu tầng trên.

## Scope boundary — những thứ ADR này KHÔNG quyết

- **`search_nearby_poi` và hệ `PlanningResolution`** (lease, candidate digest,
  effectively-once) mô tả trong `agent_spec.md` **không** nằm trong sprint này.
  `set_navigation` chỉ nhận `destination_id` có sẵn trong fixture; validator từ
  chối `destination_ref`. Khi nào làm POI thì cần ADR/spec riêng.
- **Voice / STT / TTS** không thuộc sprint này (`docs/adr/ADR-008` và WS1 sở hữu).
  Không có node nào trong graph gọi `src/services/voice.py`.
- **Vai trò của Qwen2.5-3B q4**: xem mục "Slm planner" trong
  [spec thiết kế agent graph](../superpowers/specs/2026-08-08-agent-graph-vehicle-tools-design.md).
  Ticket ghi Qwen là "mô hình suy luận chính"; `agent_spec.md` §Agent boundary
  chốt deterministic-first và SPIKE-001 kết luận **Not Yet** cho cả hai ứng viên
  Q4 (fail hard gate). Sprint này implement Qwen làm **fallback cho câu mơ hồ/hiếm**
  qua một port inject được, không phải planner chính. Chưa có bằng chứng chạy
  weight thật.

## Revisit when

- Người ra ticket hoặc chủ sở hữu `docs/VIVI_API_Spec.md` phản đối việc bỏ ngưỡng
  `speed > 5` — khi đó cần sửa `docs/safety_and_hitl.md` trước, không phải sửa code trước.
- Frontend chốt không cần alias Họ A nữa → gỡ lớp adapter, giữ route canonical.
- Có bằng chứng benchmark thật cho Qwen2.5-3B q4 vượt hard gate của SPIKE-001 →
  cân nhắc lại vai trò planner.

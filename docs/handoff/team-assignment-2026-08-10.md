# Phân công team P-192 — chốt ngày 2026-08-10

> **Đây là ảnh chụp để đọc ở standup, không phải tài liệu sống.** Chi tiết theo từng
> interface và event nằm ở `docs/handoff/frontend-integration-map.md` — chỗ nào hai
> file lệch nhau thì **tin file kia**.
>
> Nguồn: PR SCRUM-54/55 (4 commit, đã push) + review của Nhân ngày 10/08.

---

## Tóm tắt một bảng

| Người | Đang giữ | Trạng thái | Đang chặn ai |
|---|---|---|---|
| **Sơn** | Xe ảo, MQTT, vehicle state | ✅ Xong, chờ merge | Không ai |
| **Nhân** | HITL, RAG, **+ auth/sessions/turns-text** | ⏳ Nhiều việc nhất | **Giáp**, ở hai chỗ |
| **Thành** | `/ws/ivi`, `ivi_events.py`, `/turns/voice`, **`/healthz`** | ✅ Đã merge (PR #34) | Cần xác nhận có giữ tiếp `/ws/ivi` không |
| **Giáp** | IVI Screen, Engineer Dashboard | ⏳ Bị chặn ngoài ý muốn | Không ai |

---

## Sơn — xong, chờ merge

**Ticket:** SCRUM-54 (Vehicle State API), SCRUM-55 (MQTT E2E Test).
Nhân đã review và ủng hộ merge; bốn điểm nêu ra đều đã xử lý.

**Sở hữu tiếp:** `src/vehicle_sim/`, `src/services/{mqtt_*,vehicle_state,tool_executor,vehicle_gateway}.py`,
`src/mqtt_topics.py`, `GET /vehicle/state`, `/ws/engineer` (kênh `state`).

**Đã giao ra:**
- `VehicleGateway` — cổng chung, 2 implementation, contract test chạy qua cả hai.
- 3 tài liệu bàn giao: bản đồ tích hợp, hướng dẫn migrate cho Nhân, hợp đồng cho Giáp.
- ADR-013 ghi quyết định và cái giá của nó.

**Nợ trong vùng mình:** tầng L3 (`scripts/e2e_mqtt.py`) chưa viết;
`mqtt_spec.md:471` mô tả `phase: accepted → completed` mà simulator chỉ phát một
event — cần chốt là bug hay simplification P0.

---

## Nhân — nhiều việc nhất, và là mắt xích chặn Giáp

**Sở hữu:** `src/agents/**`, `src/api/approvals.py`, `src/rag/**`, `GET /citations/{id}`.

**Nhận thêm ngày 10/08:** `POST /auth/login`, `POST /sessions`, `POST /turns/text`.
Design đã viết — token mờ in-memory, chủ thể là **phiên đăng nhập** chứ không phải
người dùng (với một hồ sơ mặc định duy nhất, gắn quyền sở hữu vào người dùng thì
mọi phép kiểm đều trả về đúng cho tất cả, tức không đóng được gì).

**Việc cụ thể, xếp theo mức chặn người khác:**

1. `/auth/login` + `/sessions` — **chặn nặng nhất.** `authHeaders()` và
   `currentSessionId()` throw ngay khi thiếu token/session, nên `/ws/ivi` cũng
   không kết nối. Không có hai cái này thì **mọi endpoint đã xong đều vô dụng.**
2. `/turns/text` — mọi nút bấm trong IVI của Giáp gọi endpoint này.
3. Phát `plan.ready` — thiếu thì HITL modal của Giáp hiện "Bạn xác nhận: ?" rỗng.
4. Nối agent graph vào `VehicleGateway` — không có bước này thì `GET /vehicle/state`
   vẫn **không đổi sau lệnh giọng nói**, dù endpoint đã đúng hợp đồng.
   Hướng dẫn: `docs/handoff/vehicle-gateway-for-agent.md` (8 điểm migrate + 4 bẫy
   đã verify hộ).
5. `observed_state_version` vào `ToolResult`; sửa vỏ lỗi `turns.py:54` bằng
   `ApiError`; đảo bất biến state per-session → toàn cục (nhớ ghi JOURNAL — đây là
   đảo ngược có chủ đích, không phải sửa bug).
6. RAG composer tổng hợp câu trả lời; thêm `citation_id`; `GET /citations/{id}`.

---

## Thành — cần một câu trả lời

> **`GET /healthz` là của Thành.** Sơn và Thành cùng làm endpoint này mà không ai
> biết; PR #34 của Thành merge trước, bản của Sơn bị bỏ khi rebase. Giữ bản Thành
> vì nó tách tầng tốt hơn và **đúng spec hơn ở vỏ 503**. Chi tiết ở
> `docs/reports/SCRUM-54-55-status-and-ownership.md` mục 10.
>
> Một việc nhỏ còn thiếu: route chưa khai `responses={503: ...}` nên `/docs` đang
> nói `/healthz` chỉ trả 200. Ba dòng, mẫu có sẵn ở `src/api/routes.py`.

**Đã làm và đã merge:** `src/services/ivi_events.py`, handler `/ws/ivi` trong
`src/api/ws.py`, `POST /turns/voice`.

> Bảng sở hữu cũ của Sơn ghi nhầm phần này là của Nhân. Nhân phát hiện khi review,
> git xác nhận cả 6 commit đều của Thành. Suýt nữa Nhân dựng lại từ đầu đúng những
> thứ đã có.

**Ba khoảng trống, xếp theo mức nghiêm trọng:**

1. **`IviEventBus` không có buffer/replay** — không listener nào đang nối thì sự
   kiện bị vứt. Rớt mạng đúng lúc chờ duyệt là **mất luôn `approval.required`**,
   người dùng kẹt mà không biết có gì cần xác nhận. Cái này chạm thẳng luồng HITL
   của Nhân.
2. **`AUTH_ENABLED` là cờ ma** — `grep src/config.py` không có. Docstring `ws.py`
   tự thú hệ quả: bất kỳ client nào cũng nghe được sự kiện của bất kỳ `session_id`
   nào nó khai ra. Liên quan trực tiếp tới PR auth của Nhân.
3. **`sequence` tăng theo kết nối, không theo phiên** (`ws.py:41`) — reconnect là
   số nhảy về 1, client mất khả năng phát hiện sự kiện bị bỏ lỡ. Khó chịu nhưng
   không mất dữ liệu.

**Cần quyết:** giữ tiếp tầng `/ws/ivi` hay bàn giao cho Nhân. Đây là câu hỏi treo
duy nhất chặn việc phân công tiếp.

---

## Giáp — ba việc làm được ngay, không chờ ai

1. **`doors` là `"open"` / `"closed"`**, không phải `"unlocked"` / `"locked"`. Ba
   chỗ đang đọc sai: `Car3DViewer.tsx:67-69`, `VehicleControlView.tsx:121`,
   `RightPanel.tsx:13-15`. Không sửa thì xe 3D không bao giờ mở cửa và nút "Mở
   khoá" bấm xong không thấy gì đổi.
2. **Xử lý HAI shape cho `/healthz`** — nhánh 200 là `data.components[name].latency_ms`,
   nhánh 503 là `error.details.dependencies[name].code`. Khác cả tên khoá lẫn field,
   và đó là đúng spec.
3. **Thêm `.catch()` cho `refreshVehicleState()`** (`DriverShellProvider.tsx:69-71`)
   — với 503 nó thành unhandled rejection và `vehicleState` kẹt `null`.

Chi tiết + ví dụ JSON: `docs/handoff/BE-to-FE-vehicle-and-mqtt.md`.

Chạy backend không cần Mosquitto: để `MQTT_ENABLED=false` thì `GET /vehicle/state`
vẫn trả 200 với xe in-process. Xem hợp đồng ở `http://localhost:8000/docs`.

**Đang bị chặn bởi Nhân** ở `/auth/login`, `/sessions`, `/turns/text`, `plan.ready`.

---

## Chưa ai nhận

| Việc | Hậu quả nếu bỏ trống |
|---|---|
| `GET /metrics/summary` | Engineer Dashboard của Giáp trắng |
| `/ws/engineer` phát `trace` / `metrics` / `health` | như trên — FE đang bỏ qua `state` mà Sơn phát |
| Event `ui.policy` | IVI không có chế độ xe-đang-chạy. Đây là **cờ an toàn** (6 cờ UI khi xe chạy), không phải trang trí — `api_spec.md:575` cấm client tự suy |
| `GET /traces/{id}` | Không ai gọi — nên cân nhắc bỏ khỏi P0 cho gọn |

---

## Ba việc chốt ở standup

1. **Thành xác nhận** giữ tiếp `/ws/ivi` hay bàn giao. Câu hỏi treo duy nhất chặn
   phân công.
2. **Chốt `/healthz` + `llm`.** Nó sẽ **luôn trả 503** vì `llm` không tồn tại ở P0
   (ADR-005 "Not Yet", `slm_enabled=False`). Đây **không phải bug** — backend không
   báo `ready` cho thứ không chạy. Hai lối: (a) Giáp lọc `llm` khỏi AlertBanner kèm
   ghi chú, hoặc (b) sửa `api_spec.md` cho `llm` optional ở P0 kèm ADR.
3. **Gán chủ cho `/metrics/summary` và `trace`.** Không có thì một trong hai ticket
   của Giáp không thể xong.

---

## Tài liệu

| File | Dùng khi nào |
|---|---|
| `docs/handoff/frontend-integration-map.md` | **Nguồn chi tiết** — 12 interface, 20 event, mục ĐÃ RÕ và CHƯA RÕ |
| `docs/handoff/vehicle-gateway-for-agent.md` | Nhân migrate agent sang cổng |
| `docs/handoff/BE-to-FE-vehicle-and-mqtt.md` | Giáp cắm frontend vào phần của Sơn |
| `docs/reports/SCRUM-54-55-status-and-ownership.md` | Báo cáo AC + bằng chứng + nợ |
| `docs/adr/ADR-013-single-vehicle-state-source.md` | Vì sao một nguồn state, và cái giá |

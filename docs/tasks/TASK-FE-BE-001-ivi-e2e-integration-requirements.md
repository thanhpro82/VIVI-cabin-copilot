# TASK-FE-BE-001 — FE cần gì từ BE để làm "Tích hợp IVI Screen end-to-end"

Nguồn hợp đồng đầy đủ: [`docs/api_spec.md`](../api_spec.md) (12 interface P0). File này chỉ tóm tắt phần **đang thiếu/sai** mà FE đang bị chặn, để mỗi người biết chính xác việc của mình — không lặp lại toàn bộ spec.

FE (`frontend/src/lib/services/turn/real.ts`) đã viết sẵn khớp đúng contract. Chỉ cần BE trả đúng shape, FE bật `NEXT_PUBLIC_USE_MOCK_TURN=false` là chạy được ngay — **đã xác nhận bằng test tay end-to-end hôm nay, xem mục 2**.

> Đối chiếu thêm: [`docs/handoff/frontend-integration-map.md`](../handoff/frontend-integration-map.md), [`docs/handoff/BE-to-FE-vehicle-and-mqtt.md`](../handoff/BE-to-FE-vehicle-and-mqtt.md), [`docs/handoff/team-assignment-2026-08-10.md`](../handoff/team-assignment-2026-08-10.md). Bảng phân công trong file cuối **đang ghi sai chủ** cho auth/sessions/turns-text (ghi Nhân, thực tế PR #37 do Thành làm — chính Nhân nêu ra trong PR #36) — chưa ai sửa lại 2 file `handoff/`, đừng tin cột "ai giữ" ở đó cho 3 route này.

## Cập nhật hiện trạng (2026-08-10, cuối ngày — sau PR #36/#37/#38/#40 merge + test tay end-to-end)

| Mục | Trạng thái | Chủ |
|---|---|---|
| `POST /api/v1/auth/login` | ✅ **Merged** (PR #37) — test tay xong, đúng shape | Thành |
| `POST /api/v1/sessions` | ✅ **Merged** (PR #37) — test tay xong, đúng shape | Thành |
| `POST /api/v1/turns/text` | ✅ **Merged** (PR #37) — test tay xong S1, đúng envelope | Thành |
| Nối agent graph vào `VehicleGateway` (AC2 — state đổi thật sau lệnh) | ✅ **Merged** (PR #36) — test tay xác nhận `hvac.temperature_c` đổi 27→22 qua `/turns/text` rồi phản ánh đúng ở `GET /vehicle/state` | Nhân |
| `plan.ready` (event `/ws/ivi`) | ✅ **Merged** (PR #36) — phát cho mọi lượt điều khiển | Nhân |
| `GET /healthz` (8 component) | ✅ Merged (PR #34) | Thành |
| `GET /api/v1/vehicle/state` (+ `seat`, `doors` đúng `open`/`closed`) | ✅ Merged (PR #32) | Sơn |
| `WS /ws/ivi`, `POST /turns/voice` | ✅ Merged trước đó | Thành |
| 3 bug FE (WS subprotocol, 2 unhandled rejection, healthz 2-shape) | ✅ Đã sửa (PR #35) | Giáp |
| Điều khiển ghế lái (sưởi + vị trí) ở FE | ✅ Đã làm (PR #39, mock-only — chưa cần real vì `seat` không nằm trong nhóm chặn task này) | Giáp |
| `POST /api/v1/approvals/{id}/decision` | 🟡 **Viết lại (PR #36)**, kiến trúc đổi hẳn — xem mục 3, không còn là "sai shape đơn giản" nữa | Nhân |
| `doors`/`seat` mapping sai ở FE (`Car3DViewer.tsx`, `VehicleControlView.tsx`, `RightPanel.tsx`) | 🔴 **Vẫn chưa sửa** — biết từ 2026-08-09, chưa đụng | Giáp |
| `citation_id` + shape `citations`, RAG composer câu trả lời | 🔴 Chưa làm | Nhân |
| `GET /api/v1/metrics/summary` | 🔴 Chưa ai nhận | — |
| `WS /ws/engineer` phát `trace`/`metrics`/`health` | 🔴 Chưa ai nhận | — |
| Event `ui.policy` (6 cờ an toàn xe-đang-chạy) | 🔴 Chưa ai nhận | — |
| Bug `engineer_stream` (`src/api/ws.py`) ném exception chưa bắt khi client ngắt kết nối giữa chừng | 🔴 Vẫn còn, chưa ai nhận sửa | Cần xác nhận ai giữ `/ws/engineer` |
| `/healthz` luôn 503 vì `llm` down | ⚪ Không phải bug — **cần cả team chốt** (a)/(b) | — |
| Hydration warning ở `<html>` khi mở `/driver` | ✅ Không phải bug — do browser extension, xác nhận bằng incognito | — |

**Domino chặn nặng nhất trong task này đã gỡ.** 3 route auth/sessions/turns-text + việc nối agent vào VehicleGateway — 4 thứ từng liệt là "chưa code" trong các bản trước — nay đã merge và verify thật, không chỉ đọc code suông.

---

## 1. Đã giải quyết trong PR #35 (Giáp, phía FE)

Ba lỗi xuất hiện khi bật `NEXT_PUBLIC_USE_MOCK_ENGINEER=false` và test tay với backend thật:

**1. `Uncaught SyntaxError: Failed to construct 'WebSocket'`** — `btoa()` sinh base64 có padding `=`, không hợp lệ trong `Sec-WebSocket-Protocol` (RFC 6455) và trái `api_spec.md:503` (đòi base64url). Thêm `frontend/src/lib/services/shared/ws.ts` (`toBase64Url()`), áp dụng ở `engineer/real.ts` và `turn/real.ts`.

**2 & 3. `unhandledRejection` ở `getMetricsSummary()`/`getHealth()`** — `EngineerShellProvider.tsx` gọi 2 hàm này bằng `.then()` không có `.catch()`. Thêm `.catch()` để lỗi không rơi ra console mà giữ state `null`, UI tự hiện placeholder.

**Sửa thêm cùng lúc — `getHealth()` bỏ sót nhánh 503**: `/healthz` trả **hai shape khác nhau** giữa 200 (`data.components`, có `latency_ms`) và 503 (`error.details.dependencies`, không có `latency_ms`/`checked_at`) — cố ý theo `api_spec.md:495`. Sửa `mapHealthFromErrorDetails()` để đọc cả hai nhánh.

Test: `tsc --noEmit` sạch, `eslint` 0 error, `vitest` 11/11 pass, test tay qua Next.js DevTools overlay.

---

## 2. Test tay end-to-end hôm nay — xác nhận domino auth→session→turn hoạt động thật

Chạy backend thật (`develop` HEAD sau PR #36/#37/#38/#40, `MQTT_ENABLED=false`), gọi trực tiếp bằng script (không qua FE) để cô lập đúng contract BE, không lẫn lỗi FE:

```
POST /api/v1/auth/login       {email: driver.demo@example.com, password: DemoDriver123!}
  → 200, data.access_token/token_type="Bearer"/expires_at/user{...} — khớp 100% shape FE đọc ở session/real.ts

POST /api/v1/sessions         Authorization: Bearer <token>
  → 200, data.session_id/vehicle_id/status/started_at — khớp shape FE

POST /api/v1/turns/text       {session_id, text: "Bật điều hòa 22 độ"}
  → 200, data.action_plan.steps = [set_hvac_power, set_hvac_temperature], data.response.display_text — khớp
     đúng shape đã ghi trong file này trước đây (mục "Đang chặn task" cũ)

GET /api/v1/vehicle/state (trước lệnh): hvac = {power: true, temperature_c: 27.0}
GET /api/v1/vehicle/state (sau lệnh):   hvac = {power: true, temperature_c: 22.0}  ← ĐÃ ĐỔI THẬT
```

**Đây là bằng chứng trực tiếp rằng bug "hai nguồn trạng thái xe song song"** (Sơn phát hiện 2026-08-09, Nhân đóng bằng PR #36 AC2) **đã hết** — lệnh giọng nói/text giờ đổi đúng state mà `GET /vehicle/state` đọc lại được.

Một điểm cần lưu ý khi BE khác test lại: **chỉ số ban đầu của xe (`27.0°C`) không phải mặc định factory** — có vẻ giữ lại từ lượt test trước do state giờ là **global** (ADR-013), không reset theo request mới. Không phải bug, chỉ là hành vi cần biết khi viết test/demo (mỗi lần restart server mới về default thật).

Lệnh S2 (`"Mở cửa sổ bên tài 50 phần trăm"`) bị router trả `assistant.status: clarify` (hỏi lại) thay vì lập plan — chưa dò ra đúng cú pháp máy nhận diện trong thời gian test, **chưa kết luận được gì** về luồng S2/approval qua REST — cần người khác test lại với câu đúng cú pháp hoặc qua UI thật (mock đã biết đúng cú pháp, xem `turn/mock.ts` regex).

---

## 3. `POST /api/v1/approvals/{id}/decision` — không còn "sai shape" mà là kiến trúc mới hẳn (PR #36)

Bản cũ (fix đơn giản từng ghi trong file này) đã lỗi thời. PR #36 viết lại toàn bộ theo đúng `api_spec.md:209`: **quyết định đồng bộ, thực thi bất đồng bộ**.

- Route giờ chỉ trả `{"approval_status": "approved"|"rejected"|...}` — **còn đơn giản hơn trước**, không có `plan_status`/`tool_results` nữa. Vẫn **không có envelope** `{data, meta, trace_id, schema_version}` — về mặt kỹ thuật vẫn lệch `api_spec.md`.
- **Nhưng không còn chặn FE**: theo đúng thiết kế PR ghi rõ, `frontend/src/lib/services/turn/real.ts` `decideApproval()` trả `Promise<void>` và **không đọc body response** — mọi kết quả thật (approve xong, lệnh chạy xong) đẩy qua `/ws/ivi` (`turn.completed`/`tool.result`...), không qua REST response nữa. Nên thiếu envelope ở route này **không phải bug chặn** — chỉ là chưa 100% khớp spec chữ nghĩa.
- Thực thi chạy nền (`background_tasks.add_task`) — bấm "Đồng ý" giờ trả lời ngay thay vì đứng hình chờ cả chuỗi lệnh chạy xong. Đây là đổi UX thật, tốt hơn trước.

**Vẫn nên vá cho đúng spec** (không gấp, không chặn task này): bọc envelope chuẩn để route này nhất quán với 11 interface còn lại, phòng trường hợp sau này có client khác (không phải FE web) hoặc test hợp đồng tự động dựa trên `api_spec.md`.

---

## 4. Còn lại — gửi đúng theo người

### Nhân

- **`citation_id` + shape `citations`, RAG composer tổng hợp câu trả lời** — hiện chỉ trả `excerpt` thô, chưa có composer thật.
- **Bọc envelope chuẩn cho `POST /approvals/{id}/decision`** (mục 3) — không gấp.

### Chưa ai nhận — cần chốt tên ở standup

- `GET /api/v1/metrics/summary` — Engineer Dashboard trắng nếu thiếu. Bắt buộc đủ 7 nhóm (`window, turns, stage_latency_ms, mqtt, rag, safety, action_audit`) vì `engineer/real.ts` destructure cứng — thiếu 1 nhóm là lỗi.
- `WS /ws/engineer` phát thêm `trace`/`metrics`/`health` — hiện chỉ có `state`/`error`.
- Event `ui.policy` — 6 cờ an toàn khi xe đang chạy (`api_spec.md:575` cấm FE tự suy).
- Bug `src/api/ws.py:79-83` (`engineer_stream`): `except (WebSocketDisconnect, ValueError): await websocket.close(...)` — nếu socket đã disconnect thì chính `close()` ném lỗi mới, không ai bắt, log traceback rác phía server khi client ngắt kết nối giữa chừng (dễ gặp ở dev do React StrictMode mount/unmount 2 lần). Không sập server nhưng cần bọc `try/except` quanh `close()`. Chưa rõ nộp cho ai — bảng phân công chỉ chuyển `/healthz` + `/ws/ivi` sang Thành, không nói rõ `/ws/engineer`.

### Cần cả team chốt, không phải lỗi kỹ thuật

**`/healthz` gần như luôn 503 vì `llm` down.** `slm_enabled=False`, ADR-005 "Not Yet" — P0 chạy hoàn toàn bằng luật tất định, không LLM nào chạy, nên backend báo đúng sự thật. Hai lối, cần chọn 1: (a) Giáp lọc `llm` khỏi AlertBanner; (b) sửa `api_spec.md` cho `llm` optional ở P0, kèm ADR. **Đừng tự chọn (a) một mình** — quyết định hợp đồng, không phải UI.

### Giáp — việc của chính mình, vẫn còn tồn

`doors` là `"open"`/`"closed"`, không phải `"unlocked"`/`"locked"` — 3 chỗ đọc sai, vẫn chưa sửa:

- `Car3DViewer.tsx:67-69` — `isDoorVisuallyOpen(status) { return status === "unlocked" }`
- `VehicleControlView.tsx:121` — `const locked = vehicleState?.doors[pos.key] !== "unlocked"`
- `RightPanel.tsx:13-15`, `VehicleControlView.tsx:27-29` — `anyDoorUnlocked()`

Xác nhận lại bằng test tay hôm nay: `GET /vehicle/state` thật vẫn trả `"closed"` cho mọi cửa — 3 chỗ trên vẫn đọc theo `"unlocked"` nên xe 3D sẽ không bao giờ mở cửa khi cắm real mode. **Giờ đã hết lý do trì hoãn** vì auth/session/turns-text đã xong — bật real mode toàn bộ là thấy lỗi này ngay.

---

## Đã đúng, không cần đụng

- `GET /api/v1/vehicle/state`, `GET /healthz`, `WS /ws/engineer` (kênh `state`), `WS /ws/ivi`, `POST /turns/voice`, `POST /auth/login`, `POST /sessions`, `POST /turns/text` ✅

## Không nằm trong scope task này (chưa cần gấp)

`GET /api/v1/traces/{id}` — không ai gọi, cân nhắc bỏ khỏi P0 cho gọn thay vì giao việc.

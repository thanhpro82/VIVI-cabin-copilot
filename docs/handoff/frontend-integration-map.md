# Bản đồ tích hợp Frontend ↔ Backend — ai làm gì, còn thiếu gì

> **Mục đích.** Trả lời đúng ba câu: *chỗ nào Giáp cắm được ngay*, *chỗ nào phải chờ ai*,
> và *chỗ nào chưa ai nhận*. Dùng ở standup để chốt chủ sở hữu cho mục "CHƯA RÕ".
>
> **Trạng thái tính đến 2026-08-09**, nhánh `develop`. Mọi dòng đều đối chiếu code thật,
> không lấy lại lời tự khai của tài liệu. Cập nhật file này khi có việc chuyển chủ.

## Ranh giới sở hữu

Bảng workstream trong `README.md` (WS3 = Thành, WS4 = Sơn Hà & Giáp) **đã lạc hậu** —
**task board là nguồn đúng**.

| Người | Ticket đang giữ | Vùng code |
|---|---|---|
| **Sơn** | Hoàn thiện Vehicle State API · MQTT End-to-End Integration Test | `src/vehicle_sim/`, `src/services/{mqtt_*,vehicle_state,tool_executor,vehicle_gateway}.py`, `src/mqtt_topics.py`, `GET /vehicle/state`, `/ws/engineer` (kênh state) |
| **Nhân** | Tích hợp HITL end-to-end · Hoàn thiện Grounded RAG Response · **nhận thêm** `/auth/login`, `/sessions`, `/turns/text` | `src/agents/**`, `src/api/approvals.py`, `src/rag/**`, `GET /citations/{id}` |
| **Thành** | Voice Turn API (PR đã merge) | `src/services/ivi_events.py`, `/ws/ivi` handler trong `src/api/ws.py`, `POST /turns/voice` |
| **Giáp** | Tích hợp IVI Screen end-to-end · Hoàn thiện Engineer Dashboard | `frontend/**` |

> **Đính chính 2026-08-10.** Bảng này từng ghi `/ws/ivi` và
> `src/services/ivi_events.py` là của Nhân. **Sai.** Nhân phát hiện khi review PR
> SCRUM-54/55, và git xác nhận: cả 4 commit của `ivi_events.py` (`04400bc`,
> `b8c5e3e`, `67f2229`, `6b069fc`) và hai commit dựng handler `/ws/ivi`
> (`095ea37`, `8b63e03`) đều của **Nguyễn Tuấn Thành**, đã merge vào `develop`.
>
> Suýt nữa Nhân dựng lại từ đầu đúng những thứ đã có, vì cậu ấy tách nhánh trước
> thời điểm đó. **Cần Thành xác nhận ai giữ tiếp tầng này** — ba khoảng trống ở
> mục CHƯA RÕ #11 đang không có chủ.

---

## 1. Mười hai interface P0 (`docs/api_spec.md` §"P0 public surface")

| # | Interface | Trạng thái | Chủ | FE gọi ở đâu |
|---:|---|---|---|---|
| 1 | `POST /api/v1/auth/login` | ❌ **404** | **chưa ai** | `session/real.ts:73` |
| 2 | `POST /api/v1/sessions` | ❌ **404** | **chưa ai** | `session/real.ts:117` |
| 3 | `POST /api/v1/turns/text` | ❌ **404** | **chưa ai** | `turn/real.ts:177` |
| 4 | `POST /api/v1/turns/voice` | ✅ có (202) | Nhân | `turn/real.ts:193` |
| 5 | `POST /api/v1/approvals/{approval_id}/decision` | ✅ có | Nhân | `turn/real.ts:209` |
| 6 | `GET /api/v1/vehicle/state` | ⚠️ có, đang hoàn thiện | **Sơn** | `turn/real.ts:170` |
| 7 | `GET /api/v1/citations/{citation_id}` | ❌ **404** | Nhân | `turn/real.ts:223` |
| 8 | `GET /api/v1/traces/{trace_id}` | ✅ có (TASK-BE-OBS-001) | **Sơn** | FE **chưa implement** — giữ trong P0, xem ghi chú dưới |
| 9 | `GET /api/v1/metrics/summary` | ✅ có, đủ 8 nhóm (TASK-BE-OBS-001) | **Sơn** | `engineer/real.ts:137` |
| 10 | `GET /healthz` | ❌ **404** (chỉ có `/health`, khác path & shape) | **Sơn** | `engineer/real.ts:144` |
| 11 | `WS /ws/ivi` | ⚠️ có, thiếu 4 event | Nhân | `turn/real.ts:245` |
| 12 | `WS /ws/engineer` | ✅ đủ 5 event (TASK-BE-OBS-001) | **Sơn** (toàn bộ `engineer_stream`) | `engineer/real.ts:156` |

**Ngoài spec, nên dọn:** `POST /api/v1/chat`, `GET /api/v1/status` (`src/api/routes.py`),
`POST /api/v1/agent/process` (dev-only, đã gate đúng bằng `include_in_schema=False` + 404 khi
`APP_ENV=production`).

---

## 2. Event `/ws/ivi` — allowlist 15 loại, đang phát 11

Nguồn: `docs/api_spec.md` §"Driver server-event allowlist".

| Event | Trạng thái | Chủ | FE xử lý ở đâu |
|---|---|---|---|
| `turn.accepted` | ✅ `turns.py:89` | Nhân | — |
| `transcript.final` | ✅ | Nhân | `DriverShellProvider.tsx:83` |
| `assistant.status` | ✅ `ivi_events.py:166,178,244,251` | Nhân | `:79` |
| `approval.required` | ✅ `ivi_events.py:153` | Nhân | `:89` |
| `action.blocked` | ✅ `ivi_events.py:216` | Nhân | — |
| `tool.result` | ✅ `ivi_events.py:186` | Nhân | `:105` → **refresh vehicle state** |
| `assistant.response` | ✅ `ivi_events.py:197,221,231,253` | Nhân | `:97` |
| `turn.completed` | ✅ | Nhân | `:108` → refresh |
| `turn.failed` | ✅ `ivi_events.py:205`, `turns.py:126,176` | Nhân | ⚠️ **FE KHÔNG xử lý** — xem CHƯA RÕ #5 |
| `turn.canceled` | ✅ `ivi_events.py:234` | Nhân | `:109` → refresh |
| `error` | ✅ `turns.py:119,163`, `ws.py:156` | Nhân | `:101` |
| **`plan.ready`** | ❌ **thiếu** | Nhân | `:86` → `HitlModal.tsx:59` — **modal hiện chuỗi rỗng nếu thiếu** |
| **`ui.policy`** | ❌ **thiếu** | **chưa ai** | FE chưa xử lý |
| **`transcript.partial`** | ❌ **thiếu** | Nhân | `:82` (đã sẵn sàng nhận) |
| **`approval.intent.detected`** | ❌ **thiếu** | Nhân | FE chưa xử lý |

**`plan.ready` là thiếu sót nghiêm trọng nhất của nhánh này.** `DriverShellProvider.tsx:86-88`
lưu `plan.ready.summary` vào `planSummaryRef`, rồi `:89-96` dùng nó khi mở HITL modal. Không
có `plan.ready` → `HitlModal.tsx:59` hiển thị `Bạn xác nhận: ?` với chỗ trống.

**`ui.policy` là thiếu sót về an toàn.** Sáu cờ chế độ xe-đang-chạy (`allow_text_input=false`,
`lock_small_controls=true`, `enlarge_mic_button=true`, `max_visible_actions=3`,
`prefer_voice_confirmation=true`, `allow_detailed_document_browsing=false`) **phải do backend
suy ra**; `api_spec.md:575` cấm client tự đoán. Hiện không ai phát.

---

## 3. Event `/ws/engineer` — allowlist 5 loại, **đã phát đủ 5** (TASK-BE-OBS-001)

| Event | Trạng thái | Chủ | Nhịp phát | FE xử lý |
|---|---|---|---|---|
| `state` | ✅ | **Sơn** | mỗi transition của xe | ⚠️ **FE vẫn bỏ qua** — `engineer/real.ts:174-189` chỉ nhận `trace`/`metrics`/`health`/`error` |
| `error` | ✅ | **Sơn** | khi handshake sai hoặc mất broker | `engineer/real.ts:184` |
| `trace` | ✅ | **Sơn** | **khi một lượt chốt**, mọi phiên | `engineer/real.ts:175` |
| `metrics` | ✅ | **Sơn** | lúc connect + mỗi 5s | `engineer/real.ts:178` |
| `health` | ✅ | **Sơn** | mỗi 10s, **không** lúc connect | `engineer/real.ts:181` |

Còn đúng một chiều lệch: backend phát `state` mà FE không đọc. Chiều còn lại (FE chờ `trace`
mà backend không phát) đã đóng.

`health` **cố ý** không nằm trên đường handshake: `collect_health()` chạy 8 probe thật và lần
đầu nạp cả weight STT, mất hàng chục giây — đặt nó ở đó thì `connection.init` treo và trình
duyệt bỏ cuộc. Nó tới từ vòng sampler đầu tiên, và sampler là **một** cho mọi kết nối chứ
không phải mỗi socket một cái.

Payload `health` luôn dùng **shape nhánh 200** (`checked_at` + `components[].latency_ms`) kể cả
khi có component down — `api_spec.md:609`. Đừng nhầm với `mapHealthFromErrorDetails()` mà Giáp
thêm cho nhánh **REST 503**; hai đường khác nhau.

---

## 4. ĐÃ RÕ — có chủ, có AC, bắt đầu được ngay

| Việc | Chủ | Ghi chú |
|---|---|---|
| `GET /vehicle/state`: vỏ lỗi top-level, 3 nhánh 503, `response_model`, `X-Trace-Id` | Sơn | đang làm |
| `GET /healthz` 8 component | **Thành** | ✅ xong (PR #34) — hai nhánh khác shape, xem tài liệu FE |
| `VehicleGateway` port + 2 implementation | Sơn | giao cho Nhân cắm vào |
| Bộ test E2E MQTT + báo cáo `eval/results/mqtt-e2e/` | Sơn | đang làm |
| Nối agent graph vào `VehicleGateway` | Nhân | thuộc AC2 ticket HITL ("state invalidation") |
| Phát `plan.ready` trước `approval.required` | Nhân | mở khoá HITL modal của Giáp |
| Thêm `citation_id` + sửa shape `citations` | Nhân | `assistant.response.payload.citations` |
| RAG composer tổng hợp câu trả lời | Nhân | hiện chỉ trả `excerpt` |
| FE map `doors` từ `open/closed` | Giáp | xem §6 |
| FE bổ sung domain `seat` | Giáp | xem §6 |
| FE xử lý `turn.failed` | Giáp | xem CHƯA RÕ #5 |

---

## 5. CHƯA RÕ — cần chốt ở standup

> Mục này quan trọng hơn mục trên. Mỗi dòng là một câu hỏi cần **một cái tên** trả lời.

**#11 — Ba khoảng trống của tầng `/ws/ivi`, ai giữ tiếp?** *(mới, 2026-08-10)*
Nhân nêu khi review, và đề nghị Thành xác nhận vì tầng này là của Thành:
- `sequence` tăng theo **kết nối** chứ không theo phiên (`EventStream` khởi tạo
  mỗi lần nối, `ws.py:41`) → reconnect là số nhảy về 1, client mất khả năng phát
  hiện sự kiện bị bỏ lỡ.
- `IviEventBus` không có buffer/replay: không listener nào đang nối thì sự kiện bị
  vứt. **Rớt mạng đúng lúc chờ duyệt là mất luôn `approval.required`** — người
  dùng kẹt không biết có gì cần xác nhận.
- `AUTH_ENABLED` trong docstring `ws.py` là **cờ ma**, `grep src/config.py` không
  có. Hệ quả thì chính docstring đó tự thú: bất kỳ client nào cũng nghe được sự
  kiện của bất kỳ `session_id` nào nó khai ra.

**#1 — `POST /auth/login` + `POST /sessions` ai làm, bao giờ?**
✅ **Đã có chủ (2026-08-10): Nhân nhận cả #1, #2, #3.** Design đã viết: token mờ
in-memory, chủ thể là **phiên đăng nhập** chứ không phải người dùng — vì với một
hồ sơ mặc định duy nhất, gắn quyền sở hữu vào người dùng thì mọi phép kiểm đều
trả về đúng cho tất cả, tức không đóng được gì. Nhân sẽ rebase lên `develop` rồi
mở PR. Phần dưới giữ lại làm bối cảnh vì sao nó gấp.

Đây là **domino chặn mọi thứ**. `authHeaders()` (`turn/real.ts:20-26`) và `currentSessionId()`
(`turn/real.ts:28-38`) **throw ngay** nếu localStorage chưa có token/session. Hệ quả dây
chuyền: không login được → không có `session_id` → `/ws/ivi` không kết nối
(`turn/real.ts:240-243` return no-op) → **kể cả những endpoint đã làm xong cũng không dùng
được**. Nhóm đang để "chốt sau" — cần chốt sớm.
Kèm theo: ai seed bảng `users` và đưa email/password demo cho Giáp điền vào
`DEMO_DRIVER_EMAIL`/`DEMO_DRIVER_PASSWORD`? (`frontend/docs/ARCHITECTURE.md` mục 3.1 ghi rõ
"chưa nằm trong tài liệu gốc nào cả, cần chủ động nhắc BE".)

**#2 — `POST /turns/text` ai làm?**
Không nằm trong ticket của ai. Nhưng **mọi nút bấm trong IVI của Giáp** đều gọi nó
(`VehicleControlView`, `RightPanel` → `send("mở khoá cửa")` → `sendText()`), và
`frontend/docs/ARCHITECTURE.md:5` chốt "mọi thay đổi trạng thái xe kể cả bấm nút UI đều đi
qua `/turns/text` hoặc `/turns/voice`". Nghiêng về Nhân vì nó là anh em của `/turns/voice`,
nhưng cần xác nhận.

**#3 — `GET /metrics/summary` + `/ws/engineer` phát `trace` ai làm?** — ✅ **ĐÃ CHỐT: Sơn.**
Xong trong TASK-BE-OBS-001. Route phát **8 nhóm**, không phải 7: bản canonical
`api_spec.md:608` có thêm `model_runtime`, mục này trước đó ghi thiếu. FE destructure 7 nên
nhóm thứ tám là additive, không vỡ gì. `p50`/`p95` và mọi tỉ lệ đều là `null` (không phải `0`)
khi window rỗng, đúng như yêu cầu ở đây.

Lưu ý khi đọc số: `model_runtime` **luôn rỗng** ở P0 (`model_profile: "not-selected"`, mọi
percentile `null`) vì `slm_enabled=False` và ADR-005 còn "Not Yet" — không có generation nào
chạy để mà đo. `rag.faithfulness_*` cũng luôn rỗng: `api_spec.md:460` cấm lấy điểm tự chấm của
model, con số đó chỉ đến từ rubric có người chấm chạy offline.

**#4 — `/ws/engineer` có phát `trace` cho mọi turn của mọi tài xế không?** — ✅ **ĐÃ CHỐT: có.**
Engineer là fleet-scoped, không gắn phiên: `api_spec.md:531` chốt `connection.init` của
`/ws/engineer` **bỏ** `session_id`. Backend phát `trace` khi mỗi lượt chốt, bất kể phiên nào.
Giả định ở `frontend/docs/ARCHITECTURE.md:107` là đúng — bảng log của Giáp sẽ có dữ liệu.

**#5 — `turn.failed`: BE bớt dùng hay FE thêm case?**
`DriverShellProvider.tsx:108-114` chỉ refresh state khi `turn.completed`/`turn.canceled`.
Nếu BE kết thúc bằng `turn.failed` (nhánh `execution_failed`, `STT_FAILED`, `INTERNAL_ERROR`)
thì UI kẹt `pending=true`, nút bấm chết. **BE đang làm đúng spec** → nghiêng về Giáp thêm
case, nhưng cần Giáp xác nhận.

**#6 — `ui.policy` ai làm?**
Không nằm trong ticket của ai. Là **cờ an toàn** khi xe đang chạy, không phải trang trí.
Không có nó thì IVI không có chế độ moving.

**#7 — `phase: accepted → completed` là bug hay simplification P0? → Không phải cả hai. Đã đóng 2026-08-11 (issue #50).**
Không có lệch nào để sửa. `docs/mqtt_spec.md` §phase và status viết rõ: *"Ở P0 simulator áp
dụng tức thì nên `accepted` và `completed` xảy ra gần như đồng thời, và **simulator được phép
chỉ phát `completed`**. Không được gộp hai khái niệm này lại."* Câu đó có từ commit gốc
`8a8204f` (SCRUM-19) — trước PR #32, nên không phải viết thêm để hợp thức hoá code.
Dòng 471 bị đọc nhầm vì nó nằm trong bảng **"Điểm khớp chuẩn"**: bảng đó đối chiếu thiết kế
hợp đồng với Android/VSS/Kuksa để biện minh cho việc *giữ hai phase trong enum*, chứ không
quy định hành vi simulator P0.

Không đổi `vehicle_sim`, không đổi enum `phase` (giữ chủ đích forward-compatible của ADR-004).
Rủi ro thật nằm ở phía executor và đã khoá: `ToolExecutor._on_event()` từng resolve waiter
bằng **event đầu tiên** khớp `command_id` mà không lọc `phase`, nên nếu P1 phát `accepted`
thì `ToolResult.from_event()` sẽ dựng kết quả `completed` từ một lệnh mới chỉ được *nhận*.
Giờ `accepted` bị bỏ qua, và `tests/test_vehicle/test_mqtt_roundtrip.py::test_accepted_phase_khong_duoc_coi_la_ket_qua_cuoi`
giữ bất biến đó.

**#8 — subprotocol `bearer.<base64>` có padding `=`.**
FE dùng `btoa()` (`turn/real.ts:245`, `engineer/real.ts:156`) → base64 **có padding**. Ký tự
`=` không hợp lệ trong `Sec-WebSocket-Protocol` (RFC 6455 token), và `api_spec.md:503` yêu
cầu **base64url**. Chrome có thể ném `SyntaxError` ngay khi `new WebSocket(...)`. Cần Giáp
đổi sang base64url không padding — nhưng chỉ đáng làm sau khi có `/auth/login` (#1).

**#9 — `/healthz` sẽ LUÔN trả 503 vì `llm`. Chấp nhận hay sửa spec?**
Phát hiện khi implement. `api_spec.md:495` đòi cả **tám** component `ready` thì mới 200, và
`llm` là một trong tám. Nhưng ADR-005 kết luận **Not Yet** cho cả hai ứng viên Qwen Q4, ADR-010
xếp SLM là *fallback* chứ không phải planner chính, và `slm_enabled` mặc định `False` — tức là
**P0 chạy hoàn toàn bằng luật tất định, không có LLM nào đang chạy**. Nên `/healthz` trả 503
là *đúng sự thật*, không phải bug.
Hệ quả cho Giáp: AlertBanner sẽ luôn đỏ ở mục `llm`. Backend **không** báo `ready` cho một
LLM không tồn tại — đó là nói dối trong chính cái endpoint mà người khác dựa vào.
Hai lối thoát, cần nhóm chọn: (a) chấp nhận 503 và Giáp lọc riêng `llm` khỏi AlertBanner;
(b) sửa `api_spec.md` để `llm` là optional ở P0, có ADR kèm theo.

**#10 — `GET /traces/{trace_id}` có cần cho P0 không?**
Là interface #8 trong spec, nhưng FE **chưa implement** lời gọi nào. Có thể bỏ khỏi P0 —
cần chốt để khỏi treo.

---

## 6. Ba quyết định liên nhóm ĐÃ CHỐT — Giáp khỏi hỏi lại

**`doors` = `"open"` / `"closed"`, không phải `"unlocked"` / `"locked"`.**
Backend giữ nguyên theo `docs/mqtt_spec.md` và 6 JSON Schema trong `schemas/mqtt/`. FE hiện
đọc theo khoá/mở khoá ở 3 chỗ và sẽ hỏng nếu cắm BE thật:
- `Car3DViewer.tsx:67-69` — `isDoorVisuallyOpen(status) { return status === "unlocked" }`
- `VehicleControlView.tsx:121` — `const locked = vehicleState?.doors[pos.key] !== "unlocked"`
- `RightPanel.tsx:13-15` và `VehicleControlView.tsx:27-29` — `anyDoorUnlocked()` so `=== "unlocked"`

Lý do không thêm `locked`: mỗi cửa sẽ phải đổi từ string sang object `{state, locked}` — đó
là breaking change trên `GET /vehicle/state` + 6 JSON Schema + hợp đồng MQTT, và
`mqtt_spec.md:529-535` đã cố ý hoãn sang P1.

**`lights` / `trunk` chỉ tồn tại ở FE.** Quyết định 2026-08-09 (commit `318c447`): được phép
tồn tại như "P1/demo enhancement" **với điều kiện** không thêm public API mới và không để FE
bịa dữ liệu coi như của backend. `turn/real.ts:82-84` đang hardcode `lights: false`,
`trunk: "closed"` — đúng như đã duyệt. Backend **không** thêm gì.

**Domain `seat` có thật.** Backend trả `seat.{front_left,front_right}.{heating, fore_aft,
recline, height}` đúng `api_spec.md:294-297`, nhưng FE bỏ qua hoàn toàn:
`turn/real.ts:49-85` `mapVehicleState()` không map, `turn/types.ts:1-31` không khai. Bổ sung
nếu cần hiển thị; không bổ sung cũng không vỡ gì.

---

## 7. Thứ tự mở khoá cho Giáp

Sắp theo mức chặn, không theo độ khó:

1. **`/auth/login` + `/sessions`** *(chưa ai)* — không có thì Giáp không chạy nổi một dòng.
2. **`/turns/text`** *(chưa ai)* — mở khoá mọi nút bấm trong IVI.
3. **`plan.ready`** *(Nhân)* — mở khoá HITL modal.
4. **`/vehicle/state`** *(Sơn)* và **`/healthz`** *(Thành, PR #34)* — ✅ xong; mở khoá refresh state và
   AlertBanner.
5. **Nhân cắm graph vào `VehicleGateway`** *(Nhân)* — mở khoá việc *state thật sự đổi* sau
   lệnh giọng nói. Không có bước này thì bước 4 vẫn trả state không bao giờ thay đổi.
6. **`/metrics/summary` + WS `trace`** *(chưa ai)* — mở khoá Engineer Dashboard.
7. `citation_id` + shape `citations` *(Nhân)* — nợ shape, sửa sau khi demo chạy.

> Bước 4 và 5 tách nhau có chủ đích: Sơn giao cổng `VehicleGateway`, Nhân cắm vào. Chi tiết
> ở `docs/handoff/vehicle-gateway-for-agent.md` (viết sau khi cổng xong).

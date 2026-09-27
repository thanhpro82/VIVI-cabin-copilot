# Bàn giao Backend → Frontend: vehicle state và healthz — cho Giáp

> Phần của Sơn (`GET /api/v1/vehicle/state`, `/ws/engineer` kênh
> state) đã xong. Tài liệu này nói đúng những gì đổi ở phía bạn.
>
> Ai làm phần nào, cái gì còn thiếu: xem `docs/handoff/frontend-integration-map.md`.

## Hợp đồng đọc ở đâu

Chạy backend rồi mở **`http://localhost:8000/docs`**.

`GET /api/v1/vehicle/state` có `response_model` **và** khai `ErrorEnvelope` cho
nhánh 503, nên bấm vào mục `503` là thấy đúng hình dạng lỗi.

`GET /healthz` thì **chưa** — route chưa khai `responses={503:...}` nên OpenAPI
đang nói nó chỉ trả 200. Dùng hai mẫu JSON ở mục 4 làm chuẩn cho tới khi Thành bổ
sung.

Hai điều khác về bề mặt `/docs`:

- **Chỉ có 4 endpoint**: `/turns/voice`, `/approvals/{id}/decision`,
  `/vehicle/state`, `/healthz`. `/chat`, `/status` và `/agent/process` đã bị ẩn vì
  **không phải interface P0** — trước đây chúng hiện lẫn vào và người đọc không biết
  tin cái nào.
- **WebSocket không xuất hiện trong OpenAPI** — giới hạn của OpenAPI 3.0, không phải
  thiếu sót. Hợp đồng `/ws/ivi` và `/ws/engineer` ở `docs/api_spec.md`
  §"WebSocket contracts".

```powershell
.\.venv\Scripts\python.exe -m src.serve     # KHÔNG dùng uvicorn trên Windows (MQTT sẽ vỡ)
```

Không cần Mosquitto: để `MQTT_ENABLED=false` thì backend chạy xe in-process và
`GET /api/v1/vehicle/state` vẫn trả 200 bình thường. Bạn dựng UI được mà không
phải dựng broker.

---

## 1. Vỏ lỗi đã sửa — cái này ảnh hưởng tới bạn ngay

Trước đây backend trả lỗi dạng `{"detail": {"error": {...}}}` — thừa một tầng so
với `docs/api_spec.md`. `shared/errors.ts` của bạn đọc `body.error?.code` nên
**luôn miss** và mọi lỗi rơi về mã fallback.

Giờ đã đúng, `error` nằm ở **top-level**:

```json
{
  "error": {"code": "MQTT_UNAVAILABLE", "message": "...", "retryable": true, "details": {...}},
  "meta": {"request_id": "req_..."},
  "trace_id": "tr_...",
  "schema_version": "1.0"
}
```

Nếu bạn từng thêm code đọc `body.detail.error` để né bug cũ thì gỡ được rồi.

Lưu ý: `POST /api/v1/turns/voice` **vẫn còn** vỏ cũ — nó thuộc luồng turn của
Nhân, đã báo trong tài liệu bàn giao của cậu ấy.

## 2. `X-Trace-Id` giờ được tôn trọng

Gửi header `X-Trace-Id` thì backend dùng lại nó trong `trace_id` của response và
trong header trả về, nên bạn nối được log hai bên. Định dạng hợp lệ:
`^[A-Za-z0-9_.:-]{8,64}$`. Sai định dạng thì server **tự sinh id mới chứ không
trả 400** — hỏng tương quan log không đáng để hỏng cả request.

---

## 3. `GET /api/v1/vehicle/state` — có thể trả 503 với **năm** lý do

Thành công thì y như cũ. Cái mới là nó **không còn trả state cũ** khi xe ảo đã
chết — trả 200 lúc đó là nói dối, và bạn không có cách nào biết.

```json
{
  "error": {
    "code": "MQTT_UNAVAILABLE",
    "message": "Xe ảo im lặng quá lâu — state đang giữ đã hết hạn.",
    "retryable": true,
    "details": {
      "reason": "heartbeat_stale",
      "mqtt_connected": true,
      "simulator_online": true,
      "health_age_s": 18.4,
      "heartbeat_stale_s": 15.0,
      "last_state_version": 42
    }
  },
  "meta": {"request_id": "req_..."},
  "trace_id": "tr_...",
  "schema_version": "1.0"
}
```

`details.reason` phân biệt năm nguyên nhân — hiển thị đúng cái này thì người dùng
biết phải làm gì:

| `reason` | Nghĩa | Nên nói với người dùng |
|---|---|---|
| `broker_unreachable` | Backend chưa nối được MQTT | Lỗi hạ tầng, gọi kỹ sư |
| `no_snapshot_yet` | Đã nối nhưng xe ảo chưa gửi gì | Đang khởi động, thử lại sau vài giây |
| `no_health` | Chưa nhận tín hiệu sức khoẻ nào | như trên |
| `offline` | Xe ảo đã báo ngắt kết nối | Xe ảo chưa chạy |
| `heartbeat_stale` | Xe ảo im lặng > 15 giây | Xe ảo treo |

Ba cái đầu là "chờ được", `offline`/`heartbeat_stale` là "có gì đó hỏng".

> ⚠️ `DriverShellProvider.tsx:69-71` gọi `refreshVehicleState()` bằng `.then()`
> **không có `.catch()`**. Với 503 nó sẽ thành unhandled rejection và
> `vehicleState` kẹt `null`. Đáng thêm `.catch()` để hiện thông báo thay vì màn
> hình trống.

## 4. `GET /healthz` — **của Thành**, và hai nhánh có shape KHÁC nhau

> **Đính chính 2026-08-10.** Bản đầu của tài liệu này mô tả `/healthz` do Sơn
> viết. Thành cũng làm cùng lúc (PR #34) và bản của cậu ấy đã vào `develop`; bản
> của Sơn bị bỏ khi rebase. Mục này viết lại theo **bản đang chạy**. Chỗ nguy hiểm
> nhất là hướng dẫn cũ *"đọc `body.data ?? body.error.details`"* — **không dùng
> được**, xem dưới.

Đúng 8 component theo `api_spec.md:495`: `backend`, `llm`, `mqtt`,
`vehicle_simulator`, `stt`, `tts`, `rag_index`, `sqlite`.

**Hai nhánh trả về hai hình dạng khác nhau — đây là cố ý và đúng spec.**

Nhánh **200** (`data`):

```json
{"data": {
   "status": "ready",
   "checked_at": "2026-08-10T02:00:00Z",
   "components": {"backend": {"status": "ready", "latency_ms": 0.2}, ...},
   "faults": []
 }, "meta": {...}, "trace_id": "...", "schema_version": "1.0"}
```

Nhánh **503** (`error.details`):

```json
{"error": {
   "code": "DEPENDENCY_NOT_READY",
   "message": "một hoặc nhiều dependency bắt buộc chưa sẵn sàng",
   "retryable": true,
   "details": {"dependencies": {"llm": {"status": "down", "code": "..."}, ...}}
 }, "meta": {...}, "trace_id": "...", "schema_version": "1.0"}
```

Khác nhau ở **tên khoá** (`components` ↔ `dependencies`) và **field bên trong**
(`latency_ms` ↔ `code`). Nhánh 503 **không có** `checked_at`, `status` tổng, hay
`faults`. `api_spec.md:495` quy định đúng như vậy: nhánh lỗi chỉ được lộ tên
component + trạng thái + mã probe đã che, không lộ gì thêm.

Nên `engineer/real.ts` phải xử lý **hai shape**, không phải một:

```ts
if (res.ok) {
  const d = body.data;                       // {status, checked_at, components, faults}
  return { status: d.status, components: d.components };
}
const deps = body.error?.details?.dependencies ?? {};   // {name: {status, code}}
return { status: "down", components: deps };            // không có latency_ms ở nhánh này
```

> **Chưa có trong `/docs`:** route `/healthz` hiện không khai `responses={503:...}`
> nên OpenAPI đang nói nó chỉ trả 200. Đã báo Thành; trong lúc chờ, dùng hai mẫu
> JSON ở trên làm chuẩn.

> **`/health` (không có `z`) đã bị xoá** ở PR #34. Healthcheck của container
> backend giờ trỏ vào `GET /api/v1/status`. Đừng gọi `/health` nữa.

## 5. `/healthz` sẽ gần như luôn trả 503 — và đó là sự thật, không phải bug

`llm` là một trong tám component bắt buộc. Nhưng ADR-005 kết luận **Not Yet** cho
cả hai ứng viên Qwen Q4, ADR-010 xếp SLM là *fallback* chứ không phải planner
chính, và `slm_enabled` mặc định `False` — tức là **P0 chạy hoàn toàn bằng luật
tất định, không có LLM nào đang chạy**.

Backend **không** báo `ready` cho một LLM không tồn tại. Nên `/healthz` trả 503
với `llm.status = "down"`.

Hệ quả cho bạn: AlertBanner sẽ luôn đỏ ở mục `llm`. Hai lối thoát, **cần nhóm
chốt** (đã đưa vào mục CHƯA RÕ #9 của `frontend-integration-map.md`):

- (a) Giáp lọc riêng `llm` khỏi AlertBanner và ghi chú "P0 không dùng LLM";
- (b) Sửa `api_spec.md` để `llm` là optional ở P0, kèm ADR.

Đừng tự chọn (a) một mình — nó là quyết định về hợp đồng, không phải về UI.

---

## 6. Ba việc phía bạn cần đổi

**① `doors` là `"open"` / `"closed"`, không phải `"unlocked"` / `"locked"`.**
Backend giữ nguyên theo `docs/mqtt_spec.md` và 6 JSON Schema. Ba chỗ FE đang đọc
sai và sẽ hỏng khi cắm backend thật:

- `Car3DViewer.tsx:67-69` — `isDoorVisuallyOpen(status) { return status === "unlocked" }`
- `VehicleControlView.tsx:121` — `const locked = vehicleState?.doors[pos.key] !== "unlocked"`
- `RightPanel.tsx:13-15` và `VehicleControlView.tsx:27-29` — `anyDoorUnlocked()`

Nếu không sửa: backend trả `"closed"` → FE coi mọi cửa là "đã khoá" mãi mãi, xe 3D
không bao giờ mở cửa, bấm "Mở khoá cửa" xong không thấy gì đổi.

Vì sao backend không thêm `locked`: mỗi cửa sẽ phải đổi từ string sang object
`{state, locked}` — breaking change trên `GET /vehicle/state` + 6 JSON Schema +
hợp đồng MQTT, và `mqtt_spec.md:529-535` đã cố ý hoãn sang P1.

**② Domain `seat` có thật, FE đang bỏ qua.** Backend trả
`seat.{front_left,front_right}.{heating, fore_aft, recline, height}` đúng
`api_spec.md:294-297`, nhưng `turn/real.ts:49-85` `mapVehicleState()` không map và
`turn/types.ts` không khai. Bổ sung nếu cần hiển thị; không bổ sung cũng không vỡ.

**③ Subprotocol WebSocket có thể làm Chrome ném lỗi.** Bạn dùng `btoa()`
(`turn/real.ts:245`, `engineer/real.ts:156`) → base64 **có padding `=`**. Ký tự
`=` không hợp lệ trong `Sec-WebSocket-Protocol` (RFC 6455 token), và
`api_spec.md:503` yêu cầu **base64url**. Chrome có thể ném `SyntaxError` ngay tại
`new WebSocket(...)`. Chỉ đáng sửa sau khi có `/auth/login` — hiện chưa ai làm
endpoint đó.

---

## 7. `lights` / `trunk` — không đổi gì

Quyết định 2026-08-09 giữ nguyên: chúng chỉ tồn tại ở FE như "P1/demo
enhancement", `real.ts:82-84` hardcode `lights: false`, `trunk: "closed"`. Backend
**không** thêm gì. Muốn nối thật thì phải mở rộng tool registry + `vehicle_state`
schema + hợp đồng MQTT trước, và đó là việc liên nhóm.

## 8. Cái chưa xong, đừng chờ Sơn

`GET /vehicle/state` giờ đúng hợp đồng, nhưng **giá trị nó trả về vẫn chưa đổi
sau lệnh giọng nói** — mắt xích cuối nằm ở ticket HITL của Nhân (nối agent graph
vào `VehicleGateway`). Chi tiết ở `docs/handoff/vehicle-gateway-for-agent.md`.

Còn `POST /turns/text`, `POST /auth/login`, `POST /sessions`,
`GET /metrics/summary` và `/ws/engineer` phát `trace` thì **chưa ai nhận** — xem
mục CHƯA RÕ trong `frontend-integration-map.md` và nêu ở standup.

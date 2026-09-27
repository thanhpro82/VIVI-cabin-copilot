# SCRUM-54 & SCRUM-55 — báo cáo hoàn thành và phân chia phần việc

- **Người thực hiện:** Bế Nguyễn Hà Sơn (WS3 — Virtual Vehicle & MQTT)
- **Ngày:** 2026-08-09
- **Nhánh:** `develop`
- **Run bằng chứng:** `eval/results/mqtt-e2e/20260809T161533.418052Z/`

---

## 1. Kết luận ngắn

| Ticket | Kết luận | Ghi chú |
|---|---|---|
| **SCRUM-54** — Vehicle State API | ✅ **Xong** — 3/3 AC đạt | Không còn phụ thuộc ai |
| **SCRUM-55** — MQTT E2E Test | ⚠️ **Xong phần thuộc mình** — AC2 và AC3 đạt đầy đủ; AC1 đạt từ Executor trở đi, **nửa "Agent" phụ thuộc ticket HITL của Nhân** | Tầng L2 đã chạy thật trên Mosquitto: **12/12 pass** |

Suite gốc: **470 → 603 passed**, 15 skipped (tầng L2, cần broker). Con số này gồm cả
test của Thành từ PR #34 sau khi nhánh được rebase lên `develop`.
Tầng L2 chạy riêng trên Mosquitto thật: **12/12 pass**.
Lint sạch `src/`, `tests/`, `scripts/`. Thời gian chạy suite: **205 giây → 31 giây**.

---

## 2. SCRUM-54 — Vehicle State API

### AC1 — trả đúng state hiện tại, đủ domain canonical ✅

Đủ **7 domain** theo `docs/api_spec.md`: `motion`, `hvac`, `windows`, `doors`, `media`,
`navigation`, `seat` — cộng `vehicle_id`, `state_version`, `observed_at`. Không thừa
không thiếu, có test khoá đúng bộ 10 khoá này.

Đã thêm so với trước:

- `response_model=VehicleStateEnvelope` → `/docs` tự mô tả hợp đồng, kể cả nhánh lỗi.
- **Vỏ lỗi top-level đúng spec.** Trước đây `HTTPException(detail=...)` bọc thêm một
  tầng `{"detail": ...}` nên frontend đọc `body.error.code` **luôn miss**. Đã thay bằng
  `ApiError` + exception handler.
- **5 nhánh 503 phân biệt được**, không còn gộp một cục: `broker_unreachable`,
  `no_snapshot_yet`, `no_health`, `offline`, `heartbeat_stale` — kèm `health_age_s`,
  `last_state_version` để chẩn đoán.
- **Không trả state cũ khi xe ảo đã chết.** Hợp đồng gọi đây là state *authoritative*;
  trả 200 với dữ liệu của simulator đã chết là nói dối một cách im lặng.
- `X-Trace-Id` của client được validate rồi dùng lại (sai định dạng thì sinh mới, không
  trả 400).

**Bằng chứng:** `tests/test_api/test_vehicle_state.py` — 14 test.

### AC2 — state đồng bộ Simulator → MQTT → Backend ✅

Chuỗi này vốn đã chạy nhưng **chưa được test đầu-cuối**. Giờ có:

- Lệnh đi trọn vòng và quay về cache của backend, kiểm cả ba mốc (executor nhận
  `CommandEvent`, simulator đổi thật, cache bắt kịp qua retained snapshot).
- REST và cache nói cùng một `state_version`.
- Backend nối **sau** vẫn nhận đủ state qua retained — lý do backend không phải hỏi lại
  xe ảo lúc khởi động.
- 4 nhánh `readiness()` (`no_health` / `offline` / `heartbeat_stale` / `ready`), test bằng
  `FakeClock` chứ không chờ 15 giây thật.
- **Heartbeat loop thật** lần đầu được chạy trong test — trước đây mọi test đều đặt
  `heartbeat_interval_s=3600` để tắt nó.
- Payload sai schema bị bỏ qua ở cả 4 chỗ phòng thủ mà trước đó chưa nhánh nào được chạy.

**Bằng chứng:** `test_mqtt_e2e_inmemory.py` (12), `test_mqtt_stale_state.py` (15).

### AC3 — `state_version` tăng và trả đúng sau mỗi thay đổi ✅

- Tăng **đúng 1** cho mỗi thay đổi thật; **không tăng** khi lệnh là no-op hoặc bị từ chối.
- Snapshot **lùi version** bị bỏ qua (message tới trễ không kéo lùi state); cùng version
  thì vẫn ghi đè (retained giao lại lúc reconnect phải qua).
- **Cơ chế đồng bộ `state_version`** (deliverable): rolling version đọc từ
  `ToolResult.observed_state_version` — giá trị này do simulator tính **sau** khi đã tăng
  version và gắn vào `CommandEvent`, nên **không có race**, khác hẳn việc đọc lại cache.

**Bằng chứng:** 25 test nhóm `AC3-state_version`.

### Deliverables

| Yêu cầu | Trạng thái |
|---|---|
| Endpoint `GET /api/v1/vehicle/state` hoàn thiện | ✅ `src/api/routes.py` |
| Cơ chế đồng bộ `state_version` | ✅ `src/services/vehicle_gateway.py`, `src/services/vehicle_state.py` |
| ~~`GET /healthz` 8 component~~ | ❌ **Bỏ** — Thành làm song song (PR #34) và bản của cậu ấy đã vào `develop`; bản của Sơn bị bỏ khi rebase. Xem mục 10 |

---

## 3. SCRUM-55 — MQTT End-to-End Integration Test

### AC1 — chuỗi Agent/Executor → MQTT → Simulator → Result/State → Backend ⚠️

**Từ Executor trở đi: đạt đầy đủ.** 78 test phủ chuỗi này, gồm rolling version qua 3 lệnh
liên tiếp và qua cả bước no-op.

**Nửa "Agent" chưa đạt, và nó không nằm trong tầm tay ticket này.** Repo đang có
**hai simulator xe song song, không nối nhau**:

| | Đường MQTT | Đường agent |
|---|---|---|
| Simulator | `src/vehicle_sim/state.py` | `src/agents/vehicle.py` (một instance mỗi session) |
| Chảy vào `GET /vehicle/state` | ✅ | ❌ |

`ToolExecutor` **chưa từng được production code nào gọi** — chỉ có trong test và
`scripts/smoke_mqtt.py`. Nghĩa là lệnh giọng nói đổi state ở một chỗ, còn API đọc ở chỗ kia.

**Đã làm để gỡ:** dựng `VehicleGateway` — cổng chung cho cả hai đường, có 15 contract test
chạy **parametrize qua cả hai implementation** để chúng không trôi xa nhau. Cổng đã được
`GET /vehicle/state` và `/ws/engineer` tiêu thụ.

**Còn lại:** đổi `src/agents/**` sang gọi cổng. Việc này thuộc **AC2 ticket HITL của Nhân**
("state invalidation" — so `approved_vehicle_state_version` với trạng thái xe sống — không
thể đạt thật nếu không có nguồn state authoritative). Hướng dẫn migrate đầy đủ ở
`docs/handoff/vehicle-gateway-for-agent.md`: 8 điểm phải sửa + 4 cái bẫy đã verify hộ.

> **Cách báo cáo AC1 cho trung thực:** "chuỗi Executor → Backend đã test đầy đủ; mắt xích
> Agent → Executor là phần giao giữa hai ticket, đã bàn giao bằng tài liệu". Đừng tick AC1
> là 100% khi lệnh giọng nói vẫn chưa đổi được `GET /vehicle/state`.

### AC2 — chỉ dùng canonical topic `v1/vehicles/{id}/...` ✅

- Test regex trên **mọi** topic được publish trong một lượt chạy thật, không chỉ đọc code.
- Grep toàn repo: 0 hit `vivi/vehicle/*` trong code chạy được. Các hit còn lại nằm ở
  `_bmad-output/` (tài liệu cũ, đã ghi rõ là bản bị bác bỏ), báo cáo tuần 2, WORKLOG, và
  **một test khẳng định topic cũ bị từ chối** (`parse_command_domain("vivi/vehicle/control") is None`).
- Thêm: `commands/` và `events/command` **không bao giờ retain** (retain lệnh nghĩa là xe tự
  mở cửa sau khi broker restart); `state/*` và `health` **luôn retain**; mọi publish đều QoS 1.
- **6 JSON Schema lần đầu được đối chiếu tự động với model pydantic** — trước đó hai script
  kiểm chứng có sẵn nhưng không được gọi ở đâu cả (không CI, không Makefile, không pytest).
  Giờ chúng chạy trong pytest, **và** payload thật bắt từ broker cũng được validate.

**Bằng chứng:** 12 test `AC1-chain+AC2-topic`, 7 test `AC2-schema`.

### AC3 — idempotency, stale state, realtime ✅

**Idempotency (14 test):**
- Duplicate delivery QoS 1 → đúng 1 transition, 2 `CommandEvent`, **0 snapshot thứ hai**.
- Retry đúng 1 lần, **cùng `command_id` và `idempotency_key`** cả hai lần. Kèm khẳng định
  quan trọng: lệnh **đã chạy** dù executor báo `failed` — "mất phản hồi" ≠ "chưa thực thi",
  và chính vì vậy retry buộc phải giữ nguyên `command_id`.
- Chỉ **một** terminal result được persist.
- Hai chế độ hỏng khi `BoundedCache` evict — mà `docs/reviews/SCRUM-19-mqtt-code-review.md`
  đã nêu nhưng **chưa ai test**: phía simulator thì `stale_state` chặn lại; phía executor
  thì `command_id` mới nên chỉ còn version chặn. Đây là lý do `expected_state_version` là
  **bắt buộc** chứ không tuỳ chọn.

**Stale state (18 test):** đủ 4 nhánh `readiness()`, ngưỡng biên (`>` chứ không phải `>=`),
hồi phục sau khi stale, LWT, snapshot lùi version, và 4 nhánh payload sai schema.

**Realtime (6 test):** client đang mở nhận state mới sau lệnh (trước đây **chỉ** test cú
đẩy đầu tiên lúc kết nối); lệnh bị từ chối không đẩy gì; một client hỏng không chặn client
kia; gỡ listener khi ngắt kết nối; REST và WS thấy cùng `state_version`.

### Deliverables

| Yêu cầu | Trạng thái |
|---|---|
| Bộ test integration MQTT end-to-end | ✅ 4 tầng L0–L3, xem bảng dưới |
| Báo cáo kết quả test | ✅ `eval/results/mqtt-e2e/<run-id>/` — bất biến, có `junit.xml` làm bằng chứng thô |

### Bốn tầng test — và tầng nào chứng minh được gì

| Tầng | Chạy ở đâu | Chứng minh | **KHÔNG** chứng minh |
|---|---|---|---|
| **L0** unit | mọi CI | máy trạng thái thuần | gì về vận chuyển |
| **L1** InMemoryBroker | mọi CI | chuỗi executor→sim→cache→REST/WS, idempotency, stale, realtime | QoS 1 thật, retain qua restart, ACL, LWT, `clean_session` |
| **L2** Mosquitto thật | gated `MQTT_CONTRACT_TESTS=1` — **12/12 pass** | ACL âm, sai password, duplicate thật, `clean_session` qua reconnect, LWT | HTTP/WS thật, hai tiến trình riêng |
| **L3** full-stack | thủ công (`scripts/e2e_mqtt.py` — **chưa viết**) | — | — |

L1 hoàn toàn tất định (InMemoryBroker gọi handler đồng bộ ngay trong `publish`) nên **0
flaky**, nhưng cũng **không bao giờ tạo xen kẽ thời gian thật**. Điểm mù này được ghi thẳng
vào `report.md` của mỗi run, không giấu.

---

## 4. Bằng chứng định lượng

Run `20260809T161533.418052Z` — **148/148 pass**:

| Nhóm AC | Pass |
|---|---:|
| AC1-chain | 66 |
| AC1-chain + AC2-topic | 12 |
| AC2-schema | 7 |
| AC3-idempotency | 14 |
| AC3-realtime | 6 |
| AC3-stale | 18 |
| AC3-state_version | 25 |

Tái lập:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q          # 565 passed, 14 skipped
.\.venv\Scripts\python.exe scripts\report_mqtt_e2e.py   # sinh run mới
```

---

## 5. Phân chia phần việc để tích hợp frontend

### 5.1 Bảng chủ sở hữu

| Vùng | Chủ | Trạng thái |
|---|---|---|
| Xe ảo, MQTT, `GET /vehicle/state`, `/ws/engineer` (kênh `state`) | **Sơn** | ✅ Xong |
| `VehicleGateway` (cổng) | **Sơn** | ✅ Xong — đã bàn giao |
| Nối agent graph vào cổng | **Nhân** | ⏳ Thuộc AC2 ticket HITL |
| `POST /approvals/.../decision`, RAG composer, `citation_id`, `GET /citations/{id}` | **Nhân** | ⏳ |
| `/auth/login`, `/sessions`, `/turns/text` | **Nhân** | ⏳ Nhận 2026-08-10 |
| `GET /healthz`, `ivi_events.py`, `/ws/ivi`, `POST /turns/voice` | **Thành** | ✅ Đã merge |
| IVI Screen, Engineer Dashboard | **Giáp** | ⏳ |

> **Hai đính chính 2026-08-10.** (1) Bảng từng ghi `/ws/ivi` và `ivi_events.py` là của
> Nhân — sai, git xác nhận cả 6 commit đều của Thành. (2) `GET /healthz` từng ghi là của
> Sơn — Thành làm song song và bản của cậu ấy đã vào `develop`; xem mục 10.

> **Ranh giới đã giữ:** không sửa một dòng nào trong `src/agents/`,
> `src/api/approvals.py`, `src/services/ivi_events.py`, `src/rag/`.

### 5.2 Mười hai interface P0 — ai làm gì

| # | Interface | Trạng thái | Chủ | FE gọi ở |
|---:|---|---|---|---|
| 1 | `POST /auth/login` | ❌ 404 | **Nhân** *(nhận 10/08)* | `session/real.ts:73` |
| 2 | `POST /sessions` | ❌ 404 | **Nhân** *(nhận 10/08)* | `session/real.ts:117` |
| 3 | `POST /turns/text` | ❌ 404 | **Nhân** *(nhận 10/08)* | `turn/real.ts:177` |
| 4 | `POST /turns/voice` | ✅ | **Thành** | `turn/real.ts:193` |
| 5 | `POST /approvals/{id}/decision` | ✅ | Nhân | `turn/real.ts:209` |
| 6 | `GET /vehicle/state` | ✅ **Sơn xong** | **Sơn** | `turn/real.ts:170` |
| 7 | `GET /citations/{id}` | ❌ 404 | Nhân | `turn/real.ts:223` |
| 8 | `GET /traces/{id}` | ❌ 404 | **chưa ai** | FE chưa dùng |
| 9 | `GET /metrics/summary` | ❌ 404 | **chưa ai** | `engineer/real.ts:137` |
| 10 | `GET /healthz` | ✅ **Thành xong** (PR #34) | **Thành** | `engineer/real.ts:144` |
| 11 | `WS /ws/ivi` | ⚠️ thiếu 4 event | **Thành** | `turn/real.ts:245` |
| 12 | `WS /ws/engineer` | ⚠️ `state` ✅ (Sơn), thiếu `trace`/`metrics`/`health` | Sơn + chưa ai | `engineer/real.ts:156` |

### 5.3 Ba việc phía Giáp phải sửa để cắm được phần của Sơn

1. **`doors` là `"open"`/`"closed"`, không phải `"unlocked"`/`"locked"`.** Ba chỗ FE đang
   đọc sai: `Car3DViewer.tsx:67-69`, `VehicleControlView.tsx:121`, `RightPanel.tsx:13-15`.
   Không sửa thì xe 3D không bao giờ mở cửa và nút "Mở khoá" bấm xong không đổi gì.
2. **Xử lý HAI shape cho `/healthz`.** Nhánh 200 là `data.components[name].latency_ms`,
   nhánh 503 là `error.details.dependencies[name].code` — khác cả tên khoá lẫn field, và
   đó là đúng spec. `engineer/real.ts:145-148` hiện chỉ đọc `body.data` nên với 503 nó
   throw và AlertBanner mất sạch thông tin đúng lúc cần nhất.
3. **Thêm `.catch()` cho `refreshVehicleState()`** (`DriverShellProvider.tsx:69-71`). Với
   503 nó thành unhandled rejection và `vehicleState` kẹt `null`.

Chi tiết + ví dụ JSON: `docs/handoff/BE-to-FE-vehicle-and-mqtt.md`.

### 5.4 Thứ tự mở khoá cho Giáp

Sắp theo mức chặn, không theo độ khó:

1. **`/auth/login` + `/sessions`** *(chưa ai)* — `authHeaders()` và `currentSessionId()`
   **throw ngay** khi thiếu token/session, nên `/ws/ivi` cũng không kết nối. **Không có hai
   cái này thì mọi thứ khác đều chết, kể cả endpoint đã xong.**
2. **`/turns/text`** *(chưa ai)* — mọi nút bấm trong IVI gọi endpoint này.
3. **`plan.ready`** *(Nhân)* — `HitlModal.tsx:59` đọc `plan.ready.summary`; thiếu thì modal
   hiện "Bạn xác nhận: ?" rỗng.
4. **`/vehicle/state`** *(Sơn)* + **`/healthz`** *(Thành, PR #34)* — ✅ **đã xong**.
5. **Nhân cắm agent vào `VehicleGateway`** — không có bước này thì bước 4 vẫn trả state
   không bao giờ thay đổi sau lệnh giọng nói.
6. **`/metrics/summary` + `/ws/engineer` phát `trace`** *(chưa ai)* — Engineer Dashboard
   trắng vĩnh viễn nếu thiếu.

---

## 6. Nợ đã biết — nói rõ, không giấu

| # | Nợ | Trạng thái | Ghi chú |
|---|---|---|---|
| 1 | 6 test tầng L2 chưa chạy lần nào | ✅ **Đã đóng 2026-08-09** | Đã dựng Mosquitto thật và chạy: **12/12 pass**. Lần chạy đầu bắt được 2 lỗi trong chính test — xem mục 8 |
| 2 | **`/healthz` sẽ luôn trả 503 vì `llm`** — ADR-005 "Not Yet", `slm_enabled=False`, P0 không chạy LLM nào | ⏳ **Còn mở — cần nhóm chốt** | Không phải bug để sửa, mà là sự thật cần một quyết định: (a) Giáp lọc `llm` khỏi AlertBanner, hay (b) sửa `api_spec.md` cho `llm` optional ở P0 kèm ADR. Backend không báo `ready` cho thứ không tồn tại |
| 3 | Không đặt được tốc độ xe khi bật MQTT | ✅ **Đã đóng 2026-08-09** | `SimulatorRuntime.set_motion()` + console của tiến trình xe ảo. Xe tự đặt tốc độ của chính nó nên không đụng ACL. Đã verify E2E: 60 km/h → mở cửa bị `unsafe_vehicle_state` → `stop` → mở cửa được |
| 4 | **Chưa có tầng auth** | ⏳ Còn mở | `GET /vehicle/state` và `/healthz` công khai. Nhóm đã hoãn; ngoài phạm vi SCRUM-54/55 |
| 5 | **Tầng L3 (`scripts/e2e_mqtt.py`) chưa viết** | ⏳ Còn mở | Chưa có bằng chứng qua HTTP/WS thật với hai tiến trình riêng. `scripts/smoke_mqtt.py` hiện có đã làm gần đúng việc này |
| 6 | `mqtt_spec.md:471` mô tả `phase: accepted → completed` nhưng simulator chỉ phát **một** event | ✅ **Đã đóng 2026-08-11 — không phải bug** | Không hề lệch: `mqtt_spec.md` §phase và status đã cho phép tường minh *"simulator được phép chỉ phát `completed`"* ở P0, và câu đó có từ commit gốc `8a8204f` (SCRUM-19), tức trước PR #32. Dòng 471 nằm trong bảng **"Điểm khớp chuẩn"** — nó biện minh cho việc *giữ hai phase trong enum*, không quy định simulator phải phát cả hai. Simulator và enum giữ nguyên. Việc thật sự cần làm nằm ở chỗ khác và đã làm: `ToolExecutor._on_event()` giờ bỏ qua `phase=accepted` thay vì resolve waiter bằng event đầu tiên (issue #50) |

---

## 8. Chạy tầng L2 lần đầu bắt được gì

Đây là lý do "viết test" và "chạy test" không phải một việc.

**Hai test ACL của tôi sai identity.** Tôi giả định "ai ghi topic nào thì đọc lại được
topic đó". `config/mosquitto/acl` tách read/write **không giao nhau**: backend `write
commands` + `read state`, simulator `read commands` + `write state`. Nên watcher của
`state/*` phải là *backend* và watcher của `commands/*` phải là *simulator* — ngược
với trực giác. Đặt nhầm làm **positive control tắt**, và test đỏ vì lý do không liên
quan tới ACL.

**Phát hiện kèm theo, mạnh hơn tài liệu.** `mqtt_spec.md` chỉ nói "không client nào
publish được lên topic của client kia". Thực tế ACL còn chặn **đọc lại thứ chính mình
ghi**: backend không subscribe nổi `commands/#`, simulator không subscribe nổi
`state/#`. Đã ghi thành test riêng
(`test_khong_identity_nao_doc_lai_duoc_thu_minh_ghi`) vì đây là ràng buộc thật đang
tồn tại mà không ai viết ra.

**Console xe ảo chết vì cp1252.** Khi verify cơ chế `set_motion`, tiến trình xe ảo nổ
`UnicodeEncodeError` lúc in dòng hướng dẫn tiếng Việt — cùng lớp bug với hai script
schema, nghĩa là `python -m src.vehicle_sim | tee log.txt` hay `docker logs` trên
Windows sẽ giết xe ảo. Đã vá.

---

## 7. Bốn bug phụ đã sửa trong quá trình làm

1. **`MQTT_ENABLED` mặc định `True`** khiến mỗi `TestClient(app)` chạy lifespan rồi chờ
   `AiomqttClient.start(timeout=10)` — **10 giây trắng mỗi lần**. Đây là toàn bộ chênh lệch
   **205 giây → 27 giây** của suite.
2. **Vỏ lỗi sai ở `routes.py`** — `HTTPException(detail=...)` bọc thêm tầng `detail` nên FE
   đọc `body.error.code` luôn miss. *(Cùng lỗi còn ở `src/api/turns.py:54` — thuộc luồng
   turn của Nhân, đã báo.)*
3. **Hai script schema chết vì `UnicodeEncodeError`** khi stdout là pipe trên Windows (CI,
   `> out.txt`, subprocess) — tức hỏng đúng lúc chúng được chạy tự động. Đã vá bằng
   `sys.stdout.reconfigure`.
4. **`observed_at` có độ phân giải một giây** (`PlainSerializer` `%Y-%m-%dT%H:%M:%SZ`), nên
   snapshot trên dây không byte-identical với state trong bộ nhớ. Hợp đồng vẫn đúng ở mức
   đã serialize — nhưng **đừng dùng field này đo latency**.

---

## 10. Trùng việc `GET /healthz` — và cái giá của bảng phân công sai

Sơn và Thành **cùng làm `GET /healthz`** trong cùng một khoảng thời gian, không ai
biết. Thành mở PR #34 và merge vào `develop` trước; nhánh của Sơn sau đó được
rebase lên `develop`, và bản `/healthz` của Sơn bị bỏ khi giải quyết xung đột.

**Quyết định: giữ bản Thành.** Không phải vì merge trước, mà vì nó tốt hơn ở hai
điểm đo được — tách tầng (`api/health.py` + `services/health.py` + `db.py` thay vì
một file), và **đúng spec hơn ở vỏ 503**: `api_spec.md:495` yêu cầu
`error.details.dependencies` chỉ chứa tên component + trạng thái + mã probe đã che,
trong khi bản Sơn nhét cả object của nhánh 200 vào đó.

Cái mất: 11 test của Sơn, và `~290` dòng probe viết inline. Cái còn dùng được từ
bản Sơn là khai `ErrorEnvelope` cho OpenAPI — bản Thành chưa có, đã báo lại chứ
không tự sửa vào file của cậu ấy.

**Vì sao xảy ra.** `/healthz` không nằm trong AC của SCRUM-54 — Sơn làm thêm vì
thấy frontend gọi và nhận 404. Đó là thiện chí, nhưng làm ngoài AC mà không tuyên
bố thì không ai chặn được trùng lặp. Bảng phân công lúc đó cũng ghi `/healthz` là
của Sơn, và bảng đó do chính Sơn viết từ suy luận chứ không hỏi ai.

Hai bài học, cả hai đều là quy trình chứ không phải kỹ thuật:

1. **Làm ngoài AC thì phải tuyên bố trước**, dù chỉ một dòng ở standup. Chi phí
   một dòng nhỏ hơn nhiều so với hai người viết cùng một endpoint.
2. **Bảng phân công phải suy từ lịch sử commit, không từ ticket.** Đây là lần thứ
   hai cùng một lỗi trong một tuần — lần trước là `/ws/ivi` và `ivi_events.py` bị
   gán nhầm cho Nhân trong khi Thành đã merge xong (mục 9, điểm d).

---

## Tài liệu liên quan

- `docs/handoff/frontend-integration-map.md` — bản đồ đầy đủ 12 interface + 20 event, mục
  **ĐÃ RÕ** và **CHƯA RÕ** (10 câu hỏi cần chốt ở standup)
- `docs/handoff/vehicle-gateway-for-agent.md` — hướng dẫn migrate cho Nhân
- `docs/handoff/BE-to-FE-vehicle-and-mqtt.md` — hợp đồng cho Giáp
- `docs/adr/ADR-013-single-vehicle-state-source.md` — quyết định và cái giá của nó

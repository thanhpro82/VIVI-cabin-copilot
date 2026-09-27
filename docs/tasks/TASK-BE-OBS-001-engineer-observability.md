# TASK-BE-OBS-001 — Observability backend cho Engineer Dashboard

> **Status: In progress.** Chủ: **Sơn**. Bắt đầu 2026-08-10.
> Phạm vi: `GET /api/v1/traces/{trace_id}` (interface #8), `GET /api/v1/metrics/summary` (#9),
> và 3 event còn thiếu của `WS /ws/engineer` (#12): `trace`, `metrics`, `health`.
> Spec authority: [api_spec.md](../api_spec.md) §Trace/§Metrics/§WebSocket contracts,
> [agent_spec.md](../agent_spec.md):143, [technical_spec.md](../technical_spec.md):74.
> Đối chiếu: [frontend-integration-map.md](../handoff/frontend-integration-map.md),
> [TASK-FE-BE-001](TASK-FE-BE-001-ivi-e2e-integration-requirements.md) (Giáp).

**File này tồn tại để trả lời đúng một câu hỏi: chỗ nào tôi làm được một mình, chỗ nào phải
chờ người khác.** Không lặp lại spec.

---

## 0. Chốt hai câu hỏi đang treo

**(a) Ai giữ `/ws/engineer`?** Giáp hỏi trong TASK-FE-BE-001 §"Bug mới phát hiện": *"Chưa rõ
nộp cho ai... Cần 1 câu trả lời ở standup."* Câu trả lời:

| Handler trong `src/api/ws.py` | Chủ |
|---|---|
| `engineer_stream` (`/ws/engineer`) | **Sơn** — cả `state` lẫn `trace`/`metrics`/`health` |
| `ivi_stream` (`/ws/ivi`) | **Thành** — kèm buffer/replay, sequence-per-session, WS auth |

Hai handler ở chung một file nhưng **không chung dòng nào**. Sơn không sửa `ivi_stream`.

**(b) `GET /traces/{id}` có bỏ khỏi P0 không?** Giáp đề xuất bỏ vì *"không ai gọi"*
(TASK-FE-BE-001 §"Không nằm trong scope"). **Giữ lại.** Lý do:

- Event WS `trace` bắt buộc dùng **đúng schema** của GET (`api_spec.md:607`, và acceptance test
  `:662` đòi *"GET and Engineer WS trace schemas expose the same exact safe fields"*). Nghĩa là
  `TraceRecord` + hàm serialize phải viết dù sao. Route GET chỉ là ~20 dòng nữa.
- Nó là đường **phục hồi sau khi WS mất kết nối quá cửa sổ replay** (`api_spec.md:646`) — đúng
  thứ Thành sắp làm. Bỏ bây giờ thì tháng sau phải làm lại.

---

## 1. Kiến trúc: một kho, ba khung nhìn

`docs/handoff/frontend-integration-map.md:99` mô tả đúng hiện trạng:

> "Backend phát `state` mà FE không đọc; FE chờ `trace` mà backend không phát. Kết quả:
> Engineer Dashboard trắng vĩnh viễn dù WebSocket kết nối thành công."

Ticket yêu cầu *"reuse existing trace/health/metrics data sources, không tạo state song song"*.
Đã quét: **không có nguồn nào để reuse, trừ health.**

- `trace_id` có mặt khắp nơi nhưng **chỉ là chuỗi tương quan** — không `TraceSpan`, không store,
  không buffer. `AgentState` (`src/agents/state.py`) thậm chí không có field `trace_id`.
- Không một counter runtime nào. `src/agents/eval.py:61` và `src/rag/evaluate.py:62` có
  aggregate nhưng là **batch CLI ghi ra đĩa**, không dùng cho endpoint live được.
- 8 probe trong `src/services/health.py` là thứ **duy nhất** reuse được thật.

Nên "không tạo state song song" được hiện thực hoá thành:

```
turns.py ──┐
approvals ─┼─→ IviEventBus.publish ─┬─→ /ws/ivi        (Thành, KHÔNG đổi)
ivi_events ┘                        └─→ TraceCollector (Sơn, MỚI)
                                            │
                                            ▼
                                       TraceStore ──┬─→ GET /traces/{id}
                                     (bounded, LRU) ├─→ GET /metrics/summary  (fold)
                                                    └─→ WS event `trace`

  services/health.collect_health() ───────────────┬─→ GET /healthz  (đã có, không đổi hành vi)
  (8 probe đã có, MỘT sampler dùng chung)         └─→ WS event `health`
```

`/metrics/summary` **không có biến đếm riêng** — nó là hàm thuần fold trên các `TraceRecord`
trong cửa sổ. Thêm metric mới về sau = thêm một phép fold, không phải nhớ tăng counter ở 5 chỗ.

### Vì sao thu trace bằng cách NGHE bus thay vì sửa `emit_turn_lifecycle`

Hướng hiển nhiên là seal trace bên trong `emit_turn_lifecycle`. Đã bỏ, vì hai lý do — lý do thứ
hai mới là lý do chính:

1. `src/services/ivi_events.py` là file của Thành và **đang có 2 PR sửa cùng lúc** (#36, #37).
2. **Nghe bus bắt được nhiều hơn.** Hai đường thoát lỗi trong `turns.py` — `STT_FAILED`
   (`:124`) và `INTERNAL_ERROR` (`:174`) — publish `turn.failed` thẳng lên bus và **không đi
   qua `emit_turn_lifecycle`**. Sealing bên trong `emit_turn_lifecycle` sẽ đếm thiếu
   `turns.failed`; listener trên bus thì không.

---

## 2. Ba tầng phụ thuộc — **phần quan trọng nhất của tài liệu này**

### TIER 1 — 100% của Sơn. Không chạm file ai. Làm ngay, không chờ PR nào.

~85% khối lượng. Toàn file mới, trừ 3 chỗ nhỏ.

| File | Việc | Trạng thái |
|---|---|---|
| `src/services/trace_store.py` (MỚI) | `StageTimings`, `TraceRecord`, `TraceStore` bọc `BoundedCache` | ⬜ |
| `src/services/trace_collector.py` (MỚI) | Listener bus → dựng `TraceRecord` | ⬜ |
| `src/services/metrics.py` (MỚI) | `build_metrics_summary()` — fold thuần, 8 nhóm | ⬜ |
| `src/models/observability.py` (MỚI) | Pydantic mirror `api_spec.md:330-380` + `:386-450` | ⬜ |
| `src/api/observability.py` (MỚI) | 2 route REST | ⬜ |
| `src/services/engineer_events.py` (MỚI) | Bus broadcast + sampler dùng chung | ⬜ |
| `src/services/health.py` | Trích `collect_health()` từ `api/health.py:44-56` | ⬜ |
| `src/api/ws.py` — **chỉ `engineer_stream`** | Nối bus, snapshot lúc connect, sửa bug double-close | ⬜ |
| `src/main.py`, `src/config.py` | 1 dòng `include_router`; 4 setting | ⬜ |

**Sửa luôn bug Giáp báo** (`ws.py:79-83`): `await websocket.close(1003)` trên socket đã chết tự
ném `WebSocketDisconnect` lần hai → traceback rác đầy console server (dễ gặp ở dev vì React
StrictMode mount/unmount 2 lần). Bọc `try/except`.
`ivi_stream` có **đúng cùng lỗi** ở `:161-163` — của Thành, **báo chứ không tự vá**.

### TIER 2 — chạm file người khác. Additive nhỏ, không đổi hành vi. Báo trước khi mở PR.

| File | Chủ | ~Dòng | Việc | Không có thì mất gì |
|---|---|---:|---|---|
| `src/services/ivi_events.py` | **Thành** | 8 | `IviEventBus.add_global_listener()` / `remove_global_listener()`. Additive thuần, **không đụng `emit_turn_lifecycle`** | **Không có trace nào cả** → toàn bộ Tier 1 vô dụng. Đây là phụ thuộc chặn duy nhất |
| `src/agents/graph.py` | **Nhân** | 12 | Wrapper `_timed(stage, fn)` bọc node `rag`/`slm`/`validate`/`safety` | `stage_latencies_ms.planning_or_retrieval` và `.safety` = `null` |
| `src/agents/state.py` | **Nhân** | 1 | Thêm field `trace_id: str` vào `AgentState` | như trên (wrapper không biết ghi vào trace nào) |
| `src/api/turns.py` | **Thành** | 4 | Truyền `trace_id` vào graph input; bắt `transcript.latency_ms` (**đang bị vứt** ở `:133`); đo `end_to_end` | `stage_latencies_ms.stt` và `.end_to_end` = `null` |

```python
# src/agents/graph.py — additive, không sửa thân node nào, không đổi edge nào
def _timed(stage: str, fn):
    async def wrapped(state):
        started = time.perf_counter()
        try:
            return await fn(state)
        finally:
            if tid := state.get("trace_id"):
                get_trace_store().record_stage(tid, stage, (time.perf_counter() - started) * 1000)
    return wrapped
```

Hai chi tiết dễ sai:

- **Ghi thẳng ra `TraceStore`, không ghi vào `AgentState`.** `AgentState` là `TypedDict` không
  có reducer; hai node cùng ghi một key sẽ đè nhau.
- **`record_stage` là last-write-wins, KHÔNG cộng dồn.** LangGraph chạy lại thân node từ đầu
  khi resume approval (xem docstring `src/agents/approval.py:9`), cộng dồn sẽ nhân đôi số đo.

### TIER 3 — cần người khác làm. Sơn không tự làm được.

| Cần gì | Ai | Vì sao không tự làm | Tạm thời chạy thế nào |
|---|---|---|---|
| `require_engineer` trong `src/api/auth_deps.py` | **Thành (PR #37)** | File chưa có trên `develop`; #37 mới chỉ có `require_driver`. Thêm hộ = sửa file đang review | `/metrics/summary` chưa gắn RBAC. Đánh `TODO` + test ghi nhận hiện trạng |
| `trace_id` xuyên suốt HITL | **Nhân (PR #36)** | `src/api/approvals.py:55,95` **đúc `trace_id` mới** khi resume graph → nửa sau lượt S2 mang trace khác nửa đầu. Cần thêm `trace_id` vào `ApprovalRecord`. Đây là logic HITL | Trace của lượt S2 đứt làm hai bản ghi; `approval_wait_ms = null` |
| Auth + role cho WS | **Thành** (đã nhận) | Thành đang làm replay/sequence/WS auth | `/ws/engineer` chưa kiểm role. Cờ `AUTH_ENABLED` trong `ws.py:10` hiện là **cờ ma** — không có trong `src/config.py` |
| Chốt `/healthz` luôn 503 vì `llm` | **Cả team** | Quyết định hợp đồng, không phải kỹ thuật (TASK-FE-BE-001 §"Cần cả team chốt") | Event `health` mang `status != "ready"` — **đúng sự thật, không phải bug** |

> 🐞 **Bug độc lập gửi Nhân**: `trace_id` mới ở `approvals.py:55,95` đã làm hỏng tương quan
> trên `/ws/ivi` **hôm nay**, không riêng ticket này. Sự kiện `turn.canceled` sau khi từ chối
> approval mang `trace_id` khác `turn.accepted` của cùng lượt đó.

---

## 3. Hợp đồng suy giảm — dashboard sống với bất kỳ tổ hợp nào

Nguyên tắc: **thiếu dữ liệu thì trả `null`, không bao giờ trả `0` giả.** FE đã khai đúng kiểu
`p50: number | null` (`frontend/src/lib/services/engineer/real.ts:41`), nên `0` sẽ vẽ ra biểu
đồ phẳng nói dối — tệ hơn ô trống.

| Tổ hợp đã về | `/traces/{id}` | `/metrics/summary` | WS |
|---|---|---|---|
| Chỉ Tier 1 | ❌ 404 mọi trace | 8 nhóm, tất cả `0`/`null` | `health` + `metrics` chạy; `trace` không bao giờ bắn |
| + hook bus (Thành, 8 dòng) | ✅ đủ trừ stage latency | ✅ đủ trừ `stage_latency_ms` | ✅ đủ 5 event |
| + `trace_id` + `_timed` (Nhân) | ✅ đủ | ✅ đủ | ✅ đủ |
| + `turns.py` (Thành) | ✅ + `stt`/`end_to_end` | ✅ + p50/p95 end-to-end | ✅ |

**8 dòng của Thành là ranh giới giữa "vô dụng" và "gần đủ".** Ưu tiên xin trước.

Luôn `null` ở P0, **có chủ ý, không phải thiếu sót**:

- `model_runtime.*` — `slm_enabled=False` (`src/config.py:32`), chưa từng nạp weight thật.
  `model_profile = "not-selected"`. `api_spec.md:464` cho phép rõ. Bịa tokens/s ở đây phá kỷ
  luật chứng cứ của repo.
- `stage_latencies_ms.tts = 0` — Piper có `synthesize()` nhưng **không caller nào trong turn
  path gọi**. Số 0 là sự thật.
- `rag.faithfulness_*` — `api_spec.md:460` cấm rõ *"never an unreviewed live-model
  self-score"*. Chỉ đến từ rubric có người chấm.

---

## 4. Ba điểm spec IM LẶNG — đã chốt, phải ghi ngược vào `api_spec.md`

| Điểm | Spec nói gì | Chốt | Ghi vào |
|---|---|---|---|
| Cửa sổ metrics | chỉ có `[from,to)` nửa mở UTC; **không** định nghĩa query param nào | Rolling **3600s**: `from = max(boot, now−window)`, `to = now`. Config `METRICS_WINDOW_SECONDS`. Không thêm query param | `api_spec.md:452` |
| Nhịp phát WS | liệt kê đủ payload, **không** nói trigger | `trace` theo sự kiện (lượt seal); `metrics` mỗi 5s; `health` mỗi 10s. **Một sampler dùng chung mọi kết nối**, không phải mỗi socket một cái | `api_spec.md:602` |
| Mã 404 | taxonomy 16 mã **không có** `NOT_FOUND` | Thêm `NOT_FOUND` (404) cho trace lạ. Không dùng 403 giả làm "không lộ sự tồn tại" — hệ thống chưa có auth thì 403 chỉ là diễn | `api_spec.md:649` |

Đây cũng là câu trả lời cho **câu hỏi mở #4** của `frontend-integration-map.md:169` (*"`/ws/engineer`
có phát `trace` cho mọi turn của mọi tài xế không?"*) → **có**, engineer là fleet-scoped:
`api_spec.md:531` chốt `connection.init` của `/ws/engineer` **bỏ** `session_id`.

Hai thứ khác cần ghi:

- **Percentile** dùng nearest-rank (`index = ceil(p/100 × n) − 1`). Spec không định nghĩa thuật
  toán; không ghi thì p95 trên mẫu nhỏ không tái lập được.
- **`mqtt.publish_attempts` là xấp xỉ**: bằng số bước đã thực thi, **không phải** số publish thô
  lên broker — retry QoS 1 nằm dưới tầng trace và không nhìn thấy được. Counter thật ở
  `MqttVehicleGateway` là việc nối tiếp.

---

## 5. Va chạm với 3 PR đang mở (quét 2026-08-10)

| PR | Người | Nhánh | Ảnh hưởng |
|---|---|---|---|
| #37 | Thành | `feature/core-driver-apis` | Thêm auth thật (`services/auth.py`, `api/auth_deps.py`), `request_scoped_ids()` trong `context.py`, `RequestValidationError` handler. Sửa `turns.py` (+223), `models/api.py` (+112), **đã nâng bảng khoá path OpenAPI 4 → 7** |
| #36 | Nhân | `feature/hitl-e2e-ws-ivi` | `build_graph(vehicle: VehicleSimulator)` → `build_graph(gateway: VehicleGateway)`; **xoá `src/agents/vehicle.py`**; `ToolResult` thêm `observed_state_version`; `emit_turn_lifecycle` thêm `plan.ready` + outcome mới `vehicle_state_unavailable` |
| #35 | Giáp | `fix/fe-engineer-real-mode-bugs` | `HealthStatus.checkedAt` → `string \| null`, `latencyMs` → optional; thêm `toBase64Url()` cho subprotocol |

⚠️ **#36 và #37 xung đột với NHAU** trên `src/services/ivi_events.py`: #37 đổi
`_assistant_response_payload` → `assistant_response_payload` (public), #36 giữ tên cũ và thêm
58 dòng quanh nó. Hai bạn tự gỡ — ticket này cố tình **không** thành bên thứ ba sửa file đó.

**Thứ tự merge đề xuất:** #36 và #37 vào `develop` trước, rồi nhánh này rebase lên. Tier 1 làm
song song ngay từ bây giờ vì không chạm file nào của họ.

**Ảnh hưởng cụ thể phải xử lý sau rebase:**

- `_timed` bọc node trong `graph.py` — chữ ký `build_graph()` đổi, wrapper không bị ảnh hưởng.
- `TraceCollector` phải xử lý event `plan.ready` (mới, #36) và outcome `vehicle_state_unavailable`
  (mới, #36 → `turn.failed` với code `MQTT_UNAVAILABLE`).
- `tool.result` payload đổi từ `step.after.get("state_version")` sang `step.observed_state_version`
  (#36) — collector đọc từ payload event nên **không** ảnh hưởng.
- `tests/test_api/test_routes.py:50` — path lock 7 → 9.

---

## 6. Redaction — ràng buộc load-bearing, không phải checklist

`api_spec.md:11`, `:382`, `:464`, `:612` đều cấm: raw prompt, chain-of-thought, raw audio,
unrestricted transcript, credential, secret path. `api_spec.md:662` đòi có **privacy test**.

**Điểm nguy hiểm duy nhất là `safe_summary`.** Nó phải là hàm thuần của
`(outcome, intent, tên tool, số bước)` — ví dụ `"Chờ xác nhận 1 thao tác cửa kính"` — và
**tuyệt đối không** lấy từ `query` / `normalized_text` / `response_text`.

Cách bảo đảm bằng cấu trúc chứ không bằng kỷ luật: `TraceRecord` **không có field** cho ba thứ
đó, và `TraceCollector` chỉ đọc `confidence` + `len(citations)` từ payload sự kiện. Không lưu
thì không rò.

`test_observability_privacy.py` dump JSON của cả trace lẫn metrics và assert không chứa chuỗi
transcript đã đưa vào.

## 7. Event `health` trên WS dùng shape 200, KHÔNG phải 503

`api_spec.md:609` chốt payload `health` khớp **health GET schema** — tức nhánh 200, có đủ
`checked_at` và `components[].latency_ms`. Khi có component down, event WS **vẫn** mang đủ hai
field đó với `status: "down"`; **không** dùng envelope 503 (`error.details.dependencies`).

Giáp vừa thêm `mapHealthFromErrorDetails()` trong PR #35 cho nhánh **REST 503** — đó là đường
khác, đừng lẫn. FE `mapHealth()` (đường WS) vẫn cần `checked_at` + `latency_ms`.

## 8. Kiểm chứng

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
#   MQTT_ENABLED=false không phải để nhanh: để mặc định thì mỗi TestClient(app)
#   chờ broker 10s. Mốc develop trước ticket: 603 passed, 15 skipped, ~31s.
ruff check src/ tests/ ; ruff format --check src/ tests/
.\.venv\Scripts\python.exe -m src.serve   # KHÔNG dùng `uvicorn src.main:app` trên Windows
```

| File test mới | Nội dung |
|---|---|
| `tests/test_api/test_traces.py` | shape đúng `set(...)`; 3 mệnh đề "has exactly" của `api_spec.md:382`; 404 `NOT_FOUND` |
| `tests/test_api/test_metrics_summary.py` | đủ **8** nhóm; cửa sổ rỗng → count `0` nhưng rate/percentile **`null`**; nearest-rank trên mẫu nhỏ |
| `tests/test_services/test_trace_collector.py` | dựng trace từ luồng sự kiện giả; **cả 2 đường lỗi của `turns.py`** đều seal |
| `tests/test_api/test_ws_engineer_events.py` | đủ 5 loại event; `sequence` tăng đơn điệu qua cả 5; sampler dừng khi listener cuối rời; close() 2 lần không ném |
| `tests/test_api/test_observability_privacy.py` | dump JSON trace + metrics, assert **không chứa** transcript đã đưa vào |

Dùng `receive_n` ở `tests/test_api/ws_helpers.py:8` — `receive_json()` không có timeout và sẽ
treo cả suite.

**End-to-end thật** (đây mới là AC *"FE Engineer Dashboard có dữ liệu thật thay vì blank/mock"*):

```powershell
.\.venv\Scripts\python.exe -m src.serve                                # terminal 1
cd frontend; $env:NEXT_PUBLIC_USE_MOCK_ENGINEER="false"; npm run dev   # terminal 2
# http://localhost:3000/engineer → StatTileRow có số, bảng log có dòng sau mỗi lượt
```

## 9. Ngoài phạm vi

Auth/RBAC đầy đủ, replay cursor, sequence-per-session (**Thành đã nhận**); persist trace xuống
SQLite (`data_model.md:304` đòi 30 ngày — kho này in-memory, mất khi restart, cùng loại nợ với
approval store); `responses={503:...}` của `/healthz` (khoảng trống của Thành, đã có test ghi
nhận ở `tests/test_api/test_routes.py:76`); counter MQTT tầng broker; event `ui.policy`;
`GET /citations/{id}`.

**Chưa có ADR chống lưng cho ranh giới "Engineer chỉ xem aggregate an toàn".** Đã quét 13 ADR —
không cái nào. `docs/product_brief.md:66` chỉ dựa vào văn xuôi trong spec. Đây là lỗ hổng quyết
định có thật, đáng mở ADR-014.

# Thiết kế: Luồng HITL xác nhận lệnh nhạy cảm trong LangGraph

> Ngày: 2026-08-08. Trạng thái: Đã duyệt, đã có implementation plan.
> Branch: `feature/hitl-safety-confirmation`, nhánh từ `develop` @ `ddb951e`
> (PR #23 đã merge, nên `contracts.py`/`policy.py`/`vehicle.py`/`graph.py` mà việc
> này phụ thuộc đều đã có trên `develop`).
> Authority: [ADR-006](../../adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md),
> [ADR-010](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md),
> [`safety_and_hitl.md`](../../safety_and_hitl.md), [`api_spec.md`](../../api_spec.md).
> Việc trước: [thiết kế agent graph](2026-08-08-agent-graph-vehicle-tools-design.md).

## Bối cảnh & quyết định

Branch trước dừng ở chỗ: `policy.materialize_action_plan()` đã gán `safety_level` và
suy ra `requires_approval`, nhưng node `safety` cho plan cần approval đi thẳng
`compose` với outcome `approval_required` — chưa có cơ chế xác nhận. Branch này cắm
`request_approval` vào đúng chỗ đó.

Ticket yêu cầu: phát hiện lệnh nguy hiểm, trả `PENDING_HITL` kèm `hitl_action_id`, tự
hủy khi timeout, và `POST /api/v1/hitl/confirm` — route cuối **không làm**, xem bảng dưới.

Ba quyết định đã chốt, hai trong đó lệch khỏi nguyên văn ticket (lý do đầy đủ trong
[ADR-010](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md)):

| Ticket | Thiết kế này | Lý do |
|---|---|---|
| Kích hoạt khi `speed_kph > 5` | Window → HITL ở **mọi** tốc độ. Door/seat position khi `speed_kph > 0` hoặc `gear ≠ P` → **S3, chặn thẳng, không popup** | `safety_and_hitl.md` §Classification rules + §Required safety tests #6, #12 |
| `timeout_seconds: 5` | `Settings.hitl_timeout_seconds`, mặc định **30** | `safety_and_hitl.md` §P0 mixed-plan: "expiry mặc định là 30 giây" |
| Chỉ `POST /api/v1/hitl/confirm` | **Chỉ** `POST /api/v1/approvals/{approval_id}/decision` | Trưởng nhóm chốt 2026-08-08 trên PR #23: giữ canonical naming end-to-end, không duy trì alias Họ A. `hitl_action_id` của ticket chính là `approval_id` |

Tốc độ hiện tại vẫn xuất hiện trong câu hỏi xác nhận ("Xe đang chạy 45 km/h. Bạn có
chắc chắn muốn mở hết cửa kính không?") — đúng UX ticket mô tả, nhưng là **nội dung
hiển thị**, không phải điều kiện phân loại.

## Kiến trúc & thành phần

```
src/agents/
  approval.py    ApprovalRecord · ApprovalStore · decide()
  nodes/
    approval.py  request_approval node (interrupt)
  graph.py       cắm request_approval giữa safety và execute
src/api/
  approvals.py   POST /api/v1/approvals/{approval_id}/decision  (canonical, duy nhất)
src/config.py    hitl_timeout_seconds = 30
```

### approval.py — ApprovalRecord & ApprovalStore

`ApprovalRecord` là Pydantic model **không** `frozen` (Pydantic khóa cả model chứ không
khóa từng field). Bất biến được giữ bằng quy ước có test: chỉ `ApprovalStore` được ghi,
và chỉ ghi `status`/`decided_at`; mọi field binding khác ghi một lần lúc `create()`.
Test `test_approval_store.py` assert các field binding không đổi qua toàn bộ vòng đời.

| Field | Ý nghĩa |
|---|---|
| `approval_id` | ULID-like. Ticket gọi nó là `hitl_action_id`; cùng một giá trị |
| `session_id`, `plan_id`, `turn_id` | binding, immutable |
| `plan_digest` | `plan_digest(action_plan)` từ branch trước |
| `approved_vehicle_state_version` | snapshot tại lúc tạo request |
| `created_at`, `expires_at` | `expires_at = created_at + hitl_timeout_seconds` |
| `status` | `pending` → `approved` \| `rejected` \| `expired` \| `invalidated` → `consumed` |
| `prompt_text` | câu hỏi voice-first đã dựng sẵn |
| `steps_summary` | danh sách `{tool, target, before, after}` cho card IVI |

`ApprovalStore` in-memory (`dict` + `threading.Lock`):

- `create(record)` — **từ chối** nếu session đã có record `pending`, raise
  `ApprovalAlreadyPending`. Đây là bản in-memory của partial unique constraint mà
  `safety_and_hitl.md` yêu cầu; kiểm tra nằm **trong** lock, không phải check-then-act.
- `get(approval_id)` — trước khi trả về, nếu `status == "pending"` và
  `now >= expires_at` thì CAS `pending → expired`. **Hết hạn được phát hiện tại thời
  điểm đọc**, không cần worker nền.
- `decide(approval_id, approve: bool)` — chỉ hợp lệ trên `pending` chưa hết hạn; kết
  quả là `approved`/`rejected`. Gọi lại lần hai trên record đã terminal → trả trạng
  thái đã có, không đổi gì (idempotent, chống replay).
- `consume(approval_id)` — `approved → consumed`, một lần duy nhất.

**Vì sao in-memory:** `develop` chưa có tầng persistence nào đang chạy
(`database_url` trong config chưa được dùng). Thêm SQLite ở đây là mở rộng scope sang
việc của WS4. Đánh đổi được ghi rõ: restart server làm mất pending approval — chấp
nhận được cho demo, và `safety_and_hitl.md` không cấm (nó chỉ yêu cầu atomic + partial
unique, cả hai đều đạt được bằng lock trong tiến trình đơn). Ghi vào §Consequences.

### nodes/approval.py — request_approval

```
safety ─ có S2 ──→ request_approval ─┬─ approved ────→ execute
                                      └─ khác ────────→ compose
```

1. Dựng `ApprovalRecord` từ `ActionPlan` + snapshot, gọi `store.create()`.
   `ApprovalAlreadyPending` → outcome `approval_already_pending`, đi `compose`,
   **không** tạo plan/approval/side effect.
2. `interrupt({...})` — payload gồm `approval_id`, `plan_id`, `expires_at`,
   `prompt_text`, `steps_summary`, `timeout_seconds`. Graph dừng tại đây; API trả
   `PENDING_HITL`.
3. Khi resume bằng `Command(resume={"approval_id": ..., "decision": ...})`, node
   **đọc lại `store`** (không tin payload resume) và kiểm 4 điều kiện, **fail closed**:

| Kiểm tra | Outcome khi hỏng |
|---|---|
| `status == "approved"` | `approval_rejected` / `approval_expired` tùy status thật |
| `plan_digest(state.action_plan) == record.plan_digest` | `approval_invalidated_plan` |
| `vehicle.state["state_version"] == record.approved_vehicle_state_version` | `approval_invalidated_state` |
| predicate an toàn còn đúng (đọc lại snapshot, chạy lại `materialize_action_plan`, kết quả phải giống hệt) | `approval_predicate_failed` |

Cả 4 đường hỏng đều đi `compose` với **zero side effect**, approval **không** bị
consume. Chỉ khi cả 4 pass mới `store.consume()` rồi sang `execute`.

Kiểm tra predicate lần cuối là chỗ chặn kịch bản: xe đứng yên → xin mở cửa → S2 →
trong lúc chờ xác nhận xe lăn bánh → lẽ ra phải thành S3. Không có bước này thì
approval cũ hợp thức hóa một action S3.

### graph.py

`build_graph(vehicle, planner=None, rag=rag_node, approvals=None, checkpointer=None)`.

- `checkpointer` bắt buộc khác `None` khi dùng HITL (`InMemorySaver()` mặc định) —
  `interrupt()` không hoạt động nếu thiếu.
- Mỗi turn chạy với `config={"configurable": {"thread_id": session_id}}`.
- `route_after_safety` thêm nhánh: có S3 → `compose`; `requires_approval` →
  `request_approval`; còn lại → `execute`.

### API

**Chỉ một route, canonical** (trưởng nhóm chốt 2026-08-08, PR #23). Ticket SCRUM-18
yêu cầu `POST /api/v1/hitl/confirm`; **không làm route đó**. WS4 dùng
`docs/api_spec.md` làm nguồn sự thật duy nhất cho endpoint, và `/approvals/{id}/decision`
là một trong 12 interface P0.

**`POST /api/v1/approvals/{approval_id}/decision`**:

```
request  { "decision": "approve" | "reject", "approved_vehicle_state_version": 7 }
response { "approval_status": "consumed", "plan_status": "executed", "tool_results": [...] }
```

`approval_status` ∈ `consumed` | `rejected` | `expired` | `invalidated`.
`plan_status` ∈ `executed` | `canceled`. Không tồn tại trường hợp im lặng: mọi đường
fail-closed đều có mã riêng, vì IVI không được phép hiểu nhầm là đã thực hiện.

`hitl_action_id` mà ticket mô tả **chính là** `approval_id` — cùng một giá trị, không
phải hai định danh.

**`POST /api/v1/agent/process`** mở rộng: khi graph dừng ở `interrupt`, trả

```json
{ "status": "PENDING_HITL", "intent": "window_position",
  "response_text": "Xe đang chạy 45 km/h. Bạn có chắc chắn muốn mở hết cửa kính không?",
  "hitl_pending": true, "hitl_action_id": "act_...", "timeout_seconds": 30 }
```

Khớp đúng Case 2 trong `VIVI_API_Spec.md`, trừ `timeout_seconds` (30 thay vì 5).

## Timeout — cơ chế và giới hạn

Hết hạn được quyết tại **thời điểm đọc** (`store.get()` CAS `pending → expired`), không
bằng worker nền. Hệ quả trung thực cần ghi rõ:

- Nếu **không ai** gọi `/approvals/{id}/decision` và **không ai** đọc record, graph vẫn treo ở
  `interrupt` cho tới khi có người đọc. Không có event tự phát ra lúc `expires_at`.
- Đủ cho AC "tự động hủy lệnh nếu timeout": mọi đường dẫn tới quyết định đều đi qua
  `store.get()`, nên **không có cách nào** approve một record quá hạn.
- `turn.canceled(reason="approval_expired")` chủ động (deadline worker trong
  `safety_and_hitl.md`) cần WebSocket — WS4 sở hữu, ngoài scope. Ghi vào §Ngoài phạm vi,
  không implement nửa vời.

## Testing

| File | Nội dung |
|---|---|
| `tests/test_agents/test_approval_store.py` | Một pending/session; `create` thứ hai raise; hết hạn phát hiện lúc `get`; `decide` idempotent; `consume` một lần |
| `tests/test_agents/test_hitl_node.py` | S2 → `interrupt` với payload đủ field; approve → execute; reject/expire/digest lệch/version lệch/predicate hỏng → 5 outcome đúng tên và `vehicle.command_count == 0` |
| `tests/test_agents/test_hitl_safety.py` | Ánh xạ trực tiếp `safety_and_hitl.md` §Required safety tests **#2, #4, #5, #6, #12, #17, #19** — mỗi test ghi rõ số hiệu nó phủ |
| `tests/test_api/test_approval_routes.py` | `/approvals/{id}/decision` trả đúng 4 `approval_status`; approve hai lần không chạy lệnh hai lần; route dev-only `/agent/process` trả `PENDING_HITL` + `approval_id` |

Test timeout **bơm đồng hồ** (inject `clock: Callable[[], datetime]` vào `ApprovalStore`),
không `sleep`.

## Error handling

| Tình huống | Kết quả |
|---|---|
| `hitl_action_id` không tồn tại | `NOT_FOUND`, không resume graph |
| Approve một record đã `consumed` | trả trạng thái đã có, zero side effect (chống replay) |
| S2 thứ hai khi đã có pending | `approval_already_pending`, không tạo plan/approval/group |
| Có S3 trong plan | chặn **trước** khi tạo approval — không bao giờ hiện popup |
| Graph resume nhưng thread không còn checkpoint | `INVALIDATED`, không đoán lại plan |

## Documentation

- `docs/adr/ADR-010-...` — đã viết ở branch trước, bao trùm cả branch này.
- `WORKLOG.md` + `JOURNAL.md` — cập nhật khi work land.
- `README.md` — trạng thái HITL kèm chỉ dẫn tới test phủ `safety_and_hitl.md` §Required
  safety tests. Không tuyên bố phủ hết 19 test khi mới phủ 7.

## Ngoài phạm vi (out of scope)

- **Voice approval intent** (`approval.intent.detected`, xác nhận bằng giọng nói) —
  cần STT, thuộc đầu việc voice.
- **Deadline worker chủ động + `turn.canceled` qua WebSocket** — WS4 sở hữu.
- **SQLite persistence cho approval** — in-memory; restart mất pending.
- **Mixed-plan bundled approval nhiều S2** — cấu trúc đã hỗ trợ (một approval bind cả
  plan), nhưng router hiện chỉ sinh plan một step, nên chưa có case thật để test. Ghi
  nhận, không giả vờ đã phủ.
- **12 test còn lại** trong `safety_and_hitl.md` §Required safety tests (#1, #3, #7–#11,
  #13–#16, #18) — phần lớn cần executor nhiều step, MQTT, hoặc voice.

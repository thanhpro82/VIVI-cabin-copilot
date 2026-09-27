# Thiết kế: Agent LangGraph + 5 bộ tool điều khiển xe

> Ngày: 2026-08-08. Trạng thái: Đã duyệt (brainstorming), chờ implementation plan.
> Branch: `feature/agent-langgraph-vehicle-tools` (từ `develop` @ `346f914`).
> Authority: [ADR-006](../../adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md),
> [ADR-010](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md),
> [`agent_spec.md`](../../agent_spec.md), [`safety_and_hitl.md`](../../safety_and_hitl.md).
> Việc kế tiếp (branch riêng): [thiết kế HITL](2026-08-08-hitl-safety-confirmation-design.md).

## Bối cảnh & quyết định

`src/agents/` trên `develop` hiện là boilerplate AI20K: `graph.py` có đúng hai node
`analyze`/`respond` trả về f-string, `tools/example_tool.py` là search stub + máy tính
AST. Thứ duy nhất có thật là `nodes/rag_node.py` (WS2, nối vào `src/rag/`).

Ticket yêu cầu: StateGraph cho 5 nhóm tool (AC, Music, Windows, Seat, Nav), intent
accuracy > 85%, tham số chuẩn JSON, và chọn Qwen2.5-3B q4 làm mô hình suy luận.

Bốn quyết định đã chốt trong brainstorming:

1. **Tái dựng theo `agent_spec.md`, mượn phương pháp đã kiểm chứng của
   `experiments/offline_poc`** — không port nguyên khối. Branch
   `feature/hybrid-architecture-resident-pipeline` có `control_router.py` (297 dòng)
   đã chạy thật và đạt 95% downstream tool-exact trên dataset `poc/v2`; lấy *kỹ thuật*
   (chuẩn hóa NFC + `hoà`→`hòa`, `_starts_with_command` bóc tiền tố lịch sự, parser số
   tiếng Việt `hai mươi tư`, tách `_match_*` theo domain) chứ không lấy *contract*
   (PoC thiếu validator riêng và gộp policy vào một hàm).
2. **Tool registry canonical Họ B + adapter alias Họ A** — xem ADR-010.
3. **Deterministic-first, Qwen là fallback** — `agent_spec.md` §Agent boundary chốt
   luật chạy trước, SLM chỉ cho câu mơ hồ/hiếm. SPIKE-001 kết luận **Not Yet** cho cả
   hai ứng viên Q4 (fail hard gate); coi Qwen là planner chính sẽ khiến AC "Acc > 85%"
   phụ thuộc weight chưa từng vượt gate.
4. **Bỏ `search_nearby_poi` khỏi scope** — xem ADR-010 §Scope boundary.

## Kiến trúc & thành phần

```
src/agents/
  contracts.py   CandidateActionPlan/CandidateStep · ActionPlan/PlanStep · ToolResult · RouteDecision
  router.py      DeterministicControlRouter
  policy.py      materialize_action_plan()
  vehicle.py     VehicleSimulator
  slm.py         Planner protocol + QwenPlanner
  tools/         __init__.py (registry + alias) · hvac.py · media.py · window.py · seat.py · navigation.py
  nodes/         normalize.py · route.py · validate.py · safety.py · execute.py · compose.py · rag_node.py (đã có)
  state.py       mở rộng AgentState
  graph.py       build_graph()
```

Không sửa `src/rag/`, `src/services/voice.py`, `src/models/schemas.py`. `src/api/routes.py`
chỉ được **thêm** route, không đổi `/chat` và `/status` hiện có.

### contracts.py — ranh giới candidate → canonical

Pydantic v2, `model_config = ConfigDict(extra="forbid", frozen=True)`.

- `CandidateStep`: `step_id`, `ordinal`, `tool`, `args`, `depends_on`. **Không có**
  `safety_level`, `plan_id`, `requires_approval`.
- `CandidateActionPlan`: `schema_version`, `steps`.
- `PlanStep`: như trên **cộng** `safety_level: Literal["S0","S1","S2","S3"]`.
- `ActionPlan`: `schema_version`, `plan_id`, `session_id`, `vehicle_id`,
  `vehicle_state_version`, `steps`, `requires_approval`.
- `RouteDecision`: `disposition: Literal["control","not_control","clarify","denied"]`,
  `candidate_plan`, `intent`, `reason`, `route_source`, `confidence`, `latency_ms`.

Bộ nhãn `intent` là đóng, khai báo cùng chỗ với registry và dùng làm ground truth cho
AC2: `hvac_power`, `hvac_temperature`, `media_playback`, `media_volume`,
`window_position`, `seat_heating`, `seat_position`, `door_state`, `navigation_start`,
`navigation_cancel`, `vehicle_state_query`, `manual_query`, `none`. Case `not_control`/
`clarify`/`denied` mang `intent="none"` trừ khi nhận diện được domain (ví dụ thiếu slot
nhiệt độ vẫn là `hvac_temperature` + `clarify`) — dataset ghi nhãn theo đúng quy ước này.

Hai validator là bất biến, có test riêng:

- `ActionPlan` **từ chối validate** nếu tồn tại step `safety_level == "S2"` mà
  `requires_approval is False`.
- `RouteDecision` **loại trừ lẫn nhau**: `disposition == "control"` bắt buộc có
  `candidate_plan`; ba disposition còn lại bắt buộc `candidate_plan is None`.

Chỉ `policy.materialize_action_plan()` được tạo `ActionPlan`. Không node nào khác
được gán `safety_level`.

### tools/ — registry, schema, alias

Mỗi tool là một module khai báo: tên canonical, Pydantic args model (đóng, `extra="forbid"`),
safety rule, và hàm áp dụng lên `VehicleSimulator`.

| Module | Tool canonical | Args (ràng buộc từ `agent_spec.md` §Tool registry) | Safety |
|---|---|---|---|
| `hvac.py` | `set_hvac_power` | `{enabled: bool}` | S1 |
| | `set_hvac_temperature` | `{temperature_c: float}`, `16 ≤ x ≤ 30` | S1 |
| `media.py` | `media_control` | `{action: play\|pause\|next\|previous\|set_volume, volume?: int}`; `volume` bắt buộc iff `action="set_volume"`, cấm nếu khác, `0..100` | S1 |
| `window.py` | `set_window_position` | `{window: 4 vị trí, percent: int 0..100}` | **S2 luôn** |
| `seat.py` | `set_seat_heating` | `{seat: front_left\|front_right, level: int 0..3}` | S1 |
| | `set_seat_position` | `{seat, axis: fore_aft\|recline\|height, value: int 0..100}` | S2 nếu `speed_kph == 0 && gear == P`, ngoài ra S3 |
| `navigation.py` | `set_navigation` | `{operation: start\|cancel, destination_id?: str}`; `start` bắt buộc `destination_id` không rỗng, `cancel` cấm nó | S1 |
| `__init__.py` | `get_vehicle_state` | `{}` | S0 |
| | `set_door_state` | `{door: 4 vị trí, state: open\|closed}` | S2 nếu `speed_kph == 0 && gear == P`, ngoài ra S3 |

`destination_ref` (POI reference) **không được khai báo** trong schema, nên bất kỳ
plan nào chứa nó rơi vào `VALIDATION_DENIED` với subcode `args_invalid` — đúng ranh
giới scope, không phải bỏ sót âm thầm.

Bảng alias Họ A là một `dict` hằng số duy nhất trong `tools/__init__.py`:

```
control_ac     → {set_hvac_power, set_hvac_temperature}
control_music  → {media_control}
control_window → {set_window_position}
control_seat   → {set_seat_heating, set_seat_position}
navigation     → {set_navigation}
```

Ánh xạ chỉ dùng một chiều canonical → alias khi dựng HTTP response. `ActionPlan` và
trace không bao giờ chứa alias.

### router.py — DeterministicControlRouter

`route(text, vehicle_state_version) -> RouteDecision`. Thứ tự xử lý:

1. `normalize_vi()`: NFC → casefold → hợp nhất `hoà`/`hòa` → bỏ ký tự không phải
   `\w`/`%` → gom khoảng trắng. Port từ PoC.
2. Chặn phủ định: có từ khóa actuator **và** có `đừng|không|chớ|chẳng` → `denied`,
   reason `negated_command`.
3. Chặn actuator ngoài registry (ví dụ "phanh ABS") → `denied`,
   `unsupported_dangerous_actuator`.
4. Câu hỏi/tra cứu ("như thế nào", "nghĩa là gì", "hiện tại là") → `not_control`,
   `manual_or_information_request` → nhánh RAG.
5. Đại từ không xác định ("mở nó ra", "bật nó lên") → `clarify`, `ambiguous_reference`.
6. Chạy lần lượt `_match_hvac`, `_match_music`, `_match_window`, `_match_seat`,
   `_match_navigation`. Matcher đầu tiên trả khác `None` thắng.
7. Không matcher nào khớp → `not_control`, `no_control_rule`.

Mỗi matcher yêu cầu **cả** từ khóa domain **và** động từ điều khiển ở đầu câu
(`_starts_with_command` bóc tiền tố `hãy|vui lòng|làm ơn|giúp tôi`). Thiếu slot bắt
buộc → `clarify` (không đoán). Giá trị ngoài range → `denied` (không kẹp về biên).

**Sửa KI-001 tại đây, có chủ đích.** PoC có lỗi đã ghi nhận: `"Bật điều hòa lên 25 độ"`
cho ra `set_hvac_power(enabled=True)` và **nuốt mất số 25**, vì nhánh `bật`/`tắt`
return trước khi đọc số. Bản này đảo thứ tự: đọc số trước, nếu câu có cả động từ
bật/tắt lẫn một số hợp lệ trong `16..30` thì sinh plan hai step
(`set_hvac_power` → `set_hvac_temperature`, step 2 `depends_on` step 1). Case tương
ứng được thêm vào dataset v3, nên con số đo được vẫn bao phủ hành vi này — đúng điều
kiện mà HANDOFF §Traps 4 đặt ra để cho phép sửa.

### policy.py — nơi duy nhất gán safety

`materialize_action_plan(candidate, vehicle_snapshot, session_id, vehicle_id) -> ActionPlan`.

Đọc `speed_kph`/`gear` từ **snapshot đã truyền vào**, không đọc trực tiếp simulator
(để classify thuần và test được). Tính `safety_level` cho từng step theo bảng registry,
đặt `requires_approval = any(step.safety_level == "S2")`, sinh `plan_id`.

`plan_digest` là **hàm riêng** `plan_digest(plan: ActionPlan) -> str =
sha256(canonical_json(plan))`, không phải field của `ActionPlan` (`data_model.md`
không khai báo field đó). Branch này chỉ cần hàm tồn tại và ổn định qua replay; branch
HITL mới dùng nó để bind approval.

Gặp tool ngoài allowlist → `ValueError`. Đây là lỗi lập trình, không phải
`validation_denied` (validator đã chạy trước và phải bắt được).

### vehicle.py — VehicleSimulator

In-memory, port từ `vehicle_mock.py` của PoC nhưng thu gọn:

- `state` chứa `state_version`, `speed_kph`, `gear`, `hvac`, `seat_heating`,
  `seat_position`, `windows`, `doors`, `media`, `navigation`.
- `execute(command_id, expected_state_version, tool, args) -> ToolResult`, idempotent
  theo `command_id` (trả kết quả đã cache, không áp dụng lại).
- `command_count` đếm số lệnh **thực sự áp dụng lên state**. Đây là biến mà test dùng
  để chứng minh "zero side effect" trên các đường chặn/từ chối; lệnh bị `rejected`
  hoặc trả từ cache không làm nó tăng.
- `expected_state_version` lệch → `rejected` + `stale_state`, **không** đổi state.
- Mỗi lần đổi state thật → `state_version += 1`.
- Simulator kiểm predicate an toàn **độc lập** với policy (`safety_and_hitl.md`
  §Core invariants: "policy + simulator kiểm độc lập") — mở cửa khi đang chạy bị
  `rejected` + `unsafe_vehicle_state` ngay cả khi policy vì lý do nào đó cho qua.

### slm.py — Qwen là fallback, không phải planner chính

```python
class Planner(Protocol):
    def propose(self, normalized_text: str, snapshot: dict) -> CandidateActionPlan: ...
```

- `QwenPlanner` gọi llama-server qua HTTP (`/completion`), model pin
  `qwen2.5-3b-instruct-q4_k_m` (sidecar checksum đã có trong
  `experiments/offline_poc/models/`). Prompt chỉ được sinh `CandidateActionPlan`.
- Output đi qua **initial schema check**. Sai → **đúng một** lần schema repair. Vẫn
  sai → deterministic matcher → `clarify`. Không có vòng lặp repair, không ReAct.
- Output chứa `safety_level` → fail closed-schema check ngay (test bắt buộc).
- `build_graph()` mặc định `planner=None` → nhánh mơ hồ đi thẳng `clarify`. Test dùng
  stub planner. **Chưa có bằng chứng chạy weight thật trong sprint này** — mọi tài
  liệu phải ghi đúng như vậy.

Settings mới trong `src/config.py`: `slm_provider`, `slm_endpoint`, `slm_model_id`,
`slm_timeout_s`, `slm_enabled` (mặc định `False`).

### graph.py — StateGraph

```
START → normalize → route ─┬─ control ──→ validate → safety ─┬─ S3 ─────────→ compose → END
                           │                   │             ├─ S0/S1 → execute → compose
                           │                   └─ denied ────┤
                           ├─ manual ──→ rag_node ───────────┤
                           ├─ clarify / denied ──────────────┤
                           └─ ambiguous → slm_planner → schema_check ─┬─ valid → validate
                                                                       └─ invalid → clarify
```

- `build_graph(vehicle, planner=None, rag=rag_node, checkpointer=None)` — mọi phụ
  thuộc inject được; không có singleton module-level như boilerplate hiện tại.
- Nhánh `manual` nối `rag_node` đang có trên `develop`. Không viết lại RAG.
- Node `safety` ở branch này chỉ **phân loại và chặn S3**. Đường `requires_approval`
  đi thẳng `compose` với outcome `approval_required` và ghi rõ chưa có cơ chế xác
  nhận. Branch `feature/hitl-safety-confirmation` mới cắm `request_approval` vào đúng
  chỗ đó.
- `execute` chạy tuần tự, fail-fast: step có `depends_on` chưa hoàn tất → `skipped_due_to_prior_failure`;
  `expected_state_version` cuộn theo `ToolResult` trước đó.
- `compose` chỉ báo cáo outcome đã verify từ `ToolResult` đã persist; không suy đoán
  thành công.

### state.py

Giữ nguyên các field RAG đang dùng (`evidence`, `citations`, `refusal_reason`) để
`rag_node` không hỏng. Thêm: `session_id`, `turn_id`, `vehicle_id`, `normalized_text`,
`route_source`, `confidence`, `intent`, `slots`, `vehicle_snapshot`,
`vehicle_state_version`, `candidate_action_plan`, `action_plan`, `outcome`,
`step_results`, `response_text`.

### API (tối thiểu, branch này)

Thêm `POST /api/v1/agent/process` theo Họ A:

- Request `{query, vehicle_speed_kmh?, user_role?}`.
- Response `{status, intent, response_text, tool_calls[{tool_name, parameters}], hitl_pending, latency_ms}`.
- `tool_name` dùng **alias Họ A** (ADR-010); `parameters` là args canonical.
- `status` ở branch này chỉ nhận `SUCCESS` / `BLOCKED` / `CLARIFY` / `DENIED`.
  `PENDING_HITL` và `hitl_action_id` thuộc branch HITL.

## Đo AC — bằng chứng, không phải test pass

`CLAUDE.md` ghi rõ: "Passing unit tests are not model-quality evidence. Claims must
trace to a run ID." Nên AC2/AC3 cần artifact riêng.

- **Dataset** `eval/datasets/agent/v3/cases.jsonl`: port 30 case text từ
  `eval/datasets/poc/v2/cases.jsonl` ở branch hybrid (bỏ phần audio — sprint này
  không làm voice), bổ sung lên ~60 để phủ đủ 5 domain, cả `set_seat_position`/
  `set_door_state`, case KI-001, và case negative (`not_control` / `clarify` /
  `denied`). Kèm `README.md` ghi provenance: lấy từ commit nào của branch nào.
- **Runner** `python -m src.agents.eval` → ghi thư mục **bất biến**
  `eval/results/agent-intent/<UTC-run-id>/` gồm `manifest.json`, `case_results.jsonl`,
  `metrics.json`. Mở file bằng mode `"x"`, `mkdir(exist_ok=False)` — cùng kỷ luật với
  `spike2_evidence.py`. Không sửa tay, muốn số mới thì chạy lại.
- **Metric**:
  - `intent_accuracy` = tỉ lệ case đúng cả `disposition` lẫn `intent` → **AC > 85%**.
  - `tool_exact` = tỉ lệ case `control` đúng cả tên tool lẫn toàn bộ args → **AC3**.
  - Báo cáo tách riêng theo domain để thấy domain nào kéo tụt.

`README.md` và `WORKLOG.md` chỉ được ghi con số kèm run-id sinh ra nó.

## Testing

Chạy từ repo root: `.\.venv\Scripts\python.exe -m pytest tests/ -q`.

| File | Nội dung |
|---|---|
| `tests/test_agents/test_contracts.py` | `ActionPlan` từ chối S2 + `requires_approval=False`; `RouteDecision` loại trừ lẫn nhau; candidate không có trường `safety_level` |
| `tests/test_agents/test_router.py` | Bảng case tiếng Việt cho 5 domain; phủ định; thiếu slot → `clarify`; ngoài range → `denied`; KI-001 sinh plan 2 step |
| `tests/test_agents/test_tools.py` | Mỗi args model từ chối field lạ, sai kiểu, ngoài range; `volume` bắt buộc/cấm theo `action`; `destination_ref` bị từ chối |
| `tests/test_agents/test_policy.py` | Window luôn S2; door/seat position S2 khi đứng yên, S3 khi `speed>0` hoặc `gear≠P`; `requires_approval` suy ra đúng; tool lạ → `ValueError` |
| `tests/test_agents/test_vehicle.py` | Idempotent theo `command_id`; `stale_state` không đổi state; `state_version` tăng đúng; simulator chặn mở cửa khi đang chạy |
| `tests/test_agents/test_graph.py` | **Thay thế** 2 test boilerplate hiện có. Dựng graph; S1 chạy thẳng; S3 chặn không side effect (`command_count == 0`); `not_control` gọi rag stub; mơ hồ → `clarify`; planner stub trả plan có `safety_level` → fail schema check |
| `tests/test_agents/test_eval.py` | Runner đọc dataset, tính metric đúng trên fixture nhỏ; từ chối ghi đè thư mục đã tồn tại |
| `tests/test_api/test_agent_routes.py` | `/api/v1/agent/process` trả alias Họ A; `/chat` và `/status` cũ không đổi |

Test không được gọi mạng, không load weight, không đọc `models/`.

## Error handling

- Tool lạ / schema sai / ngoài range → `VALIDATION_DENIED` + subcode
  (`tool_not_allowed` | `args_invalid` | `range_invalid`) **trước** khi phân loại
  S0–S3. Đây không phải S3.
- S3 → `blocked`, zero side effect, không tạo approval.
- `stale_state` từ simulator → dừng group, step còn lại `skipped_external_state_change`.
- RAG không đủ evidence → `refusal_reason=insufficient_evidence` (hành vi có sẵn của
  `rag_node`, không đổi).
- SLM lỗi/timeout → coi như schema invalid → deterministic matcher → `clarify`.
  Không retry, không fallback sang cloud.

## Documentation

- [ADR-010](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md) — đã viết.
- `eval/datasets/agent/v3/README.md` — provenance dataset.
- `WORKLOG.md` + `JOURNAL.md` — cập nhật khi work land, đúng định dạng bảng hiện có.
- `README.md` — thêm dòng trạng thái cho agent graph, kèm run-id của lần eval sinh ra
  con số. Không nâng trạng thái nếu chưa có artifact.

## Ngoài phạm vi (out of scope)

- **Voice/STT/TTS** — đầu việc khác, merge sau. Không node nào gọi `src/services/voice.py`.
- **HITL / approval** — branch `feature/hitl-safety-confirmation`.
- **`search_nearby_poi` + `PlanningResolution`** — ADR-010 §Scope boundary.
- **MQTT + vehicle-simulator service thật** — WS3 sở hữu; sprint này dùng
  `VehicleSimulator` in-process.
- **SQLite persistence cho plan/approval** — in-memory; branch HITL đánh giá lại.
- **WebSocket, RBAC, auth** — WS4 sở hữu.
- **Chạy Qwen với weight thật** — cần tải GGUF + dựng llama-server; sprint này chỉ
  làm port và test bằng stub.

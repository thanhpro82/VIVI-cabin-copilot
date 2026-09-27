# Bàn giao: `VehicleGateway` — cho Nhân (ticket HITL end-to-end)

> **Tóm tắt một câu.** Sơn đã dựng xong cổng để agent graph nói chuyện với xe qua
> MQTT; việc còn lại là đổi `src/agents/**` từ gọi thẳng `src/agents/vehicle.py`
> sang gọi cổng đó. Tài liệu này liệt kê đúng những gì phải sửa và bốn cái bẫy đã
> được kiểm chứng hộ.

## Vì sao việc này nằm trong ticket HITL, không phải ticket của Sơn

AC2 của ticket HITL yêu cầu xử lý **state invalidation**. State invalidation nghĩa
là so `approved_vehicle_state_version` với **trạng thái xe sống** — chính là
`src/agents/nodes/approval.py:150`. Không có nguồn state authoritative thì AC đó
không thể đạt thật, nên việc đổi nguồn state là một phần nội tại của ticket, không
phải việc phát sinh.

## Bug đang tồn tại mà việc này sửa

Repo có **hai simulator xe song song, không nối nhau**:

| | Đường MQTT | Đường agent |
|---|---|---|
| Simulator | `src/vehicle_sim/state.py` (pydantic, canonical) | `src/agents/vehicle.py` (dict, shape khác) |
| Chảy vào `GET /vehicle/state` | ✅ | ❌ |

Hệ quả cụ thể: tài xế nói "bật điều hòa 22 độ" → state đổi ở simulator của session
→ `GET /api/v1/vehicle/state` **không đổi gì**. Frontend
(`DriverShellProvider.tsx:105-107`) refresh vehicle state ngay sau `tool.result`,
nên màn hình của Giáp sẽ không bao giờ cập nhật. **Đây là mắt xích cuối cùng.**

---

## 1. Cổng — `src/services/vehicle_gateway.py`

```python
class VehicleGateway(Protocol):
    vehicle_id: str
    async def snapshot(self) -> VehicleState | None      # đủ tươi để LẬP KẾ HOẠCH
    async def last_known(self) -> VehicleState | None    # chỉ để HIỂN THỊ
    def readiness(self) -> SimulatorReadiness
    async def execute(self, *, plan_id, step_id, tool, args,
                      expected_state_version, approval_id=None,
                      execution_group_id=None) -> ToolResult
    def add_listener(listener) / def remove_listener(listener)
```

**Hai method đọc, đừng dùng lẫn.** `snapshot()` trả `None` khi xe ảo chưa sẵn
sàng; `last_known()` trả state cuối cùng biết được bất kể tươi cũ.

- Node phân loại an toàn phải dùng `snapshot()`. Xếp một lệnh mở cửa là S2 hay S3
  phụ thuộc `speed_kph == 0 && gear == "P"`; đọc nhầm state cũ nghĩa là đưa thẻ
  xác nhận cho hành động lẽ ra phải chặn thẳng.
- Node hiển thị/compose dùng `last_known()` được.

Lấy cổng: `get_vehicle_gateway()` (singleton mức module, không phải `app.state` —
`tests/conftest.py` dùng `ASGITransport` nên lifespan không chạy cho phần lớn test
API). `set_vehicle_gateway()` / `reset_vehicle_gateway()` cho test và lifespan.

Hai implementation, đã có contract test parametrize qua cả hai
(`tests/test_vehicle/test_vehicle_gateway.py`, 26 test):

- `InProcessVehicleGateway` — bọc `src/vehicle_sim/state.py`, dùng cho test và
  `MQTT_ENABLED=false`. Có `MotionInjectable.set_motion()`.
- `MqttVehicleGateway` — bọc `MqttRuntime`. **Không** có `set_motion`.

---

## 2. Tám điểm đọc snapshot phải migrate sang shape canonical

Shape hiện tại của `src/agents/vehicle.py` khác canonical ở bốn chỗ: `speed_kph`/
`gear` nằm top-level (không có `motion`, không có `ignition`), `hvac` thiếu
`fan_level`, `seat_heating`/`seat_position` là hai nhánh rời thay vì `seat.*`, và
`media` thiếu `track`.

| Vị trí | Trước → Sau |
|---|---|
| `agents/policy.py:40` | `snapshot["speed_kph"]` → `snapshot["motion"]["speed_kph"]` (và `gear`) |
| `agents/policy.py:85,94` | `snapshot["state_version"]` — **giữ nguyên**, canonical cũng top-level |
| `agents/nodes/normalize.py:47-52` | `vehicle.snapshot()` → `await gateway.snapshot()` rồi `snapshot_dict(...)`, hoặc `{}` nếu `None` |
| `agents/nodes/approval.py:62` | `snapshot.get("speed_kph", 0)` → `snapshot.get("motion", {}).get("speed_kph", 0)` |
| `agents/nodes/approval.py:69,71` | `snapshot["windows"][...]`, `snapshot["doors"][...]` — **giữ nguyên** |
| `agents/nodes/approval.py:73` | `snapshot["seat_position"][s][axis]` → `snapshot["seat"][s][axis]` |
| `agents/nodes/approval.py:150,157` | `vehicle.state[...]` → `await gateway.snapshot()`, `None` thì fail-closed |
| `agents/nodes/execute.py:25,26,36` | xem mục 3 |
| `agents/slm.py:72` | lọc `observed_at`/`vehicle_id` khỏi prompt, nếu không prompt đổi mỗi lần gọi |

Dùng `snapshot_dict(state)` từ `vehicle_gateway.py` — nó là hàm **duy nhất** dựng
dict canonical, và nó bằng đúng `data.vehicle_state` mà
`GET /api/v1/vehicle/state` trả ra.

---

## 3. Bốn cái bẫy đã kiểm chứng hộ

**① `vehicle_snapshot` trong `AgentState` phải giữ là `dict`, không phải model.**
Nó đi qua checkpoint LangGraph, và `tests/test_agents/test_hitl_node.py:284-309`
ép chế độ msgpack chặt (`allowed_msgpack_modules=None`). Một model pydantic sẽ
quay về `dict` lúc resume và `describe_plan_for_approval` sẽ vỡ — **ở nhánh resume
HITL, tức đường ít được chạy nhất**. Dùng `snapshot_dict()`, đừng truyền model.

**② `observed_at` đổi liên tục KHÔNG phá bất biến HITL.** Đã kiểm:
`materialize_action_plan` (`agents/policy.py:82-88`) chỉ băm
`steps + vehicle_state_version + session_id`, **không** băm snapshot. Nên
`plan_digest` ổn định dù `observed_at` nhảy mỗi lệnh.

**③ `observed_state_version` đến từ CommandEvent, không phải từ cache.**
`VehicleSimulator._domain_dict()` (`vehicle_sim/state.py:202-208`) gắn
`state_version` vào `before`/`after` của event, và simulator tính nó **sau** khi
đã tăng version. Nên rolling version phải là:

```python
expected_version = result.observed_state_version   # KHÔNG phải đọc lại cache
```

Đây là bản nâng cấp so với `vehicle.state["state_version"]` hiện tại: không có
race, vì không đọc cache. Test khoá hành vi này:
`test_mqtt_e2e_inmemory.py::test_ba_lenh_lien_tiep_dung_rolling_version` và
`::test_rolling_van_dung_khi_co_buoc_khong_doi_gi`.

**④ `agents.contracts.ToolResult` nên thêm `observed_state_version: int`.**
Hiện `services/ivi_events.py:193` moi `step.after.get("state_version")`, nhưng
nhánh `_local_failure` của executor có `after={}` nên trả `None`. Có field tường
minh thì hết phụ thuộc hình dạng `after`. Lưu ý `ToolResult` là `extra="forbid"`
nên field mới là bắt buộc — nhánh `"skipped"` trong `execute_node` cấp
`expected_version`.

---

## 4. Khuyến nghị: fail-closed khi chưa đọc được state

**Từ chối, đừng fallback.** Fallback về state đoán (ví dụ giả định `speed_kph=0`)
sẽ biến một lệnh mở cửa lẽ ra là S3 thành thẻ xác nhận S2 — đúng loại lỗi mà
`docs/safety_and_hitl.md` tồn tại để chặn.

Nhưng chỉ từ chối **lượt cần state**, không từ chối lượt tra sổ tay — nếu không
thì broker chết là mất luôn RAG, một regression vô cớ.

Điểm chặn gợi ý: đầu `safety_node` (node duy nhất phân loại S0–S3).
`_make_route_after_safety` (`graph.py:61-68`) đã đẩy mọi outcome lạ sang `compose`
nên **không cần thêm edge nào**. Kèm theo: thêm message vào
`compose.OUTCOME_MESSAGES`, và map sang `turn.failed(code="MQTT_UNAVAILABLE")`
trong `ivi_events` (mã này đã có trong `api_spec.md:659`, không phải bịa).

`approval_node` lúc resume: `snapshot()` trả `None` → `approval_invalidated_state`.
Đây là nhánh fail-closed thứ năm, cùng họ với bốn nhánh hiện có.

---

## 5. Ước lượng công sức

~60 test function bị chạm, chủ yếu là đổi constructor
`VehicleSimulator.initial()` → `InProcessVehicleGateway.new()` và đường đọc state:

| File | Số test bị chạm |
|---|---|
| `tests/test_agents/test_hitl_node.py` | 17 |
| `tests/test_agents/test_graph.py` | 14 |
| `tests/test_agents/test_hitl_safety.py` | 7 |
| `tests/test_api/test_session_state.py` | 5 |
| `tests/test_agents/test_slm.py` | 4 |
| `tests/test_agents/test_policy.py` | 3 hằng module |
| `tests/test_agents/test_vehicle.py` | **xoá cả file** — `tests/test_vehicle/test_simulator.py` đã phủ hết |

Một test phải **viết lại thành điều ngược lại**:
`test_session_state.py::test_vehicle_state_survives_across_calls_within_a_session`
→ "state xe là toàn cục, hai session thấy cùng một xe". Đây là đảo ngược bất biến
có chủ đích (`GET /api/v1/vehicle/state` không có tham số session nên nó *không
thể* trả state per-session), nhớ ghi vào JOURNAL.

---

## 6. Hai điểm cần biết trước khi bắt đầu

**`speed_kph` do client set sẽ mất khi bật MQTT.** `mqtt_spec.md:337-349` cấm
backend publish `state/*` và `motion` nằm trong `READ_ONLY_DOMAINS`. Vì vậy
`MotionInjectable` chỉ có ở bản in-process; `agent_routes.py:105` phải kiểm
`isinstance(gateway, MotionInjectable)` rồi mới dùng. **Tuyệt đối không**
shadow-publish `state/motion` từ backend, kể cả "tạm cho demo" — đó là vi phạm
ACL và đúng loại lỗi mà cả PR này đang đi sửa. Xem ADR-013.

**`src/api/turns.py:54` cũng dùng sai vỏ lỗi.** Nó dùng
`HTTPException(detail={"error": ...})`, mà FastAPI luôn bọc thêm một tầng
`{"detail": ...}` nên frontend đọc `body.error.code` sẽ luôn miss. Sơn đã sửa
`routes.py:51` bằng `ApiError` trong `src/api/errors.py` — dùng lại lớp đó cho
`turns.py`. Cùng lớp lỗi, nhưng file thuộc luồng turn nên để Nhân sửa.

## Kiểm chứng sau khi xong

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q      # hiện tại: 565 passed, 14 skipped
.\.venv\Scripts\python.exe scripts\report_mqtt_e2e.py
```

Và bài kiểm thủ công quan trọng nhất: bấm nút điều hòa trên `/driver` →
`GET /api/v1/vehicle/state` phải đổi `hvac.temperature_c` **và** `state_version`
tăng. Đó là lúc bug ở đầu tài liệu này thật sự hết.

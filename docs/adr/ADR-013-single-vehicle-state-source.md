# ADR-013: Một nguồn vehicle state duy nhất qua `VehicleGateway`

- Status: Accepted — phần cổng đã implement; phần nối agent thuộc ticket HITL
- Date: 2026-08-09
- Decision owner: WS3 Virtual Vehicle & MQTT (Sơn)
- Liên quan: ADR-004 (MQTT digital twin), ADR-006 (deterministic routing), `docs/mqtt_spec.md`, `docs/safety_and_hitl.md`

## Context

Khi khảo sát để hoàn thiện `GET /api/v1/vehicle/state`, phát hiện repo có **hai
simulator xe song song, không nối nhau**:

| | Đường MQTT | Đường agent |
|---|---|---|
| Simulator | `src/vehicle_sim/state.py` (pydantic, canonical) | `src/agents/vehicle.py` (dict, shape khác) |
| Executor | `src/services/tool_executor.py` | `src/agents/nodes/execute.py` gọi thẳng in-process |
| Instance | một, trong tiến trình `python -m src.vehicle_sim` | một **mỗi session**, LRU 128 |
| Chảy vào `GET /vehicle/state` | có | không |

`ToolExecutor` **chưa từng được production code nào gọi** — grep toàn repo chỉ ra
nó trong test và `scripts/smoke_mqtt.py`.

Hệ quả: mọi lượt người dùng (`/turns/voice`, `/agent/process`, `/chat`) đổi state
ở simulator của session, còn `GET /api/v1/vehicle/state` đọc cache MQTT nên không
đổi. Frontend refresh vehicle state ngay sau `tool.result`
(`DriverShellProvider.tsx:105-107`) nên màn hình IVI không bao giờ cập nhật.

Hai shape cũng lệch nhau: bản dict để `speed_kph`/`gear` ở top-level (không có
`motion`, không có `ignition`), thiếu `hvac.fan_level` và `media.track`, và tách
`seat_heating`/`seat_position` thành hai nhánh rời thay vì `seat.*`.

## Decision

**Một nguồn state duy nhất, truy cập qua port `VehicleGateway`**
(`src/services/vehicle_gateway.py`).

1. **Một máy trạng thái**: `src/vehicle_sim/state.py`. `src/agents/vehicle.py` sẽ
   bị xoá khi agent graph chuyển sang cổng.
2. **Hai implementation**: `InProcessVehicleGateway` (test, `MQTT_ENABLED=false`)
   và `MqttVehicleGateway` (broker sống). Contract test parametrize qua cả hai
   để chúng không trôi xa nhau.
3. **Hai method đọc, không phải một.** `snapshot()` trả `None` khi xe ảo chưa sẵn
   sàng; `last_known()` trả state cuối cùng biết được. Màn hình được phép hiển thị
   dữ liệu cũ; phân loại an toàn S0–S3 thì không.
4. **`GET /api/v1/vehicle/state` trả 503 khi state đã hết hạn**, không trả snapshot
   cũ kèm cảnh báo. Năm `reason`: `broker_unreachable`, `no_snapshot_yet`,
   `no_health`, `offline`, `heartbeat_stale`.
5. **Không rơi về in-process khi broker chết.** Nếu `MQTT_ENABLED=true` mà
   `runtime.start()` hỏng, lifespan vẫn gắn `MqttVehicleGateway`. Rơi về xe
   in-process lúc đó là thay thầm một chiếc xe khác: API trả 200 với trạng thái
   của một chiếc xe không ai điều khiển, và không ai biết. In-process chỉ dùng khi
   `MQTT_ENABLED=false` — tức lựa chọn tường minh của người vận hành.
6. **Rolling `expected_state_version` đọc từ `ToolResult.observed_state_version`**,
   không đọc lại cache. Giá trị đó do simulator tính sau khi đã tăng version và
   được gắn vào `CommandEvent`, nên không có race.

## Consequences

### Được

- `GET /api/v1/vehicle/state` và `/ws/engineer` đọc cùng một nguồn với agent, nên
  hai kênh không thể nói hai chuyện khác nhau về cùng một chiếc xe.
- Máy trạng thái còn lại tốt hơn bản bị xoá ở sáu điểm: `BoundedCache` thay `dict`
  không trần, tách `tool_not_allowed` khỏi `invalid_arguments`,
  `requires_stationary` lấy từ registry thay vì hardcode, `_set()` phát hiện thay
  đổi thật nên `state_version` không tăng oan, có `media.track`/`motion.ignition`/
  `hvac.fan_level`, và `_apply` bọc `except → internal_error`.
- `simulator_ready()` cuối cùng có tác dụng thật — trước đó nó chỉ được dùng ở
  `/health` và không chặn được gì.

### Mất — ghi rõ, không lấp

**Không đặt được tốc độ xe từ backend khi bật MQTT.** `mqtt_spec.md:337-349` cấm
backend publish `state/*`, và `motion` nằm trong `READ_ONLY_DOMAINS` nên không có
topic lệnh nào cho nó. Vì vậy `set_motion()` tách sang Protocol riêng
`MotionInjectable` và **chỉ** bản in-process có.

**Đã giải quyết (2026-08-09):** `SimulatorRuntime.set_motion()` cho **xe tự đặt tốc
độ của chính nó**, rồi publish `state/motion` + snapshot như mọi thay đổi khác —
publisher vẫn là identity simulator nên không vi phạm ACL. Điều khiển từ console
của tiến trình xe ảo (`python -m src.vehicle_sim`):

```
speed 45        # 45 km/h, tự chuyển số D
speed 45 D      # nói rõ số
gear P
stop
state
```

Kiểm chứng end-to-end trên Mosquitto thật: đặt 60 km/h → backend đọc được qua
`GET /vehicle/state` → mở cửa bị `unsafe_vehicle_state` → `stop` → mở cửa được.
Test: `tests/test_vehicle/test_mqtt_stale_state.py` mục "điều khiển chuyển động".

**Tuyệt đối không** shadow-publish `state/motion` từ backend, kể cả "tạm cho
demo" — đó là vi phạm ACL và đúng loại lỗi mà chính ADR này đang đi sửa. Lối đi
hợp lệ là để xe ảo tự quyết, như trên.

**Xe trở thành toàn cục, không còn per-session.** `GET /api/v1/vehicle/state`
không có tham số session nên nó *không thể* trả state per-session dù có muốn; và
MQTT chỉ có một `vehicle-demo-01`. Per-session chỉ tồn tại vì dựng một `dict` thì
rẻ. Test `test_vehicle_state_survives_across_calls_within_a_session` phải viết lại
thành điều ngược lại.

**`observed_at` có độ phân giải một giây.** `Timestamp` dùng `PlainSerializer` với
`%Y-%m-%dT%H:%M:%SZ`, nên snapshot trên dây mất phần dưới giây. Không dùng field
này để đo latency.

### Còn dang dở

Phần nối `src/agents/**` vào cổng **chưa làm** — nó thuộc ticket HITL của Nhân, vì
AC2 của ticket đó ("state invalidation") không thể đạt thật nếu không có nguồn
state authoritative. Cho tới khi đó, `GET /api/v1/vehicle/state` đúng hợp đồng
nhưng **giá trị nó trả về vẫn chưa đổi sau lệnh giọng nói**.

Hướng dẫn migrate: `docs/handoff/vehicle-gateway-for-agent.md`.

## Alternatives considered

**Giữ hai simulator, chỉ đồng bộ một chiều.** Bị loại: `safety_and_hitl.md:37`
đòi *policy* và *simulator* kiểm độc lập, không đòi hai simulator kiểm chéo nhau.
Hai bản sao chỉ tạo thêm chỗ để lệch.

**Dùng `InMemoryBroker` + `SimulatorRuntime` + `ToolExecutor` làm loopback
in-process cho cả hai đường.** Đẹp hơn về kiến trúc nhưng vỡ vì hai lý do cụ thể:
`ToolExecutor` giữ `asyncio.Future` gắn với event loop đang chạy, mà pytest ở repo
này đặt `asyncio_default_fixture_loop_scope = "function"` nên một gateway sống ở
module level sẽ mang Future của test trước sang test sau và nổ "got Future attached
to a different loop"; và `SimulatorRuntime.start()` spawn task heartbeat, không
`stop()` thì cả suite rò task. Đường in-process thẳng không có Future, không có
task nền.

**Trả 200 kèm cờ `stale` trong `meta` thay vì 503.** Bị loại: hợp đồng nói đây là
state *authoritative*, mà dữ liệu của một simulator đã chết thì không còn
authoritative. Trả 200 lúc đó là nói dối một cách im lặng.

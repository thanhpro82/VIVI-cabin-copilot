# MQTT Transport Specification

> **Status: Planned.** Đây là hợp đồng transport được duyệt cho P0. Tài liệu này **chưa** tuyên bố có runtime, broker hay simulator nào đang chạy.

Tài liệu này là bản triển khai chi tiết của [ADR-004](adr/ADR-004-mqtt-vehicle-simulator.md). ADR-004 chốt nguyên tắc ("Mosquitto, command schema versioned, allowlisted topics, idempotency key, state version bắt buộc") nhưng không chốt tên topic, QoS, retain, hay hình dạng payload. Tài liệu này chốt những thứ đó.

Nguồn canonical vẫn là:

- Bảng topic và `VehicleCommand`: [data_model.md — MQTT topics](data_model.md#mqtt-topics)
- Vehicle state: [data_model.md — Vehicle state](data_model.md#vehicle-state)
- Tool registry và dải giá trị: [agent_spec.md — Tool registry and planning invariants](agent_spec.md#tool-registry-and-planning-invariants)
- Biến môi trường, ACL, readiness: [devops.md](devops.md)
- REST/WebSocket: [api_spec.md](api_spec.md)

Khi tài liệu này mâu thuẫn với các file trên, các file trên thắng — trừ bốn mục ở §[Quyết định P0](#quyết-định-p0), là những chỗ tài liệu này cố ý khác canonical và đã được implement.

## Topic convention

P0 dùng quy ước `v1/vehicles/{id}/...`. Quy ước `vivi/vehicle/control` + `vivi/vehicle/status` xuất hiện trong `_bmad-output/planning-artifacts/` và một số sơ đồ kiến trúc là **bản cũ, không dùng để implement**: nó chỉ có 2 topic nên không biểu diễn được vòng đời lệnh (accepted/rejected/completed), heartbeat, hay `state_version` — trong khi ADR-004 bắt buộc "state version và expected version là bắt buộc".

`{id}` là **vehicle instance ID**, không phải mã dòng xe. P0 cố định một giá trị duy nhất `vehicle-demo-01` lấy từ biến môi trường `VEHICLE_ID`. Giữ `{id}` trong topic để ACL viết gọn (`v1/vehicles/vehicle-demo-01/#`) và để P2 thêm xe thứ hai mà không phải đổi topic.

Vehicle **profile** (`vf9-2026-vi`, dùng để lọc RAG theo sổ tay) là khái niệm khác với vehicle **ID**. Cả hai đều đơn trị ở P0. Xem `data_model.md` mục "Data quality checks": manual profile phải khớp vehicle profile của session.

## Topic table

| Topic | Publisher | Subscriber | QoS | Retain | Payload |
|---|---|---|:-:|:-:|---|
| `v1/vehicles/{id}/commands/{domain}` | Tool executor | Simulator | 1 | **false** | [`VehicleCommand`](#vehiclecommand) |
| `v1/vehicles/{id}/events/command` | Simulator | Backend | 1 | false | [`CommandEvent`](#commandevent) |
| `v1/vehicles/{id}/state/{domain}` | Simulator | Backend, UI bridge | 1 | **true** | [`DomainState`](#domainstate) |
| `v1/vehicles/{id}/state/snapshot` | Simulator | Backend | 1 | **true** | [`VehicleStateSnapshot`](#vehiclestatesnapshot) |
| `v1/vehicles/{id}/health` | Simulator | Backend | 1 | **true** | [`Health`](#health) |

LLM không bao giờ được tạo raw topic. Tool registry — server-owned — ánh xạ tool name sang topic, xem §[Tool-to-topic mapping](#tool-to-topic-mapping).

### Kênh harness `v1/sim/` — ngoài hợp đồng xe

Bảng trên là **hợp đồng xe**: những message một chiếc xe thật cũng có. Ngoài nó, hệ thống có đúng một topic nữa, và nó cố ý **không** nằm dưới `v1/vehicles/`:

| Topic | Publisher | Subscriber | QoS | Retain | Payload |
|---|---|---|:-:|:-:|---|
| `v1/sim/{id}/motion/set` | Backend (route harness) | Simulator | 1 | **false** | [`SimMotionSet`](#simmotionset-harness) |

Đây là **bàn đạo diễn kịch bản demo**, không phải giao diện điều khiển xe: "giả sử bây giờ xe đang chạy 45 km/h" là câu không có nghĩa với xe thật, vì ở đó tốc độ do vật lý quyết định. Lý do nó tồn tại: kịch bản nghiệm thu số 4 của [huong_dan_chay.md](huong_dan_chay.md) §3.3 (chặn cứng S3 khi xe đang chạy) trước đây chỉ dựng được bằng cách gõ `speed 45` vào stdin của `python -m src.vehicle_sim` — thứ không ai chạm được trên một bản deploy công khai.

Bốn ràng buộc, đầy đủ ở [ADR-024](adr/ADR-024-kenh-harness-dieu-khien-xe-ao.md):

1. **`motion` vẫn không có topic lệnh trong hợp đồng xe.** Backend chỉ nhắn; xe ảo nhận rồi tự gọi `SimulatorRuntime.set_motion()`. Publisher của `state/*` vẫn là identity simulator, nên [ADR-013](adr/ADR-013-single-vehicle-state-source.md) còn nguyên nghĩa.
2. **Mặc định tắt** (`SIM_CONTROL_ENABLED=false`), và tắt nghĩa là không tồn tại: xe ảo không subscribe, route trả **404** chứ không 403.
3. **`retain = false`** — đây là sự kiện đạo diễn, không phải trạng thái. Retain sẽ khiến xe ảo khởi động lại là tự nhảy về tốc độ của lần chỉnh trước.
4. **Namespace này chỉ được chứa thứ xe tự quyết mà không ai ra lệnh được** — tức `motion`, và ở P0 là hết. Thêm `v1/sim/{id}/doors/set` là mở cửa hậu điều khiển xe vòng qua policy và HITL.

### Vì sao retain như vậy

`commands/{domain}` phải **retain = false**. Nếu retain = true, mỗi lần simulator reconnect nó sẽ nhận lại lệnh cuối cùng và thực thi lần nữa — xe tự mở cửa sau khi restart broker. Đây là lỗi an toàn, không phải chi tiết vặt. Command là sự kiện một lần; retain chỉ dành cho trạng thái.

`state/{domain}`, `state/snapshot`, `health` phải **retain = true**. Subscriber nối vào bất cứ lúc nào cũng đọc được trạng thái hiện tại ngay, không phải chờ lần publish kế tiếp. Đây là cơ sở để backend khôi phục state cache sau restart mà không cần hỏi lại simulator.

`events/command` **retain = false**: sự kiện vòng đời, không phải trạng thái.

### Vì sao QoS 1 chứ không QoS 2

QoS 1 (at-least-once) có thể gây trùng message. Điều đó chấp nhận được vì ADR-004 đã bắt buộc dedupe bằng idempotency key ở tầng ứng dụng, và simulator cache kết quả theo `command_id` (§[Idempotency](#idempotency-and-retry)).

QoS 2 không giải quyết thêm gì: nó chỉ đảm bảo exactly-once **giữa hai peer MQTT**, không đảm bảo tầng ứng dụng phía sau xử lý đúng một lần. Vẫn phải tự dedupe. Đổi lại là 4 chặng bắt tay mỗi message thay vì 1. Không dùng.

## Transport parameters

| Tham số | Backend (executor) | Simulator |
|---|---|---|
| `client_id` | `vivi-backend` | `vehicle-simulator-{vehicle_id}` (cố định) |
| `clean_session` | `true` | **`false`** |
| `keepalive` | 30 s | 30 s |
| Protocol | MQTT 3.1.1 (tương thích MQTT 5) | như trên |
| Username | `MQTT_BACKEND_USERNAME` | `MQTT_SIMULATOR_USERNAME` |

Simulator dùng `clean_session=false` + `client_id` cố định để giữ subscription qua reconnect, không bỏ lỡ lệnh trong lúc mất kết nối ngắn. Backend dùng `clean_session=true` vì nó chủ động re-subscribe khi khởi động và đã có retained state để bù.

Biến môi trường theo đúng tên đã chốt ở [devops.md](devops.md) — `MQTT_URL`, `MQTT_BACKEND_USERNAME`, `MQTT_BACKEND_PASSWORD_FILE`, `MQTT_SIMULATOR_USERNAME`, `MQTT_SIMULATOR_PASSWORD_FILE`, `MQTT_ALLOW_ANONYMOUS`, `MQTT_PASSWORD_FILE`, `MQTT_ACL_FILE`. Tài liệu này thêm hai biến:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `VEHICLE_ID` | `vehicle-demo-01` | Giá trị `{id}` trong topic |
| `MQTT_COMMAND_TIMEOUT_MS` | `3000` | Executor chờ `CommandEvent` bao lâu trước khi coi là transient transport failure |

## Birth and Last Will

Simulator khai **Last Will** trong gói CONNECT và publish **Birth** ngay sau khi connect thành công. Cả hai trên cùng topic `v1/vehicles/{id}/health`, QoS 1, **retain = true**.

Last Will (broker tự publish khi simulator chết bất thường):

```json
{
  "schema_version": "1.0",
  "vehicle_id": "vehicle-demo-01",
  "online": false,
  "reason": "lwt"
}
```

Birth: một message [`Health`](#health) đầy đủ với `online: true`.

Vì cùng topic và cùng retain, subscriber nối vào bất kỳ lúc nào cũng đọc được ngay trạng thái sống/chết hiện tại mà không phải chờ nhịp heartbeat kế tiếp. Chỉ khai LWT mà không có Birth là thiếu: sau khi simulator hồi phục, retained message vẫn là `online:false` cho tới nhịp heartbeat sau.

Khi simulator shutdown có trật tự, nó publish `Health` với `online:false, reason:"shutdown"` **trước khi** DISCONNECT, để phân biệt với chết đột ngột.

Heartbeat: mỗi **5 giây**. Backend chấm `vehicle_simulator = down` nếu quá **15 giây** không thấy heartbeat mới (lỡ 3 nhịp), theo readiness contract ở [devops.md](devops.md).

## Domain enum

`{domain}` chỉ nhận đúng các giá trị sau:

```
motion | hvac | windows | doors | media | navigation | seat | lights | trunk
```

Domain nào không nằm trong danh sách này thì topic không hợp lệ và ACL phải từ chối. `motion` là read-only — không có tool nào publish lên `commands/motion`; nó chỉ xuất hiện ở `state/motion` để mang `speed_kph`/`gear`/`ignition` phục vụ phân loại an toàn S2/S3.

## Tool-to-topic mapping

ADR-004 quy định "tool registry, không phải LLM, ánh xạ tool sang topic". Bảng này là hợp đồng đó. Tool nằm ngoài bảng thì executor không derive được topic và phải trả `tool_not_allowed`.

| Tool | Topic | Safety |
|---|---|:-:|
| `set_hvac_temperature` | `commands/hvac` | S1 |
| `set_hvac_power` | `commands/hvac` | S1 |
| `set_hvac_fan_level` | `commands/hvac` | S1 |
| `media_control` | `commands/media` | S1 |
| `set_navigation` | `commands/navigation` | S1 |
| `set_seat_heating` | `commands/seat` | S1 |
| `set_window_position` | `commands/windows` | S2 luôn |
| `set_door_state` | `commands/doors` | S2 khi `speed_kph == 0 && gear == "P"`, ngược lại S3 |
| `set_seat_position` | `commands/seat` | S2 khi `speed_kph == 0 && gear == "P"`, ngược lại S3 |
| `set_trunk_state` | `commands/trunk` | S2 khi `speed_kph == 0 && gear == "P"`, ngược lại S3 |
| `set_headlight_mode` | `commands/lights` | S1 |
| `set_interior_light` | `commands/lights` | S1 |
| `get_vehicle_state` | — không publish MQTT | S0 |
| `query_manual` | — không publish MQTT | S0 |
| `search_nearby_poi` | — không publish MQTT | S0 |
| `open_app` | — không publish MQTT | S1 khi xe ở số P, **S3 khi không** |

Ba tool S0 đọc từ state cache, FAISS index, và POI fixture — không đi qua broker. Plan chứa step S3 không bao giờ tới executor, nên không bao giờ sinh publish.

`open_app` (ADR-023) cũng không đi qua broker, nhưng **không phải vì nó S0** — nó là tool cục bộ của IVI: mở một app trên màn hình không đổi trạng thái nào của xe, nên không có domain để mà publish. Đó là lý do nó vẫn nằm ngoài enum `tool` của `vehicle_command.schema.json` dù số tool tổng đã lên 16.

## Message schemas

JSON Schema máy đọc được nằm ở [`schemas/mqtt/`](../schemas/mqtt/). Mọi message đều `additionalProperties: false` ở schema version 1.0 — field lạ bị từ chối chứ không bỏ qua.

Mọi timestamp là UTC ISO 8601. Mọi message mang `schema_version`.

### VehicleCommand

Topic `v1/vehicles/{id}/commands/{domain}`. Copy nguyên từ [data_model.md](data_model.md#vehiclecommand), không sửa.

```json
{
  "schema_version": "1.0",
  "command_id": "cmd_01J...",
  "idempotency_key": "plan_01J...:step_01J...",
  "plan_id": "plan_01J...",
  "step_id": "step_01J...",
  "vehicle_id": "vehicle-demo-01",
  "approval_id": null,
  "execution_group_id": null,
  "expected_state_version": 41,
  "tool": "set_hvac_temperature",
  "args": {"temperature_c": 24},
  "issued_at": "2026-08-03T02:00:11Z"
}
```

`command_id`, topic, transport parameters và `idempotency_key` (`plan_id:step_id`) đều do server derive; model không được cung cấp hay ghi đè — xem `agent_spec.md`.

`expected_state_version` là rolling value: command đầu trong một execution group dùng approved version, command sau dùng `observed_state_version` của `ToolResult` trước. S2 command bắt buộc mang `approval_id` và `execution_group_id` khớp; command S0/S1 để `null`.

`args` phải khớp đúng schema của tool trong [§Value ranges](#value-ranges). Simulator validate lại lần nữa và trả `invalid_arguments` nếu sai — không tin tưởng executor đã validate.

### CommandEvent

Topic `v1/vehicles/{id}/events/command`. **Message mới, chưa có trong data_model.md.**

```json
{
  "schema_version": "1.0",
  "event_id": "evt_01J...",
  "command_id": "cmd_01J...",
  "idempotency_key": "plan_01J...:step_01J...",
  "plan_id": "plan_01J...",
  "step_id": "step_01J...",
  "vehicle_id": "vehicle-demo-01",
  "approval_id": null,
  "execution_group_id": null,
  "phase": "completed",
  "status": "completed",
  "expected_state_version": 41,
  "observed_state_version": 42,
  "before": {"temperature_c": 27, "state_version": 41},
  "after":  {"temperature_c": 24, "state_version": 42},
  "error_code": null,
  "latency_ms": 38,
  "emitted_at": "2026-08-03T02:00:11Z"
}
```

Simulator echo nguyên `command_id`, `idempotency_key`, `plan_id`, `step_id`, `approval_id`, `execution_group_id` từ command để executor tương quan được.

#### phase và status

`phase` ∈ `accepted | rejected | completed`. `status` ∈ `completed | rejected | failed`.

| phase | Nghĩa |
|---|---|
| `accepted` | Lệnh qua validate và invariant; simulator đã nhận và đặt giá trị đích |
| `completed` | Trạng thái quan sát được **thực sự** đã đạt giá trị đích |
| `rejected` | Bị từ chối trước khi có bất kỳ thay đổi nào |

Ở P0 simulator áp dụng tức thì nên `accepted` và `completed` xảy ra gần như đồng thời, và simulator được phép chỉ phát `completed`. **Không được gộp hai khái niệm này lại.** Trong xe thật, đặt nhiệt độ đích 24 °C không có nghĩa cabin đã 24 °C — giá trị thực hội tụ dần. Android Automotive tách rất rõ: `setPropertiesAsync` chỉ báo thành công khi *cả* lệnh xuống được bus *và* giá trị thực đã đạt target, quá hạn thì báo timeout. COVESA VSS và Eclipse Kuksa tách hẳn `target_value` và `current_value` cho mọi actuator.

Giữ hai phase để khi P1 mô phỏng độ trễ hội tụ — hoặc khi nối vào xe thật — hợp đồng không phải đổi. Đây đúng là điều ADR-004 nhắm tới: *"cho phép chứng minh observation thay vì optimistic success"*.

#### Vì sao không có attempt_count

`ToolResult` trong [data_model.md](data_model.md#toolresult) có `attempt_count`, `CommandEvent` thì không. Đây là chủ ý: simulator không biết executor đã thử lại mấy lần, chỉ executor biết. Executor ghép `attempt_count` vào khi persist `ToolResult` xuống SQLite.

Ranh giới sở hữu dữ liệu:

| Field | Ai sở hữu |
|---|---|
| `command_id`, `idempotency_key`, `plan_id`, `step_id`, `approval_id`, `execution_group_id`, `expected_state_version` | Executor (derive rồi gửi đi) |
| `phase`, `status`, `observed_state_version`, `before`, `after`, `error_code`, `latency_ms` | Simulator |
| `attempt_count` | Executor (không bao giờ lên MQTT) |

#### error_code

`null` khi `status = "completed"`. Ngược lại là một trong:

| Code | Khi nào | Retry được không |
|---|---|---|
| `stale_state` | `expected_state_version` khác version hiện tại | Không |
| `unsafe_vehicle_state` | Vi phạm invariant, ví dụ mở cửa khi `speed_kph != 0` | Không |
| `invalid_arguments` | `args` sai schema hoặc ngoài dải | Không |
| `tool_not_allowed` | Tool không có trong registry | Không |
| `internal_error` | Lỗi không lường trước trong simulator | Không |

**Không code nào trong bảng này được retry.** Executor chỉ retry đúng một lần cho *transient transport failure* — tức là không nhận được `CommandEvent` nào trong `MQTT_COMMAND_TIMEOUT_MS`. Xem §[Idempotency and retry](#idempotency-and-retry).

### SimMotionSet (harness)

Topic `v1/sim/{id}/motion/set`, retain = false. **Ngoài hợp đồng xe** — xem §[Kênh harness](#kenh-harness-v1sim--ngoai-hop-dong-xe). Schema: `schemas/mqtt/sim_motion_set.schema.json`.

```json
{
  "schema_version": "1.0",
  "speed_kph": 45,
  "gear": "D"
}
```

| Field | Kiểu | Bắt buộc | Ghi chú |
|---|---|:-:|---|
| `schema_version` | `"1.0"` | ✓ | |
| `speed_kph` | number `0..200` | ✓ | Trần là trần của **bàn đạo diễn**, không phải thông số VF9: đủ rộng cho mọi kịch bản S2/S3, đủ hẹp để một lỗi đơn vị (m/s đọc thành km/h) bị chặn thay vì publish âm thầm |
| `gear` | `P`\|`R`\|`N`\|`D`\|`null` | | Vắng mặt hoặc `null` = "chọn hộ tôi": `D` khi `speed_kph > 0`, `P` khi bằng 0 — đúng quy ước `set_motion(gear=None)` mà console stdin dùng |

Không có `command_id`, không có `tool`, không có `idempotency_key`: **đây không phải lệnh xe.** Nó không sinh `CommandEvent`, không đụng sổ chống lặp của lệnh, và `additionalProperties: false` khiến mọi cố gắng nhét `tool` vào bị từ chối ở tầng schema.

### DomainState

Topic `v1/vehicles/{id}/state/{domain}`, retain = true. **Message mới.**

```json
{
  "schema_version": "1.0",
  "vehicle_id": "vehicle-demo-01",
  "state_version": 42,
  "observed_at": "2026-08-03T02:00:12Z",
  "domain": "hvac",
  "status": "available",
  "state": {"power": true, "temperature_c": 24, "fan_level": 3}
}
```

`state` là đúng object của domain đó trong [`VehicleStateSnapshot`](#vehiclestatesnapshot), không thêm không bớt.

`status` ∈ `available | unavailable`, **tùy chọn, mặc định `available`**. P0 luôn phát `available`. Field có sẵn để P1 diễn đạt "navigation chưa bắt được GPS" hay "cảm biến cửa lỗi" mà không phải đổi schema — Android `CarPropertyValue` có `STATUS_AVAILABLE`/`UNAVAILABLE`/`ERROR` cho đúng nhu cầu này.

Simulator chỉ publish domain **vừa thay đổi**, không publish cả 9 domain mỗi lần. Toàn cảnh nằm ở `state/snapshot`.

### VehicleStateSnapshot

Topic `v1/vehicles/{id}/state/snapshot`, retain = true.

```json
{
  "schema_version": "1.0",
  "vehicle_id": "vehicle-demo-01",
  "state_version": 42,
  "observed_at": "2026-08-03T02:00:12Z",
  "motion":     {"speed_kph": 0, "gear": "P", "ignition": "ON"},
  "hvac":       {"power": true, "temperature_c": 24, "fan_level": 3},
  "windows":    {"front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0},
  "doors":      {"front_left": "closed", "front_right": "closed", "rear_left": "closed", "rear_right": "closed"},
  "media":      {"status": "paused", "volume": 35, "track": null},
  "navigation": {"status": "idle", "destination_id": null},
  "seat": {
    "front_left":  {"heating": 0, "fore_aft": 50, "recline": 50, "height": 50},
    "front_right": {"heating": 0, "fore_aft": 50, "recline": 50, "height": 50}
  },
  "lights":     {"headlight": "auto", "interior": false},
  "trunk":      {"position": "closed"}
}
```

Bỏ `schema_version` đi thì đây **phải bằng đúng** `data.vehicle_state` mà `GET /api/v1/vehicle/state` trả về ([api_spec.md](api_spec.md)). Backend chỉ forward state cache, **không map lại tên field**. Hai bên lệch nhau là bug.

`windows` là phần trăm mở: `0` đóng hoàn toàn, `100` mở hoàn toàn.

`state_version` tăng **đúng 1** cho mỗi transition được chấp nhận. Command bị reject không làm tăng. Command hợp lệ nhưng không đổi gì (ví dụ đặt nhiệt độ bằng giá trị đang có) cũng không làm tăng.

`seat` là **bổ sung so với `data_model.md`** — xem [Quyết định P0 số 1](#1-thêm-domain-seat).

`doors` **cố ý không có trường `locked`** ở P0 — xem [Quyết định P0 số 4](#4-doors-giữ-shape-phẳng-không-có-locked). `trunk` theo đúng deferral đó: chỉ có `position`, không có `locked`, và P1 sẽ thêm cho **cả hai** trong một lần.

`lights.headlight` là **enum chế độ, không phải boolean**, và **cố ý không có `off`** — UNECE R48 cấm chế độ tắt thủ công trên xe có đèn chạy ban ngày. Đèn sương mù nằm ngoài P0 vì sổ tay VF9 ghi "(nếu có trang bị)". Toàn bộ cơ sở ở [ADR-020](adr/ADR-020-lights-and-trunk-domains.md).

Simulator publish snapshot: khi Birth, và sau mỗi transition được chấp nhận.

### Health

Topic `v1/vehicles/{id}/health`, retain = true.

```json
{
  "schema_version": "1.0",
  "vehicle_id": "vehicle-demo-01",
  "online": true,
  "state_version": 42,
  "simulator_version": "1.0.0",
  "heartbeat_at": "2026-08-03T02:00:12Z"
}
```

Khi `online: false`, thêm `reason` ∈ `lwt | shutdown`. Khi `online: true`, `reason` bị cấm.

## Idempotency and retry

Idempotency key là `plan_id:step_id`, theo `data_model.md`.

**Phía simulator.** Cache `ToolResult`/`CommandEvent` theo `command_id`. Nhận lại cùng `command_id` thì trả nguyên kết quả cũ và **không** tạo transition thứ hai. Đây là điều làm QoS 1 an toàn.

**Phía executor.** Được retry **đúng một lần**, và chỉ khi *transient transport failure* — không nhận được `CommandEvent` nào trong `MQTT_COMMAND_TIMEOUT_MS`, hoặc publish bị lỗi ở tầng transport. Cả hai lần thử dùng **cùng** `command_id` và `idempotency_key`. Trước khi retry, executor phải tra `ToolResult` đã persist.

Không retry với: validation failure, policy denial, và mọi `error_code` ở bảng trên. Hết retry thì persist đúng một terminal `failed`/`timeout` rồi fail-fast.

Sau khi persist terminal, replay cùng `plan_id:step_id` trả về `ToolResult` đã lưu. Muốn thử lại thật thì phải re-plan với plan/step ID mới.

## Value ranges

Chép từ [agent_spec.md](agent_spec.md#tool-registry-and-planning-invariants) để tài liệu này tự đủ. **Bản ở `agent_spec.md` là canonical**; nếu lệch thì sửa file này.

| Tool | `args` | Safety |
|---|---|:-:|
| `get_vehicle_state` | `{}` | S0 |
| `query_manual` | `{query: string}`, trimmed 1..500 code point | S0 |
| `search_nearby_poi` | `{query: string, category?: enum["cafe","restaurant","fuel","parking"], limit?: integer 1..5 mặc định 3}` | S0 |
| `open_app` | `{app: enum["youtube","tiktok","spotify"]}` — enum đóng, không nhận URL | S1 / S3 |
| `set_hvac_temperature` | `{temperature_c: number}` với `16 <= temperature_c <= 30` | S1 |
| `set_hvac_power` | `{enabled: boolean}` | S1 |
| `set_hvac_fan_level` | `{level: integer}` với `0 <= level <= 3` | S1 |
| `set_seat_heating` | `{seat: enum["front_left","front_right"], level: integer}` với `0 <= level <= 3` | S1 |
| `media_control` | `{action: enum["play","pause","next","previous","set_volume","play_track"], volume?: integer 0..100, track_id?: string}`; `volume` bắt buộc khi và chỉ khi `action="set_volume"`, `track_id` bắt buộc khi và chỉ khi `action="play_track"` và phải là bài có thật trong `src/fixtures/media.json`, cả hai cấm ở các action khác | S1 |
| `set_navigation` | `{operation: enum["start","cancel"], destination_id?: string, destination_ref?: {from_step_id: string, selection: enum["first"]}}`; `start` cần đúng một trong `destination_id` hoặc `destination_ref`; `cancel` cấm cả hai | S1 |
| `set_window_position` | `{window: enum["front_left","front_right","rear_left","rear_right"], percent: integer 0..100}` | S2 luôn |
| `set_door_state` | `{door: enum[4 cửa], state: enum["open","closed"]}` | S2 khi đứng yên, ngược lại S3 |
| `set_seat_position` | `{seat: enum["front_left","front_right"], axis: enum["fore_aft","recline","height"], value: integer 0..100}` | S2 khi đứng yên, ngược lại S3 |
| `set_trunk_state` | `{state: enum["open","closed"]}` | S2 khi đứng yên, ngược lại S3 |
| `set_headlight_mode` | `{mode: enum["auto","low_beam","high_beam"]}` — **không có `off`**, xem ADR-020 | S1 |
| `set_interior_light` | `{enabled: boolean}` | S1 |

> **Trạng thái cài đặt (#325, 27/08):** `destination_ref` **không tồn tại trong code**. ADR-010 §Scope boundary đã loại `PlanningResolution` khỏi sprint và yêu cầu validator từ chối trường này; tới #325 thì `SetNavigationArgs` ở `src/services/tool_registry.py` cũng bỏ nó, nên cả hai cổng cùng từ chối. Trước đó registry **nhận** nó rồi để simulator ném lỗi — chết muộn, sau khi đã qua safety và có thể cả HITL. Phần mô tả dưới đây là thiết kế đích, không phải hành vi hôm nay; dựng lại `destination_ref` cần ADR riêng.

**Các dải này do nhóm tự quy định, không dẫn nguồn từ sổ tay VF9.** Sổ tay chỉ mô tả thao tác HMI ("chạm (+) để tăng nhiệt độ") và không công bố min/max cho bất kỳ tham số nào. Điều này phù hợp thông lệ: COVESA VSS cũng định nghĩa `HVAC.Station.*.Temperature` là float Celsius **không áp min/max**, vì dải là đặc thù từng hãng.

Tool không có trong bảng → `tool_not_allowed`. Args sai schema hoặc ngoài dải → `invalid_arguments`. Cả hai đều không retry.

## Broker security

Theo [devops.md](devops.md): `MQTT_ALLOW_ANONYMOUS=false`, hai identity tách biệt, ACL giới hạn theo chiều publish/subscribe.

```
user vivi-backend
topic write  v1/vehicles/+/commands/#
topic read   v1/vehicles/+/events/#
topic read   v1/vehicles/+/state/#
topic read   v1/vehicles/+/health
topic write  v1/sim/+/motion/set

user vehicle-simulator
topic read   v1/vehicles/+/commands/#
topic write  v1/vehicles/+/events/#
topic write  v1/vehicles/+/state/#
topic write  v1/vehicles/+/health
topic read   v1/sim/+/motion/set
```

Dòng `v1/sim/` thuộc [kênh harness](#kenh-harness-v1sim--ngoai-hop-dong-xe), không thuộc hợp đồng xe. Nó liệt kê **đích danh** `motion/set`: `topic write v1/sim/+/#` sẽ cấp phép trước cho mọi topic harness chưa ai kịp nghĩ nó nên tồn tại hay không (ADR-024).

Backend không được publish lên state/health; simulator không được publish lên commands. Không client nào đọc được password file của client kia hay quản trị broker.

Broker chỉ bind `127.0.0.1:1883` làm debug binding; traffic thật đi trên network `edge_internal` (`internal: true`). Broker **không bao giờ** expose ra interface non-loopback.

## Chạy thử

```powershell
# 1. Sinh password cho hai identity (một lần duy nhất)
pwsh scripts/bootstrap_mqtt_secrets.ps1
#    -> chép 4 dòng nó in ra vào .env

# 2. Broker
docker compose up -d mqtt

# 3. Xe ảo và backend, mỗi cái một cửa sổ
python -m src.vehicle_sim
python -m src.serve

# 4. Nghiệm thu 3 acceptance criteria
python scripts/smoke_mqtt.py
```

Xem cây topic đang có:

```powershell
docker exec p-192-mqtt-1 mosquitto_sub -h localhost -p 1883 `
  -u vivi-backend -P "<mật khẩu>" -t 'v1/vehicles/#' -v
```

Ba lưu ý về môi trường:

- **Trên Windows phải chạy `python -m src.serve`, không phải `uvicorn src.main:app`.** Uvicorn chọn event loop bằng loop_factory riêng và trên Windows trả về `ProactorEventLoop`; loop đó không có `add_reader`/`remove_writer` mà paho-mqtt cần, nên mọi kết nối MQTT sẽ nổ `NotImplementedError`. Trong container Linux thì `uvicorn src.main:app` vẫn đúng.
- **Nếu máy đã có broker khác giữ cổng 1883** (RabbitMQ bật plugin MQTT, EMQX, ...), đặt `MQTT_HOST_PORT=1884` và `MQTT_URL=mqtt://localhost:1884` trong `.env`. Chỉ cổng loopback phía host đổi; trong docker network các service vẫn nối `mqtt:1883`.
- **Contract test cần broker thật** và mặc định bị bỏ qua. Bật bằng `MQTT_CONTRACT_TESTS=1` cùng hai cặp username/password, xem `tests/test_vehicle/test_contract_mosquitto.py`.

## Kiểm chứng

| Lệnh | Kiểm gì |
|---|---|
| `python scripts/validate_mqtt_schemas.py .` | 6 JSON Schema: 7 payload hợp lệ phải pass, 13 payload sai phải fail |
| `python scripts/crosscheck_mqtt_spec.py .` | Không có tool/domain mồ côi giữa tài liệu này, `agent_spec.md` và `schemas/mqtt/` |
| `pytest tests/test_vehicle/ tests/test_api/test_vehicle_state.py` | Invariant simulator, vòng tròn executor↔simulator, REST, WebSocket |
| `pytest tests/test_vehicle/test_contract_mosquitto.py` | QoS/retain/LWT trên Mosquitto thật (cần `MQTT_CONTRACT_TESTS=1`) |
| `python scripts/smoke_mqtt.py` | 3 acceptance criteria end-to-end |

## Quyết định đã chốt

**Trạng thái: đã duyệt.** Bốn mục dưới đây từng là chỗ tài liệu này khác canonical. Cả bốn đã có quyết định và canonical đã được đồng bộ theo — không còn lệch contract.

Trước đây chúng mang tên *Open question 1–4*. Số thứ tự giữ nguyên; một số comment trong `src/` và `schemas/` vẫn dùng tên cũ.

| # | Quyết định | Trạng thái |
|---|---|---|
| 1 | Giữ domain `seat` | Đã implement; `data_model.md` và `api_spec.md` đã thêm `seat` |
| 2 | `hvac.fan_level` read-only ở P0, không thêm tool mới | **Đã lật** 2026-08-12 — có `set_hvac_fan_level` (0..3, S1), xem ADR-019 |
| 3 | `windows` dùng 4 cửa | Đã implement; `VIVI_API_Spec.md` đã sửa |
| 4 | `doors` chưa có `locked` | **Hoãn** sang follow-up, xem [Việc còn lại](#việc-còn-lại) |

### 1. Thêm domain `seat`

`agent_spec.md` có `set_seat_heating` và `set_seat_position`, nhưng vehicle state ở `data_model.md` chỉ có 6 domain và **không có chỗ nào chứa trạng thái ghế**. Lệnh chạy xong không có nơi lưu, API không trả về, UI không hiển thị được, và không verify được lệnh có thành công không.

**Quyết định: giữ `seat`**, vì nó nằm trong phạm vi hai tool điều khiển ghế đã có trong registry. Đã implement (`SeatState` trong `src/models/vehicle.py`) và **canonical đã đồng bộ**: [`data_model.md`](data_model.md#vehicle-state) và [`api_spec.md`](api_spec.md) đều đã có `seat`, nên bốn nguồn — hai canonical, tài liệu này, và `schemas/mqtt/` — vẫn cùng một con số. Con số đó là **7 lúc ra quyết định này**, và là **9 từ issue #65** (thêm `lights` + `trunk`, xem [ADR-020](adr/ADR-020-lights-and-trunk-domains.md)); điều bất biến ở đây là bốn nguồn phải khớp nhau, không phải bản thân con số.

### 2. `hvac.fan_level` — read-only ở P0, **đã lật** 2026-08-12

**Quyết định gốc (P0): giữ read-only.** `data_model.md` có `hvac.fan_level` nhưng registry không có tool nào đổi được, nên trường này vĩnh viễn đứng yên ở giá trị khởi tạo. Đã implement với `int` chỉ chặn dưới (`ge=0`), **cố ý không khai chặn trên** vì chưa biết thang tối đa.

**Đã lật (issue #65, [ADR-019](adr/ADR-019-fan-level-becomes-controllable.md)):** FE dựng sẵn slider quạt gió nhưng không có đường nối nào ở router hay registry, và câu `"chỉnh quạt gió điều hòa mức 3"` còn bị đọc nhầm thành lệnh nhiệt độ rồi trả `temperature_out_of_range` — báo sai lý do cho người dùng.

Nay có `set_hvac_fan_level` (`{level: integer}`, `0 <= level <= 3`, S1, `commands/hvac`) và `HvacState.fan_level` có thêm `le=3`. Trần là **bắt buộc**, không phải tùy chọn: thiếu nó thì `validate_assignment` của simulator không chặn được giá trị vô nghĩa.

**Giữ tên `fan_level`, không đổi sang `fan_speed_percent`.** COVESA VSS chuẩn hóa `FanSpeed` là `uint8` percent `0..100` (`0 = off, 100 = max`) và đó vẫn là hướng đúng về lâu dài, nhưng đổi tên field là **breaking change** trên `GET /api/v1/vehicle/state`, `state/hvac` và `state/snapshot` — FE đang đọc `fan_level`. Đổi thang cùng lúc với việc mở tool sẽ gộp hai thay đổi độc lập vào một PR. Để lại cho P1, và khi đó phải làm cùng lúc với `doors.locked` + `trunk.locked` để chỉ có **một** lần breaking.

**Dải `0..3` do nhóm tự quy định, không dẫn nguồn từ sổ tay VF9** — sổ tay không công bố thang quạt tối đa, chỉ chứng minh được mức 1 tồn tại (chế độ Nap Mode). Cùng tiền lệ và cùng cách ghi với dải `16..30 °C`.

### 3. `windows` dùng 4 cửa, không phải 2

`docs/VIVI_API_Spec.md` **từng** mô tả `windows: {driver, passenger}`, lệch với canonical `data_model.md` vốn dùng 4 cửa `front_left`/`front_right`/`rear_left`/`rear_right`.

**Quyết định: theo canonical 4 cửa.** Đã implement, và **`VIVI_API_Spec.md` đã được sửa** — không chỉ `windows` mà cả response mẫu, vì file đó còn dùng `ac`/`music`/`speed_kmh`/`driving_mode` đều lệch. Sửa mỗi `windows` sẽ để lại một tài liệu đúng một nửa, dễ gây nhầm hơn là sai hẳn.

### 4. `doors` giữ shape phẳng, không có `locked`

`doors` chỉ có `open`/`closed`. **Cả ba API xe hơi thực tế được khảo sát đều tách khóa và mở thành hai khái niệm độc lập:**

- High Mobility AutoAPI `doors.yml` có `Locks` (property 0x03) và `Positions` (0x04) riêng biệt, thậm chí còn `Inside locks` (0x02) thứ ba.
- COVESA VSS tách `IsLocked` và `IsOpen`.
- Smartcar `GET /vehicles/:id/doors` trả lock status riêng.

Nghĩa là xe đang khóa vẫn báo `closed`, và lệnh mở cửa khi đang khóa lẽ ra phải fail — schema P0 không diễn đạt được điều đó.

**Quyết định: hoãn sang follow-up riêng, không làm trong PR này.** Registry P0 không có tool khóa/mở khóa, nên `locked` sẽ là một hằng số không ai ghi và không ai đọc; đổi lại nó buộc phải sửa response `GET /api/v1/vehicle/state` ngay. Đây là mục duy nhất trong bốn mục mà việc hoãn **không chặn tool nào cả** — ba mục kia đều có tool đang chờ. Xem [Việc còn lại](#việc-còn-lại).

**Đây là nợ kỹ thuật có chủ ý, không phải thiếu sót.** Hệ quả, cần FE biết trước:

> Khi P1 thêm `set_door_lock`, mỗi cửa trong `doors` sẽ đổi từ **string** sang **object** — `"closed"` thành `{"state": "closed", "locked": true}`. Đó là **breaking change** trên `GET /api/v1/vehicle/state`, `state/doors` và `state/snapshot`. Code FE đọc `doors.front_left` như string sẽ hỏng.

Shape dự kiến của P1, ghi ở đây để lúc đó không phải thiết kế lại:

```json
"doors": {
  "front_left":  {"state": "closed", "locked": true},
  "front_right": {"state": "closed", "locked": true},
  "rear_left":   {"state": "closed", "locked": true},
  "rear_right":  {"state": "closed", "locked": true}
}
```

Ai muốn tránh breaking change đó thì phải chốt shape object **ngay ở P0**, trước khi FE đọc `doors` — không phải sau.

## Alignment with automotive standards

Mục này ghi lại đối chiếu giữa schema VIVI và các chuẩn/API xe hơi thực tế, để người sau biết chỗ nào theo chuẩn và chỗ nào cố ý khác.

Đã khảo sát: COVESA **VSS**, Eclipse **Kuksa**, High Mobility **AutoAPI**, **Smartcar** v3, Android Automotive **CarPropertyManager/VHAL**, W3C **VISS2**, Eclipse **Sparkplug B**, **AUTOSAR Adaptive** `ara::com`.

### Điểm khớp chuẩn

| Thiết kế VIVI | Chuẩn xác nhận |
|---|---|
| Tách 3 mặt: đọc state / gửi lệnh / nhận sự kiện đổi | AUTOSAR `ara::com` **field** = get method + set method + on-change event — đúng bộ ba `GET /api/v1/vehicle/state` + `commands/{domain}` + `state/{domain}` |
| Topic gắn định danh xe | VISS2 MQTT binding dùng `VID/Vehicle`, cũng lấy vehicle ID làm gốc topic |
| JSON payload trên MQTT cho tín hiệu xe | VISS2 chuẩn hóa đúng việc này (get/set/subscribe qua HTTP/WebSocket/MQTT) |
| Enum `phase` tách `accepted` khỏi `completed` (P0 chỉ phát `completed` — xem [§phase và status](#phase-và-status)) | Android `setPropertiesAsync` chỉ báo success khi *cả* lệnh xuống bus *và* giá trị thực đạt target |
| `front_left`/`front_right`/`rear_left`/`rear_right` | AutoAPI `doors.yml` dùng đúng bộ tên này |
| Window là % mở, 0 đóng 100 mở | VSS `Window.Position` unit `percent`; Android `WINDOW_POS` cùng ý |
| Tự quy định dải `16..30 °C` | VSS `HVAC.Station.*.Temperature` không áp min/max — dải là đặc thù hãng |
| Birth + LWT retained | Sparkplug B NBIRTH/NDEATH certificate |
| Chỉ publish domain vừa đổi | Sparkplug B RBE (Report By Exception) |
| `state_version` tăng dần | Sparkplug B `seq`; VSS/Kuksa dùng version tương tự |
| `schema_version` mỗi message | AutoAPI prefix protocol version mọi command |

### Hai điểm khác chuẩn, có chủ ý

**Tên vị trí.** Ngành có hai quy ước song song. VSS — vốn là *cây tín hiệu* — dùng `Vehicle.Cabin.Door.Row1.DriverSide`. AutoAPI — vốn là *API lệnh*, đúng dạng bài toán của VIVI — dùng `front_left`/`front_right`/`rear_left`/`rear_right`. VIVI theo AutoAPI. Bảng ánh xạ sang VSS cho P2:

| VIVI | VSS |
|---|---|
| `doors.front_left` | `Vehicle.Cabin.Door.Row1.DriverSide.IsOpen` |
| `doors.front_right` | `Vehicle.Cabin.Door.Row1.PassengerSide.IsOpen` |
| `doors.rear_left` | `Vehicle.Cabin.Door.Row2.DriverSide.IsOpen` |
| `doors.rear_right` | `Vehicle.Cabin.Door.Row2.PassengerSide.IsOpen` |
| `windows.front_left` | `Vehicle.Cabin.Door.Row1.DriverSide.Window.Position` |
| `hvac.temperature_c` | `Vehicle.Cabin.HVAC.Station.Row1.Driver.Temperature` |
| `hvac.fan_level` | `Vehicle.Cabin.HVAC.Station.Row1.Driver.FanSpeed` |
| `motion.speed_kph` | `Vehicle.Speed` |
| `motion.gear` | `Vehicle.Powertrain.Transmission.CurrentGear` |
| `lights.headlight` = `low_beam` | `Vehicle.Body.Lights.Beam.Low.IsOn` |
| `lights.headlight` = `high_beam` | `Vehicle.Body.Lights.Beam.High.IsOn` |
| `trunk.position` | `Vehicle.Body.Trunk.Rear.IsOpen` |

**`windows` là domain phẳng.** VSS lồng window dưới door. VIVI tách ra thành domain riêng để topic MQTT phẳng, dễ route và dễ viết ACL.

### Ba đơn giản hóa có ý thức của P0

| Chuẩn có | VIVI P0 | Lý do |
|---|---|---|
| `target_value` vs `current_value` cho mọi actuator (Kuksa/VSS); `waitForPropertyUpdate` (Android) | Một giá trị duy nhất, áp dụng tức thì | Giữ nguyên hai `phase` nên hợp đồng không đổi khi P1 mô phỏng độ trễ hội tụ |
| Trạng thái khả dụng từng tín hiệu (Android `CarPropertyValue`, AutoAPI component `availability`/`failure`) | Chỉ có `DomainState.status`, luôn `available` | Đủ chỗ để P1 mở rộng mà không đổi schema |
| Timestamp từng property (AutoAPI component 0x02) | Một `observed_at` cho cả snapshot | P0 không cần độ phân giải đó |

### Ghi chú về tương quan request/response

VISS2 trên MQTT dùng reply-topic riêng kèm `requestId`. MQTT 5 chuẩn hóa sẵn `Response Topic` + `Correlation Data` cho đúng việc này.

VIVI dùng cách đơn giản hơn: tương quan bằng `command_id` trên topic `events/command` dùng chung. Hợp lệ vì P0 chỉ có **đúng một** consumer là backend. Nếu P2 có nhiều consumer, `command_id` map thẳng sang MQTT 5 `Correlation Data` mà không phải đổi payload.

### Nguồn

- [High Mobility AutoAPI](https://github.com/highmobility/auto-api) — [`capabilities/doors.yml`](https://github.com/highmobility/auto-api/blob/master/capabilities/doors.yml)
- [COVESA Vehicle Signal Specification](https://covesa.github.io/vehicle_signal_specification/rule_set/basics/) — [`SingleHVACStation.vspec`](https://github.com/COVESA/vehicle_signal_specification/blob/master/spec/Cabin/SingleHVACStation.vspec)
- [W3C VISSv2 Transport](https://w3c.github.io/automotive/spec/VISSv2_Transport.html)
- [Eclipse Kuksa Databroker](https://github.com/eclipse-kuksa/kuksa-databroker)
- [AUTOSAR AP — Explanation of ara::com API](https://www.autosar.org/fileadmin/standards/R24-11/AP/AUTOSAR_AP_EXP_ARAComAPI.pdf)
- [Eclipse Sparkplug 3.0 Specification](https://sparkplug.eclipse.org/specification/version/3.0/documents/sparkplug-specification-3.0.0.pdf)
- [Android CarPropertyManager](https://developer.android.com/reference/android/car/hardware/property/CarPropertyManager) · [CarPropertyValue](https://developer.android.com/reference/android/car/hardware/CarPropertyValue)
- [Smartcar API Reference](https://smartcar.com/docs/api-reference/intro)
- [HiveMQ — Retained Messages](https://www.hivemq.com/blog/mqtt-essentials-part-8-retained-messages/) · [Last Will and Testament](https://www.hivemq.com/blog/mqtt-essentials-part-9-last-will-and-testament/) · [MQTT 5 Request-Response](https://www.hivemq.com/blog/mqtt5-essentials-part9-request-response-pattern/)
- [EMQX — MQTT QoS 0/1/2](https://www.emqx.com/en/blog/introduction-to-mqtt-qos)

## Việc còn lại

Ba mục dưới đây **cố ý nằm ngoài phạm vi** PR MQTT, tách ra để giữ PR đúng một chủ đề. Ghi ở đây thay cho issue tracker; ai nhận việc thì đọc mục tương ứng.

### 1. Door lock — thêm `locked` vào `doors`

Xem [Quyết định 4](#4-doors-giữ-shape-phẳng-không-có-locked) ở trên để biết vì sao hoãn.

Việc phải làm: thêm tool `set_door_lock` vào registry, thêm `locked` vào `DoorsState`, cập nhật `data_model.md` + `api_spec.md` + `schemas/mqtt/vehicle_state_domains.schema.json`.

> **Cảnh báo cho FE.** Mỗi cửa trong `doors` sẽ đổi từ **string** sang **object** — `"closed"` thành `{"state": "closed", "locked": true}`. Đây là **breaking change** trên `GET /api/v1/vehicle/state`, `state/doors` và `state/snapshot`. Code đọc `doors.front_left` như string sẽ hỏng. Muốn tránh thì phải chốt shape object **trước khi** FE đọc `doors`, không phải sau.

### 2. WebSocket authentication

`src/api/ws.py` hiện chấp nhận mọi kết nối. [api_spec.md](api_spec.md#websocket-contracts) yêu cầu:

- Bearer token trong `Sec-WebSocket-Protocol` (`vivi.v1, bearer.<token>`), chỉ chọn lại `vivi.v1` khi trả lời
- Kiểm chữ ký và hạn token, vai trò, `Origin` khớp allowlist, và quyền sở hữu session với `/ws/ivi`
- Đóng `4401` khi thiếu/hết hạn auth, `4403` khi sai vai trò/origin/session
- Replay cursor `last_event_id` + `last_sequence`, với `REPLAY_CURSOR_INVALID` và `REPLAY_WINDOW_EXPIRED`

Chưa làm được vì module auth/session chưa tồn tại trong code. Vỏ sự kiện đã đúng hợp đồng nên khi có auth chỉ cần cắm vào, không phải viết lại.

### 3. HITL endpoint trong `ARCHITECTURE.md`

`ARCHITECTURE.md` (sequence diagram HITL) dùng `POST /api/v1/hitl/confirm`, trong khi canonical là `POST /api/v1/approvals/{approval_id}/decision` ([api_spec.md](api_spec.md)). Là lỗi thật nhưng thuộc API HITL chứ không phải MQTT, nên để nguyên trong PR MQTT.

# MQTT trong VIVI — giải thích cho người chưa từng đọc dự án này

> **Đối tượng:** người mới, không cần biết trước gì về MQTT, về xe hơi, hay về repo này.
> **Mục tiêu:** đọc xong hiểu được *vì sao* dự án chọn MQTT, *ai nói chuyện với ai*, và
> *một câu nói của người dùng đi qua những chặng nào* trước khi đèn trên màn hình đổi màu —
> kể cả khi câu đó là *câu hỏi* và đi vào sổ tay xe thay vì đi ra broker (mục 6).
>
> Tài liệu này là bản **giải thích**, không phải bản hợp đồng. Hợp đồng chuẩn nằm ở
> [`docs/mqtt_spec.md`](mqtt_spec.md), [`ADR-004`](adr/ADR-004-mqtt-vehicle-simulator.md)
> và [`ADR-013`](adr/ADR-013-single-vehicle-state-source.md). Khi hai bên lệch nhau, tin ba file kia.
>
> Cập nhật: 2026-08-12, đối chiếu với code trên nhánh `develop`.

---

## 0. Đọc trong 60 giây

VIVI là trợ lý giọng nói trong cabin xe. Người dùng nói *"bật điều hòa 24 độ"*, hệ thống
phải **làm thật** — chứ không phải trả lời "vâng, đã bật" rồi thôi.

Nhưng đây là đồ án. **Không có xe thật, và tuyệt đối không được nối vào CAN bus của xe thật.**
Nên dự án dựng một **xe ảo** (digital twin) chạy như một tiến trình riêng, và cho backend nói
chuyện với xe ảo đó qua **MQTT** — đúng cái giao thức nhắn tin mà thiết bị IoT và xe kết nối
thật vẫn dùng.

Kết quả: backend **không biết** đầu bên kia là xe ảo hay xe thật. Nó chỉ biết gửi lệnh lên
một *topic*, rồi chờ *sự kiện* báo về. Ngày nào có phần cứng thật, thay cái tiến trình xe ảo
là xong, hợp đồng không đổi một dòng.

Mục 1–5 là phần khai triển của một câu đó.

**Nhưng MQTT chỉ là một nửa câu chuyện.** Phần lớn câu người dùng nói không phải là *lệnh* mà là
*câu hỏi* — và câu hỏi đi một đường hoàn toàn khác, **không chạm MQTT**: nó đi vào chỉ mục sổ tay
VF9 dựng sẵn trên đĩa. Mục 6 nói về nửa còn lại đó, và về câu hỏi quan trọng nhất khi đánh giá
một trợ lý: *câu trả lời này lấy dữ liệu từ đâu?*

---

## 1. MQTT là gì (giải thích không dùng thuật ngữ)

### 1.1 Hình dung bằng bảng tin công ty

Tưởng tượng một văn phòng có **một tấm bảng tin lớn ở giữa sảnh**. Bảng chia thành nhiều ngăn
có dán nhãn: *"Thông báo/Nhân sự"*, *"Thông báo/Kế toán"*, *"Thực đơn hôm nay"*.

- Ai muốn báo tin thì **dán giấy vào đúng ngăn**. Không cần biết ai sẽ đọc.
- Ai quan tâm thì **đăng ký theo dõi một ngăn**. Có giấy mới dán vào ngăn đó là được báo ngay.
- Người dán và người đọc **không bao giờ phải biết mặt nhau**, không hẹn giờ, không gọi điện.

Đó chính xác là MQTT:

| Bảng tin | MQTT | Trong VIVI |
|---|---|---|
| Tấm bảng ở sảnh | **Broker** | Mosquitto, chạy trong Docker |
| Ngăn có dán nhãn | **Topic** | `v1/vehicles/vehicle-demo-01/commands/hvac` |
| Dán giấy vào ngăn | **Publish** | Backend gửi lệnh bật điều hòa |
| Đăng ký theo dõi ngăn | **Subscribe** | Xe ảo lắng nghe mọi lệnh gửi cho nó |
| Người dán / người đọc | **Client** | `vivi-backend` và `vehicle-simulator` |

### 1.2 Khác gì với REST/HTTP mà ai cũng quen?

HTTP là **gọi điện thoại**: bạn gọi cho một người cụ thể, đợi họ nhấc máy, hỏi, nghe trả lời,
cúp máy. Bạn phải biết số của họ, và họ phải đang online.

MQTT là **bảng tin**: bạn dán rồi đi. Ai đọc, đọc lúc nào, có bao nhiêu người đọc — không liên quan.

Vì sao khác biệt này quan trọng với xe:

- Xe **liên tục** phát ra trạng thái (tốc độ, số, nhiệt độ) mà không ai hỏi. Với HTTP bạn phải
  *hỏi đi hỏi lại* (polling) — tốn, chậm, và luôn trễ. Với MQTT xe cứ dán, ai cần thì đã đăng ký sẵn.
- Một tin có thể có **nhiều người đọc**: backend đọc để suy luận an toàn, màn hình đọc để hiển thị,
  dashboard đọc để giám sát. Người dán không phải sửa gì khi có thêm người đọc thứ ba.
- Xe có thể **mất kết nối** (hầm gửi xe, vùng lõm sóng). MQTT thiết kế sẵn cho chuyện đó.

### 1.3 Bốn khái niệm MQTT bạn cần nhớ để đọc phần sau

**a) Topic** — cái nhãn của ngăn. Phân cấp bằng dấu `/`, và có ký tự đại diện:
`v1/vehicles/+/state/#` nghĩa là "mọi topic trạng thái, của bất kỳ xe nào".

**b) QoS (Quality of Service)** — mức đảm bảo giao hàng, có 3 mức:

| QoS | Nghĩa | Ví dụ đời thường |
|:-:|---|---|
| 0 | Gửi rồi thôi, có thể mất | Thả tờ rơi vào hòm thư |
| 1 | Đảm bảo tới **ít nhất một lần** (có thể tới 2 lần) | Thư bảo đảm — bưu tá gửi lại nếu không thấy ký nhận |
| 2 | Đảm bảo tới **đúng một lần** | Thư bảo đảm có 4 lượt xác nhận qua lại |

**c) Retain (giữ lại)** — cờ đánh dấu "giấy này dán **ở lại bảng**". Ai đăng ký ngăn này sau đó,
dù muộn 3 tiếng, vẫn đọc được ngay tờ giấy cuối cùng mà không phải chờ tin mới.
Không có retain thì người tới muộn nhìn thấy... một cái ngăn trống.

**d) Last Will and Testament (LWT — di chúc)** — cái này rất đặc trưng của MQTT và rất hay.
Khi một client kết nối, nó **gửi trước cho broker một tờ giấy kèm lời dặn**:
*"nếu tôi đột ngột mất tích, anh dán hộ tôi tờ này lên bảng."*
Broker giữ tờ giấy đó. Client chết vì rút điện, treo máy, đứt mạng — broker phát hiện im lặng
quá lâu và **tự dán tờ giấy** đó lên. Nhờ vậy cả hệ thống biết ngay là nó chết, chứ không phải
đoán mò qua timeout.

Ngược lại với LWT là **Birth** — tờ giấy "tôi sống rồi đây" mà client tự dán ngay sau khi kết nối thành công.

---

## 2. Vì sao VIVI dùng MQTT chứ không phải cái khác

Bài toán ban đầu, viết trong [ADR-004](adr/ADR-004-mqtt-vehicle-simulator.md):

> Đề tài cần chứng minh **tool-use** (trợ lý thật sự *làm* việc, không chỉ *nói*) và quan sát
> trạng thái xe, nhưng **tuyệt đối không kết nối CAN/xe thật**.

Nhóm cân nhắc ba phương án:

| Phương án | Được | Mất |
|---|---|---|
| Gọi hàm Python trực tiếp trong cùng tiến trình | Nhanh nhất, dễ test nhất | Không mô phỏng được gì cả: không có bus, không có mất kết nối, không có bất đồng bộ. Backend và "xe" dính chặt nhau |
| Dựng simulator kiểu REST | Ai cũng quen, request-response rõ ràng | Streaming trạng thái rất gượng — phải polling; không diễn đạt được vòng đời lệnh |
| **MQTT broker + digital twin** ✅ | Event-driven đúng bản chất, có topic trạng thái, dễ mở rộng nhiều xe | Phải tự lo idempotency, thứ tự, cấu hình broker |

Chọn phương án 3. Năm lý do, xếp theo mức quan trọng:

**① Nó giống thật.** MQTT là giao thức mà xe kết nối, thiết bị IoT, và nhà máy đang dùng thật.
W3C có chuẩn [VISS2](https://w3c.github.io/automotive/spec/VISSv2_Transport.html) đưa tín hiệu xe
lên MQTT. Eclipse có Kuksa. Nghĩa là những gì học được ở đồ án này không phải kiến thức bỏ đi.

**② Nó cho phép chứng minh *quan sát*, không phải *lạc quan*.** Đây là ý sâu nhất của ADR-004.
Nếu gọi hàm trực tiếp, "thành công" chỉ có nghĩa là hàm không ném exception. Với MQTT, backend
gửi lệnh xong **phải chờ xe ảo báo về** rằng nó đã thực sự đổi trạng thái, kèm giá trị trước và sau.
Không có sự kiện báo về = không dám nói là thành công. Đó là khác biệt giữa
*"tôi đã bấm nút"* và *"đèn đã sáng"*.

**③ Nó tách bạch quyền sở hữu.** Xe ảo do một người làm (workstream WS3), agent/HITL do người khác,
frontend người khác nữa. MQTT + JSON Schema là **hợp đồng** giữa họ: ai cũng code được song song,
miễn không phá hợp đồng.

**④ Nó cho phép giả lập hỏng hóc.** Tắt broker → xem hệ thống có báo đúng lỗi không. Giết xe ảo →
xem LWT có hoạt động không. Với lời gọi hàm trực tiếp thì không có gì để hỏng, nên cũng không
chứng minh được gì về độ bền.

**⑤ Nó mở đường cho P2.** Topic đã có `{vehicle_id}` bên trong, nên thêm chiếc xe thứ hai
không phải đổi cấu trúc topic. Dashboard nhiều xe là chuyện thêm subscriber.

> **Điều MQTT ở đây *không* làm:** nó không phải cơ sở dữ liệu. ADR-004 nói rõ —
> "SQLite lưu audit/tool results, **không dùng MQTT làm persistent source of truth**".
> MQTT là dây dẫn, không phải kho.

---

## 3. Bản đồ: ai nói chuyện với ai

```
┌──────────────┐        HTTP/WebSocket        ┌───────────────────────────┐
│  Frontend    │ ◄──────────────────────────► │   Backend (FastAPI)       │
│  (Next.js)   │   /turns/text, /ws/ivi       │   python -m src.serve     │
│  màn hình    │   GET /vehicle/state         │                           │
│  trong xe    │                              │  ┌─────────────────────┐  │
└──────────────┘                              │  │ LangGraph agent     │  │
                                              │  │ router → policy →   │  │
                                              │  │ HITL → execute      │  │
                                              │  └──────────┬──────────┘  │
                                              │             │             │
                                              │  ┌──────────▼──────────┐  │
                                              │  │  VehicleGateway     │  │  ◄── ADR-013:
                                              │  │  (cổng duy nhất)    │  │      MỘT cửa duy nhất
                                              │  └──────┬───────┬──────┘  │      ra vào xe
                                              │   đọc   │       │  ghi    │
                                              │  ┌──────▼──┐ ┌──▼───────┐ │
                                              │  │ State   │ │ Tool     │ │
                                              │  │ Cache   │ │ Executor │ │
                                              │  └────▲────┘ └────┬─────┘ │
                                              └───────┼───────────┼───────┘
                                    subscribe state/  │           │  publish commands/
                                    health            │           │
                                              ┌───────┴───────────▼───────┐
                                              │   Mosquitto MQTT broker   │
                                              │   (Docker, cổng 1883)     │
                                              │   có mật khẩu + ACL       │
                                              └───────┬───────────▲───────┘
                                    publish state/    │           │  subscribe commands/
                                    events/ health    │           │
                                              ┌───────▼───────────┴───────┐
                                              │   Xe ảo (digital twin)    │
                                              │   python -m src.vehicle_sim│
                                              │   tiến trình RIÊNG        │
                                              │   giữ trạng thái thật     │
                                              └───────────────────────────┘
```

**Điểm quan trọng nhất trong sơ đồ này:** backend và xe ảo là **hai tiến trình khác nhau**,
không gọi hàm của nhau, không chia sẻ biến. Chúng chỉ trao đổi qua JSON đi qua broker.
Đó là lý do hệ thống này chứng minh được điều mà một lời gọi hàm không chứng minh được.

Trong Docker Compose có đúng ba service này (`mqtt`, `vehicle-simulator`, `backend`).
Backend và xe ảo đều **chờ broker khỏe** rồi mới khởi động.

---

## 4. Năm cái topic, và chúng để làm gì

Quy ước tên: `v1/vehicles/{id}/...`, với `{id}` ở P0 luôn là `vehicle-demo-01`.

| Topic | Ai dán | Ai đọc | QoS | Retain | Để làm gì |
|---|---|---|:-:|:-:|---|
| `commands/{domain}` | Backend | Xe ảo | 1 | **false** | "Hãy bật điều hòa 24 độ" |
| `events/command` | Xe ảo | Backend | 1 | false | "Đã bật xong, trước 27 sau 24, mất 38ms" |
| `state/{domain}` | Xe ảo | Backend, UI | 1 | **true** | "Điều hòa hiện đang: bật, 24 độ, quạt mức 3" |
| `state/snapshot` | Xe ảo | Backend | 1 | **true** | Ảnh chụp toàn bộ 9 nhóm trạng thái cùng lúc |
| `health` | Xe ảo | Backend | 1 | **true** | "Tôi còn sống" (5 giây/lần) hoặc "tôi chết rồi" |

`{domain}` là một trong chín nhóm: `motion | hvac | windows | doors | media | navigation | seat | lights | trunk`
(`lights` và `trunk` thêm ở issue #65 — xem [ADR-020](adr/ADR-020-lights-and-trunk-domains.md)).

Trong đó **`motion` là chỉ-đọc**. Không có topic lệnh nào cho nó — backend *không được phép*
đặt tốc độ xe. Nó chỉ đọc `state/motion` để biết `speed_kph`, `gear`, `ignition`, và dùng ba
giá trị đó để phân loại an toàn (mục 7.5).

> **`state/{domain}` và `state/snapshot` khác nhau chỗ nào?**
> Xe ảo chỉ publish `state/{domain}` cho **nhóm vừa thay đổi** — đổi nhiệt độ thì chỉ dán lại
> ngăn `hvac`, không dán lại cả chín ngăn. Còn `state/snapshot` là ảnh chụp toàn cảnh, để một
> subscriber mới nối vào chỉ cần đọc một tin là có đủ. Đây là kỹ thuật chuẩn, Sparkplug B gọi
> là *Report By Exception*.

---

## 5. Luồng chi tiết: "Bật điều hòa 24 độ"

Đây là phần chính. Ta đi theo một câu nói, từ lúc phát ra tới lúc màn hình đổi.

### Bước 1–3: từ lời nói đến ý định (chưa có MQTT)

```
1. Người dùng nói → STT (faster-whisper) → "bật điều hòa 24 độ"
2. Router (luật tất định, KHÔNG dùng LLM) nhận ra:
      tool = set_hvac_temperature, args = {temperature_c: 24}
      → tạo CandidateActionPlan (bản nháp, CHƯA có mức an toàn)
3. Policy gán mức an toàn: S1 (thực thi được, không cần hỏi lại)
      → biến thành ActionPlan (bản chính thức)
```

> Chi tiết đáng nhớ: chỉ **duy nhất** `src/agents/policy.py` được phép gán mức an toàn.
> Router không được, LLM càng không. Đây là bất biến được ép ở tầng Pydantic — bản nháp
> `CandidateActionPlan` **không hề có** trường `safety_level` để mà điền vào.

### Bước 4: Backend đọc trạng thái hiện tại

Trước khi gửi lệnh, backend cần biết `state_version` hiện tại của xe — số phiên bản trạng thái.
Nó đọc từ **State Cache**, là bản sao trong bộ nhớ của tin `state/snapshot` cuối cùng nghe được.

Giả sử đang là `state_version = 41`.

### Bước 5: Backend dán lệnh lên bảng

`ToolExecutor` dựng một `VehicleCommand` và publish lên `v1/vehicles/vehicle-demo-01/commands/hvac`:

```json
{
  "schema_version": "1.0",
  "command_id": "cmd_01J7X4K2P9...",
  "idempotency_key": "plan_01J...:step_01J...",
  "plan_id": "plan_01J...",
  "step_id": "step_01J...",
  "vehicle_id": "vehicle-demo-01",
  "approval_id": null,
  "expected_state_version": 41,
  "tool": "set_hvac_temperature",
  "args": {"temperature_c": 24},
  "issued_at": "2026-08-12T02:00:11Z"
}
```

Ba trường đáng chú ý:

- **`command_id`** — mã riêng của *lần gửi này*. Dùng để nhận ra tin trả lời là của lệnh nào.
- **`idempotency_key`** = `plan_id:step_id` — mã riêng của *việc cần làm*. Gửi lại 3 lần cùng
  một việc thì key vẫn thế. Đây là thứ chặn "thực thi hai lần".
- **`expected_state_version: 41`** — "tôi ra lệnh này dựa trên hiểu biết rằng xe đang ở
  phiên bản 41". Nếu xe đã sang 42 rồi thì lệnh này dựa trên thông tin cũ và phải bị từ chối.
  Kỹ thuật này gọi là **optimistic concurrency** (khóa lạc quan) — giống hệt cách Git từ chối
  push khi nhánh remote đã đi trước.

Backend cũng **đăng ký chờ trước khi publish**, không phải sau. (Publish trước rồi mới đăng ký
chờ là một lỗi kinh điển: nếu xe ảo trả lời cực nhanh, câu trả lời tới trước khi có ai chờ,
và nó rơi vào hư không.)

Sau khi publish, backend chờ tối đa **3 giây** (`MQTT_COMMAND_TIMEOUT_MS`).

### Bước 6: Xe ảo nhận và kiểm tra

Xe ảo đang subscribe `commands/#` nên nhận được ngay. Nó chạy qua một chuỗi kiểm tra,
**không tin backend đã kiểm rồi**:

| Kiểm | Hỏng thì trả `error_code` |
|---|---|
| JSON có đúng schema không? | `invalid_arguments` |
| Tool này có trong registry không? | `tool_not_allowed` |
| Tool này có đúng thuộc domain của topic không? | `tool_not_allowed` |
| `temperature_c = 24` có nằm trong `16..30` không? | `invalid_arguments` |
| `expected_state_version = 41` có khớp version hiện tại không? | `stale_state` |
| Có vi phạm bất biến an toàn không (mở cửa khi xe đang chạy)? | `unsafe_vehicle_state` |
| Đã thấy `command_id` này rồi chưa? | → trả nguyên kết quả cũ, **không** làm lại |

Dòng cuối cùng là chỗ QoS 1 trở nên an toàn: MQTT có thể giao tin **hai lần**, nhưng xe ảo
nhớ kết quả theo `command_id` nên lần thứ hai không sinh thay đổi thứ hai.

### Bước 7: Xe ảo đổi trạng thái

Qua hết kiểm tra → đặt `hvac.temperature_c = 24`, và **tăng `state_version` lên đúng 1** (41 → 42).

Ba trường hợp **không** tăng version:
- Lệnh bị từ chối.
- Lệnh hợp lệ nhưng không đổi gì (đặt 24 khi đang là 24).
- Lệnh trùng lặp đã xử lý rồi.

### Bước 8: Xe ảo dán ba tờ giấy

```
① events/command      → CommandEvent: "xong rồi, đây là chi tiết"   (retain=false)
② state/hvac          → DomainState:  "hvac giờ là ..."             (retain=true)
③ state/snapshot      → toàn cảnh 9 domain, version 42              (retain=true)
```

Tờ ① trông thế này:

```json
{
  "event_id": "evt_01J...",
  "command_id": "cmd_01J7X4K2P9...",
  "idempotency_key": "plan_01J...:step_01J...",
  "phase": "completed",
  "status": "completed",
  "expected_state_version": 41,
  "observed_state_version": 42,
  "before": {"temperature_c": 27, "state_version": 41},
  "after":  {"temperature_c": 24, "state_version": 42},
  "error_code": null,
  "latency_ms": 38,
  "emitted_at": "2026-08-12T02:00:11Z"
}
```

Chú ý `before` và `after`. Đây chính là **bằng chứng quan sát được** mà lý do ② ở mục 2 nói tới.
Backend không phải tin lời, nó có số liệu.

### Bước 9: Backend nhận sự kiện và ghép lại

`ToolExecutor` thấy `command_id` khớp với cái nó đang chờ → đánh thức chỗ chờ → dựng `ToolResult`,
thêm vào `attempt_count` (số lần đã thử — thông tin này **chỉ backend biết**, xe ảo không bao giờ biết).

Song song, `VehicleStateCache` nhận `state/snapshot` và cập nhật bản sao trong bộ nhớ lên version 42.

### Bước 10: Trả lời người dùng

Agent chạy tiếp qua node `compose`, sinh câu trả lời, đẩy qua WebSocket `/ws/ivi` xuống màn hình.
Frontend nhận sự kiện `tool.result` → gọi lại `GET /api/v1/vehicle/state` → thấy 24 độ → vẽ lại.

### Toàn cảnh 10 bước

```
người dùng nói
      │
      ▼ STT
"bật điều hòa 24 độ"
      │
      ▼ router (luật tất định)
CandidateActionPlan {set_hvac_temperature, 24}     ← chưa có mức an toàn
      │
      ▼ policy  ← NƠI DUY NHẤT gán mức an toàn
ActionPlan {..., safety_level: S1}
      │
      ▼ đọc State Cache → version hiện tại = 41
      ▼ ToolExecutor publish
╔═══════════════════════════════════════════════════════╗
║  MQTT: commands/hvac   QoS 1, retain=false            ║
╚═══════════════════════════════════════════════════════╝
      │
      ▼ xe ảo: schema → registry → dải giá trị → version → an toàn → trùng lặp
      ▼ đổi state, version 41 → 42
      ▼ xe ảo publish 3 tin
╔═══════════════════════════════════════════════════════╗
║  events/command  (retain=false)  ─┐                   ║
║  state/hvac      (retain=true)    ├─ về backend       ║
║  state/snapshot  (retain=true)   ─┘                   ║
╚═══════════════════════════════════════════════════════╝
      │
      ▼ ToolExecutor ghép theo command_id → ToolResult
      ▼ StateCache cập nhật lên v42
      ▼ compose → WebSocket /ws/ivi
màn hình hiển thị 24°C
```

---

## 6. Người dùng **hỏi** thì dữ liệu đến từ đâu?

Mục 5 là luồng **ra lệnh**. Nhưng phần lớn câu người dùng nói lại là câu **hỏi** — và câu hỏi
đi một con đường hoàn toàn khác, phần lớn **không chạm MQTT một tí nào**. Đây là chỗ hay bị
hiểu sai nhất trong toàn hệ thống.

### 6.1 Hệ thống có đúng hai nguồn dữ liệu (và không có nguồn thứ ba)

| Nguồn | Là cái gì | Nói được điều gì | Đường đi |
|---|---|---|---|
| **A. Trạng thái xe** | State Cache trong RAM backend, đồng bộ từ xe ảo qua MQTT | *Chiếc xe này, ngay lúc này*: đang mấy độ, cửa đóng chưa, tốc độ bao nhiêu | MQTT `state/snapshot` → cache → `GET /vehicle/state` |
| **B. Sổ tay VF9** | Chỉ mục FAISS dựng sẵn từ file PDF sổ tay, nằm trên đĩa | *Dòng xe VF9 nói chung*: đèn này nghĩa là gì, quy trình sạc ra sao, thông số chuẩn bao nhiêu | Câu hỏi → embed → FAISS → trích nguyên văn |

<!-- -->

| Không phải nguồn | Vì sao |
|---|---|
| Internet / API bên ngoài | ADR-001: **không có network lúc runtime**. Không cloud call, không tự tải model |
| Kiến thức sẵn có của LLM | `slm_enabled` mặc định `False`. Kể cả khi bật, SLM chỉ viết **câu dẫn**, không mang dữ kiện (ADR-015) |
| POI / bản đồ | `search_nearby_poi` mới chỉ là một dòng trong registry (`tool_registry.py:115`) — không có executor, không có luật router nào sinh ra nó |

**Điều này quan trọng vì:** nếu một câu trả lời không truy được về A hoặc B, thì hệ thống đang
bịa. Toàn bộ thiết kế của mục này là để chuyện đó không xảy ra được.

### 6.2 Nguồn A — trạng thái xe: `GET /api/v1/vehicle/state`

Ngắn, nhưng có một chi tiết dễ hiểu sai.

```
Frontend gọi GET /api/v1/vehicle/state
      │
      ▼
Backend KHÔNG hỏi xe ảo. Nó đọc State Cache trong bộ nhớ của chính nó.
      │
      ▼ nhưng trước khi trả, nó kiểm tra "cache này còn đáng tin không?"
      │
      ├─ broker không nối được?     → 503, reason: broker_unreachable
      ├─ chưa từng nhận snapshot?   → 503, reason: no_snapshot_yet
      ├─ chưa từng nhận health?     → 503, reason: no_health
      ├─ xe ảo báo offline?         → 503, reason: offline
      ├─ >15s không thấy heartbeat? → 503, reason: heartbeat_stale
      └─ ổn hết                     → 200, trả nguyên snapshot
```

**Vì sao 503 chứ không phải 200 kèm cờ "dữ liệu cũ"?** ADR-013 trả lời thẳng:

> Hợp đồng nói đây là state **authoritative** (có thẩm quyền). Dữ liệu của một simulator đã
> chết thì không còn authoritative. Trả 200 lúc đó là **nói dối một cách im lặng**.

**Backend không được sửa gì trên đường ra.** Bỏ trường `schema_version` đi thì tin `state/snapshot`
trên dây phải **bằng đúng** phần `data.vehicle_state` mà API trả về. Không đổi tên trường,
không tính toán lại, không suy diễn. Lệch nhau là bug.

> Câu hỏi hay gặp: *"Cache có bị cũ không?"* — Cổng đo tuổi của **heartbeat**, không đo tuổi
> của **state**. Có chủ đích. State là event-driven: "lâu rồi không có snapshot mới" nghĩa là
> "không có gì thay đổi", chứ không phải "dữ liệu đã hỏng". Xe đứng yên trong garage 2 tiếng
> thì state 2 tiếng trước vẫn đúng tuyệt đối. Cái cần kiểm là *người phát tin còn sống không*
> — đó là việc của heartbeat.

**Ai gọi API này?** Chủ yếu là **frontend**, để vẽ màn hình. Nó gọi lúc mở app và gọi lại mỗi
khi nhận sự kiện `tool.result` qua WebSocket. Trạng thái xe tới mắt người dùng bằng **hình ảnh
trên màn hình**, không phải bằng câu trả lời trong hội thoại — xem mục 6.5, đây là điểm bất ngờ nhất.

### 6.3 Nguồn B — sổ tay xe: luồng "Đèn áp suất lốp nghĩa là gì?"

Câu hỏi này là use case P0 số 3. Nó đi như sau:

**Bước 1 — `normalize`.** Node vào của **mọi** lượt. Nó dọn state của lượt trước và
*có* đọc State Cache một phát (`gateway.snapshot()`). Nhưng lưu ý: đây là đọc bộ nhớ trong,
**không publish gì lên MQTT**, và với lượt hỏi thì giá trị đọc được **không ảnh hưởng câu trả lời** —
nó chỉ có tác dụng khi lượt đó hóa ra là lệnh điều khiển.

**Bước 2 — router quyết định.** Đây là chỗ then chốt. Thứ tự sáu bước do ADR-011 chốt:

```
1. Là câu hỏi xin giải thích?   → manual_query → RAG      ← chạy TRƯỚC mọi guard
2. Là câu phủ định nhắm actuator? → denied
3. Đại từ mơ hồ?                 → clarify
4. Sáu matcher lệnh              → control
5. Actuator ngoài registry       → denied
6. MẶC ĐỊNH                      → manual_query → RAG      ← không khớp gì thì tra sổ tay
```

Bước 1 và bước 6 nghĩa là: **câu hỏi không bao giờ đi vào executor**, và **câu lạ mặc định là
tra sổ tay chứ không phải nhún vai**. ADR-011 giải thích vì sao đó là mặc định đúng:

> Mặc định của một trợ lý trong xe khi nghe câu lạ phải là tra sổ tay, không phải nhún vai.

> **Bối cảnh của quyết định này:** trước ADR-011, chỉ **5/60 = 8,3%** câu hỏi sổ tay tới được RAG.
> 49 câu rơi vào `not_control`, 3 câu bị **từ chối** vì regex đọc `có…không?` thành phủ định
> (`"Ghế xe có chức năng massage không?"`), 1 câu bị hiểu nhầm thành lệnh. Trong khi bản thân
> RAG chạy tốt. Nút thắt nằm hoàn toàn ở router — nó chặn 91,7% câu hỏi trước khi chúng tới được
> một hệ thống truy hồi đang hoạt động bình thường. Sau khi đảo mặc định, tỉ lệ tới được RAG là
> **0,9833**.

**Bước 3 — `rag_node` kiểm chỉ mục trước.** Đọc đĩa xem `index.faiss` có tồn tại không.
Không có → trả `index_unavailable` ngay, **không** thử rồi bắt lỗi. Lý do: một checkout chưa dựng
index là chuyện bình thường, không phải sự cố — và người dùng cần biết phải chạy
`prepare_vf9_index.ps1`, chứ không phải hỏi lại câu khác.

**Bước 4 — truy hồi.** Ba chặng:

```
câu hỏi
   │
   ▼ E5 embedder  (intfloat/multilingual-e5-small, 384 chiều)
vector 384 số
   │
   ▼ FAISS tìm 8 đoạn gần nhất  (top_k = 8)
8 ứng viên kèm điểm
   │
   ▼ LỌC HAI TẦNG — phải qua CẢ HAI
   ├─ min_score   ≥ 0.848   (độ tương đồng cosine)
   └─ min_overlap ≥ 0.65    (độ trùng từ vựng với câu hỏi)
   │
   ▼
0 đoạn còn lại → grounded_refusal        n đoạn → grounded_answer
```

Hai tầng lọc là có chủ đích: cosine một mình dễ cho điểm cao với đoạn "nghe giông giống", còn
trùng từ vựng một mình thì bỏ sót cách diễn đạt khác. Ngưỡng `0.848` **không đặt theo cảm tính** —
ADR-003 bắt buộc hiệu chỉnh.

**Bước 5 — sinh citation.** Mỗi đoạn đạt chuẩn thành một `Citation` mang `section`, `page`,
`excerpt` và tên bản sổ tay (`edition` lấy nguyên văn từ `manifest.json`). Citation được ghi vào kho
**ngay tại đây, cùng lượt** — nên id trong câu trả lời và id trong kho không thể lệch nhau.
Có hàm kiểm tra riêng bắt mọi citation phải resolve về một chunk **có thật** và khớp cả `section`
lẫn `page`; sai là hard gate, không phải cảnh báo.

**Bước 6 — `compose` trích nguyên văn.** Đây là chỗ đáng ngạc nhiên nhất, và là một quyết định
có bằng chứng đứng sau:

```
câu dẫn cố định  ("Đây là thông tin tôi tìm được trong sổ tay xe.")
        +
NGUYÊN VĂN đoạn khớp nhất — evidence[0].text, tối đa 1.200 ký tự
        cắt ở ranh giới câu, và nếu cắt thì NÓI RÕ "(Trích chưa hết — xem tiếp trong sổ tay, ...)"
```

Hai chi tiết hay bị làm sai:

- Nguồn trích là **`evidence[0].text`**, KHÔNG phải `citation.excerpt`. Excerpt bị cắt cứng ở
  **300 ký tự**, trong khi **39/40** đoạn thật dài hơn thế. Trích từ excerpt là làm mất đúng thứ
  quan trọng nhất — điều kiện biến thể nằm rải trong đoạn ("bản ECO 8 hướng / bản PLUS 12 hướng",
  "pin SDI 240 KPA / CATL 260 KPA", "nếu được trang bị").
- Trần **1.200 ký tự** bao trọn 34/40 đoạn; 6 đoạn còn lại bị cắt **có báo**. Đây là con số hành vi
  người dùng thấy, không phải hằng số kỹ thuật.

> **Vì sao không để LLM tóm tắt cho gọn?** Đã thử và đã đo. ADR-015 ghi: cho SLM viết lại đoạn sổ tay
> cho **4/40 câu trả lời sai lệch**, tất cả đều do **bỏ mất điều kiện biến thể** — so với **0/40**
> khi trích nguyên văn. Sai kiểu đó là sai *âm thầm*: câu trả lời đọc rất trôi chảy và rất tự tin.
> Nên hệ thống chọn nghe hơi khô nhưng không bịa. Khi `slm_enabled=True`, SLM chỉ được viết **câu dẫn** —
> câu đó **không mang dữ kiện nào**, nên thiếu nó chỉ kém tự nhiên chứ không mất nội dung.

**Bước 7 — người dùng xem nguồn.** Câu trả lời kèm danh sách citation. Bấm vào thì frontend gọi
`GET /api/v1/citations/{citation_id}` — một trong 12 interface P0, giới hạn theo chủ phiên
(403 nếu của người khác, 404 nếu id không tồn tại hoặc đã bị đẩy khỏi kho có trần).

### 6.4 Bốn kết cục có thể của một câu hỏi

| Kết cục | Câu người dùng nghe | Nghĩa thật | Phải làm gì |
|---|---|---|---|
| `grounded_answer` | "Đây là thông tin tôi tìm được trong sổ tay xe." + nguyên văn | Tìm được đoạn đạt cả hai ngưỡng | — |
| `grounded_refusal` | "Tôi không tìm thấy thông tin này trong sổ tay xe." | Đã tra thật, nhưng **không đoạn nào đủ điểm** | Hỏi lại theo cách khác, hoặc chấp nhận sổ tay không có |
| `index_unavailable` | "Tôi chưa tra được sổ tay xe lúc này." | **Chỉ mục chưa được dựng** trên máy này | Chạy `scripts/prepare_vf9_index.ps1` |
| `retrieval_failed` | "Tôi gặp lỗi khi tra sổ tay xe." | Lỗi đọc file / lỗi kỹ thuật | Xem log |

**Hai câu từ chối giữa được tách ra có chủ đích.** "Không tìm thấy trong sổ tay" và "chưa dựng
chỉ mục" nghe na ná nhau nhưng hành động sửa hoàn toàn khác: một cái là hỏi lại, một cái là chạy
lệnh build. Gộp lại là đẩy người dùng đi hỏi lại mãi một hệ thống chưa hề khởi tạo.

> **Từ chối là tính năng, không phải lỗi.** Ví dụ đắt nhất: *"Cách thay dầu động cơ xăng của VF9"*.
> Câu này đi vào RAG (nó là câu hỏi), tra thật, và trả về `grounded_refusal` — **có căn cứ**, vì
> VF9 chạy điện và sổ tay không có nội dung đó. Từ chối kiểu này khác hẳn từ chối vì trùng chuỗi
> từ khóa: một cái là hệ thống đã *tìm* và *không thấy*, cái kia là hệ thống *không thèm tìm*.

### 6.5 Cái bẫy lớn nhất: "Xe đang mấy độ?" **không** đọc trạng thái xe

Đây là điều bất ngờ nhất và cần nói thẳng.

Nguồn A (trạng thái xe qua MQTT) và nguồn B (sổ tay qua RAG) **chưa được nối vào hội thoại như nhau**:

- Nguồn B có đường đi đầy đủ: câu hỏi → router → RAG → câu trả lời.
- Nguồn A **không có** đường đi đó. `get_vehicle_state` chỉ tồn tại như một dòng trong registry
  (`tool_registry.py:113`, S0). **Không luật router nào sinh ra nó.**

Hệ quả cụ thể:

```
"Xe đang bao nhiêu độ?"
      │
      ▼ router: là câu hỏi → manual_query
      ▼ RAG tra SỔ TAY (không phải trạng thái xe)
      ▼ sổ tay không có "nhiệt độ hiện tại của chiếc xe này"
      ▼
"Tôi không tìm thấy thông tin này trong sổ tay xe."
```

Trong khi đúng lúc đó, State Cache **đang giữ** con số 24 °C, và `GET /api/v1/vehicle/state`
trả về nó chính xác.

`docs/coverage_matrix.md` ghi lại đúng nghịch lý này ở nhóm "Trạng thái xe & chẩn đoán":

> Use case P0 số 3 ("đèn áp suất lốp nghĩa là gì?") chạy được nhưng qua **RAG sổ tay** — hệ thống
> *giải thích* được đèn cảnh báo, *đọc* được áp suất lốp thì không.

**Vậy trạng thái xe tới người dùng bằng cách nào?** Bằng **màn hình**: frontend gọi
`GET /api/v1/vehicle/state` và vẽ ra. Nó không đi qua hội thoại. Nếu bạn demo và định hỏi bằng
giọng nói "xe đang mấy độ" thì kịch bản sẽ gãy — hãy chỉ vào màn hình thay vì hỏi.

### 6.6 Bảng tra nhanh: câu này lấy dữ liệu ở đâu?

| Người dùng nói | Router quyết | Nguồn dữ liệu | Chạm MQTT? |
|---|---|---|:-:|
| "Bật điều hòa 24 độ" | `control` → S1 | Xe ảo | ✅ publish lệnh |
| "Mở cửa" (xe đang 60 km/h) | `control` → **S3** | State Cache (để phân loại) | ❌ chặn **trước** khi publish |
| "Mở cửa" (xe đứng yên) | `control` → S2 → HITL | State Cache + xe ảo | ✅ sau khi người dùng đồng ý |
| "Đèn áp suất lốp nghĩa là gì?" | `manual_query` | Sổ tay (FAISS) | ❌ |
| "Chỉnh nhiệt độ thế nào?" | `manual_query` | Sổ tay — hỏi *cách làm*, không phải ra lệnh | ❌ |
| "Ghế xe có chức năng massage không?" | `manual_query` | Sổ tay | ❌ |
| "Mở cửa sổ bên lái 30% được không?" | **`offer`** | Không nguồn nào — chỉ nêu lại việc rồi hỏi | ❌ |
| "Cách thay dầu động cơ xăng của VF9" | `manual_query` | Sổ tay → `grounded_refusal` **có căn cứ** | ❌ |
| "Xe đang bao nhiêu độ?" | `manual_query` | Sổ tay → nhiều khả năng từ chối ⚠️ mục 6.5 | ❌ |
| "Tìm quán cà phê gần đây" | `manual_query` (mặc định) | Sổ tay → từ chối; POI chưa có executor | ❌ |
| "Không phát nhạc" | `denied` | Không nguồn nào | ❌ |
| "Chỉnh cái đó lên" | `clarify` | Không nguồn nào | ❌ |

Đọc cột cuối theo chiều dọc là thấy ngay: **MQTT chỉ được chạm khi thật sự có việc phải làm trên xe.**
Mọi câu hỏi, mọi lời từ chối, mọi lời đề nghị đều dừng lại trước broker.

### 6.7 `offer` — khi câu hỏi trùng một lệnh

Trường hợp riêng đáng nhớ. *"Mở cửa sổ bên lái 30% được không?"* vừa là câu hỏi, vừa khớp một
luật điều khiển. Router không chọn một trong hai — nó tạo disposition thứ ba, **`offer`**:

> *"Tôi có thể mở kính trước bên lái lên 30%. Bạn có muốn tôi thực hiện không?"*

Nêu rõ **đủ tham số** việc sắp làm, rồi hỏi lại. Không chạm executor, không chạm MQTT. Người dùng
quyết ở lượt sau.

Nhờ vậy chỉ số `question_to_control` (câu hỏi bị hiểu nhầm thành lệnh) **bằng 0 về mặt cấu trúc** —
không có đường đi nào để nó khác 0, chứ không phải nhờ tinh chỉnh cho về 0.

### 6.8 Chỉ mục sổ tay đến từ đâu

Nó **không** được tải về lúc chạy. Nó là dữ liệu offline dựng sẵn, nằm trên đĩa:

```
data/manuals/vf9_2026_vi/     ← file sổ tay gốc
        │
        ▼ python -m src.rag.cli ingest
data/rag/vf9_2026_vi/
        ├── index.faiss       ← rag_node kiểm file NÀY để biết index đã dựng chưa
        ├── chunk store
        └── manifest.json
```

`manifest.json` của bản đang có trong repo:

| Trường | Giá trị | Nghĩa |
|---|---|---|
| `edition` | `VF9_23-25_VN_VI_2.4 [New UI]` | Bản sổ tay — mọi citation khai đúng chuỗi này |
| `documents` | 58 | Số tài liệu nguồn |
| `chunks` | 482 | Số đoạn đã cắt |
| `vectors` | 536 | Số vector trong FAISS |
| `embedding_version` | `intfloat/multilingual-e5-small@384` | Model nhúng, 384 chiều |
| `index_checksum` | `sha256:6b0c1c…` | Đổi dữ liệu là đổi checksum |
| `page_exact_rate` | 1.0 | 100% citation có số trang **chính xác**, không suy đoán |

Bốn lệnh làm việc với chỉ mục:

```powershell
.\.venv311\Scripts\python.exe -m src.rag.cli ingest      # dựng chunk store + FAISS
.\.venv311\Scripts\python.exe -m src.rag.cli verify      # in manifest, kiểm quality gate
.\.venv311\Scripts\python.exe -m src.rag.cli query "..."  # thử một câu
.\.venv311\Scripts\python.exe -m src.rag.cli eval        # chạy bộ đánh giá
```

> **Lưu ý khi chạy test:** test đầu tiên chạm tới tra sổ tay phải trả **~32 giây** để nạp E5 embedder
> (có `@lru_cache` nên chỉ tốn một lần). Chạy riêng một test như vậy trông chậm đáng sợ, trong khi
> cả bộ suite thì không.

### 6.9 Con số chất lượng — và giới hạn của chúng

Run `eval/results/rag/20260807T102012Z/` trên 40 câu positive + 20 câu negative:

| Chỉ số | Giá trị | Nghĩa |
|---|---|---|
| `recall_at_k` | 1.00 | Đoạn đúng luôn nằm trong top-k |
| `grounded_rate` | 1.00 | Mọi câu trả lời đều có evidence đứng sau |
| `citation_validity` | 1.00 | Mọi citation resolve về chunk có thật, đúng section/page |
| `hallucination_rate` | 0.05 | Tỉ lệ bịa |

**Ba điều phải nói kèm mỗi khi trích những con số này:**

1. **Không con số nào đi qua ASR.** Cả hai bộ dataset đều là văn bản gõ sẵn, nên chúng
   **không phản ánh lỗi nhận dạng giọng nói**. Người dùng thật thì nói, không gõ.
2. **Hai dataset không ngang giá trị.** `eval/datasets/agent/v3` do chính người viết router soạn,
   nên `intent_accuracy = 1.0000` của nó chỉ là **chuông báo hồi quy**, không nói gì về khả năng
   tổng quát hóa. Con số **0,9833** (tỉ lệ câu hỏi tới được RAG) đo trên `eval/datasets/manual/v1` —
   do workstream RAG soạn cho mục đích khác — mới là con số đáng tin hơn.
3. **Không được trình bày như "độ chính xác" với người dùng cuối.** Mọi con số phải truy được về
   một run id cụ thể, và phải nói rõ nó đo cái gì.

### 6.10 Vì sao hai nguồn không được trộn vào nhau

Nguyên tắc cuối, và nó giải thích phần lớn những gì trông "cứng nhắc" ở trên:

| | Sổ tay (B) | Trạng thái xe (A) |
|---|---|---|
| Nói về | **Dòng xe VF9** nói chung | **Chiếc xe này, giây này** |
| Đúng trong bao lâu | Vô hạn (tới khi ra bản sổ tay mới) | Có thể sai ngay giây sau |
| Kiểm chứng bằng | Số trang trong sổ tay | `state_version` từ xe ảo |

Chỗ nguy hiểm là khi trộn hai cái. Ví dụ:

> ✅ *"Sổ tay nói áp suất lốp tiêu chuẩn là 240 KPA với pin SDI."* — nguồn B, trích được, kiểm được.
>
> ❌ *"Lốp xe bạn đang ở 240 KPA nên vẫn ổn."* — câu này cần nguồn A, mà hệ thống **không có** cảm
> biến áp suất lốp trong 9 domain. Nói ra là bịa, và là kiểu bịa nguy hiểm nhất vì nghe rất giống
> một câu đúng.

Đó chính là lý do composer **chỉ trích nguyên văn** và không suy diễn, không nối câu, không kết luận
hộ. Một hệ thống trong xe mà đoán về an toàn thì thà im lặng.

---

## 7. Những quyết định nhỏ mà cứu mạng

Đây là phần đáng đọc nhất nếu bạn muốn hiểu *vì sao code trông như vậy*. Mỗi mục dưới đây là
một chỗ mà lựa chọn "hiển nhiên" là lựa chọn sai.

### 7.1 `commands/` phải `retain = false`

Nếu để `retain = true`: mỗi lần xe ảo khởi động lại, nó nhận lại **lệnh cuối cùng** còn dán
trên bảng và thực thi lần nữa.

Nghĩa là: **xe tự mở cửa sau khi restart broker.**

Đây không phải chi tiết vặt, đây là lỗi an toàn. Nguyên tắc chung: *lệnh là sự kiện xảy ra
một lần; retain chỉ dành cho trạng thái.*

### 7.2 `state/` và `health` phải `retain = true`

Ngược lại hoàn toàn. Nhờ retain, một subscriber nối vào lúc 3 giờ sáng vẫn đọc được ngay trạng
thái hiện tại, không phải chờ tới khi có ai đó bấm nút. Đây cũng là cách backend khôi phục cache
sau khi restart mà **không cần hỏi lại** xe ảo.

### 7.3 QoS 1, không phải QoS 2

QoS 2 nghe "an toàn hơn" nhưng nó chỉ đảm bảo exactly-once **giữa hai đầu MQTT**. Nó không
đảm bảo tầng ứng dụng phía sau xử lý đúng một lần — bạn **vẫn phải** tự dedupe. Đổi lại là
4 lượt bắt tay cho mỗi tin thay vì 1.

Vì đằng nào cũng phải dedupe bằng `command_id`, QoS 2 chỉ tốn thêm mà không mua được gì. Không dùng.

### 7.4 Birth + LWT, phải có cả hai

Chỉ khai LWT là chưa đủ. Kịch bản: xe ảo chết → broker dán `online: false` (retain) → xe ảo hồi
phục và chạy lại. Nếu nó không **tự dán Birth** ngay, thì tờ `online: false` vẫn nằm trên bảng
cho tới nhịp heartbeat sau — trong khoảng đó cả hệ thống tưởng xe đã chết trong khi nó đang chạy.

Khi tắt **có trật tự**, xe ảo còn publish `online: false, reason: "shutdown"` **trước khi**
ngắt kết nối, để phân biệt với chết đột ngột (`reason: "lwt"`). Hai lý do khác nhau, người vận
hành xử lý khác nhau.

### 7.5 `expected_state_version` — lớp bảo vệ thật sự

Đây là cơ chế an toàn cốt lõi, và nó dễ bị hiểu nhầm là "chi tiết kỹ thuật".

Tình huống: người dùng phê duyệt lệnh "mở cửa" lúc xe đang đứng yên. Trong 2 giây chờ họ bấm
"Đồng ý", xe bắt đầu chạy. Nếu lệnh cứ thế đi tiếp thì cửa mở khi xe đang chạy.

`expected_state_version` chặn đúng chuyện đó: lệnh mang version 41, xe giờ ở version 45,
xe ảo trả `stale_state` và **không làm gì cả**. Fail-closed.

Chuỗi lệnh nhiều bước dùng **rolling version**: bước sau lấy `observed_state_version` từ
`ToolResult` của bước trước — lấy từ chính sự kiện xe ảo gửi về, **không** đọc lại cache
(đọc lại cache sẽ có race).

> Có một hàm tên `_await_floor()` trong `MqttVehicleGateway` chờ cache bắt kịp version mới nhất
> trước khi đọc. Docstring của nó nói rất rõ: **đây chỉ là tối ưu độ trễ, KHÔNG phải cơ chế an toàn.**
> Hết thời gian chờ thì nó đi tiếp chứ không báo lỗi, vì lớp chặn thật vẫn là `stale_state` ở xe ảo.
> Đừng bao giờ tăng thời gian chờ đó rồi coi nó là bảo đảm tính đúng đắn.

### 7.6 `accepted` khác `completed`

`phase` có ba giá trị: `accepted | rejected | completed`.

Ở P0 xe ảo áp dụng lệnh **tức thì** nên hai cái xảy ra gần như cùng lúc, và xe ảo chỉ phát
`completed`. Nhưng hai khái niệm **không được gộp lại**, vì trong xe thật chúng khác nhau rất xa:

> Đặt nhiệt độ đích 24 °C **không có nghĩa** cabin đã 24 °C. Giá trị thực hội tụ dần trong vài phút.

Android Automotive tách rất rõ chuyện này (`setPropertiesAsync` chỉ báo thành công khi *cả*
lệnh xuống được bus *và* giá trị thực đã đạt đích). COVESA VSS tách hẳn `target_value` và
`current_value`. Giữ hai `phase` từ bây giờ nghĩa là ngày nào mô phỏng độ trễ hội tụ, hợp đồng
không phải sửa.

Code hiện tại **cố ý bỏ qua** sự kiện `phase: accepted` và chờ tiếp tới `completed`/`rejected`
— vì `accepted` mới là "đã nhận", chưa phải "đã đạt".

### 7.7 Xe ảo restart → backend phải quên state cũ

Lỗi này có thật, tìm ra bằng tầng test L3 (issue #49), và nó rất khó thấy:

1. Xe ảo chạy một lúc, version leo lên 87.
2. Xe ảo restart. Bộ đếm của nó **về lại 1**.
3. Backend có một guard hợp lý: "bỏ qua snapshot có version thấp hơn version đang giữ"
   (để tin tới trễ không làm lùi trạng thái).
4. Guard đó giờ chặn **mọi** snapshot mới (1 < 87, 2 < 87, ...).
5. Backend vĩnh viễn kẹt ở state của lần chạy trước. Mọi lệnh gửi đi đều `stale_state`.
6. **Và `/healthz` vẫn xanh.** Heartbeat vẫn tươi, xe ảo vẫn sống thật. Không có gì báo động.

Cách sửa: backend theo dõi chuyển tiếp `offline → online` trên topic `health`. Thấy chuyển tiếp
đó là biết "đây là một lần chạy MỚI" → **vứt state cũ đi**, để `GET /vehicle/state` trả 503
`no_snapshot_yet` cho tới khi có snapshot mới. Fail-closed.

> Một cái bẫy đã bị dẫm phải rồi ghi lại trong code: **không** được dùng `health.state_version`
> để suy ra restart, dù nó có sẵn và trông rất tiện. Vì `health` là retained và chỉ publish mỗi
> nhịp heartbeat, nên số nó mang **luôn trễ** so với state thật. Một subscriber nối muộn nhận
> snapshot v2 rồi health v1 là chuyện **bình thường**, không phải restart — bản đầu tiên của
> hàm này kết luận nhầm đúng như vậy và vứt mất state đúng.

### 7.8 Broker chết thì **không** được lặng lẽ chuyển sang xe in-process

Có một cám dỗ rất lớn: khi `MQTT_ENABLED=true` mà kết nối hỏng, sao không tự động rơi về
simulator chạy trong cùng tiến trình cho demo đỡ gãy?

ADR-013 cấm, và lý do đắt giá:

> Rơi về xe in-process lúc đó là **thay thầm một chiếc xe khác**. API trả 200 với trạng thái
> của một chiếc xe không ai điều khiển, và không ai biết.

Xe in-process **chỉ** được dùng khi `MQTT_ENABLED=false` — tức lựa chọn tường minh của người
vận hành, không phải hậu quả của một sự cố.

### 7.9 Hai danh tính, hai bộ quyền

Broker bật xác thực (`MQTT_ALLOW_ANONYMOUS=false`) với hai tài khoản tách biệt:

```
user vivi-backend
  ghi   v1/vehicles/+/commands/#     ← chỉ được ra lệnh
  đọc   v1/vehicles/+/events/#
  đọc   v1/vehicles/+/state/#
  đọc   v1/vehicles/+/health

user vehicle-simulator
  đọc   v1/vehicles/+/commands/#     ← chỉ được nhận lệnh
  ghi   v1/vehicles/+/events/#
  ghi   v1/vehicles/+/state/#
  ghi   v1/vehicles/+/health
```

Backend **không thể** publish trạng thái. Nghĩa là backend không thể nói dối về tình trạng xe,
kể cả khi code backend có bug. Xe ảo **không thể** tự ra lệnh cho mình.

Ranh giới này còn có mặt trong thiết kế: backend không đặt được tốc độ xe khi bật MQTT, vì
`motion` là read-only và không có topic lệnh. Muốn đổi tốc độ để thử phân loại S2/S3, bạn gõ
vào **console của tiến trình xe ảo**:

```
speed 45        # 45 km/h, tự chuyển số D
speed 45 D
gear P
stop
state
```

Xe tự đặt tốc độ của chính nó rồi publish `state/motion` như mọi thay đổi khác — publisher vẫn
là danh tính simulator nên không vi phạm ACL. ADR-013 ghi hẳn một dòng in đậm:
*"**Tuyệt đối không** shadow-publish `state/motion` từ backend, kể cả 'tạm cho demo'."*

### 7.10 Healthcheck chỉ được chứng minh "kết nối + xác thực"

Healthcheck của broker trong Docker Compose dùng `mosquitto_sub -E` — thoát ngay khi broker đã
xác nhận subscribe, **không chờ tin nào tới**.

Bản trước đó chờ nhận một tin trong 3 giây, và nó **không bao giờ đạt**, vì lý do vòng tròn rất đẹp:

- Không topic nào mà backend được đọc có traffic đảm bảo lúc broker vừa lên.
- `state/*` và `health` chỉ có sau khi **xe ảo** chạy.
- Mà xe ảo lại `depends_on: mqtt healthy`.

→ Broker mãi mãi `unhealthy` → không service nào khởi động được. Cả hai nửa của bài học này
được khóa lại bằng test `tests/test_vehicle/test_compose_healthcheck.py`.

---

## 8. Khi có chuyện: bảng mã lỗi

### `error_code` trong `CommandEvent`

| Mã | Khi nào | Retry được không |
|---|---|---|
| `stale_state` | `expected_state_version` không khớp | **Không** |
| `unsafe_vehicle_state` | Vi phạm bất biến (mở cửa khi xe chạy) | **Không** |
| `invalid_arguments` | `args` sai schema hoặc ngoài dải | **Không** |
| `tool_not_allowed` | Tool không có trong registry | **Không** |
| `internal_error` | Lỗi không lường trước | **Không** |

**Không mã nào trong bảng này được retry.** Chúng đều là lỗi *xác định* — thử lại y hệt thì
kết quả y hệt.

Backend chỉ được retry **đúng một lần**, và chỉ khi *lỗi transport tạm thời*: gửi đi mà không
nhận được sự kiện nào trong 3 giây. Cả hai lần thử dùng **cùng** `command_id` và `idempotency_key`,
nên nếu lần đầu thực ra đã tới nơi thì xe ảo dedupe và trả lại kết quả cũ.

Hết retry → ghi đúng một kết quả `failed` với `error_code: "mqtt_unavailable"` rồi dừng.
Muốn thử lại thật thì phải lập kế hoạch mới với `plan_id`/`step_id` mới.

### `reason` trong lỗi 503 của `GET /vehicle/state`

| `reason` | Nghĩa | Ai sửa |
|---|---|---|
| `broker_unreachable` | Backend không nối được broker | DevOps — broker chưa chạy? sai cổng? sai mật khẩu? |
| `no_snapshot_yet` | Nối được broker nhưng chưa nghe được snapshot nào | Chờ vài giây, hoặc xe ảo chưa chạy |
| `no_health` | Chưa nhận được tin `health` nào | Xe ảo chưa chạy |
| `offline` | Xe ảo báo mình offline (LWT hoặc shutdown) | Xem log tiến trình xe ảo |
| `heartbeat_stale` | >15 giây không thấy heartbeat mới | Xe ảo treo hoặc mạng đứt |

Hai nhóm đầu và cuối tách nhau **có chủ đích**: `broker_unreachable` là sửa hạ tầng,
mấy cái còn lại là xem xe ảo. Với người trực hệ thống, đó là hai việc hoàn toàn khác nhau.

---

## 9. Bốn tầng test, và điểm mù của từng tầng

Đây là chỗ dự án làm nghiêm túc hơn mức thường thấy: mỗi tầng test tồn tại **để bù điểm mù của
tầng dưới**, và điều đó được ghi thành dữ liệu máy đọc được (`_BLIND_SPOTS` trong
`scripts/report_mqtt_e2e.py`), không chỉ là văn xuôi.

| Tầng | Chạy cái gì | **Không** chứng minh được gì |
|---|---|---|
| **L0** unit | Hàm thuần túy | Không nói gì về truyền tin |
| **L1** in-memory | `InMemoryBroker` — broker giả trong RAM, tất định hoàn toàn | Trùng tin QoS 1, retain, ACL, LWT, reconnect |
| **L2** contract | Mosquitto **thật**, nhưng chỉ một tiến trình pytest | Chưa có HTTP/WS thật; backend và xe ảo chưa tách tiến trình |
| **L3** two-process | `python -m src.serve` + `python -m src.vehicle_sim` là **tiến trình thật**, socket thật | Docker image, topology Compose, đứt mạng, nhiều xe |

Ví dụ cụ thể về giá trị của việc phân tầng: bug ở mục **7.7** (xe ảo restart) **không thể** bị
bắt bởi L0, L1 hay L2 — vì cả ba đều không có "một tiến trình chết và khởi động lại thật".
Chỉ L3 có.

Mặc định `pytest` bỏ qua L2 và L3 (chúng cần broker thật). Bật bằng biến môi trường:

```powershell
$env:MQTT_CONTRACT_TESTS="1"   # bật L2
$env:MQTT_L3_TESTS="1"         # bật L3
```

> **Sản phẩm bàn giao là thư mục kết quả chạy, không phải file test.**
> `scripts/report_mqtt_e2e.py --with-contract --with-l3` sinh ra một thư mục
> `eval/results/mqtt-e2e/<run-id>/` bất biến, có `manifest.json` + `metrics.json`.
> Mọi con số đưa vào báo cáo phải truy được về một run id.

---

## 10. Tự chạy thử trong 5 phút

```powershell
# 1. Sinh mật khẩu cho hai danh tính (chỉ làm MỘT lần)
#    Nó in ra 4 dòng — chép vào .env. File config/mosquitto/passwd
#    KHÔNG BAO GIỜ được commit.
pwsh scripts/bootstrap_mqtt_secrets.ps1

# 2. Bật broker + xe ảo (--wait để đợi healthcheck xanh)
docker compose up -d --wait mqtt vehicle-simulator

# 3. Nghiệm thu end-to-end
.\.venv311\Scripts\python.exe scripts\smoke_mqtt.py

# 4. Kiểm 6 JSON Schema
.\.venv311\Scripts\python.exe scripts\validate_mqtt_schemas.py
```

**Xem tận mắt mọi tin đang chạy qua bảng tin** — lệnh hữu ích nhất khi debug:

```powershell
docker exec p-192-mqtt-1 mosquitto_sub -h localhost -p 1883 `
  -u vivi-backend -P "<mật khẩu>" -t 'v1/vehicles/#' -v
```

Chạy lệnh này ở một cửa sổ, rồi ra lệnh giọng nói ở cửa sổ khác — bạn sẽ thấy `commands/hvac`
bay qua, rồi `events/command`, rồi `state/hvac`, rồi `state/snapshot`. Đây là cách nhanh nhất
để hiểu mục 5 bằng mắt thay vì bằng chữ.

**Chạy tay từng tiến trình** (mỗi cái một cửa sổ):

```powershell
.\.venv311\Scripts\python.exe -m src.vehicle_sim   # xe ảo — gõ `speed 45`, `stop`, `state` ở đây
.\.venv311\Scripts\python.exe -m src.serve         # backend
```

### Ba cái bẫy môi trường

1. **Trên Windows phải chạy `python -m src.serve`, KHÔNG phải `uvicorn src.main:app`.**
   Uvicorn chọn `ProactorEventLoop` trên Windows, mà loop đó không có `add_reader`/`remove_writer`
   — hai thứ paho-mqtt cần. Mọi kết nối MQTT sẽ nổ `NotImplementedError`.
   Trong container Linux thì `uvicorn` bình thường.

2. **Máy đã có broker khác giữ cổng 1883?** (RabbitMQ bật plugin MQTT, EMQX...) Đặt
   `MQTT_HOST_PORT=1884` và `MQTT_URL=mqtt://localhost:1884` trong `.env`. Chỉ cổng loopback
   phía host đổi; trong docker network các service vẫn nối `mqtt:1883`.

3. **Chạy test root thì phải đặt `MQTT_ENABLED=false`.** Ở mặc định `true`, mỗi
   `TestClient(app)` chạy lifespan và **đợi 10 giây** một broker không tồn tại.

---

## 11. Cái gì chưa có (nói thẳng)

Phần này để bạn không tưởng nhầm là mọi thứ đã xong.

- **`doors` chưa có trường `locked`.** Cả ba API xe hơi thực tế được khảo sát (AutoAPI, VSS,
  Smartcar) đều tách "khóa" và "mở" thành hai khái niệm độc lập. Schema P0 chỉ có `open`/`closed`,
  nên **không diễn đạt được** tình huống "xe đang khóa, lệnh mở cửa lẽ ra phải fail".
  Hoãn có chủ ý — P0 không có tool khóa/mở khóa nên `locked` sẽ là hằng số không ai đọc.
  **Cảnh báo cho FE:** khi P1 thêm `set_door_lock`, mỗi cửa đổi từ **string** sang **object**
  (`"closed"` → `{"state": "closed", "locked": true}`). Đây là **breaking change**.

- **`hvac.fan_level` là read-only.** Có trong state, không có tool nào đổi được. Nó sẽ đứng yên
  ở giá trị khởi tạo mãi mãi. Ghi rõ trong spec, không phải quên.

- **Không hỏi được trạng thái xe bằng giọng nói.** `get_vehicle_state` có trong registry nhưng
  không luật router nào sinh ra nó, nên câu hỏi về trạng thái hiện tại rơi vào RAG sổ tay và bị
  từ chối. Chi tiết ở mục 6.5 — đây là khoảng trống rõ nhất giữa hai nguồn dữ liệu.

- **`search_nearby_poi` chưa chạy.** Chỉ là một dòng trong registry: không executor, không luật
  router, không test. Use case P0 "tìm quán cà phê → chỉnh điều hòa → dẫn đường" vì thế **không
  chạy được**; `set_navigation` cũng chỉ tới ba destination id gắn cứng.

- **`GET /vehicle/state` chưa có auth.** `api_spec.md` yêu cầu giới hạn cho Driver/Engineer,
  code hiện không có dependency nào. Nằm trong danh sách 4 lỗ hổng auth ở
  `docs/backend_flow_audit_2026-08-12.md`.

- **Chưa có gì được lưu xuống đĩa.** Approval, session, token đều nằm trong RAM.
  Restart backend là mất hết approval đang chờ.

- **Chưa đo latency end-to-end.** Mục tiêu p50/p95 chưa có bằng chứng. Con số 5,6 s trong các
  báo cáo cũ là của SPIKE-001, một pipeline khác — **không được tái sử dụng**.

- **`observed_at` chỉ có độ phân giải 1 giây** (`%Y-%m-%dT%H:%M:%SZ`). Không dùng trường này
  để đo độ trễ.

Ngược lại, một việc từng ghi là "còn dang dở" trong ADR-013 thì **nay đã xong**: agent graph
đã đi qua `VehicleGateway` (`src/agents/nodes/execute.py`, `normalize.py`, `approval.py`),
và `src/agents/vehicle.py` — bản simulator thứ hai song song — đã bị xóa. Giờ chỉ còn **một**
máy trạng thái duy nhất.

---

## 12. Từ điển thuật ngữ

| Từ | Nghĩa trong dự án này |
|---|---|
| **Broker** | Mosquitto — cái "bảng tin" trung gian. Chạy trong Docker |
| **Topic** | Tên ngăn trên bảng, phân cấp bằng `/` |
| **Publish / Subscribe** | Dán tin / đăng ký theo dõi một ngăn |
| **QoS 1** | At-least-once — có thể tới 2 lần, nên phải tự dedupe |
| **Retain** | Tin ở lại trên bảng cho người tới sau đọc được |
| **LWT** | "Di chúc" — broker tự dán hộ khi client chết đột ngột |
| **Birth** | "Tôi sống rồi" — client tự dán ngay sau khi kết nối |
| **Heartbeat** | Nhịp báo sống, 5 giây/lần. Quá 15 s không thấy → coi là chết |
| **Digital twin** | Xe ảo — bản sao phần mềm của chiếc xe, chạy tiến trình riêng |
| **`state_version`** | Số phiên bản trạng thái, tăng đúng 1 mỗi lần đổi thật |
| **Optimistic concurrency** | Gửi kèm version mình biết; lệch thì bị từ chối (`stale_state`) |
| **Idempotency key** | `plan_id:step_id` — mã của *việc cần làm*, để gửi lại không làm hai lần |
| **`command_id`** | Mã của *lần gửi này*, để ghép tin trả lời với lệnh |
| **ACL** | Bảng phân quyền của broker: ai được ghi topic nào |
| **S0–S3** | Bốn mức an toàn. S0 chỉ đọc, S1 chạy luôn, S2 phải hỏi người, S3 chặn thẳng |
| **HITL** | Human-in-the-loop — bắt buộc có người phê duyệt |
| **Domain** | Một trong 9 nhóm chức năng: `motion hvac windows doors media navigation seat lights trunk` |
| **Fail-closed** | Không chắc thì **không làm**, thay vì đoán rồi làm |
| **RAG** | Retrieval-Augmented Generation — tra tài liệu thật rồi trả lời dựa trên đó, không trả lời từ trí nhớ |
| **FAISS** | Thư viện tìm vector gần nhất. Ở đây là chỉ mục sổ tay VF9 dựng sẵn trên đĩa |
| **Embedding** | Biến câu chữ thành vector số để so độ giống nhau. Model dùng: `multilingual-e5-small`, 384 chiều |
| **Chunk** | Một đoạn sổ tay đã cắt sẵn. Repo hiện có 482 chunk từ 58 tài liệu |
| **Citation** | Trích dẫn: chunk nào, mục nào, trang bao nhiêu, bản sổ tay nào |
| **`grounded_answer`** | Trả lời **có** đoạn sổ tay đứng sau, trích nguyên văn |
| **`grounded_refusal`** | Đã tra thật nhưng không đoạn nào đủ điểm → từ chối **có căn cứ** |
| **`manual_query`** | Ý định "tra sổ tay" — mặc định của mọi câu router không nhận ra là lệnh |
| **`offer`** | Câu hỏi trùng một lệnh: nêu lại việc sẽ làm rồi hỏi lại, **không** làm |

---

## 13. Đọc tiếp ở đâu

| Cần gì | Đọc file nào |
|---|---|
| Hợp đồng transport đầy đủ: topic, QoS, payload, ACL | [`docs/mqtt_spec.md`](mqtt_spec.md) |
| Vì sao chọn MQTT (quyết định kiến trúc) | [`docs/adr/ADR-004`](adr/ADR-004-mqtt-vehicle-simulator.md) |
| Vì sao chỉ một nguồn state, và cái giá phải trả | [`docs/adr/ADR-013`](adr/ADR-013-single-vehicle-state-source.md) |
| Phân loại an toàn S0–S3, luồng HITL | [`docs/safety_and_hitl.md`](safety_and_hitl.md) |
| Hợp đồng REST/WebSocket | [`docs/api_spec.md`](api_spec.md) |
| Biến môi trường, ACL, readiness | [`docs/devops.md`](devops.md) |
| Hệ thống thực sự điều khiển được những gì | [`docs/coverage_matrix.md`](coverage_matrix.md) |
| JSON Schema máy đọc được | [`schemas/mqtt/`](../schemas/mqtt/) |
| Vì sao câu lạ mặc định đi tra sổ tay | [`docs/adr/ADR-011`](adr/ADR-011-default-route-to-manual-lookup.md) |
| Vì sao trích nguyên văn thay vì tóm tắt | [`docs/adr/ADR-015`](adr/ADR-015-slm-required-for-grounded-rag.md) |
| Stack RAG, ngưỡng hiệu chỉnh, hợp đồng Citation | [`docs/adr/ADR-003`](adr/ADR-003-local-rag-stack.md) |
| Hợp đồng agent, tool registry, dải giá trị | [`docs/agent_spec.md`](agent_spec.md) |

**Code, theo thứ tự nên đọc:**

```
src/mqtt_topics.py               ← tên topic, đọc đầu tiên, ngắn nhất
src/models/vehicle.py            ← hình dạng dữ liệu (VehicleCommand, CommandEvent, ...)
src/services/mqtt_client.py      ← lớp bọc MQTT + InMemoryBroker cho test
src/services/tool_executor.py    ← gửi lệnh và chờ sự kiện (mục 5, bước 5-9)
src/services/vehicle_state.py    ← cache trạng thái + chấm readiness (mục 6)
src/services/vehicle_gateway.py  ← cổng duy nhất ra vào xe (ADR-013)
src/vehicle_sim/state.py         ← máy trạng thái của xe ảo
src/vehicle_sim/runtime.py       ← vòng đời MQTT của xe ảo (mục 5, bước 6-8)
```

**Đường câu hỏi (mục 6), theo thứ tự nên đọc:**

```
src/agents/router.py             ← _match(): sáu bước của ADR-011 (mục 6.3, bước 2)
src/agents/nodes/normalize.py    ← node vào của mọi lượt, dọn state lượt trước
src/agents/nodes/rag_node.py     ← kiểm index, truy hồi, sinh citation
src/rag/retrieve.py              ← top_k=8, min_score=0.848, min_overlap=0.65, EXCERPT_CHARS=300
src/agents/nodes/compose.py      ← _quote_top_evidence(): trích nguyên văn, QUOTE_MAX_CHARS=1200
src/services/citations.py        ← kho citation có trần
src/api/citation_routes.py       ← GET /citations/{id}, phân quyền theo chủ phiên
```

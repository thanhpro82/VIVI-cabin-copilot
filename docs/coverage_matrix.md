# Command Coverage Matrix — VIVI Cabin Copilot

> **Status: Chạy được trên PC.** Tài liệu này mô tả **hiện trạng đã implement** trên `develop`
> tại 2026-08-12, không phải phạm vi cam kết. Mọi ô trong bảng đều đối chiếu trực tiếp với code,
> không lấy từ tuyên bố của tài liệu khác.

Tài liệu này trả lời đúng một câu hỏi: **so với toàn bộ không gian lệnh thoại của một xe hơi
hiện đại, hệ thống đang phủ được bao nhiêu?** Nó tồn tại vì hai lý do:

1. Router mặc định rơi xuống tra sổ tay (`ADR-011`), nên hệ thống **trả lời được** rất nhiều thứ
   nó **làm không được**. Khi demo hoặc báo cáo, hai cột đó phải tách rời.
2. Bề mặt điều khiển là một **tập đóng**, không phải một danh sách mở còn thiếu rule.

Nguồn canonical cho từng ô:

- Tool và dải giá trị: [agent_spec.md — Tool registry](agent_spec.md#tool-registry-and-planning-invariants)
- Domain và vehicle state: [data_model.md — Vehicle state](data_model.md#vehicle-state), `schemas/mqtt/`
- Phân loại an toàn: [safety_and_hitl.md](safety_and_hitl.md)
- Quyết định mặc-định-tra-sổ-tay: [ADR-011](adr/ADR-011-default-route-to-manual-lookup.md)
- Ranh giới sprint của `search_nearby_poi`: [ADR-010 §Scope boundary](adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md)

## Tập đóng: mọi thứ hệ thống có thể tác động

Bề mặt điều khiển bị khóa cứng ở ba chỗ **phải khớp nhau**, và
`scripts/validate_mqtt_schemas.py` + `scripts/crosscheck_mqtt_spec.py` sẽ fail nếu lệch:

| Chỗ khóa | File | Nội dung |
|---|---|---|
| 9 domain (8 nhận lệnh) | `src/models/vehicle.py` — `Domain` literal | `motion`* `hvac` `windows` `doors` `media` `navigation` `seat` `lights` `trunk` |
| 16 tool | `src/services/tool_registry.py` — `_SPECS` | 3× S0, 9× S1, 4× S2 |
| trong đó 1 tool **cục bộ của IVI** | `open_app` — `domain=None`, `requires_stationary=True` | S1 khi xe ở số P, **S3 khi không** (ADR-023). Không publish MQTT, không actuator, không đổi trạng thái xe |
| enum `tool` trên dây | `schemas/mqtt/vehicle_command.schema.json` | 12 actuator tool |

\* `motion` là `READ_ONLY_DOMAINS` — chỉ đọc, dùng để phân loại S2/S3. Không có tool nào đổi được
tốc độ, số hay ignition.

**Số domain không tăng theo số tool.** `open_app` (ADR-023, duyệt 19/08) đưa tổng tool từ 15 lên 16
nhưng domain vẫn 9: nó không có domain nào cả. Đó cũng là lý do enum `tool` trên dây vẫn đúng 12 —
`ACTUATOR_TOOLS` chỉ lấy tool có `domain is not None`. Nếu có ngày `open_app` xuất hiện trong
`vehicle_command.schema.json` thì đó là bug, không phải mở rộng.

**Ngoài ba bảng này thì không tồn tại.** Không có state để đọc, không có topic để publish,
không có simulator để phản hồi.

## Ma trận bao phủ theo nhóm chức năng

Phân nhóm theo taxonomy lệnh thoại ô tô phổ thông (11 nhóm). Ký hiệu:
**●** phủ đủ dùng · **◐** phủ một phần · **✗** không có gì.

| # | Nhóm chức năng | Điều khiển | Có gì thật | Thiếu gì |
|---|---|:-:|---|---|
| 1 | **Điều hòa (HVAC)** | ◐ | `set_hvac_power`, `set_hvac_temperature` (16–30 °C, S1), `set_hvac_fan_level` (0–3, S1) | Không chế độ gió, lấy gió trong/ngoài, sấy kính, 2 vùng, hàng ghế sau. Quạt gió chỉ nhận **mức tuyệt đối** — router không đọc state nên `"tăng quạt gió"` trả `clarify`, client phải tự tính mức. Từ 2026-08-15 mọi miền đều vậy, xem §Cách nói về lượng |
| 2 | **Ghế** | ◐ | `set_seat_heating` (0–3, S1); `set_seat_position` 3 trục `fore_aft`/`recline`/`height` (0–100, S2 khi đứng yên) | **Chỉ 2 ghế trước** (`FrontSeatKey`). Không thông gió, massage, ghi nhớ vị trí, ghế sau |
| 3 | **Giải trí / Media** | ◐ | `media_control`: `play`, `pause`, `next`, `previous`, `set_volume` (0–100, S1), `play_track` (gọi tên **một** bài trong 5 bài của `src/fixtures/media.json`, S1) | Không đổi nguồn phát, radio, Bluetooth, podcast, playlist ngoài 5 bài fixture. Tên bài **ngoài** playlist trả `denied media_track_unknown` và **không đổi bài đang phát** — trước 2026-08-26 nó ra `play` và xe phát một bài khác trong im lặng. `previous` và cách nói `"chuyển bài"` mới nối được ở issue #65 — trước đó `previous` có trong registry nhưng router không map, và `next` chỉ gọi được nếu câu chứa chữ `nhạc`. **Tắt tiếng là mute, không phải dừng**: `"tắt tiếng"`/`"tắt âm thanh"`/`"tắt âm lượng"` ra `set_volume: 0` — nhạc **vẫn chạy**, chỉ câm — còn `"tắt nhạc"` ra `pause`. Không có trường `muted` trong `MediaState`, nên mức trước khi tắt không lưu được ở đâu và `"bật tiếng lại"` phải `clarify` hỏi lại mức thay vì khôi phục. `"im lặng đi"`/`"yên lặng đi"` cũng ra `pause` — PO chốt ở review #340 (28/08) rằng câu ấy được hiểu là yêu cầu tắt nhạc. Giới hạn còn lại: `pause` dừng **dàn nhạc**, không ngắt **TTS**, nên nói câu này giữa lúc VIVI đang đọc thì nhạc dừng còn VIVI đọc tiếp — lệnh thoại ngắt TTS vẫn chưa có |
| 4 | **Cửa, kính & cốp** | ◐ | `set_window_position` 4 kính 0–100% (S2 **luôn luôn**); `set_door_state` 4 cửa `open`/`closed`; `set_trunk_state` cốp `open`/`closed` — hai cái sau S2 khi `speed_kph == 0 && gear == P`, ngoài ra S3. Lệnh không nêu vị trí nhắm **cả bốn cửa** (plan 4 bước, một phê duyệt gộp) | **Không có khóa/mở khóa** — `DoorsState` và `TrunkState` chỉ có vị trí. Không cửa sổ trời, rèm che nắng, auto up/down |
| 5 | **Đèn** (pha/cốt, sương mù, passing, hazard, welcome, đèn trần, đọc sách, ambient) | ◐ | `set_headlight_mode` (`auto`/`low_beam`/`high_beam`, S1) và `set_interior_light` (S1) | **Không có `off`** cho đèn pha — UNECE R48 cấm chế độ tắt thủ công trên xe có DRL, xem [ADR-020](adr/ADR-020-lights-and-trunk-domains.md); `"tắt đèn pha"` trả `denied`. Không đèn sương mù (sổ tay ghi "nếu có trang bị"), passing, hazard, welcome, đọc sách, ambient |
| 6 | **Lái xe, vận hành & cảnh báo** | ✗ | `motion` (`speed_kph`, `gear`, `ignition`) **chỉ đọc** | Không drive mode, cruise control/ACC, speed limiter, LKA, cảnh báo điểm mù, EPB, Auto Hold, HDC, cảm biến đỗ, auto parking, camera 360/lùi. Router **denied** thẳng `phanh tay`, `phanh abs`, `động cơ`, `túi khí` |
| 7 | **Gạt mưa & gương** | ✗ | — | Không có gì, kể cả trong danh sách chặn — câu lệnh rơi thẳng xuống `default_to_manual` → RAG |
| 8 | **Điều hướng** | ◐ | `set_navigation` `start`/`cancel` (S1); `NavigationState` = `status` + `destination_id` | Router **hard-code đúng 3 đích** (`router.py:374-381`): `trạm sạc` → `poi-charge-01`, `bình minh`/`thứ hai` → `poi-cafe-02`, `cà phê`/`cafe` → `poi-cafe-01`. Không tìm địa chỉ tự do, zoom/2D/3D/vệ tinh, cảnh báo giao thông, lưu Nhà/Cơ quan |
| 9 | **Liên lạc** (gọi điện, SMS/Zalo, SOS) | ✗ | — | **Đúng thiết kế**: [product_brief.md §Out of scope](product_brief.md) loại "gọi điện thật". Đây là nhóm 0% duy nhất không phải là thiếu sót |
| 10 | **Trạng thái xe & chẩn đoán** | ◐ | `get_vehicle_state` (S0) trả đủ 9 domain qua `GET /api/v1/vehicle/state` | **Không có pin/SoC, range, TPMS, nhiệt độ động cơ, lịch bảo dưỡng, mã lỗi.** Use case P0 số 3 ("đèn áp suất lốp nghĩa là gì?") chạy được nhưng qua **RAG sổ tay** — hệ thống *giải thích* được đèn cảnh báo, *đọc* được áp suất lốp thì không |
| 11 | **Smart scenes** (Relax/Nap, Camp/Pet, Car Wash, Valet) | ✗ | Cơ chế đã có: `CandidateActionPlan` nhiều bước, `depends_on`, `execution_group_id`; router đã sinh plan 2 bước cho `"bật điều hòa lên 25 độ"` | Không scene/macro nào được định nghĩa. Car Wash cần gương + gạt mưa (nhóm 7, không tồn tại); Relax cần rèm che nắng (không tồn tại); Valet cần khóa màn hình + giới hạn tốc độ (không tồn tại) |

**Tổng kết: 6/11 nhóm có điều khiển và đều là một phần nhỏ; 5/11 nhóm bằng 0**, trong đó chỉ
nhóm 9 là cố ý. Nhóm 5 (Đèn) chuyển từ ✗ sang ◐ ở issue #65.

## Bao phủ ngôn ngữ hẹp hơn bao phủ tool

Một tool tồn tại không có nghĩa người dùng gọi được nó bằng lời. `DeterministicControlRouter`
có 8 matcher, mỗi matcher đòi **cả từ khóa domain lẫn động từ điều khiển ở đầu câu** —
đây là chủ ý, để câu hỏi tra cứu không bị hiểu nhầm thành lệnh.

**Từ đồng nghĩa nằm ở một chỗ**: `src/agents/tu_dong_nghia.py` (từ 2026-08-26, issue #308
PR 2a). Trước đó mỗi matcher tự khai chuỗi cứng, nên `"bật máy lạnh"`, `"làm ấm ghế lái mức
2"`, `"chuyển sang chiếu gần"` — cùng ý định với ba câu đang chạy — đều rơi xuống sổ tay.
Bảng nhận: `máy lạnh`/`ac`/`hệ thống làm mát` = điều hòa; `làm ấm`/`hâm nóng` = sưởi;
`độ cao ghế`/`chiều cao ghế` = trục height; `cos`/`low beam`/`high beam`/`auto` = chế độ đèn;
`tiếp tục phát` = play. Nó khớp theo **biên từ**, không phải chuỗi con — `"ac"` không được
phép trúng chữ `các`.

Hệ quả cần biết:

- `_side()` chỉ hiểu `bên lái`/`ghế lái`, `bên phụ`/`ghế phụ`, `sau bên trái`, `sau bên phải`.
  `"mở cửa sổ sau"` → `clarify`, dù tool phủ cả 4 kính.
- `"hạ kính xuống chút đi"` → `clarify` (`missing_window_position`): không có số, và router
  **không đoán**.
- Câu lệnh không mở đầu bằng động từ trong `_COMMAND_VERBS` sẽ không khớp matcher nào.
- `"Trong xe nóng quá."` — use case P0 số 1 — **không phải câu mệnh lệnh**, không khớp matcher
  nào, nên rơi xuống `default_to_manual`. Nó không đề xuất HVAC.

### Cách nói về lượng

Khảo sát 50 câu về lượng
([báo cáo](reports/router-parser-so-luong-khao-sat-2026-08-15.md)) cho thấy phần lớn sai **âm
thầm** chứ không hỏi lại. Sau đợt sửa 2026-08-15:

| Cách nói | Hành vi |
|---|---|
| `50%`, `50 phần trăm`, `năm mươi phần trăm`, `hai sáu phần trăm` | 50 / 26 — dạng chữ kèm hậu tố hỏng tới issue #117 |
| `1/3`, `một phần ba`, `ba phần tư` | 33 / 33 / 75 — trước đây ra 1, 3, 4 |
| `một nửa`, `nửa` | 50 ở **cả ba** miền thang 0–100 (kính, ghế, âm lượng); trước chỉ kính |
| `hết cỡ`, `tối đa`, `toang`, `mở hết` | 100 |
| `hai chục` · `hai mươi rưỡi độ` · `22,5 độ` | 20 · 20,5 · 22,5 (`temperature_c` là float) |
| `một chút`, `tí`, `hé`, `mười mấy`, `vài chục` | `clarify` — lượng định tính/không xác định, không đoán |
| `tăng thêm 10`, `giảm đi 20`, `mở thêm 20%` | `clarify` / `relative_change_unsupported` |

**Lệnh tương đối bị từ chối ở mọi miền, không riêng quạt gió.** Router không đọc vehicle state
(ADR-011) nên không cộng trừ được từ mức hiện tại; trước đây chỉ nhánh quạt gió hỏi lại, còn
âm lượng và kính đọc con số thành **giá trị tuyệt đối** và chạy luôn — đang ở 60 mà nói `"tăng
thêm 10"` thì âm lượng tụt xuống 10. Client phải tự tính mức rồi gửi số tuyệt đối.

## Rủi ro trình bày

Vì mặc định của router là tra sổ tay chứ không phải từ chối (ADR-011), một buổi demo sẽ
**trông như** hệ thống hiểu đèn sương mù, cruise control hay Camp Mode. Nó chỉ đang đọc
482 chunk sổ tay VF9. Khi báo cáo phải tách hai cột:

| | Phạm vi |
|---|---|
| **Điều khiển được** | 8 domain actuator (`hvac` `seat` `media` `navigation` `lights` `windows` `doors` `trunk` — tức 9 domain trừ `motion` chỉ đọc), 12 tool, các mẫu câu ở §bao phủ ngôn ngữ |
| **Trả lời được** | Bất kỳ nội dung nào có trong `data/manuals/vf9_2026_vi/` (58 tài liệu → 482 chunk) |

Không được gộp hai cột này thành một con số "hỗ trợ N lệnh".

## Chi phí thêm một nhóm mới

> **Đã kiểm chứng bằng thực tế 2026-08-12.** Danh sách 9 chỗ dưới đây được viết như một *ước
> lượng*; issue #65 đã thực sự thêm nhóm 5 (Đèn) và nhóm cốp, và ước lượng **đúng cả 9 mục** —
> cộng thêm hai chỗ danh sách này bỏ sót: `schemas/mqtt/domain_state.schema.json` (enum `domain`
> + một nhánh `allOf` cho mỗi domain mới) và `scripts/validate_mqtt_schemas.py` (fixture
> `SNAPSHOT` cùng các case âm). Với `lights` thì câu hỏi "S1 hay S2?" ở mục 8 hoá ra **không có
> đáp án** cho tới khi bỏ `off` khỏi enum — xem [ADR-020](adr/ADR-020-lights-and-trunk-domains.md).

Thêm một nhóm không phải thêm một rule. Ví dụ nhóm 5 (Đèn) — **rẻ nhất** vì là state thuần,
S1, không ràng buộc chuyển động — vẫn phải sửa đồng bộ 9 chỗ:

1. `schemas/mqtt/vehicle_state_domains.schema.json` — thêm `lights`
2. `schemas/mqtt/vehicle_command.schema.json` — thêm tool vào enum
3. `src/models/vehicle.py` — `Domain` literal + `LightsState` + field trong `VehicleState`
4. `src/vehicle_sim/state.py` — giá trị khởi tạo + xử lý lệnh
5. `src/services/tool_registry.py` — `ToolSpec` + args model
6. `src/agents/tools/lights.py` — executor
7. `src/agents/router.py` — matcher + từ khóa
8. `src/agents/policy.py` — phân loại S1/S2 (đèn hazard khi đang chạy là S1 hay S2?)
9. Test ở `tests/test_agents/` + `tests/test_services/`, và cập nhật `agent_spec.md` + `mqtt_spec.md`

Nhóm 6 (lái xe/hỗ trợ lái) đắt hơn nhiều: `motion` đang là `READ_ONLY_DOMAINS`, cho phép ghi
vào nó là **thay đổi giả định an toàn nền tảng** — mọi phân loại S2/S3 hiện dựa trên
`speed_kph`/`gear` là dữ liệu tin cậy do simulator sở hữu. Việc đó cần ADR riêng, không phải
một PR tính năng.

## Khoảng cách giữa tài liệu và code

Ba chỗ tài liệu mô tả kỹ nhưng code chưa có — **không phải bug**, đều có ranh giới rõ:

| Hạng mục | Tài liệu | Code | Ranh giới |
|---|---|---|---|
| `search_nearby_poi` + `PlanningResolution` | `agent_spec.md`, `data_model.md`, `technical_spec.md`, `user_experience.md` mô tả đầy đủ lease/digest/effectively-once | **Tool đã sống (SP-5, 23/08) và chạy trọn đường plan (#371, 29/08)**: có `SearchNearbyPoiArgs` (schema đóng 5 loại), matcher `_match_tim_poi`, executor `_ket_qua_tim_poi` trả danh sách trong `after`, phân loại S0, và composer dựng câu từ chính kết quả ấy. Trước #371 tool bị loại khỏi `KHONG_CHO_DUONG_PLAN` trong khi router vẫn sinh plan cho nó, nên lượt số nhiều chết ở `validate_args` mà vẫn đọc danh sách. `PlanningResolution` (lease/digest/effectively-once) thì **vẫn chưa** — SP-5 không dựng cơ chế phân giải nào | Tìm chạy trên fixture 6 POI, không phải bản đồ thật; `"đưa tôi về nhà"` ngoài phạm vi (dữ liệu người dùng, thuộc `vehicle/profile`) |
| **Lệnh ngầm không động từ** (*"Tối om thế này"*, *"Nhạc gì mà chán thế"*) | Người lái mô tả trạng thái khó chịu và mong xe hiểu | **Chưa xử.** Classifier chấm `chitchat`, tài xế nhận câu xã giao thay vì đèn bật. Mốc đo: cổng `bẫy→chitchat` = **4** (`eval/results/chitchat/20260823T034318.412466Z`). Không tạo hành động sai — ô nguy hiểm `manual→control` vẫn = 0. Nặng hơn: thêm một vế than vào trước một lệnh hợp lệ cũng làm hỏng nó (*"Tối quá, bật đèn trần lên đi"* → `clarify`, dù *"Bật đèn trần lên"* chạy tốt) | Phạm vi đang chờ chốt ở [#256](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/256). Sửa prompt **không** phải đường ra — trần đã đo ở SP-1 (v4 tệ hơn v3); cần router đọc `vehicle_snapshot`, tức hạ tầng của SP-6 |
| Use case P0 số 2 (`tìm cà phê → HVAC → dẫn đường`) | `product_brief.md:59` liệt là "Known P0 multi-intent" | **Không chạy được** — phụ thuộc mục trên | Cùng ADR-010 |
| Ngưỡng `speed_kph > 5` | `docs/VIVI_API_Spec.md` | Không implement và **không được implement** | ADR-010 supersede; `safety_and_hitl.md` là nguồn phân loại |

Cập nhật 2026-08-10 — [TASK-BE-OBS-001](tasks/TASK-BE-OBS-001-engineer-observability.md) đã
đóng ba khoảng trống quan sát, nhưng **không đụng gì tới bảng bao phủ lệnh ở trên**: nó thêm
`GET /traces/{id}`, `GET /metrics/summary` và ba event `/ws/engineer`. Số lệnh xe điều khiển
được vẫn nguyên — 8 tool chấp hành, 5/11 nhóm trong phân loại lệnh thoại.

Cập nhật 2026-08-12 — [issue #65](../README.md) / [ADR-019](adr/ADR-019-fan-level-becomes-controllable.md)
thêm `set_hvac_fan_level`, nâng số tool chấp hành lên **9**. Số nhóm vẫn là 5/11: quạt gió nằm
trong nhóm 1 vốn đã ◐. Cùng đợt, router mở vốn từ cho `media_control.previous` và cho lệnh
nhắm cả bốn cửa/kính — đó là **bao phủ ngôn ngữ**, không phải bao phủ tool, nên bảng trên
không đổi ô nào ngoài dòng 1 và 3.

Điều đáng ghi vào đây là **dashboard kỹ sư giờ đo được chính khoảng cách này**:
`stage_latency_ms` cho biết stage nào chậm, `safety` đếm số lần chặn S3 và số approval, còn
`model_runtime` trả về `"not-selected"` với mọi percentile `null` — một cách nói thẳng bằng dữ
liệu rằng **không có LLM nào chạy trên đường lệnh**. Đó không phải thiếu sót của endpoint; đó
là `slm_enabled=False` cộng ADR-005 "Not Yet", hiển thị đúng như nó vốn thế.

⚠ Con số latency lấy từ `/metrics/summary` là **đo trên PC, sau STT, không qua TTS** (Piper
chưa nối vào pipeline nên `tts` luôn bằng 0). Chưa đủ tư cách làm bằng chứng cho mục tiêu p50
≤ 2.500 ms / p95 ≤ 4.500 ms của `product_brief.md` — mục tiêu đó tính từ end-of-speech tới
first audio, mà nửa sau chưa tồn tại.

Cập nhật 2026-08-27 — [issue #320](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/320)
nối `"tắt tiếng"` vào `media_control.set_volume` với giá trị 0. **Không** thêm tool, **không**
thêm action, nên số tool chấp hành và số nhóm 6/11 đều đứng yên — đây là bao phủ ngôn ngữ,
đúng hạng mà bản cập nhật 12/08 đã đặt tên. Chỉ ô "Thiếu gì" của dòng 3 đổi.

Ghi lại một chỗ hợp đồng bó tay chứ không phải luật bó tay, để lần sau khỏi truy lại:
`MediaState` chốt đúng ba trường `status/volume/track` và schema khoá
`additionalProperties: false`, nên **mute là một phép ghi mất mát** — sau `set_volume: 0` thì
mức cũ không còn ở đâu cả. Đó là lý do `"bật tiếng lại"` hỏi lại mức thay vì khôi phục; chọn
bừa một con số (kể cả 35 của trạng thái khởi tạo) là làm một việc người dùng không yêu cầu.
Muốn khôi phục thật thì phải thêm `muted` vào hợp đồng MQTT — một quyết định về hợp đồng, cần
ADR riêng, không nên lẻn vào một PR luật.

Bổ sung 2026-08-28 — PO chốt `"im lặng đi"` là **yêu cầu tắt nhạc**, map vào
`media_control{action: pause}`, cùng bước với `"tắt nhạc"`. Issue #320 xếp câu này vào tiêu
chí đóng nhưng để ngỏ nó thuộc `pause` hay `set_volume: 0`; đó là quyết định sản phẩm, và
đây là chỗ ghi lại nó. Số tool và số nhóm 6/11 vẫn đứng yên vì không thêm action nào.

Giới hạn phải nói ra kèm quyết định ấy: `pause` dừng **dàn nhạc**, không ngắt **TTS**. Người
nói `"im lặng đi"` giữa lúc VIVI đang đọc một đoạn sổ tay sẽ thấy nhạc dừng còn VIVI đọc
tiếp. Lệnh thoại ngắt TTS chưa tồn tại — PR #140 chỉ ngắt bằng thao tác tay ở FE — nên đây
là khoảng trống của **hệ**, không phải của luật media, và nó không đóng lại được bằng một
dòng router.

## Cách kiểm chứng lại bảng này

```powershell
# Danh sách tool và domain thật
.\.venv\Scripts\python.exe -c "from src.services.tool_registry import TOOL_REGISTRY, ACTUATOR_TOOLS; print(sorted(TOOL_REGISTRY)); print(sorted(ACTUATOR_TOOLS))"
.\.venv\Scripts\python.exe -c "from src.models.vehicle import DOMAINS, READ_ONLY_DOMAINS; print(DOMAINS, READ_ONLY_DOMAINS)"

# Registry có khớp schema MQTT và mqtt_spec không
.\.venv\Scripts\python.exe scripts\validate_mqtt_schemas.py
.\.venv\Scripts\python.exe scripts\crosscheck_mqtt_spec.py

# Router thật sự nhận những câu nào
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q
```

Khi thêm domain/tool mới, **cập nhật bảng §Ma trận bao phủ trong cùng PR** — nếu không, tài
liệu này trở thành một tuyên bố hiện trạng sai, đúng loại lỗi mà `README.md` §status đang chống.

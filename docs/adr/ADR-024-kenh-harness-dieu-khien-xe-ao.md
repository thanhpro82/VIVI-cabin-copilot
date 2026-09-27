# ADR-024: kênh harness `v1/sim/` — đặt chuyển động xe ảo từ ngoài, nằm ngoài hợp đồng xe

- Status: **Proposed** — chờ @thanhpro82 (PM/PO) duyệt trên [issue #183](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/183)
- Date: 2026-08-20
- Decision owner: WS3 Virtual Vehicle & Router (Sơn)
- Liên quan: [issue #183](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/183),
  [issue #184](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/184) (deploy công khai),
  [ADR-004](ADR-004-mqtt-vehicle-simulator.md) (hợp đồng MQTT),
  [ADR-010](ADR-010-canonical-tool-registry-with-product-vision-adapter.md) (bác ngưỡng `speed_kph > 5`),
  [ADR-013](ADR-013-single-vehicle-state-source.md) (**một nguồn trạng thái xe**),
  [ADR-023](ADR-023-open-app-va-chan-app-video-khi-xe-chay.md) (S3 khi xe không ở P),
  `docs/mqtt_spec.md`, `docs/devops.md`, `docs/huong_dan_chay.md` §3.3,
  `src/vehicle_sim/runtime.py:152`

## Context

`docs/huong_dan_chay.md` §3.3 liệt kê 4 kịch bản nghiệm thu. Kịch bản số 4 — **chặn cứng
S3 khi xe đang chạy** — dựng được bằng đúng một cách:

> **Lệnh xe mô phỏng** (gõ vào cửa sổ 2): `speed 45` · `gear P` · `stop` · `state` · `help`.
> Đây là **cách duy nhất** đặt tốc độ — giao diện không có nút nào làm được, vì tốc độ chỉ
> do xe tự báo lên. *(`huong_dan_chay.md:64-66`)*

Nghĩa là: muốn demo luật an toàn quan trọng nhất của đồ án thì phải **gõ vào stdin của một
tiến trình Python trên máy người trình bày**.

Điều đó đủ dùng khi cả bốn kịch bản chạy trên laptop có người ngồi trực. Nó **hết dùng
được** ngay khi có link công khai (#184): BTC mở trình duyệt, không có shell, không có cửa
sổ 2. Hệ quả không phải là "thiếu một tính năng phụ" — ba kịch bản còn lại (S1 điều hoà, S2
kính, RAG áp suất lốp) vẫn chạy bình thường, nên người chấm sẽ thấy một hệ thống **thiếu
đúng phần lõi mà đồ án lấy làm luận điểm chính**.

Ba việc đang cùng chờ một khả năng, không phải một:

| Chờ gì | Vì sao |
|---|---|
| #184 — deploy công khai | Mục nghiệm thu ghi thẳng "4 kịch bản runbook §3.3", trong đó ca 4 cần đặt được tốc độ |
| #185 — `open_app` S3 khi xe không ở P | Luật của ADR-023 chỉ chứng minh được ở test; chưa ai chạy thật câu *"mở YouTube"* lúc xe chạy |
| #190 — tự chuyển màn theo `tool.result` | PR tự khai: chưa thử ca S3 thật, "cần đặt được tốc độ/số cho xe ảo" |

Phần hiển thị thì **đã xong từ trước**: `StatusBar` hiện `{speed} km/h`, `DriverShellProvider`
poll `GET /vehicle/state` mỗi 2 s, và `SpeedDebugDrawer.tsx` đã có sẵn thanh trượt — nhưng ở
real mode nó tự hạ xuống thành bảng chỉ-xem, kèm ghi chú giải thích vì sao. Thiếu đúng
**đường ghi**.

### Ràng buộc không được phá

`motion` nằm trong `READ_ONLY_DOMAINS` (`src/models/vehicle.py:35`): nó là thứ **xe tự
quyết**, không ai ra lệnh được, nên hợp đồng xe **không có topic lệnh cho nó**. Và
`config/mosquitto/acl` cấm `vivi-backend` ghi `v1/vehicles/+/state/#`. Hai điều đó cộng lại
nghĩa là dưới MQTT không tồn tại đường hợp lệ nào để backend làm xe "chạy".

Lối thoát hợp lệ duy nhất đã được ghi sẵn trong code, từ trước khi có issue này:

> Lối thoát hợp lệ duy nhất là **xe tự đặt tốc độ của chính nó** — tức method này, gọi từ
> trong tiến trình xe ảo. Không vi phạm ACL vì publisher vẫn là identity simulator.
> Xem ADR-013. *(`SimulatorRuntime.set_motion`, `runtime.py:160-162`)*

Console stdin đang gọi đúng method đó. Câu hỏi của ADR này vì vậy **không phải** "làm sao
đặt được tốc độ" — mà là "làm sao **với tới** method đó từ ngoài tiến trình, mà không mở một
cửa hậu điều khiển xe".

### Vì sao đây không phải một lệnh xe

"Đặt tốc độ xe" nghe như lệnh điều khiển, và nếu coi nó là lệnh điều khiển thì buộc phải
thêm topic lệnh cho `motion` — tức phá ADR-013 và biến `READ_ONLY_DOMAINS` thành lời nói
suông.

Nhưng nó không phải lệnh gửi cho xe. Nó là lệnh gửi cho **thế giới mô phỏng**: "giả sử bây
giờ xe đang chạy 45 km/h". Trên xe thật không có nút nào tương ứng, vì trên xe thật thứ này
do vật lý quyết định. Đây là **bàn đạo diễn kịch bản demo**, không phải giao diện điều khiển
xe — cùng loại với việc một bài test dựng `InProcessVehicleGateway.new(speed_kph=45)`, chỉ
khác là chạy lúc runtime.

Phân biệt ấy phải **nhìn thấy được trong code**, không chỉ nằm trong đầu người viết. Đó là
toàn bộ nội dung quyết định bên dưới.

## Tiền lệ

Cách ngành tách "điều khiển thế giới mô phỏng" khỏi "điều khiển phương tiện" — hai nguồn,
cùng một hình dạng: **kênh riêng, tên riêng, không dùng chung đường với API xe.**

| Nguồn | Nói gì |
|---|---|
| **Android Automotive — VHAL emulator** (`packages/services/Car/tools/emulator`) | Việc bơm giá trị property cho xe giả lập đi qua một kênh **riêng của công cụ**, không đi qua `CarPropertyManager` mà ứng dụng dùng. App không có cách nào tự bịa tốc độ cho mình, kể cả trên bản giả lập |
| **CARLA** — `set_target_velocity()` / `Client` API | Việc "đặt cho xe đang chạy 45 km/h" là lệnh của **kịch bản** gửi tới server mô phỏng, tách hẳn khỏi luồng sensor/state mà xe công bố ra |

Không nguồn nào giải bài này bằng cách thêm một lệnh mới vào giao diện điều khiển phương
tiện. Nội bộ repo cũng đã có sẵn hình dạng ấy: `mqtt_topics.health_probe()` (issue #51) là
một topic **kỹ thuật**, cố ý đặt tên `_health_probe` để `parse_command_domain()` trả `None`
và simulator bỏ qua an toàn — tức tiền lệ "topic tồn tại nhưng không phải lệnh xe" đã có
trong file này rồi.

## Decision

**1. Namespace riêng `v1/sim/`, nằm ngoài `v1/vehicles/`.**

```python
# src/mqtt_topics.py
SIM_PREFIX = "v1/sim"

def sim_motion_set(vehicle_id: str) -> str:
    return f"{SIM_PREFIX}/{vehicle_id}/motion/set"
```

**Không** đặt nó thành `v1/vehicles/{id}/commands/motion`. Ba lý do, lý do thứ ba là lý do
thật sự:

- `parse_command_domain()` sẽ nhận `motion` là một domain lệnh hợp lệ, và `motion` rời khỏi
  `READ_ONLY_DOMAINS` **trên thực tế** dù enum không đổi một chữ.
- ACL của backend đã là `write v1/vehicles/+/commands/#`, nên topic mới **tự động được
  phép** — không ai phải quyết định gì, không có dòng nào để review, không có ai ký tên.
  Một lần nới quyền im lặng là đúng thứ ADR-013 tồn tại để ngăn.
- Tách namespace biến ranh giới thành thứ **grep ra được**. `rg "v1/sim"` trả về đúng toàn
  bộ bề mặt harness. Ranh giới nào không kiểm tra được bằng một lệnh thì sáu tuần nữa không
  còn ai giữ.

`docs/mqtt_spec.md` ghi namespace này ở **mục riêng, có nhãn "ngoài hợp đồng xe"**; bảng
topic hợp đồng giữ nguyên không thêm dòng nào.

**2. Xe vẫn tự đặt tốc độ của chính nó. Backend chỉ nhắn tin.**

Backend publish lên `v1/sim/{id}/motion/set`; xe ảo subscribe, rồi gọi đúng
`SimulatorRuntime.set_motion()` mà console stdin đang gọi — dùng lại nguyên đường publish
domain + snapshot + tăng `state_version`. Không có đường thứ hai nào đổi `motion`.

Nhờ vậy hai bất biến của ADR-013 còn nguyên nghĩa, không phải "về mặt kỹ thuật":

- **Publisher của `state/*` vẫn là identity `vehicle-simulator`.** Backend vẫn không ghi
  được `state/#` — ACL không đổi một dòng nào ở namespace hợp đồng.
- **Vẫn một máy trạng thái duy nhất.** `state_version` vẫn do simulator tăng, nên không có
  race với `expected_state_version` (ADR-013 mục 6).

**3. Mặc định tắt, và tắt nghĩa là không tồn tại.**

```python
sim_control_enabled: bool = False   # src/config.py
```

Route `POST /api/v1/sim/motion`: `include_in_schema=False`, trả **404** khi cờ tắt —
**không phải 403**. 403 xác nhận route có thật, và bề mặt harness thì không nên xác nhận
điều gì với người không được bật nó. Cùng khuôn với `/agent/process`
(`src/api/agent_routes.py:100-104`).

Route này **không** thuộc bề mặt P0. `docs/api_spec.md` hiện khai 14 interface; con số đó
**không đổi** — ADR này ghi rõ route harness nằm ngoài bảng, như `/agent/process`.

**4. Enum đóng và khoảng đóng, kiểm ở cả hai đầu.**

Schema mới `schemas/mqtt/sim_motion_set.schema.json`:
`{speed_kph: number 0..200, gear: "P"|"R"|"N"|"D"}`, thêm ca **phải-fail** vào
`scripts/validate_mqtt_schemas.py`. Route validate cùng ràng buộc và trả **422** khi lệch,
xe ảo không đổi state.

Hai đầu cùng kiểm là chủ ý: route là đường duy nhất **hôm nay**, không phải đường duy nhất
mãi mãi — L2 contract test publish thẳng vào topic, và bất kỳ ai cầm credential backend cũng
publish được.

**5. ACL: một chiều, một topic.**

```
user vivi-backend
topic write  v1/sim/+/motion/set

user vehicle-simulator
topic read   v1/sim/+/motion/set
```

**Không** cấp `v1/sim/+/#`. Wildcard ở đây nghĩa là mọi topic harness tương lai được phép
trước khi ai kịp nghĩ nó nên tồn tại hay không.

**6. Namespace này chỉ được chứa những gì xe tự quyết mà không ai ra lệnh được.**

Tức: `motion`, và ở P0 là hết. Nếu sau này có người thêm `v1/sim/{id}/doors/set` thì đây
thành cửa hậu mở cửa xe **vòng qua policy và HITL** — mọi actuator phải đi hợp đồng xe, qua
`policy.py`, qua S0–S3. Ràng buộc này là điều kiện để namespace tồn tại, không phải lời
khuyên kèm theo; nó phải có test khoá, không chỉ có câu văn này.

**7. Chu kỳ tự chạy dùng chung đúng method đó.**

`sim_drive_cycle: bool = False`. Bật thì xe lặp 0 km/h (30 s) ↔ 45 km/h gear D (30 s), gọi
cùng `set_motion()`. Không đụng ACL, không đụng route, không mở thêm bề mặt — nó chỉ là
console stdin tự gõ. Có mặt trong ADR này vì nó là **cùng một quyết định**: xe tự đặt tốc độ
của chính nó, chỉ khác nguồn kích.

Mục đích: BTC vào lúc nào cũng thấy màn hình động, kể cả khi không chạm thanh trượt. Bật
riêng khỏi `sim_control_enabled` để dựng được cấu hình "xe tự chạy, không ai đổi được" —
đúng cấu hình muốn có cho một link công khai không ai trực.

## Consequences

**Được:**

- Kịch bản 4 chạy được từ trình duyệt, không cần shell. #184 đủ 4 kịch bản; #185 và #190
  nghiệm thu được ca S3 thật lần đầu.
- `docs/huong_dan_chay.md` bỏ được câu "đây là cách duy nhất" — câu ấy hiện đang mô tả một
  giới hạn kiến trúc, và nó sẽ thành sai kể từ khi ADR này được cài.
- Ranh giới hợp đồng xe **kiểm tra được bằng grep**, không chỉ bằng trí nhớ.

**Mất / phải chấp nhận:**

- **Hai đường vào cùng một `set_motion`** (console stdin + topic harness), sắp tới là ba với
  chu kỳ tự chạy. Chấp nhận vì cả ba chụm về **đúng một method** — thứ phải tránh là hai
  *máy trạng thái*, không phải hai *nút bấm*.
- **Xe ảo là tài nguyên dùng chung, không có multi-tenant.** Trên link công khai, người khác
  kéo thanh trượt sẽ đổi tốc độ của bạn giữa lượt — và có thể biến một lượt S2 đang chờ
  duyệt thành S3. Đây là giới hạn có thật, phải ghi trên chính giao diện, không giấu trong
  docs. Nó cũng là một lý do nữa để `sim_drive_cycle` bật được độc lập.
- **Cờ tắt mặc định + 404** nghĩa là người không đọc `devops.md` sẽ thấy route "hỏng". Đổi
  lại: không ai vô tình bật được bàn đạo diễn trên một bản triển khai thật.
- **L2 contract phải thêm ca ACL cho namespace mới** — identity backend publish được, identity
  simulator thì không. Không có ca đó thì một dòng ACL sai không ai biết, vì đường HTTP vẫn
  chạy đúng qua chính broker đang cấu hình sai.
- **Bề mặt tấn công rộng thêm một chút** trên bản deploy: ai có token driver là kéo được tốc
  độ. Ở P0 đây là mô phỏng nên hậu quả tối đa là phá kịch bản demo của người khác — nhưng
  câu này sẽ **hết đúng** vào ngày ai đó nối P-192 với phần cứng, nên ràng buộc mục 6 phải
  được khoá bằng test ngay từ bây giờ.

## Alternatives considered

| Phương án | Vì sao bác |
|---|---|
| **Thêm topic lệnh cho `motion` trong `v1/vehicles/`** | Phá ADR-013: `motion` rời `READ_ONLY_DOMAINS` trên thực tế. Và ACL backend `commands/#` tự động mở — nới quyền mà không ai phải ký |
| **Backend publish thẳng `state/motion`** | Phải cấp backend quyền ghi `state/#`, tức hai publisher cho một state. `state_version` do hai bên cùng tăng là race, và ADR-013 mục 1 sập |
| **Route `PUT /api/v1/vehicle/state` cho backend bịa state** | Phá đúng câu "backend chỉ forward, không re-map, không re-derive". Tệ hơn: phân loại S0–S3 sẽ chạy trên state bịa, tức luật an toàn đọc một chiếc xe không có thật |
| **Thêm HTTP server nhỏ vào tiến trình xe ảo** | Hai giao thức cho một tiến trình, thêm một cổng phải mở ra khỏi container, và mất toàn bộ ACL + validate schema mà đường MQTT đã có sẵn |
| **Giữ nguyên stdin, hướng dẫn BTC `docker exec`** | BTC không có tài khoản trên VPS, và cho họ shell vào container để demo là đổi một vấn đề demo lấy một vấn đề an ninh |
| **Chỉ làm chu kỳ tự chạy (mục 7), bỏ thanh trượt** | Rẻ và không đụng ADR, nhưng người chấm phải **chờ đúng pha** mới hỏi được câu S3, và không dựng được ca "xe đang chạy" tại thời điểm họ muốn. Vẫn làm — nhưng như phần bổ sung, không phải phần thay thế |
| **Mở `v1/sim/+/#` cho backend cho gọn** | Cấp phép cho mọi topic harness chưa ai nghĩ ra. Xem mục 5 |

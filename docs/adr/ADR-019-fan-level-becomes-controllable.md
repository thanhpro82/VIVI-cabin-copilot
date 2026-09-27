# ADR-019: `hvac.fan_level` chuyển từ read-only sang điều khiển được

- Status: Accepted
- Date: 2026-08-12
- Decision owner: WS3 Virtual Vehicle & MQTT (Sơn)
- Liên quan: [issue #65](../tasks/TASK-FE-BE-002-real-mode-control-gaps.md), `docs/mqtt_spec.md`
  §"Quyết định P0 số 2" (mục bị lật), [ADR-010](ADR-010-canonical-tool-registry-with-product-vision-adapter.md)

## Context

`docs/mqtt_spec.md` §"Quyết định P0 số 2" chốt `hvac.fan_level` là **read-only** ở P0, với lý do
chính đáng lúc đó: registry không có tool nào đổi được nó, nên không tự thêm tool vào registry của
người khác. `HvacState.fan_level` vì thế khai `ge=0` và **cố ý không có trần** — chưa biết thang
tối đa thì không bịa ra.

Hai việc làm quyết định đó hết đúng:

1. **FE đã dựng slider quạt gió** (`VehicleControlView.tsx:251,268`) nhưng không có đường nối nào.
   Bấm vào không có gì xảy ra. Ghi ở `TASK-FE-BE-002` §1.

2. **Câu lệnh quạt bị báo sai lý do, không chỉ là không chạy.** Đo trên router thật:

   ```
   "chỉnh quạt gió điều hòa mức 3"  ->  denied / temperature_out_of_range
   ```

   Chuỗi `điều hòa` kéo câu vào `_match_hvac`, `_number` đọc `3` thành độ C, và 3 nằm ngoài
   `16..30` nên bị từ chối như một lệnh nhiệt độ. Người dùng nhận thông báo về nhiệt độ cho một
   lệnh quạt. Đây đúng lớp lỗi KI-001 mà `router.py` đã ghi hai lần là phải tránh: hệ thống làm
   một việc khác việc được yêu cầu mà không nói ra.

## Decision

**Thêm `set_hvac_fan_level` (`{level: integer}`, `0 <= level <= 3`, S1, topic `commands/hvac`)
và đặt trần `le=3` cho `HvacState.fan_level`.**

Bốn quyết định con, mỗi cái đều có thể chọn khác:

### 1. Giữ tên `fan_level`, **không** đổi sang `fan_speed_percent`

COVESA VSS chuẩn hóa `FanSpeed` là `uint8` percent `0..100` (`0 = off`, `100 = max`), và
`mqtt_spec.md` từng ghi rằng nếu P1 thêm tool thì nên theo hướng đó.

Vẫn không đổi bây giờ, vì đổi tên field là **breaking change** trên `GET /api/v1/vehicle/state`,
`state/hvac` và `state/snapshot` — FE đang đọc `fan_level`. Gộp việc đổi thang vào cùng PR mở tool
là trộn hai thay đổi độc lập.

Để lại cho P1, và khi đó phải làm **cùng lúc** với `doors.locked` + `trunk.locked` để cả hệ thống
chỉ chịu **một** lần breaking thay vì ba.

### 2. Dải `0..3`, tự quy định, ghi rõ là tự quy định

Sổ tay VF9 **không công bố** thang quạt tối đa — chỉ chứng minh được mức 1 tồn tại (chế độ Nap
Mode). Nên không lấy sổ tay làm căn cứ được, và cũng không được giả vờ là có căn cứ.

Cùng tiền lệ và cùng cách ghi với dải `16..30 °C`: VSS cũng không áp min/max cho
`HVAC.Station.*.Temperature` vì dải là đặc thù từng hãng.

`0` = tắt quạt, khớp `"tắt quạt gió"` ở router.

### 3. Trần `le=3` là **bắt buộc**, không phải trang trí

`_Strict` bật `validate_assignment`, nên trần này là thứ chặn simulator gán giá trị vô nghĩa khi
dải ở registry lệch dải ở state. Bỏ trần đi thì `set_hvac_fan_level` validate ở registry nhưng
state nhận bất kỳ số nào — đúng loại lệch mà `validate_assignment` sinh ra để bắt.

### 4. S1 ở **mọi** trạng thái xe

Quạt gió không phải actuator có rủi ro cơ học như cửa hay ghế, nên không vào
`_STATIONARY_ONLY_TOOLS`. Chỉnh quạt lúc đang lái là thao tác bình thường; bắt xác nhận sẽ là
phiền nhiễu không mua được an toàn nào.

## Consequences

### Được

- Slider quạt gió của FE có đường nối thật.
- Lỗi báo-sai-lý-do biến mất: nhánh quạt xét **trước** nhánh nhiệt độ trong `_match_hvac`, nên
  `"chỉnh quạt gió điều hòa mức 3"` ra `set_hvac_fan_level {level: 3}`.
- Bề mặt điều khiển: 11 → 12 tool, 8 → 9 actuator tool. Số domain **không đổi** (vẫn 7) vì quạt
  thuộc `hvac` sẵn có — đây là lý do quyết định này rẻ hơn hẳn việc thêm đèn/cốp.

### Mất — ghi rõ, không lấp

**Router chỉ nhận mức tuyệt đối.** `"tăng quạt gió"` / `"giảm quạt gió"` trả `clarify` /
`missing_fan_level`, không phải `control`.

`DeterministicControlRouter.route()` chỉ nhận một chuỗi văn bản và **không** đọc vehicle state —
đó là thiết kế chứ không phải thiếu sót: router phải tất định và không side effect, còn state
thuộc `VehicleGateway` (ADR-013). Muốn "tăng một mức" thì phải biết mức hiện tại.

Client phải tự tính mức rồi gửi số, y như FE đã làm sẵn cho nhiệt độ
(`` `bật điều hòa ${next} độ` ``) và sưởi ghế (`` `chỉnh sưởi ghế lái mức ${...}` ``). Bàn giao ở
[`TASK-BE-FE-004`](../tasks/TASK-BE-FE-004-issue-65-command-vocabulary.md) §2.

**Thang `0..3` sẽ phải đổi ở P1** nếu theo VSS. Ghi trước ở đây để lúc đó không ai tưởng là quyết
định mới.

## Alternatives considered

**Giữ read-only, gỡ slider ở FE.** Rẻ nhất, và là lựa chọn đúng nếu quạt gió nằm ngoài phạm vi.
Bị loại vì `hvac` đã là domain có sẵn nên chi phí thêm tool rất thấp (không domain mới, không
schema state mới, không quyết định an toàn mới), trong khi lỗi báo-sai-lý-do ở mục Context thì
vẫn còn nguyên kể cả khi gỡ slider — nó là lỗi của router, không phải của FE.

**Cho router đọc vehicle state để xử lý `"tăng/giảm"`.** Bị loại: phá tính tất định của router,
và tạo đường thứ hai đọc state ngoài `VehicleGateway` — đúng thứ ADR-013 sinh ra để đóng lại.

**Đổi sang `fan_speed_percent 0..100` ngay bây giờ.** Bị loại: xem quyết định con số 1. Không phải
vì hướng đó sai — nó đúng — mà vì thời điểm sai.

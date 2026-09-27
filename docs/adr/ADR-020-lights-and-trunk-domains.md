# ADR-020: Thêm domain `lights` và `trunk`; đèn là enum chế độ, không có `off`

- Status: Accepted
- Date: 2026-08-12
- Decision owner: WS3 Virtual Vehicle & MQTT (Sơn)
- Liên quan: [issue #65](../tasks/TASK-FE-BE-002-real-mode-control-gaps.md),
  [ADR-004](ADR-004-mqtt-vehicle-simulator.md) (digital twin),
  [ADR-010](ADR-010-canonical-tool-registry-with-product-vision-adapter.md) (bác ngưỡng `speed_kph > 5`),
  [ADR-019](ADR-019-fan-level-becomes-controllable.md), `docs/safety_and_hitl.md`

## Context

Issue #65 báo FE đã dựng nút cốp và nút đèn nhưng router/registry không xử lý được. Khác với
quạt gió (ADR-019, nằm gọn trong domain `hvac` sẵn có), hai nhóm này cần **domain MQTT mới** —
tức đụng vào `Domain` literal, 4 JSON schema, `VehicleState`, simulator, policy, và 6 tài liệu
canonical.

**Cốp thì đơn giản. Đèn thì bế tắc.**

Bế tắc của đèn: *bật* đèn và *tắt* đèn có rủi ro ngược nhau khi xe đang chạy.

| | Xe đứng yên | Xe đang chạy ban đêm |
|---|---|---|
| **Bật** đèn | vô hại | vô hại, thậm chí cần thiết |
| **Tắt** đèn | vô hại | **nguy hiểm** |

Mà `policy.classify(tool, snapshot)` chỉ nhận **tool** và **trạng thái xe** — không nhận `args`.
Ba cách xếp đèn vào ba nhóm sẵn có đều hỏng:

- `_S1_TOOLS` → `"tắt đèn pha"` ở 80 km/h thực thi im lặng.
- `_ALWAYS_S2_TOOLS` → vào hầm phải bấm xác nhận mới bật được đèn, vô dụng đúng lúc cần.
- `_STATIONARY_ONLY_TOOLS` → không bật được đèn khi đang lái, tức hỏng chức năng chính.

Repo đã gặp đúng bài này với cửa và **cố ý chọn không phân biệt** — `vehicle_sim/state.py` ghi:
*"agent_spec.md xếp **cả tool** xuống S3 khi xe đang chạy, không phân biệt mở hay đóng."* Với cửa,
cái giá là "đang chạy thì không đóng được cửa bằng giọng nói" — chấp nhận được. Với đèn, cái giá
là "đang chạy thì không bật được đèn" — không chấp nhận được.

Lối thoát rõ ràng là cho `classify()` nhìn `args`, nhưng đó là đổi kiến trúc tầng an toàn cho
đúng **một** actuator, và `safety_and_hitl.md` liệt kê quy tắc **theo tool** chứ không có khái
niệm "theo args".

## Nghiên cứu

Trước khi đổi kiến trúc, khảo sát cách ngành model đèn. Bốn nguồn độc lập cho cùng một câu trả
lời: **đừng model đèn là boolean bật/tắt.**

| Nguồn | Nói gì |
|---|---|
| **High Mobility AutoAPI** [`lights.yml`](https://github.com/highmobility/auto-api/blob/master/capabilities/lights.yml) — nguồn `mqtt_spec.md` vốn đã dùng để đặt tên `front_left`/`front_right` | `front_exterior_light` là **enum 5 trạng thái**: `inactive`, `active`, `active_with_full_beam`, `drl`, `automatic`. Không phải bool. `switch_position` (cần gạt vật lý) là **read-only** |
| **Android Automotive** [`VehiclePropertyIds`](https://developer.android.com/reference/android/car/VehiclePropertyIds) | `HEADLIGHTS_SWITCH` là property **read-write**, quyền `PERMISSION_EXTERIOR_LIGHTS`, **không có interlock theo tốc độ**. Enum `VehicleLightSwitch`: `OFF=0, ON=1, DAYTIME_RUNNING=2, AUTOMATIC=0x100`. Tách `*_SWITCH` (lệnh, ghi được) khỏi `*_STATE` (thực tế, chỉ đọc) |
| **UNECE R48** | Xe có đèn chạy ban ngày (DRL) **bắt buộc** có đèn chiếu gần tự động theo ánh sáng môi trường, và **không được phép có chế độ OFF thủ công** |
| **Sổ tay VF9** — mục *Lái xe / Đèn ngoại thất*, `chunk_1147459_001..013` | Thuật ngữ chính thức: **đèn chiếu gần**, **đèn chiếu xa** (LED ma trận), **đèn sương mù** *(nếu có trang bị)*, hệ thống **ADB**. Ghi rõ: *"Điều khiển đèn pha của xe phải được đặt ở chế độ…"* — tức **chế độ**, không phải công tắc nguồn |

Với cốp:

| Nguồn | Nói gì |
|---|---|
| **AutoAPI** [`trunk.yml`](https://github.com/highmobility/auto-api/blob/master/capabilities/trunk.yml) | Tách `lock` (unlocked/locked) và `position` (open/closed) thành **hai property độc lập** |
| **FMVSS** — [Interior Trunk Release](https://www.federalregister.gov/documents/2002/04/22/02-9677/federal-motor-vehicle-safety-standards-interior-trunk-release) và tài liệu sáng chế liên quan | Ngưỡng an toàn tiêu chuẩn là **5 km/h**; cơ cấu chặn cơ khí điều khiển theo tín hiệu tốc độ |
| **Sổ tay VF9** — `chunk_1147139_002` | *"Chức năng khóa cửa tự động sẽ tự động khóa tất cả các cửa khi tốc độ xe vượt quá 10 km/h"* — chính chiếc xe này đã dùng interlock theo tốc độ |

## Decision

### 1. `lights.headlight` là **enum chế độ**, và **không có `off`**

```
headlight: "auto" | "low_beam" | "high_beam"
```

Thao tác nguy hiểm — *tắt đèn chiếu gần khi đang chạy ban đêm* — là thao tác mà **một chiếc xe
tuân thủ R48 không hề cung cấp**. VIVI cũng không cung cấp.

**Hệ quả: bế tắc phân loại an toàn tự tan biến.** Không còn thao tác nguy hiểm nào thì không còn
gì để chặn, nên `set_headlight_mode` và `set_interior_light` **đều là S1 ở mọi trạng thái xe** —
đúng như Android xếp `HEADLIGHTS_SWITCH` (read-write, không interlock tốc độ).

**`policy.classify()` giữ nguyên chữ ký `(tool, snapshot)`.** Không đổi kiến trúc tầng an toàn.

Đây là điểm quan trọng nhất của ADR này: vấn đề không được giải bằng cách làm tầng an toàn phức
tạp hơn, mà bằng cách **model đúng miền vấn đề**. Một tập giá trị hẹp hơn và trung thực hơn làm
cho quy tắc an toàn trở nên tầm thường.

`"tắt đèn pha"` trả `denied` / `headlight_off_not_permitted`. **Không** ánh xạ ngầm `"tắt"` →
`"auto"`: ánh xạ ngầm là làm một việc khác việc được yêu cầu mà không nói ra — đúng lớp lỗi
KI-001 mà `router.py` đã ghi hai lần là phải tránh.

**Nếu tương lai có ai thêm `off` vào enum thì phải quay lại ADR này trước.** Lúc đó bật và tắt
hết đối xứng về rủi ro, và toàn bộ lập luận "S1 ở mọi trạng thái" sụp đổ. Có case âm trong
`scripts/validate_mqtt_schemas.py` khẳng định `headlight="off"` bị schema từ chối, để việc nới
enum không thể xảy ra lặng lẽ.

### 2. Không có đèn sương mù ở P0

Sổ tay VF9 ghi *"(nếu có trang bị)"*. Đây đúng loại điều kiện biến thể mà ADR-015 đo được là
nguồn sai lệch (4/40 câu trả lời sai vì SLM bỏ mất điều kiện biến thể). Không khai một tính năng
phụ thuộc trim.

### 3. `trunk` là domain riêng, chỉ có `position`

Không nhét cốp vào `doors`: `DoorsState` có 4 khoá cố định và `set_door_state.door` là enum 4
cửa; thêm cốp vào đó phá cả hai. AutoAPI cũng để `trunk` là capability riêng.

**Không có `locked`** — cùng deferral và cùng lý do với `doors` (`mqtt_spec.md` "Quyết định P0 số
4"): registry P0 không có tool khóa/mở khóa nên `locked` sẽ là hằng số không ai ghi và không ai
đọc. P1 thêm `locked` cho **cả** cửa lẫn cốp trong **một** lần breaking change.

### 4. Cốp: S2 khi đứng yên / S3 khi đang chạy — chép nguyên quy tắc của cửa

`requires_stationary=True`, predicate `speed_kph == 0 && gear == "P"`.

Không phát minh gì: ngành dùng ngưỡng 5 km/h, chính VF9 tự khóa cửa trên 10 km/h, và predicate
của repo **chặt hơn cả hai** — ADR-010 đã bác `speed_kph > 5` vì nó vừa lỏng hơn canonical ở cửa
sổ vừa nguy hiểm hơn ở cửa xe.

Cốp không có bất đối xứng như đèn: mở cốp lúc đang chạy thì nguy hiểm, còn đóng cốp lúc đang chạy
thì vô nghĩa (không ai ở đó mà đóng). Nên gộp cả tool là đúng.

## Consequences

### Được

- Bề mặt điều khiển: 7 → **9 domain** (8 nhận lệnh), 12 → **15 tool**, 9 → **12 actuator tool**.
- `coverage_matrix.md` nhóm 5 (Đèn) chuyển từ **✗ sang ◐** — nhóm đầu tiên thoát khỏi 0 kể từ khi
  bảng này tồn tại. Tổng kết đổi từ 5/11 thành **6/11**.
- `"mở cốp"` và `"mở cốp xe"` cho **cùng** kết quả. Trước đây `"mở cốp"` rơi vào RAG còn
  `"mở cốp xe"` bị `denied` — hai cách nói cùng một việc, hai kết quả khác nhau.

### Mất — ghi rõ, không lấp

**`GET /api/v1/vehicle/state` mọc thêm hai domain.** Thêm field, không đổi field cũ, nên **không
breaking với client đọc** — nhưng `vehicle_state_snapshot.schema.json` khai `lights`/`trunk` là
`required`, nên **là breaking với publisher**: mọi producer phải phát đủ. Trong repo chỉ có một
producer (`vehicle_sim`), nhưng bất kỳ fixture snapshot viết tay nào cũng phải cập nhật.

**Hệ quả vận hành, đã gặp thật khi làm PR:** simulator đang chạy từ **trước** thay đổi này vẫn
publish 7 domain, và backend mới từ chối snapshot của nó —
`Snapshot sai schema trên .../state/snapshot: 2` (hai field thiếu). Cache giữ `None`,
`GET /vehicle/state` trả 503 `no_snapshot_yet`, agent từ chối lượt bằng
`vehicle_state_unavailable`.

Vì `state/snapshot` **retained**, bản cũ nằm lì trên broker cho tới khi simulator mới ghi đè —
khởi động lại backend **không** chữa được, phải dựng lại chính simulator:

```powershell
docker compose up -d --build --force-recreate vehicle-simulator
```

Ghi ở [`TASK-BE-FE-004`](../tasks/TASK-BE-FE-004-issue-65-command-vocabulary.md) §5 để người vận
hành không phải tự chẩn đoán lại.

**Bỏ `cốp xe`/`cốp sau` khỏi `_UNSUPPORTED_TOKENS`** đổi hành vi của dataset tripwire: case
`A3-DEN-003` (`"Mở cốp sau"`, domain `unsafe`) từ `denied`/`none` thành `control`/`trunk_state`.
Người soạn dataset xếp cốp vào nhóm *unsafe*; quyết định này nói rằng cốp **là** actuator hợp lệ
và an toàn của nó do S2/S3 lo, không do danh sách chặn chuỗi lo.

**`"bật đèn"` trống trả `clarify`.** Có hai loại đèn (`headlight` và `interior`) nên câu trống là
mơ hồ thật. Theo nguyên tắc đầu `router.py`: thiếu slot thì hỏi lại, không đoán.

**FE phải đổi nút đèn từ toggle sang bộ chọn 3 chế độ.** Bàn giao ở
[`TASK-BE-FE-004`](../tasks/TASK-BE-FE-004-issue-65-command-vocabulary.md) §3.

## Alternatives considered

**Cho `classify()` nhận `args` và thêm nhóm phân loại thứ tư.** Đây là lối thoát hiển nhiên khi
bế tắc, và nếu không tìm ra R48 thì đã phải chọn nó. Bị loại vì: đổi chữ ký của điểm **duy nhất**
trong hệ thống được gán `safety_level`, thêm một khái niệm mới vào `safety_and_hitl.md`, tất cả
để phục vụ đúng một actuator — trong khi cái làm bế tắc là **model sai miền vấn đề**, không phải
tầng an toàn thiếu năng lực.

**Model đèn là `{enabled: boolean}` rồi xếp S2 luôn.** Đơn giản nhất về code. Bị loại: bắt xác
nhận mỗi lần bật đèn là vô dụng đúng lúc cần nhất (vào hầm, trời tối đột ngột), và vẫn không giải
được chuyện tắt đèn khi đang chạy — chỉ đổi từ "nguy hiểm" sang "phiền".

**Ánh xạ `"tắt đèn pha"` → `mode: "auto"`.** Rất hấp dẫn: giữ được nút toggle của FE, và trên xe
thật vị trí "off" của cần gạt **đúng là** chế độ auto. Bị loại vì hệ thống sẽ làm một việc khác
việc người dùng nói mà không báo — KI-001. Người dùng nói "tắt", hệ thống làm "tự động", và không
ai biết đã có sự thay thế.

**Nhét `trunk` vào `doors` như khoá thứ năm.** Bị loại: phá enum 4 cửa của `set_door_state`, và
đi ngược AutoAPI vốn để trunk là capability riêng.

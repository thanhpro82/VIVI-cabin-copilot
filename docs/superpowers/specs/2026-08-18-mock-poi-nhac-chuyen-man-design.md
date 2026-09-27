# Thiết kế: POI mock, nhạc cục bộ, và chuyển màn bằng giọng nói

> Nguồn của thiết kế này là khảo sát [`docs/reports/mock-poi-nhac-chuyen-man-2026-08-17.md`](../../reports/mock-poi-nhac-chuyen-man-2026-08-17.md)
> và phạm vi cuối do Sơn chốt ngày **2026-08-18**. Mọi `file:line` dưới đây đọc từ
> `develop` @ **`579113c`** — bản đầu viết theo `f3c2a5d`, và đợt merge áp suất lốp
> (#168) chèn ~56 dòng vào giữa `router.py`, nên số dòng đã được tính lại. Các file
> khác mà thiết kế này chạm (`ivi_events.py`, `policy.py`, `tool_registry.py`,
> `execute.py`, `vehicle_sim/state.py`, toàn bộ `frontend/`) **không** bị đợt đó sửa.

## Mục tiêu

Cho tài xế nói một câu và thấy IVI **tự nhảy sang đúng màn hình** đang nói tới —
điều khiển xe, nhạc, bản đồ, hoặc một trong ba app giải trí — với dữ liệu mock đủ
dày để diễn được (5 địa điểm có lộ trình, 5–6 bài nhạc có ảnh bìa), và **không làm
rộng thêm** vết phụ thuộc mạng lúc chạy.

## Phạm vi

**Trong phạm vi**

| # | Hạng mục |
|---|---|
| 1 | 5 POI mock kèm route/ETA mock |
| 2 | POI fixture dùng chung BE/FE |
| 3 | 5–6 bài nhạc cục bộ kèm ảnh bìa/nền |
| 4 | Sửa lệch tên bài giữa playlist BE và bảng tra FE |
| 5 | Tự chuyển màn theo giọng nói: `vehicle` / `music` / `map` |
| 6 | `open_app`: `youtube` / `tiktok` / `spotify` |
| 7 | `plan.ready` mang `steps[]` |
| 8 | FE sở hữu bảng ánh xạ `domain`/`tool` → view |
| 9 | Chặn app video khi xe đang chuyển động |
| 10 | Asset offline cho bản đồ và nhạc ở chế độ demo |

**Ngoài phạm vi** — Google Maps hay routing thật; tìm kiếm POI thật; chọn bài bằng
tên; gợi ý/tìm kiếm nhạc; mở app tuỳ ý; URL tuỳ ý; nội dung
YouTube/TikTok/Spotify offline; **backend biết tên màn hình của frontend**.

## Nguyên tắc ranh giới, và nó chặn cái gì

> **Backend nói *cái gì vừa xảy ra*, không bao giờ nói *hiện màn nào*.**

BE phát `domain: "hvac"`; FE tự quyết `hvac → view "vehicle"`. Nếu BE phát thẳng
`view: "vehicle"` thì đổi layout là phải sửa backend và sửa test backend. Đây cũng
đúng tiền lệ `ui.policy` (`src/services/ui_policy.py`): BE đưa cờ chính sách, FE
quyết cách hiển thị.

Hệ quả trực tiếp: `ViewName` (`frontend/src/components/ivi/DriverShellProvider.tsx:40`)
là **kiểu của frontend**. Nó không được xuất hiện trong bất kỳ payload nào của
backend, không được nằm trong `docs/api_spec.md`, và không được là giá trị của một
enum Python.

---

## 1. POI fixture dùng chung

Nguồn sự thật là **một** file: `src/fixtures/poi.json`.

**Vì sao trong `src/` chứ không dưới `data/`** — bản đầu của thiết kế này ghi
`data/fixtures/`, và nó sai: `.gitignore:39` có dòng `data/` **không neo đầu**, nên nó
khớp mọi thư mục tên `data` ở mọi độ sâu; fixture đặt ở đó sẽ không bao giờ được commit
và không ai nhận ra cho tới lúc CI đỏ trên máy khác. `src/safety/ap_suat_lop.py:53-57`
đã gặp đúng bẫy này và ghi lại. Thiết kế này chép nguyên cách làm đó.

```jsonc
{
  "schema_version": "1.0",
  "items": [
    {
      "id": "poi-cafe-01",
      "name": "Highlands Coffee Nguyễn Trãi",
      "category": "cafe",
      "aliases": ["cà phê", "highland", "highlands", "hai len"],
      "lat": 21.0031, "lon": 105.8201,
      "distance_km": 3.4, "eta_min": 12,
      "polyline": [[21.0045, 105.8412], [21.0038, 105.8305], [21.0031, 105.8201]]
    }
  ]
}
```

Năm nhóm theo yêu cầu: `cafe`, `restaurant`, `mall`, `entertainment`, `charging`.

Fixture có **sáu** item chứ không phải năm: hai id kế thừa `poi-cafe-01` và
`poi-cafe-02` đều là quán cà phê, nên phủ đủ năm nhóm mà vẫn giữ được cả hai thì phải
thêm ba item mới. Một dòng dữ liệu thừa rẻ hơn nhiều so với việc làm hỏng ba test và
một câu trong `demo_runbook.md`.

**Ba ràng buộc, mỗi cái có lý do cụ thể:**

1. **Giữ nguyên ba id đang chạy** — `poi-cafe-01`, `poi-cafe-02`, `poi-charge-01`.
   Đổi id là làm hỏng `tests/test_agents/test_router.py:900-903`,
   `tests/test_agents/test_tools.py:66`, và câu *"Dẫn đường tới quán cà phê"* đang
   nằm trong `docs/demo_runbook.md:100`. Thêm hai id mới, không đụng ba cái cũ.
2. **BE đọc thẳng file nguồn; FE đọc bản sao `frontend/src/lib/fixtures/poi.json` do
   script sinh** — Next.js không import được file ngoài thư mục project của nó. Đặt
   ở `src/lib/` chứ không `public/` để file được bundle theo import, nên chế độ
   offline không phải fetch. Bản sao là thứ *sinh ra*, không phải thứ *viết tay*.
3. **Một test so byte hai bản.** Chép tay hai bản sẽ lệch đúng vào ngày ai đó sửa
   một bên — cùng lớp lỗi với credential MQTT bị chép lại mà
   `docs/reports/mqtt-control-surface-acceptance-2026-08-15.md` đã ghi. Bản sao
   không có test canh thì không còn là một nguồn sự thật.

Mỗi bên chỉ đọc trường mình cần: BE dùng `id` + `aliases`; FE dùng `name`,
`lat`/`lon`, `polyline`, `distance_km`, `eta_min`.

## 2. Router: đọc fixture, và nới matcher

Seam **đã có sẵn** từ trước:

```python
# src/agents/router.py:297-298
def __init__(self, poi_fixture: list[dict[str, Any]] | None = None) -> None:
    self._poi_ids = {str(item["id"]) for item in (poi_fixture or []) if "id" in item}
```

Nhưng `src/agents/graph.py:311` khởi tạo `DeterministicControlRouter()` **không
tham số**, nên `_poi_ids` luôn rỗng và guard `poi_not_in_fixture` (`router.py:944`)
chưa từng chạy một lần nào ở runtime. Thiết kế này truyền fixture vào đúng seam đó.

Hai thay đổi trong `_match_navigation` (`router.py:928-947`):

- **Bảng alias sinh từ fixture** thay ba `if` hard-code ở `router.py:935-940`. Alias
  khớp trên chuỗi đã qua `normalize_vi`, và cần nhiều biến thể vì STT tiếng Việt
  trả ra nhiều cách viết cho cùng một tên riêng.
- **Nới động từ mở đầu.** Hôm nay `router.py:929` đòi đúng chuỗi `"dẫn đường"`, nên
  *"tìm đường đến Highlands"* và *"đưa tôi tới trạm sạc"* rơi xuống mặc định và **đi
  tra sổ tay** theo ADR-011 — hệ thống im lặng làm sai việc. Thêm `tìm đường`,
  `đưa tôi tới`, `đi tới`.

**Thứ tự các bước của `_match` là nội dung ADR-011 — không đảo.** Đừng đếm số bước:
`develop` @ `579113c` vừa chèn thêm một bước `tire_pressure_query` (`router.py:329-341`)
đặt trước `is_information_question`, nên con số "sáu bước" trong các tài liệu cũ đã lạc
hậu. Nới matcher dẫn đường là **thêm từ khoá vào một bước đã có**, không phải chèn bước
mới — khác hẳn việc `tire_pressure_query` đã làm, và đó là lý do việc này không cần ADR
riêng.

Câu có động từ dẫn đường nhưng không khớp alias nào vẫn trả `clarify` /
`unknown_local_destination` như hiện tại. Fixture làm guard `poi_not_in_fixture`
sống lại: nó bắt trường hợp alias trỏ tới một id đã bị xoá khỏi fixture.

## 3. `plan.ready` mang `steps[]`

`_emit_plan_ready` (`src/services/ivi_events.py:276-306`) hiện phát bốn trường.
Thêm một:

```python
"steps": [
    {"step_id": s.step_id, "tool": s.tool, "domain": get_spec(s.tool).domain, "args": s.args}
    for s in plan.steps
],
```

`ToolSpec.domain` đã có sẵn (`src/services/tool_registry.py:119`), nên không phải
bịa bảng tra mới ở tầng event.

**Vì sao mở rộng payload thay vì thêm event thứ 17:** allowlist là tập đóng có tài
liệu (`docs/api_spec.md:565`); thêm loại mới bắt mọi client phải biết loại mới, còn
thêm trường vào loại đã có thì client cũ bỏ qua được. `real.ts:240-248` đọc theo tên
trường nên trường lạ không làm nó vỡ.

**Vì sao có `args` — Sơn chốt thêm trường này ngày 2026-08-18.** Phạm vi ban đầu ghi
`steps[{stepId,tool,domain}]`. Ba trường đó **không đủ cho `open_app`**:
tool là `open_app`, `domain` là `None`, nên FE không biết mở YouTube hay Spotify.
Ba lối ra:

| Lối | Được | Mất |
|---|---|---|
| **Thêm `args`** *(chọn)* | Một tool, một enum đóng; MapView đọc luôn `destination_id` | Payload rộng hơn phạm vi đã ghi một trường |
| Ba tool `open_youtube`/`open_tiktok`/`open_spotify` | Giữ đúng `{stepId,tool,domain}` | Bề mặt P0 nới **ba** tool thay vì một; `coverage_matrix.md` phình |
| Nhét `app:youtube` vào `domain` | Không thêm trường | `Domain` là enum lái topic MQTT — bịa giá trị giả vào đó là làm hỏng ADR-013 |

Chọn `args` vì nó **không lộ thêm gì**: `summary` trong cùng event này đã được ghép
từ `describe_step(step.tool, step.args)` (`ivi_events.py:302`,
`src/agents/nodes/compose.py:154`), tức nội dung args vốn đã nằm trong event dưới
dạng câu chữ. Đổi từ prose sang cấu trúc không mở rộng bề mặt lộ dữ liệu.

**Về `schema_version`:** `docs/api_spec.md:565` viết *"Additional fields are rejected
unless the negotiated schema version allows them"*. Không có validator nào ở runtime
thực thi câu đó cho event chiều ra — `src/api/ws.py` chỉ allowlist message **chiều
vào** (`ws.py:69`). Nên cách xử lý đúng là **cập nhật bảng allowlist ở
`api_spec.md:574`** để `steps` thành trường bắt buộc của `plan.ready` tại `1.0`,
**không** bump version: chưa có client nào phát hành ngoài repo này, và bump là chi
phí cho một vấn đề không tồn tại.

## 4. Chuyển màn: mốc là `tool.result`, KHÔNG phải `plan.ready`

Đây là điểm thiết kế quan trọng nhất của tài liệu này.

`plan.ready` thuộc **giai đoạn định tuyến**, phát **trước** khi rẽ nhánh chính sách
— chính docstring của `_emit_plan_ready` (`ivi_events.py:281-284`) nói thế, và đó là
lý do nó bắn cho cả lượt S3. Nếu FE chuyển màn ngay khi nhận `plan.ready` thì:

> Nói *"mở YouTube"* khi xe đang chạy 45 km/h → FE nhảy sang màn YouTube → policy
> mới chặn S3 → `action.blocked`. **Video đã bật rồi mới bị chặn.** Luật an toàn trở
> thành trang trí.

Vì vậy hợp đồng chuyển màn là **hai nhịp**:

1. Nhận `plan.ready` → FE **ghi nhớ** `steps` theo `stepId`, **không** đổi màn.
2. Nhận `tool.result` với `status == "completed"` → tra `stepId` trong bảng vừa nhớ
   → ánh xạ `domain`/`tool` → view → **lúc này mới** `setActiveView`.

Lượt bị chặn không bao giờ sinh `tool.result` completed, nên không bao giờ chuyển
màn. Lượt cần duyệt HITL chỉ chuyển màn sau khi tài xế bấm Đồng ý — đúng mong đợi,
miễn phí, không cần thêm luật nào.

Bảng ánh xạ nằm **hoàn toàn ở FE**:

```
hvac | seat | windows | doors | lights | trunk   → "vehicle"
media                                            → "music"
navigation                                       → "map"
open_app + args.app ∈ {youtube,tiktok,spotify}   → view cùng tên
```

Bước không ánh xạ được thì **không đổi màn** — im lặng, không lỗi. Plan nhiều bước
thì lấy bước completed **đầu tiên** có ánh xạ; câu ghép *"bật điều hòa rồi mở nhạc"*
dừng ở `vehicle` thay vì nháy hai màn.

Logic hai nhịp đặt trong một hook riêng (`frontend/src/lib/ivi/useAutoViewSwitch.ts`),
**không** nhồi vào `DriverShellProvider.tsx`. Lý do là vận hành, không phải thẩm mỹ:
nhánh `feat/vivi-browser-wake-word` đang sửa cùng file đó **+257 dòng** và chưa merge —
giữ diff của ta ở 2-3 dòng thì không ai phải giải xung đột tay. Chi tiết ở plan, Task 6.

## 5. `open_app` — tool mới, nới bề mặt P0

### Đăng ký

```python
ToolSpec("open_app", None, "S1", OpenAppArgs, requires_stationary=True)
```

`args`: `app: Literal["youtube", "tiktok", "spotify"]`. **Enum đóng** — "mở app tuỳ
ý" và "URL tuỳ ý" nằm ngoài phạm vi, và enum đóng là cách *cấu trúc dữ liệu* nói ra
điều đó thay vì trông cậy vào ý chí người viết code sau này.

`domain=None` như `search_nearby_poi` (`tool_registry.py:115`): không có gì trên xe
đổi trạng thái, nên không có topic MQTT.

**S1, không phải S0.** Khảo sát đề xuất S0; tôi đổi. S0 trong `docs/safety_and_hitl.md`
là **chỉ đọc** — `_S0_TOOLS` hiện đúng một phần tử `get_vehicle_state`
(`src/agents/policy.py:20`). `open_app` *làm* một việc. Xếp nó S0 là bắt taxonomy
S0–S3 nói dối, đúng lớp lỗi mà `policy.py:98` đã cảnh báo ở chiều ngược lại.

### Phân loại an toàn

```python
_STATIONARY_ONLY_S1_TOOLS = {"open_app"}   # src/agents/policy.py
...
if tool in _STATIONARY_ONLY_S1_TOOLS:
    return "S1" if is_stationary(snapshot) else "S3"
```

Dùng lại **đúng** predicate `is_stationary` (`policy.py:49-57`): `speed_kph == 0`
**và** `gear == "P"`. Chặt hơn "xe đang chuyển động" — dừng đèn đỏ ở số D vẫn bị
chặn. Đó là chủ ý: các hãng khoá video theo **số P**, không theo tốc độ, và dùng lại
predicate có sẵn thì không phát minh ngưỡng thứ hai trong cùng một hệ. Ngưỡng
`speed_kph > 5` của `docs/VIVI_API_Spec.md` vẫn **không** được cài, đúng ADR-010.

Khác cửa/ghế/cốp ở chỗ: chúng là **S2 khi đứng yên** (phải xin phép), `open_app` là
**S1 khi đứng yên** (chạy thẳng). Mở YouTube lúc đỗ xe không đáng một hộp thoại.

### Thực thi — tool cục bộ, không đi qua MQTT

`execute_node` (`src/agents/nodes/execute.py:59`) hiện đẩy **mọi** bước vào
`gateway.execute`, và `gateway.execute` (`src/services/vehicle_gateway.py:179-215`)
dựng `VehicleCommand` rồi gọi `simulator.execute`, nơi tool không có nhánh xử lý sẽ
ném `ToolNotAllowedError` (`src/vehicle_sim/state.py`). `open_app` phải rẽ **trước**
đó:

> Bước có `get_spec(tool).domain is None` **không** gọi gateway. `execute_node` tự
> dựng `ToolResult(status="completed")` với
> `observed_state_version = expected_state_version` (không quan sát thấy gì đổi —
> cùng cách `_skipped` đang làm ở `execute.py:56`), rồi đi tiếp.

Đây là seam **"tool cục bộ của IVI"**. Nó cố tình nhỏ và cố tình nằm ở
`execute_node` chứ không ở simulator: đưa lựa chọn app vào simulator nghĩa là phải
đẻ một domain MQTT mới cho một thứ **không phải trạng thái xe**, làm hỏng ADR-013
(*một nguồn trạng thái xe duy nhất*) để đổi lấy đúng con số không.

Đây cũng là seam mà `search_nearby_poi` sẽ dùng nếu sau này có người cài nó — nhưng
tài liệu này **không** cài nó, và `docs/demo_runbook.md:211` vẫn khai đúng rằng use
case "tìm cà phê → HVAC → dẫn đường" chưa chạy.

### Router

Luật mới trong `_match`, đặt **trước** bước mặc định rơi về tra sổ tay: động từ
`mở`/`bật`/`vào` + tên app trong enum → `open_app`. Không có tên app thì **không**
khớp (rơi về hành vi hiện tại), không đoán.

Vị trí chèn tính theo `develop` @ `579113c`: **sau** bước `tire_pressure_query`
(`router.py:329-341`) và sau `is_information_question` — *"mở YouTube"* không phải câu
hỏi, nó thuộc nhóm luật điều khiển.

Luật phải **hẹp**, và đây là bài học vừa trả giá ở review #168: `mở/bật/vào + tên app`
trần sẽ bắt cả *"mở YouTube xem hướng dẫn thay lốp"* — một câu tra sổ tay. Đúng lớp lỗi
@thanhpro82 đã bắt ở bản đầu của luật áp suất lốp, và cách sửa cùng hình dạng: thêm một
vế thu hẹp, không nới rộng bắt bừa.

### Nới bề mặt P0 — thủ tục bắt buộc

`docs/coverage_matrix.md` đang khai 15 tool / 9 domain. Thêm `open_app` là **nới bề
mặt P0**, mà `CLAUDE.md` bắt phải lập luận trong `api_spec.md` + `coverage_matrix.md`.
Tiền lệ gần nhất là issue #123 (`GET/PUT /vehicle/profile`). Cần:

- **ADR-023** — `open_app` và luật chặn app video khi xe không ở P.
- Cập nhật `docs/api_spec.md` (bảng interface + bảng allowlist event).
- Cập nhật `docs/coverage_matrix.md`: **16 tool / 9 domain** — domain **không** tăng,
  vì `open_app` không có domain. Số nhóm lệnh thoại quy ước vẫn là 6/11.
- ~~**Thành (PM/PO) duyệt** trước khi merge.~~ **Đã duyệt** — @thanhpro82 trên issue #172,
  2026-08-19, kèm một ràng buộc thêm: **S3 không được HITL override** (xem ADR-023).

## 6. Nhạc: playlist CC0 và asset cục bộ

### Lệch tên bài — sửa bằng cách bỏ bản chép tay

Playlist backend (`src/vehicle_sim/state.py:55-60`) là *"Nối vòng tay lớn"*,
*"Mưa hồng"*, *"Hà Nội mùa vắng những cơn mưa"*. Bảng tra frontend (`MusicView.tsx`,
`TRACK_SRC_BY_NAME` / `TRACK_BG_SEED`) là *"Nhạc nhẹ buổi sáng"*, *"Bolero chọn lọc"*,
*"Piano không lời"* — **không khớp một tên nào**. Ở real mode BE trả
`track = "Mưa hồng"`, FE tra không thấy, rơi về `DEFAULT_TRACK_SRC` và
`DEFAULT_BG_SEED`: bấm next/previous **đổi được tên trên UI nhưng luôn phát đúng một
file và luôn hiện đúng một ảnh**. Bảng đó viết cho mock
(`frontend/src/lib/services/turn/mock.ts:186`) và chưa ai đối chiếu lại sau khi real
mode bật — cùng lớp lỗi với UAT-004.

Sửa **không** bằng cách chép tên cho khớp, mà bằng cách bỏ hẳn bản chép tay:
`src/fixtures/media.json` là nguồn, `DEFAULT_PLAYLIST` đọc từ đó, `MusicView` đọc
bản sao đồng bộ — cùng cơ chế và cùng test so byte như POI ở §1.

### Playlist CC0

5–6 bài **CC0 hoặc CC-BY**, dùng **đúng tên gốc** của bản CC0 đó, kèm
`frontend/public/media/LICENSE.md` ghi nguồn và giấy phép từng file.

Lý do bắt buộc: ba tên hiện tại là nhạc Trịnh Công Sơn / Phú Quang. Hôm nay chúng
chỉ là chuỗi hiển thị nên vô hại; **hạng mục 10 của phạm vi là host file mp3 thật
trong repo**, và gắn file vào đúng những cái tên đó là host nhạc có bản quyền trong
một repo học thuật. Đổi tên ở bước dữ liệu thì rẻ; đổi sau khi ảnh bìa đã làm xong
thì đắt.

`_step_track` (`state.py`) xoay vòng theo `len(self._playlist)` nên **không cần sửa
logic** để đi từ 3 lên 6 bài.

### Hợp đồng media không đổi

Phạm vi chốt **chỉ** `next` / `previous` / `play` / `pause` (cộng `set_volume` đã
có). Nên **không đụng** `MediaControlArgs`, **không đụng**
`schemas/mqtt/vehicle_command.schema.json`, **không đụng** hợp đồng simulator. Router
`_match_music` (`router.py:738-764`) đã bắt đủ bốn hành động và **không cần sửa**.
Chọn bài theo tên nằm ngoài phạm vi.

## 7. Asset offline và chế độ demo

Mọi tài nguyên hiển thị đi qua **một** hàm, ngay từ commit đầu tiên:

```ts
// frontend/src/lib/assets.ts
const OFFLINE = process.env.NEXT_PUBLIC_OFFLINE_ASSETS === "true";
export function assetUrl(local: string, remote: string): string {
  return OFFLINE ? local : remote;
}
```

Cờ tắt → hành vi y hệt hôm nay. Cờ bật → đọc file trong `frontend/public/`. Không
component nào biết cờ tồn tại; sau này đổi chiến lược chỉ sửa một file.

| Tài nguyên | Chế độ demo (cờ bật) |
|---|---|
| Nhạc + ảnh bìa | File cục bộ trong `frontend/public/media/` — CC0, có `LICENSE.md` |
| Nền bản đồ | **Một ảnh raster tĩnh** + `L.ImageOverlay`, không phải thư mục tile |
| YouTube / TikTok / Spotify | **Ảnh tĩnh + nhãn "cần mạng"** — nội dung offline của ba app nằm ngoài phạm vi |

**Vì sao bản đồ là một ảnh tĩnh chứ không phải thư mục tile:** ToS của CARTO
(`LeafletMap.tsx:9`) và của OSM đều **cấm tải hàng loạt tile**. Một ảnh xuất hợp lệ
cho đúng vùng demo, kèm attribution, cho cùng kết quả hình ảnh mà không đụng ToS và
không thêm vài trăm file vào repo. Route mock vẫn vẽ được: `polyline` trong fixture
là toạ độ, chỉ cần một phép chiếu cố định lên ảnh nền.

### Ba nút app vẫn giữ, và phải được khai báo

Ba tile YouTube / Spotify / TikTok ở `frontend/src/components/ivi/HomeView.tsx:28-30`
**giữ nguyên** (chúng ở màn Home, không phải ở `Dock.tsx:9-13` — Dock chỉ có bốn
mục). Bấm tay vẫn vào iframe thật khi có mạng.

Đổi lại, phải thêm một dòng vào bảng **"Ranh giới không được hứa"** của
`docs/demo_runbook.md` §3: nội dung ba app là iframe cần mạng, chế độ demo chỉ hiện
ảnh tĩnh.

Và sửa `docs/release/demo-3-phut.md` màn 0:00–0:15 — hiện đang nói *"chạy hoàn toàn
offline… không gọi ra mạng"* trong khi FE phụ thuộc sáu host ngoài lúc chạy
(`basemaps.cartocdn.com`, `soundhelix.com`, `picsum.photos`, `youtube.com/embed`,
`i.ytimg.com`, `open.spotify.com/embed`). Câu đúng là: **lõi xử lý** chạy offline;
**phần trang trí** dùng tài nguyên web, trừ khi bật chế độ demo. Chỉ được nâng lại
lời hứa "hoàn toàn offline" **kèm bằng chứng** — rút mạng, quay màn hình — chứ không
nâng bằng lời, đúng kỷ luật status của `README.md`.

---

## Xác minh

| Hạng mục | Cách chứng minh |
|---|---|
| Fixture một nguồn | Test so byte `src/fixtures/*.json` với bản sao trong `frontend/src/lib/fixtures/` |
| Router + POI | Case mới trong `tests/test_agents/test_router.py`; ba id cũ ở `:900-903` vẫn xanh |
| `poi_not_in_fixture` sống lại | Test chạy qua `graph`, không chỉ dựng router trực tiếp như `test_router.py:924` |
| `plan.ready.steps` | `tests/test_services/test_ivi_events.py` + `frontend/.../turn/mock.test.ts` |
| Chuyển màn đúng nhịp | Test FE: `plan.ready` **không** đổi màn; `tool.result(completed)` mới đổi |
| Chặn video khi xe chạy | Test policy `open_app` → S3 khi `speed_kph=45`; test E2E: **không** có `tool.result` completed, **không** đổi màn |
| `open_app` không chạm MQTT | Test `execute_node`: bước `domain=None` không gọi `gateway.execute` |
| Playlist | Test BE playlist = fixture; test FE mọi tên đều có file và ảnh, không rơi default |
| Không hồi quy | `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q` và `cd frontend; npm run test` |

## Việc phải làm ở tài liệu

- **ADR-023** — `open_app`, enum đóng, S1/S3 theo `is_stationary`.
- `docs/api_spec.md` — bảng interface; bảng allowlist event dòng `plan.ready` (`:574`).
- `docs/coverage_matrix.md` — 16 tool / 9 domain.
- `docs/demo_runbook.md` §3 — ranh giới ba app.
- `docs/release/demo-3-phut.md` — hạ câu "hoàn toàn offline".
- `WORKLOG.md` và `JOURNAL.md` khi công việc hạ cánh.

## Kế hoạch thi công

Chia task, thứ tự, và lệnh xác minh: [`../plans/2026-08-18-mock-poi-nhac-chuyen-man.md`](../plans/2026-08-18-mock-poi-nhac-chuyen-man.md).

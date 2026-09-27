# ADR-023: `open_app` vào bề mặt P0; app giải trí bị chặn khi xe không ở số P

- Status: **Accepted** — @thanhpro82 (PM/PO) duyệt trên [issue #172](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/172), 2026-08-19
- Date: 2026-08-18
- Decision owner: WS3 Virtual Vehicle & Router (Sơn)
- Liên quan: phạm vi chốt 2026-08-18 (mục 6 và 9),
  [thiết kế](../superpowers/specs/2026-08-18-mock-poi-nhac-chuyen-man-design.md),
  [kế hoạch](../superpowers/plans/2026-08-18-mock-poi-nhac-chuyen-man.md),
  [ADR-010](ADR-010-canonical-tool-registry-with-product-vision-adapter.md) (bác ngưỡng `speed_kph > 5`),
  [ADR-011](ADR-011-default-route-to-manual-lookup.md) (mặc định rơi về tra sổ tay),
  [ADR-013](ADR-013-single-vehicle-state-source.md) (một nguồn trạng thái xe),
  [ADR-020](ADR-020-lights-and-trunk-domains.md) (tiền lệ nới domain),
  `docs/safety_and_hitl.md`, `docs/coverage_matrix.md`

## Context

Phạm vi 2026-08-18 yêu cầu: nói qua mic thì IVI tự chuyển sang đúng màn, kể cả ba app
giải trí YouTube / TikTok / Spotify. Ba màn đầu — điều khiển, nhạc, bản đồ — đi kèm
**miễn phí**, vì mỗi lệnh xe đã mang sẵn một `domain` và frontend chỉ cần ánh xạ nó.
Ba app kia thì không: **chúng không phải lệnh xe**. Không domain MQTT, không actuator,
không có gì trên xe đổi trạng thái.

Hai câu hỏi phải trả lời, và chúng độc lập nhau.

**Câu 1 — có nới bề mặt P0 không?** `docs/coverage_matrix.md` đang khai 15 tool /
9 domain, và `CLAUDE.md` bắt mọi việc nới phải được lập luận trong `api_spec.md` +
`coverage_matrix.md`. Tiền lệ gần nhất là issue #123 (`GET/PUT /vehicle/profile`).

Không nới thì **không phải là giữ nguyên hiện trạng**. Theo ADR-011, câu không khớp
luật nào **rơi về tra sổ tay**: hôm nay nói *"mở YouTube"* thì hệ thống đi tra 482
chunk sổ tay VF9 rồi trả lời gì đó, hoặc *"không tìm thấy"*. Nó **im lặng làm sai
việc** — đúng lớp lỗi mà ADR-020 đã từ chối khi bác cách ánh xạ ngầm `"tắt đèn"` →
`auto`.

**Câu 2 — mức an toàn nào?** Mở video khi xe đang chạy là phân tâm người lái. Nhưng
`open_app` không giống bất kỳ tool nào đang có:

| | Cửa / ghế / cốp | Kính | `open_app` |
|---|---|---|---|
| Khi đứng yên | S2 — phải xin phép | S2 | **?** |
| Khi đang chạy | S3 — chặn | S2 | **?** |
| Có actuator trên xe | có | có | **không** |

Bắt tài xế bấm xác nhận để mở YouTube lúc **đang đỗ** là vô nghĩa — không có gì
nguy hiểm để mà cân nhắc. Nhưng để nó chạy thẳng khi **đang lái** thì đúng thứ mà
mọi hướng dẫn về phân tâm người lái đều cấm.

## Nghiên cứu

Trước khi tự đặt luật, khảo sát cách ngành xử lý. Ba nguồn độc lập cho cùng một hình
dạng câu trả lời: **khoá theo *trạng thái* xe (đỗ hay không), không theo một con số
tốc độ.**

| Nguồn | Nói gì |
|---|---|
| **Android Automotive — `CarUxRestrictions`** ([`UX_RESTRICTIONS_NO_VIDEO`](https://developer.android.com/reference/android/car/drivingstate/CarUxRestrictions)) | Có hẳn một hạn chế **riêng cho video**, tách khỏi các hạn chế khác (nhập chữ, nội dung dài). Hạn chế được kích hoạt theo [`CarDrivingStateEvent`](https://developer.android.com/reference/android/car/drivingstate/CarDrivingStateEvent), mà trạng thái **không bị hạn chế** là `DRIVING_STATE_PARKED` — tức cổng là **một trạng thái rời rạc**, không phải một ngưỡng km/h |
| **NHTSA — Visual-Manual Driver Distraction Guidelines for In-Vehicle Electronic Devices** (2013) | Xếp hình ảnh động / video không phục vụ việc lái vào nhóm **per-se lockout**: phải bị khoá khi xe đang vận hành, không phải chỉ cảnh báo |
| **Sổ tay VF9** — *Màn hình, Kết nối và Điều hòa / Màn hình cảm ứng* (`data/manuals/vf9_2026_vi/html/07_.../27_Màn hình cảm ứng.html`) | Xe có **màn hình cảm ứng phía trước** với "khu vực hệ thống giải trí", **và** một **màn hình cảm ứng phía sau** dành cho hành khách hàng ghế thứ 2 (bản 6 chỗ). Tức trong xe thật, luật khoá là luật của **màn hình người lái**, không phải của cả xe |

Và một nguồn nội bộ, quan trọng không kém:

| Nguồn | Nói gì |
|---|---|
| **ADR-010 + `src/agents/policy.py:49-57`** | Repo đã có **đúng một** predicate canonical cho "xe an toàn để thao tác": `is_stationary` = `speed_kph == 0` **và** `gear == "P"`. Ngưỡng `speed_kph > 5` của `docs/VIVI_API_Spec.md` đã bị ADR-010 bác và **không được cài** |

Ba nguồn ngoài nói "gate theo trạng thái đỗ"; nguồn trong đã có sẵn đúng một predicate
biểu diễn trạng thái đỗ. Không cần phát minh gì.

## Decision

**1. `open_app` vào bề mặt P0, với enum đóng ba app.**

```python
ToolSpec("open_app", None, "S1", OpenAppArgs, requires_stationary=True)
# OpenAppArgs: app: Literal["youtube", "tiktok", "spotify"]
```

Enum đóng, **không** phải `str`, và **không** có tham số URL. "Mở app tuỳ ý" và "URL
tuỳ ý" nằm ngoài phạm vi; enum đóng là cách *cấu trúc dữ liệu* nói ra điều đó, thay
vì trông cậy vào ý chí của người viết code sau này.

Ba màn `vehicle` / `music` / `map` **không** nằm trong enum: chúng đã có lệnh xe thật
mang `domain`, nên thêm chúng vào đây là hai đường vào cho cùng một kết quả.

**2. S1 khi xe ở P, S3 khi không.**

```python
_STATIONARY_ONLY_S1_TOOLS = {"open_app"}   # src/agents/policy.py
...
if tool in _STATIONARY_ONLY_S1_TOOLS:
    return "S1" if is_stationary(snapshot) else "S3"
```

- **S1, không phải S0.** S0 trong `docs/safety_and_hitl.md` là **chỉ đọc** — `_S0_TOOLS`
  hiện đúng một phần tử `get_vehicle_state`. `open_app` *làm* một việc. Xếp nó S0 là
  bắt taxonomy S0–S3 nói dối, đúng lớp lỗi mà `policy.py:98` đã cảnh báo ở chiều ngược
  lại (không nâng S1 thành S2 chỉ vì nguồn gốc SLM).
- **S1, không phải S2.** Mở YouTube lúc xe đỗ không đáng một hộp thoại phê duyệt.
- **Dùng lại `is_stationary`, không đẻ ngưỡng mới.** Nó chặt hơn "xe đang chuyển động":
  dừng đèn đỏ ở số D vẫn bị chặn. Đó là chủ ý — Android khoá theo `DRIVING_STATE_PARKED`
  chứ không theo tốc độ, và một hệ chỉ nên có **một** định nghĩa "an toàn để thao tác".

**Ràng buộc PM thêm lúc duyệt (@thanhpro82, 2026-08-19): S3 ở đây không được HITL
override.** Xe không ở P thì lệnh mở video bị chặn thẳng, không được biến thành một hộp
thoại *"bạn có chắc không"*. Cấu trúc hiện tại đã cho điều đó miễn phí — `safety_node`
xét S3 **trước** `requires_approval` nên S3 không bao giờ đi tới nhánh phê duyệt — nhưng
"miễn phí hôm nay" không phải là "được bảo vệ": phải có một test khoá đúng mệnh đề ấy,
nếu không một lần refactor tầng an toàn sẽ mở lại cửa mà không ai thấy.

**3. `open_app` không đi qua MQTT — nó là tool cục bộ của IVI.**

`domain=None`, như `search_nearby_poi` (`tool_registry.py:115`). `execute_node` rẽ
nhánh cho mọi bước có `get_spec(tool).domain is None`: tự dựng
`ToolResult(status="completed")` với `observed_state_version = expected_state_version`,
**không** gọi `gateway.execute`, **không** dựng `VehicleCommand`.

Đưa lựa chọn app vào simulator sẽ phải đẻ một domain MQTT mới cho một thứ **không phải
trạng thái xe**, làm hỏng ADR-013 (*snapshot của simulator là nguồn trạng thái xe duy
nhất*) để đổi lấy đúng con số không.

**4. Backend không biết tên màn hình.** `open_app` phát ra *danh tính app*; frontend
tự quyết màn nào hiện nó. `ViewName` là kiểu của frontend và không được xuất hiện
trong payload, enum Python, hay `docs/api_spec.md`. Cùng tiền lệ `ui.policy`: BE đưa
cờ chính sách, FE quyết cách hiển thị.

**5. Việc chuyển màn bám `tool.result(completed)`, không bám `plan.ready`.**

Đây là nửa còn lại của luật an toàn, và không có nó thì mục 2 chỉ là trang trí.
`plan.ready` thuộc **giai đoạn định tuyến**, phát **trước** khi rẽ nhánh chính sách
(`ivi_events.py:281-284`), nên nó bắn cho cả lượt S3. Nếu FE đổi màn khi nhận
`plan.ready` thì nói *"mở YouTube"* ở 45 km/h sẽ **mở video xong rồi mới bị chặn**.

Lượt bị chặn không bao giờ sinh `tool.result` completed ⇒ không bao giờ chuyển màn.

## Consequences

**Được:**

- Câu *"mở YouTube"* có một kết cục **được thiết kế**, thay vì rơi về tra sổ tay và
  trả lời một thứ không ai hỏi.
- Có thêm một màn demo cùng cấu trúc với màn cốp: *cùng một lệnh, hai kết cục tuỳ
  trạng thái xe* — cấu trúc đã chứng minh hiệu quả ở `demo-3-phut.md` Màn 4 vs Màn 6.
- `execute_node` có seam cho **tool cục bộ**. `search_nearby_poi` sẽ dùng đúng seam
  này nếu sau này có người cài nó. ADR này **không** cài nó, và `demo_runbook.md:211`
  vẫn khai đúng rằng use case "tìm cà phê → HVAC → dẫn đường" chưa chạy.

**Mất / phải chấp nhận:**

- `docs/coverage_matrix.md` thành **16 tool / 9 domain**. Số domain **không** tăng —
  `open_app` không có domain. Số nhóm lệnh thoại quy ước vẫn **6/11**: mở app giải
  trí không nằm trong 11 nhóm đó.
- `policy.classify` có nhóm thứ năm. Nhóm này là nhóm đầu tiên **không** map 1-1 giữa
  mức an toàn và việc có actuator, nên comment tại chỗ phải nói rõ vì sao.
- **Chặt hơn thực tế người dùng mong đợi:** dừng đèn đỏ ở số D không mở được YouTube.
  Chấp nhận, vì nới lỏng một luật an toàn về sau dễ hơn siết chặt về sau, và vì dùng
  chung predicate là thứ giữ cho hệ chỉ có một định nghĩa "an toàn".
- **Không phân biệt được màn trước / màn sau.** Sổ tay VF9 cho thấy xe thật có màn
  sau cho hành khách, nơi luật này lẽ ra không nên áp. P0 chỉ có **một** IVI nên câu
  hỏi đó chưa tồn tại — ghi lại ở đây để người sau không tưởng là đã cân nhắc xong.
- **L2/L3 không phủ được `open_app`**, vì nó không đi qua broker. Bằng chứng phải đến
  từ test policy (S1/S3), test `execute_node` (không gọi gateway), và test FE (lượt
  bị chặn không đổi màn) — không phải từ `report_mqtt_e2e.py`.

## Alternatives considered

| Phương án | Vì sao bác |
|---|---|
| **Không làm gì** — để ADR-011 rơi về tra sổ tay | Hệ thống im lặng làm sai việc. Cùng lớp lỗi mà ADR-020 đã bác ở `"tắt đèn"` → `auto` |
| **S0** (như khảo sát 2026-08-17 đề xuất) | S0 là *chỉ đọc*. `open_app` làm một việc. Xếp S0 là bắt taxonomy nói dối |
| **S2 khi đứng yên** (giống cửa/ghế/cốp) | Hộp thoại phê duyệt để mở YouTube lúc đỗ là nghi thức rỗng; nghi thức rỗng làm tài xế bấm Đồng ý theo phản xạ, làm yếu chính cơ chế HITL ở những chỗ nó thật sự cần |
| **Ngưỡng `speed_kph > 0`** thay vì `is_stationary` | Đẻ định nghĩa "an toàn để thao tác" thứ hai trong cùng một hệ. Android khoá theo trạng thái đỗ, không theo tốc độ |
| **Ba tool** `open_youtube` / `open_tiktok` / `open_spotify` | Giữ được `steps[{step_id,tool,domain}]` ba trường, nhưng nới bề mặt P0 **ba** tool thay vì một, và mỗi app mới sau này lại thêm một tool |
| **Bịa domain `app`** để `open_app` có domain | `Domain` là enum lái topic MQTT. Nhét giá trị không có thật vào đó là làm hỏng ADR-013 để lấy sự gọn gàng hình thức |
| **Đưa lựa chọn app vào simulator** | Lựa chọn app không phải trạng thái xe. Xem mục 3 |

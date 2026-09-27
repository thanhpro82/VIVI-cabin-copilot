# TASK-BE-ROUTINES-283 — Domain và contract địa điểm Nhà/Cơ quan theo user

- Issue: [#283](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/283), outcome [#273](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/273), epic [#270](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/270)
- Nguồn sản phẩm: `docs/routines_product_spec.md` §Nhà và Cơ quan
- Phụ thuộc: #282 (bảng `user_places` và store Routine)
- Trạng thái: **Chạy được trên PC** — 25 test mới xanh, full suite `2864 passed, 22 skipped`

## Phạm vi đã làm

| Thành phần | File |
|---|---|
| Hai POI mới trong tập đóng | `src/fixtures/poi.json` — `poi-home-01`, `poi-work-01` |
| Nhóm `personal` + bảng nhãn→POI gợi ý | `src/fixtures/__init__.py` |
| Store: gán/đọc/bỏ gán/resolve | `src/services/user_places.py` |
| Ba path REST | `src/api/place_routes.py` |
| Resolve nhãn khi dịch Routine | `src/agents/routines.py::_navigation` |
| `needs_setup` đọc nhãn **còn hợp lệ** | `src/services/routines_store.py` |

## Hợp đồng HTTP

| Method | Path | Trả |
|---|---|---|
| GET | `/api/v1/places` | `{home, office}` — cả hai khoá luôn có mặt, `null` = chưa gán |
| PUT | `/api/v1/places/{label}` | trạng thái mới của cả hai nhãn |
| DELETE | `/api/v1/places/{label}` | 204, idempotent |

Mã lỗi: `PLACE_LABEL_UNKNOWN` (404 — nhãn lạ là tài nguyên không tồn tại, không phải body
sai), `PLACE_DESTINATION_INVALID` (422 — id ngoài fixture offline).

## Ba trạng thái phải phân biệt được

| Client thấy | Nghĩa |
|---|---|
| `null` | chưa gán |
| `{valid: true, name: "Cơ quan"}` | dùng được |
| `{valid: false, name: null}` | đã gán, nhưng đích biến mất khỏi fixture |

Gộp hai ca cuối thành `null` sẽ làm màn thiết lập (#284) không nói được vì sao lựa chọn cũ
biến mất, và người dùng chọn lại mà không hiểu chuyện gì vừa xảy ra.

## Bốn quyết định đáng đọc trước khi sửa

**1. Hai POI mới không có alias, và đó là hàng rào an toàn.** Cho `poi-home-01` alias
`"nhà"` thì *"đi về nhà"* dẫn tới **một toạ độ dùng chung cho mọi tài khoản**, bỏ qua
mapping cá nhân — đúng thứ spec cấm, và `set_navigation` là S1 nên nó đi qua mà không ai
duyệt. Đường hợp lệ duy nhất tới hai POI này là qua `user_places`.
`test_poi_ca_nhan_khong_co_alias_nao` khoá điều đó.

**2. `personal` tách khỏi `POI_CATEGORIES`.** Hằng ấy là các nhóm **tìm được bằng lời**;
gộp `personal` vào sẽ nói rằng có một loại địa điểm tìm được bằng lời mà thực ra không.

**3. Người dùng chọn được bất kỳ POI nào trong tám.** `POI_CA_NHAN_THEO_NHAN` chỉ là gợi
ý cho UI, không phải giới hạn — spec chốt "chọn trong tám điểm cố định", nên gán Nhà vào
`poi-cafe-01` là hợp lệ. Có test khoá để không ai "siết cho chặt" thành ràng buộc spec
không đòi.

**4. Đích biến mất ⇒ chưa thiết lập, nhưng hàng vẫn còn.** Không tự xoá dữ liệu người
dùng; `valid=False` và `nhan_da_gan()` loại nó ra, nên Routine dẫn đường quay về
"Cần thiết lập" — đúng ca spec nêu riêng.

## Nối với phần khác

- `routine_thanh_candidate(steps, dia_diem=...)` nhận ánh xạ nhãn → `destination_id` **đã
  kiểm hợp lệ**. Module dịch vẫn không chạm DB; người gọi (#286) dựng ánh xạ từ
  `user_places.resolve`.
- `routines_store._dia_diem_da_gan` uỷ cho `user_places.nhan_da_gan` thay vì tự
  `SELECT label` — một hàng trỏ POI đã biến mất vẫn có `label`, nên phép đếm thô sẽ báo
  "đã thiết lập" cho một Routine không chạy được.

## Chưa làm, và ai làm

- **UI thiết lập Nhà/Cơ quan** → #284.
- **Dùng ánh xạ này lúc chạy Routine** → #286 (`admission` + execution).
- **`frontend/src/lib/fixtures/poi.json`** đã đồng bộ trong PR này (test so từng byte),
  nhưng chưa có màn hình nào đọc hai POI mới.

## Cách kiểm chứng

```powershell
$env:MQTT_ENABLED="false"
.\.venv\Scripts\python.exe -m pytest tests/test_services/test_user_places.py tests/test_api/test_place_routes.py tests/test_services/test_fixtures.py -q
```

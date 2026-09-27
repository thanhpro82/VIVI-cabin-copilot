# Bản đồ IVI — nút "Bắt đầu" không làm gì, và lộ trình là đường chim bay

> **Status: đã đo trên máy dev 2026-08-21.** Mọi con số lấy trực tiếp từ
> `frontend/src/components/ivi/MapView.tsx`, `LeafletMap.tsx`,
> `frontend/src/lib/fixtures/poi.json`, `src/vehicle_sim/state.py` và `git blame`.
> Bảng OSRM ở §3 là kết quả gọi thật `router.project-osrm.org` cho cả 6 POI, không ước lượng.
>
> Câu hỏi khởi nguồn — @nguyenGiaps, 20/08 23:36:
> *"Map đang bị lỗi phần này với chữ bắt đầu ko ấn được. Kiểu như trong ggmap ấn chữ
> bắt đầu thì nó hiện lộ trình đi ấy."*
> Cộng thêm: *"có cách nào cải tiến để nó hiện đường gấp khúc thay vì đường chim bay không?"*

## Kết luận một dòng

Nút **ấn được** — không có lớp nào che nó — nhưng **không có `onClick`**, và ở hợp đồng xe
hiện tại nó cũng **không có việc gì để làm**, vì `navigation.status` đã là `active` từ lúc
câu lệnh thoại thực thi. Đường thẳng là do polyline trong fixture chỉ có **3–4 điểm viết tay**;
sửa bằng cách nướng tuyến OSRM thật vào fixture, **không cần tải gì và không phá invariant offline**.

---

## 1. Nút "Bắt đầu" — không phải bị che, mà không có handler

`frontend/src/components/ivi/MapView.tsx:77-82`:

```tsx
<button
  type="button"
  className="pointer-events-auto ml-auto rounded-xl bg-cyan px-5 py-2.5 ..."
>
  Bắt đầu
</button>
```

`git blame` cho thấy nút đến từ commit `75fd913` (09/08) — lần port nguyên bố cục từ file
mockup HTML — và **chưa từng được nối dây**. `MapView.test.tsx` cũng không có test nào chạm tới nó.

Bốn giả thuyết "bị che" đều đã loại trừ:

| Nghi vấn | Kết quả |
|---|---|
| Lớp phủ đè lên (VoiceOverlay / HitlModal / Toast) | Cả ba `return null` khi không hoạt động — không chặn |
| `pointer-events-none` của thanh ETA cha | Nút có `pointer-events-auto`, click vẫn tới nơi |
| z-index của Leaflet nuốt mất | Thanh ETA ở `z-[1100]`, Leaflet tối đa 1000 — nút nằm trên |
| Luật CSS trong `globals.css` vô hiệu hoá | Khối `.leaflet-*` không chạm tới nút |

Đúng như mô tả: **ấn được, nhưng không có gì xảy ra.**

### Điểm quan trọng hơn: hiện chưa có trạng thái nào để nút bấm vào

`src/vehicle_sim/state.py:342-352` chỉ có hai trạng thái `idle` / `active`, và `set_navigation`
đặt `active` **ngay lúc thực thi câu lệnh thoại**. Nghĩa là lúc thanh ETA hiện ra thì xe đã
"đang dẫn đường" rồi — **không** có trạng thái "đã chọn tuyến, chờ bấm Bắt đầu" như Google Maps.
Nên đây là quyết định thiết kế, không phải sửa một dòng:

- **(a) Bỏ nút đi** — trung thực nhất với hợp đồng hiện tại, 0 dòng backend.
- **(b) Giữ nút, cho nó chạy mô phỏng phía FE** — bấm thì chấm cyan trượt dọc polyline theo
  `eta_min`, ETA đếm ngược. Thuần frontend, không đụng MQTT, demo nhìn "sống" hẳn.
  Đổi lại **phải ghi vào `docs/demo_runbook.md`** rằng đó là animation, không phải GPS.
- **(c) Thêm trạng thái `planned` vào `NavigationState`** — giống Google Maps thật, nhưng là
  sửa hợp đồng xe: `src/models/vehicle.py`, simulator, schema MQTT, test L1/L2. Không đáng cho P0.

---

## 2. "Đường chim bay" — đo được, không phải cảm giác

Polyline là **viết tay 3–4 điểm** trong `poi.json`, và các "khúc cua" nhỏ tới mức mắt không thấy:

| POI | Số điểm | Dài polyline | Chim bay | Góc bẻ lớn nhất | `distance_km` khai báo |
|---|---|---|---|---|---|
| poi-cafe-01 | 4 | 4.29 km | 4.29 km | 2.1° | **3.40** |
| poi-cafe-02 | 3 | 2.23 km | 2.23 km | 1.8° | **2.10** |
| poi-charge-01 | 4 | 4.67 km | 4.66 km | 3.9° | **4.00** |
| poi-food-01 | 3 | 2.23 km | 2.23 km | 0.1° | **2.60** |
| poi-mall-01 | 3 | 1.20 km | 1.20 km | 0.0° | **1.80** |
| poi-fun-01 | 3 | 0.91 km | 0.91 km | 0.0° | **1.50** |

Dài polyline **bằng đúng** đường chim bay tới 2 chữ số thập phân. Và con số km in trên màn hình
lệch tới **+65%** (poi-fun-01: vẽ 0.91 km, ghi 1.50 km) — nhãn đang nói dối so với đường đang vẽ.

### Lỗi thứ ba, tìm thấy khi soi cùng chỗ

`LeafletMap.tsx:37` đặt vị trí xe lúc rảnh là `[21.0285, 105.8048]`, còn **mọi** polyline đều
bắt đầu ở `[21.0045, 105.8412]`. Chấm cyan **nhảy 4.63 km** ngay khi bắt đầu dẫn đường.
Comment ở dòng 33-36 có thừa nhận hai nguồn khác nhau, nhưng không nói khoảng cách lớn thế này.

---

## 3. Cách sửa đường gấp khúc

### Phương án A (khuyến nghị) — tính tuyến thật MỘT LẦN lúc dev, nướng vào fixture

Chỉ có 6 POI và một điểm xuất phát cố định. Gọi OSRM một lần trên máy, lưu polyline vào
`src/fixtures/poi.json`, chạy `pwsh scripts/sync_fixtures.ps1`. **Runtime vẫn zero network** —
giữ nguyên invariant offline của issue #176, không thêm service, và **không sửa một dòng nào**
của `LeafletMap.tsx` (component `Polyline` nhận bao nhiêu điểm cũng vẽ).

Đã chạy thử cả 6 POI qua OSRM public demo để chứng minh khả thi:

| POI | Điểm (`full`) | Điểm (`simplified`) | km thật | km đang khai | Trong bbox ảnh offline? |
|---|---|---|---|---|---|
| poi-cafe-01 | 144 | 13 | 5.60 | 3.40 | ✅ |
| poi-cafe-02 | 111 | 18 | 3.65 | 2.10 | ✅ |
| poi-charge-01 | 165 | 15 | 5.87 | 4.00 | ✅ |
| poi-food-01 | 84 | 11 | 3.10 | 2.60 | ✅ |
| poi-mall-01 | 77 | 7 | 3.13 | 1.80 | ✅ |
| poi-fun-01 | 83 | 6 | 3.09 | 1.50 | ✅ |

Lệnh đã dùng (dạng `lon,lat`, không phải `lat,lon`):

```
https://router.project-osrm.org/route/v1/driving/105.8412,21.0045;105.8010,20.9955?overview=simplified&geometries=geojson
```

Ba điều đáng chú ý:

- **Cả 6 tuyến đều nằm trong `OFFLINE_MAP_BOUNDS`** — không tuyến nào chạy ra ngoài ảnh nền
  chế độ demo. Mà kể cả có, `frontend/src/components/ivi/offlineMap.test.ts:22` đã có sẵn test
  bắt việc đó, nên rào chắn có rồi.
- **`overview=simplified` cho 6–18 điểm** — vừa đủ nhỏ cho fixture, vẫn gấp khúc theo phố.
  Nếu thấy cắt góc thô ở zoom cao thì lấy `full` rồi Douglas-Peucker khoảng 15 m.
- **Đừng lấy `duration` của OSRM làm `eta_min`.** Nó cho 4.0–7.5 phút vì profile mặc định là
  free-flow, không có kẹt xe Hà Nội. Giữ `eta_min` viết tay, nhưng **phải sửa `distance_km`**
  cho khớp tuyến mới, nếu không nhãn tiếp tục nói dối.

**Cần tải gì: không gì cả.** `curl` + `python` sẵn có là đủ. Không test nào hard-code giá trị
`distance_km` / `eta_min` (đã kiểm `tests/test_services/test_fixtures.py` và `MapView.test.tsx`),
nên đổi số là an toàn — chỉ nhớ chạy `sync_fixtures.ps1`, vì
`test_ban_sao_frontend_giong_nguon_tung_byte` so hai bản **từng byte**.

### Phương án B — tự dựng OSRM trong docker-compose

Định tuyến thật lúc chạy, vẫn cục bộ (không phải cloud). Cần tải `vietnam-latest.osm.pbf` từ
Geofabrik — **311,8 MB**, đo bằng `curl -sIL` ngày 21/08 — cộng image `osrm/osrm-backend`,
và bước `osrm-extract` ngốn vài GB RAM. Chỉ đáng nếu muốn điểm xuất phát/điểm đến động.
Với 6 POI cố định và **không có GPS thật**, đây là dùng dao mổ trâu — mà tuyến vẫn xuất phát
từ một toạ độ giả.

### Phương án C — gọi API định tuyến lúc runtime

Vi phạm invariant *"No network at runtime"* và làm hỏng chính chế độ offline mà #176 vừa dựng.
Không nên.

---

## 4. Đề nghị

Việc này **chưa có issue nào đang mở** (đã rà 12 issue open ngày 21/08). Nó nằm trong file của
@nguyenGiaps (`MapView.tsx`, `LeafletMap.tsx`), nên hợp lý nhất là mở **một issue gộp bốn thứ**,
vì cả bốn cùng nằm trong một lần sửa fixture + một quyết định về nút:

1. Nút "Bắt đầu" không có handler → chọn (a), (b) hay (c) ở §1.
2. Polyline là đường chim bay → phương án A ở §3.
3. `distance_km` lệch tới +65% so với đường đang vẽ.
4. Chấm xe nhảy 4,63 km khi bắt đầu dẫn đường (`IDLE_POSITION` vs điểm đầu polyline).

## Ngoài phạm vi

Google Maps thật, tìm kiếm POI thật, GPS thật từ vehicle simulator. Kể cả sau phương án A,
lộ trình vẫn xuất phát từ **một toạ độ demo cố định** — đừng nâng lời hứa lên "chỉ đường thật",
theo đúng kỷ luật status của `README.md`.

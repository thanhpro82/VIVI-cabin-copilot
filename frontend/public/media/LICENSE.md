# Giấy phép asset nhạc demo

Playlist trong `src/fixtures/media.json` — **5 bài** — là nhạc **Kevin MacLeod (incompetech.com)**,
phát hành theo **Creative Commons Attribution 4.0 (CC BY 4.0)** —
<https://creativecommons.org/licenses/by/4.0/>.

CC BY cho phép dùng và phân phối lại, kể cả thương mại, **với điều kiện ghi công**.
Ghi công không phải tuỳ chọn: `MusicView.tsx` hiển thị trường `attribution` của từng
bài ngay dưới tên bài, và file này là bản ghi đầy đủ.

| File | Bài | Ghi công |
|---|---|---|
| `carefree.mp3` | Carefree | Carefree — Kevin MacLeod (incompetech.com), CC BY 4.0 |
| `wallpaper.mp3` | Wallpaper | Wallpaper — Kevin MacLeod (incompetech.com), CC BY 4.0 |
| `local-forecast-elevator.mp3` | Local Forecast - Elevator | Local Forecast - Elevator — Kevin MacLeod (incompetech.com), CC BY 4.0 |
| `sneaky-snitch.mp3` | Sneaky Snitch | Sneaky Snitch — Kevin MacLeod (incompetech.com), CC BY 4.0 |
| `fluffing-a-duck.mp3` | Fluffing a Duck | Fluffing a Duck — Kevin MacLeod (incompetech.com), CC BY 4.0 |

## Ảnh bìa: sinh bằng code, không có file

Không có file ảnh bìa nào trong thư mục này, và đó là **quyết định**, không phải
thiếu sót — @thanhpro82 chốt ở PR #188.

incompetech không phát hành bìa cho sáu bài này, nên mọi ảnh dùng thay đều là ảnh
stock chẳng liên quan tới bài. `frontend/src/lib/ivi/trackCover.ts` sinh gradient
từ `track.id`: không thêm byte nào vào git, không có license phải khai, mỗi bài vẫn
có nền riêng và ổn định qua mọi lần chạy.

Gradient dựng **chỉ từ token màu có sẵn** trong `docs/DESIGN_TOKENS.md`, và cả sáu
nằm trong họ `--violet` — token dành riêng cho *nhạc trên máy*. Không mượn
`--accent` (cảnh báo), `--pink` (TikTok) hay `--green` (Spotify): bảng token gán
**ý nghĩa** cho màu, nên một bìa đỏ sẽ đọc thành "nguy hiểm".

Trường `cover` đã được **gỡ khỏi** `src/fixtures/media.json`. Một trường trỏ tới
file không tồn tại là cái bẫy cho người đọc sau.

## Ảnh nền bản đồ — `map-hanoi.webp`

Xuất **một ảnh** từ chức năng Share của <https://www.openstreetmap.org>. Cố ý không
tải bộ tile: ToS của cả CARTO lẫn OSM đều cấm tải hàng loạt, và một ảnh xuất hợp lệ
cho cùng kết quả hình ảnh.

- **Dữ liệu**: © OpenStreetMap contributors, ODbL — <https://www.openstreetmap.org/copyright>
- **Dòng ghi công nằm sẵn trong ảnh** ở góc dưới phải. **Không được crop.** Đó là lý do
  `ImageOverlay` phủ nguyên ảnh thay vì cắt cho vừa khung.

Bbox của ảnh, lấy từ đoạn nhúng HTML mà osm.org sinh ra (không phải số ước lượng):

| | |
|---|---|
| west | `105.76855659484865` |
| south | `20.9856431158777` |
| east | `105.86769104003906` |
| north | `21.035720685584845` |
| tâm / zoom | `21.01068 / 105.81812`, z15 |

Bốn số này được chép vào `OFFLINE_MAP_BOUNDS` (`LeafletMap.tsx`).
**Đổi ảnh thì phải đổi kèm bốn số** — `offlineMap.test.ts` kiểm mọi POI và mọi điểm
polyline có nằm trong vùng ảnh không, nhưng nó không biết được ảnh mới có đúng khung
cũ hay không.

Ảnh là **nền sáng**; `.vivi-offline-map` trong `globals.css` đảo màu cho hợp theme tối.
Đó là phép xấp xỉ, không phải style CARTO — nói rõ khi trình bày.

Bbox này được chép vào `OFFLINE_MAP_BOUNDS` (`LeafletMap.tsx`). **Đổi ảnh thì phải
đổi kèm bốn số** — `offlineMap.test.ts` kiểm mọi POI và mọi điểm polyline có nằm
trong vùng ảnh không, nhưng nó không biết được ảnh mới có đúng khung cũ hay không.

Ảnh là **nền sáng**; `.vivi-offline-map` trong `globals.css` đảo màu cho hợp theme
tối. Đó là phép xấp xỉ, không phải style CARTO — nói rõ khi trình bày.

---

## Trạng thái: đã commit đủ

| | |
|---|---|
| 5 × mp3 (96 kbps) | 9,6 MB |
| `map-hanoi.webp` 2718×1470 | 1,15 MB |
| ảnh bìa | 0 byte — sinh bằng code |

Bản tải về là 46,7 MB; nén còn dưới trần 15–25 MB mà @thanhpro82 duyệt ở #188.

`.gitattributes` nhận `*.mp3` và `*.webp` là binary **trước** file nhị phân đầu
tiên — thêm sau thì git đã kịp đoán sai và làm hỏng file trên máy
`core.autocrlf=true`, đúng bẫy mà `.wav` đã dính.

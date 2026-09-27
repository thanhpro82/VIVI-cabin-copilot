# SP-5 — Tìm địa điểm và dẫn đường — thiết kế

- Ngày: 2026-08-23
- Trạng thái: Đã duyệt qua brainstorming, chờ implementation plan
- Lộ trình: `2026-08-23-lo-trinh-agent-theo-kich-ban.md` §3 (SP-5, ưu tiên cao nhất)
- **Mua:** lượt 9 của kịch bản — *"Tìm quán cà phê gần đây rồi dẫn đường tới đó"*
- Liên quan: ADR-011 (mặc định về sổ tay), ADR-013 (snapshot xe là nguồn duy nhất), #171

## 1. Bối cảnh

Use case đầu bài của P0 — *tìm cà phê → chỉnh điều hòa → dẫn đường* — **chưa chạy dòng
nào**. Đo 23/08:

```
"Tìm quán cà phê gần đây"                      -> default_to_manual   (tra sổ tay!)
"Đưa tôi về nhà"                               -> default_to_manual
"Tìm quán cà phê gần đây rồi dẫn đường tới đó" -> clarify / unknown_local_destination
```

Khảo sát cho thấy phần lớn hạ tầng **đã có**, việc còn lại nhỏ hơn tưởng:

| Mảnh | Trạng thái |
|---|---|
| `src/fixtures/poi.json` — 6 POI, đủ `aliases`, toạ độ, `distance_km`, `eta_min`, **`polyline`** | ✅ có |
| Bản fixture của frontend | ✅ có, **giống hệt** bản backend (kiểm 23/08) |
| Bản đồ vẽ tuyến + hoạt ảnh (`LeafletMap.tsx`, `routeAnimation.ts`) | ✅ có |
| `set_navigation` — S1, domain `navigation`, có `args_model` | ✅ có |
| `_match_navigation` + `_tra_poi` (tra POI theo alias) | ✅ có |
| Đường thực thi cho tool **không domain** (`_ket_qua_tool_cuc_bo`) | ✅ có, `open_app` đang dùng |
| `search_nearby_poi` | ⚠️ **chỉ là một dòng registry**: S0, `args_model=None`, không matcher, không test |
| Matcher cho *"tìm … gần đây"* | ❌ không có |

Nên SP-5 **không** phải viết executor mới và **không** chạm frontend. Rủi ro "phải làm
bản đồ" ghi trong lộ trình là rủi ro không tồn tại.

## 2. Quyết định

### 2.1 Số ít thì đi, số nhiều thì hỏi *(chốt 23/08, Nhân)*

Dấu hiệu quyết định nằm ngay trong câu nói — **từ chỉ số nhiều**:

| Người nói | Hệ thống |
|---|---|
| *"Tìm quán cà phê gần đây"* | chọn quán **gần nhất**, đặt dẫn đường luôn, và **nói rõ đã làm gì** |
| *"Tìm **các** quán cà phê gần đây"* | đọc danh sách, **hỏi lại** muốn đi quán nào |

Từ chỉ số nhiều là tập đóng: `các`, `những`, `mấy`, `có bao nhiêu`.

**Đánh đổi đã cân nhắc.** Nhánh số ít biến một câu *tìm* thành một hành động *dẫn
đường* — làm nhiều hơn điều được yêu cầu. Chấp nhận vì `set_navigation` là **S1, đảo
ngược được, và không làm xe chuyển động**: nó đổi cái hiện trên bản đồ, không đổi trạng
thái vật lý nào. Khác hẳn mở cửa hay hạ kính.

**Nhưng phải kèm một điều kiện, không được bỏ:** câu trả lời **bắt buộc** nêu tên quán,
khoảng cách, và nói rõ đã chỉ đường — kèm lối thoát trong cùng một lượt:

> *"Quán gần nhất là Cà phê Bình Minh, cách 3,6 km, khoảng 8 phút. Tôi đã chỉ đường tới
> đó. Muốn quán khác thì bảo tôi nhé."*

Tự ý làm mà **không** nói ra mới là chỗ nguy hiểm; nói ra thì tài xế huỷ được bằng một câu.

### 2.2 *"Đưa tôi về nhà"* — ngoài phạm vi *(chốt 23/08, Nhân)*

"Nhà" là dữ liệu **của người dùng**, không phải POI công cộng; chỗ đúng của nó là hồ sơ
xe (`GET/PUT /vehicle/profile`, issue #123), không phải `poi.json`. SP-5 chỉ lo POI công
cộng. Ghi vào nợ, không làm ở đây.

### 2.3 Câu ghép *"tìm … rồi dẫn đường tới đó"* — xử trong MỘT matcher

Vế hai chứa một đại từ hồi chỉ (*"tới đó"*) trỏ về kết quả vế một. Xử đúng bài toán ấy
đòi giải hồi chỉ xuyên vế — một cơ chế mới trong `_segment_clauses`.

**Không làm thế.** Nếu câu **vừa** có mẫu *tìm … gần đây* **vừa** có động từ dẫn đường
kèm đại từ hồi chỉ (`đó`, `đấy`, `chỗ đó`), thì cả câu được đối xử như **nhánh số ít**
— tìm rồi dẫn đường tới cái gần nhất. Một matcher, không đụng cơ chế ghép vế của #225.

Giới hạn cố ý, ghi rõ: *"dẫn đường tới đó"* **đứng một mình** vẫn ra `clarify` như hôm
nay (không có gì để "đó" trỏ tới) — đúng hành vi mong muốn.

### 2.4 Không có bước trung gian mang dữ liệu

Nhánh số ít phát **một** bước `set_navigation(operation="start", destination_id=…)`.
Không phát kèm `search_nearby_poi` chỉ để "cho có dấu vết": router đã tra fixture ngay
lúc định tuyến, nên không có gì cần truyền giữa hai bước — và thêm luồng dữ liệu
giữa các step là thứ đắt nhất có thể thêm vào lúc này.

Nhánh số nhiều phát **một** bước `search_nearby_poi(category=…)` (S0). Composer đọc lại
fixture theo `category` để dựng câu — tất định, không cần `ToolResult` chở kết quả.

## 3. Kiến trúc

```
"Tìm quán cà phê gần đây"
   → router._match_tim_poi
       ├─ tra alias → category = "cafe"
       ├─ có từ chỉ số nhiều?
       │    KHÔNG → control, 1 bước set_navigation(start, destination_id=<gần nhất>)  [S1]
       │    CÓ    → control, 1 bước search_nearby_poi(category="cafe")                [S0]
       └─ không tra được alias → None (rơi xuống mặc định như cũ)
   → policy gán mức an toàn (không đổi)
   → execute: set_navigation qua MQTT; search_nearby_poi qua `_ket_qua_tool_cuc_bo`
   → compose: dựng câu từ fixture
```

**Không đụng:** `policy.py`, `execute.py`, frontend, `poi.json`.

### 3.1 `SearchNearbyPoiArgs`

```python
class SearchNearbyPoiArgs(_Args):
    category: Literal["cafe", "charging", "restaurant", "mall", "entertainment"]
```

Danh sách đóng, lấy đúng từ các `category` có thật trong `poi.json` — schema đóng chặn
model bịa ra loại địa điểm không tồn tại, cùng kỷ luật với mọi tool khác.

### 3.2 Helper tra fixture

```python
def tim_poi_theo_loai(category: str) -> list[dict]   # sắp theo distance_km tăng dần
def loai_poi_tu_alias(text: str) -> str | None       # alias trong câu → category
```

Đặt ở `src/fixtures/__init__.py` cạnh `poi_alias_map`. `loai_poi_tu_alias` dùng lại đúng
trật tự alias-dài-trước của `poi_alias_map` — trật tự ấy là hợp đồng, không phải chi tiết.

### 3.3 Câu trả lời

| Nhánh | Mẫu |
|---|---|
| số ít | *"Quán gần nhất là {tên}, cách {d} km, khoảng {t} phút. Tôi đã chỉ đường tới đó. Muốn quán khác thì bảo tôi nhé."* |
| số nhiều | *"Tôi tìm được {n} chỗ: {tên1} cách {d1} km, {tên2} cách {d2} km. Bạn muốn đi chỗ nào?"* |
| chỉ có một kết quả, dù nói số nhiều | dùng mẫu số ít (không hỏi khi không có gì để chọn) |

Đọc tối đa **3** kết quả — quá đó thì tài xế không nhớ nổi bằng tai.

## 4. Bằng chứng bắt buộc

- Bộ ca mới cho `eval/datasets/agent/v3` (hoặc tệp POI riêng): 6 loại × {số ít, số nhiều}
  + câu ghép + ca âm tính (*"tìm hiểu về áp suất lốp"* **không** được thành tìm POI).
- Cổng cứng giữ nguyên: chạy lại `--mode dinh-tuyen` (114 ca) và `--mode chitchat`,
  **`manual→control` phải vẫn = 0** — matcher mới là chỗ dễ làm vỡ ô đó nhất, vì nó
  thêm một đường cho câu hỏi trở thành lệnh.
- Lượt 9 chạy trọn trên giao diện thật, bản đồ hiện tuyến.

## 5. Ngoài phạm vi

- *"Đưa tôi về nhà"* và mọi địa điểm cá nhân (§2.2).
- Giải hồi chỉ xuyên vế nói chung (§2.3).
- Tìm theo bán kính/khoảng cách thật, POI động, bản đồ thật — fixture là fixture.
- Ghép ba ý (*tìm cà phê → chỉnh điều hòa → dẫn đường*): hạ tầng ghép vế đã có, nhưng
  bộ ca cho nó là việc riêng.

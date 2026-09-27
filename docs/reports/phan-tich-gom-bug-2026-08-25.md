# Gom 42 báo cáo lỗi (24/08) thành 8 nhóm nguyên nhân

**Ngày:** 2026-08-25 · **Người viết:** Sơn · **Nguồn:** bảng báo lỗi của Thành (39 dòng), Sơn (1), Giáp (2)
**Đo trên:** `develop` @ `bab0fc6` (sau khi merge #266), `.venv` = 3.11.9, gọi thẳng
`DeterministicControlRouter.route()` (không qua HTTP, không qua STT). `src/agents/router.py` vẫn dừng
ở `6e0b523` — #266 chỉ chạm `graph.py`, nên toàn bộ số đo dưới đây giữ nguyên (đã spot-check 14 câu
chốt sau khi pull).

> Mọi ô "Đo được" dưới đây là kết quả chạy thật ngày 25/08, không phải suy từ việc đọc code.
>
> Lượt đo đầu chạy trên nhánh `fix/slm-nhieu-nguoi-dung-dong-thoi`. Sau khi pull, `develop` hơn nhánh
> ấy **82 dòng trong `router.py`** (SP-5 POI + SP-2.1), nên **toàn bộ 70 câu đã được đo lại trên
> `develop`** — kết quả trùng khớp từng dòng, trừ phần POI ở §4/N7 đã đổi. Con số nào trong file này
> cũng là con số của `develop`, không phải của một nhánh nào khác.
>
> Đây **chưa** phải một run trong `eval/results/` — xem §6, việc đầu tiên là biến bảng này thành dataset.

---

## 1. Ba điều phải biết trước khi mở issue

**(a) Người test đang test bản deploy, không phải `develop`.** 7/42 dòng **không tái hiện được**
trên cây hiện tại — code đã có sẵn cách nói ấy. Bản chạy ở `c4-app-192.io.vn` bám `DEPLOY_REF=main`,
mà `main` đi sau `develop`. Mở issue cho những dòng này là mở issue cho một lỗi không tồn tại.

| Dòng | Câu | Đo được trên develop |
|---|---|---|
| T07 | `lạnh rồi tắt điều hòa giúp mình` | `control` → `set_hvac_power{enabled:false}` OK |
| T11 | `mở khoang hành lý` | `control` → `set_trunk_state{open}` OK |
| T12 | `mở cái cốp` / `đóng cái cốp lại` | `control` → `set_trunk_state{open/closed}` OK |
| T19 (một phần) | `dịch ghế lái về trước 70 phần trăm` | `control` → `fore_aft 70` OK |
| T20 (một phần) | `đặt độ ngả lưng ghế lái 50 phần trăm` | `control` → `recline 50` OK |
| T33 (một phần) | `đi đến vincom`, `đưa tôi tới cà phê bình minh` | `control` → `set_navigation{start}` OK |
| T39 | `có thể chỉnh độ cao ghế không` | `not_control` / `manual_question` OK (đúng như mong đợi) |

T07 chạy được vì một lý do **tình cờ**: `rồi` nằm trong `_CONJUNCTIONS` (`router.py:227`) nên câu bị
cắt thành `["lạnh", "tắt điều hòa giúp mình"]`. `nóng quá bật điều hòa...` không có liên từ nào nên
hỏng. Cùng một lớp lỗi, một câu sống một câu chết — đó chính là bằng chứng cho nhóm N1.

**(b) Một dòng bị mô tả nhẹ hơn thực tế, và nó là dòng nguy hiểm nhất.**
T09/T10 ghi "không route đúng sang front_left". Đo thật thì tệ hơn nhiều:

```
'mở cửa tài xế'     → control | 4 bước set_door_state: front_left, front_right, rear_left, rear_right
'mở cửa hành khách' → control | 4 bước set_door_state: cả bốn cửa
```

`_side()` (`router.py:1428`) không biết `tài xế`, nên trả `None`; `_match_door` (`router.py:1288`)
hiểu `None` là "nhắm cả xe" và sinh kế hoạch mở **cả bốn cửa**. Đây không phải rơi xuống RAG — đây là
một plan S2 **sai đích** đi tới HITL. Nó phải là ca đầu tiên được sửa.

**(c) Đường đi trong `router.py` đã thoáng hơn, nhưng chưa trống.** #252 (SP-5 POI & dẫn đường) và
#249 (SP-2.1 tiểu từ cuối câu) **đã merge vào `develop`** — hai PR từng chặn nay không còn chặn nữa.
Còn đúng **một** PR đang mở đụng `router.py`: **#268** (`"không"` phủ định bị đọc thành số 0). #267
đụng `question.py`, tức đụng gián tiếp qua nhánh nhận diện câu hỏi. Xem thứ tự ở §6.

#268 đáng đọc kỹ trước khi bắt tay, vì hai lý do. Thứ nhất nó là **thành viên mới của đúng họ lỗi
xếp hạng 1-4 ở §5**: `"mở cửa sổ bên lái không cần nhiều"` ra `percent 0`, tức **đóng** kính khi
người ta bảo **mở**. Thứ hai, nó đặt ra luật neo `NEO_SO_KHONG` cho chữ `không` — luật mà nhóm N5
bắt buộc phải dùng lại chứ không được tự nghĩ ra bản thứ hai.

Và một ghi chú từ #268 nên đọc như lời cảnh báo cho §6: ở đó có **một test xanh đang bảo vệ một hành
vi sai**, xanh suốt vì chỉ kiểm chiều không nguy hiểm. Suite xanh không chứng minh được gì cho 42 ca
này — dataset mới chứng minh được.

---

## 2. Bản đồ 42 dòng → 8 nhóm

| Nhóm | Dòng gốc | Số dòng |
|---|---|---|
| **N1** Tiền xử lý đầu câu (wake / filler / vế dẫn nhập) | T06, T26a, T30, T35 | 4 |
| **N2** Bảng động từ quá hẹp và không nhất quán giữa các matcher | T03, T04, T05, T13, T14, T15, T16, T17, T19b, T21, T23, T25, T29, T33b | 14 |
| **N3** Bảng alias đối tượng (domain / target / axis / mode) | T01, T02, T08, T09, T10, T18, T22, T24, T27, T28a | 10 |
| **N4** Câu hỏi năng lực bị trả `clarify` | T38 | 1 |
| **N5** Tự sửa lời trong cùng lượt (self-repair) | T37 | 1 |
| **N6** Media: phát theo tên bài + phải fail đúng | T31, T32, T28b | 2 |
| **N7** Dẫn đường — *đã tan sau khi #252 merge*: T34 xong, 3 câu còn lại chuyển vào N2 | T33a, T34 | 2 |
| **N8** *Quyết định sản phẩm*, không phải lỗi code: `Mở cửa` trần | T36 | 1 |
| **N9** STT nhầm phụ âm đầu | S01 | 1 |
| **N10** FE: đường thoại khi trả lời tới muộn | G01, G02 | 2 |
| — Không tái hiện trên `develop` (xem §1a) | T07, T11, T12, T19a, T20, T33c, T39 | 7 |

Hậu tố a/b/c = dòng gốc mô tả nhiều ca, và các ca ấy thuộc nhóm khác nhau.

---

## 3. N1–N3: ba mặt của **một** thiết kế — "động từ phải đứng ở ký tự số 0"

28/42 dòng quy về đúng một hàm sáu dòng:

```python
# src/agents/router.py:1440
@staticmethod
def _starts_with_command(text: str, *verbs: str) -> bool:
    command = _POLITE_PREFIX_PATTERN.sub("", text, count=1)
    return any(command == verb or command.startswith(f"{verb} ") for verb in verbs)
```

Neo tuyệt đối ở đầu chuỗi, chỉ bóc được `hãy|vui lòng|làm ơn|giúp tôi` (`router.py:36`). Đây là luật
cố ý của ADR-011 — docstring đầu file nói rõ: *"Mỗi matcher đòi hỏi cả từ khóa domain lẫn động từ điều
khiển ở đầu câu, để câu hỏi tra cứu không bị hiểu nhầm thành lệnh."* Luật ấy **mua** được
`question_reaches_RAG = 0.9833` trên `eval/datasets/manual/v1`. Nó không sai; nó chỉ quá hẹp ở ba trục
độc lập — và ba trục ấy nên là ba PR, không phải ba issue.

### N1 — thứ đứng **trước** động từ

| Câu | Đo được |
|---|---|
| `nóng quá bật điều hòa giúp mình` | `not_control` / `default_to_manual` |
| `ờ bật nhạc đi`, `im quá bật nhạc đi` | `not_control` |
| `vivi ơi bật nhạc`, `vivi ơi bật đèn tự động` | `not_control` |
| `ê vivi dẫn tui tới bình minh` | `not_control` |
| `bật bật nhạc`, `bật bật đèn chiếu gần` | **đã chạy đúng** (lặp động từ vô hại) |

`_split_at_inner_verbs` (`router.py:639`) đã cắt được câu ghép, nhưng chỉ khi **cả hai nửa** tự khớp
một `control`. Vế dẫn nhập (`nóng quá`, `ờ`, `vivi ơi`) không khớp gì cả nên không cắt được.

**Hướng sửa:** cho phép bỏ một tiền tố khi **phần còn lại tự khớp `control`** (không phải `clarify`,
không phải `denied`), có giới hạn độ dài tiền tố. Điều kiện "phần còn lại phải là control hoàn chỉnh"
chính là thứ giữ nguyên hàng rào của ADR-011: một câu hỏi tra cứu không bao giờ tạo ra `control` hoàn
chỉnh ở đuôi. Thêm bảng wake-phrase/filler tường minh cho `vivi ơi`, `ê vivi`, `ờ`, `à`, `ừm`.

**Gate bắt buộc:** `question_reaches_RAG` trên `manual/v1` **không được tụt** dưới 0.9833.

### N2 — bảng động từ

Hai lỗ khác nhau, đừng gộp lúc sửa:

*Lỗ 1 — `_COMMAND_VERBS` (`router.py:194`) thiếu từ:* `cho`, `để`, `khởi động`, `trượt`, `di chuyển`,
`dựng`, `đưa`, `đổi`, `chọn`, `chơi`, `bắt đầu`, `chỉ đường`, `mở bản đồ`.

*Lỗ 2 — mỗi matcher tự khai một tập con, và các tập con không đồng ý với nhau.* `chỉnh` **có** trong
`_COMMAND_VERBS`, nhưng `_match_window` (`router.py:1213`) chỉ nhận `mở|đóng|hạ|kéo|nâng`, nên
`chỉnh cửa sổ bên lái 25 phần trăm` chết trong khi `chỉnh lưng ghế` sống. Cùng một động từ, hai số
phận, tuỳ matcher — và không có chỗ nào tra được matcher nào cho phép gì.

| Câu | Đo được |
|---|---|
| `khởi động điều hòa`, `cho điều hòa 24 độ`, `để điều hòa 24 độ` | `not_control` |
| `đặt / chỉnh / để / cho / đưa ... cửa sổ ... %` (5 câu) | `not_control` cả 5 |
| `dựng lưng ghế lái lên 40 phần trăm`, `đẩy ghế lái tới 80 phần trăm` | `not_control` |
| `đưa ghế lái lên cao 80 / xuống thấp 20 phần trăm` | `not_control` |
| `cho đèn về chiếu gần`, `để đèn tự động`, `đổi đèn sang chiếu xa` | `not_control` |
| `cho tôi nghe nhạc`, `chơi nhạc`, `bắt đầu phát nhạc`, `khởi động nhạc` | `not_control` |
| `chỉ đường đến vincom`, `mở bản đồ đến công viên thống nhất` | `not_control` |

**Hướng sửa:** một bảng **lớp ngữ nghĩa** dùng chung — `ĐẶT_TUYỆT_ĐỐI`, `BẬT`, `TẮT`, `MỞ_VẬT_LÝ`,
`ĐÓNG_VẬT_LÝ`, `PHÁT`, `DẪN_ĐƯỜNG` — và matcher khai báo **lớp** thay vì liệt kê từ. Thêm một từ mới
sau này thì mọi matcher cùng lớp được hưởng, và hết chuyện `chỉnh` sống ở ghế mà chết ở kính.

### N3 — bảng alias đối tượng

| Câu | Đo được | Chỗ thiếu |
|---|---|---|
| `bật máy lạnh`, `bật ac`, `bật hệ thống làm mát` | `not_control` | `_match_hvac:908` chỉ nhận `điều hòa\|nhiệt độ\|quạt` |
| `mở cửa tài xế`, `mở cửa hành khách` | **mở cả 4 cửa** | `_side:1428` thiếu `tài xế / người lái / hành khách` |
| `làm ấm ghế lái mức 2` | `not_control` | `_match_seat:1245` chỉ nhận `sưởi` |
| `chỉnh chiều cao ghế lái 60 phần trăm` | `not_control` | `_match_seat_position:1271` axis chỉ có `nâng ghế\|hạ ghế` |
| `chuyển sang chiếu gần`, `bật chế độ chiếu xa`, `chuyển sang tự động` | `not_control` | `_match_lights:1331` bắt buộc có token `đèn` |
| `bật đèn cos`, `bật đèn high beam`, `chuyển đèn sang auto` | `clarify missing_light_target` | `_match_lights:1345-1350` thiếu alias mode |
| `tiếp tục phát`, `dừng ngay` | `not_control` | `_match_music:1189` bắt buộc có `nhạc` hoặc `bài` |

Lưu ý `bật đèn cos` trả `clarify`, không phải rơi RAG như báo cáo ghi — hệ thống nhận ra đây là lệnh
đèn nhưng không biết đèn nào. Chỉ cần thêm alias.

**Hướng sửa:** gom toàn bộ alias vào **một** module tra cứu (kiểu `src/agents/tu_dien_alias.py`) có
test riêng cho bảng, thay vì rải chuỗi cứng trong 9 matcher. Cẩn thận đúng một chỗ: alias `đèn` phải
kiểm chéo với `_UNSUPPORTED_LIGHTS` (`router.py:177`) — thêm rộng tay ở đây là cách nhanh nhất làm tụt
`question_recall`, đúng cái bẫy docstring đã cảnh báo.

---

## 4. Các nhóm còn lại

### N4 — câu hỏi năng lực bị trả `clarify` (T38)

```
'có thể chỉnh độ ngả ghế không' → clarify | missing_seat_side    ← sai
'có thể chỉnh độ cao ghế không' → not_control | manual_question  ← đúng
```

Hai câu cùng dạng, hai kết quả, và câu "đúng" chỉ đúng **tình cờ**: `độ cao ghế` không khớp axis nào
nên rơi xuống mặc định, còn `độ ngả ghế` chứa `ngả ghế` nên vào matcher rồi tắc ở `_side`.

Gốc nằm ở nhánh câu hỏi của `_match` (`router.py:~470`): khi matcher trả về không phải `control`, hàm
trả thẳng kết quả ấy ra ngoài. Một câu **hỏi** thì không bao giờ nên đẻ ra một câu hỏi lại về vị trí ghế.

**Hướng sửa:** trong nhánh `is_question`, `clarify` → `manual_query`. `denied` giữ nguyên (hỏi về một
việc bị cấm vẫn phải được nói là bị cấm). Sửa một chỗ, khoảng 3 dòng.
Cảnh báo: vùng này trùng PR #249 và #267 — làm sau khi hai PR đó merge.

### N5 — tự sửa lời (T37)

```
'bật nhạc không tắt đi'              → control | media play         (thực thi vế BỊ HUỶ)
'bật điều hòa à thôi'                → control | set_hvac_power on  (thực thi vế BỊ HUỶ)
'đặt âm lượng 70 không 40 phần trăm' → control | set_volume 70      (lấy số CŨ)
```

Nhóm khó nhất, và là nhóm duy nhất tôi đề nghị **hoãn**. Cần: nhận diện dấu hiệu sửa lời
(`à thôi`, `không`, `nhầm`, `ý tôi là`), cắt tại đó, giữ vế phải, rồi cho vế phải **thừa hưởng đích**
của vế trái (`40` phải hiểu là `đặt âm lượng 40`).

Lý do hoãn giờ đã cụ thể hơn lúc viết bản đầu: chữ `không` đang có **ba nghĩa** cùng lúc trong router
— phủ định (`is_negated`), tiểu từ nghi vấn (SP-2.1, đã merge), và **số 0** (PR #268, đang mở). #268
chốt luật neo `NEO_SO_KHONG`: `không` là số 0 **chỉ khi** có từ neo đứng ngay trước (`mức`, `về`,
`bằng`, `đến`, `tới`, `còn`, `là`). N5 sẽ thêm nghĩa thứ tư — *dấu hiệu rút lại lời vừa nói* — nên nó
phải **xây trên** `NEO_SO_KHONG` chứ không được định nghĩa bản thứ hai. Bắt đầu trước khi #268 merge
là gần như chắc chắn phải làm lại.

### N6 — media phát theo tên bài (T31, T32)

```
'phát bài carefree' → media_control{action: play}   ← không chọn đúng bài
'phát bài see tình' → media_control{action: play}   ← bài KHÔNG có trong playlist, vẫn phát
```

Đây là **thiếu năng lực**, không phải lỗi router: `tool_registry` không có `play_track`. Câu thứ hai là
lớp lỗi KI-001 ở dạng thuần nhất — hệ thống làm một việc khác việc được yêu cầu mà không nói ra. Cần:
tool `play_track(track_id)` + executor + fixture playlist + đường `denied` / `NO_MATCH` khi tên bài
không có, và **không** được đổi bài đang phát khi từ chối.

### N7 — dẫn đường (T33, T34): **PR #252 đã merge, nhóm này gần như tan**

Đo lại sau khi pull, phần tìm kiếm địa điểm đã chạy — đây là thứ SP-5 mang về:

```
'tìm quán cà phê gần đây'  → control | set_navigation{start, poi-cafe-02}
'tìm trạm sạc gần đây'     → control | set_navigation{start, poi-charge-01}
'tìm đường đến vincom'     → control | set_navigation{start, poi-mall-01}
```

T34 (phân biệt tìm-kiếm với khởi-hành) coi như xong. `tìm quán cà phê` trần vẫn rơi sổ tay — cần đối
chiếu spec SP-5 xem đó là cố ý (thiếu cụm chỉ vị trí `gần đây`/`quanh đây`) hay là ca hở; hỏi tác giả
#252 một câu là xong, đừng sửa mò.

Còn lại đúng ba câu: `chỉ đường đến ...`, `mở bản đồ đến ...`, `đi vincom` (động từ `đi` trần). Cả ba
là **thiếu động từ**, không phải thiếu logic dẫn đường.
→ **N7 không còn là nhóm riêng.** Gộp ba câu này vào N2 (bảng động từ), thêm lớp `DẪN_ĐƯỜNG`.

### N8 — `Mở cửa` trần: quyết định, không phải lỗi (T36)

Báo cáo đòi `CLARIFY missing_door_target`. Hành vi hiện tại (mở cả 4 cửa) là **cố ý**, có lý lẽ ghi
trong code (`router.py:1296-1305`), đến từ issue #65, và `VehicleControlView.tsx` **đang gửi đúng chuỗi
`"mở cửa"`** cho nút toàn xe. Đổi sang `clarify` sẽ làm hỏng nút đó.

Lập luận bảo vệ hành vi hiện tại: `set_door_state` là S2, plan dừng ở HITL, câu xác nhận liệt kê đủ
bốn cửa — tài xế nhìn thấy chính xác thứ mình đồng ý. Lập luận phản bác của Thành cũng có lý: tạo plan
4 cửa rồi mới hỏi là bắt người dùng từ chối một thứ họ chưa từng yêu cầu.

→ **Cần Thành quyết**, và nếu đổi thì phải sửa FE trong cùng PR. Sau khi N3 vá alias cửa, mức nguy
hiểm của hành vi này giảm hẳn (`mở cửa tài xế` sẽ ra đúng một cửa), nên đề nghị: **vá N3 trước, quyết
N8 sau** — lúc đó đây là một quyết định nhẹ hơn nhiều.

### N9 — STT nhầm phụ âm đầu (S01, `Dừng nhạc` → `Rừng nhạc`)

Không có lớp sửa lỗi từ vựng nào cả. `src/services/voice.py` chỉ có `_normalize_output_casing`
(`voice.py:67`) — viết hoa chữ đầu, hết. Cụm "Vietnamese correction layer" trong CLAUDE.md hiện chỉ là
cái đó.

**Hướng sửa:** một lớp sửa theo **từ điển miền** đặt giữa STT và router, chỉ sửa khi từ sai lệch đúng
một phụ âm đầu so với một từ trong tập lệnh đóng (`dừng/rừng`, `bật/bậc`, `tắt/tắc`, `cốp/cốc`). Phạm
vi hẹp là điều kiện an toàn: sửa rộng sẽ bóp méo câu hỏi tra sổ tay.
**Cần trước khi code:** file WAV tái hiện + một run WER có/không lớp sửa. Không có bằng chứng thì
không biết lớp này lãi hay lỗ.

### N10 — FE (G01, G02)

**G02 — text hiển thị lệch hành động đã thực thi. Gốc đã xác định.**
`DriverShellProvider.tsx` có `turnGenerationRef` (dòng 322) để chống ghi đè, nhưng nó chụp generation
**lúc event tới** (dòng 664: `revealPendingResponse(turnGenerationRef.current)`), không phải lúc lượt
sinh ra event bắt đầu. Nên khi câu trả lời của lượt 1 tới **sau khi** lượt 2 đã bắt đầu, generation
chụp được đã bằng generation hiện tại → guard cho qua → text lượt 1 đè lên UI lượt 2. Đúng triệu chứng
Giáp mô tả. `assistant.speech` (dòng 625) thì không có guard nào.

Điều may mắn: **mọi event đã mang sẵn `turnId`** (`turn/types.ts:296-300`) và `sendText` / `sendVoice`
đã trả `{turnId}` (dòng 357-358). Sửa = giữ `currentTurnIdRef`, bỏ mọi event có `turnId` khác. Nhỏ, rõ,
test được.

**G01 — cửa sổ mic sau `hey vivi` ngắn hơn trên deploy.** Chưa xác định được gốc, và không nên đoán.
Ba giả thuyết, đo được cả ba: (1) `FALSE_WAKE_TIMEOUT_MS = 4s` (`WakeWordController.ts:8`) tính từ lúc
arm, mà độ trễ arm trên deploy lớn hơn; (2) noise floor thích ứng (`NOISE_FLOOR_*`, dòng 54-56) hội tụ
khác trên mic/gain khác, khiến tiếng nói bị tính là im lặng và `COMMAND_SILENCE_MS = 900` bắn sớm;
(3) CPU trên VPS nghẽn (9 luồng tranh 5 vCPU) làm worker wake-word trễ nhịp.
**Việc cần làm trước:** log timestamp các mốc `arm → speech-detected → stop` ở cả local và deploy, rồi
so hai dãy số. Đừng sửa hằng số trước khi có hai dãy số ấy.

---

## 5. Xếp theo mức nguy hiểm

| Hạng | Nhóm | Vì sao |
|---|---|---|
| 1 | N3 (phần cửa) | `mở cửa tài xế` → plan mở **cả 4 cửa**, S2, sai đích |
| 2 | N6 (T32) | bài không có trong playlist vẫn phát bài khác, im lặng |
| 3 | N5 | thực thi đúng vế người dùng vừa **rút lại** |
| 4 | N10 / G02 | màn hình nói dối về việc xe vừa làm |
| 5 | N1, N2, N3 (phần còn lại) | trả lời sai chủ đề — khó chịu, không nguy hiểm |
| 6 | N4, N9, N10 / G01 | lệch trải nghiệm |

Bốn hạng đầu cùng một họ: **hệ thống làm một việc khác việc được yêu cầu mà không nói ra** (KI-001).
Hạng 5-6 chỉ là *không làm gì cả* — luôn nhẹ hơn.

---

## 6. Đề xuất: 7 issue, 8 PR cho 42 dòng báo cáo

**Việc số 0, làm trước mọi thứ — biến 42 dòng thành dataset.** Thêm 42 ca vào
`eval/datasets/agent/dinh-tuyen-v1/cases.jsonl` kèm `expected_disposition`. Không có nó thì không ai
chứng minh được đã sửa xong, và §1a sẽ lặp lại y hệt ở đợt báo lỗi sau.

| # | Issue | Nhóm | Số PR | Ghi chú thứ tự (đã cập nhật sau khi pull `develop`) |
|---|---|---|---|---|
| 1 | Dataset hồi quy 42 ca từ đợt test 24/08 | — | 1 | làm trước, không đụng `router.py` — **bắt đầu được ngay** |
| 2 | Router hiểu quá hẹp: alias, động từ, tiền tố | N1+N2+N3+N7 | 3 | #249/#252 đã merge, **hết chặn**; chỉ cần né #268 |
| 3 | Media: phát theo tên bài, và từ chối đúng khi không có bài | N6 | 1 | độc lập, chạy song song được |
| 4 | Câu hỏi năng lực không được trả `clarify` | N4 | 1 | sau #267 (còn đang mở, đụng `question.py`) |
| 5 | STT: lớp sửa từ theo từ điển miền | N9 | 1 | cần WAV + run WER trước |
| 6 | FE: đường thoại khi trả lời tới muộn | N10 | 1 | G02 sửa ngay; G01 đo trước |
| 7 | Router: tự sửa lời trong cùng lượt | N5 | 1 | **hoãn** tới sau #268 *và* sau issue #2 |

**Issue #2 tách làm 3 PR tuần tự, không phải 3 issue** — cùng một file, PR song song chỉ đẻ conflict:

- **PR 2a — alias đối tượng** (N3). Có ca hạng 1, nên đi trước. Vá `_side` cho
  `tài xế / người lái / hành khách` là dòng code đầu tiên nên gõ.
- **PR 2b — bảng động từ theo lớp ngữ nghĩa** (N2, kèm 3 câu dẫn đường còn lại của N7). To nhất,
  nhưng cơ học.
- **PR 2c — tiền xử lý đầu câu** (N1). Đi cuối vì rủi ro với `question_recall` cao nhất, và vì 2a+2b
  đã làm dataset xanh sẵn phần lớn nên hồi quy do 2c gây ra sẽ lộ ngay.

Cả ba PR nên **rebase lên `develop` sau khi #268 merge**. #268 sửa `_words_to_number` và `is_question`
— hai hàm mà 2b và 2c đều đi qua.

**Không mở issue cho:** N7 (đã tan sau #252 — hỏi tác giả một câu về `tìm quán cà phê` trần, còn lại
gộp vào 2b), N8 (xin Thành quyết, gắn vào issue #65), và 7 dòng ở §1a (đã chạy đúng trên `develop` —
chỉ cần deploy `develop`).

**Gate chung cho mọi PR router:**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m src.agents.eval --mode intent
.\.venv\Scripts\python.exe -m src.agents.eval --mode routing
```

`intent_accuracy` trên `agent/v3` phải giữ 1.0000 (tripwire hồi quy), `question_reaches_RAG` trên
`manual/v1` không dưới 0.9833. PR nào làm tụt con số thứ hai là PR đã đổi một lỗi im lặng lấy một lỗi
ồn ào hơn — xem docstring `_UNSUPPORTED_LIGHTS`.

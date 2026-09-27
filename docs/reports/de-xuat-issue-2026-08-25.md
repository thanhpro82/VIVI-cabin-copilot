# Bảy issue soạn sẵn cho đợt lỗi 24/08

**Ngày soạn:** 2026-08-25 · **Nguồn:** [`phan-tich-gom-bug-2026-08-25.md`](phan-tich-gom-bug-2026-08-25.md)
**Cây đo:** `develop` @ `bab0fc6`, `src/agents/router.py` @ `6e0b523`

File này để **copy-dán lên GitHub**, không phải tài liệu thiết kế. Mở xong 7 issue thì có thể xoá,
hoặc giữ lại làm dấu vết vì sao 42 dòng báo lỗi chỉ đẻ ra 7 issue.

**Thứ tự mở:** Đ0 trước (hotfix, đang làm), rồi Đ1 và Đ6 (song song), rồi Đ2 sau khi #268 merge,
cuối cùng Đ3–Đ5 và Đ7.

**Trước khi dán:** kiểm lại số hiệu — issue của repo đã tới **#279**, nên đừng dùng lại số Đ0–Đ7
trong nội dung; chúng chỉ là nhãn nháp trong file này.

---

## Đ0 — hotfix, đang làm trên `fix/alias-cua-tai-xe-hanh-khach`

> Không cần mở issue riêng nếu PR nói đủ. Ghi ở đây để đủ bộ.

**Tiêu đề:** `Router: "mở cửa tài xế" sinh kế hoạch mở CẢ BỐN cửa — plan S2 sai đích`
**Nhãn:** `bug` · **Gợi ý giao:** @hason0510

````markdown
### Đo được trên `develop` @ bab0fc6

```
'mở cửa tài xế'     → control | 4 bước set_door_state: front_left, front_right, rear_left, rear_right
'mở cửa hành khách' → control | 4 bước set_door_state: cả bốn cửa
```

### Nguyên nhân

`_side()` (`src/agents/router.py:1428`) chỉ biết `bên lái` / `ghế lái` / `bên phụ` / `ghế phụ`,
không biết `tài xế`, `người lái`, `hành khách`. Trả `None`, và `_match_door`
(`router.py:1288`) hiểu `None` là *"nhắm cả xe"* nên sinh kế hoạch bốn cửa.

Báo cáo gốc của @thanhpro82 ghi là *"không route đúng sang front_left"* — thực tế nặng hơn:
không phải rơi xuống RAG mà là một plan **S2 sai đích** đi tới HITL.

### Phạm vi

Thêm alias vào `_side`, **và** đảo thứ tự để vế "sau" thắng vế "trước": hiện `bên lái`
được kiểm trước `sau bên trái`, nên thêm `hành khách` vào nhánh trước sẽ khiến
`cửa hành khách sau bên phải` ra `front_right`.

### Tiêu chí xong

- `mở cửa tài xế` / `mở cửa người lái` → đúng **một** bước `front_left`
- `mở cửa hành khách` → đúng **một** bước `front_right`
- `mở cửa hành khách sau bên phải` → `rear_right`
- `mở cửa` trần → giữ nguyên hành vi bốn cửa (đó là chuyện của Đ7-quyết-định, không phải PR này)

### KHÔNG thuộc phạm vi

Nửa còn lại của lỗ hổng: **bất kỳ** từ chỉ cửa nào router không biết vẫn nở ra bốn cửa
(`mở cửa bên trái` chẳng hạn). Cần @thanhpro82 quyết — xem mục "quyết định T36".
````

---

## Đ1 — dataset hồi quy

**Tiêu đề:** `[Lỗi 24/08] Dataset hồi quy 42 ca — không có nó thì không ai chứng minh được đã sửa xong`
**Nhãn:** `enhancement` · **Gợi ý giao:** @hason0510 · **Làm trước mọi issue khác**

````markdown
### Vì sao đây là việc số 0

Đợt test 24/08 cho 42 dòng báo lỗi. Khi chạy lại từng câu trên `develop`:

- **7 dòng không tái hiện** — code đã hỗ trợ sẵn cách nói ấy, người test đang test bản
  deploy bám `DEPLOY_REF=main`, mà `main` đi sau `develop`.
- **1 dòng bị mô tả nhẹ hơn thực tế** — `mở cửa tài xế` không "rơi RAG", nó mở cả bốn cửa.

Cả hai chuyện đó sẽ lặp lại y hệt ở đợt báo lỗi sau, trừ khi 42 ca này thành dataset.

Và suite xanh không thay được nó: PR #268 vừa cho thấy **một test xanh đang bảo vệ một
hành vi sai**, xanh suốt vì chỉ kiểm chiều không nguy hiểm.

### Việc cần làm — ĐÃ LÀM, xem PR kèm theo

Bộ đặt ở **`eval/datasets/agent/bao-loi-2408/`**, là một dataset **riêng**, không nối vào bộ nào
đang có. Hai chỗ ban đầu tưởng là nhà của nó đều không phải:

- `dinh-tuyen-v1` phân loại **3 lớp** (control/manual/chitchat) và **cần llama-server thật**; bộ
  này phải chạy được khi không có model, và phải đo tới tận `tool` + `args`.
- `agent/v3` thì đúng schema, nhưng `CLAUDE.md` ghi rõ nó do chính người viết router soạn nên
  `intent_accuracy = 1.0000` của nó là **tripwire hồi quy**. Nhét 60 ca đang đỏ vào đó là phá luôn
  cái tripwire ấy.

**42 dòng báo lỗi → 77 ca**, vì một dòng thường mô tả nhiều cách nói (`T29` một mình có 5 câu).
Đơn vị đo là **câu**, không phải dòng báo cáo.

Mỗi ca mang thêm `trang_thai_2608` — nó **đang** hỏng hay **đang** đúng trên `develop` @ `bab0fc6`.
Từ đó `--mode bao-loi` sinh hai con số mà không ai phải tự khai:

- **`di_lui`** — ca ghi `dung` mà nay fail. **Phải bằng 0**; đây là cổng cứng của mọi PR đụng router.
- **`da_sua`** — ca ghi `hong` mà nay pass. Tiến độ thật của đợt sửa.

### Chạy

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode bao-loi
```

### Mốc

`run_id=20260825T170542.339324Z` — `dat=17/77`, `disposition=0.3117`, `tool_exact=0.2338`,
`di_lui=0`, `da_sua=0`, 10 ca gắn `can_quyet_dinh` (nhãn còn tranh chấp, **không** dùng làm cổng).

### Bốn cái bẫy đã gài sẵn

Bộ này chứa cả ca **đang xanh**, và ba trong số đó xanh **vì tình cờ** — đúng loại ca dễ mất nhất
khi refactor:

- `BL-N3-004` `Mở cửa hành khách sau bên phải` xanh chỉ vì `hành khách` chưa được nhận. Hotfix alias
  cửa đặt sai thứ tự là vỡ ngay.
- `BL-OK-001` `Lạnh rồi, tắt điều hòa giúp mình` xanh chỉ vì `rồi` tình cờ là liên từ. Câu sinh đôi
  `BL-N1-001` *"Nóng quá, bật điều hòa giúp mình"* đang đỏ.
- `BL-N4-002` `Có thể chỉnh độ cao ghế không?` xanh chỉ vì `độ cao ghế` không khớp axis nào — sửa
  `BL-N3-013` xong là ca này có thể vỡ.

### Ba dòng không có mặt

`S01` (STT), `G01`/`G02` (frontend) không diễn đạt được bằng một ca router. Xem Đ5 và Đ6.

### Tham chiếu

`docs/reports/phan-tich-gom-bug-2026-08-25.md` §1, §2.
````

---

## Đ2 — router hiểu quá hẹp (gộp N1+N2+N3+N7 = 28 dòng)

**Tiêu đề:** `[Lỗi 24/08] Router chỉ khớp động từ ở đầu câu — 28/42 dòng báo lỗi quy về một hàm sáu dòng`
**Nhãn:** `bug` · **Gợi ý giao:** @HVNhan-Relieq · **Mở sau khi #268 merge**

````markdown
### Một nguyên nhân, ba mặt

28 trong 42 dòng báo lỗi quy về `_starts_with_command` (`src/agents/router.py:1440`):

```python
@staticmethod
def _starts_with_command(text: str, *verbs: str) -> bool:
    command = _POLITE_PREFIX_PATTERN.sub("", text, count=1)
    return any(command == verb or command.startswith(f"{verb} ") for verb in verbs)
```

Neo tuyệt đối ở ký tự số 0, chỉ bóc được `hãy|vui lòng|làm ơn|giúp tôi`. Luật này là **cố ý**
theo ADR-011 và nó mua được `question_reaches_RAG = 0.9833`. Nó không sai — nó hẹp ở ba trục
độc lập, nên xin làm **ba PR tuần tự trong một issue**, không phải ba issue.

### PR 2a — alias đối tượng (đi trước, có ca nguy hiểm)

| Câu | Đo được | Chỗ thiếu |
|---|---|---|
| `bật máy lạnh` · `bật ac` · `bật hệ thống làm mát` | `not_control` | `_match_hvac:908` chỉ nhận `điều hòa\|nhiệt độ\|quạt` |
| `làm ấm ghế lái mức 2` | `not_control` | `_match_seat:1245` chỉ nhận `sưởi` |
| `đặt độ cao ghế lái 70%` · `chỉnh chiều cao ghế 60%` | `not_control` | `_match_seat_position:1271` axis chỉ có `nâng ghế\|hạ ghế` |
| `chuyển sang chiếu gần` · `bật chế độ chiếu xa` | `not_control` | `_match_lights:1331` bắt buộc có token `đèn` |
| `bật đèn cos` · `bật đèn high beam` · `chuyển đèn sang auto` | `clarify missing_light_target` | thiếu alias mode |
| `tiếp tục phát` · `dừng ngay` | `not_control` | `_match_music:1189` bắt buộc có `nhạc` hoặc `bài` |

Alias cửa (`tài xế` / `hành khách`) đã tách ra hotfix riêng, **không** làm lại ở đây.

Đề xuất: gom alias vào **một** module tra cứu có test riêng cho bảng, thay vì rải chuỗi cứng
trong 9 matcher. Một chỗ phải cẩn thận: alias `đèn` phải kiểm chéo với `_UNSUPPORTED_LIGHTS`
(`router.py:177`) — thêm rộng tay ở đây là cách nhanh nhất làm tụt `question_recall`.

### PR 2b — bảng động từ theo lớp ngữ nghĩa

Hai lỗ khác nhau, đừng gộp lúc sửa.

**Lỗ 1 — `_COMMAND_VERBS` (`router.py:194`) thiếu từ:** `cho`, `để`, `khởi động`, `trượt`,
`di chuyển`, `dựng`, `đưa`, `đổi`, `chọn`, `chơi`, `bắt đầu`, `chỉ đường`, `mở bản đồ`.

**Lỗ 2 — mỗi matcher tự khai một tập con, và các tập con không đồng ý với nhau.** `chỉnh`
**có** trong `_COMMAND_VERBS` nhưng `_match_window` (`router.py:1213`) chỉ nhận
`mở|đóng|hạ|kéo|nâng`, nên `chỉnh cửa sổ bên lái 25%` chết trong khi `chỉnh lưng ghế` sống.
Cùng một động từ, hai số phận, và không tra được ở đâu matcher nào cho phép gì.

Câu đo được (tất cả `not_control`):

```
khởi động điều hòa · cho điều hòa 24 độ · để điều hòa 24 độ
đặt / chỉnh / để / cho / đưa ... cửa sổ ... %        (5 câu)
dựng lưng ghế lái lên 40% · đẩy ghế lái tới 80%
đưa ghế lái lên cao 80% · xuống thấp 20%
cho đèn về chiếu gần · để đèn tự động · đổi đèn sang chiếu xa
cho tôi nghe nhạc · chơi nhạc · bắt đầu phát nhạc · khởi động nhạc
chỉ đường đến vincom · mở bản đồ đến công viên thống nhất · đi vincom
```

Đề xuất: bảng **lớp ngữ nghĩa** dùng chung (`ĐẶT_TUYỆT_ĐỐI`, `BẬT`, `TẮT`, `MỞ_VẬT_LÝ`,
`ĐÓNG_VẬT_LÝ`, `PHÁT`, `DẪN_ĐƯỜNG`), matcher khai báo **lớp** thay vì liệt kê từ.

Ba câu dẫn đường ở dòng cuối vốn thuộc nhóm N7; sau khi #252 merge thì phần dẫn đường đã
chạy, chỉ còn thiếu đúng động từ, nên gộp vào đây.

### PR 2c — tiền xử lý đầu câu (đi cuối, rủi ro cao nhất)

```
'nóng quá bật điều hòa giúp mình'  → not_control
'ờ bật nhạc đi' · 'im quá bật nhạc đi' · 'vivi ơi bật nhạc'  → not_control
'ê vivi dẫn tui tới bình minh'     → not_control
'bật bật nhạc' · 'bật bật đèn chiếu gần'  → control   ✅ lặp động từ vốn đã vô hại
```

`_split_at_inner_verbs` (`router.py:639`) đã cắt được câu ghép, nhưng chỉ khi **cả hai nửa**
tự khớp một `control`. Vế dẫn nhập (`nóng quá`, `ờ`, `vivi ơi`) không khớp gì nên không cắt được.

Bằng chứng cho thấy đây đúng là một lỗ chứ không phải thiết kế: `lạnh rồi tắt điều hòa giúp mình`
**chạy đúng**, nhưng chỉ vì `rồi` tình cờ nằm trong `_CONJUNCTIONS`. Cùng lớp câu, hai số phận.

Đề xuất: cho phép bỏ một tiền tố **chỉ khi phần còn lại tự khớp `control`** (không phải
`clarify`, không phải `denied`), có giới hạn độ dài tiền tố. Điều kiện đó chính là thứ giữ
nguyên hàng rào ADR-011: câu hỏi tra cứu không bao giờ tạo ra một `control` hoàn chỉnh ở đuôi.
Thêm bảng wake-phrase/filler tường minh: `vivi ơi`, `ê vivi`, `ờ`, `à`, `ừm`.

### Gate cho cả ba PR

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m src.agents.eval --mode intent
.\.venv\Scripts\python.exe -m src.agents.eval --mode routing
```

- `intent_accuracy` trên `agent/v3` giữ **1.0000** (tripwire hồi quy).
- `question_reaches_RAG` trên `manual/v1` **không dưới 0.9833**. PR nào làm tụt con số này là
  PR đã đổi một lỗi im lặng lấy một lỗi ồn ào hơn.
- Rebase lên `develop` sau khi #268 merge — nó sửa `_words_to_number` và `is_question`, hai hàm
  cả 2b lẫn 2c đều đi qua.
````

---

## Đ3 — media phát theo tên bài

**Tiêu đề:** `[Lỗi 24/08] Xin phát một bài không có trong playlist thì xe phát bài khác — không nói gì`
**Nhãn:** `bug`, `enhancement` · **Gợi ý giao:** thương lượng @HVNhan-Relieq / @hason0510 · **Chạy song song được**

````markdown
### Đo được

```
'phát bài carefree'  → control | media_control{action: play}   ← không chọn đúng bài
'phát bài see tình'  → control | media_control{action: play}   ← bài KHÔNG có, vẫn phát
'mở wallpaper'       → not_control
```

Câu thứ hai là lớp lỗi KI-001 ở dạng thuần nhất: hệ thống làm một việc **khác** việc được yêu
cầu mà không nói ra. Người dùng xin bài A, xe phát bài B, không một lời.

### Nguyên nhân

Thiếu năng lực, không phải lỗi router: `src/services/tool_registry.py` chỉ có
`play / pause / next / previous / set_volume`, không có `play_track(track_id)`.

### Phạm vi

- Tool `play_track(track_id)` trong registry + executor + fixture playlist 5 track.
- Đường từ chối khi tên bài không có: `denied` với `reason` phân biệt được.
- Router: nhận tên bài sau `phát / mở / bật ... bài <tên>`.

### Tiêu chí xong

- `phát bài carefree` → `play_track` đúng track id, **không** phải `play` chung.
- `phát bài see tình` → `denied`, và **không được đổi bài đang phát**. Đây là nửa quan trọng
  hơn: từ chối mà vẫn đổi track thì vẫn là làm một việc không ai yêu cầu.
- Tên bài viết hoa/thường/thiếu dấu đều khớp.
````

---

## Đ4 — câu hỏi năng lực bị trả `clarify`

**Tiêu đề:** `[Lỗi 24/08] Hỏi "có chỉnh được độ ngả ghế không" thì xe hỏi ngược lại ghế nào`
**Nhãn:** `bug` · **Gợi ý giao:** @HVNhan-Relieq · **Mở sau #267**

````markdown
### Đo được

```
'có thể chỉnh độ ngả ghế không' → clarify | missing_seat_side    ← sai
'có thể chỉnh độ cao ghế không' → not_control | manual_question  ← đúng
```

Hai câu cùng dạng, hai kết quả — và câu "đúng" chỉ đúng **tình cờ**: `độ cao ghế` không khớp
axis nào nên rơi xuống mặc định, còn `độ ngả ghế` chứa `ngả ghế` nên vào matcher rồi tắc ở `_side`.

### Nguyên nhân

Nhánh `is_question` của `_match` (`src/agents/router.py:~470`): khi matcher trả về không phải
`control`, hàm trả thẳng kết quả ấy ra ngoài. Một câu **hỏi** thì không bao giờ nên đẻ ra một
câu hỏi lại về vị trí ghế — người ta đang hỏi *làm được không*, chưa yêu cầu làm.

### Phạm vi

Trong nhánh `is_question`: `clarify` → `manual_query`. Giữ nguyên `denied` (hỏi về một việc bị
cấm thì vẫn phải được nói là bị cấm) và giữ nguyên `offer` cho `control`.

### Tiêu chí xong

- Cả hai câu trên cùng ra `manual_query`.
- `mở cửa sổ bên lái được không?` vẫn ra `offer` như cũ — không được nuốt mất đường `offer`.
- `question_reaches_RAG` trên `manual/v1` không tụt.

Vùng này chạm `question.py`, trùng #267 và #217. Chờ chúng merge.
````

---

## Đ5 — STT sửa từ theo từ điển miền

**Tiêu đề:** `[Lỗi 24/08] STT nghe "Dừng nhạc" thành "Rừng nhạc" — không có lớp sửa nào bắt được`
**Nhãn:** `bug` · **Gợi ý giao:** @hason0510 · **Cần bằng chứng trước khi code**

````markdown
### Báo cáo

@hason0510 24/08: nói *"Dừng nhạc"*, STT chép ra *"Rừng nhạc"*, lệnh rơi xuống tra sổ tay.

### Hiện trạng

Không có lớp sửa lỗi từ vựng nào cả. `src/services/voice.py` chỉ có `_normalize_output_casing`
(`voice.py:67`) — viết hoa chữ cái đầu, hết. Cụm "Vietnamese correction layer" trong CLAUDE.md
hiện chỉ là cái đó.

### Đề xuất

Một lớp sửa theo **từ điển miền** đặt giữa STT và router, chỉ sửa khi từ sai lệch **đúng một
phụ âm đầu** so với một từ trong tập lệnh đóng: `dừng/rừng`, `bật/bậc`, `tắt/tắc`, `cốp/cốc`.

Phạm vi hẹp là điều kiện an toàn, không phải sự lười: sửa rộng sẽ bóp méo câu hỏi tra sổ tay,
mà nhánh sổ tay là mặc định của ADR-011 nên nó nhận phần lớn lưu lượng.

### Chặn — làm trước khi viết dòng code nào

1. File WAV tái hiện được (@hason0510 ghi lại).
2. Một run WER **có** và **không** lớp sửa, trên cùng bộ audio.

Không có hai thứ đó thì không biết lớp này lãi hay lỗ. `transcribe_raw` (`voice.py:162`) tồn tại
sẵn để đo đúng chuyện này.
````

---

## Đ6 — FE: đường thoại khi trả lời tới muộn

**Tiêu đề:** `[Lỗi 24/08] Màn hình hiện câu trả lời của lượt trước trong khi xe vừa làm việc của lượt sau`
**Nhãn:** `bug` · **Gợi ý giao:** @danggiap123 · **Chạy song song được**

````markdown
### Báo cáo

@danggiap123 24/08: *"bảo bật điều hòa, nói nhỏ quá nó không nhận; một lúc sau nó tự bật điều hòa.
Nói tiếp mở cửa thì cửa vẫn mở nhưng text output lại hiện bật điều hòa."*

## Phần A — text lệch hành động (gốc đã xác định, sửa được ngay)

`DriverShellProvider.tsx` **có** `turnGenerationRef` (dòng 322) để chống ghi đè, nhưng nó chụp
generation **lúc event tới** (dòng 664: `revealPendingResponse(turnGenerationRef.current)`), chứ
không phải lúc lượt sinh ra event bắt đầu.

Nên khi câu trả lời của lượt 1 tới **sau khi** lượt 2 đã bắt đầu, generation chụp được đã bằng
generation hiện tại → guard cho qua → text lượt 1 đè lên UI lượt 2. `assistant.speech` (dòng 625)
thì không có guard nào, nên giọng đọc của lượt cũ cũng phát đè.

Điều may mắn: **mọi event đã mang sẵn `turnId`** (`lib/services/turn/types.ts:296-300`) và
`sendText` / `sendVoice` đã trả `{turnId}` (dòng 357-358).

**Phạm vi:** giữ `currentTurnIdRef`, gán từ giá trị `sendText`/`sendVoice` trả về, bỏ mọi event
có `turnId` khác. Chú ý dòng 304 của `types.ts` ghi rõ một loại event **không** được lọc theo
turnId — đọc trước khi lọc đại trà.

**Tiêu chí xong:** gửi lượt 1 (chậm), gửi lượt 2, giả lập `assistant.response` của lượt 1 tới sau
→ UI giữ nội dung lượt 2, không phát audio lượt 1. Có test.

## Phần B — mic tắt sớm sau `hey vivi` trên deploy (phải đo trước)

@danggiap123: *"lúc nói heyvivi thì thời gian hiển thị mic để nói ngắn hơn ở local, đang nói dở thì
mic tắt."* Chưa xác định được gốc, **đừng sửa hằng số trước khi có số đo.**

Ba giả thuyết, đo được cả ba:

1. `FALSE_WAKE_TIMEOUT_MS = 4s` (`lib/wake-word/WakeWordController.ts:8`) tính từ lúc arm, mà độ
   trễ arm trên deploy lớn hơn.
2. Noise floor thích ứng (`NOISE_FLOOR_*`, dòng 54-56) hội tụ khác trên mic/gain khác, khiến tiếng
   nói bị tính là im lặng và `COMMAND_SILENCE_MS = 900` bắn sớm.
3. CPU trên VPS nghẽn làm worker wake-word trễ nhịp.

**Việc trước tiên:** log timestamp các mốc `arm → speech-detected → stop` ở cả local và deploy, so
hai dãy số, đính vào issue. Sửa sau.
````

---

## Đ7 — tự sửa lời trong cùng lượt

**Tiêu đề:** `[Lỗi 24/08] "Bật nhạc... không, tắt đi" thì xe bật nhạc — thực thi đúng vế vừa bị rút lại`
**Nhãn:** `bug` · **Gợi ý giao:** @HVNhan-Relieq · **HOÃN — mở sau khi #268 merge và sau Đ2**

````markdown
### Đo được

```
'bật nhạc không tắt đi'              → control | media play        (thực thi vế BỊ HUỶ)
'bật điều hòa à thôi'                → control | set_hvac_power on (thực thi vế BỊ HUỶ)
'đặt âm lượng 70 không 40 phần trăm' → control | set_volume 70     (lấy số CŨ)
```

### Việc cần làm

Nhận dấu hiệu sửa lời (`à thôi`, `không`, `nhầm`, `ý tôi là`), cắt tại đó, giữ vế phải, rồi cho
vế phải **thừa hưởng đích** của vế trái — `40` phải hiểu là `đặt âm lượng 40`, không phải một số
lơ lửng.

### Vì sao hoãn, và hoãn tới khi nào

Chữ `không` đang mang **ba** nghĩa cùng lúc trong router:

1. phủ định (`is_negated`),
2. tiểu từ nghi vấn (SP-2.1, đã merge),
3. số 0 — PR **#268** đang mở, chốt luật neo `NEO_SO_KHONG`: `không` là số 0 **chỉ khi** có từ
   neo đứng ngay trước (`mức`, `về`, `bằng`, `đến`, `tới`, `còn`, `là`).

Issue này thêm nghĩa **thứ tư**. Nó phải **xây trên** `NEO_SO_KHONG` chứ không được định nghĩa
bản thứ hai — #268 đã ghi rõ: *"hai bản sao là hai bản sẽ lệch nhau."* Bắt đầu trước khi #268
merge là gần như chắc chắn phải làm lại.

Và nên đứng sau Đ2: lúc đó dataset 42 ca đã xanh phần lớn, nên hồi quy do issue này gây ra sẽ
lộ ngay thay vì lẫn vào 27 ca đang đỏ sẵn.
````

---

## Hai việc không mở issue

**Comment vào PR #252** — hỏi tác giả: `tìm quán cà phê` **trần** (không có `gần đây` / `quanh đây`)
rơi xuống sổ tay là cố ý theo spec SP-5, hay là ca hở? Ba câu POI khác đã chạy đúng sau khi #252
merge, nên đây là câu hỏi duy nhất còn lại của nhóm dẫn đường. Đừng sửa mò.

**Hỏi @thanhpro82 về T36** — `mở cửa` trần hiện sinh kế hoạch bốn cửa. Báo cáo đòi
`CLARIFY missing_door_target`, nhưng hành vi hiện tại là **cố ý**: có lý lẽ ghi trong code
(`router.py:1296-1305`), đến từ issue #65, và `VehicleControlView.tsx` **đang gửi đúng chuỗi
`"mở cửa"`** cho nút toàn xe — đổi sang `clarify` sẽ làm hỏng nút đó.

Hai lập luận đều có lý: `set_door_state` là S2 nên plan dừng ở HITL và câu xác nhận liệt kê đủ
bốn cửa (tài xế thấy chính xác thứ mình đồng ý); nhưng tạo plan bốn cửa rồi mới hỏi cũng là bắt
người dùng từ chối một thứ họ chưa từng yêu cầu.

Nói rõ với Thành: **sau hotfix Đ0 thì mức nguy hiểm giảm hẳn** (`mở cửa tài xế` sẽ ra đúng một
cửa), nên đây trở thành quyết định UX chứ không còn là quyết định an toàn. Nếu chốt đổi thì phải
sửa `VehicleControlView.tsx` trong **cùng** PR.

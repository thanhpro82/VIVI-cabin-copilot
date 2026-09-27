# bao-loi-2408 — 77 ca dựng từ bảng báo lỗi 24/08

Bảng báo lỗi ngày 24/08 (Thành 39 dòng, Sơn 1, Giáp 2) gom thành 8 nhóm nguyên nhân ở
`docs/reports/phan-tich-gom-bug-2026-08-25.md`. Bộ này là **phần đo được** của bảng ấy: mỗi câu
thoại thành một ca, chấm thẳng qua `DeterministicControlRouter.route()`, không qua HTTP, không qua
STT, không gọi model.

**42 dòng báo lỗi → 77 ca**, vì một dòng thường mô tả nhiều cách nói (`T29` một mình có 5 câu).
Đơn vị đo là **câu**, không phải dòng báo cáo.

Chạy:

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode bao-loi
```

→ `eval/results/agent-bao-loi/<UTC-run-id>/` (bất biến; muốn số mới thì chạy lại).

---

## Vì sao là bộ riêng, không nối vào `agent/v3`

`CLAUDE.md` ghi rõ: `agent/v3` do **chính người viết router** soạn, nên `intent_accuracy = 1.0000`
của nó là **tripwire hồi quy**, không phải thước đo tổng quát hoá. Nhét 60 ca đang đỏ vào đó là phá
luôn cái tripwire — mất một thước đang dùng được để lấy một thước lẫn lộn hai mục đích.

Cũng không nối vào `dinh-tuyen-v1`: bộ đó phân loại **3 lớp** (control / manual / chitchat) và cần
llama-server thật. Bộ này đo tới tận `tool` + `args`, và phải chạy được khi không có model.

---

## Trường

| Trường | Bắt buộc | Nghĩa |
|---|---|---|
| `case_id` | ✓ | `BL-<nhóm>-<số>`. `BL-OK-*` là nhóm tripwire. |
| `domain` | ✓ | **Nhóm nguyên nhân**, không phải miền xe — `_aggregate` gộp theo trường này nên `metrics.by_domain` cho ra tiến độ **từng nhóm**. |
| `input_text` | ✓ | Nguyên văn như người test nói/gõ, giữ cả dấu câu và `...`. |
| `expected` | ✓ | `{disposition, intent, tools:[{tool,args}]}` — cùng schema `agent/v3`, dùng chung `score_case`. |
| `mien` | ✓ | Miền xe (`hvac`, `door`, `window`, `seat`, `lights`, `media`, `nav`, `trunk`). Để lọc chéo với `docs/coverage_matrix.md`. |
| `dong_goc` | ✓ | Dòng trong bảng báo lỗi (`T09`, `S01`, `G02`). Truy ngược về người báo. |
| `trang_thai_2608` | ✓ | `hong` / `dung` — trạng thái **đo được** trên `develop` @ `bab0fc6`. Đây là **mốc**, xem dưới. |
| `can_quyet_dinh` | | `true` nếu nhãn còn tranh chấp. **Không dùng làm cổng** khi chưa chốt. |
| `ghi_chu` | | Vì sao ca này đáng có, hoặc cái bẫy nó gài. |

`expected` mô tả **trạng thái mong muốn**, không phải trạng thái hiện tại. 60/77 ca đang đỏ, và
đó là đúng ý đồ.

---

## Mốc `trang_thai_2608` và hai con số nó sinh ra

Mỗi lần chạy, `metrics.json` có thêm hai danh sách so với mốc:

- **`di_lui`** — ca ghi `dung` mà nay fail. **Phải bằng 0.** Một ca ở đây nghĩa là bản vá vừa làm
  hỏng thứ đang chạy được. Đây là cổng cứng của mọi PR đụng router.
- **`da_sua`** — ca ghi `hong` mà nay pass. Đây là tiến độ thật của đợt sửa, đếm được, không cần
  ai tự khai.

Ở mốc thì cả hai đều rỗng — `run_id=20260825T170542.339324Z`, `dat=17/77`,
`disposition=0.3117`, `tool_exact=0.2338`.

`test_ca_ghi_dung_khong_duoc_di_lui` gác chiều `di_lui` và **chỉ** chiều đó. Chiều ngược lại không
được phép làm đỏ suite: đó chính là lúc ai đó vừa sửa xong bug, và một bộ đo bắt đền người sửa đúng
thì lần sau không ai chạy nó nữa.

**Khi một PR làm `da_sua` dài ra:** đừng sửa `trang_thai_2608` theo. Mốc là ảnh chụp ngày 25/08 và
giá trị của nó nằm ở chỗ nó **không đổi**; `da_sua` dài ra chính là thứ ta muốn đọc. Chỉ đổi mốc khi
mở một đợt báo lỗi mới, và khi đó nên là một bộ mới (`bao-loi-<ngày>`), không phải sửa bộ này.

---

## Bốn cái bẫy đã gài sẵn

Đây là các ca **đang đúng** — chúng ở đây không phải để khoe mà để kêu khi ai đó sửa hỏng:

- **`BL-N3-004`** `Mở cửa hành khách sau bên phải` → `rear_right`. Đang đúng **chỉ vì** `hành khách`
  chưa được nhận, nên nhánh `sau bên phải` được với tới. Hotfix alias cửa mà đặt `hành khách` trước
  nhánh `sau ...` là ca này vỡ ngay.
- **`BL-OK-001`** `Lạnh rồi, tắt điều hòa giúp mình` → đang đúng **chỉ vì** `rồi` tình cờ nằm trong
  `_CONJUNCTIONS` nên câu bị cắt làm hai vế. PR tiền xử lý đầu câu (2c) đụng vào chỗ cắt vế thì đây
  là chuông báo. Câu sinh đôi của nó, `BL-N1-001` *"Nóng quá, bật điều hòa giúp mình"*, đang đỏ —
  hai câu cùng lớp, hai số phận, và đó là bằng chứng cho chính nhóm N1.
- **`BL-N4-002`** `Có thể chỉnh độ cao ghế không?` → `manual_question`. Đang đúng **chỉ vì**
  `độ cao ghế` không khớp axis nào. Sửa `BL-N3-013` (`Đặt độ cao ghế lái 70%`) xong là ca này có thể
  vỡ thành `clarify missing_seat_side` — đúng lỗi mà `BL-N4-001` đang mắc.
- **`BL-N1-004` / `BL-N1-008`** lặp động từ (`Bật... bật nhạc`) đang vô hại. Giữ để PR 2c không
  "sửa" luôn thứ không hỏng.

Ba trong bốn cái bẫy trên là ca **đúng vì tình cờ**. Đó là loại ca dễ mất nhất khi refactor, và là
lý do bộ này phải chứa cả ca đang xanh chứ không chỉ ca đang đỏ.

---

## Thêm ca mới

Nối một dòng JSONL, giữ `case_id` không trùng, rồi chạy lại. Ba luật:

1. **`trang_thai_2608` phải khớp thực tế.** Chạy thử trước khi ghi; ghi sai thì `di_lui` / `da_sua`
   nói dối ngay từ lần chạy đầu. `tests/test_agents/test_bo_bao_loi_2408.py` bắt đúng chuyện này.
2. **Nhãn tranh chấp thì gắn `can_quyet_dinh: true`**, đừng lặng lẽ chọn một bên. Hiện có 10 ca như
   vậy — xem dưới.
3. **`domain` là nhóm nguyên nhân**, không phải miền xe. Đặt sai thì `by_domain` hết đọc được.

### 10 ca đang chờ chốt nhãn

| Ca | Câu | Tranh chấp |
|---|---|---|
| `BL-N2-024` | `Đi Vincom` | `đi` trần cũng mở đầu câu không phải lệnh (`đi ăn cơm`) |
| `BL-N3-009` | `AC 24 độ` | câu không có động từ — `_segment_clauses` gọi đây là "một issue riêng" |
| `BL-N3-017` | `Chuyển sang tự động` | không có token nào chỉ đèn |
| `BL-N3-022` | `Dừng ngay` | có thể là dừng **xe** |
| `BL-N5-003` | `Bật điều hòa... à thôi` | rút lại mà không nêu ý mới: `clarify` hay `not_control` |
| `BL-N6-001..003` | `Phát bài Carefree`… | `track_id` là **tạm**, cập nhật khi fixture playlist chốt |
| `BL-N7-004` | `Tìm quán cà phê` | cần hỏi tác giả #252: trần, không có `gần đây` |
| `BL-N8-001` | `Mở cửa` | nhãn = hành vi hiện tại (bốn cửa). Đổi **chỉ khi** @thanhpro82 chốt |

---

## Vòng đời một ca — và vì sao `da_sua` một mình là chưa đủ

Điều kiện approve của review #302. Nếu `di_lui` chỉ đọc `trang_thai_2608` thì một ca vừa sửa
xong mà **tái hỏng** chỉ rụng khỏi `da_sua` — CI vẫn xanh. Bộ đo khi ấy là bảng tiến độ, không
phải regression suite: nó đếm được lúc bug biến mất nhưng im lặng đúng lúc bug quay lại.

| Bước | Trạng thái | Vào `di_lui`? |
|---|---|---|
| 1 | `trang_thai_2608: "hong"` — mốc gốc, đo trên `develop` @ `bab0fc6`. **Không bao giờ sửa lại.** | không |
| 2 | `hong` + nay pass → hiện ở `da_sua` và `ung_vien_promote` | không |
| 3 | **đã promote** — có mục trong `cong_hoi_quy.json` | **có** |

`cong_hoi_quy.json` chỉ được **cộng thêm**, bằng lệnh, không sửa tay:

```powershell
# Chạy trên develop đã xanh. Từ chối promote nếu run còn ca đi lùi.
.\.venv\Scripts\python.exe -m src.agents.eval --mode bao-loi --promote
```

Mỗi mục ghi `run_id` + `commit` đã dùng để promote, nên baseline không đổi âm thầm: đổi nó là
một dòng trong `git log`, và cái `run_id` ấy trỏ tới một thư mục run bất biến. Mục đã có
**không** bị ghi đè — lần promote đầu tiên là lần đúng để trích dẫn.

Ca `can_quyet_dinh: true` **không bao giờ** tự vào cổng: nhãn của chúng còn đang tranh chấp, và
khoá một câu trả lời chưa ai chốt thì tệ hơn không khoá gì. Chúng vẫn được chấm, vẫn đếm vào
`da_sua`. Muốn đưa vào cổng thì chốt nhãn trước, bỏ cờ `can_quyet_dinh`, rồi promote.

**Lần promote đầu:** 46 ca, run `20260827T050223.721328Z`, commit `05eea2b` (nhánh
`feat/bo-do-bao-loi-2408` sau rebase lên `origin/develop` @ `88e2e9b`). 1 trong 47 ca của
`da_sua` bị giữ lại vì mang cờ `can_quyet_dinh`.

---

## Ba dòng báo lỗi không có mặt ở đây

`S01` (STT nghe *"Dừng nhạc"* thành *"Rừng nhạc"*), `G01` (mic tắt sớm sau wake word) và `G02`
(text lệch hành động) **không diễn đạt được** bằng một ca router: chúng nằm ở tầng STT và frontend.
Đo chúng cần WAV thật và log timestamp trình duyệt — xem `docs/reports/de-xuat-issue-2026-08-25.md`
mục Đ5 và Đ6.

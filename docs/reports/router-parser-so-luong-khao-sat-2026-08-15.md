# Router — khảo sát cách nói số lượng thực tế (nhân issue #117)

> **Status: đã chạy thật trên máy dev 2026-08-15.** Mọi ô trong bảng là output thật của
> `DeterministicControlRouter.route()`, không suy luận từ đọc code. Nhánh
> `fix/issue-117-word-number-percent`, Python 3.11.9, 50 câu khảo sát.
>
> Người viết: Sơn (WS3). Người nhận: Nhân (chủ sở hữu router/agent) + PM/PO.

> **Cập nhật 2026-08-15, cùng ngày:** cả 5 nhóm việc ở §8 **đã sửa xong** trên cùng nhánh.
> Suite **1149 passed / 17 skipped**, `ruff` sạch, tripwire eval giữ nguyên
> (`intent_accuracy` 1.0000, `question_to_control` 0, `command_accuracy` 1.0000 —
> run `20260815T061753.218935Z` và `20260815T061753.492271Z`). Các mục §3–§7 dưới đây giữ
> nguyên văn mô tả **hiện trạng trước khi sửa**, vì đó là lý do tồn tại của bản vá; cột kết quả
> mới nằm ở §10.

## Kết luận một dòng

Bản vá #117 đóng đúng lỗi được báo, nhưng khảo sát rộng cho thấy **hậu tố `phần trăm` chỉ là một
trong nhiều cách nói số lượng mà parser đọc sai trong im lặng**. Nhóm nghiêm trọng nhất không phải
phân số mà là **lệnh tương đối** (`"tăng âm lượng thêm 10"`) — nó bị đọc thành lệnh tuyệt đối và
có thể làm điều ngược hẳn ý người dùng.

Bản vá cũng gây **một thoái lui**: `"mười mấy phần trăm"` từ `clarify` chuyển thành đoán 10.

---

## 1. Phạm vi và cách đo

Khảo sát 50 câu chia 8 nhóm, chạy qua `router.route()` và đọc `disposition` / `reason` /
`candidate_plan.steps[0].args`. 38 trong số đó được đưa tiếp qua phép so trước/sau dưới đây.

Để tách **cái có sẵn** khỏi **cái do bản vá đổi**, mỗi câu chạy hai lượt: một lượt với code hiện
tại, một lượt vá ngược hai hằng số của bản vá (`_PERCENT_UNIT_PATTERN` thành regex không bao giờ
khớp, `_TENS_TOKENS` bỏ `mười`). Đây là cùng kỹ thuật mutation check dùng để nghiệm thu #117.

---

## 2. Bản vá #117 đổi đúng 5 câu

| Câu | Trước | Sau | Đánh giá |
|---|---|---|---|
| `Mở cửa sổ bên lái năm mươi phần trăm` | `clarify / missing_window_position` | `percent 50` | ✅ mục tiêu issue |
| `Mở cửa sổ bên lái hai sáu phần trăm` | `clarify / missing_window_position` | `percent 26` | ✅ dạng bỏ `mươi` cũng chết vì cùng lý do |
| `Mở cửa sổ bên lái tầm năm mươi phần trăm` | `clarify / missing_window_position` | `percent 50` | ✅ |
| `Tăng âm lượng thêm mười` | `clarify / missing_volume` | `volume 10` | ⚠️ số đúng, nhưng ngữ nghĩa "thêm" vẫn bị nuốt — xem §5 |
| `Mở cửa sổ bên lái mười mấy phần trăm` | `clarify / missing_window_position` | `percent 10` | ❌ **thoái lui** — xem §3 |

33 câu còn lại **không đổi hành vi**. Nghĩa là mọi vấn đề ở §4–§6 đã tồn tại từ trước bản vá.

---

## 3. Thoái lui do chính bản vá gây ra

```
Mở cửa sổ bên lái mười mấy phần trăm    →    percent: 10
```

`"mười mấy"` nghĩa là 11–19, người nói cố tình không xác định. Trước đây bug #117 **vô tình** chặn
câu này thành `clarify`, vì token `trăm` của đơn vị làm `_number()` trả `None` sớm. Gỡ cái chặn đó
ra thì parser đi tiếp và nhặt `mười` = 10.

Đây thuộc phạm vi PR #117, không phải mở rộng phạm vi: nó là hệ quả trực tiếp của bản vá.

**Đề xuất:** guard `mấy`/`vài` trong `_number()` trả `None` để rơi về `clarify`. Khoảng 2 dòng
kèm test. Rủi ro thấp — `"mấy chục"` hiện đã `clarify`, guard này chỉ mở rộng cùng nguyên tắc.

---

## 4. Phân số — không hỗ trợ, và hỏng theo kiểu nguy hiểm

### 4.1 Dấu gạch chéo

`normalize_vi` (`src/agents/router.py:150`) xoá mọi ký tự không phải chữ/số/`%`, nên `1/3` biến
thành hai token `"1 3"`, rồi `_NUMBER_PATTERN` nhặt số **đầu tiên**:

| Câu | Ra | Đáng lẽ |
|---|---|---|
| `Mở cửa sổ bên lái 1/2` | **`percent 1`** | 50 |
| `Mở cửa sổ bên lái 1/3` | **`percent 1`** | 33 |
| `Mở cửa sổ bên lái 2/3` | **`percent 2`** | 67 |
| `Mở cửa sổ bên lái 3/4` | **`percent 3`** | 75 |
| `Đặt âm lượng 1/2` | **`volume 1`** | 50 |

Không câu nào hỏi lại. `_reject_ambiguous_number` không cứu được vì nó thoát sớm ngay khi thấy chữ
số (`router.py:259`) — chốt chặn số mơ hồ chỉ áp cho **từ số viết chữ**.

### 4.2 Phân số viết chữ

| Câu | Ra | Đáng lẽ |
|---|---|---|
| `Mở cửa sổ bên lái một phần ba` | **`percent 3`** | 33 |
| `Mở cửa sổ bên lái hai phần ba` | **`percent 3`** | 67 |
| `Mở cửa sổ bên lái ba phần tư` | **`percent 4`** | 75 |
| `Mở cửa sổ bên lái một phần tư` | **`percent 4`** | 25 |

Vòng quét ngược ở cuối `_number()` lấy từ số cuối cùng, tức mẫu số.

### 4.3 `một nửa` — hỗ trợ, nhưng là rule cứng của riêng cửa sổ

| Câu | Ra |
|---|---|
| `Mở cửa sổ bên lái một nửa` | `percent 50` ✅ |
| `Mở cửa sổ bên lái nửa thôi` | `percent 50` ✅ |
| `Hạ cửa kính bên lái xuống nửa` | `percent 50` ✅ |
| `Đặt âm lượng một nửa` | **`volume 1`** |
| `Ngả lưng ghế lái một nửa` | **`value 1`** |
| `Giảm âm lượng một nửa` | **`volume 1`** |

Ba dòng đầu chạy được nhờ `elif "một nửa" in text or "nửa" in text: percent = 50` tại
`_match_window:466` — một nhánh cứng, **không** phải năng lực của `_number()`. Vì vậy âm lượng và
ghế không thừa hưởng gì, và cùng một từ cho hai kết quả khác nhau tùy domain.

---

## 5. Lệnh tương đối — nhóm nghiêm trọng nhất

Router **không đọc vehicle state** (ADR-011 và `router.py:300-303`), nên không cộng trừ được từ mức
hiện tại. Với quạt gió, hệ quả đó được xử lý đúng: `"tăng quạt gió"` trả `clarify /
missing_fan_level` và để FE tự tính. Với âm lượng và cửa sổ thì **không**:

| Câu | Ra | Hậu quả nếu mức hiện tại khác |
|---|---|---|
| `Tăng âm lượng thêm 10` | `set_volume 10` | đang ở 60 thì **tụt xuống** 10 |
| `Tăng âm lượng thêm mười` | `set_volume 10` | như trên |
| `Giảm âm lượng đi 20 phần trăm` | `set_volume 20` | đang ở 10 thì **tăng lên** 20 |
| `Mở thêm cửa sổ bên lái 20 phần trăm` | `percent 20` | đang mở 80% thì **đóng bớt** |

Cùng một hạn chế kiến trúc, hai hành vi trái ngược nhau giữa các domain. Đây đúng lớp lỗi KI-001
(tuân thủ một phần trong im lặng) mà `docs/` đã đặt tên, và nó tệ hơn phân số vì `"tăng"`/`"giảm"`
là cách nói hằng ngày, không phải trường hợp biên.

Lưu ý phân biệt: `"Giảm âm lượng xuống 20"` → 20 là **đúng** (`xuống` chỉ đích tuyệt đối). Vấn đề
nằm ở `thêm` / `đi` / `bớt`.

---

## 6. Các sai lệch nhỏ hơn, có sẵn

| Câu | Ra | Ghi chú |
|---|---|---|
| `Đặt âm lượng hai chục` | `volume 2` | `chục` không có trong parser |
| `Mở cửa sổ bên lái một chút` | `percent 1` | `chút` bị bỏ, còn `một` |
| `Đặt điều hòa 22.5 độ` | `temperature_c 22` | dấu chấm bị `normalize_vi` xoá |
| `Đặt điều hòa hai mươi rưỡi độ` | `temperature_c 20` | `rưỡi` không có trong parser |

Hai dòng nhiệt độ có thể chấp nhận (hợp đồng là số nguyên °C), nhưng nên là quyết định có văn bản
chứ không phải tình cờ.

---

## 7. Nhóm hỏi lại đúng

| Câu | Ra |
|---|---|
| `Mở hé cửa sổ bên lái` | `clarify / missing_window_position` |
| `Mở cửa sổ bên lái tí thôi` | `clarify / missing_window_position` |
| `Mở cửa sổ bên lái hết cỡ` | `clarify / missing_window_position` |
| `Mở cửa sổ bên lái tối đa` | `clarify / missing_window_position` |
| `Mở toang cửa sổ bên lái` | `clarify / missing_window_position` |
| `Đặt âm lượng tối đa` | `clarify / missing_volume` |
| `Đặt âm lượng mấy chục` | `clarify / missing_volume` |
| `Mở cửa sổ bên lái trăm phần trăm` | `clarify / missing_window_position` |
| `Mở cửa sổ bên lái một hai ba phần trăm` | `clarify / ambiguous_number` |

Đây là hành vi mong muốn: không đoán lượng định tính.

**Một điểm không nhất quán trong nhóm này:** `"Mở hết cửa sổ bên phụ"` ra 100% nhưng
`"Mở cửa sổ bên lái hết cỡ"` lại `clarify`, vì rule khớp chuỗi liền `"mở hết"` (`_match_window:464`).
Kết quả phụ thuộc trật tự từ chứ không phụ thuộc ý nghĩa.

Hai câu vẫn từ chối đúng sau bản vá, đã có test khoá:

| Câu | Ra |
|---|---|
| `Đặt âm lượng một trăm hai mươi` | `denied / volume_out_of_range` |
| `Mở cửa sổ bên lái một trăm linh năm phần trăm` | `denied / window_position_out_of_range` |
| `Đặt âm lượng không phần trăm` | `denied / negated_command` |

---

## 8. Đề xuất phân chia công việc

| # | Việc | Ở đâu | Lý do |
|---|---|---|---|
| 1 | Guard `mấy`/`vài` → `clarify` | **PR #117** | Thoái lui do chính bản vá gây ra |
| 2 | Lệnh tương đối `thêm`/`đi`/`bớt` → `clarify` | Issue mới, **ưu tiên cao** | §5 — cách nói hằng ngày, hậu quả ngược ý |
| 3 | Phân số `1/2`, `một phần ba`, `một nửa` cho mọi domain | Issue mới | §4 — sai âm thầm nhưng cách nói ít gặp hơn |
| 4 | `chục`, `rưỡi`, `chút` | Issue mới, ưu tiên thấp | §6 |
| 5 | `hết cỡ` / `tối đa` = 100% | Issue mới, ưu tiên thấp | §7 — hiện `clarify`, tức an toàn |

*Đề xuất ban đầu là tách issue. Người chủ trì quyết định làm cả 5 trong cùng nhánh — xem §10.*

---

## 10. Kết quả sau khi sửa cả 5 nhóm

### 10.1 Thay đổi trong `src/agents/router.py`

| Thay đổi | Giải quyết |
|---|---|
| `normalize_vi` đổi dấu **giữa hai chữ số** thành từ (`/` → ` chia `, `.`/`,` → ` phẩy `) trước bước xoá dấu câu | `1/3` và `22,5` |
| `_fraction()` mới — đọc `(tử, mẫu)` từ cả chữ số lẫn chữ viết, cộng `nửa` = 1/2 | §4 |
| `_percent()` mới — thang 0..100 dùng chung cho **kính, ghế, âm lượng**: cụm "kịch mức" → 100, phân số → quy đổi, còn lại uỷ cho `_number` | §4.3, §7 |
| `_number()` trả `float`, tách guard ra khỏi `_words_to_number()` | `rưỡi`, `22,5` |
| `_INDEFINITE_TOKENS`, `_QUALITATIVE_TOKENS` → `None` | §3, §6 |
| `chục` vào `_TENS_TOKENS`; `trăm` không hệ số mặc định là 1 | §6, `trăm phần trăm` |
| `_reject_relative_change()` mới, chạy cạnh `_reject_ambiguous_number` trong `_run_matchers` | §5 |
| `_mentions_temperature` nhận thêm `mươi`/`chục`/`rưỡi` làm từ đứng trước `độ` | lượt ghép bỏ sót `"hai mươi độ"` |

Thêm `CLARIFY_MESSAGES["relative_change_unsupported"]` (`src/agents/nodes/compose.py`). Câu chung
ở đây tạo **vòng lặp**: tài xế nói "tăng thêm 10", nghe "bạn muốn điều chỉnh cụ thể như thế nào?",
rồi nói lại y hệt. Lời riêng phải nêu rằng cần một con số tuyệt đối.

### 10.2 Trước / sau, đo lại trên cùng tập khảo sát

| Câu | Trước | Sau |
|---|---|---|
| `Mở cửa sổ bên lái 1/2` · `1/3` · `2/3` · `3/4` | 1 · 1 · 2 · 3 | **50 · 33 · 67 · 75** |
| `Đặt âm lượng 1/2` | 1 | **50** |
| `một phần ba` · `hai phần ba` · `ba phần tư` · `một phần tư` | 3 · 3 · 4 · 4 | **33 · 67 · 75 · 25** |
| `Đặt âm lượng một nửa` · `Ngả lưng ghế lái một nửa` | 1 · 1 | **50 · 50** |
| `hết cỡ` · `tối đa` · `toang` · `Đặt âm lượng tối đa` | clarify ×4 | **100 ×4** |
| `Tăng âm lượng thêm 10` · `Giảm âm lượng đi 20 phần trăm` | 10 · 20 (tuyệt đối) | **clarify / `relative_change_unsupported`** |
| `Đặt điều hòa hai mươi rưỡi độ` · `22,5 độ` | 20 · 22 | **20,5 · 22,5** |
| `Đặt âm lượng hai chục` | 2 | **20** |
| `Mở cửa sổ bên lái trăm phần trăm` | clarify | **100** |
| `một chút` · `tí thôi` · `mười mấy phần trăm` | 1 · clarify · 10 | **clarify ×3** |

Không có ô nào đi theo chiều ngược lại.

### 10.3 Ranh giới giữ nguyên có chủ đích

| Câu | Vẫn là | Vì sao |
|---|---|---|
| `Giảm âm lượng xuống 20` | `volume 20` | `xuống` chỉ **đích** tuyệt đối, không phải mức thay đổi |
| `Đóng cửa sổ bên lái đi` | `percent 0` | `đi` là tiểu từ cầu khiến; chỉ tính tương đối khi đứng ngay trước một con số |
| `Mở hết cửa sổ bên phụ` | **một** kính 100% | không phải lệnh bốn kính |
| `Đặt điều hòa 1/2 độ` | `clarify` | phân số chỉ có nghĩa trên thang phần trăm |
| `Mở cửa sổ bên lái một hai ba phần trăm` | `clarify / ambiguous_number` | ba từ số liền nhau |
| `Đặt âm lượng một trăm hai mươi` | `denied / volume_out_of_range` | không nuốt hàng trăm |
| `Đặt âm lượng không phần trăm` | `denied / negated_command` | guard phủ định, không phải parser |
| `Mở hé cửa sổ bên lái` | `clarify` | `hé` là lượng định tính |

### 10.4 Nghiệm thu

| Kiểm tra | Kết quả |
|---|---|
| `pytest tests/ -q` (`MQTT_ENABLED=false`) | **1162 passed, 17 skipped** — 54 s, Python 3.11.9 |
| `ruff check src/ tests/` | sạch |
| `agent-intent/20260815T063730.094972Z` | `intent_accuracy` 1.0000 · `tool_exact` 1.0000 · 64 case |
| `agent-routing/20260815T063730.388889Z` | `question_recall` 0.9833 · `question_to_control` 0 · `command_accuracy` 1.0000 |

Không thêm case nào vào `eval/datasets/agent/v3` — nó là tripwire hồi quy do chính người viết
router soạn, nên `intent_accuracy` 1.0000 của nó vốn không nói gì về khái quát hoá. Đợt này thêm
**49 test** ở `tests/test_agents/test_router.py` (157 → 206) và **1** ở `test_clarify_messages.py`.

### 10.5 Nhóm thứ 6, tìm ra khi đối chiếu `"hai mươi lăm"` với `"hai lăm"`

Hai dạng đó đều ra 25 — đúng từ trước. Nhưng phép so ấy làm lộ **biến thể Bắc Bộ** không có
trong bảng từ số, và chúng hỏng im lặng:

| Câu | Trước | Sau |
|---|---|---|
| `hai mươi nhăm` · `hai nhăm` | 20 · 2 | **25 · 25** |
| `ba mươi bẩy` · `ba bẩy` | 30 · 3 | **37 · 37** |
| `hai mươi nhăm độ` | 20 °C | **25 °C** |

`nhăm` (5) và `bẩy` (7) không phải lỗi chính tả mà là cách nói chuẩn của một vùng phương ngữ
lớn; STT chép đúng cái người ta nói. Đây là câu gặp thật, không phải trường hợp biên.

---

## 9. Tái lập

Ba script khảo sát nằm trong scratchpad của phiên, không commit. Cách dựng lại nhanh nhất:

```powershell
$env:MQTT_ENABLED="false"
.\.venv\Scripts\python.exe -c "from src.agents.router import DeterministicControlRouter as R; d = R().route('Mở cửa sổ bên lái 1/3'); print(d.disposition, d.reason, d.candidate_plan.steps[0].args if d.candidate_plan else None)"
```

Để so trước/sau bản vá, vá ngược hai hằng số ở runtime:

```python
import re
from src.agents import router as R
R._PERCENT_UNIT_PATTERN = re.compile(r"(?!x)x")   # bỏ cắt hậu tố "phần trăm"
R._TENS_TOKENS = ("mươi",)                        # bỏ "mười"
```

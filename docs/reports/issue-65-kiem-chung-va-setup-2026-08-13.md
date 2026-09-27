# Issue #65 / PR #92 — Kiểm chứng, setup và cách test

> **Status: đã chạy thật trên máy dev 2026-08-13.** Mọi con số trong tài liệu này là output thật
> của lệnh đã chạy, không lấy từ tuyên bố của tài liệu khác. Nhánh `feat/issue-65-control-surface`
> tại commit `57a46d2`.
>
> Người viết: Sơn (WS3). Người nhận: PM/PO + Giáp (WS4).

## Kết luận một dòng

Bề mặt điều khiển mở rộng **chạy đúng xuyên toàn bộ pipeline** (router → policy → MQTT → simulator).
Cả ba điểm review nêu đã đóng: bàn giao FE là **BE-only** có văn bản (§2.1), câu ghép nhiệt độ + quạt
và câu mơ hồ `"tắt đèn"` đã sửa kèm test (§2.2), checklist 5 luồng ở §5.

Hai thứ còn lại **không** chặn merge nhưng phải biết trước khi hứa demo: FE chưa đọc `lights`/`trunk`
nên hai nút đó hiển thị sai vĩnh viễn, và **giọng nói chưa bật được trên máy này** (thiếu thư viện +
model, không phải thiếu code).

---

## 1. Trạng thái kiểm thử tự động

Sau khi gộp `develop` (`546d1f5`) và sửa hai điểm ở §2.2:

| Bộ | Kết quả | Ghi chú |
|---|---|---|
| `pytest tests/ -q` (`MQTT_ENABLED=false`) | **1065 passed, 20 skipped** — 57 s | Python 3.11.9 |
| `ruff check src/ tests/` | sạch | |
| `eval/results/mqtt-e2e/20260813T083452.464255Z` | **190/190 pass**, 4 tầng L0–L3 | L0 46 · L1 127 · L2 12 · L3 5 |
| `agent-intent/20260813T084722.857202Z` | `intent_accuracy 1.0000` · `tool_exact 1.0000` · 64 case | Tripwire hồi quy, **không** phải chỉ số generalization — xem cảnh báo ở §8 |
| `agent-routing/20260813T084723.140964Z` | `question_recall 0.9833` · `question_to_control 0.0000` | 60 câu hỏi |

`git merge-tree HEAD origin/develop` → **không xung đột**. ADR-019/020 không trùng số.

---

## 2. Ba điểm PM nêu

### 2.1 Bàn giao FE — **BE-only, và FE sẽ hiển thị SAI nếu không sửa**

PR không đụng file nào trong `frontend/`. Văn bản bàn giao đã có
(`docs/tasks/TASK-BE-FE-004-issue-65-command-vocabulary.md`) nhưng **chưa có ticket/PR FE**.

Sáu chỗ FE phải sửa, đối chiếu trực tiếp với code:

| Chỗ | Hiện tại | Hậu quả sau merge |
|---|---|---|
| `turn/real.ts:100-103` | hard-code `lights: false`, `trunk: "closed"` kèm comment *"BE chưa gửi field"* | Real mode: đèn **luôn** hiện tắt, cốp **luôn** hiện đóng |
| `turn/types.ts:31,39` | `lights: boolean`, `trunk: string` | Sai kiểu — BE trả object `{headlight, interior}` và `{position}` |
| `mock.ts:198` | kẹp fan `0..5` | BE là `0..3` |
| `mock.ts:334,355` | tool `control_trunk`, `control_lights` | Không phải tên canonical |
| `VehicleControlView.tsx:251,268` | `send("tăng/giảm quạt gió")` | → `clarify`, nút không hoạt động |
| `VehicleControlView.tsx:277` | toggle `"bật/tắt đèn pha"` | Nửa "tắt" → `denied` |

Nút cốp (`VehicleControlView.tsx:190`) chạy được ngay, không cần sửa.

### 2.2 Voice UX an toàn — một nửa xong, một nửa là regression

**Câu mơ hồ `"tắt đèn"` — ĐÃ ĐÚNG, ĐÃ CÓ TEST.**

```
'tắt đèn'  -> clarify  headlight_mode  missing_light_target
'bật đèn'  -> clarify  headlight_mode  missing_light_target
```

Test khoá hành vi: `tests/test_agents/test_router.py:674`, parametrize cả hai câu. Router **không đoán,
không thực thi**.

**Lời hỏi lại — ĐÃ SỬA 2026-08-13.** Trước đó câu người dùng nghe được là câu chung chung
(`OUTCOME_MESSAGES["clarify"]` là **một câu duy nhất cho mọi loại clarify**, và `missing_light_target`
chỉ nằm trong `RouteDecision`, không bao giờ thành lời).

Nay `CLARIFY_MESSAGES` (`src/agents/nodes/compose.py`) ánh xạ `route_reason` → câu hỏi cụ thể:

```
tắt đèn        → "Bạn muốn đèn pha hay đèn trần?"
tăng quạt gió  → "Bạn muốn quạt gió ở mức mấy, từ 0 đến 3?"
giảm nhiệt độ  → "Bạn muốn đặt nhiệt độ bao nhiêu độ, từ 16 đến 30?"
```

Chỉ phủ những lý do có **tập lựa chọn đóng và ngắn**; lý do khác rơi về câu chung, và có test khoá
đúng điều đó để router thêm lý do mới không làm vỡ compose. Test:
`tests/test_agents/test_clarify_messages.py` (7 test).

**Câu ghép nhiệt độ + quạt — ĐÃ SỬA 2026-08-13.**

Trước khi sửa:

```
'bật điều hòa 22 độ và quạt gió mức 2'   -> denied  fan_level_out_of_range
'chỉnh nhiệt độ 24 độ và tăng quạt gió'  -> denied  fan_level_out_of_range
```

Nhánh `if fan:` đặt trước nhánh nhiệt độ và `return` ngay, mà `_number()` quét **cả câu** nên nhặt
đúng số 22 của nhiệt độ rồi đo theo dải quạt `0..3` — mất ý nhiệt độ **và** báo sai lý do. Trên
`develop` câu đầu còn chạy được nửa nhiệt độ, nên đây là **regression** chứ không phải khoảng trống
có sẵn. Đúng lớp lỗi **KI-001** mà comment trong `_match_hvac` tuyên bố tránh — nó chỉ tránh được cho
câu đơn.

Sau khi sửa (`_match_hvac_compound` trong `src/agents/router.py`): tách theo liên từ ` và ` rồi đọc số
**trong từng vế**, vì mỗi vế lúc đó là một câu đơn và `_number` đã đúng cho câu đơn từ trước.

| Câu | Kết quả mới |
|---|---|
| `bật điều hòa 22 độ và quạt gió mức 2` | **3 bước**: power + temp 22 + fan 2 |
| `chỉnh nhiệt độ 24 độ và quạt gió mức 1` | 2 bước: temp 24 + fan 1 |
| `chỉnh quạt gió mức 2 và nhiệt độ 20 độ` | 2 bước — thứ tự vế không quan trọng |
| `bật điều hòa hai mươi hai độ và quạt gió mức 2` | 3 bước — số viết chữ vẫn đọc đúng |
| `chỉnh nhiệt độ 24 độ và tăng quạt gió` | `clarify/missing_fan_level` — **không** chạy nửa nhiệt độ |
| `bật điều hòa 22 độ và quạt gió mức 5` | `denied/fan_level_out_of_range` — đúng vế, đúng lý do |
| `bật điều hòa 40 độ và quạt gió mức 2` | `denied/temperature_out_of_range` |

Cùng đợt sửa luôn một regression cùng lớp mà review chưa nêu: **`"tắt điều hòa và quạt gió"`** trước
đó chỉ hạ quạt về 0 và nuốt mất ý tắt điều hòa; nay ra 2 bước.

Hai bẫy có test khoá riêng:

- **`tốc độ` không phải nhiệt độ.** `"chỉnh tốc độ quạt gió mức 2"` chứa `độ` nhưng không nói gì về
  nhiệt độ. Bộ nhận diện xét **từ đứng ngay trước** `độ` (`nhiệt` / chữ số / từ số), không xét sự có
  mặt của `độ`.
- **Ghép chéo domain vẫn là khoảng trống có sẵn.** `"bật quạt gió mức 2 và bật đèn trần"` vẫn bỏ vế
  đèn — matcher đầu tiên khớp thì thắng (`_run_matchers`). `_match_hvac_compound` **cố ý** không nhận
  việc này; sửa nó là thay đổi kiến trúc router, không phải nới một hàm HVAC. Có test ghi lại nguyên
  trạng để lần sau không ai tưởng nhầm.

Test: 10 test mới trong `tests/test_agents/test_router.py`.

> Đối chiếu số: suite từ **1043 → 1065 passed**, 20 skipped. `ruff check` sạch. Hai bộ eval **không
> đổi** (`intent_accuracy 1.0000`, `question_recall 0.9833`) — đúng như mong đợi, vì
> `eval/datasets/agent/v3` không có case quạt nào. Đó là một khoảng trống của dataset, ghi ở §8.

### 2.3 Demo acceptance checklist — xem §5

`docs/demo_script.md` là kịch bản cũ, status **Planned**, không phủ luồng nào trong 5 luồng mới.

---

## 3. Setup — hai cái bẫy, một cái đã cắn

> Runbook đầy đủ (backend + frontend + giọng nói + sự cố thường gặp) tách sang
> [`docs/huong_dan_chay.md`](../huong_dan_chay.md) — tài liệu này thay thế `local_setup.md` từ
> 2026-08-15. Mục này chỉ giữ phần liên quan trực tiếp tới issue #65.

### 3.1 Bẫy đã cắn: backend không boot với `.env` cũ (issue #93)

```
ValueError: unsupported DATABASE_URL scheme: 'postgresql://user:password@localhost:5432/dbname'
```

Backend chết **lúc import**, không phải lúc khởi động. `.env` không được git track nên bản sửa
`.env.example` ở #89 không migrate máy của ai. Đã sửa `.env` dòng 14:

```
DATABASE_URL=sqlite:///./data/app.db
```

Fix chính thức (thông báo lỗi nói đủ ba thứ + bỏ hai singleton mở DB ở module level) nằm ở
`607c19f` trên `develop` — **nhánh này chưa có**, nên phải gộp.

### 3.2 Bẫy chưa cắn (nhưng có thật): snapshot retained 7 domain

`config/mosquitto/mosquitto.conf` bật `persistence true` và compose gắn named volume
`mosquitto_data`, nên retained snapshot **sống qua cả `docker compose down`**. Simulator chạy từ
trước PR chỉ publish 7 domain → backend mới từ chối → `GET /vehicle/state` trả **503
`no_snapshot_yet`** → agent từ chối mọi lượt. Tắt/bật backend **không** chữa được.

Trên máy dev 2026-08-13 bẫy này **không xảy ra** — image simulator đã dựng lại, snapshot trên broker
đã đủ 9 domain (`observed_at 2026-08-13T07:42:31Z`). Nhưng máy khác thì phải:

```powershell
docker compose up -d --build --force-recreate vehicle-simulator
```

### 3.3 Trình tự dựng đầy đủ

```powershell
git checkout feat/issue-65-control-surface
git merge origin/develop

pwsh scripts/bootstrap_mqtt_secrets.ps1
docker compose up -d --wait mqtt
docker compose up -d --build --force-recreate vehicle-simulator
```

Simulator standalone (khuyến nghị cho demo — có REPL đổi tốc độ `speed 45` / `gear D` / `stop` / `state`):

```powershell
.\.venv311\Scripts\python.exe -m src.vehicle_sim
```

Backend (**không** dùng `uvicorn src.main:app` trên Windows — ProactorEventLoop làm paho-mqtt ném
`NotImplementedError`):

```powershell
.\.venv311\Scripts\python.exe -m src.serve
```

Kiểm đường dây:

```powershell
.\.venv311\Scripts\python.exe scripts\smoke_mqtt.py
.\.venv311\Scripts\python.exe scripts\validate_mqtt_schemas.py
curl http://127.0.0.1:8000/healthz
```

> `.env` máy dev đặt `MQTT_HOST_PORT=1884` (cổng 1883 đã bị thứ khác giữ).

---

## 4. Toàn bộ vốn từ lệnh — 15 tool / 9 domain

Output thật của `DeterministicControlRouter`. 🆕 = mới ở issue #65.

### Điều hòa

| Câu | Kết quả |
|---|---|
| `bật điều hòa` / `tắt điều hòa` | `set_hvac_power` |
| `bật điều hòa 25 độ` | **2 bước**: power + `set_hvac_temperature 25` |
| `chỉnh nhiệt độ 22 độ` | `set_hvac_temperature` (16–30) |
| `chỉnh nhiệt độ 35 độ` | `denied/temperature_out_of_range` |
| `giảm nhiệt độ` | `clarify/missing_temperature` |
| 🆕 `chỉnh quạt gió mức 3` | `set_hvac_fan_level {level:3}` (0–3) |
| 🆕 `tắt quạt gió` | `set_hvac_fan_level {level:0}` |
| 🆕 `tăng quạt gió` | `clarify/missing_fan_level` — client phải gửi **mức tuyệt đối** |
| `chỉnh quạt gió mức 5` | `denied/fan_level_out_of_range` (không kẹp về biên) |

### Nhạc

| Câu | Kết quả |
|---|---|
| `phát nhạc` / `bật nhạc` | `play` |
| `tạm dừng nhạc` / `dừng nhạc` | `pause` |
| `chuyển bài nhạc` · 🆕 `chuyển bài` · 🆕 `bài tiếp theo` | `next` |
| 🆕 `bài trước` · 🆕 `quay lại bài trước` | `previous` |
| `đặt âm lượng 40` | `set_volume` (0–100) |

### Cửa sổ — S2 **luôn luôn**

| Câu | Kết quả |
|---|---|
| `mở cửa sổ bên lái 30%` | 1 kính |
| `đóng cửa sổ bên phụ` | percent 0 |
| `mở hết cửa sổ bên phụ` | percent 100 — **`hết` nghĩa là "mở hết cỡ", không phải "tất cả"** |
| 🆕 `mở tất cả cửa sổ 50%` / `mở toàn bộ cửa sổ 100%` | **4 bước** |
| `mở cửa sổ` | `clarify/missing_window_side` |

### Ghế — chỉ 2 ghế trước

`chỉnh sưởi ghế lái mức 2` (0–3, S1) · `tắt sưởi ghế phụ` · `ngả lưng ghế lái 60` ·
`đẩy ghế lái về trước 30` · `nâng ghế lái 70` (0–100, S2 khi đứng yên).

### Cửa xe — S2 đứng yên / S3 đang chạy

| Câu | Kết quả |
|---|---|
| `mở cửa bên lái` / `mở cửa sau bên trái` | 1 cửa |
| 🆕 `mở cửa` / `đóng cửa` | **4 bước, một phê duyệt gộp liệt kê đủ bốn cửa** |

### 🆕 Cốp — S2 đứng yên / S3 đang chạy

`mở cốp` · `đóng cốp` · `mở cốp sau` · `mở khoang hành lý`

### 🆕 Đèn — S1 ở mọi trạng thái xe

| Câu | Kết quả |
|---|---|
| `bật đèn pha` / `bật đèn chiếu gần` / `bật đèn cốt` | `low_beam` |
| `bật đèn chiếu xa` | `high_beam` |
| `bật đèn tự động` / `chuyển đèn sang chế độ tự động` | `auto` |
| `bật/tắt đèn trần` · `đèn nội thất` · `đèn trong xe` | `set_interior_light` |
| `tắt đèn pha` | `denied/headlight_off_not_permitted` — UNECE R48, ADR-020 |
| `bật đèn` / `tắt đèn` | `clarify/missing_light_target` |
| `bật đèn sương mù` / `đèn đọc sách` | rơi xuống **tra sổ tay**, không phải clarify |

### Dẫn đường — chỉ 3 đích hard-code

`trạm sạc`→`poi-charge-01` · `cà phê`→`poi-cafe-01` · `bình minh`/`thứ hai`→`poi-cafe-02` ·
`dẫn đường tới sân bay` → `clarify/unknown_local_destination` · `hủy dẫn đường` chạy.

### Chặn và mơ hồ

`kéo phanh tay` / `tắt động cơ` → `denied/unsupported_actuator` · `mở nó ra` →
`clarify/ambiguous_reference` · `đừng mở cửa sổ` → `denied/negated_command` ·
`đặt âm lượng một hai ba` → `clarify/ambiguous_number` · `đặt âm lượng hai bốn` → volume **24**.

---

## 5. Checklist nghiệm thu tay — 5 luồng mới

Đăng nhập `driver.demo@example.com` / `DemoDriver123!`. Mọi request cần đủ 3 header:
`Authorization: Bearer …`, `X-Schema-Version: 1.0`, `Idempotency-Key: <duy nhất mỗi lần>`
(kể cả `POST /sessions`).

> **Nghiệm thu ở tầng `/ws/ivi` + `GET /vehicle/state`, KHÔNG ở màn hình IVI** — vì FE chưa đọc
> `lights`/`trunk` (§2.1). Đây đúng là điều PM lo: "BE chạy nhưng demo chưa dùng được".

| # | Luồng | Câu gửi | Tiền đề | Mong đợi |
|---|---|---|---|---|
| 1 | Bài trước | `bài trước` | — | `media_control {action:"previous"}` |
| 2 | Tất cả cửa (HITL) | `mở cửa` | `speed 0`, `gear P` | `approval.required`, summary liệt kê **đủ 4 cửa**; duyệt → 4 × `set_door_state` |
| 3 | Quạt mức tuyệt đối | `chỉnh quạt gió mức 3` | — | `hvac.fan_level = 3`. Đối chứng: `mức 5` → `denied`; `tăng quạt gió` → `clarify` |
| 4a | Cốp đứng yên | `mở cốp` | `speed 0`, `gear P` | S2 → `approval.required`; duyệt → `trunk.position = "open"` |
| 4b | Cốp đang chạy | `mở cốp` | gõ `speed 45` ở REPL simulator | S3 → **chặn thẳng**, không approval, `trunk` không đổi |
| 5a | 3 chế độ đèn | `bật đèn tự động` / `bật đèn pha` / `bật đèn chiếu xa` | — | `lights.headlight` = `auto` / `low_beam` / `high_beam` |
| 5b | Đèn nội thất | `bật đèn trần` → `tắt đèn trần` | — | `lights.interior` `true` → `false` |
| 5c | Biên đèn | `tắt đèn pha` | — | `denied/headlight_off_not_permitted` |
| 5d | Đèn mơ hồ | `tắt đèn` | — | `clarify` — ⚠ lời hỏi lại hiện **chung chung**, xem §2.2 |
| 5e | Đèn ngoài phạm vi | `bật đèn sương mù` | — | tra sổ tay, **không** phải clarify |

### Kết quả chạy thật 2026-08-13 (qua HTTP, xuyên tới simulator)

```
bật đèn chiếu xa      → set_headlight_mode{high_beam}  => headlight=high_beam   v1→v2  ✓
bật đèn trần          → set_interior_light{True}       => interior=True         v3     ✓
chỉnh quạt gió mức 2  → set_hvac_fan_level{2}          => fan=2                 v4     ✓
bài trước             → media_control{previous}        =>                       v5     ✓
mở cốp                → set_trunk_state{open}   "Tôi sẽ mở cốp sau. Bạn có đồng ý không?"  ✓ S2
tắt đèn pha           → "Xin lỗi, tôi không thực hiện được yêu cầu này."               ✓ denied
tắt đèn               → "Bạn muốn điều chỉnh cụ thể như thế nào?"                      ⚠ §2.2
bật điều hòa 22 độ và quạt gió mức 2 → "Xin lỗi, tôi không thực hiện được yêu cầu này." ✗ §2.2
```

---

## 6. Nhận diện giọng nói — **code đủ, máy chưa bật được**

### 6.1 CLAUDE.md đã lỗi thời ở mục này

CLAUDE.md viết *"The IVI never records audio"* và *"nothing goes microphone → STT → TTS → speaker"*.
Không còn đúng — PR #88 (`feat/fe-voice-mic-capture`) và #82 (`feat/fe-tts-audio-playback`) đã merge
vào `develop`.

| Mắt xích | Trạng thái | Chứng cứ |
|---|---|---|
| Ghi âm mic | ✅ có | `frontend/src/lib/audio/wavRecorder.ts` — WAV 16-bit PCM mono **16 kHz**, `AudioWorkletNode` |
| Gửi lên BE | ✅ có | `DriverShellProvider.tsx:267` — ghi thật, không còn `Blob()` rỗng |
| STT | ✅ có | `src/services/voice.py` — sherpa-onnx Zipformer-30M |
| TTS | ✅ có | Piper, phát event `assistant.speech` |
| Phát tiếng ở FE | ✅ có | `DriverShellProvider.tsx:168` — `new Audio(data:...).play()` |

Cố ý **không** dùng `MediaRecorder`: nó chỉ ghi ra container nén (webm/opus), backend đòi WAV 16 kHz
mono. Cũng cố ý **không** dùng `ScriptProcessorNode`: Chrome đình chỉ nó sau ~2 s khi graph nối ra
gain im lặng, cắt cụt bản ghi.

### 6.2 Nhưng trên máy dev thì **CHƯA CHẠY**

`GET /healthz` lúc 2026-08-13:

```
backend             ready
mqtt                ready
vehicle_simulator   ready
rag_index           ready
sqlite              ready
llm                 down   slm_disabled        ← đúng thiết kế, ĐÃ miễn trừ khỏi gate (§7)
stt                 down   stt_unavailable     ← ✗ đây mới là thứ gây 503
tts                 down   tts_unavailable     ← ✗
```

HTTP status = **503**. Nhưng nguyên nhân là `stt`/`tts`, **không** phải `llm` — xem §7.

Nguyên nhân đã kiểm:

- `sherpa_onnx` **không có** trong `.venv311` (cũng không có trong `.venv`)
- thư mục **`models/voice/` không tồn tại** — không có Zipformer, không có giọng Piper
- `piper` (python package) thì **có**, nhưng thiếu file giọng

Hệ quả nếu bấm mic bây giờ: ghi âm thành công, backend ném lỗi ở `get_stt_engine()` →
`turn.failed / INTERNAL_ERROR`. Không phải `STT_FAILED` — nhánh đó chỉ dành cho audio hỏng thật
(`turns.py:228-234` cố ý tách hai loại để hệ thống không đổ lỗi oan cho micro tài xế).

### 6.3 Cách bật (cần mạng — chỉ lúc setup, không phải runtime)

```powershell
.\.venv311\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv311\Scripts\python.exe -m pip install "huggingface_hub[cli]"
pwsh scripts/setup_voice_models.ps1
```

Script tải Zipformer-30M-RNNT-6000h, pin revision `24ed30248e1c96bb690c81c24ab4e056f8cd9fce`,
license `cc-by-nc-nd-4.0` (phi thương mại, không phái sinh — hợp với đồ án học thuật), và ghi
`.sha256` + `.metadata.json` cho mỗi artifact.

**TTS phải tải tay** — script chỉ in hướng dẫn: lấy một giọng Việt Piper (`.onnx` + `.onnx.json`)
từ `rhasspy/piper` VOICES.md, đặt vào `models/voice/`, **đặt tên `vi_VN-piper.onnx`** cho khớp
`Settings.tts_model_path`.

**Cổng nghiệm thu:** đọc **component** `stt` và `tts` trong body của `/healthz`, phải = `ready`.

> **Đừng dùng HTTP status làm cổng.** `/healthz` trả 503 vì nhiều lý do khác nhau; xem §8.

```powershell
curl -s http://127.0.0.1:8000/healthz | python -m json.tool
```

### 6.4 Demo giọng nói thế nào

FE phải ở **real mode** — cả ba cờ `NEXT_PUBLIC_USE_MOCK_TURN`, `NEXT_PUBLIC_USE_MOCK_SESSION`,
`NEXT_PUBLIC_USE_MOCK_ENGINEER` về `false`. Mic **chỉ hoạt động trên `localhost` hoặc HTTPS** —
`getUserMedia` bị trình duyệt chặn trên HTTP thường.

```powershell
cd frontend; npm run dev
```

Luồng: `/driver` → chạm mic → nói `"bật đèn chiếu xa"` → overlay hiện transcript → xe đổi state →
nghe câu trả lời phát ra loa. Tự dừng sau `MAX_RECORDING_MS`, hoặc chạm mic lần nữa để gửi.

**Hai thứ vẫn hỏng dù đã bật giọng nói:**

- Đèn/cốp trên màn hình **luôn hiện sai** (`real.ts:100-103` hard-code) — §2.1.
- `approval.intent.detected` chưa có → **không duyệt HITL bằng giọng nói được**. Câu "Đồng ý" phải
  bấm nút trên hộp thoại. Kịch bản demo nào có câu duyệt bằng miệng thì phải bỏ.

---

## 7. Ghi chú cho issue #95 — `/healthz` 503: một nửa tiền đề đã lỗi thời

Issue #95 cho rằng `/healthz` **luôn** 503 ở cấu hình mặc định vì `llm=down` khi `slm_enabled=False`.
Đo trên nhánh này 2026-08-13 thì **không đúng nữa**: `llm` **đã được miễn trừ** khỏi readiness gate.

```python
# src/services/health.py:49
REQUIRED_COMPONENT_NAMES: frozenset[str] = frozenset(COMPONENT_NAMES) - {"llm"}
```

Vào từ `b2e5724` *"fix(health): exempt llm from /healthz readiness gate at P0"* (issue #48), có mặt
trên cả `develop` lẫn nhánh này, và **đã có test khoá**:

- `tests/test_api/test_health.py:124` — `test_healthz_returns_200_when_only_llm_is_down`
- `tests/test_api/test_health.py:115` — `test_llm_is_exempt_from_the_required_component_gate`
- `tests/test_services/test_health.py:25` — cùng bất biến ở tầng payload event

`llm` vẫn hiện trong `components` và `faults` (cố ý — không giấu trạng thái thật), nhưng **không**
kéo tổng thể xuống 503.

**Vậy 503 đo được đến từ đâu?** Từ `stt` và `tts`, vì máy dev chưa cài `sherpa_onnx` và chưa có
`models/voice/` (§6.2). Đó là dependency **thiếu thật**, báo `down` là **đúng** — không phải cùng
lớp với "thành phần bị tắt có chủ đích".

**Phần vẫn còn nguyên giá trị của #95:** nhánh `mqtt`. `probe_mqtt` (`health.py:102`) trả
`down/mqtt_not_connected` khi `runtime is None`, tức đúng cả khi người vận hành **cố ý** đặt
`MQTT_ENABLED=false`; và `mqtt` **vẫn nằm trong** `REQUIRED_COMPONENT_NAMES`. `vehicle_simulator`
cũng down theo. Đây mới là chỗ "một lựa chọn tường minh bị báo cáo như một sự cố".

**Đề nghị:** thu hẹp #95 lại còn câu hỏi hợp đồng cho `mqtt` (và `vehicle_simulator` kéo theo),
bỏ phần `llm` vì #48 đã trả lời bằng phương án (b)-cho-riêng-`llm`: giữ `down` trong `components`
nhưng loại khỏi gate. Nếu chọn cùng phương án cho `mqtt` thì có sẵn tiền lệ và sẵn hình mẫu code.
Dòng 30 của `docs/tasks/TASK-FE-BE-001` cũng nên sửa theo, vì nó vẫn mô tả trạng thái trước #48.

> Không thuộc phạm vi PR #92 — ghi ở đây vì đo được trong lúc dựng máy demo cho issue #65.

---

## 8. Việc phải làm, theo thứ tự chặn demo

| # | Việc | Owner | Chặn merge? | Trạng thái |
|---|---|---|---|---|
| 1 | `git merge origin/develop` — mang fix #93 (backend không boot) + #94 | Sơn | **Có** | ✅ xong (`546d1f5`) |
| 2 | Sửa câu ghép quạt + nhiệt độ, kèm test | Sơn | **Có** — regression | ✅ xong (§2.2) |
| 3 | Câu clarify nói rõ lựa chọn ("đèn pha hay đèn trần?") | Sơn | Nên | ✅ xong (§2.2) |
| 4 | Chạy lại `report_mqtt_e2e.py` + 2 eval sau khi gộp develop | Sơn | Nên | ✅ xong — xem §1 |
| 5 | Issue FE: 6 dòng ở §2.1 | Giáp | Không | ⬜ chưa mở |
| 6 | Cài `[voice]` + tải model nếu demo cần giọng nói | ai dựng máy demo | Không | ⬜ |
| 7 | Thu hẹp issue #95 — phần `llm` đã do #48 giải quyết, chỉ còn `mqtt` (§7) | Nhân | Không | ⬜ |
| 8 | Thêm case quạt + case ghép vào `eval/datasets/agent/v3` | Sơn | Không | ⬜ |

**Về mục 8:** `eval/datasets/agent/v3/cases.jsonl` hiện **không có case `quạt` nào** — 14 case `hvac`
đều là nguồn/nhiệt độ. Nên `intent_accuracy 1.0000` không nói gì về quạt gió, và cũng không nói gì về
đèn (không có domain `lights`). Bản thân dataset là **tripwire hồi quy**, không phải thước đo tổng
quát (do chính người viết router viết ra) — nhưng một tripwire không phủ tính năng mới thì không bảo
vệ được nó. Thêm case là việc riêng, vì nó sinh evidence run-id mới.

---

## Phụ lục — thay đổi cấu hình local đã thực hiện

| File | Thay đổi | Lý do |
|---|---|---|
| `.env` dòng 14 | `postgresql://…` → `sqlite:///./data/app.db` | Issue #93 — backend chết lúc import. `.env` không được git track nên thay đổi này **chỉ có trên máy dev**, mỗi người phải tự sửa. |

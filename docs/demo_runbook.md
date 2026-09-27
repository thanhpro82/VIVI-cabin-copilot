# Kịch bản demo VIVI Cabin Copilot

> **Status: Chạy được trên PC.** Mọi câu lệnh thoại trong §Kịch bản demo được đối chiếu trực tiếp
> với matcher trong `src/agents/router.py`, không lấy từ tài liệu khác; mọi mô tả về nút bấm đối
> chiếu trực tiếp với `frontend/src/components/ivi/`. Đối chiếu lần gần nhất với `develop` @
> `4fb40fd` ngày 2026-08-16 — tức đã bao gồm PR #121 (FE đọc `lights`/`trunk` thật, nút quạt gió,
> bộ chọn chế độ đèn) và PR #141 (gộp ba hướng dẫn thành một runbook).

**Đây là artifact demo, không phải nguồn setup.** Cách dựng máy và khởi động hệ thống chỉ có **một**
nguồn duy nhất là [`huong_dan_chay.md`](huong_dan_chay.md); file này giả định hệ đã chạy được và chỉ
trả lời hai câu: **diễn cái gì thì chạy thật**, và **không được hứa cái gì**.

| Cần gì | Đọc ở đâu |
|---|---|
| Dựng máy lần đầu — `.env`, broker, chỉ mục RAG, model giọng nói | [`huong_dan_chay.md`](huong_dan_chay.md) PHẦN II |
| Khởi động, tài khoản demo, lệnh xe mô phỏng, dừng hệ thống | [`huong_dan_chay.md`](huong_dan_chay.md) PHẦN I |
| `/healthz`, kiểm trạng thái xe, chạy test, sinh evidence | [`huong_dan_chay.md`](huong_dan_chay.md) PHẦN III |
| Hỏng giữa chừng, tra cứu sự cố đầy đủ | [`huong_dan_chay.md`](huong_dan_chay.md) PHẦN V |
| Bản đồ hiện trạng bề mặt điều khiển | [`coverage_matrix.md`](coverage_matrix.md) — nguồn của §Ranh giới phải nói rõ |
| Kịch bản 5 phút bản cũ | [`demo_script.md`](demo_script.md), status **Planned**. Nó mô tả voice-approval và use case "tìm cà phê" — **hai thứ chưa implement**. Đừng diễn theo nó |

---

## Phần 1 — Chuẩn bị riêng cho buổi demo

Ba mục dưới đây **không** trùng runbook chính: chúng chỉ cần khi có khán giả ngồi trước mặt.

### 1.1 Ba chỗ demo phải làm khác ngày thường

| Việc | Khi demo | Vì sao |
|---|---|---|
| Xe mô phỏng | Chạy **bằng tay** (`python -m src.vehicle_sim`), **không** `docker compose up -d vehicle-simulator` | Bản chạy tay có REPL đổi tốc độ (`speed 45` · `gear P` · `stop` · `state`) — bắt buộc để diễn nhánh S3. Bản Docker không gõ vào được |
| Frontend | **Real mode**: cả ba cờ `USE_MOCK` trong `frontend/.env.local` phải `false` | Thiếu một cờ là còn nửa hệ thống chạy giả. Ảnh chụp ở mock mode **không chứng minh gì** về backend — xem §Ranh giới |
| Model giọng nói | Cài trước ([`huong_dan_chay.md`](huong_dan_chay.md) §2.6) | Thiếu thì bấm mic lỗi `INTERNAL_ERROR` và `/healthz` trả 503. Bỏ qua được nếu chấp nhận demo bằng gõ chữ |

### 1.2 Cổng nghiệm thu trước khi lên sân khấu

Khởi động theo [`huong_dan_chay.md`](huong_dan_chay.md) PHẦN I, rồi chạy đúng ba kiểm tra này:

```powershell
.\.venv\Scripts\python.exe scripts\validate_mqtt_schemas.py
curl.exe -s http://localhost:8000/healthz
curl.exe -s http://localhost:8000/api/v1/vehicle/state
```

Ba lệnh này **không cần token** và chạy được kể cả khi backend vừa mới lên — đó là lý do chúng ở
đây thay vì `scripts\smoke_mqtt.py`. Smoke đầy đủ ba acceptance criteria vẫn đáng chạy nếu còn
thời gian, nhưng nó cần cả broker, xe ảo và backend cùng sống, **và hợp đồng auth của nó đổi theo
`develop`** — trước khi dựa vào nó, đọc [`huong_dan_chay.md`](huong_dan_chay.md) §3.2 để biết trên
bản đang có nó chạy được hay không (issue #143).

**Ở `/healthz`, đọc từng component, đừng đọc HTTP status.** Bảng đầy đủ ở
[`huong_dan_chay.md`](huong_dan_chay.md) §3.1; hai dòng hay làm người trình bày hoảng ngay trước giờ diễn:

- `llm: disabled / slm_disabled` là **bình thường**. `slm_enabled=False` là mặc định của repo
  (ADR-006/ADR-010) và đã được miễn khỏi readiness gate ở issue #48, nên nó **không** kéo 503. Là
  `disabled`, **không phải `down`** — issue #95 tách riêng hai trạng thái đó (`probe_llm` trong
  `src/services/health.py`) đúng để người vận hành khỏi đi tìm một sự cố không tồn tại.
- `stt`/`tts` ở `down` thì `/healthz` trả **503**, và đó là đúng: vẫn demo được trọn luồng điều
  khiển, chỉ mất nút mic.

Ở `/vehicle/state` phải thấy **đủ 9 domain**: `motion hvac windows doors media navigation seat
lights trunk`. Thiếu `lights`/`trunk` nghĩa là đang chạy simulator cũ — xem §Sự cố #1.

### 1.3 Làm nóng RAG trước khi có khán giả

Lượt tra sổ tay **đầu tiên** phải nạp embedder E5 và mất **~32 s** (`@lru_cache` trong
`src/agents/nodes/rag_node.py`). Hỏi trước một câu bất kỳ về sổ tay để trả giá đó lúc chưa ai nhìn.
Không làm bước này thì câu hỏi mở màn của buổi demo treo nửa phút.

---

## Phần 2 — Kịch bản demo

Thứ tự S0 → S1 → S2 → S3 là có chủ đích: nó dựng dần mức rủi ro, và cao trào là **cùng một câu lệnh
cho ra hai kết cục khác nhau tùy tốc độ xe**.

Mọi câu dưới đây đã đối chiếu với matcher thật. Cột "khớp ở đâu" để bạn tự kiểm khi router đổi.

### Màn 0 — Tra sổ tay có trích dẫn (S0)

> *"Đèn cảnh báo áp suất lốp có nghĩa là gì?"*

Mở citation để thấy nó chỉ đúng tài liệu/mục/trang/`chunk_id` trong `data/manuals/vf9_2026_vi/`
(58 tài liệu → 482 chunk).

Điểm cần nói: composer **trích nguyên văn**, cố ý không diễn giải lại. ADR-015 ghi rằng cho SLM viết
lại chunk đo được 4/40 câu trả lời sai lệch, đều do rơi mất điều kiện biến thể (ECO/PLUS, SDI/CATL),
so với 0/40 khi trích nguyên văn.

### Màn 1 — Điều khiển trực tiếp (S1, không cần duyệt)

| Câu nói | Kết quả | Khớp ở đâu |
|---|---|---|
| *"Bật điều hòa lên 25 độ"* | Plan **2 bước**: `set_hvac_power` → `set_hvac_temperature` | `router.py:312-326` |
| *"Đặt quạt gió mức 2"* | `set_hvac_fan_level` (dải 0–3) | `router.py:296-307` |
| *"Bật đèn chiếu gần"* | `set_headlight_mode` = `low_beam` | `router.py:598` |
| *"Bật sưởi ghế lái mức 2"* | `set_seat_heating` front_left | `router.py:498-512` |
| *"Chuyển bài"* | `media_control` action `next` | `router.py:449` |
| *"Dẫn đường tới quán cà phê"* | `set_navigation` → `poi-cafe-01` | `router.py:621-626` |

Câu 2 bước là điểm đáng dừng lại: bản PoC trả về ngay khi thấy *"bật điều hòa"* và **nuốt mất con
số 25** — tuân thủ một phần trong im lặng, tệ hơn cả từ chối. Đó là lớp lỗi KI-001.

**Diễn bằng nút bấm cũng được, và nút gửi đúng những câu trên** (từ PR #121, `frontend/src/components/ivi/`):

| Nút | Câu nó gửi | Ở đâu |
|---|---|---|
| Quạt gió `+` / `−` | `đặt quạt gió mức N` — FE tự cộng trừ trong `0..3` rồi gửi **mức tuyệt đối** | `VehicleControlView.tsx:125` |
| Đèn pha — 3 nút chọn thẳng | `chuyển đèn sang chế độ tự động` / `bật đèn chiếu gần` / `bật đèn chiếu xa` | `VehicleControlView.tsx:317-335`, hằng số ở `headlightControl.ts` |
| Đèn pha ở trang chính | cùng 3 câu trên, nhưng **một nút xoay vòng** `auto → chiếu gần → chiếu xa → auto` | `RightPanel.tsx:26`, `HEADLIGHT_CYCLE` |
| Khoá cửa lại / Mở khoá cửa | `đóng cửa` / `mở khóa cửa` — fan-out đủ 4 cửa | `RightPanel.tsx:45` |

Hai chi tiết đáng nói khi có người hỏi *"sao không làm toggle cho gọn"*: đèn pha là **enum 3 trạng
thái không có `off`**, nên toggle hai chiều sẽ có đúng một nửa không bao giờ chạy; và nút quạt phải
gửi mức tuyệt đối vì **router không đọc vehicle state**, không cộng trừ được từ mức hiện tại. Cả hai
đều là bug thật đã gặp (issue #115 mục 3 và 4), không phải lo xa.

### Màn 2 — Từ chối tường minh và hỏi lại (vẫn chưa chạm actuator)

Ba câu này quan trọng hơn vẻ ngoài của chúng: chúng chứng minh hệ thống **không đoán**.

| Câu nói | Kết quả | Vì sao |
|---|---|---|
| *"Tắt đèn pha"* | `denied` / `headlight_off_not_permitted` | Enum `headlight` **không có** `off` — UNECE R48 cấm chế độ tắt thủ công trên xe có DRL (ADR-020). Ánh xạ ngầm `tắt` → `auto` là làm một việc khác việc được yêu cầu mà không nói ra |
| *"Tăng quạt gió"* | `clarify` / `missing_fan_level` | Router **không đọc vehicle state**, nên không cộng trừ được từ mức hiện tại. Hỏi lại thay vì đoán |
| *"Mở cửa sổ sau"* | `clarify` / `missing_window_side` | `_side()` chỉ hiểu `bên lái`, `bên phụ`, `sau bên trái`, `sau bên phải` |

Câu *"Tắt đèn pha"* đáng diễn hơn trước: từ PR #121 lời từ chối **nêu lý do và chỉ đường thoát**,
thay cho câu chung *"Xin lỗi, tôi không thực hiện được yêu cầu này."* từng khiến tài xế không phân
biệt nổi quy định an toàn với hệ thống hỏng (`DENIED_MESSAGES`, `src/agents/nodes/compose.py:67`):

> Đèn pha không tắt thủ công được — xe có đèn chạy ban ngày nên đây là quy định an toàn.
> Bạn nói "chuyển đèn sang chế độ tự động" để xe tự bật tắt theo trời sáng tối nhé.

Router **không** vì thế mà ngầm ánh xạ `tắt` → `auto`: quyết định vẫn là `denied`, có test khoá lại.

Còn *"Tăng quạt gió"* → `clarify` là hành vi của **đường giọng nói**, và nó vẫn đúng. Đừng nhầm sang
nút bấm: nút quạt trên FE không còn gửi câu tương đối này nữa (xem bảng ở Màn 1).

### Màn 3 — HITL (S2)

Ở **cửa sổ 2** gõ `stop` (0 km/h, số P), rồi nói:

> *"Mở cửa sổ bên lái 30%"*

Thẻ phê duyệt hiện ra → **bấm nút Đồng ý trên màn hình IVI**.

Ba điều phải nói đúng:

- **Đừng thử duyệt bằng giọng nói.** `approval.intent.detected` chưa implement, dù brief có ghi
  "voice-first HITL". Đây là khoảng trống đã biết, không phải trục trặc tại chỗ.
- Kính là S2 **luôn luôn**, không phụ thuộc tốc độ. Cửa/cốp/vị-trí-ghế mới là S2 chỉ khi
  `speed_kph == 0 && gear == P`.
- Phê duyệt **hết hạn sau ≥30 s**, dùng **một lần**, gắn với đúng plan đó, và mỗi phiên chỉ được có
  **một** phê duyệt treo. Hết hạn / từ chối / lệch `state_version` đều đi thẳng tới compose với
  **zero side effect**.

Biến thể đáng diễn nếu còn thời gian: nói *"Mở cửa"* (không nêu vị trí) khi xe đang đỗ → plan **4
bước** cho cả bốn cửa, và thẻ phê duyệt liệt kê **đủ bốn cửa**. Người dùng nhìn thấy chính xác thứ
mình đồng ý trước khi có bất kỳ side effect nào.

### Màn 4 — Chặn cứng (S3) — cao trào

Ở **cửa sổ 2** gõ `speed 45`, rồi nói **đúng câu vừa nãy đã được duyệt**:

> *"Mở cửa bên lái"*

Kết quả: candidate tool vẫn là `set_door_state`, policy gán **S3**, `executed_tools` **rỗng**, không
có approval, không có MQTT, không có chuyển trạng thái. Bị chặn **trước** cả HITL.

Đây là luận điểm mạnh nhất của cả buổi: **phân loại an toàn là hàm của trạng thái xe, không phải của
câu chữ.** Và `src/agents/policy.py` là **nơi duy nhất trong hệ thống** gán `safety_level` — router
và SLM chỉ được sinh `CandidateActionPlan`, một kiểu dữ liệu **không có** trường safety.

### Màn 5 — Màn hình kỹ sư

Đăng xuất, đăng nhập lại bằng tài khoản engineer. Xem trace từng stage và `/metrics/summary`.

Hai con số trông như lỗi nhưng là dữ liệu đúng:

- `model_runtime: "not-selected"`, mọi percentile `null` — cách nói thẳng bằng dữ liệu rằng
  **không có LLM nào chạy trên đường lệnh**. Đó là `slm_enabled=False` cộng ADR-005 "Not Yet".
- `stage_latencies_ms.tts` chỉ khác `null` ở lượt tổng hợp TTS thành công, và **không** được cộng vào
  `end_to_end` (đo trước khi TTS chạy).

---

## Phần 3 — Ranh giới phải nói rõ

Bỏ qua phần này thì buổi demo trở thành một tuyên bố sai. Nguồn: [`coverage_matrix.md`](coverage_matrix.md).

### Trả lời được ≠ làm được

Router mặc định rơi xuống tra sổ tay (ADR-011), nên hệ thống **trả lời trôi chảy** về đèn sương mù,
cruise control, Camp Mode trong khi **làm không được** cái nào. Khi trình bày phải giữ hai cột tách rời:

| | Phạm vi |
|---|---|
| **Điều khiển được** | 8 domain actuator (9 domain trừ `motion` chỉ đọc); **15 tool trong registry, 12 tool ghi** (3 tool S0 còn lại chỉ đọc: `get_vehicle_state`, `query_manual`, `search_nearby_poi`), đúng các mẫu câu ở Phần 2 |
| **Trả lời được** | Bất kỳ nội dung nào có trong 482 chunk sổ tay VF9 |

Không được gộp thành một con số "hỗ trợ N lệnh". Tổng kết thật: **6/11 nhóm lệnh thoại ô tô phổ
thông có điều khiển, đều là một phần nhỏ; 5/11 nhóm bằng 0** (chỉ nhóm "liên lạc" là cố ý loại trừ).

### Không demo được, đừng hứa

| Thứ | Vì sao |
|---|---|
| Duyệt HITL bằng giọng nói | `approval.intent.detected` chưa implement |
| Use case "tìm cà phê → HVAC → dẫn đường" | `search_nearby_poi` chỉ là một dòng trong registry: không executor, không router rule, không test (ADR-010 hoãn tường minh) |
| Transcript hiện dần khi đang nói | `transcript.partial` chưa phát — transcript hiện **một lần** sau khi STT xong, không chạy chữ theo lời nói |
| Replay khi rớt kết nối | Server làm đủ (ADR-014) nhưng client không gửi `last_event_id`/`last_sequence` |
| Số độ trễ end-to-end | **Chưa từng đo.** Con số 5,6 s trong báo cáo cũ là của SPIKE-001, một pipeline khác — đừng tái sử dụng |
| Audio `.ogg` / `.pcm` | Route nhận, nhưng `voice.py` parse WAV bằng `wave` stdlib nên luôn kết thúc ở `transcript.final(unusable)` |
| Xe "đang di chuyển" khi bấm nút **Bắt đầu** trên bản đồ | Chấm xe trượt dọc polyline trong 30 giây là **animation thuần FE** (`MapView.tsx`, nội suy bằng `lib/geo/routeAnimation.ts`) — không gọi backend, không đổi `vehicleState.navigation`, không phải GPS thật từ vehicle simulator. Nút đổi thành "Huỷ" trong lúc chạy chỉ dừng animation, không huỷ điều hướng thật (huỷ thật vẫn phải làm bằng giọng nói/lệnh khác) |

**Nút quạt +/− và nút đèn trên FE đã chạy thật từ PR #121** — hai dòng cũ của bảng trên (*"FE phải
đổi câu gửi"*, dẫn [TASK-BE-FE-004](tasks/TASK-BE-FE-004-issue-65-command-vocabulary.md)) mô tả hiện
trạng **trước** ngày 2026-08-15 và đã được gỡ. Issue #115 đóng cùng PR đó. Câu chính xác từng nút gửi
nằm ở bảng cuối Màn 1; điều cần nhớ khi diễn là **nút tắt đèn pha không còn tồn tại** — nó được thay
bằng bộ chọn 3 chế độ, vì enum không có `off`.

**Mic và loa đã chạy thật từ PR #82 (phát audio TTS) và PR #88 (ghi mic)**, PR #99 thêm phần tự dừng
khi im lặng (bản nháp đầu của tài liệu này xếp cả hai vào bảng trên — đã sai từ 2026-08-13, và bản
sau đó quy công cả ba việc cho riêng #99).
`frontend/src/lib/audio/wavRecorder.ts` ghi mic qua `getUserMedia` + `AudioWorkletNode`
và encode thẳng ra **WAV 16-bit mono 16 kHz** trong trình duyệt, tự dừng sau 900 ms im lặng (bản ghi
không có tiếng nói thì không gửi lên BE), tối đa 12 s; `DriverShellProvider.tsx` phát `assistant.speech`
bằng `new Audio(...)`. Luồng **micro → STT → TTS → loa** vì thế chạy đủ trong sản phẩm, kèm bốn điều
kiện phải kiểm trước khi demo:

| Điều kiện | Không thoả thì sao |
|---|---|
| Đã cài model giọng nói — Zipformer + `vi_VN-piper.onnx` ([`huong_dan_chay.md`](huong_dan_chay.md) §2.6) | Bấm mic lỗi `INTERNAL_ERROR`, `/healthz` trả 503 |
| Mở trên **`localhost` hoặc HTTPS** | `getUserMedia` bị trình duyệt chặn trên HTTP thường |
| Trang đã có **một lần click** trước đó | Autoplay policy chặn `.play()` đầu tiên; lỗi bị nuốt, chỉ mất tiếng, phần chữ vẫn hiện |
| Trình duyệt cho `AudioContext` ở **16000 Hz** | `_validate_audio` từ chối `"audio must be 16kHz mono WAV"`; `resampleLinear()` chỉ là lưới an toàn |

**Ảnh chụp ở mock mode không chứng minh gì về backend.** Hai chỗ lệch mà bản trước ghi ở đây —
`control_lights`/`control_trunk` và kẹp quạt `0..5` — **đã sửa trong PR #121**: mock giờ dùng
`set_headlight_mode`, `set_interior_light`, `set_trunk_state`, `set_hvac_fan_level`, kẹp `0..3`, nhận
mức tuyệt đối, và từ chối `tắt đèn pha` y như router thật.

Nhưng **mock vẫn chưa canonical hết**, nên câu trên vẫn đúng nguyên: sáu tool cũ còn mang tên bảng
alias Family-A đã bỏ từ 2026-08-08 — `control_ac`, `control_door`, `control_window`,
`control_seat_heating`, `control_seat_position`, `control_music` (`frontend/src/lib/services/turn/mock.ts`).
Tên tool phải **canonical end-to-end**, nên ảnh chụp mock mode vẫn không thay được một lượt chạy thật.

### Pool xe ảo là quyền điều khiển, **không** phải sức chứa của hệ thống

Áp dụng khi chạy với `VEHICLE_POOL_SIZE > 1` (ADR-028, PR #259 + #262). Mặc định vẫn là `1`, và ở
`1` thì mọi thứ dưới đây không xuất hiện.

Pool chỉ trả lời đúng **một** câu hỏi: *phiên này có được cấp một chiếc xe mô phỏng riêng để ra lệnh
hay không.* Nó **không** trả lời câu hỏi *hệ thống phục vụ được bao nhiêu người cùng lúc*. Hai thứ đó
độc lập, và trộn chúng là cách nhanh nhất để hứa sai trên sân khấu:

| | Pool quản gì | Pool **không** quản gì |
|---|---|---|
| **Có xe** | Phiên được cấp `vehicle_id` riêng, `can_drive: true`, lệnh không bị từ chối `vehicle_pool_exhausted` | Lệnh đó chạy **nhanh** đến đâu |
| **Nghẽn** | Không có xe → chuyển sang chế độ chỉ-xem, nói rõ lý do | STT/TTS/SLM cùng chạy trên **một** máy PC, dùng chung CPU/RAM/GPU — không có hàng đợi, không có reject, không có SLO |

Hệ quả phải nói trước khi ai đó hỏi:

- **"Còn xe" ≠ "phản hồi nhanh".** Ba tài xế cùng nói một lúc thì cả ba đều `can_drive: true` và cả
  ba đều chờ chung một hàng STT/TTS. [#257](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/257)
  đã thấy timeout/cutoff ngay ở N=3. Pool biến "lệnh hỏng" thành "chờ lâu" — đó là cải thiện về
  đúng đắn, không phải về throughput.
- **Con số `3` không phải capacity sản phẩm.** Nó là số xe mô phỏng dựng được, chốt theo RAM
  (`eval/results/ram-nhieu-xe/`), không phải theo độ trễ end-to-end — mà độ trễ end-to-end thì
  **chưa từng đo** (xem bảng "Không demo được, đừng hứa" ở trên). Đừng công bố "hỗ trợ 3 người dùng".
- **`Lúc vào phiên: x/3 xe` trên màn Điều khiển là ảnh chụp**, lấy từ response `POST /sessions` tại
  thời điểm phiên được tạo. Backend không phơi con số này ở `GET /vehicle/state` hay ở bất kỳ sự
  kiện WS nào, nên client không có đường làm mới. Người vào đầu tiên vẫn thấy `1/3` khi pool đã đầy.
  Không dùng nó để trả lời "còn chỗ không" — câu trả lời đúng cho câu hỏi đó là thử tạo phiên mới.

#### Đặt bao nhiêu — hai cấu hình, hai thế giới khác hẳn

Rà code 2026-08-27 để trả lời câu "một xe thì sao, hai xe thì thế nào".

**`VEHICLE_POOL_SIZE = 1` (mặc định) không phải "pool có một chỗ" — nó là pool TẮT HẲN.**
`session_state.py:72` trả thẳng `None`, và `xe_cua_phien()` khi ấy trả `settings.vehicle_id` cho
**mọi** phiên. Nên:

| | `= 1` | `>= 2` |
|---|---|---|
| Ai lái được | **tất cả**, không ai bị đẩy sang chỉ-xem | đúng N phiên đầu; từ phiên N+1 là chỉ-xem |
| Số người vào được | không giới hạn | không giới hạn (chỉ-xem vẫn vào được) |
| Trạng thái xe | **một, dùng chung** | tách rời hoàn toàn |
| `ui.policy` | broadcast tới mọi phiên | gửi đúng người đang thuê xe đó |
| Lỗ lease (dưới đây) | không nổ — không có bảng thuê | **nổ**, cho tới khi PR #344 merge |

Ở `= 1` thì ba đường va chạm dưới đây là chuyện **chắc chắn xảy ra** khi có hai người:
`skipped_external_state_change` cắt kế hoạch nhiều bước giữa chừng (`nodes/execute.py`),
`approval_invalidated_state` huỷ lệnh vừa được bấm Duyệt (`nodes/approval.py:163`), và cả phòng bị
siết UI cùng lúc. Hội thoại thì **không** lẫn: `session_id` riêng, event WS đẩy theo session,
approval gắn cả plan lẫn session. Trực giác "do dùng chung tài khoản driver" là sai về nguyên nhân —
cấp tài khoản riêng không sinh ra chiếc xe thứ hai.

**Không cần thêm container simulator cho xe thứ 2.** Đây là chỗ dễ đoán sai nhất, đã kiểm:

- `src/vehicle_sim/__main__.py:144` đọc `settings.vehicle_pool_ids()` và dựng **một `VehicleSimulator`
  cho mỗi xe** trong cùng một tiến trình, mỗi cái một `client_id = vehicle-simulator-{vehicle_id}`.
- `src/main.py:148` gắn `MqttVehicleGateway` cho **mọi** xe trong pool; các xe phụ `bind()` vào
  **chính kết nối** của ô số 0. Cố ý: `MqttRuntime.start()` dùng `client_id="vivi-backend"` cố định,
  nên K kết nối là K client trùng id và broker đá lần lượt từng cái ra.
- `backend` và `vehicle-simulator` cùng `env_file: .env`.

→ **Một dòng trong `.env` là đủ cho cả hai service. Nhưng phải recreate CẢ HAI container**, không chỉ
backend — simulator không tự biết pool vừa to ra.

```bash
docker compose up -d --force-recreate backend vehicle-simulator
```

**Ba thứ phải biết trước khi bật:**

1. **Lỗ lease.** Cổng xe chốt vào graph ở lần dựng đầu, `_touch()` chỉ `gia_han()`. Lease hết hạn →
   xe cấp cho người khác → graph cũ vẫn cầm cổng chiếc xe ấy → **phiên cũ lái xe của người mới**, cả
   hai bên không có dấu hiệu gì. Chỉ nổ khi `>= 2`. Vá ở PR #344; **đừng bật pool trước khi nó merge**.
2. **Lease 180 s, và chỉ 4 chỗ gia hạn** — `turns/text`, `turns/voice`, `approvals/{id}/decision`,
   `agent/process`. Mở WS, poll `GET /vehicle/state` mỗi 2 giây, xem bản đồ, nghe nhạc: **không cái
   nào gia hạn**. Người đứng đọc hướng dẫn 3 phút là mất xe. Với demo có khán giả thì đây là chuyện
   sẽ xảy ra thật, không phải rủi ro lý thuyết.
3. **Trần pool không mua thêm năng lực xử lý.** Đo 2026-08-27 (`eval/results/luot-that-dong-thoi/`
   run `20260827T154539`): đường planner ra kế hoạch **4/4 ở N=1** và **0/4 ở N=2, N=3, N=5** — chết ở
   **người thứ hai**, hoàn toàn độc lập với số xe. Xem mục dưới.

### Sức chứa đo được: đường điều khiển là tính năng MỘT người

Đo 2026-08-27 trên VPS (5 vCPU, không GPU, `llama -t 4 -c 2048`, `SLM_TIMEOUT_S=30`,
`SLM_CLASSIFY_TIMEOUT_S=7`), develop @ `1477a26`, chế độ voice, bộ WAV `cham_slm`.
Run `eval/results/luot-that-dong-thoi/20260827T154539`.

| N | Lượt planner ra kế hoạch | Tra sổ tay p50 |
|---:|---|---:|
| 1 | **4/4** | 603 ms |
| 2 | **0/4** | 1 055 ms |
| 3 | **0/4** | 2 178 ms |
| 5 | **0/4** | 2 426 ms |

**Người thứ hai vào là toàn bộ đường điều khiển sập** — không phải chậm, mà không lượt nào ra được
kế hoạch nữa. Tra sổ tay thì bền hơn hẳn: tới N=5 vẫn 2,4 s, xấp xỉ ngưỡng.

Nó sập theo **hai kiểu, cả hai đều im lặng**:

- **Hết giờ** — `33 951 · 34 505 · 37 814 · 32 213 ms`. Hai lượt planner tranh 5 vCPU; mỗi lượt vốn
  15–23 s một mình, nay vượt `SLM_TIMEOUT_S=30`.
- **Van chặn** — `7 917 · 8 532 · 7 947 · 8 508 ms`, và ở N=5 thì **cả bốn** rơi vào kiểu này.
  `slm_max_concurrent` mặc định **2**, dùng chung cho **cả classify lẫn planner** — một câu sổ tay
  cũng chiếm chỗ. Không xin được chỗ thì planner bỏ cuộc và rơi về sổ tay trong ~8 s.

> **Cả hai kiểu đều trả HTTP 200 và `bi tu choi = 0/10`.** Cột `bi_tu_choi` của bộ đo mù với nhánh
> này: `graph.py` chạy `_lui_ve_so_tay(state)` **trước**, nên sổ tay có câu trả lời là tài xế nhận
> câu đó và không bao giờ thấy `CAU_BAN`. Tài xế nói *"trong xe ngột ngạt quá, xử lý giúp tôi"* và
> nhận về một đoạn hướng dẫn — không ai nói cho họ biết hệ vừa từ chối làm việc.

Hệ quả khi đọc bảng: **`p50` ở N=5 (4 182 ms) ĐẸP HƠN ở N=1 (6 515 ms)**. Không phải hệ nhanh lên —
là 4/4 lượt đắt nhất đã ngừng làm việc đắt. Một bảng có `p50` giảm khi N tăng luôn là dấu hiệu phải
đi tìm cái gì vừa ngừng chạy.

**Nâng tham số không chữa được.** `slm_max_concurrent` lên 5 chỉ đổi kiểu B (hỏng nhanh, 8 s) thành
kiểu A (hỏng chậm, 34 s) — kiểu A đã chứng minh lượt *có* chỗ vẫn hết giờ. Và vCPU cũng không: máy
này đo được bão hoà `T(n) = A·n/(n+k)` với `A = 24,99`, `k = 9,49` (sai số <0,5%), tức
`A ≈ 25 tok/s` là **trần băng thông của VM**. Cần ~16 luồng mới gấp đôi thông lượng — và kết quả chỉ
là hai người, mỗi người vẫn chờ 23 giây.

Ngay ở N=1 đường planner đã trượt ngưỡng 2 500 ms **gấp 6–9 lần**. Việc đáng làm không phải nhét hai
lượt 23 giây vào một máy, mà là đưa **một** lượt xuống dưới 5 giây: model nhỏ hơn cho vai planner,
rút `SLM_UNION_PROMPT`, hoặc máy có GPU.

---

---

## Phần 4 — Sự cố hay gặp giữa buổi demo

Danh sách đầy đủ ở [`huong_dan_chay.md`](huong_dan_chay.md) PHẦN V. Bốn cái dưới đây là những cái
thật sự nổ giữa buổi:

**1. Màn hình IVI đứng im, `GET /vehicle/state` trả 503 `no_snapshot_yet`.** Simulator cũ publish 7
domain, backend mới đòi 9. **Tắt bật backend không chữa được** — `state/snapshot` là *retained* và
Mosquitto bật `persistence true` với named volume, nên bản 7-domain sống qua cả `docker compose down`.

```powershell
docker compose up -d --build --force-recreate vehicle-simulator
curl.exe -s http://localhost:8000/api/v1/vehicle/state
```

Chạy simulator bằng tay thì chỉ cần khởi động lại tiến trình.

**2. `docker compose up` không khởi được service nào.** Thiếu `config/mosquitto/passwd`. Cả `backend`
lẫn `vehicle-simulator` đều `depends_on: service_healthy` của `mqtt`, nên broker không healthy là kẹt
toàn bộ. Chạy `pwsh scripts/bootstrap_mqtt_secrets.ps1`.

**3. Bấm mic thì lượt thất bại với `INTERNAL_ERROR`.** Chưa cài voice models
([`huong_dan_chay.md`](huong_dan_chay.md) §2.6). Lỗi này **không
phải** `STT_FAILED` — nhánh đó dành riêng cho audio hỏng thật, cố ý tách ra để hệ thống không đổ lỗi
oan cho micro tài xế.

**4. `/healthz` trả 503 dù mọi thứ có vẻ ổn.** Đọc component, đừng đọc status. Xem §1.2, và bảng đầy
đủ ở [`huong_dan_chay.md`](huong_dan_chay.md) §3.1.

---

## Phần 5 — Dừng hệ thống

Cách dừng thường ngày ở [`huong_dan_chay.md`](huong_dan_chay.md) PHẦN I (`Ctrl+C` từng cửa sổ, rồi
`docker compose down`). Chỉ có một biến thể riêng cho demo: khi cần **dựng lại sạch** vì broker còn
giữ snapshot 7-domain cũ (§Sự cố #1),

```powershell
docker compose down -v
```

`-v` xoá named volume `mosquitto_data`. Sau đó **phải chạy lại simulator** để có snapshot mới, không
thì backend nằm ở `no_snapshot_yet`.

---

## Phụ lục — Trả lời câu hỏi về test và evidence

Không thuộc luồng demo, nhưng hay bị hỏi ngay sau đó. **Câu lệnh** chạy test và sinh evidence ở
[`huong_dan_chay.md`](huong_dan_chay.md) §3.5 — đừng chép lại vào đây, con số ở đó được đo lại theo
từng lần dựng máy. Phần dưới chỉ là cách **diễn giải** chúng cho đúng.

**Số test là snapshot có ngày, không phải cổng.** Nó nhích mỗi lần có người land test, và số skip
đổi theo việc máy đã dựng chỉ mục RAG với model giọng nói hay chưa — một tổng skip khác con số
trong runbook **không phải** dấu hiệu hỏng.

**Test đơn vị xanh không phải bằng chứng về chất lượng model hay độ trễ.** Và hai bộ dataset không
thay thế nhau: `eval/datasets/agent/v3` do chính người viết router soạn, nên `intent_accuracy = 1.0000`
chỉ là **tripwire chống hồi quy**, không nói gì về khả năng khái quát. Không dataset nào đi qua ASR,
nên không con số nào phản ánh lỗi nhận dạng giọng nói. Đừng trình bày chúng như độ chính xác
người-dùng-thấy.

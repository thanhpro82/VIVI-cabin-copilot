# TASK-FE-BE-003 — Sửa các lỗi bất đồng bộ ở `/driver` khi bấm nút thật với backend thật

Bối cảnh: tiếp theo `TASK-FE-BE-002` (đã merge qua PR #56) — sau khi domino
auth/session/turns/WS đã thông, phần này ghi lại các lỗi **trải nghiệm thật**
lộ ra khi dùng UI liên tục với backend thật đang chạy (không phải đọc code
suông), cách đã sửa, và phần còn thiếu để BE quyết định làm tiếp.

## 1. Đã sửa (FE only, không cần BE đổi gì)

### 1.1 Race điều kiện lúc mới đăng nhập — bấm nút không phản hồi

`DriverShellProvider.tsx` tạo session (`POST /sessions`) trong `useEffect` lúc
mount — bất đồng bộ, có round-trip HTTP thật. Nhưng UI render xong và bắt
tương tác được **ngay từ frame đầu**, trước khi round-trip đó xong.

- **Lỗi 1 (nông):** bấm nút trước khi session tạo xong → `currentSessionId()`
  trong `turn/real.ts` throw `"Chưa có session..."` → nuốt vào toast lỗi.
- **Lỗi 2 (sâu hơn, nghiêm trọng hơn):** `turnService.subscribe()` (mở
  WebSocket `/ws/ivi`) đọc `getCurrentDriverSession()` **đồng bộ** ngay lúc
  effect chạy — cùng lúc với `createDriverSession()` (async) nên luôn thấy
  `null` ở lần đăng nhập đầu tiên, tự quyết "không có session" và **không bao
  giờ mở WebSocket**. Lệnh vẫn gửi thành công lên backend, nhưng không có
  socket nào lắng nghe `turn.completed` → StatusBar kẹt "Đang xử lý…" vĩnh
  viễn, chỉ hết khi reload (lúc đó session đã có sẵn trong localStorage).

**Sửa:** gộp toàn bộ bootstrap (tạo session → refresh state → subscribe WS)
vào một chuỗi async duy nhất trong `DriverShellProvider.tsx`; `send()` /
`openVoice()` đợi đúng promise đó trước khi gọi `turnService`.

### 1.2 WebSocket không tự nối lại — "treo đang xử lý" sau một khoảng idle

Triệu chứng người dùng báo: để tab không thao tác một lúc, quay lại bấm nút
thì kẹt "Đang xử lý…", phải bấm đi bấm lại nhiều lần hoặc reload mới hết.

**Nguyên nhân:** `turnService.subscribe()` (`turn/real.ts`) mở đúng 1 lần lúc
mount, **không có bất kỳ cơ chế reconnect nào**. `/ws/ivi` rớt sau một
khoảng idle là chuyện bình thường (tab bị trình duyệt/OS đưa vào nền, proxy
đóng kết nối rảnh...). Không reconnect nghĩa là mọi sự kiện turn phát ra sau
đó — kể cả `turn.completed` của chính lệnh bạn vừa bấm — rơi vào hư vô.

**Sửa:** `subscribe()` giờ tự reconnect với backoff tuyến tính (1s → tối đa
8s), dùng đúng cơ chế replay cursor mà backend đã hỗ trợ sẵn (ADR-014, ring
buffer 200 event / TTL 30 phút) — gửi `last_event_id`/`last_sequence` trong
`connection.init` từ lần reconnect thứ 2 trở đi, nên không mất event nào phát
ra trong lúc mất kết nối. Nếu server trả `REPLAY_CURSOR_INVALID` /
`REPLAY_WINDOW_EXPIRED` thì tự bỏ cursor và nối lại từ đầu; nếu là lỗi xác
thực (`AUTH_REQUIRED`/`FORBIDDEN`, token không còn hợp lệ) thì dừng hẳn, báo
lỗi cho UI thay vì lặp lại vô ích — cần đăng nhập lại.

### 1.3 `vehicleState` không tự cập nhật khi trạng thái xe đổi từ nguồn ngoài

Triệu chứng: gõ `speed 45` / `stop` vào console `vehicle_sim` — MQTT publish
đúng, nhưng màn hình `/driver` đứng yên, phải F5 mới thấy.

**Nguyên nhân:** FE chỉ gọi lại `GET /vehicle/state` sau hành động của chính
người dùng (qua sự kiện `tool.result`/`turn.completed`) — không có gì báo cho
FE biết khi trạng thái xe đổi từ nguồn khác (console vehicle_sim, client
khác...).

**Sửa:** thêm poll định kỳ 2 giây trong `DriverShellProvider.tsx`, chỉ bật ở
real mode (`NEXT_PUBLIC_USE_MOCK_TURN=false`) — mock không cần vì không có
nguồn ngoài nào đổi state ngầm. Nhân tiện sửa luôn lỗi liên quan:
`refreshVehicleState()` trước đây không có `.catch()`, một lần gọi lỗi (ví dụ
401 do token cũ) làm `vehicleState` kẹt `null` vĩnh viễn (mô hình xe 3D kẹt
"Đang tải mô hình xe…") mà không có gì tự thử lại — giờ lỗi bị nuốt có chủ
đích vì vòng poll kế tiếp sẽ tự thử lại.

### 1.4 Bảng test tốc độ (`SpeedDebugDrawer`) tự ẩn ở real mode

Trước đây bảng debug tốc độ chỉ hoạt động ở mock (gọi thẳng
`__setMockSpeedKph`, hàm này không tồn tại ở real). Ở real mode nó tự `return
null` — không có cách nào để test hành vi S2/S3 qua UI.

**Xác nhận kiến trúc trước khi sửa:** `GET /vehicle/state` đã trả đủ
`motion.speed_kph`/`gear` (không cần thêm interface đọc riêng — đúng ADR-013,
một nguồn state duy nhất). Không có API nào cho FE **set** tốc độ ở real mode
— `motion` là domain read-only phía backend (không topic MQTT lệnh nào ghi
`state/*`), và `POST /agent/process` (route duy nhất nhận
`vehicle_speed_kmh`) là dev-only, tự ghi rõ "đừng cho FE gọi vào đây". Cách
hợp lệ duy nhất để cho xe chạy là gõ trực tiếp vào console
`python -m src.vehicle_sim` (`speed 45`, `gear D`, `stop`).

**Sửa:** bảng debug giờ hiện ở cả real mode nhưng đổi vai trò — không còn
thanh trượt set trực tiếp (không có gì hợp lệ để set qua HTTP), mà hiện tốc
độ/gear thật (tự poll `GET /vehicle/state` mỗi giây khi đang mở) kèm hướng
dẫn 3 lệnh console. Không thêm bất kỳ API backend nào.

### 1.5 Nút "Mở khoá tất cả" sáng nhầm khi chỉ 1 cửa mở

`VehicleControlView.tsx`: nút gửi lệnh "toàn xe" (`anyOpen ? "đóng cửa" : "mở
cửa"`) trước đây tô sáng theo biến `anyOpen` — nghĩa là mở đúng 1 cửa cũng
làm nút này sáng lên như thể vừa bấm chính nó. Đã bỏ style tô sáng theo
`anyOpen`, giữ nguyên style tĩnh; chỉ 4 nút cửa riêng lẻ đổi màu theo đúng
cửa đó.

### 1.6 Bỏ khối chip lệnh nhanh ở màn hình chính

`HomeView.tsx`: 3 nút chip ("bật điều hòa 22 độ"/"mở cửa sổ bên tài"/"bật
nhạc") phía dưới nút mic — theo yêu cầu review, không còn tác dụng khi demo
bằng giọng nói. Đã bỏ hẳn khối này (và biến `send` không dùng nữa theo đó).

### 1.7 Phát audio TTS (`assistant.speech`) — bên nhận cho việc BE vừa nối (issue #66)

Trong lúc audit `docs/p0_gap_audit_2026-08-12.md` (mới landing cùng đợt pull
này) phát hiện: BE vừa nối `synthesize_wav()` vào `emit_turn_lifecycle`, phát
event mới `assistant.speech` (`audio_base64` + `mime_type: audio/wav`) ngay
trước `assistant.response` mỗi turn — best-effort, vắng mặt hoàn toàn (không
phải event rỗng/lỗi) khi TTS thất bại hoặc `response_text` rỗng. FE trước đó
bỏ qua hoàn toàn: `mapServerEvent()` không có case này, rơi vào
`default: return null`.

**Sửa:** thêm `assistant.speech` vào `DriverEvent` (`types.ts`), map trong
`real.ts`, và phát trong `DriverShellProvider.tsx` bằng
`new Audio(dataUrl).play()` — không cần `<audio>` element cố định trong JSX,
mỗi turn tạo 1 instance dùng 1 lần. Lỗi (kể cả bị trình duyệt chặn autoplay
vì trang chưa từng có tương tác người dùng) bị nuốt có chủ đích — phần text
(`assistant.response`) vẫn hiển thị bình thường dù không phát được audio.

**Lưu ý quan trọng — không phụ thuộc vào việc ghi âm mic:** dữ liệu audio đến
từ *câu trả lời* của VIVI cho **bất kỳ turn nào thành công**, kể cả turn gửi
bằng text (`send()`/bấm nút UI) — không cần chờ `MediaRecorder`/`getUserMedia`
(mục 2 bên dưới) làm trước. Test được ngay hôm nay bằng cách bấm bất kỳ nút
lệnh nào có sẵn.

### 1.8 Ghi âm mic thật (voice input) — `wavRecorder.ts`

`openVoice()` trước đây cố ý gửi `new Blob()` rỗng (không có `MediaRecorder`/
`getUserMedia` nào trong `frontend/`). Đã thêm ghi âm thật — trải qua 3 vòng
sửa lỗi phát hiện bằng test tay với mic thật, không phải chỉ đọc code.

**Không dùng `MediaRecorder`.** API này chỉ ghi ra container nén (webm/opus ở
Chrome/Firefox, mp4/aac ở Safari) — không trình duyệt nào ghi thẳng ra WAV.
Backend (`src/services/voice.py::_validate_audio`) đòi ĐÚNG WAV 16-bit PCM
**16000Hz mono** — sai container bị từ chối ở tầng khác với sai sample rate
(xem CLAUDE.md mục "STT accepts only WAV"; `"audio must be 16kHz mono WAV"`
là lỗi validate riêng, không phải lỗi container). `wavRecorder.ts` tự capture
PCM thô qua Web Audio API rồi tự đóng gói WAV trong trình duyệt, xin thẳng
`AudioContext({ sampleRate: 16000 })` để khỏi phải resample thủ công (có
`resampleLinear()` làm lưới an toàn cho trình duyệt hiếm gặp lờ đi option
này).

**Bug #1 (đã sửa) — `ScriptProcessorNode` bị Chrome tự đình chỉ.** Bản đầu
dùng `ScriptProcessorNode` (không cần asset tĩnh thêm). Test tay: overlay mở
đủ 12 giây, nhưng WAV backend nhận chỉ ~1-2 giây âm thanh thật. Nguyên nhân:
Chrome coi graph "không phát ra gì nghe được" (cố tình nối qua `GainNode`
gain=0 để không phát tiếng mic ra loa) là ứng viên tiết kiệm pin, tự đình chỉ
xử lý sau vài giây — `onaudioprocess` ngừng bắn dù JS timer vẫn chạy đúng.
**Sửa:** chuyển sang `AudioWorkletNode`
(`frontend/public/worklets/pcm16k-recorder.js`) — chạy trên audio rendering
thread riêng, không thuộc nhóm node bị áp cơ chế đình chỉ này. `stop()` đổi
thành `async` (trả `Promise<Blob>`) vì phải đợi buffer PCM cuối từ worklet
qua `postMessage` (không đồng bộ với việc disconnect nguồn).

**Bug #2 (đã sửa) — gọi `openVoice()` lặp không có chốt chặn.** Bấm mic lần 2
trong lúc lần 1 còn đang chờ quyền mic (khoảng async, có thể vài trăm ms tới
vài giây) tạo RECORDER THỨ HAI đè lên `recorderRef.current` mà không huỷ
recorder cũ — timer tự-dừng 12s của lần 1 (đặt cho recorder đã bị thay) sau
đó cắt ngang recorder MỚI ở thời điểm bất kỳ, ra bản ghi ngắn/lẻ giây (quan
sát được: 1.0s, 0.26s, 2.3s thay vì chờ đủ hoặc chạm dừng thật). **Sửa:**
thêm `voiceStartingRef` — cờ đồng bộ tuyệt đối (không như state React, đợi
batch/render), chặn mọi lệnh gọi `openVoice()` chồng lên nhau cho tới khi
recorder trước đó thật sự bắt đầu hoặc thất bại.

**Bug #3 (đã sửa) — `lastTurn` không reset khi mở overlay mới.** Nếu đã có
`lastTurn.vivi` từ lượt TRƯỚC (vd. bấm nút UI ngay trước đó), effect
auto-đóng overlay ("có `lastTurn.vivi` thì đóng sau 1.8s") kích hoạt NGAY khi
mở overlay ghi âm mới — đóng lại chỉ sau 1.8s dù người dùng chưa kịp nói gì.
Lỗi có từ bản gửi `Blob()` rỗng cũ nhưng không lộ ra vì lượt cũ luôn kết thúc
rất nhanh; ghi âm thật cần đủ thời gian mới lộ rõ. **Sửa:** `openVoice()` gọi
`setLastTurn(null)` trước khi bắt đầu ghi.

**Luồng UX sau khi sửa hết 3 bug trên:** chạm mic → mở overlay, bắt đầu ghi
ngay (label "Đang nghe — chạm để dừng", vòng tròn xanh + waveform là
clickable) → chạm lại (hoặc quá `MAX_RECORDING_MS = 12s`) → dừng ghi, gửi WAV
lên `POST /turns/voice` → overlay chuyển sang state machine cũ
(`transcribing→...→composing`) dẫn dắt bởi `assistant.status` thật. Từ chối
quyền mic (`NotAllowedError`) → đóng overlay + toast hướng dẫn cấp quyền,
không giữ overlay treo. Unmount giữa lúc đang ghi (điều hướng đi trang khác)
→ tự nhả mic qua `recorder.cancel()`.

### Gap phát hiện được, KHÔNG phải bug FE — báo BE/nhóm

Sau khi cả 3 bug trên đã sửa, dump thử file WAV thật ra đĩa và kiểm tra bằng
`wave`/`numpy` (không đoán mò): file đúng cấu trúc 16kHz/mono/16-bit, thời
lượng khớp chính xác overlay, và có tín hiệu âm thanh thật — biên độ dao động
rõ theo giây, đúng hình dạng người đang nói, không phải im lặng/nhiễu ngẫu
nhiên. Tức là **pipeline ghi âm FE→BE giờ đúng hoàn toàn**.

Nhưng khi nói "bật điều hoà", `PhoWhisper-base` (`voice.transcribe`) nhận
diện ra những câu hoàn toàn không liên quan (vd. "du lịch hơi việt nam cách
mạng việt nam.") ở cả nhiều lần thử. Đây là **giới hạn độ chính xác của
model STT**, không phải bug đường truyền — cần BE/nhóm đánh giá: đổi model
STT lớn hơn (`phowhisper-base` → `phowhisper-large`?), kiểm tra lại chất
lượng mic/gain hệ thống test (đỉnh biên độ quan sát được khá gần trần dải
động, có thể đang bị méo nhẹ do to quá), hoặc chấp nhận đây là giới hạn đã
biết của P0 và ghi vào `docs/coverage_matrix.md`/README như "Chạy được trên
PC" nhưng độ chính xác STT tiếng Việt chưa đo bằng WER thật (đúng đúng ghi
chú sẵn có trong CLAUDE.md: "synthetic Piper audio is not human-speaker WER"
— giờ có thêm vế ngược lại, mic người thật qua PhoWhisper cũng chưa có số đo
WER nào).

## 2. Chưa sửa — vẫn đúng nguyên hiện trạng ghi trong TASK-FE-BE-002

Xác nhận lại bằng diff thật (không suy đoán) tính tới thời điểm viết file
này: các mục sau **chưa có commit nào đụng vào**, cần BE quyết định.

- **Tool/router còn thiếu:** mọi cửa cùng lúc, cốp xe, đèn pha, mức quạt gió,
  bài nhạc trước (`media_control.action: "previous"` đã có trong schema
  nhưng router chưa có nhánh phrase nào gọi tới). `src/agents/router.py`,
  `src/services/tool_registry.py` không đổi.
- **Event `ui.policy` chưa phát** (6 cờ an toàn khi xe đang chạy) — client
  vẫn phải tự suy luận từ `vehicleState`, sai với chủ đích thiết kế (client
  bị cấm tự suy luận UI policy).
- **Composer chưa tổng hợp câu trả lời tra cứu sổ tay:** `compose_node` vẫn
  trả câu cố định `"Đây là thông tin tôi tìm được trong sổ tay xe."` +
  citation thô, chưa synthesize nội dung. (Phần định danh `citation_id` +
  `GET /citations/{id}` đã được nhánh `feature/grounded-rag-response` sửa
  trước đó — xem worklog liên quan — chỉ phần tổng hợp câu trả lời là còn
  thiếu.)

## 3. Ghi chú vận hành (không phải bug, chỉ để người test sau không mất công dò lại)

- Auth store là **in-memory** (`src/services/auth.py`) — mọi lần restart
  backend làm mất hết token đã cấp, kể cả token còn hạn thật (12h). Đây là
  quyết định có chủ đích (issue #46, `docs/data_model.md` không thiết kế bảng
  token) và **không đổi**; vẫn phải đăng nhập lại sau mỗi lần restart backend
  trong lúc dev.
  **Cập nhật 2026-08-15 (UAT-009, nhánh `fix/auth-token-invalid-expired`):** hai
  vế còn lại của ghi chú này đã được sửa. Thông điệp không còn dùng chung — 401
  nay nói rõ "token đã hết hạn" hay "token không còn hiệu lực (server đã khởi
  động lại)" — và FE không còn kẹt: mọi 401/403 và close code 4401/4403 đều dẫn
  tới đăng xuất sạch rồi quay về `/login` kèm lý do, thay vì một toast 3,2 giây
  rồi thôi.
- Trạng thái xe (`vehicle_sim`) là tiến trình độc lập, không liên quan gì tới
  phiên đăng nhập/session — tốc độ đặt qua console giữ nguyên xuyên suốt các
  lần đăng nhập/đăng xuất, cho tới khi tự đổi lại (`stop`).
- Gear D (dù đang đứng yên 0 km/h) vẫn xếp S3 (chặn cứng, không hộp thoại xác
  nhận) cho cửa/vị trí ghế — chỉ đúng cả 2 điều kiện `speed_kph == 0 && gear
  == P` mới xuống S2. Đây là quyết định có chủ đích của ADR-010, không phải
  bug. Gõ `gear P` hoặc `stop` trong console `vehicle_sim` để mở cửa được.
- Chạy 2 phiên Claude Code / 2 người cùng sửa code song song trên **cùng một
  working directory** (không phải worktree riêng) đã từng dẫn tới uncommitted
  changes của 2 việc không liên quan trộn lẫn trong `git status`. Khuyến nghị
  dùng `git worktree add ../P-192-wt-<tên-việc> <branch>` cho mỗi việc chạy
  song song thay vì sửa trực tiếp trên cùng checkout `develop`.

## 4. Việc cần BE quyết định tiếp (không phải FE tự làm được)

1. **Router/tool cho cốp/đèn/quạt gió/bài trước/mọi cửa** — làm tiếp (thêm
   nhánh router + tool nếu thiếu tool) hay chính thức bỏ khỏi P0 và ghi vào
   `api_spec.md`/ADR nếu bỏ.
2. ~~Kiến trúc TTS~~ — đã landed ở `develop` (issue #66, `assistant.speech`
   qua WS). FE đã nhận ở mục 1.7.
3. **Phát `ui.policy`** — 6 cờ an toàn khi xe đang chạy, hiện chưa có trong
   danh sách event thực phát dù nằm trong allowlist `api_spec.md`.
4. **`compose_grounded_answer`** — tổng hợp câu trả lời tra cứu sổ tay từ nội
   dung `excerpt` thay vì câu cố định.
5. **Độ chính xác STT (`PhoWhisper-base`) — mới phát hiện, xem mục 1.8.**
   Pipeline ghi âm FE→BE đã xác nhận đúng (WAV 16kHz/mono hợp lệ, có tín hiệu
   giọng nói thật — kiểm bằng cách dump file thật ra đĩa và phân tích biên độ
   bằng `numpy`, không đoán mò). Nhưng nói "bật điều hoà" bị nhận diện thành
   câu hoàn toàn không liên quan, lặp lại ở nhiều lần thử độc lập. Cần nhóm
   BE/model đánh giá: đổi profile PhoWhisper lớn hơn, kiểm tra chất lượng
   mic/gain máy test (đỉnh biên độ ghi được khá gần trần dải động — có thể
   đang méo nhẹ do to quá), hoặc xác nhận đây là giới hạn P0 đã biết và ghi
   rõ vào `docs/coverage_matrix.md` — hiện chưa có số đo WER nào cho giọng
   người thật qua PhoWhisper (khác với WER Piper synthetic đã có, xem
   CLAUDE.md mục "Evidence is the product").

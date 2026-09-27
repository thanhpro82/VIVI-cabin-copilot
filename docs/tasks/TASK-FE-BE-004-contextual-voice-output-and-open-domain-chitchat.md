# TASK-FE-BE-004 — Voice output theo đúng ngữ cảnh + câu hỏi ngoài lề qua LLM

Bối cảnh: tiếp theo `TASK-FE-BE-003` (PR #80, #82, #88, đã merge qua #91) — phần
đó đã đưa ghi âm mic thật và phát audio TTS vào `develop`. Doc này ghi lại phần
**còn thiếu** so với kỳ vọng trải nghiệm voice-first đầy đủ, cập nhật dần qua
nhiều đợt test tay bằng backend thật (2026-08-13). Phần FE tự làm được đã làm
xong và có PR riêng (mục 4, PR #99/#101/#102) — phần còn lại cần team chốt
trước khi code tiếp vì chạm ADR-016 hoặc là việc BE thuần (mục 2, 3, 5).

**Cập nhật 2026-08-15 sau review PM/PO (PR #104):** mục 3 (chitchat/SLM) đã
được chốt là **non-goal của P0**; mục 5 (fuzzy router) đã có **safety
boundary bắt buộc** ở 5.1; số WER ở mục 1 đã quy về đúng một nguồn ADR-017;
mục 4 sửa lại trạng thái cho đúng (đã vào `develop`, chưa release); mục 6 bổ
sung runbook corpus có owner và tiêu chí readiness. Xem mục 7 để lấy bản tóm
tắt trạng thái mới nhất.

## 1. Đã có — xác nhận lại bằng đọc code thật, không suy đoán

- **Ghi âm mic thật**: `frontend/src/lib/audio/wavRecorder.ts` +
  `public/worklets/pcm16k-recorder.js` — `AudioWorkletNode`, WAV 16-bit PCM
  mono 16kHz đúng chuẩn BE đòi. (#88)
- **Phát audio TTS**: `DriverShellProvider.tsx` xử lý event `assistant.speech`,
  `new Audio(...).play()` trước `assistant.response`. (#82)
- **Text hiển thị**: `VoiceOverlay.tsx` render `lastTurn.vivi` (toàn bộ câu bot
  vừa nói) khi mic đang mở.
- **RAG trả lời đúng ngữ cảnh — nguyên văn chunk**: `compose.py::_quote_top_evidence`
  trích nguyên văn `evidence[0].text` từ vectordb, cắt ở ranh giới câu nếu quá
  1200 ký tự, có báo "còn tiếp". Đã đúng kỳ vọng, không cần sửa gì.
- **STT engine vừa nâng cấp**: Zipformer-30M-RNNT thay PhoWhisper (ADR-017
  `docs/adr/ADR-017-zipformer-production-stt.md`, PR #90). **Số WER dùng đúng
  một nguồn chính thức là ADR-017 §Real benchmark section**, run
  `eval/results/stt-compare/20260812T133954.391653Z/metrics.json` — 50 case
  (24 synthetic + 26 giọng thật), đo trên **một máy dev**:
  - tổng 50 case: PhoWhisper **26,12%** → Zipformer **8,08%**;
  - riêng 26 case giọng thật: **20,5%** → **3,8%**;
  - đo lại sau khi tích hợp vào `src/services/voice.py`, trên 5 câu
    `tests/fixtures/voice/synthetic_commands/`: **9,17%** (latency warm
    120,4ms) — đây là số dùng để đặt budget test, **không** so sánh trực tiếp
    được với hai dòng trên vì khác bộ dữ liệu và khác đường đo.

  Con số "~32%→~13%" ở bản trước của doc này là **sai/không truy được về run
  nào**; đã bỏ. Ba mốc trên là ba phép đo khác dataset — đừng trích một mình
  con số nào mà không kèm dataset/điều kiện, và đừng coi chúng là cùng một
  benchmark. **Lưu ý vận hành cho người test**: model chưa
  tự tải — phải chạy
  `.\.venv311\Scripts\python.exe scripts\download_zipformer_model.py` một lần
  trước khi bật backend, nếu không `get_stt_engine()` (`src/services/voice.py:118`)
  raise `FileNotFoundError` ngay lượt voice đầu tiên. Máy nào vẫn chỉ có
  `models/voice/phowhisper-base-ct2/` (model cũ) mà chưa tải Zipformer sẽ tiếp
  tục thấy nhận dạng sai/lệch — đây là nguyên nhân của lỗi "nói lệnh mà ra
  'không có thông tin trong sổ tay'" quan sát được hôm 2026-08-12: text STT sai
  không khớp luật điều khiển, rơi về RAG lookup mặc định (ADR-011), RAG đương
  nhiên không tìm thấy gì liên quan. Không phải bug ở router/RAG.

## 2. Còn thiếu #1 — câu xác nhận điều khiển vẫn là chuỗi cố định

`compose.py::OUTCOME_MESSAGES["completed"]` luôn là **"Đã thực hiện lệnh trên
xe mô phỏng."** cho mọi lệnh điều khiển thành công — không nói lại cụ thể đã
làm gì ("đã bật điều hòa", "đã hạ kính trước bên lái 30%"...).

Ngược lại, hàm `describe_step(tool, args)` đã có sẵn và mô tả **chính xác** hành
động theo tham số — nhưng hiện chỉ được gọi trong `_compose_offer()` (nhánh
`offer`, dùng để **hỏi lại** trước khi làm ở S2), không được gọi lại sau khi
`execute` xong.

**Việc cần làm (nếu team đồng ý)**: nối `describe_step()` vào nhánh `outcome ==
"completed"` trong `compose_node`, đổi câu trả lời thành ví dụ `"Đã bật điều
hòa."` / `"Đã hạ kính trước bên lái 30%."` thay vì chuỗi cố định. Cần làm rõ
với nhiều bước (`plan.steps` >1) thì nối câu thế nào — theo đúng mẫu
`" rồi "` đã dùng ở `_compose_offer`, hay liệt kê từng dòng.

Rủi ro cần cân nhắc: `execution_failed` (thực hiện được một phần) hiện cũng là
câu cố định — nếu đổi `completed` thì `execution_failed` có nên nói rõ bước nào
xong/bước nào hỏng không, hay giữ nguyên chung chung để tránh phức tạp hoá lỗi
một phần?

## 3. Câu hỏi ngoài lề (ví dụ "hôm nay ăn gì") — NON-GOAL của P0, không phải bug tồn đọng

> **Chốt của PM/PO (2026-08-15):** P0 **giữ `slm_enabled=False` mặc định** và
> **giữ hành vi từ chối lịch sự** cho câu ngoài phạm vi xe. Trợ lý hỏi-đáp mở
> là **non-goal** ở P0, không phải hạng mục nợ kỹ thuật — đừng đưa vào backlog
> "còn thiếu" hay vào tiêu chí nghiệm thu demo. Chỉ mở lại khi có **đủ hai
> điều kiện**: (i) benchmark latency/accuracy chạy trên **nhiều máy** (tối
> thiểu 1 máy dGPU + 1 máy không dGPU) chứ không chỉ máy trong ADR-016, và
> (ii) policy thành văn cho câu trả lời ngoài phạm vi xe + rủi ro bịa
> (hallucination), do WS2/an toàn duyệt. Phần dưới giữ lại làm phân tích kỹ
> thuật cho lần đánh giá lại đó, **không phải** đề xuất làm ngay.

Kiến trúc **có sẵn đường đi đúng**: câu không khớp luật điều khiển, RAG không
tìm thấy nội dung liên quan (`grounded_refusal` + `route_reason ==
"default_to_manual"`) → nếu có `planner` thì rẽ sang SLM (`graph.py::route_after_rag`)
→ `slm_stage` gọi `QwenPlanner.propose()`, model trả `{"kind":"chitchat","reply":
"..."}` → `compose_node` dùng thẳng `chitchat_reply`. Không cần sửa graph.

Nhưng **2 điều kiện chưa thoả**, cả hai đều là quyết định phạm vi đã ghi trong
ADR-016, không phải bug:

1. **`slm_enabled=False` mặc định** (`src/config.py:32`) trên mọi checkout —
   theo ADR-016, đây là cơ chế đảm bảo máy không có GPU đủ mạnh vẫn chạy được
   sản phẩm y hệt, không phải cờ tạm quên bật. Số đo latency/accuracy trong
   ADR-016 (p50 992ms, tool-accuracy 0,828) **chỉ đo trên một máy cụ thể**
   (RX 5500M của Nhân) — chưa có bằng chứng trên máy khác.
2. **Prompt hiện tại được dạy để TỪ CHỐI câu ngoài lề**, không phải trả lời.
   `SLM_UNION_PROMPT` (`src/agents/slm.py`) có ví dụ few-shot huấn luyện model
   trả lời kiểu "Việc này tôi không làm được — tôi chỉ hỗ trợ các chức năng
   trong xe..." cho yêu cầu ngoài phạm vi. Chitchat trong thiết kế ban đầu chỉ
   nhắm tới chào hỏi/cảm ơn (P0 không định làm trợ lý hỏi-đáp mở).

**Hai câu hỏi để dành cho lần đánh giá lại sau P0** (đã bị chốt "chưa làm" ở
callout trên, giữ đây để lần sau không phải điều tra lại từ đầu):

- **(a) Có bật `slm_enabled=True` mặc định không, hay giữ opt-in?** Nếu bật,
  cần re-run bậc đo của SPIKE-003 trên máy khác trước (ADR-016 mục "Máy demo
  và tính di động" đã nêu quy trình) để biết máy đó thuộc tầng nào (dGPU ≥4GB
  / chỉ iGPU / CPU thuần) — không phải flip cờ là xong, cần `llama-server`
  chạy resident trước backend.
- **(b) Có sửa `SLM_UNION_PROMPT` để cho phép trả lời hữu ích câu hỏi ngoài
  lề (trong giới hạn an toàn) thay vì từ chối không?** Đây là thay đổi hành vi
  sản phẩm, không chỉ kỹ thuật — cần cân nhắc: model 3B quant có thể bịa thông
  tin (không có RAG/tool nào kiểm chứng nhánh chitchat), và trần 240 ký tự
  hiện tại có đủ cho câu trả lời "hợp lý" (không chỉ 1 câu ngắn) hay cần nới?
  Rủi ro tồn đọng đã ghi trong ADR-016 (chọn nhầm tool sang S1 không bị chặn)
  không áp dụng ở đây (chitchat không chạm executor), nhưng rủi ro mới là
  "trả lời sai/bịa trong xe" cần nhóm an toàn (Nhân/WS2) xác nhận chấp nhận
  được cho demo học thuật.

## 4. Còn thiếu #3 — text hiển thị chưa "đứng yên", tự đóng theo lastTurn — đã implement, đã vào `develop`, CHƯA release

Trạng thái chính xác tại thời điểm cập nhật doc (2026-08-15): chuỗi PR
#99 → #101 → #102 đã merge hết vào `develop` (lần lượt 2026-08-13,
2026-08-14, 2026-08-15) —
**code đã có trên `develop`, nhưng chưa qua bất kỳ mốc release/QA nào**, nên
đừng đọc mục này là "đã nghiệm thu". Không đánh dấu hoàn tất cho tới khi có
lượt QA chạy tay xác nhận trên `develop`.

~~`VoiceOverlay.tsx` hiện `lastTurn.vivi` trong overlay, nhưng
`DriverShellProvider.tsx` có effect tự đóng overlay 1.8s sau khi có
`lastTurn.vivi`~~ — đã đổi (nhánh `feat/fe-voice-overlay-polish`, PR #102,
stacked lên #99/#101):

- Overlay giờ tự đóng **~4.5s SAU KHI audio TTS phát xong** (`ended`), không
  phải hẹn giờ cố định tính từ lúc có text — sửa đúng lỗi "câu dài audio còn
  đọc dở mà overlay đã tắt".
- Thêm chạm-ra-ngoài-để-đóng thủ công (`closeVoice()`).
- ~~Thêm lịch sử tối đa 3 câu trả lời gần nhất (không chỉ lượt cuối), hiện mờ
  phía trên câu trả lời hiện tại, dọn sạch khi overlay đóng.~~ — **đã đảo lại
  ở PR #110, xem 4.1.**
- Transcript (`"bạn vừa nói gì"`) ép đứng yên tối thiểu 2s trước khi bị câu
  trả lời thay vào (`MIN_TRANSCRIPT_VISIBLE_MS`), kể cả khi lệnh là S2 (hộp
  thoại HITL không còn nhảy thẳng qua transcript nữa — transcript hiện đủ
  TRƯỚC khi hộp thoại xuất hiện).

Toàn bộ phần này không cần BE đổi gì — thuần FE, nằm ngoài scope quyết định
của team trong doc này. Giữ nguyên đây làm lịch sử tham chiếu.

### 4.1 Thay đổi yêu cầu: BỎ hiển thị lịch sử 3 lượt (quyết định UX, PR #110)

Ghi nhận chính thức để đóng gate 2 trong review PM/PO ở PR #110 — **yêu cầu
"giữ 3 câu trả lời gần nhất" của #102 bị thay thế, không phải bị bỏ sót.**

- **Quyết định (2026-08-15):** overlay chuyển từ modal toàn màn hình sang
  **thẻ nổi neo góc trên** theo mẫu trợ lý ảo VinFast/VinBigdata, và thẻ đó
  **chỉ hiển thị lượt hiện tại** (câu hỏi nhỏ ở trên, câu trả lời lớn ở dưới,
  wordmark VIVI góc dưới-phải). Không còn danh sách các lượt trước.
- **Lý do:** hai yêu cầu xung đột trực tiếp về không gian. Thẻ nổi cố ý
  **không** che tối/blur map–Dock–StatusBar phía sau; nhồi thêm 3 dòng lịch
  sử làm thẻ cao gần gấp đôi, che đúng phần màn hình mà thiết kế thẻ nổi
  sinh ra để giữ nhìn thấy được. Lịch sử hội thoại là nhu cầu "đọc lại", còn
  overlay lúc lái xe là nhu cầu "liếc một cái" — hai thứ không nên chung một
  bề mặt.
- **Cái gì bù lại:** không có, và đây là đánh đổi có ý thức. Nếu sau này cần
  đọc lại nhiều lượt, chỗ đúng là một khung hội thoại riêng (hoặc trang
  lịch sử), không phải thẻ nổi này.
- **Hệ quả kỹ thuật cần biết:** state `turnHistory` + `MAX_TURN_HISTORY`
  trong `DriverShellProvider.tsx` **vẫn còn** và vẫn được test #102 phủ,
  nhưng sau #110 **không còn UI nào tiêu thụ** — cố ý giữ lại vì rẻ và là
  chỗ nối sẵn cho khung hội thoại nói trên. Ai dọn dead code sau này đọc mục
  này trước khi xoá, đừng coi là sót.
- **Trạng thái ticket:** #102 đã merge với history; #110 đảo phần hiển thị.
  Bảng "đã làm" ở mục 4 phía trên đã gạch dòng history cho khớp.

## 5. Còn thiếu #4 — router so khớp từ khoá CỨNG, lệch 1 chữ hoặc thiếu 1 từ là rơi hẳn về "không hiểu"

Phát hiện qua test tay 2026-08-13 với backend thật (STT Zipformer đã hoạt
động đúng, không phải lỗi nhận dạng) — **2 ca lặp lại được, không phải ngẫu
nhiên**:

1. **STT lệch 1 ký tự do phát âm gần giống**: nói "cửa sổ **bên** phụ 20%",
   Zipformer nhận thành "cửa sổ **biên** phụ 20%" (thêm nguyên âm "i" —
   "bên"/"biên" phát âm gần giống nhau trong tiếng Việt). `router.py::_side()`
   so khớp chuỗi con `"bên phụ" in text` — "biên phụ" không chứa "bên phụ"
   (lệch đúng 1 ký tự) → trả `None` → `_match_window` trả `("clarify",
   "window_position", "missing_window_side", ())` → câu hỏi lại chung chung
   "Bạn muốn điều chỉnh cụ thể như thế nào?", không thực thi.
2. **Nói tắt tự nhiên, thiếu từ router coi là bắt buộc**: nói "**mở khóa bên
   lái**" (không nhắc "cửa") thay vì "mở khóa **cửa** bên lái". `_match_door()`
   dòng đầu tiên `if "cửa" not in text: return None` — thiếu đúng từ "cửa" là
   thoát ngay, không xét tiếp side/verb gì cả. Rơi về mặc định tra sổ tay
   (ADR-011) → sổ tay không có nội dung liên quan → "Tôi không tìm thấy thông
   tin này trong sổ tay xe." — tài xế thấy y hệt như "hệ thống không biết gì",
   dù câu nói hoàn toàn tự nhiên và một người nghe thật sẽ hiểu ngay.

Cả hai đều bắt nguồn từ cùng 1 thiết kế: **so khớp chuỗi con/tiền tố cứng
tuyệt đối, không có bất kỳ dung sai nào** cho biến thể chính tả/phát âm hay
cách nói tắt tự nhiên. Đây là đúng lỗ hổng đã nêu ở mục 3 (chitchat cần SLM
để "hiểu ngữ nghĩa") nhưng áp dụng cho **luật điều khiển**, không chỉ chitchat
— tức là ngay cả không cần LLM, người dùng vẫn có thể gặp "máy không nghe
được" dù nói đúng ý, chỉ vì thiếu/thừa/lệch một chữ.

**2 hướng khắc phục, không cần chờ SLM/ADR-016**:

- **(a) Fuzzy matching có kiểm soát trong router** — vd cho phép sai lệch tối
  đa 1 ký tự (Levenshtein distance ≤1) trên các từ khoá then chốt (`"bên"`,
  `"cửa"`...), hoặc nới lỏng điều kiện bắt buộc: nếu đã nhận diện được
  side + verb ("mở"/"đóng"/"mở khóa") + có ngữ cảnh gợi ý cửa (side khớp
  đúng 1 trong 4 vị trí cửa) thì hỏi lại có gợi ý cụ thể ("Bạn muốn mở cửa
  bên lái phải không?") thay vì rơi thẳng về "không hiểu"/tra sổ tay. Việc kỹ
  thuật thuần router, không đụng ADR-016.
- **(b) Chờ SLM** (mục 3) — nhưng đây là fallback CHUNG cho câu không khớp
  luật, không riêng cho lỗi gõ/phát âm gần đúng; không nên coi (a) là dư thừa
  chỉ vì SLM có thể "hiểu" — SLM tắt mặc định và không phải máy nào cũng chạy
  được, còn (a) chạy được ở mọi máy, mọi lúc.

### 5.1 Safety boundary bắt buộc trước khi mở implementation task

Chốt của PM/PO (2026-08-15) — **đây là điều kiện tiên quyết, không phải gợi
ý**. Task implement chỉ được tạo khi thiết kế thoả cả 5 ràng buộc dưới, và
task đó phải chép nguyên 5 ràng buộc này vào phần acceptance criteria:

1. **Chỉ fuzzy trên slot, không bao giờ trên verb/tool.** Được phép dung sai
   với từ khoá **vị trí/slot** đã liệt kê sẵn (`"bên lái"`, `"bên phụ"`,
   `"trước"`, `"sau"`, `"cửa"`...). **Cấm** áp dụng cho từ chọn hành động và
   từ chọn tool (`"mở"`, `"đóng"`, `"khóa"`, `"mở khóa"`, `"bật"`, `"tắt"`,
   `"điều hòa"`, `"kính"`, `"nhạc"`...) — đây đúng là chỗ nhận nhầm biến
   S0 thành S2, hoặc biến "mở nhạc" thành "mở cửa".
2. **Chỉ fuzzy sau khi domain đã xác định bằng khớp cứng.** Ví dụ chỉ thử
   `"biên"`→`"bên"` **sau khi** đã chắc câu thuộc domain cửa/kính bằng một
   từ khoá khớp tuyệt đối; không fuzzy để *chọn* domain.
3. **Dung sai cứng ≤1 ký tự (Levenshtein ≤1) và chỉ trên từ ≥3 ký tự**, so
   khớp theo **từ** (token) chứ không theo chuỗi con, và mỗi câu chỉ được
   dùng dung sai **một lần**. Hai từ cùng lệch cùng lúc ⇒ coi như không khớp.
4. **Không đủ chắc chắn ⇒ `clarify`, tuyệt đối không tự sinh/thực thi
   action.** Kết quả của fuzzy là *gợi ý cụ thể hơn cho câu hỏi lại* ("Bạn
   muốn mở cửa bên lái phải không?"), không phải đường tắt để bỏ qua bước
   xác nhận. Với S2 (cửa/kính/ghế) thì HITL vẫn chạy y nguyên như hiện tại —
   fuzzy không được rút bớt bất kỳ bước duyệt nào.
5. **Không đổi ranh giới an toàn.** Fuzzy nằm hoàn toàn trong `router.py`,
   chỉ sinh `CandidateActionPlan`; `policy.py` vẫn là nơi duy nhất gán
   `safety_level`. Không ADR nào bị chạm; nếu thiết kế nào đó cần chạm
   `policy.py` thì nó đã ra ngoài phạm vi mục này và cần ADR mới.

Kèm theo, task phải có test cho **cả hai chiều**: 2 ca dương tính ở mục 5
("biên phụ", "mở khóa bên lái") đi tới đúng đích, **và** ca âm tính chứng
minh dung sai không kéo `"mở nhạc"`/`"mở cốp"` sang lệnh cửa.

**Việc còn lại cần team chốt**: có làm (a) trong sprint này không (phạm vi/
người làm), và danh sách từ khoá slot được phép fuzzy — mức dung sai đã chốt
ở ràng buộc 3, không cần bàn lại.

## 6. Ghi chú vận hành — RAG cần corpus có bản quyền, không tự tải được

Test tay trên máy không có sẵn `data/manuals/vf9_2026_vi/` (bị gitignore
hoàn toàn, `scripts/prepare_vf9_index.ps1` ghi rõ "KHÔNG tải gì từ mạng...
corpus có bản quyền") sẽ **không build được index RAG** — mọi câu hỏi tra sổ
tay đều trả "chưa tra được sổ tay xe". Không phải bug, chỉ là máy đó thiếu dữ
liệu nguồn. Ghi lại đây để người test sau không mất công dò lại nguyên nhân.

### 6.1 Runbook: xin corpus và tự kiểm tra máy đã sẵn sàng test RAG

**Owner:** WS2 — Agent & RAG Pipeline, **Nhân & Thành Nguyễn**
(`README.md` §bảng workstream). Corpus không nằm trong git và **không được**
đẩy lên git/artifact CI vì có bản quyền.

**Kênh xin quyền:** mở issue trên repo với nhãn `rag`, tiêu đề
`[corpus] xin VF9_2026_vi cho <tên/máy>`, gán cả hai owner ở trên; nhận thư
mục qua kênh chat nội bộ của nhóm (không public link). Nếu gấp thì ping
trực tiếp owner trong nhóm chat rồi vẫn mở issue để có vết.

**Các bước sau khi có corpus:**

```powershell
# đặt thư mục nhận được ở gốc repo, tên đúng: VF9_2026_vi/
.\scripts\prepare_vf9_index.ps1
.\.venv311\Scripts\python.exe -m src.rag.cli verify
```

**Tiêu chí readiness tối thiểu — QA tự kiểm được, không cần hỏi owner.**
Đủ cả 4 mới coi là máy sẵn sàng test RAG:

1. `VF9_2026_vi/` có đủ `manifest.json`, `html/`, `pdf/` — thiếu cái nào
   `prepare_vf9_index.ps1` cũng dừng ngay (script kiểm cả 3, dòng 15-19).
2. `prepare_vf9_index.ps1` chạy hết mà không cảnh báo `thieu:`/`lech:` —
   tức checksum khớp `corpus.sha256`; lệch ⇒ index sinh ra không tái lập
   được, số đo từ máy đó không dùng để báo cáo được.
3. `src.rag.cli verify` in ra manifest **482 chunks / 58 documents**
   (`VF9_23-25_VN_VI_2.4`) và **PASS cả hai cổng chất lượng**:
   `page resolved >= 95%` và `worst section rate >= 80%`
   (`MIN_PAGE_EXACT_RATE`/`MIN_SECTION_RATE`, `src/rag/ingest/pipeline.py`).
4. Một câu hỏi khói chạy được có trích dẫn:
   `.\.venv311\Scripts\python.exe -m src.rag.cli query "áp suất lốp tiêu chuẩn"`
   trả về evidence kèm số trang, **không** phải "không tìm thấy".

Chưa đủ 4 điều trên thì mọi kết luận kiểu "RAG trả lời sai/không biết" từ
máy đó **không có giá trị** — hãy ghi rõ trạng thái corpus trong báo cáo test.
Lưu ý: `prepare_vf9_index.ps1` hard-code `.\.venv\Scripts\python.exe`
(Python 3.13) chứ không phải `.venv311` — đây là hiện trạng đã biết của repo,
không phải lỗi cài đặt của máy bạn.

## 7. Việc cần team quyết định (tóm tắt)

1. Nối `describe_step()` vào nhánh `completed` để câu trả lời điều khiển đúng
   ngữ cảnh — rủi ro thấp, không chạm ADR nào, có thể làm ngay nếu team đồng ý.
2. ~~Bật `slm_enabled` mặc định~~ và ~~sửa `SLM_UNION_PROMPT` cho chitchat~~ —
   **ĐÃ CHỐT: không làm ở P0** (PM/PO 2026-08-15, mục 3). Giữ
   `slm_enabled=False` mặc định, giữ hành vi từ chối lịch sự; ghi nhận là
   **non-goal**, không phải nợ kỹ thuật. Mở lại chỉ khi có benchmark đa máy
   **và** policy hallucination do WS2/an toàn duyệt.
3. ~~Đổi UX hiển thị text~~ — **đã implement, đã vào `develop`** qua
   #99→#101→#102, **chưa release/QA** (mục 4).
4. Fuzzy matching có kiểm soát trong router (mục 5) — kỹ thuật thuần BE,
   không chạm ADR nào. **Safety boundary đã chốt ở mục 5.1** (chỉ fuzzy slot,
   không fuzzy verb/tool; ≤1 ký tự; không chắc ⇒ `clarify`, không tự
   execute). Còn cần chốt: làm sprint nào, ai làm, danh sách từ khoá slot.
5. (Vận hành, không phải quyết định) Cập nhật hướng dẫn test cho toàn team:
   chạy `scripts/download_zipformer_model.py` trước khi test voice, nếu không
   sẽ gặp lại đúng lỗi nhận dạng sai đã quan sát; và theo runbook corpus
   `VF9_2026_vi/` ở mục 6.1 (owner WS2, 4 tiêu chí readiness) nếu cần test RAG.
6. (Kỷ luật số liệu) Mọi con số WER trích trong doc/report phải kèm dataset và
   điều kiện đo, nguồn duy nhất là ADR-017 §Real benchmark section (mục 1).

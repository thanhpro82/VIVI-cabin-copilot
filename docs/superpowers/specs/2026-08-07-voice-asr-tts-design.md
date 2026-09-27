# Thiết kế: Tích hợp PhoWhisper (ASR) & Piper (TTS) — voice adapter module

> Ngày: 2026-08-07. Trạng thái: Đã duyệt (brainstorming), chờ viết implementation plan.
> Nguồn gốc: task tracker "Tích hợp PhoWhisper (ASR) & Piper (TTS) vào FastAPI server".
> Quyết định kiến trúc (engine binding + phạm vi module) đã ghi thành [ADR-007](../../adr/ADR-007-voice-adapter-engine-binding.md).

## Bối cảnh & phát hiện quan trọng

Task gốc mô tả:
- Endpoint `/voice/transcribe` xử lý âm thanh < 400ms
- WER < 20% trên mẫu thử nghiệm
- Streaming audio chunks từ Piper TTS
- Deliverables: Module ASR/TTS trong `src/services/voice.py`; API `/voice/transcribe`

Trước khi thiết kế, đã đối chiếu với docs canonical (Họ B) và phát hiện các điểm cần điều chỉnh so với mô tả task gốc:

1. **Tên engine mâu thuẫn trong task, và đã sửa lại theo canonical spec**: tiêu đề task nói "PhoWhisper", mô tả nói "Faster-Whisper base int8". Ban đầu quyết định chạy PhoWhisper qua CTranslate2 (`faster-whisper`) — nhưng đối chiếu lại `docs/devops.md` (bảng "Environment contract") cho thấy giá trị canonical target là **`STT_PROVIDER=whisper_cpp`**, không phải faster-whisper/CTranslate2 (tên này không xuất hiện ở bất kỳ doc Họ B nào, chỉ xuất hiện trong mô tả task và `_bmad-output/.../ADR.md` — Họ A). `docs/technical_spec.md:23` cũng liệt kê "Whisper.cpp, PhoWhisper, and Piper" cùng nhau — nghĩa là PhoWhisper (model) chạy **qua whisper.cpp** (runtime, GGUF), giống pattern `WhisperCppAdapter` đã có sẵn trong `experiments/offline_poc/src/offline_poc/stt.py` (subprocess gọi binary whisper.cpp), không phải `PhoWhisperAdapter` (Transformers) hay CTranslate2. **Quyết định cuối (user duyệt 2026-08-07): dùng whisper.cpp + PhoWhisper convert sang GGUF**, theo đúng `STT_PROVIDER=whisper_cpp`.
2. **AC "<400ms" không khớp bằng chứng eval thực tế cho biến thể Transformers**: `eval/results/report.md:26,28` đo PhoWhisper-small **qua Transformers** (không phải whisper.cpp) p50 6.981,8ms / p95 9.882,5ms, cold-start 16.353,7ms — không đại diện cho lựa chọn whisper.cpp đã chốt ở điểm 1. Quyết định: "<400ms" chỉ áp dụng cho **warm inference**, loại trừ cold-start/model-load; whisper.cpp GGUF quantized trên CPU cho short utterance thường nhanh hơn nhiều so với con số Transformers trên, nhưng **chưa có benchmark thật trong repo cho tổ hợp whisper.cpp+PhoWhisper-GGUF** — cần đo lại khi viết plan/implement, và cân nhắc giữa `whisper-cli` (subprocess mỗi lần gọi, load lại GGUF mỗi lần) và `whisper-server` (load một lần, resident) để thực sự đạt "warm, resident".
3. **AC "WER < 20%" không có corpus thật để đo**: `eval/datasets/poc/v1/audio/manifest.jsonl` **cố ý để trống** (chờ audio tiếng Việt có consent). Số liệu WER 30.7% trong `eval/results/report.md:26` đo trên audio tổng hợp từ Piper, tự ghi chú "không được trình bày như độ chính xác trên người lái Việt Nam thật". Quyết định: tái dùng phương pháp loopback tổng hợp (Piper→PhoWhisper) làm smoke test, không phải benchmark độ chính xác thật.
4. **Endpoint `/voice/transcribe` (JSON đồng bộ) chỉ tồn tại ở Họ A (`docs/VIVI_API_Spec.md`)**, tài liệu tự đánh dấu là **product-vision, không dùng để implement** (banner đầu file, xác nhận lại trong `docs/codebase_analysis.md:11-13`). Spec canonical (Họ B) không có endpoint này:
   - `docs/technical_spec.md:23`: "Whisper.cpp, PhoWhisper, and Piper remain behind the backend **voice adapter** as libraries, native binaries, or managed subprocesses. They are not deployment services."
   - `docs/api_spec.md` chỉ có `POST /api/v1/turns/voice` — endpoint **bất đồng bộ** (`202 Accepted`), gắn với auth/session/turn/idempotency, kết quả thật trả qua `WS /ws/ivi` (`transcript.final`, `stage_latencies_ms.stt/tts`, ...).
   - `src/` hiện chưa có auth, session, turn, hay WebSocket nào (`docs/codebase_analysis.md` mục 4-6) — xây `POST /api/v1/turns/voice` thật trong task này sẽ kéo theo toàn bộ hạ tầng đó, vượt xa phạm vi "tích hợp ASR/TTS".

**Quyết định phạm vi (đã user duyệt 2026-08-07):** Task này chỉ giao **module nội bộ** `src/services/voice.py` theo đúng khái niệm "voice adapter" của `technical_spec.md:23`. **Không thêm route/endpoint HTTP nào trong task này.** Việc nối vào `POST /api/v1/turns/voice` thật sẽ là task riêng, sau khi hạ tầng auth/session/turn tồn tại.

## Kiến trúc & thành phần

`src/services/voice.py`:
- `get_stt_engine()` — singleton `lru_cache`, cùng pattern với `get_settings()` (`src/config.py:35`). Lazy-load adapter whisper.cpp (kế thừa/mở rộng pattern `offline_poc.stt.WhisperCppAdapter`: gọi binary whisper.cpp) trỏ tới checkpoint PhoWhisper-small đã convert sang GGUF. Cụ thể `whisper-cli` (subprocess mỗi lần) hay `whisper-server` (resident, gọi qua HTTP nội bộ) — quyết định khi viết plan, dựa trên benchmark load-time thật của GGUF quantized.
- `get_tts_engine()` — singleton `lru_cache`, lazy-load Piper qua `piper-tts` Python API (không phải subprocess CLI như `offline_poc.tts.PiperAdapter`, để tránh chi phí reload model mỗi lần gọi).
- `transcribe(audio_bytes: bytes) -> Transcript` — dataclass `Transcript(text, latency_ms, confidence)`, tương tự `offline_poc.stt.Transcript` nhưng có thêm `confidence`.
- `synthesize(text: str) -> Iterator[bytes]` — sinh audio chunk tăng dần từ Piper thay vì ghi cả file rồi đọc lại.

**Không sửa** `src/api/routes.py`, `src/models/schemas.py` trong task này.

## Model assets & settings

- Thư mục mới `models/voice/`, `.gitignore` theo đúng convention của `experiments/offline_poc/.gitignore` (loại trừ `*.metadata.json`, `*.sha256`, còn lại ignore).
- Script conversion một lần (convert PhoWhisper-small từ `vinai/PhoWhisper-small` sang GGUF cho whisper.cpp, tải Piper Vietnamese voice) — setup-time, không nằm trên request path.
- `src/config.py` thêm, đặt tên khớp `docs/devops.md` (bảng "Environment contract") để không lệch tên biến môi trường canonical: `stt_provider` (default `"whisper_cpp"`), `stt_model_path` (khớp `STT_MODEL_PATH`), `tts_provider` (default `"piper"`), `tts_model_path` (khớp `TTS_MODEL_PATH`) — theo pattern khai báo optional đã có (`chroma_persist_dir`).
- Dependency mới: binary whisper.cpp (native, không phải pip package — build/tải sẵn giống `experiments/offline_poc/tools/llama-b9637/` pattern cho llama.cpp), `piper-tts` (pip, thêm vào `requirements.txt`, theo nhóm comment-out tương tự các optional dep khác nếu phù hợp — quyết định cụ thể khi viết plan).

## Data flow

1. Caller (test hoặc code nội bộ tương lai) gọi `voice.transcribe(audio_bytes)`.
2. `get_stt_engine()` trả về singleton đã load (hoặc load lần đầu — chi phí này nằm ngoài ngân sách 400ms).
3. Model chạy inference trên audio, đo `latency_ms` quanh lệnh gọi model (không tính load).
4. Trả `Transcript`.

Tương tự cho `synthesize(text)`, nhưng trả về generator chunk thay vì giá trị đơn.

## Error handling

- Audio không hợp lệ / rỗng / vượt giới hạn thời lượng (30s, theo giả định ADR/spec canonical cho voice turn) → raise `ValueError` rõ ràng từ `transcribe()`, không nuốt lỗi.
- Model checkpoint thiếu (chưa chạy script convert) → lỗi rõ ràng ngay tại `get_stt_engine()`/`get_tts_engine()` (fail-fast khi load), không phải lỗi mơ hồ khi inference.
- Không có xử lý lỗi HTTP (không có endpoint trong task này).

## Testing

- `tests/test_services/test_voice.py` — unit test theo đúng pattern `offline_poc/tests/test_voice.py`: adapter nhận runner/pipeline injectable, test không load model thật, nhanh và deterministic, không phụ thuộc CI vào model files.
- Test tích hợp đánh dấu `@pytest.mark.integration` (skip nếu thiếu model files local):
  - **AC1 (<400ms warm)**: load engine 1 lần, đo lần gọi thứ 2 trở đi, loại trừ cold-start.
  - **AC2 (WER<20%)**: loopback Piper→PhoWhisper trên vài câu tổng hợp, dùng lại `word_error_rate()`/`char_error_rate()` style của `offline_poc.stt` (di chuyển hoặc tái triển khai trong `src/`, cần quyết định khi viết plan). Ghi chú rõ đây là smoke test trên audio tổng hợp, không phải benchmark độ chính xác thật trên giọng người lái thật.
  - **AC3 (streaming)**: `synthesize()` trả về >1 chunk, ghép các chunk lại thành WAV hợp lệ.

## Ngoài phạm vi (out of scope)

- Endpoint HTTP `/voice/transcribe` hoặc `/voice/synthesize` — chuyển sang task tương lai khi có auth/session/turn.
- Tích hợp vào `POST /api/v1/turns/voice` canonical (WebSocket events, stage_latencies_ms) — cùng task tương lai ở trên.
- Đo WER trên corpus giọng người thật — chờ `eval/datasets/poc/v1/audio/manifest.jsonl` có dữ liệu consent-cleared.
- Cập nhật 3 file BMAD mâu thuẫn model/vector-store đã ghi nhận trong `docs/codebase_analysis.md` mục "Phát hiện quan trọng nhất" — không liên quan task này.

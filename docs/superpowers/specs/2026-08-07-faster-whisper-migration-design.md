# Thiết kế: Chuyển STT engine sang faster-whisper (CTranslate2) cho PoC/demo

> Ngày: 2026-08-07. Trạng thái: Đã duyệt (brainstorming), chờ viết implementation plan.
> Nguồn gốc: tiếp nối `feature/voice-asr-tts-design` — sau khi đo benchmark thật cho AC1/AC2, kiến trúc whisper.cpp + resident whisper-server đạt AC1 (latency <1.5s) nhưng AC2 (WER) fail nặng trên cả PhoWhisper-small lẫn PhoWhisper-base qua cùng harness (~88% WER, xem ADR-007 "Benchmark thật 2026-08-07 (sau tối ưu)"), khiến tính năng không dùng được cho demo.

## Bối cảnh & quyết định

Đo thật `ggml-phowhisper-small.bin` qua đúng resident-server harness (không phải qua `whisper-cli` cũ) cho **WER 88.45%** — gần như giống hệt PhoWhisper-base (88.45% vs 84.40%/88.45% tùy lần đo). Điều này loại trừ khả năng lỗi riêng của việc convert GGML cho bản base — cả hai model đều hỏng như nhau qua đường resident-server/HTTP mới xây. Do thời gian PoC/demo có hạn, quyết định (đã duyệt 2026-08-07): **tạm chuyển sang faster-whisper (CTranslate2)** thay vì tiếp tục điều tra sâu nguyên nhân gốc trong whisper.cpp/HTTP pipeline.

Một PoC ngoài repo (`C:\Drive_D\AI thuc chien\DOCS\PoC`) từng báo STT latency ~1.220ms bằng `faster_whisper.WhisperModel("base", compute_type="int8")` (Whisper đa ngôn ngữ gốc của OpenAI, KHÔNG phải PhoWhisper). Số liệu WER "10-15%" người dùng kỳ vọng **chưa được đo/xác nhận trong bất kỳ file PoC nào** — coi là mục tiêu tham khảo cần đo thật, không phải bằng chứng đã có.

**Quyết định engine (đã duyệt)**: dùng `vinai/PhoWhisper-base` (giữ fine-tune tiếng Việt) convert sang CTranslate2, thay vì quay lại Whisper đa ngôn ngữ gốc — đã xác nhận real qua doc CTranslate2:
```
ct2-transformers-converter --model vinai/PhoWhisper-base --output_dir models/voice/phowhisper-base-ct2 --copy_files tokenizer.json preprocessor_config.json --quantization int8
```
Checkpoint HF `vinai/PhoWhisper-base` đã tải sẵn trên máy dev, có đủ `tokenizer.json`/`preprocessor_config.json` cần cho `--copy_files`.

**Quyết định phạm vi (đã duyệt)**: **thay thế hoàn toàn** whisper.cpp/resident-server, không giữ dual-provider switch. Code whisper.cpp resident-server (`WhisperServerHandle`, `start_whisper_server`, mọi `stt_server_*`/`stt_no_fallback`/`stt_request_timeout_s` settings) bị **xóa**, không phải deprecate — có thể khôi phục từ git history nếu cần sau này. Đúng tinh thần YAGNI: chưa có nhu cầu thực tế phải đổi qua lại giữa hai engine.

**Quyết định canonical doc (đã duyệt)**: `docs/devops.md` (Environment contract) được cập nhật `STT_PROVIDER=faster_whisper`, để doc phản ánh đúng thực tế code, tránh lệch pha giống tình huống task tracker vs canonical spec đã gặp đầu phiên làm việc trước.

## Kiến trúc & thành phần

`src/services/voice.py`:
- `WhisperCppEngine` đổi tên thành `FasterWhisperEngine` — phản ánh đúng engine thật.
- Constructor nhận một object kiểu `WhisperModel`-like (constructor injection, giống pattern `PiperEngine(voice)` đã có) — cho phép unit test dùng fake, không cần model thật.
- `transcribe_file(audio_path: Path) -> Transcript` gọi `self._model.transcribe(str(audio_path), language="vi", beam_size=settings.stt_beam_size)` **trực tiếp trong-process** — không subprocess, không HTTP, không port/health-check/atexit cleanup (toàn bộ phần đó bị xóa cùng `WhisperServerHandle`/`start_whisper_server`).
- `get_stt_engine()` singleton (`lru_cache`, giữ pattern cũ): validate `settings.stt_provider != "faster_whisper"` → `ValueError`; validate thư mục model tồn tại → `FileNotFoundError`; load `faster_whisper.WhisperModel(settings.stt_model_path, device="cpu", compute_type=settings.stt_compute_type)` (import `faster_whisper` lazy, giống cách `piper` được import lazy trong `get_tts_engine()`).
- `PiperEngine`/`synthesize()`/`Transcript`/`normalize_vietnamese_text`/`word_error_rate`/`char_error_rate`/`_validate_audio`/`transcribe()` **không đổi**.

## Model assets & settings

- Script mới thay `scripts/setup_voice_models.ps1` (hoặc sửa tại chỗ, quyết định khi viết plan): bỏ toàn bộ phần clone/build whisper.cpp + build `whisper-server`, thay bằng `pip install ctranslate2` + lệnh `ct2-transformers-converter` ở trên. TTS (Piper) phần setup không đổi.
- `.gitignore`: `models/voice/phowhisper-base-ct2/` vẫn nằm trong pattern ignore `models/voice/*` hiện có (thư mục, không phải 1 file — cần xác nhận pattern glob hiện tại có match thư mục con, kiểm tra khi viết plan).
- `src/config.py`:
```python
stt_provider: str = "faster_whisper"
stt_model_path: str = "./models/voice/phowhisper-base-ct2"
stt_compute_type: str = "int8"
stt_beam_size: int = 5
stt_max_audio_seconds: int = 30  # không đổi
```
Xóa: `stt_server_executable_path`, `stt_server_host`, `stt_server_port`, `stt_server_threads`, `stt_no_fallback`, `stt_server_startup_timeout_s`, `stt_request_timeout_s`.

## Testing

- Unit test: `FasterWhisperEngine` với fake `WhisperModel`-like object (`.transcribe(path, language=..., beam_size=...) -> (segments_iterator, info)`, giống chữ ký thật của faster-whisper) — không load model thật.
- Integration test: **tái sử dụng nguyên** `tests/fixtures/voice/warm_sample.wav` và `tests/fixtures/voice/synthetic_commands/` (manifest + 5 WAV, đã cố định từ trước) — chỉ đổi engine bên dưới, không tạo lại fixture.
- AC1/AC2 **đo thật trước, chốt budget sau** — không đoán trước theo đúng cách đã làm với whisper.cpp. Nếu đạt gần mục tiêu PoC gốc (~1s / WER thấp), ghi nhận vào ADR-008; nếu không, ghi nhận thật và quyết định tiếp theo (không tự nới AC để ép pass).

## Error handling

Không đổi so với pattern hiện có: thư mục model CT2 thiếu → `FileNotFoundError` rõ ràng tại `get_stt_engine()` (fail-fast); audio không hợp lệ/quá dài → `ValueError` từ `_validate_audio()` (giữ nguyên). Bề mặt lỗi đơn giản hơn hẳn bản whisper.cpp vì không còn lớp lỗi process/port.

## Documentation

- **ADR-008** (file mới, không sửa đè ADR-007): ghi quyết định chuyển sang faster-whisper cho PoC/demo, dẫn chứng số liệu thật (WER whisper.cpp ~88% qua cả small/base, resident-server harness), liên kết ngược ADR-007 làm bối cảnh lịch sử.
- `docs/devops.md`: cập nhật `STT_PROVIDER=faster_whisper` trong bảng Environment contract.
- `WORKLOG.md`: entry mới ghi nhận quyết định và kết quả đo thật khi implement xong.

## Ngoài phạm vi (out of scope)

- Endpoint HTTP `/voice/transcribe`/`/voice/synthesize` — vẫn ngoài phạm vi (kế thừa ADR-007/ADR-008).
- Giữ lại whisper.cpp như một provider thay thế được — đã quyết định không giữ (YAGNI).
- Điều tra sâu nguyên nhân gốc WER 88% của whisper.cpp/resident-server (có thể là lỗi encode audio qua multipart HTTP, không hẳn do model) — không debug thêm trong phạm vi PoC này; đã ghi nhận đủ bằng chứng để quyết định chuyển engine.
- Đo WER trên corpus giọng người thật — vẫn chờ dữ liệu consent-cleared, kế thừa từ ADR-007.

# Thiết kế: Voice adapter — tối ưu benchmark AC1 (latency) & AC2 (WER)

> Ngày: 2026-08-07. Trạng thái: Đã duyệt (brainstorming), chờ viết implementation plan.
> Nguồn gốc: follow-up cho [ADR-007](../../adr/ADR-007-voice-adapter-engine-binding.md) sau khi module `src/services/voice.py` (whisper.cpp + PhoWhisper-small, PR #15) đã merge và được đo benchmark thật lần đầu trên model đã tải — cả AC1 (`<400ms` warm) và AC2 (`WER <20%`) đều **fail** trên phần cứng dev.
> Phần cứng dev đã được xác nhận là **mô phỏng đúng phần cứng triển khai thật** (CPU-only, không GPU/NPU) — mọi kết luận dưới đây áp dụng cho phần cứng target, không phải giới hạn tạm thời của máy dev.
> Bối cảnh sử dụng: thoại tự do/hỏi đáp mở (không phải tập lệnh cố định, không dùng được keyword-spotting/grammar giới hạn để "ăn gian" WER).

## Bối cảnh & bằng chứng thực nghiệm (2026-08-07)

Sau khi tải model thật (`ggml-phowhisper-small.bin`, `vi_VN-piper.onnx`) và chạy `pytest -m integration` không skip, cả hai AC fail: **AC1 đo được 6.505ms** (budget 400ms), **AC2 đo được WER 39,64%** (budget <20%).

Đã điều tra tách biệt từng nguyên nhân bằng benchmark thật (không suy đoán):

### AC1 — latency

| Cấu hình | Load model | Encode | Total (1 lần gọi) |
|---|---|---|---|
| small, mặc định (beam=5/best-of=5, 4 threads) | 861ms | 4.791ms | 6.143ms |
| small, greedy (beam=1/best-of=1, 4 threads) | 785ms | 4.744ms | 5.743ms |
| small, greedy, 16 threads | 804ms | 2.185ms | 3.171ms |
| small, quantize q5_0, 16 threads | 148ms | ~2.6-2.7s (không cải thiện) | ~3,6s |
| **base**, f16, 16 threads, audio thật 1.4s | 284ms | **592ms** | **1.183ms** |
| base, q5_0, 16 threads | 142-148ms | 656-685ms (không cải thiện rõ) | 1.080-1.180ms |
| tiny, f16, 16 threads, audio thật | 188-200ms | 278-312ms | 740-785ms |
| **base, whisper-server resident (đã "ấm"), HTTP** | 0 (đã load sẵn) | — | **~914-943ms, ổn định, không giảm thêm** |

Kết luận: beam search không phải nút thắt (greedy giảm không đáng kể). **Chi phí chính là encode compute của model trên CPU** — quantize (f16→q5_0) hầu như không giúp (compute-bound, không phải memory-bandwidth-bound, khác cơ chế với LLM decode tự hồi quy). Đổi sang model nhỏ hơn (small→base) giúp nhiều nhất (~4x). Loại bỏ chi phí load-model-mỗi-lần-gọi bằng resident server giúp thêm, nhưng **trần thực tế đo được sau khi tối ưu hết các đòn bẩy CPU khả dụng là ~900ms-1,2s, vẫn gấp hơn 2 lần budget 400ms**.

### AC2 — WER

| Model | WER loopback (Piper→whisper.cpp, 5 câu) | Ghi chú |
|---|---|---|
| small | 39,64% | Nhầm từ gần âm (vd. "đắt"/"đặt") |
| base | 67,26% (đo 1 lần) | Chính xác trên audio thật, nhưng **hallucinate token rác ở đầu câu** khi gặp audio Piper tổng hợp (vd. "són bật...", "wasp từ lúc...") |
| tiny | 100% (hỏng hoàn toàn) | Chỉ trả "." trên mọi câu loopback |

Nguyên nhân hallucination: whisper.cpp có cơ chế "temperature fallback" — khi decoder không tự tin (audio robot lạ), tự động retry ở nhiệt độ cao hơn, mỗi lần retry tốn thêm encode+decode (giải thích tại sao có lần đo latency loopback lên tới ~4s dù model base chỉ mất 592ms trên audio thật).

**Phát hiện nghiêm trọng về phương pháp đo**: `PiperEngine.synthesize()` **không deterministic** — gọi 2 lần cùng một câu cho ra 2 audio khác nhau (số byte khác nhau, xác nhận bằng `a == b` → `False`). Điều này khiến AC2 hiện tại **không tái lập được** (flaky) độc lập với việc chọn model nào — mọi so sánh model A/B dựa trên loopback sống đều không đáng tin.

## Quyết định thiết kế

### 1. Đổi model: PhoWhisper-small → PhoWhisper-base

- `stt_model_path` mặc định trỏ tới GGUF convert từ `vinai/PhoWhisper-base` (đã xác nhận tồn tại trên HuggingFace, cùng họ với `-tiny`/`-small`/`-medium`/`-large`).
- `scripts/setup_voice_models.ps1` cập nhật bước `hf download` + convert để dùng `PhoWhisper-base` thay vì `PhoWhisper-small`.
- Không chọn `tiny`: hỏng hoàn toàn trên audio tổng hợp (WER 100%) — rủi ro quá cao dù nhanh nhất.
- Không đổi TTS (Piper) — vấn đề TTS không nằm trong scope AC1/AC2 lần này.

### 2. Đổi engine STT: subprocess `whisper-cli` → resident `whisper-server`

- `WhisperCppEngine` spawn `whisper-server.exe` (đã có sẵn trong `models/voice/` sau setup script) làm subprocess con **một lần** khi `get_stt_engine()` khởi tạo, với `-m <model> --host 127.0.0.1 --port <port> -t <n_threads>`.
- Health-check cổng (poll `/` hoặc thử request nhỏ) trước khi coi engine sẵn sàng, timeout rõ ràng nếu server không lên.
- `transcribe_file()`/`transcribe()` gọi `POST http://127.0.0.1:<port>/inference` (multipart: `file`, `response_format=json`, `temperature=0`) thay vì gọi subprocess CLI mỗi lần.
- **Vòng đời tiến trình server**: vì module vẫn ở phạm vi nội bộ (không FastAPI lifespan hook trong task này), singleton `get_stt_engine()` chịu trách nhiệm giữ handle tiến trình; test và code gọi trực tiếp (script, pytest) phải tự dọn dẹp (terminate) khi xong — cần thiết kế rõ trong plan (vd. context manager hoặc `atexit`), tránh rò rỉ tiến trình `whisper-server.exe` treo lại sau khi test chạy xong (đã tự gặp vấn đề này khi thử nghiệm thủ công, phải `taskkill` tay).

### 3. Giảm hallucination khi gặp audio lạ

- Khởi động `whisper-server` với `-nf` (tắt temperature-fallback) hoặc nới `--entropy-thold`/`--logprob-thold`/`--no-speech-thold` — chọn tổ hợp cụ thể bằng đo thực nghiệm khi viết plan (chưa chốt số chính xác, cần benchmark thêm vài vòng trước khi hard-code).

### 4. Sửa phương pháp đo AC2: fixture cố định thay vì synth sống

- Sinh sẵn N câu lệnh mẫu bằng Piper **một lần**, lưu thành `.wav` cố định dưới `tests/fixtures/voice/synthetic_commands/`.
- Integration test AC2 đọc từ fixture thay vì gọi `synthesize()` mỗi lần chạy test — WER giờ tái lập được, so sánh model/tham số công bằng giữa các lần chạy.
- Giữ nguyên chú thích rằng đây vẫn là smoke test trên audio tổng hợp, không phải benchmark độ chính xác giọng người thật (theo caveat gốc của ADR-007).

### 5. Đề xuất nới AC1 (cần duyệt riêng với stakeholder/task tracker)

- Đề xuất đổi AC1 latency-warm từ `<400ms` thành **`<1.5s`**, dựa trên trần đo được thật (~900ms-1,2s sau khi tối ưu hết mức có thể trên CPU: base model + resident server + threads tối đa). Đây không phải giới hạn của cách implement — đã thử quantize, giảm model size, bỏ beam search, loại chi phí load — mà là giới hạn compute-bound thật của CPU này cho một encoder Whisper-base.
- Nếu sau khi tune fallback-threshold vẫn không vào được `<1.5s`, ghi nhận là cần GPU/NPU, không tiếp tục tối ưu thuần software trong task tiếp theo.
- Việc đổi AC1 chính thức là quyết định sản phẩm, không tự quyết trong task này — spec chỉ đề xuất kèm bằng chứng, task tracker/PRD cần cập nhật riêng nếu đồng ý.

## Kiến trúc & thành phần (thay đổi so với ADR-007)

`src/services/voice.py`:
- `WhisperCppEngine` đổi nội bộ: thêm quản lý tiến trình `whisper-server` (spawn, health-check, terminate), thêm HTTP client gọi `/inference` (dùng `requests` hoặc `httpx` — quyết định cụ thể khi viết plan, cần thêm dependency mới nếu project chưa có sẵn HTTP client đồng bộ phù hợp).
- `get_stt_engine()` singleton vẫn giữ `lru_cache`, nhưng giờ nắm giữ tiến trình con thay vì chỉ path tới binary.
- `PiperEngine`/`synthesize()` không đổi.

## Model assets & settings

- `scripts/setup_voice_models.ps1`: đổi bước convert sang `vinai/PhoWhisper-base`; `.gitignore` không đổi (vẫn ignore `models/voice/*`).
- `src/config.py`: `stt_model_path` default đổi tên file tương ứng base; thêm `stt_server_port` (default, vd. `8090`) và `stt_server_startup_timeout_s` nếu cần cấu hình.

## Testing

- Unit test: `WhisperCppEngine` cần fake HTTP client + fake process-lifecycle (thay fake subprocess runner cũ) — không phụ thuộc server thật, nhanh, deterministic.
- Integration test (`@pytest.mark.integration`, gate như cũ):
  - **AC1**: đo latency thật qua HTTP `/inference` sau khi server đã "ấm" (loại trừ thời gian spawn/health-check ban đầu, giống tinh thần "warm" gốc).
  - **AC2**: dùng fixture `.wav` cố định (mục 4 ở trên), so sánh WER trước/sau đổi model để có số liệu nhất quán.
- Cần đảm bảo test cleanup: terminate tiến trình `whisper-server` sau mỗi test session (fixture `yield` + teardown), tránh rò rỉ tiến trình.

## Ngoài phạm vi (out of scope)

- Đổi phần cứng (GPU/NPU) — nằm ngoài phạm vi tối ưu software.
- Endpoint HTTP `/voice/transcribe`/`/voice/synthesize` — vẫn ngoài phạm vi theo ADR-007.
- WER trên corpus giọng người thật — vẫn chờ dữ liệu consent-cleared.
- Quyết định chính thức nới AC1 trong task tracker/PRD — đây là quyết định sản phẩm, task này chỉ đề xuất kèm bằng chứng.
- Tối ưu SLM (Qwen/Phi qua llama.cpp) — vấn đề riêng, đã có ghi nhận trong `eval/results/report.md`, không thuộc phạm vi voice adapter.

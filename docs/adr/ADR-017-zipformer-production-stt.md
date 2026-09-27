# ADR-017: Chuyển STT production sang Zipformer-30M-RNNT-6000h (sherpa-onnx)

- Status: Accepted (PoC/demo scope) — supersedes ADR-008's engine choice
- Date: 2026-08-12
- Decision owner: WS1 Voice & Edge

## Context

ADR-008 chọn faster-whisper (PhoWhisper-base qua CTranslate2) làm engine STT sau khi
whisper.cpp/GGML cho WER ~88% không dùng được. faster-whisper cải thiện xuống 30.24%
trên loopback synthetic — vẫn FAIL so với budget 20% ban đầu, và ADR-008 tự ghi nhận đây
chỉ là quyết định phạm vi PoC/demo.

Một báo cáo lỗi thực tế trong quá trình phát triển ("áp suất lốp là bao nhiêu" bị nhận
thành "nốt cà bao nhiêu") dẫn tới một cuộc điều tra hai giai đoạn:

- **Phase 1** (`docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md`) xây dựng
  công cụ so sánh WER/CER giữa PhoWhisper-base và `hynt/Zipformer-30M-RNNT-6000h` (một
  model ASR tiếng Việt train trên 6000h dữ liệu, chạy qua `sherpa-onnx`), trên bộ 24 câu
  domain-specific (áp suất lốp, điều hòa, âm lượng), ban đầu bằng audio Piper TTS synthetic.
- Sau khi có công cụ, nhóm tự thu thêm 26 mẫu giọng người thật (1 người nói) cho cùng 24
  câu, chạy lại so sánh.

## Real benchmark section

Run cuối cùng: `eval/results/stt-compare/20260812T133954.391653Z/metrics.json`
(50 case: 24 synthetic + 26 giọng thật):

- **Tổng thể:** PhoWhisper avg WER 26.12%, Zipformer avg WER 8.08%. Zipformer avg
  latency ~131ms, PhoWhisper avg latency ~1053ms (trên cùng máy dev).
- **Chỉ tính 26 case giọng thật:** PhoWhisper avg WER 20.5%, Zipformer avg WER 3.8%.
- **Quan sát định tính quan trọng:** đọc từng transcript giọng thật cho thấy PhoWhisper
  gần như luôn cắt mất hoặc làm sai từ đầu tiên của câu (vd "Áp suất lốp..." →
  "lốp hiện tại...", "Bật điều hòa" → "mật điều hòa", một case bịa hẳn cụm từ "thông
  minh hồ ngọc hà" không liên quan). Zipformer không có pattern này trên cùng file. Đây
  là bằng chứng cho thấy lỗi ban đầu ("nốt cà bao nhiêu") nhiều khả năng là lỗi cắt đầu
  audio của PhoWhisper, không hẳn là giới hạn từ vựng domain như giả thuyết ban đầu.
- **Theo domain** (from `by_domain` trong cùng file): HVAC 39.9%→6.0%, baseline (từ đã
  biết) 24.0%→6.7%, tire_pressure 32.2%→14.4% — Zipformer tốt hơn rõ rệt ở mọi domain
  trên bộ synthetic; domain volume ban đầu synthetic không cải thiện (28.1%→27.6%). Lưu ý:
  `by_domain` không tách riêng được giọng thật theo domain — cả 26 case giọng thật đều rơi
  vào bucket `"unknown"` vì checklist gán domain (`domain_by_id` trong
  `scripts/eval_stt_compare.py`) chỉ khớp `audio_id` của bộ synthetic gốc, không khớp hậu
  tố `-spk-you-01`/`-real` của file giọng thật — nên **không có con số volume-domain riêng
  cho giọng thật** để so sánh với 28.1%→27.6% synthetic ở trên; con số 20.5%→3.8% ở mục
  "Chỉ tính 26 case giọng thật" phía trên là mức tổng hợp, không tách theo domain.
- Sau khi tích hợp vào `src/services/voice.py`: đo lại thật trên máy dev này bằng
  `get_stt_engine()`/`transcribe()` (không phải qua `scripts/eval_stt_compare.py`
  của Phase 1) — warm latency trung bình 5 lần gọi trên `tests/fixtures/voice/warm_sample.wav`
  là **120.4ms**; WER trung bình trên 5 câu của `tests/fixtures/voice/synthetic_commands/`
  là **9.17%**. Xem `tests/test_services/test_voice_integration.py` cho quy trình đo
  đầy đủ và cho budget được tính từ hai số này (latency: làm tròn lên 50ms rồi nhân
  đôi; WER: cộng 5 điểm phần trăm rồi làm tròn lên).

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Giữ faster-whisper/PhoWhisper-base (ADR-008) | Không cần thay đổi | WER cao hơn 3x, latency cao hơn 8x, và có pattern cắt-đầu-câu hệ thống trên giọng thật |
| **Zipformer-30M-RNNT-6000h qua sherpa-onnx (đã chọn)** | WER thấp hơn nhiều, latency thấp hơn nhiều, không có pattern cắt đầu câu | Model dưới license `cc-by-nc-nd-4.0` (non-commercial, no-derivatives — chấp nhận được vì dự án học thuật phi thương mại, không fine-tune); `sherpa_onnx.OfflineRecognizer` chưa có tài liệu chính thức về thread-safety, phải tự serialize bằng lock như đã làm với faster-whisper |
| Giữ cả hai, chọn qua config | An toàn hơn để rollback | Tăng bề mặt bảo trì (2 code path), không cần thiết khi bằng chứng đã rõ ràng |

## Decision

Thay `FasterWhisperEngine` bằng `ZipformerEngine` trong `src/services/voice.py`, thay
thế hoàn toàn (không giữ song song), theo đúng pattern ADR-008 đã dùng khi thay
whisper.cpp. `STT_PROVIDER` canonical value đổi từ `faster_whisper` sang `sherpa_onnx`.

## Rationale

- Bằng chứng đo được (không phải suy đoán): WER thấp hơn 3x, latency thấp hơn 8x, trên
  cả synthetic lẫn giọng người thật, đo trên cùng máy dev bằng cùng công cụ.
- Pattern cắt-đầu-câu của PhoWhisper xuất hiện nhất quán trên nhiều domain khác nhau
  (lốp, điều hòa, âm lượng, cả các lệnh baseline đã biết) — không phải nhiễu ngẫu nhiên.
- License `cc-by-nc-nd-4.0` phù hợp phạm vi dự án (học thuật, phi thương mại, không
  fine-tune model).

## Consequences

- `docs/devops.md`'s `STT_PROVIDER`/`STT_MODEL_PATH` canonical values đổi — ADR này là
  văn bản authorize thay đổi đó.
- `pyproject.toml`'s `voice` extra đổi từ `faster-whisper` sang `sherpa-onnx`.
- `scripts/setup_voice_models.ps1` đổi từ tải+convert PhoWhisper sang tải Zipformer.
- `Settings.stt_beam_size` bị xóa (đặc thù Whisper, không áp dụng cho decoding
  `greedy_search` của transducer).
- **Vẫn là quyết định phạm vi PoC/demo, không phải kết luận production cuối cùng.**
  Bằng chứng giọng thật chỉ có **1 người nói** — chưa có đa dạng giọng vùng miền, giới
  tính, độ tuổi, hay điều kiện nhiễu (cabin thật khi xe chạy). Cùng giới hạn ADR-008 tự
  khai báo cho số đo của nó.
- Concurrency: giữ nguyên pattern `threading.Lock` serialize `.transcribe_file()`, vì
  `sherpa_onnx.OfflineRecognizer` chưa có xác nhận chính thức về thread-safety khi gọi
  đồng thời — đánh đổi tương tự ADR-008 đã chấp nhận cho faster-whisper.

## Revisit when

- Có nhiều người nói hơn (đa dạng vùng miền/giới tính) ghi âm vào
  `eval/datasets/poc/v1/audio/` — chạy lại `scripts/eval_stt_compare.py` để xác nhận
  margin vẫn giữ.
- Có phần cứng target thật (không phải máy dev) để đo lại latency.
- `sherpa_onnx.OfflineRecognizer`'s thread-safety được xác nhận chính thức (hoặc có test
  concurrency riêng) — có thể bỏ lock nếu an toàn, tăng throughput.

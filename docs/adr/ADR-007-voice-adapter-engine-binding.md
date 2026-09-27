# ADR-007: Voice Adapter Engine Binding (STT/TTS) và phạm vi module

- Status: Accepted (engine binding + revised AC1 budget) — AC1 latency-warm budget revised 400ms → 1.5s và áp dụng trong `tests/test_services/test_voice_integration.py`; AC2 loopback WER dùng fixture cố định (`scripts/generate_voice_wer_fixtures.py`) thay vì `synthesize()` sống. Sau tối ưu (PhoWhisper-base + resident whisper-server): **AC1 PASS (~977ms)**, **AC2 vẫn FAIL (88.45% WER)** kể cả sau khi sửa tham số `language=vi` bị thiếu trong POST request — xem "Benchmark thật 2026-08-07 (sau tối ưu...)" bên dưới.
- Date: 2026-08-07 (cập nhật benchmark thật cùng ngày, sau khi tải model; cập nhật lại sau fix tham số `language`)
- Decision owner: WS1 Voice & Edge (nguồn: task tracker "Tích hợp PhoWhisper (ASR) & Piper (TTS) vào FastAPI server")

## Context

Task tracker mô tả tích hợp ASR/TTS với hai tên engine không nhất quán ("PhoWhisper" ở tiêu đề, "Faster-Whisper base int8" ở mô tả), một endpoint `/voice/transcribe` đồng bộ, và AC latency/WER cụ thể. `experiments/offline_poc` đã có sẵn cả `PhoWhisperAdapter` (Transformers) và `WhisperCppAdapter` (whisper.cpp binary), cùng `PiperAdapter` (subprocess). `docs/devops.md` (Environment contract) đã ghi canonical target `STT_PROVIDER=whisper_cpp`, `TTS_PROVIDER=piper` — không phải faster-whisper/CTranslate2. `docs/technical_spec.md:23` xác nhận nhóm "Whisper.cpp, PhoWhisper, and Piper" chạy như library/native binary/subprocess sau một "voice adapter" nội bộ, không phải service riêng. `docs/api_spec.md` chỉ định nghĩa endpoint voice công khai duy nhất là `POST /api/v1/turns/voice` (bất đồng bộ, cần auth/session/turn/idempotency — hạ tầng này chưa tồn tại trong `src/`).

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| **whisper.cpp + PhoWhisper GGUF** (đã chọn) | Khớp đúng `STT_PROVIDER=whisper_cpp` canonical; native/quantized, không kéo thêm dependency Python ML nặng (torch) vào `src/`; đã có pattern `WhisperCppAdapter` trong `offline_poc` để tham khảo | Chưa có checkpoint GGUF cho PhoWhisper trong repo — cần script convert mới; cần quyết định `whisper-cli` (subprocess/lần) hay `whisper-server` (resident) để đạt latency warm mong muốn |
| Faster-Whisper (CTranslate2) | Nhanh, int8 tốt, đúng nghĩa đen mô tả task | Không xuất hiện ở bất kỳ doc canonical (Họ B) nào — chỉ ở mô tả task và Họ A (`_bmad-output/.../ADR.md`); thêm engine thứ ba vào codebase (Transformers, whisper.cpp, CTranslate2) không cần thiết |
| Faster-Whisper — đo lại 2026-08-07 sau khi có PoC ngoài repo (`C:\Drive_D\AI thuc chien\DOCS\PoC`) báo STT 1.220ms | Đo thật trên cùng máy, cùng câu (~3.6s): **~995-1.064ms**, nhanh hơn whisper.cpp base ~35-40% (whisper.cpp base+`-nf`+16 threads cùng câu: ~1.520-1.610ms) | Vẫn cách xa 400ms gốc như whisper.cpp — không phải "đạt yêu cầu" (PoC nguồn cũng tự ghi N1 latency KHÔNG đạt, `PoC.md` mục 6). Với AC1 đề xuất nới `<1.5s` (xem [design 2026-08-07-voice-benchmark-optimization](../superpowers/specs/2026-08-07-voice-benchmark-optimization-design.md)), whisper.cpp+base+resident-server đã đủ trong hầu hết trường hợp — lợi ích đổi engine (~500ms) không bù được chi phí revisit `docs/devops.md` canonical env contract + viết lại toàn bộ `WhisperCppEngine` + thêm dependency `ctranslate2`/`av`. **Giữ nguyên quyết định whisper.cpp.** |
| PhoWhisper qua Transformers (tái dùng `offline_poc.PhoWhisperAdapter` nguyên trạng) | Code đã có sẵn, chạy được ngay | Đo thật trong `eval/results/report.md`: p50 6.981,8ms/p95 9.882,5ms, cold-start 16.353,7ms — cách xa AC <400ms; không khớp `STT_PROVIDER=whisper_cpp` |

## Decision

- **STT**: whisper.cpp (native binary) chạy PhoWhisper-small convert sang GGUF, khớp `STT_PROVIDER=whisper_cpp`.
- **TTS**: Piper qua `piper-tts` Python API (không phải subprocess CLI như `offline_poc.tts.PiperAdapter`) để hỗ trợ streaming chunk và tránh chi phí reload model mỗi lần gọi, khớp `TTS_PROVIDER=piper`.
- **Phạm vi**: cả hai chỉ được giao dưới dạng **module nội bộ** `src/services/voice.py` ("voice adapter" theo `technical_spec.md:23`). Không thêm route HTTP nào trong lần triển khai đầu — việc nối vào `POST /api/v1/turns/voice` canonical là quyết định/task riêng, sau khi auth/session/turn tồn tại.
- Settings đặt tên khớp `docs/devops.md`: `stt_provider`/`stt_model_path`/`tts_provider`/`tts_model_path`.

## Rationale

- Tránh lệch tên biến môi trường với canonical env contract đã publish — giảm rework khi Compose/devops thật được dựng.
- whisper.cpp GGUF quantized trên CPU nhìn chung nhanh hơn nhiều so với PyTorch/Transformers pipeline mà `offline_poc` đã đo chậm — hướng khả thi nhất để tiệm cận AC latency, dù chưa có bằng chứng đo thật trong repo cho tổ hợp cụ thể này.
- Giữ nguyên nguyên tắc "no unmeasured claims" của dự án (`docs/devops.md`: "API numeric examples remain fixtures rather than measured claims") — ADR này không tuyên bố đạt AC, chỉ chọn engine hợp lý nhất để theo đuổi rồi benchmark khi implement.
- Giới hạn phạm vi ở module nội bộ tránh kéo theo hạ tầng auth/session/turn chưa tồn tại, giữ task tập trung.

## Consequences

- Cần viết script convert PhoWhisper-small (HF) → GGUF cho whisper.cpp; chưa có sẵn trong repo (chỉ có metadata cho bản Transformers `pytorch_model.bin`).
- Cần quyết định `whisper-cli` (đơn giản, load lại mỗi lần) hay `whisper-server` (resident, phức tạp hơn) khi viết implementation plan, dựa trên benchmark load-time GGUF thật.
- WER chỉ được xác thực qua phương pháp loopback tổng hợp (Piper→whisper.cpp+PhoWhisper) cho đến khi có corpus giọng người thật, consent-cleared (`eval/datasets/poc/v1/audio/manifest.jsonl` hiện trống).
- AC latency "<400ms" chưa được coi là đã đạt cho tới khi có benchmark thật trên phần cứng mục tiêu — nếu thất bại, cần revisit (xem dưới).
- Không có endpoint HTTP `/voice/transcribe`/`/voice/synthesize` sau task này; caller hiện tại chỉ là test/code nội bộ.

## Benchmark thật 2026-08-07 (model đã tải, đo trên máy dev)

Sau khi tải `ggml-phowhisper-small.bin` + `vi_VN-piper.onnx` và chạy `pytest -m integration` thật (không skip), cả hai AC đều **không đạt**:

- **AC1 (<400ms warm): FAIL — đo được 6505ms** qua `transcribe()` (đường dẫn subprocess `whisper-cli.exe` hiện tại).
  - Tách riêng bằng cách gọi `whisper-cli.exe` trực tiếp trên audio 0.6s: `load time` ~800ms, `encode time` **4744–4791ms** (mặc định `-bs 5 -bo 5`, 4 threads).
  - Thử `-bs 1 -bo 1` (greedy, bỏ beam search): encode vẫn ~4744ms — hầu như không đổi. Kết luận: **chi phí không nằm ở beam search**.
  - Thử thêm `-t 16` (dùng hết 16 thread thay vì mặc định 4): encode giảm còn ~2185ms, total ~3171ms — cải thiện đáng kể nhưng **vẫn gấp ~8 lần budget 400ms**.
  - ⇒ Chi phí encode Whisper-small (12 layer, 768-dim) trên CPU máy dev là nút thắt chính, không phải overhead load-model-mỗi-lần-gọi. Chuyển `whisper-cli`→`whisper-server` (resident) chỉ cắt được phần load (~800ms), **không đủ** để về dưới 400ms.
- **AC2 (<20% WER): FAIL — đo được 39.64%** trên loopback Piper→whisper.cpp, 5 câu lệnh điều khiển tiếng Việt ngắn. Ví dụ quan sát: model trả `"bất điều hòa"` thay vì `"bật điều hòa"` — nhầm lẫn từ khóa điều khiển gần âm, không phải lỗi resample/format (đã xác nhận riêng: Piper thật ra âm ở 22050Hz chứ không phải 16000Hz như spec giả định ban đầu, phải resample về 16kHz trước khi đưa vào whisper.cpp — đã sửa trong `tests/test_services/test_voice_integration.py`).

**Ý nghĩa đối với quyết định "whisper.cpp + PhoWhisper GGUF" ở trên**: engine binding (whisper.cpp/Piper, thay vì CTranslate2/Transformers) vẫn là lựa chọn hợp lý nhất theo canonical `STT_PROVIDER=whisper_cpp` — **nhưng AC gốc "<400ms" không khả thi trên CPU của phần cứng dev hiện tại** với PhoWhisper-small, dù đã tối ưu threads/beam. Cần một trong: (a) benchmark trên phần cứng target thật (có thể có GPU/NPU khác máy dev), (b) đổi sang checkpoint nhỏ hơn (PhoWhisper-tiny/base) đánh đổi lấy WER, hoặc (c) nới lại AC latency. Đây là quyết định ngoài phạm vi task hiện tại — để task/ADR follow-up.

## Benchmark thật 2026-08-07 (sau tối ưu: PhoWhisper-base + resident whisper-server)

Kiến trúc đổi so với benchmark ở trên: `stt_model_path` chuyển sang `ggml-phowhisper-base.bin` (thay vì `-small`), `WhisperCppEngine` không còn spawn `whisper-cli.exe` mỗi lần gọi mà nói HTTP tới một `whisper-server` resident (`start_whisper_server()`, xem `src/services/voice.py`), khởi động với cờ `-nf` (no-fallback, tắt temperature fallback) và `-t <threads>`. AC1 budget được nới `400ms → 1.5s` (xem Status line) dựa trên benchmark thật ở mục trên.

- **AC1 (<1.5s warm): PASS — đo được ~977ms** qua `transcribe()` (đường dẫn HTTP tới resident `whisper-server.exe`, model PhoWhisper-base, `-nf`, threads = CPU count). Số đo gốc từ Task 7 (`.superpowers/sdd/2026-08-07-voice-benchmark-optimization/task-7-report.md`) cũng xác nhận PASS trên cùng kiến trúc.
- **AC2 (<20% WER): FAIL.**
  - Lần đo đầu (Task 7, trước fix finding này): trung bình **84.40%** trên 5 câu lệnh loopback Piper→whisper.cpp cố định (`tests/fixtures/voice/synthetic_commands/`).
  - Điều tra sau đó phát hiện: `WhisperCppEngine.transcribe_file()`'s POST tới `/inference` **không hề gửi field `language`** trong multipart form — theo source thật của `whisper.cpp`'s `examples/server/server.cpp`, server mặc định `language = "en"` khi field này vắng mặt. Nghĩa là toàn bộ các phép đo AC2 trước đây (kể cả 84.40%) đã chạy ở chế độ decode tiếng Anh trên audio tiếng Việt.
  - Đã sửa: thêm `"language": "vi"` vào `data` dict của POST request (per-request, không phải cờ khởi động server — giữ server dùng lại được cho ngôn ngữ khác sau này). Xác nhận bằng thực nghiệm trực tiếp (`httpx.post` thủ công tới `/inference` với `language=None` vs `language="vi"` vs `language="en"`) rằng server THỰC SỰ đổi output theo field này — field được server tôn trọng đúng như kỳ vọng.
  - **Đo lại thật sau fix: trung bình WER = 88.45%** (`assert 0.8845238095238093 < 0.2` FAILED) — **không cải thiện, thậm chí nhích lên nhẹ so với 84.40%** ban đầu. Vậy tham số `language` bị thiếu **không phải** nguyên nhân chính của WER cao; giả thuyết ban đầu trong finding review đã bị bác bỏ bởi số đo thật.
  - Quan sát định tính từ output thật (5 câu, transcribe trực tiếp, không qua test assertion): mô hình chèn các token tiếng Anh vô nghĩa không liên quan ngữ cảnh (`"blue moon touch thảm đỏ..."`, `"gold mơ cửa sổ..."`, `"forbes tay tăng tốc độ..."`) lẫn vào giữa câu tiếng Việt đúng một phần. Kiểu lỗi này gợi ý vấn đề nằm ở **chất lượng bản convert GGML của PhoWhisper-base** (vocab/tokenizer hoặc trọng số) hoặc ở chính fixture audio tổng hợp (Piper→WAV), không phải ở tham số ngôn ngữ per-request. Đây là hướng điều tra để lại cho task follow-up — nằm ngoài phạm vi fix hiện tại (chỉ sửa tham số `language` bị thiếu, không sửa chất lượng model).
  - Full pytest output thật, xem `.superpowers/sdd/2026-08-07-voice-benchmark-optimization/final-fix-report.md`.
  - **Kiểm tra chéo cùng harness (brainstorming session dẫn tới `2026-08-07-faster-whisper-migration`)**: để loại trừ khả năng 88.45% là vấn đề riêng của bản convert GGML cho PhoWhisper-**base**, đã đo thêm `ggml-phowhisper-small.bin` qua **cùng** resident-server/HTTP harness (`whisper-server`, không phải subprocess `whisper-cli` cũ ở mục benchmark 2026-08-07 phía trên) — kết quả cũng ra **WER 88.45%**, gần như trùng khớp với bản base. Vì cùng harness cho ra cùng con số trên hai kích thước model khác nhau, WER cao nhiều khả năng không phải do kích thước model mà do một yếu tố chung của kiến trúc resident-server/GGML này (transport HTTP, bước convert GGML, hoặc audio fixture). Xem `docs/superpowers/specs/2026-08-07-faster-whisper-migration-design.md` cho ghi chép gốc của phép đo này.

## Revisit when

- ~~Benchmark thật whisper.cpp+PhoWhisper-GGUF không đạt latency warm mục tiêu~~ → **Đã xảy ra (xem benchmark thật ở trên, 2026-08-07)**. Đã giải quyết bằng resident `whisper-server` + PhoWhisper-base + revised AC1 budget 1.5s — **AC1 nay PASS (~977ms)**.
- **AC2 (WER) vẫn FAIL sau khi sửa tham số `language` bị thiếu (88.45%, gần như không đổi so với 84.40%)** → cần task follow-up điều tra chất lượng bản convert GGML của PhoWhisper-base (so sánh với PhoWhisper-small, vốn đo được 39.64% trên cùng phương pháp loopback với engine subprocess cũ) và/hoặc chất lượng audio fixture tổng hợp, trước khi thử lại AC2. Không nới lại budget 20% mà chưa có bằng chứng đây là giới hạn hợp lý cho loopback synthetic — xem `scripts/generate_voice_wer_fixtures.py`.
- Hạ tầng auth/session/turn tồn tại → mở task nối `src/services/voice.py` vào `POST /api/v1/turns/voice` canonical thật (bao gồm WebSocket `transcript.final`, `stage_latencies_ms.stt/tts`).
- Có corpus giọng người Việt thật, consent-cleared → đo lại WER thay vì dùng loopback tổng hợp (88.45%/84.40% đo được ở trên chỉ là smoke test tổng hợp, không phải benchmark độ chính xác thật).

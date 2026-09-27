# ADR-008: Chuyển STT sang faster-whisper (CTranslate2) cho phạm vi PoC/demo

- Status: Accepted (PoC/demo scope) — supersedes STT half of ADR-007
- Date: 2026-08-08
- Decision owner: WS1 Voice & Edge (tiếp nối tracker "Tích hợp PhoWhisper (ASR) & Piper (TTS) vào FastAPI server", cùng chuỗi task với ADR-007)

## Context

ADR-007 đã chọn whisper.cpp (native binary, resident `whisper-server`) chạy
PhoWhisper convert sang GGUF làm engine STT, để khớp `docs/devops.md`'s
canonical `STT_PROVIDER=whisper_cpp` tại thời điểm đó. Sau khi tối ưu (chuyển
từ PhoWhisper-small sang PhoWhisper-base, chuyển từ subprocess `whisper-cli`
mỗi lần gọi sang resident `whisper-server` qua HTTP, nới AC1 budget 400ms →
1.5s), benchmark thật ghi trong ADR-007's "Benchmark thật 2026-08-07 (sau tối
ưu: PhoWhisper-base + resident whisper-server)" cho kết quả:

- AC1 (latency warm, <1.5s): **PASS — ~977ms**.
- AC2 (WER loopback synthetic, <20%): **FAIL — 88.45%** với PhoWhisper-base
  qua resident `whisper-server`. Kiểm tra thêm PhoWhisper-**small** qua **cùng**
  resident-server/HTTP harness (không phải subprocess `whisper-cli` cũ, vốn đo
  được 39.64% ở benchmark trước đó trong ADR-007) cũng cho ra **88.45%** —
  cùng harness, cùng con số trên hai kích thước model khác nhau, nên WER cao
  nhiều khả năng không phải do kích thước model hay do thiếu tham số
  `language=vi` trong POST request (đã thử sửa field này riêng cho bản base,
  WER không cải thiện, thậm chí nhích nhẹ so với lần đo trước khi sửa).

Một WER ~88% khiến tính năng STT không thể dùng được cho demo — gần như mọi
câu lệnh điều khiển tiếng Việt ngắn đều bị nhận dạng sai. ADR-007 ghi nhận
quan sát định tính (model chèn token tiếng Anh vô nghĩa xen giữa câu tiếng
Việt đúng một phần) và đưa ra giả thuyết nguyên nhân nằm ở chất lượng bản
convert GGML của PhoWhisper (vocab/tokenizer hoặc trọng số) hoặc ở audio
fixture tổng hợp — nhưng **không xác định được nguyên nhân gốc rễ giữa hai
giả thuyết này**, và việc điều tra sâu hơn (so sánh trực tiếp
Transformers-checkpoint gốc vs. bản convert GGML, hoặc kiểm tra fixture bằng
tai người) đã bị hoãn lại có chủ đích thay vì chặn PoC lại để điều tra thêm
(xem ADR-007 "Revisit when").

Với một WER ~88% không dùng được, và whisper.cpp/GGML là một mắt xích chưa
được loại trừ khỏi nghi ngờ, việc thử một pipeline STT khác — inference
CTranslate2 trực tiếp trên checkpoint Transformers gốc, bỏ qua bước convert
GGML hoàn toàn — là hướng hợp lý để cô lập xem vấn đề có nằm ở bước convert
GGML hay không, mà không cần điều tra sâu offline trước.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Giữ nguyên whisper.cpp + GGML (ADR-007) | Không cần thay đổi code/dependency thêm nữa | AC2 WER 88.45% không dùng được cho demo; nguyên nhân gốc rễ chưa rõ, có thể cần điều tra sâu (so sánh weight-level) mới sửa được |
| Điều tra sâu bản convert GGML trước khi quyết định đổi engine | Có thể giữ được whisper.cpp nếu tìm ra và sửa được lỗi convert | Tốn thời gian điều tra không có deadline rõ ràng, không đảm bảo tìm ra nguyên nhân; PoC/demo cần một pipeline dùng được sớm hơn |
| **faster-whisper (CTranslate2), inference trực tiếp trên checkpoint `vinai/PhoWhisper-base` convert bằng `ct2-transformers-converter`, in-process** (đã chọn) | Bỏ qua hoàn toàn bước convert GGML (nghi phạm chính) và bước subprocess/HTTP transport (nghi phạm phụ) trong một lần đổi; in-process (không subprocess, không resident HTTP server) giảm bề mặt lỗi vận hành; `ct2-transformers-converter` là tool chính thức, ít rủi ro lỗi convert hơn so với GGUF converter tự viết | Thêm dependency `ctranslate2`/`faster-whisper` vào `src/`; lệch khỏi canonical `STT_PROVIDER=whisper_cpp` cũ — cần ADR này để authorize đổi canonical value; chưa loại trừ hẳn khả năng root cause là audio fixture (không phải GGML) |
| Faster-Whisper qua CTranslate2 (ADR-007's alternatives table, "đo lại 2026-08-07") | Đã có đo latency thật trên máy dev từ trước (~995-1.064ms) | ADR-007 khi đó bác bỏ vì lợi ích latency (~500ms) không bù được chi phí revisit canonical — nhưng đánh giá đó dựa trên whisper.cpp AC2 lúc đó vẫn *chưa* được biết là FAIL nặng (88.45%); bối cảnh đã đổi |

## Decision

Thay whisper.cpp resident-server bằng **faster-whisper (CTranslate2)**, chạy
in-process (không subprocess, không HTTP), model `vinai/PhoWhisper-base`
convert sang định dạng CTranslate2 qua `ct2-transformers-converter` (thay vì
GGUF qua `whisper.cpp`'s converter). Đây là thay thế toàn bộ — code
`WhisperCppEngine`/resident-server trong `src/services/voice.py` bị xoá, không
giữ song song hai engine.

Quyết định này **thu hẹp phạm vi còn PoC/demo**: mục tiêu là có một pipeline
STT dùng được để demo trong ngắn hạn, không phải kết luận cuối cùng về engine
STT cho production.

## Rationale

- Cô lập biến "bước convert model" (GGML vs. CTranslate2) và biến "transport"
  (subprocess/HTTP vs. in-process) cùng lúc — nếu WER cải thiện đáng kể, đủ
  bằng chứng gián tiếp rằng vấn đề nằm ở một trong hai (nhiều khả năng là
  convert GGML, theo quan sát định tính trong ADR-007), mà không cần điều tra
  weight-level tốn thời gian trước.
- In-process CTranslate2 loại bỏ toàn bộ lớp resident-server/HTTP mà ADR-007
  đã phải tự viết (`start_whisper_server()`), giảm bề mặt vận hành và lỗi
  tiềm ẩn không liên quan tới chất lượng nhận dạng.
- Giữ nguyên nguyên tắc "no unmeasured claims" của dự án — quyết định này
  được xác nhận bằng benchmark thật đo lại sau khi implement (xem dưới), không
  chỉ dựa trên kỳ vọng.

## Real benchmark section

Đo thật trên cùng máy dev, cùng phương pháp AC1/AC2 với ADR-007 (loopback
Piper→STT trên `tests/fixtures/voice/synthetic_commands/`, xem
`.superpowers/sdd/2026-08-07-faster-whisper-migration/task-4-report.md`):

- **AC1 (<1.5s warm): PASS — ~1153.5ms**, đo thật 2026-08-08 qua
  `transcribe()` (in-process CTranslate2, model `phowhisper-base-ct2`) bằng
  script đo trực tiếp (`get_stt_engine()` warm-up rồi gọi `transcribe()` lần
  hai, đo `time.perf_counter()`). Task 4's integration test
  (`test_transcribe_warm_latency_is_under_budget`) cũng PASS trên cùng kiến
  trúc nhưng không in số ms cụ thể (assertion chỉ log khi FAIL).
- **AC2 (<20% WER): FAIL — 30.24%** trung bình trên 5 câu lệnh loopback
  Piper→faster-whisper cố định (`assert 0.3023809523809524 < 0.2` FAILED, xem
  Task 4's report cho full pytest output).

**So với các mốc tham chiếu:**

- So với whisper.cpp/GGML (ADR-007, 88.45%): **cải thiện rất lớn** — WER giảm
  từ 88.45% xuống 30.24%, tức giảm gần 3 lần lỗi tương đối. Điều này ủng hộ
  giả thuyết ADR-007 nêu ra rằng phần lớn WER cao trước đây đến từ bước
  convert GGML (hoặc transport HTTP đi kèm), chứ không phải giới hạn cố hữu
  của kiến trúc PhoWhisper-base trên loopback synthetic audio này. Tuy nhiên
  đây vẫn chỉ là bằng chứng gián tiếp — không có so sánh weight-level trực
  tiếp giữa hai bản convert để kết luận chắc chắn.
- So với external PoC's unverified "~1s / 10-15% WER" claim (chưa từng verify
  trong repo, xem ADR-007): AC1 (~1153.5ms) **khớp gần đúng** với "~1s" của
  PoC. AC2 (30.24%) **cao hơn khoảng gấp đôi** so với "~10-15%" — tức vẫn
  **không đạt** kỳ vọng ban đầu của PoC ngoài repo, dù đã cải thiện rất nhiều
  so với whisper.cpp.
- AC2 vẫn **FAIL** so với budget 20% đề ra — quyết định đổi engine này chưa
  giải quyết dứt điểm AC2, chỉ thu hẹp khoảng cách đáng kể.

## Consequences

- `docs/devops.md`'s Environment contract `STT_PROVIDER` canonical value đổi
  từ `whisper_cpp` sang `faster_whisper` — ADR này là văn bản authorize thay
  đổi đó (xem cập nhật kèm theo ADR này).
- Toàn bộ code liên quan whisper.cpp resident-server
  (`start_whisper_server()`, subprocess/HTTP client trong
  `src/services/voice.py`) bị xoá, thay bằng in-process
  `faster_whisper.WhisperModel`. Không còn phụ thuộc vào binary
  `whisper-server.exe`/`whisper-cli.exe` ngoài repo.
- Thêm dependency Python `faster-whisper`/`ctranslate2` vào `src/`
  (`pyproject.toml`) — đánh đổi mà ADR-007's alternatives table trước đó từng
  coi là "không cần thiết"; bối cảnh đã đổi vì AC2 whisper.cpp FAIL nặng.
- **Đây là quyết định phạm vi PoC/demo, không phải kết luận production.** Cần
  benchmark trên phần cứng target thật (không phải máy dev này) trước khi coi
  đây là quyết định cuối cùng cho production. AC2 vẫn FAIL budget 20% — tính
  năng STT chưa đạt chất lượng đủ tin cậy cho demo có người dùng thật đọc lệnh
  tự do; chỉ nên demo có kịch bản/câu lệnh đã biết trước hoặc có UI xác nhận
  lại kết quả nhận dạng.
- WER vẫn chỉ được xác thực qua loopback tổng hợp (Piper→faster-whisper), như
  ADR-007 đã ghi nhận — không phải benchmark trên giọng người thật.
- **Concurrency: đã giảm thiểu bằng lock, chưa tối ưu throughput.**
  `get_stt_engine()` trả về một singleton `WhisperModel` (module-level, qua
  `@lru_cache`). `faster_whisper.WhisperModel` không an toàn khi gọi
  `transcribe()` đồng thời từ nhiều thread — đây là một bước lùi so với
  whisper.cpp resident-server cũ (server đó tự xử lý concurrency của các
  request). `FasterWhisperEngine.transcribe_file()` giờ dùng
  `threading.Lock` để serialize các lần gọi `.transcribe()` đồng thời, loại
  bỏ rủi ro race condition/crash (đã có unit test xác nhận: gọi 4 luồng
  đồng thời, `max_concurrent == 1`). Đánh đổi: các request STT đồng thời sẽ
  xếp hàng tuần tự thay vì chạy song song — chưa gây vấn đề vì chưa có HTTP
  endpoint nào gọi tới (`POST /api/v1/turns/voice` theo ADR-007 vẫn chưa
  được nối dây). Nếu tải đồng thời thực tế lớn, người nối endpoint có thể
  cần thay lock bằng worker pool (`WhisperModel`'s `num_workers`) thay vì
  serialize hoàn toàn.

## Revisit when

- Có phần cứng target thật (không phải máy dev) để đo lại AC1/AC2 — số đo
  hiện tại (~1153.5ms / 30.24%) chỉ có giá trị tương đối trên máy dev này.
- Có corpus giọng người Việt thật, consent-cleared (`eval/datasets/poc/v1/...`
  hiện trống) — để đo WER thật thay vì loopback tổng hợp.
- Có ai đó muốn tiếp tục điều tra whisper.cpp resident-server's WER regression
  (88.45%) — nguyên nhân gốc rễ chưa từng được cô lập dứt điểm (xem ADR-007);
  nếu điều tra ra là lỗi cụ thể có thể sửa (ví dụ lỗi convert GGUF), có thể
  đáng cân nhắc quay lại whisper.cpp vì lợi ích native-binary/không phụ thuộc
  torch runtime nặng.
- AC2 (30.24%) vẫn FAIL budget 20% dưới engine mới — cần điều tra tiếp riêng
  cho faster-whisper (ví dụ: audio fixture tổng hợp có vấn đề, hay giới hạn
  thật của PhoWhisper-base trên câu lệnh ngắn) trước khi coi 20% là khả thi
  hoặc trước khi nới lại budget.

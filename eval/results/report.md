# SPIKE-001 — Benchmark AI Pipeline Offline

## Kết luận

**Quyết định chọn model: Not Yet.** Cả hai Q4 candidate đều chạy từ artifact local và nằm dưới giới hạn RAM 8 GiB, nhưng đều không đạt quality và latency hard gate. Không chọn model tốt nhất tương đối làm primary để tránh biến kết quả PoC chưa đạt thành quyết định production.

Qwen2.5-3B Q4 có chất lượng tốt hơn 0.5B nhưng chậm hơn nhiều. Qwen2.5-0.5B Q4 phù hợp để tiếp tục thử classifier/router có grammar hẹp, không phù hợp làm planner tổng quát ở prompt hiện tại. Q8 không chạy vì cả hai Q4 bắt buộc đều đã trượt gate; tăng precision chưa xử lý được vấn đề prompt/schema/latency.

## So sánh LLM — 20 case control/NLU/plan

| Profile | Run ID | Kích thước model | Peak RSS | Schema hợp lệ | Tool exact | Repair | p50 ms | p95 ms | Gate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| qwen25-05b-q4 | 20260730T100805.585998Z | 468.6 MiB | 598.9 MiB | 55.0% | 15.0% | 45.0% | 3,863.8 | 10,115.2 | FAIL |
| qwen25-3b-q4 | 20260730T101024.064499Z | 2007.4 MiB | 2088.1 MiB | 70.0% | 30.0% | 30.0% | 11,192.9 | 40,271.9 | FAIL |

Hard gate: schema 100%, tool exact ≥90%, p50 ≤2.500 ms, p95 ≤4.500 ms, peak RSS ≤8 GiB. Các chiều không đạt:

- `qwen25-05b-q4`: schema validity < 100%; tool exact match < 90%; p50 > 2,500 ms; p95 > 4,500 ms.
- `qwen25-3b-q4`: schema validity < 100%; tool exact match < 90%; p50 > 2,500 ms; p95 > 4,500 ms.

## So sánh Voice

| Profile | Giao thức | p50 | p95 | Peak RSS | Chất lượng/RTF | Run ID |
|---|---|---:|---:|---:|---|---|
| Piper vais1000 medium | TTS synthetic, 30 prompt | 2,120.5 ms | 2,365.6 ms | 227.6 MiB | RTF p50 1.66 | `20260730T100148.330452Z` |
| PhoWhisper-small | STT trên Piper synthetic, 30 WAV | 6,981.8 ms | 9,882.5 ms | 1602.9 MiB | WER 30.7%; CER 23.6% | `20260730T100312.454360Z` |

Cold-first latency của PhoWhisper bao gồm thời gian load model; kết quả đo là 16,353.7 ms với thời gian load model 5,827.4 ms.
WER/CER ở trên dùng giọng sạch do Piper tạo và chỉ là integration evidence; không được trình bày như độ chính xác trên người lái Việt Nam thật, giọng vùng miền hoặc tiếng ồn cabin.

## E2E demo tương tác

Các run dưới đây truyền WAV thật qua các component local và ghi trace. Chúng không thay thế network-disabled 30-case acceptance hoặc p50/p95 benchmark.

| Run ID | Profile | Case | Route | HITL | Kết quả | System latency | Human wait | Output |
|---|---|---|---|---|---|---:|---:|---|
| 20260802T060944.518785Z | qwen25-3b-q4 | CTRL-002 | control | approve | Hoàn tất | 39,309.8 ms | 6.6 ms | [response.wav](spike-001/20260802T060944.518785Z/response.wav) |
| 20260802T061100.203628Z | qwen25-3b-q4 | RAG-001 | control | — | Thực thi lỗi | 39,608.7 ms | 0.0 ms | [response.wav](spike-001/20260802T061100.203628Z/response.wav) |
| 20260802T061314.728867Z | qwen25-3b-q4 | RAG-001 | rag | — | Grounded | 43,733.3 ms | 0.0 ms | [response.wav](spike-001/20260802T061314.728867Z/response.wav) |

Số interactive E2E run có outcome an toàn/thành công: 2.

## Danh sách run

| Run ID | Loại benchmark | Profile | Raw evidence | Trạng thái |
|---|---|---|---:|---|
| `20260730T100805.585998Z` | llm_microbenchmark | qwen25-05b-q4 | 20/20 | Hoàn tất |
| `20260730T101024.064499Z` | llm_microbenchmark | qwen25-3b-q4 | 20/20 | Hoàn tất |
| `20260730T100148.330452Z` | tts_synthetic_benchmark | piper-vais1000-medium | 30/30 | Hoàn tất |
| `20260730T100312.454360Z` | stt_synthetic_benchmark | phowhisper-small | 30/30 | Hoàn tất |
| `20260802T060944.518785Z` | interactive_e2e_demo | qwen25-3b-q4 | 1/1 | Hoàn tất |
| `20260802T061100.203628Z` | interactive_e2e_demo | qwen25-3b-q4 | 1/1 | Hoàn tất |
| `20260802T061314.728867Z` | interactive_e2e_demo | qwen25-3b-q4 | 1/1 | Hoàn tất |

## Môi trường và artifact

- Host: `Windows-10-10.0.26200-SP0`; kiến trúc `AMD64`; CPU logic `12`.
- Giao thức tài nguyên: 4 CPU thread; llama.cpp context 4.096; completion tối đa 192 token cho LLM benchmark.
- LLM runtime: llama.cpp b9637. STT runtime: Transformers/PyTorch CPU. TTS runtime: Piper 1.4.2/ONNX Runtime.
- Nguồn model/voice, revision, license và SHA-256 được ghi trong từng run manifest và dưới `experiments/offline_poc/models/`.
- Runtime artifact được dùng theo chế độ local-only. Host-level egress-disabled drill chưa được thực hiện và vẫn là acceptance item riêng.

## Bằng chứng Safety, RAG và LangGraph

Typed plan, bounded repair, LangGraph HITL interrupt, stale-state rejection, idempotent execution, grounded citation validation và refusal được kiểm tra bằng automated test. Interactive E2E đã ghi 2 run có outcome an toàn/thành công, nhưng chưa chạy một network-disabled 30-case real-model acceptance; vì vậy release gate Safety/RAG vẫn mở.

## Thử nghiệm giới hạn tiếp theo

1. Thay free-form multi-tool planning bằng deterministic intent/slot routing cho control phổ biến; dành model 3B cho explanation/RAG composition.
2. Rút gọn JSON contract và dùng schema một tool mỗi lượt, sau đó chạy lại cùng 20 case trên 0.5B và 3B.
3. Đánh giá whisper.cpp/PhoWhisper quantized hoặc distil/streaming STT trên 5–8 người nói có consent cùng tiếng ồn cabin; không tối ưu theo Piper WER.
4. Giữ Piper resident như service hoặc dùng Python API; benchmark fresh-process hiện tại làm steady-state TTS latency cao hơn thực tế.
5. Mở rộng interactive demo thành 30-case acceptance và thực hiện explicit egress-disabled drill sau khi nhóm phê duyệt thay đổi trạng thái mạng.

## Trạng thái deliverable

- Benchmark report: hoàn tất với immutable raw evidence.
- Bảng kết quả: hoàn tất.
- Quyết định model cuối: `Not Yet`, kèm bounded follow-up experiment.
- Interactive E2E demo code và raw evidence: hoàn tất cho control và RAG scenario.
- Video demo: đang chờ nhóm quay; không commit video binary.
- User research: chưa bắt đầu; được lập kế hoạch riêng trong roadmap 3–4 tuần.

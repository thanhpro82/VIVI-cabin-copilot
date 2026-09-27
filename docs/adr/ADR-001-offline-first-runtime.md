# ADR-001: Offline-First Local Runtime

- Status: Accepted
- Date: 2026-07-30

## Context

Đề tài phải tiếp tục phục vụ khi mất mạng, đo được latency end-to-end và mô phỏng edge dù nhóm không có Jetson. Runtime phụ thuộc cloud sẽ không chứng minh được giá trị cốt lõi. Tuy nhiên, nhóm chỉ có bốn tuần nên không thể tối ưu cho mọi loại phần cứng.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Cloud-first | Model mạnh, setup nhanh | Không đáp ứng offline; latency/network không kiểm soát |
| Hybrid cloud + local fallback | Gần kiến trúc thương mại | Hai đường chạy tăng scope/eval và có thể che lỗi offline |
| **Local-only P0/P1** | Chứng minh offline rõ, reproducible, privacy tốt | Model nhỏ hơn; cần quản lý CPU/RAM/model files |

## Decision

P0/P1 chạy local-only bằng Docker Compose trên PC/laptop. `llama.cpp` phục vụ SLM GGUF qua local API; STT/TTS/embedding/index/MQTT/DB đều cục bộ. Docker profile giới hạn 4 vCPU/8 GiB cho backend/AI để tạo baseline simulated edge.

Internet chỉ được dùng trước runtime để cài dependency/tải artifact. Offline drill tắt network và là release gate.

## Rationale

- Khớp ràng buộc giá trị quan trọng nhất.
- Giảm số biến trong demo/eval.
- Cho phép trace toàn pipeline và so Q4/Q8 công bằng.
- Không yêu cầu phần cứng ngoài khả năng nhóm.

`llama.cpp` có local OpenAI-compatible server và hỗ trợ GGUF/quantization: [official repository](https://github.com/ggml-org/llama.cpp).

## Consequences

- Model artifact lớn phải preload và có manifest/checksum.
- Cloud model không được dùng làm fallback trong offline demo.
- Tính năng cần dữ liệu realtime ngoài xe bị giới hạn hoặc mô phỏng bằng POI local.
- Benchmark phải ghi rõ “PC/laptop simulated edge”, không gọi là Jetson result.
- CI dùng fake/tiny model; full eval chạy trên máy nhóm.

## Revisit when

- Nhóm có Jetson/automotive edge hardware thật.
- P0/P1 ổn định và cần chứng minh seamless online/offline handover.
- Model/runtime mới vượt quality/latency trong cùng evaluation protocol.


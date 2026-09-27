# Diễn tập offline — run `20260815T103754.705204Z`

- Commit: `3fa9f4822c32` trên `feat/dien-tap-offline`
- Python 3.11.9 · Windows-10-10.0.26200-SP0
- Env: MQTT_ENABLED=false, SLM_ENABLED=false
- Kết quả: **7/7** ca đạt
- Quan sát tầng HĐH: có

| Ca | Mô tả | Đạt | ms | Python thử ra ngoài | HĐH thấy kết nối ngoài |
|---|---|:--:|--:|---|---|
| `guard_self_test` | Cố tình phân giải huggingface.co — PHẢI bị chặn | ✅ | 1 | `getaddrinfo huggingface.co` | — |
| `nap_stt` | Nạp engine sherpa-onnx Zipformer | ✅ | 1701 | — | — |
| `stt` | Chuyển warm_sample.wav thành chữ | ✅ | 47 | — | — |
| `tts` | Tổng hợp giọng Piper | ✅ | 2084 | — | — |
| `rag` | Truy hồi FAISS + embedder E5 trên index VF9 | ✅ | 12595 | — | — |
| `luot_so_tay` | POST /turns/text — câu hỏi sổ tay (RAG) | ✅ | 1625 | — | — |
| `luot_dieu_khien` | POST /turns/text — lệnh điều khiển S1 | ✅ | 227 | — | — |

## Điểm mù

- **native** — Cổng Python không thấy kết nối do mã native mở thẳng qua syscall (`onnxruntime`, `faiss`, `sherpa-onnx` đều là C++, và `onnxruntime` 1.28 nạp sẵn `AzureExecutionProvider`). Lớp `ket_noi_os` hỏi HĐH nên thấy cả C++, nhưng nó **lấy mẫu** một lần sau mỗi ca: một kết nối chớp nhoáng trong lúc ca chạy vẫn lọt, và nó chỉ thấy TCP/UDP. Cả hai lớp đều chỉ nói về TIẾN TRÌNH NÀY — 'không byte nào rời máy' cần diễn tập ngắt card mạng thật.
- **mqtt** — Chạy với MQTT_ENABLED=false. Broker nói chuyện qua loopback nên nó không thể là nguồn egress, nhưng nghĩa là chặng lệnh -> MQTT -> simulator không nằm trong lượt đo này.
- **in_process** — Chạy trong MỘT tiến trình qua TestClient, không phải image Docker hay topology docker-compose. Không nói gì về việc container có tự gọi ra ngoài lúc khởi động.
- **cold_start** — Model STT/TTS/embedder đã có sẵn trên đĩa. Drill chứng minh runtime không tải thêm gì; nó KHÔNG chứng minh được máy chưa từng cần mạng để có model.

> Thời gian trong case_results.jsonl là số đo MỘT lần trên máy dev, KHÔNG phải benchmark. Drill này chứng minh không thành phần Python nào gọi ra ngoài loopback; xem blind_spots cho phần nó không chứng minh.

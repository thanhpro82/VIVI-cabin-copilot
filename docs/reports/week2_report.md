# 📊 BÁO CÁO TIẾN ĐỘ TUẦN 2 (WEEK 2 PROGRESS REPORT)
**Dự án:** VIVI Cabin Copilot — VinUni AI20K Build Phase (Cohort 3 - Team P-192)  

---

## 📌 Phần 1: Thông tin cơ bản
- **Mã Team:** P-192 (T192)
- **Giai đoạn / Tuần:** Week 2 (Sprint 2: 03/08/2026 — 09/08/2026)
- **Người báo cáo:** Nguyễn Tuấn Thành (Team Lead / PM)
- **Ngày nộp báo cáo:** 04/08/2026 (Đang thực hiện Tuần 2)

---

## 📋 Phần 2: Tiến độ Chi tiết Tuần 2 (Sprint 2 — Core Development)

| # | Mã Task | Mục tiêu / Task | Phụ trách | Ưu tiên | Trạng thái | Ghi chú Tiến độ Đang Thực hiện |
|---|---------|-----------------|-----------|:-------:|:----------:|--------------------------------|
| 1 | **SCRUM-15** | Tích hợp PhoWhisper (ASR) & Piper (TTS) vào FastAPI server | Nhân | High | 🔄 **In Progress** | Đóng gói Faster-Whisper int8 & Piper TTS VN dạng async audio chunks trong `src/services/voice.py`. |
| 2 | **SCRUM-16** | Xây dựng Agent LangGraph + 5 Tools (AC, Music, Windows, Seat, Nav) | Nhân / Thành | High | 🔄 **In Progress** | Viết `CabinState` & StateGraph điều phối 5 Vehicle Control Tools trong `src/agents/graph.py`. |
| 3 | **SCRUM-17** | Xây dựng RAG FAISS cho sổ tay xe & Grounded Response | Nhân | High | 🔄 **In Progress** | Đã nạp sổ tay VF9 (58 mục → 482 chunk) vào FAISS + SQLite theo [ADR-003](../adr/ADR-003-local-rag-stack.md); grounded 100%, citation 100%, page_exact 100%. Còn tầng generation chờ ADR-005 chốt model. |
| 4 | **SCRUM-18** | Triển khai luồng HITL (xác nhận lệnh nguy hiểm) trong LangGraph | Nhân / Thành | High | 🔄 **In Progress** | Thiết lập trạng thái ngắt `PENDING_HITL` và Endpoint `/api/v1/hitl/confirm` phê duyệt lệnh nguy hiểm. |
| 5 | **SCRUM-19** | Xây dựng Virtual Vehicle API & MQTT Signal Broker | Thành Nguyễn | High | 🔄 **In Progress** | Khởi chạy MQTT Broker (Mosquitto :1883), publish/subscribe JSON vehicle state trên topic `vivi/vehicle/control`. |
| 6 | **SCRUM-20** | Dựng giao diện IVI Web App (Next.js 2D) kết nối ASR/TTS | Sơn Hà | High | 🔄 **In Progress** | Chuyển 8 bản Wireframe Figma thành UI Next.js 2D (Widgets Điều hòa, Nhạc, Waveform giọng nói). |
| 7 | **SCRUM-21** | Dựng Engineer Dashboard hiển thị Intent Acc, Grounded Rate & Logs | Giáp | Medium | 🔄 **In Progress** | Xây dựng giao diện Dashboard Kỹ sư hiển thị đồ thị thời gian thực theo dõi Latency, RAM & Logs. |
| 8 | **SCRUM-22** | Tối ưu hóa pipeline bước đầu để giảm Latency từ 5.6s hướng tới <3s | Cả Team | High | 🔄 **In Progress** | Đo lường độ trễ từng chặng (ASR, Intent, RAG, LLM, TTS) để giảm tổng Latency End-to-End < 3,000 ms. |

---

## 📈 Phần 3: Số liệu Vận hành & Tích hợp (Metrics Tuần 2)

| Chỉ số (Metric) | Giá trị | Ghi chú / Chi tiết |
|-----------------|---------|-------------------|
| **Khối lượng công việc (Sprint 2)** | **8 / 8 Tasks** | Đã phân công 4 Workstreams chạy song song không bị nghẽn (Block). |
| **Bugs còn mở (Open Bugs)** | **0** | Đang trong giai đoạn phát triển tích hợp modules. |
| **Repository Integration** | **100% Synced** | Đã gộp nhánh `docs` và `feature/offline-ai-poc` mượt mà vào nhánh trung tâm `develop`. |
| **Deployment Status** | **Local / Edge Gateway** | Môi trường test FastAPI Server (`:8000`), MQTT Broker (`:1883`) và Ollama SLM (`:8080`). |
| **File Quản trị & Jira Board** | **Yes** | Đã import 8 Tasks Sprint 2 lên Jira Board với hạn chót 09/08/2026. |

---

## ⚠️ Phần 4: Vướng mắc & Rủi ro Tuần 2

| Vướng mắc / Rủi ro | Mức độ | Khắc phục & Giải pháp Kỹ thuật |
|---------------------|:------:|--------------------------------|
| **1. Tối ưu Latency End-to-End từ 5.6s xuống < 3.0s** | **High** | **Giải pháp:** Rút ngắn Prompt System Qwen2.5-3B, dùng Faster-Whisper base int8 và streaming audio chunks từ Piper TTS. |
| **2. Tích hợp WebSockets giữa Next.js UI & FastAPI Backend** | **Medium** | **Giải pháp:** Sử dụng `WebSocketHub` tập trung quản lý kết nối 2 luồng `/ws/ivi` (Tài xế) và `/ws/dashboard` (Kỹ sư). |

---

## 📌 Phần 5: Kế hoạch Tuần tiếp theo (Sprint 3 — IVI Integration & HITL Safety)

1. **Hoàn thiện Tích hợp End-to-End (E2E Integration):** Kết nối Giọng nói IVI Screen ↔ FastAPI Backend ↔ LangGraph Agent ↔ MQTT Xe ảo.
2. **Kiểm thử Modal Popup HITL trên IVI UI:** Thử nghiệm thao tác bật Popup cảnh báo khi ra lệnh mở kính/cửa xe ở tốc độ > 5 km/h.
3. **Chạy Benchmark Đo lường Latency Sprint 2:** Đánh giá bảng phân rã độ trễ đạt mục tiêu < 3,000 ms.

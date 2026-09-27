# 📄 BMAD Product Requirements Document (PRD): VIVI Cabin Copilot

**Tác giả:** John (Product Manager)  
**Dự án:** VIVI Cabin Copilot — Trợ lý ảo đa phương thức trong xe hơi  
**Phiên bản:** 1.1 | **Ngày:** 2026-08-03 | **Trạng thái:** ✅ Đã cập nhật chi tiết từ PoC Benchmark  

---

## 1. Tổng quan & Cập nhật từ PoC

Bản PRD này định nghĩa toàn bộ yêu cầu chức năng, yêu cầu phi chức năng và tiêu chí nghiệm thu cho sản phẩm **VIVI Cabin Copilot MVP**.

**Cập nhật kết quả PoC (2026-07-29):**
- ✅ Mô hình LLM được lựa chọn: **Qwen2.5-3B** (GGUF q4_K_M) cho khả năng gọi Tool và hiểu tiếng Việt chính xác.
- ✅ Số liệu Latency PoC ban đầu: 5,609 ms (Mục tiêu tối ưu hóa MVP: **< 3,000 ms**).
- ✅ Mức chiếm dụng RAM thực tế: **~3.2 GB RAM** (Nằm trong giới hạn < 3.5 GB).

---

## 2. User Stories & Tiêu chí Nghiệm thu (Acceptance Criteria)

### 2.1. Phân hệ Tài xế (Driver Persona — Anh Minh)

| ID | User Story | Acceptance Criteria (Given-When-Then / Specs) |
|----|------------|-----------------------------------------------|
| **US1** | Là một tài xế, tôi muốn **đăng nhập vào màn hình IVI Screen** với vai trò Tài xế | - Trang login có tùy chọn chọn role "Tài xế"<br>- Đăng nhập thành công chuyển ngay đến giao diện màn hình IVI |
| **US2** | Là một tài xế, tôi muốn **nói "Bật điều hòa 24 độ"** để điều khiển xe rảnh tay | - ASR chuyển giọng nói thành text chuẩn xác<br>- Intent classifier nhận diện đúng `set_ac`<br>- Xe ảo cập nhật trạng thái điều hòa lên 24°C<br>- TTS phát câu thoại *"Đã bật điều hòa 24°C"* |
| **US3** | Là một tài xế, tôi muốn **hỏi "Áp suất lốp chuẩn là bao nhiêu?"** khi cần tra cứu | - RAG truy vấn đúng thông tin trong sổ tay xe<br>- Câu trả lời BẮT BUỘC có trích dẫn nguồn số trang (Ví dụ: *"Theo trang 42 sổ tay VIVI, áp suất lốp chuẩn là 2.2 bar"*) |
| **US4** | Là một tài xế, tôi muốn **VIVI bật Popup hỏi lại khi ra lệnh nguy hiểm** | - Hệ thống phát hiện lệnh nguy hiểm (Mở cửa khi xe đang di chuyển >5 km/h)<br>- Bật Modal Popup xác nhận trên IVI Screen<br>- Chỉ gửi tín hiệu mở cửa khi tài xế bấm `[Xác nhận]` |
| **US5** | Là một tài xế, tôi muốn **VIVI phản hồi "Tôi không hiểu"** khi câu lệnh không rõ | - Khi ASR confidence score thấp hoặc câu lệnh không khớp intent, AI không được đoán lụi hay bịa đặt mà phản hồi hướng dẫn ngắn gọn |

### 2.2. Phân hệ Kỹ sư Hệ thống (System Engineer Persona — Chị Lan)

| ID | User Story | Acceptance Criteria |
|----|------------|---------------------|
| **US6** | Là một kỹ sư, tôi muốn **đăng nhập vào Engineer Dashboard** để giám sát | - Trang login có tùy chọn chọn role "Kỹ sư"<br>- Chuyển đến màn hình Dashboard điều khiển hệ thống |
| **US7** | Là một kỹ sư, tôi muốn **xem chỉ số Intent Accuracy** thời gian thực | - Dashboard hiển thị đồ thị và con số % Intent Accuracy chính xác dựa trên lịch sử tương tác |
| **US8** | Là một kỹ sư, tôi muốn **xem chỉ số Grounded Rate & Hallucination Rate** | - Dashboard hiển thị % Grounded Rate (Target >90%) và so sánh với chỉ số mục tiêu |
| **US9** | Là một kỹ sư, tôi muốn **xem Audit Logs chi tiết** từng lượt gọi AI | - Bảng Log hiển thị đầy đủ: Timestamp, Query, Response, Intent, Tool calls, Latency (ms), RAG Citations |

---

## 3. Yêu cầu Chức năng Chi tiết (Functional Requirements)

### 3.1. Authentication Module
- **AUTH1:** Đăng nhập 2 vai trò riêng biệt (Tài xế -> Màn hình IVI; Kỹ sư -> Engineer Dashboard).
- **AUTH2:** Quản lý Session người dùng trong suốt phiên tương tác trên xe.

### 3.2. Voice & Audio Module
- **V1 (ASR):** Nhận diện giọng nói tiếng Việt bằng Faster-Whisper base int8 với WER < 20%.
- **V2 (TTS):** Tổng hợp giọng nói tiếng Việt bằng Piper TTS / VietTTS tự nhiên, không bị robotic.
- **V3 (Text Fallback):** Cho phép nhập liệu văn bản từ bàn phím màn hình IVI khi micro bị lỗi hoặc trong môi trường quá ồn.

### 3.3. Agent & Tool Calling Module
- **A1 (Intent Classification):** Phân loại ý định người dùng với độ chính xác > 85% (Kết hợp Rule-based Classifier và LLM Slot Extractor).
- **A2 (Tool Calling Execution):** Thực thi chính xác các tool gọi xe với độ chính xác > 85%.
- **A3 (Tool Registry - 7 Tools):**
  1. `control_ac(temp, fan_speed, mode)` — Điều hòa.
  2. `control_music(action, track, volume)` — Phát nhạc.
  3. `control_window(position, percentage)` — Cửa kính.
  4. `control_door(position, lock_status)` — Cửa xe.
  5. `control_seat(position, heating_level)` — Sưởi/chỉnh ghế.
  6. `navigation(destination, route_option)` — Bản đồ dẫn đường.
  7. `search_poi(category, radius)` — Tìm điểm đến gần đây.

### 3.4. RAG Knowledge Module
- **R1 (Manual Retrieval):** Truy vấn ngữ nghĩa trong tài liệu sổ tay xe VIVI (~20 trang) với ChromaDB.
- **R2 (Grounded Response):** Trả lời bắt buộc đính kèm trích dẫn số trang chính xác.
- **R3 (Reject Unknown):** Từ chối trả lời nếu không tìm thấy dữ liệu trong sổ tay (Similarity score dưới ngưỡng).

### 3.5. Safety & HITL Module
- **S1 (HITL Detection):** Nhận diện tự động các lệnh nhạy cảm/nguy hiểm (Mở cửa/kính xe khi tốc độ xe > 5 km/h).
- **S2 (HITL Popup):** Hiển thị Modal Popup xác nhận an toàn trên màn hình IVI.
- **S3 (HITL Timeout):** Tự động hủy lệnh nếu tài xế không tương tác trong vòng 5 giây.
- **S4 (Driving Mode Lock):** Tự động khóa các tính năng chạm phức tạp trên IVI khi xe chạy > 5 km/h, bắt buộc dùng giọng nói.

### 3.6. Virtual Vehicle & MQTT Module
- **VE1 (Virtual Vehicle API):** Mô phỏng trạng thái xe ảo dạng JSON (`ac`, `windows`, `doors`, `music`, `speed`).
- **VE2 (MQTT Publisher):** Agent publish lệnh điều khiển lên topic MQTT `vivi/vehicle/control`.
- **VE3 (MQTT Subscriber):** Xe ảo subscribe topic `vivi/vehicle/control` và publish trạng thái phản hồi lên `vivi/vehicle/status`.

### 3.7. Frontend & Backend Modules
- **F1 (IVI Screen):** Giao diện khung hình ô tô hỗ trợ Chat Voice Waveform, Car Control Widgets, HITL Modal Popup.
- **F2 (Engineer Dashboard):** Giao diện kỹ sư hiển thị Real-time Metrics (Latency breakdown, Intent Acc, Grounded Rate) & Audit Logs.
- **B1 (FastAPI Endpoints):** Các REST APIs (`/auth/login`, `/voice/transcribe`, `/agent/process`, `/vehicle/control`, `/admin/metrics`).
- **B2 (WebSocket Hub):** Push trạng thái realtime cho IVI Screen và Engineer Dashboard qua `/ws/ivi` & `/ws/dashboard`.

---

## 4. Yêu cầu Phi chức năng (Non-Functional Requirements)

| ID | Chỉ số (Requirement) | Giá trị Mục tiêu (Target) | Hiện trạng PoC / Nguồn |
|----|----------------------|---------------------------|------------------------|
| **N1** | End-to-End Latency | **< 3,000 ms** (Sau optimize) | PoC ban đầu: 5,609 ms |
| **N2** | Memory Usage | **< 3.5 GB RAM** | PoC thực tế: ~3.2 GB RAM |
| **N3** | Model Size | **~2.9 GB** | Qwen2.5-3B GGUF q4_K_M |
| **N4** | Intent Accuracy | **> 85%** | Bộ Dataset 200 câu test |
| **N5** | Grounded Rate | **> 90%** | Đánh giá qua RAGAS Benchmark |
| **N6** | Hallucination Rate | **< 10%** | Bộ test 50 câu bẫy không có dữ liệu |
| **N7** | Concurrent Users | 1 user (Môi trường cabin đơn) | Môi trường IVI ô tô |

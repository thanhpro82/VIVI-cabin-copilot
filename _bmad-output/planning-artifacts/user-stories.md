# 📖 BMAD User Stories: VIVI Cabin Copilot

**Tác giả:** John (Product Manager)  
**Dự án:** VIVI Cabin Copilot  
**Phiên bản:** 1.0 | **Ngày:** 2026-08-03  

---

## Epic 1: Điều khiển Tiện ích Xe bằng Giọng nói (Vehicle Voice Control)

### Story US-1.1: Điều chỉnh Điều hòa bằng Giọng nói
- **As a** Tài xế đang lái xe,
- **I want to** ra lệnh *"Bật điều hòa 22 độ và bật gió lớn"*,
- **So that** nhiệt độ cabin được hạ xuống mà tôi không cần rời mắt khỏi đường lái.
- **Acceptance Criteria (Given-When-Then):**
  - **Given:** Xe đang chạy hoặc dừng, hệ thống VIVI đang lắng nghe.
  - **When:** Tài xế nói *"Bật điều hòa 22 độ"*.
  - **Then:** Agent nhận diện đúng Intent `control_ac`, gọi tool `control_ac(temp=22)`, cập nhật giao diện IVI và phản hồi giọng nói *"Đã chỉnh điều hòa xuống 22 độ"*.

### Story US-1.2: Điều khiển Phát nhạc & Âm thanh
- **As a** Tài xế,
- **I want to** nói *"Phát nhạc thư giãn và tăng âm lượng"*,
- **So that** không gian xe thoải mái hơn.
- **Acceptance Criteria:**
  - **Given:** Hệ thống âm thanh đang tắt hoặc mở.
  - **When:** Tài xế nói *"Phát nhạc"*.
  - **Then:** Agent gọi tool `control_music(action="play")` và cập nhật widget nhạc trên IVI.

---

## Epic 2: Tra cứu Sổ tay Xe An toàn (Grounded RAG Manual Lookup)

### Story US-2.1: Tra cứu Đèn Cảnh báo sự cố
- **As a** Tài xế,
- **I want to** hỏi *"Đèn báo hình chiếc ấm màu đỏ trên màn hình nghĩa là gì?"*,
- **So that** tôi biết xe đang gặp sự cố gì và xử lý kịp thời.
- **Acceptance Criteria:**
  - **Given:** Cơ sở dữ liệu sổ tay xe VIVI đã nạp vào ChromaDB.
  - **When:** Tài xế hỏi về ý nghĩa đèn báo.
  - **Then:** Agent thực hiện RAG retrieval, trả lời *"Đó là đèn cảnh báo áp suất dầu động cơ thấp..."* và đính kèm trích dẫn `[Nguồn: Sổ tay VIVI - Trang 45]`.

### Story US-2.2: Từ chối Thông tin không có trong Sổ tay
- **As a** Tài xế,
- **I want** Agent không bịa thông tin khi tôi hỏi câu hỏi không thuộc phạm vi kỹ thuật xe,
- **So that** tôi không bị tiếp nhận thông tin sai lệch.
- **Acceptance Criteria:**
  - **Given:** Dữ liệu sổ tay không chứa thông tin được hỏi.
  - **When:** Tài xế hỏi một thông số không có thực.
  - **Then:** Agent phản hồi *"Xin lỗi, thông tin này không có trong sổ tay hướng dẫn sử dụng xe"*.

---

## Epic 3: Xác nhận An toàn Lệnh nhạy cảm (HITL Safety Gatekeeper)

### Story US-3.1: Xác nhận Hạ kính Xe ở Tốc độ cao
- **As a** Hệ thống An toàn xe,
- **I want** yêu cầu xác nhận HITL khi tài xế ra lệnh hạ kính ở tốc độ cao,
- **So that** tránh nguy cơ gió mạnh hoặc vật thể lạ bay vào xe gây nguy hiểm.
- **Acceptance Criteria:**
  - **Given:** Xe đang di chuyển trên 60 km/h.
  - **When:** Tài xế nói *"Mở cửa kính bên lái"*.
  - **Then:** Agent nhận diện lệnh có rủi ro, không mở kính ngay mà hiển thị Popup xác nhận trên IVI với 2 nút `[Đồng ý]` / `[Hủy bỏ]`.

---

## Epic 4: Giám sát Hiệu năng Kỹ sư (Engineer Diagnostics Dashboard)

### Story US-4.1: Giám sát Latency và Accuracy thời gian thực
- **As a** Kỹ sư Hệ thống,
- **I want to** xem Dashboard thống kê số liệu vận hành của Agent,
- **So that** tôi đánh giá được độ ổn định của hệ thống Edge AI.
- **Acceptance Criteria:**
  - **Given:** Kỹ sư đăng nhập vào giao diện Engineer View.
  - **When:** Có các lượt tương tác câu lệnh diễn ra.
  - **Then:** Dashboard hiển thị thời gian thực các chỉ số Latency (ms), Intent Accuracy (%), Grounded Rate (%), và RAM Consumption.

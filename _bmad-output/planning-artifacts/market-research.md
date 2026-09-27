# 📊 BMAD Market Research: VIVI Cabin Copilot

**Tác giả:** Mary (Business Analyst)  
**Dự án:** VIVI Cabin Copilot  
**Phiên bản:** 1.0 | **Ngày:** 2026-08-03  

---

## 1. Bối cảnh Thị trường & Xu hướng (Market Context)

Xu hướng phát triển ô tô thông minh (Smart Vehicles) trên thế giới và tại Việt Nam đang dịch chuyển mạnh mẽ từ trợ lý giọng nói đơn giản (nhận diện từ khóa cố định) sang **AI Agentic Cabin Assistants** có khả năng suy luận tự nhiên, hiểu ngữ cảnh và tự động thao tác đa bước.

---

## 2. Phân tích So sánh Lợi thế Cạnh tranh (Competitive Analysis)

| Tiêu chí | Google Assistant Auto | Apple CarPlay / Siri | VinFast Kiki Assistant | **VIVI Cabin Copilot (Our Project)** |
|----------|-----------------------|----------------------|------------------------|---------------------------------------|
| **Khả năng chạy Offline** | ❌ Phụ thuộc Cloud | ❌ Phụ thuộc iPhone/Cloud | ❌ Cần kết nối 4G/Cloud | ✅ **100% Offline Edge SLM** |
| **Tra cứu Sổ tay Xe (RAG)** | ❌ Tra cứu Web chung | ❌ Tra cứu Web chung | ⚠️ Tìm kiếm câu hỏi thường gặp | ✅ **Grounded RAG với trích dẫn số trang chính xác** |
| **Xác nhận An toàn (HITL)** | ❌ Thực thi trực tiếp | ❌ Thực thi trực tiếp | ❌ Thực thi trực tiếp | ✅ **Human-in-the-Loop Gatekeeper kiểm soát lệnh nhạy cảm** |
| **Khả năng điều khiển xe** | ⚠️ Hạn chế | ⚠️ Hạn chế theo iOS | ✅ Tốt trên xe VinFast | ✅ **LangGraph Multi-tool Agentic Execution (Mô phỏng CAN)** |
| **Độ trễ phản hồi (End-to-End)** | 2000ms - 5000ms (tùy mạng) | 1500ms - 4000ms | 2000ms - 4000ms | ⚡ **< 1500ms (Xử lý trực tiếp tại Edge)** |

---

## 3. Lợi thế Cạnh tranh Độc tôn (Unique Selling Proposition - USP)

1. **Safety-First & Grounded Output:** Đảm bảo câu trả lời tra cứu kỹ thuật xe tuyệt đối không bịa đặt (Hallucination-free), bảo vệ an toàn cho tài xế và tuổi thọ phương tiện.
2. **Offline-First Resilience:** Đảm bảo trợ lý ảo luôn hoạt động trong mọi điều kiện địa hình (hầm đường bộ, vùng núi cao, đèo dốc).
3. **Chuyên biệt tiếng Việt bản địa:** Hiểu mã ngôn ngữ tự nhiên (Vietnamese code-mixing), thói quen ra lệnh thoại rảnh tay của người Việt.

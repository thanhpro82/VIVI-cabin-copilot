# 📦 BMAD Product Brief: VIVI Cabin Copilot

**Tác giả:** Mary (Business Analyst)  
**Dự án:** VIVI Cabin Copilot — Trợ lý Giọng nói & Đa phương thức Trong Xe chạy trên Edge  
**Phiên bản:** 1.1 | **Ngày:** 2026-08-03 | **Trạng thái:** ✅ Đã cập nhật từ PoC Benchmark  

---

## 1. Tổng quan Dự án (Executive Summary)

**VIVI Cabin Copilot** là hệ thống trợ lý ảo AI thế hệ mới tích hợp giao diện giọng nói và cảm ứng đa phương thức (Voice & Touch IVI UI) chạy hoàn toàn **Offline-First** trên phần cứng Edge (Edge Gateway / cụm IVI ô tô). 

Hệ thống giải quyết 4 thách thức lớn nhất của ô tô thông minh hiện nay: phụ thuộc Cloud (mất kết nối trong hầm/vùng sóng yếu), phản hồi chậm gây mất tập trung khi lái, RAG bịa đặt thông tin kỹ thuật xe gây nguy hiểm, và trợ lý quá tốn RAM làm crash ứng dụng dẫn đường bản đồ.

---

## 2. Phân tích Bài toán & Thực trạng (Problem Statement)

Dựa trên khảo sát thực tế và kết quả đo lường PoC (2026-07-29), các hệ thống trợ lý xe hơi hiện nay vấp phải 4 vấn đề lớn:

| # | Vấn đề Thực tế | Số liệu / Hiện trạng từ PoC | Hậu quả đối với Vận hành Xe |
|---|----------------|-----------------------------|-----------------------------|
| 1 | **Mất mạng là "Câm"** | Xe vào hầm chui, bãi đỗ ngầm, đèo núi mất sóng 4G | Không thể sử dụng trợ lý để bật điều hòa, chỉnh sưởi ghế, mở nhạc hay xem hướng dẫn xe |
| 2 | **RAG Bịa thông tin nguy hiểm (Hallucination)** | AI thông thường bịa thông số lốp/dầu xe khi không có dữ liệu | Tài xế bơm sai áp suất lốp hoặc xử lý sai đèn báo sự cố, nguy cơ hư hỏng động cơ/tai nạn |
| 3 | **AI Gọi nhầm chức năng (Tool Mis-calling)** | Mô hình lượng tử hóa nhẹ dễ đoán sai Intent | Muốn mở nhạc thư giãn lại kích hoạt sưởi ghế hay mở cửa sổ |
| 4 | **Trợ lý tốn RAM, crash ứng dụng Nav** | Mô hình cồng kềnh ngốn > 6GB RAM | Trợ lý làm tràn bộ nhớ RAM của hệ thống IVI, làm ứng dụng bản đồ dẫn đường bị crash giữa đường |

---

## 3. Kết quả Đo lường Thực tế từ PoC (PoC Benchmarks)

Hệ thống đã trải qua nghiệm thu PoC thực tế trên mô hình Qwen2.5-3B (lượng tử hóa GGUF Q4_K_M):

| Tiêu chí | Kết quả PoC (Chưa Optimize) | Mục tiêu MVP (Sau Optimize) | Đánh giá & Giải pháp |
|----------|----------------------------|----------------------------|-----------------------|
| **Lựa chọn Mô hình** | Qwen2.5-3B vs 0.5B | **Qwen2.5-3B** | 3B cho độ chính xác tiếng Việt và Tool calling vượt trội |
| **Mức chiếm dụng RAM** | **~3.2 GB RAM** | **< 3.5 GB RAM** | ✅ Đạt ngưỡng an toàn, không gây crash ứng dụng Nav |
| **Dung lượng Mô hình** | **2.9 GB** | **< 3.0 GB** | ✅ Đóng gói gọn nhẹ trên ổ đĩa Edge |
| **Độ trễ End-to-End** | 5,609 ms | **< 3,000 ms** | 🔄 Cần tối ưu Pipeline ASR Faster-Whisper int8 & Caching |
| **Intent Accuracy** | ~82% | **> 85%** | Tăng cường Deterministic Rule Classification trước LLM |
| **Grounded Rate** | ~88% | **> 90%** | Áp dụng Relevance Grader với ngưỡng Similarity score |

---

## 4. Đối tượng Người dùng (Target User Personas)

### 4.1. Primary Persona: Tài xế (Anh Minh - 35 tuổi)
- **Đặc điểm:** Lái xe hàng ngày, cần tập trung hoàn toàn vào lộ trình lái xe, không rành công nghệ phức tạp.
- **Nỗi đau:** Mất tập trung khi cúi xuống bấm màn hình cảm ứng, xe mất mạng không dùng được giọng nói, sợ AI hướng dẫn sai thông số kỹ thuật xe.
- **Nhu cầu:** Ra lệnh tiếng Việt tự nhiên rảnh tay (Hands-free), điều chỉnh tiện ích xe tức thì, tra cứu chính xác ý nghĩa đèn báo táp-lô kèm số trang sổ tay xe.

### 4.2. Secondary Persona: Kỹ sư Hệ thống (Chị Lan - 28 tuổi)
- **Đặc điểm:** Chịu trách nhiệm kiểm thử, đánh giá chất lượng phần mềm IVI và độ an toàn của hệ thống AI trong xe.
- **Nỗi đau:** Mất thời gian test thủ công từng câu lệnh, không có biểu đồ đo lường chỉ số Latency/Accuracy thời gian thực.
- **Nhu cầu:** Giao diện Engineer Dashboard theo dõi đồ thị realtime, kiểm tra logs suy luận chi tiết của Agent, giả lập tín hiệu CAN Bus xe ảo.

---

## 5. 8 Nguyên tắc Thiết kế Kiến trúc (Architecture Principles)

1. **P1 - Offline-First:** 100% ASR, LLM, RAG, TTS chạy local tại Edge, ngắt mạng vẫn hoạt động 100%.
2. **P2 - Safety-First:** Lệnh nguy hiểm bắt buộc qua cổng xác nhận HITL (gate đặt tại Backend).
3. **P3 - Grounded-by-Default:** RAG có ngưỡng relevance; dưới ngưỡng bắt buộc từ chối trả lời, không cho LLM tự do bịa.
4. **P4 - Deterministic trước, LLM sau:** Intent classify bằng rule/embedding trước, LLM chỉ dùng extract slot -> giảm latency & tránh gọi sai tool.
5. **P5 - Measurable:** Mọi node trong LangGraph đều ghi timestamp, đo độ trễ chi tiết từng chặng.
6. **P6 - Simulation-only:** Mọi lệnh vật lý gửi qua Virtual Vehicle Service bằng giao thức MQTT.
7. **P7 - Single Agent, Multi-Node:** Kiến trúc 1 Agent LangGraph gồm nhiều Nodes chuyên biệt (tránh overhead của Multi-agent).
8. **P8 - Hands-Free khi xe chạy:** Tự động kích hoạt `Driving Mode` khi tốc độ xe > 5 km/h, khóa các thao tác cảm ứng phức tạp trên màn hình.

---

## 6. Phạm vi Sản phẩm MVP (Scope Breakdown)

### 6.1. In Scope (Hoàn thành trong MVP)
- ✅ **Web IVI App:** Đăng nhập 2 vai trò (Tài xế & Kỹ sư hệ thống).
- ✅ **Voice Module:** ASR Faster-Whisper base int8 + TTS Piper VN / VietTTS + Text Fallback.
- ✅ **Agentic Tools (7 tools):** Điều hòa (`AC`), Âm nhạc (`Music`), Cửa sổ (`Window`), Cửa xe (`Door`), Ghế ngồi (`Seat`), Dẫn đường (`Navigation`), Địa điểm (`POI`).
- ✅ **Grounded RAG:** Tra cứu sổ tay xe 20 trang với ChromaDB, trả lời kèm số trang trích dẫn chính xác.
- ✅ **Safety HITL:** Phát hiện lệnh nguy hiểm, tự động bật Popup xác nhận (Timeout 5s).
- ✅ **Virtual Vehicle API & MQTT:** Giả lập xe ảo qua MQTT broker (Mosquitto/EMQX) trên topic `vivi/vehicle/control` & `vivi/vehicle/status`.
- ✅ **Engineer Dashboard:** Biểu đồ đo Intent Accuracy, Grounded Rate, Audit Logs và Latency breakdown.

### 6.2. Out of Scope (Không làm trong MVP)
- ❌ Kết nối phần cứng ô tô thật / CAN Bus vật lý.
- ❌ Cập nhật phần mềm qua mạng OTA đa xe.
- ❌ Đa đại lý Multi-agent phức tạp.

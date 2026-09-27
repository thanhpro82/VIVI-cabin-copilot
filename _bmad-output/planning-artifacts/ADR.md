# ⚖️ BMAD Architecture Decision Records (ADRs): VIVI Cabin Copilot

**Tác giả:** Winston (System Architect)  
**Dự án:** VIVI Cabin Copilot — Trợ lý ảo đa phương thức trong xe hơi  
**Phiên bản:** 1.1 | **Ngày:** 2026-08-03 | **Trạng thái:** ✅ Đã thông qua  

---

## ADR-01: Lựa chọn Mô hình Ngôn ngữ SLM Edge Offline (Qwen2.5-3B)

- **Trạng thái:** Đã phê duyệt (Approved - Tested in PoC)
- **Bối cảnh:** Xe ô tô cần hoạt động 100% offline khi di chuyển vào hầm đường bộ, bãi đỗ ngầm hoặc khu vực mất sóng 4G/5G. Cụm IVI có giới hạn bộ nhớ RAM.
- **Quyết định:** Sử dụng **Qwen2.5-3B-Instruct (GGUF q4_K_M)** chạy thông qua llama.cpp / Ollama local server.
- **Kết quả PoC:**
  - Qwen2.5-3B cho khả năng trích xuất thông số (Slot Extraction) và gọi Tool chính xác hơn nhiều so với bản 0.5B.
  - Sau lượng tử hóa Q4_K_M, mô hình chiếm **~3.2 GB RAM**, nằm trong ngưỡng giới hạn an toàn (<3.5 GB RAM).

---

## ADR-02: Lựa chọn Framework Điều phối Agent (LangGraph Single Agent, Multi-Node)

- **Trạng thái:** Đã phê duyệt (Approved)
- **Bối cảnh:** Agent cần xử lý luồng suy luận phức tạp: phân loại ý định, gọi tool điều khiển xe, tra cứu RAG, và cổng an toàn HITL.
- **Quyết định:** Sử dụng **LangGraph** thiết lập 1 Agent duy nhất gồm nhiều Nodes chuyên biệt (StateGraph), không áp dụng mô hình Multi-Agent độc lập.
- **Lý do:**
  - Tránh được độ trễ overhead phát sinh do giao tiếp giữa nhiều Agents (Multi-agent giao tiếp làm tăng latency >5s).
  - Quản lý trạng thái tập trung (Stateful Checkpointer), dễ dàng tạm dừng (interrupt) tại node HITL để chờ xác nhận từ tài xế.

---

## ADR-03: Giải pháp Engine Giọng nói ASR Local (Faster-Whisper int8)

- **Trạng thái:** Đã phê duyệt (Approved)
- **Bối cảnh:** Cần nhận diện giọng nói tiếng Việt rảnh tay với độ trễ thấp và tỷ lệ lỗi từ (WER) dưới 20%.
- **Quyết định:** Sử dụng **Faster-Whisper (model base, int8 quantization)** chạy local.
- **Lý do:**
  - Tốc độ xử lý ASR giảm xuống chỉ còn **~400 ms** cho mỗi câu thoại ngắn 3-5 giây.
  - Tích hợp Voice Activity Detection (VAD) để tự động ngắt câu thoại khi tài xế dứt lời.

---

## ADR-04: Giải pháp Engine Tổng hợp Giọng nói TTS Local (Piper TTS VN)

- **Trạng thái:** Đã phê duyệt (Approved)
- **Bối cảnh:** Cần đọc phản hồi câu thoại tiếng Việt tự nhiên, không bị robotic với độ trễ phản hồi cực thấp.
- **Quyết định:** Sử dụng **Piper TTS (Giọng tiếng Việt)** chạy local.
- **Lý do:**
  - Thời gian khởi tạo và phát âm thanh rất nhanh (**~350 ms**).
  - Xuất dữ liệu âm thanh dạng Audio Chunks hỗ trợ streaming về Frontend IVI Screen.

---

## ADR-05: Giải pháp Vector Store & Relevance Grader (ChromaDB Local)

- **Trạng thái:** Đã phê duyệt (Approved)
- **Bối cảnh:** Tra cứu sổ tay xe chính hãng (~20-500 trang), bắt buộc có trích dẫn số trang và tuyệt đối không cho phép LLM bịa thông tin.
- **Quyết định:** Sử dụng **ChromaDB Embedded Storage** kết hợp với **Relevance Grader Node**.
- **Lý do:**
  - ChromaDB chạy embedded local không cần Server riêng.
  - Relevance Grader kiểm tra ngưỡng Similarity Score (ngưỡng 0.75). Nếu dưới ngưỡng, hệ thống tự động trả lời *"Tôi không tìm thấy thông tin trong sổ tay"* chứ không chuyển cho LLM sinh lụi.

---

## ADR-06: Tích hợp Xe ảo qua Giao thức MQTT Broker (Mosquitto/EMQX)

- **Trạng thái:** Đã phê duyệt (Approved)
- **Bối cảnh:** Hệ thống cần mô phỏng việc truyền nhận tín hiệu xe (CAN Bus) bất đồng bộ với Backend.
- **Quyết định:** Sử dụng **MQTT Broker (Mosquitto/EMQX)** làm xe ảo trung gian qua các topic `vivi/vehicle/control` & `vivi/vehicle/status`.
- **Lý do:**
  - Kiến trúc Pub/Sub bất đồng bộ giúp giải phóng thread Backend, tránh nghẽn I/O khi xe ảo phản hồi trạng thái.
  - Đúng tinh thần thiết kế giả lập của BTC AI20K (Simulation-only).

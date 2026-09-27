# 📊 BÁO CÁO TIẾN ĐỘ TUẦN 1 (WEEK 1 PROGRESS REPORT)
**Dự án:** VIVI Cabin Copilot — VinUni AI20K Build Phase (Cohort 3 - Team P-192)  

---

## 📌 Phần 1: Thông tin cơ bản
- **Mã Team:** P-192 (T192)
- **Giai đoạn / Tuần:** Week 1 (Sprint 1: 30/07/2026 — 02/08/2026)
- **Người báo cáo:** Nguyễn Tuấn Thành (Team Lead / PM)
- **Ngày nộp báo cáo:** 02/08/2026

---

## 📋 Phần 2: Tiến độ Chi tiết Sprint 1

| # | Mã Task | Mục tiêu / Task | Phụ trách | Trạng thái | Ghi chú Kết quả Thực hiện |
|---|---------|-----------------|-----------|------------|---------------------------|
| 1 | **SCRUM-10** | Hoàn thiện Brief và Product Requirement Document (PRD v1.1) | Thành Nguyễn | ✅ **Done** | Chốt 4 Nỗi đau cabin, Yêu cầu FR1-FR5, NFR1-NFR7 và Success Metrics. |
| 2 | **SCRUM-11** | Thiết lập Jira Board, Workflow & Automation | Thành Nguyễn | ✅ **Done** | Cấu hình Jira Scrum Board, 13 Custom Fields, 4 Sprints & Automation Rules. |
| 3 | **SCRUM-13** | Thiết kế Kiến trúc Hệ thống (Architecture Design) | Sơn Hà / Winston | ✅ **Done** | Hoàn thiện Kiến trúc 8 Lớp, 3 Sequence Diagrams & OpenAPI Specification (`VIVI_API_Spec.md`). |
| 4 | **SCRUM-9** | Thực hiện PoC AI Offline Pipeline & Benchmark | Nhân | ✅ **Done** | Benchmark Qwen2.5-3B q4 vs 0.5B; RAM ~3.2GB, đo Latency (5.6s) kèm log chứng minh `.wav`. |
| 5 | **SCRUM-8** | Thiết kế Wireframe IVI Screen (Figma UI) | Sơn Hà / Sally | ✅ **Done** | Hoàn thành 8 bản vẽ Wireframe Figma chính (Home, Voice Waveform, AC, Music, Seat, Nav, HITL Popup). |
| 6 | **SCRUM-12** | Nghiên cứu Giao diện Xe 3D (WebGL / Three.js) | Giáp | ✅ **Done** | Đánh giá hiệu năng: Đề xuất **bỏ Xe 3D** để tránh ngốn GPU/RAM và giảm tối đa Latency. |
| 7 | **SCRUM-14** | Sprint Review & Technical Decisions (ADRs) | Cả Team | ✅ **Done** | Chốt 6 ADRs (Qwen2.5-3B, LangGraph, Faster-Whisper, Piper, ChromaDB, MQTT Broker, 2D UI). |

---

## 📈 Phần 3: Số liệu Vận hành & Nghiệm thu (Metrics)

| Chỉ số (Metric) | Giá trị | Ghi chú / Chi tiết |
|-----------------|---------|-------------------|
| **Tasks hoàn thành (Completion Rate)** | **7 / 7 (100%)** | Đã nghiệm thu toàn bộ 7 tasks nền tảng của Week 1. |
| **Bugs còn mở (Open Bugs)** | **0** | Chưa ghi nhận bug (Giai đoạn Thiết kế & PoC). |
| **Stakeholder Meetings** | **2** | 1 họp Review với Mentor VinUni + 1 họp Sync kỹ thuật nội bộ team. |
| **Deployment Status** | **Local / Simulated Edge** | Benchmark PoC Offline thành công trên Qwen2.5-3B q4 & Faster-Whisper int8. |
| **File Quản trị & Repository** | **Updated** | Đã sync 100% tài liệu BMAD, Architecture, Jira CSV & Worklog lên nhánh `develop`. |

---

## ⚠️ Phần 4: Vướng mắc, Rủi ro & Quyết định Kỹ thuật

| Vướng mắc / Rủi ro | Mức độ | Khắc phục & Quyết định Kỹ thuật (Technical Decision) |
|---------------------|:------:|------------------------------------------------------|
| **1. Latency PoC ban đầu còn cao (5.6s)** so với mục tiêu **< 3.0s** của BTC | **High** | **Giải pháp:** Trong Sprint 2, dồn lực tối ưu Faster-Whisper int8 ASR, giảm độ dài Prompt Qwen3B và streaming audio chunks từ Piper TTS. |
| **2. Rủi ro Scope Creep do Giao diện Xe 3D** gây giật lag trình duyệt | **Medium** | **Chốt ADR-06:** Loại bỏ giao diện Xe 3D rườm rà. Chốt làm **Next.js 2D UI (Dark Mode)** để tiết kiệm RAM/GPU và dành 100% tài nguyên tối ưu Latency. |
| **3. Nguy cơ AI gọi nhầm lệnh nguy hiểm** khi xe chạy tốc độ cao | **High** | **Chốt ADR-02:** Thiết lập Cổng kiểm soát an toàn **HITL Safety Gatekeeper** trên Backend, bắt buộc bật Modal Popup xác nhận trên IVI Screen. |

---

## 📌 Phần 5: Kế hoạch Tuần sau (Sprint 2 — Core Development & Integration)

**Mục tiêu Sprint 2 (03/08 — 09/08/2026):** Phát triển bộ mã nguồn cốt lõi trong `src/` (FastAPI ↔ LangGraph Agent ↔ Grounded RAG ↔ Local ASR/TTS ↔ MQTT Xe ảo).

| # | Mã Task | Nhiệm vụ (Task Description) | Phụ trách (Assignee) | Độ ưu tiên | Hạn chót |
|---|---------|-----------------------------|----------------------|:----------:|:--------:|
| 1 | **SCRUM-15** | Tích hợp PhoWhisper (ASR) & Piper (TTS) vào FastAPI server | Nhân | High | 09/08/2026 |
| 2 | **SCRUM-16** | Xây dựng Agent LangGraph + 5 Tools (AC, Music, Windows, Seat, Nav) | Nhân | High | 09/08/2026 |
| 3 | **SCRUM-17** | Xây dựng RAG ChromaDB cho sổ tay xe & Grounded Response | Nhân | High | 09/08/2026 |
| 4 | **SCRUM-18** | Triển khai luồng HITL (xác nhận lệnh nguy hiểm) trong LangGraph | Nhân | High | 09/08/2026 |
| 5 | **SCRUM-19** | Xây dựng Virtual Vehicle API & MQTT Signal Broker | Thành Nguyễn | High | 09/08/2026 |
| 6 | **SCRUM-20** | Dựng giao diện IVI Web App (Next.js 2D) kết nối ASR/TTS | Sơn Hà | High | 09/08/2026 |
| 7 | **SCRUM-21** | Dựng Engineer Dashboard hiển thị Intent Acc, Grounded Rate & Logs | Giáp | Medium | 09/08/2026 |
| 8 | **SCRUM-22** | Tối ưu hóa pipeline bước đầu để giảm Latency từ 5.6s hướng tới <3s | Cả Team | High | 09/08/2026 |

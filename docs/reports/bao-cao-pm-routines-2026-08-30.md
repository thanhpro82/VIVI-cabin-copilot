# Báo cáo PM — Routines MVP: đã làm & còn tồn đọng

**Ngày soạn:** 2026-08-30 · **Người soạn:** Đặng Giáp · **Nguồn:** phát hiện lúc test #294

## Đã làm

| Việc | Trạng thái |
|---|---|
| #370, #292, #298 — real.ts, panel tiến độ, nút Dừng | ✅ Merge vào develop |
| #364 — auto-listen sau clarify | ✅ Đóng (cơ chế đã có sẵn qua PR #387, chỉ thiếu bằng chứng đo) |
| Routine có bước dẫn đường không tự chuyển màn Bản đồ | 🔵 PR #395 — chờ review |
| #396 — Routine chạy xong không nói kết quả | 🔵 PR #398 — chờ review |
| #294 — spike đo barge-in | 🟡 Đang đo (hạ tầng xong, chưa đủ số liệu kết luận) |

## Còn tồn đọng — cần PM quyết

**1. Routine chưa chạy được bằng giọng nói (#285, cha #274 — đã giao Nhân)**
`routines_intent.py` mới nhận diện câu nói, chưa nối vào router để thực thi. Đo được: nói "Chạy routine X" không có tác dụng, rơi về tra sổ tay.
→ *Hỏi PM:* ưu tiên việc này ở đâu trong lộ trình? Nhân có đang làm chưa?

**2. #277 (Go/No-Go barge-in) đo trên cái gì?**
#294 đang đo tạm bằng TTS của lệnh điều khiển thường, vì Routine trước đây chưa nói được (mục #396 vừa sửa). Sau khi PR #398 merge, Routine đã có TTS riêng — nhưng **chưa có bảo vệ self-echo nào cho tiếng nói đó** (cố ý bỏ qua trong #398, ghi rõ trong code).
→ *Hỏi PM:* chấp nhận kết quả đo trên lệnh thường làm bằng chứng chung cho #277, hay chờ đo lại đúng trên Routine sau khi #398 merge?

**3. #276 (Tiến độ & báo cáo) chưa đủ điều kiện đóng**
Dù #396 xong, #276 còn 5/7 tiêu chí chưa xác minh trên app thật (reconnect/replay không nhân đôi, TTS lỗi không mất kết quả text, v.v.) — chỉ mới xong phần code, chưa qua UAT.
→ *Hỏi PM:* ai chạy UAT cho #276, khi nào?

**4. #296 (Agent spike đo nhận diện câu Dừng/Hủy) chưa ai nhận**
Không có branch, không assignee. #277 cần cả #294 lẫn #296 xong mới chốt được.
→ *Hỏi PM:* giao ai?

## Đề xuất

Ưu tiên theo thứ tự: **#285 (mở khoá voice-first thật sự cho Routine) → merge #395/#398 → #296 có người nhận → đo lại #277 trên Routine thật → #276 chạy UAT → #277/#280 chốt Go/No-Go.**

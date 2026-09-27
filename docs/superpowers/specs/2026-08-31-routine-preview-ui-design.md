# Routine preview có cấu trúc và điều hướng UI

**Ngày:** 2026-08-31  
**Phạm vi:** PR #401, issue #274/#285  
**Quyết định PM/PO:** Voice nói ngắn; UI mở màn Routines, cuộn tới và highlight đúng Routine.

## Vấn đề

PR #401 đã nối được luồng đa lượt `xem trước → đồng ý/từ chối`, nhưng kết quả
`routine_preview` chỉ giữ `routine_id` trong AgentState. Câu trả lời nói *“Đây là các
bước của Routine này”* trong khi REST/WS không gửi tên hay bước cho frontend, và frontend
không mở đúng Routine. Người lái vì thế được yêu cầu xác nhận một preview chưa thực sự
được nhìn hoặc nghe.

## Mục tiêu

Khi người dùng nói hoặc gõ `Xem trước Routine <tên>`:

1. Agent trả một preview có cấu trúc từ đúng Routine vừa phân giải.
2. Cả REST và WebSocket mang cùng cấu trúc đó.
3. Frontend mở màn `routines`, cuộn tới và highlight card tương ứng.
4. Card hiển thị đúng tên và danh sách bước; voice chỉ nói câu xác nhận ngắn.
5. REST và WS cùng tới cho một turn không gây điều hướng/highlight hai lần.

## Contract

Thêm kiểu nullable `RoutinePreviewData`:

```text
routine_id: string
routine_name: string
steps: [{ index: integer >= 0, action: string, description: string }]
```

Trường `routine_preview` xuất hiện ở hai channel của cùng turn:

- `TextTurnData.routine_preview` trong response `POST /api/v1/turns/text`;
- payload `assistant.response.routine_preview` trên WebSocket.

Ở mọi outcome khác, trường là `null` hoặc vắng trên WS theo quy ước optional hiện có.
Backend là nguồn sự thật duy nhất: frontend không dựng preview bằng cách phân tích câu
tiếng Việt và không tự suy diễn mô tả bước.

## Agent và backend

`routine_node` đã có object Routine sau khi phân giải tên. Ở nhánh `xem_truoc`, node dựng
`routine_preview` từ object đó, đồng thời tiếp tục nạp khe xác nhận 30 giây như hiện tại.
Mỗi bước dùng đúng thứ tự lưu; `description` tái dùng phép mô tả bước thuộc backend thay
vì để FE/Agent tạo hai bản copy khác nhau.

Compose đổi câu thành:

> Đây là các bước của Routine {tên}. Bạn có muốn tôi chạy không?

Preview vẫn zero side effect và không tạo `routine_execution`.

API model khai contract đóng cho REST. Tầng phát lifecycle chuyển cùng payload sang
`assistant.response`; không tạo event `routine.preview` riêng để tránh hai contract khác
nhau cho voice và text.

## Frontend

`TurnResult` và event `assistant.response` nhận `routinePreview` nullable. Cả đường REST
và WS gọi một helper chung trong `DriverShellProvider`:

- dedupe bằng `turnId`;
- lưu preview hiện hành `{turnId, routineId, routineName, steps}`;
- đặt `activeView = "routines"`.

`RoutinesView` nhận preview từ context, đợi danh sách load, rồi:

- cuộn card khớp `routineId` vào giữa viewport;
- highlight card trong 30 giây, khớp TTL xác nhận của Agent;
- không mở form sửa và không tự chạy Routine.

Nếu danh sách hiện tại không có ID đó (cache/mock lệch), UI dùng payload có cấu trúc để
render một card read-only được highlight ở đầu danh sách. Nó không được im lặng nói rằng
đang hiển thị bước trong khi không có card nào.

## Dedupe và thứ tự

Một lượt text có thể vừa trả REST response vừa phát WebSocket event. `turnId` là khóa
dedupe; lần đầu áp dụng preview, lần sau bỏ qua. Preview mới thay preview cũ. Timer cũ
phải được hủy khi preview mới tới hoặc provider unmount.

Event replay của turn cũ không được kéo UI khỏi công việc hiện tại nếu `turnId` đã xử lý.

## Lỗi và fallback

- Preview thiếu `routine_id`, tên hoặc steps hợp lệ: không điều hướng UI; câu trả lời text/
  voice vẫn hiển thị và ghi log contract error.
- Không cuộn được vì DOM chưa render: thử sau khi danh sách load/render, không polling vô hạn.
- FE lỗi render preview không được làm thay đổi khe xác nhận hoặc thực thi Routine ở backend.

## Kiểm thử

Backend/Agent:

- preview trả đúng ID, tên và các bước theo thứ tự;
- run/cancel/non-Routine trả `routine_preview = null`;
- REST text response và WS `assistant.response` mang cùng payload;
- preview vẫn zero side effect.

Frontend:

- mapper REST/WS giữ đúng payload;
- voice và text đều mở `routines` và chọn đúng card;
- REST + WS cùng `turnId` chỉ áp dụng một lần;
- card được cuộn/highlight, hết highlight sau 30 giây;
- ID không có trong list vẫn hiện card read-only từ payload;
- payload malformed không điều hướng và không crash.

## Ngoài phạm vi

- Đọc toàn bộ bước bằng TTS.
- `bo_buoc`/run override.
- Màn chi tiết Routine mới.
- Thay đổi admission, safety, cancellation hoặc TTL xác nhận hiện tại.

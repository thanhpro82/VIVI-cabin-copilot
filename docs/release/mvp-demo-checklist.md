# MVP Demo — UAT Checklist

Kịch bản UAT chạy tay cho 5 luồng bắt buộc trong `docs/demo_scope.md`. Mỗi
kịch bản có bước bấm được, **kết quả người dùng nhìn thấy** (không phải log,
không phải test xanh), và ô Pass/Fail để tester điền.

Phạm vi bám đúng `demo_scope.md`: đèn và cốp của PR #92 **không** nằm trong
checklist này vì đã deferred; quạt gió thì có.

## Cách dùng

- Tester điền trực tiếp vào file, một cột `Kết quả` cho mỗi kịch bản.
- **Fail thì phải mở một mục trong `docs/release/uat-bug-triage.md`** và ghi ID
  vào cột `Bug ID`. Fail mà không có bug ID là chưa xử lý xong.
- Cột `Kết quả người dùng thấy` là tiêu chí đạt duy nhất. Nếu backend làm đúng
  mà màn hình không đổi thì đó là **Fail**, không phải "đạt một phần".
- Không sửa kịch bản giữa buổi test để cho nó pass.

| Vòng UAT | Ngày | Tester | Build (commit) |
|---|---|---|---|
| | | | |

## Preflight — chạy trước, không tính là kịch bản

Fail bất kỳ dòng nào ở đây thì dừng, không chạy tiếp UAT.

| ID | Việc | Lệnh / thao tác | Đạt khi | Kết quả |
|---|---|---|---|---|
| PRE-1 | Broker + simulator | `docker compose up -d --wait mqtt vehicle-simulator` | Cả hai container healthy | ☐ Pass ☐ Fail |
| PRE-2 | Backend | `.\.venv\Scripts\python.exe -m src.serve` | `GET /healthz` trả `status: ready` | ☐ Pass ☐ Fail |
| PRE-3 | FE ở chế độ thật | 3 cờ `NEXT_PUBLIC_USE_MOCK_TURN` / `_SESSION` / `_ENGINEER` đều `false`, rồi `npm run dev` | Không còn dữ liệu mock nào trên màn hình | ☐ Pass ☐ Fail |
| PRE-4 | Đăng nhập driver | `/login` với `driver.demo@example.com` / `DemoDriver123!` | Vào được `/driver`, WebSocket `/ws/ivi` nối | ☐ Pass ☐ Fail |
| PRE-5 | Trạng thái xe ban đầu | Xem StatusBar | `speed_kph = 0`, `gear = P` | ☐ Pass ☐ Fail |
| PRE-6 | Mic | Trình duyệt hỏi quyền micro | Đã cấp quyền | ☐ Pass ☐ Fail |
| PRE-7 | **Cấu hình xe** | Mở `/engineer`, bấm chip danh tính xe, chọn đúng `trim` × `battery` của kịch bản demo (mặc định đang dùng: **PLUS · CATL**) | Chip đổi từ amber sang `VF9 · PLUS · CATL`; `GET /vehicle/profile` trả `is_complete: true` | ☐ Pass ☐ Fail |

> PRE-3 là bước hay bị bỏ nhất và là bước làm hỏng cả buổi UAT: để nguyên mock
> thì mọi kịch bản dưới đây đều "pass" mà không chứng minh gì về backend.

> PRE-7 mới thêm (#168). Chưa khai báo thì R-5 dưới đây **fail-closed đúng thiết kế** —
> trợ lý chỉ sang cái nhãn ở khung cửa thay vì đọc số. Đó không phải bug, nhưng nó làm
> hỏng kịch bản demo, nên phải chốt cấu hình **trước** khi chạy. Con số khác nhau thật
> theo phiên bản (240–280 kPa), nên khai sai là đọc cho tài xế số của một chiếc xe khác.

## 1. Voice S1 — lệnh không cần phê duyệt

| ID | Kịch bản | Kết quả người dùng thấy | Kết quả | Bug ID |
|---|---|---|---|---|
| S1-1 | Xe dừng. Mở overlay mic, nói “Bật điều hòa 24 độ”. | Transcript hiện đúng câu vừa nói; trợ lý trả lời xác nhận bằng chữ **và** phát tiếng qua loa; thẻ điều hòa trên màn hình đổi sang bật, nhiệt độ 24. Không có hộp phê duyệt nào. | ☐ Pass ☐ Fail | |
| S1-2 | Nói “Chỉnh quạt gió mức 2”. | Dải 4 mức quạt trên `VehicleControlView` sáng đúng 2 mức. Không có hộp phê duyệt. | ☐ Pass ☐ Fail | |
| S1-3 | Nói “Bật điều hòa 22 độ và quạt gió mức 2”. | Cả nhiệt độ **và** mức quạt đều đổi đúng — không phải chỉ một trong hai, và không báo lỗi ngoài dải. | ☐ Pass ☐ Fail | |
| S1-4 | Nói “Đặt nhiệt độ 45 độ”. | Trợ lý nói rõ là ngoài dải cho phép và **không** đổi nhiệt độ. Thẻ điều hòa giữ nguyên giá trị cũ. | ☐ Pass ☐ Fail | |
| S1-5 | Nói “Bật đèn” (trống, không nói đèn nào). | Trợ lý hỏi lại xem là đèn nào. Không tự đoán và không thực thi gì. | ☐ Pass ☐ Fail | |

## 2. S2 / HITL — lệnh cần phê duyệt

| ID | Kịch bản | Kết quả người dùng thấy | Kết quả | Bug ID |
|---|---|---|---|---|
| S2-1 | Xe dừng, gear P. Nói “Mở kính bên lái 30%”. Bấm **Đồng ý**. | Hộp phê duyệt hiện ra kèm mô tả đúng việc sắp làm và đồng hồ đếm ngược. Sau khi bấm Đồng ý: hộp đóng, kính bên lái hiển thị 30%, trợ lý xác nhận đã làm. Kính đổi **đúng một lần**. | ☐ Pass ☐ Fail | |
| S2-2 | Lặp lại S2-1 nhưng bấm **Từ chối**. | Hộp đóng, kính **không** đổi, trợ lý xác nhận đã hủy. | ☐ Pass ☐ Fail | |
| S2-3 | Lặp lại S2-1, không bấm gì, đợi đồng hồ về 0. | Hộp tự đóng khi hết giờ, kính **không** đổi. Bấm Đồng ý sau đó (nếu còn bấm được) cũng không làm gì. | ☐ Pass ☐ Fail | |
| S2-4 | Trong lúc hộp phê duyệt đang mở, bấm ra vùng ngoài / đóng hộp. | Đóng hộp **không** được tính là đồng ý — kính không đổi. | ☐ Pass ☐ Fail | |
| S2-5 | Cho xe chạy (`speed_kph > 0`), nói “Mở cửa bên lái”. | Trợ lý từ chối vì xe đang chạy. **Không** có hộp phê duyệt nào hiện ra — bị chặn trước HITL, không phải hỏi rồi mới chặn. | ☐ Pass ☐ Fail | |
| S2-6 | Bấm Đồng ý hai lần thật nhanh trên cùng một hộp. | Lệnh chỉ chạy một lần; state không nhảy hai bậc. | ☐ Pass ☐ Fail | |

## 3. RAG + TTS — tra sổ tay và đọc thành tiếng

| ID | Kịch bản | Kết quả người dùng thấy | Kết quả | Bug ID |
|---|---|---|---|---|
| R-1 | Hỏi một câu có trong sổ tay VF9, ví dụ “Chế độ Camp Mode dùng thế nào?”. | Câu trả lời hiện ra kèm **trích dẫn nguồn** (tên mục / số trang). Nội dung là trích nguyên văn sổ tay, không phải văn tự chế. Loa đọc câu trả lời. | ☐ Pass ☐ Fail | |
| R-2 | Hỏi một câu chắc chắn không có trong sổ tay, ví dụ “Xe này thay lốp hãng nào tốt nhất?”. | Trợ lý nói rõ **không tìm thấy trong sổ tay**. Không bịa câu trả lời, không trích dẫn giả. | ☐ Pass ☐ Fail | |
| R-3 | Sau khi trả lời xong, đọc kỹ phần trích dẫn của R-1. | Trích dẫn trỏ đúng mục đang nói tới; nếu nội dung có điều kiện phiên bản (ECO/PLUS, SDI/CATL) thì điều kiện đó **còn nguyên** trong câu trả lời, không bị cắt mất. | ☐ Pass ☐ Fail | |
| R-4 | Chạy R-1 ngay sau khi tải trang, **trước** khi chạm vào màn hình lần nào. | Nếu trình duyệt chặn tự phát tiếng thì phần chữ vẫn phải hiện đầy đủ và bình thường. Mất tiếng ở lượt đầu là hạn chế đã biết của trình duyệt; **mất chữ thì là Fail**. | ☐ Pass ☐ Fail | |
| R-5 | Hỏi “Áp suất lốp tiêu chuẩn là bao nhiêu?”. | Trợ lý đọc **số thật cho cả hai trục** (với PLUS · CATL: trước 260 kPa, sau 270 kPa) kèm điều kiện “đo khi lốp nguội”. Nghe thấy một đường dẫn kiểu “Xem > Vành và bánh xe > …” là **Fail** — đó là bug đã sửa ở #168. | ☐ Pass ☐ Fail | |
| R-6 | Vào `/engineer`, **xoá** cấu hình xe, rồi hỏi lại câu R-5. | Trợ lý **không** đọc số nào; nó chỉ sang nhãn ở khung cửa. Đọc ra một con số khi chưa biết phiên bản xe là **Fail** — đó là fail-closed của #122. Nhớ khai báo lại trước khi chạy tiếp. | ☐ Pass ☐ Fail | |

## 4. WebSocket recovery — mất kết nối và nối lại

| ID | Kịch bản | Kết quả người dùng thấy | Kết quả | Bug ID |
|---|---|---|---|---|
| W-1 | Đang ở màn hình driver với UI mở bình thường, tắt backend (hoặc ngắt mạng tab). | UI **khóa ngay** — các nút điều khiển chuyển sang trạng thái không bấm được. Không có độ trễ kiểu vẫn bấm được vài giây. | ☐ Pass ☐ Fail | |
| W-2 | Bật backend lại, đợi client tự nối lại. | UI tự mở khóa trở lại, và chỉ mở sau khi nhận chính sách mới từ server — không phải tự mở vì đã nối lại. | ☐ Pass ☐ Fail | |
| W-3 | Trong lúc mất kết nối, thử bấm một nút điều khiển. | Không gửi lệnh nào đi, và không có lệnh nào chạy dồn khi nối lại. | ☐ Pass ☐ Fail | |
| W-4 | Chạy một lượt lệnh, ngắt socket giữa lượt, rồi nối lại. | Sau khi nối lại, các thông báo bị lỡ hiện ra **đúng thứ tự**, không nhảy cóc và không lặp. | ☐ Pass ☐ Fail | |
| W-5 | Làm token hết hiệu lực rồi để tab driver chạy tiếp. **Cách dựng rẻ nhất: tắt `python -m src.serve` rồi bật lại** — store token nằm trong RAM nên restart vô hiệu hoá mọi token còn hạn, không phải chờ hết 12 h. | UI khóa và **giữ khóa**, không tự mở lại. Trong vài giây (một nhịp poll `/vehicle/state`) người dùng được đưa về `/login` kèm dòng nêu lý do, chứ không kẹt ở màn hình mở mà không có quyền. | ☐ Pass ☐ Fail | UAT-009 |

## 5. Voice overlay — micro và lớp phủ

| ID | Kịch bản | Kết quả người dùng thấy | Kết quả | Bug ID |
|---|---|---|---|---|
| O-1 | Chạm nút mic để mở overlay, nói một câu rồi im lặng. | Overlay hiện chữ “Đang nghe”; sau khi im lặng, nó **tự dừng ghi** không cần bấm gì, rồi chuyển sang xử lý. | ☐ Pass ☐ Fail | |
| O-2 | Mở overlay, đang nói dở thì bấm đóng overlay. | Overlay đóng, mic tắt hẳn (đèn báo ghi âm của trình duyệt tắt), **không** có lượt nào được gửi đi sau đó. | ☐ Pass ☐ Fail | |
| O-3 | Mở overlay rồi bấm nút dừng thủ công giữa chừng. | Dừng ghi ngay và xử lý phần đã nói; không treo ở “Đang nghe”. | ☐ Pass ☐ Fail | |
| O-4 | Mở overlay trong lúc UI đang bị khóa (xe chạy, hoặc mất kết nối như W-1). | Overlay **không** che mất trạng thái khóa và không cho phép làm việc mà chính sách đang cấm. | ☐ Pass ☐ Fail | |
| O-5 | Mở/đóng overlay 5 lần liên tiếp. | Không có tiếng phát chồng lên nhau, không đơ, mic không kẹt ở trạng thái bật. | ☐ Pass ☐ Fail | |

## Tổng kết vòng UAT

| Nhóm | Pass | Fail | Bug P0 mở | Kết luận |
|---|---|---|---|---|
| Preflight | | | | |
| 1. Voice S1 | | | | |
| 2. S2 / HITL | | | | |
| 3. RAG + TTS | | | | |
| 4. WebSocket recovery | | | | |
| 5. Voice overlay | | | | |

**Điều kiện cho demo:** không còn bug P0 nào đang mở (định nghĩa P0 ở
`docs/release/uat-bug-triage.md`). Một luồng còn P0 thì bỏ luồng đó khỏi buổi
demo, theo đúng quy tắc đã chốt trong `docs/demo_scope.md` — không thay bằng
dữ liệu hay claim khác.

## Ngoài phạm vi checklist này

- Đèn và cốp của PR #92 (deferred — xem `docs/demo_scope.md`).
- Đo độ trễ end-to-end và WER người nói thật: chưa có số liệu, và UAT chạy tay
  **không** sinh ra được số liệu đó. Đừng suy ra từ cảm giác khi test.
- Mọi thứ liên quan tới xe thật, deploy hay dịch vụ cloud.

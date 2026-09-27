# UAT real mode — pool xe ảo, 4 trình duyệt

Nghiệm thu tay cho blocker 3 của [PM/PO review PR #262](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/pull/262#pullrequestreview).
Điều kiện approve nguyên văn: *"UAT real mode với 4 trình duyệt: ba xe độc lập; người thứ tư chỉ-xem;
kiểm cả Điều khiển, Trang chính và Mic."*

Test tự động đã phủ cả `canDrive` true/false và `pool` null/cấp-phát
(`VehicleControlView.pool.test.tsx`, `RightPanel.pool.test.tsx`, `DriverShellProvider.pool.test.tsx`),
nhưng test không chứng minh được ba thứ mà PM hỏi: xe có thật sự độc lập không, tài xế có **hiểu**
lý do bị khoá không, và mic có còn dùng được ở chế độ chỉ-xem không. Đó là lý do tài liệu này tồn tại.

Tài liệu này **chưa được chạy**. Khi chạy xong, tick vào bảng ở §4, ghi ngày + người chạy, rồi dán
kết quả vào PR #262.

---

## 1. Điều kiện tiên quyết

| Thứ | Yêu cầu | Bẫy nếu sai |
|---|---|---|
| Backend | Checkout nhánh của PR #259 (`feat/pool-xe-ao-theo-phien`), `VEHICLE_POOL_SIZE=3` | Không có `can_drive`/`pool` trong response `POST /sessions` |
| Xe ảo | **Cùng checkout, cùng `VEHICLE_POOL_SIZE`**, chạy `python -m src.vehicle_sim` | Container `vehicle-simulator` build từ `context: .` — ở nhánh frontend thì nó **không có code pool** và chỉ dựng một xe. Triệu chứng: bật đèn ở Chrome thì Edge cũng sáng |
| Frontend | Nhánh `feat/fe-pool-xe-ao`, real mode — cả ba cờ `NEXT_PUBLIC_USE_MOCK_TURN` / `_SESSION` / `_ENGINEER` = `false` | Ảnh chụp mock mode không chứng minh gì về backend |
| Model giọng nói | Zipformer + `vi_VN-piper.onnx` đã cài (`huong_dan_chay.md` §2.6) | Bấm mic lỗi `INTERNAL_ERROR` → không kiểm được §3.4 |
| 4 profile trình duyệt **độc lập** | Ví dụ Chrome, Edge, Chrome ẩn danh, Firefox. Không dùng 4 tab cùng profile | `localStorage` dùng chung → 4 tab chia nhau **một** phiên, mất sạch ý nghĩa của bài test |
| Service worker lạ | Xoá trước khi test (xem `CLAUDE.md`) | Trang render nhưng React không hydrate, click không ăn, không có lỗi console |

**Xếp 4 cửa sổ cạnh nhau, đừng để cửa sổ nào nằm sau.** Tab bị ẩn lâu bị Chrome đóng băng, ngừng
poll, và mất xe — hỏng bài test mà không có triệu chứng rõ ràng.

## 2. Trình tự vào phiên

Vào **lần lượt**, không vào cùng lúc, và ghi lại `vehicle_id` mỗi lần (DevTools → Network →
`POST /api/v1/sessions` → response):

| Thứ tự | Trình duyệt | `can_drive` mong đợi | `pool` mong đợi | `vehicle_id` thực tế |
|---|---|---|---|---|
| 1 | | `true` | `{total:3, in_use:1, free:2}` | |
| 2 | | `true` | `{total:3, in_use:2, free:1}` | |
| 3 | | `true` | `{total:3, in_use:3, free:0}` | |
| 4 | | **`false`** | `{total:3, in_use:3, free:0}` | |

Ba `vehicle_id` đầu phải **khác nhau từng đôi một**. Trùng nhau = xe ảo không có code pool (bẫy ở §1).

## 3. Bài kiểm

### 3.1 Ba xe độc lập (phép thử quyết định của ADR-028)

Đặt mỗi trình duyệt 1–3 một trạng thái **khác hẳn nhau**, rồi soi cả ba màn hình cùng lúc:

| | Trình duyệt 1 | Trình duyệt 2 | Trình duyệt 3 |
|---|---|---|---|
| Điều hoà | 26° | 28° | 22° |
| Quạt | 1 | 2 | 3 |
| Cửa | mở khoá Bên phụ | mở khoá Sau trái | mở khoá tất cả |
| Cửa sổ | đóng | 65% | 30% |

- [ ] Ba màn hiển thị đúng ba trạng thái trên, **không** lẫn sang nhau.
- [ ] Xe 3D ở mỗi màn phản ánh đúng cửa/cửa sổ của **chính** phiên đó.
- [ ] Thao tác thêm ở trình duyệt 1 không làm đổi bất cứ gì ở 2 và 3 (soi trong lúc bấm, đừng bấm xong mới nhìn).

### 3.2 Người thứ tư — màn **Điều khiển**

- [ ] Toàn bộ nút điều khiển (cửa/cốp, điều hoà, đèn, cửa sổ, ghế) **disabled**.
- [ ] Hiện thông điệp *"Hết xe mô phỏng khả dụng — bạn đang ở chế độ chỉ xem…"*.
- [ ] Thông điệp đó **không** phải câu "Mất kết nối với hệ thống" của issue #241 — đây là điểm PM quan tâm nhất: hai lý do khác nhau phải đọc ra khác nhau.
- [ ] Trạng thái xe vẫn hiển thị (không trống, không "—").
- [ ] Ô pool đọc là **`Lúc vào phiên: 3/3 xe`** — không phải "Xe đang dùng"; rê chuột vào thấy tooltip nói rõ đây không phải số hiện tại.

### 3.3 Người thứ tư — **Trang chính** (`RightPanel`)

- [ ] Ba nút tắt ở Trang chính cũng **disabled** — khoá phải lan ra cả đây, không chỉ màn Điều khiển.
- [ ] `StatusBar` hiện lý do chỉ-xem, và hiện ở **mọi** màn: chuyển sang Nhạc, sang Bản đồ, lý do vẫn còn.
  *(Đây là chỗ chống "bấm rồi mới biết" — tài xế đang ở Nhạc mà chỉ thấy nút xám thì không hiểu vì sao.)*

### 3.4 Người thứ tư — **Mic**

- [ ] Nút mic **không** bị khoá.
- [ ] Hỏi sổ tay bằng giọng nói (ví dụ *"Camp Mode là gì"*) → có transcript, có câu trả lời, có trích dẫn. Phiên chỉ-xem vẫn phải tra được sổ tay.
- [ ] Ra **lệnh điều khiển** bằng giọng nói (ví dụ *"mở cửa sổ"*) → bị từ chối, và câu từ chối là **tiếng Việt** chứ không phải chuỗi thô `vehicle_pool_exhausted`.
- [ ] Nghe được câu trả lời qua loa (TTS) — nhớ đã click vào trang ít nhất một lần trước đó, nếu không autoplay policy chặn `.play()` đầu tiên.

### 3.5 Trả xe

- [ ] Đóng hẳn trình duyệt 1 (không chỉ đóng tab), đợi phiên hết hạn/được thu hồi, rồi tải lại trình duyệt 4.
- [ ] Trình duyệt 4 giờ nhận `can_drive: true` và một `vehicle_id` riêng.

> Nếu bước này không đạt, **không** coi là hỏng PR #262: cơ chế thu hồi xe nằm ở backend #259. Ghi lại kết quả và báo về #259.

### 3.6 Lưới an toàn — `VEHICLE_POOL_SIZE=1`

Chạy lại backend + xe ảo với `1`, một trình duyệt:

- [ ] `can_drive: true`, `pool: null`.
- [ ] **Không** hiện ô pool nào trên màn Điều khiển.
- [ ] Mọi nút điều khiển dùng được như hôm nay.

## 4. Kết luận

| Mục | Đạt | Ghi chú |
|---|---|---|
| 3.1 Ba xe độc lập | | |
| 3.2 Màn Điều khiển | | |
| 3.3 Trang chính + StatusBar | | |
| 3.4 Mic | | |
| 3.5 Trả xe | | |
| 3.6 `POOL_SIZE=1` | | |

**Người chạy:** ___  **Ngày:** ___  **Commit FE:** ___  **Commit BE:** ___

## 5. Cái UAT này cố ý **không** chứng minh

Ghi ra để không ai đọc một bảng toàn dấu tick thành nhiều hơn sự thật:

- **Không phải bài đo throughput.** Pool quản quyền điều khiển, không quản sức chứa của SLM/STT/TTS — xem [`demo_runbook.md`](../demo_runbook.md) §"Pool xe ảo là quyền điều khiển". Bốn người thao tác lần lượt không nói gì về bốn người nói cùng lúc; [#257](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/257) đã thấy timeout ngay ở N=3.
- **Không đo độ trễ end-to-end.** Vẫn chưa từng đo, ở bất kỳ N nào.
- **Không chốt capacity.** Con số `3` chốt theo RAM (`eval/results/ram-nhieu-xe/`), không theo SLO.
- **Không phải bằng chứng WER.** Bước mic ở §3.4 chỉ chứng minh mic *dùng được* ở phiên chỉ-xem.

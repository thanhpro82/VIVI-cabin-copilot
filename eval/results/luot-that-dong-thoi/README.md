# `luot-that-dong-thoi` — đọc file này trước khi trích bất kỳ run nào

Bảy run của ngày 2026-08-25, sinh bởi `scripts/do_luot_that_dong_thoi.py`. Chúng
**không ngang hàng nhau**: script được sửa ba lần *trong lúc* đo, vì chính số liệu lộ
ra lỗi của phép đo. Run cũ được giữ lại làm dấu vết theo kỷ luật bất biến của
`eval/results/`, **không** phải để trích dẫn.

| Run id | Chế độ | Commit | Dùng được? |
|---|---|---|---|
| `20260825T035510` | text | `3e4e6a4` | trung gian |
| `20260825T040635` | text | `3e4e6a4` | trung gian |
| `20260825T040756` | voice | `3e4e6a4` | **KHÔNG — số sai** |
| `20260825T042019` | text | `3e4e6a4` | trung gian |
| **`20260825T050738`** | text | `3e4e6a4` | **BASELINE** |
| `20260825T054210` | text | `ed3f884` | trung gian |
| **`20260825T073454`** | text | `5861ea7` | **SAU BẢN VÁ** |
| `20260825T083929` | voice | `6c0a6e7` | cột `loi` đọc theo `0db42c1` |
| **`20260825T090905`** | voice | `d4acc88` | **VOICE, dùng được** |

## Cặp dùng để ra quyết định

**`20260825T050738`** (`develop` @ `3e4e6a4`) và **`20260825T073454`** (nhánh
`fix/slm-nhieu-nguoi-dung-dong-thoi` @ `5861ea7`). Cùng `-c 2048 / 4 rãnh`, cùng
`https://c4-app-192.io.vn` (có Caddy), 24 mẫu mỗi mức, cùng rổ ca. Khác đúng **một**
biến: `asyncio.to_thread` + van đồng thời.

Đây là cặp được trích trong PR #257 và ADR-030.

## `20260825T090905` — run voice dùng được, và là bằng chứng của điều kiện 3

Chạy sau bản vá nhánh chờ duyệt (`0db42c1`): `loi 0/10`, `cat cut 0` ở cả ba mức.

p50 **5 700 / 11 149 / 20 880 ms** — **trượt** ngưỡng 2 500 ms ở cả ba mức, kể cả khi
chỉ một người dùng. Ở N=3 thì **10/10 lượt vượt p95**.

Chỗ quan trọng nhất nằm ở dữ liệu thô, không ở bảng tóm tắt: đường **`tire_pressure_all`**
— câu trả lời tất định, **không chạm model một giây nào** — đi từ **619 ms** ở N=1 lên
**26 232 ms** ở N=3. Cùng lúc đó `transcript.final` chậm từ 202 ms lên 1 462 ms. Hai
thành phần không dùng SLM cùng sập khi SLM bận, nên nút thắt là **tài nguyên máy**, không
phải model. Xem mục "Việc chưa làm" của `docs/deploy_vps_van_hanh.md`.

Khoảng `assistant.speech` → kết thúc đo được **0–3 ms** ở mọi mức, nên khâu phát audio
không phải thủ phạm.

## `20260825T083929` — run voice đầu tiên; cột `loi` của nó gây hiểu nhầm

Run này báo câu *"Trong xe ngột ngạt quá, xử lý giúp tôi"* hỏng **6/6** ở mọi mức N.
**Không phải hỏng.** Câu đó sinh kế hoạch chạm bước **S2** (mở cửa sổ — cửa sổ luôn
S2), nên lượt kết thúc bằng **hỏi lại xin duyệt**, không bằng `assistant.response`.
`ivi_events.py:467`: nhánh đó *"có tiếng nói mà không có `assistant.response`"*.

Script lúc đó chỉ chờ `assistant.response` nên ngồi tới trần 60 s rồi ghi là lỗi. Dữ
liệu thô đã tự tố cáo điều đó: `transcript.final` tới lúc 236 ms và `assistant.speech`
tới lúc 18 s — lượt chạy bình thường và đang đợi người bấm Duyệt.

Sửa ở `0db42c1`. Các con số **p50/p95 của run này vẫn dùng được** (chúng chỉ tính trên
lượt thành công); chỉ cột `loi`/`cat cut` là phải đọc kèm ghi chú này.

## `20260825T040756` — số sai, đừng dùng

Chế độ `voice` lúc đó bắt `assistant.response` **đầu tiên nhìn thấy** trên WebSocket.
Socket mở một lần cho cả phiên rồi dùng lại, nên hàng đợi đã có sẵn event của lượt
trước (kể cả hai lượt hâm nóng) — đồng hồ dừng gần như tức thì. Bảng cho `p50 33 ms`,
có ô **10 ms** cho một lượt STT + router + TTS. Không thể.

Sửa ở `97caacf`: lọc theo `data.turn_id` từ thân 202.

## Vì sao bốn run "trung gian" không dùng được

Mỗi run trượt ít nhất một trong ba lỗi của phép đo, đều đã sửa:

1. **Rổ ca đổi theo N** (`97caacf`) — tỉ lệ câu rẻ/đắt khác nhau ở mỗi mức, nên cột
   "Tổng hợp" không so ngang được. Triệu chứng: p50 ở N=3 *thấp hơn* p50 ở N=2.
2. **Lô luôn gom ca liền kề** (`d6ad6c6`) — `dieu_khien` không bao giờ chạy chung lô
   với `planner`, nên nó trông như miễn nhiễm. Sửa bằng cách xoay bộ ca theo vòng.
3. **Chỉ một câu planner** (`ed3f884`) — chứng minh được "câu này hỏng" chứ không
   chứng minh được cả đường planner hỏng. Cùng commit thêm cột `ra plan`, tách
   "chậm" khỏi "hỏng".

`20260825T054210` chạy với script trước khi có cột `bi tu choi` (`5861ea7`), nên nó
không phân biệt được "được trả lời" với "bị từ chối" — sau khi có van thì thiếu cột
đó là đủ để đọc sai.

## Điều đúng cho cả bảy run

Không run nào chạy ở `-c 8192`. Tất cả đều `-c 2048`, đọc trực tiếp từ `/props` của
llama-server và ghi vào `manifest.json` — thứ mà bốn run `eval/results/slm-dong-thoi/`
không có, nên chúng không tự nói được mình đo cấu hình nào.

Mọi run đều là **một lần đo trên một máy**. Đọc mục `blind_spots` trong `manifest.json`
trước khi kết luận.

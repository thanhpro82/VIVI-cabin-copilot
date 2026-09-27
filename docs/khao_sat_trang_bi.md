# Khảo sát trang bị tuỳ chọn trong sổ tay VF9

**Trạng thái:** Chạy được trên PC · **Bằng chứng:** `eval/results/trang-bi/20260819T055632Z/`
· **Tái lập:** `.\.venv\Scripts\python.exe scripts\khao_sat_trang_bi.py`

Tài liệu này trả lời một câu: **hồ sơ xe đầy đủ nên gồm những gì.** Bằng cách đếm,
không phải bằng cách đoán.

## Vì sao phải hỏi câu này

`GET/PUT /api/v1/vehicle/profile` (#123) hôm nay giữ đúng hai trường, `trim` và
`battery`, và chúng tồn tại để phục vụ **một** nhánh: bảng áp suất lốp bốn ô.

Nhưng sổ tay đặt điều kiện lên nhiều hơn thế rất nhiều. Quét toàn bộ chunk store:

| | |
|---|---|
| chunk trong index | 482 |
| chunk chứa ít nhất một mệnh đề điều kiện trang bị | **116** (24%) |
| tổng số lần nhắc | **147** |

Dấu được đếm: `nếu được trang bị`, `(nếu có)`, `nếu có trang bị`, `tuỳ theo thị
trường`, `tuỳ phiên bản`, `nếu xe (của bạn) được trang bị / có`.

Composer hiện trích nguyên văn, nên tài xế nghe lại đúng chữ *"nếu được trang bị"* và
phải tự đoán. Ở phần lớn ca đó chỉ là dài dòng. Ở vài ca thì không, và ba ca dưới đây
đều là ca người ta hỏi đúng lúc đang cần:

- *"Kéo cần gạt mở cửa khẩn cấp bên cạnh khoang chứa đồ ở cửa"* — quy trình thoát hiểm
  khi mất điện, trên chiếc xe không có cần gạt ấy ở hàng ghế sau.
- *"Lốp dự phòng nằm trong khoang chứa đồ phía sau"* — xe dùng bộ bơm hơi, và tài xế
  đang đứng bên đường.
- *"Xe được trang bị phanh khẩn cấp tự động"* — hứa một lớp bảo vệ không tồn tại.

Ca thứ hai không chỉ là lý thuyết: `_tra_ap_suat_lop` trả **420 kPa** cho câu hỏi áp
suất lốp dự phòng của **mọi** chiếc xe, kể cả xe không có lốp dự phòng. Đó là số của
một bánh xe không tồn tại, và nó đang chạy trên `develop`.

## Ba loại `(nếu có)`, và chỉ một loại là trường hồ sơ

Đây là kết quả chính, và là thứ ngăn người sau dựng 147 lá cờ.

| loại | là gì | ví dụ | vào hồ sơ? |
|---|---|---|---|
| **1** | trang bị tuỳ chọn — thứ rời rạc chủ xe nhìn là biết | *"Đèn sương mù phía sau (nếu được trang bị)"* | **có** |
| **2** | dữ liệu có thể vắng lúc chạy | *"cảnh báo lỗi (nếu có)"*, *"các địa danh 3D (nếu có)"* | không |
| **3** | điều kiện về thứ khác, không phải về xe | *"Nếu Ghế trẻ em của bạn được trang bị chân phụ"* | không |

Loại 2 là cái bẫy đắt nhất: nó đọc y hệt loại 1. Không cấu hình nào trả lời được
*"cảnh báo lỗi (nếu có)"* — nó phụ thuộc việc lúc đó xe có lỗi hay không. Dựng một
trường hồ sơ cho nó là tự lừa mình rằng đã xử lý xong một ca.

## Danh mục đề xuất: 65 trang bị, 10 nhóm

Curate tay tại `src/safety/trang_bi.json`, theo đúng khuôn `ap_suat_lop.json` (JSON
cạnh module, có provenance, hai lớp test). Cột "lần nhắc" là số mệnh đề điều kiện
trong sổ tay thật khớp nhóm ấy.

| nhóm | số mục | lần nhắc | trang bị |
|---|---|---|---|
| `dich_vu` | 17 | 42 | Gói thuê pin, Trợ lý ảo, Ứng dụng VinFast, Điều khiển từ xa, Đèn báo cổng sạc, Chỉ báo tiến trình sạc, Nút mở cổng sạc, Đặt mục tiêu sạc, Nhận diện trạm sạc, Cập nhật OTA, Khoá tự động khi rời xe, Cá nhân hoá hồ sơ, Chế độ Người lạ, Chế độ Thú cưng, Chế độ Nghỉ ngơi, Nhắc bảo dưỡng, Hỗ trợ bên thứ ba |
| `adas` | 15 | 23 | AEB, Hỗ trợ lái cao tốc, Trợ làn (LDW/LKA/ELK), Chuyển làn tự động, DMS, DOW, Hỗ trợ đỗ xe, ACC, Điều chỉnh tốc độ thông minh, Nhận biết biển báo, FCW, BSD, Cảnh báo giao thông sau, Camera lùi, Camera 360 |
| `khoang_lai` | 9 | 20 | Màn hình hàng ghế sau, Sạc không dây sau, HUD, Tuỳ chỉnh nút Trip, Ổ cắm AC 220V, Bộ lọc ion, Điều hoà hàng ba, Khoang chứa đồ ở cửa, Mở ca-pô từ màn hình |
| `cuu_ho` | 2 | 12 | Lốp dự phòng, Bộ bơm hơi và vá lốp |
| `chieu_sang` | 4 | 11 | Đèn sương mù sau, Đèn sương mù trước, Đèn góc cua, Đèn phanh giữa |
| `ghe` | 6 | 8 | Ghế VIP hàng hai, Ghế giữa hàng hai, Nhớ vị trí ghế, Massage ghế, Ghế sưởi/làm mát, Chỉnh tựa lưng điện |
| `an_toan` | 4 | 5 | Phát hiện trẻ bị bỏ quên, Túi khí giữa hàng trước, Túi khí đầu gối, Cần gạt mở cửa khẩn cấp hàng sau |
| `vo_lang` | 3 | 4 | Sưởi vô lăng, Cột lái chỉnh điện, Cột lái chỉnh tay |
| `lai_xe` | 3 | 4 | Móc kéo rơ moóc, Auto Hold, Mức phanh tái sinh Tắt |
| `guong` | 2 | 2 | Gương tự làm mờ, Gương nghiêng khi lùi |

Hai cặp **loại trừ nhau**, và quan hệ ấy được ép ở cả tầng nạp lẫn tầng ghi:
`lop_du_phong` ↔ `bo_bom_hoi`, `cot_lai_chinh_dien` ↔ `cot_lai_chinh_tay`. Một chiếc
xe không thể vừa có lốp dự phòng vừa dùng bộ bơm hơi, và nếu hồ sơ tin cả hai thì
nhánh cứu hộ trả lời sai theo cả hai hướng.

### Một mục đã bị gỡ, và vì sao đó là điều tốt

Bản nháp có **Chế độ Cắm trại**. Khảo sát không tìm ra mệnh đề điều kiện nào gắn với
riêng nó — chỗ trông giống nhất hoá ra nói về *màn hình hàng ghế sau*, còn đường kích
hoạt thì gắn điều kiện lên *Ứng dụng VinFast*. Nên nó bị gỡ. Đây đúng là việc mà một
đợt đếm phải làm được: bác một mục nghe hợp lý mà không có bằng chứng.

## Phủ sóng: 89%, và 100% sẽ là dấu hiệu xấu

131 trên 147 mệnh đề khớp một mục trong danh mục, và cả 65 mục đều khớp ít nhất một
mệnh đề thật (không có mục chết).

Đọc tay 16 mệnh đề còn lại: **mười lăm** đúng là loại 2 hoặc loại 3 — dữ liệu bản đồ,
cảnh báo lỗi, ảnh đại diện liên hệ, chân phụ ghế trẻ em. Chỉ **một** ca là loại 1 bị
hụt (*"Nếu xe có thể kéo thêm rơ móoc"*), và nó hụt vì biểu thức dò dấu nuốt luôn chữ
`"xe"` nên cửa sổ nhìn lui không còn cụm nào để khớp.

Vì thế đừng tối ưu con số này lên 100%. Muốn đạt 100% thì danh mục phải nuốt cả loại
2 và loại 3, tức phải khẳng định rằng *"cảnh báo lỗi (nếu có)"* là một trang bị tuỳ
chọn của chiếc xe. Sàn hồi quy đặt ở **85%** (`test_trang_bi_provenance.py`), không có
trần.

## Ba trạng thái, và "chưa biết" là trạng thái bình thường

Phản đối hiển nhiên với một danh mục 65 mục: *không ai ngồi khai đủ 65 trường.* Đúng,
và không ai phải khai.

Hồ sơ ba trạng thái — **có / không / chưa biết** — và *chưa biết* là mặc định, y hệt
`trim`/`battery` của #123. Ở tầng dữ liệu nó là **vắng hàng** trong `vehicle_options`,
nên không cần chọn một giá trị mặc định nào cả. Khai một trường thì chỉ những câu trả
lời phụ thuộc trường ấy đổi; 64 trường còn lại cư xử y như hôm nay.

Đây là tính chất khiến một danh mục 65 mục dùng được: **giá trị đến từng trường một,
không phải từ việc điền hết.** Buổi demo khai đúng những mục kịch bản chạm tới.

## Vì sao không suy trang bị từ `trim`

Cám dỗ hiển nhiên: `plus` thì có ACC, `eco` thì không, khỏi bắt ai khai báo.

Sổ tay VF9 **không nói** bản nào có gì — nó chỉ nói "nếu có". Dựng một bảng `trim →
trang bị` là bịa ra tri thức không có trong nguồn, đúng lớp lỗi mà docstring
`is_complete` đã cảnh báo: kiến thức về nội dung bảng rò rỉ ra ngoài bảng, rồi sai âm
thầm khi sổ tay bản sau đổi. Nếu sau này có tài liệu cấu hình chính thức của VinFast
thì bảng ấy là một **nguồn mới**, phải curate và có provenance như mọi bảng khác —
không phải một suy luận cài trong mã.

## Hệ quả API

Sub-resource riêng: `GET/PUT /api/v1/vehicle/profile/options`. **Không** thêm field vào
body của `PUT /vehicle/profile`, vì `VehicleProfileUpdate` có `extra="forbid"` và đòi
có mặt cả hai field — thêm `options` vào đó thì hoặc mọi client hiện có gãy 422, hoặc
phải nới lỏng đúng bất biến mà model ấy dựng lên.

`is_complete` **không** đổi nghĩa. Nó là cổng của nhánh áp suất lốp và chỉ của nhánh
ấy: "đã đủ để tra bảng bốn ô chưa". Không có khái niệm tương đương cho trang bị, vì
không tồn tại một tập "đủ".

## Cái đang làm và cái chưa làm

**Đã nối vào đường trả lời**, hẹp và cố ý hẹp: khi **mọi** trang bị nhận ra được trong
đoạn đều đã khai là *không có*, composer nói thẳng *"Xe của bạn không được trang bị
X"* thay vì đọc hướng dẫn cho phần cứng vắng mặt. Cộng với việc chặn 420 kPa cho xe
không có lốp dự phòng.

**Chưa làm**, và mỗi việc nên là một vòng có số đo riêng:

- **Đoạn pha** — có mệnh đề về một trang bị vắng nhưng cũng nói cả thứ khác. Chèn một
  câu cảnh báo rồi vẫn đọc tiếp thì tốn ngân sách ký tự trên mọi lượt như thế, mà trần
  nói là tài nguyên khan nhất của tầng này: đo 18/08 cho thấy nới câu dẫn thêm 14 ký
  tự đã đổi được 5 điểm chính xác.
- **Dùng trang bị để lọc lúc truy hồi**, không chỉ lúc soạn câu — hôm nay đoạn về phần
  cứng vắng vẫn thắng bộ chọn rồi mới bị chặn.
- **Màn khai báo trên IVI.** API trả sẵn cả danh mục kèm `nhom` và `loai_tru` để client
  không phải giữ bản sao, nhưng chưa có màn hình nào dùng.
- **Câu hỏi trực tiếp** kiểu *"xe tôi có phanh khẩn cấp tự động không?"* — router chưa
  có luật, nên nó rơi vào tra sổ tay.

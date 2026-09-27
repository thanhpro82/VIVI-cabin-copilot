# Chấm tay 15 bản tóm tắt được nhận — 19/08

Cấu hình được chấm: Qwen3-4B-Instruct-2507 Q4_K_M trên dGPU, dung sai k=1, sàn giữ 0,85.
15 trên 39 ca có bản tóm vượt cổng; 24 ca còn lại rơi về trích nguyên văn.

## Cách chấm

Hội đồng **ba lăng kính độc lập** cho mỗi ca, chấm mù với nhau:

- `quan-he` — chỉ soi quan hệ thời gian / điều kiện / nhân quả
- `pham-vi` — chỉ soi phạm vi, lượng từ, mức khuyến nghị, phủ định
- `ghep-y`  — chỉ soi việc ghép hai ý vốn rời nhau

45 lượt chấm. Bất đồng thì có một lượt phân xử đọc lại nguồn — **không ca nào cần**,
ba lăng kính đồng thuận trên cả 15 ca.

Quy tắc đã nêu rõ cho người chấm: bỏ bớt ý KHÔNG phải sai lệch; từ đồng nghĩa giữ
nguyên nghĩa KHÔNG phải sai lệch; không chắc thì chấm là không sai.

## Kết quả

| | |
|---|---|
| bản tóm được chấm | 15 |
| **sai lệch** | **2 (13%)** |
| trong đó mức nặng | 2 |
| mức nhẹ | 0 |
| ca phải phân xử | 0 |

### RAG-101 — khẳng định thành giả định

    nguồn:  "CẢNH BÁO Trong quá trình khởi tạo, cửa sổ điện không có chức năng
             cảm biến chống kẹp."
    bản tóm: "Nếu trong quá trình khởi tạo, cửa sổ điện không có chức năng
             cảm biến chống kẹp."

Thêm liên từ điều kiện `Nếu` mà nguồn không có, bỏ nhãn CẢNH BÁO, và bỏ luôn mệnh đề
kết quả. Một cảnh báo chắc chắn thành một câu giả định cụt.

### RAG-126 — lựa chọn thành trình tự

    nguồn:  "Có thể truy cập ... bằng BẤT KỲ cách nào sau đây: ... HOẶC ... HOẶC ..."
    bản tóm: "... bật Trợ lý giọng nói, RỒI nhấn nút NGUỒN và chuyển sang ..."

Sổ tay liệt kê ba cách thay thế nhau; bản tóm nối chúng thành một chuỗi thao tác.
Tài xế được bảo làm A rồi B, trong khi sổ tay nói làm A hoặc B.

## Nguyên nhân, và nó truy được về đúng một tham số

Cả hai ca có `so_tu_khong_khop = 1`, tức **cả hai bị bác ở dung sai k=0 và chỉ lọt vì
k=1**. Và hai chữ lọt vào — `nếu`, `rồi` — không phải từ đồng nghĩa nào cả: chúng là
**từ chỉ quan hệ**. Dung sai vốn mở cho đồng nghĩa ("chặn" thay "ngăn") đã bị từ quan
hệ chiếm mất.

Đã thêm cổng `chen_tu_quan_he`: chèn thêm một từ trong `TU_QUAN_HE` là bác ngay, không
qua dung sai. Kiểm lại: cả hai ca trên bị chặn, còn ca đồng nghĩa và ca xoá bớt vẫn qua.

## Giới hạn của chính bản chấm này

- Người chấm là các tác tử của cùng hệ thống đang được chấm. Đây **không** phải chấm
  bởi người ngoài, và không thay được một vòng người dùng thật.
- 15 ca là mẫu nhỏ; 2/15 có khoảng tin cậy rất rộng.
- Bộ phân loại an toàn của harness bị giới hạn nhịp khi soát 34 trên 45 lượt chấm. Kết
  quả đã được đối chiếu tay với đọc độc lập trước đó và khớp trên cả hai ca bị gắn cờ.

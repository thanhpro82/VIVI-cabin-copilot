# Bộ eval RAG sổ tay VF9 — v1

60 case: **40 positive + 20 negative**, dùng cho `python -m src.rag.cli eval`.

## Nguồn nhãn (quan trọng để đọc kết quả cho đúng)

| Trường | Nguồn | Tính độc lập |
|---|---|---|
| `expected.citation.section` | `manifest.json` của chính sổ tay — `"{chapter} / {name}"` | **Ngoại sinh.** Do VinFast phát hành, không do hệ thống sinh ra |
| `expected.citation.page` | Bảng heading→trang do `page_mapper` dựng | Nội sinh, nhưng `page_exact_rate = 100%` và đã đối chiếu tay với footer PDF |
| `expected.supported` | Người viết case quyết định | Ngoại sinh |

Vì `page` là nhãn nội sinh, **chỉ tiêu chính là `section`**. `page` dùng làm kiểm
tra chặt hơn, và độ đúng của số trang trong câu trả lời được đo riêng bằng
`citation_validity` (đối chiếu citation với chunk store, cổng cứng 100%).

## Phân bố positive — 10 mục liên quan lệnh xe

| Mục | Số câu |
|---|---:|
| Đóng Mở và Khoang chứa đồ / Cửa sổ điện | 4 |
| Đóng Mở và Khoang chứa đồ / Cửa | 3 |
| Ghế và hệ thống an toàn / Ghế | 4 |
| Lái xe / Đèn ngoại thất | 5 |
| Màn hình, Kết nối và Điều hòa / Điều hòa | 6 |
| Màn hình, Kết nối và Điều hòa / Khu vực điều khiển xe | 3 |
| Màn hình, Kết nối và Điều hòa / Thông tin giải trí | 4 |
| Bảo dưỡng / Vành và bánh xe | 5 |
| Pin và Sạc / Hướng dẫn sạc | 2 |
| Pin và Sạc / Thông tin về pin | 4 |

## Phân bố negative — 3 loại

| Loại | Số câu | Mục đích |
|---|---:|---|
| Ngoài phạm vi sổ tay | 7 | Kiến thức chung, không liên quan xe |
| Tính năng không tồn tại | 7 | Gồm cả bẫy động cơ xăng/bình xăng/số tay trên xe **điện** |
| Prompt injection | 6 | `injection_resistant: true` — sổ tay là dữ liệu, không phải chỉ thị |

Hệ thống phải **từ chối** toàn bộ 20 câu negative. Với 20 câu, ngưỡng
`hallucination_rate < 5%` nghĩa là **không được sai câu nào**.

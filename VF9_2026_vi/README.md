# VF9 2026 — corpus sách hướng dẫn sử dụng (tiếng Việt)

Bản chụp sách hướng dẫn sử dụng trực tuyến VinFast VF9 2026, dùng làm nguồn cho
RAG (`src/rag/`). **Corpus không nằm trong git.**

## Vì sao không commit

`src/rag/ingest/pipeline.py` gắn vào mọi index dòng này: *"Bản quyền thuộc Công ty
Cổ phần Sản xuất và Kinh doanh VinFast. Nội dung không được sao chép, sửa đổi hoặc
sử dụng lại nếu không có văn bản cho phép. Chỉ dùng nội bộ cho đồ án AI20K P-192."*
Đẩy 157MB nội dung đó lên repo tổ chức là phân phối lại, và git history thì gỡ ra
rất khó. Quyền phân phối lại **chưa được xác nhận bằng văn bản**.

## Cái gì được track

| File | Kích thước | Vai trò |
|---|---:|---|
| `manifest.json` | 35KB | 58 mục: `id`, `chapter`, `name`, đường dẫn `html`/`pdf`, `anchors`. Đầu vào của `load_documents()` |
| `corpus.sha256` | ~190KB | sha256 của **từng** file trong 1898 file, để verify bản corpus bạn có đúng là bản đã sinh ra index |
| `README.md` | — | file này |

Ai có corpus cũng dựng lại được index **giống hệt** và tự verify bằng checksum;
không ai phải tin lời người khác về việc index được sinh ra từ cái gì.

## Nội dung corpus đầy đủ (không track)

| Thành phần | Số file | Ghi chú |
|---|---:|---|
| `VF9_2026_full.pdf` | 1 | 59MB, **không cần** cho ingest |
| `pdf/` | 58 | 58MB, **cần** — `page_mapper.py` đọc để gán số trang |
| `html/` | 58 | 1.5MB, **cần** — nguồn nội dung |
| `assets/` | 1779 | 38MB css/ảnh, **không cần** — parser bỏ ảnh hoàn toàn |
| `menu.json` | 1 | response API gốc của cây mục lục |

Tổng: 1898 file, 157.175.616 byte (~149,9 MB).

## Nguồn gốc

- **Nguồn:** `https://om.vinfastauto.com`
- **Ngày chụp:** chưa xác định — corpus được chuyển từ repo `P-192 - Local` ngày
  2026-08-07 và provenance chưa được điền. Đừng ghi ngày đoán vào đây.
- **Công cụ chụp:** chưa xác định.
- **Tính đầy đủ:** chưa đối chiếu với mục lục gốc.

## Dựng index

```powershell
.\scripts\prepare_vf9_index.ps1
```

Script kiểm corpus tồn tại, verify checksum, copy sang `data/manuals/vf9_2026_vi/`
(thư mục `data/` đã gitignore), rồi chạy `python -m src.rag.cli ingest` và `verify`.
Nó **không tự tải** gì — `agent_spec.md` cấm network lúc chạy.

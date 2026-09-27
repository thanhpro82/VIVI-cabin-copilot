# Diễn tập offline — kiểm ADR-001 "No network at runtime"

**Trạng thái: Chạy được trên PC** (lớp tự động). Lớp ngắt card mạng thật: **Chưa chạy**.

ADR-001 là tuyên bố trung tâm của dự án: hệ thống chạy trong xe, không gọi mạng lúc
vận hành. Trước 2026-08-15 nó **chưa từng được kiểm** — không test, không run dir. Tài
liệu này mô tả hai lớp kiểm, và quan trọng hơn, mô tả chính xác **mỗi lớp không chứng
minh được gì**.

## Lớp 1 — tự động (đã có)

```powershell
.\.venv\Scripts\python.exe scripts\offline_drill.py
```

Sinh `eval/results/offline-drill/<UTC-run-id>/` gồm `manifest.json`,
`case_results.jsonl`, `metrics.json`, `report.md`. Thoát khác 0 nếu có ca nào hỏng.

Bảy ca, chạy trong `src/offline_guard.CongChanEgress`:

| Ca | Cái nó kiểm |
|---|---|
| `guard_self_test` | Cố tình phân giải `huggingface.co`. **Phải bị chặn.** |
| `nap_stt` | Nạp sherpa-onnx Zipformer từ đĩa |
| `stt` | Chuyển `warm_sample.wav` thành chữ |
| `tts` | Tổng hợp giọng Piper |
| `rag` | FAISS + embedder E5 trên index VF9 |
| `luot_so_tay` | `POST /turns/text` — câu hỏi sổ tay, qua auth + session + graph |
| `luot_dieu_khien` | `POST /turns/text` — lệnh điều khiển S1 |

**Ca đầu tiên là lý do bản báo cáo đáng tin.** Nếu cổng hỏng thì `guard_self_test`
xanh sai và script thoát khác 0 — một diễn tập không thể thất bại thì không phải bằng
chứng, nó chỉ là một dòng chữ "đã kiểm".

### Hai lớp quan sát, bù đúng điểm mù của nhau

- **Cổng Python** (`socket.connect` / `connect_ex` / `create_connection` /
  `getaddrinfo`): biết **ai gọi** — có stack trace — nhưng mù với mã native.
- **Bảng kết nối của HĐH** (`psutil`): thấy cả socket do C++ mở, vì kernel không quan
  tâm ai gọi — nhưng không biết ai gọi, và nó **lấy mẫu** một lần sau mỗi ca.

Cần cả hai. `onnxruntime` 1.28 nạp sẵn `AzureExecutionProvider` và xếp nó **đầu** danh
sách ưu tiên trên máy đo, nên "mã native có thể gọi ra ngoài" ở đây không phải lo xa.

Nếu máy chạy không có `psutil` hoặc HĐH từ chối đọc bảng kết nối, manifest ghi
`quan_sat_tang_os: false`. **Đọc trường này trước khi đọc kết quả** — "không đo được"
khác "đã đo và sạch", và hai thứ đó cho ra bản báo cáo trông giống hệt nhau.

### Chặn, không chỉ ghi

Cổng **ném** `OSError` thay vì ghi rồi cho đi tiếp. Vì thế drill trả lời được câu hỏi
thật — *hệ thống có còn chạy trọn một lượt khi không có mạng không* — chứ không chỉ
"có ai gọi ra ngoài không".

Lỗi ném ra cùng họ `OSError` với lỗi mạng thật, cố ý: nếu drill ném một loại lỗi mà
production không bao giờ thấy thì mọi `except OSError` fail-open sẽ không chạy, và ta
đo hành vi của một hệ thống khác với hệ thống thật.

## Lớp 2 — ngắt card mạng thật (chưa chạy, cần người)

Lớp 1 chỉ nói về **tiến trình Python này**. Nó không nói gì về container, về tiến trình
con, hay về thứ gì khác trên máy. "Không byte nào rời máy" cần ngắt mạng thật.

Chưa tự động hoá được vì nó đòi quyền quản trị và nó **ngắt kết nối của chính người
đang chạy** — một script tự tắt card mạng giữa phiên làm việc là thứ không nên tồn tại
trong repo.

### Quy trình

1. Chuẩn bị **trước khi ngắt mạng**: mở sẵn `docs/demo_runbook.md`, dựng xong index,
   tải xong model, `docker compose up -d --wait mqtt vehicle-simulator` nếu muốn phủ cả
   chặng MQTT.
2. Ngắt **mọi** giao diện mạng: rút cáp và tắt Wi-Fi. Không dùng chế độ máy bay nếu máy
   có modem WWAN riêng — tắt từng cái và xác nhận.
3. Xác nhận đã ngắt: `ping 8.8.8.8` phải hỏng, `ping 127.0.0.1` phải chạy.
4. Khởi động backend `python -m src.serve` và FE `npm run dev`, rồi chạy trọn kịch bản
   demo: một câu hỏi sổ tay, một lệnh S1, một lệnh S2 có phê duyệt, một lượt nói.
5. Ghi lại: mỗi bước chạy được hay không, thông báo lỗi nếu có, và thời gian mỗi lượt.
6. Nối mạng lại, rồi mới viết run dir.

### Ghi kết quả vào đâu

Tự tay tạo `eval/results/offline-drill/<UTC-run-id>/` cùng khuôn với lớp 1, và ghi rõ
trong `manifest.json`:

```json
{"suite": "offline-drill", "lop": "ngat-card-mang", "nguoi_chay": "<tên>", "ghi_chu": "..."}
```

Đừng gộp vào run dir của lớp 1: hai lớp trả lời hai câu hỏi khác nhau, gộp lại thì mất
khả năng nói câu nào đã được kiểm bằng cách nào.

## Điểm mù của cả hai lớp

- **Model phải có sẵn trên đĩa.** Cả hai lớp chứng minh runtime không tải thêm gì.
  Không lớp nào chứng minh được máy chưa từng cần mạng để **có** model — việc tải model
  là `scripts/download_models.ps1`, một bước cài đặt, không phải runtime.
- **Không nói gì về Docker.** Lớp 1 chạy trong một tiến trình qua `TestClient`; lớp 2
  chạy `src.serve` trực tiếp. Image và topology `docker-compose` chưa được kiểm.
- **Lớp 1 chạy với `MQTT_ENABLED=false`.** Broker nói chuyện qua loopback nên nó không
  thể là nguồn egress, nhưng chặng lệnh → MQTT → simulator không nằm trong lượt đo.

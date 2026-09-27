# SPIKE-003 — sổ tay làm việc (nháp, báo cáo cuối ở file riêng)

Máy: Ryzen 5 5600H (6C/12T), 7,4 GB RAM, RX 5500M 4 GB (Vulkan1; Vulkan0 là iGPU).
llama.cpp `b10358` Vulkan, pin tại `tools/llama-vulkan/`. Model: hai file SPIKE-001
sẵn có, checksum kiểm trước mỗi lần load. `n_predict=160`, `-c 2048`, temperature 0.

## Bậc A — tốc độ thô (không grammar, không prompt-file)

| Cấu hình | decode tok/s (median) | total p50 (160 tok) | RSS server | Run |
|---|---:|---:|---:|---|
| 0.5B cpu6 | 38,0 | 4.348 ms | 566 MB | `rungA-cpu6-05b` |
| 0.5B cpu12 | 34,8 | 4.655 ms | 559 MB | `rungA-cpu12-05b` |
| 0.5B vulkan | **164,5** | 1.006 ms | 752 MB | `rungA-vulkan-05b` |
| 3B cpu6 | 9,3 | 17.441 ms | 1.903 MB | `rungA-cpu6-3b` |
| 3B vulkan | **63,0** | 2.658 ms | 1.433 MB | `rungA-vulkan-3b` |

Run-id đầy đủ nằm trong manifest từng thư mục `eval/results/spike-003/`.

**Đọc số:**

- **GPU là đòn bẩy thật: 3B nhanh gấp 6,8× khi rời CPU** (9,3 → 63,0 tok/s). Đây là
  bằng chứng trực tiếp cho giả thuyết "pipeline SPIKE-001 chưa tối ưu": cùng model,
  cùng máy — SPIKE-001 đo p50 11,2 s vì chạy CPU 4 luồng; phần cứng chưa bao giờ là
  nút thắt, đường phần mềm mới là.
- **SMT gây hại**: cpu12 chậm hơn cpu6 trên 0.5B (34,8 < 38,0). Loại cpu12; ô
  cpu12-3B không chạy vì cả hai tiền đề của nó đã thua (đây là lệch so với ma trận
  3×2 trong plan, có chủ đích — ô đó không còn khả năng thay đổi quyết định nào).
- 3B cpu6 = 9,3 tok/s < ngưỡng dừng 12 tok/s → **3B chết trên CPU**, đúng dự đoán.
  Nhưng tiêu chí dừng bậc A không kích hoạt vì Vulkan nhận GPU và chạy tốt.
- RSS server 3B-vulkan chỉ 1,4 GB (trọng số nằm VRAM) — tин tốt sớm cho bậc D.

**Quyết định bậc A: cấu hình vô địch = `vulkan` + 3B**; giữ 0.5B-vulkan làm đối chứng
chất lượng ở bậc C. Ước p50 lượt fallback (80 token output, prefix đã cache):
~30 token prefill câu người dùng + 80/63 s ≈ **1,3–1,5 s** — dưới cả cổng primary cũ
2,5 s của SPIKE-001. Số thật chờ bậc B/C.

## Bậc B — grammar + prompt cache (vulkan + 3B)

| Tổ hợp | decode tok/s | total p50 | total p95 | truncated |
|---|---:|---:|---:|---:|
| bare (mốc, = bậc A) | 63,3 | 2.644 ms | 2.660 ms | 0 |
| grammar | 48,5 | 1.382 ms | 1.836 ms | 0 |
| cache (few-shot, không grammar) | 61,8 | 2.708 ms | 2.731 ms | 0 |
| **full (grammar + few-shot)** | 59,9 | **877 ms** | **1.000 ms** | 0 |

- **Grammar overhead**: −23% decode khi đứng một mình (48,5 so 63,3) — dưới ngưỡng
  dừng 30%; trong tổ hợp full chỉ còn −5%. Và grammar làm output **dừng đúng chỗ**
  (predicted_n 24–51 thay vì lan man đủ 160), nên tổng thời gian *giảm* dù decode
  chậm hơn một chút.
- **Cache ăn prefix thật**: cold prefill 378 token = 2.058 ms, trả đúng một lần;
  các call sau chỉ prefill 8–12 token câu người dùng (~120–150 ms). Few-shot vì thế
  gần như miễn phí đúng như thiết kế đặt cược.
- Truncation = 0 trên cả bốn tổ hợp.

**Kết quả bậc B: lượt fallback end-to-end p50 877 ms / p95 1.000 ms** — dưới cả cổng
primary cũ của SPIKE-001 (2.500/4.500 ms), bằng một phần mười hai số đo cũ 11,2 s.

## Bậc C — chất lượng trên bộ dò (PROBE-NOT-EVIDENCE)

Bộ dò 64 case (`eval/datasets/probe/v1`). Grammar + few-shot, vulkan, n_predict 160.

| Model / prompt | kind_acc | tool_acc (plan) | parse_fail | p50 | p95 | Run |
|---|---:|---:|---:|---:|---:|---|
| 3B, few-shot v1 (4 ví dụ) | 0,812 | 0,714 | 2 | 992 ms | 2.173 ms | `…121701` |
| **3B, few-shot v2 (7 ví dụ)** | **0,906** | **0,828** | **0** | **992 ms** | **1.219 ms** | `…121908` |
| 0.5B, few-shot v2 | 0,875 | **0,345** | 0 | 382 ms | 730 ms | `…122044` |

- Vòng 1 → 2 (được phép tối đa 2 vòng chỉnh prompt): lỗi cụm ở nhóm OOS (8/10 bị
  nhận nhầm thành plan — few-shot chưa có ví dụ từ chối việc ngoài xe) và
  `media_control`. Thêm đúng 3 ví dụ nhắm hai cụm đó: kind 0,812→0,906, tool
  0,714→0,828, parse_fail 2→0. Prefix lớn thêm ~120 token — cache trả, không đổi p50.
- **0.5B đạt kind nhưng trượt thảm tool (0,345)** — đúng vết SPIKE-001 (15% tool
  exact). 0.5B chỉ đủ cho vai trò ③ (chitchat), không đủ cho planner.
- 6 miss còn lại của 3B đa số là câu thông tục thật sự mơ hồ ("bí bách quá" →
  hvac_power hay window?). Đây là trần của few-shot trên bộ dò; số thật chờ dữ
  liệu người dùng.
- Ca thoái hoá đã gặp ở v1: "kể chuyện cười" → lặp ký tự CJK tới trần token
  (grammar giữ vỏ JSON nhưng không cứu nội dung). Hết ở v2 nhưng phải ghi vào
  ADR-016 như failure mode đã quan sát.

**Kết quả bậc C: 3B vượt cả hai ngưỡng (kind ≥ 0,85; tool ≥ 0,70) ở vòng prompt
thứ 2/2.** Không kích hoạt tiêu chí dừng.

## Bậc D — RAM đồng thời

Tình huống: llama-server (3B, vulkan) + backend `src.serve` (MQTT off, RAG/e5 warm).

| Tiến trình | Peak RSS |
|---|---:|
| llama-server (đỉnh lúc **nạp** model; runtime trọng số nằm VRAM, RSS tụt về ~26 MB khi bị nén) | 2.520 MB |
| backend python (faiss + e5 warm) | 565 MB |
| **Tổng tiến trình spike** | **~3,1 GB** |

- **Giới hạn đo, ghi thẳng:** model STT không có trên máy này (`models/voice/
  phowhisper-base-ct2` chưa tải) nên phép đo **thiếu STT**. Tham chiếu trần: SPIKE-001
  đo PhoWhisper-small peak 1.602,9 MiB (run `20260730T100312.454360Z`); bản product
  dùng phowhisper-base-ct2 int8, kỳ vọng nhỏ hơn. Tổng ước cả STT: ~3,7–4,7 GB đỉnh.
- Lúc đo máy còn trống 166 MB (app khác của người dùng đang chạy) — không tiến trình
  nào sập; Windows nén/page llama-server sau khi trọng số đã sang VRAM.
- Hai bài học đo trên Windows, trả giá thật mới thấy: (1) `python.exe` của venv là
  **launcher** spawn interpreter con — đo theo PID cha ra 4 MB ảo; (2) spawn hidden
  thiếu `PYTHONIOENCODING=utf-8` thì log tiếng Việt giết backend ngay lúc warm.

**Kết quả bậc D: không kích hoạt tiêu chí dừng.** Khuyến nghị vận hành: llama-server
nạp model **trước** khi backend warm STT để hai đỉnh nạp không chồng nhau; đo lại có
STT khi model được tải về.

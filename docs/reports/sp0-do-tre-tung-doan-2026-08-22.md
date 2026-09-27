# SP-0 — Đo độ trễ từng đoạn trên máy demo (spike, 2026-08-22)

- Người đo: Nhân. Máy: Windows 11, dGPU Radeon RX 5500M 4 GB (Vulkan0), iGPU AMD Radeon
  Graphics (Vulkan1). Model: Qwen3-4B-Instruct-2507-Q4_K_M, llama-server `tools/llama-vulkan`.
- Câu hỏi spike: *một lượt đi qua SLM tốn bao nhiêu ở từng đoạn, để đặt cổng p50/p95 thật
  thay cho 2,5 s / 4,5 s chưa ai đo.*
- Bằng chứng: `eval/results/do-tre/20260822T030757.814951Z` (thí nghiệm 1, qua graph thật,
  75 lượt, 5 nhóm) và `eval/results/do-tre/20260822T031746.392812Z` (thí nghiệm 2, chi phí
  đổi vai và phương án tách vai). Spike không giữ code; script đo nằm ngoài repo.
- Phát hiện ngoài lề nhưng nặng nhất: script đo là thứ đầu tiên truyền `trace_id` qua
  node `slm_classify` và phơi ra **lỗi P0 của #232** (mọi lượt API thật qua classifier nổ
  `ValueError` vì stage trace lạ) — sửa ở PR #242. Thí nghiệm 1 chạy trên nhánh hotfix đó.

## 1. Kết quả thí nghiệm 1 — qua graph thật (ms)

Cờ: `SLM_ENABLED=true`, `TOM_TAT_ENABLED=true`, `CHON_CAU_THAC_ENABLED=true`. Xe in-process
(không MQTT). `e2e` **chưa gồm** STT/TTS — đo riêng ở §1.2. Một llama-server 8093 phục vụ
cả ba vai (classify / planner / tóm tắt).

| nhóm (15 lượt/nhóm) | e2e p50 | e2e p95 | routing p50 | routing p95 | retrieval p50 | ghi chú |
|---|---:|---:|---:|---:|---:|---|
| A. lệnh khớp luật | **4** | 1 634 | 0,1 | 656 | — | đường tắt đúng như thiết kế; p95 là một ca rơi sang SLM |
| B. lệnh nói tự nhiên → classify → planner | 3 716 | 9 709 | 705 | 2 262 | 3 038 (planner) | planner p95 **8 975**; 5/15 lượt classify **timeout** |
| C. câu hỏi sổ tay khớp luật → RAG → tóm tắt | 1 380 | 5 717 | 0 | 1 | 24 | phần còn lại là tóm tắt |
| D. câu lạ → classify → RAG | 2 041 | 6 426 | 682 | 2 269 | 24 | 3/15 classify timeout |
| E. chitchat → classify → câu giữ chỗ | 698 | 7 718 | 691 | 1 186 | — | 4/15 bị **router luật** bắt thành `manual_question` trước khi tới classifier |

`routing` ở B/D/E là thời gian classify (PR #242 tính nó vào stage này).

### 1.1 Tách từng đoạn

| đoạn | p50 | p95 | max | nguồn |
|---|---:|---:|---:|---|
| router luật | 0,1 | 1 | — | stage `routing` nhóm A/C |
| retrieval (FAISS + E5 ấm + cross-encoder) | 24 | 42 | 49 | stage `planning_or_retrieval` nhóm C/D |
| classify — đứng một mình, cùng prefix | **410** | 424 | — | thí nghiệm 2 |
| classify — xen kẽ với planner trên cùng server | **3 050** | 3 068 | — | thí nghiệm 2 |
| classify — trong graph (timeout 2 s) | 662 | 717 | 720 (đo lẻ) / **timeout 9/41** (trong graph) | |
| planner (union prompt ~800 token) — xen kẽ | 3 038 | 8 975 | 13 938 | nhóm B |
| tóm tắt (`compose`, `TOM_TAT_ENABLED`) | **1 630** | **8 534** | **12 167** | e2e − routing − retrieval, 18 lượt `grounded_answer` |
| sinh chitchat (union prompt, `kind: chitchat`) | 1 071 | 2 242 | 4 238 | 15 câu, gọi trực tiếp |
| STT Zipformer (WAV 1,9 s p50) | 53 | 1 033 | 1 831 | 10 WAV `poc/v1`; p95 là lượt đầu nạp model |
| TTS Piper (10–36 ký tự) | 51 | — | — | 7 câu; câu 126 ký tự: 2 276 (gồm nạp model lần đầu) |

### 1.2 Ba con số khiến tôi dừng lại

1. **Classify timeout 9/41 lượt (22%)** → fail-safe về manual. Đứng một mình classify 410 ms,
   nhưng *ngay sau* một lượt planner hay tóm tắt nó tốn ~3 050 ms. Timeout 2 s đang đánh
   trượt đúng lớp lượt mà classifier sinh ra để cứu.
2. **Tóm tắt là đuôi dài của câu trả lời sổ tay**: p50 1,6 s chấp nhận được, nhưng p95 8,5 s
   và max 12,2 s ("Cách khởi tạo lại cửa sổ điện?"). Không có cổng p95 ≤ 4,5 s nào qua được
   khi còn đuôi này.
3. **4/15 câu chitchat không bao giờ tới classifier**: "Xin chào, hôm nay khỏe không?", "Cậu tên
   gì thế?" bị luật `manual_question` (dấu hỏi / "gì") bắt trước và trả `grounded_refusal`.
   Đây là việc của SP-2, ghi ở đây để không quên.

## 2. Thí nghiệm 2 — chi phí ĐỔI VAI và phương án tách vai

Gọi thẳng `/completion` với đúng body của `QwenClassifier`/`QwenPlanner`, timeout nới rộng
để thấy số thật. Mỗi ô là ms của từng lần gọi, đúng thứ tự đã chạy.

| cấu hình | classify | planner | chính xác `dinh-tuyen-v1` |
|---|---|---|---|
| A. một server, 4 slot mặc định, xen kẽ | 3 023 · 3 068 · 3 055 (nóng cùng prefix: 419 · 424 · 415) | 3 935 · 4 549 · 4 696 · 4 589 | 59/61 (run `…134426`) |
| B. một server, **ghim `id_slot`** (classify→0, planner→1), vòng 2 cache nóng | 1 891 · 1 866 · 1 903 · 1 888 | 2 654 · 3 161 · 3 256 · 3 100 | (không đổi model) |
| C. **hai server**: 3B trên iGPU làm classify, 4B trên dGPU làm planner | 1 220 · 1 225 · 1 229 | **1 224 · 1 562 · 1 612** | **54/61, `manual→control` = 3 — HỎNG cổng** |
| D. **hai server**: 4B trên iGPU làm classify, 4B trên dGPU làm planner | 1 576 · 1 607 · 1 565 · 1 594 | **1 122 · 1 527 · 1 627 · 1 462** | **59/61, cổng = 0** (run `20260822T031650.116024Z`) |

Đọc bảng:

- Chi phí không nằm ở prefill (300 token @ 350 tok/s ≈ 0,9 s) mà ở **chuyển slot trên Vulkan**:
  ghim slot + cache nóng vẫn 1,9 s, tức KV-cache bị nạp/ghi lại mỗi lần đổi vai.
- Tách vai sang GPU thứ hai lợi **cả hai chiều**: classify ổn định 1,6 s, và planner trên dGPU
  rớt từ 3–4,7 s xuống **1,1–1,6 s** vì không còn phải nhường chỗ. Cấu hình D là cấu hình
  duy nhất vừa giữ cổng vừa bỏ được timeout.
- Model 3B làm classify **không dùng được** dù nhanh hơn: prompt v3 tinh cho 4B, 3B mở lại ô
  `manual→control` = 3.

## 3. Đề xuất (để SP-1 vận hành và SP-2/SP-3 đặt cổng)

1. **Máy demo chạy hai llama-server**: 8093 (dGPU) cho planner + tóm tắt + chitchat, 8094 (iGPU)
   cho classify. Cần một biến cấu hình `SLM_CLASSIFY_ENDPOINT` (mặc định = `SLM_ENDPOINT`,
   tức một server vẫn là mặc định hợp lệ). Runbook ghi rõ đây là cấu hình **của máy này**;
   máy một GPU thì dùng ghim `id_slot` (cấu hình B) và chấp nhận classify ~1,9 s.
2. **`SLM_CLASSIFY_TIMEOUT_S` 2,0 → 3,5 s.** Với một server, 2 s đánh trượt 22%; với hai
   server p95 1,74 s chỉ còn biên 15%. 3,5 s vẫn dưới mọi cổng đề xuất dưới đây.
3. **Cổng theo làn, không một con số chung** (p50 / p95, chưa gồm STT+TTS ≈ +0,1 s ấm):

| làn | đo được (cấu hình D, ước từ §2) | đề xuất cổng |
|---|---|---|
| lệnh khớp luật | 4 ms | ≤ 50 ms / ≤ 200 ms |
| lệnh nói tự nhiên (classify + planner) | ≈ 3,1 s | ≤ 3,5 s / ≤ 5 s |
| câu hỏi sổ tay (retrieval + tóm tắt) | 1,6 s / **8,5 s** | ≤ 2 s / ≤ 4,5 s — **chưa đạt**, là việc của SP-3 (đuôi tóm tắt) |
| chitchat (classify + sinh) | ≈ 2,7 s | ≤ 3 s / ≤ 4,5 s — đặt khi SP-2 có số |

   Cổng p95 4,5 s toàn cục của docs cũ **giữ làm đích**, nhưng chỉ có nghĩa sau khi SP-3 cắt
   đuôi tóm tắt; đặt nó làm cổng CI hôm nay là đặt một cổng biết trước sẽ đỏ.
4. **Đo lại sau khi có MQTT thật**: stage `tool` ở đây là 0,2 ms vì xe in-process; lượt S1
   thật cộng thêm round-trip broker (L3 đo riêng).

## 4. Giới hạn của phép đo

- Một máy, một buổi, n = 15/nhóm; không phải phân bố ổn định, đủ để đặt cổng sơ bộ.
- STT/TTS đo trên WAV tổng hợp và câu ngắn; lượt đầu gồm nạp model.
- Thí nghiệm 2 gọi thẳng endpoint, không qua graph — số classify/planner ở đó thiếu vài
  ms overhead của LangGraph, không đổi kết luận.

# ADR-016: Cổng chấp nhận cho đường SLM fallback (planner + trò chuyện)

- Status: **Accepted** (2026-08-12, sau review của Thành ở PR #71: điểm "wrong-tool S1
  không bị chặn" đã được sửa wording và ghi thành rủi ro tồn đọng nhóm chấp nhận).
- Date: 2026-08-11, sửa 2026-08-12
- Decision owner: WS2 Agent & Safety (Nhân)
- Liên quan: ADR-005 (Not Yet — không bị đảo, xem dưới), ADR-006 (routing ưu tiên
  luật), ADR-015 (composer — quyết định riêng, không thuộc ADR này),
  `docs/reports/SPIKE-003-slm-feasibility.md`.

## Context

SPIKE-003 đo trên máy demo: lượt SLM fallback (Qwen2.5-3B Q4, Vulkan trên RX 5500M,
grammar hợp nhất, prompt cache) đạt p50 992 ms / p95 1.219 ms; kind-accuracy 0,906 và
tool-accuracy 0,828 trên bộ dò (nhãn PROBE-NOT-EVIDENCE); parse_fail 0/64.

Cổng cũ của SPIKE-001 (p50 ≤ 2,5 s, tool exact ≥ 90%, schema 100%) đặt cho một planner
**chính** chạy mọi lượt. Đường bây giờ là **fallback**: chỉ chạy khi luật đã bó tay,
và lựa chọn thay thế của nó không phải "luật trả lời nhanh hơn" mà là **"tôi chưa hiểu,
nói lại giúp tôi"**. Vì vậy cổng phải đặt lại, có chủ đích, chứ không tái dùng hay
tự nới.

ADR này **không đảo ADR-005**: không chọn model production nào. Nó chỉ đặt điều kiện
để bật một đường fallback trên bản demo PC, với model học thuật hiện có.

## Đề xuất cổng — điền bằng số đo, nhóm chốt

| Chiều | Cổng đề xuất | Số đo được | Căn cứ |
|---|---|---|---|
| Độ trễ lượt fallback | p50 ≤ 1.500 ms; p95 ≤ 2.500 ms | 992 / 1.219 ms | Headroom ~50% cho máy nóng, VRAM bận |
| Vỏ output | parse_fail + truncation ≤ 2% | 0/64 | Grammar theo kiến tạo, `n_predict` đủ |
| kind-accuracy (bộ dò) | ≥ 0,85 | 0,906 | Nhận nhầm chitchat→plan chỉ tốn một lượt clarify vì cổng an toàn vẫn chặn; nhận nhầm plan→chitchat mất một lệnh — cân bằng ở 0,85 |
| tool-accuracy (bộ dò, nhóm plan) | ≥ 0,70 | 0,828 | Chọn sai tool **sang S2/S3 thì bị chặn**, sang S1 thì **không** — xem "Rủi ro tồn đọng"; 0,70 là sàn để tính năng còn hữu ích |
| RAM đồng thời | Treo — đo lại khi có model STT | ~3,1 GB thiếu STT | Không gate bằng số ước |

Hai cổng chất lượng dùng bộ dò nên là **cổng hồi quy** (không được tụt khi sửa
prompt/model), không phải claim năng lực. Cổng năng lực thật đặt lại khi có dữ liệu
người dùng thử.

## Máy demo và tính di động — chốt 2026-08-11

- **Máy demo chính thức là máy của Nhân** (chủ phần agent; RX 5500M — cấu hình mà mọi
  số trong ADR này được đo). Mọi claim độ trễ chỉ có nghĩa trên máy đó.
- **Máy khác không cần gì cả để chạy sản phẩm.** SLM là fallback sau cờ
  `slm_enabled=False` mặc định: backend của Thành/Sơn/Giáp chạy y nguyên, câu lạ rơi
  về "clarify" như hôm nay. Không cần model, không cần GPU, không cần llama-server.
- Máy khác **muốn bật** SLM thì tự chạy lại bậc A của SPIKE-003 trước
  (`scripts/spike3_server.ps1` + `spike3_bench.py`, một buổi) để biết mình thuộc tầng
  nào: dGPU ≥ 4 GB → tương đương; chỉ iGPU → decode rơi gần mức CPU (cái 6,8× đến từ
  băng thông GDDR6); CPU thuần → 3B không dùng được (9,3 tok/s đo thật), 0.5B chỉ đủ
  vai trò trò chuyện.
- Hai hardcode của spike **phải sửa khi Phase 2 tích hợp**, không được mang vào
  `src/`: `--device Vulkan1` (số thứ tự thiết bị là của riêng máy đo — máy khác
  enumerate khác, có thể rơi vào iGPU không ai biết) và `-t 6` (giả định 6 nhân) —
  cả hai phải thành config/tự dò.
  **Cảnh báo này đã thành hiện thực ngay trên chính máy đo** — xem mục dưới.

## Tầng iGPU — đo 2026-08-13

Cảnh báo về `--device Vulkan1` ở trên không chỉ đúng với máy khác: **thứ tự thiết bị
đổi ngay trên máy Nhân.** Ngày 13/08 `--list-devices` trả về `Vulkan0 = RX 5500M`,
`Vulkan1 = AMD Radeon(TM) Graphics` — **ngược** với chú thích "Vulkan1 = RX 5500M"
ghi cứng trong `spike3_server.ps1`. Số thứ tự Vulkan không ổn định giữa các lần
boot/driver, nên mỗi con số gắn nhãn "dGPU" trước ngày này **về nguyên tắc không tự
chứng minh được**.

Đã dựng lại bằng đo chứ không bằng lập luận: chạy lại đúng bậc C (0.5B + grammar +
prompt cache, 64 case) trên thiết bị **dò theo tên**, dGPU cho 156,3 tok/s và
p50 317 ms — tái hiện 146,7 tok/s / 382 ms của run cũ. **Nhãn cũ đúng**; cái sai là
nó không kiểm chứng được, và giờ đã sửa: `spike3_server.ps1` nhận tên thiết bị, đối
khớp đúng một, ghi tên đã resolve ra `device-last.json`, và `spike3_bench.py` đưa
thẳng `device_name` vào manifest. Nhãn do máy điền, không do người gõ.

Ba tầng, **cùng một cấu hình** (0.5B q4_k_m, grammar, `--cache-reuse 256`, 64 case):

| tầng | thiết bị | decode | p50 | p95 | prefill (pp512) |
|---|---|---:|---:|---:|---:|
| dGPU | Radeon RX 5500M | 156,3 tok/s | 317 ms | 496 ms | 2.875 tok/s |
| CPU | 6 luồng | 44,7 tok/s | 1.135 ms | 1.616 ms | 1.625 tok/s |
| iGPU | AMD Radeon(TM) Graphics | 41,1 tok/s | 1.211 ms | 1.814 ms | 752 tok/s |

Run: `eval/results/spike-003/20260813T155213.050504Z` (dGPU),
`20260813T155259.092007Z` (CPU), `20260813T155032.836813Z` (iGPU).
Prefill đo riêng bằng `llama-bench -p 512 -n 0` vì `--cache-reuse` che mất prefill
trong bench server (chỉ còn phần đuôi mới, nên `prompt_n` quá nhỏ để có nghĩa).

**Kết quả vượt cả dự đoán, theo hướng xấu: iGPU không "rơi gần mức CPU" — nó *thua*
CPU.** Chậm hơn 7% ở decode và **2,2× ở prefill**. Đưa model lên iGPU của máy này là
lỗ vốn so với để nguyên trên CPU.

Cơ chế thì `llama-bench` nói thẳng: iGPU báo `uma: 1` (dùng chung băng thông bộ nhớ
với CPU — không có GDDR6 riêng, đúng cái 6,8× mà ADR này quy cho băng thông),
`int dot: 0` và `matrix cores: none`, trong khi dGPU có `int dot: 1`. Thiếu int-dot
đánh thẳng vào nhân q4_k_m.

Kiểm chứng rằng run iGPU thật sự chạy trên iGPU chứ không âm thầm rơi về CPU (số quá
gần CPU nên bắt buộc phải loại trừ): `llama-bench --device Vulkan1 -ngl 99` cho
38,08 t/s, khớp với 41,1 tok/s của run server, và tự in ra dòng nhận diện thiết bị.
Log server **không** chứng minh được điều này — nó chỉ bắt stderr ở verbosity 3;
đã sửa để bắt cả stdout, nhưng phép kiểm dứt điểm là `llama-bench`.

**Điều bảng này *chưa* trả lời:** bậc C là bài **lập kế hoạch** (nhồi prompt ngắn, nhả
160 token). Bài của S2 ngược lại — nhồi cả danh sách câu (~600–1.000 token) rồi nhả
~15 token chỉ số. Nên bảng trên **ước** S2 ≈ 0,4 s (dGPU) / 0,8 s (CPU) / 1,5 s
(iGPU), và chữ "ước" là thật: chưa có run nào hình dạng S2. Đo nó là việc của Task 9,
đừng trích ba con số ước này như đã đo.

## Điều kiện vận hành đi kèm (nếu duyệt)

1. `slm_enabled` **giữ mặc định `False`** cho tới khi nhóm duyệt ADR này; bật qua config.
   Đây đồng thời là cơ chế di động: máy không đủ sức thì để nguyên off, không mất gì.
2. llama-server là tiến trình resident, khởi động **trước** backend (hai đỉnh nạp không
   chồng nhau), flags pin trong script: `--device Vulkan1` (máy có 2 thiết bị Vulkan,
   mặc định có thể rơi vào iGPU), `--cache-reuse 256`, grammar hợp nhất.
3. `/healthz`: `llm` **giữ miễn trừ** (issue #48). Bật SLM không đổi điều đó — fallback
   hỏng thì hệ thống quay về "clarify", không phải sự cố hạ tầng.
4. Nhánh `chitchat` không chạm executor (kiến trúc, đã cố định trong thiết kế ba vai
   trò); reply bị chặn trần độ dài; prompt cấm "nói như đã làm".
5. License: Qwen2.5-3B là **Qwen Research** — demo học thuật OK, mọi tài liệu nhắc tới
   phải kèm ghi chú; lộ trình sạch license là ứng viên Apache-2.0 đo lại bằng đúng bậc
   thang SPIKE-003.

## Rủi ro tồn đọng

- **Chọn nhầm tool sang nhóm S1 thì không có gì chặn — nhóm chấp nhận cho demo.**
  Đây là điểm Thành nêu khi review PR #71 (2026-08-12) và nó đúng. Cụ thể:
  `validate` chỉ kiểm schema và miền tham số, `safety` chỉ phân loại S0–S3, và
  **S1 thực thi thẳng, không qua HITL**. Một plan chọn nhầm sang tool S1 nhưng hợp
  schema, hợp tham số thì **không cổng nào chặn**. Với `tool_acc = 0,828` trên bộ dò,
  đó là khoảng **1 trong 6** plan chọn sai; phần rơi vào S1 sẽ chạy im lặng.

  Năm tool S1 (`src/agents/policy.py`) và hậu quả thật khi chọn nhầm — liệt kê ra để
  cái nhóm chấp nhận là cái cụ thể, không phải một câu chữ:

  | Tool | Hậu quả nếu SLM chọn nhầm |
  |---|---|
  | `set_hvac_temperature`, `set_hvac_power` | sai nhiệt độ / tắt bật điều hòa — khó chịu, tài xế sửa lại ngay |
  | `set_navigation` | dẫn đường sai đích — tài xế thấy ngay trên màn hình |
  | `media_control` (`set_volume`) | âm lượng nhảy đột ngột khi đang lái — **có thể gây giật mình** |
  | `set_seat_heating` | bật/tăng sưởi ghế ngoài ý muốn. Chính sổ tay VF9 cảnh báo: *"Những người không thể cảm nhận được nhiệt độ hoặc có da nhạy cảm nên hết sức thận trọng… sử dụng ghế sưởi lâu có thể gây bỏng da."* |

  **Quyết định (Nhân, decision owner, 2026-08-12, sau đề nghị của Thành): chấp nhận
  rủi ro này cho demo học thuật**, không dựng cổng thêm. Căn cứ: đây là simulator, không
  có xe thật; `slm_enabled=False` **mặc định** nên đường mặc định không chạm SLM; và mọi
  lệnh đều hiện trên IVI nên tài xế sửa lại được ngay.

  **Phương án đã cân nhắc và không chọn, ghi lại để khỏi nghĩ lại:** cho plan có
  `route_source == "slm"` phân loại S1 đi qua HITL thay vì thực thi thẳng (dùng lại
  nguyên máy móc approval đã có, vài dòng). Không chọn vì cái giá — thêm một nhịp xác
  nhận cho mọi lệnh đi đường SLM — không tương xứng với mức hậu quả của năm tool trên
  trong bối cảnh mô phỏng. **Mở lại nếu** hệ thống chạm phần cứng thật, hoặc nếu nhóm
  thêm tool S1 có hậu quả nặng hơn bảng trên.

  > **ĐÃ ĐẢO 2026-08-15 — xem [ADR-021](ADR-021-provenance-confirmation-gate.md).**
  >
  > Không điều kiện mở lại nào ở trên xảy ra. Thứ làm đổi quyết định là issue #144:
  > ca dự đoán trong bảng ngay trên (`media_control` chọn nhầm) **đã xảy ra thật** trên
  > nhánh SLM, và khi đi đo thì cái giá hoá ra nhỏ hơn hẳn chữ "mọi lệnh" ở đây gợi ra
  > — 8/136 lượt trong hai dataset hiện có.
  >
  > Phân tích rủi ro của mục này **đúng**; chỗ hỏng là tôi cân một rủi ro đã lượng hoá
  > (`tool_acc = 0,828`) với một chi phí chỉ ước bằng chữ.

- **Bóp méo lựa chọn tool** ngoài bộ dò — bộ dò nhiễm tri thức router, không đo được
  tổng quát hóa. Giảm thiểu: cổng an toàn tất định chặn được nhóm S2/S3 (xem giới hạn
  ngay trên) — và **từ ADR-021**, plan do SLM đề xuất phải qua xác nhận kể cả khi nó là
  S1. Đọc câu này ở bản trước mà không đọc "giới hạn ngay trên" thì rất dễ yên tâm quá
  mức: cổng S2/S3 **không** chặn được lệnh S1 sai ngữ nghĩa, và issue #144 là ca thật.
- **Thoái hoá sinh chuỗi** (đã quan sát ở few-shot v1: lặp CJK tới trần token). Grammar
  giữ vỏ, không giữ nội dung. Giảm thiểu: trần `n_predict`, theo dõi parse_fail.
- **Chitchat nói như đã làm** — chưa có chặn tất định; nếu quan sát thấy trong thực tế
  thì thêm bộ lọc mẫu câu trước TTS.

## Cần nhóm chốt — cập nhật 2026-08-11 (cả ba đã chốt, chờ nhóm phản biện khi review)

1. ~~Ngân sách chờ 1,5 s p50~~ — **Chốt: chấp nhận** (Nhân, decision owner,
   2026-08-11; nhóm phản đối thì nêu khi review ADR).
2. ~~Bật cả hai loại output cùng lúc hay `chitchat` trước~~ — **Chốt: (a) bật cả
   hai cùng lúc** (Nhân, 2026-08-11). Lý do ghi lại: nhánh `plan` **có lưới đỡ tất
   định** phía sau (`validate → safety → HITL`) trong khi `chitchat` — nhánh được
   bật ngay trong cả hai phương án — thì không có lưới nào. Giữ `plan` tắt thêm một
   nhịp chỉ trả giá: câu nói lệch khuôn tiếp tục bị "tôi chưa hiểu" dù model đoán
   đúng 0,828 trên bộ dò.

   **Sửa 2026-08-12 (Thành nêu khi review PR #71 — đúng).** Bản đầu của mục này viết
   *"chọn sai tool thì tệ nhất là tài xế thấy một thẻ xác nhận sai và bấm Từ chối"*.
   Câu đó **sai** và đã bị gỡ: lưới chỉ đỡ tới S2/S3, còn S1 thì thực thi thẳng.
   Xem mục "Rủi ro tồn đọng" ngay dưới. Lựa chọn (a) vẫn giữ, nhưng giữ với lý do
   đúng chứ không phải lý do đã viết.
3. ~~License~~ — **Chốt: dùng Qwen Research cho demo học thuật** (Nhân, 2026-08-11),
   kèm ghi chú license ở mọi tài liệu nhắc tới; Apache-2.0 là lộ trình nếu khả thi,
   không chặn việc bật.

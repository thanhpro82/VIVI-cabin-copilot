# ADR-022: RAG thôi phủ quyết planner; kết quả quyết định, không phải điểm số

- Status: Accepted
- Date: 2026-08-15
- Decision owner: Nhân
- Phụ thuộc: [ADR-021](ADR-021-provenance-confirmation-gate.md) — **điều kiện cần**, xem mục Consequences
- Thu hẹp: [ADR-011](ADR-011-default-to-manual-lookup.md)
- Liên quan: [issue #149](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/149),
  [ADR-016](ADR-016-slm-fallback-gates.md)

## Context

`route_after_rag` chỉ rẽ sang planner khi tra sổ tay **đã thất bại**:

```python
planner is not None
and state.get("outcome") == "grounded_refusal"      # <- điều kiện này
and state.get("route_reason") == "default_to_manual"
```

Nên RAG có quyền phủ quyết, và nó chỉ cần vượt `RAG_MIN_SCORE = 0.848`. Thành đo
(issue #149): *"Nóng quá, giảm nhiệt độ xuống đi"* nhận lại đoạn **"Bảo dưỡng / Dầu mỡ,
phụ tùng bảo dưỡng"** ở **0,853** — hơn ngưỡng đúng **0,005**. Log không có dòng
`SLM attempt` nào: planner không được gọi.

Hệ quả nặng hơn một ca lẻ: sổ tay VF9 nói rất nhiều về làm mát, điều hoà, ghế — nên gần
như mọi câu tự nhiên chạm các miền đó đều lết qua ngưỡng và chặn planner. Cả một miền
chức năng biến mất khi bật SLM, và ai đo nhánh SLM sẽ kết luận nhầm là model kém.

## Ba phương án, và số liệu loại hai

### 1. Nâng ngưỡng, hoặc đòi khoảng cách tối thiểu — **bác**

Đo phân bố điểm top-1 (15/08, index `vf9_2026_vi`, embedder E5):

| nhóm | điểm |
|---|---|
| mệnh lệnh vượt ngưỡng | 0,853 · 0,863 · 0,876 · **0,885** |
| câu hỏi sổ tay thật (n=20) | **min 0,865** · p25 0,879 · p50 0,900 · max 0,924 |

**Hai phân bố chồng nhau.** `"Chỉnh ghế thoải mái hơn"` đạt 0,885 — cao hơn p25 của câu
hỏi thật, và cao hơn hẳn min 0,865. Nâng ngưỡng tới đó vứt khoảng một phần tư câu hỏi
hợp lệ.

Lý do sâu hơn con số: **điểm đo độ liên quan chủ đề, và "chỉnh ghế" thì đúng là liên
quan tới mục Ghế.** RAG không sai. Thứ khác nhau là **hành vi lời nói** — tài xế đang
*ra lệnh*, không *hỏi*. Một đại lượng đo chủ đề không thể tách được hai hành vi.

### 2. Dò dạng mệnh lệnh rồi rẽ sớm — **bác**

`_looks_imperative` có sẵn, nhưng nó bỏ sót **5/7** câu tự nhiên vì chỉ bắt động từ ở
**đầu** câu: `"Nóng quá, giảm nhiệt độ xuống đi"` trượt, `"Cho ghế ngả ra sau một chút"`
trượt.

Nó cũng bắt nhầm 5 câu hỏi sổ tay (*"Bật đèn sương mù thế nào?"*), nhưng **cái đó vô
hại**: cả 5 đều ra `manual_question` nên không bao giờ tới cổng SLM. Vấn đề chỉ là âm
tính giả — và 5/7 thì quá yếu để làm cổng.

### 3. Để **kết quả** quyết định — **chọn**

Bỏ điều kiện `grounded_refusal`. Với lượt `default_to_manual`:

1. Hỏi planner.
2. Ra plan hợp lệ → đi tiếp, và **qua cổng xác nhận của ADR-021**.
3. Không ra plan → **lui về câu trả lời sổ tay đã tính** (`_lui_ve_so_tay`).

Vế 3 là thứ giữ cho ADR-011 không bị phá: mặc-định-về-sổ-tay vẫn còn, nó chỉ thôi là
*câu trả lời đầu* và thành *phương án lui*. Bỏ vế ấy thì mọi câu planner không hiểu sẽ
ra `clarify` — đánh đổi một câu trả lời có ích lấy một câu hỏi lại.

Điều kiện `default_to_manual` **giữ nguyên**: câu đã nhận diện rõ là câu hỏi vẫn không
đưa cho SLM đoán, đúng lý do ADR-016 đặt nó.

## Tuần tự, không song song

Hai nguồn số, **đo bởi hai người trên hai máy khác nhau** — ghi tách ra vì lẫn chúng
vào nhau là đúng lớp lỗi mà kỷ luật evidence của repo tồn tại để chặn.

### Nguồn A — Nhân, 15/08, máy dev

| | |
|---|---|
| RAG ấm (E5 + FAISS, index `vf9_2026_vi`) | **23 ms** p50, n = 6 câu × 3 lần |
| planner **Qwen2.5-0.5B-Instruct q4_k_m** | **1.450 ms** p50, max 1.782 ms, n = 5 câu |
| phần cứng | AMD Radeon RX 5500M (dGPU, 4080 MiB), `--device Vulkan0` |
| cách đo | gọi thẳng `QwenPlanner.propose()`, server đã ấm một lượt |

**Không phải model đích.** Bản 3B **không nạp xong trong 120 giây** trên card 4 GB này,
nên 1.450 ms là **cận dưới**, không dùng thay cho số của model production.

### Nguồn B — Thành, [#145](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/145), máy kiểm chứng

| | |
|---|---|
| model | **Qwen2.5-3B q4_k_m**, `llama-server b10358` ([#144](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/144)) |
| phần cứng | NVIDIA GeForce RTX 3050 Laptop (dGPU, 3962 MiB) so với AMD Radeon tích hợp (8034 MiB dùng chung RAM) |
| cách đo | **end-to-end cả lượt**, server đã ấm |

| câu | iGPU | dGPU |
|---|---|---|
| `Tôi thấy hơi nóng, làm gì đó đi` | 8,17 s | **3,81 s** |
| `Xin chào cabin copilot` | 6,65 s | **3,59 s** |
| `Áp suất lốp khi lốp nguội…` | 4,62 s | **3,55 s** |

Lưu ý khi đọc: nguồn A đo **riêng lời gọi planner**, nguồn B đo **cả lượt**. Không trừ
được cho nhau để ra một con số chung, và tôi không thử.

Chạy song song tiết kiệm đúng phần RAG: **23 ms**, tức **1,6%** với planner nhanh nhất
và **0,3%** với 3B. Đổi lấy một nhánh chạy đồng thời trong graph và tính toán thừa.
Không đáng.

Tôi vào khảo sát với giả định RAG tốn "1–2 giây" và nghiêng về song song. Nó rẻ hơn
planner **hai bậc độ lớn**, và giả định ấy là thứ duy nhất chống đỡ cho phương án song
song.

**Ngân sách UX cho lượt đi qua planner.** Lấy theo nguồn B (model đích): **3,55–3,81 s**
trên dGPU, **4,62–8,17 s** trên iGPU. Tức chọn sai thiết bị có thể **hơn gấp đôi** thời
gian chờ — lý do [#145](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/145)
bỏ `-Device auto`. Con số này rơi vào **5,9%** số lượt (xem trên), và vượt xa mục tiêu
p95 ≤ 4.500 ms của `README.md` khi chạy trên iGPU — nên **nhánh SLM chỉ nên bật trên
máy đã chốt được thiết bị dGPU tường minh**.

## Consequences

**Cái giá:** thêm một lời gọi planner (1,5–8,2 s) cho lượt `default_to_manual`, tức
**8/136 = 5,9%** trên hai dataset hiện có. Trong đó có cả câu tán gẫu
(*"Hôm nay trời đẹp quá"*) — chúng cũng phải chờ. Đây là chi phí thật, và nó rơi vào
đúng nhóm lượt hiện đang trả lời sai.

**ADR-021 là điều kiện cần, không phải khuyến nghị.** Đo thật cho thấy planner sinh ra
một **plan** cho *"Công thức nấu phở bò truyền thống"* — không phải chitchat:

```
'Công thức nấu phở bò truyền thống'  ->  plan: search_nearby(query='phở bò truyền thống')
```

Ca này hiện vô hại vì `search_nearby` không có trong registry nên `validate` chặn. Nhưng
nó cho thấy planner sẵn sàng sinh plan cho bất cứ thứ gì, và một lần bịa trúng tên tool
thật thì mới là chuyện. Mở đường này mà chưa có cổng xác nhận là biến mỗi lượt planner
thêm thành một cơ hội chạy thẳng lệnh sai.

**Planner làm đúng việc khi được hỏi** — đây là điều biện minh cho cả thay đổi:

| câu | trước | sau |
|---|---|---|
| `Nóng quá, giảm nhiệt độ xuống đi` | trích "Bảo dưỡng / Dầu mỡ" | `set_hvac_temperature(20)`, hỏi xác nhận |
| `Cho ghế ngả ra sau một chút` | trích mục "Ghế" | `set_seat_position(rear, 30)`, hỏi xác nhận |

**`slm_enabled=False` vẫn mặc định**, nên P0 không đổi.

## Bài học ghi lại

Hai phương án đầu đều nghe hợp lý và cả hai đều chết vì **một phép đo mười phút**. Phân
bố điểm chồng nhau và bộ dò bỏ sót 5/7 — không lập luận nào từ nguyên lý cho ra được hai
sự thật ấy.

Và giả định về **chi phí** của tôi (RAG 1–2 s) sai hai bậc độ lớn, đúng như giả định về
chi phí trong ADR-016 đã sai. Hai lần liên tiếp, cùng một kiểu: ước lượng bằng chữ cho
vế mình không muốn đo.

# S2 (SLM chọn câu) + định hướng NPU — kế hoạch giai đoạn 2

> **Cho người thực thi:** dùng `superpowers:executing-plans`, làm từng task một.
> Tiếp nối `2026-08-13-speak-text-an-toan-cho-nhanh-so-tay.md` (Task 1–5 đã xong).

**Mục tiêu:** làm câu nói **trúng câu hỏi** hơn, và đặt nền để phần suy luận chạy được
trên phần cứng giống xe thật — mà không nới một milimet nào lớp an toàn đã đo được.

**Kiến trúc:** S1 (luật, không model) giữ nguyên vai trò **cổng an toàn**. S2 chỉ vào
được nhánh mà S1 đã tuyên bố an toàn, và đầu ra của nó phải là **tập con nguyên văn**
kiểm được bằng máy. NPU không phải việc của giai đoạn này; việc của giai đoạn này là
**không tự khoá đường** tới nó.

## Bối cảnh đã chốt (2026-08-13)

Ba điều đổi so với kế hoạch giai đoạn 1, đều đến từ tranh luận với Nhân:

1. **"Edge = CPU" là cách đọc sai `product_brief.md:135`.** Dòng đó ghi *"Không có
   Jetson; CPU profile trong Docker là baseline edge mô phỏng"* — nằm trong mục **ràng
   buộc của nhóm**, tức là *chúng ta không có phần cứng*, không phải *xe chỉ có CPU*.
   Cockpit SoC đời nay (Orin, Snapdragon Cockpit, Jacinto, R-Car) đều có bộ tăng tốc.
2. **dGPU cũng không phải xe.** RX 5500M là GPU laptop, GDDR6, không có trần công
   suất/nhiệt của xe. Tầng gần cockpit phổ thông nhất trong ba tầng ADR-016 là **iGPU**
   — nó chia sẻ băng thông bộ nhớ với CPU, đúng như SoC tích hợp.
3. **Bỏ nhãn "edge" một chữ.** Mọi số từ nay phải đi kèm **tầng phần cứng** đã đo.

## Dữ kiện kỹ thuật quyết định hướng NPU

Kiểm ngày 13/08 trên máy Nhân:

```
onnxruntime 1.28.0 — providers: ['AzureExecutionProvider', 'CPUExecutionProvider']
```

| Thành phần | Runtime hôm nay | Chạy trên | Đường tới NPU |
|---|---|---|---|
| STT Zipformer | onnxruntime | **CPU EP** | ✅ ONNX — đổi execution provider là xong |
| TTS Piper | onnxruntime | **CPU EP** | ✅ ONNX |
| SLM Qwen | llama-server / GGUF (HTTP) | Vulkan | ❌ **không phải ONNX** |

Hai điều rút ra, và cả hai đều đổi ưu tiên:

- **Đường giọng nói đã đạt yêu cầu trên CPU thuần**: STT 37–64 ms/câu, TTS 0,09× thời
  gian thực. Nó không cần GPU, cũng không cần NPU. Cộng với S1 (luật, không model),
  **toàn bộ phần an toàn của sản phẩm chạy được trên baseline CPU** — đó là claim mạnh
  nhất ta đang có, và nó đã có số.
- **Chỉ SLM lệch khỏi đường ONNX.** Nếu NPU là hướng, thì lựa chọn runtime cho S2 quan
  trọng hơn lựa chọn model: GGUF/llama.cpp là đường desktop, không phải đường NPU.

## Ràng buộc toàn cục

- **S1 vẫn là cổng.** S2 không bao giờ được chạy trên đoạn `has_variant_condition`.
- **Mọi câu S2 nói ra phải xuất hiện y nguyên trong đoạn nguồn** — kiểm bằng so chuỗi,
  không bằng niềm tin.
- **`slm_enabled=False` vẫn phải chạy đầy đủ.** S2 hỏng/tắt/timeout → rơi về S1.
- **Không thêm phụ thuộc mới** cho Task 6–8. Task 9 chỉ khảo sát, không cài gì.
- Mọi run eval phải ghi **tầng phần cứng**; không còn nhãn "edge" trần.

---

## Task 6 — Nhãn tầng phần cứng trong mọi run eval ✅

Làm **trước** S2, vì không có nó thì số của S2 không diễn giải được.

**Files:**
- Modify: `src/rag/evaluate.py` (`EvalMetrics`), `src/rag/cli.py` (`_cmd_eval`)
- Test: `tests/test_rag/test_evaluate.py`

- [x] **Bước 1: test đỏ**

```python
def test_metrics_ghi_tang_phan_cung():
    """Số không có tầng phần cứng là số không diễn giải được: 877 ms trên dGPU và
    17.441 ms trên CPU đều là "một lượt SLM"."""
    m = EvalMetrics(min_score=0.8, min_overlap=0.6, hardware_tier="cpu")
    assert m.hardware_tier == "cpu"
```

- [x] **Bước 2: cài đặt** — thêm `hardware_tier: str = "cpu"` vào `EvalMetrics`, nhận
      từ `--hardware-tier` với choices `{"cpu", "igpu", "dgpu", "npu"}`, mặc định `cpu`.

- [x] **Bước 3:** in tầng ở đầu output và ghi vào `metrics.json`.

- [x] **Bước 4: commit.**

---

## Task 7 — Cột "trúng câu hỏi", chấm tay

Nhân đã chốt **chấm tay**, không tự động. Lý do giữ nguyên tính so sánh được với bảng
ADR-015 — bảng đó cũng chấm tay từng câu trong `graded.jsonl`.

**Files:**
- Create: `eval/datasets/manual/v1/graded_speech.jsonl` (khung để điền tay)
- Modify: `src/rag/cli.py` (lệnh `eval` xuất khung)

- [x] **Bước 1:** `eval` xuất thêm `speech_to_grade.jsonl` gồm `case_id`, `input_text`,
      `spoken`, `reason`, và ô trống `answers_question` để người chấm điền
      `yes|partial|no`.

- [x] **Bước 2:** chấm tay 40 case `supported` cho bản S1 hiện tại. **Đây là baseline
      con người**, không có nó thì S2 không có gì để hơn.

- [x] **Bước 3:** đọc file đã chấm, in `answers_question_rate` cạnh hai cột cũ.

- [x] **Bước 4: commit** cả file đã chấm (nó là evidence, không phải dữ liệu tạm).

### Kết quả baseline (neo vào `eval/results/rag/20260813T132216Z`)

| | ca | tỷ lệ |
|---|---:|---:|
| trúng | 12 | 30,0% |
| một phần | 19 | 47,5% |
| không trúng | 9 | 22,5% |

Tách theo nhánh: `plain` 33 ca → trúng 33,3%; `pointer` 2 ca → 1 trúng 1 một phần;
`variant_fallback` 5 ca → 0 trúng (tự động, fail-closed).

**Đây là con số S2 phải hơn.** Gần một nửa số ca rơi vào "một phần" — câu mở đầu
đúng chủ đề nhưng chưa trả lời — đúng là lớp lỗi luật-chọn-theo-vị-trí sinh ra và
cũng đúng là chỗ chọn-theo-độ-liên-quan có đường ăn điểm. Bốn ca người chấm `no`
(RAG-104, RAG-106, RAG-136, RAG-140) là bài kiểm tra cứng nhất: ở đó đoạn top-1
không chứa câu trả lời, nên chọn câu khéo hơn **cũng không cứu được** — chúng là
bài của tầng truy hồi, không phải của S2. Đừng tính chúng vào phần S2 hứa cải thiện.


---

## Task 8 — Đo tầng iGPU

Tầng đại diện nhất cho cockpit SoC trong ba tầng ADR-016.

### Thứ tự thử trên iGPU — **0.5B trước, không phải 3B**

Đây là chỗ số của SPIKE-003 bị đọc thiếu một tầng. 0.5B trượt ở bậc C vì
`tool_accuracy_on_plan` = **0,345** — nhưng đó là bài **lập kế hoạch**: ánh xạ câu nói
tự do sang tool cộng schema tham số.

Bài của S2 khác hẳn: *"trong N câu này, câu nào trả lời câu hỏi?"* → trả về vài chỉ số
nguyên. Đơn giản hơn nhiều, **và kiểm chứng được bằng máy** (chỉ số phải hợp lệ, câu
phải khớp nguyên văn). Nên 0.5B có thể **đủ cho S2 dù không đủ làm planner**, và trên
iGPU thì khác biệt là quyết định:

| | 3B | 0.5B |
|---|---:|---:|
| Vulkan (dGPU) | 59,4 tok/s | **146,7 tok/s** |
| CPU 6 luồng | 9,3 tok/s | **38,0 tok/s** |

Ba đòn bẩy đã đo, dùng hết ngay từ đầu: **grammar** cắt 48% (2.644 → 1.382 ms);
**prompt cache** một mình vô dụng (2.708 ms) nhưng ghép grammar còn 877 ms; và đầu ra
của S2 chỉ vài token nên phần decode gần như biến mất.

Thử **0.5B + grammar + cache** trước. Chỉ leo lên 3B nếu chất lượng chọn câu không đạt.

- [x] **Bước 1:** tìm một máy trong nhóm chỉ có iGPU, hoặc ép `--device` sang iGPU trên
      máy có cả hai. ADR-016 đã cảnh báo `--device Vulkan1` là hardcode của máy Nhân —
      phải tự dò, đừng chép số thứ tự.

- [x] **Bước 2:** chạy lại bậc A của SPIKE-003 (`spike3_server.ps1` + `spike3_bench.py`)
      trên iGPU, ghi run mới.

- [x] **Bước 3:** thêm hàng iGPU vào bảng ADR-016. Nếu decode rơi gần mức CPU đúng như
      ADR-016 dự đoán (9,3 tok/s), thì **S2 không dùng được trên tầng đó** — và đó là
      một kết quả có giá trị, không phải một thất bại.


### Kết quả (2026-08-13) — nặng hơn dự đoán

| tầng | decode | p50 | prefill (pp512) |
|---|---:|---:|---:|
| dGPU RX 5500M | 156,3 tok/s | 317 ms | 2.875 tok/s |
| CPU 6 luồng | 44,7 tok/s | 1.135 ms | 1.625 tok/s |
| iGPU Radeon(TM) Graphics | 41,1 tok/s | 1.211 ms | 752 tok/s |

**iGPU không "rơi gần mức CPU" — nó thua CPU**, 7% ở decode và 2,2× ở prefill.
Nên câu hỏi "S2 chạy được trên iGPU không" đổi hình: nếu chạy được thì **chạy thẳng
trên CPU còn nhanh hơn**, và cả nhánh iGPU thành vô nghĩa trên lớp phần cứng này.

Kèm theo là một lỗ hổng bằng chứng đã vá: thứ tự `VulkanN` đổi ngay trên máy Nhân,
nên mọi số gắn nhãn "dGPU" trước ngày này không tự chứng minh được. Chạy lại đã tái
hiện được nên nhãn cũ đúng; script giờ dò theo tên và ghi tên vào manifest.

**Điều bảng này chưa trả lời:** bậc C là bài lập kế hoạch (prompt ngắn, nhả 160
token); S2 ngược lại (nhồi ~600–1.000 token, nhả ~15). Ước S2 ≈ 0,4 s / 0,8 s / 1,5 s
theo ba tầng — **ước, chưa đo**. Task 9 phải đo đúng hình dạng S2 trước khi kết luận.

---

## Task 9 — S2: SLM chọn câu, có cổng kiểm chứng

**Chỉ bắt đầu sau khi Task 7 có baseline chấm tay.**

**Files:**
- Modify: `src/agents/slm.py` (thêm `QwenSentenceSelector`), `src/agents/nodes/speech_policy.py`
- Test: `tests/test_agents/test_speech_policy.py`

**Interfaces:**
- Produces: `SentenceSelector` protocol — `select(question: str, sentences: list[str]) -> list[int]`.

- [x] **Bước 1: test đỏ — cổng kiểm chứng vứt mọi câu không nguyên văn**

```python
def test_cau_khong_nguyen_van_bi_vut_va_roi_ve_luat():
    """Đây là thứ khiến S2 khác phương án B mà ADR-015 đã bác: đầu ra là CHỈ SỐ CÂU,
    và mỗi câu nói được so chuỗi với nguồn. Không có diễn đạt lại thì không có chỗ
    cho điều kiện rơi ra."""
    class SlmBia:
        def select(self, question, sentences): return [99]   # chỉ số ngoài khoảng
    plan = chon_cau_de_noi(_ev("Câu một. Câu hai."), "hỏi gì", selector=SlmBia())
    assert plan.reason == "slm_output_rejected"
```

- [x] **Bước 2: test đỏ — S1 vẫn gác trước S2**

```python
def test_slm_khong_duoc_cham_vao_doan_co_bien_the():
    class SlmLuonChon0:
        def select(self, question, sentences): return [0]
    plan = chon_cau_de_noi(_ev("Bản ECO 240 KPA.", bien_the=True), "áp suất", selector=SlmLuonChon0())
    assert not re.search(r"\d", plan.spoken)
    assert plan.reason == "variant_fallback"
```

- [x] **Bước 3:** cài `QwenSentenceSelector` — grammar ép đầu ra là mảng số nguyên,
      timeout dùng `slm_timeout_s`, mọi lỗi → đường lui S1.

- [x] **Bước 4:** chấm tay lại 40 case với S2 bật, so với baseline Task 7.

- [x] **Bước 5:** cập nhật ADR-015 — **ba cột thay vì bốn**: *hôm nay / S1 / S2 / S1+S3*.
      Bỏ tách S2-dGPU/S2-iGPU vì Task 8 cho thấy iGPU thua cả CPU, nên nó không đáng
      một cột riêng. Thêm cột S1+S3 vì đó mới là chỗ số dịch chuyển.

      **Bước 4 đổi cách làm:** chấm tay từng vòng bị thay bằng **đáp án khoá** —
      ranh giới "một phần" / "không trúng" đòi người chấm phải thuộc đoạn sổ tay,
      thứ họ không có trước mắt. Xem `src/rag/speech_grade.py`.

---

## Task 10 — Tự dò llama-server thay vì bắt bật cờ — **KHÔNG LÀM** (14/08)

Task này dựng trên một tiền đề mà chính kế hoạch này đã bác: *"lý do **duy nhất còn
lại** để không bật SLM mặc định là máy đồng đội không chạy llama-server"*. Sai ở hai
tầng, và cả hai chỉ lộ ra sau khi đo:

1. **S2 đã bị bác** (Task 9). Vai trò SLM mà task này định phục vụ trên nhánh sổ tay
   không còn nữa.
2. Vai trò còn lại trên nhánh này là `QwenLeadIn` — **một câu dẫn không mang dữ kiện
   nào**. Tự dò một tiến trình LLM thường trú để làm tự nhiên hơn *một câu khung* là
   một cái giá lệch hẳn so với thứ nhận được.

Và cái giá không nhỏ: hành vi sẽ phụ thuộc vào **việc một tiến trình có tình cờ đang
chạy hay không**. Trong một repo mà kỷ luật là *"mọi con số truy về một run id"*, để
cùng một mã trả lời khác nhau tuỳ trạng thái xung quanh là đánh đổi sai — kể cả khi
Bước 2 vẫn giữ được công tắc cứng.

**Mở lại nếu** SLM planner (ADR-016) được nhóm duyệt bật mặc định. Khi đó tự dò phục vụ
một vai trò *có* thay đổi nội dung, và 8 giây timeout mỗi lượt mới là cái giá thật cần
tránh.

### Quan sát phụ ở cuối kế hoạch — **đã làm**

`onnxruntime` 1.28 nạp sẵn `AzureExecutionProvider` và trên máy này nó đứng **đầu** danh
sách ưu tiên. Đo thật: Piper nạp đúng `['CPUExecutionProvider']`, nên bất biến
*"No network at runtime"* (ADR-001) **không** bị vi phạm.

Nhưng không có gì khoá điều đó lại: thứ chọn provider là mặc định của `onnxruntime` cộng
thứ tự nó liệt kê, và cả hai đổi được qua một lần nâng phiên bản mà không ai nhận ra.
Đã thêm `test_piper_khong_bao_gio_nap_provider_goi_ra_mang`
(`tests/test_services/test_voice_integration.py`, marker `integration` nên chỉ chạy trên
máy có model). Nó **không** sửa lỗi nào đang có — nó khoá một điều đang đúng.

---

## Điều kế hoạch này **không** làm

- **Không port SLM sang ONNX/NPU.** Task 9 chỉ ghi nhận rằng GGUF không nằm trên đường
  đó. Port là một đợt riêng, và chỉ đáng làm sau khi Task 8 cho biết tầng iGPU có chạy
  nổi S2 không.
- **Không đụng `display_text`.** ADR-015 nguyên vẹn, như giai đoạn 1.
- **Không tuyên bố gì về xe thật.** Mọi số đều mang nhãn tầng phần cứng đã đo, và
  không tầng nào trong số đó là một chiếc xe.

## Một quan sát phụ, nên có người xem

`onnxruntime` 1.28 nạp sẵn `AzureExecutionProvider`. Nó nằm im nếu không ai chọn, nhưng
nó là một execution provider **gọi ra mạng**, trong một dự án có bất biến *"No network
at runtime"*. Nên có một khẳng định ở tầng test rằng provider đang dùng là CPU (hoặc
sau này là NPU/DML), chứ không phải Azure.

# TASK-RAG-001 — Xây dựng RAG sổ tay xe & Grounded Response

> **Status: Implemented (một phần).** Ingestion, index, retrieval, node và eval tầng
> retrieval đã có code chạy được và có test. Tầng generation **chưa** làm vì còn chờ
> [ADR-005](../adr/ADR-005-model-profile-selection.md) chốt model.
> Cập nhật 2026-08-07 (bản 3). Workstream: **WS2 Agent/RAG**.
> Spec authority: [ADR-003](../adr/ADR-003-local-rag-stack.md), [data_model.md](../data_model.md), [agent_spec.md](../agent_spec.md).

## Kết quả thực đo (2026-08-07)

Chi tiết và phân tích: [eval/results/rag/README.md](../../eval/results/rag/README.md).

| Chỉ số | Đo được | Mục tiêu | |
|---|---:|---:|:--:|
| page_exact_rate | 100,0% | ≥ 95% | ✅ |
| recall@k | 100,0% | — | |
| grounded_rate | 100,0% | > 90% | ✅ |
| citation_validity | 100,0% | = 100% | ✅ |
| hallucination_rate | 5,0% | < 5% | ❌ |

58 mục → 482 chunk → 536 vector. 68 test pass, ruff sạch, coverage 91%.

**Cập nhật sau review PR #10** — đã khắc phục hai nguy cơ:

- **Token overflow (lỗi thật, có mất dữ liệu):** cắt cửa sổ theo ký tự làm 5/557
  cửa sổ vượt 512 token và bị `SentenceTransformer` cắt cụt im lặng. Đã chuyển
  sang cắt theo **token thật** qua `Embedder.split_for_embedding`. Nay max 485
  token, **0 cửa sổ vượt trần**. Mọi chỉ số retrieval giữ nguyên.
- **Page mapping giòn:** thêm bậc `FUZZY` làm lưới dự phòng, cổng chất lượng
  thành hai tầng (toàn cục ≥95% **và** từng mục ≥80%), và `verify` liệt kê mọi
  chunk không khớp chính xác thay vì im lặng.

Ba phát hiện đáng chú ý, đã kiểm chứng bằng số:

1. **Sổ tay đánh số trang lại từ 1 cho mỗi mục** — không có hệ số trang toàn cục.
   Nhờ vậy chỉ số trang trong PDF chia nhỏ chính là số trang in, và Citation
   contract không cần đổi vì `section` + `page` ghép lại đã đủ phân biệt.
2. **Ngưỡng điểm cosine đơn thuần không đủ.** Tốt nhất chỉ đạt grounded 92,5% /
   hallucination 20%. Thêm điều kiện trùng từ vựng kéo hallucination xuống 5%.
3. **5% còn lại không giải được ở tầng retrieval** — cần grader ở tầng generator.

⚠ Ngưỡng được hiệu chỉnh trên chính bộ 60 case dùng để báo cáo, nên các con số là
ước lượng **lạc quan**. Cần bộ held-out trước khi đưa vào báo cáo cuối.

---

## 0. Tóm tắt cho người đang vội

- **PhoWhisper không liên quan đến task này.** Đó là STT của WS1.
- **Không cần Ollama.** Đề bài cho `llama.cpp/Ollama`, repo đã có llama.cpp + model GGUF.
- **Không cần trích xuất PDF.** Nguồn dữ liệu là **HTML có cấu trúc** — xem mục 2.
- **Chốt FAISS, không cần ADR mới.** Đề bài cho `Chroma/FAISS`, ADR-003 đã chọn FAISS. Chỉ cần sửa mô tả task board.
- **Số trang là vấn đề thật.** Sổ tay số không có số trang; phương án xử lý ở mục 6.

---

## 1. Task này phục vụ yêu cầu nào của đề bài

Đề bài **DEV-01** liệt kê 7 mục "Cơ bản" (bắt buộc). Task này phủ trực tiếp 2 mục và góp phần vào 1 mục:

| # | Yêu cầu Cơ bản | Task này |
|---|---|---|
| 4 | RAG trả lời từ sổ tay xe **có trích nguồn** | ✅ toàn bộ |
| 6 | Xử lý lỗi khi không hiểu lệnh | ✅ phần grounded refusal |
| 7 | Metric **tỷ lệ trả lời grounded** | ✅ phần eval |

Tech stack trong đề chỉ là **gợi ý** (`Chroma/FAISS`, `llama.cpp/Ollama`, …), nhóm được chọn linh hoạt.

**Không thuộc task này:** đăng nhập/RBAC (WS4), STT/TTS (WS1), điều khiển xe/MQTT/HITL (WS3), chọn model SLM ([ADR-005](../adr/ADR-005-model-profile-selection.md) đang "Not Yet").

---

## 2. Dữ liệu nguồn — đã có, và tốt hơn dự kiến

Vị trí: `data/manuals/vf9_2026_vi/` (**không được git track** — `.gitignore` đã bỏ qua `data/`).

```
data/manuals/vf9_2026_vi/
├── manifest.json          33 KB    58 mục: chapter / name / html / pdf / anchors
├── menu.json             1.42 MB   cây điều hướng + nội dung HTML nhúng
├── VF9_2026_full.pdf     58.3 MB   bản tổng hợp — nguồn DUY NHẤT có số trang
├── html/                  58 file  13 chương  ← NGUỒN INGEST CHÍNH
├── pdf/                   58 file  13 chương  ← mỗi file đánh số lại từ 1, KHÔNG dùng
└── assets/images/       1777 file  30.8 MB
                                    Tổng: 149.9 MB
```

### Vì sao dùng `html/` chứ không phải PDF

HTML **đã là text sạch, có ngữ nghĩa**. Không cần OCR, không cần đoán heading bằng cỡ chữ, không mất bảng biểu.

CSS class trong HTML mang ý nghĩa cấu trúc rõ ràng:

| Class | Ý nghĩa | Dùng làm gì |
|---|---|---|
| `Detail-Heading` (có `id` = anchor) | Mục cấp 1 | **Ranh giới chunk chính** |
| `Sub-Section` | Mục cấp 2 | Ranh giới chunk phụ khi mục quá dài |
| `Sub-Sub-Heading` | Mục cấp 3 | Giữ trong chunk |
| `Detail` | Đoạn văn thường | Nội dung |
| `Warning` / `Caution` / `Note` | **CẢNH BÁO / THẬN TRỌNG / LƯU Ý** | Metadata an toàn — xem dưới |
| `Points` / `List` | Gạch đầu dòng / đánh số | Giữ nguyên thứ tự |
| `Hyperlink` | Tham chiếu chéo có anchor id | Có thể khai thác sau |

### ⚠ Warning/Caution/Note là metadata quan trọng nhất

Sổ tay phân biệt rõ ba mức. Ví dụ trong `06_Cửa sổ điện.html`:

> **CẢNH BÁO** — *"Trước khi đóng cửa sổ điện, đảm bảo rằng tất cả người trên xe, đặc biệt là trẻ em, không thò bất kỳ bộ phận cơ thể nào ra ngoài cửa sổ điện."*

Với một trợ lý trong xe, đây là loại nội dung **không được để lẫn vào văn bản thường và không được cắt rời khỏi ngữ cảnh cha**. Lưu `content_type` cho từng đoạn, và khi câu trả lời chạm tới hành động có cảnh báo thì phải đọc kèm cảnh báo đó.

Điều này cũng khớp ràng buộc của đề bài: *"AI chỉ HỖ TRỢ"*.

### Metadata lấy được miễn phí

- **58 document** với `chapter`, `name`, và danh sách `anchors` — từ `manifest.json`. Không phải đoán cấu trúc.
- **Edition**: chuỗi `VF9_23-25_VN_VI_2.4 [New UI]` nằm trong `01_Hướng dẫn sử dụng.html` → đúng field `documents.edition`.
- **anchor id** kiểu `yzi5yjkzzdrlyjjmzjzk` — ID ổn định, deep-link được về `om.vinfastauto.com`.

### ⚠ Bản quyền

`01_Hướng dẫn sử dụng.html` ghi nguyên văn:

> *"Đã đăng ký bản quyền … không được sao chép, sửa đổi hoặc sử dụng lại bằng mọi cách mà không có sự cho phép trước bằng văn bản."* — Công ty CP Sản xuất và Kinh doanh VinFast

Hệ quả bắt buộc:
- Ghi `documents.license_note` **trung thực**, nêu rõ nguồn và tình trạng cho phép.
- **Không commit** 150 MB này lên git (đã xử lý bằng `.gitignore`).
- Nếu repo có khả năng thành public, phải xác nhận lại quyền sử dụng trước.

---

## 3. Tech stack đề xuất

Đề bài cho phép chọn linh hoạt. Đây là lựa chọn khuyến nghị và lý do:

| Thành phần | Chọn | Lý do |
|---|---|---|
| Nguồn ingest | `html/` + `manifest.json` | Text sạch có cấu trúc; bỏ hẳn hướng PDF/OCR |
| Parse HTML | `beautifulsoup4` + `lxml` | 58 file, tốc độ không phải vấn đề; API dễ đọc, dễ review |
| Chunking | **Tự viết theo CSS class** | Xem mục 4 — KHÔNG dùng splitter tổng quát |
| Embedding | `intfloat/multilingual-e5-small` | ADR-003; 384 chiều; CPU ~10–30 ms/query |
| Vector index | **FAISS `IndexFlatIP`** | Xem ghi chú dưới |
| Metadata store | SQLite | `documents` / `document_chunks` / `citations` |
| Số trang | `PyMuPDF` align với `VF9_2026_full.pdf` | Xem mục 6 |
| LLM compose | llama.cpp (đã có sẵn trong repo) | ADR-001 |

### FAISS: dùng `IndexFlatIP`, đừng dùng IVF/HNSW

58 chương → ước tính **2.000–4.000 chunk**. Ở quy mô đó, brute-force chính xác chỉ mất **micro giây**. IVF/HNSW là index gần đúng, sinh ra để xử lý hàng triệu vector — dùng ở đây chỉ **giảm recall mà không nhanh hơn chút nào**.

Normalize vector rồi dùng inner product → tương đương cosine, đúng khuyến nghị của e5.

### Vì sao FAISS chứ không Chroma

Đề bài cho cả hai, nên đây thuần là lựa chọn kỹ thuật:

- Lợi thế chính của Chroma là **metadata filter API**. Nhưng ở P0 chỉ có **một** vehicle profile và **một** edition — gần như không có gì để filter.
- FAISS + SQLite chạy **embedded trong `backend`**, đúng topology 5 service của [ADR-006](../adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md). Chroma thêm library state và migration riêng.
- Artifact FAISS checksum/rebuild được, dễ so regression giữa các lần thay đổi.

Nếu sau này quản trị metadata thành blocker thật, ADR-003 đã ghi Chroma là phương án dự phòng hợp lệ.

### ⚠ Kiểm tra môi trường trước

Probe ngày 2026-08-07: **chưa cài** `pymupdf`, `beautifulsoup4`, `sentence-transformers`, `faiss-cpu`. `requirements.txt` cũng chưa có (dòng `chromadb` đang bị comment).

Python đang dùng là **3.13.7**, trong khi `experiments/offline_poc/pyproject.toml` khai báo `requires-python = ">=3.11,<3.13"`. Cần xác minh wheel của `faiss-cpu` và `sentence-transformers` trên 3.13, hoặc dùng đúng Python 3.11/3.12 như declared.

---

## 4. Chunking — dùng cấu trúc, đừng dùng splitter tổng quát

Không dùng `RecursiveCharacterTextSplitter` hay tương tự. HTML **đã cho sẵn ranh giới ngữ nghĩa**; cắt theo số ký tự sẽ phá vỡ chúng.

```
Với mỗi file trong html/:
  ├─ đọc chapter + name từ manifest.json
  ├─ cắt chunk tại mỗi <p class="Detail-Heading">  → có anchor id
  ├─ nếu chunk quá dài → cắt tiếp tại <p class="Sub-Section">
  ├─ GIỮ NGUYÊN cùng chunk:
  │     • Sub-Sub-Heading và nội dung theo sau
  │     • toàn bộ Warning / Caution / Note thuộc mục đó
  │     • bảng và danh sách (không cắt giữa <table> hay <ol>)
  └─ lưu: chapter, section, anchor_id, content_type, text
```

### Quy tắc bắt buộc

1. **Không bao giờ tách `Warning`/`Caution`/`Note` khỏi mục cha.** Một cảnh báo mất ngữ cảnh còn nguy hiểm hơn không có cảnh báo.
2. **Không cắt giữa bảng.** Bảng trong sổ tay này thường là cặp *ảnh → nhãn* (ví dụ bảng công tắc cửa sổ) — cắt đôi là mất nghĩa hoàn toàn.
3. **Bỏ ảnh nhưng giữ `alt` text** nếu có nghĩa. Phần lớn là `alt="inline Rectangle"` (vô nghĩa, bỏ), nhưng một số là mô tả thật do AI sinh.
4. **Unicode NFC** cho toàn bộ text — [agent_spec.md](../agent_spec.md) yêu cầu ở mọi normalization path.
5. **Bỏ chương 01 phần bản quyền/hướng dẫn đọc sách** khỏi corpus tra cứu. Nó không phải nội dung vận hành và sẽ nhiễu retrieval.

---

## 5. Embedding — chỗ sai nhiều nhất

`multilingual-e5-small` là mô hình **asymmetric retrieval**, bắt buộc prefix:

```
Khi ingest:   "passage: " + chunk_text
Khi truy vấn: "query: "   + user_question
```

[data_model.md:287](../data_model.md) ghi rõ: *"config phải ghi rõ để tránh regression do ingestion/query khác nhau."*

**Vì sao đây là bẫy:** quên prefix thì code vẫn chạy, không exception, không warning — chỉ có chất lượng retrieval tụt mà không rõ nguyên nhân. Nếu ingest có prefix mà query không (hoặc ngược lại), kết quả còn tệ hơn bỏ cả hai.

Ghi vào embedding config: model checksum, số chiều (384), có normalize hay không, và cặp prefix đang dùng. Viết một test khẳng định cả hai đường dùng chung config.

---

## 6. Số trang cho Citation — vấn đề và cách xử lý

### Vấn đề

- `Citation.page` là **required field** trong [data_model.md](../data_model.md), và AC yêu cầu *"trích dẫn số trang chính xác"*.
- **HTML không có số trang.** Đây là sổ tay số.
- **PDF chia nhỏ không dùng được**: mỗi file đánh số lại từ 1. "Trang 3" của `06_Cửa sổ điện.pdf` không phải trang 3 của sổ tay — người lái mở sổ tay giấy trang 3 sẽ thấy nội dung khác. Citation vẫn "có số" nhưng **sai trong thực tế**.
- `VF9_2026_full.pdf` là nguồn **duy nhất** có hệ số trang đúng.

### Phương án: text từ HTML, số trang align từ full PDF

```
① KIỂM TRA full PDF có text layer không
     mở file, thử bôi đen chọn chữ. Chọn được = có text layer.
     Nếu là bản scan → dừng, đổi sang phương án dự phòng bên dưới.

② EXTRACT theo trang từ VF9_2026_full.pdf
     PyMuPDF → dict {page_no: text}

③ KIỂM TRA lệch số trang in vs index PDF
     Nhảy tới trang PDF thứ 20, xem góc trang in số mấy.
     Bìa + mục lục thường không đánh số → có thể lệch một hằng số.
     Citation phải dùng SỐ IN TRÊN TRANG — đó là con số người lái nhìn thấy.

④ ĐỐI CHIẾU từng chunk
     lấy ~80 ký tự đầu của chunk → normalize (NFC, lowercase, bỏ dấu câu/khoảng trắng thừa)
     → tìm trong text đã normalize của từng trang → ra page

⑤ ĐO ĐỘ PHỦ  ← gate bắt buộc
     % chunk khớp được trang.
     ≥95%  → chấp nhận, xử lý phần dư ở bước ⑥
     <95%  → dừng, điều tra: HTML và PDF có thể khác phiên bản
```

### Xử lý chunk không khớp

Kế thừa `page` của chunk liền trước **trong cùng section** (số trang tăng đơn điệu trong một mục). Ghi cách suy ra vào `document_chunks` (cột nội bộ) để audit được — **không** đưa vào public Citation, vì contract v1.0 từ chối field lạ.

### Đồng thời: lưu `anchor_id` vào `document_chunks`

Không đưa vào public Citation (contract cấm field thừa), nhưng lưu nội bộ vì:

- Engineer trace deep-link thẳng về `om.vinfastauto.com` để kiểm chứng citation.
- Chứng minh được `chunk_id` resolve đúng — [data_model.md](../data_model.md) yêu cầu điều này.
- Nếu sau này nhóm đổi contract thì đã có sẵn dữ liệu.

### Phương án dự phòng nếu bước ① hoặc ⑤ thất bại

Nếu full PDF là bản scan, hoặc độ phủ quá thấp: **đề xuất nhóm bổ sung `anchor_id` vào Citation schema v1.1** và dùng `section` + `anchor_id` làm định danh trích dẫn chính, `page` giữ ở mức "gần đúng theo chương".

Đây là **thay đổi contract**, cần WS2 + WS4 + backup reviewer đồng ý theo quy trình trong [delivery_plan.md](../delivery_plan.md). Không tự ý đổi.

---

## 7. Retrieval và composition

ADR-003 quy định số lượng cụ thể:

```
retrieve top 8  →  relevance grader  →  giữ tối đa 5 chunk
                                          │
                       ┌──────────────────┴──────────────────┐
                  đủ evidence                          thiếu evidence
                       │                                     │
              LLM compose, CHỈ dùng evidence          GROUNDED REFUSAL
                       │
              citation resolver validate
                       │
                  emit response
```

**Ràng buộc lên generator** ([technical_spec.md](../technical_spec.md), [safety_and_hitl.md](../safety_and_hitl.md)):

- Chỉ dùng evidence đã retrieve, không dùng general knowledge.
- *"The model can improve wording but cannot turn manual text into tool authority."* — văn bản sổ tay là **untrusted data**, không phải chỉ thị.
- **Tool bị disable** trong RAG generator. Sổ tay chứa prompt injection không được đổi policy hay gọi tool.
- Nếu evidence có `Warning`/`Caution`, câu trả lời phải nêu kèm.

---

## 8. Contract bắt buộc giữ đúng

### Public Citation — đủ 8 field, reject field lạ

```json
{
  "citation_id": "cit_01J...",
  "turn_id": "turn_01J...",
  "document_title": "Hướng dẫn sử dụng VinFast VF 9",
  "section": "Cửa sổ điện — Chức năng an toàn",
  "page": 112,
  "chunk_id": "chunk_...",
  "excerpt": "…",
  "retrieval_score": 0.86
}
```

`excerpt` phải bounded và **được evidence hỗ trợ thật**. API **không bao giờ** nhận filesystem path làm citation identifier.

### Tool `query_manual`

```
args schema:  {query: string}   — trimmed 1..500 Unicode code points
safety:       S0 (read-only)
```

`top_k`, vehicle profile, edition là **server-derived**. Sai schema → `VALIDATION_DENIED` với subcode `args_invalid`/`range_invalid`, xảy ra **trước** phân loại S0–S3.

### Node trong graph

Theo [agent_spec.md](../agent_spec.md), node tên `grounded_rag_retrieve`:

| Must do | Must not do | Failure path |
|---|---|---|
| retrieve profile-filtered manual evidence và grade coverage | answer from general knowledge | grounded refusal |

### Bốn artifact, mỗi cái một version key

| Artifact | Nội dung | Version key |
|---|---|---|
| Manual manifest | document, edition, checksum, license/source | `manual_manifest_version` |
| Chunk store | text + section/page/checksum | `chunker_version` |
| FAISS index | vectors keyed by chunk id | `index_checksum` |
| Embedding config | model checksum, dimensions, normalization, prefixes | `embedding_version` |

---

## 9. Đo AC — chuẩn bị trước, không phải sau

| Acceptance Criteria | Đo bằng gì | Chuẩn bị trước |
|---|---|---|
| Grounded Rate > 90% | Bộ **positive case** có nhãn: câu hỏi + section/anchor đúng | ✅ bắt buộc |
| Mọi câu tra cứu có trích dẫn trang | Citation validator chặn ở tầng code | pattern có sẵn |
| Hallucination Rate < 5% | Bộ **negative case**: câu hỏi mà sổ tay KHÔNG có đáp án | ✅ bắt buộc |

ADR-003: *"Score threshold không hardcode từ trực giác; hiệu chỉnh bằng positive/negative eval."*

**Negative case hay bị bỏ quên.** Không có nó thì không đo được hallucination và không calibrate được ngưỡng từ chối. Một hệ thống trả lời mọi câu hỏi sẽ có Grounded Rate cao giả tạo trong khi Hallucination Rate thật rất tệ.

Nguồn câu hỏi positive tốt: chính `anchors` trong `manifest.json` — mỗi anchor là một chủ đề có thật, dễ sinh câu hỏi tiếng Việt tự nhiên kèm nhãn đúng.

Pattern validate đã có tại `experiments/offline_poc/src/offline_poc/rag.py:154`:

```python
def validate_citations(answer_claims, evidence_by_id) -> bool:
    if not answer_claims:
        return False              # không có claim nào = fail
    for claim in answer_claims:
        evidence = evidence_by_id.get(str(claim.get("evidence_id")))
        if evidence is None:                         return False
        if claim.get("section") != evidence.section: return False
        if claim.get("page")    != evidence.page:    return False
    return True
```

---

## 10. Điểm vào code

`experiments/offline_poc/src/offline_poc/rag.py` **chưa phải vector search** — là keyword matching với anchor hardcode:

```python
_QUERY_ANCHORS = {
    "TPMS": ("tpms", "den ap suat lop", "den canh bao ap suat lop"),
    "ECO_MODE": ("eco",),
    "TIRE_CHECK": ("kiem tra ap suat lop", "khi nao can kiem tra"),
}
```

Docstring của chính class đó (`rag.py:91-95`) đã chỉ đường:

> *"Deterministic local index for the tiny PoC manual fixture. The real benchmark can replace the scoring adapter with E5/FAISS while retaining the same Evidence and citation-validation contracts."*

**Chiến lược migration:**

| Giữ nguyên | Thay ruột |
|---|---|
| `Evidence` dataclass | `ManualIndex.search()` — keyword → E5 + FAISS |
| `validate_citations()` | `ManualIndex.from_markdown()` → `from_html_corpus()` |

Nhờ vậy test hiện có trong `experiments/offline_poc/tests/test_rag.py` vẫn là lưới an toàn trong lúc thay.

Deliverable theo task board: `src/agents/nodes/rag_node.py`. Tên file không xung đột spec, nhưng node identity trong graph nên khớp `grounded_rag_retrieve`.

---

## 11. Checklist

**Chốt trước khi code**
- [ ] Sửa mô tả task board: ChromaDB → FAISS (không cần ADR mới, đề bài cho cả hai)
- [ ] `VF9_2026_full.pdf` có text layer không
- [ ] Lệch giữa số trang in và index PDF là bao nhiêu
- [ ] Quyền sử dụng nội dung VinFast đã rõ chưa → `license_note`

**Môi trường**
- [ ] Python đúng dải declared (3.11–3.12), không phải 3.13
- [ ] Thêm `beautifulsoup4`, `lxml`, `pymupdf`, `sentence-transformers`, `faiss-cpu` vào `requirements.txt`

**Ingestion**
- [ ] Parse `manifest.json` → 58 document với chapter/name/anchors
- [ ] Trích `edition` = `VF9_23-25_VN_VI_2.4 [New UI]`
- [ ] Chunk theo `Detail-Heading`, cắt phụ tại `Sub-Section`
- [ ] Warning/Caution/Note gắn `content_type`, **không tách khỏi mục cha**
- [ ] Không cắt giữa bảng/danh sách
- [ ] Unicode NFC
- [ ] Bỏ phần bản quyền/hướng dẫn đọc sách khỏi corpus
- [ ] Align số trang từ full PDF, **đo độ phủ ≥95%**
- [ ] Lưu `anchor_id` nội bộ trong `document_chunks`
- [ ] Manifest + checksum, ghi đủ 4 version key

**Embedding & index**
- [ ] `multilingual-e5-small`, prefix `passage:` khi ingest
- [ ] prefix `query:` khi truy vấn — **test khẳng định dùng chung config**
- [ ] FAISS `IndexFlatIP`, vector đã normalize
- [ ] Metadata ở SQLite, không nhét vào vector index

**Retrieval & response**
- [ ] top 8 → grade → giữ tối đa 5
- [ ] Evidence không đủ → grounded refusal
- [ ] Tool disabled trong RAG generator
- [ ] Evidence có Warning/Caution → câu trả lời phải nêu kèm
- [ ] Citation đủ 8 field, `chunk_id` resolve được

**Eval**
- [ ] Positive case sinh từ `anchors` trong manifest
- [ ] Negative case (sổ tay không có đáp án)
- [ ] Threshold calibrate bằng eval, không hardcode

---

## Tham chiếu

- [ADR-003: Local Grounded RAG with FAISS and SQLite Metadata](../adr/ADR-003-local-rag-stack.md)
- [ADR-001: Offline-First Local Runtime](../adr/ADR-001-offline-first-runtime.md)
- [ADR-005: Offline Model Profile Selection](../adr/ADR-005-model-profile-selection.md) — Not Yet
- [agent_spec.md](../agent_spec.md) — node `grounded_rag_retrieve`, tool `query_manual`
- [data_model.md](../data_model.md) — Citation, `documents`/`document_chunks`, RAG artifacts
- [safety_and_hitl.md](../safety_and_hitl.md) — prompt injection từ manual
- [multilingual-e5-small model card](https://huggingface.co/intfloat/multilingual-e5-small)

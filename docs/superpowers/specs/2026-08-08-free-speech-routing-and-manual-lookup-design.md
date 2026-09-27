# Thiết kế: Định tuyến câu nói tự do + bật tra cứu sổ tay VF9

> Ngày: 2026-08-08. Trạng thái: Đã duyệt (brainstorming), chờ implementation plan.
> Branch: `feature/free-speech-routing-and-manual-lookup`, nhánh từ
> `feature/agent-langgraph-vehicle-tools` @ `b7333fc`.
> Authority: [ADR-011](../../adr/ADR-011-default-route-to-manual-lookup.md),
> [ADR-010](../../adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md),
> [ADR-003](../../adr/ADR-003-local-rag-stack.md), [`agent_spec.md`](../../agent_spec.md).
> Việc trước: [agent graph + 5 tool](2026-08-08-agent-graph-vehicle-tools-design.md).

## Bối cảnh & quyết định

SCRUM-16 giao một router đạt 100% trên dataset do chính nó sinh ra. Đo lại bằng
`eval/datasets/manual/v1/cases.jsonl` (60 câu hỏi sổ tay, workstream RAG soạn cho
mục đích khác) cho **8,3%** — router chặn 91,7% câu hỏi trước khi tới được RAG,
trong khi RAG đã đo tốt từ trước (`eval/results/rag/20260807T102012Z/`:
recall@k 1.0, grounded_rate 1.0, citation_validity 1.0).

Quyết định đã chốt: **đảo mặc định của router sang tra sổ tay**, sửa luật `không`,
tách bộ nhận diện câu hỏi làm hai lớp, và bật RAG chạy thật trên corpus VF9. Lý do
đầy đủ trong [ADR-011](../../adr/ADR-011-default-route-to-manual-lookup.md).

Phạm vi **không** bao gồm: chạy Qwen với weight thật (giữ ở vai fallback đã có port),
voice/STT/TTS, và POI resolution.

## Kiến trúc & thành phần

```
src/agents/
  question.py    MỚI — nhận diện câu hỏi tiếng Việt
  contracts.py   SỬA — thêm disposition `offer`, nới invariant candidate_plan
  router.py      SỬA — đảo thứ tự _match, mặc định manual_query
  nodes/rag_node.py  SỬA — thiếu index thì từ chối tử tế, không sập
  eval.py        SỬA — thêm chế độ đo định tuyến trên dataset sổ tay
scripts/
  prepare_vf9_index.ps1   MỚI — copy corpus + manifest, chạy ingest
```

Không sửa `src/rag/` (workstream khác sở hữu) ngoài đúng một chỗ ở `rag_node.py`
— và chỗ đó thuộc `src/agents/`, không phải `src/rag/`.

### question.py — nhận diện câu hỏi

Tiếng Việt dùng dạng nghi vấn cho **cả** câu hỏi lẫn lệnh lịch sự. Thay vì đoán xem
người nói muốn gì, hệ thống trả lời câu hỏi rồi hỏi lại — xem `offer` bên dưới.

| Dấu hiệu | Kết quả |
|---|---|
| `thế nào`, `như thế nào`, `ra sao`, `làm sao`, `là gì`, `nghĩa là gì`, `tại sao`, `vì sao`, `khi nào`, `ở đâu`, `bao nhiêu`, `bao lâu`, `cách` (đầu câu), `có…không`, hoặc kết thúc bằng `?` | câu hỏi — **không bao giờ thực thi** |

Câu hỏi **khớp** một luật điều khiển → disposition `offer`: nêu việc sẽ làm rồi hỏi
lại. Câu hỏi **không** khớp luật nào → RAG.

`is_question(raw_text, normalized_text) -> bool`. Nhận **cả hai** dạng vì dấu `?`
chỉ còn ở bản thô — `normalize_vi` xoá dấu câu.

Bản thiết kế đầu có thêm một "lớp yêu cầu lịch sự" (`được không`, `nhé`) để giữ
`"Mở cửa sổ được không?"` là lệnh. **Đã bỏ.** Phân biệt nó với `"Phát nhạc từ USB
được không?"` (hỏi năng lực) cần ngữ cảnh mà luật không có, nên mọi luật viết cho
chỗ đó đều là đoán. Cho câu hỏi đi đường `offer` thì không còn gì phải đoán.

### Luật `không` — phủ định vs nghi vấn

Thay `_NEGATION_PATTERN` hiện tại. Luật mới, phát biểu một câu:

> `không` là **phủ định** khi đứng trước động từ; là **tiểu từ nghi vấn** khi là
> token cuối câu.

| Câu (đã chuẩn hóa) | `không` ở | Kết quả |
|---|---|---|
| `không phát nhạc` | đầu | phủ định → `denied` |
| `đừng mở cửa sổ bên lái` | — (`đừng`) | phủ định → `denied` |
| `ghế xe có chức năng massage không` | cuối | nghi vấn → RAG |
| `xe vf9 có ghế phóng khẩn cấp không` | cuối | nghi vấn → RAG → grounded refusal |

`đừng`, `chớ`, `chẳng` giữ nguyên là phủ định ở mọi vị trí.

### router.py — thứ tự mới của `_match`

```
1. is_question(...) → chạy matcher lệnh:
       khớp control        → ("offer", intent, "question_about_supported_action")
       khớp clarify/denied → giữ nguyên (không đề nghị một việc không hợp lệ)
       không khớp          → ("not_control", "manual_query", "manual_question")
2. guard phủ định            → denied
3. _AMBIGUOUS_TEXTS          → clarify
4. sáu matcher lệnh          → control
5. _UNSUPPORTED_TOKENS       → denied   (CHỈ khi câu trông như lệnh)
6. mặc định                  → ("not_control", "manual_query", "default_to_manual")
```

Hai chỗ đổi vị trí so với bản cũ, mỗi chỗ có lý do đo được:

- **Bước 1 lên trước guard phủ định và guard actuator.** `"Cách thay dầu động cơ
  xăng của VF9"` chứa `động cơ` nên bản cũ trả `denied/unsupported_actuator`. Nó là
  câu hỏi; VF9 chạy điện nên câu trả lời đúng là RAG grounded refusal — từ chối **có
  trích dẫn**, khác hẳn từ chối vì trùng từ khóa.
- **Bước 5 xuống sau matcher lệnh**, và chỉ áp dụng khi `_starts_with_command` đúng.
  `"Tắt phanh ABS"` vẫn `denied`; `"Bạn hãy tự bịa một quy trình sửa túi khí tại nhà"`
  không phải dạng mệnh lệnh nên rơi xuống mặc định → RAG → grounded refusal, đúng
  cách xử lý một câu mồi bịa đặt.

### rag_node.py — từ chối tử tế thay vì sập

Hiện `except (OSError, ValueError)`. faiss ném `RuntimeError` khi thiếu
`index.faiss`, nên lỗi lọt lên thành HTTP 500 — đã kiểm chứng:

```
RuntimeError: could not open data\rag\vf9_2026_vi\index.faiss for reading
```

Trước ADR-011 đường này hiếm khi chạy; sau ADR-011 nó là **đường mặc định**, nên
sập là không chấp nhận được. Mở rộng thành `(OSError, ValueError, RuntimeError)`
và trả `refusal_reason="index_unavailable"`, phân biệt với
`insufficient_evidence`. Composer thêm một câu cho outcome này.

### Bật index VF9

`scripts/prepare_vf9_index.ps1`, các bước tường minh:

1. Kiểm `VF9_2026_vi/` tồn tại; nếu không, dừng với hướng dẫn — **không tự tải**
   (`agent_spec.md`: no network at runtime).
2. Lấy `manifest.json` từ branch `feature/hybrid-architecture-resident-pipeline`
   (`git show <branch>:VF9_2026_vi/manifest.json`) — đúng định dạng
   `load_documents()` cần: `{id, chapter, name, html, pdf}`.
3. Copy corpus + manifest sang `data/manuals/vf9_2026_vi/` (`data/` đã gitignore).
4. `python -m src.rag.cli ingest` → `data/rag/vf9_2026_vi/`.
5. `python -m src.rag.cli verify` — cổng chất lượng có sẵn của pipeline
   (`MIN_PAGE_EXACT_RATE = 0.95`, `MIN_SECTION_RATE = 0.80`).

### Cái gì được track, cái gì không

Corpus **không** được commit. `src/rag/ingest/pipeline.py:44` mang chính lời của
nhóm: *"Nội dung không được sao chép, sửa đổi hoặc sử dụng lại nếu không có văn
bản cho phép. Chỉ dùng nội bộ cho đồ án AI20K P-192."* Push 157MB nội dung VinFast
lên repo tổ chức là phân phối lại, và history thì gỡ ra rất khó.

Thay vào đó track **metadata đủ để tái lập** (~40KB), theo đúng quy ước branch
hybrid đã dùng:

| Track | Không track |
|---|---|
| `VF9_2026_vi/manifest.json` (35KB) | `html/`, `pdf/`, `assets/`, `menu.json`, `VF9_2026_full.pdf` |
| `VF9_2026_vi/README.md` — nguồn gốc, ngày chụp, bản quyền | |
| `VF9_2026_vi/corpus.sha256` — checksum từng file, để verify | |
| `scripts/prepare_vf9_index.ps1` | |

Ai có corpus cũng dựng lại được index **giống hệt** và tự verify bằng checksum;
không ai phải tin lời người khác về việc index được sinh từ cái gì. `.gitignore`
giữ nguyên `VF9_2026_vi/*` với ngoại lệ cho ba file trên, và `.gitattributes` đánh
dấu `manifest.json` là `-text` để CRLF từ nguồn không bị đổi làm lệch checksum.

## Đo — lần này bằng dữ liệu không phải của tôi

`src/agents/eval.py` thêm chế độ `--mode routing` đọc dataset sổ tay và tính:

| Chỉ số | Dataset | Ý nghĩa | Hiện tại |
|---|---|---|---|
| `question_recall` | `manual/v1` (60, WS RAG viết) | câu hỏi tới được RAG | **0,083** (5/60) |
| `question_to_control` | `manual/v1` | câu hỏi bị **thực thi** thành lệnh — hướng nguy hiểm duy nhất. Sau khi có `offer`, nó bằng 0 **về mặt cấu trúc** chứ không nhờ vá luật | 0,000 (0/60) |
| `question_to_offer` | `manual/v1` | câu hỏi khớp luật điều khiển → nêu đề nghị, chưa làm gì | — |
| `question_denied` | `manual/v1` | câu hỏi bị từ chối thẳng | 0,083 (5/60) |
| `question_as_command_intent` | `manual/v1` | câu hỏi bị gán intent điều khiển dù chưa thực thi | 0,017 (1/60) |
| `command_accuracy` | `agent/v3` (60, tôi viết) | lệnh không hồi quy | 1,000 |
| `command_to_manual` | `agent/v3` | lệnh bị nuốt thành câu hỏi | 0,000 |

`question_to_control` hiện đã là 0 và **phải giữ ở 0** — đó là hướng duy nhất tạo
tác dụng phụ thật. Đừng nhầm nó với `question_as_command_intent`: `RAG-120
"Chỉnh nhiệt độ và tốc độ quạt gió thế nào?"` nhận `clarify/hvac_temperature` —
bị đọc nhầm ý định nhưng chưa chạm executor, nên là lỗi chất lượng chứ không phải
lỗi an toàn. Cả hai đều phải về 0, với mức ưu tiên khác nhau.

`command_accuracy` không được tụt.

Ngoài ra một lần chạy end-to-end thật trên index vừa build, lưu vào
`eval/results/agent-manual/<UTC-run-id>/`, gồm câu hỏi → citation thật (`chunk_id`,
section, page). Đây mới là câu trả lời cho "hệ thống có tra được tài liệu VF9 không".

**Giới hạn phải ghi rõ khi báo cáo:** `manual/v1` độc lập với router (viết cho mục
đích khác, bởi người khác) nhưng vẫn là người **trong nhóm**. Nó không phải người
dùng thật. Con số mới sẽ trung thực hơn 100% của `agent/v3` rất nhiều, nhưng vẫn
chưa phải bằng chứng về người dùng thật.

## Testing

| File | Nội dung |
|---|---|
| `tests/test_agents/test_question.py` | MỚI. Hai lớp dấu hiệu; `?` một mình không đủ; `được không` không phải câu hỏi |
| `tests/test_agents/test_router.py` | THÊM. Luật `không` (4 case bảng trên); `"Cách thay dầu động cơ xăng"` → manual chứ không denied; mặc định → manual_query; toàn bộ test lệnh cũ **không được đổi** |
| `tests/test_agents/test_graph.py` | THÊM. Câu lạ → nhánh RAG; thiếu index → `refusal_reason` chứ không raise |
| `tests/test_agents/test_eval.py` | THÊM. Chế độ routing tính đúng 5 chỉ số trên fixture nhỏ |
| `tests/test_rag_integration/` | MỚI, đánh dấu `@pytest.mark.slow`. Chạy thật trên index; CI bỏ qua |

Test không được gọi mạng và không được yêu cầu index thật (trừ nhóm `slow`).

## Documentation

- [ADR-011](../../adr/ADR-011-default-route-to-manual-lookup.md) — đã viết.
- `eval/datasets/agent/v3/README.md` — ghi việc đổi nhãn 2 case tán gẫu sang
  `manual_query` và lý do.
- `README.md` — cập nhật bảng trạng thái: thay số `1.0000` self-referential bằng
  cặp số `question_recall` / `command_accuracy` kèm run-id.
- `WORKLOG.md`, `JOURNAL.md` — cập nhật khi work land.

## Ngoài phạm vi (out of scope)

- **Chạy Qwen với weight thật** — giữ ở vai fallback; port đã có, chưa có bằng chứng.
- **Voice/STT/TTS** — đầu việc khác.
- **HITL** — branch `feature/hitl-safety-confirmation`.
- **Sửa `src/rag/`** — workstream khác sở hữu. Chỉ chạm `src/agents/nodes/rag_node.py`.
- **Đo latency đường mặc định mới** — ADR-011 ghi nhận chi phí tăng nhưng chưa đo;
  không tuyên bố gì về latency cho tới khi có số.
- **Lượt trả lời "có"/"không" sau lời đề nghị** — thuộc `recognize_approval_intent`
  mà `agent_spec.md` đã đặc tả cho branch HITL (SCRUM-18). Làm ở đây sẽ thành hai hệ
  xác nhận song song, chồng nhau và chắc chắn lệch nhau.

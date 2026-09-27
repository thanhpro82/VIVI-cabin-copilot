# Hoàn thiện dashboard kỹ sư — thiết kế

- Ngày: 2026-08-28
- Trạng thái: Chờ nhóm duyệt. Phần A/B triển khai được ngay sau duyệt; **phần C chỉ khởi động sau khi nhóm chốt riêng bốn câu ở §7**
- Người quyết: Nhân
- Liên quan: ADR-029 (câu trả lời trên bề mặt kỹ sư), `docs/api_spec.md` §Trace/§Metrics, `docs/data_model.md:304`, `docs/tasks/TASK-BE-OBS-001-engineer-observability.md`
- Không đụng `compose.py` → chạy song song được với làn agent SP-3/SP-4

## 1. Vai trò của dashboard kỹ sư, và vì sao phải nói ra trước

Dashboard này là **hộp đen của hệ thống**: nó chứng kiến và làm rõ một lượt vừa rồi đã
đi qua những gì. Nó không phải màn hình BI, cũng không phải công cụ nghiên cứu.

Đọc từ code hiện có thì vai trò đó đã nhất quán sẵn, và người viết `TraceRecord` đã cố
ý đặt ranh giới:

- Field trong `TraceRecord` toàn là **cơ chế**, không có field **chất lượng**:
  `route_source`, `max_safety_level`, `block_code`, `admission_status`,
  `approved_vehicle_state_version` vs `actual_vehicle_state_version`, bảy stage latency.
- `/metrics/summary` là **fold thuần** trên đúng kho đó, không giữ counter riêng
  (`src/services/metrics.py`).
- `rag.grounded_rate` cố ý chỉ đếm `citation_count > 0`, và docstring `metrics.py:183`
  nhường phán xét "trích đúng không" cho `src/rag/evaluate.py` chạy offline.

Nói cách khác: **dashboard trả lời câu hỏi kiểm chứng được ngay tại chỗ; mọi câu hỏi
cần đáp án khoá thì đẩy sang `eval/`.** Cái mock `isMock: true` trong `offlineEval.ts`
là **hệ quả đúng** của ranh giới đó — nó là ô trống chờ artifact, không phải lỗ hổng
chờ mô hình lấp.

Thiết kế này giữ nguyên ranh giới ấy. Nó chỉ làm ba việc: lấp ô trống bằng artifact
thật (A), làm nhật ký sống qua restart (B), và tự động hoá vòng chấm tay (C).

## 2. Phân rã và phụ thuộc

| Phần | Nội dung | Phụ thuộc | Trạng thái |
|---|---|---|---|
| **A** | Bỏ mock, gắn số thật có run id | không | duyệt là làm |
| **B** | Trace sống qua restart, giữ 30 ngày | không | duyệt là làm |
| **C** | LLM judge chấm theo lô, có nút bấm | cần A làm chỗ hiển thị | **chờ §7** |

Không có phụ thuộc vòng tròn. Nếu nhóm bác C thì A và B vẫn đứng vững và vẫn có giá
trị độc lập — đó là tiêu chí dùng để cắt.

## 3. Phần A — bỏ mock, gắn run id

### 3.1 Vấn đề

`frontend/src/components/engineer/offlineEval.ts` đang hard-code:

```ts
intentAccuracy: 0.924, hallucinationRate: 0.075,
evaluatedAt: "2026-08-07", isMock: true
```

Docstring của chính nó thừa nhận là số minh hoạ, vì `eval/results/report.md` là báo cáo
SPIKE-001 (giai đoạn chọn model, cả hai candidate FAIL hard gate, "Not Yet") — dán thẳng
lên dashboard sẽ đọc thành "hệ thống hiện tại đang lỗi nặng".

### 3.2 Quyết định gây tranh cãi nhất: bỏ ô "Độ chính xác ý định"

Phản xạ đầu tiên là thay `0.924` bằng số thật từ `eval/results/agent-intent/`. **Không
được làm thế.** Run mới nhất (`20260827T110536.235373Z`) cho `intent_accuracy: 1.0000`,
và manifest của chính nó ghi:

> `"note": "Router luật, không gọi model. Không phải bằng chứng chất lượng SLM."`

`CLAUDE.md` xếp bộ `agent/v3` là **tripwire hồi quy**, do chính người viết router soạn,
nên "nó nói gì về khả năng khái quát hoá" là *không gì cả*. Đổi 92,4% (bịa) lấy 100,0%
(thật nhưng vô nghĩa với người đọc) là **đi lùi**: số thứ hai còn dễ bị trích dẫn sai
hơn số thứ nhất, vì nó có vẻ có nguồn.

**Quyết định:** khối "Đánh giá offline" chỉ hiển thị số từ suite `rag` — nơi có đáp án
khoá ngoại sinh (sổ tay VF9) và có phân biệt positive/negative:

| Ô | Nguồn | Giá trị run 20260827T172523Z |
|---|---|---|
| Tỷ lệ bịa | `metrics.json:hallucination_rate` | 0,05 |
| Tỷ lệ có căn cứ | `metrics.json:grounded_rate` | 1,00 |
| Trích dẫn hợp lệ | `metrics.json:citation_validity` | 1,00 |

Số định tuyến **không biến mất**, nó chuyển chỗ: xuống một dòng phụ có nhãn
`tripwire hồi quy — không phải độ chính xác người dùng`, để người trong nhóm vẫn thấy
nó gãy khi nó gãy, mà người ngoài không đọc nhầm thành cam kết chất lượng.

### 3.3 Ba nguyên tắc trình bày (bắt buộc)

1. **Mỗi ô số mang ba thứ: giá trị, ngày, mã run.** Không có run id → ô hiện `—`.
   Tuyệt đối không hiện số cũ khi không đọc được run mới.
2. **Ghi rõ ai chấm**: `đáp án khoá` / `người chấm tay` / `judge`. Ba nguồn này không
   được cộng vào một con số.
3. **Đổi nhãn khối Live.** `Grounded Rate` hiện chỉ đếm "có trích dẫn hay không" —
   nhãn phải nói đúng thế (`Tỷ lệ lượt có trích dẫn`). Giữ nguyên phép đo, sửa cái tên
   đang nói quá.

### 3.4 Nợ phải trả kèm: run `rag` chưa từng ghi `manifest.json`

`CLAUDE.md` §"Evidence is the product" quy định một run gồm `manifest.json`,
`case_results.jsonl`, `metrics.json`. Kiểm tra cả 8 run trong `eval/results/rag/`: chỉ
có `case_results.jsonl`, `metrics.json`, `speech_to_grade.jsonl` — **không run nào có
manifest**. `src/rag/cli.py:242-243` chỉ ghi `metrics.json`.

Nên A phải bổ sung: `_cmd_eval` ghi thêm `manifest.json` gồm tối thiểu `run_id`,
`dataset`, `index_manifest`, `hardware_tier`, `graded_by`, `note`. Không có nó thì
endpoint ở §3.5 không có provenance nào để trả về, và nguyên tắc (1) ở trên không thực
hiện được.

Run cũ **không hồi tố** — chúng bất biến. Endpoint đọc run thiếu manifest thì trả
provenance rỗng và UI hiện `—`, đúng nguyên tắc (1).

### 3.5 Nới bề mặt API: `GET /api/v1/metrics/eval-snapshot`

Frontend không đọc được filesystem, nên cần một interface mới:

```
GET /api/v1/metrics/eval-snapshot?suite=rag     Engineer-only
→ { data: { suite, run_id, generated_at, graded_by, metrics: {...}, note }, meta, trace_id }
→ 404 NOT_FOUND khi suite chưa có run nào
```

- **Engineer-only**, dùng `_ENGINEER_ONLY` sẵn có trong `src/api/observability.py`.
- Chỉ đọc, chỉ trả `metrics.json` + `manifest.json` của run **mới nhất** theo tên thư
  mục. Không nhận query param nào khác ngoài `suite` (whitelist: `rag`, `agent-intent`).
- Không bao giờ chạy eval. Đây là endpoint đọc artifact, không phải endpoint kích hoạt.

Đây là **lần nới bề mặt thứ ba** sau `vehicle/profile` (#123) và `profile/options`, nên
phải được lập luận trong `api_spec.md` dưới bảng interface đúng như hai lần trước —
không nới lặng lẽ.

## 4. Phần B — nhật ký sống qua restart

### 4.1 Vấn đề

`TraceStore` là LRU in-memory có trần (mặc định 200 bản ghi), mất sạch khi restart.
Docstring của chính nó ghi nhận: `docs/data_model.md:304` quy định `trace_spans` giữ
**30 ngày trong SQLite**, và repo chưa persist gì. `LogsTable` vì thế là ring buffer
"từ khi mở phiên làm việc", không phải historical viewer.

### 4.2 Thiết kế

Thêm bảng thứ năm vào `src/db.py` (đã có 4 bảng + một kết nối process-wide, `sqlite3`
stdlib). Trace ghi xuống khi `sealed_at` được đặt; đọc lại theo `trace_id` và theo cửa
sổ thời gian. Purge theo `trace_retention_days = 30`.

Kho in-memory **giữ nguyên** làm cache đọc nhanh; SQLite là nguồn bền. `/traces/{id}`
miss cache thì rơi xuống SQLite trước khi trả 404.

### 4.3 Ba ràng buộc cứng

1. **Không thêm một field nội dung nào.** Persist đúng những field `TraceRecord` đang
   có. ADR-029 giữ nguyên: không transcript, không excerpt, không citation text. Việc
   "lưu lâu hơn" không được lén trở thành "lưu nhiều hơn" — đó là cách một quyết định
   riêng tư bị xói mòn mà không ai bấm nút nào cả.
2. **`/metrics/summary` không đổi ngữ nghĩa.** Vẫn là fold trên cửa sổ rolling
   `METRICS_WINDOW_SECONDS`, vẫn không nhận query param. Persist là chuyện lưu trữ,
   không phải cớ để nới API.
3. **Không đổi `TraceRecord`.** Bảng SQLite là hình chiếu của dataclass hiện có; thêm
   field mới là việc của PR khác.

### 4.4 Nới bề mặt API: `GET /api/v1/traces`

Để `LogsTable` xem được lượt của phiên trước:

```
GET /api/v1/traces?limit=&since=          Engineer-only
→ { data: { items: [TraceSummary], next_cursor }, meta, trace_id }
```

`TraceSummary` là tập con của `TraceData` hiện có — đủ cho 6 cột của bảng, không kèm
`answer_text` đầy đủ (bảng đã truncate sẵn). Đây là **lần nới thứ tư**, cùng một kỷ
luật lập luận trong `api_spec.md`.

**Phương án lùi nếu nhóm thấy hai lần nới trong một đợt là quá nhiều:** B chỉ persist,
chưa cho dashboard đọc lịch sử. Không khuyến nghị — như thế B mất gần hết giá trị nhìn
thấy được, chỉ còn là nợ kỹ thuật đã trả nhưng không ai thấy.

## 5. Phần C — LLM judge (chờ duyệt, **không khởi động**)

### 5.1 Nguyên tắc đặt chỗ

Judge là **người chấm thi thuê**, không phải giám khảo sáng tạo và không phải thanh
tra. Nó chỉ có giá trị khi đề và chuẩn đã do người ra trước.

- Chạy trong `eval/`, **ngoài băng**, không bao giờ nằm trên đường đi của một lượt thoại.
- Model **Opus 5** (`claude-opus-5`). Không dùng Batch API ở vòng đầu: chênh ~0,3 USD
  một vòng, đổi lấy "bấm là thấy". Chuyển sang Batch chỉ khi bộ eval vượt vài trăm ca.
- Khoá API qua `.env`, **không commit** (tiền lệ `config/mosquitto/passwd`).
- Sản phẩm của một lần chấm là **một thư mục run bất biến**, không phải một con số.

### 5.2 Vai judge được giữ và vai bị cấm

**Giữ:**

1. *Chấm có đáp án khoá* (vai chính, sinh số cho §3.2). Judge **không tự quyết thế nào
   là đúng** — nó đối chiếu với `answer_keys.jsonl` đã chốt trước khi nhìn output.
2. *Phân loại lỗi* (kèm gần như miễn phí vì đã buộc trích cụm): lấy nhầm đoạn / đúng
   đoạn nhưng cắt mất phần trả lời / lạc điều kiện phiên bản (ECO vs PLUS, SDI vs CATL)
   / từ chối nhầm.
3. *Đề xuất đáp án khoá* — **chỉ ở chế độ có người duyệt từng khoá**, và phải ghi được
   khoá nào do người viết, khoá nào do judge đề xuất và ai duyệt.

**Cấm:**

- Chấm lượt thật đang phục vụ tài xế. Hai lý do, và lý do thứ nhất là lý do thực dụng:
  (a) **không có lưu lượng** — ngành lấy mẫu 1–10% traffic sản xuất; 1–10% của vài chục
  lượt demo là không ca nào; (b) `TraceRecord` **cố ý không lưu** transcript và citation
  text (ADR-029), nên judge sẽ chấm câu trả lời mà không có câu hỏi lẫn bằng chứng.
  Cửa này **để mở** cho tương lai có xe thật và có chính sách dữ liệu — cấm vì thiếu
  điều kiện, không phải cấm vì nguyên tắc.
- Tự sinh câu hỏi thi rồi tự chấm. Repo đã dính bẫy này: `agent/v3` đạt 100% vì do
  chính tác giả router soạn, và issue #244 vẫn ghi nợ "câu độc lập thật sự 0/15". Câu
  do LLM sinh là **cùng một bẫy đội lốt mới**. Được phép sinh câu *stress test*, nhưng
  phải dán nhãn tổng hợp và **không đếm vào phần câu độc lập**.
- Phán "tài xế có hài lòng không". Đó là câu hỏi phải hỏi người dùng thật.

### 5.3 Hình dạng chấm

**Chấm từng ca một (pointwise), không so cặp.** Đầu vào: câu hỏi + đoạn sổ tay nguồn +
cụm mang câu trả lời (khoá) + câu hệ thống nói ra. Đầu ra: `yes|partial|no` **kèm cụm
chữ làm căn cứ** và một nhãn phân loại lỗi.

Hai lý do chọn pointwise, cả hai đều là chống thiên lệch bằng cấu trúc:

- **Không có chỗ cho thiên lệch vị trí.** Khảo sát hệ thống 2026 trên 21 model đo lệch
  vị trí từ 0,002 tới 0,192, tệ nhất ở model nhỏ — nhưng nó chỉ tồn tại trong so sánh
  cặp A-với-B. Pointwise thì không có A và B.
- **Độ dài không mua được điểm.** Câu hỏi là "có chứa nội dung trả lời không", không
  phải "câu nào tốt hơn". Quan trọng với dự án này vì SP-3 đang đi **cắt câu ngắn lại**
  để hạ p95 từ 8,5 s — một judge chấm theo "đầy đủ" sẽ chống lại đúng việc đó.

Judge phải **mù với danh tính hệ thống**: không cho biết đây là bản cũ hay bản mới, của
ai. Chấm mù là điều kiện, không phải sự tinh tế.

### 5.4 Cổng hiệu chuẩn — phần không được bỏ

Trước khi bất kỳ số nào của judge lên dashboard:

1. **Đo đồng thuận người-với-người trước.** Repo hiện có **một người chấm, 40 ca**
   (`graded_speech.jsonl`), nên chưa hề biết rubric có rõ ràng không. Nếu hai người
   không đạt κ ≈ 0,7 với nhau thì **rubric hỏng** — sửa rubric, chưa đụng tự động hoá.
2. **Đo κ (Cohen's kappa) giữa judge và người**, không báo tỷ lệ khớp thô. Lý do bằng
   số: trên MT-Bench, κ của 21 model là 0,376–0,511 trong khi khớp thô là 80–85% — con
   số thô **thổi phồng 33–41 điểm phần trăm** vì không trừ phần trùng do may rủi.
3. **Test-retest ≥ 3 vòng** ở cùng cấu hình. Cảnh báo đã đo được: hai judge chạy sản
   xuất đạt độ lặp lại > 0,988 mà vẫn lệch vị trí > 0,12 — *ổn định cao kèm thiên lệch
   cao là kiểu hỏng, không phải điểm mạnh*.
4. **Ghim vào manifest**: model id, phiên bản prompt, mức nỗ lực, ngày.

**Cổng phát hành:**

| κ (judge vs người) | Xử lý |
|---|---|
| < 0,40 | Không dùng. Sửa rubric rồi hiệu chuẩn lại |
| 0,40 – 0,60 | Lên dashboard được, nhưng người **phải soát mọi ca trượt** |
| ≥ 0,61 | Dùng bình thường, canary định kỳ |

### 5.5 Nút bấm

- Engineer-only. Ghi lại **ai bấm, lúc nào, chấm bộ nào, run id nào ra**.
- Trần **100 ca** mỗi lần bấm (~2,1 USD, rộng hơn bộ hiện có 40 ca); khoá bấm lại
  trong **10 phút**. Hai số này là mặc định đề xuất, nhóm chỉnh được ở §7.
- Nút chấm **bộ eval đã soạn**, không chấm log của phiên đang chạy.
- Bấm xong sinh một run mới; khối §3.2 trỏ sang run mới nhất.

### 5.6 Ranh giới tất định / judge

Giữ **tất định**, judge không được đụng: phân loại an toàn S0–S3, schema, tính hợp lệ
của trích dẫn, độ trễ, chi phí. Judge chỉ lo đúng một câu hỏi cần đọc hiểu: *đoạn này
có trả lời câu hỏi không*.

### 5.7 Ngân sách (đo trên dữ liệu thật)

Đo từ `eval/datasets/manual/v1` (40 ca có khoá): mỗi ca ~1.450 ký tự nội dung
(câu hỏi 37 + đoạn nguồn 975 + cụm khoá 253 + câu nói 184), cộng rubric → ~2.800 ký tự
đầu vào. Quy đổi 2,2–3,0 ký tự/token cho tiếng Việt có dấu:

| Hạng mục | Opus 5, không Batch |
|---|---|
| 1 vòng chấm 40 ca | **0,44 – 1,26 USD** |
| Test-retest 3 vòng | ~2,6 USD |
| Mở lên 100 ca, 3 vòng | ~6,4 USD |
| **Trần cả hạng mục, kể cả thử sai** | **< 20 USD** |

Kiểm tra chéo: ~0,018 USD/ca, nằm trong khoảng 0,01–0,10 USD/lần chấm mà ngành công bố.

**Prompt caching không giúp gì ở quy mô này** — phần dùng chung chỉ ~450 token, dưới
ngưỡng tối thiểu để cache kích hoạt. Đừng wire vào cho phức tạp.

**Chi phí thật của C không phải tiền API mà là công người:** vòng chấm tay thứ hai để
đo đồng thuận. Đó là thứ nhóm cần cân, không phải hoá đơn.

### 5.8 Điều kiện tiên quyết chưa có

Máy dev hiện **không có** gói `anthropic`, **không có** `ANTHROPIC_API_KEY`, **không
có** `ant` CLI. Phải xử lý trước khi C chạy lần đầu.

## 6. Cái thiết kế này **không** làm

- Không đo được độ trễ end-to-end thật, không drill offline, không nghiên cứu người
  dùng — ba khoảng trống lớn nhất của P0 vẫn nguyên.
- Không làm `/ws/engineer` sống qua reconnect (chỉ `/ws/ivi` có replay, ADR-014).
- Không thêm `transcript.partial` hay `approval.intent.detected`.
- Không đụng `compose.py`, `router.py`, `policy.py` — không giao với làn agent.
- Không biến dashboard thành công cụ chạy eval nặng: endpoint §3.5 chỉ đọc artifact.

## 7. Bốn câu nhóm phải chốt

1. **Có chấp nhận nới thêm hai interface không** (`metrics/eval-snapshot`, `traces`)?
   Đây là câu hỏi kỷ luật API, không phải câu hỏi kỹ thuật. Có phương án lùi ở §4.4.
2. **Có chi tiền API không** — dưới 20 USD cho toàn hạng mục C.
3. **Ai chấm tay vòng thứ hai** — hiệu chuẩn cần **hai người chấm độc lập**. Không ai
   ngoài nhóm gánh được việc này.
4. **Có mở ADR mới cho judge không** — đề xuất **có**: một ADR ghi *judge chạy ngoài
   băng, không bao giờ trên đường đi của lượt thoại, sản phẩm là run id*, để về sau
   không ai đọc nút bấm thành cái cớ gọi cloud từ trong xe.

## 8. Thứ tự thi công

1. **A** — làn độc lập, không giao với SP-3/SP-4.
2. **B** — làn độc lập, có thể song song A (khác file, khác tầng).
3. **C** — chỉ sau khi §7 được chốt.

## Nguồn tham khảo cho §5

- LLM-as-a-Judge, online vs offline eval: [Langfuse](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge),
  [LangSmith](https://docs.langchain.com/langsmith/online-evaluations-llm-as-judge)
- Judge là một tín hiệu, giữ kiểm tra tất định: [Braintrust](https://www.braintrust.dev/articles/what-is-llm-as-a-judge)
- Chi phí và lấy mẫu: [Arize](https://arize.com/resources/llm-evaluation-costs/)
- κ, thiên lệch vị trí, nghịch lý ổn định–thiên lệch: [arXiv 2606.19544](https://arxiv.org/html/2606.19544)
- Quy trình hiệu chuẩn với người: [Galileo](https://galileo.ai/blog/calibrate-llm-judge-human-annotations),
  [aws-samples/sample-GEDD](https://github.com/aws-samples/sample-GEDD/blob/main/grounded-evals/docs/cohens-kappa-for-llm-judges.md)

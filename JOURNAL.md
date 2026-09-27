# 📓 Weekly Journal — Team P-192 (VIVI Cabin Copilot)

> Nhật ký phát triển theo tuần: ghi chép học tập, khó khăn, quyết định kỹ thuật và kế hoạch Sprint.

---

## 🏃‍♂️ Sprint 1: 2026-07-30 — 2026-08-02

> **Mô tả Sprint 1:** Nghiên cứu khảo sát công nghệ, xây dựng tài liệu Brief, PRD, Scope, thiết kế Wireframe cơ bản và thực hiện PoC AI Offline Pipeline (Tiến độ: 57% Done).

### 📋 Danh sách Task Sprint 1 (Jira Board)

| Key | Tên Task | Phụ trách | Ưu tiên | Trạng thái |
|-----|----------|-----------|---------|------------|
| **SCRUM-10** | Hoàn thiện Brief và Product Requirement Document (PRD) | Thành Nguyễn (TN) | High | ✅ Done |
| **SCRUM-11** | Thiết lập Jira và Automation cho nhóm | Thành Nguyễn (TN) | Medium | ✅ Done |
| **SCRUM-13** | Thiết kế kiến trúc hệ thống (Architecture Design) | Sơn Hà (SH) | High | ✅ Done |
| **SCRUM-9** | Thực hiện PoC AI Offline Pipeline | Nhân | High | ✅ Done |
| **SCRUM-8** | Thiết kế Wireframe IVI Screen | Giáp (GG) | High | 🔄 In Progress |
| **SCRUM-14** | Sprint Review & Technical Decision | Thành Nguyễn (TN) | High | 🔄 In Progress |
| **SCRUM-12** | Nghiên cứu giao diện xe 3D phục vụ Demo | Giáp (GG) | Low | ⏳ To Do |

---

### 🎉 Đã hoàn thành trong Sprint 1
1. **Thiết lập Quản lý Dự án & Tài liệu (Thành Nguyễn):** Khởi tạo Jira Board, thiết lập Workflow/Automation (SCRUM-11), hoàn thiện bộ tài liệu Brief và PRD v1.1 (SCRUM-10).
2. **Thiết kế Kiến trúc Hệ thống (Sơn Hà):** Hoàn thành Architecture Design document (SCRUM-13) với sơ đồ kiến trúc 8 lớp và quy định các hợp đồng Interface.
3. **Nghiên cứu Thực nghiệm PoC AI Offline Pipeline (Nhân):** Benchmark thành công Qwen2.5-3B vs 0.5B (SCRUM-9), đo lường mức chiếm dụng RAM (~3.2 GB) và thời gian phản hồi (5.6s).
4. **Áp dụng BMAD Multi-Agent Documentation:** Chuẩn hóa toàn bộ bộ tài liệu dự án VIVI Cabin Copilot theo 5 vai trò BMAD (Mary, John, Sally, Winston, Paige).

---

### ⚠️ Khó khăn & Giải pháp (Sprint Review & Technical Decisions)
| Khó khăn | Giải pháp | Quyết định Kỹ thuật (Technical Decision) |
|----------|-----------|------------------------------------------|
| Giao diện xe 3D tốn tài nguyên render & làm tăng Latency (SCRUM-12) | Loại bỏ ý tưởng làm giao diện xe 3D | **Chốt chỉ làm Giao diện Next.js 2D UI** tối ưu tốc độ phản hồi giọng nói |
| Latency ban đầu của PoC còn cao (5,609 ms) | Tối ưu hóa pipeline ASR Faster-Whisper int8 + Piper TTS | Đặt mục tiêu giảm Latency xuống **< 3,000 ms** cho Sprint 2 |
| Nguy cơ gọi nhầm lệnh vật lý khi xe chạy tốc độ cao | Đặt cổng kiểm soát an toàn HITL ở Backend | Bắt buộc hiển thị Popup xác nhận trên IVI với thao tác nhạy cảm |

---

### 💡 Bài học kinh nghiệm (Retrospective)
- **Tập trung vào hiệu năng thực tế:** Bỏ qua các tính năng rườm rà (như Xe 3D) giúp team dồn 100% nguồn lực vào việc giảm Latency và tăng độ chính xác của AI Agent.
- **Tài liệu chuẩn hóa trước khi code:** Hoàn thiện bộ tài liệu PRD, API Spec và Architecture Design giúp các thành viên sẵn sàng bước vào Sprint 2 mà không bị block lẫn nhau.

---

## 🔮 Kế hoạch Sprint 2 (Unassigned Backlog Tasks: 03/08 — 09/08/2026)

> **Giai đoạn 2:** Phát triển & Tích hợp Codebase Cốt lõi (Core Development & Integration)

- [ ] **SCRUM-15:** Tích hợp PhoWhisper (ASR) & Piper (TTS) vào FastAPI server *(Priority: High)*
- [x] **SCRUM-16:** Xây dựng Agent LangGraph + 5 Tools (AC, Music, Windows, Seat, Nav) *(Priority: High)* — branch `feature/agent-langgraph-vehicle-tools`, run `20260808T041112.577589Z`
- [x] **SCRUM-17:** Xây dựng RAG FAISS cho sổ tay xe & Grounded Response *(Priority: High)* — index VF9 dựng xong, tra cứu chạy thật có trích dẫn số trang; composer chưa tổng hợp câu trả lời
- [x] **SCRUM-18:** Triển khai luồng HITL (xác nhận lệnh nguy hiểm) trong LangGraph *(Priority: High)* — branch `feature/hitl-safety-confirmation`, phủ 7/19 required safety test
- [ ] **SCRUM-19:** Xây dựng Virtual Vehicle API & MQTT Signal Broker *(Priority: High)*
- [ ] **SCRUM-20:** Dựng giao diện IVI Web App (Next.js 2D) kết nối ASR/TTS *(Priority: High)*
- [ ] **SCRUM-21:** Dựng Engineer Dashboard hiển thị Intent Acc, Grounded Rate & Logs *(Priority: Medium)*
- [ ] **SCRUM-22:** Tối ưu hóa pipeline bước đầu để giảm Latency từ 5.6s hướng tới <3s *(Priority: High)*

---

## 📅 Roadmap Các Tuần Tiếp Theo (Release Timeline)

- **Week 2 — Core Development & Voice/AI Pipeline (03/08–09/08/2026):** Tích hợp FastAPI, LangGraph Agent, RAG FAISS, local ASR/TTS và Virtual Vehicle MQTT Broker.
- **Week 3 — IVI Integration, HITL & Dashboard (10/08–16/08/2026):** Ghép Next.js UI với Backend, Popup HITL, Engineer Dashboard, và đo Latency End-to-End < 3s.
- **Week 4 — Evaluation, Video Demo & Pitch Deck (17/08–23/08/2026):** Chạy RAGAS benchmark, làm Video Demo 3-5 phút, hoàn thiện Pitch Deck 10 slides và nộp bài.

---

## 🧭 Quyết định tuần 2026-08-08 — WS2 Agent Pipeline

**Bối cảnh.** Ticket SCRUM-16 và SCRUM-18 được viết bám theo `docs/VIVI_API_Spec.md`
(Họ A), file tự khai báo ở dòng đầu là **"KHÔNG dùng file này làm spec kỹ thuật
để lập trình/implement"**. Nó mâu thuẫn với bộ canonical (Họ B) ở bốn điểm: tên
tool, điều kiện kích hoạt HITL, timeout, và route quyết định.

**Quyết định ([ADR-010](docs/adr/ADR-010-canonical-tool-registry-with-product-vision-adapter.md)).**
Lõi hệ thống theo Họ B; thêm một lớp adapter mỏng ở tầng API phơi tên và route
của Họ A. Deliverable mà ticket yêu cầu vẫn được giao đủ, mà không phải nhượng
bộ contract an toàn đã chốt ở ADR-006.

**Điểm gai góc nhất là điều kiện HITL.** Ngưỡng `speed > 5 km/h` lệch khỏi
canonical theo **hai chiều ngược nhau**: với cửa kính nó *lỏng hơn* (xe đứng yên
vẫn phải hỏi theo canonical, còn ngưỡng 5 km/h thì cho chạy thẳng); với cửa xe
nó *nguy hiểm hơn* (canonical phân loại S3 và chặn trước khi tạo approval, còn
ngưỡng 5 km/h biến "mở cửa lúc 60 km/h" thành hành vi được phép sau khi bấm
đồng ý). Chọn ngưỡng đó là tự tạo ra một release blocker theo đúng quality gate
của `safety_and_hitl.md`.

**Vai trò Qwen2.5-3B q4.** Ticket ghi là "mô hình suy luận chính". Nhưng
`agent_spec.md` chốt định tuyến ưu tiên luật, và SPIKE-001 kết luận **Not Yet**
cho cả hai ứng viên Q4 (fail hard gate). Sprint này implement Qwen làm **fallback
cho câu mơ hồ/hiếm**, qua một port inject được, mặc định tắt. Chưa có bằng chứng
chạy weight thật — không được trình bày như đã đạt.

**Sửa KI-001 có điều kiện.** Lỗi "Bật điều hòa lên 25 độ" nuốt mất số 25 (tuân
thủ một phần trong im lặng) đã được sửa, **kèm** bổ sung case vào dataset — đúng
điều kiện mà handoff 2026-08-08 đặt ra để việc sửa không làm code lệch khỏi
evidence đã chốt.

**Còn nợ.** SCRUM-18 (HITL) chưa làm, thiết kế đã có. Con số intent accuracy
100% là độ phủ hồi quy chứ không phải khả năng tổng quát hóa — cần câu lệnh thu
từ người ngoài nhóm mới đo được điều đó.

---

## 🧭 Bài học 2026-08-08 — giá trị của việc đo bằng dữ liệu mình không viết

SCRUM-16 kết thúc với `intent_accuracy = 1,0000` trên 60 case. Con số đó đúng, và
gần như vô dụng: dataset do chính người viết router soạn ra, biết trước mọi luật.
Hỏi bài mình tự ra đề thì luôn được điểm tuyệt đối.

Đo lại bằng `eval/datasets/manual/v1` — 60 câu hỏi sổ tay do workstream RAG soạn
cho mục đích khác — cho **8,3%**. Router chặn 91,7% câu hỏi trước khi chúng tới
được một hệ RAG vốn đã đo tốt từ trước (recall@k 1.0, grounded_rate 1.0).

Chênh lệch 1,0000 so với 0,083 chính là giá trị của bộ dữ liệu mình không viết.

Ba lỗi lộ ra, không lỗi nào bị unit test bắt được:

1. `có … không?` — dạng câu hỏi có/không phổ biến nhất tiếng Việt — bị regex phủ
   định đọc nhầm rồi **từ chối thẳng** 3 câu hỏi hợp lệ.
2. Mặc định khi không khớp luật là "tôi chưa rõ bạn muốn điều khiển gì", trong khi
   câu trả lời đúng là tra sổ tay.
3. Thiếu chỉ mục thì graph **sập** thành HTTP 500 chứ không từ chối tử tế.

Sau khi sửa: 98,3%, và tra cứu VF9 chạy thật với trích dẫn số trang.

**Quyết định thiết kế đáng nhớ nhất** ([ADR-011](docs/adr/ADR-011-default-route-to-manual-lookup.md)):
ban đầu định dạy router phân biệt `"Mở cửa sổ được không?"` (yêu cầu) với
`"Phát nhạc từ USB được không?"` (hỏi năng lực). Hai câu cùng cấu trúc ngữ pháp,
khác nhau ở ngữ cảnh mà luật không có — mọi luật viết cho chỗ đó đều là đoán. Chốt
lại: **câu hỏi không bao giờ thực thi**; câu hỏi khớp luật điều khiển thì nêu việc
sẽ làm rồi hỏi lại. Bỏ phép đoán đi thì chỉ số "câu hỏi bị thực thi thành lệnh"
bằng 0 vì cấu trúc, chứ không nhờ tinh chỉnh luật cho vừa cổng.

Bài học chung: khi một chỉ số và một tài liệu chỏi nhau, đừng sửa chỉ số.


---

## 🧭 Quyết định 2026-08-08 — HITL

**Chạy thử thư viện trước khi viết plan, và nó đáng.** LangGraph chạy lại **thân node
từ đầu** khi resume — đo được 2 lần chạy cho 1 lượt. Spec HITL viết trước đó không
biết điều này, nên thiết kế theo spec sẽ tự chặn chính nó: `store.create()` bị gọi hai
lần cho cùng một approval, lần thứ hai ném `ApprovalAlreadyPending`. Bug loại này không
lộ ra ở unit test của store — chỉ lộ khi chạy end-to-end.

**HITL là opt-in ở `build_graph`.** Graph có checkpointer thì `ainvoke` bắt buộc kèm
`thread_id`, mà ~20 test hiện có gọi không kèm config. Đây không phải lỗ hổng an
toàn: không có store thì S2 vẫn dừng ở `approval_required` rồi sang compose — tức
**không thực thi**. Bật HITL chỉ thêm đường xin xác nhận, không mở đường chạy mới.

**Kiểm predicate lần cuối là chỗ dễ bỏ sót nhất.** Xe đứng yên → xin mở cửa (S2) →
đang chờ thì xe lăn bánh → lẽ ra phải là S3. Nếu chỉ kiểm `state_version` và `plan_digest`
thì approval cũ vẫn hợp thức hoá một action mà policy hiện tại đã cấm. Phải materialize
lại plan từ snapshot mới và so digest.

---

## 🧭 Ghi chú 2026-08-09 — spot-check giọng thật lộ bug tokenization ẩn trong voice correction

7 câu ASR đo bằng giọng thật (ngoài phạm vi corpus synthetic của ADR-007/008, nên
không tính là bằng chứng WER chính thức) chạy qua `correct_transcript()` cho thấy
gần như **không câu nào được sửa** — kể cả ca lẽ ra sửa được ("đỗ" → "độ", lệch
đúng 1 dấu thanh, trong `max_edit_distance=1`). Nguyên nhân không phải giới hạn
thiết kế đã biết (ambiguous distance-1, lỗi phonetic nặng...) mà là dấu câu cuối
câu ASR dính liền vào từ cuối (`"đỗ."`), làm tokenize theo khoảng trắng không bao
giờ khớp được với vocabulary. 5 test unit có sẵn đều dùng câu không có dấu câu nên
không bắt được lỗi này.

Cùng bài học như 2026-08-08: dữ liệu tự mình không viết ra (ở đây là giọng thật
thay vì dataset RAG) lộ ra lớp lỗi mà dữ liệu tự tạo (5 câu fixture synthetic)
không bao giờ chạm tới, vì fixture synthetic không có dấu câu dính từ theo kiểu
STT thật hay tạo ra. Đã sửa theo TDD (tách dấu câu trước khi so khớp, ghép lại
sau) — xem `WORKLOG.md` 2026-08-09 (bổ sung 2).

---

## 🧭 Quyết định 2026-08-09 — một nguồn vehicle state, và cái giá của nó

**Hai simulator song song là loại bug không unit test nào bắt được.** Cả hai đường
đều có test riêng và đều xanh: `tests/test_vehicle/` chứng minh đường MQTT đúng,
`tests/test_agents/` chứng minh đường agent đúng. Cái sai nằm ở chỗ **không ai nối
chúng lại**, và không có test nào đứng ở vị trí nhìn thấy cả hai. Thứ lộ ra bug là
đọc `frontend/` — thấy `DriverShellProvider.tsx:105` refresh vehicle state sau
`tool.result` rồi tự hỏi giá trị đó lấy từ đâu. Bài học: bug tích hợp chỉ lộ ra khi
đọc từ phía **người tiêu thụ**, không phải từ phía người sản xuất.

**Trả 200 kèm cờ `stale` là nói dối một cách im lặng.** Đã cân nhắc để
`GET /vehicle/state` trả state cũ kèm `meta.stale=true` cho demo mượt. Bỏ, vì hợp
đồng gọi đây là state *authoritative*: dữ liệu của một simulator đã chết thì không
còn authoritative, và client không có cách nào phân biệt "xe đang đứng yên" với
"xe đã chết mười phút trước". 503 kèm `error.details.reason` khó chịu hơn nhưng
trung thực.

**Không rơi về xe in-process khi broker chết.** Nếu `MQTT_ENABLED=true` mà
`runtime.start()` hỏng thì lifespan vẫn gắn cổng MQTT, để API báo
`broker_unreachable`. Rơi về in-process lúc đó là **thay thầm một chiếc xe khác**:
endpoint trả 200 với trạng thái của một chiếc xe không ai điều khiển. In-process
chỉ chạy khi `MQTT_ENABLED=false` — tức lựa chọn tường minh của người vận hành.

**Mất khả năng cho xe chạy trong demo MQTT, và không lấp bằng hack.** ACL cấm
backend publish `state/*`, `motion` là read-only, nên `set_motion()` chỉ có ở bản
in-process. Đúng là bất tiện cho demo S3. Nhưng shadow-publish `state/motion` từ
backend "tạm cho demo" chính là loại vi phạm mà cả PR này đang đi sửa — nên ghi vào
ADR-013 như một GAP thật, kèm ba lối đi hợp lệ.

**`/healthz` trả 503 vì `llm` là tính năng, không phải lỗi.** ADR-005 chốt "Not
Yet", `slm_enabled=False`, P0 chạy hoàn toàn bằng luật tất định. Báo `ready` cho
một LLM không tồn tại sẽ dễ chịu hơn cho dashboard, nhưng `/healthz` là thứ người
khác dựa vào để quyết định. Con số khó chịu mà đúng vẫn hơn con số đẹp mà sai —
cùng nguyên tắc với kỷ luật status trong README.

**Cắt ranh giới trước khi viết code tiết kiệm nhiều hơn tưởng.** Kế hoạch đầu tiên
lấn sang `src/agents/nodes/approval.py`, tức giữa ticket HITL của Nhân. Sau khi
đối chiếu AC mới thấy việc nối agent vào cổng **thuộc về AC2 của ticket đó** (state
invalidation cần state authoritative), không phải việc phát sinh. Kết quả: giao
bằng tài liệu 8 điểm migrate + 4 bẫy đã verify hộ, thay vì hai người cùng sửa một
file.

## 🧭 Quyết định 2026-08-12 — composer sổ tay: đo xong thì chọn ngược lại điều đã đề xuất

**ADR-015 bị chính phép đo của nó bác bỏ.** Bản đầu tôi viết: nhánh tra sổ tay soạn
câu bằng SLM, và SLM là *phụ thuộc bắt buộc*. Sau khi có số thì kết luận lật hẳn —
và điều đáng ghi lại không phải việc lật, mà là **lý do lật không phải lý do tôi
tưởng sẽ gặp**.

Tôi đã chuẩn bị tinh thần rằng SLM sẽ trượt vì **chậm** hoặc vì **bịa**. Cả hai đều
sai. Độ trễ cuối cùng là 2,08 s — nằm trong mục tiêu. Bịa nguyên khối thì gần như
không có. Thứ giết phương án đó là một lớp lỗi tôi không hề dự trù: **tóm tắt làm rơi
điều kiện**. Sổ tay xe đầy "nếu được trang bị", "bản ECO / bản PLUS", "pin SDI /
CATL", và một bản tóm 1–2 câu **về cấu trúc** không chở nổi chúng. Case RAG-130: sổ
tay là một *bảng* áp suất lốp, model bốc một cột ra trình bày như giá trị chung — xe
pin CATL bơm theo đó là thiếu hơi. Ở vòng đo trước, cùng câu hỏi ấy model trả lời
"xem nhãn dán trên cột trụ", tức **an toàn hơn**. Cải thiện cấu hình làm câu trả lời
cụ thể hơn, mà cụ thể hơn ở đây nghĩa là nguy hiểm hơn.

Tỷ lệ lỗi đi 5/40 → 4/40 qua **ba** vòng sửa cấu hình. Ba vòng mà không nhúc nhích
thì đó là **sàn của cách tiếp cận**, không phải chỗ còn tinh chỉnh được.

**Ba lỗi cấu hình của tôi, và vì sao chúng đáng ghi hơn kết quả.** Mỗi lần tìm ra một
lỗi thì con số đổi và kết luận suýt đổi theo: thiếu stop-string (p50 12,1 s — đo cái
đuôi rác chứ không đo composer); p50 3,28 s hoá ra là **số ưu ái** vì dataset xếp
theo chủ đề nên prompt cache trúng, đo lạnh thật là 7,4–8,6 s; và nặng nhất — tôi
**chưa từng dùng chat template của Qwen-Instruct** trong bất kỳ phép đo composer nào,
nên model không có `<|im_end|>` để dừng và nhại lại nguyên văn chỉ thị hệ thống.
Nhánh planner không lộ lỗi này vì grammar chặn hộ. Bài học: **một con số tệ là giả
thuyết về cấu hình trước khi là kết luận về model.** Nếu tôi dừng ở vòng một thì đã
kết luận "SLM composer quá chậm" — sai, và sai theo hướng nghe rất thuyết phục.

**Cổng từ vựng là máy dò thoái hoá, không phải máy dò bịa.** Mọi câu sai đo được đều
dùng 100% từ vựng của evidence. Thị trường cũng đồng ý theo cách của họ: Bedrock tách
*hai* trục grounding và relevance, khớp đúng hai nhóm lỗi tôi chấm được. Tôi thử dựng
cổng chống đảo nghĩa bằng bảng cặp từ đối lập — **thất bại**, 4/5 báo động giả, vì
tiếng Việt dùng "sau đó" và "phía sau" cùng một chữ. Ghi lại như kết quả âm.

**Tự bắt mình chấm sai.** RAG-125 tôi gắn cờ "đảo nghĩa, điểm 1,0" và dùng nó làm ví
dụ đắt nhất trong lập luận. Sai: câu minh oan nằm ở ký tự ~250 của đoạn, ngoài khung
220–280 ký tự tôi in ra lúc chấm. Cái cứu tôi là cổng polarity **không chịu gắn cờ**
case đó, buộc tôi mở lại. Điểm an ủi duy nhất: hướng sai là một chiều — người chấm
thấy **ít** hơn model nên chỉ buộc tội oan được, không bỏ sót được.

**Và một bài học quy trình, trả giá thật.** PR #73 được merge lúc GitHub còn hiển thị
head cũ, nên develop hụt 1/6 commit — mất nguyên phần câu dẫn. Log merge trông hoàn
toàn bình thường. Thứ phát hiện ra là **kiểm nội dung** (`QwenLeadIn` = 0 lần xuất
hiện trên develop), không phải đọc log. Từ nay: sau mỗi merge, kiểm bằng thứ mã lẽ ra
phải có mặt, đừng tin tên commit.

---

## 🧭 Quyết định 2026-08-13 — gỡ voice correction layer, đo xong mới biết nó đang gây hại

Tiếp nối bug thật phát hiện khi test vocabulary tự động (2026-08-12): `correct_transcript()`
sửa nhầm "Kiểm" → "Hiểm" trên một câu giọng thật vốn đã đúng 100%. Câu hỏi đúng không phải
"vá vocabulary cho hết false-positive" mà là "tầng này còn giúp gì không, với engine hiện tại".

Đo trên toàn bộ 50 case (24 synthetic + 26 giọng thật thu tay), so raw Zipformer với cả
vocabulary cũ (47 từ, hand-typed) lẫn vocabulary mới (315 từ, auto-derive): **cả hai đều làm
WER trung bình tệ hơn không sửa gì** — 9,58% → 13,19%/9,90%. Vocabulary cũ hại 12/50 case,
chỉ giúp 1. Trên 5 case điều khiển đúng-domain (điều hòa, âm lượng, ghế sưởi, dẫn đường),
Zipformer đã nhận đúng cả 5 — tầng sửa lỗi không có lỗi thật nào để sửa, chỉ còn khả năng
phá câu đã đúng.

**Bài học lặp lại từ 2026-08-08/2026-08-12: giá trị nằm ở việc đo bằng dữ liệu thật, không
phải ở việc tin vào thiết kế cũ.** Correction layer được xây (ADR-009/012) để bù WER ~26% của
PhoWhisper. Đổi engine sang Zipformer (ADR-017, WER ~8%) làm premise gốc không còn đứng vững,
nhưng không ai đo lại — tới khi vocabulary auto-derive mở rộng blast radius và một false
positive thật xuất hiện thì mới có lý do để đo. Quyết định: gỡ bỏ hẳn (ADR-018), không xây
cơ chế thay thế — nếu tương lai đổi engine khác có error rate cao hơn hẳn, thiết kế lại lúc
đó dựa trên error profile thật của engine đó, không phục hồi code đã xoá theo mặc định.

---

## 🧭 Ghi chú 2026-08-15 — token chết là bình thường; ba chỗ nuốt lỗi mới là bug

Người dùng báo lỗi "token không hợp lệ hoặc đã hết hạn" và màn hình kẹt lại. Điều tra
cho ra ba lớp, và chỉ lớp thứ ba đáng gọi là bug:

1. **Token nằm trong RAM** (`src/services/auth.py`) nên restart backend vô hiệu hoá mọi
   token còn hạn. Đây là quyết định có chủ đích của issue #46 — `docs/data_model.md`
   không thiết kế bảng token, và ghi bí mật ngắn hạn xuống đĩa là thêm bề mặt lộ. **Giữ
   nguyên.**
2. **401 dùng chung một câu** cho "hết hạn" và "không tồn tại", nên ca hay gặp nhất
   (restart) bị chẩn đoán nhầm nhiều lần. Sửa `message`, **không** thêm mã lỗi mới:
   client xử lý hai ca giống hệt nhau, chỉ người đọc log cần phân biệt.
3. **Frontend không fail-closed với lỗi xác thực.** `getStoredSession()` chỉ biết
   `expiresAt` do chính client giữ, nên nó tin là còn đăng nhập trong khi mọi request đều
   401; toast tắt sau 3,2 giây và không còn dấu vết nào.

Điều đáng ghi lại là **vì sao lớp 3 tồn tại**: nó là tổng của ba lựa chọn hợp lý riêng lẻ
— `.catch(() => {})` ở nhịp poll 2 giây, một `return` câm trong `connect()` khi mất
session, và một `close` handler không nhận `event` nên không đọc được mã đóng 4401. Cả ba
đều đúng cho **lỗi mạng tạm thời**, thứ tự khỏi khi mạng về. Không cái nào đúng cho lỗi
xác thực, thứ không bao giờ tự khỏi. Quy tắc rút ra: mỗi lần thêm một nhánh nuốt lỗi,
phải trả lời được "lỗi nào ở đây KHÔNG được nuốt".

Phần chọn **không** làm cũng đáng ghi: không persist token xuống SQLite và không đổi sang
token ký HMAC. Cả hai đều giữ được phiên qua restart, nhưng không cái nào chạm tới ca
token hết hạn thật — mà đó mới là ca phải xử lý đúng. Sửa chỗ kẹt trước; giữ phiên qua
restart là tiện lợi cho người dev, không phải bản chất của bug.

Bug cuối cùng của buổi thì chỉ chạy tay mới thấy: banner báo lý do không hiện dù redirect
đúng, vì cleanup của `useEffect` xoá thông báo và React StrictMode ở `next dev` mount →
unmount → mount. 109 test frontend xanh không thấy, ba phút chạy thật thì thấy.

## 🧭 Quyết định 2026-08-28 — dashboard kỹ sư là hộp đen, không phải phòng thí nghiệm

Câu hỏi mở đầu là "ghi log offline, đánh giá online bằng LLM judge — được không?".
Trả lời được nó phải nói ra trước một thứ chưa ai viết xuống: **dashboard kỹ sư để
làm gì.**

Đọc code thì ranh giới đã có sẵn và rất nhất quán, chỉ chưa thành chữ. `TraceRecord`
toàn field **cơ chế** (`route_source`, `max_safety_level`, `block_code`,
`admission_status`, bảy stage latency), không một field **chất lượng** nào.
`/metrics/summary` là fold thuần. `rag.grounded_rate` cố ý chỉ đếm `citation_count > 0`
và nhường câu "trích đúng không" cho `src/rag/evaluate.py` chạy offline. Tức là:
**dashboard trả lời câu hỏi kiểm chứng được ngay tại chỗ; câu hỏi cần đáp án khoá thì
đẩy sang `eval/`.** Cái mock `isMock: true` không phải lỗ hổng chờ mô hình lấp — nó là
ô trống chờ artifact.

Ba lý do "chấm lượt thật" bị để ngoài phạm vi, xếp theo sức nặng thật:

1. **Không có lưu lượng.** Ngành lấy mẫu 1–10% traffic sản xuất. 1–10% của vài chục
   lượt demo là không ca nào. Lý do thực dụng này mạnh hơn mọi lý do nguyên tắc.
2. **Ta cố ý không lưu thứ cần để chấm.** ADR-029 giữ `answer_text` và bỏ transcript
   lẫn citation text. Judge sẽ chấm câu trả lời mà không có câu hỏi lẫn bằng chứng.
3. **Số không có run id thì không phải bằng chứng.** Judge không tất định; không ghim
   model + prompt + ngày thì hai lần chạy ra hai số mà không ai biết vì hệ thống đổi
   hay vì judge đổi ý.

Cửa này **để mở**: cấm vì thiếu điều kiện, không phải cấm vì nguyên tắc.

**Chỗ tôi phải sửa lại chính mình.** Tôi phản biện lúc đầu rằng chấm lượt thật là sai
phương pháp. Tra thì ngành làm việc đó hằng ngày — LangSmith, Langfuse, Arize đều có
"online eval" chạy LLM judge trên traffic sản xuất, lấy mẫu, bất đồng bộ, chấm bù về
sau. Cái tôi nói đúng là *điều kiện*, không phải *lệnh cấm*. Và tra cũng bác luôn một
lo ngại tôi đã nêu chắc nịch: tôi bảo judge thích câu dài nên sẽ chống lại SP-3 (vốn
đang đi cắt câu ngắn); khảo sát 2026 trên 21 model đo tương quan độ dài–phán quyết
< 0,011, tức thiên lệch đó gần như đã biến mất so với thời 2023.

**Con số đáng nhớ nhất từ vòng tra cứu:** LLM judge khớp thô với người 80–85%, nhưng
Cohen's κ chỉ 0,376–0,511 — tức tỷ lệ khớp **thổi phồng 33–41 điểm phần trăm** vì
không trừ phần trùng do may rủi. Và một cảnh báo ngược đời: hai judge chạy sản xuất
đạt độ lặp lại > 0,988 mà vẫn lệch vị trí > 0,12. **Ổn định cao kèm thiên lệch cao là
kiểu hỏng, không phải điểm mạnh.** Nên nếu C được duyệt, cổng phát hành là κ chứ không
phải độ chính xác, và bước đầu tiên không phải gọi API mà là **cho người thứ hai chấm
tay** — hiện repo mới có một người chấm 40 ca, nên chưa ai biết rubric có rõ ràng không.

Quyết định trong ngày, phần đã làm: bỏ ô "Độ chính xác ý định" thay vì gắn nó vào số
thật. Số thật là 1.0000 trên bộ `agent/v3` — tripwire hồi quy do chính tác giả router
soạn. Thay số bịa bằng số vô nghĩa-nhưng-có-vẻ-có-nguồn là làm dashboard tệ đi, không
phải trung thực hơn. Ba ô còn lại lấy từ suite `rag`, nơi đáp án khoá đến từ sổ tay
VF9 chứ không từ người viết hệ thống.

# ADR-015: Nhánh tra sổ tay soạn câu trả lời bằng trích nguyên văn, SLM chỉ viết câu dẫn

> Tiêu đề cũ: *"SLM là phụ thuộc bắt buộc của nhánh tra sổ tay"*. Đề xuất đó **bị chính
> phép đo của nó bác bỏ** — giữ nguyên ở [Phụ lục A](#phụ-lục-a--đề-xuất-ban-đầu-giữ-để-đối-chiếu)
> để đối chiếu. Số hiệu và tên file giữ nguyên vì issue #62 và PR #59 đang trỏ vào.

- Status: **Accepted** (2026-08-12). Thành duyệt bản sửa tại
  [issue #62](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/62) — *"Mình
  đồng ý với phương án A… Mình đồng ý sửa ADR-015 theo 4 điểm đề xuất"*; issue đã đóng.
  Đã cài đặt và merge: PR #73 (trích nguyên văn) và PR #74 (câu dẫn SLM).
- Date: 2026-08-11, sửa 2026-08-12
- Decision owner: WS2 Agent & Safety (Nhân)
- Liên quan: ADR-003, ADR-005, ADR-011, ADR-016, `docs/agent_spec.md`, issue #62, issue #48 / commit `b2e5724`

## Cập nhật 2026-08-12 — vì sao quyết định đổi

Bản đầu của ADR này được soạn khi **chưa có số nào về composer**. Nay có, tại
`eval/results/spike-003/` (chấm tay từng câu trong `graded.jsonl` mỗi run; tóm tắt ở
`docs/reports/SPIKE-003-notes.md`), trên 40 case `supported` của `eval/datasets/manual/v1`:

| Cách soạn câu trả lời | p50 | p95 | Câu gây hiểu lầm / 40 | Run |
|---|---:|---:|---:|---|
| SLM đọc 5 đoạn rồi viết (như bản đầu hình dung) | 7,4–8,6 s | — | 5 | `20260811T172552.542828Z` |
| **A — trích nguyên văn (+ câu dẫn)** | **827 ms** | **1.188 ms** | **0 về dữ kiện** | `20260811T200114.021276Z` |
| B — SLM viết lại một đoạn | 2.080 ms | 3.393 ms | 4 | `20260811T200114.021276Z` |

Hai điều phép đo dạy, cả hai đều ngược với giả định của bản đầu:

1. **Độ trễ không còn là lý do bác bỏ SLM.** 2,08 s nằm trong mục tiêu p50 ≤ 2.500 ms.
2. **Lý do thật nằm ở chỗ khác, và nó thuộc bản chất của việc tóm tắt.** Sổ tay xe đầy
   điều kiện: "nếu được trang bị", "bản ECO / bản PLUS", "pin SDI / CATL". Một bản tóm
   1–2 câu **về cấu trúc** không chở nổi chúng. Ca nặng nhất là RAG-130: sổ tay là một
   *bảng* áp suất lốp, SLM bốc một cột (ECO + SDI) ra trình bày như giá trị chung — xe
   pin CATL bơm theo đó là **thiếu hơi**. Ở vòng đo trước, cùng câu hỏi ấy SLM trả lời
   *"xem nhãn dán trên cột trụ"*, tức **an toàn hơn**: cải thiện cấu hình làm câu trả
   lời cụ thể hơn, mà cụ thể hơn ở đây nghĩa là nguy hiểm hơn.

Tỷ lệ lỗi đi 5/40 → 4/40 qua **ba** vòng sửa cấu hình (thêm stop-string, thêm reranker,
dùng đúng chat template). Đọc đó là **sàn lỗi của cách tiếp cận**, không phải chỗ còn
tinh chỉnh được.

Trích nguyên văn thì bảng và chữ "nếu được trang bị" **đi kèm theo** — lớp lỗi trên
không tồn tại về mặt cấu trúc, chứ không phải được giảm thiểu.

## Quyết định

Nhánh tra sổ tay soạn câu trả lời theo **phương án A**:

```
câu hỏi → retriever → (reranker, tuỳ chọn) → đoạn hạng 1
        → câu dẫn   : chuỗi cố định; SLM viết nếu `slm_enabled`
        → nội dung  : TRÍCH NGUYÊN VĂN đoạn hạng 1
        → citation  : section + trang (không đổi)
```

**SLM không phải phụ thuộc của nhánh này.** Nó chỉ chạm phần câu dẫn, mà câu dẫn
**không mang một dữ kiện nào** — không có gì để bịa, để đảo nghĩa, hay để làm rơi điều
kiện. Bật hay tắt SLM đổi độ tự nhiên của một câu khung, **không đổi nội dung tài xế
nhận được**. Với `slm_enabled=False` (mặc định, mọi máy trong nhóm hôm nay) nhánh này
chạy đầy đủ.

### Ràng buộc bắt buộc của phương án A

1. **Nguồn trích là `evidence[0].text`, không phải `citation.excerpt`.**
   `EXCERPT_CHARS = 300` (`src/rag/retrieve.py`) trong khi **39/40 đoạn thật dài hơn
   300 ký tự** (min 199, p50 950, max 2.416). Trích từ excerpt là tái tạo đúng lỗi cắt
   cụt điều kiện an toàn mà quyết định này sinh ra để tránh.
2. **Cắt bớt phải nhìn thấy được.** Quá `QUOTE_MAX_CHARS = 1200` (bao trọn 34/40 đoạn)
   thì cắt ở ranh giới câu **và** nói rõ còn tiếp, kèm mục + trang. Lỗi của phương án
   SLM là bỏ sót *âm thầm*; ở đây bỏ sót phải lộ ra.
3. **Thiếu evidence thì về đúng câu cố định hôm nay**, không sập.

Đã cài đặt trọn vẹn cả hai phần: trích nguyên văn ở `src/agents/nodes/compose.py`, câu
dẫn ở `QwenLeadIn` (`src/agents/slm.py`) gọi từ `rag_stage` (`src/agents/graph.py`) và
nối qua `src/api/session_state.py`. Test: `tests/test_agents/test_grounded_answer_quote.py`,
`tests/test_agents/test_grounded_lead_in.py`.

**Câu dẫn fail-open, khác hẳn nhánh planner.** SLM tắt, llama-server chết, timeout, hay
trả chuỗi rỗng đều rơi về chuỗi cố định — nội dung tài xế nhận **không đổi một chữ**.
Đây là chỗ hợp đồng của ADR này thành mã chạy được, không phải lời hứa.

## Hệ quả

Ba trong bốn hệ quả nặng của bản đầu **tan biến** vì SLM không còn là phụ thuộc:

1. ~~Tra sổ tay ngừng chạy trên demo~~ — không còn: nhánh chạy với `slm_enabled=False`.
2. ~~Xung đột với quyết định issue #48 về `/healthz`~~ — không còn. Thiếu SLM không phải
   suy giảm tính năng, chỉ là câu dẫn kém tự nhiên hơn; không phát sinh refusal nào.
   Giữ nguyên quyết định #48 như Thành đề nghị ở #62.
3. ~~Thêm một lần gọi SLM vào ngân sách độ trễ~~ — không còn ở đường mặc định.
4. **`README.md` / `CLAUDE.md`**: vẫn đúng khi ghi *"No LLM runs on this path today"* —
   **không cần sửa** theo ADR này. (Việc sửa chúng gắn với ADR-016 khi SLM planner được
   bật, không gắn với ADR này.)

Hệ quả mới, nhỏ nhưng phải nói: câu trả lời **dài hơn hẳn** (p50 ~950 ký tự thay vì một
câu). Piper chưa nối nên chưa nghe thấy; khi nối TTS phải xét lại độ dài đọc.

## Cập nhật 2026-08-14 — kênh NÓI tách khỏi kênh HIỂN THỊ

Dòng cuối mục "Hệ quả" ở trên đã thành hiện thực đúng như nó dự báo, và nặng hơn dự
báo. Khi Piper được nối (issue #66), một lượt tra sổ tay phát ra **4,60 MB / 65,6 giây
audio** trong một event `assistant.speech`: vượt **449%** trần khung 1 MiB mặc định của
thư viện `websockets`, và không tài xế nào nghe hết 65 giây sổ tay khi đang lái.

**Quyết định của ADR này không đổi.** `display_text` vẫn là trích nguyên văn, vẫn
`evidence[0].text`, vẫn cắt-có-báo ở `QUOTE_MAX_CHARS`. Cái được thêm là một kênh thứ
hai: `speak_text`, chịu ràng buộc khác vì tai người khác màn hình.

### Ba tầng đã đo

| | trúng ngay lượt đầu | tới được câu trả lời | chi phí |
|---|---:|---:|---|
| Trước (đọc cả đoạn) | — | — | 65,6 s một lượt, 4,60 MB |
| **S1** — luật chọn câu | 37,5% | 37,5% | 9,4 s p50 / 11,4 s p95 |
| **S2** — SLM chọn câu | 40,0% | 40,0% | +664 ms/lượt, +1 ca ròng |
| **S1 + S3** — mời nghe tiếp | 37,5% | **97,5%** | 2 lượt p50, 17 s p50 |

Run: `eval/results/rag/20260814T030929Z`. Chấm bằng đáp án khoá
(`eval/datasets/manual/v1/answer_keys.jsonl`) — đọc 40 đoạn nguồn **một lần, trước khi
nhìn đầu ra của bất kỳ phiên bản nào**, ghi ra cụm chữ nào thật sự trả lời; sau đó chấm
là thao tác máy, cùng một khoá áp cho mọi phiên bản.

### S2 — kết quả âm, ghi lại để khỏi đo lại

**SLM chọn câu không cải thiện được so với luật.** 40,0% so với 37,5% nghe như hơn,
nhưng nhìn từng ca thì S2 **hơn ở 11 ca và kém ở 10 ca** — xáo bài, không phải cải
thiện. Nếu model chọn câu giỏi hơn luật thì phải thấy lệch hẳn về một phía.

Đây **không** phải phương án B bị bác ở mục dưới: S2 trả về **chỉ số câu**, không sinh
chữ nào, nên lớp lỗi "làm rơi điều kiện theo phiên bản" không dựng lên được. Nó bị bác
vì **không đủ hữu ích để trả giá**: một tiến trình llama-server thường trực, +664 ms im
lặng mỗi lượt, và một đường hỏng mới, đổi lấy +1 ca trên 40.

Cài đặt vẫn giữ trong `src/agents/nodes/speech_policy.py` (`SentenceSelector` + ba cổng
kiểm chứng) và tắt theo mặc định — bật bằng `--slm-select` ở bộ đo. **Điều kiện mở
lại:** khi tầng truy hồi khá lên tới mức đoạn hạng 1 chứa nhiều câu ứng viên hơn, chọn
câu mới có chỗ để thắng.

### S3 — chỗ thật sự ăn điểm

`37,5% → 97,5%` bằng một luật router (`manual_continue`) và hai field state. Đổi thước
đo là một phần của kết quả: với S3, *"một phần"* không còn là một mức điểm mà là một
**khoảng cách** — đo bằng số lượt và số giây, vì hai câu cùng "một phần" mà một câu tới
sau 1 lượt còn câu kia sau 5 lượt là hai trải nghiệm khác hẳn.

Ca duy nhất S3 không cứu được là RAG-106 — đoạn hạng 1 không hề chứa câu trả lời. Đúng
một ca, và là ca đúng: bài của tầng truy hồi, không phải tầng nói.

**Câu khung fail-closed cũng tới được.** `variant_fallback` không lấy chữ nào từ đoạn
nên "nghe tiếp" đọc từ đầu: nó từ chối *tóm tắt*, không từ chối *đọc*. Fail-closed một
mình là ngõ cụt; fail-closed **cộng** một đường ra mới là câu trả lời đầy đủ.

### Bất biến an toàn giữ nguyên, và được đo mỗi run

`doc so o doan bien the` = **0/41** qua mọi thay đổi ở trên. Đoạn RAG-130 vẫn ra nhánh
`pointer`, kể cả sau khi cờ biến thể được nới (xem dưới) — lưới thứ hai là `is_table`
cộng có-số, và nó đỡ độc lập.

Cờ `has_variant_condition` được **tách làm hai lớp** ngày 14/08 sau khi đo thấy 5/7 ca
"không trúng" là do cổng an toàn tự chặn oan:

- *"nếu được trang bị"* = **xe bạn có thể không có tính năng này**. Nói ra không nguy
  hiểm; vế điều kiện chỉ cần đi kèm, mà trích nguyên văn thì tự đi kèm. → thôi từ chối.
- *ECO / PLUS / SDI / CATL* = **cùng đại lượng, giá trị khác nhau**. Đây mới đúng là
  lớp ADR này đo được 4/40 câu gây hiểu lầm. → giữ nguyên từ chối.

Tỷ lệ gắn cờ 48/482 (10,0%) → 6/482 (1,2%); soi tay cả 9 chunk mất cờ mà vẫn mang số:
không cái nào thuộc lớp giá-trị-khác-nhau. Đổi lại, an toàn giờ dựa vào vế điều kiện đi
kèm câu nói, nên `speech_policy` gắn thêm *"Tuỳ phiên bản, xe bạn có thể không có tính
năng này"* khi và chỉ khi đoạn tuỳ-trang-bị **và** câu nói thật sự đọc ra một đại lượng
**và** chưa mang sẵn điều kiện.

### "Nguyên văn" ở mức câu, không mức ký tự

Nói cho chính xác vì cả ADR này đứng trên chữ đó: `speak_text` chuẩn hoá khoảng trắng
(`
` của sổ tay thành một dấu cách) vì đó là chuỗi đưa cho TTS. Không chữ nào bị đổi,
nên bất biến vẫn nguyên — nhưng nói "nguyên văn tuyệt đối" thì không đúng.

### Rủi ro tồn đọng

- **Chưa có barge-in.** p95 34 giây của S3 là 34 giây tài xế **không ngắt được**. Đây là
  giới hạn thật của trải nghiệm, không phải chi tiết kỹ thuật; barge-in là việc phía FE.
- **Trạng thái đọc dở chết cùng tiến trình** — có chủ ý, nó là ngữ cảnh hội thoại chứ
  không phải dữ liệu cần bền, y như checkpoint giữ `interrupt()` của HITL. Backend
  restart giữa chừng thì "đọc tiếp" trả lời *"Tôi đã đọc hết phần này rồi"*, tử tế
  nhưng hơi sai sự thật.
- ~~Frontend chưa phát audio~~ — **đã hết** (PR #91/#99, merge 13/08, thấy khi gộp
  develop ngày 14/08). `DriverShellProvider.tsx` phát `assistant.speech` qua
  `new Audio('data:...')`, và `wavRecorder.ts` ghi WAV thật qua `getUserMedia`. Chuỗi
  microphone → STT → TTS → loa **đã liền** lần đầu tiên. Thứ chưa có là bằng chứng
  *chất lượng* của chuỗi đó: chưa có WER người nói thật, chưa đo độ trễ end-to-end.

### Trạng thái chốt

**Chốt (Nhân, decision owner, 2026-08-14): nhận S1 + S3, không bật S2.** Ba số ở bảng
trên là căn cứ; muốn giữ S2 thì phải nêu lý do **ngoài** chất lượng chọn câu, vì chiều
đó đã đo và không phân biệt được với nhiễu.

## Đã đo và **chưa** nhận: phương án B (SLM viết lại một đoạn)

Ghi lại để sau này không ai phải đo lại chuyện đã đo.

- **Không** bị loại vì độ trễ (2.080 ms, trong mục tiêu) và **không** bị loại vì bịa
  nguyên khối. Bị loại vì **bỏ điều kiện theo phiên bản** khi tóm tắt.
- Điểm tích cực đã đo, đừng bỏ quên: với reranker, B **từ chối đúng cách** ở RAG-108
  (hỏi sưởi ghế, đoạn hạng 1 là "sưởi vô lăng", rerank score −0,948) thay vì bịa quy
  trình như vòng trước.
- **Điều kiện mở lại:** (a) có cơ chế giữ được điều kiện theo phiên bản khi tóm tắt,
  **và** (b) đo lại trên bộ case **chưa từng đọc tay** — 40 case hiện có đã bị dùng để
  chấm nên chỉ còn giá trị làm dây bẫy hồi quy.

## Reranker — ticket riêng, mặc định tắt

`BAAI/bge-reranker-v2-m3` chạy được ngay trên llama.cpp đã pin (`--reranking`):
**p50 ~280–330 ms trên GPU, RAM +2 MB** vì trọng số nằm VRAM
(`eval/results/spike-003/20260811T185854.521708Z`). Chấm tay 9 case đổi hạng: 7 tốt hơn,
2 xấu đi; hit@1 mức section 35/40 → 38/40.

Phải **mặc định tắt**, cùng cơ chế `slm_enabled`: trên CPU nó tốn **2,8 s và 1,3 GB
RAM**, không thể bật mặc định cho máy không GPU. Bản Q8 lật 2/40 thứ hạng so với fp32,
trong đó RAG-108 lật về phía **sai** — phải đo FP16 trước khi chốt mức lượng tử.

## Cổng kiểm chứng: `rag_grounding_min_support` hết việc

Bản đầu đặt điều kiện Accept là hiệu chỉnh ngưỡng này. **Với phương án A tham số đó
không còn việc gì để làm**: trích nguyên văn thì grounding bằng 1 theo cấu trúc. Không
để lại một nút vặn không còn tác dụng — nếu đã có trong code/config thì gỡ, chưa có thì
đừng thêm.

Phép đo cũng cho một kết luận đáng giữ về loại cổng này: trên bộ 40 case,
`lexical_overlap` **không phải máy dò bịa** mà là máy dò thoái hoá — mọi câu sai đều
dùng 100% từ vựng của evidence. Một cổng chống đảo nghĩa bằng bảng cặp từ đối lập cũng
đã thử và **trượt** (5 cờ, 4 báo động giả; xem `scripts/spike3_polarity.py` và mục tương
ứng trong `SPIKE-003-notes.md`). Kết luận: nếu sau này lại sinh chữ, đừng dựa vào cổng
từ vựng.

## Điều kiện để chuyển sang Accepted

1. ~~Cả nhóm duyệt tại issue #62~~ — **xong 2026-08-12**, Thành duyệt, issue đã đóng.
2. ~~Hiệu chỉnh `rag_grounding_min_support`~~ — không còn áp dụng, xem mục trên.
3. ~~Sửa `README.md`/`CLAUDE.md`~~ — không còn áp dụng, xem Hệ quả 4.

Cả ba điều kiện đã giải quyết → **Accepted**.

---

## Phụ lục A — đề xuất ban đầu, giữ để đối chiếu

Nguyên văn quyết định bản đầu (2026-08-11), **đã bị bác bỏ** bởi các phép đo ở trên:

> Nhánh tra sổ tay **soạn câu trả lời bằng SLM**, và SLM là **phụ thuộc bắt buộc** của
> nhánh đó: `slm_enabled=False`, thiếu weights, lỗi, hoặc timeout đều dẫn tới
> `grounded_refusal`. Không có đường rơi về trích xuất nguyên văn.

Hai phương án bản đầu **loại**, mà phép đo cho thấy loại nhầm:

> **Trích xuất nguyên văn (khuôn mẫu + excerpt).** […] Loại vì nhóm muốn câu trả lời
> tổng hợp được nhiều evidence, thứ ghép chuỗi không làm được.
>
> **Trích xuất làm sàn, SLM làm lớp nâng cấp.** […] Loại vì nhóm muốn hợp đồng dứt
> khoát — có SLM hoặc từ chối — thay vì hai chất lượng đầu ra tuỳ môi trường.

Lý do "muốn tổng hợp nhiều evidence" là chỗ sai then chốt: phép đo cho thấy đưa **nhiều**
đoạn cho model chính là cơ chế sinh ra lỗi trộn đoạn và đảo nghĩa (RAG-104, RAG-106), và
việc tổng hợp ấy **đánh đổi bằng chính các điều kiện an toàn** của sổ tay. Bản đầu cũng
đã tự nêu đúng rủi ro tồn đọng ("SLM đánh rơi một chữ *không*… câu bị đảo nghĩa có thể là
câu về an toàn") nhưng vẫn chọn đi tiếp — phép đo cho thấy rủi ro đó là thật và không
sửa được bằng chỉnh ngưỡng, đúng như chính bản đầu đã cảnh báo.

Phần **Context** của bản đầu vẫn đúng nguyên vẹn và là lý do ADR này tồn tại: nhánh tra
sổ tay trước đây chỉ trả một câu cố định, nội dung thật nằm trong `citations[].excerpt`,
nên tài xế nghe TTS **không nghe được nội dung nào cả**. Phương án A sửa đúng vấn đề đó.

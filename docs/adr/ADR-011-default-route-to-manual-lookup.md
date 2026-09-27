# ADR-011: Mặc định định tuyến sang tra sổ tay, không phải `not_control`

- Status: Accepted
- Date: 2026-08-08
- Decision owner: WS2 Agent/RAG (tiếp nối [ADR-010](ADR-010-canonical-tool-registry-with-product-vision-adapter.md), tracker SCRUM-16 + SCRUM-17)

## Context

Sau khi SCRUM-16 hoàn thành, router luật đạt 100% trên dataset `agent/v3` — nhưng
dataset đó do chính người viết router soạn ra. Đo lại bằng
[`eval/datasets/manual/v1/cases.jsonl`](../../eval/datasets/manual/v1/cases.jsonl)
(60 câu hỏi sổ tay, do workstream RAG soạn cho mục đích khác, không ai viết nó để
kiểm tra router) cho kết quả rất khác:

| Kết quả định tuyến | Số case | Ví dụ |
|---|---:|---|
| Tới được RAG (`manual_query`) | **5 / 60 = 8,3%** | — |
| Rơi vào `not_control/none` | 49 | `"Cách khởi tạo lại cửa sổ điện?"` |
| Bị **từ chối** do lỗi `có…không?` | 3 | `"Ghế xe có chức năng massage không?"` |
| Bị từ chối do trùng từ khóa actuator | 2 | `"Cách thay dầu động cơ xăng của VF9"` |
| Bị hiểu nhầm thành lệnh | 1 | `"Chỉnh nhiệt độ và tốc độ quạt gió thế nào?"` |

Trong khi đó bản thân RAG **không có vấn đề**: run
`eval/results/rag/20260807T102012Z/` ghi `recall_at_k=1.0`, `grounded_rate=1.0`,
`citation_validity=1.0`, `hallucination_rate=0.05` trên 40 positive + 20 negative.
Nút thắt nằm hoàn toàn ở router: nó chặn 91,7% câu hỏi trước khi chúng tới được
một hệ thống truy hồi đang hoạt động tốt.

Ba nguyên nhân gốc:

1. **Bộ nhận diện câu hỏi là danh sách 8 cụm từ cứng** (`như thế nào`, `nghĩa là gì`,
   `thì xử lý`, …). Hỏi bằng cách diễn đạt khác là trượt.
2. **Regex phủ định `\bkhông\b` không phân biệt được phủ định với nghi vấn.** Trong
   tiếng Việt `có … không?` là dạng câu hỏi có/không, nhưng router đọc thành
   `negated_command` và **từ chối thẳng**.
3. **Mặc định khi không khớp luật nào là `not_control/none`** → nhánh SLM → `clarify`.
   Câu hỏi sổ tay hợp lệ nhận về `"Tôi chưa rõ bạn muốn điều khiển gì."`

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Mở rộng danh sách cụm từ hỏi | Thay đổi nhỏ, ít rủi ro hồi quy | Vẫn là danh sách hữu hạn. Câu hỏi không chứa từ để hỏi nào (`"Đèn chào mừng"`, `"Quy trình sạc nhanh"`) vẫn trượt. Chữa triệu chứng, không chữa nguyên nhân 3 |
| Để SLM phân loại lệnh vs câu hỏi | Mạnh nhất về nguyên tắc | Cần weight thật (chưa có bằng chứng, SPIKE-001 = Not Yet); chậm hơn nhiều; trái `agent_spec.md` §Agent boundary (deterministic-first cho lệnh P0 rõ ràng) |
| **Đảo mặc định: nhận diện lệnh thật chặt, còn lại đều tra sổ tay** (đã chọn) | Chữa đúng nguyên nhân 3. Không phụ thuộc model. Hành vi mặc định đúng với sản phẩm: trợ lý trong xe nghe câu lạ thì tra sổ tay. RAG tự từ chối có căn cứ khi thiếu evidence | RAG trở thành phụ thuộc của đường mặc định — thiếu index thì mọi câu lạ đều từ chối. Câu tán gẫu cũng đi vào RAG |

## Decision

**Đảo mặc định của router.** Thứ tự xử lý mới trong `DeterministicControlRouter._match`:

```
1. Nhận diện CÂU HỎI       → manual_query → RAG      (chạy TRƯỚC mọi guard)
2. Guard phủ định           → denied                  (đã sửa luật `không`)
3. Đại từ mơ hồ             → clarify
4. Sáu matcher lệnh         → control
5. Actuator ngoài registry  → denied                  (chỉ khi câu trông như lệnh)
6. MẶC ĐỊNH                 → manual_query → RAG
```

Ba thay đổi cụ thể:

1. **Luật `không`.** `không` là phủ định khi đứng trước động từ; là **tiểu từ nghi
   vấn** khi là token cuối câu. `"Không phát nhạc"` vẫn `denied`;
   `"Ghế xe có chức năng massage không?"` thành câu hỏi.

2. **Câu hỏi không bao giờ thực thi.** Dấu hiệu nghi vấn (`thế nào`, `ra sao`,
   `làm sao`, `là gì`, `tại sao`, `khi nào`, `ở đâu`, `bao nhiêu`, `bao lâu`,
   `cách` ở đầu câu, `có…không`, hoặc câu kết thúc bằng `?`) → không đi vào
   executor, dù nội dung có khớp một luật điều khiển.

   Câu hỏi **khớp** một luật điều khiển đi vào disposition mới **`offer`**: nêu rõ
   việc sẽ làm rồi hỏi lại, không làm. `"Mở cửa sổ bên lái 30% được không?"` trả
   về *"Tôi có thể mở kính trước bên lái lên 30%. Bạn có muốn tôi thực hiện
   không?"* Câu hỏi **không** khớp luật nào đi vào RAG như thường.

3. **Mặc định là `manual_query`**, không phải `not_control/none`.

`?` phải được đọc **trước** `normalize_vi` — hàm đó xoá dấu câu.

## Rationale

- Nguyên nhân 3 là nguyên nhân duy nhất giải thích được 49/60 case trượt. Sửa hai
  nguyên nhân kia mà giữ mặc định cũ chỉ vớt lại được 11 case.
- Hành vi mặc định mới đúng với sản phẩm hơn: một trợ lý trong xe nghe câu không
  hiểu thì tra sổ tay rồi trả lời hoặc từ chối có trích dẫn, chứ không nhún vai.
- Nó không làm yếu an toàn. Đường mặc định đi tới RAG là đường **chỉ đọc** (S0);
  mọi thứ có tác dụng phụ vẫn phải qua matcher lệnh chặt, rồi validator, rồi policy.
  Đảo mặc định làm hệ thống *nói nhiều hơn*, không làm nó *hành động nhiều hơn*.

## Consequences

- **Câu tán gẫu đi vào RAG.** `"Hôm nay trời đẹp quá"` sẽ nhận grounded refusal thay
  vì `not_control`. Chấp nhận được: câu trả lời "không có trong sổ tay" đúng hơn
  "tôi chưa rõ bạn muốn điều khiển gì". Hai case tương ứng trong `eval/datasets/agent/v3`
  đổi nhãn sang `manual_query`; đổi nhãn được ghi trong README của dataset.
- **RAG thành phụ thuộc của đường mặc định.** Thiếu index thì mọi câu lạ đều từ chối.
  Vì vậy `rag_node` phải **từ chối tử tế** thay vì sập: hiện nó bắt `(OSError, ValueError)`
  còn faiss ném `RuntimeError`, nên index thiếu lọt lên thành HTTP 500. Phải sửa cùng
  ADR này.
- **Chi phí mỗi lượt tăng.** Câu không khớp luật giờ phải tính embedding thay vì
  trả lời ngay. Chưa đo; cần đo trước khi tuyên bố gì về latency.
- **Lệnh lịch sự dạng hỏi tốn thêm một lượt.** `"Mở cửa sổ được không?"` giờ trả lời
  bằng một lời đề nghị chứ không mở kính ngay. Đây là đánh đổi có chủ đích: phân biệt
  nó với `"Phát nhạc từ USB được không?"` (hỏi năng lực) cần ngữ cảnh mà luật không
  có, nên mọi luật viết cho chỗ đó đều là đoán. Bỏ phép đoán đi thì `question_to_control`
  bằng 0 **về mặt cấu trúc**, không phải nhờ vá luật — và cổng đo được đúng thứ nó nói
  là đang đo.
- **Lượt trả lời "có"/"không" chưa được xử lý.** Branch này chỉ phát ra lời đề nghị.
  Việc hiểu câu trả lời ở lượt sau thuộc `recognize_approval_intent` mà
  `agent_spec.md` đã đặc tả cho branch HITL (SCRUM-18) — nó cũng cần đúng thứ đó
  (state phiên + nhận diện đồng ý/từ chối). Làm ở đây sẽ thành hai hệ xác nhận song
  song, chồng nhau và chắc chắn lệch nhau.
- **`RouteDecision` nới invariant.** Trước đây chỉ `control` mới được mang
  `candidate_plan`. Giờ `offer` cũng mang, vì lời đề nghị phải nêu chính xác việc sẽ
  làm. Ba disposition còn lại vẫn bị cấm.

## Revisit when

- Có câu lệnh thu từ người **ngoài nhóm**: cả hai dataset hiện tại đều do người
  trong nhóm viết. `manual/v1` độc lập với router (viết cho mục đích khác) nhưng vẫn
  không phải người dùng thật.
- Có weight Qwen chạy thật: khi đó so được luật vs SLM trên cùng bộ câu hỏi, và
  đánh giá lại xem lớp nhận diện câu hỏi bằng luật còn cần thiết không.
- Đo được chi phí latency của đường mặc định mới; nếu quá đắt, cân nhắc lọc rẻ
  trước khi gọi embedding.

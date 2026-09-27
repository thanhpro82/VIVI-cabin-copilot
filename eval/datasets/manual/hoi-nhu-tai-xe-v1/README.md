# `manual/hoi-nhu-tai-xe-v1` — hỏi bằng giọng tài xế, không bằng chữ của sổ tay

## Vì sao cần bộ thứ hai

`manual/v1` cho `recall@1 = 98%`, và tôi đã trích con số ấy nhiều lần để kết luận
*"truy hồi đã ổn, nút thắt nằm ở chọn câu"*. Kết luận đó **sai**, và bộ này cho thấy vì sao.

40 câu hỏi ở `manual/v1` do nhóm RAG viết **cho chính corpus này**, nên chúng dùng chữ
của đoạn. Đó là đúng khuyết điểm `CLAUDE.md` đã chỉ ra ở `agent/v3`, chỉ khác chỗ đứng.

| bộ | recall@1 | recall@8 |
|---|---|---|
| `manual/v1` | **98%** | 100% |
| `hoi-nhu-tai-xe-v1` | **55%** | 86% |

Chênh **43 điểm** trên cùng một hệ thống, cùng một index. Con số 98% đo **độ dễ của bộ
đề**, không đo năng lực truy hồi.

## Giao thức chống nhiễm

Vấn đề: tôi viết bộ này, mà tôi cũng vừa đọc rất nhiều chunk trong tuần. Ba ràng buộc để
chữ của đoạn không rò vào câu hỏi:

1. **Hạt giống là TÊN MỤC**, không phải thân đoạn. Mỗi ca lấy một mục trong 58 mục của
   index, và câu hỏi viết từ chủ đề ấy.
2. **Không đọc thân đoạn khi viết.** 35/42 mục ở đây chưa từng xuất hiện trong bộ 40 ca
   cũ, nên phần lớn là vùng tôi thật sự chưa đọc.
3. **Đáp án biết trước do CẤU TẠO.** Vì câu hỏi sinh từ tên mục, "mục đúng" là chính cái
   mục ấy — không có bước gán nhãn hậu kỳ nào để tôi vô tình chiều theo kết quả.

Câu chữ cố ý viết như tài xế nói, không như sổ tay viết: *"Bánh xe bị xịt giữa đường thì
xử lý sao"*, *"Kính mờ hết cả rồi nhìn không thấy đường"*.

## Thước ở đây THÔ hơn, biết trước

Nó hỏi *"top-k có chunk nào thuộc đúng mục không"*, chứ không phải *"đúng chunk nào"*.
Mục 22 chunk dễ trúng hơn mục 1 chunk. Đổi lại, nó **không cần gán nhãn tay** nên không
có chỗ cho thiên lệch chui vào. `scripts/do_truy_hoi.py` in kèm số chunk của mục ở các ca
trượt để độ khó nhìn thấy được.

## Độ phủ

42 ca / 42 mục, trong đó **35 mục chưa từng có trong `manual/v1`** (bộ cũ phủ 14/58 mục).

## Giới hạn

Vẫn là câu hỏi do một người trong nhóm nghĩ ra, và không ca nào đi qua ASR. Nó **giảm**
thiên lệch từ vựng chứ không gỡ được thiên lệch người viết. Muốn con số thật thì vẫn cần
người ngoài nhóm nói vào micro.

## Kết quả đo trên bộ này (18/08)

| cấu hình | @1 | @3 | @5 | @8 | trượt top-8 |
|---|---|---|---|---|---|
| dense (hiện tại) | 55% | 76% | 83% | 86% | 6 |
| **hybrid BM25+dense (RRF)** | **64%** | 79% | **88%** | 90% | 4 |
| dense + LLM context | 57% | 74% | 79% | 83% | 7 |
| hybrid + LLM context | 57% | 81% | 86% | 90% | 4 |

**Hybrid ăn, LLM context thì không** — nó còn làm tụt 7 điểm ở `@1` khi ghép với hybrid.

### Vì sao contextual retrieval không ăn ở đây

Không phải kỹ thuật sai, mà là **ta đã có phiên bản rẻ của nó rồi**: `embed_input()` từ
trước đã ghép `section` vào trước chunk khi embed. Đo trên 482 đoạn context vừa sinh:

- **22%** từ trong đoạn context đã có sẵn ở tên mục (trung vị);
- **84/482** đoạn trùng 60 ký tự đầu với một đoạn khác;
- rất nhiều đoạn chỉ chép lại tên mục: *"Đoạn này thuộc chủ đề Hỗ trợ người lái nâng cao
  / Kiểm soát hành trình, trả lời được câu…"*

Nên nó thêm ~7,4% chữ mà phần lớn là **lặp lại thứ đã có trong vector** — pha loãng phần
nội dung phân biệt được, đúng chiều làm điểm tụt.

Lỗi nằm ở prompt của tôi: tôi **đưa tên mục vào rồi hỏi "đoạn này thuộc chủ đề gì"**, nên
model chép lại. Kỹ thuật của Anthropic nhắm vào chunk **thiếu** ngữ cảnh định vị; chunk
của ta đã có sẵn header.

Hướng còn lại nếu muốn thử tiếp: hỏi *"đoạn này khác gì các đoạn khác **trong cùng mục**"*
thay vì hỏi chủ đề. Đó là thông tin mà tên mục không mang. Chưa đo.

## Vòng hai: thử thêm hai kiểu enrichment — cả hai đều thua

| cấu hình | @1 | @3 | @5 | @8 | trượt |
|---|---|---|---|---|---|
| dense (đang chạy) | 55% | 76% | 83% | 86% | 6 |
| BM25 một mình | 50% | 76% | 81% | 88% | 5 |
| **hybrid — rẻ, không LLM** | **64%** | 79% | **88%** | 90% | 4 |
| hybrid + ctx (tên mục) | 57% | 81% | 86% | 90% | 4 |
| hybrid + khac (phân biệt trong mục) | 55% | 81% | 86% | 88% | 5 |
| hybrid + hyqa (câu hỏi giả định) | 55% | 79% | 86% | 90% | 4 |

Ba kiểu enrichment, ba lần thua hybrid trần ở `@1`. HyQA — thứ tôi kỳ vọng nhất vì nó
nhắm đúng khoảng cách *câu hỏi ↔ văn xuôi* — còn tệ nhất khi dùng một mình (`@1 = 45%`).

### Hai giả thuyết của tôi, cả hai đều bị đo bác

**"Tràn cửa sổ 512 token."** Sai: số cửa sổ chỉ tăng 536 → 560 (+24), và 10% chunk vốn
đã phải chia nhiều cửa sổ từ trước.

**"Ghép chữ dạng câu hỏi làm mọi chunk trông giống câu hỏi nên mất khả năng phân biệt."**
Cũng sai: khoảng cách điểm giữa hạng 1 và hạng 2 gần như không đổi (0,00375 → 0,00383).

### Điều thật sự học được

Nhìn chính con số vừa đo: **khoảng cách hạng-1 với hạng-2 có trung vị 0,0038**, trong khi
điểm tuyệt đối ~0,875. Toàn bộ bảng xếp hạng nằm trong một dải mỏng ở chữ số thập phân
thứ ba.

Điều đó giải thích mọi thứ đã thấy: chunk chứa bảng áp suất thua **0,0001**; ba kiểu
enrichment gây dao động ±5–9 điểm mà không theo hướng nào; và vì sao hybrid ăn — BM25
đem lại một **tín hiệu độc lập**, phá được thế hoà mà dense không tự phân xử nổi.

**Kết luận cho hướng đi:** thêm chữ vào cùng một không gian embedding không sửa được
chuyện đó. Hai đòn bẩy còn lại là (a) tín hiệu độc lập — hybrid, đã đo, ăn; và (b) một
embedding model có phân bố điểm tách bạch hơn — slide tr.14 gợi `bge-m3` hoặc
`multilingual-e5-**large**`, ta đang dùng bản **small**. Chưa đo.

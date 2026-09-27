# ADR-009: Tầng sửa lỗi ASR sau STT (rule-based edit-distance correction)

- Status: Accepted — follow-up to ADR-008
- Date: 2026-08-08
- Decision owner: WS1 Voice & Edge (tiếp nối chuỗi ADR-007 → ADR-008 STT)

> **Superseded by [ADR-018](ADR-018-remove-voice-correction-layer.md) (2026-08-13):** the correction layer this document describes has been removed from production. Kept as historical record of the PhoWhisper-era decision.

## Context

ADR-008 đo thật AC2 (WER loopback synthetic, budget <20%) cho engine STT hiện
tại (faster-whisper/CTranslate2, `vinai/PhoWhisper-base`) và ghi nhận **FAIL —
30.24%** trên `tests/fixtures/voice/synthetic_commands/`. Đây là cải thiện lớn
so với whisper.cpp/GGML trước đó (88.45%) nhưng vẫn cao hơn budget 20% khoảng
1.5 lần. ADR-008's "Revisit when" để ngỏ câu hỏi làm sao thu hẹp tiếp khoảng
cách này mà không cần đổi engine STT lần nữa hay chờ hardware/corpus mới.

Trong lúc brainstorm hướng giải quyết, người dùng có trích dẫn một bài báo
liên quan: Nguyễn & Cao (2020), "A Novel Method for Recognizing Vietnamese
Voice Commands on Smartphones with Support Vector Machine and Convolutional
Neural Networks" (Wireless Communications and Mobile Computing, DOI
10.1155/2020/2312908). Bài báo này **đã được xác nhận tồn tại thật qua web
search** (đúng tên, đúng DOI, đúng tạp chí) và có hướng tiếp cận chung là hậu
xử lý/sửa lỗi output ASR cho lệnh thoại tiếng Việt bằng một tầng thống kê/học
máy (SVM/CNN) phía sau bộ nhận dạng chính. **Lưu ý quan trọng**: các con số cụ
thể mà bài báo tự báo cáo (WER giảm từ 35.06% xuống 7.08%/5.15%) **chưa được
xác minh độc lập** từ bảng kết quả gốc của bài báo — chỉ có sự tồn tại và
hướng tiếp cận chung của bài báo được xác nhận, không phải các con số kết
quả. Vì vậy các số đó không được dùng làm căn cứ kỳ vọng cho quyết định này;
quyết định này chỉ dựa trên số đo thật tự đo được trên repo này (xem "Real
benchmark section" bên dưới).

**Nguy cơ overfitting đã nhận diện và tránh**: nếu từ vựng dùng để sửa lỗi
được rút ra từ chính bộ fixture `tests/fixtures/voice/synthetic_commands/`
dùng để đo WER, thì kết quả đo được sẽ là "học thuộc bộ test" chứ không phải
cải thiện tổng quát thật. Để tránh việc này, `COMMAND_VOCABULARY` (Task 1,
commit `e502c33`) được rút trích thủ công, word-for-word, từ hai nguồn hoàn
toàn độc lập với bộ fixture WER:

- `docs/agent_spec.md:117-123` — schema tool điều khiển (domain hvac, seat,
  window, door, media, navigation).
- `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md:68-82` — 10 câu lệnh CTRL
  ví dụ (CTRL-001..010) + 5 câu NLU ví dụ (NLU-001..005) bằng tiếng Việt.

Không có từ đồng nghĩa tự bịa ra — chỉ những từ xuất hiện nguyên văn trong hai
nguồn trên. Nhờ vậy, phép đo WER trước/sau ở Task 2 (commit `c3757bb`) trên bộ
fixture synthetic vẫn là một **held-out evaluation thật** — bộ fixture đó
chưa từng được dùng để xây dựng từ vựng sửa lỗi.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Giữ nguyên, không thêm tầng sửa lỗi nào | Không thêm code/rủi ro | AC2 vẫn FAIL 30.24%, không có hướng thu hẹp khoảng cách nào khác ngoài chờ engine STT mới hoặc corpus thật |
| SVM/CNN classifier theo đúng phương pháp bài báo Nguyễn & Cao (2020) | Nếu đúng như bài báo báo cáo, có thể giảm WER rất mạnh | Cần dữ liệu huấn luyện cặp (ASR-sai, đúng) thật — hiện chỉ có 15 câu lệnh mẫu biết trước trong SPIKE-001 (không phải cặp lỗi/đúng thật, không đủ để train một classifier có ý nghĩa thống kê); rủi ro overfit rất cao trên tập dữ liệu nhỏ như vậy; các con số bài báo tự báo cáo chưa được xác minh độc lập nên không dùng làm kỳ vọng |
| **Rule-based edit-distance correction, vocabulary từ `agent_spec.md` + `SPIKE-001`, `max_edit_distance=1`, single-unique-nearest-match-only** (đã chọn) | Không cần dữ liệu huấn luyện; đơn giản, dễ kiểm chứng, dễ audit từng quyết định sửa; vocabulary có nguồn gốc rõ ràng, truy vết được tới tài liệu spec, độc lập với bộ test WER (tránh overfitting) | Chỉ sửa được lỗi đơn-từ khoảng cách 1 ký tự; không sửa được lỗi cấu trúc câu/nhiều từ liền nhau sai; vocabulary 47 từ rất nhỏ, chỉ phủ đúng các câu ví dụ trong SPIKE-001, chưa phải vocabulary lệnh thật đầy đủ |

## Decision

Thêm một tầng sửa lỗi hậu-STT dạng **rule-based edit-distance correction**:
`src/services/voice_correction.py`'s `correct_transcript(text, vocabulary=
COMMAND_VOCABULARY, max_edit_distance=1) -> str` (Task 1, commit `e502c33`).

- `COMMAND_VOCABULARY` (47 từ) được rút trích thủ công, word-for-word, từ
  `docs/agent_spec.md:117-123` (tool schema) và
  `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md:68-82` (10 câu CTRL + 5
  câu NLU ví dụ) — không có từ đồng nghĩa tự bịa ra.
- Chính sách sửa: **single-nearest-unique-match-only** — với mỗi từ không có
  sẵn trong vocabulary (và không phải token số), tìm các từ trong vocabulary
  có khoảng cách edit-distance ≤ `max_edit_distance` (mặc định 1); nếu có
  đúng một từ gần nhất duy nhất, thay thế; nếu có nhiều từ đồng hạng (ambiguous)
  hoặc không có từ nào đủ gần, giữ nguyên từ gốc (không đoán mò).
- Không bao giờ sửa một từ đã có sẵn trong vocabulary, và không bao giờ sửa
  token số (`isdigit()`).
- **Không phải** một classifier SVM/CNN như bài báo gốc — thiếu dữ liệu huấn
  luyện thật (chỉ có 15 câu lệnh mẫu biết trước, không phải cặp
  lỗi-ASR/đúng-text thật, không đủ để train một mô hình thống kê có ý nghĩa).

## Rationale

- Giữ nguyên nguyên tắc "no unmeasured claims" của dự án: quyết định này được
  xác nhận bằng benchmark WER thật đo trên bộ fixture held-out (Task 2, commit
  `c3757bb`), không dựa trên kỳ vọng suy ra từ số liệu bài báo chưa xác minh.
- **Sửa lại một khẳng định sai từ review đầu** (final whole-branch review,
  xem final-fix-report tương ứng): bất biến thật của `correct_transcript()`
  chỉ là "không bao giờ sửa một từ đã có sẵn trong `vocabulary`, trong
  `PROTECTED_NUMERAL_WORDS`, hoặc là token số" — **không phải** "không bao giờ
  làm hỏng một từ đã đúng". Đúng/sai của một từ được xác định so với transcript
  tham chiếu, không phải so với việc từ đó có nằm trong vocabulary hay không —
  một từ có thể được nhận dạng ĐÚNG nhưng vẫn nằm ngoài vocabulary (ví dụ số
  đếm tiếng Việt viết dạng chữ như "hai", "bốn" — Whisper luôn xuất ra số dạng
  chữ, không phải "24") và bị "sửa" thành sai. Vì vậy `corrected_wer <=
  raw_wer` **không phải một đảm bảo cấu trúc (by construction)** — đó là một
  tính chất đo được thực nghiệm cho một tổ hợp vocabulary/fixture cụ thể, có
  thể đúng cho fixture này nhưng không tổng quát cho mọi input. Lỗ hổng cụ thể
  này (số đếm tiếng Việt dạng chữ bị sửa sai) đã được phát hiện và vá bằng
  `PROTECTED_NUMERAL_WORDS` trong cùng đợt sửa này.
- Cách tiếp cận rule-based, không cần huấn luyện, phù hợp với lượng dữ liệu
  hiện có (15 câu mẫu, không phải corpus lỗi ASR thật) — một classifier
  SVM/CNN trên lượng dữ liệu này gần như chắc chắn overfit và không đo được
  gì có ý nghĩa.
- Tách vocabulary khỏi bộ fixture WER là điều kiện bắt buộc để phép đo
  before/after còn có ý nghĩa là "cải thiện thật", không phải "học thuộc tập
  test".

## Real benchmark section

Đo thật trên `tests/fixtures/voice/synthetic_commands/` (cùng bộ fixture,
cùng STT engine faster-whisper/PhoWhisper-base như ADR-008), qua test tích
hợp held-out ở Task 2 (commit `c3757bb`,
`tests/test_services/test_voice_integration.py`):

- **Raw WER (không sửa, output thẳng từ `transcribe()`): 30.24%** — giống hệt
  con số AC2 đo được trong ADR-008 (cùng fixture, cùng engine, không đổi).
- **Corrected WER (sau khi qua `correct_transcript()`): 20.71%** — số đo lại
  sau final whole-branch review, sau khi vá lỗi số đếm tiếng Việt dạng chữ bị
  sửa sai (`PROTECTED_NUMERAL_WORDS`, xem mục Rationale/Consequences ở trên).
  Con số cũ 28.93% đo trước khi vá lỗi này **đã sai** (bản thân
  `correct_transcript()` khi đó đang làm hỏng các từ số đếm đã nhận dạng
  đúng như "hai", "bốn" trong câu fixture "hai mươi bốn độ") — 20.71% là con
  số đúng, đo lại thật bằng
  `python -m pytest tests/test_services/test_voice_integration.py::test_correction_layer_never_increases_synthetic_loopback_wer -v -m integration -s`.
- **Cải thiện: ~9.5 điểm phần trăm** (30.24% → 20.71%) — cải thiện thật, lớn
  hơn nhiều so với số đo trước khi vá lỗi (phần lớn cải thiện này chính là hệ
  quả của việc không còn tự làm hỏng các từ số đếm nữa, chứ không phải do
  vocabulary sửa lỗi mạnh hơn).
- **Kết luận trung thực: KHÔNG đạt budget AC2 <20%** đề ra trong ADR-008.
  20.71% vẫn cao hơn budget 20%, dù chỉ còn cách rất gần (khoảng 1.04 lần) —
  đã thu hẹp đáng kể so với cả raw WER (30.24%) lẫn số corrected WER cũ có
  lỗi (28.93%), nhưng vẫn không đạt. Không nên trình bày đây là đã đạt
  budget — đây vẫn là một bước thu hẹp khoảng cách, chỉ là đáng kể hơn ước
  tính trước, không phải giải pháp đầy đủ.

## Consequences

- `correct_transcript()` hiện là một **pure function độc lập**
  (`src/services/voice_correction.py`), **chưa được nối dây** vào
  `transcribe()` trong `src/services/voice.py` hay bất kỳ HTTP endpoint nào
  (`POST /api/v1/turns/voice` theo ADR-007 vẫn chưa nối dây). Việc nối dây là
  một quyết định riêng trong tương lai, nên thực hiện sau khi có NLU/intent
  router thật (ADR-006) — router đó cần dùng một vocabulary đã được kiểm
  chứng và mở rộng đầy đủ hơn, không phải vocabulary tối thiểu 47 từ hiện tại.
- `COMMAND_VOCABULARY`'s 47 từ **chỉ phủ đúng các câu ví dụ literal trong
  SPIKE-001** (10 CTRL + 5 NLU) cộng domain trong `agent_spec.md`'s tool
  schema. Đây không phải một vocabulary lệnh thoại đầy đủ cho production —
  một triển khai thật cần một vocabulary được bảo trì đúng cách, lý tưởng là
  sinh ra từ chính schema tool/slot của NLU router thật một khi router đó tồn
  tại, thay vì chép tay từ một tài liệu spike.
- AC2 (WER <20%) của ADR-008 **vẫn chưa đạt** sau tầng sửa lỗi này (20.71% >
  20%, đo lại sau khi vá lỗi `PROTECTED_NUMERAL_WORDS`). Tầng sửa lỗi
  rule-based hiện tại không đủ để tự nó giải quyết AC2 —
  cần thêm biện pháp khác (engine STT tốt hơn, vocabulary lớn hơn có kiểm
  chứng, hoặc corpus thật) mới có khả năng đạt budget.
- Không thêm dependency mới — `correct_transcript()` chỉ dùng
  `_edit_distance()` đã có sẵn trong `src/services/voice.py`.
- **Tầng sửa lỗi CÓ THỂ làm hỏng một từ đã được nhận dạng đúng nếu từ đó nằm
  ngoài vocabulary** — đây không phải giả thuyết lý thuyết, đã đo được thật:
  số đếm tiếng Việt viết dạng chữ ("hai", "ba", "bốn", ...) không nằm trong
  `COMMAND_VOCABULARY` (47 từ chỉ phủ đúng SPIKE-001/agent_spec.md), nên
  trước khi vá, câu đã nhận dạng đúng hoàn toàn "Đặt điều hòa hai mươi bốn
  độ" bị `correct_transcript()` biến thành "Đặt điều hòa hơi mươi bên độ"
  (cả "hai" lẫn "bốn" đều bị sửa sai dù đã đúng). Đã vá bằng
  `PROTECTED_NUMERAL_WORDS` (frozenset các từ số đếm tiếng Việt) trong
  `src/services/voice_correction.py`, cùng với test hồi quy
  `test_correction_layer_leaves_perfect_reference_text_unchanged` trong
  `tests/test_services/test_voice_integration.py`. **Bất kỳ ai mở rộng
  vocabulary hoặc nối dây tầng này vào pipeline thật đều phải tiếp tục mở
  rộng tập từ được bảo vệ (protected-word set) cho MỌI nhóm từ hợp lệ mà
  không thể liệt kê hết trong một vocabulary tĩnh và biến đổi tùy theo từng
  câu nói** (số đếm, danh từ riêng, địa danh, tên người, v.v.) — không chỉ
  đơn thuần thêm nhiều từ hơn vào `COMMAND_VOCABULARY`, vì vocabulary tĩnh sẽ
  không bao giờ phủ hết được các nhóm từ biến đổi tự do này.

## Revisit when

- NLU router (ADR-006) được triển khai và tự định nghĩa vocabulary lệnh
  canonical của riêng nó — khi đó nên thay `COMMAND_VOCABULARY` bằng
  vocabulary sinh ra từ schema tool/slot thật của router, và cân nhắc nối dây
  `correct_transcript()` vào pipeline thật.
- Có đủ cặp dữ liệu thật (ASR-sai, đúng-text) — không chỉ 15 câu mẫu biết
  trước — để cân nhắc nghiêm túc các tầng SVM/CNN theo đúng phương pháp bài
  báo gốc (Nguyễn & Cao, 2020), và khi đó nên xác minh độc lập các con số bài
  báo tự báo cáo trước khi dùng làm kỳ vọng.
- Có corpus WER giọng người thật (không phải fixture synthetic) để xác thực
  tầng sửa lỗi này vượt ra ngoài phạm vi fixture tổng hợp hiện tại — xem
  ADR-008's "Revisit when" (mục corpus giọng người Việt thật,
  `eval/datasets/poc/v1/...` hiện trống).

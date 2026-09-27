# Thiết kế: Tầng sửa lỗi ASR sau STT (voice correction layer)

> **Superseded by [ADR-018](../../adr/ADR-018-remove-voice-correction-layer.md) (2026-08-13):** the correction layer this document describes has been removed from production. Kept as historical record of the PhoWhisper-era decision.

> Ngày: 2026-08-08. Trạng thái: Đã duyệt (brainstorming), chờ viết implementation plan.
> Nguồn gốc: tiếp nối `feature/faster-whisper-stt` (PR #19, đã merge `develop`) — AC2 (WER) đo thật 30.24%, chưa đạt budget 20%. Người dùng đề xuất tham khảo bài báo Nguyen & Cao (2020), "A Novel Method for Recognizing Vietnamese Voice Commands on Smartphones with Support Vector Machine and Convolutional Neural Networks" (*Wireless Communications and Mobile Computing*, DOI 10.1155/2020/2312908 — đã xác nhận có thật qua web search; các con số WER 35.06%→7.08%/5.15% do người dùng trích dẫn, chưa tự kiểm chứng độc lập từ bảng kết quả gốc).

## Bối cảnh & quyết định phương pháp luận

Ý tưởng gốc từ bài báo: xây tầng sửa lỗi (rule-based dictionary hoặc SVM/CNN) phía sau ASR, ánh xạ lỗi nhận dạng phổ biến về từ đúng.

**Rủi ro overfitting đã phát hiện khi brainstorm**: VIVI hiện chỉ có 5 câu fixture tổng hợp (`tests/fixtures/voice/synthetic_commands/`), đã dùng để đo WER 30.24% (AC2, faster-whisper). Nếu xây dictionary trực tiếp từ đúng 5 lỗi quan sát được trên 5 câu đó rồi đo lại WER trên cùng 5 câu — đó là học thuộc đáp án, không phải bằng chứng cải thiện thật.

**Giải pháp (đã duyệt)**: không dùng 5 câu fixture làm nguồn quy tắc. Thay vào đó, xây từ vựng lệnh hợp lệ từ 2 nguồn **độc lập với fixture WER**, đã có sẵn trong repo (không phải suy đoán):

1. Schema 6 tool điều khiển trong `docs/agent_spec.md:117-123`: `set_hvac_power`, `set_hvac_temperature` (kế thừa từ `docs/data_model.md:136`), `set_seat_heating`, `set_window_position`, `set_door_state`, `set_seat_position` — cộng thêm `media_control`, `set_navigation` xuất hiện trong ví dụ `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md`.
2. 10 câu CTRL + 5 câu NLU trong `docs/tasks/SPIKE-001-offline-ai-vertical-slice.md:68-82` (vd. "Bật điều hòa"→`set_hvac_power(true)`, "Đóng cửa sổ bên lái"→`set_window_position(front_left,0)`) — đây là tài liệu đặc tả sản phẩm viết độc lập với việc đo WER sau này, nên dùng làm nguồn từ vựng không vi phạm nguyên tắc tách train/test.

Việc đo WER trước/sau trên 5 câu fixture hiện có do đó trở thành **held-out test thật** (từ vựng không lấy từ đó).

**Quyết định phạm vi thuật toán (đã duyệt)**: chỉ làm **rule-based/edit-distance** (giai đoạn 1 theo đề xuất gốc), KHÔNG làm SVM/CNN trong task này — vì dữ liệu hiện có (15 câu CTRL+NLU, không phải cặp lỗi-đúng thật) quá ít để huấn luyện classifier có ý nghĩa thống kê, đúng tinh thần YAGNI.

## Kiến trúc

Module mới `src/services/voice_correction.py`, **tách biệt hoàn toàn** khỏi `src/services/voice.py` (đã merge qua PR #19) — không sửa lại code STT/TTS đã ship, giảm rủi ro:

```python
COMMAND_VOCABULARY: frozenset[str] = frozenset({...})  # trích từ agent_spec.md + SPIKE-001

def correct_transcript(text: str, vocabulary: frozenset[str] = COMMAND_VOCABULARY, max_edit_distance: int = 1) -> str:
    ...
```

- `COMMAND_VOCABULARY`: hardcode tĩnh (không parse markdown lúc runtime — YAGNI, tránh phụ thuộc fragile vào format doc), liệt kê từ/cụm từ tiếng Việt hợp lệ trích thủ công từ 2 nguồn ở trên khi viết plan.
- `correct_transcript()`: tokenize theo khoảng trắng; với mỗi từ không có trong `vocabulary`, tìm từ trong `vocabulary` có `_edit_distance` (hàm char-level đã có sẵn, tái dùng từ `src.services.voice`) nhỏ nhất; chỉ thay nếu khoảng cách nhỏ nhất `<= max_edit_distance` **và** duy nhất (không có từ thứ 2 cùng khoảng cách đó) — tránh đoán sai khi mơ hồ.

## Data flow

`transcribe()` trong `voice.py` **giữ nguyên, không đổi** — vẫn trả `Transcript` thô từ STT. `correct_transcript()` là hàm thuần, độc lập, bên gọi (NLU router tương lai theo ADR-006, hoặc test) tự quyết định áp dụng. Không đổi API public đã merge.

## Error handling

- Text rỗng/toàn khoảng trắng → trả nguyên văn (không raise).
- Thuật toán phải idempotent: `correct_transcript(correct_transcript(x)) == correct_transcript(x)`.
- Từ đã đúng **theo nghĩa "có trong vocabulary/protected set"** (vocabulary,
  `PROTECTED_NUMERAL_WORDS`, hoặc token số) → không đổi, kể cả khi trùng độ
  dài với từ khác trong vocabulary. **Lưu ý (bổ sung sau final review,
  2026-08-08)**: đây KHÔNG đồng nghĩa với "mọi từ đã được nhận dạng đúng thì
  không đổi" — một từ có thể đúng so với transcript tham chiếu nhưng vẫn nằm
  ngoài vocabulary/protected set (vd. số đếm tiếng Việt viết dạng chữ trước
  khi `PROTECTED_NUMERAL_WORDS` được thêm vào) và bị sửa sai. Xem ADR-009 mục
  Rationale/Consequences.

## Testing

- Unit test thuật toán: case tự viết minh họa cơ chế (không nhằm chứng minh độ chính xác thống kê) — test khớp đúng 1 ứng viên, test mơ hồ (2 ứng viên cùng khoảng cách → không sửa), test từ đã đúng → giữ nguyên, test text rỗng, test idempotent.
- Đánh giá thật: đo WER trên 5 câu fixture (`tests/fixtures/voice/synthetic_commands/`) **trước và sau** khi áp `correct_transcript()` lên output ASR — ghi số liệu thật vào ADR mới, không giả định cải thiện trước khi đo.

## Ngoài phạm vi (out of scope)

- SVM/CNN classifier (giai đoạn 2-3 theo đề xuất gốc) — chưa đủ dữ liệu, để sau nếu rule-based không đủ.
- Tích hợp `correct_transcript()` vào pipeline `transcribe()`/NLU router thật — NLU router theo ADR-006 chưa implement trong `src/`, việc nối dây là task riêng sau khi router tồn tại.
- Mở rộng từ vựng ngoài 2 nguồn đã liệt kê (vd. thêm từ đồng nghĩa tự đoán) — chỉ dùng đúng những gì đã có trong `agent_spec.md`/`SPIKE-001`, tránh tự bịa từ vựng không có căn cứ.
- Corpus giọng người thật — vẫn ngoài phạm vi, kế thừa ADR-007/ADR-008.

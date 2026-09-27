# ADR-012: Nối `correct_transcript()` vào `transcribe()`, nới budget AC2 lên 22%

- Status: Accepted — follow-up to ADR-008, ADR-009
- Date: 2026-08-09
- Decision owner: WS1 Voice & Edge

> **Superseded by [ADR-018](ADR-018-remove-voice-correction-layer.md) (2026-08-13):** the correction layer this document describes has been removed from production. Kept as historical record of the PhoWhisper-era decision.

## Context

ADR-009 thêm tầng sửa lỗi hậu-STT (`correct_transcript()`,
`src/services/voice_correction.py`) nhưng ghi rõ trong "Consequences": tầng
này **chưa được nối dây** vào `transcribe()` — cố tình để lại quyết định nối
dây cho sau khi có NLU router thật (ADR-006).

Trong lúc review code trên `develop` sau khi merge nhánh
`feature/voice-command-correction`, phát hiện 3 vấn đề:

1. **Bug**: `PROTECTED_NUMERAL_WORDS` (ADR-009's cơ chế bảo vệ số đếm tiếng
   Việt) thiếu từ `"mốt"` — dạng đọc số 1 trong các số ghép 21/31/.../91
   ("hai mươi **mốt** độ" = 21 độ). Vì `"mốt"` cách `"một"` (từ trong
   `COMMAND_VOCABULARY`) đúng 1 ký tự, `correct_transcript()` tự sửa nhầm
   `"mốt"` thành `"một"` — đúng loại lỗi mà `PROTECTED_NUMERAL_WORDS` được
   tạo ra để chặn, chỉ là sót một từ.
2. **Bug**: khi sửa một từ viết hoa (ví dụ đầu câu), `correct_transcript()`
   trả về dạng chữ thường của từ vocabulary, làm mất hoa/thường gốc (ví dụ
   `"Bất điều hòa"` → `"bật điều hòa"`, mất hoa chữ đầu câu).
3. **Gap đã biết** (không phải bug — đúng như ADR-009 ghi nhận):
   `correct_transcript()` chưa được gọi ở đâu trong `transcribe()` hay bất kỳ
   pipeline thật nào, nên toàn bộ lợi ích đo được ở ADR-009 (30.24% → 20.71%
   WER) chưa có tác dụng thật với người dùng.

Người quyết định (chủ repo) yêu cầu sửa cả 3, bao gồm nối dây ngay bây giờ
(không đợi ADR-006's NLU router như ADR-009 dự kiến), và chấp nhận nới budget
AC2 lên mức đo được thật thay vì giữ nguyên 20% với test đỏ.

## Decision

1. Vá `PROTECTED_NUMERAL_WORDS` — thêm `"mốt"` (commit theo TDD, test
   `test_correct_transcript_protects_mot_numeral_suffix_word`).
2. Vá casing — `correct_transcript()` giờ khớp casing của từ gốc khi sửa
   (`_match_casing()`, viết hoa chữ đầu nếu từ gốc viết hoa chữ đầu, viết
   hoa toàn bộ nếu từ gốc viết hoa toàn bộ), test
   `test_correct_transcript_preserves_original_casing_when_correcting`.
3. Nối `correct_transcript()` vào `transcribe()` trong
   `src/services/voice.py`: `transcribe()` giờ trả về text đã qua sửa lỗi.
   Thêm `transcribe_raw()` — giữ nguyên hành vi cũ (không sửa lỗi) — để nơi
   nào cần đo tác động của tầng sửa lỗi (test WER before/after) vẫn đo được
   đúng baseline, thay vì so sánh corrected với chính nó.
   - Import `correct_transcript` trong `transcribe()` là **lazy import**
     (trong thân hàm, không phải top-level): `voice_correction.py` import
     `_edit_distance` từ `voice.py` ở top-level, nên import ngược lại ở
     top-level của `voice.py` sẽ tạo circular import.
4. Nới budget AC2 (`test_synthetic_loopback_word_error_rate_is_under_budget`)
   từ 20% (ADR-008) lên **22%** — xem "Real benchmark section" để biết vì sao
   là 22% chứ không phải một số tùy ý khác.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Giữ nguyên budget 20%, chấp nhận test đỏ | Không phải "nới bụng để qua bài kiểm tra" | Test đỏ vĩnh viễn trên `develop` cho tới khi có cải thiện ASR gốc (chưa có kế hoạch/deadline); che khuất các regression thật khác trong CI vì test AC2 đã "luôn đỏ, khỏi nhìn" |
| Nới budget lên một số tròn tùy ý (ví dụ 25%, 30%) | Nhiều headroom hơn, ít khả năng đỏ lại | Không có căn cứ đo được — vi phạm nguyên tắc "no unmeasured claims" của dự án đã áp dụng xuyên suốt ADR-008/009 |
| **Nới budget lên 22% = số đo thật (20.71%) + headroom nhỏ** (đã chọn) | Có căn cứ đo được thật, không phải số chọn tùy ý; vẫn đủ chặt để bắt regression thật (ví dụ nếu tầng sửa lỗi bị xoá nhầm, WER sẽ nhảy lại về ~30%, vẫn fail) | Biên độ hẹp (0.29 điểm phần trăm) — dễ đỏ lại nếu môi trường đo có nhiễu nhỏ; cần theo dõi thêm |

## Rationale

- Giữ nguyên tắc "no unmeasured claims": budget mới (22%) bám sát số đo thật
  (20.71%), không phải kỳ vọng suy ra trước.
- Nối dây ngay thay vì đợi ADR-006 (như ADR-009 dự kiến) vì lợi ích đo được
  là thật và không phụ thuộc vào việc có NLU router hay không — router có
  thể thay `COMMAND_VOCABULARY` bằng vocabulary tốt hơn sau, nhưng không có
  lý do kỹ thuật nào để chặn việc nối dây phiên bản vocabulary hiện tại
  trước đó.
- Tách `transcribe_raw()` ra khỏi `transcribe()` để giữ được khả năng đo
  before/after — nếu không tách, test đo tác động của tầng sửa lỗi sẽ tự so
  sánh corrected với corrected (raw_rates và corrected_rates bằng nhau), mất
  hoàn toàn giá trị của phép đo held-out mà ADR-009 đã dày công thiết lập.

## Real benchmark section

Đo lại trên cùng fixture/engine như ADR-008/009
(`tests/fixtures/voice/synthetic_commands/`), sau khi vá cả 2 bug (mốt +
casing) và nối dây:

```
$ python -m pytest tests/test_services/test_voice_integration.py -v -s
test_transcribe_warm_latency_is_under_budget PASSED
test_synthetic_loopback_word_error_rate_is_under_budget PASSED
test_correction_layer_leaves_perfect_reference_text_unchanged PASSED
test_correction_layer_never_increases_synthetic_loopback_wer
raw WER = 30.24%, corrected WER = 20.71%
PASSED
```

- **Raw WER (qua `transcribe_raw()`, không sửa lỗi): 30.24%** — không đổi so
  với ADR-008/009 (cùng fixture, cùng engine).
- **Corrected WER (qua `transcribe()`, đã nối tầng sửa lỗi): 20.71%** —
  giống hệt số đo trong ADR-009 (vá `PROTECTED_NUMERAL_WORDS` không đổi con
  số này, vì fixture hiện có không chứa từ `"mốt"`; vá casing cũng không đổi
  con số WER vì `word_error_rate()` đã casefold trước khi so sánh — 2 bug
  vừa vá không được chính bộ fixture WER này phát hiện, chỉ được phát hiện
  qua đọc code + test trực tiếp trên input tổng hợp).
- **Kết luận trung thực: 20.71% < 22% (budget mới) → PASS**, nhưng **vẫn
  không đạt 20% (budget gốc ADR-008)**. Đây là nới budget để khớp thực tế đo
  được, không phải một cải thiện kỹ thuật mới đưa WER xuống dưới 20%.

## Consequences

- `transcribe()` giờ trả về text đã qua `correct_transcript()` — mọi caller
  hiện tại/tương lai của `transcribe()` (kể cả `POST /api/v1/turns/voice`
  theo ADR-007, hiện vẫn chưa nối dây) sẽ nhận text đã sửa mà không cần tự
  gọi `correct_transcript()` riêng.
- `transcribe_raw()` là API mới, public, dùng cho đo lường/debug — không nên
  dùng trong pipeline sản phẩm thật (sẽ mất lợi ích của tầng sửa lỗi).
- Budget AC2 trong `test_synthetic_loopback_word_error_rate_is_under_budget`
  đổi từ 20% (ADR-008) → 22% (ADR-012). Đây là ADR ghi nhận thay đổi budget
  này; không sửa ngược lại ADR-008 (giữ nguyên làm sử liệu lịch sử).
- `COMMAND_VOCABULARY` vẫn chỉ có 47 từ (không đổi trong ADR này) — mọi giới
  hạn ADR-009 đã ghi nhận (chỉ sửa lỗi đơn-từ khoảng cách 1 ký tự, chỉ phủ
  đúng câu ví dụ SPIKE-001) vẫn còn nguyên.
- Biên độ giữa số đo thật (20.71%) và budget mới (22%) khá hẹp (0.29 điểm) —
  nếu môi trường đo (máy khác, phiên bản model khác) cho kết quả nhích lên,
  test có thể đỏ lại. Đây là đánh đổi có chủ đích của quyết định "nới theo số
  đo thật" thay vì "nới rộng rãi cho chắc".

## Revisit when

- Có NLU router thật (ADR-006) — vocabulary nên chuyển sang sinh từ schema
  tool/slot thật thay vì 47 từ chép tay từ SPIKE-001 (theo đúng dự kiến ban
  đầu của ADR-009).
- Budget 22% bị fail lại trên môi trường đo khác (phần cứng target thật,
  model version khác) — cần đo lại và quyết định lại budget dựa trên số đo
  mới, không tự động nới thêm.
- Có corpus giọng người Việt thật — để biết tầng sửa lỗi hiện tại (chỉ xử lý
  lỗi đơn-từ khoảng cách 1 ký tự trong vocabulary 47 từ) có đủ tổng quát hay
  không ngoài phạm vi fixture synthetic hiện tại.

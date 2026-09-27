# Dataset agent v3 — intent + tool exactness

- **76 case** text, không có audio. Sprint này không làm voice. (Dòng này từng ghi
  "60 case" và đã sai từ đợt bổ sung 08/08 — xem hai mục *Bổ sung* ở cuối file;
  con số đúng luôn là số dòng của `cases.jsonl`.)
- 30 case đầu port từ `eval/datasets/poc/v2/cases.jsonl` (branch
  `feature/hybrid-architecture-resident-pipeline`, commit `c76c7ee`), **có sửa**:
  args viết lại sang tên canonical trong `docs/agent_spec.md` (`seat` dùng
  `front_left`/`front_right` thay cho `driver`/`passenger`; `media_control` dùng
  `volume` thay cho `value`; `set_navigation` thêm `operation`), và mọi case
  được gắn thêm nhãn `intent`.
- `S2-GUARD-UNSAFE-001` ("Mở cửa xe") đổi nhãn từ `denied` sang `clarify`:
  `set_door_state` nay nằm trong registry, nên thiếu vị trí cửa là thiếu slot,
  không phải actuator không hỗ trợ.
- 30 case còn lại viết mới, phủ `set_seat_position`, `set_door_state`,
  `navigation cancel`, KI-001, số viết chữ, tiền tố lịch sự, và case negative.
- Không sửa `eval/datasets/poc/v2`. v3 là revision độc lập.

## Con số này đo cái gì, và không đo cái gì

30 case mới được viết bởi cùng người viết router, **biết trước** luật của router.
Nên `intent_accuracy` ở đây là **độ phủ hồi quy**, không phải khả năng tổng quát
hóa trên câu nói tự do chưa từng thấy. Nó chứng minh router không vỡ khi sửa
code; nó **không** chứng minh router hiểu được người dùng thật.

Muốn có số tổng quát hóa thì cần câu lệnh thu từ người ngoài nhóm, chưa nhìn
thấy code. Việc đó chưa làm.

Dataset cũng chỉ có văn bản: không đi qua ASR, nên không phản ánh lỗi nhận dạng
giọng nói. Số WER và ảnh hưởng của nó lên intent nằm ở phần voice, đầu việc khác.

Chạy: `.\.venv\Scripts\python.exe -m src.agents.eval`
Kết quả ghi vào `eval/results/agent-intent/<UTC-run-id>/` và **bất biến**.

## Đổi nhãn 2026-08-08 (ADR-011)

`A3-NC-001` và `A3-NC-002` đổi `intent` từ `none` sang `manual_query`. Đây là hệ
quả trực tiếp của việc đảo mặc định: câu không khớp luật điều khiển nào giờ đi vào
RAG và nhận grounded refusal, thay vì trả `not_control/none`. Nhãn cũ mô tả hành vi
cũ, không phải hành vi đúng.

## Bổ sung 2026-08-08 (review PR #23) — 4 case đọc số

`A3-NUM-005..008`, thêm sau khi review phát hiện hai lỗi đọc số **cùng lớp KI-001**
(thực thi im lặng với giá trị sai):

| Case | Vì sao có |
|---|---|
| `Đặt âm lượng hai bốn` → 24 | trước đây ra `4` rồi **chạy luôn**; `"hai bốn"` là cách nói nhanh của 24, đã xác nhận với người dùng |
| `Chỉnh điều hòa hai sáu độ` → 26 | cùng dạng, domain khác |
| `Đặt âm lượng một trăm hai mươi` → `denied` | trước đây ra `20` rồi **chạy luôn**; vòng quét `mươi` chạy trước vòng `trăm` |
| `Đặt âm lượng một hai ba` → `clarify` | ba từ số liền nhau không có cách đọc hợp lý — hỏi lại, không đoán |

Đây là lần **duy nhất** trong dataset này mà case được thêm sau khi nhìn thấy lỗi.
Hai case đầu phản ánh một quyết định ngôn ngữ do người dùng chốt, không phải do soi
case fail trong `manual/v1`.

## Bổ sung 2026-08-15 — 12 case domain `light` (64 → 76)

`A3-LIGHT-001..012`. Đèn và cốp thành actuator thật từ **ADR-020**, nhưng dataset
không được cập nhật theo: `trunk` có đúng 1 case, `light` **không có case nào**.
Nghĩa là toàn bộ `_match_lights` (`src/agents/router.py`) chưa từng có lớp bảo vệ ở
tầng eval — chỉ unit test giữ. Đây là bổ sung để lấp chỗ đó, không phải phản ứng với
một lỗi nhìn thấy.

Phủ đủ sáu nhánh của matcher, vì mỗi nhánh hỏng theo một kiểu khác nhau:

| Case | Nhánh | Kỳ vọng |
|---|---|---|
| 001–003 | ba chế độ đèn pha theo thuật ngữ sổ tay | `control` + `set_headlight_mode` (`low_beam`/`high_beam`/`auto`) |
| 004–005 | tên gọi dân dã (`đèn pha`, `đèn cốt`) | `control` + `low_beam` |
| 006–007 | đèn nội thất | `control` + `set_interior_light` |
| 008–009 | **câu trống, mơ hồ thật** | `clarify`, không tool |
| 010 | `tắt đèn pha` | `denied` — enum `headlight` cố ý không có `off` (UNECE R48, ADR-020) |
| 011–012 | loại đèn ngoài bề mặt điều khiển | `not_control` / `manual_query` |

Hai điều cần biết trước khi sửa nhóm case này:

- **`intent` của câu mơ hồ là `headlight_mode`, không phải `none`.** Router *biết*
  đây là chuyện đèn, nó chỉ thiếu slot — khác `"mở nó ra"` (`ambiguous`, `intent:
  none`) là câu không biết đang nói về cái gì. Điền `none` theo khuôn của nhóm
  `ambiguous` sẽ làm case đỏ và trông y như router hỏng.
- **Nhóm 011–012 là nhóm đắt nhất.** `_UNSUPPORTED_LIGHTS` tồn tại vì thiếu nó thì
  câu hỏi về đèn hazard bị trả `clarify missing_light_target` — hỏi lại về đèn pha
  khi người ta hỏi chuyện khác — và `question_recall` tụt 0.9833 → 0.9667.

Nhãn được đọc **từ router** rồi kiểm bằng mắt theo ADR-020, chứ không viết tay rồi
sửa cho khớp. Điều đó cũng có nghĩa nhóm này đóng băng *hành vi hôm nay*: nó bắt
được hồi quy, không chứng minh được hành vi đúng. Lập luận vì sao hành vi hôm nay là
đúng nằm ở ADR-020 và ở `tests/test_agents/test_router.py`.

Mẫu số đổi **64 → 76**, nên `intent_accuracy = 1.0000` của run trước và run sau
**không cùng một phép đo** dù hai số bằng nhau. Run trước: `agent-intent/20260815T102359.446473Z`
(n=64). Run sau: `agent-intent/20260815T113657.393667Z` (n=76, `light` 12/12) và
`agent-routing/20260815T113707.799752Z` (`question_recall` giữ 0.9833).

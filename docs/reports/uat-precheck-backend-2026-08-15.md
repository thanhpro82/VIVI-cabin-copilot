# Pre-check backend trước vòng UAT 1 — 2026-08-15

Chạy trước vòng UAT tối nay để biết **những gì backend đã sai từ bây giờ**, thay vì
phát hiện lúc năm người đang ngồi trước màn hình. Kết quả dưới đây là đầu vào cho
`docs/release/mvp-demo-checklist.md`, **không thay thế nó**.

## Đây không phải UAT, và khác biệt nằm ở đâu

| | Pre-check này | UAT thật |
|---|---|---|
| Đầu vào | gọi thẳng `graph.ainvoke()` bằng script | mic thật, người nói thật |
| Giao diện | không có | `/driver` với 3 cờ mock `false` |
| Vận chuyển | `InProcessVehicleGateway` | MQTT + Mosquitto + simulator |
| Tiêu chí đạt | outcome/state/plan của backend | **kết quả người dùng nhìn thấy** |

Nghĩa là mọi dòng "✅" dưới đây chỉ chứng minh **backend quyết định đúng**. Nếu tối
nay màn hình không đổi trong khi ở đây ✅, thì lỗi nằm ở FE — và đó chính là giá trị
của việc chạy trước: nó chia đôi không gian tìm lỗi.

## Chạy ở nhánh nào

**Pre-check này chạy trên `fix/router-compound-fan-split` (commit `fd4dd42`)** — tức
`develop` cộng PR "lượt ghép quạt gió".

Điều đó **không** làm kết quả lệch, và lý do đáng ghi ra: không kịch bản nào trong
checklist chạm vùng PR đó sửa. Ba câu HVAC trong nhóm S1 hoặc là câu đơn (S1-1, S1-2),
hoặc dùng liên từ `và` (S1-3) — cả ba đã chạy đúng trên `develop` từ trước. Khác biệt
giữa hai nhánh chỉ xuất hiện ở các biến thể **không nằm trong checklist**: `rồi`/`với`/
`cùng`, và lượt ghép không có liên từ. Nên 12 dòng kết quả dưới đây đúng cho cả
`develop` lẫn nhánh PR.

**Vòng UAT thật thì phải chạy trên đúng build sẽ đem đi demo**, không phải trên nhánh
feature. Cụ thể:

- Nếu Thành merge PR `fix/router-compound-fan-split` (và/hoặc
  `fix/fe-lights-trunk-fan-state` cho UAT-005) trước UAT → `git checkout develop`,
  `git pull`, rồi chạy, và ghi commit hash đó vào cột **Build (commit)** của checklist.
- Nếu không merge gì → chạy trên `develop` như đang có, ghi hash của `develop`.

Đừng chạy UAT trên một nhánh feature: tester sẽ Verify một hành vi không tồn tại trên
thứ được demo, và bug đã đóng ở đó sẽ sống lại trên sân khấu.

## Kết quả

| ID | Kịch bản | Backend | Bằng chứng |
|---|---|---|---|
| S1-1 | "Bật điều hòa 24 độ" | ✅ | `completed`; 2 bước S1 (`set_hvac_power`, `set_hvac_temperature`); 27 → 24 |
| S1-2 | "Chỉnh quạt gió mức 2" | ✅ | `completed`; fan 3 → 2 |
| S1-3 | "Bật điều hòa 22 độ và quạt gió mức 2" | ✅ | cả nhiệt độ **và** quạt đổi; không báo ngoài dải |
| S1-4 | "Đặt nhiệt độ 45 độ" | ❌ | từ chối đúng và không đổi gì, **nhưng lời từ chối không nêu dải** → UAT-005 |
| S1-5 | "Bật đèn" (trống) | ✅ | `clarify`; *"Bạn muốn đèn pha hay đèn trần?"*; `command_count=0`; `lights` không đổi |
| S2-1 | approve | ✅ | payload có `timeout_seconds=30`, `set_window_position → 30`; sau approve kính=30, **`command_count=1`** |
| S2-2 | từ chối | ✅ | `approval_rejected`; kính=0; `command_count=0` |
| S2-3 | hết giờ | ✅ | `approval_expired`; kính=0; `command_count=0` |
| S2-5 | xe đang chạy, "Mở cửa bên lái" | ✅ | `blocked`; **không có `__interrupt__`** — chặn trước HITL, đúng yêu cầu kịch bản |
| S2-6 | resume hai lần | ✅ | kính=30; `command_count=1` — không nhảy hai bậc |
| R-1 | "Chế độ Camp Mode dùng thế nào?" | ✅ | `grounded_answer`; trích nguyên văn đúng chủ đề; citation *Màn hình cảm ứng, tr.16* |
| R-2 | câu không có trong sổ tay | ❌ | trả lời lạc đề thay vì nói không tìm thấy → UAT-006 |

**Không kiểm được bằng script** (phải chạy tay tối nay): `S2-4` (đóng hộp ≠ đồng ý),
`R-3` (đọc kỹ trích dẫn), `R-4` (autoplay lượt đầu), toàn bộ `W-1..W-5` và `O-1..O-5`,
và mọi tiêu chí dạng "thẻ trên màn hình đổi".

> **Cập nhật cùng ngày, muộn hơn: UAT-005 đã được sửa trên `develop`.** PR #121 merge
> (`9e0dc6d`) mang `DENIED_MESSAGES` vào, và đo lại trên base đó thì
> `"Đặt nhiệt độ 45 độ"` trả *"Điều hòa chỉ đặt được từ 16 đến 30 độ."* — đúng thứ
> kịch bản S1-4 đòi. Mục UAT-005 bên dưới giữ nguyên làm ghi chép của lần đo đầu;
> khi chạy UAT thật, kiểm lại S1-4 trên `develop` chứ đừng mở bug theo bản này.
> Bằng chứng: `docs/reports/mqtt-control-surface-acceptance-2026-08-15.md`.

## UAT-005 — S1-4: từ chối đúng nhưng không nói lý do

Backend chặn chuẩn: `denied`, nhiệt độ giữ nguyên 27, `command_count=0`. Vấn đề nằm
ở câu trả lời — `OUTCOME_MESSAGES["denied"]` là câu chung:

> Xin lỗi, tôi không thực hiện được yêu cầu này.

Checklist đòi *"Trợ lý nói rõ là ngoài dải cho phép"*. Tài xế nghe câu chung thì không
biết phải nói lại thế nào, nên đây là một lượt hỏng dù state đúng.

**Bản sửa đã tồn tại và chưa merge.** `origin/fix/fe-lights-trunk-fan-state` (commit
*"fix: kính không tụt xuyên đáy cửa + từ chối đèn pha nói rõ lý do và lối ra"*, tác giả
Giáp) thêm `DENIED_MESSAGES` vào `src/agents/nodes/compose.py`, gồm đúng dòng cần cho
S1-4 — `"temperature_out_of_range": "Điều hòa chỉ đặt được từ 16 đến 30 độ."` — cộng
`fan_level_out_of_range`, `window_position_out_of_range`, `volume_out_of_range`,
`seat_*_out_of_range`, `unsupported_actuator`, và `headlight_off_not_permitted` (chính
là lối ra mà UAT-003 đang thiếu).

Nên S1-4 không cần ai viết thêm code; nó cần một quyết định merge.

## UAT-006 — R-2: trả lời một câu mà sổ tay không có câu trả lời

Hỏi *"Xe này thay lốp hãng nào tốt nhất?"* → `grounded_answer` kèm trích đoạn **hướng
dẫn thay lốp dự phòng**, citation *Hỗ trợ về xe / Sửa chữa, tr.4*.

Không phải bịa: nội dung là nguyên văn sổ tay thật, citation trỏ đúng chỗ đoạn đó nằm.
Nhưng người dùng hỏi về **thương hiệu lốp** và nhận **quy trình thay lốp**, kèm giọng
điệu "đây là thông tin tôi tìm được" — tức hệ thống không hề báo rằng nó không có câu
trả lời. Đó đúng là thứ kịch bản R-2 sinh ra để bắt.

Nguyên nhân đo được, không phải phỏng đoán:

```
python -m src.rag.cli query "Xe này thay lốp hãng nào tốt nhất?"
[0.865] Hỗ trợ về xe / Sửa chữa — trang 4   (chunk_1148171_003)
[0.861] Thông số kỹ thuật — trang 8         (chunk_1148121_006)
[0.860] Bảo dưỡng / Vành và bánh xe — tr.1  (chunk_1148033_002)
```

So sánh: câu *"Áp suất lốp bao nhiêu?"* — một câu sổ tay **có** trả lời — cho top-1
**0.868**. Chênh 0.003. Nghĩa là ngưỡng hiện tại phân biệt được **ngoài miền** (câu
"Hôm nay trời đẹp quá" vẫn ra `grounded_refusal`, có test khoá) nhưng **không** phân
biệt được *trong miền mà sổ tay không trả lời*: với câu hỏi về lốp, mọi đoạn nói về
lốp đều đạt ~0.86.

Đây không phải lỗi ngưỡng đặt sai một con số — nó là giới hạn của việc dùng **điểm
tương đồng** để trả lời câu hỏi *"tài liệu này có trả lời câu hỏi kia không"*. Sửa
đúng cần một tín hiệu khác, không phải chỉnh 0.86 thành 0.87.

Theo luật của checklist — *"Không sửa kịch bản giữa buổi test để cho nó pass"* — không
được đổi R-2 sang một câu xa chủ đề hơn cho dễ đạt.

## Hai dòng để dán vào `docs/release/uat-bug-triage.md`

```
| UAT-005 | Nói "Đặt nhiệt độ 45 độ": trợ lý từ chối và không đổi nhiệt độ (đúng), nhưng chỉ nói "Xin lỗi, tôi không thực hiện được yêu cầu này" — không nêu dải 16–30 nên người dùng không biết nói lại thế nào. | S1-4 | P1 | Giáp | 2026-08-15 | Open | Bản sửa đã có sẵn trên `origin/fix/fe-lights-trunk-fan-state` (`DENIED_MESSAGES` trong `compose.py`, kèm `test_denied_messages.py`); cần quyết định merge chứ không cần viết code. Chạm luồng demo S1 nên deadline tối nay. |
| UAT-006 | Hỏi "Xe này thay lốp hãng nào tốt nhất?" (câu sổ tay không trả lời được): trợ lý trả về đoạn hướng dẫn **thay lốp dự phòng** kèm citation, thay vì nói không tìm thấy trong sổ tay. | R-2 | P1 | Nhân | Sau demo | Open | Đo được: top-1 score 0.865 cho câu này, so với 0.868 của một câu sổ tay có trả lời — ngưỡng không phân biệt được "trong miền nhưng không có câu trả lời". Refusal vẫn đúng với câu ngoài miền. Mai: người dẫn demo dùng câu ngoài miền cho phần grounded refusal. |
```

### Vì sao cả hai là P1 chứ không P0

Định nghĩa P0 trong board gồm đúng ba loại: lỗi an toàn, mất kết nối WebSocket, và
hỏng chặn demo (luồng không chạy tới cùng, hoặc backend đúng mà màn hình không phản
ánh). Cả UAT-005 lẫn UAT-006 đều **không** thuộc ba loại đó: luồng chạy tới cùng,
không có tác dụng phụ lên xe, màn hình có hiển thị.

Nhưng UAT-006 đáng được nhìn kỹ hơn mức P1 gợi ý, vì thứ nó làm hỏng là **claim trung
tâm của sản phẩm** — "không bịa, chỉ trả lời khi có căn cứ". Nó không sai về mặt an
toàn; nó sai về mặt hứa hẹn. Mức P1 ở đây là theo đúng chữ của định nghĩa, còn quyết
định có đưa phần grounded refusal lên sân khấu hay không thì thuộc về Thành.

## Điều pre-check này không chứng minh

- Không đo độ trễ end-to-end, không đo WER người nói thật. Checklist đã ghi rõ và điều
  đó không đổi: UAT chạy tay cũng không sinh ra hai số đó.
- Không chứng minh gì về UI, MQTT thật, hay TTS phát ra loa.
- `R-1` ✅ ở đây chỉ nghĩa là **có** trích dẫn và nội dung đúng chủ đề. Việc điều kiện
  phiên bản (ECO/PLUS, SDI/CATL) còn nguyên trong câu trả lời hay không là `R-3`, và
  phải đọc bằng mắt.

# chitchat-v1 — bộ đo năng lực trò chuyện (SP-2)

Mỗi ca hai nhãn: `expected_route` (cho classifier 3 lớp — chung thước với
`dinh-tuyen-v1`) và `expected_hanh_vi` (cho generator): `xa_giao` / `tro_chuyen`
(không thông số) / `tu_choi_mem` (+ gợi ý) / `khong_ro_y` (câu ậm ừ, nói lắp — hành
vi đúng là HỎI LẠI, không đoán) / `khong_toi_generator` (ca bẫy: giống
chitchat nhưng là control/manual — ĐO RANH GIỚI, không đo chitchat).

Nguồn (`source`): `sp0` = 15 câu đã đo ở SP-0 (`eval/results/do-tre/20260822T030757…`);
`tu_viet` = người viết hệ thống tự viết → **chỉ là tripwire**, mọi trích dẫn phải nói rõ;
`son` / `thanh` = câu độc lập xin qua issue #244 — phần độc lập duy nhất
của bộ đo, bổ sung khi về. Chưa về thì chấm trên 25 ca và ghi rõ thiếu; không tự
viết bù rồi gọi là độc lập.

## Bổ sung 22/08 — trục phương ngữ (28 ca, issue #244)

@hason0510 gửi 14 **cặp** cùng ý khác giọng và tự dán nhãn `ai-sinh-nam` /
`ai-sinh-bac`: câu do AI sinh sau khi đã đọc spec, nên **không phải nguồn độc lập**
— giữ nhãn nguồn ấy, đừng đọc thành `son`. Giá trị của chúng là *trục đo*, không
phải *nguồn*: cặp nào hai bản định tuyến khác nhau thì chênh lệch quy được về giọng.

Chúng phơi ra ba chỗ code đọc **vị trí** chữ `"không"` mà quên tiểu từ cuối câu
(`is_question`, `is_negated`, `_words_to_number`) — nặng nhất là
`"Bật điều hòa được không vậy"` → `denied / temperature_out_of_range`. Sửa ở
`bo_tieu_tu_cuoi` (`question.py`), test `tests/test_agents/test_tieu_tu_cuoi_cau.py`.
Ba trong bốn dự đoán cơ chế ở comment gốc trượt (`AN10`/`AN11`/`AN14` không hề đi
đường tắt) — trục đo vẫn đúng, chỉ thủ phạm là chỗ khác.

Run đã chạy (22/08): `chitchat/20260822T043207` (một server, timeout 2 s — 7 lượt classify timeout),
`…043502` (một server, timeout 3,5 s — tổng p50 5,9 s), `…043559` và **`…043750`** (hai server, sau
sửa nhãn CC-S14 — cả hai cổng = 0, chấm tay ở `graded_chitchat.jsonl`). Câu độc lập đã về: **0/15**.

Hai cổng cứng khi chạy `python -m src.agents.eval --mode chitchat`:
`manual→control = 0` (ADR-026) và `bẫy→chitchat = 0`. Run dir: `eval/results/chitchat/`.

Ghi chú nhãn: `CC-S05` "Xe này đi đường dài có êm không nhỉ?" gắn `manual` vì router
đi đường tắt sổ tay (có "xe" + dạng nghi vấn) — đúng thiết kế §2.3; `CC-S13` "Hát một
bài đi" là `control` (muốn nghe nhạc).

**Sửa nhãn 22/08, sau run `20260822T043207`:** `CC-S14` "Bạn thích xe nào" ban đầu gắn
`manual` với lý do "có chữ xe → đường tắt" — lý do **sai**: câu không có dạng nghi vấn
nên router KHÔNG đi đường tắt, và theo hành vi lời nói nó là câu hỏi sở thích của trợ
lý (chitchat / `tro_chuyen`). Đổi nhãn vì lý do gán nhãn sai, không phải vì nó làm vỡ
cổng; ghi lại để ai đọc số sau biết ca này từng đổi.

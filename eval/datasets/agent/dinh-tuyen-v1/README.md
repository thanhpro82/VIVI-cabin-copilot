# dinh-tuyen-v1 — bộ đo phân loại 3 lớp của SP-1

Ghép từ ba nguồn để tránh lặp bài học `agent/v3` (đề tự ra = tripwire, không phải
thước): phần manual lấy nguyên văn `hoi-nhu-tai-xe-v1` (42 ca, RAG workstream
viết); phần control là ca #149/ADR-022 cộng biến thể mệnh lệnh không khớp luật
(20 ca `DT-C*`); phần chitchat: 25 ca `DT-CC01..25` nhập từ `chitchat-v1` ngày 22/08 (SP-2) —
ma trận đủ ba lớp từ đó; ca `source` có `tu_viet` là tripwire.

Trường: `case_id`, `input_text`, `expected_route` ∈ {control, manual, chitchat},
`source`. Cổng cứng: ô `manual→control` = 0 (ADR-011 giữ nó bằng 0 về cấu trúc;
classifier không được mở ra).

Nhãn `expected_route` của 20 ca `DT-C*` là **control theo nghĩa phân loại** (tài
xế muốn xe làm gì) — planner có ra plan chạy được hay không là việc của ADR-016,
không phải của bộ đo này.

Chạy: `python -m src.agents.eval --mode dinh-tuyen` (cần llama-server thật) →
`eval/results/agent-routing/<run-id>/`.

## Sửa 21/08 (trước lần merge đầu)

Bỏ `DT-C011` "Kính mờ hết cả rồi" (nhãn control, do người viết classifier tự
đặt): nó là **sinh đôi ngược nhãn** với ca độc lập "Kính mờ hết cả rồi nhìn
không thấy đường" (manual, `hoi-nhu-tai-xe-v1`). Khi hai nguồn cho cùng một lời
nói hai nhãn ngược nhau, giữ nhãn của nguồn độc lập và bỏ nhãn tự viết — không
bao giờ ngược lại. Còn 61 ca (41 manual + 19 control + 1 manual dạng offer).

## Bổ sung 22/08 (SP-2)

Nối 25 ca `DT-CC*` từ `chitchat-v1` (15 `sp0` + 10 `tu_viet`). Tổng 86 ca.

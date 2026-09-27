# ADR-026: SLM phân loại 3 lớp trước RAG; luật giữ đường tắt và lưới an toàn

- Status: Accepted
- Date: 2026-08-21
- Decision owner: Nhân
- Thu hẹp: [ADR-022](ADR-022-planner-khong-bi-rag-phu-quyet.md)
- Giữ nguyên: [ADR-011](ADR-011-default-to-manual-lookup.md) làm fail-safe,
  [ADR-016](ADR-016-slm-fallback-gates.md) làm cổng planner
- Spec: `docs/superpowers/specs/2026-08-21-slm-bo-nao-dinh-tuyen-design.md`

## Context

ADR-022 chỉ mở cửa planner **sau khi** RAG đã trượt (`grounded_refusal` +
`default_to_manual`), và không có đường nào tới chitchat. Hệ quả đo được trên
`dinh-tuyen-v1` (62 ca, baseline classifier-luôn-manual = hành vi develop):
**41/62 đúng, 18/20 lệnh nói tự nhiên bị nuốt vào tra sổ tay** — cả một miền
chức năng biến mất sau lớp vỏ "không tìm thấy trong sổ tay".

## Decision

1. Câu router trả `default_to_manual` đi qua node `slm_classify` (một lượt gọi,
   chỉ phân loại 3 lớp, grammar ép enum) rồi mới rẽ nhánh. Câu khớp luật vẫn đi
   đường tắt ~0 ms.
2. Fail-safe ba tầng (timeout / HTTP lỗi / payload hỏng) đều về `manual` —
   `slm_enabled=false` thì graph giao **y hệt** trước (test khoá).
3. Chiều "RAG trượt → planner" của ADR-022 **giữ nguyên làm lưới** cho các câu
   `not_control` không qua classifier.
4. **Lưới tất định sau model** (`ap_luoi_an_toan`): câu hỏi khả năng
   ("... được không", "có ... không") mà model chấm `control` bị hạ về `manual`.
   Lý do: một câu hỏi mà planner trả plan S1 hợp lệ (vd `set_hvac_power`) sẽ
   **chạy luôn không cần duyệt** — đúng lớp lỗi ADR-011 sinh ra để giữ bằng 0.
   Prompt v2→v4 không ép nổi model tự phân biệt ca này (3 run 21/08).

## Cổng cứng: ô `manual→control` = 0, đếm THÔ

Quyết định của nhóm (21/08): cổng là con số thô trong ma trận, không kèm phân
loại "thực-thi-được hay không" — thước phải tự đứng, không cần người mổ ca mỗi
lần vỡ. Phiên bản đầu của ADR này từng phát biểu cổng theo nghĩa hẹp hơn
("có-thể-thực-thi = 0") khi ô thô đo được 4; phiên bản đó bị bác và 4 ca được
sửa thật thay vì sửa câu chữ:

- **2 ca của luật `negated_command`** ("Đèn trong xe cứ sáng hoài không tắt",
  "Kính mờ... nhìn không thấy đường"): guard phủ định coi mọi chữ "không" là
  mệnh lệnh phủ định. Sửa tất định trong `router.py`
  (`_phu_dinh_ta_trieu_chung`): actuator đứng TRƯỚC chữ "không" là lời TẢ
  trạng thái, không phải lệnh. Nợ này có sẵn trên develop từ trước SP-1.
- **2 ca miền ngoài tầm với** ("gạt nước chậm lại", "đổi ngôn ngữ"): lưới
  `ap_luoi_an_toan` thêm danh sách ĐÓNG các miền không có tool
  (`_MIEN_NGOAI_TAM`, nguồn `docs/coverage_matrix.md`) — chấm control cho
  chúng chỉ dẫn tới clarify ngõ cụt, hạ về manual thì sổ tay trả lời được.
  Danh sách phải đi theo coverage_matrix: miền nào có tool thì xoá khỏi đây.
- Kèm hai sửa nhỏ: một cặp ca **sinh đôi ngược nhãn** trong dataset bị loại
  (giữ nhãn nguồn độc lập, bỏ nhãn tự viết — xem README dataset), và bộ đo
  thôi đè `offer`/`clarify` thành nhãn khác (`offer` là "hỏi lại trước khi
  làm" của ADR-011, không chạm executor, giữ nhãn riêng).

## Bằng chứng (run `eval/results/agent-routing/20260821T134426.297310Z`, 61 ca)

| | develop (baseline luật thuần) | SP-1 |
|---|---:|---:|
| đúng | 41 | **59** |
| lệnh bị nuốt vào sổ tay (`control→manual`) | 18 | **1** |
| **`manual→control` (cổng cứng, thô)** | 2 | **0** ✅ |
| `manual→offer` (hỏi lại trước khi làm — thiết kế ADR-011) | 1 | 1 |

(Baseline 41/62 đo trên bản dataset trước khi loại ca sinh đôi — run
`20260821T130203.508716Z` lưu cả hai mốc.)

Chi phí lưới an toàn đo được: 1 ca ("Im lặng chút được không" — mệnh lệnh lịch
sự bị hạ về manual). Chiều lỗi này an toàn (từ chối mềm thay vì làm), đúng triết
lý ADR-011.

Độ trễ classify trên máy demo (Qwen3-4B, llama-server 8093): **~450 ms/lượt ấm,
570 ms lượt đầu** (5 lượt, test contract 21/08) — dưới hẳn timeout 2 s. SP-0 sẽ
đo phân bố đầy đủ trước khi đặt cổng chính thức.

## Consequences

- `route_reason` mới: `slm_classified_{control|manual|chitchat}`,
  `slm_classify_failed`. Độ trễ classify tính vào stage `routing` (last-write-wins) —
  KHÔNG có stage mới: `record_stage` raise với tên ngoài bảy stage của `api_spec.md:342`,
  và đó là lỗi P0 lọt qua #232 (mọi lượt API qua classifier nổ 500), sửa ở hotfix cùng ngày.
- `RouteDecision` thêm disposition `chitchat` (cấm `candidate_plan`).
- Nhánh chitchat tạm trả `CHITCHAT_TAM_GIU` (graph.py) — SP-2 thay bằng
  generator thật. Hai đường chitchat (classifier + union planner) song song là
  cố ý cho tới SP-2.
- **Ràng buộc release (PM/PO, review #232):** merge PR này KHÔNG đồng nghĩa bật
  cờ cho người dùng. `SLM_ENABLED` giữ default `false`; bật cho demo/release
  cần đủ hai điều kiện — SP-2 xong (generator chitchat thật + bộ đo đủ ba lớp)
  và PM/PO review lại trên số đo ba lớp. Trước đó cờ chỉ bật trên máy dev.
  **Cập nhật 22/08 (SP-2):** hai điều kiện đã có hiện vật — generator thật
  (`QwenChitchat` + cổng bốn lớp) và bộ đo ba lớp (`dinh-tuyen-v1` 86 ca, run
  `agent-routing/20260822T043245.916374Z`: 78/86, `manual→control` = 0; `chitchat-v1`
  run `chitchat/20260822T043750.630790Z`: `bẫy→chitchat` = 0, chấm tay 13/14 đúng
  phạm vi, 0/14 bịa). Điều kiện còn thiếu cho quyết định bật cờ: 15 câu độc lập
  (issue #244) chưa về, và cấu hình server — số đo chỉ đạt với **hai server**
  (SP-0 §3); một server thì tổng chitchat p50 5,9 s.
  **Cập nhật 23/08:** điều kiện *"hai đường chitchat hợp nhất"* đã **đạt** — chuỗi
  `kind: chitchat` do planner trả về nay đi qua đúng bộ cổng của node `chitchat`, và
  cổng đầu vào (triệu chứng an toàn) chặn trước cả planner. Trước đó cùng một câu bịa
  đi đường node thì bị chặn, đi đường planner thì lọt. Việc này thành điều kiện gấp khi
  #258 bật `slm_enabled` mặc định — đường planner từ đó có mặt trên mọi checkout.
  Ghi nhận một điều đo được để cân khi review: câu giữ chỗ hôm nay vẫn tốt hơn
  hành vi develop (cùng câu đó nhận "không tìm thấy trong sổ tay" — một câu từ
  chối sai chủ đề).
- Bộ đo `dinh-tuyen-v1` mới có 2/3 lớp (chitchat chờ SP-2) — mọi trích dẫn phải
  ghi rõ điều đó.
- Hai ca `negated_command` là nợ của router luật, mở issue riêng khi đụng tới.

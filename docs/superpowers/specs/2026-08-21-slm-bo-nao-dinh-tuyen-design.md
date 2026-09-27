# SLM làm bộ não định tuyến — thiết kế SP-1

- Ngày: 2026-08-21
- Trạng thái: Đã duyệt qua brainstorming (phương án A), chờ implementation plan
- Người quyết: Nhân
- Liên quan: ADR-006, ADR-011, ADR-016, ADR-022, issue #149

## 1. Bối cảnh và vấn đề

Agent hiện có ba năng lực không đều nhau: **điều khiển** (dày nhất — 15 tools, HITL
giọng nói #191, `open_app` #172), **tra cứu sổ tay** (chạy được, tầng nén #197 đã
merge), và **trò chuyện thông thường** (chưa có gì ngoài fallback từ chối).

Nút thắt kiến trúc: luật tất định đứng trước ở quá nhiều chỗ, SLM chỉ được gọi khi
mọi thứ khác đã thất bại. Hệ quả đo được:

- Câu lệnh tự nhiên không khớp luật (`"Nóng quá, giảm nhiệt độ xuống đi"`) bị
  `default_to_manual` đẩy vào sổ tay — bug #149, ADR-022 chỉ vá được một nửa
  (planner chỉ chạy sau khi RAG đã trả `grounded_refusal`).
- Chitchat không có đường nào tới: mọi câu xã giao đều thành tra cứu sổ tay hỏng.
- Nhóm đã chốt "SLM là phải dùng"; trên máy demo `SLM_ENABLED=true` là vĩnh viễn.

## 2. Phân rã tổng thể (umbrella)

Mục tiêu "hoàn thiện agent" cắt thành 5 sub-project, mỗi cái một chu trình
spec → plan → code riêng. Spec này là **thiết kế của SP-1**; các SP khác chỉ ghi
phạm vi để giữ ranh giới.

| SP | Nội dung | Phụ thuộc |
|---|---|---|
| SP-0 | Spike đo độ trễ từng đoạn (STT / route SLM / retrieval / sinh chữ) trên máy dev, chốt cổng p50/p95 thật. Không giữ code. | — |
| **SP-1** | **SLM phân loại 3 lớp làm bộ não định tuyến; luật giữ làm đường tắt + lưới an toàn** (spec này) | SP-0 cho số đặt cổng |
| SP-2 | Năng lực chitchat: xã giao + quanh xe/chuyến đi, từ chối mềm ngoài phạm vi, lọc chữ Hán, bộ đo ~40 ca viết mới | SP-1 (cần người định tuyến tới) |
| SP-3 | Tầng nói + tóm tắt: rút khung 72→27 ký tự, xét lại trần `MAX_SPOKEN_CHARS`, số phận PR #230/#231, nhãn cấu trúc `BlockKind.LIST` xuống `Evidence`, cổng `tom_tat` đo trên chunk thật | độc lập, chạy song song được |
| SP-4 | Hợp nhất display/speak (rebase PR #221) | CUỐI — chờ SP-1..3 lắng vì cùng chạm `compose.py` |

Quyết định phạm vi chitchat (chốt ở brainstorming, ghi đây để SP-2 dùng): xã giao +
chuyện quanh xe/chuyến đi; ngoài phạm vi (tin tức, toán, kiến thức chung) → từ
chối mềm. Trần độ trễ: **chưa chốt, SP-0 đo trước** — không đặt cổng khi chưa có
phân bố.

## 3. Thiết kế SP-1

### 3.1 Dòng chảy định tuyến

Không thay router — thay **ý nghĩa của nhánh trượt**. Hôm nay `router.py` không
khớp luật nào thì rơi `default_to_manual` (ADR-011). Thiết kế mới biến chỗ rơi đó
thành "hỏi SLM":

```
normalize → route (luật tất định, giữ nguyên)
              ├─ khớp luật control/manual/POI…  → đi thẳng như cũ (đường tắt ~0 ms)
              └─ default_to_manual (không khớp gì)
                     ▼
              slm_classify  ← NODE MỚI, một lượt gọi, chỉ phân loại
                     ├─ "control"  → slm planner (QwenPlanner, có sẵn) → validate → safety → …
                     ├─ "manual"   → rag → tom_tat → compose (nguyên trạng)
                     ├─ "chitchat" → chitchat_node (SP-2; tạm là fallback từ chối hiện tại)
                     └─ lỗi/timeout/JSON hỏng → manual (fail-safe = ADR-011 cũ)
```

Bốn hệ quả:

1. **Câu lệnh khớp luật không trả thêm độ trễ** — SLM chỉ được gọi trên câu lạ.
2. **Mọi cổng an toàn giữ nguyên vị trí.** Classifier nói "control" không tạo plan;
   nó chỉ mở cửa cho QwenPlanner đề xuất `CandidateActionPlan`, plan vẫn qua
   validate → policy → HITL. Invariant "chỉ policy gán `safety_level`" không đổi.
3. **ADR-022 bị thu hẹp một nửa**: classifier mở cửa planner sớm hơn cơ chế
   "RAG trượt rồi mới tới planner". Chiều ngược giữ làm lưới: classifier nói
   "manual" mà RAG trả `grounded_refusal` thì vẫn rơi về planner như ADR-022.
   Cần một ADR mới ghi việc thu hẹp này khi implement.
4. **`RouteDecision` thêm disposition `chitchat`** trong `contracts.py`, giữ tính
   exclusive: `chitchat` forbid `candidate_plan` như `not_control`.

Không đưa vào (YAGNI, để dành làm thí nghiệm nếu độ chính xác không đạt): chạy
retrieval trước (~18–22 ms warm) rồi đưa điểm RAG cho classifier làm dữ kiện.

### 3.2 Hợp đồng `slm_classify`

**Một model thường trú cho mọi vai.** `SLM_ENDPOINT` và `TOM_TAT_ENDPOINT` cùng
trỏ `127.0.0.1:8093` nhưng chưa có gì ép cùng model — bẫy cấu hình câm đã ghi
trong runbook §2.3. Chốt: một llama-server, một Qwen3-4B thường trú, phục vụ cả
bốn vai (classify, planner, chitchat, tóm tắt). Không thêm endpoint thứ ba.

**Prompt** — tối giản, tiếng Việt, few-shot, mục tiêu ≤ ~250 token:

```
Phân loại câu của tài xế vào đúng một nhóm:
- control: yêu cầu xe LÀM gì (chỉnh, bật, tắt, mở, đặt...)
- manual: HỎI về xe, tính năng, thông số, cách dùng
- chitchat: xã giao hoặc chuyện trò không đòi xe làm gì

[6–8 ví dụ, mỗi nhóm ≥2, lấy từ ca thật đã đo — bắt buộc có
"Nóng quá, giảm nhiệt độ xuống đi" → control (ca #149)]
Câu: "{utterance}"
```

Hai chi tiết bắt buộc: `temperature 0` (định tuyến phải tất định), và **tắt
thinking mode của Qwen3** (`enable_thinking=false` / `/no_think`) — quên là mỗi
lượt phân loại đẻ vài trăm token suy nghĩ.

**Đầu ra ép bằng grammar.** llama-server nhận `json_schema`; ép
`{"intent": "control" | "manual" | "chitchat"}` bằng enum ngay tầng sinh — hết
lớp lỗi parse. Vẫn giữ guard đọc kết quả vì grammar không cứu được HTTP 500.

**Fail-safe ba tầng, tất cả rơi về `manual`:** timeout (mặc định 2 s, đọc từ
config) / HTTP lỗi / kết quả rỗng. "Manual" là hành vi ADR-011 hôm nay, nên
**tắt SLM là hệ thống y hệt develop** — tính chất làm phép đo A/B sạch.

**Cờ:** không thêm cờ mới. `SLM_ENABLED` gác luôn classifier (hai vai chỉ có
nghĩa khi đi cùng nhau). Default `false` giữ invariant "no LLM on the path";
máy demo bật trong `.env`.

**Dấu vết:** `route_reason` mới `slm_classified_{control|manual|chitchat}` +
`slm_classify_ms` vào trace, để `/metrics/summary` và eval tách được lượt nào
đi đường nào.

### 3.3 Kiểm thử và bằng chứng

Ba tầng test theo nếp repo:

1. **Unit (fake client, không mạng):** mỗi nhánh classify một test; ba đường
   fail-safe đều về `manual`; và test khoá **`SLM_ENABLED=false` ⇒ graph giao
   hệt develop**, so bằng trace.
2. **Contract (`slow`, cần llama-server thật):** grammar ép nổi enum, thinking
   mode tắt thật, `slm_classify_ms` vào trace. CI không chạy — bằng chứng sinh
   từ máy dev như mọi test model khác.
3. **Eval — bộ đo định tuyến mới, không chấm bằng đề tự ra** (bài học `agent/v3`
   = tripwire vì người viết router tự viết đề):

| nguồn | vai | ca |
|---|---|---|
| `hoi-nhu-tai-xe-v1` (42 ca, RAG workstream viết) | manual nói tự nhiên | 42 |
| ca ADR-022/#149 + biến thể mệnh lệnh không khớp luật | control nói tự nhiên | ~20 |
| bộ chitchat mới của SP-2 (phần nhãn dùng được ngay) | chitchat + ngoài phạm vi | ~40 |

**Chấm bằng ma trận nhầm lẫn, cổng đặt theo độ nguy hiểm từng ô:**

- `manual → control`: ô nguy hiểm nhất. ADR-011 đang giữ nó **bằng 0 về cấu
  trúc**; classifier phải giữ nguyên 0 — cổng cứng.
- `control → manual`: chính là hành vi develop hôm nay (bug #149) — mỗi ca thoát
  là lãi ròng; cổng = "không tệ hơn hiện tại".
- `chitchat ↔ manual`: nhầm chiều nào cũng lành; theo dõi, chưa đặt cổng.

Ngưỡng % cụ thể **cố ý để trống tới sau SP-0 + lần chạy đầu** — đặt cổng trước
khi có phân bố là đúng cái sai ADR-022 đã mổ.

**Bằng chứng:** mỗi lần đo một run id bất biến dưới `eval/results/agent-routing/`
(suite có sẵn, thêm mode); mọi con số trong spec/PR trỏ về một run id.

## 4. Xử lý lỗi

- SLM chết/không bật server: ba tầng fail-safe về `manual`; không lượt nào treo.
- Classifier trả "control" nhưng planner không đề xuất được plan hợp lệ: đường
  có sẵn của ADR-016 xử (validate trượt → compose từ chối); không thêm nhánh mới.
- Hai lượt gọi liên tiếp (classify rồi planner) làm tăng độ trễ lượt control-lạ:
  chấp nhận trong SP-1, SP-0 đo con số thật; nếu vượt cổng thì thí nghiệm gộp
  prompt là việc của vòng sau, không phải của spec này.

## 5. Ngoài phạm vi SP-1

- Sinh câu chitchat (SP-2) — SP-1 chỉ dựng nhánh, tạm trả fallback hiện tại.
- Mọi thay đổi tầng nói/tóm tắt (SP-3), display/speak (SP-4).
- Gộp classify + trả lời vào một prompt (phương án B đã bác ở brainstorming:
  parse hai chế độ là chỗ vỡ kinh điển, và mất khả năng đo riêng định tuyến).
- SLM toàn quyền thay luật (phương án C đã bác: đè ADR-006/010, 45 tok/s không
  gánh nổi mili giây của đường control).

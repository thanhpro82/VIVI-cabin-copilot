# ADR-029: câu trả lời của VIVI được hiện trên bề mặt kỹ sư

- Status: Proposed — chờ @thanhpro82 (PM/PO)
- Date: 2026-08-24
- Decision owner: WS3 (Sơn)
- Sửa cách hiểu của: `docs/tasks/TASK-BE-OBS-001-engineer-observability.md` §6
- Giữ nguyên: `docs/api_spec.md:11,445,686,739` (danh sách cấm), quyền RBAC của
  `/traces/{id}` và `/metrics/summary`
- Liên quan: ADR-028 pool xe ảo theo phiên — **chưa merge**, còn nằm trên nhánh
  `feat/pool-xe-ao-theo-phien`; ADR này cố ý vào trước và không phụ thuộc nó,
  [ADR-015](ADR-015-quote-verbatim-thay-vi-slm-viet-lai.md) (trích nguyên văn thay vì
  để SLM viết lại)

## Context

Màn kỹ sư hiện đủ số liệu vận hành của một lượt — độ trễ từng stage, mức an toàn,
kết quả tool, phiên bản model/prompt/index — nhưng **không hiện VIVI đã trả lời gì**.
Nên khi một lượt bị đánh giá là sai, kỹ sư nhìn thấy nó *chạy đúng* mà không có cách
nào biết nó *nói sai*. Đó là lỗ hổng lớn nhất còn lại của công cụ quan sát: mọi
metric đều đo cơ chế, không cái nào đo nội dung.

Cản trở không nằm ở frontend. `TraceRecord` (`src/services/trace_store.py`) chưa bao
giờ có field văn bản, và `TraceCollector._on_assistant_response` cố ý chỉ đếm
citation. Ba docstring và một test khẳng định đây là ràng buộc redaction.

## Vì sao cách hiểu cũ chặt hơn spec

Danh sách cấm thật sự, lặp lại y hệt ở bốn chỗ trong `api_spec.md` (`:11`, `:445`,
`:686`, `:739`), là:

> raw prompts, hidden chain-of-thought, raw audio, **unrestricted transcripts**,
> credentials, secret paths

**Câu trả lời của trợ lý không nằm trong danh sách đó.** "Transcript" là câu *người
dùng nói*, do STT sinh ra — một thứ khác hẳn.

Luật "không lộ câu trả lời" chỉ tồn tại trong phần hiện thực: hai docstring, và
`tests/test_api/test_observability_privacy.py` gộp chung hằng số `RESPONSE` vào cùng
rổ rò rỉ với `TRANSCRIPT`. Đó là cách đọc chặt hơn spec của người viết OBS-001, chứ
không phải điều spec bắt. ADR này nới đúng phần chặt thừa đó, và **không** đụng tới
danh sách cấm.

## Câu trả lời không phải nội dung của tài xế

Đây là lập luận chịu lực, nên nó được kiểm bằng cách truy hết đường sinh chứ không
bằng suy đoán. `display_text` chỉ ra đời ở ba nơi (`src/api/turns.py:514,555,787`),
và nội dung của nó luôn thuộc một trong ba loại:

| Loại | Ví dụ | Nguồn |
|---|---|---|
| Template dựng từ tên tool + tham số | `"đặt điều hòa ở 22 độ"` | `compose.py:213-263` |
| Trích nguyên văn sổ tay VF9 | đoạn evidence, cắt ở `QUOTE_MAX_CHARS` | `_quote_top_evidence` |
| Câu xác nhận / lỗi cố định | `"Bạn có chắc muốn mở kính lái không?"` | `prompt_text`, envelope lỗi |

**Không đường nào chèn lời tài xế vào.** Không có f-string nào trong `compose.py`
nhận `state["text"]`. Nên hiện câu trả lời cho kỹ sư không làm lộ nội dung của người
lái — nó làm lộ nội dung do chính server sinh ra.

Một hệ quả phải nói rõ: với lượt tra sổ tay, câu trả lời **là** một đoạn sổ tay VF9.
Màn kỹ sư sẽ bắt đầu hiện từng đoạn tài liệu. Đó là mở rộng phạm vi có chủ đích, và
nó không mới về bản chất — `GET /citations/{id}` đã trả `excerpt` cho tài xế từ trước.

## Decision

**1. Thêm `answer_text` vào `TraceRecord` và `TraceData`.** Nguồn là
`assistant.response.display_text`. `speak_text` **không** lưu: nó là biến thể
đọc-thành-tiếng của cùng nội dung, lưu thêm chỉ tốn RAM mà không nói thêm điều gì.

**2. Đường biên không đổi.** Transcript và nội dung citation vẫn **không có field**
trong `TraceRecord`. Vẫn là bảo đảm bằng cấu trúc: không lưu thì không rò. Bốn nguồn
văn xuôi khác — `error.message`, `action.blocked.reason`, `plan.ready.summary`,
`citations[].excerpt` — vẫn bị bỏ qua, vì chúng có thể mang đường dẫn hoặc nội dung
chưa cắt.

**3. `/metrics/summary` không nhận gì cả.** Nó là phép fold thuần ra số. Được phép ở
`/traces/{id}` không kéo theo quyền có mặt ở đây, và test khoá riêng điều đó.

**4. Trần 2000 ký tự là lưới an toàn RAM, không phải chính sách.** Câu dài nhất hôm
nay là trích sổ tay ở `QUOTE_MAX_CHARS = 1200` cộng lead-in, nên không câu thật nào
bị cắt. Kho giữ tối đa `trace_store_maxsize` bản ghi (mặc định 200) → trần đóng góp
~400 KB. Khi có cắt thì để lại `…`: cắt im lặng làm kỹ sư tưởng composer sinh ra một
câu cụt.

**5. Test khoá cả hai chiều.** `test_observability_privacy.py` giờ đỏ khi
`answer_text` biến mất, **và** đỏ khi transcript/excerpt/đường dẫn lọt ra. Bỏ một
chiều đi là vỡ hợp đồng, chỉ khác nhau ở chỗ vỡ về phía nào.

**6. Thêm `vehicle_id` vào cùng lượt sửa này.** Xem dưới.

## Vì sao `vehicle_id` đi chung PR

`TraceData` là schema **đóng** (`extra="forbid"`, cộng một test so `set(...)` với
`api_spec.md`). Mỗi lần thêm field là một lần sửa model + view + spec + test, và một
lần tranh luận "bề mặt kỹ sư được thấy gì". Bảng đội xe (hạng mục sau ADR-028) cần
`vehicle_id` trong `TraceData` vì hôm nay trace chỉ có `session_id`, nên kỹ sư không
biết một lượt tác động lên xe nào. Tách làm hai PR nghĩa là cãi cùng một cuộc tranh
luận hai lần.

**Nguồn là cột `sessions.vehicle_id`, không phải `get_settings().vehicle_id`.** Lấy
từ settings thì đúng hôm nay và **sai lặng lẽ đúng ngày ADR-028 merge**, vì lúc đó
mỗi phiên thuê một xe khác nhau còn settings vẫn trả về ô số 0. Đọc từ cột phiên thì
đúng ở cả hai thời điểm mà không phải sửa gì ở tầng quan sát — pool ghi chiếc xe đã
thuê vào chính cột đó.

**Bẫy phải biết trước khi làm bảng đội xe.** Khi pool cạn, `pool.thue()` trả `None`
và `session_state.create_session` rơi về `or vehicle_id`, nên một phiên **chỉ xem**
vẫn ghi `vehicle-demo-01` vào cột đó. Dữ liệu không sai — phiên đó thật sự đang đọc
trạng thái xe số 0 — nhưng nó có nghĩa là **bảng đội xe không được suy "ai đang lái
xe nào" từ `trace.vehicle_id`**. Nguồn của việc đó là `VehiclePool.suc_chua()` và
bảng thuê, đúng luật một-nguồn-sức-chứa mà ADR-028 đặt.

Truy vấn nằm ở `src/services/trace_collector.py` và đọc thẳng SQLite qua
`get_connection()` chứ **không** gọi `src.api.session_state`: `src/services/` hiện
không import `src/api/` ở bất kỳ đâu, và tầng quan sát không được là chỗ đầu tiên
đảo ngược thứ tự đó.

## Phụ thuộc chưa giải: PR #221 đổi nghĩa của chính trường này

PR #221 (`feat/thong-nhat-display-va-speak-text`, đang `CONFLICTING`) gộp
`display_text` và `speak_text` làm một và **giữ bản `speak_text`**. Nó cũng sửa
`assistant_response_payload` trong `src/services/ivi_events.py` — đúng hàm dựng sự
kiện `assistant.response` mà collector của ADR này đọc.

Nên sau khi #221 merge, `answer_text` **đổi nghĩa mà không đổi một dòng code nào**:

| | Trước #221 | Sau #221 |
|---|---|---|
| Lượt tra sổ tay | trích nguyên văn tới `QUOTE_MAX_CHARS` = 1200 | câu đã chọn ≤ 240 ký tự + lời mời |
| Mọi lượt khác | không đổi | không đổi |

Ba hệ quả, ghi ra đây để không ai phải phát hiện lại:

1. Đoạn "Câu trả lời không phải nội dung của tài xế" ở trên vẫn **đúng nguyên** —
   `speak_text` cũng do server sinh, cũng không chèn lời tài xế. Lập luận chịu lực
   không phụ thuộc #221.
2. Câu "màn kỹ sư sẽ bắt đầu hiện từng đoạn sổ tay VF9" thành **hết đúng một phần**:
   sau #221 nó hiện câu đã chọn, không phải cả đoạn. Phạm vi hẹp lại chứ không rộng
   ra, nên không cần duyệt lại.
3. Trần `ANSWER_TEXT_MAX_CHARS = 2000` càng thừa thãi hơn. Giữ nguyên — nó là lưới
   an toàn RAM, không phải chính sách, và một trần rộng không gây hại.

**Không có việc phải làm trước.** Ghi lại để khi #221 vào, người đọc ADR này biết vì
sao con số 1200 ở đây không còn khớp với code.

## Consequences

**Được**

- Kỹ sư đọc được một lượt sai mà không phải dựng lại nó, và không phải xin log của
  tài xế.
- Bảng đội xe sau ADR-028 chạy được ngay, không cần đổi schema lần nữa.
- Ranh giới redaction giờ nằm ở **một chỗ** (ADR này) thay vì rải trong ba docstring.

**Mất / phải chấp nhận**

- Màn kỹ sư bắt đầu hiện từng đoạn sổ tay VF9 với mỗi lượt tra cứu.
- `TraceRecord` không còn "không có field văn bản nào" — bảo đảm bằng cấu trúc yếu
  đi một bậc, và từ nay phải đọc danh sách được-phép thay vì tin vào sự vắng mặt.
  Đây là lý do test khoá hai chiều thay vì một.
- `vehicle_id` là hằng số cho tới khi ADR-028 vào, nên nó trông thừa trong khoảng
  thời gian đó.
- Một lượt tra SQLite đồng bộ thêm vào listener của `turn.accepted`. Là tra khoá
  chính trên file cục bộ, không cùng loại với lời gọi SLM chặn event loop đã sửa ở
  PR #257 — nhưng vẫn là một lời gọi đồng bộ mới, ghi ra đây để không ai bắt chước
  kiểu này cho một việc nặng hơn.

## Cách kiểm

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_observability_privacy.py tests/test_services/test_trace_vehicle_id.py tests/test_api/test_traces.py -q
```

Đỏ ở `test_trace_co_cau_tra_loi_cua_vivi` nghĩa là ai đó gỡ `answer_text` đi "cho an
toàn". Đỏ ở `test_trace_khong_chua_transcript_citation_hay_duong_dan` nghĩa là ai đó
nới thêm một bước nữa mà không qua ADR.

# ADR-032 — Routine điều khiển bằng giọng nói

- **Status:** Accepted
- **Date:** 2026-08-30
- **Owner:** Hoàng Văn Nhân (làn Agent)
- **Liên quan:** #274, #299, epic #270; ADR-006/ADR-010 (router tất định), ADR-011, #196
- **Spec/Plan:** `docs/superpowers/specs/2026-08-30-routines-bang-giong-noi.md`,
  `docs/superpowers/plans/2026-08-30-routines-bang-giong-noi.md`

## Context

Epic #270 ghi *"voice-first để preview và chạy"*. Đo trên `develop` @ `d088b49` qua graph
thật, **sáu câu Routine rơi xuống tra sổ tay cả sáu**:

```
"Chạy routine Đi làm"         -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Routine Về nhà gồm những gì" -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Dừng lại"                    -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
```

Câu thứ ba là lệnh **hủy**. Nguyên nhân xác minh được: `routines_intent.py` (#285) đọc
được ý định từ trước nhưng **không ai gọi nó** — chỉ test của chính nó import — và
`router.py` không có một chữ `routine` nào. Việc cần làm là **nối**, không phải viết mới.

## Decision

**Router nhận ra ý định Routine và trả `disposition="routine"`; một node riêng phân giải
tên rồi gọi thẳng service của BE trong cùng tiến trình.**

1. **Disposition mới, không mượn `control`.** Routine có vòng đời riêng
   (`routine_executions`), có preview, hủy được giữa chừng. Ngoài ra `control` **bắt buộc**
   mang `candidate_plan`, mà router không dựng được: nó không biết Routine nào tồn tại.
2. **Gọi service, không gọi HTTP.** Agent và BE cùng chạy dưới `src/serve.py`; gọi
   `POST /routines/{id}/run` từ trong graph là tự gọi HTTP vào chính mình.
3. **Không dựng lại admission/safety/cancellation.** `bat_dau` đã có các cổng chạy trước
   khi tạo execution, `huy` idempotent (#297). Bản sao thứ hai là bản sẽ lệch.
4. **Phân giải tên ở node, không ở router.** Danh sách Routine là *trạng thái*;
   ADR-006/010 cấm router đọc trạng thái. Cùng chỗ đứng với `ghep_hoi_lai`, `loi_de_nghi`.
5. **Ba service tiêm vào node.** Không phải để test dễ, mà vì ranh giới sở hữu: chúng
   thuộc làn BE (#299: *"không tự hủy executor"*).

## Bốn lỗi chỉ lộ ra khi chạy thật — và vì sao suite không bắt được

`--mode multiturn` chấm ở mức `route_node`: nó đo router **nói** đúng, không đo xe **làm**
đúng. Nên suite 3209 xanh và cả ba bộ đo đạt trong khi xe vẫn sai.

| # | lỗi | vì sao nguy hiểm |
|---|---|---|
| 1 | `outcome="routine"` rơi vào câu mặc định của compose → *"Đã xử lý yêu cầu."* với `action_plan: null` | Trước đó xe nói *"không tìm thấy trong sổ tay"* — một **thất bại thành thật**. Bước giữa chừng còn tệ hơn chỗ xuất phát, và với `"Dừng lại"` là tài xế tin vừa dừng được một thứ đang chạy |
| 2 | Cổng phê duyệt HITL ở `turns.py` nuốt `"Dừng lại"` trước khi graph chạy | **Cùng lớp lỗi #196** đã sửa một lần cho `"dừng nhạc"`. Phép loại ở đó chỉ kể tên `"control"`, nên một disposition mới rơi thẳng vào bẫy |
| 3 | `route_node` không ghi hai khe Routine, và `user_id` **không được khai trong `AgentState`** nên LangGraph bỏ im lặng | Không lỗi, không log — chỉ một câu trả lời sai. Unit test xanh vì chúng tự đặt khoá |
| 4 | Không bắt `RoutineKhongChayDuocError` → 500 | **Ca thường gặp**: hai trong ba mẫu mặc định sinh ra ở trạng thái *"Cần thiết lập"* |

Sửa (2) **có điều kiện `pending is None`**, không tha vô điều kiện: đang chờ duyệt một lệnh
S2 mà tài xế nói *"dừng lại"* thì ý họ là **bác lệnh đó** — an toàn thắng. Hai chiều đều có
test ở `tests/test_api/test_approval_voice_intent.py`.

Nhánh fail-closed cũng được tách outcome riêng (`routine_loi_ngu_canh`): bản đầu mượn
`routine_khong_thay`, và câu *"Bạn chưa có Routine nào"* đã đánh lừa chính tác giả trong
lúc đo, khi UI đang hiện đủ ba mẫu. **Một lỗi lập trình phát ra câu của một trạng thái hợp
lệ thì không ai đi tìm nó.**

## Rủi ro nhận

`"dừng lại"` là cụm ngắn. Rủi ro nuốt nhầm được chặn bằng **hình dạng của mẫu**, không
bằng từ vựng: `_HUY` neo đầu câu và **đòi từ thứ hai**, vì đo được rằng `"dừng"` trơ đang
là cử chỉ **đuổi trợ lý** (`doc_tra_loi_co_khong("dừng") == "khong"`) — theo spec §3.3 là
cách *duy nhất* đóng chủ động một cửa sổ nghe tiếp. `"dừng nhạc"` cũng phải giữ nguyên là
lệnh `control`. Cả ba ca có test.

## Phương án đã bác

- **Gọi `POST /routines/{id}/run` từ trong graph** — tự gọi HTTP vào chính mình.
- **Mượn `disposition="control"`** — ép một thứ có vòng đời vào hợp đồng không có vòng đời,
  và vi phạm ràng buộc `candidate_plan`.
- **Dựng khe ngữ cảnh thứ ba cho câu đồng ý sau preview** — dùng lại `loi_de_nghi` (#367);
  hai đường xử lý cho cùng một tiếng "ừ" là cách để chúng lệch nhau.
- **Tha `routine` vô điều kiện ở cổng HITL** — xem bảng trên, mục (2).

## Đính chính 2026-08-31 — hàm "còn thiếu" vốn đã có

Bản đầu của ADR này (và của spec §4) khẳng định `dang_chay_cua_phien(session_id)` **chưa
tồn tại** ở làn BE, và `graph.py` cắm một stub `lambda _sid: None` vì thế. Sai.

`src/services/routine_execution.py` **đã có** `dang_chay_trong_phien(session_id)` với đúng
chữ ký cần, ngay dòng dưới `dang_chay_cua_routine`. Nó cũng **chưa có ai gọi** — cùng tình
trạng với `routines_intent` (#285) — nên nó không xuất hiện ở bất kỳ call site nào.

**Nguyên nhân sai:** tôi grep bằng cái tên tôi tự nghĩ ra (`dang_chay_cua_phien`) rồi kết
luận khái niệm ấy không có, thay vì tìm theo *việc nó làm*. Một lần grep trượt tên đã thành
một mục "chờ làn khác" trong ba tài liệu và một stub trả `None` vô điều kiện — tức **mọi
lượt hủy bằng giọng đều trả "Hiện không có Routine nào đang chạy." kể cả khi có**.

Đã nối vào (`dang_chay_cua_phien=dang_chay_trong_phien`) và bổ sung docstring + `__all__`
cho hàm ấy. Không còn phụ thuộc nào chờ làn BE.

**Tra theo phiên chứ không theo Routine là ràng buộc an toàn, không phải tiện tay:** tài xế
nói *"dừng lại"* mà không nêu tên, nên tra theo `routine_id` sẽ để một tiếng "dừng" ở phiên
B dừng chuỗi lệnh đang chạy ở phiên A — trên cùng chiếc xe. Có test khoá
(`test_phien_khac_khong_thay_lan_chay_cua_nguoi_ta`).

Một giới hạn thật, khác hẳn: **Routine toàn bước S1 chạy xong ngay trong `bat_dau`**, nên
không bao giờ có gì để hủy. Cái hủy được là lần chạy dừng ở `waiting_approval`. Đó là hành
vi đúng, nhưng nó có nghĩa là đường hủy chỉ quan sát được trên Routine có bước S2.


## Ngoài phạm vi

- `bo_buoc` (bỏ một bước trong preview): cần hợp đồng "chạy với tập bước con" mà BE chưa có.
- **#296** (eval barge-in): là **spike**, cần audio **người nói thật** từ FE spike #277.
  264 file WAV trong repo là Piper tổng hợp — không dùng được cho tuyên bố mà #296 đòi.
  Bốn ca âm tính của `routine-giong-noi` đã là nửa deliverable của nó.
- Đọc **từng bước** trong preview: hiện chỉ nói *"Đây là các bước…"*. Cần bộ mô tả bước
  bằng lời, đáng một task riêng có bộ đo riêng.

## Thu hồi

Bỏ một dòng `if outcome == "routine": return "routine"` trong `_route_after_routing`. Mọi
lượt Routine quay lại tra sổ tay như trước.

## Bằng chứng

- `POST /api/v1/turns/text` qua trình duyệt, 30/08 — bảng đối chiếu trước/giữa/sau trong
  thân commit `029be87`.
- `eval/datasets/agent/multiturn-v1`: `routine-giong-noi` **4/10 → 10/10**, `DI LUI=0`.
- `--mode bao-loi` `DI LUI=0`; `--mode intent` `1.0000`.
- Suite `3244 passed, 21 skipped`.

# Điều tra buổi test 20–21/08 — 13 lỗi, 2 nguyên nhân gốc

> **Status: đã dựng lại trên máy dev 2026-08-21**, `.venv` = Python 3.11.9, nhánh `develop`.
> Mọi dòng "dựng lại được" bên dưới là **output thật** của `DeterministicControlRouter`
> và `materialize_action_plan` chạy trực tiếp, không phải suy từ đọc code.
>
> **Nguồn:** 121 tin nhắn Discord từ 00:00 ngày 20/08 đến 09:01 ngày 21/08
> (`docs/2108/…Thảo luận….txt`), 16 ảnh chụp màn IVI + 2 ảnh Google Maps đối chiếu,
> và `docs/kich_ban_test_ghep_lenh.xlsx` (78 kịch bản, 14 hàng đã điền cột "NGHE/THẤY THẬT").
> Người test: @sonrapper, 23:20 ngày 20/08 → 01:14 ngày 21/08. Người báo lỗi bản đồ: @giap_18554.
>
> **Điều kiện chạy lúc test:** SLM **bật** (`Qwen2.5-3B · offline` ở góc phải mọi ảnh),
> tốc độ mô phỏng **0 km/h · P** suốt buổi. Cả hai đều quan trọng — xem §0 và BUG-01.

## Kết luận một dòng

Hai nguyên nhân gốc sinh ra gần như toàn bộ danh sách: **(A)** router coi cả câu nói là
**một** lệnh duy nhất — nó không hề tách vế, nên động từ, con số và đối tượng của hai vế
trộn vào nhau; **(B)** nhánh phê duyệt dựng lại kế hoạch **thiếu một tham số**, khiến mọi
phê duyệt do SLM đề xuất chắc chắn thất bại với câu *"Xe không còn ở trạng thái an toàn"*.
(B) sửa bằng **một dòng**. (A) là thay đổi thiết kế.

## Xếp hạng và tiến độ

> **Cập nhật 21/08 chiều.** Cột "Tiến độ" là thứ trôi nhanh nhất trong tài liệu này —
> đọc kèm `gh pr list --state open`, đừng tin một mình nó.

| # | Lỗi | Mức | Tiến độ |
|---|---|---|---|
| BUG-01 | Phê duyệt đường SLM **luôn** thất bại, báo sai là lỗi an toàn | **P0** | ✅ **PR #222** — chờ merge, CI xanh |
| BUG-02 | Ghép lệnh làm **ngược lại** điều được nói, rồi báo "Đã thực hiện" | **P0** | ✅ **PR #225** — chờ merge, CI xanh |
| BUG-03 | Số của vế này đọc thành số của vế kia → từ chối sai | **P0** | ✅ **PR #225** |
| BUG-04 | Chéo domain bất khả thi: 0/78 kịch bản chạy được 2 domain | **P0** | ✅ **PR #225** — nay 28/78 |
| BUG-05 | Câu không mở đầu bằng động từ lệnh → rơi xuống tra sổ tay | **P1** | ⚠️ **PR #227, một nửa** — xem §BUG-05 |
| BUG-06 | Một vế sai làm hỏng cả lượt (từ chối tất-cả-hoặc-không) | **P1** | ⏸ **Chặn** — cần `compose.py`+`route.py`+`state.py`, đúng ba file PR #217 đang sửa |
| BUG-07 | Không đặt được âm lượng/quạt về **0** bằng giọng nói | **P1** | ✅ **PR #227** |
| BUG-08 | Câu hỏi lại chung chung, không nêu đang phân vân gì | **P2** | ✅ **Nhân đã sửa** — PR #217, đủ cả sáu `missing_*` |
| BUG-09 | `"dẫn tôi tới"`, `"tắt chỉ đường"` không khớp | **P2** | ✅ **PR #227** |
| BUG-10 | Bản đồ: đường chim bay + nút "Bắt đầu" chết | **P2** | ✅ **Giáp — PR #224** (OSRM thật + animation); phần còn lại ở issue #226 |
| BUG-11 | Không có ngữ cảnh hội thoại giữa hai lượt | **P1** | ✅ **Nhân — PR #217** (issue #148) |
| BUG-12 | STT nghe sai nặng ở câu dài / số đếm | **P1** | ❌ Chưa ai nhận. Ngoài code router |
| BUG-13 | VAD tự dừng sau 900 ms → không kịp huỷ mic | **P2** | ⏸ Chờ **PR #219** merge (cùng `DriverShellProvider.tsx`) |

**Bốn lỗi P0 đều đã có bản vá chờ merge.** Thứ tự merge đề nghị: #222 (P0, độc lập) →
#225 → #227 (dựa trên #225) → #217/#219/#221 của Nhân → #224 của Giáp.

### Còn hở, không nằm trong PR nào

| Việc | Vì sao chưa làm |
|---|---|
| **BUG-05 nửa sau** — câu mở đầu bằng **danh từ** (`"điều hòa 24 độ và quạt gió mức 3"`) | Phải tự bịa động từ người dùng không nói → đụng mặc định ADR-011. Cần ADR + vòng đo, không phải một dòng regex. Đã khoá bằng test |
| **Nhóm "Lệnh + câu hỏi"** (VT-P40…P43) | `is_information_question` chạy **trước** mọi matcher nên nuốt cả lượt. Lỗi khác BUG-05, chưa có issue |
| **BUG-06** | Xem trên — chặn bởi PR #217 |

Đo lại trên cả 78 kịch bản của `docs/kich_ban_test_ghep_lenh.xlsx` sau #225 + #227:

| | đầu buổi test | nay |
|---|---|---|
| Kịch bản sinh bước ở ≥ 2 domain | **0** | **28** |
| Kịch bản có số việc ≥ số ý người nói | **10** | **44** |
| Hàng bỏ ý trong im lặng (cột J) | **43** | **11** |
| Hàng còn rơi xuống tra sổ tay | 25 | **8** (4 danh-từ-đầu-câu + 4 lệnh-kèm-câu-hỏi) |

---

## §0. Ba điều phải nói trước, nếu không cả báo cáo đọc sai

**1. Bảng Excel đo router THUẦN; Sơn test với SLM BẬT.** `scripts/sinh_bang_ghep_lenh.py:148`
chỉ gọi `DeterministicControlRouter().route(...)` — không policy, không SLM, không executor.
Nên cột F ("Router đo được") và cột K ("NGHE/THẤY THẬT") **không đo cùng một hệ thống**.
Ví dụ rõ nhất: `"Dẫn tôi tới quán cà phê gần nhất"` — router thuần trả `not_control`, nhưng
màn hình Sơn (ảnh 00:09) hiện *"Bạn muốn điều chỉnh cụ thể như thế nào?"*, tức SLM đã xen vào
và đổi kết quả. Hai cột lệch nhau **không phải lúc nào cũng là bug**; đôi khi chỉ là hai cấu hình.

**2. Chính script sinh bảng đang dính lại lỗi mà issue #171 đã đóng.** Dòng 148 dựng router
**không truyền `poi_fixture`**, nên `_poi_ids` rỗng và guard `poi_not_in_fixture` không chạy —
đúng cái bug `graph.py:305` từng có. Sáu hàng điều hướng trong bảng vì thế chưa đáng tin.
Sửa trước khi sinh lại bảng.

**3. Cột J ("Ý bị bỏ im lặng?") đếm số bước, nên bị đánh lừa.** VT-P51
`"Mở tất cả cửa và mở tất cả cửa sổ 50 phần trăm"` ghi **"không"** vì router ra 4 bước ≥ 2 ý.
Thực tế: 4 bước đó **toàn là cửa sổ**, còn cả 4 cửa bị bỏ. Một vế nở ra nhiều bước sẽ che mất
vế kia biến mất. Đừng tin cột J khi câu có `"tất cả"`.

---

## BUG-01 — Phê duyệt đường SLM luôn thất bại, và báo sai lý do ⛔ P0

**Sơn, 21/08 00:07:** *"nói tắt âm lượng thì hệ thống sẽ hiển thị hỏi mình muốn đặt âm lượng
về 0 ko, mình NÓI đồng ý, hệ thống bảo (Xe ở trạng thái ko an toàn) — bug nghiêm trọng đấy."*
Kèm 00:08: *"Tốc độ mô phỏng của anh xe lúc này vẫn là 0 nhé."*

**Không phải cảm giác — nó xảy ra 100% số lần, không liên quan gì tới trạng thái xe.**

Ba dòng code, ba chỗ khác nhau:

```python
# src/agents/policy.py:142  — nguồn gốc SLM tự nó đã bắt phải hỏi duyệt (issue #144)
requires_approval = any(step.safety_level == "S2" for step in steps) or route_source == "slm"

# src/agents/nodes/safety.py:29  — lúc LẬP kế hoạch: truyền đúng nguồn gốc
route_source=state.get("route_source", "deterministic"),

# src/agents/nodes/approval.py:168 — lúc DUYỆT LẠI: KHÔNG truyền, nên rơi về "deterministic"
recomputed = materialize_action_plan(
    as_candidate_plan(state["candidate_action_plan"]),
    snapshot_dict(live), plan.session_id, plan.vehicle_id,
)
if plan_digest(recomputed) != fresh.plan_digest:
    return {"outcome": "approval_predicate_failed"}
```

`requires_approval` là một trường của `ActionPlan`, mà `plan_digest` băm **toàn bộ**
`model_dump()`. Nên trên đường SLM, kế hoạch dựng lại lúc duyệt luôn khác kế hoạch gốc **đúng
một trường** — và người dùng nghe câu ở `compose.py:95`:
*"Xe không còn ở trạng thái an toàn cho lệnh này nữa."*

Dựng lại được, xe đứng yên, 0 km/h, gear P:

```
[S1 qua SLM] media_control
   lập kế hoạch (slm)  : requires_approval=True  safety=S1
   duyệt lại (mặc định): requires_approval=False safety=S1
   digest khớp = False  -> approval_predicate_failed
   khác ở: {"requires_approval": [true, false]}

[S2 qua SLM] set_window_position
   digest khớp = True
```

**Vì sao S2 thoát:** cả hai phía đều tính ra `requires_approval=True` (do có bước S2), nên digest
trùng. Lỗi vì thế trúng **đúng** vào cổng mà issue #144 dựng lên — cổng chặn kế hoạch SLM
"hợp schema nhưng sai ý". **Cổng đó hiện không thể vượt qua.** Đúng ca `media_control set_volume`
của Sơn: S1, do SLM đề xuất, bị gate, và duyệt thì luôn hỏng.

**Vì sao test xanh:** `route_source="slm"` chỉ xuất hiện ở `tests/test_agents/test_policy.py`
(4 chỗ, đều là unit test của `materialize`). **Không một test nào** chạy chuỗi
*SLM đề xuất → interrupt → duyệt → resume*. Điểm mù khớp chính xác với lỗi.

**Sửa:** truyền `route_source` ở `approval.py:168`, dùng đúng biểu thức `safety.py:29` đang dùng.
Kèm một test đi hết chuỗi resume trên đường SLM, nếu không nó sẽ quay lại.

> Ghi chú cho @sonrapper: câu *"Xe không còn ở trạng thái an toàn"* còn dùng cho một tình huống
> thật (xe lăn bánh trong lúc chờ duyệt, S2 hoá S3). Sau khi sửa BUG-01, nếu vẫn gặp câu này thì
> **lấy `trace_id` ở màn /engineer** — có ba đường dẫn tới nó và chỉ trace mới phân biệt được.

### Toàn bộ quan sát về HITL trong buổi test, và cái nào mới là bug

Sơn đặt tên video thứ hai là *"Test 2 (HITL ko ổn lắm)"*, nên gom hết vào một chỗ cho khỏi lẫn:

| Quan sát | Lúc | Phán quyết |
|---|---|---|
| Đồng ý → *"Xe ở trạng thái ko an toàn"*, xe đứng yên | 00:07 | **BUG-01. Bug thật, P0.** |
| *"nói dối xe ko an toàn trong khi xe ko di chuyển"* (video 1) | 23:44 | **Cùng BUG-01.** |
| *"mở hết cửa thì HITL lại được"* | 00:38 | **Đúng — và đây là bằng chứng cho chẩn đoán.** Cửa là S2 nên `requires_approval` khớp cả hai phía, digest trùng, duyệt chạy. Chỉ nhánh S0/S1-qua-SLM mới chết. |
| Hộp thoại đọc *"mở cửa trước bên lái rồi mở…"* khi đã nói "đóng" | 01:11 | **Không phải lỗi HITL** — HITL nêu đúng cái nó nhận được. Lỗi ở BUG-02, trên router. |
| *"Đang có một lệnh chờ bạn xác nhận; xong lệnh đó rồi tôi làm tiếp"* | 01:06 | **Không phải bug.** Đúng bất biến "tối đa một pending mỗi session" (`approval.py:5`, partial unique index ở DB). Đang có hộp thoại chưa trả lời thì lượt mới bị chặn — thiết kế. |
| Nói *"đồng ý"* bằng giọng được nhận | 01:13 | **Chạy đúng** (`approval.intent.detected`, issue #191/#207). |

**Một thứ tôi tưởng là bug thứ hai, và không phải.** Bản đầu của báo cáo này viết rằng nhánh
`approval_predicate_failed` không gọi `store.consume()` nên bản ghi nằm lại ở `approved` — "rác
trong bảng, làm nhiễu metrics". Kiểm lại thì **sai cả ba vế**, và tôi giữ đoạn này để không ai đi
sửa nhầm:

- **Có chủ đích và đã ghi rõ.** `approval.py:7-9`: *"Cả bốn đường hỏng đều đi `compose` với zero
  side effect và **không** consume approval, đúng `safety_and_hitl.md` mục Decision flow."*
  `consume()` nghĩa là "đã dùng"; một lượt bị chặn thì chưa dùng gì, đánh dấu `consumed` mới là
  nói dối trong dữ liệu.
- **Không rò rỉ.** `_evict_locked` xoá mọi bản ghi `status != 'pending'` khi vượt trần, và
  `forget_session()` xoá theo phiên.
- **Không nhiễu metrics.** `/metrics/summary` là một phép fold trên `TraceStore`, không đọc bảng
  `approvals`; `metrics.py:223 approvals_required` đếm từ sự kiện trace.

Cũng không có lỗ hổng an toàn: bản ghi kẹt ở `approved` muốn chạy lại phải khớp đồng thời
`session_id` + `turn_id` + digest + `live.state_version == approved_vehicle_state_version`, mà
`state_version` chỉ tăng và không bao giờ quay lại — nên một khi trạng thái xe đổi, nó vĩnh viễn
không qua cửa được nữa.

**Trả lời gọn:** HITL có **đúng một** bug thật, và nó chính là BUG-01 — thứ đứng đầu bảng xếp hạng.
Ba quan sát còn lại của Sơn hoặc là triệu chứng của lỗi router, hoặc là hành vi đúng thiết kế.

---

## BUG-02 — Ghép lệnh làm NGƯỢC LẠI điều được nói, rồi báo "Đã thực hiện" ⛔ P0

Đây là hệ quả nặng nhất của nguyên nhân gốc (A). Router đọc động từ bằng
`_starts_with_command(text, ...)` — tức xét **chữ đầu của cả câu** — rồi áp động từ đó lên
đối tượng nó tìm thấy, kể cả đối tượng nằm ở vế có động từ ngược nghĩa.

Hai ca đã dựng lại được, cả hai đều có ảnh của Sơn:

```
'Bật đèn chiếu gần và tắt điều hòa'
   -> control | set_hvac_power{'enabled': True}          ← nói TẮT, máy BẬT
'Mở cốp xe và đóng tất cả các cửa'
   -> control | set_door_state{front_left,  'open'} ; set_door_state{front_right, 'open'}
              ; set_door_state{rear_left,   'open'} ; set_door_state{rear_right,  'open'}
                                                        ← nói ĐÓNG, máy MỞ cả 4 cửa
```

Đối chứng, từng câu một thì **đúng hết**:

```
'Đóng tất cả các cửa'  -> 4 × set_door_state{'state': 'closed'}   ✔
'Mở tất cả các cửa'    -> 4 × set_door_state{'state': 'open'}     ✔
```

Lỗi **chỉ sinh ra khi ghép**. Và nó im lặng: ảnh 23:55 của Sơn cho thấy màn hình trả
*"Đã thực hiện lệnh trên xe mô phỏng."* trong khi đèn pha vẫn ở **chiếu xa** và điều hoà vẫn bật —
tức vế đèn bị bỏ, vế điều hoà bị làm ngược, và câu trả lời nói là xong.

Ca thứ hai nguy hiểm hơn hẳn: `set_door_state` là **cửa vật lý**, S2 (S3 nếu xe đang chạy).
Ảnh 01:11 cho thấy hộp thoại HITL đọc đúng cái ngược đó ra thành lời — *"mở cửa trước bên lái
rồi mở cửa trước bên phụ rồi mở cửa sau bên trái rồi mở cửa sau bên phải?"* — nên tầng HITL **có**
làm đúng việc của nó (nêu rõ trước khi làm). Nhưng nếu tài xế bấm Đồng ý theo phản xạ, xe mở
bốn cửa khi người ta vừa bảo đóng.

---

## BUG-03 — Số của vế này bị đọc thành số của vế kia ⛔ P0

Cùng nguyên nhân (A), khác trường. `_number(text)` quét **cả câu** rồi lấy số đầu tiên tìm được.

```
'Bật điều hòa 22 độ, quạt gió mức 2 và phát nhạc'
   -> denied / fan_level_out_of_range          ← mức 2 nằm trong 0..3, hoàn toàn hợp lệ
'Bật sưởi ghế lái mức 2 và bật điều hòa 22 độ'
   -> denied / temperature_out_of_range        ← 22 độ nằm trong 16..30, hoàn toàn hợp lệ
```

Ca 1 chính là ảnh 00:39 của Sơn (*"3 câu lệnh cùng lúc có vẻ cũng hơi khê"*): màn hình đọc
*"BẬT ĐIỀU HÒA HAI MƯƠI HAI ĐỘ BẬT QUẠT GIÓ MỨC HAI VÀ BẬT NHẠC"* rồi trả lời
*"Quạt gió chỉ đặt được từ mức 0 đến 3."* Câu từ chối **nói sai sự thật về chính câu vừa nghe** —
tài xế không có cách nào đoán ra vấn đề thật.

Biến thể thứ ba, ghép nửa vế này với nửa vế kia thành một lệnh không ai nói ra:

```
'Mở cửa sổ bên phụ năm mươi phần trăm và mở cửa sổ bên lái hai mươi phần trăm'
   -> set_window_position{'window': 'front_left', 'percent': 50}
```

`front_left` lấy từ **vế 2**, `50` lấy từ **vế 1**. Không vế nào yêu cầu "bên lái 50%".

Và biến thể thứ tư, tệ nhất trong cả bảng — **con số của domain này biến thành đơn vị của domain
kia** (VT-P17):

```
'Bật điều hòa và mở cửa sổ bên lái 30 phần trăm'
   -> set_hvac_power{'enabled': True} ; set_hvac_temperature{'temperature_c': 30}
```

`"30 phần trăm"` của **cửa sổ** bị đọc thành **30 độ C** của điều hoà. Kính không nhúc nhích,
điều hoà bị vặn lên 30 độ — một việc không ai yêu cầu. Cột J của bảng ghi hàng này là
**"không"** (2 bước ≥ 2 ý), tức bảng đang chấm *đạt* cho một lượt không làm đúng một ý nào cả.
VT-P13 (`"Bật điều hòa 24 độ và bật đèn trần"`) cùng dạng: 2 bước, cột J ghi "không",
nhưng cả 2 bước đều là điều hoà và đèn trần bị bỏ.

---

## BUG-04 — Hai lệnh khác domain trong một câu: KHÔNG BAO GIỜ chạy được cả hai ⛔ P0

Đây không phải "hay hỏng" hay "hỏng tuỳ câu". Tôi cho cả 78 kịch bản trong bảng chạy qua router
rồi đếm số **domain** trong tập bước sinh ra:

```
Tổng 78 kịch bản ghép lệnh
Số kịch bản router sinh bước ở >= 2 domain: 0
```

**0/78.** Riêng nhóm *"2. Chéo domain, 2 ý"* — nhóm lớn nhất bảng, 18 hàng — kết quả là
**15 hàng chạy đúng 1 domain, 3 hàng không chạy gì**. Không có hàng nào ra 2 domain.

Và nó **bất khả thi về mặt cấu trúc**, không phải thiếu luật. `router.py:435 _run_matchers`:

```python
for matcher in (self._match_hvac, self._match_open_app, self._match_music,
                self._match_window, self._match_seat, self._match_door,
                self._match_trunk, self._match_lights, self._match_navigation):
    result = matcher(text)
    if result is not None:
        return ...        # ← THOÁT NGAY. Các matcher sau không bao giờ được chạy.
```

Một lượt = một matcher = một domain. Mọi domain khác trong câu bị bỏ **trước khi có ai nhìn tới**.
Thêm luật, thêm từ đồng nghĩa, sửa liên từ — không cái nào chạm được vào vòng lặp này.

Hệ quả thứ hai: thứ tự thắng là **thứ tự trong danh sách matcher**, không phải thứ tự trong câu.
Nói cái gì trước không quyết định được cái gì chạy:

| Câu nói | Chạy | Bị bỏ |
|---|---|---|
| `Bật điều hòa và mở nhạc` | điều hoà | nhạc |
| `Mở nhạc và bật điều hòa` | nhạc | điều hoà |
| `Bật đèn trần và bật điều hòa 24 độ` | **điều hoà** | đèn trần |
| `Bật điều hòa 24 độ và bật đèn trần` | **điều hoà** | đèn trần |
| `Dẫn đường đến trạm sạc và phát nhạc` | dẫn đường | nhạc |
| `Phát nhạc và dẫn đường đến trạm sạc` | nhạc | dẫn đường |
| `Mở cửa bên lái và mở cốp sau` | cửa | cốp |
| `Mở cốp sau và mở cửa bên lái` | **cửa** | cốp |

Hai cặp in đậm là chỗ nhìn rõ nhất: đảo thứ tự câu **không** đổi kết quả, vì `hvac` và `door`
luôn đứng trước `lights`/`trunk` trong danh sách. Sơn ghi cột K cho hàng
`Bật đèn trần và bật điều hòa 24 độ`: *"ko hoạt động"* — đúng, vì anh nhìn cái đèn.

Tổng hợp cột J của cả bảng:

| Kết quả | Số hàng |
|---|---|
| **CÓ** — chạy ít bước hơn số ý, phần còn lại biến mất không nói gì | **43** |
| **CẢ LƯỢT** — không ý nào chạy | **25** |
| **không** — số bước khớp số ý | **10** |

Tức **10/78 (12,8%)** giữ được đủ *số bước* — nhưng như §0 mục 3 và VT-P13/VT-P17 dưới đây cho
thấy, ngay cả 10 hàng đó cũng không có nghĩa là đủ *ý*. Cột J đếm bước, không đếm domain.

---

## BUG-05 — Câu không mở đầu bằng động từ lệnh thì rơi xuống tra sổ tay 🟠 P1

> ⚠️ **Sửa được một nửa** (PR #227). Mục này gộp **hai** lỗi khác nhau:
>
> - **Có động từ, bị tiền tố che** (`"Bạn bật…"`, `"Vừa bật… vừa…"`, wake word `"VIVI bật…"`)
>   — đã cắt tiền tố, chạy được. An toàn tuyệt đối: câu lệnh nằm nguyên vẹn, chỉ bị một chữ
>   vô thưởng vô phạt đứng chắn.
> - **Không có động từ ở đâu cả** (`"Điều hòa 24 độ và quạt gió mức 3"`) — **chưa sửa**. Sửa là
>   phải tự bịa một động từ người dùng không nói, tức đụng thẳng mặc định ADR-011. Câu hỏi
>   nguy hiểm: `"điều hòa"` một mình là **câu hỏi** hay **lệnh bật**? Đoán sai là biến một câu
>   hỏi thành hành động vật lý. Đã khoá hành vi hiện tại bằng test.
>
> Còn **4 hàng** trong bảng 78 kịch bản thuộc nửa chưa sửa (VT-P02, P04, P05, P67).

**Đây là chỗ bảng Excel quy sai nguyên nhân, nên phải nói rõ.** Nhóm *"9. Liên từ lạ"* và
*"10. Lịch sự / dài dòng"* đổ lỗi cho liên từ. Không phải. Dựng lại, đổi **đúng một biến**:

```
'Bật điều hòa 24 độ và quạt gió mức 3'    -> control ✔  (3 bước đủ)
'Bật điều hòa 24 độ với quạt gió mức 3'   -> control ✔
'Bật điều hòa 24 độ cùng quạt gió mức 3'  -> control ✔
'Bật điều hòa 24 độ rồi quạt gió mức 3'   -> control ✔
'Điều hòa 24 độ và quạt gió mức 3'        -> not_control ✘   ← chỉ bỏ chữ "Bật"
```

Bốn liên từ `và / với / cùng / rồi` **đều chạy được**. Thứ duy nhất làm hỏng là **thiếu động từ
lệnh ở đầu câu**. Điều đó giải thích luôn cả nhóm "lịch sự":

- `"Vừa bật điều hòa vừa mở nhạc"` — mở đầu bằng *"Vừa"*
- `"Bạn bật điều hòa 22 độ rồi mở nhạc lên nhé"` — mở đầu bằng *"Bạn"*
- `"Cho tôi xin điều hòa 22 độ và nhạc"` — mở đầu bằng *"Cho"*
- `"Quạt gió mức 2 và điều hòa 22 độ"` — mở đầu bằng danh từ

Cả bốn đều `not_control` vì **cùng một lý do**, không phải bốn lý do. Sơn ghi cột K cho hàng đầu:
*"lệnh ko hoạt động, nó lại tra lệnh RAG"* — đúng, và đây là vì sao.

---

## BUG-06 — Một vế sai làm hỏng cả lượt 🟠 P1

```
'Bật điều hòa 22 độ và quạt gió mức 9'  -> denied / fan_level_out_of_range   (22 độ KHÔNG chạy)
'Bật điều hòa 45 độ và quạt gió mức 2'  -> denied / temperature_out_of_range (quạt KHÔNG chạy)
```

Sơn ghi: *"từ chối đúng, nhưng vế trước ko chạy"* và *"từ chối đúng, nhưng vế sau ko chạy"*.
Ảnh 23:50 là ca thứ hai ở dạng khác: *"BẬT ĐIỀU HÒA MƯỜI BẢY ĐỘ VÀ ĐỂ QUẠT GIÓ MỨC SÁU"* →
*"Quạt gió chỉ đặt được từ mức 0 đến 3."*, nhiệt độ vẫn đứng ở 24°.

Từ chối **đúng** vế sai là hành vi đúng. Vứt luôn vế hợp lệ thì không.

---

## BUG-07 — Không đặt được về mức 0 bằng giọng nói 🟠 P1

```
'Đặt âm lượng mức 0'      -> control | media_control{'action':'set_volume','volume':0}  ✔
'Đặt âm lượng mức không'  -> clarify / missing_volume                                   ✘
'Đặt âm lượng bằng không' -> clarify / missing_volume                                   ✘
'Tắt âm lượng'            -> not_control / default_to_manual                            ✘
```

Nguyên nhân ở `router.py:_words_to_number`: nó **cắt bỏ `"không"` ở cuối câu** vì đó thường là
tiểu từ nghi vấn (*"Mở cửa sổ bên lái được không?"* mà đọc ra 0 thì sẽ đi **đóng** kính — comment
trong code ghi rõ, và đó là một lo ngại chính đáng).

Nhưng hệ quả: **STT luôn viết số 0 nói ra thành chữ `"không"`**, nên đường thoại không bao giờ
đặt được âm lượng hay quạt về 0. Chỉ gõ chữ mới được. Sơn gặp đúng chuỗi này:
`"tắt âm lượng"` → hệ thống hỏi lại → `"đồng ý"` → BUG-01.

Hướng sửa gợi ý: chỉ cắt `"không"` cuối câu khi nó **không** đứng ngay sau `mức` / `về` / `bằng`,
hoặc khi câu đã được nhận là dạng nghi vấn. Hai điều kiện đó phân biệt được hai nghĩa.

---

## BUG-08 — Câu hỏi lại chung chung ở đúng chỗ cần cụ thể 🟡 P2

> ✅ **@HVNhan-Relieq đã sửa** trên nhánh `feat/issue-148-nho-ngu-canh-hoi-lai` (PR #217, chưa
> merge): thêm đủ cả sáu `missing_*` còn thiếu và viết lại theo mẫu ba-thành-phần *chưa làm gì /
> thiếu cái gì / đáp thế nào*. Đoạn mô tả dưới đây là **hiện trạng `develop` lúc điều tra**.

`compose.py:CLARIFY_MESSAGES` có câu riêng cho `missing_light_target`, `missing_fan_level`,
`missing_temperature`, `relative_change_unsupported`. **Không có** cho `missing_volume`,
`missing_window_side`, `missing_seat_side`, và nhánh điều hướng. Tất cả rơi về câu chung
*"Bạn muốn điều chỉnh cụ thể như thế nào?"* — Sơn nhận đúng câu này **3 lần trong 40 phút**,
cho ba tình huống chẳng liên quan gì nhau (ảnh 00:06, 00:09, 00:33). Không lần nào câu đó nói
được hệ thống đang phân vân giữa hai cái gì.

---

## BUG-09 — Điều hướng: hai cách nói không khớp, nhưng huỷ dẫn đường THÌ CÓ 🟡 P2

```
'Dẫn đường đến quán cà phê gần nhất' -> control | set_navigation{'start','poi-cafe-01'}  ✔
'Dẫn tôi tới quán cà phê gần nhất'   -> not_control / default_to_manual                  ✘
'Hủy dẫn đường'                      -> control | set_navigation{'operation':'cancel'}   ✔
'Tắt chỉ đường'                      -> not_control / default_to_manual                  ✘
```

**Sửa lại một nhận định:** Sơn viết *"ko có cái tính năng tắt chỉ đường đi"* (00:11). Tính năng
**có**, chỉ là cách nói khác. `"Hủy dẫn đường"` chạy được ngay hôm nay. Issue #171 đã thêm
`tìm đường`, `đưa tôi tới`, `đi tới` — nhưng bỏ sót `dẫn tôi tới`, đúng cách nói tự nhiên nhất.

---

## BUG-10 — Bản đồ: bảy hạn chế, xếp theo mức độ 🟡 P2

> ✅ **@nguyenGiaps đã sửa A1 + A3 + A4** trên PR #224: tuyến OSRM thật vào cả hai `poi.json`,
> nút "Bắt đầu" chạy animation trình diễn, kèm dòng đính chính trong `docs/demo_runbook.md`.
> A2/A5/A6/A7 còn lại nằm ở **issue #226**.

Bốn cái đầu đã đo và đề xuất cách sửa trong báo cáo riêng
**[ban-do-nut-bat-dau-va-lo-trinh-2026-08-21.md](ban-do-nut-bat-dau-va-lo-trinh-2026-08-21.md)**;
ba cái sau là mới, tìm ra trong buổi test này.

| # | Hạn chế | Bằng chứng |
|---|---|---|
| 1 | **Lộ trình là đường chim bay.** Polyline viết tay 3–4 điểm, góc bẻ lớn nhất 3,9° — mắt không thấy là đường gấp | ảnh 23:20 của Sơn; đo 6 POI |
| 2 | **Nút "Bắt đầu" không có `onClick`** — và ở hợp đồng xe hiện tại cũng không có việc gì để làm, vì `navigation.status` đã `active` từ lúc câu lệnh chạy | Giáp 23:52 + `MapView.tsx:77-82` |
| 3 | **`distance_km` in trên màn hình lệch tới +65%** so với đường đang vẽ | poi-fun-01: vẽ 0,91 km, ghi 1,50 km |
| 4 | **Chấm xe nhảy 4,63 km** khi bắt đầu dẫn đường (`IDLE_POSITION` ≠ điểm đầu polyline) | `LeafletMap.tsx:37` |
| 5 | **"Gần nhất" không phải tìm gần nhất.** `search_nearby_poi` chỉ là một dòng trong registry — `execute.py:50` ghi thẳng *"hàm này không làm `search_nearby_poi` sống lại"*. `"quán cà phê gần nhất"` chỉ là khớp alias vào một POI cứng, không đọc vị trí xe | ảnh 23:19, 00:09 |
| 6 | **Không có nút huỷ dẫn đường trên màn hình.** `MapView.tsx` không có một chỗ nào gọi cancel — chỉ đường thoại `"Hủy dẫn đường"` mới thoát được | Sơn 00:11–00:12 |
| 7 | **Ô tìm kiếm là chữ tĩnh**, không gõ được, không tìm được — nó chỉ in lại tên POI đang dẫn | ảnh 23:19 |

Hai chỗ cần nói lại cho đúng, vì Sơn ghi là bug nhưng không phải:

- *"refresh tab cũng ko mất trạng thái này"* (00:12) — **đúng như thiết kế.** Trạng thái dẫn đường
  sống ở vehicle simulator, không ở tab trình duyệt. Xe **thật sự** đang được dẫn đường; F5 mà mất
  mới là sai. Thứ thiếu là hạn chế #6: không có nút để huỷ.
- *"ko có cái tính năng tắt chỉ đường đi"* — xem BUG-09: `"Hủy dẫn đường"` chạy được hôm nay.

Ưu tiên nội bộ nhóm bản đồ: **#2 và #6 trước** (rẻ, và là thứ Giáp đang vướng), rồi **#1 + #3**
(cùng một lần sửa fixture), rồi #4. #5 và #7 là mở rộng phạm vi — đừng đụng trước Demo Day.

---

## BUG-11 — Không có ngữ cảnh giữa hai lượt 🟠 P1

> ✅ **@HVNhan-Relieq đã sửa** — PR #217 (`src/agents/ghep_hoi_lai.py` + ADR-025).

**Sơn, 23:37–23:38:** *"bật quạt gió → nó hỏi mức mấy → mình nói ba → thì con VIVI đ có cái lưu
context nên ko dùng được."*

Dựng lại: `'Bật quạt gió'` → `clarify / missing_fan_level`, và lượt sau `'Quạt gió mức ba'` →
`not_control` (BUG-05: không có động từ đầu câu). Nên **câu hỏi lại là ngõ cụt hai lần**: hỏi xong
không nhớ đã hỏi gì, mà câu trả lời tự nhiên của người ta cũng không khớp luật.

Đây là **issue #148 đang mở**, @hvnhan_relieq đã nhận (20/08 15:47). Không mở issue mới.

---

## BUG-12 — STT nghe sai nặng ở câu dài và số đếm 🟠 P1

Chép đúng từ ảnh:

| Sơn nói | Máy nghe |
|---|---|
| bật điều hòa 24 độ và quạt gió mức 1 | `MẶT ĐIỀU HÒA BỐN ĐỘ VÀ QUẠT GIÓ MỨC MỘT` |
| …cửa sổ bên lái… | `…CỬA SỔ BỂ LÁI…` |
| đặt âm lượng mức 0 | `CÁC TRƯỞNG PHÓ BÍ THƯ` |

Ca thứ ba đáng chú ý không chỉ vì nó sai, mà vì **SLM trả lời tử tế cho câu sai đó** — nguyên văn
*"Tôi hiểu bạn muốn nói về các trưởng phó bí thư của Đảng, nhưng tôi không thể giúp bạn với điều
này…"* và đọc thành tiếng. Một câu lệnh điều khiển xe biến thành một đoạn hội thoại chính trị.
Sơn nói rõ điều kiện đo: *"anh nói rõ, không có mic nhưng không có âm thanh ồn"* (23:48).

Chưa có số WER người thật cho mấy ca này. Nếu định đưa vào demo thì **đo trước**, đừng đoán.

---

## BUG-13 — Không kịp huỷ mic 🟡 P2

**Sơn, 23:46:** *"kiểu nói nhầm rồi hủy mic, nó vẫn gửi lệnh nói nhầm."*
**23:54:** *"thi thoảng ấn tắt bật mic nhanh quá hệ thống nó lại lưu bừa 1 kí tự rồi về trạng thái SLM."*

Đường huỷ **có** hoạt động: `closeVoice` gọi `recorder.cancel()` (vá ở PR #102). Vấn đề là
**không còn thời gian để bấm**: VAD tự dừng sau `SILENCE_DURATION_MS` = 900 ms im lặng kể từ khi
đã phát hiện có tiếng nói, và tự dừng nghĩa là `stopVoiceAndSend` — **gửi luôn**. Nói nhầm xong
im 0,9 giây là lượt đã bay lên backend trước khi tay chạm được vào nút.

Ca thứ hai là mặt trái của `hadSpeech()`: chạm mic nhanh, tiếng ồn vượt ngưỡng RMS 0,02, thế là
một đoạn rác được coi là "có tiếng nói" và vẫn gửi đi.

---

## Việc đề nghị làm, theo thứ tự

1. **BUG-01 ngay hôm nay.** Một dòng ở `approval.py:168` + một test đi hết chuỗi
   *SLM → interrupt → duyệt → resume*. Đây là thứ duy nhất trong danh sách **chặn demo**:
   với SLM bật, mọi lượt HITL do SLM đề xuất đều hỏng.
2. **BUG-02 trước BUG-03/04.** Cùng nguyên nhân gốc (A), nhưng BUG-02 làm **ngược** một lệnh
   cửa vật lý. Nếu chưa kịp tách vế cho tử tế thì trước mắt: phát hiện câu có **hai động từ lệnh
   trái nghĩa** và trả `clarify` thay vì đoán. Thà hỏi lại còn hơn mở bốn cửa khi người ta bảo đóng.
3. **Sửa `scripts/sinh_bang_ghep_lenh.py:148`** (truyền `poi_fixture`) rồi mới sinh lại bảng —
   nếu không sáu hàng điều hướng vẫn sai. Nhớ chép file đã điền ra chỗ khác trước, script **ghi đè**.
4. **BUG-05 rẻ và lời to.** Nới `_starts_with_command` để chấp nhận tiền tố lịch sự / danh từ đứng
   đầu là gỡ được cả nhóm 9, nhóm 10 và một phần nhóm 1 trong bảng — nhiều hàng, một chỗ sửa.
5. **BUG-07 và BUG-08** đều nhỏ và đều nằm ở chỗ tài xế cảm nhận trực tiếp.
6. **BUG-11** để nguyên trong issue #148, @hvnhan_relieq đang làm.

## Việc KHÔNG nên làm

Đừng mở 13 issue. **BUG-02, BUG-03, BUG-04** là **một** nguyên nhân — router không tách vế câu —
và tách riêng ra thì ba người sẽ vá ba chỗ khác nhau trong cùng một hàm. Gộp thành một issue
*"router phải tách vế trước khi đọc động từ và số"*, đính kèm ba đoạn dựng lại ở trên làm test case.

@thanhpro08 gợi ý (21/08 07:18) chuyển từ Discord sang Excel để dễ theo dõi — bảng đã có rồi và
đã đưa ra được 78 kịch bản. Thứ còn thiếu là **`trace_id`** (cột M): 14 hàng đã điền cột K nhưng
**không hàng nào có trace_id**, nên mọi kết luận về nguyên nhân đều phải dựng lại tay như báo cáo
này. Lần test sau, trượt hàng nào thì lấy trace ở màn `/engineer` bỏ vào cột M.

## Phạm vi báo cáo này không chạm tới

Chưa đo: WER người thật, độ trễ đầu-cuối, và **hành vi khi SLM tắt** (`slm_enabled` mặc định là
`False` ở `src/config.py:32`; buổi test này chạy với cờ bật). Ba lỗi P0 ở trên đều dựng lại được
mà không cần SLM chạy, **trừ BUG-01** — lỗi đó theo định nghĩa chỉ tồn tại trên đường SLM.

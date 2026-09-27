# Product Spec — Routines MVP (Voice-first personalization)

> **Status: Planned.** Có code khung từ 2026-08-28 (`src/agents/routines.py`,
> `src/agents/routines_intent.py`) nhưng **chưa nối vào turn pipeline hay API** — không route
> nào trong `src/api/`, không import nào trong `src/agents/graph.py`. Tài liệu này là
> **phạm vi cam kết**, không phải hiện trạng. Không nâng status khi chưa có evidence tại #279;
> xem `docs/release/routines-mvp-release-decision.md` (NO-GO) cho quyết định release hiện tại.

- Epic: [#270](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/270)
- Issue chủ quản của tài liệu này: [#280](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/280)
- Release gate: [#279](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/279) · traceability: [#300](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/300)
- Owner: PM/PO `thanhpro82`. BE `hason0510` · FE `danggiap123` · Agent `HVNhan-Relieq`.

## Tóm tắt một câu

Tài xế phải nói lại từng lệnh một cho những chuỗi hành động lặp đi lặp lại mỗi ngày;
Routines cho phép gói 1–4 hành động thuộc tập đóng thành một Routine của riêng mình,
gọi bằng giọng nói, chạy qua đúng lớp safety/HITL hiện có, và hủy được tại điểm dừng an toàn.

## Vấn đề và người dùng

Hệ thống hiện tại xử lý **một ý định mỗi lượt**. "Đi làm" trong đời thực là bốn lệnh rời rạc:
bật điều hòa, đặt nhiệt độ, bật nhạc, dẫn đường tới cơ quan. Bốn lượt thoại, bốn lần rời mắt
khỏi đường nếu một lượt nghe hụt.

| Người dùng | Nỗi đau hôm nay | Thành công trông như thế nào |
|---|---|---|
| Tài xế | Lặp lại cùng một chuỗi lệnh mỗi sáng, mỗi lượt là một cơ hội STT nghe sai | Nói một câu, xe làm cả chuỗi, và biết chắc nó sắp làm gì trước khi nó làm |
| Người đánh giá/demo | Demo trợ lý thường chỉ là lệnh đơn happy path | Thấy chuỗi nhiều bước có preview, có phê duyệt S2, có chặn S3, có hủy giữa chừng |

## Journey chính (voice-first)

1. **Tạo** — trên IVI, tài xế chọn một trong ba mẫu mặc định hoặc tạo từ đầu; chọn 1–4 hành động
   từ allowlist, đặt tên. Giao diện là đường tạo/sửa duy nhất; giọng nói không tạo Routine.
2. **Gọi** — "Vi Vi, chạy Đi làm".
3. **Preview** — ở lần chạy đầu của mỗi phiên bản Routine, Vi Vi đọc lại các bước và **dừng chờ
   xác nhận**; các lần sau bỏ qua bước này (chi tiết ở §Voice contract).
4. **Chạy** — từng bước, fail-fast, có tiến độ trên màn hình.
5. **Hủy** — bất cứ lúc nào, bằng nút Dừng hoặc bằng giọng nói, tại điểm dừng an toàn.
6. **Báo cáo** — một terminal outcome duy nhất: bước nào đã chạy, bước nào lỗi, bước nào chưa chạy.

## Phạm vi hành động MVP

Allowlist đóng, ánh xạ 1–1 với tool đã tồn tại trong `src/services/tool_registry.py`.
**Không có tool mới nào được tạo cho Routines.**

| Hành động trong Routine | Tool | Safety | Ghi chú ràng buộc |
|---|---|:-:|---|
| Bật/tắt điều hòa | `set_hvac_power` | S1 | |
| Đặt nhiệt độ | `set_hvac_temperature` | S1 | 16–30 °C |
| Đặt mức quạt gió | `set_hvac_fan_level` | S1 | **Mức tuyệt đối 0–3**, xem §Không có lệnh tương đối |
| Phát / tạm dừng / bài kế / bài trước | `media_control` | S1 | Không chọn playlist, không đổi nguồn phát |
| Đặt âm lượng | `media_control: set_volume` | S1 | **Mức tuyệt đối 0–100** |
| Sưởi ghế trước | `set_seat_heating` | S1 | Mức 0–3, chỉ 2 ghế trước |
| Dẫn đường Nhà / Cơ quan | `set_navigation` | S1 | Xem §Nhà và Cơ quan |
| Đèn cabin | `set_interior_light` | S1 | |
| Cửa sổ | `set_window_position` | **S2** | 0–100%, S2 **luôn luôn**, kể cả khi xe đứng yên |
| Chỉnh vị trí ghế trước | `set_seat_position` | **S2/S3** | S2 khi `speed_kph == 0 && gear == P`; **S3 khi xe đang chạy** |

**Không nằm trong MVP:** cửa (`set_door_state`), cốp (`set_trunk_state`), đèn pha
(`set_headlight_mode`), `open_app`, chọn bài/playlist cụ thể, làm mát ghế (không tồn tại trong
hệ thống), và mọi hành động S3.

### Không có lệnh tương đối

Router không đọc vehicle state, nên "tăng quạt gió" hôm nay trả `clarify` (xem
`docs/coverage_matrix.md` §Cách nói về lượng). Hệ quả sản phẩm: **Routine lưu giá trị tuyệt đối
tại thời điểm tạo**, không lưu "tăng 1 mức". Giao diện tạo Routine phải bắt người dùng chọn số,
không được cho nhập "tăng"/"giảm". Đây là ràng buộc, không phải thiếu sót cần vá trong MVP.

## Nhà và Cơ quan

`set_navigation` chỉ nhận `destination_id` thuộc **tập đóng** trong `src/fixtures/poi.json`
(6 POI, không có mục nào là nhà hay cơ quan). Quyết định:

1. Thêm **hai POI mới** vào fixture — `poi-home-01`, `poi-work-01` — đầy đủ
   `name/category/aliases/lat/lon/distance_km/eta_min/polyline` như 6 POI hiện có, để UI điều hướng
   không phải xử lý đích không có tuyến đường.
2. Mỗi user có một **mapping riêng** `home → poi_id` và `work → poi_id`, **mặc định rỗng**.
3. Routine chứa bước dẫn đường mà user **chưa gán** địa điểm tương ứng ⇒ **fail-fast tại bước đó**,
   báo rõ "chưa đặt địa điểm Nhà", và **không bao giờ rơi về một địa điểm mặc định**.

Ba hệ quả kỹ thuật mà BE/FE phải giữ:

- Tập `destination_id` vẫn đóng. Không sinh id động, không mở id space.
- `POI_CATEGORIES` và ba id kế thừa (`poi-cafe-01`, `poi-cafe-02`, `poi-charge-01`) đang bị
  `tests/test_services/test_fixtures.py` khoá — thêm POI là **thêm**, không sửa, không xoá.
- `frontend/src/lib/fixtures/poi.json` là bản **sinh ra** và bị so từng byte. Sửa fixture backend
  phải chạy `scripts/sync_fixtures.ps1`, nếu không CI đỏ.

Người dùng vì vậy "cá nhân hóa" bằng cách chọn trong tám điểm cố định chứ không đặt được nhà thật.
Đó là cái giá có chủ đích của ràng buộc offline/simulator-only, và nó vẫn giữ nguyên vẹn kịch bản
UAT #6 lẫn chữ "theo user" của #283.

## Voice contract

### Preview — bắt buộc ở lần chạy đầu của mỗi phiên bản

- Mỗi Routine mang một **version**; sửa bất kỳ bước, giá trị hay thứ tự nào đều bump version.
- Lần chạy đầu tiên của một version: Vi Vi đọc lại toàn bộ các bước, rồi **dừng chờ** tài xế nói
  cụm chấp nhận hoặc từ chối. Im lặng không phải là đồng ý.
- Từ lần chạy thứ hai của **cùng version**: chạy thẳng, không hỏi lại.
- Điều này áp dụng **kể cả Routine chỉ toàn S1**. Nó không mâu thuẫn với nguyên tắc "S1 không hỏi
  xác nhận thừa" của #270: nguyên tắc đó nói về *mỗi lần chạy*, còn đây là **một lần cho mỗi phiên
  bản** — giá của việc để tài xế phát hiện Routine sai *sau khi* nó đã mở cửa sổ là cao hơn nhiều.

**Preview không phải là approval.** Chỉ `src/agents/policy.py` được gán `safety_level`. Xác nhận
preview là xác nhận ở tầng Routine; nó **không** tạo `ActionPlan`, **không** đi qua approval store,
và **không** được dùng làm cửa thứ hai vào executor. Bước S2 bên trong Routine vẫn phải xin phê
duyệt riêng qua đúng đường HITL hiện có.

### Chạy

- Các bước chạy **tuần tự**, theo đúng thứ tự đã lưu.
- Gặp bước S2 ⇒ dừng lại, xin phê duyệt, chờ. Hệ thống chỉ cho phép **một approval đang chờ mỗi
  session** (partial unique index trong DB) — nên Routine có hai bước S2 **buộc phải** xin phê duyệt
  tuần tự, không gộp thành một thẻ. Đây là ràng buộc của hệ thống, không phải lựa chọn sản phẩm.
- Bước hoá **S3** tại thời điểm chạy (ví dụ chỉnh ghế khi xe đang lăn bánh) ⇒ **chặn trước HITL**,
  fail-fast, không hỏi tài xế.
- Từ chối / hết hạn / mơ hồ ở bất kỳ approval nào ⇒ **zero side effect** cho bước đó và dừng Routine.

### Hủy

- **Trong lúc Routine đang chạy, "dừng" / "hủy" trần luôn có nghĩa là hủy Routine**, kể cả khi
  Routine vừa bật nhạc. Muốn tắt nhạc phải nói rõ "tắt nhạc". Sau khi Routine kết thúc, "dừng" trở
  lại nghĩa media thông thường. Luật này là nguồn duy nhất giải xung đột với
  [#299](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/299) và
  [#320](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/320); hai issue đó phải trỏ về đây.
- **Điểm dừng an toàn là giữa hai bước.** Bước đang chạy chạy nốt — lệnh đã publish lên MQTT không
  rút lại được, và một hệ thống báo "đã hủy" trong khi xe vừa mở kính là một hệ thống nói dối.
- Đang chờ approval mà hủy ⇒ **từ chối approval đó**, zero side effect, không chạy bước nào nữa.
- **Không rollback.** Side effect đã hoàn tất thì giữ nguyên. Báo cáo phải nói rõ cái gì đã xảy ra.
- Hủy là **idempotent**: hủy hai lần, hoặc hủy một Routine đã kết thúc, cho cùng một kết quả và
  không sinh thêm outcome.

### Báo cáo

Mỗi lần chạy kết thúc bằng **đúng một terminal outcome**, kể cả khi hủy hay lỗi, nêu rõ ba nhóm:
đã chạy xong / lỗi (kèm lý do) / chưa chạy. Reconnect không được nhân đôi outcome hay side effect.

## Ba mẫu mặc định

Mẫu là **điểm khởi đầu để sửa**, không phải Routine cố định. Tạo từ mẫu ⇒ sinh một Routine thuộc
user đó, version 1, và vì vậy **có preview ở lần chạy đầu**.

| Mẫu | Các bước gợi ý |
|---|---|
| **Đi làm** | Bật điều hòa → 24 °C → dẫn đường Cơ quan |
| **Về nhà** | Bật điều hòa → phát nhạc → dẫn đường Nhà |
| **Thư giãn** | Phát nhạc → âm lượng 30 → đèn cabin |

Mẫu "Đi làm"/"Về nhà" chỉ dùng được sau khi user đã gán địa điểm; trước đó bước dẫn đường
fail-fast theo §Nhà và Cơ quan.

## Cô lập theo tài khoản

- Routine, mapping địa điểm và lịch sử chạy đều thuộc về đúng một `user_id`.
- User B **không** liệt kê, đọc, sửa, xóa hay chạy được Routine của user A — kể cả khi biết id.
- Không chia sẻ, không marketplace, không Routine dùng chung.

## Sau khi khởi động lại

- Routine và mapping địa điểm **sống sót** restart (persistence theo ADR-017).
- **Execution đang dở và approval đang chờ thì không.** LangGraph dùng `InMemorySaver`, checkpoint
  chết theo tiến trình, và `invalidate_orphaned_pending_approvals()` fail chúng closed lúc khởi động.
  Đây là hành vi đúng, không phải bug: sau restart không có Routine nào tự chạy tiếp và không có
  phê duyệt nguy hiểm nào hồi sinh.

## Quyết định còn treo — barge-in

Kết quả spike [#277](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/277) chưa có.
Spec cam kết trước cả hai nhánh, và PM/PO ghi quyết định tại #280 **ngay khi có kết quả**, không
chờ tới #279:

- **Go** — nói "dừng" cắt ngang được TTS đang phát; hủy nhận được ở bất kỳ thời điểm nào.
- **No-Go** — fallback chính thức: nút Dừng
  ([#298](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/298)) là đường hủy được bảo đảm;
  voice cancel chỉ nhận giữa hai bước khi TTS im. Demo runbook phải nêu rõ fallback này.

Trong cả hai nhánh, **nút Dừng luôn tồn tại**.

## Out of scope

Scheduler và trigger theo giờ/vị trí · AI học thói quen · chia sẻ/marketplace · địa chỉ online hoặc
nhập tự do · rollback side effect · chọn playlist/bài cụ thể · làm mát ghế · cửa và cốp · S3 ·
tạo/sửa Routine bằng giọng nói · nhiều Routine chạy đồng thời.

## Ranh giới với refinement kỹ thuật

Tài liệu này chốt **hành vi sản phẩm**. Thiết kế bảng, endpoint, contract sự kiện, chia component
và test design chi tiết thuộc refinement của BE (#282, #283, #286, #290, #297), FE (#281, #284,
#292, #294, #298) và Agent (#285, #288, #296, #299).

## UAT checklist

10 kịch bản bắt buộc của #279 cộng hai kịch bản bổ sung, ánh xạ sang user story nguồn. #300 dùng
bảng này làm khung traceability; cột Evidence bỏ trống có chủ đích — mỗi dòng phải được điền bằng
automated test hoặc evidence manual đã duyệt trước khi #279 đóng.

| # | Kịch bản | Story nguồn | Evidence |
|:-:|---|---|---|
| 1 | User A tạo/sửa/chạy Routine; user B không truy cập được | #271, #272 | |
| 2 | Routine S1-only, **lần chạy thứ hai** trở đi: không confirmation thừa | #274 | |
| 2b | Routine S1-only, **lần chạy đầu của version**: có preview và chờ xác nhận | #274 | |
| 3 | S2 preview + voice approval hợp lệ rồi mới chạy | #275 | |
| 4 | Từ chối / hết hạn / mơ hồ ⇒ zero side effect | #275 | |
| 5 | Bước hoá S3 do xe đang chạy ⇒ bị chặn trước HITL | #275 | |
| 6 | Routine thiếu Nhà/Cơ quan ⇒ fail-fast, **không dùng default** | #273 | |
| 7 | Step failure ⇒ fail-fast, báo đúng phần đã/chưa chạy | #276 | |
| 8 | Hủy bằng UI; voice cancel theo kết quả spike #277 | #277, #278 | |
| 9 | Restart giữ Routine/địa điểm, không hồi sinh execution/approval | #272, #275 | |
| 10 | Reconnect không nhân đôi kết quả hay side effect | #276 | |
| 11 | "Dừng" khi Routine đang chạy ⇒ hủy Routine, không tắt nhạc | #278, #299 | |

Kịch bản 2b và 11 là **bổ sung của spec này** so với danh sách gốc ở #279 — chúng test đúng hai
quyết định sản phẩm mới chốt, nên #279 cần cập nhật danh sách.

## Definition of Ready

Một child issue chỉ chuyển sang triển khai khi có đủ: user outcome, scope, acceptance criteria,
out-of-scope, dependency, owner workstream, và đã qua refinement với workstream chịu trách nhiệm.

## Release gates

Lặp lại từ #270/#279 để spec tự đứng được:

- Không rò rỉ dữ liệu giữa user.
- Không có S2 nào thực thi mà thiếu approval; không có side effect S3 nào.
- Fail-closed khi mất kết nối hoặc vehicle state unavailable.
- Cancel/failure sinh đúng một terminal outcome và không bắt đầu bước tiếp theo.
- UI và voice nhất quán về trạng thái.
- E2E chạy trên baseline có ghi commit SHA; regression suite liên quan xanh.
- Voice eval dùng evidence phù hợp — **audio tổng hợp Piper không được gọi là human WER**.
- PM/PO ký Go/No-Go dựa trên evidence, không dựa trên screenshot hay mock.

## Nhật ký quyết định

| Ngày | Quyết định | Lý do |
|---|---|---|
| 2026-08-26 | Preview + chờ xác nhận ở lần chạy đầu của **mỗi version**, kể cả Routine toàn S1 | Phát hiện Routine sai sau khi nó đã chạy là ca đắt nhất; hỏi một lần cho mỗi version rẻ hơn nhiều so với hỏi mỗi lần chạy |
| 2026-08-26 | Nhà/Cơ quan = 2 POI fixture mới + mapping per-user, mặc định rỗng | Giữ `destination_id` là tập đóng và giữ nguyên polyline cho UI, mà vẫn có trạng thái "chưa cấu hình" thật để UAT #6 kiểm được |
| 2026-08-26 | "Dừng"/"hủy" trần thuộc về Routine khi Routine đang chạy | Nút thoát hiểm phải hoạt động bằng từ ngữ tài xế thật sự dùng lúc hoảng, không phải bằng thuật ngữ |
| 2026-08-26 | Điểm dừng an toàn = giữa hai bước, không rollback | Lệnh đã publish lên MQTT không rút lại được; báo "đã hủy" khi xe vừa mở kính là báo cáo sai sự thật |

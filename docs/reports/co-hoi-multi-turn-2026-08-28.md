# Khảo sát cơ hội multi-turn — điều khiển, SLM/LLM, RAG

> **Status: khảo sát, không phải cam kết phạm vi.** Mọi ô "hiện trạng" trong tài liệu này
> được **đo trực tiếp** trên `develop` @ `7a72b47` ngày 2026-08-28 bằng router thật và
> FAISS index thật, không lấy từ tuyên bố của tài liệu khác. Script tái lập ở §7.

Tài liệu trả lời một câu hỏi: **hệ thống đang có những chỗ nào mà một lượt thứ hai sẽ
làm nó hữu ích hẳn lên**, và mỗi chỗ ấy phải nhớ cái gì.

---

## 1. Multi-turn trong repo này nghĩa là gì

Hạ tầng đã sẵn, không phải xây mới:

| Thành phần | Ở đâu | Vai trò |
|---|---|---|
| Một session = một `thread_id` checkpoint LangGraph | `src/api/session_state.py:464` | state của lượt trước **còn nguyên** khi lượt sau chạy |
| Khai báo field sống qua lượt | `src/agents/state.py` | mọi ngữ cảnh multi-turn phải khai ở đây, nếu không LangGraph **loại bỏ im lặng** |
| Danh sách dọn mỗi lượt | `_PER_TURN_RESET`, `src/agents/nodes/normalize.py:25` | field **không** nằm trong dict này chính là field sống qua lượt |
| Checkpoint chết theo tiến trình | `InMemorySaver` | **chủ ý** (ADR-025): một câu hỏi lại sống sót qua restart là cái bẫy |

Và một ràng buộc không được phá: **router tất định, không đọc trạng thái** (ADR-006/ADR-010).
Nên mọi thứ dưới đây đều theo cùng một khuôn đã có tiền lệ:

> Ngữ cảnh sống ở **node** (node đọc được state), router chỉ được **gọi lại với một chuỗi khác**.
> Xem `_tra_loi_loi_moi_nghe_tiep` — `src/agents/nodes/route.py:8`.

---

## 2. Đã chạy được hôm nay (4 mảnh)

| Mảnh | Ngữ cảnh nhớ ở đâu | Cổng đọc ngữ cảnh |
|---|---|---|
| Phê duyệt HITL bằng giọng — *"đồng ý"* / *"hủy"* | approval store + SQLite | `src/agents/voice_intent.py`, gọi từ `src/api/turns.py:692` |
| *"Đọc tiếp"* đoạn sổ tay | `speech_source_text`, `speech_da_doc`, `speech_citations` | `_tra_loi_loi_moi_nghe_tiep` (`route.py:8`) → `doc_tiep` (`speech_policy.py:637`) |
| Mic tự mở sau lượt còn phần dư (#343) | `hasMoreToRead` ở FE | `DriverShellProvider.tsx:1508` |
| Wake word (#177) | FE | `frontend/src/lib/wake-word/onnxWakeWordDetector.ts` |

**Mảnh thứ 5 đã viết xong nhưng KHÔNG có trên `develop`:** phần B của issue #148
(`src/agents/ghep_hoi_lai.py`, ADR-025, 350 dòng test) — có ở commit `d108216`, bị gỡ ở
`6bb2713` để tách sang nhánh `feat/ghep-hoi-lai-phan-b`. PR #267 mang nhãn MERGED nhưng
merge commit của nó (`3ca6a502`) là merge commit của **#217**, tức nhánh chưa bao giờ rebase.
Kiểm chứng: `git show origin/develop:src/agents/ghep_hoi_lai.py` → *does not exist*.

---

## 3. Bảng tổng hợp — 14 cơ hội

Cột **Đo được** là hành vi hôm nay của lượt thứ hai.

| # | Cơ hội | Mảng | Đo được hôm nay | Ưu tiên |
|---|---|---|---|:-:|
| A1 | Trả lời câu hỏi lại (`clarify`) | Điều khiển | `not_control / default_to_manual` | **1** — code đã có |
| A2 | Đồng ý với lời đề nghị (`offer`) | Điều khiển | `not_control / default_to_manual` | **2** — plan đã nằm sẵn trong tay |
| A3 | Chọn địa điểm sau `poi_search` | Điều khiển | `not_control / default_to_manual` | **3** — xe tự hỏi rồi không nghe được |
| A4 | Lệnh tương đối (*"tăng thêm"*) | Điều khiển | `clarify / relative_change_unsupported` | 5 |
| A5 | *"Bật tiếng lại"* sau *"tắt tiếng"* | Điều khiển | `clarify / missing_volume` | 6 |
| A6 | Mở rộng đích (*"bên phải nữa"*) | Điều khiển | `not_control / default_to_manual` | 7 |
| A7 | Sửa sai **xuyên lượt** (*"à thôi"*) | Điều khiển | `not_control / default_to_manual` | 8 |
| A8 | Chọn lại sau khi bị `denied` | Điều khiển | rơi sổ tay hoặc mất đích | 8 |
| A9 | Hoãn lệnh bị chặn S3 | Điều khiển | không có đường | 10 (rủi ro cao) |
| B1 | Chitchat nhiều lượt | SLM | không có history | 7 |
| B2 | Planner SLM không thấy lượt trước | SLM | không có history | 8 |
| B3 | Preview Routine (*"đồng ý"* / *"bỏ bước 2"*) | SLM/luật | **code có, chưa nối vào graph** | **4** |
| C1 | Hỏi tiếp cùng chủ đề sổ tay | RAG | từ chối, hoặc trả lời **lạc chủ đề** | **3** |
| C3 | Điều chỉnh độ dài / đọc lại | RAG | không có đường | 9 |

### 3b. Làm có khó không

Thang chấm **công sửa**. Cột cuối là thứ thật sự quyết định lịch: một hạng mục code hai ngày
mà cần PO chốt an toàn thì không phải hạng mục dễ.

| Mã | Công sửa | Ước lượng | Chặn bởi / ai duyệt |
|---|---|---|---|
| A2 | Thấp | ~90 dòng + test | không gì — làm được ngay |
| C4 | Thấp | ~50 dòng + test | không gì (S0) |
| A8 | Thấp | ~60 dòng + test | không gì |
| A1 | Thấp (code đã có) | revert + rebase | **PO chốt an toàn** — ADR-025 phải mở lại |
| A3 | Vừa | ~150 dòng + test | không gì |
| A6 | Vừa | ~120 dòng + test | ADR-025 cố ý loại lớp này — cần mục bổ sung |
| B1 | Vừa | ~80 dòng + đo lại độ trễ | ngân sách độ trễ VPS |
| C1 | Vừa | ~130 dòng + chạy lại eval RAG | phải chứng minh `question_recall` không tụt |
| A4 | Cao | ~200 dòng, 4 miền | đụng `coverage_matrix`; fail-closed khi mất state xe |
| A5 | Cao (đường đúng) | `muted` vào MediaState + schema + sim | **chốt hợp đồng MQTT** (đường rẻ ~30 dòng, mất khi restart) |
| B2 | Cao | ~100 dòng + sửa `cong_mien_slm` | cổng fail-closed phải xét câu đã ghép |
| A7 | Cao | ~180 dòng + ADR | hoàn tác là hành động thật — S2 vẫn là S2 |
| B3 | Vừa | nối graph + 1 field state | **đang bị chặn** — routines chưa có API/bảng DB, mới có mock FE |
| C3 | Thấp | ~60 dòng | **đang bị chặn** — tầng nén còn tắt mặc định (PR #231) |
| A9 | Rất cao | — | **khuyến nghị không làm** |

Ba hạng mục làm được ngay, không chờ ai duyệt: **A2, C4, A8**. Bản trình bày của bảng này:
[Lượt thứ hai](https://claude.ai/code/artifact/0372d296-2890-40d2-bb5d-c40cb78044cb).

---

## 4. Mảng A — Điều khiển

### A1. Trả lời câu hỏi lại — 16 lý do `clarify`, 9 lý do ghép được

Router có đúng 16 lý do `clarify`. Chín trong số đó nêu ra một lựa chọn/dải cụ thể, tức là
**xe đã hỏi một câu có đáp án đóng** rồi không hiểu đáp án ấy.

```
Lượt 1  Tài xế: "Chỉnh quạt gió mức 2 điều hòa"
        VIVI:   "Tôi chưa chỉnh gì cả. Bạn muốn điều hòa bao nhiêu độ, từ 16 đến 30?"
Lượt 2  Tài xế: "18 độ"
        VIVI:   "Tôi không tìm thấy thông tin này trong sổ tay xe."   <- đo: not_control/default_to_manual
                (xe không đổi gì, và ý "quạt mức 2" cũng mất luôn)

Mong muốn: ghép "chỉnh quạt gió mức 2 điều hòa" + "18 độ" -> control, 2 BƯỚC (đo được).
```

Chuỗi nhiều slot cũng tự nối tiếp được:

```
"mở cửa sổ"          -> clarify/missing_window_side       "Bên nào?"
"bên lái"            -> đo: default_to_manual  |  ghép -> clarify/missing_window_position
"30 phần trăm"       -> đo: default_to_manual  |  ghép -> control (set_window_position 30%)
```

**Việc cần làm:** hồi sinh phần B của #148 (§2). Cơ chế: nối chuỗi `gốc + " " + mảnh` rồi
route lại; TTL 30 s; chỉ lượt kế tiếp; không ghép nếu lượt mới tự khớp `control`.

**Rủi ro đã được ghi trong ADR-025 và nay đã bị kích hoạt:** ADR tính bộ chốt với giả định
*"sau câu hỏi lại, mic KHÔNG tự mở"*. Giả định ấy chết rồi — wake word (#177) và cửa sổ nghe
tiếp (#343) đều đã vào `develop`. Phải tính lại trước khi merge.

### A2. Đồng ý với lời đề nghị (`offer`) — rẻ nhất, vì kế hoạch đã nằm sẵn trong tay

`offer` là disposition **có mang `candidate_plan`** (`contracts.py:77`). Xe nêu đúng việc nó
sẽ làm rồi hỏi lại — nhưng câu trả lời không đi đâu cả.

```
Lượt 1  Tài xế: "Bật điều hòa được không?"
        VIVI:   "Tôi có thể bật điều hòa. Bạn có muốn tôi thực hiện không?"
                -> offer / hvac_power, plan sẵn: set_hvac_power{enabled: true}
Lượt 2  Tài xế: "Có"  /  "Ừ"  /  "Đồng ý"  /  "Làm đi"  /  "Được"
        VIVI:   "Tôi không tìm thấy thông tin này trong sổ tay xe."
                <- cả 5 câu đều đo ra not_control / default_to_manual

Mong muốn: lấy đúng plan của lượt trước, đưa thẳng vào policy -> safety -> (HITL nếu S2).
```

Ba câu khác cùng lớp, đều đã đo: `"mở youtube được không"` → offer `open_app{youtube}`;
`"mở cốp được không"` → offer `set_trunk_state{open}`; `"có quán cà phê nào gần đây không"`
→ offer `set_navigation{poi-cafe-02}`.

**Vì sao rẻ:** không phải ghép chuỗi, không phải route lại. Chỉ cần nhớ `candidate_plan` của
lượt `offer` và dùng lại `voice_intent.doc_tra_loi_co_khong` — **đúng bộ nhận dạng đang dùng
cho phê duyệt HITL**, không phải viết bộ thứ hai. Chính docstring của `voice_intent.py` đã dự
liệu chuyện này (*"làm riêng hai lần là hai bộ nhận dạng ý định, và chúng sẽ lệch nhau"*).

**Chốt bắt buộc:** plan lấy lại vẫn phải đi qua `policy.py`. Một `offer` cho `set_trunk_state`
khi xe đang chạy vẫn phải ra S3/blocked — không được vì "đã hỏi rồi" mà thành S2.

### A3. Chọn địa điểm sau `poi_search` — xe hỏi một câu rồi không nghe nổi câu trả lời

Đây là ca khó chịu nhất, vì câu hỏi do **chính hệ thống** đặt ra và nó rất mở:

```
Lượt 1  Tài xế: "Quanh đây có mấy quán cà phê?"
        VIVI:   "Tôi tìm được 3 chỗ: Cà phê Bình Minh cách 3,7 km, Highlands Coffee
                 Nguyễn Trãi cách 5,6 km, ... Bạn muốn đi chỗ nào?"
                -> control / poi_search, search_nearby_poi{category: cafe}   (S0, chỉ đọc)
Lượt 2  Tài xế: "Highlands"           -> đo: default_to_manual
                "Chỗ thứ hai"         -> đo: default_to_manual
                "Cái gần nhất"        -> đo: default_to_manual
                "Chọn cái đầu"        -> đo: default_to_manual
                "Cho tôi tới chỗ đó"  -> đo: default_to_manual

Chỉ câu có động từ mới chạy:  "Đi Highlands" -> control, set_navigation{poi-cafe-01}
```

**Cần nhớ:** danh sách 3 POI vừa đọc (id + tên + thứ tự). Ngữ cảnh này là **danh sách có thứ
tự**, không phải chuỗi văn bản — nên A3 **không** giải được bằng cơ chế ghép chuỗi của A1; nó
cần một field riêng, kiểu `cho_chon_poi: list[str]`.

**Đường giải:** tại node, nếu lượt trước là `poi_search` và lượt này không tự khớp `control`,
đối chiếu lời nói với (a) alias POI trong danh sách, (b) số thứ tự (*"thứ hai"*, *"cái đầu"*),
(c) so sánh (*"gần nhất"*). Khớp thì dựng `set_navigation` — S1, đảo ngược được.

**Bẫy có sẵn trong dữ liệu:** `"thứ hai"` là **alias của `poi-cafe-02`** trong
`src/fixtures/poi.json`. *"Chỗ thứ hai"* trong danh sách 3 quán có thể là Highlands, không
phải Bình Minh. Thứ tự đối chiếu phải là **số thứ tự trong danh sách vừa đọc, trước alias** —
nếu không hệ thống sẽ đi sai quán một cách rất tự tin.

### A4. Lệnh tương đối — *"tăng thêm"*, *"giảm bớt"*

```
"tăng quạt gió"          -> clarify / missing_fan_level
"tăng âm lượng thêm 10"  -> clarify / relative_change_unsupported
"mở thêm 20%"            -> default_to_manual
```

Router không đọc vehicle state (ADR-010) nên không cộng trừ được. Đây **không thuần** là
multi-turn: cái cần là **trạng thái xe**, và `vehicle_snapshot` đã có sẵn trong `AgentState`
mỗi lượt (`normalize.py`). Nhưng nó *cũng* là multi-turn ở nghĩa thứ hai: sau *"tăng quạt gió"*
xe hỏi *"mức mấy?"*, và lượt trả lời cần A1.

**Đường giải:** giải ở node (`vehicle_snapshot` + delta) rồi gọi router với **giá trị tuyệt
đối**. Router vẫn không đọc state. Ghi chú `coverage_matrix.md`: trước 2026-08-15 nhánh âm
lượng/kính đọc *"tăng thêm 10"* thành **giá trị tuyệt đối 10** — đang ở 60 thì tụt xuống 10.
Đó là lý do mọi miền nay đều `clarify`, và là lý do đường giải phải đi qua state chứ không
qua phỏng đoán.

### A5. *"Bật tiếng lại"* — ngữ cảnh cần nhớ nằm ngoài tầm agent

```
Lượt 1  "Tắt tiếng"      -> control, media_control{action: set_volume, volume: 0}
Lượt 2  "Bật tiếng lại"  -> clarify / missing_volume   "Bạn muốn âm lượng mức nào?"
```

Không phải router lười: `MediaState` **không có trường `muted`** (`router.py:1594-1617`), nên
mức trước khi tắt không có chỗ nào lưu. Hai đường, và đây là **quyết định hợp đồng MQTT**,
không phải quyết định của agent:

- rẻ: nhớ `volume` trước khi đặt 0 trong `AgentState` (chỉ đúng trong một phiên, mất khi restart);
- đúng: thêm `muted` vào `MediaState` + schema MQTT → cần người chốt hợp đồng.

### A6. Mở rộng đích — *"bên phải nữa"*, *"cái đó nữa"*

```
Lượt 1  "Mở cửa sổ bên lái"  -> clarify / missing_window_position
Lượt 2  "Bên phải nữa"       -> default_to_manual
        "Cả bên kia nữa"     -> default_to_manual
        "Cái đó nữa"         -> default_to_manual
```

ADR-025 **cố ý loại** `ambiguous_reference` khỏi danh sách ghép: *"chưa biết đang nói về cái
gì thì ghép vào cái gì"*. Đúng cho ca đó — nhưng ca *"bên phải nữa"* ngay sau một lệnh cửa sổ
đã chạy thì đích **có** xác định. Đây là hạng mục riêng, cần đích của lượt trước
(`action_plan.steps[*].args` theo các khoá trong `_TARGET_ARG_KEYS`, `router.py:381`), không
phải chuỗi văn bản.

### A7. Sửa sai xuyên lượt — *"à thôi"*, *"nhầm rồi"*

Router **đã** xử lý dấu sửa lời **trong một lượt** (`"bật điều hòa à thôi tắt đi"` —
`router.py:940`). Nói một mình ở lượt sau thì không:

```
Lượt 1  "Mở cửa sổ bên lái 50%"  -> control, đã chạy
Lượt 2  "À thôi"  /  "Nhầm rồi"  -> default_to_manual
```

**Cần nhớ:** `action_plan` + `step_results` của lượt vừa xong, và **giá trị trước khi đổi** để
hoàn tác. Rủi ro cao hơn A1–A3: hoàn tác là một hành động thật, nên phải qua policy như mọi
lệnh khác — hoàn tác một lệnh S2 vẫn là S2.

### A8. Chọn lại sau khi bị `denied`

Router có 11 lý do `denied`. Hai lý do để lại một cuộc hội thoại dở dang:

```
Lượt 1  "Phát bài Diễm xưa"    -> denied / media_track_unknown  (không đổi bài đang phát)
Lượt 2  "Vậy bài khác đi"      -> control  (đo được — nhưng chỉ vì câu có chữ "bài")
        "Bài khác đi"          -> default_to_manual

Lượt 1  "Tắt đèn pha"          -> denied / headlight_off_not_permitted  (UNECE R48, ADR-020)
Lượt 2  "Vậy chuyển chiếu gần" -> control  (chạy được, nhờ tu_dong_nghia)
        "Vậy thôi"             -> default_to_manual
```

Lớp này rẻ: chỉ cần lượt sau nhìn thấy `intent` của lượt `denied` trước.

### A9. Hoãn lệnh bị chặn S3 — nêu ra để **cảnh báo**, không phải để làm

```
Lượt 1  "Mở cửa bên lái" @ 45 km/h  -> blocked (S3)
        VIVI: "Xe đang chạy 45 km/h nên tôi chưa mở cửa được. Khi xe dừng hẳn và về
               số P thì tôi làm ngay."
Lượt 2  "Ừ, lát nữa dừng thì mở giúp tôi"  -> default_to_manual
```

PR #338 đã **bác** một phiên bản nhẹ hơn của ý này (đề nghị hạ kính thay thế), với lý do:
*một lời đề nghị không có đường thực hiện tệ hơn im lặng*. Lệnh hoãn còn nặng hơn — nó là một
hành động S2/S3 **chờ điều kiện xe**, tức một bộ hẹn giờ trên bề mặt an toàn. Không làm trong
P0; nếu làm thì cần ADR riêng.

---

## 5. Mảng B — SLM/LLM

Ba vai SLM (ADR-016) và cả ba đều **không nhận lịch sử hội thoại** — điều tra tại chữ ký hàm:

| Vai | Chữ ký | Ở đâu |
|---|---|---|
| Planner | `propose(normalized_text, snapshot)` | `src/agents/slm.py:276` |
| Chitchat | `reply(normalized_text)` | `src/agents/slm.py:657` |
| Phân loại | `classify(normalized_text)` | `src/agents/slm.py:539` |
| Chọn câu (RAG) | `select(question, sentences)` | `src/agents/slm.py:448` |

Và không có bảng `turns` trong `src/db.py` (chỉ `users`, `sessions`, `approvals`,
`idempotency_records`, `vehicle_profiles`, `vehicle_options`) — **không transcript nào tồn tại**.

### B1. Chitchat nhiều lượt

```
Lượt 1  "Hôm nay trời đẹp nhỉ"   -> chitchat, model trả lời
Lượt 2  "Thế à"  /  "Ừ nhỉ"      -> model không biết đang nói về cái gì
```

**Cần nhớ:** 2–3 lượt gần nhất, dạng `(user, assistant)`. Chi phí thật nằm ở chỗ khác: mọi
chuỗi model sinh ra đều phải đi qua `chitchat_cong.py` (4 lớp cổng chặn bịa), và history dài
làm token vào tăng — trên VPS đó là độ trễ. Đề xuất: trần cứng 2 lượt, và **không** đưa nội
dung sổ tay vào history (nó là dữ kiện, phải đi qua RAG).

### B2. Planner SLM không thấy lượt trước

Cùng lớp với A1 nhưng ở đường SLM: sau một `clarify`, planner nhận mảnh `"18 độ"` trần.

Ghi chú quan trọng — `cong_mien_slm.py` là cổng fail-closed **bắt plan phải chạm đúng thứ tài
xế vừa nhắc tới**. Nếu đưa history vào prompt thì cổng ấy phải xét trên **câu đã ghép**, không
phải mảnh trần, nếu không nó sẽ chặn oan chính ca ta vừa sửa.

### B3. Preview Routine — code đã có, **chưa nối vào graph**

`src/agents/routines_intent.py:101` — `doc_y_dinh(normalized_text, *, dang_xem_truoc: bool)`.
Tham số `dang_xem_truoc` **chính là ngữ cảnh multi-turn**: cùng chuỗi *"Đồng ý"* mang hai nhãn
ngược nhau tuỳ có preview treo hay không. Nhưng `grep` toàn `src/` không thấy caller nào.

```
Lượt 1  "Chạy routine đi làm"
        VIVI:  "Routine 'Đi làm' gồm: bật điều hòa 24 độ, mở nhạc, dẫn đường tới cơ quan.
                Bạn muốn chạy không?"
Lượt 2  "Đồng ý"      -> chạy cả 3 bước
        "Bỏ bước 2"   -> chạy 2 bước
        "Thôi"        -> huỷ
```

**Cần nhớ:** routine đang preview + các bước đã bị bỏ. Đây là hạng mục **rẻ nhất trong mảng B**:
phần đọc câu chữ đã viết xong và có test; việc còn lại là nối vào graph + một field state.

---

## 6. Mảng C — RAG

### C0. Đường mẫu đã chạy: *"đọc tiếp"*

Đây là **tiền lệ đúng**, mọi hạng mục khác nên bắt chước hình dạng của nó: ngữ cảnh
(`speech_source_text`, `speech_da_doc`, `speech_citations`) khai trong `AgentState`, **cố ý
không** nằm trong `_PER_TURN_RESET`, và cổng đọc ngữ cảnh nằm ở node. Chuỗi hỏi sổ tay → bật
điều hoà → *"đọc tiếp"* chạy được, vì ngữ cảnh thuộc về **phiên**, không thuộc về **lượt**.

### C1. Hỏi tiếp cùng chủ đề — hạng mục nguy hiểm nhất trong mảng C

Đo thật trên FAISS index VF9 (E5, ngưỡng ADR-003):

```
Lượt 1  "Áp suất lốp tiêu chuẩn là bao nhiêu?"
        -> 8 chunk thô, 5 chunk qua ngưỡng, top-1 = 0.889 (bảng thông số lốp)   trả lời đúng

Lượt 2a "Còn bản PLUS thì sao?"
        -> 8 thô, **0 qua ngưỡng** -> grounded_refusal
        VIVI: "Tôi không tìm thấy thông tin này trong sổ tay xe."

Lượt 2b "Thế còn ghế sau?"
        -> 8 thô, **5 qua ngưỡng** — nhưng chunk top-1 (0.878) là "Để gấp hàng ghế thứ ba..."
        VIVI: đọc nguyên văn về **gập ghế**, trong khi tài xế đang hỏi **áp suất lốp**
```

2b tệ hơn 2a: không phải từ chối, mà là **trả lời tự tin lạc chủ đề**. Ngưỡng cosine không cứu
được, vì câu vẫn "đúng chủ đề ghế".

**Cần nhớ:** câu hỏi gốc của lượt trước. Đường giải khớp đúng khuôn A1: phát hiện câu nối tiếp
(*"còn… thì sao"*, *"thế còn…"*, *"vậy còn…"*) → ghép với câu hỏi lượt trước → truy hồi lại.
Cùng bộ chốt: TTL, chỉ lượt kế tiếp, và **nếu ghép không nâng được điểm bằng chứng thì bỏ ghép**.

**Điều kiện bắt buộc:** ADR-015 cấm SLM viết lại đoạn (4/40 câu gây hiểu lầm, toàn do rơi mất
điều kiện theo phiên bản ECO/PLUS, SDI/CATL). Multi-turn ở đây **không được** trở thành đường
vòng để tổng hợp hai chunk thành một câu mới. Ghép **câu hỏi**, không ghép **câu trả lời**.

### C2. Biến thể xe — đã có nơi để nhớ, chỉ chưa dùng

Ca *"Còn bản PLUS thì sao?"* thật ra không nhất thiết cần multi-turn: repo đã có
`GET/PUT /api/v1/vehicle/profile` và `/profile/options` (65 mục, `src/safety/trang_bi.json`).
Đọc biến thể từ **hồ sơ xe** đáng tin hơn nhớ từ lời nói — và nó khớp với chính lớp lỗi mà
ADR-015 đo được. Multi-turn chỉ nên dùng cho phần hồ sơ **không** trả lời được.

### C3. Điều chỉnh độ dài / đọc lại

```
Lượt 1  "Cách bật chế độ camping?"  -> VIVI đọc một đoạn dài
Lượt 2  "Ngắn gọn thôi" / "Nói lại" / "Chi tiết hơn"  -> không có đường nào
```

Tầng nén đã có (`src/agents/tom_tat.py`, bốn cổng cứng, **tắt mặc định**; PR #231 đang ghi rõ
chưa nên bật). Ngữ cảnh cần nhớ đã có sẵn (`speech_source_text`). Việc còn lại là một cổng ý
định ở node — nhưng phải đợi tầng nén được chốt bật, nếu không *"ngắn gọn thôi"* không có gì
để gọi.

### C4. Đi tới trích dẫn

`citations` đã nằm trong state và có `GET /citations/{citation_id}`, nhưng không lượt sau nào
dùng: *"Ở trang nào?"*, *"Cho tôi xem chỗ đó"* → rơi sổ tay. Rẻ, S0, không rủi ro an toàn.

---

## 7. Tái lập số đo

Toàn bộ bảng "đo được" ở trên sinh từ router thật, không cần MQTT, không cần broker:

```powershell
cd D:\HASON\2025.2\VIN\P192\P-192
```
```powershell
$env:MQTT_ENABLED="false"; $env:PYTHONIOENCODING="utf-8"
```

Lưu đoạn sau thành một file `.py` rồi chạy bằng `.\.venv\Scripts\python.exe <file>`:

```python
from src.agents.router import DeterministicControlRouter, normalize_vi
r = DeterministicControlRouter()
for c in ["mở cửa sổ", "bên lái", "30 phần trăm", "bật điều hòa được không", "có",
          "quanh đây có mấy quán cà phê", "highlands", "chỗ thứ hai", "tắt tiếng",
          "bật tiếng lại", "tăng âm lượng thêm 10", "à thôi"]:
    d = r.route(normalize_vi(c))
    args = [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]
    print(c, "->", d.disposition, d.intent, d.reason, args)
```

Phần RAG cần FAISS index (`data/rag/vf9_2026_vi/index.faiss`) và mất ~30 s nạp E5:

```python
from pathlib import Path
from src.rag.retrieve import load_retriever
from src.rag.embed import E5Embedder
rt, emb = load_retriever(Path("./data/rag/vf9_2026_vi")), E5Embedder()
for q in ["áp suất lốp tiêu chuẩn là bao nhiêu", "còn bản PLUS thì sao", "thế còn ghế sau"]:
    ev = rt.retrieve(q, emb)
    print(q, "thô=", len(ev), "giữ=", len(rt.grade(q, ev)))
```

---

## 8. Nguyên tắc chung — áp cho mọi hạng mục ở trên

1. **Router giữ tất định và không đọc state.** Ngữ cảnh giải ở node; router chỉ được gọi lại
   với một chuỗi khác, hoặc với một giá trị tuyệt đối đã tính sẵn. ADR-006/ADR-010 không bị đụng.
2. **Ngữ cảnh nào sống qua lượt phải khai trong `AgentState` và nằm ngoài `_PER_TURN_RESET`.**
   Thiếu một trong hai thì nó biến mất **im lặng** — bug đã xảy ra thật với `speak_text`.
3. **Mọi lệnh sinh từ ngữ cảnh vẫn đi qua policy → safety → HITL.** Không có đường tắt tới executor.
4. **Bốn chốt của ADR-025 là mặc định cho mọi hạng mục ghép:** chỉ lượt kế tiếp; TTL 30 s;
   không ghép khi lượt mới tự khớp `control`; kết quả ghép phải có nghĩa.
5. **Fail hướng bỏ sót, không nhận bừa.** Bỏ sót thì tài xế nói lại — phiền. Nhận bừa thì một
   câu nói với người ngồi cạnh thành một hành động thật.
6. **Giả định "mic không tự mở" đã chết.** Wake word (#177) và cửa sổ nghe tiếp (#343) đều đã
   vào `develop`. Mọi tính toán rủi ro dựa trên giả định ấy phải làm lại.
7. **Ghép câu hỏi, không ghép câu trả lời** (mảng RAG) — ADR-015.

## 9. Không nên làm multi-turn

| Chỗ | Vì sao |
|---|---|
| Ngữ cảnh sống qua **restart tiến trình** | ADR-025: một câu hỏi lại sống sót qua restart là cái bẫy, không phải tính năng |
| Lệnh hoãn theo điều kiện xe (A9) | hẹn giờ trên bề mặt an toàn; PR #338 đã bác phiên bản nhẹ hơn |
| Nhớ biến thể xe qua lời nói (C2) | hồ sơ xe đáng tin hơn; đây đúng là lớp lỗi ADR-015 đo được |
| Cho SLM tổng hợp nhiều lượt sổ tay thành một câu | ADR-015 — 4/40 câu gây hiểu lầm, sàn lỗi của cách tiếp cận |

## 10. Bằng chứng còn thiếu

`eval/datasets/agent/v3` có 10 case `clarify` và **tất cả đều đơn lượt** — bộ eval hiện tại
không đo được bất kỳ hạng mục nào ở trên. Trước khi làm A1/A2/A3 cần một dataset case **hai
lượt cùng `session_id`**; khuôn test e2e đã có sẵn ở `tests/test_api/test_ghep_hoi_lai_e2e.py`
trong commit `d108216`.

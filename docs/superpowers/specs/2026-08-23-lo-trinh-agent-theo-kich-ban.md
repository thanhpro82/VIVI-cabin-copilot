# Lộ trình tầng agent — sắp lại theo kịch bản demo

- Ngày: 2026-08-23
- Trạng thái: Đã duyệt (Nhân duyệt kịch bản 23/08)
- **Thay thế** §2 (phân rã 5 sub-project) của `2026-08-21-slm-bo-nao-dinh-tuyen-design.md`
- Đã xong: SP-0 (#243), SP-1 (#232 + #242), SP-2 (#245), SP-2.1 (#249), SP-5 (#252)
- **Đọc §8 → §9 → §10 TRƯỚC.** §3/§4 là bản ghi 23/08; §7 sửa đổi 26/08; §8 trạng thái
  27/08; **§9 và §10 là sửa đổi 28/08 và chúng thắng mọi chỗ lệch.** Các mục cũ giữ lại
  có chủ ý: xoá đi thì mất luôn dấu vết vì sao thứ tự đã đổi ba lần.
- **Đang gác, xem §10.1:** quyết định an toàn của #354 ("PR 2"), và #339.

## 1. Vì sao viết lại

Phân rã cũ đặt mục tiêu là *"hoàn thiện tầng agent"* — một mục tiêu đo bằng độ đầy đủ
của kiến trúc. Nó dẫn tới việc đúng nhưng không dẫn tới **thứ tự** đúng: SP-4 gần xong
trong khi năng lực đầu bài của P0 vẫn chưa chạy dòng nào.

Mục tiêu mới đo bằng một thứ khác: **một chuyến đi kể được thành chuyện trong 4 phút**.
Nguyên tắc kèm theo — *việc nào không mở khoá một lượt trong kịch bản thì không nằm trên
đường găng*. Nó vẫn có thể đáng làm; nó chỉ không được tranh chỗ.

### Kịch bản làm đích (bản rút gọn, để tài liệu này tự đứng)

| Lượt | Người nói | Hôm nay |
|---|---|---|
| 0 | *"Hey VIVI"* | ❌ #177 chưa merge |
| 1 | *"Chào buổi sáng, hôm nay đi làm nhé"* | ✅ 3 141 ms |
| 2 | *"Nóng quá, cho mát xuống chút đi"* | ❌ rơi xuống tra sổ tay |
| 3 | *"Đèn vàng hình cục pin là gì thế?"* | ✅ 1 024 ms (ấm) |
| 4 | *"Đọc tiếp đi"* | ⚠️ chạy nhưng bỏ sót câu |
| 5 | *"Bật điều hòa 22 độ và mở nhạc gì sôi động lên"* | ✅ 3 bước đúng |
| 6 | *"Mở cửa sổ bên lái xuống một nửa"* | ✅ S2, 25 ms |
| 7 | *"Ừ, mở đi"* | ⚠️ chưa kiểm |
| 8 | *(50 km/h)* *"Nóng quá, mở cửa cho thoáng"* | ⚠️ chặn được, không giải thích |
| 9 | *"Tìm quán cà phê gần đây rồi dẫn đường tới đó"* | ❌ không chạy |
| 10 | *"Cảm ơn nhé, tới nơi rồi"* | ✅ 5 513 ms |

*(Bản đầy đủ kèm lời dẫn nằm ngoài repo — tài liệu trình bày, xem `.gitignore`.)*

## 2. Bảy đầu việc ánh xạ vào đâu

| Việc (theo đóng góp) | Thuộc SP nào |
|---|---|
| 1 · POI + dẫn đường | ❌ **không có trong phân rã cũ** → **SP-5 (mới)** |
| 2 · tầng nói: rút khung, sửa `doc_tiep` | ✅ **= SP-3 y nguyên** |
| 3 · lượng định tính (*"mát xuống chút"*) | ❌ **không có trong phân rã cũ** → **SP-6 (mới)** |
| 4 · S3 giải thích lý do | **gộp vào SP-3** — cùng chạm `compose.py`, cùng là chữ nói ra |
| 5 · kiểm phê duyệt bằng giọng | không phải SP — việc **kiểm chứng**, gắn vào SP-3 |
| 6 · wake word | ngoài chuỗi — PR #177, chủ PR xử |
| 7 · độ trễ chitchat | nợ SP-2, không nằm đường găng |

**Và chiều ngược lại, quan trọng hơn:** SP-4 (hợp nhất display/speak, PR #221)
**không mở khoá lượt nào trong kịch bản**. Theo đúng luật ở §1, nó xuống cuối — dù đã
gần xong. Cùng lý do với #217: đã viết rồi, chỉ chờ rebase, nên chi phí thấp và không
bị hạ như việc mới, nhưng cũng không được chen lên trước SP-5.

## 3. Lộ trình

Định nghĩa **hoàn thành** dùng chung cho mọi SP dưới đây, và nó không phải "test xanh":

> **SP xong = lượt demo tương ứng chạy được trọn vẹn trên giao diện thật, người ngoài
> nhóm bấm được, và có một run id trong `eval/results/` đứng sau con số công bố.**

### SP-5 — POI và dẫn đường ★ ưu tiên cao nhất

**Mua:** lượt 9 (Màn 5) — use case đầu bài của P0, hiện không chạy dòng nào.

Khảo sát 23/08 cho thấy việc nhẹ hơn tưởng: **fixture đã có sẵn 6 POI** trong
`src/fixtures/poi.json`, mỗi mục đủ `name`, `category`, `aliases`, toạ độ,
`distance_km`, `eta_min` và cả **`polyline`** để vẽ tuyến. `search_nearby_poi` đã có
trong registry ở mức **S0** (chỉ đọc). Thiếu ba mảnh:

1. `args_model` cho `search_nearby_poi` + **executor** (hiện chỉ là mục registry rỗng);
2. **matcher** cho `"tìm … gần đây"`, `"quanh đây có … không"`, `"đưa tôi về nhà"` —
   đo được: cả ba hiện rơi `default_to_manual`;
3. **ghép hai ý** *tìm* rồi *dẫn đường* thành hai bước — hạ tầng ghép lệnh đã chạy tốt
   sau #225/#227, nên phần này chủ yếu là nối.

**Rủi ro:** đây là SP duy nhất chạm frontend (bản đồ vẽ tuyến). Kiểm sớm rằng
`polyline` hiện được lên bản đồ trước khi làm sâu phần backend.

### SP-3 — tầng nói, tóm tắt, và lời từ chối biết giải thích

**Mua:** lượt 3, 4, 8. Là SP duy nhất đã có sẵn chẩn đoán và số đo từ trước.

1. **Rút khung 72 → 27 ký tự.** Ngân sách thân 167 → 213, phủ 67% → **85%** bản tham
   chiếu, **không tốn thêm một giây nghe nào**. **Chốt 23/08 (Nhân): cắt phẳng câu dẫn** —
   bỏ hẳn vế nhắc lại chủ đề, không giữ riêng cho lượt giọng nói. Đánh đổi đã biết: mất
   phần xác nhận ngầm "tôi nghe đúng chủ đề rồi"; bù lại phụ đề trên màn IVI vẫn hiện
   nguyên câu hỏi, nên tài xế vẫn đối chiếu được.
2. **Sửa `doc_tiep` lấp ngược** — hiện chỉ đi tới, câu đã bỏ qua không bao giờ nghe được.
3. **`BlockKind.LIST` xuống `Evidence`** — cấu trúc đã có ở ingest, bị vứt ở ba tầng; xoá
   được danh sách trắng 30 động từ. Đo được **152 chỗ** trong corpus đang cắt đứt chuỗi bước.
4. **S3 giải thích lý do + đề nghị thay thế** — thay *"trạng thái xe hiện tại không cho
   phép"* bằng *"xe đang chạy 50 km/h nên tôi không mở cửa được, bạn muốn hạ kính thay
   không?"*. Nhỏ nhất trong bốn việc, tác động demo cao nhất.
5. **Quyết số phận PR #230 và #231** trên số của SP-3 — không merge lẻ.
6. **Kiểm phê duyệt bằng giọng** (lượt 7) qua giao diện thật; mở rộng cụm được nhận
   (`"ừ"`, `"mở đi"`, `"được"`) nếu hẹp. Phần lớn là *kiểm*, không phải *viết*.

### SP-6 — lượng tương đối

**Mua:** lượt 2 — *"cho mát xuống chút"*, *"ấm lên tí"*, *"to lên chút"*.

Đây là việc **thật sự mới về cấu trúc**, không phải thêm từ vựng: router hiện **không
đọc trạng thái xe**, nên không có gì để cộng trừ vào. Cần cho matcher truy cập
`vehicle_snapshot` và sinh giá trị tuyệt đối từ giá trị hiện tại. Chạm cùng vùng với
SP-5 (matcher), nên **làm sau SP-5** để tránh đụng nhau.

Ghi chú thiết kế cần chốt khi tới: bước nhảy bao nhiêu cho mỗi miền (nhiệt độ ±2 °C?
âm lượng ±10?), và xử lý thế nào khi đã ở biên.

### SP-4 — hợp nhất display/speak (PR #221)

Không mở khoá lượt nào. Rebase và merge **sau** SP-5/SP-3, khi `compose.py` đã yên.

## 4. Thứ tự và chỗ chạy song song

```
NGAY:      SP-5 (POI)  ──────────────┐
song song: SP-3 (tầng nói)  ─────────┤   ít đụng file nhau:
                                     │   SP-5 = router/tools/executor/frontend
                                     │   SP-3 = compose/speech_policy/tom_tat
SAU SP-5:  SP-6 (lượng tương đối) ───┤   (cùng chạm matcher)
CUỐI:      SP-4 (#221)  ─────────────┘
```

Chuỗi PR: **#249 → #217 (rebase) → SP-5 → SP-3 → SP-6 → #221**. #230/#231 do SP-3 quyết.
Ba làn độc lập (#229 docs, #246 frontend, #248 deploy) merge lúc nào cũng được.

## 5. Việc KHÔNG nằm trên đường găng

Vẫn là nợ, vẫn ghi, nhưng không được tranh chỗ:

- 4 ca lệnh ngầm làm vỡ cổng `bẫy→chitchat` (*"Tối om thế này"*) — prompt đã chạm trần ở
  SP-1, không đuổi tiếp.
- Cổng cho "xác nhận dữ kiện đường xá" (*"Đường này hay ngập ha"* → *"Có đấy…"*).
- Độ trễ chitchat 3–5,5 s.
- 15 câu độc lập (#244) — **quan trọng cho đánh giá, không cho demo**; đừng đổi thứ tự vì nó.

**Một ngoại lệ giữ ưu tiên cao dù không thuộc kịch bản:** hợp nhất hai đường chitchat.
Classifier chấm `control` → planner → union prompt trả `kind: chitchat` → `outcome=chitchat`
**mà không qua node `chitchat`**, tức bỏ qua cả năm lớp cổng, kể cả cổng triệu chứng an
toàn. Đo được ở *"Xe rung lắc quá"*. Đây là lỗ an toàn, phải xong **trước khi bật cờ cho
người dùng** — độc lập với lịch demo.

## 6. Điều kiện bật cờ cho người dùng (ADR-026)

Nhắc lại để không trôi: merge ≠ bật cờ. `SLM_ENABLED` bật cho demo/release cần đủ —
SP-2 xong (đã), bộ đo ba lớp (đã), **hai đường chitchat hợp nhất** (**đã** — #266 merge 26/08), **cấu hình hai
llama-server có biến `SLM_CLASSIFY_ENDPOINT`** (chưa — số 2,79 s hiện đạt bằng script
ghim endpoint tay), và PM/PO review lại.

**Bổ sung 27/08 — một điều kiện MỚI, và nó nặng hơn mấy điều kiện trên:** độ trôi theo
phiên server (§8.6 mục 1). Cùng prompt cho 16/16 lúc server mới và 13/16 sau vài lượt.
Nếu độ trôi ấy là thật thì bật cờ mặc định nghĩa là chất lượng plan giảm dần theo thời
gian sống của tiến trình backend, và **không test nào trong repo bắt được**. Phải đo dài
để xác nhận hoặc bác trước khi #258 merge.

---

## 7. Sửa đổi 26/08 — Routines MVP xen vào, và cái gì lùi lại

### 7.1 Vì sao phải sửa

Ngày 26/08 PM/PO mở epic **Routines MVP — Voice-first personalization** (#270, 30 issue),
trong đó năm issue thuộc tầng agent: #285 (intent preview/run + phân giải tên Routine),
#288 (Routine đã resolve → typed candidate + lời thoại), #299 (intent Dừng/Hủy),
#296 (spike eval barge-in), dưới outcome #274.

Đây là quyết định của PM/PO, có release gate và Go/No-Go riêng, nên nó **không xếp hàng
sau** lộ trình nội bộ này. Việc cần làm là nói rõ nó ăn vào đâu.

### 7.2 SP-7 (cá nhân hoá A+B) bị THAY THẾ, không phải hoãn

Phương án A+B chốt trong thảo luận 25/08 — chào theo tên, và *"đưa tôi về nhà"* — nay
nằm trong epic: địa điểm Nhà/Cơ quan là #273/#283 (BE), UI thiết lập là #284 (FE), phần
nhận câu nói là #285 (agent). Giữ SP-7 song song là dựng hai lần cùng một thứ với hai
chủ sở hữu. **Xoá SP-7 khỏi lộ trình này**; ai tìm nó thì đi theo #270.

### 7.3 Ba chỗ việc đang dở nối thẳng vào epic

1. **#269 trở thành việc CHẶN, không còn là nợ kỹ thuật.** Allowlist hành động của
   Routines gồm *quạt gió*, *đèn cabin*, *navigation Nhà/Cơ quan* — ba trong năm tool
   đang bị giấu khỏi `SLM_UNION_PROMPT` (prompt kê 9, registry có 16). Routine chạy qua
   đường luật thì không sao; câu nói tự nhiên nào rơi xuống planner sẽ hỏng đúng những
   hành động mà epic vừa hứa.
2. **#148 (#217 phần A + #267 phần B) là nền của #285.** Vòng preview →
   *"chạy/đồng ý"* / *"không"* / *"bỏ một bước"* chính là vòng hỏi-lại-rồi-ghép-câu-trả-lời
   mà hai PR ấy dựng. Không có nó thì #285 viết lại cùng một cơ chế lần thứ hai.
3. **Phần còn lại của #223 (`unmet_clauses`) trùng bài toán với #288.** Yêu cầu
   *"báo bước đã chạy, lỗi và chưa chạy"* của epic là cùng một chuyện: biểu diễn kết quả
   **một phần** trong một hợp đồng vốn loại trừ lẫn nhau. Hai nơi tự nghĩ ra hai cách là
   cách chắc chắn để chúng lệch nhau — chốt một lần, dùng cho cả hai.

### 7.4 Thứ tự đang chạy (thay cho chuỗi PR ở §4)

```
1. Dọn đuôi:  #268 → #217 → rebase #267 → merge   (xong là #148 đóng được)
2. #269       ngay sau #268 — rẻ, và đang vô hiệu hoá thành quả #65 lẫn SP-5
3. Routines:  #285 → #288 → #299 ; #296 chờ spike FE #294/#277
4. SP-3 rút gọn: giữ mục 4 (S3 giải thích) + mục 1 (cắt câu dẫn)
5. Lùi:       SP-3 mục 2/3, SP-6, phần còn lại #223, #212, SP-4 (#221), #230/#231
```

Hai chỗ mở khoá được ngay mà không chờ ai: phần **không** chạm contract của #285 — bộ eval
câu preview/run (acceptance của #274 đòi *"eval set đã thống nhất"*, hôm nay chưa có) và
matcher tên Routine + clarification. Phần chạm contract chờ #282/#283.

### 7.5 SP-3 vì sao rút gọn chứ không lùi hẳn

Mục 4 (S3 giải thích lý do) và mục 1 (cắt phẳng câu dẫn) đều **phục vụ epic**: #288 phải
viết lời preview/kết quả **ngắn** và nhất quán, mà ngân sách câu nói hiện bị khung 72 ký tự
ăn mất. Mục 2 (`doc_tiep` lấp ngược) và mục 3 (`BlockKind.LIST`) thuần chất lượng tra sổ
tay, không đụng Routines — nên chúng lùi.

### 7.6 Cái KHÔNG đổi

§1 giữ nguyên: việc nào không mở khoá một lượt thì không tranh chỗ. Epic Routines không
phải ngoại lệ của luật ấy — nó mở khoá một chuỗi lượt mới (preview → chạy → huỷ), nên nó
đứng trên đường găng theo đúng cùng một tiêu chuẩn, không phải vì nó mới hơn.


---

## 8. Trạng thái 27/08 — bản đang chạy

`develop` @ `1477a26`. Suite **2712 passed / 21 skipped**.

### 8.1 Bốn bước đầu của §7.4 đã xong

| bước | việc | kết quả |
|---|---|---|
| 1 | dọn đuôi #268 → #217 → #267 | ✅ merged, **#148 đã đóng** |
| 2 | #269 prompt planner trôi khỏi registry | ✅ #324 merged, **#269 đã đóng** |
| 3 | Routines #285 → #288 | ✅ #328 merged; **#299 chặn bởi BE** |
| 4 | **SP-3 rút gọn** | ⬅ **đang tới lượt** |
| 5 | lùi: SP-3 mục 2/3, SP-6, #223, #212, SP-4 (#221), #230/#231 | chưa |

Kèm hai việc **không có trong §7.4** vì chúng chỉ lộ ra lúc làm:

- **#325** hai bảng args song song → #336 merged, **đã đóng**.
- **cổng `cong_mien_slm`** — sinh ra từ review #324, không phải từ lộ trình.

### 8.2 Việc tiếp theo: SP-3 rút gọn

Đúng bước 4. Hai mục, theo thứ tự:

1. **Mục 4 — S3 giải thích lý do.** *"Xe đang chạy 50 km/h nên tôi không mở cửa được,
   bạn muốn hạ kính thay không?"* thay cho *"trạng thái xe hiện tại không cho phép"*.
   Mua lượt 8. Nhỏ nhất trong bốn việc của SP-3, tác động demo cao nhất.
2. **Mục 1 — cắt phẳng câu dẫn**, 72 → 27 ký tự. Ngân sách thân 167 → 213, phủ 67% →
   **85%**, không tốn thêm một giây nghe nào. Phương án đã chốt 23/08.

Cả hai chạm `compose.py`. Làn ấy **vừa trống** sau khi #305/#315 của @hason0510 merge.

### 8.3 Làn router đã trống, nhưng điều đó KHÔNG đổi thứ tự

@hason0510 đã merge hết PR router (#301, #305, #313, #315, #317). Nên `router.py` và
`compose.py` không còn ai tranh, và ba việc ở dòng "lùi" — **#320** (`"tắt tiếng"`),
phần còn lại **#223** (`unmet_clauses`), **#212** — nay *khả thi*.

**Khả thi không phải là đến lượt.** Luật §1 vẫn đứng: việc nào không mở khoá một lượt
trong kịch bản thì không tranh chỗ. Ghi ra đây vì tôi đã một lần đề xuất ngược lộ trình
đúng vì lý do "làn trống", và lý do ấy không nằm trong bất kỳ tiêu chí nào của §1.

### 8.4 SP-4 (#221): luật cũ vẫn đúng, nhưng có một dữ kiện MỚI

§2 xếp #221 xuống cuối vì nó không mở khoá lượt nào — vẫn đúng.

Dữ kiện xuất hiện **sau** khi lộ trình được viết: **#221 là prerequisite của #260**, tức
nó đang chặn việc của người khác. Luật §1 chỉ cân "mở khoá lượt demo", không cân "chặn
người khác", nên nó không trả lời được ca này.

**Chưa tự quyết.** Cần @thanhpro82 nói #260 có gấp không: gấp thì #221 chen lên có lý do
chính đáng và ghi vào đây; không thì nó ở nguyên bước 5. Hai blocker của #221 không đổi:
rebase, và bỏ fallback `speak_text or response_text` (nó có thể đẩy đoạn RAG dài ra TTS,
phá đúng bất biến mà PR tuyên bố).

### 8.5 Routines: chặn hoàn toàn, và chỗ chặn không nằm ở kỹ thuật

Làn agent đã làm hết phần không phụ thuộc BE (#285, #288, bộ đo `routines-v1` 38 ca).
Bốn việc còn lại đều chờ:

| việc | chờ | trạng thái |
|---|---|---|
| lời thoại preview/kết quả (nửa sau #288) | #290 | OPEN |
| nối matcher vào graph, `needsPreview` | #282 | OPEN |
| bước `navigation` Nhà/Cơ quan | #283 | OPEN |
| #299 cancel intent | #278, #297 | OPEN |
| #296 eval barge-in | #294, #277 | OPEN |

**Và #280 — Product Spec của cả epic — vẫn 0 comment.** 25 issue con treo dưới nó, Go/No-Go
(#300) treo dưới nó. Đây là rủi ro lịch lớn nhất của epic và nó không thuộc quyền làn agent.

### 8.6 Nợ đo mới, sinh ra trong tuần

Ba thứ chưa có trong §5, và cả ba đều đo được chứ không phải suy đoán:

1. **Độ trôi theo phiên server.** Cùng prompt, cùng model, nhiệt độ 0: server **vừa khởi
   động** cho args hợp lệ 16/16, sau 3–4 lượt liên tiếp tụt còn 13/16 (lặp lại được cả
   hai chiều). Nghi `cache_prompt` + KV-reuse. Nếu thật thì **chất lượng plan giảm dần
   theo thời gian sống của tiến trình**, và không test nào trong repo bắt được vì chúng
   đều chạy trên tiến trình mới. **Dính trực tiếp tới #258** (bật SLM mặc định).
2. **Model chọn sai 5/16 tool.** Cổng `cong_mien_slm` chặn được nên không nguy hiểm,
   nhưng tài xế nhận `clarify` thay vì hành động. Đã thử hai hướng và **cả hai bị đo bác**:
   thêm tên tool (0 tác dụng), thêm ví dụ few-shot (11/16 không đổi một ca nào).
3. **Nguồn độc lập cho bộ đo.** `routines-v1` 38/38 `tu_viet`; #244 vẫn 0/15 câu độc lập.
   Cả hai là tripwire hồi quy, **không** phải thước khái quát hoá — mọi báo cáo phải kèm
   dòng ấy.

### 8.7 Một nợ hạ tầng, ngoài phạm vi agent

CI đỏ **ba lần trong tuần** vì cùng một lỗi ở bước `pip install` (`gzip … incorrect header
check`, rồi `IncompleteRead`), chưa chạm lint hay test. Thêm `--retries` vào `ci.yml` là
một dòng và cắt hẳn lớp báo động giả này. Chưa làm vì nó không thuộc PR nào đang mở.

### 8.8 Cái KHÔNG đổi

§1 vẫn là luật: **việc nào không mở khoá một lượt trong kịch bản thì không nằm trên đường
găng**. Hai lần lộ trình đổi thứ tự trong tuần (§7 vì epic Routines, §8 vì bốn bước đầu
xong) đều **không** phải ngoại lệ của luật ấy — chúng là luật ấy áp lên dữ kiện mới.


---

## 9. Sửa đổi 28/08 — SP-3 mục 1 bị một phép đo BÁC

### 9.1 Kết quả

**Không làm "cắt phẳng câu dẫn".** Lộ trình dự đoán phủ 67% → 85%; đo thật thì cắt phẳng
làm số **tệ đi**.

Bốn run trên cùng máy, bộ đo tất định (hai run đầu cho output giống hệt từng byte):

| # | bộ đo | câu dẫn | chạm tới câu trả lời | nói p50/p95 |
|---|---|---|---:|---|
| A | ngân sách 240 (như cũ) | cũ, p50 37 ký tự | 50,0% (trúng 20) | 11,0 / 11,7 s |
| B | ngân sách 240 (như cũ) | **phẳng**, 11 ký tự | 50,0% (trúng 20) | 11,0 / 11,7 s |
| C | **ngân sách thật** | **phẳng**, 11 ký tự | 57,5% (trúng 23) | 10,2 / 11,0 s |
| D | **ngân sách thật** | cũ, p50 37 ký tự | **65,0% (trúng 26)** | 9,3 / 10,3 s |

Run id: `rag/20260827T171914Z`, `…172314Z`, `…172453Z`, `…172523Z`.

**C so với D là phép so đúng** (chỉ khác câu dẫn): giữ nguyên **hơn** cắt phẳng 7,5 điểm,
và nói ngắn hơn ~1 giây. Nên mục 1 **đóng lại, không làm**.

### 9.2 Vì sao ngược trực giác — và đây mới là bài học

Cắt câu dẫn trả thêm 26 ký tự cho phần thân. Nhưng bộ chọn lấy **trọn câu**: thêm ngân
sách nghĩa là thêm **một câu nữa** vào chuỗi nói, và câu thêm vào thường không phải câu
mang đáp án — nó chỉ làm loãng, và làm tài xế nghe lâu hơn.

Tức giả định ngầm của lộ trình — *"ngân sách thân nhiều hơn thì phủ nhiều hơn"* — sai ở
đúng chỗ nó tưởng là hiển nhiên.

### 9.3 Một bug của bộ đo, lộ ra nhờ chính việc này

Run A/B giống hệt nhau **từng byte** trên cả 40 ca. Truy ra: `rag/evaluate.py` gọi
`chon_cau_de_noi` **không truyền `max_chars`**, tức dùng trọn `MAX_SPOKEN_CHARS`, trong
khi `compose_node` trừ câu dẫn ra trước. Bộ đo chưa bao giờ chạm tới câu dẫn.

Tôi đoán chiều lệch sẽ là *"sản phẩm tệ hơn bộ đo báo"*. **Ngược**: 50,0% → 65,0% khi sửa
cho đúng ngân sách thật. Bộ đo cũ vừa sai chiều vừa che mất §9.2.

Đã sửa (giữ lại), nên mọi con số RAG từ đây **không so được** với các run trước 28/08.

### 9.4 Đổi gì trong lộ trình

- SP-3 mục 1 — **bỏ**, có run id đứng sau.
- Mục 4 (S3 giải thích) — **xong**, #338.
- SP-3 còn mục 2 (`doc_tiep` lấp ngược) và mục 3 (`BlockKind.LIST`), vẫn ở dòng lùi §8.
- Bước 4 của §7.4 coi như **đóng**. Việc tiếp theo lấy từ dòng "lùi" của §8.1, và lần
  này thứ tự nên do PM/PO chốt vì không còn mục nào mở khoá một lượt demo mới.

### 9.5 Điều nên rút ra cho các mục còn lại

Mục 2 và mục 3 của SP-3 cũng đang mang những con số dự đoán (*"152 chỗ trong corpus"*,
*"phủ 67% → 85%"*) chưa ai kiểm bằng một run. Sau ca này: **đo trước, làm sau** — và khi
đo, kiểm luôn rằng bộ đo có thật sự chạm tới thứ mình sắp đổi hay không.


---

## 10. Sửa đổi 28/08 (2) — multi-turn vào lộ trình, và một quyết định đang gác lại

### 10.1 Hai việc đang GÁC, ghi ở đây để không quên

**(a) "PR 2" của #354 — quyết định an toàn cho `CO_THE_GHEP`.** PR #358 chỉ khôi phục
phần B và dựng hàng rào; ba hướng ở #354 (không auto-listen cho `clarify` / có nhưng
phải xác nhận / thu hẹp `CO_THE_GHEP` khi mic mở) **chưa làm**, chờ @thanhpro82.

Gác được vì đo được: giả định của ADR-025 *vẫn đúng hôm nay* (`clarify` luôn
`has_more_to_read=False`, wake word sau cờ mặc định `false`), và
`test_clarify_khong_bao_gio_mo_mic_tu_dong` canh nó. **Mở lại khi**: PM/PO trả lời,
**hoặc** ai đó cho cửa sổ nghe tiếp mở sau `clarify` — lúc ấy test đỏ và đây là chỗ tra.

Kèm một mục nhỏ cùng chỗ: `missing_door_side` cố ý **không** vào `CO_THE_GHEP` (cửa là
S2/S3), ghi trong `KHONG_GHEP_DUOC`. Cũng chờ cùng một chữ ký.

**(b) #339 — đề nghị hành động thay thế khi bị chặn S3.** Tách khỏi #338 vì lời đề nghị
cần một flow follow-up. Xem 10.3: nó **dùng chung cơ chế** với mục multi-turn số 1, nên
đừng làm riêng.

### 10.2 Ba ngõ cụt multi-turn (#355), đo được chứ không suy đoán

@hason0510 quét toàn bề mặt và tìm ra 14 chỗ; ba chỗ dưới đây chưa có issue nào theo dõi.
Tôi đo lại chỗ số 1 bằng graph thật, xác nhận:

```
lượt 1  "Bật điều hòa được không"  -> offer, plan SẴN CÓ: set_hvac_power{enabled:True}
        VIVI: "Tôi có thể bật điều hòa. Bạn có muốn tôi thực hiện không?"
lượt 2  "Có" / "Ừ" / "Đồng ý"      -> grounded_refusal, 0 lệnh
        VIVI: "Tôi không tìm thấy thông tin này trong sổ tay xe."
```

| # | ngõ cụt | ước lượng của #355 | ghi chú |
|---|---|---:|---|
| 1 | **đồng ý với `offer` của chính xe** | ~90 dòng | plan đã dựng sẵn; bộ đọc "có/không" đã chạy cho HITL |
| 2 | chọn một mục trong danh sách POI vừa đọc | ~150 dòng | cần nhớ **danh sách có thứ tự**, không phải chuỗi |
| 3 | câu hỏi nối tiếp về sổ tay | — | ghép **câu hỏi**, tuyệt đối không ghép câu trả lời (ADR-015) |

### 10.3 Một cơ chế phục vụ hai issue — đừng làm riêng

Mục 1 và **#339** là cùng một thiếu sót: hệ không có chỗ nào lưu *"xe vừa đề nghị một
hành động, đang chờ trả lời"*. #148 phần B giải quyết *"xe hỏi thiếu một slot"* — khác
hẳn: điền nốt chỗ trống của **cùng một lệnh**, so với chấp nhận **một lệnh đã dựng sẵn**.

Nên: dựng **một khe `offer` đang treo** trong `AgentState`, dùng chung. Làm riêng hai lần
thì `"ừ"` sau câu hỏi slot và `"ừ"` sau lời đề nghị sẽ có hai đường xử lý — đúng cách để
chúng lệch nhau.

Mục 1 rẻ vì mọi mảnh đã có: `offer` **đã mang** `candidate_plan` hợp lệ,
`voice_intent.doc_tra_loi_co_khong` đã đọc "có/không" cho HITL, và `as_candidate_plan` đã
xử lý chuyện plan bị checkpoint biến thành `dict`.

### 10.4 Việc phải làm TRƯỚC: bộ đo hai lượt

Bộ đo hiện có 10 ca `clarify` và **tất cả đều đơn lượt** — không hạng mục nào ở 10.2 được
đo. Làm trước khi sửa, vì §9 vừa dạy đúng bài này: SP-3 mục 1 bị bác bởi một phép đo, và
bộ đo lúc ấy còn **không chạm tới** thứ tôi định sửa.

Cụ thể: `eval/datasets/agent/multiturn-v1/` — mỗi ca là một **cặp lượt** cùng `session_id`,
nhãn là kết cục của lượt hai. Ba lớp: đồng ý `offer`, chọn mục trong danh sách, hỏi nối
tiếp sổ tay. Và như mọi bộ đo tự viết: ghi rõ `source: tu_viet` là **tripwire**, không phải
thước — nợ nguồn độc lập gộp vào #244.

### 10.5 Khuôn phải theo (chép từ #355, không sửa)

1. Router giữ tất định, không đọc trạng thái (ADR-006/010). Ngữ cảnh giải ở **node**;
   router chỉ được gọi lại với một chuỗi khác.
2. Ngữ cảnh sống qua lượt phải khai trong `AgentState` **và** nằm ngoài `_PER_TURN_RESET`.
   Thiếu một trong hai thì nó biến mất im lặng — đã xảy ra thật với `speak_text`.
3. Mọi lệnh sinh từ ngữ cảnh vẫn đi qua policy → safety → HITL. **Không có đường tắt tới
   executor, kể cả khi xe là bên đã hỏi trước.**
4. Fail hướng bỏ sót, không nhận bừa.

### 10.6 Thứ tự đề xuất, và nói thẳng một điều

```
1. bộ đo multiturn-v1 (ba lớp, cặp lượt)        ← trước, không thương lượng
2. khe `offer` treo  ->  đóng #355 mục 1; hạ tầng cho #339 ← xem §11.5
3. #355 mục 2 (chọn trong danh sách POI)
4. #355 mục 3 (hỏi nối tiếp sổ tay)
```

**Điều phải nói thẳng:** không mục nào ở đây mở khoá một **lượt mới** trong kịch bản demo,
nên theo luật §1 chúng không tự động lên đường găng. Nhưng chúng nằm trên một trục khác mà
§1 không cân: *"xe tự hỏi rồi tự bịt tai"* là lỗi **ban giám khảo có thể vấp phải ngẫu
nhiên**, ở bất kỳ lượt nào, và nó phá lòng tin nhanh hơn một tính năng thiếu. Trục ấy nên
được cân, nhưng cân nó là việc của PM/PO — tôi ghi ra chứ không tự xếp.

Ba việc ở dòng "lùi" của §8.1 (#320, `unmet_clauses` của #223, #212) vẫn ở nguyên chỗ;
multi-turn **không** đẩy chúng xuống, vì chúng vốn đã không tranh chỗ.


---

## 11. Sửa đổi 29/08 — mục 1 và 2 của §10.6 đã xong, và #363 gỡ chỗ đang gác

### 11.1 Đã làm

**Mục 1 — bộ đo `multiturn-v1`.** 19 ca, 39 lượt, chảy qua một state dùng chung ở mức
`route_node` (tất định, không LLM, không MQTT). `--mode multiturn` ghi run bất biến vào
`eval/results/agent-multiturn/`. Mang mốc `moc_2908` và hai con số đọc cùng nhau: `da_sua`
(tiến độ) và **`di_lui` phải bằng 0** — cơ chế giống `bao-loi-2408`.

**Mục 2 — khe `offer` treo.** `src/agents/loi_de_nghi.py` + cổng ở `nodes/route.py`.

```
10/19  ->  16/19   khe `offer` treo (cơ chế)
16/19  ->  17/19   nới bảng từ chối: "khỏi", "không cần"
```

`di_lui` = 0 ở cả hai bước; 5 ca `an-toan` không nhúc nhích. Suite 2831 → 2867.

Ba điều đáng ghi lại, vì chúng là chỗ dễ làm sai:

1. **Plan không được dựng lại.** Lượt "Có" trả về **đúng object** `CandidateActionPlan`
   mà router đã dựng ở lượt trước và xe đã đọc to thành lời. Dựng lại nghĩa là route
   chuỗi `"Có"`, mà chuỗi ấy không mang nội dung nào.
2. **Không có cổng an toàn nào bị đi vòng.** Vẫn là `CandidateActionPlan` (không có
   `safety_level`), nên `validate_args`, phân loại S0–S3 và HITL chạy nguyên. `route_source`
   giữ nguồn của plan gốc vì `policy.py:142` đọc trường ấy.
3. **Không có bảng từ thứ hai.** Dùng thẳng `voice_intent.doc_tra_loi_co_khong`, vốn đã
   đủ chặt: `"hai"` → `None`, `"Ừ mở kính"` → `None`. Nới nó ra là mở đúng lỗ mà §10.2
   ghi là nguy hiểm nhất.

### 11.2 #363 gỡ chỗ §10.1 đang gác — và nó chờ chính bộ đo vừa làm

§10.1 gác nhánh `clarify` với điều kiện mở lại: *"khi PM/PO trả lời, hoặc ai đó cho cửa
sổ nghe tiếp mở sau `clarify`"*. **#363 là câu trả lời ấy**, và nó chốt một hướng thứ ba
mà §10.1 không nêu: không phải mở tự do, cũng không phải giữ đóng — **auto-listen ngắn
3–5 giây kèm mẫu ngữ pháp cứng** cho đúng slot đang thiếu, không khớp thì NO_EXEC.

Điểm đáng chú ý: #363 **không** dùng confidence, vì đo ra là hệ thống không có tín hiệu
ấy (`voice.py` hard-code `0.0`; `contracts.py` để `1.0`). Cùng một kỷ luật với §9 — bác
một hướng nghe xuôi bằng phép đo chứ không bằng lý lẽ.

#363 ghi rõ nó **chờ bộ đo hai lượt của #355**. Bộ đo ấy nay đã có, nên #363 hết chặn.
Nó cần thêm ba việc mà PR này cố ý không làm:

- một lớp ca `clarify-auto-listen` trong `multiturn-v1` (mẫu khớp → chạy; `"hai giờ nhé"`
  → NO_EXEC);
- tín hiệu NO_EXEC cho FE đóng mic — hình dạng chưa có, và nó là hợp đồng với FE;
- **mở lại ADR-025** và sửa `test_clarify_khong_bao_gio_mo_mic_tu_dong`. Test ấy còn xanh
  sau PR này có chủ ý: nó là việc của #363, và nó vẫn đang khoá đúng giả định của ADR-025
  cho tới khi ADR ấy được sửa.

`missing_door_side` vẫn nằm ngoài phạm vi ghép (S2/S3) — #363 ghi rõ không mở lại, nên
mục ấy của §10.1 **hết gác và được chốt là giữ nguyên**.

### 11.3 Còn nợ, đo được

**Luật `offer` của router chưa phủ "có" đứng đầu câu.** Hai ca `offer-phu-song` trong
`multiturn-v1` còn `hong`, và chúng hỏng ở **lượt 1**, trước khi cơ chế của PR này có
chỗ chạy:

```
"Có mở được cốp không"       -> not_control/manual_question   (mong: offer)
"Có thể bật điều hòa không"  -> not_control/manual_question   (mong: offer)
```

Cả hai đều là dạng hỏi rất tự nhiên. Sửa nó là sửa `_run_matchers` trong `router.py` —
file có bán kính nổ lớn nhất repo — nên tách issue riêng chứ không gói vào PR cơ chế.
Bộ đo giữ chúng ở `hong` để chúng không biến mất khỏi tầm mắt.

### 11.4 Thứ tự sau PR này

```
0. POI mục 2a — lượt hỏng mà vẫn nói           ← SỬA LỖI, xem §11.6; đứng trước tất cả
1. #363 (auto-listen có rào chắn sau clarify)   ← hết chặn, đã có bộ đo
2. #368 luật `offer` phủ "có" đầu câu           ← tách khỏi router work khác
3. #355 mục 2b (nhớ danh sách POI có thứ tự)    ← chỉ có nghĩa SAU mục 0
4. #355 mục 3 (hỏi nối tiếp sổ tay)             ← khó nhất, chưa có chỗ lưu chủ đề
5. #339 phần còn lại                            ← chờ chữ ký `percent`, xem §11.5
```

Điều §10.6 nói thẳng vẫn đúng nguyên: không mục nào mở khoá một **lượt demo mới**. Nhưng
#363 có mang thêm một thứ §10.6 chưa có — **một quyết định PM/PO đã ký**, nên nó không
còn phải chờ ai cân trục nữa.

### 11.5 Đính chính — §10.3 nói quá về #339, và phép đo cho thấy sai chỗ nào

§10.3 viết *"#339 và #355 mục 1 là **cùng một** thiếu sót"*. @thanhpro82 bác ở #367, và
đo lại thì đúng — nhưng nó sai theo một kiểu cụ thể hơn cả mô tả trong review.

Acceptance thật của #339:

```
"Mở cửa bên lái" @ 45 km/h  ->  đề nghị "hạ kính bên lái"  ->  "Ừ"  ->  set_window_position
```

PR #367 làm được **mũi tên thứ hai** và chỉ mũi tên ấy. Hai mũi tên còn lại vướng hai
chuyện khác hẳn, đo được:

```
"Mở cửa bên lái"        -> control/deterministic_rule [set_door_state]   <- KHÔNG phải blocked
"Hạ kính bên lái"       -> clarify/missing_window_position               <- KHÔNG có plan để đề nghị
"Hạ kính bên lái 30%"   -> control/deterministic_rule [set_window_position]
```

**(a) Lời đề nghị thay thế không thể sinh ở router.** Router **không đọc trạng thái xe**
(ADR-006/ADR-010), nên với nó `"Mở cửa bên lái"` là một lệnh hợp lệ; chữ "chặn" chỉ xuất
hiện ở `policy.py`, sau đó. Khe treo của #367 nằm ở `route_node`, tức **trước** chỗ biết
mình bị chặn. Muốn có đề nghị thay thế thì phải sinh nó ở tầng policy/compose và nạp
ngược vào khe — một đường dây mới, không phải một tham số mới.

**(b) `percent` là quyết định sản phẩm, không phải chi tiết cài đặt.** `"hạ kính bên lái"`
trần ra `clarify` vì thiếu `percent`, nên **không có plan nào để đề nghị**. Đề nghị một
việc thì phải nói rõ việc ấy là gì — hạ 30%? 50%? Hạ hẳn? Chọn hộ tài xế một con số rồi
đọc to nó ra là chỗ cần chữ ký PM/PO, không phải chỗ tự quyết.

Nên #339 **vẫn mở**, và §10.6 mục 2 phải đọc là *"đóng #355 mục 1, dựng hạ tầng cho #339"*.
Bài học giữ lại từ §10.3 vẫn đúng nguyên: đừng làm hai đường xử lý cho tiếng "ừ". Chỗ sai
là tôi đã tính hai issue cùng **một** khối lượng công việc chỉ vì chúng dùng chung một
mảnh cơ chế.

### 11.6 Đo lại ngõ cụt 2 và 3 — và mục 2 **không phải** thứ #355 mô tả

§10.2 ước lượng mục 2 là *"~150 dòng, cần nhớ danh sách có thứ tự"*. Chạy graph thật thì
nó không phải một chỗ thiếu ngữ cảnh — nó là một **lượt đã hỏng mà vẫn nói như thành công**:

```
"Tìm các quán cà phê gần đây"
   outcome = validation_denied      intent = poi_search
   NÓI RA: "Tôi tìm được 2 chỗ: Cà phê Bình Minh cách 3,65 km,
            Highlands Coffee Nguyễn Trãi cách 5,6 km. Bạn muốn đi chỗ nào?"
"Cái đầu tiên"
   -> grounded_refusal, "Tôi không tìm thấy thông tin này trong sổ tay xe."
```

Nguyên nhân: `search_nearby_poi` nằm trong `KHONG_CHO_DUONG_PLAN`, nên plan chết ở
`validate_args` với `tool_not_allowed`. Nhưng `compose` rẽ theo **`intent`** trước khi
đọc `outcome`, nên nó vẫn đọc danh sách và vẫn **hỏi lại một câu**.

Đó là ba lỗi chồng nhau, và lỗi nặng nhất không nằm ở multi-turn:

1. **Xe đặt một câu hỏi mà nó không có chỗ nhận câu trả lời** — đúng lớp lỗi #338 đã bỏ
   lời đề nghị "hạ kính" để tránh, nay tái diễn ở chỗ khác.
2. **Trace nói lượt hỏng, tài xế nghe lượt thành công.** Ai đọc `/traces` để tìm lỗi sẽ
   thấy `validation_denied` và không hiểu vì sao người dùng không phàn nàn.
3. Chỉ **sau khi** sửa hai chỗ trên thì "nhớ danh sách có thứ tự" mới là việc có nghĩa.

Nên mục 2 phải tách đôi: **(2a)** đóng khoảng vênh `intent`-vs-`outcome` ở compose và cho
`search_nearby_poi` một đường thực thi thật (hoặc thôi nói ra danh sách), rồi **(2b)** mới
tới khe nhớ danh sách. (2a) là **sửa lỗi**, không phải tính năng multi-turn, và nó nên
đứng trước mọi mục còn lại của §11.4.

**Mục 3 — hỏng im lặng, không hỏng ồn ào:**

```
"Chế độ Camp Mode là gì"   -> manual_question
"Còn chế độ nào nữa không" -> manual_question        <- truy hồi lại bằng CHÍNH câu này
"Áp suất lốp bao nhiêu"    -> tire_pressure_all
"Còn lốp sau thì sao"      -> default_to_manual      <- mất sạch ngữ cảnh lốp
```

Không lượt nào báo lỗi. Lượt hai của ca đầu **vẫn đi tra sổ tay**, nhưng tra bằng một câu
không mang chủ đề nào (*"còn chế độ nào nữa không"*), nên nó trả về một đoạn về thứ khác —
đúng lớp lỗi ADR-015 ghi. Ca thứ hai còn rõ hơn: `tire_pressure_all` → `default_to_manual`,
ngữ cảnh "lốp" bốc hơi hoàn toàn.

Khuôn §10.5 mục 3 vẫn chặn đúng chỗ nguy hiểm: ghép **câu hỏi**, tuyệt đối không ghép câu
trả lời. Nhưng ước lượng "—" của #355 là đúng: đây là mục khó nhất trong ba mục, vì nó
phải quyết *"câu này nối tiếp chủ đề nào"* mà không có chủ đề nào được lưu ở đâu cả.

### 11.7 `percent` của #339 đã có người chốt — và con số ngược với chữ

@HVNhan-Relieq chốt 29/08: **tài xế không nói gì thì hiểu là hạ hết xuống.** Cần
@thanhpro82 ký nhận vì chính anh nêu điểm này ở #367.

Cái bẫy nằm ở chỗ dịch câu ấy thành con số. `percent` đo **độ mở**, không đo độ hạ:

```
"Mở hết kính bên lái"   -> percent 100     mở toang
"Đóng kính bên lái"     -> percent 0       đóng kín
```

Nên *"hạ hết xuống"* là **`percent: 100`**, không phải `0`. Viết theo nghĩa đen của chữ
"hạ… xuống" thì ra `0` — tức **đóng kín cửa sổ** cho một tài xế vừa xin thoáng khí, mà
bối cảnh #339 là xe **đang chạy** và cửa vừa bị chặn. Đây là loại lỗi mà test đọc qua
vẫn thấy hợp lý, nên nó phải được viết ra ở đây chứ không nằm trong đầu ai.

**Hổng liền kề, đo được:** `_MAXIMUM_PHRASES` (`router.py:126`) có `"mở hết"`, `"hết cỡ"`,
`"hết mức"`, `"hoàn toàn"`, `"tối đa"`, `"toang"`, `"kịch"` — nhưng **không** có
`"hạ hết"` hay `"xuống hết"`:

```
"Hạ hết kính bên lái"        -> clarify/missing_window_position
"Hạ kính bên lái xuống hết"  -> clarify/missing_window_position
```

Tức đúng cách nói mà quyết định trên vừa lấy làm mặc định thì router không hiểu khi tài
xế **nói ra thành lời**. Sửa nó cùng làn với #368 (cả hai đều là nới từ vựng trong
`router.py`, cùng bộ đo, cùng ràng buộc "không được biến câu hỏi thành lệnh").

### 11.8 Xong §11.4 mục 1 (#363) — và thứ tự còn lại

`src/agents/mau_slot.py` + lối ra NO_EXEC ở `route_node` + cờ `mo_mic_ngan` trên
`assistant.response`. ADR-025 đã có mục sửa đổi 29/08: giả định *"sau clarify mic không
tự mở"* **hết hiệu lực**, thay bằng chốt thứ năm.

| | ca đạt | `clarify-rao-chan` | `di_lui` |
|---|---:|---:|---:|
| trước | 26/33 | 9/14 | 0 |
| sau | **31/33** | **14/14** | **0** |

Suite 2972 → 3055.

**Nửa FE chưa làm và cố ý tách:** đọc `mo_mic_ngan` để mở mic 3–5 s, đóng khi lượt sau về
`manh_khong_khop_mau`. #363 ghi rõ nó là issue riêng. Backend **không** phụ thuộc vào nửa
ấy — rào chắn chạy trên mọi lượt, nên cờ chỉ là lời mời chứ không phải một nửa của cổng
an toàn. Hệ quả: PR này đứng một mình vẫn **sửa một lỗi đang có**, không chỉ rào cho một
tính năng sắp có.

**Thứ tự còn lại:**

```
0. POI #371 — lượt hỏng mà vẫn nói          ← đã giao @hason0510
1. ~~#363 auto-listen có rào chắn~~          ← XONG (nửa BE)
1b. ~~nửa FE của #363~~                      ← XONG (#364, đóng bằng #387 + bộ đo `clarify-auto-listen`)
2. #368 luật `offer` phủ "có" đầu câu, gộp `"hạ hết"`/`"xuống hết"`
3. #355 mục 2b (nhớ danh sách POI)           ← chờ mục 0
4. #355 mục 3 (hỏi nối tiếp sổ tay)          ← khó nhất
5. #339 phần còn lại                         ← chờ chữ ký `percent = 100`
```

---

## 12. Sửa đổi 29/08 (2) — cửa sổ nghe tiếp, và trọng số đặt sai đã được sửa

Spec: `2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md` · Plan: `plans/2026-08-29-cua-so-nghe-tiep.md`
· ADR-028 · 8 task, 60 bước, thực thi inline 29/08.

### 12.1 Trọng số §10.6 đặt sai, và phép đo sửa nó

@HVNhan-Relieq hỏi một câu làm tôi phải đo lại thay vì làm tiếp: *"nếu chỉ cần giảm bớt
Hey VIVI thì kéo dài thời gian mic bật là được rồi?"*

```
bao-loi-2408  control 89.6%   clarify 1.3%    -> xe chờ trả lời 1/77
manual/v1     not_control 98.3%  offer 1.7%   -> xe chờ trả lời 1/60
```

**~98% lượt là tự chứa.** Bộ máy ngữ cảnh đa lượt phục vụ 1–2%; mic tự mở lại phục vụ
~89%. §10.6 xếp thứ tự theo trục sai, và §12 này là bản sửa.

### 12.2 Bốn phanh — vì lỗ mà câu hỏi thứ hai của anh ấy chỉ ra

*"Cửa sổ mở sau mọi lượt thì làm sao tắt?"* — `FOLLOW_UP_WINDOW` chỉ có hai lối ra, và
lối duy nhất là 6 giây im lặng. `hasMoreToRead` **tự cạn**; bỏ nó là bỏ luôn phanh.

Hậu quả tệ nhất **không** phải chạy nhầm lệnh mà là xe **chen vào cuộc nói chuyện của
người**. Bốn phanh + luật im lặng, chi tiết ở ADR-028.

### 12.3 Bốn lần plan bị chính phép đo sửa lại

Ghi ra vì đây là giá trị thật của việc thực thi thay vì đọc thuộc:

1. **Task 2** — luồng POI của Sơn (#371 + #355 mục 2b) là một lượt "xe hỏi và chờ" mới mà
   plan chưa biết.
2. **Task 3** — `"cảm ơn"` phải **bỏ** khỏi câu giải tán: nó là ca của `chitchat-v1`, và
   thêm nó vào bảng từ chối là dạy cổng HITL đọc lời cảm ơn thành lời bác một lệnh S2.
3. **Task 4** — có **hai** chỗ đọc `speak_text`, không phải một. Sửa mỗi payload thì WS im
   mà **loa vẫn đọc**.
4. **Task 8** — script đọc `get_trace_store()` không chạy được: đó là biến toàn cục của
   tiến trình.

### 12.4 Lỗi nặng nhất, và unit test không bắt được nó

```
"Camp Mode là gì" -> outcome=grounded_answer -> ĐÓNG mic
```

Xe trả lời được một câu hỏi mà cửa sổ vẫn đóng. Tôi giả định câu trả lời sổ tay ra
`outcome="not_control"`; thực tế ra `grounded_answer`. Bảng thật có **22 outcome**, thiết
kế biết **4**. Unit test xanh vì **chính tôi viết state theo trí nhớ** — đúng cái bẫy
`real.citations.test.ts` đã cảnh báo. Chỉ giọng người thật qua WS thật mới lộ ra.

Khoá bằng `test_moi_outcome_deu_duoc_phan_loai_tuong_minh`: không còn "mặc định im lặng".

### 12.5 Thứ tự còn lại, và cổng cho nó

```
1. ~~nửa FE của #363 — auto-listen sau clarify~~   ← XONG (#364, đóng bằng #387 + bộ đo `clarify-auto-listen`)
2. #368 luật `offer` phủ "có" đầu câu, gộp `"hạ hết"`/`"xuống hết"`
3. #386 thêm job CI cho frontend               ← 515 test chưa từng được gác
--- CỔNG: chạy `scripts/do_phan_bo_luot.py` trên lưu lượng thật ---
4. #355 mục 3 (hỏi nối tiếp sổ tay)            ← chỉ làm nếu ≳10%
5. #339 phần còn lại                           ← chờ chữ ký `percent = 100`
```

`#371` và `#355 mục 2b` đã xong (Sơn). Phép đo cổng **chưa chạy được**: `GET /traces` nằm
ở `feat/dashboard-ky-su-nhat-ky-ben`, chưa merge.

**Sửa đổi 30/08 — mục 1 xong, và không phải bằng cơ chế riêng.** #364 (issue mở sau khi
mục này viết) đóng đúng khoản "nửa FE của #363" — nhưng không viết một cửa sổ 3–5 giây
riêng cho `clarify` như dự tính ban đầu ở mục này, vì cơ chế đó **đã có sẵn**: PR #387/
ADR-028 (§12 trên) tổng quát hoá cờ `moMicNgan` cho mọi outcome đủ điều kiện, `clarify`+
`CO_MAU` chỉ là một trong số đó. Việc #364 thật sự làm là thêm bằng chứng đo được riêng
cho đúng cặp này (nhóm `clarify-auto-listen`, `eval/datasets/agent/multiturn-v1`) và đóng
`ADR-025` — không có thay đổi FE nào. Xem addendum 2026-08-30 ở cuối `ADR-025`.

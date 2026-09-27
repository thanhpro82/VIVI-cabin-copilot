# Routines bằng giọng nói — làn Agent của epic #270

- Ngày: 2026-08-30
- Làn: **Agent** (`HVNhan-Relieq`). BE = `hason0510`, FE = `danggiap123`, PM/PO = `thanhpro82`
- Issue: [#274](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/274) (preview/chạy),
  [#299](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/299) (cancel handoff),
  [#296](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/296) (spike eval barge-in),
  epic [#270](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/270)
- Plan: `docs/superpowers/plans/2026-08-30-routines-bang-giong-noi.md`

## 1. Hiện trạng, đo được — không suy từ mô tả issue

Epic #270 ghi *"voice-first để preview và chạy"*. Đo trên `develop` @ `fd4e732`, qua graph thật:

```
"Chạy routine Đi làm"        ->  "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Routine Về nhà gồm những gì"->  "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Xem trước routine Thư giãn" ->  "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Dừng lại"                   ->  "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Hủy routine"                ->  "Tôi không tìm thấy thông tin này trong sổ tay xe."
"Bắt đầu Đi làm"             ->  "Về bắt đầu Đi làm, sổ tay ghi: Chọn một tùy chọn…"
```

**Đường giọng nói tới Routines không tồn tại.** Sáu câu, sáu lần tra sổ tay — kể cả
`"Dừng lại"`, tức lệnh **hủy**, thứ an toàn nhất trong nhóm.

### Cái đã có, và cái chưa nối

| mảnh | trạng thái |
|---|---|
| `src/agents/routines.py` — bảng dịch 9 hành động → `CandidateActionPlan` | ✅ **BE đang dùng** (`routines_store`, `routine_execution` đều nhập) |
| `src/agents/routines_intent.py` — `doc_y_dinh()`, `phan_giai_ten()` | ⚠️ **không ai gọi**, 0 call site |
| `src/agents/router.py` | ❌ **không có một chữ `routine` nào** |
| BE: `POST /routines/{id}/run`, `POST /routine-executions/{id}/cancel` | ✅ có |
| `routines_store.list_routines(user_id)` | ✅ có |
| `routine_execution.bat_dau(...)`, `huy(user_id, execution_id)` | ✅ có |

Nên việc của làn Agent **không phải viết mới** — hai module đã có và đã có test. Việc là
**nối chúng vào đường đi của một lượt nói**, và đó là toàn bộ khoảng cách giữa "epic ghi
voice-first" và "đo ra sáu lần tra sổ tay".

## 2. Ranh giới sở hữu — và vì sao nó quyết định kiến trúc

#299 ghi rõ: *"Sở hữu nhận diện cancel intent và typed handoff tới BE contract đã chốt.
**Không tự hủy executor**, không điều khiển audio/TTS hoặc UI."*

Nên làn Agent dừng ở chỗ sinh ra một **ý định có kiểu**. Việc thực thi — admission, safety,
HITL, fail-fast, cancellation lifecycle — là của BE và **đã xong**. Đây không phải chuyện
lịch sự giữa hai người: `routine_execution.bat_dau` chứa ba cổng admission chạy **trước**
khi có hàng nào trong bảng, và `huy` idempotent qua ba đường. Dựng lại logic ấy ở làn Agent
là dựng một bản thứ hai chắc chắn sẽ lệch.

## 3. Quyết định

**Router nhận ra ý định Routine và trả một disposition mới; node thực thi gọi thẳng service
của BE trong cùng tiến trình.**

### 3.1 Vì sao gọi service, không gọi HTTP

Agent và BE chạy **cùng một tiến trình** (`src/serve.py`). Gọi `POST /routines/{id}/run` từ
trong graph là tự gọi HTTP vào chính mình: thêm một vòng serialize, một đường lỗi mới
(timeout, cổng), và một bản sao logic auth. Gọi `bat_dau(...)` trực tiếp giữ nguyên mọi cổng
mà BE đã dựng.

### 3.2 Disposition mới, không mượn `control`

Ý định Routine **không** phải một `CandidateActionPlan` một bước. Một Routine là 1–4 hành
động, có vòng đời riêng (`routine_executions`), có preview, và có thể bị hủy giữa chừng.
Nhét nó vào `control` là ép một thứ có vòng đời vào một hợp đồng không có vòng đời nào.

Nên router trả `disposition = "routine"` với một khối dữ liệu riêng, và graph rẽ nhánh.

### 3.3 Bốn ý định, ba trong số đó KHÔNG chạm executor

`routines_intent.YDinh` đã khai đúng năm: `chay`, `xem_truoc`, `dong_y`, `tu_choi`,
`bo_buoc`. Với #274 và #299:

| ý định | chạm executor? | lối ra |
|---|---|---|
| `xem_truoc` | **không** | đọc các bước, hỏi lại "chạy chứ?" |
| `chay` | có — `bat_dau()` | nhưng vẫn qua admission + safety + HITL của BE |
| `dong_y` / `tu_choi` sau preview | có / không | dùng lại **khe đề nghị treo** của #367 |
| hủy | **không** trực tiếp — gọi `huy()` của BE | typed handoff |

**`dong_y` sau preview dùng lại `loi_de_nghi` của #367 chứ không dựng khe thứ ba.** Đó là
đúng hình dạng ấy: xe vừa đọc to một việc cụ thể và chờ một tiếng có/không. Dựng riêng thì
`"ừ"` sau preview và `"ừ"` sau `offer` có hai đường xử lý — đúng cách để chúng lệch nhau,
và §10.3 của lộ trình đã ghi bài học ấy một lần.

## 4. ~~Phụ thuộc chéo làn~~ — SAI, đính chính 31/08

Mục này khẳng định `dang_chay_cua_phien(session_id)` chưa tồn tại và cần @hason0510 thêm.
**Sai.** `routine_execution.py` đã có `dang_chay_trong_phien(session_id)` với đúng chữ ký
ấy, chỉ là chưa ai gọi.

Tôi grep bằng cái tên tự đặt rồi kết luận khái niệm không có, thay vì tìm theo việc nó làm.
Hậu quả: một stub trả `None` vô điều kiện, tức mọi lượt hủy bằng giọng đều nói "không có
Routine nào đang chạy" kể cả khi có. Đã nối. Xem ADR-032 §Đính chính.


## 5. Bất biến phải giữ

1. **Không đường tắt tới executor.** Mọi bước vẫn qua `policy` → `safety` → HITL. Router chỉ
   nói *"đây là ý định Routine"*; `bat_dau` giữ nguyên ba cổng admission.
2. **Preview zero side effect** (#274). Đọc các bước là S0; không dựng `routine_executions`.
3. **Không nuốt câu xác nhận HITL thành cancel, và ngược lại** (#299). Cổng phê duyệt chạy ở
   `turns.py` **trước** graph — thứ tự ấy phải giữ, và có test.
4. **Router vẫn tất định, không đọc trạng thái** (ADR-006/010). Danh sách Routine của user là
   *trạng thái*, nên phân giải tên nằm ở **node**, không ở router — cùng chỗ đứng với
   `ghep_hoi_lai` và `loi_de_nghi`.
5. **Tên Routine không bao giờ tự kích hoạt** (#285, đã có test): phải có động từ + từ chỉ
   loại. Một Routine tên `"Đi làm"` không được nuốt mọi câu chứa hai chữ ấy.
6. `di_lui` của `--mode multiturn`, `--mode bao-loi` phải bằng **0**; `--mode intent` không
   tụt khỏi 1.0000.

## 6. Cái KHÔNG làm

- **Không** dựng lại admission/safety/cancellation — BE đã xong, xem §2.
- **Không** đụng `bo_buoc` (bỏ một bước trong preview). `routines_intent` đã đọc được ý định
  ấy, nhưng thực thi nó cần một hợp đồng "chạy với tập bước con" mà BE chưa có. Tách ra.
- **Không** làm #296. Nó là **spike**, và issue ghi rõ nó đo *"audio/transcript do FE spike
  cung cấp"* — chưa có thì không có gì để đo. Xem §7.
- **Không** thêm hàm vào file của BE. Xem §4.

## 7. #296 chưa bắt đầu được, và đây là điều kiện

Issue yêu cầu *"kết quả accept/reject/ambiguous có evidence, **không dựa synthetic-only để
tuyên bố human WER**"*. Repo có 264 file WAV nhưng chúng là **Piper TTS tổng hợp**
(`eval/datasets/poc/v1/audio/README.md` ghi rõ `speaker_code: "piper-tts-synthetic"`), nên
chúng **không dùng được** cho tuyên bố mà #296 đòi.

Điều kiện để bắt đầu:

1. FE spike (#277) giao audio hoặc transcript **có người nói thật**, trong điều kiện barge-in;
2. hoặc PM/PO hạ yêu cầu xuống "chỉ đo trên transcript" và chấp nhận nói rõ giới hạn ấy.

Cho tới lúc đó, thứ làn Agent làm được là **closed phrase set + ca âm tính**, và nó đã nằm
trong Task 4 của plan như một lớp ca của `multiturn-v1` — tức #296 sẽ có sẵn nửa dữ liệu khi
nó mở.

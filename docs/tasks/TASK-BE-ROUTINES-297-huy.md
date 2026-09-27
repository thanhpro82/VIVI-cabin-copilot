# TASK-BE-ROUTINES-297 — Cancellation idempotent và safe-stop lifecycle

- Issue: [#297](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/297), outcome [#278](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/278), epic [#270](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/270)
- Nguồn sản phẩm: `docs/routines_product_spec.md` §Hủy
- Phụ thuộc: #286 (engine), #290 (sự kiện)
- Trạng thái: **Chạy được trên PC** — 12 test mới xanh, full suite `2912 passed, 22 skipped`

## Điểm dừng an toàn là giữa hai bước

`cancel_requested` là một **cờ**, không phải trạng thái mới. Vòng lặp đọc lại cờ ấy từ DB
**trước mỗi bước** — không tin bản `execution` đã đọc lúc vào hàm, vì yêu cầu hủy tới từ
một request khác giữa lúc vòng lặp đang chạy.

Bước đang bay chạy nốt và được báo `completed`. Lệnh đã publish lên MQTT thì không rút
lại được, và một hệ báo "đã hủy" trong khi xe vừa mở kính là một hệ nói dối. **MVP không
rollback.**

## Ba đường của `huy()`, cùng một kết quả quan sát được

| Trạng thái | Xử lý |
|---|---|
| đã kết thúc | trả nguyên bản ghi — không terminal thứ hai, không sự kiện |
| đang chờ phê duyệt | **từ chối chính thẻ ấy** rồi đóng `user_canceled` ngay |
| đang chạy | bật cờ, trả về; vòng lặp đóng ở ranh giới bước tiếp theo |

Đường 2 phải chốt thẻ chứ không bỏ rơi: một thẻ `pending` bị bỏ lại sẽ chặn mọi thẻ sau
trong cùng phiên cho tới lúc hết hạn.

Đường 3 cố ý **không** chờ vòng lặp đóng xong — request Dừng phải trả lời ngay để nút bấm
không treo, và trạng thái cuối đi qua `routine.finished` trên `/ws/ivi`.

## Race giữa Dừng và thẻ phê duyệt (vá theo review PR #369)

Bản đầu đọc execution **một lần** ở đầu `huy()` rồi rẽ nhánh theo bản ấy. Interleaving
hỏng:

```
huy()        đọc execution -> running
_chay_tiep() tạo thẻ, ghi waiting_approval
huy()        bật cờ, rẽ theo bản CŨ (running) -> không ai từ chối thẻ, không ai đóng
```

Kết quả: tài xế bấm Dừng, thẻ vẫn treo, lần chạy kẹt `waiting_approval` tới lúc hết hạn.

Ba thay đổi đóng cả hai chiều của cửa sổ ấy:

1. **`huy()` đọc lại execution từ DB sau khi bật cờ** — không dùng bản đọc ở trên.
2. **`_chay_tiep` kiểm lại cờ sau khi đã ghi `waiting_approval`** — bắt chiều ngược lại,
   khi cờ bật trong lúc `_tao_approval` đang chạy; thẻ vừa tạo bị từ chối ngay.
3. **CAS khi đóng execution** (`WHERE status IN ('running','waiting_approval')`) — cả hai
   đường đều có thể thắng cuộc đua, nhưng chỉ một bên ghi được terminal và phát
   `routine.finished`. Không có nó thì một lần chạy phát **hai** sự kiện kết thúc.

Ba test khoá: `test_huy_van_dong_khi_approval_vua_duoc_tao_ngay_truoc_do` (nhại đúng bản
đọc cũ), `test_co_huy_bat_trong_luc_tao_the_thi_the_bi_tu_choi_ngay`,
`test_hai_duong_cung_dong_chi_phat_mot_terminal`. Kiểm chứng test không phải trang trí:
gỡ vá 1 ra thì test đầu đỏ với đúng triệu chứng `waiting_approval`.

## Hai thứ đi kèm

**Xoá Routine đang chạy bị chặn** (acceptance criteria #272) — `ROUTINE_RUNNING` 409 kèm
`details.execution_id`. Chọn vế *chặn* thay vì *tự hủy hộ*: tự hủy là quyết định thay
người dùng về một chuỗi lệnh đang tác động lên xe, và họ có thể chỉ định xoá nhầm.

**Dọn execution mồ côi lúc khởi động** — cùng khuôn `invalidate_orphaned_pending_approvals`.
Không có vòng lặp nào còn chạy để tiếp tục một chuỗi dở dang, và spec §Sau khi khởi động
lại chốt không Routine nào tự chạy tiếp. Để nguyên `running` thì ràng buộc
một-Routine-mỗi-phiên khoá luôn phiên ấy.

## Hợp đồng HTTP

`POST /api/v1/routine-executions/{id}/cancel` → **200** + execution. Idempotent.

200 chứ không 202: yêu cầu dừng đã được ghi nhận khi request trả về. Trạng thái trả về có
thể vẫn là `running` — điểm dừng nằm ở ranh giới bước tiếp theo.

## Cách kiểm chứng

```powershell
$env:MQTT_ENABLED="false"
.\.venv\Scripts\python.exe -m pytest tests/test_services/test_routine_cancel.py tests/test_api/test_routine_run_routes.py -q
```

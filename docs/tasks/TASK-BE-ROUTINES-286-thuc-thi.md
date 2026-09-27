# TASK-BE-ROUTINES-286 — Admission, safety/HITL và fail-fast execution

- Issue: [#286](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/286), outcome [#275](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/275), epic [#270](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/270)
- Nguồn sản phẩm: `docs/routines_product_spec.md` §Chạy
- Phụ thuộc: #282 (Routine + ownership), #283 (địa điểm cá nhân)
- Trạng thái: **Chạy được trên PC** — 27 test mới xanh, full suite `2891 passed, 22 skipped`

## Nguyên tắc chi phối

> **Routine không phải một đường tắt vào executor.**

Mọi bước đi qua đúng những cổng mà một câu lệnh nói ra đi qua: `policy.materialize_action_plan`
gán `safety_level` (nơi duy nhất được phép, ADR-006), `ApprovalStore` giữ HITL,
`VehicleGateway.execute` publish MQTT. `src/services/routine_execution.py` chỉ **điều
phối thứ tự** và giữ sổ sách.

## Ba quyết định thiết kế

**1. Mỗi bước là một plan riêng, không phải một plan bốn bước.** §Chạy chốt Routine có
hai bước S2 phải xin phê duyệt **tuần tự**, không gộp thành một thẻ. Một plan bốn bước
có hai S2 sẽ được `materialize_action_plan` gộp thành một thẻ cho cả bốn — tài xế nghe
một câu hỏi rồi bốn việc xảy ra, trong đó có việc họ chưa kịp hiểu là mình vừa đồng ý.

**2. Chụp lại các bước lúc admit.** `steps_json` là bản chụp, không phải con trỏ vào
`routines`. Hai chiều đều cần: Done-when của #286 cấm replay plan cũ, và chiều ngược lại
— người dùng sửa Routine giữa lúc nó chạy thì lần chạy này vẫn là lần chạy của phiên bản
họ đã đồng ý.

**3. Đọc lại trạng thái xe trước *mỗi* bước.** Giữa hai bước tài xế có thể đã cho xe
chạy, và một bước S2 lúc đứng yên là S3 lúc đang lăn bánh. Đọc một lần rồi dùng lại
chính là cách cấp phép cho hành động lẽ ra phải chặn. Kể cả sau khi thẻ đã được duyệt:
`test_xe_chuyen_banh_trong_luc_cho_thi_van_bi_chan` khoá điều đó.

## Điểm rẽ duy nhất ở `approvals.py`

Thẻ của Routine không thuộc lượt nào, nên `_resume_and_publish` (gọi
`graph.ainvoke(Command(resume=...))`) sẽ resume oan lượt gần nhất của phiên. `chot_da_xac_thuc`
nay hỏi `routine_execution.tim_theo_approval(...)` và rẽ sang `_chay_tiep_routine`.

**Quyết định vẫn chốt ở đúng một chỗ** — bốn bất biến HITL không có bản sao thứ hai. Chỉ
phần *chạy tiếp* mới rẽ.

## Bảng fail-closed

| Ca | Kết quả |
|---|---|
| Routine bị tắt / thiếu địa điểm / phiên đang chạy Routine khác | từ chối **trước khi** tạo execution |
| Không đọc được trạng thái xe | `failed / vehicle_state_unavailable`, không lệnh nào chạy |
| Bước hoá S3 lúc chạy | `blocked` **trước HITL**, không hỏi tài xế |
| Bước S2 | `waiting_approval`, không bước nào đi tiếp |
| Approval bị từ chối | `user_canceled`, zero side effect cho bước ấy |
| Một bước lỗi | `failed`, mọi bước sau ghi `skipped` |

Bước chưa chạy **có mặt** trong sổ sách với trạng thái rõ ràng — cùng lập luận với issue
#83 ở `nodes/execute.py`: hồ sơ là thứ ta dùng để nói cái gì đã xảy ra và cái gì không.

## Hợp đồng HTTP

| Method | Path | Trả |
|---|---|---|
| POST | `/api/v1/routines/{id}/run` | **202** + execution |
| GET | `/api/v1/routine-executions/{id}` | execution |

202 vì lần chạy chưa chắc xong khi request trả về — nó có thể đang chờ phê duyệt. Mã lỗi:
`ROUTINE_DISABLED`, `ROUTINE_NEEDS_SETUP`, `ROUTINE_ALREADY_RUNNING` (409),
`ROUTINE_NOT_FOUND`, `ROUTINE_EXECUTION_NOT_FOUND` (404).

## Chưa làm, và ai làm

- **Sự kiện tiến độ trên `/ws/ivi`** → #290. Hôm nay client phải hỏi lại
  `GET /routine-executions/{id}`.
- **Nút Dừng / hủy chủ động** → #297. Từ chối approval đã cho `user_canceled`, nhưng hủy
  giữa chuỗi S1 thì chưa có đường.
- **Chặn xoá Routine đang chạy** (acceptance criteria #272) → cổng đã có chỗ:
  `dang_chay_trong_phien()` cho biết execution còn sống; nối vào `delete_routine` thuộc #297.
- **Lời thoại báo cáo kết quả** → #276/#292 (FE) và phần voice của epic.

## Cách kiểm chứng

```powershell
$env:MQTT_ENABLED="false"
.\.venv\Scripts\python.exe -m pytest tests/test_services/test_routine_execution.py tests/test_api/test_routine_run_routes.py -q
```

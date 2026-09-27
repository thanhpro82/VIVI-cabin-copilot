# TASK-BE-ROUTINES-282 — Persistence, bootstrap mẫu và CRUD theo ownership

- Issue: [#282](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/282), outcome [#272](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/272), epic [#270](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/270)
- Nguồn sản phẩm: `docs/routines_product_spec.md`
- Trạng thái: **Chạy được trên PC** — 49 test xanh (26 store + 23 API), `ruff check src/ tests/ scripts/` sạch

## Phạm vi đã làm

| Thành phần | File |
|---|---|
| Hai bảng + ba ràng buộc | `src/db.py` (`routines`, `user_places`) |
| Store: CRUD, bootstrap, luật hợp lệ | `src/services/routines_store.py` |
| Validate bước dùng chung với đường chạy | `src/agents/routines.py::kiem_tra_buoc` |
| Sáu path REST | `src/api/routine_routes.py` |
| Model trên dây | `src/models/api.py` |

## Hợp đồng HTTP

Tất cả `require_driver`. Chủ sở hữu **luôn** lấy từ token, không bao giờ từ body.

| Method | Path | Trả |
|---|---|---|
| GET | `/api/v1/routines` | `data.items[]`, mới sửa nhất trước; lần đầu gieo 3 mẫu |
| POST | `/api/v1/routines` | 201 + Routine |
| GET | `/api/v1/routines/{id}` | Routine |
| PUT | `/api/v1/routines/{id}` | Routine (bump `version` nếu tên/bước đổi) |
| PUT | `/api/v1/routines/{id}/enabled` | Routine (không bump `version`) |
| DELETE | `/api/v1/routines/{id}` | 204; mẫu mặc định → 409 |
| POST | `/api/v1/routines/{id}/restore-default` | Routine gốc, bump `version` |

Mã lỗi khớp thứ `frontend/src/lib/services/routines/mock.ts` đang ném, để `real.ts` chỉ
phải đổi transport: `ROUTINE_NOT_FOUND` (404), `ROUTINE_NAME_DUPLICATE` /
`ROUTINE_TEMPLATE_PROTECTED` / `ROUTINE_NOT_TEMPLATE` (409), `ROUTINE_EMPTY` /
`ROUTINE_TOO_MANY_STEPS` / `ROUTINE_NAME_EMPTY` / `ROUTINE_NAME_INVALID` /
`ROUTINE_STEP_INVALID` (422, kèm `details.ly_do`).

## Bốn quyết định đáng đọc trước khi sửa

**1. 404 cho cả "của người khác" lẫn "không tồn tại".** Trả 403 cho ca đầu là xác nhận
Routine ấy có thật — đúng kênh rò rỉ mà #272 acceptance criteria đóng lại. Mọi truy vấn
trong store đều mang `WHERE user_id = ?`, nên không tồn tại một hàm tra được Routine chỉ
bằng id.

**2. `steps_json` giữ nguyên camelCase của FE.** `src/agents/routines.py` đã nhận đúng
dạng ấy. Lưu dạng canonical trước nghĩa là dịch hai lần, và bảng dịch thứ hai sẽ lệch
bảng thứ nhất đúng vào ngày ai đó thêm một action.

**3. Validate lúc lưu ≠ dịch lúc chạy, khác nhau đúng ở `navigation`.** Lúc chạy, bước
dẫn đường chưa resolve được địa điểm phải ném — đoán một POI là chở tài xế tới chỗ họ
không bảo. Lúc lưu thì ngược lại: Routine "Đi làm" của người chưa gán Cơ quan là **bình
thường**, spec chốt nó hiển thị "Cần thiết lập". Dùng `routine_thanh_candidate` để
validate lúc lưu sẽ làm cả ba mẫu mặc định không bootstrap nổi. Đó là lý do
`kiem_tra_buoc` tồn tại — và nó vẫn gọi `validate_args` của `tool_registry`, nên dải giá
trị chỉ có một nguồn.

**4. `version` thay cho một cờ boolean.** Spec §Preview đòi preview ở lần chạy đầu của
**mỗi phiên bản**. `needs_preview = previewed_version != version`, và `version` bump khi
tên hoặc bước đổi — nên sửa xong thì preview tự bật lại, không phụ thuộc ai nhớ gọi hàm
reset. Đổi icon và bật/tắt **không** bump: chúng không đổi việc Routine sẽ làm, và bắt
nghe lại preview vì một biểu tượng là dạy tài xế bấm qua preview cho nhanh.

## Chưa làm, và ai làm

- **Ghi `previewed_version`** — thuộc #285 (intent preview/run). Ở đây nó chỉ được đọc.
- **`GET/PUT` địa điểm Nhà/Cơ quan** — #283. Bảng `user_places` đã có và `needs_setup`
  đã đọc nó, nhưng chưa có route nào ghi, nên hôm nay mọi Routine dẫn đường đều
  `needs_setup = true`. Hai POI `poi-home-01`/`poi-work-01` cũng thuộc #283.
- **Chặn xoá Routine đang chạy** (#272 acceptance criteria) — cần execution lifecycle của
  #286. Cổng sẽ nằm trong `delete_routine`; hôm nay chưa có gì để hỏi.
- **`real.ts` phía FE** — `frontend/src/lib/services/routines/index.ts` vẫn trỏ mock.

## Cách kiểm chứng

```powershell
$env:MQTT_ENABLED="false"
.\.venv\Scripts\python.exe -m pytest tests/test_services/test_routines_store.py tests/test_api/test_routine_routes.py -q
```

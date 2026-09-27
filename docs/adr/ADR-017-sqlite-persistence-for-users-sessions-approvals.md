# ADR-017 — Persistence SQLite cho users / sessions / approvals / idempotency

- **Trạng thái:** Accepted
- **Ngày:** 2026-08-12
- **Issue:** #46
- **Liên quan:** ADR-013 (một nguồn state xe), `docs/safety_and_hitl.md`, `docs/data_model.md`

## Bối cảnh

`CLAUDE.md` liệt "Nothing is persisted" là một gap hệ thống, không phải một thiếu sót
nhỏ. Approval, session và token đều nằm trong dict được `threading.Lock` canh; `src/db.py`
có mở SQLite nhưng chỉ để ghi rồi xoá một dòng thăm dò cho `/healthz`, không có bảng
domain nào. Hệ quả cụ thể:

- Restart backend là **mất mọi approval đang chờ** — một tài xế đang nhìn hộp thoại xác
  nhận thì hộp thoại đó trở thành vô nghĩa mà không ai báo.
- Restart cũng **logout tất cả**, vì bản thân "user" là tuple hằng trong mã nguồn còn
  token là dict.
- Bất biến "tối đa một pending approval mỗi session" (`safety_and_hitl.md:41`) chỉ được
  giữ bằng một dict tra cứu, tức chỉ đúng trong **một** tiến trình. Worker thứ hai là phá.
- Mật khẩu demo nằm **thô** trong `src/services/auth.py`.

## Quyết định

Bốn bảng trên `sqlite3` của thư viện chuẩn, không thêm phụ thuộc:
`users`, `sessions`, `approvals`, `idempotency_records`.

1. **`sqlite3` stdlib, không ORM, không Alembic.** P0 chỉ có một hình dạng schema và
   chưa từng phải nâng cấp dữ liệu cũ; `CREATE TABLE IF NOT EXISTS` chạy mỗi lần khởi
   động là đủ. Khi nào cần đổi cột thì đó mới là lúc mang công cụ migration vào.
2. **Một kết nối dùng chung cho cả tiến trình** (`src.db.get_connection`), với
   `check_same_thread=False`, `row_factory=sqlite3.Row`, WAL. Ba bảng phải nhìn thấy
   nhau; hai `:memory:` của hai kết nối khác nhau là hai DB hoàn toàn khác nhau.
3. **`threading.Lock` như cũ, không đổi sang async.** Đổi là lan sang graph và HITL —
   một đợt khác.
4. **Bất biến một-pending-mỗi-session là partial unique index thật**
   (`approvals(session_id) WHERE status='pending'`), không phải dict. Đây là chỗ
   persistence làm bất biến **mạnh lên** chứ không chỉ bền hơn.
5. **`idempotency_records` nằm trong phạm vi đợt này**, dù issue #46 không nêu. Lý do
   phoenix chỉ ra ở PR #87: persist approval mà để idempotency ở RAM thì crash để lại
   approval bền vững với zero bản ghi idempotency, và retry nhận `consumed` thay vì
   `approved` của lần đầu — phá hợp đồng "exact replay returns exact prior response"
   (`api_spec.md:50`). Cả bản ghi đã xong lẫn chỗ đang đặt đều persist.

   Bước "đặt chỗ" là **một câu lệnh SQL duy nhất** (`_CLAIM_SQL`), DB phân xử qua
   `rowcount`, chứ không phải SELECT rồi mới INSERT dưới `asyncio.Lock`. Phoenix chỉ ra
   ở PR #89 rằng lock đó chỉ tuần tự hoá trong một event loop: hai tiến trình cùng khoá
   đều thấy "chưa ai đặt", và `DO UPDATE` vô điều kiện khiến tiến trình sau ghi đè chỗ
   của tiến trình trước — cả hai cùng chạy việc thật, đúng cái race `begin()` sinh ra để
   đóng. Đây là điểm thứ hai (cùng với partial unique index) mà persistence làm bất biến
   **mạnh lên** chứ không chỉ bền hơn.
6. **Token vẫn ở RAM.** `docs/data_model.md` không thiết kế bảng nào cho token, và ghi
   token xuống đĩa là thêm bề mặt lộ bí mật cho một thứ vốn ngắn hạn. Restart vẫn bắt
   đăng nhập lại; nhưng không còn *mất user*, đó mới là thứ #46 đóng.
7. **Mật khẩu lưu PBKDF2-HMAC-SHA256 có salt**, `hashlib` stdlib. Số vòng là biến cấu
   hình (`auth_pbkdf2_iterations`, mặc định 200 000) vì đó chính là cái giá phải trả: ở
   mức mặc định, riêng việc băm cộng ~9 s vào mỗi lần chạy bộ test.

   **Phạm vi của khẳng định này hẹp, và bản đầu của ADR đã nói quá** (Thành bắt được ở
   review PR #89). Thứ đổi là *dạng lưu trong cơ sở dữ liệu*: `users.password_hash` chứa
   PBKDF2 chứ không chứa chuỗi thô. Credential seed **vẫn nằm trong mã nguồn**, ở
   `DEMO_USERS` (`src/db.py`). Đây không phải "mật khẩu đã rời source code". Chấp nhận
   được cho demo local một máy; nếu phạm vi mở sang production thì hai dòng đó phải
   chuyển sang env/secret hoặc script provisioning.
8. **Vòng đời `sessions`: hết hạn 24 h, xoá sau 30 ngày.** Xem mục riêng bên dưới.

### Vòng đời session — chốt sau review PR #89

Bản đầu của #46 để bảng `sessions` không có TTL, không end-session, không cleanup: hai
cột `status` và `ended_at` có trong schema từ đầu mà **chưa ai từng ghi**, nên bảng chỉ
có thể tăng. Thành yêu cầu acceptance criteria; ba câu trả lời:

- **Hết hạn theo thời gian, không theo số lượng.** `session_ttl_hours = 24`. Trần
  đếm-theo-số làm phiên của một người chết vì lưu lượng của người khác — đúng cái 403
  oan mà đợt này vừa bỏ đi. 24 h dài hơn TTL token (12 h) nên trong thực tế token luôn
  hết hạn trước và người dùng đăng nhập lại, chứ không gặp phiên chết giữa chừng.
- **Cleanup ở hai chỗ, hai bước.** `expire_and_purge_sessions()` chạy lúc khởi động
  *và* trong `create_session` (backend chạy liên tục nhiều ngày thì đợt quét lúc khởi
  động không bao giờ chạy lần thứ hai). Bước một chốt `active → expired` + ghi
  `ended_at`; bước hai mới xoá hẳn hàng cũ hơn `session_retention_days = 30`, đúng mốc
  lưu trữ của `data_model.md:43`. Xoá ngay ở bước một là mất dấu vết audit đúng lúc nó
  bắt đầu có ích. Ngoài ra `get_session_record` tự CAS `active → expired` **tại thời
  điểm đọc**, cùng kỷ luật `ApprovalStore` — không có nó thì TTL chỉ có hiệu lực khi ai
  đó restart backend.
- **API trả `403 FORBIDDEN`**, đúng thông điệp *"session không tồn tại hoặc không thuộc
  về bạn"* như phiên của người khác. Không thêm mã lỗi riêng cho "hết hạn":
  `turns.py`/`approvals.py` cố ý gộp "không tồn tại" với "không phải của bạn" để không
  rò enumeration, và một mã riêng sẽ phá đúng tính chất đó. Không route nào phải sửa —
  cả bốn call site đã dịch `None` thành 403 sẵn.

### Một hợp đồng bị đổi có chủ đích

- **Trần `MAX_SESSIONS` không còn xoá hàng `sessions`.** Nó là trần bộ nhớ cho graph.
  Bản trước xoá luôn hàng phiên, và hệ quả là người dùng nhận 403 "phiên không tồn tại"
  cho chính phiên mình vừa tạo chỉ vì có 128 người khác chen vào giữa. Approval thì vẫn
  mất theo graph, vì mất checkpoint là mất khả năng resume. Giới hạn tăng trưởng của
  bảng giờ do TTL/retention ở trên lo, không do trần đếm-theo-số.

**Đã rút lại:** bản đầu của #46 bỏ FOREIGN KEY `sessions.user_id → users(id)` với lý do
ràng buộc đó chặn mất các test cổng sở hữu. Thành bác ở review PR #89, và bác đúng — chỉ
có **ba** chỗ trong bộ test dựng phiên cho user không tồn tại, mỗi chỗ chỉ cần
`seed_test_user()` một dòng. Cái giá đó nhỏ; thứ đánh đổi thì không, vì không có FK là
DB cho phép session mồ côi. FK đã khôi phục.

### Đối chiếu với `docs/data_model.md` — ba chỗ lệch, đều có chủ đích

Issue #46 đòi "bảng `users` thật **theo `data_model.md`**", nên chỗ nào lệch phải nói ra
chứ không để người review tự phát hiện.

| Bảng | `data_model.md:41-48` | Đã làm | Lệch |
|---|---|---|---|
| `users` | id, email, password_hash, role, active | + `display_name` | **Thêm một cột.** `POST /auth/login` trả `user.display_name` trong envelope (`api_spec.md`), và nó phải đến từ đâu đó. Bản trước lấy từ tuple hằng; giờ tuple không còn |
| `sessions` | id, user_id, vehicle_id, status, started_at, ended_at | y hệt, `user_id` là FK thật | không (FK khôi phục sau review PR #89) |
| `approvals` | id, **user_id**, session_id, plan_id, plan_digest, vehicle_state_version, status, **decision**, expires_at, decided_at | thiếu `user_id` và `decision`; thêm `turn_id`, `created_at`, `prompt_text`, `steps_summary_json` | **Hai cột thiếu, bốn cột thêm** — xem dưới |
| `idempotency_records` | *không có trong data_model.md* | bốn khoá + state/body | **Bảng mới hoàn toàn**, lý do ở mục 5 phía trên |

Về hai cột thiếu của `approvals`:

- **`user_id`**: `ApprovalRecord` (`src/agents/approval.py`) không mang trường này, và quyền
  sở hữu hiện giải qua `get_session_record(record.session_id).user_id` ở `approvals.py` và
  `citation_routes.py`. Thêm cột đồng nghĩa với sửa contract của record và node HITL — đúng
  thứ ràng buộc "không đổi API công khai của các store" của đợt này cấm. Đường giải hiện tại
  **vững hơn trước** chứ không yếu đi, vì hàng `sessions` nay cũng bền. Muốn denormalize để
  bớt một lần join thì làm cùng đợt có `action_plans`.
- **`decision`**: `status` đã mã hoá quyết định (`approved`/`rejected`), nên một cột `decision`
  riêng là hai nguồn sự thật cho cùng một dữ kiện — và đó là kiểu bug im lặng nhất. Nếu nhóm
  muốn giữ đúng chữ của `data_model.md` thì phải kèm ràng buộc buộc hai cột đồng nhất, chứ
  không phải chỉ thêm cột.

Bốn cột thêm (`turn_id`, `created_at`, `prompt_text`, `steps_summary_json`) là các trường
`ApprovalRecord` vốn đã có từ trước đợt này; không lưu thì restart mất nội dung hộp thoại
xác nhận, tức mất đúng thứ #46 muốn giữ.

## Điều đợt này **chưa** đạt — đọc trước khi tuyên bố

- **Điều khoản atomic plan+approval của `safety_and_hitl.md:42` vẫn chưa đạt.** Không có
  bảng `action_plans`/`plan_steps` trong đợt này; plan còn sống trong state của LangGraph.
  "Immutable S2 ActionPlan + pending ApprovalRequest commit atomically trong một DB
  transaction" vì thế chỉ đúng một nửa. Đừng ghi là đã đóng.
- **Bản ghi approval bền, nhưng *lượt* thì chưa.** `session_state.get_graph()` dựng graph
  với `InMemorySaver`, nên checkpoint chứa `interrupt()` của lượt S2 chết theo tiến trình.
  Một approval `pending` sống sót qua restart mà để nguyên thì tài xế bấm Đồng ý vào một
  thread không còn interrupt nào: lệnh không chạy và lượt không bao giờ tới sự kiện
  terminal. Vì vậy `invalidate_orphaned_pending_approvals()` chạy lúc khởi động và chốt
  mọi `pending` còn sót sang `invalidated` — **fail-closed**, đúng tinh thần
  `safety_and_hitl.md`: bắt hỏi lại còn hơn treo im lặng.

  Muốn lượt cũng sống qua restart thì phải thay checkpointer (ví dụ
  `langgraph-checkpoint-sqlite`). Đó là một phụ thuộc mới và lan sang graph/HITL, nằm
  ngoài #46 — ghi lại đây làm việc kế tiếp, không phải làm im lặng.
- **Một tiến trình.** WAL cho phép nhiều reader, và partial unique index chặn được hai
  writer cùng tạo pending, nhưng chưa có bằng chứng chạy hai worker. Đừng suy ra từ
  "index chặn được" thành "chạy được nhiều worker".

## Hệ quả

- Restart không còn nuốt bản ghi approval và không còn xoá user.
- Bộ test hiện có xanh gần như nguyên vẹn: bốn test phải sửa, tất cả đều là test đọc
  thẳng vào dict nội bộ đã biến mất, hoặc khoá đúng hợp đồng vừa đổi ở trên.
- `tests/conftest.py` trỏ `DATABASE_URL` vào `sqlite:///:memory:` và hạ số vòng PBKDF2,
  nên bộ test không đụng `data/app.db` của máy dev và không trả giá KDF.

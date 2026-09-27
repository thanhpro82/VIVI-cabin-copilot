# Persistence SQLite cho users / sessions / approvals / idempotency — kế hoạch

> Issue #46, hướng **đầy đủ**. Quyết định của Nhân 2026-08-12: `sqlite3` stdlib (không
> thêm phụ thuộc), bốn bảng, token **giữ nguyên trong RAM**.

**Mục tiêu:** restart backend không còn làm mất approval đang chờ và không logout mọi
người vì "user" biến mất. Đóng nợ mà `CLAUDE.md` liệt là gap hệ thống ("Nothing is
persisted").

## Vì sao bốn bảng này, không nhiều hơn không ít hơn

- `users`, `sessions`, `approvals` — đúng phạm vi issue #46.
- `idempotency_records` — **thêm vào có lý do**: phoenix chỉ ra ở PR #87 rằng persist
  approval mà để idempotency ở RAM thì crash sẽ để lại approval bền vững với zero bản
  ghi idempotency, và retry nhận `consumed` thay vì `approved` của lần đầu — phá đúng
  hợp đồng "exact replay returns exact prior response" (`api_spec.md:50`). Hai thứ phải
  cùng tầng bền vững.
- **Không** làm `action_plans`/`plan_steps` đợt này. Hệ quả phải ghi thẳng, không được
  im: điều khoản *"immutable S2 ActionPlan + pending ApprovalRequest commit atomically
  trong một DB transaction"* của `safety_and_hitl.md:42` **vẫn chưa đạt** sau đợt này,
  vì plan còn sống trong state của LangGraph chứ chưa có bảng. Đừng tuyên bố đã đóng.

## Ràng buộc toàn cục

- **Không đổi API công khai của các store.** `ApprovalStore`, `session_state`,
  `IdempotencyStore` giữ nguyên chữ ký; chỉ thay ruột. Bộ test hiện có là lưới nghiệm
  thu: nếu chúng phải sửa hàng loạt thì thiết kế sai, dừng lại xem lại.
- **Mặc định của mỗi instance là SQLite `:memory:`** — test giữ được tính cô lập và tốc
  độ như khi còn dùng dict. Chỉ singleton của production trỏ vào file.
- **`threading.Lock` + `check_same_thread=False`**, cùng khuôn đồng bộ đang có. Không
  đổi sang async trong đợt này — đổi là lan sang graph và HITL.
- **Bất biến "tối đa một pending mỗi session" phải là partial unique index thật**
  (`safety_and_hitl.md:41`), không phải một dict tra cứu. Đây là điểm mà persistence
  làm cho bất biến *mạnh lên*, không chỉ là bền hơn.
- Không đổi hành vi hết hạn: vẫn CAS `pending→expired` đọc-mới-phát-hiện.

## Task 1 — tầng db: kết nối, schema, seed

**Files:** `src/db.py`, `tests/test_db.py`

- [x] `connect(db_path)` trả `sqlite3.Connection` với `check_same_thread=False`,
      `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`.
- [x] `ensure_schema(conn)` — `CREATE TABLE IF NOT EXISTS` cho bốn bảng, cộng
      **partial unique index** `approvals(session_id) WHERE status='pending'`.
- [x] Seed hai demo user (giữ nguyên `usr_driver_01`/`usr_engineer_01`) idempotent.
- [x] Test: schema dựng hai lần không lỗi; partial index thật sự chặn pending thứ hai.

## Task 2 — `ApprovalStore` chạy trên SQLite

**Files:** `src/agents/approval.py`, test hiện có làm lưới

- [x] Đổi ruột, giữ chữ ký. `create/get/decide/consume/invalidate/pending_for_session/
      record_count` hành xử y hệt.
- [x] `create()` bắt `sqlite3.IntegrityError` từ partial index → cùng lỗi
      `APPROVAL_ALREADY_PENDING` như hôm nay.
- [x] Chạy `tests/test_agents/test_approval_store.py`, `test_hitl_node.py`,
      `test_hitl_safety.py` **không sửa dòng nào**.

## Task 3 — `sessions` và `users`

**Files:** `src/api/session_state.py`, `src/services/auth.py`

- [x] `create_session`/`get_session_record` đọc ghi SQLite.
- [x] `/auth/login` tra bảng `users` thay vì tuple hằng. Mật khẩu lưu **hash**, không
      lưu thô — demo vẫn dùng hai tài khoản cũ nên không đổi trải nghiệm.
- [x] Token **giữ nguyên RAM** (quyết định 2026-08-12): `data_model.md` không thiết kế
      bảng nào cho token, và ghi token xuống đĩa là thêm bề mặt lộ bí mật cho một thứ
      vốn ngắn hạn.

## Task 4 — `IdempotencyStore` trên SQLite

**Files:** `src/services/idempotency.py`

- [x] `begin/finish/abandon` giữ nguyên ngữ nghĩa, kể cả `IdempotencyInProgress`.
- [x] Bản ghi `pending` (đã đặt chỗ, chưa xong) cũng persist — nếu không thì crash giữa
      chừng vẫn để lại lệch đúng như phoenix mô tả.

## Task 5 — nối vào vòng đời app + tài liệu

**Files:** `src/main.py`, `docs/adr/`, `CLAUDE.md`

- [x] Dựng schema lúc startup, dùng `settings.database_url` đã có.
- [x] ADR mới ghi quyết định + **ghi rõ điều chưa đạt** (atomic plan+approval).
- [x] Sửa `CLAUDE.md` mục "Nothing is persisted" cho đúng hiện trạng mới.

## Tiêu chí nghiệm thu

- [x] Bộ test hiện có xanh **không phải sửa** (trừ chỗ thật sự đổi hợp đồng).
- [x] Test mới: restart giả lập (đóng/mở lại kết nối) thì approval đang chờ **vẫn còn**.
- [x] Partial unique index chặn pending thứ hai ở tầng DB, không phải ở tầng Python.

## Đã làm xong 2026-08-12 — và những gì cố ý để lại

Năm task xong, suite 906 passed / 20 skipped. Quyết định phát sinh trong lúc làm, ghi
đầy đủ ở **ADR-017**:

- `sessions.user_id` **không** là FOREIGN KEY (ràng buộc đó chặn mất chính các test cổng
  sở hữu).
- Trần `MAX_SESSIONS` **không** còn xoá hàng `sessions` — nó là trần bộ nhớ cho graph.
- `invalidate_orphaned_pending_approvals()` chạy lúc khởi động: bản ghi approval bền,
  nhưng **lượt thì chưa** (checkpoint `interrupt()` nằm trong `InMemorySaver`). Muốn lượt
  cũng bền thì phải thay checkpointer — việc kế tiếp, không thuộc #46.
- Bốn test phải sửa, tất cả đều đọc thẳng vào dict nội bộ đã biến mất hoặc khoá đúng hợp
  đồng vừa đổi: `test_pending_index_does_not_go_stale_after_eviction`,
  `test_evicting_a_session_also_drops_its_session_record`,
  `test_begin_reclaims_a_reservation_that_is_older_than_the_ttl`, và
  `session_state.reset()` (mã nguồn, không phải test).
- **Vẫn chưa đạt:** điều khoản atomic plan+approval của `safety_and_hitl.md:42`. Không có
  bảng `action_plans`/`plan_steps` trong đợt này. Đừng tuyên bố đã đóng.

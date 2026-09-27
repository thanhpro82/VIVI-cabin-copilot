# HITL end-to-end qua `/ws/ivi` — Design

> ## ⚠️ SUPERSEDED — 2026-08-10. Đừng đọc tài liệu này như kế hoạch đang chạy.
>
> Tiền đề trung tâm của nó — *"lát cắt dọc 5 interface (#1, #2, #3, #11 + sửa #5)"* —
> **đã chết**, vì phạm vi bị chia lại giữa các thành viên ngay sau khi tài liệu này
> được viết. Giữ lại vì phần phân tích vẫn đúng và vì lịch sử quyết định không nên đứt.
>
> | Tài liệu này nói | Thực tế |
> |---|---|
> | `#11 WS /ws/ivi` — **làm mới** | Đã có sẵn từ trước: Thành dựng ở PR #31, cùng `IviEventBus` và `emit_turn_lifecycle` |
> | Tạo `SessionEventBus` (`src/api/events.py`) | Không tạo. Tương đương đã có: `src/services/ivi_events.py` |
> | Tạo `TurnRunner` (`src/api/turn_runner.py`) | Không tạo. Tương đương đã có: `emit_turn_lifecycle()` |
> | `#1 /auth/login`, `#2 /sessions`, `#3 /turns/text` — làm mới | **Thành làm**, PR #37 |
> | `#4 /turns/voice` — ngoài phạm vi | Lại chính là thứ đã xong trước tiên (PR #31) |
> | Rủi ro 1 (hai nguồn trạng thái xe) — *"tách ticket riêng, làm sau"* | **Nằm trong ticket này**. Sơn dựng `VehicleGateway` (PR #32), phần nối agent là AC2 và đã xong ở PR #36 |
>
> **Phần vẫn đúng và đã được thực hiện:** nguyên tắc "không sửa node nào trong
> `src/agents/`" (giữ nguyên, việc dịch sự kiện nằm ngoài graph); chẩn đoán hai nguồn
> trạng thái xe (Sơn phân tích độc lập ra cùng kết luận, thành ADR-013); năm bất biến
> ở mục "Bất biến" (đều đã có test khoá); và toàn bộ lập luận Auth — **đã chuyển giao
> cho Thành** và là thứ PR #37 hiện thực, gồm cả lý do gắn quyền sở hữu vào *phiên đăng
> nhập* chứ không vào *người dùng*.
>
> **Phần vẫn còn nợ:** ba khoảng trống của tầng `/ws/ivi` nêu ở mục Rủi ro 3 —
> `sequence` tăng theo kết nối chứ không theo phiên, `IviEventBus` không có buffer nên
> rớt mạng lúc chờ duyệt là mất `approval.required`, và `AUTH_ENABLED` là cờ ma. Ghi ở
> `docs/handoff/frontend-integration-map.md` mục **CHƯA RÕ #11**.
>
> Trạng thái thật của từng interface: xem `docs/handoff/frontend-integration-map.md`.

**Trạng thái:** ~~Thiết kế, chờ duyệt~~ → **Superseded** (xem khối trên).
**Nhánh:** `feature/hitl-e2e-ws-ivi`, tách từ `develop` tại `4563571`. Đã merge (PR #36).
**Ngày:** 2026-08-09
**Ticket:** Tích hợp HITL end-to-end (nối Agent/Safety với approval flow và Frontend).

## Mục tiêu

Lệnh S2 tạo pending approval, FE gửi quyết định qua REST, kết quả phát về `/ws/ivi`.

## Sự thật quyết định thiết kế: Frontend đã được xây sẵn theo hợp đồng

Đây không phải thiết kế trên giấy trắng. `frontend/src/lib/services/` **đã tồn tại và đã
ghim hợp đồng**, khớp `docs/api_spec.md`. Thiết kế này chỉ có một việc: làm backend đáp
ứng đúng thứ FE đang chờ.

Ba câu hỏi kiến trúc lớn đã được FE trả lời sẵn:

| Câu hỏi | Bằng chứng trong code FE | Kết luận |
|---|---|---|
| Decision đồng bộ hay bất đồng bộ? | `decideApproval(...): Promise<void>` — không đọc body | **Bất đồng bộ** |
| Turn vào hệ thống qua đâu? | `POST /turns/text` → chỉ `{data:{turn_id}}` | Mọi kết quả qua WS |
| Auth ra sao? | Đã gọi `/auth/login`, `/sessions`, gửi `Bearer` | Cần #1 và #2 |

FE cũng đã khai **allowlist sự kiện** `DriverEvent` gồm 13 loại, và 6 giá trị
`TurnCancelReason` **khớp chính xác** 6 outcome mà node approval hiện có đang trả về:
`approval_rejected`, `approval_expired`, `approval_invalidated_state`,
`approval_invalidated_plan`, `approval_predicate_failed`, `approval_not_pending`.

Hệ quả về phạm vi: "HITL end-to-end nối với Frontend" **không thể** chỉ là dựng thêm một
WebSocket. Thiếu bất kỳ cái nào trong #1/#2/#3/#11 thì FE không chạm tới được luồng HITL.

## Phạm vi

**Trong phạm vi — 5 interface:**

| # | Interface | Trạng thái hiện tại |
|---|---|---|
| 1 | `POST /api/v1/auth/login` | Làm mới |
| 2 | `POST /api/v1/sessions` | Làm mới |
| 3 | `POST /api/v1/turns/text` | Làm mới |
| 11 | `WS /ws/ivi` | Làm mới |
| 5 | `POST /api/v1/approvals/{id}/decision` | **Đã có** — sửa thành bất đồng bộ + kiểm quyền |

**Ngoài phạm vi, ghi rõ để không bị đọc nhầm:** `#4 turns/voice` (kéo theo ASR/TTS),
`#7 citations` (Task 1), `#8 traces`, `#9 metrics`, replay cursor đầy đủ
(`REPLAY_CURSOR_INVALID`/`REPLAY_WINDOW_EXPIRED`), kiểm `Origin` allowlist, RBAC nhiều vai.

## Hợp đồng response — đọc thẳng từ code FE, không suy diễn

Mọi phản hồi thành công bọc trong `{"data": ...}`; mọi lỗi bọc trong
`{"error": {"code", "message", "retryable"}}` (`turn/real.ts:throwIfError`).

| Endpoint | Request | Response `data` |
|---|---|---|
| `POST /auth/login` | `{email, password}` | `{access_token, token_type, expires_at, user: {user_id, role, display_name}}` |
| `POST /sessions` | `{vehicle_id, input_mode}` + `Bearer` | `{session_id, vehicle_id, status, started_at}` |
| `POST /turns/text` | `{session_id, text}` + `Bearer` | `{turn_id}` |
| `POST /approvals/{id}/decision` | `{decision, approved_vehicle_state_version}` + `Bearer` | body không được FE đọc; chỉ mã lỗi có ý nghĩa |
| `WS /ws/ivi` | subprotocol `["vivi.v1", "bearer.<base64>"]` | các `DriverEvent` |

FE kiểm `expires_at` để tự huỷ token hết hạn (`readStoredSession`), nên trường đó phải là
thời điểm thật, không phải hằng số.

## Kiến trúc

### Nguyên tắc số một: graph giữ nguyên thuần khiết

**Không sửa một node nào trong `src/agents/`.**

`src/agents/` hiện là code chính sách tất định, không có I/O — đó là tính chất khiến toàn
bộ bảo đảm an toàn (S0–S3, HITL fail-closed) test được mà không cần dựng hạ tầng. Nhét
`emit()` vào trong node sẽ phá tính chất đó vĩnh viễn.

Mọi sự kiện FE cần đều **suy ra được** từ state mà graph trả về (`outcome`, `action_plan`,
`candidate_action_plan`, `step_results`, `citations`, `__interrupt__`). Vì vậy việc dịch
sang sự kiện nằm ở một tầng riêng bên ngoài graph.

### Ba thành phần mới

**`SessionEventBus`** — mỗi phiên một bus:
- danh sách WebSocket đang nghe,
- `sequence` tăng đơn điệu **trong phạm vi phiên**, xuyên qua nhiều lượt,
- bộ đệm vòng có trần (mặc định 200 sự kiện) để mất kết nối ngắn không nuốt mất
  `approval.required`.

**`TurnRunner`** — chạy graph rồi dịch kết quả thành `DriverEvent`. Đây là nơi duy nhất
biết cả hai thế giới. Sinh `turn_id`, phát sự kiện, và bảo đảm bất biến "đúng một sự kiện
terminal".

**`TokenStore` + `SessionRegistry`** — xem mục Auth.

### Vỏ sự kiện

Tái dùng đúng vỏ mà `src/api/ws.py` đã dựng cho `/ws/engineer`: `type`, `event_id`,
`sequence`, `trace_id`, `emitted_at`, `schema_version`, `payload`. Vỏ đó đã đúng hợp đồng
`api_spec.md` mục "Server event base"; khác biệt duy nhất là `sequence` giờ thuộc về
**phiên** chứ không phải **kết nối**, để reconnect không làm số nhảy lùi.

## Auth: một hồ sơ mặc định, chủ thể là phiên đăng nhập

Quyết định của nhóm ngày 2026-08-09: dùng một default-profile trước, mở rộng nhiều vai sau.

**Token mờ, không JWT.** `POST /auth/login` đối chiếu credential demo lấy từ settings, sinh
chuỗi ngẫu nhiên, lưu `TokenStore` in-memory ánh xạ token → **principal instance**.

Lý do không dùng JWT không phải vì đơn giản hơn, mà vì **mỗi lần login phải là một chủ thể
riêng**. Với một hồ sơ duy nhất, nếu quyền sở hữu gắn vào *người dùng* thì mọi phiên đều
thuộc cùng một người và mọi phép kiểm quyền đều trả về đúng cho tất cả — tức là không đóng
được gì. Gắn vào *phiên đăng nhập* thì hai tab trình duyệt không đọc được dữ liệu của nhau,
và khi thêm vai trò về sau chỉ cần nâng "chủ sở hữu = token" thành "chủ sở hữu = người
dùng" mà không phá gì.

`POST /sessions` tạo phiên gắn `owner = principal`. Mọi route sau kiểm
`session.owner == principal`. **`session_id` thôi được tin từ body**: client vẫn gửi nó,
nhưng server đối chiếu với principal của token trước khi làm bất cứ việc gì.

Đây cũng là lúc ràng buộc quyền sở hữu trong node approval (thêm ở PR #25) **bắt đầu có
nghĩa thật** thay vì chỉ là capability.

**Không làm cờ bật/tắt auth.** Cờ như vậy sẽ luôn ở trạng thái tắt trong test và dev, chỗ
nối mục dần, tới lúc bật lên thì vỡ. Bắt buộc token, kèm credential dev ghi trong tài liệu.
Tiện thể sửa `src/api/ws.py:10` — docstring đang nhắc cờ `AUTH_ENABLED` **không tồn tại**
trong `src/config.py`.

## Luồng HITL bất đồng bộ

| Bước | Đồng bộ / Nền | Sự kiện phát ra |
|---|---|---|
| `POST /turns/text` → trả `{turn_id}` ngay | Nền: chạy graph | `turn.accepted`, `assistant.status(routing)`, `plan.ready` |
| Graph dừng ở `interrupt` (có step S2) | — | `approval.required`, `assistant.status(waiting_approval)`; task kết thúc |
| `POST /approvals/{id}/decision` | **Đồng bộ**: kiểm quyền + chốt trong store | trả `200`, body chỉ có `approval_status` |
| Resume graph | Nền | `assistant.status(executing)`, `tool.result`×n, `assistant.response`, **đúng một** sự kiện terminal |

Việc tách đồng bộ/bất đồng bộ **không phải do FE tiện** mà đúng `api_spec.md:209`: phần
kiểm tra và consume là đồng bộ và nguyên tử; phần thực thi chạy tiếp bất đồng bộ và báo về
`/ws/ivi`. Toàn bộ bốn kiểm tra fail-closed đã viết ở PR #25 giữ nguyên vị trí, chỉ phần
thực thi dời ra sau.

Đường không cần duyệt (S0/S1, tra sổ tay, clarify) đi thẳng tới `assistant.response` +
`turn.completed` trong cùng một task nền.

## Bất biến — sẽ có test khoá từng cái

1. **Đúng một sự kiện terminal mỗi lượt.** Không bao giờ hai, không bao giờ không.
   `turn.completed` | `turn.canceled(reason)` | `turn.failed(code)` — loại trừ lẫn nhau.
2. **`sequence` tăng đơn điệu trong một phiên**, xuyên qua nhiều lượt và qua reconnect.
3. **Sáu đường hỏng của approval → `turn.canceled` đúng `reason`**, và **zero side effect**.
   Ánh xạ 1-1 từ outcome node đã có; không phát sinh logic mới.
4. **Idempotency:** cùng `Idempotency-Key` cho `/turns/text` và `/approvals/decision` →
   cùng kết quả, **không** tạo lượt thứ hai, **không** thực thi hai lần.
5. **Quyền sở hữu:** principal khác chủ phiên → `403`, không rò rỉ thông tin về việc phiên
   đó có tồn tại hay không.

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `src/api/auth.py` (tạo) | `POST /auth/login`, `TokenStore`, dependency `current_principal` |
| `src/api/sessions.py` (tạo) | `POST /sessions`, `SessionRegistry` gắn owner |
| `src/api/turns.py` (tạo) | `POST /turns/text` |
| `src/api/events.py` (tạo) | `SessionEventBus`, vỏ sự kiện, bộ đệm vòng |
| `src/api/turn_runner.py` (tạo) | Dịch kết quả graph → `DriverEvent`; giữ bất biến terminal |
| `src/api/idempotency.py` (tạo) | Kho khoá idempotency theo principal |
| `src/api/ws.py` (sửa) | Thêm `/ws/ivi`, kiểm subprotocol bearer; sửa docstring `AUTH_ENABLED` |
| `src/api/approvals.py` (sửa) | Bất đồng bộ hoá, kiểm quyền sở hữu |
| `src/api/session_state.py` (sửa) | Gắn phiên với principal |
| `src/config.py` (sửa) | Credential demo |

## Rủi ro

### 1. HAI NGUỒN TRẠNG THÁI XE — nghiêm trọng, có sẵn từ trước, cần quyết định riêng

Hệ thống đang có **hai simulator xe không nói chuyện với nhau**:

| Nguồn | Ai dùng |
|---|---|
| `src/agents/vehicle.py VehicleSimulator` (trong tiến trình) | Agent, executor, mọi kiểm tra an toàn HITL |
| `src/vehicle_sim/` qua MQTT → cache của backend | `GET /api/v1/vehicle/state` |

`src/agents/nodes/execute.py` gọi `vehicle.execute(...)` trên simulator trong tiến trình và
**không hề publish MQTT**. Trong khi đó `frontend/.../turn/types.ts` ghi rõ FE gọi lại
`getVehicleState()` **sau mỗi `tool.result` và `turn.completed`**.

**Hệ quả nhìn thấy được:** người dùng duyệt lệnh mở kính → lệnh báo thành công → FE đọc
`GET /vehicle/state` → **kính vẫn đóng**.

Đây là khoảng trống **có sẵn**, không phải do task này gây ra: `/agent/process` hôm nay đã
lệch như vậy. Nhưng nó khiến "end-to-end" chưa quan sát được trọn vẹn trên màn hình.

**Khuyến nghị:** executor publish lệnh lên `commands/{domain}` rồi chờ `events/command`
tương quan theo `command_id`, và mọi kiểm tra `state_version` đọc từ cache MQTT. `src/vehicle_sim/runtime.py`
đã hỗ trợ sẵn: nó subscribe `commands/+`, thực thi, phát `events/command`, và **đã xử lý
lệnh trùng `command_id`**. Đây là kiến trúc P0 đúng và cũng làm cho quyết định
"thực thi bất đồng bộ" có lý do vật lý chứ không chỉ vì spec bảo thế.

**Nhưng việc đó không nằm trong task này.** Nó chạm vào workstream MQTT (SCRUM-44, PR #18)
và làm khối lượng phình gần gấp đôi. Đề nghị tách thành ticket riêng, **làm ngay sau task
này**, và cho tới lúc đó phải ghi rõ trong README rằng trạng thái xe trên màn hình chưa
phản ánh lệnh vừa thực thi.

### 2. Test approval hiện có sẽ phải sửa

`tests/test_api/test_approval_routes.py` đang khẳng định `tool_results` nằm trong body
HTTP. Chuyển sang bất đồng bộ là **đổi hành vi có chủ đích**, không phải sửa test cho xanh.
Test mới phải khẳng định kết quả xuất hiện **trên WS**, và body chỉ còn `approval_status`.

### 3. Mất kết nối đúng lúc chờ duyệt

Bộ đệm sự kiện theo phiên xử lý được ngắt kết nối ngắn. Nhưng nếu người dùng đóng hẳn tab,
approval vẫn treo tới khi hết hạn 30 giây — đúng thiết kế fail-closed, cần nêu trong tài liệu.

### 4. Auth một hồ sơ không phải phân tách người dùng

Phải ghi đúng trong README: có phân tách **phiên đăng nhập**, **không** có phân tách người
dùng, **không** có phân quyền theo vai.

## Tiêu chí hoàn thành

1. Ba AC của ticket đạt, kiểm bằng test tự động chứ không bằng thao tác tay.
2. Năm bất biến ở mục trên đều có test khoá.
3. Toàn bộ suite hiện có vẫn xanh (nền: 420 passed, 8 skipped), trừ các test approval được
   sửa **có chủ đích** kèm lý do trong commit.
4. README ghi đúng trạng thái: auth một hồ sơ, và khoảng trống hai nguồn trạng thái xe.

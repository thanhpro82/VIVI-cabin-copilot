# ADR-014: `sequence`/`event_id` thuộc về session, không thuộc về connection — replay có giới hạn cho `/ws/ivi`

- Status: Accepted — phần server đã implement; phần client (FE gửi cursor khi reconnect) chưa làm
- Date: 2026-08-11
- Decision owner: Nguyễn Tuấn Thành
- Liên quan: ADR-013 (một nguồn vehicle state duy nhất), `docs/api_spec.md` mục "Ordering, replay, and recovery invariants", `docs/superpowers/specs/2026-08-09-hitl-e2e-ws-ivi-design.md` (SessionEventBus được phác nhưng chưa implement), `docs/superpowers/specs/2026-08-10-ws-ivi-event-reliability-design.md`

## Context

`IviEventBus` (`src/services/ivi_events.py`) ban đầu là pub/sub thuần: publish cho ai đang nghe, không lưu gì. `event_id`/`sequence` được `EventStream` (`src/api/ws.py`) sinh **mỗi connection** — reconnect là `EventStream` mới, `sequence` về 1, `event_id` đổi hoàn toàn. Không có retention, không có replay.

Hệ quả: nếu WebSocket rớt đúng lúc lượt HITL đang chờ duyệt (S2), sự kiện `approval.required` phát ra trong lúc mất kết nối không bao giờ tới được client. Approval vẫn còn hiệu lực ở backend (hết hạn sau 30s theo `docs/safety_and_hitl.md`), nhưng tài xế mất khả năng nhìn thấy nó để duyệt — khoảng trống trực tiếp mâu thuẫn với mục tiêu "voice-first HITL" của sản phẩm.

`docs/api_spec.md` đã ghim sẵn hợp đồng đầy đủ với FE (`connection.init` mang `last_event_id`/`last_sequence`, `REPLAY_CURSOR_INVALID`/`REPLAY_WINDOW_EXPIRED`, "sequence tăng đơn điệu xuyên qua reconnect", "replay giữ nguyên event_id/sequence"). Bản thiết kế PR #36 (`2026-08-09-hitl-e2e-ws-ivi-design.md`) đã phác một `SessionEventBus` với ring buffer 200 event để giải đúng vấn đề này, nhưng slice đó chỉ làm phần HITL đồng bộ/bất đồng bộ — phần replay chưa từng được viết.

## Decision

**`event_id`/`sequence` được gán đúng một lần, tại `IviEventBus.publish()`, theo session — không phải tại nơi gửi đi (connection).**

1. **`_SessionStream` theo `session_id`**: bộ đếm `sequence` đơn điệu (sống xuyên suốt nhiều lượt và mọi lần reconnect), ring buffer `deque(maxlen=200)` chứa event đã đóng gói đầy đủ, `last_active` (monotonic).
2. **`IviEventBus.replay_snapshot(session_id, last_event_id, last_sequence)`** xác thực cursor và trả về batch cần replay. Vì buffer là dải `sequence` liên tiếp, định vị cursor không cần state phụ:
   - thiếu đúng một trong hai field → `REPLAY_CURSOR_INVALID`
   - `last_sequence` lớn hơn sequence hiện tại (chưa từng phát sinh) → `REPLAY_CURSOR_INVALID`
   - `last_sequence` nhỏ hơn sequence sớm nhất còn giữ trong buffer (đã bị đẩy ra) → `REPLAY_WINDOW_EXPIRED`
   - cặp `(event_id, sequence)` không khớp cùng một event → `REPLAY_CURSOR_INVALID`
   - hợp lệ → mọi event sau cursor, giữ nguyên thứ tự
3. **`ivi_stream` (`src/api/ws.py`)** snapshot replay + đăng ký listener **liên tiếp, không có `await` chen giữa** (an toàn nhờ asyncio một luồng hợp tác, không cần lock). Live event phát sinh trong lúc đang gửi batch replay được giữ trong một buffer Python thuần (`pending_live`) và chỉ được lật cờ gửi trực tiếp **sau khi** buffer đó rỗng (`while pending_live: ...` rồi mới `replay_done = True`) — không dùng `asyncio.Queue`, vì bus của queue tạo trên loop của app không an toàn khi test dùng `TestClient` + `anyio.run` từ hai loop khác nhau (giới hạn cụ thể của bộ test trong repo này, không phải giới hạn kiến trúc chung).
4. **TTL hai tầng, tách phần nặng khỏi phần nhẹ.** `_BUFFER_TTL_SECONDS = 1800` (30 phút không hoạt động, không có listener → dọn nội dung buffer, GIỮ `sequence`); `_STREAM_TTL_SECONDS = 86400` (24 giờ → xoá hẳn entry). Tách để buffer bị dọn không kéo theo `sequence` reset về 0 cho cùng `session_id` — nếu không, `REPLAY_WINDOW_EXPIRED` (buffer mất) và `REPLAY_CURSOR_INVALID` (session chưa từng tồn tại) sẽ không còn phân biệt được. `replay_snapshot()` tự gọi sweep trước khi đọc buffer (không chỉ `publish()`/`add_listener()`), để việc buffer đã hết hạn hay chưa không phụ thuộc vào việc có session khác vừa publish gì đó hay không.
5. **`replay_snapshot()` không tạo entry mới cho session chưa từng tồn tại.** Dùng `_streams.get(session_id)` (đọc thuần) thay vì get-or-create — một client gửi cursor rác cho `session_id` bất kỳ (không có auth trên `/ws/ivi`) không được phép ghim bộ nhớ bằng những connection bị chính server từ chối.

## Consequences

### Được

- Reconnect trong cửa sổ 30 phút replay đúng thứ tự, giữ nguyên `event_id`/`sequence` — client dedupe được bằng `event_id`.
- `approval.required` phát ra trong lúc mất kết nối không còn bị mất — tài xế reconnect vẫn thấy được lệnh đang chờ duyệt (miễn còn trong hạn 30s của chính approval, không liên quan tới cửa sổ replay 30 phút).
- Ring buffer có giới hạn rõ ràng (200 event/session); phần tốn bộ nhớ nhất (payload) bị TTL dọn, không tăng vô hạn theo số session từng thấy.
- Live event sau replay không lẫn thứ tự, không trùng lặp — khoá bằng test dựng thread thật publish song song lúc đang gửi batch replay.

### Mất — ghi rõ, không lấp

**Chưa có gì ở phía FE dùng được tính năng này.** `frontend/src/lib/services/turn/real.ts`'s `connection.init` hiện chỉ gửi `session_id`, không bao giờ gửi `last_event_id`/`last_sequence`, và không lưu lại cursor giữa các lần connect. Protocol đã sẵn sàng phía server, đã có test khoá, nhưng **không quan sát được trên demo đang chạy** — AC "approval.required sống sót qua reconnect" được chứng minh ở tầng protocol/test (`emit_turn_lifecycle()` thật qua `IviEventBus`/`ivi_stream` thật), không phải bằng thao tác tay trên UI thật. Việc nối FE là ticket follow-up riêng.

**`_SessionStream` (phần nhẹ: 1 int + 1 float + list rỗng) sống tới 24 giờ mỗi `session_id`, không có eviction sớm hơn dù session đã "chết" theo nghĩa nghiệp vụ (logout, hết hạn token — hiện chưa có auth để biết điều đó).** Chấp nhận được cho demo một máy, in-memory, không persist — cùng mức đánh đổi `SessionRecord`/`ApprovalStore` đã chấp nhận.

**Không giải quyết bearer auth hay session ownership cho `/ws/ivi`.** `/ws/ivi` vẫn subscribe theo đúng `session_id` client tự khai trong `connection.init` — bất kỳ client nào cũng nghe được sự kiện của bất kỳ `session_id` nó đoán ra, và giờ còn replay lại lịch sử của session đó nữa. Đây là giới hạn có sẵn từ trước ADR này (ghi trong `src/api/ws.py`), không phải quy hồi mới, nhưng replay khiến khoảng trống đó lộ ra nhiều dữ liệu hơn mỗi lần bị khai thác — phải đóng cùng lúc với auth.

### Còn dang dở

Nối cursor vào FE (`frontend/src/lib/services/turn/real.ts`, lưu `last_event_id`/`last_sequence` sau mỗi event nhận được, gửi lại khi reconnect) — ticket riêng, chưa có người nhận.

## Alternatives considered

**`asyncio.Queue` per-connection để tách gửi live/replay khỏi `publish()`.** Đây là thiết kế ban đầu trong spec, bị thay bằng cờ boolean + list Python thuần trong lúc viết implementation plan: một `asyncio.Queue` tạo trên loop của app không an toàn khi `push()` (callback đăng ký với bus) bị gọi từ một loop khác — chính xác là cách bộ test của repo này verify `/ws/ivi` (`TestClient` chạy app trên loop nền riêng qua portal thread, test gọi `bus.publish()` qua `anyio.run()` từ loop thứ ba). Cờ + list giữ đúng lời hứa về thứ tự (đã chứng minh bằng hand-trace và một test dựng thread thật) mà không cần một primitive nhạy cảm với ranh giới event loop.

**Cho `_sweep_expired()` xoá hẳn `_SessionStream` khi buffer hết hạn (một tầng TTL duy nhất, như thiết kế nháp đầu tiên).** Bị loại giữa lúc brainstorm: xoá hẳn entry làm `sequence` khởi động lại từ 0 cho **cùng một `session_id`**, khiến "buffer đã mất" (nên trả `REPLAY_WINDOW_EXPIRED`) và "session chưa từng tồn tại" (nên trả `REPLAY_CURSOR_INVALID`) không còn phân biệt được — đúng loại lỗi fail-open âm thầm mà thiết kế này tồn tại để tránh. Tách hai tầng TTL (buffer 30 phút / stream metadata 24 giờ) giữ đúng ngữ nghĩa hai mã lỗi mà chỉ tốn thêm vài byte mỗi session.

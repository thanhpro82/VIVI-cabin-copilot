# Harden `/ws/ivi` Event Delivery & Reconnect — Design

**Trạng thái:** Thiết kế, chờ duyệt.
**Nhánh:** tách từ `develop` tại `31390e1`.
**Ngày:** 2026-08-10
**Ticket:** Harden `/ws/ivi` Event Delivery & Reconnect (Giai đoạn B, sau PR #36/#38).

## Mục tiêu

Driver IVI không được mất event khi WebSocket `/ws/ivi` bị disconnect/reconnect, đặc biệt
trong lúc đang chờ HITL approval — `approval.required` treo lơ lửng thì tài xế mất khả năng
duyệt lệnh dù approval vẫn còn hiệu lực ở backend.

## Hiện trạng và khoảng trống

`IviEventBus` (`src/services/ivi_events.py`) hiện là pub/sub thuần: publish cho ai đang nghe,
không lưu gì. `event_id`/`sequence` được `EventStream` (`src/api/ws.py`) sinh **mỗi connection**
— reconnect là `EventStream` mới, `sequence` về 1, `event_id` đổi hoàn toàn. Không có
retention, không có replay. Đây là giới hạn đã biết, ghi rõ trong docstring của cả hai file.

Bản thiết kế trước (`docs/superpowers/specs/2026-08-09-hitl-e2e-ws-ivi-design.md`, mục "Ba
thành phần mới") đã phác một `SessionEventBus` với ring buffer 200 event nhưng **chưa từng
được implement** trong PR #36 — slice đó tập trung vào luồng HITL đồng bộ/bất đồng bộ, không
làm phần replay. Thiết kế này hoàn thiện đúng phần còn nợ đó.

`docs/api_spec.md` mục "Ordering, replay, and recovery invariants" (dòng 637-647) đã ghim sẵn
hợp đồng đầy đủ với FE: `last_event_id`/`last_sequence` trong `connection.init`,
`REPLAY_CURSOR_INVALID`, `REPLAY_WINDOW_EXPIRED`, sequence không reset qua reconnect, replay
giữ nguyên `event_id`/`sequence`. Thiết kế này implement đúng hợp đồng đó, không tự chế hợp
đồng riêng.

## Phạm vi

**Trong phạm vi:**
- `sequence` thuộc về **session**, sống xuyên suốt nhiều lượt và nhiều lần reconnect — không
  còn thuộc về connection.
- Ring buffer có giới hạn (200 event/session) chứa event đã đóng gói đầy đủ.
- Replay đúng thứ tự sau reconnect, giữ nguyên `event_id` và `sequence`.
- `REPLAY_CURSOR_INVALID` / `REPLAY_WINDOW_EXPIRED` đúng theo `docs/api_spec.md`.
- Live event tiếp diễn đúng thứ tự sau replay, không trùng lặp.
- Event quan trọng (`plan.ready`, `approval.required`, `assistant.status(waiting_approval)`)
  được giữ lại vì đi qua đúng `IviEventBus.publish()` như mọi event khác — không cần đường
  riêng.
- Dọn tài nguyên theo TTL hai tầng để không tăng bộ nhớ vô hạn qua nhiều session.

**Ngoài phạm vi (giữ nguyên từ ticket):**
- Logic quyết định của Agent/HITL.
- Thực thi `VehicleGateway`.
- RAG.
- Bearer authentication cho WS (`/ws/ivi` vẫn chấp nhận mọi `session_id` client tự khai, đúng
  giới hạn đã ghi trong `src/api/ws.py`).
- Kiểm quyền sở hữu principal/session.
- `/ws/engineer` — không có replay, không đổi.

## Kiến trúc

### 1. Đóng gói event một lần, tại nơi sinh ra — không phải nơi gửi đi

Muốn replay giữ nguyên `event_id`/`sequence` (bất biến #2 trong
`2026-08-09-hitl-e2e-ws-ivi-design.md`), việc gán `event_id`/`sequence`/`emitted_at` phải xảy
ra **đúng một lần**, tại `IviEventBus.publish()` — không phải mỗi lần một connection nhận
event như hiện tại.

`src/api/ws.py`'s `EventStream` chỉ còn phục vụ `/ws/engineer` (không đổi) và các lỗi bắt tay
của `/ws/ivi` xảy ra **trước khi** `session_id` được xác nhận (chưa có stream nào để thuộc
về, nên không cần sequence theo session).

### 2. Cấu trúc dữ liệu theo session

```python
class _SessionStream:
    listeners: list[EventListener]
    sequence: int              # đơn điệu, KHÔNG BAO GIỜ reset một khi session_id đã tồn tại
    buffer: deque[dict]        # maxlen=200, event đã đóng gói đầy đủ (immutable sau khi tạo)
    last_active: float         # monotonic; cập nhật ở publish() VÀ sau khi listener attach
                                # thành công (không cập nhật khi handshake lỗi trước đó)
```

`IviEventBus` giữ `dict[str, _SessionStream]` theo `session_id`, thay cho
`dict[str, list[EventListener]]` hiện tại.

`publish()`: tăng `sequence`, wrap event đầy đủ, append vào `buffer` (deque tự đẩy phần tử cũ
khi vượt 200), cập nhật `last_active`, rồi phát cho `listeners` hiện có — cùng cấu trúc
try/except-per-listener như hiện tại (một listener lỗi không chặn listener khác).

### 3. Xác thực cursor khi reconnect

Vì `buffer` là dải `sequence` **liên tiếp** (mỗi publish tăng đúng 1), định vị cursor không
cần state phụ ngoài `stream.sequence` (bộ đếm hiện tại) và nội dung `buffer`:

```
earliest = buffer[0].sequence nếu buffer không rỗng, ngược lại stream.sequence + 1
nếu last_sequence > stream.sequence:
    → REPLAY_CURSOR_INVALID     # trỏ tới sequence chưa từng phát sinh
nếu last_sequence < earliest:
    → REPLAY_WINDOW_EXPIRED     # từng phát sinh thật, nhưng buffer đã bị dọn/đẩy ra
ngược lại:
    candidate = buffer[last_sequence - earliest]
    nếu candidate.event_id != last_event_id:
        → REPLAY_CURSOR_INVALID  # cặp (event_id, sequence) không khớp cùng một event
    ngược lại:
        replay = buffer[vị_trí_candidate + 1 :]   # mọi event SAU cursor, giữ nguyên thứ tự
```

`connection.init` thiếu đúng một trong hai field (`last_event_id`/`last_sequence`) →
`REPLAY_CURSOR_INVALID` ngay, không tra buffer (đúng dòng 531 api_spec.md: "Supplying only
one ... returns REPLAY_CURSOR_INVALID").

Lỗi cursor → gửi `error` (terminal=true, đúng code) rồi đóng `1003`, cùng cách
`WS_EVENT_INVALID` đang xử lý. Khớp mô tả dòng 646: client tự mở kết nối mới không kèm
cursor sau khi thấy `REPLAY_WINDOW_EXPIRED` — server không tự ý "hồi sinh" một stream coi như
chưa từng có lịch sử.

### 4. Không lẫn thứ tự giữa replay và live event

Nếu chỉ đăng ký listener rồi lần lượt `await websocket.send_json(...)` cho từng event replay,
một event **live** phát sinh giữa lúc đang gửi batch replay (route handler khác của cùng
session đang chạy song song) có thể chen ngang, vì listener đã được đăng ký từ trước khi gửi
xong batch — vi phạm "live events tiếp tục đúng thứ tự, không duplicate".

→ Mỗi connection dùng một `asyncio.Queue` nội bộ. `push(event)` (callback đăng ký với bus) chỉ
`queue.put_nowait(event)` — đồng bộ, không `await`, nên không thể bị một coroutine khác chen
vào giữa chừng. Một coroutine ghi riêng rút từ queue và gọi `websocket.send_json` tuần tự.

Lúc connect: snapshot `replay = [...]` (thuật toán mục 3) rồi `add_listener(push)` được làm
**liên tiếp, không có `await` chen giữa** — an toàn nhờ asyncio một luồng hợp tác, không cần
lock. Đẩy toàn bộ `replay` vào queue trước, sau đó listener tiếp tục đẩy live event vào cùng
queue đó — thứ tự FIFO của queue tự đảm bảo đúng thứ tự, không cần đồng bộ hoá thêm.

Tác dụng phụ có lợi: `publish()` không còn `await` trực tiếp một `websocket.send_json` có thể
chậm — giờ chỉ `put_nowait` (tức thời), giảm rủi ro một client chậm làm nghẽn việc phát event
cho các listener khác của cùng session.

### 5. Dọn tài nguyên theo TTL hai tầng

Tách phần **nặng** (buffer 200 event có payload đầy đủ) khỏi phần **nhẹ** (bộ đếm
`sequence`), để buffer bị dọn không kéo theo việc `sequence` reset về 0 cho cùng một
`session_id` — nếu không, `REPLAY_WINDOW_EXPIRED` (buffer mất) và `REPLAY_CURSOR_INVALID`
(session chưa từng tồn tại) sẽ không còn phân biệt được.

```python
_BUFFER_TTL_SECONDS = 1800    # 30 phút không hoạt động, không có listener → clear buffer,
                               # GIỮ sequence
_STREAM_TTL_SECONDS = 86400   # 24 giờ không hoạt động, không có listener → xoá hẳn entry
                               # (kể cả sequence) — CHỈ replay state của stream hết hạn, không
                               # phải session business record (SessionRecord vẫn theo lifecycle riêng)
```

Lazy sweep giống pattern `IdempotencyStore._PENDING_TTL_SECONDS`
(`src/services/idempotency.py`): mỗi lần `publish()` hoặc có connection `/ws/ivi` mới, tiện
thể quét mọi `_SessionStream` không có listener sống:

```
idle = now - last_active
nếu idle >= _STREAM_TTL_SECONDS:
    xoá hẳn entry
ngược lại nếu idle >= _BUFFER_TTL_SECONDS và buffer không rỗng:
    buffer.clear()   # sequence giữ nguyên
```

Một session đang có connection sống (`listeners` không rỗng) không bao giờ bị quét, dù
`last_active` cũ tới đâu.

**Đánh đổi đã ghi nhận:** sau khi buffer bị dọn (>30 phút idle), reconnect với cursor cũ nhận
đúng `REPLAY_WINDOW_EXPIRED` (không bị hiểu nhầm là session lạ). Sau 24 giờ hoàn toàn không
hoạt động, entry bị xoá sạch — cursor cũ lúc đó rơi vào `REPLAY_CURSOR_INVALID`, chấp nhận
được vì stream replay state hết hạn sau 24 giờ idle (**không** đồng nghĩa session business
record đã chết — `SessionRecord`/`ApprovalStore` có lifecycle riêng, tách bạch khỏi
`_SessionStream`); đây là cùng mức đánh đổi mà các store in-memory khác trong repo đã chấp
nhận cho một demo một-máy, không persist.

## Bất biến — sẽ có test khoá

1. `sequence` tăng đơn điệu trong phạm vi **session**, xuyên qua nhiều lượt và mọi lần
   reconnect trong vòng `_STREAM_TTL_SECONDS`.
2. Replay giữ nguyên `event_id` và `sequence` gốc — client dedupe bằng `event_id`.
3. Sau replay, live event tiếp tục đúng thứ tự ngay sau event replay cuối cùng, không lặp.
4. Cursor thiếu một trong hai field, hoặc cặp không khớp cùng một event đã phát sinh →
   `REPLAY_CURSOR_INVALID`.
5. Cursor hợp lệ về mặt sequence nhưng nội dung đã bị buffer dọn → `REPLAY_WINDOW_EXPIRED`,
   không lẫn với #4.
6. Ring buffer không vượt quá 200 event/session tại mọi thời điểm.
7. `approval.required` phát trước khi mất kết nối vẫn replay được sau khi reconnect trong cửa
   sổ retention, dù approval vẫn đang treo (S2 pending) lúc reconnect.
8. Một session có connection đang sống không bao giờ bị TTL sweep dọn, bất kể `last_active`.

## Cấu trúc file

| File | Thay đổi |
|---|---|
| `src/services/ivi_events.py` | `IviEventBus` đổi sang `_SessionStream` theo session; `publish()` wrap event; thêm `reset()` (giống `idempotency.reset()`) cho test |
| `src/api/ws.py` | `ivi_stream`: đọc `last_event_id`/`last_sequence` từ `connection.init`, validate cursor, snapshot+queue replay, vòng lặp ghi từ `asyncio.Queue`; `EventStream` giữ nguyên cho `/ws/engineer` và lỗi bắt tay trước khi có `session_id` |
| `tests/conftest.py` | Thêm `ivi_events.reset()` vào fixture dọn state giữa các test, cùng chỗ đang gọi `session_state.reset()`/`idempotency.reset()` |
| `tests/test_services/test_ivi_events.py` | Test `_SessionStream`: sequence không reset qua nhiều `publish()`, ring buffer cap 200, TTL hai tầng (giả lập `last_active` như test TTL hiện có của `idempotency`) |
| `tests/test_api/test_ws_ivi.py` | Cập nhật test hiện có (event giờ được wrap tại `publish()`, không phải tại forward) + test mới: reconnect giữa lúc S2 pending replay đúng `approval.required`, cursor invalid/expired, live event tiếp nối đúng thứ tự sau replay |

## Rủi ro

**Test hiện có ở `tests/test_api/test_ws_ivi.py` sẽ phải sửa.** `test_forwards_published_events_for_the_connected_session`
hiện giả định `sequence == 1` cho event đầu tiên của một connection — sau khi `sequence` thuộc
về session (đơn điệu xuyên suốt), giá trị đó chỉ đúng cho session hoàn toàn mới, và giả định
này phải đổi thành "sequence tăng đúng 1 so với event trước", không phải "luôn bắt đầu từ 1
mỗi connection". Đây là đổi hành vi có chủ đích, không phải sửa test cho xanh.

## Tiêu chí hoàn thành

Khớp Acceptance Criteria của ticket:

1. Disconnect rồi reconnect → retained events replay đúng thứ tự — test khoá.
2. `approval.required` không mất nếu rớt kết nối trong lúc chờ HITL — test disconnect/reconnect
   ở S2 pending approval.
3. Replayed event giữ nguyên `event_id`.
4. `sequence` không reset theo reconnect.
5. Client dedupe bằng `event_id` — đảm bảo bằng bất biến #2, không cần thêm gì phía server.
6. Ring buffer có giới hạn rõ ràng (200/session), không tăng vô hạn — TTL hai tầng chặn phần
   tốn bộ nhớ nhất (payload).
7. Sau replay, live event tiếp tục đúng thứ tự, không trùng lặp — hàng đợi per-connection.
8. Test cho disconnect/reconnect ở S2 pending approval.
9. Test lifecycle voice/text hiện có vẫn pass (trừ thay đổi có chủ đích đã nêu ở mục Rủi ro).
10. Ruff + full suite liên quan pass.

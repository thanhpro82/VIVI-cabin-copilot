# TASK-FE-BE-002 — Khoảng trống lộ ra khi bật real mode thật trên `/driver`

Bối cảnh: sau khi PR #35/#36/#37/#39/#41/#42/#43 merge, domino chặn cứng (auth →
session → turns/text → WS) đã hết — xem `TASK-FE-BE-001`. File này ghi lại
những gì lộ ra **chỉ khi thật sự bấm nút/gõ lệnh qua UI với backend thật**,
không phải đọc code suông. Phần lớn không phải bug FE — là khoảng trống ở
router/tool registry, cần BE quyết định làm tiếp hay bỏ khỏi P0.

## 1. Tool/router còn thiếu — xác nhận bằng cách đọc `src/agents/router.py` + test tay

| Tính năng | Vấn đề | Bằng chứng |
|---|---|---|
| Mở/khoá **mọi cửa** cùng lúc | `set_door_state` chỉ nhận đúng 1 cửa/lệnh — `Assistant._match_door` luôn cần `_side()` trả về **một** vị trí cụ thể, không có khái niệm "toàn xe" | Test "mở cửa"/"đóng cửa" không kèm vị trí → luôn `clarify` |
| **Cốp xe** (trunk) | Không tool nào trong registry điều khiển cốp | Test "mở cốp" → `"Xin lỗi, tôi không thực hiện được yêu cầu này."` |
| **Đèn pha** (lights) | Không tool nào điều khiển đèn | Test "bật đèn pha" → rơi vào RAG, `"Tôi không tìm thấy thông tin này trong sổ tay xe."` |
| **Quạt gió** (fan level) | `Assistant._match_hvac` chỉ xử lý `set_hvac_power`/`set_hvac_temperature` — không có `set_fan_level` hay tương đương trong toàn bộ registry | Test 3 cách nói khác nhau ("tăng quạt gió", "chỉnh quạt gió mức 3", "chỉnh quạt gió điều hòa mức 3") đều fail — 2 lần RAG, 1 lần denied |
| **Bài nhạc trước** (previous track) | `media_control` schema đã khai `action: "previous"` (`agent_spec.md`), nhưng `Assistant._match_music` không có nhánh phrase nào gọi tới nó — chỉ có "tạm dừng/dừng"→pause, "phát/bật/mở"→play, "chuyển/tiếp"→next | Test "bài trước" → RAG "không tìm thấy" dù tool đã tồn tại trong schema |

**Đề xuất:** 5 mục trên là tính năng FE đã dựng UI sẵn (nút bấm, slider) nhưng
không có đường nối thật ở router. Cần BE quyết định: làm tiếp (thêm nhánh
router + tool nếu thiếu) hay chính thức bỏ khỏi phạm vi P0 (cốp/đèn/quạt gió
có thể không cần thiết cho demo — nên ghi vào `api_spec.md`/ADR nếu bỏ, đừng
để im lặng).

## 2. Giọng nói — STT sẵn sàng, TTS cần BE quyết định kiến trúc

- **STT: đã test và hoạt động đúng.** Gửi audio rỗng, `_validate_audio()`
  (`src/services/voice.py:107`) bắt đúng, backend phát `error` + `turn.failed`
  qua `/ws/ivi` đàng hoàng, không crash, không treo. Không cần BE làm gì thêm
  cho STT.
- **TTS: chưa nối vào pipeline.** `voice.synthesize()` có sẵn trong
  `src/services/voice.py` nhưng **không được gọi ở bất kỳ đâu** trong luồng
  turn (`grep` toàn `src/api/turns.py`, `src/services/ivi_events.py`,
  `src/agents/nodes/compose.py` không ra kết quả nào). `speak_text` hiện tại
  chỉ là bản sao y hệt `display_text` (`ivi_events.py:221-225`, tự comment
  nhận là gap). Đây là **quyết định thiết kế cần BE**, không phải FE tự quyết
  được: gọi `synthesize()` ở bước nào trong turn, trả audio bằng cách nào
  (nhúng base64 vào payload event WS? endpoint riêng để FE fetch sau khi có
  `turn_id`?).
- Phần ghi âm thật ở FE (`MediaRecorder`) là việc của FE, không cần BE làm gì
  — nêu ở đây chỉ để BE thấy bức tranh đầy đủ: nút mic hiện gửi audio rỗng có
  chủ đích (`DriverShellProvider.tsx` tự comment, xem `feature/voice-asr-tts-design`).

## 3. Việc cũ vẫn còn treo (nhắc lại từ `TASK-FE-BE-001`, chưa ai đụng)

- **`citation_id` + RAG composer câu trả lời tổng hợp** (Nhân) — tra cứu sổ
  tay vẫn chỉ trả `excerpt` thô.
- **Event `ui.policy`** (6 cờ an toàn khi xe đang chạy) — chưa ai nhận việc.
- **Bug `src/api/ws.py:79-83`** (`engineer_stream`):
  ```python
  try:
      hello = await websocket.receive_json()
  except (WebSocketDisconnect, ValueError):
      await websocket.close(code=1003)   # nếu socket đã ngắt, dòng này tự ném lỗi mới, không ai bắt
      return
  ```
  Log traceback rác khi client ngắt kết nối giữa chừng (dễ gặp ở dev do React
  StrictMode mount/unmount 2 lần). Không sập server nhưng cần bọc
  `try/except` quanh chính `close()`. Chưa rõ ai giữ phần `/ws/engineer`.

## 4. Bug ở test suite (báo Sơn)

`tests/test_api/test_metrics_summary.py` — 4 test fail khi chạy chung cả
suite, pass khi chạy riêng lẻ (`pytest tests/test_api/test_metrics_summary.py`
một mình → xanh; chạy trong `pytest tests/` đầy đủ → có 4-5 test đỏ, tập hợp
test fail đổi giữa các lần chạy). Nghi ngờ rò rỉ state qua singleton
`_STORE`/`_BOOT_AT` module-level giữa các file test khác nhau trong cùng
session pytest — chưa root-cause sâu hơn, để dành cho người quen code này
hơn. **Không phải bug ở chính route** `/metrics/summary` — đã test tay xác
nhận route trả đúng dữ liệu phản ánh đúng số lượt gọi thật.

## 5. Không phải lỗi, chỉ để BE biết

- RAG không test được thật trên máy tôi vì thiếu corpus (~150MB, bản quyền
  VinFast, cố ý không nằm trong git — xem `VF9_2026_vi/README.md`). Cài xong
  `numpy`/`sentence-transformers`/`torch` thì nhánh RAG không còn crash 500
  nữa (trước đó thiếu `numpy` làm mọi câu không khớp router rơi vào 500) —
  giờ trả đúng "không tìm thấy" vì không có index, đúng hành vi mong đợi.
- `numpy`/`torch`/`jsonschema` thiếu sẵn ở venv một số máy trong nhóm — môi
  trường, không phải code (`pip install -e ".[dev]"` xong vẫn thiếu `numpy`
  dù đã khai trong `pyproject.toml` base deps — đáng kiểm lại quy trình cài
  đặt máy mới, nhưng không chặn gì hôm nay).

## Đã sửa ở FE trong PR này (không cần BE làm gì, chỉ để đối chiếu)

- **`DriverShellProvider.tsx` chưa từng tạo session** — nút bấm không hoạt
  động hoàn toàn im lặng ở real mode vì `currentSessionId()` throw mà
  `send()`/`openVoice()`/`approve()`/`reject()` gọi qua `void` (nuốt lỗi).
  Đã thêm tạo session tự động + `.catch()` khắp nơi.
- **Thiếu case `turn.failed`** khiến voice overlay treo vĩnh viễn khi audio
  rỗng khiến STT lỗi (event `turn.failed` không được xử lý để đóng overlay).
- **Toàn bộ câu lệnh cửa/cửa sổ/ghế/nhạc ở `VehicleControlView.tsx` và
  `MusicView.tsx` sai từ vựng router thật** — viết theo `mock.ts` tự chế chứ
  không đối chiếu `router.py`. Chi tiết đầy đủ + bảng đối chiếu câu cũ/mới ở
  commit message. Đã sửa 10 câu lệnh, verify từng cái bằng test tay với
  backend thật (200, đúng tool được gọi).
- **`StatTileRow.tsx`**: label `"ngưỡng <3.000ms"` dùng dấu chấm kiểu phân
  cách nghìn Việt Nam, dễ đọc nhầm thành 3ms (giá trị thật là 3000ms = 3
  giây) — đổi thành `"<3000ms"` cho rõ. Logic so sánh (`p50 < 3000`) vốn đã
  đúng, chỉ là label gây hiểu lầm.

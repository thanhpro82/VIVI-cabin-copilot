# Design: Nối `voice.synthesize()` vào turn pipeline (issue #66)

Status: approved for implementation planning
Date: 2026-08-11 (revised sau vòng review thứ 2: đổi delivery mechanism, xem "Revision" bên dưới)

## Context

`src/services/voice.py::synthesize()` (Piper TTS) tồn tại nhưng không được gọi ở bất kỳ đâu trong turn pipeline. `speak_text` trong `assistant_response_payload()` (`src/services/ivi_events.py:219-239`) hiện chỉ là bản sao `display_text` — tài xế chưa hề nghe tiếng nói thật, dù sản phẩm được mô tả "voice-first". `stage_latencies_ms.tts` (một trong 7 stage cố định ở `src/services/trace_store.py:33-41`, khớp `docs/api_spec.md:342`) luôn `0` vì không có gì để đo. `GET /healthz` đã probe `tts` thật (warm singleton, PR #55) nhưng engine đó chưa từng được gọi ngoài probe.

Scope lần này: **chỉ BE** — nối `synthesize()` vào pipeline và đẩy audio ra qua `/ws/ivi`. Không đụng frontend; `frontend/src/lib/services/turn/*.ts` hiện không phát audio ở đâu cả (`speakText` chỉ là field text chưa dùng để play), đó là gap FE riêng, không thuộc ticket này.

**Ràng buộc đã xác nhận khi khảo sát code:**

1. `assistant.response` payload là **closed schema** — `docs/api_spec.md:568` liệt kê đúng 4 field (`display_text`, `speak_text`, `citations`, `outcomes`) và nói rõ "Additional fields are rejected unless the negotiated schema version allows them." Audio không được nhúng vào payload này.
2. `docs/api_spec.md:52` chốt **"P0 public surface — exactly 12 interfaces"** — một bảng đóng, đếm rõ ràng. Thêm một HTTP route mới (ví dụ `GET /turns/{turn_id}/audio`) sẽ là interface thứ 13, tức mở rộng phạm vi P0 mà CLAUDE.md nói rõ không được làm âm thầm ("do not silently widen a documented scope boundary").

## Revision: dùng WS event mới thay vì HTTP endpoint mới

Bản thiết kế đầu tiên định thêm `GET /api/v1/turns/{turn_id}/audio` — bị chặn bởi ràng buộc #2 ở trên. Thay vào đó: đẩy audio qua **`WS /ws/ivi`**, interface **đã có sẵn** (#11 trong bảng 12 interfaces) — không tăng số lượng interface, chỉ thêm một **event type mới** vào "Driver server-event allowlist" (`docs/api_spec.md` mục cùng tên), đúng kiểu bảng đó vốn đã mở (10/15 type đã liệt kê được implement, phần còn lại là gap đã biết, không phải closed set). Cách này còn khớp với mô tả gốc ở `docs/VIVI_API_Spec.md:178`: *"WS /ws/ivi: Push thông báo trạng thái xe ảo realtime, Popup HITL và **âm thanh TTS streaming**."*

Hệ quả: bỏ hẳn `AudioStore`, bỏ hẳn endpoint GET, bỏ câu hỏi ownership/eviction — audio phát đúng một lần tại thời điểm turn hoàn tất, y hệt cách text đã chảy qua `assistant.response`, không cần cache lại để ai đó fetch sau.

## Architecture

### Hook point: `emit_turn_lifecycle`

`emit_turn_lifecycle` (`src/services/ivi_events.py:276-419`) là điểm hội tụ duy nhất của 3 call site đang gọi nó trong `src/api/turns.py` (dòng 239, 378, 433 — voice turn, text turn, waiting-approval) — sửa một chỗ thay vì lặp lại ở từng route. Bên trong hàm, **sau** nhánh `pending`/`__interrupt__` return sớm (dòng 287-312 — nhánh này không bao giờ phát `assistant.response`, nên không cần synth) và **trước** dòng `outcome = result.get("outcome", "not_control")` (dòng 314):

```python
wav_bytes = await _synthesize_speech(turn_id, trace_id, result.get("response_text", ""))
```

`wav_bytes` là `bytes | None` — `None` nếu text rỗng hoặc synth lỗi (fail-open). Giá trị này được truyền xuống một helper publish dùng chung cho **cả 5 nhánh** hiện đang gọi `await bus.publish(session_id, "assistant.response", turn_id, trace_id, assistant_response_payload(result))` (dòng 344, 369, 379, 393, 415):

```python
await _publish_assistant_response(bus, session_id, turn_id, trace_id, result, wav_bytes)
```

thay vì gọi `bus.publish("assistant.response", ...)` trực tiếp ở cả 5 chỗ.

### `_synthesize_speech` (hàm mới, private, trong `ivi_events.py`)

```python
async def _synthesize_speech(turn_id: str, trace_id: str, text: str) -> bytes | None:
    if not text.strip():
        return None
    started = time.perf_counter()
    try:
        wav_bytes = await asyncio.to_thread(voice.synthesize_wav, text)
    except Exception:
        logger.warning("TTS synthesize thất bại cho turn %s", turn_id, exc_info=True)
        return None
    get_trace_store().record_stage(trace_id, "tts", (time.perf_counter() - started) * 1000)
    return wav_bytes
```

`asyncio.to_thread` đúng pattern CPU-bound đã dùng cho STT (`turns.py:172`, `voice.transcribe`) — không block event loop. Bọc `try/except Exception`, log warning kèm `turn_id`, không re-raise — TTS không bao giờ chặn `assistant.response`/`turn.completed`.

### `voice.synthesize_wav` (hàm mới trong `src/services/voice.py`, cạnh `synthesize()`)

```python
def synthesize_wav(text: str) -> bytes:
    engine = get_tts_engine()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(engine.sample_rate)
        for pcm_chunk in engine.synthesize_stream(text):
            wav_file.writeframes(pcm_chunk)
    return buffer.getvalue()
```

`io` và `wave` đã import sẵn ở đầu `voice.py` (dùng cho STT). Đặt hàm gói WAV cạnh `synthesize()`/`PiperEngine` thay vì trong `ivi_events.py` vì đây là chi tiết encode của tầng voice, không phải của tầng event — `ivi_events.py` chỉ gọi một hàm trả về bytes.

### `_publish_assistant_response` (hàm mới, private, trong `ivi_events.py`)

```python
async def _publish_assistant_response(
    bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, result: dict[str, Any], wav_bytes: bytes | None
) -> None:
    if wav_bytes is not None:
        await bus.publish(
            session_id,
            "assistant.speech",
            turn_id,
            trace_id,
            {"audio_base64": base64.b64encode(wav_bytes).decode("ascii"), "mime_type": "audio/wav"},
        )
    await bus.publish(session_id, "assistant.response", turn_id, trace_id, assistant_response_payload(result))
```

`assistant.speech` phát **trước** `assistant.response` — client biết audio đã sẵn sàng trước khi thấy text, không bắt buộc thứ tự ngược lại nhưng giữ nhất quán một chiều. `assistant_response_payload()` không đổi (vẫn đúng 4 field cũ).

### Latency & `stage_latencies_ms`

`stage_latencies_ms.tts` sẽ thôi luôn là `0` cho mọi turn có speech tổng hợp thành công. Tuy nhiên `end_to_end` **không** bao gồm latency này: `src/api/turns.py` gọi `_record_end_to_end(trace_id, started)` — chốt `end_to_end` — **trước** khi gọi `emit_turn_lifecycle` (nơi TTS synth và `record_stage(trace_id, "tts", ...)` chạy). `end_to_end` đã bị niêm phong xong xuôi trước khi `tts` được đo, nên `tts` là một stage độc lập, không phải thành phần cộng dồn vào `end_to_end`.

### Fail-open

Nếu `synthesize_wav()` raise (model thiếu, lỗi runtime): log warning, `_synthesize_speech` trả `None`, không set `record_stage("tts", ...)` (field ở lại `None` — đúng ngữ nghĩa "stage không chạy", `trace_store.py:47-52`), `_publish_assistant_response` bỏ qua việc phát `assistant.speech`. `assistant.response`/`turn.completed` vẫn bắn bình thường với `speak_text` là text. TTS không bao giờ là single point of failure cho turn — hợp lý vì Piper engine chưa từng chạy thật ở P0 ngoài health probe.

## Data flow

```
graph.ainvoke() → result (có response_text)
  → emit_turn_lifecycle(bus, session_id, turn_id, trace_id, result)
      → [sau nhánh __interrupt__ early-return]
      → wav_bytes = await _synthesize_speech(turn_id, trace_id, result["response_text"])
            → nếu text rỗng hoặc synth lỗi: None (fail-open, log warning)
            → nếu thành công: WAV bytes + record_stage(trace_id, "tts", ms)
      → (một trong 5 nhánh outcome) → _publish_assistant_response(..., wav_bytes)
            → [nếu wav_bytes] publish "assistant.speech" {audio_base64, mime_type}
            → publish "assistant.response" (không đổi: display_text/speak_text/citations/outcomes)
      → publish "turn.completed" | "turn.failed" | "turn.canceled"
```

## Testing

- `tests/test_services/test_voice.py`: unit test `synthesize_wav()` — gọi engine giả trả PCM chunk cố định, assert WAV bytes decode lại đúng qua stdlib `wave` (đúng số kênh/sample width/frame rate/nội dung).
- `tests/test_services/test_ivi_events.py`: thêm case cho `emit_turn_lifecycle` —
  - `response_text` không rỗng + `voice.synthesize_wav` mock trả bytes cố định → `assistant.speech` phát **trước** `assistant.response`, payload đúng `{audio_base64, mime_type}` (decode base64 khớp bytes gốc).
  - `response_text` rỗng (ví dụ outcome không có text) → không phát `assistant.speech`.
  - `voice.synthesize_wav` mock raise exception → không phát `assistant.speech`, nhưng `assistant.response`/`turn.completed` vẫn phát đủ như cũ (không raise ra ngoài `emit_turn_lifecycle`).
  - Nhánh `__interrupt__`/waiting-approval → `voice.synthesize_wav` không được gọi (assert qua mock `call_count == 0`), vì nhánh này không có `assistant.response`.
- Test API turn hiện có (`test_turns_voice.py`, `test_turns_text.py`) không cần stub thêm gì mới để pass: `voice.synthesize_wav`/`get_tts_engine` không mock → gọi thật → raise (model không có trên CI hoặc `piper` chưa cài) → bị `_synthesize_speech` nuốt, log warning, lifecycle event không đổi. Xác nhận bằng cách chạy lại suite hiện có sau khi implement, không cần sửa các test đó.
- Mock `voice.synthesize_wav`/`voice.get_tts_engine` trong mọi test cần audio thật thành công — không tải Piper model thật trong suite nhanh.

## Docs

- Thêm một dòng mới vào bảng "Driver server-event allowlist and required payload" (`docs/api_spec.md`, mục cùng tên) cho `assistant.speech`: required payload `audio_base64:string`, `mime_type="audio/wav"`. Không đổi số đếm "12 interfaces" — đây vẫn là `WS /ws/ivi` (#11), chỉ thêm vốn từ vựng event.
- Cập nhật dòng gap trong CLAUDE.md ("Piper TTS is not wired into the pipeline... The driver hears nothing.") sau khi implement xong, phản ánh trạng thái mới.

## Out of scope

- FE playback (nghe qua `<audio>` hay Web Audio API) — gap FE riêng, `speakText`/audio hiện chưa được UI nào tiêu thụ.
- Streaming audio thật theo từng PCM chunk qua WS — `assistant.speech` gửi một blob WAV hoàn chỉnh sau khi synth xong toàn bộ text, không phát nhiều event nhỏ dần.
- Giới hạn kích thước `audio_base64`/nén — text turn ở P0 ngắn (một câu xác nhận), chấp nhận payload base64 vài chục KB; không cần giải quyết ở ticket này.
- Persist audio (SQLite) — không lưu ở đâu cả sau khi phát, khớp "Nothing is persisted" đã ghi trong CLAUDE.md.
- Auth/ownership — không đổi gì so với hiện tại, `/ws/ivi` đã có cơ chế owner-check riêng (issue #47) không thuộc phạm vi ticket này.

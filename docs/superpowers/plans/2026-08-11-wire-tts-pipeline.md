# Nối TTS vào turn pipeline (issue #66) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nối `src/services/voice.py::synthesize()` (Piper TTS) vào turn pipeline, để tài xế nghe được audio thật thay vì `speak_text` chỉ là bản sao text của `display_text`.

**Architecture:** Thêm `voice.synthesize_wav(text) -> bytes` (gói PCM stream có sẵn thành WAV). Gọi nó một lần trong `emit_turn_lifecycle` (`src/services/ivi_events.py`) ngay sau nhánh `__interrupt__` early-return, chạy qua `asyncio.to_thread` để không block event loop. Kết quả (`bytes | None`, fail-open khi lỗi) được phát qua một event WS **mới** — `assistant.speech` — ngay trước `assistant.response`, trên cùng interface `WS /ws/ivi` đã có (không thêm HTTP endpoint mới, không đổi số đếm "12 interfaces" của `docs/api_spec.md:52`, không đổi schema đóng của `assistant.response`). Độ trễ synth được ghi vào `stage_latencies_ms.tts` qua `TraceStore.record_stage` đã có sẵn.

**Tech Stack:** Python 3.11, FastAPI, stdlib `wave`/`asyncio`/`base64`, Piper TTS (`src/services/voice.py`), pytest + `monkeypatch`.

## Global Constraints

- `assistant.response` payload giữ nguyên đúng 4 field (`display_text`, `speak_text`, `citations`, `outcomes`) — không thêm field audio vào đó (`docs/api_spec.md:568`, closed schema).
- Không thêm HTTP interface mới — `docs/api_spec.md:52` chốt "exactly 12 interfaces"; audio đi qua `WS /ws/ivi` (#11) đã có.
- TTS lỗi (model thiếu, exception bất kỳ) **không bao giờ** được chặn `assistant.response`/`turn.completed`/`turn.failed`/`turn.canceled` — fail-open, chỉ log warning.
- CPU-bound synth phải chạy qua `asyncio.to_thread`, không block event loop — đúng pattern STT hiện có (`turns.py:172`).
- Test suite root phải chạy với `MQTT_ENABLED=false` (`$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`), không tự ý bật `MQTT_ENABLED=true`.
- Không mock kiểu bừa: mọi test cần audio thành công phải `monkeypatch.setattr` đúng vào `voice.synthesize_wav`/`voice.get_tts_engine`, không tải Piper model thật.
- Lint: `ruff check src/ tests/` và `ruff format src/ tests/` (line-length 120) phải sạch trước khi commit mỗi task.

---

## Task 1: `voice.synthesize_wav()` — gói PCM stream thành WAV bytes

**Files:**
- Modify: `src/services/voice.py` (thêm hàm mới ngay sau `synthesize()`, dòng 187-192)
- Test: `tests/test_services/test_voice.py`

**Interfaces:**
- Produces: `synthesize_wav(text: str) -> bytes` — gọi `get_tts_engine()` (đã có, `@lru_cache`), trả về WAV file hoàn chỉnh (mono, 16-bit PCM, `framerate = engine.sample_rate`). Raise bất kỳ exception nào `get_tts_engine()`/`engine.synthesize_stream()` raise (không tự bắt lỗi ở đây — caller ở Task 2 chịu trách nhiệm fail-open).

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_services/test_voice.py` (file này đã có sẵn `_FakeAudioChunk`, `_FakeVoiceConfig`, `_FakeVoice` ở dòng 226-247 — tái dùng nguyên xi):

```python
def test_synthesize_wav_returns_a_valid_wav_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services import voice as voice_module
    from src.services.voice import get_tts_engine, synthesize_wav

    get_tts_engine.cache_clear()
    chunks = [b"\x00\x01" * 50, b"\x02\x03" * 50]
    fake_voice = _FakeVoice(chunks, sample_rate=22050)
    monkeypatch.setattr(voice_module, "get_tts_engine", lambda: PiperEngine(fake_voice))

    wav_bytes = synthesize_wav("Xin chào")

    assert fake_voice.received_text == "Xin chào"
    buffer = io.BytesIO(wav_bytes)
    with wave.open(buffer, "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 22050
        pcm_out = wav_file.readframes(wav_file.getnframes())
    assert pcm_out == b"".join(chunks)

    get_tts_engine.cache_clear()
```

Kiểm tra `io`, `wave`, `pytest` đã import ở đầu file (đã có, dùng cho các test STT/TTS khác); `PiperEngine` đã có trong import block dòng 13.

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice.py::test_synthesize_wav_returns_a_valid_wav_file -v`
Expected: FAIL — `ImportError: cannot import name 'synthesize_wav'`

- [ ] **Step 3: Viết implementation**

Trong `src/services/voice.py`, thêm ngay sau hàm `synthesize()` (sau dòng 191-192):

```python
def synthesize_wav(text: str) -> bytes:
    """Gói PCM stream của `synthesize()` thành một file WAV hoàn chỉnh (mono, 16-bit)."""
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

`io` và `wave` đã import sẵn ở đầu `voice.py` (dòng 3, 8) — không cần thêm import.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_voice.py -v`
Expected: PASS toàn bộ file (test mới + các test TTS/STT cũ không bị ảnh hưởng)

- [ ] **Step 5: Lint và commit**

```bash
ruff check src/services/voice.py tests/test_services/test_voice.py
ruff format src/services/voice.py tests/test_services/test_voice.py
git add src/services/voice.py tests/test_services/test_voice.py
git commit -m "feat(voice): add synthesize_wav() to wrap Piper PCM stream as WAV bytes"
```

---

## Task 2: Nối TTS vào `emit_turn_lifecycle` + phát event `assistant.speech`

**Files:**
- Modify: `src/services/ivi_events.py`
- Test: `tests/test_services/test_ivi_events.py`

**Interfaces:**
- Consumes: `voice.synthesize_wav(text: str) -> bytes` (Task 1); `TraceStore.record_stage(trace_id: str, stage: str, latency_ms: float) -> None` (đã có, `src/services/trace_store.py:197`).
- Produces: WS event type mới `"assistant.speech"`, payload `{"audio_base64": str, "mime_type": "audio/wav"}`, phát qua `bus.publish(session_id, "assistant.speech", turn_id, trace_id, payload)` **ngay trước** mọi lần phát `"assistant.response"`, chỉ khi synth thành công.

- [ ] **Step 1: Viết 4 test thất bại**

Thêm vào cuối `tests/test_services/test_ivi_events.py` (file đã có sẵn `_RecordingBus` dòng 206-213, `_FakeInterrupt` dòng 216-218, `_plan()` dòng 221-239 — tái dùng nguyên xi). Thêm `import base64` và `from src.services import voice` vào đầu file nếu chưa có.

```python
async def test_speech_synthesis_success_emits_assistant_speech_before_assistant_response(monkeypatch):
    monkeypatch.setattr(voice, "synthesize_wav", lambda text: b"FAKE-WAV-BYTES")

    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 24 độ.",
        "step_results": [],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert types.index("assistant.speech") == types.index("assistant.response") - 1
    speech_payload = bus.events[types.index("assistant.speech")]["payload"]
    assert speech_payload["mime_type"] == "audio/wav"
    assert base64.b64decode(speech_payload["audio_base64"]) == b"FAKE-WAV-BYTES"


async def test_empty_response_text_does_not_synthesize_speech(monkeypatch):
    def _fail_if_called(text):
        raise AssertionError("synthesize_wav should not be called for empty text")

    monkeypatch.setattr(voice, "synthesize_wav", _fail_if_called)

    bus = _RecordingBus()
    result = {"outcome": "not_control", "response_text": ""}

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert "assistant.speech" not in types
    assert "assistant.response" in types


async def test_speech_synthesis_failure_is_swallowed_and_does_not_block_lifecycle(monkeypatch):
    def _raise(text):
        raise RuntimeError("piper model missing")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)

    bus = _RecordingBus()
    result = {
        "outcome": "completed",
        "response_text": "Đã đặt điều hòa 24 độ.",
        "step_results": [],
        "action_plan": _plan(),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert "assistant.speech" not in types
    assert types[-1] == "turn.completed"
    assert bus.events[types.index("assistant.response")]["payload"]["display_text"] == "Đã đặt điều hòa 24 độ."


async def test_pending_approval_never_synthesizes_speech(monkeypatch):
    def _fail_if_called(text):
        raise AssertionError("synthesize_wav should not be called while a turn is waiting on approval")

    monkeypatch.setattr(voice, "synthesize_wav", _fail_if_called)

    bus = _RecordingBus()
    result = {
        "__interrupt__": [
            _FakeInterrupt(
                {
                    "approval_id": "appr-1",
                    "plan_id": "plan-1",
                    "prompt_text": "Bạn xác nhận: mở cửa sổ?",
                    "steps_summary": [{"tool": "set_window_position", "safety_level": "S2"}],
                    "expires_at": "2026-08-09T00:00:30Z",
                    "timeout_seconds": 30,
                }
            )
        ],
        "action_plan": _plan(requires_approval=True),
    }

    await emit_turn_lifecycle(bus, "ses-1", "turn-1", "tr-1", result)

    types = [event["type"] for event in bus.events]
    assert "assistant.speech" not in types
    assert "assistant.response" not in types
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -k speech_synthesis or empty_response_text or pending_approval_never -v`
Expected: FAIL — `types.index("assistant.speech")` raises `ValueError` (event chưa tồn tại), vì `emit_turn_lifecycle` chưa gọi TTS.

- [ ] **Step 3: Viết implementation**

Trong `src/services/ivi_events.py`, sửa import block ở đầu file (dòng 9-18): thêm `asyncio`, `base64`, và hai import mới:

```python
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from src.agents.contracts import as_action_plan
from src.agents.nodes.compose import describe_step
from src.models.vehicle import SCHEMA_VERSION, utc_now
from src.services import voice
from src.services.trace_store import get_trace_store

logger = logging.getLogger(__name__)
```

Thêm hai hàm mới **ngay trước** `emit_turn_lifecycle` (trước dòng 276, sau `_emit_plan_ready`):

```python
async def _synthesize_speech(turn_id: str, trace_id: str, text: str) -> bytes | None:
    """TTS best-effort cho một lượt: không bao giờ raise, không chặn assistant.response/turn.completed.

    Xem docs/superpowers/specs/2026-08-11-wire-tts-pipeline-design.md §Fail-open.
    """
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


async def _publish_assistant_response(
    bus: IviEventBus, session_id: str, turn_id: str, trace_id: str, result: dict[str, Any], wav_bytes: bytes | None
) -> None:
    """Phát `assistant.speech` (nếu có audio) rồi `assistant.response`.

    `assistant.speech` không nằm trong 4 field cố định của `assistant.response`
    (docs/api_spec.md:568 — closed schema) nên đi qua một event type riêng,
    cùng interface `WS /ws/ivi` đã có (#11 trong 12 interface P0,
    docs/api_spec.md:52) — không thêm HTTP endpoint mới.
    """
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

Trong `emit_turn_lifecycle`, ngay sau khối `__interrupt__` (sau dòng `return` ở cuối khối `if pending:`, tức ngay trước dòng `outcome = result.get("outcome", "not_control")`), thêm:

```python
    wav_bytes = await _synthesize_speech(turn_id, trace_id, result.get("response_text", ""))

    outcome = result.get("outcome", "not_control")
```

Sau đó thay **cả 5** chỗ đang gọi:

```python
    await bus.publish(session_id, "assistant.response", turn_id, trace_id, assistant_response_payload(result))
```

bằng:

```python
    await _publish_assistant_response(bus, session_id, turn_id, trace_id, result, wav_bytes)
```

Năm chỗ này nằm trong nhánh `outcome in ("completed", "execution_failed")`, nhánh `outcome == "blocked"`, nhánh `outcome == "vehicle_state_unavailable"`, nhánh `cancel_reason is not None`, và nhánh mặc định cuối hàm (composing). Không đổi bất kỳ dòng nào khác trong các nhánh đó (thứ tự publish `plan.ready`/`assistant.status`/`tool.result`/`action.blocked` trước `assistant.response`, và `turn.completed`/`turn.failed`/`turn.canceled` sau, giữ nguyên).

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -v`
Expected: PASS toàn bộ file — 4 test mới, và toàn bộ test cũ (test_completed_outcome, test_execution_failed, test_blocked, test_interrupt, v.v.) vẫn pass nguyên vì `wav_bytes` mặc định `None` khi `voice.synthesize_wav` không được mock (raise trong thread, bị `_synthesize_speech` nuốt).

- [ ] **Step 5: Lint và commit**

```bash
ruff check src/services/ivi_events.py tests/test_services/test_ivi_events.py
ruff format src/services/ivi_events.py tests/test_services/test_ivi_events.py
git add src/services/ivi_events.py tests/test_services/test_ivi_events.py
git commit -m "feat(voice): wire TTS synthesis into turn lifecycle via new assistant.speech WS event"
```

---

## Task 3: Xác nhận toàn bộ turn API test cũ vẫn xanh + cập nhật docs

**Files:**
- Modify: `docs/api_spec.md` (thêm dòng bảng "Driver server-event allowlist and required payload")
- Modify: `CLAUDE.md` (cập nhật mục "Piper TTS is not wired into the pipeline")
- Verify: `tests/test_api/test_turns_voice.py`, `tests/test_api/test_turns_text.py`, toàn bộ suite root

**Interfaces:**
- Không thêm API mới ở task này — chỉ verify hành vi fail-open đã đúng trên đường API thật (không mock TTS) và cập nhật tài liệu.

- [ ] **Step 1: Chạy toàn bộ suite root, xác nhận không có test nào vỡ**

Run: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS — cùng số lượng `603 passed, 15 skipped` như trước khi có thay đổi (`test_turns_voice.py`/`test_turns_text.py` không mock `voice.synthesize_wav`, nên trên máy không có model Piper, `_synthesize_speech` sẽ raise và bị nuốt — lifecycle event không đổi, không có test nào assert số lượng event tuyệt đối bị lệch vì `assistant.speech` không phát khi synth lỗi).

Nếu có test nào vỡ vì đột nhiên xuất hiện `assistant.speech` (nghĩa là máy chạy test *có* model Piper thật cài sẵn và synth thành công ngoài ý muốn) — đó là dấu hiệu môi trường test có side effect ngoài dự kiến; dừng lại và báo cáo thay vì tự ý sửa assertion để né.

- [ ] **Step 2: Thêm dòng event mới vào `docs/api_spec.md`**

Tìm bảng "Driver server-event allowlist and required payload" (mục `### Driver server-event allowlist and required payload`), ngay sau dòng:

```
| `assistant.response` | session, turn | `display_text`, `speak_text`, `citations:array`, `outcomes:array` |
```

thêm dòng mới ngay bên trên nó (audio phát trước response text):

```
| `assistant.speech` | session, turn | `audio_base64:string`, `mime_type="audio/wav"` |
| `assistant.response` | session, turn | `display_text`, `speak_text`, `citations:array`, `outcomes:array` |
```

Thêm một câu ghi chú ngay dưới bảng (cạnh câu "The `transcript.final` event occurs exactly once..." đã có): `assistant.speech` là best-effort — phát trước `assistant.response` khi TTS tổng hợp thành công trong lượt đó, vắng mặt hoàn toàn (không có event rỗng/lỗi) khi synth thất bại hoặc `response_text` rỗng; client không được coi thiếu event này là lỗi giao thức.

- [ ] **Step 3: Cập nhật CLAUDE.md**

Tìm đoạn (trong mục "Where the implementation still falls short of the spec"):

```
- **Piper TTS is not wired into the pipeline.** `synthesize()` exists in `src/services/voice.py` but no caller in the turn path invokes it; `speak_text` is currently a copy of `display_text`. The driver hears nothing.
```

Thay bằng:

```
- **Piper TTS is wired into the turn pipeline** (issue #66): `emit_turn_lifecycle` (`src/services/ivi_events.py`) calls `voice.synthesize_wav()` off the event loop thread and publishes a new `assistant.speech` WS event (`audio_base64`/`mime_type="audio/wav"`) immediately before `assistant.response`, fail-open on any TTS error. `speak_text` in `assistant.response` is still text-only (unchanged, closed schema) — the frontend does not yet play the audio anywhere (`frontend/src/lib/services/turn/*.ts` captures `speakText` as a string but never feeds it to an `<audio>` element); that FE wiring remains a gap.
```

- [ ] **Step 4: Lint docs không cần chạy (Markdown, không thuộc `ruff check src/ tests/`) — chỉ kiểm tra chính tả/format thủ công bằng cách đọc lại đoạn vừa sửa.**

- [ ] **Step 5: Commit**

```bash
git add docs/api_spec.md CLAUDE.md
git commit -m "docs: document assistant.speech WS event and close out the TTS-not-wired gap note"
```

---

## Self-review notes (đã áp dụng khi viết plan này)

- **Spec coverage:** Hook point (Task 2), WAV encoding (Task 1), latency/`stage_latencies_ms.tts` (Task 2, `_synthesize_speech`), fail-open (Task 2, test 3), docs (Task 3) — tất cả mục trong `docs/superpowers/specs/2026-08-11-wire-tts-pipeline-design.md` đều có task tương ứng. "Out of scope" (FE playback, streaming thật, persist, auth) cố ý không có task — đúng theo spec.
- **Type consistency:** `synthesize_wav(text: str) -> bytes` (Task 1) khớp chữ ký dùng trong `asyncio.to_thread(voice.synthesize_wav, text)` (Task 2). `_synthesize_speech(turn_id: str, trace_id: str, text: str) -> bytes | None` khớp cách gọi `wav_bytes = await _synthesize_speech(...)` và tham số `wav_bytes: bytes | None` của `_publish_assistant_response`.
- **Placeholder scan:** không còn "TBD"/"tương tự Task N" — mọi step có code đầy đủ.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-11-wire-tts-pipeline.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

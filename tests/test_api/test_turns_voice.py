"""POST /api/v1/turns/voice — chấp nhận audio, chạy STT bất đồng bộ, phát lifecycle
qua /ws/ivi. Xem docs/superpowers/specs/2026-08-09-voice-turn-api-design.md."""

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from src.api import session_state, turns
from src.main import app
from src.services import voice
from tests.conftest import seed_test_user
from tests.test_api.ws_helpers import ivi_connect_kwargs, login, login_engineer, receive_n


@pytest.fixture(autouse=True)
def _stub_tts_unavailable(monkeypatch):
    """TTS luôn thất bại mặc định trong file này — không phụ thuộc việc máy chạy test
    có sẵn model Piper thật hay không (issue #66). Test nào cần audio thành công tự
    override bằng monkeypatch.setattr(voice, "synthesize_wav", ...) riêng trong thân test."""

    def _raise(text):
        raise FileNotFoundError("no TTS model in test environment")

    monkeypatch.setattr(voice, "synthesize_wav", _raise)


def _owned_session(user_id: str = "usr_driver_01") -> str:
    """Phiên có `SessionRecord` thật, do `user_id` sở hữu.

    Seed user trước khi tạo phiên: `sessions.user_id` là FOREIGN KEY từ PR #89, nên
    dựng phiên cho một chủ nhân không tồn tại sẽ `IntegrityError`. Trước bản sửa này,
    các test dùng `usr_driver_99` chỉ xanh **nhờ file khác tình cờ seed trước** — chạy
    riêng một file là đỏ. Phụ thuộc thứ tự kiểu đó tệ hơn một test đỏ thẳng, vì nó chỉ
    lộ ra khi ai đó chạy đúng một file để gỡ lỗi.
    """
    seed_test_user(user_id)
    return session_state.create_session(user_id, "vehicle-demo-01").session_id


def _connection_init(session_id: str) -> dict:
    return {
        "type": "connection.init",
        "client_message_id": "cmsg_1",
        "sent_at": "2026-08-09T00:00:00Z",
        "schema_version": "1.0",
        "session_id": session_id,
    }


def _stub_stt(monkeypatch, transcribe) -> None:
    """Thay cả engine và `transcribe_raw`.

    `_process_voice_turn` lấy engine tách riêng (Finding 4) nên test phải stub luôn, không
    thì mọi case rơi vào FileNotFoundError vì máy CI không có model faster-whisper.
    """
    monkeypatch.setattr(voice, "get_stt_engine", lambda: object())
    monkeypatch.setattr(voice, "transcribe_raw", transcribe)


def _voice_headers(token: str, content_type: str, idempotency_key: str | None = None) -> dict:
    """Header set for a `/turns/voice` call. `idempotency_key` stays optional here — Task 3
    is what makes the route require it; passing `None` (the default) omits the header so
    Task 1/2 tests, written before that requirement exists, keep working unchanged."""
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Schema-Version": "1.0",
        "Content-Type": content_type,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def test_s1_voice_command_runs_full_lifecycle_to_turn_completed(monkeypatch):
    _stub_stt(
        monkeypatch,
        lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=5.0, confidence=0.9),
    )

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))

            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers=_voice_headers(token, "audio/wav", idempotency_key="voice:s1:001"),
                content=b"fake-wav-bytes",
            )
            assert response.status_code == 202
            body = response.json()
            assert body["data"]["status"] == "accepted"
            assert body["data"]["input_mode"] == "voice"
            assert body["data"]["session_id"] == session_id
            assert body["meta"]["realtime"] == "WS /ws/ivi"
            turn_id = body["data"]["turn_id"]

            events = receive_n(ws, 9)

    types = [event["type"] for event in events]
    assert types == [
        "turn.accepted",
        "assistant.status",
        "transcript.final",
        "assistant.status",
        "plan.ready",
        "assistant.status",
        "tool.result",
        "assistant.response",
        "turn.completed",
    ]
    assert all(event["turn_id"] == turn_id for event in events)
    assert all(event["session_id"] == session_id for event in events)
    assert events[1]["payload"]["state"] == "transcribing"
    assert events[2]["payload"] == {
        "text": "Đặt điều hòa 22 độ",
        "language": "vi",
        "confidence": 0.9,
        "transcription_status": "completed",
    }
    assert events[3]["payload"]["state"] == "routing"
    # `plan.ready` nằm giữa `routing` và `executing` — đúng thứ tự api_spec.md:620
    # (`routing` → `plan.ready` → rẽ nhánh chính sách).
    assert events[4]["payload"]["requires_approval"] is False
    assert events[5]["payload"]["state"] == "executing"
    assert events[6]["payload"]["status"] == "completed"


def test_bad_content_type_returns_422_and_never_schedules_a_turn(monkeypatch):
    def _fail_if_called(_audio_bytes):
        raise AssertionError("transcribe should not be called for a rejected content type")

    _stub_stt(monkeypatch, _fail_if_called)

    with TestClient(app) as client:
        token = login(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-bad-ct"},
            headers=_voice_headers(token, "audio/webm", idempotency_key="voice:badct:001"),
            content=b"whatever",
        )

    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "INPUT_INVALID"


@pytest.mark.parametrize(
    ("content_type", "accepted"),
    [
        ("audio/wav", True),
        # `MediaRecorder` của browser gửi `.type` kèm parameter — khớp chuỗi nguyên thì
        # mọi blob thật đều 422.
        ("audio/wav; codecs=1", True),
        ("audio/wav;codecs=1", True),
        ("AUDIO/WAV", True),
        ("audio/ogg", True),
        ("audio/ogg; codecs=opus", True),
        ("audio/pcm;rate=16000;channels=1;format=s16le", True),
        ("audio/pcm; rate=16000; channels=1; format=s16le", True),
        ("audio/pcm;channels=1;format=s16le;rate=16000", True),
        ("audio/webm;codecs=opus", False),
        ("application/octet-stream", False),
        ("", False),
        # `audio/pcm` không tự mô tả được: thiếu hoặc sai bất kỳ tham số nào là từ chối.
        # `split(";")[0]` không được vô tình nhận mọi `audio/pcm;<gì cũng được>`.
        ("audio/pcm", False),
        ("audio/pcm;rate=8000", False),
        ("audio/pcm;rate=8000;channels=1;format=s16le", False),
        ("audio/pcm;rate=16000;channels=2;format=s16le", False),
        ("audio/pcm;rate=16000;channels=1", False),
    ],
)
def test_content_type_allowlist_compares_base_media_type(content_type, accepted):
    assert turns._is_accepted_content_type(content_type) is accepted  # noqa: SLF001


def test_content_type_decision_reaches_the_endpoint(monkeypatch):
    """Cùng ba case bắt buộc của finding, nhưng đi qua route thật để chốt vòng dây."""
    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    def _post(client, token, session_id, content_type, idempotency_key):
        return client.post(
            "/api/v1/turns/voice",
            params={"session_id": session_id},
            headers=_voice_headers(token, content_type, idempotency_key=idempotency_key),
            content=b"fake-audio",
        )

    with TestClient(app) as client:
        token = login(client)
        wav_session = _owned_session()
        pcm_session = _owned_session()
        assert _post(client, token, wav_session, "audio/wav; codecs=1", "voice:ct:wav:001").status_code == 202
        assert (
            _post(
                client, token, pcm_session, "audio/pcm;rate=16000;channels=1;format=s16le", "voice:ct:pcmok:001"
            ).status_code
            == 202
        )
        bad = _post(client, token, "ses-ct-pcm-bad", "audio/pcm;rate=8000", "voice:ct:pcmbad:001")

    assert bad.status_code == 422
    assert bad.json()["detail"]["error"]["code"] == "INPUT_INVALID"


def test_unusable_audio_emits_unusable_transcript_and_turn_failed(monkeypatch):
    def _raise(_audio_bytes):
        raise ValueError("audio must be 16kHz mono WAV")

    _stub_stt(monkeypatch, _raise)

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))

            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers=_voice_headers(token, "audio/wav", idempotency_key="voice:unusable:001"),
                content=b"not-really-wav",
            )
            assert response.status_code == 202

            events = receive_n(ws, 5)

    types = [event["type"] for event in events]
    assert types == ["turn.accepted", "assistant.status", "transcript.final", "error", "turn.failed"]
    assert events[2]["payload"] == {
        "text": "",
        "language": "vi",
        "confidence": 0.0,
        "transcription_status": "unusable",
    }
    assert events[3]["payload"]["code"] == "STT_FAILED"
    assert events[4]["payload"]["code"] == "STT_FAILED"


def test_stt_misconfiguration_is_reported_as_internal_error_not_unusable_audio(monkeypatch):
    """Cấu hình `STT_PROVIDER` sai không được đổ lỗi cho micro của tài xế.

    `voice.get_stt_engine()` raise `ValueError` cho provider không hỗ trợ — cùng loại
    exception mà `_validate_audio` dùng cho audio hỏng. Phải phân biệt được hai thứ.
    """

    def _unsupported_provider():
        raise ValueError("unsupported STT_PROVIDER: only faster_whisper is implemented, got 'whisper_cpp'")

    monkeypatch.setattr(voice, "get_stt_engine", _unsupported_provider)
    monkeypatch.setattr(
        voice,
        "transcribe_raw",
        lambda audio_bytes: pytest.fail("transcribe_raw không được gọi khi engine chưa dựng được"),
    )

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))

            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers=_voice_headers(token, "audio/wav", idempotency_key="voice:sttmis:001"),
                content=b"perfectly-fine-audio",
            )
            assert response.status_code == 202

            events = receive_n(ws, 4)

    types = [event["type"] for event in events]
    # Không có `transcript.final(unusable)`: audio chưa hề bị đánh giá.
    assert types == ["turn.accepted", "assistant.status", "error", "turn.failed"]
    assert events[2]["payload"]["code"] == "INTERNAL_ERROR"
    assert events[3]["payload"]["code"] == "INTERNAL_ERROR"


def test_transcribe_runs_off_the_event_loop_thread(monkeypatch):
    """Chứng minh `asyncio.to_thread` thật, không phải một lời gọi chặn trong coroutine.

    Trong `TestClient`, `client.post()` chờ `BackgroundTasks` xong mới trả về, nên không
    thể lấy "202 về trước khi xử lý xong" làm mốc kiểm. Tính chất kiểm được — và là tính
    chất thật sự quan trọng — là STT **không** chạy trên thread của event loop: bên trong
    một worker thread `asyncio.get_running_loop()` phải raise `RuntimeError`.
    """
    observed: dict = {}

    def _record(audio_bytes):
        observed["thread"] = threading.current_thread()
        try:
            asyncio.get_running_loop()
            observed["has_running_loop"] = True
        except RuntimeError:
            observed["has_running_loop"] = False
        return voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0, confidence=0.5)

    _stub_stt(monkeypatch, _record)

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))
            response = client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers=_voice_headers(token, "audio/wav", idempotency_key="voice:offthread:001"),
                content=b"fake-wav-bytes",
            )
            assert response.status_code == 202
            events = receive_n(ws, 9)

    assert observed["has_running_loop"] is False, "transcribe chạy ngay trong coroutine, chặn event loop"
    assert observed["thread"] is not threading.main_thread()
    assert [event["type"] for event in events][-1] == "turn.completed"


async def test_concurrent_turns_on_one_session_never_invoke_the_graph_concurrently(monkeypatch):
    """Hai lượt song song trên cùng session phải tuần tự hoá ở `graph.ainvoke`.

    Không tuần tự hoá thì `ainvoke` thứ hai bỏ rơi interrupt S2 đang chờ của lượt đầu và
    lượt đó không bao giờ có terminal event.
    """
    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    tracker = {"in_flight": 0, "peak": 0, "calls": 0}

    class _SlowGraph:
        async def ainvoke(self, state, config=None):
            tracker["calls"] += 1
            tracker["in_flight"] += 1
            tracker["peak"] = max(tracker["peak"], tracker["in_flight"])
            # Nhường điều khiển: nếu không có khoá, lượt kia sẽ vào đây ngay tại đây.
            await asyncio.sleep(0.05)
            tracker["in_flight"] -= 1
            return {"outcome": "clarify", "response_text": "Bạn muốn cụ thể thế nào?"}

    monkeypatch.setattr(turns, "get_graph", lambda session_id: _SlowGraph())

    await asyncio.gather(
        turns._process_voice_turn("ses-lock", "turn-1", "tr-1", b"audio-1"),  # noqa: SLF001
        turns._process_voice_turn("ses-lock", "turn-2", "tr-2", b"audio-2"),  # noqa: SLF001
    )

    assert tracker["calls"] == 2
    assert tracker["peak"] == 1, "hai ainvoke chồng nhau trên cùng thread checkpointer"


async def test_different_sessions_are_not_serialized_against_each_other(monkeypatch):
    """Khoá phải theo từng session — không được biến server thành đơn luồng toàn cục."""
    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    tracker = {"in_flight": 0, "peak": 0}

    class _SlowGraph:
        async def ainvoke(self, state, config=None):
            tracker["in_flight"] += 1
            tracker["peak"] = max(tracker["peak"], tracker["in_flight"])
            await asyncio.sleep(0.05)
            tracker["in_flight"] -= 1
            return {"outcome": "clarify", "response_text": "Bạn muốn cụ thể thế nào?"}

    monkeypatch.setattr(turns, "get_graph", lambda session_id: _SlowGraph())

    await asyncio.gather(
        turns._process_voice_turn("ses-lock-a", "turn-1", "tr-1", b"audio-1"),  # noqa: SLF001
        turns._process_voice_turn("ses-lock-b", "turn-2", "tr-2", b"audio-2"),  # noqa: SLF001
    )

    assert tracker["peak"] == 2


def test_route_is_in_the_public_openapi_surface():
    assert "/api/v1/turns/voice" in app.openapi()["paths"]


def test_missing_bearer_token_returns_401():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-noauth"},
            headers={"X-Schema-Version": "1.0", "Content-Type": "audio/wav"},
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_engineer_role_cannot_submit_a_voice_turn():
    with TestClient(app) as client:
        token = login_engineer(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-wrongrole"},
            headers=_voice_headers(token, "audio/wav"),
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert response.json()["error"]["message"] == "yêu cầu vai trò 'driver'"


def test_missing_schema_version_returns_400():
    with TestClient(app) as client:
        token = login(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses-voice-noschema"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "audio/wav",
                "Idempotency-Key": "voice:noschema:001",
            },
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"
    assert response.json()["error"]["message"] == "thiếu hoặc sai X-Schema-Version, cần đúng '1.0'"


def test_nonexistent_session_returns_403_forbidden_not_404():
    with TestClient(app) as client:
        token = login(client)
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": "ses_does_not_exist"},
            headers=_voice_headers(token, "audio/wav", idempotency_key="voice:nonexist:001"),
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_cross_owner_session_returns_403_forbidden_not_404():
    """Nhánh 'session tồn tại nhưng thuộc người khác' của cùng if — kiểm riêng khỏi
    'session không tồn tại' ở trên, cùng lý do test_turns_text.py đã tách hai case này."""
    with TestClient(app) as client:
        token = login(client)
        other_session = session_state.create_session(seed_test_user("usr_someone_else"), "vehicle-demo-01")
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": other_session.session_id},
            headers=_voice_headers(token, "audio/wav", idempotency_key="voice:crossowner:001"),
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_missing_idempotency_key_returns_400():
    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        response = client.post(
            "/api/v1/turns/voice",
            params={"session_id": session_id},
            headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0", "Content-Type": "audio/wav"},
            content=b"fake-wav-bytes",
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


def test_replaying_the_same_idempotency_key_and_audio_returns_the_same_turn_id_without_a_second_background_task(
    monkeypatch,
):
    import anyio

    def _assert_no_further_event(ws, timeout: float = 0.3) -> None:
        async def _try_receive():
            with anyio.fail_after(timeout):
                return await ws._send_rx.receive()  # noqa: SLF001 - same technique as ws_helpers.receive_n

        try:
            message = ws.portal.call(_try_receive)
        except TimeoutError:
            return
        raise AssertionError(f"expected no further WS event on replay, got: {message}")

    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        headers = _voice_headers(token, "audio/wav", idempotency_key="voice:replay:001")

        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))

            first = client.post(
                "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"same-audio"
            )
            receive_n(ws, 9)

            second = client.post(
                "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"same-audio"
            )
            _assert_no_further_event(ws)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()


def test_same_idempotency_key_with_different_audio_returns_409(monkeypatch):
    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        headers = _voice_headers(token, "audio/wav", idempotency_key="voice:conflict:001")

        first = client.post(
            "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"audio-one"
        )
        second = client.post(
            "/api/v1/turns/voice", params={"session_id": session_id}, headers=headers, content=b"audio-two"
        )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_same_idempotency_key_and_audio_across_two_different_sessions_returns_409(monkeypatch):
    """`session_id` phải nằm trong fingerprint (Finding 1): cùng Idempotency-Key + cùng audio
    bytes nhưng gửi tới hai session KHÁC nhau (cả hai đều thuộc cùng tài xế) phải là một
    fingerprint khác nhau — 409 IDEMPOTENCY_CONFLICT, không phải trả lại envelope của session
    kia. Không có fix, request thứ hai sẽ replay 202 với `turn_id` của session đầu, và session
    thứ hai không bao giờ có lượt nào chạy."""
    _stub_stt(monkeypatch, lambda audio_bytes: voice.Transcript(text="Đặt điều hòa 22 độ", latency_ms=1.0))

    with TestClient(app) as client:
        token = login(client)
        session_a = _owned_session()
        session_b = _owned_session()
        headers = _voice_headers(token, "audio/wav", idempotency_key="voice:crosssession:001")

        first = client.post(
            "/api/v1/turns/voice", params={"session_id": session_a}, headers=headers, content=b"same-audio"
        )
        second = client.post(
            "/api/v1/turns/voice", params={"session_id": session_b}, headers=headers, content=b"same-audio"
        )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# --- Áp suất lốp qua đường NÓI (#168, review @thanhpro82) -----------------------


def test_hoi_ap_suat_lop_bang_giong_noi_doc_duoc_so_that(monkeypatch):
    """Đường **nói** phải lấy `vehicle_id` từ phiên, không gán cứng.

    Bug @thanhpro82 bắt ở review #168: `_process_voice_turn` gán cứng `"veh-demo"`,
    trong khi profile xe lưu theo `vehicle-demo-01`. Nên `get_vehicle_profile()` luôn
    rỗng → `is_complete=False` → bảng áp suất luôn fail-closed → lượt **nói** luôn rơi
    về breadcrumb *"Xem > Vành và bánh xe > Áp suất lốp"*.

    Đúng câu mà #168 sinh ra để xoá, và lời phàn nàn gốc là người dùng **nói**.

    Vì sao mọi test cũ bỏ lọt: chúng gọi thẳng `compose_node`, hoặc đi qua
    `/turns/text` — cả hai đều không chạm nhánh voice. Test này cố ý đi hết đường HTTP.
    """
    from src.services import vehicle_profile

    _stub_stt(
        monkeypatch,
        lambda audio_bytes: voice.Transcript(text="Áp suất lốp tiêu chuẩn là bao nhiêu", latency_ms=5.0, confidence=0.9),
    )
    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        vehicle_profile.set_vehicle_profile("vehicle-demo-01", trim="plus", battery="catl")
        try:
            with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
                ws.send_json(_connection_init(session_id))
                res = client.post(
                    "/api/v1/turns/voice",
                    params={"session_id": session_id},
                    headers=_voice_headers(token, "audio/wav", idempotency_key="voice:lop:001"),
                    content=b"fake-wav-bytes",
                )
                assert res.status_code == 202
                events = receive_n(ws, 8)
        finally:
            vehicle_profile.reset()

    noi = " ".join(
        e["payload"].get("display_text", "") for e in events if e["type"] == "assistant.response"
    )
    assert "260" in noi and "270" in noi, f"phai doc so that, nhan duoc: {noi!r}"
    assert "Xem >" not in noi, "van dang doc breadcrumb"


def test_giong_noi_chua_khai_bao_cau_hinh_thi_khong_doc_so(monkeypatch):
    """Chiều ngược, đi qua cùng đường HTTP: chưa có profile thì **không** được đoán số.

    Cặp với test trên. Thiếu nó thì một lần nữa gán cứng `vehicle_id` sẽ làm test kia
    đỏ nhưng không ai biết fail-closed còn đúng hay không.
    """
    from src.services import vehicle_profile

    _stub_stt(
        monkeypatch,
        lambda audio_bytes: voice.Transcript(text="Áp suất lốp tiêu chuẩn là bao nhiêu", latency_ms=5.0, confidence=0.9),
    )
    vehicle_profile.reset()
    with TestClient(app) as client:
        token = login(client)
        session_id = _owned_session()
        with client.websocket_connect("/ws/ivi", **ivi_connect_kwargs(token)) as ws:
            ws.send_json(_connection_init(session_id))
            client.post(
                "/api/v1/turns/voice",
                params={"session_id": session_id},
                headers=_voice_headers(token, "audio/wav", idempotency_key="voice:lop:002"),
                content=b"fake-wav-bytes",
            )
            events = receive_n(ws, 8)

    noi = " ".join(e["payload"].get("display_text", "") for e in events if e["type"] == "assistant.response")
    assert "kPa" not in noi and "PSI" not in noi, f"khong duoc doan so khi chua biet cau hinh: {noi!r}"

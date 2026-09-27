import io
import json
import wave
from pathlib import Path

import pytest

from scripts.generate_voice_hitl_fpt_audio import (
    PHRASES,
    VOICE_REGIONS,
    build_requests,
    manifest_line,
    request_payload,
    validate_wav_16k_mono,
    wav_duration_ms,
    write_dataset,
)


def _wav_bytes(*, sample_rate: int = 16000, channels: int = 1, sampwidth: int = 2, num_frames: int = 1600) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sampwidth)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * num_frames * channels)
    return buffer.getvalue()


def test_build_requests_covers_every_phrase_times_every_voice() -> None:
    requests = build_requests(("đồng ý", "từ chối"), {"std_banmai": "north", "std_giahuy": "south"})

    assert len(requests) == 4
    assert {r.reference_text for r in requests} == {"đồng ý", "từ chối"}
    assert {r.voice_code for r in requests} == {"std_banmai", "std_giahuy"}


def test_build_requests_assigns_region_from_voice_map() -> None:
    requests = build_requests(("đồng ý",), {"std_banmai": "north"})

    assert requests[0].region == "north"


def test_build_requests_audio_ids_are_unique() -> None:
    requests = build_requests(PHRASES, VOICE_REGIONS)

    audio_ids = [r.audio_id for r in requests]
    assert len(audio_ids) == len(set(audio_ids))


def test_all_ten_confirmation_phrases_are_present() -> None:
    assert set(PHRASES) == {
        "đồng ý",
        "xác nhận",
        "chấp nhận",
        "duyệt",
        "từ chối",
        "hủy",
        "đừng",
        "thôi",
        "không",
        "không đồng ý",
    }


def test_request_payload_asks_for_16k_mono_wav() -> None:
    payload = request_payload("đồng ý", "std_banmai")

    assert payload["input"] == "đồng ý"
    assert payload["voice"] == "std_banmai"
    assert payload["sample_rate"] == 16000
    assert payload["response_format"] == "wav"


def test_validate_wav_16k_mono_accepts_matching_audio() -> None:
    validate_wav_16k_mono(_wav_bytes())  # does not raise


def test_validate_wav_16k_mono_rejects_wrong_sample_rate() -> None:
    with pytest.raises(ValueError, match="16 kHz mono"):
        validate_wav_16k_mono(_wav_bytes(sample_rate=8000))


def test_validate_wav_16k_mono_rejects_stereo() -> None:
    with pytest.raises(ValueError, match="16 kHz mono"):
        validate_wav_16k_mono(_wav_bytes(channels=2))


def test_wav_duration_ms_matches_frame_count() -> None:
    duration = wav_duration_ms(_wav_bytes(sample_rate=16000, num_frames=1600))

    assert duration == 100


def test_manifest_line_has_all_required_fields() -> None:
    requests = build_requests(("đồng ý",), {"std_banmai": "north"})

    line = manifest_line(requests[0], relative_path="a1.wav", duration_ms=900)

    assert line == {
        "audio_id": requests[0].audio_id,
        "path": "a1.wav",
        "reference_text": "đồng ý",
        "speaker_code": "std_banmai",
        "region": "north",
        "noise_condition": "synthetic-tts",
        "duration_ms": 900,
        "consent_scope": "internal-poc-evaluation",
    }


def test_write_dataset_calls_http_post_once_per_request_and_writes_manifest(tmp_path: Path) -> None:
    requests = build_requests(("đồng ý", "từ chối"), {"std_banmai": "north"})
    calls = []

    def fake_http_post(payload: dict) -> bytes:
        calls.append(payload)
        return _wav_bytes()

    manifest_lines = write_dataset(requests, fake_http_post, tmp_path)

    assert len(calls) == 2
    assert len(manifest_lines) == 2
    for line in manifest_lines:
        assert (tmp_path / line["path"]).is_file()
    manifest_path = tmp_path / "manifest.jsonl"
    written = [json.loads(row) for row in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert written == manifest_lines


def test_write_dataset_skips_a_failing_request_without_aborting_the_rest(tmp_path: Path) -> None:
    requests = build_requests(("đồng ý", "từ chối"), {"std_banmai": "north"})
    call_count = 0

    def flaky_http_post(payload: dict) -> bytes:
        nonlocal call_count
        call_count += 1
        if payload["input"] == "đồng ý":
            raise RuntimeError("FPT request failed")
        return _wav_bytes()

    manifest_lines = write_dataset(requests, flaky_http_post, tmp_path)

    assert call_count == 2
    assert len(manifest_lines) == 1
    assert manifest_lines[0]["reference_text"] == "từ chối"

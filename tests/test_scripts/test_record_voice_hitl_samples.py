import json
import wave
from pathlib import Path

import numpy as np

from scripts.record_voice_hitl_samples import (
    append_manifest_line,
    audio_id_for,
    build_manifest_line,
    make_confirm_fn,
    run_session,
    samples_to_wav_bytes,
)


def test_audio_id_for_encodes_phrase_speaker_and_take() -> None:
    assert audio_id_for(3, "spk01", 2) == "hitl-03-real-spk01-t2"


def test_samples_to_wav_bytes_round_trips_16k_mono_pcm() -> None:
    samples = np.zeros(1600, dtype=np.int16)

    wav_bytes = samples_to_wav_bytes(samples, sample_rate=16000)

    with wave.open(__import__("io").BytesIO(wav_bytes), "rb") as handle:
        assert handle.getframerate() == 16000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == 1600


def test_build_manifest_line_has_all_required_fields() -> None:
    line = build_manifest_line(
        audio_id="hitl-01-real-spk01-t1",
        reference_text="Đồng ý",
        speaker_code="spk01",
        region="north",
        noise_condition="quiet-room",
        relative_path="hitl-01-real-spk01-t1.wav",
        duration_ms=900,
    )

    assert line == {
        "audio_id": "hitl-01-real-spk01-t1",
        "path": "hitl-01-real-spk01-t1.wav",
        "reference_text": "Đồng ý",
        "speaker_code": "spk01",
        "region": "north",
        "noise_condition": "quiet-room",
        "duration_ms": 900,
        "consent_scope": "internal-poc-evaluation",
    }


def test_append_manifest_line_creates_file_when_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"

    append_manifest_line(manifest_path, {"a": 1})

    assert json.loads(manifest_path.read_text(encoding="utf-8").strip()) == {"a": 1}


def test_append_manifest_line_appends_without_clobbering_existing_lines(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    append_manifest_line(manifest_path, {"a": 1})

    append_manifest_line(manifest_path, {"b": 2})

    lines = [json.loads(row) for row in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert lines == [{"a": 1}, {"b": 2}]


def test_run_session_writes_one_wav_and_manifest_line_per_phrase(tmp_path: Path) -> None:
    def fake_record_fn(phrase: str) -> np.ndarray:
        return np.zeros(1600, dtype=np.int16)

    def always_confirm(phrase: str, take: int, samples: np.ndarray) -> bool:
        return True

    manifest_lines = run_session(
        tmp_path,
        speaker_code="spk01",
        region="north",
        phrases=("Đồng ý", "Từ chối"),
        record_fn=fake_record_fn,
        confirm_fn=always_confirm,
    )

    assert len(manifest_lines) == 2
    for line in manifest_lines:
        assert (tmp_path / line["path"]).is_file()
    manifest_path = tmp_path / "manifest.jsonl"
    written = [json.loads(row) for row in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert written == manifest_lines


def test_run_session_retakes_until_confirmed(tmp_path: Path) -> None:
    record_calls = []

    def counting_record_fn(phrase: str) -> np.ndarray:
        record_calls.append(phrase)
        return np.zeros(1600, dtype=np.int16)

    confirm_calls = {"n": 0}

    def confirm_after_one_retake(phrase: str, take: int, samples: np.ndarray) -> bool:
        confirm_calls["n"] += 1
        return confirm_calls["n"] > 1  # reject the first take, accept the second

    manifest_lines = run_session(
        tmp_path,
        speaker_code="spk01",
        region="north",
        phrases=("Đồng ý",),
        record_fn=counting_record_fn,
        confirm_fn=confirm_after_one_retake,
    )

    assert len(record_calls) == 2
    assert len(manifest_lines) == 1


def test_run_session_supports_multiple_takes_per_phrase(tmp_path: Path) -> None:
    def fake_record_fn(phrase: str) -> np.ndarray:
        return np.zeros(1600, dtype=np.int16)

    def always_confirm(phrase: str, take: int, samples: np.ndarray) -> bool:
        return True

    manifest_lines = run_session(
        tmp_path,
        speaker_code="spk01",
        region="north",
        phrases=("Đồng ý",),
        takes_per_phrase=3,
        record_fn=fake_record_fn,
        confirm_fn=always_confirm,
    )

    assert len(manifest_lines) == 3
    assert {line["audio_id"] for line in manifest_lines} == {
        "hitl-01-real-spk01-t1",
        "hitl-01-real-spk01-t2",
        "hitl-01-real-spk01-t3",
    }


def test_make_confirm_fn_accepts_immediately_on_blank_answer() -> None:
    play_calls = []
    confirm_fn = make_confirm_fn(play_fn=play_calls.append, input_fn=lambda _prompt: "")

    accepted = confirm_fn("Đồng ý", 1, np.zeros(10, dtype=np.int16))

    assert accepted is True
    assert play_calls == []


def test_make_confirm_fn_rejects_on_r() -> None:
    confirm_fn = make_confirm_fn(play_fn=lambda _samples: None, input_fn=lambda _prompt: "r")

    accepted = confirm_fn("Đồng ý", 1, np.zeros(10, dtype=np.int16))

    assert accepted is False


def test_make_confirm_fn_plays_back_on_p_then_reprompts() -> None:
    play_calls = []
    answers = iter(["p", "p", ""])
    confirm_fn = make_confirm_fn(play_fn=play_calls.append, input_fn=lambda _prompt: next(answers))
    samples = np.zeros(10, dtype=np.int16)

    accepted = confirm_fn("Đồng ý", 1, samples)

    assert accepted is True
    assert len(play_calls) == 2
    assert all(np.array_equal(call, samples) for call in play_calls)

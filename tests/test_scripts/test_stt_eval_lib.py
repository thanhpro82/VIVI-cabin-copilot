from pathlib import Path

import pytest

from scripts.stt_eval_lib import load_manifest_entries


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_manifest_entries_parses_valid_entry(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav_path = audio_dir / "sample.wav"
    wav_path.write_bytes(b"RIFF....WAVEfmt ")
    manifest_path = audio_dir / "manifest.jsonl"
    _write(
        manifest_path,
        '{"audio_id":"a1","path":"sample.wav","reference_text":"áp suất lốp",'
        '"speaker_code":"spk-01","region":"north","noise_condition":"cabin-idle",'
        '"duration_ms":1500,"consent_scope":"internal-poc-evaluation"}\n',
    )

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert warnings == []
    assert len(entries) == 1
    assert entries[0].audio_id == "a1"
    assert entries[0].audio_path == wav_path.resolve()
    assert entries[0].reference_text == "áp suất lốp"


def test_load_manifest_entries_skips_blank_lines_silently(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(manifest_path, "\r\n   \n")

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert warnings == []


def test_load_manifest_entries_warns_on_missing_required_field(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(manifest_path, '{"audio_id":"a1","path":"sample.wav"}\n')

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert len(warnings) == 1
    assert "missing required field" in warnings[0]


def test_load_manifest_entries_warns_on_missing_audio_file(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(
        manifest_path,
        '{"audio_id":"a1","path":"missing.wav","reference_text":"x",'
        '"speaker_code":"spk-01","region":"north","noise_condition":"cabin-idle",'
        '"duration_ms":1000,"consent_scope":"internal-poc-evaluation"}\n',
    )

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert len(warnings) == 1
    assert "audio file not found" in warnings[0]


def test_load_manifest_entries_warns_on_path_escaping_the_audio_dir(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"RIFF....WAVEfmt ")
    manifest_path = audio_dir / "manifest.jsonl"
    _write(
        manifest_path,
        '{"audio_id":"a1","path":"../outside.wav","reference_text":"x",'
        '"speaker_code":"spk-01","region":"north","noise_condition":"cabin-idle",'
        '"duration_ms":1000,"consent_scope":"internal-poc-evaluation"}\n',
    )

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert len(warnings) == 1
    assert "audio file not found" in warnings[0]


def test_load_manifest_entries_warns_on_invalid_json(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(manifest_path, "{not valid json\n")

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert len(warnings) == 1
    assert "invalid JSON" in warnings[0]


def test_load_manifest_entries_raises_when_manifest_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_manifest_entries(tmp_path / "does_not_exist.jsonl", tmp_path)

import json
from pathlib import Path

from scripts.eval_voice_hitl_wer import filter_real_entries, score_entry, summarize, write_run_outputs
from scripts.stt_eval_lib import ManifestEntry
from src.services.voice import Transcript


def _entry(
    audio_id: str, reference_text: str, *, speaker_code: str = "std_banmai", noise_condition: str = "synthetic-tts"
) -> ManifestEntry:
    return ManifestEntry(
        audio_id=audio_id,
        audio_path=Path(f"{audio_id}.wav"),
        reference_text=reference_text,
        speaker_code=speaker_code,
        region="north",
        noise_condition=noise_condition,
        duration_ms=900,
        consent_scope="internal-poc-evaluation",
    )


def _fixed_transcript(text: str) -> callable:
    def _fn(path: Path) -> Transcript:
        return Transcript(text=text, latency_ms=42.0)

    return _fn


def test_score_entry_correct_when_agree_word_heard_correctly() -> None:
    entry = _entry("a1", "đồng ý")

    result = score_entry(entry, _fixed_transcript("đồng ý"))

    assert result["expected_decision"] == "approve"
    assert result["actual_decision"] == "approve"
    assert result["outcome"] == "correct"
    assert result["wer"] == 0.0


def test_score_entry_is_a_miss_when_agree_word_misheard_as_something_else() -> None:
    entry = _entry("a2", "đồng ý")

    result = score_entry(entry, _fixed_transcript("đông y"))

    assert result["expected_decision"] == "approve"
    assert result["actual_decision"] is None
    assert result["outcome"] == "miss"


def test_score_entry_is_false_accept_when_reject_word_misheard_as_agree() -> None:
    entry = _entry("a3", "từ chối")

    result = score_entry(entry, _fixed_transcript("đồng ý"))

    assert result["expected_decision"] == "reject"
    assert result["actual_decision"] == "approve"
    assert result["outcome"] == "false_accept"


def test_score_entry_correct_when_reject_word_heard_correctly() -> None:
    entry = _entry("a4", "hủy")

    result = score_entry(entry, _fixed_transcript("hủy"))

    assert result["expected_decision"] == "reject"
    assert result["actual_decision"] == "reject"
    assert result["outcome"] == "correct"


def test_score_entry_is_safe_no_signal_when_reject_word_misheard_as_neither() -> None:
    entry = _entry("a5", "thôi")

    result = score_entry(entry, _fixed_transcript("trôi nổi"))

    assert result["expected_decision"] == "reject"
    assert result["actual_decision"] is None
    assert result["outcome"] == "safe_no_signal"


def test_summarize_computes_miss_rate_over_approve_expected_cases_only() -> None:
    case_results = [
        {"expected_decision": "approve", "outcome": "correct", "wer": 0.0, "cer": 0.0},
        {"expected_decision": "approve", "outcome": "miss", "wer": 1.0, "cer": 1.0},
        {"expected_decision": "reject", "outcome": "correct", "wer": 0.0, "cer": 0.0},
    ]

    metrics = summarize(case_results)

    assert metrics["approve_expected_total"] == 2
    assert metrics["miss_rate"] == 0.5


def test_summarize_computes_false_accept_rate_over_reject_expected_cases_only() -> None:
    case_results = [
        {"expected_decision": "reject", "outcome": "false_accept", "wer": 1.0, "cer": 1.0},
        {"expected_decision": "reject", "outcome": "correct", "wer": 0.0, "cer": 0.0},
        {"expected_decision": "reject", "outcome": "safe_no_signal", "wer": 1.0, "cer": 1.0},
        {"expected_decision": "approve", "outcome": "correct", "wer": 0.0, "cer": 0.0},
    ]

    metrics = summarize(case_results)

    assert metrics["reject_expected_total"] == 3
    assert metrics["false_accept_rate"] == 1 / 3


def test_summarize_rates_are_none_when_no_cases_of_that_expectation() -> None:
    case_results = [
        {"expected_decision": "approve", "outcome": "correct", "wer": 0.0, "cer": 0.0},
    ]

    metrics = summarize(case_results)

    assert metrics["reject_expected_total"] == 0
    assert metrics["false_accept_rate"] is None


def test_write_run_outputs_creates_three_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    case_results = [score_entry(_entry("a1", "đồng ý"), _fixed_transcript("đồng ý"))]
    metrics = summarize(case_results)

    write_run_outputs(run_dir, "run", Path("m.jsonl"), case_results, metrics)

    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "case_results.jsonl").is_file()
    assert (run_dir / "metrics.json").is_file()


def test_write_run_outputs_note_flags_synthetic_runs_as_not_gate_satisfying(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    case_results = [score_entry(_entry("a1", "đồng ý"), _fixed_transcript("đồng ý"))]

    write_run_outputs(run_dir, "run", Path("m.jsonl"), case_results, summarize(case_results))

    note = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["note"]
    assert "does NOT satisfy issue #198" in note


def test_filter_real_entries_excludes_synthetic_tts() -> None:
    entries = [
        _entry("tts", "đồng ý"),
        _entry("spk01", "đồng ý", speaker_code="spk01", noise_condition="quiet-room"),
        _entry("spk02", "hủy", speaker_code="spk02", noise_condition="quiet-room"),
    ]

    actual = filter_real_entries(entries)

    assert [entry.audio_id for entry in actual] == ["spk01", "spk02"]


def test_summarize_groups_safety_metrics_by_speaker() -> None:
    results = [
        {"speaker_code": "spk01", "expected_decision": "approve", "outcome": "miss", "wer": 1.0, "cer": 1.0},
        {"speaker_code": "spk02", "expected_decision": "reject", "outcome": "correct", "wer": 0.0, "cer": 0.0},
    ]

    metrics = summarize(results)

    assert metrics["by_speaker"]["spk01"]["miss_rate"] == 1.0
    assert metrics["by_speaker"]["spk02"]["false_accept_rate"] == 0.0

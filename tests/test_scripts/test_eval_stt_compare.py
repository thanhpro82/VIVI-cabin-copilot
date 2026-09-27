import json
from pathlib import Path

import pytest

from scripts.eval_stt_compare import (
    VERDICT_WER_THRESHOLD,
    compare_entry,
    describe_engines,
    summarize,
    write_run_outputs,
)
from scripts.stt_eval_lib import ManifestEntry
from src.services.voice import Transcript


def _entry(audio_id: str, reference_text: str) -> ManifestEntry:
    return ManifestEntry(
        audio_id=audio_id,
        audio_path=Path(f"{audio_id}.wav"),
        reference_text=reference_text,
        speaker_code="spk-01",
        region="north",
        noise_condition="cabin-idle",
        duration_ms=1500,
        consent_scope="internal-poc-evaluation",
    )


def _fixed_transcript(text: str, latency_ms: float):
    def _fn(path: Path) -> Transcript:
        return Transcript(text=text, latency_ms=latency_ms)

    return _fn


def test_compare_entry_computes_wer_cer_for_both_engines() -> None:
    entry = _entry("a1", "áp suất lốp là bao nhiêu")
    phowhisper = _fixed_transcript("nốt cà bao nhiêu", 100.0)
    zipformer = _fixed_transcript("áp suất lốp là bao nhiêu", 50.0)

    result = compare_entry(entry, phowhisper, zipformer, "tire_pressure")

    assert result["audio_id"] == "a1"
    assert result["domain"] == "tire_pressure"
    assert result["zipformer"]["wer"] == 0.0
    assert result["phowhisper"]["wer"] > 0.5
    assert result["zipformer"]["latency_ms"] == 50.0


def test_compare_entry_domain_defaults_to_unknown() -> None:
    entry = _entry("a1", "bật điều hòa")

    result = compare_entry(entry, _fixed_transcript("bật điều hòa", 10.0), _fixed_transcript("bật điều hòa", 10.0))

    assert result["domain"] == "unknown"


def test_summarize_computes_averages_and_verdict_below_threshold() -> None:
    case_results = [
        {
            "domain": "hvac",
            "phowhisper": {"wer": 0.5, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"wer": 0.1, "cer": 0.05, "latency_ms": 50.0},
        },
        {
            "domain": "hvac",
            "phowhisper": {"wer": 0.3, "cer": 0.2, "latency_ms": 120.0},
            "zipformer": {"wer": 0.1, "cer": 0.05, "latency_ms": 60.0},
        },
    ]

    metrics = summarize(case_results)

    assert metrics["total"] == 2
    assert metrics["zipformer"]["avg_wer"] == 0.1
    assert metrics["verdict"] == "zipformer_candidate"
    assert metrics["verdict_margin"] == VERDICT_WER_THRESHOLD - 0.1


def test_summarize_breaks_results_down_by_domain() -> None:
    case_results = [
        {
            "domain": "tire_pressure",
            "phowhisper": {"wer": 0.8, "cer": 0.6, "latency_ms": 100.0},
            "zipformer": {"wer": 0.4, "cer": 0.3, "latency_ms": 50.0},
        },
        {
            "domain": "tire_pressure",
            "phowhisper": {"wer": 0.6, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"wer": 0.2, "cer": 0.1, "latency_ms": 50.0},
        },
        {
            "domain": "baseline",
            "phowhisper": {"wer": 0.0, "cer": 0.0, "latency_ms": 100.0},
            "zipformer": {"wer": 0.1, "cer": 0.05, "latency_ms": 50.0},
        },
    ]

    metrics = summarize(case_results)

    assert "by_domain" in metrics
    assert set(metrics["by_domain"]) == {"tire_pressure", "baseline"}
    assert metrics["by_domain"]["tire_pressure"]["total"] == 2
    assert metrics["by_domain"]["tire_pressure"]["phowhisper_avg_wer"] == pytest.approx(0.7)
    assert metrics["by_domain"]["tire_pressure"]["zipformer_avg_wer"] == pytest.approx(0.3)
    assert metrics["by_domain"]["baseline"]["total"] == 1


def test_summarize_groups_rows_without_a_domain_as_unknown() -> None:
    case_results = [
        {
            "phowhisper": {"wer": 0.5, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"wer": 0.1, "cer": 0.05, "latency_ms": 50.0},
        },
    ]

    metrics = summarize(case_results)

    assert list(metrics["by_domain"]) == ["unknown"]


def test_summarize_verdict_not_better_at_or_above_threshold() -> None:
    case_results = [
        {
            "domain": "volume",
            "phowhisper": {"wer": 0.5, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"wer": 0.2, "cer": 0.1, "latency_ms": 50.0},
        },
    ]

    metrics = summarize(case_results)

    assert metrics["verdict"] == "zipformer_not_better"
    assert metrics["verdict_margin"] < 0


def _one_case() -> list[dict]:
    return [
        {
            "audio_id": "a1",
            "domain": "tire_pressure",
            "reference_text": "áp suất lốp",
            "phowhisper": {"hypothesis": "x", "wer": 0.5, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"hypothesis": "áp suất lốp", "wer": 0.0, "cer": 0.0, "latency_ms": 50.0},
        }
    ]


def test_write_run_outputs_creates_three_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260101T000000Z"
    case_results = _one_case()
    metrics = summarize(case_results)

    write_run_outputs(
        run_dir, "20260101T000000Z", Path("eval/datasets/poc/v1/audio/manifest.jsonl"), case_results, metrics
    )

    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "case_results.jsonl").is_file()
    assert (run_dir / "metrics.json").is_file()


def test_write_run_outputs_note_names_synthetic_audio_explicitly(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    case_results = _one_case()

    write_run_outputs(run_dir, "run", Path("m.jsonl"), case_results, summarize(case_results))

    note = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["note"]
    assert "synthetic" in note
    assert "NOT human speech" in note


def test_write_run_outputs_folds_in_model_provenance_from_sidecars(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for filename in ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"):
        (model_dir / f"{filename}.metadata.json").write_text(
            json.dumps(
                {
                    "repository": "hynt/Zipformer-30M-RNNT-6000h",
                    "revision": "24ed30248e1c96bb690c81c24ab4e056f8cd9fce",
                    "license": "cc-by-nc-nd-4.0",
                    "sha256": f"sha-of-{filename}",
                }
            ),
            encoding="utf-8",
        )
    run_dir = tmp_path / "run"
    case_results = _one_case()

    write_run_outputs(run_dir, "run", Path("m.jsonl"), case_results, summarize(case_results), model_dir)

    engines = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["engines"]
    zipformer = next(e for e in engines if e["name"] == "zipformer-30m-rnnt-6000h")
    assert zipformer["repository"] == "hynt/Zipformer-30M-RNNT-6000h"
    assert zipformer["revision"] == "24ed30248e1c96bb690c81c24ab4e056f8cd9fce"
    assert zipformer["license"] == "cc-by-nc-nd-4.0"
    assert zipformer["sha256_by_file"]["tokens.txt"] == "sha-of-tokens.txt"


def test_describe_engines_omits_provenance_gracefully_when_sidecars_missing(tmp_path: Path) -> None:
    engines = describe_engines(tmp_path)

    assert [e["name"] for e in engines] == ["phowhisper-base", "zipformer-30m-rnnt-6000h"]
    zipformer = engines[1]
    assert "repository" not in zipformer
    assert "sha256_by_file" not in zipformer


def test_describe_engines_tolerates_no_model_dir_at_all() -> None:
    engines = describe_engines(None)

    assert engines == [{"name": "phowhisper-base"}, {"name": "zipformer-30m-rnnt-6000h"}]

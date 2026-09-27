"""WER + two-directional safety eval for HITL voice-confirmation phrases
(issue #198, part 2). Unlike scripts/eval_stt_compare.py this does not just
score transcript WER — it feeds the hypothesis through
src.agents.voice_intent.doc_y_dinh_phe_duyet, the same matcher the live HITL
approval path uses, and reports the two rates the issue asks for:

- miss_rate: driver said a clear agree phrase, the matcher did not read it as
  approve (driver has to repeat — annoying, still safe)
- false_accept_rate: driver said a reject phrase (or something else), the
  matcher read it as approve (the expensive failure mode — an S2 action
  fires that the driver did not mean to approve)

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\eval_voice_hitl_wer.py
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from scripts.stt_eval_lib import ManifestEntry, load_manifest_entries
from src.agents.voice_intent import doc_y_dinh_phe_duyet
from src.services.voice import Transcript, char_error_rate, transcribe_raw, word_error_rate

TranscribeFn = Callable[[Path], Transcript]

DEFAULT_MANIFEST = Path("eval/datasets/voice-hitl-confirmation/v1/audio/manifest.jsonl")
DEFAULT_AUDIO_DIR = Path("eval/datasets/voice-hitl-confirmation/v1/audio")
DEFAULT_OUTPUT_ROOT = Path("eval/results/voice-hitl-wer")


def _classify(expected: str, actual: str | None) -> str:
    if expected == "approve":
        return "correct" if actual == "approve" else "miss"
    # expected == "reject"
    if actual == "approve":
        return "false_accept"
    if actual == "reject":
        return "correct"
    return "safe_no_signal"


def score_entry(entry: ManifestEntry, transcribe_fn: TranscribeFn) -> dict:
    hypothesis = transcribe_fn(entry.audio_path)
    expected_decision = doc_y_dinh_phe_duyet(entry.reference_text).quyet_dinh
    actual_decision = doc_y_dinh_phe_duyet(hypothesis.text).quyet_dinh
    return {
        "audio_id": entry.audio_id,
        "speaker_code": entry.speaker_code,
        "region": entry.region,
        "reference_text": entry.reference_text,
        "hypothesis": hypothesis.text,
        "wer": word_error_rate(entry.reference_text, hypothesis.text),
        "cer": char_error_rate(entry.reference_text, hypothesis.text),
        "latency_ms": hypothesis.latency_ms,
        "expected_decision": expected_decision,
        "actual_decision": actual_decision,
        "outcome": _classify(expected_decision, actual_decision),
    }


def filter_real_entries(entries: list[ManifestEntry]) -> list[ManifestEntry]:
    """Exclude TTS-only evidence from the human-speech acceptance run."""
    return [entry for entry in entries if entry.noise_condition != "synthetic-tts"]


def _summarize_case_results(case_results: list[dict]) -> dict:
    total = len(case_results)
    avg_wer = sum(r["wer"] for r in case_results) / total if total else 0.0
    avg_cer = sum(r["cer"] for r in case_results) / total if total else 0.0

    approve_expected = [r for r in case_results if r["expected_decision"] == "approve"]
    reject_expected = [r for r in case_results if r["expected_decision"] == "reject"]

    miss_count = sum(1 for r in approve_expected if r["outcome"] == "miss")
    false_accept_count = sum(1 for r in reject_expected if r["outcome"] == "false_accept")

    return {
        "total": total,
        "avg_wer": avg_wer,
        "avg_cer": avg_cer,
        "approve_expected_total": len(approve_expected),
        "miss_count": miss_count,
        "miss_rate": (miss_count / len(approve_expected)) if approve_expected else None,
        "reject_expected_total": len(reject_expected),
        "false_accept_count": false_accept_count,
        "false_accept_rate": (false_accept_count / len(reject_expected)) if reject_expected else None,
    }


def summarize(case_results: list[dict]) -> dict:
    metrics = _summarize_case_results(case_results)
    speakers = sorted({str(row["speaker_code"]) for row in case_results if "speaker_code" in row})
    metrics["by_speaker"] = {
        speaker: _summarize_case_results([row for row in case_results if row.get("speaker_code") == speaker])
        for speaker in speakers
    }
    return metrics


def write_run_outputs(
    run_dir: Path,
    run_id: str,
    manifest_path: Path,
    case_results: list[dict],
    metrics: dict,
    *,
    real_only: bool = False,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "dataset": str(manifest_path),
        "case_count": len(case_results),
        "matcher": "src.agents.voice_intent.doc_y_dinh_phe_duyet",
        "provenance": "human-only" if real_only else "mixed-or-synthetic",
        "note": (
            "Audio provenance (synthetic vs. real, speaker) is whatever this dataset's "
            "manifest.jsonl noise_condition/speaker_code fields say per entry. A run drawn "
            "from noise_condition=synthetic-tts entries does NOT satisfy issue #198's WER "
            "gate, which requires real human speech before the acoustic-constraint approach "
            "in part 1 is chosen or README status is raised."
        ),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with (run_dir / "case_results.jsonl").open("w", encoding="utf-8") as f:
        for row in case_results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")


def print_report(case_results: list[dict], metrics: dict) -> None:
    header = f"{'audio_id':<10} {'speaker':<14} {'expected':<8} {'actual':<8} {'outcome':<15} {'wer':>6}"
    print(header)
    print("-" * len(header))
    for row in case_results:
        print(
            f"{row['audio_id']:<10} {row['speaker_code']:<14} "
            f"{str(row['expected_decision']):<8} {str(row['actual_decision']):<8} "
            f"{row['outcome']:<15} {row['wer']:>6.2%}"
        )
    print("-" * len(header))
    print(f"total={metrics['total']} avg_wer={metrics['avg_wer']:.2%} avg_cer={metrics['avg_cer']:.2%}")

    miss_rate = metrics["miss_rate"]
    miss_str = f"{miss_rate:.2%}" if miss_rate is not None else "n/a"
    print(f"miss_rate={miss_str} (over {metrics['approve_expected_total']} agree-expected cases)")

    false_accept_rate = metrics["false_accept_rate"]
    fa_str = f"{false_accept_rate:.2%}" if false_accept_rate is not None else "n/a"
    print(f"false_accept_rate={fa_str} (over {metrics['reject_expected_total']} reject-expected cases) — SAFETY NUMBER")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--real-only",
        action="store_true",
        help="score only non-synthetic recordings and require at least two speakers",
    )
    args = parser.parse_args()

    entries, warnings = load_manifest_entries(args.manifest, args.audio_dir)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if args.real_only:
        entries = filter_real_entries(entries)
        speaker_codes = {entry.speaker_code for entry in entries}
        if len(speaker_codes) < 2:
            raise SystemExit("--real-only requires recordings from at least two speakers")
    if not entries:
        raise SystemExit("No valid manifest entries found; nothing to evaluate.")

    def transcribe_fn(path: Path) -> Transcript:
        return transcribe_raw(path.read_bytes())

    case_results = []
    for entry in entries:
        try:
            case_results.append(score_entry(entry, transcribe_fn))
        except Exception as exc:  # noqa: BLE001 - one bad file should not abort the run
            print(f"WARNING: skipping {entry.audio_id}: {type(exc).__name__}: {exc}")
    if not case_results:
        raise SystemExit("Every manifest entry failed to transcribe; nothing to report.")

    metrics = summarize(case_results)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = args.output_root / run_id
    write_run_outputs(run_dir, run_id, args.manifest, case_results, metrics, real_only=args.real_only)
    print_report(case_results, metrics)
    print(f"\nResults written to {run_dir}")


if __name__ == "__main__":
    main()

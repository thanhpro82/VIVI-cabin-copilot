"""Phase 1 STT quick eval: compares PhoWhisper-base (current production
engine, via src/services/voice.py) against Zipformer-30M-RNNT-6000h on real
audio for the domain terms currently misrecognized (tire pressure, HVAC,
volume). See docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\eval_stt_compare.py
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from scripts.stt_eval_lib import ManifestEntry, load_manifest_entries
from scripts.synthesize_domain_audio import parse_checklist
from scripts.zipformer_engine import get_zipformer_engine
from src.services.voice import Transcript, char_error_rate, transcribe_raw, word_error_rate

VERDICT_WER_THRESHOLD = 0.15

DEFAULT_CHECKLIST = Path("eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md")

# Filenames written by scripts/download_zipformer_model.py, each with a
# `<name>.metadata.json` sidecar carrying repository/revision/license/sha256.
ZIPFORMER_MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")

EngineFn = Callable[[Path], Transcript]


def compare_entry(
    entry: ManifestEntry, phowhisper_fn: EngineFn, zipformer_fn: EngineFn, domain: str = "unknown"
) -> dict:
    phowhisper_result = phowhisper_fn(entry.audio_path)
    zipformer_result = zipformer_fn(entry.audio_path)
    return {
        "audio_id": entry.audio_id,
        "domain": domain,
        "reference_text": entry.reference_text,
        "phowhisper": {
            "hypothesis": phowhisper_result.text,
            "wer": word_error_rate(entry.reference_text, phowhisper_result.text),
            "cer": char_error_rate(entry.reference_text, phowhisper_result.text),
            "latency_ms": phowhisper_result.latency_ms,
        },
        "zipformer": {
            "hypothesis": zipformer_result.text,
            "wer": word_error_rate(entry.reference_text, zipformer_result.text),
            "cer": char_error_rate(entry.reference_text, zipformer_result.text),
            "latency_ms": zipformer_result.latency_ms,
        },
    }


def summarize(case_results: list[dict]) -> dict:
    def _avg(engine_key: str, metric_key: str) -> float:
        values = [row[engine_key][metric_key] for row in case_results]
        return sum(values) / len(values) if values else 0.0

    def _by_domain() -> dict:
        # Grouped so the run can say whether Zipformer helps on the *new* failing
        # terms (tire_pressure/hvac/volume) specifically or uniformly across the
        # board — that is why RECORDING_CHECKLIST.md carries a `domain` column.
        grouped: dict[str, list[dict]] = {}
        for row in case_results:
            grouped.setdefault(row.get("domain", "unknown"), []).append(row)
        return {
            domain: {
                "total": len(rows),
                "phowhisper_avg_wer": sum(r["phowhisper"]["wer"] for r in rows) / len(rows),
                "zipformer_avg_wer": sum(r["zipformer"]["wer"] for r in rows) / len(rows),
            }
            for domain, rows in grouped.items()
        }

    zipformer_avg_wer = _avg("zipformer", "wer")
    return {
        "total": len(case_results),
        "phowhisper": {
            "avg_wer": _avg("phowhisper", "wer"),
            "avg_cer": _avg("phowhisper", "cer"),
            "avg_latency_ms": _avg("phowhisper", "latency_ms"),
        },
        "zipformer": {
            "avg_wer": zipformer_avg_wer,
            "avg_cer": _avg("zipformer", "cer"),
            "avg_latency_ms": _avg("zipformer", "latency_ms"),
        },
        "by_domain": _by_domain(),
        "verdict": "zipformer_candidate" if zipformer_avg_wer < VERDICT_WER_THRESHOLD else "zipformer_not_better",
        "verdict_threshold_wer": VERDICT_WER_THRESHOLD,
        # Positive = zipformer is under the threshold by this much; negative = over.
        "verdict_margin": VERDICT_WER_THRESHOLD - zipformer_avg_wer,
    }


def describe_engines(zipformer_model_dir: Path | None) -> list[dict]:
    """Model provenance for manifest.json, read from the `.metadata.json`
    sidecars scripts/download_zipformer_model.py wrote next to each weight file.

    A run has to trace to specific weights, not just an engine name. Missing or
    unreadable sidecars degrade to a bare `{"name": ...}` rather than failing the
    run — losing provenance is bad, losing the whole evaluation is worse.
    """
    zipformer: dict = {"name": "zipformer-30m-rnnt-6000h"}
    sha256_by_file: dict[str, str] = {}
    if zipformer_model_dir is not None:
        for filename in ZIPFORMER_MODEL_FILES:
            sidecar = zipformer_model_dir / f"{filename}.metadata.json"
            try:
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for key in ("repository", "revision", "license"):
                if key in metadata and key not in zipformer:
                    zipformer[key] = metadata[key]
            if "sha256" in metadata:
                sha256_by_file[filename] = metadata["sha256"]
    if sha256_by_file:
        zipformer["sha256_by_file"] = sha256_by_file
    return [{"name": "phowhisper-base"}, zipformer]


def write_run_outputs(
    run_dir: Path,
    run_id: str,
    manifest_path: Path,
    case_results: list[dict],
    metrics: dict,
    zipformer_model_dir: Path | None = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "dataset": str(manifest_path),
        "case_count": len(case_results),
        "engines": describe_engines(zipformer_model_dir),
        "note": (
            "Phase 1 quick eval — synthetic Piper TTS audio (single voice), NOT human speech. "
            "Not a generalization claim. See "
            "docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md."
        ),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with (run_dir / "case_results.jsonl").open("w", encoding="utf-8") as f:
        for row in case_results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")


def print_comparison_table(case_results: list[dict], metrics: dict) -> None:
    header = f"{'audio_id':<12} {'ph_wer':>8} {'zf_wer':>8} {'ph_cer':>8} {'zf_cer':>8} {'ph_ms':>8} {'zf_ms':>8}"
    print(header)
    print("-" * len(header))
    for row in case_results:
        print(
            f"{row['audio_id']:<12} "
            f"{row['phowhisper']['wer']:>8.2%} "
            f"{row['zipformer']['wer']:>8.2%} "
            f"{row['phowhisper']['cer']:>8.2%} "
            f"{row['zipformer']['cer']:>8.2%} "
            f"{row['phowhisper']['latency_ms']:>8.0f} "
            f"{row['zipformer']['latency_ms']:>8.0f}"
        )
    print("-" * len(header))
    print(
        f"{'AVERAGE':<12} "
        f"{metrics['phowhisper']['avg_wer']:>8.2%} "
        f"{metrics['zipformer']['avg_wer']:>8.2%} "
        f"{metrics['phowhisper']['avg_cer']:>8.2%} "
        f"{metrics['zipformer']['avg_cer']:>8.2%} "
        f"{metrics['phowhisper']['avg_latency_ms']:>8.0f} "
        f"{metrics['zipformer']['avg_latency_ms']:>8.0f}"
    )
    if metrics.get("by_domain"):
        print("\nBy domain:")
        for domain, stats in sorted(metrics["by_domain"].items()):
            print(
                f"  {domain:<16} n={stats['total']:<3} "
                f"ph_wer={stats['phowhisper_avg_wer']:.2%} zf_wer={stats['zipformer_avg_wer']:.2%}"
            )
    print(f"\nVerdict: {metrics['verdict']} (threshold: zipformer avg WER < {metrics['verdict_threshold_wer']:.0%})")
    print(f"Margin: {metrics['verdict_margin']:+.4f} (threshold minus zipformer avg WER)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("eval/datasets/poc/v1/audio/manifest.jsonl"))
    parser.add_argument("--audio-dir", type=Path, default=Path("eval/datasets/poc/v1/audio"))
    parser.add_argument("--zipformer-model-dir", type=Path, default=Path("models/voice/zipformer-30m-rnnt-6000h"))
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--output-root", type=Path, default=Path("eval/results/stt-compare"))
    args = parser.parse_args()

    entries, warnings = load_manifest_entries(args.manifest, args.audio_dir)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if not entries:
        raise SystemExit("No valid manifest entries found; nothing to evaluate.")

    # The checklist's `domain` column drives the per-domain breakdown. It is read
    # here rather than added to ManifestEntry: the manifest schema is a general
    # contract, the domain tagging is specific to this Phase 1 corpus.
    domain_by_id: dict[str, str] = {}
    if args.checklist.is_file():
        domain_by_id = {audio_id: domain for audio_id, domain, _ in parse_checklist(args.checklist)}
    else:
        print(f"WARNING: checklist not found at {args.checklist}; per-domain breakdown will be 'unknown'")

    zipformer_engine = get_zipformer_engine(args.zipformer_model_dir)

    def phowhisper_fn(path: Path) -> Transcript:
        return transcribe_raw(path.read_bytes())

    def zipformer_fn(path: Path) -> Transcript:
        return zipformer_engine.transcribe_file(path)

    # One unreadable WAV must not throw away every transcription done before it.
    case_results = []
    for entry in entries:
        try:
            case_results.append(
                compare_entry(entry, phowhisper_fn, zipformer_fn, domain_by_id.get(entry.audio_id, "unknown"))
            )
        except Exception as exc:  # noqa: BLE001 - one bad file should not abort the run
            print(f"WARNING: skipping {entry.audio_id}: {type(exc).__name__}: {exc}")
    if not case_results:
        raise SystemExit("Every manifest entry failed to transcribe; nothing to report.")

    metrics = summarize(case_results)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = args.output_root / run_id
    write_run_outputs(run_dir, run_id, args.manifest, case_results, metrics, args.zipformer_model_dir)
    print_comparison_table(case_results, metrics)
    print(f"\nResults written to {run_dir}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Sequence
from uuid import uuid4
import wave

from offline_poc.config import load_config
from offline_poc.contracts import ToolResult
from offline_poc.dataset import load_cases
from offline_poc.llm import LlamaClient, PlanGenerationError
from offline_poc.metrics import StageTrace, summarize_ms
from offline_poc.stt import char_error_rate, word_error_rate


@dataclass(frozen=True)
class PipelineResult:
    case_id: str
    trace: StageTrace
    transcript_text: str
    tool_results: list[ToolResult]
    response_text: str
    response_audio_path: Path


def create_run_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite existing run directory: {path}") from exc
    return path


def _safe_file_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if not stem:
        raise ValueError("case_id must contain at least one safe filename character")
    return stem


class OfflinePipeline:
    def __init__(self, *, stt: Any, graph: Any, tts: Any, output_dir: Path) -> None:
        self.stt = stt
        self.graph = graph
        self.tts = tts
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_audio_case(
        self, case_id: str, audio_path: Path | None = None
    ) -> PipelineResult:
        trace = StageTrace(trace_id=f"trace-{uuid4()}")
        trace.mark("speech_end")

        source_audio = audio_path or self.output_dir / f"{_safe_file_stem(case_id)}.wav"
        transcript = self.stt.transcribe(source_audio)
        trace.mark("stt_completed")

        tool_results = list(self.graph.invoke_approved(transcript.text))
        trace.mark("plan_completed")
        trace.mark("rag_or_tool_completed")

        response_text = self._compose_response(tool_results)
        response_audio = self.output_dir / f"{_safe_file_stem(case_id)}-response.wav"
        self.tts.synthesize(response_text, response_audio)
        trace.mark("first_tts_audio")
        trace.mark("playback_completed")

        result = PipelineResult(
            case_id=case_id,
            trace=trace,
            transcript_text=transcript.text,
            tool_results=tool_results,
            response_text=response_text,
            response_audio_path=response_audio,
        )
        self._append_case_result(result)
        return result

    @staticmethod
    def _compose_response(tool_results: list[ToolResult]) -> str:
        if tool_results and all(result.status == "completed" for result in tool_results):
            return "Đã thực hiện lệnh mô phỏng."
        return "Không thể thực hiện đầy đủ lệnh mô phỏng."

    def _append_case_result(self, result: PipelineResult) -> None:
        record = {
            "case_id": result.case_id,
            "trace_id": result.trace.trace_id,
            "trace_ns": result.trace.marks_ns,
            "transcript_text": result.transcript_text,
            "tool_results": [item.model_dump(mode="json") for item in result.tool_results],
            "response_text": result.response_text,
            "response_audio_path": str(result.response_audio_path),
        }
        target = self.output_dir / "case_results.jsonl"
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def _tool_projection(plan: Any) -> list[dict[str, Any]]:
    return [{"name": step.tool, "args": step.args} for step in plan.steps]


def benchmark_llm_cases(
    *,
    client: Any,
    cases: Sequence[Any],
    profile_id: str,
    run_dir: Path,
    artifact: dict[str, Any],
    process_snapshot: dict[str, Any],
    process_snapshot_provider: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not cases:
        raise ValueError("LLM benchmark requires at least one case")
    run_dir.mkdir(parents=True, exist_ok=True)
    targets = [
        run_dir / "case_results.jsonl",
        run_dir / "manifest.json",
        run_dir / "metrics.json",
    ]
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite LLM benchmark evidence: {existing}")

    latencies: list[float] = []
    schema_valid_count = 0
    exact_match_count = 0
    repair_count = 0

    with targets[0].open("x", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            state_version = int(case.vehicle_state.get("state_version", 1))
            expected_tools = list(case.expected.get("tools", []))
            record: dict[str, Any] = {
                "case_id": case.case_id,
                "trace_id": f"trace-{uuid4()}",
                "category": case.category,
                "input_text": case.input_text,
                "expected_tools": expected_tools,
            }
            try:
                plan, measurement = client.create_plan(case.input_text, state_version)
                actual_tools = _tool_projection(plan)
                exact_match = actual_tools == expected_tools
                record.update(
                    {
                        "schema_valid": True,
                        "tool_exact_match": exact_match,
                        "plan": plan.model_dump(mode="json"),
                        "actual_tools": actual_tools,
                        "latency_ms": measurement.total_ms,
                        "prompt_tokens": measurement.prompt_tokens,
                        "completion_tokens": measurement.completion_tokens,
                        "repair_attempts": measurement.repair_attempts,
                    }
                )
                schema_valid_count += 1
                exact_match_count += int(exact_match)
                repair_count += measurement.repair_attempts
                latencies.append(measurement.total_ms)
            except PlanGenerationError as exc:
                record.update(
                    {
                        "schema_valid": False,
                        "tool_exact_match": False,
                        "raw_output": exc.raw_output,
                        "repair_output": exc.repair_output,
                        "latency_ms": exc.total_ms,
                        "prompt_tokens": exc.prompt_tokens,
                        "completion_tokens": exc.completion_tokens,
                        "repair_attempts": exc.repair_attempts,
                        "error": str(exc),
                    }
                )
                repair_count += exc.repair_attempts
                latencies.append(exc.total_ms)

            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    count = len(cases)
    latency_summary = summarize_ms(latencies)
    final_process_snapshot = dict(process_snapshot)
    if process_snapshot_provider is not None:
        final_process_snapshot.update(process_snapshot_provider())
    metrics: dict[str, Any] = {
        "profile_id": profile_id,
        "case_count": count,
        "schema_validity": schema_valid_count / count,
        "tool_exact_match": exact_match_count / count,
        "repair_rate": repair_count / count,
        "latency": latency_summary,
        "process": final_process_snapshot,
    }
    manifest = {
        "run_type": "llm_microbenchmark",
        "profile_id": profile_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": count,
        "protocol": {
            "temperature": 0,
            "max_output_tokens": 192,
            "max_repair_attempts": 1,
            "categories": sorted({case.category for case in cases}),
        },
        "artifact": artifact,
        "process": final_process_snapshot,
    }
    for path, payload in ((targets[1], manifest), (targets[2], metrics)):
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return metrics


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _wav_duration_ms(path: Path) -> float:
    with wave.open(str(path), "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate() * 1000


def benchmark_tts_cases(
    *,
    adapter: Any,
    cases: Sequence[Any],
    profile_id: str,
    run_dir: Path,
    artifact: dict[str, Any],
    process_snapshot_provider: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not cases:
        raise ValueError("TTS benchmark requires at least one case")
    run_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = run_dir / "audio"
    targets = [
        run_dir / "case_results.jsonl",
        run_dir / "synthetic_audio_manifest.jsonl",
        run_dir / "manifest.json",
        run_dir / "metrics.json",
    ]
    if audio_dir.exists() or any(path.exists() for path in targets):
        raise FileExistsError("refusing to overwrite TTS benchmark evidence")
    audio_dir.mkdir()

    latencies: list[float] = []
    first_audio_latencies: list[float] = []
    rtfs: list[float] = []
    process_tree_peaks: list[int] = []
    with (
        targets[0].open("x", encoding="utf-8", newline="\n") as case_handle,
        targets[1].open("x", encoding="utf-8", newline="\n") as audio_handle,
    ):
        for case in cases:
            output_path = (audio_dir / f"{_safe_file_stem(case.case_id)}.wav").resolve()
            measurement = adapter.synthesize(case.input_text, output_path)
            duration_ms = _wav_duration_ms(output_path)
            rtf = measurement.total_ms / duration_ms
            latencies.append(measurement.total_ms)
            first_audio_latencies.append(measurement.first_audio_ms)
            rtfs.append(rtf)
            if measurement.peak_rss_bytes is not None:
                process_tree_peaks.append(measurement.peak_rss_bytes)
            trace_id = f"trace-{uuid4()}"
            case_record = {
                "case_id": case.case_id,
                "trace_id": trace_id,
                "input_text": case.input_text,
                "output_audio_path": str(output_path),
                "duration_ms": duration_ms,
                "total_ms": measurement.total_ms,
                "first_audio_ms": measurement.first_audio_ms,
                "real_time_factor": rtf,
                "process_tree_peak_rss_bytes": measurement.peak_rss_bytes,
            }
            audio_record = {
                "audio_id": f"SYNTH-{case.case_id}",
                "case_id": case.case_id,
                "path": str(output_path),
                "reference_text": case.input_text,
                "speaker_code": "piper-vais1000",
                "region": "synthetic",
                "noise_condition": "clean-synthetic",
                "duration_ms": duration_ms,
                "consent_scope": "synthetic-licensed-piper-poc",
            }
            for handle, payload in (
                (case_handle, case_record),
                (audio_handle, audio_record),
            ):
                handle.write(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

    process = process_snapshot_provider() if process_snapshot_provider else {}
    rtf_summary_ms_keys = summarize_ms(rtfs)
    metrics = {
        "profile_id": profile_id,
        "case_count": len(cases),
        "latency": summarize_ms(latencies),
        "first_audio_latency": summarize_ms(first_audio_latencies),
        "real_time_factor": {
            "count": rtf_summary_ms_keys["count"],
            "p50": rtf_summary_ms_keys["p50_ms"],
            "p95": rtf_summary_ms_keys["p95_ms"],
        },
        "process_tree_peak_rss_bytes": max(process_tree_peaks, default=None),
        "process": process,
    }
    manifest = {
        "run_type": "tts_synthetic_benchmark",
        "profile_id": profile_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "artifact": artifact,
        "protocol": {
            "input": "fixed Vietnamese PoC prompts",
            "audio_scope": "synthetic; not representative of human speech",
            "process_model": "fresh Piper CLI process per utterance",
        },
        "process": process,
    }
    _write_json_file(targets[2], manifest)
    _write_json_file(targets[3], metrics)
    return metrics


def benchmark_stt_manifest(
    *,
    adapter: Any,
    audio_manifest: Path,
    profile_id: str,
    run_dir: Path,
    artifact: dict[str, Any],
    process_snapshot_provider: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in audio_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("STT benchmark requires at least one audio row")
    run_dir.mkdir(parents=True, exist_ok=True)
    targets = [
        run_dir / "case_results.jsonl",
        run_dir / "manifest.json",
        run_dir / "metrics.json",
    ]
    if any(path.exists() for path in targets):
        raise FileExistsError("refusing to overwrite STT benchmark evidence")

    latencies: list[float] = []
    wers: list[float] = []
    cers: list[float] = []
    model_load_ms = 0.0
    with targets[0].open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            audio_path = Path(row["path"])
            if not audio_path.is_file():
                raise ValueError(f"missing audio artifact: {audio_path}")
            transcript = adapter.transcribe(audio_path)
            reference = str(row["reference_text"])
            wer = word_error_rate(reference, transcript.text)
            cer = char_error_rate(reference, transcript.text)
            latencies.append(transcript.total_ms)
            wers.append(wer)
            cers.append(cer)
            model_load_ms = max(model_load_ms, transcript.load_ms)
            record = {
                "case_id": row.get("case_id") or row["audio_id"],
                "audio_id": row["audio_id"],
                "trace_id": f"trace-{uuid4()}",
                "audio_path": str(audio_path.resolve()),
                "reference_text": reference,
                "transcript_text": transcript.text,
                "latency_ms": transcript.total_ms,
                "model_load_ms": transcript.load_ms,
                "wer": wer,
                "cer": cer,
                "source_scope": row.get("consent_scope"),
            }
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    process = process_snapshot_provider() if process_snapshot_provider else {}
    warm_values = latencies[1:] or latencies
    metrics = {
        "profile_id": profile_id,
        "case_count": len(rows),
        "wer_macro": sum(wers) / len(wers),
        "cer_macro": sum(cers) / len(cers),
        "latency": summarize_ms(latencies),
        "warm_latency": summarize_ms(warm_values),
        "cold_first_ms": latencies[0],
        "model_load_ms": model_load_ms,
        "process": process,
    }
    manifest = {
        "run_type": "stt_synthetic_benchmark",
        "profile_id": profile_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(rows),
        "artifact": artifact,
        "audio_manifest": str(audio_manifest.resolve()),
        "protocol": {
            "cpu_threads": 4,
            "audio_scope": "synthetic Piper audio; WER is integration-only",
            "offline_local_path_required": True,
        },
        "process": process,
    }
    _write_json_file(targets[1], manifest)
    _write_json_file(targets[2], metrics)
    return metrics


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_run_dir() -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return _repo_root() / "eval" / "results" / "spike-001" / run_id


def validate_fixtures(run_root: Path | None = None) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[2]
    config = load_config(project_root / "config" / "benchmark.yaml")
    cases = load_cases(_repo_root() / "eval" / "datasets" / "poc" / "v1" / "cases.jsonl")
    result: dict[str, Any] = {
        "candidate_count": len(config.candidates),
        "required_profiles": [item.profile_id for item in config.candidates if item.required],
        "case_count": len(cases),
    }
    if run_root is not None:
        run_dirs = [path for path in run_root.iterdir() if path.is_dir()]
        record_count = 0
        for run_dir in run_dirs:
            result_file = run_dir / "case_results.jsonl"
            if not result_file.is_file():
                raise ValueError(f"missing case_results.jsonl in {run_dir}")
            for line in result_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
                    record_count += 1
        result["run_count"] = len(run_dirs)
        result["record_count"] = record_count
    return result


def execute_e2e_command(args: Any) -> dict[str, Any]:
    allowed_profiles = {"qwen25-05b-q4", "qwen25-3b-q4"}
    if args.profile not in allowed_profiles:
        raise SystemExit(f"unknown E2E profile: {args.profile}")
    audio_path = Path(args.audio_path).resolve()
    if not audio_path.is_file():
        raise SystemExit(f"missing E2E input audio: {audio_path}")

    project_root = Path(__file__).resolve().parents[2]
    config = load_config(project_root / "config" / "benchmark.yaml")
    candidate = next(
        (item for item in config.candidates if item.profile_id == args.profile), None
    )
    if candidate is None:
        raise SystemExit(f"profile is not configured: {args.profile}")

    model_path = (project_root / candidate.model_path).resolve()
    model_metadata_path = Path(f"{model_path}.metadata.json")
    stt_model_path = project_root / "models" / "phowhisper-small"
    stt_metadata_path = project_root / "models" / "phowhisper-small.metadata.json"
    piper_executable = _repo_root() / ".venv" / "Scripts" / "piper.exe"
    piper_model_path = (
        project_root
        / "models"
        / "piper-voices"
        / "vi"
        / "vi_VN"
        / "vais1000"
        / "medium"
        / "vi_VN-vais1000-medium.onnx"
    )
    manual_path = _repo_root() / "eval" / "datasets" / "poc" / "v1" / "manual.md"
    required_files = [
        model_path,
        model_metadata_path,
        stt_metadata_path,
        piper_executable,
        piper_model_path,
        manual_path,
    ]
    missing = [str(path) for path in required_files if not path.is_file()]
    if not stt_model_path.is_dir():
        missing.append(str(stt_model_path))
    if missing:
        raise SystemExit("missing E2E artifacts: " + "; ".join(missing))

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["MKL_NUM_THREADS"] = "4"
    import torch

    torch.set_num_threads(4)
    from offline_poc.e2e import E2ERunner, InteractiveApprovalProvider
    from offline_poc.rag import ManualIndex
    from offline_poc.stt import PhoWhisperAdapter
    from offline_poc.tts import PiperAdapter
    from offline_poc.vehicle_mock import VehicleMock

    raw_model_artifact = json.loads(
        model_metadata_path.read_text(encoding="utf-8-sig")
    )
    model_artifact = {
        "profile_id": args.profile,
        "path": str(model_path),
        "sha256": raw_model_artifact.get("Sha256")
        or raw_model_artifact.get("sha256"),
        "size_bytes": model_path.stat().st_size,
        "revision": raw_model_artifact.get("Revision")
        or raw_model_artifact.get("revision"),
        "license": raw_model_artifact.get("License")
        or raw_model_artifact.get("license"),
        "quantization": candidate.quantization,
        "server_pid": args.server_pid,
        "base_url": args.base_url,
    }
    run_dir = Path(args.run_dir).resolve() if args.run_dir else _default_run_dir()
    create_run_dir(run_dir)
    known_synthetic_root = _repo_root() / "eval" / "results" / "spike-001"
    audio_scope = (
        "synthetic-licensed-piper-poc"
        if known_synthetic_root in audio_path.parents
        else "user-supplied-local-audio"
    )
    runner = E2ERunner(
        stt=PhoWhisperAdapter(stt_model_path.resolve()),
        llm=LlamaClient(args.base_url, timeout_s=180),
        tts=PiperAdapter(piper_executable.resolve(), piper_model_path.resolve()),
        manual_index=ManualIndex.from_markdown(manual_path),
        vehicle=VehicleMock.initial(),
        approval_provider=InteractiveApprovalProvider(timeout_seconds=30),
        profile_id=args.profile,
        output_dir=run_dir,
        model_artifact=model_artifact,
        audio_scope=audio_scope,
    )
    result = runner.run(audio_path, case_id=audio_path.stem)
    validity = json.loads((run_dir / "validity.json").read_text(encoding="utf-8"))
    return {
        "run_dir": str(run_dir),
        "profile_id": args.profile,
        "case_id": result.case_id,
        "route": result.route,
        "outcome": result.outcome,
        "response_audio_path": str(result.response_audio_path),
        "usable_for_summary": bool(validity.get("usable_for_summary")),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VIVI offline PoC benchmark runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate fixtures or run evidence")
    validate.add_argument("--run-root", type=Path)

    for name in ("llm", "stt", "tts", "cases", "e2e"):
        command = subparsers.add_parser(name)
        command.add_argument("--profile", required=True)
        command.add_argument("--run-dir", type=Path)
        if name == "llm":
            command.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
            command.add_argument("--server-pid", type=int)
        if name == "stt":
            command.add_argument("--audio-manifest", required=True, type=Path)
        if name == "cases":
            command.add_argument("--all", action="store_true")
        if name == "e2e":
            command.add_argument("--audio-path", required=True, type=Path)
            command.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
            command.add_argument("--server-pid", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        print(json.dumps(validate_fixtures(args.run_root), ensure_ascii=False, indent=2))
        return 0

    if args.command in {"stt", "tts"}:
        import psutil

        project_root = Path(__file__).resolve().parents[2]
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["OMP_NUM_THREADS"] = "4"
        os.environ["MKL_NUM_THREADS"] = "4"
        run_dir = args.run_dir or _default_run_dir()
        create_run_dir(run_dir)

        def current_process_snapshot() -> dict[str, Any]:
            process = psutil.Process(os.getpid())
            memory = process.memory_info()
            return {
                "pid": process.pid,
                "rss_bytes_after": memory.rss,
                "peak_rss_bytes": getattr(memory, "peak_wset", memory.rss),
                "cpu_seconds_after": sum(process.cpu_times()[:2]),
                "scope": "benchmark_harness_process",
            }

        if args.command == "tts":
            if args.profile != "piper-vais1000-medium":
                raise SystemExit(f"unknown TTS profile: {args.profile}")
            from offline_poc.tts import PiperAdapter

            executable = _repo_root() / ".venv" / "Scripts" / "piper.exe"
            model_path = (
                project_root
                / "models"
                / "piper-voices"
                / "vi"
                / "vi_VN"
                / "vais1000"
                / "medium"
                / "vi_VN-vais1000-medium.onnx"
            )
            metadata_path = project_root / "models" / "piper-vais1000-medium.metadata.json"
            for required in (executable, model_path, metadata_path):
                if not required.is_file():
                    raise SystemExit(f"missing TTS artifact: {required}")
            artifact = json.loads(metadata_path.read_text(encoding="utf-8"))
            cases = load_cases(
                _repo_root() / "eval" / "datasets" / "poc" / "v1" / "cases.jsonl"
            )
            metrics = benchmark_tts_cases(
                adapter=PiperAdapter(executable.resolve(), model_path.resolve()),
                cases=cases,
                profile_id=args.profile,
                run_dir=run_dir,
                artifact=artifact,
                process_snapshot_provider=current_process_snapshot,
            )
        else:
            if args.profile != "phowhisper-small":
                raise SystemExit(f"unknown STT profile: {args.profile}")
            from offline_poc.stt import PhoWhisperAdapter
            import torch

            torch.set_num_threads(4)
            model_path = project_root / "models" / "phowhisper-small"
            metadata_path = project_root / "models" / "phowhisper-small.metadata.json"
            if not model_path.is_dir() or not metadata_path.is_file():
                raise SystemExit("missing PhoWhisper model or metadata")
            artifact = json.loads(metadata_path.read_text(encoding="utf-8"))
            metrics = benchmark_stt_manifest(
                adapter=PhoWhisperAdapter(model_path),
                audio_manifest=args.audio_manifest,
                profile_id=args.profile,
                run_dir=run_dir,
                artifact=artifact,
                process_snapshot_provider=current_process_snapshot,
            )
        print(
            json.dumps(
                {"run_dir": str(run_dir.resolve()), "metrics": metrics},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "llm":
        project_root = Path(__file__).resolve().parents[2]
        config = load_config(project_root / "config" / "benchmark.yaml")
        candidate = next(
            (item for item in config.candidates if item.profile_id == args.profile),
            None,
        )
        if candidate is None:
            raise SystemExit(f"unknown profile: {args.profile}")
        model_path = project_root / candidate.model_path
        metadata_path = Path(f"{model_path}.metadata.json")
        if not model_path.is_file() or not metadata_path.is_file():
            raise SystemExit(f"missing model or metadata for {args.profile}")

        run_dir = args.run_dir or _default_run_dir()
        create_run_dir(run_dir)
        all_cases = load_cases(
            _repo_root() / "eval" / "datasets" / "poc" / "v1" / "cases.jsonl"
        )
        cases = [
            case for case in all_cases if case.category in {"control", "nlu", "plan"}
        ]
        raw_artifact = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        artifact = {
            "profile_id": args.profile,
            "path": str(model_path.resolve()),
            "sha256": raw_artifact.get("Sha256") or raw_artifact.get("sha256"),
            "size_bytes": model_path.stat().st_size,
            "revision": raw_artifact.get("Revision") or raw_artifact.get("revision"),
            "license": raw_artifact.get("License") or raw_artifact.get("license"),
            "quantization": candidate.quantization,
        }
        process_snapshot: dict[str, Any] = {"server_pid": args.server_pid}
        process_snapshot_provider: Callable[[], dict[str, Any]] | None = None
        if args.server_pid:
            import psutil

            def read_process_snapshot() -> dict[str, Any]:
                process = psutil.Process(args.server_pid)
                memory = process.memory_info()
                return {
                    "rss_bytes_after": memory.rss,
                    "peak_rss_bytes": getattr(memory, "peak_wset", memory.rss),
                    "cpu_seconds_after": sum(process.cpu_times()[:2]),
                }

            process = psutil.Process(args.server_pid)
            memory = process.memory_info()
            process_snapshot.update(
                {
                    "rss_bytes_before": memory.rss,
                    "peak_rss_bytes": getattr(memory, "peak_wset", memory.rss),
                    "cpu_seconds_before": sum(process.cpu_times()[:2]),
                }
            )
            process_snapshot_provider = read_process_snapshot
        metrics = benchmark_llm_cases(
            client=LlamaClient(args.base_url, timeout_s=180),
            cases=cases,
            profile_id=args.profile,
            run_dir=run_dir,
            artifact=artifact,
            process_snapshot=process_snapshot,
            process_snapshot_provider=process_snapshot_provider,
        )
        print(
            json.dumps(
                {"run_dir": str(run_dir.resolve()), "metrics": metrics},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "e2e":
        result = execute_e2e_command(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("usable_for_summary") else 1

    run_dir = args.run_dir or _default_run_dir()
    raise SystemExit(
        f"'{args.command}' runtime is not configured yet; no run directory was created "
        f"({run_dir}). Complete local model/runtime setup first."
    )


if __name__ == "__main__":
    raise SystemExit(main())

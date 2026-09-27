from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
from typing import Sequence
from typing import Any

from offline_poc.scoring import (
    CandidateDecision,
    CandidateMetrics,
    evaluate_candidate,
)


def _load_raw_cases(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"missing raw case file: {path}")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    case_ids = [str(row.get("case_id", "")) for row in rows]
    trace_ids = [str(row.get("trace_id", "")) for row in rows]
    if any(not value for value in case_ids + trace_ids):
        raise ValueError("every raw case requires case_id and trace_id")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("duplicate case_id in raw evidence")
    if len(set(trace_ids)) != len(trace_ids):
        raise ValueError("duplicate trace_id in raw evidence")
    return rows


def _write_json_exclusive(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _markdown_report(
    manifest: dict[str, Any],
    metrics: CandidateMetrics,
    decision: CandidateDecision,
    raw_count: int,
) -> str:
    eligible = "có" if decision.eligible else "không"
    failed = ", ".join(decision.failed_gates) or "không có"
    return "\n".join(
        [
            f"# Benchmark offline — {manifest['profile_id']}",
            "",
            f"- Đủ điều kiện: {eligible}",
            f"- Các hard gate không đạt: {failed}",
            f"- Điểm có trọng số: {decision.weighted_score:.3f}/100",
            f"- Raw case đã xác minh: {raw_count}",
            "",
            "## Chỉ số hard gate",
            "",
            "| Metric | Giá trị |",
            "|---|---:|",
            f"| Offline | {str(metrics.offline).lower()} |",
            f"| Schema validity | {metrics.schema_validity:.3f} |",
            f"| Tool exact match | {metrics.tool_exact_match:.3f} |",
            f"| Safety violations | {metrics.safety_violations} |",
            f"| Duplicate executions | {metrics.duplicate_executions} |",
            f"| Citation validity | {metrics.citation_validity:.3f} |",
            f"| E2E p50 | {metrics.e2e_p50_ms:.1f} ms |",
            f"| E2E p95 | {metrics.e2e_p95_ms:.1f} ms |",
            f"| Peak RSS | {metrics.peak_rss_bytes} bytes |",
            f"| Model size | {metrics.model_size_bytes} bytes |",
            "",
            "## Các chiều xếp hạng",
            "",
            "| Chiều đánh giá | Giá trị chuẩn hóa |",
            "|---|---:|",
            *[
                f"| {name} | {value:.4f} |"
                for name, value in decision.components.items()
            ],
            "",
            "## Phạm vi quyết định",
            "",
            "Report này chỉ ghi nhận kết quả benchmark PoC. Đây không phải bằng chứng "
            "chứng nhận automotive safety hoặc production readiness.",
            "",
        ]
    )


def write_benchmark_report(
    run_dir: Path,
    manifest: dict[str, Any],
    metrics: CandidateMetrics,
) -> Path:
    raw_rows = _load_raw_cases(run_dir / "case_results.jsonl")
    expected_count = int(manifest.get("case_count", -1))
    if len(raw_rows) != expected_count:
        raise ValueError(
            f"raw case count {len(raw_rows)} does not match manifest {expected_count}"
        )

    targets = [
        run_dir / "manifest.json",
        run_dir / "metrics.json",
        run_dir / "benchmark_report.md",
    ]
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite run evidence: {existing}")

    memory_limit_gib = float(
        manifest.get("environment", {}).get("memory_limit_gib", 8)
    )
    decision = evaluate_candidate(metrics, memory_limit_gib=memory_limit_gib)
    metrics_payload = {
        "profile_id": manifest["profile_id"],
        "raw_case_count": len(raw_rows),
        "metrics": metrics.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
    }
    markdown = _markdown_report(manifest, metrics, decision, len(raw_rows))

    _write_json_exclusive(targets[0], manifest)
    _write_json_exclusive(targets[1], metrics_payload)
    with targets[2].open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)
    return targets[2]


def _verified_runs(run_root: Path) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in run_root.iterdir() if path.is_dir()):
        manifest_path = run_dir / "manifest.json"
        metrics_path = run_dir / "metrics.json"
        cases_path = run_dir / "case_results.jsonl"
        if not all(path.is_file() for path in (manifest_path, metrics_path, cases_path)):
            continue
        validity_path = run_dir / "validity.json"
        if validity_path.is_file():
            validity = json.loads(validity_path.read_text(encoding="utf-8"))
            if validity.get("usable_for_summary") is False:
                continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        metrics = json.loads(metrics_path.read_text(encoding="utf-8-sig"))
        raw_count = len(_load_raw_cases(cases_path))
        if raw_count != int(manifest["case_count"]):
            raise ValueError(f"raw count mismatch in {run_dir}")
        verified.append(
            {
                "run_id": run_dir.name,
                "run_dir": run_dir,
                "manifest": manifest,
                "metrics": metrics,
                "raw_count": raw_count,
            }
        )
    return verified


def _latest_by_profile(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for run in runs:
        profile = str(run["manifest"]["profile_id"])
        current = selected.get(profile)
        created = str(run["manifest"].get("created_at_utc", run["run_id"]))
        current_created = (
            str(current["manifest"].get("created_at_utc", current["run_id"]))
            if current
            else ""
        )
        if current is None or created > current_created:
            selected[profile] = run
    return selected


def _mib(value: int | float | None) -> str:
    if value is None:
        return "Chưa đo"
    return f"{float(value) / 1024 / 1024:.1f} MiB"


def _percent(value: float | None) -> str:
    if value is None:
        return "Chưa đo"
    return f"{value * 100:.1f}%"


def _llm_gate_status(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    failed: list[str] = []
    if float(metrics["schema_validity"]) < 1:
        failed.append("schema validity < 100%")
    if float(metrics["tool_exact_match"]) < 0.9:
        failed.append("tool exact match < 90%")
    latency = metrics["latency"]
    if float(latency["p50_ms"]) > 2500:
        failed.append("p50 > 2,500 ms")
    if float(latency["p95_ms"]) > 4500:
        failed.append("p95 > 4,500 ms")
    peak = metrics.get("process", {}).get("peak_rss_bytes")
    if peak is None or int(peak) > 8 * 1024**3:
        failed.append("peak RSS missing or > 8 GiB")
    return ("FAIL" if failed else "PASS", failed)


def write_spike_summary(run_root: Path, target: Path) -> Path:
    runs = _verified_runs(run_root)
    benchmark_runs = [
        run
        for run in runs
        if run["manifest"].get("run_type")
        in {
            "llm_microbenchmark",
            "tts_synthetic_benchmark",
            "stt_synthetic_benchmark",
        }
    ]
    e2e_runs = [
        run
        for run in runs
        if run["manifest"].get("run_type") == "interactive_e2e_demo"
    ]
    latest = _latest_by_profile(benchmark_runs)
    required = ["qwen25-05b-q4", "qwen25-3b-q4"]
    missing = [profile for profile in required if profile not in latest]
    if missing:
        raise ValueError(f"missing required profile runs: {missing}")

    llm_rows: list[str] = []
    failed_details: list[str] = []
    for profile in required:
        run = latest[profile]
        metrics = run["metrics"]
        status, failed = _llm_gate_status(metrics)
        artifact = run["manifest"].get("artifact", {})
        llm_rows.append(
            "| {profile} | {run_id} | {size} | {peak} | {schema} | {exact} | "
            "{repair} | {p50:,.1f} | {p95:,.1f} | {status} |".format(
                profile=profile,
                run_id=run["run_id"],
                size=_mib(artifact.get("size_bytes")),
                peak=_mib(metrics.get("process", {}).get("peak_rss_bytes")),
                schema=_percent(metrics.get("schema_validity")),
                exact=_percent(metrics.get("tool_exact_match")),
                repair=_percent(metrics.get("repair_rate")),
                p50=float(metrics["latency"]["p50_ms"]),
                p95=float(metrics["latency"]["p95_ms"]),
                status=status,
            )
        )
        failed_details.append(f"- `{profile}`: " + "; ".join(failed) + ".")

    voice_lines: list[str] = []
    tts = latest.get("piper-vais1000-medium")
    if tts:
        metrics = tts["metrics"]
        voice_lines.append(
            "| Piper vais1000 medium | TTS synthetic, 30 prompt | "
            f"{metrics['latency']['p50_ms']:,.1f} ms | "
            f"{metrics['latency']['p95_ms']:,.1f} ms | "
            f"{_mib(metrics.get('process_tree_peak_rss_bytes'))} | "
            f"RTF p50 {metrics['real_time_factor']['p50']:.2f} | "
            f"`{tts['run_id']}` |"
        )
    stt = latest.get("phowhisper-small")
    if stt:
        metrics = stt["metrics"]
        voice_lines.append(
            "| PhoWhisper-small | STT trên Piper synthetic, 30 WAV | "
            f"{metrics['warm_latency']['p50_ms']:,.1f} ms | "
            f"{metrics['warm_latency']['p95_ms']:,.1f} ms | "
            f"{_mib(metrics['process'].get('peak_rss_bytes'))} | "
            f"WER {_percent(metrics['wer_macro'])}; CER {_percent(metrics['cer_macro'])} | "
            f"`{stt['run_id']}` |"
        )

    e2e_lines: list[str] = []
    successful_e2e = 0
    for run in e2e_runs:
        metrics = run["metrics"]
        record = _load_raw_cases(run["run_dir"] / "case_results.jsonl")[0]
        outcome = str(record.get("outcome", metrics.get("outcome", "unknown")))
        status_labels = {
            "completed": "Hoàn tất",
            "grounded": "Grounded",
            "grounded_fallback": "Grounded fallback",
            "rejected_by_user": "Người dùng reject",
            "approval_expired": "Approval hết hạn",
            "execution_failed": "Thực thi lỗi",
            "failed_planning": "Planning lỗi",
        }
        if outcome in {"completed", "grounded", "grounded_fallback"}:
            successful_e2e += 1
        response_path = run["run_dir"] / "response.wav"
        relative_response = Path(
            os.path.relpath(response_path, target.parent)
        ).as_posix()
        approval = record.get("approval_decision") or "—"
        e2e_lines.append(
            "| {run_id} | {profile} | {case_id} | {route} | {approval} | "
            "{outcome} | {system:,.1f} ms | {human:,.1f} ms | "
            "[response.wav]({response}) |".format(
                run_id=run["run_id"],
                profile=run["manifest"]["profile_id"],
                case_id=record["case_id"],
                route=record.get("route", metrics.get("route", "—")),
                approval=approval,
                outcome=status_labels.get(outcome, outcome),
                system=float(metrics.get("system_total_ms", 0)),
                human=float(metrics.get("human_wait_ms", 0)),
                response=relative_response,
            )
        )

    inventory = []
    for profile in [*required, "piper-vais1000-medium", "phowhisper-small"]:
        run = latest.get(profile)
        if run:
            inventory.append(
                f"| `{run['run_id']}` | {run['manifest']['run_type']} | "
                f"{profile} | {run['raw_count']}/{run['manifest']['case_count']} | Hoàn tất |"
            )
    for run in e2e_runs:
        inventory.append(
            f"| `{run['run_id']}` | interactive_e2e_demo | "
            f"{run['manifest']['profile_id']} | "
            f"{run['raw_count']}/{run['manifest']['case_count']} | Hoàn tất |"
        )

    report = "\n".join(
        [
            "# SPIKE-001 — Benchmark AI Pipeline Offline",
            "",
            "## Kết luận",
            "",
            "**Quyết định chọn model: Not Yet.** Cả hai Q4 candidate đều chạy từ "
            "artifact local và nằm dưới giới hạn RAM 8 GiB, nhưng đều không đạt quality "
            "và latency hard gate. Không chọn model tốt nhất tương đối làm primary để "
            "tránh biến kết quả PoC chưa đạt thành quyết định production.",
            "",
            "Qwen2.5-3B Q4 có chất lượng tốt hơn 0.5B nhưng chậm hơn nhiều. Qwen2.5-0.5B "
            "Q4 phù hợp để tiếp tục thử classifier/router có grammar hẹp, không phù hợp "
            "làm planner tổng quát ở prompt hiện tại. Q8 không chạy vì cả hai Q4 bắt buộc "
            "đều đã trượt gate; tăng precision chưa xử lý được vấn đề prompt/schema/latency.",
            "",
            "## So sánh LLM — 20 case control/NLU/plan",
            "",
            "| Profile | Run ID | Kích thước model | Peak RSS | Schema hợp lệ | Tool exact | Repair | p50 ms | p95 ms | Gate |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
            *llm_rows,
            "",
            "Hard gate: schema 100%, tool exact ≥90%, p50 ≤2.500 ms, p95 ≤4.500 ms, "
            "peak RSS ≤8 GiB. Các chiều không đạt:",
            "",
            *failed_details,
            "",
            "## So sánh Voice",
            "",
            "| Profile | Giao thức | p50 | p95 | Peak RSS | Chất lượng/RTF | Run ID |",
            "|---|---|---:|---:|---:|---|---|",
            *(voice_lines or ["| Chưa chạy | — | — | — | — | — | — |"]),
            "",
            "Cold-first latency của PhoWhisper bao gồm thời gian load model; kết quả đo là "
            + (
                f"{stt['metrics']['cold_first_ms']:,.1f} ms với thời gian load model "
                f"{stt['metrics']['model_load_ms']:,.1f} ms."
                if stt
                else "chưa đo."
            ),
            "WER/CER ở trên dùng giọng sạch do Piper tạo và chỉ là integration evidence; "
            "không được trình bày như độ chính xác trên người lái Việt Nam thật, giọng "
            "vùng miền hoặc tiếng ồn cabin.",
            "",
            "## E2E demo tương tác",
            "",
            "Các run dưới đây truyền WAV thật qua các component local và ghi trace. "
            "Chúng không thay thế network-disabled 30-case acceptance hoặc p50/p95 benchmark.",
            "",
            "| Run ID | Profile | Case | Route | HITL | Kết quả | System latency | Human wait | Output |",
            "|---|---|---|---|---|---|---:|---:|---|",
            *(e2e_lines or ["| Chưa có run | — | — | — | — | — | — | — | — |"]),
            "",
            f"Số interactive E2E run có outcome an toàn/thành công: {successful_e2e}.",
            "",
            "## Danh sách run",
            "",
            "| Run ID | Loại benchmark | Profile | Raw evidence | Trạng thái |",
            "|---|---|---|---:|---|",
            *inventory,
            "",
            "## Môi trường và artifact",
            "",
            f"- Host: `{platform.platform()}`; kiến trúc `{platform.machine()}`; "
            f"CPU logic `{os.cpu_count()}`.",
            "- Giao thức tài nguyên: 4 CPU thread; llama.cpp context 4.096; "
            "completion tối đa 192 token cho LLM benchmark.",
            "- LLM runtime: llama.cpp b9637. STT runtime: Transformers/PyTorch CPU. "
            "TTS runtime: Piper 1.4.2/ONNX Runtime.",
            "- Nguồn model/voice, revision, license và SHA-256 được ghi trong từng "
            "run manifest và dưới `experiments/offline_poc/models/`.",
            "- Runtime artifact được dùng theo chế độ local-only. Host-level "
            "egress-disabled drill chưa được thực hiện và vẫn là acceptance item riêng.",
            "",
            "## Bằng chứng Safety, RAG và LangGraph",
            "",
            "Typed plan, bounded repair, LangGraph HITL interrupt, stale-state rejection, "
            "idempotent execution, grounded citation validation và refusal được kiểm tra bằng "
            f"automated test. Interactive E2E đã ghi {successful_e2e} run có outcome "
            "an toàn/thành công, nhưng chưa "
            "chạy một network-disabled 30-case real-model acceptance; vì vậy release gate "
            "Safety/RAG vẫn mở.",
            "",
            "## Thử nghiệm giới hạn tiếp theo",
            "",
            "1. Thay free-form multi-tool planning bằng deterministic intent/slot routing cho "
            "control phổ biến; dành model 3B cho explanation/RAG composition.",
            "2. Rút gọn JSON contract và dùng schema một tool mỗi lượt, sau đó chạy lại cùng "
            "20 case trên 0.5B và 3B.",
            "3. Đánh giá whisper.cpp/PhoWhisper quantized hoặc distil/streaming STT trên 5–8 "
            "người nói có consent cùng tiếng ồn cabin; không tối ưu theo Piper WER.",
            "4. Giữ Piper resident như service hoặc dùng Python API; benchmark fresh-process "
            "hiện tại làm steady-state TTS latency cao hơn thực tế.",
            "5. Mở rộng interactive demo thành 30-case acceptance và thực hiện explicit "
            "egress-disabled drill sau khi nhóm phê duyệt thay đổi trạng thái mạng.",
            "",
            "## Trạng thái deliverable",
            "",
            "- Benchmark report: hoàn tất với immutable raw evidence.",
            "- Bảng kết quả: hoàn tất.",
            "- Quyết định model cuối: `Not Yet`, kèm bounded follow-up experiment.",
            "- Interactive E2E demo code và raw evidence: hoàn tất cho control và RAG scenario.",
            "- Video demo: đang chờ nhóm quay; không commit video binary.",
            "- User research: chưa bắt đầu; được lập kế hoạch riêng trong roadmap 3–4 tuần.",
            "",
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8", newline="\n")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate SPIKE-001 reports")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--write-summary", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = write_spike_summary(args.root, args.write_summary)
    print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

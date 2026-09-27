import json
from pathlib import Path

import pytest

from offline_poc.report import write_benchmark_report, write_spike_summary
from offline_poc.scoring import CandidateMetrics, evaluate_candidate


def eligible_metrics(**overrides: object) -> CandidateMetrics:
    values: dict[str, object] = {
        "offline": True,
        "schema_validity": 1.0,
        "tool_exact_match": 0.95,
        "safety_violations": 0,
        "duplicate_executions": 0,
        "citation_validity": 1.0,
        "e2e_p50_ms": 900,
        "e2e_p95_ms": 1500,
        "peak_rss_bytes": 1_000_000_000,
        "model_size_bytes": 500_000_000,
        "quality_score": 0.92,
        "integration_stability": 1.0,
        "operational_simplicity": 0.9,
    }
    values.update(overrides)
    return CandidateMetrics(**values)


def test_safety_failure_disqualifies_fast_model() -> None:
    decision = evaluate_candidate(
        eligible_metrics(safety_violations=1), memory_limit_gib=8
    )

    assert decision.eligible is False
    assert "safety_violations" in decision.failed_gates


def test_performance_miss_is_reported_without_hiding_quality() -> None:
    decision = evaluate_candidate(
        eligible_metrics(e2e_p50_ms=2600, e2e_p95_ms=5000),
        memory_limit_gib=8,
    )

    assert decision.eligible is False
    assert {"e2e_p50_ms", "e2e_p95_ms"} <= set(decision.failed_gates)
    assert decision.components["quality"] == pytest.approx(0.92)


def test_report_cross_checks_raw_count_before_writing(tmp_path: Path) -> None:
    case_file = tmp_path / "case_results.jsonl"
    case_file.write_text(
        "\n".join(
            [
                json.dumps({"case_id": "A", "trace_id": "trace-a"}),
                json.dumps({"case_id": "B", "trace_id": "trace-b"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "profile_id": "qwen25-05b-q4",
        "case_count": 2,
        "environment": {"cpu_limit": 4, "memory_limit_gib": 8},
        "artifacts": [],
    }
    metrics = eligible_metrics()

    report_path = write_benchmark_report(tmp_path, manifest, metrics)

    assert report_path.is_file()
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "metrics.json").is_file()
    report = report_path.read_text(encoding="utf-8")
    assert "Đủ điều kiện: có" in report
    assert "Các hard gate không đạt: không có" in report
    assert "## Chỉ số hard gate" in report
    assert "## Phạm vi quyết định" in report


def test_report_refuses_mismatched_raw_count(tmp_path: Path) -> None:
    (tmp_path / "case_results.jsonl").write_text(
        json.dumps({"case_id": "A", "trace_id": "trace-a"}) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "profile_id": "qwen25-05b-q4",
        "case_count": 2,
        "environment": {"memory_limit_gib": 8},
        "artifacts": [],
    }

    with pytest.raises(ValueError, match="raw case count"):
        write_benchmark_report(tmp_path, manifest, eligible_metrics())

    assert not (tmp_path / "manifest.json").exists()


def test_spike_summary_selects_latest_runs_and_records_not_yet(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_root.mkdir()
    profiles = [
        ("run-05b", "qwen25-05b-q4", 0.55, 0.15, 3864, 10115, 627970048),
        ("run-3b", "qwen25-3b-q4", 0.70, 0.30, 11193, 40272, 2189578240),
    ]
    for run_id, profile, schema, exact, p50, p95, peak in profiles:
        run_dir = run_root / run_id
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "run_type": "llm_microbenchmark",
                    "profile_id": profile,
                    "created_at_utc": f"2026-07-30T10:00:0{len(run_id)}Z",
                    "case_count": 20,
                    "artifact": {"size_bytes": 123, "license": "test"},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "metrics.json").write_text(
            json.dumps(
                {
                    "schema_validity": schema,
                    "tool_exact_match": exact,
                    "repair_rate": 0.3,
                    "latency": {"p50_ms": p50, "p95_ms": p95},
                    "process": {"peak_rss_bytes": peak},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "case_results.jsonl").write_text(
            "\n".join(
                json.dumps({"case_id": f"C-{index}", "trace_id": f"T-{index}"})
                for index in range(20)
            )
            + "\n",
            encoding="utf-8",
        )

    e2e_dir = run_root / "run-e2e-control"
    e2e_dir.mkdir()
    (e2e_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_type": "interactive_e2e_demo",
                "profile_id": "qwen25-3b-q4",
                "created_at_utc": "2026-08-02T06:00:00Z",
                "case_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (e2e_dir / "metrics.json").write_text(
        json.dumps(
            {
                "profile_id": "qwen25-3b-q4",
                "case_id": "CTRL-002",
                "route": "control",
                "outcome": "completed",
                "system_total_ms": 39309.8,
                "human_wait_ms": 6.6,
            }
        ),
        encoding="utf-8",
    )
    (e2e_dir / "case_results.jsonl").write_text(
        json.dumps(
            {
                "case_id": "CTRL-002",
                "trace_id": "trace-e2e",
                "route": "control",
                "outcome": "completed",
                "approval_decision": "approve",
                "response_audio_path": str(e2e_dir / "response.wav"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (e2e_dir / "validity.json").write_text(
        json.dumps({"usable_for_summary": True}), encoding="utf-8"
    )
    (e2e_dir / "response.wav").write_bytes(b"RIFF-test")

    target = tmp_path / "summary.md"
    write_spike_summary(run_root, target)
    report = target.read_text(encoding="utf-8")

    assert "Not Yet" in report
    assert "run-05b" in report
    assert "run-3b" in report
    assert "55.0%" in report
    assert "## So sánh LLM" in report
    assert "## So sánh Voice" in report
    assert "## Danh sách run" in report
    assert "## Môi trường và artifact" in report
    assert "## Thử nghiệm giới hạn tiếp theo" in report
    assert "## Trạng thái deliverable" in report
    assert "## E2E demo tương tác" in report
    assert "run-e2e-control" in report
    assert "CTRL-002" in report
    assert "39,309.8 ms" in report
    assert "6.6 ms" in report
    assert "Interactive E2E đã ghi 1 run" in report
    assert "LLM comparison" not in report
    assert "Voice comparison" not in report

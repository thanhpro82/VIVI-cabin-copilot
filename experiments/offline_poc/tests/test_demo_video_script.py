from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "demo_video_evidence.ps1"
E2E_SCRIPT = PROJECT_ROOT / "scripts" / "run_e2e_demo.ps1"


def run_presenter(stage: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-Stage",
            stage,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_validate_stage_prints_current_fixture_contract() -> None:
    completed = run_presenter("Validate")

    assert completed.returncode == 0, completed.stderr
    assert "Purpose: Validate benchmark fixtures and dataset contract." in completed.stdout
    assert "Runs: python -m offline_poc.runner validate" in completed.stdout
    assert "Reads: config/benchmark.yaml and eval/datasets/poc/v1/cases.jsonl" in completed.stdout
    assert (
        "Does not: load models, benchmark latency/RAM, call the network, "
        "or prove full E2E."
    ) in completed.stdout
    start = completed.stdout.index("{")
    end = completed.stdout.rindex("}") + 1
    payload = json.loads(completed.stdout[start:end])
    assert payload["candidate_count"] == 3
    assert payload["required_profiles"] == [
        "qwen25-05b-q4",
        "qwen25-3b-q4",
    ]
    assert payload["case_count"] == 30
    assert "PASS - Validate evidence is current." in completed.stdout


def test_tests_stage_explains_contract_scope_before_running_tests() -> None:
    completed = run_presenter("Tests")

    assert completed.returncode == 0, completed.stderr
    assert "Purpose: Run component contract regression tests." in completed.stdout
    assert (
            "Runs: 17 tests in test_graph_hitl.py, test_rag.py, and test_voice.py."
        in completed.stdout
    )
    assert (
        "Covers: HITL/idempotency; RAG citations/refusal; "
        "voice adapters/offline guards."
    ) in completed.stdout
    assert (
        "Does not: benchmark real Qwen, PhoWhisper, or Piper models, "
        "or prove full real-model E2E."
    ) in completed.stdout
    assert "17 passed" in completed.stdout
    assert "PASS - Tests evidence is current." in completed.stdout


def test_unknown_stage_is_rejected_without_running_evidence() -> None:
    completed = run_presenter("Unknown")

    assert completed.returncode != 0
    assert "ValidateSet" in completed.stderr or "validation set" in completed.stderr
    assert "PASS -" not in completed.stdout


def test_e2e_wrapper_requires_profile_and_audio_but_not_approval() -> None:
    source = E2E_SCRIPT.read_text(encoding="utf-8")

    assert '[ValidateSet("qwen25-05b-q4", "qwen25-3b-q4")]' in source
    assert "[Parameter(Mandatory = $true)]" in source
    assert "[string]$AudioPath" in source
    assert "$resolvedAudio = (Resolve-Path -LiteralPath $AudioPath" in source
    assert "$Approval" not in source
    assert "--profile $Profile" in source
    assert "--audio-path $resolvedAudio" in source
    assert "--server-pid $process.Id" in source
    assert "Invoke-RestMethod" in source
    assert "finally" in source
    assert "Stop-Process -Id $process.Id -Force" in source

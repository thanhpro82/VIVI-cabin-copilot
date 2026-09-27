from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import time

from offline_poc.contracts import (
    ActionPlan,
    GroundedAnswer,
    GroundedClaim,
    PlanStep,
)
from offline_poc.e2e import E2ERunner, InteractiveApprovalProvider
from offline_poc.llm import LlmMeasurement
from offline_poc.rag import ManualIndex
from offline_poc.stt import Transcript
from offline_poc.tts import TtsMeasurement
from offline_poc.vehicle_mock import VehicleMock


def test_e2e_runtime_module_is_available() -> None:
    assert importlib.util.find_spec("offline_poc.e2e") is not None


MANUAL_PATH = Path("../../eval/datasets/poc/v1/manual.md")


class FakeStt:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio_path: Path) -> Transcript:
        assert audio_path.is_file()
        return Transcript(text=self.text, total_ms=12.5, load_ms=2.5)


class FakeLlm:
    def __init__(self, *, invalid_citation: bool = False) -> None:
        self.invalid_citation = invalid_citation

    def create_plan(
        self, text: str, state_version: int
    ) -> tuple[ActionPlan, LlmMeasurement]:
        return (
            ActionPlan(
                plan_id="plan-hvac-24",
                vehicle_state_version=state_version,
                requires_approval=True,
                steps=[
                    PlanStep(
                        step_id="step-1",
                        tool="set_hvac_temperature",
                        args={"temperature_c": 24},
                        safety_level="S2",
                    )
                ],
            ),
            LlmMeasurement(10, 5, 4, 0),
        )


    def create_grounded_answer(
        self, query: str, evidence: list[object]
    ) -> tuple[GroundedAnswer, LlmMeasurement]:
        item = evidence[0]
        page = 999 if self.invalid_citation else item.page
        return (
            GroundedAnswer(
                answer_text="Đèn TPMS báo một hoặc nhiều lốp có áp suất thấp.",
                claims=[
                    GroundedClaim(
                        text="Đèn TPMS báo áp suất lốp thấp.",
                        evidence_id=item.chunk_id,
                        section=item.section,
                        page=page,
                    )
                ],
            ),
            LlmMeasurement(8, 4, 3, 0),
        )


class FailingPlanLlm(FakeLlm):
    def create_plan(self, text: str, state_version: int) -> object:
        raise RuntimeError("planner unavailable")


class FakeTts:
    def synthesize(self, text: str, output_path: Path) -> TtsMeasurement:
        output_path.write_bytes(b"RIFF-e2e")
        return TtsMeasurement(total_ms=4, first_audio_ms=4, peak_rss_bytes=32)


class FakeApproval:
    def __init__(self, decision: str, age_seconds: float = 0.1) -> None:
        self.decision = decision
        self.age_seconds = age_seconds
        self.requests: list[dict[str, object]] = []

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        self.requests.append(payload)
        return {
            "decision": self.decision,
            "state_version": payload["vehicle_state_version"],
            "approval_age_seconds": self.age_seconds,
        }


def make_audio(path: Path) -> Path:
    path.write_bytes(b"RIFF-input")
    return path


def make_runner(
    tmp_path: Path,
    *,
    transcript: str,
    approval: FakeApproval,
    invalid_citation: bool = False,
    event_sink: object | None = None,
) -> tuple[E2ERunner, VehicleMock]:
    vehicle = VehicleMock.initial()
    runner = E2ERunner(
        stt=FakeStt(transcript),
        llm=FakeLlm(invalid_citation=invalid_citation),
        tts=FakeTts(),
        manual_index=ManualIndex.from_markdown(MANUAL_PATH),
        vehicle=vehicle,
        approval_provider=approval,
        profile_id="qwen25-3b-q4",
        output_dir=tmp_path,
        model_artifact={"sha256": "model-sha", "size_bytes": 123},
        audio_scope="test-synthetic",
        event_sink=event_sink or (lambda _: None),
    )
    return runner, vehicle


def test_control_e2e_waits_for_approval_and_writes_complete_evidence(
    tmp_path: Path,
) -> None:
    approval = FakeApproval("approve")
    runner, vehicle = make_runner(
        tmp_path, transcript="Đặt điều hòa 24 độ", approval=approval
    )

    result = runner.run(make_audio(tmp_path / "CTRL-002.wav"), case_id="CTRL-002")

    assert result.route == "control"
    assert result.outcome == "completed"
    assert result.approval_decision == "approve"
    assert vehicle.state["hvac"]["temperature_c"] == 24
    assert vehicle.command_count == 1
    assert len(approval.requests) == 1
    assert result.response_audio_path.read_bytes().startswith(b"RIFF")
    for name in (
        "manifest.json",
        "case_results.jsonl",
        "metrics.json",
        "trace.json",
        "response.wav",
        "validity.json",
    ):
        assert (tmp_path / name).is_file(), name
    validity = json.loads((tmp_path / "validity.json").read_text(encoding="utf-8"))
    assert validity["usable_for_summary"] is True
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert "human_wait_ms" in metrics
    assert "system_total_ms" in metrics
    assert "p50_ms" not in metrics


def test_control_reject_and_expired_approval_never_execute(tmp_path: Path) -> None:
    for decision, age, expected in (
        ("reject", 0.1, "rejected_by_user"),
        ("approve", 31.0, "approval_expired"),
    ):
        run_dir = tmp_path / expected
        run_dir.mkdir()
        runner, vehicle = make_runner(
            run_dir,
            transcript="Đặt điều hòa 24 độ",
            approval=FakeApproval(decision, age),
        )

        result = runner.run(
            make_audio(run_dir / "CTRL-002.wav"), case_id="CTRL-002"
        )

        assert result.outcome == expected
        assert vehicle.command_count == 0
        assert vehicle.state["hvac"]["temperature_c"] == 27


def test_rag_e2e_uses_qwen_grounded_answer_and_validates_citation(
    tmp_path: Path,
) -> None:
    runner, vehicle = make_runner(
        tmp_path,
        transcript="Đèn cảnh báo áp suất lốp nghĩa là gì?",
        approval=FakeApproval("approve"),
    )

    result = runner.run(make_audio(tmp_path / "RAG-001.wav"), case_id="RAG-001")

    assert result.route == "rag"
    assert result.outcome == "grounded"
    assert result.citation_valid is True
    assert result.citations == [{"evidence_id": "manual:TPMS:p112:0", "section": "TPMS", "page": 112}]
    assert vehicle.command_count == 0


def test_invalid_qwen_citation_falls_back_to_evidence_text(tmp_path: Path) -> None:
    runner, _ = make_runner(
        tmp_path,
        transcript="Đèn cảnh báo áp suất lốp nghĩa là gì?",
        approval=FakeApproval("approve"),
        invalid_citation=True,
    )

    result = runner.run(make_audio(tmp_path / "RAG-001.wav"), case_id="RAG-001")

    assert result.outcome == "grounded_fallback"
    assert result.citation_valid is True
    assert "giảm tốc an toàn" in result.response_text
    assert result.citations[0]["page"] == 112


def test_interactive_approval_times_out_without_a_decision() -> None:
    def slow_input(_: str) -> str:
        time.sleep(0.05)
        return "A"

    provider = InteractiveApprovalProvider(
        timeout_seconds=0.01,
        input_func=slow_input,
        output_func=lambda _: None,
    )

    decision = provider.request(
        {
            "plan_id": "plan-1",
            "vehicle_state_version": 1,
            "steps": [],
            "expires_in_seconds": 0.01,
        }
    )

    assert decision["decision"] == "timeout"
    assert decision["approval_age_seconds"] >= 0.01


def test_planning_failure_produces_safe_audio_and_invalid_evidence(
    tmp_path: Path,
) -> None:
    runner, vehicle = make_runner(
        tmp_path,
        transcript="Đặt điều hòa 24 độ",
        approval=FakeApproval("approve"),
    )
    runner.llm = FailingPlanLlm()

    result = runner.run(make_audio(tmp_path / "CTRL-002.wav"), case_id="CTRL-002")

    assert result.outcome == "failed_planning"
    assert "không thể lập kế hoạch" in result.response_text.casefold()
    assert result.response_audio_path.read_bytes().startswith(b"RIFF")
    assert vehicle.command_count == 0
    validity = json.loads((tmp_path / "validity.json").read_text(encoding="utf-8"))
    assert validity["usable_for_summary"] is False
    assert validity["error_type"] == "RuntimeError"


def test_e2e_emits_presenter_friendly_stage_progress(tmp_path: Path) -> None:
    events: list[str] = []
    runner, _ = make_runner(
        tmp_path,
        transcript="Đặt điều hòa 24 độ",
        approval=FakeApproval("approve"),
        event_sink=events.append,
    )

    runner.run(make_audio(tmp_path / "CTRL-002.wav"), case_id="CTRL-002")

    output = "\n".join(events)
    assert "[1/7] File WAV" in output
    assert "[2/7] PhoWhisper transcript" in output
    assert "[3/7] Route: control" in output
    assert "[4/7] Qwen ActionPlan" in output
    assert "[5/7] HITL/VehicleMock" in output
    assert "[6/7] Piper response WAV" in output
    assert "[7/7] Evidence" in output

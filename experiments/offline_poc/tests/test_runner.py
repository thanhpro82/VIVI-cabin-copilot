from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest
import offline_poc.runner as runner_module

from offline_poc.contracts import ActionPlan, PlanStep, ToolResult
from offline_poc.dataset import PocCase
from offline_poc.llm import LlmMeasurement, PlanGenerationError
from offline_poc.runner import (
    OfflinePipeline,
    benchmark_llm_cases,
    benchmark_stt_manifest,
    benchmark_tts_cases,
    build_parser,
    create_run_dir,
)
from offline_poc.stt import Transcript
from offline_poc.tts import TtsMeasurement


@dataclass
class FakeTranscript:
    text: str = "đặt điều hòa 24 độ"


class FakeStt:
    def transcribe(self, audio_path: Path) -> FakeTranscript:
        return FakeTranscript()


class FakeGraph:
    def invoke_approved(self, text: str) -> list[ToolResult]:
        return [
            ToolResult(
                command_id="plan-1:step-1",
                step_id="step-1",
                status="completed",
                before={"temperature_c": 27},
                after={"temperature_c": 24},
                latency_ms=10,
            )
        ]


class FakeTts:
    def synthesize(self, text: str, output: Path) -> None:
        output.write_bytes(b"RIFF-test")


def test_pipeline_emits_complete_trace_and_flushes_case_record(tmp_path: Path) -> None:
    pipeline = OfflinePipeline(
        stt=FakeStt(), graph=FakeGraph(), tts=FakeTts(), output_dir=tmp_path
    )

    result = pipeline.run_audio_case("audio-ctrl-002")

    required = {
        "speech_end",
        "stt_completed",
        "plan_completed",
        "rag_or_tool_completed",
        "first_tts_audio",
        "playback_completed",
    }
    assert required <= set(result.trace.marks_ns)
    assert result.tool_results[0].status == "completed"
    assert result.response_audio_path.read_bytes().startswith(b"RIFF")

    rows = (tmp_path / "case_results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    record = json.loads(rows[0])
    assert record["case_id"] == "audio-ctrl-002"
    assert required <= set(record["trace_ns"])


def test_run_directory_is_immutable_by_default(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-001"

    assert create_run_dir(run_dir) == run_dir
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        create_run_dir(run_dir)


class FakeLlm:
    def create_plan(
        self, text: str, state_version: int
    ) -> tuple[ActionPlan, LlmMeasurement]:
        if text == "bad":
            raise PlanGenerationError(
                raw_output="bad-raw",
                repair_output="bad-repair",
                total_ms=20,
                prompt_tokens=10,
                completion_tokens=5,
                validation_error=ValueError("invalid"),
            )
        return (
            ActionPlan(
                plan_id="plan-1",
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
            LlmMeasurement(
                total_ms=10,
                prompt_tokens=8,
                completion_tokens=4,
                repair_attempts=0,
            ),
        )


def test_llm_benchmark_keeps_success_and_failure_evidence(tmp_path: Path) -> None:
    cases = [
        PocCase(
            case_id="CTRL-TEST",
            category="control",
            input_text="good",
            vehicle_state={"state_version": 1},
            expected={
                "tools": [
                    {
                        "name": "set_hvac_temperature",
                        "args": {"temperature_c": 24},
                    }
                ]
            },
        ),
        PocCase(
            case_id="NLU-TEST",
            category="nlu",
            input_text="bad",
            vehicle_state={"state_version": 1},
            expected={"tools": []},
        ),
    ]

    metrics = benchmark_llm_cases(
        client=FakeLlm(),
        cases=cases,
        profile_id="fake-q4",
        run_dir=tmp_path,
        artifact={"sha256": "abc", "size_bytes": 123},
        process_snapshot={"peak_rss_bytes": 456},
        process_snapshot_provider=lambda: {
            "peak_rss_bytes": 789,
            "rss_bytes_after": 654,
        },
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "case_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["schema_valid"] is True
    assert rows[1]["schema_valid"] is False
    assert rows[1]["raw_output"] == "bad-raw"
    assert metrics["schema_validity"] == 0.5
    assert metrics["tool_exact_match"] == 0.5
    assert metrics["process"]["peak_rss_bytes"] == 789
    assert metrics["process"]["rss_bytes_after"] == 654
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "metrics.json").is_file()


class BenchmarkFakeTts:
    def synthesize(self, text: str, output: Path) -> TtsMeasurement:
        with wave.open(str(output), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 1600)
        return TtsMeasurement(total_ms=25, first_audio_ms=25, peak_rss_bytes=123)


class BenchmarkFakeStt:
    def transcribe(self, audio_path: Path) -> Transcript:
        return Transcript(text="đặt điều hòa 24 độ", total_ms=40, load_ms=10)


def test_voice_benchmarks_write_synthetic_manifest_and_metrics(
    tmp_path: Path,
) -> None:
    cases = [
        PocCase(
            case_id="CTRL-TEST",
            category="control",
            input_text="Đặt điều hòa 24 độ",
            vehicle_state={},
            expected={},
        )
    ]
    tts_run = tmp_path / "tts"
    stt_run = tmp_path / "stt"

    tts_metrics = benchmark_tts_cases(
        adapter=BenchmarkFakeTts(),
        cases=cases,
        profile_id="fake-piper",
        run_dir=tts_run,
        artifact={"sha256": "tts-sha"},
    )
    audio_manifest = tts_run / "synthetic_audio_manifest.jsonl"
    audio_row = json.loads(audio_manifest.read_text(encoding="utf-8"))
    assert audio_row["consent_scope"] == "synthetic-licensed-piper-poc"
    assert tts_metrics["case_count"] == 1
    assert tts_metrics["real_time_factor"]["p50"] == 0.25
    assert "p50_ms" not in tts_metrics["real_time_factor"]
    assert tts_metrics["process_tree_peak_rss_bytes"] == 123

    stt_metrics = benchmark_stt_manifest(
        adapter=BenchmarkFakeStt(),
        audio_manifest=audio_manifest,
        profile_id="fake-whisper",
        run_dir=stt_run,
        artifact={"sha256": "stt-sha"},
    )
    assert stt_metrics["wer_macro"] == 0
    assert stt_metrics["cer_macro"] == 0
    assert stt_metrics["latency"]["p50_ms"] == 40
    assert len(
        (stt_run / "case_results.jsonl").read_text(encoding="utf-8").splitlines()
    ) == 1


def test_stt_cli_requires_explicit_audio_manifest() -> None:
    args = build_parser().parse_args(
        [
            "stt",
            "--profile",
            "phowhisper-small",
            "--audio-manifest",
            "audio.jsonl",
        ]
    )

    assert args.audio_manifest == Path("audio.jsonl")


def test_e2e_cli_requires_explicit_profile_and_audio_without_approval() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "e2e",
            "--profile",
            "qwen25-3b-q4",
            "--audio-path",
            "input.wav",
            "--base-url",
            "http://127.0.0.1:8080/v1",
            "--server-pid",
            "1234",
        ]
    )

    assert args.profile == "qwen25-3b-q4"
    assert args.audio_path == Path("input.wav")
    assert args.base_url == "http://127.0.0.1:8080/v1"
    assert args.server_pid == 1234

    with pytest.raises(SystemExit):
        parser.parse_args(["e2e", "--profile", "qwen25-3b-q4"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "e2e",
                "--profile",
                "qwen25-3b-q4",
                "--audio-path",
                "input.wav",
                "--approval",
                "approve",
            ]
        )


def test_e2e_main_dispatches_to_real_runtime_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "CTRL-002.wav"
    audio.write_bytes(b"RIFF-test")
    captured: dict[str, object] = {}

    def fake_execute(args: object) -> dict[str, object]:
        captured["args"] = args
        return {
            "usable_for_summary": True,
            "run_dir": str(tmp_path / "run"),
            "outcome": "completed",
        }

    monkeypatch.setattr(
        runner_module, "execute_e2e_command", fake_execute, raising=False
    )

    exit_code = runner_module.main(
        [
            "e2e",
            "--profile",
            "qwen25-3b-q4",
            "--audio-path",
            str(audio),
        ]
    )

    assert exit_code == 0
    args = captured["args"]
    assert args.profile == "qwen25-3b-q4"
    assert args.audio_path == audio


def test_execute_e2e_rejects_unknown_profile_before_creating_run(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"RIFF-test")
    run_dir = tmp_path / "run"
    args = SimpleNamespace(
        profile="unknown-model",
        audio_path=audio,
        base_url="http://127.0.0.1:8080/v1",
        server_pid=None,
        run_dir=run_dir,
    )

    with pytest.raises(SystemExit, match="unknown E2E profile"):
        runner_module.execute_e2e_command(args)

    assert not run_dir.exists()


def test_execute_e2e_assembles_local_components_and_returns_validity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import offline_poc.e2e as e2e_module

    audio = tmp_path / "CTRL-002.wav"
    audio.write_bytes(b"RIFF-test")
    run_dir = tmp_path / "run"
    captured: dict[str, object] = {}

    class FakeResult:
        case_id = "CTRL-002"
        outcome = "completed"
        route = "control"
        response_audio_path = run_dir / "response.wav"

    class CapturingRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, audio_path: Path, *, case_id: str) -> FakeResult:
            captured["audio_path"] = audio_path
            captured["case_id"] = case_id
            (run_dir / "response.wav").write_bytes(b"RIFF-output")
            (run_dir / "validity.json").write_text(
                json.dumps({"usable_for_summary": True}), encoding="utf-8"
            )
            return FakeResult()

    monkeypatch.setattr(e2e_module, "E2ERunner", CapturingRunner)
    args = SimpleNamespace(
        profile="qwen25-3b-q4",
        audio_path=audio,
        base_url="http://127.0.0.1:8080/v1",
        server_pid=None,
        run_dir=run_dir,
    )

    result = runner_module.execute_e2e_command(args)

    assert result["usable_for_summary"] is True
    assert result["outcome"] == "completed"
    assert result["route"] == "control"
    assert captured["profile_id"] == "qwen25-3b-q4"
    assert captured["audio_path"] == audio
    assert captured["case_id"] == "CTRL-002"
    assert run_dir.is_dir()

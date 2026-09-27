"""Interactive local E2E runtime for SPIKE-001."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable, Protocol
from uuid import uuid4

from langgraph.types import Command

from offline_poc.graph import build_graph
from offline_poc.rag import Evidence, ManualIndex, validate_citations
from offline_poc.vehicle_mock import VehicleMock


class ApprovalProvider(Protocol):
    def request(self, payload: dict[str, object]) -> dict[str, object]: ...


@dataclass(frozen=True)
class E2EResult:
    case_id: str
    trace_id: str
    route: str
    outcome: str
    transcript_text: str
    response_text: str
    response_audio_path: Path
    approval_decision: str | None
    citation_valid: bool | None
    citations: list[dict[str, object]]


class InteractiveApprovalProvider:
    """Read an A/R decision without blocking beyond the approval deadline."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        input_func: Callable[[str], str] = input,
        output_func: Callable[[str], None] = print,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.input_func = input_func
        self.output_func = output_func

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        configured_timeout = float(payload.get("expires_in_seconds", self.timeout_seconds))
        timeout = min(self.timeout_seconds, configured_timeout)
        started = time.monotonic()
        deadline = started + timeout
        self._render(payload, timeout)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._decision("timeout", payload, started)

            answers: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

            def read_answer() -> None:
                try:
                    answers.put(("value", self.input_func("Lựa chọn của bạn: ")))
                except (EOFError, KeyboardInterrupt) as exc:
                    answers.put(("eof", exc))

            thread = threading.Thread(target=read_answer, daemon=True)
            thread.start()
            try:
                kind, value = answers.get(timeout=remaining)
            except queue.Empty:
                return self._decision("timeout", payload, started)
            if kind == "eof":
                return self._decision("reject", payload, started)

            normalized = str(value).strip().casefold()
            if normalized in {"a", "approve"}:
                return self._decision("approve", payload, started)
            if normalized in {"r", "reject"}:
                return self._decision("reject", payload, started)
            self.output_func("Chỉ chấp nhận A (Approve) hoặc R (Reject).")

    def _decision(
        self, decision: str, payload: dict[str, object], started: float
    ) -> dict[str, object]:
        return {
            "decision": decision,
            "state_version": payload["vehicle_state_version"],
            "approval_age_seconds": time.monotonic() - started,
        }

    def _render(self, payload: dict[str, object], timeout: float) -> None:
        self.output_func("YÊU CẦU XÁC NHẬN HITL")
        self.output_func(f"Plan: {payload.get('plan_id')}")
        for step in payload.get("steps", []):
            if isinstance(step, dict):
                args = json.dumps(step.get("args", {}), ensure_ascii=False)
                self.output_func(f"- {step.get('tool')} {args}")
        self.output_func(f"Hết hạn sau: {timeout:g} giây")
        self.output_func("[A] Approve    [R] Reject")


class E2ERunner:
    def __init__(
        self,
        *,
        stt: Any,
        llm: Any,
        tts: Any,
        manual_index: ManualIndex,
        vehicle: VehicleMock,
        approval_provider: ApprovalProvider,
        profile_id: str,
        output_dir: Path,
        model_artifact: dict[str, Any],
        audio_scope: str,
        event_sink: Callable[[str], None] = print,
    ) -> None:
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.manual_index = manual_index
        self.vehicle = vehicle
        self.approval_provider = approval_provider
        self.profile_id = profile_id
        self.output_dir = output_dir
        self.model_artifact = dict(model_artifact)
        self.audio_scope = audio_scope
        self.event_sink = event_sink

    def run(self, audio_path: Path, *, case_id: str | None = None) -> E2EResult:
        if not audio_path.is_file():
            raise ValueError(f"missing input audio: {audio_path}")
        try:
            return self._run_success(audio_path, case_id=case_id)
        except FileExistsError:
            raise
        except Exception as exc:
            return self._write_failure_result(audio_path, case_id, exc)

    def _run_success(
        self, audio_path: Path, *, case_id: str | None = None
    ) -> E2EResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        targets = [
            self.output_dir / name
            for name in (
                "manifest.json",
                "case_results.jsonl",
                "metrics.json",
                "trace.json",
                "response.wav",
                "validity.json",
            )
        ]
        existing = [str(path) for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"refusing to overwrite E2E evidence: {existing}")

        resolved_case_id = case_id or audio_path.stem
        trace_id = f"trace-{uuid4()}"
        wall_started = time.perf_counter()
        marks_ms: dict[str, float] = {"audio_received": 0.0}
        stage_ms: dict[str, float] = {}
        self.event_sink(f"[1/7] File WAV: {audio_path}")

        def mark(name: str) -> None:
            marks_ms[name] = (time.perf_counter() - wall_started) * 1000

        stt_started = time.perf_counter()
        transcript = self.stt.transcribe(audio_path)
        stage_ms["stt"] = (time.perf_counter() - stt_started) * 1000
        mark("stt_completed")
        self.event_sink(f"[2/7] PhoWhisper transcript: {transcript.text}")

        route_started = time.perf_counter()
        evidence = self.manual_index.search(transcript.text, k=5)
        route = "rag" if evidence else "control"
        stage_ms["routing"] = (time.perf_counter() - route_started) * 1000
        mark("route_selected")
        self.event_sink(f"[3/7] Route: {route}")

        approval_decision: str | None = None
        human_wait_ms = 0.0
        citations: list[dict[str, object]] = []
        citation_valid: bool | None = None
        plan_payload: dict[str, Any] | None = None
        tool_results: list[Any] = []

        if route == "rag":
            llm_started = time.perf_counter()
            answer, measurement = self.llm.create_grounded_answer(
                transcript.text, evidence
            )
            self.event_sink("[4/7] Qwen grounded answer đã được tạo.")
            stage_ms["llm_or_rag"] = max(
                float(measurement.total_ms),
                (time.perf_counter() - llm_started) * 1000,
            )
            evidence_by_id = {item.chunk_id: item for item in evidence}
            claims = [item.model_dump(mode="json") for item in answer.claims]
            if validate_citations(claims, evidence_by_id):
                outcome = "grounded"
                response_text = answer.answer_text
                citations = [
                    {
                        "evidence_id": item.evidence_id,
                        "section": item.section,
                        "page": item.page,
                    }
                    for item in answer.claims
                ]
            else:
                outcome = "grounded_fallback"
                response_text, citations = self._grounded_fallback(evidence[0])
            citation_valid = True
            mark("rag_completed")
            self.event_sink(f"[5/7] RAG citation: {outcome}")
        else:
            measurement_box: list[Any] = []

            def planner(text: str, state_version: int, vehicle: VehicleMock) -> Any:
                plan, measurement = self.llm.create_plan(text, state_version)
                measurement_box.append(measurement)
                return plan

            graph = build_graph(self.vehicle, planner=planner)
            config = {"configurable": {"thread_id": trace_id}}
            graph_started = time.perf_counter()
            graph_result = graph.invoke(
                {
                    "input_text": transcript.text,
                    "vehicle_state_version": self.vehicle.state["state_version"],
                },
                config=config,
            )
            mark("plan_and_safety_completed")
            self.event_sink("[4/7] Qwen ActionPlan đã qua schema validation.")
            if measurement_box:
                stage_ms["llm_or_rag"] = float(measurement_box[0].total_ms)
            interrupts = graph_result.get("__interrupt__", ())
            if interrupts:
                payload = self._interrupt_payload(interrupts[0])
                approval_started = time.perf_counter()
                approval = self.approval_provider.request(payload)
                human_wait_ms = (time.perf_counter() - approval_started) * 1000
                approval_decision = str(approval.get("decision"))
                graph_result = graph.invoke(Command(resume=approval), config=config)
                mark("approval_resumed")
            stage_ms["graph_and_tool"] = (time.perf_counter() - graph_started) * 1000
            outcome = str(graph_result.get("outcome", "failed"))
            response_text = str(graph_result.get("response_text", "Không thể xử lý lệnh."))
            plan = graph_result.get("plan")
            plan_payload = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
            tool_results = list(graph_result.get("tool_results", []))
            mark("control_completed")
            self.event_sink(f"[5/7] HITL/VehicleMock: {outcome}")

        tts_started = time.perf_counter()
        response_audio = self.output_dir / "response.wav"
        tts_measurement = self.tts.synthesize(response_text, response_audio)
        stage_ms["tts"] = max(
            float(getattr(tts_measurement, "total_ms", 0)),
            (time.perf_counter() - tts_started) * 1000,
        )
        mark("response_audio_completed")
        self.event_sink(f"[6/7] Piper response WAV: {response_audio}")
        wall_total_ms = (time.perf_counter() - wall_started) * 1000
        system_total_ms = max(0.0, wall_total_ms - human_wait_ms)

        result = E2EResult(
            case_id=resolved_case_id,
            trace_id=trace_id,
            route=route,
            outcome=outcome,
            transcript_text=transcript.text,
            response_text=response_text,
            response_audio_path=response_audio,
            approval_decision=approval_decision,
            citation_valid=citation_valid,
            citations=citations,
        )
        self._write_evidence(
            result=result,
            input_audio=audio_path,
            marks_ms=marks_ms,
            stage_ms=stage_ms,
            wall_total_ms=wall_total_ms,
            system_total_ms=system_total_ms,
            human_wait_ms=human_wait_ms,
            plan=plan_payload,
            tool_results=tool_results,
        )
        self.event_sink(f"[7/7] Evidence: {self.output_dir}")
        return result

    def _write_failure_result(
        self, audio_path: Path, case_id: str | None, exc: Exception
    ) -> E2EResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        resolved_case_id = case_id or audio_path.stem
        trace_id = f"trace-{uuid4()}"
        response_text = (
            "Tôi không thể lập kế hoạch hoặc xử lý yêu cầu này. "
            "Không có lệnh điều khiển nào được thực thi."
        )
        response_audio = self.output_dir / "response.wav"
        if not response_audio.exists():
            self.tts.synthesize(response_text, response_audio)
        result = E2EResult(
            case_id=resolved_case_id,
            trace_id=trace_id,
            route="control",
            outcome="failed_planning",
            transcript_text="",
            response_text=response_text,
            response_audio_path=response_audio,
            approval_decision=None,
            citation_valid=None,
            citations=[],
        )
        manifest = {
            "run_type": "interactive_e2e_demo",
            "profile_id": self.profile_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_count": 1,
            "artifact": self.model_artifact,
            "input_audio": {
                "path": str(audio_path.resolve()),
                "sha256": _sha256(audio_path),
                "scope": self.audio_scope,
            },
            "approval_mode": "interactive",
        }
        record = {
            "case_id": resolved_case_id,
            "trace_id": trace_id,
            "route": "control",
            "outcome": "failed_planning",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "response_text": response_text,
            "response_audio_path": str(response_audio.resolve()),
        }
        _write_json(self.output_dir / "manifest.json", manifest)
        with (self.output_dir / "case_results.jsonl").open(
            "x", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        _write_json(
            self.output_dir / "metrics.json",
            {
                "profile_id": self.profile_id,
                "case_id": resolved_case_id,
                "route": "control",
                "outcome": "failed_planning",
                "stage_ms": {},
                "system_total_ms": 0.0,
                "human_wait_ms": 0.0,
                "wall_total_ms": 0.0,
            },
        )
        _write_json(
            self.output_dir / "trace.json",
            {"trace_id": trace_id, "marks_ms": {}, "error": str(exc)},
        )
        _write_json(
            self.output_dir / "validity.json",
            {
                "usable_for_summary": False,
                "scope": "interactive_demo_only",
                "network_disabled_acceptance": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return result

    @staticmethod
    def _interrupt_payload(interrupt: Any) -> dict[str, object]:
        value = getattr(interrupt, "value", interrupt)
        if not isinstance(value, dict):
            raise ValueError("LangGraph interrupt payload must be an object")
        return value

    @staticmethod
    def _grounded_fallback(
        evidence: Evidence,
    ) -> tuple[str, list[dict[str, object]]]:
        citation = {
            "evidence_id": evidence.chunk_id,
            "section": evidence.section,
            "page": evidence.page,
        }
        return evidence.text, [citation]

    def _write_evidence(
        self,
        *,
        result: E2EResult,
        input_audio: Path,
        marks_ms: dict[str, float],
        stage_ms: dict[str, float],
        wall_total_ms: float,
        system_total_ms: float,
        human_wait_ms: float,
        plan: dict[str, Any] | None,
        tool_results: list[Any],
    ) -> None:
        manifest = {
            "run_type": "interactive_e2e_demo",
            "profile_id": self.profile_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_count": 1,
            "artifact": self.model_artifact,
            "input_audio": {
                "path": str(input_audio.resolve()),
                "sha256": _sha256(input_audio),
                "scope": self.audio_scope,
            },
            "approval_mode": "interactive",
        }
        record = {
            "case_id": result.case_id,
            "trace_id": result.trace_id,
            "route": result.route,
            "outcome": result.outcome,
            "transcript_text": result.transcript_text,
            "approval_decision": result.approval_decision,
            "plan": plan,
            "tool_results": [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in tool_results
            ],
            "citations": result.citations,
            "citation_valid": result.citation_valid,
            "response_text": result.response_text,
            "response_audio_path": str(result.response_audio_path.resolve()),
        }
        metrics = {
            "profile_id": self.profile_id,
            "case_id": result.case_id,
            "route": result.route,
            "outcome": result.outcome,
            "stage_ms": stage_ms,
            "system_total_ms": system_total_ms,
            "human_wait_ms": human_wait_ms,
            "wall_total_ms": wall_total_ms,
        }
        trace = {"trace_id": result.trace_id, "marks_ms": marks_ms}
        validity = {
            "usable_for_summary": True,
            "scope": "interactive_demo_only",
            "network_disabled_acceptance": False,
        }
        _write_json(self.output_dir / "manifest.json", manifest)
        with (self.output_dir / "case_results.jsonl").open(
            "x", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        _write_json(self.output_dir / "metrics.json", metrics)
        _write_json(self.output_dir / "trace.json", trace)
        _write_json(self.output_dir / "validity.json", validity)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Sequence
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from offline_poc.contracts import ActionPlan, GroundedAnswer
from offline_poc.rag import Evidence


ACTION_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plan_id": {"type": "string", "minLength": 1},
        "vehicle_state_version": {"type": "integer", "minimum": 0},
        "requires_approval": {"type": "boolean"},
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string", "minLength": 1},
                    "tool": {
                        "type": "string",
                        "enum": [
                            "set_hvac_temperature",
                            "set_hvac_power",
                            "set_seat_heating",
                            "set_window_position",
                            "media_control",
                            "search_nearby",
                            "set_navigation",
                            "set_door_state",
                        ],
                    },
                    "args": {"type": "object"},
                    "safety_level": {
                        "type": "string",
                        "enum": ["S0", "S1", "S2", "S3"],
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "step_id",
                    "tool",
                    "args",
                    "safety_level",
                    "depends_on",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "plan_id",
        "vehicle_state_version",
        "requires_approval",
        "steps",
    ],
    "additionalProperties": False,
}


GROUNDED_ANSWER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer_text": {"type": "string", "minLength": 1},
        "claims": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "evidence_id": {"type": "string", "minLength": 1},
                    "section": {"type": "string", "minLength": 1},
                    "page": {"type": "integer", "minimum": 1},
                },
                "required": ["text", "evidence_id", "section", "page"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer_text", "claims"],
    "additionalProperties": False,
}


SYSTEM_PLAN_CONTRACT = """You are a bounded Vietnamese vehicle command planner.
Return one ActionPlan JSON object and no explanation.

Tool rules:
- set_hvac_temperature args: {"temperature_c": 16..30}; safety S2.
- set_hvac_power args: {"enabled": boolean}; safety S2.
- set_seat_heating args: {"seat": "driver"|"passenger", "level": 0..3}; safety S2.
- set_window_position args: {"window": "front_left"|"front_right", "percent": 0..100}; safety S2.
- media_control args: {"action": "play"|"pause"|"set_volume", optional "value": 0..100}; safety S1.
- search_nearby and set_navigation are S1. Opening a door is S3 while moving.
- Any S2 step requires requires_approval=true.
- Copy vehicle_state_version exactly from the request.

Example for request 'Đặt điều hòa 24 độ' at state version 1:
{"plan_id":"plan-hvac-24","vehicle_state_version":1,"requires_approval":true,"steps":[{"step_id":"step-1","tool":"set_hvac_temperature","args":{"temperature_c":24},"safety_level":"S2","depends_on":[]}]}

Required JSON Schema:
""" + json.dumps(ACTION_PLAN_JSON_SCHEMA, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class LlmMeasurement:
    total_ms: float
    prompt_tokens: int
    completion_tokens: int
    repair_attempts: int


class PlanGenerationError(ValueError):
    def __init__(
        self,
        *,
        raw_output: str,
        repair_output: str,
        total_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        validation_error: Exception,
    ) -> None:
        super().__init__(f"ActionPlan remained invalid after one repair: {validation_error}")
        self.raw_output = raw_output
        self.repair_output = repair_output
        self.total_ms = total_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.repair_attempts = 1


class LlamaClient:
    """Small OpenAI-compatible client for a local llama.cpp/Ollama endpoint."""

    _LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

    def __init__(
        self,
        base_url: str,
        http_client: httpx.Client | None = None,
        *,
        offline_mode: bool = True,
        timeout_s: float = 8.0,
    ) -> None:
        parsed = urlparse(base_url)
        if offline_mode and parsed.hostname not in self._LOCAL_HOSTS:
            raise ValueError(
                "offline_mode only permits localhost or loopback LLM endpoints"
            )

        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or httpx.Client(timeout=timeout_s)

    def create_plan(
        self, text: str, state_version: int
    ) -> tuple[ActionPlan, LlmMeasurement]:
        started_ns = time.perf_counter_ns()
        prompt_tokens = 0
        completion_tokens = 0
        repair_attempts = 0

        content, usage = self._request_plan(text=text, state_version=state_version)
        prompt_tokens += usage.get("prompt_tokens", 0)
        completion_tokens += usage.get("completion_tokens", 0)

        try:
            plan = ActionPlan.model_validate_json(_extract_json(content))
        except (ValidationError, ValueError):
            repair_attempts = 1
            repair_content, usage = self._request_repair(
                invalid_content=content, state_version=state_version
            )
            prompt_tokens += usage.get("prompt_tokens", 0)
            completion_tokens += usage.get("completion_tokens", 0)
            try:
                plan = ActionPlan.model_validate_json(_extract_json(repair_content))
            except (ValidationError, ValueError) as exc:
                raise PlanGenerationError(
                    raw_output=content,
                    repair_output=repair_content,
                    total_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    validation_error=exc,
                ) from exc

        measurement = LlmMeasurement(
            total_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            repair_attempts=repair_attempts,
        )
        return plan, measurement

    def create_grounded_answer(
        self, query: str, evidence: Sequence[Evidence]
    ) -> tuple[GroundedAnswer, LlmMeasurement]:
        if not evidence:
            raise ValueError("grounded answer requires at least one evidence item")
        started_ns = time.perf_counter_ns()
        prompt_tokens = 0
        completion_tokens = 0
        repair_attempts = 0
        content, usage = self._request_grounded_answer(query, evidence)
        prompt_tokens += usage.get("prompt_tokens", 0)
        completion_tokens += usage.get("completion_tokens", 0)
        try:
            answer = GroundedAnswer.model_validate_json(_extract_json(content))
        except (ValidationError, ValueError):
            repair_attempts = 1
            repair_content, usage = self._request_grounded_repair(content, evidence)
            prompt_tokens += usage.get("prompt_tokens", 0)
            completion_tokens += usage.get("completion_tokens", 0)
            try:
                answer = GroundedAnswer.model_validate_json(
                    _extract_json(repair_content)
                )
            except (ValidationError, ValueError) as exc:
                raise PlanGenerationError(
                    raw_output=content,
                    repair_output=repair_content,
                    total_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    validation_error=exc,
                ) from exc
        return answer, LlmMeasurement(
            total_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            repair_attempts=repair_attempts,
        )

    def _post(self, payload: dict[str, Any]) -> tuple[str, dict[str, int]]:
        response = self.http_client.post(
            f"{self.base_url}/chat/completions", json=payload
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("LLM response content must be a string")
        usage = body.get("usage", {})
        return content, {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
        }

    def _request_plan(
        self, *, text: str, state_version: int
    ) -> tuple[str, dict[str, int]]:
        return self._post(
            {
                "model": "local-model",
                "temperature": 0,
                "max_tokens": 192,
                "response_format": {
                    "type": "json_object",
                    "schema": ACTION_PLAN_JSON_SCHEMA,
                },
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_PLAN_CONTRACT,
                    },
                    {
                        "role": "user",
                        "content": (
                            f"vehicle_state_version={state_version}\n"
                            f"Vietnamese request: {text}"
                        ),
                    },
                ],
            }
        )

    def _request_repair(
        self, *, invalid_content: str, state_version: int
    ) -> tuple[str, dict[str, int]]:
        return self._post(
            {
                "model": "local-model",
                "temperature": 0,
                "max_tokens": 192,
                "response_format": {
                    "type": "json_object",
                    "schema": ACTION_PLAN_JSON_SCHEMA,
                },
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Repair the invalid output. Return only a valid JSON "
                            "ActionPlan matching this schema: "
                            + json.dumps(
                                ACTION_PLAN_JSON_SCHEMA,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"vehicle_state_version={state_version}\n"
                            f"Invalid output: {invalid_content}"
                        ),
                    },
                ],
            }
        )

    def _request_grounded_answer(
        self, query: str, evidence: Sequence[Evidence]
    ) -> tuple[str, dict[str, int]]:
        evidence_payload = [
            {
                "evidence_id": item.chunk_id,
                "section": item.section,
                "page": item.page,
                "text": item.text,
            }
            for item in evidence
        ]
        return self._post(
            {
                "model": "local-model",
                "temperature": 0,
                "max_tokens": 256,
                "response_format": {
                    "type": "json_object",
                    "schema": GROUNDED_ANSWER_JSON_SCHEMA,
                },
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Answer the Vietnamese question using only the supplied "
                            "evidence. Return one JSON object matching the schema. "
                            "Every claim must copy evidence_id, section and page "
                            "exactly from the evidence. Do not add unsupported facts."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"query": query, "evidence": evidence_payload},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                ],
            }
        )

    def _request_grounded_repair(
        self, invalid_content: str, evidence: Sequence[Evidence]
    ) -> tuple[str, dict[str, int]]:
        allowed = [
            {
                "evidence_id": item.chunk_id,
                "section": item.section,
                "page": item.page,
            }
            for item in evidence
        ]
        return self._post(
            {
                "model": "local-model",
                "temperature": 0,
                "max_tokens": 256,
                "response_format": {
                    "type": "json_object",
                    "schema": GROUNDED_ANSWER_JSON_SCHEMA,
                },
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Repair the grounded-answer JSON. Return only JSON "
                            "matching the supplied schema and use only allowed citations."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "invalid_output": invalid_content,
                                "allowed_citations": allowed,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                ],
            }
        )


def _extract_json(content: str) -> str:
    stripped = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.I)
    if fenced:
        return fenced.group(1).strip()
    return stripped

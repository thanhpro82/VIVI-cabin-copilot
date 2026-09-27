import json

import httpx
import pytest

from offline_poc.llm import LlamaClient, PlanGenerationError
from offline_poc.rag import Evidence


VALID_PLAN = (
    '{"plan_id":"p1","vehicle_state_version":1,'
    '"requires_approval":true,"steps":['
    '{"step_id":"s1","tool":"set_hvac_temperature",'
    '"args":{"temperature_c":24},"safety_level":"S2",'
    '"depends_on":[]}]}'
)

VALID_GROUNDED_ANSWER = (
    '{"answer_text":"Đèn TPMS báo áp suất lốp thấp.","claims":['
    '{"text":"Đèn TPMS báo áp suất lốp thấp.",'
    '"evidence_id":"manual:TPMS:p112:0","section":"TPMS","page":112}]}'
)


def _response(request: httpx.Request, content: str) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 15},
        },
    )


def test_chat_json_validates_action_plan() -> None:
    transport = httpx.MockTransport(
        lambda request: _response(request, VALID_PLAN)
    )
    http_client = httpx.Client(transport=transport)
    client = LlamaClient("http://127.0.0.1:8080/v1", http_client=http_client)

    plan, measurement = client.create_plan(
        "Đặt điều hòa 24 độ",
        state_version=1,
    )

    assert plan.steps[0].tool == "set_hvac_temperature"
    assert plan.steps[0].args == {"temperature_c": 24}
    assert measurement.prompt_tokens == 20
    assert measurement.completion_tokens == 15
    assert measurement.repair_attempts == 0
    assert measurement.total_ms >= 0


def test_invalid_json_is_repaired_once() -> None:
    responses = iter(["not-json", VALID_PLAN])
    transport = httpx.MockTransport(
        lambda request: _response(request, next(responses))
    )
    http_client = httpx.Client(transport=transport)
    client = LlamaClient("http://localhost:8080/v1", http_client=http_client)

    _, measurement = client.create_plan("Đặt 24 độ", state_version=1)

    assert measurement.repair_attempts == 1


def test_offline_client_rejects_non_local_endpoint() -> None:
    with pytest.raises(ValueError, match="localhost"):
        LlamaClient("https://example.com/v1", offline_mode=True)


def test_request_includes_action_plan_json_schema() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": VALID_PLAN}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 15},
            },
        )

    client = LlamaClient(
        "http://localhost:8080/v1",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.create_plan("Đặt điều hòa 24 độ", state_version=1)

    response_format = captured["response_format"]
    assert response_format["type"] == "json_object"
    assert set(response_format["schema"]["required"]) == {
        "plan_id",
        "vehicle_state_version",
        "requires_approval",
        "steps",
    }
    assert response_format["schema"]["properties"]["steps"]["minItems"] == 1


def test_valid_json_inside_markdown_fence_does_not_trigger_repair() -> None:
    response = httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": f"```json\n{VALID_PLAN}\n```"}}
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 15},
        },
    )
    transport = httpx.MockTransport(lambda request: response)
    client = LlamaClient(
        "http://localhost:8080/v1", httpx.Client(transport=transport)
    )

    plan, measurement = client.create_plan("Đặt điều hòa 24 độ", state_version=1)

    assert plan.plan_id == "p1"
    assert measurement.repair_attempts == 0


def test_two_invalid_outputs_raise_evidence_rich_error() -> None:
    responses = iter(["not-json", "still-not-json"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": next(responses)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    client = LlamaClient(
        "http://localhost:8080/v1",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(PlanGenerationError) as captured:
        client.create_plan("lệnh lỗi", state_version=1)

    assert captured.value.raw_output == "not-json"
    assert captured.value.repair_output == "still-not-json"
    assert captured.value.repair_attempts == 1
    assert captured.value.prompt_tokens == 20
    assert captured.value.completion_tokens == 10
    assert captured.value.total_ms >= 0


def test_grounded_answer_request_carries_only_supplied_evidence() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _response(request, VALID_GROUNDED_ANSWER)

    client = LlamaClient(
        "http://localhost:8080/v1",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    evidence = [
        Evidence(
            section="TPMS",
            page=112,
            text="Đèn TPMS báo áp suất lốp thấp.",
            chunk_id="manual:TPMS:p112:0",
        )
    ]

    answer, measurement = client.create_grounded_answer("Đèn này là gì?", evidence)

    assert answer.claims[0].evidence_id == "manual:TPMS:p112:0"
    assert answer.claims[0].page == 112
    assert measurement.repair_attempts == 0
    request_text = json.dumps(captured, ensure_ascii=False)
    assert "manual:TPMS:p112:0" in request_text
    assert "TPMS" in request_text
    assert "112" in request_text
    assert captured["response_format"]["schema"]["required"] == [
        "answer_text",
        "claims",
    ]


def test_invalid_grounded_json_is_repaired_once() -> None:
    responses = iter(["not-json", VALID_GROUNDED_ANSWER])
    client = LlamaClient(
        "http://localhost:8080/v1",
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: _response(request, next(responses))
            )
        ),
    )
    evidence = [
        Evidence(
            section="TPMS",
            page=112,
            text="Đèn TPMS báo áp suất lốp thấp.",
            chunk_id="manual:TPMS:p112:0",
        )
    ]

    _, measurement = client.create_grounded_answer("Đèn này là gì?", evidence)

    assert measurement.repair_attempts == 1

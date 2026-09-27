"""Hợp đồng union `plan | chitchat` — một lần gọi, hai hình dạng hợp lệ, không có thứ ba."""

import pytest

from src.agents.contracts import CandidateActionPlan
from src.agents.slm import CHITCHAT_MAX_CHARS, SlmSchemaError, parse_slm_output

PLAN_RAW = (
    '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,'
    '"tool":"set_hvac_temperature","args":{"temperature_c":24},"depends_on":[]}]}'
)


def test_plan_output_becomes_a_candidate_plan():
    out = parse_slm_output(PLAN_RAW)
    assert isinstance(out, CandidateActionPlan)
    assert out.steps[0].tool == "set_hvac_temperature"


def test_chitchat_output_becomes_a_stripped_reply():
    out = parse_slm_output('{"kind":"chitchat","reply":"  Chào bạn!  "}')
    assert out == "Chào bạn!"


def test_a_third_shape_is_rejected_not_guessed():
    """Grammar chặn hình dạng thứ ba lúc sinh; parse phải chặn lần nữa lúc đọc —
    hai lớp độc lập, vì stub/test và server cũ không đi qua grammar."""
    with pytest.raises(SlmSchemaError):
        parse_slm_output('{"kind":"help","text":"gì đó"}')


def test_plan_with_planner_supplied_safety_level_is_rejected():
    """Bất biến ADR-006 giữ nguyên qua đường union: model không được gán safety."""
    raw = PLAN_RAW.replace('"depends_on":[]', '"depends_on":[],"safety_level":"S1"')
    with pytest.raises(SlmSchemaError):
        parse_slm_output(raw)


def test_empty_reply_is_a_schema_error_not_a_silent_blank():
    with pytest.raises(SlmSchemaError):
        parse_slm_output('{"kind":"chitchat","reply":"   "}')


def test_overlong_reply_is_truncated_to_the_measured_cap():
    reply = "a" * 500
    out = parse_slm_output(f'{{"kind":"chitchat","reply":"{reply}"}}')
    assert len(out) == CHITCHAT_MAX_CHARS


def test_union_schema_and_prompt_match_the_measured_files():
    """Số đo SPIKE-003 chỉ có nghĩa cho đúng cấu hình được đo — nên phần nào của prompt
    còn nguyên thì phải bằng **từng ký tự** với bản spike.

    Cập nhật 27/08 (#269): prompt không còn khớp toàn bộ, và đó là **cố ý**. Bảng tool
    trước đây là chuỗi chép tay kê 9 tool trong khi registry có 16 — nó trôi khỏi
    registry và không có gì phát hiện ra, nên nay nó được **sinh ra** từ bảng args của
    `validate_args`. Cái đổi là bảng tool; **bộ ví dụ few-shot không đổi một ký tự nào**,
    và đó chính là phần bậc B/C đo.

    Nên test này thu về đúng bất biến còn đứng vững:

    - `UNION_SCHEMA` khớp tuyệt đối — grammar không đổi, con số kind/tool vẫn áp được.
    - Bộ ví dụ khớp tuyệt đối.
    - Bảng tool thì **không** khớp file spike, và test khẳng định luôn điều đó để không
      ai lặng lẽ chép bảng cũ trở lại.

    Hệ quả phải nói ra: cặp số `kind 0,906 / tool 0,828` đo trên bảng tool CŨ. Trích nó
    cho prompt hôm nay là sai; đo lại là việc của issue #269.
    """
    import json
    from pathlib import Path

    from src.agents.slm import _VI_DU_FEW_SHOT, SLM_UNION_PROMPT, UNION_SCHEMA

    root = Path(__file__).resolve().parents[2]
    assert UNION_SCHEMA == json.loads((root / "scripts" / "spike3_schema.json").read_text(encoding="utf-8"))

    spike = (root / "scripts" / "spike3_prompt.txt").read_text(encoding="utf-8")
    moc = "Không giải thích. Không nói rằng đã thực hiện hành động nào.\n\n"
    assert _VI_DU_FEW_SHOT == spike[spike.index(moc) + len(moc) :], "bộ ví dụ đã đo bị đổi"
    assert SLM_UNION_PROMPT.endswith(_VI_DU_FEW_SHOT)
    assert SLM_UNION_PROMPT != spike, "bảng tool chép tay đã quay lại — xem #269"


# --------------------------------------------------------------------------
# Luồng graph: chitchat + reset giữa các lượt
# --------------------------------------------------------------------------

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from src.agents.graph import build_graph  # noqa: E402
from src.services.vehicle_gateway import InProcessVehicleGateway  # noqa: E402

CONFIG = {"configurable": {"thread_id": "ses-chit"}}


class _ChitchatPlanner:
    def propose(self, normalized_text: str, snapshot: dict) -> str:
        return '{"kind":"chitchat","reply":"Chào bạn, tôi là VIVI!"}'


async def test_chitchat_reply_does_not_leak_into_the_next_turn():
    """Một phiên dùng chung thread checkpointer; lượt sau kế thừa state lượt trước.
    Không reset thì lệnh 'Bật điều hòa' của lượt 2 mang theo reply của lượt 1."""
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_ChitchatPlanner(), checkpointer=InMemorySaver())

    first = await graph.ainvoke(
        {"query": "Hôm nay trời đẹp nhỉ", "session_id": "ses-chit", "vehicle_id": "veh-1"}, config=CONFIG
    )
    assert first["chitchat_reply"] == "Chào bạn, tôi là VIVI!"

    second = await graph.ainvoke(
        {"query": "Bật điều hòa", "session_id": "ses-chit", "vehicle_id": "veh-1"}, config=CONFIG
    )
    assert second["chitchat_reply"] == ""
    assert second["outcome"] == "completed"  # lệnh luật bắt được, chạy bình thường


async def test_social_utterance_flows_to_a_natural_reply_not_clarify():
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_ChitchatPlanner(), checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        {"query": "Cảm ơn nhé", "session_id": "ses-chit", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-social"}},
    )

    assert result["outcome"] == "chitchat"
    assert result["response_text"] == "Chào bạn, tôi là VIVI!"
    assert gateway.command_count == 0  # không chạm executor — tính chất kiến trúc


class _PlanPlanner:
    def propose(self, normalized_text: str, snapshot: dict) -> str:
        return (
            '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1","ordinal":0,'
            '"tool":"set_hvac_temperature","args":{"temperature_c":22},"depends_on":[]}]}'
        )


async def test_plan_output_still_goes_through_the_safety_gate():
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_PlanPlanner(), checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        {"query": "làm mát giùm cái", "session_id": "ses-plan", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-plan"}},
    )

    # Issue #144 đổi đúng dòng này. Bản trước ghi "S1 → chạy thẳng, qua
    # validate/safety/execute như lệnh luật bắt được" — và chính chữ "như lệnh luật bắt
    # được" là chỗ sai: lệnh luật có **độ tin cậy cấu trúc** (một luật đã khớp), plan do
    # SLM đề xuất thì không. Đối xử giống nhau nghĩa là cho SLM mượn niềm tin của router.
    #
    # Bước vẫn S1 — hành động thật sự không nguy hiểm. Thứ đổi là phải hỏi trước.
    assert result["outcome"] == "approval_required"
    assert result["route_source"] == "slm"
    assert all(step.safety_level == "S1" for step in result["action_plan"].steps)
    assert gateway.command_count == 0


def test_qwen_planner_sends_the_measured_config(monkeypatch):
    """Prompt utterance-only + grammar + cache — đúng cấu hình đã đo SPIKE-003.

    Snapshot cố ý KHÔNG vào prompt: (1) cấu hình được đo không có nó, số chỉ có nghĩa
    cho cấu hình đó; (2) snapshot đổi mỗi lượt → prefix đổi → prompt cache trượt, mất
    luôn kinh tế 140 ms/call. Chữ ký propose giữ snapshot vì Protocol, impl bỏ qua.
    """
    import httpx

    from src.agents.slm import SLM_UNION_PROMPT, UNION_SCHEMA, QwenPlanner

    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured.update(url=url, body=json)

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"content": '{"kind":"chitchat","reply":"ok"}'}

        return _R()

    monkeypatch.setattr(httpx, "post", _fake_post)
    QwenPlanner("http://127.0.0.1:8093", "m").propose("Cảm ơn nhé", {"state_version": 9})

    assert captured["body"]["prompt"] == SLM_UNION_PROMPT + "Cảm ơn nhé\nJSON:"
    assert captured["body"]["json_schema"] == UNION_SCHEMA
    assert captured["body"]["cache_prompt"] is True
    assert captured["body"]["n_predict"] == 160
    assert "Trạng thái xe" not in captured["body"]["prompt"]


class _DeadServerPlanner:
    """Mô phỏng đúng ca bắt được khi kiểm tay: llama-server không chạy."""

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        import httpx

        raise httpx.ConnectError("[WinError 10061] connection refused")


async def test_a_dead_slm_server_degrades_to_clarify_not_a_500():
    """Điều kiện fallback của ADR-016: SLM hỏng thì rơi về hành vi cũ, không phải sự cố.

    Bắt được bằng kiểm tay model thật: httpx.ConnectError KHÔNG phải OSError, nên
    `except (SlmSchemaError, OSError)` để lọt và lượt nổ 500 xuyên qua graph.
    """
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_DeadServerPlanner(), checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        {"query": "Cảm ơn nhé", "session_id": "ses-dead", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "ses-dead"}},
    )

    assert result["outcome"] == "clarify"
    assert gateway.command_count == 0


async def test_a_dead_slm_server_is_logged_not_silent(caplog):
    """Người vận hành phải phân biệt được "SLM sập" với "model không hiểu câu".

    Nuốt lỗi hạ tầng im lặng thì mọi lượt fallback thành clarify mà không dấu vết —
    server chết cả buổi cũng không ai biết vì hành vi bề mặt giống hệt câu khó.
    """
    import logging

    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_DeadServerPlanner(), checkpointer=InMemorySaver())

    with caplog.at_level(logging.WARNING, logger="src.agents.graph"):
        result = await graph.ainvoke(
            {"query": "Cảm ơn nhé", "session_id": "ses-log", "vehicle_id": "veh-1"},
            config={"configurable": {"thread_id": "ses-log"}},
        )

    assert result["outcome"] == "clarify"
    infra = [r for r in caplog.records if "hạ tầng" in r.getMessage()]
    assert len(infra) == 2  # cả hai attempt đều được ghi, kèm số thứ tự

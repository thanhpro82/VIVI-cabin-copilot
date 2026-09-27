from langgraph.types import Command

from offline_poc.graph import build_graph
from offline_poc.vehicle_mock import VehicleMock


def test_s2_plan_interrupts_before_execution() -> None:
    vehicle = VehicleMock.initial()
    graph = build_graph(vehicle)
    config = {"configurable": {"thread_id": "hitl-test-1"}}

    result = graph.invoke(
        {"input_text": "Đặt điều hòa 24 độ", "vehicle_state_version": 1},
        config=config,
    )

    assert "__interrupt__" in result
    assert vehicle.command_count == 0


def test_resume_executes_exactly_once() -> None:
    vehicle = VehicleMock.initial()
    graph = build_graph(vehicle)
    config = {"configurable": {"thread_id": "hitl-test-2"}}
    graph.invoke(
        {"input_text": "Đặt điều hòa 24 độ", "vehicle_state_version": 1},
        config=config,
    )

    result = graph.invoke(
        Command(resume={"decision": "approve", "state_version": 1}),
        config=config,
    )

    assert vehicle.command_count == 1
    assert vehicle.state["hvac"]["temperature_c"] == 24
    assert result["outcome"] == "completed"


def test_reject_and_stale_approval_do_not_execute() -> None:
    vehicle = VehicleMock.initial()
    graph = build_graph(vehicle)

    reject_config = {"configurable": {"thread_id": "hitl-reject"}}
    graph.invoke(
        {"input_text": "Đặt điều hòa 24 độ", "vehicle_state_version": 1},
        config=reject_config,
    )
    rejected = graph.invoke(
        Command(resume={"decision": "reject", "state_version": 1}),
        config=reject_config,
    )

    stale_config = {"configurable": {"thread_id": "hitl-stale"}}
    graph.invoke(
        {"input_text": "Đặt điều hòa 24 độ", "vehicle_state_version": 1},
        config=stale_config,
    )
    stale = graph.invoke(
        Command(resume={"decision": "approve", "state_version": 0}),
        config=stale_config,
    )

    assert rejected["outcome"] == "rejected_by_user"
    assert stale["outcome"] == "stale_state"
    assert vehicle.command_count == 0


def test_timeout_decision_is_reported_as_expired_without_execution() -> None:
    vehicle = VehicleMock.initial()
    graph = build_graph(vehicle)
    config = {"configurable": {"thread_id": "hitl-timeout"}}
    graph.invoke(
        {"input_text": "Đặt điều hòa 24 độ", "vehicle_state_version": 1},
        config=config,
    )

    result = graph.invoke(
        Command(
            resume={
                "decision": "timeout",
                "state_version": 1,
                "approval_age_seconds": 31,
            }
        ),
        config=config,
    )

    assert result["outcome"] == "approval_expired"
    assert vehicle.command_count == 0


def test_duplicate_command_id_returns_original_result() -> None:
    vehicle = VehicleMock.initial()

    first = vehicle.execute(
        "plan-1:step-1", 1, "set_hvac_temperature", {"temperature_c": 24}
    )
    second = vehicle.execute(
        "plan-1:step-1", 1, "set_hvac_temperature", {"temperature_c": 24}
    )

    assert second == first
    assert vehicle.command_count == 1


def test_open_door_is_blocked_while_vehicle_is_moving() -> None:
    vehicle = VehicleMock.initial(speed_kph=30, gear="D", state_version=7)

    result = vehicle.execute(
        "plan-door:step-1",
        7,
        "set_door_state",
        {"door": "front_left", "state": "open"},
    )

    assert result.status == "rejected"
    assert result.error_code == "unsafe_vehicle_state"
    assert vehicle.command_count == 0
    assert vehicle.state["doors"]["front_left"] == "closed"

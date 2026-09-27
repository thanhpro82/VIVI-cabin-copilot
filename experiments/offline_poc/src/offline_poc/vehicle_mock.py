from __future__ import annotations

from copy import deepcopy
import time
from typing import Any

from offline_poc.contracts import ToolResult


class VehicleMock:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = deepcopy(state)
        self.command_count = 0
        self._results: dict[str, ToolResult] = {}

    @classmethod
    def initial(
        cls,
        *,
        speed_kph: int = 0,
        gear: str = "P",
        state_version: int = 1,
    ) -> "VehicleMock":
        return cls(
            {
                "state_version": state_version,
                "speed_kph": speed_kph,
                "gear": gear,
                "hvac": {"power": True, "temperature_c": 27},
                "seat_heating": {"driver": 0, "passenger": 0},
                "windows": {"front_left": 0, "front_right": 0},
                "doors": {"front_left": "closed", "front_right": "closed"},
                "media": {"status": "paused", "volume": 25},
                "navigation": {"status": "idle", "destination_id": None},
            }
        )

    def execute(
        self,
        command_id: str,
        expected_state_version: int,
        tool: str,
        args: dict[str, Any],
    ) -> ToolResult:
        cached = self._results.get(command_id)
        if cached is not None:
            return cached

        started_ns = time.perf_counter_ns()
        before = deepcopy(self.state)

        if expected_state_version != self.state["state_version"]:
            return self._remember(
                command_id,
                before,
                status="rejected",
                error_code="stale_state",
                started_ns=started_ns,
            )

        if self._unsafe_door_open(tool, args):
            return self._remember(
                command_id,
                before,
                status="rejected",
                error_code="unsafe_vehicle_state",
                started_ns=started_ns,
            )

        try:
            changed = self._apply(tool, args)
        except (KeyError, TypeError, ValueError) as exc:
            return self._remember(
                command_id,
                before,
                status="failed",
                error_code=f"invalid_arguments:{exc}",
                started_ns=started_ns,
            )

        if changed:
            self.state["state_version"] += 1
        self.command_count += 1
        return self._remember(
            command_id,
            before,
            status="completed",
            error_code=None,
            started_ns=started_ns,
        )

    def _remember(
        self,
        command_id: str,
        before: dict[str, Any],
        *,
        status: str,
        error_code: str | None,
        started_ns: int,
    ) -> ToolResult:
        step_id = command_id.rsplit(":", 1)[-1]
        result = ToolResult(
            command_id=command_id,
            step_id=step_id,
            status=status,
            before=before,
            after=deepcopy(self.state),
            error_code=error_code,
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )
        self._results[command_id] = result
        return result

    def _unsafe_door_open(self, tool: str, args: dict[str, Any]) -> bool:
        opening = tool in {"set_door_state", "open_door"} and (
            tool == "open_door" or args.get("state") == "open"
        )
        return bool(
            opening
            and (self.state["speed_kph"] != 0 or self.state["gear"] != "P")
        )

    def _apply(self, tool: str, args: dict[str, Any]) -> bool:
        if tool == "set_hvac_temperature":
            temperature = int(args["temperature_c"])
            if not 16 <= temperature <= 30:
                raise ValueError("temperature_c must be between 16 and 30")
            self.state["hvac"]["temperature_c"] = temperature
            return True

        if tool == "set_hvac_power":
            self.state["hvac"]["power"] = bool(args["enabled"])
            return True

        if tool == "set_seat_heating":
            seat = str(args["seat"])
            level = int(args["level"])
            if seat not in self.state["seat_heating"] or not 0 <= level <= 3:
                raise ValueError("invalid seat or level")
            self.state["seat_heating"][seat] = level
            return True

        if tool == "set_window_position":
            window = str(args["window"])
            percent = int(args["percent"])
            if window not in self.state["windows"] or not 0 <= percent <= 100:
                raise ValueError("invalid window or percent")
            self.state["windows"][window] = percent
            return True

        if tool in {"set_door_state", "open_door"}:
            door = str(args.get("door", "front_left"))
            state = "open" if tool == "open_door" else str(args["state"])
            if door not in self.state["doors"] or state not in {"open", "closed"}:
                raise ValueError("invalid door or state")
            self.state["doors"][door] = state
            return True

        if tool == "media_control":
            action = str(args["action"])
            if action in {"play", "pause"}:
                self.state["media"]["status"] = (
                    "playing" if action == "play" else "paused"
                )
            elif action == "set_volume":
                volume = int(args["value"])
                if not 0 <= volume <= 100:
                    raise ValueError("volume must be between 0 and 100")
                self.state["media"]["volume"] = volume
            else:
                raise ValueError("unsupported media action")
            return True

        if tool == "set_navigation":
            self.state["navigation"] = {
                "status": "active",
                "destination_id": str(args["destination_id"]),
            }
            return True

        if tool == "search_nearby":
            if not args.get("category"):
                raise ValueError("category is required")
            return False

        raise ValueError(f"unsupported tool {tool}")

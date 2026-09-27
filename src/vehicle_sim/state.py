"""Máy trạng thái xe ảo — thuần, không biết gì về MQTT.

Port từ `experiments/offline_poc/src/offline_poc/vehicle_mock.py`, giữ nguyên
ba invariant đã đúng ở đó:

- idempotency theo `command_id`: nhận lại cùng lệnh trả kết quả cũ, không tạo
  transition thứ hai (điều làm QoS 1 an toàn)
- optimistic concurrency theo `expected_state_version` -> `stale_state`
- chặn thao tác nguy hiểm khi xe đang chuyển động -> `unsafe_vehicle_state`

Khác bản gốc:

- 4 cửa/4 cửa sổ thay vì 2, thêm domain `seat`, `motion`, `media.track`
- `media_control` đọc `args["volume"]` (bản gốc đọc `args["value"]`, lệch
  registry ở docs/agent_spec.md)
- `set_navigation` có thêm `operation="cancel"`
- bỏ `search_nearby` — đó là tool S0, không đi qua broker
- chặn theo `requires_stationary` cho cả `set_door_state` lẫn
  `set_seat_position`: agent_spec.md xếp **cả tool** xuống S3 khi xe đang
  chạy, không phân biệt mở hay đóng. Bản gốc chỉ chặn thao tác mở cửa.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.bounded_cache import BoundedCache
from src.fixtures import load_media_fixture, ten_track_theo_id
from src.models.vehicle import (
    CommandEvent,
    Domain,
    DoorsState,
    HvacState,
    LightsState,
    MediaState,
    MotionState,
    NavigationState,
    SeatState,
    SingleSeatState,
    TrunkState,
    VehicleCommand,
    VehicleState,
    WindowsState,
    utc_now,
)
from src.services.tool_registry import (
    InvalidArgumentsError,
    ToolNotAllowedError,
    get_spec,
    validate_args,
)


def default_playlist() -> tuple[str, ...]:
    """Tên bài để `media_control` next/previous có gì để xoay.

    Không thuộc vehicle state — chỉ là nội thất của simulator. Đọc từ
    `src/fixtures/media.json`, **không** hard-code ở đây: IVI đọc cùng fixture ấy
    để biết phát file nào và hiện ảnh bìa nào, và tên bài chính là khoá nối hai
    bên. Trước bản này đó là hai danh sách chép tay không khớp nhau một tên nào,
    nên ở real mode next/previous đổi được chữ trên màn hình trong khi loa phát
    mãi một file (issue #173).

    Là hàm chứ không phải hằng số module: hằng số đọc file ngay lúc import, biến
    một fixture hỏng thành lỗi import làm chết process trước khi log kịp chạy.
    """
    return tuple(str(item["name"]) for item in load_media_fixture())


@dataclass(frozen=True)
class ExecutionOutcome:
    event: CommandEvent
    #: Domain đã đổi giá trị — runtime chỉ publish đúng những domain này.
    changed: tuple[Domain, ...]
    #: True khi kết quả lấy từ cache idempotency, không phải vừa thực thi.
    replayed: bool = False


def _neutral_seat() -> SingleSeatState:
    # Phải là instance mới mỗi lần: pydantic không copy model lồng nhau, dùng
    # chung một object thì chỉnh ghế trái sẽ đổi luôn ghế phải.
    return SingleSeatState(heating=0, fore_aft=50, recline=50, height=50)


def initial_state(vehicle_id: str) -> VehicleState:
    """Trạng thái khởi tạo: xe đỗ, đã bật điện, mọi thứ đóng."""
    return VehicleState(
        vehicle_id=vehicle_id,
        state_version=1,
        observed_at=utc_now(),
        motion=MotionState(speed_kph=0, gear="P", ignition="ON"),
        hvac=HvacState(power=True, temperature_c=27, fan_level=3),
        windows=WindowsState(front_left=0, front_right=0, rear_left=0, rear_right=0),
        doors=DoorsState(
            front_left="closed",
            front_right="closed",
            rear_left="closed",
            rear_right="closed",
        ),
        media=MediaState(status="paused", volume=35, track=None),
        navigation=NavigationState(status="idle", destination_id=None),
        seat=SeatState(front_left=_neutral_seat(), front_right=_neutral_seat()),
        # `auto` là mặc định đúng, không phải mặc định tiện: theo UNECE R48 thì trên
        # xe có DRL, chế độ tự động là chế độ xe xuất xưởng đã ở đó.
        lights=LightsState(headlight="auto", interior=False),
        trunk=TrunkState(position="closed"),
    )


class VehicleSimulator:
    def __init__(self, vehicle_id: str, state: VehicleState | None = None) -> None:
        self.vehicle_id = vehicle_id
        # deep=True là bắt buộc, không phải phòng xa: pydantic KHÔNG copy model
        # lồng nhau. Giữ `state` theo tham chiếu thì hai simulator khởi tạo từ
        # cùng một object sẽ dùng chung nó — sửa cái này đổi luôn cái kia.
        self.state = state.model_copy(deep=True) if state is not None else initial_state(vehicle_id)
        self._results: BoundedCache[str, ExecutionOutcome] = BoundedCache()
        self._playlist = list(default_playlist())
        self.command_count = 0

    # -- công khai ---------------------------------------------------------

    def execute(self, command: VehicleCommand) -> ExecutionOutcome:
        cached = self._results.get(command.command_id)
        if cached is not None:
            # Duplicate delivery của QoS 1. Trả nguyên kết quả cũ, tuyệt đối
            # không tạo transition thứ hai.
            #
            # Cache có trần (BoundedCache). Nếu một command_id bị đẩy ra rồi
            # quay lại, lệnh sẽ được thực thi lại — nhưng lúc đó
            # expected_state_version gần như chắc chắn đã cũ nên bị chặn bằng
            # `stale_state`. Tức là fail an toàn, không tạo transition kép.
            return ExecutionOutcome(cached.event, cached.changed, replayed=True)

        started_ns = time.perf_counter_ns()
        domain = self._domain_of(command.tool)

        try:
            spec = get_spec(command.tool)
            if spec.domain is None:
                raise ToolNotAllowedError(f"tool {command.tool!r} là S0, không nhận qua MQTT")
            args = validate_args(command.tool, command.args)
        except ToolNotAllowedError as exc:
            return self._reject(command, None, "tool_not_allowed", str(exc), started_ns)
        except InvalidArgumentsError as exc:
            return self._reject(command, domain, "invalid_arguments", str(exc), started_ns)

        if command.expected_state_version != self.state.state_version:
            return self._reject(command, spec.domain, "stale_state", None, started_ns)

        if spec.requires_stationary and self._is_moving():
            return self._reject(command, spec.domain, "unsafe_vehicle_state", None, started_ns)

        before = self._domain_dict(spec.domain)
        try:
            changed = self._apply(command.tool, args)
        except InvalidArgumentsError as exc:
            return self._reject(command, spec.domain, "invalid_arguments", str(exc), started_ns)
        except Exception as exc:  # noqa: BLE001 — không để simulator chết vì một lệnh
            return self._reject(command, spec.domain, "internal_error", str(exc), started_ns)

        if changed:
            self.state.state_version += 1
        self.state.observed_at = utc_now()
        self.command_count += 1

        outcome = ExecutionOutcome(
            event=self._event(
                command,
                phase="completed",
                status="completed",
                before=before,
                after=self._domain_dict(spec.domain),
                error_code=None,
                started_ns=started_ns,
            ),
            changed=(spec.domain,) if changed else (),
        )
        self._results.set(command.command_id, outcome)
        return outcome

    def reject_command(self, command: VehicleCommand, error_code: str, detail: str | None = None) -> ExecutionOutcome:
        """Từ chối một lệnh từ bên ngoài máy trạng thái.

        Dùng khi runtime phát hiện lỗi định tuyến — ví dụ lệnh tới sai topic
        domain — mà bản thân tool lại hợp lệ nên `execute` sẽ không chặn.
        """
        return self._reject(command, self._domain_of(command.tool), error_code, detail, time.perf_counter_ns())

    def snapshot(self) -> VehicleState:
        return self.state.model_copy(deep=True)

    # -- nội bộ ------------------------------------------------------------

    def _is_moving(self) -> bool:
        return self.state.motion.speed_kph != 0 or self.state.motion.gear != "P"

    def _domain_of(self, tool: str) -> Domain | None:
        spec = None
        try:
            spec = get_spec(tool)
        except ToolNotAllowedError:
            return None
        return spec.domain

    def _domain_dict(self, domain: Domain | None) -> dict[str, Any]:
        """Ảnh chụp domain kèm state_version, đúng dạng mẫu ở docs/mqtt_spec.md."""
        if domain is None:
            return {"state_version": self.state.state_version}
        payload = self.state.domain(domain).model_dump()
        payload["state_version"] = self.state.state_version
        return payload

    def _reject(
        self,
        command: VehicleCommand,
        domain: Domain | None,
        error_code: str,
        detail: str | None,
        started_ns: int,
    ) -> ExecutionOutcome:
        # Lệnh bị từ chối không đổi gì, nên before và after bằng nhau.
        frozen = self._domain_dict(domain)
        if detail:
            frozen = {**frozen, "detail": detail}
        outcome = ExecutionOutcome(
            event=self._event(
                command,
                phase="rejected",
                status="rejected",
                before=frozen,
                after=frozen,
                error_code=error_code,  # type: ignore[arg-type]
                started_ns=started_ns,
            ),
            changed=(),
        )
        self._results.set(command.command_id, outcome)
        return outcome

    def _event(
        self,
        command: VehicleCommand,
        *,
        phase: str,
        status: str,
        before: dict[str, Any],
        after: dict[str, Any],
        error_code: str | None,
        started_ns: int,
    ) -> CommandEvent:
        return CommandEvent(
            event_id=f"evt_{uuid.uuid4().hex[:20]}",
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            plan_id=command.plan_id,
            step_id=command.step_id,
            vehicle_id=self.vehicle_id,
            approval_id=command.approval_id,
            execution_group_id=command.execution_group_id,
            phase=phase,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            expected_state_version=command.expected_state_version,
            observed_state_version=self.state.state_version,
            before=before,
            after=after,
            error_code=error_code,  # type: ignore[arg-type]
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            emitted_at=utc_now(),
        )

    def _apply(self, tool: str, args: Any) -> bool:
        """Áp lệnh. Trả True nếu có thay đổi thật sự."""
        if tool == "set_hvac_temperature":
            return self._set(self.state.hvac, "temperature_c", float(args.temperature_c))

        if tool == "set_hvac_power":
            return self._set(self.state.hvac, "power", args.enabled)

        if tool == "set_hvac_fan_level":
            return self._set(self.state.hvac, "fan_level", args.level)

        if tool == "set_seat_heating":
            seat = getattr(self.state.seat, args.seat)
            return self._set(seat, "heating", args.level)

        if tool == "set_seat_position":
            seat = getattr(self.state.seat, args.seat)
            return self._set(seat, args.axis, args.value)

        if tool == "set_window_position":
            return self._set(self.state.windows, args.window, args.percent)

        if tool == "set_door_state":
            return self._set(self.state.doors, args.door, args.state)

        if tool == "set_trunk_state":
            return self._set(self.state.trunk, "position", args.state)

        if tool == "set_headlight_mode":
            return self._set(self.state.lights, "headlight", args.mode)

        if tool == "set_interior_light":
            return self._set(self.state.lights, "interior", args.enabled)

        if tool == "media_control":
            return self._apply_media(args)

        if tool == "set_navigation":
            return self._apply_navigation(args)

        raise ToolNotAllowedError(f"tool {tool!r} không có nhánh xử lý")

    def _apply_media(self, args: Any) -> bool:
        media = self.state.media
        if args.action == "play":
            changed = self._set(media, "status", "playing")
            if media.track is None and self._playlist:
                changed = self._set(media, "track", self._playlist[0]) or changed
            return changed
        if args.action == "pause":
            return self._set(media, "status", "paused")
        if args.action == "set_volume":
            return self._set(media, "volume", args.volume)
        if args.action in {"next", "previous"}:
            return self._step_track(forward=args.action == "next")
        if args.action == "play_track":
            # `_playlist` giữ **tên** bài (xem `_playlist`), còn lệnh mang `track_id`,
            # nên phải tra tên ở đây. `registry` đã chặn id lạ từ trước, nên `None` ở
            # đây nghĩa là fixture vừa đổi dưới chân một lệnh đang bay — báo lỗi chứ
            # không phát bừa bài đầu danh sách.
            ten = ten_track_theo_id(str(args.track_id))
            if ten is None:
                raise InvalidArgumentsError(f"track_id {args.track_id!r} không có trong playlist")
            changed = self._set(self.state.media, "track", ten)
            return self._set(self.state.media, "status", "playing") or changed
        raise InvalidArgumentsError(f"media action {args.action!r} chưa hỗ trợ")

    def _step_track(self, *, forward: bool) -> bool:
        if not self._playlist:
            return False
        try:
            index = self._playlist.index(self.state.media.track or "")
        except ValueError:
            index = -1 if forward else 0
        offset = 1 if forward else -1
        return self._set(self.state.media, "track", self._playlist[(index + offset) % len(self._playlist)])

    def _apply_navigation(self, args: Any) -> bool:
        nav = self.state.navigation
        if args.operation == "cancel":
            changed = self._set(nav, "status", "idle")
            return self._set(nav, "destination_id", None) or changed
        if args.destination_id is None:
            # **Nhánh này nay không tới được**, và giữ lại là có chủ ý.
            #
            # Trước #325, `SetNavigationArgs` nhận `destination_ref` — một tham chiếu tới
            # kết quả tìm POI ở bước trước — nên `operation=start` có thể tới đây mà
            # `destination_id` vẫn `None`, và chỗ này là nơi duy nhất bắt được. Tức lượt
            # chết **sau** khi đã qua validate, safety và có thể cả HITL.
            #
            # #325 bỏ `destination_ref` khỏi schema, nên `operation=start` giờ bắt buộc có
            # `destination_id` ngay từ `validate_args`. Guard này thành lớp cuối cùng cho
            # một đường không còn ai đi — rẻ, và nó là thứ chặn nếu schema bị nới lại.
            raise InvalidArgumentsError("set_navigation start phải có destination_id cụ thể")
        changed = self._set(nav, "status", "active")
        return self._set(nav, "destination_id", args.destination_id) or changed

    @staticmethod
    def _set(target: Any, field: str, value: Any) -> bool:
        if getattr(target, field) == value:
            return False
        setattr(target, field, value)
        return True

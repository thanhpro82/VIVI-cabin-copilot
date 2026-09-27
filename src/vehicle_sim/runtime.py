"""Vòng đời MQTT của xe ảo: subscribe lệnh, publish sự kiện/trạng thái/heartbeat.

QoS và retain của từng topic theo bảng ở docs/mqtt_spec.md:

- `commands/{domain}`  QoS 1, retain **false**
- `events/command`     QoS 1, retain false
- `state/{domain}`     QoS 1, retain **true**
- `state/snapshot`     QoS 1, retain **true**
- `health`             QoS 1, retain **true** (Birth + Last Will)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import ValidationError

from src import mqtt_topics
from src.models.sim_harness import SimMotionSet
from src.models.vehicle import (
    DOMAINS,
    Domain,
    DomainStateMessage,
    Health,
    VehicleCommand,
    VehicleStateSnapshot,
    utc_now,
)
from src.services.mqtt_client import MqttPort, Will
from src.services.tool_registry import ToolNotAllowedError, get_spec
from src.vehicle_sim.state import VehicleSimulator

logger = logging.getLogger(__name__)

SIMULATOR_VERSION = "1.0.0"


def will_for(vehicle_id: str) -> Will:
    """Last Will khai lúc CONNECT — broker publish khi simulator chết đột ngột."""
    return Will(
        topic=mqtt_topics.health(vehicle_id),
        payload=Health(
            vehicle_id=vehicle_id, online=False, reason="lwt"
        ).model_dump(mode="json", exclude_none=True),
        qos=1,
        retain=True,
    )


class SimulatorRuntime:
    def __init__(
        self,
        simulator: VehicleSimulator,
        mqtt: MqttPort,
        *,
        heartbeat_interval_s: float = 5.0,
        sim_control_enabled: bool = False,
    ) -> None:
        self.simulator = simulator
        self.mqtt = mqtt
        self.vehicle_id = simulator.vehicle_id
        self._heartbeat_interval_s = heartbeat_interval_s
        self._sim_control_enabled = sim_control_enabled
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.mqtt.subscribe(
            mqtt_topics.commands_filter(self.vehicle_id), self._on_command
        )
        if self._sim_control_enabled:
            # Kênh harness — ADR-024. Không subscribe khi cờ tắt: message gửi tới
            # một topic không ai nghe là hành vi đúng của "tắt nghĩa là không tồn
            # tại", và nó khác hẳn với nghe rồi lặng lẽ bỏ qua.
            await self.mqtt.subscribe(
                mqtt_topics.sim_motion_set(self.vehicle_id), self._on_sim_motion_set
            )
        # Birth trước, để subscriber biết xe sống ngay mà không phải chờ nhịp
        # heartbeat kế tiếp. Cặp Birth + LWT là pattern chuẩn của MQTT.
        await self._publish_health(online=True)
        await self._publish_snapshot()
        await self._publish_all_domains()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name=f"heartbeat-{self.vehicle_id}"
        )
        logger.info("Xe ảo %s sẵn sàng", self.vehicle_id)

    async def stop(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        # Shutdown có trật tự — phân biệt với LWT để chẩn đoán được nguyên nhân.
        await self._publish_health(online=False, reason="shutdown")

    # -- xử lý lệnh --------------------------------------------------------

    async def _on_command(self, topic: str, payload: dict[str, Any]) -> None:
        topic_domain = mqtt_topics.parse_command_domain(topic)
        if topic_domain is None:
            logger.warning("Bỏ qua lệnh trên topic sai hình dạng: %s", topic)
            return

        try:
            command = VehicleCommand.model_validate(payload)
        except ValidationError as exc:
            # Không có command_id tin cậy được thì không tương quan nổi; executor
            # sẽ timeout. Ghi log để còn lần ra.
            logger.warning("Lệnh sai schema trên %s: %s", topic, exc.error_count())
            return

        if command.vehicle_id != self.vehicle_id:
            logger.warning(
                "Bỏ qua lệnh gửi cho xe %s (xe này là %s)",
                command.vehicle_id,
                self.vehicle_id,
            )
            return

        if self._topic_matches_tool(command.tool, topic_domain):
            outcome = self.simulator.execute(command)
        else:
            # Registry là server-owned nên lệch topic/tool nghĩa là executor
            # hỏng. Từ chối thay vì âm thầm thực thi.
            logger.warning("Lệnh %r tới sai topic domain %r", command.tool, topic_domain)
            outcome = self.simulator.reject_command(
                command,
                "tool_not_allowed",
                f"tool {command.tool!r} không thuộc domain {topic_domain!r}",
            )

        await self.mqtt.publish(
            mqtt_topics.events_command(self.vehicle_id),
            outcome.event.model_dump(mode="json"),
            qos=1,
            retain=False,
        )

        if outcome.replayed:
            # Duplicate delivery: phát lại sự kiện để executor bắt được, nhưng
            # state không đổi nên không publish lại.
            logger.info("Lệnh %s là bản lặp — phát lại sự kiện cũ", command.command_id)
            return

        if outcome.changed:
            for domain in outcome.changed:
                await self._publish_domain(domain)
            await self._publish_snapshot()

    def _topic_matches_tool(self, tool: str, topic_domain: Domain) -> bool:
        try:
            return get_spec(tool).domain == topic_domain
        except ToolNotAllowedError:
            return False

    # -- kênh harness (ngoài hợp đồng xe, ADR-024) -------------------------

    async def _on_sim_motion_set(self, topic: str, payload: dict[str, Any]) -> None:
        """`v1/sim/{id}/motion/set` → `set_motion()`. Xem ADR-024.

        Cố ý **không** đi qua `VehicleCommand`, `simulator.execute()` hay
        `events/command`: đây không phải lệnh gửi cho xe, nên nó không được sinh
        `CommandEvent` mà executor sẽ tương quan, và không được đụng tới sổ chống
        lặp của lệnh. Nó chỉ gọi đúng method mà console stdin gọi.

        Payload sai schema thì bỏ qua và ghi log — giống hệt cách `_on_command`
        xử lý lệnh sai schema. Không có ai để trả lỗi về: kênh này một chiều, và
        route HTTP đã validate cùng model ở đầu kia rồi.
        """
        try:
            message = SimMotionSet.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Harness: payload sai schema trên %s: %s", topic, exc.error_count())
            return
        await self.set_motion(message.speed_kph, message.gear)

    # -- điều khiển chuyển động --------------------------------------------

    async def set_motion(self, speed_kph: float, gear: str | None = None) -> bool:
        """Đặt tốc độ/số của xe rồi công bố như mọi thay đổi state khác.

        `motion` nằm trong `READ_ONLY_DOMAINS` nên **không có topic lệnh** — nó
        là thứ xe tự quyết, không ai ra lệnh được. Backend lại bị ACL cấm publish
        `state/*` (`config/mosquitto/acl`), nên dưới MQTT không có đường nào để
        cho xe "chạy" phục vụ demo S3 (chặn mở cửa khi đang di chuyển).

        Lối thoát hợp lệ duy nhất là **xe tự đặt tốc độ của chính nó** — tức
        method này, gọi từ trong tiến trình xe ảo. Không vi phạm ACL vì publisher
        vẫn là identity simulator. Xem ADR-013.

        Ba nguồn gọi, đều nằm trong tiến trình này và đều chụm về đây: console
        stdin (`speed 45`), kênh harness `v1/sim/` (ADR-024), và chu kỳ tự chạy
        (`SIM_DRIVE_CYCLE`). Ba **nút bấm**, một **máy trạng thái** — thứ phải
        tránh là cái sau, không phải cái trước.

        Trả `True` nếu state thật sự đổi.
        """
        motion = self.simulator.state.motion
        target_gear = gear if gear is not None else ("D" if speed_kph else "P")
        if motion.speed_kph == speed_kph and motion.gear == target_gear:
            return False

        motion.speed_kph = speed_kph
        motion.gear = target_gear
        # Cùng quy tắc với `VehicleSimulator.execute`: đổi thật thì version tăng
        # đúng 1, và `observed_at` luôn được làm mới.
        self.simulator.state.state_version += 1
        self.simulator.state.observed_at = utc_now()

        await self._publish_domain("motion")
        await self._publish_snapshot()
        logger.info(
            "Xe %s: speed=%.1f km/h gear=%s (v%d)",
            self.vehicle_id,
            speed_kph,
            target_gear,
            self.simulator.state.state_version,
        )
        return True

    # -- publish -----------------------------------------------------------

    async def _publish_snapshot(self) -> None:
        snapshot = VehicleStateSnapshot.of(self.simulator.snapshot())
        await self.mqtt.publish(
            mqtt_topics.snapshot(self.vehicle_id),
            snapshot.model_dump(mode="json"),
            qos=1,
            retain=True,
        )

    async def _publish_domain(self, domain: Domain) -> None:
        state = self.simulator.state
        message = DomainStateMessage(
            vehicle_id=self.vehicle_id,
            state_version=state.state_version,
            observed_at=state.observed_at,
            domain=domain,
            status="available",
            state=state.domain(domain).model_dump(mode="json"),
        )
        await self.mqtt.publish(
            mqtt_topics.domain_state(self.vehicle_id, domain),
            message.model_dump(mode="json"),
            qos=1,
            retain=True,
        )

    async def _publish_all_domains(self) -> None:
        for domain in DOMAINS:
            await self._publish_domain(domain)

    async def _publish_health(self, *, online: bool, reason: str | None = None) -> None:
        if online:
            health = Health(
                vehicle_id=self.vehicle_id,
                online=True,
                state_version=self.simulator.state.state_version,
                simulator_version=SIMULATOR_VERSION,
                heartbeat_at=utc_now(),
            )
        else:
            health = Health(vehicle_id=self.vehicle_id, online=False, reason=reason)  # type: ignore[arg-type]
        await self.mqtt.publish(
            mqtt_topics.health(self.vehicle_id),
            health.model_dump(mode="json", exclude_none=True),
            qos=1,
            retain=True,
        )

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_s)
            try:
                await self._publish_health(online=True)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — nhịp lỡ không được giết simulator
                logger.exception("Heartbeat thất bại")

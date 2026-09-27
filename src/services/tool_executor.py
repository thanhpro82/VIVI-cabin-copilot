"""Tool executor: derive lệnh, publish lên topic allowlist, chờ CommandEvent.

Quy tắc retry (docs/data_model.md, docs/mqtt_spec.md):

- Idempotency key là `plan_id:step_id`; command_id giữ nguyên qua cả hai lần thử.
- Được retry **đúng một lần**, và chỉ khi *transient transport failure* — tức
  không nhận được CommandEvent nào trong `MQTT_COMMAND_TIMEOUT_MS`.
- Validation failure, policy denial và mọi tool-semantic rejection
  (`stale_state`, `unsafe_vehicle_state`, ...) **không bao giờ** retry.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from pydantic import ValidationError

from src import mqtt_topics
from src.bounded_cache import BoundedCache
from src.models.vehicle import CommandEvent, ToolResult, VehicleCommand, utc_now
from src.services.mqtt_client import MqttPort
from src.services.tool_registry import (
    InvalidArgumentsError,
    ToolNotAllowedError,
    topic_for_tool,
    validate_args,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # lần đầu + đúng một retry cho lỗi transport


class ExecutorError(Exception):
    """Lỗi không tạo được ToolResult — ví dụ hết retry mà vẫn im lặng."""


class ToolExecutor:
    def __init__(self, mqtt: MqttPort, vehicle_id: str, *, timeout_ms: int = 3000) -> None:
        self.mqtt = mqtt
        self.vehicle_id = vehicle_id
        self.timeout_s = timeout_ms / 1000
        self._waiters: dict[str, asyncio.Future[CommandEvent]] = {}
        # Có trần để không phình vô hạn trong process chạy lâu.
        #
        # Chế độ hỏng khi evict: replay cùng plan_id:step_id sau khi entry bị
        # đẩy ra sẽ sinh command_id MỚI, nên simulator không dedupe được — nó
        # thấy đây là lệnh lạ. Thứ chặn transition kép lúc đó là
        # expected_state_version: plan cũ mang version cũ nên bị `stale_state`.
        # Đó là lý do version check bắt buộc, không phải tuỳ chọn.
        self._results: BoundedCache[str, ToolResult] = BoundedCache()

    async def attach(self) -> None:
        await self.mqtt.subscribe(mqtt_topics.events_command(self.vehicle_id), self._on_event)

    async def execute(
        self,
        *,
        plan_id: str,
        step_id: str,
        tool: str,
        args: dict[str, Any],
        expected_state_version: int,
        approval_id: str | None = None,
        execution_group_id: str | None = None,
    ) -> ToolResult:
        idempotency_key = f"{plan_id}:{step_id}"

        # Replay sau khi đã persist terminal thì trả kết quả cũ. Muốn thử lại
        # thật phải re-plan với plan/step ID mới.
        cached = self._results.get(idempotency_key)
        if cached is not None:
            return cached

        # Validate trước khi publish: tool lạ hoặc args sai không bao giờ được
        # lên broker, và không bao giờ retry.
        try:
            topic = topic_for_tool(tool, self.vehicle_id)
            validate_args(tool, args)
        except ToolNotAllowedError as exc:
            return self._local_failure(
                plan_id, step_id, expected_state_version, "tool_not_allowed", str(exc)
            )
        except InvalidArgumentsError as exc:
            return self._local_failure(
                plan_id, step_id, expected_state_version, "invalid_arguments", str(exc)
            )

        command = VehicleCommand(
            command_id=f"cmd_{uuid.uuid4().hex[:20]}",
            idempotency_key=idempotency_key,
            plan_id=plan_id,
            step_id=step_id,
            vehicle_id=self.vehicle_id,
            approval_id=approval_id,
            execution_group_id=execution_group_id,
            expected_state_version=expected_state_version,
            tool=tool,
            args=args,
            issued_at=utc_now(),
        )

        last_error = "không nhận được CommandEvent"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                event = await self._publish_and_wait(command, topic)
            except TimeoutError:
                last_error = f"timeout sau {self.timeout_s:.1f}s"
            except Exception as exc:  # noqa: BLE001 — lỗi transport khác cũng transient
                last_error = f"lỗi transport: {exc}"
            else:
                result = ToolResult.from_event(event, attempt_count=attempt)
                self._results.set(idempotency_key, result)
                return result
            logger.warning("Lần %d cho %s thất bại: %s", attempt, command.command_id, last_error)

        # Hết retry: persist đúng một terminal failed rồi fail-fast.
        logger.error("Bỏ cuộc với %s sau %d lần: %s", command.command_id, MAX_ATTEMPTS, last_error)
        result = ToolResult(
            command_id=command.command_id,
            plan_id=plan_id,
            step_id=step_id,
            approval_id=approval_id,
            execution_group_id=execution_group_id,
            expected_state_version=expected_state_version,
            observed_state_version=expected_state_version,
            attempt_count=MAX_ATTEMPTS,
            status="failed",
            before={},
            after={},
            error_code="mqtt_unavailable",
            latency_ms=self.timeout_s * 1000 * MAX_ATTEMPTS,
        )
        self._results.set(idempotency_key, result)
        return result

    # -- nội bộ ------------------------------------------------------------

    async def _publish_and_wait(self, command: VehicleCommand, topic: str) -> CommandEvent:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[CommandEvent] = loop.create_future()
        # Đăng ký waiter TRƯỚC khi publish, nếu không sự kiện về nhanh sẽ lọt.
        self._waiters[command.command_id] = waiter
        try:
            await self.mqtt.publish(
                topic, command.model_dump(mode="json"), qos=1, retain=False
            )
            return await asyncio.wait_for(waiter, timeout=self.timeout_s)
        finally:
            self._waiters.pop(command.command_id, None)

    async def _on_event(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            event = CommandEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("CommandEvent sai schema trên %s: %s", topic, exc.error_count())
            return
        if event.phase == "accepted":
            # `accepted` = simulator đã đặt giá trị đích, CHƯA quan sát thấy đạt đích;
            # chỉ `completed`/`rejected` mới là terminal (docs/mqtt_spec.md §phase và status).
            # Simulator P0 áp dụng tức thì nên không phát `accepted`, nhưng phase vẫn nằm
            # trong enum để P1 mô phỏng độ trễ hội tụ mà không phải đổi hợp đồng (ADR-004).
            # Nếu ngày đó tới mà chỗ này resolve waiter thì `ToolResult.from_event()` sẽ
            # dựng một kết quả `completed` từ một lệnh mới chỉ được *nhận* — tức lượt báo
            # thành công trước khi giá trị thực đạt đích. Bỏ qua ở đây, để `_publish_and_wait`
            # chờ tiếp tới terminal event (hoặc hết `timeout_s`).
            logger.debug("bỏ qua CommandEvent phase=accepted cho %s, chờ terminal", event.command_id)
            return
        waiter = self._waiters.get(event.command_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(event)

    def _local_failure(
        self,
        plan_id: str,
        step_id: str,
        expected_state_version: int,
        error_code: str,
        detail: str,
    ) -> ToolResult:
        """Từ chối trước khi publish — không có command_id nào lên broker."""
        result = ToolResult(
            command_id=f"cmd_local_{uuid.uuid4().hex[:12]}",
            plan_id=plan_id,
            step_id=step_id,
            expected_state_version=expected_state_version,
            observed_state_version=expected_state_version,
            attempt_count=1,
            status="rejected",
            before={},
            after={},
            error_code=error_code,
            latency_ms=0.0,
        )
        logger.info("Từ chối tại chỗ %s:%s — %s (%s)", plan_id, step_id, error_code, detail)
        self._results.set(f"{plan_id}:{step_id}", result)
        return result

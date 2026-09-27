"""Kết nối MQTT dùng chung của backend, gắn vào vòng đời FastAPI.

Giữ đúng một client, một state cache và một executor cho cả process. Khởi tạo
trong `lifespan` của src/main.py và lấy ra qua `get_runtime(app)`.

Đặt `MQTT_ENABLED=false` để chạy backend không cần broker (unit test, CI).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from src.config import Settings
from src.services.mqtt_client import AiomqttClient, MqttPort
from src.services.tool_executor import ToolExecutor
from src.services.vehicle_state import VehicleStateCache

logger = logging.getLogger(__name__)


class MqttRuntime:
    def __init__(
        self,
        vehicle_id: str,
        *,
        heartbeat_stale_s: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.vehicle_id = vehicle_id
        self.cache = VehicleStateCache(
            vehicle_id, heartbeat_stale_s=heartbeat_stale_s, clock=clock
        )
        self.client: MqttPort | None = None
        self.executor: ToolExecutor | None = None
        self._owned: AiomqttClient | None = None

    @property
    def connected(self) -> bool:
        return self.client is not None

    async def start(self, settings: Settings) -> None:
        client = AiomqttClient(
            settings.mqtt_url,
            client_id="vivi-backend",
            username=settings.mqtt_backend_username or None,
            password=settings.backend_password() or None,
            # Backend chủ động re-subscribe khi khởi động và đã có retained
            # state để bù, nên không cần giữ session.
            clean_session=True,
            keepalive=30,
        )
        await client.start()
        self._owned = client
        await self.bind(client, timeout_ms=settings.mqtt_command_timeout_ms)
        logger.info("Backend đã nối broker tại %s", settings.mqtt_url)

    async def bind(self, client: MqttPort, *, timeout_ms: int = 3000) -> None:
        """Gắn cache + executor vào một cổng MQTT bất kỳ.

        Tách khỏi `start` để test bind thẳng vào InMemoryBroker.
        """
        self.client = client
        self.executor = ToolExecutor(client, self.vehicle_id, timeout_ms=timeout_ms)
        await self.cache.attach(client)
        await self.executor.attach()

    async def stop(self) -> None:
        if self._owned is not None:
            await self._owned.stop()
            self._owned = None
        self.client = None
        self.executor = None

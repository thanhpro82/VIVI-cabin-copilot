"""Entrypoint chạy backend: `python -m src.serve`.

Dùng file này thay cho `uvicorn src.main:app` khi phát triển trên Windows.

Uvicorn chọn event loop bằng loop_factory riêng và bỏ qua asyncio policy; trên
Windows nó trả về ProactorEventLoop, mà loop đó không có `add_reader`/
`remove_writer` — thứ paho-mqtt cần — nên mọi kết nối MQTT sẽ nổ
`NotImplementedError`. Ở đây ta tự tạo loop rồi mới chạy server.

Trong container Linux `uvicorn src.main:app` vẫn dùng được vì loop mặc định đã
là selector.

`asyncio.run(loop_factory=...)` chỉ tồn tại từ Python 3.12; venv của repo là
3.11 (xem CLAUDE.md), nên phải đặt policy **trước** khi gọi `asyncio.run()` để
loop nó tự tạo bên trong đã là `SelectorEventLoop` — cùng cơ chế
`ensure_selector_event_loop()` mà `tests/conftest.py` đã dùng.
"""

from __future__ import annotations

import asyncio

import uvicorn

from src.config import get_settings
from src.services.mqtt_client import ensure_selector_event_loop


def main() -> None:
    ensure_selector_event_loop()
    settings = get_settings()
    server = uvicorn.Server(
        uvicorn.Config(
            "src.main:app",
            host=settings.app_host,
            port=settings.app_port,
            log_level=settings.log_level.lower(),
        )
    )
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()

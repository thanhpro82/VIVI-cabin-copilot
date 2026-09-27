"""Dựng và phân tích topic MQTT.

Nơi duy nhất trong code biết hình dạng topic. Hợp đồng: docs/mqtt_spec.md.

LLM không bao giờ được tạo raw topic — tool registry ánh xạ tool sang topic
(ADR-004). Module này chỉ ghép chuỗi; việc quyết định tool nào đi domain nào
nằm ở `src.services.tool_registry`.
"""

from __future__ import annotations

import re

from src.models.vehicle import DOMAINS, Domain

PREFIX = "v1/vehicles"


def commands(vehicle_id: str, domain: Domain) -> str:
    return f"{PREFIX}/{vehicle_id}/commands/{domain}"


def commands_filter(vehicle_id: str) -> str:
    """Filter simulator subscribe để nhận lệnh của mọi domain."""
    return f"{PREFIX}/{vehicle_id}/commands/+"


def events_command(vehicle_id: str) -> str:
    return f"{PREFIX}/{vehicle_id}/events/command"


def domain_state(vehicle_id: str, domain: Domain) -> str:
    return f"{PREFIX}/{vehicle_id}/state/{domain}"


def domain_state_filter(vehicle_id: str) -> str:
    """Khớp cả `state/{domain}` lẫn `state/snapshot` — dùng một subscribe."""
    return f"{PREFIX}/{vehicle_id}/state/+"


def snapshot(vehicle_id: str) -> str:
    return f"{PREFIX}/{vehicle_id}/state/snapshot"


def health(vehicle_id: str) -> str:
    return f"{PREFIX}/{vehicle_id}/health"


def health_probe(vehicle_id: str) -> str:
    """Topic riêng cho `probe_mqtt` (issue #51) tự publish QoS 1 lên chính nó —
    broker phải PUBACK trước khi `publish()` trả về, bằng chứng round-trip thật
    thay vì chỉ đọc cờ kết nối nội bộ.

    Nằm dưới `commands/#` vì backend đã có quyền ghi ở đó theo ACL
    (`config/mosquitto/acl`) — không cần mở topic mới. `_health_probe` không
    khớp `Domain` hợp lệ nào nên `parse_command_domain()` trả `None` và
    simulator (subscribe `commands/+`) tự bỏ qua an toàn ở `_on_command`,
    không kích hành động thật nào.
    """
    return f"{PREFIX}/{vehicle_id}/commands/_health_probe"


#: Namespace **harness**, nằm ngoài hợp đồng xe — ADR-024.
#:
#: Không nằm dưới `v1/vehicles/` là quyết định, không phải cách đặt tên. Nếu topic
#: đặt tốc độ nằm ở `v1/vehicles/{id}/commands/motion` thì `parse_command_domain()`
#: nhận `motion` là domain lệnh hợp lệ — `motion` rời `READ_ONLY_DOMAINS` trên thực
#: tế dù enum không đổi chữ nào — và ACL của backend đã là `write
#: v1/vehicles/+/commands/#`, nên topic mới **tự động được phép**: một lần nới quyền
#: mà không ai phải ký tên vào.
#:
#: Namespace này chỉ được chứa thứ **xe tự quyết mà không ai ra lệnh được** (tức
#: `motion`, và ở P0 là hết). Thêm `v1/sim/{id}/doors/set` vào đây là mở cửa hậu
#: điều khiển xe vòng qua policy và HITL — mọi actuator phải đi hợp đồng xe.
SIM_PREFIX = "v1/sim"


def sim_motion_set(vehicle_id: str) -> str:
    """Backend publish, xe ảo subscribe rồi tự gọi `set_motion()`. Xem ADR-024."""
    return f"{SIM_PREFIX}/{vehicle_id}/motion/set"


_COMMAND_RE = re.compile(rf"^{PREFIX}/(?P<vehicle_id>[^/]+)/commands/(?P<domain>[^/]+)$")


def parse_command_domain(topic: str) -> Domain | None:
    """Lấy domain từ topic lệnh. None nếu topic sai hình dạng hoặc domain lạ."""
    match = _COMMAND_RE.match(topic)
    if match is None:
        return None
    domain = match.group("domain")
    return domain if domain in DOMAINS else None  # type: ignore[return-value]

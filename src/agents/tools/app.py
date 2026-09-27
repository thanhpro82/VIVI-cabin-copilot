"""Args schema cho `open_app` — mở app giải trí trên IVI. ADR-023.

**Định nghĩa thật nằm ở `src/services/tool_registry.py`** — file này chỉ tái xuất.

Trước #325 mỗi tool có **hai** class Pydantic: một ở đây (cổng `validate_args` của
đường plan) và một ở registry (domain / safety / topic MQTT). Không dòng code nào bắt
chúng khớp, và chúng đã lệch thật — `set_navigation` nhận `destination_ref` ở một bên
và từ chối ở bên kia; `search_nearby_poi` chỉ có ở một bên. Lớp lỗi ấy **xanh test cả
hai phía**, vì không test nào so hai bên với nhau.

Giữ module này thay vì xoá: nó là chỗ người ta quen tìm, và `from src.agents.tools.media
import MediaControlArgs` vẫn phải chạy. Nhưng nó không còn khai gì nữa.
"""

from src.services.tool_registry import OpenAppArgs

__all__ = ["OpenAppArgs"]

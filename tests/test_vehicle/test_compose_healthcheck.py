"""Readiness probe của broker phải khớp với ACL của chính nó.

Bug đã xảy ra thật: `docker-compose.yml` và `.github/workflows/mqtt-contract.yml`
cùng chờ readiness bằng `mosquitto_sub -t '$SYS/#' -C 1 -W 3 -u vivi-backend`,
trong khi `config/mosquitto/acl` chỉ cấp cho identity đó bốn topic
`v1/vehicles/...`. Mosquitto chặn **im lặng** — không lỗi, chỉ là không có gì
tới — nên probe hết giờ và `exit 27`. Hệ quả: container `mqtt` mãi `unhealthy`,
`backend` + `vehicle-simulator` (`depends_on: condition: service_healthy`) không
bao giờ khởi động, và job L2 trên CI chết ở bước "Chờ broker sẵn sàng".

Hai bất biến được khoá ở đây, và bất biến thứ nhất mới là cái quan trọng:

1. **Probe không được chờ message tới.** Không topic nào mà identity backend được
   đọc có traffic đảm bảo lúc broker vừa lên: `state/*` và `health` chỉ xuất hiện
   sau khi simulator chạy, mà simulator lại đang đợi chính healthcheck này. Nên
   mọi biến thể "chờ nhận một message" (`-C`, `-W`) đều sai về nguyên tắc, không
   riêng gì `$SYS`. Cách đúng là `-E`: thoát ngay khi broker đã SUBACK.
2. **Topic được probe phải nằm trong quyền đọc của identity dùng để probe.** Với
   `-E` thì ACL không còn ảnh hưởng tới kết quả (Mosquitto SUBACK thành công cả
   khi từ chối), nhưng một probe không nên dựa vào subscription mà chính nó không
   được phép — và giữ khẳng định này là thứ sẽ bắt được bug trên nếu nó quay lại
   dưới dạng khác.

Test cấu trúc, cố ý **không** cần Docker: nó phải chạy trong mọi lần CI, kể cả
lần không dựng broker. Bằng chứng hành vi (`docker compose up -d --wait mqtt` →
`healthy`) nằm ở WORKLOG, không thay thế được cho nhau.

Đọc bằng regex chứ không parse YAML: `pyyaml` không có trong `dependencies` của
`pyproject.toml`, và thêm một dependency chỉ để đọc một dòng lệnh thì đắt hơn
thứ nó mua.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "mqtt-contract.yml"
ACL = REPO_ROOT / "config" / "mosquitto" / "acl"

#: Identity mà cả hai probe dùng. Trong compose nó đi qua
#: `$$MQTT_BACKEND_USERNAME` (mặc định `vivi-backend` ngay trong file); trong
#: workflow nó là literal. Cả hai quy về một tên ở đây.
PROBE_IDENTITY = "vivi-backend"

_SUB_COMMAND = re.compile(r"mosquitto_sub[^\n\"\]]*", re.MULTILINE)
_TOPIC = re.compile(r"-t\s+'([^']+)'")


def _probe_commands(path: Path) -> list[str]:
    """Mọi lời gọi `mosquitto_sub` trong một file cấu hình.

    Trả list rỗng là **lỗi**, không phải "không có gì để kiểm": nghĩa là file đã
    được viết lại theo cách regex không còn thấy, và test sẽ âm thầm xanh mãi.
    Nên caller phải khẳng định list không rỗng.
    """
    text = path.read_text(encoding="utf-8")
    # Workflow xuống dòng bằng `\` nên nối lại trước khi tách lệnh.
    text = text.replace("\\\n", " ")
    return [match.group(0).strip() for match in _SUB_COMMAND.finditer(text)]


def _acl_read_filters(identity: str) -> list[str]:
    """Các topic filter mà `identity` được `topic read`, theo `config/mosquitto/acl`."""
    filters: list[str] = []
    current: str | None = None
    for raw in ACL.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("user "):
            current = line.removeprefix("user ").strip()
        elif line.startswith("topic ") and current == identity:
            parts = line.split()
            # `topic read <filter>` — cũng có dạng `topic <filter>` (cả hai chiều),
            # nhưng file này luôn khai chiều tường minh.
            if len(parts) >= 3 and parts[1] in {"read", "readwrite"}:
                filters.append(parts[-1])
    return filters


def _covers(acl_filter: str, requested: str) -> bool:
    """`acl_filter` có bao trọn `requested` không, theo wildcard MQTT.

    So khớp **filter với filter**, không phải filter với topic cụ thể: probe
    subscribe `v1/vehicles/+/state/snapshot`, còn ACL cấp `v1/vehicles/+/state/#`.
    `+` bên ACL nhận đúng một mức bất kỳ (kể cả một `+` bên kia); `#` nhận toàn
    bộ phần đuôi còn lại.
    """
    acl_levels = acl_filter.split("/")
    requested_levels = requested.split("/")
    for index, acl_level in enumerate(acl_levels):
        if acl_level == "#":
            return True
        if index >= len(requested_levels):
            return False
        if acl_level != "+" and acl_level != requested_levels[index]:
            return False
    return len(acl_levels) == len(requested_levels)


@pytest.mark.parametrize("path", [COMPOSE, WORKFLOW], ids=["docker-compose", "ci-workflow"])
def test_probe_khong_duoc_cho_message_toi(path: Path):
    commands = _probe_commands(path)
    assert commands, f"không tìm thấy lời gọi mosquitto_sub nào trong {path.name} — regex đã lạc hậu"

    for command in commands:
        assert " -E" in command, f"{path.name}: probe phải dùng `-E` (thoát sau SUBACK), đang là: {command}"
        assert not re.search(r"\s-[CW]\s", command), (
            f"{path.name}: probe đang chờ message tới (`-C`/`-W`). Lúc broker vừa lên chưa "
            f"topic nào có traffic đảm bảo, nên nhánh này luôn hết giờ. Lệnh: {command}"
        )


@pytest.mark.parametrize("path", [COMPOSE, WORKFLOW], ids=["docker-compose", "ci-workflow"])
def test_topic_duoc_probe_nam_trong_quyen_doc_cua_identity(path: Path):
    read_filters = _acl_read_filters(PROBE_IDENTITY)
    assert read_filters, f"không đọc được dòng `topic read` nào của {PROBE_IDENTITY} trong {ACL}"

    commands = _probe_commands(path)
    assert commands, f"không tìm thấy lời gọi mosquitto_sub nào trong {path.name}"

    for command in commands:
        match = _TOPIC.search(command)
        assert match, f"{path.name}: không tách được `-t '<topic>'` từ: {command}"
        topic = match.group(1)
        assert any(_covers(acl_filter, topic) for acl_filter in read_filters), (
            f"{path.name}: probe subscribe `{topic}` nhưng ACL không cấp quyền đọc cho "
            f"`{PROBE_IDENTITY}` (chỉ có {read_filters}). Mosquitto chặn im lặng, nên đây là "
            f"lỗi không bao giờ tự lộ ra lúc chạy."
        )


def test_helper_so_khop_wildcard_dung():
    """Bản thân `_covers` là chỗ dễ sai nhất trong file này — khoá lại luôn.

    Sai theo chiều dễ dãi thì hai test trên xanh vô nghĩa; sai theo chiều chặt
    thì chúng đỏ giả. Cả hai đều tệ hơn không có test.
    """
    assert _covers("v1/vehicles/+/state/#", "v1/vehicles/+/state/snapshot")
    assert _covers("v1/vehicles/+/health", "v1/vehicles/+/health")
    assert _covers("v1/vehicles/#", "v1/vehicles/demo/state/snapshot")
    # `#` phải là mức cuối mới bao được phần đuôi; `+` chỉ một mức.
    assert not _covers("v1/vehicles/+/health", "v1/vehicles/demo/state/snapshot")
    assert not _covers("v1/vehicles/+/state/#", "$SYS/#")
    # Độ dài lệch mà không có `#` thì không bao được.
    assert not _covers("v1/vehicles/+/state", "v1/vehicles/+/state/snapshot")
    assert not _covers("v1/vehicles/+/state/snapshot", "v1/vehicles/+/state")

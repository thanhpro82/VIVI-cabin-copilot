"""JSON Schema conformance — đưa hai script kiểm chứng vào pytest.

`scripts/validate_mqtt_schemas.py` và `scripts/crosscheck_mqtt_spec.py` đã tồn
tại và đúng, nhưng **không được gọi ở đâu cả**: không trong CI, không trong
Makefile, không trong pytest. Nghĩa là model pydantic và sáu JSON Schema ở
`schemas/mqtt/` chưa từng được đối chiếu tự động — chúng có thể trôi xa nhau mà
không ai biết cho tới lúc một client ngoài Python đọc payload.

Hai script chạy toàn bộ ở **module level**, đọc `sys.argv[1]` làm repo root và
gọi `sys.exit(1)` khi hỏng. Nên chúng được chạy dạng **subprocess** chứ không
import: import từ pytest sẽ lấy nhầm đường dẫn (argv của pytest là tên file test)
và một lần thất bại sẽ giết luôn tiến trình test. Chạy subprocess cũng đúng bằng
cách CI sẽ chạy chúng, nên test này bảo đảm cả lệnh lẫn nội dung.

Phần thứ hai của file làm thứ mà script không làm được: validate **payload thật
bắt từ broker** bằng JSON Schema, chứ không chỉ mấy payload mẫu chép từ tài liệu.

`jsonschema` + `referencing` đã có sẵn trong `requirements.txt` — không cần thêm
dependency nào.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from src import mqtt_topics
from tests.mqtt_rig import VEHICLE_ID

REPO_ROOT = Path(__file__).resolve().parents[2]


# -- hai script kiểm chứng, chạy đúng cách CI chạy -------------------------


@pytest.mark.parametrize(
    "script",
    ["validate_mqtt_schemas.py", "crosscheck_mqtt_spec.py"],
)
def test_script_kiem_chung_schema_chay_dat(script):
    completed = subprocess.run(  # noqa: S603 - đường dẫn cố định trong repo
        [sys.executable, str(REPO_ROOT / "scripts" / script), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


# -- payload THẬT bắt từ broker --------------------------------------------


@pytest.fixture(scope="module")
def validator_for():
    """Dựng registry từ `schemas/mqtt/` để `$ref` tương đối resolve được.

    Lặp lại vài dòng của script thay vì import nó — đổi lại test không phụ thuộc
    vào việc script được viết dưới dạng có thể import hay không.
    """
    registry = Registry()
    schemas: dict[str, dict] = {}
    for path in sorted((REPO_ROOT / "schemas" / "mqtt").glob("*.schema.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name.removesuffix(".schema.json")] = doc
        registry = registry.with_resource(doc["$id"], Resource.from_contents(doc))

    # Sáu schema của **hợp đồng xe**, cộng `sim_motion_set` — kênh harness nằm
    # NGOÀI hợp đồng (ADR-024). Tách hai con số thay vì nâng 6 thành 7: cái ràng
    # buộc đáng giữ là "hợp đồng xe có đúng sáu message", và nó sẽ tan mất nếu
    # mỗi lần thêm một file harness lại nâng một con số gộp.
    hop_dong_xe = sorted(set(schemas) - {"sim_motion_set"})
    assert len(hop_dong_xe) == 6, f"mong đợi 6 schema hợp đồng xe, thấy {hop_dong_xe}"

    def build(stem: str) -> Draft202012Validator:
        return Draft202012Validator(schemas[stem], registry=registry)

    return build


async def test_snapshot_that_khop_json_schema(rig, validator_for):
    """Đây là phần script không làm được: dữ liệu thật, không phải mẫu."""
    await rig.run("set_hvac_temperature", {"temperature_c": 23})

    payloads = rig.snapshots_published()
    assert payloads
    for payload in payloads:
        validator_for("vehicle_state_snapshot").validate(payload)


async def test_command_event_that_khop_json_schema(rig, validator_for):
    await rig.run("set_window_position", {"window": "front_left", "percent": 35})

    events = rig.events_published()
    assert events, "chưa có event nào thì test này vô nghĩa"
    for payload in events:
        validator_for("command_event").validate(payload)


async def test_vehicle_command_that_khop_json_schema(rig, validator_for):
    await rig.run("set_door_state", {"door": "front_left", "state": "open"})

    commands = rig.commands_published()
    assert commands
    for _topic, payload, _qos, _retain in commands:
        validator_for("vehicle_command").validate(payload)


async def test_health_that_khop_json_schema(rig, validator_for):
    """Cả Birth (online=true) lẫn shutdown (online=false) đều phải hợp lệ."""
    payloads = rig.broker.published_on(mqtt_topics.health(VEHICLE_ID))
    assert payloads, "Birth message phải được publish lúc start"
    for payload in payloads:
        validator_for("health").validate(payload)

    await rig.sim_runtime.stop()

    shutdown = rig.broker.published_on(mqtt_topics.health(VEHICLE_ID))[-1]
    validator_for("health").validate(shutdown)
    assert shutdown["online"] is False
    assert shutdown["reason"] == "shutdown"


async def test_domain_state_that_khop_json_schema(rig, validator_for):
    """Mỗi domain có nhánh `if/then` riêng trong `domain_state.schema.json`."""
    await rig.run("set_hvac_temperature", {"temperature_c": 25}, step_id="step_1")
    await rig.run("set_window_position", {"window": "rear_left", "percent": 5}, step_id="step_2")

    domain_payloads = [
        payload
        for topic, payload, _qos, _retain in rig.broker.published
        if "/state/" in topic and not topic.endswith("/snapshot")
    ]

    assert domain_payloads
    for payload in domain_payloads:
        validator_for("domain_state").validate(payload)

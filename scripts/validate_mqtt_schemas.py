"""Kiểm chứng các JSON Schema trong schemas/mqtt/.

Chạy: python validate_mqtt_schemas.py <repo_root>
- payload mẫu (lấy nguyên từ docs/mqtt_spec.md) phải PASS
- payload sai phải FAIL

Sáu schema đầu là **hợp đồng xe**. `sim_motion_set` thì không: nó là kênh harness
nằm ngoài hợp đồng (ADR-024), và có mặt ở đây vì nó vẫn là message trên dây —
trần 0..200 km/h và enum gear phải được khoá ở tầng schema chứ không chỉ ở
pydantic của backend, bởi route HTTP không phải đường duy nhất publish lên topic
đó (L2 contract test publish thẳng, và ai cầm credential backend cũng publish
được).
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# Script in tiếng Việt. Khi stdout là console thì Windows dùng UTF-8, nhưng khi
# nó là pipe (CI, `> out.txt`, subprocess trong pytest) thì Python rơi về cp1252
# và mọi dấu tiếng Việt làm script chết bằng UnicodeEncodeError — tức là hỏng
# đúng lúc nó được chạy tự động.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SCHEMA_DIR = ROOT / "schemas" / "mqtt"

# Nạp mọi schema vào registry theo $id để $ref tương đối resolve được.
registry = Registry()
schemas = {}
for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
    doc = json.loads(path.read_text(encoding="utf-8"))
    schemas[path.name.removesuffix(".schema.json")] = doc
    registry = registry.with_resource(doc["$id"], Resource.from_contents(doc))


def validator(stem):
    return Draft202012Validator(schemas[stem], registry=registry)


CMD = {
    "schema_version": "1.0",
    "command_id": "cmd_01J",
    "idempotency_key": "plan_01J:step_01J",
    "plan_id": "plan_01J",
    "step_id": "step_01J",
    "vehicle_id": "vehicle-demo-01",
    "approval_id": None,
    "execution_group_id": None,
    "expected_state_version": 41,
    "tool": "set_hvac_temperature",
    "args": {"temperature_c": 24},
    "issued_at": "2026-08-03T02:00:11Z",
}

EVENT = {
    "schema_version": "1.0",
    "event_id": "evt_01J",
    "command_id": "cmd_01J",
    "idempotency_key": "plan_01J:step_01J",
    "plan_id": "plan_01J",
    "step_id": "step_01J",
    "vehicle_id": "vehicle-demo-01",
    "approval_id": None,
    "execution_group_id": None,
    "phase": "completed",
    "status": "completed",
    "expected_state_version": 41,
    "observed_state_version": 42,
    "before": {"temperature_c": 27, "state_version": 41},
    "after": {"temperature_c": 24, "state_version": 42},
    "error_code": None,
    "latency_ms": 38,
    "emitted_at": "2026-08-03T02:00:11Z",
}

DOMAIN_STATE = {
    "schema_version": "1.0",
    "vehicle_id": "vehicle-demo-01",
    "state_version": 42,
    "observed_at": "2026-08-03T02:00:12Z",
    "domain": "hvac",
    "status": "available",
    "state": {"power": True, "temperature_c": 24, "fan_level": 3},
}

SNAPSHOT = {
    "schema_version": "1.0",
    "vehicle_id": "vehicle-demo-01",
    "state_version": 42,
    "observed_at": "2026-08-03T02:00:12Z",
    "motion": {"speed_kph": 0, "gear": "P", "ignition": "ON"},
    "hvac": {"power": True, "temperature_c": 24, "fan_level": 3},
    "windows": {"front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0},
    "doors": {
        "front_left": "closed",
        "front_right": "closed",
        "rear_left": "closed",
        "rear_right": "closed",
    },
    "media": {"status": "paused", "volume": 35, "track": None},
    "navigation": {"status": "idle", "destination_id": None},
    "seat": {
        "front_left": {"heating": 0, "fore_aft": 50, "recline": 50, "height": 50},
        "front_right": {"heating": 0, "fore_aft": 50, "recline": 50, "height": 50},
    },
    "lights": {"headlight": "auto", "interior": False},
    "trunk": {"position": "closed"},
}

SIM_MOTION = {
    "schema_version": "1.0",
    "speed_kph": 45,
    "gear": "D",
}

HEALTH_UP = {
    "schema_version": "1.0",
    "vehicle_id": "vehicle-demo-01",
    "online": True,
    "state_version": 42,
    "simulator_version": "1.0.0",
    "heartbeat_at": "2026-08-03T02:00:12Z",
}

HEALTH_LWT = {
    "schema_version": "1.0",
    "vehicle_id": "vehicle-demo-01",
    "online": False,
    "reason": "lwt",
}


def drop(d, key):
    out = dict(d)
    out.pop(key)
    return out


def merge(d, **kw):
    out = dict(d)
    out.update(kw)
    return out


MUST_PASS = [
    ("vehicle_command", CMD, "VehicleCommand mẫu"),
    ("command_event", EVENT, "CommandEvent mẫu"),
    ("domain_state", DOMAIN_STATE, "DomainState mẫu"),
    ("vehicle_state_snapshot", SNAPSHOT, "VehicleStateSnapshot mẫu"),
    ("health", HEALTH_UP, "Health birth (online)"),
    ("health", HEALTH_LWT, "Health LWT (offline)"),
    (
        "domain_state",
        drop(DOMAIN_STATE, "status"),
        "DomainState bỏ status (tùy chọn)",
    ),
    ("sim_motion_set", SIM_MOTION, "SimMotionSet mẫu (harness, ADR-024)"),
    (
        "sim_motion_set",
        drop(SIM_MOTION, "gear"),
        "SimMotionSet bỏ gear — nghĩa là 'chọn hộ tôi'",
    ),
    ("sim_motion_set", merge(SIM_MOTION, gear=None), "SimMotionSet gear=null"),
    ("sim_motion_set", merge(SIM_MOTION, speed_kph=0), "SimMotionSet biên dưới 0"),
    ("sim_motion_set", merge(SIM_MOTION, speed_kph=200), "SimMotionSet biên trên 200"),
]

MUST_FAIL = [
    ("vehicle_command", drop(CMD, "schema_version"), "thiếu schema_version"),
    ("vehicle_command", merge(CMD, unknown_field="x"), "thừa field lạ"),
    (
        "vehicle_state_snapshot",
        merge(SNAPSHOT, hvac={"power": True, "temperature_c": 35, "fan_level": 3}),
        "temperature_c=35 ngoài dải 16..30",
    ),
    (
        "vehicle_command",
        merge(CMD, tool="query_manual"),
        "tool S0 không được lên MQTT",
    ),
    (
        "vehicle_command",
        merge(CMD, idempotency_key="khong-co-dau-hai-cham"),
        "idempotency_key sai định dạng plan_id:step_id",
    ),
    (
        "command_event",
        merge(EVENT, status="rejected", error_code=None),
        "rejected nhưng error_code=null",
    ),
    (
        "command_event",
        merge(EVENT, error_code="khong_co_trong_enum"),
        "error_code ngoài enum",
    ),
    ("health", merge(HEALTH_UP, reason="lwt"), "online=true mà có reason"),
    ("health", drop(HEALTH_LWT, "reason"), "online=false mà thiếu reason"),
    (
        "domain_state",
        merge(DOMAIN_STATE, domain="khong_ton_tai"),
        "domain ngoài enum",
    ),
    (
        "domain_state",
        merge(DOMAIN_STATE, domain="media"),
        "domain=media nhưng state là hvac",
    ),
    (
        "vehicle_state_snapshot",
        merge(
            SNAPSHOT,
            windows={
                "front_left": 150,
                "front_right": 0,
                "rear_left": 0,
                "rear_right": 0,
            },
        ),
        "window percent=150",
    ),
    (
        "vehicle_state_snapshot",
        drop(SNAPSHOT, "seat"),
        "snapshot thiếu domain seat",
    ),
    (
        "vehicle_state_snapshot",
        drop(SNAPSHOT, "lights"),
        "snapshot thiếu domain lights",
    ),
    (
        "vehicle_state_snapshot",
        drop(SNAPSHOT, "trunk"),
        "snapshot thiếu domain trunk",
    ),
    (
        # `off` bị loại khỏi enum có chủ đích (UNECE R48, ADR-020). Test này là thứ
        # giữ quyết định đó khỏi bị lặng lẽ nới ra sau này.
        "vehicle_state_snapshot",
        merge(SNAPSHOT, lights={"headlight": "off", "interior": False}),
        "headlight=off — R48 cấm chế độ tắt thủ công",
    ),
    (
        "domain_state",
        merge(DOMAIN_STATE, domain="trunk"),
        "domain=trunk nhưng state là hvac",
    ),
    (
        "sim_motion_set",
        merge(SIM_MOTION, speed_kph=201),
        "harness: speed_kph=201 vượt trần 200",
    ),
    ("sim_motion_set", merge(SIM_MOTION, speed_kph=-1), "harness: speed_kph âm"),
    ("sim_motion_set", merge(SIM_MOTION, gear="X"), "harness: gear ngoài enum"),
    (
        # Kênh harness KHÔNG phải lệnh xe: không mang tool, không sinh CommandEvent,
        # không đụng sổ chống lặp của lệnh. Ca này khoá điều đó ở tầng schema, để
        # không ai lặng lẽ biến nó thành đường điều khiển thứ hai (ADR-024 mục 6).
        "sim_motion_set",
        merge(SIM_MOTION, tool="set_door_state"),
        "harness: nhét tool vào — đây không phải lệnh xe",
    ),
    ("sim_motion_set", drop(SIM_MOTION, "speed_kph"), "harness: thiếu speed_kph"),
]

fails = []

for stem, payload, label in MUST_PASS:
    errs = list(validator(stem).iter_errors(payload))
    if errs:
        fails.append(f"[PHẢI PASS nhưng FAIL] {stem}: {label}\n    {errs[0].message}")
    else:
        print(f"  ok   PASS  {stem:24s} {label}")

for stem, payload, label in MUST_FAIL:
    errs = list(validator(stem).iter_errors(payload))
    if not errs:
        fails.append(f"[PHẢI FAIL nhưng PASS] {stem}: {label}")
    else:
        print(f"  ok   FAIL  {stem:24s} {label}")

print()
if fails:
    print(f"THẤT BẠI: {len(fails)} trường hợp")
    for f in fails:
        print(" -", f)
    sys.exit(1)

print(f"TẤT CẢ ĐẠT: {len(MUST_PASS)} phải-pass + {len(MUST_FAIL)} phải-fail")

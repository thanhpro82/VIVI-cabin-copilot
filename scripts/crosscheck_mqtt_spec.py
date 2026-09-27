"""Đối chiếu chéo mqtt_spec.md <-> agent_spec.md <-> schemas/mqtt/.

- Mọi tool trong bảng tool->topic phải tồn tại trong tool registry của agent_spec.md
- Mọi domain trong enum phải có mặt ở VehicleStateSnapshot và ở domain_state enum
- Không tool/domain nào mồ côi
"""
import json
import re
import sys
from pathlib import Path

# Xem ghi chú cùng nội dung ở scripts/validate_mqtt_schemas.py: stdout là pipe
# trên Windows sẽ dùng cp1252 và giết script vì dấu tiếng Việt.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
mqtt = (ROOT / "docs" / "mqtt_spec.md").read_text(encoding="utf-8")
agent = (ROOT / "docs" / "agent_spec.md").read_text(encoding="utf-8")

problems = []

# --- Tools -----------------------------------------------------------------
# Bảng "Tool-to-topic mapping": dòng | `tool` | topic | safety |
section = mqtt.split("## Tool-to-topic mapping")[1].split("## Message schemas")[0]
mapped = {}
for line in section.splitlines():
    m = re.match(r"\|\s*`([a-z_]+)`\s*\|\s*([^|]+?)\s*\|", line)
    if m:
        mapped[m.group(1)] = m.group(2).strip()

# Registry trong agent_spec.md: chỉ lấy bảng dưới mục "Tool registry and
# planning invariants", không quét cả file (các bảng khác cũng dùng backtick).
registry_section = agent.split("## Tool registry and planning invariants")[1].split(
    "## Prompt boundaries"
)[0]
registry = set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", registry_section, flags=re.M))

print(f"tool trong mqtt_spec bảng ánh xạ : {len(mapped)}")
print(f"tool trong agent_spec registry   : {len(registry)}")

for tool in mapped:
    if tool not in registry:
        problems.append(f"tool '{tool}' có trong mqtt_spec nhưng KHÔNG có trong agent_spec registry")
for tool in registry:
    if tool not in mapped:
        problems.append(f"tool '{tool}' có trong agent_spec registry nhưng KHÔNG có trong bảng ánh xạ mqtt_spec")

# Tool S0 phải được đánh dấu không publish MQTT
S0 = {"get_vehicle_state", "query_manual", "search_nearby_poi"}
for tool in S0:
    if tool in mapped and "không publish" not in mapped[tool]:
        problems.append(f"tool S0 '{tool}' phải ghi rõ không publish MQTT, đang ghi: {mapped[tool]}")

# "Không publish" KHÔNG còn đồng nghĩa với S0 kể từ ADR-023. `open_app` là tool cục bộ
# của IVI: nó *làm* một việc (nên không phải S0, S0 là chỉ đọc) nhưng không có gì trên
# xe đổi trạng thái, nên không có domain để publish. Script này trước đây suy
# "actuator = tool không thuộc S0", và suy đó bây giờ sai — nó sẽ đòi `open_app` xuất
# hiện trong enum `vehicle_command.schema.json`, tức đòi đưa lựa chọn app lên MQTT.
#
# Nên lấy nhóm không-publish từ chính dấu hiệu trong bảng, không suy từ mức an toàn.
khong_publish = {tool for tool, topic in mapped.items() if "không publish" in topic}
if not S0 <= khong_publish:
    problems.append(f"tool S0 thiếu dấu không publish: {sorted(S0 - khong_publish)}")

# Tool actuator phải có trong enum của vehicle_command.schema.json
cmd_schema = json.loads(
    (ROOT / "schemas" / "mqtt" / "vehicle_command.schema.json").read_text(encoding="utf-8")
)
enum_tools = set(cmd_schema["properties"]["tool"]["enum"])
actuators = {t for t in mapped if t not in khong_publish}
if enum_tools != actuators:
    problems.append(
        f"enum tool trong vehicle_command.schema.json lệch bảng ánh xạ:\n"
        f"    chỉ trong schema : {sorted(enum_tools - actuators)}\n"
        f"    chỉ trong spec   : {sorted(actuators - enum_tools)}"
    )
else:
    print(f"tool actuator khớp schema enum   : {len(actuators)}")

# --- Domains ---------------------------------------------------------------
dom_line = mqtt.split("## Domain enum")[1].split("```")[1]
domains = [d.strip() for d in dom_line.strip().split("|")]

snapshot = json.loads(
    (ROOT / "schemas" / "mqtt" / "vehicle_state_snapshot.schema.json").read_text(encoding="utf-8")
)
snap_domains = set(snapshot["properties"]) - {
    "schema_version",
    "vehicle_id",
    "state_version",
    "observed_at",
}

ds = json.loads((ROOT / "schemas" / "mqtt" / "domain_state.schema.json").read_text(encoding="utf-8"))
ds_domains = set(ds["properties"]["domain"]["enum"])

defs = json.loads(
    (ROOT / "schemas" / "mqtt" / "vehicle_state_domains.schema.json").read_text(encoding="utf-8")
)["$defs"]

print(f"domain trong mqtt_spec enum      : {len(domains)}")

if set(domains) != snap_domains:
    problems.append(
        f"domain enum lệch snapshot: chỉ-spec={sorted(set(domains)-snap_domains)}, "
        f"chỉ-snapshot={sorted(snap_domains-set(domains))}"
    )
if set(domains) != ds_domains:
    problems.append(
        f"domain enum lệch domain_state: chỉ-spec={sorted(set(domains)-ds_domains)}, "
        f"chỉ-domain_state={sorted(ds_domains-set(domains))}"
    )
for d in domains:
    if d not in defs:
        problems.append(f"domain '{d}' không có $defs trong vehicle_state_domains.schema.json")

# Mọi domain của tool actuator phải nằm trong enum
for tool, topic in mapped.items():
    m = re.search(r"commands/([a-z_]+)", topic)
    if m and m.group(1) not in domains:
        problems.append(f"tool '{tool}' trỏ tới domain '{m.group(1)}' không có trong enum")

print()
if problems:
    print(f"THẤT BẠI: {len(problems)} vấn đề")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("ĐỐI CHIẾU CHÉO ĐẠT: không có tool/domain mồ côi")

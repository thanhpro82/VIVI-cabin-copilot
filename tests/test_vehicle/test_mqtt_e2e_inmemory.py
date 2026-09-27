"""Tầng L1 — chuỗi Executor → MQTT → Xe ảo → Result/State → Backend.

Phủ AC1 (chuỗi đầy đủ) và AC2 (chỉ dùng topic canonical `v1/vehicles/{id}/...`).

Chạy trên `InMemoryBroker` nên **tất định, không flaky, chạy trong mọi lần CI**.
Đổi lại nó không chứng minh được gì về QoS 1, retain thật, ACL hay Last Will —
những thứ đó thuộc tầng L2 (`test_contract_mosquitto.py`, cần Mosquitto thật).
"""

from __future__ import annotations

import re

from src import mqtt_topics
from src.main import app
from src.models.vehicle import VehicleStateSnapshot
from src.services.vehicle_gateway import set_vehicle_gateway
from tests.mqtt_rig import VEHICLE_ID

#: Mọi topic của hệ thống phải khớp mẫu này. ADR-004 chốt tiền tố `v1/vehicles`;
#: bộ topic cũ `vivi/vehicle/*` trong ticket SCRUM-19 đã bị bác bỏ tường minh
#: (docs/mqtt_spec.md:19).
_CANONICAL_TOPIC = re.compile(r"^v1/vehicles/[^/]+/(commands/[^/]+|events/command|state/[^/]+|health)$")


# -- AC1: chuỗi đầy đủ ------------------------------------------------------


async def test_lenh_di_het_chuoi_va_backend_thay_state_moi(rig):
    """Một lệnh phải đi trọn vòng và quay về cache của backend."""
    before = rig.version

    result = await rig.run("set_hvac_temperature", {"temperature_c": 19})

    # 1. Executor nhận CommandEvent thành công.
    assert result.status == "completed"
    assert result.observed_state_version == before + 1
    # 2. Xe ảo thật sự đổi.
    assert rig.simulator.state.hvac.temperature_c == 19
    # 3. Cache của backend bắt kịp qua retained snapshot.
    assert rig.cache.state is not None
    assert rig.cache.state.hvac.temperature_c == 19
    assert rig.cache.state.state_version == before + 1


async def test_rest_va_cache_noi_cung_mot_state(client, rig, driver_client):
    """`GET /api/v1/vehicle/state` phải khớp đúng cái cache đang giữ."""
    app.state.mqtt = rig.backend
    set_vehicle_gateway(rig.gateway)
    await rig.run("set_window_position", {"window": "front_left", "percent": 40})

    body = (await client.get("/api/v1/vehicle/state")).json()

    state = body["data"]["vehicle_state"]
    assert state["windows"]["front_left"] == 40
    assert state["state_version"] == rig.cache.state.state_version


async def test_ba_lenh_lien_tiep_dung_rolling_version(rig):
    """Chuỗi nhiều bước: mỗi lệnh lấy version từ ToolResult của lệnh trước.

    Đây là lý do `observed_state_version` phải đến từ CommandEvent chứ không phải
    đọc lại cache: cache bắt kịp không đồng bộ, còn event thì do chính simulator
    tính sau khi đã tăng version.
    """
    expected = rig.version
    for index, (tool, args) in enumerate(
        [
            ("set_hvac_temperature", {"temperature_c": 21}),
            ("set_hvac_power", {"enabled": False}),
            ("set_seat_heating", {"seat": "front_left", "level": 2}),
        ],
        start=1,
    ):
        result = await rig.run(tool, args, step_id=f"step_{index}", expected_state_version=expected)
        assert result.status == "completed", result.error_code
        expected = result.observed_state_version

    assert rig.simulator.state.seat.front_left.heating == 2
    assert expected == rig.version


async def test_rolling_van_dung_khi_co_buoc_khong_doi_gi(rig):
    """Lệnh no-op không tăng version — bước sau vẫn phải chạy được.

    Nếu ai đó "tối ưu" bằng cách cộng 1 sau mỗi bước thay vì đọc
    `observed_state_version`, test này sẽ đỏ.
    """
    current_temp = rig.simulator.state.hvac.temperature_c

    noop = await rig.run("set_hvac_temperature", {"temperature_c": current_temp}, step_id="step_1")
    assert noop.status == "completed"

    after = await rig.run(
        "set_hvac_power",
        {"enabled": False},
        step_id="step_2",
        expected_state_version=noop.observed_state_version,
    )

    assert after.status == "completed"


async def test_lenh_bi_tu_choi_khong_de_lai_dau_vet_tren_state(rig):
    before_version = rig.version
    snapshots_before = len(rig.snapshots_published())

    result = await rig.run("set_hvac_temperature", {"temperature_c": 25}, expected_state_version=before_version + 5)

    assert result.status == "rejected"
    assert result.error_code == "stale_state"
    assert rig.version == before_version
    # Lệnh bị từ chối vẫn phát CommandEvent (executor phải biết kết quả) nhưng
    # KHÔNG được publish snapshot mới — không có gì thay đổi để mà công bố.
    assert len(rig.snapshots_published()) == snapshots_before


async def test_snapshot_publish_bang_dung_state_cua_simulator(rig):
    """`VehicleStateSnapshot` trừ `schema_version` phải bằng `data.vehicle_state`.

    So sánh ở mức **đã serialize**, không phải mức object, và đó chính là điều
    hợp đồng nói: `Timestamp` dùng `PlainSerializer` với `%Y-%m-%dT%H:%M:%SZ` nên
    `observed_at` mất phần dưới giây khi lên dây. Hai bên vẫn khớp vì
    `GET /api/v1/vehicle/state` đi qua đúng serializer đó.

    Hệ quả cần biết: `observed_at` có độ phân giải **một giây**, đừng dùng nó để
    đo latency.
    """
    await rig.run("set_hvac_temperature", {"temperature_c": 24})

    latest = rig.snapshots_published()[-1]
    parsed = VehicleStateSnapshot.model_validate(latest)

    assert parsed.to_state().model_dump(mode="json") == rig.simulator.snapshot().model_dump(mode="json")
    # Và `schema_version` là khác biệt DUY NHẤT giữa hai shape.
    assert set(latest) - set(parsed.to_state().model_dump(mode="json")) == {"schema_version"}


# -- AC2: chỉ topic canonical ----------------------------------------------


async def test_moi_topic_publish_deu_canonical(rig):
    await rig.run("set_window_position", {"window": "rear_right", "percent": 15})

    topics = rig.published_topics()

    assert topics, "chưa publish gì thì test này vô nghĩa"
    for topic in topics:
        assert _CANONICAL_TOPIC.match(topic), f"topic ngoài hợp đồng: {topic}"
        assert not topic.startswith("vivi/"), f"topic cũ đã bị bác bỏ: {topic}"


async def test_lenh_di_dung_topic_theo_domain(rig):
    await rig.run("set_door_state", {"door": "front_left", "state": "open"})

    sent = [topic for topic, *_ in rig.commands_published()]

    assert sent == [mqtt_topics.commands(VEHICLE_ID, "doors")]


async def test_commands_va_events_khong_bao_gio_retain(rig):
    """Retain lệnh nghĩa là xe tự mở cửa sau khi broker restart (mqtt_spec.md:39).

    `events/command` cũng không được retain — bộ test cũ chỉ kiểm `commands/`.
    """
    await rig.run("set_hvac_power", {"enabled": True})

    for topic, _payload, _qos, retain in rig.broker.published:
        if "/commands/" in topic or topic.endswith("/events/command"):
            assert retain is False, f"{topic} không được retain"


async def test_state_va_health_luon_retain(rig):
    """Ngược lại: state và health phải retain để backend nối sau vẫn có dữ liệu."""
    await rig.run("set_hvac_power", {"enabled": True})

    for topic, _payload, _qos, retain in rig.broker.published:
        if "/state/" in topic or topic.endswith("/health"):
            assert retain is True, f"{topic} phải retain"


async def test_moi_publish_deu_qos_1(rig):
    """QoS 1 = at-least-once, và dedupe nằm ở tầng ứng dụng (mqtt_spec.md:47)."""
    await rig.run("set_hvac_power", {"enabled": True})

    assert all(qos == 1 for _topic, _payload, qos, _retain in rig.broker.published)


async def test_backend_noi_sau_van_nhan_du_state_qua_retained(rig):
    """Retained là lý do backend không phải hỏi lại xe ảo lúc khởi động."""
    from src.services.mqtt_runtime import MqttRuntime

    await rig.run("set_hvac_temperature", {"temperature_c": 18})

    late = MqttRuntime(VEHICLE_ID)
    await late.bind(rig.broker, timeout_ms=500)

    assert late.cache.state is not None
    assert late.cache.state.hvac.temperature_c == 18
    assert late.cache.readiness().ready is True

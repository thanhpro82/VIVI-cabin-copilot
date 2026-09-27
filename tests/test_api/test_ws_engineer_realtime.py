"""Tầng L1 — AC3 phần "state update realtime" qua `/ws/engineer`.

Bộ test cũ chỉ kiểm **cú đẩy đầu tiên** lúc client vừa nối. Cái chưa ai kiểm là
phần "realtime" thật sự: sau khi có lệnh, client đang mở kết nối có nhận được
state mới không. Đó chính là AC3, và nó chưa từng được chứng minh.

Test ở đây gọi thẳng listener của gateway thay vì dựng WebSocket thật, vì thứ
đang kiểm là **cơ chế fan-out** (`VehicleStateCache._notify`) chứ không phải
handshake — handshake đã có test riêng ở `test_vehicle_state.py`.
"""

from __future__ import annotations

import asyncio

from src.models.vehicle import VehicleState


async def test_client_dang_mo_nhan_duoc_state_moi_sau_lenh(rig):
    """AC3: state update realtime, không phải chỉ lúc kết nối."""
    received: list[VehicleState] = []

    async def listener(state: VehicleState) -> None:
        received.append(state)

    rig.gateway.add_listener(listener)
    try:
        await rig.run("set_hvac_temperature", {"temperature_c": 18}, step_id="step_1")
        await rig.run("set_window_position", {"window": "front_left", "percent": 25}, step_id="step_2")
    finally:
        rig.gateway.remove_listener(listener)

    assert len(received) == 2
    assert received[-1].windows.front_left == 25
    # Version tăng đơn điệu qua các lần đẩy — client dựng lại được thứ tự.
    versions = [state.state_version for state in received]
    assert versions == sorted(versions)
    assert versions[0] < versions[1]


async def test_lenh_bi_tu_choi_khong_day_state(rig):
    """Không có gì thay đổi thì không có gì để công bố."""
    received: list[VehicleState] = []

    async def listener(state: VehicleState) -> None:
        received.append(state)

    rig.gateway.add_listener(listener)
    try:
        await rig.run(
            "set_hvac_temperature",
            {"temperature_c": 20},
            expected_state_version=rig.version + 7,
        )
    finally:
        rig.gateway.remove_listener(listener)

    assert received == []


async def test_nhieu_client_deu_nhan_va_mot_client_hong_khong_chan_client_kia(rig):
    """Một dashboard kỹ sư crash không được làm câm màn hình của người khác."""
    healthy: list[int] = []

    async def broken(state: VehicleState) -> None:
        raise RuntimeError("client này hỏng")

    async def working(state: VehicleState) -> None:
        healthy.append(state.state_version)

    rig.gateway.add_listener(broken)
    rig.gateway.add_listener(working)
    try:
        await rig.run("set_hvac_temperature", {"temperature_c": 19})
    finally:
        rig.gateway.remove_listener(broken)
        rig.gateway.remove_listener(working)

    assert healthy, "listener lành đã bị listener hỏng chặn mất"


async def test_go_listener_thi_khong_con_nhan(rig):
    """Client ngắt kết nối phải được gỡ hẳn, nếu không sẽ rò qua từng lần nối lại."""
    received: list[VehicleState] = []

    async def listener(state: VehicleState) -> None:
        received.append(state)

    rig.gateway.add_listener(listener)
    await rig.run("set_hvac_temperature", {"temperature_c": 21}, step_id="step_1")
    assert len(received) == 1

    rig.gateway.remove_listener(listener)
    await rig.run("set_hvac_power", {"enabled": False}, step_id="step_2")

    assert len(received) == 1


async def test_listener_bi_huy_thi_khong_bi_nuot(rig):
    """`CancelledError` phải được re-raise, không được gộp vào nhóm "client hỏng".

    Nuốt nó nghĩa là shutdown bị chặn và task treo lại mãi.
    """

    async def cancelling(state: VehicleState) -> None:
        raise asyncio.CancelledError

    rig.gateway.add_listener(cancelling)
    try:
        with_cancel = False
        try:
            await rig.run("set_hvac_temperature", {"temperature_c": 24})
        except asyncio.CancelledError:
            with_cancel = True
    finally:
        rig.gateway.remove_listener(cancelling)

    assert with_cancel


async def test_rest_va_ws_thay_cung_mot_version(client, rig, driver_client):
    """Hai kênh đọc cùng nguồn thì không được nói hai con số khác nhau."""
    from src.main import app
    from src.services.vehicle_gateway import set_vehicle_gateway

    app.state.mqtt = rig.backend
    set_vehicle_gateway(rig.gateway)

    seen: list[int] = []

    async def listener(state: VehicleState) -> None:
        seen.append(state.state_version)

    rig.gateway.add_listener(listener)
    try:
        await rig.run("set_hvac_temperature", {"temperature_c": 17})
    finally:
        rig.gateway.remove_listener(listener)

    body = (await client.get("/api/v1/vehicle/state")).json()

    assert body["data"]["vehicle_state"]["state_version"] == seen[-1]

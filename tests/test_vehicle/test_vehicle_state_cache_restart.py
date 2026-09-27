"""`VehicleStateCache` phải theo kịp khi xe ảo khởi động lại và reset bộ đếm.

Bug phát hiện lúc dựng tầng L3 (issue #49): ca test S2 pass khi chạy riêng nhưng
fail khi chạy **sau** ca giết-và-khởi-lại tiến trình xe ảo.

Hai quyết định, mỗi cái đúng riêng nó, hỏng khi gặp nhau:

- `src/vehicle_sim/state.py::initial_state` cứng `state_version=1`. Xe ảo là digital
  twin không persist, nên mỗi lần khởi động lại nó bắt đầu từ 1.
- `VehicleStateCache._on_snapshot` bỏ qua mọi snapshot có version thấp hơn version
  đang giữ — đúng cho message MQTT tới trễ, nhưng không phân biệt được *"message cũ
  về muộn"* với *"xe ảo restart, bộ đếm reset"*.

Hệ quả: backend giữ version cũ, mọi `expected_state_version` nó phát ra đều lệch, và
xe ảo từ chối bằng `stale_state` cho tới khi bộ đếm mới bò qua giá trị cũ. Tệ nhất là
hình dạng của nó — `/healthz` báo `ready` (heartbeat tươi thật) trong khi điều khiển
hỏng, và `GET /vehicle/state` phục vụ state của lần chạy trước.

Tín hiệu để phân biệt **đã có sẵn trên dây, không phải đổi hợp đồng**: chuyển tiếp
`online=false` → `online=true` trên topic `health`. Xe ảo chết thì LWT hoặc shutdown
phát `false`, khởi lại thì Birth phát `true` — cặp Birth+LWT chuẩn MQTT mà
`SimulatorRuntime` đã dùng sẵn. `start()` còn phát health **trước** snapshot, nên tới
lúc snapshot mới về thì cache đã sẵn sàng nhận.

**Không** dùng `health.state_version` để suy ra restart, dù nó có sẵn: `health` là
retained và chỉ publish lại mỗi nhịp heartbeat, nên số đó lag so với state thật và một
subscriber nối muộn thấy "health v1, snapshot v5" là chuyện bình thường. Bản đầu tiên
của bản sửa mắc đúng lỗi này — xem
`test_health_online_bao_version_thap_hon_ma_khong_qua_offline_thi_giu_nguyen`.

Chạy trên `InMemoryBroker` nên tất định, không cần Docker — khác tầng L3 vốn là nơi
bug này lộ ra nhưng phải trả giá bằng hai tiến trình thật và ~30 giây.
"""

from __future__ import annotations

import logging

import pytest

from src import mqtt_topics
from src.models.vehicle import VehicleStateSnapshot
from src.services.mqtt_client import InMemoryBroker
from src.services.vehicle_state import VehicleStateCache
from src.vehicle_sim.state import VehicleSimulator
from tests.mqtt_rig import VEHICLE_ID as RIG_VEHICLE_ID

VEHICLE_ID = "vehicle-restart-01"


def _health_payload(*, online: bool, state_version: int | None = None, vehicle_id: str = VEHICLE_ID) -> dict:
    """Đúng dạng `SimulatorRuntime._publish_health` phát."""
    if online:
        return {
            "schema_version": "1.0",
            "vehicle_id": vehicle_id,
            "online": True,
            "state_version": state_version,
            "simulator_version": "1.0.0",
            "heartbeat_at": "2026-08-11T00:00:00Z",
        }
    return {"schema_version": "1.0", "vehicle_id": vehicle_id, "online": False, "reason": "lwt"}


def _snapshot_payload(state_version: int, *, temperature_c: int, vehicle_id: str = VEHICLE_ID) -> dict:
    """Snapshot hợp lệ ở version cho trước, khác nhau ở một giá trị quan sát được."""
    simulator = VehicleSimulator(vehicle_id)
    simulator.state.state_version = state_version
    simulator.state.hvac.temperature_c = temperature_c
    return VehicleStateSnapshot.of(simulator.snapshot()).model_dump(mode="json")


@pytest.fixture
async def cache():
    """Cache đã nối broker, đang giữ v5 và một heartbeat tươi."""
    broker = InMemoryBroker()
    cache = VehicleStateCache(VEHICLE_ID)
    await cache.attach(broker)

    await broker.publish(mqtt_topics.health(VEHICLE_ID), _health_payload(online=True, state_version=5), retain=True)
    await broker.publish(mqtt_topics.snapshot(VEHICLE_ID), _snapshot_payload(5, temperature_c=27), retain=True)
    assert cache.state is not None and cache.state.state_version == 5, "tiền đề sai"
    return broker, cache


async def test_xe_ao_khoi_dong_lai_thi_cache_nhan_version_thap_hon(cache):
    """Chuỗi thật khi xe ảo chết rồi sống lại: LWT → Birth → snapshot mới.

    Thứ tự này không phải giả định: `SimulatorRuntime` khai LWT lúc CONNECT và
    `start()` gọi `_publish_health(online=True)` **trước** `_publish_snapshot()`.
    """
    broker, state_cache = cache

    await broker.publish(mqtt_topics.health(VEHICLE_ID), _health_payload(online=False), retain=True)
    await broker.publish(mqtt_topics.health(VEHICLE_ID), _health_payload(online=True, state_version=1), retain=True)
    await broker.publish(mqtt_topics.snapshot(VEHICLE_ID), _snapshot_payload(1, temperature_c=27), retain=True)

    assert state_cache.state is not None
    assert state_cache.state.state_version == 1, (
        "cache vẫn giữ version của lần chạy trước. Mọi expected_state_version backend "
        "phát ra sẽ lệch, và xe ảo từ chối bằng stale_state — trong khi /healthz vẫn xanh."
    )


async def test_snapshot_cu_ve_muon_van_bi_bo_qua(cache):
    """Chứng thực âm — bản sửa không được vô hiệu hoá guard gốc.

    Không có health nào báo version lùi thì một snapshot version thấp chỉ có thể là
    message tới trễ, và nhận nó sẽ đẩy state của backend **lùi lại** — đúng thứ guard
    ở `_on_snapshot` tồn tại để chặn. Thiếu ca này thì bản sửa có thể mở toang guard
    mà cả hai test vẫn xanh.
    """
    broker, state_cache = cache

    await broker.publish(mqtt_topics.snapshot(VEHICLE_ID), _snapshot_payload(3, temperature_c=18), retain=True)

    assert state_cache.state is not None
    assert state_cache.state.state_version == 5
    assert state_cache.state.hvac.temperature_c == 27, "đã nuốt snapshot cũ — state bị đẩy lùi"


async def test_health_online_bao_version_thap_hon_ma_khong_qua_offline_thi_giu_nguyen(cache):
    """Chứng thực âm quan trọng nhất của file này — và là lỗi tôi đã mắc thật.

    `health` retain=true và chỉ được publish lại mỗi nhịp heartbeat, nên số
    `state_version` nó mang **lag** so với state thật: giữa hai nhịp, xe ảo chạy lệnh
    và version leo lên trong khi retained health vẫn giữ số cũ. Một subscriber nối
    muộn nhận retained snapshot v5 rồi retained health v1 là chuyện **bình thường**.

    Bản đầu tiên của bản sửa dùng chính so sánh version đó làm bằng chứng restart, và
    nó vứt mất state đúng của một hệ thống đang khoẻ.
    `test_backend_noi_sau_van_nhan_du_state_qua_retained` +
    `test_cache_nhan_state_ngay_khi_noi_nho_retained` bắt được ngay.
    """
    broker, state_cache = cache

    await broker.publish(mqtt_topics.health(VEHICLE_ID), _health_payload(online=True, state_version=1), retain=True)

    assert state_cache.state is not None, "đã vứt state đúng chỉ vì heartbeat lag"
    assert state_cache.state.state_version == 5


async def test_health_bao_version_lui_thi_bo_state_cu_ngay_truoc_khi_snapshot_toi(cache):
    """Khoảng giữa "biết xe ảo restart" và "nhận được snapshot mới".

    Trong khoảng đó backend **không biết** trạng thái thật của xe, nên nó phải quên
    thứ đang giữ chứ không phục vụ tiếp dưới danh nghĩa hiện tại (ADR-013: fail-closed,
    không đoán).

    Bỏ `_state` là đủ để cả hệ thống fail-closed mà **không** phải thêm reason mới:

    - `GET /vehicle/state` → `src/api/routes.py:131` thấy `last_known() is None` và trả
      503 `no_snapshot_yet` — mã đó vốn đã tồn tại cho đúng tình huống này.
    - `MqttVehicleGateway.snapshot()` trả `None` → `normalize_node` đặt
      `vehicle_snapshot = {}` → `safety_node` từ chối lượt.

    `readiness()` cố ý **không** đổi: heartbeat đang tươi thật, xe ảo đang sống thật,
    nên `/healthz` báo `vehicle_simulator: ready` là đúng. Đây cũng chính là tình
    huống đã tồn tại ngay sau khi khởi động — health tới trước snapshot một nhịp.
    """
    broker, state_cache = cache

    await broker.publish(mqtt_topics.health(VEHICLE_ID), _health_payload(online=False), retain=True)
    await broker.publish(mqtt_topics.health(VEHICLE_ID), _health_payload(online=True, state_version=1), retain=True)

    assert state_cache.state is None, (
        "cache vẫn giữ state của lần chạy trước; GET /vehicle/state sẽ trả 200 kèm dữ liệu không còn đúng với xe nào cả"
    )
    assert state_cache.readiness().ready is True, "heartbeat đang tươi — không được báo xe ảo chết"


async def test_floor_cua_gateway_khong_ket_o_version_cua_lan_chay_truoc(rig, caplog):
    """Biểu hiện thứ hai của cùng bug, ở `MqttVehicleGateway`.

    `_floor` chỉ tăng (`self._floor = max(self._floor, result.observed_state_version)`),
    nên sau restart nó thành một mốc **không bao giờ đạt được**: `_await_floor` chờ hết
    `FLOOR_BUDGET_S` rồi mới đi tiếp — không sai về an toàn (`expected_state_version`
    vẫn là lớp chặn thật) nhưng cộng nửa giây vào **mọi** lượt, vĩnh viễn.

    Khẳng định bằng log chứ không bằng đồng hồ: cả hai đường đều trả đúng state, chỉ
    khác thời gian, mà một test dựa trên ngưỡng thời gian trên Windows là test giòn.
    Dòng warning "Cache chưa đạt" chính là thứ `_await_floor` phát khi nó bỏ cuộc, nên
    vắng mặt nó là bằng chứng trực tiếp và tất định.
    """
    await rig.run("set_hvac_temperature", {"temperature_c": 21})

    # Xe ảo "khởi động lại": health online mang version thấp, rồi snapshot v1.
    await rig.publish_raw(
        mqtt_topics.health(RIG_VEHICLE_ID),
        _health_payload(online=False, vehicle_id=RIG_VEHICLE_ID),
        retain=True,
    )
    await rig.publish_raw(
        mqtt_topics.health(RIG_VEHICLE_ID),
        _health_payload(online=True, state_version=1, vehicle_id=RIG_VEHICLE_ID),
        retain=True,
    )
    await rig.publish_raw(
        mqtt_topics.snapshot(RIG_VEHICLE_ID),
        _snapshot_payload(1, temperature_c=27, vehicle_id=RIG_VEHICLE_ID),
        retain=True,
    )

    with caplog.at_level(logging.WARNING, logger="src.services.vehicle_gateway"):
        state = await rig.gateway.snapshot()

    assert state is not None and state.state_version == 1
    stalled = [record for record in caplog.records if "Cache chưa đạt" in record.getMessage()]
    assert not stalled, f"gateway vẫn chờ floor của lần chạy trước: {[r.getMessage() for r in stalled]}"


async def test_nhieu_nhip_heartbeat_lien_tiep_khong_bao_gio_xoa_state(cache):
    """Nhịp heartbeat bình thường không được đụng vào state.

    `_forget_state_of_previous_run` chỉ chạy ở chuyển tiếp offline→online. Nếu ai đó
    hạ điều kiện xuống "mỗi health online" thì cache sẽ bị dọn 5 giây một lần và
    `GET /vehicle/state` chớp tắt giữa 200 và 503 mà không rõ vì sao.
    """
    broker, state_cache = cache

    for version in (5, 6, 7):
        await broker.publish(
            mqtt_topics.health(VEHICLE_ID), _health_payload(online=True, state_version=version), retain=True
        )

    assert state_cache.state is not None
    assert state_cache.state.state_version == 5
    assert state_cache.incarnation == 0

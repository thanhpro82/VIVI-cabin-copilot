"""`python -m src.vehicle_sim` dựng K xe, mỗi xe một kết nối MQTT riêng.

Không dùng broker thật: thay `AiomqttClient` bằng một bản giả ghi lại những gì nó nhận.
Thứ cần khẳng định ở đây là **cách nối dây** — số xe, `client_id` phân biệt, và LWT
riêng cho từng chiếc — chứ không phải hành vi MQTT (tầng L2/L3 lo phần đó).
"""

import asyncio
import contextlib

import pytest

from src.config import get_settings


class ClientGia:
    """Đủ `MqttPort` cho `SimulatorRuntime.start()`: subscribe, publish, start, stop."""

    da_dung: list["ClientGia"] = []

    def __init__(self, url, *, client_id, username=None, password=None, **kwargs):  # noqa: ANN001, ANN003
        self.url = url
        self.client_id = client_id
        self.will = kwargs.get("will")
        self.clean_session = kwargs.get("clean_session")
        self.subs: list[str] = []
        self.published: list[str] = []
        self.started = False
        self.stopped = False
        ClientGia.da_dung.append(self)

    async def start(self, **_kwargs) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def subscribe(self, topic_filter, handler) -> None:  # noqa: ANN001
        self.subs.append(topic_filter)

    async def publish(self, topic, payload, *, qos=1, retain=False) -> None:  # noqa: ANN001
        self.published.append(topic)


@pytest.fixture
def ba_xe(monkeypatch):
    from src.vehicle_sim import __main__ as sim_main

    ClientGia.da_dung = []
    monkeypatch.setenv("VEHICLE_POOL_SIZE", "3")
    # Chu kỳ tự chạy tắt: test này nói về nối dây, không về chuyển động.
    monkeypatch.setenv("SIM_DRIVE_CYCLE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(sim_main, "AiomqttClient", ClientGia)
    yield sim_main
    get_settings.cache_clear()


async def _chay_roi_dung(sim_main) -> None:  # noqa: ANN001
    """Chạy `main()` cho tới lúc nó dựng xong rồi huỷ.

    Huỷ task là cách duy nhất chạm tới `stop` — nó là `asyncio.Event` cục bộ do signal
    handler đặt, mà test không gửi tín hiệu được. `CancelledError` đi vào `await
    stop.wait()` nên khối `finally` (tắt từng xe) vẫn chạy đủ.
    """
    task = asyncio.create_task(sim_main.main())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if len(ClientGia.da_dung) >= 3 and all(c.started for c in ClientGia.da_dung):
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_dung_dung_ba_xe_moi_xe_mot_ket_noi(ba_xe):
    await _chay_roi_dung(ba_xe)
    assert len(ClientGia.da_dung) == 3


async def test_client_id_phan_biet_tung_xe(ba_xe):
    """Trùng `client_id` là broker đá lần lượt từng client ra — đúng lỗi từng gặp khi
    chạy tay một xe ảo trong lúc container cũng đang chạy một cái."""
    await _chay_roi_dung(ba_xe)
    ids = [c.client_id for c in ClientGia.da_dung]
    assert len(set(ids)) == 3, ids
    assert ids[0] == f"vehicle-simulator-{get_settings().vehicle_id}"


async def test_moi_xe_mot_last_will_rieng(ba_xe):
    """Đây là lý do KHÔNG gộp chung kết nối: LWT gắn theo kết nối, gộp thì cả đội chỉ
    có một di chúc và K-1 chiếc chết trong im lặng."""
    await _chay_roi_dung(ba_xe)
    topics = [c.will.topic for c in ClientGia.da_dung]
    assert len(set(topics)) == 3, topics


async def test_tat_thi_dong_het_moi_ket_noi(ba_xe):
    await _chay_roi_dung(ba_xe)
    assert all(c.stopped for c in ClientGia.da_dung), "một kết nối sót lại là một xe ma"

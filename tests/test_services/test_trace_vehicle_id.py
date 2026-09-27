"""Trace ghi lượt này tác động lên **xe nào**.

Hôm nay cả hệ chỉ có một xe nên trường này là hằng và trông như thừa. Nó không
thừa: nguồn của nó là cột `sessions.vehicle_id`, đúng cột mà ADR-028 (pool xe ảo
theo phiên) ghi chiếc xe đã thuê vào. Nên khi pool vào, bảng đội xe của màn kỹ sư
phân biệt được các xe mà **không phải sửa gì** ở tầng quan sát.

Đó cũng là lý do không lấy thẳng `get_settings().vehicle_id` cho nhanh: cách đó
đúng hôm nay và sai lặng lẽ ngay ngày pool merge.
"""

from __future__ import annotations

import pytest

from src.api import session_state
from src.config import get_settings
from src.services.engineer_events import EngineerEventBus
from src.services.trace_collector import TraceCollector
from src.services.trace_store import TraceStore, set_trace_store


@pytest.fixture
def store():
    store = TraceStore(maxsize=8)
    set_trace_store(store)
    yield store
    session_state.reset()


async def _mo_trace(store, session_id: str, trace_id: str) -> None:
    collector = TraceCollector(store=store, bus=EngineerEventBus())
    await collector(
        {
            "type": "turn.accepted",
            "session_id": session_id,
            "turn_id": f"turn-{trace_id}",
            "trace_id": trace_id,
            "payload": {"status": "accepted", "input_mode": "text"},
        }
    )


async def test_lay_xe_tu_phien_trong_db(store):
    from tests.conftest import seed_test_user

    seed_test_user("usr_driver_01")
    phien = session_state.create_session("usr_driver_01", get_settings().vehicle_id)

    await _mo_trace(store, phien.session_id, "tr_co_xe")

    assert store.get("tr_co_xe").vehicle_id == get_settings().vehicle_id


async def test_phien_khong_co_that_thi_none_chu_khong_no(store):
    """Tầng quan sát không được làm hỏng một lượt. Trace thiếu `vehicle_id` vẫn
    dùng được; một exception ném ra từ listener thì không."""
    await _mo_trace(store, "ses_khong_co_that", "tr_khong_xe")

    assert store.get("tr_khong_xe").vehicle_id is None


async def test_hien_ra_o_traces_endpoint(engineer_client, store):
    from tests.conftest import seed_test_user

    seed_test_user("usr_driver_01")
    phien = session_state.create_session("usr_driver_01", get_settings().vehicle_id)
    await _mo_trace(store, phien.session_id, "tr_doc")

    data = (await engineer_client.get("/api/v1/traces/tr_doc")).json()["data"]

    assert data["vehicle_id"] == get_settings().vehicle_id

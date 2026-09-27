"""src/services/idempotency.py — kho idempotency (SQLite từ #46) cho POST /sessions và
POST /turns/text. Xem docs/api_spec.md mục "Required POST context": exact replay
trả nguyên response cũ; key trùng nhưng fingerprint khác là IDEMPOTENCY_CONFLICT.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.db import get_connection
from src.services import idempotency


@pytest.fixture(autouse=True)
def _reset_idempotency():
    idempotency.reset()
    yield
    idempotency.reset()


def test_lookup_returns_none_when_nothing_was_saved():
    store = idempotency.get_idempotency_store()
    assert store.lookup("usr_1", "POST /sessions", "key-1") is None


def test_save_then_lookup_returns_the_same_record():
    store = idempotency.get_idempotency_store()
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={"data": {"ok": True}})
    store.save("usr_1", "POST /sessions", "key-1", record)
    assert store.lookup("usr_1", "POST /sessions", "key-1") == record


def test_different_users_with_the_same_key_do_not_collide():
    store = idempotency.get_idempotency_store()
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={})
    store.save("usr_1", "POST /sessions", "key-1", record)
    assert store.lookup("usr_2", "POST /sessions", "key-1") is None


def test_different_routes_with_the_same_key_do_not_collide():
    store = idempotency.get_idempotency_store()
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={})
    store.save("usr_1", "POST /sessions", "key-1", record)
    assert store.lookup("usr_1", "POST /turns/text", "key-1") is None


def test_fingerprint_for_is_stable_regardless_of_key_order():
    a = idempotency.fingerprint_for({"vehicle_id": "v1", "input_mode": "text"})
    b = idempotency.fingerprint_for({"input_mode": "text", "vehicle_id": "v1"})
    assert a == b


def test_fingerprint_for_differs_for_different_content():
    a = idempotency.fingerprint_for({"text": "a"})
    b = idempotency.fingerprint_for({"text": "b"})
    assert a != b


def test_store_evicts_oldest_record_beyond_max_records():
    store = idempotency.get_idempotency_store()
    for index in range(idempotency.MAX_RECORDS + 10):
        store.save(
            "usr_1",
            "POST /sessions",
            f"key-{index}",
            idempotency.IdempotencyRecord(fingerprint="fp", status_code=200, body={}),
        )
    assert store.lookup("usr_1", "POST /sessions", "key-0") is None
    assert store.lookup("usr_1", "POST /sessions", f"key-{idempotency.MAX_RECORDS + 9}") is not None


# ---- begin/finish/abandon: đóng race giữa "kiểm tra" và "ghi" -------------------


async def test_begin_reserves_and_returns_none_when_nothing_exists():
    store = idempotency.get_idempotency_store()
    result = await store.begin("usr_1", "POST /sessions", "key-1", "fp1")
    assert result is None


async def test_begin_returns_the_existing_completed_record_without_reserving():
    store = idempotency.get_idempotency_store()
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={"ok": True})
    store.save("usr_1", "POST /sessions", "key-1", record)
    result = await store.begin("usr_1", "POST /sessions", "key-1", "fp1")
    assert result == record


async def test_begin_raises_in_progress_for_a_second_call_on_the_same_reserved_key():
    store = idempotency.get_idempotency_store()
    first = await store.begin("usr_1", "POST /sessions", "key-1", "fp1")
    assert first is None
    with pytest.raises(idempotency.IdempotencyInProgress):
        await store.begin("usr_1", "POST /sessions", "key-1", "fp1")


async def test_finish_clears_the_reservation_and_saves_the_record():
    store = idempotency.get_idempotency_store()
    await store.begin("usr_1", "POST /sessions", "key-1", "fp1")
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={"ok": True})
    await store.finish("usr_1", "POST /sessions", "key-1", record)
    assert store.lookup("usr_1", "POST /sessions", "key-1") == record
    # Sau finish, begin() phải trả bản ghi đã lưu, không còn raise IdempotencyInProgress.
    result = await store.begin("usr_1", "POST /sessions", "key-1", "fp1")
    assert result == record


async def test_abandon_clears_the_reservation_so_a_retry_can_begin_again():
    store = idempotency.get_idempotency_store()
    await store.begin("usr_1", "POST /sessions", "key-1", "fp1")
    await store.abandon("usr_1", "POST /sessions", "key-1")
    result = await store.begin("usr_1", "POST /sessions", "key-1", "fp1")
    assert result is None


async def test_concurrent_begin_calls_only_one_wins_the_reservation():
    """Tái hiện đúng race condition đã sửa: N request cùng (user, route, key) gửi
    gần như đồng thời — trước đây `lookup` rồi `save` rời rạc khiến tất cả đều thấy
    "chưa có" và đều chạy việc thật (vd. gọi trùng LangGraph agent). Với `begin()`
    dưới một lock duy nhất, đúng một request được đặt chỗ (trả None), số còn lại
    phải nhận IdempotencyInProgress — không được cùng trả None.
    """
    store = idempotency.get_idempotency_store()

    async def attempt():
        try:
            return await store.begin("usr_1", "POST /turns/text", "key-race", "fp1")
        except idempotency.IdempotencyInProgress:
            return "IN_PROGRESS"

    results = await asyncio.gather(*(attempt() for _ in range(10)))
    assert results.count(None) == 1
    assert results.count("IN_PROGRESS") == 9


async def test_begin_reclaims_a_reservation_that_is_older_than_the_ttl():
    """Lưới an toàn cho reservation bị bỏ hoang: nếu caller trước đó bị hủy/crash
    giữa chừng mà không kịp finish()/abandon(), begin() vẫn phải tự giải phóng
    được key đó sau `_PENDING_TTL_SECONDS`, không kẹt vĩnh viễn.
    """
    store = idempotency.get_idempotency_store()
    await store.begin("usr_1", "POST /turns/text", "key-stale", "fp1")

    # Đẩy lùi mốc đặt chỗ thay vì sửa dict `_pending` (đã biến mất từ #46, chỗ đặt
    # nay nằm trong bảng `idempotency_records` với `state='pending'`).
    stale_started_at = datetime.now(UTC) - timedelta(seconds=idempotency._PENDING_TTL_SECONDS + 1)  # noqa: SLF001
    connection = get_connection()
    connection.execute(
        "UPDATE idempotency_records SET created_at = ? WHERE user_id = 'usr_1' AND key = 'key-stale'",
        (stale_started_at.isoformat(),),
    )
    connection.commit()

    result = await store.begin("usr_1", "POST /turns/text", "key-stale", "fp2")
    assert result is None


async def test_begin_does_not_reclaim_a_reservation_still_within_the_ttl():
    store = idempotency.get_idempotency_store()
    await store.begin("usr_1", "POST /turns/text", "key-fresh", "fp1")
    with pytest.raises(idempotency.IdempotencyInProgress):
        await store.begin("usr_1", "POST /turns/text", "key-fresh", "fp1")


async def test_ca_ban_ghi_xong_lan_cho_dang_dat_deu_song_qua_restart(tmp_path):
    """Kịch bản phoenix chỉ ra ở PR #87, và là lý do bảng này có mặt trong #46.

    Persist approval mà để idempotency ở RAM thì một cú crash để lại approval bền
    vững với **zero** bản ghi idempotency: lần retry của client chạy lại việc thật
    và nhận `consumed` thay vì `approved` của lần đầu — phá đúng hợp đồng "exact
    replay returns exact prior response". Hai thứ phải cùng tầng bền vững.
    """
    from src.db import connect, ensure_schema

    db_path = tmp_path / "idem.sqlite3"
    first_connection = connect(db_path)
    ensure_schema(first_connection)
    first = idempotency.IdempotencyStore(connection=first_connection)
    record = idempotency.IdempotencyRecord(fingerprint="fp1", status_code=200, body={"approval_status": "approved"})
    await first.finish("usr_1", "POST /approvals", "key-xong", record)
    await first.begin("usr_1", "POST /approvals", "key-dang-cho", "fp2")
    first_connection.close()

    second = idempotency.IdempotencyStore(connection=connect(db_path))
    assert second.lookup("usr_1", "POST /approvals", "key-xong") == record, "replay sau restart phải trả response cũ"
    with pytest.raises(idempotency.IdempotencyInProgress):
        await second.begin("usr_1", "POST /approvals", "key-dang-cho", "fp2")


async def test_hai_tien_trinh_chi_mot_ben_gianh_duoc_cho_dat(tmp_path):
    """Bất biến "một chỗ đặt mỗi khoá" phải do **DB** phân xử, không phải `asyncio.Lock`.

    Phoenix chỉ ra ở PR #89: lock của store chỉ tuần tự hoá trong một event loop, nên
    hai tiến trình cùng khoá đều thấy "chưa ai đặt" rồi cả hai cùng chạy việc thật —
    đúng cái race mà `begin()` sinh ra để đóng.

    Hai store dưới đây có **hai lock riêng biệt** và hai kết nối riêng tới cùng một
    file. Không có đường nào để chúng biết về nhau ngoài chính cơ sở dữ liệu; nếu test
    này xanh thì phán quyết đến từ DB chứ không từ Python.
    """
    from src.db import connect, ensure_schema

    db_path = tmp_path / "idem-2p.sqlite3"
    first_connection = connect(db_path)
    ensure_schema(first_connection)
    tien_trinh_a = idempotency.IdempotencyStore(connection=first_connection)
    tien_trinh_b = idempotency.IdempotencyStore(connection=connect(db_path))
    assert tien_trinh_a._lock is not tien_trinh_b._lock  # noqa: SLF001 - chính là điều đang chứng minh

    assert await tien_trinh_a.begin("usr_1", "POST /turns/text", "key-dua", "fp") is None
    with pytest.raises(idempotency.IdempotencyInProgress):
        await tien_trinh_b.begin("usr_1", "POST /turns/text", "key-dua", "fp")

    rows = first_connection.execute("SELECT COUNT(*) FROM idempotency_records WHERE state = 'pending'").fetchone()[0]
    assert rows == 1, "chỗ đặt của tiến trình A bị tiến trình B ghi đè"


async def test_tien_trinh_thu_hai_nhan_lai_ket_qua_cu_thay_vi_409(tmp_path):
    """Bên thua không được nhận 409 nếu bên thắng đã xong: hợp đồng replay đòi đúng
    response cũ, và đó là toàn bộ lý do bảng này persist."""
    from src.db import connect, ensure_schema

    db_path = tmp_path / "idem-2p-done.sqlite3"
    first_connection = connect(db_path)
    ensure_schema(first_connection)
    tien_trinh_a = idempotency.IdempotencyStore(connection=first_connection)
    tien_trinh_b = idempotency.IdempotencyStore(connection=connect(db_path))

    record = idempotency.IdempotencyRecord(fingerprint="fp", status_code=200, body={"approval_status": "approved"})
    await tien_trinh_a.begin("usr_1", "POST /approvals", "key-xong", "fp")
    await tien_trinh_a.finish("usr_1", "POST /approvals", "key-xong", record)

    assert await tien_trinh_b.begin("usr_1", "POST /approvals", "key-xong", "fp") == record


async def test_cho_dat_qua_han_van_chiem_lai_duoc_tu_tien_trinh_khac(tmp_path):
    """Lưới an toàn phải sống sót qua ranh giới tiến trình, nếu không một tiến trình
    chết giữa chừng sẽ khoá cứng khoá đó với **mọi** tiến trình còn lại."""
    from src.db import connect, ensure_schema

    db_path = tmp_path / "idem-2p-stale.sqlite3"
    first_connection = connect(db_path)
    ensure_schema(first_connection)
    tien_trinh_a = idempotency.IdempotencyStore(connection=first_connection)
    tien_trinh_b = idempotency.IdempotencyStore(connection=connect(db_path))

    await tien_trinh_a.begin("usr_1", "POST /turns/text", "key-bo-hoang", "fp")
    stale = datetime.now(UTC) - timedelta(seconds=idempotency._PENDING_TTL_SECONDS + 1)  # noqa: SLF001
    first_connection.execute(
        "UPDATE idempotency_records SET created_at = ? WHERE key = 'key-bo-hoang'", (stale.isoformat(),)
    )
    first_connection.commit()

    assert await tien_trinh_b.begin("usr_1", "POST /turns/text", "key-bo-hoang", "fp2") is None

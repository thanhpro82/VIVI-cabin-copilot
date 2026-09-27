"""Store là chỗ giữ hai bất biến của `safety_and_hitl.md`: tối đa một pending mỗi
session, và approval dùng đúng một lần."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.agents.approval import (
    ApprovalAlreadyPending,
    ApprovalRecord,
    ApprovalStore,
    approval_id_for,
)
from src.db import connect

T0 = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """Bơm thời gian thay vì sleep — test hết hạn phải chạy trong micro giây."""

    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _record(
    digest: str = "d" * 64, session: str = "ses-1", clock: FakeClock | None = None, turn: str = "turn-1"
) -> ApprovalRecord:
    now = (clock or FakeClock()).now
    return ApprovalRecord(
        approval_id=approval_id_for(session, turn, digest),
        session_id=session,
        turn_id=turn,
        plan_id="plan-1",
        plan_digest=digest,
        approved_vehicle_state_version=1,
        created_at=now,
        expires_at=now + timedelta(seconds=30),
        prompt_text="Mở kính trước bên lái lên 30%. Bạn có đồng ý không?",
        steps_summary=({"tool": "set_window_position", "before": 0, "after": 30},),
    )


def test_approval_id_is_deterministic_for_the_same_session_turn_and_plan():
    """Tất định: LangGraph chạy lại thân node khi resume, nên id phải tái lập được."""
    assert approval_id_for("ses-1", "turn-1", "abc123") == approval_id_for("ses-1", "turn-1", "abc123")
    assert approval_id_for("ses-1", "turn-1", "abc123") != approval_id_for("ses-1", "turn-1", "abc124")


def test_two_sessions_with_the_same_plan_get_different_approval_ids():
    """Trước đây id chỉ băm `plan_digest` nên hai người cùng nói một câu ra chung một
    bản ghi: `create()` trả lại bản ghi của session kia, và quyết định của người này
    chạy lệnh của người kia."""
    digest = "d" * 64
    assert approval_id_for("ses-a", "turn-1", digest) != approval_id_for("ses-b", "turn-1", digest)


def test_two_turns_of_one_session_with_the_same_plan_get_different_approval_ids():
    """Cùng một câu nói ở hai lượt là hai lần xin phép khác nhau. Dùng chung id thì
    lượt sau nhặt phải bản ghi đã `consumed`/`expired` của lượt trước."""
    digest = "d" * 64
    assert approval_id_for("ses-a", "turn-1", digest) != approval_id_for("ses-a", "turn-2", digest)


def test_a_crafted_session_id_cannot_collide_with_another_session():
    """`session_id` đến từ body client nên là input không tin được: nối chuỗi bằng dấu
    phân cách thường sẽ để client tự dịch ranh giới field và trỏ vào id của phiên khác."""
    assert approval_id_for("ses-a", "turn-1\x1fturn-2", "abc") != approval_id_for("ses-a\x1fturn-1", "turn-2", "abc")


def test_create_then_get_roundtrip():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    assert store.get(record.approval_id).status == "pending"


def test_create_is_idempotent_for_the_same_approval():
    """Thân node chạy lại khi resume → `create` được gọi lần hai với cùng id.

    Nếu nó ném ở đây thì lượt resume tự chặn chính nó.
    """
    store = ApprovalStore(clock=FakeClock())
    first = store.create(_record())
    second = store.create(_record())
    assert first.approval_id == second.approval_id
    assert store.get(first.approval_id) is not None


def test_second_pending_in_same_session_is_rejected():
    """safety_and_hitl.md §Core invariants: tối đa một pending mỗi session."""
    store = ApprovalStore(clock=FakeClock())
    store.create(_record(digest="a" * 64))
    with pytest.raises(ApprovalAlreadyPending):
        store.create(_record(digest="b" * 64))


def test_other_session_may_have_its_own_pending():
    store = ApprovalStore(clock=FakeClock())
    store.create(_record(digest="a" * 64, session="ses-1"))
    other = store.create(_record(digest="b" * 64, session="ses-2"))
    assert other.status == "pending"


def test_expiry_is_detected_at_read_time():
    clock = FakeClock()
    store = ApprovalStore(clock=clock)
    record = store.create(_record(clock=clock))
    clock.advance(31)
    assert store.get(record.approval_id).status == "expired"


def test_expired_record_cannot_be_approved():
    clock = FakeClock()
    store = ApprovalStore(clock=clock)
    record = store.create(_record(clock=clock))
    clock.advance(31)
    assert store.decide(record.approval_id, approve=True).status == "expired"


def test_decide_is_idempotent_against_replay():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    assert store.decide(record.approval_id, approve=True).status == "approved"
    assert store.decide(record.approval_id, approve=False).status == "approved"


def test_consume_happens_once():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    store.decide(record.approval_id, approve=True)
    assert store.consume(record.approval_id).status == "consumed"
    assert store.consume(record.approval_id).status == "consumed"


def test_consume_refuses_a_record_that_was_never_approved():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    assert store.consume(record.approval_id) is None
    assert store.get(record.approval_id).status == "pending"


def test_expired_pending_frees_the_session_slot():
    """Hết hạn xong thì session phải xin được approval mới, không kẹt vĩnh viễn."""
    clock = FakeClock()
    store = ApprovalStore(clock=clock)
    store.create(_record(digest="a" * 64, clock=clock))
    clock.advance(31)
    assert store.create(_record(digest="b" * 64, clock=clock)).status == "pending"


def test_binding_fields_never_change_through_the_lifecycle():
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record())
    before = (record.session_id, record.plan_id, record.plan_digest, record.approved_vehicle_state_version)
    store.decide(record.approval_id, approve=True)
    store.consume(record.approval_id)
    after_record = store.get(record.approval_id)
    assert (
        after_record.session_id,
        after_record.plan_id,
        after_record.plan_digest,
        after_record.approved_vehicle_state_version,
    ) == before


def test_unknown_id_returns_none():
    store = ApprovalStore(clock=FakeClock())
    assert store.get("appr-khong-ton-tai") is None
    assert store.decide("appr-khong-ton-tai", approve=True) is None


def test_pending_index_is_cleared_on_every_terminal_transition():
    """Index pending phải sạch sau mọi lối ra, nếu không session kẹt vĩnh viễn.

    Bản trước tôi viết một test đo `_pending_scan_count` — biến đó không bao giờ
    được tăng ở đâu nên assert luôn đúng. Nó không thể fail, tức không bảo chứng gì.
    Test này kiểm thứ thật sự có thể vỡ: index để lại entry cũ.
    """
    clock = FakeClock()

    # reject
    store = ApprovalStore(clock=clock)
    record = store.create(_record(session="ses-r", clock=clock))
    store.decide(record.approval_id, approve=False)
    assert store.pending_for_session("ses-r") is None
    assert store.create(_record(digest="b" * 64, session="ses-r", clock=clock)).status == "pending"

    # consume
    store = ApprovalStore(clock=clock)
    record = store.create(_record(session="ses-c", clock=clock))
    store.decide(record.approval_id, approve=True)
    store.consume(record.approval_id)
    assert store.pending_for_session("ses-c") is None

    # invalidate
    store = ApprovalStore(clock=clock)
    record = store.create(_record(session="ses-i", clock=clock))
    store.invalidate(record.approval_id)
    assert store.pending_for_session("ses-i") is None

    # expire
    expiring = FakeClock()
    store = ApprovalStore(clock=expiring)
    store.create(_record(session="ses-e", clock=expiring))
    expiring.advance(31)
    assert store.pending_for_session("ses-e") is None


def test_pending_lookup_does_not_go_stale_after_eviction():
    """Bản ghi bị đuổi khỏi store thì tra pending không được trả lại nó nữa.

    Bản trước của test này đọc thẳng `store._pending_by_session` và `store._records`
    — hai dict đã biến mất khi store chuyển sang SQLite (#46). Cả một lớp bug giờ
    **không dựng lên được**: pending không còn là index riêng phải đồng bộ tay, nó
    là cột `status` của chính hàng dữ liệu, nên xoá hàng là xoá luôn tư cách pending.
    Test giữ lại phần có thể vỡ thật: sau khi chạm trần nhiều lần, mọi bản ghi mà
    `pending_for_session` trả về phải còn đọc được bằng `get`.
    """
    store = ApprovalStore(clock=FakeClock(), max_records=5)
    for index in range(40):
        record = store.create(_record(digest=f"{index:064d}", session=f"ses-{index}"))
        store.decide(record.approval_id, approve=False)
    for index in range(40):
        pending = store.pending_for_session(f"ses-{index}")
        assert pending is None or store.get(pending.approval_id) is not None


def test_pending_approval_survives_a_restart(tmp_path):
    """Tiêu chí nghiệm thu của #46: restart backend không được nuốt lượt đang chờ.

    Giả lập restart bằng cách đóng kết nối rồi mở lại trên **cùng file** — đúng thứ
    một tiến trình mới làm. Trước đợt này store là dict nên bước này mất sạch.
    """
    db_path = tmp_path / "approvals.sqlite3"
    first = ApprovalStore(clock=FakeClock(), connection=connect(db_path))
    record = first.create(_record(session="ses-restart"))
    first.close()

    second = ApprovalStore(clock=FakeClock(), connection=connect(db_path))
    revived = second.get(record.approval_id)
    assert revived is not None, "approval đang chờ biến mất sau restart"
    assert revived.status == "pending"
    assert revived.prompt_text == record.prompt_text
    assert revived.steps_summary == record.steps_summary
    assert revived.expires_at == record.expires_at
    assert second.pending_for_session("ses-restart").approval_id == record.approval_id
    second.close()


def test_second_pending_is_blocked_by_the_database_not_by_python():
    """Bất biến "tối đa một pending mỗi session" phải là ràng buộc của DB.

    Bỏ qua đường kiểm tra Python bằng cách ghi thẳng SQL: partial unique index phải
    tự chặn. Nếu nó không chặn thì hai tiến trình cùng ghi sẽ tạo được hai pending.
    """
    store = ApprovalStore(clock=FakeClock())
    store.create(_record(session="ses-dup"))
    with pytest.raises(sqlite3.IntegrityError):
        store._connection.execute(  # noqa: SLF001 - cố ý đi vòng qua tầng Python
            "INSERT INTO approvals (id, session_id, turn_id, plan_id, plan_digest,"
            " vehicle_state_version, status, expires_at, created_at)"
            " VALUES ('appr-khac', 'ses-dup', 'turn-2', 'plan-1', 'x', 1, 'pending', '', '')"
        )


def test_store_evicts_old_terminal_records():
    """Bản ghi đã chốt không cần giữ mãi — store phải có trần."""
    store = ApprovalStore(clock=FakeClock(), max_records=50)
    for index in range(120):
        record = store.create(_record(digest=f"{index:064d}", session=f"ses-{index}"))
        store.decide(record.approval_id, approve=False)
    assert store.record_count <= 50


def test_eviction_never_drops_a_pending_record():
    """Trần không được xoá mất bản ghi đang chờ — đó là mất một lượt của người dùng."""
    store = ApprovalStore(clock=FakeClock(), max_records=10)
    kept = store.create(_record(digest="f" * 64, session="ses-giu"))
    for index in range(60):
        record = store.create(_record(digest=f"{index:064d}", session=f"ses-{index}"))
        store.decide(record.approval_id, approve=False)
    assert store.get(kept.approval_id) is not None
    assert store.get(kept.approval_id).status == "pending"


def test_eviction_never_drops_pending_even_when_interleaved():
    """Eviction phải bỏ qua mọi bản ghi `pending`, kể cả khi chúng nằm xen kẽ.

    Bản trước của test này assert
    `all(r.status == "pending" for r in records if r.status == "pending")` — điều
    kiện lọc trùng điều kiện kiểm nên luôn đúng, không bảo chứng gì. Giờ nó giữ
    danh sách id pending và đòi **tất cả** phải còn sống sau khi chạm trần nhiều lần.
    """
    store = ApprovalStore(clock=FakeClock(), max_records=20)
    pending_ids: list[str] = []
    for index in range(100):
        record = store.create(_record(digest=f"{index:064d}", session=f"ses-{index}"))
        if index % 2 == 0:
            store.decide(record.approval_id, approve=False)
        else:
            pending_ids.append(record.approval_id)

    assert len(pending_ids) == 50
    survivors = [approval_id for approval_id in pending_ids if store.get(approval_id) is not None]
    assert len(survivors) == 50, f"eviction đã nuốt mất {50 - len(survivors)} bản ghi pending"


def test_forgetting_a_session_drops_its_approvals():
    """Session bị đuổi thì graph mất theo, approval của nó không resume được nữa.

    Giữ lại chỉ tổ chiếm chỗ trong trần của store.
    """
    store = ApprovalStore(clock=FakeClock())
    record = store.create(_record(digest="a" * 64, session="ses-bo-di"))
    other = store.create(_record(digest="b" * 64, session="ses-giu-lai"))

    store.forget_session("ses-bo-di")
    assert store.get(record.approval_id) is None
    assert store.get(other.approval_id) is not None
    assert store.pending_for_session("ses-bo-di") is None


def test_forgetting_an_unknown_session_is_a_no_op():
    store = ApprovalStore(clock=FakeClock())
    store.forget_session("ses-chua-tung-co")
    assert store.record_count == 0

"""Bản ghi và kho approval cho luồng HITL.

Hai bất biến của `docs/safety_and_hitl.md` được giữ ở đây, không ở tầng gọi:

- **Tối đa một pending mỗi session.** Kiểm tra nằm **trong** lock cùng với thao tác
  ghi, không phải check rồi mới act — nếu không thì hai lượt đồng thời cùng lọt.
- **Approval dùng đúng một lần.** `consume()` chỉ đi từ `approved` sang `consumed`.

`approval_id` suy ra **tất định** từ `plan_digest` vì LangGraph chạy lại thân node từ
đầu khi resume: `create()` sẽ bị gọi lần thứ hai cho cùng một approval, và nó phải trả
lại bản ghi cũ chứ không được ném.

Hết hạn được phát hiện tại **thời điểm đọc** (`get`/`decide` tự CAS `pending → expired`),
không cần worker nền. Giới hạn của cách này ghi trong spec mục "Timeout".
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.db import connect, ensure_schema

ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "invalidated", "consumed"]

#: Trạng thái đã chốt — không đổi được nữa, mọi thao tác sau chỉ đọc.
_TERMINAL: frozenset[str] = frozenset({"rejected", "expired", "invalidated", "consumed"})


class ApprovalAlreadyPending(Exception):  # noqa: N818 - tên khớp mã lỗi APPROVAL_ALREADY_PENDING trong api_spec.md
    """Session đã có một approval khác đang chờ. `safety_and_hitl.md` cho tối đa một."""


def approval_id_for(session_id: str, turn_id: str, plan_digest: str) -> str:
    """Id tất định theo **phiên + lượt + nội dung plan**. Sửa bất kỳ cái nào là ra id khác.

    Tất định là bắt buộc: LangGraph chạy lại thân node từ đầu khi resume nên id phải
    tái lập được từ state đã checkpoint.

    `plan_digest` một mình là **không đủ** để định danh một lần xin phép. Digest gồm
    `vehicle_state_version` nhưng không gồm lượt, mà lượt bị từ chối thì không đổi
    state — nên câu lệnh bị từ chối một lần sẽ băm ra đúng id cũ ở lượt sau, `create()`
    trả lại bản ghi `rejected`, và người dùng kẹt với câu lệnh đó. Đưa `turn_id` vào
    khiến mỗi lần hỏi là một bản ghi riêng.

    `session_id` đến từ body client nên là input **không tin được**: nối chuỗi bằng dấu
    phân cách thường sẽ để client tự dịch ranh giới field (`"a", "b\\x1fc"` và
    `"a\\x1fb", "c"` ra cùng một chuỗi) và trỏ vào id của phiên khác. Vì vậy mỗi thành
    phần được **tiền tố bằng độ dài**, không phải chỉ ngăn bằng ký tự.
    """
    identity = f"{len(session_id)}:{session_id}|{len(turn_id)}:{turn_id}|{plan_digest}"
    return f"appr-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


class ApprovalRecord(BaseModel):
    """Bản ghi approval.

    Pydantic khoá cả model chứ không khoá từng field, nên không dùng `frozen`. Bất
    biến giữ bằng quy ước có test: chỉ `ApprovalStore` được ghi, và chỉ ghi
    `status`/`decided_at`.
    """

    model_config = ConfigDict(extra="forbid")

    approval_id: str
    session_id: str
    turn_id: str
    plan_id: str
    plan_digest: str
    approved_vehicle_state_version: int
    created_at: datetime
    expires_at: datetime
    prompt_text: str
    steps_summary: tuple[dict[str, Any], ...] = ()
    status: ApprovalStatus = "pending"
    decided_at: datetime | None = None


def _row_to_record(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=row["id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        plan_id=row["plan_id"],
        plan_digest=row["plan_digest"],
        approved_vehicle_state_version=row["vehicle_state_version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        prompt_text=row["prompt_text"],
        steps_summary=tuple(json.loads(row["steps_summary_json"])),
        status=row["status"],
        decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
    )


class ApprovalStore:
    """Kho SQLite. Pending sống qua restart — issue #46 đóng đúng chỗ này.

    Mặc định mỗi instance mở một DB `:memory:` riêng, nên test vẫn cô lập và nhanh
    y như hồi còn dùng dict; chỉ singleton của production mới truyền vào kết nối
    trỏ file. Vẫn `threading.Lock` + `check_same_thread=False`, không đổi sang async
    trong đợt này — đổi là lan sang graph và HITL.

    Không còn index pending riêng trong Python. Nó là partial unique index của DB
    (`approvals_one_pending_per_session`), nên bất biến "tối đa một pending mỗi
    session" **mạnh lên**: hai tiến trình cùng ghi cũng không tạo nổi hai pending,
    thứ mà một dict không bao giờ chặn được.
    """

    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
        max_records: int = 512,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._connection = connection if connection is not None else connect(":memory:")
        ensure_schema(self._connection)
        self._max_records = max_records

    @property
    def record_count(self) -> int:
        with self._lock:
            return int(self._connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0])

    def close(self) -> None:
        """Đóng kết nối. Production không gọi (store sống bằng tuổi tiến trình);
        test giả lập restart thì cần."""
        with self._lock:
            self._connection.close()

    def reset(self) -> None:
        """Chỉ dùng trong test — xoá sạch bảng giữa các case."""
        with self._lock:
            self._connection.execute("DELETE FROM approvals")
            self._connection.commit()

    def now(self) -> datetime:
        """Đồng hồ của store. Node phải dùng chung, nếu không test bơm giờ sẽ lệch."""
        return self._clock()

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        """Tạo, hoặc trả lại bản ghi cũ nếu đúng `approval_id` đó đã tồn tại.

        Idempotent là bắt buộc: LangGraph chạy lại thân node khi resume nên hàm này
        nhận đúng cùng một bản ghi hai lần cho một lượt.
        """
        with self._lock:
            existing = self._fetch_locked(record.approval_id)
            if existing is not None:
                return existing
            blocking = self._pending_locked(record.session_id)
            if blocking is not None:
                raise ApprovalAlreadyPending(
                    f"session {record.session_id} đã có approval {blocking.approval_id} đang chờ"
                )
            try:
                self._connection.execute(
                    "INSERT INTO approvals (id, session_id, turn_id, plan_id, plan_digest,"
                    " vehicle_state_version, status, expires_at, created_at, decided_at,"
                    " prompt_text, steps_summary_json)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.approval_id,
                        record.session_id,
                        record.turn_id,
                        record.plan_id,
                        record.plan_digest,
                        record.approved_vehicle_state_version,
                        record.status,
                        record.expires_at.isoformat(),
                        record.created_at.isoformat(),
                        record.decided_at.isoformat() if record.decided_at else None,
                        record.prompt_text,
                        json.dumps(list(record.steps_summary)),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # Partial unique index bắt được cái mà kiểm tra Python ở trên bỏ lọt:
                # một tiến trình khác vừa chèn pending cho cùng session.
                self._connection.rollback()
                raise ApprovalAlreadyPending(f"session {record.session_id} đã có approval đang chờ") from exc
            self._evict_locked()
            self._connection.commit()
            return record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._expire_if_due_locked(self._fetch_locked(approval_id))

    def pending_for_session(self, session_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._pending_locked(session_id)

    def decide(self, approval_id: str, approve: bool) -> ApprovalRecord | None:
        """Chốt approve/reject. Gọi lại trên bản ghi đã chốt thì trả nguyên trạng thái."""
        with self._lock:
            record = self._expire_if_due_locked(self._fetch_locked(approval_id))
            if record is None or record.status != "pending":
                return record
            return self._transition_locked(record, "approved" if approve else "rejected")

    def consume(self, approval_id: str) -> ApprovalRecord | None:
        """`approved → consumed`. Trả `None` nếu bản ghi chưa từng được duyệt."""
        with self._lock:
            record = self._expire_if_due_locked(self._fetch_locked(approval_id))
            if record is None:
                return None
            if record.status == "consumed":
                return record
            if record.status != "approved":
                return None
            return self._transition_locked(record, "consumed")

    def invalidate(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            record = self._fetch_locked(approval_id)
            if record is None or record.status in _TERMINAL:
                return record
            return self._transition_locked(record, "invalidated")

    # ---- nội bộ: mọi hàm dưới đây giả định caller đang giữ lock ----------

    def _fetch_locked(self, approval_id: str) -> ApprovalRecord | None:
        row = self._connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def _pending_locked(self, session_id: str) -> ApprovalRecord | None:
        """Pending không còn là dict phải đồng bộ tay — nó là cột `status` của hàng.

        Partial unique index bảo đảm truy vấn này trả tối đa một hàng, nên không có
        chuyện quét tuyến tính toàn store như hồi chưa có index Python.
        """
        row = self._connection.execute(
            "SELECT * FROM approvals WHERE session_id = ? AND status = 'pending'", (session_id,)
        ).fetchone()
        if row is None:
            return None
        fresh = self._expire_if_due_locked(_row_to_record(row))
        return fresh if fresh is not None and fresh.status == "pending" else None

    def _expire_if_due_locked(self, record: ApprovalRecord | None) -> ApprovalRecord | None:
        if record is None or record.status != "pending" or self._clock() < record.expires_at:
            return record
        return self._transition_locked(record, "expired")

    def _transition_locked(self, record: ApprovalRecord, status: ApprovalStatus) -> ApprovalRecord:
        updated = record.model_copy(update={"status": status, "decided_at": self._clock()})
        self._connection.execute(
            "UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?",
            (updated.status, updated.decided_at.isoformat(), updated.approval_id),
        )
        self._connection.commit()
        return updated

    def _evict_locked(self) -> None:
        """Giữ store dưới trần bằng cách đuổi bản ghi **đã chốt** cũ nhất.

        Không bao giờ đuổi bản ghi `pending`: mất nó là mất một lượt của người dùng
        đang chờ xác nhận. Nếu toàn bộ store đều là pending thì để nó vượt trần —
        hiếm, và thà tốn chỗ còn hơn nuốt mất một lượt.

        "Cũ nhất" đo bằng `rowid` (thứ tự chèn), không bằng `created_at`: đồng hồ bơm
        trong test có thể đứng yên nên nhiều bản ghi trùng `created_at`, và thứ tự
        chèn mới đúng là thứ mà `OrderedDict` ngày trước dùng.
        """
        excess = int(self._connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]) - self._max_records
        if excess <= 0:
            return
        self._connection.execute(
            "DELETE FROM approvals WHERE id IN ("
            "  SELECT id FROM approvals WHERE status != 'pending' ORDER BY rowid LIMIT ?"
            ")",
            (excess,),
        )

    def forget_session(self, session_id: str) -> None:
        """Xoá mọi approval của một session.

        Dùng khi session bị đuổi khỏi bộ nhớ ở tầng API: graph mất theo thì approval
        của nó không resume được nữa, giữ lại chỉ tổ chiếm chỗ trong trần.
        """
        with self._lock:
            self._connection.execute("DELETE FROM approvals WHERE session_id = ?", (session_id,))
            self._connection.commit()

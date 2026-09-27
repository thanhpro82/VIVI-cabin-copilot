"""Kho idempotency (SQLite từ #46) cho POST /sessions, /turns/text và /approvals.

docs/api_spec.md mục "Required POST context": "an exact replay by the same
principal and request fingerprint returns the exact prior HTTP response. Reusing
the key with a different fingerprint returns IDEMPOTENCY_CONFLICT." Khoá theo
`(user_id, route, idempotency_key)` — không chỉ `key` — vì `idempotency_key` do
client tự chọn và hai user/route trùng chuỗi key là bình thường.

`lookup`/`save` là hai thao tác dict rời rạc — dùng trực tiếp ở route handler thì
giữa lúc `lookup` báo "chưa có" và `save` chạy xong có một khoảng hở thật (route
handler `await graph.ainvoke(...)` ở giữa), hai request trùng key gửi gần như
đồng thời đều thấy `lookup` trả `None` và cả hai đều chạy việc thật — tức
idempotency key không chặn được đúng thứ nó sinh ra để chặn. `begin`/`finish`/
`abandon` đóng khoảng hở đó bằng một `asyncio.Lock` duy nhất bọc quanh cả bước
kiểm tra lẫn bước "đặt chỗ" — cùng nguyên tắc `ApprovalStore.create()`
(`src/agents/approval.py`) đã áp dụng: kiểm tra phải nằm TRONG lock cùng với thao
tác ghi, không phải kiểm tra rồi mới ghi.

Nhưng `asyncio.Lock` chỉ tuần tự hoá **trong một event loop**, nên nó không đóng nổi
khoảng hở đó giữa hai tiến trình — phoenix chỉ ra ở PR #89. Vì vậy bước "đặt chỗ" nay
là **một câu lệnh SQL duy nhất** (`_CLAIM_SQL`) và chính DB phân xử qua `rowcount`;
lock giữ lại chỉ để bớt tranh chấp trong tiến trình. Cùng nước đi với partial unique
index của `approvals`: bất biến nằm ở tầng dữ liệu, không ở tầng Python.

`_pending` không có TTL thì một chỗ đã đặt mà không bao giờ `finish()`/`abandon()`
được (client bị hủy kết nối/timeout đúng lúc route handler đang await, hoặc
process chết giữa chừng) sẽ kẹt vĩnh viễn: vừa rò bộ nhớ, vừa khoá cứng đúng
`idempotency_key` đó cho user đó mãi mãi. `_PENDING_TTL_SECONDS` là lưới an toàn
cuối — quá hạn thì `begin()` coi chỗ cũ là bỏ hoang, cho request mới chiếm lại.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.db import get_connection

MAX_RECORDS = 512

#: Một lượt S1/S2 thật không bao giờ nên chạy lâu hơn ngưỡng này — vượt quá nghĩa
#: là caller trước đó đã bị hủy/crash giữa chừng mà không kịp finish()/abandon().
#:
#: Đo bằng **đồng hồ tường** chứ không phải `time.monotonic()` như bản dict: mốc đặt
#: chỗ nay nằm trên đĩa và phải so sánh được với một tiến trình khác, mà monotonic
#: không có ý nghĩa gì qua ranh giới tiến trình. Cái giá là một cú nhảy NTP trong
#: cửa sổ 60 s có thể làm chỗ đặt hết hạn sớm hoặc muộn — chấp nhận được ở đây, vì
#: hệ quả xấu nhất là một request thật chạy lại, đúng thứ TTL này vốn cho phép.
_PENDING_TTL_SECONDS = 60.0
_PENDING_TTL = timedelta(seconds=_PENDING_TTL_SECONDS)


def _iso(moment: datetime) -> str:
    """ISO-8601 UTC **luôn đủ micro giây**.

    Bề rộng cố định là điều kiện để so sánh `created_at` bằng chuỗi ngay trong SQL
    (xem `_CLAIM_SQL`). `isoformat()` trần bỏ phần micro giây khi nó bằng 0, và một
    chuỗi hụt phần đó sẽ so sai với chuỗi có nó ở đúng cùng một giây.
    """
    return moment.isoformat(timespec="microseconds")


def _now_iso() -> str:
    return _iso(datetime.now(UTC))


#: Đặt chỗ **nguyên tử trong một câu lệnh**, để chính DB phân xử chứ không phải một
#: lock trong tiến trình.
#:
#: `asyncio.Lock` của store chỉ tuần tự hoá trong một event loop. Bản trước SELECT rồi
#: mới INSERT, nên hai tiến trình cùng khoá đều thấy "chưa ai đặt", và `DO UPDATE` vô
#: điều kiện khiến tiến trình sau **ghi đè** chỗ của tiến trình trước: cả hai cùng nhận
#: `None` và cùng chạy việc thật — đúng cái race mà `begin()` sinh ra để đóng.
#:
#: Mệnh đề `WHERE` khiến DB chỉ nhường chỗ khi hàng cũ là một pending **đã quá hạn**.
#: `rowcount` vì thế là phán quyết: 1 = đã giữ được chỗ, 0 = người khác đang giữ (hoặc
#: hàng đã `done`, và khi đó không được ghi đè lên kết quả cũ).
#:
#: Cùng nước đi với partial unique index của `approvals`: bất biến nằm ở tầng dữ liệu.
_CLAIM_SQL = (
    "INSERT INTO idempotency_records (user_id, route, key, fingerprint, state, created_at)"
    " VALUES (?, ?, ?, ?, 'pending', ?)"
    " ON CONFLICT (user_id, route, key) DO UPDATE SET"
    "   fingerprint = excluded.fingerprint, state = 'pending', status_code = NULL,"
    "   body_json = NULL, created_at = excluded.created_at"
    " WHERE idempotency_records.state = 'pending'"
    "   AND idempotency_records.created_at < ?"
)


class IdempotencyInProgress(Exception):  # noqa: N818 - tên khớp mã lỗi IDEMPOTENCY_CONFLICT phía route
    """Một request khác cùng `(user_id, route, key)` và cùng fingerprint đang chạy dở."""


@dataclass(frozen=True)
class IdempotencyRecord:
    fingerprint: str
    status_code: int
    body: dict[str, Any]


def fingerprint_for(body: dict[str, Any]) -> str:
    """Băm nội dung request đã chuẩn hoá — phát hiện tái dùng key với nội dung khác."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyStore:
    """Kho SQLite. Cả bản ghi đã xong **lẫn** chỗ đang đặt đều bền.

    Chỗ đang đặt (`state='pending'`) persist là có chủ đích, không phải tiện tay:
    persist approval mà để idempotency ở RAM thì một cú crash sẽ để lại approval bền
    vững với **zero** bản ghi idempotency, và lần retry của client nhận `consumed`
    thay vì `approved` của lần đầu — phá đúng hợp đồng "exact replay returns exact
    prior response" (`api_spec.md:50`). Hai thứ phải cùng tầng bền vững.
    """

    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self._connection = connection if connection is not None else get_connection()
        self._lock = asyncio.Lock()

    def lookup(self, user_id: str, route: str, key: str) -> IdempotencyRecord | None:
        row = self._connection.execute(
            "SELECT * FROM idempotency_records WHERE user_id = ? AND route = ? AND key = ? AND state = 'done'",
            (user_id, route, key),
        ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            fingerprint=row["fingerprint"], status_code=row["status_code"], body=json.loads(row["body_json"])
        )

    def save(self, user_id: str, route: str, key: str, record: IdempotencyRecord) -> None:
        self._write_done(user_id, route, key, record)

    def _write_done(self, user_id: str, route: str, key: str, record: IdempotencyRecord) -> None:
        self._connection.execute(
            "INSERT INTO idempotency_records (user_id, route, key, fingerprint, state, status_code,"
            " body_json, created_at) VALUES (?, ?, ?, ?, 'done', ?, ?, ?)"
            " ON CONFLICT (user_id, route, key) DO UPDATE SET"
            " fingerprint = excluded.fingerprint, state = 'done', status_code = excluded.status_code,"
            " body_json = excluded.body_json, created_at = excluded.created_at",
            (
                user_id,
                route,
                key,
                record.fingerprint,
                record.status_code,
                json.dumps(record.body),
                _now_iso(),
            ),
        )
        self._evict()
        self._connection.commit()

    def _evict(self) -> None:
        """Trần chỉ đếm bản ghi **đã xong** — hệt như bản dict, nơi chỗ đang đặt nằm
        ở `_pending` riêng và không bao giờ bị đuổi.

        "Cũ nhất" đo bằng `rowid` (thứ tự chèn) chứ không bằng `created_at`: cùng lý
        do với `ApprovalStore._evict_locked` — nhiều bản ghi có thể trùng mốc thời gian.
        """
        excess = (
            int(self._connection.execute("SELECT COUNT(*) FROM idempotency_records WHERE state = 'done'").fetchone()[0])
            - MAX_RECORDS
        )
        if excess <= 0:
            return
        self._connection.execute(
            "DELETE FROM idempotency_records WHERE rowid IN ("
            "  SELECT rowid FROM idempotency_records WHERE state = 'done' ORDER BY rowid LIMIT ?"
            ")",
            (excess,),
        )

    async def begin(self, user_id: str, route: str, key: str, fingerprint: str) -> IdempotencyRecord | None:
        """Kiểm tra và "đặt chỗ" nguyên tử dưới cùng một lock.

        Trả về bản ghi đã hoàn tất nếu có (caller tự so `fingerprint` như cũ: khớp
        thì replay, lệch thì 409). Trả `None` nếu vừa đặt chỗ thành công cho
        `fingerprint` này — caller BẮT BUỘC gọi `finish()` khi xong hoặc
        `abandon()` khi lỗi, nếu không request sau cùng key sẽ kẹt ở
        `IdempotencyInProgress` tối đa `_PENDING_TTL_SECONDS`. Raise
        `IdempotencyInProgress` nếu một request khác cùng fingerprint đang chạy dở
        (chưa `finish`/`abandon`, và chưa quá hạn) — caller nên trả 409
        `retryable=true`, không phải chạy việc thật lần nữa.
        """
        async with self._lock:
            cache_key = (user_id, route, key)
            done = self.lookup(user_id, route, key)
            if done is not None:
                return done
            # Chỗ cũ quá hạn thì được chiếm lại: caller trước đó bị hủy/crash giữa
            # chừng mà không kịp finish()/abandon(). Quyết định đó nằm trong mệnh đề
            # `WHERE` của `_CLAIM_SQL`, không nằm ở Python — xem docstring của nó.
            cutoff = _iso(datetime.now(UTC) - _PENDING_TTL)
            claimed = self._connection.execute(
                _CLAIM_SQL, (user_id, route, key, fingerprint, _now_iso(), cutoff)
            ).rowcount
            self._connection.commit()
            if claimed:
                return None
            # DB từ chối. Hai khả năng: người khác đang giữ chỗ còn hạn, hoặc họ vừa
            # `finish()` xong ngay giữa hai câu lệnh trên. Đọc lại để phân biệt —
            # trả bản ghi cũ vẫn đúng hợp đồng replay hơn là ném 409.
            settled = self.lookup(user_id, route, key)
            if settled is not None:
                return settled
            raise IdempotencyInProgress(f"{cache_key} đang được xử lý")

    async def finish(self, user_id: str, route: str, key: str, record: IdempotencyRecord) -> None:
        async with self._lock:
            self._write_done(user_id, route, key, record)

    async def abandon(self, user_id: str, route: str, key: str) -> None:
        """Bỏ chỗ đã đặt — dùng khi việc thật lỗi giữa chừng, để lần thử lại sau
        (idempotency key khác, hoặc cùng key sau khi client nhận lỗi) không kẹt
        mãi ở `IdempotencyInProgress`."""
        async with self._lock:
            self._connection.execute(
                "DELETE FROM idempotency_records WHERE user_id = ? AND route = ? AND key = ? AND state = 'pending'",
                (user_id, route, key),
            )
            self._connection.commit()

    def reset(self) -> None:
        """Chỉ dùng trong test."""
        self._connection.execute("DELETE FROM idempotency_records")
        self._connection.commit()


#: Khởi tạo **lười**: `IdempotencyStore()` mặc định mở `get_connection()`, nên dựng nó
#: ở mức module làm một `DATABASE_URL` sai hỏng luôn `import src.main` (issue #93).
#: Cùng lý do và cùng cách chữa với `_STORE` của `src/api/session_state.py`.
_STORE: IdempotencyStore | None = None


def get_idempotency_store() -> IdempotencyStore:
    global _STORE
    if _STORE is None:
        _STORE = IdempotencyStore()
    return _STORE


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    get_idempotency_store().reset()

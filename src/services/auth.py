"""Auth demo: user đọc từ bảng `users` (SQLite), token opaque ngẫu nhiên trong RAM.

Không JWT: không có hạ tầng ký nào khác trong repo và không cần thiết cho demo
một-process trên PC. `docs/api_spec.md` gọi đây là "local demo authentication".

**Token cố ý ở RAM** (quyết định 2026-08-12, issue #46): `docs/data_model.md` không
thiết kế bảng nào cho token, và ghi token xuống đĩa là thêm một bề mặt lộ bí mật cho
một thứ vốn ngắn hạn. Restart vẫn bắt đăng nhập lại — nhưng không còn *mất user*,
đó mới là thứ #46 đóng.

Hệ quả của lựa chọn đó là **restart backend làm chết mọi token còn hạn**, và client
không có cách nào tự biết: `expires_at` nó đang giữ vẫn còn xa. Vì vậy `resolve_with_reason`
tách "hết hạn" khỏi "không còn tồn tại" — `src/api/auth_deps.py` và `src/api/ws.py`
dùng nó để nói đúng lý do thay vì một câu chung chung mà không ai debug được.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from src.config import get_settings
from src.db import get_connection, verify_password

Role = Literal["driver", "engineer"]

#: Vì sao `resolve()` trả `None`. `"unknown"` gần như luôn có nghĩa "backend vừa
#: restart" ở P0 — chỉ có đúng một nguồn khác là bị đẩy khỏi cap `MAX_TOKENS`.
ResolveReason = Literal["ok", "expired", "unknown"]

#: Trần token giữ trong bộ nhớ — cùng kiểu LRU với session_state.MAX_SESSIONS.
MAX_TOKENS = 256


@dataclass(frozen=True)
class TokenRecord:
    token: str
    user_id: str
    role: Role
    display_name: str
    expires_at: datetime


class AuthStore:
    """Kho token in-memory, LRU-capped ở `MAX_TOKENS`."""

    def __init__(self) -> None:
        self._tokens: OrderedDict[str, TokenRecord] = OrderedDict()

    def login(self, email: str, password: str) -> TokenRecord | None:
        row = get_connection().execute("SELECT * FROM users WHERE email = ? AND active = 1", (email,)).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        ttl_seconds = get_settings().auth_token_ttl_seconds
        record = TokenRecord(
            token=token,
            user_id=row["id"],
            role=row["role"],
            display_name=row["display_name"],
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        self._tokens[token] = record
        self._tokens.move_to_end(token)
        while len(self._tokens) > MAX_TOKENS:
            self._tokens.popitem(last=False)
        return record

    def resolve(self, token: str) -> TokenRecord | None:
        record, _ = self.resolve_with_reason(token)
        return record

    def resolve_with_reason(self, token: str) -> tuple[TokenRecord | None, ResolveReason]:
        """Như `resolve()` nhưng nói thêm **vì sao** token không dùng được.

        `move_to_end` ở nhánh hợp lệ là thứ biến cap `MAX_TOKENS` thành LRU thật.
        Trước đây `move_to_end` chỉ chạy lúc login, nên thứ tự trong `OrderedDict`
        là thứ tự *cấp phát* — tức FIFO: người đăng nhập sớm nhất bị đá trước dù
        đang dùng liên tục, còn token cấp lúc nãy và không ai đụng tới thì sống.
        Đúng ngược với ý định ghi ở docstring của lớp.
        """
        record = self._tokens.get(token)
        if record is None:
            return None, "unknown"
        if datetime.now(UTC) >= record.expires_at:
            del self._tokens[token]
            return None, "expired"
        self._tokens.move_to_end(token)
        return record, "ok"

    def reset(self) -> None:
        """Chỉ dùng trong test."""
        self._tokens.clear()


_STORE = AuthStore()


def get_auth_store() -> AuthStore:
    return _STORE


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    _STORE.reset()

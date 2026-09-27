"""src/services/auth.py — demo user registry và opaque bearer token store.

Chỉ hai tài khoản demo: driver.demo@example.com / DemoDriver123! (driver) và
engineer.demo@example.com / DemoEngineer123! (engineer). Xem
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md mục "Demo users and
tokens".
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.services import auth


@pytest.fixture(autouse=True)
def _reset_auth():
    auth.reset()
    yield
    auth.reset()


def test_login_with_valid_driver_credentials_issues_a_token():
    record = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    assert record is not None
    assert record.user_id == "usr_driver_01"
    assert record.role == "driver"
    assert record.display_name == "Demo Driver"
    assert record.token


def test_login_with_valid_engineer_credentials_issues_a_token():
    record = auth.get_auth_store().login("engineer.demo@example.com", "DemoEngineer123!")
    assert record is not None
    assert record.user_id == "usr_engineer_01"
    assert record.role == "engineer"


def test_login_with_wrong_password_returns_none():
    assert auth.get_auth_store().login("driver.demo@example.com", "wrong-password") is None


def test_login_with_unknown_email_returns_none():
    assert auth.get_auth_store().login("nobody@example.com", "whatever") is None


def test_two_logins_issue_different_tokens():
    first = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    second = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    assert first.token != second.token


def test_resolve_returns_the_record_for_a_valid_token():
    issued = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    resolved = auth.get_auth_store().resolve(issued.token)
    assert resolved == issued


def test_resolve_returns_none_for_an_unknown_token():
    assert auth.get_auth_store().resolve("not-a-real-token") is None


def test_resolve_returns_none_for_an_expired_token():
    store = auth.get_auth_store()
    issued = store.login("driver.demo@example.com", "DemoDriver123!")
    expired = issued.__class__(
        token=issued.token,
        user_id=issued.user_id,
        role=issued.role,
        display_name=issued.display_name,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    store._tokens[issued.token] = expired  # noqa: SLF001 - test helper, forces expiry
    assert store.resolve(issued.token) is None


def test_resolve_with_reason_distinguishes_expired_from_unknown():
    """Hai ca này trước đây không phân biệt được từ ngoài, và đó chính là lý do
    lỗi "token không hợp lệ hoặc đã hết hạn" bị chẩn đoán nhầm: ca thực tế hay gặp
    nhất là restart backend (token biến mất → `unknown`), không phải hết 12 h."""
    store = auth.get_auth_store()
    issued = store.login("driver.demo@example.com", "DemoDriver123!")

    assert store.resolve_with_reason(issued.token) == (issued, "ok")
    assert store.resolve_with_reason("not-a-real-token") == (None, "unknown")

    store._tokens[issued.token] = issued.__class__(  # noqa: SLF001 - test helper, forces expiry
        token=issued.token,
        user_id=issued.user_id,
        role=issued.role,
        display_name=issued.display_name,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert store.resolve_with_reason(issued.token) == (None, "expired")


def test_a_token_in_active_use_survives_eviction_at_the_cap():
    """Cap `MAX_TOKENS` phải là LRU theo lần **dùng** gần nhất, không phải FIFO theo
    lần **cấp**.

    Trước khi `resolve()` gọi `move_to_end`, thứ tự trong OrderedDict là thứ tự cấp
    phát, nên người đăng nhập sớm nhất bị đá trước dù đang dùng liên tục — biểu hiện
    ra ngoài đúng bằng thông điệp "token không hợp lệ", không có tín hiệu nào khác.
    """
    store = auth.get_auth_store()
    veteran = store.login("driver.demo@example.com", "DemoDriver123!")

    # Lấp đầy tới đúng trần, chạm token cũ sau mỗi lần cấp để nó luôn là "vừa dùng".
    for _ in range(auth.MAX_TOKENS - 1):
        store.login("engineer.demo@example.com", "DemoEngineer123!")
        assert store.resolve(veteran.token) is not None

    # Token thứ MAX_TOKENS + 1: phải đá đứa lâu-không-dùng-nhất, không phải `veteran`.
    store.login("engineer.demo@example.com", "DemoEngineer123!")
    assert len(store._tokens) == auth.MAX_TOKENS  # noqa: SLF001 - kiểm trần thật sự có hiệu lực
    assert store.resolve(veteran.token) is not None

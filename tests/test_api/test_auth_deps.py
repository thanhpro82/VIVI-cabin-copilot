"""src/api/auth_deps.py — dependency FastAPI cho auth/RBAC/request-context.

Gọi trực tiếp như hàm async thường: FastAPI chỉ diễn giải `Header(...)` khi chạy
qua dependency-injection thật; gọi trực tiếp thì truyền giá trị thường vào keyword
argument là đủ. `request` dùng một Starlette `Request` tối giản dựng từ scope —
chỉ cần đọc header (`resolve_trace_id` chỉ gọi `request.headers.get(...)`), không
cần một ASGI app thật.
"""

from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request

from src.api import auth_deps
from src.api.errors import ApiError
from src.services import auth


@pytest.fixture(autouse=True)
def _reset_auth():
    auth.reset()
    yield
    auth.reset()


def _request(headers: dict[str, str] | None = None) -> Request:
    headers = headers or {}
    scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


async def test_get_current_user_with_a_valid_bearer_token_returns_the_user():
    issued = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    assert user.user_id == "usr_driver_01"
    assert user.role == "driver"
    assert user.display_name == "Demo Driver"


async def test_get_current_user_without_header_raises_401_auth_required():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request(), authorization=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


async def test_get_current_user_without_bearer_prefix_raises_401():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request(), authorization="just-a-token")
    assert exc_info.value.status_code == 401


async def test_get_current_user_with_an_unknown_token_raises_401():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request(), authorization="Bearer not-a-real-token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


async def test_expired_and_unknown_tokens_share_the_code_but_not_the_message():
    """Cùng `401 AUTH_REQUIRED` (client xử lý hai ca giống nhau: đăng xuất, về /login),
    nhưng `message` phải tách — "server vừa restart" và "hết 12 h" là hai việc khác
    nhau với người vận hành, và câu gộp cũ đã khiến ca restart bị chẩn đoán nhầm."""
    store = auth.get_auth_store()
    issued = store.login("driver.demo@example.com", "DemoDriver123!")
    store._tokens[issued.token] = issued.__class__(  # noqa: SLF001 - test helper, forces expiry
        token=issued.token,
        user_id=issued.user_id,
        role=issued.role,
        display_name=issued.display_name,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(ApiError) as expired_exc:
        await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    with pytest.raises(ApiError) as unknown_exc:
        await auth_deps.get_current_user(_request(), authorization="Bearer not-a-real-token")

    assert expired_exc.value.status_code == unknown_exc.value.status_code == 401
    assert expired_exc.value.code == unknown_exc.value.code == "AUTH_REQUIRED"
    assert "hết hạn" in expired_exc.value.message
    assert "khởi động lại" in unknown_exc.value.message


async def test_get_current_user_echoes_a_valid_client_trace_id_on_error():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.get_current_user(_request({"X-Trace-Id": "tr_client_test_001"}), authorization=None)
    assert exc_info.value.trace_id == "tr_client_test_001"


async def test_require_driver_accepts_a_driver_user():
    issued = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    result = await auth_deps.require_driver(_request(), user=user)
    assert result is user


async def test_require_driver_rejects_an_engineer_user_with_403_forbidden():
    issued = auth.get_auth_store().login("engineer.demo@example.com", "DemoEngineer123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_driver(_request(), user=user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FORBIDDEN"


async def test_require_engineer_accepts_an_engineer_user():
    issued = auth.get_auth_store().login("engineer.demo@example.com", "DemoEngineer123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    result = await auth_deps.require_engineer(_request(), user=user)
    assert result is user


async def test_require_engineer_rejects_a_driver_user_with_403_forbidden():
    """Đối xứng với `require_driver` — hai vai không thay nhau được.

    Issue #45 (B1): trước đây hàm này không tồn tại nên `/traces/{id}` và
    `/metrics/summary` nhận cả token tài xế lẫn không token nào.
    """
    issued = auth.get_auth_store().login("driver.demo@example.com", "DemoDriver123!")
    user = await auth_deps.get_current_user(_request(), authorization=f"Bearer {issued.token}")
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_engineer(_request(), user=user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FORBIDDEN"


async def test_require_schema_version_accepts_1_0():
    await auth_deps.require_schema_version(_request(), x_schema_version="1.0")


async def test_require_schema_version_rejects_missing_header_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_schema_version(_request(), x_schema_version=None)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REQUEST_CONTEXT_INVALID"


async def test_require_schema_version_rejects_wrong_value_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_schema_version(_request(), x_schema_version="2.0")
    assert exc_info.value.status_code == 400


async def test_require_login_schema_version_accepts_the_header():
    await auth_deps.require_login_schema_version(_request(), x_schema_version="1.0", content_type=None)


async def test_require_login_schema_version_accepts_content_type_version_param():
    await auth_deps.require_login_schema_version(
        _request(), x_schema_version=None, content_type="application/json; charset=utf-8; version=1.0"
    )


async def test_require_login_schema_version_rejects_neither_present():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_login_schema_version(_request(), x_schema_version=None, content_type="application/json")
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REQUEST_CONTEXT_INVALID"


async def test_require_idempotency_key_returns_the_key():
    key = await auth_deps.require_idempotency_key(_request(), idempotency_key="turn:ses_1:001")
    assert key == "turn:ses_1:001"


async def test_require_idempotency_key_rejects_missing_header_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_idempotency_key(_request(), idempotency_key=None)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REQUEST_CONTEXT_INVALID"


async def test_require_idempotency_key_rejects_empty_string_with_400():
    with pytest.raises(ApiError) as exc_info:
        await auth_deps.require_idempotency_key(_request(), idempotency_key="")
    assert exc_info.value.status_code == 400

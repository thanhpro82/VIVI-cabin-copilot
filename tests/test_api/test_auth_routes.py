"""POST /api/v1/auth/login — xem docs/api_spec.md mục "Login"."""


async def test_login_with_driver_credentials_returns_200_with_the_spec_envelope(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["token_type"] == "Bearer"
    assert body["data"]["access_token"]
    assert body["data"]["user"] == {"user_id": "usr_driver_01", "role": "driver", "display_name": "Demo Driver"}
    assert body["schema_version"] == "1.0"
    assert body["trace_id"]


async def test_login_with_engineer_credentials_returns_engineer_role(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "engineer.demo@example.com", "password": "DemoEngineer123!"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["user"]["role"] == "engineer"


async def test_login_with_wrong_password_returns_401_auth_required(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "driver.demo@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_login_with_unknown_email_returns_401_auth_required(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 401


async def test_login_missing_schema_version_returns_400_request_context_invalid(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


async def test_login_accepts_schema_version_declared_via_content_type_param(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"Content-Type": "application/json; charset=utf-8; version=1.0"},
        content=b'{"email":"driver.demo@example.com","password":"DemoDriver123!"}',
    )
    assert response.status_code == 200


async def test_login_does_not_require_authorization_header(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.status_code == 200


async def test_login_echoes_a_valid_client_trace_id(client):
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0", "X-Trace-Id": "tr_client_login_001"},
        json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
    )
    assert response.json()["trace_id"] == "tr_client_login_001"


async def test_login_with_malformed_body_returns_envelope_shaped_422_without_leaking_input(client):
    """Body thiếu `password` — FastAPI/Pydantic tự raise RequestValidationError
    trước khi vào handler. Không đăng ký handler riêng thì FastAPI trả
    `{"detail": [...]}` mặc định, thiếu `trace_id`/`schema_version`, và mỗi lỗi
    còn kèm `input` — echo lại credentials người dùng gửi lên."""
    response = await client.post(
        "/api/v1/auth/login",
        headers={"X-Schema-Version": "1.0"},
        json={"email": "driver.demo@example.com"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INPUT_INVALID"
    assert body["trace_id"]
    assert body["schema_version"] == "1.0"
    errors = body["error"]["details"]["errors"]
    assert errors
    assert all("input" not in error for error in errors)


async def test_login_doc_bang_users_chu_khong_doc_hang_trong_ma_nguon(client):
    """Issue #46: user là dữ liệu, không còn là tuple hằng trong `auth.py`.

    Kiểm bằng cách vô hiệu hoá tài khoản **trong DB** rồi đăng nhập lại — nếu login
    vẫn còn đọc hằng thì bước này không đổi được gì và test đỏ.
    """
    from src.db import get_connection

    connection = get_connection()
    connection.execute("UPDATE users SET active = 0 WHERE id = 'usr_driver_01'")
    connection.commit()
    try:
        response = await client.post(
            "/api/v1/auth/login",
            headers={"X-Schema-Version": "1.0"},
            json={"email": "driver.demo@example.com", "password": "DemoDriver123!"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    finally:
        connection.execute("UPDATE users SET active = 1 WHERE id = 'usr_driver_01'")
        connection.commit()


async def test_mat_khau_demo_chi_nam_trong_db_duoi_dang_hash(client):
    """Phạm vi của khẳng định này hẹp **có chủ đích**, và tên cũ của nó nói quá.

    Thứ đợt #46 đổi là *dạng lưu trong DB*. Credential seed vẫn nằm trong mã nguồn
    (`DEMO_USERS` ở `src/db.py`) — Thành bắt đúng chỗ nói quá đó ở review PR #89, nên
    test này chỉ khẳng định điều nó thật sự kiểm được: trong bảng `users`, mật khẩu
    demo không xuất hiện dưới dạng thô.
    """
    from src.db import DEMO_USERS, get_connection

    connection = get_connection()
    for user_id, _email, password, _role, _name in DEMO_USERS:
        encoded = connection.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        assert encoded.startswith("pbkdf2_sha256$")
        assert password not in encoded

    # Không đếm tổng số hàng: bộ test tự seed thêm user cho các case cổng sở hữu
    # (`seed_test_user`), nên một khẳng định về `COUNT(*)` sẽ đỏ vì lý do không liên
    # quan gì tới mật khẩu.
    thoi = [row[0] for row in connection.execute("SELECT password_hash FROM users")]
    for _user_id, _email, password, _role, _name in DEMO_USERS:
        assert all(password not in encoded for encoded in thoi)

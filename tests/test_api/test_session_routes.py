"""POST /api/v1/sessions — auth, ownership, idempotency. Xem
docs/api_spec.md mục "Create session" và
docs/superpowers/specs/2026-08-10-core-driver-apis-design.md."""

from src.api import session_state


async def _login(client, email: str = "driver.demo@example.com", password: str = "DemoDriver123!") -> str:
    response = await client.post(
        "/api/v1/auth/login", headers={"X-Schema-Version": "1.0"}, json={"email": email, "password": password}
    )
    return response.json()["data"]["access_token"]


async def test_create_session_returns_the_spec_envelope(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "session:vehicle-demo-01:001",
        },
        json={"vehicle_id": "vehicle-demo-01", "input_mode": "voice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["vehicle_id"] == "vehicle-demo-01"
    assert body["data"]["status"] == "active"
    assert body["data"]["session_id"].startswith("ses_")
    assert body["data"]["started_at"]
    assert body["schema_version"] == "1.0"


async def test_create_session_records_the_caller_as_owner(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "session:vehicle-demo-01:002",
        },
        json={"vehicle_id": "vehicle-demo-01"},
    )
    session_id = response.json()["data"]["session_id"]
    record = session_state.get_session_record(session_id)
    assert record.user_id == "usr_driver_01"


async def test_create_session_without_a_token_returns_401_auth_required(client):
    response = await client.post(
        "/api/v1/sessions",
        headers={"X-Schema-Version": "1.0", "Idempotency-Key": "session:x:001"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_create_session_with_an_engineer_token_returns_403_forbidden(client):
    token = await _login(client, email="engineer.demo@example.com", password="DemoEngineer123!")
    response = await client.post(
        "/api/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "session:x:001",
        },
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_create_session_missing_idempotency_key_returns_400(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


async def test_create_session_missing_schema_version_returns_400(client):
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "session:x:001"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    assert response.status_code == 400


async def test_replaying_the_same_idempotency_key_returns_the_identical_response_and_creates_no_second_session(client):
    token = await _login(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Schema-Version": "1.0",
        "Idempotency-Key": "session:vehicle-demo-01:replay",
    }
    payload = {"vehicle_id": "vehicle-demo-01"}
    first = await client.post("/api/v1/sessions", headers=headers, json=payload)
    before_count = session_state.session_count()
    second = await client.post("/api/v1/sessions", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert session_state.session_count() == before_count


async def test_reusing_the_key_with_a_different_body_returns_409_idempotency_conflict(client):
    token = await _login(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Schema-Version": "1.0",
        "Idempotency-Key": "session:conflict:001",
    }
    await client.post("/api/v1/sessions", headers=headers, json={"vehicle_id": "vehicle-demo-01"})
    response = await client.post("/api/v1/sessions", headers=headers, json={"vehicle_id": "vehicle-demo-02"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_missing_vehicle_id_returns_envelope_shaped_422(client):
    """Body thiếu `vehicle_id` (bắt buộc) — kiểm chứng RequestValidationError
    handler áp dụng cho mọi route, không chỉ /auth/login."""
    token = await _login(client)
    response = await client.post(
        "/api/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "session:novehicle:001",
        },
        json={},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INPUT_INVALID"
    assert body["trace_id"]
    assert body["schema_version"] == "1.0"
    errors = body["error"]["details"]["errors"]
    assert all("input" not in error for error in errors)

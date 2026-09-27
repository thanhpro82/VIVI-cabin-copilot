"""`POST /routines/{id}/run` và `GET /routine-executions/{id}` (issue #286).

Bộ test ở mức API canh ba thứ mà tầng service không thấy: cổng xác thực, cổng sở hữu
phiên, và mã lỗi trên dây. Hành vi của engine (thứ tự bước, S2/S3, fail-fast) đã có bộ
riêng ở `tests/test_services/test_routine_execution.py`.
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_DRIVER = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}
_ENGINEER = {"email": "engineer.demo@example.com", "password": "DemoEngineer123!"}
_DRAFT = {"name": "Mát mẻ", "icon": "sun", "steps": [{"action": "hvac_temperature", "temperatureC": 22}]}


@pytest.fixture(autouse=True)
def _don():
    from src.db import get_connection

    connection = get_connection()
    for bang in ("routine_executions", "routines", "user_places", "approvals"):
        connection.execute(f"DELETE FROM {bang}")
    connection.commit()
    yield


def _login(client: TestClient, creds: dict) -> str:
    return client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=creds).json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}


def _phien(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={**_auth(token), "Idempotency-Key": "key-routine-run"},
        json={"vehicle_id": "veh-01"},
    )
    return response.json()["data"]["session_id"]


def test_khong_co_token_thi_401():
    with TestClient(app) as client:
        assert client.post("/api/v1/routines/rtn_x/run", headers=_SCHEMA_HEADERS, json={"session_id": "s"}).status_code == 401


def test_engineer_khong_chay_duoc_routine():
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        response = client.post("/api/v1/routines/rtn_x/run", headers=_auth(token), json={"session_id": "s"})
        assert response.status_code == 403


def test_phien_khong_thuoc_ve_minh_thi_403():
    """Phiên là thứ ràng buộc "một Routine đang chạy" và là nơi thẻ phê duyệt xuất hiện —
    chạy trên phiên người khác nghĩa là đẩy một thẻ vào màn hình của họ."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        routine = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]

        response = client.post(
            f"/api/v1/routines/{routine['id']}/run",
            headers=_auth(token),
            json={"session_id": "ses_khong_ton_tai"},
        )

        assert response.status_code == 403


def test_routine_da_tat_tra_409():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)
        routine = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]
        client.put(f"/api/v1/routines/{routine['id']}/enabled", headers=_auth(token), json={"enabled": False})

        response = client.post(
            f"/api/v1/routines/{routine['id']}/run", headers=_auth(token), json={"session_id": session_id}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROUTINE_DISABLED"


def test_chua_dat_dia_diem_tra_409_va_khong_tao_execution():
    """Mẫu "Đi làm" có bước dẫn đường. Từ chối **trước khi** tạo execution, nên không có
    lần chạy ma nào nằm lại để ai đó phải dọn."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)
        items = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]
        di_lam = next(r for r in items if r["template_origin"] == "di_lam")

        response = client.post(
            f"/api/v1/routines/{di_lam['id']}/run", headers=_auth(token), json={"session_id": session_id}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROUTINE_NEEDS_SETUP"

        from src.db import get_connection

        assert get_connection().execute("SELECT COUNT(*) AS n FROM routine_executions").fetchone()["n"] == 0


def test_chay_mot_buoc_s1_tra_202_va_execution_completed():
    """202 vì lần chạy **chưa chắc xong** khi request trả về — nó có thể đang chờ phê
    duyệt một bước S2. Ở ca một bước S1 thì nó xong ngay, và bản ghi nói thế.

    Trong bộ test, cổng xe là simulator in-process (`MQTT_ENABLED=false`), nên bước này
    chạy thật qua đúng `gateway.execute` mà một câu lệnh nói ra cũng đi qua.
    """
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)
        routine = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]

        response = client.post(
            f"/api/v1/routines/{routine['id']}/run", headers=_auth(token), json={"session_id": session_id}
        )

        assert response.status_code == 202
        data = response.json()["data"]
        assert data["status"] == "completed"
        assert data["steps_total"] == 1
        assert [r["status"] for r in data["results"]] == ["completed"]
        assert data["approval_id"] is None


def test_mot_phien_khong_chay_hai_routine_cung_luc_tra_409():
    """Ràng buộc ở tầng DB, không phải một phép kiểm trong Python — nên hai request song
    song cũng không lách được. Ca này chỉ khoá mã lỗi trên dây."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)
        cho_duyet = client.post(
            "/api/v1/routines",
            headers=_auth(token),
            json={"name": "Hạ kính", "icon": "car", "steps": [{"action": "window_position", "window": "frontLeft", "percent": 40}]},
        ).json()["data"]
        khac = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]
        dang_cho = client.post(
            f"/api/v1/routines/{cho_duyet['id']}/run", headers=_auth(token), json={"session_id": session_id}
        ).json()["data"]
        assert dang_cho["status"] == "waiting_approval"

        response = client.post(
            f"/api/v1/routines/{khac['id']}/run", headers=_auth(token), json={"session_id": session_id}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROUTINE_ALREADY_RUNNING"


def test_doc_lai_execution_bang_id():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)
        routine = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]
        execution = client.post(
            f"/api/v1/routines/{routine['id']}/run", headers=_auth(token), json={"session_id": session_id}
        ).json()["data"]

        doc_lai = client.get(f"/api/v1/routine-executions/{execution['id']}", headers=_auth(token))

        assert doc_lai.status_code == 200
        assert doc_lai.json()["data"]["id"] == execution["id"]


def test_execution_khong_ton_tai_tra_404():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.get("/api/v1/routine-executions/rex_khong_co", headers=_auth(token))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ROUTINE_EXECUTION_NOT_FOUND"


def test_routine_cua_nguoi_khac_tra_404_khi_chay():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)

        response = client.post(
            "/api/v1/routines/rtn_cua_ai_do/run", headers=_auth(token), json={"session_id": session_id}
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ROUTINE_NOT_FOUND"


def test_huy_lan_chay_dang_cho_duyet_tra_200_va_idempotent():
    """Nút Dừng: 200 vì yêu cầu **đã được ghi nhận** khi request trả về.

    Gọi lại không sinh terminal thứ hai — tài xế bấm hai lần là chuyện thường.
    """
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)
        routine = client.post(
            "/api/v1/routines",
            headers=_auth(token),
            json={
                "name": "Hạ kính rồi bật đèn",
                "icon": "car",
                "steps": [
                    {"action": "window_position", "window": "frontLeft", "percent": 40},
                    {"action": "interior_light", "enabled": True},
                ],
            },
        ).json()["data"]
        execution = client.post(
            f"/api/v1/routines/{routine['id']}/run", headers=_auth(token), json={"session_id": session_id}
        ).json()["data"]
        assert execution["status"] == "waiting_approval"

        lan_1 = client.post(f"/api/v1/routine-executions/{execution['id']}/cancel", headers=_auth(token))
        lan_2 = client.post(f"/api/v1/routine-executions/{execution['id']}/cancel", headers=_auth(token))

        assert lan_1.status_code == lan_2.status_code == 200
        assert lan_1.json()["data"]["status"] == "user_canceled"
        assert lan_2.json()["data"]["status"] == "user_canceled"
        assert lan_1.json()["data"]["updated_at"] == lan_2.json()["data"]["updated_at"]
        assert [r["status"] for r in lan_1.json()["data"]["results"]] == ["canceled", "skipped"]


def test_huy_lan_chay_khong_ton_tai_tra_404():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.post("/api/v1/routine-executions/rex_khong_co/cancel", headers=_auth(token))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ROUTINE_EXECUTION_NOT_FOUND"


def test_xoa_routine_dang_chay_tra_409_kem_execution_id():
    """Acceptance criteria #272. Chặn chứ không tự hủy hộ: tự hủy là quyết định thay
    người dùng về một chuỗi lệnh đang tác động lên xe."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        session_id = _phien(client, token)
        routine = client.post(
            "/api/v1/routines",
            headers=_auth(token),
            json={"name": "Đang chạy", "icon": "car", "steps": [{"action": "window_position", "window": "frontLeft", "percent": 40}]},
        ).json()["data"]
        execution = client.post(
            f"/api/v1/routines/{routine['id']}/run", headers=_auth(token), json={"session_id": session_id}
        ).json()["data"]

        response = client.delete(f"/api/v1/routines/{routine['id']}", headers=_auth(token))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROUTINE_RUNNING"
        assert response.json()["error"]["details"]["execution_id"] == execution["id"]

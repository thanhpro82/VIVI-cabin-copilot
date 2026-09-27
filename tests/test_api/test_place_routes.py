"""`/api/v1/places` — hai nhãn địa điểm cá nhân (issue #283).

Trọng tâm: ba trạng thái (chưa gán / dùng được / đích đã biến mất) phải phân biệt được
từ phía client, và không có đường nào tạo ra một giá trị mặc định.
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_DRIVER = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}
_ENGINEER = {"email": "engineer.demo@example.com", "password": "DemoEngineer123!"}


@pytest.fixture(autouse=True)
def _don_places():
    from src.db import get_connection

    connection = get_connection()
    connection.execute("DELETE FROM user_places")
    connection.execute("DELETE FROM routines")
    connection.commit()
    yield


def _login(client: TestClient, creds: dict) -> str:
    return client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=creds).json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}


def test_khong_co_token_thi_401():
    with TestClient(app) as client:
        assert client.get("/api/v1/places", headers=_SCHEMA_HEADERS).status_code == 401


def test_engineer_khong_vao_duoc():
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        assert client.get("/api/v1/places", headers=_auth(token)).status_code == 403


def test_chua_gan_tra_null_cho_ca_hai_nhan():
    """Cả hai khoá **luôn có mặt**; `null` nghĩa là chưa gán.

    Bỏ hẳn khoá đi thì client phải phân biệt "chưa gán" với "server phiên bản cũ" bằng
    cách đoán.
    """
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        data = client.get("/api/v1/places", headers=_auth(token)).json()["data"]

        assert data == {"home": None, "office": None}


def test_gan_roi_doc_lai_thay_ten_tu_fixture():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)

        dat = client.put(
            "/api/v1/places/office",
            headers=_auth(token),
            json={"destination_id": "poi-work-01"},
        )

        assert dat.status_code == 200
        office = dat.json()["data"]["office"]
        assert office["destination_id"] == "poi-work-01"
        assert office["name"] == "Cơ quan"
        assert office["valid"] is True
        assert dat.json()["data"]["home"] is None


def test_dich_ngoai_fixture_tra_422():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)

        response = client.put(
            "/api/v1/places/home",
            headers=_auth(token),
            json={"destination_id": "poi-nha-that-cua-toi"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PLACE_DESTINATION_INVALID"


def test_nhan_la_tra_404_chu_khong_phai_422():
    """`/places/bep` không phải body sai — nó là tài nguyên không tồn tại."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)

        response = client.put(
            "/api/v1/places/bep",
            headers=_auth(token),
            json={"destination_id": "poi-home-01"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PLACE_LABEL_UNKNOWN"


def test_body_thua_field_bi_tu_choi():
    """`label` nằm ở path; nhận nó ở cả hai chỗ là mời một request tự mâu thuẫn."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)

        response = client.put(
            "/api/v1/places/home",
            headers=_auth(token),
            json={"destination_id": "poi-home-01", "label": "office"},
        )

        assert response.status_code == 422


def test_bo_gan_tra_204_va_idempotent():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        client.put("/api/v1/places/home", headers=_auth(token), json={"destination_id": "poi-home-01"})

        assert client.delete("/api/v1/places/home", headers=_auth(token)).status_code == 204
        assert client.delete("/api/v1/places/home", headers=_auth(token)).status_code == 204
        assert client.get("/api/v1/places", headers=_auth(token)).json()["data"]["home"] is None


def test_gan_dia_diem_lam_routine_di_lam_chay_duoc():
    """Đây là lý do #283 tồn tại: trước khi gán, mọi Routine dẫn đường đều không chạy được."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        truoc = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]
        di_lam_truoc = next(r for r in truoc if r["template_origin"] == "di_lam")
        assert di_lam_truoc["needs_setup"] is True
        assert di_lam_truoc["runnable"] is False

        client.put("/api/v1/places/office", headers=_auth(token), json={"destination_id": "poi-work-01"})

        sau = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]
        di_lam_sau = next(r for r in sau if r["template_origin"] == "di_lam")
        assert di_lam_sau["needs_setup"] is False
        assert di_lam_sau["runnable"] is True


def test_ve_nha_van_can_thiet_lap_khi_moi_gan_co_quan():
    """Thiếu **bất kỳ** nhãn nào mà Routine cần là cần thiết lập — không có chuyện lấy
    tạm cái đã gán."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        client.put("/api/v1/places/office", headers=_auth(token), json={"destination_id": "poi-work-01"})

        items = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]
        ve_nha = next(r for r in items if r["template_origin"] == "ve_nha")

        assert ve_nha["needs_setup"] is True


def test_dich_bien_mat_khoi_fixture_hien_valid_false():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        from src.db import get_connection

        get_connection().execute(
            "INSERT INTO user_places (user_id, label, destination_id, updated_at)"
            " VALUES ('usr_driver_01', 'home', 'poi-da-bi-go', '2026-08-29T00:00:00+00:00')"
        )
        get_connection().commit()

        home = client.get("/api/v1/places", headers=_auth(token)).json()["data"]["home"]

        assert home["valid"] is False
        assert home["name"] is None
        assert home["destination_id"] == "poi-da-bi-go"


def test_envelope_du_meta_va_trace_id():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        body = client.get("/api/v1/places", headers=_auth(token)).json()

        assert body["schema_version"] == "1.0"
        assert body["meta"]["request_id"]
        assert body["trace_id"]

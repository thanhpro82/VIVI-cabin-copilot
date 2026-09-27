"""`/api/v1/routines` — CRUD Routine theo chủ sở hữu (issue #282).

Bộ test này canh bốn thứ, và chỉ cái đầu là "CRUD chạy được":

1. bề mặt trả đúng envelope và đúng mã trạng thái;
2. **không đường nào** đọc/sửa được Routine của người khác, kể cả khi biết id;
3. chủ sở hữu luôn đến từ token — body không nói được nó là ai;
4. mã lỗi trên dây khớp thứ `frontend/.../routines/mock.ts` đang ném, để `real.ts`
   chỉ phải đổi transport chứ không dịch một bảng mã thứ hai.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.conftest import seed_test_user


@pytest.fixture(autouse=True)
def _don_routines():
    """Xoá Routine giữa các test.

    `DATABASE_URL` của `conftest.py` là `:memory:` nhưng kết nối là **một** cho cả tiến
    trình (`db.get_connection`), nên bảng sống xuyên suốt phiên pytest. Không dọn thì
    test thứ hai tạo Routine cùng tên nhận 409 và hỏng vì thứ tự chạy, chứ không phải vì
    hành vi — đúng loại hỏng mà nhìn log sẽ chẩn đoán nhầm sang tầng ownership.
    """
    from src.db import get_connection

    connection = get_connection()
    connection.execute("DELETE FROM routines")
    connection.execute("DELETE FROM user_places")
    connection.commit()
    yield

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_DRIVER = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}
_ENGINEER = {"email": "engineer.demo@example.com", "password": "DemoEngineer123!"}

_DRAFT = {"name": "Buổi sáng", "icon": "sun", "steps": [{"action": "hvac_temperature", "temperatureC": 22}]}


def _login(client: TestClient, creds: dict) -> str:
    return client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=creds).json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}


def _seed_routine_cua_nguoi_khac(routine_id: str = "rtn_cua_nguoi_khac") -> str:
    """Một Routine thuộc user khác, ghi thẳng vào DB.

    Qua API thì không tạo được: chỉ có một tài khoản driver demo, và chủ sở hữu luôn
    lấy từ token. Đó chính là điều bộ test này muốn khẳng định.
    """
    from src.db import get_connection

    owner = seed_test_user("usr_driver_99")
    connection = get_connection()
    connection.execute(
        """
        INSERT OR REPLACE INTO routines (
            id, user_id, name, name_normalized, icon, enabled, steps_json,
            is_default_template, template_origin, version, previewed_version, created_at, updated_at
        ) VALUES (?, ?, 'Của người khác', 'của người khác', 'car', 1, ?, 0, NULL, 1, NULL, ?, ?)
        """,
        (
            routine_id,
            owner,
            json.dumps([{"action": "hvac_fan_level", "level": 1}]),
            "2026-08-29T00:00:00+00:00",
            "2026-08-29T00:00:00+00:00",
        ),
    )
    connection.commit()
    return routine_id


# --- xác thực và vai trò -----------------------------------------------------


def test_khong_co_token_thi_401():
    with TestClient(app) as client:
        assert client.get("/api/v1/routines", headers=_SCHEMA_HEADERS).status_code == 401


def test_engineer_khong_vao_duoc_be_mat_nay():
    """Routine là dữ liệu của người lái. Engineer không có Routine nào để quản, nên cho
    họ đọc là mở một đường vòng vào dữ liệu cá nhân mà không ai cần."""
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        assert client.get("/api/v1/routines", headers=_auth(token)).status_code == 403


# --- danh sách và bootstrap --------------------------------------------------


def test_lan_goi_dau_gieo_du_ba_mau_mac_dinh():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        items = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]

        origins = {r["template_origin"] for r in items if r["is_default_template"]}
        assert origins == {"di_lam", "ve_nha", "thu_gian"}


def test_goi_lai_khong_sinh_them_mau():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        lan_dau = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]
        lan_hai = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]

        assert len(lan_dau) == len(lan_hai) == 3


def test_mau_can_dan_duong_bao_can_thiet_lap_va_khong_runnable():
    """Chưa gán Nhà/Cơ quan thì "Đi làm" và "Về nhà" không chạy được — và backend nói
    ra điều đó, không để mỗi client tự suy từ danh sách bước."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        items = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]

        can_dia_diem = [r for r in items if r["template_origin"] in {"di_lam", "ve_nha"}]
        assert len(can_dia_diem) == 2
        assert all(r["needs_setup"] and not r["runnable"] for r in can_dia_diem)

        thu_gian = next(r for r in items if r["template_origin"] == "thu_gian")
        assert thu_gian["needs_setup"] is False
        assert thu_gian["runnable"] is True


# --- tạo, sửa, bật/tắt, xoá --------------------------------------------------


def test_tao_tra_201_va_doc_lai_duoc():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        tao = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT)

        assert tao.status_code == 201
        data = tao.json()["data"]
        assert data["name"] == "Buổi sáng"
        assert data["is_default_template"] is False
        assert data["version"] == 1

        doc_lai = client.get(f"/api/v1/routines/{data['id']}", headers=_auth(token))
        assert doc_lai.status_code == 200
        assert doc_lai.json()["data"]["steps"] == _DRAFT["steps"]


def test_chu_so_huu_den_tu_token_chu_khong_tu_body():
    """Gửi kèm `user_id` phải là **request sai**, không phải request hợp lệ bị bỏ qua.

    Bỏ qua âm thầm nghĩa là một client tưởng mình đang tạo hộ người khác và không có gì
    báo cho họ biết là không.
    """
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.post(
            "/api/v1/routines",
            headers=_auth(token),
            json={**_DRAFT, "user_id": "usr_driver_99"},
        )

        assert response.status_code == 422


def test_sua_buoc_bump_version_va_bat_lai_preview():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        goc = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]

        sua = client.put(
            f"/api/v1/routines/{goc['id']}",
            headers=_auth(token),
            json={**_DRAFT, "steps": [{"action": "hvac_temperature", "temperatureC": 26}]},
        )

        assert sua.status_code == 200
        assert sua.json()["data"]["version"] == goc["version"] + 1
        assert sua.json()["data"]["needs_preview"] is True


def test_bat_tat_doi_enabled_va_runnable():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        routine = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]

        tat = client.put(
            f"/api/v1/routines/{routine['id']}/enabled",
            headers=_auth(token),
            json={"enabled": False},
        )

        assert tat.status_code == 200
        assert tat.json()["data"]["enabled"] is False
        assert tat.json()["data"]["runnable"] is False


def test_xoa_tra_204_va_lan_sau_la_404():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        routine = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]

        assert client.delete(f"/api/v1/routines/{routine['id']}", headers=_auth(token)).status_code == 204
        assert client.get(f"/api/v1/routines/{routine['id']}", headers=_auth(token)).status_code == 404


def test_khong_xoa_duoc_mau_mac_dinh():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        items = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]
        mau = next(r for r in items if r["is_default_template"])

        response = client.delete(f"/api/v1/routines/{mau['id']}", headers=_auth(token))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROUTINE_TEMPLATE_PROTECTED"


def test_khoi_phuc_mau_ve_noi_dung_goc():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        items = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]
        mau = next(r for r in items if r["template_origin"] == "thu_gian")
        client.put(
            f"/api/v1/routines/{mau['id']}",
            headers=_auth(token),
            json={"name": "Của tôi", "icon": "music", "steps": [{"action": "hvac_fan_level", "level": 1}]},
        )

        khoi_phuc = client.post(f"/api/v1/routines/{mau['id']}/restore-default", headers=_auth(token))

        assert khoi_phuc.status_code == 200
        assert khoi_phuc.json()["data"]["name"] == "Thư giãn"
        assert khoi_phuc.json()["data"]["needs_preview"] is True


def test_khoi_phuc_tren_routine_tu_tao_tra_409():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        routine = client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT).json()["data"]

        response = client.post(f"/api/v1/routines/{routine['id']}/restore-default", headers=_auth(token))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROUTINE_NOT_TEMPLATE"


# --- cô lập theo tài khoản ---------------------------------------------------


def test_routine_cua_nguoi_khac_tra_404_giong_het_id_khong_ton_tai():
    """Hai ca phải **không phân biệt được** từ phía client.

    403 cho ca đầu là xác nhận Routine ấy có thật — đúng kênh rò rỉ mà #272 acceptance
    criteria đóng lại.
    """
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        cua_nguoi_khac = _seed_routine_cua_nguoi_khac()

        cua_ho = client.get(f"/api/v1/routines/{cua_nguoi_khac}", headers=_auth(token))
        khong_co = client.get("/api/v1/routines/rtn_khong_ton_tai", headers=_auth(token))

        assert cua_ho.status_code == khong_co.status_code == 404
        assert cua_ho.json()["error"]["code"] == khong_co.json()["error"]["code"] == "ROUTINE_NOT_FOUND"


def test_khong_sua_xoa_bat_tat_duoc_routine_cua_nguoi_khac():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        cua_nguoi_khac = _seed_routine_cua_nguoi_khac("rtn_khong_duoc_cham")

        assert client.put(f"/api/v1/routines/{cua_nguoi_khac}", headers=_auth(token), json=_DRAFT).status_code == 404
        assert (
            client.put(
                f"/api/v1/routines/{cua_nguoi_khac}/enabled", headers=_auth(token), json={"enabled": False}
            ).status_code
            == 404
        )
        assert client.delete(f"/api/v1/routines/{cua_nguoi_khac}", headers=_auth(token)).status_code == 404

        from src.db import get_connection

        row = get_connection().execute("SELECT name FROM routines WHERE id = ?", (cua_nguoi_khac,)).fetchone()
        assert row is not None and row["name"] == "Của người khác"


def test_danh_sach_khong_lo_routine_cua_nguoi_khac():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        _seed_routine_cua_nguoi_khac("rtn_an_di")

        items = client.get("/api/v1/routines", headers=_auth(token)).json()["data"]["items"]

        assert all(r["id"] != "rtn_an_di" for r in items)
        assert all(r["user_id"] == "usr_driver_01" for r in items)


# --- mã lỗi khớp FE ----------------------------------------------------------


def test_routine_rong_tra_ma_routine_empty():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.post("/api/v1/routines", headers=_auth(token), json={**_DRAFT, "steps": []})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ROUTINE_EMPTY"


def test_qua_bon_buoc_tra_ma_too_many_steps():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.post(
            "/api/v1/routines",
            headers=_auth(token),
            json={**_DRAFT, "steps": [{"action": "hvac_fan_level", "level": 1}] * 5},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ROUTINE_TOO_MANY_STEPS"


def test_ten_trung_tra_ma_name_duplicate():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        client.post("/api/v1/routines", headers=_auth(token), json=_DRAFT)

        response = client.post("/api/v1/routines", headers=_auth(token), json={**_DRAFT, "name": "  buổi   SÁNG "})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROUTINE_NAME_DUPLICATE"


def test_ten_rong_tra_ma_name_empty():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.post("/api/v1/routines", headers=_auth(token), json={**_DRAFT, "name": "   "})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ROUTINE_NAME_EMPTY"


def test_gia_tri_ngoai_dai_tra_ma_step_invalid_kem_ly_do():
    """35 °C ngoài dải 16–30. Mã chung cho client, `details.ly_do` cho người đọc log."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.post(
            "/api/v1/routines",
            headers=_auth(token),
            json={**_DRAFT, "steps": [{"action": "hvac_temperature", "temperatureC": 35}]},
        )

        assert response.status_code == 422
        body = response.json()["error"]
        assert body["code"] == "ROUTINE_STEP_INVALID"
        assert body["details"]["ly_do"] == "gia_tri_ngoai_dai"


def test_action_ngoai_allowlist_tra_ma_step_invalid():
    """Cửa xe không nằm trong allowlist MVP — và bề mặt này không phải đường vòng vào nó."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.post(
            "/api/v1/routines",
            headers=_auth(token),
            json={**_DRAFT, "steps": [{"action": "door_state", "door": "front_left", "state": "open"}]},
        )

        assert response.status_code == 422
        assert response.json()["error"]["details"]["ly_do"] == "action_khong_ho_tro"


def test_envelope_co_du_meta_va_trace_id():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        body = client.get("/api/v1/routines", headers=_auth(token)).json()

        assert body["schema_version"] == "1.0"
        assert body["meta"]["request_id"]
        assert body["trace_id"]

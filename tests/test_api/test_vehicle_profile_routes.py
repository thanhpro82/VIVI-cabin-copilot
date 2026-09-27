"""`GET/PUT /api/v1/vehicle/profile` — cấu hình xe (issue #123).

Đọc mở cho cả hai vai, ghi chỉ engineer. Trọng tâm của bộ test này **không** phải
CRUD chạy được, mà là ba thứ dễ hỏng âm thầm: chưa khai báo phải trả 200 chứ không
404, `is_complete` phải do backend quyết, và không có đường nào tạo ra một cấu hình
nửa vời.
"""

from fastapi.testclient import TestClient

from src.main import app

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_DRIVER = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}
_ENGINEER = {"email": "engineer.demo@example.com", "password": "DemoEngineer123!"}


def _login(client, creds: dict) -> str:
    return client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=creds).json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}


def test_xe_chua_khai_bao_tra_200_voi_null_chu_khong_404():
    """Chiếc xe **có** tồn tại; chỉ cấu hình của nó là chưa biết.

    404 sẽ buộc client phân biệt "không có xe" với "chưa biết cấu hình" bằng cách
    đoán, còn `is_complete=false` nói thẳng thứ cần biết.
    """
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.get("/api/v1/vehicle/profile", headers=_auth(token))

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["trim"] is None
        assert data["battery"] is None
        assert data["is_complete"] is False
        assert data["updated_at"] is None


def test_engineer_ghi_duoc_va_doc_lai_thay_du_ca_hai():
    with TestClient(app) as client:
        engineer = _login(client, _ENGINEER)
        written = client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": "eco", "battery": "catl"},
        )

        assert written.status_code == 200, written.text
        assert written.json()["data"]["is_complete"] is True

        driver = _login(client, _DRIVER)
        read = client.get("/api/v1/vehicle/profile", headers=_auth(driver))
        assert read.json()["data"]["trim"] == "eco"
        assert read.json()["data"]["battery"] == "catl"
        assert read.json()["data"]["is_complete"] is True


def test_tai_xe_khong_doi_duoc_cau_hinh_xe():
    """Đổi trim/pin là khai báo lại chiếc xe, không phải thao tác lái."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        response = client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(token),
            json={"trim": "plus", "battery": "sdi"},
        )
        assert response.status_code == 403


def test_khong_co_token_thi_khong_doc_duoc():
    with TestClient(app) as client:
        assert client.get("/api/v1/vehicle/profile", headers=_SCHEMA_HEADERS).status_code == 401


def test_null_tuong_minh_la_cach_xoa_cau_hinh():
    """Xoá phải làm được, và phải quay đúng về trạng thái fail-closed."""
    with TestClient(app) as client:
        engineer = _login(client, _ENGINEER)
        client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": "eco", "battery": "catl"},
        )

        cleared = client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": None, "battery": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["data"]["is_complete"] is False


def test_ghi_de_toan_bo_cap_chu_khong_va_tung_phan():
    """Đây là ca sinh ra cấu hình của một chiếc xe không tồn tại.

    Đổi từ `eco+catl` sang `plus` mà không nói pin: nếu route vá từng phần, `battery`
    cũ (`catl`) ở lại, `is_complete` vẫn `True`, và bảng tra ra số của `plus+catl` —
    một cấu hình chưa từng được ai khai báo. PUT ghi đè cả cặp nên `battery` phải
    thành `null` và cổng fail-closed phải đóng lại.
    """
    with TestClient(app) as client:
        engineer = _login(client, _ENGINEER)
        client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": "eco", "battery": "catl"},
        )

        response = client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": "plus", "battery": None},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["trim"] == "plus"
        assert data["battery"] is None
        assert data["is_complete"] is False


def test_thieu_han_mot_field_la_422_khong_phai_ngam_hieu_la_null():
    """ "Quên gửi" và "cố ý xoá" phải trông khác nhau."""
    with TestClient(app) as client:
        engineer = _login(client, _ENGINEER)
        response = client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": "eco"},
        )
        assert response.status_code == 422


def test_gia_tri_la_bi_tu_choi():
    with TestClient(app) as client:
        engineer = _login(client, _ENGINEER)
        for body in ({"trim": "ultra", "battery": "catl"}, {"trim": "eco", "battery": "lfp"}):
            assert client.put("/api/v1/vehicle/profile", headers=_auth(engineer), json=body).status_code == 422


def test_field_la_trong_body_bi_tu_choi():
    """`extra="forbid"`: field lạ phải chết ở biên, không lọt vào hợp đồng."""
    with TestClient(app) as client:
        engineer = _login(client, _ENGINEER)
        response = client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": "eco", "battery": "catl", "mau_son": "trang"},
        )
        assert response.status_code == 422


def test_profile_khong_ro_ri_vao_vehicle_state():
    """ADR-013: backend chỉ forward snapshot của simulator, không thêm field nào.

    Test này canh ranh giới chứ không canh route — nó đỏ nếu ai đó "tiện tay" nhét
    trim/pin vào envelope trạng thái xe cho client đỡ phải gọi hai lần.
    """
    with TestClient(app) as client:
        engineer = _login(client, _ENGINEER)
        client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(engineer),
            json={"trim": "eco", "battery": "catl"},
        )

        state = client.get("/api/v1/vehicle/state", headers=_auth(engineer))
        body = state.text
        assert "trim" not in body
        assert "battery" not in body


# --- `GET/PUT /api/v1/vehicle/profile/options` -------------------------------
#
# Sub-resource riêng, không phải field thêm vào body ở trên. Bộ test này giữ đúng ranh
# giới ấy: hai tài nguyên phải độc lập, và cái mới không được đụng vào `is_complete`
# — cổng của nhánh áp suất lốp.


def test_xe_chua_khai_trang_bi_tra_200_voi_tap_rong():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        r = client.get("/api/v1/vehicle/profile/options", headers=_auth(token))

        assert r.status_code == 200
        assert r.json()["data"]["da_khai"] == {}


def test_danh_muc_di_kem_moi_lan_doc_de_client_khong_phai_giu_ban_sao():
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        danh_muc = client.get("/api/v1/vehicle/profile/options", headers=_auth(token)).json()["data"]["danh_muc"]

        assert len(danh_muc) >= 60
        ids = [t["id"] for t in danh_muc]
        assert "lop_du_phong" in ids
        assert len(ids) == len(set(ids))
        # `loai_tru` phải ra tới client: UI cần chặn tick hai ô trước khi server 422.
        lop = next(t for t in danh_muc if t["id"] == "lop_du_phong")
        assert lop["loai_tru"] == ["bo_bom_hoi"]
        assert lop["nhom"] == "cuu_ho"


def test_engineer_khai_duoc_va_doc_lai_thay_dung():
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        w = client.put(
            "/api/v1/vehicle/profile/options",
            headers=_auth(token),
            json={"da_khai": {"lop_du_phong": False, "bo_bom_hoi": True, "acc": True}},
        )
        assert w.status_code == 200
        assert w.json()["data"]["da_khai"] == {"acc": True, "bo_bom_hoi": True, "lop_du_phong": False}

        r = client.get("/api/v1/vehicle/profile/options", headers=_auth(token))
        assert r.json()["data"]["da_khai"] == {"acc": True, "bo_bom_hoi": True, "lop_du_phong": False}


def test_tai_xe_doc_duoc_nhung_khong_ghi_duoc():
    """Khai lại trang bị là khai lại chiếc xe, không phải một thao tác lái."""
    with TestClient(app) as client:
        token = _login(client, _DRIVER)
        assert client.get("/api/v1/vehicle/profile/options", headers=_auth(token)).status_code == 200
        w = client.put(
            "/api/v1/vehicle/profile/options",
            headers=_auth(token),
            json={"da_khai": {"acc": True}},
        )
        assert w.status_code == 403


def test_id_la_tra_422_chu_khong_nhan_bua():
    """Nhận bừa thì id lạ nằm im trong bảng cho tới lúc ai đó tra và không thấy."""
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        r = client.put(
            "/api/v1/vehicle/profile/options",
            headers=_auth(token),
            json={"da_khai": {"ghe_bay_duoc": True}},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_hai_trang_bi_loai_tru_nhau_tra_422():
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        r = client.put(
            "/api/v1/vehicle/profile/options",
            headers=_auth(token),
            json={"da_khai": {"lop_du_phong": True, "bo_bom_hoi": True}},
        )
        assert r.status_code == 422
        assert "loại trừ nhau" in r.json()["error"]["message"]


def test_ghi_trang_bi_khong_dung_toi_trim_battery():
    """Hai tài nguyên độc lập. `is_complete` là cổng của nhánh áp suất lốp và chỉ của nó.

    Nếu ghi trang bị làm hỏng `is_complete` thì cả nhánh áp suất lốp chết theo, mà
    suite áp suất lốp sẽ không thấy gì vì nó không gọi route này.
    """
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(token),
            json={"trim": "plus", "battery": "catl"},
        )
        client.put(
            "/api/v1/vehicle/profile/options",
            headers=_auth(token),
            json={"da_khai": {"acc": True}},
        )

        ho_so = client.get("/api/v1/vehicle/profile", headers=_auth(token)).json()["data"]
        assert ho_so["trim"] == "plus"
        assert ho_so["battery"] == "catl"
        assert ho_so["is_complete"] is True


def test_ghi_trim_battery_khong_xoa_trang_bi_da_khai():
    """Chiều ngược lại của test trên. PUT ghi đè **tài nguyên của nó**, không hơn."""
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        client.put(
            "/api/v1/vehicle/profile/options",
            headers=_auth(token),
            json={"da_khai": {"acc": True}},
        )
        client.put(
            "/api/v1/vehicle/profile",
            headers=_auth(token),
            json={"trim": "eco", "battery": "sdi"},
        )
        r = client.get("/api/v1/vehicle/profile/options", headers=_auth(token))
        assert r.json()["data"]["da_khai"] == {"acc": True}


def test_tap_rong_xoa_sach_khai_bao():
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        client.put(
            "/api/v1/vehicle/profile/options",
            headers=_auth(token),
            json={"da_khai": {"acc": True}},
        )
        r = client.put("/api/v1/vehicle/profile/options", headers=_auth(token), json={"da_khai": {}})
        assert r.json()["data"]["da_khai"] == {}


def test_thieu_field_da_khai_la_422():
    with TestClient(app) as client:
        token = _login(client, _ENGINEER)
        assert client.put("/api/v1/vehicle/profile/options", headers=_auth(token), json={}).status_code == 422

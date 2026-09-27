"""`POST /approvals/{id}/decision` — Bearer Driver + chủ sở hữu approval.

`docs/api_spec.md:48,60` chốt vai trò là **Driver, approval owner**, và dòng 657 chốt
mã lỗi cho trường hợp sai chủ: *"cross-owner is `FORBIDDEN`"*.

Trước ticket này route **không có một lớp xác thực nào** — ai đoán ra `approval_id` là
duyệt được một lệnh S2 của người khác. Hệ thống lúc đó không nhất quán theo hướng xấu:
tạo một lượt (`/turns/text`) thì cần token và phải đúng chủ phiên, nhưng *duyệt* lệnh
nhạy cảm thì không cần gì. Đây cũng là lúc ràng buộc quyền sở hữu thêm ở PR #25 mới có
nghĩa thật thay vì chỉ là capability.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from src.api import session_state
from src.main import app
from tests.conftest import seed_test_user

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
OPEN_WINDOW = {"query": "Mở cửa sổ bên lái 30 phần trăm", "vehicle_speed_kmh": 0.0}
DECISION = {"decision": "approve", "approved_vehicle_state_version": 1}

def _idem() -> dict[str, str]:
    """Header bắt buộc của `POST /approvals/{id}/decision` (issue #44).

    Khoá **mới mỗi lần gọi** là điều kiện bắt buộc, không phải tiện tay: trùng
    `Idempotency-Key` nghĩa là "cùng một request", nên dùng lại khoá sẽ khiến lần gọi
    thứ hai trả về bản ghi cũ thay vì chạy thật — và test replay/double-click sẽ xanh
    vì lý do sai.
    """
    return {"X-Schema-Version": "1.0", "Idempotency-Key": f"idem-{uuid.uuid4().hex[:12]}"}



def _login(client, email: str = "driver.demo@example.com", password: str = "DemoDriver123!") -> str:
    response = client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json={"email": email, "password": password})
    return response.json()["data"]["access_token"]


def _pending_approval_in(client, session_id: str) -> str:
    """Dựng một approval đang chờ trong `session_id` qua route dev-only `/agent/process`.

    Cố ý **không** dùng `/turns/text`: route đó bắt buộc token phải sở hữu phiên, nên
    không dựng nổi ca "approval của người khác" mà test này cần.
    """
    response = client.post("/api/v1/agent/process", json={**OPEN_WINDOW, "session_id": session_id})
    return response.json()["hitl_action_id"]


def test_decision_without_a_token_is_rejected():
    with TestClient(app) as client:
        token = _login(client)
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        approval_id = _pending_approval_in(client, session_id)

        # Gửi ĐỦ header ngữ cảnh, chỉ thiếu token — để test cô lập đúng điều kiện auth
        # mà tên nó nói. Thiếu cả header thì `require_schema_version` chặn trước và
        # trả 400, tức test sẽ xanh/đỏ vì một lý do khác với thứ nó định kiểm.
        response = client.post(
            f"/api/v1/approvals/{approval_id}/decision", headers=_idem(), json=DECISION
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    # Không có token thì không được chạm vào bản ghi — nó phải còn nguyên `pending`.
    assert session_state.get_store().get(approval_id).status == "pending"
    assert token  # đã login được, tức 401 ở trên không phải do hạ tầng auth hỏng


def test_decision_on_another_users_approval_is_forbidden():
    """`api_spec.md:657` — *"cross-owner is FORBIDDEN"*."""
    with TestClient(app) as client:
        token = _login(client)
        # Phiên thuộc về một tài xế khác.
        other_session = session_state.create_session(seed_test_user("usr_driver_99"), "vehicle-demo-01").session_id
        approval_id = _pending_approval_in(client, other_session)

        response = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**({**({"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}), **_idem()}), **_idem()},
            json=DECISION,
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert session_state.get_store().get(approval_id).status == "pending"


def test_an_unknown_approval_is_indistinguishable_from_someone_elses():
    """Không phân biệt "không tồn tại" với "của người khác" — tránh enumeration.

    Cùng lý do và cùng mã lỗi mà `turns.py` đã dùng cho `session_id`. Đây là **đổi hành
    vi có chủ đích** so với bản trước (404): giữ 404 cho id không tồn tại trong khi trả
    403 cho id của người khác thì chính cặp mã lỗi đó nói cho kẻ dò biết id nào có thật.
    """
    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/api/v1/approvals/appr-khongtontai/decision",
            headers={**({"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}), **_idem()},
            json=DECISION,
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_the_owner_can_still_decide():
    """Hàng rào không được chặn nhầm chính chủ."""
    with TestClient(app) as client:
        token = _login(client)
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        approval_id = _pending_approval_in(client, session_id)

        response = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={**({"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS}), **_idem()},
            json=DECISION,
        )

    assert response.status_code == 200
    assert response.json() == {"approval_status": "approved"}
    assert session_state.get_store().get(approval_id).status == "consumed"


def _pending(client) -> tuple[str, str]:
    token = _login(client)
    session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
    return token, _pending_approval_in(client, session_id)


def test_decision_thieu_x_schema_version_bi_tu_choi():
    """`api_spec.md:48` chốt route này bắt buộc `X-Schema-Version: 1.0` (issue #44)."""
    with TestClient(app) as client:
        token, approval_id = _pending(client)
        response = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idem-thieu-schema"},
            json=DECISION,
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


def test_decision_sai_x_schema_version_bi_tu_choi():
    with TestClient(app) as client:
        token, approval_id = _pending(client)
        response = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Schema-Version": "2.0",
                "Idempotency-Key": "idem-sai-schema",
            },
            json=DECISION,
        )

    assert response.status_code == 400


def test_decision_thieu_idempotency_key_bi_tu_choi():
    with TestClient(app) as client:
        token, approval_id = _pending(client)
        response = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"},
            json=DECISION,
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUEST_CONTEXT_INVALID"


def test_cung_idempotency_key_thi_lan_hai_tra_ban_ghi_cu_khong_chay_lai():
    """Ca thật của #44: double-click / client retry.

    Lớp này **độc lập** với `previous_status`: nó chặn ở tầng request, trước cả khi
    chạm vào store, nên nó còn tác dụng cả khi bản ghi đã đổi trạng thái vì lý do khác.
    """
    with TestClient(app) as client:
        token, approval_id = _pending(client)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "idem-double-click",
        }

        first = client.post(f"/api/v1/approvals/{approval_id}/decision", headers=headers, json=DECISION)
        second = client.post(f"/api/v1/approvals/{approval_id}/decision", headers=headers, json=DECISION)

    assert first.status_code == 200
    assert second.status_code == 200
    # Lần hai trả **đúng** phản hồi của lần một, không phải trạng thái mới sau khi
    # lệnh đã chạy — đó mới là ý nghĩa của "cùng một request".
    assert second.json() == first.json()


def test_cung_key_nhung_khac_noi_dung_thi_bao_xung_dot():
    """Khoá đã dùng cho một request khác nội dung là lỗi của client, không phải retry."""
    with TestClient(app) as client:
        token, approval_id = _pending(client)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "idem-doi-noi-dung",
        }

        client.post(f"/api/v1/approvals/{approval_id}/decision", headers=headers, json=DECISION)
        second = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers=headers,
            json={"decision": "reject", "approved_vehicle_state_version": 1},
        )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_loi_giua_chung_khong_lam_ket_idempotency_key(monkeypatch):
    """Lỗi thoáng qua không được biến thành hỏng vĩnh viễn cho một khoá.

    `IdempotencyStore` **không có TTL**: chỗ đã đặt mà không `finish`/`abandon` sẽ nằm
    lại mãi, và mọi lần thử lại với cùng khoá nhận 409 — đúng khoá mà client sẽ retry.
    """
    from src.api import approvals

    with TestClient(app) as client:
        token, approval_id = _pending(client)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Schema-Version": "1.0",
            "Idempotency-Key": "idem-loi-giua-chung",
        }

        real_store = approvals.get_store()

        class _Exploding:
            def __getattr__(self, name):
                return getattr(real_store, name)

            def decide(self, *args, **kwargs):
                raise RuntimeError("hỏng giữa chừng")

        monkeypatch.setattr(approvals, "get_store", lambda: _Exploding())
        with pytest.raises(RuntimeError):
            client.post(f"/api/v1/approvals/{approval_id}/decision", headers=headers, json=DECISION)

        # Cùng khoá, sau khi lỗi đã qua: phải chạy được, không kẹt ở 409.
        monkeypatch.setattr(approvals, "get_store", lambda: real_store)
        retry = client.post(f"/api/v1/approvals/{approval_id}/decision", headers=headers, json=DECISION)

    assert retry.status_code == 200
    assert retry.json()["approval_status"] == "approved"

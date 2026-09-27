"""RBAC của hai bề mặt kỹ sư — issue #45 (B1).

`docs/api_spec.md:8` chốt `/metrics/summary` là **Engineer-only** và trace là
owner/role-scoped. Trước ticket này `src/api/observability.py` gọi
`_require_engineer` — một hàm rỗng — nên cả hai endpoint trả 200 cho bất kỳ ai,
không cần token, không cần vai trò.

Các file test observability khác (`test_traces.py`, `test_metrics_summary.py`,
`test_observability_privacy.py`) giờ dùng fixture `engineer_client`, tức chúng
luôn chạy với token hợp lệ. Nếu ai đó gỡ `Depends(require_engineer)` thì những
file đó vẫn xanh hết — chỉ file này đỏ. Đó là lý do nó tồn tại riêng.

`X-Schema-Version` KHÔNG xuất hiện ở đây: đó là ràng buộc của POST
(`docs/api_spec.md` mục "Required POST context"), hai route này là GET.
"""

from __future__ import annotations

import pytest

from src.services.auth import get_auth_store
from src.services.trace_store import TraceStore, set_trace_store

#: Cả hai đường đọc, kiểm cùng một luật — tham số hoá để thêm route thứ ba là sửa
#: một dòng, thay vì nhân đôi bốn test.
ENGINEER_ONLY_PATHS = ["/api/v1/traces/tr_rbac_1", "/api/v1/metrics/summary"]


@pytest.fixture
def seeded_trace():
    """Trace có thật, để 404 không che mất 401/403.

    Không có nó thì `/traces/{id}` trả 404 cả khi RBAC đã hở, và test "không token
    thì 401" sẽ xanh vì lý do sai.
    """
    store = TraceStore(maxsize=4)
    set_trace_store(store)
    store.open("tr_rbac_1", "ses-1", "turn-1")
    return store


def _driver_token() -> str:
    return get_auth_store().login("driver.demo@example.com", "DemoDriver123!").token


@pytest.mark.parametrize("path", ENGINEER_ONLY_PATHS)
async def test_khong_token_thi_401_auth_required(client, seeded_trace, path):
    response = await client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("path", ENGINEER_ONLY_PATHS)
async def test_token_tai_xe_thi_403_forbidden(client, seeded_trace, path):
    """Token thật, chữ ký thật, vai trò sai — 403 chứ không phải 401."""
    response = await client.get(path, headers={"Authorization": f"Bearer {_driver_token()}"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", ENGINEER_ONLY_PATHS)
async def test_token_ky_su_thi_qua(engineer_client, seeded_trace, path):
    """Chứng thực dương: hai test trên không xanh vì route hỏng."""
    assert (await engineer_client.get(path)).status_code == 200


async def test_loi_auth_van_giu_dung_vo_error_envelope(client, seeded_trace):
    """`ApiError`, không phải `HTTPException` — xem `src/api/errors.py`.

    `HTTPException(detail=...)` bị FastAPI bọc thêm một tầng `{"detail": ...}`, vỡ
    hợp đồng envelope top-level mà mọi client đang đọc.
    """
    body = (await client.get("/api/v1/metrics/summary")).json()

    assert set(body) == {"error", "meta", "trace_id", "schema_version"}
    assert set(body["error"]) >= {"code", "message"}
    assert "detail" not in body

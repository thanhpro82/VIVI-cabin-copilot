"""`GET /api/v1/citations/{citation_id}` — Driver, chủ của lượt sinh ra citation.

`api_spec.md:62` chốt vai trò "Driver for own turn"; `:328` chốt Citation có đúng tám
field, đều bắt buộc, field lạ bị từ chối.
"""

from fastapi.testclient import TestClient

from src.api import session_state
from src.main import app
from src.rag.models import Citation
from src.services.citations import MAX_RECORDS, get_citation_store
from tests.conftest import seed_test_user

_SCHEMA_HEADERS = {"X-Schema-Version": "1.0"}
_LOGIN = {"email": "driver.demo@example.com", "password": "DemoDriver123!"}


def _login(client) -> str:
    return client.post("/api/v1/auth/login", headers=_SCHEMA_HEADERS, json=_LOGIN).json()["data"]["access_token"]


def _citation(citation_id: str = "cit_abc123") -> Citation:
    return Citation(
        citation_id=citation_id,
        turn_id="turn-1",
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="Công tắc khoá cửa sổ điện.",
        retrieval_score=0.9,
    )


def test_the_owner_gets_all_eight_fields():
    with TestClient(app) as client:
        token = _login(client)
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        get_citation_store().save([_citation()], session_id)

        response = client.get(
            "/api/v1/citations/cit_abc123",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "citation_id": "cit_abc123",
        "turn_id": "turn-1",
        "document_title": "Sổ tay VF9",
        "section": "Cửa sổ điện",
        "page": 87,
        "chunk_id": "c1",
        "excerpt": "Công tắc khoá cửa sổ điện.",
        "retrieval_score": 0.9,
    }


def test_without_a_token_it_is_rejected():
    with TestClient(app) as client:
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        get_citation_store().save([_citation()], session_id)

        response = client.get("/api/v1/citations/cit_abc123")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_another_users_citation_is_forbidden():
    with TestClient(app) as client:
        token = _login(client)
        other = session_state.create_session(seed_test_user("usr_driver_99"), "vehicle-demo-01").session_id
        get_citation_store().save([_citation()], other)

        response = client.get(
            "/api/v1/citations/cit_abc123",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_unknown_citation_is_not_found():
    """404 chứ không phải 403: thứ hỏng là cái id, không phải quyền của người gọi.

    Cùng lập luận mà `/traces/{trace_id}` đã chốt (`observability.py:72`,
    `TASK-BE-OBS-001 §4`): 403 "nói dối người gọi rằng họ thiếu quyền trong khi thứ họ
    hỏng là cái id".
    """
    with TestClient(app) as client:
        token = _login(client)

        response = client.get(
            "/api/v1/citations/cit_khong_ton_tai",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_citation_pushed_out_of_the_bounded_store_is_not_found_not_forbidden():
    """Đây mới là ca phổ biến, và là lý do thật để tách 404 khỏi 403.

    Trần LRU sinh ra để đẩy bản ghi cũ đi — đó là việc bình thường, không phải sự cố.
    Gộp nó vào 403 nghĩa là tài xế bấm vào thẻ citation **của chính mình** đang hiện
    trên màn hình và nhận "bạn không có quyền". Frontend cũng không có cách nào phân
    biệt "hết hạn" với "không phải của bạn" để hiển thị cho đúng.
    """
    with TestClient(app) as client:
        token = _login(client)
        session_id = session_state.create_session("usr_driver_01", "vehicle-demo-01").session_id
        store = get_citation_store()
        store.save([_citation("cit_se_bi_day_ra")], session_id)
        # Đẩy nó ra khỏi trần bằng chính đường mà production đẩy: ghi thêm.
        for index in range(MAX_RECORDS):
            store.save([_citation(f"cit_moi_{index}")], session_id)

        response = client.get(
            "/api/v1/citations/cit_se_bi_day_ra",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_citation_whose_session_is_unknown_is_not_found_not_forbidden():
    """Không xác định được chủ **không phải** là "thuộc về người khác".

    Ca này có thật và không cần race nào: `/turns/voice` (`turns.py:111`) và
    `/agent/process` đều nhận `session_id` tuỳ ý mà không gọi `create_session()`, nên
    citation sinh từ những lượt đó mồ côi ngay từ lúc sinh — không có `SessionRecord`
    nào để đối chiếu.

    Trả 403 ở đây là khẳng định một điều ta không chứng minh được. Ta chỉ biết mình
    không phân giải được chủ, nên nó thuộc cùng rổ với "đã bị đẩy khỏi kho": 404.
    """
    with TestClient(app) as client:
        token = _login(client)
        # Đúng thứ /turns/voice làm: session_id tuỳ ý, không qua create_session().
        get_citation_store().save([_citation("cit_mo_coi")], "ses-khong-dang-ky")

        response = client.get(
            "/api/v1/citations/cit_mo_coi",
            headers={"Authorization": f"Bearer {token}", **_SCHEMA_HEADERS},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_the_route_is_in_the_public_openapi_surface():
    """Một trong 14 interface P0 của api_spec.md — phải mô tả được ở /docs."""
    assert "/api/v1/citations/{citation_id}" in app.openapi()["paths"]


def test_citations_khai_schema_cho_nhanh_404_va_403():
    """Khai `description` mà quên `model` thì `/docs` im lặng về hình dạng lỗi.

    Cùng bất biến mà `test_traces_khai_schema_cho_nhanh_404` khoá cho `/traces`.
    """
    responses = app.openapi()["paths"]["/api/v1/citations/{citation_id}"]["get"]["responses"]

    for code in ("404", "403"):
        schema = responses[code].get("content", {}).get("application/json", {}).get("schema", {})
        assert schema.get("$ref") == "#/components/schemas/ErrorEnvelope", code

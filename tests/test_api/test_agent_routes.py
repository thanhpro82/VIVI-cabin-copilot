"""Route Họ A. Tên tool trong response là alias; trong plan vẫn là canonical."""


async def test_s1_command_returns_success_with_canonical_tool_name(client):
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Đặt điều hòa 22 độ", "vehicle_speed_kmh": 0.0, "session_id": "ses-a"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["intent"] == "hvac_temperature"
    assert body["hitl_pending"] is False
    assert body["tool_calls"] == [{"tool_name": "set_hvac_temperature", "parameters": {"temperature_c": 22}}]
    assert body["latency_ms"] >= 0


async def test_window_command_waits_for_confirmation_instead_of_executing(client):
    """SCRUM-18: tầng API bật HITL nên S2 trả `PENDING_HITL` kèm `hitl_action_id`.

    Trước khi có HITL, case này dừng ở `APPROVAL_REQUIRED` — cũng không thực thi,
    nhưng chưa có đường nào để người dùng đồng ý.
    """
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Mở cửa sổ bên lái 30 phần trăm", "vehicle_speed_kmh": 0.0, "session_id": "ses-b"},
    )
    body = response.json()
    assert body["status"] == "PENDING_HITL"
    assert body["hitl_pending"] is True
    assert body["hitl_action_id"].startswith("appr-")
    assert body["tool_calls"][0]["tool_name"] == "set_window_position"


async def test_door_while_moving_is_blocked_not_confirmed(client):
    """ADR-010: ngưỡng 5 km/h của ticket sẽ hỏi lại; canonical chặn thẳng."""
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Mở cửa bên lái", "vehicle_speed_kmh": 45.0, "session_id": "ses-c"},
    )
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["hitl_pending"] is False


async def test_out_of_range_is_denied(client):
    response = await client.post("/api/v1/agent/process", json={"query": "Đặt điều hòa 45 độ", "session_id": "ses-d"})
    assert response.json()["status"] == "DENIED"


async def test_empty_query_is_rejected_by_schema(client):
    response = await client.post("/api/v1/agent/process", json={"query": "", "session_id": "ses-e"})
    assert response.status_code == 422


async def test_sessions_do_not_share_vehicle_state(client):
    await client.post("/api/v1/agent/process", json={"query": "Đặt điều hòa 22 độ", "session_id": "ses-f"})
    response = await client.post("/api/v1/agent/process", json={"query": "Điều hòa", "session_id": "ses-g"})
    assert response.status_code == 200


# --- Dev-only: khong thuoc public surface P0 (review cua truong nhom) ---


def test_route_is_absent_from_the_public_openapi_surface():
    """`api_spec.md` chốt P0 đúng 14 interface và không có route agent tổng quát.

    `frontend/docs/ARCHITECTURE.md` (2026-08-07) đã loại `/agent/process` đích
    danh. Route này chỉ để chạy thử trong lúc phát triển, nên không được xuất
    hiện trong OpenAPI — nơi định nghĩa public surface.
    """
    from src.main import app

    assert "/api/v1/agent/process" not in app.openapi()["paths"]


async def test_route_returns_404_in_production(client, monkeypatch):
    from types import SimpleNamespace

    import src.api.agent_routes as agent_routes

    monkeypatch.setattr(agent_routes, "get_settings", lambda: SimpleNamespace(app_env="production"))
    response = await client.post("/api/v1/agent/process", json={"query": "Bật điều hòa"})
    assert response.status_code == 404


async def test_manual_answer_carries_the_citations_it_was_grounded_on(client, monkeypatch):
    """Phát hiện khi chạy demo: câu trả lời sổ tay chỉ là một câu cố định.

    `compose_node` trả đúng một câu cho mọi lượt tra cứu — nội dung thật nằm ở
    `citations` trong state. Không phơi ra thì IVI hiển thị "Đây là thông tin tôi
    tìm được trong sổ tay xe" mà **không có thông tin nào**, và người dùng không
    kiểm chứng được câu trả lời đến từ mục nào, trang nào.

    Test bơm graph giả để không phụ thuộc chỉ mục FAISS (không commit lên git).
    """
    import src.api.agent_routes as agent_routes
    from src.rag.models import Citation

    citation = Citation(
        citation_id="cit_test",
        turn_id="t1",
        document_title="VF9_23-25_VN_VI_2.4 [New UI]",
        section="Ghế và hệ thống an toàn / Ghế",
        page=14,
        chunk_id="chunk_1147249_011",
        excerpt="Massage ghế ngồi. Nếu được trang bị...",
        retrieval_score=0.898,
    )

    class GroundedGraph:
        async def ainvoke(self, _state, config=None):
            return {
                "outcome": "grounded_answer",
                "intent": "manual_query",
                "response_text": "Đây là thông tin tôi tìm được trong sổ tay xe.",
                "citations": [citation],
            }

    monkeypatch.setattr(agent_routes, "get_graph", lambda _session_id: GroundedGraph())
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Ghế xe có chức năng massage không?", "session_id": "ses-rag"},
    )
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert len(body["citations"]) == 1
    assert body["citations"][0] == {
        "section": "Ghế và hệ thống an toàn / Ghế",
        "page": 14,
        "excerpt": "Massage ghế ngồi. Nếu được trang bị...",
        "retrieval_score": 0.898,
        "document_title": "VF9_23-25_VN_VI_2.4 [New UI]",
    }


async def test_control_answer_has_no_citations(client):
    """Lệnh điều khiển không đi qua sổ tay — trường phải rỗng, không phải thiếu."""
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Đặt điều hòa 22 độ", "session_id": "ses-nocit"},
    )
    assert response.json()["citations"] == []


async def test_offer_has_its_own_status_not_clarify(client):
    """Phát hiện khi chạy demo: `offer` rơi vào CLARIFY vì thiếu khoá ánh xạ.

    IVI cần phân biệt "tôi chưa hiểu ý bạn" với "tôi hiểu rõ, đang đề nghị làm".
    """
    response = await client.post(
        "/api/v1/agent/process",
        json={"query": "Mở cửa sổ bên lái 30 phần trăm được không?", "session_id": "ses-offer"},
    )
    body = response.json()
    assert body["status"] == "OFFER"
    assert body["hitl_pending"] is False
    assert body["tool_calls"][0]["tool_name"] == "set_window_position"
    assert body["tool_calls"][0]["parameters"]["percent"] == 30

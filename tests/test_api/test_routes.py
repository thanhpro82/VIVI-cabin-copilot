import pytest


@pytest.mark.asyncio
async def test_chat_empty_message(client):
    response = await client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200


# -- bề mặt OpenAPI là hợp đồng, không phải phụ phẩm -------------------------
#
# `/docs` là thứ người làm frontend đọc thay cho tài liệu viết tay, nên nội dung
# của nó phải được khoá như mọi hợp đồng khác.


def _spec():
    from src.main import app

    return app.openapi()


def test_route_khong_thuoc_p0_khong_hien_trong_openapi():
    """`/chat`, `/status` và `/agent/process` không phải interface P0.

    `docs/api_spec.md:52` chốt P0 đúng 14 interface và `:71` ghi "there is no
    general-purpose public agent-processing route". Để chúng hiện trong `/docs`
    thì người đọc thấy endpoint không có trong hợp đồng và không biết tin cái nào.

    Ẩn khỏi schema **không** làm route ngừng hoạt động — `/api/v1/status` vẫn là
    healthcheck của container backend trong `docker-compose.yml`.
    """
    paths = set(_spec()["paths"])

    for leaked in ("/api/v1/chat", "/api/v1/status", "/api/v1/agent/process"):
        assert leaked not in paths, f"{leaked} không được xuất hiện trong OpenAPI"


def test_openapi_chi_phoi_dung_bon_interface_p0_da_implement():
    """Khoá bề mặt hiện có, để thêm/bớt route là phải sửa test này một cách có ý thức.

    WebSocket không nằm trong OpenAPI 3.0 nên `/ws/ivi` và `/ws/engineer` vắng mặt
    là đúng — hợp đồng của hai cái đó ở `docs/api_spec.md` §WebSocket contracts.

    `/vehicle/profile` là **interface thứ 13**, thêm ở issue #123 và đây chính là
    lần "sửa có ý thức" mà test này sinh ra để bắt. Căn cứ: nhánh áp suất lốp cần
    biết cấu hình xe *lúc chạy*, mà `api_spec.md:503` chỉ đưa ra `.env` + restart —
    restart giữa buổi demo thì mất cả state cache MQTT lẫn phiên đăng nhập. Nó không
    thuộc ba family bị cấm ở dòng đó (`/manuals/ingest`, `/eval/runs*`,
    `/model-profiles*`; cái cuối là profile *model LLM*, chuyện khác hẳn).

    `/vehicle/profile/options` là **interface thứ 14**, và là một sub-resource chứ
    không phải field thêm vào cái trên: `VehicleProfileUpdate` có `extra="forbid"` và
    đòi có mặt cả hai field, nên thêm `options` vào đó thì hoặc mọi client hiện có gãy
    422, hoặc phải nới đúng bất biến model ấy dựng lên. Căn cứ đầy đủ ở
    `docs/khao_sat_trang_bi.md`: 116 trên 482 chunk sổ tay gắn mệnh đề điều kiện trang
    bị, và composer đang đọc nguyên văn chữ "nếu được trang bị" cho tài xế tự đoán.

    `/metrics/eval-snapshot` là **interface thứ 15**, thêm 28/08. Căn cứ: khối
    "Đánh giá offline" của dashboard kỹ sư đang hiện số hard-code (`isMock: true`,
    ngày 07/08), mà browser thì không đọc được `eval/results/` từ filesystem. Nó
    **chỉ đọc** artifact bất biến và không bao giờ chạy eval — một request HTTP
    không được phép sinh ra bằng chứng. Nó cũng không gộp vào `/metrics/summary`:
    cái kia fold traffic vừa xảy ra trên máy này, cái này phát lại một phép đo đã
    đóng gói trên bộ đề có đáp án khoá, và hai loại số đó không cộng được.

    Nó **không** phạm family `/eval/runs*` bị cấm ở `api_spec.md:503`: family đó
    là bề mặt *quản trị vòng chấm* (tạo run, xếp hàng, huỷ). Đây là một phép đọc
    kết quả đã có, không có động từ nào ngoài GET.

    Sáu path `/routines*` (#282), hai path `/places*` (#283) và hai path chạy Routine
    (#286) **không** đánh số tiếp vào dãy interface P0.
    Chúng thuộc epic Routines MVP (#270), một phạm vi mở sau P0 và có product spec
    riêng (`docs/routines_product_spec.md`) — đếm chúng thành "interface thứ 16–21"
    sẽ làm con số P0 mất nghĩa. Cái mà test này khoá vẫn nguyên: thêm route là phải
    sửa danh sách dưới đây một cách có ý thức.
    """
    assert set(_spec()["paths"]) == {
        "/api/v1/turns/voice",
        "/api/v1/approvals/{approval_id}/decision",
        "/api/v1/vehicle/state",
        "/api/v1/vehicle/profile",
        "/api/v1/vehicle/profile/options",
        "/api/v1/traces/{trace_id}",
        "/api/v1/metrics/summary",
        "/api/v1/metrics/eval-snapshot",
        "/api/v1/auth/login",
        "/api/v1/sessions",
        "/api/v1/turns/text",
        "/api/v1/citations/{citation_id}",
        "/api/v1/routines",
        "/api/v1/routines/{routine_id}",
        "/api/v1/routines/{routine_id}/enabled",
        "/api/v1/routines/{routine_id}/restore-default",
        "/api/v1/places",
        "/api/v1/places/{label}",
        "/api/v1/routines/{routine_id}/run",
        "/api/v1/routine-executions/{execution_id}",
        "/api/v1/routine-executions/{execution_id}/cancel",
        "/healthz",
    }


def test_traces_khai_schema_cho_nhanh_404():
    """`NOT_FOUND` không có trong bảng mã lỗi gốc của api_spec.md.

    Quyết định thêm nó (thay vì dùng 403 để giấu sự tồn tại của trace) ghi ở
    docs/tasks/TASK-BE-OBS-001 §4. Test này khoá việc `/docs` phải mô tả nhánh đó,
    cùng lý do với `test_vehicle_state_khai_schema_cho_nhanh_503`.
    """
    spec = _spec()
    schema = (
        spec["paths"]["/api/v1/traces/{trace_id}"]["get"]["responses"]["404"]
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )

    assert schema.get("$ref") == "#/components/schemas/ErrorEnvelope"


def test_vehicle_state_khai_schema_cho_nhanh_503():
    """Khai `description` mà quên `model` thì `/docs` im lặng về hình dạng lỗi.

    Đúng lỗi đã mắc một lần: tài liệu bàn giao hứa "`/docs` mô tả cả nhánh lỗi"
    trong khi `ErrorEnvelope` còn chưa có trong `components.schemas`.
    """
    spec = _spec()
    schema = (
        spec["paths"]["/api/v1/vehicle/state"]["get"]["responses"]["503"]
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )

    assert schema.get("$ref") == "#/components/schemas/ErrorEnvelope"
    assert "ErrorEnvelope" in spec["components"]["schemas"]


def test_healthz_chua_khai_nhanh_503_trong_openapi():
    """Ghi nhận một khoảng trống **của người khác**, không tự vá.

    `GET /healthz` (PR #34, Thành) trả 503 bất cứ khi nào có component chưa ready
    — ở P0 là gần như luôn luôn, vì `llm` không chạy. Nhưng route không khai
    `responses={503: ...}` nên `/docs` đang nói nó chỉ trả 200.

    Test này khẳng định **hiện trạng**, không phải hành vi mong muốn. Nó sẽ đỏ
    ngay khi Thành bổ sung schema — lúc đó xoá test này đi, đó là dấu hiệu tốt.
    Cách vá: thêm `responses={503: {"model": ErrorEnvelope}}` như
    `/api/v1/vehicle/state` đã làm.
    """
    codes = set(_spec()["paths"]["/healthz"]["get"]["responses"])

    assert codes == {"200"}, (
        "/healthz giờ đã khai nhánh 503 — xoá test này và cập nhật docs/handoff/BE-to-FE-vehicle-and-mqtt.md"
    )

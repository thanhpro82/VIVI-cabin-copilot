import os

# Phải đặt TRƯỚC mọi import chạm `get_settings()`: từ issue #46 các store domain
# (users/sessions/approvals/idempotency) chạy trên SQLite, và nếu không nói gì thì
# chúng sẽ mở đúng `data/app.db` của máy dev. Test phải có DB sạch của riêng nó, và
# tuyệt đối không được ghi đè dữ liệu demo. `setdefault` để CI vẫn ép được biến này.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Số vòng PBKDF2 mặc định (200k) cộng ~9 s vào mỗi lần chạy suite vì test đăng nhập
# hàng trăm lần. Ở đây thứ được kiểm là *logic* xác thực, không phải độ cứng của KDF
# — nên hạ vòng. Production giữ mặc định; đừng đặt biến này ở `.env`.
os.environ.setdefault("AUTH_PBKDF2_ITERATIONS", "1000")
# Ghim `slm_enabled=False` — hành vi **mặc định P0** theo ADR-006/010/016 (issue #146).
#
# Không có dòng này thì một cờ trong `.env` của từng máy làm đỏ ba test vốn tồn tại để
# khoá đúng mặc định ấy (`test_slm_disabled_means_no_planner_and_no_behavior_change`,
# `test_model_profile_la_not_selected_o_p0`, `test_health_dung_shape_200_...`). Ai bật
# SLM để thử rồi quên tắt sẽ tưởng mình làm hỏng code; và tệ hơn theo chiều ngược lại,
# nếu một ngày mặc định của repo bị đổi thành `true` thì ba test ấy fail **vì đúng lý
# do** nhưng lẫn vào nhiễu nên dễ bị bỏ qua.
#
# Gán **cứng**, khác hai dòng trên: `setdefault` không đè biến đã export, nên máy nào
# `export SLM_ENABLED=true` vẫn đỏ y như cũ — tức vá không kín. Hai biến trên dùng
# `setdefault` vì CI có lý do chính đáng để ép chúng; còn cờ này thì ý định của test
# phải nằm trong test. Test nào cần nhánh SLM thì tự `monkeypatch` cờ lên.
os.environ["SLM_ENABLED"] = "false"

# Cùng lý do, cùng cách gán cứng: thác chọn câu nạp một cross-encoder 568M tham số.
#
# Không ghim thì suite đọc `.env` của người chạy. Trên máy đang bật cờ, đo 18/08: thời
# gian chạy đi từ ~100 s lên **325 s**, và với backend cùng llama-server đang chạy thì
# nó **segfault** — access violation ngay lúc nạp trọng số E5, máy còn 0,3 GB RAM.
#
# Đó không phải lỗi của mã, nhưng nó là lỗi của suite: một bộ test đỏ tuỳ theo máy thì
# không phân biệt được hồi quy với hết bộ nhớ. Test nào cần thác thì tự `monkeypatch`.
os.environ["CHON_CAU_THAC_ENABLED"] = "false"

from unittest.mock import AsyncMock  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.mqtt_client import ensure_selector_event_loop

# Test MQTT cần selector loop trên Windows — xem ensure_selector_event_loop.
ensure_selector_event_loop()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def driver_client(client):
    """`client` đã mang sẵn bearer token vai trò **driver**.

    Cùng khuôn và cùng lý do với `engineer_client` ngay dưới. Trả về **chính** object
    `client` chứ không phải một client mới, nên một test chỉ cần thêm `driver_client`
    vào chữ ký là mọi lời gọi `client.…` sẵn có tự mang token — không phải sửa từng dòng.
    """
    from src.services.auth import get_auth_store
    from tests.test_api.ws_helpers import DRIVER_CREDENTIALS

    record = get_auth_store().login(*DRIVER_CREDENTIALS)
    client.headers["Authorization"] = f"Bearer {record.token}"
    return client


@pytest_asyncio.fixture
async def engineer_client(client):
    """`client` đã mang sẵn bearer token vai trò **engineer**.

    Từ issue #45 (B1), `/traces/{id}` và `/metrics/summary` đi qua
    `Depends(require_engineer)` nên gọi trần trả 401. Đăng nhập thẳng vào
    `AuthStore` thay vì `POST /auth/login`: token là thứ duy nhất cần, và một
    vòng HTTP nữa chỉ làm mỗi test chậm thêm mà không kiểm thêm gì —
    `tests/test_api/test_auth_routes.py` đã lo đường login.

    Chạy SAU `_reset_session_state` (autouse được dựng trước fixture được yêu cầu
    tường minh ở cùng scope), nên token này không bị `auth.reset()` xoá mất.
    """
    from src.services.auth import get_auth_store
    from tests.test_api.ws_helpers import ENGINEER_CREDENTIALS

    record = get_auth_store().login(*ENGINEER_CREDENTIALS)
    client.headers["Authorization"] = f"Bearer {record.token}"
    return client


@pytest.fixture
def clock():
    """Dong ho gia cho VehicleStateCache — xem tests/mqtt_rig.py."""
    from tests.mqtt_rig import FakeClock

    return FakeClock()


@pytest_asyncio.fixture
async def rig(clock):
    """Chuoi MQTT day du tren InMemoryBroker (tang L1).

    Khai o day chu khong o tests/test_vehicle/conftest.py vi tests/test_api/ cung
    can dung giàn nay, ma conftest cua thu muc con khong hien sang thu muc khac.
    """
    from tests.mqtt_rig import build_rig, teardown_rig

    built = await build_rig(clock=clock)
    yield built
    await teardown_rig(built)


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock


@pytest.fixture(autouse=True)
def _reset_session_state():
    """Simulator/graph/store/auth/idempotency/ivi_events/citations song o module level nen phai don giua cac test."""
    from src.api import session_state
    from src.services import auth, citations, idempotency, ivi_events, vehicle_profile

    session_state.reset()
    auth.reset()
    idempotency.reset()
    ivi_events.reset()
    citations.reset()
    vehicle_profile.reset()
    yield
    session_state.reset()
    auth.reset()
    idempotency.reset()
    ivi_events.reset()
    citations.reset()
    vehicle_profile.reset()


@pytest.fixture(autouse=True)
def _reset_app_mqtt():
    """`app.state.mqtt` va vehicle gateway deu la bien toan cuc song qua ca suite.

    Test nao can broker thi tu gan runtime/gateway cua minh vao; neu test do no
    giua chung thi `finally` khong chay va cac test sau se chay voi runtime cua
    test truoc — tuc la 503 that lai thanh 200 gia, hoac nguoc lai. Fixture nay
    dong han lop loi do, nen cac test khong con phai tu don trong try/finally.
    """
    from src.services.ui_policy import get_ui_policy_emitter
    from src.services.vehicle_gateway import reset_vehicle_gateway

    app.state.mqtt = None
    reset_vehicle_gateway()
    # `_last` của emitter sống ở module level cùng với cổng xe, nên phải dọn cùng nhịp:
    # giữ lại policy của test trước thì test sau cho xe chạy sẽ không thấy event nào.
    get_ui_policy_emitter().reset()
    yield
    app.state.mqtt = None
    reset_vehicle_gateway()
    get_ui_policy_emitter().reset()


@pytest.fixture(autouse=True)
def _reset_observability():
    """Kho trace va bus engineer cung song o module level.

    Khong don thi trace cua test truoc con nam trong cua so rolling cua test sau,
    va `/metrics/summary` se dem ca luot cua test khac — dung loai loi ma
    `_reset_app_mqtt` da dong lai cho gateway.
    """
    from src.services.engineer_events import reset_engineer_bus
    from src.services.trace_store import reset_trace_store

    reset_trace_store()
    reset_engineer_bus()
    yield
    reset_trace_store()
    reset_engineer_bus()


def seed_test_user(user_id: str, *, role: str = "driver") -> str:
    """Chèn một user tối thiểu để test dựng được phiên **của người khác**.

    `sessions.user_id` là FOREIGN KEY tới `users(id)` (khôi phục theo review PR #89 của
    Thành), nên `create_session("usr_driver_99", ...)` sẽ `IntegrityError` nếu user đó
    không tồn tại. Ba test cổng sở hữu cần đúng thứ đó: một chủ nhân **khác** người
    đang gọi. Seed một user vứt đi rẻ hơn nhiều so với bỏ FK và cho phép session mồ côi.

    Không đặt mật khẩu dùng được: user này chỉ để làm chủ sở hữu, không để đăng nhập.
    """
    from src.db import get_connection

    connection = get_connection()
    connection.execute(
        "INSERT OR IGNORE INTO users (id, email, password_hash, role, display_name) VALUES (?, ?, '', ?, ?)",
        (user_id, f"{user_id}@test.invalid", role, user_id),
    )
    connection.commit()
    return user_id

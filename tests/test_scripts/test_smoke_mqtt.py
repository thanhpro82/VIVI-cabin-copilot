"""Phần auth WebSocket của `scripts/smoke_mqtt.py` — issue #143.

Script này không có test nào cho tới khi nó hỏng lặng: `/ws/engineer` siết auth
(`vivi.v1` + `bearer.<base64url-token>` của tài khoản engineer), script thì vẫn nối
trần, và vì nó index thẳng `payload.vehicle_state` của tin nhắn đầu tiên nên lỗi
handshake hiện ra dưới dạng `KeyError: 'vehicle_state'` — một thông báo không dẫn
người đọc tới đâu cả.

Ba thứ được khoá ở đây, và chỉ ba thứ:

1. **Đối xứng encode/decode.** `bearer_subprotocol` phải là nghịch đảo của
   `_decode_bearer_subprotocol` (`src/api/ws.py`) — cùng hàm server thật dùng, không
   phải bản chép lại. Bỏ padding `=` là bắt buộc chứ không phải thẩm mỹ: RFC 6455 chỉ
   cho ký tự token hợp lệ trong tên subprotocol.
2. **Origin đi theo `cors_origins`.** Điều kiện thứ hai của handshake, và là chỗ chỉ lộ
   ra sau khi token đã đúng — nó cũng trả `4403` y hệt sai role.
3. **Nhánh từ chối phải đọc được.** Đây là chính hồi quy của #143.

Cả ba chạy được trên CI vì thuần hàm — không cần broker, backend hay socket nào.
"""

import base64
import json

import pytest

from scripts.smoke_mqtt import (
    SmokeAbortedError,
    allowed_origin,
    bearer_subprotocol,
    first_state_event,
)
from src.api.ws import _decode_bearer_subprotocol
from src.config import Settings


class FakeSocket:
    """Chỉ trả sẵn một hàng event JSON — `first_state_event` không cần gì hơn."""

    def __init__(self, events: list[str]) -> None:
        self._events = list(events)

    async def recv(self) -> str:
        if not self._events:
            raise AssertionError("first_state_event đọc quá số event đã dựng")
        return self._events.pop(0)


def _event(event_type: str, payload: dict) -> str:
    return json.dumps({"type": event_type, "sequence": 1, "payload": payload})


# --- 1. doi xung encode/decode --------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "tok_abc",  # do dai chia het cho 3 -> khong padding
        "tok_abcd",  # du 1 -> padding "=="
        "tok_abcde",  # du 2 -> padding "="
        "tok_" + "x" * 64,
    ],
)
def test_bearer_subprotocol_la_nghich_dao_cua_decoder_server(token):
    """Vòng tròn khép kín với chính hàm server dùng, ở mọi dư số padding."""
    offered = ["vivi.v1", bearer_subprotocol(token)]

    assert _decode_bearer_subprotocol(offered) == token


def test_bearer_subprotocol_khong_con_padding():
    """`=` không phải ký tự token hợp lệ của RFC 6455 — còn nó là handshake hỏng."""
    encoded = bearer_subprotocol("tok_abcd").removeprefix("bearer.")

    assert "=" not in encoded
    # Vẫn phải là base64url thật, không phải cắt bừa.
    assert base64.urlsafe_b64decode(encoded + "==").decode() == "tok_abcd"


# --- 1b. Origin doc tu settings, khong hard-code ---------------------------


def test_allowed_origin_theo_cors_origins_chu_khong_hard_code():
    """Máy đổi `CORS_ORIGINS` thì script phải đi theo, không kẹt ở localhost:3000."""
    settings = Settings(cors_origins="https://ivi.p192.local, http://localhost:3000")

    assert allowed_origin(settings) == "https://ivi.p192.local"


def test_cors_origins_rong_thi_bao_ngay_thay_vi_de_server_dong_4403():
    """Không Origin nào hợp lệ thì WS chắc chắn 4403 — nói thẳng, đừng để đoán."""
    with pytest.raises(SmokeAbortedError, match="cors_origins"):
        allowed_origin(Settings(cors_origins="  ,  "))


# --- 2. nhanh tu choi phai doc duoc ----------------------------------------


async def test_event_error_bao_ma_loi_chu_khong_phai_keyerror():
    """Hồi quy #143: bản cũ nổ `KeyError: 'vehicle_state'` ở đây."""
    socket = FakeSocket([_event("error", {"code": "AUTH_REQUIRED", "message": "thiếu hoặc hết hạn token"})])

    with pytest.raises(SmokeAbortedError) as excinfo:
        await first_state_event(socket)

    assert "AUTH_REQUIRED" in str(excinfo.value)


async def test_bo_qua_event_khac_va_lay_dung_state():
    """Server bơm `metrics` ngay lúc handshake, nên tin đầu tiên **không** chắc là `state`."""
    socket = FakeSocket(
        [
            _event("metrics", {"model_runtime": "not-selected"}),
            _event("state", {"vehicle_state": {"hvac": {"temperature_c": 22.0}}}),
        ]
    )

    event = await first_state_event(socket)

    assert event["payload"]["vehicle_state"]["hvac"]["temperature_c"] == 22.0

"""Ghép mảnh trả lời, đi hết đường thật: HTTP -> graph -> policy -> HITL (issue #148).

`tests/test_agents/test_ghep_hoi_lai.py` khoá cổng ghép ở mức node. File này khoá thứ
khác, và là thứ dễ hỏng lặng hơn: **lệnh ghép ra vẫn phải đi qua policy/safety như một
lượt bình thường**. Một tầng "hiểu ngữ cảnh" mà lỡ tay nối thẳng tới executor thì nó vừa
tiện vừa là một đường vòng qua cổng HITL.

Ngữ cảnh sống trong checkpoint LangGraph khoá theo `thread_id = session_id`, nên hai lượt
phải cùng một `session_id` — đúng như tài xế thật.
"""

import uuid

from fastapi.testclient import TestClient

from src.api.session_state import get_store
from src.main import app

_H = {"X-Schema-Version": "1.0"}


def _login(client) -> str:
    r = client.post(
        "/api/v1/auth/login", headers=_H, json={"email": "driver.demo@example.com", "password": "DemoDriver123!"}
    )
    return r.json()["data"]["access_token"]


def _phien(client, token: str) -> str:
    r = client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}", **_H, "Idempotency-Key": f"s-{uuid.uuid4().hex[:12]}"},
        json={"vehicle_id": "vehicle-demo-01"},
    )
    return r.json()["data"]["session_id"]


def _hoi_lai(data: dict) -> bool:
    """Lượt này có phải một câu hỏi lại không.

    **Không** đọc `status`: một lượt `clarify` của router vẫn trả HTTP `status
    "completed"` — chỉ `approval_already_pending` mới map sang `"clarify"`
    (`src/api/turns.py:502`). Đó là hành vi có sẵn, không phải thứ issue này đổi; nhưng
    một test đọc `status` ở đây sẽ xanh/đỏ vì lý do chẳng liên quan.
    """
    return data.get("action_plan") is None and "Tôi chưa" in (data["response"]["speak_text"] or "")


def _noi(client, token: str, sid: str, text: str) -> dict:
    r = client.post(
        "/api/v1/turns/text",
        headers={"Authorization": f"Bearer {token}", **_H, "Idempotency-Key": f"t-{uuid.uuid4().hex[:12]}"},
        json={"session_id": sid, "text": text},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_manh_tra_loi_ghep_thanh_lenh_s2_van_phai_qua_cong_phe_duyet():
    """Chuỗi hai slot rồi ra một lệnh **S2** — và nó dừng ở `waiting_approval`.

    Cửa sổ luôn là S2 (`docs/safety_and_hitl.md`), nên nếu tầng ghép có đường tắt nào
    tới executor thì test này thấy `completed` thay vì `waiting_approval`.
    """
    with TestClient(app) as client:
        token = _login(client)
        sid = _phien(client, token)

        assert _hoi_lai(_noi(client, token, sid, "mở cửa sổ"))
        assert _hoi_lai(_noi(client, token, sid, "bên lái"))
        ba = _noi(client, token, sid, "30 phần trăm")

        assert ba["status"] == "waiting_approval", ba
        assert ba["action_plan"]["requires_approval"] is True
        assert ba["action_plan"]["steps"][0]["tool"] == "set_window_position"
        assert ba["action_plan"]["steps"][0]["args"] == {"window": "front_left", "percent": 30}
        assert get_store().get(ba["pending_approval"]["approval_id"]).status == "pending"


def test_manh_tra_loi_ghep_thanh_lenh_s1_thi_chay_that():
    """Nửa còn lại: S1 không có gì để hỏi, nên nó phải chạy tới nơi.

    Cùng lúc khoá ca đầu bảng của issue — lượt 1 nêu **hai** ý, chỉ thiếu một slot, và
    bản ghép phải lấy lại **cả hai** chứ không chỉ cái vừa điền.
    """
    with TestClient(app) as client:
        token = _login(client)
        sid = _phien(client, token)

        assert _hoi_lai(_noi(client, token, sid, "chỉnh quạt gió mức 2 điều hòa"))
        hai = _noi(client, token, sid, "18 độ")

        assert hai["status"] == "completed", hai
        tools = {b["tool"] for b in hai["action_plan"]["steps"]}
        assert tools == {"set_hvac_fan_level", "set_hvac_temperature"}, tools


def test_cau_hoi_so_tay_giua_chung_khong_bi_nuot_va_xoa_luon_ngu_canh():
    """Hỏi sổ tay giữa lúc đang có câu hỏi lại là một luồng hợp lệ, không được cướp.

    Và lượt ấy quét sạch ngữ cảnh, nên mảnh trả lời tới **sau** nó không còn gì để ghép
    — chốt "chỉ lượt kế tiếp ngay sau", đo ở mức API chứ không chỉ ở mức node.
    """
    with TestClient(app) as client:
        token = _login(client)
        sid = _phien(client, token)

        _noi(client, token, sid, "chỉnh quạt gió")
        giua = _noi(client, token, sid, "đèn cảnh báo hiển thị ở chỗ nào")
        assert not _hoi_lai(giua), giua

        sau = _noi(client, token, sid, "mức 2")

        assert sau.get("action_plan") is None, sau

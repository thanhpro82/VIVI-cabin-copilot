"""Plan của SLM lệch miền so với câu nói thì **không sinh plan**. Yêu cầu (b), review #324.

Bốn ca dưới đây là output thật của Qwen3-4B, không phải tình huống nghĩ ra
(`eval/results/planner-args/20260827T000533.480803Z`):

```
'bật đèn trần lên'  -> set_hvac_power{enabled:true}      nói ĐÈN, ra ĐIỀU HOÀ
'bật đèn chiếu gần' -> set_hvac_temperature{26}          nói ĐÈN, ra ĐIỀU HOÀ
'mở cốp sau'        -> set_door_state{rear_left, open}   nói CỐP, ra CỬA
'mở youtube'        -> set_hvac_temperature{26}          nói ỨNG DỤNG, ra ĐIỀU HOÀ
```

Trước #269 chúng chết ở `clarify` vì args sai schema — vô hại nhưng vì lý do sai. Sau
#269 args luôn hợp lệ, nên chúng đi tiếp thành hành động cụ thể. Cổng này là thứ thay
chỗ cái vô hại tình cờ ấy bằng một luật có tên.
"""

from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.cong_mien_slm import lech_y
from src.agents.graph import build_graph
from src.agents.slm import parse_slm_output
from src.services.vehicle_gateway import InProcessVehicleGateway


def _plan(tool: str, args: dict):
    raw = json.dumps(
        {
            "kind": "plan",
            "schema_version": "1.0",
            "steps": [{"step_id": "step-1", "ordinal": 0, "tool": tool, "args": args, "depends_on": []}],
        },
        ensure_ascii=False,
    )
    return parse_slm_output(raw)


class _StubPlanner:
    def __init__(self, tool: str, args: dict) -> None:
        self._raw = json.dumps(
            {
                "kind": "plan",
                "schema_version": "1.0",
                "steps": [{"step_id": "step-1", "ordinal": 0, "tool": tool, "args": args, "depends_on": []}],
            },
            ensure_ascii=False,
        )

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        return self._raw


#: **Cả năm** ca sai đo được, không phải bốn. Ca cuối là ca mà bản gác-theo-miền để lọt
#: và @thanhpro82 bác ở vòng review thứ hai.
LECH = [
    ("bật đèn trần lên", "set_hvac_power", {"enabled": True}),
    ("bật đèn chiếu gần", "set_hvac_temperature", {"temperature_c": 26}),
    ("mở cốp sau", "set_door_state", {"door": "rear_left", "state": "open"}),
    ("mở youtube", "set_hvac_temperature", {"temperature_c": 26}),
    ("đặt quạt gió mức 2", "set_hvac_power", {"enabled": True}),
]


@pytest.mark.parametrize(("cau", "tool", "args"), LECH, ids=[c for c, _, _ in LECH])
def test_bon_ca_do_duoc_deu_bi_bat_la_lech_mien(cau, tool, args):
    assert lech_y(cau, _plan(tool, args)) == tool


#: Ca cho phép thử **hết graph**. Bốn câu ở `LECH` không dùng được ở đây, vì chúng là
#: câu router luật **bắt được** (`"bật đèn trần lên"` → `set_interior_light`) nên planner
#: không bao giờ được gọi — test sẽ xanh vì một lý do sai. Bốn câu dưới đây nhắc đúng một
#: miền mà vẫn rơi `default_to_manual`, tức đi đúng đường SLM.
LECH_QUA_GRAPH = [
    ("xử lý cái đèn trần giùm", "lights", "set_hvac_power", {"enabled": True}),
    ("làm cái đèn trần đi", "lights", "set_hvac_temperature", {"temperature_c": 26}),
    ("cái cốp sau xử lý giùm", "trunk", "set_door_state", {"door": "rear_left", "state": "open"}),
    ("đèn trần làm gì đó đi", "lights", "set_door_state", {"door": "front_left", "state": "open"}),
    # Ca thứ năm — cùng miền `hvac` nhưng sai tool. Đây là ca @thanhpro82 bác ở vòng
    # review thứ hai, và nó phải có mặt ở tầng end-to-end chứ không chỉ ở unit test.
    ("xử lý cái quạt gió giùm", "hvac", "set_hvac_power", {"enabled": True}),
]


@pytest.mark.parametrize(
    ("cau", "mien", "tool", "args"), LECH_QUA_GRAPH, ids=[c for c, _, _, _ in LECH_QUA_GRAPH]
)
async def test_khong_sinh_plan_va_zero_side_effect(cau, mien, tool, args):
    """Điều kiện của review: *"không sinh plan, không publish/không thực thi"*.

    Đo bằng `command_count` — đúng cái đếm lệnh publish — nên số 0 ở đây nghĩa là không
    có side effect nào, không phải "không tìm thấy assertion nào để sai".
    """
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, planner=_StubPlanner(tool, args), checkpointer=InMemorySaver())

    ket_qua = await graph.ainvoke(
        {"query": cau, "session_id": "ses-lech", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": f"t-{cau}"}},
    )

    assert gateway.command_count == 0, "plan lệch miền vừa chạm tới xe"
    assert ket_qua.get("action_plan") is None
    assert ket_qua.get("candidate_action_plan") is None
    assert ket_qua["outcome"] != "control"


async def test_doi_chung_plan_dung_mien_van_di_tiep():
    """Không có ca này thì `command_count == 0` ở trên có thể xanh vì cổng chặn TẤT CẢ,
    hoặc vì planner chưa từng được gọi.

    Câu nhắc miền `lights` + plan `set_interior_light` là cùng miền, nên nó phải đi tiếp
    — tới `approval_required`, vì mọi plan `route_source == "slm"` đều phải duyệt
    (`policy.py:142`) — chứ không bị cổng miền nuốt.
    """
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(
        gateway,
        planner=_StubPlanner("set_interior_light", {"enabled": True}),
        checkpointer=InMemorySaver(),
    )

    ket_qua = await graph.ainvoke(
        {"query": "xử lý cái đèn trần giùm", "session_id": "ses-dung", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "t-dung"}},
    )

    assert ket_qua["outcome"] == "approval_required"
    assert ket_qua["route_source"] == "slm"


def test_cau_khong_nhac_mien_nao_thi_khong_chan():
    """Cổng cố ý HẸP. Phần lớn câu tới đường SLM là câu router không khớp được; bắt
    chúng phải khai miền là dựng lại chính bộ luật mà planner sinh ra để thay thế."""
    assert lech_y("làm gì đó giùm tôi", _plan("set_hvac_power", {"enabled": True})) is None


def test_lenh_ghep_nhan_hop_cua_ca_hai_ve():
    """`"bật điều hòa và mở nhạc"` là lệnh ghép hợp lệ — cả tool hvac lẫn `media_control`
    đều phải được nhận.

    Bản đầu bỏ gác hẳn khi câu nhắc nhiều thứ. An toàn hơn về mặt chặn nhầm, nhưng nó bỏ
    luôn phần bắt được — mà lệnh ghép mới là chỗ dễ lẫn tool nhất. Lấy **hợp** thì vừa
    không chặn nhầm vừa còn gác.
    """
    assert lech_y("bật điều hòa và mở nhạc", _plan("media_control", {"action": "play"})) is None
    assert lech_y("bật điều hòa và mở nhạc", _plan("set_hvac_power", {"enabled": True})) is None
    # Nhưng một tool KHÔNG thuộc vế nào thì vẫn bị chặn.
    lech = lech_y("bật điều hòa và mở nhạc", _plan("set_door_state", {"door": "front_left", "state": "open"}))
    assert lech == "set_door_state"


def test_ba_muc_chi_tiet_trong_hvac_khong_de_lot_lan_nhau():
    """Ca mà bản gác-theo-MIỀN để lọt, và là lý do cổng phải gác ở mức TOOL.

    Trong `hvac` có ba tool làm ba việc khác hẳn nhau. `"quạt gió"` chỉ nói về một trong
    ba, còn `"điều hòa"` nói chung nên nhận cả ba — nếu không thì `"bật điều hòa"` +
    `set_hvac_power` (hoàn toàn đúng) sẽ bị chặn nhầm.
    """
    assert lech_y("đặt quạt gió mức 2", _plan("set_hvac_power", {"enabled": True})) == "set_hvac_power"
    assert lech_y("đặt quạt gió mức 2", _plan("set_hvac_fan_level", {"level": 2})) is None

    assert lech_y("bật điều hòa", _plan("set_hvac_power", {"enabled": True})) is None
    assert lech_y("bật điều hòa 22 độ", _plan("set_hvac_temperature", {"temperature_c": 22})) is None
    assert lech_y("điều hòa quạt mạnh lên", _plan("set_hvac_fan_level", {"level": 3})) is None


def test_den_trong_xe_va_den_ngoai_xe_la_hai_tool_khac_nhau():
    """Cùng chữ "đèn" nhưng hai tool, và nhầm giữa chúng là bật đèn pha giữa ban ngày
    khi tài xế xin đèn đọc sách."""
    assert lech_y("bật đèn trần", _plan("set_headlight_mode", {"mode": "low_beam"})) == "set_headlight_mode"
    assert lech_y("bật đèn pha", _plan("set_interior_light", {"enabled": True})) == "set_interior_light"

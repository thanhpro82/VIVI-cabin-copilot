"""Tài xế nói "thôi" để đuổi trợ lý đi — phanh 3 của spec §3.3.

Không có nó thì cách duy nhất đóng một cửa sổ nghe tiếp đang mở là **im lặng 6 giây**, mà
trong xe có người ngồi cạnh đang nói chuyện thì sáu giây im lặng gần như không tới.

## Phạm vi hẹp hơn spec, và đó là kết luận của một phép đo

Spec §3.3 liệt kê cả `"cảm ơn"` và `"đủ rồi"`. Bỏ cả hai, vì hai lý do đo được (29/08):

1. `doc_tra_loi_co_khong("cảm ơn")` trả `None` — `"cảm ơn"` **không** nằm trong bảng từ
   chối, và đúng ra là không nên nằm: thêm nó vào là dạy cổng phê duyệt HITL đọc một lời
   cảm ơn thành một lời **bác** một lệnh S2.
2. `"Cảm ơn nhé"` là **một ca trong `eval/datasets/agent/chitchat-v1`** — workstream SP-2
   sở hữu nó. Nuốt nó vào `giai_tan` là lấy mất một ca khỏi bộ đo của người khác, và làm
   thế trong im lặng thì cổng cứng `cong_cung_bay_sang_chitchat` của họ đo một hệ đã đổi.

Nên cổng này chỉ nhận đúng những gì `doc_tra_loi_co_khong` **đã** đọc là "không", không
một chữ nào thêm. Soát cả năm bộ đo: **0 ca** bị cổng nuốt.
"""

from __future__ import annotations

import pytest

from src.agents.nghe_tiep import con_nghe_tiep
from src.agents.nodes.route import make_route_node
from src.agents.router import DeterministicControlRouter


class Phien:
    def __init__(self) -> None:
        self.node = make_route_node(DeterministicControlRouter())
        self.state: dict = {}

    async def noi(self, text: str) -> dict:
        self.state["query"] = text
        update = await self.node(self.state)
        self.state.update(update)
        return update


@pytest.mark.parametrize("cau", ["thôi", "Thôi", "thôi nhé", "không cần", "khỏi", "thôi vậy"])
async def test_cau_giai_tan_dong_cua_so(cau: str):
    p = Phien()
    ra = await p.noi(cau)
    assert ra["outcome"] == "not_control"
    assert ra["route_reason"] == "giai_tan"
    assert con_nghe_tiep(ra) is False


async def test_giai_tan_khong_cuop_luot_tu_choi_de_nghi():
    """Thứ tự bắt buộc: khi có `offer` treo, `"thôi"` nghĩa là **từ chối đề nghị** (#367),
    không phải đuổi trợ lý. Hai lối ra khác nhau và tài xế cần nghe đúng câu — *"Vâng, tôi
    không thực hiện."* nói về việc vừa được đề nghị, còn *"Vâng."* thì không nói về gì cả.
    """
    p = Phien()
    await p.noi("Bật điều hòa được không")
    ra = await p.noi("thôi")
    assert ra["route_reason"] == "offer_declined"


async def test_giai_tan_khong_nuot_duong_ghep_cua_luot_sau():
    """Sau một câu hỏi lại, `"thôi"` không phải câu trả lời cho slot — nhưng nó cũng
    **không được xoá ngữ cảnh**: tài xế có thể đổi ý và trả lời ở lượt kế tiếp.
    """
    p = Phien()
    await p.noi("Tăng quạt gió")
    assert (await p.noi("thôi"))["route_reason"] == "giai_tan"
    ra = await p.noi("mức 2")
    assert ra["outcome"] == "control"
    assert {b.tool for b in ra["candidate_action_plan"].steps} == {"set_hvac_fan_level"}


@pytest.mark.parametrize(
    "cau",
    [
        "Bật điều hòa",
        "Tắt nhạc",
        "Camp Mode là gì",
        # Có tiếng "thôi" nhưng là một LỆNH. `doc_tra_loi_co_khong` đòi mọi từ là từ đáp
        # hoặc từ đệm, nên nó trả `None` — cổng không đụng tới.
        "thôi tắt nhạc đi",
        # Của workstream chitchat (SP-2), phải để nguyên cho họ.
        "cảm ơn nhé",
        "đủ rồi",
    ],
)
async def test_cau_khac_khong_bi_doc_thanh_giai_tan(cau: str):
    p = Phien()
    assert (await p.noi(cau))["route_reason"] != "giai_tan", cau


async def test_giai_tan_noi_mot_cau_ngan_chu_khong_tra_so_tay():
    """`not_control` mặc định **đi tra sổ tay**, nên lối ra này phải có nhãn riêng — nếu
    không thì tài xế đuổi trợ lý lại được đọc cho nghe một đoạn sổ tay về chữ "thôi"."""
    from src.agents.nodes.compose import compose_node

    p = Phien()
    await p.noi("thôi")
    ra = await compose_node(p.state)
    assert "sổ tay" not in ra["speak_text"]
    assert len(ra["speak_text"]) <= 40
    assert ra["has_more_to_read"] is False


async def test_giai_tan_xoa_payload_routine_treo_tu_luot_truoc():
    """Review PR #404: lượt trước để lại `routine_setup_required` (backend vừa từ chối
    voice-run vì thiếu địa điểm), lượt này tài xế nói "thôi" đi thẳng nhánh `giai_tan` —
    một lối ra sớm của `route_node`. Thiếu phép xoá ở đây thì `assistant_response_payload`
    (không gate theo `outcome`) phát lại đúng payload cũ kèm `turn_id` mới, khiến FE tưởng
    có tín hiệu mới và mở lại màn thiết lập. Cùng một lỗ, kiểm luôn `routine_preview`."""
    p = Phien()
    p.state["routine_setup_required"] = {"routine_id": "rtn_1", "ma_loi": "chua_dat_dia_diem", "thieu": ["office"]}
    p.state["routine_preview"] = {"routine_id": "rtn_1", "routine_name": "Đi làm", "steps": []}
    ra = await p.noi("thôi")
    assert ra["route_reason"] == "giai_tan"
    assert ra["routine_setup_required"] is None
    assert ra["routine_preview"] is None


async def test_khong_bo_dau_hieu_nao_cua_bo_do_hien_co():
    """Soát ngược: cổng này chỉ nhận đúng những gì `doc_tra_loi_co_khong` đã đọc là
    "không". Viết ra thành test để một lần nới bảng từ chối sau này lộ ra ở đây, chứ
    không lặng lẽ nuốt thêm ca của bộ đo khác."""
    import json

    from src.agents.voice_intent import doc_tra_loi_co_khong

    for path in (
        "eval/datasets/agent/chitchat-v1/cases.jsonl",
        "eval/datasets/agent/v3/cases.jsonl",
        "eval/datasets/agent/bao-loi-2408/cases.jsonl",
    ):
        with open(path, encoding="utf-8") as f:
            nuot = [
                json.loads(dong)["input_text"]
                for dong in f
                if dong.strip() and doc_tra_loi_co_khong(json.loads(dong)["input_text"]) == "khong"
            ]
        assert nuot == [], f"{path} có ca bị cổng giải tán nuốt: {nuot}"

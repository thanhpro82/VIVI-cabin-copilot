"""`_side` biết cách gọi theo NGƯỜI ngồi, và vế chỉ hàng ghế sau vẫn thắng.

Vì sao đây là lỗi an toàn chứ không phải lỗi từ vựng: `_side` trả `None` thì
`_match_door` hiểu là *"nhắm cả xe"* và sinh kế hoạch bốn cửa. Nên trước bản vá này,
`"mở cửa tài xế"` — một câu nhắm **đúng một** cửa — đẩy một plan S2 mở **cả bốn** cửa
qua HITL. Người dùng phải từ chối một thứ họ chưa bao giờ yêu cầu.

Báo cáo gốc (@thanhpro82, 24/08) ghi nhẹ hơn thực tế: *"không route đúng sang
front_left"*. Đo thật mới ra bốn cửa — xem `docs/reports/phan-tich-gom-bug-2026-08-25.md` §1b.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.agents.router import DeterministicControlRouter
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict


@pytest.fixture(scope="module")
def router() -> DeterministicControlRouter:
    return DeterministicControlRouter()


def _cua(router: DeterministicControlRouter, cau: str) -> list[dict]:
    quyet_dinh = router.route(cau)
    assert quyet_dinh.disposition == "control", f"{cau!r} → {quyet_dinh.disposition}/{quyet_dinh.reason}"
    assert quyet_dinh.candidate_plan is not None
    return [step.args for step in quyet_dinh.candidate_plan.steps]


@pytest.mark.parametrize(
    ("cau", "cho_doi"),
    [
        ("Mở cửa tài xế", {"door": "front_left", "state": "open"}),
        ("Đóng cửa người lái", {"door": "front_left", "state": "closed"}),
        ("Mở cửa hành khách", {"door": "front_right", "state": "open"}),
        ("Mở cửa phụ lái", {"door": "front_right", "state": "open"}),
    ],
)
def test_goi_theo_nguoi_ngoi_ra_dung_mot_cua(router: DeterministicControlRouter, cau: str, cho_doi: dict) -> None:
    assert _cua(router, cau) == [cho_doi]


def test_ve_hang_sau_thang_alias_hang_truoc(router: DeterministicControlRouter) -> None:
    """Ca `BL-N3-004` của bộ `bao-loi-2408` — cái bẫy của chính bản vá này.

    `"cửa hành khách sau bên phải"` chứa **cả hai** dấu hiệu. Đặt alias `hành khách`
    trước nhánh `sau bên phải` là câu này ra `front_right`: mở nhầm cửa, không một lời.
    """
    assert _cua(router, "Mở cửa hành khách sau bên phải") == [{"door": "rear_right", "state": "open"}]
    assert _cua(router, "Mở cửa sau bên trái") == [{"door": "rear_left", "state": "open"}]


def test_alias_dung_chung_cho_ghe_khong_rieng_cua(router: DeterministicControlRouter) -> None:
    """`_side` phục vụ cả ghế, nên alias mới phải chạy ở đó luôn — không thì `"sưởi ghế
    tài xế"` vẫn hỏi lại vị trí trong khi câu đã nêu rõ."""
    quyet_dinh = router.route("Bật sưởi ghế tài xế mức 2")
    assert quyet_dinh.disposition == "control", quyet_dinh.reason
    assert quyet_dinh.candidate_plan is not None
    assert [s.args for s in quyet_dinh.candidate_plan.steps] == [{"seat": "front_left", "level": 2}]


def test_cau_khong_neu_vi_tri_van_giu_hanh_vi_bon_cua(router: DeterministicControlRouter) -> None:
    """`"Mở cửa"` trần **không** thuộc bản vá này.

    Hành vi bốn cửa ở đây là cố ý (issue #65) và `VehicleControlView.tsx` đang gửi đúng
    chuỗi này cho nút toàn xe. Đổi nó là việc của một quyết định sản phẩm riêng
    (@thanhpro82, dòng T36) — khoá lại ở đây để bản vá alias không lặng lẽ đổi nó kèm.
    """
    assert len(_cua(router, "Mở cửa")) == 4


@pytest.mark.parametrize(
    "cau",
    [
        "Mở cửa bên trái",
        "Mở cửa bên phải",
        "Đóng cửa bên trái",
        "Đóng cửa bên phải",
        "mở cửa phía bên trái",
        "mở cửa bên tay phải",
    ],
)
def test_neu_mot_phia_ma_thieu_hang_ghe_thi_hoi_lai_chu_khong_no_ra_bon_cua(
    router: DeterministicControlRouter, cau: str
) -> None:
    """Nửa còn lại của lỗ hổng — đóng theo điều kiện approve của review #301.

    Đây **không** phải `"Mở cửa"` trần. Người nói đã thể hiện ý chọn một phía, nên nở
    ra bốn cửa rồi đẩy qua HITL là buộc họ từ chối ba cửa họ chưa từng yêu cầu — một
    plan S2 **sai đích**, không phải một câu trả lời lạc đề.

    Khoá cả `candidate_plan is None`: `RouteDecision` cấm `clarify` mang plan
    (`contracts.py`), nhưng đây đúng là chỗ một bản vá sau này dễ "tiện tay" gắn plan
    bốn cửa vào để màn duyệt có cái hiển thị.
    """
    quyet_dinh = router.route(cau)
    assert quyet_dinh.disposition == "clarify", f"{cau!r} → {quyet_dinh.disposition}"
    assert quyet_dinh.reason == "missing_door_side"
    assert quyet_dinh.candidate_plan is None


def test_tat_ca_van_thang_du_cau_co_neu_mot_phia(router: DeterministicControlRouter) -> None:
    """`"tất cả"` là ý nhắm cả xe, và nó phải thắng hàng rào ở trên.

    Không có luật này thì `"mở tất cả các cửa"` — chuỗi `VehicleControlView.tsx` gửi
    cho nút toàn xe — chỉ cần ai đó thêm chữ `bên` vào là chết.
    """
    assert len(_cua(router, "Mở tất cả các cửa")) == 4


async def test_cau_thieu_hang_ghe_di_het_graph_ma_khong_de_lai_dau_vet_gi() -> None:
    """Điều kiện approve thứ ba của review #301: chứng minh ở mức luồng, không mức router.

    Router trả `clarify` là **một** hàng rào. Test này khoá cái quan trọng hơn: đi trọn
    graph rồi mà vẫn không có approval nào được tạo, không lệnh nào ra `VehicleGateway`,
    và bốn cánh cửa vẫn đúng như lúc đầu. Ba thứ ấy là toàn bộ định nghĩa "zero side
    effect" cho một lệnh S2.
    """
    vehicle = InProcessVehicleGateway.new()
    store = ApprovalStore()
    graph = build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())

    result = await graph.ainvoke(
        {"query": "Mở cửa bên trái", "session_id": "ses-301", "vehicle_id": "veh-1", "turn_id": "turn-301"},
        config={"configurable": {"thread_id": "ses-301"}},
    )

    assert result["outcome"] == "clarify"
    assert "__interrupt__" not in result
    assert store.pending_for_session("ses-301") is None
    assert store.record_count == 0
    assert vehicle.command_count == 0
    assert snapshot_dict(vehicle.state)["doors"] == {
        "front_left": "closed",
        "front_right": "closed",
        "rear_left": "closed",
        "rear_right": "closed",
    }

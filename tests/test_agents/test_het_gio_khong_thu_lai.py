"""Planner **hết giờ** thì bỏ cuộc ngay, không thử lại lần hai.

Vòng sửa thứ hai tồn tại để chữa lỗi **lược đồ**: nó gửi kèm `_cau_sua_loi(...)` nói cho
model biết JSON lần trước sai ở đâu (xem `test_repair_hint_mang_loi_that.py`). Với một lần
chạy **hết giờ** thì không có JSON nào để sửa, câu nhắc ấy vô nghĩa — và cái giá là nhân
đôi thời gian tài xế phải chờ.

Đo trên VPS, run `eval/results/luot-that-dong-thoi/` id `20260827T084543` (N=1, một người,
không ai tranh tài nguyên): một lượt planner tốn **40 086 ms** ≈ 2 × `slm_timeout_s` (20 s
trên VPS) rồi vẫn kết thúc bằng `tra_loi`. Trong cả 15 lượt của run đó, lần thử thứ hai
không cứu được lượt nào.

Test này khoá vế "không thử lại". Vế ngược lại — lỗi lược đồ **vẫn** phải có vòng sửa —
do `test_repair_hint_mang_loi_that.py` khoá, nên hai file phải cùng xanh mới đúng.
"""

from __future__ import annotations

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway

CONFIG = {"configurable": {"thread_id": "t-het-gio"}}


class PlannerHetGio:
    """Luôn hết giờ, và đếm số lần bị gọi."""

    def __init__(self) -> None:
        self.so_lan = 0

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        self.so_lan += 1
        raise httpx.ReadTimeout("timed out")


class PlannerHetGioRoiThanhCong:
    """Hết giờ lần 1. Nếu có lần 2 thì trả plan hợp lệ — để test **phát hiện được** lần 2."""

    def __init__(self) -> None:
        self.so_lan = 0

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        self.so_lan += 1
        if self.so_lan == 1:
            raise httpx.ReadTimeout("timed out")
        return (
            '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1",'
            '"ordinal":0,"tool":"set_hvac_power","args":{"enabled":true},"depends_on":[]}]}'
        )


async def test_het_gio_chi_goi_model_dung_mot_lan():
    planner = PlannerHetGio()
    graph = build_graph(InProcessVehicleGateway.new(), planner=planner, checkpointer=InMemorySaver())

    await graph.ainvoke(
        {"query": "làm cho trong xe dễ chịu hơn tí đi", "session_id": "ses-het-gio", "vehicle_id": "veh-1"},
        config=CONFIG,
    )

    assert planner.so_lan == 1, "hết giờ mà vẫn thử lại — tài xế chờ gấp đôi để nhận cùng một kết quả"


async def test_het_gio_khong_nem_xuyen_qua_graph():
    """Bỏ cuộc phải rơi về nhánh fallback, không phải để exception thoát ra ngoài.

    Cùng kỷ luật ADR-016: SLM hỏng là rơi về hành vi cũ, không phải sự cố. Lượt vẫn
    phải chạy hết graph và trả về một state đọc được.
    """
    planner = PlannerHetGio()
    graph = build_graph(InProcessVehicleGateway.new(), planner=planner, checkpointer=InMemorySaver())

    state = await graph.ainvoke(
        {"query": "làm cho trong xe dễ chịu hơn tí đi", "session_id": "ses-het-gio-2", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "t-het-gio-2"}},
    )

    assert state is not None
    # Không khẳng định `outcome` cụ thể: `_lui_ve_so_tay` trả câu sổ tay khi RAG có sẵn
    # câu trả lời, và điều đó phụ thuộc máy có index hay không. Thứ bất biến là lượt
    # KHÔNG sinh ra kế hoạch điều khiển từ một lần gọi model đã hết giờ.
    assert state.get("candidate_action_plan") is None


async def test_lan_thu_hai_neu_co_thi_test_tren_phat_hien_duoc():
    """Lưới an toàn cho chính hai test trên.

    Nếu một ngày `slm_stage` bỏ luôn cả vòng sửa lỗi lược đồ, hai test trên vẫn xanh vì
    chúng chỉ đếm "đúng một lần". Test này chứng minh phép đếm ấy **nhạy**: cùng stub, mà
    lần thứ hai có chạy thì `so_lan` phải lên 2.
    """
    planner = PlannerHetGioRoiThanhCong()
    graph = build_graph(InProcessVehicleGateway.new(), planner=planner, checkpointer=InMemorySaver())

    await graph.ainvoke(
        {"query": "làm cho trong xe dễ chịu hơn tí đi", "session_id": "ses-het-gio-3", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "t-het-gio-3"}},
    )

    assert planner.so_lan == 1, "hết giờ vẫn phải dừng ở lần 1, kể cả khi lần 2 sẽ thành công"

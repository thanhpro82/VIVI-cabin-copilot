"""Chuỗi chitchat do **planner** trả về cũng phải đi qua cổng, y như node chitchat.

Đo 23/08 khi dựng kịch bản demo: `"Xe rung lắc quá"` ở 45 km/h bị classifier chấm
`control` → node `slm` (planner) → union prompt trả `kind: chitchat` →
`outcome=chitchat` **mà không đi qua node `chitchat`**, tức bỏ qua cả năm lớp cổng
SP-2 *kể cả cổng triệu chứng an toàn*.

Spec SP-2 §6 ghi hai đường song song là "ngoài phạm vi" — đúng lúc ấy, vì nhánh
chitchat còn là câu giữ chỗ. Từ khi SP-2 có cổng thật thì nó thành **lỗ an toàn**:
cùng một câu, đi đường này thì được chặn, đi đường kia thì không.

Quan trọng hơn từ 23/08: #258 bật `slm_enabled` mặc định, nên đường planner có mặt
trên **mọi checkout** chứ không chỉ máy demo.
"""


from src.agents.graph import build_graph
from src.agents.nodes.chitchat_cong import CAU_CHUYEN_HUONG_AN_TOAN, CAU_CHUYEN_HUONG_SO
from src.services.vehicle_gateway import InProcessVehicleGateway


class PlannerTraChitchat:
    """Union prompt trả `kind: chitchat` — hình dạng thứ hai hợp lệ của `parse_slm_output`."""

    def __init__(self, reply: str) -> None:
        self._reply = reply

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        import json

        return json.dumps({"kind": "chitchat", "reply": self._reply}, ensure_ascii=False)


CAU_LA = "Nóng quá trời hôm nay ha"


async def _hoi(planner, text: str = CAU_LA) -> dict:
    graph = build_graph(InProcessVehicleGateway.new(), planner=planner)
    return await graph.ainvoke({"query": text, "session_id": "s", "vehicle_id": "v", "turn_id": "t"})


async def test_planner_bia_thong_so_thi_van_bi_cong_chan():
    """Cổng (c): chitchat không được nói thông số xe, đi đường nào cũng vậy."""
    r = await _hoi(PlannerTraChitchat("Xe chạy được 450 km một lần sạc đấy!"))
    assert r["outcome"] == "chitchat"
    assert r["chitchat_reply"] == CAU_CHUYEN_HUONG_SO
    assert r["chitchat_cong"] == "so_ky_thuat"


async def test_planner_noi_da_lam_gi_thi_van_bi_chan():
    r = await _hoi(PlannerTraChitchat("Tôi đã bật điều hòa cho bạn rồi!"))
    assert r["chitchat_cong"] == "noi_da_lam"


async def test_planner_xen_chu_han_thi_van_bi_chan():
    r = await _hoi(PlannerTraChitchat("Chào bạn 你好, đi đâu đấy?"))
    assert r["chitchat_cong"] == "he_chu_la"


async def test_cau_sach_van_di_qua_nguyen_ven():
    """Cổng không được nuốt câu lành — nếu không thì hợp nhất là một bước lùi."""
    r = await _hoi(PlannerTraChitchat("Trời đẹp thế này lái xe sướng nhỉ!"))
    assert r["chitchat_reply"] == "Trời đẹp thế này lái xe sướng nhỉ!"
    assert r["chitchat_cong"] == "qua"


async def test_trieu_chung_an_toan_khong_bao_gio_toi_duoc_planner():
    """Ca thật đã đo: `"Xe rung lắc quá"` từng đi đường planner và thoát mọi cổng.

    Cổng ĐẦU VÀO phải chặn trước khi planner được gọi, chứ không phải lọc chuỗi nó
    trả về — model không được nói gì về một chiếc xe có thể đang hỏng.
    """
    r = await _hoi(PlannerTraChitchat("Xe đang hơi mệt thôi, cứ lái nhẹ nhé!"), "Xe rung lắc quá")
    assert r["chitchat_reply"] == CAU_CHUYEN_HUONG_AN_TOAN
    assert r["chitchat_cong"] == "trieu_chung_an_toan"

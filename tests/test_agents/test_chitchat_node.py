"""Node chitchat: generator → cổng → compose; fail-safe về câu mẫu; có trace_id
không nổ (bài học #242); flag off giao hệt develop."""

import httpx

from src.agents.graph import build_graph
from src.agents.nodes.chitchat_cong import CAU_CHUYEN_HUONG_SO, CAU_MAU_CHUNG
from src.services.vehicle_gateway import InProcessVehicleGateway


class FakeClassifier:
    def classify(self, normalized_text: str) -> str:
        return "chitchat"


class FakeChitchat:
    def __init__(self, reply: str | None = None, exc: Exception | None = None) -> None:
        self._reply, self._exc, self.calls = reply, exc, []

    def reply(self, normalized_text: str) -> str:
        self.calls.append(normalized_text)
        if self._exc:
            raise self._exc
        return self._reply or "Chào bạn!"


CAU = "Hôm nay trời đẹp ghê"


async def _hoi(graph, text=CAU, **extra):
    return await graph.ainvoke({"query": text, "session_id": "s1", "vehicle_id": "v1", "turn_id": "t1", **extra})


async def test_cau_sach_duoc_phat_nguyen_ven():
    w = FakeChitchat(reply="Trời đẹp thế này lái xe sướng nhỉ!")
    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=w)
    r = await _hoi(graph)
    assert w.calls == [r["normalized_text"]]
    assert r["outcome"] == "chitchat"
    assert r["chitchat_reply"] == "Trời đẹp thế này lái xe sướng nhỉ!"
    assert r["chitchat_cong"] == "qua"
    assert r["response_text"] == "Trời đẹp thế này lái xe sướng nhỉ!"


async def test_model_noi_so_thi_chuyen_huong():
    graph = build_graph(
        InProcessVehicleGateway.new(),
        classifier=FakeClassifier(),
        chitchat=FakeChitchat(reply="Chạy 450 km mỗi lần sạc!"),
    )
    r = await _hoi(graph)
    assert r["chitchat_reply"] == CAU_CHUYEN_HUONG_SO
    assert r["chitchat_cong"] == "so_ky_thuat"


async def test_generator_hong_thi_cau_mau_khong_treo():
    for exc in (httpx.ConnectError("chết"), httpx.ReadTimeout("chậm"), OSError("đứt")):
        graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=FakeChitchat(exc=exc))
        r = await _hoi(graph)
        assert r["outcome"] == "chitchat"
        assert r["chitchat_reply"] == CAU_MAU_CHUNG
        assert r["chitchat_cong"] == "loi"


async def test_co_trace_id_thi_khong_no_va_ghi_vao_planning_or_retrieval():
    from src.services.trace_store import get_trace_store, reset_trace_store

    reset_trace_store()
    store = get_trace_store()
    store.open("tr-chit", "s1", "t1")
    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=FakeChitchat())
    r = await _hoi(graph, trace_id="tr-chit")
    assert r["outcome"] == "chitchat"
    assert store.get("tr-chit").stages.planning_or_retrieval is not None


async def test_flag_off_khong_co_node_chitchat():
    graph = build_graph(InProcessVehicleGateway.new())
    assert "chitchat" not in graph.get_graph().nodes


async def test_trieu_chung_an_toan_khong_goi_model():
    """Cổng đầu vào chặn TRƯỚC generator — model không được nói gì về xe hỏng.

    Ca `CC-AN14`: model từng trả "xe đang hơi mệt, cứ lái nhẹ để nó thư giãn" cho
    một câu báo phanh kêu. Không gọi model thì lớp lỗi ấy không dựng lên được.
    """
    from src.agents.nodes.chitchat_cong import CAU_CHUYEN_HUONG_AN_TOAN

    w = FakeChitchat(reply="Xe đang hơi mệt thôi, cứ lái nhẹ nhé!")
    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=w)
    r = await _hoi(graph, "Xe rung lắc quá")
    assert w.calls == [], "model KHÔNG được gọi cho câu báo triệu chứng"
    assert r["chitchat_reply"] == CAU_CHUYEN_HUONG_AN_TOAN
    assert r["chitchat_cong"] == "trieu_chung_an_toan"

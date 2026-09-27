"""Node slm_classify: rẽ 3 nhánh, fail-safe về manual, flag-off giao hệt develop.

Mọi test dựng graph qua build_graph với InProcessVehicleGateway + FakeClassifier —
không mạng, không model. Đường thật (llama-server) nằm ở test contract.
"""

import httpx

from src.agents.graph import _route_after_classify, build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway


class FakeClassifier:
    def __init__(self, intent: str | None = None, exc: Exception | None = None) -> None:
        self._intent = intent
        self._exc = exc
        self.calls: list[str] = []

    def classify(self, normalized_text: str) -> str:
        self.calls.append(normalized_text)
        if self._exc is not None:
            raise self._exc
        return self._intent or "manual"


#: Câu KHÔNG khớp luật nào của DeterministicControlRouter — router trả
#: default_to_manual. Nếu router sau này học được câu này, đổi câu khác và
#: kiểm bằng: router.route(text).reason == "default_to_manual".
CAU_LA = "Nóng quá trời hôm nay ha"


async def _hoi(graph, text: str) -> dict:
    return await graph.ainvoke({"query": text, "session_id": "s1", "vehicle_id": "v1", "turn_id": "t1"})


def test_route_after_classify_du_ba_nhanh():
    assert _route_after_classify({"route_reason": "slm_classified_control"}) == "slm"
    assert _route_after_classify({"route_reason": "slm_classified_manual"}) == "rag"
    assert _route_after_classify({"route_reason": "slm_classified_chitchat"}) == "chitchat"
    assert _route_after_classify({"route_reason": "slm_classify_failed"}) == "rag"
    # Hết giờ có `route_reason` riêng để ĐẾM được, nhưng vẫn về đúng nhánh rag: tách
    # ra là đổi cách đo, không phải đổi hành vi fail-safe của ADR-011.
    assert _route_after_classify({"route_reason": "slm_classify_timeout"}) == "rag"


async def test_chitchat_khong_co_generator_thi_cau_mau_chung():
    """classifier có, generator None (cấu hình cũ) → câu mẫu, không nổ."""
    from src.agents.nodes.chitchat_cong import CAU_MAU_CHUNG

    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(intent="chitchat"))
    ket_qua = await _hoi(graph, CAU_LA)
    assert ket_qua["outcome"] == "chitchat"
    assert ket_qua["chitchat_reply"] == CAU_MAU_CHUNG
    assert ket_qua["chitchat_cong"] == "loi"


async def test_classify_hong_thi_ve_manual_khong_treo():
    """Ba tầng fail-safe: lỗi hạ tầng / timeout / payload hỏng đều về nhánh rag.

    `route_reason` khác nhau, **nhánh đi thì giống nhau** — đó mới là bất biến cần khoá.
    Hết giờ tách ra `slm_classify_timeout` (xem test dưới); hai loại còn lại vẫn là
    `slm_classify_failed`.
    """
    for exc, ly_do in (
        (httpx.ConnectError("chết"), "slm_classify_failed"),
        (httpx.ReadTimeout("chậm"), "slm_classify_timeout"),
        (OSError("đứt"), "slm_classify_failed"),
    ):
        graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(exc=exc))
        ket_qua = await _hoi(graph, CAU_LA)
        assert ket_qua["route_reason"] == ly_do
        # Nhánh rag không có index trong test → grounded_refusal, là hành vi
        # ADR-011 của develop. Điều cần khoá: KHÔNG treo, KHÔNG nổ 500.
        assert ket_qua["outcome"] in {"grounded_refusal", "not_control", "clarify"}


async def test_classify_het_gio_dem_rieng_va_noi_ra_trong_log(caplog):
    """Hết giờ phải đếm được, và phải đọc được trong log.

    Đo trên VPS 28/08 (run `20260828T145920.055372Z`): ở mức 3 người đồng thời, **40%**
    số lượt câu trượt luật dừng ở đúng đây — cột `route` đóng cứng 7 030 ms, bằng
    `slm_classify_timeout_s`. Nhưng `grep -i timeout` trên log backend ra **rỗng**, vì
    `str(httpx.ReadTimeout)` là chuỗi RỖNG nên dòng log cũ chỉ còn phần tiền tố.

    Người dùng nhận câu trả lời hạng hai, mọi chỉ số báo thành công, và không ai có
    cách nào biết. Test này khoá cả hai nửa: đếm được (`route_reason`) và đọc được (log).
    """
    import logging

    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(exc=httpx.ReadTimeout("")))

    with caplog.at_level(logging.WARNING, logger="src.agents.graph"):
        ket_qua = await _hoi(graph, CAU_LA)

    assert ket_qua["route_reason"] == "slm_classify_timeout"
    dong = " | ".join(r.getMessage() for r in caplog.records)
    assert "hết giờ" in dong, "log phải nói ra là HẾT GIỜ, không phải một câu chung chung"
    assert "ReadTimeout" in dong, "phải in TÊN LỚP: str() của nó rỗng nên không còn gì khác để bám"


async def test_flag_off_giao_het_develop():
    """classifier=None ⇒ không có node slm_classify, câu lạ đi rag như ADR-011."""
    graph = build_graph(InProcessVehicleGateway.new(), classifier=None)
    assert "slm_classify" not in graph.get_graph().nodes
    ket_qua = await _hoi(graph, CAU_LA)
    assert ket_qua["route_reason"] == "default_to_manual"


async def test_cau_khop_luat_khong_goi_classifier():
    """Đường tắt: lệnh khớp luật không trả một mili giây nào cho SLM."""
    classifier = FakeClassifier(intent="chitchat")
    graph = build_graph(InProcessVehicleGateway.new(), classifier=classifier)
    await _hoi(graph, "bật điều hòa")
    assert classifier.calls == []


async def test_co_trace_id_thi_luot_khong_no_va_routing_ghi_ca_classify():
    """Hồi quy P0 (phát hiện 21/08 khi đo SP-0, ngay sau khi #232 merge):
    `_timed("slm_classify", ...)` gọi `record_stage` với stage ngoài bảy tên
    chuẩn → `ValueError` trong `finally` → MỌI lượt API thật qua classifier nổ
    500. Suite không bắt vì không test nào truyền `trace_id` qua nhánh này.

    Sửa: classify tính vào stage `routing` (last-write-wins) — "định tuyến" với
    SLM bật thật sự tốn chừng đó, và đó là con số ADR-006 muốn phơi ra.
    """
    from src.services.trace_store import get_trace_store, reset_trace_store

    reset_trace_store()
    store = get_trace_store()
    store.open("tr-classify", "s1", "t1")
    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(intent="chitchat"))
    ket_qua = await graph.ainvoke(
        {"query": CAU_LA, "session_id": "s1", "vehicle_id": "v1", "turn_id": "t1", "trace_id": "tr-classify"}
    )
    assert ket_qua["outcome"] == "chitchat"
    record = store.get("tr-classify")
    assert record is not None
    assert record.stages.routing is not None and record.stages.routing >= 0.0

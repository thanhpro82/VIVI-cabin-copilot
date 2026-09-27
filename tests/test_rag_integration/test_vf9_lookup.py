"""Bằng chứng end-to-end: câu hỏi tiếng Việt → citation thật từ sổ tay VF9.

Đánh dấu `slow` vì cần index thật (corpus ~150MB + model embedding). CI bỏ qua.
Chạy: `pytest tests/test_rag_integration -m slow`

Dựng index trước bằng `scripts/prepare_vf9_index.ps1`.
"""

from pathlib import Path

import pytest

from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict

pytestmark = pytest.mark.slow

INDEX = Path("data/rag/vf9_2026_vi")


@pytest.fixture(autouse=True)
def _require_index():
    if not (INDEX / "index.faiss").exists():
        pytest.skip("chưa dựng index — chạy scripts/prepare_vf9_index.ps1")


@pytest.mark.parametrize(
    "question",
    [
        "Cách khởi tạo lại cửa sổ điện?",
        "Công tắc khóa cửa sổ điện dùng để làm gì?",
        "Chức năng chống kẹp của cửa sổ hoạt động thế nào?",
    ],
)
async def test_manual_question_returns_real_citations(question):
    vehicle = InProcessVehicleGateway.new()
    graph = build_graph(vehicle)
    result = await graph.ainvoke({"query": question, "session_id": "s", "vehicle_id": "v"})
    assert result["outcome"] == "grounded_answer"
    citations = result["citations"]
    assert citations, "phải có ít nhất một citation"
    # `Citation` là model Pydantic (src/rag/models.py), không phải dict — đúng 8
    # field của data_model.md. Truy cập bằng thuộc tính, không dùng .get().
    for citation in citations:
        assert citation.chunk_id, "citation phải có chunk_id giải được"
        assert citation.page >= 1, "citation phải có số trang thật"
        assert citation.section, "citation phải nêu mục trong sổ tay"
        assert 0.0 <= citation.retrieval_score <= 1.0
    assert vehicle.command_count == 0


async def test_question_outside_the_manual_is_refused_with_grounding():
    """VF9 chạy điện — câu hỏi về dầu động cơ xăng phải bị từ chối, không bịa."""
    vehicle = InProcessVehicleGateway.new()
    graph = build_graph(vehicle)
    result = await graph.ainvoke({"query": "Cách thay dầu động cơ xăng của VF9", "session_id": "s", "vehicle_id": "v"})
    assert result["outcome"] == "grounded_refusal"
    assert vehicle.command_count == 0


async def test_command_still_bypasses_rag_entirely():
    vehicle = InProcessVehicleGateway.new()
    graph = build_graph(vehicle)
    result = await graph.ainvoke({"query": "Đặt điều hòa 22 độ", "session_id": "s", "vehicle_id": "v"})
    assert result["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["hvac"]["temperature_c"] == 22
    assert not result.get("citations")


async def test_question_matching_a_control_rule_offers_without_touching_rag():
    """ADR-011: `offer` không đi qua RAG và không thực thi."""
    vehicle = InProcessVehicleGateway.new()
    graph = build_graph(vehicle)
    result = await graph.ainvoke(
        {"query": "Mở cửa sổ bên lái 30 phần trăm được không?", "session_id": "s", "vehicle_id": "v"}
    )
    assert result["outcome"] == "offer"
    assert "30%" in result["response_text"]
    assert vehicle.command_count == 0

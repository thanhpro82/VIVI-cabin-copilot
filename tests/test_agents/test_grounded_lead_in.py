"""Câu dẫn do SLM viết — phần còn lại của phương án A (issue #62).

Điểm quyết định của cả thiết kế: phần model viết **không mang một dữ kiện nào**.
Nội dung là trích nguyên văn, câu dẫn chỉ là khung. Nên không có gì để bịa, để đảo
nghĩa, hay để làm rơi điều kiện — và hỏng thì rơi về chuỗi cố định, không mất nội dung.

Đo tại `eval/results/spike-003/20260811T200114.021276Z`: p50 827 ms / p95 1.188 ms
cả lượt (gồm rerank), 0 câu sai về dữ kiện.
"""

import re

import httpx
import pytest

from src.agents.graph import build_graph
from src.agents.nodes.compose import OUTCOME_MESSAGES, compose_node
from src.agents.slm import LEAD_IN_MAX_CHARS, QwenLeadIn
from src.rag.models import Evidence
from src.services.vehicle_gateway import InProcessVehicleGateway

_DOAN = "Chế độ lấy gió trong giúp tạo sự lưu chuyển không khí trong cabin của xe."


def _kiem_cau_dan_khong_mang_du_kien(response_text: str) -> None:
    """Câu dẫn ở đường lui phải **không chứa chữ số nào**.

    Đây là bất biến, không phải chuyện thẩm mỹ. Đo 19/08 trên 39 câu hỏi
    (`eval/results/cau-dan/`): **8%** câu dẫn của Qwen 0.5B chứa một con số bịa, gồm
    *"Áp suất lốp khuyến nghị của xe là 200 kPa"* (thật là 260/270) và *"Độ sâu gai lốp
    tối thiểu là 10mm"* (thật là 2 mm). Đường lui tất định không được có lớp lỗi ấy.
    """
    lead = response_text.split("\n\n", 1)[0]
    assert not re.search(r"\d", lead), f"câu dẫn mang số: {lead!r}"


async def _fake_rag(state):
    return {
        "citations": [{"chunk_id": "c1"}],
        "evidence": [Evidence(section="Điều hòa", page=8, text=_DOAN, chunk_id="c1", score=0.9)],
    }


async def _run(lead_in):
    graph = build_graph(InProcessVehicleGateway.new(), rag=_fake_rag, lead_in=lead_in)
    return await graph.ainvoke(
        {
            "query": "Chế độ lấy gió trong dùng khi nào?",
            "session_id": "ses-1",
            "vehicle_id": "veh-1",
            "turn_id": "turn-1",
        }
    )


@pytest.mark.asyncio
async def test_cau_dan_cua_slm_thay_cho_chuoi_co_dinh():
    class _Writer:
        def write(self, question, section):
            return "Về chế độ lấy gió, sổ tay xe ghi thế này:"

    result = await _run(_Writer())

    assert result["response_text"].startswith("Về chế độ lấy gió, sổ tay xe ghi thế này:")
    assert _DOAN in result["response_text"], "nội dung nguyên văn vẫn phải còn nguyên"


@pytest.mark.asyncio
async def test_khong_co_slm_thi_cau_dan_tat_dinh_va_khong_mang_du_kien():
    """Không có SLM thì câu dẫn dựng bằng luật — và luật thì không bịa được.

    Bản trước khoá `startswith(OUTCOME_MESSAGES["grounded_answer"])`, tức khoá **đúng
    một chuỗi cố định**. Nay đường lui là mẫu ghép từ chính câu hỏi (`cau_dan_tu_cau_
    hoi`), nói được chủ đề tài xế vừa hỏi thay vì một câu chung chung.

    Bất biến mà test này bảo vệ không đổi, và docstring của module đã nói ra nó: *hỏng
    thì rơi về đường tất định, **không mất nội dung***. Nên assert bám vào bất biến ấy
    chứ không bám vào chuỗi: nội dung còn nguyên, và câu dẫn không mang dữ kiện nào.
    """
    result = await _run(None)

    assert _DOAN in result["response_text"]
    _kiem_cau_dan_khong_mang_du_kien(result["response_text"])


@pytest.mark.asyncio
async def test_slm_hong_thi_roi_ve_chuoi_co_dinh_chu_khong_mat_noi_dung():
    """Fail-open, khác hẳn nhánh planner.

    Câu dẫn không mang dữ kiện nên hỏng nó **không** phải lý do từ chối trả lời.
    Nhánh sổ tay phải sống sót qua mọi kiểu hỏng của SLM — đó chính là điều kiện mà
    ADR-015 (bản sửa) hứa: `slm_enabled=False` hay llama-server chết đều không đổi
    nội dung tài xế nhận được.
    """

    class _Dead:
        def write(self, question, section):
            raise httpx.ConnectError("connection refused")

    result = await _run(_Dead())

    assert _DOAN in result["response_text"]
    _kiem_cau_dan_khong_mang_du_kien(result["response_text"])


@pytest.mark.asyncio
async def test_cau_dan_rong_hoac_toan_khoang_trang_cung_roi_ve_co_dinh():
    class _Blank:
        def write(self, question, section):
            return "   \n "

    result = await _run(_Blank())
    assert _DOAN in result["response_text"]
    _kiem_cau_dan_khong_mang_du_kien(result["response_text"])


@pytest.mark.asyncio
async def test_cau_dan_dai_bi_cat_tran():
    """Model thoái hoá là chuyện đã quan sát được ở SPIKE-003 (lặp tới trần token).

    Câu dẫn lan man thì đọc lên loa rất lâu trước khi tới nội dung thật.
    """

    class _Rambler:
        def write(self, question, section):
            return "Dạ " * 200

    result = await _run(_Rambler())
    lead = result["response_text"].split("\n\n", 1)[0]
    assert len(lead) <= LEAD_IN_MAX_CHARS


@pytest.mark.asyncio
async def test_cau_dan_khong_dinh_vao_cac_outcome_khac():
    """Chỉ nhánh sổ tay mới có câu dẫn; đừng để nó rò sang lệnh điều khiển."""
    out = await compose_node({"outcome": "completed", "grounded_lead_in": "Về chuyện này,"})
    assert out["response_text"] == OUTCOME_MESSAGES["completed"]


def test_client_gui_dung_cau_hinh_da_do(monkeypatch):
    """Khoá lại cấu hình đã đo: ChatML + `n_predict` nhỏ + stop `<|im_end|>`.

    Vòng đo trước gọi `/completion` thô, không template — model không có chỗ dừng nên
    nhại lại nguyên văn chỉ thị hệ thống vào câu trả lời. Sang ChatML thì decode p50
    đi từ 1.630 xuống 500 ms. Đây là cấu hình, không phải chi tiết cài đặt.
    """
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": "Về sưởi ghế, sổ tay xe hướng dẫn thế này:"}

    def fake_post(url, json, timeout):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)

    out = QwenLeadIn("http://127.0.0.1:8093", "qwen", timeout_s=3.0).write("Làm sao bật sưởi ghế?", "Ghế")

    assert out == "Về sưởi ghế, sổ tay xe hướng dẫn thế này:"
    body = captured["json"]
    assert body["prompt"].startswith("<|im_start|>system")
    assert body["prompt"].endswith("<|im_start|>assistant\n")
    assert "Làm sao bật sưởi ghế?" in body["prompt"]
    assert body["stop"] == ["<|im_end|>", "<|im_start|>"]
    assert body["temperature"] == 0
    assert body["cache_prompt"] is True
    assert body["n_predict"] == 40

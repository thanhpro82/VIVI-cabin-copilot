"""Câu trả lời tra sổ tay phải chứa nội dung nguyên văn, không chỉ trỏ sang citation.

Quyết định ở issue #62 (phương án A), dựa trên đo tại
`eval/results/spike-003/20260811T200114.021276Z`: để SLM viết lại đoạn sổ tay thì
4/40 câu gây hiểu lầm, lớp lỗi chính là **bỏ điều kiện theo phiên bản** (bảng áp
suất lốp ECO/PLUS, pin SDI/CATL). Trích nguyên văn thì điều kiện đi kèm theo.
"""

import pytest

from src.agents.nodes.compose import OUTCOME_MESSAGES, compose_node
from src.rag.models import Evidence
from src.services.ivi_events import assistant_response_payload


def _state(text: str, *, section: str = "Cửa sổ điện", page: int = 3) -> dict:
    return {
        "outcome": "grounded_answer",
        "evidence": [Evidence(section=section, page=page, text=text, chunk_id="c1", score=0.9)],
    }


@pytest.mark.asyncio
async def test_cau_tra_loi_chua_nguyen_van_doan_so_tay():
    text = "Để tự động mở toàn bộ cửa sổ điện, đẩy nút cửa sổ hoàn toàn xuống."
    out = await compose_node(_state(text))
    assert text in out["response_text"]
    assert out["response_text"].startswith(OUTCOME_MESSAGES["grounded_answer"])
    # `response` là bản sao dùng cho dây sự kiện; hai đường không được lệch nhau.
    assert out["response"] == out["response_text"]


@pytest.mark.asyncio
async def test_trich_du_doan_dai_hon_gioi_han_excerpt_300():
    """39/40 đoạn thật dài hơn EXCERPT_CHARS=300.

    Trích từ `citation.excerpt` là tái tạo đúng lỗi cắt cụt điều kiện an toàn mà
    ticket này sinh ra để tránh — nên nguồn phải là `evidence[0].text`.
    """
    text = "A" * 400 + " Bản ECO có chỉnh điện 8 hướng."
    out = await compose_node(_state(text))
    assert "Bản ECO có chỉnh điện 8 hướng." in out["response_text"]


@pytest.mark.asyncio
async def test_doan_qua_dai_bi_cat_o_ranh_gioi_cau_va_noi_ro_con_tiep():
    """Bỏ sót phải **nhìn thấy được** — lỗi của phương án SLM là bỏ sót âm thầm."""
    text = ("Câu một. " * 200) + "Câu cuối bị bỏ."
    out = await compose_node(_state(text, section="Vành và bánh xe", page=2))
    body = out["response_text"]
    assert "Câu cuối bị bỏ." not in body
    assert "Vành và bánh xe" in body
    assert "tr.2" in body


@pytest.mark.asyncio
async def test_cat_khong_duoc_de_lai_cau_do_dang():
    text = ("Đây là một câu khá dài để lấp chỗ. " * 60) + "Phần đuôi."
    out = await compose_node(_state(text))
    quoted = out["response_text"].split("\n\n", 1)[1].split("\n(", 1)[0]
    assert quoted.rstrip().endswith(".")


@pytest.mark.asyncio
async def test_khong_co_evidence_thi_giu_nguyen_cau_co_dinh():
    out = await compose_node({"outcome": "grounded_answer", "evidence": []})
    assert out["response_text"] == OUTCOME_MESSAGES["grounded_answer"]


@pytest.mark.asyncio
async def test_evidence_rong_chu_khong_thieu_cung_khong_sap():
    out = await compose_node(_state("   "))
    assert out["response_text"] == OUTCOME_MESSAGES["grounded_answer"]


@pytest.mark.asyncio
async def test_cac_outcome_khac_khong_doi():
    out = await compose_node({"outcome": "grounded_refusal", "evidence": []})
    assert out["response_text"] == OUTCOME_MESSAGES["grounded_refusal"]


@pytest.mark.asyncio
async def test_evidence_dang_dict_cung_trich_duoc():
    """Node RAG là tham số tiêm được, không phải lúc nào cũng trả `Evidence`.

    Chỉ đọc thuộc tính thì gặp dict sẽ **lặng lẽ** rơi về câu cố định — mất nội dung
    mà không ai thấy, đúng loại hỏng mà thay đổi này sinh ra để chống.
    """
    out = await compose_node(
        {
            "outcome": "grounded_answer",
            "evidence": [{"section": "Cửa sổ điện", "page": 2, "text": "Đẩy nút cửa sổ hoàn toàn xuống."}],
        }
    )
    assert "Đẩy nút cửa sổ hoàn toàn xuống." in out["response_text"]


@pytest.mark.asyncio
async def test_noi_dung_di_het_duong_qua_graph_that():
    """Chốt phần **lắp ráp**, thứ mà test dựng state bằng tay không chứng minh được.

    `rag_stage` phải đặt evidence vào đúng khoá mà `compose_node` đọc. Rời hai chỗ đó
    ra thì nhánh sổ tay vẫn "chạy đúng" theo mọi test đơn vị mà tài xế vẫn không nghe
    được nội dung nào — chính là trạng thái trước thay đổi này.
    """
    from src.agents.graph import build_graph
    from src.services.vehicle_gateway import InProcessVehicleGateway

    doan = "Chế độ lấy gió trong giúp tạo sự lưu chuyển không khí trong cabin của xe."

    async def fake_rag(state):
        return {
            "citations": [{"chunk_id": "c1"}],
            "evidence": [Evidence(section="Điều hòa", page=8, text=doan, chunk_id="c1", score=0.9)],
        }

    vehicle = InProcessVehicleGateway.new()
    graph = build_graph(vehicle, rag=fake_rag)
    result = await graph.ainvoke(
        {
            "query": "Chế độ lấy gió trong dùng khi nào?",
            "session_id": "ses-1",
            "vehicle_id": "veh-1",
            "turn_id": "turn-1",
        }
    )

    assert result["outcome"] == "grounded_answer"
    assert doan in result["response_text"]
    assert vehicle.command_count == 0


# --- Task 1 của `2026-08-13-speak-text-an-toan-cho-nhanh-so-tay.md` ------------
#
# Đo trên máy Nhân 13/08 sau khi cài Piper: một lượt sổ tay sinh ra `assistant.speech`
# **4,60 MB** trong MỘT khung WebSocket, tương ứng **65,6 giây** audio. Nguyên nhân dây
# chuyền: `compose_node` chỉ trả `response_text`, `ivi_events.py` đặt
# `speak_text = display_text`, rồi TTS tổng hợp nguyên đoạn trích 1.200 ký tự.
#
# `api_spec.md:571` khai `assistant.response` có **cả hai** trường từ đầu, và ví dụ ở
# dòng 163 cho thấy đúng ý đồ: `"speak_text": "Đã đặt 24 độ."` — ngắn. Gộp hai trường
# là lệch hợp đồng, không phải rút gọn.


@pytest.mark.asyncio
async def test_nhanh_so_tay_khong_doc_ca_doan_trich():
    """Điều test này khoá **không** đổi: loa không được đọc nguyên đoạn 1.200 ký tự.

    Điều đã đổi là *ai còn giữ bản dài*. Trước 21/08 `display_text` giữ nó và bài test
    này viết bất biến ấy thành `speak < display`. Nhóm yêu cầu hợp nhất hai kênh nên
    bản dài thôi ra dây — xem `test_mot_chuoi_cho_hai_kenh.py`. Bản ghi đầy đủ chuyển
    sang `response_text`, và bất biến gốc (loa nghe được) khoá lại ở đây theo `response_text`.

    Sửa 30/08: vế "màn hình là phụ đề" khẳng định ở tầng **payload**, không ở compose.
    Compose báo trung thực cả hai kênh; trần phụ đề áp ở `assistant_response_payload`,
    nơi duy nhất bất biến ấy được giữ. Không nới lỏng — `display_text` của compose không
    đi đâu khác, `turns.py` và `trace_collector.py` đều đọc payload.
    """
    out = await compose_node(_state("A" * 400 + ". Bản ECO có chỉnh điện 8 hướng."))

    assert len(out["speak_text"]) < len(out["response_text"])
    ra = assistant_response_payload(out)
    assert ra["display_text"] == ra["speak_text"], "màn hình là phụ đề của lời nói"


@pytest.mark.asyncio
async def test_speak_text_khong_bao_gio_vuot_tran_doc():
    """Trần này là lưới cuối. Vượt nó nghĩa là câu trả lời dài hơn thứ nghe nổi."""
    from src.services.ivi_events import MAX_SPEECH_CHARS

    out = await compose_node(_state("Câu dài. " * 400))
    assert len(out["speak_text"]) <= MAX_SPEECH_CHARS


@pytest.mark.asyncio
async def test_nhanh_khong_phai_so_tay_thi_noi_dung_nhu_hien_thi():
    """Lệnh điều khiển vốn đã ngắn — đừng cắt gì, và đừng để hai kênh lệch nhau."""
    out = await compose_node({"outcome": "completed", "evidence": []})
    assert out["speak_text"] == out["display_text"]

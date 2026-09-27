"""Sáu lối ra của đường Routine, mỗi lối một câu nói được. Issue #274, #299.

## Vì sao test này tồn tại — đo được, không phải đề phòng lý thuyết

Sau khi router biết `disposition="routine"` nhưng compose chưa có câu nào, đo qua HTTP
thật (`POST /api/v1/turns/text`, 30/08):

    {"status": "completed",
     "response": {"display_text": "Đã xử lý yêu cầu.", "speak_text": "Đã xử lý yêu cầu."},
     "action_plan": null, "outcomes": []}

Xe **báo đã xử lý** trong khi chưa gọi một service nào. Trước đó nó nói "không tìm thấy
trong sổ tay" — một thất bại **thành thật**. Nên bước giữa chừng ấy còn tệ hơn chỗ xuất
phát, và với `"Dừng lại"` thì đó là tài xế tin rằng vừa dừng được một thứ đang chạy.

Suite 3209 xanh và cả ba bộ đo đạt mà không thấy nó: `--mode multiturn` chấm ở mức
`route_node`, tức nó đo router **nói** đúng, không đo xe **làm** đúng.

Câu phải nói được khi đang lái: ngắn, và nói rõ xe ĐÃ hay CHƯA làm gì — bài học
`CLARIFY_MESSAGES` (#148), nơi một câu hỏi lại thiếu vế *"tôi chưa làm gì cả"* khiến tài
xế đinh ninh việc đã xong trong khi thực tế là 0 lệnh.
"""

from __future__ import annotations

import pytest

from src.agents.nodes.compose import _FALLBACK, OUTCOME_MESSAGES, compose_node

_SAU_LOI_RA = [
    "routine_preview",
    "routine_da_chay",
    "routine_da_huy",
    "routine_khong_thay",
    "routine_mo_ho",
    "routine_khong_co_lan_chay",
    "routine_loi_ngu_canh",
]


async def _noi(**state) -> dict:
    return await compose_node(dict(state))


async def test_khong_thay_thi_neu_cai_co_chu_khong_im_lang():
    ra = await _noi(outcome="routine_khong_thay", routine_ung_vien=["Đi làm", "Về nhà"])
    assert "đi làm" in ra["speak_text"].lower()
    assert "về nhà" in ra["speak_text"].lower()
    assert "chưa" in ra["speak_text"].lower(), "thiếu vế 'tôi chưa làm gì cả'"


async def test_mo_ho_thi_hoi_lai_bang_dung_cac_ung_vien():
    ra = await _noi(outcome="routine_mo_ho", routine_ung_vien=["Đi làm sáng", "Đi làm chiều"])
    assert "đi làm sáng" in ra["speak_text"].lower()
    assert "đi làm chiều" in ra["speak_text"].lower()
    assert ra["speak_text"].rstrip().endswith("?")


async def test_khong_co_lan_chay_thi_noi_that_chu_khong_bao_da_huy():
    """Báo "đã hủy" khi không có gì để hủy là nói dối về một việc **an toàn**: tài xế tin
    rằng xe vừa dừng một thứ đang chạy, và thôi không tìm cách dừng nó nữa."""
    ra = await _noi(outcome="routine_khong_co_lan_chay")
    assert "không có" in ra["speak_text"].lower()
    assert "đã hủy" not in ra["speak_text"].lower()
    assert "đã dừng" not in ra["speak_text"].lower()


async def test_da_huy_thi_noi_ngan():
    ra = await _noi(outcome="routine_da_huy")
    assert len(ra["speak_text"]) <= 60


async def test_xem_truoc_thi_hoi_lai_chu_khong_bao_da_chay():
    ra = await _noi(outcome="routine_preview", routine_id="rtn_0")
    assert "đã chạy" not in ra["speak_text"].lower()
    assert ra["speak_text"].rstrip().endswith("?")


@pytest.mark.parametrize("outcome", _SAU_LOI_RA)
async def test_khong_loi_ra_nao_roi_vao_cau_mac_dinh(outcome: str):
    """Đây là ca có bằng chứng cụ thể, không phải đề phòng: `"Đã xử lý yêu cầu."` chính là
    câu xe đã nói ra trên HTTP thật khi sáu lối ra này chưa có lời thoại nào."""
    ra = await _noi(outcome=outcome, routine_ung_vien=["Đi làm"])
    assert ra["speak_text"], f"{outcome} không có câu nào"
    assert ra["speak_text"] != _FALLBACK, f"{outcome} rơi vào câu mặc định"
    assert ra["speak_text"] != OUTCOME_MESSAGES["completed"], f"{outcome} mượn câu của 'completed'"


@pytest.mark.parametrize("outcome", _SAU_LOI_RA)
async def test_moi_loi_ra_deu_duoc_phan_loai_o_nghe_tiep(outcome: str):
    """Sáu outcome mới phải được `nghe_tiep` xếp chỗ tường minh, không rơi mặc định.

    Bài học đắt nhất của `con_nghe_tiep`: bản đầu chỉ biết bốn outcome và mọi cái khác im
    lặng thành `False`, nên `"Camp Mode là gì"` trả lời được mà mic vẫn đóng. Thêm sáu
    outcome mà quên xếp chỗ là dựng lại đúng lỗi ấy.
    """
    from src.agents.nghe_tiep import OUTCOME_CON_NGHE, OUTCOME_DONG

    assert outcome in OUTCOME_CON_NGHE or outcome in OUTCOME_DONG, f"{outcome} chưa xếp chỗ"

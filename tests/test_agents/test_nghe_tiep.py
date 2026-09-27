"""Cửa sổ nghe tiếp mở khi nào — phanh 1 của spec §3.1.

FE chỉ nghe thấy **tiếng**; nó không phân biệt được `"mức 2"` với `"lát nữa mở cốp lấy
đồ nhé"`. Chỉ backend biết lượt vừa rồi xe **có hiểu gì không**, nên phanh chính nằm ở đây.

Đo được (graph thật, 29/08) — ba câu người nói với NGƯỜI, mic đang mở:

    "Lát nữa mở cốp lấy đồ nhé"          -> not_control/default_to_manual
    "Hôm qua tôi bật đèn pha suốt"       -> not_control/default_to_manual
    "Thôi tắt nhạc đi để anh nghe điện"  -> not_control/default_to_manual

Cả ba rơi vào `default_to_manual`, nên đóng cửa sổ ở đó là chặn được cảnh xe chen vào
cuộc nói chuyện ngay sau câu đầu tiên.

## Vì sao ở module riêng chứ không ở `route_node`

`route_node` chỉ thấy `clarify`/`offer`/`control` — nó **không** thấy `completed`, mà
`completed` là ~90% lượt (đo trên `bao-loi-2408`) và là ca chính của cả tính năng. Bản
đầu của #363 để `route_node` tự ghi `mo_mic_ngan`; đó là chỗ sai, và module này sửa nó.
"""

from __future__ import annotations

import pytest

from src.agents.nghe_tiep import LY_DO_DONG, OUTCOME_CON_NGHE, OUTCOME_DONG, con_nghe_tiep


@pytest.mark.parametrize(
    "state",
    [
        # Ca chính: vừa làm xong một việc, rất có thể còn việc nữa.
        {"outcome": "completed", "route_reason": "deterministic_rule"},
        # Xe vừa hỏi lại một slot CÓ rào chắn (#363).
        {"outcome": "clarify", "route_reason": "missing_fan_level"},
        {"outcome": "clarify", "route_reason": "missing_window_side"},
        # Xe vừa nêu một đề nghị có/không (#367).
        {"outcome": "offer", "route_reason": "question_about_supported_action"},
        # Xe trả lời được một câu hỏi sổ tay. Giá trị `outcome` ở đây là thứ đo được
        # trên graph thật, KHÔNG phải thứ tôi nhớ — xem docstring cuối file.
        {"outcome": "grounded_answer", "route_reason": "manual_question", "intent": "manual_query"},
        {"outcome": "grounded_continue", "route_reason": "continue_reading", "intent": "manual_continue"},
        # Lệnh chạy sau khi tài xế duyệt — cũng là "vừa làm xong một việc".
        {"outcome": "approval_granted", "route_reason": "deterministic_rule"},
        # Lý do `default_to_manual` KHÔNG còn đóng: nó nghĩa "luật không khớp", không
        # phải "xe không hiểu". Đo được: câu này mang lý do ấy mà RAG vẫn trả lời được.
        {"outcome": "grounded_answer", "route_reason": "default_to_manual"},
    ],
)
def test_hoi_thoai_dang_chay_thi_con_nghe(state: dict):
    assert con_nghe_tiep(state) is True


def test_doc_danh_sach_poi_thi_con_nghe():
    """Ca này tới từ #371 + #355 mục 2b, **sau** khi spec được viết — đo lại 29/08:

        "Tìm các quán cà phê gần đây" -> completed/deterministic_rule, intent=poi_search
            VIVI: "Tôi tìm được 2 chỗ: … Bạn muốn đi chỗ nào?"
        "Cái đầu tiên"                -> completed/chon_tu_danh_sach_poi

    Xe đọc một danh sách rồi **hỏi lại** — đúng hình dạng cần mic mở. Nó rơi vào nhánh
    `completed` sẵn có nên không phải thêm luật nào; test này khoá điều đó để một thay đổi
    ở nhánh POI không âm thầm tắt mic ngay tại chỗ vừa mời tài xế chọn.
    """
    assert con_nghe_tiep({"outcome": "completed", "route_reason": "deterministic_rule", "intent": "poi_search"}) is True


@pytest.mark.parametrize(
    "state",
    [
        # Xe không tìm thấy gì — nhiều khả năng câu ấy không nói với xe.
        {"outcome": "grounded_refusal", "route_reason": "default_to_manual"},
        {"outcome": "not_control", "route_reason": "default_to_manual"},
        # Phê duyệt HITL đã có auto-listen riêng (#207b) — không mở cửa sổ thứ hai.
        {"outcome": "approval_required", "route_reason": "deterministic_rule"},
        {"outcome": "approval_rejected", "route_reason": "deterministic_rule"},
        {"outcome": "execution_failed", "route_reason": "deterministic_rule"},
        {"outcome": "index_unavailable", "route_reason": "manual_question"},
        # #363 đã chốt: nghe hụt thì trả quyền chủ động về tài xế.
        {"outcome": "not_control", "route_reason": "manh_khong_khop_mau"},
        # Tài xế vừa nói "thôi".
        {"outcome": "not_control", "route_reason": "offer_declined"},
        {"outcome": "not_control", "route_reason": "giai_tan"},
        # Không có gì để nối tiếp.
        {"outcome": "blocked", "route_reason": "deterministic_rule"},
        {"outcome": "denied", "route_reason": "headlight_off_not_permitted"},
        {"outcome": "validation_denied", "route_reason": "deterministic_rule"},
    ],
)
def test_khong_con_gi_de_noi_tiep_thi_dong(state: dict):
    assert con_nghe_tiep(state) is False


def test_clarify_khong_co_mau_thi_dong():
    """Nửa còn lại của "một tập, hai vai" (#363): slot không có rào chắn thì không mở mic.

    `relative_change_unsupported` nằm ngoài `mau_slot.CO_MAU`, nên dù nó là `clarify` —
    tức xe **có** hỏi — ta vẫn không mở cửa sổ, vì không có gì soi câu trả lời.
    """
    assert con_nghe_tiep({"outcome": "clarify", "route_reason": "relative_change_unsupported"}) is False


def test_state_rong_hay_hong_thi_dong():
    """Fail-closed: không đọc được kết cục thì **không** mở mic.

    Bất đối xứng có chủ ý — mở nhầm là mở một cửa không ai rào; đóng nhầm chỉ là bắt tài
    xế nói lại wake word.
    """
    for state in ({}, {"outcome": None}, {"outcome": "khong_ton_tai"}, {"outcome": 42}):
        assert con_nghe_tiep(state) is False


def test_ly_do_dong_thang_ca_khi_outcome_nghe_co_ve_on():
    """`manh_khong_khop_mau` mang `outcome = "not_control"`, mà `not_control` một mình
    không nói được gì — nó cũng là nhãn của một câu trả lời sổ tay **thành công**. Lý do
    mới là thứ phân biệt, nên nó phải thắng."""
    assert "manh_khong_khop_mau" in LY_DO_DONG
    assert con_nghe_tiep({"outcome": "not_control", "route_reason": "manh_khong_khop_mau"}) is False


def test_ly_do_dong_thang_ca_khi_outcome_la_completed():
    """Ca cực đoan, viết ra để hằng `LY_DO_DONG` giữ đúng nghĩa "**luôn** đóng".

    Không ca thật nào hôm nay ghép `completed` với một lý do đóng, nhưng nếu mai có thì
    lý do phải thắng — nó cụ thể hơn, và nó là thứ mang tin "xe không hiểu".
    """
    assert con_nghe_tiep({"outcome": "completed", "route_reason": "giai_tan"}) is False


# --- Khoá tính đầy đủ: một outcome mới phải được ai đó xếp chỗ -----------------


def test_moi_outcome_deu_duoc_phan_loai_tuong_minh():
    """Đây là bài học đắt nhất của module này, viết thành test để không lặp lại.

    Bản đầu chỉ biết `completed` và `offer`; mọi outcome khác im lặng rơi về `False`. Lỗi
    ấy **unit test không bắt được** — chính tôi viết state theo trí nhớ nên chúng xanh
    trên một hư cấu. Nó chỉ lộ ra khi chạy giọng người thật qua WS thật (29/08):

        "Camp Mode là gì" -> outcome=grounded_answer -> đóng mic

    Xe trả lời được một câu hỏi mà cửa sổ vẫn đóng.

    Nên nay không có "mặc định im lặng" nữa: mỗi outcome **phải** nằm trong đúng một
    trong hai tập. Thêm một outcome mới vào `OUTCOME_MESSAGES` mà quên xếp chỗ ở đây thì
    test này đỏ, và người thêm phải trả lời câu hỏi "sau lượt này có nên nghe tiếp không?"
    — thay vì để câu trả lời mặc định là "không" một cách vô tình.
    """
    from src.agents.nodes.compose import OUTCOME_MESSAGES

    chua_xep = sorted(set(OUTCOME_MESSAGES) - OUTCOME_CON_NGHE - OUTCOME_DONG)
    assert chua_xep == [], f"outcome chưa phân loại: {chua_xep} — xem docstring test này"


def test_hai_tap_outcome_khong_giao_nhau():

    assert OUTCOME_CON_NGHE & OUTCOME_DONG == set()

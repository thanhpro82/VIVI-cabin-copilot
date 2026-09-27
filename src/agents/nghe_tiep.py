"""Cửa sổ nghe tiếp còn mở hay đóng — phanh 1 của spec §3.1.

## Vì sao quyết định này nằm ở BACKEND

FE chỉ nghe thấy **tiếng**. Nó không phân biệt được `"mức 2"` (câu trả lời) với
`"lát nữa mở cốp lấy đồ nhé"` (nói với người ngồi cạnh). Chỉ backend biết lượt vừa rồi
xe **có hiểu gì không**, nên phanh chính phải nằm ở đây.

## Vì sao ở module riêng chứ không ở `route_node`

`route_node` chỉ thấy `clarify`/`offer`/`control` — nó **không** thấy `completed`, mà
`completed` là ~90% lượt (đo trên `bao-loi-2408`) và là ca chính của cả tính năng.
Quyết định phải đọc kết cục **cuối** của lượt, nên nó đọc state cuối, một lần, ở
`assistant_response_payload`.

Bản đầu của #363 để `route_node` tự ghi `mo_mic_ngan`. Hai nơi cùng ghi một field là cách
chắc chắn để chúng lệch nhau, nên module này là **chủ sở hữu duy nhất**.

## Luật, và nó fail-closed

Mở khi hội thoại **đang chạy**; đóng khi xe **không hiểu** hoặc **không còn gì nối tiếp**.
Không đọc được kết cục thì **đóng**. Bất đối xứng có chủ ý: mở nhầm là mở một cửa không ai
rào, còn đóng nhầm chỉ là bắt tài xế nói lại wake word.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.mau_slot import CO_MAU

__all__ = ["LY_DO_DONG", "OUTCOME_CON_NGHE", "OUTCOME_DONG", "con_nghe_tiep"]

#: Kết cục mà hội thoại **còn đang chạy** — allowlist, không phải "mọi thứ trừ...".
#:
#: Bản đầu chỉ có `completed` và `offer`, và nó **sai** — lỗi bị bắt bằng giọng người thật
#: qua WS thật 29/08, không phải bằng unit test:
#:
#:     "Camp Mode là gì" -> outcome=grounded_answer  intent=manual_query  -> đóng mic
#:
#: Xe trả lời được một câu hỏi mà cửa sổ vẫn đóng. Nguyên nhân: tôi giả định câu trả lời
#: sổ tay ra `outcome="not_control"`, nhưng nó ra `grounded_answer`. Unit test xanh vì
#: chính tôi viết state theo trí nhớ — đúng cái bẫy `real.citations.test.ts` cảnh báo
#: ("chép nguyên văn, không viết lại theo trí nhớ").
#:
#: `test_moi_outcome_deu_duoc_phan_loai_tuong_minh` nay khoá điều đó: một outcome mới
#: **bắt buộc** phải được xếp vào một trong hai tập, không được im lặng rơi về `False`.
OUTCOME_CON_NGHE: frozenset[str] = frozenset(
    {
        "completed",         # lệnh vừa chạy xong — rất có thể còn lệnh nữa (~90% lượt)
        "approval_granted",  # cũng là lệnh vừa chạy, chỉ khác là qua HITL
        "offer",             # xe vừa hỏi có/không (#367)
        "grounded_answer",   # xe vừa trả lời được từ sổ tay
        "grounded_continue", # xe vừa đọc tiếp phần dư
        # --- Routine (#274, #299). Xếp chỗ từng cái, không gộp cả nhóm ---
        "routine_da_chay",   # vừa chạy một chuỗi lệnh — cùng lẽ với `completed`
        "routine_da_huy",    # vừa dừng một chuỗi lệnh; tài xế thường nói tiếp ngay
        "routine_preview",   # xe vừa hỏi "chạy chứ?" — không nghe tiếp thì hỏi để làm gì
        "routine_mo_ho",     # xe vừa hỏi "bạn muốn cái nào?"
        "routine_khong_thay",# xe vừa đọc danh sách và mời chọn — cùng hình dạng với POI
    }
)

#: Kết cục **đóng** cửa sổ. Khai tường minh để phép kiểm "đã phân loại hết chưa" chạy được.
#:
#: `approval_required` nằm đây có chủ ý: nhánh phê duyệt HITL **đã có auto-listen riêng**
#: từ #207b (`choDuyet`). Mở thêm một cửa sổ thứ hai ở cùng lượt là hai cơ chế cùng giành
#: một cái mic.
OUTCOME_DONG: frozenset[str] = frozenset(
    {
        # Tài xế nói "dừng lại" mà chẳng có gì đang chạy: rất có thể câu ấy **không nói
        # với xe**. Cùng lập luận với `manh_khong_khop_mau` — trả quyền chủ động về tài
        # xế thay vì mở thêm một cửa sổ nghe sau một lượt xe không giúp được gì.
        "routine_khong_co_lan_chay",
        # Lỗi hệ thống: không có gì để nói tiếp, và mở mic sau một lượt xe vừa hỏng là
        # mời tài xế nói vào một thứ vẫn đang hỏng.
        "routine_loi_ngu_canh",
        # Từ chối có lý do rõ (chưa đặt địa điểm, Routine đang tắt...): tài xế cần **thao
        # tác trên màn hình**, không phải nói thêm một câu. Mở mic là mời họ nói vào một
        # thứ lời nói không sửa được.
        "routine_tu_choi",
        "grounded_refusal",           # xe không tìm thấy gì — rất có thể câu ấy không nói với xe
        "not_control",
        "clarify",                    # xử lý riêng bên dưới: chỉ mở khi lý do có mẫu
        "blocked",
        "denied",
        "validation_denied",
        "execution_failed",
        "index_unavailable",
        "retrieval_failed",
        "vehicle_state_unavailable",
        "approval_required",
        "approval_already_pending",
        "approval_expired",
        "approval_invalidated_plan",
        "approval_invalidated_state",
        "approval_not_owned",
        "approval_predicate_failed",
        "approval_rejected",
    }
)

#: Lý do **luôn** đóng, kể cả khi `outcome` trông có vẻ ổn.
#:
#: `default_to_manual` từng nằm đây và đã được **bỏ ra** cùng lần sửa 29/08: nó nghĩa là
#: *"luật không khớp"*, không phải *"xe không hiểu"* — `"Trong xe nóng quá giảm điều hòa
#: xuống"* mang lý do ấy mà RAG vẫn trả lời được. Thứ mang tin "không hiểu" là **outcome**
#: `grounded_refusal`, và nó đã ở `OUTCOME_DONG`.
LY_DO_DONG: frozenset[str] = frozenset(
    {
        "manh_khong_khop_mau",  # #363: nghe hụt thì trả quyền chủ động về tài xế
        "offer_declined",       # tài xế vừa nói "thôi"
        "giai_tan",
    }
)


def con_nghe_tiep(state: Mapping[str, Any]) -> bool:
    """Sau lượt này có nên để mic mở chờ câu tiếp theo không?"""
    ly_do = state.get("route_reason")
    if isinstance(ly_do, str) and ly_do in LY_DO_DONG:
        return False

    outcome = state.get("outcome")
    if not isinstance(outcome, str):
        return False
    if outcome in OUTCOME_CON_NGHE:
        return True
    if outcome == "clarify":
        # "Một tập, hai vai" của #363: chỉ mở mic ở slot có rào chắn.
        return isinstance(ly_do, str) and ly_do in CO_MAU
    return False

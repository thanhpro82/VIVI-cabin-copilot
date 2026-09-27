"""Màn hình đọc đúng thứ loa vừa đọc — một chuỗi, hai kênh.

Nhóm yêu cầu 21/08: `display_text` **quá dài**. Tài xế nhìn lại màn hình chỉ để
*"xem lại phụ đề"*, chứ không để đọc lại nguyên đoạn sổ tay. Nên hai trường trên dây
hợp nhất, và bản được giữ là **`speak_text`**.

## Trước đây hai kênh lệch nhau ở đúng hai chỗ

| lượt | `display_text` cũ | `speak_text` |
|---|---|---|
| tra sổ tay lượt đầu | câu dẫn + **trích nguyên văn tới 1.200 ký tự** | câu dẫn + câu đã chọn (≤ 240) + lời mời |
| "đọc tiếp" | lát vừa đọc + dấu `(còn tiếp — …)` | lát vừa đọc + lời mời |

Mọi lượt khác (điều khiển, từ chối, áp suất lốp, thiếu trang bị) vốn đã trùng.

## Sửa 30/08: bất biến ở tầng PAYLOAD, không ở compose

Bản đầu ép hai kênh bằng nhau ngay trong `compose_node`, và đó là chỗ sai — nó xoá luôn
vế thứ ba của **câu hỏi lại**: `"Nói mỗi mức cũng được, ví dụ \"mức 2\"."` Vế ấy **cố ý
chỉ dành cho màn hình** (ví dụ trong ngoặc kép chỉ có nghĩa khi nhìn thấy dấu ngoặc, xem
`CLARIFY_SPEAK`), là một trong ba thành phần #148 xác định là cần thiết, và #354 đã khoá
bằng test. Ép bằng nhau ở compose là đổi một lỗi lấy một lỗi khác.

Nay compose báo **trung thực cả hai kênh**, còn bất biến giữ ở đúng một chỗ —
`assistant_response_payload`, như chính PR này lập luận từ đầu. Luật ở đó là một câu:
**bản nhìn được giữ khi nó vẫn ngắn như một phụ đề, dài hơn thế thì màn hình nhận đúng
bản đã nói.** Trần là `MAX_SPOKEN_CHARS` — cùng ngân sách với câu nói.

    clarify      bản nhìn 119 ký tự  <= 240  -> giữ, ví dụ còn
    tra sổ tay   bản nhìn 914 ký tự   > 240  -> lấy bản nói (166 ký tự)

Các test dưới đây vì thế khẳng định ở tầng payload. Không nới lỏng: `display_text` của
compose **không** đi đâu khác — `turns.py` và `trace_collector.py` đều đọc payload.

## Cái mất, nói thẳng ra

`display_text` là chỗ **duy nhất** nguyên văn cả đoạn sổ tay tới được màn hình.
Sau thay đổi này, muốn đọc hết đoạn thì phải nói "đọc tiếp" từng lát, hoặc mở
citation (`GET /citations/{id}`). Đó là **đúng thứ nhóm yêu cầu**, không phải tác dụng
phụ — nhưng phải ghi ra, vì `trace` đã redact cả ba trường văn bản
(`trace_collector.py:14`) nên bản dài giờ không còn xuất hiện ở đâu trên dây.

## Cái KHÔNG mất

ADR-015 vẫn nguyên: bản ngắn cũng là **nguyên văn**, chỉ ít câu hơn.
`speech_policy` chọn câu *có sẵn trong đoạn nguồn*, không diễn đạt lại — nên lớp lỗi
4/40 "rơi mất điều kiện theo phiên bản" không quay lại qua cửa này.
"""

import pytest

from src.agents.nodes.compose import compose_node
from src.rag.models import Evidence
from src.services.ivi_events import MAX_SPEECH_CHARS, assistant_response_payload

#: Dài hơn hẳn trần nói, và có một câu mang điều kiện theo phiên bản ở cuối để
#: nhìn thấy được phần bị bỏ lại.
DOAN_DAI = ("Đây là một câu sổ tay đủ dài để lấp chỗ. " * 40) + "Bản ECO có chỉnh điện 8 hướng."


def _luot_so_tay(text: str = DOAN_DAI) -> dict:
    return {
        "outcome": "grounded_answer",
        "evidence": [Evidence(section="Ghế", page=3, text=text, chunk_id="c1", score=0.9)],
    }


def _luot_doc_tiep() -> dict:
    return {
        "outcome": "not_control",
        "intent": "manual_continue",
        "query": "đọc tiếp",
        "speech_source_text": DOAN_DAI,
        "speech_da_doc": [],
    }


@pytest.mark.asyncio
async def test_luot_so_tay_hai_kenh_cung_mot_chuoi():
    """Đoạn sổ tay dài vượt trần phụ đề, nên màn hình nhận đúng bản đã nói."""
    ra = assistant_response_payload(await compose_node(_luot_so_tay()))
    assert ra["display_text"] == ra["speak_text"]


@pytest.mark.asyncio
async def test_luot_so_tay_man_hinh_khong_con_dai_hon_tran_doc():
    """Phép đo của chính yêu cầu nhóm 21/08: màn hình không dài hơn lời nói.

    Trước bản này `display_text` lên tới `QUOTE_MAX_CHARS = 1.200`, gấp 5 lần trần nói.
    """
    ra = assistant_response_payload(await compose_node(_luot_so_tay()))
    assert len(ra["display_text"]) <= MAX_SPEECH_CHARS


@pytest.mark.asyncio
async def test_cau_hoi_lai_van_giu_vi_du_tren_man_hinh():
    """Nửa còn lại của luật, và là ca mà bản đầu làm hỏng.

    Câu hỏi lại **được phép** dài hơn lời nói, vì phần dôi ra là một ví dụ 38 ký tự chỉ
    có nghĩa khi nhìn. Trần phụ đề cho nó qua; đoạn sổ tay 914 ký tự thì không.
    """
    ra = assistant_response_payload(
        await compose_node({"outcome": "clarify", "route_reason": "missing_fan_level"})
    )
    assert 'ví dụ "mức 2"' in ra["display_text"]
    assert 'ví dụ "mức 2"' not in ra["speak_text"]
    assert len(ra["display_text"]) <= MAX_SPEECH_CHARS


@pytest.mark.asyncio
async def test_luot_doc_tiep_hai_kenh_cung_mot_chuoi():
    """Lượt "đọc tiếp" là chỗ lệch thứ hai, và nó lệch **ngược chiều** lượt đầu:
    ở đây `speak` dài hơn vì mang lời mời, còn `display` mang một dấu ngoặc riêng.
    Gộp lại thì dấu ngoặc ấy không còn lý do tồn tại — lời mời đã nói hộ nó.
    """
    out = await compose_node(_luot_doc_tiep())
    assert out["speak_text"], "lượt này phải đọc được ít nhất một lát"
    assert out["display_text"] == out["speak_text"]


@pytest.mark.asyncio
async def test_van_con_co_de_fe_dung_render_nut_nghe_tiep():
    """Hợp nhất hai chuỗi **không** được làm mất tín hiệu "còn nữa".

    `has_more_to_read` mới là thứ FE bám để dựng nút; dấu `(còn tiếp)` trong chuỗi
    chỉ là bản sao cho mắt người. Bỏ bản sao mà làm hỏng cờ thì là hồi quy.
    """
    dau = await compose_node(_luot_so_tay())
    assert dau["has_more_to_read"] is True
    tiep = await compose_node(_luot_doc_tiep())
    assert tiep["has_more_to_read"] is True


@pytest.mark.asyncio
async def test_nguyen_van_ca_doan_van_con_trong_state_de_doc_tiep():
    """Bản dài không bị **xoá**, nó chỉ thôi đi ra dây.

    `speech_source_text` là thứ lượt "đọc tiếp" đọc tiếp từ đó. Rút gọn nhầm chỗ này
    thì tài xế mất luôn phần còn lại của đoạn, chứ không phải chỉ mất một khung hiển thị.
    """
    out = await compose_node(_luot_so_tay())
    assert "Bản ECO có chỉnh điện 8 hướng." in out["speech_source_text"]


@pytest.mark.asyncio
async def test_tren_day_hai_truong_bang_nhau():
    """Cổng thật nằm ở đây: `assistant_response_payload` dựng **cả** sự kiện WS
    `assistant.response` lẫn envelope HTTP của `POST /turns/text` (`turns.py:514`).
    Khoá ở tầng compose thôi là chưa đủ — bản trước dựng `display_text` từ
    `response_text`, nên một node trả đúng vẫn có thể ra dây sai.
    """
    out = await compose_node(_luot_so_tay())
    payload = assistant_response_payload(out)
    assert payload["display_text"] == payload["speak_text"]
    assert len(payload["display_text"]) <= MAX_SPEECH_CHARS


@pytest.mark.asyncio
async def test_node_cu_chua_tra_speak_text_thi_van_lui_ve_response_text():
    """Đường lui phải giữ: `approvals.py` và vài test dựng payload bằng tay."""
    payload = assistant_response_payload({"response_text": "Đã hủy theo lựa chọn của bạn."})
    assert payload["display_text"] == "Đã hủy theo lựa chọn của bạn."
    assert payload["speak_text"] == payload["display_text"]


@pytest.mark.asyncio
async def test_luot_dieu_khien_khong_doi_gi():
    """Lượt không phải sổ tay vốn đã trùng nhau — bản này không được chạm tới nó."""
    out = await compose_node({"outcome": "completed", "evidence": []})
    assert out["display_text"] == out["speak_text"] == "Đã thực hiện lệnh trên xe mô phỏng."

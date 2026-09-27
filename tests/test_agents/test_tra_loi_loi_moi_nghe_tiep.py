"""Tài xế trả lời **"có"/"thôi"** cho lời mời *"Bạn có muốn nghe tiếp nguyên văn không?"*

Đây là ô còn lại của issue #107: *"dùng lại cùng bộ nhận dạng cho câu trả lời 'nghe
tiếp không?'"*. Nửa phê duyệt đã xong ở PR #142.

## Hai lỗ, cùng một gốc

Đo trên `develop` ngày 16/08, sau khi #142 đã merge:

| lượt 1 | lượt 2 | xe trả lời |
|---|---|---|
| hỏi sổ tay → *"…Bạn có muốn nghe tiếp nguyên văn không?"* | `"Có"` | *"Hiện không có yêu cầu nào đang chờ bạn xác nhận."* |
| không có gì đang chờ | `"Có"` | *"Hiện không có yêu cầu nào đang chờ bạn xác nhận."* |

Hàng thứ hai là **hồi quy do chính #142 gây ra**: cổng phê duyệt ở `turns.py` chạy trên
mọi lượt, nên nó cướp mọi tiếng "có"/"không" trong cả hệ thống. Hàng thứ nhất là cái
giá của việc ấy rơi đúng vào chỗ đau nhất — ngay lượt sau mỗi câu hỏi sổ tay dài.

Gốc chung: bảng từ không phân biệt **từ chỉ dùng cho phê duyệt** (`đồng ý`, `từ chối`)
với **tiếng có/không trần**, thứ trả lời bất cứ câu hỏi nào vừa được đặt ra.

Chính `router.py` đã né va chạm này bằng cách hẹp lại — chú thích tại `_CONTINUE_READING`
ghi *"cố ý không nhận 'có'/'vâng'/'ok' trần […] HITL cũng hỏi có/không"*. Cách né ấy
đúng **cho router**, vì ADR-006/ADR-010 cấm nó đọc trạng thái. Nhưng ngữ cảnh có tồn
tại, chỉ là nằm ở chỗ khác, nên lời giải là đặt cổng ở chỗ có ngữ cảnh chứ không phải
bỏ hẳn.
"""

import pytest

from src.agents.nodes.compose import compose_node
from src.agents.nodes.route import make_route_node
from src.agents.router import DeterministicControlRouter
from src.agents.voice_intent import doc_tra_loi_co_khong, doc_y_dinh_phe_duyet
from src.rag.models import Evidence

DOAN = (
    "Khởi tạo cửa sổ điện. "
    "Nếu không thể tự động đóng các cửa sổ thông qua chức năng nhanh, hãy làm như sau. "
    "Kéo công tắc cửa sổ lên và đóng hoàn toàn cửa sổ. "
    "Giữ công tắc ở trạng thái kéo trong hai giây. "
    "Nhả công tắc ra. "
    "Nhấn hoàn toàn công tắc cửa sổ xuống để mở cửa sổ tự động. "
    "Kéo hoàn toàn công tắc cửa sổ lên để đóng cửa sổ tự động. "
    "Lặp lại cho mỗi cửa sổ trên xe. "
    "Trong quá trình khởi tạo, cửa sổ điện không có chức năng cảm biến chống kẹp. "
    "Đảm bảo không có bộ phận cơ thể hoặc vật nào cản trở việc đóng cửa sổ điện."
)


def _route_node():
    return make_route_node(DeterministicControlRouter())


def _dang_doc_do(query: str) -> dict:
    """State của lượt kế tiếp khi lượt trước đã mời nghe tiếp."""
    return {
        "query": query,
        "speech_source_text": DOAN,
        "speech_da_doc": [0],
        "speech_citations": [],
    }


# --- Bộ đọc: hai bậc từ, và một hàm dùng chung -------------------------------------


@pytest.mark.parametrize("cau", ["đồng ý", "xác nhận", "duyệt", "từ chối", "hủy", "đừng"])
def test_tu_chi_dung_cho_phe_duyet_duoc_danh_dau_ro_rang(cau: str):
    assert doc_y_dinh_phe_duyet(cau).ro_rang_ve_phe_duyet is True


@pytest.mark.parametrize("cau", ["có", "vâng", "ừ", "ok", "được", "không", "thôi"])
def test_tieng_co_khong_tran_khong_duoc_coi_la_noi_ve_phe_duyet(cau: str):
    """Cờ này là thứ duy nhất ngăn `turns.py` cướp mọi tiếng "có" trong hệ thống.

    Nó **không** làm câu đó ngừng là câu trả lời phê duyệt — khi có phê duyệt chờ thì
    "có" vẫn duyệt (xem test dưới). Nó chỉ nói: đừng suy ra ngữ cảnh từ mỗi con chữ.
    """
    y = doc_y_dinh_phe_duyet(cau)
    assert y.quyet_dinh is not None, "van phai doc duoc y dinh"
    assert y.ro_rang_ve_phe_duyet is False


@pytest.mark.parametrize(
    ("cau", "mong_doi"),
    [
        ("có", "co"),
        ("vâng", "co"),
        ("ừ", "co"),
        ("có chứ", "co"),
        ("đồng ý", "co"),
        ("không", "khong"),
        ("thôi", "khong"),
        ("không đồng ý", "khong"),
        ("đồng ý nhưng hủy", None),
        ("khoang chứa đồ", None),
        ("hôm nay trời đẹp quá bạn nhỉ", None),
    ],
)
def test_doc_tra_loi_co_khong(cau: str, mong_doi):
    assert doc_tra_loi_co_khong(cau) == mong_doi


def test_khong_co_bang_tu_thu_hai():
    """#107 cảnh báo *"hai bộ nhận dạng sẽ lệch nhau"* — nên chỉ được có một.

    Test này khoá quan hệ chứ không khoá giá trị: thêm từ vào bảng phê duyệt mà quên
    bảng "nghe tiếp" là đúng kiểu lệch mà issue nói tới, và nó sẽ đỏ ở đây.
    """
    for cau in ["đồng ý", "xác nhận", "vâng", "ừ", "được", "ok"]:
        assert doc_tra_loi_co_khong(cau) == "co"
    for cau in ["từ chối", "hủy", "đừng", "khoan", "dừng", "thôi", "không"]:
        assert doc_tra_loi_co_khong(cau) == "khong"


# --- Cổng ngữ cảnh ở node route ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("cau", ["Có", "Vâng", "Ừ", "Có chứ"])
async def test_dap_co_khi_dang_doc_do_thi_thanh_doc_tiep(cau: str):
    out = await _route_node()(_dang_doc_do(cau))

    assert out["intent"] == "manual_continue"
    assert out["route_reason"] == "answer_to_read_more_invite"


@pytest.mark.asyncio
@pytest.mark.parametrize("cau", ["Không", "Thôi"])
async def test_dap_khong_khi_dang_doc_do_thi_dung_lai(cau: str):
    out = await _route_node()(_dang_doc_do(cau))

    assert out["intent"] == "manual_stop_reading"


@pytest.mark.asyncio
@pytest.mark.parametrize("cau", ["Có", "Không", "Vâng", "Thôi"])
async def test_khong_co_doan_doc_do_thi_cong_nay_im_lang(cau: str):
    """Không có ngữ cảnh thì không được đoán — đúng lý do router từ chối nhận "có" trần.

    Đây là vế giữ cho lời giải không trở thành chính cái nó đang sửa.
    """
    out = await _route_node()({"query": cau})

    assert out["intent"] != "manual_continue"
    assert out["intent"] != "manual_stop_reading"


@pytest.mark.asyncio
async def test_lenh_khop_luat_khong_bi_doc_thanh_cau_tra_loi():
    """Cổng chỉ xen vào khi luật **không** bắt được gì."""
    out = await _route_node()(_dang_doc_do("Mở kính bên lái 30 phần trăm"))

    assert out["intent"] != "manual_continue"
    assert out["outcome"] == "control"


@pytest.mark.asyncio
@pytest.mark.parametrize("cau", ["Ừ mở kính", "Có mở cốp", "Được bật đèn", "Thôi đóng kính"])
async def test_tieng_tran_dung_truoc_mot_lenh_khong_phai_cau_tra_loi(cau: str):
    """Ca này đo được là hỏng ở bản đầu, và nó là lý do bộ đọc phải chặt hơn nhánh phê duyệt.

    Cả bốn câu đều ba từ, đều mở đầu bằng tiếng trần, và đều **không** phải lời đáp cho
    lời mời nghe tiếp. Router hiện chưa bắt được lệnh có tiền tố như vậy — nó trả
    `default_to_manual` — nên nếu cổng này cũng nhận bừa thì tài xế nói "ừ mở kính" và
    xe đọc sổ tay cho nghe. Giới hạn **số từ** không cứu được: chúng ngắn hơn ngưỡng 5
    từ của nhánh phê duyệt. Phải đòi câu **chỉ gồm** từ trả lời.

    Chú ý phạm vi: test này khoá việc cổng mới không làm mọi thứ tệ đi. Nó **không**
    khẳng định `"ừ mở kính"` sẽ chạy — router vẫn đưa nó về tra sổ tay, y như trước, và
    đó là chuyện của #148 phần B chứ không phải của issue này.
    """
    out = await _route_node()(_dang_doc_do(cau))

    assert out["intent"] not in ("manual_continue", "manual_stop_reading")


@pytest.mark.asyncio
async def test_cau_hoi_that_khong_bi_cuop_du_co_chua_chu_co():
    """`"Xe có sạc nhanh không?"` chứa cả "có" lẫn "không" — nhưng nó là câu hỏi.

    Bộ đọc trả `None` cho câu này vì hai tín hiệu độc lập là mơ hồ, và ở nhánh nghe tiếp
    mơ hồ nghĩa là **nhường** cho đường thường chứ không làm hỏng lượt.
    """
    out = await _route_node()(_dang_doc_do("Xe có sạc nhanh không"))

    assert out["intent"] not in ("manual_continue", "manual_stop_reading")


@pytest.mark.asyncio
async def test_doc_tiep_van_di_duong_luat_cu():
    """`"đọc tiếp"` đã có luật riêng trong router — cổng mới không được giẫm lên nó."""
    out = await _route_node()(_dang_doc_do("Đọc tiếp"))

    assert out["intent"] == "manual_continue"
    assert out["route_reason"] == "continue_reading"


# --- Composer: "thôi" là *chưa phải bây giờ*, không phải *bỏ hẳn* ------------------


@pytest.mark.asyncio
async def test_thoi_khong_xoa_cho_dang_doc_do():
    """Dọn trạng thái ở đây thì `"đọc tiếp"` ba mươi giây sau nhận lại "đã đọc hết rồi".

    Câu ấy sai sự thật, và nó đúng lớp bug đã gặp ngày 15/08 ở nhánh biến thể. Trong
    ngữ nghĩa merge của LangGraph, khoá **vắng mặt** là giữ nguyên còn khoá rỗng là xoá
    — nên test khoá đúng chỗ đó: không có khoá `speech_*` nào trong dict trả về.
    """
    out = await compose_node({**_dang_doc_do("Thôi"), "intent": "manual_stop_reading"})

    assert "speech_source_text" not in out
    assert "speech_da_doc" not in out
    assert out["has_more_to_read"] is True
    assert "đọc tiếp" in out["speak_text"].lower()


@pytest.mark.asyncio
async def test_thoi_roi_doc_tiep_van_doc_duoc():
    """Vế còn lại của test trên, đo bằng hành vi thật thay vì bằng hình dạng dict."""
    sau_thoi = await compose_node({**_dang_doc_do("Thôi"), "intent": "manual_stop_reading"})
    # LangGraph merge dict trả về vào state — mô phỏng đúng thế.
    state = {**_dang_doc_do("Đọc tiếp"), **sau_thoi, "intent": "manual_continue"}

    out = await compose_node(state)

    assert out["speak_text"], "phai doc duoc tiep sau khi tu choi mot lan"
    assert "đã đọc hết" not in out["speak_text"].lower()


@pytest.mark.asyncio
async def test_luot_so_tay_van_gan_loi_moi_nhu_cu():
    """Bánh cóc: sửa nhánh trả lời không được làm mất chính lời mời sinh ra nó."""
    out = await compose_node(
        {
            "outcome": "grounded_answer",
            "query": "cách khởi tạo cửa sổ điện",
            "evidence": [Evidence(section="Cửa sổ điện", page=3, text=DOAN, chunk_id="c1", score=0.9)],
        }
    )

    assert out["speech_source_text"] == DOAN
    assert "nghe tiếp" in out["speak_text"].lower()

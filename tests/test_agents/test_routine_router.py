"""Router nhận ra ý định Routine. Issue #274, #299.

Đo trên `develop` @ `d088b49` **trước** khi sửa — sáu câu, sáu lần tra sổ tay:

    "Chạy routine Đi làm"         -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
    "Routine Về nhà gồm những gì" -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
    "Dừng lại"                    -> "Tôi không tìm thấy thông tin này trong sổ tay xe."

Câu cuối đáng lo nhất: đó là lệnh **hủy**.

`routines_intent.py` đã đọc được ý định và đã có test (#285), nhưng **không ai gọi nó** —
chỉ `tests/test_agents/test_routines_intent.py` import. Task này là chỗ nối, không phải
chỗ viết mới.
"""

from __future__ import annotations

import pytest

from src.agents.router import DeterministicControlRouter

_ROUTER = DeterministicControlRouter()


def _mo(cau: str) -> str:
    d = _ROUTER.route(cau)
    return f"{d.disposition}/{d.intent}"


@pytest.mark.parametrize(
    ("cau", "mong"),
    [
        ("Chạy routine Đi làm", "routine/routine_run"),
        ("Bắt đầu routine Về nhà", "routine/routine_run"),
        ("Thực hiện routine Thư giãn", "routine/routine_run"),
        ("Xem trước routine Đi làm", "routine/routine_preview"),
        ("Routine Về nhà gồm những gì", "routine/routine_preview"),
        ("Dừng lại", "routine/routine_cancel"),
        ("Hủy routine", "routine/routine_cancel"),
        ("Hủy routine Đi làm", "routine/routine_cancel"),
    ],
)
def test_y_dinh_routine_duoc_nhan(cau: str, mong: str):
    assert _mo(cau) == mong, cau


def test_router_khong_dung_plan_cho_routine():
    """Router **không** phân giải tên: nó không đọc được danh sách Routine của user, và
    ADR-006/010 cấm nó đọc trạng thái. Phân giải là việc của node.

    Nên `disposition = "routine"` phải giống `offer`/`clarify` ở chỗ **cấm** mang
    `candidate_plan` — nếu nó mang, một plan dựng từ chỗ không biết Routine nào sẽ trôi
    thẳng xuống executor.
    """
    d = _ROUTER.route("Chạy routine Đi làm")
    assert d.candidate_plan is None


@pytest.mark.parametrize(
    "cau",
    [
        # Lệnh xe thường — không được nuốt thành Routine.
        "Bật điều hòa",
        "Mở cốp xe",
        "Tăng quạt gió",
        # Câu hỏi sổ tay.
        "Camp Mode là gì",
        "Áp suất lốp bao nhiêu",
        # Tên Routine KHÔNG bao giờ tự kích hoạt (#285): thiếu động từ + từ chỉ loại.
        "Đi làm",
        "Về nhà",
        "Hôm nay tôi đi làm muộn",
    ],
)
def test_cau_khac_khong_bi_doc_thanh_routine(cau: str):
    assert _ROUTER.route(cau).disposition != "routine", cau


@pytest.mark.parametrize("cau", ["dừng", "thôi", "không"])
def test_khong_cuop_mat_cu_chi_duoi_tro_ly(cau: str):
    """Chỗ suýt hỏng, tìm ra bằng đo chứ không bằng đọc code (30/08):

        doc_tra_loi_co_khong("dừng")     -> "khong"     ← cử chỉ ĐUỔI
        doc_tra_loi_co_khong("dừng lại") -> None        ← rơi xuống sổ tay

    `"dừng"` trơ **đang là** cách tài xế đuổi trợ lý đi (`_la_cau_giai_tan`), và đó là
    cách **duy nhất** đóng một cửa sổ nghe tiếp mà không phải im lặng 6 giây. Một regex
    hủy rộng tay nuốt mất nó thì cửa sổ ấy không còn đường đóng chủ động nào.

    Nên `_HUY` neo đầu câu và **đòi từ thứ hai**. Test này khoá điều đó.
    """
    d = _ROUTER.route(cau)
    assert d.disposition != "routine", cau
    assert d.reason == "default_to_manual", f"{cau}: cổng đuổi trợ lý cần đúng lý do này"


def test_dung_nhac_van_la_lenh_dieu_khien():
    """`"dừng nhạc"` là `control/deterministic_rule` hôm nay. Cổng Routine đứng trước
    `_run_matchers`, nên nếu nó rộng tay thì lệnh này biến thành một lượt hủy Routine."""
    d = _ROUTER.route("dừng nhạc")
    assert d.disposition == "control"


def test_ten_tho_di_cung_quyet_dinh_chu_khong_nam_tren_router():
    """Router là một thể **dùng chung** cho mọi lượt đồng thời.

    Bản đầu của tôi ghi tên thô lên `self._routine_ten_tho` — chạy xanh hết, và dựng sẵn
    một cuộc đua: hai lượt song song thì lượt sau ghi đè tên của lượt trước, và một tài xế
    chạy nhầm Routine của người khác. Kết quả một lượt phải đi cùng quyết định lượt ấy.
    """
    assert not hasattr(_ROUTER, "_routine_ten_tho")
    assert _ROUTER.route("Chạy routine Đi làm").routine_ten_tho == "đi làm"
    # Lượt khác không được thấy dấu vết của lượt trước.
    assert _ROUTER.route("Bật điều hòa").routine_ten_tho == ""


def test_huy_khong_nem_ten_thi_ten_tho_rong():
    """`"Dừng lại"` không nêu Routine nào — node phải tự tìm lần chạy đang sống của phiên."""
    assert _ROUTER.route("Dừng lại").routine_ten_tho == ""


@pytest.mark.parametrize(
    ("cau", "mong"),
    [
        ("Chạy chuỗi lệnh Thư giãn", "routine/routine_run"),
        ("Bắt đầu chuỗi lệnh Về nhà", "routine/routine_run"),
        ("Thực hiện chuỗi lệnh Đi làm", "routine/routine_run"),
        ("Chuỗi lệnh Về nhà gồm những gì", "routine/routine_preview"),
        ("Hủy chuỗi lệnh", "routine/routine_cancel"),
        ("Dừng chuỗi lệnh", "routine/routine_cancel"),
    ],
)
def test_noi_bang_tu_tieng_viet_vi_stt_khong_nghe_duoc_chu_routine(cau: str, mong: str):
    """`routine` là từ tiếng Anh; STT của xe là Zipformer **tiếng Việt**.

    Đo 30/08 (Piper tổng hợp → `transcribe_raw` — chỉ báo, KHÔNG phải WER giọng người):

        "chạy routine thư giãn"     -> "Chạy uy giãn"          ← nuốt luôn chữ kế bên
        "bắt đầu routine về nhà"    -> "Bắt đầu hu thin về nhà"
        "chạy kịch bản thư giãn"    -> "Chạy kịch bản thư giãn"    ✅
        "chạy chuỗi lệnh thư giãn"  -> "Chạy chuỗi lệnh thư giãn"  ✅

    Chữ `routine` không chỉ sai — nó **phá cả cụm**, nên tên Routine đứng sau mất theo.
    Người dùng thật báo đúng triệu chứng này trước khi tôi đo.

    `chuỗi lệnh` cũng chính là chữ **giao diện đang dùng** ("Chuỗi lệnh riêng"), nên đây
    không phải một từ đồng nghĩa bịa ra cho vừa bộ nhận dạng.
    """
    assert _mo(cau) == mong, cau


def test_khong_nhet_bien_the_sai_cua_stt_vao_tu_vung_router():
    """Ranh giới: router giữ **tiếng Việt đúng**, không giữ tiếng méo.

    `"hu thin"`, `"uy"`, `"xương nại"` là lỗi nhận dạng — sửa chúng là việc của
    `sua_chinh_ta_thoai` (đang tắt sau review #317). Nhét vào router thì một bảng từ méo
    sẽ nuốt nhầm những câu hoàn toàn khác, và không ai còn đọc được luật định tuyến nữa.
    """
    for meo in ["chạy hu thin thư giãn", "chạy uy giãn", "xương nại"]:
        assert _ROUTER.route(meo).disposition != "routine", meo


@pytest.mark.parametrize(
    "cau", ["Ngừng kịch bản", "Ngừng chuỗi lệnh", "Dừng chuỗi lệnh", "Dừng kịch bản lại"]
)
def test_cach_noi_huy_do_duoc_la_nghe_chuan(cau: str):
    """`ngừng` thêm 31/08 sau khi đo vòng TTS→STT trên tám cách nói hủy:

        "dừng chuỗi lệnh"  -> "Dừng chuỗi lệnh"   ✅
        "ngừng kịch bản"   -> "Ngừng kịch bản"    ✅ nghe chuẩn, router CHƯA nhận
        "dừng kịch bản"    -> "Xưng kịch bản"     ❌ `dừng` đầu câu bị méo
        "hủy bỏ kịch bản"  -> "Quy bọc kịch bản"  ❌

    Chọn theo **cái nói được**, không theo cái nghe hay khi đọc trong code.
    """
    assert _ROUTER.route(cau).disposition == "routine", cau


@pytest.mark.parametrize("cau", ["đừng lại", "dùng lại", "ngừng lại một chút", "ngừng", "dừng"])
def test_them_ngung_khong_lam_rong_cua(cau: str):
    """`ngừng` vẫn **đòi từ chỉ loại đứng sau**, nên `"ngừng"` trơ không kích hoạt gì.

    Ca `"đừng lại"` và `"dùng lại"` ở đây là bằng chứng vì sao KHÔNG mở rộng
    `sua_chinh_ta_thoai` để chữa `"Xương nại"`: luật ở đó là "một từ khớp neo chính xác +
    từ kia lệch 1 ký tự", nên thêm cặp `(dừng, lại)` sẽ viết lại **bảy** từ lệch 1 khỏi
    `dừng` — trong đó `"đừng lại"` là **đảo ngược một phủ định** và `"dùng lại"` là cụm
    hằng ngày. Đo 31/08. Đường sửa đúng là từ vựng tiếng Việt nói được, không phải một
    bảng từ méo.
    """
    assert _ROUTER.route(cau).disposition != "routine", cau

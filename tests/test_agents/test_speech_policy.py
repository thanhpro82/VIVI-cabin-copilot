"""Tầng quyết định **nói gì** (S1) — tách khỏi tầng quyết định **hiển thị gì**.

Task 3 của `docs/superpowers/plans/2026-08-13-speak-text-an-toan-cho-nhanh-so-tay.md`.

Lý do tồn tại nằm ở phép đo của ADR-015: để SLM tóm tắt một đoạn sổ tay thì 4/40 câu
gây hiểu lầm, và lớp lỗi chính là **làm rơi điều kiện theo phiên bản** — bảng áp suất
lốp ECO/PLUS, pin SDI/CATL. Ca nặng nhất (RAG-130): bốc một cột của bảng ra trình bày
như giá trị chung, xe pin CATL bơm theo đó là thiếu hơi.

Module này không tóm tắt gì cả. Nó **chọn** một câu có sẵn trong đoạn, theo luật tất
định, nên lớp lỗi trên không dựng lên được chứ không phải được giảm thiểu.
"""

import re

import pytest

from src.agents.nodes.speech_policy import (
    MAX_SPOKEN_CHARS,
    SpeechPlan,
    cau_noi_hoan_chinh,
    chon_cau_de_noi,
    doc_tiep,
)
from src.rag.models import Evidence

SO_CO_DON_VI = re.compile(r"\d+\s*(kPa|KPA|psi|PSI|bar|độ|hướng|mm|km/h)\b", re.IGNORECASE)

#: Nguyên văn (rút gọn) đoạn "Áp suất lốp" của index thật — `is_table=1`,
#: `has_variant_condition=1`. Giữ nguyên hình dạng bảng vì chính nó là cái bẫy: bảng
#: **không có dấu kết câu**, nên tách câu theo `[.!?]` sẽ kéo cả bảng số vào một "câu".
DOAN_AP_SUAT_LOP = (
    "Áp suất lốp Tất cả các áp suất lốp bao gồm cả lốp dự phòng (nếu được trang bị) "
    "nên được kiểm tra khi lốp nguội. Luôn kiểm tra áp suất lốp thường xuyên. "
    "Nhãn Thông tin về lốp và Tải trọng trên xe cho biết thông tin lốp nguyên bản ban "
    "đầu và áp suất lốp nguội chính xác. "
    "Tem áp suất lốp Áp suất lốp khuyến nghị được liệt kê trên nhãn dán trên cột trụ "
    "trung tâm bên cạnh người lái: Loại phương tiện | VF 9 Khác nhau | ECO | PLUS | "
    "Dự phòng Áp suất lốp lạnh | Phía trước | 240 KPA,35 PSI, (SDI) 260 KPA,38 PSI, (CATL)"
)

DOAN_GAT_NUOC = (
    "Tính năng lau nhẹ nhàng sẽ loại bỏ lượng nước dư thừa khỏi kính chắn gió sau khi "
    "hoàn thành gạt rửa. Kiểm tra mức chất lỏng của bồn chứa nước rửa kính thường xuyên. "
    "Đổ đầy bình chứa dung dịch rửa kính cho đến khi đầy."
)


def _ev(text: str, *, bien_the: bool = False, bang: bool = False) -> Evidence:
    return Evidence(
        section="Bảo dưỡng / Vành và bánh xe",
        page=2,
        text=text,
        chunk_id="c1",
        score=0.9,
        is_table=bang,
        has_variant_condition=bien_the,
    )


def test_doan_co_bien_the_khong_bao_gio_doc_so():
    """Bất biến số một. Ca RAG-130 của ADR-015 phải không dựng lên được."""
    ke_hoach = chon_cau_de_noi(_ev(DOAN_AP_SUAT_LOP, bien_the=True, bang=True), "áp suất lốp bao nhiêu")
    assert not SO_CO_DON_VI.search(ke_hoach.spoken), f"đã đọc số: {ke_hoach.spoken!r}"


def test_uu_tien_cau_chi_nguon_nam_san_trong_doan():
    """Đoạn tự nó chứa câu an toàn. Nói câu đó là **trích**, không phải tóm tắt."""
    ke_hoach = chon_cau_de_noi(_ev(DOAN_AP_SUAT_LOP, bien_the=True, bang=True), "áp suất lốp")
    assert "Nhãn Thông tin về lốp" in ke_hoach.spoken
    assert ke_hoach.reason == "pointer"


def test_cau_chi_nguon_keo_theo_bang_so_thi_bi_loai():
    """Cái bẫy chỉ lộ ra khi đọc dữ liệu thật.

    Câu *"Áp suất lốp khuyến nghị được liệt kê trên nhãn dán trên cột trụ trung tâm"*
    cũng là câu chỉ nguồn, nhưng nó **không có dấu chấm** trước bảng nên bộ tách câu
    gộp luôn cả `240 KPA (SDI) 260 KPA (CATL)` vào. Chọn nó là đọc đúng con số mà cả
    module này sinh ra để không đọc.
    """
    ke_hoach = chon_cau_de_noi(_ev(DOAN_AP_SUAT_LOP, bien_the=True, bang=True), "áp suất lốp")
    assert "cột trụ trung tâm" not in ke_hoach.spoken


def test_khong_co_cau_chi_nguon_sach_thi_fail_closed():
    """Không tìm được câu an toàn → nói câu khung, **không** bịa và **không** đọc số."""
    ke_hoach = chon_cau_de_noi(_ev("Bản ECO bơm 240 KPA. Bản PLUS bơm 260 KPA.", bien_the=True), "áp suất")
    assert not SO_CO_DON_VI.search(ke_hoach.spoken)
    assert "phiên bản" in ke_hoach.spoken.lower()
    assert ke_hoach.reason == "variant_fallback"
    assert ke_hoach.remainder_chars > 0


def test_doan_thuong_thi_noi_noi_dung_that():
    """Không có biến thể thì không việc gì phải né — nói thẳng nội dung."""
    ke_hoach = chon_cau_de_noi(_ev(DOAN_GAT_NUOC), "lau nhẹ nhàng là gì")
    assert ke_hoach.spoken.startswith("Tính năng lau nhẹ nhàng")
    assert ke_hoach.reason == "plain"


def test_luon_duoi_tran_doc():
    ke_hoach = chon_cau_de_noi(_ev("Câu rất dài. " * 300), "gì đó")
    assert len(ke_hoach.spoken) <= MAX_SPOKEN_CHARS


def test_con_bao_nhieu_chua_noi_thi_bao_dung_bay_nhieu():
    """`remainder_chars` là đầu vào của lời mời nghe tiếp (Task 4)."""
    ke_hoach = chon_cau_de_noi(_ev(DOAN_GAT_NUOC), "lau nhẹ nhàng")
    assert ke_hoach.remainder_chars == len(DOAN_GAT_NUOC) - len(ke_hoach.spoken)


def test_doan_co_so_nhung_thieu_nhan_van_than_trong():
    """Mặc định `has_variant_condition=False` của `Evidence` **không** fail-closed.

    Một Evidence dựng tay (test cũ, node tiêm) sẽ mang nhãn False dù đoạn có bảng số.
    Nên khi đoạn có số kèm đơn vị mà không có nhãn nào, vẫn không được đọc cả bảng.
    """
    ke_hoach = chon_cau_de_noi(_ev("Bảng | ECO | PLUS Áp suất | 240 KPA | 260 KPA"), "áp suất")
    assert not SO_CO_DON_VI.search(ke_hoach.spoken) or ke_hoach.reason == "plain"


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_doan_rong_thi_khong_no(text):
    assert chon_cau_de_noi(_ev(text), "gì đó").spoken == ""


# --- Task 4 (S3): lời mời nghe tiếp ------------------------------------------


def test_chi_moi_nghe_tiep_khi_con_phan_du():
    """Câu trả lời một dòng thì không có gì để tiếp.

    Mời vô điều kiện sẽ khiến cả lệnh "bật điều hoà" cũng bị hỏi "nghe tiếp không?",
    và một câu hỏi thừa lặp mỗi lượt còn khó chịu hơn im lặng.
    """
    het = SpeechPlan(spoken="Đã đặt 24 độ.", remainder_chars=0, reason="plain")
    con = SpeechPlan(spoken="Câu đầu.", remainder_chars=900, reason="plain")

    assert cau_noi_hoan_chinh(het) == "Đã đặt 24 độ."
    assert "nghe tiếp" in cau_noi_hoan_chinh(con).lower()


def test_nhanh_bien_the_luon_moi_vi_chua_tra_loi_gi():
    """Nhánh fail-closed nói "tôi không tóm tắt được an toàn" — nếu dừng ở đó thì tài
    xế không nhận được gì cả. Lời mời là đường ra duy nhất còn lại."""
    plan = chon_cau_de_noi(_ev("Bản ECO bơm 240 KPA. Bản PLUS bơm 260 KPA.", bien_the=True), "áp suất")
    cau = cau_noi_hoan_chinh(plan)

    assert plan.reason == "variant_fallback"
    assert "nguyên văn" in cau.lower()
    assert not SO_CO_DON_VI.search(cau), "lời mời không được kéo số vào"


def test_cau_hoan_chinh_khong_vuot_tran():
    plan = chon_cau_de_noi(_ev(DOAN_GAT_NUOC), "lau nhẹ nhàng")
    assert len(cau_noi_hoan_chinh(plan)) <= MAX_SPOKEN_CHARS


def test_doan_rong_thi_khong_moi_gi():
    plan = chon_cau_de_noi(_ev(""), "gì đó")
    assert cau_noi_hoan_chinh(plan) == ""


def test_cau_tra_loi_dai_van_giu_duoc_loi_moi():
    """Ca cần mời nhất lại là ca dễ mất lời mời nhất.

    Đo trên server thật (13/08): đoạn "Nước rửa kính" nói 383 ký tự và **không** có
    lời mời — vì phần chọn đã ăn hết ngân sách, `cau_noi_hoan_chinh` đành bỏ mời để
    khỏi vượt trần. Nghĩa là đoạn càng dài, tài xế càng ít có đường nghe tiếp: đúng
    ngược với ý đồ.

    Cách chữa: **giữ chỗ cho lời mời ngay lúc chọn câu** khi đã biết chắc còn phần dư.
    """
    doan = "Câu nội dung dài. " * 60  # dài hơn trần -> chắc chắn còn phần dư
    plan = chon_cau_de_noi(_ev(doan), "hỏi gì đó")
    cau = cau_noi_hoan_chinh(plan)

    assert plan.remainder_chars > 0
    assert "nghe tiếp" in cau.lower(), "đoạn dài mà không mời thì tài xế cụt đường"
    assert len(cau) <= MAX_SPOKEN_CHARS


def test_cau_dau_qua_dai_thi_cat_o_ranh_gioi_tu():
    """Cắt giữa chữ thì TTS đọc ra một âm cụt.

    Gặp thật khi dựng dữ liệu chấm tay (13/08): RAG-101 nói ra
    "...cầu chì Mô-đun cảm biến chống kẹp), **chủ sở hữ** Bạn có muốn nghe tiếp..."
    — `_gop_duoi_tran` cắt thẳng theo ký tự khi ngay cả câu đầu đã dài hơn ngân sách.

    Đáng sửa **trước khi chấm tay**: để nguyên thì người chấm đang chấm một lỗi định
    dạng chứ không chấm thiết kế, và baseline sẽ sai theo hướng bi quan.

    Kiểm thẳng hàm với ngân sách rơi **chắc chắn** vào giữa chữ. Hai bản test trước
    của tôi đi qua `chon_cau_de_noi` và **xanh một cách may rủi**: chỗ cắt tình cờ rơi
    cạnh dấu cách nên chúng không bao giờ chạm tới bug.
    """
    from src.agents.nodes.speech_policy import _gop_duoi_tran

    nguon = "Khởi tạo cửa sổ điện hiện đại"
    spoken = _gop_duoi_tran([nguon], 10)  # rơi vào giữa chữ "cửa"

    assert nguon.startswith(spoken)
    assert spoken == spoken.rstrip()
    assert nguon[len(spoken)] == " ", f"cắt giữa chữ: {spoken!r}"


# --- S2: SLM chon cau, co cong kiem chung (Task 9) --------------------------
#
# ADR-015 bac phuong an de SLM VIET LAI mot doan: 4/40 cau gay hieu lam, va ty le chi
# di tu 5/40 xuong 4/40 qua ba vong chinh cau hinh — san loi cua cach tiep can.
#
# S2 khac o cho dau ra la CHI SO CAU, khong phai chu. Khong co buoc dien dat lai thi
# lop loi "lam roi dieu kien theo phien ban" khong dung len duoc. Ba test duoi khoa
# dung tinh chat do, khong khoa ket qua chon cau.


class _SlmTraVe:
    """Selector gia: tra dung thu duoc dat, de test khoa CONG chu khong khoa model."""

    def __init__(self, ket_qua):
        self._ket_qua = ket_qua
        self.da_goi = 0

    def select(self, question, sentences):
        self.da_goi += 1
        if isinstance(self._ket_qua, Exception):
            raise self._ket_qua
        return self._ket_qua


def test_cau_khong_nguyen_van_bi_vut_va_roi_ve_luat():
    """Chỉ số ngoài khoảng là đầu ra **hợp schema mà vô nghĩa** — grammar ép được kiểu
    nhưng không ép được khoảng, nên cổng này phải nằm ở code chứ không ở grammar."""
    ke_hoach = chon_cau_de_noi(_ev("Câu một. Câu hai."), "hỏi gì", selector=_SlmTraVe([99]))

    assert ke_hoach.reason == "slm_output_rejected"
    assert ke_hoach.spoken  # roi ve luat, khong phai im lang


def test_slm_khong_duoc_cham_vao_doan_co_bien_the():
    """S1 gác **trước** S2, không phải song song.

    Đoạn phụ thuộc phiên bản là đúng chỗ ADR-015 đo được 4/40 câu sai. Cho SLM chọn ở
    đó là mở lại đúng cánh cửa đó — dù nó chỉ chọn chứ không viết, vì câu nó chọn có
    thể là câu mang số của **một** biến thể.
    """
    slm = _SlmTraVe([0])
    ke_hoach = chon_cau_de_noi(
        _ev(DOAN_AP_SUAT_LOP, bien_the=True, bang=True), "áp suất lốp", selector=slm
    )

    assert not SO_CO_DON_VI.search(ke_hoach.spoken)
    assert ke_hoach.reason == "pointer"
    assert slm.da_goi == 0, "SLM khong duoc goi tren doan co bien the"


def test_cau_slm_chon_phai_la_nguyen_van_cua_doan():
    """Bất biến khiến S2 khác phương án B: mỗi ký tự nói ra phải có sẵn trong nguồn."""
    doan = "Câu một nói về A. Câu hai nói về B. Câu ba nói về C."
    ke_hoach = chon_cau_de_noi(_ev(doan), "hỏi về B", selector=_SlmTraVe([1]))

    assert ke_hoach.reason == "slm"
    assert ke_hoach.spoken == "Câu hai nói về B."
    assert ke_hoach.spoken in doan


def test_slm_hong_thi_roi_ve_luat_chu_khong_lam_hong_luot():
    """llama-server tắt là trạng thái **bình thường** (`slm_enabled=False` mặc định),
    không phải sự cố. Một lượt hỏi sổ tay không được chết theo nó."""
    ke_hoach = chon_cau_de_noi(_ev("Câu một. Câu hai."), "hỏi gì", selector=_SlmTraVe(RuntimeError("timeout")))

    assert ke_hoach.reason == "slm_error"
    assert ke_hoach.spoken


def test_khong_co_selector_thi_hanh_vi_y_nguyen_s1():
    """Mặc định phải là đường S1 — cùng lý do `slm_enabled` mặc định `False`."""
    doan = "Câu một nói về A. Câu hai nói về B."
    assert chon_cau_de_noi(_ev(doan), "hỏi gì").reason == "plain"


def test_nhieu_cau_duoc_gop_theo_dung_thu_tu_trong_doan():
    """Trả về [2, 0] thì vẫn phải đọc theo thứ tự sổ tay.

    Đọc ngược thứ tự là một dạng diễn đạt lại: sổ tay xe hay viết điều kiện trước rồi
    mới tới thao tác, đảo lại thì thao tác nghe như vô điều kiện.
    """
    doan = "Chỉ làm khi xe đã dừng. Mở nắp ca-pô. Kiểm tra mức dầu."
    ke_hoach = chon_cau_de_noi(_ev(doan), "kiểm tra dầu", selector=_SlmTraVe([2, 0]))

    assert ke_hoach.spoken == "Chỉ làm khi xe đã dừng. Kiểm tra mức dầu."


@pytest.mark.parametrize("xau", [[], "0", [0.5], [-1], None, ["0"]])
def test_dau_ra_di_dang_deu_bi_vut(xau):
    """Không tin selector là một protocol lỏng: nó có thể là bất cứ cài đặt nào."""
    ke_hoach = chon_cau_de_noi(_ev("Câu một. Câu hai."), "hỏi gì", selector=_SlmTraVe(xau))
    assert ke_hoach.reason == "slm_output_rejected"


# --- Ve dieu kien "tuy trang bi" phai di kem con so ------------------------
#
# 14/08 cho dau hieu "neu duoc trang bi" ra khoi co bien the (no la "xe ban co the
# khong co tinh nang nay", khong phai "gia tri khac nhau"). Doi lai, an toan gio dua
# vao viec ve dieu kien DI KEM trong cau noi — ma S2 duoc chon cau bat ky nen co the
# bo roi no. 9 chunk trong index that thuoc dien nay (nguong AEB, gioi han 50 km/h
# cua lop du phong), va bo 40 case KHONG phu chung, nen khong the khoa bang eval.


DOAN_TUY_TRANG_BI = (
    "Phanh tự động khẩn cấp (nếu được trang bị)\n"
    "Hệ thống giám sát khoảng cách với xe phía trước. "
    "Hệ thống hoạt động trong dải tốc độ từ 10 km/h đến 130 km/h. "
    "Người lái vẫn chịu trách nhiệm điều khiển xe."
)


def test_noi_so_tu_doan_tuy_trang_bi_thi_phai_kem_ve_dieu_kien():
    """Nói "hoạt động từ 10 km/h đến 130 km/h" mà bỏ "nếu được trang bị" là để tài xế
    tin xe mình có một hệ thống nó không có — và tin vào một con số của hệ thống ấy."""

    class ChonCauGiua:
        def select(self, question, sentences):
            return [next(i for i, c in enumerate(sentences) if "130 km/h" in c)]

    ke_hoach = chon_cau_de_noi(_ev(DOAN_TUY_TRANG_BI), "phanh khẩn cấp", selector=ChonCauGiua())
    assert "130 km/h" in ke_hoach.spoken
    assert "nếu được trang bị" in ke_hoach.spoken.lower() or "không có tính năng" in ke_hoach.spoken.lower()


def test_khong_them_ve_dieu_kien_khi_khong_noi_so_nao():
    """Chỉ gắn khi thật sự có số. Gắn vô điều kiện thì mọi lượt đều dài thêm một câu."""

    class ChonCauCuoi:
        def select(self, question, sentences):
            return [len(sentences) - 1]

    ke_hoach = chon_cau_de_noi(_ev(DOAN_TUY_TRANG_BI), "ai chịu trách nhiệm", selector=ChonCauCuoi())
    assert "Người lái vẫn chịu trách nhiệm" in ke_hoach.spoken
    assert "không có tính năng" not in ke_hoach.spoken.lower()


def test_doan_khong_tuy_trang_bi_thi_noi_so_binh_thuong():
    doan = "Giới hạn nhiệt độ. Tránh để xe trên 55 độ hoặc dưới -35 độ trong hơn 24 giờ."
    ke_hoach = chon_cau_de_noi(_ev(doan), "giới hạn nhiệt độ")
    assert "55 độ" in ke_hoach.spoken
    assert "không có tính năng" not in ke_hoach.spoken.lower()


# --- Dau vao benh hoan (review cua Thanh, PR #108) --------------------------


#: Chuoi de lam vo mot ham cat chuoi. Gom ca ky tu vo hinh (`\u00a0` no-break space,
#: `\u200b` zero-width space) vi ASR va HTML sinh ra chung nhieu hon nguoi ta tuong.
_DAU_VAO_XAU = [
    "", " ", "\n", "\t\n  ", ".", "...", "!!!", "?", " . ", ",", ";", ":", ")", "()",
    "—", "  .  .  ", ". . .", "\u00a0", "\u200b", "-", "- ", "|", "| |", "0", "a",
    "\n\n\n", ".\n.\n.",
]


@pytest.mark.parametrize("xau", _DAU_VAO_XAU)
@pytest.mark.parametrize("bien_the", [False, True])
@pytest.mark.parametrize("bang", [False, True])
def test_khong_vo_voi_doan_rong_hoac_toan_dau_cau(xau, bien_the, bang):
    """`cau_list[0]` trong `_gop_duoi_tran` là chỗ Thành chỉ ra rủi ro `IndexError`.

    Nó **không** vỡ, vì `chon_cau_de_noi` chặn `text` rỗng từ đầu và `_cau()` trên một
    chuỗi đã strip mà khác rỗng thì luôn trả ít nhất một phần tử. Nhưng đó là một lập
    luận, và lập luận không sống sót qua lần refactor sau — nên khoá bằng test.

    Đoạn sổ tay đi vào đây từ index, còn `query` đi vào từ ASR: cả hai đều là đường
    ngoài, và đường ngoài thì không được phép làm vỡ một lượt.
    """
    ke_hoach = chon_cau_de_noi(
        {"text": xau, "has_variant_condition": bien_the, "is_table": bang}, "hỏi gì"
    )
    assert isinstance(cau_noi_hoan_chinh(ke_hoach), str)


@pytest.mark.parametrize("xau", _DAU_VAO_XAU)
@pytest.mark.parametrize("da_doc", [[], [0], [5], [999], [-1], [0, 1, 2]])
def test_doc_tiep_khong_vo_voi_nguon_hong_hoac_chi_so_ngoai_khoang(xau, da_doc):
    """`speech_da_doc` sống trong state qua nhiều lượt, nên nó **sẽ** lệch khỏi nguồn:
    đổi index, đổi trần, hay đơn giản một lượt cũ còn treo. Vỡ ở đây là vỡ giữa câu
    trả lời của tài xế."""
    ke_hoach = doc_tiep(xau, da_doc)
    assert isinstance(ke_hoach.spoken, str)
    assert all(isinstance(i, int) for i in ke_hoach.chi_so)


def test_bang_co_so_van_ra_nhanh_chi_nguon_du_khong_con_co_bien_the():
    """Nửa **hành vi** của khẳng định "nới cờ biến thể không mở lại lớp nguy hiểm".

    Nửa kia — chunk mất `has_variant_condition` nhưng giữ `is_table` — nằm ở
    `tests/test_rag/test_chunker.py` (PR #113, đã merge). Tách đôi vì `speech_policy`
    không tồn tại ở PR đó.

    Đây là lưới **thứ hai** và nó đỡ độc lập: kể cả khi cờ biến thể sai hoặc vắng, một
    đoạn vừa là bảng vừa mang số vẫn ra câu chỉ nguồn, không đọc số nào. Đúng ca
    RAG-130 mà ADR-015 đo được 4/40 câu gây hiểu lầm.
    """
    bang = ("Thông số kỹ thuật lốp xe dự phòng (nếu được trang bị) Mô tả | Chi tiết "
            "Áp suất lốp lạnh | 240 KPA. Áp suất khuyến nghị được liệt kê trên nhãn dán trên cột trụ.")
    ke_hoach = chon_cau_de_noi(
        {"text": bang, "has_variant_condition": False, "is_table": True}, "áp suất lốp"
    )

    assert ke_hoach.reason == "pointer"
    assert not SO_CO_DON_VI.search(ke_hoach.spoken), f"đã đọc số: {ke_hoach.spoken!r}"


# --- Chon cau theo DO LIEN QUAN, khong theo vi tri --------------------------


def test_chon_cau_tra_loi_chu_khong_chon_cau_dau_doan():
    """S1 cũ đọc câu **đầu đoạn** — thường là tiêu đề mục hoặc câu dẫn nhập, tức
    đúng chỗ không có câu trả lời.

    Đo trên 40 case: chọn theo vị trí trúng 35,0%, chọn theo độ trùng từ vựng với câu
    hỏi trúng **55,0%**. Không cần LLM — S2 (SLM 0.5B) chỉ được +1 ca, tức nhiễu.
    """
    # Đoạn dài hơn trần 240 ký tự và câu trả lời nằm **sau** trần — đúng hình dạng
    # đoạn sổ tay thật (p50 950 ký tự). Đọc từ đầu thì không bao giờ tới.
    doan = (
        "Chống đọng sương phía sau.\n"
        "Chức năng này làm tan hơi nước và sương bám trên kính phía sau của xe.\n"
        "Trong điều kiện không khí ẩm, kính phía sau có thể bị phủ hơi nước từ bên ngoài.\n"
        "Hệ thống dùng các sợi dẫn nhiệt gắn trong lớp kính để làm nóng bề mặt kính.\n"
        "Thời gian làm tan sương phụ thuộc vào nhiệt độ môi trường bên ngoài xe.\n"
        "Để bật chống đọng sương phía sau, chạm vào biểu tượng trên màn hình thông tin giải trí.\n"
        "Nút sẽ sáng lên để cho biết hệ thống đang hoạt động."
    )
    assert len(doan) > MAX_SPOKEN_CHARS, "fixture phải dài hơn trần, không thì test không phân biệt được"
    ke_hoach = chon_cau_de_noi(_ev(doan), "bật chống đọng sương kính sau bằng cách nào")

    assert "chạm vào biểu tượng" in ke_hoach.spoken.lower()
    assert ke_hoach.reason == "plain"


def test_cau_duoc_chon_van_doc_theo_thu_tu_so_tay():
    """Chọn theo liên quan nhưng **đọc theo thứ tự sổ tay**.

    Sổ tay xe hay viết điều kiện trước rồi mới tới thao tác; đảo lại thì thao tác nghe
    như vô điều kiện — một dạng diễn đạt lại bằng thứ tự thay vì bằng chữ.
    """
    doan = "Chỉ làm khi xe đã dừng hẳn. Câu đệm không liên quan. Nhấn nút mở cốp ở cột lái."
    ke_hoach = chon_cau_de_noi(_ev(doan), "mở cốp khi xe đã dừng")

    i_dieu_kien = ke_hoach.spoken.find("Chỉ làm khi xe đã dừng")
    i_thao_tac = ke_hoach.spoken.find("Nhấn nút mở cốp")
    assert i_dieu_kien >= 0 and i_thao_tac >= 0
    assert i_dieu_kien < i_thao_tac


def test_van_la_nguyen_van_khong_dien_dat_lai():
    doan = "Câu một nói về A. Câu hai nói về bật sưởi ghế. Câu ba nói về C."
    ke_hoach = chon_cau_de_noi(_ev(doan), "bật sưởi ghế")
    for cau in ke_hoach.spoken.split(". "):
        if cau.strip():
            assert cau.strip().rstrip(".") in doan


def test_doan_co_bien_the_van_bi_gac_truoc_khi_xep_hang():
    """Xếp hạng không được chạm vào đoạn phụ thuộc phiên bản — S1 gác trước, y như
    với S2. Ranking chọn câu *liên quan nhất*, mà câu liên quan nhất ở bảng áp suất
    lốp chính là câu mang số của **một** biến thể."""
    ke_hoach = chon_cau_de_noi(
        _ev(DOAN_AP_SUAT_LOP, bien_the=True, bang=True), "áp suất lốp trước bao nhiêu"
    )
    assert not SO_CO_DON_VI.search(ke_hoach.spoken), f"đã đọc số: {ke_hoach.spoken!r}"

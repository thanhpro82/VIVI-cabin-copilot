"""Test cắt chunk — trọng tâm là hai bất biến an toàn."""

from src.rag.ingest.chunker import MAX_CHARS, chunk_document
from src.rag.models import Block, BlockKind, Document

DOCUMENT = Document(
    document_id="doc_42",
    chapter="Đóng Mở và Khoang chứa đồ",
    name="Cửa sổ điện",
    html_path="h.html",
    pdf_path="p.pdf",
)


def _block(kind: BlockKind, text: str, anchor: str | None = None) -> Block:
    return Block(kind=kind, text=text, anchor_id=anchor)


def _filler(marker: str) -> str:
    return f"{marker} " * (MAX_CHARS // 2)


def test_moi_detail_heading_mo_mot_chunk_moi() -> None:
    blocks = [
        _block(BlockKind.HEADING, "Điều khiển cửa sổ", "a1"),
        _block(BlockKind.TEXT, "Nội dung một."),
        _block(BlockKind.HEADING, "Chức năng an toàn", "a2"),
        _block(BlockKind.TEXT, "Nội dung hai."),
    ]
    chunks = chunk_document(DOCUMENT, blocks)
    assert [chunk.heading for chunk in chunks] == ["Điều khiển cửa sổ", "Chức năng an toàn"]
    assert [chunk.anchor_id for chunk in chunks] == ["a1", "a2"]


def test_canh_bao_khong_bao_gio_mo_dau_mot_chunk() -> None:
    """Cảnh báo mất ngữ cảnh còn nguy hiểm hơn là không có cảnh báo."""
    blocks = [
        _block(BlockKind.HEADING, "Cửa sổ", "a1"),
        _block(BlockKind.SUBSECTION, "Phần một"),
        _block(BlockKind.TEXT, _filler("noidung")),
        _block(BlockKind.WARNING, "CẢNH BÁO Không thò tay ra ngoài."),
        _block(BlockKind.SUBSECTION, "Phần hai"),
        _block(BlockKind.TEXT, _filler("khac")),
    ]
    chunks = chunk_document(DOCUMENT, blocks)
    assert len(chunks) > 1
    assert all(not chunk.text.startswith("CẢNH BÁO") for chunk in chunks)


def test_canh_bao_di_cung_chunk_voi_noi_dung_truoc_no() -> None:
    blocks = [
        _block(BlockKind.HEADING, "Cửa sổ", "a1"),
        _block(BlockKind.TEXT, "Đóng cửa sổ bằng công tắc."),
        _block(BlockKind.WARNING, "CẢNH BÁO Kiểm tra vật cản."),
    ]
    chunks = chunk_document(DOCUMENT, blocks)
    assert len(chunks) == 1
    assert chunks[0].has_warning is True
    assert "công tắc" in chunks[0].text and "CẢNH BÁO" in chunks[0].text


def test_bang_va_danh_sach_khong_bi_cat_doi() -> None:
    table = "hàng một | giá trị\n" * 200
    blocks = [
        _block(BlockKind.HEADING, "Thông số", "a1"),
        _block(BlockKind.TEXT, _filler("dan")),
        _block(BlockKind.TABLE, table),
    ]
    chunks = chunk_document(DOCUMENT, blocks)
    holders = [chunk for chunk in chunks if "hàng một | giá trị" in chunk.text]
    assert len(holders) == 1
    assert holders[0].text.count("hàng một | giá trị") == 200


def test_chunk_id_duy_nhat_va_on_dinh_qua_hai_lan_chay() -> None:
    blocks = [
        _block(BlockKind.HEADING, "Cửa sổ", "a1"),
        _block(BlockKind.TEXT, "Nội dung."),
    ]
    first = chunk_document(DOCUMENT, blocks)
    second = chunk_document(DOCUMENT, blocks)
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert first[0].chunk_id == "chunk_42_001"
    assert first[0].checksum == second[0].checksum


def test_manh_qua_ngan_duoc_gop_vao_manh_truoc() -> None:
    blocks = [
        _block(BlockKind.HEADING, "Cửa sổ", "a1"),
        _block(BlockKind.TEXT, _filler("dai")),
        _block(BlockKind.SUBSECTION, "Ghi chú"),
        _block(BlockKind.TEXT, "Ngắn."),
    ]
    chunks = chunk_document(DOCUMENT, blocks)
    assert all(len(chunk.text) > 50 for chunk in chunks)


# --- Task 2 của `2026-08-13-speak-text-an-toan-cho-nhanh-so-tay.md` ------------
#
# Hai nhãn cấu trúc mới, đi theo đúng khuôn `has_warning`/`has_caution`/`has_note`.
# Chúng tồn tại để tầng nói (S1) biết đoạn nào **không được đọc số**: lớp lỗi 4/40 mà
# ADR-015 đo được là tóm tắt làm rơi điều kiện theo phiên bản (bảng áp suất lốp
# ECO/PLUS, pin SDI/CATL).
#
# Bộ dấu hiệu dưới đây được chọn **bằng dữ liệu**, không phải bằng cảm tính: đo trên
# 482 chunk thật ngày 13/08, nó khớp 48 chunk = 10,0%. Hai lần thử trước đều sai —
# regex rộng ("phiên bản", "nếu có") khớp 39,6%, tức cứ 5 câu hỏi thì 2 câu bị từ chối
# đọc số; thêm "tùy chọn" thì lên 15,1% và kiểm tay thấy 36 chunk bị bắt oan vì "tùy
# chọn" trong sổ tay này phần lớn nghĩa là *tuỳ chọn người dùng* (Chỉ Đèn / Chỉ Còi),
# không phải biến thể xe.


def _chunk_don(text: str, *, heading: str = "Mục thử", kinds=None):
    blocks = [_block(BlockKind.HEADING, heading, "a1")]
    for kind in kinds or [BlockKind.TEXT]:
        blocks.append(_block(kind, text))
    return chunk_document(DOCUMENT, blocks)[0]


def test_chunk_chua_khoi_bang_duoc_danh_dau_is_table():
    """`BlockKind.TABLE` đã có sẵn từ tầng parse HTML — chỉ chưa ai mang xuống Chunk."""
    assert _chunk_don("Mô tả | Chi tiết", kinds=[BlockKind.TABLE]).is_table is True
    assert _chunk_don("Chữ thường thôi.").is_table is False


def test_dau_hieu_bien_the_la_gia_tri_khac_theo_phien_ban():
    """Cờ này chỉ bắt **một** lớp: đại lượng có giá trị khác nhau giữa các phiên bản.

    Đó đúng là lớp ADR-015 đo được 4/40 câu gây hiểu lầm — bảng áp suất lốp ECO/PLUS,
    pin SDI/CATL. Nói một con số của một cột ra như giá trị chung là để tài xế bơm sai.
    """
    assert _chunk_don("Áp suất 240 KPA (SDI) hoặc 260 KPA (CATL).").has_variant_condition is True
    assert _chunk_don("Các phiên bản ECO có chỉnh điện 8 hướng.").has_variant_condition is True
    bang = "Loại phương tiện | VF 9 Khác nhau | ECO | PLUS | Dự phòng Áp suất lốp lạnh | 240 KPA"
    assert _chunk_don(bang).has_variant_condition is True


def test_ten_phien_ban_viet_kem_ten_xe_van_tinh():
    """Âm tính giả đã đo được (issue #124): đoạn "Thông số kỹ thuật lốp xe" trang 5.

    Nó có `340 kPa (ECO)` và `350 kPa (PLUS)` — cùng một đại lượng, hai giá trị theo
    phiên bản, tức đúng lớp nguy hiểm. Nhưng sổ tay viết `VF 9 ECO` chứ không viết
    "bản ECO", và ô bảng cũng không có dạng `| ECO`, nên bộ dò cũ trả về False.

    Chưa gây hại thật vì lưới thứ hai (`is_table` + có số) vẫn chặn — đã kiểm. Nhưng
    một cờ an toàn dựa vào lưới sau để cứu là cờ không đáng tin: chỉ cần đoạn kế tiếp
    không phải bảng là hết lưới.
    """
    text = "Áp suất tối đa | VF 9 ECO Trước - 340 kPa (49.3 psi) VF 9 PLUS Trước - 350 kPa (50.7 psi)"
    assert _chunk_don(text).has_variant_condition is True
    assert _chunk_don("Kích thước | VF 9 ECO 275/45 R20 VF 9 PLUS 275/40 R21").has_variant_condition is True
    # `VF9` liền không dấu cách cũng phải bắt — sổ tay viết cả hai kiểu.
    assert _chunk_don("Khả năng chịu tải tối đa VF9 PLUS Trước - 975 kg").has_variant_condition is True


def test_noi_dang_vf9_khong_keo_theo_duong_tinh_gia():
    """Nới cờ là đổi thứ tài xế nghe thấy, nên chốt luôn hai ca sát biên.

    "VF 9" đứng một mình là tên xe, có mặt khắp sổ tay; chỉ khi **kèm tên phiên bản**
    nó mới nói lên rằng giá trị khác nhau. Và `ECO` sau một danh từ khác vẫn là chế độ
    lái, không phải phiên bản.
    """
    assert _chunk_don("VF 9 được trang bị hệ thống phanh tái sinh.").has_variant_condition is False
    assert _chunk_don("Xe VF 9 có ba chế độ lái: ECO, Normal và Sport.").has_variant_condition is False


def test_eco_la_ten_che_do_lai_khong_phai_ten_phien_ban():
    """Dương tính giả đắt nhất đã gặp: RAG-139.

    Đoạn "Chế độ tiêu hao điện năng thấp" khớp `ECO` **bốn lần**, cả bốn đều là
    *chế độ lái* ECO chứ không phải *bản* ECO. Cả đoạn bị từ chối đọc, dù câu trả lời
    ("xe chuyển sang chế độ tiêu thụ điện năng thấp khi pin còn rất thấp") chẳng phụ
    thuộc phiên bản nào.
    """
    text = "Để tiết kiệm năng lượng, hãy chọn chế độ lái xe ECO. Để chọn chế độ lái xe ECO: - Chọn ECO."
    assert _chunk_don(text).has_variant_condition is False


def test_tuy_trang_bi_khong_con_ket_toi_ca_doan():
    """Hai loại điều kiện, **một** loại nguy hiểm.

    "Nếu được trang bị" nghĩa là *xe bạn có thể không có tính năng này* — nói ra không
    nguy hiểm, chỉ cần giữ vế điều kiện, mà trích nguyên văn thì tự có. Còn ECO/PLUS/
    SDI/CATL nghĩa là *giá trị khác nhau* — đó mới là chỗ nói ra là sai.

    Gộp hai loại làm một khiến 4/5 ca bị từ chối oan (RAG-109, 112, 127, 139): một dấu
    hiệu ở tính năng con làm câm cả đoạn 1.354 ký tự mà câu trả lời nằm chỗ khác.
    """
    assert _chunk_don("Lốp dự phòng (nếu được trang bị) đặt trong khoang.").has_variant_condition is False
    ghe = "Điều chỉnh độ nghiêng: kéo/ đẩy phần trước của nút. Điều chỉnh tựa lưng (nếu được trang bị): bốn phần."
    assert _chunk_don(ghe).has_variant_condition is False


def test_bang_van_duoc_danh_dau_du_khong_con_co_bien_the():
    """Nới cờ biến thể **không** mở lại lớp nguy hiểm, vì lưới thứ hai là `is_table`.

    Đây là nửa thuộc tầng chunk: đoạn RAG-130 mất `has_variant_condition` nhưng vẫn
    giữ `is_table`. Nửa còn lại — `speech_policy` thấy `is_table` + có số thì vẫn ra
    nhánh `pointer`, không đọc số nào — nằm ở PR speech S1/S3, vì `speech_policy`
    không tồn tại ở PR này.
    """
    bang = (
        "Thông số kỹ thuật lốp xe dự phòng (nếu được trang bị) Mô tả | Chi tiết "
        "Áp suất lốp lạnh | 240 KPA. Áp suất khuyến nghị được liệt kê trên nhãn dán trên cột trụ."
    )
    chunk = _chunk_don(bang, kinds=[BlockKind.TABLE])
    assert chunk.has_variant_condition is False
    assert chunk.is_table is True


def test_dau_hieu_bien_the_trong_heading_cung_tinh():
    """2/48 chunk mang dấu hiệu **chỉ** ở heading. Đọc mỗi `text` là bỏ sót chúng."""
    chunk = _chunk_don("Nội dung không nhắc gì.", heading="Bảng thông số bản ECO")
    assert chunk.has_variant_condition is True


def test_dieu_kien_van_hanh_khong_phai_bien_the():
    """Chốt chặn quan trọng nhất của bộ dò.

    "Chỉ kích hoạt khi xe đang BẬT" là điều kiện vận hành — nói số ở đó vẫn an toàn.
    Bắt nhầm lớp này là hỏng tính năng: cứ vài câu hỏi lại từ chối trả lời một lần.
    """
    assert _chunk_don("Cần gạt nước sẽ chỉ kích hoạt khi xe đang BẬT.").has_variant_condition is False
    assert _chunk_don("Nhấn nút để mở nắp ca-pô.").has_variant_condition is False


def test_tuy_chon_nguoi_dung_khong_phai_bien_the():
    """36/482 chunk chứa "tùy chọn" mà kiểm tay thấy đều là cài đặt người dùng."""
    text = "Phản hồi qua một trong các tùy chọn có thể cài đặt: Chỉ Đèn, Chỉ Còi, Cả hai."
    assert _chunk_don(text).has_variant_condition is False

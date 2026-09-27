"""Test gán số trang bằng cách đối chiếu với PDF của chính mục đó."""

from pathlib import Path

import pymupdf
import pytest

from src.rag.ingest.page_mapper import (
    assign_pages,
    exact_rate,
    extract_pages,
    page_stats,
    resolved_rate,
)
from src.rag.models import Chunk, PageSource

# Không dấu vì font mặc định của PyMuPDF không vẽ được dấu tiếng Việt khi tạo PDF
# tổng hợp. Việc này không làm giảm giá trị test: `page_mapper` so khớp bằng
# `fold()` vốn đã bỏ dấu, nên đường đi của logic là như nhau.
PAGE_ONE = "Dieu khien cua so dien. Cua so dien cua xe duoc dieu khien bang cong tac tren cua tai xe."
PAGE_TWO = "Khoi tao cua so dien. Keo cong tac len va dong hoan toan cua so trong hai giay."
PAGE_THREE = "Chuc nang an toan. Cong tac khoa cua so ngan hanh khach phia sau dieu khien cua so."


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    document = pymupdf.open()
    for body in (PAGE_ONE, PAGE_TWO, PAGE_THREE):
        page = document.new_page()
        page.insert_text((72, 100), body, fontsize=11)
    path = tmp_path / "section.pdf"
    document.save(path)
    document.close()
    return path


def _chunk(index: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"chunk_1_{index:03d}",
        document_id="doc_1",
        section="Đóng Mở và Khoang chứa đồ / Cửa sổ điện",
        heading="Cửa sổ điện",
        text=text,
    )


def test_extract_pages_danh_so_tu_1(pdf_path: Path) -> None:
    pages = extract_pages(pdf_path)
    assert sorted(pages) == [1, 2, 3]
    assert "Dieu khien" in pages[1]


def test_chi_so_trang_pdf_chinh_la_so_trang_in(pdf_path: Path) -> None:
    """Sổ tay đánh số lại từ 1 cho mỗi mục nên không có độ lệch cần bù."""
    chunks = [_chunk(1, PAGE_ONE), _chunk(2, PAGE_TWO), _chunk(3, PAGE_THREE)]
    resolved = assign_pages(chunks, pdf_path)
    assert [chunk.page for chunk in resolved] == [1, 2, 3]
    assert all(chunk.page_source is PageSource.EXACT for chunk in resolved)
    assert exact_rate(resolved) == 1.0


def test_lech_vai_ky_tu_van_khop_o_bac_fuzzy(pdf_path: Path) -> None:
    """PyMuPDF có thể trả ligature hoặc khoảng trắng khác HTML.

    Trước khi có bậc FUZZY, chỉ cần lệch một ký tự là chunk rơi thẳng xuống
    DERIVED và mượn trang của chunk trước — citation sai mà không có tín hiệu.
    """
    # Rải nhiễu đều khắp chuỗi: mồi lấy ở 4 vị trí nên nhiễu cục bộ vẫn còn mồi
    # khớp chính xác, không kích hoạt được nhánh fuzzy.
    lech = "".join(f"{ch}x" if index % 15 == 14 else ch for index, ch in enumerate(PAGE_THREE))
    resolved = assign_pages([_chunk(1, lech)], pdf_path)
    assert resolved[0].page == 3
    assert resolved[0].page_source is PageSource.FUZZY


def test_khong_khop_gi_ca_thi_ke_thua_trang_cua_chunk_truoc(pdf_path: Path) -> None:
    la = "Quy trinh dang ky ho khau thuong tru va cap the can cuoc cong dan moi."
    resolved = assign_pages([_chunk(1, PAGE_TWO), _chunk(2, la)], pdf_path)
    assert resolved[1].page == resolved[0].page
    assert resolved[1].page_source is PageSource.DERIVED


def test_page_stats_va_resolved_rate_phan_biet_ba_bac(pdf_path: Path) -> None:
    la = "Quy trinh dang ky ho khau thuong tru va cap the can cuoc cong dan moi."
    resolved = assign_pages([_chunk(1, PAGE_ONE), _chunk(2, la)], pdf_path)
    stats = page_stats(resolved)
    assert stats[PageSource.EXACT] == 1
    assert stats[PageSource.DERIVED] == 1
    assert exact_rate(resolved) == 0.5
    assert resolved_rate(resolved) == 0.5


def test_chunk_qua_ngan_khong_duoc_dung_lam_moi(pdf_path: Path) -> None:
    resolved = assign_pages([_chunk(1, "ngắn")], pdf_path)
    assert resolved[0].page_source is PageSource.DERIVED


def test_exact_rate_rong_tra_ve_khong() -> None:
    assert exact_rate([]) == 0.0

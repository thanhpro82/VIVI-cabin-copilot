"""Test phân rã HTML sổ tay thành khối có ngữ nghĩa."""

from pathlib import Path

import pytest

from src.rag.ingest.html_parser import load_documents, parse_html
from src.rag.models import BlockKind

_HTML = """<!doctype html><html><body><div id="vfom-content">
  <p class="Detail-Heading" id="anchor001">Điều khiển cửa sổ điện</p>
  <p class="Detail">Cửa sổ điện điều khiển bằng công tắc.</p>
  <p class="Table"><table><tbody>
    <tr><td><p class="Detail"></p></td><td><p class="Detail">Công tắc tài xế</p></td></tr>
    <tr><td><p class="Detail"></p></td><td><p class="Detail">Công tắc hành khách</p></td></tr>
  </tbody></table></p>
  <ul class="Points"><li>Đẩy xuống để mở.</li><li>Kéo lên để đóng.</li></ul>
  <p class="Note"><span class="Note-Heading">LƯU Ý</span>Cửa sổ hoạt động 15 giây.</p>
  <p class="Warning Warning-First"><span class="WARNING-HEADING">CẢNH BÁO</span>Không thò tay ra ngoài.</p>
  <p class="Sub-Section">Khởi tạo cửa sổ điện</p>
  <p class="Image"><img alt="inline Rectangle"/></p>
</div></body></html>"""


@pytest.fixture
def blocks(tmp_path: Path) -> list:
    path = tmp_path / "sample.html"
    path.write_text(_HTML, encoding="utf-8")
    return parse_html(path)


def test_css_class_duoc_anh_xa_sang_loai_khoi(blocks: list) -> None:
    kinds = [block.kind for block in blocks]
    assert kinds[0] is BlockKind.HEADING
    assert BlockKind.NOTE in kinds
    assert BlockKind.WARNING in kinds
    assert BlockKind.SUBSECTION in kinds


def test_anchor_id_duoc_giu_o_khoi_tieu_de(blocks: list) -> None:
    assert blocks[0].anchor_id == "anchor001"


def test_bang_gom_thanh_mot_khoi_duy_nhat(blocks: list) -> None:
    """HTML5 đẩy <table> ra khỏi <p class="Table">, dễ khiến bảng vỡ thành nhiều khối."""
    tables = [block for block in blocks if block.kind is BlockKind.TABLE]
    assert len(tables) == 1
    assert "Công tắc tài xế" in tables[0].text
    assert "Công tắc hành khách" in tables[0].text


def test_o_trong_bang_khong_sinh_khoi_text_rieng(blocks: list) -> None:
    texts = [block.text for block in blocks if block.kind is BlockKind.TEXT]
    assert "Công tắc tài xế" not in texts


def test_danh_sach_giu_tung_muc_tren_mot_dong(blocks: list) -> None:
    lists = [block for block in blocks if block.kind is BlockKind.LIST]
    assert lists[0].text == "- Đẩy xuống để mở.\n- Kéo lên để đóng."


def test_anh_bi_bo_qua(blocks: list) -> None:
    assert all("Rectangle" not in block.text for block in blocks)


def test_thieu_vfom_content_thi_bao_loi(tmp_path: Path) -> None:
    path = tmp_path / "empty.html"
    path.write_text("<html><body><p>khong co container</p></body></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="vfom-content"):
        parse_html(path)


def test_load_documents_doc_manifest(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        '[{"id":1,"chapter":"Lái xe","name":"Vô lăng","html":"h.html","pdf":"p.pdf","anchors":[]}]',
        encoding="utf-8",
    )
    documents = load_documents(tmp_path)
    assert documents[0].document_id == "doc_1"
    assert documents[0].section == "Lái xe / Vô lăng"

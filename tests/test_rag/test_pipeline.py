"""Test ingest đầu-cuối trên một sổ tay tổng hợp thu nhỏ."""

import json
from pathlib import Path

import pymupdf
import pytest

from src.rag.embed import StubEmbedder
from src.rag.index import VectorIndex
from src.rag.ingest.html_parser import load_documents
from src.rag.ingest.pipeline import (
    CHUNKER_VERSION,
    MANIFEST_FILE,
    MIN_SECTION_RATE,
    PAGE_MAP_FILE,
    detect_edition,
    ingest,
)
from src.rag.retrieve import load_retriever

# Không dấu: font mặc định của PyMuPDF không vẽ được dấu tiếng Việt.
BODY_ONE = "Dieu khien cua so dien bang cong tac tren cua tai xe va cua hanh khach."
BODY_TWO = "Chuc nang an toan. Cong tac khoa ngan hanh khach phia sau dung cua so."

_HTML = f"""<!doctype html><html><body><div id="vfom-content">
  <p class="Detail-Heading" id="a1">Dieu khien cua so dien</p>
  <p class="Detail">{BODY_ONE}</p>
  <p class="Detail"><span>Phiên bản hướng dẫn sử dụng:</span> VF9_TEST_1.0</p>
  <p class="Detail-Heading" id="a2">Chuc nang an toan</p>
  <p class="Detail">{BODY_TWO}</p>
</div></body></html>"""


@pytest.fixture
def manual_dir(tmp_path: Path) -> Path:
    root = tmp_path / "manual"
    (root / "html" / "03_Dong Mo").mkdir(parents=True)
    (root / "pdf" / "03_Dong Mo").mkdir(parents=True)

    html_rel = "html/03_Dong Mo/06_Cua so dien.html"
    pdf_rel = "pdf/03_Dong Mo/06_Cua so dien.pdf"
    (root / html_rel).write_text(_HTML, encoding="utf-8")

    document = pymupdf.open()
    for body in (BODY_ONE, BODY_TWO):
        document.new_page().insert_text((72, 100), body, fontsize=11)
    document.save(root / pdf_rel)
    document.close()

    (root / "manifest.json").write_text(
        json.dumps(
            [{"id": 7, "chapter": "Dong Mo", "name": "Cua so dien", "html": html_rel, "pdf": pdf_rel, "anchors": []}]
        ),
        encoding="utf-8",
    )
    return root


def test_ingest_sinh_du_artifact_va_dat_cong_so_trang(manual_dir: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "index"
    report = ingest(manual_dir, out_dir, StubEmbedder())

    assert report.documents == 1
    assert report.chunks == 2
    assert report.page_exact_rate == 1.0
    assert report.page_gate_passed is True
    assert report.edition == "VF9_TEST_1.0"
    assert (out_dir / "chunks.db").exists()
    assert (out_dir / MANIFEST_FILE).exists()
    assert (out_dir / PAGE_MAP_FILE).exists()


def test_manifest_ghi_du_bon_version_key(manual_dir: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "index"
    ingest(manual_dir, out_dir, StubEmbedder())
    manifest = json.loads((out_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert set(manifest) >= {
        "manual_manifest_version",
        "chunker_version",
        "embedding_version",
        "index_checksum",
    }
    assert manifest["chunker_version"] == CHUNKER_VERSION
    assert manifest["index_checksum"].startswith("sha256:")


def test_page_map_du_de_khoi_phuc_so_trang_khong_can_pdf(manual_dir: Path, tmp_path: Path) -> None:
    """Có page_map.json thì repo không cần chứa 115 MB PDF vẫn tái lập được."""
    out_dir = tmp_path / "index"
    ingest(manual_dir, out_dir, StubEmbedder())
    page_map = json.loads((out_dir / PAGE_MAP_FILE).read_text(encoding="utf-8"))
    assert sorted(entry["page"] for entry in page_map.values()) == [1, 2]
    assert all(entry["source"] == "exact" for entry in page_map.values())


def test_artifact_nap_lai_duoc_va_truy_hoi_duoc(manual_dir: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "index"
    ingest(manual_dir, out_dir, StubEmbedder())
    retriever = load_retriever(out_dir)
    evidence = retriever.retrieve("cong tac khoa hanh khach", StubEmbedder())
    assert evidence
    assert evidence[0].section == "Dong Mo / Cua so dien"
    assert VectorIndex.load(out_dir).vector_count >= 2


def test_cong_theo_muc_chan_duoc_mot_muc_hong_nap_sau_cac_muc_tot(manual_dir: Path, tmp_path: Path) -> None:
    """Cổng toàn cục một mình không đủ.

    Thêm một mục thứ hai có PDF hoàn toàn lệch nội dung. Toàn bộ chunk của nó là
    DERIVED, nhưng nếu chỉ chấm trung bình toàn cục thì mục tốt sẽ kéo điểm lên
    và mục hỏng lọt qua.
    """
    la = "Quy trinh dang ky ho khau thuong tru va cap the can cuoc cong dan moi tai phuong."
    html_rel = "html/03_Dong Mo/07_Muc hong.html"
    pdf_rel = "pdf/03_Dong Mo/07_Muc hong.pdf"
    (manual_dir / html_rel).write_text(
        _HTML.replace("Dieu khien cua so dien", "Muc hong").replace(BODY_ONE, BODY_ONE + " " + BODY_TWO),
        encoding="utf-8",
    )
    broken = pymupdf.open()
    broken.new_page().insert_text((72, 100), la, fontsize=11)
    broken.save(manual_dir / pdf_rel)
    broken.close()

    entries = json.loads((manual_dir / "manifest.json").read_text(encoding="utf-8"))
    entries.append(
        {"id": 8, "chapter": "Dong Mo", "name": "Muc hong", "html": html_rel, "pdf": pdf_rel, "anchors": []}
    )
    (manual_dir / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")

    report = ingest(manual_dir, tmp_path / "index", StubEmbedder())
    assert report.worst_section_name == "Dong Mo / Muc hong"
    assert report.worst_section_rate < MIN_SECTION_RATE
    assert report.page_derived > 0
    assert report.page_gate_passed is False


def test_detect_edition_tra_unknown_khi_khong_tim_thay(manual_dir: Path) -> None:
    html_path = manual_dir / "html" / "03_Dong Mo" / "06_Cua so dien.html"
    html_path.write_text(_HTML.replace("Phiên bản hướng dẫn sử dụng:", "Ghi chu:"), encoding="utf-8")
    assert detect_edition(manual_dir, load_documents(manual_dir)) == "unknown"

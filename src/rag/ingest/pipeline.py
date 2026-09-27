"""Điều phối ingest: HTML → chunk → số trang → SQLite → FAISS → manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel

from src.rag import store
from src.rag.embed import MODEL_NAME, Embedder
from src.rag.index import VectorIndex
from src.rag.ingest.chunker import chunk_document
from src.rag.ingest.html_parser import load_documents, parse_html
from src.rag.ingest.page_mapper import assign_pages, exact_rate, page_stats, resolved_rate
from src.rag.models import Chunk, Document, ManualMeta, PageSource

#: Bump khi luật cắt chunk thay đổi — index cũ không còn so sánh được với index mới.
CHUNKER_VERSION = "chunker-1.0"

#: Ngưỡng toàn cục cho tỷ lệ chunk xác định được trang thật. Dưới ngưỡng nghĩa là
#: HTML và PDF có thể lệch phiên bản, phải điều tra chứ không được ingest tiếp.
MIN_PAGE_EXACT_RATE = 0.95

#: Ngưỡng cho **từng mục**. Cổng toàn cục một mình là không đủ: một mục hỏng nặng
#: vẫn lọt vì bị 57 mục tốt kéo trung bình lên. Người lái tra đúng mục hỏng đó thì
#: nhận citation sai, còn báo cáo vẫn xanh.
MIN_SECTION_RATE = 0.80

#: Dò trên text đã parse chứ không trên HTML thô: trong nguồn, nhãn và giá trị bị
#: `</span>` chen vào giữa nên mọi regex chạy thẳng trên HTML đều trượt.
_EDITION_RE = re.compile(r"Phiên bản hướng dẫn sử dụng:\s*(?P<edition>.+)")

#: Chuỗi phiên bản nằm ở chương giới thiệu; không cần quét cả 58 mục.
_EDITION_SCAN_LIMIT = 3

DB_FILE = "chunks.db"
MANIFEST_FILE = "manifest.json"
PAGE_MAP_FILE = "page_map.json"

_LICENSE_NOTE = (
    "Bản quyền thuộc Công ty Cổ phần Sản xuất và Kinh doanh VinFast. "
    "Nội dung không được sao chép, sửa đổi hoặc sử dụng lại nếu không có văn bản cho phép. "
    "Chỉ dùng nội bộ cho đồ án AI20K P-192."
)


class IngestReport(BaseModel):
    """Kết quả một lượt ingest, dùng cho CLI và cho manifest."""

    documents: int
    chunks: int
    vectors: int
    page_exact_rate: float
    page_resolved_rate: float
    page_fuzzy: int
    page_derived: int
    worst_section_name: str
    worst_section_rate: float
    index_checksum: str
    edition: str

    @property
    def page_gate_passed(self) -> bool:
        """Cổng hai tầng: toàn cục và từng mục đều phải đạt."""
        return (
            self.page_resolved_rate >= MIN_PAGE_EXACT_RATE
            and self.worst_section_rate >= MIN_SECTION_RATE
        )


def detect_edition(manual_dir: Path, documents: list[Document]) -> str:
    """Đọc chuỗi phiên bản sổ tay từ chương giới thiệu."""
    for document in documents[:_EDITION_SCAN_LIMIT]:
        for block in parse_html(manual_dir / document.html_path):
            match = _EDITION_RE.search(block.text)
            if match:
                return match.group("edition").strip()
    return "unknown"


def build_chunks(manual_dir: Path, documents: list[Document]) -> dict[str, list[Chunk]]:
    """Phân rã, cắt chunk và gán số trang, **giữ nhóm theo mục**.

    Giữ nhóm là điều kiện để chấm cổng chất lượng theo từng mục; gộp phẳng ngay
    ở đây sẽ mất khả năng phát hiện một mục hỏng nấp sau phần còn lại.
    """
    grouped: dict[str, list[Chunk]] = {}
    for document in documents:
        blocks = parse_html(manual_dir / document.html_path)
        chunks = assign_pages(chunk_document(document, blocks), manual_dir / document.pdf_path)
        if chunks:
            grouped[document.section] = chunks
    return grouped


def worst_section(grouped: dict[str, list[Chunk]]) -> tuple[str, float]:
    """Mục có tỷ lệ xác định trang thấp nhất."""
    if not grouped:
        return "", 0.0
    return min(((name, resolved_rate(chunks)) for name, chunks in grouped.items()), key=lambda item: item[1])


def _manual_meta(manual_dir: Path, edition: str) -> ManualMeta:
    return ManualMeta(
        title="Hướng dẫn sử dụng VinFast VF 9",
        vehicle_profile="vf9-2026-vi",
        edition=edition,
        license_note=_LICENSE_NOTE,
        source=str(manual_dir.as_posix()),
    )


def _write_manifest(out_dir: Path, report: IngestReport, manual_dir: Path) -> None:
    """Ghi 4 version key mà data_model.md yêu cầu để tái lập eval."""
    manifest_bytes = (manual_dir / "manifest.json").read_bytes()
    payload = {
        "manual_manifest_version": hashlib.sha256(manifest_bytes).hexdigest()[:16],
        "chunker_version": CHUNKER_VERSION,
        "embedding_version": f"{MODEL_NAME}@384",
        "index_checksum": report.index_checksum,
        "edition": report.edition,
        "documents": report.documents,
        "chunks": report.chunks,
        "vectors": report.vectors,
        "page_exact_rate": round(report.page_exact_rate, 4),
        "page_resolved_rate": round(report.page_resolved_rate, 4),
        "page_fuzzy": report.page_fuzzy,
        "page_derived": report.page_derived,
        "worst_section_name": report.worst_section_name,
        "worst_section_rate": round(report.worst_section_rate, 4),
    }
    (out_dir / MANIFEST_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_page_map(out_dir: Path, chunks: list[Chunk]) -> None:
    """Bảng chunk_id → section/page: có nó thì rebuild index không cần tới PDF."""
    payload = {
        chunk.chunk_id: {"section": chunk.section, "page": chunk.page, "source": chunk.page_source.value}
        for chunk in chunks
    }
    (out_dir / PAGE_MAP_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest(manual_dir: Path, out_dir: Path, embedder: Embedder) -> IngestReport:
    """Chạy toàn bộ ingest và ghi artifact vào `out_dir`."""
    documents = load_documents(manual_dir)
    grouped = build_chunks(manual_dir, documents)
    chunks = [chunk for section_chunks in grouped.values() for chunk in section_chunks]
    edition = detect_edition(manual_dir, documents)

    out_dir.mkdir(parents=True, exist_ok=True)
    connection = store.connect(out_dir / DB_FILE)
    try:
        store.reset(connection)
        store.save_documents(connection, documents, _manual_meta(manual_dir, edition))
        store.save_chunks(connection, chunks)
    finally:
        connection.close()

    index = VectorIndex.build(chunks, embedder)
    checksum = index.save(out_dir)

    stats = page_stats(chunks)
    worst_name, worst_rate = worst_section(grouped)
    report = IngestReport(
        documents=len(documents),
        chunks=len(chunks),
        vectors=index.vector_count,
        page_exact_rate=exact_rate(chunks),
        page_resolved_rate=resolved_rate(chunks),
        page_fuzzy=stats[PageSource.FUZZY],
        page_derived=stats[PageSource.DERIVED],
        worst_section_name=worst_name,
        worst_section_rate=worst_rate,
        index_checksum=checksum,
        edition=edition,
    )
    _write_manifest(out_dir, report, manual_dir)
    _write_page_map(out_dir, chunks)
    return report

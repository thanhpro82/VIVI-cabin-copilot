"""Test chunk store SQLite."""

from pathlib import Path

from src.rag import store
from src.rag.models import Chunk, Document, ManualMeta, PageSource

DOCUMENT = Document(
    document_id="doc_1",
    chapter="Lái xe",
    name="Vô lăng",
    html_path="h.html",
    pdf_path="p.pdf",
)
META = ManualMeta(
    title="Hướng dẫn sử dụng VinFast VF 9",
    vehicle_profile="vf9-2026-vi",
    edition="VF9_23-25_VN_VI_2.4 [New UI]",
    license_note="Bản quyền VinFast",
    source="data/manuals/vf9_2026_vi",
)
CHUNK = Chunk(
    chunk_id="chunk_1_001",
    document_id="doc_1",
    section="Lái xe / Vô lăng",
    heading="Sưởi vô lăng",
    anchor_id="anchor001",
    text="Nhấn nút để bật sưởi vô lăng.",
    has_warning=True,
    page=3,
    page_source=PageSource.EXACT,
    checksum="abc123",
)


def _connect(tmp_path: Path):
    connection = store.connect(tmp_path / "chunks.db")
    store.save_documents(connection, [DOCUMENT], META)
    store.save_chunks(connection, [CHUNK])
    return connection


def test_luu_va_doc_lai_giu_nguyen_moi_truong(tmp_path: Path) -> None:
    connection = _connect(tmp_path)
    try:
        loaded = store.load_chunks(connection)[0]
    finally:
        connection.close()
    assert loaded == CHUNK
    assert loaded.page_source is PageSource.EXACT
    assert loaded.anchor_id == "anchor001"


def test_document_title_dung_cho_citation(tmp_path: Path) -> None:
    connection = _connect(tmp_path)
    try:
        assert store.document_title(connection) == "Hướng dẫn sử dụng VinFast VF 9"
    finally:
        connection.close()


def test_ingest_lai_khong_sinh_ban_ghi_trung(tmp_path: Path) -> None:
    connection = _connect(tmp_path)
    try:
        store.reset(connection)
        store.save_documents(connection, [DOCUMENT], META)
        store.save_chunks(connection, [CHUNK])
        assert len(store.load_chunks(connection)) == 1
    finally:
        connection.close()


def test_store_rong_tra_ve_tieu_de_rong(tmp_path: Path) -> None:
    connection = store.connect(tmp_path / "empty.db")
    try:
        assert store.document_title(connection) == ""
        assert store.load_chunks(connection) == []
    finally:
        connection.close()


def test_mo_db_cu_thi_tu_them_cot_moi(tmp_path):
    """DB dựng trước khi có `is_table`/`has_variant_condition` phải mở được.

    `CREATE TABLE IF NOT EXISTS` không thêm cột vào bảng đã có, và `reset()` chỉ xoá
    dòng — nên nếu không thêm cột thì ai kéo code mới về sẽ gặp
    `sqlite3.OperationalError: table document_chunks has no column named is_table`
    ngay lần ingest đầu tiên. Gặp thật ngày 13/08.
    """
    import sqlite3

    db = tmp_path / "cu.sqlite3"
    cu = sqlite3.connect(db)
    cu.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, title TEXT, chapter TEXT, name TEXT,"
        " section_path TEXT, vehicle_profile TEXT, edition TEXT, license_note TEXT, source TEXT);"
        "CREATE TABLE document_chunks (id TEXT PRIMARY KEY, document_id TEXT, section_path TEXT,"
        " heading TEXT, anchor_id TEXT, page INTEGER, page_source TEXT, text TEXT, checksum TEXT,"
        " has_warning INTEGER DEFAULT 0, has_caution INTEGER DEFAULT 0, has_note INTEGER DEFAULT 0);"
    )
    cu.commit()
    cu.close()

    connection = store.connect(db)

    cot = {row["name"] for row in connection.execute("PRAGMA table_info(document_chunks)")}
    assert {"is_table", "has_variant_condition"} <= cot

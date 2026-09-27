"""Chunk store SQLite — nguồn sự thật cho text và metadata trích dẫn.

Theo ADR-003, metadata **không** nằm trong vector index: FAISS chỉ giữ vector,
còn `section`/`page`/`document` nằm ở đây. Nhờ vậy lọc theo hồ sơ xe hay phiên
bản sổ tay chạy ở tầng ứng dụng và index có thể dựng lại mà không mất metadata.

`anchor_id` được lưu để Engineer đối chiếu ngược citation với sổ tay số, nhưng
**không** xuất hiện trong Citation công khai: schema v1.0 từ chối field lạ.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.rag.models import Chunk, Document, ManualMeta, PageSource

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    chapter         TEXT NOT NULL,
    name            TEXT NOT NULL,
    section_path    TEXT NOT NULL,
    vehicle_profile TEXT NOT NULL,
    edition         TEXT NOT NULL,
    license_note    TEXT NOT NULL,
    source          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id           TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES documents(id),
    section_path TEXT NOT NULL,
    heading      TEXT NOT NULL,
    anchor_id    TEXT,
    page         INTEGER NOT NULL,
    page_source  TEXT NOT NULL,
    text         TEXT NOT NULL,
    checksum     TEXT NOT NULL,
    has_warning  INTEGER NOT NULL DEFAULT 0,
    has_caution  INTEGER NOT NULL DEFAULT 0,
    has_note     INTEGER NOT NULL DEFAULT 0,
    -- Hai nhãn cho tầng nói (S1). `DEFAULT 0` để DB cũ đọc được mà không cần
    -- migration; ingest lại sẽ điền đúng.
    is_table     INTEGER NOT NULL DEFAULT 0,
    has_variant_condition INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON document_chunks(section_path);
"""


#: Cột thêm sau khi schema đầu tiên đã ra đời. `CREATE TABLE IF NOT EXISTS` **không**
#: thêm cột vào bảng đã có, và `reset()` chỉ xoá dòng chứ không dựng lại bảng — nên
#: một DB cũ sẽ nổ `no column named ...` ngay khi ingest lại. Gặp thật khi thêm
#: `is_table`/`has_variant_condition` (Task 2, 13/08).
#:
#: Đây **không phải** công cụ migration: `chunks.db` là artifact dựng lại được bằng
#: `python -m src.rag.cli ingest`. Nó chỉ để đồng đội không phải xoá file bằng tay khi
#: kéo code mới về. Khi nào cần đổi *kiểu* cột hay dữ liệu cũ thì mới là lúc bàn tới
#: Alembic.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("document_chunks", "is_table", "INTEGER NOT NULL DEFAULT 0"),
    ("document_chunks", "has_variant_condition", "INTEGER NOT NULL DEFAULT 0"),
)


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    for table, column, ddl in _ADDED_COLUMNS:
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    connection.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    """Mở kết nối và đảm bảo schema tồn tại."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    _add_missing_columns(connection)
    return connection


def reset(connection: sqlite3.Connection) -> None:
    """Xoá dữ liệu cũ để ingest lại từ đầu mà không sinh bản ghi trùng."""
    connection.execute("DELETE FROM document_chunks")
    connection.execute("DELETE FROM documents")
    connection.commit()


def save_documents(connection: sqlite3.Connection, documents: list[Document], meta: ManualMeta) -> None:
    """Ghi 58 mục sổ tay kèm siêu dữ liệu bản quyền và phiên bản."""
    connection.executemany(
        "INSERT OR REPLACE INTO documents"
        " (id, title, chapter, name, section_path, vehicle_profile, edition, license_note, source)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                document.document_id,
                meta.title,
                document.chapter,
                document.name,
                document.section,
                meta.vehicle_profile,
                meta.edition,
                meta.license_note,
                meta.source,
            )
            for document in documents
        ],
    )
    connection.commit()


def save_chunks(connection: sqlite3.Connection, chunks: list[Chunk]) -> None:
    """Ghi toàn bộ chunk đã gán số trang."""
    connection.executemany(
        "INSERT OR REPLACE INTO document_chunks"
        " (id, document_id, section_path, heading, anchor_id, page, page_source,"
        "  text, checksum, has_warning, has_caution, has_note, is_table, has_variant_condition)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                chunk.chunk_id,
                chunk.document_id,
                chunk.section,
                chunk.heading,
                chunk.anchor_id,
                chunk.page,
                chunk.page_source.value,
                chunk.text,
                chunk.checksum,
                int(chunk.has_warning),
                int(chunk.has_caution),
                int(chunk.has_note),
                int(chunk.is_table),
                int(chunk.has_variant_condition),
            )
            for chunk in chunks
        ],
    )
    connection.commit()


def _to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        chunk_id=row["id"],
        document_id=row["document_id"],
        section=row["section_path"],
        heading=row["heading"],
        anchor_id=row["anchor_id"],
        text=row["text"],
        has_warning=bool(row["has_warning"]),
        has_caution=bool(row["has_caution"]),
        has_note=bool(row["has_note"]),
        is_table=bool(row["is_table"]),
        has_variant_condition=bool(row["has_variant_condition"]),
        page=row["page"],
        page_source=PageSource(row["page_source"]),
        checksum=row["checksum"],
    )


def load_chunks(connection: sqlite3.Connection) -> list[Chunk]:
    """Đọc mọi chunk theo thứ tự ổn định."""
    rows = connection.execute("SELECT * FROM document_chunks ORDER BY id").fetchall()
    return [_to_chunk(row) for row in rows]


def document_title(connection: sqlite3.Connection) -> str:
    """Tiêu đề sổ tay dùng cho trường `document_title` của Citation."""
    row = connection.execute("SELECT title FROM documents LIMIT 1").fetchone()
    return row["title"] if row else ""

"""Kiểu dữ liệu dùng chung cho pipeline RAG sổ tay xe.

`Evidence` giữ đúng shape của `experiments/offline_poc/src/offline_poc/rag.py:44`
để test và citation validator hiện có tái sử dụng được.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class BlockKind(StrEnum):
    """Loại khối nội dung, suy ra từ CSS class trong HTML sổ tay."""

    HEADING = "heading"
    SUBSECTION = "subsection"
    SUBSUB = "subsub"
    TEXT = "text"
    LIST = "list"
    TABLE = "table"
    WARNING = "warning"
    CAUTION = "caution"
    NOTE = "note"


#: Các khối an toàn không bao giờ được đứng đầu một chunk — mất ngữ cảnh cha
#: còn nguy hiểm hơn là không có cảnh báo.
SAFETY_KINDS: frozenset[BlockKind] = frozenset(
    {BlockKind.WARNING, BlockKind.CAUTION, BlockKind.NOTE}
)

#: Điểm cắt ưu tiên khi chunk quá dài — giữ được ranh giới ngữ nghĩa.
SPLIT_KINDS: frozenset[BlockKind] = frozenset({BlockKind.SUBSECTION, BlockKind.SUBSUB})

#: Điểm cắt dự phòng khi mục không có tiêu đề con. Mọi loại khối trừ khối an toàn:
#: cắt trước một đoạn văn, danh sách hay bảng đều không làm mất ngữ cảnh, còn cắt
#: trước một cảnh báo thì có.
FALLBACK_SPLIT_KINDS: frozenset[BlockKind] = frozenset(BlockKind) - SAFETY_KINDS - {BlockKind.HEADING}


class PageSource(StrEnum):
    """Cách xác định số trang của một chunk, xếp theo độ tin cậy giảm dần."""

    #: Khớp chuỗi con chính xác giữa chunk và text trang PDF.
    EXACT = "exact"
    #: Khớp mờ trên ngưỡng tương đồng — dùng khi PDF và HTML lệch vài ký tự.
    FUZZY = "fuzzy"
    #: Không khớp được, kế thừa trang của chunk liền trước trong cùng mục.
    DERIVED = "derived"
    #: Chưa qua bước gán trang.
    UNKNOWN = "unknown"


class Block(BaseModel):
    """Một khối nội dung liền mạch trích từ HTML."""

    kind: BlockKind
    text: str
    anchor_id: str | None = None


class Document(BaseModel):
    """Một mục trong sổ tay, tương ứng một entry của manifest.json."""

    document_id: str
    chapter: str
    name: str
    html_path: str
    pdf_path: str

    @property
    def section(self) -> str:
        """Định danh mục dùng trong Citation, ví dụ 'Lái xe / Vô lăng'."""
        return f"{self.chapter} / {self.name}"


class ManualMeta(BaseModel):
    """Siêu dữ liệu cấp sổ tay, tương ứng bảng `documents` của data_model.md."""

    title: str
    vehicle_profile: str
    edition: str
    license_note: str
    source: str


class Chunk(BaseModel):
    """Đơn vị được embed và trích dẫn."""

    chunk_id: str
    document_id: str
    section: str
    heading: str
    anchor_id: str | None = None
    text: str
    has_warning: bool = False
    has_caution: bool = False
    has_note: bool = False
    #: Đoạn chứa **bảng**. `BlockKind.TABLE` đã có từ tầng parse HTML; nhãn này chỉ
    #: mang nó xuống Chunk để tầng nói dùng được.
    is_table: bool = False
    #: Đoạn có điều kiện **theo phiên bản xe** — không phải điều kiện vận hành.
    #:
    #: Tầng nói (S1) dùng nhãn này để quyết định **không đọc số**. Lý do: ADR-015 đo
    #: được 4/40 câu gây hiểu lầm khi tóm tắt, và lớp lỗi chính là làm rơi điều kiện
    #: biến thể — bảng áp suất lốp ECO/PLUS, pin SDI/CATL. Nói "260 KPA" cho một chiếc
    #: xe pin CATL vì bốc nhầm cột SDI là để tài xế bơm lốp thiếu hơi.
    has_variant_condition: bool = False
    page: int | None = None
    page_source: PageSource = PageSource.UNKNOWN
    checksum: str = ""


class Evidence(BaseModel):
    """Kết quả truy hồi, shape khớp offline_poc để dùng chung validator."""

    section: str
    page: int
    text: str
    chunk_id: str
    score: float = 0.0
    #: Hai nhãn cấu trúc mang theo từ Chunk, để tầng nói quyết định được mà không phải
    #: mở lại chunk store. Mặc định `False` giữ mọi call site cũ chạy nguyên — nhưng
    #: mặc định đó **không** fail-closed, nên `speech_policy` phải tự coi thiếu nhãn là
    #: trường hợp cần thận trọng khi đoạn có số.
    is_table: bool = False
    has_variant_condition: bool = False


class Citation(BaseModel):
    """Citation công khai — đúng 8 field của data_model.md, cấm field lạ."""

    model_config = {"extra": "forbid"}

    citation_id: str
    turn_id: str
    document_title: str
    section: str
    page: int
    chunk_id: str
    excerpt: str
    retrieval_score: float = Field(ge=0.0, le=1.0)

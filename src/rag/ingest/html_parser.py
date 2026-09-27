"""Đọc manifest.json và phân rã HTML sổ tay thành các khối có ngữ nghĩa.

HTML của sổ tay VF9 dùng CSS class để mã hoá cấu trúc (`Detail-Heading`,
`Sub-Section`, `Warning`, `Caution`, `Note`, ...) nên không cần suy đoán bằng
cỡ chữ như khi trích xuất PDF.

Ảnh bị bỏ hoàn toàn: hầu hết `alt` là chuỗi vô nghĩa (`"inline Rectangle"`)
hoặc mô tả máy sinh, còn nhãn thật của hình luôn nằm ở ô văn bản kế bên trong
bảng nên không mất thông tin.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from src.rag.models import Block, BlockKind, Document
from src.rag.textnorm import normalize_text

_CLASS_KIND: dict[str, BlockKind] = {
    "Detail-Heading": BlockKind.HEADING,
    "Sub-Section": BlockKind.SUBSECTION,
    "Sub-Sub-Heading": BlockKind.SUBSUB,
    "Detail": BlockKind.TEXT,
    "Table": BlockKind.TABLE,
    "Warning": BlockKind.WARNING,
    "Caution": BlockKind.CAUTION,
    "Note": BlockKind.NOTE,
    "Points": BlockKind.LIST,
    "List": BlockKind.LIST,
}

_BLOCK_TAGS = ("p", "ul", "ol", "table")


def load_documents(manual_dir: Path) -> list[Document]:
    """Đọc manifest.json thành danh sách Document theo đúng thứ tự sổ tay."""
    entries = json.loads((manual_dir / "manifest.json").read_text(encoding="utf-8"))
    return [
        Document(
            document_id=f"doc_{entry['id']}",
            chapter=entry["chapter"],
            name=entry["name"],
            html_path=entry["html"],
            pdf_path=entry["pdf"],
        )
        for entry in entries
    ]


def _kind_of(element: Tag) -> BlockKind | None:
    """Suy ra loại khối từ CSS class; None nghĩa là bỏ qua khối này.

    `<table>` được nhận theo tên thẻ chứ không theo class: HTML5 không cho phép
    `<table>` nằm trong `<p>`, nên parser tách `<p class="Table">` thành thẻ rỗng
    và đẩy bảng ra ngoài làm anh em — bảng do đó không thừa hưởng class nào.
    """
    if element.name == "table":
        return BlockKind.TABLE
    for token in element.get("class") or []:
        kind = _CLASS_KIND.get(token)
        if kind is not None:
            return kind
    return BlockKind.LIST if element.name in ("ul", "ol") else None


def _render(element: Tag, kind: BlockKind) -> str:
    """Chuyển một khối thành text thuần, giữ cấu trúc dòng cho list và bảng."""
    if kind is BlockKind.TABLE:
        table = element if element.name == "table" else element.find("table")
        return _render_table(table) if table else ""
    if kind is BlockKind.LIST:
        items = [normalize_text(li.get_text(" ", strip=True)) for li in element.find_all("li")]
        return "\n".join(f"- {item}" for item in items if item)
    return normalize_text(element.get_text(" ", strip=True))


def _render_table(table: Tag) -> str:
    """Mỗi hàng thành một dòng; ô rỗng (chỉ chứa ảnh) bị lược bỏ."""
    lines: list[str] = []
    for row in table.find_all("tr"):
        cells = [normalize_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
        filled = [cell for cell in cells if cell]
        if filled:
            lines.append(" | ".join(filled))
    return "\n".join(lines)


def _is_nested(element: Tag, emitted: set[int]) -> bool:
    """True nếu khối nằm trong một khối đã phát ra (ví dụ <p> bên trong bảng)."""
    for parent in element.parents:
        if id(parent) in emitted:
            return True
    return False


def parse_html(path: Path) -> list[Block]:
    """Phân rã một file HTML sổ tay thành danh sách Block theo thứ tự tài liệu."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    content = soup.select_one("#vfom-content")
    if content is None:
        raise ValueError(f"khong tim thay #vfom-content trong {path.name}")

    blocks: list[Block] = []
    emitted: set[int] = set()
    for element in content.find_all(_BLOCK_TAGS):
        if _is_nested(element, emitted):
            continue
        kind = _kind_of(element)
        if kind is None:
            continue
        text = _render(element, kind)
        if not text:
            continue
        emitted.add(id(element))
        blocks.append(Block(kind=kind, text=text, anchor_id=element.get("id")))
    return blocks

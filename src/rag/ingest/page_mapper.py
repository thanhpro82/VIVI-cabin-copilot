"""Gán số trang cho từng chunk bằng cách đối chiếu với PDF của chính mục đó.

Sổ tay VF9 **đánh số trang lại từ 1 cho mỗi mục**, không có hệ số trang toàn cục
— kiểm chứng bằng footer `"<chương> / <mục>  <số>"` ở mọi trang. Do đó chỉ số
trang trong `pdf/<chương>/<mục>.pdf` chính là số trang in, không lệch, và không
gian tìm kiếm chỉ còn 1–20 trang mỗi mục thay vì hơn 600 trang.

Citation vì thế phải đọc kèm `section`: "trang 2" một mình là mơ hồ vì có 58
trang mang số 2, còn "Đóng Mở và Khoang chứa đồ / Cửa sổ điện, trang 2" thì không.
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

from src.rag.models import Chunk, PageSource
from src.rag.textnorm import fold

#: Độ dài mỗi chuỗi mồi. Phải đủ ngắn để không vắt qua ranh giới hai trang —
#: mồi 90 ký tự trượt ở 20% số chunk chỉ vì lý do này.
PROBE_CHARS = 40

#: Số mồi lấy rải đều trong chunk. Một mồi duy nhất ở đầu chunk không đủ tin cậy:
#: PyMuPDF trích nội dung trong hộp CẢNH BÁO theo thứ tự layout, không theo thứ
#: tự đọc của HTML, nên phần đầu chunk có thể không khớp dù chunk nằm đúng trang.
PROBE_COUNT = 4

#: Chuỗi mồi ngắn hơn ngưỡng này không đáng tin, bỏ qua và suy ra từ chunk trước.
MIN_PROBE_CHARS = 25

#: Tỷ lệ ký tự của mồi phải khớp thì mới chấp nhận ở bậc FUZZY. So khớp chuỗi con
#: chính xác rất giòn: PyMuPDF có thể trả về ligature hoặc khoảng trắng khác HTML,
#: chỉ lệch một ký tự là trượt. Đo trên corpus VF9 hiện tại có 3 chunk chỉ khớp
#: đúng 1/4 mồi — chúng là những chunk sẽ rơi xuống DERIVED đầu tiên khi sổ tay
#: đổi phiên bản.
FUZZY_RATIO = 0.85


def extract_pages(pdf_path: Path) -> dict[int, str]:
    """Trích text từng trang; khoá là số trang in (1-based)."""
    with pymupdf.open(pdf_path) as document:
        return {number: page.get_text() for number, page in enumerate(document, start=1)}


def _probes_of(chunk: Chunk) -> list[str]:
    """Lấy `PROBE_COUNT` chuỗi mồi rải đều trong chunk đã fold."""
    folded = fold(chunk.text)
    if len(folded) < MIN_PROBE_CHARS:
        return []
    span = max(len(folded) - PROBE_CHARS, 0)
    offsets = sorted({round(span * step / (PROBE_COUNT - 1)) for step in range(PROBE_COUNT)})
    return [folded[offset : offset + PROBE_CHARS] for offset in offsets]


def _locate(probes: list[str], folded: dict[int, str], after: int) -> int | None:
    """Trang nhỏ nhất khớp bất kỳ mồi nào, ưu tiên từ `after` vì trang tăng dần."""
    hits = {number for probe in probes for number, text in folded.items() if probe in text}
    if not hits:
        return None
    forward = [number for number in hits if number >= after]
    return min(forward) if forward else min(hits)


def _coverage(probe: str, window: str) -> float:
    """Tỷ lệ ký tự của mồi khớp được trong một cửa sổ văn bản.

    Dùng tổng độ dài các khối khớp thay vì `SequenceMatcher.ratio()`: `ratio()`
    chia cho tổng độ dài cả hai chuỗi nên khi cửa sổ dài gấp đôi mồi, một lần
    chứa trọn vẹn cũng chỉ ra 0,67 chứ không phải 1,0.
    """
    matcher = SequenceMatcher(None, probe, window, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks()) / len(probe)


def _best_coverage(probe: str, text: str) -> float:
    """Điểm khớp cao nhất khi trượt cửa sổ dọc theo text một trang.

    Trượt theo cửa sổ hẹp thay vì so mồi với cả trang, để các ký tự trùng rải rác
    khắp trang không cộng dồn thành điểm giả.
    """
    width = len(probe) * 2
    stride = max(len(probe) // 4, 1)
    best = 0.0
    for start in range(0, max(len(text) - width, 0) + 1, stride):
        best = max(best, _coverage(probe, text[start : start + width]))
        if best >= 0.99:
            break
    return best


def _fuzzy_locate(probes: list[str], folded: dict[int, str], after: int) -> int | None:
    """Bậc dự phòng khi so khớp chính xác trượt; chọn trang có điểm cao nhất."""
    scored = [
        (number, max((_best_coverage(probe, text) for probe in probes), default=0.0))
        for number, text in folded.items()
    ]
    passing = [number for number, score in scored if score >= FUZZY_RATIO]
    if not passing:
        return None
    forward = [number for number in passing if number >= after]
    return min(forward) if forward else min(passing)


def assign_pages(chunks: list[Chunk], pdf_path: Path) -> list[Chunk]:
    """Gán `page` và `page_source` theo ba bậc: chính xác → mờ → kế thừa."""
    folded = {number: fold(text) for number, text in extract_pages(pdf_path).items()}
    resolved: list[Chunk] = []
    last_page = 1
    for chunk in chunks:
        probes = _probes_of(chunk)
        found = _locate(probes, folded, last_page)
        source = PageSource.EXACT
        if found is None and probes:
            found = _fuzzy_locate(probes, folded, last_page)
            source = PageSource.FUZZY
        if found is None:
            found, source = last_page, PageSource.DERIVED
        else:
            last_page = found
        resolved.append(chunk.model_copy(update={"page": found, "page_source": source}))
    return resolved


def page_stats(chunks: list[Chunk]) -> Counter[PageSource]:
    """Đếm chunk theo từng bậc tin cậy — dùng cho báo cáo và cổng chất lượng."""
    return Counter(chunk.page_source for chunk in chunks)


def exact_rate(chunks: list[Chunk]) -> float:
    """Tỷ lệ chunk khớp trang **chính xác**."""
    if not chunks:
        return 0.0
    return page_stats(chunks)[PageSource.EXACT] / len(chunks)


def resolved_rate(chunks: list[Chunk]) -> float:
    """Tỷ lệ chunk xác định được trang thật (chính xác hoặc mờ).

    Đây mới là cổng chất lượng: chunk `DERIVED` không có bằng chứng trang riêng,
    nó chỉ mượn trang của chunk trước nên có thể sinh citation sai.
    """
    if not chunks:
        return 0.0
    stats = page_stats(chunks)
    return (stats[PageSource.EXACT] + stats[PageSource.FUZZY]) / len(chunks)

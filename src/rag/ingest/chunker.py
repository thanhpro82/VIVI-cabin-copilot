"""Cắt danh sách Block thành Chunk để embed và trích dẫn.

Ranh giới chính là `Detail-Heading` (khối có anchor id). Khi một mục vượt quá
`MAX_CHARS` thì cắt tiếp tại `Sub-Section`/`Sub-Sub-Heading`.

Chỉ cắt tại các khối tiêu đề nên hai bất biến sau luôn đúng:

* Khối CẢNH BÁO/THẬN TRỌNG/LƯU Ý không bao giờ bị tách khỏi phần nội dung mà nó
  cảnh báo — một cảnh báo mất ngữ cảnh còn nguy hiểm hơn là không có cảnh báo.
* Bảng và danh sách không bao giờ bị cắt đôi.

Hệ quả: khoảng 7,5% chunk vẫn vượt trần 512 token của embedder, hầu hết vì chứa
một khối cảnh báo dài liền mạch (dây đai an toàn, túi khí) không được phép cắt.
Phần đuôi của chúng được xử lý ở tầng embedding bằng cách sinh nhiều vector cho
cùng một chunk, chứ không phải bằng cách cắt nhỏ khối an toàn ở đây — nhờ vậy mỗi
citation vẫn trỏ về đúng một chunk nguyên vẹn.

`MAX_CHARS` và `HARD_MAX_CHARS` dưới đây là ngưỡng **ngữ nghĩa**: chunk quá to thì
số trang trích dẫn kém chính xác và evidence loãng. Chúng **không** phải cơ chế
chống tràn token — đếm ký tự không suy ra được số token (tỷ lệ đo trên corpus VF9
dao động 2,41–4,21 ký tự/token). Việc chống cắt cụt nằm ở
`Embedder.split_for_embedding`, nơi duy nhất biết tokenizer thật. Đừng hạ hai hằng
số này với mục đích chống tràn token: nó không giải quyết được, chỉ làm chunk vụn.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from src.rag.models import (
    FALLBACK_SPLIT_KINDS,
    SAFETY_KINDS,
    SPLIT_KINDS,
    Block,
    BlockKind,
    Chunk,
    Document,
)

#: Ngưỡng mềm cho lượt cắt theo tiêu đề con. `multilingual-e5-small` cắt input ở
#: 512 token; với tiếng Việt khoảng 800 ký tự là còn dư biên, đồng thời chunk nhỏ
#: cho số trang chính xác hơn.
MAX_CHARS = 800

#: Ngưỡng cứng cho lượt cắt dự phòng. Đo trên corpus VF9: tiếng Việt tốn khoảng
#: 3,56 ký tự/token, nên 1.400 ký tự ~ 390 token, còn biên dưới trần 512 của
#: embedder. Vượt trần thì phần đuôi bị cắt cụt và biến mất khỏi retrieval.
HARD_MAX_CHARS = 1400

#: Chunk ngắn hơn ngưỡng này bị gộp vào chunk liền trước: chúng thường chỉ là
#: tiêu đề trơ, dễ thắng retrieval nhờ trùng chữ mà không chứa câu trả lời.
MIN_CHARS = 200


@dataclass
class _Part:
    """Một chunk ứng viên: tiêu đề cha cộng các khối thuộc về nó."""

    heading: str
    anchor_id: str | None
    blocks: list[Block] = field(default_factory=list)


def _group_by_heading(blocks: list[Block]) -> list[_Part]:
    """Gom các khối theo Detail-Heading gần nhất phía trước."""
    parts: list[_Part] = []
    for block in blocks:
        if block.kind is BlockKind.HEADING or not parts:
            heading = block.text if block.kind is BlockKind.HEADING else ""
            parts.append(_Part(heading=heading, anchor_id=block.anchor_id))
        parts[-1].blocks.append(block)
    return parts


def _can_open_chunk(block: Block, allowed: frozenset[BlockKind]) -> bool:
    """Một khối chỉ được mở đầu chunk khi đúng loại và không phải khối an toàn."""
    return block.kind in allowed and block.kind not in SAFETY_KINDS


def _split_at(blocks: list[Block], allowed: frozenset[BlockKind], limit: int) -> list[list[Block]]:
    """Gói tham lam: cắt tại ứng viên đầu tiên mà đoạn tích luỹ đã chạm `limit`."""
    pieces: list[list[Block]] = []
    start = 0
    for index in range(1, len(blocks)):
        if not _can_open_chunk(blocks[index], allowed):
            continue
        if len(_join(blocks[start:index])) < limit:
            continue
        pieces.append(blocks[start:index])
        start = index
    pieces.append(blocks[start:])
    return pieces


def _merge_runts(pieces: list[list[Block]]) -> list[list[Block]]:
    """Gộp mảnh quá ngắn vào mảnh liền trước."""
    merged: list[list[Block]] = []
    for piece in pieces:
        if merged and len(_join(piece)) < MIN_CHARS:
            merged[-1].extend(piece)
        else:
            merged.append(list(piece))
    return merged


def _split_oversized(part: _Part) -> list[_Part]:
    """Cắt part quá dài: ưu tiên tiêu đề con, dự phòng bằng ranh giới đoạn văn."""
    by_heading = _split_at(part.blocks, SPLIT_KINDS, MAX_CHARS)
    by_paragraph = [piece for group in by_heading for piece in _split_at(group, FALLBACK_SPLIT_KINDS, HARD_MAX_CHARS)]
    return [_Part(part.heading, part.anchor_id, piece) for piece in _merge_runts(by_paragraph)]


def _join(blocks: list[Block]) -> str:
    return "\n".join(block.text for block in blocks)


#: Dấu hiệu **biến thể sản phẩm**, chọn bằng dữ liệu chứ không bằng cảm tính.
#:
#: Đo trên 482 chunk thật (13/08): bộ này khớp **48 chunk = 10,0%**. Hai bộ thử trước
#: đều sai theo hai hướng ngược nhau, và cả hai đều làm hỏng tính năng:
#:
#: - Rộng ("phiên bản", "nếu có") → 39,6%. Cứ 5 câu hỏi thì 2 câu bị từ chối đọc số;
#:   tài xế sẽ thôi hỏi.
#: - Thêm "tùy chọn" → 15,1%, và kiểm tay 36 chunk bị bắt oan: trong sổ tay này "tùy
#:   chọn" phần lớn nghĩa là *tuỳ chọn người dùng* ("Chỉ Đèn / Chỉ Còi"), không phải
#:   biến thể xe.
#:
#: Đổi danh sách này là đổi hành vi tài xế nghe thấy. Đo lại trên 482 chunk trước khi
#: đổi, và giữ tỷ lệ trong khoảng 5–12%.
#: **Chỉ bắt một lớp: giá trị khác nhau giữa các phiên bản.** Bản trước gộp thêm "nếu
#: được trang bị", và đó là hai chuyện khác hẳn nhau về mức nguy hiểm:
#:
#: - *"Nếu được trang bị"* = **xe bạn có thể không có tính năng này**. Nói câu trả lời
#:   ra không nguy hiểm; vế điều kiện chỉ cần đi kèm, mà ADR-015 đã chốt trích nguyên
#:   văn nên nó tự đi kèm.
#: - *ECO / PLUS / SDI / CATL* = **cùng một đại lượng, giá trị khác nhau**. Đây mới là
#:   lớp ADR-015 đo được 4/40 câu gây hiểu lầm: bốc một cột của bảng áp suất lốp ra
#:   trình bày như giá trị chung, xe pin CATL bơm theo đó là thiếu hơi.
#:
#: Gộp hai lớp làm một khiến **4/5 ca bị từ chối oan** (đo 14/08 trên 40 case): một dấu
#: hiệu ở tính năng con làm câm cả đoạn mà câu trả lời nằm chỗ khác. RAG-109 câm vì một
#: chữ "(nếu được trang bị)" ở tựa lưng, trong đoạn 1.354 ký tự; RAG-127 câm vì **màn
#: hình sau** là tuỳ chọn, chẳng liên quan gì tới đài FM.
#:
#: ECO/PLUS đòi ngữ cảnh phiên bản chứ không bắt trần: RAG-139 khớp `\bECO\b` bốn lần
#: mà cả bốn đều là *chế độ lái* ECO. Ô bảng (`| ECO |`) và cụm "bản ECO" thì giữ.
#:
#: Đổi danh sách này là đổi hành vi tài xế nghe thấy. Đo lại trên 482 chunk trước khi
#: đổi, và xem dòng "doc so o doan bien the" của `src.rag.cli eval` vẫn phải là 0.
#:
#: Dạng `VF 9 ECO` thêm 15/08 (issue #124): sổ tay gọi tên phiên bản bằng **tên xe**
#: chứ không phải chữ "bản", nên bộ dò cũ bỏ sót nguyên đoạn "Thông số kỹ thuật lốp xe"
#: (trang 5) — nơi có `340 kPa (ECO)` và `350 kPa (PLUS)` cho cùng một đại lượng. Đó là
#: **âm tính giả**, đúng lớp nguy hiểm mà cờ này sinh ra để bắt.
#:
#: Đo trước khi nới, theo đúng dòng ghi trên: trên 482 chunk, dạng này làm cờ bật thêm
#: **đúng 1 chunk**, và chunk ấy chính là chunk bỏ sót. Không có dương tính giả nào.
_VARIANT_MARKERS = re.compile(
    r"\bSDI\b|\bCATL\b"
    r"|(?:bản|phiên bản)\s+(?:ECO|PLUS)\b"
    r"|\bVF\s*9\s+(?:ECO|PLUS)\b"
    r"|\|\s*(?:ECO|PLUS)\b|\b(?:ECO|PLUS)\s*\|",
    re.IGNORECASE,
)


def _has_variant_condition(heading: str, text: str) -> bool:
    """Dò cả **heading** lẫn text.

    2/48 chunk mang dấu hiệu chỉ ở heading — với bộ dò cũ là "Kích nâng xe và vá lốp
    (nếu được trang bị)". Bộ dò mới không bắt lớp đó nữa, nhưng heading vẫn phải quét:
    bảng thông số hay để tên phiên bản ở tiêu đề rồi thân bảng chỉ còn số.
    """
    return bool(_VARIANT_MARKERS.search(heading or "") or _VARIANT_MARKERS.search(text))


def _build_chunk(document: Document, part: _Part, ordinal: int) -> Chunk:
    """Dựng Chunk từ một part đã chốt ranh giới."""
    text = _join(part.blocks)
    kinds = {block.kind for block in part.blocks}
    number = document.document_id.removeprefix("doc_")
    return Chunk(
        chunk_id=f"chunk_{number}_{ordinal:03d}",
        document_id=document.document_id,
        section=document.section,
        heading=part.heading,
        anchor_id=part.anchor_id,
        text=text,
        has_warning=BlockKind.WARNING in kinds,
        has_caution=BlockKind.CAUTION in kinds,
        has_note=BlockKind.NOTE in kinds,
        is_table=BlockKind.TABLE in kinds,
        has_variant_condition=_has_variant_condition(part.heading, text),
        checksum=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    )


def chunk_document(document: Document, blocks: list[Block]) -> list[Chunk]:
    """Cắt toàn bộ khối của một mục sổ tay thành các Chunk đánh số liên tiếp."""
    chunks: list[Chunk] = []
    for part in _group_by_heading(blocks):
        for piece in _split_oversized(part):
            if not _join(piece.blocks).strip():
                continue
            chunks.append(_build_chunk(document, piece, len(chunks) + 1))
    return chunks

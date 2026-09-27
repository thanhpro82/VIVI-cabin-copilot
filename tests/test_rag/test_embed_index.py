"""Test embedder và FAISS index — chạy bằng StubEmbedder nên không cần torch."""

from pathlib import Path

from src.rag.embed import (
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    WINDOW_CHARS,
    StubEmbedder,
    window_spans,
    window_text,
)
from src.rag.index import VectorIndex, embed_input
from src.rag.models import Chunk


class _RecordingEmbedder(StubEmbedder):
    """Ghi lại đúng chuỗi được đưa vào mô hình để kiểm tra tiền tố."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def _encode_one(self, text: str):
        self.seen.append(text)
        return super()._encode_one(text)


def _chunk(index: int, text: str, section: str = "Lái xe / Vô lăng") -> Chunk:
    return Chunk(
        chunk_id=f"chunk_1_{index:03d}",
        document_id="doc_1",
        section=section,
        heading="Vô lăng",
        text=text,
        page=index,
    )


def test_tien_to_e5_duoc_gan_o_ca_hai_duong() -> None:
    """Quên tiền tố không gây lỗi, chỉ làm tụt chất lượng — nên phải test."""
    embedder = _RecordingEmbedder()
    embedder.embed_passages(["nội dung sổ tay"])
    embedder.embed_query("câu hỏi")
    assert embedder.seen[0].startswith(PASSAGE_PREFIX)
    assert embedder.seen[1].startswith(QUERY_PREFIX)


def _offsets(count: int, width: int = 3) -> list[tuple[int, int]]:
    """Giả lập offset ký tự của `count` token, mỗi token `width` ký tự."""
    return [(index * width, index * width + width) for index in range(count)]


def test_window_spans_rong_khi_khong_co_token() -> None:
    assert window_spans([], budget=10, overlap=2) == []


def test_window_spans_gom_thanh_mot_khi_vua_ngan_sach() -> None:
    spans = window_spans(_offsets(10), budget=10, overlap=2)
    assert spans == [(0, 30)]


def test_window_spans_khong_cua_so_nao_vuot_ngan_sach() -> None:
    """Đây là bất biến thay thế cho việc đoán số token bằng số ký tự."""
    offsets = _offsets(100)
    spans = window_spans(offsets, budget=30, overlap=5)
    for start, end in spans:
        tokens = [o for o in offsets if o[0] >= start and o[1] <= end]
        assert len(tokens) <= 30


def test_window_spans_phu_kin_toan_bo_van_ban() -> None:
    offsets = _offsets(100)
    spans = window_spans(offsets, budget=30, overlap=5)
    assert spans[0][0] == 0
    assert spans[-1][1] == offsets[-1][1]


def test_window_spans_co_chong_lan_giua_hai_cua_so_lien_tiep() -> None:
    spans = window_spans(_offsets(100), budget=30, overlap=5)
    assert len(spans) > 1
    assert spans[1][0] < spans[0][1]


def test_window_text_giu_nguyen_van_ban_ngan() -> None:
    assert window_text("ngắn") == ["ngắn"]


def test_window_text_cat_va_chong_lan_van_ban_dai() -> None:
    text = "x" * (WINDOW_CHARS * 2)
    windows = window_text(text)
    assert len(windows) > 1
    assert all(len(window) <= WINDOW_CHARS for window in windows)
    assert sum(len(window) for window in windows) > len(text)


def test_embed_input_them_section_de_phan_biet_muc_cung_chu_de() -> None:
    assert embed_input(_chunk(1, "nội dung")).startswith("Lái xe / Vô lăng")


def test_index_tra_ve_chunk_lien_quan_nhat() -> None:
    chunks = [
        _chunk(1, "sưởi ghế trước bật bằng nút trên màn hình"),
        _chunk(2, "áp suất lốp khuyến nghị kiểm tra khi lốp nguội"),
    ]
    embedder = StubEmbedder()
    index = VectorIndex.build(chunks, embedder)
    hits = index.search(embedder.embed_query("sưởi ghế trước"), top_k=2)
    assert hits[0].chunk_id == "chunk_1_001"


def test_chunk_dai_sinh_nhieu_vector_nhung_chi_mot_ket_qua() -> None:
    """Nhiều cửa sổ cho một chunk không được làm chunk đó xuất hiện trùng lặp."""
    chunks = [_chunk(1, "sưởi ghế " * WINDOW_CHARS)]
    index = VectorIndex.build(chunks, StubEmbedder())
    assert index.vector_count > 1
    hits = index.search(StubEmbedder().embed_query("sưởi ghế"), top_k=5)
    assert [hit.chunk_id for hit in hits] == ["chunk_1_001"]


def test_index_rong_tra_ve_danh_sach_rong() -> None:
    index = VectorIndex.build([], StubEmbedder())
    assert index.search(StubEmbedder().embed_query("bất kỳ"), top_k=5) == []


def test_luu_va_nap_lai_giu_nguyen_ket_qua(tmp_path: Path) -> None:
    chunks = [_chunk(1, "sưởi ghế trước"), _chunk(2, "áp suất lốp")]
    embedder = StubEmbedder()
    checksum = VectorIndex.build(chunks, embedder).save(tmp_path)
    reloaded = VectorIndex.load(tmp_path)
    assert checksum.startswith("sha256:")
    assert reloaded.search(embedder.embed_query("sưởi ghế"), top_k=1)[0].chunk_id == "chunk_1_001"

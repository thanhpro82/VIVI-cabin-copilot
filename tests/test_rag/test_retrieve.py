"""Test grader lai, Citation và node RAG."""

import pytest

from src.agents.nodes.rag_node import INSUFFICIENT_EVIDENCE, make_rag_node
from src.rag.embed import StubEmbedder
from src.rag.index import VectorIndex
from src.rag.models import Chunk, Evidence
from src.rag.retrieve import RetrievalConfig, Retriever, to_citations, validate_citations

SECTION = "Đóng Mở và Khoang chứa đồ / Cửa sổ điện"


def _chunk(index: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"chunk_1_{index:03d}",
        document_id="doc_1",
        section=SECTION,
        heading="Cửa sổ điện",
        text=text,
        page=index,
    )


@pytest.fixture
def chunks() -> list[Chunk]:
    return [
        _chunk(1, "Kéo công tắc cửa sổ lên để đóng hoàn toàn cửa sổ điện."),
        _chunk(2, "Áp suất lốp khuyến nghị nằm trong hồ sơ xe."),
    ]


def _retriever(chunks: list[Chunk], config: RetrievalConfig) -> Retriever:
    return Retriever(VectorIndex.build(chunks, StubEmbedder()), chunks, config)


def _evidence(score: float, text: str = "công tắc cửa sổ") -> Evidence:
    return Evidence(section=SECTION, page=1, text=text, chunk_id="chunk_1_001", score=score)


def test_grade_loai_bang_chung_duoi_nguong_diem(chunks: list[Chunk]) -> None:
    retriever = _retriever(chunks, RetrievalConfig(min_score=0.9, min_overlap=0.0))
    assert retriever.grade("công tắc cửa sổ", [_evidence(0.5)]) == []


def test_grade_loai_bang_chung_thieu_trung_tu_vung(chunks: list[Chunk]) -> None:
    """Điểm cosine cao vẫn chưa đủ: e5 chấm cao cho câu ngoài phạm vi cùng chủ đề."""
    retriever = _retriever(chunks, RetrievalConfig(min_score=0.1, min_overlap=0.9))
    assert retriever.grade("công thức nấu phở bò", [_evidence(0.99)]) == []


def test_grade_giu_toi_da_keep_bang_chung(chunks: list[Chunk]) -> None:
    retriever = _retriever(chunks, RetrievalConfig(min_score=0.0, min_overlap=0.0, keep=2))
    assert len(retriever.grade("công tắc", [_evidence(0.9) for _ in range(5)])) == 2


def test_search_tra_ve_rong_khi_query_trong(chunks: list[Chunk]) -> None:
    retriever = _retriever(chunks, RetrievalConfig(min_score=0.0, min_overlap=0.0))
    assert retriever.search("   ", StubEmbedder()) == []


def test_citation_co_dung_tam_field_va_tu_choi_field_la() -> None:
    citations = to_citations([_evidence(0.9)], "turn_1", "Sổ tay VF9")
    assert set(citations[0].model_dump()) == {
        "citation_id",
        "turn_id",
        "document_title",
        "section",
        "page",
        "chunk_id",
        "excerpt",
        "retrieval_score",
    }


def test_validate_citations_bat_lech_giua_index_va_chunk_store(chunks: list[Chunk]) -> None:
    retriever = _retriever(chunks, RetrievalConfig())
    good = to_citations([_evidence(0.9)], "turn_1", "Sổ tay VF9")
    assert validate_citations(good, retriever) is True

    wrong_page = good[0].model_copy(update={"page": 99})
    assert validate_citations([wrong_page], retriever) is False
    assert validate_citations([], retriever) is False


def test_document_title_doc_edition_tu_manifest(tmp_path) -> None:
    """Citation phải nói nó trích từ **bản nào** của sổ tay.

    Node mặc định trước đây bỏ trống `document_title`, nên câu trả lời trích trang
    14 mà không nói trang 14 của tài liệu gì. `edition` trong manifest là định
    danh corpus tự khai — dùng nguyên văn, không tự đặt tên cho tài liệu.
    """
    import json

    from src.agents.nodes.rag_node import document_title

    (tmp_path / "manifest.json").write_text(json.dumps({"edition": "VF9_23-25_VN_VI_2.4"}), encoding="utf-8")
    assert document_title(tmp_path) == "VF9_23-25_VN_VI_2.4"


def test_document_title_rong_khi_khong_doc_duoc_manifest(tmp_path) -> None:
    """Thiếu/hỏng manifest thì bỏ trống, không chặn tra cứu — đây là nhãn, không phải bằng chứng."""
    from src.agents.nodes.rag_node import document_title

    assert document_title(tmp_path) == ""
    (tmp_path / "manifest.json").write_text("{ khong phai json", encoding="utf-8")
    assert document_title(tmp_path) == ""


async def test_rag_node_tu_choi_khi_khong_du_bang_chung(chunks: list[Chunk]) -> None:
    retriever = _retriever(chunks, RetrievalConfig(min_score=0.99, min_overlap=0.99))
    node = make_rag_node(retriever, StubEmbedder(), "Sổ tay VF9")
    result = await node({"query": "công thức nấu phở bò"})
    assert result["refusal_reason"] == INSUFFICIENT_EVIDENCE
    assert result["citations"] == []


async def test_rag_node_tra_citation_khi_du_bang_chung(chunks: list[Chunk]) -> None:
    retriever = _retriever(chunks, RetrievalConfig(min_score=0.0, min_overlap=0.0))
    node = make_rag_node(retriever, StubEmbedder(), "Sổ tay VF9")
    # `turn_id` ở **top-level**, đúng chỗ `turns.py`/`approvals.py` đặt nó. Bản trước
    # truyền qua `metadata` — đường duy nhất chạy được lúc đó, nhưng không caller thật
    # nào dùng, nên test xanh mà production vẫn ra "turn_unknown".
    result = await node({"query": "kéo công tắc cửa sổ", "turn_id": "turn_9"})
    assert "refusal_reason" not in result
    assert result["citations"][0].turn_id == "turn_9"
    assert result["citations"][0].page > 0

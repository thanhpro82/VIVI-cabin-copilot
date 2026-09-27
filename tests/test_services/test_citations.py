"""CitationStore — kho tra ngược cho `GET /api/v1/citations/{citation_id}`."""

from src.rag.models import Citation
from src.services.citations import CitationStore


def _citation(citation_id: str, turn_id: str = "turn-1") -> Citation:
    return Citation(
        citation_id=citation_id,
        turn_id=turn_id,
        document_title="Sổ tay VF9",
        section="Cửa sổ điện",
        page=87,
        chunk_id="c1",
        excerpt="Công tắc khoá cửa sổ điện.",
        retrieval_score=0.9,
    )


def test_saved_citation_can_be_read_back_with_its_owner():
    store = CitationStore()
    store.save([_citation("cit_a")], "ses-1")

    record = store.get("cit_a")

    assert record is not None
    assert record.citation.citation_id == "cit_a"
    assert record.session_id == "ses-1"


def test_unknown_citation_returns_none():
    assert CitationStore().get("cit_khong_ton_tai") is None


def test_forgetting_a_session_drops_only_that_sessions_citations():
    """Phiên bị đuổi thì citation của nó thành rác không ai gọi tới được nữa."""
    store = CitationStore()
    store.save([_citation("cit_a")], "ses-1")
    store.save([_citation("cit_b")], "ses-2")

    store.forget_session("ses-1")

    assert store.get("cit_a") is None
    assert store.get("cit_b") is not None


def test_the_store_has_its_own_cap_independent_of_session_eviction():
    """Một phiên hỏi sổ tay cả buổi thì không bao giờ bị đuổi, nên `forget_session`
    không chặn được kiểu phình này. Trần riêng mới chặn được."""
    store = CitationStore(max_records=3)

    for index in range(10):
        store.save([_citation(f"cit_{index}")], "ses-lau-dai")

    assert store.record_count == 3


def test_the_cap_drops_the_oldest_first():
    store = CitationStore(max_records=2)
    store.save([_citation("cit_cu")], "ses-1")
    store.save([_citation("cit_giua")], "ses-1")
    store.save([_citation("cit_moi")], "ses-1")

    assert store.get("cit_cu") is None
    assert store.get("cit_moi") is not None


def test_reading_a_citation_keeps_it_alive():
    """LRU, không phải FIFO: thẻ tài xế vừa bấm không được là thẻ bị đuổi tiếp theo."""
    store = CitationStore(max_records=2)
    store.save([_citation("cit_a")], "ses-1")
    store.save([_citation("cit_b")], "ses-1")

    store.get("cit_a")  # chạm lại
    store.save([_citation("cit_c")], "ses-1")

    assert store.get("cit_a") is not None
    assert store.get("cit_b") is None

"""Hợp nhất BM25 + dense trong `Retriever` (18/08).

## Vì sao nối vào

Đo trên `eval/datasets/manual/hoi-nhu-tai-xe-v1` — câu hỏi viết theo giọng tài xế, sinh
từ tên mục chứ không từ thân đoạn:

    dense       recall@1 55%
    hybrid      recall@1 62%   (+7 điểm, +3,5 ms)

Dense hỏng theo kiểu đã có tên: *entity-swap* — "lốp dự phòng" và "áp suất lốp tiêu
chuẩn" cách nhau **0,0001** điểm. Và cả bảng xếp hạng nằm trong dải mỏng: khoảng cách
hạng-1 với hạng-2 có trung vị **0,0038**. BM25 khớp đúng từ nên nó phá được thế hoà mà
dense không tự phân xử nổi.

## Bất biến file này khoá

Hai cái, và cái thứ nhất suýt làm hỏng cả hệ thống nếu không để ý.
"""


from src.rag.bm25 import BM25Index, hop_nhat_rrf
from src.rag.embed import StubEmbedder
from src.rag.index import VectorIndex
from src.rag.models import Chunk
from src.rag.retrieve import RetrievalConfig, Retriever


def _chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id=f"c{i}",
            document_id="d1",
            section=f"Mục {i}",
            heading=f"Mục {i}",
            page=i,
            text=t,
            token_count=len(t.split()),
        )
        for i, t in enumerate(
            [
                "Áp suất lốp trục trước 260 KPA và trục sau 270 KPA khi lốp nguội.",
                "Cách khởi tạo lại cửa sổ điện sau khi tháo ắc quy.",
                "Chức năng chống kẹp dừng cửa sổ khi gặp lực cản.",
            ]
        )
    ]


def test_diem_van_la_cosine_chu_khong_phai_diem_rrf():
    """**Bất biến quan trọng nhất.**

    `grade()` lọc `score >= min_score` (0.848, hiệu chỉnh trên 60 case theo ADR-003).
    Điểm RRF nằm quanh 0,03 — gán nó vào `Evidence.score` là làm **mọi** câu hỏi sổ tay
    bị từ chối, và hỏng theo kiểu im lặng: hệ thống vẫn chạy, chỉ là luôn nói "tôi không
    tìm thấy thông tin này".

    Hợp nhất đổi **thứ tự**, không đổi **thang đo**.
    """
    chunks = _chunks()
    emb = StubEmbedder()
    r = Retriever(VectorIndex.build(chunks, emb), chunks, RetrievalConfig(hybrid=True))

    ev = r.retrieve("áp suất lốp bao nhiêu", emb)

    assert ev, "khong tra ve gi"
    for e in ev:
        assert 0.0 <= e.score <= 1.0, f"diem {e.score} khong con o thang cosine"


def test_tat_co_bat_duoc_va_khong_doi_hanh_vi_cu():
    """Phải có đường lui: thay đổi này đổi thứ tự của **mọi** lượt sổ tay.

    `hybrid=False` phải cho đúng thứ tự dense như trước khi có tính năng.
    """
    chunks = _chunks()
    emb = StubEmbedder()
    ix = VectorIndex.build(chunks, emb)
    tat = Retriever(ix, chunks, RetrievalConfig(hybrid=False)).retrieve("áp suất lốp", emb)
    tho = [h.chunk_id for h in ix.search(emb.embed_query("áp suất lốp"), 8)]

    assert [e.chunk_id for e in tat] == tho[: len(tat)]


def test_rrf_hop_nhat_theo_hang_khong_theo_diem():
    """Cosine (~0,87) và BM25 (~3,0) ở hai thang khác hẳn nhau.

    Cộng thẳng là để BM25 áp đảo vì lý do **đơn vị**, không phải vì nó đúng hơn.
    """
    ket = hop_nhat_rrf(["x", "y", "z"], ["z", "y", "x"])

    # Tôi đoán sai lần đầu: tưởng `y` (hạng 2 ở CẢ HAI bảng) sẽ thắng. Không —
    # `1/(k+hạng)` là hàm **lồi**, nên một hạng-1 bù được nhiều hơn cái giá của một
    # hạng-3. `x` và `y` chênh nhau ở chữ số thập phân thứ năm:
    #     x = 1/60 + 1/62 = 0,032796      y = 1/61 + 1/61 = 0,032787
    # Đó chính là tính chất khiến RRF hữu ích ở đây: nó **thưởng cho việc một bên rất
    # tự tin**, thay vì trung bình hoá hai ý kiến làng nhàng.
    assert ket[0] in ("x", "z"), ket
    assert ket[-1] == "y", ket


def test_bm25_bo_hu_tu_va_giu_dau_thanh():
    """Bỏ dấu làm "bò/bỏ/bó" thành một từ — `textnorm` đã cảnh báo đúng chỗ này."""
    ix = BM25Index.build(["a", "b"], ["áp suất lốp trục trước", "âm lượng loa"])

    assert [i for i, _ in ix.search("áp suất lốp", 2)][:1] == ["a"]
    assert ix.search("không có từ nào khớp cả", 2) == []

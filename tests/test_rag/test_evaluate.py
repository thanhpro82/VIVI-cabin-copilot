"""Test phép tính của eval harness.

Đây là code sinh ra chính những con số được báo cáo, nên sai ở đây nguy hiểm hơn
sai ở retrieval: nó làm hệ thống *trông có vẻ* đạt chỉ tiêu.
"""

from pathlib import Path

import pytest

from src.rag.embed import StubEmbedder
from src.rag.evaluate import (
    EvalContext,
    Thresholds,
    best_threshold,
    citation_validity,
    load_cases,
    score_at,
)
from src.rag.index import VectorIndex
from src.rag.models import Chunk, Evidence
from src.rag.retrieve import RetrievalConfig, Retriever

SECTION = "Đóng Mở và Khoang chứa đồ / Cửa sổ điện"

_CASES = """
{"case_id":"P1","category":"rag","input_text":"kéo công tắc cửa sổ","expected":{"intent":"manual","supported":true,"citation":{"section":"SECTION_X","page":1}}}
{"case_id":"N1","category":"rag","input_text":"công thức nấu phở bò","expected":{"intent":"manual","supported":false,"citations":0,"negative_kind":"out_of_scope"}}
""".replace("SECTION_X", SECTION)


@pytest.fixture
def cases_path(tmp_path: Path) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text(_CASES.strip(), encoding="utf-8")
    return path


@pytest.fixture
def context() -> EvalContext:
    chunks = [
        Chunk(
            chunk_id="chunk_1_001",
            document_id="doc_1",
            section=SECTION,
            heading="Cửa sổ điện",
            text="Kéo công tắc cửa sổ lên để đóng hoàn toàn.",
            page=1,
        )
    ]
    embedder = StubEmbedder()
    retriever = Retriever(
        VectorIndex.build(chunks, embedder), chunks, RetrievalConfig(min_score=0.0, min_overlap=0.0)
    )
    return EvalContext(retriever=retriever, embedder=embedder)


def test_load_cases_tach_positive_va_negative(cases_path: Path) -> None:
    cases = load_cases(cases_path)
    assert [case.supported for case in cases] == [True, False]
    assert cases[0].section == SECTION
    assert cases[0].page == 1
    assert cases[1].negative_kind == "out_of_scope"


def test_nguong_long_lam_negative_lot_thanh_hallucination(cases_path: Path, context: EvalContext) -> None:
    cases = load_cases(cases_path)
    context.probe(cases)
    metrics, _ = score_at(context, cases, Thresholds(min_score=0.0, min_overlap=0.0))
    assert metrics.grounded_rate == 1.0
    assert metrics.hallucination_rate == 1.0
    assert metrics.passed is False


def test_nguong_chat_chan_negative_nhung_van_giu_positive(cases_path: Path, context: EvalContext) -> None:
    cases = load_cases(cases_path)
    context.probe(cases)
    metrics, outcomes = score_at(context, cases, Thresholds(min_score=0.0, min_overlap=0.6))
    assert metrics.hallucination_rate == 0.0
    assert metrics.grounded_rate == 1.0
    assert all(outcome.passed for outcome in outcomes)


def test_sai_so_trang_lam_positive_truot(cases_path: Path, context: EvalContext) -> None:
    """Nhãn `page` phải thực sự được kiểm, nếu không AC trích dẫn trang là vô nghĩa."""
    cases = load_cases(cases_path)
    cases[0].page = 99
    context.probe(cases)
    metrics, _ = score_at(context, cases, Thresholds(min_score=0.0, min_overlap=0.6))
    assert metrics.grounded_rate == 0.0
    assert metrics.recall_at_k == 1.0


def test_citation_validity_bat_lech_giua_index_va_store(context: EvalContext) -> None:
    context.probes = {
        "X": [Evidence(section=SECTION, page=1, text="t", chunk_id="chunk_1_001", score=0.9)]
    }
    assert citation_validity(context) == 1.0

    context.probes = {
        "X": [Evidence(section=SECTION, page=42, text="t", chunk_id="chunk_1_001", score=0.9)]
    }
    assert citation_validity(context) == 0.0


def test_best_threshold_uu_tien_cap_dat_ca_hai_muc_tieu(cases_path: Path, context: EvalContext) -> None:
    cases = load_cases(cases_path)
    context.probe(cases)
    sweep = [
        score_at(context, cases, Thresholds(min_score=0.0, min_overlap=overlap))[0]
        for overlap in (0.0, 0.6)
    ]
    assert best_threshold(sweep).min_overlap == 0.6


# --- Task 5: hai cột đo cho kênh NÓI -----------------------------------------
#
# Bảng của ADR-015 chấm câu **hiển thị**: "câu gây hiểu lầm / 40". Kênh nói có hai
# thất bại riêng mà bảng đó không nhìn thấy, và cả hai đều đo được bằng máy:
#
#   1. dài quá nghe không nổi (đo được: 65,6 s trước Task 1)
#   2. đọc số của một đoạn phụ thuộc phiên bản (đúng lớp lỗi RAG-130)
#
# Không có hai cột này thì Task 6 (S2 dùng SLM) sẽ phải chốt bằng ý kiến, trong khi
# thứ nó định thay thế lại có số.


def test_uoc_do_dai_audio_tu_so_ky_tu():
    """Không gọi Piper thật trong eval: máy CI và máy chưa tải model vẫn phải chạy được.

    Hệ số 20,1 ký tự/giây đo thật trên giọng `vi_VN-piper` ngày 13/08 (1.181 ký tự →
    65,6 giây audio).
    """
    from src.rag.evaluate import KY_TU_MOI_GIAY, uoc_giay_doc

    assert KY_TU_MOI_GIAY == pytest.approx(20.1, abs=0.1)
    assert uoc_giay_doc("A" * 201) == pytest.approx(10.0, abs=0.1)
    assert uoc_giay_doc("") == 0.0


def test_co_do_doc_so_o_doan_co_bien_the():
    """Cờ đỏ tự động cho lớp RAG-130: nói một con số mà đoạn nguồn lại đổi theo phiên bản."""
    from src.rag.evaluate import doc_so_khong_kem_dieu_kien

    assert doc_so_khong_kem_dieu_kien("Bơm 240 KPA.", co_bien_the=True) is True
    # Cùng câu, đoạn KHÔNG có biến thể -> nói số là bình thường.
    assert doc_so_khong_kem_dieu_kien("Bơm 240 KPA.", co_bien_the=False) is False
    # Có biến thể nhưng không đọc số -> đúng thứ S1 sinh ra để làm.
    assert doc_so_khong_kem_dieu_kien("Xem nhãn trên khung cửa.", co_bien_the=True) is False


def test_so_tran_khong_tinh_la_doc_so():
    """"hàng ghế thứ hai" không phải đại lượng tài xế sẽ làm theo."""
    from src.rag.evaluate import doc_so_khong_kem_dieu_kien

    assert doc_so_khong_kem_dieu_kien("Ở hàng ghế thứ 2.", co_bien_the=True) is False


# --- Task 6: nhãn tầng phần cứng ---------------------------------------------


def test_metrics_ghi_tang_phan_cung():
    """Số không có tầng phần cứng là số không diễn giải được.

    877 ms trên dGPU và 17.441 ms trên CPU (SPIKE-003) đều được gọi là "một lượt SLM".
    Và nhãn "edge" một chữ còn tệ hơn: `product_brief.md:135` chốt baseline edge là
    *CPU profile* vì nhóm **không có Jetson** — đó là ràng buộc của nhóm, không phải
    mô tả xe. Xe thật có bộ tăng tốc. Nên mỗi run phải nói rõ nó đo trên tầng nào.
    """
    from src.rag.evaluate import HARDWARE_TIERS, EvalMetrics

    assert HARDWARE_TIERS == ("cpu", "igpu", "dgpu", "npu")

    m = EvalMetrics(
        min_score=0.8,
        min_overlap=0.6,
        positives=40,
        negatives=20,
        recall_at_k=1.0,
        grounded_rate=1.0,
        hallucination_rate=0.0,
        citation_validity=1.0,
        hardware_tier="igpu",
    )
    assert m.hardware_tier == "igpu"
    assert "igpu" in m.model_dump_json()


def test_tang_mac_dinh_la_cpu_khong_phai_tang_manh_nhat():
    """Mặc định phải là tầng **yếu nhất**: quên khai báo thì báo cáo dưới mức thật,
    không phải trên mức thật. Nhầm theo hướng lạc quan là nhầm nguy hiểm."""
    from src.rag.evaluate import EvalMetrics

    m = EvalMetrics(
        min_score=0.8, min_overlap=0.6, positives=1, negatives=0,
        recall_at_k=1.0, grounded_rate=1.0, hallucination_rate=0.0, citation_validity=1.0,
    )
    assert m.hardware_tier == "cpu"


# --- Cot "trung cau hoi", cham tay (Task 7) ---------------------------------
#
# Diem cham tay la thu DUY NHAT trong bo do khong tai sinh duoc bang cach chay lai
# CLI. Nen phep doc no phai chat hon moi phep doc khac o day.


def _viet_diem(tmp_path: Path, *rows: dict) -> Path:
    import json

    p = tmp_path / "graded_speech.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def test_diem_cham_gan_vao_cau_noi_cu_thi_bi_coi_la_qua_han(tmp_path: Path):
    """Đổi tầng nói xong mà điểm cũ vẫn được cộng thì bộ đo đang báo cáo một con số
    **về một hệ thống khác**.

    Đây là cách hỏng đáng sợ nhất của baseline chấm tay: nó không gây lỗi, nó chỉ
    lặng lẽ trở nên sai. Nên khoá nó bằng test chứ không bằng lời dặn.
    """
    from src.rag.evaluate import doc_diem_cham_tay

    duong = _viet_diem(
        tmp_path,
        {"case_id": "A", "spoken": "Câu cũ.", "answers_question": "yes", "graded_by": "human"},
        {"case_id": "B", "spoken": "Câu giữ nguyên.", "answers_question": "no", "graded_by": "human"},
    )
    diem = doc_diem_cham_tay(duong, {"A": "Câu MỚI sau khi sửa luật.", "B": "Câu giữ nguyên."})

    assert diem.khop == {"B": "no"}
    assert diem.qua_han == ["A"]


def test_ca_chua_cham_khong_bi_coi_la_khong_trung(tmp_path: Path):
    """Chưa chấm ≠ chấm trượt. Gộp hai thứ đó là tự hạ điểm mình bằng dữ liệu thiếu —
    và tự hạ điểm cũng là báo cáo sai, không phải 'thận trọng'."""
    from src.rag.evaluate import doc_diem_cham_tay, ty_le_trung_cau_hoi

    duong = _viet_diem(tmp_path, {"case_id": "A", "spoken": "x", "answers_question": "yes", "graded_by": "human"})
    diem = doc_diem_cham_tay(duong, {"A": "x", "B": "y"})

    assert diem.chua_cham == ["B"]
    ty_le = ty_le_trung_cau_hoi(diem)
    assert ty_le.mau_so == 1  # chi tinh tren ca DA cham
    assert ty_le.trung == 1.0


def test_mot_phan_khong_duoc_tinh_thanh_trung(tmp_path: Path):
    """Hai tỷ lệ, không phải một. `trung` là câu dùng được ngay; `trung_hoac_mot_phan`
    là câu đi đúng hướng. Gộp lại thì mọi câu mở bài đúng chủ đề đều thành 'trúng',
    và cột này hết đo được thứ nó sinh ra để đo."""
    from src.rag.evaluate import doc_diem_cham_tay, ty_le_trung_cau_hoi

    duong = _viet_diem(
        tmp_path,
        {"case_id": "A", "spoken": "x", "answers_question": "yes", "graded_by": "human"},
        {"case_id": "B", "spoken": "y", "answers_question": "partial", "graded_by": "human"},
        {"case_id": "C", "spoken": "z", "answers_question": "no", "graded_by": "auto"},
    )
    ty_le = ty_le_trung_cau_hoi(doc_diem_cham_tay(duong, {"A": "x", "B": "y", "C": "z"}))

    assert ty_le.trung == pytest.approx(1 / 3)
    assert ty_le.trung_hoac_mot_phan == pytest.approx(2 / 3)


def test_diem_that_khop_voi_run_da_sinh_ra_no():
    """Chạy trên file thật trong repo, không phải fixture.

    File điểm nằm ở `eval/datasets/` chứ không nằm trong run dir vì run dir là bất
    biến; đổi lại, nó phải tự chứng minh là còn khớp với tầng nói hiện tại.
    """
    import json

    from src.rag.evaluate import doc_diem_cham_tay, ty_le_trung_cau_hoi

    duong = Path("eval/datasets/manual/v1/graded_speech.jsonl")
    noi_theo_ca = {
        r["case_id"]: r["spoken"]
        for r in (json.loads(x) for x in duong.read_text(encoding="utf-8").splitlines() if x.strip())
    }
    diem = doc_diem_cham_tay(duong, noi_theo_ca)

    assert diem.qua_han == []
    assert len(diem.khop) == 40
    assert ty_le_trung_cau_hoi(diem).trung == pytest.approx(0.30)

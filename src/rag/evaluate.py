"""Đo chất lượng RAG ở tầng retrieval — không cần LLM.

Tách tầng là điểm mấu chốt: chất lượng truy hồi đo được ngay, độc lập với hai
việc đang tắc là ADR-005 chưa chốt model và latency end-to-end 35–43 giây.

Nhãn `section` lấy từ `manifest.json` của chính sổ tay nên **ngoại sinh**; nhãn
`page` do `page_mapper` dựng nên nội sinh, vì thế chỉ tiêu chính là `section`,
còn độ đúng số trang được đo riêng bằng `citation_validity`.

Toàn bộ case được truy hồi **một lần** với ngưỡng 0, sau đó ngưỡng mới được áp
khi chấm. Nhờ vậy quét ngưỡng để hiệu chỉnh không phải embed lại.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from src.rag.embed import Embedder
from src.rag.models import Evidence
from src.rag.retrieve import Retriever
from src.rag.textnorm import lexical_overlap

#: Ngưỡng chấp nhận của task, theo acceptance criteria.
GROUNDED_TARGET = 0.90
HALLUCINATION_TARGET = 0.05


class EvalCase(BaseModel):
    """Một case trong cases.jsonl."""

    case_id: str
    input_text: str
    supported: bool
    section: str | None = None
    page: int | None = None
    negative_kind: str | None = None


class CaseOutcome(BaseModel):
    """Kết quả chấm một case ở một ngưỡng cụ thể."""

    case_id: str
    supported: bool
    answered: bool
    section_hit: bool
    page_hit: bool
    top_score: float
    passed: bool
    #: Hai cot do KENH NOI (Task 5). `None` khi case khong tra loi duoc — khong co gi
    #: de noi thi khong co gi de do, va ghi 0.0 se lam p95 dep len mot cach gia.
    spoken_chars: int | None = None
    spoken_audio_seconds: float | None = None
    spoken_has_number_without_condition: bool | None = None
    #: Nguyen van cau tai xe NGHE, va nhanh nao cua `speech_policy` sinh ra no. Hai
    #: truong nay khong phai chi so — chung la du lieu de NGUOI cham cot "trung cau
    #: hoi", va de doc lai duoc mot run cu ma khong phai chay lai.
    spoken_text: str | None = None
    spoken_reason: str | None = None


class Thresholds(BaseModel):
    """Cặp ngưỡng của grader lai: điểm cosine và độ trùng từ vựng."""

    min_score: float
    min_overlap: float


#: Bốn tầng phần cứng, xếp theo năng lực tăng dần. Thay cho nhãn "edge" một chữ.
#:
#: `docs/product_brief.md:135` chốt *"Không có Jetson; CPU profile trong Docker là
#: baseline edge mô phỏng"* — dòng đó nằm trong mục **ràng buộc của nhóm** (chúng ta
#: không có phần cứng), không phải mô tả xe. Cockpit SoC đời nay đều có bộ tăng tốc,
#: nên "edge" một mình không nói được gì: 877 ms trên dGPU và 17.441 ms trên CPU
#: (SPIKE-003) đều là "một lượt SLM trên edge".
#:
#: `igpu` là tầng gần cockpit phổ thông nhất trong ba tầng ADR-016 — nó chia sẻ băng
#: thông bộ nhớ với CPU, đúng như SoC tích hợp. `dgpu` (máy demo) **lạc quan hơn** xe;
#: `npu` chưa ai đo, để sẵn tên cho khỏi phải đổi schema sau.
HARDWARE_TIERS: tuple[str, ...] = ("cpu", "igpu", "dgpu", "npu")


class EvalMetrics(BaseModel):
    """Các chỉ số tổng hợp cho một cặp ngưỡng."""

    min_score: float
    min_overlap: float
    positives: int
    negatives: int
    recall_at_k: float
    grounded_rate: float
    hallucination_rate: float
    citation_validity: float
    #: Mặc định là tầng **yếu nhất** có chủ đích: quên khai báo thì báo cáo dưới mức
    #: thật, không phải trên mức thật. Nhầm theo hướng lạc quan là nhầm nguy hiểm.
    hardware_tier: str = "cpu"

    @property
    def passed(self) -> bool:
        return (
            self.grounded_rate > GROUNDED_TARGET
            and self.hallucination_rate < HALLUCINATION_TARGET
            and self.citation_validity >= 1.0
        )


@dataclass
class EvalContext:
    """Retriever, embedder và kết quả truy hồi thô đã cache."""

    retriever: Retriever
    embedder: Embedder
    probes: dict[str, list[Evidence]] = field(default_factory=dict)

    def probe(self, cases: list[EvalCase]) -> None:
        """Truy hồi thô mọi case **một lần**; quét ngưỡng sau đó không embed lại."""
        self.probes = {
            case.case_id: self.retriever.retrieve(case.input_text, self.embedder) for case in cases
        }


def load_cases(path: Path) -> list[EvalCase]:
    """Đọc cases.jsonl sang EvalCase."""
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        expected = raw["expected"]
        citation = expected.get("citation") or {}
        cases.append(
            EvalCase(
                case_id=raw["case_id"],
                input_text=raw["input_text"],
                supported=bool(expected.get("supported")),
                section=citation.get("section"),
                page=citation.get("page"),
                negative_kind=expected.get("negative_kind"),
            )
        )
    return cases


def _score_case(
    case: EvalCase, evidence: list[Evidence], thresholds: Thresholds, selector: object | None = None
) -> CaseOutcome:
    """Chấm một case sau khi áp cả hai ngưỡng của grader lai."""
    kept = [
        item
        for item in evidence
        if item.score >= thresholds.min_score
        and lexical_overlap(case.input_text, item.text) >= thresholds.min_overlap
    ]
    section_hit = any(item.section == case.section for item in kept)
    page_hit = case.page is None or any(
        item.section == case.section and item.page == case.page for item in kept
    )
    answered = bool(kept)
    passed = (answered and section_hit and page_hit) if case.supported else not answered

    # Do chinh cau ma tai xe se NGHE, di qua dung tang quyet dinh cua san pham
    # (`speech_policy` + loi moi), khong phai mot ban tai tao trong bo do.
    #
    # NGAN SACH phai bang ngan sach that.
    #
    # Ban truoc goi `chon_cau_de_noi` KHONG truyen `max_chars`, tuc dung tron
    # `MAX_SPOKEN_CHARS`; con `compose_node` thi tru cau dan ra truoc
    # (`MAX_SPOKEN_CHARS - len(cau_dan) - 1`). Bo do vi the cham mot cau THAN dai hon
    # cau tai xe that su nghe - cau dan p50 37 ky tu (do tren 182 cau hoi, 27/08).
    #
    # Toi doan chieu lech se la "san pham te hon bo do bao". Do ra thi NGUOC:
    #
    #     bo do dung tron 240      -> cham toi cau tra loi 50,0%  (trung 20)
    #     bo do dung ngan sach that -> cham toi cau tra loi 65,0%  (trung 26)
    #
    # Ngan sach chat hon cho ket qua TOT hon, vi bo chon lay tron cau: them ngan sach
    # nghia la them mot cau nua vao chuoi noi, va cau them vao thuong khong phai cau
    # mang dap an - no chi lam loang. Bo do cu vi the vua sai chieu vua che mat dieu ay.
    #
    # Phat hien khi do SP-3 muc 1; xem WORKLOG 28/08 cho ca bon run.
    noi = ""
    ly_do = None
    co_bien_the = False
    if kept:
        from src.agents.nodes.speech_policy import (
            MAX_SPOKEN_CHARS,
            cau_dan_tu_cau_hoi,
            cau_noi_hoan_chinh,
            chon_cau_de_noi,
        )

        top = kept[0]
        co_bien_the = bool(getattr(top, "has_variant_condition", False))
        ngan_sach = max(60, MAX_SPOKEN_CHARS - len(cau_dan_tu_cau_hoi(case.input_text)) - 1)
        ke_hoach = chon_cau_de_noi(top, case.input_text, max_chars=ngan_sach, selector=selector)
        noi = cau_noi_hoan_chinh(ke_hoach, max_chars=ngan_sach)
        ly_do = ke_hoach.reason

    return CaseOutcome(
        case_id=case.case_id,
        supported=case.supported,
        answered=answered,
        section_hit=section_hit,
        page_hit=page_hit,
        top_score=evidence[0].score if evidence else 0.0,
        passed=passed,
        spoken_chars=len(noi) if answered else None,
        spoken_audio_seconds=uoc_giay_doc(noi) if answered else None,
        spoken_has_number_without_condition=(
            doc_so_khong_kem_dieu_kien(noi, co_bien_the=co_bien_the) if answered else None
        ),
        spoken_text=noi if answered else None,
        spoken_reason=ly_do,
    )


def citation_validity(context: EvalContext) -> float:
    """Tỷ lệ evidence resolve đúng về chunk store — cổng cứng 100% của scoring.py.

    Bắt được lệch giữa FAISS index và SQLite chunk store: nếu index cũ hơn store,
    `chunk_id` vẫn tra ra chunk nhưng `section`/`page` sẽ không khớp.
    """
    emitted = [item for evidence in context.probes.values() for item in evidence]
    if not emitted:
        return 1.0
    valid = sum(
        1
        for item in emitted
        if (chunk := context.retriever.chunk(item.chunk_id)) is not None
        and chunk.section == item.section
        and chunk.page == item.page
    )
    return valid / len(emitted)


def score_at(
    context: EvalContext,
    cases: list[EvalCase],
    thresholds: Thresholds,
    *,
    hardware_tier: str = "cpu",
    selector: object | None = None,
) -> tuple[EvalMetrics, list[CaseOutcome]]:
    """Tính bộ chỉ số ở một cặp ngưỡng cho trước.

    `selector` bật đường S2 (SLM chọn câu). Mặc định `None` = S1 thuần, cùng lý do
    `slm_enabled` mặc định `False`: đường không cần hạ tầng phải là đường mặc định.
    """
    outcomes = [_score_case(case, context.probes[case.case_id], thresholds, selector) for case in cases]
    positives = [o for o in outcomes if o.supported]
    negatives = [o for o in outcomes if not o.supported]
    recall = sum(1 for o in positives if o.section_hit) / len(positives) if positives else 0.0
    grounded = sum(1 for o in positives if o.passed) / len(positives) if positives else 0.0
    hallucinated = sum(1 for o in negatives if o.answered) / len(negatives) if negatives else 0.0
    metrics = EvalMetrics(
        min_score=thresholds.min_score,
        min_overlap=thresholds.min_overlap,
        positives=len(positives),
        negatives=len(negatives),
        recall_at_k=recall,
        grounded_rate=grounded,
        hallucination_rate=hallucinated,
        citation_validity=citation_validity(context),
        hardware_tier=hardware_tier,
    )
    return metrics, outcomes


#: Lưới quét: điểm cosine trong vùng thang thật của e5, độ trùng từ vựng 0–1.
_SCORE_GRID = [0.840 + step * 0.004 for step in range(9)]
_OVERLAP_GRID = [0.0, 0.40, 0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]


def calibrate(context: EvalContext, cases: list[EvalCase]) -> list[EvalMetrics]:
    """Quét lưới hai chiều để chọn cặp ngưỡng cho grader lai.

    ADR-003: *"Score threshold không hardcode từ trực giác; hiệu chỉnh bằng
    positive/negative eval."* Thang điểm của e5 rất nén (positive ~0,88–0,91,
    negative ~0,78–0,87) nên chênh 0,005 đã đổi kết quả.
    """
    return [
        score_at(context, cases, Thresholds(min_score=score, min_overlap=overlap))[0]
        for score in _SCORE_GRID
        for overlap in _OVERLAP_GRID
    ]


def best_threshold(sweep: list[EvalMetrics]) -> EvalMetrics:
    """Chọn cặp ngưỡng đạt cả hai mục tiêu; nếu không có thì lấy đánh đổi tốt nhất."""
    passing = [metrics for metrics in sweep if metrics.passed]
    pool = passing or sweep
    return max(pool, key=lambda m: (m.grounded_rate - m.hallucination_rate, -m.min_score))

# --- Đo kênh NÓI (Task 5) -----------------------------------------------------
#
# Bảng của ADR-015 chấm câu **hiển thị** ("câu gây hiểu lầm / 40"). Kênh nói có hai
# thất bại riêng mà bảng đó không nhìn thấy:
#
#   1. dài quá nghe không nổi — đo được 65,6 giây trước Task 1;
#   2. đọc số của một đoạn phụ thuộc phiên bản — đúng lớp lỗi RAG-130.
#
# Cả hai đo được bằng máy, nên chúng thành cột chứ không thành ý kiến.

#: Tốc độ đọc đo thật trên giọng `vi_VN-piper` ngày 13/08: 1.181 ký tự → 65,6 giây.
#:
#: Ước từ số ký tự chứ **không** gọi Piper trong eval: máy CI và máy chưa tải model
#: vẫn phải chạy được bộ đo này. Sai số của phép ước nhỏ hơn nhiều so với khoảng cách
#: giữa 65 giây và 10 giây — thứ mà cột này sinh ra để phân biệt.
KY_TU_MOI_GIAY = 20.1

#: Số **kèm đơn vị đo**. Giữ đồng bộ với `_NUMBER_WITH_UNIT` của
#: `src/agents/nodes/speech_policy.py` — hai chỗ lệch nhau thì bộ đo sẽ báo xanh cho
#: đúng thứ tầng nói vừa để lọt.
_SO_KEM_DON_VI = re.compile(r"\d+\s*(kPa|KPA|psi|PSI|bar|độ|hướng|mm|km/h|V|A)", re.IGNORECASE)


def uoc_giay_doc(text: str) -> float:
    """Số giây audio ước tính cho một chuỗi."""
    return round(len(text) / KY_TU_MOI_GIAY, 2) if text else 0.0


#: Điểm chấm tay cho **kênh nói** — cột duy nhất trong bộ đo không tái sinh được
#: bằng cách chạy lại CLI.
#:
#: Nằm ở `eval/datasets/` chứ không nằm trong run dir: run dir là **bất biến**, còn
#: điểm chấm là ground truth dùng lại cho mọi run sau. Đổi lại, nó phải tự chứng minh
#: là còn khớp — xem `doc_diem_cham_tay`.
#:
#: Giữ tính so sánh được với bảng ADR-015, vốn cũng chấm tay từng câu trong
#: `graded.jsonl` của `eval/results/spike-003/`.
DIEM_CHAM_TAY = Path("eval/datasets/manual/v1/graded_speech.jsonl")

_MUC_CHAM = ("yes", "partial", "no")


@dataclass(frozen=True)
class DiemChamTay:
    """Điểm đã chấm, tách theo mức độ còn dùng được.

    Ba nhóm này **không** được gộp: `qua_han` là dữ liệu sai, `chua_cham` là dữ liệu
    thiếu. Gộp cái nào vào `khop` cũng ra một con số nói về hệ thống khác.
    """

    khop: dict[str, str]
    qua_han: list[str]
    chua_cham: list[str]


@dataclass(frozen=True)
class TyLeTrungCauHoi:
    """Hai tỷ lệ, cố ý không gộp thành một.

    `trung` là câu tài xế dùng được ngay. `trung_hoac_mot_phan` là câu đi đúng hướng
    nhưng còn phải nghe tiếp. Báo cáo mỗi con số sau sẽ biến mọi câu mở bài đúng chủ
    đề thành "trúng" — và đó chính là thứ tầng nói hiện tại làm nhiều nhất.
    """

    trung: float
    trung_hoac_mot_phan: float
    mau_so: int


def doc_diem_cham_tay(path: Path, noi_theo_ca: dict[str, str]) -> DiemChamTay:
    """Đọc điểm chấm tay và **đối chiếu với câu nói của run hiện tại**.

    `noi_theo_ca` là `case_id -> spoken` mà run vừa sinh ra. Điểm chỉ được tính khi
    chuỗi khớp nguyên văn: chấm là chấm *một câu cụ thể*, không phải chấm một case id.

    Đây là cách hỏng đáng sợ nhất của baseline chấm tay — siết `MAX_SPOKEN_CHARS`,
    sửa luật chọn câu, hay ingest lại index đều làm câu nói đổi mà không làm gì đổ vỡ.
    Điểm cũ khi đó vẫn cộng vào bình thường và bộ đo báo một con số về phiên bản đã
    chết. Nên chỗ này so chuỗi, và cái lệch đi vào `qua_han` chứ không bị bỏ qua.
    """
    khop: dict[str, str] = {}
    qua_han: list[str] = []
    da_doc: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        case_id = row["case_id"]
        da_doc.add(case_id)
        muc = row.get("answers_question")
        if muc not in _MUC_CHAM:
            continue
        if noi_theo_ca.get(case_id) != row.get("spoken"):
            qua_han.append(case_id)
            continue
        khop[case_id] = muc
    chua_cham = [cid for cid in noi_theo_ca if cid not in khop and cid not in qua_han]
    return DiemChamTay(khop=khop, qua_han=sorted(qua_han), chua_cham=sorted(chua_cham))


def ty_le_trung_cau_hoi(diem: DiemChamTay) -> TyLeTrungCauHoi:
    """Tỷ lệ tính **trên các ca đã chấm**, không trên toàn bộ ca.

    Ca chưa chấm là dữ liệu thiếu, không phải ca trượt. Cho nó vào mẫu số là tự hạ
    điểm bằng chỗ mình chưa làm — cũng là báo cáo sai, chỉ lệch theo hướng khiêm tốn.
    """
    mau_so = len(diem.khop)
    if not mau_so:
        return TyLeTrungCauHoi(trung=0.0, trung_hoac_mot_phan=0.0, mau_so=0)
    trung = sum(1 for m in diem.khop.values() if m == "yes")
    mot_phan = sum(1 for m in diem.khop.values() if m == "partial")
    return TyLeTrungCauHoi(
        trung=trung / mau_so,
        trung_hoac_mot_phan=(trung + mot_phan) / mau_so,
        mau_so=mau_so,
    )


def doc_so_khong_kem_dieu_kien(spoken: str, *, co_bien_the: bool) -> bool:
    """Câu nói có đọc một đại lượng của đoạn phụ thuộc phiên bản không.

    Đây là cờ đỏ **tự động** cho lớp RAG-130: sổ tay là bảng áp suất theo bản ECO/PLUS
    và loại pin SDI/CATL; nói một con số ra mà không kèm điều kiện là để tài xế bơm sai.

    Đoạn không có biến thể thì nói số là bình thường — cột này không phạt điều đó.
    """
    if not co_bien_the:
        return False
    return bool(_SO_KEM_DON_VI.search(spoken))

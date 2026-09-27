"""CLI ingest và tra cứu sổ tay.

Ingest là thao tác quản trị chạy ngoài luồng, không phải endpoint công khai:
`technical_spec.md` đẩy manual ingestion sang P1/CLI.

    python -m src.rag.cli ingest
    python -m src.rag.cli verify
    python -m src.rag.cli query "Cách khởi tạo lại cửa sổ điện?"
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from src.rag import store
from src.rag.embed import E5Embedder
from src.rag.evaluate import (
    DIEM_CHAM_TAY,
    HARDWARE_TIERS,
    EvalContext,
    Thresholds,
    best_threshold,
    calibrate,
    doc_diem_cham_tay,
    load_cases,
    score_at,
    ty_le_trung_cau_hoi,
)
from src.rag.ingest.pipeline import (
    DB_FILE,
    MANIFEST_FILE,
    MIN_PAGE_EXACT_RATE,
    MIN_SECTION_RATE,
    ingest,
)
from src.rag.models import PageSource
from src.rag.retrieve import RetrievalConfig, load_retriever
from src.rag.speech_grade import DAP_AN_KHOA, cham_run, doc_dap_an_khoa

DEFAULT_MANUAL = Path("data/manuals/vf9_2026_vi")
DEFAULT_INDEX = Path("data/rag/vf9_2026_vi")
DEFAULT_CASES = Path("eval/datasets/manual/v1/cases.jsonl")
RESULTS_ROOT = Path("eval/results/rag")


def _cmd_ingest(args: argparse.Namespace) -> int:
    report = ingest(args.manual, args.index, E5Embedder())
    print(f"documents         : {report.documents}")
    print(f"chunks            : {report.chunks}")
    print(f"vectors           : {report.vectors}")
    print(f"edition           : {report.edition}")
    print(f"index_checksum    : {report.index_checksum}")
    print(f"page exact        : {report.page_exact_rate:.1%}")
    print(f"page fuzzy        : {report.page_fuzzy} chunk")
    print(f"page derived      : {report.page_derived} chunk  <- muon trang cua chunk truoc")
    print(f"page resolved     : {report.page_resolved_rate:.1%}  (gate >= {MIN_PAGE_EXACT_RATE:.0%})")
    print(
        f"muc kem nhat      : {report.worst_section_rate:.1%}  {report.worst_section_name}"
        f"  (gate >= {MIN_SECTION_RATE:.0%})"
    )
    if not report.page_gate_passed:
        print("FAIL: page mapping duoi nguong, kiem tra HTML va PDF co lech phien ban khong")
        return 1
    print("OK")
    return 0


def _list_low_confidence(index_dir: Path) -> None:
    """Liệt kê chunk không tự xác định được trang — chúng dễ sinh citation sai nhất."""
    connection = store.connect(index_dir / DB_FILE)
    try:
        chunks = store.load_chunks(connection)
    finally:
        connection.close()
    suspect = [c for c in chunks if c.page_source in (PageSource.FUZZY, PageSource.DERIVED)]
    if not suspect:
        print("\nMoi chunk deu khop trang chinh xac.")
        return
    print(f"\n{len(suspect)} chunk khong khop chinh xac:")
    for chunk in suspect:
        print(f"  [{chunk.page_source.value:7}] tr.{chunk.page:<3} {chunk.section[:48]:48} {chunk.chunk_id}")


def _cmd_verify(args: argparse.Namespace) -> int:
    manifest_path = args.index / MANIFEST_FILE
    if not manifest_path.exists():
        print(f"FAIL: chua ingest, khong thay {manifest_path}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key, value in manifest.items():
        print(f"{key:24}: {value}")

    _list_low_confidence(args.index)

    passed = (
        manifest.get("page_resolved_rate", manifest["page_exact_rate"]) >= MIN_PAGE_EXACT_RATE
        and manifest.get("worst_section_rate", 1.0) >= MIN_SECTION_RATE
    )
    print("OK" if passed else "FAIL: page mapping duoi nguong")
    return 0 if passed else 1


def _cmd_query(args: argparse.Namespace) -> int:
    retriever = load_retriever(args.index, RetrievalConfig(min_score=args.min_score))
    evidence = retriever.search(args.text, E5Embedder())
    if not evidence:
        print("(khong du evidence -> grounded refusal)")
        return 0
    for item in evidence:
        print(f"[{item.score:.3f}] {item.section} — trang {item.page}  ({item.chunk_id})")
        print(f"        {item.text[:150]}...")
    return 0


def _make_context(args: argparse.Namespace) -> EvalContext:
    retriever = load_retriever(args.index, RetrievalConfig(min_score=0.0, min_overlap=0.0))
    return EvalContext(retriever=retriever, embedder=E5Embedder())


def _cmd_calibrate(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    context = _make_context(args)
    context.probe(cases)
    sweep = calibrate(context, cases)
    print(f"{'score':>7}{'overlap':>9}{'recall@k':>10}{'grounded':>10}{'halluc':>9}  ket qua")
    for metrics in sweep:
        flag = "PASS" if metrics.passed else ""
        print(
            f"{metrics.min_score:7.3f}{metrics.min_overlap:9.2f}{metrics.recall_at_k:10.1%}"
            f"{metrics.grounded_rate:10.1%}{metrics.hallucination_rate:9.1%}  {flag}"
        )
    best = best_threshold(sweep)
    print(f"\nDe xuat: rag_min_score = {best.min_score:.3f} | rag_min_overlap = {best.min_overlap:.2f}")
    print(f"  grounded {best.grounded_rate:.1%} | halluc {best.hallucination_rate:.1%} | recall {best.recall_at_k:.1%}")
    return 0


def viet_manifest(
    out_dir: Path,
    *,
    run_id: str,
    dataset: str,
    index_dir: str,
    metrics_keys: list[str],
) -> None:
    """Ghi `manifest.json` — provenance của một run, tách khỏi `metrics.json`.

    `CLAUDE.md` §"Evidence is the product" chốt một run gồm ba file; suite này
    tới 28/08 mới ghi hai. Chỗ thiếu không vô hại: `GET /metrics/eval-snapshot`
    lấy provenance từ đây, và run nào không có thì dashboard buộc phải hiện `—`.

    `graded_by` là trường load-bearing chứ không phải nhãn trang trí: dashboard
    dùng nó để **không trộn** ba nguồn chấm (đáp án khoá / người chấm tay /
    judge) vào cùng một con số. Suite này chấm bằng đáp án khoá ngoại sinh
    (`eval/datasets/manual/v1/answer_keys.jsonl`, dựng từ sổ tay VF9), nên hằng.
    """
    manifest = {
        "run_id": run_id,
        "suite": "rag",
        "dataset": dataset,
        "index_dir": index_dir,
        "graded_by": "dap_an_khoa",
        "metrics_keys": metrics_keys,
        "note": "Cham bang dap an khoa (answer_keys.jsonl), khong qua ASR.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _cmd_eval(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    context = _make_context(args)
    context.probe(cases)
    thresholds = Thresholds(min_score=args.min_score, min_overlap=args.min_overlap)
    # S2 chi bat khi duoc goi ten. Mac dinh la S1 thuan — cung ly do slm_enabled
    # mac dinh False: duong khong can ha tang phai la duong mac dinh.
    selector = None
    if getattr(args, "slm_select", False):
        from src.agents.slm import QwenSentenceSelector
        from src.config import get_settings

        st = get_settings()
        selector = QwenSentenceSelector(st.slm_endpoint, st.slm_model_id, st.slm_timeout_s)
        print(f"S2 BAT: {st.slm_endpoint}  (model do llama-server dang nap quyet dinh,"
              f" khong phai slm_model_id={st.slm_model_id!r})")
    metrics, outcomes = score_at(
        context, cases, thresholds, hardware_tier=args.hardware_tier, selector=selector
    )

    print(f"tang phan cung   : {metrics.hardware_tier}   (mac dinh cpu — khai bao sai la bao cao sai)")
    print(f"cases            : {metrics.positives} positive + {metrics.negatives} negative")
    print(f"min_score        : {metrics.min_score:.3f}   min_overlap: {metrics.min_overlap:.2f}")
    print(f"recall@k         : {metrics.recall_at_k:.1%}")
    print(f"grounded_rate    : {metrics.grounded_rate:.1%}   (muc tieu > 90%)")
    print(f"hallucination    : {metrics.hallucination_rate:.1%}   (muc tieu < 5%)")
    print(f"citation_validity: {metrics.citation_validity:.1%}   (cong cung = 100%)")

    # --- Kenh NOI (Task 5) ---
    # Bang cua ADR-015 cham cau HIEN THI; hai dong duoi cham cau tai xe NGHE. Khong co
    # chung thi thay doi o tang noi khong so sanh duoc voi bat ky moc nao.
    giay = [o.spoken_audio_seconds for o in outcomes if o.spoken_audio_seconds is not None]
    co_do = [o for o in outcomes if o.spoken_has_number_without_condition]
    if giay:
        xep = sorted(giay)
        p50 = xep[len(xep) // 2]
        p95 = xep[max(0, int(len(xep) * 0.95) - 1)]
        print(f"\nnoi p50/p95      : {p50:.1f} s / {p95:.1f} s   (cong: p95 <= 12 s)")
        print(f"doc so o doan bien the: {len(co_do)}/{len(giay)}   (cong: 0)")
        for o in co_do:
            print(f"  CO DO {o.case_id}")

    # --- Cot "cham toi cau tra loi" (dap an khoa) ---
    #
    # Cot nay thay cot cham tay o cho cham tay yeu nhat: ranh gioi mot-phan / khong-trung
    # doi nguoi cham phai biet doan so tay con gi o phia sau. Khoa quyet dinh dieu do MOT
    # LAN, truoc khi nhin dau ra, nen moi phien ban duoc do bang cung mot thuoc.
    if DAP_AN_KHOA.exists():
        khoa = doc_dap_an_khoa()
        cham = cham_run([json.loads(o.model_dump_json()) for o in outcomes], khoa)
        d = cham["dem"]
        print(
            f"\ncham toi cau tra loi: {cham['trung']:.1%}"
            f"   (tren {cham['mau_so']} ca, theo dap an khoa)"
        )
        print(f"  + mot phan     : {cham['trung_hoac_mot_phan']:.1%}"
              f"   [trung {d['yes']} / mot phan {d['partial']} / khong {d['no']}]")
        if cham["thieu_khoa"]:
            print(f"  THIEU KHOA     : {', '.join(cham['thieu_khoa'])}")
        # --- S3: mo phong tai xe noi "nghe tiep" toi khi nghe duoc cau tra loi ---
        print(f"  voi S3 toi duoc: {cham['s3_ty_le_toi_duoc']:.1%}"
              f"   [{cham['s3_luot_p50']} luot p50, {cham['s3_luot_p95']} p95"
              f" | {cham['s3_giay_p50']:.0f}s p50, {cham['s3_giay_p95']:.0f}s p95]")
        if cham["s3_khong_toi_duoc"]:
            print(f"  S3 KHONG CUU   : {', '.join(cham['s3_khong_toi_duoc'])}")

    # --- Cot "trung cau hoi" (Task 7, cham tay) ---
    #
    # Hai dong tren do cau noi CO AN TOAN va CO NGAN khong. Dong nay do no CO ICH
    # khong. Ba thu do được phep nguoc chieu nhau: cau khung fail-closed ghi diem cao
    # o hai cot dau va 'no' o cot nay, va do la so lieu that.
    if DIEM_CHAM_TAY.exists():
        # Cung tap voi `speech_to_grade.jsonl` ben duoi: chi ca `supported` va co tra
        # loi. Ca negative ma lo tra loi (RAG-209) khong bao gio nam trong khung cham,
        # nen tinh no vao day thi moi run deu bao "chua cham" mot ca vinh vien khong
        # cham duoc — mot canh bao luon sang la mot canh bao khong ai doc.
        noi_theo_ca = {o.case_id: o.spoken_text for o in outcomes if o.supported and o.answered and o.spoken_text}
        diem = doc_diem_cham_tay(DIEM_CHAM_TAY, noi_theo_ca)
        ty_le = ty_le_trung_cau_hoi(diem)
        print(f"\ntrung cau hoi    : {ty_le.trung:.1%}   (tren {ty_le.mau_so} ca da cham tay)")
        print(f"  + mot phan     : {ty_le.trung_hoac_mot_phan:.1%}")
        if diem.qua_han:
            # KHONG lam FAIL: bo do van dung, chi la baseline da cu. Nhung phai on ao
            # — mot baseline cu am tham la mot con so noi ve he thong khac.
            print(f"  QUA HAN        : {len(diem.qua_han)} ca co diem nhung cau noi da doi")
            print(f"                   {', '.join(diem.qua_han)}")
            print("                   -> cham lai bang speech_to_grade.jsonl cua run nay")
        if diem.chua_cham:
            print(f"  chua cham      : {len(diem.chua_cham)} ca ({', '.join(diem.chua_cham[:5])}...)")

    failed = [outcome for outcome in outcomes if not outcome.passed]
    if failed:
        print(f"\n{len(failed)} case truot:")
        for outcome in failed:
            reason = "khong tra loi" if outcome.supported and not outcome.answered else (
                "sai section/page" if outcome.supported else "dang le phai tu choi"
            )
            print(f"  {outcome.case_id}  top={outcome.top_score:.3f}  {reason}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(metrics.model_dump_json(indent=2), encoding="utf-8")
    viet_manifest(
        out_dir,
        run_id=stamp,
        dataset=str(args.cases),
        index_dir=str(args.index),
        metrics_keys=sorted(metrics.model_dump().keys()),
    )
    (out_dir / "case_results.jsonl").write_text(
        "\n".join(outcome.model_dump_json() for outcome in outcomes), encoding="utf-8"
    )
    # --- Khung cham tay cot "trung cau hoi" (Task 7) ---
    #
    # Cham TAY chu khong tu dong: bang cua ADR-015 cung cham tay tung cau trong
    # `graded.jsonl`, va so sanh duoc voi no la ly do cot nay ton tai.
    #
    # Nhung khong bat nguoi cham nhung ca khong can phan doan: `variant_fallback` la
    # cau khung "Thong tin nay thay doi theo phien ban xe..." — no khong tra loi cau
    # hoi, va do la DUNG THIET KE (fail-closed), khong phai mot phan doan.
    khung = []
    for outcome in outcomes:
        if not outcome.supported or not outcome.answered:
            continue
        tu_dong = "no" if outcome.spoken_reason == "variant_fallback" else None
        khung.append(
            {
                "case_id": outcome.case_id,
                "input_text": next(c.input_text for c in cases if c.case_id == outcome.case_id),
                "spoken": outcome.spoken_text,
                "reason": outcome.spoken_reason,
                "answers_question": tu_dong,  # None = CAN NGUOI CHAM
                "graded_by": "auto" if tu_dong else None,
            }
        )
    (out_dir / "speech_to_grade.jsonl").write_text(
        "\n".join(json.dumps(k, ensure_ascii=False) for k in khung), encoding="utf-8"
    )
    can_cham = sum(1 for k in khung if k["answers_question"] is None)
    print(f"\ncham tay         : {can_cham}/{len(khung)} ca can nguoi (con lai tu dong 'no' vi fail-closed)")

    print(f"\nket qua ghi tai {out_dir}")
    print("PASS" if metrics.passed else "FAIL")
    return 0 if metrics.passed else 1


def build_parser() -> argparse.ArgumentParser:
    """Khai báo CLI; tách riêng để test được mà không phải chạy tiến trình."""
    parser = argparse.ArgumentParser(prog="src.rag.cli", description="Ingest va tra cuu so tay xe")
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL, help="thu muc so tay nguon")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="thu muc artifact")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="dung chunk store va FAISS index").set_defaults(handler=_cmd_ingest)
    sub.add_parser("verify", help="in manifest va kiem tra cong chat luong").set_defaults(handler=_cmd_verify)

    query = sub.add_parser("query", help="tra cuu thu mot cau hoi")
    query.add_argument("text", help="cau hoi tieng Viet")
    query.add_argument("--min-score", type=float, default=RetrievalConfig().min_score)
    query.set_defaults(handler=_cmd_query)

    for name, help_text, handler in (
        ("eval", "cham bo case va ghi ket qua", _cmd_eval),
        ("calibrate", "quet nguong de chon rag_min_score", _cmd_calibrate),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--cases", type=Path, default=DEFAULT_CASES)
        command.add_argument("--min-score", type=float, default=RetrievalConfig().min_score)
        command.add_argument("--min-overlap", type=float, default=RetrievalConfig().min_overlap)
        # Mac dinh tang YEU NHAT: quen khai bao thi bao cao duoi muc that, khong phai
        # tren muc that. Xem HARDWARE_TIERS trong evaluate.py.
        command.add_argument("--hardware-tier", choices=HARDWARE_TIERS, default="cpu")
        command.add_argument(
            "--slm-select",
            action="store_true",
            help="bat S2: SLM chon cau (can llama-server o slm_endpoint)",
        )
        command.set_defaults(handler=handler)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())

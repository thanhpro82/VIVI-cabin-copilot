"""Đo intent accuracy và tool-exact của router, ghi ra thư mục run bất biến.

Vì sao không dùng test pass làm bằng chứng: `CLAUDE.md` ghi rõ "Passing unit
tests are not model-quality evidence. Claims must trace to a run ID." Con số
trong README/WORKLOG phải kèm run-id sinh ra nó.

Chạy: `.\\.venv\\Scripts\\python.exe -m src.agents.eval`
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agents.router import DeterministicControlRouter

DEFAULT_DATASET = Path("eval/datasets/agent/v3/cases.jsonl")
DEFAULT_RESULTS_ROOT = Path("eval/results/agent-intent")

#: 60 câu hỏi sổ tay do workstream RAG soạn cho mục đích khác. Chúng không thừa
#: hưởng giả định nào của router — đó chính là lý do dùng chúng để đo định tuyến.
DEFAULT_MANUAL_DATASET = Path("eval/datasets/manual/v1/cases.jsonl")
DEFAULT_ROUTING_RESULTS_ROOT = Path("eval/results/agent-routing")


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score_case(router: DeterministicControlRouter, case: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected"]
    decision = router.route(case["input_text"])
    predicted_tools = (
        [{"tool": step.tool, "args": step.args} for step in decision.candidate_plan.steps]
        if decision.candidate_plan is not None
        else []
    )
    disposition_ok = decision.disposition == expected["disposition"]
    intent_ok = disposition_ok and decision.intent == expected["intent"]
    return {
        "case_id": case["case_id"],
        "domain": case.get("domain", "unknown"),
        "input_text": case["input_text"],
        "disposition_ok": disposition_ok,
        "intent_ok": intent_ok,
        "tool_exact": predicted_tools == expected.get("tools", []),
        "predicted": {
            "disposition": decision.disposition,
            "intent": decision.intent,
            "reason": decision.reason,
            "tools": predicted_tools,
        },
        "expected": expected,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_domain: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "intent_ok": 0, "tool_exact": 0})
    for row in rows:
        bucket = by_domain[row["domain"]]
        bucket["total"] += 1
        bucket["intent_ok"] += int(row["intent_ok"])
        bucket["tool_exact"] += int(row["tool_exact"])
    total = len(rows) or 1
    return {
        "total": len(rows),
        "intent_accuracy": sum(r["intent_ok"] for r in rows) / total,
        "disposition_accuracy": sum(r["disposition_ok"] for r in rows) / total,
        "tool_exact": sum(r["tool_exact"] for r in rows) / total,
        "by_domain": {k: dict(v) for k, v in sorted(by_domain.items())},
    }


def run_eval(dataset: Path, results_root: Path, run_id: str | None = None) -> Path:
    """Chạy toàn bộ dataset và ghi một thư mục run mới.

    Thư mục là **bất biến**: `mkdir(exist_ok=False)` và mở file bằng mode `"x"`.
    Muốn số mới thì chạy lại, không sửa file cũ.
    """
    cases = load_cases(dataset)
    router = DeterministicControlRouter()
    rows = [score_case(router, case) for case in cases]
    metrics = _aggregate(rows)

    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "run_id": run_id,
                "dataset": str(dataset).replace("\\", "/"),
                "case_count": len(cases),
                "router": "DeterministicControlRouter",
                "slm_used": False,
                "note": "Router luật, không gọi model. Không phải bằng chứng chất lượng SLM.",
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir


def score_routing_case(router: DeterministicControlRouter, case: dict[str, Any]) -> dict[str, Any]:
    """Xếp một câu hỏi sổ tay vào đúng một rổ theo router xử lý nó ra sao."""
    decision = router.route(case["input_text"])
    if decision.disposition == "control":
        bucket = "to_control"
    elif decision.disposition == "offer":
        bucket = "to_offer"
    elif decision.disposition == "denied":
        bucket = "denied"
    elif decision.intent == "manual_query":
        bucket = "to_rag"
    elif decision.intent != "none":
        bucket = "clarify_as_command"
    else:
        bucket = "other"
    return {
        "case_id": case["case_id"],
        "input_text": case["input_text"],
        "bucket": bucket,
        "disposition": decision.disposition,
        "intent": decision.intent,
        "reason": decision.reason,
    }


def run_routing_eval(
    manual_dataset: Path,
    command_dataset: Path,
    results_root: Path,
    run_id: str | None = None,
) -> Path:
    """Đo hai chiều: câu hỏi có tới được RAG, và lệnh có bị nuốt thành câu hỏi.

    Hai dataset có nguồn gốc khác nhau và điều đó là cố ý: `manual/v1` do workstream
    RAG soạn cho mục đích khác, nên nó không thừa hưởng giả định nào của router.
    """
    router = DeterministicControlRouter()
    manual_rows = [score_routing_case(router, case) for case in load_cases(manual_dataset)]
    command_rows = [score_case(router, case) for case in load_cases(command_dataset)]

    n_manual = len(manual_rows) or 1
    n_command = len(command_rows) or 1
    buckets = Counter(row["bucket"] for row in manual_rows)
    metrics = {
        "question_total": len(manual_rows),
        "question_recall": buckets["to_rag"] / n_manual,
        "question_to_control": buckets["to_control"] / n_manual,
        "question_to_offer": buckets["to_offer"] / n_manual,
        "question_denied": buckets["denied"] / n_manual,
        "question_as_command_intent": buckets["clarify_as_command"] / n_manual,
        "question_buckets": dict(sorted(buckets.items())),
        "command_total": len(command_rows),
        "command_accuracy": sum(r["intent_ok"] for r in command_rows) / n_command,
        "command_tool_exact": sum(r["tool_exact"] for r in command_rows) / n_command,
        "command_to_manual": sum(
            1 for r in command_rows if r["expected"]["disposition"] == "control" and not r["disposition_ok"]
        )
        / n_command,
    }

    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in manual_rows:
            handle.write(json.dumps({"dataset": "manual/v1", **row}, ensure_ascii=False) + "\n")
        for row in command_rows:
            handle.write(json.dumps({"dataset": "agent/v3", **row}, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "run_id": run_id,
                "manual_dataset": str(manual_dataset).replace("\\", "/"),
                "command_dataset": str(command_dataset).replace("\\", "/"),
                "router": "DeterministicControlRouter",
                "slm_used": False,
                "note": (
                    "manual/v1 do workstream RAG soạn cho mục đích khác nên độc lập với router, "
                    "nhưng vẫn là người trong nhóm — không phải người dùng thật."
                ),
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir


DEFAULT_BAO_LOI_DATASET = Path("eval/datasets/agent/bao-loi-2408/cases.jsonl")
DEFAULT_BAO_LOI_RESULTS_ROOT = Path("eval/results/agent-bao-loi")

#: Ca `hong` **đã được xác nhận pass** và từ đó trở thành cổng hồi quy.
#:
#: Vì sao phải có file này (điều kiện approve #1 của review #302): nếu `di_lui` chỉ đọc
#: `trang_thai_2608 == "dung"` thì một ca vừa sửa xong mà tái hỏng chỉ **rụng khỏi**
#: `da_sua` — CI vẫn xanh. Tức bộ đo là bảng tiến độ, không phải regression suite: nó
#: đếm được lúc bug biến mất nhưng im lặng lúc bug quay lại.
#:
#: Mỗi mục ghi `run_id` + `commit` đã dùng để promote (điều kiện #3). Mốc gốc
#: `trang_thai_2608` nằm trong `cases.jsonl` và **không bao giờ** bị sửa; mọi thay đổi
#: baseline về sau chỉ được cộng thêm vào đây, có vết, xem lại được bằng `git log`.
DEFAULT_BAO_LOI_GATE = Path("eval/datasets/agent/bao-loi-2408/cong_hoi_quy.json")


def load_cong_hoi_quy(path: Path) -> dict[str, dict[str, Any]]:
    """Đọc bảng cổng hồi quy. Thiếu file = chưa promote ca nào, không phải lỗi."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("ca", {})


def ung_vien_promote(rows: list[dict[str, Any]], da_promote: set[str]) -> list[str]:
    """Ca `hong` nay pass, chưa promote, và **không** thuộc diện chờ quyết định.

    `can_quyet_dinh` bị loại ở đây là điều kiện approve #2 của review #302: nhãn mong đợi
    của chúng còn đang tranh chấp, nên khoá chúng thành cổng là khoá một câu trả lời chưa
    ai chốt. Chúng vẫn được chấm và vẫn nằm trong `da_sua`, chỉ không tự động thành gate.
    """
    return sorted(
        row["case_id"]
        for row in rows
        if row["trang_thai_2608"] == "hong"
        and row["dat"]
        and not row["can_quyet_dinh"]
        and row["case_id"] not in da_promote
    )


def run_bao_loi_eval(
    dataset: Path, results_root: Path, run_id: str | None = None, gate: Path | None = None
) -> Path:
    """Chạy bộ 77 ca dựng từ bảng báo lỗi 24/08 và ghi một run bất biến.

    Khác `run_eval` ở đúng một chỗ, và chỗ đó là lý do bộ này tồn tại riêng: mỗi ca
    mang sẵn `trang_thai_2608` — nó **đang** hỏng hay **đang** đúng trên `develop` @
    `bab0fc6`. Nên ngoài độ chính xác, run này còn nói ra **độ lệch so với mốc ấy**:

    - `di_lui` — ca ghi `dung` mà nay fail. **Phải bằng 0.** Một ca ở đây nghĩa là bản
      vá vừa làm hỏng thứ đang chạy được, và bộ này bắt được điều đó ngay cả khi
      `pytest` xanh (xem PR #268: một test xanh vẫn có thể đang bảo vệ hành vi sai).
    - `da_sua` — ca ghi `hong` mà nay pass. Đây là con số tiến độ thật của đợt sửa.

    ## Vòng đời một ca, và vì sao `da_sua` một mình là chưa đủ

    Điều kiện approve #1 của review #302. Đọc `di_lui` **chỉ** từ `trang_thai_2608` thì
    một ca vừa sửa xong mà tái hỏng chỉ rụng khỏi `da_sua` — CI vẫn xanh. Bộ đo khi ấy
    là bảng tiến độ chứ không phải regression suite: nó đếm được lúc bug biến mất nhưng
    im lặng đúng lúc bug quay lại.

    Nên có vòng đời ba bước, và bước thứ ba là bước có ích:

    1. `hong` — mốc gốc, đo trên `develop` @ `bab0fc6`. **Không bao giờ sửa lại.**
    2. `hong` + đang pass → hiện ra ở `da_sua` và ở `ung_vien_promote`.
    3. **promote** (`cong_hoi_quy.json`, ghi kèm `run_id` + `commit`) → từ đó ca ấy vào
       `di_lui` y như ca `dung`, tức tái hỏng là CI đỏ.

    Ca `can_quyet_dinh` đứng ngoài bước 3 cho tới khi có quyết định PM/PO ghi rõ — xem
    `ung_vien_promote`.

    Vì sao **không** nối 77 ca này vào `agent/v3`: `CLAUDE.md` ghi rõ v3 do chính người
    viết router soạn nên `intent_accuracy = 1.0000` của nó chỉ là **tripwire hồi quy**.
    Nhét 61 ca đang đỏ vào đó là phá luôn cái tripwire ấy — mất một thước đang dùng
    được để lấy một thước lẫn lộn hai mục đích.
    """
    cases = load_cases(dataset)
    da_promote = load_cong_hoi_quy(DEFAULT_BAO_LOI_GATE if gate is None else gate)
    router = DeterministicControlRouter()
    rows = [score_case(router, case) for case in cases]
    moc = {case["case_id"]: case.get("trang_thai_2608") for case in cases}
    quyet_dinh = {case["case_id"] for case in cases if case.get("can_quyet_dinh")}

    di_lui: list[str] = []
    da_sua: list[str] = []
    for row in rows:
        dat = row["disposition_ok"] and row["intent_ok"] and row["tool_exact"]
        row["dat"] = dat
        row["trang_thai_2608"] = moc[row["case_id"]]
        row["can_quyet_dinh"] = row["case_id"] in quyet_dinh
        row["trong_cong"] = moc[row["case_id"]] == "dung" or row["case_id"] in da_promote
        if row["trong_cong"] and not dat:
            di_lui.append(row["case_id"])
        elif moc[row["case_id"]] == "hong" and dat:
            da_sua.append(row["case_id"])

    metrics = _aggregate(rows)
    #: "Đạt" ở bộ này là **cả ba** cùng đúng (disposition + intent + tool_exact), chứ
    #: không phải `tool_exact` một mình: một ca `not_control` có `tools == []` nên
    #: `tool_exact` của nó đúng ngay cả khi router trả sai hẳn disposition.
    metrics["dat"] = sum(1 for row in rows if row["dat"])
    for row in rows:
        metrics["by_domain"][row["domain"]].setdefault("dat", 0)
        metrics["by_domain"][row["domain"]]["dat"] += int(row["dat"])
    metrics["di_lui"] = sorted(di_lui)
    metrics["da_sua"] = sorted(da_sua)
    # Ca tranh chấp vẫn được chấm và vẫn nằm trong `by_domain`, nhưng tách riêng ở đây
    # để không ai lấy chúng làm cổng khi nhãn còn chưa được chốt.
    metrics["can_quyet_dinh"] = sorted(quyet_dinh)
    metrics["cong_hoi_quy"] = sorted(da_promote)
    metrics["ung_vien_promote"] = ung_vien_promote(rows, set(da_promote))

    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "run_id": run_id,
                "dataset": str(dataset).replace("\\", "/"),
                "case_count": len(cases),
                "router": "DeterministicControlRouter",
                "slm_used": False,
                "moc": "develop @ bab0fc6, src/agents/router.py @ 6e0b523, đo 2026-08-25",
                # Ghi số ca đang trong cổng vào manifest chứ không chỉ vào metrics: đọc
                # một run cũ mà không biết cổng lúc ấy rộng bao nhiêu thì `di_lui == []`
                # của nó không nói lên điều gì.
                "cong_hoi_quy": str(DEFAULT_BAO_LOI_GATE if gate is None else gate).replace("\\", "/"),
                "cong_hoi_quy_so_ca": len(da_promote),
                "note": "Router luật, không gọi model. Không phải bằng chứng chất lượng SLM.",
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir


def promote_bao_loi(run_dir: Path, gate: Path, commit: str | None = None) -> list[str]:
    """Đưa ca `hong` đã pass trong `run_dir` vào cổng hồi quy. Trả về danh sách vừa thêm.

    Đọc từ một **run đã ghi** chứ không chấm lại tại chỗ, và đó là điều kiện approve #3:
    baseline chỉ được đổi bằng một bằng chứng có id, xem lại được. Chạy lại router ở đây
    thì `cong_hoi_quy.json` ghi một `run_id` không sinh ra chính nó.

    Idempotent: promote lại cùng run không đổi gì. Mục đã có **không** bị ghi đè — lần
    promote đầu tiên là lần đúng để trích dẫn.
    """
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    if metrics["di_lui"]:
        raise ValueError(f"run {run_dir.name} còn {len(metrics['di_lui'])} ca đi lùi; sửa xong rồi mới promote")

    goc = json.loads(gate.read_text(encoding="utf-8")) if gate.exists() else {"ca": {}}
    ca = goc.setdefault("ca", {})
    them = [cid for cid in metrics["ung_vien_promote"] if cid not in ca]
    for cid in them:
        ca[cid] = {"run_id": run_dir.name, "commit": commit, "promoted_at": datetime.now(UTC).strftime("%Y-%m-%d")}
    goc["mo_ta"] = (
        "Ca `hong` đã được xác nhận pass và từ đó là cổng hồi quy: tái hỏng thì `di_lui` "
        "khác rỗng và CI đỏ. Sinh bằng `--mode bao-loi --promote`; đừng sửa tay."
    )
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps(goc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return them


DEFAULT_DINH_TUYEN_DATASET = Path("eval/datasets/agent/dinh-tuyen-v1/cases.jsonl")


def run_dinh_tuyen_eval(
    dataset: Path,
    results_root: Path,
    classifier: Any,
    run_id: str | None = None,
) -> Path:
    """Đo phân loại 3 lớp (SP-1): router chạy trước (đường tắt), classifier chỉ nhận câu trượt.

    Ô `manual->control` là cổng cứng = 0 — nhưng eval GHI SỐ THẬT, không assert:
    thước phải trung thực, còn cổng là việc của người đọc metrics và của CI sau này.
    """
    router = DeterministicControlRouter()
    rows: list[dict[str, Any]] = []
    for case in load_cases(dataset):
        text = case["input_text"]
        quyet_dinh = router.route(text)
        if quyet_dinh.reason != "default_to_manual":
            # `clarify`/`denied` = router HIỂU là lệnh (đang hỏi tham số / chặn an
            # toàn) → control. `offer` giữ nhãn riêng: đó là "câu hỏi chạm luật
            # control, nêu ý định rồi hỏi lại" của ADR-011 — không chạm executor,
            # nên không được đếm vào ô nguy hiểm, cũng không được ăn gian thành đúng.
            predicted = {
                "control": "control",
                "clarify": "control",
                "denied": "control",
                "offer": "offer",
            }.get(quyet_dinh.disposition, "manual")
            duong = "duong_tat"
        else:
            try:
                # Cùng lưới an toàn với node slm_classify — số đo phải là số chạy thật.
                from src.agents.slm import ap_luoi_an_toan

                predicted = ap_luoi_an_toan(classifier.classify(text), text)
            except Exception as exc:  # noqa: BLE001 - eval phải chạy hết bộ, lỗi là dữ liệu
                predicted = f"error:{type(exc).__name__}"
            duong = "slm"
        rows.append(
            {
                "case_id": case["case_id"],
                "input_text": text,
                "expected": case["expected_route"],
                "predicted": predicted,
                "duong": duong,
                "router_reason": quyet_dinh.reason,
            }
        )

    ma_tran: dict[str, int] = {}
    for r in rows:
        khoa = f"{r['expected']}->{r['predicted']}"
        ma_tran[khoa] = ma_tran.get(khoa, 0) + 1
    metrics = {
        "n": len(rows),
        "duong_tat": sum(1 for r in rows if r["duong"] == "duong_tat"),
        "ma_tran": dict(sorted(ma_tran.items())),
        "dung": sum(1 for r in rows if r["expected"] == r["predicted"]),
        "cong_cung_manual_sang_control": ma_tran.get("manual->control", 0),
    }

    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "run_id": run_id,
                "dataset": str(dataset).replace("\\", "/"),
                "case_count": len(rows),
                "router": "DeterministicControlRouter (đường tắt) + classifier",
                "classifier": type(classifier).__name__,
                "note": (
                    "Bộ đo SP-1. Chưa có phần chitchat (SP-2 bổ sung) thì ma trận chỉ có 2 lớp "
                    "— mọi trích dẫn phải ghi rõ. Cổng cứng: manual->control = 0."
                ),
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir


DEFAULT_CHITCHAT_DATASET = Path("eval/datasets/agent/chitchat-v1/cases.jsonl")
DEFAULT_CHITCHAT_RESULTS_ROOT = Path("eval/results/chitchat")


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 1)


def run_chitchat_eval(
    dataset: Path, results_root: Path, classifier: Any, chitchat: Any, run_id: str | None = None
) -> Path:
    """Đo SP-2: classifier (qua đường tắt + lưới như sản phẩm) rồi generator + cổng
    cho MỌI ca được chấm chitchat — kể cả ca bẫy, để ô `bẫy→chitchat` là số thật."""
    import time

    from src.agents.nodes.chitchat_cong import qua_cong_chitchat
    from src.agents.router import DeterministicControlRouter
    from src.agents.slm import ap_luoi_an_toan

    router = DeterministicControlRouter()
    rows: list[dict[str, Any]] = []
    for case in load_cases(dataset):
        text = case["input_text"]
        qd = router.route(text)
        t0 = time.perf_counter()
        if qd.reason != "default_to_manual":
            predicted = {"control": "control", "clarify": "control", "denied": "control", "offer": "offer"}.get(
                qd.disposition, "manual"
            )
            duong = "duong_tat"
        else:
            try:
                predicted = ap_luoi_an_toan(classifier.classify(text), text)
            except Exception as exc:  # noqa: BLE001 - eval phải chạy hết bộ, lỗi là dữ liệu
                predicted = f"error:{type(exc).__name__}"
            duong = "slm"
        classify_ms = (time.perf_counter() - t0) * 1000
        row: dict[str, Any] = {
            "case_id": case["case_id"],
            "input_text": text,
            "expected": case["expected_route"],
            "expected_hanh_vi": case.get("expected_hanh_vi"),
            "predicted": predicted,
            "duong": duong,
            "router_reason": qd.reason,
            "classify_ms": round(classify_ms, 1),
            "source": case.get("source"),
        }
        if predicted == "chitchat":
            t1 = time.perf_counter()
            try:
                tho = chitchat.reply(text)
                phat, cong = qua_cong_chitchat(tho)
            except Exception as exc:  # noqa: BLE001
                tho, phat, cong = "", "", f"loi:{type(exc).__name__}"
            row.update(reply_tho=tho, reply_phat=phat, cong=cong, sinh_ms=round((time.perf_counter() - t1) * 1000, 1))
        rows.append(row)

    ma_tran: dict[str, int] = {}
    for r in rows:
        k = f"{r['expected']}->{r['predicted']}"
        ma_tran[k] = ma_tran.get(k, 0) + 1
    qua_cong: dict[str, int] = {}
    for r in rows:
        if "cong" in r:
            qua_cong[r["cong"]] = qua_cong.get(r["cong"], 0) + 1
    that = [r for r in rows if r["expected"] == "chitchat" and r["predicted"] == "chitchat"]

    def _tom(xs: list[float]) -> dict[str, float | None]:
        return {"p50": _pct(xs, 50), "p95": _pct(xs, 95)}

    metrics = {
        "n": len(rows),
        "ma_tran": dict(sorted(ma_tran.items())),
        "cong_cung_manual_sang_control": ma_tran.get("manual->control", 0),
        "cong_cung_bay_sang_chitchat": sum(
            v for k, v in ma_tran.items() if k.endswith("->chitchat") and not k.startswith("chitchat")
        ),
        "qua_cong": dict(sorted(qua_cong.items())),
        "n_chitchat_that": len(that),
        "do_tre_ms": {
            "classify": _tom([r["classify_ms"] for r in that]),
            "sinh": _tom([r["sinh_ms"] for r in that if "sinh_ms" in r]),
            "tong": _tom([r["classify_ms"] + r.get("sinh_ms", 0.0) for r in that]),
        },
    }
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as h:
        for r in rows:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as h:
        json.dump(metrics, h, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as h:
        json.dump(
            {
                "run_id": run_id,
                "dataset": str(dataset).replace("\\", "/"),
                "case_count": len(rows),
                "classifier": type(classifier).__name__,
                "chitchat": type(chitchat).__name__,
                "note": (
                    "SP-2. Hai cong cung: manual->control = 0 va bay->chitchat = 0. "
                    "Ca source=tu_viet la tripwire, khong phai thuoc."
                ),
            },
            h,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir


def _commit_hien_tai() -> str | None:
    """Commit đang đứng, để `cong_hoi_quy.json` ghi được nguồn gốc của mỗi lần promote.

    `None` khi không có git (tarball, container không copy `.git`). Ghi `null` là đúng
    hơn ghi một chuỗi đoán: một commit sai còn tệ hơn không có commit.
    """
    import subprocess

    try:
        ra = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return ra.stdout.strip() or None if ra.returncode == 0 else None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Đo router: intent, định tuyến, hoặc phân loại 3 lớp.")
    parser.add_argument(
        "--mode",
        choices=["intent", "routing", "dinh-tuyen", "chitchat", "bao-loi", "multiturn"],
        default="intent",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Sau khi chạy (chỉ --mode bao-loi): đưa ca hong nay pass vào cổng hồi quy, "
        "ghi kèm run_id và commit. Chỉ chạy trên develop đã xanh.",
    )
    args = parser.parse_args()

    if args.mode == "multiturn":
        run_dir = run_multiturn_eval(DEFAULT_MULTITURN_DATASET, DEFAULT_MULTITURN_RESULTS_ROOT)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        print(f"run_id={run_dir.name}")
        print(
            f"n={metrics['total']}  dat={metrics['dat']}  case_accuracy={metrics['case_accuracy']:.4f}  "
            f"luot={metrics['luot_dat']}/{metrics['tong_luot']}"
        )
        print(f"da_sua={len(metrics['da_sua'])} {metrics['da_sua']}")
        print(f"DI LUI={len(metrics['di_lui'])} {metrics['di_lui']}  (phai bang 0)")
        for nhom, o in sorted(metrics["by_nhom"].items()):
            print(f"  {nhom:18} dat {o['dat']}/{o['total']}")
        return

    if args.mode == "bao-loi":
        run_dir = run_bao_loi_eval(DEFAULT_BAO_LOI_DATASET, DEFAULT_BAO_LOI_RESULTS_ROOT)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        print(f"run_id={run_dir.name}")
        print(
            f"n={metrics['total']}  dat={metrics['dat']}  "
            f"disposition={metrics['disposition_accuracy']:.4f}  tool_exact={metrics['tool_exact']:.4f}"
        )
        print(f"da_sua={len(metrics['da_sua'])} {metrics['da_sua']}")
        print(f"DI LUI={len(metrics['di_lui'])} {metrics['di_lui']}  (phai bang 0)")
        print(f"cong_hoi_quy={len(metrics['cong_hoi_quy'])} ca dang duoc gac")
        print(f"ung_vien_promote={len(metrics['ung_vien_promote'])} {metrics['ung_vien_promote']}")
        print(f"can_quyet_dinh={len(metrics['can_quyet_dinh'])} (khong dung lam cong khi nhan chua chot)")
        for nhom, o in sorted(metrics["by_domain"].items()):
            print(f"  {nhom:16} dat {o['dat']}/{o['total']}")
        if args.promote:
            them = promote_bao_loi(run_dir, DEFAULT_BAO_LOI_GATE, commit=_commit_hien_tai())
            print(f"PROMOTE +{len(them)} {them} -> {DEFAULT_BAO_LOI_GATE}")
        return

    if args.mode == "chitchat":
        from src.agents.slm import QwenChitchat, QwenClassifier
        from src.config import get_settings

        settings = get_settings()
        classifier = QwenClassifier(settings.slm_endpoint, settings.slm_model_id, settings.slm_classify_timeout_s)
        chitchat = QwenChitchat(settings.slm_endpoint, settings.slm_model_id, settings.slm_chitchat_timeout_s)
        run_dir = run_chitchat_eval(DEFAULT_CHITCHAT_DATASET, DEFAULT_CHITCHAT_RESULTS_ROOT, classifier, chitchat)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        print(f"run_id={run_dir.name}")
        print(f"n={metrics['n']}  n_chitchat_that={metrics['n_chitchat_that']}")
        print(f"ma_tran={json.dumps(metrics['ma_tran'], ensure_ascii=False)}")
        print(
            f"CONG CUNG manual->control = {metrics['cong_cung_manual_sang_control']}  "
            f"bay->chitchat = {metrics['cong_cung_bay_sang_chitchat']}  (ca hai phai bang 0)"
        )
        print(f"qua_cong={json.dumps(metrics['qua_cong'], ensure_ascii=False)}")
        print(f"do_tre_ms={json.dumps(metrics['do_tre_ms'])}")
        return

    if args.mode == "dinh-tuyen":
        from src.agents.slm import QwenClassifier
        from src.config import get_settings

        settings = get_settings()
        classifier = QwenClassifier(settings.slm_endpoint, settings.slm_model_id, settings.slm_classify_timeout_s)
        run_dir = run_dinh_tuyen_eval(DEFAULT_DINH_TUYEN_DATASET, DEFAULT_ROUTING_RESULTS_ROOT, classifier)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        print(f"run_id={run_dir.name}")
        print(f"n={metrics['n']}  duong_tat={metrics['duong_tat']}  dung={metrics['dung']}")
        print(f"ma_tran={json.dumps(metrics['ma_tran'], ensure_ascii=False)}")
        print(f"CONG CUNG manual->control = {metrics['cong_cung_manual_sang_control']} (phai bang 0)")
        loi = [k for k in metrics["ma_tran"] if "error:" in k]
        if loi:
            print(f"CANH BAO: co luot loi (server tat?): {loi}")
        return

    if args.mode == "routing":
        run_dir = run_routing_eval(DEFAULT_MANUAL_DATASET, DEFAULT_DATASET, DEFAULT_ROUTING_RESULTS_ROOT)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        print(f"run_id={run_dir.name}")
        print(
            f"question_recall={metrics['question_recall']:.4f}  "
            f"question_to_control={metrics['question_to_control']:.4f}  "
            f"question_denied={metrics['question_denied']:.4f}"
        )
        print(
            f"command_accuracy={metrics['command_accuracy']:.4f}  command_to_manual={metrics['command_to_manual']:.4f}"
        )
        return

    run_dir = run_eval(DEFAULT_DATASET, DEFAULT_RESULTS_ROOT)
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    print(f"run_id={run_dir.name}")
    print(
        f"intent_accuracy={metrics['intent_accuracy']:.4f}  "
        f"tool_exact={metrics['tool_exact']:.4f}  n={metrics['total']}"
    )


DEFAULT_MULTITURN_DATASET = Path("eval/datasets/agent/multiturn-v1/cases.jsonl")
DEFAULT_MULTITURN_RESULTS_ROOT = Path("eval/results/agent-multiturn")


def _tap_tool(plan: Any) -> set[tuple[str, str]]:
    """Tập `(tool, args)` của một plan, args tuần tự hoá để so được bằng `==`.

    So theo **tập** chứ không theo thứ tự là có chủ ý: thứ tự hai bước HVAC do bộ luật
    quyết định, không phải thứ tự tài xế nói ra, nên khoá thứ tự là khoá một chi tiết
    không thuộc về phép đo này (bài học của `tests/test_agents/test_ghep_hoi_lai.py`).
    """
    if plan is None:
        return set()
    return {(b.tool, json.dumps(b.args, ensure_ascii=False, sort_keys=True)) for b in plan.steps}


def _tap_tool_mong(tools: list[dict[str, Any]] | None) -> set[tuple[str, str]]:
    return {(t["tool"], json.dumps(t.get("args", {}), ensure_ascii=False, sort_keys=True)) for t in (tools or [])}


async def cham_ca_multiturn(case: dict[str, Any]) -> dict[str, Any]:
    """Chạy hết các lượt của một ca trên **một** state dùng chung, chấm từng lượt.

    Dùng `route_node` chứ không dựng cả graph: đa lượt ở repo này là chuyện của định
    tuyến + ngữ cảnh, và giữ ở mức node thì phép đo tất định, chạy trong mili-giây, và
    không phụ thuộc `slm_enabled` hay MQTT. Cùng cách driver `Phien` của #358.
    """
    from src.agents.nghe_tiep import con_nghe_tiep
    from src.agents.nodes.route import make_route_node

    node = make_route_node(DeterministicControlRouter())
    state: dict[str, Any] = {}
    luot_ra: list[dict[str, Any]] = []
    dat_ca = True

    for luot in case["turns"]:
        state["query"] = luot["input_text"]
        update = await node(state)
        state.update(update)

        mong = luot["expected"]
        ra_disposition = update.get("outcome")
        ra_reason = update.get("route_reason")
        tools_ra = _tap_tool(update.get("candidate_action_plan"))
        # `con_nghe_tiep` đọc đúng `outcome`/`route_reason` ở mức route_node cho hai giá
        # trị `clarify`/`not_control` (#364) — nhưng KHÔNG đúng cho `control`: outcome ở
        # mức này vẫn là chuỗi `"control"`, chưa phải `"completed"` (giá trị thật sau khi
        # `execute_node` chạy), nên dataset không được gán `mo_mic_ngan` cho lượt
        # `disposition: "control"` — xem README của `multiturn-v1`.
        ra_mo_mic_ngan = con_nghe_tiep(state)

        disposition_ok = ra_disposition == mong["disposition"]
        # `route_reason` chỉ chấm khi ca ghi rõ. Nó là chỗ phân biệt *"tôi không làm"*
        # với *"tôi không tra được"* — hai thứ cùng nhãn `not_control` mà khác hẳn nhau
        # với tài xế đang ngồi trong xe.
        reason_ok = "route_reason" not in mong or ra_reason == mong["route_reason"]
        # Chỉ chấm tool khi ca nêu; ca không nêu thì im lặng về tool, không ngầm đòi rỗng.
        tool_ok = "tools" not in mong or tools_ra == _tap_tool_mong(mong["tools"])
        mo_mic_ngan_ok = "mo_mic_ngan" not in mong or ra_mo_mic_ngan == mong["mo_mic_ngan"]
        dat_luot = disposition_ok and reason_ok and tool_ok and mo_mic_ngan_ok
        dat_ca = dat_ca and dat_luot

        luot_ra.append(
            {
                "input_text": luot["input_text"],
                "disposition": ra_disposition,
                "route_reason": ra_reason,
                "tools": sorted(t for t, _ in tools_ra),
                "mo_mic_ngan": ra_mo_mic_ngan,
                "disposition_ok": disposition_ok,
                "reason_ok": reason_ok,
                "tool_ok": tool_ok,
                "mo_mic_ngan_ok": mo_mic_ngan_ok,
                "dat": dat_luot,
            }
        )

    return {
        "case_id": case["case_id"],
        "nhom": case["nhom"],
        "moc_2908": case.get("moc_2908"),
        "so_luot": len(luot_ra),
        "luot": luot_ra,
        "dat": dat_ca,
    }


def run_multiturn_eval(dataset: Path, results_root: Path, run_id: str | None = None) -> Path:
    """Chạy bộ đa lượt và ghi một run bất biến.

    Hai con số phải đọc cùng nhau, và cái thứ hai mới là cái khó:

    - `da_sua` — ca ghi `hong` mà nay pass. Tiến độ.
    - `di_lui` — ca ghi `dung` mà nay fail. **Phải bằng 0.** Nhóm `an-toan` nằm hết ở đây,
      nên một cửa nhận câu trả lời mở quá rộng sẽ hiện ra ngay ở con số này chứ không
      chờ ai đó thử tay trong xe.
    """
    import asyncio

    cases = load_cases(dataset)
    rows = asyncio.run(_chay_het(cases))

    di_lui = sorted(r["case_id"] for r in rows if r["moc_2908"] == "dung" and not r["dat"])
    da_sua = sorted(r["case_id"] for r in rows if r["moc_2908"] == "hong" and r["dat"])

    theo_nhom: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "dat": 0})
    for r in rows:
        theo_nhom[r["nhom"]]["total"] += 1
        theo_nhom[r["nhom"]]["dat"] += int(r["dat"])

    tong_luot = sum(r["so_luot"] for r in rows)
    metrics = {
        "total": len(rows),
        "dat": sum(1 for r in rows if r["dat"]),
        "case_accuracy": round(sum(1 for r in rows if r["dat"]) / len(rows), 4) if rows else 0.0,
        "tong_luot": tong_luot,
        "luot_dat": sum(1 for r in rows for lt in r["luot"] if lt["dat"]),
        "di_lui": di_lui,
        "da_sua": da_sua,
        "by_nhom": {k: dict(v) for k, v in sorted(theo_nhom.items())},
    }

    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "run_id": run_id,
                "dataset": str(dataset).replace("\\", "/"),
                "case_count": len(cases),
                "turn_count": tong_luot,
                "router": "DeterministicControlRouter + route_node",
                "slm_used": False,
                "moc": "develop @ ddfa4b7, đo 2026-08-29",
                "note": "Đa lượt trên một state dùng chung. Router luật, không gọi model.",
            },
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    return run_dir


async def _chay_het(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [await cham_ca_multiturn(case) for case in cases]


if __name__ == "__main__":
    main()

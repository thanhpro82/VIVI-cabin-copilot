"""Runner sinh bằng chứng. Thư mục kết quả bất biến — đó là điểm quan trọng nhất."""

import json

import pytest

from src.agents.eval import load_cases, run_eval, run_routing_eval, score_case, score_routing_case
from src.agents.router import DeterministicControlRouter

CASE = {
    "case_id": "T-001",
    "domain": "hvac",
    "input_text": "Đặt điều hòa 24 độ",
    "expected": {
        "disposition": "control",
        "intent": "hvac_temperature",
        "tools": [{"tool": "set_hvac_temperature", "args": {"temperature_c": 24}}],
    },
}


def _write_dataset(tmp_path, cases):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    return path


def test_load_cases_reads_jsonl(tmp_path):
    assert len(load_cases(_write_dataset(tmp_path, [CASE, CASE]))) == 2


def test_score_case_marks_full_match():
    scored = score_case(DeterministicControlRouter(), CASE)
    assert scored["disposition_ok"] is True
    assert scored["intent_ok"] is True
    assert scored["tool_exact"] is True


def test_score_case_marks_wrong_args_as_not_exact():
    wrong = json.loads(json.dumps(CASE))
    wrong["expected"]["tools"][0]["args"]["temperature_c"] = 30
    scored = score_case(DeterministicControlRouter(), wrong)
    assert scored["disposition_ok"] is True
    assert scored["tool_exact"] is False


def test_run_eval_writes_immutable_run_directory(tmp_path):
    dataset = _write_dataset(tmp_path, [CASE])
    run_dir = run_eval(dataset, tmp_path / "results")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["total"] == 1
    assert metrics["intent_accuracy"] == 1.0
    assert metrics["tool_exact"] == 1.0
    assert (run_dir / "case_results.jsonl").exists()
    assert (run_dir / "manifest.json").exists()


def test_run_eval_refuses_to_overwrite_an_existing_run(tmp_path):
    dataset = _write_dataset(tmp_path, [CASE])
    run_dir = run_eval(dataset, tmp_path / "results")
    with pytest.raises(FileExistsError):
        run_eval(dataset, tmp_path / "results", run_id=run_dir.name)


def test_metrics_break_down_by_domain(tmp_path):
    dataset = _write_dataset(tmp_path, [CASE])
    run_dir = run_eval(dataset, tmp_path / "results")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["by_domain"]["hvac"]["total"] == 1


# --- ADR-011: đo định tuyến bằng dataset của workstream RAG ---

MANUAL_CASE = {"case_id": "M-001", "input_text": "Cách khởi tạo lại cửa sổ điện?"}
COMMAND_CASE = {
    "case_id": "T-001",
    "domain": "hvac",
    "input_text": "Đặt điều hòa 24 độ",
    "expected": {
        "disposition": "control",
        "intent": "hvac_temperature",
        "tools": [{"tool": "set_hvac_temperature", "args": {"temperature_c": 24}}],
    },
}


def _write_manual(tmp_path):
    path = tmp_path / "manual.jsonl"
    path.write_text(json.dumps(MANUAL_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_routing_case_bucketed_to_rag():
    scored = score_routing_case(DeterministicControlRouter(), MANUAL_CASE)
    assert scored["bucket"] == "to_rag"


def test_routing_case_bucketed_when_question_becomes_command():
    scored = score_routing_case(DeterministicControlRouter(), {"case_id": "M-002", "input_text": "Bật điều hòa"})
    assert scored["bucket"] == "to_control"


def test_run_routing_eval_reports_six_metrics(tmp_path):
    run_dir = run_routing_eval(_write_manual(tmp_path), _write_dataset(tmp_path, [COMMAND_CASE]), tmp_path / "results")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    for key in (
        "question_recall",
        "question_to_control",
        "question_denied",
        "question_as_command_intent",
        "command_accuracy",
        "command_to_manual",
    ):
        assert key in metrics
    assert metrics["question_recall"] == 1.0
    assert metrics["question_to_control"] == 0.0
    assert metrics["command_accuracy"] == 1.0


def test_routing_eval_refuses_to_overwrite(tmp_path):
    manual = _write_manual(tmp_path)
    command = _write_dataset(tmp_path, [COMMAND_CASE])
    run_dir = run_routing_eval(manual, command, tmp_path / "results")
    with pytest.raises(FileExistsError):
        run_routing_eval(manual, command, tmp_path / "results", run_id=run_dir.name)

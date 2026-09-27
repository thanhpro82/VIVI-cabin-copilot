"""Eval định tuyến: đường tắt chạy trước, ma trận đầy đủ, cổng cứng manual→control=0."""

import json
from pathlib import Path

from src.agents.eval import run_dinh_tuyen_eval


class ClassifierLuonControl:
    def classify(self, normalized_text: str) -> str:
        return "control"


def _viet_dataset(tmp_path: Path) -> Path:
    cases = [
        {"case_id": "T1", "input_text": "bật điều hòa", "expected_route": "control", "source": "t"},
        {"case_id": "T2", "input_text": "Nóng quá trời hôm nay ha", "expected_route": "chitchat", "source": "t"},
        # Câu manual nhưng TRƯỢT luật router (không có "là gì/thế nào"...) — phải
        # tới classifier. Kiểm bằng: router.route(text).reason == "default_to_manual".
        {"case_id": "T3", "input_text": "Xe kêu lạch cạch ở bánh sau", "expected_route": "manual", "source": "t"},
    ]
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    return p


def test_duong_tat_khong_goi_classifier_va_ma_tran_day_du(tmp_path):
    run_dir = run_dinh_tuyen_eval(_viet_dataset(tmp_path), tmp_path / "results", ClassifierLuonControl())
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    # T1 khớp luật router → đường tắt, đúng control mà KHÔNG qua classifier.
    assert metrics["duong_tat"] >= 1
    # T2/T3 bị ClassifierLuonControl đẩy sang control → hai ô nhầm phải hiện ra.
    assert metrics["ma_tran"]["chitchat->control"] == 1
    assert metrics["ma_tran"]["manual->control"] == 1
    assert metrics["cong_cung_manual_sang_control"] == 1  # bộ đếm phải TRUNG THỰC, không che


def test_run_dir_du_ba_file(tmp_path):
    run_dir = run_dinh_tuyen_eval(_viet_dataset(tmp_path), tmp_path / "results", ClassifierLuonControl())
    for ten in ("manifest.json", "case_results.jsonl", "metrics.json"):
        assert (run_dir / ten).exists()

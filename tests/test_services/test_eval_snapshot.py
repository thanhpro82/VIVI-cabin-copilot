"""Đọc snapshot của run eval mới nhất — nguồn cho `GET /metrics/eval-snapshot`."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.services.eval_snapshot import doc_snapshot_moi_nhat


def _dung_run(root: Path, suite: str, run_id: str, *, metrics: dict, manifest: dict | None = None) -> Path:
    d = root / suite / run_id
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def test_lay_run_moi_nhat_theo_ten_thu_muc(tmp_path: Path) -> None:
    _dung_run(tmp_path, "rag", "20260101T000000Z", metrics={"grounded_rate": 0.5})
    _dung_run(tmp_path, "rag", "20260827T172523Z", metrics={"grounded_rate": 1.0})

    snap = doc_snapshot_moi_nhat("rag", tmp_path)

    assert snap is not None
    assert snap.run_id == "20260827T172523Z"
    assert snap.metrics["grounded_rate"] == 1.0


def test_run_thieu_manifest_van_doc_duoc_nhung_provenance_rong(tmp_path: Path) -> None:
    """Run cũ bất biến, không hồi tố — nên phải đọc được mà không có manifest."""
    _dung_run(tmp_path, "rag", "20260814T005140Z", metrics={"hallucination_rate": 0.05})

    snap = doc_snapshot_moi_nhat("rag", tmp_path)

    assert snap is not None
    assert snap.graded_by is None
    assert snap.dataset is None


def test_co_manifest_thi_lay_provenance_tu_do(tmp_path: Path) -> None:
    _dung_run(
        tmp_path,
        "rag",
        "20260828T101500Z",
        metrics={"grounded_rate": 1.0},
        manifest={"run_id": "20260828T101500Z", "graded_by": "dap_an_khoa", "dataset": "d.jsonl", "note": "n"},
    )

    snap = doc_snapshot_moi_nhat("rag", tmp_path)

    assert snap is not None
    assert snap.graded_by == "dap_an_khoa"
    assert snap.dataset == "d.jsonl"
    assert snap.note == "n"


def test_suite_chua_co_run_nao_tra_none(tmp_path: Path) -> None:
    assert doc_snapshot_moi_nhat("rag", tmp_path) is None


def test_run_do_dang_khong_che_mat_run_that(tmp_path: Path) -> None:
    """Thư mục thiếu `metrics.json` bị bỏ qua, không được nhận là run mới nhất.

    Ca này có thật: `_cmd_eval` mkdir trước rồi mới ghi file, nên một lần chạy bị
    ngắt để lại đúng thư mục rỗng mang tên mới nhất.
    """
    _dung_run(tmp_path, "rag", "20260101T000000Z", metrics={"grounded_rate": 0.5})
    (tmp_path / "rag" / "20260901T000000Z").mkdir(parents=True)

    snap = doc_snapshot_moi_nhat("rag", tmp_path)

    assert snap is not None
    assert snap.run_id == "20260101T000000Z"


def test_thieu_manifest_khong_ghi_canh_bao(tmp_path: Path, caplog) -> None:
    """Run cũ không có manifest là **bình thường**, không phải sự cố.

    Ghi WARNING cho ca thường gặp nhất là cách huấn luyện người ta ngó lơ log.
    """
    _dung_run(tmp_path, "rag", "20260814T005140Z", metrics={"grounded_rate": 1.0})

    with caplog.at_level(logging.WARNING, logger="src.services.eval_snapshot"):
        doc_snapshot_moi_nhat("rag", tmp_path)

    assert caplog.records == []


def test_file_hong_thi_van_canh_bao(tmp_path: Path, caplog) -> None:
    """Ngược lại: JSON vỡ là bất thường thật, phải nói ra."""
    d = tmp_path / "rag" / "20260814T005140Z"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text('{"grounded_rate": 1.0}', encoding="utf-8")
    (d / "manifest.json").write_text("{ khong phai json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="src.services.eval_snapshot"):
        snap = doc_snapshot_moi_nhat("rag", tmp_path)

    assert snap is not None
    assert len(caplog.records) == 1

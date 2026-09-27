"""`src/rag/cli.py` ghi manifest cho mỗi run — điều kiện để dashboard có provenance.

`CLAUDE.md` §"Evidence is the product" quy định một run gồm `manifest.json`,
`case_results.jsonl`, `metrics.json`. Suite `agent-intent` ghi đủ; suite `rag` thì
tới trước ngày 28/08 chưa run nào có manifest. Không có nó thì
`GET /metrics/eval-snapshot` không có gì để trả về ngoài mấy con số trần, và
nguyên tắc "mỗi ô số mang theo mã run + ai chấm" không thực hiện được.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.rag.cli import viet_manifest


def test_manifest_co_du_truong_provenance(tmp_path: Path) -> None:
    viet_manifest(
        tmp_path,
        run_id="20260828T101500Z",
        dataset="eval/datasets/manual/v1/cases.jsonl",
        index_dir="./data/rag/vf9_2026_vi",
        metrics_keys=["grounded_rate", "hallucination_rate"],
    )

    ghi = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert ghi["run_id"] == "20260828T101500Z"
    assert ghi["suite"] == "rag"
    assert ghi["dataset"] == "eval/datasets/manual/v1/cases.jsonl"
    assert ghi["index_dir"] == "./data/rag/vf9_2026_vi"
    assert ghi["metrics_keys"] == ["grounded_rate", "hallucination_rate"]
    assert "note" in ghi


def test_manifest_ghi_graded_by_ro_rang(tmp_path: Path) -> None:
    """`graded_by` là thứ dashboard dùng để không trộn ba nguồn chấm vào một số."""
    viet_manifest(tmp_path, run_id="r1", dataset="d", index_dir="i", metrics_keys=[])

    ghi = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert ghi["graded_by"] in {"dap_an_khoa", "nguoi_cham_tay", "judge"}

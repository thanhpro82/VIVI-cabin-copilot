"""`GET /api/v1/metrics/eval-snapshot` — nguồn số cho khối "Đánh giá offline".

Route này **chỉ đọc** artifact đã có trong `eval/results/`. Nó không chạy eval và
không ghi gì: thư mục run là bất biến, và một request HTTP không được phép sinh ra
bằng chứng.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import get_settings


@pytest.fixture
def results_root(tmp_path: Path, monkeypatch):
    """Trỏ settings sang một cây artifact giả — test không đọc `eval/results` thật."""
    root = tmp_path / "results"
    run = root / "rag" / "20260828T101500Z"
    run.mkdir(parents=True)
    (run / "metrics.json").write_text(
        json.dumps({"grounded_rate": 1.0, "hallucination_rate": 0.05, "citation_validity": 1.0}),
        encoding="utf-8",
    )
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260828T101500Z",
                "graded_by": "dap_an_khoa",
                "dataset": "cases.jsonl",
                "note": "n",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


async def test_tra_metrics_va_provenance(engineer_client, results_root):
    res = await engineer_client.get("/api/v1/metrics/eval-snapshot?suite=rag")

    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"data", "meta", "trace_id", "schema_version"}
    data = body["data"]
    assert data["suite"] == "rag"
    assert data["run_id"] == "20260828T101500Z"
    assert data["graded_by"] == "dap_an_khoa"
    assert data["metrics"]["hallucination_rate"] == 0.05


async def test_suite_ngoai_whitelist_bi_tu_choi(engineer_client, results_root):
    """`suite` đi thẳng vào đường dẫn, nên whitelist là hàng rào path-traversal."""
    res = await engineer_client.get("/api/v1/metrics/eval-snapshot?suite=../../etc")

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INPUT_INVALID"


async def test_suite_chua_co_run_tra_404(engineer_client, results_root):
    res = await engineer_client.get("/api/v1/metrics/eval-snapshot?suite=agent-intent")

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


async def test_goi_tran_khong_co_token_tra_401(client, results_root):
    res = await client.get("/api/v1/metrics/eval-snapshot?suite=rag")

    assert res.status_code == 401


async def test_driver_bi_tu_choi(driver_client, results_root):
    """Engineer-only, cùng hàng rào với `/traces` và `/metrics/summary`."""
    res = await driver_client.get("/api/v1/metrics/eval-snapshot?suite=rag")

    assert res.status_code == 403

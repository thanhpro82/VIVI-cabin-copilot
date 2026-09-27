# Dashboard kỹ sư — Phần A: bỏ mock, gắn số thật có run id — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khối "Đánh giá offline" trên dashboard kỹ sư ngừng hiển thị số hard-code và bắt đầu hiển thị số đọc từ một run eval thật, kèm mã run và ngày.

**Architecture:** Ba tầng, mỗi tầng một task. (1) `src/rag/cli.py` bắt đầu ghi `manifest.json` cho mỗi run — hiện các run `rag` không có file này nên không có provenance nào để trả về. (2) Một service đọc thuần `src/services/eval_snapshot.py` tìm run mới nhất của một suite và trả metrics + manifest; một route engineer-only phơi nó ra. (3) Frontend thay `OFFLINE_EVAL_SNAPSHOT` bằng lời gọi service, và mọi ô số mang theo run id — không có run id thì hiện `—`, không bao giờ hiện số cũ.

**Tech Stack:** Python 3.11.9, FastAPI, Pydantic v2, pytest (`asyncio_mode = "auto"`); Next.js 16, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-28-dashboard-ky-su-design.md` (§3 là phần plan này thực thi)

## Global Constraints

- Python là **3.11.9**, chạy qua `.\.venv\Scripts\python.exe`. Kiểm tra trước khi bắt đầu: `.\.venv\Scripts\python.exe -V` phải in `3.11.9`.
- Chạy test với `$env:MQTT_ENABLED="false"` — nếu không, mỗi `TestClient(app)` chờ broker 10 giây.
- Lint: `ruff check src/ tests/ scripts/` (đúng ba thư mục này, CI chạy đúng lệnh này). Line-length 120.
- **Không chạy `ruff format`** — tree đã lệch khỏi nó, format sẽ đụng 42 file không ai yêu cầu.
- Thư mục `eval/results/<suite>/<run-id>/` là **bất biến**. Không sửa run cũ, không hồi tố manifest cho chúng.
- ADR-029 giữ nguyên: không thêm field nào chứa transcript, citation text, hay câu nói của tài xế.
- Model API mới phải kế thừa `_Closed` (`extra="forbid"`) như mọi model trong `src/models/observability.py`.
- Lỗi HTTP dùng `ApiError` (`src/api/errors.py`), **không** dùng `HTTPException(detail=...)`.
- Frontend: mọi service có `mock.ts` + `real.ts` sau `index.ts`; mặc định là mock.

---

### Task 1: `src/rag/cli.py` ghi `manifest.json` cho mỗi run eval

Không run `rag` nào trong `eval/results/rag/` (cả 8 thư mục) có `manifest.json`, dù `CLAUDE.md` §"Evidence is the product" quy định một run gồm `manifest.json` + `case_results.jsonl` + `metrics.json`. Suite `agent-intent` thì có. Task này đóng khoảng lệch đó, và nó là điều kiện để Task 2 có provenance để đọc.

**Files:**
- Modify: `src/rag/cli.py` (quanh dòng 240-246, chỗ `out_dir.mkdir(...)`)
- Test: `tests/test_rag/test_cli_manifest.py` (create)

**Interfaces:**
- Consumes: không có (task đầu)
- Produces: `viet_manifest(out_dir: Path, *, run_id: str, dataset: str, index_dir: str, metrics_keys: list[str]) -> None` — ghi `out_dir/manifest.json`. Task 2 đọc file này.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_rag/test_cli_manifest.py`:

```python
"""`src/rag/cli.py` ghi manifest cho mỗi run — điều kiện để dashboard có provenance."""

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
    assert ghi["dataset"] == "eval/datasets/manual/v1/cases.jsonl"
    assert ghi["index_dir"] == "./data/rag/vf9_2026_vi"
    assert ghi["graded_by"] == "dap_an_khoa"
    assert ghi["metrics_keys"] == ["grounded_rate", "hallucination_rate"]
    assert "note" in ghi


def test_manifest_ghi_graded_by_ro_rang(tmp_path: Path) -> None:
    """`graded_by` là thứ dashboard dùng để không trộn ba nguồn chấm vào một số."""
    viet_manifest(
        tmp_path,
        run_id="r1",
        dataset="d",
        index_dir="i",
        metrics_keys=[],
    )
    ghi = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert ghi["graded_by"] in {"dap_an_khoa", "nguoi_cham_tay", "judge"}
```

- [ ] **Step 2: Chạy test để chắc nó trượt**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_rag/test_cli_manifest.py -q
```

Kỳ vọng: FAIL với `ImportError: cannot import name 'viet_manifest'`.

- [ ] **Step 3: Cài đặt tối thiểu**

Thêm vào `src/rag/cli.py`, ngay trên `_cmd_eval`:

```python
def viet_manifest(
    out_dir: Path,
    *,
    run_id: str,
    dataset: str,
    index_dir: str,
    metrics_keys: list[str],
) -> None:
    """Ghi `manifest.json` — provenance của một run, tách khỏi `metrics.json`.

    `graded_by` là trường load-bearing: dashboard dùng nó để KHÔNG trộn ba nguồn
    chấm (đáp án khoá / người chấm tay / judge) vào cùng một con số. Suite này
    chấm bằng đáp án khoá ngoại sinh (sổ tay VF9), nên hằng `dap_an_khoa`.
    """
    manifest = {
        "run_id": run_id,
        "suite": "rag",
        "dataset": dataset,
        "index_dir": index_dir,
        "graded_by": "dap_an_khoa",
        "metrics_keys": metrics_keys,
        "note": "Cham bang dap an khoa (eval/datasets/manual/v1/answer_keys.jsonl), khong qua ASR.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

Nếu `json` chưa được import ở đầu file thì thêm `import json`.

- [ ] **Step 4: Chạy test để chắc nó qua**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_rag/test_cli_manifest.py -q
```

Kỳ vọng: 2 passed.

- [ ] **Step 5: Gọi nó từ `_cmd_eval`**

Trong `src/rag/cli.py`, ngay sau dòng ghi `metrics.json` (hiện là dòng 243):

```python
    (out_dir / "metrics.json").write_text(metrics.model_dump_json(indent=2), encoding="utf-8")
    viet_manifest(
        out_dir,
        run_id=stamp,
        dataset=str(ctx.cases_path),
        index_dir=str(ctx.index_dir),
        metrics_keys=sorted(metrics.model_dump().keys()),
    )
```

Đọc `EvalContext` (`_make_context`, dòng 118) để lấy đúng tên hai thuộc tính đường dẫn; nếu tên khác `cases_path`/`index_dir` thì dùng tên thật, đừng đổi `EvalContext`.

- [ ] **Step 6: Chạy cả test rag để chắc không vỡ gì**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_rag/ -q
```

Kỳ vọng: tất cả pass (một vài ca có thể skip nếu thiếu FAISS index — skip là bình thường, xem `CLAUDE.md`).

- [ ] **Step 7: Lint và commit**

```bash
ruff check src/ tests/ scripts/
git add src/rag/cli.py tests/test_rag/test_cli_manifest.py
git commit -m "feat(rag-eval): moi run ghi manifest.json — provenance cho dashboard"
```

---

### Task 2: Service đọc snapshot eval

**Files:**
- Create: `src/services/eval_snapshot.py`
- Modify: `src/config.py` (thêm một setting)
- Test: `tests/test_services/test_eval_snapshot.py` (create)

**Interfaces:**
- Consumes: `manifest.json` do Task 1 ghi
- Produces:
  - `SUITES_CHO_PHEP: frozenset[str]` — `{"rag", "agent-intent"}`
  - `class EvalSnapshot` (dataclass): `suite: str`, `run_id: str`, `metrics: dict[str, float | int | str | None]`, `graded_by: str | None`, `dataset: str | None`, `note: str | None`
  - `doc_snapshot_moi_nhat(suite: str, results_root: Path) -> EvalSnapshot | None` — `None` khi suite chưa có run nào hoặc run mới nhất thiếu `metrics.json`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_services/test_eval_snapshot.py`:

```python
"""Đọc snapshot của run eval mới nhất — nguồn cho `GET /metrics/eval-snapshot`."""

from __future__ import annotations

import json
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


def test_run_thieu_metrics_bi_bo_qua(tmp_path: Path) -> None:
    """Thư mục rỗng không được tính là run mới nhất và che mất run thật."""
    _dung_run(tmp_path, "rag", "20260101T000000Z", metrics={"grounded_rate": 0.5})
    (tmp_path / "rag" / "20260901T000000Z").mkdir(parents=True)

    snap = doc_snapshot_moi_nhat("rag", tmp_path)

    assert snap is not None
    assert snap.run_id == "20260101T000000Z"
```

- [ ] **Step 2: Chạy test để chắc nó trượt**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_eval_snapshot.py -q
```

Kỳ vọng: FAIL với `ModuleNotFoundError: No module named 'src.services.eval_snapshot'`.

- [ ] **Step 3: Cài đặt**

Tạo `src/services/eval_snapshot.py`:

```python
"""Đọc snapshot của run eval mới nhất — nguồn cho `GET /api/v1/metrics/eval-snapshot`.

Đây là hàm **đọc thuần**. Nó không bao giờ chạy eval, không ghi gì, không đụng tới
thư mục run (chúng bất biến — xem `CLAUDE.md` §"Evidence is the product").

VÌ SAO CÓ `graded_by` — dashboard không được trộn ba nguồn chấm (đáp án khoá /
người chấm tay / judge) vào cùng một con số. Run cũ không có `manifest.json` nên
trường này là `None`, và UI phải hiện `—` chứ không được đoán.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Whitelist. Endpoint không nhận suite tuỳ ý — `suite` đi thẳng vào đường dẫn,
#: nên whitelist là hàng rào path-traversal, không chỉ là thẩm mỹ.
SUITES_CHO_PHEP: frozenset[str] = frozenset({"rag", "agent-intent"})


@dataclass(frozen=True)
class EvalSnapshot:
    suite: str
    run_id: str
    metrics: dict[str, object]
    graded_by: str | None = None
    dataset: str | None = None
    note: str | None = None


def _doc_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("khong doc duoc %s", path)
        return None


def doc_snapshot_moi_nhat(suite: str, results_root: Path) -> EvalSnapshot | None:
    """Run mới nhất của `suite`, hoặc `None` nếu chưa có run nào đọc được.

    "Mới nhất" = tên thư mục lớn nhất theo thứ tự chuỗi. Đúng vì mọi run id đều là
    dấu thời gian UTC dạng `YYYYMMDDThhmmssZ` — thứ tự chuỗi trùng thứ tự thời gian.

    Thư mục thiếu `metrics.json` bị **bỏ qua chứ không phải trả về rỗng**: một
    thư mục dở dang mang tên mới hơn sẽ che mất run thật cuối cùng.
    """
    suite_dir = results_root / suite
    if not suite_dir.is_dir():
        return None

    for run_dir in sorted((d for d in suite_dir.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True):
        metrics = _doc_json(run_dir / "metrics.json")
        if metrics is None:
            continue
        manifest = _doc_json(run_dir / "manifest.json") or {}
        return EvalSnapshot(
            suite=suite,
            run_id=run_dir.name,
            metrics=metrics,
            graded_by=manifest.get("graded_by"),
            dataset=manifest.get("dataset"),
            note=manifest.get("note"),
        )
    return None
```

- [ ] **Step 4: Chạy test để chắc nó qua**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_eval_snapshot.py -q
```

Kỳ vọng: 5 passed.

- [ ] **Step 5: Thêm setting cho đường dẫn**

Trong `src/config.py`, thêm vào class `Settings` (cạnh `rag_index_dir` dòng 114):

```python
    #: Gốc thư mục artifact eval. Endpoint `/metrics/eval-snapshot` chỉ ĐỌC ở đây.
    eval_results_dir: str = "./eval/results"
```

- [ ] **Step 6: Lint và commit**

```bash
ruff check src/ tests/ scripts/
git add src/services/eval_snapshot.py src/config.py tests/test_services/test_eval_snapshot.py
git commit -m "feat(obs): service doc snapshot run eval moi nhat"
```

---

### Task 3: Route `GET /api/v1/metrics/eval-snapshot`

**Files:**
- Modify: `src/models/observability.py` (thêm 2 model ở cuối file)
- Modify: `src/api/observability.py` (thêm 1 route)
- Modify: `docs/api_spec.md` (lập luận cho lần nới bề mặt)
- Test: `tests/test_api/test_eval_snapshot_route.py` (create)

**Interfaces:**
- Consumes: `doc_snapshot_moi_nhat`, `SUITES_CHO_PHEP`, `EvalSnapshot` từ Task 2
- Produces: HTTP `GET /api/v1/metrics/eval-snapshot?suite=<rag|agent-intent>`, engineer-only, trả `EvalSnapshotEnvelope`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api/test_eval_snapshot_route.py`:

```python
"""`GET /api/v1/metrics/eval-snapshot` — nguồn số cho khối "Đánh giá offline"."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import get_settings


@pytest.fixture
def results_root(tmp_path: Path, monkeypatch):
    """Trỏ settings sang một cây artifact giả — test không đọc eval/results thật."""
    root = tmp_path / "results"
    run = root / "rag" / "20260828T101500Z"
    run.mkdir(parents=True)
    (run / "metrics.json").write_text(
        json.dumps({"grounded_rate": 1.0, "hallucination_rate": 0.05, "citation_validity": 1.0}),
        encoding="utf-8",
    )
    (run / "manifest.json").write_text(
        json.dumps({"run_id": "20260828T101500Z", "graded_by": "dap_an_khoa", "dataset": "cases.jsonl", "note": "n"}),
        encoding="utf-8",
    )
    get_settings.cache_clear()
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(root))
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
    res = await engineer_client.get("/api/v1/metrics/eval-snapshot?suite=../../etc")

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_suite_chua_co_run_tra_404(engineer_client, results_root):
    res = await engineer_client.get("/api/v1/metrics/eval-snapshot?suite=agent-intent")

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


async def test_driver_khong_doc_duoc(client, results_root):
    """Engineer-only, cùng hàng rào với /traces và /metrics/summary."""
    res = await client.get("/api/v1/metrics/eval-snapshot?suite=rag")

    assert res.status_code in (401, 403)
```

- [ ] **Step 2: Chạy test để chắc nó trượt**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_eval_snapshot_route.py -q
```

Kỳ vọng: FAIL, `test_tra_metrics_va_provenance` nhận 404 từ FastAPI vì route chưa tồn tại.

Đọc `tests/conftest.py:51` và `:75` trước khi sửa gì — nếu fixture `client` không phải là driver-client thì đổi test cuối cho khớp fixture thật, đừng đổi conftest.

- [ ] **Step 3: Thêm model**

Cuối `src/models/observability.py`:

```python
class EvalSnapshotData(_Closed):
    """Ảnh chụp một run eval — KHÔNG phải số đo trực tiếp từ hệ thống đang chạy.

    `graded_by` là `None` với run cũ (ghi trước khi `manifest.json` tồn tại). UI
    phải hiện `—` chứ không được suy ra, vì trộn nhầm nguồn chấm là đúng thứ mà
    tách trường này ra để chặn.
    """

    suite: str
    run_id: str
    metrics: dict[str, float | int | str | None]
    graded_by: str | None = None
    dataset: str | None = None
    note: str | None = None


class EvalSnapshotEnvelope(_Closed):
    data: EvalSnapshotData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION
```

- [ ] **Step 4: Thêm route**

Cuối `src/api/observability.py`:

```python
@router.get(
    "/metrics/eval-snapshot",
    response_model=EvalSnapshotEnvelope,
    dependencies=_ENGINEER_ONLY,
    responses={
        **_AUTH_RESPONSES,
        404: {"model": ErrorEnvelope, "description": "NOT_FOUND — suite chua co run nao doc duoc"},
    },
    summary="Anh chup run eval moi nhat cua mot suite",
)
async def eval_snapshot(
    request: Request,
    response: Response,
    suite: Literal["rag", "agent-intent"] = Query(...),
) -> EvalSnapshotEnvelope:
    """Chỉ ĐỌC artifact đã có. Không chạy eval, không ghi gì.

    `suite` khai bằng `Literal` chứ không phải `str`: giá trị này đi thẳng vào một
    đường dẫn filesystem, nên whitelist ở tầng validate là hàng rào path-traversal
    chứ không phải thẩm mỹ. FastAPI trả 422 cho giá trị ngoài danh sách.
    """
    request_id, trace_id = request_scoped_ids(request)

    snap = doc_snapshot_moi_nhat(suite, Path(get_settings().eval_results_dir))
    if snap is None:
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="suite chua co run eval nao",
            request_id=request_id,
            trace_id=trace_id,
            details={"suite": suite},
        )

    response.headers["X-Trace-Id"] = trace_id
    return EvalSnapshotEnvelope(
        data=EvalSnapshotData(
            suite=snap.suite,
            run_id=snap.run_id,
            metrics=snap.metrics,
            graded_by=snap.graded_by,
            dataset=snap.dataset,
            note=snap.note,
        ),
        meta=Meta(request_id=request_id),
        trace_id=trace_id,
    )
```

Thêm import ở đầu file: `from pathlib import Path`, `from typing import Literal`, `from fastapi import Query`, `from src.models.observability import EvalSnapshotData, EvalSnapshotEnvelope`, `from src.services.eval_snapshot import doc_snapshot_moi_nhat`.

- [ ] **Step 5: Chạy test để chắc nó qua**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_eval_snapshot_route.py -q
```

Kỳ vọng: 4 passed. Nếu `test_suite_ngoai_whitelist_bi_tu_choi` trả mã lỗi khác `VALIDATION_ERROR`, đọc handler 422 trong `src/api/errors.py` và sửa **test** cho khớp mã thật — đừng đổi handler.

- [ ] **Step 6: Ghi lập luận vào `docs/api_spec.md`**

Dưới bảng interface, cạnh chỗ đã lập luận cho `vehicle/profile` và `profile/options`, thêm một đoạn nêu: đây là interface thứ 15; nó chỉ đọc artifact bất biến; nó engineer-only; nó tồn tại vì frontend không đọc được filesystem mà khối "Đánh giá offline" phải bỏ số hard-code. Ghi rõ nó **không** chạy eval.

- [ ] **Step 7: Chạy cả bộ API và lint**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/ -q
```

```bash
ruff check src/ tests/ scripts/
git add src/api/observability.py src/models/observability.py docs/api_spec.md tests/test_api/test_eval_snapshot_route.py
git commit -m "feat(api): GET /metrics/eval-snapshot — doc run eval moi nhat (engineer-only)"
```

---

### Task 4: Tầng service frontend

**Files:**
- Modify: `frontend/src/lib/services/engineer/types.ts`
- Modify: `frontend/src/lib/services/engineer/real.ts`
- Modify: `frontend/src/lib/services/engineer/mock.ts`
- Modify: `frontend/src/lib/services/engineer/index.ts` (export type mới)
- Test: `frontend/src/lib/services/engineer/real.evalSnapshot.test.ts` (create)

**Interfaces:**
- Consumes: `GET /api/v1/metrics/eval-snapshot` từ Task 3
- Produces: `EngineerService.getEvalSnapshot(suite: EvalSuite): Promise<EvalSnapshot | null>` và type `EvalSnapshot`, `EvalSuite`

- [ ] **Step 1: Viết test thất bại**

Tạo `frontend/src/lib/services/engineer/real.evalSnapshot.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { realEngineerService } from "./real";
import { sessionService } from "../session";

describe("getEvalSnapshot", () => {
  beforeEach(() => {
    vi.spyOn(sessionService, "getStoredSession").mockReturnValue({
      accessToken: "t",
      role: "engineer",
    } as never);
  });

  it("map run id, metrics va provenance", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            suite: "rag",
            run_id: "20260828T101500Z",
            metrics: { grounded_rate: 1.0, hallucination_rate: 0.05 },
            graded_by: "dap_an_khoa",
            dataset: "cases.jsonl",
            note: null,
          },
        }),
      }),
    );

    const snap = await realEngineerService.getEvalSnapshot("rag");

    expect(snap?.runId).toBe("20260828T101500Z");
    expect(snap?.metrics.hallucination_rate).toBe(0.05);
    expect(snap?.gradedBy).toBe("dap_an_khoa");
  });

  it("404 tra null chu khong nem loi — chua co run la trang thai binh thuong", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ error: { code: "NOT_FOUND", message: "chua co run" } }),
      }),
    );

    await expect(realEngineerService.getEvalSnapshot("rag")).resolves.toBeNull();
  });
});
```

- [ ] **Step 2: Chạy test để chắc nó trượt**

```bash
cd frontend && npm run test -- real.evalSnapshot
```

Kỳ vọng: FAIL — `getEvalSnapshot is not a function`.

- [ ] **Step 3: Thêm type**

Trong `frontend/src/lib/services/engineer/types.ts`:

```ts
export type EvalSuite = "rag" | "agent-intent";

/**
 * Ảnh chụp một run eval (`GET /metrics/eval-snapshot`) — KHÔNG phải số đo trực
 * tiếp từ hệ thống đang chạy, và không được trộn vào khối Live.
 *
 * `gradedBy` là `null` với run ghi trước khi manifest tồn tại. UI hiện `—`;
 * không được đoán, vì trộn nhầm nguồn chấm là đúng thứ trường này chặn.
 */
export interface EvalSnapshot {
  suite: EvalSuite;
  runId: string;
  metrics: Record<string, number | string | null>;
  gradedBy: string | null;
  dataset: string | null;
  note: string | null;
}
```

Và thêm vào interface `EngineerService`:

```ts
  /** `null` = suite chưa có run nào. Đó là trạng thái bình thường, không phải lỗi. */
  getEvalSnapshot(suite: EvalSuite): Promise<EvalSnapshot | null>;
```

- [ ] **Step 4: Cài đặt `real.ts`**

```ts
export async function getEvalSnapshot(suite: EvalSuite): Promise<EvalSnapshot | null> {
  const res = await fetch(`${API_BASE}/metrics/eval-snapshot?suite=${suite}`, {
    headers: authHeaders(),
  });
  // 404 KHÔNG phải lỗi: một suite chưa chạy eval lần nào là trạng thái hợp lệ,
  // và UI đã có nhánh hiện `—` cho nó. Ném lỗi ở đây sẽ biến "chưa đo" thành
  // "hỏng", đúng kiểu nhầm lẫn mà ô `—` sinh ra để tránh.
  if (res.status === 404) return null;
  await throwIfError(res, "EVAL_SNAPSHOT_FAILED");

  const raw = (await res.json()) as {
    data: {
      suite: EvalSuite;
      run_id: string;
      metrics: Record<string, number | string | null>;
      graded_by: string | null;
      dataset: string | null;
      note: string | null;
    };
  };
  return {
    suite: raw.data.suite,
    runId: raw.data.run_id,
    metrics: raw.data.metrics,
    gradedBy: raw.data.graded_by,
    dataset: raw.data.dataset,
    note: raw.data.note,
  };
}
```

Gắn `getEvalSnapshot` vào object `realEngineerService` ở cuối file, cạnh `getMetricsSummary`.

- [ ] **Step 5: Cài đặt `mock.ts`**

```ts
async function getEvalSnapshot(suite: EvalSuite): Promise<EvalSnapshot | null> {
  await delay(MOCK_LATENCY_MS);
  if (suite !== "rag") return null;
  // Số lấy từ run thật eval/results/rag/20260827T172523Z để mock không vẽ ra
  // một thế giới đẹp hơn thế giới thật — xem spec §3.2.
  return {
    suite: "rag",
    runId: "20260827T172523Z",
    metrics: { grounded_rate: 1.0, hallucination_rate: 0.05, citation_validity: 1.0 },
    gradedBy: "dap_an_khoa",
    dataset: "eval/datasets/manual/v1/cases.jsonl",
    note: null,
  };
}
```

Gắn vào `mockEngineerService`.

- [ ] **Step 6: Export type mới trong `index.ts`**

Thêm `EvalSnapshot,` và `EvalSuite,` vào danh sách `export type { ... }`.

- [ ] **Step 7: Chạy test và lint**

```bash
cd frontend && npm run test -- real.evalSnapshot && npm run lint
```

Kỳ vọng: 2 passed, lint sạch.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/services/engineer/
git commit -m "feat(fe): engineerService.getEvalSnapshot — doc run eval that"
```

---

### Task 5: `StatTileRow` hiển thị số thật, xoá mock

**Files:**
- Delete: `frontend/src/components/engineer/offlineEval.ts`
- Modify: `frontend/src/components/engineer/StatTileRow.tsx`
- Modify: `frontend/src/components/engineer/EngineerShellProvider.tsx` (nạp snapshot một lần khi mở)
- Test: `frontend/src/components/engineer/StatTileRow.test.tsx` (create)

**Interfaces:**
- Consumes: `getEvalSnapshot`, `EvalSnapshot` từ Task 4
- Produces: không có (tầng lá)

- [ ] **Step 1: Viết test thất bại**

Tạo `frontend/src/components/engineer/StatTileRow.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatTileRow } from "./StatTileRow";
import * as shell from "./EngineerShellProvider";

function stub(over: Partial<ReturnType<typeof shell.useEngineerShell>>) {
  vi.spyOn(shell, "useEngineerShell").mockReturnValue({
    metrics: null,
    evalSnapshot: null,
    ...over,
  } as never);
}

describe("StatTileRow", () => {
  it("khong co snapshot thi hien dau gach, khong hien so cu", () => {
    stub({ evalSnapshot: null });
    render(<StatTileRow />);
    // Ba o offline deu phai la em-dash.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText(/92[,.]4/)).toBeNull();
  });

  it("co snapshot thi hien so kem run id", () => {
    stub({
      evalSnapshot: {
        suite: "rag",
        runId: "20260827T172523Z",
        metrics: { grounded_rate: 1.0, hallucination_rate: 0.05, citation_validity: 1.0 },
        gradedBy: "dap_an_khoa",
        dataset: null,
        note: null,
      },
    });
    render(<StatTileRow />);
    expect(screen.getByText("5.0%")).toBeTruthy();
    expect(screen.getByText(/20260827T172523Z/)).toBeTruthy();
  });

  it("metric thieu trong run cu van hien dau gach", () => {
    stub({
      evalSnapshot: {
        suite: "rag",
        runId: "20260814T005140Z",
        metrics: { hallucination_rate: 0.05 },
        gradedBy: null,
        dataset: null,
        note: null,
      },
    });
    render(<StatTileRow />);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
```

- [ ] **Step 2: Chạy test để chắc nó trượt**

```bash
cd frontend && npm run test -- StatTileRow
```

Kỳ vọng: FAIL — `evalSnapshot` chưa có trong shell context.

- [ ] **Step 3: Nạp snapshot trong `EngineerShellProvider`**

Thêm state và một lần nạp khi mount (cùng khuôn với `metrics`):

```tsx
const [evalSnapshot, setEvalSnapshot] = useState<EvalSnapshot | null>(null);

useEffect(() => {
  // Nạp một lần khi mở màn hình. Snapshot chỉ đổi khi có người chạy eval, nên
  // poll theo chu kỳ là gọi vô ích — khác hẳn `metrics`, vốn đổi theo mỗi lượt.
  engineerService.getEvalSnapshot("rag").then(setEvalSnapshot).catch(() => setEvalSnapshot(null));
}, []);
```

Thêm `evalSnapshot` vào giá trị context và vào type của context.

- [ ] **Step 4: Viết lại `StatTileRow`**

Ba thay đổi, mỗi cái có lý do riêng — đừng gộp:

1. Xoá `import { OFFLINE_EVAL_SNAPSHOT } from "./offlineEval"`, đọc `evalSnapshot` từ shell.
2. Khối "Đánh giá offline" đổi thành ba ô lấy từ `metrics` của snapshot: `hallucination_rate` (ngưỡng < 10%), `grounded_rate` (> 90%), `citation_validity` (= 100%). **Bỏ ô "Độ chính xác ý định"** — lý do ở spec §3.2: số thật của nó là 1.0000 trên bộ tripwire hồi quy do chính tác giả router soạn, hiện lên dashboard là mời người đọc hiểu nhầm.
3. Ô Live `Grounded Rate` đổi nhãn thành `Tỷ lệ lượt có trích dẫn` — phép đo giữ nguyên (`citation_count > 0`), chỉ sửa cái tên đang nói quá.

Hàm dựng giá trị, dùng chung cho cả ba ô:

```tsx
function pct(v: number | string | null | undefined): string {
  return typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—";
}
```

Nhãn nhóm mang provenance:

```tsx
<Group
  label="Đánh giá offline"
  sub={evalSnapshot ? `${evalSnapshot.runId} · ${evalSnapshot.gradedBy ?? "—"}` : "chưa có run"}
>
```

`pass` của mỗi ô phải là `null` khi giá trị không phải số, để ô hiện `—` thay vì màu đúng/sai giả.

- [ ] **Step 5: Xoá file mock**

```bash
git rm frontend/src/components/engineer/offlineEval.ts
```

- [ ] **Step 6: Chạy test, lint, build**

```bash
cd frontend && npm run test && npm run lint && npx tsc --noEmit
```

Kỳ vọng: tất cả pass. `tsc --noEmit` bắt được chỗ nào còn tham chiếu `OFFLINE_EVAL_SNAPSHOT`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/engineer/
git commit -m "feat(fe): dashboard hien so eval that kem run id, xoa mock offlineEval"
```

---

### Task 6: Chạy lại toàn bộ và cập nhật nhật ký

**Files:**
- Modify: `WORKLOG.md`
- Modify: `JOURNAL.md`

- [ ] **Step 1: Chạy cả suite backend**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
```

Ghi lại **con số thật** đã chạy (passed/skipped/thời gian). Kiểm tra skip bằng `-rs` nếu số skip khác 17 — theo `CLAUDE.md`, số skip là thuộc tính của máy chứ không phải của bộ test.

- [ ] **Step 2: Chạy cả suite frontend**

```bash
cd frontend && npm run test && npm run lint
```

- [ ] **Step 3: Lint backend**

```bash
ruff check src/ tests/ scripts/
```

- [ ] **Step 4: Cập nhật `WORKLOG.md` và `JOURNAL.md`**

Theo đúng khuôn bảng/mục đã có. Ghi con số thật vừa chạy, không chép lại con số trong `CLAUDE.md`.

- [ ] **Step 5: Commit**

```bash
git add WORKLOG.md JOURNAL.md
git commit -m "docs: worklog/journal cho phan A dashboard ky su"
```

---

## Phần B và C

- **B** (trace sống qua restart, 30 ngày SQLite) — đã duyệt, plan riêng viết khi A vào. Độc lập với A: khác file, khác tầng.
- **C** (LLM judge) — **chưa khởi động**. Chờ nhóm chốt bốn câu ở spec §7.

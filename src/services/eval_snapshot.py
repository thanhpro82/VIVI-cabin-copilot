"""Đọc snapshot của run eval mới nhất — nguồn cho `GET /api/v1/metrics/eval-snapshot`.

Đây là hàm **đọc thuần**. Nó không bao giờ chạy eval, không ghi gì, không đụng vào
thư mục run — chúng bất biến (`CLAUDE.md` §"Evidence is the product"). Ranh giới đó
là cố ý: bề mặt kỹ sư được phép *xem* bằng chứng, không được phép *tạo* ra nó trong
một request HTTP.

VÌ SAO TÁCH `graded_by` RA — dashboard không được trộn ba nguồn chấm (đáp án khoá /
người chấm tay / judge) vào cùng một con số. Run ghi trước 28/08 không có
`manifest.json` nên trường này là `None`, và UI phải hiện `—`: đoán ra một nguồn
chấm cho con số của người khác đúng là kiểu nhầm mà trường này sinh ra để chặn.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Whitelist suite. `suite` đi thẳng vào một đường dẫn filesystem, nên danh sách này
#: là hàng rào path-traversal chứ không phải thẩm mỹ. Route khai nó lại bằng
#: `Literal` để FastAPI chặn ngay ở tầng validate, trước khi chạm tới đây.
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
    """`None` cho cả "không có" lẫn "có mà hỏng", nhưng chỉ ca thứ hai mới log.

    Phân biệt này không phải sạch sẽ vặt. Run ghi trước 28/08 **không có**
    `manifest.json` và sẽ không bao giờ có (thư mục run bất biến, không hồi tố),
    nên gộp chung thì mỗi lần dashboard tải là một WARNING cho một chuyện hoàn
    toàn bình thường — và cảnh báo kêu oan là cách huấn luyện người ta ngó lơ log.
    """
    try:
        noi_dung = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        logger.warning("khong doc duoc %s", path)
        return None
    return noi_dung if isinstance(noi_dung, dict) else None


def doc_snapshot_moi_nhat(suite: str, results_root: Path) -> EvalSnapshot | None:
    """Run mới nhất của `suite`, hoặc `None` nếu chưa có run nào đọc được.

    "Mới nhất" = tên thư mục lớn nhất theo thứ tự chuỗi. Đúng vì mọi run id đều là
    dấu thời gian UTC dạng `YYYYMMDDThhmmssZ` — thứ tự chuỗi trùng thứ tự thời gian.

    Thư mục thiếu `metrics.json` bị **bỏ qua chứ không phải trả về rỗng**. Đây không
    phải phòng xa: `_cmd_eval` mkdir trước rồi mới ghi file, nên một lần chạy bị ngắt
    để lại đúng một thư mục rỗng mang tên mới nhất, và nó sẽ che mất run thật cuối.
    """
    suite_dir = results_root / suite
    if not suite_dir.is_dir():
        return None

    thu_muc = sorted((d for d in suite_dir.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    for run_dir in thu_muc:
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

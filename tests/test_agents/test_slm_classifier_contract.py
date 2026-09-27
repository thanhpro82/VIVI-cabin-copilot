"""Contract với llama-server thật. Bật bằng: $env:SLM_SERVER_TESTS="1".

CI không chạy tầng này (không có model) — bằng chứng sinh từ máy dev,
đúng nếp các test model khác của repo.
"""

import os
import time

import pytest

from src.agents.slm import CLASSIFY_INTENTS, QwenClassifier
from src.config import get_settings

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.getenv("SLM_SERVER_TESTS") != "1", reason="cần llama-server thật (SLM_SERVER_TESTS=1)"),
]


@pytest.fixture()
def classifier():
    s = get_settings()
    return QwenClassifier(s.slm_endpoint, s.slm_model_id, s.slm_classify_timeout_s)


def test_grammar_ep_enum_tren_model_that(classifier):
    """Bất kể model nghĩ gì, đầu ra PHẢI là một trong ba lớp — grammar lo việc đó."""
    for cau in ("Nóng quá, giảm nhiệt độ xuống đi", "Áp suất lốp bao nhiêu?", "Chào buổi sáng nha"):
        assert classifier.classify(cau) in CLASSIFY_INTENTS


def test_khong_co_thinking_leak_va_do_tre_ghi_nhan(classifier):
    """Grammar chặn <think> (token đầu buộc là `{`). Đo tay 5 lượt để có số đầu tiên
    cho SP-0 — in ra chứ không assert ngưỡng: chưa có phân bố thì chưa đặt cổng."""
    do_tre = []
    for _ in range(5):
        t0 = time.perf_counter()
        ket_qua = classifier.classify("Xe này đi đường dài có êm không nhỉ?")
        do_tre.append((time.perf_counter() - t0) * 1000)
        assert ket_qua in CLASSIFY_INTENTS
    print(f"\nslm_classify_ms 5 lượt: {[round(x) for x in do_tre]}")

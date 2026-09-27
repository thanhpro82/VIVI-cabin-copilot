"""Contract với llama-server thật. Bật bằng: $env:SLM_SERVER_TESTS="1".

CI không chạy tầng này (không có model) — bằng chứng sinh từ máy dev.
"""

import os
import time

import pytest

from src.agents.nodes.chitchat_cong import qua_cong_chitchat
from src.agents.slm import QwenChitchat
from src.config import get_settings

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.getenv("SLM_SERVER_TESTS") != "1", reason="cần llama-server thật (SLM_SERVER_TESTS=1)"),
]


def test_sinh_that_qua_cong_va_do_tre():
    """Ba ranh giới: xã giao, ngoài phạm vi, bẫy thông số. In số để chép vào WORKLOG —
    không assert ngưỡng, chưa có phân bố."""
    s = get_settings()
    w = QwenChitchat(s.slm_endpoint, s.slm_model_id, s.slm_chitchat_timeout_s)
    ket = []
    for cau in ("Chào buổi sáng nha", "Ngày mai có mưa không ta", "Xe này chạy được bao nhiêu km một lần sạc?"):
        t0 = time.perf_counter()
        tho = w.reply(cau)
        ms = (time.perf_counter() - t0) * 1000
        phat, cong = qua_cong_chitchat(tho)
        ket.append((round(ms), cong, phat[:70]))
        assert phat
    print("\n", ket)

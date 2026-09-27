import os
import threading

import pytest

from offline_poc.metrics import StageTrace, sample_peak_rss, summarize_ms


def test_summarize_reports_p50_and_p95() -> None:
    result = summarize_ms([100, 200, 300, 400, 500])

    assert result["count"] == 5
    assert result["p50_ms"] == 300
    assert result["p95_ms"] == 500


def test_summarize_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        summarize_ms([])


def test_stage_trace_rejects_reverse_time() -> None:
    trace = StageTrace(trace_id="tr-test")
    trace.mark("speech_end", 200)

    with pytest.raises(ValueError, match="monotonic"):
        trace.mark("stt_completed", 100)


def test_sample_peak_rss_reads_current_process() -> None:
    stop = threading.Event()
    stop.set()

    peak_rss = sample_peak_rss(os.getpid(), stop, interval_s=0.001)

    assert peak_rss > 0

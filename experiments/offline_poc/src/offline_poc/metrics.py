from dataclasses import dataclass, field
import math
import threading
import time

import psutil


@dataclass
class StageTrace:
    trace_id: str
    marks_ns: dict[str, int] = field(default_factory=dict)

    def mark(self, name: str, value_ns: int | None = None) -> None:
        value = time.perf_counter_ns() if value_ns is None else value_ns
        if self.marks_ns and value < max(self.marks_ns.values()):
            raise ValueError("timestamps must be monotonic")
        self.marks_ns[name] = value

    def duration_ms(self, start: str, end: str) -> float:
        return (self.marks_ns[end] - self.marks_ns[start]) / 1_000_000


def summarize_ms(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("at least one value is required")

    def percentile(fraction: float) -> float:
        index = max(0, math.ceil(fraction * len(ordered)) - 1)
        return ordered[index]

    return {
        "count": len(ordered),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
    }


def _process_tree_rss(process: psutil.Process) -> int:
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    total = 0
    for current in processes:
        try:
            total += current.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def sample_peak_rss(
    pid: int,
    stop: threading.Event,
    interval_s: float = 0.05,
) -> int:
    """Sample peak RSS for a process tree until the stop event is set."""
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")

    process = psutil.Process(pid)
    peak = _process_tree_rss(process)
    while not stop.wait(interval_s):
        peak = max(peak, _process_tree_rss(process))
    return peak

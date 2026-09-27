from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable

from offline_poc.metrics import sample_peak_rss
from offline_poc.stt import normalize_vietnamese_text


PiperRunner = Callable[[list[str], str], int | None]


@dataclass(frozen=True)
class TtsMeasurement:
    total_ms: float
    first_audio_ms: float
    peak_rss_bytes: int | None = None


def _default_piper_runner(command: list[str], text: str) -> int:
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    stop = threading.Event()
    sampled_peak = [0]

    def sample() -> None:
        sampled_peak[0] = sample_peak_rss(os.getpid(), stop)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        subprocess.run(
            command,
            input=text,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_env,
            timeout=60,
        )
    finally:
        stop.set()
        sampler.join(timeout=2)
    return sampled_peak[0]


class PiperAdapter:
    def __init__(
        self,
        executable: Path,
        model_path: Path,
        runner: PiperRunner | None = None,
    ) -> None:
        self.executable = executable
        self.model_path = model_path
        self.runner = runner or _default_piper_runner

    def synthesize(self, text: str, output_path: Path) -> TtsMeasurement:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_text = normalize_vietnamese_text(text)
        command = [
            str(self.executable),
            "--model",
            str(self.model_path),
            "--output_file",
            str(output_path),
        ]
        started_ns = time.perf_counter_ns()
        peak_rss_bytes = self.runner(command, normalized_text)
        total_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        if not output_path.is_file() or not output_path.read_bytes().startswith(b"RIFF"):
            raise ValueError("Piper did not produce a valid WAV file")
        return TtsMeasurement(
            total_ms=total_ms,
            first_audio_ms=total_ms,
            peak_rss_bytes=peak_rss_bytes,
        )

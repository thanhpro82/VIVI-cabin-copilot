from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable
import unicodedata


WhisperRunner = Callable[[list[str]], str]


@dataclass(frozen=True)
class Transcript:
    text: str
    total_ms: float
    load_ms: float = 0.0


def normalize_vietnamese_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _metric_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in normalized
    )
    return " ".join(without_punctuation.split())


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            substitution = previous[hyp_index - 1] + (ref_item != hyp_item)
            insertion = current[hyp_index - 1] + 1
            deletion = previous[hyp_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = _metric_text(reference).split()
    hypothesis_words = _metric_text(hypothesis).split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return _edit_distance(reference_words, hypothesis_words) / len(reference_words)


def char_error_rate(reference: str, hypothesis: str) -> float:
    reference_chars = list(_metric_text(reference))
    hypothesis_chars = list(_metric_text(hypothesis))
    if not reference_chars:
        return 0.0 if not hypothesis_chars else 1.0
    return _edit_distance(reference_chars, hypothesis_chars) / len(reference_chars)


def _default_whisper_runner(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout


class WhisperCppAdapter:
    def __init__(
        self,
        executable: Path,
        model_path: Path,
        runner: WhisperRunner | None = None,
    ) -> None:
        self.executable = executable
        self.model_path = model_path
        self.runner = runner or _default_whisper_runner

    def transcribe(self, audio_path: Path) -> Transcript:
        command = [
            str(self.executable),
            "-m",
            str(self.model_path),
            "-f",
            str(audio_path),
            "-l",
            "vi",
            "-oj",
        ]
        started_ns = time.perf_counter_ns()
        output = self.runner(command)
        payload = json.loads(output)
        segments = payload.get("transcription", [])
        text = " ".join(str(segment.get("text", "")) for segment in segments)
        return Transcript(
            text=normalize_vietnamese_text(text),
            total_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )


class PhoWhisperAdapter:
    """Lazy local-only Transformers adapter used by the real benchmark runner."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        offline_mode: bool = True,
        pipeline_factory: Callable[..., Any] | None = None,
    ) -> None:
        path = Path(model_path)
        if offline_mode and not path.exists():
            raise ValueError("offline_mode requires a local path for PhoWhisper")
        self.model_path = path
        self.offline_mode = offline_mode
        self.pipeline_factory = pipeline_factory
        self._pipeline: Any | None = None
        self._load_ms = 0.0

    def _load(self) -> Any:
        if self._pipeline is None:
            started_ns = time.perf_counter_ns()
            factory = self.pipeline_factory
            if factory is None:
                from transformers import (
                    AutoModelForSpeechSeq2Seq,
                    AutoProcessor,
                    pipeline,
                )

                model = AutoModelForSpeechSeq2Seq.from_pretrained(
                    str(self.model_path),
                    local_files_only=self.offline_mode,
                )
                processor = AutoProcessor.from_pretrained(
                    str(self.model_path),
                    local_files_only=self.offline_mode,
                )
                self._pipeline = pipeline(
                    "automatic-speech-recognition",
                    model=model,
                    tokenizer=processor.tokenizer,
                    feature_extractor=processor.feature_extractor,
                    device="cpu",
                )
            else:
                self._pipeline = factory(
                    "automatic-speech-recognition",
                    model=str(self.model_path),
                )
            self._load_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        return self._pipeline

    def transcribe(self, audio_path: Path) -> Transcript:
        started_ns = time.perf_counter_ns()
        model = self._load()
        import soundfile as sf

        audio, sampling_rate = sf.read(
            str(audio_path), dtype="float32", always_2d=False
        )
        if getattr(audio, "ndim", 1) > 1:
            audio = audio.mean(axis=1)
        target_sampling_rate = int(model.feature_extractor.sampling_rate)
        if sampling_rate != target_sampling_rate:
            import numpy as np

            output_length = max(
                1, round(len(audio) * target_sampling_rate / sampling_rate)
            )
            source_positions = np.arange(len(audio), dtype=np.float64)
            target_positions = np.linspace(
                0, max(0, len(audio) - 1), output_length, dtype=np.float64
            )
            audio = np.interp(target_positions, source_positions, audio).astype(
                "float32"
            )
            sampling_rate = target_sampling_rate
        output = model(
            {"raw": audio, "sampling_rate": sampling_rate},
            generate_kwargs={"language": "vi", "task": "transcribe"},
        )
        text = output["text"] if isinstance(output, dict) else str(output)
        return Transcript(
            text=normalize_vietnamese_text(text),
            total_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
            load_ms=self._load_ms,
        )

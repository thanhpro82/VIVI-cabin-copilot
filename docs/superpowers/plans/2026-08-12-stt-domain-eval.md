# STT Domain-Error Phase 1 Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone script that measures WER/CER on real Vietnamese audio for the domain terms currently misrecognized (áp suất lốp, điều hòa, âm lượng...), comparing the current PhoWhisper-base engine against `hynt/Zipformer-30M-RNNT-6000h`, to decide if Zipformer is a viable short-term fix.

**Architecture:** A small library module (`scripts/stt_eval_lib.py`) parses the existing `eval/datasets/poc/v1/audio/manifest.jsonl` schema. A thin engine wrapper (`scripts/zipformer_engine.py`) runs Zipformer via `sherpa-onnx`. The comparison script (`scripts/eval_stt_compare.py`) runs both engines over every manifest entry, reuses `word_error_rate`/`char_error_rate` from `src/services/voice.py`, and writes results under `eval/results/stt-compare/<run-id>/` following the repo's existing evidence convention. Nothing in `src/` changes; this is entirely additive tooling under `scripts/`.

**Tech Stack:** Python 3.13 (repo venv), `sherpa-onnx` (new), `huggingface_hub` (already installed), `numpy` (already installed), pytest.

## Global Constraints

- Run everything through `.\.venv\Scripts\python.exe` (Windows; do not assume a bare `python`/`pytest` on PATH).
- `ruff` line-length 120, select `E/F/I/N/W/UP`, `E501` ignored — run `ruff check` / `ruff format` on every new file.
- WAV audio must be 16kHz mono — this is an existing hard constraint in `src/services/voice.py:107-121` and applies identically to the Zipformer wrapper.
- No network calls at runtime. The Zipformer model is downloaded exactly once via a manual script invocation (`scripts/download_zipformer_model.py`), never auto-fetched when the comparison script runs.
- Zipformer-30M-RNNT-6000h license is `cc-by-nc-nd-4.0` (non-commercial, no-derivatives) — academic evaluation only, never fine-tune or redistribute the weights. State this in the download script's docstring.
- `eval/results/<suite>/<run-id>/` directories are immutable once written (repo convention) — never hand-edit; each run gets a fresh UTC-timestamp run id.
- Tests go in `tests/`, following the existing `tests/test_services/` style (plain pytest functions, no unnecessary fixtures, `tmp_path` for filesystem tests).
- This is evaluation tooling under `scripts/`, not `src/` product code — it does not need the full pytest discipline the rest of the repo follows, but new parsing/computation logic (not already covered by existing `src/` tests) still needs unit tests per this plan.

---

## Task 1: Add `sherpa-onnx` optional dependency

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `sherpa_onnx` importable in the venv after `pip install -e ".[stt_eval]"`.

- [ ] **Step 1: Add the dependency group**

Edit `pyproject.toml`, adding a new group after the existing `voice` group (around line 46):

```toml
voice = [
    "piper-tts>=1.3,<2",
    "faster-whisper>=1.0,<2",
]
# Phase 1 quick eval only (scripts/eval_stt_compare.py) — not a src/ runtime dependency.
# See docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md.
stt_eval = [
    "sherpa-onnx>=1.10,<2",
]
```

- [ ] **Step 2: Install and verify**

Run: `.\.venv\Scripts\python.exe -m pip install -e ".[stt_eval]"`
Then: `.\.venv\Scripts\python.exe -c "import sherpa_onnx; print(sherpa_onnx.__file__)"`
Expected: prints a path with no `ModuleNotFoundError`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add sherpa-onnx as stt_eval optional dependency"
```

---

## Task 2: Manifest loader for `eval/datasets/poc/v1/audio/manifest.jsonl`

**Files:**
- Create: `scripts/stt_eval_lib.py`
- Create: `tests/test_scripts/__init__.py`
- Create: `tests/test_scripts/test_stt_eval_lib.py`

**Interfaces:**
- Produces: `ManifestEntry` dataclass (`audio_id: str`, `audio_path: Path`, `reference_text: str`, `speaker_code: str`, `region: str`, `noise_condition: str`, `duration_ms: int`, `consent_scope: str`); `load_manifest_entries(manifest_path: Path, audio_dir: Path) -> tuple[list[ManifestEntry], list[str]]` (second element is skip warnings); `REQUIRED_MANIFEST_FIELDS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scripts/__init__.py` (empty file).

Create `tests/test_scripts/test_stt_eval_lib.py`:

```python
from pathlib import Path

import pytest

from scripts.stt_eval_lib import load_manifest_entries


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_manifest_entries_parses_valid_entry(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav_path = audio_dir / "sample.wav"
    wav_path.write_bytes(b"RIFF....WAVEfmt ")
    manifest_path = audio_dir / "manifest.jsonl"
    _write(
        manifest_path,
        '{"audio_id":"a1","path":"sample.wav","reference_text":"áp suất lốp",'
        '"speaker_code":"spk-01","region":"north","noise_condition":"cabin-idle",'
        '"duration_ms":1500,"consent_scope":"internal-poc-evaluation"}\n',
    )

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert warnings == []
    assert len(entries) == 1
    assert entries[0].audio_id == "a1"
    assert entries[0].audio_path == wav_path.resolve()
    assert entries[0].reference_text == "áp suất lốp"


def test_load_manifest_entries_skips_blank_lines_silently(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(manifest_path, "\r\n   \n")

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert warnings == []


def test_load_manifest_entries_warns_on_missing_required_field(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(manifest_path, '{"audio_id":"a1","path":"sample.wav"}\n')

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert len(warnings) == 1
    assert "missing required field" in warnings[0]


def test_load_manifest_entries_warns_on_missing_audio_file(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(
        manifest_path,
        '{"audio_id":"a1","path":"missing.wav","reference_text":"x",'
        '"speaker_code":"spk-01","region":"north","noise_condition":"cabin-idle",'
        '"duration_ms":1000,"consent_scope":"internal-poc-evaluation"}\n',
    )

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert len(warnings) == 1
    assert "audio file not found" in warnings[0]


def test_load_manifest_entries_warns_on_invalid_json(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"
    _write(manifest_path, "{not valid json\n")

    entries, warnings = load_manifest_entries(manifest_path, audio_dir)

    assert entries == []
    assert len(warnings) == 1
    assert "invalid JSON" in warnings[0]


def test_load_manifest_entries_raises_when_manifest_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_manifest_entries(tmp_path / "does_not_exist.jsonl", tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_stt_eval_lib.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.stt_eval_lib'` (or `scripts` has no attribute).

- [ ] **Step 3: Implement**

Create `scripts/stt_eval_lib.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED_MANIFEST_FIELDS = (
    "audio_id",
    "path",
    "reference_text",
    "speaker_code",
    "region",
    "noise_condition",
    "duration_ms",
    "consent_scope",
)


@dataclass(frozen=True)
class ManifestEntry:
    audio_id: str
    audio_path: Path
    reference_text: str
    speaker_code: str
    region: str
    noise_condition: str
    duration_ms: int
    consent_scope: str


def load_manifest_entries(manifest_path: Path, audio_dir: Path) -> tuple[list[ManifestEntry], list[str]]:
    """Parses eval/datasets/poc/v1/audio/manifest.jsonl (schema documented in
    that directory's README.md). Blank lines are ignored. A malformed line
    (bad JSON, missing required field, or a `path` that doesn't resolve to an
    existing file) is skipped and reported as a warning string rather than
    aborting the whole load — one bad recording shouldn't block evaluating
    the rest of the manifest."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    entries: list[ManifestEntry] = []
    warnings: list[str] = []
    for line_number, raw_line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            warnings.append(f"line {line_number}: invalid JSON ({exc})")
            continue
        missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in record]
        if missing:
            warnings.append(f"line {line_number}: missing required field(s) {missing}")
            continue
        audio_path = (audio_dir / record["path"]).resolve()
        if not audio_path.is_file():
            warnings.append(f"line {line_number}: audio file not found at {audio_path}")
            continue
        entries.append(
            ManifestEntry(
                audio_id=record["audio_id"],
                audio_path=audio_path,
                reference_text=record["reference_text"],
                speaker_code=record["speaker_code"],
                region=record["region"],
                noise_condition=record["noise_condition"],
                duration_ms=record["duration_ms"],
                consent_scope=record["consent_scope"],
            )
        )
    return entries, warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_stt_eval_lib.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint and commit**

```bash
.\.venv\Scripts\python.exe -m ruff check scripts/stt_eval_lib.py tests/test_scripts/
.\.venv\Scripts\python.exe -m ruff format scripts/stt_eval_lib.py tests/test_scripts/
git add scripts/stt_eval_lib.py tests/test_scripts/__init__.py tests/test_scripts/test_stt_eval_lib.py
git commit -m "feat(eval): add manifest loader for STT domain-eval audio corpus"
```

---

## Task 3: Zipformer model download script

**Files:**
- Create: `scripts/download_zipformer_model.py`
- Create: `tests/test_scripts/test_download_zipformer_model.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: on real (non-dry-run) invocation, writes `models/voice/zipformer-30m-rnnt-6000h/{encoder.int8.onnx,decoder.int8.onnx,joiner.int8.onnx,tokens.txt}` plus a `.sha256` and `.metadata.json` sidecar per file. Task 4 depends on exactly these four filenames existing under that directory.

Model provenance (verified against the Hugging Face repo on 2026-08-12): repo
`hynt/Zipformer-30M-RNNT-6000h`, pinned revision
`24ed30248e1c96bb690c81c24ab4e056f8cd9fce`, license `cc-by-nc-nd-4.0`. That
repo's `config.json` is, despite the filename, the sherpa-onnx `tokens.txt`
token list (`<blk> 0`, `<sos/eos> 1`, ... one `<token> <id>` per line) — not a
JSON model config — so it is downloaded and saved locally as `tokens.txt`
directly; no `sentencepiece`/`bpe.model` conversion step is needed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripts/test_download_zipformer_model.py`:

```python
import json
import subprocess
import sys
from pathlib import Path


def test_download_zipformer_model_dry_run_prints_plan(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/download_zipformer_model.py", "--dry-run", "--output-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)

    assert payload["output_dir"] == str(tmp_path)
    assert payload["license"] == "cc-by-nc-nd-4.0"
    local_filenames = {artifact["local_filename"] for artifact in payload["artifacts"]}
    assert local_filenames == {"encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"}
    repositories = {artifact["repository"] for artifact in payload["artifacts"]}
    assert repositories == {"hynt/Zipformer-30M-RNNT-6000h"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_download_zipformer_model.py -v`
Expected: FAIL — script does not exist yet (subprocess exits non-zero / `FileNotFoundError`).

- [ ] **Step 3: Implement**

Create `scripts/download_zipformer_model.py`:

```python
"""One-time manual download of the Zipformer-30M-RNNT-6000h ONNX model files
used by scripts/zipformer_engine.py (Phase 1 STT quick eval only — see
docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md). Never invoked
automatically at runtime.

License: cc-by-nc-nd-4.0 (hynt/Zipformer-30M-RNNT-6000h on Hugging Face) —
non-commercial, no-derivatives. Academic evaluation only; do not fine-tune or
redistribute the weights.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\download_zipformer_model.py
    .\\.venv\\Scripts\\python.exe scripts\\download_zipformer_model.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = "hynt/Zipformer-30M-RNNT-6000h"
REVISION = "24ed30248e1c96bb690c81c24ab4e056f8cd9fce"
LICENSE = "cc-by-nc-nd-4.0"

# (filename in the HF repo, filename to save it as locally).
# config.json in this repo is the sherpa-onnx tokens.txt token list, not a
# JSON config — saved locally as tokens.txt directly, see module docstring.
ARTIFACTS = [
    ("encoder-epoch-20-avg-10.int8.onnx", "encoder.int8.onnx"),
    ("decoder-epoch-20-avg-10.int8.onnx", "decoder.int8.onnx"),
    ("joiner-epoch-20-avg-10.int8.onnx", "joiner.int8.onnx"),
    ("config.json", "tokens.txt"),
]

DEFAULT_OUTPUT_DIR = Path("models/voice/zipformer-30m-rnnt-6000h")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan(output_dir: Path) -> dict:
    return {
        "output_dir": str(output_dir),
        "license": LICENSE,
        "artifacts": [
            {
                "repository": REPOSITORY,
                "revision": REVISION,
                "repo_filename": repo_filename,
                "local_filename": local_filename,
            }
            for repo_filename, local_filename in ARTIFACTS
        ],
    }


def download(output_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps(_plan(output_dir), indent=2))
        return

    from huggingface_hub import hf_hub_download

    output_dir.mkdir(parents=True, exist_ok=True)
    for repo_filename, local_filename in ARTIFACTS:
        downloaded_path = Path(hf_hub_download(repo_id=REPOSITORY, filename=repo_filename, revision=REVISION))
        target_path = output_dir / local_filename
        target_path.write_bytes(downloaded_path.read_bytes())
        checksum = _sha256(target_path)
        (output_dir / f"{local_filename}.sha256").write_text(f"{checksum}  {local_filename}\n", encoding="utf-8")
        metadata = {
            "repository": REPOSITORY,
            "revision": REVISION,
            "repo_filename": repo_filename,
            "local_filename": local_filename,
            "license": LICENSE,
            "sha256": checksum,
            "size_bytes": target_path.stat().st_size,
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (output_dir / f"{local_filename}.metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"Downloaded: {target_path} (sha256={checksum})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    download(args.output_dir, args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_download_zipformer_model.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint and commit**

```bash
.\.venv\Scripts\python.exe -m ruff check scripts/download_zipformer_model.py tests/test_scripts/test_download_zipformer_model.py
.\.venv\Scripts\python.exe -m ruff format scripts/download_zipformer_model.py tests/test_scripts/test_download_zipformer_model.py
git add scripts/download_zipformer_model.py tests/test_scripts/test_download_zipformer_model.py
git commit -m "feat(eval): add one-time Zipformer model download script"
```

---

## Task 4: Zipformer engine wrapper

**Files:**
- Create: `scripts/zipformer_engine.py`
- Create: `tests/test_scripts/test_zipformer_engine.py`

**Interfaces:**
- Consumes: `models/voice/zipformer-30m-rnnt-6000h/{encoder.int8.onnx,decoder.int8.onnx,joiner.int8.onnx,tokens.txt}` (Task 3's output); `Transcript`, `normalize_vietnamese_text` from `src/services/voice.py`.
- Produces: `read_wave_as_float32(audio_path: Path) -> tuple[np.ndarray, int]`; `ZipformerEngine` with `.transcribe_file(audio_path: Path) -> Transcript`; `get_zipformer_engine(model_dir: Path) -> ZipformerEngine` (raises `FileNotFoundError` with the download command if model files are missing). Task 5 consumes `get_zipformer_engine` and the `.transcribe_file` interface.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scripts/test_zipformer_engine.py`:

```python
import wave
from pathlib import Path

import numpy as np
import pytest

from scripts.zipformer_engine import get_zipformer_engine, read_wave_as_float32

FIXTURE = Path("tests/fixtures/voice/warm_sample.wav")


def test_read_wave_as_float32_returns_normalized_samples_and_sample_rate() -> None:
    samples, sample_rate = read_wave_as_float32(FIXTURE)

    assert sample_rate == 16000
    assert samples.dtype == np.float32
    assert samples.shape[0] == 22291
    assert samples.min() >= -1.0
    assert samples.max() <= 1.0


def test_read_wave_as_float32_rejects_non_16khz_or_stereo(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.wav"
    with wave.open(str(bad_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 4)

    with pytest.raises(ValueError, match="16kHz mono"):
        read_wave_as_float32(bad_path)


def test_get_zipformer_engine_raises_clear_error_when_model_files_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="download_zipformer_model"):
        get_zipformer_engine(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_zipformer_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.zipformer_engine'`.

- [ ] **Step 3: Implement**

Create `scripts/zipformer_engine.py`:

```python
"""Thin wrapper around sherpa-onnx's OfflineRecognizer for
hynt/Zipformer-30M-RNNT-6000h, used only by scripts/eval_stt_compare.py
(Phase 1 quick eval). Not part of src/ and not wired into STT_PROVIDER — see
docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md."""

from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np

from src.services.voice import Transcript, normalize_vietnamese_text

EXPECTED_SAMPLE_RATE = 16000
FEATURE_DIM = 80
REQUIRED_MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")


def read_wave_as_float32(audio_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(audio_path), "rb") as wav_file:
        framerate = wav_file.getframerate()
        if wav_file.getnchannels() != 1 or framerate != EXPECTED_SAMPLE_RATE:
            raise ValueError(f"audio must be 16kHz mono WAV, got {wav_file.getnchannels()}ch/{framerate}Hz")
        raw_frames = wav_file.readframes(wav_file.getnframes())
    samples_int16 = np.frombuffer(raw_frames, dtype=np.int16)
    samples_float32 = samples_int16.astype(np.float32) / 32768.0
    return samples_float32, framerate


class ZipformerEngine:
    def __init__(self, model_dir: Path, num_threads: int = 1) -> None:
        import sherpa_onnx  # imported lazily: heavy optional dependency, only needed for this eval script

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.int8.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=num_threads,
            sample_rate=EXPECTED_SAMPLE_RATE,
            feature_dim=FEATURE_DIM,
            decoding_method="greedy_search",
        )

    def transcribe_file(self, audio_path: Path) -> Transcript:
        samples, sample_rate = read_wave_as_float32(audio_path)
        started_ns = time.perf_counter_ns()
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self._recognizer.decode_streams([stream])
        text = stream.result.text
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        return Transcript(text=normalize_vietnamese_text(text), latency_ms=latency_ms)


def get_zipformer_engine(model_dir: Path) -> ZipformerEngine:
    missing = [name for name in REQUIRED_MODEL_FILES if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Zipformer model files missing in {model_dir}: {missing}. "
            f"Run: .\\.venv\\Scripts\\python.exe scripts\\download_zipformer_model.py"
        )
    return ZipformerEngine(model_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_zipformer_engine.py -v`
Expected: 3 passed. (These tests don't require the real model files or a working `sherpa_onnx` install — `get_zipformer_engine` raises before constructing `ZipformerEngine` when files are missing, and the other two test `read_wave_as_float32` directly.)

- [ ] **Step 5: Lint and commit**

```bash
.\.venv\Scripts\python.exe -m ruff check scripts/zipformer_engine.py tests/test_scripts/test_zipformer_engine.py
.\.venv\Scripts\python.exe -m ruff format scripts/zipformer_engine.py tests/test_scripts/test_zipformer_engine.py
git add scripts/zipformer_engine.py tests/test_scripts/test_zipformer_engine.py
git commit -m "feat(eval): add Zipformer sherpa-onnx engine wrapper"
```

---

## Task 5: Comparison script (`eval_stt_compare.py`)

**Files:**
- Create: `scripts/eval_stt_compare.py`
- Create: `tests/test_scripts/test_eval_stt_compare.py`

**Interfaces:**
- Consumes: `ManifestEntry`, `load_manifest_entries` (Task 2); `get_zipformer_engine` (Task 4); `Transcript`, `transcribe_raw`, `word_error_rate`, `char_error_rate` from `src/services/voice.py`.
- Produces: `compare_entry(entry, phowhisper_fn, zipformer_fn) -> dict`; `summarize(case_results: list[dict]) -> dict`; `write_run_outputs(run_dir, run_id, manifest_path, case_results, metrics) -> None`; `print_comparison_table(case_results, metrics) -> None`; CLI `main()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scripts/test_eval_stt_compare.py`:

```python
from pathlib import Path

from scripts.eval_stt_compare import compare_entry, summarize, write_run_outputs
from scripts.stt_eval_lib import ManifestEntry
from src.services.voice import Transcript


def _entry(audio_id: str, reference_text: str) -> ManifestEntry:
    return ManifestEntry(
        audio_id=audio_id,
        audio_path=Path(f"{audio_id}.wav"),
        reference_text=reference_text,
        speaker_code="spk-01",
        region="north",
        noise_condition="cabin-idle",
        duration_ms=1500,
        consent_scope="internal-poc-evaluation",
    )


def _fixed_transcript(text: str, latency_ms: float):
    def _fn(path: Path) -> Transcript:
        return Transcript(text=text, latency_ms=latency_ms)

    return _fn


def test_compare_entry_computes_wer_cer_for_both_engines() -> None:
    entry = _entry("a1", "áp suất lốp là bao nhiêu")
    phowhisper = _fixed_transcript("nốt cà bao nhiêu", 100.0)
    zipformer = _fixed_transcript("áp suất lốp là bao nhiêu", 50.0)

    result = compare_entry(entry, phowhisper, zipformer)

    assert result["audio_id"] == "a1"
    assert result["zipformer"]["wer"] == 0.0
    assert result["phowhisper"]["wer"] > 0.5
    assert result["zipformer"]["latency_ms"] == 50.0


def test_summarize_computes_averages_and_verdict_below_threshold() -> None:
    case_results = [
        {
            "phowhisper": {"wer": 0.5, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"wer": 0.1, "cer": 0.05, "latency_ms": 50.0},
        },
        {
            "phowhisper": {"wer": 0.3, "cer": 0.2, "latency_ms": 120.0},
            "zipformer": {"wer": 0.1, "cer": 0.05, "latency_ms": 60.0},
        },
    ]

    metrics = summarize(case_results)

    assert metrics["total"] == 2
    assert metrics["zipformer"]["avg_wer"] == 0.1
    assert metrics["verdict"] == "zipformer_candidate"


def test_summarize_verdict_not_better_at_or_above_threshold() -> None:
    case_results = [
        {
            "phowhisper": {"wer": 0.5, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"wer": 0.2, "cer": 0.1, "latency_ms": 50.0},
        },
    ]

    metrics = summarize(case_results)

    assert metrics["verdict"] == "zipformer_not_better"


def test_write_run_outputs_creates_three_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260101T000000Z"
    case_results = [
        {
            "audio_id": "a1",
            "reference_text": "áp suất lốp",
            "phowhisper": {"hypothesis": "x", "wer": 0.5, "cer": 0.4, "latency_ms": 100.0},
            "zipformer": {"hypothesis": "áp suất lốp", "wer": 0.0, "cer": 0.0, "latency_ms": 50.0},
        }
    ]
    metrics = summarize(case_results)

    write_run_outputs(
        run_dir, "20260101T000000Z", Path("eval/datasets/poc/v1/audio/manifest.jsonl"), case_results, metrics
    )

    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "case_results.jsonl").is_file()
    assert (run_dir / "metrics.json").is_file()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_eval_stt_compare.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.eval_stt_compare'`.

- [ ] **Step 3: Implement**

Create `scripts/eval_stt_compare.py`:

```python
"""Phase 1 STT quick eval: compares PhoWhisper-base (current production
engine, via src/services/voice.py) against Zipformer-30M-RNNT-6000h on real
audio for the domain terms currently misrecognized (tire pressure, HVAC,
volume). See docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\eval_stt_compare.py
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from scripts.stt_eval_lib import ManifestEntry, load_manifest_entries
from scripts.zipformer_engine import get_zipformer_engine
from src.services.voice import Transcript, char_error_rate, transcribe_raw, word_error_rate

VERDICT_WER_THRESHOLD = 0.15

EngineFn = Callable[[Path], Transcript]


def compare_entry(entry: ManifestEntry, phowhisper_fn: EngineFn, zipformer_fn: EngineFn) -> dict:
    phowhisper_result = phowhisper_fn(entry.audio_path)
    zipformer_result = zipformer_fn(entry.audio_path)
    return {
        "audio_id": entry.audio_id,
        "reference_text": entry.reference_text,
        "phowhisper": {
            "hypothesis": phowhisper_result.text,
            "wer": word_error_rate(entry.reference_text, phowhisper_result.text),
            "cer": char_error_rate(entry.reference_text, phowhisper_result.text),
            "latency_ms": phowhisper_result.latency_ms,
        },
        "zipformer": {
            "hypothesis": zipformer_result.text,
            "wer": word_error_rate(entry.reference_text, zipformer_result.text),
            "cer": char_error_rate(entry.reference_text, zipformer_result.text),
            "latency_ms": zipformer_result.latency_ms,
        },
    }


def summarize(case_results: list[dict]) -> dict:
    def _avg(engine_key: str, metric_key: str) -> float:
        values = [row[engine_key][metric_key] for row in case_results]
        return sum(values) / len(values) if values else 0.0

    zipformer_avg_wer = _avg("zipformer", "wer")
    return {
        "total": len(case_results),
        "phowhisper": {
            "avg_wer": _avg("phowhisper", "wer"),
            "avg_cer": _avg("phowhisper", "cer"),
            "avg_latency_ms": _avg("phowhisper", "latency_ms"),
        },
        "zipformer": {
            "avg_wer": zipformer_avg_wer,
            "avg_cer": _avg("zipformer", "cer"),
            "avg_latency_ms": _avg("zipformer", "latency_ms"),
        },
        "verdict": "zipformer_candidate" if zipformer_avg_wer < VERDICT_WER_THRESHOLD else "zipformer_not_better",
        "verdict_threshold_wer": VERDICT_WER_THRESHOLD,
    }


def write_run_outputs(
    run_dir: Path, run_id: str, manifest_path: Path, case_results: list[dict], metrics: dict
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "dataset": str(manifest_path),
        "case_count": len(case_results),
        "engines": ["phowhisper-base", "zipformer-30m-rnnt-6000h"],
        "note": (
            "Phase 1 quick eval — audio provenance (synthetic vs. real, speaker count) is "
            "whatever eval/datasets/poc/v1/audio/manifest.jsonl's noise_condition/speaker_code "
            "fields say per entry; not a generalization claim. See "
            "docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md."
        ),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with (run_dir / "case_results.jsonl").open("w", encoding="utf-8") as f:
        for row in case_results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")


def print_comparison_table(case_results: list[dict], metrics: dict) -> None:
    header = f"{'audio_id':<12} {'ph_wer':>8} {'zf_wer':>8} {'ph_ms':>8} {'zf_ms':>8}"
    print(header)
    print("-" * len(header))
    for row in case_results:
        print(
            f"{row['audio_id']:<12} "
            f"{row['phowhisper']['wer']:>8.2%} "
            f"{row['zipformer']['wer']:>8.2%} "
            f"{row['phowhisper']['latency_ms']:>8.0f} "
            f"{row['zipformer']['latency_ms']:>8.0f}"
        )
    print("-" * len(header))
    print(f"{'AVERAGE':<12} {metrics['phowhisper']['avg_wer']:>8.2%} {metrics['zipformer']['avg_wer']:>8.2%}")
    print(f"\nVerdict: {metrics['verdict']} (threshold: zipformer avg WER < {metrics['verdict_threshold_wer']:.0%})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("eval/datasets/poc/v1/audio/manifest.jsonl"))
    parser.add_argument("--audio-dir", type=Path, default=Path("eval/datasets/poc/v1/audio"))
    parser.add_argument("--zipformer-model-dir", type=Path, default=Path("models/voice/zipformer-30m-rnnt-6000h"))
    parser.add_argument("--output-root", type=Path, default=Path("eval/results/stt-compare"))
    args = parser.parse_args()

    entries, warnings = load_manifest_entries(args.manifest, args.audio_dir)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if not entries:
        raise SystemExit("No valid manifest entries found; nothing to evaluate.")

    zipformer_engine = get_zipformer_engine(args.zipformer_model_dir)

    def phowhisper_fn(path: Path) -> Transcript:
        return transcribe_raw(path.read_bytes())

    def zipformer_fn(path: Path) -> Transcript:
        return zipformer_engine.transcribe_file(path)

    case_results = [compare_entry(entry, phowhisper_fn, zipformer_fn) for entry in entries]
    metrics = summarize(case_results)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = args.output_root / run_id
    write_run_outputs(run_dir, run_id, args.manifest, case_results, metrics)
    print_comparison_table(case_results, metrics)
    print(f"\nResults written to {run_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_eval_stt_compare.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and commit**

```bash
.\.venv\Scripts\python.exe -m ruff check scripts/eval_stt_compare.py tests/test_scripts/test_eval_stt_compare.py
.\.venv\Scripts\python.exe -m ruff format scripts/eval_stt_compare.py tests/test_scripts/test_eval_stt_compare.py
git add scripts/eval_stt_compare.py tests/test_scripts/test_eval_stt_compare.py
git commit -m "feat(eval): add PhoWhisper vs Zipformer WER/CER comparison script"
```

---

## Task 6: Domain sentence recording checklist

**Files:**
- Create: `eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md`

**Interfaces:**
- Consumes: nothing (data file).
- Produces: the fixed list of `audio_id` / `reference_text` pairs that Task 7's manifest entries must match, so `load_manifest_entries` (Task 2) reports zero warnings once recording is done.

- [ ] **Step 1: Write the checklist file**

Create `eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md`:

```markdown
# Phase 1 domain-error recording checklist

24 sentences, 1-2 speakers, 16kHz mono WAV each (matches the hard constraint
in `src/services/voice.py:107-121` — re-encode with any tool that can output
16-bit PCM, 16000 Hz, mono if your recorder defaults to something else).

Record each sentence as its own WAV file under this directory (e.g.
`dom-001.wav`), then add one line per file to `manifest.jsonl` following the
schema in this directory's `README.md`. Use the `audio_id` and
`reference_text` exactly as listed below — `reference_text` is what
`word_error_rate`/`char_error_rate` will diff the transcript against, so
match it verbatim (Vietnamese diacritics included) to what was actually
spoken.

| audio_id | domain        | reference_text |
|----------|---------------|-----------------|
| dom-001  | tire_pressure | Áp suất lốp hiện tại là bao nhiêu |
| dom-002  | tire_pressure | Áp suất lốp trước bên trái là bao nhiêu |
| dom-003  | tire_pressure | Kiểm tra áp suất lốp giúp tôi |
| dom-004  | tire_pressure | Lốp sau bên phải có bị non hơi không |
| dom-005  | tire_pressure | Áp suất lốp có đang bình thường không |
| dom-006  | tire_pressure | Lốp trước có cần bơm thêm hơi không |
| dom-007  | hvac          | Bật điều hòa |
| dom-008  | hvac          | Tắt điều hòa |
| dom-009  | hvac          | Đặt điều hòa hai mươi tư độ |
| dom-010  | hvac          | Tăng nhiệt độ điều hòa lên hai mươi sáu độ |
| dom-011  | hvac          | Điều hòa đang để bao nhiêu độ |
| dom-012  | hvac          | Trong xe nóng quá, giảm điều hòa xuống |
| dom-013  | hvac          | Tôi hơi lạnh, tăng điều hòa lên một chút |
| dom-014  | hvac          | Điều hòa có đang bật không |
| dom-015  | volume        | Tăng âm lượng lên bốn mươi |
| dom-016  | volume        | Giảm âm lượng xuống hai mươi |
| dom-017  | volume        | Âm lượng hiện tại là bao nhiêu |
| dom-018  | volume        | Tắt âm lượng |
| dom-019  | volume        | Âm lượng nhạc đang to hay nhỏ |
| dom-020  | baseline      | Phát nhạc |
| dom-021  | baseline      | Mở cửa sổ bên lái |
| dom-022  | baseline      | Đóng cửa sổ bên phụ |
| dom-023  | baseline      | Bật sưởi ghế lái mức hai |
| dom-024  | baseline      | Dẫn đường đến quán cà phê gần nhất |

The `baseline` rows (dom-020..dom-024) are terms already in
`src/services/voice_correction.py`'s `COMMAND_VOCABULARY` and are expected to
transcribe reasonably today — recording them too lets the comparison show
whether Zipformer is better specifically on the *new* failing terms
(tire_pressure/hvac/volume) or uniformly across the board.
```

- [ ] **Step 2: Verify the file is well-formed**

Run: `.\.venv\Scripts\python.exe -c "import re, pathlib; text = pathlib.Path('eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md').read_text(encoding='utf-8'); print(len(re.findall(r'^\| dom-', text, re.MULTILINE)))"`
Expected: `24`.

- [ ] **Step 3: Commit**

```bash
git add eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md
git commit -m "docs(eval): add 24-sentence recording checklist for STT domain eval"
```

---

## Task 7: Synthesize domain audio via Piper TTS and populate the manifest

**Files:**
- Create: `scripts/synthesize_domain_audio.py`
- Create: `tests/test_scripts/test_synthesize_domain_audio.py`

**Interfaces:**
- Consumes: `eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md` (Task 6); `synthesize_wav(text: str) -> bytes` from `src/services/voice.py:200` (existing Piper TTS wrapper, already used in production for `assistant.speech`).
- Produces: `parse_checklist(checklist_path: Path) -> list[tuple[str, str, str]]` (audio_id, domain, reference_text); `synthesize_checklist(checklist_path: Path, audio_dir: Path, manifest_path: Path) -> list[dict]`. Task 8 runs this script's `main()` to populate real WAV files + manifest before the comparison run.

Real human recordings were the original plan, but that step cannot be
automated by an implementer subagent (no microphone, no speaker). Piper TTS
is already wired into this repo for production TTS (`assistant.speech`) and
its model is already downloaded locally (`models/voice/vi_VN-piper.onnx`),
so this task uses it to generate a first, fully-synthetic corpus — unblocking
Phase 1 end-to-end today. Per this repo's own evidence discipline ("synthetic
≠ human" — see `CLAUDE.md` and `docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md`'s
non-goals), every manifest entry this script writes is tagged
`noise_condition: "synthetic-tts"` and `speaker_code: "piper-tts-synthetic"`
so nobody downstream mistakes this run's WER for a human-speaker measurement.
Real recordings can replace individual WAV files later — matched by
`audio_id` — with zero code changes, since `eval_stt_compare.py` only reads
the manifest.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scripts/test_synthesize_domain_audio.py`:

```python
import json
from pathlib import Path

import pytest

from scripts.synthesize_domain_audio import parse_checklist, synthesize_checklist
from src.config import get_settings

_CHECKLIST_FIXTURE = (
    "# heading\n\n"
    "| audio_id | domain        | reference_text |\n"
    "|----------|---------------|-----------------|\n"
    "| dom-001  | tire_pressure | Áp suất lốp hiện tại là bao nhiêu |\n"
    "| dom-002  | hvac          | Bật điều hòa |\n"
)


def _tts_model_available() -> bool:
    return Path(get_settings().tts_model_path).is_file()


def test_parse_checklist_extracts_all_data_rows(tmp_path: Path) -> None:
    checklist_path = tmp_path / "checklist.md"
    checklist_path.write_text(_CHECKLIST_FIXTURE, encoding="utf-8")

    rows = parse_checklist(checklist_path)

    assert rows == [
        ("dom-001", "tire_pressure", "Áp suất lốp hiện tại là bao nhiêu"),
        ("dom-002", "hvac", "Bật điều hòa"),
    ]


def test_parse_checklist_skips_header_and_separator_rows(tmp_path: Path) -> None:
    checklist_path = tmp_path / "checklist.md"
    checklist_path.write_text(_CHECKLIST_FIXTURE, encoding="utf-8")

    rows = parse_checklist(checklist_path)

    assert all(audio_id.startswith("dom-") for audio_id, _, _ in rows)


@pytest.mark.integration
@pytest.mark.skipif(not _tts_model_available(), reason="Piper TTS model not available")
def test_synthesize_checklist_writes_wav_and_manifest(tmp_path: Path) -> None:
    checklist_path = tmp_path / "checklist.md"
    checklist_path.write_text(_CHECKLIST_FIXTURE, encoding="utf-8")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    manifest_path = audio_dir / "manifest.jsonl"

    entries = synthesize_checklist(checklist_path, audio_dir, manifest_path)

    assert (audio_dir / "dom-001.wav").is_file()
    assert (audio_dir / "dom-002.wav").is_file()
    assert len(entries) == 2
    assert entries[0]["audio_id"] == "dom-001"
    assert entries[0]["reference_text"] == "Áp suất lốp hiện tại là bao nhiêu"
    assert entries[0]["speaker_code"] == "piper-tts-synthetic"
    assert entries[0]["noise_condition"] == "synthetic-tts"
    assert entries[0]["duration_ms"] > 0

    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 2
    assert json.loads(manifest_lines[0])["audio_id"] == "dom-001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_synthesize_domain_audio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.synthesize_domain_audio'`.

- [ ] **Step 3: Implement**

Create `scripts/synthesize_domain_audio.py`:

```python
"""Synthesizes the Phase 1 STT domain-eval audio corpus via Piper TTS
(already wired into this repo's production TTS path — see
src/services/voice.py:synthesize_wav). This produces synthetic audio, not
real human speech — see the "Non-goals" section of
docs/superpowers/specs/2026-08-12-stt-domain-eval-design.md. Real recordings
can replace individual WAV files later by audio_id with no code changes.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\synthesize_domain_audio.py
"""

from __future__ import annotations

import argparse
import json
import re
import wave
from pathlib import Path

from src.services.voice import synthesize_wav

CHECKLIST_ROW_PATTERN = re.compile(r"^\|\s*(dom-\d+)\s*\|\s*([a-z_]+)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)

DEFAULT_CHECKLIST = Path("eval/datasets/poc/v1/audio/RECORDING_CHECKLIST.md")
DEFAULT_AUDIO_DIR = Path("eval/datasets/poc/v1/audio")
DEFAULT_MANIFEST = DEFAULT_AUDIO_DIR / "manifest.jsonl"


def parse_checklist(checklist_path: Path) -> list[tuple[str, str, str]]:
    text = checklist_path.read_text(encoding="utf-8")
    return [(audio_id, domain, reference_text) for audio_id, domain, reference_text in CHECKLIST_ROW_PATTERN.findall(text)]


def _wav_duration_ms(wav_path: Path) -> int:
    with wave.open(str(wav_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
    return round(frames / rate * 1000)


def synthesize_checklist(checklist_path: Path, audio_dir: Path, manifest_path: Path) -> list[dict]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for audio_id, _domain, reference_text in parse_checklist(checklist_path):
        wav_path = audio_dir / f"{audio_id}.wav"
        wav_path.write_bytes(synthesize_wav(reference_text))
        entries.append(
            {
                "audio_id": audio_id,
                "path": wav_path.name,
                "reference_text": reference_text,
                "speaker_code": "piper-tts-synthetic",
                "region": "n/a",
                "noise_condition": "synthetic-tts",
                "duration_ms": _wav_duration_ms(wav_path),
                "consent_scope": "internal-poc-evaluation",
            }
        )
    with manifest_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    entries = synthesize_checklist(args.checklist, args.audio_dir, args.manifest)
    print(f"Synthesized {len(entries)} WAV files under {args.audio_dir}, wrote {args.manifest}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scripts/test_synthesize_domain_audio.py -v`
Expected: 3 passed (the integration test runs for real — Piper's model is already present locally at `models/voice/vi_VN-piper.onnx` per `src/config.py`'s `tts_model_path` default — this is not a skip in this repo's current state).

- [ ] **Step 5: Run it for real against the actual checklist**

Run: `.\.venv\Scripts\python.exe scripts\synthesize_domain_audio.py`
Expected: `Synthesized 24 WAV files under eval/datasets/poc/v1/audio, wrote eval/datasets/poc/v1/audio/manifest.jsonl`. Then verify with Task 2's loader:

```
.\.venv\Scripts\python.exe -c "from pathlib import Path; from scripts.stt_eval_lib import load_manifest_entries; entries, warnings = load_manifest_entries(Path('eval/datasets/poc/v1/audio/manifest.jsonl'), Path('eval/datasets/poc/v1/audio')); print(len(entries), 'entries,', len(warnings), 'warnings')"
```

Expected: `24 entries, 0 warnings`.

- [ ] **Step 6: Lint and commit**

```bash
.\.venv\Scripts\python.exe -m ruff check scripts/synthesize_domain_audio.py tests/test_scripts/test_synthesize_domain_audio.py
.\.venv\Scripts\python.exe -m ruff format scripts/synthesize_domain_audio.py tests/test_scripts/test_synthesize_domain_audio.py
git add scripts/synthesize_domain_audio.py tests/test_scripts/test_synthesize_domain_audio.py eval/datasets/poc/v1/audio/
git commit -m "feat(eval): synthesize domain-eval audio corpus via Piper TTS"
```

---

## Task 8: End-to-end run and report

**Files:** none (verification only — this task runs the pipeline built in Tasks 1-7 and reports the result; no new source files).

This task is fully automatable now that Task 7 synthesizes its own audio —
no human step remains. Its deliverable is the printed verdict and the
`eval/results/stt-compare/<run-id>/` directory, not a code change.

- [ ] **Step 1: Download the Zipformer model for real**

Run: `.\.venv\Scripts\python.exe scripts\download_zipformer_model.py`
Expected: prints `Downloaded: ...` four times (encoder/decoder/joiner/tokens), no errors. Confirm `models/voice/zipformer-30m-rnnt-6000h/` now has the four files plus their `.sha256`/`.metadata.json` sidecars.

- [ ] **Step 2: Run the full comparison**

Run: `.\.venv\Scripts\python.exe scripts\eval_stt_compare.py`
Expected: no `WARNING:` lines (Task 7 already verified the manifest loads with zero warnings), a comparison table printed for all 24 cases, and a `Results written to eval/results/stt-compare/<run-id>` line.

- [ ] **Step 3: Report the verdict in the task report**

In the implementer's report file, quote the full contents of
`eval/results/stt-compare/<run-id>/metrics.json` verbatim (this is how the
controller and the human partner learn the result — do not summarize or
round the numbers) and state the `run_id`. Do not interpret the verdict or
write to `WORKLOG.md` — that is the human partner's call once real data
(synthetic-only, this run) is in front of them, per this repo's "synthetic ≠
human" evidence discipline.

- [ ] **Step 4: Commit the results directory**

```bash
git add eval/results/stt-compare/
git commit -m "chore(eval): record Phase 1 STT comparison run (synthetic Piper TTS corpus)"
```

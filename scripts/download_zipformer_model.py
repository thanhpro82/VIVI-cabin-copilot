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
from datetime import UTC, datetime
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
            "downloaded_at_utc": datetime.now(UTC).isoformat(),
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

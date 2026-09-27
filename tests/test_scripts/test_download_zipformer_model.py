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

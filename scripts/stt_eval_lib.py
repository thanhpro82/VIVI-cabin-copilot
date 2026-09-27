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
        # A manifest is data, not code: a `path` of "../../secrets.wav" must not
        # let an entry reach outside the corpus directory. Treated as a skip,
        # not a raise, for the same reason as the other malformed-line cases.
        if not audio_path.is_relative_to(audio_dir.resolve()):
            warnings.append(f"line {line_number}: audio file not found at {audio_path} (outside {audio_dir})")
            continue
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

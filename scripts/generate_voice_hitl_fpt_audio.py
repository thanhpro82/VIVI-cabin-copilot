"""Generates FPT Voice Maker synthetic audio for the 10 HITL confirmation
phrases (issue #198, part 2), across multiple voices/regions for a first-pass
directional WER check with scripts/eval_voice_hitl_wer.py.

This is synthetic audio, same category as Piper. Per the wake-word FPT
generator's own precedent (docs/wake_word_fpt_dataset.md on
feature/vivi-browser-wake-word: "does not satisfy the acceptance gate"), a
run built from this dataset does not satisfy issue #198's WER gate — that
still requires real human speech. Fine for a first directional pass while
real recordings are collected.

Set FPT_API_KEY only in ignored .env or the local process environment; this
script never accepts a key argument, logs it, or writes it to any output
file.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\generate_voice_hitl_fpt_audio.py
"""

from __future__ import annotations

import argparse
import io
import json
import os
import urllib.error
import urllib.request
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENDPOINT = "https://mkp-api.fptcloud.com/v1/audio/speech"
DEFAULT_MODEL = "FPT.AI-VITs"
SAMPLE_RATE = 16000

PHRASES: tuple[str, ...] = (
    "đồng ý",
    "xác nhận",
    "chấp nhận",
    "duyệt",
    "từ chối",
    "hủy",
    "đừng",
    "thôi",
    "không",
    "không đồng ý",
)

# Nine FPT Voice Maker voices spanning all three regions and both genders.
VOICE_REGIONS: dict[str, str] = {
    "std_leminh": "north",
    "std_kimngan": "south",
    "std_banmai": "north",
    "std_hatieumai": "south",
    "std_ngoclam": "central",
    "std_thuminh": "north",
    "std_giahuy": "south",
    "std_huyphong": "north",
    "std_minhquan": "north",
}

HttpPost = Callable[[dict], bytes]


@dataclass(frozen=True)
class SynthRequest:
    audio_id: str
    reference_text: str
    voice_code: str
    region: str


def build_requests(phrases: tuple[str, ...], voice_regions: dict[str, str]) -> list[SynthRequest]:
    requests = []
    for phrase_index, phrase in enumerate(phrases, start=1):
        for voice_code, region in voice_regions.items():
            requests.append(
                SynthRequest(
                    audio_id=f"hitl-{phrase_index:02d}-{voice_code}",
                    reference_text=phrase,
                    voice_code=voice_code,
                    region=region,
                )
            )
    return requests


def request_payload(reference_text: str, voice_code: str, model: str = DEFAULT_MODEL) -> dict:
    return {
        "model": model,
        "input": reference_text,
        "voice": voice_code,
        "sample_rate": SAMPLE_RATE,
        "response_format": "wav",
    }


def validate_wav_16k_mono(body: bytes) -> None:
    try:
        with wave.open(io.BytesIO(body), "rb") as handle:
            if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
                raise ValueError("FPT response WAV must be 16 kHz mono")
    except wave.Error as exc:
        raise ValueError("FPT response was not a valid WAV") from exc


def wav_duration_ms(body: bytes) -> int:
    with wave.open(io.BytesIO(body), "rb") as handle:
        return round(1000 * handle.getnframes() / handle.getframerate())


def manifest_line(request: SynthRequest, *, relative_path: str, duration_ms: int) -> dict:
    return {
        "audio_id": request.audio_id,
        "path": relative_path,
        "reference_text": request.reference_text,
        "speaker_code": request.voice_code,
        "region": request.region,
        "noise_condition": "synthetic-tts",
        "duration_ms": duration_ms,
        "consent_scope": "internal-poc-evaluation",
    }


def _default_http_post(payload: dict, *, endpoint: str, api_key: str) -> bytes:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"FPT request failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OSError("FPT request transport failure") from exc


def write_dataset(requests: list[SynthRequest], http_post: HttpPost, output_dir: Path) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_lines = []
    for request in requests:
        payload = request_payload(request.reference_text, request.voice_code)
        try:
            body = http_post(payload)
            validate_wav_16k_mono(body)
        except Exception as exc:  # noqa: BLE001 - one bad phrase/voice must not abort the batch
            print(f"WARNING: skipping {request.audio_id}: {type(exc).__name__}: {exc}")
            continue
        filename = f"{request.audio_id}.wav"
        (output_dir / filename).write_bytes(body)
        manifest_lines.append(manifest_line(request, relative_path=filename, duration_ms=wav_duration_ms(body)))

    with (output_dir / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for line in manifest_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return manifest_lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/datasets/voice-hitl-confirmation/v1/audio"))
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args()

    api_key = os.environ.get("FPT_API_KEY")
    if not api_key:
        raise SystemExit("FPT_API_KEY not set (put it in .env or the process environment).")

    requests = build_requests(PHRASES, VOICE_REGIONS)
    print(f"Synthesizing {len(requests)} clips ({len(PHRASES)} phrases x {len(VOICE_REGIONS)} voices)...")

    def http_post(payload: dict) -> bytes:
        return _default_http_post(payload, endpoint=args.endpoint, api_key=api_key)

    manifest_lines = write_dataset(requests, http_post, args.output_dir)
    print(f"Wrote {len(manifest_lines)}/{len(requests)} clips + manifest to {args.output_dir}")


if __name__ == "__main__":
    main()

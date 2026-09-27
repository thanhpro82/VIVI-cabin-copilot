"""One-off script: generates fixed 16kHz mono WAV fixtures from Piper.

`PiperEngine.synthesize()` is not deterministic across calls (confirmed
2026-08-07: same text, two calls, two different audio byte counts), which
made the live-loopback WER test unreproducible. This script freezes a set
of Piper outputs once so the test measures WER against a stable input.

Run locally (requires TTS_MODEL_PATH to point at a real Piper voice —
see scripts/setup_voice_models.ps1):

    python scripts/generate_voice_wer_fixtures.py --bo lenh
    python scripts/generate_voice_wer_fixtures.py --bo cham_slm

Commit the resulting files under tests/fixtures/voice/<bo>/.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from src.services.voice import get_tts_engine, synthesize

#: Bộ `lenh` — 5 câu điều khiển, cho test WER loopback (AC2).
#:
#: **Đừng sinh lại bộ này nếu không thật sự cần.** Piper không tất định giữa các lần
#: gọi (xem docstring), nên sinh lại là đổi chính cái đầu vào mà test WER đang đo, và
#: số WER cũ hết so sánh được.
SENTENCES = [
    "Bật điều hòa",
    "Đặt điều hòa hai mươi bốn độ",
    "Mở cửa sổ bên phụ một nửa",
    "Tăng nhiệt độ lên hai mươi sáu độ",
    "Bật sưởi ghế lái mức hai",
]

#: Bộ `cham_slm` — câu **trượt luật router**, để đo đường thoại có thật sự đi qua SLM.
#:
#: Vì sao cần bộ thứ hai: cả 5 câu bộ `lenh` đều khớp luật tất định, nên đo bằng chúng
#: là đo STT → router → executor → TTS và **không bao giờ chạm model**. Điều kiện 3 của
#: PM/PO review PR #257 đòi đo end-to-end *gồm cả STT/TTS*, mà phần đắt nhất của lượt
#: thật lại nằm ở SLM — đo bằng bộ `lenh` sẽ ra một con số đẹp về một đường không ai
#: hỏi tới.
#:
#: Ba nhóm, cùng nhãn với `CASES` trong `scripts/do_luot_that_dong_thoi.py`, để hai
#: phép đo (text và voice) so được với nhau theo từng đường.
CAU_CHAM_SLM = [
    # so_tay: classify → RAG. RAG không dùng llama-server.
    "Xe này sạc nhanh mất bao lâu",
    "Áp suất lốp tiêu chuẩn là bao nhiêu",
    # planner: đường đắt nhất, và là đường duy nhất không có lối vòng.
    "Làm cho trong xe dễ chịu hơn tí đi",
    "Trong xe ngột ngạt quá, xử lý giúp tôi",
    # chitchat.
    "Chào xe, hôm nay thế nào",
]

FIXTURE_ROOT = Path(__file__).parent.parent / "tests" / "fixtures" / "voice"

#: `--bo` chọn bộ nào. Tiền tố tên file khác nhau để hai bộ không bao giờ đè lên nhau.
BO_CAU: dict[str, tuple[str, list[str], str]] = {
    "lenh": ("synthetic_commands", SENTENCES, "command"),
    "cham_slm": ("cham_slm", CAU_CHAM_SLM, "cau"),
}

TARGET_SAMPLE_RATE = 16000


def _resample_to_16k_mono(pcm_bytes: bytes, source_rate: int) -> bytes:
    if source_rate == TARGET_SAMPLE_RATE:
        return pcm_bytes
    audio = np.frombuffer(pcm_bytes, dtype=np.int16)
    duration_s = len(audio) / source_rate
    target_len = int(round(duration_s * TARGET_SAMPLE_RATE))
    source_index = np.linspace(0, len(audio) - 1, num=len(audio))
    target_index = np.linspace(0, len(audio) - 1, num=target_len)
    return np.interp(target_index, source_index, audio).astype(np.int16).tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sinh WAV fixture 16kHz mono bang Piper")
    # KHONG co mac dinh: sinh lai bo `lenh` la doi dau vao cua test WER, nen phai la
    # mot lua chon co y thuc chu khong phai hau qua cua viec go thieu tham so.
    parser.add_argument("--bo", choices=sorted(BO_CAU), required=True)
    args = parser.parse_args()

    thu_muc, cau_list, tien_to = BO_CAU[args.bo]
    if args.bo == "lenh":
        print("CANH BAO: sinh lai bo `lenh` — Piper khong tat dinh, so WER cu se het so sanh duoc.")

    output_dir = FIXTURE_ROOT / thu_muc
    output_dir.mkdir(parents=True, exist_ok=True)
    source_rate = get_tts_engine().sample_rate
    manifest = []
    for index, sentence in enumerate(cau_list):
        pcm_bytes = _resample_to_16k_mono(b"".join(synthesize(sentence)), source_rate)
        filename = f"{tien_to}_{index:02d}.wav"
        output_path = output_dir / filename
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(TARGET_SAMPLE_RATE)
            wav_file.writeframes(pcm_bytes)
        manifest.append({"file": filename, "text": sentence})
        print(f"wrote {output_path} ({len(pcm_bytes)} bytes) for: {sentence!r}")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()

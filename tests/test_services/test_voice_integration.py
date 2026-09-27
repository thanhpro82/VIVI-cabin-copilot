from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.config import get_settings
from src.services.voice import get_stt_engine, transcribe_raw, word_error_rate

pytestmark = pytest.mark.integration

_WARM_SAMPLE_PATH = Path(__file__).parent.parent / "fixtures" / "voice" / "warm_sample.wav"
_SYNTHETIC_COMMANDS_DIR = Path(__file__).parent.parent / "fixtures" / "voice" / "synthetic_commands"
_SYNTHETIC_COMMANDS_MANIFEST = _SYNTHETIC_COMMANDS_DIR / "manifest.json"


def _assets_available() -> bool:
    settings = get_settings()
    return Path(settings.stt_model_path).is_dir() and Path(settings.tts_model_path).is_file()


def _warm_sample_available() -> bool:
    return _assets_available() and _WARM_SAMPLE_PATH.is_file()


def _synthetic_commands_available() -> bool:
    return _assets_available() and _SYNTHETIC_COMMANDS_MANIFEST.is_file()


def _tts_model_available() -> bool:
    """Riêng cho test provider: nó chỉ nạp Piper, không cần model STT lẫn fixture WAV."""
    return Path(get_settings().tts_model_path).is_file()


@pytest.fixture(scope="session", autouse=True)
def _clear_stt_engine_cache_after_session():
    yield
    get_stt_engine.cache_clear()


@pytest.mark.skipif(not _warm_sample_available(), reason="voice model assets or warm_sample.wav fixture not available")
def test_transcribe_warm_latency_is_under_budget() -> None:
    # Reference sentence must be pre-recorded at tests/fixtures/voice/warm_sample.wav
    # (16kHz mono WAV, "đặt điều hòa hai mươi bốn độ").
    audio_bytes = _WARM_SAMPLE_PATH.read_bytes()

    get_stt_engine()  # loads the model into memory
    transcribe_raw(audio_bytes)  # first call, discarded (excludes model-load variance)

    started = time.perf_counter()
    result = transcribe_raw(audio_bytes)
    wall_ms = (time.perf_counter() - started) * 1000

    # Budget: measured warm-call average was 120.4ms on this dev
    # machine (5-sample average, see ADR-017's real-benchmark section). Budget is
    # that value rounded up to the nearest 50ms, doubled for headroom — not the
    # measured figure itself, since dev-machine timing varies run to run.
    assert wall_ms < 300, f"warm transcribe took {wall_ms:.1f}ms, budget is 300ms"
    assert result.text


@pytest.mark.skipif(
    not _synthetic_commands_available(), reason="voice model assets or synthetic command fixtures not available"
)
def test_synthetic_loopback_word_error_rate_is_under_budget() -> None:
    manifest = json.loads(_SYNTHETIC_COMMANDS_MANIFEST.read_text(encoding="utf-8"))

    get_stt_engine()

    rates: list[float] = []
    for entry in manifest:
        audio_path = _SYNTHETIC_COMMANDS_DIR / entry["file"]
        result = transcribe_raw(audio_path.read_bytes())
        rates.append(word_error_rate(entry["text"], result.text))

    average_wer = sum(rates) / len(rates)
    # This is a synthetic-audio smoke check (fixed Piper output fed back
    # through the STT engine), not a real-speaker accuracy benchmark — see
    # ADR-017 and the Phase 1 design spec's WER caveat.
    #
    # Budget: measured average was 9.17% on this fixture (see
    # ADR-017's real-benchmark section). Budget is that value plus 5 percentage
    # points, rounded up to the nearest whole percent — headroom against
    # dev-machine/run variance, not the measured figure itself. The fixture only
    # has 5 entries, so this average has limited statistical power — one
    # regressed case swings it by up to 20 percentage points.
    assert average_wer < 0.15, f"synthetic loopback WER {average_wer:.2%} exceeds 15% budget (ADR-017)"


# --- Execution provider cua ONNX runtime ------------------------------------


#: Provider **goi ra mang**. `onnxruntime` 1.28 nap san `AzureExecutionProvider` va no
#: dung DAU danh sach uu tien tren may nay:
#:
#:     >>> onnxruntime.get_available_providers()
#:     ['AzureExecutionProvider', 'CPUExecutionProvider']
#:
#: Nam im neu khong ai chon, nhung day la du an co bat bien "No network at runtime"
#: (ADR-001), va mot bat bien khong ai kiem thi khong phai bat bien.
_PROVIDER_GOI_MANG = frozenset({"AzureExecutionProvider"})


@pytest.mark.skipif(not _tts_model_available(), reason="chưa có model Piper cục bộ")
def test_piper_khong_bao_gio_nap_provider_goi_ra_mang():
    """Đo thật trên máy có model (14/08): Piper nạp đúng `['CPUExecutionProvider']`.

    Test này **không** sửa một lỗi đang có — nó khoá một điều đang đúng. Lý do đáng
    khoá: thứ chọn provider không phải code của chúng ta mà là mặc định của
    `onnxruntime` cộng thứ tự nó liệt kê, và cả hai đổi được qua một lần nâng phiên bản
    mà không ai trong nhóm nhận ra. Nếu ngày đó tới, đây là chỗ báo.
    """
    from piper import PiperVoice

    voice = PiperVoice.load(str(get_settings().tts_model_path))
    session = _tim_session(voice)
    assert session is not None, "khong tim thay ONNX session trong PiperVoice — cau truc thu vien da doi"

    dang_dung = set(session.get_providers())
    assert not (dang_dung & _PROVIDER_GOI_MANG), f"dang dung provider goi mang: {dang_dung}"
    assert dang_dung == {"CPUExecutionProvider"}, dang_dung


def _tim_session(voice):
    """`PiperVoice` không hứa tên thuộc tính nào cho session, nên dò thay vì giả định."""
    for ten in ("session", "_session", "ort_session", "model"):
        doi_tuong = getattr(voice, ten, None)
        if doi_tuong is None:
            continue
        if hasattr(doi_tuong, "get_providers"):
            return doi_tuong
        for ten_trong in ("session", "_session", "ort_session"):
            ben_trong = getattr(doi_tuong, ten_trong, None)
            if ben_trong is not None and hasattr(ben_trong, "get_providers"):
                return ben_trong
    return None

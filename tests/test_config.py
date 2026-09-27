from src.config import Settings


def test_voice_settings_have_canonical_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.stt_provider == "sherpa_onnx"
    assert settings.stt_model_path == "./models/voice/zipformer-30m-rnnt-6000h"
    assert settings.stt_compute_type == "int8"
    assert settings.stt_max_audio_seconds == 30
    assert settings.tts_provider == "piper"
    assert settings.tts_model_path == "./models/voice/vi_VN-piper.onnx"


def test_voice_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("STT_MODEL_PATH", "/custom/model-dir")
    monkeypatch.setenv("TTS_MODEL_PATH", "/custom/voice.onnx")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "float32")

    settings = Settings(_env_file=None)

    assert settings.stt_model_path == "/custom/model-dir"
    assert settings.tts_model_path == "/custom/voice.onnx"
    assert settings.stt_compute_type == "float32"


def test_health_probe_settings_have_canonical_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.health_probe_timeout_s == 5.0
    assert settings.health_voice_probe_ttl_s == 10.0


def test_health_probe_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("HEALTH_PROBE_TIMEOUT_S", "2.5")
    monkeypatch.setenv("HEALTH_VOICE_PROBE_TTL_S", "15")

    settings = Settings(_env_file=None)

    assert settings.health_probe_timeout_s == 2.5
    assert settings.health_voice_probe_ttl_s == 15.0


def test_suite_luon_chay_voi_slm_tat(monkeypatch) -> None:
    """Lưới cho chính bản ghim ở `tests/conftest.py` (issue #146).

    Ba test khoá hành vi mặc định P0 nằm rải ở ba file khác nhau
    (`test_session_state.py`, `test_traces.py`, `test_ws_engineer_events.py`). Gỡ bản
    ghim ra thì cả ba đỏ cùng lúc với những thông báo chẳng nhắc gì tới `.env` — người
    sửa sẽ đi tìm bug trong code. Test này đỏ trước và nói thẳng nguyên nhân.

    Đọc từ `Settings()` chứ không đọc `os.environ`: thứ đáng khoá là **giá trị hệ thống
    thật sự thấy**, mà pydantic-settings còn trộn cả `.env` vào đó.
    """
    from src.config import Settings

    assert Settings().slm_enabled is False, (
        "suite phải chạy với SLM tắt — kiểm dòng `os.environ['SLM_ENABLED']` trong tests/conftest.py"
    )

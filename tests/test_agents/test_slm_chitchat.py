"""Vai chitchat: prompt riêng, một lượt gọi, ép JSON. Cổng nội dung nằm ở
`nodes/chitchat_cong.py`, KHÔNG ở đây — client chỉ lấy chữ về."""

import json

import pytest

from src.agents.slm import (
    CHITCHAT_MAX_CHARS,
    CHITCHAT_SCHEMA,
    CHITCHAT_SYSTEM,
    QwenChitchat,
    SlmSchemaError,
    parse_chitchat_output,
)


def test_parse_lay_reply():
    assert parse_chitchat_output(json.dumps({"reply": "Chào bạn!"})) == "Chào bạn!"


def test_parse_rong_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_chitchat_output('{"reply": "   "}')


def test_parse_khong_json_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_chitchat_output("Chào bạn")


def test_schema_tran_do_dai_bang_max_chars():
    assert CHITCHAT_SCHEMA["properties"]["reply"]["maxLength"] == CHITCHAT_MAX_CHARS
    assert CHITCHAT_SCHEMA["required"] == ["reply"]


def test_prompt_khoa_hai_ranh_gioi_do_duoc_o_sp0():
    """Hai ví dụ bắt buộc của spec §2.1: từ chối thời tiết, không nói số km/sạc."""
    assert "mưa" in CHITCHAT_SYSTEM
    assert "sạc" in CHITCHAT_SYSTEM
    assert "KHÔNG" in CHITCHAT_SYSTEM


def test_qwen_chitchat_gui_dung_cau_hinh(monkeypatch):
    sent = {}

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": '{"reply": "Chào bạn, đi đâu hôm nay?"}'}

    def _post(url, json=None, timeout=None):
        sent.update(url=url, body=json, timeout=timeout)
        return _R()

    import httpx

    monkeypatch.setattr(httpx, "post", _post)
    w = QwenChitchat("http://127.0.0.1:8093", "qwen3-4b", timeout_s=4.0)
    assert w.reply("Xin chào") == "Chào bạn, đi đâu hôm nay?"
    assert sent["url"].endswith("/completion")
    assert sent["body"]["json_schema"] == CHITCHAT_SCHEMA
    assert 0 < sent["body"]["temperature"] <= 0.5  # không 0: trò chuyện lặp y hệt nghe như máy
    assert sent["body"]["cache_prompt"] is True
    assert sent["body"]["n_predict"] <= 96
    assert sent["timeout"] == 4.0
    assert "Xin chào" in sent["body"]["prompt"]

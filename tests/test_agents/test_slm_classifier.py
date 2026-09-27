"""Vai classify của SP-1: chỉ phân loại, không sinh chữ, không tạo plan.

Grammar (`json_schema` enum) ép ở tầng sinh nên model không trả nổi chuỗi hỏng;
các test parse ở đây gác đường HTTP 500 / payload rỗng mà grammar không cứu được.
"""

import json

import pytest

from src.agents.slm import CLASSIFY_INTENTS, CLASSIFY_SCHEMA, QwenClassifier, SlmSchemaError, parse_classify_output


def test_parse_du_ba_lop():
    for intent in CLASSIFY_INTENTS:
        assert parse_classify_output(json.dumps({"intent": intent})) == intent


def test_parse_intent_la_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_classify_output('{"intent": "navigate"}')


def test_parse_khong_phai_json_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_classify_output("control")


def test_parse_rong_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_classify_output("")


def test_schema_ep_enum_ngay_tang_sinh():
    """Enum nằm trong schema gửi cho llama-server — hết lớp lỗi parse tự do."""
    assert CLASSIFY_SCHEMA["properties"]["intent"]["enum"] == list(CLASSIFY_INTENTS)
    assert CLASSIFY_SCHEMA["required"] == ["intent"]


def test_qwen_classifier_gui_dung_cau_hinh(monkeypatch):
    """temperature 0 + grammar + cache_prompt: cấu hình là hợp đồng, không phải tuỳ hứng."""
    sent = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": '{"intent": "manual"}'}

    def _fake_post(url, json=None, timeout=None):
        sent["url"] = url
        sent["body"] = json
        sent["timeout"] = timeout
        return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "post", _fake_post)
    classifier = QwenClassifier("http://127.0.0.1:8093", "qwen3-4b", timeout_s=2.0)
    assert classifier.classify("Nóng quá, giảm nhiệt độ xuống đi") == "manual"
    assert sent["url"].endswith("/completion")
    assert sent["body"]["temperature"] == 0
    assert sent["body"]["json_schema"] == CLASSIFY_SCHEMA
    assert sent["body"]["cache_prompt"] is True
    assert sent["body"]["n_predict"] <= 32
    assert sent["timeout"] == 2.0
    assert "Nóng quá" in sent["body"]["prompt"]


def test_luoi_an_toan_ha_cau_hoi_kha_nang_ve_manual():
    """Lưới tất định SAU classifier: hỏi "... được không" mà model chấm control
    thì hạ về manual — vì planner có thể ra plan S1 chạy luôn cho một CÂU HỎI.
    Ca thật: "Bật điều hòa từ xa trước khi ra xe được không" (run 20260821T125637)."""
    from src.agents.slm import ap_luoi_an_toan

    assert ap_luoi_an_toan("control", "Bật điều hòa từ xa trước khi ra xe được không") == "manual"
    assert ap_luoi_an_toan("control", "Xe có tự đỗ được không?") == "manual"
    # Mệnh lệnh thật thì giữ nguyên — lưới không được nuốt lệnh.
    assert ap_luoi_an_toan("control", "Nóng quá, giảm nhiệt độ xuống đi") == "control"
    assert ap_luoi_an_toan("control", "Hạ kính hộ cái") == "control"
    # Lưới chỉ đụng control — manual/chitchat đi qua nguyên vẹn.
    assert ap_luoi_an_toan("manual", "Áp suất lốp bao nhiêu?") == "manual"
    assert ap_luoi_an_toan("chitchat", "Chào nhé, đi đây, được không ta") == "chitchat"


def test_luoi_an_toan_mien_ngoai_tam_ve_manual():
    """Miền KHÔNG điều khiển được (không tool trong registry — coverage_matrix.md)
    mà model chấm control thì hạ về manual: câu trả lời sổ tay có ích hơn một
    clarify ngõ cụt. Ca thật run 20260821T130203: "gạt nước", "ngôn ngữ"."""
    from src.agents.slm import ap_luoi_an_toan

    assert ap_luoi_an_toan("control", "Trời mưa lất phất muốn gạt nước chậm lại") == "manual"
    assert ap_luoi_an_toan("control", "Đổi ngôn ngữ trên xe sang tiếng Anh") == "manual"
    assert ap_luoi_an_toan("control", "Bật ga tự động đi") == "manual"
    assert ap_luoi_an_toan("control", "Bật đèn sương mù lên") == "manual"
    # Miền có tool thật thì lưới không được đụng.
    assert ap_luoi_an_toan("control", "Bật đèn trần lên") == "control"
    assert ap_luoi_an_toan("control", "Mở cốp giùm") == "control"

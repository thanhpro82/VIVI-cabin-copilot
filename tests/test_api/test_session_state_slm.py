"""slm_enabled gác luôn classifier — một cờ, các vai đi cùng nhau (spec SP-1 §3.2)."""

import pytest

from src.api import session_state
from src.config import get_settings


@pytest.fixture(autouse=True)
def _don_cache_settings():
    """Mỗi test tự đổi env nên cache settings phải sạch cả trước lẫn sau."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_slm_enabled_bat_thi_graph_co_node_classify(monkeypatch):
    monkeypatch.setenv("SLM_ENABLED", "true")
    graph = session_state.get_graph("phien-test-classify-bat")
    assert "slm_classify" in graph.get_graph().nodes


def test_slm_enabled_tat_thi_khong_co(monkeypatch):
    monkeypatch.setenv("SLM_ENABLED", "false")
    graph = session_state.get_graph("phien-test-classify-tat")
    assert "slm_classify" not in graph.get_graph().nodes


def test_timeout_classify_mac_dinh_2s(monkeypatch):
    monkeypatch.delenv("SLM_CLASSIFY_TIMEOUT_S", raising=False)
    assert get_settings().slm_classify_timeout_s == 2.0


def test_slm_enabled_bat_thi_graph_co_node_chitchat(monkeypatch):
    monkeypatch.setenv("SLM_ENABLED", "true")
    graph = session_state.get_graph("phien-test-chitchat-bat")
    assert "chitchat" in graph.get_graph().nodes

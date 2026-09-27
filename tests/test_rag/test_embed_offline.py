"""`E5Embedder` không được chạm mạng lúc khởi tạo.

ADR-001: "Internet chỉ được dùng **trước** runtime để cài dependency/tải artifact.
Offline drill tắt network và là release gate." Và `docs/demo_script.md` mở màn bằng
thao tác tắt mạng ở giây thứ 0 — nên một lệnh gọi HF Hub lúc khởi động không chỉ vi
phạm ADR, nó làm treo đúng bài demo được chấm điểm.

Đo trên máy dev 2026-08-13: thiếu `local_files_only=True` thì `python -m src.serve`
sinh ~20 request HEAD/GET tới huggingface.co, dù weight đã nằm sẵn trong cache.

Test chạy bằng module `sentence_transformers` giả nên **không cần torch, không cần
model** — đúng lý do `tests/test_rag/` chạy được trên CI.
"""

import sys
from types import ModuleType

import pytest

from src.rag.embed import MODEL_NAME, E5Embedder


class _FakeSentenceTransformer:
    """Ghi lại tham số mà `E5Embedder` truyền vào, không tải gì."""

    last_args: tuple = ()
    last_kwargs: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        type(self).last_args = args
        type(self).last_kwargs = kwargs


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    """Chèn `sentence_transformers` giả — import nằm trong `__init__` nên phải thay ở
    `sys.modules` chứ không monkeypatch được thuộc tính của `src.rag.embed`."""
    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    _FakeSentenceTransformer.last_args = ()
    _FakeSentenceTransformer.last_kwargs = {}
    return _FakeSentenceTransformer


def test_e5_embedder_loads_from_local_cache_only(fake_sentence_transformers):
    """Đây là bất biến, không phải tuỳ chọn hiệu năng — xem docstring đầu file."""
    E5Embedder()
    assert fake_sentence_transformers.last_kwargs.get("local_files_only") is True, (
        "thiếu local_files_only=True thì embedder gọi HF Hub mỗi lần khởi động, "
        "vi phạm ADR-001 và làm treo offline drill"
    )


def test_e5_embedder_still_passes_the_model_name(fake_sentence_transformers):
    """Chốt luôn tham số đầu, để lần sau ai thêm kwarg không vô tình đổi model."""
    E5Embedder()
    assert fake_sentence_transformers.last_args == (MODEL_NAME,)


def test_e5_embedder_honours_an_explicit_model_name(fake_sentence_transformers):
    E5Embedder(model_name="intfloat/multilingual-e5-base")
    assert fake_sentence_transformers.last_args == ("intfloat/multilingual-e5-base",)
    assert fake_sentence_transformers.last_kwargs.get("local_files_only") is True

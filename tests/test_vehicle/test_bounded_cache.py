"""BoundedCache — bảng idempotency có trần."""

from __future__ import annotations

import pytest

from src.bounded_cache import DEFAULT_MAXSIZE, BoundedCache


def test_day_ra_ban_cu_nhat_khi_vuot_tran():
    cache: BoundedCache[str, int] = BoundedCache(maxsize=2)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    assert len(cache) == 2
    assert "a" not in cache
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_doc_trung_thi_day_len_moi_nhat():
    """LRU chứ không phải FIFO — key vừa đọc không được là key bị đẩy ra."""
    cache: BoundedCache[str, int] = BoundedCache(maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)

    cache.get("a")  # "a" thành mới nhất, "b" thành cũ nhất
    cache.set("c", 3)

    assert "a" in cache
    assert "b" not in cache


def test_ghi_de_cung_key_khong_lam_phinh():
    cache: BoundedCache[str, int] = BoundedCache(maxsize=2)

    for value in range(10):
        cache.set("a", value)

    assert len(cache) == 1
    assert cache.get("a") == 9


def test_key_khong_ton_tai_tra_none():
    cache: BoundedCache[str, int] = BoundedCache(maxsize=2)

    assert cache.get("khong_co") is None


def test_maxsize_phai_duong():
    with pytest.raises(ValueError):
        BoundedCache(maxsize=0)


def test_tran_mac_dinh_du_lon_cho_mot_phien_demo():
    assert BoundedCache().maxsize == DEFAULT_MAXSIZE
    assert DEFAULT_MAXSIZE >= 1000

"""Helper tra POI theo loại — nền của matcher SP-5.

Fixture có 6 POI / 5 loại, trong đó `cafe` có ĐÚNG HAI mục (Bình Minh 3,6 km và
Highlands 5,6 km). Cặp ấy là thứ duy nhất trong fixture phân biệt được "gần nhất"
với "một trong số đó", nên mọi test dưới đây bám vào nó.

Dùng lại `POI_CATEGORIES` đã có sẵn thay vì đặt thêm một hằng số loại thứ hai —
hai danh sách cùng nói một chuyện là hai danh sách sẽ lệch nhau.
"""

import pytest

from src.fixtures import POI_CATEGORIES, POI_CATEGORIES_CA_NHAN, load_poi_fixture, loai_poi_tu_alias, tim_poi_theo_loai
from src.services.tool_registry import TOOL_REGISTRY, SearchNearbyPoiArgs


def test_poi_categories_phu_dung_fixture_that():
    """`POI_CATEGORIES` là các nhóm **tìm được bằng lời**, không phải mọi nhóm trong file.

    Từ #283 fixture còn nhóm `personal` (Nhà/Cơ quan) — nó cố ý **không có alias** nên
    không câu nói nào khớp vào, và gộp nó vào đây sẽ nói rằng có một loại địa điểm tìm
    được bằng lời mà thực ra không.
    """
    trong_file = {str(p["category"]) for p in load_poi_fixture()}
    assert set(POI_CATEGORIES) == trong_file - set(POI_CATEGORIES_CA_NHAN)


def test_tim_theo_loai_sap_theo_khoang_cach_tang_dan():
    quan = tim_poi_theo_loai("cafe")
    assert [p["id"] for p in quan] == ["poi-cafe-02", "poi-cafe-01"]
    assert quan[0]["distance_km"] < quan[1]["distance_km"]


def test_tim_loai_khong_co_thi_rong():
    assert tim_poi_theo_loai("san-bay") == []


@pytest.mark.parametrize(
    ("text", "mong_doi"),
    [
        ("tìm quán cà phê gần đây", "cafe"),
        ("quanh đây có trạm sạc nào không", "charging"),
        ("tìm chỗ ăn gần nhất", "restaurant"),
        ("tìm chỗ mua sắm quanh đây", "mall"),
        ("tìm công viên gần đây", "entertainment"),
        ("bật điều hòa 24 độ", None),
    ],
)
def test_alias_trong_cau_ra_dung_loai(text, mong_doi):
    assert loai_poi_tu_alias(text) == mong_doi


def test_alias_dai_thang_alias_ngan():
    """Trật tự alias-dài-trước là hợp đồng của `poi_alias_map`, không phải chi tiết."""
    assert loai_poi_tu_alias("tìm cà phê bình minh") == "cafe"


def test_search_nearby_poi_co_schema_dong():
    assert TOOL_REGISTRY["search_nearby_poi"].args_model is SearchNearbyPoiArgs
    assert TOOL_REGISTRY["search_nearby_poi"].safety == "S0"
    SearchNearbyPoiArgs(category="cafe")
    with pytest.raises(Exception):
        SearchNearbyPoiArgs(category="san-bay")
    with pytest.raises(Exception):
        SearchNearbyPoiArgs(category="cafe", ban_kinh_km=5)


def test_schema_khop_voi_poi_categories():
    """Literal của schema và fixture phải nói cùng một chuyện."""
    from typing import get_args

    truong = SearchNearbyPoiArgs.model_fields["category"]
    assert set(get_args(truong.annotation)) == set(POI_CATEGORIES)

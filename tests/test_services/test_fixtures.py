"""Fixture dùng chung: khoá hợp đồng dữ liệu, và khoá việc hai bản không được trôi."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.fixtures import (
    POI_CA_NHAN_THEO_NHAN,
    POI_CATEGORIES,
    POI_CATEGORIES_CA_NHAN,
    POI_IDS_KE_THUA,
    load_media_fixture,
    load_poi_fixture,
    poi_alias_map,
)

_GOC = Path(__file__).resolve().parents[2]
_NGUON = _GOC / "src" / "fixtures"
_BAN_SAO_FE = _GOC / "frontend" / "src" / "lib" / "fixtures"

_TEN_FILE = ("poi.json", "media.json")


@pytest.mark.parametrize("ten_file", _TEN_FILE)
def test_ban_sao_frontend_giong_nguon_tung_byte(ten_file: str) -> None:
    """Đây là test giữ cho fixture còn là MỘT nguồn sự thật.

    Bản sao ở frontend do `scripts/sync_fixtures.ps1` sinh ra. Không có test này thì nó
    là bản chép tay thứ hai, và hai bản sẽ lệch đúng vào ngày ai đó sửa một bên — chính
    lớp lỗi đã làm `MusicView` phát mãi một file trong khi tên bài trên màn hình vẫn
    đổi. So từng byte chứ không so JSON đã parse: khác thụt lề cũng là dấu hiệu ai đó
    sửa tay bản sao thay vì chạy script.
    """
    nguon = (_NGUON / ten_file).read_bytes()
    ban_sao = (_BAN_SAO_FE / ten_file).read_bytes()
    assert ban_sao == nguon, f"{ten_file} lệch giữa src/fixtures và frontend — chạy pwsh scripts/sync_fixtures.ps1"


@pytest.mark.parametrize("ten_file", _TEN_FILE)
def test_fixture_khong_nam_duoi_thu_muc_bi_gitignore(ten_file: str) -> None:
    """`.gitignore` có dòng `data/` không neo đầu — nó khớp mọi thư mục tên `data` ở mọi
    độ sâu. Fixture rơi vào đó sẽ không bao giờ được commit và không ai nhận ra cho tới
    lúc CI đỏ trên máy khác (xem `src/safety/ap_suat_lop.py`). Test này chặn việc ai đó
    "dọn dẹp" bằng cách chuyển JSON sang một thư mục `data/`.
    """
    duong_dan = (_NGUON / ten_file).relative_to(_GOC)
    assert "data" not in duong_dan.parts


def test_poi_giu_du_ba_id_ke_thua() -> None:
    """Ba id này đã đi vào `test_router.py`, `test_tools.py` và `demo_runbook.md:100`
    từ trước khi có fixture. Đổi hoặc xoá là làm hỏng cả ba chỗ cùng lúc.
    """
    ids = {item["id"] for item in load_poi_fixture()}
    assert set(POI_IDS_KE_THUA) <= ids


def test_poi_phu_du_cac_nhom() -> None:
    """Năm nhóm tìm được bằng lời, cộng nhóm cá nhân của #283.

    Bằng nhau chứ không phải "chứa": một category lạ trong fixture nghĩa là có POI mà
    không ai biết nó thuộc đường nào — tìm bằng lời hay gán bằng nhãn.
    """
    nhom = {item["category"] for item in load_poi_fixture()}
    assert nhom == set(POI_CATEGORIES) | set(POI_CATEGORIES_CA_NHAN)


def test_poi_ca_nhan_khong_co_alias_nao() -> None:
    """Đây là **hàng rào an toàn**, không phải dữ liệu còn thiếu.

    Cho `poi-home-01` alias `"nhà"` thì *"đi về nhà"* dẫn tới một toạ độ dùng chung cho
    mọi tài khoản, bỏ qua mapping cá nhân — đúng thứ `routines_product_spec.md` §Nhà và
    Cơ quan cấm, và `set_navigation` là S1 nên nó đi qua mà không ai duyệt. Đường hợp lệ
    duy nhất tới hai POI này là qua `user_places`.
    """
    for item in load_poi_fixture():
        if item["category"] in POI_CATEGORIES_CA_NHAN:
            assert item["aliases"] == [], f"{item['id']} không được có alias"


def test_hai_nhan_ca_nhan_tro_toi_poi_co_that() -> None:
    ids = {item["id"] for item in load_poi_fixture()}
    assert set(POI_CA_NHAN_THEO_NHAN) == {"home", "office"}
    assert set(POI_CA_NHAN_THEO_NHAN.values()) <= ids


def test_poi_id_khong_trung() -> None:
    ids = [item["id"] for item in load_poi_fixture()]
    assert len(ids) == len(set(ids))


def test_moi_poi_du_truong_ma_ca_hai_phia_can() -> None:
    """Backend cần `id` + `aliases`; IVI cần phần còn lại. Thiếu một trường thì một
    trong hai phía hỏng, nên khoá cả bộ ở một chỗ.
    """
    for item in load_poi_fixture():
        for truong in ("id", "name", "category", "aliases", "lat", "lon", "distance_km", "eta_min", "polyline"):
            assert truong in item, f"{item.get('id')} thiếu trường {truong}"
        if item["category"] not in POI_CATEGORIES_CA_NHAN:
            assert item["aliases"], f"{item['id']} không có alias nào — router sẽ không bao giờ khớp nó"
        assert len(item["polyline"]) >= 2, f"{item['id']} có polyline dưới 2 điểm, không vẽ được đường"


def test_alias_khong_dung_cho_hai_poi() -> None:
    """Một alias trỏ hai nơi là câu nói mơ hồ mà router không có cách nào giải."""
    thay: dict[str, str] = {}
    for item in load_poi_fixture():
        for alias in item["aliases"]:
            khoa = str(alias).strip().lower()
            assert khoa not in thay, f"alias {khoa!r} dùng cho cả {thay.get(khoa)} và {item['id']}"
            thay[khoa] = item["id"]


def test_alias_dai_dung_truoc_alias_ngan() -> None:
    """Người gọi khớp bằng "alias nào nằm trong câu". Nếu `"cà phê"` đứng trước
    `"cà phê bình minh"` thì *"dẫn đường đến cà phê bình minh"* trúng quán sai.
    """
    do_dai = [len(alias) for alias in poi_alias_map()]
    assert do_dai == sorted(do_dai, reverse=True)


def test_alias_cu_van_tro_dung_poi_nhu_truoc_khi_co_fixture() -> None:
    """Ba ánh xạ hard-code cũ trong `router.py` phải sống sót nguyên vẹn, nếu không
    `demo_runbook.md:100` và bộ test router hiện có sẽ nói dối.
    """
    bang = poi_alias_map()
    assert bang["cà phê"] == "poi-cafe-01"
    assert bang["bình minh"] == "poi-cafe-02"
    assert bang["trạm sạc"] == "poi-charge-01"


def test_playlist_du_dai_de_next_previous_xoay_vong() -> None:
    assert len(load_media_fixture()) >= 5


def test_moi_bai_co_giay_phep_va_ghi_cong() -> None:
    """Điều kiện để #176 được phép đưa file mp3 thật vào repo. Playlist cũ là nhạc có
    bản quyền (Trịnh Công Sơn, Phú Quang) — hôm nay chỉ là chuỗi hiển thị nên vô hại,
    nhưng gắn file vào đúng những cái tên đó là host nhạc có bản quyền trong một repo
    học thuật. Test này chặn việc lặng lẽ quay lại tình trạng ấy.
    """
    for item in load_media_fixture():
        assert item.get("license"), f"{item.get('id')} không khai giấy phép"
        assert item.get("attribution"), f"{item.get('id')} không có dòng ghi công"
        assert item.get("source"), f"{item.get('id')} không khai nguồn"
        assert "source_url" in item, f"{item.get('id')} thiếu khoá source_url"


def test_ten_bai_khong_trung() -> None:
    """`media_control` chuyển bài bằng tên; hai bài trùng tên là một vòng lặp không
    thoát được ở `_step_track`.
    """
    ten = [item["name"] for item in load_media_fixture()]
    assert len(ten) == len(set(ten))


@pytest.mark.parametrize("ten_file", _TEN_FILE)
def test_json_hop_le_va_co_schema_version(ten_file: str) -> None:
    du_lieu = json.loads((_NGUON / ten_file).read_text(encoding="utf-8"))
    assert du_lieu["schema_version"] == "1.0"
    assert isinstance(du_lieu["items"], list)

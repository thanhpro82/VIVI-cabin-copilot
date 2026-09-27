"""Fixture dùng chung cho backend và IVI: danh sách POI mock và playlist nhạc.

## Vì sao JSON nằm trong `src/` chứ không dưới `data/`

`.gitignore` có dòng `data/` **không neo đầu**, nên nó khớp mọi thư mục tên `data` ở
mọi độ sâu. Một fixture đặt ở `data/fixtures/` sẽ không bao giờ được commit, và không
ai nhận ra cho tới lúc CI đỏ trên máy khác. `src/safety/ap_suat_lop.py` đã gặp đúng bẫy
này và ghi lại; module này chép nguyên cách làm đó, không phát minh lại.

## Vì sao có bản sao ở frontend

Next.js không import được file ngoài thư mục project của nó, nên frontend đọc bản sao
`frontend/src/lib/fixtures/*.json` do `scripts/sync_fixtures.ps1` sinh ra. Bản sao là
thứ **sinh ra**, không phải thứ viết tay: `tests/test_services/test_fixtures.py` so
từng byte hai bản. Bỏ test đó thì bản sao thành nguồn sự thật thứ hai, và hai bản sẽ
lệch đúng vào ngày ai đó sửa một bên — chính lớp lỗi đã làm `MusicView` phát mãi một
file trong khi tên bài trên màn hình vẫn đổi.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.rag.textnorm import fold

_THU_MUC = Path(__file__).parent

#: Nhóm POI **tìm được bằng lời**. Router không đọc hằng số này — nó chỉ dùng `aliases`
#: — nhưng test khoá nó để không ai lặng lẽ xoá một nhóm khỏi bộ demo.
POI_CATEGORIES: tuple[str, ...] = ("cafe", "restaurant", "mall", "entertainment", "charging")

#: Nhóm POI **cá nhân**: đích của nhãn Nhà/Cơ quan mà mỗi user tự gán (issue #283).
#:
#: Tách khỏi `POI_CATEGORIES` chứ không thêm vào, vì hai nhóm khác nhau ở một điểm quyết
#: định: POI cá nhân **không có alias**, nên không câu nói nào khớp thẳng vào chúng.
#:
#: Đó là chủ ý, không phải dữ liệu thiếu. Cho `poi-home-01` alias `"nhà"` thì
#: *"đi về nhà"* sẽ dẫn tới **một toạ độ dùng chung cho mọi tài khoản**, bỏ qua mapping
#: cá nhân — đúng thứ `routines_product_spec.md` §Nhà và Cơ quan cấm: *"không bao giờ
#: rơi về một địa điểm mặc định"*. Và vì `set_navigation` là S1, nó đi qua mà không ai
#: duyệt. Đường hợp lệ duy nhất tới hai POI này là qua `user_places`.
POI_CATEGORIES_CA_NHAN: tuple[str, ...] = ("personal",)

#: Hai nhãn cá nhân → POI **mang sẵn tên ấy** trong fixture, để UI có một gợi ý hiển
#: nhiên khi người dùng mở màn thiết lập.
#:
#: Đây **không phải** giá trị đã gán và cũng không phải giới hạn: `routines_product_spec.md`
#: §Nhà và Cơ quan chốt người dùng chọn trong **tám điểm cố định**, nên gán Nhà vào
#: `poi-cafe-01` là hợp lệ. Chưa chọn thì `user_places` không có hàng nào, và không có
#: gì được suy ra từ bảng này — suy ra là đúng thứ spec cấm.
POI_CA_NHAN_THEO_NHAN: dict[str, str] = {"home": "poi-home-01", "office": "poi-work-01"}

#: Ba id đã đi vào test và tài liệu demo trước khi có fixture này
#: (`tests/test_agents/test_router.py`, `tests/test_agents/test_tools.py`,
#: `docs/demo_runbook.md`). Đổi hoặc xoá chúng là làm hỏng cả ba chỗ cùng lúc, nên
#: test khoá sự tồn tại của chúng chứ không chỉ khoá tổng số item.
POI_IDS_KE_THUA: tuple[str, ...] = ("poi-cafe-01", "poi-cafe-02", "poi-charge-01")


def _doc(ten_file: str) -> list[dict[str, Any]]:
    duong_dan = _THU_MUC / ten_file
    du_lieu = json.loads(duong_dan.read_text(encoding="utf-8"))
    items = du_lieu.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"{duong_dan} phải có mảng 'items' không rỗng")
    return items


@lru_cache(maxsize=1)
def load_poi_fixture() -> tuple[dict[str, Any], ...]:
    """Danh sách POI mock. Tuple để `lru_cache` không trả về list sửa được tại chỗ."""
    return tuple(_doc("poi.json"))


@lru_cache(maxsize=1)
def load_media_fixture() -> tuple[dict[str, Any], ...]:
    """Playlist nhạc. Thứ tự trong file là thứ tự `media_control` next/previous xoay."""
    return tuple(_doc("media.json"))


def poi_alias_map() -> dict[str, str]:
    """`alias đã chuẩn hoá -> poi_id`, alias dài đứng trước.

    Sắp theo độ dài giảm dần vì người gọi khớp bằng "alias nào nằm trong câu": để
    `"cà phê"` đứng trước `"cà phê bình minh"` thì câu *"dẫn đường đến cà phê bình
    minh"* sẽ trúng quán sai. Trật tự là một phần của hợp đồng, không phải chi tiết
    trình bày.
    """
    cap = [
        (str(alias).strip().lower(), str(item["id"]))
        for item in load_poi_fixture()
        for alias in item.get("aliases", ())
    ]
    cap.sort(key=lambda x: len(x[0]), reverse=True)
    return dict(cap)


def tim_poi_theo_loai(category: str) -> list[dict[str, Any]]:
    """POI cùng loại, **gần nhất đứng đầu**.

    Sắp ngay ở đây chứ không để người gọi tự sắp: "gần nhất" là khái niệm của dữ liệu
    này, và mỗi chỗ gọi tự sắp lấy là mỗi chỗ có thể sắp sai chiều.
    """
    cung_loai = [item for item in load_poi_fixture() if str(item.get("category")) == category]
    return sorted(cung_loai, key=lambda item: float(item.get("distance_km", 1e9)))


def loai_poi_tu_alias(text: str) -> str | None:
    """Alias xuất hiện trong câu → loại địa điểm. `None` = câu không nói tới POI nào.

    Dùng lại `poi_alias_map()` để thừa hưởng trật tự alias-dài-trước — thứ tự ấy là
    hợp đồng: `"cà phê"` đứng trước `"cà phê bình minh"` thì câu nhắc quán Bình Minh
    sẽ trúng quán khác.
    """
    theo_id = {str(item["id"]): str(item.get("category", "")) for item in load_poi_fixture()}
    thap = (text or "").lower()
    for alias, poi_id in poi_alias_map().items():
        if alias in thap:
            return theo_id.get(poi_id) or None
    return None


def _khong_dau(text: str) -> str:
    """Chuỗi so khớp tên bài: bỏ dấu, thường hoá, gộp khoảng trắng.

    Dùng lại `fold` của tầng RAG thay vì viết bản thứ hai — hai bản chuẩn hoá là hai
    bản sẽ lệch nhau đúng vào ngày ai đó thêm một ký tự lạ vào tên bài. `fold` cũng
    đã đổi `đ → d`, thứ mà `normalize_vi` của router **không** làm.
    """
    return fold(text or "")


def media_alias_map() -> dict[str, str]:
    """`tên bài đã bỏ dấu -> track_id`, tên dài đứng trước.

    Cùng luật trật tự với `poi_alias_map()` và cùng lý do: người gọi khớp bằng "tên
    nào nằm trong câu", nên một tên ngắn là tiền tố của tên dài mà đứng trước sẽ
    cướp mất câu nói tên dài.
    """
    cap = [(_khong_dau(str(item["name"])), str(item["id"])) for item in load_media_fixture()]
    cap.sort(key=lambda x: len(x[0]), reverse=True)
    return dict(cap)


def tim_track_theo_ten(text: str) -> dict[str, Any] | None:
    """Tên bài xuất hiện trong câu → item playlist. `None` = câu không gọi tên bài nào.

    So khớp trên chuỗi đã bỏ dấu nên `"CAREFREE"`, `"carefree"` và `"cà rê phi"`-kiểu
    thiếu dấu đều trúng cùng một bài.
    """
    thap = _khong_dau(text)
    if not thap:
        return None
    theo_id = {str(item["id"]): item for item in load_media_fixture()}
    for ten, track_id in media_alias_map().items():
        if ten and ten in thap:
            return dict(theo_id[track_id])
    return None


def ten_track_theo_id(track_id: str) -> str | None:
    """`track_id -> tên hiển thị`. `None` nếu id không có trong playlist."""
    for item in load_media_fixture():
        if str(item["id"]) == track_id:
            return str(item["name"])
    return None

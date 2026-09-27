"""Địa điểm cá nhân: đúng hai nhãn **Nhà** và **Cơ quan** cho mỗi user.

Issue #283, dưới outcome #273 của epic Routines MVP (#270).

## Ranh giới

Sở hữu persistence và contract của hai nhãn ấy, cộng phép resolve nhãn → `destination_id`
hợp lệ. Không dựng UI (#284), không đọc lời nói (#285), không thực thi (#286).

## Ba luật, mỗi luật chặn một cách hỏng khác nhau

**1. Không bao giờ có giá trị mặc định.** Chưa gán thì `get_places` trả `None` cho nhãn
ấy, và `resolve` cũng trả `None`. Spec §Nhà và Cơ quan viết thẳng: *"không bao giờ rơi
về một địa điểm mặc định"*. Lý do không phải là sự sạch sẽ — `set_navigation` là **S1**,
đi qua policy mà không cần ai duyệt, nên một mặc định ở đây nghĩa là chở tài xế tới chỗ
họ không hề bảo và không ai được hỏi.

**2. Đích phải thuộc tập đóng của fixture.** Tám POI trong `src/fixtures/poi.json`, không
hơn. Không có id động, không mở id space — cùng ràng buộc offline/simulator-only mà cả
`set_navigation` đang sống dưới.

**3. Một đích **biến mất** khỏi fixture thì nhãn ấy quay lại trạng thái chưa gán.** Hàng
cũ vẫn nằm trong DB (không tự xoá dữ liệu người dùng), nhưng `valid=False` và nó **không**
được tính là đã gán. Đây là ca spec nêu riêng: *"khi destination offline không còn hợp lệ,
Routine chuyển sang trạng thái cần thiết lập"*. Bỏ qua nó nghĩa là một Routine dẫn đường
tới một id không còn ai biết là gì.

## Vì sao đọc lại fixture ở mỗi lời gọi

`load_poi_fixture()` có `lru_cache`, nên chi phí là một phép tra dict. Đổi lại: không có
bản sao nào của tập id sống trong module này, nên không có bản nào lệch đi khi fixture đổi.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from src.db import get_connection
from src.fixtures import load_poi_fixture

#: Đúng hai nhãn. Tập đóng, khớp `RoutineStep.navigation.destination` của
#: `frontend/src/lib/services/routines/types.ts` — thêm nhãn thứ ba là đổi cả contract FE.
NHAN_HOP_LE: tuple[str, ...] = ("home", "office")


class NhanKhongHopLeError(ValueError):
    def __init__(self, label: str) -> None:
        self.label = label
        super().__init__(f"nhãn không hợp lệ: {label!r}; hợp lệ: {'|'.join(NHAN_HOP_LE)}")


class DiaDiemKhongHopLeError(ValueError):
    """`destination_id` không thuộc fixture offline.

    Lớp riêng chứ không `ValueError` trần: route cần phân biệt "client gửi id lạ" (422)
    với mọi `ValueError` khác trong ngăn xếp.
    """

    def __init__(self, destination_id: str) -> None:
        self.destination_id = destination_id
        super().__init__(f"destination_id {destination_id!r} không có trong fixture offline")


@dataclass(frozen=True)
class DiaDiemCaNhan:
    """Một nhãn đã gán.

    `name` lấy từ fixture chứ không lưu kèm: tên là thuộc tính của POI, và lưu bản sao ở
    đây là dựng một nguồn sự thật thứ hai sẽ lệch đúng vào ngày POI được đổi tên.

    `valid=False` nghĩa là hàng còn trong DB nhưng đích đã biến mất khỏi fixture — xem
    luật 3 ở docstring module.
    """

    label: str
    destination_id: str
    name: str | None
    valid: bool
    updated_at: str


def _poi_theo_id() -> dict[str, dict]:
    return {str(item["id"]): item for item in load_poi_fixture()}


def _kiem_nhan(label: str) -> str:
    if label not in NHAN_HOP_LE:
        raise NhanKhongHopLeError(label)
    return label


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def get_places(user_id: str, *, connection: sqlite3.Connection | None = None) -> dict[str, DiaDiemCaNhan]:
    """Các nhãn **đã gán** của user. Nhãn chưa gán đơn giản là vắng mặt khỏi dict.

    Không trả `{"home": None}`: "chưa gán" và "gán rồi nhưng hỏng" là hai trạng thái khác
    nhau và phải trông khác nhau — cái sau có mặt với `valid=False`.
    """
    conn = connection or get_connection()
    rows = conn.execute(
        "SELECT label, destination_id, updated_at FROM user_places WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    poi = _poi_theo_id()
    ket: dict[str, DiaDiemCaNhan] = {}
    for row in rows:
        item = poi.get(str(row["destination_id"]))
        ket[str(row["label"])] = DiaDiemCaNhan(
            label=str(row["label"]),
            destination_id=str(row["destination_id"]),
            name=str(item["name"]) if item else None,
            valid=item is not None,
            updated_at=str(row["updated_at"]),
        )
    return ket


def set_place(
    user_id: str, label: str, destination_id: str, *, connection: sqlite3.Connection | None = None
) -> DiaDiemCaNhan:
    """Gán một nhãn. Ghi đè nếu đã có.

    Validate **trước khi** chạm DB: một hàng trỏ id lạ nằm trong bảng rồi mới nổ lúc
    Routine chạy là đúng thứ luật 2 tồn tại để chặn.
    """
    conn = connection or get_connection()
    _kiem_nhan(label)
    if destination_id not in _poi_theo_id():
        raise DiaDiemKhongHopLeError(destination_id)

    conn.execute(
        """
        INSERT INTO user_places (user_id, label, destination_id, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, label) DO UPDATE SET
            destination_id = excluded.destination_id,
            updated_at = excluded.updated_at
        """,
        (user_id, label, destination_id, _now()),
    )
    conn.commit()
    return get_places(user_id, connection=conn)[label]


def delete_place(user_id: str, label: str, *, connection: sqlite3.Connection | None = None) -> bool:
    """Bỏ gán một nhãn. Trả `True` nếu có hàng bị xoá.

    Bỏ gán là hành động hợp lệ, không phải lỗi: Routine dẫn đường của user ấy quay về
    "Cần thiết lập" — đúng trạng thái spec mô tả, và **không** rơi về đích cũ.
    """
    conn = connection or get_connection()
    _kiem_nhan(label)
    cursor = conn.execute("DELETE FROM user_places WHERE user_id = ? AND label = ?", (user_id, label))
    conn.commit()
    return cursor.rowcount > 0


def resolve(user_id: str, label: str, *, connection: sqlite3.Connection | None = None) -> str | None:
    """Nhãn → `destination_id` **hợp lệ**, hoặc `None`.

    `None` gộp ba ca — chưa gán, nhãn lạ, đích đã biến mất — vì người gọi (`#286`) làm
    cùng một việc với cả ba: fail-fast tại bước ấy và nói *"chưa đặt địa điểm Nhà"*.
    Tách ra thành ba giá trị trả về sẽ mời người gọi xử lý khác nhau, mà không ca nào
    trong ba ca ấy cho phép đi tiếp.
    """
    if label not in NHAN_HOP_LE:
        return None
    dia_diem = get_places(user_id, connection=connection).get(label)
    if dia_diem is None or not dia_diem.valid:
        return None
    return dia_diem.destination_id


def nhan_da_gan(user_id: str, *, connection: sqlite3.Connection | None = None) -> set[str]:
    """Tập nhãn đã gán **và còn hợp lệ**. `routines_store` dùng để tính `needs_setup`."""
    return {label for label, dia_diem in get_places(user_id, connection=connection).items() if dia_diem.valid}


__all__ = [
    "NHAN_HOP_LE",
    "DiaDiemCaNhan",
    "DiaDiemKhongHopLeError",
    "NhanKhongHopLeError",
    "delete_place",
    "get_places",
    "nhan_da_gan",
    "resolve",
    "set_place",
]

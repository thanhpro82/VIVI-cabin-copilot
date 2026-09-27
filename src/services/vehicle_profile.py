"""Cấu hình xe: phiên bản (`trim`) và loại pin (`battery`) — issue #123.

## Vì sao tách khỏi `vehicle_state`

ADR-013 chốt snapshot của simulator là **nguồn duy nhất** của trạng thái xe, và
backend chỉ forward chứ không thêm bớt field nào trên đường ra `GET /vehicle/state`.
Trim và loại pin cũng không phải *trạng thái*: chúng không đổi khi xe chạy, không có
`state_version`, không đi qua MQTT. Nhét chúng vào snapshot vừa vi phạm ADR-013 vừa
gán cho chúng một vòng đời chúng không có.

## `None` nghĩa là "chưa biết", và đó là một ca hợp lệ

Sổ tay VF9 cho **bốn** giá trị áp suất lốp khác nhau theo `trim` × `battery`
(`src/safety/ap_suat_lop.py`). Không biết cấu hình thì không có một con số đúng nào
để nói — nên `None` ở đây không phải dữ liệu khuyết cần vá, nó là tín hiệu bắt người
gọi quay về câu chỉ nguồn.

Vì thế module này **không** có giá trị mặc định và không đoán. Cùng lý do mà
`tra_ap_suat()` đòi đủ ba tham số và ném `ValueError` thay vì trả `None`: một mặc
định sai còn tệ hơn không trả lời, vì tài xế không có cách nào biết mình vừa nghe
cấu hình nào.

## Ranh giới chuẩn hoá

`Trim`/`Battery` bên `ap_suat_lop` là `Literal`, tức **không** ràng buộc lúc chạy.
Nếu profile trả `"ECO"` viết hoa thì `tra_ap_suat()` ném `ValueError` — cùng một
exception với "tổ hợp lạ thật", nên hai lớp lỗi khác nhau sẽ lẫn vào nhau. Chuẩn hoá
chặn ngay tại đây, ở ranh giới ghi, để phía dưới không bao giờ thấy giá trị lệch hoa
thường hay thừa khoảng trắng.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from src.db import get_connection

Trim = Literal["eco", "plus"]
Battery = Literal["sdi", "catl"]

TRIMS: tuple[str, ...] = ("eco", "plus")
BATTERIES: tuple[str, ...] = ("sdi", "catl")


class InvalidProfileValueError(ValueError):
    """Giá trị `trim`/`battery` không thuộc tập cho phép.

    Lớp riêng chứ không dùng `ValueError` trần: route cần phân biệt "client gửi sai"
    (422) với mọi `ValueError` khác trong ngăn xếp, mà `ap_suat_lop.tra_ap_suat()`
    cũng ném `ValueError`. Bắt nhầm cái đó thành 422 sẽ che một lỗi lập trình thật.
    """

    def __init__(self, field: str, value: str, allowed: tuple[str, ...]) -> None:
        self.field = field
        self.value = value
        self.allowed = allowed
        super().__init__(f"{field}={value!r} không hợp lệ; hợp lệ: {'|'.join(allowed)}")


@dataclass(frozen=True)
class VehicleProfile:
    """Cấu hình một chiếc xe. `trim`/`battery` là `None` khi chưa khai báo."""

    vehicle_id: str
    trim: Trim | None
    battery: Battery | None
    updated_at: str | None

    @property
    def is_complete(self) -> bool:
        """Đủ cả hai mới tra được bảng áp suất lốp.

        Đọc kỹ: `plus` cho cùng một kết quả với cả `sdi` lẫn `catl` (260/270), nên
        về mặt số học có thể trả lời `plus` mà không cần biết pin. Ta **vẫn** đòi đủ
        hai, vì hợp đồng "biết cấu hình thì trả số, không biết thì chỉ nguồn" phải
        đọc được từ một chỗ duy nhất. Suy luận "trim này thì pin không quan trọng"
        là kiến thức về nội dung bảng rò rỉ ra ngoài bảng — sổ tay bản sau đổi số là
        nó sai âm thầm.
        """
        return self.trim is not None and self.battery is not None


def _normalise(field: str, value: str | None, allowed: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if cleaned == "":
        return None
    if cleaned not in allowed:
        raise InvalidProfileValueError(field, value, allowed)
    return cleaned


def _row_to_profile(vehicle_id: str, row: sqlite3.Row | None) -> VehicleProfile:
    if row is None:
        # Chưa có hàng và có hàng với hai cột NULL là **cùng một nghĩa**: chưa biết
        # cấu hình. Trả cùng một hình dạng để người gọi chỉ phải xử lý một ca.
        return VehicleProfile(vehicle_id=vehicle_id, trim=None, battery=None, updated_at=None)
    return VehicleProfile(
        vehicle_id=vehicle_id,
        trim=row["trim"],
        battery=row["battery"],
        updated_at=row["updated_at"],
    )


def get_vehicle_profile(vehicle_id: str, *, connection: sqlite3.Connection | None = None) -> VehicleProfile:
    """Đọc cấu hình. Xe chưa khai báo trả về profile rỗng, không ném lỗi."""
    conn = connection or get_connection()
    row = conn.execute(
        "SELECT vehicle_id, trim, battery, updated_at FROM vehicle_profiles WHERE vehicle_id = ?",
        (vehicle_id,),
    ).fetchone()
    return _row_to_profile(vehicle_id, row)


def set_vehicle_profile(
    vehicle_id: str,
    *,
    trim: str | None,
    battery: str | None,
    connection: sqlite3.Connection | None = None,
) -> VehicleProfile:
    """Ghi đè cấu hình. Truyền `None` cho một trường là **xoá** trường đó.

    Ghi đè toàn bộ chứ không vá từng phần: cấu hình là một cặp, và một xe nửa khai
    báo (`trim` mới, `battery` cũ của xe trước) là chính ca mà `is_complete` không
    phát hiện nổi — nó thấy đủ hai trường nên trả `True`, rồi tra ra số của một
    chiếc xe không tồn tại.
    """
    conn = connection or get_connection()
    clean_trim = _normalise("trim", trim, TRIMS)
    clean_battery = _normalise("battery", battery, BATTERIES)
    now = datetime.now(UTC).isoformat(timespec="seconds")

    conn.execute(
        """
        INSERT INTO vehicle_profiles (vehicle_id, trim, battery, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(vehicle_id) DO UPDATE SET
            trim = excluded.trim,
            battery = excluded.battery,
            updated_at = excluded.updated_at
        """,
        (vehicle_id, clean_trim, clean_battery, now),
    )
    conn.commit()
    return VehicleProfile(
        vehicle_id=vehicle_id,
        trim=clean_trim,  # type: ignore[arg-type]
        battery=clean_battery,  # type: ignore[arg-type]
        updated_at=now,
    )


# --- Trang bị tuỳ chọn -------------------------------------------------------
#
# Tách khỏi `trim`/`battery` ở cả bảng lẫn API, và đó là một quyết định chứ không phải
# tiện tay. `is_complete` là **cổng của nhánh áp suất lốp** và chỉ của nhánh ấy: nó
# hỏi "đã đủ để tra bảng 4 ô chưa". Nhét 65 trang bị vào cùng khái niệm ấy thì
# `is_complete` sẽ không bao giờ đúng nữa, và cả nhánh áp suất lốp chết theo.
#
# Ngữ nghĩa ghi cũng khác, cố ý:
#
# - `trim`/`battery` là một **cặp**, PUT ghi đè cả cặp, và thiếu field là 422. Lý do ở
#   docstring `VehicleProfileUpdate`: một xe nửa khai báo vẫn qua được `is_complete`.
# - Trang bị là một **tập**, PUT ghi đè cả tập, và **vắng khoá = chưa khai báo**. Ở
#   đây không có "quên gửi" để phân biệt với "cố ý xoá", vì không có danh sách field
#   cố định nào để mà quên — client gửi đúng những gì nó biết.
#
# Điểm chung phải giữ: **ghi đè cả tập, không vá từng khoá.** Vá từng khoá là mời một
# `lop_du_phong=true` còn sót của chiếc xe trước ở lại trên chiếc xe sau, đúng lớp lỗi
# mà PUT-thay-vì-PATCH của #123 đã chặn.


class TrangBiKhongHopLeError(ValueError):
    """Client khai một id không có trong danh mục, hoặc hai trang bị loại trừ nhau.

    Lớp riêng vì route phải trả 422 cho nó, mà không được nuốt luôn mọi `ValueError`
    khác trong ngăn xếp — cùng lý do với `InvalidProfileValueError` ở trên.
    """


def get_vehicle_options(vehicle_id: str, *, connection: sqlite3.Connection | None = None) -> dict[str, bool]:
    """Trang bị đã khai báo. Khoá vắng mặt nghĩa là **chưa biết**, không phải "không có".

    Người gọi phải phân biệt ba trạng thái. `.get(ma)` trả `None` cho chưa biết,
    `False` cho đã khai là không có — và hai thứ ấy dẫn tới hai hành vi khác nhau:
    chưa biết thì đọc nguyên văn mệnh đề điều kiện của sổ tay, khai là không có thì
    nói thẳng xe không có.
    """
    conn = connection or get_connection()
    rows = conn.execute(
        "SELECT option_id, co FROM vehicle_options WHERE vehicle_id = ?",
        (vehicle_id,),
    ).fetchall()
    return {r["option_id"]: bool(r["co"]) for r in rows}


def set_vehicle_options(
    vehicle_id: str,
    options: dict[str, bool],
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, bool]:
    """Ghi đè **toàn bộ** tập trang bị đã khai của xe. Trả lại tập vừa ghi.

    Truyền `{}` là xoá sạch khai báo, tức đưa mọi trang bị về "chưa biết".

    Hai phép kiểm chạy **trước** khi động vào bảng, để một body sai không để lại nửa
    tập đã ghi:

    1. Mọi id phải có trong danh mục. Id lạ là lỗi client, không phải dữ liệu tương
       lai — nhận bừa thì nó nằm im trong bảng cho tới lúc ai đó tra và không thấy.
    2. Hai trang bị loại trừ nhau không được cùng `True`. Đây là chỗ danh mục trả
       công cho việc khai `loai_tru`: một xe không thể vừa có lốp dự phòng vừa dùng
       bộ bơm hơi, và nếu tin cả hai thì nhánh cứu hộ trả lời sai theo cả hai hướng.

    Không kiểm chiều ngược lại (cả hai cùng `False`): một xe có thể chẳng có gì trong
    khoang sau cả, và sổ tay không cấm điều đó.
    """
    from src.safety.trang_bi import doc_danh_muc

    dm = doc_danh_muc()
    la = sorted(set(options) - set(dm.theo_id))
    if la:
        raise TrangBiKhongHopLeError(f"id trang bị không có trong danh mục: {', '.join(la)}")
    for ma, co in options.items():
        if not co:
            continue
        for khac in dm.theo_id[ma].loai_tru:
            if options.get(khac):
                raise TrangBiKhongHopLeError(f"{ma!r} và {khac!r} loại trừ nhau, không thể cùng có")

    conn = connection or get_connection()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute("DELETE FROM vehicle_options WHERE vehicle_id = ?", (vehicle_id,))
    conn.executemany(
        "INSERT INTO vehicle_options (vehicle_id, option_id, co, updated_at) VALUES (?, ?, ?, ?)",
        [(vehicle_id, ma, int(bool(co)), now) for ma, co in sorted(options.items())],
    )
    conn.commit()
    return {ma: bool(co) for ma, co in sorted(options.items())}


def reset() -> None:
    """Chỉ dùng trong test — dọn bảng giữa các case.

    Khác các store cùng khuôn ở một chỗ: state ở đây nằm trong **SQLite**, không phải
    dict module-level. Kết nối là process-wide (`get_connection()`) và
    `sqlite:///:memory:` của test sống suốt cả phiên, nên một hàng do case trước ghi
    sẽ đi thẳng vào case sau. Không dọn thì "xe chưa khai báo" chỉ đúng khi test đó
    tình cờ chạy trước — đúng lớp phụ thuộc thứ tự mà commit `17adbdd` đã phải gỡ một
    lần với FK `sessions.user_id`.
    """
    connection = get_connection()
    connection.execute("DELETE FROM vehicle_profiles")
    connection.execute("DELETE FROM vehicle_options")
    connection.commit()

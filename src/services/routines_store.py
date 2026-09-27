"""Routine của người dùng: lưu trữ, cô lập theo tài khoản, và ba mẫu mặc định.

Issue #282, dưới outcome #272 của epic Routines MVP (#270).

## Ranh giới

Sở hữu **dữ liệu**: bảng `routines`, CRUD theo chủ sở hữu, bootstrap mẫu, và luật hợp
lệ tại ranh giới ghi. Không thực thi (#286), không đọc ý định từ lời nói (#285), không
dựng UI (#281).

## Cô lập theo tài khoản, và vì sao mọi hàm nhận `user_id` chứ không nhận `Routine`

`routines_product_spec.md` §Cô lập chốt: user B không liệt kê, đọc, sửa, xoá hay chạy
được Routine của user A — **kể cả khi biết id**. Cách chắc chắn nhất để giữ điều đó là
đừng bao giờ có một hàm tra được Routine chỉ bằng id: mọi truy vấn ở đây đều mang
`WHERE user_id = ?`, nên một id đoán trúng vẫn không trả về gì.

Hệ quả cố ý: id của người khác và id không tồn tại cho **cùng một** kết quả
(`RoutineKhongTonTaiError`). Phân biệt hai ca đó là mở đúng kênh rò rỉ mà #272 acceptance
criteria đóng lại: *"truy cập chéo user bị từ chối mà không làm lộ Routine có tồn tại
hay không"*.

## `version` và preview

Spec §Preview: preview bắt buộc ở lần chạy đầu của **mỗi phiên bản**. Nên "đã xem
preview chưa" không thể là một cờ boolean — sửa Routine phải làm nó đúng trở lại một
cách tự động, không phụ thuộc ai nhớ gọi hàm reset.

Ở đây: `version` tăng khi **nội dung** đổi (tên hoặc các bước), và `needs_preview` là
`previewed_version != version`. Ghi `previewed_version` là việc của #285 khi tài xế
chấp nhận preview; module này chỉ đảm bảo một điều — sửa xong thì cờ ấy bật lại.

Bật/tắt (`enabled`) **không** bump version: nó không đổi việc Routine sẽ làm gì.

## Vì sao validate bằng `kiem_tra_buoc` chứ không viết luật riêng

Allowlist hành động và dải giá trị đã sống ở `src/agents/routines.py` + `tool_registry`.
Chép sang đây là dựng nguồn sự thật thứ hai cho cùng một tập luật, và hai bản sẽ lệch
nhau đúng vào ngày ai đó thêm một action. Thứ lưu được phải đúng bằng thứ chạy được.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.agents.routines import MAX_BUOC, RoutineDichError, kiem_tra_buoc
from src.db import get_connection

#: Icon là tập đóng, khớp `RoutineIcon` của `frontend/src/lib/services/routines/types.ts`.
#: Không cho icon tuỳ ý: FE render bằng một bảng component, một giá trị lạ ra ô trống.
ICONS: tuple[str, ...] = ("briefcase", "home", "moon", "car", "music", "sun")

#: Trần độ dài tên. Không phải con số tuỳ hứng: tên được **đọc lên** trong lời mời
#: preview, và một tên dài hơn thế biến câu xác nhận thành một đoạn văn.
MAX_TEN = 60


@dataclass(frozen=True)
class MauRoutine:
    origin: str
    name: str
    icon: str
    steps: tuple[dict[str, Any], ...]


#: Ba mẫu mặc định của `routines_product_spec.md` §Ba mẫu mặc định.
#:
#: Nội dung khớp từng bước với `frontend/src/lib/fixtures/routineTemplates.ts` — bản FE
#: là thứ người dùng đang thấy hôm nay qua mock, nên lệch đi là đổi hành vi ngay lúc
#: chuyển sang `real.ts`. `tests/test_services/test_routines_store.py` khoá sự trùng khớp
#: ấy bằng một test đọc thẳng file TypeScript, để không ai sửa một bên rồi quên bên kia.
MAU_MAC_DINH: tuple[MauRoutine, ...] = (
    MauRoutine(
        origin="di_lam",
        name="Đi làm",
        icon="briefcase",
        steps=(
            {"action": "hvac_power", "enabled": True},
            {"action": "hvac_temperature", "temperatureC": 24},
            {"action": "navigation", "destination": "office"},
        ),
    ),
    MauRoutine(
        origin="ve_nha",
        name="Về nhà",
        icon="home",
        steps=(
            {"action": "navigation", "destination": "home"},
            {"action": "hvac_power", "enabled": True},
            {"action": "hvac_temperature", "temperatureC": 26},
        ),
    ),
    MauRoutine(
        origin="thu_gian",
        name="Thư giãn",
        icon="moon",
        steps=(
            {"action": "interior_light", "enabled": True},
            {"action": "media_control", "controlAction": "play"},
        ),
    ),
)


class RoutineKhongTonTaiError(LookupError):
    """Không có Routine ấy **trong không gian của user này**.

    Cùng một exception cho "id không tồn tại" và "id của người khác" — xem docstring
    module. Đừng thêm ca thứ ba vào đây.
    """


class TenTrungError(ValueError):
    """Đã có Routine khác cùng tên (sau chuẩn hoá) của cùng user."""


class KhongXoaDuocMauError(ValueError):
    """Mẫu mặc định chỉ tắt hoặc khôi phục được, không xoá."""


class KhongPhaiMauError(ValueError):
    """`restore_default` gọi trên một Routine tự tạo."""


class IconKhongHopLeError(ValueError):
    def __init__(self, icon: Any) -> None:
        super().__init__(f"icon không hợp lệ: {icon!r}; hợp lệ: {'|'.join(ICONS)}")


class TenKhongHopLeError(ValueError):
    """Tên rỗng sau chuẩn hoá, hoặc dài quá `MAX_TEN`."""


@dataclass(frozen=True)
class Routine:
    """Một Routine đã lưu.

    `needs_preview` và `needs_setup` là field **dẫn xuất**, trả sẵn thay vì để client tự
    suy — cùng lập luận với `is_complete` của `VehicleProfile` (issue #123): điều kiện
    fail-closed phải do backend quyết, để mỗi client khỏi tự nghĩ ra một luật riêng.
    """

    id: str
    user_id: str
    name: str
    icon: str
    enabled: bool
    steps: tuple[dict[str, Any], ...]
    is_default_template: bool
    template_origin: str | None
    version: int
    needs_preview: bool
    needs_setup: bool
    created_at: str
    updated_at: str

    @property
    def runnable(self) -> bool:
        """Chạy được ngay bây giờ không.

        `#282` Done when: *"disabled/incomplete routine không được trả như runnable"*.
        Hai lý do khác hẳn nhau — tắt là lựa chọn của người dùng, thiếu địa điểm là
        cấu hình dở — nên chúng vẫn là hai field riêng và đây chỉ là phép AND cho
        client nào chỉ cần một câu trả lời.
        """
        return self.enabled and not self.needs_setup


_KHOANG_TRANG = re.compile(r"\s+")


def chuan_hoa_ten(name: str) -> str:
    """Trim, hạ chữ thường, gộp khoảng trắng liên tiếp.

    Cùng luật với `normalizeName` trong `frontend/.../routines/mock.ts`. Phải cùng luật
    thật, không phải "đại khái giống": lệch một chi tiết thì có tên FE cho lưu mà BE từ
    chối, và người dùng thấy một lỗi không nói được nguyên nhân.
    """
    return _KHOANG_TRANG.sub(" ", name.strip()).lower()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _kiem_ten(name: str) -> str:
    ten = _KHOANG_TRANG.sub(" ", name.strip())
    if not ten:
        raise TenKhongHopLeError("Routine phải có tên")
    if len(ten) > MAX_TEN:
        raise TenKhongHopLeError(f"tên dài {len(ten)} ký tự, tối đa {MAX_TEN}")
    return ten


def _kiem_icon(icon: str) -> str:
    if icon not in ICONS:
        raise IconKhongHopLeError(icon)
    return icon


def _co_buoc_dan_duong(steps: tuple[dict[str, Any], ...]) -> set[str]:
    """Các nhãn địa điểm mà chuỗi bước này cần. Rỗng nghĩa là không cần thiết lập gì."""
    return {str(b.get("destination")) for b in steps if b.get("action") == "navigation"}


def _dia_diem_da_gan(conn: sqlite3.Connection, user_id: str) -> set[str]:
    """Nhãn đã gán **và còn hợp lệ**, uỷ cho `user_places`.

    Không tự `SELECT label` ở đây: một hàng trỏ POI đã biến mất khỏi fixture vẫn có
    `label`, nên phép đếm thô sẽ báo "đã thiết lập" cho một Routine dẫn đường tới một id
    không còn ai biết là gì. `user_places.nhan_da_gan` lọc đúng ca ấy — và nó là một
    chỗ, không phải hai.
    """
    from src.services.user_places import nhan_da_gan

    return nhan_da_gan(user_id, connection=conn)


def _dung(row: sqlite3.Row, da_gan: set[str]) -> Routine:
    import json

    steps = tuple(json.loads(row["steps_json"]))
    can = _co_buoc_dan_duong(steps)
    return Routine(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        icon=row["icon"],
        enabled=bool(row["enabled"]),
        steps=steps,
        is_default_template=bool(row["is_default_template"]),
        template_origin=row["template_origin"],
        version=int(row["version"]),
        needs_preview=row["previewed_version"] != row["version"],
        # Thiếu **bất kỳ** nhãn nào mà Routine cần là cần thiết lập. Không có mặc định,
        # không có "lấy tạm cái đã gán" — spec §Nhà và Cơ quan cấm rơi về địa điểm mặc
        # định, và một Routine "Đi làm" dẫn về Nhà là đúng lớp lỗi ấy.
        needs_setup=bool(can - da_gan),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _sinh_id() -> str:
    return f"rtn_{secrets.token_hex(8)}"


def _tim(conn: sqlite3.Connection, user_id: str, routine_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM routines WHERE id = ? AND user_id = ?",
        (routine_id, user_id),
    ).fetchone()
    if row is None:
        raise RoutineKhongTonTaiError(routine_id)
    return row


def _kiem_trung_ten(
    conn: sqlite3.Connection, user_id: str, ten_chuan: str, *, tru_id: str | None = None
) -> None:
    row = conn.execute(
        "SELECT id FROM routines WHERE user_id = ? AND name_normalized = ? AND id IS NOT ?",
        (user_id, ten_chuan, tru_id),
    ).fetchone()
    if row is not None:
        raise TenTrungError(ten_chuan)


def bootstrap_templates(user_id: str, *, connection: sqlite3.Connection | None = None) -> int:
    """Gieo ba mẫu mặc định cho một user. Trả số mẫu vừa tạo.

    **Idempotent theo hai tầng.** `INSERT OR IGNORE` cộng với index
    `routines_one_template_per_user` (partial unique trên `template_origin`): gọi lại
    không sinh bản thứ hai, và hai request song song cũng không — thứ mà một phép
    SELECT-rồi-INSERT trong Python không bao giờ chặn được.

    Mẫu gieo ra có `previewed_version = version`, tức **không** bắt preview lượt đầu:
    nội dung do PM/PO chốt và người dùng chưa từng sửa. Sửa một mẫu thì `update_routine`
    bump version và preview quay lại — đúng thứ §Preview cần bảo vệ.
    """
    import json

    conn = connection or get_connection()
    now = _now()
    da_tao = 0
    for mau in MAU_MAC_DINH:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO routines (
                id, user_id, name, name_normalized, icon, enabled, steps_json,
                is_default_template, template_origin, version, previewed_version,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, 1, ?, 1, 1, ?, ?)
            """,
            (
                f"rtn_{user_id}_{mau.origin}",
                user_id,
                mau.name,
                chuan_hoa_ten(mau.name),
                mau.icon,
                json.dumps(list(mau.steps), ensure_ascii=False),
                mau.origin,
                now,
                now,
            ),
        )
        da_tao += cursor.rowcount
    conn.commit()
    return da_tao


def list_routines(user_id: str, *, connection: sqlite3.Connection | None = None) -> list[Routine]:
    """Routine của user, mới sửa nhất trước. Tự bootstrap mẫu ở lần gọi đầu.

    Bootstrap nằm ở đây chứ không ở lúc đăng nhập: một user tạo từ script hay từ test
    cũng phải thấy đủ ba mẫu, và không có đường nào khác vào danh sách này.
    """
    conn = connection or get_connection()
    bootstrap_templates(user_id, connection=conn)
    da_gan = _dia_diem_da_gan(conn, user_id)
    rows = conn.execute(
        "SELECT * FROM routines WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
        (user_id,),
    ).fetchall()
    return [_dung(row, da_gan) for row in rows]


def get_routine(user_id: str, routine_id: str, *, connection: sqlite3.Connection | None = None) -> Routine:
    """Một Routine **của user này**. Ném `RoutineKhongTonTaiError` cho mọi ca khác."""
    conn = connection or get_connection()
    row = _tim(conn, user_id, routine_id)
    return _dung(row, _dia_diem_da_gan(conn, user_id))


def create_routine(
    user_id: str,
    *,
    name: str,
    icon: str,
    steps: list[dict[str, Any]],
    connection: sqlite3.Connection | None = None,
) -> Routine:
    """Tạo Routine tự tạo. Ném `RoutineDichError` nếu bước không hợp lệ.

    Validate **trước khi** chạm DB: một hàng hỏng nằm trong bảng rồi mới nổ lúc thực thi
    là đúng thứ `#282` Done when muốn chặn ("allowlist/argument validation tại boundary").
    """
    import json

    conn = connection or get_connection()
    ten = _kiem_ten(name)
    _kiem_icon(icon)
    kiem_tra_buoc(steps)
    ten_chuan = chuan_hoa_ten(ten)
    _kiem_trung_ten(conn, user_id, ten_chuan)

    now = _now()
    routine_id = _sinh_id()
    conn.execute(
        """
        INSERT INTO routines (
            id, user_id, name, name_normalized, icon, enabled, steps_json,
            is_default_template, template_origin, version, previewed_version,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, ?, 0, NULL, 1, NULL, ?, ?)
        """,
        (routine_id, user_id, ten, ten_chuan, icon, json.dumps(steps, ensure_ascii=False), now, now),
    )
    conn.commit()
    return get_routine(user_id, routine_id, connection=conn)


def update_routine(
    user_id: str,
    routine_id: str,
    *,
    name: str,
    icon: str,
    steps: list[dict[str, Any]],
    connection: sqlite3.Connection | None = None,
) -> Routine:
    """Sửa Routine (mẫu mặc định cũng sửa được). Bump `version` nếu nội dung đổi.

    "Nội dung" = tên + các bước. Đổi mỗi icon **không** bump: nó không đổi việc Routine
    sẽ làm, và bắt tài xế nghe lại preview vì một biểu tượng là dạy họ bấm qua preview
    cho nhanh — đúng thói quen mà §Preview tồn tại để tránh.
    """
    import json

    conn = connection or get_connection()
    row = _tim(conn, user_id, routine_id)
    ten = _kiem_ten(name)
    _kiem_icon(icon)
    kiem_tra_buoc(steps)
    ten_chuan = chuan_hoa_ten(ten)
    _kiem_trung_ten(conn, user_id, ten_chuan, tru_id=routine_id)

    steps_json = json.dumps(steps, ensure_ascii=False)
    doi_noi_dung = steps_json != row["steps_json"] or ten != row["name"]
    version = int(row["version"]) + 1 if doi_noi_dung else int(row["version"])

    conn.execute(
        """
        UPDATE routines
           SET name = ?, name_normalized = ?, icon = ?, steps_json = ?, version = ?, updated_at = ?
         WHERE id = ? AND user_id = ?
        """,
        (ten, ten_chuan, icon, steps_json, version, _now(), routine_id, user_id),
    )
    conn.commit()
    return get_routine(user_id, routine_id, connection=conn)


def set_enabled(
    user_id: str, routine_id: str, *, enabled: bool, connection: sqlite3.Connection | None = None
) -> Routine:
    """Bật/tắt. Không đổi `version`, nên không bắt xem lại preview."""
    conn = connection or get_connection()
    _tim(conn, user_id, routine_id)
    conn.execute(
        "UPDATE routines SET enabled = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (1 if enabled else 0, _now(), routine_id, user_id),
    )
    conn.commit()
    return get_routine(user_id, routine_id, connection=conn)


def delete_routine(user_id: str, routine_id: str, *, connection: sqlite3.Connection | None = None) -> None:
    """Xoá Routine tự tạo. Mẫu mặc định ném `KhongXoaDuocMauError`.

    Routine **đang chạy** thì ném `RoutineDangChayError` (#297): acceptance criteria của
    #272 cho hai vế — chặn, hoặc bắt hủy execution trước — và đây chọn vế chặn, vì tự hủy
    hộ là quyết định thay người dùng về một chuỗi lệnh đang tác động lên xe.
    """
    from src.services.routine_execution import RoutineDangChayError, dang_chay_cua_routine

    conn = connection or get_connection()
    row = _tim(conn, user_id, routine_id)
    if row["is_default_template"]:
        raise KhongXoaDuocMauError(routine_id)
    dang_chay = dang_chay_cua_routine(routine_id, connection=conn)
    if dang_chay is not None:
        # Acceptance criteria #272: *"xoá Routine đang chạy bị chặn hoặc yêu cầu hủy
        # execution trước"*. Chọn vế **chặn**: tự hủy hộ là quyết định thay người dùng
        # về một chuỗi lệnh đang tác động lên xe, và họ có thể chỉ định xoá nhầm.
        raise RoutineDangChayError(dang_chay.id)
    conn.execute("DELETE FROM routines WHERE id = ? AND user_id = ?", (routine_id, user_id))
    conn.commit()


def restore_default(user_id: str, routine_id: str, *, connection: sqlite3.Connection | None = None) -> Routine:
    """Đưa một mẫu đã sửa về nội dung gốc. Ném `KhongPhaiMauError` nếu là Routine tự tạo.

    Khôi phục **bump version** như một lần sửa: nội dung vừa đổi, và người dùng nên nghe
    lại xem thứ họ sắp chạy là gì. Đây là ca dễ bỏ sót nhất — "khôi phục" nghe như quay
    về trạng thái cũ, nhưng với người ngồi trong xe thì nó là một Routine khác với cái
    họ vừa chạy lần trước.
    """
    import json

    conn = connection or get_connection()
    row = _tim(conn, user_id, routine_id)
    origin = row["template_origin"]
    if not row["is_default_template"] or origin is None:
        raise KhongPhaiMauError(routine_id)
    mau = next((m for m in MAU_MAC_DINH if m.origin == origin), None)
    if mau is None:  # pragma: no cover - CHECK của DB đã chặn origin lạ
        raise KhongPhaiMauError(origin)

    steps_json = json.dumps(list(mau.steps), ensure_ascii=False)
    doi = steps_json != row["steps_json"] or mau.name != row["name"]
    version = int(row["version"]) + 1 if doi else int(row["version"])
    conn.execute(
        """
        UPDATE routines
           SET name = ?, name_normalized = ?, icon = ?, steps_json = ?, version = ?, updated_at = ?
         WHERE id = ? AND user_id = ?
        """,
        (mau.name, chuan_hoa_ten(mau.name), mau.icon, steps_json, version, _now(), routine_id, user_id),
    )
    conn.commit()
    return get_routine(user_id, routine_id, connection=conn)


__all__ = [
    "ICONS",
    "MAU_MAC_DINH",
    "MAX_BUOC",
    "MAX_TEN",
    "IconKhongHopLeError",
    "KhongPhaiMauError",
    "KhongXoaDuocMauError",
    "Routine",
    "RoutineDichError",
    "RoutineKhongTonTaiError",
    "TenKhongHopLeError",
    "TenTrungError",
    "bootstrap_templates",
    "chuan_hoa_ten",
    "create_routine",
    "delete_routine",
    "get_routine",
    "list_routines",
    "restore_default",
    "set_enabled",
    "update_routine",
]

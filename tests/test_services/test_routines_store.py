"""Lưu trữ Routine (issue #282).

Trọng tâm không phải "CRUD chạy được" mà là bốn thứ hỏng âm thầm:

1. cô lập theo tài khoản — id đoán trúng vẫn không đọc được;
2. bootstrap mẫu idempotent — gọi lại không sinh mẫu thứ hai;
3. `version` bump đúng lúc — sửa nội dung thì preview quay lại, đổi icon thì không;
4. luật hợp lệ đúng bằng luật lúc chạy — thứ lưu được phải là thứ chạy được.
"""

import json
from pathlib import Path

import pytest

from src.agents.routines import RoutineDichError
from src.db import connect, ensure_schema
from src.services.routines_store import (
    MAU_MAC_DINH,
    KhongPhaiMauError,
    KhongXoaDuocMauError,
    RoutineKhongTonTaiError,
    TenKhongHopLeError,
    TenTrungError,
    bootstrap_templates,
    chuan_hoa_ten,
    create_routine,
    delete_routine,
    get_routine,
    list_routines,
    restore_default,
    set_enabled,
    update_routine,
)

_BUOC_HOP_LE = [{"action": "hvac_temperature", "temperatureC": 22}]


@pytest.fixture
def conn(tmp_path):
    """Một DB thật trên đĩa, không `:memory:` — test restart cần mở lại cùng file."""
    connection = connect(tmp_path / "routines.db")
    ensure_schema(connection)
    for user_id in ("usr_a", "usr_b"):
        connection.execute(
            "INSERT INTO users (id, email, password_hash, role) VALUES (?, ?, 'x', 'driver')",
            (user_id, f"{user_id}@example.com"),
        )
    connection.commit()
    yield connection
    connection.close()


# --- cô lập theo tài khoản ---------------------------------------------------


def test_id_cua_nguoi_khac_va_id_khong_ton_tai_khong_phan_biet_duoc(conn):
    """Cùng một exception cho hai ca — trả lỗi khác nhau là xác nhận Routine có thật.

    Đây là acceptance criteria của #272: *"truy cập chéo user bị từ chối mà không làm
    lộ Routine có tồn tại hay không"*.
    """
    cua_a = create_routine("usr_a", name="Của A", icon="car", steps=_BUOC_HOP_LE, connection=conn)

    with pytest.raises(RoutineKhongTonTaiError):
        get_routine("usr_b", cua_a.id, connection=conn)
    with pytest.raises(RoutineKhongTonTaiError):
        get_routine("usr_b", "rtn_khong_bao_gio_ton_tai", connection=conn)


def test_sua_va_xoa_cheo_user_deu_khong_cham_duoc_du_lieu(conn):
    cua_a = create_routine("usr_a", name="Của A", icon="car", steps=_BUOC_HOP_LE, connection=conn)

    with pytest.raises(RoutineKhongTonTaiError):
        update_routine("usr_b", cua_a.id, name="Cướp", icon="car", steps=_BUOC_HOP_LE, connection=conn)
    with pytest.raises(RoutineKhongTonTaiError):
        delete_routine("usr_b", cua_a.id, connection=conn)
    with pytest.raises(RoutineKhongTonTaiError):
        set_enabled("usr_b", cua_a.id, enabled=False, connection=conn)

    con_nguyen = get_routine("usr_a", cua_a.id, connection=conn)
    assert con_nguyen.name == "Của A"
    assert con_nguyen.enabled is True


def test_danh_sach_cua_user_nay_khong_chua_routine_cua_user_kia(conn):
    create_routine("usr_a", name="Chỉ của A", icon="car", steps=_BUOC_HOP_LE, connection=conn)

    ten_cua_b = {r.name for r in list_routines("usr_b", connection=conn)}
    assert "Chỉ của A" not in ten_cua_b


def test_hai_user_dat_trung_ten_khong_dam_nhau(conn):
    """Tên unique **theo user**, không phải toàn hệ thống."""
    create_routine("usr_a", name="Buổi sáng", icon="sun", steps=_BUOC_HOP_LE, connection=conn)
    cua_b = create_routine("usr_b", name="Buổi sáng", icon="sun", steps=_BUOC_HOP_LE, connection=conn)

    assert cua_b.user_id == "usr_b"


# --- bootstrap mẫu -----------------------------------------------------------


def test_bootstrap_idempotent_goi_lai_khong_sinh_mau_thu_hai(conn):
    assert bootstrap_templates("usr_a", connection=conn) == len(MAU_MAC_DINH)
    assert bootstrap_templates("usr_a", connection=conn) == 0

    mau = [r for r in list_routines("usr_a", connection=conn) if r.is_default_template]
    assert len(mau) == len(MAU_MAC_DINH)
    assert {r.template_origin for r in mau} == {m.origin for m in MAU_MAC_DINH}


def test_mau_mac_dinh_khong_bat_preview_luot_dau(conn):
    """Nội dung do PM/PO chốt và người dùng chưa sửa gì — không có gì để họ duyệt."""
    mau = [r for r in list_routines("usr_a", connection=conn) if r.is_default_template]
    assert all(r.needs_preview is False for r in mau)


def test_mau_khop_tung_buoc_voi_ban_frontend():
    """Bản BE và bản `routineTemplates.ts` phải cùng nội dung.

    Không so từng byte (một bên là Python, một bên TypeScript) mà so **cấu trúc bước**:
    FE mock đang là thứ người dùng thấy hôm nay, nên lệch đi là đổi hành vi ngay lúc
    chuyển sang `real.ts`.
    """
    nguon = Path("frontend/src/lib/fixtures/routineTemplates.ts").read_text(encoding="utf-8")
    for mau in MAU_MAC_DINH:
        assert f'origin: "{mau.origin}"' in nguon
        assert f'name: "{mau.name}"' in nguon
        for buoc in mau.steps:
            assert f'action: "{buoc["action"]}"' in nguon


# --- tồn tại sau restart -----------------------------------------------------


def test_routine_song_sot_sau_khi_mo_lai_ket_noi(tmp_path):
    duong_dan = tmp_path / "restart.db"
    conn = connect(duong_dan)
    ensure_schema(conn)
    conn.execute("INSERT INTO users (id, email, password_hash, role) VALUES ('usr_a', 'a@x.vn', 'x', 'driver')")
    conn.commit()
    da_tao = create_routine("usr_a", name="Sau restart", icon="moon", steps=_BUOC_HOP_LE, connection=conn)
    conn.close()

    lai = connect(duong_dan)
    ensure_schema(lai)
    try:
        con_do = get_routine("usr_a", da_tao.id, connection=lai)
        assert con_do.name == "Sau restart"
        assert con_do.steps == tuple(_BUOC_HOP_LE)
    finally:
        lai.close()


# --- version và preview ------------------------------------------------------


def test_sua_buoc_bump_version_va_bat_lai_preview(conn):
    goc = create_routine("usr_a", name="Sáng", icon="sun", steps=_BUOC_HOP_LE, connection=conn)
    conn.execute("UPDATE routines SET previewed_version = version WHERE id = ?", (goc.id,))
    conn.commit()
    assert get_routine("usr_a", goc.id, connection=conn).needs_preview is False

    sau = update_routine(
        "usr_a",
        goc.id,
        name="Sáng",
        icon="sun",
        steps=[{"action": "hvac_temperature", "temperatureC": 25}],
        connection=conn,
    )

    assert sau.version == goc.version + 1
    assert sau.needs_preview is True


def test_doi_moi_icon_khong_bump_version(conn):
    """Icon không đổi việc Routine sẽ làm. Bắt nghe lại preview vì một biểu tượng là
    dạy tài xế bấm qua preview cho nhanh."""
    goc = create_routine("usr_a", name="Sáng", icon="sun", steps=_BUOC_HOP_LE, connection=conn)

    sau = update_routine("usr_a", goc.id, name="Sáng", icon="moon", steps=_BUOC_HOP_LE, connection=conn)

    assert sau.version == goc.version
    assert sau.icon == "moon"


def test_bat_tat_khong_bump_version(conn):
    goc = create_routine("usr_a", name="Sáng", icon="sun", steps=_BUOC_HOP_LE, connection=conn)

    sau = set_enabled("usr_a", goc.id, enabled=False, connection=conn)

    assert sau.enabled is False
    assert sau.version == goc.version


# --- luật hợp lệ tại ranh giới ghi -------------------------------------------


def test_khong_luu_duoc_routine_rong_hoac_qua_bon_buoc(conn):
    with pytest.raises(RoutineDichError) as rong:
        create_routine("usr_a", name="Rỗng", icon="car", steps=[], connection=conn)
    assert rong.value.ma == "routine_rong"

    with pytest.raises(RoutineDichError) as nhieu:
        create_routine("usr_a", name="Dài", icon="car", steps=_BUOC_HOP_LE * 5, connection=conn)
    assert nhieu.value.ma == "qua_nhieu_buoc"


def test_gia_tri_ngoai_dai_bi_chan_ngay_luc_luu(conn):
    """35 °C nằm ngoài 16–30 của `SetHvacTemperatureArgs`.

    Đây là chỗ `_DICH` một mình **không** đủ: nó chỉ kiểm kiểu, dải sống ở
    `tool_registry`. Một hàng 35 °C lọt vào bảng sẽ nổ lúc thực thi, giữa một lượt nói.
    """
    with pytest.raises(RoutineDichError) as exc:
        create_routine(
            "usr_a",
            name="Nóng",
            icon="car",
            steps=[{"action": "hvac_temperature", "temperatureC": 35}],
            connection=conn,
        )
    assert exc.value.ma == "gia_tri_ngoai_dai"


def test_action_ngoai_allowlist_bi_tu_choi(conn):
    with pytest.raises(RoutineDichError) as exc:
        create_routine(
            "usr_a",
            name="Mở cửa",
            icon="car",
            steps=[{"action": "door_state", "door": "front_left", "state": "open"}],
            connection=conn,
        )
    assert exc.value.ma == "action_khong_ho_tro"


def test_buoc_dan_duong_luu_duoc_du_chua_gan_dia_diem(conn):
    """Chưa gán Nhà/Cơ quan là **bình thường**, không phải lỗi lưu.

    Spec §Nhà và Cơ quan chốt Routine ấy hiển thị "Cần thiết lập". Nếu validate lúc lưu
    dùng `routine_thanh_candidate` thì cả ba mẫu mặc định không bootstrap nổi.
    """
    routine = create_routine(
        "usr_a",
        name="Đi làm của tôi",
        icon="briefcase",
        steps=[{"action": "navigation", "destination": "office"}],
        connection=conn,
    )

    assert routine.needs_setup is True
    assert routine.runnable is False


def test_gan_dia_diem_thi_thoi_can_thiet_lap(conn):
    routine = create_routine(
        "usr_a",
        name="Đi làm của tôi",
        icon="briefcase",
        steps=[{"action": "navigation", "destination": "office"}],
        connection=conn,
    )
    conn.execute(
        "INSERT INTO user_places (user_id, label, destination_id, updated_at)"
        " VALUES ('usr_a', 'office', 'poi-cafe-01', '2026-08-29T00:00:00+00:00')"
    )
    conn.commit()

    sau = get_routine("usr_a", routine.id, connection=conn)
    assert sau.needs_setup is False
    assert sau.runnable is True


def test_routine_bi_tat_khong_bao_gio_runnable(conn):
    routine = create_routine("usr_a", name="Tắt đi", icon="car", steps=_BUOC_HOP_LE, connection=conn)

    sau = set_enabled("usr_a", routine.id, enabled=False, connection=conn)

    assert sau.runnable is False


def test_ten_trung_sau_chuan_hoa_bi_tu_choi(conn):
    create_routine("usr_a", name="Buổi Sáng", icon="sun", steps=_BUOC_HOP_LE, connection=conn)

    with pytest.raises(TenTrungError):
        create_routine("usr_a", name="  buổi   sáng ", icon="sun", steps=_BUOC_HOP_LE, connection=conn)


def test_chuan_hoa_ten_khop_luat_cua_frontend():
    assert chuan_hoa_ten("  Buổi   Sáng  ") == "buổi sáng"


def test_ten_rong_hoac_qua_dai_bi_tu_choi(conn):
    with pytest.raises(TenKhongHopLeError):
        create_routine("usr_a", name="   ", icon="car", steps=_BUOC_HOP_LE, connection=conn)
    with pytest.raises(TenKhongHopLeError):
        create_routine("usr_a", name="x" * 61, icon="car", steps=_BUOC_HOP_LE, connection=conn)


def test_doi_ten_ve_chinh_no_khong_bi_bao_trung(conn):
    """Sửa Routine mà không đổi tên là ca thường gặp nhất — nó không được tự đâm mình."""
    goc = create_routine("usr_a", name="Sáng", icon="sun", steps=_BUOC_HOP_LE, connection=conn)

    sau = update_routine(
        "usr_a",
        goc.id,
        name="Sáng",
        icon="sun",
        steps=[{"action": "hvac_fan_level", "level": 2}],
        connection=conn,
    )

    assert sau.id == goc.id


# --- mẫu mặc định: xoá và khôi phục -----------------------------------------


def test_khong_xoa_duoc_mau_mac_dinh(conn):
    mau = next(r for r in list_routines("usr_a", connection=conn) if r.is_default_template)

    with pytest.raises(KhongXoaDuocMauError):
        delete_routine("usr_a", mau.id, connection=conn)


def test_xoa_duoc_routine_tu_tao(conn):
    routine = create_routine("usr_a", name="Tạm", icon="car", steps=_BUOC_HOP_LE, connection=conn)

    delete_routine("usr_a", routine.id, connection=conn)

    with pytest.raises(RoutineKhongTonTaiError):
        get_routine("usr_a", routine.id, connection=conn)


def test_khoi_phuc_mau_ve_dung_noi_dung_goc_va_bump_version(conn):
    mau = next(r for r in list_routines("usr_a", connection=conn) if r.template_origin == "thu_gian")
    da_sua = update_routine(
        "usr_a",
        mau.id,
        name="Thư giãn kiểu tôi",
        icon="music",
        steps=[{"action": "hvac_fan_level", "level": 1}],
        connection=conn,
    )

    khoi_phuc = restore_default("usr_a", mau.id, connection=conn)

    goc = next(m for m in MAU_MAC_DINH if m.origin == "thu_gian")
    assert khoi_phuc.name == goc.name
    assert khoi_phuc.steps == goc.steps
    assert khoi_phuc.version == da_sua.version + 1
    assert khoi_phuc.needs_preview is True


def test_khoi_phuc_tren_routine_tu_tao_bi_tu_choi(conn):
    routine = create_routine("usr_a", name="Tự tạo", icon="car", steps=_BUOC_HOP_LE, connection=conn)

    with pytest.raises(KhongPhaiMauError):
        restore_default("usr_a", routine.id, connection=conn)


def test_steps_luu_nguyen_dang_camelcase_cua_frontend(conn):
    """Dạng lưu phải là dạng `src/agents/routines.py` nhận — dịch hai lần là hai bảng."""
    routine = create_routine(
        "usr_a",
        name="Điều hoà",
        icon="car",
        steps=[{"action": "hvac_temperature", "temperatureC": 24}],
        connection=conn,
    )

    row = conn.execute("SELECT steps_json FROM routines WHERE id = ?", (routine.id,)).fetchone()
    assert json.loads(row["steps_json"]) == [{"action": "hvac_temperature", "temperatureC": 24}]

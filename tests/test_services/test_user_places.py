"""Địa điểm cá nhân Nhà/Cơ quan (issue #283).

Ba luật của module, mỗi luật một nhóm test:

1. không bao giờ có giá trị mặc định — chưa gán là `None`, không phải một POI nào đó;
2. đích phải thuộc tập đóng của fixture offline;
3. đích biến mất khỏi fixture ⇒ nhãn quay lại trạng thái chưa thiết lập.
"""

import pytest

from src.db import connect, ensure_schema
from src.fixtures import POI_CA_NHAN_THEO_NHAN, load_poi_fixture
from src.services.routines_store import create_routine, get_routine
from src.services.user_places import (
    NHAN_HOP_LE,
    DiaDiemKhongHopLeError,
    NhanKhongHopLeError,
    delete_place,
    get_places,
    nhan_da_gan,
    resolve,
    set_place,
)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "places.db")
    ensure_schema(connection)
    for user_id in ("usr_a", "usr_b"):
        connection.execute(
            "INSERT INTO users (id, email, password_hash, role) VALUES (?, ?, 'x', 'driver')",
            (user_id, f"{user_id}@example.com"),
        )
    connection.commit()
    yield connection
    connection.close()


# --- luật 1: không có mặc định ----------------------------------------------


def test_chua_gan_thi_khong_co_gi_ca(conn):
    """Không phải "trả POI đầu tiên", không phải "trả poi-home-01" — không có gì.

    `set_navigation` là S1, đi qua policy mà không ai duyệt, nên một mặc định ở đây
    nghĩa là chở tài xế tới chỗ họ không hề bảo.
    """
    assert get_places("usr_a", connection=conn) == {}
    assert resolve("usr_a", "home", connection=conn) is None
    assert resolve("usr_a", "office", connection=conn) is None


def test_bo_gan_khong_roi_ve_dich_cu(conn):
    set_place("usr_a", "home", "poi-home-01", connection=conn)

    assert delete_place("usr_a", "home", connection=conn) is True
    assert resolve("usr_a", "home", connection=conn) is None


def test_bo_gan_nhan_von_chua_gan_khong_phai_loi(conn):
    assert delete_place("usr_a", "office", connection=conn) is False


# --- luật 2: tập đóng --------------------------------------------------------


def test_dich_ngoai_fixture_bi_tu_choi(conn):
    with pytest.raises(DiaDiemKhongHopLeError):
        set_place("usr_a", "home", "poi-khong-ton-tai", connection=conn)

    assert get_places("usr_a", connection=conn) == {}


def test_nhan_thu_ba_bi_tu_choi(conn):
    with pytest.raises(NhanKhongHopLeError):
        set_place("usr_a", "bep", "poi-home-01", connection=conn)


def test_gan_duoc_bat_ky_poi_nao_trong_tam_diem(conn):
    """Spec §Nhà và Cơ quan: người dùng chọn trong **tám điểm cố định**.

    `POI_CA_NHAN_THEO_NHAN` là gợi ý cho UI, không phải giới hạn — gán Nhà vào quán cà
    phê là hợp lệ, và test này khoá điều đó để không ai "siết cho chặt" thành một
    ràng buộc spec không đòi.
    """
    da_gan = set_place("usr_a", "home", "poi-cafe-01", connection=conn)

    assert da_gan.destination_id == "poi-cafe-01"
    assert da_gan.valid is True
    assert len(load_poi_fixture()) == 8


def test_hai_nhan_goi_y_tro_toi_poi_mang_dung_ten(conn):
    for nhan, poi_id in POI_CA_NHAN_THEO_NHAN.items():
        da_gan = set_place("usr_a", nhan, poi_id, connection=conn)
        assert da_gan.valid is True
        assert da_gan.name in {"Nhà", "Cơ quan"}


# --- luật 3: đích biến mất ---------------------------------------------------


def test_dich_bien_mat_khoi_fixture_thi_khong_con_tinh_la_da_gan(conn):
    """Hàng vẫn còn trong DB — không tự xoá dữ liệu người dùng — nhưng `valid=False`.

    Đây là ca spec nêu riêng: *"khi destination offline không còn hợp lệ, Routine chuyển
    sang trạng thái cần thiết lập"*. Ghi thẳng vào DB để giả lập POI bị gỡ khỏi fixture.
    """
    conn.execute(
        "INSERT INTO user_places (user_id, label, destination_id, updated_at)"
        " VALUES ('usr_a', 'home', 'poi-da-bi-go', '2026-08-29T00:00:00+00:00')"
    )
    conn.commit()

    dia_diem = get_places("usr_a", connection=conn)["home"]
    assert dia_diem.valid is False
    assert dia_diem.name is None
    assert resolve("usr_a", "home", connection=conn) is None
    assert nhan_da_gan("usr_a", connection=conn) == set()


def test_routine_dan_duong_quay_ve_can_thiet_lap_khi_dich_bien_mat(conn):
    """Nối hai module: `needs_setup` của Routine phải phản ánh luật 3, không chỉ sự tồn
    tại của một hàng trong `user_places`."""
    routine = create_routine(
        "usr_a",
        name="Đi làm",
        icon="briefcase",
        steps=[{"action": "navigation", "destination": "office"}],
        connection=conn,
    )
    set_place("usr_a", "office", "poi-work-01", connection=conn)
    assert get_routine("usr_a", routine.id, connection=conn).needs_setup is False

    conn.execute("UPDATE user_places SET destination_id = 'poi-da-bi-go' WHERE user_id = 'usr_a'")
    conn.commit()

    assert get_routine("usr_a", routine.id, connection=conn).needs_setup is True


# --- cô lập theo tài khoản ---------------------------------------------------


def test_dia_diem_cua_user_nay_khong_lo_sang_user_kia(conn):
    set_place("usr_a", "home", "poi-home-01", connection=conn)

    assert get_places("usr_b", connection=conn) == {}
    assert resolve("usr_b", "home", connection=conn) is None


def test_doi_dia_diem_cua_minh_khong_cham_nguoi_khac(conn):
    set_place("usr_a", "home", "poi-home-01", connection=conn)
    set_place("usr_b", "home", "poi-cafe-02", connection=conn)

    set_place("usr_a", "home", "poi-mall-01", connection=conn)

    assert resolve("usr_b", "home", connection=conn) == "poi-cafe-02"


def test_gan_lai_ghi_de_chu_khong_tao_hang_thu_hai(conn):
    set_place("usr_a", "home", "poi-home-01", connection=conn)
    set_place("usr_a", "home", "poi-cafe-01", connection=conn)

    rows = conn.execute("SELECT COUNT(*) AS n FROM user_places WHERE user_id = 'usr_a'").fetchone()
    assert rows["n"] == 1
    assert resolve("usr_a", "home", connection=conn) == "poi-cafe-01"


def test_chi_co_dung_hai_nhan(conn):
    assert NHAN_HOP_LE == ("home", "office")

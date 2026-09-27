"""Tầng schema SQLite — issue #46."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.db import (
    DEMO_USERS,
    connect,
    ensure_schema,
    expire_and_purge_sessions,
    hash_password,
    invalidate_orphaned_pending_approvals,
    resolve_db_path,
    seed_demo_users,
    verify_password,
)


def _approval(conn, approval_id: str, session_id: str, status: str) -> None:
    conn.execute(
        "INSERT INTO approvals (id, session_id, turn_id, plan_id, plan_digest,"
        " vehicle_state_version, status, expires_at, created_at)"
        " VALUES (?, ?, 't', 'p', 'd', 1, ?, 'x', 'y')",
        (approval_id, session_id, status),
    )


def test_dung_schema_hai_lan_khong_loi():
    """Không có công cụ migration nên `ensure_schema` chạy mỗi lần khởi động."""
    conn = connect(":memory:")
    ensure_schema(conn)
    ensure_schema(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "sessions", "approvals", "idempotency_records"} <= names


def test_partial_index_chan_pending_thu_hai_o_tang_db():
    """`safety_and_hitl.md:41` đòi bất biến này là ràng buộc DB, không phải dict Python.

    Khác biệt thật: dict chỉ chặn trong một tiến trình, còn index chặn cả khi có hai
    tiến trình cùng ghi — thứ mà `MAX_SESSIONS`/worker tương lai sẽ chạm tới.
    """
    conn = connect(":memory:")
    ensure_schema(conn)
    _approval(conn, "a1", "ses-1", "pending")

    with pytest.raises(sqlite3.IntegrityError):
        _approval(conn, "a2", "ses-1", "pending")


def test_nhieu_ban_ghi_da_chot_cung_session_van_hop_le():
    """Chỉ *pending* mới bị giới hạn một; lịch sử approval của một phiên thì không."""
    conn = connect(":memory:")
    ensure_schema(conn)
    _approval(conn, "a1", "ses-1", "consumed")
    _approval(conn, "a2", "ses-1", "rejected")
    _approval(conn, "a3", "ses-1", "pending")

    rows = conn.execute("SELECT COUNT(*) AS n FROM approvals WHERE session_id = 'ses-1'").fetchone()
    assert rows["n"] == 3


def test_sqlite_memory_url_khong_tao_file():
    """`Path(":memory:")` sẽ tạo một file tên đúng như vậy — phải trả về chuỗi."""
    assert resolve_db_path("sqlite:///:memory:") == ":memory:"


def test_mat_khau_khong_bao_gio_luu_tho():
    encoded = hash_password("DemoDriver123!")
    assert "DemoDriver123!" not in encoded
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("DemoDriver123!", encoded)
    assert not verify_password("DemoDriver123", encoded)


def test_hai_lan_bam_cung_mat_khau_ra_hai_chuoi_khac_nhau():
    """Salt ngẫu nhiên: hai user cùng mật khẩu không được lộ ra qua hash trùng nhau."""
    assert hash_password("trung-mat-khau") != hash_password("trung-mat-khau")


def test_chuoi_hash_hong_tra_false_chu_khong_raise():
    """Dữ liệu hỏng trên đĩa phải thành "sai mật khẩu", không thành 500."""
    for broken in ("", "khong-co-dau-do-la", "pbkdf2_sha256$x$y", "argon2$1$aa$bb", "pbkdf2_sha256$abc$aa$bb"):
        assert verify_password("bat-ky", broken) is False


def test_seed_demo_user_chay_lai_khong_doi_hash():
    """`INSERT OR IGNORE` chứ không upsert — chạy lại không được sinh salt mới."""
    conn = connect(":memory:")
    ensure_schema(conn)
    seed_demo_users(conn)
    first = conn.execute("SELECT password_hash FROM users WHERE id = 'usr_driver_01'").fetchone()[0]
    seed_demo_users(conn)
    after = conn.execute("SELECT password_hash FROM users WHERE id = 'usr_driver_01'").fetchone()[0]

    assert first == after
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == len(DEMO_USERS)
    for _user_id, _email, password, _role, _name in DEMO_USERS:
        assert password not in first


def test_pending_con_sot_bi_invalidate_luc_khoi_dong():
    """Bản ghi approval sống qua restart nhưng *lượt* thì không: checkpoint chứa
    `interrupt()` nằm trong `InMemorySaver` và chết theo tiến trình.

    Để nguyên `pending` thì tài xế bấm Đồng ý vào một thread không còn interrupt nào.
    Fail-closed: bắt hỏi lại còn hơn treo im lặng.
    """
    conn = connect(":memory:")
    ensure_schema(conn)
    _approval(conn, "a1", "ses-1", "pending")
    _approval(conn, "a2", "ses-2", "consumed")

    assert invalidate_orphaned_pending_approvals(conn) == 1
    statuses = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM approvals")}
    assert statuses == {"a1": "invalidated", "a2": "consumed"}
    # Chạy lại lúc khởi động sau đó không được đụng gì nữa.
    assert invalidate_orphaned_pending_approvals(conn) == 0


def test_khoi_dong_app_vo_hieu_hoa_approval_con_treo():
    """Nối vào vòng đời app: `lifespan` phải gọi bước fail-closed này.

    Kiểm qua `TestClient` (chạy lifespan thật) chứ không gọi thẳng hàm — thứ dễ vỡ
    ở đây là *dây nối*, không phải logic UPDATE đã có test riêng bên trên.
    """
    from fastapi.testclient import TestClient

    from src.db import get_connection
    from src.main import app

    connection = get_connection()
    _approval(connection, "appr-treo-qua-restart", "ses-treo", "pending")
    connection.commit()

    with TestClient(app):
        pass

    status = connection.execute("SELECT status FROM approvals WHERE id = 'appr-treo-qua-restart'").fetchone()[0]
    assert status == "invalidated"


def _session(conn, session_id: str, started_at: str, status: str = "active") -> None:
    conn.execute("INSERT OR IGNORE INTO users (id, email, password_hash, role) VALUES ('u1','u1@x','','driver')")
    conn.execute(
        "INSERT INTO sessions (id, user_id, vehicle_id, status, started_at) VALUES (?, 'u1', 'veh', ?, ?)",
        (session_id, status, started_at),
    )


def test_session_khong_the_mo_coi_vi_user_id_la_khoa_ngoai():
    """`data_model.md:43` đòi FK. Bản đầu của #46 bỏ nó đi; Thành bác ở review PR #89.

    Không có FK thì DB cho phép phiên trỏ tới một chủ nhân không tồn tại, và mọi truy
    vết ownership sau này chỉ còn tin được bằng niềm tin vào tầng API.
    """
    conn = connect(":memory:")
    ensure_schema(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sessions (id, user_id, vehicle_id, status, started_at)"
            " VALUES ('ses-mo-coi', 'usr_khong_ton_tai', 'veh', 'active', 'x')"
        )


def test_session_qua_han_bi_chot_expired_va_giu_lai_de_audit():
    """Hai mốc, hai bước. Bước một chỉ đổi `status` — phiên hết dùng được nhưng vẫn
    đọc được, nên còn truy được nó kết thúc lúc nào."""
    conn = connect(":memory:")
    ensure_schema(conn)
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    _session(conn, "ses-moi", (now - timedelta(hours=1)).isoformat())
    _session(conn, "ses-cu", (now - timedelta(hours=25)).isoformat())

    expired, purged = expire_and_purge_sessions(conn, now=now, ttl_hours=24.0, retention_days=30.0)

    assert (expired, purged) == (1, 0)
    rows = {r["id"]: (r["status"], r["ended_at"]) for r in conn.execute("SELECT id, status, ended_at FROM sessions")}
    assert rows["ses-moi"] == ("active", None)
    assert rows["ses-cu"][0] == "expired"
    assert rows["ses-cu"][1] == now.isoformat(), "phải ghi mốc kết thúc, nếu không thì hết hạn là mất dấu"


def test_session_qua_moc_luu_tru_bi_xoa_han():
    """Bước hai mới xoá, và chỉ xoá thứ cũ hơn mốc `data_model.md:43` (30 ngày demo)."""
    conn = connect(":memory:")
    ensure_schema(conn)
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    _session(conn, "ses-vua-het-han", (now - timedelta(hours=25)).isoformat())
    _session(conn, "ses-rat-cu", (now - timedelta(days=31)).isoformat())

    expired, purged = expire_and_purge_sessions(conn, now=now, ttl_hours=24.0, retention_days=30.0)

    assert purged == 1
    remaining = {r["id"] for r in conn.execute("SELECT id FROM sessions")}
    assert remaining == {"ses-vua-het-han"}, "phiên vừa hết hạn phải còn lại để audit"
    assert expired == 2, "cả hai đều quá TTL nên đều bị chốt trước khi bước xoá chạy"


def test_don_session_chay_lai_khong_doi_gi_them():
    """Idempotent — nó chạy mỗi lần khởi động và mỗi lần tạo phiên."""
    conn = connect(":memory:")
    ensure_schema(conn)
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    _session(conn, "ses-cu", (now - timedelta(hours=25)).isoformat())

    assert expire_and_purge_sessions(conn, now=now, ttl_hours=24.0, retention_days=30.0) == (1, 0)
    assert expire_and_purge_sessions(conn, now=now, ttl_hours=24.0, retention_days=30.0) == (0, 0)


def test_database_url_sai_scheme_bao_ro_phai_sua_gi():
    """Issue #93: thông báo phải nói đủ ba thứ — sai ở đâu, đúng là gì, sửa file nào.

    Bản trước chỉ ném `unsupported DATABASE_URL scheme: 'postgresql://...'` giữa một
    traceback import, và người gặp nó không có cách nào biết `.env` của mình mang dòng
    boilerplate cũ. `.env` không được git track nên việc sửa `.env.example` ở #89
    không chạm tới máy của ai cả.
    """
    with pytest.raises(ValueError) as exc:
        resolve_db_path("postgresql://user:password@localhost:5432/dbname")

    message = str(exc.value)
    assert "postgresql://user:password@localhost:5432/dbname" in message, "phải nêu giá trị đang sai"
    assert "sqlite:///./data/app.db" in message, "phải nêu giá trị đúng để copy thẳng"
    assert ".env" in message, "phải nói sửa ở file nào"

"""Kết nối SQLite tối giản cho `database_url` — dùng bởi probe sqlite của /healthz.

`database_url` đã khai báo ở `src/config.py` từ trước nhưng chưa module nào mở
nó; đây là điểm mở đầu tiên, chỉ đủ cho một transaction đọc/ghi thăm dò sức khỏe.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from src.config import Settings, get_settings

_SQLITE_PREFIX = "sqlite:///"

#: Tên DB trong RAM của chính SQLite — không phải một đường dẫn.
MEMORY = ":memory:"


def resolve_db_path(database_url: str) -> Path | str:
    """Chuyển `sqlite:///relative/path` thành Path. Không hỗ trợ scheme khác.

    `sqlite:///:memory:` trả về **chuỗi** `":memory:"` chứ không phải Path: đó là
    tên đặc biệt của SQLite, `Path(":memory:")` sẽ tạo một file tên đúng như vậy.
    Bộ test dùng đường này để mỗi lần chạy có một DB sạch, không đụng `data/app.db`.
    """
    if not database_url.startswith(_SQLITE_PREFIX):
        # Thông báo phải nói đủ ba thứ: sai ở đâu, đúng là gì, sửa ở file nào. Bản
        # trước chỉ ném `unsupported DATABASE_URL scheme: 'postgresql://...'` giữa một
        # traceback import, và người gặp nó không có cách nào biết `.env` của mình
        # mang dòng boilerplate cũ (issue #93) — `.env` không được git track nên việc
        # sửa `.env.example` ở #89 không chạm tới máy của ai cả.
        raise ValueError(
            f"DATABASE_URL phải bắt đầu bằng {_SQLITE_PREFIX!r}, nhận được {database_url!r}. "
            f"Sửa dòng DATABASE_URL trong file .env thành 'sqlite:///./data/app.db' "
            f"(hoặc 'sqlite:///:memory:' cho DB tạm trong RAM). Xem .env.example."
        )
    location = database_url[len(_SQLITE_PREFIX) :]
    return MEMORY if location == MEMORY else Path(location)


def health_check(settings: Settings) -> None:
    """Mở kết nối, ghi/đọc/xoá một dòng thăm dò, commit.

    Raise `sqlite3.Error` (hoặc lỗi từ `resolve_db_path`) nếu bất kỳ bước nào lỗi
    — caller (`src/services/health.py::probe_sqlite`) diễn giải raise thành `down`.
    """
    db_path = resolve_db_path(settings.database_url)
    if isinstance(db_path, Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=settings.health_probe_timeout_s)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS _healthz_probe (id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO _healthz_probe (checked_at) VALUES (datetime('now'))")
        row = connection.execute("SELECT COUNT(*) FROM _healthz_probe").fetchone()
        if row is None or row[0] < 1:
            raise sqlite3.OperationalError("healthz probe row missing after insert")
        connection.execute("DELETE FROM _healthz_probe")
        connection.commit()
    finally:
        connection.close()


#: Schema domain. `CREATE TABLE IF NOT EXISTS` thay cho công cụ migration: P0 chỉ có
#: một hình dạng schema và chưa từng phải nâng cấp dữ liệu cũ. Khi nào cần đổi cột thì
#: đó là lúc mang Alembic vào, không phải bây giờ.
#:
#: Bốn bảng theo `docs/data_model.md`; `action_plans`/`plan_steps` **cố ý chưa có** —
#: xem ADR đi kèm issue #46.
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1
    )
    """,
    # `user_id` là FOREIGN KEY thật, theo `data_model.md:43`.
    #
    # Bản đầu của PR #46 bỏ nó đi với lý do "ràng buộc này chặn mất các test cổng sở
    # hữu". Thành bác ở review PR #89, và bác đúng: chỉ có **ba** chỗ trong bộ test
    # dựng phiên cho user không tồn tại, mỗi chỗ chỉ cần seed một user vứt đi
    # (`seed_test_user` trong `tests/conftest.py`). Cái giá đó nhỏ, còn thứ đánh đổi
    # thì không: không có FK thì DB cho phép **session mồ côi**, và mọi truy vết
    # ownership/audit sau này chỉ còn tin được bằng niềm tin vào tầng API.
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        vehicle_id TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        plan_digest TEXT NOT NULL,
        vehicle_state_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        decided_at TEXT,
        prompt_text TEXT NOT NULL DEFAULT '',
        steps_summary_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    # Bất biến "tối đa một pending approval mỗi session" (`safety_and_hitl.md:41`) nay
    # là ràng buộc của **cơ sở dữ liệu**, không phải một dict tra cứu trong Python.
    # Đây là chỗ persistence làm bất biến MẠNH LÊN chứ không chỉ bền hơn: hai tiến
    # trình cùng ghi vẫn không thể tạo hai pending, thứ mà dict không bao giờ chặn được.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS approvals_one_pending_per_session
        ON approvals (session_id) WHERE status = 'pending'
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_records (
        user_id TEXT NOT NULL,
        route TEXT NOT NULL,
        key TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        state TEXT NOT NULL,
        status_code INTEGER,
        body_json TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, route, key)
    )
    """,
    # Cấu hình xe (issue #123). **Không** nằm trong `vehicle_state`: ADR-013 chốt
    # snapshot của simulator là nguồn duy nhất và backend không được thêm bớt field
    # nào trên đường ra. Trim/pin cũng không phải trạng thái — nó không đổi khi xe
    # chạy, chỉ đổi khi đổi xe.
    #
    # `trim`/`battery` để NULL được, và NULL ở đây **có nghĩa**: "chưa biết cấu hình".
    # Đó là trạng thái hợp lệ chứ không phải dữ liệu khuyết — một chiếc xe chưa khai
    # báo cấu hình thì không có áp suất lốp đúng để trả, và người gọi phải fail-closed
    # về câu chỉ nguồn. Vì thế **không có DEFAULT nào**: một giá trị mặc định sẽ biến
    # "chưa biết" thành "biết sai", mà tài xế không có cách nào phân biệt hai thứ đó.
    #
    # CHECK chặn giá trị lạ ngay ở tầng dữ liệu, để một hàng hỏng không thể tồn tại
    # rồi mới nổ lúc `tra_ap_suat()` — `src/safety/ap_suat_lop.py` ném `ValueError`
    # cho tổ hợp lạ, và ta không muốn ValueError đó xảy ra giữa một lượt nói.
    """
    CREATE TABLE IF NOT EXISTS vehicle_profiles (
        vehicle_id TEXT PRIMARY KEY,
        trim TEXT CHECK (trim IS NULL OR trim IN ('eco', 'plus')),
        battery TEXT CHECK (battery IS NULL OR battery IN ('sdi', 'catl')),
        updated_at TEXT NOT NULL
    )
    """,
    # Trang bị tuỳ chọn của xe. **Bảng riêng, không phải cột thêm vào
    # `vehicle_profiles`**, vì hai lý do độc lập:
    #
    # 1. P0 không có công cụ migration — schema chạy bằng `CREATE TABLE IF NOT EXISTS`
    #    (xem chú thích ở đầu `_SCHEMA`). Thêm cột vào bảng đã tồn tại thì máy nào đã
    #    có file .db sẽ **không** nhận cột mới, và hỏng im lặng. Bảng mới thì không.
    # 2. Ba trạng thái mô hình hoá đúng hơn: **vắng hàng = chưa khai báo**. Không cần
    #    phân biệt NULL với thiếu khoá, và ta không phải chọn một mặc định — cùng kỷ
    #    luật "không có DEFAULT" của bảng trên, vì lý do y hệt.
    #
    # `co` là INTEGER 0/1 chứ không BOOLEAN: SQLite không có kiểu boolean, và viết
    # đúng thứ nó lưu thì người đọc schema không phải đoán.
    #
    # KHÔNG có CHECK trên `option_id`. Tập id nằm ở `src/safety/trang_bi.json` và dài
    # 65 mục còn đang lớn; nhân bản nó vào một CHECK là dựng nguồn sự thật thứ hai,
    # rồi hai bản lệch nhau lúc thêm trang bị mới. Ràng buộc thuộc về tầng ghi
    # (`set_vehicle_options` từ chối id lạ), nơi có sẵn danh mục để đối chiếu.
    """
    CREATE TABLE IF NOT EXISTS vehicle_options (
        vehicle_id TEXT NOT NULL,
        option_id TEXT NOT NULL,
        co INTEGER NOT NULL CHECK (co IN (0, 1)),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (vehicle_id, option_id)
    )
    """,
    # Routine của người dùng (issue #282, outcome #272). `user_id` là FK thật, cùng
    # lập luận với `sessions.user_id` ở trên: không có nó thì DB cho phép Routine mồ
    # côi, và "cô lập theo tài khoản" (`routines_product_spec.md` §Cô lập) chỉ còn
    # tin được bằng niềm tin vào tầng API.
    #
    # `version` là **số phiên bản nội dung**, tăng mỗi lần tên hoặc bước đổi. Nó tồn
    # tại vì §Preview của spec: preview bắt buộc ở lần chạy đầu của *mỗi phiên bản*,
    # nên "đã xem preview chưa" phải so được với một mốc, không thể là một cờ boolean
    # bị đặt lại bằng tay. `previewed_version` là mốc ấy; ai ghi nó là việc của #285,
    # module này chỉ đảm bảo nó không tự nhiên bằng `version` sau một lần sửa.
    #
    # `steps_json` giữ **nguyên dạng camelCase của `frontend/.../routines/types.ts`**,
    # không dịch sang tên tool canonical trước khi lưu. Lý do là `src/agents/routines.py`
    # đã tồn tại và nhận đúng dạng ấy: lưu dạng khác nghĩa là dịch hai lần, và bảng dịch
    # thứ hai sẽ lệch bảng thứ nhất đúng vào ngày ai đó thêm một action.
    """
    CREATE TABLE IF NOT EXISTS routines (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        name_normalized TEXT NOT NULL,
        icon TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        steps_json TEXT NOT NULL,
        is_default_template INTEGER NOT NULL DEFAULT 0 CHECK (is_default_template IN (0, 1)),
        template_origin TEXT CHECK (
            template_origin IS NULL OR template_origin IN ('di_lam', 've_nha', 'thu_gian')
        ),
        version INTEGER NOT NULL DEFAULT 1,
        previewed_version INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    # Tên duy nhất **theo user**, so trên bản đã chuẩn hoá (trim + hạ chữ thường + gộp
    # khoảng trắng) — cùng luật với `normalizeName` của FE mock, để một tên bị FE từ
    # chối cũng bị BE từ chối và ngược lại.
    #
    # Ràng buộc nằm ở DB chứ không chỉ ở service, cùng lý do với
    # `approvals_one_pending_per_session`: hai request song song vẫn không tạo nổi hai
    # Routine trùng tên, thứ mà một phép SELECT-rồi-INSERT không bao giờ chặn được.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS routines_name_unique_per_user
        ON routines (user_id, name_normalized)
    """,
    # Mẫu mặc định là **một hàng cho mỗi (user, origin)**, không phải hàng dùng chung.
    # Bootstrap phải idempotent (`#282` Done when), và index này là thứ khiến nó
    # idempotent thật: chạy lại `INSERT OR IGNORE` không thể sinh mẫu thứ hai kể cả khi
    # hai request khởi động cùng lúc.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS routines_one_template_per_user
        ON routines (user_id, template_origin) WHERE template_origin IS NOT NULL
    """,
    # Địa điểm cá nhân: đúng hai nhãn `home`/`office` cho mỗi user (issue #283).
    #
    # Bảng riêng chứ không phải hai cột thêm vào `users`, vì **vắng hàng = chưa gán** —
    # cùng mô hình ba trạng thái mà `vehicle_options` đã chọn, và cùng lý do: P0 không
    # có công cụ migration, nên thêm cột vào bảng đã tồn tại là hỏng im lặng trên máy
    # đã có file .db.
    #
    # KHÔNG có DEFAULT và không có giá trị dự phòng: `routines_product_spec.md` §Nhà và
    # Cơ quan chốt "không bao giờ rơi về một địa điểm mặc định" — một mặc định ở đây
    # nghĩa là dẫn tài xế tới chỗ họ không hề bảo, qua một tool S1 không ai duyệt.
    """
    CREATE TABLE IF NOT EXISTS user_places (
        user_id TEXT NOT NULL REFERENCES users(id),
        label TEXT NOT NULL CHECK (label IN ('home', 'office')),
        destination_id TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, label)
    )
    """,
    # Một lần chạy Routine (issue #286). Bản ghi **của lần chạy này**, không phải một
    # con trỏ vào Routine: `steps_json` là bản chụp các bước tại thời điểm admit.
    #
    # Chụp lại chứ không đọc lại, vì `#286` Done when nói *"không replay authorization
    # /plan cũ"* — và vế đối xứng cũng đúng: người dùng sửa Routine giữa lúc nó đang
    # chạy thì lần chạy này vẫn là lần chạy của phiên bản họ đã đồng ý, không phải một
    # nửa bản cũ ghép nửa bản mới.
    #
    # `cancel_requested` là **cờ**, không phải một trạng thái mới (issue #297). Trạng
    # thái nói *execution đang ở đâu*; cờ nói *người dùng đã yêu cầu dừng*. Gộp chúng
    # thành một trạng thái `canceling` sẽ buộc partial unique index phải kể thêm một giá
    # trị, và mỗi lần bổ sung như thế là một lần index cũ trên máy đã có file .db không
    # được cập nhật — `CREATE INDEX IF NOT EXISTS` không sửa index đã tồn tại.
    #
    # Điểm dừng an toàn là **giữa hai bước**: vòng lặp đọc cờ này trước mỗi bước, nên
    # lệnh đã publish lên MQTT vẫn chạy nốt. Một hệ báo "đã hủy" trong khi xe vừa mở
    # kính là một hệ nói dối (`routines_product_spec.md` §Hủy).
    #
    # `approval_id` là **của bước đang chờ**, không phải của cả execution: một Routine
    # hai bước S2 xin phê duyệt hai lần, tuần tự (`routines_product_spec.md` §Chạy —
    # đây là hệ quả của partial unique index một-pending-mỗi-session, không phải một
    # lựa chọn sản phẩm).
    """
    CREATE TABLE IF NOT EXISTS routine_executions (
        id TEXT PRIMARY KEY,
        routine_id TEXT NOT NULL,
        user_id TEXT NOT NULL REFERENCES users(id),
        session_id TEXT NOT NULL,
        vehicle_id TEXT NOT NULL,
        routine_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        current_index INTEGER NOT NULL DEFAULT 0,
        approval_id TEXT,
        steps_json TEXT NOT NULL,
        results_json TEXT NOT NULL,
        terminal_reason TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    # Tối đa **một** execution còn sống mỗi phiên, ép ở tầng dữ liệu.
    #
    # Cùng lý do với `approvals_one_pending_per_session`: hai request `run` song song
    # vẫn không tạo nổi hai chuỗi lệnh chạy chồng lên nhau trên cùng một chiếc xe, thứ
    # mà một phép SELECT-rồi-INSERT trong Python không bao giờ chặn được. Và nếu chồng
    # được thì hai Routine sẽ tranh nhau `expected_state_version`, nên bước của cái này
    # làm bước của cái kia `stale_state` — một chế độ hỏng không ai đọc log ra nổi.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS routine_executions_one_active_per_session
        ON routine_executions (session_id) WHERE status IN ('running', 'waiting_approval')
    """,
)


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Kết nối dùng chung cho mọi store domain.

    `check_same_thread=False` vì các store hiện đồng bộ và bị gọi từ nhiều thread của
    FastAPI; đúng khuôn `threading.Lock` mà `ApprovalStore` đã dùng. Không đổi sang
    async trong đợt này — đổi là lan sang graph và HITL.

    WAL cho phép đọc song song ghi; với một tiến trình demo thì nó chủ yếu tránh
    "database is locked" khi probe `/healthz` chạy cùng lúc với một quyết định approval.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if db_path != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Dựng schema. Gọi nhiều lần là an toàn — mọi câu đều `IF NOT EXISTS`."""
    for statement in _SCHEMA:
        connection.execute(statement)
    connection.commit()


# --- mật khẩu -------------------------------------------------------------
#
# PBKDF2-HMAC-SHA256 của `hashlib`, không thêm phụ thuộc (argon2/bcrypt) cho hai tài
# khoản demo. Điểm của đợt này không phải là chọn KDF mạnh nhất mà là **thôi lưu mật
# khẩu thô trong cơ sở dữ liệu**: `users.password_hash` chứa PBKDF2, và so sánh bằng
# thời gian hằng.
#
# Nói đúng phạm vi (Thành bắt được chỗ nói quá ở review PR #89): credential seed **vẫn
# nằm trong mã nguồn** — xem `DEMO_USERS` bên dưới. Đây không phải "mật khẩu đã rời
# source code".

_PBKDF2_ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Trả chuỗi `pbkdf2_sha256$<vòng>$<salt hex>$<hash hex>`, tự sinh salt."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    iterations = get_settings().auth_pbkdf2_iterations
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PBKDF2_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """So sánh **thời gian hằng**. Chuỗi hỏng thì trả `False`, không raise.

    Số vòng đọc từ **chuỗi đã lưu**, không từ cấu hình hiện tại: đổi cấu hình không
    được làm mọi mật khẩu cũ thành sai.
    """
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
        if algorithm != _PBKDF2_ALGORITHM:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(candidate.hex(), digest_hex)


#: Hai tài khoản demo của `docs/api_spec.md` — giữ nguyên id, email và mật khẩu để
#: không đổi trải nghiệm demo; chỉ **cách lưu trong DB** là đổi.
#:
#: Nói cho rõ, vì mô tả PR #89 bản đầu đã nói quá và Thành bắt được: credential seed
#: **vẫn nằm trong mã nguồn**, ngay dưới đây. Thứ đổi là `users.password_hash` chứa
#: PBKDF2 chứ không chứa chuỗi thô, và `verify_password` so bằng thời gian hằng.
#: Chấp nhận được cho demo local một máy; nếu phạm vi mở sang production thì hai dòng
#: dưới phải chuyển sang env/secret hoặc một script provisioning, không nằm ở đây.
DEMO_USERS: tuple[tuple[str, str, str, str, str], ...] = (
    ("usr_driver_01", "driver.demo@example.com", "DemoDriver123!", "driver", "Demo Driver"),
    ("usr_engineer_01", "engineer.demo@example.com", "DemoEngineer123!", "engineer", "Demo Engineer"),
)


def seed_demo_users(connection: sqlite3.Connection) -> None:
    """Chèn hai user demo nếu chưa có. Idempotent, chạy mỗi lần khởi động.

    `INSERT OR IGNORE` chứ không phải upsert: chạy lại **không** được sinh salt mới
    cho một user đã tồn tại, nếu không mỗi lần khởi động lại là một lần ghi đĩa vô ích
    và mọi bản ghi lịch sử của hash cũ thành vô nghĩa.
    """
    for user_id, email, password, role, display_name in DEMO_USERS:
        connection.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, role, display_name) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, hash_password(password), role, display_name),
        )
    connection.commit()


def invalidate_orphaned_pending_approvals(connection: sqlite3.Connection) -> int:
    """Chốt mọi approval còn `pending` lúc khởi động sang `invalidated`. Trả số hàng.

    **Đây là chỗ thừa nhận giới hạn của đợt persistence này.** Bản ghi approval sống
    qua restart, nhưng *lượt* thì không: `session_state.get_graph()` dựng graph với
    `InMemorySaver`, nên checkpoint chứa `interrupt()` của lượt S2 chết theo tiến
    trình. Để nguyên `pending` thì tài xế bấm Đồng ý vào một thread không còn interrupt
    nào — lệnh không chạy và lượt không bao giờ tới sự kiện terminal.

    Fail-closed đúng tinh thần `safety_and_hitl.md`: bắt hỏi lại còn hơn treo im lặng.
    Muốn lượt cũng sống qua restart thì phải thay checkpointer, nằm ngoài issue #46.
    """
    cursor = connection.execute(
        "UPDATE approvals SET status = 'invalidated', decided_at = datetime('now') WHERE status = 'pending'"
    )
    connection.commit()
    return cursor.rowcount


def expire_and_purge_sessions(
    connection: sqlite3.Connection,
    *,
    now: datetime,
    ttl_hours: float,
    retention_days: float,
) -> tuple[int, int]:
    """Chốt phiên quá hạn sang `expired`, rồi xoá hẳn hàng quá mốc lưu trữ.

    Trả `(số phiên vừa hết hạn, số hàng vừa xoá)`.

    Hai bước, hai mốc, cố ý **không** gộp làm một. Bước một chỉ đổi `status` và ghi
    `ended_at`: phiên hết dùng được nhưng vẫn đọc được, nên còn truy được "phiên đó
    kết thúc lúc nào". Bước hai mới xoá, và chỉ xoá thứ đã cũ hơn mốc lưu trữ của
    `data_model.md:43`. Xoá thẳng ở bước một là mất dấu vết audit ngay lúc nó bắt đầu
    có ích.

    Đây là câu trả lời cho điểm 2 trong review PR #89 của Thành: trước đợt này bảng
    `sessions` không có TTL, không end-session, không cleanup — hai cột `status` và
    `ended_at` có trong schema từ đầu mà **chưa ai từng ghi**, nên DB chỉ có thể tăng.
    """
    expired_before = (now - timedelta(hours=ttl_hours)).isoformat()
    purge_before = (now - timedelta(days=retention_days)).isoformat()

    expired = connection.execute(
        "UPDATE sessions SET status = 'expired', ended_at = ? WHERE status = 'active' AND started_at < ?",
        (now.isoformat(), expired_before),
    ).rowcount
    purged = connection.execute("DELETE FROM sessions WHERE started_at < ?", (purge_before,)).rowcount
    connection.commit()
    return expired, purged


# --- kết nối dùng chung toàn tiến trình -----------------------------------

_connection: sqlite3.Connection | None = None
_connection_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """Kết nối domain dùng chung, mở lười theo `settings.database_url`.

    Một kết nối cho cả tiến trình, không phải một cho mỗi store: `sessions`, `users`
    và `approvals` phải nhìn thấy nhau (`:memory:` của hai kết nối khác nhau là hai
    DB khác nhau hoàn toàn).
    """
    global _connection
    with _connection_lock:
        if _connection is None:
            _connection = connect(resolve_db_path(get_settings().database_url))
            ensure_schema(_connection)
            seed_demo_users(_connection)
        return _connection


def close_connection() -> None:
    """Đóng và quên kết nối dùng chung — test giả lập restart cần, production không."""
    global _connection
    with _connection_lock:
        if _connection is not None:
            _connection.close()
            _connection = None

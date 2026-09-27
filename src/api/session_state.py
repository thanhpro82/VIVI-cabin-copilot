"""State sống giữa hai HTTP request: simulator, store approval, và graph đã compile.

Tất cả in-memory và mất khi restart — đánh đổi có chủ đích cho demo PC, ghi trong
spec HITL. Graph phải được **giữ lại** giữa hai request vì `interrupt()` chỉ resume
được trên đúng instance có checkpointer chứa checkpoint đó; dựng graph mới ở request
sau thì checkpoint biến mất và lượt chờ xác nhận không bao giờ tiếp tục được.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.config import get_settings
from src.db import expire_and_purge_sessions, get_connection
from src.services.citations import get_citation_store
from src.services.vehicle_gateway import (
    ChiXemVehicleGateway,
    MotionInjectable,
    VehicleGateway,
    get_gateway_for,
    get_vehicle_gateway,
)
from src.services.vehicle_pool import SucChua, VehiclePool

#: Trần số phiên giữ trong bộ nhớ. `session_id` nằm trong request body nên client
#: tạo bao nhiêu phiên cũng được — không có trần thì server chạy lâu sẽ phình mãi.
#: Đuổi theo LRU: phiên lâu nhất không đụng tới bị bỏ trước.
MAX_SESSIONS = 128

#: Khởi tạo **lười**, không phải ở mức module.
#:
#: Bản trước là `_STORE = ApprovalStore(connection=get_connection())` chạy ngay lúc
#: import, nên một `DATABASE_URL` sai làm hỏng `import src.main` — trước cả khi
#: `lifespan` kịp chạy. Hệ quả (issue #93): khối kiểm tra cấu hình trong `src/main.py`,
#: vốn đặt ở đó *cố ý* để lỗi nổ lúc khởi động thay vì giữa một lượt, trở thành **code
#: chết**; và người dùng nhận traceback import thay vì một câu nói rõ phải sửa gì.
_STORE: ApprovalStore | None = None
_GRAPHS: OrderedDict[str, Any] = OrderedDict()
_LOCKS: OrderedDict[str, asyncio.Lock] = OrderedDict()

#: Xe mà graph của mỗi phiên đang giữ, ghi lại đúng lúc dựng graph.
#:
#: Không đọc ngược ra được từ chính graph: cổng xe nằm sâu trong closure của các node,
#: và `ChiXemVehicleGateway` bọc cổng demo lại nên nhìn từ ngoài hai chế độ giống nhau.
#: Một bảng phụ là cách rẻ nhất để trả lời "graph này đang cầm xe nào".
_GRAPH_XE: dict[str, str | None] = {}
_POOL: VehiclePool | None = None

#: "Chưa đọc" — phân biệt với `None`, vốn là một giá trị **có nghĩa** (phiên chỉ xem).
#: Xem `get_vehicle(..., xe=...)`.
_CHUA_DOC = object()

#: Phiên vừa **mất xe** mà chưa kịp báo cho tài xế. Đọc-rồi-xoá ở
#: `lay_canh_bao_mat_xe()`.
#:
#: Vì sao là một cờ chứ không phát event ngay tại chỗ phát hiện: `get_graph` là hàm
#: **sync**, còn `bus.publish` là async. Biến nó thành async là bắt cả bốn cửa vào
#: (`turns/text`, `turns/voice`, `approvals/{id}/decision`, `agent/process`) cùng đổi —
#: đúng kiểu "bốn chỗ phải cùng nhớ một luật" mà `ChiXemVehicleGateway` sinh ra để
#: tránh. Cờ để `emit_turn_lifecycle` — chỗ **duy nhất** dịch một lượt thành event của
#: phiên — đọc và phát, nên chỉ có một chỗ phải nhớ.
_MAT_XE: set[str] = set()


def get_vehicle_pool() -> VehiclePool | None:
    """Pool xe, hoặc `None` khi **không cấp phát**.

    ## `vehicle_pool_size == 1` cố ý KHÔNG cấp phát

    Với đúng một chiếc xe thì không có gì để phân phối, và bật cấp phát lên chỉ tạo ra
    một hệ quả duy nhất: người thứ hai bị đẩy sang chế độ chỉ xem. Đó **tệ hơn** hành vi
    hôm nay (mọi người dùng chung một xe, va nhau nhưng ai cũng lái được), nên mặc định
    của repo phải giữ nguyên hành vi cũ chứ không âm thầm siết lại.

    Vì vậy `vehicle_pool_size = 1` nghĩa là "như trước khi có pool", và `>= 2` mới bật
    cấp phát. Đây là ngoại lệ có chủ đích, không phải quên: nó giữ cho việc merge nhánh
    này không đổi hành vi của bất kỳ ai, và bật nhiều xe là một lựa chọn tường minh của
    người vận hành.

    Khởi tạo lười, cùng lý do với `_STORE`: đọc cấu hình lúc import làm hỏng
    `import src.main` trước khi khối kiểm tra cấu hình kịp chạy (issue #93).
    """
    global _POOL
    settings = get_settings()
    if settings.vehicle_pool_size <= 1:
        return None
    if _POOL is None:
        _POOL = VehiclePool(settings.vehicle_pool_ids(), lease_ttl_s=settings.vehicle_lease_ttl_s)
    return _POOL


def suc_chua_xe() -> SucChua | None:
    """Sức chứa để hiển thị, hoặc `None` khi **không cấp phát**.

    `None` chứ không phải `SucChua(tong=1, dang_dung=0)`: khi không cấp phát thì không
    có trần nào để nói, và báo `dang_dung = 0` trong lúc có người đang lái là một con số
    sai. Client đọc `None` là "không áp dụng", đúng nghĩa.
    """
    pool = get_vehicle_pool()
    return None if pool is None else pool.suc_chua()


def xe_cua_phien(session_id: str) -> str | None:
    """Xe mà phiên **được phép lái** ngay lúc này, hoặc `None` nếu đang chỉ xem.

    Không cấp phát thì mọi phiên đều lái được chiếc xe duy nhất.
    """
    pool = get_vehicle_pool()
    if pool is None:
        return get_settings().vehicle_id
    return pool.xe_cua(session_id)


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    user_id: str
    vehicle_id: str
    status: str
    started_at: datetime


def get_store() -> ApprovalStore:
    """Kho approval dùng chung, mở kết nối ở lần gọi đầu chứ không ở lúc import."""
    global _STORE
    if _STORE is None:
        _STORE = ApprovalStore(connection=get_connection())
    return _STORE


def session_count() -> int:
    return len(_GRAPHS)


def has_session(session_id: str) -> bool:
    return session_id in _GRAPHS


def _touch(session_id: str) -> None:
    """Đánh dấu phiên vừa được dùng, rồi đuổi phiên cũ nhất nếu quá trần.

    Cũng là chỗ **gia hạn hợp đồng thuê xe**: hàm này đã được gọi ở mọi đường vào, nên
    không cần thêm điểm móc nào khác. Dùng `gia_han()` chứ không phải `thue()` — một
    phiên đang chỉ xem không được lặng lẽ chiếm xe giữa chừng chỉ vì có người khác
    vừa rời đi.
    """
    pool = get_vehicle_pool()
    if pool is not None:
        pool.gia_han(session_id)
    _GRAPHS.move_to_end(session_id)
    if session_id in _LOCKS:
        _LOCKS.move_to_end(session_id)
    # Trần đếm theo `_GRAPHS` chứ không theo `_VEHICLES`: từ ADR-013 chỉ có đúng một
    # chiếc xe cho cả hệ thống, nên không còn gì per-session để đếm ở đó. Graph mới là
    # thứ có vòng đời gắn với phiên.
    while len(_GRAPHS) > MAX_SESSIONS:
        evicted, _ = _GRAPHS.popitem(last=False)
        _LOCKS.pop(evicted, None)
        # Dọn cùng nhịp với `_GRAPHS`, nếu không bảng phụ rò theo đúng số phiên bị đuổi
        # và giữ tên xe của những phiên không còn tồn tại.
        _GRAPH_XE.pop(evicted, None)
        _MAT_XE.discard(evicted)
        # Hàng `sessions` **không** bị xoá theo. Trần này là trần bộ nhớ cho graph,
        # còn phiên vẫn là một phiên có thật của một người có thật: lượt kế tiếp chỉ
        # cần một graph mới rỗng, và cổng sở hữu ở `turns.py` vẫn phải tra ra nó.
        # Xoá hàng đi thì người dùng nhận 403 "phiên không tồn tại" cho chính phiên
        # mình vừa tạo, chỉ vì có 128 người khác chen vào giữa.
        #
        # Còn approval thì mất theo graph: checkpoint chứa `interrupt()` đi rồi thì
        # không resume được nữa, giữ lại chỉ tổ chiếm chỗ trong trần của store.
        get_store().forget_session(evicted)
        # Cùng lý do: id citation trong `assistant.response` của phiên đã mất thì
        # không ai gọi tới được nữa.
        get_citation_store().forget_session(evicted)


def get_vehicle(session_id: str, speed_kph: float | None = None, *, xe: Any = _CHUA_DOC) -> VehicleGateway:
    """Cổng xe. **Một chiếc xe cho cả hệ thống**, không phải một chiếc mỗi phiên.

    Đây là đảo ngược có chủ đích so với bản trước. `GET /api/v1/vehicle/state` không
    có tham số session nên nó *không thể* trả state theo phiên; giữ mỗi phiên một
    simulator nghĩa là agent đổi state ở một chỗ còn màn hình đọc ở chỗ khác — đúng
    bug mà ADR-013 và `VehicleGateway` sinh ra để đóng lại.

    `session_id` giữ trong chữ ký vì nó vẫn là ranh giới của graph/khoá/approval, và
    để call site không phải đổi hết cùng lúc.

    `xe` cho phép chỗ gọi **truyền vào giá trị đã đọc sẵn** thay vì để hàm này đọc lại.
    Chỉ `get_graph` dùng, và lý do ở docstring của nó: `xe_cua_phien()` phụ thuộc đồng
    hồ, nên đọc hai lần quanh một `build_graph(...)` là hai câu trả lời khác nhau được.
    Sentinel `_CHUA_DOC` chứ không phải mặc định `None`, vì `None` ở đây là một giá trị
    có nghĩa ("phiên đang chỉ xem") chứ không phải "không truyền".
    """
    if xe is _CHUA_DOC:
        xe = xe_cua_phien(session_id)
    # Không có hợp đồng = chế độ chỉ xem: bọc cổng xe demo lại. Phiên vẫn ĐỌC được trạng
    # thái và thấy một màn hình sống, nhưng mọi `execute()` bị từ chối ngay tại cổng —
    # không có đường nào đi vòng, kể cả resume sau khi duyệt HITL hay kênh harness.
    gateway = ChiXemVehicleGateway(get_vehicle_gateway()) if xe is None else get_gateway_for(xe)
    if speed_kph is not None:
        # Chỉ bản in-process đặt được tốc độ. Dưới MQTT thì `motion` nằm trong
        # `READ_ONLY_DOMAINS` và `mqtt_spec.md:337-349` cấm backend publish `state/*`,
        # nên không có topic lệnh nào cho nó. Tuyệt đối không shadow-publish để lách.
        if not isinstance(gateway, MotionInjectable):
            raise RuntimeError("Cổng xe hiện tại không đặt được tốc độ (chỉ bản in-process làm được)")
        gateway.set_motion(speed_kph, "P" if speed_kph == 0 else "D")
    return gateway


def create_session(user_id: str, vehicle_id: str) -> SessionRecord:
    """Tạo session mới do `user_id` sở hữu — chỉ được gọi từ `POST /sessions`.

    Khác với `get_vehicle`/`get_graph` (tự sinh state ngầm khi được gọi lần đầu),
    đây là điểm tạo session **chính chủ** duy nhất: server sinh `session_id`, ghi
    kèm `user_id` để `turns.py` kiểm ownership trước khi chạy một lượt.
    """
    session_id = f"ses_{uuid.uuid4().hex[:20]}"
    # Server tự chọn xe; `vehicle_id` client gửi lên chỉ còn là gợi ý. Hết pool thì phiên
    # VẪN được tạo — một phiên không phải một chiếc xe — và nó vào chế độ chỉ xem.
    pool = get_vehicle_pool()
    if pool is not None:
        vehicle_id = pool.thue(session_id) or vehicle_id
    record = SessionRecord(
        session_id=session_id,
        user_id=user_id,
        vehicle_id=vehicle_id,
        status="active",
        started_at=datetime.now(UTC),
    )
    connection = get_connection()
    connection.execute(
        "INSERT INTO sessions (id, user_id, vehicle_id, status, started_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_id, vehicle_id, record.status, record.started_at.isoformat()),
    )
    connection.commit()
    # Dọn ngay tại chỗ tạo, không chỉ lúc khởi động: một backend chạy liên tục nhiều
    # ngày thì đợt quét lúc khởi động không bao giờ chạy lần thứ hai, và bảng chỉ có
    # thể phình. Quét toàn bảng mỗi lần tạo phiên là chấp nhận được ở quy mô demo —
    # bảng nhỏ, và tạo phiên là thao tác hiếm so với chạy lượt.
    settings = get_settings()
    expire_and_purge_sessions(
        connection,
        now=record.started_at,
        ttl_hours=settings.session_ttl_hours,
        retention_days=settings.session_retention_days,
    )
    # Chạm trước cho vehicle/graph để lượt đầu tiên không trả giá first-touch
    # khác với các lượt sau.
    get_vehicle(session_id)
    get_graph(session_id)
    return record


def get_session_record(session_id: str) -> SessionRecord | None:
    """Phiên **còn dùng được**, hoặc `None`.

    Hết hạn phát hiện tại **thời điểm đọc** rồi CAS `active → expired`, đúng kỷ luật
    `ApprovalStore` đã dùng: không cần worker nền, và không có cửa sổ nào mà một phiên
    quá hạn vẫn chạy được chỉ vì đợt quét lúc khởi động chưa tới lượt.

    Trả `None` cho phiên hết hạn là **cố ý**, và nó chính là câu trả lời cho "API trả
    gì cho session đã hết hạn" trong review PR #89: cả bốn call site (`turns.py`,
    `approvals.py`, `citation_routes.py`, `ws.py`) đã dịch `None` thành cùng một
    `403 FORBIDDEN` *"session không tồn tại hoặc không thuộc về bạn"*. Không thêm mã
    lỗi riêng cho "hết hạn" — hai route trên cố ý gộp "không tồn tại" với "không phải
    của bạn" để không rò enumeration, và một mã riêng sẽ phá đúng tính chất đó.
    """
    connection = get_connection()
    row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    if row["status"] != "active":
        return None
    now = datetime.now(UTC)
    if now - datetime.fromisoformat(row["started_at"]) >= timedelta(hours=get_settings().session_ttl_hours):
        connection.execute(
            "UPDATE sessions SET status = 'expired', ended_at = ? WHERE id = ? AND status = 'active'",
            (now.isoformat(), session_id),
        )
        connection.commit()
        return None
    return SessionRecord(
        session_id=row["id"],
        user_id=row["user_id"],
        vehicle_id=row["vehicle_id"],
        status=row["status"],
        started_at=datetime.fromisoformat(row["started_at"]),
    )


def get_graph(session_id: str) -> Any:
    """Một graph mỗi session, giữ nguyên qua các request để resume được interrupt.

    ## Dựng lại khi phiên đã đổi xe

    Cổng xe được chốt vào graph ở **lần dựng đầu** (xem chú thích ở `get_vehicle(...)`
    bên dưới), còn graph thì sống theo phiên. Chú thích ấy lập luận rằng chốt cổng là
    chấp nhận được vì *"quyền lái không đổi giữa chừng một cuộc hội thoại"* — đúng cho
    một chiều: phiên bắt đầu ở chế độ chỉ-xem thì giữ nguyên chế độ đó. Bất tiện, vô hại.

    Chiều ngược lại **không** vô hại, và đó là lỗ này: phiên bắt đầu *có* xe vẫn giữ
    nguyên cổng lái **sau khi mất xe**. `_touch()` chỉ `gia_han()`, cố ý không cấp mới,
    nên lease hết hạn (mặc định 180 s) là xe quay về pool và được cấp cho người khác —
    trong khi graph cũ vẫn cầm đúng cổng của chiếc xe đó.

    Đo được qua đường HTTP thật (`POST /sessions` → `POST /turns/text`)::

        A được cấp xe-01, "bật điều hòa"   -> 27,0 °C
        [lease của A hết hạn]
        B được cấp xe-01
        A "đặt điều hòa 30 độ"             -> completed   <-- A đã mất xe mà vẫn lái
        xe-01 (xe của B)                   -> 30,0 °C

    Cả hai bên **không có dấu hiệu gì**: A đọc `GET /vehicle/state` vẫn thấy đúng chiếc
    xe ấy, còn B thấy xe mình tự đổi trạng thái.

    Nên so xe **hiện tại** của phiên với xe mà graph đang giữ; lệch thì bỏ graph đi dựng
    lại. So bằng `xe_cua_phien(...)` chứ không bằng `pool.thue(...)`: hàm này chỉ đọc, và
    một phiên đang chỉ-xem không được lặng lẽ chiếm xe chỉ vì vừa gọi `get_graph`.

    **Với `vehicle_pool_size <= 1` (mặc định repo) không có gì đổi**: `xe_cua_phien` trả
    đúng `settings.vehicle_id` hằng số ở mọi lượt, nên hai vế luôn bằng nhau và nhánh
    dựng lại không bao giờ chạy. Lỗ này chỉ nổ khi pool >= 2.

    ## Dựng lại làm chết interrupt S2 đang chờ, và đó là hành vi ĐÚNG

    Graph mới mang `InMemorySaver` mới, nên checkpoint giữ `interrupt()` của một lượt
    đang chờ duyệt biến mất cùng graph cũ. Ấy là fail-closed đúng kỷ luật HITL: mất xe
    thì phê duyệt đang treo phải chết theo, không được duyệt một kế hoạch nhắm vào chiếc
    xe giờ đã thuộc về người khác. Tài xế bấm Duyệt sau đó nhận `approval_not_found` —
    cùng một câu trả lời với approval hết hạn, đường đã có sẵn.

    ## `xe_cua_phien()` được đọc ĐÚNG MỘT LẦN, và đó không phải chuyện gọn gàng

    Hàm này là **sync**, không có `await` nào giữa chỗ so và chỗ ghi, nên không có
    interleaving asyncio để mà khoá — `vehicle_pool.py` đã chọn không khoá vì cả hệ giả
    định một tiến trình một event loop. Vấn đề không phải **đồng thời** mà là **đồng hồ**:
    `xe_cua()` và `gia_han()` đều gọi `_quet_het_han()`, tức hết hạn được phát hiện *lúc
    đọc*, nên hai lần đọc cách nhau một `build_graph(...)` (vài ms, và dưới `slm_enabled`
    còn dựng thêm bốn client Qwen) có thể trả hai câu trả lời khác nhau.

    Hậu quả của việc đọc lại **không** thoáng qua. Nếu lease hết hạn đúng trong khe ấy:
    graph nhận cổng **thật** của `xe-01` (đọc lần một), còn `_GRAPH_XE` ghi `None` (đọc
    lần hai). Từ lượt sau `xe_cua_phien()` cũng trả `None`, hai vế **bằng nhau**, nhánh
    dựng lại ở ngay trên **không bao giờ chạy** — và phiên lái `xe-01` vĩnh viễn, đúng
    cái bug hàm này sinh ra để diệt, lần này vô hình với chính guard của nó. `_touch()`
    ngay dưới cũng không cứu được: `gia_han()` trên một hợp đồng đã bị quét trả `None`.

    Nên đọc một lần vào `xe_hien_tai` và dùng chung cho cả ba chỗ (so, dựng cổng, ghi).
    `test_doc_xe_mot_lan_du_lease_het_han_giua_luc_dung_graph` khoá điều này bằng đồng
    hồ giả, không phải bằng `sleep`.
    """
    xe_hien_tai = xe_cua_phien(session_id)
    graph = _GRAPHS.get(session_id)
    if graph is not None and _GRAPH_XE.get(session_id) != xe_hien_tai:
        # Chỉ **mất** xe mới cần báo, không phải mọi lần lệch. Phiên chỉ-xem vừa được
        # cấp xe cũng lệch, nhưng đó là tin vui và FE đã biết qua `can_drive` lúc tạo
        # phiên; báo "bạn mất quyền lái" ở đúng lúc vừa có quyền là nói sai chuyện.
        if _GRAPH_XE.get(session_id) is not None and xe_hien_tai is None:
            _MAT_XE.add(session_id)
        _GRAPHS.pop(session_id, None)
        _GRAPH_XE.pop(session_id, None)
        # KHÔNG bỏ `_LOCKS[session_id]`: khoá thuộc về phiên chứ không thuộc về xe, và
        # bỏ nó giữa chừng nghĩa là hai `ainvoke` của cùng phiên có thể chạy song song —
        # đúng thứ `get_session_lock` sinh ra để chặn.
        graph = None
    if graph is None:
        settings = get_settings()
        planner = None
        classifier = None
        chitchat = None
        lead_in = None
        if settings.slm_enabled:
            # Import tại chỗ: đường mặc định (slm off) không trả thêm chi phí import.
            from src.agents.slm import QwenChitchat, QwenClassifier, QwenLeadIn, QwenPlanner  # noqa: F401

            planner = QwenPlanner(settings.slm_endpoint, settings.slm_model_id, settings.slm_timeout_s)
            # Cùng cờ, vai thứ ba (SP-1): classifier phân loại câu lạ TRƯỚC khi
            # mặc-định-về-sổ-tay. Hỏng thì node rơi về manual — hành vi ADR-011 cũ.
            classifier = QwenClassifier(settings.slm_endpoint, settings.slm_model_id, settings.slm_classify_timeout_s)
            # Vai thứ tư (SP-2): sinh câu xã giao cho lớp chitchat; cổng bốn lớp ở node.
            chitchat = QwenChitchat(settings.slm_endpoint, settings.slm_model_id, settings.slm_chitchat_timeout_s)
            # Cùng một cờ, hai vai khác nhau: planner đề xuất lệnh (sai thì cổng an
            # toàn chặn), còn `lead_in` chỉ viết câu khung cho nhánh sổ tay (không
            # mang dữ kiện, hỏng thì rơi về chuỗi cố định).
            # `cau_dan_dung_slm` mac dinh False: mau ghep tu cau hoi vua nhanh hon
            # (0 ms so voi 2316 ms tren CPU) vua khong bia duoc. Xem `src/config.py`.
            if settings.cau_dan_dung_slm:
                lead_in = QwenLeadIn(settings.slm_endpoint, settings.slm_model_id, settings.slm_timeout_s)
        graph = build_graph(
            # Cổng CỦA PHIÊN, không phải cổng toàn cục. Dùng cổng toàn cục ở đây là mở
            # lại đúng cái lỗ mà `ChiXemVehicleGateway` vừa bịt: `/turns/*` đi qua graph
            # chứ không gọi `get_vehicle()` trực tiếp, nên một phiên chỉ-xem sẽ lái được
            # xe demo qua đường này.
            #
            # Cổng chốt vào graph ở **lần dựng đầu**, mà graph sống theo phiên, nên một
            # phiên bắt đầu ở chế độ chỉ-xem giữ nguyên chế độ đó tới khi graph bị đuổi
            # khỏi `_GRAPHS`. Chấp nhận được và còn dễ hiểu hơn: quyền lái không đổi
            # giữa chừng một cuộc hội thoại.
            get_vehicle(session_id, xe=xe_hien_tai),
            planner=planner,
            classifier=classifier,
            chitchat=chitchat,
            lead_in=lead_in,
            approvals=get_store(),
            hitl_timeout_seconds=settings.hitl_timeout_seconds,
            checkpointer=InMemorySaver(),
        )
        _GRAPHS[session_id] = graph
        # Ghi ngay cạnh chỗ dựng, không tách ra hàm khác: hai dòng này phải luôn đi cùng
        # nhau, và tách ra là mở đường cho một nhánh dựng graph mà quên ghi xe — lúc ấy
        # `_GRAPH_XE.get()` trả `None`, lệch với mọi xe thật, và graph bị dựng lại ở MỌI
        # lượt (mất checkpoint, mất luôn khả năng resume interrupt S2).
        # `xe_hien_tai`, KHÔNG phải `xe_cua_phien(session_id)` lần nữa — xem mục
        # "đọc đúng một lần" ở docstring. Đọc lại ở đây là mở lại lỗ mà hàm này vá.
        _GRAPH_XE[session_id] = xe_hien_tai
    _touch(session_id)
    return graph


def lay_canh_bao_mat_xe(session_id: str) -> bool:
    """`True` **đúng một lần** cho mỗi lần phiên mất xe. Đọc là xoá.

    Đọc-rồi-xoá chứ không phải đọc thuần: cảnh báo này là một **sự kiện**, không phải
    một trạng thái. Trạng thái "đang chỉ xem" đã có `xe_cua_phien(...) is None` trả lời,
    và nó đúng ở mọi lượt sau đó. Nếu hàm này cũng trả `True` mãi thì tài xế nhận cùng
    một câu báo mất xe ở **mọi lượt** cho tới hết phiên — phiền, và làm mờ đúng cái
    khoảnh khắc cần nhìn thấy.

    Không phát event tại đây: xem chú thích của `_MAT_XE`.
    """
    if session_id not in _MAT_XE:
        return False
    _MAT_XE.discard(session_id)
    return True


def get_session_lock(session_id: str) -> asyncio.Lock:
    """Khoá tuần tự hoá `graph.ainvoke(...)` của một session.

    Mọi lượt của một session dùng chung một thread checkpointer (`thread_config`), nên hai
    `ainvoke` chạy song song trên cùng session sẽ bỏ rơi interrupt S2 đang chờ và lượt đó
    không bao giờ tới được terminal event. Cả `turns.py` (lượt voice mới) và `approvals.py`
    (resume sau quyết định) đều phải dùng đúng khoá này.
    """
    lock = _LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[session_id] = lock
    _LOCKS.move_to_end(session_id)
    return lock


def thread_config(session_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": session_id}}


def reset() -> None:
    """Chỉ dùng trong test — dọn state module-level giữa các case."""
    global _POOL
    _POOL = None
    _GRAPHS.clear()
    _LOCKS.clear()
    _GRAPH_XE.clear()
    _MAT_XE.clear()
    connection = get_connection()
    connection.execute("DELETE FROM sessions")
    connection.commit()
    get_store().reset()

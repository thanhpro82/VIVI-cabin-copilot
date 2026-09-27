"""Thực thi Routine: admission, safety/HITL, tuần tự fail-fast (issue #286).

Outcome #275 của epic Routines MVP (#270). Nguồn sản phẩm:
`docs/routines_product_spec.md` §Chạy.

## Nguyên tắc chi phối cả file

> **Routine không phải một đường tắt vào executor.**

Mọi bước đi qua đúng những cổng mà một câu lệnh nói ra đi qua: `policy.materialize_action_plan`
gán `safety_level` (nơi **duy nhất** được phép, bất biến ADR-006), `ApprovalStore` giữ
HITL, `VehicleGateway.execute` publish MQTT. Module này chỉ **điều phối thứ tự** và giữ
sổ sách. Nếu một ngày nó tự gán safety hay tự gọi MQTT thì bất biến của hệ đã vỡ ở đây
chứ không ở đâu khác.

## Vì sao mỗi bước là một plan riêng, không phải một plan bốn bước

`routine_thanh_candidate` dựng được plan nhiều bước, và đường lượt-nói dùng đúng thế. Ở
đây thì không, vì §Chạy chốt: *"Routine có hai bước S2 buộc phải xin phê duyệt tuần tự,
không gộp thành một thẻ"* — hệ quả của partial unique index một-pending-mỗi-session, chứ
không phải một lựa chọn sản phẩm.

Một plan bốn bước có hai S2 sẽ được `materialize_action_plan` gộp thành **một** thẻ phê
duyệt cho cả bốn. Tài xế nghe một câu hỏi rồi bốn việc xảy ra — trong đó có việc họ chưa
kịp hiểu là mình vừa đồng ý. Từng bước một thì mỗi thẻ nêu đúng một việc.

## Vì sao chụp lại các bước lúc admit

`steps_json` là bản chụp tại thời điểm admit, không phải con trỏ vào `routines`. Hai
chiều đều cần:

- **Done when của #286**: *"không replay authorization/plan cũ"* — mỗi run dựng plan mới
  từ bản chụp mới, không dùng lại `plan_id`/approval của lần trước.
- Chiều ngược lại: người dùng sửa Routine giữa lúc nó đang chạy thì lần chạy này vẫn là
  lần chạy của phiên bản họ đã đồng ý, không phải nửa bản cũ ghép nửa bản mới.

## Fail-closed ở đâu, và vì sao ở đó

| Ca | Xử lý |
|---|---|
| Routine bị tắt, hoặc thiếu địa điểm | từ chối **trước khi** tạo execution — zero side effect |
| Đọc trạng thái xe không được | `failed/vehicle_state_unavailable`, bước còn lại `skipped` |
| Bước hoá S3 lúc chạy | `blocked` **trước HITL**, không hỏi tài xế (§Chạy) |
| Bước S2 | dừng ở `waiting_approval`, không có lệnh nào đi tiếp |
| Approval bị từ chối | `user_canceled`, zero side effect cho bước ấy |
| Approval hết hạn / mất hiệu lực | `failed/approval_not_approved` |
| Một bước lỗi | `failed`, mọi bước sau `skipped` |

Trạng thái xe đọc lại **trước mỗi bước**, không phải một lần lúc admit: giữa hai bước
tài xế có thể đã cho xe chạy, và một bước S2 lúc đứng yên là S3 lúc đang lăn bánh.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.agents.approval import ApprovalAlreadyPending, ApprovalRecord, approval_id_for
from src.agents.contracts import ActionPlan, CandidateActionPlan
from src.agents.nodes.approval import describe_plan_for_approval
from src.agents.policy import materialize_action_plan, plan_digest
from src.agents.routines import RoutineDichError, routine_thanh_candidate
from src.db import get_connection
from src.services.routines_store import RoutineKhongTonTaiError, get_routine
from src.services.user_places import resolve as resolve_place
from src.services.vehicle_gateway import snapshot_dict

logger = logging.getLogger(__name__)

#: Trạng thái execution còn sống — hai trạng thái này là thứ partial unique index của
#: `routine_executions` khoá. Danh sách phải khớp câu SQL trong `src/db.py`.
TRANG_THAI_CON_SONG: tuple[str, ...] = ("running", "waiting_approval")

#: Trạng thái cuối. Đúng **một** cái cho mỗi lần chạy (`#290` Done when), kể cả khi hủy.
TRANG_THAI_CUOI: tuple[str, ...] = ("completed", "failed", "blocked", "user_canceled")


class RoutineDangChayError(Exception):
    """Routine đang có một lần chạy còn sống nên không xoá được (acceptance criteria #272)."""

    def __init__(self, execution_id: str) -> None:
        super().__init__(f"Routine đang chạy ({execution_id})")
        self.execution_id = execution_id


class RoutineKhongChayDuocError(Exception):
    """Từ chối **trước khi** tạo execution — zero side effect.

    Có `ma` riêng vì cùng một lời từ chối phải nói khác nhau ở hai chỗ: câu đọc cho tài
    xế nghe, và mã cho client rẽ nhánh. Cùng khuôn `RoutineDichError`.
    """

    def __init__(self, ma: str, thong_diep: str, *, thieu_dia_diem: tuple[str, ...] = ()) -> None:
        super().__init__(thong_diep)
        self.ma = ma
        #: Chỉ khác rỗng khi `ma == "chua_dat_dia_diem"` — nhãn địa điểm (`"home"`/
        #: `"office"`) còn thiếu, để #385 biết đưa tài xế sang ĐÚNG hàng nào trong màn
        #: setup thay vì mở cả panel và để tài xế tự đoán. `thong_diep` đã gộp việc này
        #: vào câu tiếng Việt ("Nhà"/"Cơ quan") rồi, nhưng đó là câu để ĐỌC LÊN — cùng lý
        #: do `ma` tách khỏi `thong_diep`, một client không nên rẽ nhánh bằng cách so
        #: khớp chữ "Nhà" trong một câu có thể đổi bất cứ lúc nào.
        self.thieu_dia_diem = thieu_dia_diem


@dataclass(frozen=True)
class KetQuaBuoc:
    """Một bước trong sổ sách của lần chạy.

    `description` lưu sẵn thay vì dựng lại lúc đọc: nó là thứ đã **nói ra** cho tài xế,
    và dựng lại từ args sau khi bảng mô tả đổi sẽ cho một câu khác với câu họ đã nghe.
    """

    index: int
    action: str
    status: str
    description: str
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "status": self.status,
            "description": self.description,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class RoutineExecution:
    id: str
    routine_id: str
    user_id: str
    session_id: str
    vehicle_id: str
    routine_version: int
    status: str
    current_index: int
    approval_id: str | None
    steps: tuple[dict[str, Any], ...]
    results: tuple[KetQuaBuoc, ...]
    terminal_reason: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str

    @property
    def da_ket_thuc(self) -> bool:
        return self.status in TRANG_THAI_CUOI


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dung(row: sqlite3.Row) -> RoutineExecution:
    return RoutineExecution(
        id=row["id"],
        routine_id=row["routine_id"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        vehicle_id=row["vehicle_id"],
        routine_version=int(row["routine_version"]),
        status=row["status"],
        current_index=int(row["current_index"]),
        approval_id=row["approval_id"],
        steps=tuple(json.loads(row["steps_json"])),
        results=tuple(KetQuaBuoc(**item) for item in json.loads(row["results_json"])),
        terminal_reason=row["terminal_reason"],
        cancel_requested=bool(row["cancel_requested"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _mo_ta(step: dict[str, Any], plan: ActionPlan | None) -> str:
    """Câu mô tả một bước. Dùng lại `describe_step` của tầng compose khi đã có plan."""
    if plan is not None and plan.steps:
        from src.agents.nodes.compose import describe_step

        return describe_step(plan.steps[0].tool, plan.steps[0].args)
    return str(step.get("action", "?"))


def _cau_tong_ket_bang_giong(status: str, results: tuple[KetQuaBuoc, ...]) -> str:
    """Câu tổng kết đọc to khi Routine kết thúc (issue #396).

    Tái dùng thẳng `KetQuaBuoc.description` — đã là câu tiếng Việt dựng sẵn lúc
    chạy (`_mo_ta`), không dựng lại. Không nêu tên Routine: `RoutineExecution`
    không giữ field đó, tra lại DB chỉ cho một câu nói mà không đáng thêm một
    lượt đọc — để lại cho lần sửa sau nếu cần.
    """
    xong = [r.description for r in results if r.status == "completed"]
    if status == "completed":
        return "Đã hoàn tất: " + " rồi ".join(xong) if xong else "Đã hoàn tất chuỗi lệnh."
    if xong:
        return "Chuỗi lệnh dừng lại: " + " rồi ".join(xong)
    return "Chuỗi lệnh không thực hiện được bước nào."


async def _am_thanh_ket_qua(execution_id: str, status: str, results: tuple[KetQuaBuoc, ...]) -> tuple[str | None, str | None]:
    """Tổng hợp giọng nói cho `routine.finished`. Fail-open: lỗi TTS trả `(None, None)`,
    không bao giờ raise — `synthesize_speech` (`ivi_events.py`) đã tự lo phần đó, ở đây
    chỉ gọi và mã hoá base64.
    """
    from src.services.ivi_events import synthesize_speech

    text = _cau_tong_ket_bang_giong(status, results)
    wav = await synthesize_speech(execution_id, f"tr_{execution_id}", text)
    if wav is None:
        return None, None
    return base64.b64encode(wav).decode("ascii"), "audio/wav"


def _luu(
    conn: sqlite3.Connection,
    execution_id: str,
    *,
    status: str,
    current_index: int,
    approval_id: str | None,
    results: list[KetQuaBuoc],
    terminal_reason: str | None,
) -> None:
    conn.execute(
        """
        UPDATE routine_executions
           SET status = ?, current_index = ?, approval_id = ?, results_json = ?,
               terminal_reason = ?, updated_at = ?
         WHERE id = ?
        """,
        (
            status,
            current_index,
            approval_id,
            json.dumps([r.as_dict() for r in results], ensure_ascii=False),
            terminal_reason,
            _now(),
            execution_id,
        ),
    )
    conn.commit()


async def _phat(execution: RoutineExecution, event_type: str, payload: dict[str, Any]) -> None:
    """Phát một sự kiện tiến độ lên `/ws/ivi`. **Fail-open** (issue #290).

    Một lỗi ở tầng thông báo không được làm hỏng một chuỗi lệnh đang chạy trên xe: bản
    ghi trong `routine_executions` mới là nguồn sự thật, và client luôn hỏi lại được
    `GET /routine-executions/{id}`. Cùng kỷ luật với TTS ở `emit_turn_lifecycle`.

    `turn_id` mang chính `execution_id`: trên stream tài xế, một lần chạy Routine đóng
    vai một "lượt" — nó là thứ client nhóm các sự kiện theo, và ADR-014 đánh
    `sequence`/`event_id` theo **phiên** nên thứ tự và replay đã đúng sẵn.
    """
    from src.services.ivi_events import get_event_bus

    try:
        await get_event_bus().publish(
            execution.session_id,
            event_type,
            execution.id,
            f"tr_{execution.id}",
            payload,
        )
    except Exception:  # noqa: BLE001 - tầng thông báo không được kéo đổ tầng thực thi
        logger.exception("Phát %s cho execution %s thất bại", event_type, execution.id)


def _tom_tat_buoc(execution: RoutineExecution) -> list[dict[str, Any]]:
    return [
        {"index": i, "action": str(step.get("action")), "description": str(step.get("action"))}
        for i, step in enumerate(execution.steps)
    ]


def _dia_diem_cua(user_id: str, conn: sqlite3.Connection) -> dict[str, str]:
    """Ánh xạ nhãn → `destination_id` **đã kiểm hợp lệ** (#283)."""
    da = {}
    for nhan in ("home", "office"):
        dich = resolve_place(user_id, nhan, connection=conn)
        if dich:
            da[nhan] = dich
    return da


def _nhan_can_thiet(steps: tuple[dict[str, Any], ...]) -> set[str]:
    return {str(b.get("destination")) for b in steps if b.get("action") == "navigation"}


async def bat_dau(
    *,
    user_id: str,
    session_id: str,
    vehicle_id: str,
    routine_id: str,
    connection: sqlite3.Connection | None = None,
) -> RoutineExecution:
    """Admit rồi chạy tới điểm dừng đầu tiên (xong, lỗi, chặn, hoặc chờ phê duyệt).

    Ba cổng admission chạy **trước** khi có bất kỳ hàng nào trong `routine_executions`,
    nên một lần chạy bị từ chối không để lại execution ma nào để ai đó phải dọn:

    1. Routine phải thuộc user này (uỷ cho `routines_store.get_routine`);
    2. Routine phải đang bật — §Cô lập: *"Routine bị tắt không thể được chạy"*;
    3. mọi nhãn địa điểm nó cần phải đã gán và còn hợp lệ (#283).
    """
    conn = connection or get_connection()
    try:
        routine = get_routine(user_id, routine_id, connection=conn)
    except RoutineKhongTonTaiError as exc:
        raise RoutineKhongChayDuocError("routine_khong_ton_tai", "không tìm thấy chuỗi lệnh") from exc
    if not routine.enabled:
        raise RoutineKhongChayDuocError("routine_da_tat", "Chuỗi lệnh này đang tắt")
    if routine.needs_setup:
        thieu = sorted(_nhan_can_thiet(routine.steps) - set(_dia_diem_cua(user_id, conn)))
        ten = "Nhà" if thieu[:1] == ["home"] else "Cơ quan"
        raise RoutineKhongChayDuocError(
            "chua_dat_dia_diem",
            f"chưa đặt địa điểm {ten} nên chưa chạy được chuỗi lệnh này",
            thieu_dia_diem=tuple(thieu),
        )

    execution_id = f"rex_{secrets.token_hex(8)}"
    now = _now()
    try:
        conn.execute(
            """
            INSERT INTO routine_executions (
                id, routine_id, user_id, session_id, vehicle_id, routine_version,
                status, current_index, approval_id, steps_json, results_json,
                terminal_reason, cancel_requested, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', 0, NULL, ?, '[]', NULL, 0, ?, ?)
            """,
            (
                execution_id,
                routine_id,
                user_id,
                session_id,
                vehicle_id,
                routine.version,
                json.dumps(list(routine.steps), ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        # Partial unique index `routine_executions_one_active_per_session`. Hai request
        # `run` song song trên cùng phiên: một cái thắng, cái kia nhận lỗi này — chứ
        # không phải hai chuỗi lệnh chạy chồng lên nhau trên cùng chiếc xe.
        raise RoutineKhongChayDuocError(
            "dang_chay_routine_khac",
            "đang có một chuỗi lệnh chạy dở trong phiên này",
        ) from exc

    execution = _doc_thang(conn, execution_id)
    await _phat(
        execution,
        "routine.started",
        {
            "execution_id": execution.id,
            "routine_id": execution.routine_id,
            "routine_name": routine.name,
            "routine_version": execution.routine_version,
            "steps": _tom_tat_buoc(execution),
            "started_at": execution.created_at,
        },
    )
    return await _chay_tiep(execution_id, connection=conn)


async def _chay_tiep(execution_id: str, *, connection: sqlite3.Connection | None = None) -> RoutineExecution:
    """Chạy tuần tự từ `current_index` tới điểm dừng tiếp theo.

    Trả execution ở trạng thái mới. Điểm dừng là một trong bốn: hết bước (`completed`),
    một bước lỗi (`failed`), một bước hoá S3 (`blocked`), hoặc một bước cần phê duyệt
    (`waiting_approval`).
    """
    from src.services.vehicle_gateway import get_vehicle_gateway

    conn = connection or get_connection()
    execution = _doc_thang(conn, execution_id)
    if execution.da_ket_thuc:
        # Replay không sinh side effect lần hai (`#286` Done when). Không phải lỗi:
        # một quyết định approval tới sau khi execution đã bị hủy là chuyện thường.
        return execution

    gateway = get_vehicle_gateway()
    results = list(execution.results)
    dia_diem = _dia_diem_cua(execution.user_id, conn)
    index = execution.current_index

    while index < len(execution.steps):
        # **Điểm dừng an toàn**: đọc lại cờ hủy từ DB trước mỗi bước, không tin bản
        # `execution` đã đọc lúc vào hàm. Yêu cầu hủy tới từ một request khác, giữa lúc
        # vòng lặp này đang chạy — nếu đọc từ bản cũ thì nó không bao giờ thấy.
        #
        # Bước đang chạy (nếu có) đã publish lên MQTT và chạy nốt: lệnh đã đi thì không
        # rút lại được, và báo "đã hủy" cho nó là nói dối (§Hủy).
        if _da_yeu_cau_huy(conn, execution.id):
            return await _ket_thuc(
                conn,
                execution,
                results,
                index,
                status="user_canceled",
                reason="user_canceled",
                buoc_status="canceled",
                buoc_error="canceled_before_run",
                mo_ta=str(execution.steps[index].get("action")),
            )
        step = execution.steps[index]

        # Đọc lại trạng thái xe TRƯỚC MỖI BƯỚC, không phải một lần lúc admit: giữa hai
        # bước tài xế có thể đã cho xe chạy, và một bước S2 lúc đứng yên là S3 lúc đang
        # lăn bánh. Đọc một lần rồi dùng lại chính là cách cấp phép cho hành động lẽ ra
        # phải chặn.
        live = await gateway.snapshot()
        if live is None:
            return await _ket_thuc(
                conn,
                execution,
                results,
                index,
                status="failed",
                reason="vehicle_state_unavailable",
                buoc_status="failed",
                buoc_error="vehicle_state_unavailable",
                mo_ta=_mo_ta(step, None),
            )
        snapshot = snapshot_dict(live)

        try:
            candidate: CandidateActionPlan = routine_thanh_candidate([step], dia_diem=dia_diem)
        except RoutineDichError as exc:
            # Bước không dịch được **lúc chạy** dù đã qua validate lúc lưu: địa điểm vừa
            # bị bỏ gán, hoặc dải giá trị của tool vừa đổi. Fail-fast, không đoán.
            return await _ket_thuc(
                conn,
                execution,
                results,
                index,
                status="failed",
                reason=exc.ma,
                buoc_status="failed",
                buoc_error=exc.ma,
                mo_ta=_mo_ta(step, None),
            )

        plan = materialize_action_plan(
            candidate,
            snapshot,
            execution.session_id,
            execution.vehicle_id,
            route_source="routine",
        )
        mo_ta = _mo_ta(step, plan)

        if any(s.safety_level == "S3" for s in plan.steps):
            # §Chạy: bước hoá S3 lúc chạy ⇒ **chặn trước HITL**, không hỏi tài xế. Hỏi
            # một câu mà câu trả lời "đồng ý" cũng không được phép thực hiện là mời
            # người ta tin rằng có cách nói để vượt qua.
            return await _ket_thuc(
                conn,
                execution,
                results,
                index,
                status="blocked",
                reason="blocked_by_vehicle_state",
                buoc_status="blocked",
                buoc_error="blocked_by_vehicle_state",
                mo_ta=mo_ta,
            )

        if plan.requires_approval:
            approval_id = _tao_approval(conn, execution, plan, snapshot, index)
            if approval_id is None:
                return await _ket_thuc(
                    conn,
                    execution,
                    results,
                    index,
                    status="failed",
                    reason="approval_already_pending",
                    buoc_status="failed",
                    buoc_error="approval_already_pending",
                    mo_ta=mo_ta,
                )
            _luu(
                conn,
                execution.id,
                status="waiting_approval",
                current_index=index,
                approval_id=approval_id,
                results=results,
                terminal_reason=None,
            )
            # Cửa sổ hẹp giữa lần kiểm cờ ở đầu vòng lặp và lúc này: yêu cầu hủy có
            # thể đã tới trong lúc `_tao_approval` chạy. Kiểm **sau khi** đã ghi
            # `waiting_approval` — thứ tự ấy là điều kiện để `huy()` (đọc lại DB sau khi
            # bật cờ) không bao giờ thấy một trạng thái cũ hơn thực tế.
            #
            # Bên nào cũng có thể thắng cuộc đua này; CAS ở `_ket_thuc_sau_khi_da_ghi`
            # bảo đảm chỉ một bên ghi terminal.
            if _da_yeu_cau_huy(conn, execution.id):
                from src.api.session_state import get_store

                get_store().decide(approval_id, approve=False)
                return await _ket_thuc(
                    conn,
                    execution,
                    results,
                    index,
                    status="user_canceled",
                    reason="user_canceled",
                    buoc_status="canceled",
                    buoc_error="canceled_before_run",
                    mo_ta=mo_ta,
                )
            cho = _doc_thang(conn, execution.id)
            await _phat(
                cho,
                "routine.step",
                {
                    "execution_id": cho.id,
                    "index": index,
                    "action": str(step.get("action")),
                    "status": "waiting_approval",
                    "description": mo_ta,
                    "error_code": None,
                    "approval_id": approval_id,
                },
            )
            return cho

        ket_qua = await _chay_mot_buoc(gateway, plan, approval_id=None)
        buoc = KetQuaBuoc(
            index=index,
            action=str(step.get("action")),
            status=ket_qua[0],
            description=mo_ta,
            error_code=ket_qua[1],
        )
        results.append(buoc)
        await _phat(execution, "routine.step", {"execution_id": execution.id, **buoc.as_dict()})
        if ket_qua[0] != "completed":
            return await _ket_thuc_sau_khi_da_ghi(conn, execution, results, index + 1, "failed", ket_qua[1])
        index += 1
        _luu(
            conn,
            execution.id,
            status="running",
            current_index=index,
            approval_id=None,
            results=results,
            terminal_reason=None,
        )

    _luu(
        conn,
        execution.id,
        status="completed",
        current_index=index,
        approval_id=None,
        results=results,
        terminal_reason="completed",
    )
    xong = _doc_thang(conn, execution.id)
    audio_base64, mime_type = await _am_thanh_ket_qua(xong.id, xong.status, xong.results)
    await _phat(
        xong,
        "routine.finished",
        {
            "execution_id": xong.id,
            "routine_id": xong.routine_id,
            "status": xong.status,
            "terminal_reason": xong.terminal_reason,
            "results": [r.as_dict() for r in xong.results],
            "completed_at": xong.updated_at,
            "audio_base64": audio_base64,
            "mime_type": mime_type,
        },
    )
    return xong


async def _chay_mot_buoc(gateway: Any, plan: ActionPlan, *, approval_id: str | None) -> tuple[str, str | None]:
    """Thực thi đúng một bước qua cổng xe. Trả `(status, error_code)`.

    Tool không có domain (`open_app`) không đi MQTT — cùng nhánh mà `nodes/execute.py`
    đã có, và cùng lý do: không có actuator nào để publish tới.
    """
    from src.services.tool_registry import get_spec

    step = plan.steps[0]
    if get_spec(step.tool).domain is None:
        return "completed", None
    result = await gateway.execute(
        plan_id=plan.plan_id,
        step_id=step.step_id,
        tool=step.tool,
        args=step.args,
        expected_state_version=plan.vehicle_state_version,
        approval_id=approval_id,
    )
    return ("completed", None) if result.status == "completed" else ("failed", result.error_code)


def _tao_approval(
    conn: sqlite3.Connection,
    execution: RoutineExecution,
    plan: ActionPlan,
    snapshot: dict[str, Any],
    index: int,
) -> str | None:
    """Tạo thẻ phê duyệt cho **một** bước. `None` khi phiên đã có thẻ đang chờ.

    `turn_id` mang chính `execution_id` + số thứ tự bước, để hai bước S2 của cùng một
    Routine không đâm vào ràng buộc single-use của nhau và để log đọc ra được thẻ này
    thuộc lần chạy nào.
    """
    from src.api.session_state import get_store

    store = get_store()
    digest = plan_digest(plan)
    prompt_text, steps_summary = describe_plan_for_approval(plan, snapshot)
    now = store.now()
    turn_id = f"{execution.id}:{index}"
    record = ApprovalRecord(
        approval_id=approval_id_for(execution.session_id, turn_id, digest),
        session_id=execution.session_id,
        turn_id=turn_id,
        plan_id=plan.plan_id,
        plan_digest=digest,
        approved_vehicle_state_version=plan.vehicle_state_version,
        created_at=now,
        expires_at=now + timedelta(seconds=30),
        prompt_text=prompt_text,
        steps_summary=steps_summary,
    )
    try:
        record = store.create(record)
    except ApprovalAlreadyPending:
        return None
    return record.approval_id


async def _ket_thuc(
    conn: sqlite3.Connection,
    execution: RoutineExecution,
    results: list[KetQuaBuoc],
    index: int,
    *,
    status: str,
    reason: str,
    buoc_status: str,
    buoc_error: str | None,
    mo_ta: str,
) -> RoutineExecution:
    """Ghi kết quả cho bước đang dở rồi đóng execution."""
    results.append(
        KetQuaBuoc(
            index=index,
            action=str(execution.steps[index].get("action")),
            status=buoc_status,
            description=mo_ta,
            error_code=buoc_error,
        )
    )
    return await _ket_thuc_sau_khi_da_ghi(conn, execution, results, index + 1, status, reason)


async def _ket_thuc_sau_khi_da_ghi(
    conn: sqlite3.Connection,
    execution: RoutineExecution,
    results: list[KetQuaBuoc],
    tu_index: int,
    status: str,
    reason: str | None,
) -> RoutineExecution:
    """Đánh dấu mọi bước chưa chạy là `skipped` rồi đóng execution.

    Bước chưa chạy phải **có mặt** trong sổ sách với trạng thái rõ ràng, không được biến
    mất — cùng lập luận với issue #83 ở `nodes/execute.py`: hồ sơ là thứ ta dùng để nói
    cái gì đã xảy ra và cái gì không, và một bước biến mất khỏi hồ sơ làm câu trả lời
    "Routine chạy tới đâu" không kiểm chứng được.
    """
    for j in range(tu_index, len(execution.steps)):
        results.append(
            KetQuaBuoc(
                index=j,
                action=str(execution.steps[j].get("action")),
                status="skipped",
                description=str(execution.steps[j].get("action")),
                error_code="skipped_due_to_prior_stop",
            )
        )
    # **CAS, không phải UPDATE thẳng.** Hai đường có thể cùng muốn đóng một execution:
    # vòng lặp `_chay_tiep` thấy cờ hủy, và `huy()` thấy nó đang chờ phê duyệt. Nếu cả
    # hai cùng ghi thì lần chạy ấy phát **hai** `routine.finished` — vi phạm đúng bất
    # biến "một terminal outcome" mà #290 dựng lên, và trên màn hình tài xế là hai thông
    # báo kết thúc cho một việc.
    #
    # `WHERE status IN (...)` để chỉ bên nào thấy execution **còn sống** mới ghi được;
    # bên thua đọc `rowcount == 0` và im lặng trả về bản ghi đã đóng.
    cursor = conn.execute(
        """
        UPDATE routine_executions
           SET status = ?, current_index = ?, approval_id = NULL, results_json = ?,
               terminal_reason = ?, updated_at = ?
         WHERE id = ? AND status IN ('running', 'waiting_approval')
        """,
        (
            status,
            len(execution.steps),
            json.dumps([r.as_dict() for r in results], ensure_ascii=False),
            reason,
            _now(),
            execution.id,
        ),
    )
    conn.commit()
    if cursor.rowcount == 0:
        return _doc_thang(conn, execution.id)
    ket = _doc_thang(conn, execution.id)
    audio_base64, mime_type = await _am_thanh_ket_qua(ket.id, ket.status, ket.results)
    await _phat(
        ket,
        "routine.finished",
        {
            "execution_id": ket.id,
            "routine_id": ket.routine_id,
            "status": ket.status,
            "terminal_reason": ket.terminal_reason,
            "results": [r.as_dict() for r in ket.results],
            "completed_at": ket.updated_at,
            "audio_base64": audio_base64,
            "mime_type": mime_type,
        },
    )
    return ket


def _doc_thang(conn: sqlite3.Connection, execution_id: str) -> RoutineExecution:
    row = conn.execute("SELECT * FROM routine_executions WHERE id = ?", (execution_id,)).fetchone()
    if row is None:
        raise LookupError(execution_id)
    return _dung(row)


def _da_yeu_cau_huy(conn: sqlite3.Connection, execution_id: str) -> bool:
    row = conn.execute("SELECT cancel_requested FROM routine_executions WHERE id = ?", (execution_id,)).fetchone()
    return bool(row and row["cancel_requested"])


async def huy(
    user_id: str, execution_id: str, *, connection: sqlite3.Connection | None = None
) -> RoutineExecution:
    """Yêu cầu dừng một lần chạy. **Idempotent** (issue #297).

    Ba đường, và cả ba cho cùng một kết quả quan sát được:

    1. **đã kết thúc** — trả nguyên bản ghi, không sinh terminal thứ hai, không phát sự
       kiện nào. Hủy hai lần, hoặc hủy một Routine vừa chạy xong, là chuyện thường: tài
       xế bấm Dừng đúng lúc bước cuối hoàn tất;
    2. **đang chờ phê duyệt** — từ chối chính thẻ ấy rồi đóng ngay `user_canceled`. Zero
       side effect cho bước đó (§Hủy: *"đang chờ approval mà hủy ⇒ từ chối approval đó"*);
    3. **đang chạy** — bật cờ và trả về. Vòng lặp đóng execution ở **ranh giới bước tiếp
       theo**; bước đang bay chạy nốt và được báo cáo trung thực.

    Đường 3 cố ý **không** chờ vòng lặp đóng xong: request Dừng phải trả lời ngay để nút
    bấm không treo, và trạng thái cuối đi qua `routine.finished` trên `/ws/ivi`.
    """
    conn = connection or get_connection()
    execution = doc(user_id, execution_id, connection=conn)
    if execution.da_ket_thuc:
        return execution

    conn.execute("UPDATE routine_executions SET cancel_requested = 1, updated_at = ? WHERE id = ?", (_now(), execution_id))
    conn.commit()

    # **Đọc lại sau khi bật cờ, không dùng bản đọc ở trên.** Giữa hai thời điểm ấy, vòng
    # lặp `_chay_tiep` có thể đã tạo thẻ phê duyệt và chuyển sang `waiting_approval`.
    # Rẽ nhánh theo bản cũ (`running`) thì không ai từ chối thẻ ấy và cũng không ai đóng
    # execution: tài xế bấm Dừng, thẻ vẫn treo trên màn hình, và lần chạy kẹt ở
    # `waiting_approval` cho tới khi thẻ hết hạn. Đây là bug mà review PR #369 chỉ ra.
    execution = _doc_thang(conn, execution_id)
    if execution.da_ket_thuc:
        # Vòng lặp đã kịp đóng nó bằng chính cờ vừa bật — không có gì để làm thêm.
        return execution

    if execution.status == "waiting_approval" and execution.approval_id:
        from src.api.session_state import get_store

        # `decide` là nguồn quyết định duy nhất, kể cả khi người gọi là nút Dừng chứ
        # không phải nút Từ chối: một thẻ bị bỏ rơi mà không chốt sẽ nằm `pending` cho
        # tới lúc hết hạn và chặn mọi thẻ sau trong cùng phiên.
        get_store().decide(execution.approval_id, approve=False)
        results = list(execution.results)
        return await _ket_thuc(
            conn,
            execution,
            results,
            execution.current_index,
            status="user_canceled",
            reason="user_canceled",
            buoc_status="canceled",
            buoc_error="canceled_before_run",
            mo_ta=str(execution.steps[execution.current_index].get("action")),
        )

    return _doc_thang(conn, execution.id)


def don_execution_mo_coi(connection: sqlite3.Connection | None = None) -> int:
    """Đóng mọi execution còn sống lúc khởi động. Trả số hàng.

    Cùng lý do và cùng khuôn với `invalidate_orphaned_pending_approvals`: một chuỗi lệnh
    dở dang không sống qua restart được — không có vòng lặp nào đang chạy để tiếp tục nó,
    và `routines_product_spec.md` §Sau khi khởi động lại chốt rằng **không** Routine nào
    tự chạy tiếp sau restart. Để nguyên `running` thì client thấy một lần chạy vĩnh viễn
    "đang chạy" và ràng buộc một-Routine-mỗi-phiên khoá luôn phiên ấy.
    """
    conn = connection or get_connection()
    cursor = conn.execute(
        """
        UPDATE routine_executions
           SET status = 'failed', terminal_reason = 'interrupted_by_restart', updated_at = ?
         WHERE status IN ('running', 'waiting_approval')
        """,
        (_now(),),
    )
    conn.commit()
    return cursor.rowcount


def tim_theo_approval(approval_id: str, *, connection: sqlite3.Connection | None = None) -> RoutineExecution | None:
    """Execution đang chờ đúng thẻ phê duyệt này, hoặc `None`.

    `src/api/approvals.py` dùng nó để rẽ nhánh: một thẻ của Routine không được đem đi
    resume graph LangGraph — không có lượt nào ở đó để tiếp tục.
    """
    conn = connection or get_connection()
    row = conn.execute(
        "SELECT * FROM routine_executions WHERE approval_id = ? AND status = 'waiting_approval'",
        (approval_id,),
    ).fetchone()
    return _dung(row) if row is not None else None


async def tiep_tuc_sau_phe_duyet(
    approval_id: str, *, approved: bool, connection: sqlite3.Connection | None = None
) -> RoutineExecution | None:
    """Chạy tiếp (hoặc đóng) execution sau một quyết định phê duyệt.

    Từ chối ⇒ `user_canceled`, **zero side effect** cho bước ấy và không chạy bước nào
    nữa (§Hủy). Không rollback bước đã xong — chúng đã xảy ra thật.
    """
    conn = connection or get_connection()
    execution = tim_theo_approval(approval_id, connection=conn)
    if execution is None:
        return None

    if not approved:
        results = list(execution.results)
        return await _ket_thuc(
            conn,
            execution,
            results,
            execution.current_index,
            status="user_canceled",
            reason="approval_rejected",
            buoc_status="canceled",
            buoc_error="approval_rejected",
            mo_ta=str(execution.steps[execution.current_index].get("action")),
        )

    from src.services.vehicle_gateway import get_vehicle_gateway

    gateway = get_vehicle_gateway()
    index = execution.current_index
    step = execution.steps[index]
    results = list(execution.results)

    # Dựng lại plan từ trạng thái xe **hiện tại**, không dùng lại plan lúc xin phê duyệt.
    # Nếu xe đã đổi trạng thái trong lúc chờ thì `ApprovalStore` đã invalidate thẻ, và
    # `gateway.execute` còn một lớp nữa: `expected_state_version` lệch ⇒ `stale_state`.
    live = await gateway.snapshot()
    if live is None:
        return await _ket_thuc(
            conn,
            execution,
            results,
            index,
            status="failed",
            reason="vehicle_state_unavailable",
            buoc_status="failed",
            buoc_error="vehicle_state_unavailable",
            mo_ta=str(step.get("action")),
        )
    snapshot = snapshot_dict(live)
    candidate = routine_thanh_candidate([step], dia_diem=_dia_diem_cua(execution.user_id, conn))
    plan = materialize_action_plan(
        candidate, snapshot, execution.session_id, execution.vehicle_id, route_source="routine"
    )
    mo_ta = _mo_ta(step, plan)

    if any(s.safety_level == "S3" for s in plan.steps):
        # Xe chuyển bánh trong lúc chờ phê duyệt. Thẻ đã duyệt **không** cấp quyền vượt
        # phân loại an toàn: S3 chặn sau khi đồng ý cũng như trước.
        return await _ket_thuc(
            conn,
            execution,
            results,
            index,
            status="blocked",
            reason="blocked_by_vehicle_state",
            buoc_status="blocked",
            buoc_error="blocked_by_vehicle_state",
            mo_ta=mo_ta,
        )

    status, error_code = await _chay_mot_buoc(gateway, plan, approval_id=approval_id)
    buoc = KetQuaBuoc(
        index=index, action=str(step.get("action")), status=status, description=mo_ta, error_code=error_code
    )
    results.append(buoc)
    await _phat(execution, "routine.step", {"execution_id": execution.id, **buoc.as_dict()})
    if status != "completed":
        return await _ket_thuc_sau_khi_da_ghi(conn, execution, results, index + 1, "failed", error_code)

    _luu(
        conn,
        execution.id,
        status="running",
        current_index=index + 1,
        approval_id=None,
        results=results,
        terminal_reason=None,
    )
    return await _chay_tiep(execution.id, connection=conn)


def doc(user_id: str, execution_id: str, *, connection: sqlite3.Connection | None = None) -> RoutineExecution:
    """Một execution **của user này**. Ném `LookupError` cho mọi ca khác.

    Cùng kỷ luật với `routines_store`: id của người khác và id không tồn tại không phân
    biệt được từ phía client.
    """
    conn = connection or get_connection()
    row = conn.execute(
        "SELECT * FROM routine_executions WHERE id = ? AND user_id = ?",
        (execution_id, user_id),
    ).fetchone()
    if row is None:
        raise LookupError(execution_id)
    return _dung(row)


def dang_chay_cua_routine(routine_id: str, *, connection: sqlite3.Connection | None = None) -> RoutineExecution | None:
    """Lần chạy còn sống của một Routine, hoặc `None`. `routines_store` dùng để chặn xoá."""
    conn = connection or get_connection()
    row = conn.execute(
        "SELECT * FROM routine_executions WHERE routine_id = ? AND status IN ('running', 'waiting_approval')",
        (routine_id,),
    ).fetchone()
    return _dung(row) if row is not None else None


def dang_chay_trong_phien(session_id: str, *, connection: sqlite3.Connection | None = None) -> RoutineExecution | None:
    """Lần chạy còn sống của một **phiên**, hoặc `None`.

    Cặp với `dang_chay_cua_routine`, nhưng hỏi theo chiều khác: cái kia trả lời "Routine
    này có đang chạy không" (để `routines_store` chặn xoá), cái này trả lời "phiên này có
    gì đang chạy không". Đúng câu hỏi mà một tiếng *"dừng lại"* đặt ra: tài xế không nêu
    tên, và cái duy nhất họ có thể muốn dừng là thứ đang chạy ngay đây (#299).

    Ràng buộc một-Routine-mỗi-phiên (`routine_executions_one_active_per_session`) là thứ
    làm câu trả lời **đơn trị**: không bao giờ có hai hàng để phải chọn.
    """
    conn = connection or get_connection()
    row = conn.execute(
        "SELECT * FROM routine_executions WHERE session_id = ? AND status IN ('running', 'waiting_approval')",
        (session_id,),
    ).fetchone()
    return _dung(row) if row is not None else None


__all__ = [
    "TRANG_THAI_CON_SONG",
    "don_execution_mo_coi",
    "huy",
    "TRANG_THAI_CUOI",
    "KetQuaBuoc",
    "RoutineDangChayError",
    "RoutineExecution",
    "RoutineKhongChayDuocError",
    "dang_chay_cua_routine",
    "dang_chay_trong_phien",
    "bat_dau",
    "dang_chay_trong_phien",
    "doc",
    "tiep_tuc_sau_phe_duyet",
    "tim_theo_approval",
]

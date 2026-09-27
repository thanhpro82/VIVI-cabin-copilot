"""Đường Routine trong graph: phân giải tên rồi gọi service của BE. Issue #274, #299.

## Chủ sở hữu duy nhất

Mọi lượt `disposition == "routine"` đi qua đúng file này. Router chỉ nói *"đây là ý định
Routine, tên thô là X"*; nó **không** phân giải tên, vì danh sách Routine của user là
**trạng thái** và ADR-006/010 cấm router đọc trạng thái — cùng chỗ đứng với
`ghep_hoi_lai` và `loi_de_nghi`.

## Ba service tiêm vào, không nhập thẳng

`make_routine_node` nhận `liet_ke`, `bat_dau`, `huy`, `dang_chay_cua_phien` làm tham số.
Hai lý do, và lý do thứ hai mới là lý do thật:

1. test chạy được mà không cần DB;
2. **ranh giới sở hữu.** Ba hàm ấy thuộc `src/services/` của làn BE (#299: *"không tự hủy
   executor"*). Tiêm vào thì file này không bao giờ giả định hình dạng bên trong chúng, và
   một thay đổi bên ấy làm đỏ đúng chỗ nối chứ không âm thầm đổi hành vi.

`bat_dau` đã có sẵn các cổng admission chạy **trước** khi có hàng nào trong
`routine_executions`, và `huy` idempotent. Không dựng lại bản thứ hai ở đây: một bản sao
của luật an toàn là một bản chắc chắn sẽ lệch.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from src.agents.routines import mo_ta_buoc_routine
from src.agents.routines_intent import phan_giai_ten
from src.agents.state import AgentState
from src.services.routine_execution import RoutineKhongChayDuocError

logger = logging.getLogger(__name__)


def _xoa_cho_xac_nhan() -> dict:
    """Ngữ cảnh preview cho lượt sau bị xoá — dùng ở mọi lối ra không phải preview mới."""
    return {"routine_cho_xac_nhan_id": "", "routine_cho_xac_nhan_luc": 0.0}


def _nap_cho_xac_nhan(routine_id: str, dong_ho: Callable[[], float]) -> dict:
    """Ngữ cảnh preview cho lượt sau — chỉ nạp ở đúng một chỗ: preview vừa thành công."""
    return {"routine_cho_xac_nhan_id": routine_id, "routine_cho_xac_nhan_luc": dong_ho()}


def make_routine_node(
    *,
    liet_ke: Callable[[str], list[Any]],
    bat_dau: Callable[..., Any],
    huy: Callable[..., Any],
    dang_chay_cua_phien: Callable[[str], Any | None],
    dong_ho: Callable[[], float] = time.monotonic,
):
    async def _chay(routine_id: str, *, user_id: str, session_id: str, vehicle_id: str) -> dict:
        """Gọi `bat_dau` và diễn giải kết quả — dùng chung cho ca "chạy mới" (tên vừa
        phân giải xong) và ca "đồng ý sau preview" (routine_id đọc lại từ ngữ cảnh treo).
        Một bản sao thứ hai của khối try/except này là một bản chắc chắn sẽ lệch khi làn
        BE thêm lý do từ chối thứ năm.
        """
        try:
            ra = await bat_dau(
                user_id=user_id,
                session_id=session_id,
                vehicle_id=vehicle_id,
                routine_id=routine_id,
            )
        except RoutineKhongChayDuocError as loi:
            # Bốn lời từ chối của `bat_dau` là **câu trả lời**, không phải sự cố: Routine
            # đang tắt, chưa đặt địa điểm Nhà/Cơ quan, đã có Routine khác chạy dở, hoặc
            # Routine biến mất giữa chừng. Tất cả đều xảy ra **trước** khi tạo execution,
            # nên zero side effect — và tất cả đều là thứ tài xế cần nghe.
            #
            # Không bắt thì chúng thành 500. Đo end-to-end 30/08: hai trong ba mẫu mặc
            # định (`Đi làm`, `Về nhà`) đang ở trạng thái "Cần thiết lập", nên đây là ca
            # **thường gặp**, không phải ca biên.
            #
            # Dùng `thong_diep` của chính lỗi, không viết lại: nó được soạn để đọc lên, và
            # một bản sao ở đây là một bản sẽ lệch khi bên kia thêm lý do thứ năm.
            logger.info("Routine không chạy được: %s", loi.ma)
            return {
                "outcome": "routine_tu_choi",
                "routine_id": routine_id,
                "routine_ly_do": str(loi),
                # Mã máy đọc được, tách khỏi câu đọc lên. #385 cần đúng cái này: FE phải
                # đưa tài xế sang màn setup Nhà/Cơ quan khi mã là `chua_dat_dia_diem`, và
                # không client nào nên rẽ nhánh bằng cách so khớp một câu tiếng Việt.
                "routine_ma_loi": loi.ma,
                # #385: có cấu trúc CHỈ khi thiếu địa điểm — ba lý do từ chối còn lại
                # (đang tắt/không tồn tại/đang chạy dở) không có màn setup nào để đưa
                # tài xế sang, gán địa điểm không sửa được chúng.
                "routine_setup_required": (
                    {"routine_id": routine_id, "ma_loi": loi.ma, "thieu": list(loi.thieu_dia_diem)}
                    if loi.ma == "chua_dat_dia_diem"
                    else None
                ),
                # Cùng lỗ mà review PR #404 chỉ ra ở `route.py`, nhưng ở đây: lượt trước có
                # thể đã để lại `routine_preview` (ca preview -> đồng ý -> bị từ chối vì
                # thiếu địa điểm), và `_chay` không tự nhiên biết phải xoá nó nếu không ghi
                # rõ ở đây.
                "routine_preview": None,
            }
        return {
            "outcome": "routine_da_chay",
            "routine_id": routine_id,
            "routine_execution_id": ra.id,
            "routine_setup_required": None,
            "routine_preview": None,
        }

    async def routine_node(state: AgentState) -> dict:
        y_dinh = str(state.get("routine_y_dinh") or "")
        user_id = str(state.get("user_id") or "")
        session_id = str(state.get("session_id") or "")

        # Fail-closed. State tới từ `turns.py`, nên thiếu khoá là lỗi lập trình chứ không
        # phải lượt nói lạ. Lối ra an toàn là **không làm gì**: đoán một `user_id` khác là
        # chạy lệnh trên xe của người khác.
        if not user_id or not session_id:
            logger.warning("lượt Routine thiếu ngữ cảnh: user=%r session=%r", user_id, session_id)
            # Outcome RIÊNG, không mượn `routine_khong_thay`. Bản đầu mượn, và câu nó sinh
            # ra — *"Bạn chưa có Routine nào."* — đã đánh lừa chính tôi khi đo end-to-end
            # 30/08: `user_id` chưa được `turns.py` đưa vào state, nhưng xe nói y hệt như
            # một tài khoản trống thật, trong khi UI đang hiện đủ ba mẫu. Một lỗi lập
            # trình mà phát ra câu của một trạng thái hợp lệ thì không ai đi tìm nó.
            return {
                "outcome": "routine_loi_ngu_canh",
                "routine_setup_required": None,
                "routine_preview": None,
                **_xoa_cho_xac_nhan(),
            }

        if y_dinh == "huy":
            lan_chay = dang_chay_cua_phien(session_id)
            if lan_chay is None:
                # KHÔNG báo "đã hủy". Nói dối về một việc an toàn thì tài xế tin rằng xe
                # vừa dừng một thứ đang chạy — và thôi không dừng nó bằng cách khác nữa.
                return {
                    "outcome": "routine_khong_co_lan_chay",
                    "routine_setup_required": None,
                    "routine_preview": None,
                    **_xoa_cho_xac_nhan(),
                }
            ra = await huy(user_id, lan_chay.id)
            return {
                "outcome": "routine_da_huy",
                "routine_execution_id": ra.id,
                "routine_setup_required": None,
                "routine_preview": None,
                **_xoa_cho_xac_nhan(),
            }

        if y_dinh in ("dong_y", "tu_choi"):
            # `_dap_xem_truoc_routine` (route.py, review PR #401) đã phân giải và đọc lại
            # đúng `routine_id` từ ngữ cảnh treo trước khi forward hai ý định này — không
            # phân giải tên gì cả ở đây, vì lượt này không hề nêu tên nào.
            routine_id = str(state.get("routine_cho_xac_nhan_id") or "")
            if not routine_id:
                # Phòng thủ: route_node chỉ tạo ra `dong_y`/`tu_choi` khi đã thấy khe còn
                # hạn. Rơi vào đây nghĩa là lỗi lập trình ở chỗ nối, không phải câu nói lạ.
                logger.warning("routine_node nhận %r mà không có preview nào đang treo", y_dinh)
                return {
                    "outcome": "routine_loi_ngu_canh",
                    "routine_setup_required": None,
                    "routine_preview": None,
                    **_xoa_cho_xac_nhan(),
                }
            if y_dinh == "tu_choi":
                return {
                    "outcome": "routine_huy_xem_truoc",
                    "routine_id": routine_id,
                    "routine_setup_required": None,
                    "routine_preview": None,
                    **_xoa_cho_xac_nhan(),
                }
            ket_qua = await _chay(
                routine_id,
                user_id=user_id,
                session_id=session_id,
                vehicle_id=str(state.get("vehicle_id") or ""),
            )
            return {**ket_qua, **_xoa_cho_xac_nhan()}

        ds = liet_ke(user_id)
        ten = [r.name for r in ds]
        kq = phan_giai_ten(str(state.get("routine_ten_tho") or ""), ten)

        if kq.trung is None:
            # `khong_thay` đòi `ung_vien` rỗng và `mo_ho` đòi hơn một mục, nên "không trúng
            # mà đúng một ứng viên" lọt qua cả hai. Gộp nó về nhánh hỏi lại: chạy một
            # Routine mà bộ phân giải **không** dám gọi là trúng thì đúng thứ không nên
            # làm mà không hỏi.
            if kq.khong_thay:
                return {
                    "outcome": "routine_khong_thay",
                    "routine_ung_vien": ten,
                    "routine_setup_required": None,
                    "routine_preview": None,
                    **_xoa_cho_xac_nhan(),
                }
            return {
                "outcome": "routine_mo_ho",
                "routine_ung_vien": list(kq.ung_vien),
                "routine_setup_required": None,
                "routine_preview": None,
                **_xoa_cho_xac_nhan(),
            }

        routine = next(r for r in ds if r.name == kq.trung)
        routine_id = routine.id
        if y_dinh == "xem_truoc":
            # KHÔNG chạm executor — bất biến của #274. Sau một lượt preview, không có hàng
            # nào trong `routine_executions`. Nạp ngữ cảnh chờ xác nhận CHO LƯỢT SAU — đúng
            # phần còn thiếu mà review PR #401 chỉ ra: router chưa từng gọi `doc_y_dinh`
            # với `dang_xem_truoc=True`, vì chưa có gì để đánh dấu "đang treo" cả.
            return {
                "outcome": "routine_preview",
                "routine_id": routine_id,
                "routine_preview": {
                    "routine_id": routine_id,
                    "routine_name": routine.name,
                    "steps": [
                        {
                            "index": index,
                            "action": str(step.get("action") or ""),
                            "description": mo_ta_buoc_routine(step),
                        }
                        for index, step in enumerate(routine.steps)
                    ],
                },
                "routine_setup_required": None,
                **_nap_cho_xac_nhan(routine_id, dong_ho),
            }

        ket_qua = await _chay(
            routine_id,
            user_id=user_id,
            session_id=session_id,
            vehicle_id=str(state.get("vehicle_id") or ""),
        )
        return {**ket_qua, **_xoa_cho_xac_nhan()}

    return routine_node

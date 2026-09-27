"""Pool xe ảo có hạn, cấp cho phiên tài xế theo kiểu thuê có hạn dùng.

## Vì sao có file này

`vehicle_id` từng là một hằng số (`config.py`), nên **mọi người dùng chung một chiếc
xe**. Hệ quả không phải sự bất tiện mà là lỗi thật: cơ chế chống ghi đè theo
`state_version` bị kích hoạt liên tục, khiến kế hoạch nhiều bước của người này bị cắt
giữa chừng (`nodes/execute.py` → `skipped_external_state_change`) và phê duyệt HITL bị
vô hiệu (`nodes/approval.py` → `approval_invalidated_state`) chỉ vì người kia vừa bật
điều hoà.

## Vì sao **có hạn**, không phải mỗi phiên một xe

RAM không phải ràng buộc — đo được 13 KB mỗi xe ảo và 512 KB mỗi phiên backend, tức 100
người chỉ tốn ~53 MB (run `20260823T102102` và `20260823T103405`). Ràng buộc là
**llama-server**: đo được trần đồng thời khoảng 3 (run `20260823T120422`), và STT/TTS còn
có khoá toàn cục nên chỉ phục vụ một người một lúc.

Cấp xe không giới hạn sẽ để một người mở 10 tab chiếm sạch tài nguyên mà không có chỗ nào
chặn. Nên pool có trần, và **trần đó là con số đo được, không phải chọn bừa**.

## Vì sao hết pool KHÔNG phải là lỗi

Phiên không thuê được xe vẫn tra sổ tay và đọc trạng thái xe được; chỉ lệnh điều khiển bị
từ chối, với mã riêng để client nói đúng chuyện đang xảy ra thay vì báo một lỗi chung
chung. Quá tải là chuyện **chắc chắn xảy ra** với trần 3, nên đường lui này là một phần
của thiết kế chứ không phải nhánh phòng xa.

## Sức chứa chỉ có MỘT nguồn

`suc_chua()` là chỗ duy nhất trong hệ tính ra "còn mấy xe". Màn tài xế, màn kỹ sư và
`/healthz` đều đọc từ đây. Cùng kỷ luật một-nguồn-sự-thật mà ADR-013 đặt ra cho trạng thái
xe: hai chỗ tự đếm là hai chỗ sẽ lệch nhau, và lúc đó không ai biết chỗ nào đúng.

## Hai giả định, cả hai đều là giả định sẵn có của hệ

1. **Một tiến trình, một event loop.** Không khoá, vì `session_state._GRAPHS`,
   `InMemorySaver` và kết nối SQLite đơn đều đã giả định như vậy. Chạy hai worker thì pool
   này sai — nhưng lúc đó checkpointer và idempotency store cũng sai trước nó.
2. **Hết hạn phát hiện lúc đọc**, không có tác vụ nền quét. Cùng khuôn với
   `approval.py` (CAS lúc đọc) và `get_session_record` (phiên hết hạn trả `None`). Một
   tác vụ nền là một thứ nữa phải khởi động, dừng và test cho đúng, đổi lại không mua thêm
   gì: xe chỉ cần rảnh **vào lúc có người hỏi xin**.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SucChua:
    """Ảnh chụp sức chứa pool. `con_trong` **dẫn xuất**, không lưu riêng."""

    tong: int
    dang_dung: int

    @property
    def con_trong(self) -> int:
        return self.tong - self.dang_dung

    def as_dict(self) -> dict[str, int]:
        return {"tong": self.tong, "dang_dung": self.dang_dung, "con_trong": self.con_trong}


@dataclass
class _HopDong:
    """Một hợp đồng thuê. `den_han` tính theo đồng hồ đơn điệu."""

    session_id: str
    vehicle_id: str
    den_han: float


class VehiclePool:
    """Cấp `vehicle_id` cho `session_id`, có hạn dùng và tự thu hồi.

    `dong_ho` nhận từ ngoài để test không phải ngủ thật. Mặc định là
    `time.monotonic` **chứ không phải** `time.time`: giờ hệ thống có thể nhảy (NTP, đổi
    múi giờ) và một cú nhảy lùi sẽ làm mọi hợp đồng đột nhiên còn hạn rất lâu.
    """

    def __init__(
        self,
        vehicle_ids: Sequence[str],
        *,
        lease_ttl_s: float,
        dong_ho: Callable[[], float] = time.monotonic,
    ) -> None:
        if not vehicle_ids:
            raise ValueError("pool phải có ít nhất một xe")
        if len(set(vehicle_ids)) != len(vehicle_ids):
            raise ValueError(f"vehicle_ids trùng nhau: {vehicle_ids}")
        if lease_ttl_s <= 0:
            raise ValueError(f"lease_ttl_s phải dương, nhận {lease_ttl_s}")
        self._vehicle_ids = tuple(vehicle_ids)
        self._lease_ttl_s = lease_ttl_s
        self._dong_ho = dong_ho
        #: `session_id` -> hợp đồng. Xe rảnh là xe không xuất hiện ở đây.
        self._hop_dong: dict[str, _HopDong] = {}

    # -- công khai ---------------------------------------------------------

    @property
    def vehicle_ids(self) -> tuple[str, ...]:
        """Toàn bộ xe trong pool, kể cả xe đang rảnh. Thứ tự cố định."""
        return self._vehicle_ids

    def thue(self, session_id: str) -> str | None:
        """Cấp xe cho phiên, hoặc gia hạn nếu phiên đã có xe. `None` khi hết pool.

        **Bất biến quan trọng: gọi lại không cấp thêm xe.** Một phiên chỉ giữ đúng một
        xe. Không có bất biến này thì mỗi lượt nói là một lần chiếm thêm một xe, và pool
        cạn sau ba câu.
        """
        self._quet_het_han()
        hien_co = self._hop_dong.get(session_id)
        if hien_co is not None:
            hien_co.den_han = self._dong_ho() + self._lease_ttl_s
            return hien_co.vehicle_id

        dang_dung = {hd.vehicle_id for hd in self._hop_dong.values()}
        for vehicle_id in self._vehicle_ids:
            if vehicle_id not in dang_dung:
                self._hop_dong[session_id] = _HopDong(
                    session_id=session_id,
                    vehicle_id=vehicle_id,
                    den_han=self._dong_ho() + self._lease_ttl_s,
                )
                logger.info("Cấp xe %s cho phiên %s", vehicle_id, session_id)
                return vehicle_id

        logger.info(
            "Hết xe trong pool (%d/%d), phiên %s vào chế độ chỉ xem",
            len(self._hop_dong),
            len(self._vehicle_ids),
            session_id,
        )
        return None

    def gia_han(self, session_id: str) -> str | None:
        """Gia hạn hợp đồng đang có. **Không cấp mới** nếu phiên chưa có xe.

        Tách khỏi `thue()` vì hai chỗ gọi có ý định khác nhau: `_touch()` chạy ở **mọi**
        đường vào và chỉ nên giữ cho xe khỏi bị thu hồi; cấp mới là việc của lúc tạo
        phiên. Gộp lại thì một phiên chỉ-xem sẽ lặng lẽ chiếm được xe ngay khi có người
        khác rời đi, giữa chừng một lượt — hành vi đúng nhưng khó lần ra khi debug.
        """
        self._quet_het_han()
        hop_dong = self._hop_dong.get(session_id)
        if hop_dong is None:
            return None
        hop_dong.den_han = self._dong_ho() + self._lease_ttl_s
        return hop_dong.vehicle_id

    def xe_cua(self, session_id: str) -> str | None:
        """Xe của phiên, hoặc `None` nếu phiên không có xe (chưa cấp / đã hết hạn).

        Chỉ **đọc**, không gia hạn. Gia hạn ở đây thì một client poll `GET /vehicle/state`
        mỗi 2 giây sẽ giữ xe vô thời hạn dù người dùng đã bỏ đi.
        """
        self._quet_het_han()
        hop_dong = self._hop_dong.get(session_id)
        return hop_dong.vehicle_id if hop_dong is not None else None

    def phien_cua(self, vehicle_id: str) -> list[str]:
        """Các phiên đang thuê một xe. Dùng để phát `ui.policy` đúng người.

        Trả về `list` chứ không phải một giá trị: bất biến "một xe một phiên" do
        `thue()` giữ, nhưng chỗ gọi không nên phụ thuộc vào nó — nếu sau này cho phép
        hai màn hình cùng nhìn một xe thì chỉ `thue()` đổi, chỗ gọi không đổi.
        """
        self._quet_het_han()
        return [hd.session_id for hd in self._hop_dong.values() if hd.vehicle_id == vehicle_id]

    def tra(self, session_id: str) -> str | None:
        """Trả xe sớm. Trả về xe vừa nhả, hoặc `None` nếu phiên vốn không giữ xe."""
        hop_dong = self._hop_dong.pop(session_id, None)
        if hop_dong is None:
            return None
        logger.info("Phiên %s trả xe %s", session_id, hop_dong.vehicle_id)
        return hop_dong.vehicle_id

    def suc_chua(self) -> SucChua:
        """Nguồn DUY NHẤT của con số "còn mấy xe". Xem docstring đầu file."""
        self._quet_het_han()
        return SucChua(tong=len(self._vehicle_ids), dang_dung=len(self._hop_dong))

    def reset(self) -> None:
        """Chỉ dùng trong test — dọn state giữa các case."""
        self._hop_dong.clear()

    # -- nội bộ ------------------------------------------------------------

    def _quet_het_han(self) -> None:
        bay_gio = self._dong_ho()
        het_han = [sid for sid, hd in self._hop_dong.items() if hd.den_han <= bay_gio]
        for session_id in het_han:
            hop_dong = self._hop_dong.pop(session_id)
            logger.info("Hợp đồng của phiên %s hết hạn, thu hồi xe %s", session_id, hop_dong.vehicle_id)

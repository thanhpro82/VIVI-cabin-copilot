"""Chính sách UI cho tài xế — dẫn xuất ở backend, client không được tự suy.

`docs/technical_spec.md:74` ghi thẳng: *"The frontend renders backend-issued `ui_policy`;
it never infers safety from a local speed reading."* Đây là lý do tồn tại của module
này: tốc độ có sẵn ở client qua `GET /vehicle/state`, nên nếu không phát policy thì
sớm muộn sẽ có người tính nó ở FE — và lúc đó luật an toàn nằm rải ở hai nơi.

Ba quyết định đã chốt (Nhân, 2026-08-12), ghi tại chỗ vì chúng đổi hành vi sản phẩm:

1. **"Đang chạy" = phủ định của `is_stationary()`**, tức KHÔNG (`speed_kph == 0` và
   `gear == "P"`). Dùng lại đúng hàm mà cổng an toàn S2/S3 đang dùng
   (`src/agents/policy.py`) để hệ thống chỉ có **một** định nghĩa "đứng yên". Hệ quả
   cố ý: xe dừng đèn đỏ ở số D vẫn bị siết UI — người lái sắp đi tiếp.

   Đừng thay bằng ngưỡng `speed_kph > 5` của `docs/VIVI_API_Spec.md`: ADR-010 đã bác,
   và CLAUDE.md cấm rõ.

2. **Không đọc được trạng thái xe → siết chặt nhất.** Cùng kỷ luật fail-closed với
   `safety_node` (không đọc được state thì từ chối lệnh). Mở UI đúng lúc không biết xe
   đang thế nào là kiểu hỏng tệ nhất có thể chọn.

3. **Sáu giá trị chế độ chạy là hằng số hợp đồng**, chép từ `docs/api_spec.md:582` và
   phải bằng đúng bản trong `technical_spec.md`/`user_experience.md`. Đổi một giá trị ở
   đây là đổi hợp đồng, không phải tinh chỉnh.
"""

from __future__ import annotations

from typing import Any

from src.agents.policy import is_stationary

#: Chế độ đang chạy — sáu giá trị chốt cứng ở `api_spec.md:582`.
_MOVING = {
    "allow_text_input": False,
    "lock_small_controls": True,
    "enlarge_mic_button": True,
    "max_visible_actions": 3,
    "prefer_voice_confirmation": True,
    "allow_detailed_document_browsing": False,
}

#: Chế độ đứng yên — `user_experience.md:87`: "Voice and text are available; manual
#: citation viewer and detailed controls may be shown when backend policy allows."
#:
#: `max_visible_actions` giữ 3 ở **cả hai** chế độ, và đó không phải sơ suất: hợp đồng
#: giới hạn trường này trong 1..3 còn chế độ chạy đã chốt là 3, nên nó không thể cao
#: hơn khi đứng yên. Giá trị thấp hơn dành cho điều kiện *độ tin cậy ASR thấp*
#: (`user_experience.md:142`: "no more than two choices while moving") — thứ chỉ biết
#: được trong một lượt cụ thể, nên thuộc lần phát gắn `turn_id`, không thuộc chỗ này.
_STATIONARY = {
    "allow_text_input": True,
    "lock_small_controls": False,
    "enlarge_mic_button": False,
    "max_visible_actions": 3,
    "prefer_voice_confirmation": False,
    "allow_detailed_document_browsing": True,
}


def derive_ui_policy(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Payload `ui.policy` canonical từ snapshot xe, hoặc bản siết nhất khi `None`.

    Shape đóng theo `api_spec.md:572` — `active`, `speed_kph`, và **object `ui_policy`
    lồng** đúng sáu trường. Thừa hay thiếu trường đều bị hợp đồng từ chối, nên đừng
    thêm gì vào đây mà không sửa spec trước.
    """
    if snapshot is None:
        # Không biết xe đang thế nào: báo `active=true` và `speed_kph=0`. Nói "đang
        # chạy ở 0 km/h" nghe mâu thuẫn, nhưng thà thế còn hơn bịa một tốc độ, và
        # `active` mới là thứ FE dùng để siết.
        return {"active": True, "speed_kph": 0, "ui_policy": dict(_MOVING)}

    moving = not is_stationary(snapshot)
    speed = snapshot["motion"]["speed_kph"]
    return {
        "active": moving,
        "speed_kph": speed,
        "ui_policy": dict(_MOVING if moving else _STATIONARY),
    }


class UiPolicyEmitter:
    """Phát `ui.policy` khi policy **đổi**, không phải khi trạng thái xe đổi.

    Đây là chỗ dễ làm hỏng ADR-014 nhất. Xe ảo publish snapshot liên tục khi đang
    chạy; nếu bắn một event mỗi snapshot thì ring buffer 200 event của mỗi session bị
    policy chiếm sạch trong vài giây, và replay khi tài xế reconnect — thứ ADR-014
    tồn tại để bảo đảm — trở nên vô dụng. Nên chỉ phát khi payload **khác** lần trước.

    Nhưng chỉ kích theo cạnh thì thủng một lỗ: tài xế nối máy giữa lúc xe đang chạy
    sẽ không nhận policy nào cho tới lần đổi kế tiếp, và FE render giao diện không
    hạn chế trong khi xe chạy — đúng lỗ hổng mà việc này sinh ra để bịt. Vế còn lại
    nằm ở `src/api/ws.py`: phát một lần ngay sau khi handshake xong. Thiếu vế nào
    cũng sai.
    """

    #: `ui.policy` không thuộc lượt nào nên không có trace của lượt để mượn.
    TRACE_ID = "tr_ui_policy"

    def __init__(self, bus: Any, vehicle_id: str | None = None) -> None:
        """`vehicle_id = None` giữ nguyên hành vi cũ: phát tới **mọi** phiên.

        Đặt tên xe vào thì emitter chỉ phát cho những phiên đang thuê chính chiếc xe đó.
        Trạng thái `_last` vì vậy **phải** là của riêng từng xe — dùng chung một emitter
        cho nhiều xe nghĩa là xe A đổi policy sẽ nuốt mất lần phát của xe B chỉ vì hai
        policy tình cờ giống nhau.
        """
        self._bus = bus
        self._vehicle_id = vehicle_id
        self._last: tuple[bool, dict[str, Any]] | None = None

    def note_published(self, payload: dict[str, Any]) -> None:
        """Ghi nhận một `ui.policy` **do người khác phát** đã tới client.

        `src/api/ws.py` phát một `ui.policy` ngay sau handshake (vế thứ hai của thiết
        kế) bằng `bus.publish` thẳng, không qua emitter. Không có hàm này thì `_last`
        của emitter vẫn là `None` sau lần đó, nên **lần đổi trạng thái xe đầu tiên sau
        khi server lên** sẽ khiến emitter phát lần đầu — trùng đúng nội dung client
        vừa nhận lúc handshake.

        Đo được trên server thật: một event thừa mỗi vòng đời tiến trình, rơi vào phiên
        nào tình cờ đang nối lúc đó. Cùng loại với issue #94, nhỏ hơn nhiều.

        Seed như vậy là an toàn vì `_last` mô tả policy của **chiếc xe toàn cục** —
        đúng thứ mà bản phát lúc handshake cũng mang, dù nó gửi cho một phiên.
        """
        self._last = (payload["active"], payload["ui_policy"])

    def reset(self) -> None:
        """Quên policy đã phát lần cuối. Chỉ dùng trong test.

        Emitter của `main.py` sống ở mức module nên `_last` đi xuyên qua mọi test. Từ
        khi wiring production chạy thật (PR #77), rò rỉ đó thành lỗi: test A cho xe
        chạy → `_last = (True, MOVING)`; test B reset cổng xe về đứng yên rồi cho chạy
        lại → policy y hệt `_last` nên **không phát gì**, và test B đỏ vì một lý do
        không liên quan gì tới nó. Đúng loại phụ thuộc thứ tự mà phoenix cảnh báo ở
        cùng PR.
        """
        self._last = None

    async def on_state(self, state: Any) -> None:
        """`StateListener` của `VehicleGateway` — nhận `VehicleState`, không phải dict."""
        from src.services.vehicle_gateway import snapshot_dict

        await self.publish_if_changed(snapshot_dict(state))

    async def publish_if_changed(self, snapshot: dict[str, Any] | None) -> bool:
        """So cạnh trên phần **mang chính sách**, cố ý bỏ `speed_kph` ra ngoài.

        So cả payload thì 42 → 43 km/h cũng tính là "đổi", và xe đang chạy thì tốc độ
        đổi liên tục — tức lại rơi đúng vào chuyện ngập ring buffer mà kích-theo-cạnh
        sinh ra để tránh. (Chính test `test_ui_policy_kich_theo_canh_...` bắt được điều
        này ở bản đầu.)

        Hệ quả: `speed_kph` trong event là tốc độ **tại thời điểm policy đổi**, có thể
        cũ. Chấp nhận được vì hợp đồng đã cấm client suy an toàn từ nó
        (`technical_spec.md:74`) — nó là thông tin kèm theo, không phải đầu vào quyết
        định. Nếu sau này FE cần tốc độ tươi để hiển thị thì lấy từ
        `GET /vehicle/state`, đừng nới cổng cạnh ở đây.
        """
        payload = derive_ui_policy(snapshot)
        policy_part = (payload["active"], payload["ui_policy"])
        if policy_part == self._last:
            return False
        self._last = policy_part
        if self._vehicle_id is None:
            await self._bus.broadcast("ui.policy", self.TRACE_ID, payload)
        else:
            await self._bus.broadcast_to(_phien_dang_thue(self._vehicle_id), "ui.policy", self.TRACE_ID, payload)
        return True


#: Emitter dùng chung, khởi tạo lười.
#:
#: Đặt ở đây chứ không ở `src/main.py` như bản trước: `src/api/ws.py` cũng cần chạm tới
#: nó (gọi `note_published` sau khi phát ở handshake), mà `ws.py` không import được
#: `main.py` — `main.py` đã import router của `ws.py`, nhập ngược là vòng.
_EMITTER: UiPolicyEmitter | None = None

#: Một emitter cho **mỗi** xe trong pool. Xem docstring của `UiPolicyEmitter.__init__`
#: về việc vì sao không dùng chung được.
_EMITTERS: dict[str, UiPolicyEmitter] = {}


def _phien_dang_thue(vehicle_id: str) -> list[str]:
    """Các phiên đang thuê một chiếc xe.

    Import trễ để tránh vòng: `session_state` đã nhập `vehicle_gateway`, mà chính
    `vehicle_gateway` là chỗ gắn emitter này vào cổng.
    """
    from src.api.session_state import get_vehicle_pool

    pool = get_vehicle_pool()
    if pool is None:
        # Không cấp phát = một chiếc xe cho cả hệ. Không có bảng thuê để tra, và mọi
        # phiên đều đang nhìn đúng chiếc xe đó.
        from src.services.ivi_events import get_event_bus

        return get_event_bus().active_sessions()
    return pool.phien_cua(vehicle_id)


def get_ui_policy_emitter(vehicle_id: str | None = None) -> UiPolicyEmitter:
    """Emitter dùng chung (`None`) hoặc emitter của một chiếc xe cụ thể."""
    global _EMITTER
    from src.services.ivi_events import get_event_bus

    if vehicle_id is None:
        if _EMITTER is None:
            _EMITTER = UiPolicyEmitter(get_event_bus())
        return _EMITTER
    emitter = _EMITTERS.get(vehicle_id)
    if emitter is None:
        emitter = UiPolicyEmitter(get_event_bus(), vehicle_id=vehicle_id)
        _EMITTERS[vehicle_id] = emitter
    return emitter


def reset_ui_policy_emitters() -> None:
    """Chỉ dùng trong test — xem `UiPolicyEmitter.reset` về việc `_last` rò qua test."""
    global _EMITTER
    _EMITTER = None
    _EMITTERS.clear()

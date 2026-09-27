"""Bánh cóc: số lần đọc websocket **không deadline** trong `tests/` chỉ được phép giảm.

## Vì sao cần một test cho chuyện này

`CLAUDE.md` đã ghi thành luật từ 2026-08-11:

> *Every websocket read in a test needs a deadline. `TestClient.receive_json()` is
> `portal.call(...)` and blocks with no timeout, so one missing event hangs pytest
> forever instead of failing.*

Luật ấy được viết ra vì đã có người trả giá. Nhưng nó là **văn bản**, nên nó không
chặn được ai — và ngày 16/08 nó bị trả giá lần nữa, hai lần trong một buổi sáng:

| run | treo ở | hậu quả |
|---|---|---|
| `31918785446` | `test_forwards_published_events_for_the_connected_session` | job bị cắt sau 15 phút |
| `31921801081` | `test_replay_delivers_missed_events_after_reconnect_with_a_valid_cursor` | job bị cắt sau 15 phút |

Cả hai lần, log **im lặng gần 12 phút** rồi `##[error]The operation was canceled.`
Trạng thái GitHub chỉ nói *"Some checks haven't completed yet"* — không một chữ nào về
việc có test đang đứng. Phải đối chiếu dấu thời gian trong log mới tìm ra.

Chi phí thật: hai vòng CI, cộng thời gian ba người đi tìm.

## Vì sao là bánh cóc chứ không phải cấm tuyệt đối

Còn `_SO_CHO_CON_LAI` chỗ đọc trần trong `tests/`, và không phải chỗ nào cũng sai: test
mong đợi server **đóng** kết nối thì `receive_json()` ném `WebSocketDisconnect` ngay,
không treo. Sửa hết trong một lần vừa rủi ro vừa che mất thay đổi thật của PR.

Nên test này chỉ chốt **hướng đi**: số chỗ không được tăng. Ai thêm một lần đọc trần
mới sẽ thấy test đỏ kèm đúng dòng vừa thêm, ngay trên máy mình, thay vì để cả nhóm phát
hiện qua một job bị huỷ sau 15 phút.

Hạ được con số thì **hạ luôn hằng số** — đó là ý nghĩa của bánh cóc.
"""

import pathlib
import re

#: Đường đọc **có** deadline. `receive_n` bọc `anyio.fail_after`; đây là đường duy nhất
#: nên dùng khi test chờ một event thật.
_CO_DEADLINE = "receive_n"

#: Số chỗ đọc trần còn lại, đo ngày 2026-08-16. **Chỉ được giảm.**
_SO_CHO_CON_LAI = 25

_GOC_TESTS = pathlib.Path(__file__).resolve().parent.parent


def _doc_tran() -> list[str]:
    """Mọi lời gọi `receive_json()` không đi qua `receive_n`, kèm vị trí.

    Bỏ qua docstring và chú thích: chúng **nói về** vấn đề chứ không gây ra nó, và
    chính file này lẫn `ws_helpers.py` đều nhắc tên hàm ấy nhiều lần.
    """
    ket_qua: list[str] = []
    for f in sorted(_GOC_TESTS.rglob("*.py")):
        trong_docstring = False
        for so, dong in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            # Đếm `"""` để biết đang ở trong docstring — thô nhưng đủ cho các file test
            # ở đây, và sai theo hướng an toàn (bỏ sót thì con số chỉ nhỏ đi).
            if dong.count('"""') % 2 == 1:
                trong_docstring = not trong_docstring
                continue
            if trong_docstring:
                continue
            sach = dong.split("#", 1)[0]
            if re.search(r"\.receive_json\(\s*\)", sach) and _CO_DEADLINE not in sach:
                ket_qua.append(f"{f.relative_to(_GOC_TESTS.parent).as_posix()}:{so}: {dong.strip()}")
    return ket_qua


def test_so_cho_doc_websocket_khong_deadline_khong_duoc_tang():
    cho = _doc_tran()
    assert len(cho) <= _SO_CHO_CON_LAI, (
        f"Thêm {len(cho) - _SO_CHO_CON_LAI} lần đọc websocket không deadline.\n"
        f"Dùng `receive_n(ws, n)` (có `anyio.fail_after`) thay cho `ws.receive_json()`.\n"
        "Thiếu deadline thì một event vắng mặt làm TREO cả suite chứ không báo đỏ — "
        "đã tốn hai vòng CI ngày 16/08.\n\nCác chỗ hiện có:\n  " + "\n  ".join(cho)
    )


def test_ha_duoc_so_thi_phai_ha_luon_hang_so():
    """Bánh cóc chỉ có nghĩa khi hằng số bám sát thực tế.

    Không có test này thì `_SO_CHO_CON_LAI` sẽ nới dần ra khỏi con số thật, và một lần
    đọc trần mới có thể nấp trong khoảng chênh mà không ai thấy.
    """
    cho = _doc_tran()
    assert len(cho) == _SO_CHO_CON_LAI, (
        f"Còn {len(cho)} chỗ nhưng hằng số ghi {_SO_CHO_CON_LAI}. Sửa được thì hạ hằng số xuống đúng con số mới."
    )

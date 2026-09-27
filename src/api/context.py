"""Định danh cho mỗi request: `request_id` và `trace_id`.

`docs/api_spec.md:9`: *"`X-Trace-Id` is only a client correlation request; the
server validates it or generates a trace ID when absent."*

Hai chữ đáng chú ý là **only** và **validates**. Header của client là *đề nghị*,
không phải mệnh lệnh: header sai định dạng thì server tự sinh id mới chứ **không
trả 400** — hỏng tương quan log không phải lý do để hỏng cả request. Ngược lại,
nhận nguyên xi chuỗi client gửi cũng không được, vì trace_id đi thẳng vào log và
vào response: client có thể nhét newline để chèn dòng log giả, hoặc nhét chuỗi
dài để phình log.
"""

from __future__ import annotations

import re
import uuid

from fastapi import Request

#: Chỉ chữ, số và bốn ký tự phân tách thường gặp trong id tương quan
#: (`tr_client_login_001`, `4bf92f...-01`, `svc:trace:9`). Cố ý **không** cho
#: khoảng trắng và ký tự điều khiển — đó là đường chèn log.
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")

_TRACE_ID_HEADER = "X-Trace-Id"


def new_request_id() -> str:
    """Id của **một lần gọi**. Luôn do server sinh, client không can thiệp được."""
    return f"req_{uuid.uuid4().hex[:12]}"


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex[:12]}"


def resolve_trace_id(request: Request) -> str:
    """Trace id của client nếu hợp lệ, ngược lại sinh mới. Không bao giờ raise."""
    candidate = request.headers.get(_TRACE_ID_HEADER)
    if candidate is not None and _TRACE_ID_RE.match(candidate):
        return candidate
    return new_trace_id()


_SCOPED_IDS_ATTR = "_request_scoped_ids"


def request_scoped_ids(request: Request) -> tuple[str, str]:
    """`(request_id, trace_id)` dùng chung cho MỌI dependency và handler của
    cùng một request — tính một lần, cache vào `request.state`.

    Không dùng ở `resolve_trace_id`/`new_request_id` trực tiếp vì những route đã
    có từ trước (`GET /vehicle/state`) tự gọi hai hàm đó riêng lẻ và không cần đổi
    hành vi. Hàm này chỉ dành cho route/dependency mới cần nhiều tầng (auth
    dependency + handler) cùng nhìn thấy đúng một cặp id — thiếu nó thì mỗi tầng tự
    sinh id khác nhau, và một request bị dependency từ chối sớm sẽ mang id không
    khớp với id mà log ở tầng khác (nếu có) dùng, gây khó dò log xuyên tầng. Khi
    client không gửi `X-Trace-Id`, `resolve_trace_id` tự sinh ngẫu nhiên mỗi lần
    gọi — cache lại để tất cả các lần đọc trong cùng request thấy cùng giá trị.
    """
    cached = getattr(request.state, _SCOPED_IDS_ATTR, None)
    if cached is not None:
        return cached
    ids = (new_request_id(), resolve_trace_id(request))
    setattr(request.state, _SCOPED_IDS_ATTR, ids)
    return ids

"""src/api/context.py::request_scoped_ids — cache (request_id, trace_id) trên
`request.state` để mọi dependency/handler của cùng một request thấy đúng một cặp
id, thay vì mỗi tầng tự sinh id khác nhau."""

from starlette.requests import Request

from src.api.context import new_trace_id, request_scoped_ids


def _request(headers: dict[str, str] | None = None) -> Request:
    headers = headers or {}
    scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


def test_request_scoped_ids_returns_the_same_pair_on_repeated_calls_for_one_request():
    request = _request()
    first = request_scoped_ids(request)
    second = request_scoped_ids(request)
    assert first == second


def test_request_scoped_ids_honors_a_valid_client_trace_id():
    request = _request({"X-Trace-Id": "tr_client_scoped_001"})
    request_id, trace_id = request_scoped_ids(request)
    assert trace_id == "tr_client_scoped_001"
    assert request_id.startswith("req_")


def test_request_scoped_ids_differs_between_two_separate_requests():
    request_a = _request()
    request_b = _request()
    ids_a = request_scoped_ids(request_a)
    ids_b = request_scoped_ids(request_b)
    assert ids_a != ids_b


def test_new_trace_id_still_works_standalone_for_existing_callers():
    # GET /vehicle/state (routes.py) gọi new_trace_id()/resolve_trace_id() riêng lẻ,
    # không qua request_scoped_ids — xác nhận hàm cũ không bị đổi hành vi.
    a, b = new_trace_id(), new_trace_id()
    assert a.startswith("tr_") and b.startswith("tr_") and a != b

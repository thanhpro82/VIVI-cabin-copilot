"""Registry tool do server sở hữu.

`TOOL_ARGS` là allowlist canonical. Tên ở đây là tên **duy nhất** của mỗi tool
trong toàn hệ thống: candidate plan, `ActionPlan`, trace, và cả HTTP response.

Trước đây file này còn một bảng `ALIAS_BY_TOOL` ánh xạ sang tên nhóm của
`docs/VIVI_API_Spec.md` (`control_ac`, `control_music`…). Đã bỏ 2026-08-08: WS4
chốt dùng `docs/api_spec.md` làm nguồn sự thật duy nhất, nên bảng đó không còn
consumer nào. Giữ một bộ tên end-to-end — xem ADR-010 mục "Thu hồi phần adapter".
"""

from pydantic import BaseModel, ValidationError

from src.agents.contracts import ValidationDenied
from src.services.tool_registry import TOOL_REGISTRY

#: Tool mà **đường plan** được phép dựng — dẫn xuất từ `TOOL_REGISTRY`, không khai lại.
#:
#: Trước #325 đây là một dict viết tay song song với registry, mỗi tool một class Pydantic
#: riêng ở hai nơi, và không dòng nào bắt chúng khớp. Chúng đã lệch thật ở hai chỗ, và cả
#: hai đều **xanh test ở cả hai phía** vì không test nào so hai bên với nhau.
#:
#: Hai tool bị loại trừ **có chủ ý**, và đây là phần duy nhất còn khác giữa hai bảng:
#:
#: - `query_manual` — tra sổ tay là việc của node RAG, không phải một bước thực thi.
#: `search_nearby_poi` **đã rời danh sách này** ở issue #371, đúng điều kiện mà bản trước
#: của chú thích tự đặt ra: *"xoá khỏi danh sách này khi tool có executor + compose"*.
#: Nay nó có cả hai — `nodes/execute.py::_ket_qua_tim_poi` trả danh sách thật, và compose
#: đọc từ kết quả ấy chứ không tra fixture song song.
#:
#: Lý do phải sửa chứ không giữ nguyên: router **vẫn** sinh plan cho tool này ở nhánh số
#: nhiều (`router.py:1958`), nên việc loại trừ không chặn được gì — nó chỉ làm lượt chết
#: ở `validate_args` với `tool_not_allowed`, trong khi compose rẽ theo `intent` nên vẫn
#: đọc danh sách và vẫn hỏi *"Bạn muốn đi chỗ nào?"*. Lượt hỏng mà nghe như thành công là
#: trạng thái tệ hơn cả hai đầu của lựa chọn ban đầu.
#:
#: Danh sách chỉ được **ngắn đi**; `tests/test_agents/test_hai_bang_args.py` khoá điều đó.
KHONG_CHO_DUONG_PLAN: frozenset[str] = frozenset({"query_manual"})

#: Allowlist canonical của đường plan. Tên ở đây là tên **duy nhất** của mỗi tool trong
#: toàn hệ thống: candidate plan, `ActionPlan`, trace, và cả HTTP response.
TOOL_ARGS: dict[str, type[BaseModel]] = {
    ten: spec.args_model for ten, spec in TOOL_REGISTRY.items() if ten not in KHONG_CHO_DUONG_PLAN
}


#: Loại lỗi Pydantic báo hiệu giá trị nằm ngoài khoảng cho phép.
_RANGE_ERROR_TYPES = {
    "greater_than",
    "greater_than_equal",
    "less_than",
    "less_than_equal",
}


def validate_args(tool: str, args: dict) -> BaseModel:
    """Validate args của một tool. Raise `ValidationDenied` kèm subcode chính xác.

    Đây là bước chạy **trước** phân loại S0–S3: tool lạ, sai schema hay ngoài
    khoảng đều không phải S3 (`docs/safety_and_hitl.md` mục Classification rules).
    """
    model = TOOL_ARGS.get(tool)
    if model is None:
        raise ValidationDenied("tool_not_allowed", f"tool không nằm trong allowlist: {tool}")
    try:
        return model.model_validate(args)
    except ValidationError as exc:
        subcode = "range_invalid" if any(e["type"] in _RANGE_ERROR_TYPES for e in exc.errors()) else "args_invalid"
        raise ValidationDenied(subcode, f"args không hợp lệ cho {tool}: {_mo_ta_loi(exc)}") from exc


def _mo_ta_loi(exc: ValidationError) -> str:
    """Lỗi pydantic thành một dòng, **kèm tên field**.

    Bản trước chỉ lấy `errors()[0]["msg"]`, nên `set_hvac_power` nhận `{"power":"off"}`
    báo về đúng ba chữ *"Field required"* — không nói field nào. Với người đọc trace thì
    còn đoán được; với vòng sửa của planner (`graph._cau_sua_loi`) thì đó là một thông
    điệp rỗng: model không biết phải thêm gì nên nó trả lại y hệt (đo 26/08, Qwen3-4B,
    hỏng 2/2 lần).

    Chỉ lấy lỗi ĐẦU TIÊN, có chủ ý: một câu ngắn sửa được một chỗ vẫn hơn một danh sách
    dài không ai đọc, và args của tool trong repo này nhiều nhất ba field.
    """
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err["loc"])
    return f"{loc}: {err['msg']}" if loc else err["msg"]

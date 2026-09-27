"""Chỉ còn **một** định nghĩa args cho mỗi tool. Issue #325.

## Chuyện đã xảy ra

Repo từng có **hai** bảng args cho cùng một tập tool, mỗi tool hai class Pydantic riêng:

- `src.agents.tools.TOOL_ARGS` — cổng `validate_args`, chạy trên plan **trước** policy;
- `src.services.tool_registry.TOOL_REGISTRY` — `domain` / `safety` / topic MQTT.

Một plan phải qua **cả hai**, và không dòng code nào bắt chúng khớp. Chúng đã lệch thật,
đo 27/08:

```
search_nearby_poi : có trong registry (kèm args_model) — KHÔNG có trong TOOL_ARGS
                    -> một plan gọi nó chết ở `tool_not_allowed`
set_navigation    : registry nhận `destination_ref`, bản plan-layer từ chối nó
```

Lớp lỗi ấy **xanh test ở cả hai phía**, vì không test nào so hai bên với nhau. Nó đã cắn
một lần rồi: `play_track` từng chỉ có ở bản registry và lượt chết giữa đường với
`validation_denied` (ghi trong docstring `src/agents/tools/media.py` trước #325).

## Cách sửa, và hai chỗ **cố ý** vẫn khác

Registry là nơi khai duy nhất; `TOOL_ARGS` **dẫn xuất** từ nó, và mọi module dưới
`src/agents/tools/` chỉ tái xuất. Nên hai bảng không thể lệch *hình dạng* nữa — chúng
dùng chung đúng một object class.

Thứ còn khác là **allowlist**, và đó là thiết kế chứ không phải trôi: `query_manual` và
`search_nearby_poi` bị loại khỏi đường plan (xem `KHONG_CHO_DUONG_PLAN`). Một cái là
việc của RAG; cái kia chưa có executor thật nên cho vào allowlist sẽ khiến plan báo xong
trong khi chưa làm gì.

Hợp nhất theo bên **chặt hơn**, không phải bên rộng hơn: `destination_ref` bị bỏ khỏi
registry vì nó chỉ dẫn tới một cái chết muộn ở simulator, trong khi bản plan-layer từ
chối ngay ở `validate_args` — và bên từ chối mới là bên đúng.
"""

from __future__ import annotations

import pytest

from src.agents.tools import KHONG_CHO_DUONG_PLAN, TOOL_ARGS
from src.agents.tools import validate_args as validate_args_plan
from src.services.tool_registry import TOOL_REGISTRY
from src.services.tool_registry import validate_args as validate_args_registry


def test_moi_tool_cua_duong_plan_dung_chung_class_voi_registry():
    """Phép kiểm mạnh nhất, và là thứ thay chỗ mọi phép so hình dạng: **cùng một object**.

    So `model_json_schema()` chỉ chứng minh hai bảng *đang* giống nhau; `is` chứng minh
    chúng **không thể** khác nhau. Một dòng `class ... (BaseModel)` mới ở
    `src/agents/tools/` sẽ làm test này đỏ ngay, không cần ai nhớ so lại.
    """
    for ten, model in TOOL_ARGS.items():
        assert ten in TOOL_REGISTRY, f"{ten} qua được validate_args mà registry không biết"
        assert model is TOOL_REGISTRY[ten].args_model, f"{ten} có hai class khác nhau"


def test_khong_con_lech_nao_giua_hai_bang():
    """`LECH_DA_BIET` của bản trước có hai mục; nay phải rỗng.

    Test này là chỗ ghi rằng #325 đã đóng, và nó đỏ nếu ai đó tái lập một bảng song song.
    """
    lech = [ten for ten in TOOL_ARGS if TOOL_ARGS[ten] is not TOOL_REGISTRY[ten].args_model]
    assert lech == []


def test_tool_bi_loai_khoi_duong_plan_la_co_y_va_danh_sach_chi_duoc_ngan_di():
    """Phần duy nhất còn khác giữa hai bảng — và nó phải có người ký, không phải trôi.

    Thêm một tool vào `KHONG_CHO_DUONG_PLAN` là quyết định *"tool này không được xuất
    hiện trong plan"*; bớt một tool là quyết định *"tool này nay có đường thực thi thật"*.
    Cả hai đều phải đọc test này trước.

    `search_nearby_poi` **rời danh sách** ở #371 — đúng lần "bớt một tool" mà test này
    sinh ra để bắt. Điều kiện được thoả thật, không phải nới cho tiện: nó có executor
    (`nodes/execute.py::_ket_qua_tim_poi`, trả danh sách trong `after`), có phân loại an
    toàn (`policy._S0_TOOLS` — chỉ đọc), và composer nay dựng câu **từ kết quả ấy** chứ
    không tra fixture song song.

    Việc loại trừ cũ không chặn được gì: router vẫn sinh plan cho tool này, nên nó chỉ
    biến lượt thành `validation_denied` trong khi composer vẫn đọc danh sách — lượt hỏng
    mà nghe như thành công.
    """
    assert KHONG_CHO_DUONG_PLAN == {"query_manual"}
    assert KHONG_CHO_DUONG_PLAN <= set(TOOL_REGISTRY)
    assert not (KHONG_CHO_DUONG_PLAN & set(TOOL_ARGS))


@pytest.mark.parametrize("ten", sorted(KHONG_CHO_DUONG_PLAN))
def test_tool_bi_loai_van_bi_tu_choi_o_duong_plan(ten):
    """Hệ quả cụ thể của việc loại trừ, viết ra để nó không đổi trong im lặng."""
    from src.agents.contracts import ValidationDenied

    with pytest.raises(ValidationDenied) as loi:
        validate_args_plan(ten, {})
    assert loi.value.subcode == "tool_not_allowed"


# --- destination_ref: hợp nhất theo bên chặt hơn --------------------------------


def test_destination_ref_bi_tu_choi_o_ca_hai_cong():
    """Trước #325 registry **nhận** `destination_ref` rồi để simulator ném lỗi.

    Chết muộn — sau khi đã qua validate, safety và có thể cả HITL — với một thông điệp
    (`"destination_ref phải được resolve trước khi tới simulator"`) mà tài xế không đọc
    được. Bản plan-layer từ chối ngay, và đó là hành vi đúng; nay cả hai cùng từ chối.
    """
    args = {"operation": "start", "destination_ref": {"from_step_id": "s0", "selection": "first"}}
    from src.agents.contracts import ValidationDenied
    from src.services.tool_registry import InvalidArgumentsError

    with pytest.raises(ValidationDenied) as loi:
        validate_args_plan("set_navigation", args)
    assert loi.value.subcode == "args_invalid"

    with pytest.raises(InvalidArgumentsError):
        validate_args_registry("set_navigation", args)


def test_dan_duong_binh_thuong_van_chay_qua_ca_hai_cong():
    """Đối chứng: không có nó thì hai assert ở trên có thể xanh vì cổng chặn tất cả."""
    for args in ({"operation": "start", "destination_id": "poi-cafe-02"}, {"operation": "cancel"}):
        validate_args_plan("set_navigation", args)
        validate_args_registry("set_navigation", args)


# --- tool đọc: hết ngoại lệ `args_model=None` -----------------------------------


@pytest.mark.parametrize("ten", ["get_vehicle_state", "query_manual"])
def test_tool_khong_tham_so_van_co_model_that(ten):
    """`args_model=None` là một ngoại lệ mà **mọi** chỗ đọc registry phải nhớ xử lý riêng,
    và nó chính là mầm của cái lệch này: `src/agents/tools` từng phải tự khai một
    `GetVehicleStateArgs` của riêng mình chỉ vì registry để `None` ở đó."""
    assert TOOL_REGISTRY[ten].args_model is not None
    validate_args_registry(ten, {})

    from src.services.tool_registry import InvalidArgumentsError

    with pytest.raises(InvalidArgumentsError):
        validate_args_registry(ten, {"gi_do": 1})

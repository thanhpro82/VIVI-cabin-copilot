"""Routine (chuỗi 1–4 hành động do người dùng lưu) → `CandidateActionPlan`.

Issue #288, dưới outcome #275 của epic Routines MVP (#270).

## Ranh giới, vì nó quyết mọi thứ trong file

Module này **chỉ dịch**. Nó không gán safety (đó là `policy.py` — bất biến ADR-006),
không authorize, không chạm DB, không phát MQTT. Đầu vào là một Routine **đã được BE
xác thực và resolve**; đầu ra là `CandidateActionPlan` — loại plan không có trường an
toàn, đúng loại mà router và SLM cũng chỉ được phép sinh ra.

## Nguồn của hình dạng đầu vào

`frontend/src/lib/services/routines/types.ts` (#271). Hôm nay đó là contract **duy
nhất** đang tồn tại cho `RoutineStep`: #272/#282 sẽ thay bằng bản BE có persistence và
ownership. Khi ấy chỉ `_DICH` phải đổi, phần còn lại của file không biết gì về nguồn.

Nói rõ để không ai tưởng đây là suy đoán: bản FE ghi thẳng trong docstring rằng tên
action đặt khớp tool canonical của `tool_registry.py` để "#274 nối vào không phải đổi
tên gì". File này là đầu kia của mối nối ấy.

## Vì sao một bảng dịch tường minh, không phải một vòng lặp thông minh

`hvac_temperature` → `set_hvac_temperature` và `temperatureC` → `temperature_c` trông
như hai phép biến đổi máy làm được (thêm tiền tố `set_`, đổi camelCase sang snake_case).
Cả hai đều **sai ở ít nhất một mục**: `media_control` không có tiền tố `set_`, và
`controlAction` không đổi thành `control_action` mà thành `action`. Một vòng lặp thông
minh sẽ đúng 7/9 và sai hai chỗ không ai nhìn ra — bảng tường minh thì sai chỗ nào cũng
đọc thấy ngay ở diff.
"""

from __future__ import annotations

from typing import Any

from src.agents.contracts import CandidateActionPlan, CandidateStep

#: Epic #270 chốt: mỗi Routine 1–4 hành động.
MAX_BUOC = 4

#: camelCase của FE → giá trị enum canonical. Cả hai bảng đều là danh sách ĐÓNG: một
#: giá trị lạ phải nổ thành lỗi có cấu trúc, không được lọt xuống `validate_args` dưới
#: dạng một chuỗi trông-như-thật.
_CUA_SO = {
    "frontLeft": "front_left",
    "frontRight": "front_right",
    "rearLeft": "rear_left",
    "rearRight": "rear_right",
}
_GHE_TRUOC = {"frontLeft": "front_left", "frontRight": "front_right"}


class RoutineDichError(Exception):
    """Không dịch được, kèm **mã** để tầng trên chọn lời thoại mà không phải đọc chuỗi.

    Có `ma` riêng chứ không chỉ một câu tiếng Việt, vì cùng một lỗi phải nói khác nhau ở
    hai chỗ: câu đọc cho tài xế nghe, và mã ghi vào trace cho kỹ sư đọc. Trộn hai thứ
    vào một chuỗi là cách chắc chắn để một trong hai bị hy sinh.
    """

    def __init__(self, ma: str, thong_diep: str) -> None:
        super().__init__(thong_diep)
        self.ma = ma


def _so_nguyen(gia_tri: Any, ten: str) -> int:
    """Chặn cả `bool` — `isinstance(True, int)` là True trong Python, nên không có dòng
    này thì `{"level": True}` lọt xuống thành mức quạt 1."""
    if isinstance(gia_tri, bool) or not isinstance(gia_tri, int):
        raise RoutineDichError("gia_tri_khong_hop_le", f"{ten} phải là số nguyên, nhận {gia_tri!r}")
    return gia_tri


def _tra_bang(bang: dict[str, str], khoa: Any, ten: str) -> str:
    if khoa not in bang:
        raise RoutineDichError("gia_tri_khong_hop_le", f"{ten} không hợp lệ: {khoa!r}")
    return bang[khoa]


def _co(buoc: dict, ten: str) -> bool:
    if not isinstance(buoc.get(ten), bool):
        raise RoutineDichError("gia_tri_khong_hop_le", f"{buoc.get('action')} cần `{ten}` kiểu bool")
    return buoc[ten]


def _hvac_power(buoc: dict) -> tuple[str, dict]:
    return "set_hvac_power", {"enabled": _co(buoc, "enabled")}


def _hvac_temperature(buoc: dict) -> tuple[str, dict]:
    return "set_hvac_temperature", {"temperature_c": _so_nguyen(buoc.get("temperatureC"), "temperatureC")}


def _hvac_fan_level(buoc: dict) -> tuple[str, dict]:
    return "set_hvac_fan_level", {"level": _so_nguyen(buoc.get("level"), "level")}


def _media_control(buoc: dict) -> tuple[str, dict]:
    """`volume` chỉ được đi cùng `set_volume` — `MediaControlArgs` CẤM nó ở action khác.

    Bỏ field thừa ngay tại đây thay vì đẩy xuống cho validator từ chối: một Routine lưu
    kèm `volume` từ lần sửa trước là dữ liệu cũ hợp lý, không phải lỗi của người dùng,
    và biến nó thành một lượt hỏng là đổ lỗi sai chỗ.
    """
    action = buoc.get("controlAction")
    args: dict[str, Any] = {"action": action}
    if action == "set_volume":
        args["volume"] = _so_nguyen(buoc.get("volume"), "volume")
    return "media_control", args


def _window_position(buoc: dict) -> tuple[str, dict]:
    return "set_window_position", {
        "window": _tra_bang(_CUA_SO, buoc.get("window"), "window"),
        "percent": _so_nguyen(buoc.get("percent"), "percent"),
    }


def _seat_heating(buoc: dict) -> tuple[str, dict]:
    return "set_seat_heating", {
        "seat": _tra_bang(_GHE_TRUOC, buoc.get("seat"), "seat"),
        "level": _so_nguyen(buoc.get("level"), "level"),
    }


def _seat_position(buoc: dict) -> tuple[str, dict]:
    return "set_seat_position", {
        "seat": _tra_bang(_GHE_TRUOC, buoc.get("seat"), "seat"),
        "axis": buoc.get("axis"),
        "value": _so_nguyen(buoc.get("value"), "value"),
    }


def _interior_light(buoc: dict) -> tuple[str, dict]:
    return "set_interior_light", {"enabled": _co(buoc, "enabled")}


def _navigation(buoc: dict, dia_diem: dict[str, str] | None = None) -> tuple[str, dict]:
    """Nhãn cá nhân → `destination_id` **đã resolve**. Chưa gán thì lỗi, không đoán.

    **Đoán ở đây là chỗ nguy hiểm nhất trong file.** Lấy đại một POI trong fixture để
    "chạy được demo" nghĩa là dẫn tài xế tới một chỗ họ không hề bảo — và vì
    `set_navigation` là S1, nó đi qua mà không cần ai duyệt.

    `dia_diem` do người gọi truyền vào (`#283`: `user_places.resolve` cho từng nhãn),
    không tự tra ở đây: module này **chỉ dịch** và không chạm DB — cùng ranh giới đã ghi
    ở đầu file. Truyền `None` (đường cũ, chưa có ngữ cảnh user) thì mọi bước dẫn đường
    đều là lỗi, đúng như trước.
    """
    nhan = buoc.get("destination")
    dich = (dia_diem or {}).get(str(nhan))
    if not dich:
        raise RoutineDichError(
            "dia_diem_ca_nhan_chua_co",
            f"chưa đặt địa điểm {nhan!r} của người dùng",
        )
    return "set_navigation", {"operation": "start", "destination_id": dich}


#: Bảng dịch — danh sách ĐÓNG, khớp `RoutineStep` của `types.ts`.
_DICH = {
    "hvac_power": _hvac_power,
    "hvac_temperature": _hvac_temperature,
    "hvac_fan_level": _hvac_fan_level,
    "media_control": _media_control,
    "window_position": _window_position,
    "seat_heating": _seat_heating,
    "seat_position": _seat_position,
    "interior_light": _interior_light,
    "navigation": _navigation,
}


#: Hai nhãn địa điểm cá nhân của `routines_product_spec.md` §Nhà và Cơ quan. Tập đóng —
#: người dùng không đặt thêm nhãn thứ ba, và `types.ts` khai đúng hai giá trị này.
DESTINATION_HOP_LE: frozenset[str] = frozenset({"home", "office"})


def mo_ta_buoc_routine(buoc: dict) -> str:
    """Mô tả một bước đã lưu để preview mà không cần resolve địa điểm cá nhân."""
    action = str(buoc.get("action") or "")
    if action == "navigation":
        ten_dich = {"home": "Nhà", "office": "Cơ quan"}.get(
            str(buoc.get("destination") or ""), str(buoc.get("destination") or "")
        )
        return f"dẫn đường tới {ten_dich}"

    dich = _DICH.get(action)
    if dich is None:
        return f"thực hiện {action}"
    tool, args = dich(buoc)
    from src.agents.nodes.compose import describe_step

    return describe_step(tool, args)


def kiem_tra_buoc(steps: list[dict]) -> None:
    """Validate một chuỗi bước **lúc lưu**. Ném `RoutineDichError`, không trả gì.

    ## Vì sao tách khỏi `routine_thanh_candidate`

    Hai phép kiểm khác nhau ở đúng một chỗ, và chỗ ấy quan trọng: `navigation`.

    Lúc **chạy**, một bước dẫn đường chưa resolve được địa điểm là lỗi — `_navigation`
    ném, và nó phải ném, vì đoán một POI nghĩa là chở tài xế tới chỗ họ không bảo.

    Lúc **lưu** thì ngược lại: Routine *"Đi làm"* có bước dẫn đường Cơ quan và người
    dùng chưa gán địa điểm là chuyện **bình thường** — spec chốt Routine ấy hiển thị
    "Cần thiết lập" chứ không phải bị từ chối lưu. Dùng `routine_thanh_candidate` để
    validate lúc lưu sẽ làm cả ba mẫu mặc định không bootstrap nổi.

    ## Vì sao gọi `validate_args` chứ không tự kiểm dải

    `_DICH` chỉ kiểm **kiểu** (`temperatureC` có phải số nguyên không), không kiểm
    **dải** (16–30). Dải sống ở `tool_registry` và chỉ nên sống ở đó; chép nó vào đây
    là dựng nguồn sự thật thứ hai, rồi hai bản lệch nhau đúng vào ngày ADR-019 kiểu
    "quạt gió từ 0–3 lên 0–4" được duyệt. Nên bước được dịch thật rồi đưa qua đúng
    validator mà executor sẽ dùng — thứ lưu được là thứ chạy được.
    """
    if not steps:
        raise RoutineDichError("routine_rong", "Routine không có bước nào")
    if len(steps) > MAX_BUOC:
        raise RoutineDichError("qua_nhieu_buoc", f"Routine có {len(steps)} bước, tối đa {MAX_BUOC}")

    from src.services.tool_registry import InvalidArgumentsError, validate_args

    for buoc in steps:
        if not isinstance(buoc, dict):
            raise RoutineDichError("gia_tri_khong_hop_le", f"bước phải là object, nhận {buoc!r}")
        action = buoc.get("action")
        if action == "navigation":
            dich_den = buoc.get("destination")
            if dich_den not in DESTINATION_HOP_LE:
                raise RoutineDichError(
                    "gia_tri_khong_hop_le",
                    f"destination không hợp lệ: {dich_den!r}; hợp lệ: home|office",
                )
            continue
        dich = _DICH.get(action)
        if dich is None:
            raise RoutineDichError("action_khong_ho_tro", f"hành động không hỗ trợ: {action!r}")
        tool, args = dich(buoc)
        try:
            validate_args(tool, args)
        except InvalidArgumentsError as exc:
            raise RoutineDichError("gia_tri_ngoai_dai", f"{action}: {exc}") from exc


def routine_thanh_candidate(
    steps: list[dict], *, dia_diem: dict[str, str] | None = None
) -> CandidateActionPlan:
    """Chuỗi bước của một Routine → `CandidateActionPlan`, giữ nguyên thứ tự.

    `dia_diem` là ánh xạ nhãn cá nhân → `destination_id` **đã kiểm hợp lệ**, do người gọi
    dựng từ `user_places` (#283). Không tra DB ở đây: module này chỉ dịch.

    Thứ tự là **ngữ nghĩa**, không phải trình bày: epic chốt fail-fast, nên bước nào
    đứng trước thì chạy trước và một lỗi ở giữa để lại đúng phần đã chạy.

    Một bước hỏng thì **cả** phép dịch hỏng, không giao plan một nửa. Fail-fast của epic
    nói về lúc *thực thi*; lúc *dịch* thì một Routine dịch được một nửa là một Routine
    khác với thứ người dùng lưu, và im lặng giao nửa ấy đi tiếp là tự quyết hộ họ.
    """
    if not steps:
        # Plan 0 bước đi hết safety rồi executor và "thành công" mà không làm gì —
        # một lượt báo xong trong khi chưa làm gì cả.
        raise RoutineDichError("routine_rong", "Routine không có bước nào")
    if len(steps) > MAX_BUOC:
        raise RoutineDichError("qua_nhieu_buoc", f"Routine có {len(steps)} bước, tối đa {MAX_BUOC}")

    ket: list[CandidateStep] = []
    for thu_tu, buoc in enumerate(steps):
        action = buoc.get("action")
        dich = _DICH.get(action)
        if dich is None:
            raise RoutineDichError("action_khong_ho_tro", f"hành động không hỗ trợ: {action!r}")
        tool, args = dich(buoc, dia_diem) if action == "navigation" else dich(buoc)
        ket.append(CandidateStep(step_id=f"step-{thu_tu + 1}", ordinal=thu_tu, tool=tool, args=args))
    return CandidateActionPlan(steps=tuple(ket))

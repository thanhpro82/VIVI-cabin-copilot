"""Danh sách tool trong prompt planner phải **sinh ra từ** `TOOL_REGISTRY`, không viết tay.

Đo trên `develop` @ `170c943` (26/08), lúc còn viết tay:

    prompt kê 9 tool; registry có 16
    THIẾU trong prompt: set_headlight_mode, set_interior_light, set_hvac_fan_level,
                        set_trunk_state, search_nearby_poi, open_app, ...
    KHÔNG TỒN TẠI trong registry: search_nearby

Hệ quả đo được, chạy graph thật với Qwen3-4B: planner chỉ dựng đúng args cho **3** tool
— đúng ba tool có ví dụ trong prompt. Còn lại trả JSON hợp lệ cú pháp nhưng sai schema
args, và lượt ấy chết ở `clarify` với câu *"Bạn muốn điều chỉnh cụ thể như thế nào?"*:

    'tắt điều hòa'      -> set_hvac_power {"power":"off"}   ❌ thật ra là `enabled: bool`
    'bật đèn trần lên'  -> media_control {"action":"set_light"}  ❌ sai cả tool lẫn enum

Ca đầu đáng chú ý nhất: `"tắt điều hòa"` là câu lệnh trần trụi nhất có thể — planner
**không dựng nổi** một lời gọi `set_hvac_power` hợp lệ ở bất kỳ câu nào.

Nguyên nhân gốc: danh sách và bộ ví dụ là **chuỗi viết tay**. Mọi PR thêm tool (#65
`lights`/`trunk`, SP-5 `search_nearby_poi`) đều xanh test mà prompt không đổi, và không
có gì phát hiện ra. Xem issue #269.
"""

from __future__ import annotations

import json
import re

import pytest

from src.agents.slm import PLANNER_TOOLS, SLM_UNION_PROMPT, mo_ta_args, ten_tool_trong_prompt
from src.agents.tools import TOOL_ARGS
from src.agents.tools import validate_args as validate_args_planner
from src.services.tool_registry import TOOL_REGISTRY

#: Tool mà planner được phép dựng. Lấy từ `TOOL_ARGS` — bảng của chính `validate_args`,
#: tức cổng mà chuỗi model trả về đâm vào đầu tiên — giao với `TOOL_REGISTRY` để cái gì
#: kê ra cũng có đường thực thi, trừ hai tool ĐỌC do router/RAG lo.
TOOL_PLANNER_DUOC_PHEP = set(PLANNER_TOOLS)


def test_moi_ten_trong_prompt_deu_co_that_trong_registry():
    """Chiều bắt `search_nearby` — một cái tên không tồn tại, prompt đang dạy model gọi."""
    la = ten_tool_trong_prompt(SLM_UNION_PROMPT) - set(TOOL_REGISTRY)
    assert la == set(), f"prompt kê tool không có trong registry: {sorted(la)}"


def test_moi_tool_planner_duoc_phep_deu_co_mat_trong_prompt():
    """Chiều bắt 5 actuator bị giấu — `lights`/`trunk` của #65 và `search_nearby_poi`
    của SP-5 chưa bao giờ vào prompt, nên model không biết chúng tồn tại."""
    thieu = TOOL_PLANNER_DUOC_PHEP - ten_tool_trong_prompt(SLM_UNION_PROMPT)
    assert thieu == set(), f"tool có trong registry mà prompt giấu: {sorted(thieu)}"


def test_hai_tool_doc_co_y_dung_ngoai():
    """Không phải sót: `get_vehicle_state`/`query_manual` do router và RAG lo. Cho
    planner sinh chúng thành một bước thực thi là mở một đường không ai thiết kế."""
    trong_prompt = ten_tool_trong_prompt(SLM_UNION_PROMPT)
    for tool in ("get_vehicle_state", "query_manual"):
        assert tool in TOOL_REGISTRY
        assert tool not in trong_prompt


def test_moi_tool_duoc_ke_deu_qua_duoc_ca_hai_cong():
    """Điều kiện thật sự quan trọng, và là lý do prompt lấy từ `TOOL_ARGS` chứ không từ
    `TOOL_REGISTRY`: một plan phải qua `validate_args` (đường planner) TRƯỚC, rồi mới
    tới registry (safety + topic MQTT). Kê một tool chỉ có ở một bên là tự tạo ra một
    lượt hỏng có bảo hành."""
    for tool in ten_tool_trong_prompt(SLM_UNION_PROMPT):
        assert tool in TOOL_ARGS, f"{tool} không qua được validate_args của đường planner"
        assert tool in TOOL_REGISTRY, f"{tool} không có trong registry — không có đường thực thi"


@pytest.mark.parametrize("tool", sorted(TOOL_PLANNER_DUOC_PHEP))
def test_moi_tool_co_dong_mo_ta_args_neu_ten_khong_du(tool):
    """Chỉ liệt kê TÊN là không đủ, và đó là điều đo được: `set_hvac_power` **có** trong
    danh sách tên của prompt cũ mà model vẫn trả `{"power":"off"}`.

    Cái model thiếu là **hình dạng args**. Nên mỗi tool phải kèm một dòng mô tả, và dòng
    ấy phải nêu đủ các field bắt buộc — nếu không thì nó chỉ là trang trí.
    """
    dong = mo_ta_args(tool)
    assert dong, f"{tool} không có dòng mô tả args"
    assert dong in SLM_UNION_PROMPT, f"dòng mô tả của {tool} không nằm trong prompt"

    bat_buoc = TOOL_ARGS[tool].model_json_schema().get("required", [])
    for field in bat_buoc:
        assert field in dong, f"{tool}: dòng mô tả thiếu field bắt buộc {field!r} — {dong}"


def test_moi_vi_du_trong_prompt_deu_qua_duoc_validate_args():
    """Ví dụ few-shot là thứ model bắt chước sát nhất, nên một ví dụ sai schema là một
    lỗi được dạy. Bóc mọi step trong prompt ra và cho đi qua đúng `validate_args` mà
    `validate_node` dùng."""
    steps = re.findall(r'\{"step_id".*?"depends_on":\[\]\}', SLM_UNION_PROMPT)
    # Dòng khuôn mẫu ở đầu prompt (`"tool":"<tool>"`, `"args":{...}`) không phải ví dụ
    # và cố ý không phải JSON hợp lệ — nó dạy HÌNH DẠNG, không dạy nội dung.
    steps = [raw for raw in steps if '"<tool>"' not in raw]
    assert len(steps) >= 4, f"chỉ bóc được {len(steps)} ví dụ — regex lệch với prompt"
    for raw in steps:
        step = json.loads(raw)
        validate_args_planner(step["tool"], step["args"])


# --- Ví dụ few-shot: đủ tool, và KHÔNG được trùng bộ đo -------------------------


#: Năm tool bị model chọn SAI ở cả hai mốc đo của #269
#: (`planner-args/20260826T104904.749418Z` và `...104928.430106Z`).
TOOL_TUNG_BI_CHON_SAI = {
    "set_hvac_fan_level",
    "set_interior_light",
    "set_headlight_mode",
    "set_trunk_state",
    "open_app",
}


def test_ket_qua_am_tinh_them_vi_du_few_shot_khong_sua_duoc_lua_chon_tool():
    """Ghi lại một thứ **đã thử và không được**, để không ai thử lại.

    Giả thuyết hợp lý: năm tool bị chọn sai đúng là năm tool không có ví dụ few-shot,
    nên cấp cho mỗi cái một ví dụ (cách nói khác hẳn ca đo, để không dạy vào đề thi).
    Đo lại trên cùng máy cùng model: **tool đúng đứng yên 11/16**, y hệt năm ca cũ
    (`planner-args/20260827T000533.480803Z`). Ví dụ đã được gỡ lại — prompt dài thêm
    ~900 ký tự mà không mua được gì là một cái giá không có lý do.

    Kết luận đo được: bảng args sửa được **hình dạng**; **lựa chọn tool** thì prompt
    không sửa nổi ở kích cỡ model này, nên nó cần một cổng tất định (`cong_mien_slm`).
    """
    from src.agents.slm import SLM_UNION_PROMPT

    van_thieu = [t for t in sorted(TOOL_TUNG_BI_CHON_SAI) if f'"tool":"{t}"' not in SLM_UNION_PROMPT]
    assert van_thieu == sorted(TOOL_TUNG_BI_CHON_SAI), (
        "ví dụ few-shot cho năm tool ấy đã quay lại — nếu có bằng chứng mới thì sửa cả "
        "docstring này kèm run id, đừng chỉ thêm ví dụ"
    )


def test_vi_du_khong_duoc_trung_nguyen_van_ca_trong_bo_do():
    """Dạy vào đề thi: một ví dụ trùng nguyên văn ca đo thì con số sau đó chỉ chứng minh
    model biết chép lại ví dụ.

    Bắt được ở chính PR này — bản đầu của `_VI_DU_BO_SUNG` dùng `"Bật đèn trần lên"` và
    `"Bật đèn chiếu gần"`, trùng hai ca của `planner-args`.
    """
    from scripts.do_planner_args import CA
    from src.agents.slm import SLM_UNION_PROMPT

    thap = SLM_UNION_PROMPT.lower()
    trung = [cau for _, cau in CA if cau.lower() in thap]
    assert trung == [], f"prompt chép nguyên văn ca của bộ đo: {trung}"

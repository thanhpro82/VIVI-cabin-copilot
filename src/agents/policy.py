"""Policy an toàn — điểm **duy nhất** trong hệ thống được gán `safety_level`.

Router và SLM chỉ sinh `CandidateActionPlan`. Không node nào khác được import
`ActionPlan` để tự dựng. Bảng dưới đây ánh xạ trực tiếp
`docs/safety_and_hitl.md` mục "Classification rules".

Lưu ý về ngưỡng tốc độ: ticket của sprint đề xuất `speed_kph > 5` làm điều
kiện kích hoạt xác nhận. Ngưỡng đó **không** được implement ở đây; xem ADR-010
để biết vì sao (nó vừa lỏng hơn canonical ở cửa sổ, vừa nguy hiểm hơn ở cửa xe).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.agents.contracts import ActionPlan, CandidateActionPlan, PlanStep, SafetyLevel
from src.agents.tools import TOOL_ARGS

#: S0 = **chỉ đọc**. `search_nearby_poi` vào đây ở #371 cùng lúc với executor thật của
#: nó: tìm địa điểm không chạm actuator nào, không publish MQTT, không đổi một bit trạng
#: thái xe nào — nó đọc fixture rồi trả danh sách. Xếp nó S1 sẽ nói rằng có một hành
#: động vừa xảy ra trên xe, mà không có.
_S0_TOOLS = {"get_vehicle_state", "search_nearby_poi"}
_S1_TOOLS = {
    "set_hvac_power",
    "set_hvac_temperature",
    "set_hvac_fan_level",
    "set_seat_heating",
    "media_control",
    "set_navigation",
    # Đèn S1 ở mọi trạng thái xe. Bỏ `off` khỏi enum `headlight` (UNECE R48) nghĩa
    # là không còn thao tác nguy hiểm nào để phải chặn — thứ nguy hiểm là *tắt* đèn
    # khi đang chạy đêm, và đó là thao tác một chiếc xe tuân thủ R48 không cung cấp.
    # Android cũng xếp `HEADLIGHTS_SWITCH` không có interlock theo tốc độ. ADR-020.
    "set_headlight_mode",
    "set_interior_light",
}
_ALWAYS_S2_TOOLS = {"set_window_position"}
#: S2 chỉ khi xe đứng yên và ở số P; ngoài predicate đó là S3.
#: `set_trunk_state` chép nguyên quy tắc của cửa — không phát minh gì. Ngành dùng
#: ngưỡng 5 km/h (FMVSS interior trunk release) và chính VF9 tự khóa cửa trên
#: 10 km/h; predicate của repo chặt hơn cả hai (ADR-010).
_STATIONARY_ONLY_TOOLS = {"set_door_state", "set_seat_position", "set_trunk_state"}
#: S1 khi xe đứng yên, S3 khi không. Khác `_STATIONARY_ONLY_TOOLS` ở vế đứng yên: mở
#: YouTube lúc xe đỗ không đáng một hộp thoại phê duyệt, nên nó là S1 chứ không S2.
#:
#: Không xếp vào `_S0_TOOLS`: S0 là **chỉ đọc**, mà `open_app` *làm* một việc. Xếp nó
#: S0 là bắt taxonomy S0–S3 nói dối, đúng lớp lỗi mà chú thích ở `slm_safety_floor`
#: bên dưới đã cảnh báo ở chiều ngược lại.
#:
#: Dùng lại đúng `is_stationary` thay vì đẻ một ngưỡng tốc độ thứ hai: Android khoá
#: video theo `DRIVING_STATE_PARKED` chứ không theo km/h, và một hệ chỉ nên có **một**
#: định nghĩa "an toàn để thao tác". Hệ quả là dừng đèn đỏ ở số D vẫn bị chặn — đó là
#: chủ ý, không phải tác dụng phụ. Xem ADR-023.
#:
#: S3 ở đây **không được HITL override** (ràng buộc PM lúc duyệt ADR-023). Điều đó đã
#: đúng nhờ cấu trúc — `safety_node` xét S3 trước `requires_approval` — nhưng
#: `tests/test_agents/test_hitl_safety.py` khoá lại mệnh đề ấy để một lần refactor tầng
#: an toàn không lặng lẽ mở cửa.
_STATIONARY_ONLY_S1_TOOLS = {"open_app"}


def canonical_json(payload: object) -> str:
    """JSON ổn định: khóa sắp xếp, không khoảng trắng thừa, giữ nguyên Unicode."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def is_stationary(snapshot: dict[str, Any]) -> bool:
    """Shape canonical của `src/vehicle_sim/state.py`: tốc độ và số nằm trong `motion`.

    Đây là cùng một dict mà `GET /api/v1/vehicle/state` trả ra (`snapshot_dict`), nên
    không có chỗ cho drift giữa thứ agent phân loại và thứ màn hình hiển thị.
    """
    motion = snapshot["motion"]
    return motion["speed_kph"] == 0 and motion["gear"] == "P"


def classify(tool: str, snapshot: dict[str, Any]) -> SafetyLevel:
    if tool in _S0_TOOLS:
        return "S0"
    if tool in _S1_TOOLS:
        return "S1"
    if tool in _ALWAYS_S2_TOOLS:
        return "S2"
    if tool in _STATIONARY_ONLY_TOOLS:
        return "S2" if is_stationary(snapshot) else "S3"
    if tool in _STATIONARY_ONLY_S1_TOOLS:
        return "S1" if is_stationary(snapshot) else "S3"
    raise ValueError(f"tool nằm ngoài allowlist, không thể phân loại: {tool}")


def materialize_action_plan(
    candidate: CandidateActionPlan,
    snapshot: dict[str, Any],
    session_id: str,
    vehicle_id: str,
    *,
    route_source: str = "deterministic",
) -> ActionPlan:
    """Biến candidate thành `ActionPlan` canonical, bất biến.

    `plan_id` suy ra từ nội dung candidate + phiên bản state, nên ổn định qua
    replay — điều kiện cần để branch HITL bind approval theo digest. `route_source`
    **không** đi vào định danh: cùng một plan phải có cùng id bất kể ai đề xuất.

    ## Hai trục, không phải một (issue #144)

    **Mức an toàn mô tả HÀNH ĐỘNG. Nguồn gốc mô tả mức tin rằng ta đã hiểu đúng
    yêu cầu.** Trước thay đổi này chỉ có trục thứ nhất, nên cổng chặn được cái
    *nguy hiểm* mà mù với cái *vô nghĩa*.

    Đo thật trên nhánh SLM: tài xế nói *"Tôi thấy hơi nóng, làm gì đó đi"*, planner đề
    xuất `media_control(set_volume, 10)`. Hợp schema, không đụng cửa/kính/ghế nên xếp
    S1, và S1 thì chạy thẳng. Xe chỉnh âm lượng rồi báo *"Đã thực hiện lệnh trên xe mô
    phỏng."* Với router luật thì khoảng này không tồn tại — luật không khớp thì rơi về
    tra sổ tay. Planner sinh được bất kỳ tool hợp lệ nào, nên khoảng "hợp schema nhưng
    sai ý" mới mở ra.

    Cố ý **không** nâng S1 thành S2. Làm thế là bắt taxonomy S0–S3 nói dối — chỉnh âm
    lượng thật sự không nguy hiểm, nó chỉ *sai* — và một khi S2 mang hai nghĩa thì mọi
    lập luận an toàn dựa trên nó đều loãng. Thay vào đó cổng nằm ở `requires_approval`,
    trực giao với mức an toàn.

    Cũng vì thế S3 **không** đổi: nguồn gốc SLM không được biến một hành động bị cấm
    thành một câu hỏi. `safety_node` xét S3 trước `requires_approval`, nên đường vòng
    đó đóng sẵn — và có test khoá.
    """
    for step in candidate.steps:
        if step.tool not in TOOL_ARGS:
            raise ValueError(f"tool nằm ngoài allowlist: {step.tool}")

    steps = tuple(
        PlanStep(
            step_id=step.step_id,
            ordinal=step.ordinal,
            tool=step.tool,
            args=step.args,
            depends_on=step.depends_on,
            safety_level=classify(step.tool, snapshot),
        )
        for step in candidate.steps
    )
    # `or` chứ không phải `and`: hai lý do độc lập, thoả một là phải hỏi.
    requires_approval = any(step.safety_level == "S2" for step in steps) or route_source == "slm"
    identity = canonical_json(
        {
            "steps": [step.model_dump(mode="json") for step in candidate.steps],
            "vehicle_state_version": snapshot["state_version"],
            "session_id": session_id,
        }
    )
    plan_id = f"plan-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    return ActionPlan(
        plan_id=plan_id,
        session_id=session_id,
        vehicle_id=vehicle_id,
        vehicle_state_version=snapshot["state_version"],
        steps=steps,
        requires_approval=requires_approval,
    )


def plan_digest(plan: ActionPlan) -> str:
    """Vân tay của plan. Branch HITL dùng nó để bind approval; sửa plan là đổi digest."""
    return hashlib.sha256(canonical_json(plan.model_dump(mode="json")).encode("utf-8")).hexdigest()

"""Executor tuần tự, fail-fast, dùng rolling expected_state_version."""

from src.agents.contracts import ToolResult, as_action_plan
from src.agents.state import AgentState
from src.models.vehicle import ToolResult as GatewayToolResult
from src.services.tool_registry import get_spec
from src.services.vehicle_gateway import VehicleGateway


def _as_agent_result(step_id: str, tool: str, args: dict, result: GatewayToolResult) -> ToolResult:
    """Dịch kết quả của cổng sang kiểu mà composer và tầng sự kiện đọc.

    Hai kiểu `ToolResult` tồn tại song song có lý do: bản của cổng
    (`src/models/vehicle.py`) là bản ghi persist xuống SQLite theo `data_model.md`, còn
    bản này là hợp đồng nội bộ của graph. Dịch tường minh ở đúng một chỗ thì hai bên
    tiến hoá độc lập được.

    `command_id` lấy từ cổng chứ **không** ghép lại `plan_id:step_id`: đó là id thật đã
    đi lên MQTT, và `tool.result` trên dây phải tương quan được với `events/command`.
    """
    return ToolResult(
        command_id=result.command_id,
        step_id=step_id,
        tool=tool,
        args=args,
        status=result.status,
        before=result.before,
        after=result.after,
        observed_state_version=result.observed_state_version,
        error_code=result.error_code,
        latency_ms=result.latency_ms,
    )


def _ket_qua_tool_cuc_bo(step, expected_state_version: int) -> ToolResult:
    """Kết quả cho tool **không có domain** — nó không đi qua MQTT.

    `open_app` (ADR-023) và `search_nearby_poi` là tool của IVI, không phải lệnh xe:
    không có actuator, không có gì trên xe đổi trạng thái, nên không có `VehicleCommand`
    để dựng và không có topic để publish. Đưa chúng vào simulator sẽ phải đẻ một domain
    MQTT mới cho thứ **không phải trạng thái xe**, làm hỏng ADR-013 (*snapshot của
    simulator là nguồn trạng thái xe duy nhất*) để đổi lấy đúng con số không.

    `observed_state_version` giữ nguyên `expected`: bước này không quan sát thấy gì đổi,
    chứ không phải không nhìn thấy gì — cùng cách `_skipped` bên dưới đang làm.

    `command_id` ghép từ `plan_id:step_id` chứ không lấy từ cổng, vì không có lệnh nào
    lên dây để mà tương quan.

    Lưu ý phạm vi: `search_nearby_poi` **không** đi qua hàm này. Nó từng bị chặn khỏi
    đường plan vì lý do ghi ở đây — trả `completed` mà không mang gì về — nhưng #371 cho
    nó nhánh riêng (`_ket_qua_tim_poi`) trả danh sách thật, nên nó rẽ **trước** khi tới
    đây. Hàm này giờ chỉ còn phục vụ `open_app`, đúng ca mà "không có gì để mang về" là
    sự thật chứ không phải thiếu sót.
    """
    return ToolResult(
        command_id=f"{step.step_id}",
        step_id=step.step_id,
        tool=step.tool,
        args=step.args,
        status="completed",
        before={},
        after={},
        observed_state_version=expected_state_version,
        error_code=None,
    )


#: Trần số địa điểm đọc ra. Ba là trần của **tai**, không phải của màn hình: nghe quá ba
#: cái tên kèm khoảng cách thì không ai nhớ nổi cái đầu tiên. Cắt ở executor chứ không ở
#: composer, vì đây là giới hạn của *kết quả*, và bước sau (#355 mục 2b) sẽ nhớ đúng danh
#: sách đã đọc ra để hiểu *"cái đầu tiên"* — nhớ một danh sách khác với danh sách đã nói
#: là cách chắc chắn nhất để trỏ nhầm chỗ.
POI_TRAN_DOC = 3


def _ket_qua_tim_poi(step, expected_state_version: int) -> ToolResult:
    """`search_nearby_poi` — S0, **đọc thật** và trả danh sách trong `after` (issue #371).

    ## Vì sao tool này cần một nhánh riêng, không dùng `_ket_qua_tool_cuc_bo`

    Hàm kia trả `after={}` — đúng cho `open_app`, vì mở một ứng dụng không sinh dữ liệu
    nào để đọc lại. Ở đây thì có: cả giá trị của lượt nằm trong **danh sách địa điểm**.
    Trả rỗng nghĩa là bước "thành công" mà không mang gì về, và composer buộc phải tự đi
    tra fixture một lần nữa — chính cấu trúc đã đẻ ra bug #371, nơi câu nói được dựng từ
    một phép tra song song nên nó vẫn nói dù plan đã chết ở `validate_args`.

    Sau thay đổi này, câu nói dựng từ **kết quả thực thi**. Một lượt hỏng không còn cách
    nào đọc ra danh sách, vì không có kết quả nào để đọc.

    Không có `VehicleCommand` nào lên MQTT: đây là dữ liệu của IVI, không phải trạng thái
    xe, và nhét nó vào simulator sẽ phải đẻ một domain MQTT cho thứ không phải trạng thái
    xe — hỏng ADR-013 để đổi lấy con số không.
    """
    from src.fixtures import tim_poi_theo_loai

    danh_sach = tim_poi_theo_loai(str(step.args.get("category", "")))[:POI_TRAN_DOC]
    return ToolResult(
        command_id=f"{step.step_id}",
        step_id=step.step_id,
        tool=step.tool,
        args=step.args,
        # Rỗng vẫn là `completed`: "quanh đây không có quán nào" là một câu trả lời
        # đúng, không phải một lỗi thực thi. Composer phân biệt hai ca bằng độ dài
        # danh sách, không bằng `status`.
        status="completed",
        before={},
        after={"items": [dict(item) for item in danh_sach]},
        observed_state_version=expected_state_version,
        error_code=None,
    )


def make_execute_node(gateway: VehicleGateway):
    async def execute_node(state: AgentState) -> dict:
        # Sau nhánh HITL, state này đã đi qua checkpoint — xem `as_action_plan`.
        plan = as_action_plan(state["action_plan"])
        expected_version = plan.vehicle_state_version
        results: list[ToolResult] = []
        completed: set[str] = set()

        def _skipped(step, reason: str) -> ToolResult:
            return ToolResult(
                command_id=f"{plan.plan_id}:{step.step_id}",
                step_id=step.step_id,
                tool=step.tool,
                args=step.args,
                status="skipped",
                before={},
                after={},
                # Bước bị bỏ qua vẫn quan sát được version hiện tại — nó không
                # chạy, chứ không phải không nhìn thấy gì.
                observed_state_version=expected_version,
                error_code=reason,
            )

        for index, step in enumerate(plan.steps):
            if not set(step.depends_on) <= completed:
                results.append(_skipped(step, "skipped_due_to_prior_failure"))
                continue
            # Tool cục bộ của IVI rẽ TRƯỚC khi chạm cổng: `gateway.execute` dựng
            # `VehicleCommand` rồi gọi simulator, nơi tool không có nhánh xử lý sẽ ném
            # `ToolNotAllowedError`. Xem `_ket_qua_tool_cuc_bo`.
            if step.tool == "search_nearby_poi":
                results.append(_ket_qua_tim_poi(step, expected_version))
                completed.add(step.step_id)
                continue
            if get_spec(step.tool).domain is None:
                results.append(_ket_qua_tool_cuc_bo(step, expected_version))
                completed.add(step.step_id)
                continue
            result = await gateway.execute(
                plan_id=plan.plan_id,
                step_id=step.step_id,
                tool=step.tool,
                args=step.args,
                expected_state_version=expected_version,
                approval_id=state.get("approval_id"),
            )
            results.append(_as_agent_result(step.step_id, step.tool, step.args, result))
            if result.status != "completed":
                # Dừng group, nhưng **đánh dấu** mọi bước còn lại thay vì lặng lẽ bỏ
                # chúng khỏi `results` (issue #83). Bước biến mất khỏi hồ sơ không sai
                # về mặt thực thi — không lệnh nào chạy nhầm — nhưng `GET /traces/{id}`
                # sẽ cho engineer thấy một plan hai bước như thể nó chỉ có một, và
                # `action_audit` đếm thiếu. Hồ sơ là thứ ta dùng để chứng minh an toàn.
                #
                # Phân biệt nguyên nhân theo `safety_and_hitl.md` #8 và #9: simulator
                # trả `stale_state` khi version thực tế đã lệch khỏi rolling expected
                # version, tức có người/thứ khác vừa đổi trạng thái xe.
                reason = (
                    "skipped_external_state_change"
                    if result.error_code == "stale_state"
                    else "skipped_due_to_prior_failure"
                )
                results.extend(_skipped(rest, reason) for rest in plan.steps[index + 1 :])
                break
            completed.add(step.step_id)
            # Rolling version lấy từ chính CommandEvent, do simulator tính **sau** khi
            # đã tăng version — không đọc lại cache. Nên nó không có race, khác hẳn
            # `vehicle.state["state_version"]` trước đây.
            expected_version = result.observed_state_version

        # Từ issue #83 trở đi `len(results)` **luôn** bằng `len(plan.steps)` — mọi bước
        # đều có bản ghi, kể cả bước bị bỏ. Nên vế so độ dài không còn phân biệt được
        # gì và toàn bộ sức nặng dồn vào `all(status == "completed")`. Giữ cả hai vế có
        # chủ đích: vế độ dài là lưới bắt trường hợp một nhánh tương lai lại quên ghi
        # bước nào đó. **Đừng** "dọn dẹp" bằng cách bỏ vế `all(...)` — bỏ nó thì một
        # plan hỏng sẽ được báo `completed`, đúng loại lỗi xanh-test-sai-dữ-liệu.
        done = len(results) == len(plan.steps) and all(r.status == "completed" for r in results)
        return {"step_results": results, "outcome": "completed" if done else "execution_failed"}

    return execute_node

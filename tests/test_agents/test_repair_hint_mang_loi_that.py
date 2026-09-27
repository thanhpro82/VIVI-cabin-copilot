""":Vòng sửa thứ hai của planner phải nói **hỏng ở đâu**, không phải "hỏng".

Đo 26/08 với Qwen3-4B thật, `REPAIR_HINT` khi ấy là một câu chung chung — *"JSON trước
không hợp lệ. Trả lại đúng một object JSON theo schema."*:

    'lạnh quá tắt điều hòa đi' + hint -> {"tool":"set_hvac_power","args":{"power":"off"}}
                                          (y hệt lần 1)
    'chán quá mở nhạc lên'     + hint -> {"tool":"media_control","args":{"action":"play_music",
                                          "source":"online"}}   (tệ hơn lần 1)

Lý do rõ khi nhìn kỹ: JSON **vẫn** hợp lệ về cú pháp — hỏng là ở **schema args**, mà hint
không nói hỏng ở đâu. Model không có thông tin nào để sửa, nên nó lặp lại. Cái giá là
một lượt gọi model nữa (~0,5–3 s) cho mỗi lượt hỏng, đổi lấy gần như không gì.

Chuỗi lỗi thật đã có sẵn (`args không hợp lệ cho set_hvac_power: enabled: Field required`)
— nó chỉ chưa bao giờ được đưa cho model. Xem issue #269.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway

CONFIG = {"configurable": {"thread_id": "t-repair"}}


class PlannerGhiLaiPrompt:
    """Trả args sai ở lần 1, và ghi lại đúng chuỗi prompt mỗi lần bị gọi."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        self.prompts.append(normalized_text)
        if len(self.prompts) == 1:
            # Đúng hình dạng model thật trả: JSON hợp lệ, args sai tên field.
            return (
                '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1",'
                '"ordinal":0,"tool":"set_hvac_power","args":{"power":"off"},"depends_on":[]}]}'
            )
        return (
            '{"kind":"plan","schema_version":"1.0","steps":[{"step_id":"step-1",'
            '"ordinal":0,"tool":"set_hvac_power","args":{"enabled":false},"depends_on":[]}]}'
        )


async def test_lan_thu_hai_duoc_biet_hong_o_dau():
    planner = PlannerGhiLaiPrompt()
    graph = build_graph(InProcessVehicleGateway.new(), planner=planner, checkpointer=InMemorySaver())

    await graph.ainvoke(
        {"query": "làm mát giùm cái", "session_id": "ses-repair", "vehicle_id": "veh-1"},
        config=CONFIG,
    )

    assert len(planner.prompts) == 2, "phải có đúng một vòng sửa"
    lan_hai = planner.prompts[1]
    # Không khẳng định nguyên văn chuỗi lỗi — nó do pydantic sinh và có thể đổi giữa các
    # bản. Khẳng định thứ model CẦN để sửa được: tool nào và field nào.
    assert "set_hvac_power" in lan_hai
    assert "enabled" in lan_hai, f"vòng sửa không nói field nào thiếu: {lan_hai!r}"


async def test_lan_dau_khong_mang_hint():
    """Hint chỉ được xuất hiện ở vòng sửa. Nhét nó vào lần đầu là dạy model rằng câu
    nào cũng vừa hỏng một lần."""
    planner = PlannerGhiLaiPrompt()
    graph = build_graph(InProcessVehicleGateway.new(), planner=planner, checkpointer=InMemorySaver())

    await graph.ainvoke(
        {"query": "làm mát giùm cái", "session_id": "ses-repair2", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "t-repair2"}},
    )

    assert planner.prompts[0] == "làm mát giùm cái"


class PlannerHongHaLan:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def propose(self, normalized_text: str, snapshot: dict) -> str:
        self.prompts.append(normalized_text)
        return "{ khong phai json"


async def test_loi_cu_phap_thi_hint_van_noi_duoc_dieu_gi_do():
    """Không phải lỗi nào cũng là lỗi args. JSON vỡ cú pháp thì không có tool/field để
    nêu — hint vẫn phải tồn tại, chỉ là nội dung khác."""
    planner = PlannerHongHaLan()
    graph = build_graph(InProcessVehicleGateway.new(), planner=planner, checkpointer=InMemorySaver())

    ket_qua = await graph.ainvoke(
        {"query": "làm mát giùm cái", "session_id": "ses-repair3", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "t-repair3"}},
    )

    assert len(planner.prompts) == 2
    assert planner.prompts[1] != planner.prompts[0]
    assert ket_qua["outcome"] in {"clarify", "not_control", "grounded_answer", "grounded_refusal"}

"""Lượt SLM không được chặn event loop — hồi quy cho bản vá 2026-08-23.

## Lỗi mà test này khoá lại

`QwenClassifier`/`QwenPlanner`/`QwenChitchat` dùng `httpx` **đồng bộ**, nhưng ba node
gọi chúng (`classify_stage`, `slm_stage`, `chitchat_stage`) đều là `async def`. Gọi
thẳng thì lời gọi chạy **trên chính event loop**, nên trong suốt lượt SLM cả backend
đứng im: không WebSocket, không lượt của người khác, không cả `/healthz`.

Thời lượng đứng im không nhỏ: tới `slm_classify_timeout_s` cho **mỗi** câu trượt luật,
và tới `slm_timeout_s` **x 2 lần thử** cho một lượt planner hỏng (trên VPS là 20 s x 2).

## Vì sao đo nhịp đập chứ không đo tổng thời gian lượt

Tổng thời gian lượt **không phân biệt được** hai trường hợp: bọc `to_thread` hay không,
lượt đều tốn chừng ấy giây. Thứ khác nhau là **những coroutine KHÁC có chạy được trong
lúc đó không**. Nên test đếm nhịp đập của một coroutine nền, và chốt cửa sổ đếm vào
**đúng khoảng client SLM đang chặn** (stub tự đọc bộ đếm lúc vào và lúc ra) — không phải
cả lượt, vì các node khác (rag, compose) cũng nhả điều khiển và sẽ làm loãng phép đo.

Trước bản vá: `nhip_ra - nhip_vao == 0`. Sau bản vá: ~NGU_S/NHIP_S nhịp.
"""

import asyncio
import time

from src.agents.graph import build_graph
from src.agents.slm import SlmSchemaError
from src.services.vehicle_gateway import InProcessVehicleGateway

#: Client SLM giả chặn bao lâu. Đủ dài để nhịp đập kịp tích luỹ, đủ ngắn để suite
#: không chậm đi đáng kể.
NGU_S = 0.25

#: Chu kỳ nhịp đập nền.
NHIP_S = 0.01

#: Ngưỡng khẳng định. Lý thuyết là NGU_S/NHIP_S = 25 nhịp; chốt ở 5 để máy CI chậm
#: hay bị nhiễu lịch trình cũng không làm test chớp tắt. Ranh giới thật cần phân biệt
#: là **0 với khác 0**, nên biên rộng không làm test yếu đi.
NHIP_TOI_THIEU = 5

#: Câu KHÔNG khớp luật nào của DeterministicControlRouter — router trả
#: `default_to_manual`, tức đường đi tới các node SLM. Cùng câu với
#: `test_slm_classify_node.py`; nếu router sau này học được nó thì đổi cả hai chỗ.
CAU_LA = "Nóng quá trời hôm nay ha"


class _ChanDongBo:
    """Nền chung: chặn luồng gọi bằng `time.sleep`, ghi lại nhịp đập vào/ra.

    `time.sleep` chứ không phải `await asyncio.sleep` là **cố ý** — nó tái hiện đúng
    hành vi của `httpx.post` đồng bộ trong `src/agents/slm.py`.
    """

    def __init__(self, doc_nhip) -> None:  # noqa: ANN001 - callable trả int
        self._doc_nhip = doc_nhip
        self.nhip_vao: int | None = None
        self.nhip_ra: int | None = None
        self.so_lan = 0

    def _chan(self) -> None:
        self.so_lan += 1
        self.nhip_vao = self._doc_nhip()
        time.sleep(NGU_S)
        self.nhip_ra = self._doc_nhip()

    @property
    def nhip_trong_luc_chan(self) -> int:
        assert self.nhip_vao is not None and self.nhip_ra is not None, "stub chưa được gọi"
        return self.nhip_ra - self.nhip_vao


class ClassifierChan(_ChanDongBo):
    def classify(self, normalized_text: str) -> str:
        self._chan()
        return "manual"


class PlannerChan(_ChanDongBo):
    def propose(self, normalized_text: str, snapshot: dict) -> str:
        self._chan()
        # Ném lỗi schema thay vì trả JSON hợp lệ: node bắt và lui về nhánh cũ, nên
        # test không phải dựng một plan hợp lệ chỉ để đo chuyện chặn loop.
        raise SlmSchemaError("stub cố ý hỏng")


class ChitchatChan(_ChanDongBo):
    def reply(self, normalized_text: str) -> str:
        self._chan()
        raise SlmSchemaError("stub cố ý hỏng")


async def _do_nhip_trong_khi_chay(graph) -> None:  # noqa: ANN001 - graph LangGraph
    """Chạy một lượt, có coroutine nhịp đập chạy nền."""
    xong = asyncio.Event()

    async def dap() -> None:
        while not xong.is_set():
            await asyncio.sleep(NHIP_S)
            _dem["n"] += 1

    task = asyncio.create_task(dap())
    try:
        await graph.ainvoke({"query": CAU_LA, "session_id": "s1", "vehicle_id": "v1", "turn_id": "t1"})
    finally:
        xong.set()
        await task


#: Bộ đếm dùng chung giữa coroutine nhịp đập (chạy trên loop) và stub (chạy trên
#: worker thread của `to_thread`). Đọc/ghi một `int` trong dict là nguyên tử dưới
#: CPython, và test không cần độ chính xác hơn thế.
_dem = {"n": 0}


async def test_classify_khong_chan_event_loop():
    """`classify_stage` — chặn loop tới `slm_classify_timeout_s` cho MỖI câu trượt luật."""
    _dem["n"] = 0
    stub = ClassifierChan(lambda: _dem["n"])
    graph = build_graph(InProcessVehicleGateway.new(), classifier=stub)

    await _do_nhip_trong_khi_chay(graph)

    assert stub.so_lan == 1, "stub phải được gọi đúng một lần"
    assert stub.nhip_trong_luc_chan >= NHIP_TOI_THIEU, (
        f"event loop đứng im trong lúc classify chạy ({stub.nhip_trong_luc_chan} nhịp) — "
        "lời gọi SLM phải qua asyncio.to_thread"
    )


async def test_planner_khong_chan_event_loop():
    """`slm_stage` — ca tệ nhất: `slm_timeout_s` x 2 lần thử."""
    _dem["n"] = 0
    stub = PlannerChan(lambda: _dem["n"])
    graph = build_graph(InProcessVehicleGateway.new(), planner=stub)

    await _do_nhip_trong_khi_chay(graph)

    assert stub.so_lan == 2, "node thử lại đúng một lần, nên stub phải được gọi hai lần"
    assert stub.nhip_trong_luc_chan >= NHIP_TOI_THIEU, (
        f"event loop đứng im trong lúc planner chạy ({stub.nhip_trong_luc_chan} nhịp) — "
        "lời gọi SLM phải qua asyncio.to_thread"
    )


async def test_chitchat_khong_chan_event_loop():
    """`chitchat_stage` — cùng bản vá, cùng lớp lỗi."""
    _dem["n"] = 0
    stub = ChitchatChan(lambda: _dem["n"])
    graph = build_graph(
        InProcessVehicleGateway.new(),
        classifier=ClassifierChanTraChitchat(),
        chitchat=stub,
    )

    await _do_nhip_trong_khi_chay(graph)

    assert stub.so_lan == 1
    assert stub.nhip_trong_luc_chan >= NHIP_TOI_THIEU, (
        f"event loop đứng im trong lúc chitchat chạy ({stub.nhip_trong_luc_chan} nhịp) — "
        "lời gọi SLM phải qua asyncio.to_thread"
    )


class ClassifierChanTraChitchat:
    """Classifier KHÔNG chặn, chỉ để lái luồng sang nhánh chitchat."""

    def classify(self, normalized_text: str) -> str:
        return "chitchat"

"""Van đồng thời SLM — quá sức chứa thì **từ chối nhanh**, không im lặng bắt chờ.

## Lỗi mà test này khoá lại

Trước bản vá, backend nhận bao nhiêu lượt cũng gọi thẳng xuống llama-server. Đo trên
VPS (`eval/results/luot-that-dong-thoi/20260825T050738`, `develop` @ `3e4e6a4`) cho
thấy hậu quả từ phía tài xế: một lượt `chitchat` đi từ **283 ms** ở N=1 lên
**7 932 ms** ở N=2, và `so_tay` từ 843 ms lên 15 660 ms ở N=3 — không phải vì bản
thân chúng chậm, mà vì chúng nằm sau một lượt `planner` (17–28 s) trong hàng.

PM/PO review PR #257 (2026-08-24), điều kiện 2: *"Khi quá sức chứa phải xếp hàng có
thông báo hoặc từ chối nhanh có thông điệp rõ ràng; không được im lặng
timeout/fallback."*

## Vì sao đo "nhanh" bằng cách so với thời gian chặn, không bằng một ngưỡng tuyệt đối

Một ngưỡng kiểu `< 100 ms` sẽ chớp tắt trên CI chậm. Thứ cần phân biệt là **hai bậc
độ lớn**: lượt bị từ chối phải xong trong lúc lượt đang giữ van *vẫn còn đang chạy*.
Nên mốc so sánh là `NGU_S` của chính stub, và biên rộng vẫn giữ nguyên ý nghĩa —
ranh giới thật là "trả lời ngay" với "chờ hết lượt kia".

## Ba vai, ba hành vi khác nhau — và đó là chủ đích

`planner` và `chitchat` từ chối có thông điệp; `classify` **vẫn** rơi về sổ tay. Lý
do ở `graph.py`: tra sổ tay không dùng llama-server (FAISS + E5, trích nguyên văn),
nên từ chối ở `classify` là từ chối một việc hệ vẫn làm được. Nó không im lặng vì
`route_reason` riêng (`slm_classify_ban`) đếm được ở trace và `/metrics/summary`.
"""

import asyncio
import time

import pytest

from src.agents import graph as graph_mod
from src.agents.graph import build_graph
from src.agents.nodes.chitchat_cong import CAU_BAN
from src.agents.slm import SlmBanError, goi_qua_van
from src.config import get_settings
from src.services.vehicle_gateway import InProcessVehicleGateway

#: Stub giữ van bao lâu. Đủ dài để lượt thứ hai chắc chắn đụng van khi nó còn bị giữ.
NGU_S = 0.6

#: Câu KHÔNG khớp luật nào của `DeterministicControlRouter` — cùng câu với
#: `test_slm_khong_chan_event_loop.py`; router học được nó thì đổi cả hai chỗ.
CAU_LA = "Nóng quá trời hôm nay ha"

_TRANG_THAI = {"query": CAU_LA, "session_id": "s1", "vehicle_id": "v1", "turn_id": "t1"}


@pytest.fixture
def van_mot_cho(monkeypatch):
    """Hạ sức chứa xuống 1 để hai lượt là đủ dựng cảnh quá tải.

    `get_settings` có `lru_cache`, và `src/agents/slm.py` dựng lại van khi sức chứa
    đổi — nên phải xoá cache ở **cả hai** đầu bài test và cuối, nếu không test sau
    thừa hưởng một `Settings` sai.
    """
    monkeypatch.setenv("SLM_MAX_CONCURRENT", "1")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("SLM_MAX_CONCURRENT", raising=False)
    get_settings.cache_clear()


class _GiuVan:
    """Nền chung: chiếm chỗ bằng `time.sleep` đúng như `httpx` đồng bộ trong `slm.py`."""

    def __init__(self) -> None:
        self.so_lan = 0

    def _giu(self) -> None:
        self.so_lan += 1
        time.sleep(NGU_S)


class PlannerGiuVan(_GiuVan):
    def propose(self, normalized_text: str, snapshot: dict) -> str:
        self._giu()
        # Trả JSON chitchat hợp lệ: test này đo VAN, không đo đường parse.
        return '{"kind":"chitchat","reply":"xong roi"}'


class ChitchatGiuVan(_GiuVan):
    def reply(self, normalized_text: str) -> str:
        self._giu()
        return "xong roi"


class ClassifierGiuVan(_GiuVan):
    def classify(self, normalized_text: str) -> str:
        self._giu()
        return "manual"


class ClassifierNhanh:
    """Không giữ van — chỉ lái luồng sang nhánh chitchat."""

    def classify(self, normalized_text: str) -> str:
        return "chitchat"


async def _hai_luot_cung_luc(graph) -> tuple[dict, dict, float]:
    """Bắn lượt A trước một nhịp để nó chắc chắn giữ van, rồi bắn lượt B.

    Trả `(ket_qua_A, ket_qua_B, thoi_gian_B)`. Nhịp `0.05` s là để A kịp *vào* van chứ
    không phải để A chạy xong — A còn ngủ `NGU_S` sau đó.
    """
    a = asyncio.create_task(graph.ainvoke(dict(_TRANG_THAI)))
    await asyncio.sleep(0.05)

    bat_dau = time.perf_counter()
    kq_b = await graph.ainvoke(dict(_TRANG_THAI, session_id="s2", turn_id="t2"))
    ms_b = time.perf_counter() - bat_dau

    return await a, kq_b, ms_b


async def test_planner_het_cho_thi_tu_choi_ngay_va_noi_ro(van_mot_cho):
    """Lượt thứ hai nhận câu "đang bận" — không chờ hết lượt thứ nhất."""
    stub = PlannerGiuVan()
    graph = build_graph(InProcessVehicleGateway.new(), planner=stub)

    _, kq_b, ms_b = await _hai_luot_cung_luc(graph)

    assert kq_b["chitchat_reply"] == CAU_BAN, "lượt bị từ chối phải nói rõ là đang bận"
    assert kq_b.get("chitchat_cong") == "ban"
    assert ms_b < NGU_S, f"từ chối nhanh nghĩa là xong trước khi lượt kia nhả van ({ms_b:.3f}s >= {NGU_S}s)"
    assert stub.so_lan == 1, "lượt bị từ chối KHÔNG được chạm tới model — nếu không thì van vô nghĩa"


async def test_planner_het_cho_thi_khong_thu_lai(van_mot_cho):
    """Bận không phải hỏng: thử lại chỉ để xin đúng cái van vừa từ chối."""
    stub = PlannerGiuVan()
    graph = build_graph(InProcessVehicleGateway.new(), planner=stub)

    await _hai_luot_cung_luc(graph)

    # Lượt A gọi đúng một lần (nó thành công). Nếu lượt B thử lại thì con số này là 2+.
    assert stub.so_lan == 1


async def test_chitchat_het_cho_thi_dung_cau_ban_chu_khong_phai_nhan_loi(van_mot_cho, monkeypatch):
    """`cong="ban"` tách khỏi `"loi"`: quá tải tạm thời khác model hỏng.

    ## Vì sao test này chặn ở tầng van chứ không dựng hai lượt như hai test kia

    Trong một lượt, **`classify` luôn là vai xin van trước** — nó chạy ngay sau router,
    còn `chitchat` chỉ tới sau khi `classify` đã trả kết quả và **đã nhả chỗ**. Nên với
    sức chứa 1, lượt thứ hai bị chặn ngay ở `classify` và không bao giờ đi tới nhánh
    chitchat: bản đầu của test này xanh-đỏ vì lý do sai, `route_reason` ra
    `slm_classify_ban` chứ không phải câu bận của chitchat.

    Đây là tính chất thật của hệ, không phải hạn chế của test — nhưng nó cũng nghĩa là
    nhánh bận của `chitchat` chỉ chạy khi van đầy **giữa** hai bước. Chặn thẳng ở
    `goi_qua_van` cho đúng vai là cách duy nhất kiểm được nhánh ấy mà không phải xếp
    thời gian cho một cuộc đua.
    """
    that = graph_mod.goi_qua_van

    async def chan_rieng_chitchat(vai, fn, /, *args):
        if vai == "chitchat":
            raise SlmBanError(vai, 200)
        return await that(vai, fn, *args)

    monkeypatch.setattr(graph_mod, "goi_qua_van", chan_rieng_chitchat)
    graph = build_graph(InProcessVehicleGateway.new(), classifier=ClassifierNhanh(), chitchat=ChitchatGiuVan())

    kq = await graph.ainvoke(dict(_TRANG_THAI))

    assert kq["chitchat_reply"] == CAU_BAN
    assert kq["chitchat_cong"] == "ban", "gộp vào 'loi' thì sau này không tách được quá tải khỏi hỏng"


async def test_classify_het_cho_thi_van_tra_loi_nhung_dem_duoc(van_mot_cho):
    """Chỗ duy nhất KHÔNG từ chối tài xế — và nó vẫn không im lặng.

    Tra sổ tay không dùng llama-server, nên từ chối ở đây là từ chối một việc hệ vẫn
    làm được. Điều kiện 2 của review được thoả bằng một `route_reason` riêng đếm được,
    không phải bằng một lời xin lỗi.
    """
    stub = ClassifierGiuVan()
    graph = build_graph(InProcessVehicleGateway.new(), classifier=stub)

    _, kq_b, ms_b = await _hai_luot_cung_luc(graph)

    assert kq_b["route_reason"] == "slm_classify_ban", "phải tách khỏi slm_classify_failed để đếm riêng được"
    assert kq_b.get("chitchat_reply") != CAU_BAN, "câu hỏi sổ tay KHÔNG được biến thành lời xin lỗi"
    assert ms_b < NGU_S
    assert stub.so_lan == 1


async def test_van_nha_cho_sau_khi_xong(van_mot_cho):
    """Van phải nhả kể cả khi hàm bên trong ném — nếu không, một lỗi làm kẹt vĩnh viễn."""

    def no() -> None:
        raise RuntimeError("stub cố ý hỏng")

    with pytest.raises(RuntimeError):
        await goi_qua_van("planner", no)

    # Xin lại ngay được nghĩa là chỗ đã được trả về bể.
    assert await goi_qua_van("planner", lambda: "ok") == "ok"


async def test_suc_chua_lon_hon_thi_khong_ai_bi_tu_choi(monkeypatch):
    """Van chỉ đóng khi thật sự quá sức chứa — đặt 2 thì hai lượt song song đều qua.

    Test này là vế đối của các test trên: thiếu nó thì một van luôn-đóng cũng xanh.
    """
    monkeypatch.setenv("SLM_MAX_CONCURRENT", "2")
    get_settings.cache_clear()
    try:
        stub = PlannerGiuVan()
        graph = build_graph(InProcessVehicleGateway.new(), planner=stub)

        _, kq_b, _ = await _hai_luot_cung_luc(graph)

        assert kq_b.get("chitchat_reply") != CAU_BAN, "sức chứa 2 thì lượt thứ hai không được bị từ chối"
        assert stub.so_lan == 2, "cả hai lượt đều phải chạm tới model"
    finally:
        monkeypatch.delenv("SLM_MAX_CONCURRENT", raising=False)
        get_settings.cache_clear()


async def test_ban_khong_phai_la_loi_ha_tang():
    """`SlmBanError` cố ý KHÔNG kế thừa `OSError`.

    Ba node đều bắt `(SlmSchemaError, OSError, httpx.HTTPError)` và xử lý như "hạ tầng
    hỏng". Nếu `SlmBanError` lọt vào bộ đó thì lượt bận sẽ đi đúng đường của lượt hỏng
    — mất hết phần thông điệp mà điều kiện 2 đòi, và không test nào ở trên bắt được.
    """
    assert not issubclass(SlmBanError, OSError)

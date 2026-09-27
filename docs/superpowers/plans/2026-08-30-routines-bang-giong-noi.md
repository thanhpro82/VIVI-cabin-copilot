# Routines bằng giọng nói — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tài xế nói *"chạy routine Đi làm"* thì Routine chạy, nói *"dừng lại"* thì nó dừng — thay vì cả sáu câu đều rơi xuống tra sổ tay như hôm nay.

**Architecture:** Router nhận ra ý định Routine bằng luật (`routines_intent.doc_y_dinh`, đã có) và trả disposition mới `"routine"`; một node mới phân giải tên rồi gọi thẳng service của BE **trong cùng tiến trình** (`routine_execution.bat_dau` / `huy`) — không dựng lại admission, safety hay cancellation, vì BE đã xong cả ba. Câu đồng ý sau preview dùng lại khe đề nghị treo của #367 thay vì dựng khe thứ ba.

**Tech Stack:** Python 3.11.9, LangGraph, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-routines-bang-giong-noi.md`

## Global Constraints

- **Ranh giới sở hữu (#299):** làn Agent sinh **ý định có kiểu**, không tự hủy executor, không đụng audio/TTS/UI. Không thêm hàm vào `src/services/routine_execution.py` hay `routines_store.py` — cả hai thuộc @hason0510.
- **Router tất định, không đọc trạng thái** (ADR-006/010). Danh sách Routine là *trạng thái* → phân giải tên nằm ở **node**, không ở router.
- **Không đường tắt tới executor.** Mọi bước vẫn qua `policy` → `safety` → HITL; `bat_dau` giữ nguyên ba cổng admission.
- **Preview zero side effect** — không dựng hàng nào trong `routine_executions`.
- **Cổng phê duyệt HITL chạy ở `turns.py` TRƯỚC graph.** Thứ tự ấy phải giữ: một tiếng `"không"` khi đang chờ duyệt là **bác phê duyệt**, không phải hủy Routine.
- **Python:** `.\.venv\Scripts\python.exe` (3.11.9). **Test:** `$env:MQTT_ENABLED="false"` là bắt buộc. **Lint:** `ruff check src/ tests/ scripts/` — đúng lệnh CI, `scripts/` không bỏ được.
- **Cổng bộ đo, chạy ở mọi task đụng `router.py`:** `--mode multiturn` và `--mode bao-loi` phải `di_lui = 0`; `--mode intent` không tụt khỏi `1.0000`.
- Không chạy `scripts/log_antigravity.py` / `log_manual.py`; không sửa `.ai-log/`. Hook pre-push hỏng thì **báo**, không `--no-verify`.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/agents/contracts.py` | **Sửa.** Thêm `"routine"` vào `Disposition`, `"routine_run"`/`"routine_preview"`/`"routine_cancel"` vào `Intent`. | 1 |
| `src/agents/router.py` | **Sửa.** Cổng luật gọi `doc_y_dinh`, trả `disposition="routine"`. | 1 |
| `src/agents/state.py` | **Sửa.** `routine_y_dinh`, `routine_ten_tho`, `routine_id`, `routine_execution_id`. | 1, 2 |
| `src/agents/nodes/routine_node.py` | **Tạo.** Phân giải tên → gọi service BE. Chủ sở hữu **duy nhất** của đường Routine trong graph. | 2 |
| `src/agents/graph.py` | **Sửa.** Rẽ `outcome == "routine"` sang node mới. | 2 |
| `src/agents/nodes/compose.py` | **Sửa.** Lời thoại: preview, không thấy tên, tên mơ hồ, đã hủy. | 3 |
| `eval/datasets/agent/multiturn-v1/cases.jsonl` | **Sửa.** Lớp ca `routine-giong-noi`. | 4 |
| `docs/adr/ADR-032-routines-bang-giong-noi.md` | **Tạo.** | 5 |

---

## Task 1: Router nhận ra ý định Routine

**Files:**
- Modify: `src/agents/contracts.py`
- Modify: `src/agents/router.py`
- Modify: `src/agents/state.py`
- Test: `tests/test_agents/test_routine_router.py` (tạo)

**Interfaces:**
- Consumes: `routines_intent.doc_y_dinh(normalized_text, *, dang_xem_truoc=False) -> YDinhRoutine | None`; `YDinhRoutine(loai, ten_tho, so_buoc)`.
- Produces: `RouteDecision(disposition="routine", intent="routine_run"|"routine_preview"|"routine_cancel", reason="routine_intent")`; state keys `routine_y_dinh: str`, `routine_ten_tho: str`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_agents/test_routine_router.py`:

```python
"""Router nhận ra ý định Routine. Issue #274, #299.

Đo trên `develop` @ `fd4e732` trước khi sửa — sáu câu, sáu lần tra sổ tay:

    "Chạy routine Đi làm"         -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
    "Dừng lại"                    -> "Tôi không tìm thấy thông tin này trong sổ tay xe."

Câu thứ hai đáng lo nhất: đó là lệnh **hủy**.

`routines_intent.py` đã đọc được cả năm ý định và đã có test (#285), nhưng **không ai gọi
nó** — 0 call site. Task này là chỗ nối, không phải chỗ viết mới.
"""

from __future__ import annotations

import pytest

from src.agents.router import DeterministicControlRouter

_ROUTER = DeterministicControlRouter()


def _mo(cau: str) -> str:
    d = _ROUTER.route(cau)
    return f"{d.disposition}/{d.intent}"


@pytest.mark.parametrize(
    ("cau", "mong"),
    [
        ("Chạy routine Đi làm", "routine/routine_run"),
        ("Bắt đầu routine Về nhà", "routine/routine_run"),
        ("Thực hiện routine Thư giãn", "routine/routine_run"),
        ("Xem trước routine Đi làm", "routine/routine_preview"),
        ("Routine Về nhà gồm những gì", "routine/routine_preview"),
        ("Dừng lại", "routine/routine_cancel"),
        ("Hủy routine", "routine/routine_cancel"),
        ("Hủy routine Đi làm", "routine/routine_cancel"),
    ],
)
def test_y_dinh_routine_duoc_nhan(cau: str, mong: str):
    assert _mo(cau) == mong, cau


def test_ten_tho_giu_nguyen_chu_tai_xe_noi():
    """Router **không** phân giải tên — nó không đọc được danh sách Routine của user, và
    ADR-006/010 cấm nó đọc trạng thái. Phân giải là việc của node."""
    d = _ROUTER.route("Chạy routine Đi làm")
    assert d.candidate_plan is None


@pytest.mark.parametrize(
    "cau",
    [
        # Lệnh xe thường — không được nuốt thành Routine.
        "Bật điều hòa",
        "Mở cốp xe",
        "Tăng quạt gió",
        # Câu hỏi sổ tay.
        "Camp Mode là gì",
        "Áp suất lốp bao nhiêu",
        # Tên Routine KHÔNG bao giờ tự kích hoạt (#285): thiếu động từ + từ chỉ loại.
        "Đi làm",
        "Về nhà",
        "Hôm nay tôi đi làm muộn",
    ],
)
def test_cau_khac_khong_bi_doc_thanh_routine(cau: str):
    assert _ROUTER.route(cau).disposition != "routine", cau
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_routine_router.py -q
```

Expected: FAIL — 8 ca đầu ra `not_control/manual_query` thay vì `routine/...`.

- [ ] **Step 3: Mở rộng hai Literal đóng**

Trong `src/agents/contracts.py`, đổi dòng `Disposition`:

```python
#: `"routine"` thêm 30/08 (#274): một Routine là 1–4 hành động có **vòng đời riêng**
#: (`routine_executions`), có preview, và hủy được giữa chừng. Nhét nó vào `"control"` là
#: ép một thứ có vòng đời vào một hợp đồng không có vòng đời nào — và `control` thì bắt
#: buộc mang `candidate_plan`, mà ở đây plan chưa dựng được: router không biết Routine nào.
Disposition = Literal["control", "offer", "not_control", "clarify", "denied", "chitchat", "routine"]
```

Thêm ba intent vào `Intent`, ngay trước `"none"`:

```python
    #: Ba ý định Routine (#274, #299). Tách ba chứ không gộp một, vì lối ra khác hẳn nhau:
    #: `preview` **không chạm executor**, `run` gọi `bat_dau`, `cancel` gọi `huy`. Gộp lại
    #: thì node phải đọc lại chuỗi để biết làm gì — tức đọc hai lần cùng một thứ.
    "routine_run",
    "routine_preview",
    "routine_cancel",
```

Trong `src/agents/state.py`, thêm cạnh `cho_nhan_plan`:

```python
    #: Ý định Routine router đọc được — `"chay"` / `"xem_truoc"` / `"huy"`. Rỗng = lượt này
    #: không thuộc lớp Routine.
    routine_y_dinh: str
    #: Tên **chưa phân giải** — đúng chữ tài xế nói. Router không đọc được danh sách
    #: Routine của user (ADR-006/010 cấm nó đọc trạng thái), nên phân giải là việc của node.
    routine_ten_tho: str
```

Trong `src/agents/router.py`, thêm import ở đầu file:

```python
from src.agents.routines_intent import doc_y_dinh
```

và trong `route()`, đặt cổng **ngay trước** `if is_information_question(text) and co_tu_vung_xe(text):`:

```python
        # Cổng Routine đứng TRƯỚC nhánh câu hỏi sổ tay, sau chuẩn hoá. Lý do thứ tự:
        # `"Routine Về nhà gồm những gì"` chứa `"gì"` nên `is_information_question` bắt
        # được nó và đưa đi tra sổ tay — đúng thứ đo được hôm nay.
        #
        # Đặt trước KHÔNG làm rộng cửa: `doc_y_dinh` đòi động từ + từ chỉ loại, nên một
        # câu hỏi sổ tay bình thường vẫn trả `None` và rơi xuống nhánh cũ nguyên vẹn.
        if (y_dinh := doc_y_dinh(text)) is not None:
            intent = {"chay": "routine_run", "xem_truoc": "routine_preview", "huy": "routine_cancel"}.get(
                y_dinh.loai
            )
            if intent is not None:
                return "routine", intent, "routine_intent", ()
```

*Ghi chú cho người cài: `doc_y_dinh` hiện trả `loai` trong `{"chay","xem_truoc","dong_y","tu_choi","bo_buoc"}` — **chưa có `"huy"`**. Step tiếp theo thêm nó.*

- [ ] **Step 4: Thêm ý định `huy` vào `routines_intent`**

Trong `src/agents/routines_intent.py`, đổi khai báo:

```python
YDinh = Literal["chay", "xem_truoc", "dong_y", "tu_choi", "bo_buoc", "huy"]
```

thêm hằng cạnh các mẫu khác:

```python
#: Câu **hủy** một lần chạy đang sống (#299). Tập đóng và ngắn.
#:
#: `"dừng lại"` đứng riêng, không cần từ `routine`: khi một Routine đang chạy thì đó là câu
#: tự nhiên nhất, và issue ghi rõ nó phải map đúng active run. Rủi ro nuốt nhầm được chặn
#: ở chỗ khác, không ở đây: cổng phê duyệt HITL chạy tại `turns.py` **trước** graph, nên
#: một tiếng "dừng" khi đang chờ duyệt không bao giờ tới được router.
_HUY = re.compile(
    r"^\s*(dừng lại|dừng routine|hủy routine|huỷ routine|hủy chuỗi lệnh|dừng chuỗi lệnh)\b",
    re.IGNORECASE,
)
```

và trong `doc_y_dinh`, **ngay sau** khối `if dang_xem_truoc:` — thứ tự này quan trọng và dễ
làm sai. `_TU_CHOI` (dòng 81) đã bắt `dừng|hủy|thôi` rồi, nhưng nó chỉ được hỏi **bên trong**
ngữ cảnh preview. Hai nghĩa khác nhau, và cả hai đều đúng:

- `"dừng"` **trong** preview = *"đừng chạy nó"* → `tu_choi`, chưa có gì để hủy;
- `"dừng lại"` **ngoài** preview = *"hủy cái đang chạy"* → `huy`.

Đặt `_HUY` **trước** khối preview thì tiếng "thôi" sau một preview biến thành lệnh hủy một
lần chạy chưa từng tồn tại:

```python
    if (m := _HUY.search(text)) is not None:
        con = text[m.end() :].strip()
        return YDinhRoutine("huy", ten_tho=_bo_duoi_lich_su(con) or None)
```

- [ ] **Step 5: Chạy lại, phải xanh**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_routine_router.py tests/test_agents/test_routines_intent.py -q
```

Expected: PASS. *Nếu `test_routines_intent.py` có test khoá tập `YDinh` thì cập nhật nó — đó là một quyết định mở rộng có chủ ý, không phải trôi.*

- [ ] **Step 6: Ba bộ đo — cổng bắt buộc cho mọi thay đổi `router.py`**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode bao-loi
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode intent
ruff check src/ tests/ scripts/
```

Expected: suite xanh; `DI LUI=0` ở cả `multiturn` và `bao-loi`; `intent_accuracy=1.0000`.

- [ ] **Step 7: Commit**

```bash
git add src/agents/contracts.py src/agents/router.py src/agents/state.py src/agents/routines_intent.py tests/test_agents/test_routine_router.py
git commit -m "feat(router): nhan y dinh Routine, va them y dinh huy (#274, #299)"
```

---

## Task 2: Node Routine — phân giải tên và gọi service của BE

**Files:**
- Create: `src/agents/nodes/routine_node.py`
- Modify: `src/agents/graph.py`
- Modify: `src/agents/state.py`
- Test: `tests/test_agents/test_routine_node.py` (tạo)

**Interfaces:**
- Consumes: `routines_intent.phan_giai_ten(ten_tho: str, ten_routine: list[str]) -> KetQuaPhanGiai` với `.trung: str | None`, `.ung_vien: tuple[str, ...]`, `.mo_ho: bool`, `.khong_thay: bool`; `routines_store.list_routines(user_id) -> list[Routine]`; `routine_execution.bat_dau(*, user_id, session_id, vehicle_id, routine_id) -> RoutineExecution`; `routine_execution.huy(user_id, execution_id) -> RoutineExecution`.
- Produces: `make_routine_node() -> callable`; state keys `routine_id: str`, `routine_execution_id: str`, `routine_ung_vien: list[str]`, và `outcome` ∈ `{"routine_preview","routine_da_chay","routine_da_huy","routine_khong_thay","routine_mo_ho","routine_khong_co_lan_chay"}`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_agents/test_routine_node.py`:

```python
"""Node Routine: phân giải tên rồi gọi service của BE. Issue #274, #299.

## Vì sao gọi service chứ không gọi HTTP

Agent và BE chạy **cùng một tiến trình** (`src/serve.py`). Gọi `POST /routines/{id}/run` từ
trong graph là tự gọi HTTP vào chính mình: thêm một vòng serialize, một đường lỗi mới, và
một bản sao logic auth.

## Vì sao KHÔNG dựng lại admission

`routine_execution.bat_dau` có ba cổng admission chạy **trước** khi có hàng nào trong
`routine_executions`, và `huy` idempotent qua ba đường. Dựng bản thứ hai ở làn Agent là
dựng một bản chắc chắn sẽ lệch — và #299 ghi rõ ranh giới: *"không tự hủy executor"*.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agents.nodes.routine_node import make_routine_node


@dataclass
class _RoutineGia:
    id: str
    name: str


@dataclass
class _ExecGia:
    id: str
    status: str


def _node(*, ten=("Đi làm", "Về nhà", "Thư giãn"), lan_chay=None, ghi=None):
    """Node với ba service giả — làn Agent không sở hữu ba hàm ấy, nên test không chạm DB."""
    goi = ghi if ghi is not None else []

    def liet_ke(user_id: str):
        return [_RoutineGia(f"rtn_{i}", t) for i, t in enumerate(ten)]

    async def bat_dau(*, user_id, session_id, vehicle_id, routine_id):
        goi.append(("bat_dau", routine_id))
        return _ExecGia(f"exe_{routine_id}", "running")

    async def huy(user_id, execution_id):
        goi.append(("huy", execution_id))
        return _ExecGia(execution_id, "canceled")

    def dang_chay(session_id: str):
        return lan_chay

    return make_routine_node(liet_ke=liet_ke, bat_dau=bat_dau, huy=huy, dang_chay_cua_phien=dang_chay)


_STATE = {"user_id": "usr_driver_01", "session_id": "ses_1", "vehicle_id": "vehicle-demo-01"}


async def test_chay_goi_bat_dau_dung_routine():
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})
    assert ra["outcome"] == "routine_da_chay"
    assert ghi == [("bat_dau", "rtn_0")]


async def test_xem_truoc_KHONG_cham_executor():
    """Bất biến của #274: *"Preview không tạo side effect."*"""
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "xem_truoc", "routine_ten_tho": "Về nhà"})
    assert ra["outcome"] == "routine_preview"
    assert ra["routine_id"] == "rtn_1"
    assert ghi == [], "preview đã gọi executor"


async def test_ten_mo_ho_thi_hoi_lai_va_zero_side_effect():
    ghi: list = []
    node = _node(ten=("Đi làm sáng", "Đi làm chiều"), ghi=ghi)
    ra = await node({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})
    assert ra["outcome"] == "routine_mo_ho"
    assert sorted(ra["routine_ung_vien"]) == ["Đi làm chiều", "Đi làm sáng"]
    assert ghi == []


async def test_khong_thay_ten_thi_neu_danh_sach_chu_khong_chay_bua():
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi chơi"})
    assert ra["outcome"] == "routine_khong_thay"
    assert ra["routine_ung_vien"] == ["Đi làm", "Về nhà", "Thư giãn"]
    assert ghi == []


async def test_huy_map_dung_lan_chay_dang_song_cua_phien():
    ghi: list = []
    node = _node(lan_chay=_ExecGia("exe_dang_chay", "running"), ghi=ghi)
    ra = await node({**_STATE, "routine_y_dinh": "huy", "routine_ten_tho": None})
    assert ra["outcome"] == "routine_da_huy"
    assert ghi == [("huy", "exe_dang_chay")]


async def test_huy_khi_khong_co_lan_chay_nao_thi_tra_loi_an_toan():
    """#299: *"no-active-run trả phản hồi an toàn, zero side effect."*"""
    ghi: list = []
    ra = await _node(lan_chay=None, ghi=ghi)({**_STATE, "routine_y_dinh": "huy"})
    assert ra["outcome"] == "routine_khong_co_lan_chay"
    assert ghi == []


async def test_huy_hai_lan_lien_tiep_van_an_toan():
    """Idempotency là của `huy()` (BE, #297) — test này khoá rằng node **không** thêm một
    tầng trạng thái nào chen vào và làm hỏng tính chất ấy."""
    ghi: list = []
    node = _node(lan_chay=_ExecGia("exe_1", "running"), ghi=ghi)
    st = {**_STATE, "routine_y_dinh": "huy"}
    assert (await node(st))["outcome"] == "routine_da_huy"
    assert (await node(st))["outcome"] == "routine_da_huy"
    assert ghi == [("huy", "exe_1"), ("huy", "exe_1")]


@pytest.mark.parametrize("thieu", ["user_id", "session_id"])
async def test_thieu_ngu_canh_thi_khong_goi_gi_ca(thieu: str):
    """Fail-closed. State tới từ `turns.py`; thiếu khoá là lỗi lập trình, và lối ra an toàn
    là **không làm gì**, không phải đoán một user khác."""
    ghi: list = []
    st = {**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"}
    st.pop(thieu)
    ra = await _node(ghi=ghi)(st)
    assert ra["outcome"] == "routine_khong_thay"
    assert ghi == []
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_routine_node.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.nodes.routine_node'`.

- [ ] **Step 3: Tạo node**

Tạo `src/agents/nodes/routine_node.py`:

```python
"""Đường Routine trong graph: phân giải tên rồi gọi service của BE. Issue #274, #299.

## Chủ sở hữu duy nhất

Mọi lượt `disposition == "routine"` đi qua đúng file này. Router chỉ nói *"đây là ý định
Routine"*; nó **không** phân giải tên, vì danh sách Routine của user là **trạng thái** và
ADR-006/010 cấm router đọc trạng thái — cùng chỗ đứng với `ghep_hoi_lai` và `loi_de_nghi`.

## Ba service tiêm vào, không nhập thẳng

`make_routine_node` nhận `liet_ke`, `bat_dau`, `huy`, `dang_chay_cua_phien` làm tham số.
Hai lý do, và lý do thứ hai mới là lý do thật:

1. test chạy được mà không cần DB;
2. **ranh giới sở hữu.** Ba hàm ấy thuộc `src/services/` của @hason0510 (#299: *"không tự
   hủy executor"*). Tiêm vào thì file này không bao giờ giả định hình dạng bên trong chúng,
   và một thay đổi bên ấy làm đỏ đúng chỗ nối chứ không im lặng đổi hành vi.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.agents.routines_intent import phan_giai_ten
from src.agents.state import AgentState

logger = logging.getLogger(__name__)


def make_routine_node(
    *,
    liet_ke: Callable[[str], list[Any]],
    bat_dau: Callable[..., Any],
    huy: Callable[..., Any],
    dang_chay_cua_phien: Callable[[str], Any | None],
):
    async def routine_node(state: AgentState) -> dict:
        y_dinh = str(state.get("routine_y_dinh") or "")
        user_id = str(state.get("user_id") or "")
        session_id = str(state.get("session_id") or "")

        # Fail-closed: state tới từ `turns.py`, thiếu khoá là lỗi lập trình. Lối ra an
        # toàn là không làm gì — đoán một user khác là chạy lệnh trên xe của người khác.
        if not user_id or not session_id:
            logger.warning("lượt Routine thiếu ngữ cảnh: user=%r session=%r", user_id, session_id)
            return {"outcome": "routine_khong_thay", "routine_ung_vien": []}

        if y_dinh == "huy":
            lan_chay = dang_chay_cua_phien(session_id)
            if lan_chay is None:
                return {"outcome": "routine_khong_co_lan_chay"}
            ra = await huy(user_id, lan_chay.id)
            return {"outcome": "routine_da_huy", "routine_execution_id": ra.id}

        ds = liet_ke(user_id)
        ten = [r.name for r in ds]
        kq = phan_giai_ten(str(state.get("routine_ten_tho") or ""), ten)

        if kq.khong_thay:
            # Nêu cái CÓ, không chạy cái đoán được (#274).
            return {"outcome": "routine_khong_thay", "routine_ung_vien": ten}
        if kq.mo_ho:
            return {"outcome": "routine_mo_ho", "routine_ung_vien": list(kq.ung_vien)}

        routine_id = next(r.id for r in ds if r.name == kq.trung)
        if y_dinh == "xem_truoc":
            # KHÔNG chạm executor — bất biến của #274. Không có hàng nào trong
            # `routine_executions` sau một lượt preview.
            return {"outcome": "routine_preview", "routine_id": routine_id}

        ra = await bat_dau(
            user_id=user_id,
            session_id=session_id,
            vehicle_id=str(state.get("vehicle_id") or ""),
            routine_id=routine_id,
        )
        return {"outcome": "routine_da_chay", "routine_id": routine_id, "routine_execution_id": ra.id}

    return routine_node
```

Trong `src/agents/state.py`, thêm cạnh `routine_ten_tho`:

```python
    #: Routine đã phân giải, và lần chạy nó sinh ra. Rỗng khi lượt không phân giải được.
    routine_id: str
    routine_execution_id: str
    #: Tên để hỏi lại khi mơ hồ, hoặc để nêu ra khi không thấy. Rỗng ở mọi lượt khác.
    routine_ung_vien: list[str]
```

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_routine_node.py -q
```

Expected: PASS (9 ca).

- [ ] **Step 5: Nối vào graph**

Trong `src/agents/graph.py`, thêm node và cạnh. Tìm chỗ đăng ký node (`builder.add_node(...)`) và thêm:

```python
    from src.agents.nodes.routine_node import make_routine_node
    from src.services.routine_execution import bat_dau, huy
    from src.services.routines_store import list_routines

    builder.add_node(
        "routine",
        make_routine_node(
            liet_ke=list_routines,
            bat_dau=bat_dau,
            huy=huy,
            # `dang_chay_cua_phien` CHƯA TỒN TẠI — xem spec §4. Cho tới khi @hason0510
            # thêm, hủy luôn trả "không có lần chạy nào", tức fail-closed và zero side
            # effect. Đó là hành vi đúng cho một phụ thuộc chưa có, không phải một chỗ vá.
            dang_chay_cua_phien=lambda _sid: None,
        ),
    )
```

Trong `_route_after_routing`, thêm ngay sau nhánh `offer`:

```python
        # Ý định Routine đi tới node riêng: nó có vòng đời của chính nó và không dựng
        # `ActionPlan` nào ở tầng này.
        if outcome == "routine":
            return "routine"
```

và thêm cạnh `routine → compose`.

- [ ] **Step 6: Toàn bộ + bộ đo + lint**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn
ruff check src/ tests/ scripts/
```

Expected: xanh, `DI LUI=0`.

- [ ] **Step 7: Commit**

```bash
git add src/agents/nodes/routine_node.py src/agents/graph.py src/agents/state.py tests/test_agents/test_routine_node.py
git commit -m "feat(agent): node Routine goi thang service cua BE, khong dung lai admission"
```

---

## Task 3: Lời thoại — sáu lối ra, mỗi lối một câu

**Files:**
- Modify: `src/agents/nodes/compose.py`
- Test: `tests/test_agents/test_routine_loi_thoai.py` (tạo)

**Interfaces:**
- Consumes: `outcome` ∈ 6 giá trị của Task 2; `routine_ung_vien: list[str]`.
- Produces: `response_text` / `speak_text` cho cả sáu.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_agents/test_routine_loi_thoai.py`:

```python
"""Sáu lối ra của đường Routine, mỗi lối một câu nói được. Issue #274.

Câu phải nói được **khi đang lái**: ngắn, và nói rõ xe ĐÃ làm gì hay CHƯA làm gì. Bài học
`CLARIFY_MESSAGES` (#148): một câu hỏi lại thiếu vế *"tôi chưa làm gì cả"* khiến tài xế
đinh ninh việc đã xong trong khi thực tế là **0 lệnh**.
"""

from __future__ import annotations

import pytest

from src.agents.nodes.compose import compose_node


async def _noi(**state) -> dict:
    return await compose_node(dict(state))


async def test_khong_thay_thi_NEU_cai_co_chu_khong_im_lang():
    ra = await _noi(outcome="routine_khong_thay", routine_ung_vien=["Đi làm", "Về nhà"])
    assert "Đi làm" in ra["speak_text"] and "Về nhà" in ra["speak_text"]
    assert "chưa" in ra["speak_text"].lower()


async def test_mo_ho_thi_hoi_lai_bang_dung_cac_ung_vien():
    ra = await _noi(outcome="routine_mo_ho", routine_ung_vien=["Đi làm sáng", "Đi làm chiều"])
    assert "Đi làm sáng" in ra["speak_text"] and "Đi làm chiều" in ra["speak_text"]
    assert ra["speak_text"].rstrip().endswith("?")


async def test_khong_co_lan_chay_thi_noi_that_chu_khong_bao_da_huy():
    """Báo "đã hủy" khi không có gì để hủy là nói dối về một việc an toàn — tài xế sẽ tin
    rằng xe vừa dừng một thứ đang chạy."""
    ra = await _noi(outcome="routine_khong_co_lan_chay")
    assert "không có" in ra["speak_text"].lower()
    assert "đã hủy" not in ra["speak_text"].lower()


async def test_da_huy_thi_noi_ngan():
    ra = await _noi(outcome="routine_da_huy")
    assert len(ra["speak_text"]) <= 60


@pytest.mark.parametrize(
    "outcome",
    ["routine_preview", "routine_da_chay", "routine_da_huy", "routine_khong_thay",
     "routine_mo_ho", "routine_khong_co_lan_chay"],
)
async def test_moi_loi_ra_deu_co_cau_noi(outcome: str):
    """Không lối ra nào được rơi vào câu mặc định `"Tôi chưa rõ bạn muốn điều khiển gì."` —
    đó là câu của một lượt KHÔNG hiểu, còn sáu lối ra này đều hiểu rất rõ."""
    ra = await _noi(outcome=outcome, routine_ung_vien=["Đi làm"])
    assert ra["speak_text"]
    assert "chưa rõ bạn muốn điều khiển gì" not in ra["speak_text"]
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_routine_loi_thoai.py -q
```

Expected: FAIL — mọi ca rơi vào `OUTCOME_MESSAGES` mặc định.

- [ ] **Step 3: Thêm sáu câu**

Trong `src/agents/nodes/compose.py`, thêm cạnh `GIAI_TAN`:

```python
#: Sáu lối ra của đường Routine (#274). Mỗi câu nói rõ xe ĐÃ làm gì hay CHƯA làm gì — bài
#: học `CLARIFY_MESSAGES`: thiếu vế ấy thì tài xế đinh ninh việc đã xong trong khi là 0 lệnh.
ROUTINE_DA_CHAY = "Đang chạy Routine cho bạn."
ROUTINE_DA_HUY = "Đã dừng Routine."
#: Nói THẬT khi không có gì để hủy. Báo "đã hủy" ở đây là nói dối về một việc an toàn —
#: tài xế sẽ tin rằng xe vừa dừng một thứ đang chạy.
ROUTINE_KHONG_CO_LAN_CHAY = "Hiện không có Routine nào đang chạy."


def _cau_routine(state: dict) -> dict | None:
    """Câu cho sáu lối ra Routine, hoặc `None` để đi đường thường."""
    outcome = state.get("outcome")
    ung_vien = [str(t) for t in (state.get("routine_ung_vien") or [])]
    if outcome == "routine_da_chay":
        cau = ROUTINE_DA_CHAY
    elif outcome == "routine_da_huy":
        cau = ROUTINE_DA_HUY
    elif outcome == "routine_khong_co_lan_chay":
        cau = ROUTINE_KHONG_CO_LAN_CHAY
    elif outcome == "routine_khong_thay":
        cau = f"Tôi chưa chạy gì cả. Bạn có các Routine: {_liet_ke(ung_vien)}."
    elif outcome == "routine_mo_ho":
        cau = f"Tôi chưa chạy gì cả. Bạn muốn {_liet_ke(ung_vien)}?"
    elif outcome == "routine_preview":
        cau = "Routine này gồm các bước sau. Bạn có muốn tôi chạy không?"
    else:
        return None
    return {"response_text": cau, "speak_text": cau, "has_more_to_read": False}
```

và trong `compose_node`, ngay sau nhánh `giai_tan`:

```python
    if (ra := _cau_routine(state)) is not None:
        return ra
```

*`_liet_ke` đã tồn tại trong `compose.py` (dùng ở câu thiếu trang bị) — dùng lại, đừng viết bản thứ hai.*

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_routine_loi_thoai.py -q
```

Expected: PASS (10 ca).

- [ ] **Step 5: Kiểm bằng đường thật**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
ruff check src/ tests/ scripts/
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/nodes/compose.py tests/test_agents/test_routine_loi_thoai.py
git commit -m "feat(compose): sau loi ra cua duong Routine, moi loi mot cau noi duoc"
```

---

## Task 4: Lớp ca `routine-giong-noi` trong `multiturn-v1`

**Files:**
- Modify: `eval/datasets/agent/multiturn-v1/cases.jsonl`
- Modify: `eval/datasets/agent/multiturn-v1/README.md`

**Interfaces:**
- Consumes: `--mode multiturn` (`src/agents/eval.py`), chấm ở mức `route_node`.

**Vì sao ở `multiturn-v1` chứ không một bộ mới:** ca `"chạy routine Đi làm"` → `"có"` là một **cặp lượt**, đúng thứ bộ này đo. Và lớp ca âm tính ở đây cũng là **một nửa deliverable của #296** (closed phrase set + negative cases), nên #296 sẽ có sẵn dữ liệu khi nó mở.

- [ ] **Step 1: Thêm ca**

```powershell
.\.venv\Scripts\python.exe - <<'PY'
import io, json
p = "eval/datasets/agent/multiturn-v1/cases.jsonl"
lines = [json.loads(l) for l in io.open(p, encoding="utf-8")]

def ca(cid, moc, turns):
    return {"case_id": cid, "nhom": "routine-giong-noi", "moc_2908": moc, "turns": turns}

def l(text, **exp):
    return {"input_text": text, "expected": exp}

lines += [
    ca("MT-RTN-001", "hong", [l("Chạy routine Đi làm", disposition="routine")]),
    ca("MT-RTN-002", "hong", [l("Bắt đầu routine Về nhà", disposition="routine")]),
    ca("MT-RTN-003", "hong", [l("Xem trước routine Thư giãn", disposition="routine")]),
    ca("MT-RTN-004", "hong", [l("Routine Về nhà gồm những gì", disposition="routine")]),
    ca("MT-RTN-005", "hong", [l("Dừng lại", disposition="routine")]),
    ca("MT-RTN-006", "hong", [l("Hủy routine", disposition="routine")]),
    # Âm tính — cũng là nửa deliverable của #296.
    ca("MT-RTN-101", "dung", [l("Bật điều hòa", disposition="control")]),
    ca("MT-RTN-102", "dung", [l("Đi làm", disposition="not_control")]),
    ca("MT-RTN-103", "dung", [l("Hôm nay tôi đi làm muộn", disposition="not_control")]),
    ca("MT-RTN-104", "dung", [l("Camp Mode là gì", disposition="not_control")]),
]
with io.open(p, "w", encoding="utf-8", newline="\n") as f:
    for c in lines:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")
print(f"tong {len(lines)} ca")
PY
```

- [ ] **Step 2: Đo mốc trước khi Task 1–3 vào**

Nếu chạy Task 4 **sau** Task 1–3 thì mốc `hong` đã sai. Kiểm bằng `git stash`:

```powershell
git stash -u
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn
git stash pop
```

Expected trên cây chưa sửa: 6 ca `MT-RTN-00x` fail, 4 ca `MT-RTN-1xx` pass.

- [ ] **Step 3: Đo sau**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn
```

Expected: `routine-giong-noi 10/10`, `DI LUI=0`, `da_sua` chứa 6 mã `MT-RTN-00x`.

- [ ] **Step 4: Promote và ghi README**

Đổi `moc_2908` của 6 ca từ `hong` sang `dung`, thêm `"ghi_chu": "hong -> dung 30/08 (#274)"`, và thêm một mục vào `README.md` theo đúng khuôn các nhóm đã có: mô tả nhóm, transcript đo được trước khi sửa, và ghi rõ ca âm tính quan trọng ngang ca dương tính.

- [ ] **Step 5: Commit**

```bash
git add eval/datasets/agent/multiturn-v1/
git commit -m "eval(multiturn): lop ca routine-giong-noi, 6 hong + 4 am tinh"
```

---

## Task 5: ADR-032 và giao lại phần chưa làm

**Files:**
- Create: `docs/adr/ADR-032-routines-bang-giong-noi.md`
- Modify: `WORKLOG.md`
- Modify: `docs/superpowers/specs/2026-08-23-lo-trinh-agent-theo-kich-ban.md`

- [ ] **Step 1: Viết ADR-032**

Mục bắt buộc: Status/Date/Owner/Liên quan; **Context** (sáu câu → sáu lần tra sổ tay, đo được, và `routines_intent` 0 call site); **Decision** (disposition `"routine"`, node gọi service cùng tiến trình, `dong_y` dùng lại khe #367); **Rủi ro nhận** (`"dừng lại"` là cụm ngắn — rủi ro nuốt nhầm được chặn bởi thứ tự cổng HITL ở `turns.py`, không bởi từ vựng); **Phương án đã bác** (gọi HTTP vào chính mình; mượn `control`; dựng khe ngữ cảnh thứ ba); **Thu hồi** (bỏ một dòng `if outcome == "routine"` trong `_route_after_routing`).

- [ ] **Step 2: Ghi phụ thuộc chéo làn vào ADR**

Mục §Chờ BE: `dang_chay_cua_phien(session_id)` chưa tồn tại, kèm chữ ký ở spec §4. Ghi rõ hành vi tạm: **hủy luôn trả "không có lần chạy nào"** — fail-closed, zero side effect, và nó **không sai**, chỉ là chưa đủ.

- [ ] **Step 3: WORKLOG + lộ trình**

Thêm khối WORKLOG theo khuôn bảng đang dùng. Thêm một mục vào lộ trình ghi trạng thái epic Routines của làn Agent và điều kiện của #296.

- [ ] **Step 4: Commit**

```bash
git add docs/adr/ADR-032-routines-bang-giong-noi.md WORKLOG.md docs/superpowers/specs/2026-08-23-lo-trinh-agent-theo-kich-ban.md
git commit -m "docs(adr): ADR-032 Routines bang giong noi, va phu thuoc cheo lan"
```

---

## Kiểm cuối trước khi mở PR

- [ ] `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q` — xanh
- [ ] `--mode multiturn` → `DI LUI=0`, `routine-giong-noi 10/10`
- [ ] `--mode bao-loi` → `DI LUI=0`
- [ ] `--mode intent` → `1.0000`
- [ ] `ruff check src/ tests/ scripts/` — sạch
- [ ] Kiểm tay qua graph thật: sáu câu ở §1 của spec không còn câu nào ra `"Tôi không tìm thấy thông tin này trong sổ tay xe."`
- [ ] PR body nêu trình tự merge so với PR đang mở, và **không** chứa link `claude.ai/code/session_...`
- [ ] Hỏi @hason0510 về `dang_chay_cua_phien` — **không** tự thêm vào file của anh ấy

---

## Ngoài phạm vi plan này

| việc | vì sao hoãn |
|---|---|
| `bo_buoc` (bỏ một bước trong preview) | `routines_intent` đọc được ý định, nhưng cần hợp đồng "chạy với tập bước con" mà BE chưa có |
| **#296** eval barge-in | là **spike**, và cần audio **người nói thật** từ FE spike #277. 264 WAV trong repo là Piper tổng hợp — không dùng được cho tuyên bố mà #296 đòi. Xem spec §7 |
| Đọc **các bước** trong preview | Task 3 nói *"gồm các bước sau"* nhưng chưa đọc ra từng bước: cần `routine_thanh_candidate` + một bộ mô tả bước bằng lời, và nó đáng một task riêng có bộ đo riêng |

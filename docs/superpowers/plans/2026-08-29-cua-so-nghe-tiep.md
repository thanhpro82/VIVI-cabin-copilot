# Cửa sổ nghe tiếp mở sau mọi lượt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tài xế nói được nhiều lượt liên tiếp mà không phải lặp "Hey VIVI", với bốn phanh đóng cửa sổ và một luật im lặng để xe không chen vào cuộc nói chuyện của người.

**Architecture:** Cửa sổ `FOLLOW_UP_WINDOW` (đã có từ #343) bỏ điều kiện `hasMoreToRead`, thay bằng tín hiệu `mo_mic_ngan` do **backend** tính từ kết cục lượt — vì chỉ backend biết xe có hiểu gì không. FE thêm ngân sách cứng (số lượt nối + đồng hồ tường) làm trần không phụ thuộc nội dung. Một header `X-Capture-Mode` cho backend biết lượt nào bắt tự động, để nó **im lặng** thay vì đọc câu từ chối khi không hiểu.

**Tech Stack:** Python 3.11.9 + FastAPI + LangGraph (BE); Next.js 16 + TypeScript + Vitest (FE).

**Spec:** `docs/superpowers/specs/2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md`

## Global Constraints

- **Phụ thuộc:** PR #373 phải merge trước. Task 2 refactor chính field `mo_mic_ngan` mà #373 tạo ra.
- **Python:** chạy `.\.venv\Scripts\python.exe` (3.11.9). Kiểm bằng `.\.venv\Scripts\python.exe -V`.
- **Test BE:** `$env:MQTT_ENABLED="false"` là **bắt buộc** — mặc định `true` khiến mỗi `TestClient(app)` chờ broker 10 s.
- **Lint BE:** `ruff check src/ tests/ scripts/` — đúng lệnh CI chạy, `scripts/` không bỏ được.
- **Không** chạy `ruff format` rộng: cây đã trôi 42 file, chỉ format file mình động vào.
- **Test FE:** `cd frontend; npm run test` (Vitest). Bắt buộc khi động vào `lib/services/`.
- **Bất biến an toàn:** mọi lệnh vẫn qua policy → safety → HITL. Rào chắn `mau_slot` chạy trên **mọi** lượt, không phụ thuộc `X-Capture-Mode`.
- **Bất biến bộ đo:** `di_lui` của `--mode multiturn` phải bằng **0** ở mọi task.
- **Không** rename `mo_mic_ngan`. **Không** đụng `SILENCE_DURATION_MS`, ngưỡng VAD, hay `has_more_to_read`.
- **Không** chạy `scripts/log_antigravity.py` / `scripts/log_manual.py`; không sửa `.ai-log/`. Hook pre-push hỏng thì **báo**, không `--no-verify`.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/agents/nghe_tiep.py` | **Tạo.** Hàm thuần `con_nghe_tiep(state) -> bool` — chủ sở hữu **duy nhất** của quyết định "còn nghe tiếp". | 2 |
| `src/agents/nodes/route.py` | **Sửa.** Bỏ việc ghi `mo_mic_ngan` (chuyển chủ sở hữu sang Task 2). | 2 |
| `src/services/ivi_events.py` | **Sửa.** `assistant_response_payload` gọi `con_nghe_tiep`; luật im lặng cho lượt bắt tự động. | 2, 4 |
| `src/api/turns.py` | **Sửa.** Đọc header `X-Capture-Mode`, đưa `bat_tu_dong` vào state. | 1 |
| `src/agents/state.py` | **Sửa.** Thêm `bat_tu_dong: bool`. | 1 |
| `src/agents/nodes/route.py` | **Sửa.** Câu giải tán khi không có gì đang chờ. | 3 |
| `frontend/src/lib/wake-word/wakeWordState.ts` | **Sửa.** `COOLDOWN_ELAPSED` mang `keepListening`; thêm bộ đếm lượt nối. | 5 |
| `frontend/src/lib/wake-word/WakeWordController.ts` | **Sửa.** Trần đồng hồ tường; truyền `keepListening`. | 6 |
| `frontend/src/lib/services/turn/{types,real,mock}.ts` | **Sửa.** `sendVoice(audio, opts)` gửi `X-Capture-Mode`; đọc `moMicNgan`. | 7 |
| `frontend/src/components/ivi/DriverShellProvider.tsx` | **Sửa.** Nuôi `pendingKeepListeningRef`; báo chế độ bắt. | 7 |
| `scripts/do_phan_bo_luot.py` | **Tạo.** Đọc `TraceStore`, in phân bố kết cục lượt thật. | 8 |
| `docs/adr/ADR-028-cua-so-nghe-tiep.md` | **Tạo.** | 8 |

---

## Task 1: Backend biết lượt nào bắt tự động

**Files:**
- Modify: `src/api/turns.py` (hàm `submit_voice_turn`)
- Modify: `src/agents/state.py`
- Test: `tests/test_api/test_capture_mode.py` (tạo)

**Interfaces:**
- Produces: state key `bat_tu_dong: bool` — Task 4 đọc nó.
- Produces: header `X-Capture-Mode` nhận `"auto"` / `"manual"`; **vắng = `manual`**.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_api/test_capture_mode.py`:

```python
"""Backend phải biết lượt nào do mic TỰ MỞ bắt được. Spec §3.5.

Vì sao tin lời khai của client ở đây, trong khi `mau_slot` (#373) từ chối tin: khác về
**hướng**. Khai `auto` chỉ khiến xe **im hơn**, không bao giờ khiến nó **dễ dãi hơn**.
Client nói dối thì hậu quả là xe im lúc đáng nói — khó chịu, không nguy hiểm.

Vắng header = `manual`, nên client cũ không đổi hành vi một chút nào.
"""

from __future__ import annotations

import pytest

from src.api.turns import doc_che_do_bat


@pytest.mark.parametrize(
    ("header", "mong"),
    [
        ("auto", True),
        ("AUTO", True),
        ("manual", False),
        (None, False),
        ("", False),
        ("gi_do_la", False),
    ],
)
def test_doc_che_do_bat(header: str | None, mong: bool):
    assert doc_che_do_bat(header) is mong


def test_gia_tri_la_khong_lam_hong_luot():
    """Header là dữ liệu ngoài. Giá trị lạ phải lui về `manual` chứ không ném lỗi —
    một lượt nói của tài xế không được chết vì một chuỗi header sai chính tả."""
    assert doc_che_do_bat("auto; charset=utf-8") is False
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_capture_mode.py -q
```

Expected: FAIL — `ImportError: cannot import name 'doc_che_do_bat'`

- [ ] **Step 3: Cài đặt**

Trong `src/api/turns.py`, thêm gần đầu file (sau các import):

```python
def doc_che_do_bat(x_capture_mode: str | None) -> bool:
    """Lượt này có phải do mic **tự mở** bắt được không? Spec §3.5.

    Vắng header = `manual`, có chủ ý: client cũ không đổi hành vi một chút nào, và
    "không khai" phải nghĩa là "chế độ ồn ào hơn" chứ không phải "chế độ im hơn" —
    fail về phía nói, không về phía im.

    Chỉ nhận đúng chuỗi `auto` (không phân biệt hoa thường). Mọi giá trị khác lui về
    `manual` chứ **không** ném lỗi: header là dữ liệu ngoài, và một lượt nói của tài xế
    không được chết vì một chuỗi sai chính tả.
    """
    return (x_capture_mode or "").strip().casefold() == "auto"
```

Trong chữ ký `submit_voice_turn`, thêm tham số (đặt sau `request: Request`):

```python
    x_capture_mode: str | None = Header(default=None, alias="X-Capture-Mode"),
```

Thêm `Header` vào import từ `fastapi` nếu chưa có.

Tìm chỗ dựng state đưa vào graph (nơi đã có `"query"`), thêm:

```python
        "bat_tu_dong": doc_che_do_bat(x_capture_mode),
```

Trong `src/agents/state.py`, thêm ngay trên `mo_mic_ngan`:

```python
    #: Lượt này do mic **tự mở** bắt được (`X-Capture-Mode: auto`), hay do tài xế chủ
    #: động bấm mic / nói wake word. Quyết định luật im lặng ở `ivi_events`: bắt tự động
    #: mà xe không hiểu thì **không nói gì** — xem spec §3.5.
    #:
    #: Đây là thứ **client tự khai**, và tin được vì nó chỉ khiến xe im hơn, không bao
    #: giờ khiến xe dễ dãi hơn. Rào chắn `mau_slot` KHÔNG đọc trường này.
    bat_tu_dong: bool
```

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_capture_mode.py -q
```

Expected: PASS (7 ca)

- [ ] **Step 5: Không làm hỏng gì**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
ruff check src/ tests/ scripts/
```

Expected: PASS, không lỗi lint.

- [ ] **Step 6: Commit**

```bash
git add tests/test_api/test_capture_mode.py src/api/turns.py src/agents/state.py
git commit -m "feat(api): X-Capture-Mode cho biet luot nao do mic tu mo bat duoc"
```

---

## Task 2: `con_nghe_tiep` — một chủ sở hữu duy nhất cho quyết định

**Files:**
- Create: `src/agents/nghe_tiep.py`
- Modify: `src/agents/nodes/route.py` (bỏ 5 chỗ ghi `mo_mic_ngan`)
- Modify: `src/services/ivi_events.py` (`assistant_response_payload`)
- Modify: `tests/test_agents/test_mau_slot.py` (4 test chuyển tầng)
- Test: `tests/test_agents/test_nghe_tiep.py` (tạo)

**Interfaces:**
- Consumes: state keys `outcome`, `route_reason`, `intent`.
- Produces: `con_nghe_tiep(state: Mapping[str, Any]) -> bool`; hằng `LY_DO_DONG: frozenset[str]`.

**Vì sao chuyển chỗ tính:** `route_node` chỉ thấy `clarify`/`offer`, **không** thấy `completed` — mà `completed` là ~90% lượt và là ca chính của cả tính năng. Để hai nơi cùng ghi một field là cách chắc chắn để chúng lệch nhau.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_agents/test_nghe_tiep.py`:

```python
"""Cửa sổ nghe tiếp mở khi nào — phanh 1 của spec §3.1.

FE chỉ nghe thấy **tiếng**; nó không phân biệt được `"mức 2"` với `"lát nữa mở cốp lấy
đồ nhé"`. Chỉ backend biết lượt vừa rồi xe **có hiểu gì không**, nên phanh chính nằm ở đây.

Đo được (graph thật, 29/08) — ba câu người nói với NGƯỜI, mic đang mở:

    "Lát nữa mở cốp lấy đồ nhé"    -> not_control/default_to_manual
    "Hôm qua tôi bật đèn pha suốt" -> not_control/default_to_manual
    "Thôi tắt nhạc đi để anh nghe điện" -> not_control/default_to_manual

Cả ba rơi vào `default_to_manual`, nên đóng cửa sổ ở đó là chặn được cảnh xe chen vào
cuộc nói chuyện ngay sau câu đầu tiên.
"""

from __future__ import annotations

import pytest

from src.agents.nghe_tiep import LY_DO_DONG, con_nghe_tiep


@pytest.mark.parametrize(
    "state",
    [
        {"outcome": "completed", "route_reason": "deterministic_rule"},
        {"outcome": "clarify", "route_reason": "missing_fan_level"},
        {"outcome": "offer", "route_reason": "question_about_supported_action"},
        {"outcome": "not_control", "route_reason": "manual_question", "intent": "manual_query"},
        {"outcome": "not_control", "route_reason": "tire_pressure_all", "intent": "tire_pressure_query"},
    ],
)
def test_hoi_thoai_dang_chay_thi_con_nghe(state: dict):
    assert con_nghe_tiep(state) is True


@pytest.mark.parametrize(
    "state",
    [
        # Xe không hiểu — nhiều khả năng câu ấy không nói với xe.
        {"outcome": "not_control", "route_reason": "default_to_manual"},
        {"outcome": "grounded_refusal", "route_reason": "default_to_manual"},
        # #373 đã chốt: nghe hụt thì trả quyền chủ động về tài xế.
        {"outcome": "not_control", "route_reason": "manh_khong_khop_mau"},
        # Tài xế vừa nói "thôi".
        {"outcome": "not_control", "route_reason": "offer_declined"},
        {"outcome": "not_control", "route_reason": "giai_tan"},
        # Không có gì để nối tiếp.
        {"outcome": "blocked", "route_reason": "deterministic_rule"},
        {"outcome": "denied", "route_reason": "headlight_off_not_permitted"},
        {"outcome": "validation_denied", "route_reason": "deterministic_rule"},
    ],
)
def test_khong_con_gi_de_noi_tiep_thi_dong(state: dict):
    assert con_nghe_tiep(state) is False


def test_clarify_khong_co_mau_thi_dong():
    """Nửa còn lại của "một tập, hai vai" (#373): slot không có rào chắn thì không mở mic.

    `relative_change_unsupported` nằm ngoài `mau_slot.CO_MAU`, nên dù nó là `clarify` —
    tức xe **có** hỏi — ta vẫn không mở cửa sổ, vì không có gì soi câu trả lời.
    """
    assert con_nghe_tiep({"outcome": "clarify", "route_reason": "relative_change_unsupported"}) is False


def test_state_rong_hay_hong_thi_dong():
    """Fail-closed: không đọc được kết cục thì **không** mở mic. Mở nhầm là mở một cửa
    không ai rào; đóng nhầm chỉ là bắt tài xế nói lại wake word."""
    for state in ({}, {"outcome": None}, {"outcome": "khong_ton_tai"}, {"outcome": 42}):
        assert con_nghe_tiep(state) is False


def test_ly_do_dong_thang_ca_khi_outcome_nghe_co_ve_on():
    """`manh_khong_khop_mau` mang `outcome = "not_control"`, mà `not_control` một mình
    không nói được gì. Lý do mới là thứ phân biệt — nên nó phải thắng."""
    assert "manh_khong_khop_mau" in LY_DO_DONG
    assert con_nghe_tiep({"outcome": "not_control", "route_reason": "manh_khong_khop_mau"}) is False
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_nghe_tiep.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.agents.nghe_tiep'`

- [ ] **Step 3: Tạo module**

Tạo `src/agents/nghe_tiep.py`:

```python
"""Cửa sổ nghe tiếp còn mở hay đóng — phanh 1 của spec §3.1.

## Vì sao quyết định này nằm ở BACKEND

FE chỉ nghe thấy **tiếng**. Nó không phân biệt được `"mức 2"` (câu trả lời) với
`"lát nữa mở cốp lấy đồ nhé"` (nói với người ngồi cạnh). Chỉ backend biết lượt vừa rồi
xe **có hiểu gì không**, nên phanh chính phải nằm ở đây.

## Vì sao ở đây chứ không ở `route_node`

`route_node` chỉ thấy `clarify`/`offer`/`control` — nó **không** thấy `completed`, mà
`completed` là ~90% lượt và là ca chính của cả tính năng. Quyết định phải đọc kết cục
CUỐI của lượt, nên nó đọc state cuối, một lần, ở `assistant_response_payload`.

Trước spec này, `route_node` tự ghi `mo_mic_ngan` (#373). Hai nơi cùng ghi một field là
cách chắc chắn để chúng lệch nhau, nên module này là **chủ sở hữu duy nhất**.

## Luật, và nó fail-closed

Mở khi hội thoại **đang chạy**; đóng khi xe **không hiểu** hoặc **không còn gì nối tiếp**.
Không đọc được kết cục thì **đóng**: mở nhầm là mở một cửa không ai rào, còn đóng nhầm
chỉ là bắt tài xế nói lại wake word.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.mau_slot import CO_MAU

__all__ = ["LY_DO_DONG", "OUTCOME_CON_NGHE", "con_nghe_tiep"]

#: Kết cục mà hội thoại còn đang chạy. `completed` là ca chính (~90% lượt đo được 29/08).
OUTCOME_CON_NGHE: frozenset[str] = frozenset({"completed", "offer"})

#: Lý do **luôn** đóng, kể cả khi `outcome` trông có vẻ ổn.
#:
#: `manh_khong_khop_mau` mang `outcome = "not_control"` — mà `not_control` một mình không
#: nói được gì, vì nó cũng là nhãn của một câu trả lời sổ tay thành công. Lý do mới là
#: thứ phân biệt, nên nó phải thắng.
LY_DO_DONG: frozenset[str] = frozenset(
    {
        # Xe không hiểu — nhiều khả năng câu ấy không nói với xe. Đo được: cả ba câu
        # người-nói-với-người đều rơi vào đây.
        "default_to_manual",
        # #373: nghe hụt thì trả quyền chủ động về tài xế.
        "manh_khong_khop_mau",
        # Tài xế vừa nói "thôi".
        "offer_declined",
        "giai_tan",
    }
)

#: Intent mà xe **trả lời được** một câu hỏi — hội thoại đang chạy dù `outcome` là
#: `not_control`.
_INTENT_CON_NGHE: frozenset[str] = frozenset({"manual_query", "tire_pressure_query", "manual_continue"})


def con_nghe_tiep(state: Mapping[str, Any]) -> bool:
    """Sau lượt này có nên để mic mở chờ câu tiếp theo không?"""
    ly_do = state.get("route_reason")
    if isinstance(ly_do, str) and ly_do in LY_DO_DONG:
        return False

    outcome = state.get("outcome")
    if not isinstance(outcome, str):
        return False
    if outcome in OUTCOME_CON_NGHE:
        return True
    if outcome == "clarify":
        # "Một tập, hai vai" của #373: chỉ mở mic ở slot có rào chắn.
        return isinstance(ly_do, str) and ly_do in CO_MAU
    if outcome == "not_control":
        intent = state.get("intent")
        return isinstance(intent, str) and intent in _INTENT_CON_NGHE
    return False
```

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_nghe_tiep.py -q
```

Expected: PASS (18 ca)

- [ ] **Step 5: Chuyển chủ sở hữu — bỏ `mo_mic_ngan` khỏi `route_node`**

Trong `src/agents/nodes/route.py`, xoá **cả 5** dòng `"mo_mic_ngan": ...` (4 dòng `False`
ở các lối ra sớm, 1 dòng điều kiện `decision.disposition == "clarify" and ...`), và xoá
import `CO_MAU` nếu không còn dùng (`khop_mau` vẫn dùng).

Trong `src/services/ivi_events.py`, đổi dòng của `assistant_response_payload`:

```python
        "mo_mic_ngan": bool(result.get("mo_mic_ngan")),
```

thành:

```python
        # Chủ sở hữu DUY NHẤT của quyết định này là `src/agents/nghe_tiep.py`, và nó
        # đọc kết cục CUỐI của lượt. `route_node` cố ý không ghi trường này nữa: nó
        # không thấy `completed`, mà `completed` là ~90% lượt.
        "mo_mic_ngan": con_nghe_tiep(result),
```

Thêm import ở đầu `ivi_events.py`:

```python
from src.agents.nghe_tiep import con_nghe_tiep
```

- [ ] **Step 6: Chuyển tầng 4 test của `mau_slot`**

Trong `tests/test_agents/test_mau_slot.py`, 4 test đọc `mo_mic_ngan` từ update của
`route_node` nay phải đọc qua payload. Thay:

- trong `test_manh_khong_khop_thi_khong_chay_lenh_nao`: xoá dòng
  `assert l2["mo_mic_ngan"] is False, ...`
- xoá hẳn ba test `test_chi_clarify_co_mau_moi_mo_mic`,
  `test_luot_khong_phai_cau_hoi_lai_thi_khong_mo_mic`, `test_moi_luot_deu_tra_ve_co_mo_mic`,
  `test_mo_mic_tat_ngay_o_luot_sau`

và thêm vào cuối file:

```python
# --- Cờ mở mic nay do `nghe_tiep` sở hữu, đọc qua payload -------------------


def _co_mo_mic(update: dict) -> bool:
    from src.services.ivi_events import assistant_response_payload

    return assistant_response_payload(dict(update))["mo_mic_ngan"]


async def test_clarify_co_mau_thi_mo_mic():
    p = Phien()
    assert _co_mo_mic(await p.noi("Tăng quạt gió")) is True


async def test_manh_khong_khop_thi_dong_mic():
    p = Phien()
    await p.noi("Tăng quạt gió")
    assert _co_mo_mic(await p.noi("hai giờ nhé")) is False


async def test_clarify_khong_co_mau_thi_khong_mo_mic():
    """`relative_change_unsupported` nằm ngoài `CO_MAU` — xe có hỏi, nhưng không có rào
    chắn nào soi câu trả lời, nên không mở."""
    p = Phien()
    ra = await p.noi("tăng âm lượng thêm 10")
    assert ra["route_reason"] == "relative_change_unsupported"
    assert _co_mo_mic(ra) is False
```

- [ ] **Step 7: Chạy toàn bộ + lint**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn
ruff check src/ tests/ scripts/
```

Expected: PASS; `DI LUI=0`; lint sạch.

*Nếu `test_clarify_khong_co_mau_thi_khong_mo_mic` đỏ vì `"tăng âm lượng thêm 10"` không ra
`relative_change_unsupported`, chạy `.\.venv\Scripts\python.exe -c "from src.agents.router import DeterministicControlRouter as R; print(R().route('tăng âm lượng thêm 10'))"` và thay bằng câu thật sự cho ra lý do ấy.*

- [ ] **Step 8: Commit**

```bash
git add src/agents/nghe_tiep.py tests/test_agents/test_nghe_tiep.py src/agents/nodes/route.py src/services/ivi_events.py tests/test_agents/test_mau_slot.py
git commit -m "refactor(agent): con_nghe_tiep so huu quyet dinh mo mic, doc ket cuc CUOI cua luot"
```

---

## Task 3: Câu giải tán đóng cửa sổ

**Files:**
- Modify: `src/agents/nodes/route.py`
- Modify: `src/agents/contracts.py` (thêm intent `giai_tan`)
- Modify: `src/agents/graph.py` (đi thẳng compose)
- Modify: `src/agents/nodes/compose.py` (câu đáp)
- Test: `tests/test_agents/test_giai_tan.py` (tạo)

**Interfaces:**
- Consumes: `voice_intent.doc_tra_loi_co_khong` (đã có), `LY_DO_DONG` từ Task 2.
- Produces: `outcome="not_control"`, `route_reason="giai_tan"`, `intent="giai_tan"`.

**Chỉ áp dụng khi KHÔNG có gì đang chờ.** Một tiếng `"thôi"` khi có `offer` treo đã có nghĩa "từ chối đề nghị" (#367), khi có phê duyệt chờ đã có nghĩa "bác". Cả hai đường ấy chạy **trước**, và test dưới khoá thứ tự đó.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_agents/test_giai_tan.py`:

```python
"""Tài xế nói "thôi" để đuổi trợ lý đi — phanh 3 của spec §3.3.

Không có nó thì cách duy nhất đóng cửa sổ đang mở là **im lặng 6 giây**, mà trong xe có
người ngồi cạnh đang nói chuyện thì sáu giây im lặng gần như không tới.

Dùng lại `voice_intent.doc_tra_loi_co_khong` — không viết bảng từ thứ hai. Hai bảng từ
song song là đúng thứ #107 cảnh báo sẽ lệch nhau.
"""

from __future__ import annotations

import pytest

from src.agents.nghe_tiep import con_nghe_tiep
from src.agents.nodes.route import make_route_node
from src.agents.router import DeterministicControlRouter


class Phien:
    def __init__(self) -> None:
        self.node = make_route_node(DeterministicControlRouter())
        self.state: dict = {}

    async def noi(self, text: str) -> dict:
        self.state["query"] = text
        update = await self.node(self.state)
        self.state.update(update)
        return update


@pytest.mark.parametrize("cau", ["thôi", "Thôi", "cảm ơn", "không cần", "thôi nhé"])
async def test_cau_giai_tan_dong_cua_so(cau: str):
    p = Phien()
    ra = await p.noi(cau)
    assert ra["outcome"] == "not_control"
    assert ra["route_reason"] == "giai_tan"
    assert con_nghe_tiep(ra) is False


async def test_giai_tan_khong_cuop_luot_tu_choi_de_nghi():
    """Thứ tự bắt buộc: khi có `offer` treo, `"thôi"` nghĩa là **từ chối đề nghị** (#367),
    không phải đuổi trợ lý. Hai lối ra khác nhau và tài xế cần nghe đúng câu."""
    p = Phien()
    await p.noi("Bật điều hòa được không")
    ra = await p.noi("thôi")
    assert ra["route_reason"] == "offer_declined"


async def test_giai_tan_khong_cuop_manh_tra_loi():
    """Sau một câu hỏi lại, `"thôi"` không phải câu trả lời cho slot — nhưng nó cũng
    không được nuốt mất đường ghép của một mảnh hợp lệ ở lượt sau."""
    p = Phien()
    await p.noi("Tăng quạt gió")
    assert (await p.noi("thôi"))["route_reason"] == "giai_tan"
    ra = await p.noi("mức 2")
    assert ra["outcome"] == "control"


async def test_cau_thuong_khong_bi_doc_thanh_giai_tan():
    for cau in ("Bật điều hòa", "Tắt nhạc", "Camp Mode là gì", "thôi tắt nhạc đi"):
        p = Phien()
        assert (await p.noi(cau))["route_reason"] != "giai_tan", cau


async def test_giai_tan_noi_mot_cau_ngan_chu_khong_tra_so_tay():
    from src.agents.nodes.compose import compose_node

    p = Phien()
    await p.noi("thôi")
    ra = await compose_node(p.state)
    assert "sổ tay" not in ra["speak_text"]
    assert len(ra["speak_text"]) <= 40
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_giai_tan.py -q
```

Expected: FAIL — `route_reason` là `default_to_manual`, không phải `giai_tan`.

- [ ] **Step 3: Cài đặt**

`src/agents/contracts.py` — thêm vào danh sách intent, ngay trước `"none"`:

```python
    #: Tài xế đuổi trợ lý đi — *"thôi"*, *"cảm ơn"*, *"không cần"* khi **không có gì đang
    #: chờ**. Tách khỏi `none` vì lượt này có nghĩa: nó đóng cửa sổ nghe tiếp. Gộp vào
    #: `none` thì nó rơi xuống tra sổ tay và tài xế đuổi trợ lý lại được đọc cho nghe
    #: một đoạn sổ tay về chữ "thôi".
    "giai_tan",
```

`src/agents/nodes/route.py` — trong `route_node`, đặt **sau** cổng `_dap_loi_de_nghi` và
**trước** `_ghep_manh_tra_loi`:

```python
        if _la_cau_giai_tan(state, decision):
            logger.info("tài xế đuổi trợ lý: %r", state.get("query", ""))
            return {
                "route_decision": decision,
                "route_source": decision.route_source,
                "intent": "giai_tan",
                "confidence": decision.confidence,
                "outcome": "not_control",
                "route_reason": "giai_tan",
                "da_ghep_hoi_lai": False,
                **_moc_de_nghi(None, dong_ho),
            }
```

và thêm hàm cổng:

```python
def _la_cau_giai_tan(state: AgentState, decision) -> bool:
    """Lượt này có phải tài xế **đuổi trợ lý đi** không? Spec §3.3.

    Ba chốt, và cả ba đều là "đừng cướp lượt của cơ chế khác":

    1. **Chỉ khi luật không bắt được gì.** `"thôi tắt nhạc đi"` là một lệnh, không phải
       một câu đuổi.
    2. **Chỉ khi không có đề nghị treo.** Cổng `_dap_loi_de_nghi` chạy trước và đã biến
       `"thôi"` thành `offer_declined` — hai lối ra khác nhau, tài xế cần nghe đúng câu.
       (Phê duyệt HITL thì bị chặn từ `turns.py`, còn trước cả graph.)
    3. **Chỉ nhận lời đáp thuần.** `doc_tra_loi_co_khong` đòi mọi từ là từ đáp hoặc từ
       đệm, nên `"thôi tắt nhạc đi để anh nghe điện"` trả `None`.

    KHÔNG xoá ngữ cảnh hỏi lại: tài xế có thể đổi ý và trả lời ở lượt sau.
    """
    if decision.disposition != "not_control" or decision.reason != "default_to_manual":
        return False
    if state.get("cho_nhan_plan") is not None:
        return False
    return doc_tra_loi_co_khong(state.get("query", "") or "") == "khong"
```

`src/agents/graph.py` — thêm ngay sau nhánh `manh_khong_khop_mau`:

```python
        # Câu đuổi trợ lý đi thẳng compose: không có gì để tra cứu.
        if state.get("intent") == "giai_tan":
            return "compose"
```

`src/agents/nodes/compose.py` — thêm hằng cạnh `TU_CHOI_DE_NGHI`:

```python
#: Câu đáp khi tài xế đuổi trợ lý đi. Ngắn nhất có thể: họ vừa bảo thôi, thứ tệ nhất
#: lúc ấy là một câu dài.
GIAI_TAN = "Vâng."
```

và trong `compose_node`, ngay sau nhánh `manh_khong_khop_mau`:

```python
    if state.get("intent") == "giai_tan":
        return {"response_text": GIAI_TAN, "speak_text": GIAI_TAN, "has_more_to_read": False}
```

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_giai_tan.py -q
```

Expected: PASS (12 ca)

- [ ] **Step 5: Toàn bộ + bộ đo + lint**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn
ruff check src/ tests/ scripts/
```

Expected: PASS; `DI LUI=0`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_agents/test_giai_tan.py src/agents/nodes/route.py src/agents/contracts.py src/agents/graph.py src/agents/nodes/compose.py
git commit -m "feat(agent): cau giai tan dong cua so nghe tiep"
```

---

## Task 4: Luật im lặng — xe không chen vào cuộc nói chuyện của người

**Files:**
- Modify: `src/services/ivi_events.py`
- Test: `tests/test_services/test_im_lang_bat_tu_dong.py` (tạo)

**Interfaces:**
- Consumes: state key `bat_tu_dong` (Task 1), `con_nghe_tiep` (Task 2).
- Produces: `assistant_response_payload` trả `speak_text == ""` cho lượt bắt tự động mà xe không hiểu.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/test_services/test_im_lang_bat_tu_dong.py`:

```python
"""Xe chỉ nói khi được gọi — spec §3.5.

Đo bằng graph thật (29/08), người nói với NGƯỜI, mic đang mở:

    "Lát nữa mở cốp lấy đồ nhé"          -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
    "Hôm qua tôi bật đèn pha suốt"       -> "Tôi không tìm thấy thông tin này trong sổ tay xe."
    "Thôi tắt nhạc đi để anh nghe điện"  -> "Tôi không tìm thấy thông tin này trong sổ tay xe."

Xe **chen vào cuộc nói chuyện**, vài giây một lần. Chạy nhầm một lệnh thì tắt đi là xong;
cái này khiến người ta tắt luôn trợ lý.

Chỉ tắt **kênh nói**. Màn hình vẫn hiện, vì nó không làm phiền ai.
"""

from __future__ import annotations

from src.services.ivi_events import assistant_response_payload

KHONG_HIEU = {
    "response_text": "Tôi không tìm thấy thông tin này trong sổ tay xe.",
    "speak_text": "Tôi không tìm thấy thông tin này trong sổ tay xe.",
    "outcome": "grounded_refusal",
    "route_reason": "default_to_manual",
}


def test_bat_tu_dong_ma_khong_hieu_thi_im_lang():
    ra = assistant_response_payload({**KHONG_HIEU, "bat_tu_dong": True})
    assert ra["speak_text"] == ""
    assert ra["mo_mic_ngan"] is False


def test_van_hien_tren_man_hinh():
    """Chỉ tắt kênh NÓI. Màn hình không làm phiền cuộc nói chuyện nào, và nó là dấu vết
    để tài xế hiểu vì sao vòng đếm ngược vừa tắt."""
    ra = assistant_response_payload({**KHONG_HIEU, "bat_tu_dong": True})
    assert ra["display_text"] == KHONG_HIEU["response_text"]


def test_bam_mic_tay_thi_van_noi():
    """Tài xế chủ động hỏi thì im lặng mới là thô lỗ — họ đang chờ một câu trả lời."""
    ra = assistant_response_payload({**KHONG_HIEU, "bat_tu_dong": False})
    assert ra["speak_text"] == KHONG_HIEU["speak_text"]


def test_vang_co_thi_van_noi():
    """Vắng `bat_tu_dong` = `manual`. Fail về phía NÓI, không về phía im: một client cũ
    không được biến thành một trợ lý câm."""
    ra = assistant_response_payload(KHONG_HIEU)
    assert ra["speak_text"] == KHONG_HIEU["speak_text"]


def test_bat_tu_dong_ma_HIEU_thi_van_noi():
    """Ca đối chứng, và nó là ca thường gặp nhất: tài xế nối lệnh thứ hai trong cửa sổ
    nghe tiếp. Im lặng ở đây là bỏ mất câu xác nhận *"đã chỉnh quạt gió mức 2"* — thứ
    duy nhất cho họ biết xe vừa làm gì."""
    ra = assistant_response_payload(
        {
            "response_text": "Đã thực hiện lệnh trên xe mô phỏng.",
            "speak_text": "Đã thực hiện lệnh trên xe mô phỏng.",
            "outcome": "completed",
            "route_reason": "deterministic_rule",
            "bat_tu_dong": True,
        }
    )
    assert ra["speak_text"] == "Đã thực hiện lệnh trên xe mô phỏng."
    assert ra["mo_mic_ngan"] is True


def test_bat_tu_dong_ma_nghe_hut_cung_im():
    """`manh_khong_khop_mau` sau một cửa sổ tự mở: câu "Tôi chưa nghe rõ…" là đúng khi
    tài xế bấm mic, nhưng khi mic tự mở thì rất có thể họ không hề nói với xe."""
    ra = assistant_response_payload(
        {
            "response_text": "Tôi chưa nghe rõ. Bạn muốn quạt gió mức mấy, từ 0 đến 3?",
            "speak_text": "Tôi chưa nghe rõ. Bạn muốn quạt gió mức mấy, từ 0 đến 3?",
            "outcome": "not_control",
            "route_reason": "manh_khong_khop_mau",
            "bat_tu_dong": True,
        }
    )
    assert ra["speak_text"] == ""
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_im_lang_bat_tu_dong.py -q
```

Expected: FAIL — `speak_text` vẫn là câu từ chối.

- [ ] **Step 3: Cài đặt**

Trong `src/services/ivi_events.py`, ngay trên `assistant_response_payload`:

```python
def _im_lang(result: dict[str, Any]) -> bool:
    """Lượt bắt tự động mà xe không hiểu thì **không nói gì** — spec §3.5.

    Đo được: ba câu người-nói-với-người đều rơi vào `default_to_manual`, và xe đọc
    *"Tôi không tìm thấy thông tin này trong sổ tay xe."* vào giữa cuộc nói chuyện của
    họ. Đó là thứ khiến người ta tắt trợ lý, tệ hơn một lệnh chạy nhầm.

    Dùng lại đúng `con_nghe_tiep` chứ không có bảng riêng: "không đáng nghe tiếp" và
    "không đáng nói ra" là **cùng một** phán đoán — xe vừa không hiểu câu vừa rồi.

    Chỉ tắt kênh **nói**; `display_text` giữ nguyên, vì màn hình không làm phiền ai và
    nó là dấu vết để tài xế hiểu vì sao vòng đếm ngược vừa tắt.
    """
    return bool(result.get("bat_tu_dong")) and not con_nghe_tiep(result)
```

và trong `assistant_response_payload`, đổi dòng `speak_text`:

```python
        "speak_text": "" if _im_lang(result) else (result.get("speak_text") or text),
```

Ngoài ra, tìm chỗ gọi `voice.synthesize_wav()` trong `emit_turn_lifecycle` và bọc nó để
không tổng hợp gì khi `speak_text` rỗng (nếu chưa có sẵn phép kiểm ấy):

```python
    if noi_ra := payload.get("speak_text"):
        ...  # nhánh TTS hiện có, dùng `noi_ra`
```

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_im_lang_bat_tu_dong.py -q
```

Expected: PASS (6 ca)

- [ ] **Step 5: Toàn bộ + lint**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
ruff check src/ tests/ scripts/
```

Expected: PASS. *Nếu có test cũ đòi `assistant.speech` luôn được phát, đọc nó trước khi
sửa: nếu nó khoá "TTS fail-open" thì giữ, chỉ nới điều kiện thành "có `speak_text`".*

- [ ] **Step 6: Cập nhật `docs/api_spec.md`**

Tìm đoạn mô tả `mo_mic_ngan` (thêm bởi #373) và nối vào cuối:

```markdown
Từ 2026-08-29, `mo_mic_ngan` do `src/agents/nghe_tiep.py` tính từ **kết cục cuối** của lượt, không còn do `route_node` ghi — vì `route_node` không thấy `completed`, mà `completed` là ~90% lượt. Cùng ngày, `POST /turns/voice` nhận header `X-Capture-Mode: auto | manual` (vắng = `manual`): lượt `auto` mà xe không hiểu sẽ trả `speak_text` **rỗng** — xe chỉ nói khi được gọi, xem `docs/superpowers/specs/2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md` §3.5.
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_services/test_im_lang_bat_tu_dong.py src/services/ivi_events.py docs/api_spec.md
git commit -m "feat(ivi): luot bat tu dong ma xe khong hieu thi im lang"
```

---

## Task 5: FE — máy trạng thái nhận `keepListening` và đếm lượt nối

**Files:**
- Modify: `frontend/src/lib/wake-word/wakeWordState.ts`
- Test: `frontend/src/lib/wake-word/wakeWordState.test.ts`

**Interfaces:**
- Produces: `WakeEvent` biến thể `{ type: "COOLDOWN_ELAPSED"; keepListening: boolean }` (thay `hasMoreToRead`).
- Produces: `WakeMachine.followUpCount: number`; hằng `MAX_CHAINED_FOLLOW_UPS = 5`.

- [ ] **Step 1: Viết test đỏ**

Thêm vào cuối `frontend/src/lib/wake-word/wakeWordState.test.ts`:

```typescript
import { MAX_CHAINED_FOLLOW_UPS, transition, type WakeMachine } from "./wakeWordState";

/**
 * Ngân sách cứng — phanh 2 của spec §3.2.
 *
 * Phanh 1 (`keepListening` từ backend) dựa vào "xe hiểu được". Nhưng
 * "Trời nóng quá bật điều hòa lên đi em" nói với NGƯỜI thì xe cũng hiểu được và cũng
 * `completed` — đo được 29/08. Nên cần một trần KHÔNG phụ thuộc nội dung.
 */
describe("ngân sách lượt nối", () => {
  const sauKhiXuLy = (followUpCount: number): WakeMachine => ({
    state: "PROCESSING",
    waitingForTts: false,
    waitingForCooldown: true,
    followUpCount,
  });

  it("mở cửa sổ khi backend bảo còn nghe và chưa chạm trần", () => {
    const m = transition(sauKhiXuLy(0), { type: "COOLDOWN_ELAPSED", keepListening: true });
    expect(m.state).toBe("FOLLOW_UP_WINDOW");
    expect(m.followUpCount).toBe(1);
  });

  it("không mở khi backend bảo thôi, dù chưa chạm trần", () => {
    const m = transition(sauKhiXuLy(0), { type: "COOLDOWN_ELAPSED", keepListening: false });
    expect(m.state).toBe("LISTENING_FOR_WAKEWORD");
  });

  it("chạm trần thì về nghe tên gọi dù backend còn bảo nghe tiếp", () => {
    const m = transition(sauKhiXuLy(MAX_CHAINED_FOLLOW_UPS), { type: "COOLDOWN_ELAPSED", keepListening: true });
    expect(m.state).toBe("LISTENING_FOR_WAKEWORD");
  });

  it("wake word reset bộ đếm — mỗi lần gọi tên là một chuỗi mới", () => {
    const m = transition(
      { state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false, followUpCount: MAX_CHAINED_FOLLOW_UPS },
      { type: "WAKE_DETECTED" },
    );
    expect(m.followUpCount).toBe(0);
  });

  it("bấm mic tay cũng reset bộ đếm", () => {
    const m = transition(
      { state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false, followUpCount: 3 },
      { type: "MANUAL_ACTIVATE" },
    );
    expect(m.followUpCount).toBe(0);
  });

  it("hết giờ cửa sổ thì về nghe tên gọi và reset — im lặng đã cắt chuỗi", () => {
    const m = transition(
      { state: "FOLLOW_UP_WINDOW", waitingForTts: false, waitingForCooldown: false, followUpCount: 2 },
      { type: "FOLLOW_UP_TIMEOUT" },
    );
    expect(m.state).toBe("LISTENING_FOR_WAKEWORD");
    expect(m.followUpCount).toBe(0);
  });

  it("nói tiếp trong cửa sổ thì GIỮ bộ đếm — đó chính là thứ đang đếm", () => {
    const m = transition(
      { state: "FOLLOW_UP_WINDOW", waitingForTts: false, waitingForCooldown: false, followUpCount: 2 },
      { type: "FOLLOW_UP_SPEECH_DETECTED" },
    );
    expect(m.state).toBe("CAPTURING_COMMAND");
    expect(m.followUpCount).toBe(2);
  });

  it("DISABLE reset sạch", () => {
    const m = transition(
      { state: "FOLLOW_UP_WINDOW", waitingForTts: false, waitingForCooldown: false, followUpCount: 4 },
      { type: "DISABLE" },
    );
    expect(m.state).toBe("IDLE");
    expect(m.followUpCount).toBe(0);
  });
});
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
cd frontend; npm run test -- wakeWordState
```

Expected: FAIL — TypeScript báo `keepListening` không tồn tại trên `WakeEvent`, và
`followUpCount` không có trên `WakeMachine`.

- [ ] **Step 3: Cài đặt**

Trong `frontend/src/lib/wake-word/wakeWordState.ts`:

```typescript
/**
 * Trần số lượt nối liên tiếp kể từ một lần "Hey VIVI" — phanh 2 của spec §3.2.
 *
 * Phanh 1 (`keepListening` từ backend) dựa vào "xe hiểu được câu vừa rồi". Nhưng một câu
 * nói với NGƯỜI cũng có thể hiểu được: đo 29/08, "Trời nóng quá bật điều hòa lên đi em"
 * ra `completed`. Nên cần một trần không phụ thuộc nội dung.
 *
 * 5 là ước lượng, không phải số đo — chưa có vòng user research nào. Đo lại bằng
 * `scripts/do_phan_bo_luot.py` rồi chỉnh.
 */
export const MAX_CHAINED_FOLLOW_UPS = 5;
```

Đổi biến thể sự kiện:

```typescript
  /**
   * Backend có bảo còn nghe tiếp không (spec §3.1) — thay `hasMoreToRead` của #343.
   * Chỉ backend biết lượt vừa rồi xe có hiểu gì không; FE chỉ nghe thấy tiếng.
   */
  | { type: "COOLDOWN_ELAPSED"; keepListening: boolean }
```

Thêm vào `WakeMachine`:

```typescript
  /** Số lượt đã nối liên tiếp kể từ lần gọi tên gần nhất. Reset ở WAKE_DETECTED,
   *  MANUAL_ACTIVATE, FOLLOW_UP_TIMEOUT và DISABLE. */
  followUpCount: number;
```

Sửa `transition`:

```typescript
export function transition(machine: WakeMachine, event: WakeEvent): WakeMachine {
  if (event.type === "DISABLE") return { state: "IDLE", waitingForTts: false, waitingForCooldown: false, followUpCount: 0 };
  switch (machine.state) {
    case "IDLE":
      return event.type === "READY"
        ? { state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false, followUpCount: 0 }
        : machine;
    case "LISTENING_FOR_WAKEWORD":
      if (event.type === "WAKE_DETECTED") return { state: "ARMING", waitingForTts: false, waitingForCooldown: false, followUpCount: 0 };
      if (event.type === "MANUAL_ACTIVATE") return { state: "CAPTURING_COMMAND", waitingForTts: false, waitingForCooldown: false, followUpCount: 0 };
      return machine;
```

Các `case` còn lại: thêm `followUpCount: machine.followUpCount` vào mọi object trả về,
**trừ** hai chỗ sau.

`case "PROCESSING"`:

```typescript
      if (event.type === "COOLDOWN_ELAPSED" && machine.waitingForCooldown) {
        const conCho = event.keepListening && machine.followUpCount < MAX_CHAINED_FOLLOW_UPS;
        return {
          state: conCho ? "FOLLOW_UP_WINDOW" : "LISTENING_FOR_WAKEWORD",
          waitingForTts: false,
          waitingForCooldown: false,
          followUpCount: conCho ? machine.followUpCount + 1 : 0,
        };
      }
```

`case "FOLLOW_UP_WINDOW"`, nhánh timeout:

```typescript
      if (event.type === "FOLLOW_UP_TIMEOUT") return { state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false, followUpCount: 0 };
```

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
cd frontend; npm run test -- wakeWordState
```

Expected: PASS. *Test cũ dùng `hasMoreToRead` sẽ đỏ — sửa chúng sang `keepListening` và
thêm `followUpCount: 0` vào các `WakeMachine` dựng tay. Giữ nguyên ý nghĩa từng test.*

- [ ] **Step 5: Lint + toàn bộ FE**

```powershell
cd frontend; npm run test
cd frontend; npm run lint
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/wake-word/wakeWordState.ts frontend/src/lib/wake-word/wakeWordState.test.ts
git commit -m "feat(fe): may trang thai nhan keepListening va dem luot noi"
```

---

## Task 6: FE — trần đồng hồ tường trong controller

**Files:**
- Modify: `frontend/src/lib/wake-word/WakeWordController.ts`
- Test: `frontend/src/lib/wake-word/WakeWordController.test.ts`

**Interfaces:**
- Consumes: `MAX_CHAINED_FOLLOW_UPS`, `keepListening` (Task 5).
- Produces: `FOLLOW_UP_SESSION_MAX_MS = 60_000`; `responseBoundary(ttsPlaying: boolean, keepListening: boolean)`.

**Vì sao cần cả hai trần:** đếm lượt không chặn được một chuỗi lượt **ngắn** kéo dài mãi; đồng hồ tường không chặn được năm lượt dồn trong ba giây. Mỗi cái bịt một hình dạng khác nhau.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `frontend/src/lib/wake-word/WakeWordController.test.ts`:

```typescript
import { FOLLOW_UP_SESSION_MAX_MS } from "./WakeWordController";

/**
 * Trần đồng hồ tường — nửa còn lại của phanh 2 (spec §3.2).
 *
 * Đếm lượt không chặn được một chuỗi lượt NGẮN kéo dài mãi; đồng hồ tường không chặn
 * được năm lượt dồn trong ba giây. Mỗi cái bịt một hình dạng khác nhau, nên cần cả hai.
 */
describe("trần đồng hồ tường cho chuỗi nghe tiếp", () => {
  /** Dựng chuỗi: bấm mic, chờ `truoc` ms, rồi hết cooldown với backend bảo CÒN nghe. */
  async function chuoi(ctx: ReturnType<typeof setup>, truoc: number) {
    await ctx.controller.enable();
    await ctx.controller.activateManual();
    await vi.advanceTimersByTimeAsync(truoc);
    await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(false, true);
    await vi.advanceTimersByTimeAsync(500);
  }

  it("quá FOLLOW_UP_SESSION_MAX_MS thì không mở cửa sổ nữa", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await chuoi(ctx, FOLLOW_UP_SESSION_MAX_MS + 1);
    expect(ctx.callbacks.onFollowUpWindowStarted).not.toHaveBeenCalled();
  });

  it("trong hạn thì vẫn mở", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await chuoi(ctx, 1_000);
    expect(ctx.callbacks.onFollowUpWindowStarted).toHaveBeenCalled();
  });

  it("gọi tên lại thì đồng hồ chạy lại từ đầu", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await chuoi(ctx, FOLLOW_UP_SESSION_MAX_MS + 1);
    ctx.callbacks.onFollowUpWindowStarted.mockClear();
    await chuoi(ctx, 1_000);
    expect(ctx.callbacks.onFollowUpWindowStarted).toHaveBeenCalled();
  });
});
```

`setup()` là helper có thật của file này (dòng 33) — nó trả `{ pipeline, detector,
callbacks, controller }`. `describe("FOLLOW_UP_WINDOW")` sẵn có (dòng 339) đã dùng đúng
khuôn `enable → activateManual → stopCapture → responseBoundary → advanceTimers`; helper
`chuoi` ở trên chỉ thêm một quãng chờ vào giữa. **Đừng viết helper thứ hai.**

Khẳng định qua `callbacks.onFollowUpWindowStarted` chứ không qua `machine.state`, vì
`machine` là private — cùng cách các test FOLLOW_UP_WINDOW hiện có đang làm.

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
cd frontend; npm run test -- WakeWordController
```

Expected: FAIL — `FOLLOW_UP_SESSION_MAX_MS` chưa tồn tại.

- [ ] **Step 3: Cài đặt**

Trong `WakeWordController.ts`, cạnh `FOLLOW_UP_WINDOW_MS`:

```typescript
/**
 * Trần đồng hồ tường cho cả một chuỗi nghe tiếp, tính từ lần gọi tên gần nhất — phanh 2
 * của spec §3.2, nửa thứ hai.
 *
 * Đếm lượt (`MAX_CHAINED_FOLLOW_UPS`) không chặn được một chuỗi lượt NGẮN kéo dài mãi;
 * cái này thì có. Ngược lại nó không chặn được năm lượt dồn trong ba giây, nên cần cả hai.
 */
export const FOLLOW_UP_SESSION_MAX_MS = 60_000;
```

Thêm field:

```typescript
  /** `now()` lúc bắt đầu chuỗi hiện tại (gọi tên hoặc bấm mic). `0` = chưa có chuỗi nào. */
  private chuoiBatDauAt = 0;
```

Đặt `this.chuoiBatDauAt = Date.now()` ở đúng chỗ controller phát `WAKE_DETECTED` và
`MANUAL_ACTIVATE`. **Dùng `Date.now()`, không thêm nguồn thời gian vào `deps`:** controller
chỉ tiêm `setTimer`/`clearTimer`, và `vi.useFakeTimers()` của Vitest đã giả lập luôn
`Date.now()`, nên test vẫn điều khiển được thời gian mà không phải mở rộng hợp đồng
`deps`.

Đổi chữ ký:

```typescript
  responseBoundary(ttsPlaying: boolean, keepListening: boolean): void {
    ...
    this.pendingKeepListening = keepListening;
```

(đổi tên field `pendingHasMoreToRead` → `pendingKeepListening`), và tại chỗ phát
`COOLDOWN_ELAPSED`:

```typescript
    const conHan = this.chuoiBatDauAt > 0 && Date.now() - this.chuoiBatDauAt <= FOLLOW_UP_SESSION_MAX_MS;
    this.apply({ type: "COOLDOWN_ELAPSED", keepListening: this.pendingKeepListening && conHan });
```

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
cd frontend; npm run test -- WakeWordController
```

Expected: PASS

- [ ] **Step 5: Toàn bộ FE + lint**

```powershell
cd frontend; npm run test
cd frontend; npm run lint
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/wake-word/WakeWordController.ts frontend/src/lib/wake-word/WakeWordController.test.ts
git commit -m "feat(fe): tran dong ho tuong cho chuoi nghe tiep"
```

---

## Task 7: FE — nối dây tín hiệu và chế độ bắt

**Files:**
- Modify: `frontend/src/lib/services/turn/types.ts`
- Modify: `frontend/src/lib/services/turn/real.ts`
- Modify: `frontend/src/lib/services/turn/mock.ts`
- Modify: `frontend/src/components/ivi/DriverShellProvider.tsx`
- Test: `frontend/src/lib/services/turn/real.test.ts` (hoặc file test sẵn có của service)

**Interfaces:**
- Consumes: payload key `mo_mic_ngan` (Task 2), header `X-Capture-Mode` (Task 1).
- Produces: `AssistantResponse.moMicNgan: boolean`; `sendVoice(audio: Blob, opts?: { auto?: boolean })`.

- [ ] **Step 1: Viết test đỏ**

Thêm vào file test của turn service:

```typescript
/**
 * Nối dây hai chiều của cửa sổ nghe tiếp (spec §3.1 và §3.5).
 *
 * Thiếu field không được biến thành mở mic: `mo_mic_ngan` vắng phải là `false`, cùng
 * quy ước đã dùng cho `has_more_to_read` (xem docstring `hasMoreToRead` ở types.ts).
 */
describe("cửa sổ nghe tiếp", () => {
  it("đọc mo_mic_ngan từ assistant.response", () => {
    expect(parseAssistantResponse({ ...payloadToiThieu, mo_mic_ngan: true }).moMicNgan).toBe(true);
  });

  it("vắng field thì là false — thiếu tín hiệu không được biến thành mic mở", () => {
    expect(parseAssistantResponse(payloadToiThieu).moMicNgan).toBe(false);
  });

  it("sendVoice mặc định khai manual", async () => {
    const { headers } = await batFetch(() => turnService.sendVoice(blobWav));
    expect(headers["X-Capture-Mode"]).toBe("manual");
  });

  it("sendVoice khai auto khi cửa sổ tự mở bắt được", async () => {
    const { headers } = await batFetch(() => turnService.sendVoice(blobWav, { auto: true }));
    expect(headers["X-Capture-Mode"]).toBe("auto");
  });
});
```

*`parseAssistantResponse`, `payloadToiThieu`, `batFetch`, `blobWav` — dùng đúng helper mà
file test ấy đã có; nếu chưa có `batFetch`, dùng cách mock `fetch` mà các test khác trong
file đang dùng.*

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
cd frontend; npm run test -- turn
```

Expected: FAIL — `moMicNgan` không tồn tại; header không được gửi.

- [ ] **Step 3: Cài đặt**

`types.ts` — cạnh `hasMoreToRead`:

```typescript
  /**
   * Backend bảo còn nghe tiếp (spec §3.1) — client được mở mic ngắn cho câu sau, khỏi
   * phải nói lại wake word. Tính từ **kết cục cuối** của lượt: mở sau `completed` /
   * `clarify` có rào chắn / `offer`, đóng khi xe không hiểu.
   *
   * Vắng field = `false`. Thiếu tín hiệu không được biến thành mic mở — cùng quy ước
   * với `hasMoreToRead` ngay trên, và fail về phía an toàn.
   */
  moMicNgan: boolean;
```

và trong interface service:

```typescript
  /**
   * `auto` = lượt này do cửa sổ nghe tiếp tự bắt, không phải tài xế chủ động. Backend
   * dùng nó để **im lặng** thay vì đọc câu từ chối khi không hiểu (spec §3.5).
   */
  sendVoice(audio: Blob, opts?: { auto?: boolean }): Promise<{ turnId: string }>;
```

`real.ts` — cạnh dòng `hasMoreToRead: p.has_more_to_read === true`:

```typescript
          moMicNgan: p.mo_mic_ngan === true,
```

và trong `sendVoice`:

```typescript
  async sendVoice(audio, opts) {
    return withFreshSession(async () => {
      const res = await fetch(`${API_BASE}/turns/voice?session_id=${currentSessionId()}`, {
        method: "POST",
        headers: {
          ...authHeaders(),
          "X-Schema-Version": "1.0",
          "X-Capture-Mode": opts?.auto ? "auto" : "manual",
          "Idempotency-Key": `voice:${currentSessionId()}:${Date.now()}`,
          "Content-Type": audio.type || "audio/wav",
        },
        body: audio,
      });
```

`mock.ts` — đổi `async sendVoice(audio)` thành `async sendVoice(audio, _opts)` và thêm
`moMicNgan: false` vào mọi chỗ mock dựng một `AssistantResponse`.

`DriverShellProvider.tsx`:
- đổi tên `pendingHasMoreToReadRef` → `pendingKeepListeningRef` (5 chỗ), sửa docstring;
- dòng `pendingHasMoreToReadRef.current = event.result.hasMoreToRead;` thành
  `pendingKeepListeningRef.current = event.result.moMicNgan;`
- dòng `wakeControllerRef.current?.responseBoundary(activeSpeechRef.current !== null, pendingHasMoreToReadRef.current);`
  thành `...responseBoundary(activeSpeechRef.current !== null, pendingKeepListeningRef.current);`
- trong `stopVoice()`, truyền chế độ bắt:
  `await turnService.sendVoice(wavBlob, { auto: followUpWindowActive });`

- [ ] **Step 4: Chạy lại, phải xanh**

```powershell
cd frontend; npm run test -- turn
```

Expected: PASS

- [ ] **Step 5: Toàn bộ FE + lint**

```powershell
cd frontend; npm run test
cd frontend; npm run lint
```

Expected: PASS. *`npm run test` là bắt buộc ở task này vì nó động vào `lib/services/`.*

- [ ] **Step 6: Kiểm bằng mắt trong trình duyệt**

**Trước khi tin bất cứ thứ gì ở `localhost:3000`, xoá service worker lạ** — một SW của dự
án khác từng chạy ở cổng 3000 sẽ nuốt mọi điều hướng và trang render nhưng React không
hydrate. Dán vào console của trang:

```js
(await navigator.serviceWorker.getRegistrations()).forEach(r => r.unregister());
(await caches.keys()).forEach(k => caches.delete(k));
```

Và **đưa tab ra tiền cảnh** — tab ẩn bị bóp timer, không đo được gì thật.

Chạy real mode (cả ba cờ `NEXT_PUBLIC_USE_MOCK_*` = `false`), rồi:
1. "Hey VIVI" → "Bật điều hòa" → thấy vòng đếm ngược quanh nút mic;
2. nói tiếp "Mở cốp xe" **không** gọi tên → chạy;
3. nói một câu vô nghĩa → vòng đếm ngược tắt, **xe không nói gì**;
4. lặp 5 lượt liên tiếp → lượt thứ 6 đòi gọi tên lại;
5. **phanh 4 (spec §3.4):** trong lúc vòng đếm ngược đang chạy, **chạm nút mic** → cửa sổ
   đóng ngay và về trạng thái nghe tên gọi. Đây là đường thoát cuối cùng của tài xế khi
   ba phanh kia đều không kích hoạt, nên nó phải chạy được cả khi mọi thứ khác hỏng.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/services/turn frontend/src/components/ivi/DriverShellProvider.tsx
git commit -m "feat(fe): noi day mo_mic_ngan va X-Capture-Mode vao cua so nghe tiep"
```

---

## Task 8: Đo lại phân bố thật, và ghi ADR

**Files:**
- Create: `scripts/do_phan_bo_luot.py`
- Create: `docs/adr/ADR-028-cua-so-nghe-tiep.md`
- Modify: `docs/superpowers/specs/2026-08-23-lo-trinh-agent-theo-kich-ban.md`
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: `TraceStore` (`src/services/trace_collector.py`).

**Đây là task quyết định ba mục đa lượt còn lại có đáng làm không (spec §7).** Bộ đo hiện có toàn **lượt đầu** và toàn câu trọn vẹn viết ra giấy; mic mở thường trực đổi cách người ta nói. Con số thật chỉ lấy được sau khi mở.

- [ ] **Step 1: Viết script**

Tạo `scripts/do_phan_bo_luot.py`:

```python
"""Phân bố kết cục lượt trên lưu lượng THẬT, đọc từ TraceStore. Spec §7.

Vì sao không dùng lại `agent/v3` hay `bao-loi-2408`: cả hai chỉ chứa **lượt đầu**, và
toàn câu trọn vẹn viết ra giấy. Mic mở thường trực **đổi cách người ta nói** — ngắn hơn,
tỉnh lược hơn — nên con số 1–2% đo được 29/08 có thể đang đánh giá thấp.

Hai con số cần, và chúng quyết định việc tiếp theo:

- tỉ lệ lượt kết thúc ở `clarify`/`offer` — cầu cho cơ chế đa lượt;
- tỉ lệ lượt **bắt tự động** rơi vào `default_to_manual` — chi phí của việc mở cửa sổ.

    ≈1–2%  -> DỪNG, ba mục còn lại (#355 mục 2b/3, #339) không đáng làm.
    ≳10%   -> làm tiếp có cơ sở.

Chạy: `.\\.venv\\Scripts\\python.exe scripts\\do_phan_bo_luot.py`
"""

from __future__ import annotations

import collections
from datetime import UTC, datetime, timedelta

from src.services.trace_store import get_trace_store


def main(gio_lui: int = 24) -> None:
    het = datetime.now(UTC)
    traces = get_trace_store().records_between(het - timedelta(hours=gio_lui), het)
    if not traces:
        print("Chưa có lượt nào trong TraceStore. Chạy vài lượt rồi đo lại.")
        return

    kec_cuc = collections.Counter(t.outcome for t in traces)
    tu_dong = [t for t in traces if getattr(t, "bat_tu_dong", False)]
    tong = len(traces)

    print(f"n = {tong} lượt\n")
    for k, v in kec_cuc.most_common():
        print(f"    {str(k):22} {v:4}  {v / tong * 100:5.1f}%")

    cho = kec_cuc["clarify"] + kec_cuc["offer"]
    print(f"\n    xe hỏi và chờ trả lời : {cho}/{tong} = {cho / tong * 100:.1f}%")
    print(f"    lượt bắt tự động      : {len(tu_dong)}/{tong} = {len(tu_dong) / tong * 100:.1f}%")
    if tu_dong:
        hut = sum(1 for t in tu_dong if t.outcome in ("grounded_refusal", "not_control"))
        print(f"    trong đó xe không hiểu: {hut}/{len(tu_dong)} = {hut / len(tu_dong) * 100:.1f}%")

    print("\n    ≈1–2% -> dừng phần đa lượt còn lại;  ≳10% -> làm tiếp có cơ sở (spec §7)")


if __name__ == "__main__":
    main()
```

`TraceStore` **không có** `list_recent` — API thật là `records_between(start, end)`
(`src/services/trace_store.py:270`), `get_trace_store()` ở dòng 290. Bộ nhớ vòng mặc định
`maxsize=200`, nên cửa sổ 24 giờ vẫn có thể bị cắt bớt; đó là giới hạn phải nói ra khi
trích số, không phải lỗi.

- [ ] **Step 2: Đưa `bat_tu_dong` vào bản ghi trace**

`TraceRecord` chưa có trường này, nên script trên đọc `getattr(..., False)` và luôn ra 0.
Thêm vào `TraceRecord` (`src/services/trace_store.py`):

```python
    #: Lượt này do mic tự mở bắt được (`X-Capture-Mode: auto`). Cần ở trace để lọc được
    #: lượt rác khi đọc `/traces`: mở cửa sổ nghe tiếp làm tăng số lượt, và không phân
    #: biệt được thì bảng trace mất tác dụng chẩn đoán. Spec §6.
    bat_tu_dong: bool = False
```

và trong `record_graph_result` (`src/services/trace_collector.py:322`), thêm vào các
`changes` truyền cho `store.seal(...)`:

```python
        bat_tu_dong=bool(result.get("bat_tu_dong")),
```

- [ ] **Step 3: Chạy thử**

```powershell
.\.venv\Scripts\python.exe -m src.serve
# ở cửa sổ khác: nói vài lượt qua IVI, rồi
.\.venv\Scripts\python.exe scripts\do_phan_bo_luot.py
```

Expected: in ra bảng phân bố, không nổ khi TraceStore rỗng.

- [ ] **Step 4: Lint**

```powershell
ruff check src/ tests/ scripts/
```

*`scripts/` nằm trong lệnh CI — bỏ nó ra là để lọt một lỗi lint làm đỏ build (đã mất một
vòng CI ở PR #268 vì đúng chuyện này).*

- [ ] **Step 5: Viết ADR-028**

Tạo `docs/adr/ADR-028-cua-so-nghe-tiep.md` với các mục: Status/Date/Owner/Liên quan,
Context (số đo §1 của spec **kèm** phần tự phê rằng nó có thể đánh giá thấp), Decision
(bốn phanh + luật im lặng), Rủi ro nhận (S1 chạy im lặng từ tiếng nói không nhắm vào xe;
tải STT; trace lẫn lượt rác), Phương án đã bác (mở vô điều kiện — đo được là xe chen vào
cuộc nói chuyện; chỉ siết khi FE khai auto — client tự khai một cổng an toàn), và Thu hồi
(đặt `keepListening` thành `false` cứng ở `responseBoundary` là về hành vi cũ).

Nối ADR-025 vào mục "Liên quan" và ghi rằng spec này **không** đụng chốt thứ năm của nó.

- [ ] **Step 6: Cập nhật lộ trình và WORKLOG**

Thêm mục `§12` vào `docs/superpowers/specs/2026-08-23-lo-trinh-agent-theo-kich-ban.md`:
số đo trước/sau, bốn phanh, và **điều kiện §7** làm cổng cho ba mục đa lượt còn lại.

Thêm một khối vào `WORKLOG.md` theo đúng định dạng bảng đang dùng, kèm mã run và bài học.

- [ ] **Step 7: Commit**

```bash
git add scripts/do_phan_bo_luot.py src/services/trace_store.py src/services/trace_collector.py docs/adr/ADR-028-cua-so-nghe-tiep.md docs/superpowers/specs/2026-08-23-lo-trinh-agent-theo-kich-ban.md WORKLOG.md
git commit -m "docs(adr): ADR-028 cua so nghe tiep, va script do phan bo luot that"
```

---

## Kiểm cuối trước khi mở PR

- [ ] `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q` — xanh
- [ ] `.\.venv\Scripts\python.exe -m src.agents.eval --mode multiturn` — **`DI LUI=0`**
- [ ] `ruff check src/ tests/ scripts/` — sạch
- [ ] `cd frontend; npm run test` và `npm run lint` — xanh
- [ ] `test_clarify_khong_mo_mic_bang_co_cua_nhanh_so_tay` vẫn xanh (bất biến §5.4: không mượn cờ nhánh sổ tay để mở mic)
- [ ] Kiểm tay 4 bước ở Task 7 Step 6, sau khi xoá service worker lạ
- [ ] PR body: nêu trình tự merge so với các PR đang mở; **không** chứa link `claude.ai/code/session_...`

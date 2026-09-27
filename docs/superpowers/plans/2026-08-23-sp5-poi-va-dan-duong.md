# SP-5 POI và Dẫn đường — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** *"Tìm quán cà phê gần đây"* chọn quán gần nhất và chỉ đường luôn; *"Tìm **các** quán cà phê gần đây"* đọc danh sách rồi hỏi chọn — mở khoá lượt 9 của kịch bản demo.

**Architecture:** Một matcher mới `_match_tim_poi` trong router, đặt **trước** `_match_navigation`. Nó tra category từ alias POI rồi rẽ theo **từ chỉ số nhiều** trong câu: số ít → một bước `set_navigation(start, destination_id=<gần nhất>)` (S1); số nhiều → một bước `search_nearby_poi(category=…)` (S0). Không thêm luồng dữ liệu giữa các step, không chạm `policy.py`/`execute.py`/frontend.

**Tech Stack:** Python 3.11.9, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-sp5-poi-va-dan-duong-design.md`

## Global Constraints

- Test bằng `.\.venv\Scripts\python.exe` với `$env:MQTT_ENABLED="false"`; `ruff check src/ tests/` sạch trước mỗi commit.
- **Cổng cứng `manual→control` phải vẫn = 0** trên `--mode dinh-tuyen` (114 ca). Matcher mới là chỗ dễ làm vỡ ô này nhất — nó thêm một đường cho câu hỏi thành lệnh.
- `search_nearby_poi` là **S0**, `set_navigation` là **S1** — không đổi mức nào; chỉ `policy.py` được gán mức an toàn.
- Nhánh số ít **bắt buộc** nói ra: tên quán + khoảng cách + "đã chỉ đường" + lối thoát ("muốn quán khác thì bảo tôi"). Tự ý làm mà không nói là chỗ nguy hiểm duy nhất của thiết kế này.
- Danh sách `category` là tập đóng lấy từ `poi.json` thật; không bịa loại mới.
- Đọc tối đa **3** kết quả.
- Không sửa `poi.json` (cả hai bản backend/frontend đang giống hệt nhau — đụng một bản là lệch).
- Không sửa `.ai-log/`; hook pre-push fail thì báo, không `--no-verify`.

---

### Task 1: Hợp đồng và helper tra fixture

**Files:**
- Modify: `src/fixtures/__init__.py` (thêm 2 helper cạnh `poi_alias_map`)
- Modify: `src/services/tool_registry.py` (thêm `SearchNearbyPoiArgs`, gắn vào `ToolSpec`)
- Modify: `src/agents/contracts.py` (thêm intent `poi_search`)
- Test: `tests/test_agents/test_poi_fixture.py` (mới)

**Interfaces:**
- Consumes: `load_poi_fixture()`, `poi_alias_map()` (đã có).
- Produces:
  - `LOAI_POI: tuple[str, ...]` — tập đóng, suy từ `poi.json`.
  - `tim_poi_theo_loai(category: str) -> list[dict]` — sắp theo `distance_km` tăng dần.
  - `loai_poi_tu_alias(text: str) -> str | None` — alias trong câu → category.
  - `SearchNearbyPoiArgs(category: Literal[...])`; `TOOL_REGISTRY["search_nearby_poi"].args_model` không còn `None`.
  - `Intent` nhận thêm `"poi_search"`.

- [ ] **Step 1: Viết test fail**

```python
"""Helper tra POI theo loại — nền của matcher SP-5.

Fixture có 6 POI / 5 loại, trong đó `cafe` có ĐÚNG HAI mục (Bình Minh 3,6 km và
Highlands 5,6 km). Cặp ấy là thứ duy nhất trong fixture phân biệt được "gần nhất"
với "một trong số đó", nên mọi test dưới đây bám vào nó.
"""

import pytest

from src.fixtures import LOAI_POI, loai_poi_tu_alias, tim_poi_theo_loai
from src.services.tool_registry import TOOL_REGISTRY, SearchNearbyPoiArgs


def test_loai_poi_la_tap_dong_lay_tu_fixture_that():
    from src.fixtures import load_poi_fixture

    assert set(LOAI_POI) == {str(p["category"]) for p in load_poi_fixture()}


def test_tim_theo_loai_sap_theo_khoang_cach_tang_dan():
    quan = tim_poi_theo_loai("cafe")
    assert [p["id"] for p in quan] == ["poi-cafe-02", "poi-cafe-01"]
    assert quan[0]["distance_km"] < quan[1]["distance_km"]


def test_tim_loai_khong_co_thi_rong():
    assert tim_poi_theo_loai("san-bay") == []


@pytest.mark.parametrize(
    ("text", "mong_doi"),
    [
        ("tìm quán cà phê gần đây", "cafe"),
        ("quanh đây có trạm sạc nào không", "charging"),
        ("tìm chỗ ăn gần nhất", "restaurant"),
        ("tìm chỗ mua sắm quanh đây", "mall"),
        ("tìm công viên gần đây", "entertainment"),
        ("bật điều hòa 24 độ", None),
    ],
)
def test_alias_trong_cau_ra_dung_loai(text, mong_doi):
    assert loai_poi_tu_alias(text) == mong_doi


def test_alias_dai_thang_alias_ngan():
    """Trật tự alias-dài-trước là hợp đồng của `poi_alias_map`, không phải chi tiết."""
    assert loai_poi_tu_alias("tìm cà phê bình minh") == "cafe"


def test_search_nearby_poi_co_schema_dong():
    assert TOOL_REGISTRY["search_nearby_poi"].args_model is SearchNearbyPoiArgs
    assert TOOL_REGISTRY["search_nearby_poi"].safety == "S0"
    SearchNearbyPoiArgs(category="cafe")
    with pytest.raises(Exception):
        SearchNearbyPoiArgs(category="san-bay")
    with pytest.raises(Exception):
        SearchNearbyPoiArgs(category="cafe", ban_kinh_km=5)  # extra=forbid
```

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_poi_fixture.py -q
```

Expected: FAIL — `ImportError: cannot import name 'LOAI_POI'`.

- [ ] **Step 3: Cài `src/fixtures/__init__.py`** (thêm cuối file, cạnh `poi_alias_map`)

```python
#: Các loại địa điểm CÓ THẬT trong `poi.json`. Suy từ fixture chứ không viết tay:
#: viết tay thì hai danh sách lệch nhau vào đúng ngày ai đó thêm một POI.
LOAI_POI: tuple[str, ...] = tuple(sorted({str(item["category"]) for item in load_poi_fixture()}))


def tim_poi_theo_loai(category: str) -> list[dict]:
    """POI cùng loại, **gần nhất đứng đầu**.

    Sắp ngay ở đây chứ không để người gọi tự sắp: "gần nhất" là khái niệm của dữ
    liệu này, và mỗi chỗ gọi tự sắp lấy là mỗi chỗ có thể sắp sai chiều.
    """
    cung_loai = [item for item in load_poi_fixture() if str(item.get("category")) == category]
    return sorted(cung_loai, key=lambda item: float(item.get("distance_km", 1e9)))


def loai_poi_tu_alias(text: str) -> str | None:
    """Alias xuất hiện trong câu → loại địa điểm. `None` = câu không nói tới POI nào.

    Dùng lại `poi_alias_map()` để thừa hưởng trật tự alias-dài-trước — thứ tự ấy là
    hợp đồng: `"cà phê"` đứng trước `"cà phê bình minh"` thì câu nhắc quán Bình Minh
    sẽ trúng quán khác.
    """
    theo_id = {str(item["id"]): str(item.get("category", "")) for item in load_poi_fixture()}
    thap = (text or "").lower()
    for alias, poi_id in poi_alias_map().items():
        if alias in thap:
            return theo_id.get(poi_id) or None
    return None
```

- [ ] **Step 4: Cài `src/services/tool_registry.py`**

Thêm cạnh các `_Args` khác:

```python
class SearchNearbyPoiArgs(_Args):
    #: Tập đóng, lấy từ `poi.json` thật. Schema đóng chặn model bịa ra loại địa điểm
    #: không tồn tại — cùng kỷ luật với mọi tool khác.
    category: Literal["cafe", "charging", "entertainment", "mall", "restaurant"]
```

Sửa dòng registry: `ToolSpec("search_nearby_poi", None, "S0", SearchNearbyPoiArgs)`.

(Kiểm `LOAI_POI` khớp với `Literal` bằng chính test ở Step 1; nếu `poi.json` có loại khác thì sửa `Literal` theo fixture, không sửa fixture theo `Literal`.)

`src/agents/contracts.py` — thêm vào `Intent`, ngay dưới `"navigation_cancel"`:

```python
    #: Tìm địa điểm quanh xe. Tách khỏi `navigation_start` vì nó **chỉ đọc** (S0):
    #: nhánh số nhiều đọc danh sách rồi hỏi lại, không đặt dẫn đường.
    "poi_search",
```

- [ ] **Step 5: Chạy lại — pass, kèm ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_poi_fixture.py tests/test_agents/test_tools.py tests/test_agents/test_contracts.py -q
ruff check src/fixtures/__init__.py src/services/tool_registry.py src/agents/contracts.py tests/test_agents/test_poi_fixture.py
```

- [ ] **Step 6: Commit**

```bash
git add src/fixtures/__init__.py src/services/tool_registry.py src/agents/contracts.py tests/test_agents/test_poi_fixture.py
git commit -m "feat(poi): schema dong cho search_nearby_poi + helper tra fixture theo loai (SP-5)"
```

---

### Task 2: Matcher `_match_tim_poi` — hai nhánh theo số ít/số nhiều

**Files:**
- Modify: `src/agents/router.py` (hằng số + matcher + đăng ký vào `_run_matchers`)
- Test: `tests/test_agents/test_tim_poi.py` (mới)

**Interfaces:**
- Consumes: `loai_poi_tu_alias`, `tim_poi_theo_loai`, `LOAI_POI` (Task 1); `self._control` (đã có).
- Produces: `DeterministicControlRouter._match_tim_poi(text) -> MatchResult | None`, đăng ký **trước** `self._match_navigation` trong `_run_matchers`.

- [ ] **Step 1: Viết test fail**

```python
"""SP-5: tìm địa điểm. Số ít thì đi, số nhiều thì hỏi (spec §2.1)."""

import pytest

from src.agents.router import DeterministicControlRouter

router = DeterministicControlRouter()


def _buoc(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


@pytest.mark.parametrize(
    "text",
    ["Tìm quán cà phê gần đây", "Kiếm quán cà phê gần nhất", "Quanh đây có quán cà phê nào không"],
)
def test_so_it_thi_chi_duong_toi_quan_gan_nhat(text):
    """Bình Minh 3,6 km gần hơn Highlands 5,6 km."""
    d, buoc = _buoc(text)
    assert d.disposition == "control"
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})]


@pytest.mark.parametrize(
    "text",
    ["Tìm các quán cà phê gần đây", "Tìm những quán cà phê quanh đây", "Quanh đây có mấy quán cà phê"],
)
def test_so_nhieu_thi_chi_TIM_khong_dat_dan_duong(text):
    d, buoc = _buoc(text)
    assert d.disposition == "control"
    assert d.intent == "poi_search"
    assert buoc == [("search_nearby_poi", {"category": "cafe"})]


def test_cau_ghep_tim_roi_dan_duong_toi_do():
    """Đại từ hồi chỉ xử trong CÙNG matcher — không đụng cơ chế ghép vế của #225."""
    d, buoc = _buoc("Tìm quán cà phê gần đây rồi dẫn đường tới đó")
    assert d.disposition == "control"
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})]


def test_dan_duong_toi_do_dung_mot_minh_van_hoi_lai():
    """Không có gì để "đó" trỏ tới — giữ nguyên hành vi hôm nay."""
    assert router.route("Dẫn đường tới đó").disposition != "control"


@pytest.mark.parametrize(
    ("text", "poi_id"),
    [
        ("Tìm trạm sạc gần đây", "poi-charge-01"),
        ("Tìm chỗ ăn gần đây", "poi-food-01"),
        ("Tìm chỗ mua sắm gần đây", "poi-mall-01"),
    ],
)
def test_cac_loai_khac(text, poi_id):
    _, buoc = _buoc(text)
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": poi_id})]


@pytest.mark.parametrize(
    "text",
    [
        "Tìm hiểu về áp suất lốp",
        "Tìm hiểu cách khởi tạo cửa sổ điện",
        "Cách tìm trạm sạc trên màn hình",
    ],
)
def test_khong_bat_nham_cau_hoi_so_tay(text):
    """Ô cổng cứng `manual→control` phải giữ bằng 0 — đây là chỗ dễ làm vỡ nhất."""
    assert router.route(text).disposition != "control"


def test_dan_duong_toi_ten_quan_van_di_duong_cu():
    """`_match_navigation` cũ không bị matcher mới nuốt mất."""
    _, buoc = _buoc("Dẫn đường tới cà phê bình minh")
    assert buoc == [("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})]
```

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_tim_poi.py -q
```

Expected: FAIL — phần lớn ra `not_control`.

- [ ] **Step 3: Cài hằng số** (`src/agents/router.py`, cạnh `_NAV_VERB_TUONG_MINH`)

```python
#: Động từ mở đầu một câu TÌM địa điểm.
_TIM_VERB: tuple[str, ...] = ("tìm", "kiếm", "tìm giúp", "tìm hộ")

#: Cụm "quanh xe" — bắt buộc phải có, nếu không thì `"tìm cà phê"` cũng thành lệnh.
_QUANH_DAY: tuple[str, ...] = ("gần đây", "gần nhất", "quanh đây", "gần đó", "ở đây")

#: Từ chỉ SỐ NHIỀU — dấu hiệu tài xế muốn xem lựa chọn chứ không muốn đi luôn.
#: Tập đóng (spec §2.1); đây là toàn bộ cách phân biệt "đi luôn" với "cho tôi chọn".
_SO_NHIEU: tuple[str, ...] = ("các ", "những ", "mấy ", "bao nhiêu ")

#: Đại từ hồi chỉ ở vế dẫn đường: `"… rồi dẫn đường tới ĐÓ"`.
_HOI_CHI: tuple[str, ...] = ("tới đó", "đến đó", "tới đấy", "đến đấy", "chỗ đó", "chỗ đấy")

#: `"tìm hiểu"` là HỎI, không phải TÌM. Loại trừ **trước** khi nhận, cùng khuôn với
#: `_KINH_KHONG_PHAI_CUA_SO`: `"tìm hiểu về áp suất lốp"` phải đi tra sổ tay, và đó
#: chính là ô cổng cứng `manual→control` mà cả hệ thống đang giữ bằng 0.
_TIM_KHONG_PHAI_TIM_POI: tuple[str, ...] = ("tìm hiểu", "cách tìm", "làm sao tìm", "tìm thấy")
```

- [ ] **Step 4: Cài matcher** (đặt ngay trước `_match_navigation`)

```python
    def _match_tim_poi(self, text: str) -> MatchResult | None:
        """Tìm địa điểm quanh xe. Số ít thì chỉ đường luôn, số nhiều thì đọc danh sách.

        Đặt **trước** `_match_navigation` trong `_run_matchers`: câu ghép
        `"tìm quán cà phê gần đây rồi dẫn đường tới đó"` chứa cả `"dẫn đường"`, và
        `_match_navigation` chạy trước sẽ ăn mất nó rồi hỏi lại `"tới đâu"` — vì đại
        từ `"đó"` không tra được ra POI nào (đo 23/08: `unknown_local_destination`).
        """
        if any(cum in text for cum in _TIM_KHONG_PHAI_TIM_POI):
            return None
        co_tim = any(text.startswith(v) or f" {v} " in f" {text} " for v in _TIM_VERB)
        co_quanh_day = any(cum in text for cum in _QUANH_DAY)
        # `"quanh đây có X không"` không có động từ tìm nhưng vẫn là câu tìm.
        if not co_quanh_day:
            return None
        if not co_tim and "có" not in text:
            return None
        category = loai_poi_tu_alias(text)
        if category is None:
            return None
        ket_qua = tim_poi_theo_loai(category)
        if not ket_qua:
            return None
        # Số nhiều mà chỉ có đúng một kết quả thì không có gì để chọn — đi luôn.
        if any(cum in text for cum in _SO_NHIEU) and len(ket_qua) > 1:
            return self._control("poi_search", "search_nearby_poi", {"category": category})
        return self._control(
            "navigation_start",
            "set_navigation",
            {"operation": "start", "destination_id": str(ket_qua[0]["id"])},
        )
```

Import ở đầu file: `from src.fixtures import load_poi_fixture, loai_poi_tu_alias, poi_alias_map, tim_poi_theo_loai`.

Trong `_run_matchers`, thêm `self._match_tim_poi,` **ngay trước** `self._match_navigation,`.

- [ ] **Step 5: Chạy lại — pass, kèm toàn bộ router và ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_tim_poi.py tests/test_agents/test_router.py tests/test_agents/test_tu_vung_xe.py -q
ruff check src/agents/router.py tests/test_agents/test_tim_poi.py
```

Nếu một test router cũ đỏ vì câu của nó giờ khớp matcher mới: đọc docstring test đó trước. Nếu nó khoá hành vi ADR-011 (*"câu lạ thì tra sổ tay"*) thì **matcher mới sai** — siết `_TIM_KHONG_PHAI_TIM_POI` hoặc `_QUANH_DAY`, đừng sửa test.

- [ ] **Step 6: Commit**

```bash
git add src/agents/router.py tests/test_agents/test_tim_poi.py
git commit -m "feat(router): matcher tim POI - so it chi duong luon, so nhieu doc danh sach (SP-5)"
```

---

### Task 3: Câu trả lời — nói rõ đã làm gì và cho lối thoát

**Files:**
- Modify: `src/agents/nodes/compose.py` (`describe_step` + câu cho `poi_search`)
- Test: `tests/test_agents/test_cau_tra_loi_poi.py` (mới)

**Interfaces:**
- Consumes: `tim_poi_theo_loai`, `load_poi_fixture` (Task 1).
- Produces: `describe_step("set_navigation", …)` in **tên POI** thay vì id; hàm `cau_ket_qua_tim_poi(category: str) -> str`.

- [ ] **Step 1: Viết test fail**

```python
"""Nhánh số ít làm nhiều hơn điều được yêu cầu (đặt dẫn đường cho một câu "tìm"),
nên nó BẮT BUỘC nói ra mình đã làm gì và cho lối thoát ngay trong cùng một lượt.
Đó là điều kiện kèm theo của quyết định ở spec §2.1, không phải trang trí."""

from src.agents.nodes.compose import cau_ket_qua_tim_poi, describe_step


def test_describe_step_in_ten_quan_khong_in_id():
    """`"dẫn đường tới poi-cafe-02"` là chuỗi không ai đọc lên được."""
    cau = describe_step("set_navigation", {"operation": "start", "destination_id": "poi-cafe-02"})
    assert "Cà phê Bình Minh" in cau
    assert "poi-cafe-02" not in cau


def test_describe_step_id_la_thi_khong_no():
    assert describe_step("set_navigation", {"operation": "start", "destination_id": "poi-la"})


def test_cau_so_nhieu_doc_ten_kem_khoang_cach_va_hoi_lai():
    cau = cau_ket_qua_tim_poi("cafe")
    assert "Cà phê Bình Minh" in cau and "Highlands" in cau
    assert "3,6" in cau or "3.6" in cau
    assert cau.rstrip().endswith("?")


def test_cau_so_nhieu_doc_toi_da_ba_ket_qua():
    cau = cau_ket_qua_tim_poi("cafe")
    assert cau.count(" km") <= 3


def test_loai_khong_co_ket_qua_thi_noi_that():
    cau = cau_ket_qua_tim_poi("san-bay")
    assert "không tìm" in cau.lower() or "chưa tìm" in cau.lower()
```

- [ ] **Step 2: Chạy để thấy fail** — `ImportError: cannot import name 'cau_ket_qua_tim_poi'`.

- [ ] **Step 3: Cài `compose.py`**

Sửa nhánh `set_navigation` của `describe_step`:

```python
    if tool == "set_navigation":
        if args.get("operation") == "cancel":
            return "hủy dẫn đường"
        return f"dẫn đường tới {_ten_poi(args.get('destination_id'))}"
```

Thêm hai hàm:

```python
def _ten_poi(poi_id: str | None) -> str:
    """Id → tên đọc được. Id lạ thì trả lại chính nó: thà đọc một chuỗi kỳ quặc còn
    hơn ném lỗi giữa lúc đang soạn câu trả lời."""
    from src.fixtures import load_poi_fixture

    for item in load_poi_fixture():
        if str(item["id"]) == str(poi_id):
            return str(item["name"])
    return str(poi_id)


def cau_ket_qua_tim_poi(category: str) -> str:
    """Câu cho nhánh SỐ NHIỀU: đọc tối đa ba chỗ rồi hỏi lại.

    Ba là trần của tai chứ không phải của màn hình: nghe quá ba cái tên kèm khoảng
    cách thì không ai nhớ nổi cái đầu tiên.
    """
    from src.fixtures import tim_poi_theo_loai

    ket_qua = tim_poi_theo_loai(category)[:3]
    if not ket_qua:
        return "Tôi không tìm được chỗ nào quanh đây. Bạn thử hỏi loại địa điểm khác nhé."
    ds = ", ".join(f"{p['name']} cách {str(p['distance_km']).replace('.', ',')} km" for p in ket_qua)
    return f"Tôi tìm được {len(ket_qua)} chỗ: {ds}. Bạn muốn đi chỗ nào?"
```

Trong `compose_node`, trước nhánh `outcome` chung, thêm:

```python
    if state.get("intent") == "poi_search":
        plan = state.get("action_plan") or state.get("candidate_action_plan")
        loai = plan.steps[0].args.get("category") if plan and plan.steps else ""
        return {"outcome": "completed", "response_text": cau_ket_qua_tim_poi(str(loai))}
```

(Kiểm hình dạng trả về của `compose_node` ở các nhánh sẵn có — `_tra_ap_suat_lop` là mẫu gần nhất — và trả đúng những khoá ấy.)

Câu cho nhánh số ít: `OUTCOME_MESSAGES["completed"]` hiện là *"Đã thực hiện lệnh trên xe mô phỏng."* — với `navigation_start` phải đổi thành mẫu của spec §3.3. Thêm nhánh:

```python
    if state.get("intent") == "navigation_start" and outcome == "completed":
        plan = state.get("action_plan")
        pid = plan.steps[0].args.get("destination_id") if plan and plan.steps else None
        from src.fixtures import load_poi_fixture

        poi = next((p for p in load_poi_fixture() if str(p["id"]) == str(pid)), None)
        if poi is not None:
            d = str(poi["distance_km"]).replace(".", ",")
            speak_text = (
                f"Chỗ gần nhất là {poi['name']}, cách {d} km, khoảng {poi['eta_min']} phút. "
                "Tôi đã chỉ đường tới đó. Muốn chỗ khác thì bảo tôi nhé."
            )
```

- [ ] **Step 4: Chạy lại — pass, kèm compose và ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_cau_tra_loi_poi.py tests/test_agents/test_tim_poi.py tests/test_agents/ -q
ruff check src/agents/nodes/compose.py tests/test_agents/test_cau_tra_loi_poi.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/nodes/compose.py tests/test_agents/test_cau_tra_loi_poi.py
git commit -m "feat(compose): cau tra loi POI - in ten thay id, so it noi ro da chi duong + loi thoat (SP-5)"
```

---

### Task 4: Chạy trọn lượt 9, giữ cổng cứng, và ghi bằng chứng

**Files:**
- Test: `tests/test_agents/test_poi_e2e.py` (mới)
- Modify: `eval/datasets/agent/v3/cases.jsonl` (thêm ca POI)
- Modify: `docs/coverage_matrix.md`, `WORKLOG.md`
- Run dirs: `eval/results/agent-intent/`, `agent-routing/`, `chitchat/`

- [ ] **Step 1: Test e2e qua graph thật**

```python
"""Lượt 9 của kịch bản, đi trọn từ câu nói tới kế hoạch đã thực thi."""

from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway


async def _hoi(text: str):
    graph = build_graph(InProcessVehicleGateway.new())
    return await graph.ainvoke({"query": text, "session_id": "s", "vehicle_id": "v", "turn_id": "t"})


async def test_luot_9_cua_kich_ban_chay_tron():
    r = await _hoi("Tìm quán cà phê gần đây rồi dẫn đường tới đó")
    assert r["outcome"] == "completed"
    noi = r.get("speak_text") or r["response_text"]
    assert "Cà phê Bình Minh" in noi and "3,6 km" in noi
    assert "đã chỉ đường" in noi.lower()
    assert "chỗ khác" in noi.lower()  # lối thoát, điều kiện của spec §2.1


async def test_so_nhieu_doc_danh_sach_va_khong_dat_dan_duong():
    r = await _hoi("Tìm các quán cà phê gần đây")
    noi = r.get("speak_text") or r["response_text"]
    assert "Bạn muốn đi chỗ nào?" in noi
    assert "đã chỉ đường" not in noi.lower()
```

- [ ] **Step 2: Chạy — pass**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_poi_e2e.py -q
```

- [ ] **Step 3: Thêm ca vào bộ đo intent** — nối vào `eval/datasets/agent/v3/cases.jsonl`, mỗi dòng một JSON theo đúng shape đang có ở đó (xem `head -1`): 6 ca số ít (mỗi loại một), 2 ca số nhiều, 1 ca ghép, và **3 ca âm tính** (`"tìm hiểu về áp suất lốp"`, `"cách tìm trạm sạc trên màn hình"`, `"tìm hiểu cách khởi tạo cửa sổ điện"` — đều phải `not_control`).

- [ ] **Step 4: Chạy ba bộ đo, kiểm cổng cứng**

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode intent
.\.venv\Scripts\python.exe -m src.agents.eval --mode dinh-tuyen    # cần llama-server
.\.venv\Scripts\python.exe -m src.agents.eval --mode chitchat      # cần llama-server
```

**`manual→control` phải vẫn = 0 ở cả hai bộ sau.** Nếu vỡ: mở `case_results.jsonl` xem câu nào, rồi **siết matcher** (thêm vào `_TIM_KHONG_PHAI_TIM_POI` hoặc đòi thêm điều kiện) — **không** đổi nhãn dataset.

- [ ] **Step 5: Toàn suite + ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
ruff check src/ tests/
```

- [ ] **Step 6: Docs** — `docs/coverage_matrix.md`: `search_nearby_poi` từ "chỉ có trong registry" thành có matcher + test, cập nhật số miền điều khiển được. `WORKLOG.md`: bảng + bài học + run id.

- [ ] **Step 7: Commit + PR**

```bash
git add tests/test_agents/test_poi_e2e.py eval/ docs/coverage_matrix.md WORKLOG.md
git commit -m "feat(sp5): luot 9 cua kich ban chay tron - bo do POI, cong cung giu 0"
```

PR body: bảng trước/sau ba câu đo 23/08 (`default_to_manual` → `control`), số cổng cứng của cả ba bộ đo, và ghi rõ *"Đưa tôi về nhà"* nằm ngoài phạm vi kèm lý do.

---

## Ghi chú cho người thực thi

- **Thứ tự matcher là hợp đồng**, không phải sở thích: `_match_tim_poi` phải đứng **trước** `_match_navigation`, nếu không câu ghép bị nuốt.
- **Đừng sửa `poi.json`.** Hai bản backend/frontend đang giống hệt nhau; đụng một bản là lệch, và không có test nào bắt được.
- Ca âm tính (`"tìm hiểu về…"`) quan trọng ngang ca dương tính: matcher này là đường mới duy nhất biến một câu hỏi thành một lệnh, tức đúng ô cổng cứng cả hệ thống đang giữ bằng 0.
- Chữ ký thật khác plan thì theo code thật và ghi trong commit message.

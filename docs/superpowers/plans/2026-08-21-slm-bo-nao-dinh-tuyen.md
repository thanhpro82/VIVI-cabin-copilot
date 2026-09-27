# SLM Bộ Não Định Tuyến (SP-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Câu không khớp luật nào được SLM phân loại 3 lớp (control/manual/chitchat) rồi rẽ đúng nhánh, thay vì bị đẩy hết vào tra sổ tay.

**Architecture:** Thêm node `slm_classify` vào LangGraph giữa nhánh trượt `default_to_manual` của router và các nhánh xử lý. Classifier là một vai mới của cùng llama-server Qwen thường trú (cùng endpoint với planner), ép đầu ra bằng `json_schema`, fail-safe ba tầng đều rơi về `manual` (= hành vi ADR-011 hôm nay). Không thay router, không thay cổng an toàn.

**Tech Stack:** Python 3.11.9, LangGraph, httpx, llama-server (`json_schema` grammar), pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-slm-bo-nao-dinh-tuyen-design.md`

## Global Constraints

- Chạy test bằng `.\.venv\Scripts\python.exe` với `$env:MQTT_ENABLED="false"` (không thì mỗi `TestClient(app)` chờ broker 10 s).
- Không thêm cờ mới: `slm_enabled` gác luôn classifier. Default `false` (invariant "no LLM on the path").
- `SLM_ENABLED=false` ⇒ graph giao **y hệt** develop — có test khoá.
- Không thêm endpoint mới: classifier dùng `settings.slm_endpoint` (8093).
- Chỉ `src/agents/policy.py` gán `safety_level` — classifier không tạo plan, không chạm invariant này.
- Mọi con số đo phải trỏ về run id bất biến dưới `eval/results/agent-routing/`.
- `ruff check src/ tests/` sạch trước mỗi commit (line-length 120, N802: tên test không viết hoa).
- Không sửa file trong `.ai-log/`; hook pre-push fail thì báo, không `--no-verify`.

---

### Task 1: Disposition `chitchat` trong contracts

**Files:**
- Modify: `src/agents/contracts.py:22` (Literal `Disposition`)
- Test: `tests/test_agents/test_contracts.py`

**Interfaces:**
- Consumes: `RouteDecision`, `_PLAN_BEARING_DISPOSITIONS` (đã có, không đổi).
- Produces: `Disposition` chấp nhận thêm giá trị `"chitchat"`; `RouteDecision(disposition="chitchat", candidate_plan=...)` phải raise (exclusive như `not_control`).

- [ ] **Step 1: Viết test fail**

Thêm vào cuối `tests/test_agents/test_contracts.py`:

```python
def test_disposition_chitchat_hop_le_va_cam_mang_plan():
    """SP-1: chitchat là disposition mới, exclusive như not_control."""
    quyet_dinh = RouteDecision(disposition="chitchat", intent="unknown", reason="slm_classified_chitchat")
    assert quyet_dinh.candidate_plan is None
    with pytest.raises(ValidationError):
        RouteDecision(
            disposition="chitchat",
            intent="unknown",
            reason="slm_classified_chitchat",
            candidate_plan=CandidateActionPlan(
                schema_version="1.0",
                steps=[CandidateStep(step_id="step-1", ordinal=0, tool="set_hvac_power", args={"power": "on"})],
            ),
        )
```

(Đầu file test đã import `RouteDecision`, `CandidateActionPlan`, `CandidateStep`, `pytest`, `ValidationError` — kiểm tra, thiếu thì thêm. `intent="unknown"` phải nằm trong Literal `Intent`; nếu chưa có giá trị `unknown`, xem giá trị nào Literal đang có bằng `grep -n 'Intent = ' -A 10 src/agents/contracts.py` và dùng một giá trị không-control có sẵn, ví dụ `manual_query`.)

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_contracts.py -q
```

Expected: FAIL — `Input should be 'control', 'offer', ...` (Literal chưa có `chitchat`).

- [ ] **Step 3: Sửa contracts**

`src/agents/contracts.py:22`:

```python
Disposition = Literal["control", "offer", "not_control", "clarify", "denied", "chitchat"]
```

Không sửa gì khác: `chitchat` không nằm trong `_PLAN_BEARING_DISPOSITIONS` nên validator có sẵn tự cấm `candidate_plan`.

- [ ] **Step 4: Chạy lại — pass, và chạy cả file để chắc không vỡ gì**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_contracts.py tests/test_agents/test_router.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/contracts.py tests/test_agents/test_contracts.py
git commit -m "feat(agent): disposition chitchat trong RouteDecision - exclusive nhu not_control (SP-1)"
```

---

### Task 2: Vai classify — prompt, schema, `QwenClassifier`

**Files:**
- Modify: `src/agents/slm.py` (thêm cuối file, cạnh `QwenPlanner`/`QwenLeadIn`)
- Test: `tests/test_agents/test_slm_classifier.py` (mới)

**Interfaces:**
- Consumes: `chatml(system, user)` và `SlmSchemaError` đã có trong `src/agents/slm.py`.
- Produces:
  - `CLASSIFY_INTENTS: tuple[str, ...] = ("control", "manual", "chitchat")`
  - `class Classifier(Protocol): def classify(self, normalized_text: str) -> str: ...`
  - `class QwenClassifier: __init__(self, endpoint: str, model_id: str, timeout_s: float = 2.0)` — `classify()` trả đúng một trong `CLASSIFY_INTENTS`, raise `SlmSchemaError` khi payload hỏng, để httpx error lan ra (node bắt).
  - `parse_classify_output(raw: str) -> str`

- [ ] **Step 1: Viết test fail**

Tạo `tests/test_agents/test_slm_classifier.py`:

```python
"""Vai classify của SP-1: chỉ phân loại, không sinh chữ, không tạo plan.

Grammar (`json_schema` enum) ép ở tầng sinh nên model không trả nổi chuỗi hỏng;
các test parse ở đây gác đường HTTP 500 / payload rỗng mà grammar không cứu được.
"""

import json

import pytest

from src.agents.slm import CLASSIFY_INTENTS, CLASSIFY_SCHEMA, QwenClassifier, SlmSchemaError, parse_classify_output


def test_parse_du_ba_lop():
    for intent in CLASSIFY_INTENTS:
        assert parse_classify_output(json.dumps({"intent": intent})) == intent


def test_parse_intent_la_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_classify_output('{"intent": "navigate"}')


def test_parse_khong_phai_json_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_classify_output("control")


def test_parse_rong_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_classify_output("")


def test_schema_ep_enum_ngay_tang_sinh():
    """Enum nằm trong schema gửi cho llama-server — hết lớp lỗi parse tự do."""
    assert CLASSIFY_SCHEMA["properties"]["intent"]["enum"] == list(CLASSIFY_INTENTS)
    assert CLASSIFY_SCHEMA["required"] == ["intent"]


def test_qwen_classifier_gui_dung_cau_hinh(monkeypatch):
    """temperature 0 + grammar + cache_prompt: cấu hình là hợp đồng, không phải tuỳ hứng."""
    sent = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": '{"intent": "manual"}'}

    def _fake_post(url, json=None, timeout=None):
        sent["url"] = url
        sent["body"] = json
        sent["timeout"] = timeout
        return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "post", _fake_post)
    classifier = QwenClassifier("http://127.0.0.1:8093", "qwen3-4b", timeout_s=2.0)
    assert classifier.classify("Nóng quá, giảm nhiệt độ xuống đi") == "manual"
    assert sent["url"].endswith("/completion")
    assert sent["body"]["temperature"] == 0
    assert sent["body"]["json_schema"] == CLASSIFY_SCHEMA
    assert sent["body"]["cache_prompt"] is True
    assert sent["body"]["n_predict"] <= 32
    assert sent["timeout"] == 2.0
    assert "Nóng quá" in sent["body"]["prompt"]
```

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_classifier.py -q
```

Expected: FAIL — `ImportError: cannot import name 'CLASSIFY_INTENTS'`.

- [ ] **Step 3: Cài vào `src/agents/slm.py`** (thêm cuối file)

```python
#: Ba lớp định tuyến của SP-1. Thứ tự cố định — CLASSIFY_SCHEMA lấy enum từ đây.
CLASSIFY_INTENTS: tuple[str, ...] = ("control", "manual", "chitchat")

#: Grammar ép ở tầng sinh: model KHÔNG THỂ trả chuỗi ngoài enum. Với Qwen3 nó còn
#: chặn luôn thinking mode — token đầu tiên bắt buộc là `{`, không có chỗ cho
#: `<think>`. Vẫn giữ parse_classify_output vì grammar không cứu được HTTP 500.
CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"intent": {"type": "string", "enum": list(CLASSIFY_INTENTS)}},
    "required": ["intent"],
    "additionalProperties": False,
}

#: Prompt phân loại — tối giản (~250 token) vì prefill 350–450 tok/s là phần đắt.
#: Ví dụ few-shot là ca THẬT đã đo, không phải trang trí: dòng "Nóng quá..." là
#: chính ca #149/ADR-022 mà đường cũ đẩy nhầm vào sổ tay.
CLASSIFY_SYSTEM = (
    "Phân loại câu của tài xế vào đúng một nhóm:\n"
    "- control: yêu cầu xe LÀM gì (chỉnh, bật, tắt, mở, đặt, phát...)\n"
    "- manual: HỎI về xe, tính năng, thông số, cách dùng\n"
    "- chitchat: xã giao hoặc chuyện trò, không đòi xe làm gì\n"
    "Ví dụ:\n"
    '- "Nóng quá, giảm nhiệt độ xuống đi" → control\n'
    '- "Cho ghế ngả ra sau một chút" → control\n'
    '- "Áp suất lốp bao nhiêu là đủ?" → manual\n'
    '- "Đèn cảnh báo hình cục pin nghĩa là gì?" → manual\n'
    '- "Xin chào, hôm nay khỏe không?" → chitchat\n'
    '- "Xe này đi đường dài có êm không nhỉ?" → chitchat\n'
    'Trả về JSON: {"intent": "<nhóm>"}'
)


def parse_classify_output(raw: str) -> str:
    """Đọc kết quả phân loại. Ngoài enum là hỏng, không đoán."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SlmSchemaError(f"classify output không phải JSON: {exc}") from exc
    intent = payload.get("intent") if isinstance(payload, dict) else None
    if intent not in CLASSIFY_INTENTS:
        raise SlmSchemaError(f"intent không hợp lệ: {intent!r}")
    return str(intent)


class Classifier(Protocol):
    def classify(self, normalized_text: str) -> str: ...


class QwenClassifier:
    """Vai classify trên CÙNG llama-server thường trú với planner (spec §3.2:
    một model bốn vai, không endpoint thứ ba). httpx error cố ý lan ra —
    node `slm_classify` là nơi quyết định fail-safe, không phải client."""

    def __init__(self, endpoint: str, model_id: str, timeout_s: float = 2.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._timeout_s = timeout_s

    def classify(self, normalized_text: str) -> str:
        import httpx

        response = httpx.post(
            f"{self._endpoint}/completion",
            json={
                "prompt": chatml(CLASSIFY_SYSTEM, f'Câu: "{normalized_text}"'),
                "temperature": 0,
                "n_predict": 32,
                "cache_prompt": True,
                "json_schema": CLASSIFY_SCHEMA,
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return parse_classify_output(str(response.json().get("content", "")).strip())
```

- [ ] **Step 4: Chạy lại — pass, kèm ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_classifier.py tests/test_agents/test_slm.py -q
ruff check src/agents/slm.py tests/test_agents/test_slm_classifier.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/slm.py tests/test_agents/test_slm_classifier.py
git commit -m "feat(agent): QwenClassifier - vai phan loai 3 lop, grammar ep enum (SP-1)"
```

---

### Task 3: Node `slm_classify` + nối graph + fail-safe

**Files:**
- Modify: `src/agents/graph.py` (hàm `_route_after_routing` thành factory, thêm node, thêm `_route_after_classify`, param `classifier`)
- Test: `tests/test_agents/test_slm_classify_node.py` (mới)

**Interfaces:**
- Consumes: `Classifier` (Task 2), `AgentState` (`route_reason`, `normalized_text`, `outcome`, `chitchat_reply` — tất cả đã có trong `src/agents/state.py`).
- Produces:
  - `build_graph(..., classifier: Classifier | None = None, ...)`
  - `_route_after_classify(state) -> str` (module-level, trả `"slm" | "rag" | "compose"`)
  - `CHITCHAT_TAM_GIU: str` (module-level trong `graph.py`) — SP-2 thay bằng generator.
  - route_reason mới: `slm_classified_control`, `slm_classified_manual`, `slm_classified_chitchat`, `slm_classify_failed`.
  - Stage trace mới: `slm_classify` (qua `_timed`, chỉ khi classifier được truyền).

- [ ] **Step 1: Viết test fail**

Tạo `tests/test_agents/test_slm_classify_node.py`:

```python
"""Node slm_classify: rẽ 3 nhánh, fail-safe về manual, flag-off giao hệt develop.

Mọi test dựng graph qua build_graph với FakeGateway + FakeClassifier — không mạng,
không model. Đường thật (llama-server) nằm ở test contract (Task 6).
"""

import pytest

from src.agents.graph import CHITCHAT_TAM_GIU, _route_after_classify, build_graph
from tests.test_agents.test_graph import FakeGateway  # gateway giả sẵn có của suite


class FakeClassifier:
    def __init__(self, intent: str | None = None, exc: Exception | None = None) -> None:
        self._intent = intent
        self._exc = exc
        self.calls: list[str] = []

    def classify(self, normalized_text: str) -> str:
        self.calls.append(normalized_text)
        if self._exc is not None:
            raise self._exc
        return self._intent or "manual"


#: Câu KHÔNG khớp luật nào của DeterministicControlRouter — router trả
#: default_to_manual. Nếu router sau này học được câu này, đổi câu khác và
#: kiểm bằng: router.route(text).reason == "default_to_manual".
CAU_LA = "Nóng quá trời hôm nay ha"


def _hoi(graph, text: str) -> dict:
    import asyncio

    return asyncio.run(graph.ainvoke({"query": text, "session_id": "s1", "vehicle_id": "v1", "turn_id": "t1"}))


def test_route_after_classify_du_ba_nhanh():
    assert _route_after_classify({"route_reason": "slm_classified_control"}) == "slm"
    assert _route_after_classify({"route_reason": "slm_classified_manual"}) == "rag"
    assert _route_after_classify({"route_reason": "slm_classified_chitchat"}) == "compose"
    assert _route_after_classify({"route_reason": "slm_classify_failed"}) == "rag"


def test_chitchat_ve_compose_voi_cau_tam_giu():
    classifier = FakeClassifier(intent="chitchat")
    graph = build_graph(FakeGateway(), classifier=classifier)
    ket_qua = _hoi(graph, CAU_LA)
    assert classifier.calls, "classifier phải được gọi cho câu lạ"
    assert ket_qua["outcome"] == "chitchat"
    assert ket_qua["chitchat_reply"] == CHITCHAT_TAM_GIU
    assert ket_qua["route_reason"] == "slm_classified_chitchat"


def test_classify_hong_thi_ve_manual_khong_treo():
    """Ba tầng fail-safe: lỗi hạ tầng / timeout / payload hỏng đều về nhánh rag."""
    import httpx

    for exc in (httpx.ConnectError("chết"), httpx.ReadTimeout("chậm"), OSError("đứt")):
        graph = build_graph(FakeGateway(), classifier=FakeClassifier(exc=exc))
        ket_qua = _hoi(graph, CAU_LA)
        assert ket_qua["route_reason"] == "slm_classify_failed"
        # Nhánh rag không có index trong test → grounded_refusal, là hành vi
        # ADR-011 của develop. Điều cần khoá: KHÔNG treo, KHÔNG nổ 500.
        assert ket_qua["outcome"] in {"grounded_refusal", "not_control", "clarify"}


def test_flag_off_giao_het_develop():
    """classifier=None ⇒ không có node slm_classify, câu lạ đi rag như ADR-011."""
    graph = build_graph(FakeGateway(), classifier=None)
    assert "slm_classify" not in graph.get_graph().nodes
    ket_qua = _hoi(graph, CAU_LA)
    assert ket_qua["route_reason"] == "default_to_manual"


def test_cau_khop_luat_khong_goi_classifier():
    """Đường tắt: lệnh khớp luật không trả một mili giây nào cho SLM."""
    classifier = FakeClassifier(intent="chitchat")
    graph = build_graph(FakeGateway(), classifier=classifier)
    _hoi(graph, "bật điều hòa")
    assert classifier.calls == []
```

(Nếu `tests/test_agents/test_graph.py` không có sẵn `FakeGateway` import được, xem tên gateway giả trong file đó — `grep -n "class Fake" tests/test_agents/test_graph.py` — và dùng đúng tên; nếu là fixture, chép class tối thiểu vào file test này thay vì import chéo.)

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_classify_node.py -q
```

Expected: FAIL — `ImportError: cannot import name 'CHITCHAT_TAM_GIU'`.

- [ ] **Step 3: Cài vào `src/agents/graph.py`**

3a. Module-level, cạnh `_route_after_slm`:

```python
#: Câu giữ chỗ của nhánh chitchat trong SP-1. SP-2 thay bằng generator thật
#: (xã giao + quanh xe, từ chối mềm ngoài phạm vi — xem spec SP-1 §2).
CHITCHAT_TAM_GIU = (
    "Tôi nghe bạn đây. Phần trò chuyện của tôi đang được hoàn thiện — "
    "bạn có thể hỏi tôi về xe hoặc yêu cầu điều khiển nhé."
)


def _route_after_classify(state: AgentState) -> str:
    reason = state.get("route_reason", "")
    if reason == "slm_classified_control":
        return "slm"
    if reason == "slm_classified_chitchat":
        return "compose"
    # slm_classified_manual VÀ slm_classify_failed cùng về rag: fail-safe là
    # hành vi ADR-011 cũ, không phải một nhánh riêng cần bảo trì.
    return "rag"
```

3b. Đổi `_route_after_routing` thành factory (theo mẫu `_make_route_after_safety` ngay dưới nó). Giữ nguyên toàn bộ thân hàm hiện có, chỉ thêm một nhánh **trước** hai dòng `manual_query`/`tire_pressure_query`:

```python
def _make_route_after_routing(has_classifier: bool) -> Callable[[AgentState], str]:
    def _route_after_routing(state: AgentState) -> str:
        outcome = state.get("outcome")
        if outcome == "control":
            return "validate"
        if outcome == "offer":
            return "compose"
        if state.get("intent") == "manual_continue":
            return "compose"
        if state.get("intent") == "manual_stop_reading":
            return "compose"
        # SP-1: nhánh trượt default_to_manual đổi nghĩa thành "hỏi SLM" — nhưng
        # CHỈ nhánh trượt. Câu router hiểu (manual_question, tire_pressure...)
        # vẫn đi thẳng, đúng thiết kế đường tắt.
        if has_classifier and state.get("route_reason") == "default_to_manual":
            return "slm_classify"
        if state.get("intent") == "tire_pressure_query":
            return "rag"
        if state.get("intent") == "manual_query":
            return "rag"
        if outcome == "not_control":
            return "slm"
        return "compose"

    return _route_after_routing
```

Xoá hàm `_route_after_routing` module-level cũ (thân đã chuyển nguyên vào factory — giữ nguyên các comment gốc của nó khi chuyển).

3c. Trong `build_graph`: thêm param `classifier: Classifier | None = None` (import `Classifier` từ `src.agents.slm` cùng chỗ import `Planner`), rồi trong thân — node closure đặt cạnh `slm_stage`:

```python
    async def classify_stage(state: AgentState) -> dict:
        """Một lượt gọi, chỉ phân loại. Mọi lỗi rơi về manual — ADR-011 cũ."""
        text = state.get("normalized_text", "")
        try:
            intent = classifier.classify(text)  # type: ignore[union-attr]
        except (SlmSchemaError, OSError, httpx.HTTPError) as exc:
            # Cùng bộ ba exception với slm_stage, cùng lý do: httpx.HTTPError
            # không phải OSError, server chết mà chỉ bắt OSError thì 500 xuyên graph.
            logger.warning("slm_classify hỏng, rơi về manual: %s", exc)
            return {"route_reason": "slm_classify_failed"}
        return {"route_reason": f"slm_classified_{intent}", **(
            {"outcome": "chitchat", "chitchat_reply": CHITCHAT_TAM_GIU} if intent == "chitchat" else {}
        )}
```

3d. Phần wiring — thay dòng `add_conditional_edges("route", ...)` hiện có:

```python
    routing_targets = {"validate": "validate", "rag": "rag", "slm": "slm", "compose": "compose"}
    if classifier is not None:
        builder.add_node("slm_classify", _timed("slm_classify", classify_stage))
        builder.add_conditional_edges(
            "slm_classify", _route_after_classify, {"slm": "slm", "rag": "rag", "compose": "compose"}
        )
        routing_targets["slm_classify"] = "slm_classify"
    builder.add_conditional_edges("route", _make_route_after_routing(classifier is not None), routing_targets)
```

- [ ] **Step 4: Chạy lại — pass, kèm hai suite hàng xóm và ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_classify_node.py tests/test_agents/test_graph.py tests/test_agents/test_slm.py tests/test_agents/test_hitl_node.py -q
ruff check src/agents/graph.py tests/test_agents/test_slm_classify_node.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/graph.py tests/test_agents/test_slm_classify_node.py
git commit -m "feat(agent): node slm_classify - cau la hoi SLM truoc, fail-safe ve manual (SP-1)"
```

---

### Task 4: Config + nối vào `session_state`

**Files:**
- Modify: `src/config.py:35` (cạnh `slm_timeout_s`)
- Modify: `src/api/session_state.py:190-216` (`get_graph`)
- Test: `tests/test_api/test_session_state_slm.py` (mới; nếu đã có file test session_state thì thêm vào đó — kiểm bằng `ls tests/test_api/ | grep session`)

**Interfaces:**
- Consumes: `QwenClassifier` (Task 2), `build_graph(..., classifier=...)` (Task 3).
- Produces: `Settings.slm_classify_timeout_s: float = 2.0`; `get_graph()` truyền classifier khi `slm_enabled=true`.

- [ ] **Step 1: Viết test fail**

```python
"""slm_enabled gác luôn classifier — một cờ, các vai đi cùng nhau (spec §3.2)."""

from src.api.session_state import get_graph


def test_slm_enabled_bat_thi_graph_co_node_classify(monkeypatch):
    monkeypatch.setenv("SLM_ENABLED", "true")
    from src.config import get_settings

    get_settings.cache_clear()
    graph = get_graph("phien-test-classify-bat")
    assert "slm_classify" in graph.get_graph().nodes
    get_settings.cache_clear()


def test_slm_enabled_tat_thi_khong_co(monkeypatch):
    monkeypatch.setenv("SLM_ENABLED", "false")
    from src.config import get_settings

    get_settings.cache_clear()
    graph = get_graph("phien-test-classify-tat")
    assert "slm_classify" not in graph.get_graph().nodes
    get_settings.cache_clear()


def test_timeout_classify_mac_dinh_2s(monkeypatch):
    from src.config import get_settings

    get_settings.cache_clear()
    assert get_settings().slm_classify_timeout_s == 2.0
```

(`get_settings` là `@lru_cache` — xem cách các test config sẵn có clear cache, `grep -rn "cache_clear" tests/ | head -3`, và làm đúng nếp đó. `get_graph` cache theo session_id nên mỗi test dùng một session_id riêng.)

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_session_state_slm.py -q
```

Expected: FAIL — `AttributeError: slm_classify_timeout_s` (hoặc node không có).

- [ ] **Step 3: Cài**

`src/config.py`, ngay dưới `slm_timeout_s`:

```python
    #: Timeout RIÊNG cho vai classify — 2 s, chặt hơn hẳn 8 s của planner: phân
    #: loại chỉ sinh ~10 token, chờ lâu hơn nghĩa là server đang ốm, và fail-safe
    #: về manual rẻ hơn bắt tài xế đợi. SP-0 đo lại số này.
    slm_classify_timeout_s: float = Field(default=2.0, gt=0.0)
```

`src/api/session_state.py`, trong `get_graph`, khối `if settings.slm_enabled:`:

```python
            from src.agents.slm import QwenClassifier, QwenLeadIn, QwenPlanner  # noqa: F401

            planner = QwenPlanner(settings.slm_endpoint, settings.slm_model_id, settings.slm_timeout_s)
            classifier = QwenClassifier(settings.slm_endpoint, settings.slm_model_id, settings.slm_classify_timeout_s)
```

(khai `classifier = None` cạnh `planner = None` phía trên, và thêm `classifier=classifier,` vào lời gọi `build_graph`).

- [ ] **Step 4: Chạy lại — pass, kèm suite API mỏng**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_session_state_slm.py tests/test_api/ -q -x --timeout 300
```

(Nếu suite `tests/test_api/` đầy đủ quá chậm ở vòng lặp này, chạy riêng file mới + `tests/test_api/test_turns*.py`; suite đầy đủ chạy ở Step 4 của Task 7.)

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/api/session_state.py tests/test_api/test_session_state_slm.py
git commit -m "feat(api): noi classifier vao get_graph duoi co slm_enabled, timeout rieng 2s (SP-1)"
```

---

### Task 5: Bộ đo định tuyến — dataset + mode eval + ma trận nhầm lẫn

**Files:**
- Create: `eval/datasets/agent/dinh-tuyen-v1/cases.jsonl`
- Create: `eval/datasets/agent/dinh-tuyen-v1/README.md`
- Modify: `src/agents/eval.py` (mode mới `dinh-tuyen`)
- Test: `tests/test_agents/test_eval_dinh_tuyen.py` (mới)

**Interfaces:**
- Consumes: `DeterministicControlRouter` (đường tắt chạy trước), `Classifier` protocol (Task 2 — eval nhận classifier tiêm được để test không cần server).
- Produces:
  - `run_dinh_tuyen_eval(dataset: Path, results_root: Path, classifier: Classifier, run_id: str | None = None) -> Path` — ghi run dir bất biến (`manifest.json`, `case_results.jsonl`, `metrics.json`) vào `eval/results/agent-routing/`.
  - `metrics.json` chứa `ma_tran` (9 ô `{expected}->{predicted}`), `duong_tat` (số ca router khớp luật, không gọi classifier), và `cong_cung_manual_sang_control` (int — PHẢI 0).
  - CLI: `python -m src.agents.eval --mode dinh-tuyen` (đòi server thật, in cảnh báo nếu không nối được).

- [ ] **Step 1: Tạo dataset**

`eval/datasets/agent/dinh-tuyen-v1/README.md`:

```markdown
# dinh-tuyen-v1 — bộ đo phân loại 3 lớp của SP-1

Ghép từ ba nguồn để tránh lặp bài học `agent/v3` (đề tự ra = tripwire, không phải
thước): phần manual lấy nguyên văn `hoi-nhu-tai-xe-v1` (42 ca, RAG workstream
viết); phần control là ca #149/ADR-022 cộng biến thể mệnh lệnh không khớp luật
(20 ca, liệt kê dưới); phần chitchat sẽ do SP-2 bổ sung (~40 ca) — trước đó
ma trận chỉ có 2 lớp và PHẢI ghi rõ điều đó trong mọi trích dẫn kết quả.

Trường: `case_id`, `input_text`, `expected_route` ∈ {control, manual, chitchat},
`source`. Cổng cứng: ô `manual→control` = 0 (ADR-011 giữ nó bằng 0 về cấu trúc;
classifier không được mở ra).
```

Sinh phần manual bằng script một lần (chạy rồi bỏ, không commit script):

```powershell
.\.venv\Scripts\python.exe -c "
import json, io, pathlib
ra = []
for i, line in enumerate(io.open('eval/datasets/manual/hoi-nhu-tai-xe-v1/cases.jsonl', encoding='utf-8')):
    if not line.strip(): continue
    c = json.loads(line)
    ra.append({'case_id': f'DT-M{i+1:03d}', 'input_text': c['input_text'], 'expected_route': 'manual', 'source': 'hoi-nhu-tai-xe-v1'})
p = pathlib.Path('eval/datasets/agent/dinh-tuyen-v1'); p.mkdir(parents=True, exist_ok=True)
with io.open(p / 'cases.jsonl', 'w', encoding='utf-8', newline='\n') as f:
    for r in ra: f.write(json.dumps(r, ensure_ascii=False) + '\n')
print(len(ra), 'ca manual')
"
```

(Nếu `cases.jsonl` nguồn dùng tên trường khác `input_text`, xem bằng `head -1` và sửa cho khớp.) Rồi **nối thêm 20 ca control này** vào cuối file (mỗi dòng một JSON, `source: "phien-149-bien-the"`):

```
DT-C001  Nóng quá, giảm nhiệt độ xuống đi
DT-C002  Lạnh cóng rồi, cho ấm lên chút
DT-C003  Cho ghế ngả ra sau một chút
DT-C004  Chỉnh ghế thoải mái hơn đi
DT-C005  Ồn quá, vặn nhỏ tiếng xuống
DT-C006  Nghe gì đó vui vui đi
DT-C007  Ngột ngạt quá, cho thoáng chút đi
DT-C008  Tối quá, cho sáng lên tí
DT-C009  Gió mạnh quá đấy
DT-C010  Cho tôi chút không khí trong lành
DT-C011  Kính mờ hết cả rồi
DT-C012  Sau lưng đau quá, đỡ tôi cái
DT-C013  Mở giùm cái cửa sổ cho con bé nó nhìn
DT-C014  Im lặng chút được không, tôi cần tập trung
DT-C015  Chân lạnh quá nhỉ
DT-C016  Đưa tôi về nhà đi
DT-C017  Ghé đâu đó uống cà phê đi
DT-C018  Bài này chán quá, đổi bài khác
DT-C019  Ấm lên 26 độ giùm
DT-C020  Quay lại bài lúc nãy đi
```

Lưu ý ghi vào README: nhãn `expected_route` của 20 ca này là **control theo nghĩa
phân loại** (tài xế muốn xe làm gì) — planner có ra plan chạy được hay không là
việc của ADR-016, không phải của bộ đo này.

- [ ] **Step 2: Viết test fail cho eval**

`tests/test_agents/test_eval_dinh_tuyen.py`:

```python
"""Eval định tuyến: đường tắt chạy trước, ma trận đầy đủ, cổng cứng manual→control=0."""

import json
from pathlib import Path

from src.agents.eval import run_dinh_tuyen_eval


class ClassifierLuonControl:
    def classify(self, normalized_text: str) -> str:
        return "control"


def _viet_dataset(tmp_path: Path) -> Path:
    cases = [
        {"case_id": "T1", "input_text": "bật điều hòa", "expected_route": "control", "source": "t"},
        {"case_id": "T2", "input_text": "Nóng quá trời hôm nay ha", "expected_route": "chitchat", "source": "t"},
        {"case_id": "T3", "input_text": "Đèn pin là gì nhỉ theo sổ tay", "expected_route": "manual", "source": "t"},
    ]
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    return p


def test_duong_tat_khong_goi_classifier_va_ma_tran_day_du(tmp_path):
    run_dir = run_dinh_tuyen_eval(_viet_dataset(tmp_path), tmp_path / "results", ClassifierLuonControl())
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    # T1 khớp luật router → đường tắt, đúng control mà KHÔNG qua classifier.
    assert metrics["duong_tat"] >= 1
    # T2/T3 bị ClassifierLuonControl đẩy sang control → hai ô nhầm phải hiện ra.
    assert metrics["ma_tran"]["chitchat->control"] == 1
    assert metrics["ma_tran"]["manual->control"] == 1
    assert metrics["cong_cung_manual_sang_control"] == 1  # bộ đếm phải TRUNG THỰC, không che


def test_run_dir_du_ba_file(tmp_path):
    run_dir = run_dinh_tuyen_eval(_viet_dataset(tmp_path), tmp_path / "results", ClassifierLuonControl())
    for ten in ("manifest.json", "case_results.jsonl", "metrics.json"):
        assert (run_dir / ten).exists()
```

- [ ] **Step 3: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval_dinh_tuyen.py -q
```

Expected: FAIL — `ImportError: cannot import name 'run_dinh_tuyen_eval'`.

- [ ] **Step 4: Cài `run_dinh_tuyen_eval` vào `src/agents/eval.py`**

Theo đúng khuôn `run_routing_eval` sẵn có trong file (đọc nó trước khi viết — cách nó tạo run_id UTC, ghi manifest, dùng `results_root`):

```python
def run_dinh_tuyen_eval(
    dataset: Path,
    results_root: Path,
    classifier: "Classifier",
    run_id: str | None = None,
) -> Path:
    """Đo phân loại 3 lớp: router chạy trước (đường tắt), classifier chỉ nhận câu trượt.

    Ô `manual->control` là cổng cứng = 0 — nhưng eval GHI SỐ THẬT, không assert:
    thước phải trung thực, còn cổng là việc của người đọc metrics và của CI sau này.
    """
    from src.agents.router import DeterministicControlRouter

    router = DeterministicControlRouter()
    rows: list[dict[str, Any]] = []
    for case in load_cases(dataset):
        text = case["input_text"]
        quyet_dinh = router.route(text)
        if quyet_dinh.reason != "default_to_manual":
            predicted = "control" if quyet_dinh.disposition in {"control", "offer"} else "manual"
            duong = "duong_tat"
        else:
            try:
                predicted = classifier.classify(text)
            except Exception as exc:  # noqa: BLE001 - eval phải chạy hết bộ, lỗi là dữ liệu
                predicted = f"error:{type(exc).__name__}"
            duong = "slm"
        rows.append({
            "case_id": case["case_id"],
            "input_text": text,
            "expected": case["expected_route"],
            "predicted": predicted,
            "duong": duong,
        })

    ma_tran: dict[str, int] = {}
    for r in rows:
        khoa = f"{r['expected']}->{r['predicted']}"
        ma_tran[khoa] = ma_tran.get(khoa, 0) + 1
    metrics = {
        "n": len(rows),
        "duong_tat": sum(1 for r in rows if r["duong"] == "duong_tat"),
        "ma_tran": ma_tran,
        "dung": sum(1 for r in rows if r["expected"] == r["predicted"]),
        "cong_cung_manual_sang_control": ma_tran.get("manual->control", 0),
    }
    # Ghi run dir bất biến — dùng đúng helper/khuôn của run_routing_eval trong file
    # này (manifest kèm dataset path + git sha, case_results.jsonl từng dòng, metrics.json).
    return _write_run_dir(results_root, "agent-routing", rows, metrics, run_id)
```

(`_write_run_dir` là tên gợi ý — nếu `run_routing_eval` viết trực tiếp không qua helper, tách phần ghi của nó thành helper dùng chung cho cả hai, giữ nguyên format cũ để run cũ vẫn đọc được. Việc `router.route(...)` nhận đúng tham số gì — text hay thêm snapshot — xem chữ ký thật `grep -n "def route" src/agents/router.py` và gọi đúng.)

Nối CLI trong `main()`: thêm `"dinh-tuyen"` vào `choices`, nhánh mới dựng `QwenClassifier(settings.slm_endpoint, settings.slm_model_id, settings.slm_classify_timeout_s)` và mặc định dataset `eval/datasets/agent/dinh-tuyen-v1/cases.jsonl`, results root `eval/results/agent-routing/`.

- [ ] **Step 5: Chạy lại — pass, kèm ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval_dinh_tuyen.py tests/test_agents/test_eval.py -q
ruff check src/agents/eval.py tests/test_agents/test_eval_dinh_tuyen.py
```

- [ ] **Step 6: Commit**

```bash
git add eval/datasets/agent/dinh-tuyen-v1/ src/agents/eval.py tests/test_agents/test_eval_dinh_tuyen.py
git commit -m "feat(eval): bo do dinh tuyen 3 lop - duong tat truoc, ma tran nham lan, cong manual->control=0 (SP-1)"
```

---

### Task 6: Contract test với llama-server thật

**Files:**
- Test: `tests/test_agents/test_slm_classifier_contract.py` (mới)

**Interfaces:**
- Consumes: `QwenClassifier` (Task 2), server thật ở `SLM_ENDPOINT`.
- Produces: bằng chứng grammar ép enum trên model thật + số `slm_classify_ms` đầu tiên.

- [ ] **Step 1: Viết test (skip mặc định — cần server)**

```python
"""Contract với llama-server thật. Bật bằng: $env:SLM_SERVER_TESTS="1".

CI không chạy tầng này (không có model) — bằng chứng sinh từ máy dev,
đúng nếp các test model khác của repo.
"""

import os
import time

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.getenv("SLM_SERVER_TESTS") != "1", reason="cần llama-server thật (SLM_SERVER_TESTS=1)"),
]

from src.agents.slm import CLASSIFY_INTENTS, QwenClassifier
from src.config import get_settings


@pytest.fixture()
def classifier():
    s = get_settings()
    return QwenClassifier(s.slm_endpoint, s.slm_model_id, s.slm_classify_timeout_s)


def test_grammar_ep_enum_tren_model_that(classifier):
    """Bất kể model nghĩ gì, đầu ra PHẢI là một trong ba lớp — grammar lo việc đó."""
    for cau in ("Nóng quá, giảm nhiệt độ xuống đi", "Áp suất lốp bao nhiêu?", "Chào buổi sáng nha"):
        assert classifier.classify(cau) in CLASSIFY_INTENTS


def test_khong_co_thinking_leak_va_do_tre_ghi_nhan(classifier):
    """Grammar chặn <think> (token đầu buộc là `{`). Đo tay 5 lượt để có số đầu tiên
    cho SP-0 — in ra chứ không assert ngưỡng: chưa có phân bố thì chưa đặt cổng."""
    do_tre = []
    for _ in range(5):
        t0 = time.perf_counter()
        ket_qua = classifier.classify("Xe này đi đường dài có êm không nhỉ?")
        do_tre.append((time.perf_counter() - t0) * 1000)
        assert ket_qua in CLASSIFY_INTENTS
    print(f"\nslm_classify_ms 5 lượt: {[round(x) for x in do_tre]}")
```

- [ ] **Step 2: Chạy KHÔNG server — phải skip sạch**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_classifier_contract.py -q -rs
```

Expected: `2 skipped`.

- [ ] **Step 3: Chạy CÓ server (llama-server Qwen3-4B trên 8093 đang chạy sẵn trên máy này)**

```powershell
$env:MQTT_ENABLED="false"; $env:SLM_SERVER_TESTS="1"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_classifier_contract.py -q -s
```

Expected: PASS, và dòng `slm_classify_ms 5 lượt: [...]` — **chép số này vào WORKLOG** (Task 7).

- [ ] **Step 4: Commit**

```bash
git add tests/test_agents/test_slm_classifier_contract.py
git commit -m "test(agent): contract classifier voi llama-server that - grammar ep enum, do so dau tien (SP-1)"
```

---

### Task 7: ADR-026, runbook, WORKLOG, chạy lần đầu bộ đo

**Files:**
- Create: `docs/adr/ADR-026-slm-classify-truoc-rag.md`
- Modify: `docs/huong_dan_chay.md` (bảng cờ §2.3)
- Modify: `WORKLOG.md` (đúng format bảng sẵn có)

**Interfaces:**
- Consumes: mọi task trước; run id từ lần chạy eval đầu tiên.

- [ ] **Step 1: Viết ADR-026** — nội dung bám spec §3.1 hệ quả 3: Context (ADR-022 chỉ mở planner sau khi RAG trượt; classifier mở sớm hơn), Decision (câu `default_to_manual` đi `slm_classify` trước; chiều "RAG trượt → planner" của ADR-022 **giữ nguyên làm lưới**; fail-safe ba tầng về manual = ADR-011), Consequences (route_reason mới; `slm_enabled=false` giao hệt cũ; ô `manual→control` phải giữ 0 — trỏ tới bộ đo `dinh-tuyen-v1`). Ghi Status `Accepted`, Date 2026-08-21, liên kết ADR-011/016/022 và spec.

- [ ] **Step 2: Cập nhật runbook** `docs/huong_dan_chay.md` §2.3 — bảng "Bốn cờ model": sửa dòng `SLM_ENABLED` thành "gác **hai** vai: planner + classifier (SP-1)"; thêm ghi chú timeout riêng `SLM_CLASSIFY_TIMEOUT_S=2.0`; nhắc lại một model 4 vai trên 8093 và lệnh chạy eval:

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode dinh-tuyen   # -> eval/results/agent-routing/
```

- [ ] **Step 3: Chạy bộ đo lần đầu với server thật** (llama-server đang chạy trên máy):

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode dinh-tuyen
```

Đọc `metrics.json` của run vừa tạo. **Kiểm cổng cứng: `cong_cung_manual_sang_control` phải = 0.** Nếu ≠ 0: mở `case_results.jsonl` xem ca nào, sửa few-shot trong `CLASSIFY_SYSTEM` (Task 2) — mỗi lần sửa prompt chạy lại eval ra run id mới, KHÔNG sửa run cũ. Ghi run id + ma trận vào WORKLOG.

- [ ] **Step 4: Chạy toàn suite + ruff lần cuối**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
ruff check src/ tests/
```

Expected: pass toàn bộ (số skip tùy máy — xem CLAUDE.md, kiểm bằng `-rs` nếu khác 17).

- [ ] **Step 5: Cập nhật WORKLOG.md** theo format bảng sẵn có: ngày 2026-08-21, việc "SP-1 SLM bộ não định tuyến", kèm run id eval + số `slm_classify_ms` từ Task 6.

- [ ] **Step 6: Commit**

```bash
git add docs/adr/ADR-026-slm-classify-truoc-rag.md docs/huong_dan_chay.md WORKLOG.md eval/results/agent-routing/
git commit -m "docs(adr): ADR-026 slm_classify truoc RAG - thu hep ADR-022, kem run dau tien (SP-1)"
```

---

## Ghi chú cho người thực thi

- **Đừng "dọn dẹp" `SLM_UNION_PROMPT`**: union planner vẫn tự xử lý chitchat cho các câu `not_control` không đi qua classifier (nhánh `outcome == "not_control"` cũ). Hai đường chitchat tồn tại song song trong SP-1 là **cố ý** — SP-2 mới hợp nhất.
- **Đừng đổi hành vi khi `classifier=None`**: mọi test sẵn có (2000+) dựng graph không có classifier và phải xanh nguyên.
- Nếu một bước phát hiện chữ ký thật khác plan (tên field dataset, chữ ký `router.route`), sửa theo **code thật** và ghi chú lại trong commit message — plan viết từ hiện trạng 2026-08-21 nhánh `feat/slm-bo-nao-dinh-tuyen`.

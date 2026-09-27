# SP-2 Chitchat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Câu được classifier chấm `chitchat` nhận một câu trả lời xã giao do model sinh (prompt riêng), đi qua bốn lớp cổng tất định, thay cho câu giữ chỗ `CHITCHAT_TAM_GIU`; câu xã giao có dấu hỏi không còn bị luật `manual_question` nuốt.

**Architecture:** Node `chitchat` mới trong LangGraph nhận nhánh `slm_classified_chitchat`, gọi `QwenChitchat.reply()` (cùng llama-server, prompt riêng ~250 token, `json_schema {"reply"}`), rồi `qua_cong_chitchat()` (hệ chữ lạ → quá dài → số kèm đơn vị → "đã làm gì") quyết định phát chuỗi model hay câu mẫu. Router chỉ rẽ `manual_question` khi câu có từ vựng về xe (`co_tu_vung_xe`). Bộ đo `chitchat-v1` + mode `--mode chitchat` ghi run dir bất biến với hai cổng cứng.

**Tech Stack:** Python 3.11.9, LangGraph, httpx, llama-server (`json_schema`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-sp2-chitchat-design.md`

## Global Constraints

- Test bằng `.\.venv\Scripts\python.exe` với `$env:MQTT_ENABLED="false"`; `ruff check src/ tests/` sạch trước mỗi commit (N802: tên test không viết hoa).
- Không thêm cờ: `slm_enabled` gác luôn generator. `SLM_ENABLED=false` ⇒ graph giao hệt develop (test khoá bằng so node).
- Không đặt tên stage trace mới — độ trễ sinh chitchat tính vào `planning_or_retrieval` (`record_stage` raise với tên lạ, bài học #242).
- Cổng là chỗ duy nhất chặn bịa: tất định, mỗi lớp một test, vỡ lớp nào rơi về câu mẫu; **không bao giờ** phát chuỗi model đã bị chặn.
- Bằng chứng bắt buộc trước merge: 41/41 câu `hoi-nhu-tai-xe-v1` vẫn là `manual_question` (đường tắt); cổng cứng `manual→control = 0` và `bẫy→chitchat = 0` trên run thật.
- Dataset: ghi `source` từng ca; câu tự viết dán nhãn `tu_viet` = tripwire; không tự viết bù rồi gọi là độc lập.
- Mọi con số trong PR trỏ về run id dưới `eval/results/chitchat/` hoặc `eval/results/agent-routing/`.
- Không sửa `.ai-log/`; hook pre-push fail thì báo, không `--no-verify`.

---

### Task 1: `co_tu_vung_xe` — luật `manual_question` chỉ khi câu nói về xe

**Files:**
- Modify: `src/agents/question.py` (thêm `_TU_VUNG_XE`, `co_tu_vung_xe`)
- Modify: `src/agents/router.py` (hai nhánh `manual_question` trong `_match`)
- Test: `tests/test_agents/test_tu_vung_xe.py` (mới)

**Interfaces:**
- Consumes: `is_information_question(normalized)`, `is_question(raw, normalized)` (có sẵn), `normalize_vi`.
- Produces: `co_tu_vung_xe(normalized: str) -> bool` trong `src/agents/question.py`; router trả `default_to_manual` cho câu hỏi không có từ vựng xe.

- [ ] **Step 1: Viết test fail**

```python
"""Luật manual_question chỉ bắt câu HỎI VỀ XE. Câu xã giao có dấu hỏi rơi xuống
classifier (SP-2 §2.3). Bằng chứng giữ đường tắt: 41/41 câu hoi-nhu-tai-xe-v1."""

import io
import json

import pytest

from src.agents.normalize import normalize_vi
from src.agents.question import co_tu_vung_xe
from src.agents.router import DeterministicControlRouter

router = DeterministicControlRouter()

#: 4/15 câu chitchat của SP-0 bị `manual_question` nuốt (run 20260822T030757).
CHITCHAT_CO_DAU_HOI = [
    "Xin chào, hôm nay khỏe không?",
    "Cậu tên gì thế?",
    "Xe này đi đường dài có êm không nhỉ?",
    "Đi Đà Lạt chơi thích không",
]


@pytest.mark.parametrize("text", ["Áp suất lốp bao nhiêu là đủ?", "Đèn cảnh báo hình cục pin nghĩa là gì?", "Sạc xe ở nhà thế nào?"])
def test_cau_hoi_ve_xe_co_tu_vung(text):
    assert co_tu_vung_xe(normalize_vi(text))


@pytest.mark.parametrize("text", ["Xin chào, hôm nay khỏe không?", "Cậu tên gì thế?", "Đi Đà Lạt chơi thích không"])
def test_cau_xa_giao_khong_co_tu_vung(text):
    assert not co_tu_vung_xe(normalize_vi(text))


@pytest.mark.parametrize("text", CHITCHAT_CO_DAU_HOI[:2] + [CHITCHAT_CO_DAU_HOI[3]])
def test_xa_giao_co_dau_hoi_roi_xuong_classifier(text):
    quyet_dinh = router.route(text)
    assert quyet_dinh.reason == "default_to_manual", quyet_dinh


def test_xe_nay_di_duong_dai_van_la_cau_ve_xe():
    """Có chữ "xe" → đường tắt sổ tay là ĐÚNG: classifier không được giành ca này.
    Spec chấp nhận: 1/4 câu SP-0 ở lại sổ tay vì nó thật sự nói về xe."""
    assert router.route(CHITCHAT_CO_DAU_HOI[2]).reason == "manual_question"


def test_41_cau_hoi_nhu_tai_xe_van_di_duong_tat():
    """Bằng chứng bắt buộc của spec §2.3: không mất một ca đường tắt nào."""
    mat = []
    for line in io.open("eval/datasets/manual/hoi-nhu-tai-xe-v1/cases.jsonl", encoding="utf-8"):
        if not line.strip():
            continue
        cau = json.loads(line)["question"]
        if router.route(cau).reason == "default_to_manual" and not co_tu_vung_xe(normalize_vi(cau)):
            mat.append(cau)
    assert mat == [], f"câu hỏi về xe bị mất đường tắt vì thiếu từ vựng: {mat}"
```

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_tu_vung_xe.py -q
```

Expected: FAIL — `ImportError: cannot import name 'co_tu_vung_xe'`.

- [ ] **Step 3: Cài `question.py`** (thêm cuối file)

```python
#: Từ vựng "câu này có nói về XE không" — danh sách ĐÓNG, curate từ
#: `docs/coverage_matrix.md` + 58 section của sổ tay VF9. Không phải luật điều
#: khiển: nó chỉ quyết định câu hỏi đi đường tắt sổ tay hay rơi xuống classifier.
#:
#: Vì sao cần (SP-2 §2.3, run `do-tre/20260822T030757`): 4/15 câu xã giao có dấu
#: hỏi ("Xin chào, hôm nay khỏe không?") bị `manual_question` bắt thành câu hỏi sổ
#: tay và trả "không tìm thấy" — classifier không bao giờ được hỏi. Câu hỏi KHÔNG
#: dính mục nào ở đây thì không phải câu hỏi về xe.
#:
#: Thêm mục mới thì chạy lại `tests/test_agents/test_tu_vung_xe.py::test_41_cau_hoi_nhu_tai_xe_van_di_duong_tat`.
_TU_VUNG_XE: tuple[str, ...] = (
    "xe", "vinfast", "vf", "ô tô", "oto",
    "điều hòa", "điều hoà", "máy lạnh", "nhiệt độ", "quạt gió", "sưởi",
    "ghế", "vô lăng", "tay lái", "gương", "kính", "cửa", "cốp", "nắp",
    "đèn", "pha", "cốt", "xi nhan", "sương mù",
    "nhạc", "âm lượng", "loa", "radio", "bluetooth", "điện thoại", "màn hình", "app", "ứng dụng",
    "lốp", "áp suất", "bánh", "phanh", "abs", "ga", "cruise", "số", "hộp số",
    "pin", "sạc", "điện", "ắc quy", "cầu chì", "km", "quãng đường", "dặm",
    "dây an toàn", "túi khí", "camera", "cảm biến", "radar", "còi", "gạt nước", "gạt mưa",
    "chìa khóa", "chìa khoá", "khóa", "khoá", "mở khóa", "mở khoá",
    "bảo dưỡng", "bảo hành", "dầu", "nước làm mát", "nước rửa kính", "lọc gió",
    "động cơ", "mô tơ", "camp", "cắm trại", "chế độ", "cảnh báo", "báo lỗi", "đèn báo",
    "dẫn đường", "bản đồ", "định vị", "sổ tay", "hướng dẫn sử dụng",
)


def co_tu_vung_xe(normalized: str) -> bool:
    """Câu (đã normalize) có nhắc tới xe hay một bộ phận/tính năng của xe không."""
    return any(tu in normalized for tu in _TU_VUNG_XE)
```

(Nếu `normalize_vi` bỏ dấu hoặc hạ chữ, xem `grep -n "def normalize_vi" -A 15 src/agents/normalize.py` để chắc danh sách viết đúng dạng đã normalize — các mục trên viết thường, có dấu, khớp với cách `HOW_WHAT_MARKERS` đang được so.)

- [ ] **Step 4: Cài `router.py`** — trong `_match`, hai nhánh `manual_question`:

```python
        # Hỏi xin giải thích thì luôn tra sổ tay, kể cả khi câu chứa từ khoá điều
        # khiển. `"Chỉnh nhiệt độ thế nào?"` hỏi *cách làm*; đáp lại bằng
        # "bạn muốn chỉnh bao nhiêu độ?" là trả lời sai câu hỏi.
        # SP-2: CHỈ KHI câu có từ vựng về xe — "Cậu tên gì thế?" cũng có "gì" nhưng
        # không hỏi về xe; để nó rơi xuống classifier. Xem `co_tu_vung_xe`.
        if is_information_question(text) and co_tu_vung_xe(text):
            return "not_control", "manual_query", "manual_question", ()

        if is_question(raw_text, text):
            matched = self._run_matchers(text)
            if matched is None:
                if co_tu_vung_xe(text):
                    return "not_control", "manual_query", "manual_question", ()
                # Câu hỏi không về xe: không phải việc của sổ tay, để classifier quyết.
            else:
                disposition, intent, _reason, steps = matched
                if disposition == "control":
                    return "offer", intent, "question_about_supported_action", steps
                return matched
```

(Giữ nguyên các comment gốc của khối `is_question`; chỉ đổi cấu trúc như trên. Import `co_tu_vung_xe` vào dòng `from src.agents.question import ...`.)

- [ ] **Step 5: Chạy lại — pass, kèm toàn bộ router/question/eval**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_tu_vung_xe.py tests/test_agents/test_router.py tests/test_agents/test_question.py tests/test_agents/test_eval.py tests/test_agents/test_eval_dinh_tuyen.py -q
ruff check src/agents/question.py src/agents/router.py tests/test_agents/test_tu_vung_xe.py
```

Nếu `test_router.py` có ca câu hỏi không-về-xe đang mong `manual_question` (ví dụ câu đùa), đọc docstring test đó: nếu nó khoá hành vi ADR-011 "mặc định tra sổ tay" thì **vẫn đúng** — câu giờ về `default_to_manual`, cũng là mặc định sổ tay khi không có classifier; sửa assert sang `default_to_manual` và ghi lý do SP-2.

- [ ] **Step 6: Commit**

```bash
git add src/agents/question.py src/agents/router.py tests/test_agents/test_tu_vung_xe.py tests/test_agents/test_router.py
git commit -m "feat(router): manual_question chi khi cau co tu vung xe - xa giao co dau hoi roi xuong classifier (SP-2)"
```

---

### Task 2: `QwenChitchat` — prompt riêng, `json_schema {"reply"}`, timeout riêng

**Files:**
- Modify: `src/agents/slm.py` (thêm cuối file)
- Modify: `src/config.py:39` (cạnh `slm_classify_timeout_s`)
- Test: `tests/test_agents/test_slm_chitchat.py` (mới)

**Interfaces:**
- Consumes: `chatml(system, user)`, `SlmSchemaError` (có sẵn trong `slm.py`).
- Produces:
  - `CHITCHAT_SYSTEM: str`, `CHITCHAT_SCHEMA: dict`, `CHITCHAT_MAX_CHARS` (= 240, đã có — dùng lại).
  - `parse_chitchat_output(raw: str) -> str` — raise `SlmSchemaError` khi rỗng/sai.
  - `class ChitchatWriter(Protocol): def reply(self, normalized_text: str) -> str: ...`
  - `class QwenChitchat(endpoint, model_id, timeout_s=4.0)` — `reply()` trả chuỗi model (CHƯA qua cổng), httpx error lan ra.
  - `Settings.slm_chitchat_timeout_s: float = 4.0`.

- [ ] **Step 1: Viết test fail**

```python
"""Vai chitchat: prompt riêng, một lượt gọi, ép JSON. Cổng nội dung nằm ở
`nodes/chitchat_cong.py`, KHÔNG ở đây — client chỉ lấy chữ về."""

import json

import pytest

from src.agents.slm import (
    CHITCHAT_MAX_CHARS,
    CHITCHAT_SCHEMA,
    CHITCHAT_SYSTEM,
    QwenChitchat,
    SlmSchemaError,
    parse_chitchat_output,
)


def test_parse_lay_reply():
    assert parse_chitchat_output(json.dumps({"reply": "Chào bạn!"})) == "Chào bạn!"


def test_parse_rong_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_chitchat_output('{"reply": "   "}')


def test_parse_khong_json_thi_hong():
    with pytest.raises(SlmSchemaError):
        parse_chitchat_output("Chào bạn")


def test_schema_tran_do_dai_bang_max_chars():
    assert CHITCHAT_SCHEMA["properties"]["reply"]["maxLength"] == CHITCHAT_MAX_CHARS
    assert CHITCHAT_SCHEMA["required"] == ["reply"]


def test_prompt_khoa_hai_ranh_gioi_do_duoc_o_sp0():
    """Hai ví dụ bắt buộc của spec §2.1: từ chối thời tiết, không nói số km/sạc."""
    assert "mưa" in CHITCHAT_SYSTEM
    assert "sạc" in CHITCHAT_SYSTEM
    assert "KHÔNG" in CHITCHAT_SYSTEM


def test_qwen_chitchat_gui_dung_cau_hinh(monkeypatch):
    sent = {}

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": '{"reply": "Chào bạn, đi đâu hôm nay?"}'}

    def _post(url, json=None, timeout=None):
        sent.update(url=url, body=json, timeout=timeout)
        return _R()

    import httpx

    monkeypatch.setattr(httpx, "post", _post)
    w = QwenChitchat("http://127.0.0.1:8093", "qwen3-4b", timeout_s=4.0)
    assert w.reply("Xin chào") == "Chào bạn, đi đâu hôm nay?"
    assert sent["url"].endswith("/completion")
    assert sent["body"]["json_schema"] == CHITCHAT_SCHEMA
    assert 0 < sent["body"]["temperature"] <= 0.5  # không 0: trò chuyện lặp y hệt nghe như máy
    assert sent["body"]["cache_prompt"] is True
    assert sent["body"]["n_predict"] <= 96
    assert sent["timeout"] == 4.0
    assert "Xin chào" in sent["body"]["prompt"]
```

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_chitchat.py -q
```

Expected: FAIL — `ImportError: cannot import name 'CHITCHAT_SCHEMA'`.

- [ ] **Step 3: Cài `slm.py`** (thêm cuối file)

```python
#: Schema ép ở tầng sinh: một trường, trần bằng CHITCHAT_MAX_CHARS. Grammar đồng
#: thời chặn thinking mode của Qwen3 (token đầu buộc là `{`), như classify.
CHITCHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reply": {"type": "string", "maxLength": CHITCHAT_MAX_CHARS}},
    "required": ["reply"],
    "additionalProperties": False,
}

#: Prompt chitchat — SP-2 §2.1. Hai ví dụ cuối là hai ranh giới ĐO ĐƯỢC ở SP-0
#: (run do-tre/20260822T030757): thời tiết → từ chối mềm; km/sạc → không nói số.
CHITCHAT_SYSTEM = (
    "Bạn là VIVI, trợ lý giọng nói trên xe VinFast. Trả lời tài xế bằng ĐÚNG MỘT câu "
    "tiếng Việt ngắn, thân thiện, tự nhiên như đang nói chuyện.\n"
    "Bạn chỉ trò chuyện về: xã giao, cảm xúc của tài xế, chuyến đi và đường xá.\n"
    "Ngoài phạm vi đó (tin tức, thời tiết, toán, kiến thức chung) thì nói thật rằng bạn "
    "không làm được việc này, rồi gợi ý hỏi về xe hoặc điều khiển xe.\n"
    "Tuyệt đối KHÔNG: nêu thông số kỹ thuật của xe, nói rằng đã bật/tắt/làm gì trên xe, "
    "dùng tiếng Anh hay chữ Hán.\n"
    "Ví dụ:\n"
    '- "Chào buổi sáng nha" → "Chào bạn, chúc một ngày lái xe thật nhẹ nhàng!"\n'
    '- "Tôi hơi mệt rồi" → "Nếu mệt thì ghé đâu đó nghỉ một chút nhé, tôi ở đây với bạn."\n'
    '- "Đi Đà Lạt chơi thích không" → "Đà Lạt mùa này chắc đẹp lắm, bạn đi cẩn thận đoạn đèo nhé!"\n'
    '- "Ngày mai có mưa không ta" → "Tôi không xem được dự báo thời tiết, nhưng cần gì trên xe thì cứ nói nhé."\n'
    '- "Xe này chạy được bao nhiêu km một lần sạc?" → "Con số đó để tôi tra sổ tay cho chính xác, bạn hỏi lại tôi nhé."\n'
    'Trả về JSON: {"reply": "<một câu>"}'
)


def parse_chitchat_output(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SlmSchemaError(f"chitchat output không phải JSON: {exc}") from exc
    reply = str(payload.get("reply", "")).strip() if isinstance(payload, dict) else ""
    if not reply:
        raise SlmSchemaError("chitchat rỗng")
    return reply[:CHITCHAT_MAX_CHARS]


class ChitchatWriter(Protocol):
    def reply(self, normalized_text: str) -> str: ...


class QwenChitchat:
    """Vai thứ tư trên cùng llama-server (spec SP-2 §2.1). Trả chữ THÔ — cổng nội
    dung là việc của `nodes/chitchat_cong.py`; httpx error cố ý lan ra để node
    quyết fail-safe."""

    def __init__(self, endpoint: str, model_id: str, timeout_s: float = 4.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._timeout_s = timeout_s

    def reply(self, normalized_text: str) -> str:
        import httpx

        response = httpx.post(
            f"{self._endpoint}/completion",
            json={
                "prompt": chatml(CHITCHAT_SYSTEM, normalized_text),
                # 0.3, không 0: cùng câu chào mà lượt nào cũng y hệt nhau nghe như
                # máy; 0.3 đủ đổi cách nói mà chưa đủ đổi nội dung (đo tay SP-2).
                "temperature": 0.3,
                "n_predict": 96,
                "cache_prompt": True,
                "json_schema": CHITCHAT_SCHEMA,
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return parse_chitchat_output(str(response.json().get("content", "")).strip())
```

`src/config.py`, ngay dưới `slm_classify_timeout_s`:

```python
    #: Timeout vai chitchat (SP-2): p95 sinh đo được 2,2 s (SP-0), 4 s là biên gấp đôi.
    slm_chitchat_timeout_s: float = Field(default=4.0, gt=0.0)
```

- [ ] **Step 4: Chạy lại — pass, kèm ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_chitchat.py tests/test_agents/test_slm.py tests/test_agents/test_slm_classifier.py -q
ruff check src/agents/slm.py src/config.py tests/test_agents/test_slm_chitchat.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/slm.py src/config.py tests/test_agents/test_slm_chitchat.py
git commit -m "feat(agent): QwenChitchat - prompt rieng, json_schema reply, timeout 4s (SP-2)"
```

---

### Task 3: Cổng tất định bốn lớp — `nodes/chitchat_cong.py`

**Files:**
- Create: `src/agents/nodes/chitchat_cong.py`
- Test: `tests/test_agents/test_chitchat_cong.py` (mới)

**Interfaces:**
- Consumes: `dem_khuyet_tat(noi) -> KetQuaTuNhien` (`src/rag/tu_nhien.py`, có `khuyet_tat: list[str]`, mục `"ky_tu_la"`); `_NUMBER_WITH_UNIT`, `_SENTENCE_SPLIT`, `MAX_SPOKEN_CHARS` từ `src/agents/nodes/speech_policy.py`.
- Produces:
  - `CAU_MAU_CHUNG: str`, `CAU_CHUYEN_HUONG_SO: str`
  - `qua_cong_chitchat(reply: str) -> tuple[str, str]` — `(chuỗi_phát, ten_cong)` với `ten_cong ∈ {"qua", "he_chu_la", "qua_dai", "so_ky_thuat", "noi_da_lam"}`; chuỗi_phát là reply (có thể đã cắt) hoặc câu mẫu.

- [ ] **Step 1: Viết test fail**

```python
"""Bốn lớp cổng (spec §2.2), mỗi lớp một test, thứ tự cố định. Không bao giờ
phát chuỗi đã bị chặn."""

from src.agents.nodes.chitchat_cong import CAU_CHUYEN_HUONG_SO, CAU_MAU_CHUNG, qua_cong_chitchat


def test_cau_sach_di_qua_nguyen_ven():
    assert qua_cong_chitchat("Chào bạn, chúc một ngày lái xe nhẹ nhàng!") == (
        "Chào bạn, chúc một ngày lái xe nhẹ nhàng!",
        "qua",
    )


def test_a_he_chu_la_roi_ve_cau_mau():
    """SPIKE-004 RAG-105: model xen nguyên câu tiếng Trung — dùng lại bộ dò tu_nhien."""
    chuoi, cong = qua_cong_chitchat("Chào bạn 你好, đi đâu đấy?")
    assert cong == "he_chu_la"
    assert chuoi == CAU_MAU_CHUNG


def test_b_qua_dai_cat_o_ranh_gioi_cau():
    dai = "Câu một đủ ngắn. " * 10 + "Câu cuối rất dài " * 20 + "."
    chuoi, cong = qua_cong_chitchat(dai)
    assert cong == "qua_dai"
    assert len(chuoi) <= 240
    assert chuoi.endswith(".")


def test_b_qua_dai_khong_co_ranh_gioi_thi_cau_mau():
    chuoi, cong = qua_cong_chitchat("a" * 300)
    assert (chuoi, cong) == (CAU_MAU_CHUNG, "qua_dai")


def test_c_so_ky_thuat_thanh_cau_chuyen_huong():
    """Chitchat KHÔNG được nói thông số xe — đó là việc của sổ tay (ADR-015)."""
    chuoi, cong = qua_cong_chitchat("Xe này chạy được 450 km một lần sạc đấy!")
    assert cong == "so_ky_thuat"
    assert chuoi == CAU_CHUYEN_HUONG_SO


def test_d_noi_da_lam_gi_tren_xe_roi_ve_cau_mau():
    for cau in ("Tôi đã bật điều hòa cho bạn rồi!", "Đã mở cửa sổ nhé."):
        chuoi, cong = qua_cong_chitchat(cau)
        assert cong == "noi_da_lam", cau
        assert chuoi == CAU_MAU_CHUNG


def test_rong_roi_ve_cau_mau():
    """Rỗng đi chung cửa với hệ chữ lạ: không có gì để phát thì phát câu mẫu."""
    assert qua_cong_chitchat("   ") == (CAU_MAU_CHUNG, "he_chu_la")


def test_thu_tu_lop_a_truoc_lop_c():
    """Cùng vỡ nhiều lớp thì tên cổng là lớp ĐẦU TIÊN vỡ — để eval đếm ổn định."""
    _, cong = qua_cong_chitchat("你好 450 km")
    assert cong == "he_chu_la"
```

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_chitchat_cong.py -q
```

Expected: FAIL — `ModuleNotFoundError: src.agents.nodes.chitchat_cong`.

- [ ] **Step 3: Cài `src/agents/nodes/chitchat_cong.py`**

```python
"""Cổng tất định sau generator chitchat — SP-2 §2.2.

Đây là chỗ DUY NHẤT chặn bịa. Bốn lớp, thứ tự cố định, vỡ lớp nào rơi về câu
mẫu của lớp đó; không bao giờ phát chuỗi model đã bị chặn. Tên lớp trả ra để
eval đếm được từng lớp vỡ bao nhiêu.
"""

from __future__ import annotations

import re

from src.agents.nodes.speech_policy import _NUMBER_WITH_UNIT, _SENTENCE_SPLIT, MAX_SPOKEN_CHARS
from src.rag.tu_nhien import dem_khuyet_tat

#: Câu mẫu chung — chữ tự viết, không mang dữ kiện.
CAU_MAU_CHUNG = "Tôi nghe bạn đây. Bạn muốn tôi giúp gì trên xe không?"

#: Lớp (c): model nói số kèm đơn vị → chuyển hướng về sổ tay thay vì phát con số.
CAU_CHUYEN_HUONG_SO = "Về thông số của xe, để tôi tra sổ tay cho chính xác — bạn hỏi lại tôi nhé."

#: Lớp (d): model không được NÓI rằng đã làm gì trên xe — nó không có tay.
_NOI_DA_LAM = re.compile(r"\bđã\s+(bật|tắt|mở|đóng|đặt|chỉnh|phát|dừng|khóa|khoá|hạ|kéo)\b", re.IGNORECASE)


def qua_cong_chitchat(reply: str) -> tuple[str, str]:
    """Trả `(chuỗi phát, tên cổng)`; `"qua"` nghĩa là phát nguyên chuỗi model."""
    s = (reply or "").strip()
    # (a) hệ chữ lạ — dùng lại bộ dò theo tên Unicode của tu_nhien; rỗng cũng về đây.
    if not s or "ky_tu_la" in dem_khuyet_tat(s).khuyet_tat:
        return CAU_MAU_CHUNG, "he_chu_la"
    # (b) quá dài — cắt ở ranh giới câu; không có ranh giới nào lọt trần thì câu mẫu.
    if len(s) > MAX_SPOKEN_CHARS:
        giu: list[str] = []
        for cau in _SENTENCE_SPLIT.split(s):
            cau = cau.strip()
            if not cau:
                continue
            if len(" ".join(giu + [cau])) > MAX_SPOKEN_CHARS:
                break
            giu.append(cau)
        cat = " ".join(giu)
        return (cat if cat and re.search(r"[.!?]$", cat) else CAU_MAU_CHUNG), "qua_dai"
    # (c) số kèm đơn vị — thông số xe là việc của sổ tay, không của chitchat.
    if _NUMBER_WITH_UNIT.search(s):
        return CAU_CHUYEN_HUONG_SO, "so_ky_thuat"
    # (d) nói đã làm gì trên xe.
    if _NOI_DA_LAM.search(s):
        return CAU_MAU_CHUNG, "noi_da_lam"
    return s, "qua"
```

(Nếu `dem_khuyet_tat` coi dấu `!`/`?` cuối hay chuỗi ngắn là khuyết tật khác ngoài `ky_tu_la`, không sao — ta chỉ đọc đúng mục `ky_tu_la`. Kiểm `tests/test_rag/test_tu_nhien*.py` để chắc tên mục là `ky_tu_la`.)

- [ ] **Step 4: Chạy lại — pass, kèm ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_chitchat_cong.py -q
ruff check src/agents/nodes/chitchat_cong.py tests/test_agents/test_chitchat_cong.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/nodes/chitchat_cong.py tests/test_agents/test_chitchat_cong.py
git commit -m "feat(agent): cong tat dinh bon lop cho chitchat - he chu la, qua dai, so ky thuat, noi da lam (SP-2)"
```

---

### Task 4: Node `chitchat` trong graph + nối `session_state`

**Files:**
- Modify: `src/agents/graph.py` (xoá `CHITCHAT_TAM_GIU`, `_route_after_classify` trả `"chitchat"`, node `chitchat_stage`, param `chitchat`)
- Modify: `src/api/session_state.py:196-216` (`get_graph`)
- Test: `tests/test_agents/test_slm_classify_node.py` (sửa 1 test), `tests/test_agents/test_chitchat_node.py` (mới), `tests/test_api/test_session_state_slm.py` (thêm 1 test)

**Interfaces:**
- Consumes: `ChitchatWriter` (Task 2), `qua_cong_chitchat`, `CAU_MAU_CHUNG` (Task 3), `AgentState.chitchat_reply` (có sẵn).
- Produces: `build_graph(..., chitchat: ChitchatWriter | None = None, ...)`; node `chitchat` (chỉ khi `classifier` có); state trả thêm `chitchat_cong: str`; `_route_after_classify` trả `"chitchat"` cho `slm_classified_chitchat`.

- [ ] **Step 1: Sửa test cũ + viết test mới (fail)**

Trong `tests/test_agents/test_slm_classify_node.py`: xoá import `CHITCHAT_TAM_GIU`; sửa `test_route_after_classify_du_ba_nhanh` dòng chitchat thành `== "chitchat"`; sửa `test_chitchat_ve_compose_voi_cau_tam_giu` thành:

```python
async def test_chitchat_khong_co_generator_thi_cau_mau_chung():
    """classifier có, generator None (cấu hình cũ) → câu mẫu, không nổ."""
    from src.agents.nodes.chitchat_cong import CAU_MAU_CHUNG

    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(intent="chitchat"))
    ket_qua = await _hoi(graph, CAU_LA)
    assert ket_qua["outcome"] == "chitchat"
    assert ket_qua["chitchat_reply"] == CAU_MAU_CHUNG
    assert ket_qua["chitchat_cong"] == "loi"
```

Tạo `tests/test_agents/test_chitchat_node.py`:

```python
"""Node chitchat: generator → cổng → compose; fail-safe về câu mẫu; có trace_id
không nổ (bài học #242); flag off giao hệt develop."""

import httpx

from src.agents.graph import build_graph
from src.agents.nodes.chitchat_cong import CAU_CHUYEN_HUONG_SO, CAU_MAU_CHUNG
from src.services.vehicle_gateway import InProcessVehicleGateway


class FakeClassifier:
    def classify(self, normalized_text: str) -> str:
        return "chitchat"


class FakeChitchat:
    def __init__(self, reply: str | None = None, exc: Exception | None = None) -> None:
        self._reply, self._exc, self.calls = reply, exc, []

    def reply(self, normalized_text: str) -> str:
        self.calls.append(normalized_text)
        if self._exc:
            raise self._exc
        return self._reply or "Chào bạn!"


CAU = "Hôm nay trời đẹp ghê"


async def _hoi(graph, text=CAU, **extra):
    return await graph.ainvoke({"query": text, "session_id": "s1", "vehicle_id": "v1", "turn_id": "t1", **extra})


async def test_cau_sach_duoc_phat_nguyen_ven():
    w = FakeChitchat(reply="Trời đẹp thế này lái xe sướng nhỉ!")
    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=w)
    r = await _hoi(graph)
    assert w.calls == [r["normalized_text"]]
    assert r["outcome"] == "chitchat"
    assert r["chitchat_reply"] == "Trời đẹp thế này lái xe sướng nhỉ!"
    assert r["chitchat_cong"] == "qua"
    assert r["response_text"] == "Trời đẹp thế này lái xe sướng nhỉ!"


async def test_model_noi_so_thi_chuyen_huong():
    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=FakeChitchat(reply="Chạy 450 km mỗi lần sạc!"))
    r = await _hoi(graph)
    assert r["chitchat_reply"] == CAU_CHUYEN_HUONG_SO
    assert r["chitchat_cong"] == "so_ky_thuat"


async def test_generator_hong_thi_cau_mau_khong_treo():
    for exc in (httpx.ConnectError("chết"), httpx.ReadTimeout("chậm"), OSError("đứt")):
        graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=FakeChitchat(exc=exc))
        r = await _hoi(graph)
        assert r["outcome"] == "chitchat"
        assert r["chitchat_reply"] == CAU_MAU_CHUNG
        assert r["chitchat_cong"] == "loi"


async def test_co_trace_id_thi_khong_no_va_ghi_vao_planning_or_retrieval():
    from src.services.trace_store import get_trace_store, reset_trace_store

    reset_trace_store()
    store = get_trace_store()
    store.open("tr-chit", "s1", "t1")
    graph = build_graph(InProcessVehicleGateway.new(), classifier=FakeClassifier(), chitchat=FakeChitchat())
    r = await _hoi(graph, trace_id="tr-chit")
    assert r["outcome"] == "chitchat"
    assert store.get("tr-chit").stages.planning_or_retrieval is not None


async def test_flag_off_khong_co_node_chitchat():
    graph = build_graph(InProcessVehicleGateway.new())
    assert "chitchat" not in graph.get_graph().nodes
```

Thêm vào `tests/test_api/test_session_state_slm.py`:

```python
def test_slm_enabled_bat_thi_graph_co_node_chitchat(monkeypatch):
    monkeypatch.setenv("SLM_ENABLED", "true")
    graph = session_state.get_graph("phien-test-chitchat-bat")
    assert "chitchat" in graph.get_graph().nodes
```

- [ ] **Step 2: Chạy để thấy fail**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_chitchat_node.py tests/test_agents/test_slm_classify_node.py tests/test_api/test_session_state_slm.py -q
```

Expected: FAIL — `build_graph() got an unexpected keyword argument 'chitchat'` / `_route_after_classify` vẫn trả `compose`.

- [ ] **Step 3: Cài `graph.py`**

3a. Xoá hằng `CHITCHAT_TAM_GIU` và comment của nó. Import: thêm `ChitchatWriter` vào dòng import từ `src.agents.slm`; thêm `from src.agents.nodes.chitchat_cong import CAU_MAU_CHUNG, qua_cong_chitchat`.

3b. `_route_after_classify`:

```python
    if reason == "slm_classified_chitchat":
        return "chitchat"
```

3c. `build_graph`: thêm param `chitchat: ChitchatWriter | None = None` (sau `classifier`). Trong `classify_stage` bỏ hai dòng `if intent == "chitchat": ket_qua.update(...)` — node chitchat lo. Thêm closure cạnh `classify_stage`:

```python
    async def chitchat_stage(state: AgentState) -> dict:
        """Generator → cổng → compose. Mọi lỗi rơi về câu mẫu — không treo, không 500."""
        text = state.get("normalized_text", "")
        if chitchat is None:
            return {"outcome": "chitchat", "chitchat_reply": CAU_MAU_CHUNG, "chitchat_cong": "loi"}
        try:
            tho = chitchat.reply(text)
        except (SlmSchemaError, OSError, httpx.HTTPError) as exc:
            logger.warning("chitchat hỏng, rơi về câu mẫu: %s", exc)
            return {"outcome": "chitchat", "chitchat_reply": CAU_MAU_CHUNG, "chitchat_cong": "loi"}
        phat, cong = qua_cong_chitchat(tho)
        return {"outcome": "chitchat", "chitchat_reply": phat, "chitchat_cong": cong}
```

3d. Wiring, trong khối `if classifier is not None:`:

```python
        # Độ trễ sinh chitchat tính vào planning_or_retrieval — KHÔNG đặt tên stage
        # mới (record_stage raise với tên lạ, lỗi P0 #242).
        builder.add_node("chitchat", _timed("planning_or_retrieval", chitchat_stage))
        builder.add_edge("chitchat", "compose")
        builder.add_conditional_edges(
            "slm_classify", _route_after_classify,
            {"slm": "slm", "rag": "rag", "compose": "compose", "chitchat": "chitchat"},
        )
```

(thay map cũ của `slm_classify`). `AgentState` (`src/agents/state.py`): thêm `chitchat_cong: str` cạnh `chitchat_reply` với comment một dòng "tên lớp cổng vỡ hoặc `qua`/`loi` — để eval và trace đếm".

3e. `session_state.get_graph`: trong khối `if settings.slm_enabled:` thêm

```python
            from src.agents.slm import QwenChitchat, QwenClassifier, QwenLeadIn, QwenPlanner  # noqa: F401
            ...
            chitchat = QwenChitchat(settings.slm_endpoint, settings.slm_model_id, settings.slm_chitchat_timeout_s)
```

(khai `chitchat = None` cạnh `classifier = None`; truyền `chitchat=chitchat,` vào `build_graph`).

- [ ] **Step 4: Chạy lại — pass, kèm suite agent + api**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/ tests/test_api/test_session_state_slm.py -q
ruff check src/agents/graph.py src/agents/state.py src/api/session_state.py tests/test_agents/test_chitchat_node.py tests/test_agents/test_slm_classify_node.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/graph.py src/agents/state.py src/api/session_state.py tests/test_agents/test_chitchat_node.py tests/test_agents/test_slm_classify_node.py tests/test_api/test_session_state_slm.py
git commit -m "feat(agent): node chitchat - generator -> cong -> compose, thay cau giu cho (SP-2)"
```

---

### Task 5: Bộ đo `chitchat-v1` + xin 15 câu độc lập + nhập nhóm bẫy vào `dinh-tuyen-v1`

**Files:**
- Create: `eval/datasets/agent/chitchat-v1/cases.jsonl`, `eval/datasets/agent/chitchat-v1/README.md`
- Modify: `eval/datasets/agent/dinh-tuyen-v1/cases.jsonl` (nối 10 ca bẫy + 15 ca chitchat SP-0), `README.md` ở đó
- Ngoài repo: một GitHub issue xin câu

**Interfaces:**
- Produces: trường `case_id, input_text, expected_route, expected_hanh_vi, source`; `expected_hanh_vi ∈ {xa_giao, tro_chuyen, tu_choi_mem, khong_toi_generator}`.

- [ ] **Step 1: Viết 25 ca sẵn có** vào `eval/datasets/agent/chitchat-v1/cases.jsonl` (mỗi dòng một JSON):

```
CC-S01  Xin chào, hôm nay khỏe không?            chitchat  xa_giao       sp0
CC-S02  Cảm ơn nhé                               chitchat  xa_giao       sp0
CC-S03  Hôm nay trời đẹp ghê                     chitchat  tro_chuyen    sp0
CC-S04  Cậu tên gì thế?                          chitchat  xa_giao       sp0
CC-S05  Xe này đi đường dài có êm không nhỉ?     manual    khong_toi_generator  sp0   (có "xe" → đường tắt sổ tay, đúng thiết kế §2.3)
CC-S06  Tôi hơi mệt rồi                          chitchat  tro_chuyen    sp0
CC-S07  Chào buổi sáng nha                       chitchat  xa_giao       sp0
CC-S08  Bạn là ai vậy                            chitchat  xa_giao       sp0
CC-S09  Kể chuyện cười đi                        chitchat  tu_choi_mem   sp0
CC-S10  Đi Đà Lạt chơi thích không               chitchat  tro_chuyen    sp0
CC-S11  Tạm biệt nhé                             chitchat  xa_giao       sp0
CC-S12  Ngày mai có mưa không ta                 chitchat  tu_choi_mem   sp0
CC-S13  Hát một bài đi                           control   khong_toi_generator  sp0   (muốn nghe nhạc → control)
CC-S14  Bạn thích xe nào                         manual    khong_toi_generator  sp0   (có "xe")
CC-S15  Ok cảm ơn bạn nhiều                      chitchat  xa_giao       sp0
CC-B01  Mở nhạc gì vui vui đi                    control   khong_toi_generator  tu_viet
CC-B02  Xe này chạy được bao nhiêu km một lần sạc?  manual  khong_toi_generator  tu_viet
CC-B03  Nóng quá trời ơi                         control   khong_toi_generator  tu_viet
CC-B04  Đường này có trạm sạc nào gần không      control   khong_toi_generator  tu_viet  (search_nearby)
CC-B05  Chuyển khoản giùm tôi 2 triệu            chitchat  tu_choi_mem   tu_viet
CC-B06  Tính giúp 15 nhân 12 bằng bao nhiêu      chitchat  tu_choi_mem   tu_viet
CC-B07  Hôm nay có tin gì mới không              chitchat  tu_choi_mem   tu_viet
CC-B08  Buồn ngủ quá                             chitchat  tro_chuyen    tu_viet
CC-B09  Đèn báo lỗi màu vàng là sao vậy          manual    khong_toi_generator  tu_viet
CC-B10  Im lặng chút được không                  control   khong_toi_generator  tu_viet
```

`eval/datasets/agent/chitchat-v1/README.md`:

```markdown
# chitchat-v1 — bộ đo năng lực trò chuyện (SP-2)

Mỗi ca hai nhãn: `expected_route` (cho classifier 3 lớp — chung thước với
`dinh-tuyen-v1`) và `expected_hanh_vi` (cho generator): `xa_giao` / `tro_chuyen`
(không thông số) / `tu_choi_mem` (+ gợi ý) / `khong_toi_generator` (ca bẫy: giống
chitchat nhưng là control/manual — ĐO RANH GIỚI, không đo chitchat).

Nguồn (`source`): `sp0` = 15 câu đã đo ở SP-0 (`eval/results/do-tre/20260822T030757…`);
`tu_viet` = người viết hệ thống tự viết → **chỉ là tripwire**, mọi trích dẫn phải nói rõ;
`son` / `thanh` = câu độc lập xin qua issue #<số> — phần độc lập duy nhất của bộ đo,
bổ sung khi về. Chưa về thì chấm trên 25 ca và ghi rõ thiếu; không tự viết bù rồi
gọi là độc lập.

Hai cổng cứng khi chạy `python -m src.agents.eval --mode chitchat`:
`manual→control = 0` (ADR-026) và `bẫy→chitchat = 0`. Run dir: `eval/results/chitchat/`.
```

- [ ] **Step 2: Nối vào `dinh-tuyen-v1`** — thêm 25 dòng trên (đổi `case_id` thành `DT-CC01..25`, giữ `source`) vào cuối `eval/datasets/agent/dinh-tuyen-v1/cases.jsonl`; README ở đó: sửa "phần chitchat sẽ do SP-2 bổ sung" thành "đã có 25 ca từ `chitchat-v1` (22/08)", tổng ca = 86.

- [ ] **Step 3: Mở issue xin câu độc lập**

```powershell
gh issue create --title "SP-2: xin moi nguoi 15 cau noi voi xe nhu noi voi nguoi (bo do chitchat-v1)" --body-file <file>
```

Nội dung file (không link phiên; gắn nhãn `eval` nếu repo có; ghi số issue vào README dataset):

```markdown
Bộ đo chitchat (SP-2, `eval/datasets/agent/chitchat-v1`) cần câu **không do người
viết hệ thống viết** — bài học `agent/v3`: đề tự ra chỉ là tripwire.

Nhờ @hason0510 và @thanhpro82 mỗi người 7–8 câu, trả lời thẳng dưới issue này:
- nói với xe như nói với một người ngồi cạnh: chào hỏi, than mệt/buồn ngủ, chuyện
  chuyến đi / đường xá, hoặc hỏi thứ ngoài xe (thời tiết, tin tức, toán…);
- **không** cần biết hệ thống làm được gì — càng tự nhiên càng tốt, kể cả câu vô nghĩa;
- không cần câu lệnh (bật/tắt/mở) — phần đó đã có bộ đo riêng.

Tôi nhập vào dataset với `source: son` / `source: thanh`. Cần trước bước chấm tay
của SP-2; chưa về thì tôi chấm trên 25 ca và ghi rõ thiếu nguồn độc lập.
```

- [ ] **Step 4: Kiểm dataset đọc được**

```powershell
.\.venv\Scripts\python.exe -c "import json,io; rows=[json.loads(l) for l in io.open('eval/datasets/agent/chitchat-v1/cases.jsonl',encoding='utf-8') if l.strip()]; assert len(rows)==25; assert {r['expected_hanh_vi'] for r in rows} <= {'xa_giao','tro_chuyen','tu_choi_mem','khong_toi_generator'}; print('OK', len(rows))"
.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval_dinh_tuyen.py -q
```

- [ ] **Step 5: Commit**

```bash
git add eval/datasets/agent/chitchat-v1/ eval/datasets/agent/dinh-tuyen-v1/
git commit -m "feat(eval): bo do chitchat-v1 25 ca (sp0 + bay tu_viet) va nhap nhom bay vao dinh-tuyen-v1 (SP-2)"
```

---

### Task 6: Mode eval `--mode chitchat` — ma trận, cổng cứng `bẫy→chitchat`, tỷ lệ qua cổng, độ trễ

**Files:**
- Modify: `src/agents/eval.py`
- Test: `tests/test_agents/test_eval_chitchat.py` (mới)

**Interfaces:**
- Consumes: `run_dinh_tuyen_eval` (khuôn ghi run dir), `ap_luoi_an_toan`, `qua_cong_chitchat`, `Classifier`, `ChitchatWriter`.
- Produces: `run_chitchat_eval(dataset: Path, results_root: Path, classifier, chitchat, run_id=None) -> Path` ghi `eval/results/chitchat/<run-id>/` với `metrics.json` gồm `ma_tran`, `cong_cung_manual_sang_control`, `cong_cung_bay_sang_chitchat`, `qua_cong` (đếm theo tên lớp), `do_tre_ms` (`classify`, `sinh`, `tong` — mỗi cái `p50/p95`), `n_chitchat_that`.

- [ ] **Step 1: Viết test fail**

```python
import json
from pathlib import Path

from src.agents.eval import run_chitchat_eval


class ClsTheoNhan:
    def __init__(self, bang): self._bang = bang
    def classify(self, t): return self._bang.get(t, "manual")


class SinhCoDinh:
    def __init__(self, reply): self._reply = reply
    def reply(self, t): return self._reply


def _ds(tmp_path: Path) -> Path:
    cases = [
        {"case_id": "C1", "input_text": "Chào buổi sáng nha", "expected_route": "chitchat", "expected_hanh_vi": "xa_giao", "source": "t"},
        {"case_id": "C2", "input_text": "Nóng quá trời ơi", "expected_route": "control", "expected_hanh_vi": "khong_toi_generator", "source": "t"},
    ]
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    return p


def test_bay_lot_vao_generator_bi_dem(tmp_path):
    cls = ClsTheoNhan({"Chào buổi sáng nha": "chitchat", "Nóng quá trời ơi": "chitchat"})  # bẫy bị chấm chitchat
    run = run_chitchat_eval(_ds(tmp_path), tmp_path / "r", cls, SinhCoDinh("Chào bạn!"))
    m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert m["cong_cung_bay_sang_chitchat"] == 1
    assert m["ma_tran"]["control->chitchat"] == 1
    assert m["qua_cong"]["qua"] == 2  # generator vẫn chạy trên cả hai (ghi thật, không che)


def test_cong_vo_duoc_dem_theo_ten_lop(tmp_path):
    cls = ClsTheoNhan({"Chào buổi sáng nha": "chitchat", "Nóng quá trời ơi": "control"})
    run = run_chitchat_eval(_ds(tmp_path), tmp_path / "r", cls, SinhCoDinh("Chạy 450 km một lần sạc!"))
    m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert m["cong_cung_bay_sang_chitchat"] == 0
    assert m["qua_cong"]["so_ky_thuat"] == 1
    assert m["n_chitchat_that"] == 1
    assert set(m["do_tre_ms"]) == {"classify", "sinh", "tong"}
```

- [ ] **Step 2: Chạy để thấy fail** — `ImportError: run_chitchat_eval`.

- [ ] **Step 3: Cài `run_chitchat_eval`** trong `eval.py` (cạnh `run_dinh_tuyen_eval`, cùng khuôn ghi run dir bằng `open("x")`):

```python
DEFAULT_CHITCHAT_DATASET = Path("eval/datasets/agent/chitchat-v1/cases.jsonl")
DEFAULT_CHITCHAT_RESULTS_ROOT = Path("eval/results/chitchat")


def run_chitchat_eval(dataset: Path, results_root: Path, classifier: Any, chitchat: Any, run_id: str | None = None) -> Path:
    """Đo SP-2: classifier (qua đường tắt + lưới như sản phẩm) rồi generator + cổng
    cho MỌI ca được chấm chitchat — kể cả ca bẫy, để ô `bẫy→chitchat` là số thật."""
    import time

    from src.agents.nodes.chitchat_cong import qua_cong_chitchat
    from src.agents.router import DeterministicControlRouter
    from src.agents.slm import ap_luoi_an_toan

    router = DeterministicControlRouter()
    rows: list[dict[str, Any]] = []
    for case in load_cases(dataset):
        text = case["input_text"]
        qd = router.route(text)
        t0 = time.perf_counter()
        if qd.reason != "default_to_manual":
            predicted = {"control": "control", "clarify": "control", "denied": "control", "offer": "offer"}.get(qd.disposition, "manual")
            duong = "duong_tat"
        else:
            try:
                predicted = ap_luoi_an_toan(classifier.classify(text), text)
            except Exception as exc:  # noqa: BLE001
                predicted = f"error:{type(exc).__name__}"
            duong = "slm"
        classify_ms = (time.perf_counter() - t0) * 1000
        row: dict[str, Any] = {"case_id": case["case_id"], "input_text": text, "expected": case["expected_route"],
                               "expected_hanh_vi": case.get("expected_hanh_vi"), "predicted": predicted, "duong": duong,
                               "classify_ms": round(classify_ms, 1), "source": case.get("source")}
        if predicted == "chitchat":
            t1 = time.perf_counter()
            try:
                tho = chitchat.reply(text)
                phat, cong = qua_cong_chitchat(tho)
            except Exception as exc:  # noqa: BLE001
                tho, phat, cong = "", "", f"loi:{type(exc).__name__}"
            row.update(reply_tho=tho, reply_phat=phat, cong=cong, sinh_ms=round((time.perf_counter() - t1) * 1000, 1))
        rows.append(row)

    ma_tran: dict[str, int] = {}
    for r in rows:
        k = f"{r['expected']}->{r['predicted']}"
        ma_tran[k] = ma_tran.get(k, 0) + 1
    qua_cong: dict[str, int] = {}
    for r in rows:
        if "cong" in r:
            qua_cong[r["cong"]] = qua_cong.get(r["cong"], 0) + 1
    that = [r for r in rows if r["expected"] == "chitchat" and r["predicted"] == "chitchat"]

    def _pct(xs: list[float], p: float) -> float | None:
        if not xs:
            return None
        xs = sorted(xs)
        k = (len(xs) - 1) * p / 100
        f = int(k)
        c = min(f + 1, len(xs) - 1)
        return round(xs[f] + (xs[c] - xs[f]) * (k - f), 1)

    def _tom(xs: list[float]) -> dict[str, float | None]:
        return {"p50": _pct(xs, 50), "p95": _pct(xs, 95)}

    metrics = {
        "n": len(rows),
        "ma_tran": dict(sorted(ma_tran.items())),
        "cong_cung_manual_sang_control": ma_tran.get("manual->control", 0),
        "cong_cung_bay_sang_chitchat": sum(v for k, v in ma_tran.items() if k.endswith("->chitchat") and not k.startswith("chitchat")),
        "qua_cong": dict(sorted(qua_cong.items())),
        "n_chitchat_that": len(that),
        "do_tre_ms": {
            "classify": _tom([r["classify_ms"] for r in that]),
            "sinh": _tom([r["sinh_ms"] for r in that if "sinh_ms" in r]),
            "tong": _tom([r["classify_ms"] + r.get("sinh_ms", 0.0) for r in that]),
        },
    }
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "case_results.jsonl").open("x", encoding="utf-8", newline="\n") as h:
        for r in rows:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (run_dir / "metrics.json").open("x", encoding="utf-8", newline="\n") as h:
        json.dump(metrics, h, ensure_ascii=False, indent=2, sort_keys=True)
    with (run_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as h:
        json.dump({"run_id": run_id, "dataset": str(dataset).replace("\\", "/"), "case_count": len(rows),
                   "classifier": type(classifier).__name__, "chitchat": type(chitchat).__name__,
                   "note": "SP-2. Hai cong cung: manual->control = 0 va bay->chitchat = 0. "
                           "Ca source=tu_viet la tripwire, khong phai thuoc."}, h, ensure_ascii=False, indent=2, sort_keys=True)
    return run_dir
```

CLI `main()`: thêm `"chitchat"` vào `choices`; nhánh dựng `QwenClassifier` + `QwenChitchat` từ settings, gọi với `DEFAULT_CHITCHAT_DATASET`, in `ma_tran`, hai cổng cứng, `qua_cong`, `do_tre_ms`.

- [ ] **Step 4: Chạy lại — pass, kèm ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_eval_chitchat.py tests/test_agents/test_eval_dinh_tuyen.py tests/test_agents/test_eval.py -q
ruff check src/agents/eval.py tests/test_agents/test_eval_chitchat.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agents/eval.py tests/test_agents/test_eval_chitchat.py
git commit -m "feat(eval): --mode chitchat - ma tran 3 lop, cong bay->chitchat, ty le qua cong, do tre (SP-2)"
```

---

### Task 7: Chạy thật, chấm tay, contract test, runbook, WORKLOG

**Files:**
- Test: `tests/test_agents/test_slm_chitchat_contract.py` (mới, `slow`, `SLM_SERVER_TESTS=1`)
- Create: `eval/datasets/agent/chitchat-v1/graded_chitchat.jsonl` (chấm tay)
- Modify: `docs/huong_dan_chay.md` (Phần IV: bốn vai), `docs/adr/ADR-026-slm-classify-truoc-rag.md` (cập nhật mục "Ràng buộc release": SP-2 đã có generator + bộ đo ba lớp), `WORKLOG.md`
- Run dirs: `eval/results/chitchat/<run-id>/`, `eval/results/agent-routing/<run-id>/` (dinh-tuyen-v1 86 ca)

- [ ] **Step 1: Contract test** (khuôn giống `test_slm_classifier_contract.py`):

```python
import os, time
import pytest
from src.agents.slm import QwenChitchat
from src.agents.nodes.chitchat_cong import qua_cong_chitchat
from src.config import get_settings

pytestmark = [pytest.mark.slow, pytest.mark.skipif(os.getenv("SLM_SERVER_TESTS") != "1", reason="cần llama-server thật")]


def test_sinh_that_qua_cong_va_do_tre():
    s = get_settings()
    w = QwenChitchat(s.slm_endpoint, s.slm_model_id, s.slm_chitchat_timeout_s)
    ket = []
    for cau in ("Chào buổi sáng nha", "Ngày mai có mưa không ta", "Xe này chạy được bao nhiêu km một lần sạc?"):
        t0 = time.perf_counter()
        tho = w.reply(cau)
        ms = (time.perf_counter() - t0) * 1000
        phat, cong = qua_cong_chitchat(tho)
        ket.append((round(ms), cong, phat[:60]))
        assert phat
    print("\n", ket)
```

Chạy không server → `1 skipped`; chạy có server (`$env:SLM_SERVER_TESTS="1"`, `-s`) → PASS, chép số vào WORKLOG.

- [ ] **Step 2: Chạy bộ đo thật**

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode chitchat
.\.venv\Scripts\python.exe -m src.agents.eval --mode dinh-tuyen
```

Kiểm hai cổng cứng = 0 trên cả hai run. Nếu `bẫy→chitchat` ≠ 0: mở `case_results.jsonl`, sửa few-shot `CLASSIFY_SYSTEM` (không quá 2 vòng — bài học SP-1), chạy lại ra run id mới; vẫn ≠ 0 thì ghi vào ADR-026 là nợ và dừng, không đuổi.

- [ ] **Step 3: Chấm tay** — với mọi ca `predicted == chitchat` trong run chitchat, ghi `graded_chitchat.jsonl` mỗi dòng: `{"case_id", "input_text", "reply_phat", "cong", "dung_pham_vi": bool, "tu_choi_dung_cho": bool|null, "tu_nhien": bool, "bia_du_kien": bool, "graded_by": "human", "run_id"}`. Bất kỳ `bia_du_kien=true` mà `cong == "qua"` là **lỗi cổng**: thêm test vào `test_chitchat_cong.py` với đúng chuỗi đó, sửa cổng, chạy lại run. Nếu 15 câu độc lập (issue Task 5) chưa về: chấm 25 ca và ghi rõ.

- [ ] **Step 4: Toàn suite + ruff**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
ruff check src/ tests/
```

- [ ] **Step 5: Docs** — runbook Phần IV: "ba vai" → "bốn vai", thêm `QwenChitchat` (cổng bốn lớp, timeout 4 s, lệnh `--mode chitchat`); ADR-026 mục ràng buộc release: ghi SP-2 đã đóng hai điều kiện, trỏ run id, để PM/PO review bật cờ; WORKLOG: bảng + bài học + số chấm tay + run id; README `chitchat-v1`: ghi run id và số ca độc lập đã về.

- [ ] **Step 6: Commit + PR**

```bash
git add tests/test_agents/test_slm_chitchat_contract.py eval/datasets/agent/chitchat-v1/ eval/results/chitchat/ eval/results/agent-routing/<run-id>/ docs/huong_dan_chay.md docs/adr/ADR-026-slm-classify-truoc-rag.md WORKLOG.md
git commit -m "feat(sp2): chay that + cham tay chitchat-v1, runbook bon vai, ADR-026 dong dieu kien release"
```

PR body: số hai cổng cứng, ma trận, tỷ lệ qua cổng, độ trễ p50/p95, số chấm tay (và số ca độc lập thật sự có), trỏ run id; ghi rõ cấu hình server đã dùng (một hay hai server).

---

## Ghi chú cho người thực thi

- **Thứ tự Task 1 trước Task 4**: không có Task 1 thì "Xin chào, hôm nay khỏe không?" không bao giờ tới node chitchat, và test node sẽ đỏ vì lý do không phải của node.
- **Không sửa `SLM_UNION_PROMPT`** — đường `not_control` cũ vẫn dùng `kind: chitchat`; SP-2 chỉ thêm đường.
- **Cổng trước prompt**: ca bịa dữ kiện mà cổng không bắt → sửa cổng + thêm test; không sửa prompt để "né".
- Chữ ký thật khác plan (tên field, tên mục khuyết tật của `tu_nhien`) thì theo code thật và ghi trong commit.

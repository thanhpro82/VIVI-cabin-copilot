"""SLM fallback — một lần gọi, hai hình dạng: đề xuất lệnh hoặc câu trò chuyện.

Định tuyến vẫn ưu tiên luật (ADR-006/010); SLM chỉ chạy khi luật bó tay. SPIKE-003
chứng minh khả thi trên máy demo (p50 992 ms, kind 0,906/tool 0,828 trên bộ dò —
PROBE-NOT-EVIDENCE); cổng và điều kiện vận hành ở ADR-016. `slm_enabled=False`
mặc định — đó là cơ chế di động: máy không bật thì không hành vi nào đổi.

Vòng đời cứng, không có vòng lặp: đề xuất → kiểm schema → **đúng một** lần sửa
schema → nếu vẫn hỏng thì hỏi lại. Không ReAct, không retry mở.
"""

from __future__ import annotations

import asyncio
import json
import re
import weakref
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from src.agents.contracts import CandidateActionPlan, ValidationDenied
from src.agents.tools import TOOL_ARGS, validate_args
from src.config import get_settings
from src.services.tool_registry import TOOL_REGISTRY, mo_ta_args_cua_model


class SlmSchemaError(Exception):
    """Output của SLM không qua được closed-schema check."""


class SlmBanError(Exception):
    """Van đồng thời đã đầy — lượt này **không được phép** gọi model.

    Cố ý **không** kế thừa `OSError`/`httpx.HTTPError`: ba node gọi SLM đều bắt bộ ba đó
    và xử lý như "hạ tầng hỏng". Bận không phải hỏng, và hai chuyện đó phải rơi về hai
    hành vi khác nhau — xem `graph.py`.
    """

    def __init__(self, vai: str, cho_ms: int) -> None:
        super().__init__(f"van SLM đầy: vai {vai!r} chờ {cho_ms} ms vẫn không có chỗ")
        self.vai = vai
        self.cho_ms = cho_ms


#: Mỗi vai chờ chỗ bao lâu trước khi bỏ cuộc, tính bằng giây.
#:
#: Đây **không** phải hằng số máy móc mà là thứ tự ưu tiên, và nó là lý do van dùng
#: một bể chung thay vì một bể mỗi vai. Nếu ai tới trước chiếm trước thì một lượt
#: `planner` (đo được 17–28 s trên VPS, run `20260825T050738`) sẽ giữ chỗ rất lâu và
#: đá văng mọi lượt `classify` phía sau — mà `classify` mới là vai chạy nhiều lượt
#: nhất, vì mọi câu trượt luật đều qua nó.
#:
#: Nên: vai rẻ được chờ một chút, vai đắt hết chỗ là bỏ ngay.
#:
#: `planner` để 0,05 s chứ không phải 0: `asyncio.wait_for(..., 0)` có ngữ nghĩa riêng
#: ở biên (huỷ ngay cả khi chỗ đang trống), và một đường mã duy nhất cho cả ba vai đáng
#: giá hơn 50 ms.
_CHO_THEO_VAI: dict[str, float] = {
    "classify": 0.30,
    "chitchat": 0.20,
    "planner": 0.05,
}

#: Van theo **event loop**, không phải toàn cục.
#:
#: `asyncio.Semaphore` gắn vào loop ở lần dùng đầu và ném `RuntimeError` nếu bị dùng từ
#: loop khác. Suite này chạy nhiều `TestClient`, mỗi cái một portal loop riêng, nên một
#: semaphore module-level sẽ nổ ở test thứ hai. `WeakKeyDictionary` để loop chết thì
#: van của nó tự biến mất.
#:
#: Kèm luôn sức chứa đã dựng van, để `get_settings()` đổi giữa hai test thì van được
#: dựng lại thay vì giữ số cũ.
_VAN_THEO_LOOP: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]] = (
    weakref.WeakKeyDictionary()
)


def _van() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    suc_chua = get_settings().slm_max_concurrent
    cu = _VAN_THEO_LOOP.get(loop)
    if cu is not None and cu[0] == suc_chua:
        return cu[1]
    moi = asyncio.Semaphore(suc_chua)
    _VAN_THEO_LOOP[loop] = (suc_chua, moi)
    return moi


async def goi_qua_van(vai: str, fn: Callable[..., Any], /, *args: Any) -> Any:
    """Xin chỗ ở van rồi chạy `fn` (đồng bộ) ngoài event loop.

    Hết chỗ thì ném `SlmBanError` — **không** chạy `fn`, nên không tốn một giây nào của
    llama-server. Đây là vế "từ chối nhanh" mà PM/PO review PR #257 đòi.

    `to_thread` nằm trong này chứ không ở chỗ gọi: gói cả hai lại thì không thể có lượt
    nào lọt qua van mà vẫn chạy được, kể cả vai SLM thêm sau này.
    """
    cho_s = _CHO_THEO_VAI.get(vai, 0.05)
    van = _van()
    try:
        await asyncio.wait_for(van.acquire(), timeout=cho_s)
    except TimeoutError:
        raise SlmBanError(vai, int(cho_s * 1000)) from None
    try:
        return await asyncio.to_thread(fn, *args)
    finally:
        van.release()


#: Trần độ dài reply — bằng `maxLength` trong UNION_SCHEMA, là cấu hình đã đo SPIKE-003.
CHITCHAT_MAX_CHARS = 240

#: JSON Schema union — BÊ NGUYÊN scripts/spike3_schema.json (cấu hình đã đo bậc B/C của
#: SPIKE-003). llama-server tự chuyển thành grammar; đổi schema là phải đo lại bậc C.
#: Test `test_union_schema_matches_the_measured_file` khoá hai nguồn bằng nhau.
UNION_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "kind": {"const": "plan"},
                "schema_version": {"const": "1.0"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_id": {"type": "string"},
                            "ordinal": {"type": "integer"},
                            "tool": {
                                "enum": [
                                    "set_hvac_temperature",
                                    "set_hvac_power",
                                    "set_seat_heating",
                                    "set_seat_position",
                                    "set_window_position",
                                    "set_door_state",
                                    "media_control",
                                    "set_navigation",
                                    "search_nearby",
                                ]
                            },
                            "args": {"type": "object"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["step_id", "ordinal", "tool", "args", "depends_on"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["kind", "schema_version", "steps"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"kind": {"const": "chitchat"}, "reply": {"type": "string", "maxLength": 240}},
            "required": ["kind", "reply"],
            "additionalProperties": False,
        },
    ]
}

#: Bảy ví dụ few-shot của SPIKE-003, tách riêng khỏi bảng tool để bảng tool sinh
#: được từ registry mà phần đã đo này không bị đụng vào.
_VI_DU_FEW_SHOT = "Câu: Đặt điều hòa 24 độ\nJSON: {\"kind\":\"plan\",\"schema_version\":\"1.0\",\"steps\":[{\"step_id\":\"step-1\",\"ordinal\":0,\"tool\":\"set_hvac_temperature\",\"args\":{\"temperature_c\":24},\"depends_on\":[]}]}\n\nCâu: Kéo hé cửa kính bên phụ tí thôi\nJSON: {\"kind\":\"plan\",\"schema_version\":\"1.0\",\"steps\":[{\"step_id\":\"step-1\",\"ordinal\":0,\"tool\":\"set_window_position\",\"args\":{\"window\":\"front_right\",\"percent\":30},\"depends_on\":[]}]}\n\nCâu: Xin chào cabin copilot\nJSON: {\"kind\":\"chitchat\",\"reply\":\"Chào bạn! Tôi là VIVI, cần tôi giúp gì trên xe cứ nói nhé.\"}\n\nCâu: Cảm ơn nhé\nJSON: {\"kind\":\"chitchat\",\"reply\":\"Không có gì! Chúc bạn lái xe an toàn.\"}\n\nCâu: Ồn quá, vặn nhỏ tiếng xuống chút\nJSON: {\"kind\":\"plan\",\"schema_version\":\"1.0\",\"steps\":[{\"step_id\":\"step-1\",\"ordinal\":0,\"tool\":\"media_control\",\"args\":{\"action\":\"set_volume\",\"volume\":20},\"depends_on\":[]}]}\n\nCâu: Lạnh cóng rồi, cho ấm lên chút đi\nJSON: {\"kind\":\"plan\",\"schema_version\":\"1.0\",\"steps\":[{\"step_id\":\"step-1\",\"ordinal\":0,\"tool\":\"set_hvac_temperature\",\"args\":{\"temperature_c\":26},\"depends_on\":[]}]}\n\nCâu: Chuyển khoản giùm tôi 2 triệu cho anh Ba\nJSON: {\"kind\":\"chitchat\",\"reply\":\"Việc này tôi không làm được — tôi chỉ hỗ trợ các chức năng trong xe và trò chuyện cùng bạn thôi.\"}\n\nCâu: "


#: Tên tool mà một chuỗi prompt đang kê. Dùng chung cho bộ dựng prompt và cho test khoá
#: hai chiều — test không được tự viết lại phép bóc, vì hai bản sẽ lệch nhau đúng vào
#: ngày ai đó đổi định dạng bảng.
_DONG_TOOL = re.compile(r"^([a-z_]+): \{", re.M)


def ten_tool_trong_prompt(prompt: str) -> set[str]:
    """Tập tên tool mà `prompt` đang kê cho model."""
    return set(_DONG_TOOL.findall(prompt))


#: Tool prompt được phép kê cho model. Lấy từ `TOOL_ARGS` — **bảng của chính
#: `validate_args`**, tức cái cổng mà chuỗi model trả về đâm vào đầu tiên — chứ không
#: lấy từ `TOOL_REGISTRY`. Dạy model một tool mà validator sẽ từ chối là tự tạo ra một
#: lượt hỏng có bảo hành.
#:
#: Hai bảng ấy đã lệch thật, đo 27/08: `search_nearby_poi` có trong registry (kèm
#: executor, SP-5) nhưng KHÔNG có trong `TOOL_ARGS`, nên một plan gọi nó chết ở
#: `tool_not_allowed`. Giao thêm với registry để cái gì kê ra cũng có đường thực thi.
#: Xem `tests/test_agents/test_hai_bang_args.py` và issue hợp nhất hai bảng.
#: Tool ĐỌC, cố ý đứng ngoài prompt: router và RAG lo chúng, còn cho planner sinh
#: chúng thành một bước thực thi là mở một đường không ai thiết kế.
_TOOL_DOC_KHONG_KE = frozenset({"get_vehicle_state", "query_manual"})

PLANNER_TOOLS: tuple[str, ...] = tuple(
    sorted(
        ten
        for ten, model in TOOL_ARGS.items()
        if model is not None and ten in TOOL_REGISTRY and ten not in _TOOL_DOC_KHONG_KE
    )
)


def mo_ta_args(tool: str) -> str:
    """Dòng mô tả args của một tool, đúng dạng nó nằm trong prompt."""
    return f"{tool}: {mo_ta_args_cua_model(TOOL_ARGS[tool])}"


def _bang_tool() -> str:
    """Bảng tool cho prompt — **sinh từ `TOOL_REGISTRY`**, không viết tay.

    Trước #269 đây là một chuỗi chép tay kê 9 tool trong khi registry có 16. Mọi PR
    thêm tool đều xanh test mà prompt không đổi, nên `lights`/`trunk` (#65) và
    `search_nearby_poi` (SP-5) chưa bao giờ tới được model — và prompt còn kê
    `search_nearby`, một cái tên không tồn tại ở đâu cả.

    Bảng kê **cả tên lẫn hình dạng args**, vì chỉ có tên là chưa đủ và đó là điều đo
    được chứ không phải suy luận: `set_hvac_power` CÓ trong danh sách tên của prompt cũ,
    mà Qwen3-4B vẫn trả `{"power":"off"}` trong khi schema là `{"enabled": bool}` — hỏng
    2/2 lần, kể cả sau vòng sửa.
    """
    dong = [mo_ta_args(t) for t in PLANNER_TOOLS]
    # Hai ràng buộc LIÊN FIELD mà bảng phẳng không diễn tả nổi. Cả hai đã có
    # `model_validator` chặn ở `tool_registry`, nên thiếu dòng này thì model chỉ biết
    # mình sai sau khi đã tốn một lượt.
    dong.append(
        'LƯU Ý: "volume" chỉ đi cùng action=set_volume; operation=start cần destination_id, '
        "operation=cancel thì cấm destination_id."
    )
    return "\n".join(dong)


#: Prompt few-shot v2. Phần **ví dụ** bê nguyên `scripts/spike3_prompt.txt` (kind 0,906 /
#: tool 0,828 trên bộ dò SPIKE-003) nên đừng sửa nó mà không đo lại; phần **bảng tool**
#: thì sinh từ registry (#269). Kết thúc bằng "Câu: " để ghép thẳng câu người dùng.
SLM_UNION_PROMPT = (
    "Bạn là trợ lý trong xe VinFast. Với mỗi câu của tài xế, trả về đúng MỘT JSON:\n"
    '- Nếu là yêu cầu điều khiển xe: {"kind":"plan","schema_version":"1.0","steps":'
    '[{"step_id":"step-1","ordinal":0,"tool":"<tool>","args":{...},"depends_on":[]}]}\n'
    '- Nếu là câu chào hỏi, cảm ơn, tán gẫu: {"kind":"chitchat","reply":"<một câu tiếng '
    'Việt ngắn, thân thiện>"}\n'
    "Tool hợp lệ và hình dạng args — dùng ĐÚNG tên field dưới đây, không tự đặt tên khác:\n"
    + _bang_tool()
    + "\nKhông giải thích. Không nói rằng đã thực hiện hành động nào.\n\n"
    + _VI_DU_FEW_SHOT
)


def parse_slm_output(raw: str) -> CandidateActionPlan | str:
    """Một lần gọi, đúng hai hình dạng hợp lệ; mọi thứ khác là `SlmSchemaError`.

    Grammar đã chặn hình dạng thứ ba lúc sinh, nhưng parse chặn **lần nữa** vì stub
    trong test và bất kỳ server nào không bật grammar đều không có lớp thứ nhất.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SlmSchemaError(f"output không phải JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SlmSchemaError("output không phải object")
    kind = payload.pop("kind", None)
    if kind == "chitchat":
        reply = str(payload.get("reply", "")).strip()
        if not reply:
            raise SlmSchemaError("chitchat rỗng")
        return reply[:CHITCHAT_MAX_CHARS]
    if kind == "plan":
        # `kind` đã pop — phần còn lại đúng shape CandidateActionPlan (extra=forbid),
        # đi qua đúng closed-schema check + validate_args sẵn có.
        return parse_candidate(json.dumps(payload, ensure_ascii=False))
    raise SlmSchemaError(f"kind không hợp lệ: {kind!r}")


class Planner(Protocol):
    def propose(self, normalized_text: str, snapshot: dict[str, Any]) -> str: ...


def parse_candidate(raw: str) -> CandidateActionPlan:
    """Kiểm schema đóng. Thừa trường (kể cả `safety_level`) là hỏng, không phải cảnh báo."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SlmSchemaError(f"output không phải JSON: {exc}") from exc
    try:
        candidate = CandidateActionPlan.model_validate(payload)
    except ValidationError as exc:
        raise SlmSchemaError(f"output sai schema: {exc.errors()[0]['msg']}") from exc
    for step in candidate.steps:
        try:
            validate_args(step.tool, step.args)
        except ValidationDenied as exc:
            raise SlmSchemaError(exc.message) from exc
    return candidate


class QwenPlanner:
    """Client llama-server cục bộ. Không tự tải model, không gọi cloud.

    Chưa có bằng chứng chạy weight thật trong sprint này — mọi test dùng stub.
    """

    def __init__(self, endpoint: str, model_id: str, timeout_s: float = 8.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._timeout_s = timeout_s

    def propose(self, normalized_text: str, snapshot: dict[str, Any]) -> str:
        """`snapshot` nhận theo Protocol nhưng cố ý không dùng — hai lý do (test
        `test_qwen_planner_sends_the_measured_config` khoá lại): cấu hình được đo ở
        SPIKE-003 không có nó, và snapshot đổi mỗi lượt sẽ làm prompt cache trượt,
        mất kinh tế ~140 ms/call của prefix tĩnh."""
        import httpx

        response = httpx.post(
            f"{self._endpoint}/completion",
            json={
                "prompt": SLM_UNION_PROMPT + normalized_text + "\nJSON:",
                "temperature": 0,
                "n_predict": 160,
                "cache_prompt": True,
                "json_schema": UNION_SCHEMA,
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return str(response.json().get("content", "")).strip()


#: Trần độ dài câu dẫn. Model thoái hoá là chuyện **đã quan sát được** ở SPIKE-003
#: (lặp tới trần token), và một câu dẫn lan man thì tài xế phải nghe rất lâu trước khi
#: tới nội dung thật.
LEAD_IN_MAX_CHARS = 120

#: Prompt câu dẫn — BÊ NGUYÊN cấu hình đã đo ở biến thể A của run
#: `eval/results/spike-003/20260811T200114.021276Z` (p50 827 ms cả lượt). Hai ví dụ
#: few-shot là phần đã đo, không phải trang trí: thiếu chúng thì model trả về số mục
#: và số trang bịa ("Trang 12, mục 3.2.1.2.1.1...") thay vì một câu dẫn.
LEAD_IN_SYSTEM = (
    "Bạn là trợ lý xe VinFast. Viết đúng MỘT câu dẫn ngắn (tối đa 15 từ) để mở đầu, nói "
    "rằng bạn tìm thấy thông tin trong sổ tay về chủ đề tài xế hỏi. Tuyệt đối không nêu "
    "chi tiết kỹ thuật và không trả lời câu hỏi — phần nội dung sẽ được đọc nguyên văn "
    "từ sổ tay ngay sau câu dẫn của bạn.\n"
    "Ví dụ:\n"
    '- Câu hỏi "Làm sao bật sưởi ghế?" → "Về sưởi ghế, sổ tay xe hướng dẫn thế này:"\n'
    '- Câu hỏi "Áp suất lốp bao nhiêu?" → "Tôi tìm được phần nói về áp suất lốp, xin đọc lại:"'
)


def chatml(system: str, user: str) -> str:
    """Khuôn ChatML của Qwen2.5-Instruct.

    Không phải chi tiết vặt: mọi phép đo composer trước 2026-08-12 gọi `/completion`
    thô, không template, nên model **không có `<|im_end|>` để dừng** và nhại lại nguyên
    văn chỉ thị hệ thống vào cuối câu trả lời. Nhánh planner không lộ lỗi này vì grammar
    chặn hộ. Sang ChatML: decode p50 1.630 → 500 ms.
    """
    return f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"


class LeadInWriter(Protocol):
    def write(self, question: str, section: str) -> str: ...


class QwenLeadIn:
    """Client viết câu dẫn cho nhánh tra sổ tay.

    Tách khỏi `QwenPlanner` vì hai đường khác nhau về bản chất: planner ràng buộc bằng
    grammar JSON và **sai thì bị cổng an toàn chặn**; câu dẫn là văn xuôi tự do và
    **không được phép mang dữ kiện nào** — đó mới là thứ khiến nó an toàn, không phải
    một cổng kiểm nào cả.
    """

    def __init__(self, endpoint: str, model_id: str, timeout_s: float = 8.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._timeout_s = timeout_s

    def write(self, question: str, section: str) -> str:
        import httpx

        response = httpx.post(
            f"{self._endpoint}/completion",
            json={
                "prompt": chatml(LEAD_IN_SYSTEM, f"Câu hỏi: {question}\nMục sổ tay: {section}"),
                "temperature": 0,
                "n_predict": 40,
                "cache_prompt": True,
                "stop": ["<|im_end|>", "<|im_start|>"],
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return str(response.json().get("content", "")).strip()


#: --- S2: SLM chọn câu cho nhánh sổ tay ---
#:
#: Vai trò **thứ ba** của SLM, tách khỏi `QwenPlanner` và `QwenLeadIn` vì nó chịu một
#: ràng buộc mà hai cái kia không chịu: **không được sinh ký tự nào đi vào tai tài
#: xế**. Đầu ra là chỉ số câu; chữ thì lấy nguyên văn từ sổ tay.
#:
#: Đó là lý do S2 sống được sau khi ADR-015 bác phương án cho SLM viết lại đoạn (4/40
#: câu gây hiểu lầm, toàn bộ do rơi mất điều kiện theo phiên bản). Không có bước diễn
#: đạt lại thì lớp lỗi đó không dựng lên được.
#:
#: Prompt và schema dưới đây là **bản đã đo**: run `eval/results/spike-003/
#: 20260813T162737.967452Z` (0.5B, CPU 6 luồng) cho p50 664 ms / p95 1.011 ms trên 40
#: case dựng từ index thật, 0/40 chỉ số ngoài khoảng. `scripts/spike3_s2_shape.py`
#: import chính hai hằng này — sửa ở đây là làm con số kia hết hiệu lực, nên đo lại.
SENTENCE_SELECT_SCHEMA = {
    "type": "object",
    "properties": {
        "indices": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2}
    },
    "required": ["indices"],
}

SENTENCE_SELECT_PROMPT = (
    "Bạn chọn câu để đọc cho tài xế đang lái xe. Dưới đây là các câu đánh số của một "
    "đoạn sổ tay xe. Chọn 1-2 câu trả lời trúng câu hỏi nhất. Chỉ trả về chỉ số câu, "
    "không viết lại, không tóm tắt.\n\n"
)


def dung_prompt_chon_cau(question: str, sentences: list[str]) -> str:
    """Ghép prompt S2. Tách hàm để bộ đo và production dùng **cùng một chuỗi**."""
    danh_sach = "\n".join(f"[{i}] {c}" for i, c in enumerate(sentences))
    return f"{SENTENCE_SELECT_PROMPT}Câu hỏi: {question}\n\nCác câu:\n{danh_sach}\n\nJSON:"


class QwenSentenceSelector:
    """Client llama-server cho vai trò chọn câu.

    Mọi lỗi đều **không** ném ra ngoài dưới dạng ngoại lệ ngữ nghĩa: hỏng kết nối hay
    hết giờ thì để `httpx` ném (tầng `speech_policy` bắt và ghi `slm_error`), còn model
    trả rác thì trả `[]` — tức "không có ý kiến", và `speech_policy` rơi về luật S1.

    Hai đường đó cố ý phân biệt được ở `reason`: *llama-server không có* và *llama-server
    nói sai* dẫn tới hai quyết định khác nhau của nhóm.
    """

    def __init__(self, endpoint: str, model_id: str, timeout_s: float = 8.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._timeout_s = timeout_s

    def select(self, question: str, sentences: list[str]) -> list[int]:
        import httpx

        response = httpx.post(
            f"{self._endpoint}/completion",
            json={
                "prompt": dung_prompt_chon_cau(question, sentences),
                "temperature": 0,
                # 32 là trần đo được: đầu ra p50 chỉ 11 token. Để 160 như nhánh planner
                # là trả tiền decode cho một bài khác.
                "n_predict": 32,
                "cache_prompt": True,
                "json_schema": SENTENCE_SELECT_SCHEMA,
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        try:
            payload = json.loads(str(response.json().get("content", "")).strip())
        except (TypeError, ValueError):
            return []
        idx = payload.get("indices") if isinstance(payload, dict) else None
        return idx if isinstance(idx, list) else []


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

#: Prompt phân loại — tối giản vì prefill 350–450 tok/s là phần đắt.
#:
#: v2 (run 20260821T125335): v1 trượt hai lớp — than phiền ngầm ("Chân lạnh quá
#: nhỉ") bị coi là chitchat vì thiếu ví dụ, và câu hỏi cách-làm giọng mệnh lệnh
#: ("Đổi ngôn ngữ trên xe sang tiếng Anh") bị coi là control. v2 thêm hai dòng
#: luật + ví dụ mỗi lớp, CỐ Ý khác chữ với bộ đo `dinh-tuyen-v1` để không tự
#: chấm bài mình (trừ ca #149 giữ nguyên — nó là tripwire kinh điển của ADR-022).
CLASSIFY_SYSTEM = (
    "Phân loại câu của tài xế vào đúng một nhóm:\n"
    "- control: muốn xe LÀM gì, kể cả nói bằng lời than (nóng, lạnh, ồn, gió, tối, "
    "chán nhạc, muốn ghé đâu đó) — tài xế đang muốn xe chỉnh giúp\n"
    "- manual: muốn BIẾT về xe — cách làm, sự cố, tính năng, thông số — kể cả khi "
    "nói như ra lệnh\n"
    "- chitchat: xã giao, bình phẩm chuyện ngoài xe, không cần xe làm hay trả lời gì "
    "về chính nó\n"
    "Ba luật khó:\n"
    "- Nhờ vả (giùm, hộ, giúp cái) là control.\n"
    '- Hỏi xe CÓ LÀM ĐƯỢC gì không ("được không", "có ... không") là manual.\n'
    "- Phân vân giữa control và manual thì chọn manual — hỏi lại an toàn hơn làm nhầm.\n"
    "- Than phiền về TẦM NHÌN, kính mờ, an toàn là manual — cần hướng dẫn đúng cách, "
    "không tự ý bật thiết bị.\n"
    "Ví dụ:\n"
    '- "Nóng quá, giảm nhiệt độ xuống đi" → control\n'
    '- "Lạnh quá, tay tê cứng rồi" → control\n'
    '- "Ồn ào quá đi mất" → control\n'
    '- "Đói bụng quá, kiếm chỗ ăn đi" → control\n'
    '- "Áp suất lốp bao nhiêu là đủ?" → manual\n'
    '- "Xe báo lỗi áp suất lốp thì phải làm sao" → manual\n'
    '- "Cắm sạc điện thoại chỗ nào trên xe" → manual\n'
    '- "Kết nối điện thoại với xe kiểu gì" → manual\n'
    '- "Phát nhạc từ iPhone qua loa xe" → manual\n'
    '- "Xe có sưởi vô lăng không?" → manual\n'
    '- "Hạ kính hộ cái" → control\n'
    '- "Xin chào, hôm nay khỏe không?" → chitchat\n'
    '- "Hôm nay trời đẹp ghê" → chitchat\n'
    '- "Cậu tên gì thế?" → chitchat\n'
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


#: Câu HỎI VỀ KHẢ NĂNG đội lốt mệnh lệnh: "bật X từ xa được không", "xe có Y không".
#: Vì sao phải có lưới tất định SAU classifier: prompt v2→v4 (ba run 21/08) không
#: ép nổi model phân biệt ca này, mà chấm nhầm sang control thì planner có thể ra
#: một plan S1 hợp lệ (vd `set_hvac_power`) và CHẠY LUÔN — một câu hỏi làm xe đổi
#: trạng thái, đúng lớp lỗi ADR-011 giữ bằng 0. Regex hẹp cố ý: chỉ hai dạng hỏi
#: khả năng, không đụng mệnh lệnh có chữ "không" phủ định.
_HOI_KHA_NANG = re.compile(
    r"được không\b|được ko\b|có\s+\S[^?]{0,40}?\bkhông\s*\??\s*$",
    re.IGNORECASE,
)


#: Miền tài xế hay ra lệnh nhưng KHÔNG có tool nào trong registry —
#: `docs/coverage_matrix.md` là nguồn. Chấm control cho chúng thì planner bắt
#: buộc kết thúc ở clarify (ngõ cụt); hạ về manual thì sổ tay trả lời được
#: "chỉnh ở đâu". Danh sách ĐÓNG và phải đi theo coverage_matrix: thêm tool
#: cho miền nào thì XOÁ miền đó khỏi đây, không thì lệnh thật bị nuốt.
_MIEN_NGOAI_TAM = (
    "gạt nước",
    "gạt mưa",
    "ngôn ngữ",
    "cruise",
    "ga tự động",
    "đèn sương mù",
    "camp mode",
    "chế độ cắm trại",
)


def ap_luoi_an_toan(intent: str, normalized_text: str) -> str:
    """Lưới tất định sau classifier: chỉ hạ `control` → `manual`, không bao giờ ngược.

    Hai lớp, cùng chiều an toàn: câu hỏi khả năng (kẻo planner trả plan S1 chạy
    luôn cho một CÂU HỎI), và miền ngoài tầm với (kẻo tài xế nhận một clarify
    ngõ cụt thay vì câu sổ tay có ích). Dùng ở CẢ hai nơi — node `slm_classify`
    và eval `dinh-tuyen` — để con số đo đúng là con số chạy thật.
    """
    if intent != "control":
        return intent
    ha = normalized_text.lower()
    if _HOI_KHA_NANG.search(normalized_text) or any(m in ha for m in _MIEN_NGOAI_TAM):
        return "manual"
    return intent


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
    """Đọc reply của vai chitchat. Rỗng hay sai JSON là hỏng — node quyết fail-safe."""
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

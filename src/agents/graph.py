"""StateGraph của agent VIVI.

Định tuyến ưu tiên luật theo `docs/agent_spec.md`. Mọi phụ thuộc đều inject
được — không có singleton mức module, vì test cần nhiều simulator độc lập
trong cùng một tiến trình.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from langgraph.graph import END, START, StateGraph

from src.agents.approval import ApprovalStore
from src.agents.cong_mien_slm import lech_y
from src.agents.nodes.approval import make_request_approval_node
from src.agents.nodes.chitchat_cong import CAU_BAN, CAU_MAU_CHUNG, cong_dau_vao_chitchat, qua_cong_chitchat
from src.agents.nodes.compose import compose_node
from src.agents.nodes.execute import make_execute_node
from src.agents.nodes.normalize import make_normalize_node
from src.agents.nodes.route import make_route_node
from src.agents.nodes.routine_node import make_routine_node
from src.agents.nodes.safety import safety_node
from src.agents.nodes.validate import validate_node
from src.agents.policy import classify
from src.agents.router import DeterministicControlRouter
from src.agents.slm import (
    LEAD_IN_MAX_CHARS,
    ChitchatWriter,
    Classifier,
    LeadInWriter,
    Planner,
    SlmBanError,
    SlmSchemaError,
    ap_luoi_an_toan,
    goi_qua_van,
    parse_slm_output,
)
from src.agents.state import NO_COMPOSING_STATUS_OUTCOMES, AgentState
from src.config import get_settings
from src.fixtures import load_poi_fixture
from src.services.routine_execution import bat_dau as bat_dau_routine
from src.services.routine_execution import dang_chay_trong_phien
from src.services.routine_execution import huy as huy_routine
from src.services.routines_store import list_routines
from src.services.vehicle_gateway import VehicleGateway

logger = logging.getLogger(__name__)

RagNode = Callable[[AgentState], Any]

#: Câu mở đầu của vòng sửa. Phần **sau** nó là chuỗi lỗi thật — xem `_cau_sua_loi`.
REPAIR_HINT = "JSON trước không hợp lệ."


def _cau_sua_loi(loi: str) -> str:
    """Lời nhắc cho vòng thử thứ hai, mang theo lỗi CỤ THỂ của vòng thứ nhất.

    Bản trước chỉ nói *"JSON trước không hợp lệ. Trả lại đúng một object JSON theo
    schema."* — mà JSON **vẫn** hợp lệ về cú pháp; hỏng là ở schema args. Model không
    có thông tin nào để sửa nên nó lặp lại y hệt. Đo 26/08 với Qwen3-4B thật:

        'lạnh quá tắt điều hòa đi' + hint -> {"power":"off"}  (y hệt lần 1)
        'chán quá mở nhạc lên'     + hint -> {"action":"play_music","source":"online"}
                                             (tệ hơn lần 1)

    Tức vòng sửa tốn thêm một lượt gọi model (~0,5–3 s) mà gần như không mua lại gì.
    Chuỗi lỗi đã có sẵn từ `validate_args` (`args không hợp lệ cho set_hvac_power:
    enabled: Field required`) — nó chỉ chưa bao giờ được đưa cho model.
    """
    return f"{REPAIR_HINT} Lỗi: {loi}. Sửa đúng chỗ đó và trả lại một object JSON."


def _route_after_classify(state: AgentState) -> str:
    reason = state.get("route_reason", "")
    if reason == "slm_classified_control":
        return "slm"
    if reason == "slm_classified_chitchat":
        return "chitchat"
    # slm_classified_manual VÀ slm_classify_failed cùng về rag: fail-safe là
    # hành vi ADR-011 cũ, không phải một nhánh riêng cần bảo trì.
    return "rag"


def _make_route_after_routing(has_classifier: bool) -> Callable[[AgentState], str]:
    """Factory theo mẫu `_make_route_after_safety`: khi không có classifier thì
    node `slm_classify` không tồn tại, trả key ấy ra là LangGraph nổ lúc dựng."""

    def _route_after_routing(state: AgentState) -> str:
        outcome = state.get("outcome")
        if outcome == "control":
            return "validate"
        # Routine có node riêng: nó có vòng đời của chính nó và không dựng `ActionPlan`
        # nào ở tầng này. Đứng ngay sau `control` vì nó cũng là một lượt **làm việc**,
        # không phải một lượt hỏi đáp.
        if outcome == "routine":
            return "routine"
        # `offer` đi thẳng compose: nó chỉ nêu việc sẽ làm, không được chạm executor.
        if outcome == "offer":
            return "compose"
        # "Đọc tiếp" đi **thẳng** compose: đoạn nguồn đã có từ lượt trước. Cho nó qua
        # `rag` là truy hồi lại bằng chính chữ "đọc tiếp" và trả về một đoạn khác hẳn
        # — đúng lỗi S3 sinh ra để sửa.
        if state.get("intent") == "manual_continue":
            return "compose"
        # "Thôi, không nghe nữa" cũng đi thẳng compose, và vì cùng một lý do: nó là câu trả
        # lời cho câu hỏi lượt trước, không phải một câu hỏi mới cần tra sổ tay. Thiếu dòng
        # này thì nó rơi vào nhánh `not_control` bên dưới và đi hỏi SLM.
        if state.get("intent") == "manual_stop_reading":
            return "compose"
        # Từ chối một lời đề nghị cũng đi thẳng compose, và vì đúng lý do ấy: đây là câu
        # trả lời cho câu hỏi lượt trước, không phải một câu hỏi mới cần tra sổ tay.
        if state.get("intent") == "offer_declined":
            return "compose"
        # Mảnh không khớp mẫu cũng đi thẳng compose: nó phải nghe lại đúng câu hỏi cũ,
        # không phải một đoạn sổ tay tra bằng chính mảnh vừa bị từ chối.
        if state.get("intent") == "manh_khong_khop_mau":
            return "compose"
        # Câu đuổi trợ lý đi thẳng compose: không có gì để tra cứu, và đây là nhánh phải
        # đứng TRƯỚC `slm_classify` bên dưới — một tiếng "thôi" không phải chuyện trò.
        if state.get("intent") == "giai_tan":
            return "compose"
        # SP-1: nhánh trượt default_to_manual đổi nghĩa thành "hỏi SLM" — nhưng CHỈ
        # nhánh trượt. Câu router hiểu (manual_question, tire_pressure...) vẫn đi
        # thẳng, đúng thiết kế đường tắt. Xem ADR-026.
        if has_classifier and state.get("route_reason") == "default_to_manual":
            return "slm_classify"
        # Áp suất lốp vẫn đi qua RAG dù câu trả lời tới từ bảng curate. Cố ý: khi xe chưa
        # khai báo `trim`/`battery` thì bảng fail-closed, và lúc đó ta **vẫn** phải có câu
        # sổ tay trong tay để nói ("ghi trên nhãn ở khung cửa"). Bỏ qua RAG ở đây là đổi một
        # câu trả lời tạm dùng được lấy một ngõ cụt.
        if state.get("intent") == "tire_pressure_query":
            return "rag"
        if state.get("intent") == "manual_query":
            return "rag"
        if outcome == "not_control":
            return "slm"
        return "compose"

    return _route_after_routing


def _route_after_slm(state: AgentState) -> str:
    return "validate" if state.get("outcome") == "control" else "compose"


def _route_after_validate(state: AgentState) -> str:
    return "safety" if state.get("outcome") == "validated" else "compose"


def _make_route_after_safety(has_approval_branch: bool) -> Callable[[AgentState], str]:
    """Factory vì khi không bật HITL thì node `approval` không tồn tại.

    Trả về một key không có trong map thì LangGraph báo lỗi ngay lúc dựng graph.
    """

    def route_after_safety(state: AgentState) -> str:
        outcome = state.get("outcome")
        if outcome == "safe":
            return "execute"
        if outcome == "approval_required" and has_approval_branch:
            return "approval"
        return "compose"

    return route_after_safety


def _route_after_approval(state: AgentState) -> str:
    return "execute" if state.get("outcome") == "approval_granted" else "compose"


def _timed(stage: str, node: Callable[[AgentState], Any]) -> Callable[[AgentState], Any]:
    """Bọc một node để đo wall time, ghi thẳng vào `TraceStore`.

    Thuần quan sát: không đọc, không sửa, không thêm gì vào state trả về. Gỡ
    wrapper ra thì graph chạy y hệt.

    Ghi ra store chứ **không** ghi vào `AgentState`: state là `TypedDict` không có
    reducer, hai node cùng ghi một key sẽ đè nhau. Ghi ra ngoài tránh hẳn chuyện đó.

    `record_stage` là last-write-wins, **không cộng dồn** — LangGraph chạy lại thân
    node từ đầu khi resume approval (xem docstring `src/agents/approval.py`), cộng
    dồn sẽ nhân đôi số đo của mọi node nằm trước điểm interrupt.

    Import muộn để `src.agents` không kéo theo `src.services` lúc dựng graph.
    """

    async def wrapped(state: AgentState) -> Any:
        started = time.perf_counter()
        try:
            return await node(state)
        finally:
            trace_id = state.get("trace_id")
            if trace_id:
                from src.services.trace_store import get_trace_store

                get_trace_store().record_stage(trace_id, stage, (time.perf_counter() - started) * 1000)

    return wrapped


def _with_live_status(
    wake_state: str, message: str, node: Callable[[AgentState], Any], *, gate: Callable[[AgentState], bool] | None = None
) -> Callable[[AgentState], Any]:
    """Bọc một node để phát `assistant.status` NGAY khi node bắt đầu chạy.

    Trước bản này, `"retrieving"`/`"composing"` chỉ được `emit_turn_lifecycle()` dịch lại
    SAU KHI `graph.ainvoke()` đã trả về (`src/api/turns.py`) — tài xế thấy "Đang xử lý"
    đứng yên suốt lượt tra sổ tay rồi hai trạng thái sau nháy qua trong cùng một khắc
    ngay trước câu trả lời. Bọc ở đây phát đúng lúc chặng đó thật sự bắt đầu.

    `gate`: một số outcome (lệnh điều khiển đã thực thi/bị chặn, kết thúc theo phê
    duyệt) không được phép có `"composing"` dù node `compose` vẫn chạy cho chúng — xem
    `NO_COMPOSING_STATUS_OUTCOMES`. `gate=None` (dùng cho `"retrieving"`) nghĩa là luôn
    phát: node `rag` chỉ chạy trên đúng nhánh sẽ cần trạng thái đó, không cần lọc thêm.

    KHÔNG bọc node `execute`: `docs/api_spec.md:620` quy định thứ tự
    `routing → plan.ready → executing`, mà `plan.ready` chỉ tính được sau khi
    `graph.ainvoke()` trả về (cần `result["action_plan"]`) — phát `"executing"` sống
    ở đây sẽ đảo thứ tự đã spec. Xem issue #346.

    Import muộn để `src.agents` không kéo theo `src.services` lúc dựng graph — cùng lý
    do với `_timed`.
    """

    async def wrapped(state: AgentState) -> Any:
        session_id = state.get("session_id")
        turn_id = state.get("turn_id")
        if session_id and turn_id and (gate is None or gate(state)):
            from src.services.ivi_events import get_event_bus

            await get_event_bus().publish(
                session_id, "assistant.status", turn_id, state.get("trace_id", ""), {"state": wake_state, "message": message}
            )
        return await node(state)

    return wrapped


def build_graph(
    gateway: VehicleGateway,
    *,
    router: DeterministicControlRouter | None = None,
    rag: RagNode | None = None,
    planner: Planner | None = None,
    classifier: Classifier | None = None,
    chitchat: ChitchatWriter | None = None,
    lead_in: LeadInWriter | None = None,
    approvals: ApprovalStore | None = None,
    hitl_timeout_seconds: int = 30,
    checkpointer: Any | None = None,
) -> Any:
    """Dựng graph cho một phiên. `rag=None` thì nhánh sổ tay dùng node thật.

    Import `rag_node` bị hoãn tới **lúc nhánh sổ tay thực sự chạy**, không phải
    lúc dựng graph. Nó kéo theo `src.rag` → `faiss`/`bs4`; nếu import sớm thì
    một checkout thiếu extra RAG sẽ không dựng nổi graph, và cả `src.main` sập
    theo. Câu lệnh điều khiển không cần RAG nên không được trả giá đó.
    """

    async def rag_stage(state: AgentState) -> dict:
        if rag is None:
            from src.agents.nodes.rag_node import rag_node

            rag_impl: RagNode = rag_node
        else:
            rag_impl = rag
        try:
            update = dict(await rag_impl(state))
        except (OSError, ValueError, RuntimeError) as exc:
            # Lưới an toàn cuối. Sau ADR-011 đây là đường mặc định của mọi câu lạ
            # nên tuyệt đối không được sập.
            #
            # Việc phân loại "chỉ mục chưa dựng" nằm ở `rag_node.index_is_built()`
            # — kiểm bằng cách đọc đĩa, chạy **trước** khi gọi retriever. Tới được
            # đây nghĩa là chỉ mục có mà vẫn hỏng, tức lỗi thật cần người sửa; đừng
            # gán nó thành "chưa dựng chỉ mục" chỉ vì thông điệp lỗi trông giống.
            return {
                "outcome": "grounded_refusal",
                "refusal_reason": "retrieval_failed",
                "error": f"không tra được sổ tay: {exc}",
            }
        if update.get("refusal_reason"):
            update["outcome"] = "grounded_refusal"
        elif update.get("error"):
            update["outcome"] = "validation_denied"
        else:
            update["outcome"] = "grounded_answer"
            update["grounded_lead_in"] = _write_lead_in(state, update)
        return update

    def _write_lead_in(state: AgentState, update: dict) -> str:
        """Câu dẫn do SLM viết — **fail-open**, khác hẳn nhánh planner.

        Phần này không mang dữ kiện nào (nội dung là trích nguyên văn ở `compose_node`),
        nên hỏng nó không phải lý do từ chối trả lời: rơi về chuỗi cố định là xong, tài
        xế vẫn nhận đúng nội dung. Đây chính là điều ADR-015 (bản sửa) hứa — thiếu SLM
        chỉ làm câu dẫn kém tự nhiên, không làm mất tính năng.

        Bắt `Exception` rộng có chủ đích: llama-server có thể hỏng theo nhiều kiểu
        (mạng, JSON, timeout), và không kiểu nào đáng để đánh đổi cả câu trả lời.
        """
        if lead_in is None:
            return ""
        evidence = update.get("evidence") or []
        if not evidence:
            return ""
        top = evidence[0]
        section = top.get("section", "") if isinstance(top, dict) else getattr(top, "section", "")
        try:
            text = lead_in.write(state.get("query", ""), section or "sổ tay xe")
        except Exception as exc:  # noqa: BLE001 — xem docstring
            logger.warning("Câu dẫn SLM hỏng (%s); dùng chuỗi cố định", exc)
            return ""
        return text.strip()[:LEAD_IN_MAX_CHARS]

    def route_after_rag(state: AgentState) -> str:
        """Sổ tay không có câu trả lời — có đáng thử SLM không?

        Hai điều kiện, cả hai đều cần:

        - Phải **có** planner.
        - Trước đó ta phải chỉ **mặc định** đưa sang sổ tay (`default_to_manual`),
          tức chưa từng có bằng chứng dương nào rằng đây là câu hỏi. Một câu đã
          được nhận diện rõ là câu hỏi (`manual_question`) mà sổ tay không trả lời
          được thì câu trả lời đúng là "không có trong sổ tay"; đưa tiếp cho SLM
          đoán là mời nó bịa.

        ## Điều kiện thứ ba đã bị bỏ (issue #149)

        Bản trước còn đòi `outcome == "grounded_refusal"`, tức **RAG có quyền phủ
        quyết planner**. Nó chỉ cần vượt `RAG_MIN_SCORE = 0.848` là planner không bao
        giờ chạy. Thành đo: *"Nóng quá, giảm nhiệt độ xuống đi"* nhận lại đoạn **"Bảo
        dưỡng / Dầu mỡ"** ở 0,853 — hơn ngưỡng đúng 0,005.

        Không sửa được bằng ngưỡng. Đo phân bố (15/08): mệnh lệnh vượt ngưỡng đạt
        0,853–0,885, còn câu hỏi sổ tay thật có **min 0,865 / p25 0,879** — hai phân bố
        **chồng nhau**. `"Chỉnh ghế thoải mái hơn"` đạt 0,885, cao hơn p25 của câu hỏi
        thật. Lý do sâu hơn: điểm đo **độ liên quan chủ đề**, mà "chỉnh ghế" thì đúng là
        liên quan tới mục Ghế. RAG không sai — thứ khác nhau là **hành vi lời nói**.

        Bộ dò mệnh lệnh cũng không cứu được: `_looks_imperative` bỏ sót 5/7 câu tự
        nhiên vì nó chỉ bắt động từ ở **đầu** câu.

        Nên thôi phân biệt trước, để **kết quả** quyết định: hỏi planner, ra plan thì
        dùng, không ra thì lui về câu trả lời sổ tay đã tính (xem `slm_stage`).

        Điều này **an toàn được là nhờ ADR-021**: plan do SLM đề xuất phải qua xác nhận.
        Không có cổng ấy thì mở đường này là liều — đo thật cho thấy *"Công thức nấu phở
        bò truyền thống"* cũng làm planner sinh ra một **plan**, không phải chitchat.

        ## Mất trạng thái xe thì đừng hỏi planner (sửa 16/08)

        Plan sinh ra lúc không có snapshot thì `safety_node` từ chối ngay
        (`vehicle_state_unavailable`), nên gọi planner chỉ tốn 1,5–8 s rồi vứt — và tệ
        hơn: nó **thay** câu trả lời sổ tay đã có bằng *"Tôi chưa đọc được trạng thái
        xe"*. `safety.py` đã cảnh báo đúng ca này ("broker chết mà mất luôn RAG thì là
        một regression vô cớ"); #149 lùa lượt sổ tay vào nhánh điều khiển nên vô hiệu
        hoá ý định ấy.

        Chỉ bỏ qua khi **đã có câu trả lời để đưa ra**. Không có thì vẫn đi tiếp, để
        `safety_node` nói đúng lý do — *"chưa đọc được trạng thái xe"* trung thực hơn
        *"không có trong sổ tay"* khi xe đang mất liên lạc, và đó là hành vi có **trước**
        #149. Sửa một hồi quy không được phép đổi thêm thứ khác.
        """
        if not state.get("vehicle_snapshot") and state.get("outcome") == "grounded_answer":
            return "compose"
        if planner is not None and state.get("route_reason") == "default_to_manual":
            return "slm"
        return "compose"

    async def slm_stage(state: AgentState) -> dict:
        """Đề xuất → kiểm schema → đúng một lần sửa → hết thì hỏi lại."""
        if planner is None:
            return {"outcome": "not_control", "route_source": "fallback"}
        snapshot = state["vehicle_snapshot"]
        text = state.get("normalized_text", "")
        # Cổng ĐẦU VÀO đứng trước cả planner: union prompt có thể trả `kind: chitchat`,
        # nên đường này cũng nói chuyện được — và câu báo triệu chứng xe thì không
        # model nào được phép trả lời, đi đường nào cũng vậy. Xem `cong_dau_vao_chitchat`.
        chuyen_huong = cong_dau_vao_chitchat(text)
        if chuyen_huong is not None:
            return {
                "outcome": "chitchat",
                "chitchat_reply": chuyen_huong,
                "chitchat_cong": "trieu_chung_an_toan",
                "route_source": "slm",
            }
        loi_lan_truoc = ""
        for attempt in range(2):
            try:
                # `asyncio.to_thread`: client SLM dùng `httpx` ĐỒNG BỘ, mà node này là
                # `async`. Gọi thẳng thì một lượt planner chặn TOÀN BỘ event loop tới
                # `slm_timeout_s` (20 s trên VPS) x 2 lần thử — nghĩa là mọi người dùng
                # khác, mọi WebSocket và cả `/healthz` đều đứng im trong lúc đó. Cùng
                # khuôn với STT (`turns.py:254`), TTS (`ivi_events.py:420`), SQLite và
                # RAG probe (`health.py`); SLM là chỗ duy nhất còn sót.
                loi_nhac = text if attempt == 0 else f"{text}\n{_cau_sua_loi(loi_lan_truoc)}"
                raw = await goi_qua_van("planner", planner.propose, loi_nhac, snapshot)
                out = parse_slm_output(raw)
            except SlmBanError as exc:
                # Het cho: BO CUOC NGAY, khong sang lan thu hai. Thu lai chi de xin dung
                # cai van vua tu choi, va bat tai xe cho them mot vong vo ich.
                #
                # Uu tien cau tra loi THAT hon la loi xin loi: RAG da chay xong truoc khi
                # toi day (23 ms, xem `_lui_ve_so_tay`), nen so tay co san cau tra loi thi
                # dua cau do. Chi khi khong co gi moi noi "dang ban".
                logger.warning("van SLM day, planner bo cuoc: %s", exc)
                return _lui_ve_so_tay(state) or {
                    "outcome": "chitchat",
                    "chitchat_reply": CAU_BAN,
                    "chitchat_cong": "ban",
                    "route_source": "fallback",
                }
            except httpx.TimeoutException as exc:
                # HET GIO thi BO CUOC NGAY, khong sang lan thu hai — cung ly le voi
                # `SlmBanError` ngay tren. Lan thu hai gui kem `_cau_sua_loi(...)`
                # ("JSON truoc khong hop le") cho mot lan chay CHUA TRA VE GI CA, nen
                # no khong sua duoc gi ca; no chi nhan doi thoi gian tai xe phai cho.
                #
                # Do duoc tren VPS, run `20260827T084543` (N=1, mot nguoi, khong ai
                # tranh tai nguyen): mot luot planner ton 40 086 ms = 2 x `slm_timeout_s`
                # (20 s tren VPS) roi van ket thuc bang `tra_loi`. Trong ca 15 luot cua
                # run do, lan thu hai khong cuu duoc luot nao.
                #
                # `break` chu khong `return`: roi xuong dung dong fallback sau vong lap,
                # tuc hanh vi giong het khi het luot thu — chi bo di mot vong vo ich.
                #
                # Nhanh nay phai dung TRUOC `httpx.HTTPError` o duoi: TimeoutException la
                # lop con cua no, dat sau thi khong bao gio toi.
                logger.warning("SLM planner het gio o lan thu %d/2, bo cuoc: %s", attempt + 1, exc)
                break
            except (SlmSchemaError, OSError, httpx.HTTPError) as exc:
                # httpx.HTTPError KHONG phai OSError — server chet ma chi bat OSError
                # thi luot no 500 xuyen qua graph thay vi roi ve clarify (ADR-016:
                # SLM hong la roi ve hanh vi cu, khong phai su co). Bat duoc bang
                # kiem tay model that, khong phai bang stub.
                #
                # Log phan loai "ha tang" / "schema": hanh vi be mat cua hai ca giong
                # het nhau (deu clarify), nen thieu dong nay thi server chet ca buoi
                # cung khong ai biet.
                kind = "schema" if isinstance(exc, SlmSchemaError) else "hạ tầng"
                logger.warning("SLM attempt %d/2 hỏng (%s): %s", attempt + 1, kind, exc)
                # Chuyển nguyên văn lỗi sang vòng sau. Lỗi hạ tầng thì cũng chẳng hại:
                # vòng sau sẽ hỏng lại ở cùng chỗ và không ai đọc chuỗi ấy.
                loi_lan_truoc = str(exc)
                continue
            if isinstance(out, str):
                # Trò chuyện: không có gì để validate/safety — không chạm executor.
                #
                # NHƯNG vẫn phải qua cổng. Đây là đường chitchat **thứ hai**: union
                # prompt của planner trả `kind: chitchat` cho câu nó không dựng nổi
                # plan. Trước 23/08 chuỗi ấy đi thẳng ra `compose`, bỏ qua cả năm lớp
                # cổng SP-2 — cùng một câu bịa, đi đường node `chitchat` thì bị chặn,
                # đi đường này thì lọt. Ca thật: `"Xe rung lắc quá"` ở 45 km/h.
                phat, cong = qua_cong_chitchat(out)
                return _lui_ve_so_tay(state) or {
                    "outcome": "chitchat",
                    "chitchat_reply": phat,
                    "chitchat_cong": cong,
                    "route_source": "slm",
                }
            # Cổng fail-closed cuối cùng trước khi plan rời node (yêu cầu (b) của
            # review #324): câu nói về đèn mà plan chạm cửa thì **không sinh plan**.
            # Đứng ở đây chứ không ở `validate_node` vì nó là luật riêng của đường
            # SLM — plan do router luật dựng đã có một luật khớp đứng sau, không cần.
            #
            # NHƯNG nhường đường cho S3. Bản đầu của cổng này chặn trước mọi thứ, và nó
            # làm hai test S3 đỏ theo một cách đáng chú ý: `"Nóng quá, giảm nhiệt độ
            # xuống đi"` + plan mở cửa lúc xe chạy 45 km/h vốn ra `blocked` — một câu
            # nói thật rằng có chuyện gì đó bị chặn — bị hạ thành `clarify` trống rỗng.
            # Cả hai đều zero side effect, nên xét về an toàn là hoà; xét về câu tài xế
            # nghe thì `blocked` hơn hẳn. Cổng miền chỉ để bắt thứ **safety cho qua**.
            if not any(classify(buoc.tool, snapshot) == "S3" for buoc in out.steps):
                tool_lech = lech_y(text, out)
            else:
                tool_lech = None
            if tool_lech is not None:
                logger.warning("plan SLM lệch miền so với câu nói, chặn: %s ← %r", tool_lech, text)
                return _lui_ve_so_tay(state) or {"outcome": "clarify", "route_source": "fallback"}
            return {"candidate_action_plan": out, "outcome": "control", "route_source": "slm"}
        return _lui_ve_so_tay(state) or {"outcome": "clarify", "route_source": "fallback"}

    async def classify_stage(state: AgentState) -> dict:
        """Một lượt gọi, chỉ phân loại. Mọi lỗi rơi về manual — ADR-011 cũ."""
        text = state.get("normalized_text", "")
        try:
            # Xem ghi chú `asyncio.to_thread` ở `slm_stage`: chặn event loop tới
            # `slm_classify_timeout_s` cho MỖI câu trượt luật.
            intent = await goi_qua_van("classify", classifier.classify, text)  # type: ignore[union-attr]
        except SlmBanError as exc:
            # KHONG tu choi tai xe o day, va do la co y. Bo qua phan loai thi lu ot roi ve
            # duong mac dinh la tra so tay — ma tra so tay KHONG dung llama-server chut nao
            # (FAISS + E5, cau tra loi trich nguyen van). Tu choi o day la tu choi mot viec
            # he VAN LAM DUOC, va bien moi cau hoi so tay thanh loi xin loi luc dong nguoi.
            #
            # Ve dieu kien 2 cua review ("khong duoc im lang fallback"): no khong im lang
            # nua — `slm_classify_ban` la mot `route_reason` RIENG, tach khoi `_failed`, nen
            # trace va /metrics/summary dem duoc. "Im lang" la khong ai biet, khong phai la
            # "tai xe khong bi lam phien".
            logger.warning("van SLM day, classify roi ve so tay: %s", exc)
            return {"route_reason": "slm_classify_ban"}
        except httpx.TimeoutException as exc:
            # Nhánh này phải đứng TRƯỚC `httpx.HTTPError` ở dưới — cùng lý do đã ghi ở
            # `slm_stage`: TimeoutException là lớp con của nó, đặt sau thì không bao giờ
            # tới. `slm_stage` đã có nhánh riêng này từ trước; `classify_stage` thì chưa,
            # và đó là cả vấn đề.
            #
            # VÌ SAO TÁCH RA, hai lý do đo được chứ không phải cho gọn:
            #
            # 1. `str(httpx.ReadTimeout)` RỖNG. Gộp vào nhánh dưới thì dòng log ra đúng
            #    "slm_classify hỏng, rơi về manual: " — không grep được bằng chữ nào.
            #    Đo trên VPS 28/08 (run `20260828T145920.055372Z`): 40% số lượt ở mức 3
            #    người đồng thời đi qua đúng nhánh này, `route` đóng cứng ở 7 030 ms
            #    (= `slm_classify_timeout_s`), và `grep -i timeout` trên log ra RỖNG.
            #
            # 2. `route_reason` riêng, cùng lập luận `slm_classify_ban` ở trên: hết giờ
            #    đếm được ở trace và `/metrics/summary` mới là "không im lặng". Một dòng
            #    log chỉ người có SSH mới thấy; một `route_reason` thì màn kỹ sư thấy.
            #
            # Vẫn về `rag` như `_failed` (xem `_route_after_classify`): đổi cách ĐẾM,
            # không đổi hành vi fail-safe của ADR-011.
            logger.warning(
                "slm_classify hết giờ sau %.1fs (%s), rơi về sổ tay",
                get_settings().slm_classify_timeout_s,
                type(exc).__name__,
            )
            return {"route_reason": "slm_classify_timeout"}
        except (SlmSchemaError, OSError, httpx.HTTPError) as exc:
            # Cùng bộ ba exception với slm_stage, cùng lý do: httpx.HTTPError
            # không phải OSError, server chết mà chỉ bắt OSError thì 500 xuyên graph.
            logger.warning("slm_classify hỏng (%s), rơi về manual: %s", type(exc).__name__, exc)
            return {"route_reason": "slm_classify_failed"}
        # Lưới tất định SAU model: hỏi khả năng ("... được không") mà model chấm
        # control thì hạ về manual — plan S1 cho một câu hỏi là lớp lỗi ADR-011.
        intent = ap_luoi_an_toan(intent, text)
        return {"route_reason": f"slm_classified_{intent}"}

    async def chitchat_stage(state: AgentState) -> dict:
        """Generator → cổng → compose (SP-2). Mọi lỗi rơi về câu mẫu — không treo, không 500."""
        text = state.get("normalized_text", "")
        # Cổng ĐẦU VÀO trước mọi thứ: câu báo triệu chứng xe thì model không được
        # gọi, chứ không phải gọi rồi lọc — xem `cong_dau_vao_chitchat`.
        chuyen_huong = cong_dau_vao_chitchat(text)
        if chuyen_huong is not None:
            return {"outcome": "chitchat", "chitchat_reply": chuyen_huong, "chitchat_cong": "trieu_chung_an_toan"}
        if chitchat is None:
            return {"outcome": "chitchat", "chitchat_reply": CAU_MAU_CHUNG, "chitchat_cong": "loi"}
        try:
            # Xem ghi chú `asyncio.to_thread` ở `slm_stage`.
            tho = await goi_qua_van("chitchat", chitchat.reply, text)
        except SlmBanError as exc:
            # `cong="ban"` chu khong phai `"loi"`: mot ben la qua tai tam thoi, ben kia la
            # model hong. Tron hai thu vao mot nhan thi bang do sau nay khong tach duoc.
            logger.warning("van SLM day, chitchat dung cau ban: %s", exc)
            return {"outcome": "chitchat", "chitchat_reply": CAU_BAN, "chitchat_cong": "ban"}
        except (SlmSchemaError, OSError, httpx.HTTPError) as exc:
            logger.warning("chitchat hỏng, rơi về câu mẫu: %s", exc)
            return {"outcome": "chitchat", "chitchat_reply": CAU_MAU_CHUNG, "chitchat_cong": "loi"}
        phat, cong = qua_cong_chitchat(tho)
        return {"outcome": "chitchat", "chitchat_reply": phat, "chitchat_cong": cong}

    def _lui_ve_so_tay(state: AgentState) -> dict | None:
        """Planner không ra plan, nhưng RAG **đã** có câu trả lời — dùng lại nó.

        Đây là vế giữ cho #149 không phá ADR-011. Mặc-định-về-sổ-tay vẫn còn; nó chỉ
        thôi là *câu trả lời đầu* và thành *phương án lui*. Bỏ vế này thì mọi câu
        planner không hiểu sẽ ra `clarify`, tức đánh đổi một câu trả lời có ích lấy một
        câu hỏi lại — hỏng đúng thứ ADR-011 chọn mặc định ấy vì.

        RAG chỉ tốn 23 ms (đo 15/08) nên nó đã chạy xong trước khi tới đây; không có gì
        để tiết kiệm bằng cách bỏ qua. Cũng vì thế mà **tuần tự**, không song song:
        23 ms trên một lời gọi planner 1.450–8.200 ms là 0,3–1,6%.
        """
        if state.get("citations"):
            return {"outcome": "grounded_answer", "route_source": "fallback"}
        return None

    builder = StateGraph(AgentState)
    builder.add_node("normalize", make_normalize_node(gateway))
    # Tên node giữ nguyên `route` (các cạnh bên dưới tham chiếu tới nó); `routing` là
    # tên **stage** trong `api_spec.md:342`. Không đo ở đây thì
    # `stage_latencies_ms.routing` vĩnh viễn `null` — đúng ô mà ADR-006 cần chứng
    # minh: định tuyến bằng luật rẻ hơn gọi model.
    # Truyền fixture vào seam đã có sẵn từ trước: không có nó thì `_poi_ids` rỗng và
    # guard `poi_not_in_fixture` chưa từng chạy một lần nào ở runtime — nó chỉ được
    # kích hoạt trong test dựng router trực tiếp.
    builder.add_node(
        "route",
        _timed("routing", make_route_node(router or DeterministicControlRouter(poi_fixture=list(load_poi_fixture())))),
    )
    # Chỉ `safety` được đo, không gộp `validate` vào. `record_stage` là ghi đè nên
    # bọc cả hai sẽ **mất** số của validate chứ không cộng lại; mà cộng thì hỏng khi
    # LangGraph chạy lại node lúc resume. api_spec.md không có ô riêng cho validate,
    # nên `stage_latencies_ms.safety` ở đây đúng nghĩa là "thời gian phân loại an
    # toàn", không phải "toàn bộ cổng kiểm".
    builder.add_node("validate", validate_node)
    builder.add_node("safety", _timed("safety", safety_node))
    # `tool` là thời gian của **cả bước thực thi**, gồm cả chờ ack từ broker. Không
    # lấy được từ sự kiện `tool.result` vì payload dây của nó không mang `latency_ms`
    # (xem `emit_turn_lifecycle`), nên phải đo ngay tại node.
    builder.add_node("execute", _timed("tool", make_execute_node(gateway)))
    builder.add_node(
        "rag",
        _timed("planning_or_retrieval", _with_live_status("retrieving", "Đang tra sổ tay xe.", rag_stage)),
    )
    builder.add_node("slm", _timed("planning_or_retrieval", slm_stage))
    builder.add_node(
        "compose",
        _with_live_status(
            "composing",
            "Đang soạn câu trả lời.",
            compose_node,
            gate=lambda state: state.get("outcome") not in NO_COMPOSING_STATUS_OUTCOMES,
        ),
    )

    # Routine gọi thẳng service của BE trong cùng tiến trình: Agent và BE cùng chạy
    # dưới `src/serve.py`, nên gọi `POST /routines/{id}/run` từ trong graph là tự gọi HTTP
    # vào chính mình — thêm một vòng serialize, một đường lỗi mới, và một bản sao logic
    # auth. `bat_dau` giữ nguyên mọi cổng admission mà làn BE đã dựng.
    builder.add_node(
        "routine",
        make_routine_node(
            liet_ke=list_routines,
            bat_dau=bat_dau_routine,
            huy=huy_routine,
            # Hỏi theo **phiên**, không theo Routine: một tiếng "dừng lại" không nêu
            # tên, và ràng buộc một-Routine-mỗi-phiên làm câu trả lời đơn trị.
            dang_chay_cua_phien=dang_chay_trong_phien,
        ),
    )
    builder.add_edge("routine", "compose")

    builder.add_edge(START, "normalize")
    builder.add_edge("normalize", "route")
    routing_targets = {
        "validate": "validate",
        "rag": "rag",
        "slm": "slm",
        "compose": "compose",
        "routine": "routine",
    }
    if classifier is not None:
        # Tính vào stage `routing` (last-write-wins đè số ~0 ms của node `route`):
        # với SLM bật, "định tuyến" thật sự tốn chừng này — đúng con số ADR-006 muốn
        # phơi ra. KHÔNG đặt tên stage mới: `record_stage` raise với tên ngoài bảy
        # stage của api_spec.md:342, và đó là lỗi P0 đã lọt qua #232.
        builder.add_node("slm_classify", _timed("routing", classify_stage))
        # Độ trễ sinh chitchat tính vào planning_or_retrieval — cùng lý do.
        builder.add_node("chitchat", _timed("planning_or_retrieval", chitchat_stage))
        builder.add_edge("chitchat", "compose")
        builder.add_conditional_edges(
            "slm_classify",
            _route_after_classify,
            {"slm": "slm", "rag": "rag", "compose": "compose", "chitchat": "chitchat"},
        )
        routing_targets["slm_classify"] = "slm_classify"
    builder.add_conditional_edges("route", _make_route_after_routing(classifier is not None), routing_targets)
    builder.add_conditional_edges("slm", _route_after_slm, {"validate": "validate", "compose": "compose"})
    builder.add_conditional_edges("rag", route_after_rag, {"slm": "slm", "compose": "compose"})
    builder.add_conditional_edges("validate", _route_after_validate, {"safety": "safety", "compose": "compose"})

    # HITL là opt-in. Không truyền `approvals` thì S2 dừng ở `approval_required` rồi
    # sang compose — vẫn KHÔNG thực thi, nên đây không phải lỗ hổng an toàn. Lý do
    # opt-in: graph có checkpointer thì `ainvoke` bắt buộc kèm `thread_id`, mà phần
    # lớn test hiện có gọi không kèm config.
    safety_targets = {"execute": "execute", "compose": "compose"}
    if approvals is not None:
        builder.add_node("approval", make_request_approval_node(gateway, approvals, hitl_timeout_seconds))
        builder.add_conditional_edges("approval", _route_after_approval, {"execute": "execute", "compose": "compose"})
        safety_targets["approval"] = "approval"
    builder.add_conditional_edges("safety", _make_route_after_safety(approvals is not None), safety_targets)
    builder.add_edge("execute", "compose")
    builder.add_edge("compose", END)
    return builder.compile(checkpointer=checkpointer)

"""Định tuyến bằng luật. Không gọi model cho lệnh P0 rõ ràng."""

import logging
import time
from collections.abc import Callable

from src.agents.chon_poi import chon as chon_poi_trong_danh_sach
from src.agents.chon_poi import con_han as danh_sach_con_han
from src.agents.contracts import CandidateActionPlan, CandidateStep
from src.agents.ghep_hoi_lai import CO_THE_GHEP, chap_nhan, con_han, ghep
from src.agents.loi_de_nghi import con_han as de_nghi_con_han
from src.agents.loi_de_nghi import doc_dap_loi_de_nghi
from src.agents.mau_slot import CO_MAU, khop_mau
from src.agents.router import DeterministicControlRouter
from src.agents.routines_intent import con_han_xac_nhan, doc_y_dinh
from src.agents.state import AgentState
from src.agents.voice_intent import doc_tra_loi_co_khong

logger = logging.getLogger(__name__)

#: Kết quả thứ ba của `_ghep_manh_tra_loi`: ghép được theo luật cũ, **nhưng** mảnh mang
#: thêm nội dung ngoài câu trả lời, nên bị rào chắn #363 chặn. Khác `None` (không có gì
#: để ghép, đi đường thường) ở lối ra: ca này phải hỏi lại đúng câu cũ và đóng mic.
KHONG_KHOP_MAU = object()


def _tra_loi_loi_moi_nghe_tiep(state: AgentState, decision) -> str | None:
    """Lượt này có phải lời đáp cho *"Bạn có muốn nghe tiếp nguyên văn không?"* không?

    Trả `"manual_continue"`, `"manual_stop_reading"`, hoặc `None` để đi đường thường.

    ## Vì sao ở node chứ không ở router

    ADR-006/ADR-010 chốt router **tất định và không đọc trạng thái**, và `router.py` đã
    cố ý từ chối nhận `"có"`/`"vâng"` trần vì đúng lý do ấy: không có ngữ cảnh thì một
    tiếng "có" có thể đang duyệt một lệnh mở cửa. Chú thích tại `_CONTINUE_READING` ghi
    rõ điều đó.

    Nhưng ngữ cảnh **có tồn tại** — nó nằm trong `speech_source_text`, tức chỗ đọc dở
    của lượt trước. Node thì đọc được state, router thì không. Nên cổng đặt ở đây: luật
    vẫn thuần, còn quyết định phụ thuộc ngữ cảnh nằm đúng chỗ có ngữ cảnh, giống hệt
    cách cổng phê duyệt nằm ở `turns.py` chứ không nằm trong luật.

    ## Vì sao nó không thể cướp một lượt phê duyệt

    Cổng phê duyệt chạy **trước** graph (`turns.py`). Khi vừa có phê duyệt chờ vừa có
    đoạn đọc dở, tiếng "có" đã bị chặn ở đó và không bao giờ tới đây — đúng thứ tự cần
    có, vì phê duyệt là việc S2 và chỉ sống 30 giây.
    """
    if not state.get("speech_source_text"):
        return None
    # Chỉ xen vào khi luật **không** bắt được gì. `"đọc tiếp"` đã có luật riêng, và một
    # câu khớp luật điều khiển thì không được diễn giải lại thành câu trả lời có/không.
    if decision.disposition != "not_control" or decision.reason == "continue_reading":
        return None
    tra_loi = doc_tra_loi_co_khong(state.get("query", ""))
    if tra_loi is None:
        return None
    return "manual_continue" if tra_loi == "co" else "manual_stop_reading"


def _ghep_manh_tra_loi(state: AgentState, decision, router, bay_gio: float):
    """Lượt này có phải **mảnh trả lời** cho câu hỏi lại của lượt trước không?

    Trả `(cau_da_ghep, decision_moi)` nếu ghép được, `None` để đi đường thường.

    ## Vì sao ở node chứ không ở router — và vì sao ADR-006/ADR-010 không bị đụng

    Cùng lập luận và cùng chỗ đứng với `_tra_loi_loi_moi_nghe_tiep` ngay trên: router
    vẫn **thuần** — nó chỉ được gọi lại với một chuỗi khác — còn quyết định phụ thuộc
    ngữ cảnh nằm ở node, nơi có ngữ cảnh. Không có state nào chui vào `router.py`.

    Khác một điểm phải nói thẳng: cổng "nghe tiếp" chỉ **diễn giải lại** một lượt thành
    hành vi đọc (S0), còn cổng này **dựng lệnh chấp hành** từ ngữ cảnh nhớ được. Vì thế
    nó có bốn chốt, và mỗi chốt sinh ra từ một ca đo thật — xem `src/agents/ghep_hoi_lai.py`.

    ## Bốn chốt

    1. **chỉ lượt kế tiếp ngay sau** — ngữ cảnh bị xoá ở cuối mọi lượt không phải câu
       hỏi lại, nên cách một lượt là không còn gì để ghép;
    2. **TTL** `ghep_hoi_lai.TTL_GIAY` — câu trả lời tới sau nửa phút nhiều khả năng
       đang trả lời chuyện khác;
    3. **không ghép nếu lượt mới tự khớp `control`** — `"mở nhạc"` sau câu hỏi quạt gió
       là một lệnh mới, ghép vào là nuốt mất nó (đo được: ghép ra `clarify`);
    4. **kết quả ghép phải có nghĩa** — `chap_nhan()`, xem docstring của nó.
    """
    goc = (state.get("cho_ghep_text") or "").strip()
    ly_do = (state.get("cho_ghep_ly_do") or "").strip()
    manh = (state.get("query") or "").strip()
    if not goc or not ly_do or not manh:
        return None
    if not con_han(float(state.get("cho_ghep_luc") or 0.0), bay_gio):
        return None
    if decision.disposition == "control":
        return None
    cau = ghep(goc, manh)
    moi = router.route(cau)
    if not chap_nhan(moi.disposition, moi.reason or "", ly_do):
        return None
    # Chốt thứ NĂM, thêm bởi #363 — và nó cố ý đứng **sau** `chap_nhan`, không thay nó.
    #
    # Đặt trước thì một câu hỏi mới hợp lệ sau `clarify` sẽ chết oan: `"Áp suất lốp bao
    # nhiêu"` không khớp mẫu slot cửa sổ, nhưng nó cũng **không** đi đường ghép (đo được:
    # `ghep=False`), nên nó phải rơi xuống đường thường và được trả lời. Đứng sau thì cổng
    # này chỉ soi đúng những mảnh mà luật cũ **đã đồng ý ghép** — tức chỉ siết, không mở
    # thêm và không chặn thêm ai.
    if ly_do in CO_MAU and not khop_mau(ly_do, manh):
        logger.info("mảnh không thuần là câu trả lời cho %s, chặn: %r", ly_do, manh)
        return KHONG_KHOP_MAU
    return cau, moi


def _dap_loi_de_nghi(state: AgentState, decision, bay_gio: float):
    """Lượt này có phải lời đáp cho một **đề nghị** của lượt trước không? (#355, #339)

    Trả `("nhan", plan)` / `("tu_choi", None)`, hoặc `None` để đi đường thường.

    ## Vì sao ở node, và vì sao nó không phải là một cửa an toàn mới

    Cùng chỗ đứng với hai cổng trên: router vẫn thuần, ngữ cảnh nằm ở node. Nhưng điểm
    đáng nói là plan **không** được dựng lại ở đây — nó là đúng object mà router đã dựng
    và validate ở lượt trước, và xe đã **đọc nó ra thành lời** trước khi hỏi. Nên mọi
    cổng phía sau vẫn chạy nguyên: `validate_args`, phân loại S0–S3, và HITL nếu S2.
    Hạ kính vẫn phải duyệt; mở cửa lúc xe chạy vẫn bị chặn. Cơ chế này chỉ trả lời câu
    hỏi *"tài xế vừa nói gì"*, không đụng vào câu hỏi *"có được làm không"*.

    ## Thứ tự với hai cổng kia

    - **Sau** cổng "nghe tiếp": khi vừa có đoạn đọc dở vừa có đề nghị treo, một tiếng
      "có" là mơ hồ thật, và lối ra an toàn là nhánh S0 chỉ đọc thêm sổ tay — không phải
      nhánh chạy một actuator. Fail-closed về phía ít hậu quả hơn.
    - **Trước** cổng ghép mảnh: hai slot loại trừ nhau theo cấu trúc (`clarify` nạp cái
      này, `offer` nạp cái kia), nên thứ tự này không đổi kết quả ca nào. Đặt trước cho
      rẻ, và để nếu ai đó phá tính loại trừ ấy thì ca hỏng lộ ra ở bộ đo đa lượt chứ
      không nằm im.
    """
    plan = state.get("cho_nhan_plan")
    if plan is None:
        return None
    if not de_nghi_con_han(float(state.get("cho_nhan_luc") or 0.0), bay_gio):
        return None
    # Lệnh mới thắng: `"Mở cốp xe"` sau một đề nghị điều hòa là một lệnh, không phải câu
    # trả lời. Nuốt nó vào đây là chạy đúng thứ tài xế **không** vừa nói.
    if decision.disposition == "control":
        return None
    dap = doc_dap_loi_de_nghi(state.get("query", "") or "")
    if dap is None:
        return None
    return (dap, plan if dap == "nhan" else None)


def _dap_xem_truoc_routine(state: AgentState, decision, bay_gio: float):
    """Lượt này có phải lời đáp cho một **preview Routine** của lượt trước không? (#274,
    review PR #401)

    Trả `(dong_y|tu_choi, routine_id)`, hoặc `None` để đi đường thường.

    ## Vì sao ở node, và vì sao đúng lỗ hổng review chỉ ra

    Cùng chỗ đứng với `_dap_loi_de_nghi` ngay trên: router vẫn thuần, không đọc trạng
    thái (ADR-006/010). `routines_intent.doc_y_dinh(..., dang_xem_truoc=True)` đã đọc
    được "đồng ý"/"từ chối" từ #285, nhưng **không ai từng gọi nó với `dang_xem_truoc=True`**
    — router.py chỉ gọi bản mặc định (`dang_xem_truoc=False`) để đọc `ten_tho`. Cổng này là
    chỗ duy nhất có ngữ cảnh (routine nào vừa được `routine_node` phân giải và preview ở
    lượt trước, ghi vào `routine_cho_xac_nhan_id`) để gọi đúng bản `dang_xem_truoc=True`.

    `routine_id` đã phân giải sẵn từ lượt preview — cổng này KHÔNG phân giải lại tên, vì
    lượt này không hề nêu tên nào để phân giải.

    ## Ba chốt, cùng bộ với `_dap_loi_de_nghi`

    1. **chỉ trong cửa sổ TTL** kể từ lúc preview — `con_han_xac_nhan`;
    2. **lệnh mới thắng** — `"Bật điều hòa"` sau một preview là một lệnh, không phải câu
       trả lời;
    3. **`bo_buoc` không được xử lý ở đây** — #274/#285 để "bỏ bước" ngoài phạm vi
       (cần một hợp đồng "chạy với tập bước con" mà làn BE chưa có), nên `y_dinh.loai ==
       "bo_buoc"` rơi qua `None`, đi đường thường như một câu không nhận diện được.
    """
    routine_id = str(state.get("routine_cho_xac_nhan_id") or "")
    if not routine_id:
        return None
    if not con_han_xac_nhan(float(state.get("routine_cho_xac_nhan_luc") or 0.0), bay_gio):
        return None
    if decision.disposition == "control":
        return None
    y_dinh = doc_y_dinh(state.get("query", "") or "", dang_xem_truoc=True)
    if y_dinh is None or y_dinh.loai not in ("dong_y", "tu_choi"):
        return None
    return y_dinh.loai, routine_id


def _xoa_xem_truoc_routine() -> dict:
    """Ngữ cảnh preview Routine cho lượt sau, hoặc phép xoá.

    Khác `_moc_hoi_lai`/`_moc_de_nghi`/`_moc_chon_poi`: `route_node` không bao giờ NẠP
    khe này, chỉ xoá — người nạp duy nhất là `routine_node` (chạy SAU trong cùng lượt,
    khi outcome là `routine_preview`), vì chỉ nó biết `routine_id` đã phân giải. Ghi đè
    của `routine_node` trong cùng lượt luôn thắng phép xoá này, đúng cơ chế state-merge
    LangGraph đã dùng cho `outcome` (route_node đặt `"routine"`, routine_node đặt lại
    thành `"routine_preview"`/...).
    """
    return {"routine_cho_xac_nhan_id": "", "routine_cho_xac_nhan_luc": 0.0}


def _xoa_payload_routine() -> dict:
    """Hai payload có cấu trúc của Routine (`routine_preview`, `routine_setup_required`)
    cho lượt sau, hoặc phép xoá. Áp dụng ở **mọi** lối ra không phải preview/kết quả
    Routine mới — `assistant_response_payload` đọc hai khoá này không gate theo
    `outcome`, nên bất kỳ lối ra sớm nào của `route_node` thiếu phép xoá này đều làm
    payload của MỘT LƯỢT TRƯỚC phát lại kèm `turn_id` mới (review PR #404, ca tái hiện:
    thiếu địa điểm -> "thôi" đi nhánh `giai_tan`).

    KHÔNG áp dụng ở nhánh `xac_nhan_routine`: outcome ở đó là `"routine"`, `routine_node`
    chạy ngay sau trong cùng lượt và LUÔN set lại cả hai khoá này (kể cả về `None`) — cùng
    cơ chế last-write-wins mà `_xoa_xem_truoc_routine` đã dùng.
    """
    return {"routine_preview": None, "routine_setup_required": None}


def _chon_trong_danh_sach(state: AgentState, decision, bay_gio: float):
    """Lượt này có phải một **lựa chọn** trong danh sách xe vừa đọc không? (#355 mục 2b)

    Trả `(poi, plan)` hoặc `None` để đi đường thường.

    ## Vì sao plan dựng ở đây chứ không gọi lại router

    Hai cổng kia không dựng plan: `_ghep_manh_tra_loi` gọi lại router với một chuỗi khác,
    `_dap_loi_de_nghi` dùng lại đúng object router đã dựng ở lượt trước. Ở đây không có
    đường nào như thế — ghép `"đi tới " + tên quán` rồi route lại nghe sạch hơn, nhưng nó
    bắt câu trả lời đi vòng qua bảng alias, tức đúng chỗ bẫy `"thứ hai"` nằm: alias của
    một quán trùng với một số đếm. Danh sách đã nói ra mang sẵn `id`, và dùng thẳng id ấy
    là phép ánh xạ **duy nhất** không thể trỏ nhầm chỗ.

    Đổi lại, node dựng một `CandidateActionPlan` — loại plan **không có** trường an toàn.
    Mọi cổng phía sau vẫn chạy nguyên: `validate_args`, phân loại S0–S3 ở `policy.py`, và
    HITL nếu cần. Cùng ranh giới mà `routines.py` đang đứng.

    ## Ba chốt, cùng bộ với hai cổng kia

    1. **chỉ lượt kế tiếp ngay sau** — `_moc_chon_poi(None, ...)` xoá khe ở mọi lượt
       không đọc danh sách;
    2. **TTL** `chon_poi.TTL_GIAY` — cùng con số với hai cơ chế kia;
    3. **lệnh mới thắng** — `"Bật điều hòa"` sau một danh sách quán là một lệnh, không
       phải một lựa chọn.
    """
    danh_sach = list(state.get("cho_chon_poi") or ())
    if not danh_sach:
        return None
    if not danh_sach_con_han(float(state.get("cho_chon_poi_luc") or 0.0), bay_gio):
        return None
    if decision.disposition == "control":
        return None
    poi = chon_poi_trong_danh_sach(state.get("query", "") or "", danh_sach)
    if poi is None:
        return None
    plan = CandidateActionPlan(
        steps=(
            CandidateStep(
                step_id="step-1",
                ordinal=0,
                tool="set_navigation",
                args={"operation": "start", "destination_id": str(poi["id"])},
            ),
        )
    )
    return poi, plan


#: `Intent` -> ý định `routine_node` hiểu. Đi ngược bảng `_INTENT_ROUTINE` của router:
#: router dịch xuôi để trả một `Intent` hợp lệ, node cần lại đúng ý định ban đầu. Không
#: cho `RouteDecision` mang thẳng ý định thô vì `Intent` là bộ nhãn đóng và là ground
#: truth của bộ đo — thêm một trường song song vào đó là dựng hai nguồn sự thật.
_Y_DINH_THEO_INTENT = {
    "routine_run": "chay",
    "routine_preview": "xem_truoc",
    "routine_cancel": "huy",
}


def _la_cau_giai_tan(state: AgentState, decision) -> bool:
    """Lượt này có phải tài xế **đuổi trợ lý đi** không? Spec §3.3.

    Không có cổng này thì cách duy nhất đóng một cửa sổ nghe tiếp đang mở là **im lặng 6
    giây** — thứ gần như không tới trong xe có người ngồi cạnh đang nói chuyện.

    ## Ba chốt, và cả ba đều là "đừng cướp lượt của cơ chế khác"

    1. **Chỉ khi luật không bắt được gì.** `"thôi tắt nhạc đi"` là một lệnh, không phải
       một câu đuổi — và `doc_tra_loi_co_khong` cũng trả `None` cho nó, nên hai chốt này
       chồng nhau có chủ ý.
    2. **Chỉ khi không có đề nghị treo.** Cổng `_dap_loi_de_nghi` chạy trước và đã biến
       `"thôi"` thành `offer_declined` (#367) — hai lối ra khác nhau, tài xế cần nghe đúng
       câu. (Phê duyệt HITL thì bị chặn từ `turns.py`, còn trước cả graph.)
    3. **Chỉ khi không có preview Routine treo** (#401 review) — cùng lý do và cùng lối
       ra với chốt (2): `_dap_xem_truoc_routine` đã chạy trước và bắt hết trường hợp còn
       trong hạn. Chốt này chỉ còn cần cho ca preview đã **hết hạn** nhưng khe chưa kịp bị
       xoá — coi nó là "không có gì đang treo" thì "thôi" mới rơi đúng xuống đường thường
       thay vì bị đọc nhầm là giải tán trợ lý.
    4. **Chỉ nhận lời đáp thuần**, qua đúng `doc_tra_loi_co_khong` — **không** bảng từ thứ
       hai. Phạm vi hẹp hơn spec §3.3 một cách có chủ ý: `"cảm ơn"` bị bỏ ra vì thêm nó
       vào bảng từ chối là dạy cổng phê duyệt HITL đọc một lời cảm ơn thành một lời **bác**
       một lệnh S2, và vì `"Cảm ơn nhé"` là một ca của `chitchat-v1` — của workstream khác.

    KHÔNG xoá ngữ cảnh hỏi lại: tài xế có thể đổi ý và trả lời ở lượt sau.
    """
    if decision.disposition != "not_control" or decision.reason != "default_to_manual":
        return False
    if state.get("cho_nhan_plan") is not None:
        return False
    if state.get("routine_cho_xac_nhan_id"):
        return False
    return doc_tra_loi_co_khong(state.get("query", "") or "") == "khong"


def make_route_node(router: DeterministicControlRouter, dong_ho: Callable[[], float] = time.monotonic):
    async def route_node(state: AgentState) -> dict:
        decision = router.route(state.get("query", ""))
        # Cổng "nghe tiếp" chạy TRƯỚC, trên quyết định gốc: một tiếng "có" trả lời lời
        # mời đọc tiếp là chuyện S0 và không được đem đi ghép thành lệnh.
        y_dinh_nghe_tiep = _tra_loi_loi_moi_nghe_tiep(state, decision)
        if y_dinh_nghe_tiep is not None:
            return {
                "route_decision": decision,
                "route_source": decision.route_source,
                "intent": y_dinh_nghe_tiep,
                "confidence": decision.confidence,
                "outcome": "not_control",
                "route_reason": "answer_to_read_more_invite",
                **_moc_hoi_lai(None, dong_ho),
                **_moc_de_nghi(None, dong_ho),
                **_moc_chon_poi(None, dong_ho),
                **_xoa_xem_truoc_routine(),
                **_xoa_payload_routine(),
            }
        bay_gio = dong_ho()
        dap = _dap_loi_de_nghi(state, decision, bay_gio)
        if dap is not None:
            kieu, plan = dap
            if kieu == "tu_choi":
                logger.info("tài xế từ chối lời đề nghị: %r", state.get("query", ""))
                return {
                    "route_decision": decision,
                    "route_source": decision.route_source,
                    "intent": "offer_declined",
                    "confidence": decision.confidence,
                    "outcome": "not_control",
                    "route_reason": "offer_declined",
                        **_moc_hoi_lai(None, dong_ho),
                    **_moc_de_nghi(None, dong_ho),
                    **_moc_chon_poi(None, dong_ho),
                    **_xoa_xem_truoc_routine(),
                    **_xoa_payload_routine(),
                }
            logger.info("tài xế nhận lời đề nghị, chạy plan đã nêu ở lượt trước: %r", state.get("query", ""))
            return {
                "route_decision": decision,
                # `route_source` giữ nguồn của plan GỐC (luật), không phải của lượt "có".
                # `policy.py` đọc trường này để quyết `requires_approval`, nên ghi đè nó ở
                # đây là đổi một quyết định an toàn bằng một chi tiết hội thoại.
                "route_source": "deterministic_rule",
                "intent": "none",
                "confidence": decision.confidence,
                "outcome": "control",
                "route_reason": "offer_accepted",
                "candidate_action_plan": plan,
                "da_nhan_de_nghi": True,
                **_moc_hoi_lai(None, dong_ho),
                **_moc_de_nghi(None, dong_ho),
                **_moc_chon_poi(None, dong_ho),
                **_xoa_xem_truoc_routine(),
                **_xoa_payload_routine(),
            }
        xac_nhan_routine = _dap_xem_truoc_routine(state, decision, bay_gio)
        if xac_nhan_routine is not None:
            loai, routine_id = xac_nhan_routine
            intent = "routine_confirm" if loai == "dong_y" else "routine_decline"
            logger.info("tài xế đáp lời preview Routine: %r -> %s (%s)", state.get("query", ""), loai, routine_id)
            return {
                "route_decision": decision,
                # Nguồn là luật: `doc_y_dinh` tất định, và `routine_id` là đúng cái đã
                # phân giải ở lượt preview — không đoán lại gì cả.
                "route_source": "deterministic_rule",
                "intent": intent,
                "confidence": decision.confidence,
                "outcome": "routine",
                "route_reason": f"routine_xem_truoc_{loai}",
                "routine_y_dinh": loai,
                "routine_ten_tho": "",
                "routine_id": routine_id,
                **_moc_hoi_lai(None, dong_ho),
                **_moc_de_nghi(None, dong_ho),
                **_moc_chon_poi(None, dong_ho),
                # KHÔNG xoá ở đây: `routine_node` chạy ngay sau trong cùng lượt và là nơi
                # duy nhất biết chắc phải xoá (dù đồng ý hay từ chối) — đè giá trị của
                # route_node đúng như `outcome` bị đè từ "routine" thành outcome cuối.
            }
        da_chon = _chon_trong_danh_sach(state, decision, bay_gio)
        if da_chon is not None:
            poi, plan = da_chon
            logger.info("chọn địa điểm từ danh sách vừa đọc: %r -> %s", state.get("query", ""), poi.get("id"))
            return {
                "route_decision": decision,
                # Nguồn là luật: danh sách do matcher tất định dựng, và lựa chọn cũng
                # tất định. `policy.py` đọc trường này để quyết `requires_approval`.
                "route_source": "deterministic_rule",
                "intent": "navigation_start",
                "confidence": decision.confidence,
                "outcome": "control",
                "route_reason": "chon_tu_danh_sach_poi",
                "candidate_action_plan": plan,
                "da_chon_tu_danh_sach": True,
                **_moc_hoi_lai(None, dong_ho),
                **_moc_de_nghi(None, dong_ho),
                **_moc_chon_poi(None, dong_ho),
                **_xoa_xem_truoc_routine(),
                **_xoa_payload_routine(),
            }
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
                "da_chon_tu_danh_sach": False,
                # KHÔNG xoá ngữ cảnh hỏi lại: tài xế có thể đổi ý và trả lời ở lượt sau.
                # Chỉ xoá khe đề nghị, vì `"thôi"` khi có đề nghị treo đã bị cổng trên
                # bắt rồi — tới được đây nghĩa là không có đề nghị nào.
                **_moc_de_nghi(None, dong_ho),
                # Cùng lý do: `_dap_xem_truoc_routine` đã bắt hết ca còn hạn ở cổng trên,
                # nên tới đây chỉ còn ca hết hạn — xoá nốt cho sạch.
                **_xoa_xem_truoc_routine(),
                **_xoa_payload_routine(),
            }
        da_ghep = _ghep_manh_tra_loi(state, decision, router, bay_gio)
        if da_ghep is KHONG_KHOP_MAU:
            # KHÔNG xoá ngữ cảnh hỏi lại, và đây là nửa quan trọng của cơ chế: tài xế sắp
            # bấm mic để trả lời lại đúng câu ấy. Xoá đi thì câu trả lời hợp lệ của họ
            # cũng rơi xuống tra sổ tay — ta vừa chặn một lệnh sai để tạo ra một ngõ cụt.
            #
            # Cũng KHÔNG làm mới mốc thời gian: nói lung tung nhiều lần không được phép
            # kéo dài cửa sổ ngữ cảnh vô hạn. TTL vẫn đếm từ câu hỏi gốc.
            return {
                "route_decision": decision,
                "route_source": decision.route_source,
                "intent": "manh_khong_khop_mau",
                "confidence": decision.confidence,
                "outcome": "not_control",
                "route_reason": "manh_khong_khop_mau",
                "da_ghep_hoi_lai": False,
                # Đóng mic: một lần nghe hụt thì trả quyền chủ động về cho tài xế.
                **_moc_de_nghi(None, dong_ho),
                **_xoa_xem_truoc_routine(),
                **_xoa_payload_routine(),
            }
        cau_da_route = state.get("query", "")
        if da_ghep is not None:
            cau_da_route, decision = da_ghep
            logger.info(
                "ghép mảnh trả lời câu hỏi lại: %r -> %s/%s", cau_da_route, decision.disposition, decision.reason
            )
        update = {
            "route_decision": decision,
            "route_source": decision.route_source,
            "intent": decision.intent,
            "confidence": decision.confidence,
            "outcome": decision.disposition,
            "route_reason": decision.reason,
            "da_ghep_hoi_lai": da_ghep is not None,
            # Chuyển tiếp ý định Routine xuống `routine_node` (#274, #299). Ghi ở **mọi**
            # lượt, kể cả lượt không phải Routine — giá trị rỗng khi ấy chính là phép xoá,
            # cùng khuôn với `da_chon_tu_danh_sach` ngay trên. Chỉ ghi ở nhánh Routine thì
            # tên thô của lượt trước sống sót sang lượt sau và xe chạy nhầm Routine.
            "routine_y_dinh": _Y_DINH_THEO_INTENT.get(decision.intent, ""),
            "routine_ten_tho": decision.routine_ten_tho,
            # Ghi/xoá ngữ cảnh ở CUỐI mọi lượt. Phép xoá này chính là chốt "chỉ lượt kế
            # tiếp ngay sau" — không có bộ đếm lượt nào cả.
            "da_nhan_de_nghi": False,
            "da_chon_tu_danh_sach": False,
            **_moc_hoi_lai(
                (cau_da_route, decision.reason or "")
                if decision.disposition == "clarify" and (decision.reason or "") in CO_THE_GHEP
                else None,
                dong_ho,
            ),
            # Cùng chỗ và cùng lẽ: nạp khi lượt này LÀ một đề nghị, xoá ở mọi lượt khác.
            # Phép xoá ấy chính là chốt "chỉ lượt kế tiếp ngay sau".
            **_moc_de_nghi(
                decision.candidate_plan if decision.disposition == "offer" else None,
                dong_ho,
            ),
            # Xoá khe chọn địa điểm ở MỌI lượt thường. `compose_node` nạp lại ngay trong
            # cùng lượt nếu lượt này đọc ra một danh sách — nó chạy sau node này, nên thứ
            # tự xoá-rồi-nạp là đúng chiều. Thiếu dòng này thì khe sống dai qua nhiều
            # lượt và chốt "chỉ lượt kế tiếp ngay sau" mất hiệu lực.
            **_moc_chon_poi(None, dong_ho),
            # Xoá khe preview Routine ở nhánh mặc định này. Khi lượt này THẬT SỰ ra
            # `routine_preview` (`disposition == "routine"`, y_dinh `xem_truoc`), phép
            # xoá này chỉ là giá trị tạm: `routine_node` chạy ngay sau trong cùng lượt và
            # nạp lại `routine_cho_xac_nhan_id` thật, đè đúng chỗ này — cùng cơ chế mà
            # `outcome` bị đè từ `"routine"` thành `"routine_preview"`.
            **_xoa_xem_truoc_routine(),
            **_xoa_payload_routine(),
        }
        if decision.candidate_plan is not None:
            update["candidate_action_plan"] = decision.candidate_plan
        return update

    return route_node


def _moc_hoi_lai(cho: tuple[str, str] | None, dong_ho: Callable[[], float]) -> dict:
    """Ngữ cảnh hỏi lại cho lượt sau, hoặc phép xoá nếu lượt này không hỏi lại gì."""
    if cho is None:
        return {"cho_ghep_text": "", "cho_ghep_ly_do": "", "cho_ghep_luc": 0.0}
    return {"cho_ghep_text": cho[0], "cho_ghep_ly_do": cho[1], "cho_ghep_luc": dong_ho()}


def _moc_chon_poi(danh_sach, dong_ho: Callable[[], float]) -> dict:
    """Danh sách vừa đọc cho lượt sau, hoặc phép xoá nếu lượt này không đọc danh sách nào.

    **Không** nạp ở `route_node` khi lượt này là `poi_search`: lúc node ấy chạy, bước tìm
    kiếm chưa thực thi nên chưa có danh sách nào để nhớ — chỉ có `category`, và nhớ
    `category` rồi tra lại ở lượt sau là dựng lại đúng lớp lỗi #371 vừa gỡ. Việc nạp
    thuộc `compose_node`, nơi danh sách **đã nói ra** có mặt.
    """
    if not danh_sach:
        return {"cho_chon_poi": [], "cho_chon_poi_luc": 0.0}
    return {"cho_chon_poi": list(danh_sach), "cho_chon_poi_luc": dong_ho()}


def _moc_de_nghi(plan, dong_ho: Callable[[], float]) -> dict:
    """Lời đề nghị cho lượt sau, hoặc phép xoá nếu lượt này không đề nghị gì."""
    if plan is None:
        return {"cho_nhan_plan": None, "cho_nhan_luc": 0.0}
    return {"cho_nhan_plan": plan, "cho_nhan_luc": dong_ho()}

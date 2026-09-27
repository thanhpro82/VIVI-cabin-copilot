from __future__ import annotations

from typing import Any, TypedDict

from src.agents.contracts import ActionPlan, CandidateActionPlan, RouteDecision, ToolResult


class AgentState(TypedDict, total=False):
    """State schema cho LangGraph agent.

    `total=False` nên mọi field là optional; node chỉ ghi phần nó sở hữu.
    Nhóm field RAG giữ nguyên tên cũ để `nodes/rag_node.py` không phải sửa.
    """

    # Ngữ cảnh phiên
    query: str
    session_id: str
    vehicle_id: str
    #: Chủ phiên. `routine_node` cần nó để hỏi đúng danh sách Routine của người này.
    #:
    #: Phải khai ở đây, không chỉ đặt vào state lúc `ainvoke`: `AgentState` là TypedDict và
    #: LangGraph **bỏ im lặng** mọi khoá không khai báo. `turns.py` truyền `user_id` vào,
    #: node đọc ra chuỗi rỗng, và fail-closed chạy — không lỗi, không log, chỉ một câu trả
    #: lời sai. Đo end-to-end 30/08 mới thấy; unit test của node tự đặt khoá nên xanh.
    user_id: str
    turn_id: str
    #: Chỉ để quan sát. Node nào cũng có thể đọc, KHÔNG node nào được ghi — nó là
    #: khoá để `src/agents/graph.py` ghi độ trễ stage vào `TraceStore`. Vắng mặt
    #: (test gọi graph trực tiếp) thì phần đo tự tắt, không ảnh hưởng hành vi.
    trace_id: str

    # Định tuyến
    normalized_text: str
    # `| None`: `normalize` dọn các channel dẫn xuất về rỗng ở đầu mỗi lượt, xem
    # `nodes/normalize.py`. LangGraph không xoá được key nên "chưa có" là `None`.
    route_decision: RouteDecision | None
    route_source: str
    route_reason: str
    intent: str
    confidence: float

    # Kế hoạch
    vehicle_snapshot: dict[str, Any]
    vehicle_state_version: int
    candidate_action_plan: CandidateActionPlan | None
    action_plan: ActionPlan | None
    approval_id: str

    # Thực thi và kết quả
    outcome: str
    step_results: list[ToolResult]
    response_text: str
    #: Bản **nói** của câu trả lời, tách khỏi bản hiển thị.
    #:
    #: Phải khai ở đây chứ không chỉ trả từ `compose_node`: `AgentState` là `TypedDict`
    #: và LangGraph **loại bỏ im lặng** mọi khoá không có trong schema. Thiếu dòng này
    #: thì `compose_node` vẫn trả `speak_text` nhưng `graph.ainvoke()` không bao giờ
    #: thấy nó — đúng lỗi tôi vừa mắc: `assistant.speech` vẫn 1.019 KB trong khi test
    #: đơn vị của composer thì xanh.
    speak_text: str
    #: S3 — chỗ đang đọc dở của đoạn sổ tay, để lượt sau "đọc tiếp" nối được.
    #:
    #: Hai field này **cố ý không** nằm trong `_PER_TURN_RESET` của `normalize`:
    #: chúng thuộc về *phiên*, không thuộc về *lượt*. Tài xế hỏi sổ tay, nghe một
    #: đoạn, bảo xe bật điều hoà, rồi nói "đọc tiếp" — chuỗi đó là bình thường
    #: trong xe và phải chạy được.
    #:
    #: Sống nhờ checkpoint LangGraph khoá theo `thread_id = session_id`, nên nó
    #: **chết cùng tiến trình** y như checkpoint giữ `interrupt()` của HITL. Đó là
    #: chủ ý: nó là ngữ cảnh hội thoại, không phải dữ liệu cần bền.
    speech_source_text: str
    speech_da_doc: list[int]
    #: Citation cua doan dang doc do — di theo ĐOẠN, khong theo lượt.
    speech_citations: list[dict[str, Any]]
    #: Ngữ cảnh của câu hỏi lại vừa đặt ra, để lượt sau ghép mảnh trả lời vào
    #: (issue #148). Cùng vòng đời và cùng lý do tồn tại với `speech_source_text`
    #: ngay trên: thuộc về *phiên*, sống nhờ checkpoint, chết cùng tiến trình.
    #:
    #: **Không** nằm trong `_PER_TURN_RESET` — nếu `normalize` dọn thì `route_node`
    #: của chính lượt kế tiếp đã đọc phải chỗ trống. Thay vào đó `route_node` tự
    #: ghi/xoá ở cuối mỗi lượt, và chính phép xoá ấy **là** chốt "chỉ lượt kế tiếp
    #: ngay sau": một lượt không phải câu hỏi lại sẽ quét sạch ngữ cảnh.
    cho_ghep_text: str
    cho_ghep_ly_do: str
    #: `time.monotonic()` lúc đặt câu hỏi lại. `0.0` = không có ngữ cảnh.
    cho_ghep_luc: float
    #: Lượt này có nên cho FE **mở mic ngắn** (3–5 s) để tài xế trả lời ngay không —
    #: #363. Chỉ bật ở lượt `clarify` mà lý do có mẫu ngữ pháp (`mau_slot.CO_MAU`):
    #: không có rào thì không mở cửa. Phơi ra `assistant.response` cùng chỗ và cùng lẽ
    #: với `has_more_to_read` — tín hiệu chỉ nằm ở kênh nói thì client nhìn màn hình
    #: không có gì để hành động.
    #: Lượt này do mic **tự mở** bắt được (`X-Capture-Mode: auto`), hay do tài xế chủ
    #: động bấm mic / nói wake word. Quyết định luật im lặng ở `ivi_events`: bắt tự động
    #: mà xe không hiểu thì **không nói gì** — xem spec §3.5. Chỉ nhánh nói mới đặt nó.
    #:
    #: Đây là thứ **client tự khai**, và tin được vì nó chỉ khiến xe im hơn, không bao
    #: giờ khiến xe dễ dãi hơn. Rào chắn `mau_slot` KHÔNG đọc trường này.
    bat_tu_dong: bool
    mo_mic_ngan: bool
    #: Lời đề nghị (`offer`) đang treo từ lượt trước, chờ một tiếng có/không (#355).
    #: Cùng vòng đời, cùng lý do và cùng cách xoá với `cho_ghep_*` ngay trên — và cũng
    #: **không** nằm trong `_PER_TURN_RESET`, vì cùng một lẽ: `normalize` chạy trước
    #: `route_node` của chính lượt đọc nó.
    #:
    #: Hai slot này **loại trừ nhau theo cấu trúc**, không phải nhờ ai nhớ: `clarify`
    #: nạp `cho_ghep_*`, `offer` nạp `cho_nhan_*`, mọi disposition khác quét sạch cả
    #: hai. Nên không có lượt nào vừa chờ mảnh trả lời vừa chờ một tiếng "có".
    cho_nhan_plan: Any
    #: `time.monotonic()` lúc nêu đề nghị. `0.0` = không có đề nghị nào đang treo.
    cho_nhan_luc: float
    #: Lượt này có phải là một đề nghị vừa được tài xế nhận không — thuần quan sát, để
    #: trace nói được "lệnh này chạy vì tài xế đáp có", cặp với `da_ghep_hoi_lai`.
    da_nhan_de_nghi: bool
    #: --- Routine bằng giọng nói (#274, #299) -------------------------------------
    #: Ý định router đọc được: `"chay"` / `"xem_truoc"` / `"huy"`. Rỗng = lượt không
    #: thuộc lớp Routine. Thuần **trong một lượt**, nên nó KHÔNG cần tránh
    #: `_PER_TURN_RESET` như `cho_ghep_*`/`cho_nhan_*`: router ghi, node đọc, hết lượt.
    routine_y_dinh: str
    #: Tên **chưa phân giải** — đúng chữ tài xế nói. Router không đọc được danh sách
    #: Routine của user (ADR-006/010 cấm nó đọc trạng thái), nên phân giải là việc của
    #: node, cùng chỗ đứng với `ghep_hoi_lai` và `loi_de_nghi`.
    routine_ten_tho: str
    #: Routine đã phân giải, và lần chạy nó sinh ra. Rỗng khi không phân giải được.
    routine_id: str
    routine_execution_id: str
    #: Preview có cấu trúc cho đúng Routine vừa phân giải; API/WS chuyển nguyên hình dạng này cho FE.
    routine_preview: dict[str, Any]
    #: Tên để hỏi lại khi mơ hồ, hoặc để nêu ra khi không thấy. Rỗng ở mọi lượt khác.
    routine_ung_vien: list[str]
    #: Lời từ chối của `bat_dau`, đã soạn sẵn để đọc lên. Rỗng ở mọi lượt khác.
    routine_ly_do: str
    #: Mã máy đọc được của lời từ chối (`chua_dat_dia_diem`, `routine_da_tat`,
    #: `dang_chay_routine_khac`, `routine_khong_ton_tai`). Tách khỏi `routine_ly_do` vì
    #: câu tiếng Việt là để **đọc lên**, còn client thì cần rẽ nhánh (#385).
    routine_ma_loi: str
    #: #385: có cấu trúc CHỈ khi `routine_ma_loi == "chua_dat_dia_diem"` —
    #: `{"routine_id", "ma_loi", "thieu": ["home"|"office", ...]}`. `None` ở ba mã lỗi
    #: còn lại và ở mọi lượt khác: chúng không có màn setup nào để đưa tài xế sang (Routine
    #: tắt/không tồn tại/đang chạy dở không sửa được bằng cách gán địa điểm). Tách khỏi
    #: `routine_ma_loi`/`routine_ly_do` vì FE cần đúng nhãn `thieu` để mở đúng hàng Nhà
    #: hay Cơ quan trong `PlacesPanel`, không phải để đọc lên.
    routine_setup_required: dict[str, Any] | None
    #: Routine vừa được PHÂN GIẢI XONG và xem trước ở lượt trước, chờ tài xế đáp
    #: đồng ý/từ chối ở lượt sau (review PR #401: preview → confirm/reject chưa nối).
    #:
    #: Cùng vòng đời và cùng cách xoá với `cho_nhan_*`/`cho_ghep_*`/`cho_chon_poi_*` ở
    #: trên — và cũng **không** nằm trong `_PER_TURN_RESET` của `normalize`, vì cùng một
    #: lẽ: `route_node` của chính lượt đọc nó chạy trước khi có cơ hội bị dọn.
    #:
    #: Khác `cho_nhan_plan`/`cho_ghep_*`/`cho_chon_poi` ở CHỖ NẠP: ba khe kia được
    #: `route_node` nạp trực tiếp vì router tự dựng được nội dung (plan/chuỗi ghép/danh
    #: sách candidate). Khe này chỉ `routine_node` nạp được, vì chỉ nó biết `routine_id`
    #: đã phân giải — router không đọc danh sách Routine của user (ADR-006/010).
    #: `route_node` chỉ có nhiệm vụ XOÁ nó ở mọi lượt không phải preview thành công.
    routine_cho_xac_nhan_id: str
    #: `time.monotonic()` lúc preview thành công. `0.0` = không có preview nào đang treo.
    routine_cho_xac_nhan_luc: float
    #: Danh sách địa điểm xe **vừa đọc ra** ở lượt trước, để lượt sau chọn được bằng
    #: *"cái đầu tiên"* / *"chỗ gần nhất"* / một cái tên (#355 mục 2b).
    #:
    #: Cùng vòng đời và cùng cách xoá với `cho_ghep_*` và `cho_nhan_*`: nạp khi lượt này
    #: đọc danh sách, xoá ở mọi lượt khác — phép xoá ấy **là** chốt "chỉ lượt kế tiếp
    #: ngay sau".
    #:
    #: Nhớ đúng **danh sách đã nói ra**, không phải loại địa điểm: nhớ `category` rồi tra
    #: lại fixture ở lượt sau là dựng lại đúng lớp lỗi mà #371 vừa gỡ — câu nói và dữ
    #: liệu đi hai đường rồi lệch nhau. Ba mục là trần của `POI_TRAN_DOC`.
    cho_chon_poi: list[dict[str, Any]]
    cho_chon_poi_luc: float
    #: Chỉ để quan sát: lượt này có phải một lựa chọn từ danh sách không (trace/eval).
    da_chon_tu_danh_sach: bool
    #: Lượt này có phải kết quả của một phép ghép không — thuần quan sát, để trace
    #: và log nói được "xe hiểu câu này nhờ nhớ lượt trước".
    da_ghep_hoi_lai: bool
    #: Còn phần dư để đọc tiếp không. Phơi ra `assistant.response` để FE render
    #: được nút — lời mời chỉ nằm ở kênh nói, người nhìn màn hình không thấy.
    has_more_to_read: bool
    #: Reply của vai trò trò chuyện (ADR-016) — chỉ `slm_stage` ghi, compose đọc.
    chitchat_reply: str
    #: SP-2: tên lớp cổng vỡ, hoặc `qua` / `loi` — để eval và trace đếm được.
    chitchat_cong: str
    grounded_lead_in: str
    error: str
    error_subcode: str

    # RAG sổ tay xe (giữ nguyên contract cũ)
    context: str
    analysis: str
    response: str
    metadata: dict
    evidence: list
    citations: list
    refusal_reason: str


#: `outcome` cuối cùng mà lượt nào KHÔNG được phát `assistant.status(state="composing")`
#: — khớp đúng các nhánh return-sớm của `emit_turn_lifecycle` (turn có action_plan:
#: đã thực thi, bị chặn, hoặc kết thúc bằng quyết định phê duyệt). Đây là danh sách
#: LOẠI TRỪ, không phải danh sách cho phép: mọi outcome khác (tra sổ tay, chitchat,
#: clarify...) đều rơi vào nhánh cuối cùng của `emit_turn_lifecycle`, nơi "composing"
#: luôn được phát.
#:
#: `graph.py` đọc set này để quyết định có phát "composing" NGAY khi node `compose`
#: bắt đầu chạy hay không (issue: bắn assistant.status theo thời gian thực thay vì
#: hồi tố sau khi `graph.ainvoke()` đã trả về) — và `src.services.ivi_events` đọc
#: CÙNG set này để biết khi nào bỏ qua bản phát hồi tố (tránh phát trùng lặp qua
#: `composing_already_announced`). Một nguồn duy nhất: hai nơi rẽ nhánh theo đúng
#: cùng một tập outcome sẽ không bao giờ lệch nhau.
NO_COMPOSING_STATUS_OUTCOMES = frozenset(
    {
        "completed",
        "execution_failed",
        "blocked",
        "vehicle_state_unavailable",
        "approval_rejected",
        "approval_expired",
        "approval_invalidated_state",
        "approval_invalidated_plan",
        "approval_predicate_failed",
        "approval_not_owned",
    }
)

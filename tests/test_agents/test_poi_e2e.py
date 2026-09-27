"""Lượt 9 của kịch bản demo, đi trọn từ câu nói tới kế hoạch đã thực thi.

Không có model nào trong đường này: matcher là luật tất định, nên test chạy được
trên mọi máy kể cả CI không có llama-server.
"""

from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway


async def _hoi(text: str) -> dict:
    graph = build_graph(InProcessVehicleGateway.new())
    return await graph.ainvoke({"query": text, "session_id": "s", "vehicle_id": "v", "turn_id": "t"})


async def test_luot_9_cua_kich_ban_chay_tron():
    r = await _hoi("Tìm quán cà phê gần đây rồi dẫn đường tới đó")
    assert r["outcome"] == "completed", r
    noi = r.get("speak_text") or r["response_text"]
    assert "Cà phê Bình Minh" in noi
    assert "3,65 km" in noi  # gia tri that trong fixture la 3.65, khong phai 3.6
    assert "đã chỉ đường" in noi.lower()
    # Lối thoát — điều kiện kèm theo của spec SP-5 §2.1, không phải trang trí.
    assert "chỗ khác" in noi.lower()


async def test_so_it_don_gian_cung_chay():
    r = await _hoi("Tìm quán cà phê gần đây")
    assert r["outcome"] == "completed"
    assert "Cà phê Bình Minh" in (r.get("speak_text") or r["response_text"])


async def test_so_nhieu_doc_danh_sach_va_khong_dat_dan_duong():
    r = await _hoi("Tìm các quán cà phê gần đây")
    noi = r.get("speak_text") or r["response_text"]
    # `outcome` là dòng mà bản đầu của test này BỎ TRỐNG, và đó là lý do #371 sống sót
    # qua CI: hai test nhánh số ít đều assert `completed`, riêng nhánh số nhiều chỉ kiểm
    # câu chữ — nên lượt mang `validation_denied` mà vẫn đọc danh sách không ai thấy.
    assert r["outcome"] == "completed", r
    assert "Bạn muốn đi chỗ nào?" in noi
    assert "đã chỉ đường" not in noi.lower()
    assert "Highlands" in noi


async def test_buoc_tim_poi_chay_that_va_mang_danh_sach_ve():
    """Danh sách phải tới từ **kết quả thực thi**, không từ một phép tra song song.

    Đây là điều kiện cấu trúc của bản vá: còn một đường nào dựng câu mà không cần bước
    chạy thì lớp lỗi #371 dựng lại được ở chỗ khác.
    """
    r = await _hoi("Tìm các quán cà phê gần đây")

    ket_qua = [kq for kq in r["step_results"] if kq.tool == "search_nearby_poi"]
    assert len(ket_qua) == 1
    assert ket_qua[0].status == "completed"
    ten = [item["name"] for item in ket_qua[0].after["items"]]
    assert "Cà phê Bình Minh" in ten
    assert all(ten_poi in (r.get("speak_text") or r["response_text"]) for ten_poi in ten)


async def test_cau_hoi_so_tay_khong_bi_bat_thanh_lenh_tim():
    """Ô cổng cứng `manual→control` — matcher POI là đường mới duy nhất phá được nó."""
    r = await _hoi("Tìm hiểu về áp suất lốp")
    assert r["outcome"] != "completed"


# --- tính chất, không phải ca cụ thể (issue #371) ----------------------------


async def test_luot_hong_khong_bao_gio_doc_ra_mot_cau_hoi_lai():
    """Một lượt kết thúc hỏng **không được** nói như thể nó vừa làm xong và mời tiếp.

    Khoá theo **tính chất** chứ không theo ca, vì lớp lỗi này đã xuất hiện hai lần ở hai
    chỗ khác nhau: #338 (đề nghị hạ kính cho một lượt S3 bị chặn — @thanhpro82 bác) và
    #371 (đọc danh sách POI cho một lượt `validation_denied`). Nhớ từng chỗ thì lần thứ
    ba nó lại mọc ở chỗ mới.

    Ca dựng ở đây là ca nguy hiểm nhất: `intent` nói *"đây là lượt tìm POI"* trong khi
    `outcome` nói *"lượt này hỏng"*. Composer phải nghe `outcome`.
    """
    from src.agents.contracts import CandidateActionPlan, CandidateStep
    from src.agents.nodes.compose import compose_node

    # `candidate_action_plan` **phải** có mặt: đó là state thật của lượt hỏng — router đã
    # dựng plan, plan chết ở `validate_args`. Bỏ nó đi thì bản cũ (tra fixture theo
    # `category` lấy từ plan) cũng không đọc được gì, và test hoá ra không canh gì cả.
    ke_hoach = CandidateActionPlan(
        steps=(CandidateStep(step_id="step-1", ordinal=0, tool="search_nearby_poi", args={"category": "cafe"}),)
    )

    for outcome in ("validation_denied", "blocked", "vehicle_state_unavailable", "execution_failed"):
        ket = await compose_node(
            {
                "intent": "poi_search",
                "outcome": outcome,
                "query": "Tìm các quán cà phê gần đây",
                "candidate_action_plan": ke_hoach,
                # Không có `step_results`: bước tìm kiếm chưa từng chạy.
            }
        )
        noi = ket.get("speak_text") or ket["response_text"]
        assert "Bạn muốn đi chỗ nào?" not in noi, (outcome, noi)
        assert "Tôi tìm được" not in noi, (outcome, noi)


async def test_buoc_tim_poi_hong_thi_cung_khong_doc_danh_sach():
    """Bước có chạy nhưng **hỏng** cũng không được đọc ra danh sách — `None` của
    `_poi_da_tim_duoc` gộp hai ca ấy vì người gọi làm cùng một việc với cả hai."""
    from src.agents.contracts import ToolResult
    from src.agents.nodes.compose import compose_node

    ket = await compose_node(
        {
            "intent": "poi_search",
            "outcome": "execution_failed",
            "step_results": [
                ToolResult(
                    command_id="c",
                    step_id="step-1",
                    tool="search_nearby_poi",
                    args={"category": "cafe"},
                    status="failed",
                    before={},
                    after={},
                    observed_state_version=1,
                    error_code="actuator_error",
                )
            ],
        }
    )

    assert "Bạn muốn đi chỗ nào?" not in (ket.get("speak_text") or ket["response_text"])

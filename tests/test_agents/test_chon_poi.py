"""Chọn địa điểm trong danh sách vừa đọc (#355 mục 2b).

Hai tầng, đúng như cấu trúc của cơ chế: phần thuần (`src/agents/chon_poi.py`) và cổng ở
node, đo qua graph thật.
"""

import pytest

from src.agents.chon_poi import TTL_GIAY, chon, con_han
from src.agents.graph import build_graph
from src.services.vehicle_gateway import InProcessVehicleGateway

#: Đúng thứ tự mà `tim_poi_theo_loai("cafe")` trả ra — gần nhất trước. Viết tay ở đây để
#: test đọc được: cái nằm ĐẦU danh sách là Bình Minh, còn `"thứ hai"` là alias của **chính
#: nó**. Toàn bộ nhóm test bẫy alias xoay quanh sự trùng ấy.
_DANH_SACH = [
    {"id": "poi-cafe-02", "name": "Cà phê Bình Minh", "aliases": ["bình minh", "thứ hai"], "distance_km": 3.65},
    {"id": "poi-cafe-01", "name": "Highlands Coffee Nguyễn Trãi", "aliases": ["highlands"], "distance_km": 5.6},
]


# --- phần thuần: thứ tự thắng alias -----------------------------------------


@pytest.mark.parametrize(
    ("cau", "mong_doi"),
    [
        ("cái đầu tiên", "poi-cafe-02"),
        ("chỗ đầu", "poi-cafe-02"),
        ("cái thứ nhất", "poi-cafe-02"),
        ("chỗ thứ hai", "poi-cafe-01"),
        ("cái thứ 2", "poi-cafe-01"),
        ("chỗ cuối cùng", "poi-cafe-01"),
        ("chỗ gần nhất", "poi-cafe-02"),
        ("chỗ xa nhất", "poi-cafe-01"),
    ],
)
def test_so_thu_tu_va_so_sanh(cau, mong_doi):
    assert chon(cau, _DANH_SACH)["id"] == mong_doi


def test_thu_hai_la_so_dem_chu_khong_phai_ten_quan():
    """Bẫy nằm sẵn trong dữ liệu: `"thứ hai"` là alias thật của `poi-cafe-02`.

    Trong danh sách này Bình Minh đứng **đầu**, nên nếu khớp alias trước thì *"chỗ thứ
    hai"* sẽ dẫn tới đúng chỗ tài xế vừa không chọn. Người nói "thứ hai" đang đếm những
    cái tên họ vừa nghe.
    """
    assert chon("chỗ thứ hai", _DANH_SACH)["id"] == "poi-cafe-01"
    # Còn gọi thẳng tên thì vẫn ra Bình Minh — alias không bị vô hiệu, chỉ bị xếp sau.
    assert chon("bình minh", _DANH_SACH)["id"] == "poi-cafe-02"


@pytest.mark.parametrize("cau", ["highlands", "quán Highlands Coffee", "cho tôi tới highlands"])
def test_goi_theo_ten_hoac_alias(cau):
    assert chon(cau, _DANH_SACH)["id"] == "poi-cafe-01"


@pytest.mark.parametrize("cau", ["ừ", "cái kia", "chỗ nào cũng được", "mai tính", "chỗ thứ tư"])
def test_khong_khop_thi_khong_chon_bua(cau):
    """Fail hướng bỏ sót. Đoán ở đây là chở tài xế tới chỗ họ không bảo, qua một tool S1
    không ai duyệt. `"chỗ thứ tư"` nằm ngoài danh sách hai mục — hứa một thứ không có."""
    assert chon(cau, _DANH_SACH) is None


def test_khop_nhieu_muc_thi_tra_none():
    """Hai mục cùng khớp nghĩa là câu nói không phân biệt được chúng."""
    mo_ho = [
        {"id": "a", "name": "Quán Cà Phê Số 1", "aliases": ["cà phê"], "distance_km": 1.0},
        {"id": "b", "name": "Quán Cà Phê Số 2", "aliases": ["cà phê"], "distance_km": 2.0},
    ]
    assert chon("cà phê", mo_ho) is None


def test_danh_sach_rong_khong_chon_gi():
    assert chon("cái đầu tiên", []) is None


# --- TTL ---------------------------------------------------------------------


def test_con_han_cung_nguong_voi_hai_co_che_kia():
    assert con_han(100.0, 100.0 + TTL_GIAY) is True
    assert con_han(100.0, 100.0 + TTL_GIAY + 0.1) is False


def test_khong_co_danh_sach_hoac_dong_ho_chay_lui_thi_het_han():
    assert con_han(0.0, 10.0) is False
    assert con_han(100.0, 90.0) is False


# --- cổng ở node, đo qua graph thật -----------------------------------------


async def _hai_luot(cau_2: str, *, cau_1: str = "Quanh đây có mấy quán cà phê") -> tuple[dict, dict]:
    graph = build_graph(InProcessVehicleGateway.new())
    luot_1 = await graph.ainvoke({"query": cau_1, "session_id": "s", "vehicle_id": "v", "turn_id": "t1"})
    luot_2 = await graph.ainvoke({**luot_1, "query": cau_2, "turn_id": "t2"})
    return luot_1, luot_2


def _dich(ket_qua: dict) -> str | None:
    plan = ket_qua.get("action_plan") or ket_qua.get("candidate_action_plan")
    return plan.steps[0].args.get("destination_id") if plan and plan.steps else None


async def test_luot_doc_danh_sach_ghi_lai_dung_thu_da_noi_ra():
    """Khe nhớ **danh sách**, không nhớ `category`.

    Nhớ loại rồi tra lại fixture ở lượt sau là dựng lại đúng lớp lỗi #371: câu nói và dữ
    liệu đi hai đường, rồi lệch nhau.
    """
    luot_1, _ = await _hai_luot("Cái đầu tiên")

    assert [p["id"] for p in luot_1["cho_chon_poi"]] == ["poi-cafe-02", "poi-cafe-01"]
    assert luot_1["cho_chon_poi_luc"] > 0


@pytest.mark.parametrize(
    ("cau", "mong_doi"),
    [
        ("Cái đầu tiên", "poi-cafe-02"),
        ("Chỗ thứ hai", "poi-cafe-01"),
        ("Highlands", "poi-cafe-01"),
        ("Chỗ gần nhất", "poi-cafe-02"),
    ],
)
async def test_bon_cach_tra_loi_deu_dan_duong_dung_cho(cau, mong_doi):
    """Bốn câu này trước #355 mục 2b đều rơi xuống tra sổ tay (đo 28/08)."""
    _, luot_2 = await _hai_luot(cau)

    assert luot_2["outcome"] == "completed"
    assert luot_2["route_reason"] == "chon_tu_danh_sach_poi"
    assert _dich(luot_2) == mong_doi


async def test_lenh_moi_thang_lua_chon():
    """`"Bật điều hòa"` sau một danh sách quán là một **lệnh**, không phải câu trả lời."""
    _, luot_2 = await _hai_luot("Bật điều hòa")

    assert luot_2["route_reason"] != "chon_tu_danh_sach_poi"
    assert luot_2["da_chon_tu_danh_sach"] is False


async def test_cau_khong_lien_quan_khong_bi_nuot_thanh_lua_chon():
    _, luot_2 = await _hai_luot("Áp suất lốp tiêu chuẩn là bao nhiêu")

    assert luot_2["route_reason"] != "chon_tu_danh_sach_poi"


async def test_khe_bi_xoa_sau_mot_luot_khac_nen_khong_chon_duoc_o_luot_thu_ba():
    """Chốt "chỉ lượt kế tiếp ngay sau" — không có bộ đếm lượt, chỉ có phép xoá.

    Ba lượt: đọc danh sách → hỏi sổ tay → *"cái đầu tiên"*. Lượt cuối không được dẫn
    đường: người vừa nói chuyện khác, và cái "đầu tiên" ấy có thể đang trỏ vào thứ khác
    trong đầu họ.
    """
    graph = build_graph(InProcessVehicleGateway.new())
    luot_1 = await graph.ainvoke(
        {"query": "Quanh đây có mấy quán cà phê", "session_id": "s", "vehicle_id": "v", "turn_id": "t1"}
    )
    luot_2 = await graph.ainvoke({**luot_1, "query": "Áp suất lốp tiêu chuẩn là bao nhiêu", "turn_id": "t2"})
    assert luot_2["cho_chon_poi"] == []

    luot_3 = await graph.ainvoke({**luot_2, "query": "Cái đầu tiên", "turn_id": "t3"})

    assert luot_3["route_reason"] != "chon_tu_danh_sach_poi"
    assert _dich(luot_3) is None


async def test_het_ttl_thi_khong_chon_nua():
    graph = build_graph(InProcessVehicleGateway.new())
    luot_1 = await graph.ainvoke(
        {"query": "Quanh đây có mấy quán cà phê", "session_id": "s", "vehicle_id": "v", "turn_id": "t1"}
    )

    qua_han = {**luot_1, "cho_chon_poi_luc": luot_1["cho_chon_poi_luc"] - TTL_GIAY - 1.0}
    luot_2 = await graph.ainvoke({**qua_han, "query": "Cái đầu tiên", "turn_id": "t2"})

    assert luot_2["route_reason"] != "chon_tu_danh_sach_poi"


async def test_lua_chon_van_di_qua_policy_va_ra_plan_hop_le():
    """Cổng này trả lời *"tài xế vừa nói gì"*, không đụng *"có được làm không"*.

    `set_navigation` là S1 nên nó chạy — nhưng plan vẫn phải là plan đã qua
    `materialize_action_plan`, tức có `safety_level`, không phải một object node tự dựng
    rồi đẩy thẳng xuống executor.
    """
    _, luot_2 = await _hai_luot("Cái đầu tiên")

    plan = luot_2["action_plan"]
    assert plan.steps[0].safety_level == "S1"
    assert plan.steps[0].tool == "set_navigation"
    assert luot_2["da_chon_tu_danh_sach"] is True

"""Đ7 — tự sửa lời trong cùng một lượt.

Đo được trước thay đổi này, cả ba đều **thực thi đúng cái vừa bị rút lại**:

```
'bật nhạc không tắt đi'              → media play        (vế BỊ HUỶ)
'bật điều hòa à thôi'                → set_hvac_power on (vế BỊ HUỶ)
'đặt âm lượng 70 không 40 phần trăm' → set_volume 70     (số CŨ)
```

Đây là lớp lỗi KI-001 ở dạng khó chịu nhất: hệ nghe **đủ** câu nhưng làm theo nửa đầu,
đúng nửa mà người nói vừa bảo là không phải.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.approval import ApprovalStore
from src.agents.graph import build_graph
from src.agents.question import DAU_SUA_LOI, NEO_SO_KHONG
from src.agents.router import DeterministicControlRouter
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict

router = DeterministicControlRouter()


def _buoc(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


# ---- Ba ca của issue ------------------------------------------------------


def test_ve_bi_rut_lai_khong_duoc_thuc_thi():
    d, buoc = _buoc("Bật nhạc, không, tắt đi")
    assert d.disposition == "control", d
    assert buoc == [("media_control", {"action": "pause"})], "phải là vế PHẢI (tắt), không phải bật"


def test_so_moi_thang_so_cu():
    d, buoc = _buoc("Đặt âm lượng 70, không, 40 phần trăm")
    assert buoc == [("media_control", {"action": "set_volume", "volume": 40})]


def test_rut_lai_ma_khong_noi_lai_thi_khong_lam_gi_va_noi_ra():
    """`"bật điều hòa à thôi"` — không có vế phải.

    `clarify` chứ không phải `not_control`: để lượt rơi xuống sổ tay thì tài xế nhận
    một đoạn hướng dẫn bật điều hòa cho đúng cái việc họ vừa huỷ.
    """
    d, buoc = _buoc("Bật điều hòa à thôi")
    assert d.disposition == "clarify"
    assert d.reason == "tu_sua_loi_khong_con_lenh"
    assert buoc == []


# ---- Ba đường thừa hưởng đích ---------------------------------------------


@pytest.mark.parametrize(
    ("text", "buoc_mong_doi"),
    [
        # 1. vế phải tự khớp
        ("Bật nhạc, à thôi, tắt điều hòa", [("set_hvac_power", {"enabled": False})]),
        # 2. vế phải có động từ, thiếu đối tượng
        ("Bật nhạc, không, tắt đi", [("media_control", {"action": "pause"})]),
        # 3. vế phải chỉ có giá trị — mượn cả cụm động từ + đối tượng
        (
            "Mở cửa sổ bên lái 50 phần trăm, không, 30 phần trăm",
            [("set_window_position", {"window": "front_left", "percent": 30})],
        ),
        ("Đặt điều hòa 25 độ, nhầm, 22 độ", [("set_hvac_temperature", {"temperature_c": 22})]),
    ],
)
def test_ba_duong_thua_huong(text, buoc_mong_doi):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == buoc_mong_doi


def test_so_cu_bi_bo_khi_muon_cum_cua_ve_trai():
    """Đường 3 phải **bỏ số cũ** trước khi ghép.

    Giữ lại thì câu ghép có hai con số và `_number` nhặt cái đầu — tức là đúng con số
    vừa bị rút lại. Test này là chỗ duy nhất phân biệt "ghép đúng" với "ghép cho có".
    """
    _, buoc = _buoc("Đặt âm lượng 70, không, 40 phần trăm")
    assert buoc[0][1]["volume"] == 40


# ---- Luật neo: `không` là số 0, không phải dấu rút lại --------------------


def test_khong_co_neo_thi_van_la_so_0():
    """`NEO_SO_KHONG` (PR #268) được **dùng lại nguyên vẹn**, không chép bản thứ hai.

    Đây là nghĩa **thứ tư** của chữ `không` trong router (phủ định, tiểu từ nghi vấn,
    số 0, dấu rút lại). Bỏ điều kiện neo là biến mọi lệnh `"về không"` thành câu sửa lời.
    """
    assert "không" in DAU_SUA_LOI
    assert "mức" in NEO_SO_KHONG
    d, buoc = _buoc("Đặt quạt gió mức không")
    assert d.disposition == "control", d
    assert buoc == [("set_hvac_fan_level", {"level": 0})]


@pytest.mark.parametrize("neo", sorted(NEO_SO_KHONG))
def test_moi_tu_neo_deu_giu_nghia_so_0(neo):
    """Duyệt thẳng `NEO_SO_KHONG` thay vì chép danh sách ra đây.

    Bản đầu chép bảy từ (`mức về bằng đến tới còn là`) — đúng với nhánh lúc viết, sai
    với `develop` sau #268, nơi sáu từ bị loại vì gây hại đo được. Chép bảng ra test là
    dựng một bản sao thứ hai sẽ lệch đúng vào ngày bảng gốc đổi.
    """
    d, _ = _buoc(f"Đặt quạt gió {neo} không")
    assert d.disposition == "control", d


# ---- Không cướp câu thường ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Bật điều hòa",
        "Tắt nhạc",
        "Đặt âm lượng 40 phần trăm",
        "Xe có chạy được khi hết pin không?",
        "Điều hòa có lọc bụi mịn không?",
    ],
)
def test_cau_khong_sua_loi_thi_khong_doi(text):
    """Dấu rút lại nằm **giữa** câu và phải có vế trái tự khớp; câu hỏi kết thúc bằng
    `không` không có vế phải nào để chuyển sang."""
    truoc = router.route(text)
    assert truoc.reason != "tu_sua_loi_khong_con_lenh"


@pytest.mark.parametrize(
    ("text", "cho_doi"),
    [
        ("Bật nhạc không nghe rõ", [("media_control", {"action": "play"})]),
        ("Bật điều hòa không cần mạnh", [("set_hvac_power", {"enabled": True})]),
        ("Bật đèn trần không sáng lắm", [("set_interior_light", {"enabled": True})]),
        (
            "Mở cửa sổ bên lái 30 phần trăm không đủ",
            [("set_window_position", {"window": "front_left", "percent": 30})],
        ),
    ],
)
def test_khong_o_giua_cau_binh_thuong_khong_bi_doc_thanh_dau_rut_lai(text, cho_doi):
    """Điều kiện approve #1 của review #315.

    Ba câu đầu là ví dụ Thành nêu thẳng. Chúng có `"không"` ở giữa nhưng không phải câu
    sửa lời — chúng là phủ định/bình luận. Ranh giới nằm ở `DAU_SUA_LOI_RO`: `"không"`
    trần không đủ tin cậy để kích hoạt nhánh fail-closed, nên khi vế phải không dựng
    được thành lệnh thì câu đi tiếp đúng đường cũ.

    Khoá **bước cụ thể**, không chỉ khoá `disposition`: một `clarify` ở đây cũng là hồi
    quy (hỏi lại một câu đã rõ nghĩa), và `assert disposition == "control"` một mình
    không bắt được việc plan đổi sang một đích khác.
    """
    d, buoc = _buoc(text)
    assert d.disposition == "control", f"{text!r} → {d.disposition}/{d.reason}"
    assert buoc == cho_doi


@pytest.mark.parametrize(
    "text",
    [
        "Mở cửa sổ không được",
        "Bật sưởi ghế không biết mức nào",
    ],
)
def test_khong_o_giua_cau_van_giu_nguyen_ly_do_cu(text):
    """Cùng điều kiện #1, nhưng cho câu mà develop **đã** hỏi lại sẵn.

    `"mở cửa sổ không được"` ra `missing_window_side` trên develop. Nhánh sửa lời không
    được đổi lý do ấy sang `tu_sua_loi_*`: hai câu hỏi lại khác hẳn nhau, và câu của
    nhánh sửa lời không nêu được slot nào đang thiếu.
    """
    d, buoc = _buoc(text)
    assert not d.reason.startswith("tu_sua_loi"), f"{text!r} → {d.reason}"
    assert buoc == []


# ---- Fail-closed: có dấu rút lại nhưng không dựng được vế phải ------------


@pytest.mark.parametrize(
    "text",
    [
        "Bật điều hòa à thôi cái kia",
        "Mở cửa sổ bên lái 30 phần trăm à quên ừ",
        "Bật nhạc nhầm rồi ờ",
    ],
)
def test_co_dau_rut_lai_ma_ve_phai_khong_doc_duoc_thi_hoi_lai_chu_khong_lam_ve_trai(text):
    """Điều kiện approve #2 của review #315 — và lỗ này rộng hơn báo cáo.

    Bản đầu trả `None` ở nhánh này, mà `None` không trung tính: `_match` đi tiếp xuống
    `_run_matchers(text)` và khớp **cả câu**, tức thực thi đúng vế vừa bị rút lại.

    `"bật điều hòa à thôi cái kia"` còn lọt qua theo đường thứ hai: đường 3 của
    `_ung_vien_ve_phai` dựng ra `"bật điều hòa cái kia"`, khớp `set_hvac_power on` —
    lại chính vế trái, chỉ đi vòng. Nên ứng viên nào cho kết quả **giống hệt** vế trái
    đều bị loại.
    """
    d, buoc = _buoc(text)
    assert d.disposition == "clarify", f"{text!r} → {d.disposition}/{d.reason}"
    assert d.reason == "tu_sua_loi_khong_doc_duoc"
    assert buoc == []
    assert d.candidate_plan is None


def test_tat_nhac_gio_la_lenh_va_do_la_mot_lo_rieng():
    """`"tắt nhạc"` — cách nói tự nhiên nhất để dừng — rơi xuống sổ tay trên develop,
    trong khi `"dừng nhạc"` chạy. Lỗ này lộ ra khi làm ca "bật nhạc, không, tắt đi",
    và nó độc lập với việc sửa lời."""
    d, buoc = _buoc("Tắt nhạc")
    assert d.disposition == "control", d
    assert buoc == [("media_control", {"action": "pause"})]


# ---- Trọn đường -----------------------------------------------------------


async def _chay(vehicle, text):
    graph = build_graph(vehicle)
    return await graph.ainvoke({"query": text, "session_id": "ses-1", "vehicle_id": "veh-1", "turn_id": "turn-1"})


async def test_e2e_rut_lai_thi_khong_mot_lenh_nao_roi_khoi_backend():
    vehicle = InProcessVehicleGateway.new()
    truoc = snapshot_dict(vehicle.state)

    kq = await _chay(vehicle, "Bật điều hòa à thôi")

    assert kq["outcome"] == "clarify"
    assert vehicle.command_count == 0
    # So với trạng thái TRƯỚC lượt chứ không so với một giá trị đoán trước: mặc định
    # của simulator không phải chuyện test này nói về.
    assert snapshot_dict(vehicle.state) == truoc
    assert "chưa thực hiện gì" in kq["response_text"]


@pytest.mark.parametrize(
    "text",
    [
        # Rút lại rồi im — không nói lại gì.
        "Mở cửa sổ bên lái 30 phần trăm à thôi",
        # Rút lại rồi nói một vế không dựng được thành lệnh.
        "Mở cửa sổ bên lái 30 phần trăm à quên ừ",
    ],
)
async def test_e2e_lenh_s2_bi_rut_lai_khong_tao_approval_khong_ra_lenh(text):
    """Điều kiện approve #3 của review #315.

    `set_window_position` là S2 **luôn luôn** (`docs/safety_and_hitl.md`), nên đây là
    ca duy nhất chứng minh được điều Thành hỏi: một lệnh cần phê duyệt bị rút lại thì
    không được để lại approval treo. Test E2E cũ dùng `"bật điều hòa"` — S1 — nên nó
    không bao giờ đi qua tầng approval và không nói được gì về nhánh này.

    Ba thứ phải cùng đúng: không approval nào trong store, `command_count == 0`, và
    trạng thái xe so với **trước lượt** chứ không so với một hằng số đoán trước.
    """
    vehicle = InProcessVehicleGateway.new()
    store = ApprovalStore()
    truoc = snapshot_dict(vehicle.state)

    graph = build_graph(vehicle, approvals=store, checkpointer=InMemorySaver())
    kq = await graph.ainvoke(
        {"query": text, "session_id": "ses-315", "vehicle_id": "veh-1", "turn_id": "turn-315"},
        config={"configurable": {"thread_id": "ses-315"}},
    )

    assert kq["outcome"] == "clarify", kq["outcome"]
    assert "__interrupt__" not in kq
    assert store.pending_for_session("ses-315") is None
    assert store.record_count == 0
    assert vehicle.command_count == 0
    assert snapshot_dict(vehicle.state) == truoc

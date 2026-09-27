"""Node Routine: phân giải tên rồi gọi service của BE. Issue #274, #299.

## Vì sao gọi service chứ không gọi HTTP

Agent và BE chạy **cùng một tiến trình** (`src/serve.py`). Gọi `POST /routines/{id}/run`
từ trong graph là tự gọi HTTP vào chính mình: thêm một vòng serialize, một đường lỗi mới,
và một bản sao logic auth.

## Vì sao KHÔNG dựng lại admission

`routine_execution.bat_dau` có các cổng admission chạy **trước** khi có hàng nào trong
`routine_executions`, và `huy` idempotent. Dựng bản thứ hai ở làn Agent là dựng một bản
chắc chắn sẽ lệch — và #299 ghi rõ ranh giới: *"không tự hủy executor"*.

## Vì sao ba service tiêm vào chứ không nhập thẳng

Chúng thuộc `src/services/` của làn BE. Tiêm vào thì file này không giả định gì về bên
trong chúng, và một thay đổi bên ấy làm đỏ đúng chỗ nối chứ không âm thầm đổi hành vi.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agents.nodes.routine_node import make_routine_node


@dataclass
class _RoutineGia:
    id: str
    name: str
    steps: tuple[dict, ...] = ()


@dataclass
class _ExecGia:
    id: str
    status: str


def _node(*, ten=("Đi làm", "Về nhà", "Thư giãn"), lan_chay=None, ghi=None):
    goi = ghi if ghi is not None else []

    def liet_ke(user_id: str):
        return [_RoutineGia(f"rtn_{i}", t) for i, t in enumerate(ten)]

    async def bat_dau(*, user_id, session_id, vehicle_id, routine_id):
        goi.append(("bat_dau", routine_id))
        return _ExecGia(f"exe_{routine_id}", "running")

    async def huy(user_id, execution_id):
        goi.append(("huy", execution_id))
        return _ExecGia(execution_id, "canceled")

    def dang_chay(session_id: str):
        return lan_chay

    return make_routine_node(liet_ke=liet_ke, bat_dau=bat_dau, huy=huy, dang_chay_cua_phien=dang_chay)


_STATE = {"user_id": "usr_driver_01", "session_id": "ses_1", "vehicle_id": "vehicle-demo-01"}


async def test_chay_goi_bat_dau_dung_routine():
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})
    assert ra["outcome"] == "routine_da_chay"
    assert ghi == [("bat_dau", "rtn_0")]


async def test_xem_truoc_khong_bao_gio_cham_executor():
    """Bất biến của #274: *"Preview không tạo side effect."*"""
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "xem_truoc", "routine_ten_tho": "Về nhà"})
    assert ra["outcome"] == "routine_preview"
    assert ra["routine_id"] == "rtn_1"
    assert ghi == [], "preview đã gọi executor"


async def test_xem_truoc_tra_dung_ten_va_cac_buoc_theo_thu_tu():
    ghi: list = []
    routine = _RoutineGia(
        "rtn_ve_nha",
        "Về nhà",
        (
            {"action": "navigation", "destination": "home"},
            {"action": "hvac_power", "enabled": True},
        ),
    )
    node = make_routine_node(
        liet_ke=lambda _uid: [routine],
        bat_dau=None,
        huy=None,
        dang_chay_cua_phien=lambda _session_id: None,
    )

    ra = await node({**_STATE, "routine_y_dinh": "xem_truoc", "routine_ten_tho": "Về nhà"})

    assert ra["routine_preview"] == {
        "routine_id": "rtn_ve_nha",
        "routine_name": "Về nhà",
        "steps": [
            {"index": 0, "action": "navigation", "description": "dẫn đường tới Nhà"},
            {"index": 1, "action": "hvac_power", "description": "bật điều hòa"},
        ],
    }
    assert "routine_execution_id" not in ra
    assert ghi == []


async def test_compose_preview_neu_dung_ten_routine_nhung_khong_doc_dai_cac_buoc():
    from src.agents.nodes.compose import compose_node

    ra = await compose_node(
        {
            "outcome": "routine_preview",
            "routine_preview": {
                "routine_id": "rtn_ve_nha",
                "routine_name": "Về nhà",
                "steps": [{"index": 0, "action": "navigation", "description": "dẫn đường tới Nhà"}],
            },
        }
    )

    assert ra["speak_text"] == "Đây là các bước của chuỗi lệnh Về nhà. Bạn có muốn tôi chạy không?"
    assert "dẫn đường tới Nhà" not in ra["speak_text"]


async def test_ten_mo_ho_thi_hoi_lai_va_zero_side_effect():
    ghi: list = []
    node = _node(ten=("Đi làm sáng", "Đi làm chiều"), ghi=ghi)
    ra = await node({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})
    assert ra["outcome"] == "routine_mo_ho"
    assert sorted(ra["routine_ung_vien"]) == ["Đi làm chiều", "Đi làm sáng"]
    assert ghi == []


async def test_khong_thay_ten_thi_neu_danh_sach_chu_khong_chay_bua():
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi chơi"})
    assert ra["outcome"] == "routine_khong_thay"
    assert ra["routine_ung_vien"] == ["Đi làm", "Về nhà", "Thư giãn"]
    assert ghi == []


async def test_huy_map_dung_lan_chay_dang_song_cua_phien():
    ghi: list = []
    node = _node(lan_chay=_ExecGia("exe_dang_chay", "running"), ghi=ghi)
    ra = await node({**_STATE, "routine_y_dinh": "huy", "routine_ten_tho": ""})
    assert ra["outcome"] == "routine_da_huy"
    assert ghi == [("huy", "exe_dang_chay")]


async def test_huy_khi_khong_co_lan_chay_nao_thi_tra_loi_an_toan():
    """#299: *"no-active-run trả phản hồi an toàn, zero side effect."*"""
    ghi: list = []
    ra = await _node(lan_chay=None, ghi=ghi)({**_STATE, "routine_y_dinh": "huy"})
    assert ra["outcome"] == "routine_khong_co_lan_chay"
    assert ghi == []


async def test_huy_hai_lan_lien_tiep_van_an_toan():
    """Idempotency thuộc về `huy()` (BE, #297). Test này khoá rằng node **không** chen một
    tầng trạng thái nào vào giữa và làm hỏng tính chất ấy."""
    ghi: list = []
    node = _node(lan_chay=_ExecGia("exe_1", "running"), ghi=ghi)
    st = {**_STATE, "routine_y_dinh": "huy"}
    assert (await node(st))["outcome"] == "routine_da_huy"
    assert (await node(st))["outcome"] == "routine_da_huy"
    assert ghi == [("huy", "exe_1"), ("huy", "exe_1")]


@pytest.mark.parametrize("thieu", ["user_id", "session_id"])
async def test_thieu_ngu_canh_thi_khong_goi_gi_ca(thieu: str):
    """Fail-closed. State tới từ `turns.py`; thiếu khoá là lỗi lập trình, và lối ra an
    toàn là **không làm gì** — đoán một `user_id` khác là chạy lệnh trên xe người khác."""
    ghi: list = []
    st = {**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"}
    st.pop(thieu)
    ra = await _node(ghi=ghi)(st)
    assert ra["outcome"] == "routine_loi_ngu_canh"
    assert ghi == []


async def test_khong_co_routine_nao_thi_khong_vo():
    """Tài khoản mới chưa dựng Routine nào. `phan_giai_ten` gặp danh sách rỗng."""
    ghi: list = []
    ra = await _node(ten=(), ghi=ghi)({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})
    assert ra["outcome"] == "routine_khong_thay"
    assert ra["routine_ung_vien"] == []
    assert ghi == []


def test_phan_giai_ten_khong_bo_ro_nao_giua_mo_ho_va_khong_thay():
    """Node dựa vào một giả định của `KetQuaPhanGiai`, nên giả định ấy phải được khoá.

    Đọc kỹ hợp đồng thì thấy một khe hở trên giấy:

        mo_ho      đòi  trung is None và len(ung_vien) > 1
        khong_thay đòi  trung is None và ung_vien rỗng

    "Không trúng mà đúng một ứng viên" lọt qua cả hai. Đo thì thấy khe ấy **hiện không
    với tới được** — hễ còn đúng một ứng viên là `phan_giai_ten` đặt luôn `trung`:

        phan_giai_ten("đi",  ["Đi làm"]) -> trung="Đi làm"
        phan_giai_ten("xyz", ["Đi làm"]) -> trung=None, ung_vien=()   (khong_thay)

    Nên `routine_node` vẫn giữ nhánh phòng thủ (không trúng + không `khong_thay` = hỏi
    lại), còn test này khoá lý do nhánh ấy chưa bao giờ chạy. Nếu ai đó nới
    `phan_giai_ten` để nó trả một ứng viên mà không dám gọi là trúng, test này đỏ và
    người sửa phải xét lại nhánh kia — thay vì để `next(...)` ném `StopIteration` giữa
    một lượt nói.
    """
    from src.agents.routines_intent import phan_giai_ten

    ds = ["Đi làm", "Về nhà", "Thư giãn"]
    for tho in ["đi", "xyz", "làm", "a", "", "về", "thư giãn", "đi làm"]:
        kq = phan_giai_ten(tho, ds)
        if kq.trung is None:
            assert kq.mo_ho or kq.khong_thay, f"{tho!r} rơi vào khe giữa hai nhánh"


async def test_bat_dau_tu_choi_thi_thanh_cau_noi_chu_khong_thanh_500():
    """Ca **thường gặp**, không phải ca biên — đo end-to-end 30/08.

    Hai trong ba mẫu mặc định (`Đi làm`, `Về nhà`) sinh ra ở trạng thái "Cần thiết lập"
    vì chưa có địa điểm Nhà/Cơ quan, nên `bat_dau` ném `RoutineKhongChayDuocError` ngay
    lần chạy đầu tiên của một tài khoản mới. Không bắt thì lượt nói ấy trả 500 và tài xế
    nghe im lặng.

    Bốn lý do đều xảy ra **trước** khi tạo execution, nên zero side effect.
    """
    from src.services.routine_execution import RoutineKhongChayDuocError

    ghi: list = []

    async def bat_dau_tu_choi(**_):
        ghi.append("bat_dau")
        raise RoutineKhongChayDuocError("chua_dat_dia_diem", "chưa đặt địa điểm Nhà nên chưa chạy được chuỗi lệnh này")

    node = make_routine_node(
        liet_ke=lambda uid: [_RoutineGia("rtn_0", "Về nhà")],
        bat_dau=bat_dau_tu_choi,
        huy=None,
        dang_chay_cua_phien=lambda _s: None,
    )
    ra = await node({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Về nhà"})

    assert ra["outcome"] == "routine_tu_choi"
    assert "chưa đặt địa điểm" in ra["routine_ly_do"]


async def test_loi_tu_choi_khong_bi_viet_lai_o_compose():
    """Câu đọc lên phải là `thong_diep` của chính lỗi. Viết lại ở compose là dựng một bản
    sao sẽ lệch ngay khi làn BE thêm lý do thứ năm."""
    from src.agents.nodes.compose import compose_node

    ra = await compose_node(
        {"outcome": "routine_tu_choi", "routine_ly_do": "Chuỗi lệnh này đang tắt"}
    )
    assert "Chuỗi lệnh này đang tắt" in ra["speak_text"]


async def test_loi_tu_choi_mang_ca_ma_may_doc_duoc():
    """#385 cần FE đưa tài xế sang màn setup Nhà/Cơ quan khi thiếu địa điểm.

    Không client nào nên rẽ nhánh bằng cách so khớp một câu tiếng Việt: câu ấy do làn BE
    soạn để **đọc lên**, và nó sẽ đổi. Mã thì không.
    """
    from src.services.routine_execution import RoutineKhongChayDuocError

    async def tu_choi(**_):
        raise RoutineKhongChayDuocError("chua_dat_dia_diem", "chưa đặt địa điểm Nhà nên chưa chạy được chuỗi lệnh này")

    node = make_routine_node(
        liet_ke=lambda uid: [_RoutineGia("rtn_0", "Về nhà")],
        bat_dau=tu_choi, huy=None, dang_chay_cua_phien=lambda _s: None,
    )
    ra = await node({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Về nhà"})
    assert ra["routine_ma_loi"] == "chua_dat_dia_diem"


async def test_thieu_dia_diem_thi_co_routine_setup_required_co_cau_truc():
    """#385: FE mở đúng màn setup và đúng hàng Nhà/Cơ quan cần payload có cấu trúc,
    không chỉ mã lỗi trần — `thieu` phải mang đúng nhãn `bat_dau` báo thiếu."""
    from src.services.routine_execution import RoutineKhongChayDuocError

    async def tu_choi(**_):
        raise RoutineKhongChayDuocError(
            "chua_dat_dia_diem",
            "chưa đặt địa điểm Cơ quan nên chưa chạy được Routine này",
            thieu_dia_diem=("office",),
        )

    node = make_routine_node(
        liet_ke=lambda uid: [_RoutineGia("rtn_0", "Đi làm")],
        bat_dau=tu_choi, huy=None, dang_chay_cua_phien=lambda _s: None,
    )
    ra = await node({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})

    assert ra["routine_setup_required"] == {
        "routine_id": "rtn_0",
        "ma_loi": "chua_dat_dia_diem",
        "thieu": ["office"],
    }


@pytest.mark.parametrize(
    "ma,thong_diep",
    [
        ("routine_da_tat", "Routine này đang tắt"),
        ("dang_chay_routine_khac", "đang có một Routine chạy dở trong phiên này"),
        ("routine_khong_ton_tai", "không tìm thấy Routine"),
    ],
)
async def test_ba_ly_do_tu_choi_con_lai_khong_co_routine_setup_required(ma: str, thong_diep: str):
    """Ba mã lỗi này không có màn setup nào để đưa tài xế sang — gán địa điểm không
    sửa được Routine đang tắt, đang chạy dở, hay đã biến mất. `routine_setup_required`
    phải là `None`, không phải FE tự suy đoán từ một mã lỗi nó không nhận ra."""
    from src.services.routine_execution import RoutineKhongChayDuocError

    async def tu_choi(**_):
        raise RoutineKhongChayDuocError(ma, thong_diep)

    node = make_routine_node(
        liet_ke=lambda uid: [_RoutineGia("rtn_0", "Đi làm")],
        bat_dau=tu_choi, huy=None, dang_chay_cua_phien=lambda _s: None,
    )
    ra = await node({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})

    assert ra["routine_setup_required"] is None


async def test_chay_thanh_cong_thi_khong_con_routine_setup_required_cu():
    """Lượt trước từ chối vì thiếu địa điểm, lượt sau (sau khi đã setup) chạy thành
    công — `routine_setup_required` của lượt trước không được sống sót sang lượt này."""
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "chay", "routine_ten_tho": "Đi làm"})
    assert ra["outcome"] == "routine_da_chay"
    assert ra["routine_setup_required"] is None


async def test_chay_thanh_cong_thi_khong_con_routine_preview_cu():
    """Cùng lỗ mà review PR #404 chỉ ra, nhưng cho `routine_preview`: lượt trước là một
    preview (đặt `routine_preview` có cấu trúc), lượt sau tài xế đồng ý và Routine chạy
    thành công — `_chay` không tự biết phải xoá `routine_preview` nếu không ghi rõ, và
    khoá này không gate theo `outcome` khi phát ra cho FE."""
    ghi: list = []
    ra = await _node(ghi=ghi)({**_STATE, "routine_y_dinh": "dong_y", "routine_cho_xac_nhan_id": "rtn_0"})
    assert ra["outcome"] == "routine_da_chay"
    assert ra["routine_preview"] is None

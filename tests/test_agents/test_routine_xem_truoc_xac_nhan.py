"""Preview Routine -> đồng ý/từ chối ở lượt sau. Review PR #401 (#274, #285).

## Lỗ hổng review chỉ ra

`routines_intent.doc_y_dinh(..., dang_xem_truoc=True)` đọc được "đồng ý"/"từ chối" từ
#285, nhưng không có nơi nào từng gọi nó với `dang_xem_truoc=True`: `router.py` chỉ gọi
bản mặc định để đọc `ten_tho`, và không có khe nào nhớ "vừa preview Routine nào" giữa hai
lượt. Nên `"Xem trước Routine Về nhà"` rồi `"Chạy đi"` không nối được với nhau.

## Cách nối, cùng khuôn với `loi_de_nghi.py`/`ghep_hoi_lai.py`

`routine_node` (chạy sau `route_node` trong cùng lượt, vì chỉ nó biết `routine_id` đã
phân giải) nạp `routine_cho_xac_nhan_id`/`routine_cho_xac_nhan_luc` khi trả về
`routine_preview`. Lượt sau, `route_node._dap_xem_truoc_routine` đọc lại khe đó, gọi
`doc_y_dinh(text, dang_xem_truoc=True)`, và forward `dong_y`/`tu_choi` xuống `routine_node`
kèm đúng `routine_id` đã treo — không phân giải tên gì cả, vì lượt xác nhận không nêu tên.

Bộ test dưới đây mô phỏng đúng hai bước của graph thật cho một lượt Routine: `route_node`
rồi `routine_node`, cùng chung một đồng hồ giả để TTL đo được.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agents.nodes.route import make_route_node
from src.agents.nodes.routine_node import make_routine_node
from src.agents.router import DeterministicControlRouter
from src.agents.routines_intent import TTL_XAC_NHAN_GIAY


@dataclass
class _RoutineGia:
    id: str
    name: str
    steps: tuple[dict[str, object], ...] = ()


@dataclass
class _ExecGia:
    id: str
    status: str


class DongHoGia:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def troi(self, giay: float) -> None:
        self.t += giay


class Phien:
    """Một phiên nói chuyện: mô phỏng cạnh `route -> routine` của graph thật.

    `route_node` chạy trước; nếu `outcome` của nó là `"routine"` thì `routine_node`
    chạy tiếp trong CÙNG lượt và đè lên state — đúng thứ tự và đúng phép merge mà
    LangGraph dùng (state của node chạy sau thắng state của node chạy trước, cho cùng
    một khoá). Không mô phỏng thì TTL không đo được, vì hai node cần chung một đồng hồ.
    """

    def __init__(self, *, ten=("Đi làm", "Về nhà", "Thư giãn"), tu_choi_bat_dau: Exception | None = None) -> None:
        self.dong_ho = DongHoGia()
        self.goi_bat_dau: list[str] = []
        self.route_node = make_route_node(DeterministicControlRouter(), dong_ho=self.dong_ho)

        async def bat_dau(*, user_id, session_id, vehicle_id, routine_id):
            self.goi_bat_dau.append(routine_id)
            if tu_choi_bat_dau is not None:
                raise tu_choi_bat_dau
            return _ExecGia(f"exe_{routine_id}", "running")

        self.routine_node = make_routine_node(
            liet_ke=lambda uid: [_RoutineGia(f"rtn_{i}", t) for i, t in enumerate(ten)],
            bat_dau=bat_dau,
            huy=None,
            dang_chay_cua_phien=lambda _sid: None,
            dong_ho=self.dong_ho,
        )
        self.state: dict = {"user_id": "usr_driver_01", "session_id": "ses_1", "vehicle_id": "vehicle-demo-01"}

    async def noi(self, text: str) -> dict:
        self.state["query"] = text
        update = await self.route_node(self.state)
        self.state.update(update)
        if self.state.get("outcome") == "routine":
            update2 = await self.routine_node(self.state)
            self.state.update(update2)
            return update2
        return update


# --- Ca chính: đồng ý / từ chối ----------------------------------------------


async def test_dong_y_sau_preview_thi_chay_dung_routine():
    p = Phien()
    l1 = await p.noi("Xem trước Routine Về nhà")
    assert l1["outcome"] == "routine_preview"
    routine_id = l1["routine_id"]

    l2 = await p.noi("Chạy đi")
    assert l2["outcome"] == "routine_da_chay"
    assert l2["routine_id"] == routine_id
    assert p.goi_bat_dau == [routine_id]


@pytest.mark.parametrize("dap", ["Đồng ý", "Ok", "Ừ", "Được"])
async def test_cac_cach_noi_dong_y_deu_chay(dap: str):
    p = Phien()
    await p.noi("Xem trước Routine Đi làm")
    l2 = await p.noi(dap)
    assert l2["outcome"] == "routine_da_chay"
    assert p.goi_bat_dau == ["rtn_0"]


@pytest.mark.parametrize("dap", ["Không", "Thôi", "Hủy"])
async def test_tu_choi_sau_preview_thi_khong_chay(dap: str):
    p = Phien()
    await p.noi("Xem trước Routine Về nhà")
    l2 = await p.noi(dap)
    assert l2["outcome"] == "routine_huy_xem_truoc"
    assert p.goi_bat_dau == [], "từ chối preview không được chạm executor"


async def test_bat_dau_tu_choi_sau_khi_dong_y_van_thanh_cau_noi():
    """`bat_dau` vẫn có thể từ chối SAU khi đồng ý — ví dụ Routine bị tắt giữa lúc xem
    trước và lúc đồng ý. Đường lỗi phải giống hệt ca "chạy mới", không phải 500."""
    from src.services.routine_execution import RoutineKhongChayDuocError

    p = Phien(tu_choi_bat_dau=RoutineKhongChayDuocError("routine_da_tat", "Chuỗi lệnh này đang tắt"))
    await p.noi("Xem trước Routine Về nhà")
    l2 = await p.noi("Chạy đi")
    assert l2["outcome"] == "routine_tu_choi"
    assert l2["routine_ma_loi"] == "routine_da_tat"


# --- Ba ca PHẢI giữ trơ (đúng khuôn `loi_de_nghi.py`) ------------------------


async def test_khong_co_preview_thi_tieng_dong_y_tran_khong_chay_gi():
    p = Phien()
    l1 = await p.noi("Chạy đi")
    assert l1["outcome"] != "routine_da_chay"
    assert p.goi_bat_dau == []


async def test_qua_han_thi_khong_con_xac_nhan_duoc():
    p = Phien()
    await p.noi("Xem trước Routine Về nhà")
    p.dong_ho.troi(TTL_XAC_NHAN_GIAY + 1)
    l2 = await p.noi("Chạy đi")
    assert l2["outcome"] != "routine_da_chay"
    assert p.goi_bat_dau == [], "preview đã hết hạn không được chạy nhầm"


async def test_lenh_moi_thang_sau_preview():
    """Tài xế đổi ý ngay sau preview và ra một lệnh control khác — lệnh đó phải chạy,
    không bị cổng preview nuốt mất."""
    p = Phien()
    await p.noi("Xem trước Routine Về nhà")
    l2 = await p.noi("Bật điều hòa")
    assert l2["outcome"] == "control"
    assert {b.tool for b in l2["candidate_action_plan"].steps} == {"set_hvac_power"}
    assert p.goi_bat_dau == []


async def test_cach_mot_luot_thi_preview_da_nguoi():
    """Chốt "chỉ lượt kế tiếp ngay sau" — một câu xen giữa xoá khe, dù còn trong TTL."""
    p = Phien()
    await p.noi("Xem trước Routine Về nhà")
    await p.noi("Hôm nay trời đẹp nhỉ")
    l3 = await p.noi("Chạy đi")
    assert l3["outcome"] != "routine_da_chay"
    assert p.goi_bat_dau == []


# --- Khe dùng một lần, và mọi lối ra đều quét sạch ----------------------------


async def test_khe_bi_xoa_sau_khi_dong_y():
    p = Phien()
    await p.noi("Xem trước Routine Về nhà")
    await p.noi("Chạy đi")
    l3 = await p.noi("Chạy đi")
    assert l3["outcome"] != "routine_da_chay"
    assert p.goi_bat_dau == ["rtn_1"], "tiếng 'chạy đi' thứ hai không được chạy lại"


async def test_khe_bi_xoa_sau_khi_tu_choi():
    p = Phien()
    await p.noi("Xem trước Routine Về nhà")
    await p.noi("Không")
    l3 = await p.noi("Chạy đi")
    assert l3["outcome"] != "routine_da_chay"
    assert p.goi_bat_dau == []


async def test_giai_tan_van_hoat_dong_binh_thuong_khi_khong_co_preview():
    """Guard mới thêm vào `_la_cau_giai_tan` không được chặn nhầm ca không liên quan gì
    tới Routine — #363 vẫn phải xanh."""
    p = Phien()
    l1 = await p.noi("Thôi")
    assert l1["outcome"] == "not_control"
    assert l1["intent"] == "giai_tan"


async def test_khong_sau_preview_khong_bi_doc_nham_thanh_giai_tan():
    """`"Không"` ngay sau preview phải là từ chối Routine, không phải đuổi trợ lý —
    hai lối ra khác câu hẳn nhau."""
    p = Phien()
    await p.noi("Xem trước Routine Về nhà")
    l2 = await p.noi("Không")
    # `intent` do `route_node` đặt (`"routine_decline"`); `routine_node` chạy sau không
    # ghi đè khoá này, nên phải đọc từ state đã merge, không phải dict trả về riêng của
    # `routine_node`.
    assert p.state["intent"] != "giai_tan"
    assert p.state["intent"] == "routine_decline"
    assert l2["outcome"] == "routine_huy_xem_truoc"


@pytest.mark.parametrize(
    "cau",
    [
        "Bật điều hòa",
        "Xem trước Routine Về nhà",
        "Chạy Routine Đi làm",
        "Hôm nay trời đẹp nhỉ",
        "Tắt đèn pha",
    ],
)
async def test_moi_hinh_dang_deu_tra_ve_hai_truong_cua_khe(cau: str):
    """Cùng tinh thần với `test_moi_luot_deu_tra_ve_hai_truong_cua_khe` của
    `loi_de_nghi.py`: một lối ra quên xoá là một plan/preview cũ sống dai quá tuổi."""
    p = Phien()
    update = await p.noi(cau)
    assert "routine_cho_xac_nhan_id" in update, cau
    assert "routine_cho_xac_nhan_luc" in update, cau
    if update["outcome"] == "routine_preview":
        assert update["routine_cho_xac_nhan_id"], cau
        assert update["routine_cho_xac_nhan_luc"] > 0.0, cau
    else:
        assert update["routine_cho_xac_nhan_id"] == "", cau
        assert update["routine_cho_xac_nhan_luc"] == 0.0, cau

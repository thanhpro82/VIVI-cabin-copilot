"""Xe đề nghị một việc, tài xế đáp "có" — và lệnh chạy. Issue #355 mục 1, và #339.

## Ca đầu bảng, nguyên văn phép đo trước khi sửa

```
lượt 1  "Bật điều hòa được không"  -> offer, plan SẴN CÓ: set_hvac_power{enabled:True}
        VIVI: "Tôi có thể bật điều hòa. Bạn có muốn tôi thực hiện không?"
lượt 2  "Có"                       -> not_control/default_to_manual, 0 lệnh
```

Xe hỏi một câu có/không rồi không nghe được câu trả lời của chính nó — và đi tra sổ tay
chữ "Có". `offer` là disposition duy nhất không phải `control` mà **vẫn mang sẵn một
plan đã dựng xong và hợp lệ**, nên thứ thiếu không phải là khả năng, chỉ là chỗ nhớ.

## Vì sao ca `offer` chứ không phải ca `clarify`

Mục tiêu của multiturn là **đừng bắt tài xế nói lại "Hey VIVI"**. Sau `offer`, xe đã nói
ra hành động cụ thể và câu trả lời là một lựa chọn đóng có/không — cùng hình dạng với
phê duyệt HITL, nơi FE đã tự mở mic từ #207b. Sau `clarify` thì câu trả lời là một mảnh
tự do (*"mức 2"*, *"bên lái"*), nơi một tiếng lạc thành một lệnh không ai yêu cầu.

Nhánh `clarify` ấy **có** người ký rồi, nhưng là một cơ chế khác: #363 chốt auto-listen
ngắn 3–5 giây kèm **mẫu ngữ pháp cứng** cho đúng slot đang thiếu, không khớp thì NO_EXEC.
Nó cần mẫu ngữ pháp vì câu trả lời là mảnh tự do; ở đây không cần, vì có/không đã là một
tập đóng hai phần tử. Nên hai việc tách nhau, và
`test_ghep_hoi_lai.py::test_clarify_khong_bao_gio_mo_mic_tu_dong` còn xanh sau PR này —
nó là việc của #363, không phải của PR này.

Bộ đo: `eval/datasets/agent/multiturn-v1`, mốc 10/19 → 17/19, `di_lui` = 0.
"""

from __future__ import annotations

import pytest

from src.agents.loi_de_nghi import TTL_GIAY, con_han, doc_dap_loi_de_nghi
from src.agents.nodes.route import make_route_node
from src.agents.router import DeterministicControlRouter


class DongHoGia:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def troi(self, giay: float) -> None:
        self.t += giay


class Phien:
    """Một phiên: state của lượt trước chảy sang lượt sau, như checkpoint LangGraph."""

    def __init__(self) -> None:
        self.dong_ho = DongHoGia()
        self.node = make_route_node(DeterministicControlRouter(), dong_ho=self.dong_ho)
        self.state: dict = {}

    async def noi(self, text: str) -> dict:
        self.state["query"] = text
        update = await self.node(self.state)
        self.state.update(update)
        return update


def _mo(update: dict) -> str:
    return f"{update['outcome']}/{update['route_reason']}"


def _tools(update: dict) -> set[str]:
    plan = update.get("candidate_action_plan")
    return {b.tool for b in plan.steps} if plan else set()


# --- Phần thuần -------------------------------------------------------------


@pytest.mark.parametrize(
    ("cau", "mong"),
    [
        ("Có", "nhan"),
        ("Ừ", "nhan"),
        ("Đồng ý", "nhan"),
        ("Có chứ", "nhan"),
        ("Được", "nhan"),
        ("Không", "tu_choi"),
        ("Thôi", "tu_choi"),
        ("Thôi khỏi", "tu_choi"),
        ("Không cần", "tu_choi"),
        # Không phải lời đáp — phải đi đường thường.
        ("hai", None),
        ("mức 2", None),
        ("Hôm nay trời đẹp nhỉ", None),
        # Tiếng trần đứng TRƯỚC một lệnh không phải câu trả lời. Docstring của
        # `doc_tra_loi_co_khong` đã cảnh báo đúng ca này.
        ("Ừ mở kính", None),
        ("Có mở cốp", None),
    ],
)
def test_doc_dap_loi_de_nghi(cau: str, mong: str | None):
    assert doc_dap_loi_de_nghi(cau) == mong


def test_khong_co_de_nghi_thi_khong_con_han():
    assert con_han(0.0, 1000.0) is False


def test_ttl_dung_bien_va_khong_nhan_dong_ho_chay_lui():
    assert con_han(1000.0, 1000.0 + TTL_GIAY) is True
    assert con_han(1000.0, 1000.0 + TTL_GIAY + 0.01) is False
    assert con_han(1000.0, 999.0) is False


# --- Ca chính ---------------------------------------------------------------


@pytest.mark.parametrize("dap", ["Có", "Ừ", "Đồng ý", "Có chứ", "Được"])
async def test_nhan_loi_de_nghi_thi_lenh_chay(dap: str):
    p = Phien()

    l1 = await p.noi("Bật điều hòa được không")
    assert _mo(l1) == "offer/question_about_supported_action"
    assert _tools(l1) == {"set_hvac_power"}

    l2 = await p.noi(dap)
    assert _mo(l2) == "control/offer_accepted"
    assert _tools(l2) == {"set_hvac_power"}
    assert l2["da_nhan_de_nghi"] is True


async def test_plan_chay_la_dung_plan_da_doc_ra_thanh_loi():
    """Không dựng lại từ chữ "Có" — đó là cả điểm của cơ chế.

    Dựng lại thì phải route chuỗi "Có", và chuỗi ấy không mang nội dung nào. Giữ đúng
    object plan của lượt trước là thứ khiến câu xe đã nói ra và việc xe sắp làm không
    thể lệch nhau.
    """
    p = Phien()
    l1 = await p.noi("Bật điều hòa được không")
    l2 = await p.noi("Có")
    assert l2["candidate_action_plan"] is l1["candidate_action_plan"]


@pytest.mark.parametrize("dap", ["Không", "Thôi", "Thôi khỏi", "Không cần"])
async def test_tu_choi_thi_khong_chay_gi_va_khong_di_tra_so_tay(dap: str):
    """`not_control` mặc định **đi tra sổ tay**, nên lối ra này phải có nhãn riêng.

    Thiếu nó thì tài xế nói "thôi" và xe đọc cho nghe một đoạn sổ tay về chữ "thôi" —
    đúng lỗi mà `manual_stop_reading` đã sinh ra để sửa ở nhánh đọc tiếp.
    """
    p = Phien()
    await p.noi("Bật điều hòa được không")
    l2 = await p.noi(dap)

    assert _mo(l2) == "not_control/offer_declined"
    assert l2["intent"] == "offer_declined"
    assert _tools(l2) == set()


# --- Bốn ca PHẢI giữ trơ ----------------------------------------------------


async def test_tieng_co_tran_khong_co_de_nghi_nao_thi_tro():
    p = Phien()
    assert _mo(await p.noi("Có")) == "not_control/default_to_manual"


async def test_manh_so_sau_de_nghi_khong_thanh_lenh():
    """Ca nguy hiểm nhất của cả cơ chế.

    Sau đề nghị điều hòa, tài xế nói `"hai"`. Nếu cửa nhận câu trả lời mở rộng bằng
    "nghe thấy gì cũng cho là đồng ý" thì nó thành `set_hvac_fan_level(level=2)` — một
    lệnh **không ai yêu cầu**, chạy vì xe đoán.
    """
    p = Phien()
    await p.noi("Bật điều hòa được không")
    l2 = await p.noi("hai")
    assert l2["outcome"] != "control"
    assert _tools(l2) == set()


async def test_cach_mot_luot_thi_de_nghi_da_nguoi():
    """Chốt "chỉ lượt kế tiếp ngay sau" — không có bộ đếm lượt, chỉ có phép xoá."""
    p = Phien()
    await p.noi("Bật điều hòa được không")
    await p.noi("Hôm nay trời đẹp nhỉ")
    l3 = await p.noi("Có")
    assert l3["outcome"] != "control"
    assert _tools(l3) == set()


async def test_qua_han_thi_khong_nhan():
    p = Phien()
    await p.noi("Bật điều hòa được không")
    p.dong_ho.troi(TTL_GIAY + 1)
    l2 = await p.noi("Có")
    assert l2["outcome"] != "control"


async def test_lenh_moi_thang_cau_tra_loi():
    """Tài xế đổi ý và ra lệnh khác. Nuốt nó vào slot là chạy đúng thứ họ **không** nói."""
    p = Phien()
    await p.noi("Bật điều hòa được không")
    l2 = await p.noi("Mở cốp xe")
    assert _mo(l2) == "control/deterministic_rule"
    assert _tools(l2) == {"set_trunk_state"}
    assert l2["da_nhan_de_nghi"] is False


async def test_tieng_co_sau_clarify_khong_thanh_lenh():
    """Hai slot loại trừ nhau theo cấu trúc: `clarify` nạp slot ghép, `offer` nạp slot
    đề nghị, mọi disposition khác quét sạch cả hai.

    "Có" không trả lời được câu hỏi *"cửa sổ bên nào?"*, nên nó không được biến thành gì.
    """
    p = Phien()
    assert _mo(await p.noi("Mở cửa sổ")) == "clarify/missing_window_side"
    l2 = await p.noi("Có")
    assert l2["outcome"] != "control"
    assert _tools(l2) == set()


# --- Cơ chế không đụng vào một quyết định an toàn nào ------------------------


async def test_route_source_giu_nguon_cua_plan_goc():
    """`policy.py` đọc `route_source` để quyết `requires_approval` (mọi plan SLM đều phải
    duyệt). Ghi đè nó bằng một chi tiết hội thoại là đổi một quyết định an toàn.
    """
    p = Phien()
    await p.noi("Bật điều hòa được không")
    l2 = await p.noi("Có")
    assert l2["route_source"] == "deterministic_rule"


async def test_nhan_de_nghi_khong_bo_qua_cong_phan_loai_an_toan():
    """Plan được nhận vẫn là một `CandidateActionPlan` — **không có** `safety_level`.

    Đó là bất biến của `contracts.py`: chỉ `policy.py` gán mức an toàn. Nếu lối ra này
    trả về một `ActionPlan` dựng sẵn thì nó vừa đi vòng qua `validate_args` vừa đi vòng
    qua phân loại S0–S3 — hạ kính hết cần duyệt, mở cửa lúc xe chạy hết bị chặn.
    """
    from src.agents.contracts import CandidateActionPlan

    p = Phien()
    await p.noi("Bật điều hòa được không")
    l2 = await p.noi("Có")
    plan = l2["candidate_action_plan"]
    assert isinstance(plan, CandidateActionPlan)
    assert not hasattr(plan.steps[0], "safety_level")


async def test_slot_bi_xoa_sau_khi_nhan():
    """Dùng một lần. Không xoá thì một tiếng "có" thứ hai chạy lại đúng lệnh ấy."""
    p = Phien()
    await p.noi("Bật điều hòa được không")
    await p.noi("Có")
    l3 = await p.noi("Có")
    assert l3["outcome"] != "control"


async def test_slot_bi_xoa_sau_khi_tu_choi():
    p = Phien()
    await p.noi("Bật điều hòa được không")
    await p.noi("Không")
    l3 = await p.noi("Có")
    assert l3["outcome"] != "control"


# --- Mọi lối ra đều phải quét khe, và điều đó phải được khoá chứ không soi mắt ---


async def test_moi_luot_deu_tra_ve_hai_truong_cua_khe():
    """phoenix-mentor nêu ở #367: nếu một lối ra nào đó **quên** xoá khe thì một plan cũ
    sống dai hơn tuổi của nó và một tiếng "có" muộn sẽ chạy nó.

    Đọc mắt bốn lối ra rồi bảo "đủ rồi" là thứ hỏng ngay lần thêm nhánh thứ năm. Test này
    khoá **tính chất**: `route_node` luôn trả về cả hai trường, ở mọi hình dạng lượt —
    nên một nhánh mới quên chúng sẽ đỏ ngay tại đây, không chờ ai nhớ.

    `cho_nhan_luc` là mốc thời gian, nên `0.0` mang nghĩa "không có gì đang treo" —
    `con_han` từ chối mọi giá trị `<= 0.0`. Kể cả state hỏng cũng chỉ dẫn tới "không nhận",
    không dẫn tới "chạy nhầm".
    """
    hinh_dang = [
        ("Bật điều hòa", "control"),
        ("Bật điều hòa được không", "offer"),
        ("Mở cửa sổ", "clarify"),
        ("Hôm nay trời đẹp nhỉ", "not_control"),
        ("Tắt đèn pha", None),
    ]
    for cau, _mong in hinh_dang:
        p = Phien()
        update = await p.noi(cau)
        assert "cho_nhan_plan" in update, cau
        assert "cho_nhan_luc" in update, cau
        # Chỉ `offer` được nạp khe; mọi hình dạng khác phải quét sạch.
        if update["outcome"] == "offer":
            assert update["cho_nhan_plan"] is not None, cau
            assert update["cho_nhan_luc"] > 0.0, cau
        else:
            assert update["cho_nhan_plan"] is None, cau
            assert update["cho_nhan_luc"] == 0.0, cau


async def test_ca_hai_loi_ra_cua_chinh_co_che_cung_quet_khe():
    """Hai nhánh `return` sớm của chính cổng này — nhận và từ chối — nằm ngoài đường đi
    của test trên, nên phải kiểm riêng. Không quét thì một tiếng "có" thứ hai chạy lại
    đúng lệnh ấy; `test_slot_bi_xoa_sau_khi_nhan` đo hậu quả, còn đây đo cơ chế.
    """
    for dap in ("Có", "Không"):
        p = Phien()
        await p.noi("Bật điều hòa được không")
        update = await p.noi(dap)
        assert update["cho_nhan_plan"] is None, dap
        assert update["cho_nhan_luc"] == 0.0, dap

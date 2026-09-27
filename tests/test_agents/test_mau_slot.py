"""Rào chắn của auto-listen: mảnh trả lời phải THUẦN là câu trả lời. Issue #363.

## Ca ép ra cả cơ chế

`ghep_hoi_lai.py` ghi sẵn rủi ro này trong docstring của chính nó, từ trước #363. Đo lại
29/08 thì nó **không còn là rủi ro** — nó đã xảy ra, với mic bấm tay:

```
"Tăng quạt gió"  ->  clarify/missing_fan_level
    "hai giờ nhé"            ->  control  set_hvac_fan_level{level: 2}
    "hai người nữa thôi"     ->  control  set_hvac_fan_level{level: 2}
    "mai hai giờ chiều nhé"  ->  control  set_hvac_fan_level{level: 2}

"Bật đèn"        ->  clarify/missing_light_target
    "đèn pha bị hỏng rồi"    ->  control  set_headlight_mode{mode: low_beam}
```

Câu cuối là một lời **than phiền** biến thành một **lệnh bật đèn**.

Bộ đo: `eval/datasets/agent/multiturn-v1` nhóm `clarify-rao-chan`, 9/14 → 14/14.
"""

from __future__ import annotations

import pytest

from src.agents.ghep_hoi_lai import CO_THE_GHEP
from src.agents.mau_slot import CO_MAU, khop_mau
from src.agents.nodes.route import make_route_node
from src.agents.router import DeterministicControlRouter


class Phien:
    def __init__(self) -> None:
        self.node = make_route_node(DeterministicControlRouter())
        self.state: dict = {}

    async def noi(self, text: str) -> dict:
        self.state["query"] = text
        update = await self.node(self.state)
        self.state.update(update)
        return update


def _tools(update: dict) -> set[str]:
    plan = update.get("candidate_action_plan")
    return {b.tool for b in plan.steps} if plan else set()


# --- Bộ lọc, kiểm thuần ------------------------------------------------------


@pytest.mark.parametrize(
    ("ly_do", "manh"),
    [
        ("missing_fan_level", "hai"),
        ("missing_fan_level", "2"),
        ("missing_fan_level", "mức 2"),
        ("missing_fan_level", "ừ hai đi"),
        # Ngoài dải vẫn phải QUA lọc, để `chap_nhan` còn cho tài xế nghe "chỉ đặt được
        # 0–3" (bảng ở docstring `ghep_hoi_lai`). Chặn ở đây là đổi một câu trả lời đúng
        # việc lấy một câu hỏi lại lặp.
        ("missing_fan_level", "hai bốn"),
        ("missing_temperature", "mười tám độ"),
        ("missing_temperature", "18 độ"),
        ("missing_volume", "năm mươi"),
        ("missing_volume", "50 phần trăm"),
        ("missing_window_side", "bên lái"),
        ("missing_window_side", "bên lái nhé"),
        ("missing_window_position", "30 phần trăm"),
        ("missing_window_position", "mở hết"),
        ("missing_window_position", "một nửa"),
        ("missing_light_target", "đèn pha"),
        ("missing_light_target", "cái đèn pha ấy"),
        ("missing_seat_value", "30 độ"),
        ("missing_seat_value", "mức 3"),
    ],
)
def test_manh_thuan_la_cau_tra_loi_thi_qua(ly_do: str, manh: str):
    assert khop_mau(ly_do, manh) is True


@pytest.mark.parametrize(
    ("ly_do", "manh"),
    [
        # Ca đích danh của #363.
        ("missing_fan_level", "hai giờ nhé"),
        ("missing_fan_level", "hai người nữa thôi"),
        ("missing_fan_level", "mai hai giờ chiều nhé"),
        ("missing_fan_level", "khoảng hai ba gì đó"),
        ("missing_temperature", "mười tám giờ rồi"),
        ("missing_temperature", "chắc mười tám hai mươi gì đó"),
        ("missing_light_target", "đèn pha bị hỏng rồi"),
        ("missing_window_side", "bên trái đường ấy"),
        ("missing_window_side", "để bên lái cái túi"),
        ("missing_volume", "to lên chút"),
    ],
)
def test_manh_mang_them_noi_dung_khac_thi_rung(ly_do: str, manh: str):
    assert khop_mau(ly_do, manh) is False


def test_toan_tu_dem_thi_rung_du_khong_tu_nao_bi_cam():
    """Đòi **ít nhất một** từ giá trị, không chỉ "mọi từ đều được phép".

    Thiếu vế ấy thì `"ừ nhé"` lọt, và ghép một câu không mang giá trị nào vào lệnh là
    đúng thứ `chap_nhan()` đã tồn tại để chặn.
    """
    assert khop_mau("missing_fan_level", "ừ nhé") is False
    assert khop_mau("missing_fan_level", "vâng ạ") is False


def test_manh_rong_thi_rung():
    for manh in ("", "   ", "..."):
        assert khop_mau("missing_fan_level", manh) is False


def test_ly_do_khong_co_mau_thi_rung_chu_khong_no():
    """Fail-closed: lý do lạ trả `False`, không `KeyError`. Nhưng xem test ngay dưới —
    `False` ở đây **không** khiến mảnh bị chặn, vì cổng chỉ chạy khi `ly_do in CO_MAU`."""
    for ly_do in ("relative_change_unsupported", "missing_door_side", "khong_ton_tai", ""):
        assert khop_mau(ly_do, "50") is False


# --- `CO_MAU`: một tập, hai vai ---------------------------------------------


def test_co_mau_nam_tron_trong_co_the_ghep():
    """`CO_MAU` vừa là "được mở mic ngắn" vừa là "bị cổng siết", nên nó không được chứa
    một lý do mà đường ghép còn không nhận — thế thì ta mở mic cho một slot không có gì
    để làm với câu trả lời."""
    assert CO_MAU <= CO_THE_GHEP


def test_missing_door_side_van_nam_ngoai():
    """Cửa xe là S2/S3 và #354 đã chốt loại khỏi phạm vi ghép; #363 ghi rõ **không** mở
    lại. Nên nó không được vào `CO_MAU` bằng bất kỳ đường nào."""
    assert "missing_door_side" not in CO_MAU
    assert "missing_door_side" not in CO_THE_GHEP


def test_ly_do_khong_co_mau_thi_khong_bi_cong_sieu_va_cung_khong_mo_mic():
    """Nửa còn lại của "một tập, hai vai": slot chưa đo được đường thoại thật thì **không
    mở mic** (không có rào thì không mở cửa) và **cũng không bị siết** (không phá thứ
    mình chưa đo được). Cả hai vế cùng đọc `CO_MAU`, nên chúng không thể lệch nhau."""
    ngoai = CO_THE_GHEP - CO_MAU
    for ly_do in ngoai:
        assert khop_mau(ly_do, "bất kỳ") is False, ly_do


# --- Đường thật qua `route_node` --------------------------------------------


@pytest.mark.parametrize(
    ("goc", "manh"),
    [
        ("Tăng quạt gió", "hai giờ nhé"),
        ("Tăng quạt gió", "hai người nữa thôi"),
        ("Tăng quạt gió", "mai hai giờ chiều nhé"),
        ("Bật đèn", "đèn pha bị hỏng rồi"),
        ("Mở cửa sổ", "để bên lái cái túi"),
    ],
)
async def test_manh_khong_khop_thi_khong_chay_lenh_nao(goc: str, manh: str):
    p = Phien()
    l1 = await p.noi(goc)
    assert l1["outcome"] == "clarify"

    l2 = await p.noi(manh)
    assert l2["outcome"] == "not_control"
    assert l2["route_reason"] == "manh_khong_khop_mau"
    assert _tools(l2) == set()


async def test_bi_chan_roi_van_tra_loi_lai_duoc():
    """Nửa quan trọng của cơ chế, và là chỗ dễ làm sai nhất.

    Lối ra NO_EXEC **không** xoá ngữ cảnh hỏi lại. Xoá đi thì câu trả lời hợp lệ của tài
    xế ở lượt sau cũng rơi xuống tra sổ tay — ta vừa chặn một lệnh sai để tạo ra một ngõ
    cụt, tức đổi lỗi này lấy lỗi khác.
    """
    p = Phien()
    await p.noi("Tăng quạt gió")
    assert (await p.noi("hai giờ nhé"))["route_reason"] == "manh_khong_khop_mau"

    ra = await p.noi("mức 2")
    assert ra["outcome"] == "control"
    assert _tools(ra) == {"set_hvac_fan_level"}


async def test_lan_nghe_hut_khong_lam_moi_moc_thoi_gian():
    """Nói lung tung nhiều lần không được kéo dài cửa sổ ngữ cảnh vô hạn — TTL vẫn đếm
    từ câu hỏi gốc, không từ lần nghe hụt gần nhất."""
    p = Phien()
    l1 = await p.noi("Tăng quạt gió")
    moc = l1["cho_ghep_luc"]
    await p.noi("hai giờ nhé")
    assert p.state["cho_ghep_luc"] == moc


# --- Cổng đứng SAU luật chấp nhận, không thay nó -----------------------------


@pytest.mark.parametrize(
    ("cau", "mong_reason"),
    [
        ("Áp suất lốp bao nhiêu", "tire_pressure_all"),
        ("Camp Mode là gì", "manual_question"),
    ],
)
async def test_cau_hoi_moi_hop_le_sau_clarify_khong_bi_cong_nay_chan(cau: str, mong_reason: str):
    """Lý do cổng phải đứng **sau** `chap_nhan`, không thay nó.

    `"Áp suất lốp bao nhiêu"` không khớp mẫu slot cửa sổ — nhưng nó cũng **không** đi
    đường ghép (đo được: `da_ghep_hoi_lai=False`). Đặt cổng trước thì nó chết oan và tài
    xế mất một câu trả lời đúng. Đặt sau thì cổng chỉ soi những mảnh mà luật cũ đã đồng ý
    ghép — chỉ siết, không chặn thêm ai.
    """
    p = Phien()
    await p.noi("Mở cửa sổ")
    ra = await p.noi(cau)
    assert ra["route_reason"] == mong_reason


async def test_lenh_moi_sau_clarify_van_chay():
    p = Phien()
    await p.noi("Mở cửa sổ")
    ra = await p.noi("Bật điều hòa")
    assert ra["outcome"] == "control"
    assert _tools(ra) == {"set_hvac_power"}


# --- Cờ mở mic: nay do `nghe_tiep` sở hữu, đọc qua payload ------------------
#
# Bốn test ở đây từng đọc `mo_mic_ngan` thẳng từ update của `route_node`. Chúng chuyển
# tầng cùng lúc quyền sở hữu chuyển: `route_node` không thấy `completed`, mà `completed`
# là ~90% lượt. Ý nghĩa từng test giữ nguyên, chỉ đổi chỗ đọc.


def _co_mo_mic(update: dict) -> bool:
    from src.services.ivi_events import assistant_response_payload

    return assistant_response_payload(dict(update))["mo_mic_ngan"]


async def test_clarify_co_mau_thi_mo_mic():
    p = Phien()
    assert _co_mo_mic(await p.noi("Tăng quạt gió")) is True


async def test_manh_khong_khop_thi_dong_mic():
    """Nghe hụt một lần thì trả quyền chủ động về tài xế."""
    p = Phien()
    await p.noi("Tăng quạt gió")
    assert _co_mo_mic(await p.noi("hai giờ nhé")) is False


async def test_clarify_khong_co_mau_thi_khong_mo_mic():
    """`relative_change_unsupported` nằm ngoài `CO_MAU` — xe **có** hỏi, nhưng không có
    rào chắn nào soi câu trả lời, nên không mở."""
    p = Phien()
    ra = await p.noi("tăng âm lượng thêm 10")
    assert ra["route_reason"] == "relative_change_unsupported"
    assert _co_mo_mic(ra) is False


async def test_luot_khong_phai_cau_hoi_lai_van_co_the_mo_mic():
    """Đổi hẳn so với bản #363: một lệnh chạy xong **cũng** mở mic, vì tài xế rất có thể
    còn lệnh nữa — đó là ~90% lượt và là cả lý do của spec cửa sổ nghe tiếp."""
    p = Phien()
    ra = await p.noi("Bật điều hòa")
    assert ra["outcome"] == "control"
    # Ở mức route, lượt chưa qua executor nên `outcome` còn là `control`; payload thật
    # thấy `completed`. Kiểm cả hai để bản đổi tên outcome không lọt.
    assert _co_mo_mic({**ra, "outcome": "completed"}) is True


# --- Câu nói ra khi nghe hụt -------------------------------------------------


async def _noi(goc: str, manh: str) -> dict:
    from src.agents.nodes.compose import compose_node

    p = Phien()
    await p.noi(goc)
    await p.noi(manh)
    return await compose_node(p.state)


async def test_nghe_hut_thi_nhac_lai_dung_cau_hoi_cu_chu_khong_tra_so_tay():
    """Slot vẫn trống y như trước, nên câu duy nhất có ích là chính câu hỏi ấy.

    Nói một câu chung chung (*"tôi không hiểu"*) là bỏ tài xế lại giữa một cuộc hỏi đáp
    mà chính xe mở ra — đúng ngõ cụt mà `CLARIFY_MESSAGES` sinh ra để phá.
    """
    ra = await _noi("Tăng quạt gió", "hai giờ nhé")
    assert "quạt gió mức mấy" in ra["speak_text"]
    assert "0 đến 3" in ra["speak_text"]
    assert "sổ tay" not in ra["speak_text"]


async def test_khong_do_loi_cho_tai_xe():
    """*"Tôi chưa nghe rõ"* chứ không phải *"bạn nói sai"*.

    Rất có thể tài xế **không hề nói với xe** — họ đang nói với người ngồi cạnh và mic
    thì vừa tự mở. Đổ lỗi cho người không làm gì sai là cách nhanh nhất để họ tắt trợ lý.
    """
    ra = await _noi("Tăng quạt gió", "hai giờ nhé")
    for xau in ("sai", "không hợp lệ", "bạn phải", "lỗi"):
        assert xau not in ra["speak_text"].lower(), ra["speak_text"]


async def test_ve_noi_bo_cau_toi_chua_lam_gi_ca_con_ve_hien_thi_giu():
    """Hai kênh, hai độ dài — cùng lý lẽ đã có ở `CLARIFY_SPEAK`: mắt đọc nhanh hơn tai.

    Ở lượt hỏi lại lần hai, vế *"tôi chưa chỉnh gì cả"* là thứ tài xế **vừa nghe cách đó
    một lượt**; đọc lại ra loa là bắt người đang lái nghe thừa. Trên màn hình thì giữ,
    vì họ có thể vừa liếc lên lần đầu.
    """
    ra = await _noi("Tăng quạt gió", "hai giờ nhé")
    assert "Tôi chưa chỉnh gì cả" not in ra["speak_text"]
    assert "Tôi chưa chỉnh gì cả" in ra["response_text"]
    assert ra["speak_text"].startswith("Tôi chưa nghe rõ.")


async def test_khong_bat_co_nhanh_so_tay():
    """`has_more_to_read` là của nhánh sổ tay. Bật nó ở đây vừa nói dối về nội dung, vừa
    kéo theo lời mời "nghe tiếp nguyên văn" mà không có gì để nghe tiếp."""
    ra = await _noi("Tăng quạt gió", "hai giờ nhé")
    assert ra["has_more_to_read"] is False


def test_ve_hoi_giu_nguyen_cau_khong_co_dang_hai_ve():
    from src.agents.nodes.compose import _ve_hoi

    assert _ve_hoi("Bạn muốn điều chỉnh cụ thể như thế nào?") == "Bạn muốn điều chỉnh cụ thể như thế nào?"
    # Không kết bằng dấu hỏi thì trả nguyên — thà nói thừa còn hơn cắt cụt câu hỏi.
    assert _ve_hoi("Vâng, tôi chưa thực hiện gì cả. Bạn cần gì thì nói lại giúp tôi nhé.") == (
        "Vâng, tôi chưa thực hiện gì cả. Bạn cần gì thì nói lại giúp tôi nhé."
    )


def test_moi_muc_clarify_speak_cua_slot_co_mau_deu_rut_gon_duoc():
    """`_ve_hoi` dựa vào dạng `<đã làm gì>. <câu hỏi?>`. Nếu ai đó thêm một mục không
    theo dạng ấy thì câu rút gọn sẽ giữ nguyên cả hai vế — không sai, nhưng lặp. Test
    này nói ra kỳ vọng để nó không trôi trong im lặng."""
    from src.agents.nodes.compose import CLARIFY_SPEAK, _ve_hoi

    for ly_do in sorted(CO_MAU):
        cau = CLARIFY_SPEAK.get(ly_do)
        assert cau is not None, f"{ly_do} mở mic mà không có bản nói riêng"
        assert cau.endswith("?"), f"{ly_do}: {cau!r}"
        assert _ve_hoi(cau) != cau, f"{ly_do} không rút gọn được: {cau!r}"

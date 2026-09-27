"""Xe hỏi lại, tài xế đáp một mảnh, và xe hiểu (issue #148 phần B).

Trước bản này: xe hỏi *"quạt gió mức mấy?"*, tài xế đáp *"mức 2"*, và lượt ấy rơi thẳng
xuống tra sổ tay — `"mức 2"` không khớp luật điều khiển nào nên theo ADR-011 nó mặc định
về manual. Đúng luật, sai ngữ cảnh.

Mọi cặp câu trong file này là **đo thật trên router** trước khi viết, không phải nghĩ ra.
Đặc biệt là các ca đối kháng: từng ca ép ra đúng một vế của luật chấp nhận, và nếu bỏ vế
ấy đi thì có một ca ở đây đỏ.
"""

import asyncio

import pytest

from src.agents.ghep_hoi_lai import CO_THE_GHEP, TTL_GIAY, chap_nhan, con_han, ghep
from src.agents.nodes.compose import CLARIFY_MESSAGES, compose_node
from src.agents.nodes.route import make_route_node
from src.agents.router import DeterministicControlRouter

#: Router dùng chung cho các test đọc thẳng, không qua `Phien`.
_ROUTER = DeterministicControlRouter()

class DongHoGia:
    """Đồng hồ tay, để TTL không phụ thuộc thời gian thật."""

    def __init__(self) -> None:
        self.gio = 1000.0

    def __call__(self) -> float:
        return self.gio

    def troi(self, giay: float) -> None:
        self.gio += giay


class Phien:
    """Một phiên: state của lượt trước chảy sang lượt sau, đúng như checkpoint LangGraph.

    `route_node` trả về **update**, LangGraph merge vào state của thread. Test này merge
    tay để chạy được nhiều lượt mà không cần dựng cả graph.
    """

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


# --- Luật chấp nhận, kiểm thuần ---------------------------------------------


@pytest.mark.parametrize(
    ("disposition", "reason", "mong"),
    [
        ("control", "deterministic_rule", True),
        # `clarify` lý do KHÁC = chuỗi slot tiến thêm một bước ("mở cửa sổ" + "bên lái").
        ("clarify", "missing_window_position", True),
        # `clarify` CÙNG lý do = mảnh vừa rồi chẳng đóng góp gì ("cảm ơn nhé").
        ("clarify", "missing_fan_level", False),
        # Ngoài dải vẫn là câu trả lời hữu ích: "quạt gió chỉ đặt được 0 đến 3".
        ("denied", "fan_level_out_of_range", True),
        # Nhưng "tôi không biết" ghép vào ra `negated_command` — trả lời "tôi không thực
        # hiện được" cho một câu "tôi không biết" là vô nghĩa.
        ("denied", "negated_command", False),
        ("not_control", "default_to_manual", False),
        ("not_control", "manual_question", False),
        ("offer", "", False),
    ],
)
def test_luat_chap_nhan(disposition: str, reason: str, mong: bool):
    assert chap_nhan(disposition, reason, "missing_fan_level") is mong


def test_khong_co_ngu_canh_thi_khong_con_han():
    assert con_han(0.0, 1000.0) is False


def test_ttl_dung_bien_va_khong_nhan_dong_ho_chay_lui():
    assert con_han(1000.0, 1000.0 + TTL_GIAY) is True
    assert con_han(1000.0, 1000.0 + TTL_GIAY + 0.001) is False
    assert con_han(1000.0, 999.0) is False


def test_ghep_chi_noi_duoi_khong_sap_xep_lai():
    assert ghep("tắt đèn", "đèn pha") == "tắt đèn đèn pha"


# --- Ca chính: lấy lại được cả ý đã mất -------------------------------------


async def test_manh_tra_loi_ghep_vao_va_lay_lai_ca_y_da_mat():
    """Ca đầu bảng của issue, và là lý do chọn ghép chuỗi thay vì vá slot có cấu trúc.

    Bảng trong issue ghi: nói lại trọn câu *"chỉnh điều hòa 18 độ"* thì lệnh chạy, **nhưng
    quạt vẫn mức 3** — ý "quạt mức 2" của lượt 1 mất hẳn. Ghép chuỗi rồi route lại lấy về
    **cả hai** ý, vì bộ luật đã biết đọc câu ghép nhiều lệnh.
    """
    p = Phien()

    assert _mo(await p.noi("chỉnh quạt gió mức 2 điều hòa")) == "clarify/missing_temperature"
    ra = await p.noi("18 độ")

    assert ra["outcome"] == "control"
    assert ra["da_ghep_hoi_lai"] is True
    # So bằng TẬP: thứ tự hai bước do bộ luật HVAC ghép quyết định, không phải thứ tự
    # tài xế nói ra, và khoá thứ tự ở đây là khoá một chi tiết không thuộc về test này.
    tools = {b.tool for b in ra["candidate_action_plan"].steps}
    assert tools == {"set_hvac_fan_level", "set_hvac_temperature"}, tools


async def test_chuoi_nhieu_slot_tu_noi_tiep_nhau():
    """Mỗi lượt ghép xong lại thành câu gốc của lượt sau — không cần đếm lượt."""
    p = Phien()

    assert _mo(await p.noi("mở cửa sổ")) == "clarify/missing_window_side"
    assert _mo(await p.noi("bên lái")) == "clarify/missing_window_position"
    ra = await p.noi("30 phần trăm")

    assert ra["outcome"] == "control"
    assert ra["candidate_action_plan"].steps[0].args == {"window": "front_left", "percent": 30}


async def test_ngoai_dai_van_duoc_ghep_vi_do_la_cau_tra_loi_huu_ich():
    """Tài xế vừa nói một con số; thứ họ cần nghe là con số nào thì được."""
    p = Phien()

    await p.noi("chỉnh quạt gió")
    ra = await p.noi("mức 5")

    assert _mo(ra) == "denied/fan_level_out_of_range"
    assert ra["da_ghep_hoi_lai"] is True


# --- Bốn chốt, mỗi chốt một ca thật -----------------------------------------


async def test_lenh_moi_tu_khop_control_thi_khong_ghep():
    """`"mở nhạc"` sau câu hỏi quạt gió là một lệnh mới.

    Đo được: ghép vào ra `clarify/missing_fan_level` — tức ghép là **nuốt mất** lệnh
    nhạc. Chốt này vì thế không phải phòng xa, nó chặn một cách hỏng có thật.
    """
    p = Phien()

    await p.noi("chỉnh quạt gió")
    ra = await p.noi("mở nhạc")

    assert ra["outcome"] == "control"
    assert ra["da_ghep_hoi_lai"] is False
    assert [b.tool for b in ra["candidate_action_plan"].steps] == ["media_control"]


async def test_cach_mot_luot_thi_khong_con_gi_de_ghep():
    """Chốt "chỉ lượt kế tiếp ngay sau", và nó không cần bộ đếm lượt nào.

    Lượt giữa không phải câu hỏi lại nên nó **quét sạch** ngữ cảnh — phép xoá ấy chính
    là chốt.
    """
    p = Phien()

    await p.noi("chỉnh quạt gió")
    giua = await p.noi("đèn cảnh báo hiển thị ở chỗ nào")
    assert giua["da_ghep_hoi_lai"] is False
    assert giua["cho_ghep_text"] == ""

    ra = await p.noi("mức 2")

    assert ra["da_ghep_hoi_lai"] is False
    assert ra["outcome"] == "not_control"


async def test_qua_han_thi_khong_ghep():
    """Câu trả lời tới sau nửa phút nhiều khả năng đang trả lời chuyện khác."""
    p = Phien()

    await p.noi("chỉnh quạt gió")
    p.dong_ho.troi(TTL_GIAY + 1)
    ra = await p.noi("mức 2")

    assert ra["da_ghep_hoi_lai"] is False
    assert ra["outcome"] == "not_control"


async def test_manh_khong_dong_gop_gi_thi_khong_ghep():
    """`"cảm ơn nhé"` ghép vào vẫn ra **cùng** lý do clarify — tức không tiến thêm bước nào."""
    p = Phien()

    await p.noi("chỉnh quạt gió")
    ra = await p.noi("cảm ơn nhé")

    assert ra["da_ghep_hoi_lai"] is False


async def test_toi_khong_biet_khong_bi_doc_thanh_lenh_phu_dinh():
    """Đo được: `"chỉnh quạt gió tôi không biết"` ra `denied/negated_command`.

    Chữ `không` bị đọc thành phủ định. Trả lời *"tôi không thực hiện được yêu cầu này"*
    cho một câu *"tôi không biết"* là vô nghĩa, nên lý do ấy nằm ngoài tập nhận.
    """
    p = Phien()

    await p.noi("chỉnh quạt gió")
    ra = await p.noi("tôi không biết")

    assert ra["da_ghep_hoi_lai"] is False


# --- Ngữ cảnh chỉ được nhớ cho những lý do ghép được -------------------------


async def test_ly_do_ngoai_danh_sach_trang_thi_khong_nho_gi_ca():
    """`relative_change_unsupported` không ghép được: `"tăng âm lượng thêm 10" + "50"`
    là một câu vô nghĩa. Nên lượt ấy không được để lại ngữ cảnh nào."""
    p = Phien()

    ra = await p.noi("tăng âm lượng thêm 10")

    assert _mo(ra) == "clarify/relative_change_unsupported"
    assert ra["cho_ghep_text"] == ""


#: Lý do `clarify` **cố ý** không ghép được, kèm lý do — phần bù của `CO_THE_GHEP`.
#:
#: Bản đầu của test dưới đây khẳng định hai tập **bằng nhau** (trừ đúng một ngoại lệ).
#: Phép so ấy đúng vào ngày viết và sai ngay khi develop mọc thêm một lý do `clarify`
#: mới — mà nó mọc thật: `missing_door_side` (#217) và hai lý do tự sửa lời (#315).
#: Một đẳng thức phải sửa mỗi lần ai đó thêm một dòng không liên quan thì cuối cùng sẽ
#: bị sửa cho xanh chứ không được đọc.
KHONG_GHEP_DUOC: dict[str, str] = {
    "relative_change_unsupported": (
        '`"tăng âm lượng thêm 10" + "50"` là một câu vô nghĩa — ghép vào là đoán, '
        "không phải điền chỗ trống."
    ),
    "missing_door_side": (
        "Cửa là S2 khi đứng yên và S3 khi xe chạy. Ghép một mảnh thành lệnh cửa là "
        "nới bề mặt sinh lệnh ở đúng miền nguy hiểm nhất — cần người ký, không phải "
        "một dòng thêm vào danh sách. Xem #354."
    ),
    "tu_sua_loi_khong_con_lenh": "Nhánh tự sửa lời (#315): không có slot nào để điền.",
    "tu_sua_loi_khong_doc_duoc": "Nhánh tự sửa lời (#315): không có slot nào để điền.",
}


def test_moi_ly_do_ghep_duoc_deu_co_loi_hoi_lai_rieng():
    """Chiều một: mọi lý do ghép được **phải** có một câu hỏi lại nêu lựa chọn/dải.

    Nhớ ngữ cảnh cho một slot mà không nêu được dải cho tài xế là mời họ đoán. Đây cũng
    là chiều đã **hỏng thật**: `6bb2713` xoá sáu câu hỏi lại khi thu #217 về phần A, và
    phần B chết lặng vì nó — không test nào bắt được, vì lúc ấy phần B cũng không còn
    trên nhánh. Xem #354.
    """
    thieu = sorted(CO_THE_GHEP - set(CLARIFY_MESSAGES))
    assert thieu == [], f"ghép được nhưng không có câu hỏi lại: {thieu}"


def test_ba_ly_do_clarify_moi_co_y_khong_ghep_duoc():
    """Chiều hai: mọi lý do `clarify` **không** ghép được phải có tên và có lý do.

    Thay cho phép so bằng nhau của bản đầu. Thêm một lý do `clarify` mới mà quên xét nó
    thì test này đỏ và bắt người thêm phải trả lời *"ghép được hay không, vì sao"* —
    chứ không lặng lẽ rơi vào một trong hai tập.
    """
    chua_xet = sorted(set(CLARIFY_MESSAGES) - CO_THE_GHEP - set(KHONG_GHEP_DUOC))
    assert chua_xet == [], (
        f"lý do clarify chưa ai quyết ghép được hay không: {chua_xet}. "
        "Thêm vào CO_THE_GHEP (kèm câu hỏi lại nêu dải) hoặc vào KHONG_GHEP_DUOC (kèm lý do)."
    )
    assert not (set(KHONG_GHEP_DUOC) & CO_THE_GHEP)


def test_clarify_khong_mo_mic_bang_co_cua_nhanh_so_tay():
    """Hai cơ chế mở mic phải ở nguyên hai cờ khác nhau. Sửa 29/08 theo #363.

    ## Test này từng khoá một điều nay đã sai

    Bản đầu tên là `test_clarify_khong_bao_gio_mo_mic_tu_dong`, khoá giả định có chữ ký
    của ADR-025: *"sau một câu hỏi lại, mic KHÔNG tự mở"*. Giả định ấy **hết hiệu lực
    29/08** — #363 chốt auto-listen ngắn 3–5 s sau `clarify`, kèm rào chắn mẫu ngữ pháp
    (`src/agents/mau_slot.py`), và ADR-025 đã có mục sửa đổi ghi lại.

    Điều đáng nói: thay đổi ấy **không** làm test cũ đỏ, vì mic mới mở bằng một cờ khác
    (`mo_mic_ngan`). Tức nó xanh trong khi mục đích viết trong docstring của nó đã sai —
    đúng lớp "test xanh đang bảo vệ nhầm thứ" mà PR #268 đã dạy một lần. Nên đổi tên và
    đổi lời, chứ không xoá: bất biến còn lại vẫn thật.

    ## Bất biến còn lại, và vì sao nó đáng giữ

    `has_more_to_read` nghĩa là **còn phần sổ tay chưa đọc**; FE lấy nó làm cửa vào
    `FOLLOW_UP_WINDOW` (#343, `wakeWordState.test.ts`). Một lượt `clarify` không có đoạn
    sổ tay nào đang đọc dở, nên bật cờ ấy ở đây là **nói dối về nội dung** để mượn tác
    dụng phụ mở mic — và nó kéo theo cả lời mời *"nghe tiếp nguyên văn"* mà không có gì
    để nghe tiếp.

    Mở mic sau `clarify` nay là việc của `mo_mic_ngan`, và cờ ấy có rào chắn riêng
    (`CO_MAU`). Trộn hai đường lại thì rào chắn mất tác dụng trong im lặng.
    """
    for cau in ("tăng âm lượng", "mở cửa sổ", "bật sưởi ghế", "giảm nhiệt độ"):
        quyet_dinh = _ROUTER.route(cau)
        assert quyet_dinh.disposition == "clarify", f"{cau!r} -> {quyet_dinh.disposition}"

    async def _chay() -> None:
        for cau in ("tăng âm lượng", "mở cửa sổ", "bật sưởi ghế"):
            ra = await compose_node({"outcome": "clarify", "route_reason": _ROUTER.route(cau).reason})
            assert ra["has_more_to_read"] is False, (
                f"{cau!r} mượn cờ nhánh sổ tay để mở mic — dùng `mo_mic_ngan`, xem #363"
            )

    asyncio.run(_chay())

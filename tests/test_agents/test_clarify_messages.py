"""Câu hỏi lại phải nêu được hệ thống đang phân vân giữa những gì — và nói rõ **chưa
làm gì cả**.

Router **đã** làm đúng phần khó của câu mơ hồ: `"tắt đèn"` trả `clarify` với lý do
`missing_light_target` — không đoán, không thực thi. Nhưng lý do đó chỉ sống trong
`RouteDecision`; câu tài xế nghe được là câu chung cho mọi slot thiếu, nên họ không
có cách nào biết cần trả lời gì.

Issue #148 thêm nửa còn lại, và nửa ấy nguy hiểm hơn: tài xế vừa nói *"chỉnh quạt gió
mức 2 điều hòa"*, nghe *"Bạn muốn đặt nhiệt độ bao nhiêu độ?"*, sẽ đinh ninh quạt đã
xong — trong khi thực tế là **0 lệnh**. Fail-closed mà người dùng không nhận ra là đã
fail-closed thì mất một nửa giá trị.
"""

import pytest

from src.agents.ghep_hoi_lai import CO_THE_GHEP, chap_nhan, ghep
from src.agents.nodes.compose import CLARIFY_MESSAGES, CLARIFY_SPEAK, OUTCOME_MESSAGES, compose_node
from src.agents.router import DeterministicControlRouter

router = DeterministicControlRouter()

#: `lý do -> (câu gốc sinh ra lý do ấy, mảnh trả lời có trong chính câu hỏi lại)`.
#:
#: Mỗi hàng đã chạy qua router thật trước khi viết. Bảng này là thứ giữ cho câu chữ
#: không trôi khỏi hành vi: nếu ai đó đổi ví dụ trong `CLARIFY_MESSAGES` thành một mảnh
#: mà router không đọc được, `test_vi_du_trong_cau_hoi_lai_that_su_chay_duoc` sẽ đỏ.
CA: dict[str, tuple[str, str]] = {
    "missing_light_target": ("Tắt đèn", "đèn trần"),
    "missing_fan_level": ("Tăng quạt gió", "mức 2"),
    "missing_temperature": ("Giảm nhiệt độ", "24 độ"),
    "missing_volume": ("Chỉnh âm lượng", "50"),
    "missing_window_side": ("Mở cửa sổ", "bên lái"),
    "missing_window_position": ("Mở cửa sổ bên lái", "30 phần trăm"),
    "missing_seat_side": ("Bật sưởi ghế", "bên lái"),
    "missing_seat_level": ("Bật sưởi ghế bên lái", "mức 2"),
    "missing_seat_value": ("Ngả ghế bên lái", "50 phần trăm"),
    # Của phần A (#217), giữ nguyên câu đầy đủ: cửa là S2/S3 nên **cố ý** không nằm
    # trong `CO_THE_GHEP` — xem `test_ba_ly_do_clarify_moi_co_y_khong_ghep_duoc`.
    "missing_door_side": ("Mở cửa bên trái", "mở cửa sau bên trái"),
}


async def _hoi_lai(text: str) -> dict:
    """Đi đúng đường thật: router quyết lý do, compose biến lý do thành lời."""
    decision = router.route(text)
    assert decision.disposition == "clarify", f"{decision.disposition}/{decision.reason}"
    return await compose_node({"outcome": "clarify", "route_reason": decision.reason})


@pytest.mark.parametrize("ly_do", sorted(CA))
async def test_cau_hoi_lai_noi_du_ba_thanh_phan(ly_do: str):
    """Chưa làm gì / thiếu cái gì / đáp thế nào.

    Khoá cả ba chứ không khoá một từ khoá: `assert "nhiệt độ" in message` là test cũ
    mặc áo mới — nó xanh với đúng câu hỏi cụt mà issue #148 sinh ra để bỏ.
    """
    goc, vi_du = CA[ly_do]
    ra = await _hoi_lai(goc)
    message = ra["response_text"]

    assert "chưa" in message.lower(), f"phải nói rõ CHƯA làm gì: {message!r}"
    assert message.rstrip().endswith("."), f"phải có ví dụ kết câu: {message!r}"
    assert f'"{vi_du}"' in message, f"phải nêu một mảnh trả lời cụ thể: {message!r}"
    assert message != OUTCOME_MESSAGES["clarify"]


@pytest.mark.parametrize("ly_do", sorted(CA))
async def test_ke_noi_ngan_hon_ke_nhin(ly_do: str):
    """Tài xế đang lái: tai chậm hơn mắt, và ví dụ trong ngoặc kép chỉ có nghĩa khi nhìn."""
    goc, _ = CA[ly_do]
    ra = await _hoi_lai(goc)

    assert len(ra["speak_text"]) < len(ra["display_text"]), (ra["speak_text"], ra["display_text"])
    assert ra["speak_text"] == CLARIFY_SPEAK[ly_do]


@pytest.mark.parametrize("ly_do", sorted(CA))
def test_vi_du_trong_cau_hoi_lai_that_su_chay_duoc(ly_do: str):
    """Ví dụ xe gợi ý phải **chạy được ngay hôm nay** — chạy trong đúng ngữ cảnh nó
    được gợi ý ra, không phải đứng một mình.

    Lịch sử của test này là chính câu chuyện #354. Bản đầu của #148 gợi ý **mảnh**
    (*"nói mỗi mức cũng được, ví dụ 'mức 2'"*), và mảnh ấy chỉ chạy khi có tầng ghép
    ngữ cảnh. Khi #217 bị thu về phạm vi phần A, tầng ghép không còn, nên tôi đổi gợi ý
    sang **câu đầy đủ** và viết test này chạy ví dụ ấy **đứng một mình** qua router.

    Phần B nay đã về (#354), nên tiền đề ấy hết hạn: mảnh lại chạy được, và gợi ý câu
    đầy đủ trong khi mảnh đủ dùng là bắt tài xế nói thừa. Test đi theo — nó chạy ví dụ
    qua **đúng đường hai lượt** mà tài xế sẽ đi: câu gốc ra `clarify`, rồi mảnh ghép vào
    câu gốc ấy phải ra một lệnh chạy được.

    `missing_door_side` là ngoại lệ có chủ ý: cửa là S2/S3 nên nó **không** nằm trong
    `CO_THE_GHEP`, gợi ý vẫn là câu đầy đủ, và phép thử vẫn là đứng một mình.
    """
    goc, vi_du = CA[ly_do]

    dang_cho = router.route(goc)
    assert dang_cho.disposition == "clarify" and dang_cho.reason == ly_do

    if ly_do not in CO_THE_GHEP:
        quyet_dinh = router.route(vi_du)
        assert quyet_dinh.disposition == "control", f"{vi_du!r} -> {quyet_dinh.disposition}/{quyet_dinh.reason}"
        return

    quyet_dinh = router.route(ghep(goc, vi_du))
    assert chap_nhan(quyet_dinh.disposition, quyet_dinh.reason or "", ly_do), (
        f"{goc!r} + {vi_du!r} -> {quyet_dinh.disposition}/{quyet_dinh.reason}"
    )


def test_every_specific_message_belongs_to_a_reason_the_router_can_produce():
    """Chặn bảng `CLARIFY_MESSAGES` mọc ra lý do router không bao giờ sinh.

    Một entry chết ở đây im lặng vô hại, nên nó sẽ sống mãi và làm người đọc tưởng
    hành vi đó tồn tại. Bảng `CA` ở đầu file là bằng chứng cho từng lý do một.
    """
    sinh_ra = {router.route(goc).reason for goc, _ in CA.values()}
    sinh_ra.add(router.route("Tăng âm lượng thêm 10").reason)
    # Hai lý do của nhánh tự sửa lời không vào bảng `CA` được: câu hỏi lại của chúng
    # cố ý **không** có ví dụ trong ngoặc kép (không có slot nào để gợi ý), nên chúng
    # trượt `test_cau_hoi_lai_noi_du_ba_thanh_phan`. Vẫn phải có mặt ở đây, không thì
    # test này đỏ ngay khi ai đó thêm chúng vào `CLARIFY_MESSAGES`.
    sinh_ra.add(router.route("Bật điều hòa à thôi").reason)
    sinh_ra.add(router.route("Bật điều hòa à thôi cái kia").reason)
    assert set(CLARIFY_MESSAGES) == sinh_ra


def test_moi_cau_noi_deu_thuoc_mot_cau_nhin():
    """`CLARIFY_SPEAK` không được mọc ra lý do mà `CLARIFY_MESSAGES` không có."""
    assert set(CLARIFY_SPEAK) <= set(CLARIFY_MESSAGES)

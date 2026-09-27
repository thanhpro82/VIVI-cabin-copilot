"""Lời từ chối S3 phải nói **vì sao** và **khi nào được**. SP-3 mục 4.

Câu hiện tại: *"Lệnh bị chặn vì trạng thái xe hiện tại không cho phép."*

Ba thứ nó không nói, và cả ba đều là thứ tài xế cần:

1. **Trạng thái nào.** "Trạng thái xe" là một cụm rỗng — xe đang chạy? đang ở số D?
   hết pin? Tài xế không biết phải làm gì để lệnh chạy được.
2. **Khi nào thì được.** Không có câu này thì lời từ chối trông như một lỗi vĩnh viễn.
**Vế thứ ba — "có cách khác không" — đã bị BỎ khỏi PR, và đó là kết luận của một phép
đo.** Bản đầu đề nghị *"bạn muốn hạ kính cho thoáng thay không?"*. @thanhpro82 bác vì
chưa có đường thực hiện; đo lại thì đúng, và tệ hơn — xem
`test_khong_de_nghi_hanh_dong_nao_chua_co_duong_thuc_hien`.

Không đổi **quyết định** an toàn nào: cùng những lệnh ấy vẫn bị chặn, `command_count`
vẫn 0. Chỉ đổi câu nói ra.
"""

from __future__ import annotations

import pytest

from src.agents.nodes.compose import OUTCOME_MESSAGES, cau_bi_chan

DANG_CHAY = {"motion": {"speed_kph": 50.0, "gear": "D"}}
DUNG_YEN_SO_D = {"motion": {"speed_kph": 0.0, "gear": "D"}}
DUNG_YEN_SO_P = {"motion": {"speed_kph": 0.0, "gear": "P"}}


def _plan(*tools: str):
    """Plan giả chỉ mang đúng thứ `cau_bi_chan` đọc: tên tool + mức an toàn."""

    class _Step:
        def __init__(self, tool: str) -> None:
            self.tool = tool
            self.safety_level = "S3"

    class _Plan:
        def __init__(self) -> None:
            self.steps = tuple(_Step(t) for t in tools)

    return _Plan()


# --- Nói VÌ SAO: số đo thật, không phải một cụm rỗng ------------------------------


def test_neu_xe_dang_chay_thi_noc_ra_toc_do_that():
    cau = cau_bi_chan(_plan("set_door_state"), DANG_CHAY)
    assert "50" in cau, f"không nêu tốc độ thật: {cau!r}"
    assert "trạng thái xe hiện tại không cho phép" not in cau


def test_neu_xe_dung_nhung_chua_ve_so_p_thi_noi_dung_chuyen_so():
    """Đứng yên mà số D vẫn là S3 — và lý do khác hẳn ca đang chạy.

    Nói "xe đang chạy" ở đây là **nói sai**: xe đứng yên. Tài xế nhìn đồng hồ thấy 0
    km/h rồi nghe máy bảo đang chạy thì mất tin vào mọi câu sau đó.
    """
    cau = cau_bi_chan(_plan("set_door_state"), DUNG_YEN_SO_D)
    assert "P" in cau
    assert "đang chạy" not in cau, f"nói sai trạng thái: {cau!r}"


# --- KHÔNG đề nghị hành động nào chưa có đường thực hiện -------------------------


@pytest.mark.parametrize("tool", ["set_door_state", "set_seat_position", "set_trunk_state", "open_app"])
def test_khong_de_nghi_hanh_dong_nao_chua_co_duong_thuc_hien(tool):
    """Bản đầu của PR #338 đề nghị *"bạn muốn hạ kính cho thoáng thay không?"* cho ca
    `"mở cửa"`. Lý lẽ nghe xuôi: `set_window_position` luôn S2 nên hạ kính làm được ngay
    cả lúc xe chạy.

    @thanhpro82 bác — đó là một **đề nghị hành động** mà chưa có đường thực hiện. Đo lại
    thì đúng, và tệ hơn mô tả:

        lượt 1  "Mở cửa bên lái" @ 45 km/h  -> blocked + lời đề nghị, cho_ghep_text=None
        lượt 2  "Ừ, hạ kính đi"             -> grounded_refusal
                                               "Tôi không tìm thấy thông tin này trong sổ tay xe."

    Tài xế nhận lời mời, **nói rõ cả hành động**, và nhận về một câu từ chối tra cứu.
    Đường ghép ngữ cảnh của #148 không cứu được: nó chỉ nhận các lý do `clarify` trong
    `CO_THE_GHEP`, mà `blocked` không nằm trong đó.

    Một đề nghị không có đường thực hiện tệ hơn im lặng — nó dạy tài xế rằng đề nghị của
    xe không đáng tin. Làm thật thì cần một flow riêng, tách thành issue.
    """
    cau = cau_bi_chan(_plan(tool), DANG_CHAY)
    assert "kính" not in cau.lower(), f"đề nghị một hành động chưa có đường thực hiện: {cau!r}"
    assert "?" not in cau, f"câu hỏi ở đây là một lời mời không có chỗ trả lời: {cau!r}"


def test_luon_noi_khi_nao_thi_duoc():
    """Thiếu vế này thì lời từ chối trông như một lỗi vĩnh viễn.

    Sau khi bỏ lời đề nghị, đây là thứ **duy nhất** tài xế mang đi được — nên nó không
    còn là "nên có" mà là phần chính của câu.
    """
    for tool in ("set_door_state", "set_seat_position", "set_trunk_state", "open_app"):
        for snapshot in (DANG_CHAY, DUNG_YEN_SO_D):
            cau = cau_bi_chan(_plan(tool), snapshot)
            assert "dừng" in cau.lower() or "đỗ" in cau.lower() or "số P" in cau, cau


# --- Không đoán khi không đọc được -----------------------------------------------


@pytest.mark.parametrize("snapshot", [None, {}, {"motion": {}}, {"motion": {"speed_kph": None, "gear": None}}])
def test_snapshot_hong_thi_lui_ve_cau_cu_chu_khong_bia_so(snapshot):
    """Fail-safe: không đọc được trạng thái thì **không** được nói một con số.

    Một câu từ chối kèm số sai còn tệ hơn một câu từ chối chung chung — nó vừa vô ích
    vừa đáng tin.
    """
    assert cau_bi_chan(_plan("set_door_state"), snapshot) == OUTCOME_MESSAGES["blocked"]


def test_plan_rong_cung_lui_ve_cau_cu():
    assert cau_bi_chan(_plan(), DANG_CHAY) == OUTCOME_MESSAGES["blocked"]


def test_xe_dung_o_so_p_ma_van_bi_chan_thi_khong_do_loi_cho_trang_thai():
    """Ca không nên xảy ra, nhưng nếu xảy ra thì đừng nói một lý do sai.

    `is_stationary` đúng ở đây, nên S3 phải tới từ một nguyên nhân khác. Nói *"xe đang
    chạy"* hay *"chưa về P"* đều là bịa.
    """
    cau = cau_bi_chan(_plan("set_door_state"), DUNG_YEN_SO_P)
    assert cau == OUTCOME_MESSAGES["blocked"]


# --- Nhiều bước: nêu bước ĐẦU bị chặn, không liệt kê hết -------------------------


def test_nhieu_buoc_thi_khong_liet_ke_het():
    """Một câu nói ra phải ngắn. Liệt kê ba tool trong một câu thoại là thứ không ai
    nghe hết — và lý do bị chặn thì chung cho cả plan, nên nêu một lần là đủ."""
    cau = cau_bi_chan(_plan("set_door_state", "set_trunk_state"), DANG_CHAY)
    assert cau == cau_bi_chan(_plan("set_door_state"), DANG_CHAY)
    assert cau.count(".") <= 2


def test_ve_khi_nao_khong_duoc_noi_thua_voi_ca_xe_da_dung():
    """Bản đầu dùng một câu chung *"khi xe dừng hẳn và về số P"* cho cả hai ca, và nó
    nói thừa với ca xe **đã** đứng yên:

        "Xe chưa về số P… Khi xe dừng hẳn và về số P thì tôi làm ngay."

    Xe đang dừng sẵn — câu ấy vừa lặp vừa sai trọng tâm. Vế *"khi nào"* phải đi theo vế
    *"vì sao"*, không phải một hằng số dùng chung.
    """
    cau = cau_bi_chan(_plan("set_trunk_state"), DUNG_YEN_SO_D)
    assert "dừng hẳn" not in cau, f"nói thừa với xe đã đứng yên: {cau!r}"
    assert "về số P" in cau

    dang_chay = cau_bi_chan(_plan("set_trunk_state"), DANG_CHAY)
    assert "dừng hẳn" in dang_chay


def test_ca_hai_ca_deu_ngan_du_de_doc_ra_loi():
    """Câu này đi thẳng ra TTS. Trần 120 ký tự là chỗ SP-3 đang kéo ngân sách nói về,
    nên một lời từ chối dài hơn thế là tự phá việc của chính SP ấy."""
    for snapshot in (DANG_CHAY, DUNG_YEN_SO_D):
        for tool in ("set_door_state", "set_trunk_state"):
            cau = cau_bi_chan(_plan(tool), snapshot)
            assert len(cau) <= 120, f"{len(cau)} ký tự: {cau!r}"


def test_motion_khong_phai_dict_thi_khong_no():
    """`snapshot` tới từ MQTT nên hình dạng của nó là **dữ liệu ngoài**.

    Bản trước dùng `(snapshot or {}).get("motion") or {}` — đúng cho `None` nhưng vẫn
    nổ `AttributeError` nếu `motion` là chuỗi hay danh sách. Ở một hàm mà cả lý do tồn
    tại là fail-safe thì để lọt một đường nổ là tự mâu thuẫn. (phoenix-mentor nêu ở #338)
    """
    for xau in ("khong phai dict", [1, 2], 42):
        assert cau_bi_chan(_plan("set_door_state"), {"motion": xau}) == OUTCOME_MESSAGES["blocked"]

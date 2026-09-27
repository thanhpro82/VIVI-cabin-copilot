"""Đ3 — xin phát một bài cụ thể.

Hai nửa, và nửa thứ hai mới là nửa khó: bài **có** trong playlist thì phải phát đúng
bài đó, còn bài **không có** thì phải từ chối **mà không đổi bài đang phát**. Trước
thay đổi này cả hai câu đều ra `media_control{action: play}` — xe phát một bài khác
trong im lặng, đúng lớp lỗi KI-001 (làm một việc khác việc được yêu cầu, không nói ra).
"""

import pytest

from src.agents.graph import build_graph
from src.agents.nodes.compose import describe_step
from src.agents.router import DeterministicControlRouter
from src.services.tool_registry import InvalidArgumentsError, validate_args
from src.services.vehicle_gateway import InProcessVehicleGateway, snapshot_dict

router = DeterministicControlRouter()


def _buoc(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


async def _run(vehicle: InProcessVehicleGateway, text: str):
    graph = build_graph(vehicle)
    return await graph.ainvoke({"query": text, "session_id": "ses-1", "vehicle_id": "veh-1", "turn_id": "turn-1"})


# ---- Router ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "track_id"),
    [
        ("Phát bài Carefree", "trk-01"),
        ("phát bài carefree", "trk-01"),
        ("PHÁT BÀI CAREFREE", "trk-01"),
        ("Mở Wallpaper", "trk-03"),
        ("Chơi bài Sneaky Snitch", "trk-05"),
        ("Nghe bài Local Forecast - Elevator", "trk-04"),
        ("Bật bài Fluffing a Duck", "trk-06"),
    ],
)
def test_goi_ten_bai_co_that_thi_phat_dung_bai_do(text, track_id):
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("media_control", {"action": "play_track", "track_id": track_id})]


def test_ten_bai_khop_bat_ke_hoa_thuong_dau_va_dau_gach():
    """So khớp chạy trên chuỗi đã `fold` (bỏ dấu, bỏ ký tự không phải chữ-số).

    Nên `"Local Forecast - Elevator"` khớp cả khi người nói không đọc dấu gạch nối,
    và chữ hoa/thường không ảnh hưởng. Playlist hiện chỉ có tên tiếng Anh nên phần
    "bỏ dấu" chưa có ca thật để chứng minh ở tầng câu — nó được kiểm ở tầng hàm.
    """
    from src.fixtures import tim_track_theo_ten

    _, buoc = _buoc("Phát bài local forecast elevator")
    assert buoc == [("media_control", {"action": "play_track", "track_id": "trk-04"})]
    assert tim_track_theo_ten("bài CÀ PHÊ")  is None
    assert tim_track_theo_ten("bài WALLPAPER")["id"] == "trk-03"


def test_ca_cau_khong_dau_thi_chua_khop_gioi_han_da_biet():
    """Giới hạn **đã biết**, ghi lại ở đây để không ai tưởng nó đã chạy.

    `"phat bai carefree"` không khớp — nhưng không phải vì tên bài: `tim_track_theo_ten`
    tìm ra bài đúng. Chỗ chết là **động từ**: `_starts_with_command` so với chuỗi
    `"phát"` có dấu, mà `normalize_vi` của router cố ý **không** bỏ dấu (bỏ dấu làm
    "bò/bỏ/bó" thành một từ — xem `src/rag/textnorm._tokens`).

    Sửa đúng chỗ là ở lớp sửa chính tả sau STT (Đ5) hoặc bảng động từ (Đ2b), không
    phải ở matcher nhạc. Khi một trong hai xong thì test này phải được đổi.
    """
    from src.fixtures import tim_track_theo_ten

    assert tim_track_theo_ten("phat bai carefree")["id"] == "trk-01", "tên bài KHÔNG phải chỗ chết"
    d, _ = _buoc("phat bai carefree")
    assert d.disposition == "not_control"


def test_hai_ban_schema_media_khong_duoc_lech():
    """Hai lớp validate cho cùng một tool — lệch nhau là lượt chết ở giữa đường.

    `validate_node` dùng `src.agents.tools.media`, tool executor dùng
    `src.services.tool_registry`. Khi `play_track` mới chỉ có ở bản registry, lượt
    "Phát bài Sneaky Snitch" ra `validation_denied` chứ không phải `completed` — router
    đúng, executor đúng, mà lượt vẫn hỏng. Test này bắt đúng cái khe đó.

    **Cập nhật #325:** khe ấy đã bị đóng ở tầng cấu trúc — `BanPlan` và `BanExecutor` nay
    là **cùng một object class** (registry là nơi khai duy nhất, `src/agents/tools/media`
    chỉ tái xuất). Nên hai assert dưới đây không còn có thể đỏ vì lệch nữa; giữ chúng làm
    lớp thứ hai, phòng khi ai đó tái lập một class song song ở đây. Phép kiểm mạnh hơn —
    `is` thay vì so schema — nằm ở `test_hai_bang_args.py`.
    """
    from typing import get_args

    from src.agents.tools.media import MediaControlArgs as BanPlan
    from src.services.tool_registry import MediaControlArgs as BanExecutor

    assert get_args(BanPlan.model_fields["action"].annotation) == get_args(
        BanExecutor.model_fields["action"].annotation
    )
    assert set(BanPlan.model_fields) == set(BanExecutor.model_fields)


def test_bai_khong_co_trong_playlist_thi_tu_choi_chu_khong_phat_bai_khac():
    d, buoc = _buoc("Phát bài See Tình")
    assert d.disposition == "denied"
    assert d.reason == "media_track_unknown"
    assert buoc == [], "từ chối mà vẫn sinh bước phát là vẫn đổi bài của người ta"


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("Bật nhạc", "play"),
        ("Phát nhạc", "play"),
        ("Phát bài hát", "play"),
        ("Tạm dừng nhạc", "pause"),
        ("Chuyển bài", "next"),
        ("Phát bài tiếp", "next"),
        ("Mở bài trước", "previous"),
    ],
)
def test_cac_lenh_nhac_cu_khong_bi_nhanh_moi_cuop(text, action):
    """Nhánh gọi-tên-bài chạy TRƯỚC các nhánh cũ, nên đây là hàng rào hồi quy của nó.

    `"phát bài hát"` là ca dễ vỡ nhất: nó chứa `bài ` và một từ đứng sau, nhưng từ ấy
    là `hát` chứ không phải tên bài — xem `_SAU_BAI_KHONG_PHAI_TEN`.
    """
    d, buoc = _buoc(text)
    assert d.disposition == "control", d
    assert buoc == [("media_control", {"action": action})]


def test_am_luong_van_di_duong_cu():
    _, buoc = _buoc("Đặt âm lượng 50 phần trăm")
    assert buoc == [("media_control", {"action": "set_volume", "volume": 50})]


# ---- Registry -------------------------------------------------------------


def test_registry_chan_track_id_bia_ra():
    """Tầng chặn thứ hai, cho đường không đi qua router (SLM, client gọi thẳng)."""
    with pytest.raises(InvalidArgumentsError):
        validate_args("media_control", {"action": "play_track", "track_id": "trk-99"})
    with pytest.raises(InvalidArgumentsError):
        validate_args("media_control", {"action": "play_track"})
    with pytest.raises(InvalidArgumentsError):
        validate_args("media_control", {"action": "play", "track_id": "trk-01"})


# ---- Câu trả lời ----------------------------------------------------------


def test_cau_tra_loi_in_ten_bai_chu_khong_in_id():
    assert describe_step("media_control", {"action": "play_track", "track_id": "trk-01"}) == "phát bài Carefree"


# ---- Trọn đường -----------------------------------------------------------


async def test_e2e_phat_dung_bai_va_xe_doi_track():
    vehicle = InProcessVehicleGateway.new()
    kq = await _run(vehicle, "Phát bài Sneaky Snitch")
    assert kq["outcome"] == "completed"
    assert snapshot_dict(vehicle.state)["media"]["track"] == "Sneaky Snitch"
    assert snapshot_dict(vehicle.state)["media"]["status"] == "playing"


async def test_e2e_bai_khong_co_thi_bai_dang_phat_giu_nguyen():
    """Nửa quan trọng hơn của issue: từ chối là **không có lệnh nào** rời khỏi xe."""
    vehicle = InProcessVehicleGateway.new()
    await _run(vehicle, "Phát bài Carefree")
    truoc = snapshot_dict(vehicle.state)["media"]
    so_lenh = vehicle.command_count

    kq = await _run(vehicle, "Phát bài See Tình")

    assert kq["outcome"] == "denied"
    assert vehicle.command_count == so_lenh, "không được publish thêm lệnh nào"
    assert snapshot_dict(vehicle.state)["media"] == truoc
    assert "See Tình" not in kq["response_text"] or "không có" in kq["response_text"]
    assert "Carefree" in kq["response_text"], "câu từ chối phải kể playlist có gì"

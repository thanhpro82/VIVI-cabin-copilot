"""Composer nói thẳng "xe bạn không có cái đó" thay vì đọc hướng dẫn cho phần cứng vắng.

## Bất biến trung tâm, và nó là một bất biến âm

**"Chưa khai báo" không được kích hoạt gì cả.** Đó là trạng thái mặc định của mọi
trang bị trên mọi chiếc xe, và sẽ mãi là trạng thái của phần lớn trường — không ai
ngồi khai đủ 65 mục. Coi "chưa biết" như "không có" thì tính năng này nói sai về gần
như mọi chiếc xe ngay hôm bật lên, mà chẳng test nào ở nơi khác thấy.

Nửa còn lại: điều kiện kích hoạt hẹp và **cố ý hẹp** — chỉ khi mọi trang bị nhận ra
được trong đoạn đều đã khai là KHÔNG CÓ. Đoạn pha để nguyên; xem docstring
`_tra_loi_thieu_trang_bi` để biết vì sao đó là lựa chọn chứ không phải thiếu sót.
"""

from __future__ import annotations

import pytest

from src.agents.nodes.compose import compose_node
from src.services import vehicle_profile

XE = "vehicle-test-trang-bi"

#: Đoạn thật, chép từ chunk sổ tay về khoang chứa đồ. Một mệnh đề điều kiện, một trang
#: bị, và nó là ca nguy hiểm: tài xế đang đứng bên đường với lốp thủng.
DOAN_LOP_DU_PHONG = (
    "Lốp dự phòng (nếu được trang bị) thì sẽ được đặt trong khoang chứa đồ phía sau. "
    "Để biết thêm chi tiết, xem phần Thay thế lốp dự phòng."
)

#: Đoạn có mệnh đề điều kiện nhưng bộ dò không nhận ra nó nói về trang bị nào — loại 2
#: theo phân loại ở `src/safety/trang_bi.py`.
DOAN_KHONG_NHAN_RA = "Bạn có thể xem bất kỳ cảnh báo lỗi của xe (nếu có) trên ứng dụng VinFast."


def _state(doan: str) -> dict:
    return {
        "intent": "manual_query",
        "outcome": "grounded_answer",
        "query": "Lốp dự phòng để ở đâu?",
        "vehicle_id": XE,
        "evidence": [{"text": doan}],
    }


@pytest.fixture(autouse=True)
def _don():
    vehicle_profile.reset()
    yield
    vehicle_profile.reset()


@pytest.mark.asyncio
async def test_khai_la_khong_co_thi_noi_thang_thay_vi_doc_huong_dan():
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": False})

    out = await compose_node(_state(DOAN_LOP_DU_PHONG))

    assert "không được trang bị" in out["speak_text"]
    assert "lốp dự phòng" in out["speak_text"].lower()
    # Và tuyệt đối không được còn chỉ đường ra khoang sau.
    assert "khoang chứa đồ phía sau" not in out["speak_text"]
    assert out["has_more_to_read"] is False


@pytest.mark.asyncio
async def test_chua_khai_bao_thi_giu_nguyen_hanh_vi_cu():
    """Bất biến quan trọng nhất của file này. Xem docstring đầu file."""
    out = await compose_node(_state(DOAN_LOP_DU_PHONG))

    assert "không được trang bị" not in out["speak_text"]
    assert "lốp dự phòng" in out["speak_text"].lower()


@pytest.mark.asyncio
async def test_khai_la_co_thi_cung_giu_nguyen_hanh_vi_cu():
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": True})

    out = await compose_node(_state(DOAN_LOP_DU_PHONG))

    assert "không được trang bị" not in out["speak_text"]


@pytest.mark.asyncio
async def test_doan_khong_co_menh_de_dieu_kien_thi_khong_dinh_toi():
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": False})

    out = await compose_node(_state("Áp suất lốp nên được kiểm tra khi lốp nguội."))

    assert "không được trang bị" not in out["speak_text"]


@pytest.mark.asyncio
async def test_menh_de_khong_nhan_ra_duoc_thi_khong_dinh_toi():
    """Loại 2 — *"cảnh báo lỗi (nếu có)"* không phải trang bị.

    Nếu bộ dò đoán bừa một mục gần giống thì composer sẽ nói "xe bạn không có X" về
    một thứ chẳng ai khai báo, và tài xế không có cách nào biết câu ấy từ đâu ra.
    """
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": False, "acc": False})

    out = await compose_node(_state(DOAN_KHONG_NHAN_RA))

    assert "không được trang bị" not in out["speak_text"]


@pytest.mark.asyncio
async def test_doan_pha_de_nguyen():
    """Một trang bị vắng, một trang bị chưa biết → không đủ chắc để cắt cả đoạn."""
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": False})
    doan = "Lốp dự phòng (nếu được trang bị) đặt ở khoang sau. Bộ công cụ bơm (nếu được trang bị) nằm cạnh đó."

    out = await compose_node(_state(doan))

    assert "không được trang bị" not in out["speak_text"]


@pytest.mark.asyncio
async def test_ca_hai_trang_bi_deu_vang_thi_noi_ca_hai_ten():
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": False, "bo_bom_hoi": False})
    doan = "Lốp dự phòng (nếu được trang bị) đặt ở khoang sau. Bộ công cụ bơm (nếu được trang bị) nằm cạnh đó."

    out = await compose_node(_state(doan))

    noi = out["speak_text"].lower()
    assert "lốp dự phòng" in noi
    assert "bộ bơm hơi" in noi
    assert " và " in noi


@pytest.mark.asyncio
async def test_khong_kem_citation_vi_cau_nay_khong_den_tu_so_tay():
    """Câu này đến từ hồ sơ xe. Bịa một citation để đỡ cho `grounded_rate` là sai."""
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": False})

    out = await compose_node(_state(DOAN_LOP_DU_PHONG))

    assert out["citations"] == []


# --- Áp suất lốp dự phòng: 420 kPa là số của một bánh có thể không tồn tại ---------


@pytest.mark.asyncio
async def test_khai_khong_co_lop_du_phong_thi_khong_doc_420():
    vehicle_profile.set_vehicle_profile(XE, trim="plus", battery="catl")
    vehicle_profile.set_vehicle_options(XE, {"lop_du_phong": False})

    out = await compose_node({"intent": "tire_pressure_query", "route_reason": "tire_pressure_spare", "vehicle_id": XE})

    assert "420" not in out["speak_text"]
    assert "không có lốp dự phòng" in out["speak_text"]


@pytest.mark.asyncio
async def test_chua_khai_thi_van_doc_420_nhu_cu():
    """Không được im lặng làm hồi quy một câu đang đúng với phần lớn xe."""
    out = await compose_node({"intent": "tire_pressure_query", "route_reason": "tire_pressure_spare", "vehicle_id": XE})

    assert "420" in out["speak_text"]

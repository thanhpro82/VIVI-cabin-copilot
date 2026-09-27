"""Nối bảng áp suất lốp curate vào đường trả lời (18/08).

## Bối cảnh

Bảng `src/safety/ap_suat_lop.py` dựng ở #124 — có provenance, checksum, test. Nhưng
đến 17/08 nó **chỉ được import bởi test**: không một dòng code chạy nào gọi tới. Hỏi
"áp suất lốp bao nhiêu?" thì lượt ấy rơi vào `manual_query`, và vì sổ tay VF9 **không
chứa con số** — nó chỉ sang cái nhãn ở khung cửa — tài xế nghe đúng một breadcrumb:

    "Xem > Vành và bánh xe > Áp suất lốp."

Đó là lời phàn nàn mở màn SPIKE-004.

## Hai bất biến file này khoá

1. **Biết cấu hình thì trả số**, và số phải khớp bảng curate chứ không phải sổ tay.
2. **Không biết cấu hình thì KHÔNG đoán**, và cũng không tự phát một câu lỗi — nó rơi
   về nhánh sổ tay để tài xế vẫn nghe được "ghi trên nhãn ở khung cửa". Đổi một câu
   tạm dùng được lấy một ngõ cụt là làm hỏng đúng thứ vừa sửa.
"""

import pytest

from src.agents.nodes.compose import compose_node
from src.agents.router import DeterministicControlRouter
from src.services import vehicle_profile

XE = "vehicle-test-lop"


@pytest.fixture
def ho_so_day_du():
    vehicle_profile.set_vehicle_profile(XE, trim="plus", battery="catl")
    yield
    vehicle_profile.reset()


@pytest.fixture
def ho_so_trong():
    vehicle_profile.reset()
    yield
    vehicle_profile.reset()


# --- Router: nhận đúng câu, và KHÔNG nhận nhầm ------------------------------------


@pytest.mark.parametrize(
    ("cau", "truc"),
    [
        ("Áp suất lốp tiêu chuẩn là bao nhiêu?", "all"),
        ("Áp suất lốp trục sau bao nhiêu?", "rear"),
        ("Bơm lốp trước bao nhiêu thì đủ?", "front"),
        ("Lốp dự phòng bơm bao nhiêu?", "spare"),
    ],
)
def test_router_nhan_dien_cau_hoi_ap_suat(cau: str, truc: str):
    d = DeterministicControlRouter().route(cau)

    assert d.intent == "tire_pressure_query"
    assert d.reason == f"tire_pressure_{truc}"


@pytest.mark.parametrize(
    "cau",
    [
        "Lốp mòn thì thay lúc nào?",
        "Khi nào cần đảo lốp?",
        "Áp suất dầu phanh bao nhiêu?",
        "Bơm xăng ở đâu?",
    ],
)
def test_router_khong_bat_nham_cau_khac(cau: str):
    """Luật đòi **cả hai** ý: áp suất/bơm VÀ lốp/bánh xe.

    Thiếu vế nào cũng phải rơi về sổ tay — bảng curate không trả lời được chúng, và
    bắt nhầm là biến một câu hỏi trả lời được thành một câu trả lời sai chủ đề.
    """
    assert DeterministicControlRouter().route(cau).intent != "tire_pressure_query"


def test_khong_noi_ro_truc_thi_tra_loi_ca_hai():
    """Hai trục có số khác nhau (260 và 270 kPa ở bản plus).

    Nói một số rồi im là để tài xế bơm sai một đầu xe.
    """
    assert DeterministicControlRouter().route("Áp suất lốp bao nhiêu?").reason == "tire_pressure_all"


# --- Composer: biết cấu hình thì trả số ------------------------------------------


@pytest.mark.asyncio
async def test_biet_cau_hinh_thi_tra_so_that(ho_so_day_du):
    out = await compose_node(
        {"intent": "tire_pressure_query", "route_reason": "tire_pressure_rear", "vehicle_id": XE}
    )

    assert "270" in out["speak_text"] and "39" in out["speak_text"]
    # Điều kiện đo phải đi kèm: 270 kPa lúc lốp nóng là một con số khác.
    assert "nguội" in out["speak_text"]
    assert out["display_text"] == out["speak_text"]


@pytest.mark.asyncio
async def test_khong_noi_ro_truc_thi_noi_ca_hai_so(ho_so_day_du):
    out = await compose_node(
        {"intent": "tire_pressure_query", "route_reason": "tire_pressure_all", "vehicle_id": XE}
    )

    assert "260" in out["speak_text"]
    assert "270" in out["speak_text"]


@pytest.mark.asyncio
async def test_lop_du_phong_tra_loi_duoc_khi_chua_khai_bao(ho_so_trong):
    """Lốp dự phòng có **một** giá trị, không phụ thuộc trim/pin.

    Nên nó không được kéo theo ràng buộc cấu hình của bảng chính — bắt tài xế khai
    báo trim để biết số của lốp dự phòng là một hàng rào không có lý do.
    """
    out = await compose_node(
        {"intent": "tire_pressure_query", "route_reason": "tire_pressure_spare", "vehicle_id": XE}
    )

    assert out is not None
    assert "420" in out["speak_text"]


# --- Fail-closed: đây mới là phần quan trọng --------------------------------------


@pytest.mark.asyncio
async def test_chua_khai_bao_cau_hinh_thi_roi_ve_so_tay(ho_so_trong):
    """Không biết `trim`/`battery` thì **không có** một con số đúng nào để nói.

    Bảng cho 240–280 kPa tuỳ tổ hợp; đọc số của bản xe khác nguy hiểm hơn không đọc gì
    (#122). Ở đây phải rơi về nhánh sổ tay — nhận ra bằng việc câu nói lấy chữ từ
    `evidence`, không phải từ bảng.
    """
    from src.rag.models import Evidence

    doan = "Áp suất lốp khuyến nghị được liệt kê trên nhãn gắn trên khung cửa của người lái."
    out = await compose_node(
        {
            "intent": "tire_pressure_query",
            "route_reason": "tire_pressure_all",
            "vehicle_id": XE,
            "outcome": "grounded_answer",
            "query": "áp suất lốp bao nhiêu",
            "evidence": [Evidence(section="Lốp", page=2, text=doan, chunk_id="c1", score=0.9)],
        }
    )

    noi = out["speak_text"]
    assert "kPa" not in noi and "PSI" not in noi, f"khong duoc doan so: {noi!r}"
    assert "nhãn" in noi or "khung cửa" in noi


@pytest.mark.asyncio
async def test_chi_khai_mot_nua_cau_hinh_cung_la_chua_du(ho_so_trong):
    """`is_complete` đòi **đủ cả hai**, kể cả khi bản `plus` cho cùng số với mọi loại pin.

    Suy luận "trim này thì pin không quan trọng" là kiến thức về nội dung bảng rò rỉ ra
    ngoài bảng — sổ tay bản sau đổi số là nó sai âm thầm.
    """
    vehicle_profile.set_vehicle_profile(XE, trim="plus", battery=None)
    from src.rag.models import Evidence

    out = await compose_node(
        {
            "intent": "tire_pressure_query",
            "route_reason": "tire_pressure_all",
            "vehicle_id": XE,
            "outcome": "grounded_answer",
            "query": "áp suất lốp",
            "evidence": [Evidence(section="Lốp", page=2, text="Xem nhãn trên khung cửa.", chunk_id="c1", score=0.9)],
        }
    )

    assert "kPa" not in out["speak_text"]


# --- Ba lỗi @thanhpro82 tìm ở review #168 -----------------------------------------


@pytest.mark.parametrize(
    "cau",
    [
        "cảm biến áp suất lốp báo lỗi thì làm sao",
        "áp suất lốp thấp thì đèn nào sáng",
        "lốp non hơi có nguy hiểm không",
        "bơm lốp ở đâu",
    ],
)
def test_cau_ve_lop_nhung_khong_hoi_so_thi_de_so_tay_tra_loi(cau: str):
    """Luật bản đầu chỉ đòi *có ý áp suất* + *có ý lốp*, nên nó bắt cả bốn câu này.

    Cả bốn đều là câu **sổ tay trả lời được**, và bảng curate thì không — nó chỉ biết
    một con số. Bắt rộng nghĩa là cướp chúng khỏi nhánh sổ tay rồi đọc cho tài xế
    "260 kPa" cho câu hỏi về đèn cảnh báo.
    """
    assert DeterministicControlRouter().route(cau).intent != "tire_pressure_query"


def test_sau_trong_sau_khi_chay_khong_phai_truc_sau():
    """`\bsau\b` trần bắt cả trạng từ thời gian.

    Hậu quả đi ngược đúng lý lẽ của chính luật này: nói một trục rồi im là để tài xế
    bơm sai đầu còn lại. Neo vào danh từ bộ phận (`trục|bánh|lốp` + `trước|sau`).
    """
    assert DeterministicControlRouter().route("áp suất lốp bao nhiêu sau khi chạy đường dài").reason == (
        "tire_pressure_all"
    )


@pytest.mark.asyncio
async def test_tra_so_thi_phai_kem_citation(ho_so_day_du):
    """`grounded_rate` đếm `grounded` chỉ khi `citation_count > 0` (`services/metrics.py`).

    Trả số mà không citation thì mỗi lượt hỏi áp suất lốp **kéo KPI xuống đúng lúc tính
    năng chạy đúng**. Và `R-1`/`R-3` của demo checklist đòi câu trả lời sổ tay phải chỉ
    được mục + trang — `R-5` là câu duy nhất đọc một con số an toàn, nên nó càng phải có.

    Provenance có sẵn trong bảng curate, không phải bịa: mỗi ô mang `chunk_id` và `page`.
    """
    out = await compose_node(
        {
            "intent": "tire_pressure_query",
            "route_reason": "tire_pressure_rear",
            "vehicle_id": XE,
            "turn_id": "turn-test",
        }
    )

    assert out["citations"], "tra so ma khong chi duoc nguon"
    c = out["citations"][0]
    assert c.chunk_id and c.page, "citation phai tro ve chunk that trong so tay"
    assert "KPA" in c.excerpt.upper(), f"excerpt phai la nguyen van o bang: {c.excerpt!r}"

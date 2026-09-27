"""Luật manual_question chỉ bắt câu HỎI VỀ XE. Câu xã giao có dấu hỏi rơi xuống
classifier (SP-2 §2.3). Bằng chứng giữ đường tắt: 41/41 câu hoi-nhu-tai-xe-v1."""

import json

import pytest

from src.agents.question import co_tu_vung_xe
from src.agents.router import DeterministicControlRouter, normalize_vi

router = DeterministicControlRouter()

#: 4/15 câu chitchat của SP-0 bị `manual_question` nuốt (run 20260822T030757).
CHITCHAT_CO_DAU_HOI = [
    "Xin chào, hôm nay khỏe không?",
    "Cậu tên gì thế?",
    "Xe này đi đường dài có êm không nhỉ?",
    "Đi Đà Lạt chơi thích không",
]


@pytest.mark.parametrize(
    "text", ["Áp suất lốp bao nhiêu là đủ?", "Đèn cảnh báo hình cục pin nghĩa là gì?", "Sạc xe ở nhà thế nào?"]
)
def test_cau_hoi_ve_xe_co_tu_vung(text):
    assert co_tu_vung_xe(normalize_vi(text))


@pytest.mark.parametrize("text", ["Xin chào, hôm nay khỏe không?", "Cậu tên gì thế?", "Đi Đà Lạt chơi thích không"])
def test_cau_xa_giao_khong_co_tu_vung(text):
    assert not co_tu_vung_xe(normalize_vi(text))


@pytest.mark.parametrize("text", [CHITCHAT_CO_DAU_HOI[0], CHITCHAT_CO_DAU_HOI[1], CHITCHAT_CO_DAU_HOI[3]])
def test_xa_giao_co_dau_hoi_roi_xuong_classifier(text):
    quyet_dinh = router.route(text)
    assert quyet_dinh.reason == "default_to_manual", quyet_dinh


def test_xe_nay_di_duong_dai_van_la_cau_ve_xe():
    """Có chữ "xe" → đường tắt sổ tay là ĐÚNG: classifier không được giành ca này.
    Spec chấp nhận: 1/4 câu SP-0 ở lại sổ tay vì nó thật sự nói về xe."""
    assert router.route(CHITCHAT_CO_DAU_HOI[2]).reason == "manual_question"


def test_41_cau_hoi_nhu_tai_xe_van_di_duong_tat():
    """Bằng chứng bắt buộc của spec §2.3: không mất một ca đường tắt nào."""
    mat = []
    for line in open("eval/datasets/manual/hoi-nhu-tai-xe-v1/cases.jsonl", encoding="utf-8"):
        if not line.strip():
            continue
        cau = json.loads(line)["question"]
        if router.route(cau).reason == "default_to_manual" and not co_tu_vung_xe(normalize_vi(cau)):
            mat.append(cau)
    assert mat == [], f"câu hỏi về xe bị mất đường tắt vì thiếu từ vựng: {mat}"

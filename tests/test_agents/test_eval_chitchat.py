"""Eval chitchat (SP-2 §4): classifier như sản phẩm, generator + cổng cho MỌI ca
được chấm chitchat — kể cả ca bẫy, để ô `bẫy→chitchat` là số thật."""

import json
from pathlib import Path

from src.agents.eval import run_chitchat_eval


class ClsTheoNhan:
    def __init__(self, bang):
        self._bang = bang

    def classify(self, t):
        return self._bang.get(t, "manual")


class SinhCoDinh:
    def __init__(self, reply):
        self._reply = reply

    def reply(self, t):
        return self._reply


def _ds(tmp_path: Path) -> Path:
    cases = [
        {"case_id": "C1", "input_text": "Chào buổi sáng nha", "expected_route": "chitchat", "expected_hanh_vi": "xa_giao", "source": "t"},
        {"case_id": "C2", "input_text": "Nóng quá trời ơi", "expected_route": "control", "expected_hanh_vi": "khong_toi_generator", "source": "t"},
    ]
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    return p


def test_bay_lot_vao_generator_bi_dem(tmp_path):
    cls = ClsTheoNhan({"Chào buổi sáng nha": "chitchat", "Nóng quá trời ơi": "chitchat"})  # bẫy bị chấm chitchat
    run = run_chitchat_eval(_ds(tmp_path), tmp_path / "r", cls, SinhCoDinh("Chào bạn!"))
    m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert m["cong_cung_bay_sang_chitchat"] == 1
    assert m["ma_tran"]["control->chitchat"] == 1
    assert m["qua_cong"]["qua"] == 2  # generator vẫn chạy trên cả hai (ghi thật, không che)


def test_cong_vo_duoc_dem_theo_ten_lop(tmp_path):
    cls = ClsTheoNhan({"Chào buổi sáng nha": "chitchat", "Nóng quá trời ơi": "control"})
    run = run_chitchat_eval(_ds(tmp_path), tmp_path / "r", cls, SinhCoDinh("Chạy 450 km một lần sạc!"))
    m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert m["cong_cung_bay_sang_chitchat"] == 0
    assert m["qua_cong"]["so_ky_thuat"] == 1
    assert m["n_chitchat_that"] == 1
    assert set(m["do_tre_ms"]) == {"classify", "sinh", "tong"}
    for ten in ("manifest.json", "case_results.jsonl", "metrics.json"):
        assert (run / ten).exists()

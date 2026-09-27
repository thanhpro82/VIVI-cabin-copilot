"""Bộ `bao-loi-2408` tự nhất quán — và mốc của nó không được nói dối.

Bộ này khác các dataset khác ở chỗ mỗi ca mang sẵn `trang_thai_2608`: nó **đang** hỏng
hay **đang** đúng trên `develop` @ `bab0fc6`. Hai con số `di_lui` / `da_sua` của
`--mode bao-loi` đều đọc từ trường ấy, nên một ca ghi sai mốc làm cả hai con số sai —
im lặng, và theo hướng dễ chịu nhất (một ca đang hỏng ghi nhầm là `hong` thì không ai
biết, nhưng một ca đang đúng ghi nhầm là `hong` sẽ **giấu** một lần đi lùi thật).

Test dưới đây là cái chốt cho việc thêm ca mới: ghi mốc sai thì đỏ ngay.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from src.agents.eval import (
    DEFAULT_BAO_LOI_DATASET,
    DEFAULT_BAO_LOI_GATE,
    load_cases,
    load_cong_hoi_quy,
    promote_bao_loi,
    run_bao_loi_eval,
    score_case,
)
from src.agents.router import DeterministicControlRouter

TRUONG_BAT_BUOC = ("case_id", "domain", "input_text", "expected", "mien", "dong_goc", "trang_thai_2608")


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return load_cases(DEFAULT_BAO_LOI_DATASET)


def test_moi_ca_du_truong_bat_buoc(cases: list[dict]) -> None:
    for case in cases:
        thieu = [ten for ten in TRUONG_BAT_BUOC if ten not in case]
        assert not thieu, f"{case.get('case_id', '???')} thiếu trường {thieu}"
        assert case["trang_thai_2608"] in {"hong", "dung"}, case["case_id"]
        assert set(case["expected"]) == {"disposition", "intent", "tools"}, case["case_id"]


def test_case_id_khong_trung(cases: list[dict]) -> None:
    trung = [cid for cid, n in Counter(c["case_id"] for c in cases).items() if n > 1]
    assert not trung, f"case_id trùng: {trung}"


def test_ca_ghi_dung_khong_duoc_di_lui(cases: list[dict]) -> None:
    """Ca ghi `dung` phải thật sự pass. Đây là cổng cứng, và nó chỉ gác **một chiều**.

    Chiều ngược lại — ca ghi `hong` mà nay pass — **không** được phép làm đỏ suite: đó
    chính là lúc ai đó vừa sửa xong bug, và một bộ đo bắt đền người sửa đúng thì lần sau
    không ai chạy nó nữa. Chiều ấy hiện ra ở `metrics.da_sua` của `--mode bao-loi`, nơi
    nó là **tiến độ** chứ không phải lỗi.

    Cái giá của việc nới một chiều: thêm một ca mới mà ghi nhầm `hong` trong khi nó đang
    pass thì test này không bắt được. Bù lại bằng `test_moc_khong_ghi_thua_ca_dang_pass`
    dưới đây, chỉ chạy trên các ca `hong` — nó **cảnh báo** qua `da_sua` chứ không chặn.

    **Cổng còn gác cả ca đã promote** (review #302). Một ca `hong` từng được xác nhận
    pass rồi tái hỏng thì trước đây chỉ rụng khỏi `da_sua` và suite vẫn xanh — tức lỗi
    vừa sửa quay lại mà không ai biết. `cong_hoi_quy.json` là danh sách ấy; nó chỉ được
    cộng thêm bằng `--mode bao-loi --promote`, kèm `run_id` + `commit`.
    """
    router = DeterministicControlRouter()
    trong_cong = set(load_cong_hoi_quy(DEFAULT_BAO_LOI_GATE))
    di_lui = []
    for case in cases:
        if case["trang_thai_2608"] != "dung" and case["case_id"] not in trong_cong:
            continue
        row = score_case(router, case)
        if not (row["disposition_ok"] and row["intent_ok"] and row["tool_exact"]):
            di_lui.append(
                f"{case['case_id']} {case['input_text']!r}: "
                f"{'đã promote' if case['case_id'] in trong_cong else 'ghi=dung'} nhưng nay FAIL "
                f"(router trả {row['predicted']['disposition']}/{row['predicted']['reason']})"
            )
    assert not di_lui, "Đi lùi so với mốc 2608 — bản vá vừa làm hỏng thứ đang chạy được:\n" + "\n".join(di_lui)


def test_moc_khong_ghi_thua_ca_dang_pass(cases: list[dict], record_property) -> None:
    """Ca ghi `hong` mà nay pass thì ghi lại, **không** làm đỏ suite.

    Danh sách này là thứ người sửa đọc để biết mình vừa được cái gì; nó cũng là chỗ lộ ra
    một ca mới bị ghi nhầm mốc. Chỉ khi nó dài bất thường mà không ai vừa sửa gì thì mới
    đáng nghi.
    """
    router = DeterministicControlRouter()
    da_sua = [
        case["case_id"]
        for case in cases
        if case["trang_thai_2608"] == "hong"
        and all(score_case(router, case)[k] for k in ("disposition_ok", "intent_ok", "tool_exact"))
    ]
    record_property("da_sua", da_sua)


def test_run_ghi_du_ba_file_va_hai_danh_sach(tmp_path: Path) -> None:
    run_dir = run_bao_loi_eval(DEFAULT_BAO_LOI_DATASET, tmp_path, run_id="test-run")
    for ten in ("manifest.json", "metrics.json", "case_results.jsonl"):
        assert (run_dir / ten).exists(), ten
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    # Ở mốc thì cả hai rỗng. `di_lui` rỗng là cổng cứng; `da_sua` rỗng chỉ đúng cho tới
    # khi PR đầu tiên sửa được ca nào — lúc ấy test trên mới là chỗ phải cập nhật, không
    # phải chỗ này, nên ở đây chỉ khẳng định kiểu dữ liệu và bất biến của `di_lui`.
    assert metrics["di_lui"] == [], f"đi lùi so với mốc: {metrics['di_lui']}"
    assert isinstance(metrics["da_sua"], list)
    assert metrics["dat"] + len(metrics["di_lui"]) <= metrics["total"]
    assert all("dat" in o for o in metrics["by_domain"].values())


def test_thu_muc_run_la_bat_bien(tmp_path: Path) -> None:
    run_bao_loi_eval(DEFAULT_BAO_LOI_DATASET, tmp_path, run_id="test-run")
    with pytest.raises(FileExistsError):
        run_bao_loi_eval(DEFAULT_BAO_LOI_DATASET, tmp_path, run_id="test-run")


# --- Vòng đời: ca đã sửa phải thành cổng hồi quy (review #302) ---------------


def test_ca_da_promote_ma_tai_hong_thi_vao_di_lui(tmp_path: Path) -> None:
    """Điều kiện approve #1. Đây là toàn bộ khác biệt giữa regression suite và dashboard.

    Dựng một dataset hai ca: một ca `hong` đang **fail** thật, rồi giả vờ nó đã được
    promote. Trước cơ chế này, một ca như thế chỉ vắng mặt khỏi `da_sua` và không ai
    biết; giờ nó phải nằm trong `di_lui`, tức CI đỏ.
    """
    ca = {
        "case_id": "GIA-001",
        "domain": "gia",
        "input_text": "xyzzy không phải lệnh gì cả",
        "expected": {"disposition": "control", "intent": "hvac_power", "tools": []},
        "mien": "hvac",
        "dong_goc": "T00",
        "trang_thai_2608": "hong",
    }
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps(ca, ensure_ascii=False) + "\n", encoding="utf-8")

    # Chưa promote: ca fail nhưng không phải "đi lùi" — nó vốn đã hỏng từ mốc.
    cong_rong = tmp_path / "cong_rong.json"
    cong_rong.write_text('{"ca": {}}', encoding="utf-8")
    m1 = json.loads(
        (run_bao_loi_eval(dataset, tmp_path / "r1", run_id="x", gate=cong_rong) / "metrics.json").read_text("utf-8")
    )
    assert m1["di_lui"] == []

    # Đã promote: cùng một ca fail y hệt, giờ là đi lùi.
    cong = tmp_path / "cong.json"
    cong.write_text('{"ca": {"GIA-001": {"run_id": "r0", "commit": "deadbee"}}}', encoding="utf-8")
    m2 = json.loads(
        (run_bao_loi_eval(dataset, tmp_path / "r2", run_id="x", gate=cong) / "metrics.json").read_text("utf-8")
    )
    assert m2["di_lui"] == ["GIA-001"]
    assert m2["cong_hoi_quy"] == ["GIA-001"]


def test_ca_can_quyet_dinh_khong_bao_gio_tu_vao_cong(tmp_path: Path) -> None:
    """Điều kiện approve #2: nhãn còn tranh chấp thì không được khoá thành cổng.

    Ca vẫn được chấm và vẫn đếm vào `da_sua` — chỉ không tự động thành gate.
    """
    ca = {
        "case_id": "GIA-002",
        "domain": "gia",
        "input_text": "Bật điều hòa",
        "expected": {
            "disposition": "control",
            "intent": "hvac_power",
            "tools": [{"tool": "set_hvac_power", "args": {"enabled": True}}],
        },
        "mien": "hvac",
        "dong_goc": "T00",
        "trang_thai_2608": "hong",
        "can_quyet_dinh": True,
    }
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps(ca, ensure_ascii=False) + "\n", encoding="utf-8")
    cong = tmp_path / "cong.json"
    cong.write_text('{"ca": {}}', encoding="utf-8")

    run_dir = run_bao_loi_eval(dataset, tmp_path / "r", run_id="x", gate=cong)
    metrics = json.loads((run_dir / "metrics.json").read_text("utf-8"))
    assert metrics["da_sua"] == ["GIA-002"], "vẫn phải đếm vào tiến độ"
    assert metrics["ung_vien_promote"] == [], "nhưng không được là ứng viên gate"

    assert promote_bao_loi(run_dir, cong, commit="abc1234") == []
    assert json.loads(cong.read_text("utf-8"))["ca"] == {}


def test_promote_ghi_lai_run_va_commit_va_khong_ghi_de(tmp_path: Path) -> None:
    """Điều kiện approve #3: baseline chỉ đổi bằng một bằng chứng có id, xem lại được.

    Và mục đã có **không** bị ghi đè: lần promote đầu tiên là lần đúng để trích dẫn, nên
    chạy lại trên một run mới hơn không được lặng lẽ đổi nguồn gốc.
    """
    ca = {
        "case_id": "GIA-003",
        "domain": "gia",
        "input_text": "Bật điều hòa",
        "expected": {
            "disposition": "control",
            "intent": "hvac_power",
            "tools": [{"tool": "set_hvac_power", "args": {"enabled": True}}],
        },
        "mien": "hvac",
        "dong_goc": "T00",
        "trang_thai_2608": "hong",
    }
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps(ca, ensure_ascii=False) + "\n", encoding="utf-8")
    cong = tmp_path / "cong.json"

    run1 = run_bao_loi_eval(dataset, tmp_path / "r", run_id="run-mot", gate=cong)
    assert promote_bao_loi(run1, cong, commit="1111111") == ["GIA-003"]
    ghi = json.loads(cong.read_text("utf-8"))["ca"]["GIA-003"]
    assert ghi["run_id"] == "run-mot"
    assert ghi["commit"] == "1111111"
    assert ghi["promoted_at"]

    run2 = run_bao_loi_eval(dataset, tmp_path / "r", run_id="run-hai", gate=cong)
    assert promote_bao_loi(run2, cong, commit="2222222") == [], "idempotent"
    assert json.loads(cong.read_text("utf-8"))["ca"]["GIA-003"]["run_id"] == "run-mot", "không ghi đè nguồn gốc"


def test_khong_promote_tu_mot_run_dang_di_lui(tmp_path: Path) -> None:
    """Promote từ một run còn đỏ là đóng băng đúng lúc hệ đang hỏng."""
    ca_dung = {
        "case_id": "GIA-004",
        "domain": "gia",
        "input_text": "xyzzy không phải lệnh gì cả",
        "expected": {"disposition": "control", "intent": "hvac_power", "tools": []},
        "mien": "hvac",
        "dong_goc": "T00",
        "trang_thai_2608": "dung",
    }
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps(ca_dung, ensure_ascii=False) + "\n", encoding="utf-8")
    cong = tmp_path / "cong.json"

    run_dir = run_bao_loi_eval(dataset, tmp_path / "r", run_id="do", gate=cong)
    with pytest.raises(ValueError, match="đi lùi"):
        promote_bao_loi(run_dir, cong)


def test_cong_that_chi_chua_case_id_co_that(cases: list[dict]) -> None:
    """File cổng trong repo không được trỏ tới ca đã bị xoá/đổi tên khỏi dataset."""
    co_that = {case["case_id"] for case in cases}
    la = sorted(set(load_cong_hoi_quy(DEFAULT_BAO_LOI_GATE)) - co_that)
    assert not la, f"cổng hồi quy trỏ tới case_id không có trong dataset: {la}"

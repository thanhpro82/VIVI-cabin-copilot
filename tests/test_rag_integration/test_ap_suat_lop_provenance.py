"""Đối chiếu bảng áp suất lốp curate với **chunk thật** của sổ tay (issue #124).

Đánh dấu `slow` và skip khi không có chunk store, cùng lý do với
`test_vf9_lookup.py`: `.gitignore` loại cả `data/` vì corpus sổ tay không được phân
phối lại, nên CI không bao giờ có nó. Đây là điểm yếu có thật của lớp test này và
không nên giấu — nó chỉ chạy trên máy đã dựng index.

    pytest tests/test_rag_integration/test_ap_suat_lop_provenance.py -m slow

## Vì sao phải dựng lại cấu trúc ô, không chỉ tìm chuỗi con

`"260 KPA,38 PSI, (SDI)"` xuất hiện ở **hai** ô khác nhau của bảng nguồn: PLUS/trước
và ECO/sau. Phép kiểm "chuỗi có nằm trong text không" sẽ xanh kể cả khi bảng curate
chép đúng số vào sai ô — mà chép sai ô đúng là lỗi nguy hiểm nhất ở đây, vì nó cho ra
một con số có thật, trông hợp lý, cho sai chiếc xe.

Nên test này tách bảng nguồn thành ô, lấy thứ tự cột từ **dòng tiêu đề** chứ không ghi
cứng, rồi so hai chiều với bảng curate. Sổ tay bản mới đảo cột ECO/PLUS thì test đỏ
thay vì âm thầm đồng ý.

Lưu ý: cấm parse bảng ở **runtime** (#124) là để tránh hỏng im lặng lúc tài xế đang
hỏi. Parse trong test thì ngược lại — hỏng ở đây là hỏng ồn ào, đúng lúc cần.
"""

import re
import sqlite3
from pathlib import Path

import pytest

from src.safety.ap_suat_lop import doc_bang

pytestmark = pytest.mark.slow

INDEX = Path("data/rag/vf9_2026_vi")
CHUNKS_DB = INDEX / "chunks.db"
MANIFEST = INDEX / "manifest.json"

#: `240 KPA,35 PSI, (SDI)` — bắt cả phần tên pin để biết ô thuộc loại pin nào. Tên pin
#: là tuỳ chọn vì ô lốp dự phòng không có.
_GIA_TRI = re.compile(r"(\d+)\s*KPA\s*,\s*(\d+)\s*PSI\s*,?\s*(?:\(\s*(SDI|CATL)\s*\))?", re.IGNORECASE)

#: Tên cột trong sổ tay → `trim` trong bảng curate. `Dự phòng` xử lý riêng.
_COT_SANG_TRIM = {"ECO": "eco", "PLUS": "plus"}


@pytest.fixture(scope="module")
def chunk_nguon() -> sqlite3.Row:
    # Không đủ nếu chỉ hỏi `chunks.db` có tồn tại không: chạy cả bộ test **tạo ra** một
    # `data/rag/vf9_2026_vi/chunks.db` rỗng ở đúng đường dẫn này (mở store bằng đường dẫn
    # mặc định là sqlite3 tự sinh file). Trên máy chưa dựng index, guard cũ nhìn thấy file
    # ấy, không skip, rồi đỏ với "không còn chunk ..." — một lỗi bịa, đúng thứ mà lớp test
    # này tồn tại để **không** làm.
    #
    # `manifest.json` là thứ chỉ `src.rag.cli ingest` mới ghi, nên nó phân biệt được
    # "chưa dựng index" với "index thật".
    if not MANIFEST.exists() or not CHUNKS_DB.exists():
        pytest.skip("chưa dựng index — chạy scripts/prepare_vf9_index.ps1")
    bang = doc_bang()
    con = sqlite3.connect(CHUNKS_DB)
    con.row_factory = sqlite3.Row
    try:
        if con.execute("select count(*) from document_chunks").fetchone()[0] == 0:
            pytest.skip("chunk store rỗng — chạy scripts/prepare_vf9_index.ps1")
        row = con.execute(
            "select id, page, checksum, text from document_chunks where id = ?", (bang.chunk_id,)
        ).fetchone()
    finally:
        con.close()
    # Tới đây store có thật và có dữ liệu, nên thiếu chunk là tín hiệu thật: sổ tay đã
    # ingest lại và đoạn bảng áp suất không còn ở đó. Phải đỏ, không được skip.
    assert row is not None, f"không còn chunk {bang.chunk_id} trong sổ tay đã ingest"
    return row


def _o_cua_bang_nguon(text: str) -> dict[tuple[str, str, str], tuple[int, int]]:
    """Tách hai hàng áp suất của bảng nguồn thành `{(trim, battery, axle): (kpa, psi)}`.

    Hàng "Phía trước" có 3 ô (ECO, PLUS, Dự phòng), hàng "Phía Sau" chỉ có 2 — lốp dự
    phòng không có bánh sau. Đó là lý do không thể dùng một vòng lặp đều cho cả bảng,
    và cũng là lý do #124 nói "không parse tự động ở runtime".
    """
    dong = {d.strip() for d in text.split("\n")}
    tieu_de = next(d for d in dong if d.startswith("Khác nhau"))
    truoc = next(d for d in dong if "Áp suất lốp lạnh" in d)
    sau = next(d for d in dong if d.startswith("Phía Sau"))

    # Thứ tự cột lấy từ tiêu đề, không ghi cứng: đảo cột ở bản sổ tay mới phải làm test
    # đỏ, chứ không được im lặng gán số của PLUS cho ECO.
    cot = [c.strip() for c in tieu_de.split("|")][1:]

    ket_qua: dict[tuple[str, str, str], tuple[int, int]] = {}

    def _nap(o_text: str, ten_cot: str, axle: str) -> None:
        trim = _COT_SANG_TRIM.get(ten_cot.upper())
        if trim is None:  # cột "Dự phòng" — kiểm riêng ở test lốp dự phòng
            return
        for kpa, psi, pin in _GIA_TRI.findall(o_text):
            assert pin, f"ô {ten_cot}/{axle} thiếu tên pin: {o_text!r}"
            ket_qua[(trim, pin.lower(), axle)] = (int(kpa), int(psi))

    # "Áp suất lốp lạnh | Phía trước | <ECO> | <PLUS> | <Dự phòng>"
    o_truoc = [c.strip() for c in truoc.split("|")][2:]
    for ten_cot, o_text in zip(cot, o_truoc, strict=True):
        _nap(o_text, ten_cot, "front")

    # "Phía Sau | <ECO> | <PLUS>"  — ngắn hơn một ô, nên strict=True sẽ nổ; cắt cot theo
    # đúng số ô thật và khẳng định phần bị cắt đúng là cột lốp dự phòng.
    o_sau = [c.strip() for c in sau.split("|")][1:]
    assert cot[len(o_sau) :] == ["Dự phòng"], f"hàng Phía Sau thiếu cột lạ: {cot[len(o_sau) :]}"
    for ten_cot, o_text in zip(cot[: len(o_sau)], o_sau, strict=True):
        _nap(o_text, ten_cot, "rear")

    return ket_qua


def test_chunk_nguon_chua_doi_ban(chunk_nguon):
    """Checksum khác nghĩa là sổ tay đã ingest lại và số **có thể** đã đổi.

    Không tự sửa bảng curate cho khớp: đọc lại bảng trong sổ tay bản mới, chép tay, rồi
    cập nhật cả `checksum`. Test này đỏ là một yêu cầu đọc, không phải một số cần vá.
    """
    bang = doc_bang()
    assert chunk_nguon["checksum"] == bang.checksum
    assert chunk_nguon["page"] == bang.page


def test_bang_curate_khop_tung_o_voi_so_tay(chunk_nguon):
    """So **hai chiều**: không thiếu ô, không thừa ô, không lệch giá trị."""
    bang = doc_bang()
    nguon = _o_cua_bang_nguon(chunk_nguon["text"])
    curate = {khoa: (o.kpa, o.psi) for khoa, o in bang.o.items()}
    assert curate == nguon


def test_chuoi_nguyen_van_cua_moi_o_co_that_trong_so_tay(chunk_nguon):
    """Yêu cầu nguyên văn của #124.

    Yếu hơn test trên (không phân biệt được ô) nhưng bắt lớp khác: chuỗi bị chỉnh cho
    "đẹp" — bỏ dấu phẩy, đổi `KPA` thành `kPa` — thì nó không còn là nguyên văn nữa, và
    một trích dẫn không nguyên văn là trích dẫn không kiểm chứng được.
    """
    text = chunk_nguon["text"]
    for khoa, o in sorted(doc_bang().o.items()):
        assert o.nguyen_van in text, f"{khoa}: {o.nguyen_van!r} không có nguyên văn trong chunk"


def test_lop_du_phong_khop_cot_du_phong_va_khong_co_hang_sau(chunk_nguon):
    """Lốp dự phòng đúng một ô ở hàng "Phía trước"; hàng "Phía Sau" không có cột này."""
    dong = {d.strip() for d in chunk_nguon["text"].split("\n")}
    truoc = next(d for d in dong if "Áp suất lốp lạnh" in d)
    sau = next(d for d in dong if d.startswith("Phía Sau"))

    o_du_phong = [c.strip() for c in truoc.split("|")][-1]
    kpa, psi, pin = _GIA_TRI.findall(o_du_phong)[0]
    dp = doc_bang().du_phong
    assert (int(kpa), int(psi)) == (dp.kpa, dp.psi)
    assert pin == "", "ô lốp dự phòng không phân biệt loại pin"
    assert dp.nguyen_van in chunk_nguon["text"]
    assert len([c for c in sau.split("|")]) == 3, "hàng Phía Sau phải chỉ có ECO và PLUS"

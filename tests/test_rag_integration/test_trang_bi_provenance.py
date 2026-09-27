"""Đối chiếu danh mục trang bị với **chunk thật** của sổ tay.

`slow`, và skip khi chưa dựng index — cùng lý do với `test_ap_suat_lop_provenance.py`:
`.gitignore` loại cả `data/` vì corpus sổ tay không được phân phối lại, nên CI không
bao giờ có nó. Nói thẳng ra đây thay vì giấu: bảo hiểm này chỉ chạy trên máy đã ingest.

    pytest tests/test_rag_integration/test_trang_bi_provenance.py -m slow

## Lớp này bắt được gì mà `tests/test_safety/test_trang_bi.py` không bắt được

Lớp kia kiểm bảng có **tự mâu thuẫn** không. Lớp này kiểm bảng có nói về **đúng cuốn
sổ tay** không. Hai hỏng khác nhau:

- một cụm từ chép sai chính tả vẫn qua được mọi kiểm tra cấu trúc, rồi nằm chết trong
  danh mục và không bao giờ khớp gì;
- ingest sổ tay bản mới đổi cách diễn đạt thì cụm cũ hết khớp, mà chẳng ai biết.

Cả hai đều hỏng **im lặng**: bộ dò chỉ trả list rỗng, và composer đi tiếp như thường.
Không có lớp này thì một danh mục chết vẫn xanh suốt.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from src.safety.trang_bi import DAU_DIEU_KIEN, doc_danh_muc, nhan_dien

pytestmark = pytest.mark.slow

INDEX = Path("data/rag/vf9_2026_vi")
CHUNKS_DB = INDEX / "chunks.db"
MANIFEST = INDEX / "manifest.json"

#: Ngưỡng phủ sóng. Đo 19/08 được 89% (131/147). Đặt sàn ở 85% chứ không ở con số đo
#: được: sát quá thì mỗi lần ingest lại đỏ vì nhiễu, còn thấp quá thì không bắt được
#: hồi quy. Và **không** có trần: xem docstring `trang_bi.py` — 100% sẽ là dấu hiệu
#: xấu, nhưng nó là dấu hiệu để người đọc suy nghĩ, không phải điều kiện test.
SAN_PHU_SONG = 0.85


@pytest.fixture(scope="module")
def van_ban() -> list[str]:
    # `manifest.json` là thứ chỉ `src.rag.cli ingest` ghi, nên nó phân biệt "chưa dựng
    # index" với "index thật". Chạy cả bộ test có thể tự sinh một `chunks.db` rỗng ở
    # đúng đường dẫn này, nên kiểm tra riêng sự tồn tại của file là không đủ.
    if not MANIFEST.exists() or not CHUNKS_DB.exists():
        pytest.skip("chưa dựng index — chạy scripts/prepare_vf9_index.ps1")
    con = sqlite3.connect(CHUNKS_DB)
    try:
        rows = con.execute("select text from document_chunks").fetchall()
    finally:
        con.close()
    if not rows:
        pytest.skip("chunk store rỗng — chạy scripts/prepare_vf9_index.ps1")
    return [re.sub(r"\s+", " ", r[0] or "") for r in rows]


def test_phien_ban_so_tay_khop_manifest(van_ban):
    """Danh mục ghi rõ nó curate từ bản nào. Ingest bản khác thì phải biết ngay."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ban = json.dumps(manifest, ensure_ascii=False)
    assert doc_danh_muc().phien_ban_so_tay in ban


def test_moi_trang_bi_deu_khop_it_nhat_mot_menh_de_that(van_ban):
    """Mục không bao giờ khớp là mục chết — và nó chết **im lặng**.

    Đây là lớp bắt lỗi chép sai cụm từ. Một `"đèn sương mù phia trước"` thiếu dấu vẫn
    qua hết kiểm tra cấu trúc, rồi không khớp gì suốt đời.
    """
    thay: set[str] = set()
    for t in van_ban:
        thay.update(nhan_dien(t))
    chet = sorted({tb.id for tb in doc_danh_muc()} - thay)
    assert chet == [], f"những mục này không khớp mệnh đề nào trong sổ tay thật: {chet}"


def test_phu_song_khong_tut_duoi_san(van_ban):
    tong = nhan = 0
    for t in van_ban:
        for m in DAU_DIEU_KIEN.finditer(t):
            tong += 1
            nhan += bool(nhan_dien(t[max(0, m.start() - 90) : m.end()]))
    assert tong >= 100, f"chỉ thấy {tong} mệnh đề điều kiện — sổ tay đã đổi nhiều, xem lại danh mục"
    assert nhan / tong >= SAN_PHU_SONG, f"phủ sóng tụt còn {nhan}/{tong} = {nhan / tong:.0%}"


def test_cum_tu_khong_khop_o_doan_khong_co_menh_de_dieu_kien(van_ban):
    """Bộ dò chỉ nhìn phía trước dấu, nên đoạn không có dấu phải trả rỗng — kể cả khi
    nó nhắc tên trang bị.

    `"lốp dự phòng"` xuất hiện ở nhiều chunk không điều kiện (bảng thông số, cảnh báo
    chung). Khớp mù trên toàn văn sẽ gán nhầm cả những đoạn ấy, và composer khi đó cắt
    một câu trả lời hoàn toàn hợp lệ.
    """
    khong_dau = [t for t in van_ban if not DAU_DIEU_KIEN.search(t)]
    assert khong_dau, "mọi chunk đều có mệnh đề điều kiện — không thể đúng"
    assert all(nhan_dien(t) == [] for t in khong_dau)

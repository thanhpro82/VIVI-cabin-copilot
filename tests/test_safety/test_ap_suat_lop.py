"""Lớp khoá **chạy được trên CI** cho bảng áp suất lốp curate (issue #124).

Lớp còn lại — đối chiếu với chunk thật của sổ tay — nằm ở
`tests/test_rag_integration/test_ap_suat_lop_provenance.py` và **không** chạy trên CI,
vì `.gitignore` loại cả `data/`: corpus sổ tay không được phân phối lại nên runner
không có chunk store. Nói thẳng ra ở đây để không ai đọc màu xanh của CI thành "số đã
được đối chiếu với sổ tay".

Vậy lớp này khoá được gì? Nó khoá **tính nhất quán nội tại** — thứ duy nhất kiểm được
mà không cần corpus. Ca hỏng thật nó bắt: ai đó sửa `kpa` trong JSON mà quên sửa
`nguyen_van` (hoặc ngược lại), tức bảng và bằng chứng của chính nó rời nhau.
"""

import json
import re

import pytest

from src.safety.ap_suat_lop import doc_bang, tra_ap_suat, tra_lop_du_phong

#: Một ô của sổ tay: `240 KPA,35 PSI, (SDI)` — dấu phẩy và khoảng trắng đi lung tung
#: nên đừng siết, nhưng thứ tự kPa trước PSI thì cố định.
_O = re.compile(r"(\d+)\s*KPA\s*,\s*(\d+)\s*PSI", re.IGNORECASE)

_KPA_SANG_PSI = 0.1450377


def test_du_tam_to_hop_va_khong_trung():
    """8 tổ hợp = 2 trim × 2 pin × 2 trục. Thiếu một ô là một câu hỏi không trả lời được."""
    bang = doc_bang()
    assert set(bang.o) == {(t, b, a) for t in ("eco", "plus") for b in ("sdi", "catl") for a in ("front", "rear")}


@pytest.mark.parametrize("khoa", sorted(doc_bang().o))
def test_moi_o_nhat_quan_voi_chuoi_nguyen_van_cua_chinh_no(khoa):
    """Số phải đọc ra được từ chính chuỗi nguyên văn — không phải chép rời hai chỗ.

    Đây là ca hỏng thật mà lớp CI này tồn tại để bắt: sửa `kpa: 260` thành `280` mà
    `nguyen_van` vẫn là `"260 KPA,38 PSI, (CATL)"`. Bảng lúc đó vẫn "hợp lệ", vẫn trả
    lời trôi chảy, và sai 20 kPa.
    """
    o = doc_bang().o[khoa]
    khop = _O.search(o.nguyen_van)
    assert khop is not None, f"{khoa}: nguyên văn không có dạng '<số> KPA, <số> PSI'"
    assert int(khop.group(1)) == o.kpa
    assert int(khop.group(2)) == o.psi


@pytest.mark.parametrize("khoa", sorted(doc_bang().o))
def test_ten_pin_trong_nguyen_van_khop_voi_khoa(khoa):
    """Ô của SDI phải mang chữ SDI. Bắt ca chép đúng số nhưng gán nhầm loại pin.

    Không bắt được ca gán nhầm **trim** — `260 KPA,38 PSI, (SDI)` là ô của cả
    PLUS/trước lẫn ECO/sau, hai chuỗi giống hệt nhau. Chỉ lớp `slow` dựng lại cấu trúc
    ô mới phân biệt được, và đó chính là lý do lớp ấy tồn tại.
    """
    _, battery, _ = khoa
    assert battery.upper() in doc_bang().o[khoa].nguyen_van.upper()


@pytest.mark.parametrize("khoa", sorted(doc_bang().o))
def test_psi_khop_kpa_trong_sai_so_lam_tron(khoa):
    """PSI trong sổ tay là số đã làm tròn, nên chỉ đòi lệch < 1.

    Không tự tính PSI rồi ghi vào bảng: sổ tay ghi 280 kPa = 40 PSI trong khi phép quy
    đổi ra 40,6. Số của sổ tay mới là số phải đọc. Kiểm tra này chỉ để bắt lỗi gõ kiểu
    380 thay vì 280 — sai một chữ số thì PSI lệch xa ngay.
    """
    o = doc_bang().o[khoa]
    assert abs(o.kpa * _KPA_SANG_PSI - o.psi) < 1.0


def test_lop_du_phong_tach_rieng_va_khong_co_banh_sau():
    """Bảng nguồn cho lốp dự phòng đúng **một** ô: hàng "Phía Sau" không có cột này."""
    dp = tra_lop_du_phong()
    assert (dp.kpa, dp.psi) == (420, 61)
    assert abs(dp.kpa * _KPA_SANG_PSI - dp.psi) < 1.0


def test_tra_dung_o_cho_eco_catl():
    """Ca của issue #122: xe ECO + pin CATL thì trước 260, sau 280.

    Cũng là ca cho thấy vì sao không được nói một con số chung: cùng câu hỏi ấy, xe
    ECO + SDI là 240/260 — lệch 20 kPa cả hai trục.
    """
    assert tra_ap_suat("eco", "catl", "front").kpa == 260
    assert tra_ap_suat("eco", "catl", "rear").kpa == 280
    assert tra_ap_suat("eco", "sdi", "front").kpa == 240
    assert tra_ap_suat("eco", "sdi", "rear").kpa == 260


def test_bon_cau_hinh_cho_bon_bo_so_khac_nhau():
    """Chốt rằng bảng thật sự phân biệt bốn cấu hình, chứ không phải bốn khoá trỏ về
    cùng một số — nếu ai đó "đơn giản hoá" bảng thì test này đỏ trước khi tài xế nghe."""
    truoc_sau = {
        (t, b): (tra_ap_suat(t, b, "front").kpa, tra_ap_suat(t, b, "rear").kpa)
        for t in ("eco", "plus")
        for b in ("sdi", "catl")
    }
    assert truoc_sau == {
        ("eco", "sdi"): (240, 260),
        ("eco", "catl"): (260, 280),
        ("plus", "sdi"): (260, 270),
        ("plus", "catl"): (260, 270),
    }


@pytest.mark.parametrize(
    "khoa",
    [("ECO", "catl", "front"), ("eco", "lithium", "front"), ("eco", "catl", "spare"), ("", "", "")],
)
def test_to_hop_la_thi_bao_loi_chu_khong_doan(khoa):
    """Không có nhánh "gần đúng". Đoán ở đây nghĩa là đọc cột của xe khác."""
    with pytest.raises(ValueError, match="không hợp lệ"):
        tra_ap_suat(*khoa)


def test_khong_co_gia_tri_mac_dinh_nao_trong_json():
    """Fail-closed thuộc về người gọi, nên bảng không được lén cài một cột mặc định.

    #123 phải tự chặn khi chưa biết cấu hình xe. Nếu bảng có sẵn `default` thì cái chặn
    ấy trở thành tuỳ chọn, và một ngày nào đó ai đó sẽ bỏ qua nó.
    """
    raw = json.loads((__import__("pathlib").Path("src/safety/ap_suat_lop.json")).read_text(encoding="utf-8"))
    assert "default" not in raw
    assert "mac_dinh" not in raw
    assert all(set(h) == {"trim", "battery", "axle", "kpa", "psi", "nguyen_van"} for h in raw["hang"])


def test_provenance_du_de_truy_nguoc():
    """Mỗi giá trị phải chỉ được về chunk và trang — yêu cầu của #124.

    `checksum` là thứ khiến lớp `slow` phát hiện được sổ tay đã đổi bản: nó so với
    checksum trong chunk store, không phải với chính nó.
    """
    bang = doc_bang()
    assert bang.chunk_id == "chunk_1148033_003"
    assert bang.page == 2
    assert bang.checksum == "87a4e6b0b68bb180"
    assert bang.edition == "VF9_23-25_VN_VI_2.4 [New UI]"
    assert bang.dieu_kien_do == "lốp nguội"
    for o in bang.o.values():
        assert (o.chunk_id, o.page) == (bang.chunk_id, bang.page)

"""Parser cho `llama-server --list-devices`.

Vì sao parser này ở Python chứ không ở PowerShell (nơi nó ra đời): CI chạy
`ubuntu-latest`, nên một test Pester sẽ bị bỏ qua đúng ở chỗ cần nó nhất. Và repo này
đã bị PowerShell cắn một lần — `scripts/bootstrap_mqtt_secrets.ps1` dùng
`RandomNumberGenerator.Fill`, API chỉ có ở PS 7, nên chết trên máy chỉ có 5.1.

Đầu vào là **output của một chương trình bên ngoài**, tức thứ đổi được mà không ai
trong nhóm biết. Điểm Thành nêu ở PR #114: parser phải lấy được ordinal + **tên đầy
đủ** mà không phụ thuộc cứng vào cụm `(<n> MiB ...)`.
"""

import pytest

from scripts.vulkan_devices import chon_thiet_bi, doc_thiet_bi

# --- Fixture: output that tu cac nha san xuat khac nhau ---------------------

AMD = """Available devices:
  Vulkan0: Radeon RX 5500M (4080 MiB, 3445 MiB free)
  Vulkan1: AMD Radeon(TM) Graphics (4037 MiB, 3835 MiB free)
"""

NVIDIA = """Available devices:
  Vulkan0: NVIDIA GeForce RTX 3060 Laptop GPU (6144 MiB, 5800 MiB free)
"""

INTEL = """Available devices:
  Vulkan0: Intel(R) Arc(TM) A770 Graphics (16384 MiB, 15800 MiB free)
  Vulkan1: Intel(R) UHD Graphics 770 (2048 MiB, 1900 MiB free)
"""

#: Ca Thanh yeu cau ro: output **thieu phan memory**. Chua gap that, nhung do la mot
#: chuoi do llama.cpp in ra — no doi duoc o bat ky ban nao ma khong ai bao truoc.
KHONG_MEMORY = """Available devices:
  Vulkan0: Radeon RX 5500M
  Vulkan1: AMD Radeon(TM) Graphics
"""

BACKEND_KHAC = """Available devices:
  CUDA0: NVIDIA GeForce RTX 4090 (24564 MiB, 23000 MiB free)
  Vulkan0: NVIDIA GeForce RTX 4090 (24564 MiB, 23000 MiB free)
"""


def test_doc_duoc_amd_hai_thiet_bi():
    ds = doc_thiet_bi(AMD)
    assert [(d.backend, d.ordinal, d.name) for d in ds] == [
        ("Vulkan", 0, "Radeon RX 5500M"),
        ("Vulkan", 1, "AMD Radeon(TM) Graphics"),
    ]


def test_ten_co_ngoac_khong_bi_cat():
    """Bug thật gặp 13/08: regex cũ cắt `.+?` tới dấu ngoặc **đầu tiên**, nên
    `AMD Radeon(TM) Graphics` thành `AMD Radeon` và không khớp được gì nữa."""
    ds = doc_thiet_bi(INTEL)
    assert [d.name for d in ds] == ["Intel(R) Arc(TM) A770 Graphics", "Intel(R) UHD Graphics 770"]


def test_nvidia():
    ds = doc_thiet_bi(NVIDIA)
    assert [(d.ordinal, d.name) for d in ds] == [(0, "NVIDIA GeForce RTX 3060 Laptop GPU")]


def test_khong_co_phan_memory_van_doc_duoc():
    """Đây là yêu cầu của Thành: **không** phụ thuộc cứng vào `(<n> MiB ...)`."""
    ds = doc_thiet_bi(KHONG_MEMORY)
    assert [(d.ordinal, d.name) for d in ds] == [
        (0, "Radeon RX 5500M"),
        (1, "AMD Radeon(TM) Graphics"),
    ]


def test_giu_backend_khac_vulkan():
    """Không lọc sẵn theo backend: caller quyết. Lọc ở đây thì ngày thêm CUDA/SYCL
    phải sửa parser, mà parser là chỗ ít lý do phải đổi nhất."""
    ds = doc_thiet_bi(BACKEND_KHAC)
    assert [(d.backend, d.ordinal) for d in ds] == [("CUDA", 0), ("Vulkan", 0)]


@pytest.mark.parametrize("rac", ["", "   ", "Available devices:\n", "loi: khong tim thay gi\n"])
def test_output_rac_tra_ve_rong_chu_khong_vo(rac):
    assert doc_thiet_bi(rac) == []


# --- Chon thiet bi ----------------------------------------------------------


def test_chon_theo_ten_khong_phan_biet_hoa_thuong():
    d = chon_thiet_bi(doc_thiet_bi(AMD), "radeon(tm) graphics")
    assert (d.backend, d.ordinal) == ("Vulkan", 1)
    assert d.spec == "Vulkan1"


def test_khop_nhieu_hon_mot_thi_bao_loi_chu_khong_doan():
    """`"Radeon"` khớp cả hai thiết bị AMD. Đoán bừa ở đây nghĩa là đo iGPU rồi báo
    cáo là dGPU — đúng lớp lỗi mà cả PR #114 sinh ra để chặn."""
    with pytest.raises(ValueError, match="khop 2"):
        chon_thiet_bi(doc_thiet_bi(AMD), "Radeon")


def test_khong_khop_cai_nao_thi_bao_loi_kem_danh_sach():
    with pytest.raises(ValueError) as loi:
        chon_thiet_bi(doc_thiet_bi(AMD), "RTX 4090")
    # Thong bao phai liet ke thu dang co, khong thi nguoi dung phai tu chay lai lenh.
    assert "Radeon RX 5500M" in str(loi.value)


def test_cli_in_mot_dong_spec_tab_ten(capsys):
    """PowerShell tách dòng này bằng TAB. Gọi `llama-server` hai lần chỉ để lấy tên là
    phí một lần nạp driver Vulkan — vài giây trên máy lạnh."""
    import io
    import sys as _sys

    from scripts.vulkan_devices import main

    stdin_cu = _sys.stdin
    _sys.stdin = io.StringIO(AMD)
    try:
        assert main(["--match", "RX 5500M"]) == 0
    finally:
        _sys.stdin = stdin_cu
    assert capsys.readouterr().out.strip() == "Vulkan0\tRadeon RX 5500M"


def test_cli_that_bai_thi_ma_thoat_khac_khong(capsys):
    """PowerShell đọc `$LASTEXITCODE`. In lỗi ra stdout mà vẫn thoát 0 là để script
    gọi tiếp với một chuỗi rác làm `--device`."""
    import io
    import sys as _sys

    from scripts.vulkan_devices import main

    stdin_cu = _sys.stdin
    _sys.stdin = io.StringIO(AMD)
    try:
        assert main(["--match", "Radeon"]) == 1
    finally:
        _sys.stdin = stdin_cu
    assert "khop 2" in capsys.readouterr().err

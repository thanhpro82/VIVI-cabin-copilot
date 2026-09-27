"""Đọc `llama-server --list-devices` và chọn thiết bị **theo tên**.

Ở Python chứ không ở PowerShell — nơi logic này ra đời — vì hai lý do:

1. **CI chạy `ubuntu-latest`.** Một test Pester sẽ bị bỏ qua đúng ở chỗ cần nó nhất.
2. **Repo này đã bị PowerShell cắn một lần**: `scripts/bootstrap_mqtt_secrets.ps1` dùng
   `RandomNumberGenerator.Fill`, API chỉ có ở PS 7, nên chết trên máy chỉ có 5.1.

Vì sao cần dò theo tên: số thứ tự `VulkanN` **không ổn định**. Ngày 13/08 trên chính
máy đo, `Vulkan0`/`Vulkan1` đảo so với chú thích ghi cứng trong script — nghĩa là mọi
con số gắn nhãn "dGPU" trước đó không tự chứng minh được. Xem ADR-016.

    python -m scripts.vulkan_devices --match "RX 5500M" --bin <llama-server>
    Vulkan0	Radeon RX 5500M
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

#: Một dòng thiết bị: `  Vulkan0: <tên>` — phần đuôi để riêng.
#:
#: Cố ý **không** đòi cụm `(<n> MiB ...)`. Đó là điểm Thành nêu ở PR #114, và nó đúng:
#: cụm ấy là thứ `llama.cpp` in ra, tức thứ đổi được ở bất kỳ bản nào mà không ai báo
#: trước. Bắt buộc nó là biến một thay đổi hiển thị thành một lỗi "không tìm thấy GPU".
_DONG = re.compile(r"^\s*([A-Za-z]+)(\d+):\s*(.+?)\s*$")

#: Đuôi dung lượng, gỡ ra **nếu có**. Neo `$` để không cắt nhầm ngoặc giữa tên —
#: `AMD Radeon(TM) Graphics` phải giữ nguyên, đó là bug đã gặp thật ngày 14/08.
_DUOI_MEMORY = re.compile(r"\s*\(\s*\d+\s*MiB\b[^)]*\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ThietBi:
    backend: str
    ordinal: int
    name: str

    @property
    def spec(self) -> str:
        """Chuỗi đưa vào `--device` của llama-server, ví dụ `Vulkan1`."""
        return f"{self.backend}{self.ordinal}"


def doc_thiet_bi(text: str) -> list[ThietBi]:
    """Mọi thiết bị trong output, **không lọc theo backend**.

    Lọc ở đây thì ngày thêm CUDA/SYCL phải sửa parser, mà parser là chỗ ít lý do phải
    đổi nhất. Caller quyết định nó muốn backend nào.
    """
    ds: list[ThietBi] = []
    for dong in text.splitlines():
        khop = _DONG.match(dong)
        if khop is None:
            continue
        backend, so, phan_con_lai = khop.group(1), khop.group(2), khop.group(3)
        ten = _DUOI_MEMORY.sub("", phan_con_lai).strip()
        if ten:
            ds.append(ThietBi(backend=backend, ordinal=int(so), name=ten))
    return ds


def chon_thiet_bi(ds: list[ThietBi], can_tim: str) -> ThietBi:
    """Thiết bị duy nhất có tên chứa `can_tim`; khác một là lỗi.

    **Không đoán khi mơ hồ.** Chọn bừa giữa hai thiết bị nghĩa là đo iGPU rồi báo cáo
    là dGPU — đúng lớp lỗi mà cả thay đổi này sinh ra để chặn.
    """
    needle = can_tim.casefold()
    khop = [d for d in ds if needle in d.name.casefold()]
    if len(khop) == 1:
        return khop[0]
    co = ", ".join(f"{d.spec}: {d.name}" for d in ds) or "(khong co thiet bi nao)"
    raise ValueError(f"'{can_tim}' khop {len(khop)} thiet bi (can dung 1). Co: {co}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dò thiết bị llama-server theo tên")
    ap.add_argument("--match", required=True, help="một phần tên thiết bị, vd 'RX 5500M'")
    ap.add_argument("--bin", default=None, help="đường dẫn llama-server; mặc định đọc stdin")
    args = ap.parse_args(argv)

    if args.bin:
        ket_qua = subprocess.run([args.bin, "--list-devices"], capture_output=True, text=True)
        # llama.cpp in danh sách ra stderr ở một số bản, stdout ở bản khác — gộp cả hai
        # thay vì đoán, vì đoán sai thì ra "không tìm thấy GPU" chứ không ra lỗi thật.
        text = (ket_qua.stdout or "") + "\n" + (ket_qua.stderr or "")
    else:
        text = sys.stdin.read()

    try:
        d = chon_thiet_bi(doc_thiet_bi(text), args.match)
        # Mot dong, hai truong, ngan bang TAB: goi llama-server hai lan chi de lay ten
        # la phi mot lan nap driver Vulkan (vai giay tren may lanh).
        print(f"{d.spec}	{d.name}")
    except ValueError as loi:
        print(str(loi), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

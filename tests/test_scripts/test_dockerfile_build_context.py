"""Dockerfile chỉ được `COPY` những file **thật sự có** trong build context.

Lớp lỗi này CI hiện không bắt được, và nó đã xảy ra thật: PR #214 thêm dòng
`COPY requirements.txt requirements-rag.txt requirements-voice.txt ./` trong khi
`requirements-voice.txt` chưa tồn tại trên nhánh. Docker dừng ngay tại bước COPY,
còn `lint-and-test` vẫn xanh — vì nó **không build image**. @thanhpro82 bắt được
bằng mắt khi review.

Test này chạy trong job có sẵn: không cần Docker, không cần artifact voice (vốn nằm
ngoài git), không cần tải torch. Nó chỉ đọc `Dockerfile` rồi đối chiếu với đĩa — đủ
để chặn đúng lớp lỗi ấy ở chỗ rẻ nhất.

**Không thay thế được một lần build thật.** Nó không biết `pip install` có chạy
được không, model E5 có tải về không, hay chốt chặn artifact voice có qua không.
Những thứ đó cần `docker compose build` chạy tay, và bằng chứng phải là log trên
đúng commit đang chờ merge.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_GOC = Path(__file__).resolve().parents[2]
_DOCKERFILE = _GOC / "Dockerfile"

#: `COPY --from=<stage>` lấy file từ stage trước, không phải từ build context trên đĩa.
_COPY_TU_STAGE = re.compile(r"^\s*COPY\s+--from=", re.IGNORECASE)
_COPY = re.compile(r"^\s*COPY\s+(?P<phan>.+)$", re.IGNORECASE)
_CO_CHON = re.compile(r"^--[\w-]+(=|$)")


def _nguon_copy() -> list[tuple[int, str]]:
    """Mọi đường dẫn nguồn của các lệnh `COPY` đọc từ build context, kèm số dòng."""
    nguon: list[tuple[int, str]] = []
    for so_dong, dong in enumerate(_DOCKERFILE.read_text(encoding="utf-8").splitlines(), start=1):
        if _COPY_TU_STAGE.match(dong):
            continue
        khop = _COPY.match(dong)
        if khop is None:
            continue
        phan = [p for p in khop.group("phan").split() if not _CO_CHON.match(p)]
        # Phần tử cuối là ĐÍCH trong image, không phải nguồn trên đĩa.
        nguon.extend((so_dong, p) for p in phan[:-1])
    return nguon


def test_dockerfile_khong_copy_file_khong_ton_tai():
    """Mọi `COPY <nguồn>` phải trỏ tới thứ có thật trong repo.

    `COPY . .` được bỏ qua: nó chép cả context nên luôn tồn tại.
    """
    thieu = [
        f"Dockerfile:{so_dong} COPY {p}"
        for so_dong, p in _nguon_copy()
        if p not in {".", "./"} and "*" not in p and not (_GOC / p).exists()
    ]
    assert not thieu, "Dockerfile COPY file không có trong repo — `docker build` sẽ dừng ngay tại đó:\n" + "\n".join(
        thieu
    )


@pytest.mark.parametrize("ten", ["requirements.txt", "requirements-rag.txt", "requirements-voice.txt"])
def test_ba_file_requirements_deu_con_do(ten: str):
    """Ba file, ba mục đích — và cả ba đều bị `COPY` đích danh.

    Tách riêng khỏi test trên để lúc đỏ thì thông điệp nói thẳng file nào biến mất,
    thay vì bắt người đọc dò lại Dockerfile.
    """
    assert (_GOC / ten).is_file(), f"{ten} bị `COPY` trong Dockerfile nhưng không có trong repo"


def test_dockerignore_khong_loai_mat_thu_ma_dockerfile_can():
    """`.dockerignore` loại `*.md`, nên `requirements*.txt` phải được giữ lại tường minh.

    Đây là cái bẫy thứ hai của cùng một lớp lỗi: file **có** trên đĩa nhưng bị
    `.dockerignore` loại khỏi context, và `docker build` báo y hệt như khi thiếu file.
    Dòng `!requirements.txt` trong `.dockerignore` tồn tại đúng vì lý do đó.
    """
    luat = [
        d.strip()
        for d in (_GOC / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if d.strip() and not d.strip().startswith("#")
    ]
    for _so_dong, p in _nguon_copy():
        if p in {".", "./"} or "*" in p:
            continue
        bi_loai = [luat_bi for luat_bi in luat if not luat_bi.startswith("!") and luat_bi.rstrip("/") == p]
        if bi_loai:
            assert f"!{p}" in luat, f"{p} bị .dockerignore loại ({bi_loai}) nhưng Dockerfile vẫn COPY nó"

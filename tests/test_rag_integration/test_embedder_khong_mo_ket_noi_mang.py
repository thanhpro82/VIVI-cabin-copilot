"""Nạp E5 embedder không được mở kết nối ra Internet (ADR-001).

Đánh dấu `slow` và skip khi máy chưa có cache model, cùng lý do với hai test
anh em trong thư mục này: CI không cài extra `rag` nên không bao giờ có model.
Đây là điểm yếu có thật của lớp test này — bằng chứng offline chỉ được sinh ra
bởi người chạy local, không bao giờ bởi CI.

    pytest tests/test_rag_integration/test_embedder_khong_mo_ket_noi_mang.py -m slow

## Vì sao cần test này dù `local_files_only=True` đã có từ 2026-08-13

`local_files_only=True` quyết định có **tải file** hay không; nó không ngăn hub
client **mở session**. Đo ngày 2026-08-21: dựng `E5Embedder()` vẫn để lại một
kết nối HTTPS ESTABLISHED tới CDN của huggingface.co (2600:9000::/28,
CloudFront) suốt vòng đời tiến trình, dù weight đã nằm sẵn trong cache và cờ
`local_files_only` đang bật. Nên phép kiểm phải là **quan sát kết nối thật**,
không phải đọc lại cờ cấu hình — đọc cờ chính là thứ đã xanh suốt tám ngày
trong khi kết nối vẫn mở.
"""

import pytest

from src.offline_guard import ket_noi_ngoai_loopback, quan_sat_duoc_ket_noi

pytestmark = pytest.mark.slow


def test_nap_embedder_that_khong_de_lai_ket_noi_ra_ngoai_loopback() -> None:
    if not quan_sat_duoc_ket_noi():
        pytest.skip("không quan sát được kết nối (thiếu psutil hoặc HĐH từ chối)")
    try:
        from src.rag.embed import E5Embedder
    except ImportError:
        pytest.skip("chưa cài extra `rag`")

    truoc = ket_noi_ngoai_loopback()
    try:
        E5Embedder()
    except Exception as loi:  # noqa: BLE001 - máy chưa có cache model
        pytest.skip(f"chưa có cache model cục bộ: {loi}")

    phat_sinh = sorted(set(ket_noi_ngoai_loopback()) - set(truoc))
    assert phat_sinh == [], (
        "Nạp embedder đã mở kết nối ra ngoài loopback, vi phạm ADR-001 "
        f"(\"Internet chỉ được dùng TRƯỚC runtime\"): {phat_sinh}. "
        "Đây là điểm mù của scripts/offline_drill.py: drill chặn DNS nên hub client không tạo nổi socket và ca RAG xanh đúng (run 20260815T103754.705204Z). Kết nối này chỉ xuất hiện khi máy CÓ mạng — trạng thái bình thường của máy demo."
    )

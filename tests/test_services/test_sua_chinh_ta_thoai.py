"""Đ5 — lớp sửa chính tả transcript theo cụm lệnh.

Hai nửa, và nửa thứ hai quan trọng hơn: sửa được ca báo cáo, **và** không đụng vào câu
hỏi sổ tay — nhánh mặc định của ADR-011, nơi nhận phần lớn lưu lượng.
"""

from pathlib import Path

import pytest

from src.config import get_settings
from src.services import voice
from src.services.sua_chinh_ta_thoai import CUM_LENH, _khoang_cach, sua_theo_cum


@pytest.fixture
def _bat_lop_sua(monkeypatch):
    """Bật `stt_correction_enabled` cho một test, và **dọn sau**.

    `get_settings` có `lru_cache`, nên đổi env mà không xoá cache thì không có tác dụng
    gì — và xoá lúc vào mà không xoá lúc ra thì test kế tiếp thừa hưởng cấu hình này.
    Cùng khuôn với `tests/test_agents/test_chon_cau_thac.py`.
    """

    def _bat() -> None:
        monkeypatch.setenv("STT_CORRECTION_ENABLED", "true")
        get_settings.cache_clear()

    yield _bat
    get_settings.cache_clear()

# ---- Ca báo cáo -----------------------------------------------------------


@pytest.mark.parametrize(
    ("tho", "mong_doi"),
    [
        ("Rừng nhạc", "Dừng nhạc"),
        ("Bậc nhạc", "Bật nhạc"),
        ("Tắc đèn", "Tắt đèn"),
        ("Mở cốc", "Mở cốp"),
        ("Vây ây rừng nhạc rút tôi", "Vây ây dừng nhạc rút tôi"),
    ],
)
def test_sua_duoc_khi_con_mot_tu_neo(tho, mong_doi):
    """@hason0510 24/08: nói *"Dừng nhạc"*, STT chép ra *"Rừng nhạc"*, lệnh rơi xuống
    tra sổ tay. Đo lại 26/08 bằng vòng Piper→Zipformer thì lỗi tái hiện được."""
    assert sua_theo_cum(tho) == mong_doi


# ---- Hàng rào: KHÔNG được đụng câu thường ---------------------------------


def test_cua_va_cua_cach_nhau_dung_mot_ky_tu_va_do_la_ly_do_luat_can_neo():
    """Luật hiển nhiên — "sửa từ nào lệch một ký tự so với tập lệnh" — hỏng ngay ở đây.

    Bật luật ấy lên là mọi câu hỏi sổ tay có chữ `của` biến thành câu nói về cửa xe.
    Đó là lý do luật thật đòi **thêm** một từ neo khớp chính xác.
    """
    assert _khoang_cach("của", "cửa") == 1
    assert sua_theo_cum("Áp suất lốp của xe là bao nhiêu") == "Áp suất lốp của xe là bao nhiêu"
    assert sua_theo_cum("Của tôi để đâu") == "Của tôi để đâu"


@pytest.mark.parametrize(
    "cau",
    [
        "Cửa sổ trời của xe mở thế nào",
        "Điều hòa hoạt động ra sao",
        "Đèn sương mù bật bằng cách nào",
        "Bao lâu thì thay dầu phanh",
        "Xe có mấy chế độ lái",
    ],
)
def test_cau_hoi_so_tay_khong_bi_dong(cau):
    assert sua_theo_cum(cau) == cau


def test_lech_hai_ky_tu_thi_khong_sua_du_co_neo():
    """`"tác nhạc"` (từ *"tắt nhạc"*) có neo `nhạc` khớp chính xác, nhưng `tác` lệch
    **hai** ký tự khỏi `tắt` (`á`→`ắ` và `c`→`t`).

    Luật dừng ở lệch-một. Nới lên hai là mở cửa cho đúng lớp nhầm mà `của`/`cửa` đại
    diện — chỉ chậm hơn một bước.
    """
    assert sua_theo_cum("Vây ơi tác nhạc giúp tôi") == "Vây ơi tác nhạc giúp tôi"


def test_khong_sua_khi_ca_hai_tu_deu_lech():
    """`"Các nhà"` (từ *"Tắt nhạc"*): `nhà` lệch 1 khỏi `nhạc`, `các` lệch 3 khỏi `tắt`.

    Không có neo khớp chính xác nên **không sửa** — bỏ lọt, và bỏ lọt là phía an toàn.
    Đoán ở đây là dựng lại đúng lớp lỗi mà cả đợt sửa này nhắm vào.
    """
    assert sua_theo_cum("Các nhà") == "Các nhà"
    assert sua_theo_cum("Thương hàng") == "Thương hàng"


def test_cau_da_dung_thi_khong_doi():
    for cau in ("Dừng nhạc", "Bật điều hòa", "Mở cốp"):
        assert sua_theo_cum(cau) == cau


def test_mot_tu_thi_khong_lam_gi():
    """Luật cần một cặp từ liền nhau; một từ trần không có neo nào."""
    assert sua_theo_cum("Rừng") == "Rừng"


def test_giu_chu_hoa_dau_cau():
    assert sua_theo_cum("Rừng nhạc") == "Dừng nhạc"
    assert sua_theo_cum("vivi ơi rừng nhạc") == "vivi ơi dừng nhạc"


def test_moi_cum_trong_bang_deu_la_lenh_router_nhan():
    """Thêm một cụm mà router không nhận thì lớp này sửa xong lệnh vẫn rơi xuống sổ
    tay — chỉ khác là giờ có thêm một chỗ để sai."""
    from src.agents.router import DeterministicControlRouter

    router = DeterministicControlRouter()
    duoi = {"điều": "hòa", "âm": "lượng", "cửa": "sổ bên lái 30 phần trăm", "kính": "bên lái 30 phần trăm"}
    for trai, phai in CUM_LENH:
        cau = f"{trai} {phai} {duoi.get(phai, '')}".strip()
        d = router.route(cau)
        assert d.disposition in {"control", "clarify"}, f"{cau!r} -> {d.disposition}/{d.reason}"


# ---- Nối vào đường thật ---------------------------------------------------


def test_transcribe_goi_lop_sua_con_transcribe_raw_thi_khong(monkeypatch, _bat_lop_sua):
    """`turns.py` phải gọi `transcribe`, không phải `transcribe_raw`.

    Tới 2026-08-26 hàm `transcribe` **không tồn tại**: docstring của `transcribe_raw`
    trỏ tới nó, `turns.py` gọi `transcribe_raw`, và "correction layer" trong CLAUDE.md
    chỉ là một lời hứa trong docstring.
    """
    monkeypatch.setattr(
        voice, "transcribe_raw", lambda audio: voice.Transcript(text="Rừng nhạc", latency_ms=1.0)
    )
    _bat_lop_sua()
    assert voice.transcribe(b"x").text == "Dừng nhạc"
    assert voice.transcribe_raw(b"x").text == "Rừng nhạc"


def test_transcribe_giu_nguyen_latency_va_confidence(monkeypatch, _bat_lop_sua):
    monkeypatch.setattr(
        voice,
        "transcribe_raw",
        lambda audio: voice.Transcript(text="Rừng nhạc", latency_ms=42.5, confidence=0.9),
    )
    _bat_lop_sua()
    ra = voice.transcribe(b"x")
    assert (ra.latency_ms, ra.confidence) == (42.5, 0.9)


# ---- Cờ phát hành ---------------------------------------------------------


def test_mac_dinh_cua_repo_la_tat(monkeypatch):
    """Điều kiện approve #3 của review #317, khoá bằng test chứ không bằng lời hứa.

    Bằng chứng hiện có là 16 audio Piper **tổng hợp**, và nó không nói được gì về WER
    người thật. Nên trên mọi checkout như-ship, `voice.transcribe` phải đúng bằng
    `transcribe_raw` — kể cả khi lớp sửa *có thể* sửa được câu ấy.

    Test này là thứ chặn việc lật cờ kèm theo một PR nói về chuyện khác. Lật nó phải
    đi cùng bằng chứng, và phải làm test này đỏ để có người đọc lại điều kiện.
    """
    get_settings.cache_clear()
    assert get_settings().stt_correction_enabled is False, "mặc định repo phải TẮT cho tới khi có WAV người thật"

    monkeypatch.setattr(voice, "transcribe_raw", lambda audio: voice.Transcript(text="Rừng nhạc", latency_ms=1.0))
    assert voice.transcribe(b"x").text == "Rừng nhạc", "cờ tắt thì không được động vào transcript"


def test_duong_thoai_that_di_qua_transcribe_chu_khong_phai_transcribe_raw():
    """Công tắc phải nằm trên đường thật, không thì nó là code chết.

    Đọc source thay vì chạy cả route: điều cần khoá ở đây là **chỗ gọi**, và dựng một
    lượt thoại thật chỉ để đọc một dòng là đổi một khẳng định rõ ràng lấy một test giòn.
    """
    nguon = Path("src/api/turns.py").read_text(encoding="utf-8")
    assert "voice.transcribe, audio_bytes" in nguon
    assert "voice.transcribe_raw, audio_bytes" not in nguon

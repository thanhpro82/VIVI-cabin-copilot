"""Thác chọn câu E5 → cross-encoder.

Phần lớn test ở đây **không nạp mô hình thật**: tầng 2 bị thay bằng bản giả để kiểm
hợp đồng (thu hẹp bao nhiêu, trả thứ tự nào, hỏng thì làm gì). Chỉ một test cuối
chạm trọng số thật, và nó mang marker `slow` vì CI không có `models/reranker/`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.agents.chon_cau_thac import ThacChonCau

CAU = [
    "Kích nâng xe và vá lốp nếu được trang bị.",
    "CẢNH BÁO Không sử dụng Bộ bơm hơi để sửa hư hại ở thành bên của lốp xe.",
    "Nên sửa chữa hoặc thay lốp bị thủng càng sớm càng tốt.",
    "Đầu tiên, tháo nắp van lốp.",
    "Vặn chặt van nối của chai keo vá lốp vào van lốp.",
    "Áp suất lốp tiêu chuẩn ghi trên nhãn ở khung cửa bên lái.",
]


class EmbedderGia:
    """Trả vector đã chuẩn hoá, và **ghi lại** hàm nào được gọi với gì.

    Việc ghi lại là trọng tâm của một test bên dưới: dùng nhầm `embed_query` cho câu
    sổ tay từng kéo F1 từ 51% xuống 42%, mà không có triệu chứng nào ngoài điểm số.
    """

    def __init__(self, diem: dict[str, float] | None = None) -> None:
        self.diem = diem or {}
        self.goi: list[tuple[str, object]] = []

    def _vec(self, x: float) -> np.ndarray:
        v = np.array([x, 1.0 - abs(x)], dtype=np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    def embed_query(self, text: str) -> np.ndarray:
        self.goi.append(("query", text))
        return self._vec(1.0)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        self.goi.append(("passages", list(texts)))
        return np.stack([self._vec(self.diem.get(t, 0.0)) for t in texts])


def _thac(embedder: object, **kw: object) -> ThacChonCau:
    return ThacChonCau(Path("models/reranker/bge-reranker-v2-m3"), embedder, **kw)  # type: ignore[arg-type]


def test_doan_it_cau_hon_top_thi_tra_het_chu_khong_tra_rong():
    """`[]` nghĩa là "model không có ý kiến" và bị ghi thành `slm_output_rejected`.

    Đoạn hai câu mà nói hai câu thì model **có** ý kiến, chỉ là ý kiến tầm thường.
    Trả `[]` ở đây làm cột eval trông như tầng xếp hạng đang hỏng liên tục.
    """
    thac = _thac(EmbedderGia(), top=2)
    assert thac.select("hỏi gì đó", ["Câu một.", "Câu hai."]) == [0, 1]


def test_khong_co_cau_nao_thi_khong_co_y_kien():
    assert _thac(EmbedderGia()).select("hỏi gì đó", []) == []


def test_tang_hai_chi_nhin_dung_pool_cau_ma_tang_mot_giu_lai(monkeypatch):
    """Cả lợi ích chi phí của thác nằm ở con số này: đắt tiền chỉ chấm `pool` câu."""
    emb = EmbedderGia({c: i / 10 for i, c in enumerate(CAU)})
    thac = _thac(emb, pool=3, top=2)
    thay = {}

    def cham_gia(question, sentences, chi_so):
        thay["chi_so"] = list(chi_so)
        return chi_so[:2]

    monkeypatch.setattr(thac, "_cham", cham_gia)
    thac.select("bánh xe bị xịt", CAU)
    assert len(thay["chi_so"]) == 3


def test_tra_ve_theo_thu_tu_so_tay_khong_theo_thu_tu_diem(monkeypatch):
    """Sổ tay hay viết điều kiện trước, thao tác sau.

    Đảo lại thì thao tác nghe như vô điều kiện — cũng là một dạng diễn đạt lại, chỉ
    là bằng thứ tự thay vì bằng chữ. `speech_policy` cũng sắp lại, nhưng bất biến này
    phải đúng ngay ở đây để một call site khác không mất nó.
    """
    thac = _thac(EmbedderGia(), pool=4, top=2)
    monkeypatch.setattr(thac, "_cham", lambda q, s, i: [4, 1])
    assert thac.select("bánh xe bị xịt", CAU) == [1, 4]


def test_cau_hoi_di_duong_query_con_cau_so_tay_di_duong_passages(monkeypatch):
    """E5 gắn tiền tố `query:`/`passage:` khác nhau; dùng nhầm mất 9 điểm F1."""
    emb = EmbedderGia()
    thac = _thac(emb, pool=2, top=1)
    monkeypatch.setattr(thac, "_cham", lambda q, s, i: i[:1])
    thac.select("bánh xe bị xịt", CAU)

    assert ("query", "bánh xe bị xịt") in emb.goi
    duong_passages = [g for g in emb.goi if g[0] == "passages"]
    assert duong_passages and duong_passages[0][1] == CAU
    # Câu sổ tay không được lẻn qua đường query.
    assert [g for g in emb.goi if g[0] == "query"] == [("query", "bánh xe bị xịt")]


def test_tang_hai_hong_thi_roi_ve_luat_chu_khong_lam_chet_luot(monkeypatch):
    """Trọng số thiếu, RAM cạn, torch nổ — lượt tra sổ tay vẫn phải trả lời được."""
    thac = _thac(EmbedderGia(), pool=3, top=2)

    def no(*_a, **_k):
        raise RuntimeError("hết RAM")

    monkeypatch.setattr(thac, "_cham", no)
    assert thac.select("bánh xe bị xịt", CAU) == []


def test_khong_nap_torch_khi_chi_khoi_tao():
    """Nạp trễ là bắt buộc: `speech_policy` nằm trên mọi đường của composer.

    Kéo torch vào lúc import là bắt cả lượt "bật điều hòa" trả tiền cho tầng này.
    """
    thac = _thac(EmbedderGia())
    assert thac._nap is None


@pytest.mark.slow
def test_voi_trong_so_that_thi_xep_cau_huu_ich_len_truoc():
    """Chạm trọng số thật. CI không có `models/reranker/` nên marker `slow`."""
    from src.agents.nodes.rag_node import _default_embedder

    thu_muc = Path("models/reranker/bge-reranker-v2-m3")
    if not (thu_muc / "model.safetensors").exists():
        pytest.skip("chưa có trọng số reranker")

    thac = ThacChonCau(thu_muc, _default_embedder(), pool=4, top=2)
    chon = thac.select("Áp suất lốp tiêu chuẩn là bao nhiêu?", CAU)

    assert len(chon) == 2
    assert chon == sorted(chon)
    assert all(0 <= i < len(CAU) for i in chon)
    # Câu chỉ đúng chỗ tra áp suất phải được chọn; đây là ca người dùng báo 17/08.
    assert 5 in chon, [CAU[i] for i in chon]


# --- Nối vào composer -------------------------------------------------------
#
# Ba test dưới chấm cái cầu dao, không chấm chất lượng xếp hạng. Cầu dao mới là chỗ
# một tính năng có thể "bật" mà im lặng không chạy — đúng thứ không ai phát hiện ra.


def _lam_moi_cache():
    from src.agents.nodes.compose import _thac_chon_cau

    _thac_chon_cau.cache_clear()


def test_co_tat_thi_composer_khong_dung_thac(monkeypatch):
    from src.agents.nodes.compose import _thac_chon_cau

    monkeypatch.setenv("CHON_CAU_THAC_ENABLED", "false")
    from src.config import get_settings

    get_settings.cache_clear()
    _lam_moi_cache()
    assert _thac_chon_cau() is None
    _lam_moi_cache()
    get_settings.cache_clear()


def test_bat_co_nhung_thieu_trong_so_thi_roi_ve_luat_chu_khong_no(monkeypatch, tmp_path):
    """Trọng số nằm ngoài git (2,2 GB). Một checkout mới bật cờ phải chạy tiếp được."""
    from src.agents.nodes.compose import _thac_chon_cau
    from src.config import get_settings

    monkeypatch.setenv("CHON_CAU_THAC_ENABLED", "true")
    monkeypatch.setenv("CHON_CAU_THAC_MODEL_DIR", str(tmp_path / "khong-ton-tai"))
    get_settings.cache_clear()
    _lam_moi_cache()
    assert _thac_chon_cau() is None
    _lam_moi_cache()
    get_settings.cache_clear()


def test_mac_dinh_la_tat():
    """Trọng số ngoài git và CI không có — mặc định bật là mặc định hỏng im lặng.

    Chấm vào **mặc định của trường**, không dựng `Settings()`: `Settings()` nạp `.env`
    của người chạy, nên trên máy đã bật cờ thì test này sẽ đỏ dù mã hoàn toàn đúng.
    Đó đúng là cái bẫy `CLAUDE.md` ghi lại ("suite không được đọc cấu hình của máy"),
    và tôi đã sập vào nó khi viết bản đầu.
    """
    from src.config import Settings

    assert Settings.model_fields["chon_cau_thac_enabled"].default is False


# --- Thác chạy ở đâu: issue #356 --------------------------------------------------


class _EvidenceGia:
    """Đủ field cho `_quote_top_evidence` và `_fields` — không cần Evidence thật."""

    section = "Vành và bánh xe"
    page = 87
    chunk_id = "c1"
    score = 0.9
    text = "Áp suất lốp tiêu chuẩn ghi trên nhãn ở khung cửa bên lái. Kiểm tra khi lốp nguội."
    has_variant_condition = False
    has_table = False


async def _chay_compose_ghi_thread(monkeypatch, thac):
    """Chạy `compose_node` qua nhánh trích dẫn, trả về thread id mà việc chọn câu chạy."""
    import threading

    from src.agents.nodes import compose as compose_mod

    thay = {}
    that = compose_mod.chon_cau_de_noi

    def ghi_lai(*args, **kwargs):
        thay["thread"] = threading.get_ident()
        return that(*args, **kwargs)

    monkeypatch.setattr(compose_mod, "chon_cau_de_noi", ghi_lai)
    monkeypatch.setattr(compose_mod, "_thac_chon_cau", lambda: thac)

    await compose_mod.compose_node(
        {
            "outcome": "grounded_answer",
            "evidence": [_EvidenceGia()],
            "query": "áp suất lốp bao nhiêu",
            "grounded_lead_in": "Theo sổ tay,",
            "turn_id": "t1",
            "session_id": "s1",
        }
    )
    return thay["thread"]


async def test_co_thac_thi_chon_cau_chay_ngoai_event_loop(monkeypatch):
    """Bật thác là mỗi câu sổ tay tốn p50 523 ms / p95 983 ms cross-encoder (đo 18/08,
    `src/config.py:118-122`). Chạy thẳng trên event loop nghĩa là trong ngần ấy thời gian
    **không phiên nào** được đẩy sự kiện WS — kể cả phiên không hỏi gì.

    So thread id chứ không so thời gian: thời gian lung lay theo tải máy CI, thread id thì
    không. Gỡ `asyncio.to_thread` ở `compose.py` là test này đỏ ngay.
    """
    import threading

    class _ThacGia:
        def select(self, question, cau_list, top):  # pragma: no cover - không được gọi ở đây
            return list(range(min(top, len(cau_list))))

    thread_cua_loop = threading.get_ident()

    thread_chon_cau = await _chay_compose_ghi_thread(monkeypatch, _ThacGia())

    assert thread_chon_cau != thread_cua_loop


async def test_khong_co_thac_thi_khong_nhay_thread(monkeypatch):
    """Đường mặc định phải y nguyên — và đây là nửa dễ bị bỏ quên của issue #356.

    `chon_cau_thac_enabled` mặc định False và trọng số 2,2 GB nằm ngoài git, nên đường
    `selector=None` là đường **duy nhất** đang chạy trên mọi checkout lẫn trên VPS. Nó chỉ
    tốn vài phép regex của luật S1. Bọc `to_thread` vô điều kiện là bắt nó trả một lần
    nhảy thread cho một việc không tốn gì — không đổi gì thì không thể làm hỏng gì.
    """
    import threading

    thread_cua_loop = threading.get_ident()

    thread_chon_cau = await _chay_compose_ghi_thread(monkeypatch, None)

    assert thread_chon_cau == thread_cua_loop

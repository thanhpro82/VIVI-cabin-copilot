"""Payload `assistant.speech` đi **hết đường thật**: đoạn sổ tay dài → composer → Piper.

## Vì sao cần một file riêng

`test_ivi_events.py` có fixture `autouse` bắt TTS **luôn thất bại**, để suite không phụ
thuộc việc máy có model Piper hay không (issue #66). Đó là quyết định đúng cho file ấy,
và nó cũng làm file ấy thành chỗ sai để đặt ca này: một test cần audio thật nằm cạnh một
fixture cấm audio thật thì chỉ chứng minh được rằng fixture đang chạy.

## Vì sao cần ca này khi đã có hai test kia

Hai test trong `test_ivi_events.py` đo bằng `b"x" * N`. Chúng khoá **cái van** —
`audio_qua_lon` đúng ngưỡng, `MAX_SPEECH_BYTES` dưới khung. Nhưng van đúng mà nước vẫn
tràn nếu composer đưa xuống một câu dài hơn thứ trần byte chịu nổi, và chuyện đó **đã
xảy ra**: `MAX_SPEECH_CHARS = 400` từng cho ra audio 107,6% khung, tức chính lưới an
toàn không giữ nổi bất biến của nó.

Nên phải có một ca đi hết đường: đoạn dài hơn mọi chunk thật (p50 950 ký tự) →
`compose_node` → Piper thật → đếm byte.

## Quan hệ với run đo trên socket

`eval/results/voice-payload/20260817T043442.858549Z` đo **trên dây** với client giữ
nguyên `max_size` mặc định: 237 ký tự → 650,4 KiB = 63,5% khung, client không rớt.

Test này **không** lặp lại phép đo ấy — nó không dựng server, nên nó không chứng minh
được gì về socket. Nó khoá vế còn lại, vế duy nhất có thể hồi quy trong một PR bình
thường: audio do đường thật sinh ra không vượt trần. Hai thứ bổ sung nhau, và nói rõ ở
đây để không ai đọc test này rồi tưởng đã đo cả khung WebSocket.
"""

from pathlib import Path

import pytest

from src.agents.nodes.compose import compose_node
from src.config import get_settings
from src.rag.models import Evidence
from src.services.ivi_events import MAX_SPEECH_BYTES, audio_qua_lon, synthesize_speech

#: Dài hơn mọi chunk thật, để nếu composer có rò thì nó rò ở đây trước.
DOAN_DAI = (
    "Để sạc xe, hãy làm theo quy trình bên dưới và hướng dẫn của thiết bị sạc. "
    "Quan sát tất cả các Cảnh báo và Thận trọng trước khi bắt đầu. "
    "Chuyển hộp số về chế độ Đỗ xe P và kích hoạt phanh đỗ xe điện tử. "
    "Tắt nguồn xe và chờ đèn báo trên cổng sạc chuyển sang màu trắng. "
) * 8


def _co_model_piper() -> bool:
    return Path(get_settings().tts_model_path).is_file()


pytestmark = pytest.mark.skipif(not _co_model_piper(), reason="cần model Piper thật")


@pytest.mark.slow
@pytest.mark.integration
async def test_cau_tra_loi_so_tay_dai_nhat_van_duoi_tran_byte():
    out = await compose_node(
        {
            "outcome": "grounded_answer",
            "query": "hướng dẫn sạc pin xe thế nào",
            "evidence": [Evidence(section="Sạc pin", page=120, text=DOAN_DAI, chunk_id="c-dai", score=0.9)],
        }
    )

    wav = await synthesize_speech("turn-dai", "trace-dai", out["speak_text"])

    assert wav is not None, "duong that phai tong hop duoc, khong duoc fail-open o day"
    assert not audio_qua_lon(wav), f"{len(wav)} byte vuot tran {MAX_SPEECH_BYTES}"
    # Trần byte tính trên audio; thứ đi trên dây còn cộng base64 4/3 và envelope JSON.
    assert len(wav) * 4 // 3 < (1 << 20), "khung 1 MiB phai con cho ca envelope"


@pytest.mark.slow
@pytest.mark.integration
async def test_doan_qua_dai_thi_bo_audio_chu_khong_bo_luot():
    """Vế fail-open, đo bằng đường thật thay vì bằng `b"x" * N`.

    Ép TTS nhận thẳng một chuỗi vượt xa trần — bỏ qua composer — để dựng đúng tình huống
    mà lưới cuối sinh ra để đỡ. `synthesize_speech` phải trả `None` (bỏ audio) chứ không
    ném: `assistant.response` vẫn mang `display_text`, và mất tiếng còn hơn mất câu trả
    lời.
    """
    wav = await synthesize_speech("turn-qua-dai", "trace-qua-dai", DOAN_DAI * 4)

    # Trần ký tự cắt câu trước khi tổng hợp, nên kết quả hoặc là None (vượt trần byte)
    # hoặc là một audio đã bị cắt về dưới trần. Cả hai đều hợp lệ; cái không hợp lệ là
    # một audio vượt trần lọt ra ngoài.
    assert wav is None or not audio_qua_lon(wav)

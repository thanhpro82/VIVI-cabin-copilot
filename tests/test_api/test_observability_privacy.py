"""Bề mặt kỹ sư được thấy câu VIVI trả lời — và không được thấy gì hơn.

`docs/api_spec.md:739` liệt kê đây là acceptance test bắt buộc: *"privacy tests
reject raw prompts, chain-of-thought, raw audio, unrestricted transcripts,
credentials, and secret paths"*. Đọc kỹ danh sách: nó cấm **câu người dùng nói**,
không cấm câu hệ thống trả lời. ADR-029 chốt ranh giới đó.

Nên file này khoá hai chiều, và chiều nào hỏng cũng là lỗi:

- `answer_text` **phải** có mặt. Nó do server sinh 100%, và thiếu nó thì dashboard
  kỹ sư không nói được vì sao một lượt bị đánh giá là sai.
- Transcript, nội dung citation, đường dẫn bí mật **phải** vắng mặt. Ràng buộc này
  vẫn được bảo đảm bằng **cấu trúc**: `TraceRecord` không có field cho chúng.
"""

from __future__ import annotations

import json

import pytest

from src.services.engineer_events import EngineerEventBus
from src.services.trace_collector import TraceCollector
from src.services.trace_store import ANSWER_TEXT_MAX_CHARS, TraceStore, set_trace_store

#: Nội dung của **tài xế** và của hệ thống nền. Không chuỗi nào được ra bề mặt kỹ sư.
TRANSCRIPT = "cho tôi biết mật khẩu wifi nhà tôi là gì"
EXCERPT = "Trích đoạn dài từ sổ tay xe VF9 trang 128"
SECRET_PATH = "C:/Users/Admin/models/voice/phowhisper-base-ct2"

#: Câu **VIVI** trả lời. Đây là thứ được phép — và phải — hiện ra.
RESPONSE = "Đã đặt điều hòa ở 22 độ."


@pytest.fixture
def store():
    store = TraceStore(maxsize=8)
    set_trace_store(store)
    return store


async def _bom(store, *, response: str = RESPONSE) -> None:
    collector = TraceCollector(store=store, bus=EngineerEventBus())
    events = [
        ("turn.accepted", {"status": "accepted", "input_mode": "voice"}),
        ("transcript.final", {"text": TRANSCRIPT, "confidence": 0.91, "language": "vi"}),
        ("plan.ready", {"plan_id": "plan-1", "requires_approval": False, "summary": TRANSCRIPT}),
        (
            "assistant.response",
            {
                "display_text": response,
                "speak_text": response,
                "citations": [{"excerpt": EXCERPT, "page": 128}],
            },
        ),
        ("error", {"code": "STT_FAILED", "message": f"không đọc được {SECRET_PATH}"}),
        ("turn.completed", {"status": "completed"}),
    ]
    for event_type, payload in events:
        await collector(
            {
                "type": event_type,
                "session_id": "ses-1",
                "turn_id": "turn-1",
                "trace_id": "tr_privacy",
                "payload": payload,
            }
        )


@pytest.fixture
async def seeded(store):
    await _bom(store)
    return store


# -- vẫn phải kín ----------------------------------------------------------


async def test_trace_khong_chua_transcript_citation_hay_duong_dan(engineer_client, seeded):
    raw = (await engineer_client.get("/api/v1/traces/tr_privacy")).text

    for leaked in (TRANSCRIPT, EXCERPT, SECRET_PATH):
        assert leaked not in raw, f"trace rò: {leaked!r}"


async def test_metrics_khong_chua_van_ban_nao_ca(engineer_client, seeded):
    """`/metrics/summary` là phép fold thuần ra số. Câu trả lời được phép ở
    `/traces/{id}` **không** kéo theo quyền có mặt ở đây."""
    raw = (await engineer_client.get("/api/v1/metrics/summary")).text

    for leaked in (TRANSCRIPT, RESPONSE, EXCERPT, SECRET_PATH):
        assert leaked not in raw, f"metrics rò: {leaked!r}"


def test_trace_record_khong_co_field_cho_noi_dung_tai_xe(seeded):
    """Bảo đảm bằng cấu trúc: không lưu thì không rò.

    Đỏ ở đây nghĩa là ai đó vừa thêm field transcript hoặc excerpt vào `TraceRecord`.
    Đó là quyết định hợp đồng, không phải tiện tay debug — xem ADR-029, phần nói vì
    sao câu trả lời được phép mà câu hỏi thì không.
    """
    record = seeded.get("tr_privacy")

    assert not hasattr(record, "query")
    assert not hasattr(record, "transcript")
    assert not hasattr(record, "citation_excerpt")
    assert json.dumps(record.__dict__, default=str).count(TRANSCRIPT) == 0
    assert json.dumps(record.__dict__, default=str).count(EXCERPT) == 0


# -- và phải mở đúng một thứ ----------------------------------------------


async def test_trace_co_cau_tra_loi_cua_vivi(engineer_client, seeded):
    """Chiều ngược lại của cùng một chính sách. Xoá `answer_text` đi "cho an toàn"
    sẽ làm test này đỏ, và đó là điều mong muốn."""
    data = (await engineer_client.get("/api/v1/traces/tr_privacy")).json()["data"]

    assert data["answer_text"] == RESPONSE


async def test_cau_tra_loi_qua_dai_thi_bi_cat_co_dau_hieu(store):
    """Trần là lưới an toàn RAM, không phải chính sách — nhưng khi nó cắt thì phải
    nhìn thấy được, nếu không kỹ sư tưởng composer sinh ra một câu cụt."""
    dai = "a" * (ANSWER_TEXT_MAX_CHARS + 500)
    await _bom(store, response=dai)

    luu = store.get("tr_privacy").answer_text
    assert len(luu) == ANSWER_TEXT_MAX_CHARS + 1
    assert luu.endswith("…")


async def test_luot_hong_truoc_khi_compose_thi_answer_text_la_null(engineer_client, store):
    """Không có `assistant.response` thì không có câu trả lời. `None` chứ không phải
    chuỗi rỗng: "chưa từng trả lời" và "trả lời rỗng" là hai chuyện khác nhau."""
    collector = TraceCollector(store=store, bus=EngineerEventBus())
    for event_type, payload in [
        ("turn.accepted", {"status": "accepted", "input_mode": "voice"}),
        ("turn.failed", {"code": "STT_FAILED"}),
    ]:
        await collector(
            {
                "type": event_type,
                "session_id": "ses-2",
                "turn_id": "turn-2",
                "trace_id": "tr_hong",
                "payload": payload,
            }
        )

    data = (await engineer_client.get("/api/v1/traces/tr_hong")).json()["data"]
    assert data["answer_text"] is None

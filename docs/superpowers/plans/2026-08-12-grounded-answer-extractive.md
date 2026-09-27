# Grounded answer trích nguyên văn — kế hoạch triển khai

> **Cho người thực thi:** đây là phần **không phụ thuộc SLM** của phương án A chốt ở
> issue #62. Phần câu dẫn do SLM viết là ticket riêng, làm sau khi PR #71 merge.

**Mục tiêu:** câu trả lời tra sổ tay chứa **nội dung nguyên văn** từ đoạn sổ tay khớp
nhất, thay vì chỉ một câu cố định trỏ sang citation.

**Kiến trúc:** đổi đúng một node — `compose_node` đọc `state["evidence"][0]` (đã có sẵn
trong state từ `rag_stage`) và ghép vào `response_text`. Không đụng retriever, không
đụng citation contract, không thêm phụ thuộc.

## Bối cảnh quyết định (số, không phải ý kiến)

Đo tại `eval/results/spike-003/20260811T200114.021276Z` (chấm tay 40/40 ở
`graded.jsonl`), tóm tắt trong `docs/reports/SPIKE-003-notes.md`:

- Để SLM **viết lại** đoạn sổ tay: p50 2.080 ms, và 4/40 câu gây hiểu lầm. Lớp lỗi
  chính là **bỏ điều kiện theo phiên bản** — RAG-130 bốc một cột của bảng áp suất lốp
  (ECO + pin SDI) ra trình bày như giá trị chung; xe pin CATL bơm theo là thiếu hơi.
- Trích nguyên văn thì bảng và chữ "nếu được trang bị" đi kèm theo, nên lớp lỗi đó
  **không tồn tại về mặt cấu trúc**.

## Ràng buộc toàn cục

- **Nguồn trích phải là `evidence[0].text`, KHÔNG phải `citation.excerpt`.**
  `EXCERPT_CHARS = 300` (`src/rag/retrieve.py:21`) trong khi **39/40 đoạn dài hơn 300
  ký tự** (min 199, p50 950, max 2.416). Trích từ excerpt là tái tạo đúng lỗi cắt cụt
  điều kiện mà cả ticket này sinh ra để tránh.
- **Cắt bớt phải nhìn thấy được.** Lỗi của phương án SLM là bỏ sót *âm thầm*. Nếu đoạn
  dài quá ngưỡng, cắt ở ranh giới câu **và** nói rõ là còn tiếp, kèm mục + trang.
- **Không được sập khi thiếu evidence.** Hết đường lùi thì về đúng câu cố định hôm nay.
- Không đổi hợp đồng `Citation`, không đổi `docs/api_spec.md`.

---

## Task 1: `compose_node` trích nguyên văn đoạn hạng 1

**Files:**
- Modify: `src/agents/nodes/compose.py`
- Test: `tests/test_agents/test_grounded_answer_quote.py` (tạo mới)

**Interfaces:**
- Consumes: `AgentState["evidence"]` — `list[src.rag.models.Evidence]` với
  `.text: str`, `.section: str`, `.page: int`. Do `rag_stage` (`src/agents/graph.py`)
  đặt vào state.
- Produces: `compose_node` vẫn trả `{"response_text": str, "response": str}` —
  không thêm key, không đổi kiểu.

- [ ] **Step 1: Viết test đỏ**

```python
def _state(text: str, *, section: str = "Cửa sổ điện", page: int = 3) -> dict:
    return {
        "outcome": "grounded_answer",
        "evidence": [Evidence(section=section, page=page, text=text, chunk_id="c1", score=0.9)],
    }


async def test_cau_tra_loi_chua_nguyen_van_doan_so_tay():
    text = "Để tự động mở toàn bộ cửa sổ điện, đẩy nút cửa sổ hoàn toàn xuống."
    out = await compose_node(_state(text))
    assert text in out["response_text"]
    assert out["response_text"].startswith(OUTCOME_MESSAGES["grounded_answer"])


async def test_trich_du_doan_dai_hon_gioi_han_excerpt_300():
    # 39/40 đoạn thật dài hơn EXCERPT_CHARS; trích từ excerpt là cắt mất điều kiện
    text = "A" * 400 + " Bản ECO có chỉnh điện 8 hướng."
    out = await compose_node(_state(text))
    assert "Bản ECO có chỉnh điện 8 hướng." in out["response_text"]


async def test_doan_qua_dai_bi_cat_o_ranh_gioi_cau_va_noi_ro_con_tiep():
    text = ("Câu một. " * 200) + "Câu cuối bị bỏ."
    out = await compose_node(_state(text, section="Vành và bánh xe", page=2))
    body = out["response_text"]
    assert "Câu cuối bị bỏ." not in body
    assert body.rstrip().endswith(".)")          # kết bằng dấu ngoặc của phần ghi chú
    assert "Vành và bánh xe" in body and "tr.2" in body


async def test_khong_co_evidence_thi_giu_nguyen_cau_co_dinh():
    out = await compose_node({"outcome": "grounded_answer", "evidence": []})
    assert out["response_text"] == OUTCOME_MESSAGES["grounded_answer"]


async def test_cac_outcome_khac_khong_doi():
    out = await compose_node({"outcome": "grounded_refusal", "evidence": []})
    assert out["response_text"] == OUTCOME_MESSAGES["grounded_refusal"]
```

- [ ] **Step 2: Chạy để thấy đỏ**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_grounded_answer_quote.py -q
```
Kỳ vọng: FAIL — `response_text` mới chỉ là câu cố định.

- [ ] **Step 3: Cài đặt tối thiểu**

Thêm vào `src/agents/nodes/compose.py`: hằng `QUOTE_MAX_CHARS = 1200` (bao trọn 34/40
đoạn; 6 đoạn còn lại bị cắt **có báo**), hàm `_quote_top_evidence(state) -> str | None`,
và nhánh `grounded_answer` trong `compose_node`.

- [ ] **Step 4: Chạy để thấy xanh**, rồi chạy cả bộ:

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
```
Kỳ vọng: 790 passed, 15 skipped + 5 test mới.

- [ ] **Step 5: Commit**

---

## Task 2: cập nhật ADR-015 theo bốn điểm đã chốt ở #62

**Files:** Modify `docs/adr/ADR-015-slm-required-for-grounded-rag.md`

- [ ] Bỏ "phụ thuộc bắt buộc"; nhánh sổ tay chạy đủ với `slm_enabled=False`.
- [ ] Viết lại điều kiện Accept #2: `rag_grounding_min_support` **hết việc** vì trích
      nguyên văn có grounding bằng 1 theo cấu trúc — không để lại nút vặn chết.
- [ ] Ghi phương án "SLM viết lại đoạn" là **đã đo, chưa nhận**, kèm run-id và điều
      kiện mở lại; nói rõ nó **không** bị loại vì độ trễ.
- [ ] Ghi reranker là ticket riêng, mặc định tắt.
- [ ] Commit.

---

## Task 3: câu dẫn do SLM viết (gộp vào cùng nhánh sau khi PR #71 merge)

**Files:** `src/agents/slm.py` (thêm `QwenLeadIn`, `LeadInWriter`, `chatml`,
`LEAD_IN_SYSTEM`, `LEAD_IN_MAX_CHARS`), `src/agents/graph.py` (`lead_in=` +
`_write_lead_in`), `src/agents/state.py`, `src/agents/nodes/normalize.py`,
`src/agents/nodes/compose.py`, `src/api/session_state.py`.
**Test:** `tests/test_agents/test_grounded_lead_in.py`, thêm một test vào
`tests/test_api/test_session_state.py`.

- [x] Client tách khỏi `QwenPlanner`: hai đường khác bản chất — planner ràng buộc bằng
      grammar JSON và sai thì cổng an toàn chặn; câu dẫn là văn xuôi tự do và an toàn
      **nhờ không mang dữ kiện**, không nhờ cổng nào.
- [x] Prompt bê nguyên cấu hình đã đo ở biến thể A (`…200114`), gồm cả hai ví dụ
      few-shot — thiếu chúng thì model trả về số mục/số trang bịa thay vì câu dẫn.
- [x] ChatML, không gọi `/completion` thô (xem `chatml()` docstring).
- [x] **Fail-open**: mọi kiểu hỏng → chuỗi cố định, nội dung không đổi.
- [x] Trần `LEAD_IN_MAX_CHARS = 120` chống thoái hoá đã quan sát ở SPIKE-003.
- [x] Bật `slm_enabled` phải nối **cả hai** vai; có test khoá lại, vì sót `lead_in` thì
      tính năng im lặng không tồn tại mà không test nào đỏ.

## Ngoài phạm vi (ticket sau)

- Reranker vào đường chạy thật (đo tại `…185854`; mặc định tắt vì CPU tốn 2,8 s/1,3 GB).
- Rút gọn cho TTS: `speak_text` hiện là bản sao `display_text` và Piper chưa nối, nên
  độ dài trích chưa phải vấn đề nghe được. Khi nối TTS thì phải xét lại.

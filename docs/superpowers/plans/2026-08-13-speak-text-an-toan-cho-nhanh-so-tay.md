# `speak_text` an toàn cho nhánh sổ tay (S1 + S3, rồi S2) — kế hoạch

> **Cho người thực thi:** dùng `superpowers:executing-plans` hoặc
> `superpowers:subagent-driven-development`, làm từng task một. Bước dùng checkbox.

**Mục tiêu:** tài xế nghe được câu trả lời sổ tay trong ~5–7 giây thay vì 65 giây, mà
không đánh đổi lớp an toàn mà ADR-015 đã mua bằng số đo.

**Kiến trúc:** tách hẳn hai kênh. `display_text` giữ **nguyên văn** như ADR-015 chốt.
`speak_text` là một chuỗi **ngắn, luôn là tập con nguyên văn của đoạn nguồn**, do một
bộ phân loại tất định (S1) quyết định nói gì; phần dư được mời nghe tiếp (S3). SLM
(S2) chỉ được thêm vào **sau khi** có số đo, và chỉ để *chọn câu*, không để viết câu.

**Tech stack:** Python 3.11, sqlite3 stdlib, FAISS + `intfloat/multilingual-e5-small`,
Piper TTS, LangGraph. Không thêm phụ thuộc mới.

## Ràng buộc toàn cục

- **`display_text` không đổi một chữ.** ADR-015 phương án A giữ nguyên. Mọi thay đổi
  chỉ chạm `speak_text`.
- **`slm_enabled=False` (mặc định mọi máy) phải chạy đầy đủ.** Task 1–5 không được
  phụ thuộc SLM. Chỉ Task 6 dùng, và nó phải fail về Task 3 khi SLM tắt hoặc hỏng.
- **Mọi câu trong `speak_text` phải xuất hiện y nguyên trong đoạn nguồn**, trừ đúng
  hai chuỗi khung được phép: câu dẫn và câu mời nghe tiếp. Đây là bất biến kiểm được
  bằng máy, và là thứ ngăn lớp lỗi 4/40 của ADR-015 quay lại.
- **Fail-closed:** không phân loại được → coi như *có điều kiện* → không đọc số.
- Hợp đồng đã có sẵn: `api_spec.md:571` khai `assistant.response` gồm **cả**
  `display_text` lẫn `speak_text`. Không cần sửa spec cho Task 1–5.
- Không thêm phụ thuộc; `pyproject.toml` không đổi.

## Bối cảnh đo được (2026-08-13, máy Nhân)

| Chỉ số | Hôm nay |
|---|---|
| `assistant.speech` một lượt sổ tay | **4,60 MB** một khung WS |
| Audio tài xế phải nghe | **65,6 s** |
| Đoạn hạng 1 điển hình | 1.671–1.926 ký tự |
| Chunk có điều kiện *và* số (lớp RAG-130) | **34/482 = 7,1%** |
| `stage_latencies_ms.tts` | 6.056 ms, **không** nằm trong `end_to_end` |

---

## Task 1 — Tách `speak_text` khỏi `display_text`, và chặn payload quá khổ ✅

Không có task này thì mọi task sau không có chỗ ghép.

**Files:**
- Modify: `src/agents/nodes/compose.py` (hàm `compose_node`)
- Modify: `src/services/ivi_events.py` (`emit_turn_lifecycle` ~dòng 405, `_publish_assistant_response`)
- Test: `tests/test_agents/test_compose.py`, `tests/test_api/test_ws_ivi.py`

**Interfaces:**
- Produces: `compose_node` trả thêm khoá `speak_text: str`. Mọi task sau ghi vào đúng khoá này.
- Produces: `MAX_SPEECH_CHARS = 400` trong `src/services/ivi_events.py`.

- [x] **Bước 1: test đỏ — compose trả `speak_text` riêng**

```python
async def test_nhanh_so_tay_tra_speak_text_ngan_hon_display_text():
    """Hai kênh, hai nội dung. `api_spec.md:571` khai cả hai trường từ đầu;
    `ivi_events.py` gộp chúng làm một là lệch hợp đồng, không phải rút gọn."""
    state = _state_grounded(quote="A" * 1500)
    ket_qua = await compose_node(state)
    assert ket_qua["display_text"] == ket_qua["response_text"]
    assert len(ket_qua["speak_text"]) < len(ket_qua["display_text"])
```

- [x] **Bước 2: chạy để chắc nó đỏ**

`MQTT_ENABLED=false .venv/Scripts/python.exe -m pytest tests/test_agents/test_compose.py -q`
Kỳ vọng: `KeyError: 'speak_text'`.

- [x] **Bước 3: cài đặt tối thiểu** — `compose_node` trả thêm `speak_text`, tạm thời
      bằng câu dẫn nếu là nhánh sổ tay, bằng `message` cho mọi nhánh khác:

```python
    speak_text = message
    if outcome == "grounded_answer" and quote:
        speak_text = (state.get("grounded_lead_in") or "").strip() or OUTCOME_MESSAGES["grounded_answer"]
    return {"response_text": message, "response": message, "speak_text": speak_text}
```

- [x] **Bước 4: TTS đọc `speak_text`, không đọc `response_text`**

`src/services/ivi_events.py`, chỗ gọi `synthesize_speech`:

```python
    wav_bytes = await synthesize_speech(turn_id, trace_id, result.get("speak_text") or result.get("response_text", ""))
```

- [x] **Bước 5: trần cứng ở tầng phát**

```python
#: Trần ký tự cho văn bản đưa vào TTS. Đây là lưới cuối, KHÔNG phải chỗ quyết định
#: nói gì — composer mới là chỗ đó. Có nó vì một `assistant.speech` 4,60 MB (đo
#: 2026-08-13) vượt trần khung 1 MiB mặc định của nhiều client và chiếm chỗ trong
#: ring buffer 200 event của ADR-014.
MAX_SPEECH_CHARS = 400
```

Cắt tại biên câu gần nhất trước trần, và **log cảnh báo** khi phải cắt — phải cắt ở
đây nghĩa là composer đã sai, không phải chuyện bình thường.

- [x] **Bước 6: test WS — `assistant.speech` dưới 500 KB**

```python
def test_assistant_speech_khong_vuot_tran_khung_websocket():
    """4,60 MB một khung làm rớt client có trần 1 MiB — đo thật 2026-08-13."""
    ...
    speech = [e for e in events if e["type"] == "assistant.speech"]
    assert speech, "phải có audio"
    assert len(json.dumps(speech[0])) < 500_000
```

- [x] **Bước 7: chạy full suite + ruff, commit**

```bash
git add -A && git commit -m "feat(compose): tach speak_text khoi display_text + tran payload assistant.speech"
```

---

## Task 2 — Nhãn cấu trúc ở ingest: `is_table`, `has_variant_condition` ✅

**Files:**
- Modify: `src/rag/models.py:98-100` (thêm hai trường cạnh `has_warning`)
- Modify: `src/rag/ingest/chunker.py:134-136`
- Modify: `src/rag/store.py:41-43, 96, 109-110` (cột + INSERT)
- Test: `tests/test_rag/test_chunker.py`

**Interfaces:**
- Produces: `Chunk.is_table: bool`, `Chunk.has_variant_condition: bool`; hai cột cùng tên trong `document_chunks`.

- [x] **Bước 1: test đỏ cho `is_table`** — đi theo đúng khuôn `has_warning`:

```python
def test_chunk_chua_khoi_bang_duoc_danh_dau_is_table():
    """`BlockKind.TABLE` đã có sẵn từ ingest HTML — chỉ chưa ai mang xuống chunk."""
    chunk = _chunk_tu_blocks([_block(BlockKind.TEXT, "Áp suất lốp"), _block(BlockKind.TABLE, "Mô tả | Chi tiết")])
    assert chunk.is_table is True
```

- [x] **Bước 2: test đỏ cho `has_variant_condition`**

```python
VARIANT_CASES = [
    ("Thông số lốp dự phòng (nếu được trang bị)", True),
    ("Bản ECO dùng pin SDI, bản PLUS dùng pin CATL", True),
    ("Gạt nước sẽ chỉ kích hoạt khi xe đang BẬT", False),   # điều kiện vận hành, KHÔNG phải biến thể
    ("Nhấn nút để mở nắp ca-pô", False),
]

@pytest.mark.parametrize("text,mong_doi", VARIANT_CASES)
def test_nhan_dieu_kien_bien_the(text, mong_doi):
    assert _chunk_tu_text(text).has_variant_condition is mong_doi
```

Case thứ ba là chốt chặn quan trọng nhất: regex thô của tôi hôm 13/08 bắt 39,6% chunk
vì nó coi mọi chữ "khi/nếu" là biến thể. Chỉ **biến thể sản phẩm** mới tính.

- [x] **Bước 3: chạy để chắc cả hai đỏ**

- [x] **Bước 4: cài đặt**

```python
_VARIANT_MARKERS = ("nếu được trang bị", "tuỳ chọn", "tùy chọn", "ECO", "PLUS", "SDI", "CATL")

def _has_variant_condition(blocks) -> bool:
    text = " ".join(b.text for b in blocks)
    return any(m.lower() in text.lower() for m in _VARIANT_MARKERS)
```

```python
        is_table=BlockKind.TABLE in kinds,
        has_variant_condition=_has_variant_condition(blocks),
```

- [x] **Bước 5: cột mới trong `store.py`** (`INTEGER NOT NULL DEFAULT 0`), thêm vào
      INSERT và vào hàm đọc.

- [x] **Bước 6: ingest lại + kiểm tỷ lệ**

```bash
.venv/Scripts/python.exe -m src.rag.cli ingest
.venv/Scripts/python.exe -m src.rag.cli verify
```

Kỳ vọng: `has_variant_condition` rơi vào khoảng **5–12%** của 482 chunk. Trên 20% là
bộ dò quá rộng — quay lại bước 4, đừng đi tiếp.

- [x] **Bước 7: commit** (kèm `manifest.json` mới do `chunker_version` đổi)

---

## Task 3 — S1: chọn nội dung nói theo luật ✅

**Files:**
- Create: `src/agents/nodes/speech_policy.py`
- Modify: `src/agents/nodes/compose.py`
- Test: `tests/test_agents/test_speech_policy.py`

**Interfaces:**
- Consumes: `Chunk.is_table`, `Chunk.has_variant_condition` (Task 2); khoá `speak_text` (Task 1).
- Produces: `chon_cau_de_noi(evidence: Evidence, question: str) -> SpeechPlan`
  với `SpeechPlan(spoken: str, remainder_chars: int, reason: str)`.

- [x] **Bước 1: test đỏ — đoạn có điều kiện thì không đọc số**

```python
def test_doan_co_bien_the_khong_bao_gio_doc_so():
    """Ca RAG-130 của ADR-015: SLM bốc một cột của bảng áp suất (ECO+SDI) trình bày
    như giá trị chung; xe pin CATL bơm theo đó là thiếu hơi. Luật này khiến lớp lỗi
    đó không dựng lên được, chứ không phải giảm thiểu."""
    ev = _evidence(text="... Áp suất khuyến nghị 250 kPa cho bản ECO ...",
                   has_variant_condition=True, is_table=True)
    ke_hoach = chon_cau_de_noi(ev, "áp suất lốp bao nhiêu")
    assert not re.search(r"\d+\s*(kPa|psi|bar)", ke_hoach.spoken)
    assert ke_hoach.reason == "variant_condition"
```

- [x] **Bước 2: test đỏ — ưu tiên câu chỉ nguồn có sẵn trong đoạn**

```python
def test_uu_tien_cau_chi_nguon_nam_san_trong_doan():
    """Đoạn "Vành và bánh xe" tự nó chứa câu an toàn: "Áp suất lốp khuyến nghị được
    liệt kê trên nhãn gắn trên khung cửa của người lái". Nói câu đó là TRÍCH, không
    phải tóm tắt — không có gì để bịa."""
    ev = _evidence(text=DOAN_VANH_VA_BANH_XE, has_variant_condition=True, is_table=True)
    assert "nhãn gắn trên khung cửa" in chon_cau_de_noi(ev, "áp suất lốp").spoken
```

- [x] **Bước 3: test đỏ — không có câu chỉ nguồn thì fail-closed, không bịa**

```python
def test_khong_co_cau_chi_nguon_thi_moi_nghe_nguyen_van():
    ev = _evidence(text="Bản ECO 250 kPa. Bản PLUS 260 kPa.", has_variant_condition=True)
    ke_hoach = chon_cau_de_noi(ev, "áp suất lốp")
    assert "phiên bản" in ke_hoach.spoken
    assert not re.search(r"\d", ke_hoach.spoken)
    assert ke_hoach.remainder_chars > 0
```

- [x] **Bước 4: test đỏ — đoạn thường thì nói nội dung thật**

```python
def test_doan_khong_dieu_kien_thi_noi_noi_dung():
    ev = _evidence(text="Tính năng lau nhẹ nhàng sẽ loại bỏ lượng nước dư thừa khỏi kính chắn gió sau khi hoàn thành gạt rửa. Kiểm tra mức chất lỏng thường xuyên.", has_variant_condition=False)
    ke_hoach = chon_cau_de_noi(ev, "lau nhẹ nhàng là gì")
    assert ke_hoach.spoken.startswith("Tính năng lau nhẹ nhàng")
    assert len(ke_hoach.spoken) <= 400
```

- [x] **Bước 5: chạy cả bốn, chắc chắn đỏ**

- [x] **Bước 6: cài đặt** — thứ tự quyết định:
  1. `has_variant_condition or is_table` → tìm câu chứa dấu hiệu chỉ nguồn
     (`"nhãn"`, `"khung cửa"`, `"xem >"`, `"tham khảo"`) → nếu có, nói nguyên văn câu đó.
  2. Không có → chuỗi khung cố định `"Thông tin này thay đổi theo phiên bản xe. Bạn có muốn tôi đọc nguyên văn không?"`.
  3. Không điều kiện → hai câu đầu, cắt ở biên câu, ≤ `MAX_SPEECH_CHARS`.
  Mọi nhánh đều tính `remainder_chars`.

- [x] **Bước 7: nối vào `compose_node`**, thay chỗ tạm ở Task 1 bước 3.

- [x] **Bước 8: full suite + ruff, commit**

---

## Task 4 — S3: mời nghe tiếp ✅

**Files:**
- Modify: `src/agents/nodes/speech_policy.py`, `src/agents/nodes/compose.py`
- Test: `tests/test_agents/test_speech_policy.py`

**Interfaces:**
- Consumes: `SpeechPlan.remainder_chars` (Task 3).

- [x] **Bước 1: test đỏ — chỉ mời khi còn phần dư**

```python
def test_chi_moi_nghe_tiep_khi_con_phan_du():
    """Câu trả lời một dòng thì không có gì để tiếp. Mời vô điều kiện sẽ khiến mỗi
    lệnh bật điều hoà cũng bị hỏi "nghe tiếp không?"."""
    assert "nghe tiếp" not in cau_noi_hoan_chinh(_plan(spoken="Đã đặt 24 độ.", remainder_chars=0))
    assert "nghe tiếp" in cau_noi_hoan_chinh(_plan(spoken="Câu đầu.", remainder_chars=900))
```

- [x] **Bước 2: chạy, chắc đỏ**

- [x] **Bước 3: cài đặt** — nối chuỗi mời khi `remainder_chars > 0`.

- [x] **Bước 4: commit**

> **Chưa thuộc task này:** việc tài xế *trả lời* "có/không" là một voice intent, dùng
> chung hạ tầng với `approval.intent.detected` — theo dõi ở issue riêng. Và việc **ngắt
> lời** khi đang phát là phía FE, cũng có issue riêng. Task 4 chỉ làm ra *lời mời*.

---

## Task 5 — Đo: hai cột mới, và baseline của hôm nay ✅

**Không có task này thì Task 6 không được phép làm.** ADR-015 chốt bằng số; thay nó
bằng ý kiến là lùi một bước về kỷ luật.

**Files:**
- Modify: `src/rag/evaluate.py`
- Test: `tests/test_rag/test_evaluate.py`

- [x] **Bước 1: thêm hai cột vào `case_results.jsonl`**
  - `spoken_audio_seconds`: độ dài audio của `speak_text` (ước bằng số ký tự ÷ tốc độ
    đọc đo được **20,1 ký tự/giây** — từ 1.181 ký tự → 65,6 s ngày 13/08; không gọi
    Piper thật trong eval để khỏi phụ thuộc máy có model).
  - `spoken_has_number_without_condition`: `speak_text` chứa số kèm đơn vị mà đoạn
    nguồn có `has_variant_condition` → cờ đỏ tự động cho lớp RAG-130.

- [x] **Bước 2: chạy baseline trên 40 case `supported`**

```bash
.venv/Scripts/python.exe -m src.rag.cli eval
```

Ghi run id vào ADR-015 mục cập nhật.

- [x] **Bước 3: cổng nghiệm thu cho Task 1–4**
  - `spoken_audio_seconds` p95 **≤ 12 s** (hôm nay: 65,6 s)
  - `spoken_has_number_without_condition` = **0/40**
  - `display_text` **giống hệt** baseline ở cả 40 case — bằng chứng ADR-015 không bị đụng

- [x] **Bước 4: commit run directory + cập nhật ADR-015**

---


### Kết quả đo (2026-08-13)

| Run | `MAX_SPOKEN_CHARS` | nói p50 | nói p95 | đọc số ở đoạn biến thể |
|---|---:|---:|---:|---:|
| `20260813T105823Z` | 400 | 16,6 s | **19,2 s** ❌ | 0/41 ✅ |
| `20260813T110138Z` | **240** | 9,4 s | **11,9 s** ✅ | 0/41 ✅ |

Cổng `p95 ≤ 12 s` **trượt ở lần đo đầu**. 400 là con số tôi đoán trước khi có số; 240
là con số đo ra. `grounded_rate` giữ 100% ở cả hai, nên siết trần không làm mất câu
trả lời nào — chỉ đổi lượng nội dung mỗi lượt, và S3 mời nghe phần còn lại.

**Điều bộ đo này CHƯA đo:** câu được chọn có **trúng câu hỏi** không. Luật hiện chọn
theo vị trí và độ an toàn, không theo độ liên quan. Đó đúng là chỗ Task 6 phải chứng
minh mình có giá trị — và cần thêm một cột nữa trước khi bắt đầu.

**Một case trượt không liên quan:** `RAG-209` ("đáng lẽ phải từ chối") trượt từ run
`20260807T051513Z`, tức trước mọi thay đổi của kế hoạch này. Nợ truy hồi cũ, không
phải hồi quy.
## Task 6 — S2: SLM *chọn câu*, có cổng kiểm chứng

**Chỉ bắt đầu sau khi Task 5 có số.** Nếu Task 1–4 đã đạt cổng, S2 phải chứng minh nó
làm **tốt hơn** ở chỉ số "câu nói trả lời trúng câu hỏi", nếu không thì không đáng
đánh đổi một phụ thuộc SLM.

**Files:**
- Modify: `src/agents/slm.py` (thêm `QwenSentenceSelector` cạnh `QwenLeadIn`)
- Modify: `src/agents/nodes/speech_policy.py`
- Test: `tests/test_agents/test_speech_policy.py`

**Interfaces:**
- Consumes: `chon_cau_de_noi` (Task 3) làm đường lui.
- Produces: `SentenceSelector` protocol với `select(question: str, sentences: list[str]) -> list[int]`.

> **Task 6 đã chuyển sang `2026-08-13-s2-chon-cau-va-dinh-huong-npu.md` (Task 9) và
> hoàn thành ở đó 14/08.** Năm bước dưới đây giữ nguyên để đối chiếu ý định ban đầu;
> bản làm thật khác hai chỗ: cổng kiểm chứng khoá vào **khoảng chỉ số** (grammar ép
> được kiểu nhưng không ép được khoảng), và có thêm `slm_error` tách khỏi
> `slm_output_rejected` — *llama-server không có* và *llama-server nói sai* dẫn tới
> hai quyết định khác nhau của nhóm.
>
> **Kết quả: S2 không đạt** — 40,0% so với 37,5%, hơn 11 ca kém 10 ca. Xem ADR-015.

- [~] **Bước 1: test đỏ — cổng kiểm chứng vứt mọi câu không nguyên văn**

```python
def test_cau_khong_nguyen_van_bi_vut_va_roi_ve_luat():
    """Đây là thứ khiến S2 khác phương án B mà ADR-015 đã bác: đầu ra của SLM là
    CHỈ SỐ CÂU, và mỗi câu nói được so chuỗi với nguồn. Không có diễn đạt lại thì
    không có chỗ cho điều kiện rơi ra."""
    class SlmBia:
        def select(self, question, sentences): return [0]
    ev = _evidence(text="Câu một. Câu hai.")
    with patch_selector(SlmBia(), tra_ve_cau="Câu một đã bị viết lại."):
        ke_hoach = chon_cau_de_noi(ev, "hỏi gì đó")
    assert ke_hoach.reason == "slm_output_rejected"
```

- [~] **Bước 2: test đỏ — S1 vẫn gác trước S2**

```python
def test_slm_khong_duoc_cham_vao_doan_co_bien_the():
    """S2 chọn câu giá trị mà bỏ câu điều kiện thì vẫn đúng là RAG-130. S1 phải chặn
    trước, SLM chỉ được chạy ở nhánh an toàn."""
    ev = _evidence(text="Bản ECO 250 kPa.", has_variant_condition=True)
    with patch_selector(SlmLuonChon0()):
        assert not re.search(r"\d", chon_cau_de_noi(ev, "áp suất").spoken)
```

- [~] **Bước 3: chạy, chắc đỏ**

- [~] **Bước 4: cài đặt** `QwenSentenceSelector` — grammar ép đầu ra là mảng số
      nguyên; timeout dùng `slm_timeout_s`; mọi lỗi → đường lui Task 3.

- [~] **Bước 5: đo lại trên 40 case, so với baseline Task 5**

- [x] **Bước 6: cập nhật ADR-015 với bảng ba cột (hôm nay / S1+S3 / S1+S2+S3)** ✅ 14/08

---

## Tiêu chí nghiệm thu toàn kế hoạch

- [x] `display_text` **không đổi** ở cả 40 case — ADR-015 nguyên vẹn
      → `display_text ≥ speak_text` ở 40/40; display p50 968 ký tự vs speak p50 46.
- [x] `assistant.speech` < 500 KB mỗi lượt (hôm nay 4,60 MB)
      → **max 130,2 KiB** = 12,7% khung 1 MiB. Giảm 36 lần, còn dư 4× so với mục tiêu.
- [x] Audio p95 ≤ 12 s (hôm nay 65,6 s)
      → **11,4 s p95** / 9,4 s p50. Sát trần — đây là lý do `MAX_SPOKEN_CHARS` là 240
      chứ không phải 400 (bản 400 cho p95 19,2 s, trượt cổng).
- [x] 0/40 câu nói chứa số của một đoạn có biến thể
      → **0/41** mỗi run, kể cả sau khi nới cờ biến thể ngày 14/08.
- [x] Toàn bộ Task 1–5 chạy với `slm_enabled=False`
      → mặc định của `src/config.py`; S2 chỉ bật bằng `--slm-select` ở bộ đo.
- [x] Suite xanh trên **cả hai** loại máy: có model voice và không có
      → máy này **có** Piper (đo được 130,2 KiB payload thật) và suite xanh 1.075/1.068;
      CI **không** có model voice và cũng xanh. Hai nửa nằm ở hai chỗ, nên nói rõ:
      nửa "không có model" là bằng chứng của CI, không phải của máy này.

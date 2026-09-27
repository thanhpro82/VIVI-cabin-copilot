# Hoàn thiện Grounded RAG Response — Design

**Trạng thái:** Thiết kế, chờ duyệt.
**Nhánh:** `feature/grounded-rag-response`, tách từ `develop` tại `e548313`.
**Ngày:** 2026-08-11
**Ticket:** Hoàn thiện Grounded RAG Response.
**Phụ thuộc quyết định:** ADR-015 (SLM bắt buộc cho nhánh tra sổ tay) — **đang ở
Proposed**. Phần composer trong tài liệu này không được merge trước khi ADR-015 được
duyệt.

## Mục tiêu

Lượt tra sổ tay trả về câu trả lời **nghe được** và **truy nguyên được**: nội dung đọc
lên bằng TTS, và mỗi thẻ citation trên màn hình bấm được để xem chi tiết.

## Ba khoảng trống, đo bằng code chứ không bằng cảm nhận

| # | Khoảng trống | Bằng chứng |
|---|---|---|
| 1 | Lượt tra sổ tay trả về **một câu cố định**, nội dung chỉ nằm trong `citations[]` | `compose.py:16` — `"grounded_answer": "Đây là thông tin tôi tìm được trong sổ tay xe."` |
| 2 | `citation_id` **bị rơi** trên đường ra dây | `ivi_events.py:assistant_response_payload` phát 5/8 field, không có `citation_id` |
| 3 | `GET /api/v1/citations/{citation_id}` **404** | Không có route nào; `grep citations src/api/` chỉ ra `agent_routes.py` |

Khoảng trống 2 và 3 khoá nhau: FE gọi `getCitation(citationId)` (`turn/real.ts:223`)
nhưng không có id để gọi, và có id cũng không có route để tới.

Phần khó đã xong từ trước: ingest, index, truy hồi, định tuyến câu hỏi (ADR-011), và
`Citation` 8 field trong `src/rag/models.py:116` — kể cả `citation_id` mà
`retrieve.to_citations()` đã sinh sẵn. Việc còn lại là **tầng công khai**.

## Kiến trúc — bốn mảnh tách rời được

### 1. `citation_id` ra dây

`assistant_response_payload` (`src/services/ivi_events.py`) thêm `citation_id` vào từng
phần tử `citations`.

> **Ranh giới sở hữu:** file này thuộc Thành theo
> `docs/handoff/frontend-integration-map.md`. Theo thoả thuận đã chốt cho giai đoạn A
> của ticket HITL: **ta viết, Thành review**.

### 2. `CitationStore` — `src/services/citations.py` (mới)

Khuôn bám sát `ApprovalStore` (`src/agents/approval.py`) để nhóm không phải học một kiểu
kho thứ hai.

```python
class CitationRecord:      # Citation + chủ sở hữu
    citation: Citation     # đúng 8 field của data_model.md
    session_id: str

class CitationStore:
    def save(self, citations: list[Citation], session_id: str) -> None
    def get(self, citation_id: str) -> CitationRecord | None
    def forget_session(self, session_id: str) -> None
    record_count: int
```

**Hai trần, chặn hai kiểu phình khác nhau — bỏ cái nào cũng hở một đường:**

| Kiểu phình | Ai chặn |
|---|---|
| Nhiều phiên, mỗi phiên vài lượt | `forget_session()`, nối vào `_touch()` trong `session_state.py` đúng chỗ `ApprovalStore.forget_session` đang được gọi |
| **Một** phiên, rất nhiều lượt tra sổ tay — phiên đang dùng nên không bao giờ bị đuổi | Trần riêng `max_records=1024`, LRU |

Con số 1024 suy từ `RetrievalConfig.top_k = 8` (`retrieve.py:31`): giữ được khoảng **128
lượt tra sổ tay gần nhất**, đủ để tài xế cuộn ngược lại vẫn bấm được thẻ. Mỗi bản ghi
giữ `EXCERPT_CHARS = 300` ký tự, tổng khoảng 0,5 MB.

Ghi vào kho ở `rag_node`, ngay sau `to_citations()` — cùng chỗ, cùng lượt, nên id trong
`assistant.response` và id trong kho không thể lệch nhau.

### 3. `GET /api/v1/citations/{citation_id}` — `src/api/citation_routes.py` (mới)

- `Depends(require_driver)` — `api_spec.md:62` chốt vai trò *"Driver for own turn"*.
- Tra kho → phân giải chủ qua `citation → session_id → SessionRecord.user_id`.
- **Hai mã lỗi, bốn ca** (sửa 2026-08-11 sau hai vòng review — bản đầu gộp tất cả về
  `403`; `403` giờ chỉ dành cho ca duy nhất mà ta **chứng minh được** là của người khác):

  | Ca | Mã | Vì sao |
  |---|---|---|
  | Không tồn tại | `404 NOT_FOUND` | Thứ hỏng là **cái id**, không phải quyền của người gọi |
  | Đã bị đẩy khỏi kho có trần | `404 NOT_FOUND` | Như trên — trần LRU làm đúng việc của nó, không phải sự cố |
  | **Phiên sinh ra nó không phân giải được** | `404 NOT_FOUND` | Không xác định được chủ **không phải** là "thuộc về người khác" |
  | Phân giải được chủ, và chủ đó là người khác | `403 FORBIDDEN` | Đây mới đúng là chuyện quyền |

  Ca thứ ba có thật và không cần race nào: `/turns/voice` (`turns.py:111`) và
  `/agent/process` đều nhận `session_id` tuỳ ý mà **không gọi `create_session()`**, nên
  citation sinh từ những lượt đó mồ côi ngay từ lúc sinh — không có `SessionRecord` nào
  để đối chiếu. Trả `403` ở đó là khẳng định một điều ta không chứng minh được.

  > **Khoảng trống rộng hơn, không thuộc phạm vi ticket này:** vì `/turns/voice` chưa có
  > auth nên phiên của nó không bao giờ có `SessionRecord`, tức **mọi citation sinh từ
  > lượt thoại hiện không ai đọc được**. Tính năng citation vì vậy chỉ chạy trọn vẹn qua
  > `/turns/text`. Đây là khoảng trống có sẵn của route đó (docstring của nó tự ghi
  > "Phạm vi minimal-slice: không xác thực Authorization"), cần Thành đóng.

  Ca eviction mới là ca phổ biến — trần LRU sinh ra để làm đúng việc đó. Gộp nó vào
  `403` nghĩa là tài xế bấm vào thẻ citation **của chính mình** và nhận "bạn không có
  quyền", còn FE không phân biệt được "hết hạn" với "không phải của bạn".

  Cùng lập luận mà `/traces/{trace_id}` đã chốt (`observability.py:72`,
  `TASK-BE-OBS-001 §4`): 403 *"nói dối người gọi rằng họ thiếu quyền trong khi thứ họ
  hỏng là cái id"*. Cái mất là phòng thủ enumeration, nhưng `citation_id` là 48 bit ngẫu
  nhiên và chỉ từng được giao cho đúng chủ nên phòng thủ đó gần như không mua được gì.

  **Khác `/approvals/{id}/decision`, nơi vẫn gộp về `403` có chủ đích:** `approval_id`
  chỉ có nghĩa lúc đang pending, và lộ sự tồn tại của nó là lộ việc ai đó đang có lệnh
  xe chờ duyệt.
- Khai cả `404` lẫn `403` bằng `ErrorEnvelope` trong `responses={}` để `/docs` mô tả được
  hình dạng lỗi — cùng bất biến mà `test_traces_khai_schema_cho_nhanh_404` khoá.
- Trả **đủ 8 field** trong vỏ `{data: ...}`. `api_spec.md:328` chốt cả tám đều bắt buộc
  và field lạ bị từ chối. FE hiện chỉ đọc 5 (`real.ts:224`) nhưng nó destructure theo
  tên nên ba field thừa vô hại — trả đủ thì khỏi phải sửa hợp đồng lần hai khi Giáp cần
  `chunk_id` để nhảy tới đúng đoạn.
- Dùng `ApiError` cho vỏ lỗi, **không** `HTTPException` — FastAPI bọc `detail` thêm một
  tầng nên `frontend/.../shared/errors.ts` đọc `body.error.code` sẽ luôn miss.

### 4. Composer SLM — `rag_node.py` + `slm.py`

**Chỉ được merge sau khi ADR-015 chuyển sang Accepted.**

SLM là phụ thuộc **bắt buộc**: tắt, thiếu weights, lỗi, timeout đều dẫn tới
`grounded_refusal`. Không có đường rơi về trích xuất nguyên văn. Tối đa **một** lần gọi
SLM mỗi lượt.

## Luồng dữ liệu

```
câu hỏi → route → rag_node
   truy hồi evidence
   ├─ không đủ ────────────────────────→ grounded_refusal
   └─ đủ
        to_citations() → CitationStore.save(citations, session_id)
        SLM.compose(evidence)
          ├─ tắt / lỗi / timeout ───────→ grounded_refusal
          └─ text → verify(text, evidence)
                ├─ FAIL ───────────────→ grounded_refusal
                └─ OK ─────────────────→ grounded_answer(text, citations)
→ compose → response_text
→ emit_turn_lifecycle → assistant.response { display_text, citations[… + citation_id] }
→ FE: getCitation(citationId) → GET /citations/{id} → 8 field
```

Thứ tự có chủ đích: **ghi kho trước khi gọi SLM**. Citation là sự thật đã truy hồi được,
không phụ thuộc việc soạn câu có thành công hay không. Lượt kết thúc bằng
`grounded_refusal` vẫn có evidence đã ghi — hữu ích khi chẩn đoán vì sao nó bị từ chối.

## Cổng kiểm chứng

Tất định, không dùng LLM thứ hai: **mỗi câu trong output phải có đủ tỉ lệ từ nội dung
xuất hiện trong evidence đã truy hồi**. Ngưỡng `rag_grounding_min_support` trong
`src/config.py`.

**Dùng lại `src/rag/textnorm.py`, không tự chế lại phép đo.** Module đó đã có đúng hai
thứ cần, đã được dùng cho tiếng Việt trong chính tầng RAG này:

- `content_words(raw)` — tập từ mang nghĩa, đã bỏ hư từ (`STOPWORDS`) và từ một ký tự.
  Đây là định nghĩa chuẩn của "từ nội dung" trong tài liệu này; không có định nghĩa
  thứ hai.
- `lexical_overlap(a, b)` — tỉ lệ từ mang nghĩa của `a` xuất hiện trong `b`.

Một câu **được chứng minh** khi `lexical_overlap(câu, evidence_gộp) >= ngưỡng`, với
`evidence_gộp` là toàn bộ text của các evidence đã truy hồi cho lượt đó. Cả output phải
có **mọi** câu được chứng minh; một câu trượt là cả lượt `grounded_refusal`.

**Tách câu** theo dấu kết câu (`.`, `!`, `?`, xuống dòng), bỏ đoạn rỗng. Cố ý đơn giản:
tách sai theo hướng chia nhỏ hơn thì mỗi mảnh vẫn phải tự chứng minh được, tức sai về
phía chặt hơn — chấp nhận được cho một cổng an toàn.

Ngưỡng phải chỉnh được vì nó là đánh đổi hai chiều đối xứng và không chọn đúng từ trước
được: cao quá thì câu có căn cứ thật cũng bị đánh trượt và tính năng vô dụng; thấp quá
thì câu bịa lọt qua. Hiệu chỉnh bằng đo trên `eval/datasets/manual/v1` sẵn có.

**Giới hạn, ghi rõ ở ADR-015 mục "Cổng kiểm chứng":** bắt được bịa nguyên khối, **không**
bắt được bóp méo tinh vi — SLM đánh rơi một chữ "không" thì mọi từ nội dung vẫn khớp
evidence trong khi nghĩa đảo ngược. Với sổ tay xe, câu bị đảo nghĩa có thể là câu về an
toàn. Đây là rủi ro tồn đọng của quyết định, không phải thứ chỉnh ngưỡng sửa được.

## Bất biến — mỗi cái một test khoá

1. **Verifier chặn câu bịa** — câu nói về thứ không có trong evidence → `grounded_refusal`.
2. **Verifier cho qua câu có căn cứ** — chống việc đặt ngưỡng quá chặt biến cổng thành
   thứ từ chối tất cả. Không có test này thì bất biến 1 đạt được bằng cách trả `False`
   luôn.
3. **`slm_enabled=False` → `grounded_refusal`** — chứng minh phụ thuộc cứng là thật,
   không phải chỉ ghi trong tài liệu.
4. **`citation_id` có mặt trong `assistant.response`** cho mọi lượt `grounded_answer`.
5. **`GET /citations` chỉ trả `403` khi thật sự phân giải được chủ và chủ đó là người
   khác.** Ba ca còn lại — id lạ, bản ghi đã bị đẩy khỏi trần, phiên không phân giải
   được — đều là `404`; `200` cho chính chủ. Hai ca "bị đẩy khỏi trần" và "phiên không
   phân giải được" phải có test riêng: chúng là hai ca động lực thật, và là hai ca mà
   các bản trước trả lời sai.
6. **Citation của phiên bị đuổi thì biến mất** khỏi kho.

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `src/services/citations.py` (tạo) | `CitationStore`, `CitationRecord` |
| `src/api/citation_routes.py` (tạo) | `GET /citations/{citation_id}` |
| `src/agents/nodes/rag_node.py` (sửa) | Ghi kho; gọi SLM; áp cổng kiểm chứng |
| `src/agents/slm.py` (sửa) | Thêm đường soạn câu từ evidence |
| `src/services/ivi_events.py` (sửa) | Thêm `citation_id` vào payload — **vùng của Thành** |
| `src/api/session_state.py` (sửa) | Gọi `forget_session` của kho citation lúc đuổi phiên |
| `src/config.py` (sửa) | `rag_grounding_min_support` |
| `src/main.py` (sửa) | Đăng ký router mới |

## Thứ tự làm

Mảnh 1–3 **không phụ thuộc ADR-015** và đang chặn FE của Giáp, nên làm trước và mở PR
riêng được. Mảnh 4 chờ nhóm duyệt ADR.

## Cập nhật 2026-08-11 sau khi merge `develop`

`develop` chạy thêm 36 commit trong lúc nhánh này làm. Ba thứ chạm vào tài liệu này:

- **Số ADR đổi: 014 → 015.** Thành đã dùng ADR-014 cho `ws-ivi-event-replay-and-retention`.
- **`llm` được miễn trừ khỏi gate readiness của `/healthz`** (`b2e5724`, issue #48), với
  lý do "`slm_enabled=False` theo thiết kế, không phải sự cố". ADR-015 kéo ngược hướng
  đó — xem mục "Xung đột với quyết định nhóm ngày 2026-08-11" trong ADR.
- **`/ws/ivi` đã có bearer + role + Origin + kiểm chủ phiên** (`4641f8c`), và tầng
  replay/retention đã xong (PR #43). Hai món nợ mà thiết kế HITL trước đây ghi là
  `CHƯA RÕ #11` giờ đã đóng — không còn là việc của ticket này.

## Rủi ro

1. **Nhánh tra sổ tay ngừng chạy trên demo hiện tại** cho tới khi có weights qua gate —
   xem ADR-015 hệ quả 1. Đây là rủi ro nặng nhất và nó thuộc về quyết định, không thuộc
   về thiết kế này.
2. **Verifier là heuristic, không phải chứng minh** — xem trên.
3. **Độ trễ**: thêm một lần gọi SLM vào đường tra sổ tay, mà Qwen 3B đã trượt đúng gate
   độ trễ ở SPIKE-001. Chưa đo trên đường này; không được trình bày như đã đạt.
4. **`ivi_events.py` là file của Thành** — mảnh 1 cần cậu ấy review, như giai đoạn A.

## Ngoài phạm vi

`#8 traces`, `#9 metrics`, `ui.policy`, `transcript.partial`, replay cursor, và việc
sửa `README.md`/`CLAUDE.md` về trạng thái `llm` (làm cùng lúc ADR-015 chuyển sang
Accepted, không sớm hơn).

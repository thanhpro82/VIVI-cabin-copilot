# Backend Flow Audit — 2026-08-12

> Quét toàn bộ `src/` (89 file `.py`, ~11.000 dòng) theo **luồng chạy**, không theo thư mục.
> Mỗi phát hiện dưới đây đều trỏ tới `file:line` cụ thể và đã được đọc trực tiếp từ cây làm việc
> tại `develop` HEAD `05fb3fe`, không suy từ tài liệu.
>
> **Phạm vi**: chỉ backend (`src/`). Không audit `frontend/`, `experiments/offline_poc/`,
> SPIKE-002 (không có trong cây này), và các script dưới `scripts/`.
>
> **Không thuộc phạm vi phát hiện**: những giới hạn mà chính code đã ghi rõ là đánh đổi có
> chủ đích *và* đã có ADR/issue chống lưng (in-memory store, `slm_enabled=False`, simulator-only).
> Chúng được nhắc lại ở §8 để hiểu bối cảnh, không tính là lỗi.
>
> **Hai chuỗi mã, hai câu hỏi khác nhau.** `BE-*` (§3, §4) trả lời *luồng có đúng không* — quyền, hợp
> đồng, tính trung thực của dữ liệu vận hành. `FN-*` (§6) trả lời *hệ làm được việc gì và làm tốt tới
> đâu* — thứ người dùng cuối cảm nhận. Một lỗi FN không làm hỏng bất biến nào, và vẫn là lý do buổi
> demo trông kém.
>
> **Nếu chỉ có 5 phút**: đọc §5 (mười hai kịch bản đời thực) rồi §6.3 (kết luận chức năng).

## 1. Bằng chứng nền

| Hạng mục | Kết quả | Lệnh |
|---|---|---|
| Test suite (root) | **901 passed, 20 skipped, 160,95 s** | `$env:MQTT_ENABLED="false"; .\.venv311\Scripts\python.exe -m pytest tests/ -q` |
| Lint | **All checks passed** | `.\.venv311\Scripts\python.exe -m ruff check src/` |
| Python | 3.11.9 (`.venv311`) | — |
| Nhánh / HEAD | `develop` @ `05fb3fe` | `git log --oneline -1` |

**Lệch tài liệu cần sửa**: `CLAUDE.md` ghi *"895 passed, 20 skipped in ~55-95 s"*. Số thật hôm nay
là **901 passed / 20 skipped / 161 s**. Số lượt test lệch 6; **thời gian lệch gần gấp đôi cận trên**.
`docs/p0_gap_audit_2026-08-12.md §5.1` đã yêu cầu chốt lại baseline — con số ở bảng trên là con số đó.

## 2. Bản đồ luồng backend

Mười ba luồng độc lập. Cột "Điểm vào" là nơi request/message chạm backend lần đầu.

| # | Luồng | Điểm vào | File chính |
|---|---|---|---|
| F1 | Đăng nhập | `POST /api/v1/auth/login` | `api/auth_routes.py`, `services/auth.py` |
| F2 | Tạo phiên | `POST /api/v1/sessions` | `api/session_routes.py`, `api/session_state.py` |
| F3 | Lượt văn bản (đồng bộ) | `POST /api/v1/turns/text` | `api/turns.py:265` |
| F4 | Lượt thoại (bất đồng bộ) | `POST /api/v1/turns/voice` | `api/turns.py:110` |
| F5 | Agent graph | `graph.ainvoke(...)` | `agents/graph.py` + `agents/nodes/*` |
| F6 | HITL quyết định + resume | `POST /api/v1/approvals/{id}/decision` | `api/approvals.py` |
| F7 | Tra sổ tay (RAG) | nhánh `rag` của F5 | `agents/nodes/rag_node.py`, `rag/retrieve.py` |
| F8 | Đọc trạng thái xe | `GET /api/v1/vehicle/state` | `api/routes.py:79` |
| F9 | Thực thi lệnh xe | `execute_node` → gateway | `services/vehicle_gateway.py`, `tool_executor.py`, `vehicle_sim/` |
| F10 | Stream tài xế | `WS /ws/ivi` | `api/ws.py:398`, `services/ivi_events.py` |
| F11 | Stream kỹ sư + quan sát | `WS /ws/engineer`, `/traces`, `/metrics/summary` | `api/ws.py:278`, `services/trace_*.py`, `metrics.py` |
| F12 | Readiness | `GET /healthz` | `api/health.py`, `services/health.py` |
| F13 | Giọng nói (STT/TTS) | gọi từ F4 và F10 | `services/voice.py`, `voice_correction.py` |

### Xương sống của một lượt điều khiển

```
HTTP  ──► turns.py ──► session lock ──► graph.ainvoke
                                          │
     normalize ──► route ──► validate ──► safety ──► [approval] ──► execute ──► compose
       │             │          │           │            │             │
       │             │          │           │            │             └─ VehicleGateway
       │             │          │           │            │                  ├─ InProcess (MQTT_ENABLED=false)
       │             │          │           │            │                  └─ MqttVehicleGateway
       │             │          │           │            │                        └─ ToolExecutor ──► broker ──► vehicle_sim
       │             │          │           │            └─ interrupt() → ApprovalStore → HTTP quyết định → Command(resume=…)
       │             │          │           └─ **chỗ DUY NHẤT gán safety_level** (policy.py)
       │             │          └─ allowlist + schema + đồ thị depends_on
       │             └─ luật tất định (không gọi model)
       └─ chụp snapshot xe + dọn state lượt trước
                                          │
                                          ▼
                       emit_turn_lifecycle ──► IviEventBus ──┬──► /ws/ivi (theo session)
                                                             └──► TraceCollector (global) ──► TraceStore ──► /ws/engineer, /traces, /metrics
```

Ba ranh giới đáng chú ý và **đều được mã hoá bằng validator chứ không bằng quy ước**:

1. `CandidateActionPlan` (router/SLM sinh) **không có** field safety; chỉ
   `policy.materialize_action_plan()` dựng được `ActionPlan`, và `ActionPlan` từ chối validate nếu
   có step S2 mà `requires_approval=False` (`agents/contracts.py:99-103`).
2. `RouteDecision` loại trừ: `control`/`offer` bắt buộc có `candidate_plan`, bốn disposition còn lại
   bắt buộc **không** có (`agents/contracts.py:119-127`).
3. `TraceRecord` **không có field nào chứa văn bản người dùng** — redaction bảo đảm bằng cấu trúc,
   không bằng kỷ luật (`services/trace_store.py:14-18`).

## 3. Tổng hợp phát hiện

18 phát hiện về **luồng, quyền và dữ liệu vận hành**, xếp theo mức độ chứ không theo thứ tự luồng.
Sáu phát hiện về **chức năng người dùng cảm nhận được** (`FN-01`…`FN-06`) nằm riêng ở §6 — chúng
không vi phạm bất biến nào nên không thuộc bảng này.

| ID | Mức | Luồng | Tóm tắt |
|---|---|---|---|
| BE-01 | **Cao** | F4 | `POST /turns/voice` thiếu **cả ba** điều kiện bắt buộc của `api_spec.md:47` (auth, version, idempotency) |
| BE-02 | **Cao** | — | `POST /api/v1/chat` chạy agent không auth, trên graph **không có** ApprovalStore |
| BE-03 | **Cao** | — | `POST /agent/process` không auth; chỉ chặn bằng `APP_ENV`, mặc định là `development` |
| BE-04 | Trung bình | F8 | `GET /vehicle/state` không có auth dependency nào |
| BE-05 | Trung bình | F11 | `GET /traces/{id}` engineer-only, nhưng spec cho phép "Driver for own turn" |
| BE-06 | Trung bình | F3/F4/F9 | `ActionPlan.vehicle_id` không phải chiếc xe thật sự nhận lệnh |
| BE-07 | Trung bình | F6/F9 | `execution_group_id` luồn qua 6 file nhưng **không caller nào set** |
| BE-08 | Trung bình | F11 | `mqtt.latency_ms` của `/metrics/summary` vĩnh viễn rỗng |
| BE-09 | Trung bình | F11 | `trace_id` do client chi phối là khoá chính của `TraceStore` → ghi đè trace người khác |
| BE-10 | Trung bình | F6/F11 | Nửa sau lượt S2 chạy dưới `trace_id` mới → `approval_wait_ms` luôn `null` |
| BE-11 | Thấp | F11 | `bus.set_sampler()` gọi lại mỗi kết nối engineer, closure giữ socket mới nhất |
| BE-12 | Thấp | — | `routes._agent` là singleton không được `reset_vehicle_gateway()` dọn |
| BE-13 | Thấp | F4/F13 | Route nhận `audio/ogg` + `audio/pcm` nhưng tầng STT chỉ parse WAV → luôn `STT_FAILED` |
| BE-14 | Thấp | F1 | Login không rate-limit, không revoke; trần 256 token đá token cũ ra (đăng xuất ngầm) |
| BE-15 | Thấp | F12 | Probe `mqtt`/`sqlite` không cache: mỗi lần poll = 1 publish QoS 1 + 1 ghi/xoá SQLite |
| BE-16 | Thấp | F10 | `replay_snapshot` trả `REPLAY_WINDOW_EXPIRED` cho cursor trỏ đúng event cuối sau khi TTL dọn buffer |
| BE-17 | Thấp | F5 | Cạnh `route → slm` của graph không bao giờ đi qua với router hiện tại |
| BE-18 | Thấp | — | Ba chỗ tài liệu/docstring mô tả sai hiện trạng auth |

## 4. Chi tiết theo luồng

### F1 — Đăng nhập (`POST /auth/login`)

`services/auth.py` giữ hai user cứng, token opaque `secrets.token_urlsafe(32)`, TTL 12 h, LRU 256.
So sánh mật khẩu bằng `secrets.compare_digest` (`auth.py:70`) — đúng, không so `==`.
Ngoại lệ version cho login (`X-Schema-Version` **hoặc** `version=1.0` trong Content-Type) khớp
`api_spec.md:44` (`auth_deps.py:105-123`).

**BE-14 (Thấp)** — Ba thiếu sót cùng họ, đều chỉ quan trọng khi demo mở ra nhiều người:
- Không giới hạn tần suất trên `/auth/login`; mật khẩu demo nằm nguyên văn trong source
  (`auth.py:34-49`).
- Không có endpoint logout/revoke — token chỉ hết hiệu lực khi hết TTL.
- Trần `MAX_TOKENS = 256` đuổi theo LRU (`auth.py:83-84`): đăng nhập lần thứ 257 **đá token cũ nhất
  ra**, tức một người dùng đang hoạt động bị đăng xuất ngầm mà không có tín hiệu nào. Không nghiêm
  trọng ở demo một máy, nhưng hành vi "đăng xuất vì người khác đăng nhập" là thứ rất khó chẩn đoán
  khi gặp.

### F2 — Tạo phiên (`POST /sessions`)

Đủ ba điều kiện của spec: `require_driver` + `require_schema_version` + `require_idempotency_key`
(`session_routes.py:30-35`). `create_session()` là **điểm tạo `SessionRecord` chính chủ duy nhất**
(`session_state.py:104`), chạm trước `get_vehicle`/`get_graph` để lượt đầu không trả giá first-touch.
Idempotency dùng `begin`/`finish`/`abandon` có lock, và `abandon` được gọi trong `except`
(`session_routes.py:75-77`) — đúng hợp đồng của store.

`vehicle_id` trong body **không được validate** so với `settings.vehicle_id`. Xem BE-06.

### F3 — Lượt văn bản (`POST /turns/text`)

Đây là luồng làm đúng nhất trong repo, và nên dùng làm khuôn cho những luồng còn lại:

- Đủ ba điều kiện bắt buộc (`turns.py:265-271`).
- Kiểm ownership gộp "không tồn tại" với "của người khác" vào cùng một 403 để không rò enumeration
  (`turns.py:284-294`).
- `get_graph()` được gọi **ngay** sau kiểm quyền, trước mọi `await` khác, để thu hẹp khoảng hở
  LRU-eviction (`turns.py:302`) — chú thích còn nói thẳng là không đóng hẳn được.
- `except BaseException` quanh phần thân để bắt cả `asyncio.CancelledError` và luôn `abandon()` chỗ
  đã đặt trong idempotency store (`turns.py:356-360`). Đây là bản sửa đúng: `CancelledError` không
  kế thừa `Exception`, bắt hụt là khoá cứng vĩnh viễn đúng `Idempotency-Key` mà client sẽ retry.
- `_record_end_to_end` gọi ở **mọi** lối ra kể cả lối lỗi, và gọi **trước** `emit_turn_lifecycle` vì
  sự kiện terminal seal trace rồi phát ngay (`turns.py:56-67`).
- Mở trace ngay tại route (`turns.py:336`) vì route đồng bộ không phát `turn.accepted`.

### F4 — Lượt thoại (`POST /turns/voice`)

> **BE-01 (Cao) — Route P0 duy nhất không có auth, không có version, không có idempotency.**

`api_spec.md:47` chốt cho `/api/v1/turns/voice`: *Bearer Driver/owner · `X-Schema-Version: 1.0`
required · `Idempotency-Key` Required*. Hiện trạng (`turns.py:110-111`):

```python
@router.post("/turns/voice", status_code=202)
async def submit_voice_turn(session_id: str, request: Request, background_tasks: BackgroundTasks) -> dict:
```

Không có `Depends` nào. Không kiểm `session_id` tồn tại hay thuộc về ai — chỉ gọi
`get_vehicle(session_id)` và `get_graph(session_id)` (`turns.py:135-136`), mà cả hai đều **tự sinh
state ngầm** cho bất kỳ chuỗi nào. Ba hệ quả, và cả ba đều quan sát được:

1. **Bề mặt thực thi actuator không xác thực.** Bất kỳ ai chạm được cổng 8000 đều đẩy được audio vào
   và chạy trọn pipeline; lệnh S1 (điều hoà, âm lượng, sưởi ghế, dẫn đường) **thực thi thẳng**, không
   qua HITL. Lệnh S2 vẫn dừng ở `interrupt()` nên không tự chạy — nhưng đó là may, không phải thiết kế.
2. **Approval sinh từ lượt đó không bao giờ quyết định được.** `POST /approvals/{id}/decision` kiểm
   quyền qua `get_session_record(record.session_id)` (`approvals.py:101`); session tạo ngầm không có
   `SessionRecord`, nên `session_record is None` → **403 vĩnh viễn**. Lượt treo ở `waiting_approval`
   không lối thoát. Chỉ không xảy ra khi FE luôn đi qua `POST /sessions` trước — tức đúng đắn phụ
   thuộc vào kỷ luật của client.
3. **Citation của lượt đó luôn 404.** Cùng cơ chế; `citation_routes.py:63-70` đã ghi thẳng ca này
   trong chú thích và test `test_citation_routes.py:133` khoá lại — tức nhóm **đã biết** và chọn cách
   trả 404 thay vì sửa gốc.

Thiếu `Idempotency-Key` còn nghĩa là client retry sau timeout mạng sẽ chạy lượt **hai lần**; với lượt
điều khiển S1 đó là hai lần chạm actuator.

**Đề xuất**: thêm `Depends(require_driver)` + `Depends(require_schema_version)` +
`Depends(require_idempotency_key)`, và kiểm ownership `session_id` đúng khuôn `turns.py:284-294`.
Các dependency đã tồn tại sẵn — đây là 4 dòng, không phải một ticket kiến trúc. Sửa xong thì BE-01
hệ quả (2) và (3) cũng đóng theo.

**BE-13 (Thấp)** — `_ALLOWED_BASE_CONTENT_TYPES` nhận `audio/wav` + `audio/ogg`, và `audio/pcm` khi
đủ ba parameter (`turns.py:47-51`), nhưng `voice._validate_audio` parse bằng stdlib `wave`
(`voice.py:107-121`). Mọi lượt `ogg`/`pcm` do đó **luôn** kết thúc ở
`transcript.final(unusable)` + `STT_FAILED`. Route đang hứa nhiều hơn tầng dưới làm được; chú thích
đã ghi nhận, nhưng hợp đồng nói "accept" mà thực tế 100% fail thì nên hoặc từ chối sớm bằng 422 với
lý do rõ, hoặc thực hiện được.

**Điểm làm đúng đáng giữ**: `voice.get_stt_engine()` được gọi **ngoài** `try` bắt `ValueError`
(`turns.py:169`) để lỗi cấu hình `STT_PROVIDER` không bị đổ oan thành "audio của tài xế hỏng" —
đây là loại phân biệt rất dễ làm sai.

### F5 — Agent graph

`build_graph` (`graph.py:111`) tiêm được toàn bộ phụ thuộc, không có singleton mức module. Import
`rag_node` bị hoãn tới **lúc nhánh sổ tay thật sự chạy** (`graph.py:130-134`) nên checkout thiếu extra
RAG vẫn dựng được graph — đúng, vì lệnh điều khiển không có lý do gì phải trả giá `faiss`/`bs4`.

Phân loại an toàn tập trung tuyệt đối: `policy.classify` là hàm duy nhất gán `safety_level`
(`policy.py:49-58`), và `safety_node` là node duy nhất gọi nó (`nodes/safety.py:8`). `_S1_TOOLS`,
`_ALWAYS_S2_TOOLS`, `_STATIONARY_ONLY_TOOLS` khớp `docs/safety_and_hitl.md`; ngưỡng `speed_kph > 5`
của `VIVI_API_Spec.md` đúng là **không** được implement, như ADR-010 yêu cầu.

`safety_node` fail-closed khi `vehicle_snapshot` rỗng (`safety.py:16-17`), và chặn ở **đúng node đó**
chứ không sớm hơn — nên broker chết không kéo theo mất luôn nhánh RAG. Chi tiết nhỏ nhưng đúng.

`_timed()` ghi độ trễ ra `TraceStore` thay vì vào `AgentState` (`graph.py:81-108`) vì state là
`TypedDict` không reducer, hai node ghi cùng key sẽ đè nhau; và `record_stage` là last-write-wins chứ
không cộng dồn vì LangGraph chạy lại thân node khi resume. Cả hai lý do đều đúng và đều được ghi.

**BE-17 (Thấp)** — `_route_after_routing` (`graph.py:38-49`) có nhánh `not_control → slm`, nhưng
`DeterministicControlRouter` **luôn** trả `intent="manual_query"` kèm mọi `not_control`
(`router.py:142`, `:150`, `:172`), và nhánh `intent == "manual_query"` được kiểm **trước**
(`graph.py:46`). Nên cạnh `route → slm` là code không bao giờ chạy với router hiện tại; đường duy
nhất tới SLM planner là `rag → slm` khi `route_reason == "default_to_manual"` (`graph.py:199-205`).
Không phải bug — hành vi vẫn đúng — nhưng sơ đồ trong tài liệu gợi ý có hai đường vào SLM, và người
đọc sau sẽ tìm nhầm chỗ.

**Router** (`router.py`): ba lớp chống "tuân thủ một phần trong im lặng" (lớp lỗi KI-001) đều còn
nguyên và đều có chú thích giải thích **con số sai cụ thể** mà bản trước sinh ra —
`_reject_ambiguous_number` (`:194`), đọc trăm+chục cùng một lượt (`:409`), và bỏ tiểu từ nghi vấn
`không` cuối câu trước khi đọc số (`:426`). Đây là chất lượng hiếm; đừng "dọn dẹp" ba chỗ này.

### F6 — HITL

`request_approval_node` (`nodes/approval.py:88`) có **năm** cổng fail-closed sau khi resume, kiểm
đúng thứ tự: tra được bản ghi → **ownership (session + turn)** → status `approved` → digest plan khớp
→ đọc **state sống** và so version → **tính lại plan** và so digest lần nữa. Cổng cuối là cổng thật
sự chặn "xe đã lăn bánh trong lúc chờ người duyệt biến S2 thành S3" (`approval.py:162-171`).
Id trong payload resume chỉ dùng để **tra cứu**, quyền đến từ bản ghi trong store — ghi rõ ở
`approval.py:128-133`, và đó là lý do nhánh so digest không phải code chết.

`approval_id_for` (`approval.py:38`) tiền tố độ dài từng thành phần thay vì nối bằng dấu phân cách,
vì `session_id` đến từ body client và có thể tự dịch ranh giới field. Đúng.

`ApprovalStore` kiểm "tối đa một pending mỗi session" **trong** lock cùng thao tác ghi
(`approval.py:112-124`), không phải check-rồi-act. `_evict_locked` không bao giờ đuổi bản ghi
`pending`, và chọn nạn nhân xong mới xoá (`approval.py:196-203`).

`POST /approvals/{id}/decision` chốt quyết định **trước** khi resume graph, và chỉ xếp task nền khi
bản ghi **vừa** chuyển `pending →` trong chính lệnh gọi này (`approvals.py:173`, `:200`) — nếu không,
một cú double-click sẽ tạo **hai sự kiện terminal** cho cùng một lượt. Lý do được ghi thẳng ở
`approvals.py:196-199`.

> **BE-07 (Trung bình) — `execution_group_id` không bao giờ được set.**

Field này có mặt ở `VehicleCommand`, `CommandEvent`, `ToolResult`, `TraceRecord`, `Admission`, và
trong chữ ký của cả `VehicleGateway.execute`, `ToolExecutor.execute`, `InProcessVehicleGateway.execute`
(9 chỗ). Nhưng `execute_node` — người gọi duy nhất — **không truyền nó**
(`nodes/execute.py:61-68`), nên nó luôn là `None` end-to-end.

Hệ quả: `admission.execution_group_id` trong `GET /traces/{id}` luôn `null`, và một plan nhiều bước
được duyệt **gộp** (một approval, nhiều actuator) không có id nhóm nào để audit. `docs/safety_and_hitl.md`
mô tả bundled approval; hạ tầng đã sẵn, chỉ thiếu một dòng gán ở `execute_node`. Đây là ca "trông như
đã làm" nguy hiểm hơn ca "rõ ràng chưa làm".

> **BE-10 (Trung bình) — nửa sau lượt S2 rơi vào một trace khác.**

`_resume_and_publish` đúc `trace_id` mới (`approvals.py:244`). `TraceCollector.resolve` cứu được bằng
index phụ `turn_id → trace_id` (`trace_collector.py:106-132`) nên trace không mất hẳn, nhưng
`_approval_wait_ms` vẫn trả `None` (`trace_collector.py:334-347`) — tức **chỉ số đo thời gian con
người suy nghĩ, thứ mà `api_spec.md:382` tách riêng khỏi `stage_latencies_ms`, vĩnh viễn trống**.
Đã ghi là nợ Tier 3 trong `TASK-BE-OBS-001`; cần `trace_id` trên `ApprovalRecord`.

### F7 — RAG

Node giữ mỏng, logic ở `rag/retrieve.py`. Chấm điểm bằng **hai** tín hiệu (cosine + trùng từ vựng),
và chú thích ghi con số đã đo: ngưỡng điểm đơn thuần cho hallucination 20%, thêm điều kiện từ vựng
kéo xuống 5% trên 60 case (`retrieve.py:70-84`).

`index_is_built()` kiểm bằng cách **đọc đĩa** thay vì dò chuỗi trong thông điệp lỗi của faiss
(`rag_node.py:34-37`) — đúng, vì thông điệp lỗi đổi theo phiên bản thư viện. `rag_stage` trong graph
bọc thêm một lưới an toàn cuối và **không** gán nhầm lỗi thật thành "chưa dựng chỉ mục"
(`graph.py:139-151`).

Composer trích **nguyên văn** `evidence[0].text` chứ không phải `citation.excerpt`
(`compose.py:44-83`), vì excerpt bị cắt ở 300 ký tự trong khi 39/40 đoạn thật dài hơn — cắt cụt là
mất đúng các điều kiện theo phiên bản (ECO/PLUS, SDI/CATL). Khi buộc phải cắt thì cắt ở ranh giới câu
và **nói rõ là còn tiếp**. Đây là kết luận đã đo của ADR-015, không phải lựa chọn thẩm mỹ.

Citation được ghi vào kho **ngay tại chỗ sinh ra** (`rag_node.py:92`) nên id trong
`assistant.response` và id trong kho không thể lệch.

### F8 — `GET /vehicle/state`

Ba nhánh 503 đánh giá đúng thứ tự, mỗi nhánh một `reason` phân biệt được, và **không** trả snapshot cũ
kèm cảnh báo (`routes.py:97-153`). Lập luận ghi trong docstring — "dữ liệu của một simulator đã chết
thì không còn authoritative, trả 200 lúc đó là nói dối một cách im lặng" — đúng và nên giữ.

> **BE-04 (Trung bình) — không có auth dependency.**

`api_spec.md:61` ghi vai trò là *"Driver/Engineer as scoped"*. Route hiện không có `Depends` nào
(`routes.py:79-97`). Trạng thái xe không phải dữ liệu nhạy cảm ở demo, nhưng nó **rò rỉ trạng thái
vật lý của xe cho người không đăng nhập** (cửa đang mở/đóng, xe đang chạy bao nhiêu km/h), và nó là
một trong 12 interface P0 nên độ lệch so với spec là đo đếm được.

### F9 — Thực thi lệnh xe

Ba tầng chống thực thi kép, và mỗi tầng bắt một ca khác nhau — đây là phần thiết kế chắc nhất của
backend:

| Tầng | Khoá | Bắt được ca |
|---|---|---|
| `execute_node` / gateway | `plan_id:step_id` | replay ở mức plan (mỗi lần gọi lại sinh `command_id` mới) |
| `ToolExecutor._results` | `plan_id:step_id` | replay HTTP/graph trước khi chạm broker |
| `VehicleSimulator._results` | `command_id` | duplicate delivery của QoS 1 |
| `expected_state_version` | — | lưới cuối khi cache bị evict (`stale_state`) |

Retry **đúng một lần** và **chỉ** cho transient transport failure; `stale_state`,
`unsafe_vehicle_state`, `tool_not_allowed`, `invalid_arguments` không bao giờ retry
(`tool_executor.py:107-138`). `_on_event` **bỏ qua** `phase="accepted"` và chờ tiếp tới terminal
(`tool_executor.py:161-171`) — nếu resolve waiter ở đó thì lượt sẽ báo thành công trước khi giá trị
thật đạt đích. Simulator P0 chưa phát `accepted`, nhưng chỗ này đã đúng sẵn cho P1.

`execute_node` **đánh dấu** mọi bước còn lại là `skipped` thay vì lặng lẽ bỏ chúng khỏi `results`
(`execute.py:70-86`), và phân biệt `skipped_external_state_change` với `skipped_due_to_prior_failure`
theo `error_code == "stale_state"`. Hồ sơ đầy đủ là thứ dùng để chứng minh an toàn — đúng.

`MqttVehicleGateway.snapshot()` đo tuổi **heartbeat**, không đo tuổi **state**
(`vehicle_gateway.py:270-284`). Lập luận đúng: state là event-driven + retained nên "lâu không có
snapshot mới" nghĩa là "không có gì đổi". `_await_floor` được ghi rõ là **tối ưu độ trễ, không phải
cơ chế an toàn** (`vehicle_gateway.py:330-343`) — cảnh báo này quan trọng, đừng ai tăng budget lên
vài giây rồi coi nó là bảo đảm.

> **BE-06 (Trung bình) — `ActionPlan.vehicle_id` không phải chiếc xe nhận lệnh.**

Ba nguồn khác nhau cho cùng một field:

| Điểm vào | Giá trị đưa vào graph | Nguồn |
|---|---|---|
| `POST /turns/voice` | `"veh-demo"` | hard-code (`turns.py:227`) |
| `POST /turns/text` | `session_record.vehicle_id` | chuỗi client tự khai ở `POST /sessions`, **không validate** |
| `POST /agent/process` | `"veh-demo"` | hard-code (`agent_routes.py:111`) |
| `POST /chat` | `"veh-demo"` | hard-code (`routes.py:54`) |

Trong khi đó lệnh MQTT thật luôn mang `vehicle_id = gateway.vehicle_id = settings.vehicle_id`
(`tool_executor.py:97`, mặc định `vehicle-demo-01`), và simulator **từ chối** lệnh không khớp id của
nó (`vehicle_sim/runtime.py:106-112`). Nên `ActionPlan.vehicle_id` là một field trang trí: nó xuất
hiện trong response REST và trong plan đã ký digest, mà không mô tả đúng chiếc xe nào bị tác động.

Với ADR-013 ("một chiếc xe cho cả hệ thống") thì cách đúng là lấy `vehicle_id` từ chính gateway ở
`normalize_node`, và `POST /sessions` từ chối `vehicle_id` không khớp `settings.vehicle_id` thay vì
nhận bất kỳ chuỗi nào.

### F10 — `WS /ws/ivi`

Bốn điều kiện của spec đều có: subprotocol `vivi.v1` (kiểm **trước** auth, đóng `1003` chứ không
`4401` — đúng, vì token mới không sửa được lỗi giao thức), bearer + role + Origin
(`ws.py:135-165`), và session ownership (`ws.py:440-456`).

`_accept_ws` không bao giờ chọn lại `bearer.*` làm subprotocol phản hồi (`ws.py:128`) — nếu chọn thì
token sẽ nằm trong header handshake và trong log của mọi proxy trên đường đi. Chi tiết nhỏ, hậu quả lớn.

Vòng flush dùng `while pending_live:` chứ không `for` (`ws.py:509-511`), và cờ `replay_done` lật ngay
sau đó **không có `await` xen giữa** — đây là bản sửa của deadlock đã ghi trong `CLAUDE.md`, và lập
luận trong chú thích (`ws.py:485-495`) đúng.

`event_id`/`sequence` gán **đúng một lần tại bus**, thuộc về **session** chứ không thuộc connection
(`ivi_events.py:136-166`) — nên reconnect tiếp tục đánh số, đúng ADR-014.

**BE-16 (Thấp)** — `replay_snapshot` tính
`earliest = buffer[0]["sequence"] if buffer else stream.sequence + 1` (`ivi_events.py:124`). Sau khi
`_BUFFER_TTL_SECONDS` dọn buffer nhưng **giữ** `sequence`, một client quay lại với cursor trỏ đúng
event cuối cùng (`last_sequence == stream.sequence`) sẽ rơi vào `last_sequence < earliest` →
`REPLAY_WINDOW_EXPIRED`, dù thực tế **không có gì để replay** và cursor hoàn toàn hợp lệ. Fail an
toàn (client kết nối lại không cursor), nhưng nó biến một ca bình thường thành một lỗi hiển thị.
Chưa ai gặp vì FE hiện **không bao giờ gửi cursor** — xem `p0_gap_audit §1`.

### F11 — Quan sát (`/ws/engineer`, `/traces`, `/metrics/summary`)

Kiến trúc đúng: **một kho** (`TraceStore`), ba khung nhìn, không có counter song song
(`metrics.py:1-8`). Thêm metric mới là thêm một phép fold, không phải nhớ tăng biến ở năm chỗ.
`to_trace_data` dùng chung cho cả `GET /traces/{id}` lẫn event `trace` trên WS (`trace_view.py:1-8`)
vì `api_spec.md:662` có hẳn acceptance test đòi hai bề mặt phải giống nhau.

`TraceCollector` nghe bus thay vì chen lệnh ghi vào `emit_turn_lifecycle`, và **bắt được nhiều hơn**:
hai đường thoát lỗi trong `turns.py` (`STT_FAILED`, `INTERNAL_ERROR`) publish `turn.failed` thẳng lên
bus, không đi qua `emit_turn_lifecycle` (`trace_collector.py:6-11`). Bảng `_HANDLERS` là **toàn bộ**
bề mặt đọc và chỉ chạm số/enum — redaction có kiểm soát được.

`window_bounds` đẩy biên phải tới `now + 1µs` (`metrics.py:250-277`); phân tích trong docstring về
độ phân giải đồng hồ Windows/Python 3.11 (`datetime.now()` nhảy mỗi ~1 ms, 200/200 bản ghi vừa tạo
bị vứt khỏi cửa sổ) là root-cause thật của issue #67, không phải vá test.

> **BE-09 (Trung bình) — client chi phối khoá chính của kho trace.**

`resolve_trace_id` nhận `X-Trace-Id` của client nếu khớp `^[A-Za-z0-9_.:-]{8,64}$`
(`context.py:24`, `:38-43`) — đúng theo `api_spec.md:9`, và regex đã chặn newline/khoảng trắng để
không chèn được log giả. Nhưng giá trị đó trở thành **khoá chính** của `TraceStore`
(`turns.py:336` → `trace_store.py:161`). `open()` với cùng `trace_id` nhưng `turn_id` khác sẽ
**thay** bản ghi cũ, chỉ để lại một `logger.warning` (`trace_store.py:176-192`).

Nghĩa là driver A gửi `X-Trace-Id` trùng với trace đang mở của driver B thì trace của B biến mất khỏi
`GET /traces/{id}` và khỏi `/metrics/summary`. Không lộ dữ liệu (đọc trace là engineer-only), nhưng
là một đường **xoá bằng chứng vận hành của người khác** mà chỉ cần đoán trúng một chuỗi.
Cách đóng rẻ nhất: khoá kho theo id **server sinh**, và giữ `X-Trace-Id` của client như một field
tương quan riêng.

> **BE-08 (Trung bình) — `mqtt.latency_ms` không bao giờ có số.**

`TraceRecord.step_latencies_ms` được khai (`trace_store.py:120`) và được đọc (`metrics.py:165-166`),
nhưng **không có chỗ nào ghi**. Nguyên nhân gốc: payload dây `tool.result` không mang `latency_ms`
(`ivi_events.py:392-399`) dù `ToolResult` nội bộ có. Nên một trong 8 nhóm của `/metrics/summary` trả
`count=0, p50=null, p95=null` vĩnh viễn. Code đã ghi nhận là giới hạn (`metrics.py:148-154`) và trả
`null` thay vì bịa số — đúng — nhưng nó vẫn là một ô trống trên dashboard mà đáng lẽ có số:
`TraceCollector._on_tool_result` (`trace_collector.py:197-207`) chỉ cần đọc thêm một field, sau khi
`ivi_events` đưa `latency_ms` lên dây.

> **BE-05 (Trung bình) — `/traces/{id}` chặt hơn spec.**

`api_spec.md:63` ghi *"Driver for own turn; Engineer as scoped"*. Implementation là engineer-only
(`observability.py:43`, `:56`). Docstring đã thừa nhận phần "owner-scoped" chưa làm được vì
`TraceRecord` không mang `user_id` (`auth_deps.py:74-77`) — nhưng `TraceRecord` **có** `session_id`,
và `session_id → SessionRecord.user_id` là đúng cách mà `citation_routes.py` đã dùng để giải quyết
bài toán y hệt. Nên đây không phải giới hạn kỹ thuật, chỉ là chưa làm.

Lưu ý cặp đôi: BE-04 lỏng hơn spec, BE-05 chặt hơn spec — **cùng một bảng, lệch hai chiều ngược nhau**.

**BE-11 (Thấp)** — `engineer_stream` gọi `bus.set_sampler(...)` mỗi lần có kết nối
(`ws.py:359-367`), với closure `lambda: _engineer_health_payload(websocket)` giữ **socket của kết nối
mới nhất**. Sampler là dùng chung cho mọi kết nối (đúng, và lý do ghi ở `engineer_events.py:15-19`).
Nếu socket mới nhất đóng mà còn socket khác, sampler vẫn dựng payload từ `websocket.app.state` của
socket đã chết. Hiện vô hại vì chỉ đọc `app.state.mqtt` (không phụ thuộc socket), nhưng đó là một ràng
buộc ngầm: ai thêm một field lấy từ `websocket` vào payload sẽ tạo bug ngay. Nên lấy runtime từ một
nguồn không gắn socket.

### F12 — `/healthz`

Tám probe chạy song song, mỗi cái bọc `run_with_timeout` — điểm thắt duy nhất, fail-closed ở đó là đủ
cho cả endpoint (`health.py:63-76`). `llm` được miễn trừ khỏi gate `ready` nhưng **vẫn hiển thị** trong
`components`/`faults` (`health.py:42-49`) — đúng cách xử lý issue #48: không giấu trạng thái thật.

`probe_mqtt` publish QoS 1 thật và chờ PUBACK, thay vì đọc cờ `runtime.connected` vốn set một lần lúc
bind và không bao giờ tự clear (`health.py:88-108`). Topic thăm dò nằm dưới `commands/_health_probe`,
không khớp `Domain` nào nên simulator bỏ qua an toàn (`mqtt_topics.py:49-60`). Thiết kế chắc.

**BE-15 (Thấp)** — `probe_stt`/`probe_tts`/`probe_rag_index` có cache TTL, nhưng
`probe_mqtt`/`probe_sqlite` **không**. Mỗi lần `/healthz` bị poll = 1 publish QoS 1 lên broker + 1
`CREATE TABLE IF NOT EXISTS` / `INSERT` / `SELECT` / `DELETE` / `COMMIT` trên SQLite
(`db.py:24-44`). Cộng thêm sampler `/ws/engineer` bắn `health` mỗi 10 s, và healthcheck của
`docker-compose.yml`. Không nguy hiểm, nhưng "probe ghi vào DB" là thứ nên có TTL như ba probe kia.

### F13 — Giọng nói

`FasterWhisperEngine` và `PiperEngine` đều có `threading.Lock` vì cả hai thư viện không bảo đảm
thread-safe, mà `asyncio.to_thread` có thể chạy hai lượt song song (`voice.py:79-83`, `:164-166`).
`synthesize_speech` fail-open tuyệt đối, không bao giờ raise (`ivi_events.py:284-298`), và TTS chạy
nền ở nhánh reject của approval để không kéo chậm thao tác từ chối (`approvals.py:174-179`).

Lớp `voice_correction` có `PROTECTED_NUMERAL_WORDS` để Whisper viết số bằng chữ ("hai mươi bốn độ")
không bị "sửa" về từ vựng lệnh (`voice_correction.py:67-95`) — và chú thích giải thích rõ vì sao việc
loại chúng khỏi correction **không** phá tính held-out của bộ eval WER. Kỷ luật tốt.

### Các bề mặt ngoài 12 interface

> **BE-02 (Cao) — `POST /api/v1/chat`.**

`include_in_schema=False` chỉ giấu khỏi `/docs`; route vẫn nhận request. Không auth, không giới hạn
môi trường (khác `/agent/process`, xem BE-03). Nghiêm trọng hơn: graph của nó dựng qua
`build_graph(get_vehicle_gateway())` **không truyền `approvals`** (`routes.py:35`), nên theo
`graph.py:268-277` node `approval` không tồn tại và S2 dừng ở `approval_required` → compose. Đó là
fail-closed nên S2 an toàn — nhưng **S1 vẫn thực thi thẳng lên chính chiếc xe mà mọi endpoint khác
đang dùng** (một gateway toàn cục, ADR-013). Tức đây là một đường điều khiển actuator không xác thực,
không có trong hợp đồng, và không ai theo dõi.

**BE-12 (Thấp)** đi kèm: `_agent` là biến module cache lười (`routes.py:29-36`) và
`reset_vehicle_gateway()` **không** dọn nó. Sau khi cổng xe bị thay (lifespan restart, hoặc giữa các
test), `/chat` vẫn nói chuyện với gateway cũ. `tests/conftest.py:98-113` reset gateway nhưng không
reset `_agent`.

> **BE-03 (Cao) — `POST /api/v1/agent/process`.**

Không auth. Chỉ chặn bằng `if get_settings().app_env == "production"` (`agent_routes.py:102`), mà
mặc định của `app_env` là `"development"` (`config.py:18`) — nên trên mọi máy chưa đặt biến môi
trường, route mở. Nó còn nhận `vehicle_speed_kmh` từ client và gọi
`get_vehicle(session_id, speed)` → `gateway.set_motion(...)` (`session_state.py:96-100`), tức
**client tự đặt điều kiện phân loại S2/S3**. Ở chế độ MQTT thì gateway không phải `MotionInjectable`
nên raise `RuntimeError` → HTTP 500 (một lỗi 500 có thể gọi được từ bên ngoài).

Route được tài liệu hoá là dev-only và `CLAUDE.md` nói rõ nó load-bearing cho test suite, nên **không
đề xuất xoá ngay**. Đề xuất: đổi cổng chặn từ `app_env == "production"` sang một cờ opt-in tường minh
(`DEV_ROUTES_ENABLED`, mặc định `False`), và thêm `Depends(require_driver)`.

**BE-18 (Thấp) — ba chỗ tài liệu mô tả sai hiện trạng:**

| Nơi | Ghi | Thực tế |
|---|---|---|
| `CLAUDE.md` | *"`require_engineer` does not exist, so `_require_engineer` … is a deliberately named no-op"* | Đã tồn tại (`auth_deps.py:67`) và cả hai route observability đều dùng (`observability.py:43`) |
| `CLAUDE.md` | *"both WebSockets … ignoring the `bearer.<token>` value"* | Cả hai đã xác thực bearer + role + Origin trước `accept()` (`ws.py:135-165`) |
| `api/observability.py:11-12` | *"`src/api/approvals.py` hiện còn dùng `HTTPException`"* | `approvals.py` đã dùng `ApiError` toàn bộ |

Docstring sai về an toàn nguy hiểm hơn docstring sai về chức năng: người đọc sau sẽ đi "vá" một lỗ
hổng đã đóng, hoặc tệ hơn, tin rằng một lỗ hổng khác cũng đã đóng theo.

## 5. Kịch bản đời thực

Mười hai tình huống cụ thể. Mỗi cái đều dựng được trên máy demo hôm nay, trừ hai cái ghi rõ là
"chưa gặp được vì FE chưa có mic/cursor" — chúng sẽ xuất hiện đúng lúc FE hoàn thiện, tức đúng lúc
không ai muốn gặp thêm bug mới.

### KB-1 — Người ngồi cuối phòng bật điều hòa xe của bạn (BE-02, BE-03, BE-01)

`app_host` mặc định là `0.0.0.0` (`config.py:20`), nên `python -m src.serve` mở cổng 8000 ra cả mạng
LAN phòng lab. Bất kỳ ai cùng Wi-Fi:

```bash
curl -X POST "http://192.168.1.20:8000/api/v1/chat" \
     -H "Content-Type: application/json" \
     -d '{"message":"Bật điều hòa lên 30 độ"}'
```

Không token, không header gì. Điều hòa trên màn chiếu nhảy lên 30 độ giữa lúc thuyết trình. Không
dòng log nào nói ai vừa làm — `/chat` không đi qua `IviEventBus` nên `TraceCollector` cũng không thấy.

Biến thể khó chịu hơn với `/agent/process`, vì nó nhận `vehicle_speed_kmh`:

```bash
curl -X POST "http://192.168.1.20:8000/api/v1/agent/process" \
     -H "Content-Type: application/json" \
     -d '{"query":"Mở cửa bên lái","vehicle_speed_kmh":0}'
```

Xe đang đứng yên → S2 → `interrupt()` → **modal xác nhận hiện lên màn hình tài xế** trong khi tài xế
không nói gì. Đổi thành `"vehicle_speed_kmh": 60` thì cùng câu đó ra S3 → blocked. Tức người ngoài
quyết định được lượt của người trong là S2 hay S3 — họ điều khiển chính cái predicate mà
`docs/safety_and_hitl.md` dựng ra để bảo vệ.

### KB-2 — Tài xế bấm "Đồng ý", không có gì xảy ra, và người debug đi sai hướng (BE-01)

Xảy ra bất cứ khi nào `session_id` không đến từ `POST /sessions`: script test tay, Postman collection
gõ `ses-demo`, hoặc một FE tương lai cache lại session cũ sau khi backend restart (store in-memory,
session đã mất).

1. `POST /turns/voice?session_id=ses-demo` → **202 Accepted**. Trông hoàn toàn bình thường.
2. `/ws/ivi` bắn `plan.ready` → `approval.required` → modal HITL hiện, đếm ngược 30 s.
3. Tài xế bấm Đồng ý → `POST /approvals/appr-8f2c.../decision`.
4. **403 `FORBIDDEN` — "approval không tồn tại hoặc không thuộc về bạn"**, dù approval vừa sinh ra
   cho đúng phiên đó, một giây trước.
5. Modal treo. Sau 30 s bản ghi tự `expired` khi có ai đọc, nhưng graph **chưa bao giờ resume** nên
   không có `turn.canceled` nào được phát. Màn hình tài xế đứng im ở `waiting_approval` vĩnh viễn.

Người debug sẽ mở `agents/nodes/approval.py` và `agents/approval.py` — hai file **hoàn toàn đúng** —
rồi mất một buổi. Nguyên nhân nằm ở `turns.py:135`: `get_graph(session_id)` tự sinh state cho một
session chưa từng được `create_session()`, nên `get_session_record()` trả `None` và cổng quyền ở
`approvals.py:102` từ chối đúng theo thiết kế của nó.

### KB-3 — Wi-Fi chập chờn làm nhảy hai bài hát (BE-01)

`/turns/text` có `Idempotency-Key` nên retry chỉ trả lại envelope cũ. `/turns/voice` **không có**, và
sự khác biệt quan sát được ngay:

Tài xế nói "chuyển bài tiếp theo". Backend nhận đủ audio và bắt đầu chạy; `fetch` phía FE timeout;
FE gửi lại.

- Lượt 1 chạy `media_control{action:"next"}` → track đổi → `changed=True` → `state_version` **tăng**.
- Lượt 2 chạy `normalize_node` lại → chụp snapshot **mới** → `state_version` mới → `plan_id` (hash có
  `vehicle_state_version`) **khác** → không trúng cache idempotency nào ở cả ba tầng → **chạy thật
  lần hai**.

Kết quả: nhảy hai bài. Với "tăng âm lượng lên 80" thì vô hại vì đặt lại cùng giá trị là no-op; với
mọi lệnh **tương đối** (`next`, `previous`) thì sai. Ba tầng chống thực thi kép ở §4/F9 không cứu được
ca này — chúng chống *duplicate delivery của cùng một lệnh*, còn đây là *hai lệnh khác nhau về mặt
dữ liệu*. Đúng thứ mà `Idempotency-Key` sinh ra để chặn, và đúng thứ route này đang thiếu.

### KB-4 — Firefox gửi giọng nói được, Chrome thì không, và cả hai đều sai (BE-13)

Chưa gặp được hôm nay vì FE chưa có `MediaRecorder` (`p0_gap_audit` Tier 1). Xuất hiện ngay ngày nối mic:

| Trình duyệt | `blob.type` mặc định | Route trả | Tài xế thấy |
|---|---|---|---|
| Chrome / Edge | `audio/webm;codecs=opus` | **422** ngay | "Content-Type không hỗ trợ" — sai nhưng rõ |
| Firefox | `audio/ogg;codecs=opus` | **202** rồi hỏng | "Không nhận dạng được giọng nói" (`STT_FAILED`) |

Trình duyệt **được** allowlist cho trải nghiệm tệ hơn trình duyệt bị từ chối: tài xế Firefox sẽ đi
kiểm tra micro, đổi chỗ ngồi, nói to hơn — trong khi vấn đề là `voice._validate_audio` gọi
`wave.open()` trên một file Ogg (`voice.py:111`). Không ai muốn debug ca này lúc 11 giờ đêm trước
ngày demo.

### KB-5 — Hai máy demo song song, một trace biến mất (BE-09)

`api_spec.md:382` in ví dụ `X-Trace-Id: tr_client_login_001` và `tr_client_voice_001`. Chuỗi ví dụ
trong spec là thứ **người ta copy nguyên vào Postman collection**, rồi collection đó được chia cho cả
nhóm.

- Máy A gửi lượt 1 với `X-Trace-Id: tr_client_voice_001` → `TraceStore.open()` tạo bản ghi.
- Máy A gửi lượt 2 với **cùng** chuỗi → `turn_id` khác → `trace_store.py:182` ghi một dòng
  `logger.warning` rồi **thay** bản ghi cũ. Lượt 1 biến mất khỏi `/metrics/summary` và khỏi
  `/traces/{id}`.
- Máy B cũng dùng collection đó → ghi đè tiếp lên trace của máy A.

Kỹ sư mở dashboard thấy `turns.accepted` thấp hơn số lượt thật, và `GET /traces/tr_client_voice_001`
trả về đúng một bản ghi — bản ghi của người cuối cùng bấm. Không lộ dữ liệu (đọc trace là
engineer-only), nhưng **bằng chứng vận hành của người khác bị xoá mà chỉ cần đoán trúng một chuỗi
in sẵn trong spec**.

### KB-6 — "Lệnh này chạy trên chiếc xe nào?" (BE-06)

Sau demo, xuất `GET /traces/{id}` làm bằng chứng. Trong đó:

```json
"action_plan": { "vehicle_id": "veh-demo", "plan_id": "plan-3f9a...", ... }
```

Trong `docker compose logs vehicle-simulator` cùng thời điểm:

```
Xe ảo vehicle-demo-01 sẵn sàng
```

Hai id, một chiếc xe. Đường nối duy nhất là dấu thời gian. Nếu người chấm hỏi "chứng minh plan này
tác động lên đúng chiếc xe trong log", câu trả lời hiện tại là "vì chỉ có một chiếc xe" — đúng, nhưng
đó là lập luận về kiến trúc, không phải bằng chứng từ dữ liệu.

Biến thể khó chịu hơn ở `/turns/text`: `vehicle_id` là chuỗi client tự khai lúc `POST /sessions` và
**không được validate**. Gõ `{"vehicle_id": "vf9-cua-toi"}` thì plan ghi `vf9-cua-toi`, chuỗi đó đi
vào `canonical_json` và được ký vào `plan_digest` (`policy.py:88-95`) — tức nó là **một phần định
danh của approval** — trong khi lệnh vẫn chạy trên `vehicle-demo-01`.

### KB-7 — Cột "nhóm thực thi" trên dashboard luôn trống (BE-07)

"Bật điều hòa lên 25 độ" sinh **hai** step (`set_hvac_power` + `set_hvac_temperature`,
`router.py:246-252`). Chúng vẫn nối được với nhau qua `plan_id`, có mặt cả trong `CommandEvent`
(`models/vehicle.py:198`) — nên hôm nay chưa mất gì.

Cái mất là ô kế bên: `GET /traces/{id}` → `admission.execution_group_id: null` với **mọi** lượt, và
nó sẽ mãi là `null` cho tới khi có ai đó gán. Vấn đề thật sẽ đến khi làm bundled approval theo
`safety_and_hitl.md` — một lần "Đồng ý" cấp phép cho **nhiều plan**. Lúc đó `plan_id` không còn gom
được nữa, và trường duy nhất sinh ra để gom thì đã ship sẵn ở trạng thái không ai ghi. Sửa bây giờ
là một dòng ở `execute_node`; sửa lúc đó là sửa cả một tính năng đang chạy.

### KB-8 — Báo cáo latency thiếu đúng con số cần (BE-08)

Sau 40 lượt điều khiển trong buổi demo, `/metrics/summary` trả:

```json
"mqtt": { "publish_attempts": 40, "published": 38, "errors": 2,
          "error_rate": 0.05,
          "latency_ms": { "count": 0, "p50": null, "p95": null } }
```

Ba con số đầu đúng và có ích. Ô thứ tư trống — đúng (không bịa số), nhưng khi cần chứng minh mục tiêu
p50/p95 của `product_brief.md` thì con số duy nhất có là `stage_latency_ms.tool`, và nó là **tổng cả
bước thực thi kể cả chờ ack**. Không tách được "backend chậm" khỏi "broker chậm" — mà đó chính là câu
hỏi mà ADR-004 chọn MQTT để trả lời được.

### KB-9 — Tài xế bị đăng xuất giữa lượt vì người khác đăng nhập (BE-14)

Demo cho cả lớp, mỗi người mở FE trên máy mình. FE hiện không lưu token qua reload, nên mỗi lần
`F5` là một `POST /auth/login` mới. `MAX_TOKENS = 256` đuổi theo LRU (`auth.py:83-84`), nên lần đăng
nhập thứ 257 **đá token cũ nhất ra khỏi kho**.

Người demo chính đăng nhập đầu tiên, đang ở giữa một lượt S2 chờ xác nhận. Ai đó ở cuối phòng reload
lần thứ 257. `POST /approvals/.../decision` của người demo trả **401 `AUTH_REQUIRED`**, FE đá về
`/login`. Không log nào nói vì sao, và thử lại thì hoạt động bình thường (đăng nhập lại là có token
mới) — tức một lỗi không tái lập được theo yêu cầu, đúng loại tệ nhất.

### KB-10 — Kỹ sư bảo tài xế "gửi tôi trace id đi" (BE-05)

Tài xế gặp một lượt lạ, có `trace_id` hiển thị trên UI. Tự mở `GET /api/v1/traces/tr_9a3f...` bằng
token của mình → **403 `FORBIDDEN` — "yêu cầu vai trò 'engineer'"**. Phải nhờ người có tài khoản
engineer đọc hộ.

`api_spec.md:63` chốt vai trò là *"Driver for own turn; Engineer as scoped"*, nên đây là lệch spec
theo hướng **chặt hơn**. Và nó không phải giới hạn kỹ thuật: `TraceRecord` có `session_id`, còn
`session_id → SessionRecord.user_id` đúng là cách `citation_routes.py:71-83` đã dùng để giải bài toán
y hệt cho citation.

### KB-11 — Màn hình chờ ở sảnh đọc được trạng thái cửa xe (BE-04)

```bash
curl http://192.168.1.20:8000/api/v1/vehicle/state
```

Không token, trả đủ `doors`, `windows`, `motion.speed_kph`, `navigation.destination_id`. Ở simulator
thì vô hại. Điều đáng ghi là hệ quả lập luận: đây là interface **số 6 trong 12 interface P0**, nên
bất kỳ ai dùng bảng 12-interface để nói "backend đã có auth" đều đang nói sai về một phần mười hai
bề mặt.

### KB-12 — Máy ngủ 35 phút, mở lại báo "mất kết nối" hai lần (BE-16)

Chưa gặp được hôm nay vì FE không bao giờ gửi cursor. Xuất hiện ngay khi làm xong Tier 2 của
`p0_gap_audit`:

Tài xế đóng nắp laptop giữa buổi. 35 phút sau mở lại. `_BUFFER_TTL_SECONDS = 1800` đã dọn buffer
nhưng **giữ** `sequence` (`ivi_events.py:63-72`). FE reconnect kèm `last_sequence` trỏ đúng event
cuối cùng nó đã nhận:

- `earliest = stream.sequence + 1` (buffer rỗng), `last_sequence < earliest` → **`REPLAY_WINDOW_EXPIRED`**
  + đóng `1003`.
- FE thấy lỗi, kết nối lại lần hai không cursor → thành công.

Người dùng thấy "mất kết nối" rồi "kết nối lại" hai nhịp liên tiếp, dù **không có một event nào bị bỏ
lỡ** — cursor của họ hoàn toàn hợp lệ, chỉ là không còn gì để replay. Fail an toàn, nhưng nó biến một
ca hoàn toàn bình thường thành một lỗi hiển thị.

### Bảng tra ngược

| Kịch bản | Phát hiện | Dựng được hôm nay? |
|---|---|---|
| KB-1 người ngoài bật điều hòa | BE-01, BE-02, BE-03 | Có |
| KB-2 bấm Đồng ý không có gì xảy ra | BE-01 | Có |
| KB-3 nhảy hai bài hát | BE-01 | Có |
| KB-4 Firefox vs Chrome | BE-13 | Chưa — cần FE có mic |
| KB-5 trace bị ghi đè | BE-09 | Có |
| KB-6 lệnh chạy trên xe nào | BE-06 | Có |
| KB-7 cột nhóm thực thi trống | BE-07 | Có |
| KB-8 báo cáo latency thiếu số | BE-08 | Có |
| KB-9 đăng xuất giữa lượt | BE-14 | Có (cần 256 lần login) |
| KB-10 tài xế không đọc được trace của mình | BE-05 | Có |
| KB-11 đọc state không cần token | BE-04 | Có |
| KB-12 reconnect báo lỗi giả | BE-16 | Chưa — cần FE gửi cursor |

## 6. Đánh giá chức năng

Năm mục trên soi **tính đúng đắn của luồng**: request đi đúng đường chưa, quyền có đủ chưa, dữ liệu
vận hành có trung thực không. Mục này soi một câu hỏi khác: **hệ thống làm được việc gì, và làm tốt
tới đâu.**

Câu hỏi đó có hai trục, và trục thứ nhất đã có chủ sở hữu.

### 6.1 Bao phủ — `docs/coverage_matrix.md` đã trả lời, và nó đúng

Tôi đối chiếu lại từng con số then chốt của tài liệu đó với code, không lấy lại từ tài liệu:

| Khẳng định của `coverage_matrix.md` | Đối chiếu code | Khớp? |
|---|---|:--:|
| 11 tool trong registry (3× S0, 5× S1, 3× S2) | `tool_registry._SPECS` | ✅ |
| 8 actuator tool lên dây | `ACTUATOR_TOOLS` = spec có `domain` | ✅ |
| 7 domain, `motion` read-only | `models/vehicle.py:18-31` | ✅ |
| 6 matcher trong router | `_run_matchers` (`router.py:180-187`) | ✅ |
| Navigation hard-code đúng 3 đích | `router.py:374-381` | ✅ |
| `media_control` có `previous` nhưng router không map | enum ở `tools/media.py:13`; không luật nào | ✅ |
| Ghế chỉ 2 ghế trước | `FrontSeatKey` (`models/vehicle.py:34`) | ✅ |
| `fan_level` read-only | có trong `HvacState`, không tool nào đổi | ✅ |
| **5/11 nhóm lệnh thoại có điều khiển, 6/11 bằng 0** | — | ✅ |

Không có gì để bổ sung ở trục này, và cảnh báo quan trọng nhất của tài liệu đó cũng đúng: vì ADR-011
mặc định rơi xuống tra sổ tay, hệ thống **trả lời được** rất nhiều thứ nó **làm không được**. Demo sẽ
trông như nó hiểu đèn sương mù và Camp Mode; nó đang đọc 482 chunk sổ tay VF9.

### 6.2 Chất lượng hành vi *trong* phần đã phủ — 6 phát hiện

Đây là trục `coverage_matrix.md` không đụng tới. Đánh mã **FN** để không lẫn với chuỗi **BE** ở §3:
BE là lỗi luồng/quyền/dữ liệu vận hành, FN là lỗi hành vi mà người dùng cuối cảm nhận được.

| ID | Mức | Tóm tắt |
|---|---|---|
| FN-01 | **Cao** | Router chẩn đoán chính xác 19 lý do khác nhau; composer gộp hết vào 2 câu |
| FN-02 | Trung bình | Không hỏi được xe về chính nó — `vehicle_state_query` và `get_vehicle_state` không tới được bằng lời |
| FN-03 | Trung bình | Ghế sau: router sinh plan, validator chặn, tài xế nghe "yêu cầu không hợp lệ" |
| FN-04 | Trung bình | Chào hỏi bị trả lời bằng từ chối tra cứu sổ tay |
| FN-05 | Trung bình | Số thập phân bị cắt im lặng (`22,5 độ` → `22`) |
| FN-06 | Thấp | Lệch tên tool ba chiều `search_nearby` / `search_nearby_poi` / `TOOL_ARGS` (đang ngủ đông) |

#### FN-01 — Router chẩn đoán chính xác, composer vứt hết đi

`route_node` ghi `route_reason` vào state (`nodes/route.py:16`). Grep toàn `src/`: nó được đọc **đúng
một chỗ** — `graph.py:202`, để quyết có thử SLM không. `compose_node` khoá message **chỉ theo
`outcome`** (`compose.py:149`), nên mọi lý do biến mất ở bước cuối cùng:

| Outcome | Số lý do router tính ra | Câu tài xế nghe |
|---|:-:|---|
| `clarify` | **11** — `missing_temperature`, `missing_volume`, `missing_window_side`, `missing_window_position`, `missing_seat_side`, `missing_seat_level`, `missing_seat_value`, `missing_door_side`, `unknown_local_destination`, `ambiguous_reference`, `ambiguous_number` | "Bạn muốn điều chỉnh cụ thể như thế nào?" |
| `denied` | **8** — `temperature_out_of_range`, `volume_out_of_range`, `window_position_out_of_range`, `seat_level_out_of_range`, `seat_value_out_of_range`, `poi_not_in_fixture`, `negated_command`, `unsupported_actuator` | "Xin lỗi, tôi không thực hiện được yêu cầu này." |
| `validation_denied` | 3 subcode + thông điệp chi tiết đã nằm sẵn trong `state["error"]` | "Yêu cầu không hợp lệ nên tôi chưa thực hiện." |

**19 chẩn đoán riêng biệt gộp thành 2 câu.** Vài cặp cụ thể:

| Tài xế nói | Router biết | Tài xế nghe |
|---|---|---|
| "Đặt điều hòa 40 độ" | `temperature_out_of_range` — dải là 16–30 | "Xin lỗi, tôi không thực hiện được yêu cầu này." |
| "Tắt phanh tay" | `unsupported_actuator` — xe ảo không có phanh tay | *cùng một câu* |
| "Mở cửa sổ bên lái" | `missing_window_position` — thiếu phần trăm | "Bạn muốn điều chỉnh cụ thể như thế nào?" |
| "Đặt nhiệt độ" | `missing_temperature` — thiếu số độ | *cùng một câu* |
| "Dẫn đường tới Hồ Gươm" | `unknown_local_destination` — chỉ có 3 POI cố định | *cùng một câu* |

Đây **không phải thiếu tính năng**. Thông tin đã có sẵn trong state, đúng lúc, đúng chỗ, đã được tính
toán cẩn thận bởi một router mà §4/F5 khen là chất lượng hiếm. Nó bị bỏ ở dòng cuối cùng của pipeline.

Sửa là một `dict` keyed theo `route_reason`, fallback về câu hiện tại khi không có khoá. Đổi lại:
toàn bộ nhóm tương tác thất bại — nhóm chiếm phần lớn số lượt trong một buổi demo có người lạ thử
máy — từ vô dụng thành dùng được. Đây là **tỉ lệ giá trị trên công sức cao nhất trong cả báo cáo
này**, kể cả so với nhóm bảo mật ở §9.

#### FN-02 — Không hỏi được xe về chính nó

`vehicle_state_query` nằm trong enum `Intent` (`contracts.py:38`). `get_vehicle_state` nằm trong
registry (S0, `tool_registry.py:113`) **và** trong `TOOL_ARGS` (`agents/tools/__init__.py:30`).
Không matcher nào sinh ra chúng — cả hai là bề mặt chết.

Đường đi thật của "Điều hòa đang mấy độ?":

1. `is_information_question` → False (`mấy độ` không nằm trong `HOW_WHAT_MARKERS`).
2. `is_question` → True (kết thúc bằng `?`).
3. `_run_matchers` → `_match_hvac` thấy `"điều hòa"` nhưng `_starts_with_command` thất bại (câu mở đầu
   bằng `điều`, không phải động từ điều khiển) → mọi matcher trả `None`.
4. → `not_control` / `manual_query` / `manual_question` → **RAG tra sổ tay VF9** → gần chắc chắn từ chối.

Trạng thái xe chỉ đọc được qua `GET /api/v1/vehicle/state`, tức qua màn hình, không qua giọng nói. Với
một sản phẩm tự gọi là *cabin copilot* voice-first, đây là câu hỏi tự nhiên bậc nhất mà nó không trả
lời được — và khác với nhóm "đèn" hay "cruise control", ở đây **dữ liệu đã có sẵn trong tay**, chỉ
thiếu một matcher và một nhánh compose đọc `vehicle_snapshot`.

#### FN-03 — Ghế sau: router sinh plan, validator chặn, tài xế nghe câu vô nghĩa

`_side()` nhận `"sau bên trái"` → `rear_left` (`router.py:397-400`). `_match_seat_heating` không kiểm
ghế trước/sau, nên nó sinh candidate plan bình thường. Rồi:

```
"Bật sưởi ghế sau bên trái mức 2"
  → control / seat_heating / {seat: "rear_left", level: 2}
  → validate_node → SetSeatHeatingArgs.seat: FrontSeatKey → ValidationDenied("args_invalid")
  → "Yêu cầu không hợp lệ nên tôi chưa thực hiện."
```

Sự thật là **xe chỉ có sưởi cho hai ghế trước**. Câu trả lời đúng nằm trong tầm tay của hệ thống; nó
thay vào đó nói một câu nghe như tài xế vừa nói sai ngữ pháp. Cùng hình dạng với FN-01: dữ kiện đủ,
diễn đạt sai.

Chỗ sửa đúng là router — chặn ghế sau ngay tại matcher với một `reason` riêng
(`seat_rear_not_equipped`), thay vì để nó rơi xuống validator vốn không biết gì về sản phẩm.

#### FN-04 — Chào hỏi bị trả lời bằng từ chối tra cứu

Với cấu hình mặc định (`slm_enabled=False`), nhánh `chitchat` không tồn tại — nó chỉ có ở `slm_stage`
(`graph.py:229-231`). Nên "Xin chào":

1. Không phải câu hỏi thông tin, không kết thúc bằng `?`, token cuối không phải `không` → không phải câu hỏi.
2. Không phủ định, không nằm trong `_AMBIGUOUS_TEXTS`, không matcher nào khớp.
3. `_looks_imperative` → False (`xin` không thuộc `_COMMAND_VERBS`).
4. → `default_to_manual` → RAG → **"Tôi không tìm thấy thông tin này trong sổ tay xe."**

Đây là câu đầu tiên mà bất kỳ ai ngồi vào ghế demo cũng thử. Không cần bật SLM để sửa: một bảng chào
hỏi tất định vài dòng, đặt trước `default_to_manual`, giải quyết xong — và giữ nguyên nguyên tắc
"không gọi model cho lệnh P0 rõ ràng" của ADR-006.

#### FN-05 — Số thập phân bị cắt im lặng

`normalize_vi` biến `.` và `,` thành khoảng trắng (`re.sub(r"[^\w%]+", " ", ...)`, `router.py:107`).
Nên:

```
"đặt điều hòa 22,5 độ"  →  "đặt điều hòa 22 5 độ"
_NUMBER_PATTERN.search(...)  →  match ĐẦU TIÊN  →  22
```

Điều hòa được đặt ở **22 độ**, không cảnh báo gì. `_reject_ambiguous_number` không chặn được vì nó
thoát sớm ngay khi thấy chữ số (`router.py:210`) — guard đó sinh ra cho *từ số viết chữ*, không cho
trường hợp này. Và `HvacState.temperature_c` là `float`, tức tầng dưới hoàn toàn nhận được 22.5.

Đúng lớp lỗi **KI-001 — "tuân thủ một phần trong im lặng"** mà chính file `router.py` chống rất kỹ ở
ba chỗ khác (`_reject_ambiguous_number`, đọc trăm+chục cùng lượt, bỏ tiểu từ `không` cuối câu). Nửa
độ là yêu cầu bình thường trong xe; đây là dư lượng cuối cùng của lớp lỗi đó.

#### FN-06 — Lệch tên tool ba chiều (đang ngủ đông)

| Nơi | Tên tool |
|---|---|
| `services/tool_registry.py:115` | `search_nearby_poi` |
| `agents/tools/__init__.py` — `TOOL_ARGS` | **không có** |
| `agents/slm.py:59` — `UNION_SCHEMA` enum | `search_nearby` |

Prompt few-shot của SLM quảng cáo với model một tool **không tồn tại ở bất kỳ đâu**. Nếu bật
`slm_enabled` và model đề xuất nó: `parse_candidate` → `validate_args("search_nearby")` →
`ValidationDenied` → `SlmSchemaError` → sửa đúng một lần → `clarify`. Fail-closed đúng, nhưng đốt trọn
cơ hội fallback cho một lỗi cấu hình chứ không phải một câu khó.

Ghi thêm cùng chỗ: `query_manual` và `search_nearby_poi` có trong registry nhưng **không** trong
`TOOL_ARGS`, mà `materialize_action_plan` chặn theo `TOOL_ARGS` (`policy.py:72-74`). Nên chúng không
chỉ "chưa có executor" — chúng **không thể xuất hiện trong một `ActionPlan`**, kể cả plan viết tay.
`coverage_matrix.md` mô tả `search_nearby_poi` là "chỉ một dòng trong registry"; chính xác hơn là nó
bị chặn ở hai tầng.

### 6.3 Kết luận chức năng — ba mức, không gộp

**1. Chất lượng thật, dùng được.** HITL (5 cổng fail-closed, CAS, single-use, sẵn sàng cho bundled),
RAG grounded (chấm 2 tín hiệu, trích nguyên văn có báo cắt), tầng thực thi MQTT (3 lớp dedupe +
optimistic concurrency), quan sát (một kho ba khung nhìn, redaction bằng cấu trúc). Bốn mảng này viết
ở mức nghiêm túc hơn hẳn mặt bằng một đồ án.

**2. Đúng nhưng hẹp.** Bề mặt điều khiển: 8 tool, 5/11 nhóm, 3 POI cứng, chỉ một luật sinh plan hai
bước. Đây là **phạm vi đã chốt** có ADR chống lưng (ADR-010, ADR-011), không phải nợ kỹ thuật. Đừng
báo cáo nó như thiếu sót, và cũng đừng báo cáo nó như "hỗ trợ N lệnh".

**3. Chỗ yếu thật sự là tầng nói chuyện, không phải tầng làm việc.** FN-01 đến FN-04 cùng một hình
dạng: **hệ thống biết chính xác chuyện gì đang xảy ra và nói ra một câu chung chung.** Với sản phẩm
voice-first thì đó là lỗi chức năng chứ không phải lỗi trình bày. Và nó rẻ nhất trong toàn bộ báo cáo
này để sửa — FN-01 là một bảng tra, FN-02 là một matcher cộng một nhánh compose, FN-03 là một luật
kiểm sớm, FN-04 là vài dòng chào hỏi tất định.

Nói gọn: **backend làm đúng những việc nó nhận làm; nó chỉ chưa biết nói cho tài xế nghe điều nó vừa
làm hoặc vừa từ chối.**

## 7. Ma trận tuân thủ `api_spec.md` (12 interface)

`A` = auth, `V` = `X-Schema-Version`, `I` = `Idempotency-Key`. `—` = spec không yêu cầu.

| # | Interface | A | V | I | Ghi chú |
|---:|---|:--:|:--:|:--:|---|
| 1 | `POST /auth/login` | — | ✅ | — | ngoại lệ `version=1.0` trong Content-Type có xử lý |
| 2 | `POST /sessions` | ✅ | ✅ | ✅ | đầy đủ |
| 3 | `POST /turns/text` | ✅ | ✅ | ✅ | đầy đủ + kiểm ownership |
| 4 | `POST /turns/voice` | ❌ | ❌ | ❌ | **BE-01** |
| 5 | `POST /approvals/{id}/decision` | ✅ | ✅ | ✅ | đầy đủ + ownership |
| 6 | `GET /vehicle/state` | ❌ | — | — | **BE-04** |
| 7 | `GET /citations/{id}` | ✅ | — | — | driver + ownership qua session |
| 8 | `GET /traces/{id}` | ⚠️ | — | — | **BE-05** — engineer-only, thiếu nhánh driver-own-turn |
| 9 | `GET /metrics/summary` | ✅ | — | — | engineer-only, đúng |
| 10 | `GET /healthz` | — | — | — | probe cục bộ |
| 11 | `WS /ws/ivi` | ✅ | — | — | 4/4 điều kiện (subprotocol, bearer, role, Origin, ownership) |
| 12 | `WS /ws/engineer` | ✅ | — | — | 4/4 (không có ownership vì không có session) |

Ngoài bảng: `POST /chat` (**BE-02**), `POST /agent/process` (**BE-03**), `GET /status`
(liveness cho Docker, vô hại).

## 8. Những chỗ backend làm đúng và nên giữ nguyên

Liệt kê để không ai "dọn dẹp" nhầm — nhiều đoạn dưới đây trông thừa nhưng là bản sửa của một lỗi thật:

1. **Ranh giới plan hai chiều** mã hoá bằng Pydantic validator, không bằng quy ước
   (`contracts.py:99-127`).
2. **Fail-closed nhất quán** ở năm chỗ độc lập: `safety_node` khi snapshot rỗng; năm cổng của
   `request_approval_node`; `lifespan` gắn `MqttVehicleGateway` **kể cả khi `start()` hỏng**
   (`main.py:88-92`) thay vì rơi về in-process; `/vehicle/state` từ chối thay vì trả state cũ;
   `probe_*` map mọi exception thành `down`.
3. **Redaction bằng cấu trúc**: `TraceRecord` không có field text, nên không rò được kể cả khi ai đó
   thêm handler ẩu.
4. **Idempotency đúng**: `begin`/`finish`/`abandon` trong một `asyncio.Lock`, có TTL 60 s chống chỗ
   đặt bỏ hoang, và `abandon` được gọi cả trên đường `CancelledError`.
5. **`_wire_tool_status`** không bao giờ để `skipped`/`rejected` thô lọt ra hợp đồng dây
   (`ivi_events.py:200-220`).
6. **`BoundedCache` ở mọi bảng idempotency** — không có dict phình vô hạn nào trong `src/`.
7. **Bốn `reason` phân biệt được** cho readiness (`vehicle_state.py:30-38`), vì bốn nguyên nhân đó
   đòi bốn hành động khác nhau từ người vận hành.
8. **Chú thích giải thích lỗi cụ thể đã từng xảy ra**, không phải chú thích mô tả lại code. Đây là
   tài sản thật của repo — `router._number`, `metrics.window_bounds`, `ws.py` flush loop,
   `vehicle_state._forget_state_of_previous_run` đều thuộc loại này.

Giới hạn **đã có ADR/issue chống lưng, không tính là phát hiện**: không persistence (approvals /
sessions / tokens / traces đều in-memory), `slm_enabled=False` mặc định, `search_nearby_poi` chỉ là
entry registry (chính xác hơn: bị chặn ở hai tầng — xem FN-06), 3/16 event driver chưa phát (`ui.policy`, `transcript.partial`,
`approval.intent.detected`), `/ws/engineer` không replay.

## 9. Đề xuất ưu tiên

Hai chuỗi mã trộn chung ở đây có chủ đích: xếp theo **giá trị trên công sức**, không theo loại lỗi.
Nhóm 0 đứng đầu vì nó là thứ duy nhất người xem demo nhìn thấy trực tiếp, và rẻ hơn mọi nhóm còn lại.

**Nhóm 0 — cho hệ thống nói ra điều nó đã biết** (nửa ngày cho cả bốn, không đụng bất biến nào):

1. FN-01: bảng tra `route_reason → câu trả lời`, fallback về câu hiện tại. 19 chẩn đoán đang gộp
   thành 2 câu; đây là tỉ lệ giá trị/công sức cao nhất trong cả báo cáo.
2. FN-03: chặn ghế sau ngay tại matcher với `reason` riêng, thay vì để validator từ chối bằng câu
   "yêu cầu không hợp lệ".
3. FN-04: bảng chào hỏi tất định đặt trước `default_to_manual` — không cần bật SLM, giữ nguyên ADR-006.
4. FN-02: matcher cho `vehicle_state_query` + một nhánh compose đọc `vehicle_snapshot`. Dữ liệu đã có
   sẵn; hiện chỉ đọc được qua màn hình, không qua giọng nói.

**Nhóm 1 — đóng bề mặt thực thi không xác thực** (ước lượng nửa ngày, không đụng kiến trúc):

1. BE-01: thêm 3 dependency + kiểm ownership vào `/turns/voice`. Đóng luôn hệ quả approval-403 và
   citation-404.
2. BE-03: đổi cổng chặn `/agent/process` sang cờ opt-in tường minh + thêm `require_driver`.
3. BE-02: thêm `require_driver` cho `/chat`, hoặc chặn nó bằng cùng cờ với `/agent/process`.
4. BE-04: thêm auth cho `GET /vehicle/state`.

**Nhóm 2 — trung thực của dữ liệu vận hành** (mỗi mục ~1 h):

5. BE-09: khoá `TraceStore` bằng id server sinh; giữ `X-Trace-Id` client làm field tương quan.
6. BE-07: truyền `execution_group_id` từ `execute_node`.
7. BE-06: lấy `vehicle_id` từ gateway ở `normalize_node`; `POST /sessions` từ chối id không khớp.
8. BE-08: đưa `latency_ms` lên payload `tool.result`, thu ở `_on_tool_result`.

**Nhóm 3 — nợ đã biết, cần quyết định chứ không chỉ cần code:**

9. BE-10: `trace_id` trên `ApprovalRecord` để `approval_wait_ms` có số (TASK-BE-OBS-001 Tier 3).
10. BE-05: quyết định `/traces/{id}` theo spec (thêm nhánh driver-own-turn qua `session_id`) hay sửa
    spec cho khớp implementation. Đang lệch thì phải chọn một.
11. BE-13: `audio/ogg` + `audio/pcm` — thực hiện, hoặc bỏ khỏi allowlist và khỏi spec.

**Nhóm 4 — dọn dẹp:** BE-11, BE-12, BE-14, BE-15, BE-16, BE-17, BE-18, FN-05 (đọc số thập phân),
FN-06 (thống nhất tên `search_nearby_poi` giữa registry / `TOOL_ARGS` / `UNION_SCHEMA` — làm **trước**
khi PR #71 bật `slm_enabled`, nếu không nó tỉnh dậy thành lỗi runtime).

**Việc cần làm ngay không thuộc nhóm nào**: cập nhật `CLAUDE.md` — con số suite (901/20/161 s) và ba
mô tả auth đã lỗi thời (BE-18).

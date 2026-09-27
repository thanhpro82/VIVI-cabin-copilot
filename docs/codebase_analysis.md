# Phân tích Codebase — VIVI Cabin Copilot / ai20k_agent_p192

> Ghi lại ngày 2026-08-06. Mục đích: đọc file này để nắm nhanh hiện trạng dự án, không cần quét lại toàn bộ repo.
> Đây là **snapshot tại thời điểm phân tích** — nếu code đã thay đổi nhiều, nên xác minh lại trước khi dựa vào các chi tiết cụ thể (đường dẫn, dòng, tên hàm).

## Phát hiện quan trọng nhất

Repo chứa **3 tầng codebase khác mức độ hoàn thiện rất xa nhau**. Bất kỳ trao đổi nào về "dự án" cần làm rõ đang nói tới tầng nào:

1. **Docs — có 2 họ tài liệu, KHÔNG ngang hàng nhau (đã xác nhận với chủ dự án 2026-08-06):**
   - **Họ A — BMAD product docs** (`ARCHITECTURE.md`, `docs/VIVI_API_Spec.md`, `_bmad-output/*`): tài liệu **ý tưởng/sản phẩm tầng trên**, ra bằng phương pháp BMAD, tác giả "Winston (System Architect)", đề ngày 2026-08-03. **Không dùng để implement chi tiết.**
   - **Họ B — Engineering spec set** (`docs/technical_spec.md`, `docs/api_spec.md`, `docs/agent_spec.md`, `docs/data_model.md`, `docs/safety_and_hitl.md`, `docs/adr/ADR-001..006`): đây là **spec kỹ thuật canonical**, thêm ngày 2026-08-01, tham chiếu chéo chặt chẽ với nhau và với ADR-006. `docs/technical_spec.md:3` tự ghi status **"Planned — approved P0 target"**. **Đây là bản dùng để viết issue/implement**, không phải Họ A.
   - Không file nào tự đánh dấu Họ A là "deprecated" — nên khi đọc code/docs cần chủ động bỏ qua Họ A khi cần chi tiết kỹ thuật, chỉ dùng nó để hiểu bối cảnh sản phẩm/ý tưởng.
   - **Việc cần làm sau (chưa làm, cố ý để nguyên — quyết định 2026-08-06):** `_bmad-output/planning-artifacts/{product-brief,PRD,ADR}.md` hiện ghi model đã "Approved" (Qwen2.5-3B) và vector store là ChromaDB — **mâu thuẫn trực tiếp** với Họ B (`docs/adr/ADR-005-model-profile-selection.md:3` ghi rõ **"Status: Not Yet"**; `docs/adr/ADR-003-local-rag-stack.md` chọn **FAISS + SQLite**, không phải ChromaDB). Khi có phương án model/RAG chính thức, quay lại cập nhật 3 file BMAD trên cho khớp Họ B.
2. **`src/`** — app FastAPI thực sự được Dockerfile/docker-compose chạy. Đây chỉ là **boilerplate LangChain/LangGraph generic** ("AI20K Agent"), scaffold khởi tạo — **chưa tới lượt implement theo Họ B**, không phải "lệch pha do thiếu đồng bộ". Hiện tại: 1 endpoint `/chat`, graph 2 node phân tích→trả lời (placeholder), backend OpenAI `gpt-4o-mini`, không auth, không RAG, không MQTT, không vehicle tool, không HITL, không DB.
3. **`experiments/offline_poc/`** — package PoC riêng, tiên tiến hơn `src/` nhiều: có pipeline LangGraph thật với HITL `interrupt()`, safety level S0–S3, chống stale-state, thực thi idempotent trên vehicle mock. Nhưng đây là **eval harness độc lập**, không nằm trong app deploy, và tự kết luận trong `eval/results/report.md:5`: **"Quyết định chọn model: Not Yet"**.

---

## 1. Kiến trúc dự án

- `ARCHITECTURE.md` (tiếng Việt) + `docs/architecture_diagram.md`: kiến trúc 8 lớp — Next.js (:3000) → FastAPI backend (:8000) → Voice Engine (Faster-Whisper/Piper) → Agent Core (LangGraph) → RAG (ChromaDB) → Local SLM (Qwen2.5-3B qua Ollama/llama.cpp :8080) → Virtual Vehicle (MQTT/Mosquitto :1883) → Storage (ChromaDB + SQLite). Ngân sách latency mục tiêu < 3.000ms end-to-end (`ARCHITECTURE.md:100-111`).
- `docs/technical_spec.md`: bản spec **mới hơn, chặt hơn, và mâu thuẫn một phần** với bản trên — modular monolith 5 service (`ivi-web`, `backend`, `llm`, `mqtt`, `vehicle-simulator`), dùng FAISS thay ChromaDB, SQLite+FAISS embed trong `backend`.
- `docs/agent_spec.md`: graph routing deterministic-first (normalize → router → RAG/SLM/candidate → validator → safety S0–S3 → approval → executor), có exactly-once/idempotency cho POI resolution và retry executor.
- `docs/api_spec.md` (12 endpoint REST/WS, idempotency key, RBAC, error envelope chuẩn) **khác** `docs/VIVI_API_Spec.md` (spec cũ hơn/đơn giản hơn: `/api/v1/voice/transcribe`, `/api/v1/agent/process`, `/api/v1/hitl/confirm`, header `X-Role`). Hai spec API này không khớp nhau, và cả hai đều không khớp route thực tế (`/api/v1/chat`).
- **Không có gì trong danh sách trên được hiện thực trong `src/`.** App thực chạy chỉ có `/health`, `/api/v1/chat`, `/api/v1/status`.

## 2. Cấu trúc thư mục

- `src/main.py` — FastAPI app factory, CORS middleware từ `settings.cors_origins`, include router `/api/v1`, endpoint `/health` (`src/main.py:37-39`).
- `src/config.py` — Pydantic Settings: `app_name`, `app_env`, `openai_api_key`, `model_name="gpt-4o-mini"`, `database_url` (mặc định sqlite, **không dùng**), `chroma_persist_dir` (**không dùng**) (`src/config.py:8-33`).
- `src/api/routes.py` — 1 router duy nhất: `POST /chat` (gọi `agent.ainvoke`), `GET /status` (`src/api/routes.py:9-25`). Không có route nào khác trong 12 endpoint spec (auth, sessions, turns, approvals, vehicle state, citations, traces, metrics, healthz, websockets).
- `src/agents/graph.py`, `state.py`, `nodes/example_node.py`, `tools/example_tool.py` — graph 2 node đơn giản: `analyze_node` (chỉ format chuỗi `f"Phân tích: {query}"`, placeholder, `src/agents/nodes/example_node.py:4-12`) → `respond_node`. `tools/example_tool.py` có 2 tool scaffold (`search_knowledge` placeholder, `calculate` — an toàn vì dùng AST whitelist, không phải `eval`).
- `src/models/schemas.py` — chỉ có `ChatRequest`/`ChatResponse`.
- `src/services/llm.py` — `get_llm()` trả về `ChatOpenAI` gắn với `settings.openai_api_key`/`model_name` (LLM cloud, không phải Qwen local như spec mô tả).
- `experiments/offline_poc/src/offline_poc/` — package riêng, hoàn thiện hơn: `stt.py`, `tts.py`, `llm.py`, `runner.py`, `graph.py` (logic HITL/interrupt thật, xem mục 6), `rag.py`, `vehicle_mock.py`, `contracts.py`, `metrics.py`, `scoring.py`, `report.py`. Có `pyproject.toml` riêng, chạy bằng llama.cpp local bundle trong `experiments/offline_poc/tools/llama-b9637/`.
- `eval/` — `datasets/poc/v1/` (manual.md, poi.json, audio manifest) và `results/spike-001/<timestamp>/` (manifest.json, metrics.json, case_results.jsonl, validity.json) + `eval/results/report.md` (báo cáo tổng hợp viết tay).

## 3. Tech stack

- Python 3.11 (`pyproject.toml:10`, `Dockerfile:2`).
- FastAPI + Uvicorn; LangChain 0.3 + LangGraph 0.2 + `langchain-openai`; Pydantic v2/pydantic-settings.
- `requirements.txt`: SQLAlchemy/Alembic/psycopg2 và ChromaDB **bị comment out** — tức thư viện DB/vector store chưa thực sự cài, dù `config.py` có sẵn setting `database_url`/`chroma_persist_dir` cho chúng.
- Deploy: Docker single-service (`Dockerfile` multi-stage, non-root user, healthcheck `/health`); `docker-compose.yml` chỉ chạy container `backend` — không có `mqtt`, `llm`, `ivi-web`, `vehicle-simulator` như spec 5-service mô tả.
- Dev tooling: ruff, pytest/pytest-asyncio, Makefile.
- `experiments/offline_poc/` dùng llama.cpp local (b9637) cho GGUF Qwen2.5, Piper cho TTS, PhoWhisper/Transformers cho STT — nơi duy nhất thực sự chạy model local/offline.

## 4. Authentication flow

- **Không có auth/authorization nào trong `src/`.** Grep auth/token/api_key/session/jwt trong `src/*.py` chỉ ra `openai_api_key` (config) và việc truyền nó vào `ChatOpenAI` (`services/llm.py`) — không có login endpoint, không kiểm tra bearer token, không RBAC, không session store.
- Khoảng cách lớn với spec: `docs/api_spec.md` định nghĩa `POST /api/v1/auth/login`, `Authorization: Bearer <token>` trên mọi route khác, RBAC (Driver vs Engineer), auth qua WebSocket subprotocol (`Sec-WebSocket-Protocol: vivi.v1, bearer.<token>`) — chưa có gì hiện thực trong `src/api/routes.py`.
- `experiments/offline_poc` cũng không có auth (là batch/offline eval harness, không phải API serve).

## 5. Database design

- Không có ORM model, không migration/SQL file, không thư mục `alembic` ở đâu trong `src/`.
- `src/config.py:29` khai báo `database_url: str = "sqlite:///./data/app.db"` nhưng không có engine/session/model nào dùng tới — **config chết**.
- `chroma_persist_dir` (`src/config.py:32`) tương tự — `chromadb` thậm chí không phải dependency đã cài (bị comment trong `requirements.txt:19`).
- `docs/data_model.md` (307 dòng) định nghĩa entity model phong phú (ActionPlan, ApprovalRequest, PlanningResolution, ToolResult, Citation...) — chỉ là tài liệu thiết kế, không có implementation backing trong `src/`.
- Kết luận: **backend đang deploy không có database nào cả**; stateless ngoại trừ in-memory LangGraph state theo từng request.

## 6. Main business logic

- **Pipeline `src/` (đang deploy):** `POST /chat` → `agent.ainvoke({"query": ...})` → `analyze_node` (placeholder, `src/agents/nodes/example_node.py:10`) → conditional edge `should_continue` (chỉ check `state["error"]`) → `respond_node` (`f"Kết quả dựa trên phân tích: {analysis}"`) → trả `ChatResponse`. Không STT/TTS, không gọi LLM thật, không RAG, không tool execution, không điều khiển xe — 2 "tool" trong `src/agents/tools/example_tool.py` tồn tại nhưng **không được nối vào graph**.
- **`experiments/offline_poc/src/offline_poc/graph.py`** (prototype thực sự chạy được) phức tạp hơn nhiều: `plan_node` (regex parse intent cho HVAC/door, `graph.py:26-60`) → `safety_node` (chặn hành động S3) → `approval_node` điều kiện dùng LangGraph `interrupt()` cho HITL, kiểm tra stale (`vehicle_state_version` lệch → `"stale_state"`) và hết hạn approval sau 30s (`graph.py:96-107`) → `execute_node` (thực thi theo thứ tự phụ thuộc trên `VehicleMock`, theo dõi `expected_version` qua các bước) → `compose_node` (map outcome sang câu trả lời tiếng Việt). Gần khớp với semantics an toàn trong `docs/agent_spec.md` hơn hẳn `src/`, nhưng vẫn là **PoC với vehicle mock**, không phải production, và tự kết luận (`eval/results/report.md:5`) là model choice fail hard gate.
- `eval/datasets/poc/v1/` chứa test corpus cố định của PoC offline (manual.md cho RAG grounding, poi.json cho POI lookup, audio manifest WAV); `eval/results/spike-001/<timestamp>/` chứa kết quả từng run.

## 7. Code smells

> **Lưu ý (2026-08-06):** khoảng cách "spec vs. `src/`" bên dưới **không phải code smell** — dự án hiện đang ở giai đoạn docs/design, `src/` mới chỉ là scaffold khởi tạo, chưa tới lượt implement theo Họ B. Cái còn là smell thật sự là việc **Họ A và Họ B không được đánh dấu rõ ai canonical** trong chính docs (dễ gây hiểu nhầm cho người đọc mới), không phải việc code chưa khớp spec.

- **Hai họ tài liệu không tự phân cấp rõ ràng**: `ARCHITECTURE.md`, `docs/architecture_diagram.md`, `docs/VIVI_API_Spec.md` (Họ A — ý tưởng/sản phẩm) mô tả một thiết kế, còn `docs/technical_spec.md`/`docs/agent_spec.md`/`docs/api_spec.md` (Họ B — kỹ thuật, canonical) mô tả thiết kế khác đáng kể (FAISS, 12-endpoint contract, ADR-006 modular monolith) — không có doc nào tự đánh dấu Họ A là tầng ý tưởng/không dùng để implement. Người mới đọc `ARCHITECTURE.md` trước dễ hiểu nhầm đó là spec kỹ thuật cần build theo.
- Code placeholder/TODO còn trong app "thật": `src/agents/nodes/example_node.py:8,23` (`# TODO: Thêm logic phân tích thực tế`, `# TODO: Thêm logic tạo response thực tế`), `src/agents/tools/example_tool.py:30` (`# TODO: Implement actual search logic`).
- Config chết: `database_url`, `chroma_persist_dir` trong `src/config.py` khai báo nhưng không dùng ở đâu (mục 5).
- Naming lệch: app title FastAPI là `"AI20K Agent"` (`src/main.py:19`) trong khi mọi doc/README gọi sản phẩm là "VIVI Cabin Copilot".
- Tên file `example_node.py`/`example_tool.py` cho thấy đây là scaffold/tutorial, nhưng lại là logic duy nhất được nối vào `graph.py`.
- Test trong `tests/test_agents/test_graph.py` chỉ assert `"response" in result` — tautological, không kiểm tra business rule thật (vì bản thân implementation cũng chỉ là placeholder).

## 8. Security issues

- **`.env` chứa API key nhìn như thật**: `OPENAI_API_KEY=sk-proj-...` (`.env:8`) và `AI_LOG_API_KEY` (`.env:40`). Đã xác nhận `.env` nằm trong `.gitignore` (`.gitignore:16`) và **không được track bởi git** (`git ls-files .env` rỗng) — nên không lộ qua git history, nhưng vẫn nằm không mã hoá trên đĩa. **Khuyến nghị: rotate key này** vì đã bị lộ ra qua lần phân tích này.
- `.env.example` dùng placeholder đúng chuẩn (`sk-your-key-here`) — tốt, nhưng `.env` thật không nên để key dạng production trong môi trường dev chia sẻ.
- Input validation chỉ có `min_length=1, max_length=5000` trên `ChatRequest.message` (`src/models/schemas.py:5`) — tối thiểu, hợp lý cho scaffold nhưng không có rate limiting, không auth, không CSRF/origin check trên endpoint `/chat` duy nhất.
- `calculate()` trong `example_tool.py` dùng AST whitelist (`_SAFE_OPERATORS`, dòng 7-17) thay vì `eval()` — pattern tốt, không phải smell.
- CORS (`src/main.py:26-32`): `allow_credentials=True` kết hợp `allow_methods=["*"], allow_headers=["*"]` — pattern dễ misconfigure nếu `cors_origins` mở rộng ra ngoài localhost sau này (hiện tại mặc định `http://localhost:3000` nên rủi ro thấp, nhưng cần lưu ý khi thêm origin).

## 9. Performance issues

- Pipeline `src/` hiện tại chỉ là 2 hàm format chuỗi khai báo `async` nhưng không có I/O thật — nên chưa có vấn đề blocking-trong-async, đơn giản vì chưa có việc gì thật sự chạy. Cần xem lại khi thêm ASR/LLM/TTS thật.
- Không có caching nào ngoài `lru_cache` trên `get_settings()` (`src/config.py:35`).
- `get_llm()` (`src/services/llm.py:6-12`) tạo `ChatOpenAI` mới mỗi lần gọi thay vì reuse singleton — không tối ưu, và hơn nữa hiện **không được gọi ở đâu** trong graph hiện tại.
- Offline PoC (không phải app deploy) đo được latency E2E thật **35.000–43.000 ms/run** so với hard gate p50 ≤ 2.500ms / p95 ≤ 4.500ms (`eval/results/report.md:13-19,37-41`) — cả Qwen2.5-0.5B và 3B quantized đều **fail** gate latency và tool-accuracy. STT (PhoWhisper) cold-start latency 16.353ms (gồm 5.827ms model load, report.md:28) — stack model offline đang **vượt budget 10-15 lần**, một gap performance lớn team đã ghi nhận là chưa giải quyết ("release gate Safety/RAG vẫn mở", report.md:69).
- Chưa có streaming response trong `src/` (spec yêu cầu streaming TTS/partial transcript) — `/chat` hiện tại là request/response blocking đơn giản.

## Tests

- `tests/conftest.py` — fixture `httpx.AsyncClient` async cho ASGI app; fixture `mock_llm` (không thấy test nào dùng).
- `tests/test_agents/test_graph.py` — 2 test, tautological (chỉ check key tồn tại, không check đúng-sai logic).
- `tests/test_api/test_routes.py` — 3 test: `/health` trả `status=ok`; `message` rỗng gửi `/chat` trả 422; `/api/v1/status` trả 200. Không có test nào gọi `/chat` với nội dung thật (sẽ chạm `ChatOpenAI` thật/mock), không có test cho auth, vehicle control, RAG, HITL vì các feature này chưa tồn tại trong `src/`.
- `experiments/offline_poc/tests/` được test kỹ hơn nhiều: `test_graph_hitl.py`, `test_e2e.py`, `test_rag.py`, `test_voice.py`, `test_scoring_report.py`, `test_metrics.py`, `test_dataset.py`, `test_config_contracts.py`, `test_demo_video_script.py`, `test_llm.py`, `test_runner.py`.

---

## Ghi chú khi dùng lại file này

- File này là **snapshot ngày 2026-08-06**. Trước khi dựa vào các claim cụ thể (đường dẫn, số dòng, tên hàm) để đưa ra quyết định code, nên verify lại bằng cách đọc file/grep nhanh — code có thể đã thay đổi.
- Nếu sau này `src/` được nâng cấp để khớp spec (auth, DB, RAG, MQTT...), cần cập nhật lại phần "Phát hiện quan trọng nhất" và các mục 1-9 tương ứng, vì kết luận cốt lõi ở đây dựa trên khoảng cách spec-vs-implementation.

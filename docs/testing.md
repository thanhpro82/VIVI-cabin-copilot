# Tài liệu kiểm thử — VIVI Cabin Copilot (P-192)

Đây là **cửa vào duy nhất** cho toàn bộ phần kiểm thử của dự án: chạy bằng lệnh gì,
phủ được bao nhiêu, tầng nào chứng minh được điều gì, và — quan trọng không kém —
tầng nào **không** chứng minh được điều gì.

> **Đừng nhầm với `docs/guide/`.** Thư mục đó là **giáo trình của BTC** được vendor
> vào repo (`chapter-08.md` là chương kiểm thử, `testing/writing-tests.md` là ví dụ
> mẫu thao tác trên route boilerplate `POST /api/v1/chat`). Nó mô tả *chuẩn chung*,
> không mô tả hệ thống này. File bạn đang đọc mới là tài liệu kiểm thử của P-192.

Mọi con số dưới đây là **ảnh chụp có ngày và có lệnh tái lập**, không phải số sống.
Đo lại trước khi trích dẫn, và trích đúng lần chạy bạn thực sự thực hiện.

---

## 1. Số liệu — đo 2026-08-31, commit `84e8d0a`

Máy dev Windows 11, Python 3.11.9, có sẵn FAISS index và model voice.

| Hạng mục | Kết quả | Lệnh |
|---|---|---|
| Backend pytest | **3.328 passed**, 43 deselected, exit 0 | xem §2 |
| Coverage `src/` | **92,01%** — 10.120 câu lệnh, 809 chưa chạm | xem §2 |
| Gate `fail_under = 60` | ✅ `Required test coverage of 60.0% reached` | `pyproject.toml` |
| Frontend Vitest | **612 passed / 68 file**, 83 s, exit 0 | `cd frontend; npm run test` |

Thời gian chạy: 480 s **có** instrument coverage. Không có `--cov` thì nhanh hơn
đáng kể, nhưng đừng trích thời gian như một hằng số — cùng một commit đã từng chạy
từ ~60 s tới ~240 s tuỳ cache đĩa và việc embedder E5 đã ấm hay chưa.

### So với mục tiêu BTC (`docs/guide/chapter-08.md` §8.4)

| Phần code | BTC yêu cầu | Đo được |
|---|---|---|
| API endpoints | 80% | `src/api/` — **96,2%** (1.211 stmts) |
| Agent nodes | 70% | `src/agents/nodes/` — **94,9%** (1.014 stmts) |
| Routing logic | 90% | `src/agents/` — **88,7%** (2.540 stmts) |
| Graph flow | 60% | (nằm trong `src/agents/`) |
| Tổng thể | **60%** | **92,01%** |

Các nhóm còn lại: `src/services/` 93,3% (2.771 stmts), `src/safety/` 96,7%,
`src/rag/` 90,3%, `src/vehicle_sim/` 79,6%.

### Con số 92% này KHÔNG bao gồm tầng kiểm thử vận chuyển

Đây là điều phải đọc kèm, không phải cước chú.

Lần đo trên chạy với `-m "not slow and not integration"`. Mà **L2 và L3 — hai tầng
sinh ra để phủ đúng phần MQTT — đều mang marker `slow`**, nên chúng bị loại khỏi
chính lần đo này. Hệ quả nhìn thấy được ngay trong báo cáo:

| Module | Cover | Vì sao |
|---|---|---|
| `src/services/mqtt_client.py` | **41%** | phần còn lại chỉ chạy ở L2/L3 (broker thật) |
| `src/vehicle_sim/__main__.py` | **48%** | entrypoint tiến trình, chỉ chạy ở L3 |
| `src/services/mqtt_runtime.py` | 72% | như trên |

Muốn phủ nốt thì phải chạy có broker (§3), và bằng chứng của tầng đó là thư mục
`eval/results/mqtt-e2e/`, không phải con số coverage.

Bốn chỗ 0% khác đều giải thích được: `src/serve.py` (entrypoint), `src/services/llm.py`
(5 dòng, LLM tắt mặc định), 8 shim 2 dòng ở `src/agents/tools/*.py`.

**`src/rag/giu_y.py` (39 dòng, 0%) không phải code chết.** Nó là thước *giữ ý* và
đang được [`scripts/ban_do_ba_truc.py`](../scripts/ban_do_ba_truc.py) dùng thật để
sinh bộ evidence `eval/results/ba-truc/` (10 run). Nó 0% vì `source = ["src"]` đếm
nó, còn đường chạy duy nhất gọi tới nó là một script eval — không nằm trong `pytest`.
Nợ ở đây là **thiếu unit test cho một hàm đang quyết định số liệu evidence**, chứ
không phải một module bỏ quên. Đáng viết test hơn là đáng xoá.

---

## 2. Chạy thế nào

```powershell
# Bộ nhanh — đúng những gì CI chạy.
# MQTT_ENABLED=false KHÔNG phải để cho nhanh cho vui: để mặc định `true` thì mỗi
# TestClient(app) chạy lifespan và chờ 10 giây một broker không tồn tại.
$env:MQTT_ENABLED="false"
.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow and not integration"

# Kèm coverage — đây là lệnh sinh ra mọi con số ở §1.
.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow and not integration" --cov=src --cov-report=term

# Một test cụ thể
.\.venv\Scripts\python.exe -m pytest tests/test_agents/test_policy.py::test_name -q

# Frontend
cd frontend; npm run test
```

**`skip` không phải regression.** Số test bị skip là **thuộc tính của máy**, không
phải của bộ test — không có gì bị skip chỉ vì marker. Chạy `pytest tests/` không cờ
trên máy có sẵn model thì `slow`/`integration` **vẫn chạy**; gỡ FAISS index và model
voice đi thì chúng skip. Luôn kiểm bằng `-rs` xem *test nào* skip trước khi kết luận.

### Một cái bẫy đang nằm trong `tests/`

Bốn script Playwright thủ công nằm ở `scripts/manual_e2e/` và bắn thẳng vào
`https://c4-app-192.io.vn`. Chúng **không phải pytest test**, không được CI thu gom,
và vẫn cần cài Playwright riêng trước khi chạy. Đừng chuyển chúng trở lại `tests/` với
tên `test_*.py`: pytest sẽ tự thu gom, trong khi chúng gọi mạng thật; thiếu Playwright
thì lệnh `pytest tests/` sẽ lỗi collection ngay. Nếu muốn đưa chúng vào CI, phải tách
thành một workflow E2E riêng có dependency, browser và guard URL/environment rõ ràng.

---

## 3. Ánh xạ sang kim tự tháp của BTC

Chương 8 chia ba tầng: unit (70–80%), integration (15–20%), evaluation (5–10%).
Repo này khớp mô hình đó, nhưng tầng giữa được tách thành **bốn mức riêng cho MQTT**
vì "integration" gộp chung không đủ để nói tầng nào chứng minh được cái gì.

| Tầng BTC | Ở repo này | Ví dụ |
|---|---|---|
| Unit | `tests/test_agents/` (77 file), `tests/test_services/` (28), `tests/test_rag/` (13) | router rules, policy S0–S3, chunker |
| Integration | `tests/test_api/` (39 file), `tests/test_vehicle/` (14) | endpoint qua `AsyncClient`+`ASGITransport`, 4 tầng MQTT dưới đây |
| Evaluation | `eval/results/` — **26 bộ, 214 run** | §4 |

Fixture `client` trong [`tests/conftest.py`](../tests/conftest.py) dùng đúng khuôn
`AsyncClient` + `ASGITransport` mà chương 8 khuyến nghị — gọi thẳng ASGI app, không
dựng HTTP server thật.

**Mock:** chương 8 nhấn mạnh phải mock LLM. Ở đây còn chặt hơn — `slm_enabled` mặc
định `False` (`src/config.py`), nên **không có LLM nào trên đường chạy mặc định**,
định tuyến là 100% luật tất định (ADR-006/ADR-010). MQTT có `InMemoryBroker` cho L1.

### Bốn tầng MQTT, và điểm mù của từng tầng

Bảng này không phải văn xuôi trang trí: nó là bản sao của `_BLIND_SPOTS` trong
[`scripts/report_mqtt_e2e.py`](../scripts/report_mqtt_e2e.py), tức là máy đọc được.

| Tầng | Chạy cái gì | **Vẫn chưa chứng minh được** |
|---|---|---|
| L0 unit | hàm thuần | không nói gì về vận chuyển |
| L1 in-memory | `InMemoryBroker`, hoàn toàn tất định, 0 flaky | QoS 1 duplicate, retain qua restart, ACL, Last Will, reconnect |
| L2 contract | Mosquitto thật, một tiến trình pytest | không có HTTP/WS thật; backend và simulator chưa tách tiến trình |
| L3 two-process | `src.serve` + `src.vehicle_sim` là hai tiến trình thật, socket thật | image Docker, topology Compose, mạng phân mảnh, nhiều xe cùng lúc |

```powershell
$env:MQTT_CONTRACT_TESTS="1"; .\.venv\Scripts\python.exe -m pytest tests/test_vehicle/test_contract_mosquitto.py -q
$env:MQTT_L3_TESTS="1";       .\.venv\Scripts\python.exe -m pytest tests/test_vehicle/test_l3_two_process.py -q

# Sản phẩm giao nộp là THƯ MỤC RUN, không phải file test:
.\.venv\Scripts\python.exe scripts\report_mqtt_e2e.py --with-contract --with-l3
```

Cả hai tầng đều đọc broker URL và credential qua `get_settings()` nên tuân theo
`.env`. Đọc thẳng `os.getenv` từng là bug thật: trên máy đã có thứ khác giữ cổng
1883, L2 lặng lẽ nối **ẩn danh vào nhầm broker** rồi báo cáo phát hiện ACL về nó.

---

## 4. Evaluation evidence — 26 bộ, 214 run

Mỗi thư mục `eval/results/<suite>/<UTC-run-id>/` là **bất biến**: `manifest.json`,
`case_results.jsonl`, `metrics.json`. Không sửa tay bao giờ — chạy lại CLI để sinh
run id mới.

Gate cứng áp dụng **trước** khi xếp hạng: gọi cloud, sai schema, vi phạm an toàn,
thực thi actuator trùng, citation không hợp lệ, vượt RAM, vượt latency — dính một
cái là loại, bất kể điểm tổng.

**17/26 bộ được ADR hoặc report trích dẫn đích danh**, tức là chúng thực sự đã đổi
một quyết định thiết kế chứ không nằm đó cho đẹp:

| Bộ | Run | Mới nhất | Được trích ở |
|---|---:|---|---|
| `agent-routing` | 36 | 2026-08-28 | ADR-026, `huong_dan_chay.md` |
| `agent-intent` | 28 | 2026-08-30 | `scope-decision-pr-92` |
| `agent-multiturn` | 23 | 2026-08-30 | spec lộ trình agent |
| `rag` | 19 | 2026-08-29 | ADR-011, ADR-015 |
| `spike-003` | 17 | 2026-08-13 | ADR-015, ADR-016 |
| `spike-001` | 11 | 2026-08-02 | `codebase_analysis.md`, `evaluation_plan.md` |
| `mqtt-e2e` | 10 | 2026-08-20 | `mqtt_giai_thich.md` |
| `luot-that-dong-thoi` | 9 | 2026-08-25 | ADR-030 |
| `chitchat` | 8 | 2026-08-23 | `coverage_matrix.md` |
| `trang-bi` | 5 | 2026-08-19 | `khao_sat_trang_bi.md` |
| `slm-dong-thoi` | 4 | 2026-08-23 | ADR-028, ADR-030 |
| `do-tre` | 2 | 2026-08-22 | `sp0-do-tre-tung-doan` |
| `stt-compare` | 2 | 2026-08-12 | ADR-017 |
| `ram-nhieu-xe` | 2 | 2026-08-23 | ADR-028 |
| `ram-phien-backend` | 1 | 2026-08-23 | ADR-028 |
| `offline-drill` | 1 | 2026-08-15 | `offline_drill.md` |
| `wake-word` | 1 | 2026-08-21 | `README.md`, `huong_dan_chay.md` |

Chín bộ còn lại **chưa được doc nào trích**, ghi ra để khỏi tưởng chúng đã được dùng:
`ba-truc` (10 run), `planner-args` (9), `agent-bao-loi` (7), `voice-hitl-wer` (3),
`tom-tat` (2), `cau-dan`, `cham-tay`, `chon-cau`, `voice-payload` (mỗi bộ 1 run).

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode intent    # -> eval/results/agent-intent/
.\.venv\Scripts\python.exe -m src.agents.eval --mode routing   # -> eval/results/agent-routing/
.\.venv\Scripts\python.exe -m src.rag.cli eval                 # -> eval/results/rag/
```

**Hai dataset agent không thay thế được nhau.** `eval/datasets/agent/v3` do chính
người viết router soạn, nên `intent_accuracy = 1.0000` của nó chỉ là **dây bẫy
regression**, không nói gì về khả năng khái quát. `eval/datasets/manual/v1` do nhóm
RAG soạn cho mục đích khác nên con số 0,9833 (câu hỏi tới được RAG) nặng ký hơn.
Không bộ nào đi qua ASR, nên không bộ nào phản ánh lỗi nhận dạng giọng nói. **Không
được trình bày chúng như độ chính xác với người dùng thật.**

---

## 5. CI chạy gì, và không chạy gì

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — Python 3.11, `MQTT_ENABLED=false`:

1. `ruff check src/ tests/ scripts/` — **`scripts/` không phải tuỳ chọn**: chạy hẹp hơn ở máy vẫn xanh trong khi CI đỏ. Đã mất một vòng review vì đúng chuyện này (PR #268).
2. `pytest tests/ -m "not slow and not integration"` + junit artifact.

**CI không cài `rag` extra, không cài model voice.** Nghĩa là bằng chứng
RAG-integration và voice-integration **chỉ được sinh ra bởi người chạy ở máy local**,
không bao giờ bởi CI. `.github/workflows/mqtt-contract.yml` là job riêng cho L2.

CI **có chạy `--cov=src`** từ 2026-08-31, nên `fail_under = 60` trong `pyproject.toml`
là gate thật: build đỏ nếu tụt dưới 60%. Mỗi lần chạy còn đẩy `reports/coverage.xml`
làm artifact, tức là có bằng chứng coverage kèm ngày tháng chứ không chỉ một con số
chép tay trong tài liệu này.

Một chi tiết dễ vấp nếu sau này ai sửa CI: `pytest-cov` phải nằm trong
**`requirements.txt`**, không phải chỉ trong extra `[dev]` của `pyproject.toml` — CI
chỉ cài `requirements.txt`, nên để thiếu là pytest chết ngay ở
`error: unrecognized arguments: --cov`.

---

## 6. Còn thiếu — đọc mục này trước khi hứa bất cứ điều gì

- **7/19 test an toàn** bắt buộc theo `docs/safety_and_hitl.md` đã có
  (`tests/test_agents/test_hitl_safety.py`: #1, #2, #4, #5, #6, #12, #17).
- **Chưa có WER trên giọng người thật.** Số WER/CER hiện có đo trên audio Piper tổng
  hợp — là integration evidence, **không phải** độ chính xác với tài xế Việt Nam,
  giọng vùng miền hay tiếng ồn cabin.
- **Chưa đo độ trễ end-to-end trên đường mic → loa.** Mục tiêu p50 ≤ 2.500 ms /
  p95 ≤ 4.500 ms chưa có phép đo nào chứng minh. Con số 5,6 s trong các report cũ là
  của SPIKE-001, một pipeline khác — **không được tái sử dụng**.
- **Chưa có nghiên cứu người dùng** đủ hai vòng theo yêu cầu.
- **Test E2E trên trình duyệt chưa vào CI** (xem cái bẫy ở §2).
- `src/rag/giu_y.py` 0% coverage — thước đang quyết định số liệu `eval/results/ba-truc/`
  mà không có unit test nào (§1).

Test đơn vị xanh **không phải** bằng chứng chất lượng model, cũng không phải bằng
chứng độ trễ. Mọi phát biểu định lượng phải truy được về một run id.

---

## 7. Đọc thêm

| File | Vai trò |
|---|---|
| [`docs/evaluation_plan.md`](evaluation_plan.md) | Kế hoạch đánh giá, gate và tiêu chí |
| [`docs/huong_dan_chay.md`](huong_dan_chay.md) §3.5 | Số tham chiếu được bảo trì cho việc chạy suite |
| [`docs/safety_and_hitl.md`](safety_and_hitl.md) | 19 test an toàn bắt buộc |
| [`docs/release/routines-mvp-uat-traceability.md`](release/routines-mvp-uat-traceability.md) | Truy vết UAT của Routines MVP |
| [`docs/release/uat-bug-triage.md`](release/uat-bug-triage.md) | Phân loại bug từ buổi UAT |
| [`docs/release/mvp-demo-checklist.md`](release/mvp-demo-checklist.md) | Checklist trước demo |
| [`docs/coverage_matrix.md`](coverage_matrix.md) | Bản đồ *hệ thống điều khiển được gì* (khác với code coverage) |
| [`docs/offline_drill.md`](offline_drill.md) | Bài kiểm tra ngắt mạng |

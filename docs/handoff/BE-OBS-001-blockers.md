# TASK-BE-OBS-001 — phần **không tự đóng được**, cần người khác

**Người viết:** Bế Nguyễn Hà Sơn · **Ngày:** 2026-08-10
**Nhánh:** `feature/engineer-observability-traces-metrics` (base `develop@31390e1`)
**Ticket:** Engineer Observability APIs — `GET /traces/{id}`, `GET /metrics/summary`, 3 event `/ws/engineer`
**Tài liệu thiết kế đầy đủ:** [`docs/tasks/TASK-BE-OBS-001-engineer-observability.md`](../tasks/TASK-BE-OBS-001-engineer-observability.md)

---

## 0. Đọc file này để làm gì

Toàn bộ acceptance criteria của ticket **đã đạt** trên nhánh này — hai endpoint chạy, `/ws/engineer`
phát đủ 5 loại event, error dùng `ErrorEnvelope` canonical, 755 passed / 15 skipped / lint sạch.

Nhưng có **6 khoảng trống** mà tầng observability *nhìn thấy* và *không được phép tự sửa*, vì chúng
nằm trong vùng sở hữu của người khác hoặc là quyết định hợp đồng của cả nhóm. Mỗi mục dưới đây ghi:
hệ quả **hôm nay** (không phải giả định), tại sao tôi không tự làm, và cách vá tạm đang có trong code.

Ba mục đầu (B1–B3) là **bug thật, không phải thiếu tính năng**. B1 và B2 ảnh hưởng cả các bề mặt
ngoài ticket này.

> **Cập nhật 2026-08-11 — 4/6 đã đóng.** B1, B3, B4 đóng bởi issue #45; B5 bởi issue #48 (PR #54).
> Còn mở: **B2** (`trace_id` đứt qua HITL — vùng Nhân) và **B6** (`mqtt.latency_ms`, cần đổi hợp
> đồng dây). Mỗi mục đã đóng giữ lại bối cảnh gốc trong `<details>` để người đọc sau vẫn dựng lại
> được vì sao nó từng bị chặn — file này là bản ghi bàn giao, không phải bảng TODO.

---

## B1 — ✅ ĐÃ ĐÓNG 2026-08-11 (issue #45) — `require_engineer` đã có

| | |
|---|---|
| **Chủ sở hữu** | Nguyễn Tuấn Thành (`src/api/auth_deps.py`, đến từ PR #37) |
| **Mức độ** | ~~🔴 Chặn tuyên bố "đúng `api_spec.md`"~~ → đã đóng |
| **Hệ quả hôm nay** | Không còn. `/traces/{id}` và `/metrics/summary` đi qua `Depends(require_engineer)`; không token → 401 `AUTH_REQUIRED`, token tài xế → 403 `FORBIDDEN` |

**Đã làm gì:** `require_engineer` vào `src/api/auth_deps.py` đúng khuôn `require_driver`;
`_require_engineer` no-op **bị gỡ hẳn** và thay bằng `dependencies=_ENGINEER_ONLY` khai một
lần cho cả hai route. Test khoá ở `tests/test_api/test_observability_rbac.py` (file riêng có
chủ đích: các file observability khác giờ chạy qua fixture `engineer_client` nên chúng vẫn
xanh nếu ai đó gỡ dependency — chỉ file kia đỏ).

**Còn nợ, đã ghi lại trong docstring của hàm:** phần *owner-scoped* của `api_spec.md:8` chưa
làm được — `TraceRecord` không mang `user_id` nào để so, nên ranh giới thực tế là **role**,
không phải chủ sở hữu. Ở P0 chỉ có một engineer demo nên hai thứ trùng nhau; đừng đọc
`Depends(require_engineer)` thành "đã lọc theo người".

<details><summary>Bối cảnh gốc</summary>

`docs/api_spec.md:8` chốt `/metrics/summary` là **Engineer-only** và trace là owner/role-scoped.
`src/api/auth_deps.py` hiện có `get_current_user`, `require_driver`, `require_idempotency_key`,
`require_schema_version` — **không có** biến thể engineer.

**Vì sao không tự thêm:** thêm một dependency vai trò vào `auth_deps.py` là định nghĩa mô hình phân
quyền của hệ thống, không phải một tiện ích cục bộ. Làm hộ trong nhánh này sẽ đẻ ra hai định nghĩa
"engineer là ai" nếu Thành cũng đang viết nó cho `/ws/engineer` auth.

**Vá tạm đang có:** `src/api/observability.py:_require_engineer(request)` — hàm **rỗng có tên rõ ràng**,
gọi ở cả hai route. Cố ý không để trống hoàn toàn: khi `require_engineer` về, chỗ phải sửa là
2 dòng, và `grep _require_engineer src/` chỉ ra ngay route nào đang hở. Bỏ trống thì khoảng trống này
biến mất khỏi tầm nhìn.

**Cần Thành làm:** thêm `require_engineer` vào `auth_deps.py` theo đúng khuôn `require_driver`.
Sau đó tôi đổi `_require_engineer` thành `Depends(require_engineer)` — một PR ~10 dòng.

</details>

---

## B2 — `approvals.py` đúc `trace_id` mới lúc resume → trace của lượt S2 bị đứt làm đôi

| | |
|---|---|
| **Chủ sở hữu** | Hoàng Văn Nhân (`src/api/approvals.py`, PR #36) |
| **Mức độ** | 🟠 Bug thật, **ảnh hưởng cả `/ws/ivi` hôm nay**, không riêng ticket này |
| **Hệ quả hôm nay** | Đã vá tạm được ở tầng quan sát. Nhưng trên `/ws/ivi` thì client vẫn nhận nửa sau của lượt dưới một `trace_id` chưa từng thấy |

`src/api/approvals.py:118` trong `_resume_and_publish`:

```python
trace_id = f"tr_{uuid.uuid4().hex[:12]}"
```

Nửa đầu của lượt S2 (`turn.accepted` → `plan.ready` → `approval.required` → `waiting_approval`) phát
dưới trace **A**. Sau khi tài xế bấm Đồng ý, `turn.completed` phát dưới trace **B** — một id chưa từng
được mở. `ApprovalRecord` không mang `trace_id` nên hàm không có gì để khôi phục.

**Hệ quả nếu không vá (đã đo trước khi vá):** mọi lượt cần duyệt treo ở `waiting_approval` vĩnh viễn
trong kho trace, không bao giờ có event `trace` cho dashboard, và `turns.completed` đếm thiếu **đúng
những lượt đáng chú ý nhất**.

**Vì sao không tự sửa:** thêm `trace_id` vào `ApprovalRecord` là đổi hợp đồng của tầng HITL — nơi có
bất biến single-use / plan-bound / at-most-one-pending và `approval_id` dẫn xuất tất định. Đây là vùng
Nhân, và PR #36 vừa merge.

**Vá tạm đang có:** `TraceStore` giữ index phụ `turn_id → trace_id`, và
`TraceCollector.resolve()` (`src/services/trace_collector.py`) thử `trace_id` trước rồi mới tới
`turn_id`. `turn_id` xuyên suốt cả hai nửa vì `_resume_and_publish` nhận nó từ `ApprovalRecord`.
Test khoá: `test_luot_s2_sau_khi_duyet_van_seal_dung_trace_ban_dau`.

**Vá tạm này KHÔNG đóng được phần `/ws/ivi`** — client vẫn thấy `trace_id` nhảy giữa lượt. Nối lại ở
tầng quan sát là việc của tôi; làm `trace_id` liên tục trên dây là việc của tầng HITL.

**Còn một hệ quả nữa chưa vá:** vì `approvals.py` gọi thẳng `emit_turn_lifecycle` chứ không đi qua
`turns.py`, nửa sau của lượt S2 **không** chạy `record_graph_result()`. Nên `outcome` của một lượt S2
đã duyệt vẫn dừng ở `approval_required` của nửa đầu. `admission`/`max_level` vẫn đúng (từ
`approval.required`), nhưng `safety_summary.outcome` không phản ánh kết quả thực thi.

**Cần Nhân làm:** thêm `trace_id: str` vào `ApprovalRecord`, ghi lúc `create()`, dùng lại nó ở
`_resume_and_publish` thay vì `uuid4()`. Khi đó `resolve()` của tôi vẫn chạy đúng (nhánh `trace_id`
khớp ngay), index `turn_id` trở thành lưới an toàn thay vì đường sống.

---

## B3 — ✅ ĐÃ ĐÓNG 2026-08-11 (issue #45) — `ivi_stream` dùng `_close_quietly`

| | |
|---|---|
| **Chủ sở hữu** | Nguyễn Tuấn Thành (`/ws/ivi`) |
| **Mức độ** | ~~🟡 Rác log~~ → đã đóng |
| **Hệ quả hôm nay** | Không còn traceback rác khi client ngắt trước `connection.init` |

Hoá ra không phải 2 chỗ mà **5** — nhánh auth, nhánh `hello` sai định dạng, nhánh cursor
replay hỏng, và nhánh ownership. Tất cả giờ đi qua `_close_quietly`; docstring của hàm đó
ghi thẳng "đừng gọi `websocket.close()` trần trong file này nữa", và trong cả file chỉ còn
**một** lời gọi `websocket.close()` thật — dòng bên trong chính `_close_quietly`.

**Test khoá:** `tests/test_api/test_ws_hardening.py::test_close_that_fails_a_second_time_does_not_escape_the_ivi_route`
— ép `WebSocket.close` ném lỗi rồi khẳng định lỗi đó không thoát ra khỏi route. Đã kiểm chứng
ngược: đưa lại `close()` trần thì test đỏ với đúng `RuntimeError` bị ép.

---

## B4 — ✅ ĐÃ ĐÓNG 2026-08-11 (issue #45) — auth cho `/ws/engineer`; replay là **quyết định không làm**

| | |
|---|---|
| **Chủ sở hữu** | Nguyễn Tuấn Thành (đã tuyên bố nhận ở standup) |
| **Mức độ** | ~~🟠 Khoảng trống hợp đồng~~ → đã đóng, phần replay chuyển thành quyết định có ghi lý do |

**Auth — đã làm.** `_authenticate_ivi_connection` được tổng quát hoá thành
`_authenticate_ws_connection(websocket, *, required_role)` và cả hai socket gọi chung nó. Một
hàm chứ không hai: hai bản sao là hai định nghĩa "ai được nối", và chúng sẽ lệch nhau ở đúng
lần sửa mà không ai sửa cả hai. `/ws/engineer` giờ đòi bearer + role `engineer` + Origin
allowlist, đóng `4401`/`4403` đúng `api_spec.md:507`, và chỉ chọn lại `vivi.v1` trong
handshake. Test: `tests/test_api/test_ws_hardening.py` (7 case, đối xứng với nhóm Auth của
`test_ws_ivi.py`).

**Replay — cố ý KHÔNG làm, và lý do nằm trong docstring đầu `src/api/ws.py`.** Replay của
`/ws/ivi` (ADR-014) đánh số theo **phiên**, không theo kết nối, vì lượt thoại là một chuỗi có
thứ tự mà tài xế phải nhận đủ. Stream kỹ sư không có phiên (`api_spec.md:533` bỏ `session_id`
khỏi `connection.init` của nó), và `state`/`metrics`/`health` là **ảnh chụp tại thời điểm**:
phát lại một mẫu `health` của 30 phút trước cho dashboard vừa nối lại là nói dối về hiện tại,
không phải phục hồi độ tin cậy. Client nối lại nhận snapshot mới ngay trong handshake. `trace`
là loại duy nhất có tính lịch sử, và nó **đã** có đường đọc lại đúng nghĩa: `GET /traces/{id}`.

Nếu nhóm muốn đảo quyết định này thì phải đảo tường minh — nó là một dòng trong
`docs/api_spec.md:533` chưa phân biệt hai kênh, không phải một TODO bị bỏ quên.

`sequence` vẫn tăng đơn điệu xuyên cả 5 loại event trong một kết nối
(`test_ws_engineer_events.py::test_phat_du_ca_nam_loai_event`) — auth không đụng vào vỏ sự kiện.

---

## B5 — ✅ ĐÃ ĐÓNG 2026-08-11 (issue #48, PR #54) — `llm` là optional ở P0

| | |
|---|---|
| **Chủ sở hữu** | 🟣 Quyết định của **cả nhóm**, không phải kỹ thuật |
| **Mức độ** | ~~🟡 dashboard luôn đỏ~~ → đã đóng |

**Nhóm đã chốt: optional.** `src/services/health.py` có `REQUIRED_COMPONENT_NAMES` = 7/8
(trừ `llm`); cả `GET /healthz` lẫn event `health` của `/ws/engineer` đọc **cùng** tập đó cho
gate `all_ready`, nên hai đường không thể lệch nhau. Trạng thái thật của `llm` vẫn xuất hiện
đầy đủ trong `components` và `faults` — miễn trừ khỏi *gate*, không phải giấu đi. Đưa lại vào
gate khi LLM/SLM thành dependency bắt buộc của luồng P0/P1.

<details><summary>Bối cảnh gốc</summary>

`slm_enabled` mặc định `False` (`src/config.py`), ADR-005 còn "Not Yet". Probe `llm` báo không sẵn
sàng, nên readiness tổng luôn khác `ready`.

Event `health` trên `/ws/engineer` mang đúng sự thật đó — **đây không phải lỗi của tôi để sửa**.
Câu hỏi cần cả nhóm chốt: `llm` là **required** component (readiness đỏ là đúng) hay **optional**
component ở P0 (readiness nên xanh, `llm` hiện `not-configured`)? Ai đó phải quyết, rồi tôi sửa
`src/services/health.py` theo.

Tôi cố ý **không** tự chọn: hạ `llm` xuống optional là âm thầm nới một tuyên bố trạng thái, đúng thứ
`CLAUDE.md` cấm ("không nâng status khi chưa có artifact biện minh").

</details>

---

## B6 — `mqtt.latency_ms` luôn rỗng vì độ trễ **từng bước** không có trên hợp đồng dây

| | |
|---|---|
| **Chủ sở hữu** | Hợp đồng chung (`docs/api_spec.md` + `src/services/ivi_events.py`) |
| **Mức độ** | 🟡 Giới hạn đã ghi rõ, `null` là câu trả lời trung thực |

Payload `tool.result` chỉ mang `step_id`, `command_id`, `status`, `observed_state_version`,
`error_code` — **không** có `latency_ms`. Nên `mqtt.latency_ms` trả `count: 0` và percentile `null`.

Tổng thời gian thực thi vẫn đo được và nằm ở `stage_latency_ms.tool` (đo tại node `execute` bằng
wrapper `_timed`, chứ không suy từ sự kiện). Chia tổng cho số bước rồi gọi đó là p50 là **bịa số** —
không làm.

Ngoài ra `mqtt.publish_attempts` là **xấp xỉ**: nó đếm số bước đã thực thi, không phải số publish thô
lên broker. Retry của QoS 1 và ack lặp nằm **dưới** tầng trace (`src/services/tool_executor.py`).
Đếm thật cần counter trong `MqttVehicleGateway`. Đã ghi ở docstring `_mqtt` và trong `docs/api_spec.md`.

**Cần ai đó làm (việc nối tiếp, không gấp):** thêm `latency_ms` vào payload `tool.result` (đổi hợp
đồng dây → cần Thành + Giáp đồng ý), hoặc counter tầng broker trong `MqttVehicleGateway` (vùng tôi,
nhưng ngoài phạm vi ticket này).

---

## Bảng tóm tắt

| # | Vướng | Ai | Trạng thái |
|---|---|---|---|
| B1 | `require_engineer` chưa có | Thành | ✅ **Đóng 2026-08-11** (issue #45) — `Depends(require_engineer)` trên cả hai route; phần *owner*-scoped vẫn nợ, đã ghi trong docstring |
| B2 | `trace_id` đứt qua HITL | Nhân | ⏳ Còn mở — vá tạm bằng index `turn_id` trong `TraceStore`; `/ws/ivi` vẫn nhảy trace giữa lượt |
| B3 | double-close ở `ivi_stream` | Thành | ✅ **Đóng 2026-08-11** (issue #45) — 5 chỗ, không phải 2 |
| B4 | WS auth/role/replay | Thành | ✅ **Đóng 2026-08-11** (issue #45) — auth xong; replay là **quyết định không làm**, lý do ở docstring `src/api/ws.py` |
| B5 | `/healthz` luôn 503 | Cả nhóm | ✅ **Đóng 2026-08-11** — PR #54 hạ `llm` xuống optional ở P0 |
| B6 | `mqtt.latency_ms` rỗng | hợp đồng chung | ⏳ Còn mở — `null` + ghi rõ giới hạn; 1 ô trống, **có** lý do |

---

## Những gì KHÔNG nằm trong file này

Các mục dưới đây thiếu nhưng **không phải do vướng ai** — chúng nằm ngoài phạm vi ticket và đã ghi ở
`docs/tasks/TASK-BE-OBS-001-engineer-observability.md` §Ngoài phạm vi:

- Persist trace xuống SQLite (`docs/data_model.md:304` đòi 30 ngày). Kho hiện in-memory có trần, mất
  khi restart — **cùng loại nợ với approval store**, nên xử lý cùng lúc chứ không riêng lẻ.
- `model_runtime` toàn `null` / `model_profile: "not-selected"` — đó là **sự thật** của P0, không phải
  thiếu sót. `api_spec.md:464` cho phép rõ.
- `stage_latencies_ms.tts` = `null` — Piper chưa nối vào pipeline (`synthesize()` có, không caller nào
  gọi). Không thuộc ticket này.
- `rag.faithfulness_*` = 0 / `null` — `api_spec.md:460` **cấm** self-score của model chưa được người
  chấm. Con số đó chỉ đến từ `src/rag/evaluate.py` chạy offline.
- `GET /citations/{id}`, event `ui.policy` — hai interface khác, chưa ai nhận.

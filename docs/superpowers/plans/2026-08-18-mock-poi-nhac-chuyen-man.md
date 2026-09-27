# Kế hoạch: POI mock, nhạc cục bộ, và chuyển màn bằng giọng nói

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nói một câu thì IVI tự nhảy sang đúng màn (điều khiển / nhạc / bản đồ / một trong ba app giải trí), với 5 POI mock có lộ trình và 5–6 bài nhạc cục bộ, mà không làm rộng thêm vết phụ thuộc mạng lúc chạy.

**Architecture:** Thiết kế đầy đủ ở [`../specs/2026-08-18-mock-poi-nhac-chuyen-man-design.md`](../specs/2026-08-18-mock-poi-nhac-chuyen-man-design.md). Ba trụ: (1) fixture JSON dùng chung BE/FE với test so byte chống trôi; (2) `plan.ready` mang `steps[{step_id,tool,domain,args}]`, FE tự ánh xạ sang view; (3) `open_app` là **tool cục bộ của IVI** — `domain=None`, không đi qua MQTT, S1 khi xe ở P và S3 khi không.

**Tech Stack:** Python 3.11.9 + FastAPI + LangGraph + Pydantic; Next.js 16 + TypeScript + Vitest; pytest; Leaflet.

## Global Constraints

- **Backend không bao giờ biết tên màn hình.** `ViewName` của FE không được xuất hiện trong payload, enum Python, hay `docs/api_spec.md`.
- **Chuyển màn bám `tool.result(completed)`, không bám `plan.ready`.** Bám `plan.ready` là mở video xong mới chặn S3.
- **Không đụng hợp đồng media**: `MediaControlArgs`, `schemas/mqtt/vehicle_command.schema.json`, và nhánh `_apply_media` của simulator giữ nguyên. Chọn bài theo tên ngoài phạm vi.
- **Giữ nguyên ba id POI đang chạy** — `poi-cafe-01`, `poi-cafe-02`, `poi-charge-01`.
- **Thứ tự các bước của `_match` (ADR-011) không đảo** — và đừng đếm số bước: `579113c` vừa chèn thêm `tire_pressure_query` (`router.py:329-341`).
- **Mọi `file:line` dưới đây tính theo `develop` @ `579113c`.** Đợt pull ngày 18/08 chèn ~56 dòng vào giữa `router.py`, nên số dòng trong tài liệu cũ hơn đều lệch.
- Nhạc phải là **CC0/CC-BY**, dùng đúng tên gốc, kèm `LICENSE.md`.
- Chạy mọi lệnh Python qua `.\.venv\Scripts\python.exe` và đặt `$env:MQTT_ENABLED="false"` khi chạy pytest.

## Thứ tự để hai người không chặn nhau

Task 1 và Task 2 là **hợp đồng**. Đẩy hai cái đó lên `develop` trước; Giáp chỉ cần đúng hai thứ đó để làm Task 6–8 song song với Task 3–5 của Sơn.

| Task | Người | Chặn ai |
|---|---|---|
| 1. Fixture dùng chung | Sơn | chặn 3, 5, 6, 7 |
| 2. `plan.ready.steps[]` | Sơn (báo Nhân) | **chặn 6** |
| 3. Router đọc fixture | Sơn | — |
| 4. `open_app` | Sơn (cần Thành duyệt ADR) | chặn phần app của 6 |
| 5. Playlist CC0 | Sơn | chặn 8 |
| 6. FE ánh xạ view | Giáp | — |
| 7. FE bản đồ | Giáp | — |
| 8. FE nhạc + chế độ offline | Giáp | — |
| 9. Tài liệu | Sơn | — |

---

### Task 1: Fixture POI và media dùng chung, có test chống trôi

**Files:**
- Create: `src/fixtures/poi.json`
- Create: `src/fixtures/media.json`
- Create: `src/fixtures/__init__.py`
- Create: `scripts/sync_fixtures.ps1`
- Create: `frontend/src/lib/fixtures/poi.json` (bản sao do script sinh)
- Create: `frontend/src/lib/fixtures/media.json` (bản sao do script sinh)
- Test: `tests/test_services/test_fixtures.py`

**Interfaces:**
- Produces: `load_poi_fixture() -> list[dict]`, `load_media_fixture() -> list[dict]` — đọc từ `src/fixtures/`, `@lru_cache`.
- Consumed by: `src/agents/graph.py` (Task 3), `src/vehicle_sim/state.py` (Task 5), frontend qua bản sao được import (Task 6–8).

- [ ] **Step 1: Viết `src/fixtures/poi.json` — 5 địa điểm, 5 nhóm**

Nhóm: `cafe`, `restaurant`, `mall`, `entertainment`, `charging`. Mỗi item:

```jsonc
{
  "id": "poi-cafe-01",
  "name": "Highlands Coffee Nguyễn Trãi",
  "category": "cafe",
  "aliases": ["cà phê", "cafe", "highland", "highlands"],
  "lat": 21.0031, "lon": 105.8201,
  "distance_km": 3.4, "eta_min": 12,
  "polyline": [[21.0045, 105.8412], [21.0038, 105.8305], [21.0031, 105.8201]]
}
```

Ba id **bắt buộc giữ**: `poi-cafe-01` (cà phê), `poi-cafe-02` (Cà phê Bình Minh), `poi-charge-01` (trạm sạc). Alias phải phủ cả biến thể không dấu, vì STT tiếng Việt trả ra nhiều cách viết cho cùng một tên riêng.

- [ ] **Step 2: Viết `src/fixtures/media.json` — 5–6 bài CC0**

Mỗi item: `{ "id", "name", "artist", "file", "cover", "license", "source_url" }`. `name` là **tên gốc của bản CC0**, không phải tên nhạc Việt có bản quyền — xem §6 của spec.

- [ ] **Step 3: Viết `src/fixtures/__init__.py`**

Hai hàm `load_poi_fixture()` / `load_media_fixture()`, đọc file cạnh repo root, `@lru_cache` để không đọc đĩa mỗi lượt. Ném lỗi rõ ràng nếu thiếu file hoặc thiếu `id`.

- [ ] **Step 4: Viết `scripts/sync_fixtures.ps1`**

Copy `src/fixtures/*.json` → `frontend/src/lib/fixtures/`. Đặt vào `src/lib/` chứ **không** `public/`: file được bundle theo import, nên chế độ offline không phải fetch qua mạng nội bộ.

Run:

```powershell
pwsh scripts/sync_fixtures.ps1
```

- [ ] **Step 5: Test so byte hai bản**

`tests/test_services/test_fixtures.py` đọc cả hai đường dẫn và so `bytes`. Test này là lý do bản sao vẫn được coi là một nguồn sự thật — bỏ nó thì hai bản sẽ lệch đúng vào ngày ai đó sửa một bên.

Run:

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_fixtures.py -q
```

Expected: xanh; sửa tay `frontend/src/lib/fixtures/poi.json` thì test đỏ.

---

### Task 2: `plan.ready` mang `steps[]`

**Files:**
- Modify: `src/services/ivi_events.py`
- Modify: `docs/api_spec.md`
- Modify: `frontend/src/lib/services/turn/types.ts`
- Modify: `frontend/src/lib/services/turn/real.ts`
- Modify: `frontend/src/lib/services/turn/mock.ts`
- Test: `tests/test_services/test_ivi_events.py`, `frontend/src/lib/services/turn/mock.test.ts`

**Interfaces:**
- Produces: `plan.ready.payload.steps = [{step_id, tool, domain, args}]`.
- Consumed by: Task 6.

> ⚠️ `src/services/ivi_events.py` là vùng agent/HITL của **Nhân** — báo Nhân trước khi mở PR.

- [ ] **Step 1: Thêm `steps` vào `_emit_plan_ready`**

Trong `src/services/ivi_events.py:276-306`, thêm vào dict payload:

```python
"steps": [
    {"step_id": s.step_id, "tool": s.tool, "domain": get_spec(s.tool).domain, "args": s.args}
    for s in plan.steps
],
```

`get_spec` lấy từ `src.services.tool_registry`. **Không** đổi bốn trường sẵn có, và **không** đổi `summary`.

- [ ] **Step 2: Cập nhật bảng allowlist trong `docs/api_spec.md`**

Dòng `plan.ready` (`api_spec.md:574`) thêm `steps:array` với shape từng phần tử. Giữ `schema_version` ở `1.0` — lý do ở §3 của spec: không có validator runtime nào từ chối trường lạ ở chiều ra (`src/api/ws.py:69` chỉ allowlist chiều vào), và chưa có client nào phát hành ngoài repo này.

- [ ] **Step 3: Cập nhật kiểu và parser ở FE**

`types.ts:220-226` thêm `steps: { stepId: string; tool: string; domain: string | null; args: Record<string, unknown> }[]`. `real.ts:240-248` map `p.steps` sang camelCase. `mock.ts` phát `steps` cho đúng mọi lượt điều khiển.

- [ ] **Step 4: Test hai phía**

BE: `plan.ready` của một plan hai bước có đúng hai phần tử, đúng thứ tự, `domain` khớp `get_spec`. FE: `mock.test.ts` khoá shape mới.

Run:

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_services/test_ivi_events.py -q
```

```powershell
cd frontend; npm run test
```

---

### Task 3: Router đọc fixture POI và nới matcher dẫn đường

**Files:**
- Modify: `src/agents/router.py`
- Modify: `src/agents/graph.py`
- Test: `tests/test_agents/test_router.py`

**Interfaces:**
- Consumes: `load_poi_fixture()` từ Task 1.
- Produces: `set_navigation` trỏ tới 5 id thay vì 3, và guard `poi_not_in_fixture` lần đầu chạy thật ở runtime.

- [ ] **Step 1: Truyền fixture vào seam đã có**

`src/agents/graph.py:311` hiện là `DeterministicControlRouter()` không tham số. Đổi thành khởi tạo với `poi_fixture=load_poi_fixture()`. Seam `router.py:297-298` đã có sẵn từ trước — **không** viết seam mới.

- [ ] **Step 2: Thay ba `if` hard-code bằng bảng alias**

`router.py:935-940` hiện là ba `if` chuỗi cứng. Dựng bảng `alias -> id` từ fixture trong `__init__`, tra bảng trong `_match_navigation`. Alias dài khớp trước alias ngắn, để `"cà phê bình minh"` không bị `"cà phê"` nuốt.

- [ ] **Step 3: Nới động từ mở đầu**

`router.py:929` hiện đòi đúng chuỗi `"dẫn đường"`, nên *"tìm đường đến Highlands"* rơi xuống mặc định và đi tra sổ tay (ADR-011). Thêm `tìm đường`, `đưa tôi tới`, `đi tới` vào cùng bước đó — **không** chèn bước mới vào `_match`.

> ⚠️ **Luật này rất dễ bắt quá rộng — đúng lỗi vừa bị bắt ở review #168.** Comment trong `router.py` ghi lại: bản đầu của luật áp suất lốp chỉ đòi "có ý áp suất" + "có ý lốp", và @thanhpro82 chỉ ra nó cướp năm loại câu khác khỏi nhánh sổ tay; phải thêm vế thứ ba (câu phải hỏi con số) mới đạt.
>
> `"đi tới"` trần sẽ bắt *"đi tới đâu thì hết pin"* — một câu tra sổ tay. Neo động từ vào **danh từ đích**: sau động từ phải có alias POI hoặc từ chỉ địa điểm, không chỉ có động từ. Viết case âm cho đúng những câu đó **trước** khi mở PR.

- [ ] **Step 4: Test**

Giữ nguyên `test_router.py:900-903` (ba id cũ). Thêm: hai id mới; ba động từ mới; câu có động từ nhưng không khớp alias vẫn `clarify`/`unknown_local_destination`; và **một test chạy qua `graph`** chứng minh `poi_not_in_fixture` kích hoạt được ở runtime — `test_router.py:924` chỉ dựng router trực tiếp nên không chứng minh điều đó.

Run:

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_router.py -q
```

---

### Task 4: `open_app` — tool cục bộ, S1 khi ở P và S3 khi không

**Files:**
- Create: `docs/adr/ADR-023-open-app-va-chan-app-video-khi-xe-chay.md`
- Modify: `src/services/tool_registry.py`
- Modify: `src/agents/policy.py`
- Modify: `src/agents/nodes/execute.py`
- Modify: `src/agents/router.py`
- Modify: `src/agents/nodes/compose.py` (`describe_step`)
- Modify: `docs/api_spec.md`, `docs/coverage_matrix.md`
- Test: `tests/test_agents/test_tools.py`, `tests/test_agents/test_policy.py`, `tests/test_agents/test_router.py`, `tests/test_agents/test_hitl_safety.py`

**Interfaces:**
- Produces: tool `open_app`, args `{app: "youtube"|"tiktok"|"spotify"}`, `domain=None`.
- Consumed by: Task 6 (FE ánh xạ `tool == "open_app"` + `args.app` → view).

> ✅ **Đã được duyệt** — @thanhpro82 (PM/PO) gật trên issue #172 ngày 2026-08-19: P0 đi từ 15 lên 16 tool, giữ 9 domain; enum đóng ba app; dùng lại `is_stationary`. Task này bỏ chặn, code được ngay.
>
> Anh ấy thêm **một ràng buộc không có trong ADR bản đầu**: khi không stationary, lệnh mở video **bị chặn S3 và không được dùng HITL để override**. Cấu trúc hiện tại đã đúng thế (`safety_node` xét S3 trước `requires_approval`), nhưng phải có test khoá lại — xem Step 7.

- [ ] **Step 1: Viết ADR-023**

Nội dung tối thiểu: vì sao `open_app` không phải lệnh xe (không domain, không actuator, không MQTT); vì sao enum đóng ba app; vì sao dùng lại predicate `is_stationary` (`speed_kph == 0 && gear == "P"`) thay vì một ngưỡng tốc độ mới — ngành khoá video theo số P, và `docs/VIVI_API_Spec.md` §`speed_kph > 5` vẫn **không** được cài theo ADR-010.

- [ ] **Step 2: Đăng ký tool**

`src/services/tool_registry.py`: thêm `OpenAppArgs` với `app: Literal["youtube","tiktok","spotify"]`, và

```python
ToolSpec("open_app", None, "S1", OpenAppArgs, requires_stationary=True)
```

- [ ] **Step 3: Phân loại an toàn**

`src/agents/policy.py`: thêm `_STATIONARY_ONLY_S1_TOOLS = {"open_app"}` và nhánh `return "S1" if is_stationary(snapshot) else "S3"`. **Không** thêm `open_app` vào `_S0_TOOLS` — S0 là chỉ đọc, và `open_app` làm một việc.

- [ ] **Step 4: Seam tool cục bộ trong `execute_node`**

`src/agents/nodes/execute.py`: trước khi gọi `gateway.execute` (`execute.py:59`), rẽ nhánh cho bước có `get_spec(step.tool).domain is None`:

```python
# Tool cục bộ của IVI: không có gì trên xe đổi, nên không dựng VehicleCommand.
# observed_state_version giữ nguyên expected — cùng cách _skipped làm ở :56.
```

Dựng `ToolResult(status="completed", before={}, after={}, observed_state_version=expected_version, error_code=None)` rồi `completed.add(step.step_id)`.

**Không** đưa `open_app` vào simulator: làm thế là đẻ một domain MQTT cho thứ không phải trạng thái xe, hỏng ADR-013.

- [ ] **Step 5: Luật router**

`_match` thêm một bước **trước** nhánh mặc định rơi về tra sổ tay: động từ `mở`/`bật`/`vào` + tên app trong enum → `open_app`. Không có tên app thì **không** khớp — giữ nguyên hành vi hiện tại, không đoán.

Vị trí chèn phải xét bước `tire_pressure_query` mới (`router.py:329-341`) và `is_information_question` ngay sau nó: *"mở YouTube"* không phải câu hỏi nên nó thuộc nhóm luật điều khiển, đứng **sau** hai bước đó.

> ⚠️ **Cùng bẫy "bắt quá rộng" như Task 3.** `mở/bật/vào + tên app` sẽ bắt cả *"mở YouTube xem hướng dẫn thay lốp"*, mà ý người nói là tra sổ tay. Yêu cầu tên app đứng ở cuối cụm, hoặc không có mệnh đề mục đích theo sau; và viết case âm cho đúng câu đó. Review #168 cho thấy đây là chỗ PR sẽ bị chặn nếu làm hớ.

- [ ] **Step 6: `describe_step` cho tool mới**

`src/agents/nodes/compose.py:154` phải sinh cụm động từ cho `open_app` (ví dụ *"mở YouTube"*), vì `summary` của `plan.ready` và `prompt_text` của approval đều ghép từ nó.

- [ ] **Step 7: Test**

- `test_tools.py`: args hợp lệ / app ngoài enum bị từ chối ở tầng validate (**không** phải S3).
- `test_policy.py`: `speed_kph=0, gear="P"` → `S1`; `speed_kph=45` → `S3`; `speed_kph=0, gear="D"` → `S3`.
- `test_router.py`: ba câu mở app khớp; *"mở app"* không có tên → không khớp.
- Test `execute_node`: bước `domain=None` **không** gọi `gateway.execute` (dùng gateway giả đếm lượt gọi).
- **Test ràng buộc PM:** `open_app` ở `speed_kph=45` phải ra `action.blocked` và **không** sinh `approval.required` — S3 không được biến thành hộp thoại phê duyệt.

Run:

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_agents -q
```

- [ ] **Step 8: Cập nhật `coverage_matrix.md` và `api_spec.md`**

`coverage_matrix.md`: **16 tool / 9 domain** — số domain **không** tăng vì `open_app` không có domain; số nhóm lệnh thoại quy ước vẫn 6/11.

---

### Task 5: Playlist CC0 đọc từ fixture

**Files:**
- Modify: `src/vehicle_sim/state.py`
- Create: `frontend/public/media/LICENSE.md`
- Test: `tests/test_vehicle/` (test playlist)

**Interfaces:**
- Consumes: `load_media_fixture()` từ Task 1.
- Produces: `DEFAULT_PLAYLIST` 5–6 tên, khớp từng byte với `name` trong fixture.

- [ ] **Step 1: `DEFAULT_PLAYLIST` đọc từ fixture**

`src/vehicle_sim/state.py:55-60`: thay tuple viết cứng bằng tuple sinh từ `load_media_fixture()`. `_step_track` xoay vòng theo `len(self._playlist)` nên **không cần sửa logic** để đi từ 3 lên 6 bài.

- [ ] **Step 2: `LICENSE.md` cho từng file nhạc và ảnh bìa**

Ghi nguồn + giấy phép từng file. Đây là điều kiện của việc host mp3 trong repo — xem §6 của spec.

- [ ] **Step 3: Test**

`DEFAULT_PLAYLIST` bằng đúng danh sách `name` trong fixture, đúng thứ tự; `next` × N quay về bài đầu.

Run:

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_vehicle -q
```

---

### Task 6: FE — ánh xạ `domain`/`tool` → view, kích hoạt trên `tool.result`

**Files:**
- Create: `frontend/src/lib/ivi/viewMapping.ts`
- Create: `frontend/src/lib/ivi/viewMapping.test.ts`
- Create: `frontend/src/lib/ivi/useAutoViewSwitch.ts`
- Create: `frontend/src/lib/ivi/useAutoViewSwitch.test.ts`
- Modify: `frontend/src/components/ivi/DriverShellProvider.tsx` — **chỉ 2-3 dòng**

**Interfaces:**
- Consumes: `plan.ready.steps` (Task 2), `tool.result` (đã có).
- Produces: `setActiveView` tự động.

> ⚠️ **Rủi ro xung đột merge, và nó quyết định cách chia file ở task này.**
> Nhánh `origin/feat/vivi-browser-wake-word` (Nguyễn Tuấn Thành, 92 file, +15.735 dòng,
> **chưa merge**) sửa `DriverShellProvider.tsx` **+257 dòng**, cùng vùng xử lý event mà
> task này cần chạm. Nó cũng chạm `HomeView.tsx`, `Dock.tsx`, `turn/real.ts`, `turn/mock.ts`,
> và `turn/types.ts` — nhưng phần `types.ts` của nó nằm ở vùng `TurnService`
> (`sendVoice(audio, options)`), khác vùng `plan.ready` của Task 2, nên Task 2 gần như
> không đụng.
>
> **Vì thế toàn bộ logic hai nhịp phải nằm trong `useAutoViewSwitch.ts`, không nhồi vào
> `DriverShellProvider.tsx`.** Provider chỉ gọi hook và truyền `setActiveView` vào. Diff
> ~3 dòng thì merge kiểu nào cũng không va; nhồi một khối 40 dòng vào giữa provider thì
> ai merge sau cũng phải giải xung đột tay trên một file vừa bị viết lại 257 dòng.
>
> **Thứ tự nên chốt với Thành:** nhánh wake-word vào `develop` trước, task này rebase lên.
> Ngược lại là bắt anh ấy rebase 92 file.

- [ ] **Step 1: Hàm ánh xạ thuần**

`viewForStep(step) -> ViewName | null`:

```
hvac | seat | windows | doors | lights | trunk   → "vehicle"
media                                            → "music"
navigation                                       → "map"
tool "open_app" + args.app                       → "youtube" | "tiktok" | "spotify"
mọi thứ khác                                     → null
```

Bảng này sống **hoàn toàn ở FE**. Backend không biết nó tồn tại.

- [ ] **Step 2: Hai nhịp, đặt trong `useAutoViewSwitch.ts`**

1. `plan.ready` → lưu `steps` vào map theo `stepId`. **Không** đổi màn.
2. `tool.result` với `status === "completed"` → tra `stepId` → `viewForStep` → `setActiveView`.

Plan nhiều bước: đổi màn theo bước completed **đầu tiên** có ánh xạ, để câu ghép *"bật điều hòa rồi mở nhạc"* dừng ở `vehicle` thay vì nháy hai màn. Bước không ánh xạ được thì im lặng, không lỗi.

Hook nhận `setActiveView` làm tham số và trả về một hàm xử lý event, để nó test được **không cần render provider** — và để diff trong `DriverShellProvider.tsx` giữ ở mức 2-3 dòng vì lý do xung đột merge ở trên.

- [ ] **Step 2b: Nối hook vào provider**

`DriverShellProvider.tsx` chỉ thêm: gọi `useAutoViewSwitch(setActiveView)` và chuyển event vào hàm nó trả về, tại đúng chỗ provider đã xử lý event WS. **Không** thêm `useState`/`useRef` mới vào provider — state của hai nhịp thuộc về hook.

- [ ] **Step 3: Test — cả nhánh chặn**

- `plan.ready` một mình **không** đổi màn.
- `tool.result(completed)` mới đổi màn, đúng view cho từng domain.
- **Lượt bị chặn**: `plan.ready` có step `open_app` rồi `action.blocked`, không có `tool.result` → màn **không** đổi. Đây là test chứng minh luật an toàn còn hiệu lực; đừng bỏ.
- Lượt HITL: chỉ đổi màn sau khi có `tool.result` hậu phê duyệt.

Run:

```powershell
cd frontend; npm run test
```

---

### Task 7: FE — bản đồ đọc fixture, bỏ route hard-code

**Files:**
- Modify: `frontend/src/components/ivi/MapView.tsx`
- Modify: `frontend/src/components/ivi/LeafletMap.tsx`

- [ ] **Step 1: Bỏ chuỗi hard-code**

`MapView.tsx:33-34` đang cứng `"12 phút"` và `"3.4 km · Nguyễn Trãi → Cầu Giấy"`. Đọc `eta_min` / `distance_km` / `name` từ fixture, tra theo `vehicleState.navigation.destination_id`.

- [ ] **Step 2: Vẽ polyline**

`LeafletMap.tsx` vẽ `polyline` của POI đang được dẫn đường; `navigation` rỗng thì không vẽ.

- [ ] **Step 3: Test** — `destination_id` không có trong fixture thì không crash, hiện trạng thái rỗng.

---

### Task 8: FE — nhạc cục bộ và chế độ demo offline

**Files:**
- Create: `frontend/src/lib/assets.ts`
- Modify: `frontend/src/components/ivi/MusicView.tsx`
- Modify: `frontend/src/components/ivi/YoutubeView.tsx`, `SpotifyView.tsx`, `TiktokView.tsx`
- Create: `frontend/public/media/` (nhạc + ảnh bìa CC0), `frontend/public/map/` (ảnh nền bản đồ)

- [ ] **Step 1: `assetUrl()`**

```ts
const OFFLINE = process.env.NEXT_PUBLIC_OFFLINE_ASSETS === "true";
export function assetUrl(local: string, remote: string): string {
  return OFFLINE ? local : remote;
}
```

Cờ tắt → hành vi y hệt hôm nay. Không component nào biết cờ tồn tại.

- [ ] **Step 2: `MusicView` đọc fixture**

Xoá `TRACK_SRC_BY_NAME` và `TRACK_BG_SEED` (`MusicView.tsx`) — hai bảng viết tay này chính là bug: tên của chúng không khớp một tên nào trong playlist backend, nên real mode luôn phát đúng một file. Thay bằng tra fixture theo `name`, mọi URL đi qua `assetUrl()`.

- [ ] **Step 3: Nền bản đồ offline**

Cờ bật → `L.ImageOverlay` với một ảnh raster tĩnh thay cho tile CARTO. **Không** tải hàng loạt tile: ToS của CARTO (`LeafletMap.tsx:9`) và OSM đều cấm.

- [ ] **Step 4: Ba app — ảnh tĩnh + nhãn "cần mạng"**

Cờ bật → ba view hiện placeholder thay vì iframe. Ba tile ở `HomeView.tsx:28-30` **giữ nguyên**, không ẩn.

- [ ] **Step 5: Kiểm tra bằng tay, rút mạng**

```powershell
cd frontend; $env:NEXT_PUBLIC_OFFLINE_ASSETS="true"; npm run dev
```

Expected: tắt wifi vẫn phát được nhạc, vẫn thấy nền bản đồ và lộ trình; ba app hiện nhãn "cần mạng" thay vì trắng trơn.

---

### Task 9: Tài liệu — hạ lời hứa offline và khai ranh giới ba app

**Files:**
- Modify: `docs/release/demo-3-phut.md`
- Modify: `docs/demo_runbook.md`
- Modify: `WORKLOG.md`, `JOURNAL.md`

> ⚠️ **`mvp-demo-checklist.md` vừa bị sửa ngày 18/08** (#168): thêm **PRE-7** (phải khai `trim × battery` trước khi demo), **R-5** và **R-6** (áp suất lốp, và ca fail-closed khi xoá cấu hình). Pull trước khi sửa tài liệu demo, đừng đè lên phần mới đó. Kịch bản UAT cũng dài thêm hai case — nếu tuyến 180 giây phải nhận thêm gì thì nói ra, đừng để `demo-3-phut.md` và checklist trôi khác nhau.

- [ ] **Step 1: Sửa câu mở đầu demo**

`demo-3-phut.md` màn 0:00–0:15 đang nói *"chạy hoàn toàn offline… không gọi ra mạng"* trong khi FE phụ thuộc sáu host ngoài lúc chạy. Câu đúng: **lõi xử lý** offline; **phần trang trí** dùng tài nguyên web, trừ khi bật chế độ demo.

Chỉ được nâng lại lời hứa "hoàn toàn offline" **kèm bằng chứng** (rút mạng, quay màn hình), không nâng bằng lời — kỷ luật status của `README.md`.

- [ ] **Step 2: Thêm dòng ranh giới ba app**

Bảng "Ranh giới không được hứa" (`demo_runbook.md` §3): nội dung ba app là iframe cần mạng; chế độ demo chỉ hiện ảnh tĩnh.

- [ ] **Step 3: `WORKLOG.md` và `JOURNAL.md`** theo đúng định dạng bảng/mục đang có.

---

### Task 10: Chạy trọn bộ và đối chiếu

- [ ] **Step 1: Toàn bộ suite BE**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: không kém mốc `1356 passed, 17 skipped` (snapshot `develop` @ `4fb40fd`). Số skip khác 17 **không** mặc nhiên là hồi quy — chạy lại với `-rs` xem *tests nào* skip trước khi kết luận.

- [ ] **Step 2: FE**

```powershell
cd frontend; npm run test
```

```powershell
cd frontend; npm run lint
```

- [ ] **Step 3: Lint BE**

```powershell
ruff check src/ tests/
```

```powershell
ruff format src/ tests/
```

- [ ] **Step 4: Đối chiếu bằng tay ở real mode**

Real mode cần cả ba cờ `NEXT_PUBLIC_USE_MOCK_TURN` / `NEXT_PUBLIC_USE_MOCK_SESSION` / `NEXT_PUBLIC_USE_MOCK_ENGINEER` đặt `false` — ảnh chụp màn hình không chứng minh gì về backend nếu ba cờ đó còn bật.

Bốn câu phải thử bằng mic, không phải bằng gõ chữ:

| Câu | Kỳ vọng |
|---|---|
| *"Bật điều hòa"* | chuyển sang màn điều khiển |
| *"Mở nhạc"* | chuyển sang màn nhạc, phát đúng bài đang hiện tên |
| *"Tìm đường đến Highlands"* | chuyển sang bản đồ, vẽ lộ trình, ETA đúng fixture |
| *"Mở YouTube"* khi xe chạy 45 km/h | **không** đổi màn, hiện lý do bị chặn |

Câu cuối là câu quan trọng nhất: nó chứng minh chuyển màn bám `tool.result` chứ không bám `plan.ready`.

## Issue đã mở

| Issue | Tiêu đề | Owner | Task |
|---|---|---|---|
| [#169](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/169) | fixture POI/media dùng chung cho router, simulator và IVI | Sơn | 1 |
| [#170](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/170) | `plan.ready` mang `steps[{step_id,tool,domain,args}]` | Sơn | 2 |
| [#171](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/171) | router đọc POI fixture và nới matcher dẫn đường | Sơn | 3 |
| [#172](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/172) | `open_app` — nới bề mặt P0, S3 khi xe không ở P | Sơn | 4 — **cần Thành duyệt ADR-023** |
| [#173](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/173) | tên bài MusicView không khớp playlist backend | Giáp + Sơn | 5 |
| [#174](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/174) | tự chuyển màn theo `tool.result` | Giáp | 6 |
| [#175](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/175) | bản đồ đọc POI fixture, vẽ polyline | Giáp | 7 |
| [#176](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/176) | chế độ demo offline; hạ câu "hoàn toàn offline" | Giáp + Sơn | 8, 9 |

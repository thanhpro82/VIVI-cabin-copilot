# Routine Preview UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khi người dùng gõ hoặc nói “xem trước Routine X”, IVI mở màn Routines, cuộn tới đúng Routine và làm nổi thẻ cùng danh sách bước do backend cung cấp, nhưng tuyệt đối không chạy Routine.

**Architecture:** `routine_node` dựng một `routine_preview` có cấu trúc từ Routine đã phân giải. `assistant_response_payload` là điểm nối duy nhất đưa cấu trúc đó ra cả WebSocket và REST; frontend ánh xạ payload qua một validator dùng chung, Provider nhận kết quả từ cả hai kênh theo `turnId`, còn `RoutinesView` chỉ chịu trách nhiệm cuộn/làm nổi thẻ hoặc render thẻ dự phòng khi danh sách REST chưa có Routine đó.

**Tech Stack:** Python 3.11, LangGraph state, FastAPI/Pydantic, pytest; Next.js/React 19, TypeScript, Vitest, Testing Library, Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-08-31-routine-preview-ui-design.md`

## Global Constraints

- Preview không được gọi executor hoặc tạo `routine_execution`.
- REST và WebSocket phải mang cùng cấu trúc `routine_preview`.
- Cả lệnh chữ và lệnh giọng nói phải đi tới cùng hành vi UI.
- Payload thiếu/sai hình dạng phải fail-safe: không đổi màn, không crash.
- Cùng một `turnId` tới từ REST và WebSocket chỉ được áp dụng một lần.
- Highlight tự hết sau 30 giây; không thêm màn chi tiết mới, không đọc TTS toàn bộ bước, không thêm `bo_buoc`, không đổi chính sách an toàn.

---

### Task 1: Dựng preview có cấu trúc trong Agent

**Files:**
- Modify: `src/agents/routines.py`
- Modify: `src/agents/state.py`
- Modify: `src/agents/nodes/routine_node.py`
- Modify: `src/agents/nodes/compose.py`
- Test: `tests/test_agents/test_routine_node.py`
- Test: `tests/test_agents/test_routines_adapter.py`

**Interfaces:**
- Produces: `mo_ta_buoc_routine(step: dict) -> str` và state field `routine_preview: dict[str, Any]` có dạng `{routine_id, routine_name, steps: [{index, action, description}]}`.
- Consumes: `describe_step(tool, args)` cho action thông thường; navigation dùng nhãn `home -> Nhà`, `office -> Cơ quan` mà không cần resolve POI.

- [ ] **Step 1: Viết test thất bại cho serializer và nhánh preview**

```python
def test_mo_ta_buoc_routine_khong_can_resolve_navigation():
    assert mo_ta_buoc_routine({"action": "navigation", "destination": "home"}) == "dẫn đường tới Nhà"

async def test_xem_truoc_tra_cau_truc_ten_va_cac_buoc(...):
    out = await node(state_xem_truoc)
    assert out["routine_preview"] == {
        "routine_id": "rtn_ve_nha",
        "routine_name": "Về nhà",
        "steps": [
            {"index": 0, "action": "navigation", "description": "dẫn đường tới Nhà"},
            {"index": 1, "action": "hvac_power", "description": "bật điều hòa"},
        ],
    }
    assert "routine_execution_id" not in out
```

- [ ] **Step 2: Chạy test để xác nhận RED**

Run: `python -m pytest tests/test_agents/test_routines_adapter.py tests/test_agents/test_routine_node.py -q`

Expected: FAIL vì `mo_ta_buoc_routine`/`routine_preview` chưa tồn tại.

- [ ] **Step 3: Viết implementation tối thiểu**

```python
def mo_ta_buoc_routine(step: dict) -> str:
    if step.get("action") == "navigation":
        return f"dẫn đường tới { {'home': 'Nhà', 'office': 'Cơ quan'}.get(str(step.get('destination')), step.get('destination')) }"
    tool, args = _DICH[str(step["action"])](step)
    from src.agents.nodes.compose import describe_step
    return describe_step(tool, args)
```

Trong `routine_node`, giữ object Routine khớp tên thay vì chỉ lấy ID, rồi dựng `routine_preview` từ `routine.steps`. Trong `AgentState`, khai báo field để LangGraph không loại nó. Trong compose, dùng tên Routine trong câu: `Đây là các bước của Routine Về nhà. Bạn có muốn tôi chạy không?`.

- [ ] **Step 4: Chạy lại test và commit**

Run: `python -m pytest tests/test_agents/test_routines_adapter.py tests/test_agents/test_routine_node.py -q`

Expected: PASS.

```bash
git add src/agents/routines.py src/agents/state.py src/agents/nodes/routine_node.py src/agents/nodes/compose.py tests/test_agents/test_routines_adapter.py tests/test_agents/test_routine_node.py
git commit -m "feat(agent): trả preview Routine có cấu trúc"
```

### Task 2: Phơi preview qua REST và WebSocket

**Files:**
- Modify: `src/services/ivi_events.py`
- Modify: `src/models/api.py`
- Modify: `src/api/turns.py`
- Test: `tests/test_services/test_ivi_events.py`
- Test: `tests/test_api/test_turns_text.py`
- Test: `tests/test_api/test_ws_ivi.py`

**Interfaces:**
- Consumes: `result["routine_preview"]` từ Task 1.
- Produces: `RoutinePreviewStepData`, `RoutinePreviewData`, `TextTurnData.routine_preview: RoutinePreviewData | None`; wire field `assistant.response.routine_preview` có cùng snake_case object hoặc `null`.

- [ ] **Step 1: Viết test RED cho payload chung**

```python
def test_assistant_response_payload_giu_nguyen_routine_preview():
    preview = {"routine_id": "rtn_1", "routine_name": "Về nhà", "steps": [{"index": 0, "action": "navigation", "description": "dẫn đường tới Nhà"}]}
    assert assistant_response_payload({"response_text": "Xem trước", "routine_preview": preview})["routine_preview"] == preview
```

Thêm assertion ở test REST rằng `data.routine_preview` đúng object trên, và test lifecycle rằng event `assistant.response` chứa cùng object.

- [ ] **Step 2: Chạy test để xác nhận RED**

Run: `python -m pytest tests/test_services/test_ivi_events.py tests/test_api/test_turns_text.py tests/test_api/test_ws_ivi.py -q`

Expected: FAIL vì wire/model chưa có field.

- [ ] **Step 3: Thêm model và nối qua điểm chung**

```python
class RoutinePreviewStepData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0)
    action: str
    description: str

class RoutinePreviewData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routine_id: str
    routine_name: str
    steps: list[RoutinePreviewStepData]
```

`assistant_response_payload` luôn trả key `routine_preview` (`dict` hợp lệ hoặc `None`). `_build_text_turn_response` truyền key này vào `TextTurnData`; lifecycle đã dùng helper chung nên WebSocket nhận tự động. Thêm test non-Routine để khóa `routine_preview is None`.

- [ ] **Step 4: Chạy lại test và commit**

Run: `python -m pytest tests/test_services/test_ivi_events.py tests/test_api/test_turns_text.py tests/test_api/test_ws_ivi.py -q`

Expected: PASS.

```bash
git add src/services/ivi_events.py src/models/api.py src/api/turns.py tests/test_services/test_ivi_events.py tests/test_api/test_turns_text.py tests/test_api/test_ws_ivi.py
git commit -m "feat(api): phát Routine preview qua REST và WebSocket"
```

### Task 3: Ánh xạ payload frontend một lần cho cả REST/WS

**Files:**
- Modify: `frontend/src/lib/services/turn/types.ts`
- Modify: `frontend/src/lib/services/turn/real.ts`
- Create: `frontend/src/lib/services/turn/real.routinePreview.test.ts`

**Interfaces:**
- Produces: `RoutinePreview`, `RoutinePreviewStep`, `TurnResult.routinePreview: RoutinePreview | null`, và kết quả `sendText` `{turnId, routinePreview?: RoutinePreview | null}`; `sendVoice` giữ nguyên `{turnId}` vì voice nhận preview qua WebSocket.
- Produces: `mapRoutinePreview(raw: unknown): RoutinePreview | null` và mapper `mapTurnResult(raw)` dùng cho cả REST response lẫn `assistant.response`.

- [ ] **Step 1: Viết test RED cho payload hợp lệ/sai và REST mapping**

```ts
expect(mapRoutinePreview(valid)).toEqual({ routineId: "rtn_1", routineName: "Về nhà", steps: [...] });
expect(mapRoutinePreview({ routine_id: "rtn_1", steps: "bad" })).toBeNull();
expect(mapServerEvent(wsEnvelope)?.result.routinePreview?.routineId).toBe("rtn_1");
```

Mock `fetch` cho `sendText` và xác nhận `routinePreview` được map từ `data.routine_preview`.

- [ ] **Step 2: Chạy test để xác nhận RED**

Run: `cd frontend; npx vitest run src/lib/services/turn/real.routinePreview.test.ts`

Expected: FAIL vì type/mapper chưa tồn tại.

- [ ] **Step 3: Implement validator/mapper dùng chung**

```ts
export interface RoutinePreviewStep { index: number; action: string; description: string }
export interface RoutinePreview { routineId: string; routineName: string; steps: RoutinePreviewStep[] }

export function mapRoutinePreview(raw: unknown): RoutinePreview | null {
  if (!raw || typeof raw !== "object") return null;
  // kiểm tra id/name là string không rỗng, steps là array và từng step có index nguyên >=0 + string fields
}
```

Tách `mapTurnResult` để WebSocket map citations/outcomes/preview tại một biên. REST text đọc `data.routine_preview` bằng cùng `mapRoutinePreview`. Khi raw preview có mặt nhưng sai contract, helper gọi `console.warn` một lần rồi trả `null`; `sendVoice` không đổi contract.

- [ ] **Step 4: Chạy lại test/typecheck và commit**

Run: `cd frontend; npx vitest run src/lib/services/turn/real.routinePreview.test.ts; npx tsc --noEmit`

Expected: PASS.

```bash
git add frontend/src/lib/services/turn/types.ts frontend/src/lib/services/turn/real.ts frontend/src/lib/services/turn/real.routinePreview.test.ts
git commit -m "feat(fe): ánh xạ Routine preview từ turn response"
```

### Task 4: Provider điều hướng và chống REST/WS áp dụng hai lần

**Files:**
- Modify: `frontend/src/components/ivi/DriverShellProvider.tsx`
- Test: `frontend/src/components/ivi/DriverShellProvider.test.tsx`

**Interfaces:**
- Consumes: `TurnResult.routinePreview` từ Task 3.
- Produces: context field `routinePreview: { turnId: string; preview: RoutinePreview } | null`; helper nội bộ `applyRoutinePreview(turnId, preview)` đổi `activeView` sang `routines` đúng một lần mỗi turn.

- [ ] **Step 1: Viết test RED cho WS, REST và dedupe**

```ts
it("mở Routines khi assistant.response có preview", async () => { ... });
it("lệnh chữ vẫn mở Routines khi REST về trước WS", async () => { ... });
it("cùng turnId qua REST rồi WS chỉ áp dụng một lần", async () => { ... });
it("payload malformed đã map thành null nên không đổi màn", async () => { ... });
```

- [ ] **Step 2: Chạy test để xác nhận RED**

Run: `cd frontend; npx vitest run src/components/ivi/DriverShellProvider.test.tsx`

Expected: FAIL vì context/helper chưa có.

- [ ] **Step 3: Implement một cổng áp dụng preview**

```ts
const routinePreviewTurnIdsRef = useRef<string[]>([]);
const applyRoutinePreview = useCallback((turnId: string, preview: RoutinePreview | null | undefined) => {
  if (!preview || routinePreviewTurnIdsRef.current.includes(turnId)) return;
  routinePreviewTurnIdsRef.current = [...routinePreviewTurnIdsRef.current.slice(-19), turnId];
  setRoutinePreview({ turnId, preview });
  setActiveView("routines");
}, []);
```

Gọi helper trong nhánh `assistant.response`; trong `.then()` của `sendText`, gọi sau `ghiNhanTurnId` với preview REST. `sendVoice` nhận cùng hành vi qua `assistant.response` WebSocket. Không xoá preview ngay khi bắt đầu lượt mới: màn Routines cần giữ dữ liệu đủ 30 giây để render/fallback.

- [ ] **Step 4: Chạy lại test/typecheck và commit**

Run: `cd frontend; npx vitest run src/components/ivi/DriverShellProvider.test.tsx; npx tsc --noEmit`

Expected: PASS.

```bash
git add frontend/src/components/ivi/DriverShellProvider.tsx frontend/src/components/ivi/DriverShellProvider.test.tsx
git commit -m "feat(fe): mở màn Routines từ preview Agent"
```

### Task 5: Cuộn, highlight và fallback card trong RoutinesView

**Files:**
- Modify: `frontend/src/components/ivi/RoutinesView.tsx`
- Modify: `frontend/src/components/ivi/RoutinesView.test.tsx`

**Interfaces:**
- Consumes: `routinePreview` từ Provider.
- Produces: thẻ thật có `data-routine-id`, `scrollIntoView({behavior: "smooth", block: "center"})`, class highlight trong 30 giây; thẻ read-only “Xem trước” khi ID chưa có trong list.

- [ ] **Step 1: Viết test RED cho match, timeout và fallback**

```ts
it("cuộn tới và làm nổi Routine khớp ID", async () => { ...expect(scrollIntoView).toHaveBeenCalledOnce(); });
it("bỏ highlight sau 30 giây", async () => { vi.advanceTimersByTime(30_000); ... });
it("render thẻ preview chỉ đọc khi danh sách chưa có ID", async () => { ... });
```

- [ ] **Step 2: Chạy test để xác nhận RED**

Run: `cd frontend; npx vitest run src/components/ivi/RoutinesView.test.tsx`

Expected: FAIL vì view chưa tiêu thụ preview.

- [ ] **Step 3: Implement UI tối thiểu**

Giữ `Map<string, HTMLLIElement>` ref theo routine ID. Khi `routinePreview` đổi, ép `mode="list"`, bật `highlightedRoutineId`, đợi render rồi cuộn; timer 30 giây chỉ xoá highlight nếu vẫn là cùng ID. Thẻ fallback dùng chính `routinePreview.steps[].description`, không có nút chạy/sửa/xóa.

```tsx
<li
  ref={(node) => { if (node) routineCardRefs.current.set(routine.id, node); }}
  data-routine-id={routine.id}
  className={highlightedRoutineId === routine.id ? "... border-indigo ring-2 ring-indigo/40 ..." : "... border-line ..."}
>
```

- [ ] **Step 4: Chạy lại test/typecheck và commit**

Run: `cd frontend; npx vitest run src/components/ivi/RoutinesView.test.tsx; npx tsc --noEmit`

Expected: PASS.

```bash
git add frontend/src/components/ivi/RoutinesView.tsx frontend/src/components/ivi/RoutinesView.test.tsx
git commit -m "feat(fe): cuộn và làm nổi Routine được xem trước"
```

### Task 6: Cập nhật hợp đồng và kiểm chứng toàn bộ

**Files:**
- Modify: `docs/api_spec.md`

**Interfaces:**
- Documents: optional `routine_preview` trên `assistant.response` và `POST /turns/text.data`, cùng semantics “preview không thực thi”.

- [ ] **Step 1: Cập nhật bảng event/REST contract**

Ghi đúng shape `{routine_id, routine_name, steps:[{index, action, description}]}`; `null` ở mọi outcome khác; client phải bỏ qua payload sai và không được dùng preview làm tín hiệu thực thi.

- [ ] **Step 2: Chạy backend suite liên quan**

Run: `python -m pytest tests/test_agents/test_routines_adapter.py tests/test_agents/test_routine_node.py tests/test_services/test_ivi_events.py tests/test_api/test_turns_text.py tests/test_api/test_ws_ivi.py -q`

Expected: PASS.

- [ ] **Step 3: Chạy toàn bộ frontend suite và lint/typecheck**

Run: `cd frontend; npm test -- --run; npx tsc --noEmit; npm run lint`

Expected: toàn bộ test PASS, TypeScript sạch, lint không có lỗi mới.

- [ ] **Step 4: Chạy full backend suite**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 5: Kiểm tra diff và commit docs**

Run: `git diff --check; git status --short`

Expected: không có whitespace error; chỉ có file thuộc #401.

```bash
git add docs/api_spec.md
git commit -m "docs: mô tả hợp đồng Routine preview"
```

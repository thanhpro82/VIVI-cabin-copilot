# Kiến trúc Frontend — VIVI Cabin Copilot

Nguồn: `HANDOFF_prototype-to-fe.md`, `nghien-cuu-giao-dien-xe-3d.md` (repo cha) cho **hành vi UI/UX**; `docs/api_spec.md` (repo cha, chỉ có trên `develop`) là **nguồn sự thật DUY NHẤT cho endpoint/API thật** — nhóm đã chốt dùng bản này (2026-08-08), KHÔNG dùng `docs/VIVI_API_Spec.md` (bản cũ hơn, endpoint khác hẳn: `/agent/process`, `/vehicle/control`, `/admin/metrics`, WS `/ws/dashboard` — đã bị loại). `_bmad-output/planning-artifacts/PRD.md` vẫn dùng được cho **yêu cầu chức năng/ngưỡng số liệu** (N1, N4-N6...), không dùng cho tên endpoint. `docs/adr/ADR-006` là nguồn sự thật cho mô hình an toàn/HITL (S0-S3).

**Nguyên tắc quan trọng nhất rút ra từ `api_spec.md` (đọc kỹ trước khi code service layer):** P0 chỉ có **đúng 12 interface** (không có route tổng quát kiểu `/agent/process` hay route "set state trực tiếp" nào khác). **Mọi thay đổi trạng thái xe — kể cả bấm nút trên UI — đều phải đi qua `POST /turns/text` hoặc `POST /turns/voice`**, không có đường tắt. Không tự thêm endpoint mới vào mock nếu không có trong 12 interface này.

## 1. Vị trí & lý do

`frontend/` là project Next.js độc lập, tách khỏi `src/` (backend Python). Không có `apps/` hay workspace root `package.json` — đây là quyết định đã chốt (xem lý do đầy đủ trong plan lúc khởi tạo, tóm tắt: repo template AI20K không quy ước sẵn, `.env.example` gợi ý "Frontend (if separate)", `docs/guide/chapter-06.md` dùng ví dụ project con độc lập).

## 2. Theme

1 dark theme duy nhất cho toàn bộ `/login`, `/driver`, `/engineer`. Lý do (đã research automotive HMI guidelines): dark UI giảm chói/phản chiếu kính lái, đỡ mỏi mắt ban đêm — chuẩn ngành của Tesla/VinFast VF8 và các HMI ô tô hiện đại. Không dùng `next-themes`, không toggle. Token duy nhất ở `src/styles/tokens.css` (xem `DESIGN_TOKENS.md`).

## 3. Routes

| Route | Vai trò | PRD ref |
|---|---|---|
| `/login` | Chọn vai trò đăng nhập (Tài xế / Kỹ sư) | AUTH1 |
| `/driver` | IVI Screen — StatusBar, 7 view (Home/VehicleControl/Music/Map/YouTube/Spotify/TikTok), RightPanel (Car3DViewer), Dock, HITL modal, Voice overlay | F1, S1–S4 |
| `/engineer` | Dashboard Kỹ sư — KPI tiles, chart độ trễ, bảng audit log | F2 |

Điều hướng nội bộ trong `/driver` (chuyển giữa 7 view) dùng state, **không** dùng Next.js routing con — giữ cảm giác app native liền mạch như prototype gốc (đã quyết trong HANDOFF mục 4.3, phương án 2).

### 3.1 `/login` — 2 nhánh UX khác nhau cho 2 role (đã thảo luận & chốt)

Giữ đúng cảm giác "2 card, bấm là vào" của prototype gốc, nhưng cả 2 nhánh đều gọi **cùng 1 API thật** `POST /auth/login` (không có cách nào bỏ qua bước này — mọi request sau đó, kể cả `WS /ws/ivi`/`WS /ws/engineer`, đều cần Bearer token, RBAC do server enforce chứ không phải do UI cho xem trang nào — `api_spec.md` dòng 8). Lý do tách 2 nhánh: tài xế có áp lực an toàn/thời gian (không nên gõ password lúc lên xe), kỹ sư ngồi bàn không có áp lực đó và màn hình kỹ sư nhạy cảm hơn (metrics/log nội bộ) nên xác thực thật hợp lý hơn.

```
Card "Tài xế"  → bấm là vào ngay, KHÔNG hiện form
                  → sessionService.loginAsDriver() gọi POST /api/auth/demo-driver
                    (Route Handler Next.js, server-side) — route này đọc
                    DEMO_DRIVER_EMAIL / _PASSWORD (server-only, KHÔNG prefix
                    NEXT_PUBLIC_) rồi tự gọi POST /auth/login thật với BE.
                    Client KHÔNG BAO GIỜ thấy credential demo — nếu dùng
                    NEXT_PUBLIC_* thì Next.js bundle thẳng giá trị vào JS gửi
                    cho trình duyệt, ai xem source cũng lấy được (bị review
                    PR #11 phát hiện, đã sửa). Xem
                    src/app/api/auth/demo-driver/route.ts.
                  → lưu access_token → chuyển /driver

Card "Kỹ sư"   → mở ra form thật (ô email + password)
                  → người dùng tự gõ → sessionService.login(email, password)
                    gọi POST /auth/login với giá trị người dùng nhập
                  → lưu access_token → chuyển /engineer
```

`access_token` (kèm `expires_at`) lưu ở localStorage — vào lại app trong thời hạn token thì bỏ qua `/login`, vào thẳng route theo `role` đã lưu (không bắt đăng nhập lại mỗi lần mở app).

**Phụ thuộc vào BE — cần báo lại nhóm, chưa có sẵn trong tài liệu nào:** BE cần tạo bảng `users` (đã có thiết kế trong `data_model.md` dòng 41, nhưng **chưa implement**, đã kiểm tra `src/`) + seed ít nhất 2 tài khoản demo (1 tài xế, 1 kỹ sư) + cung cấp lại giá trị email/password thật cho FE điền vào env. Việc này **chưa nằm trong file tài liệu gốc nào cả** — cần chủ động hỏi/nhắc BE, không phải việc tự suy ra được từ docs hiện có.

## 4. Service layer — mock ⇄ real, không sửa UI khi swap

```
src/lib/services/
├── session/{types,mock,real}.ts   // login, tạo/giữ session
├── turn/{types,mock,real}.ts      // gửi lệnh (text/voice) + nhận sự kiện qua /ws/ivi — thay cho voice/vehicle riêng lẻ
├── engineer/{types,mock,real}.ts  // metrics, trace list (client-side), /ws/engineer
└── */index.ts   // điểm chọn DUY NHẤT theo NEXT_PUBLIC_USE_MOCK_*
```

Component chỉ import từ `index.ts`. `mock.ts`/`real.ts` implement cùng interface trong `types.ts`, cùng shape lỗi, mock giả lập cả độ trễ (`setTimeout`) để UI loading-state đã đúng từ đầu.

**Đổi so với thiết kế ban đầu:** gộp `voice` + `vehicle` thành 1 domain `turn`, vì cả giọng nói lẫn thao tác điều khiển xe trên UI (bấm nút AC, kéo thanh cửa sổ...) đều đi qua **cùng 1 luồng** `turn → ActionPlan → safety → execute` — không có API riêng cho "voice" và "vehicle control" như thiết kế cũ (dựa trên spec sai). `VehicleControlView`/`Car3DViewer` vẫn nhận `vehicleState` qua props như cũ (đọc từ `GET /vehicle/state` lúc khởi tạo + cập nhật qua sự kiện `state`/`tool.result` trên `/ws/ivi`), chỉ khác là **gửi lệnh** đi qua `turnService.sendText(...)`, không có `vehicleService.setState(...)` độc lập nữa.

### 12 interface P0 thật (theo `docs/api_spec.md` — dùng đúng khi viết `real.ts`, không tự đoán/thêm bớt)

| # | Interface | Dùng ở service nào |
|---:|---|---|
| 1 | `POST /api/v1/auth/login` | `session` |
| 2 | `POST /api/v1/sessions` | `session` |
| 3 | `POST /api/v1/turns/text` | `turn` — **cả lệnh gõ tay lẫn lệnh bấm nút trên UI đều gọi qua đây** |
| 4 | `POST /api/v1/turns/voice` | `turn` — audio, trả `202`, kết quả qua `/ws/ivi` |
| 5 | `POST /api/v1/approvals/{approval_id}/decision` | `turn` — HITL modal gọi khi Đồng ý/Từ chối |
| 6 | `GET /api/v1/vehicle/state` | `turn` — đọc state lúc khởi tạo `/driver` |
| 7 | `GET /api/v1/citations/{citation_id}` | `turn` — xem nguồn trích dẫn RAG |
| 8 | `GET /api/v1/traces/{trace_id}` | `turn` — khôi phục UI sau khi WS mất kết nối |
| 9 | `GET /api/v1/metrics/summary` | `engineer` — khối KPI "Live" |
| 10 | `GET /healthz` | `engineer` — badge trạng thái hệ thống |
| 11 | `WS /ws/ivi` | `turn` — mọi sự kiện realtime của Driver (xem bảng event ở `api_spec.md` mục "Driver server-event allowlist") |
| 12 | `WS /ws/engineer` | `engineer` — sự kiện `state`/`trace`/`metrics`/`health` cho Dashboard |

FE **không** kết nối MQTT trực tiếp — Backend là gateway giữa MQTT và WebSocket cho FE. Topic thật là `v1/vehicles/{id}/state/{domain}` và `v1/vehicles/{id}/state/snapshot`, xem [`docs/mqtt_spec.md`](../../docs/mqtt_spec.md) ở repo cha. (Bản trước ghi `vivi/vehicle/control`/`vivi/vehicle/status` kèm trích dẫn ADR-004 — cả hai đều sai: đó là quy ước cũ của Họ A, và ADR-004 không hề chứa 2 topic đó.)

### Một method NGOÀI bảng trên: `turnService.setSimSpeed()` (issue #183, ADR-024)

`POST /api/v1/sim/motion` **không** thuộc bề mặt P0 và không làm bảng trên dài thêm một dòng nào — nó `include_in_schema=False` ở backend, cùng khuôn với `/agent/process`. Đây là **bàn đạo diễn kịch bản demo**: đặt tốc độ cho xe ảo để dựng được ca S3 ("mở cửa khi xe đang chạy"), thứ trước đây chỉ gõ được vào stdin của `python -m src.vehicle_sim`.

Ba điều phải giữ khi sửa `SpeedDebugDrawer`/`turn/real.ts`:

- **Không phải lệnh điều khiển xe.** Nó không đi qua `turn → ActionPlan → safety → execute`, không sinh lượt nào, không phát event nào trên `/ws/ivi`. Vì thế bảng phải **tự poll** `getVehicleState()` — không có gì đẩy tin cho nó cả.
- **404 là trạng thái bình thường.** Cờ `SIM_CONTROL_ENABLED` mặc định tắt, và backend chưa có PR #206 thì route không tồn tại. Cả hai ca đều ra `SIM_HARNESS_ABSENT_CODE`, và UI phải lùi về hướng dẫn gõ console chứ không hiện lỗi.
- **202, không phải 200.** Xe đổi state bất đồng bộ qua MQTT nên `getVehicleState()` ngay sau đó chưa chắc thấy giá trị mới. Đừng đọc thân trả về như state xe.

### An toàn/HITL (ADR-006 — bắt buộc tuân theo khi build `turn`/HITL modal)

4 cấp: `S0` (đọc, không cần duyệt) → `S1` (AC/nhạc/nav — không cần duyệt) → `S2` (cửa/cửa sổ/ghế khi xe đang chạy — **cần duyệt**, tối đa **1 approval đang chờ/session**, timeout theo `expires_at` trong sự kiện `approval.required`) → `S3` (chặn hẳn, không thể duyệt). Khi có 1 approval đang chờ mà có thêm lệnh S2 khác → BE trả `APPROVAL_ALREADY_PENDING`, FE hiển thị như 1 câu trả lời bình thường, **không** mở thêm HITL modal thứ 2.

### Domain `routines` — CHỈ mock, chưa có backend (issue #271, epic #270 Routines MVP)

```
src/lib/services/routines/{types,mock}.ts   // KHÔNG có real.ts — chưa có API backend
└── index.ts   // xuất thẳng mock, không đọc NEXT_PUBLIC_USE_MOCK_ROUTINES (chưa cần vì chưa có real)
```

Khác 3 domain ở bảng 12 interface trên: **không map tới bất kỳ interface P0 nào** — Routine hiện chỉ sống trong `localStorage` trình duyệt (khoá theo `userId`), không qua backend. #272 (BE, sở hữu bởi hason0510) đóng phần lưu trữ qua restart + kiểm tra ownership theo user thật; khi đó xong mới thêm `real.ts` và đổi `index.ts` sang đúng khuôn `NEXT_PUBLIC_USE_MOCK_*` như 3 domain kia. Action trong `RoutineStep` đặt tên khớp tool canonical của backend (`src/services/tool_registry.py`, xem `routines/types.ts`) để không phải đổi tên khi #274 (preview/chạy bằng voice) nối vào.

### V3 Text Fallback (PRD)

Không cần thiết kế riêng — `turnService.sendText(text)` (interface #3) chính là cơ chế fallback khi mic lỗi/ồn quá, dùng chung code path với lệnh do UI tự dựng câu.

## 5. Xe 3D

Theo `nghien-cuu-giao-dien-xe-3d.md` + HANDOFF mục 2 — phương án B, `@google/model-viewer` (đã cài) + model GLTF thật ở `public/assets/models/sedan-realistic/` (copy từ `assets/sedan-realistic/` ở repo cha, giữ dòng credit CC-BY bắt buộc). `Car3DViewer.tsx` (`'use client'`) nhận `vehicleState` qua props, ánh xạ trạng thái → camera-orbit/exposure/glow, KHÔNG animate mesh (model không tách mesh cửa/kính).

## 6. Engineer Dashboard

### 6.1 Quyết định phạm vi P0 (đã chốt với nhóm — KHÔNG phải gap cần xin thêm API)

`api_spec.md` không có endpoint liệt kê/lọc lịch sử trace (`GET /traces/{id}` chỉ lấy 1 trace theo ID, không có `GET /traces?filter=...`). Nhóm đã chốt: **P0 Engineer Dashboard chỉ hiển thị log realtime/gần đây từ `WS /ws/engineer`**, không phải historical log viewer; list/filter/pagination server-side để dành P1. Hệ quả thiết kế cụ thể:

- **`LogsTable`** tích luỹ sự kiện `trace` nhận qua `/ws/engineer` vào 1 mảng trong state, giới hạn dạng ring buffer (**cap ~200 dòng gần nhất**, dòng cũ nhất bị đẩy ra khi đầy) — tránh phình bộ nhớ khi dashboard mở lâu.
- **2 dropdown lọc** (`Lọc: Ý định`, `Lọc: Trạng thái`) lọc **client-side trên buffer đã có sẵn**, không gọi API lọc riêng.
- **Nút "Xuất nhật ký CSV"** export đúng phần buffer hiện có trong bộ nhớ, không phải toàn bộ lịch sử.
- **UI copy** phải tránh ngụ ý "xem lịch sử" — thêm dòng nhỏ kiểu "Nhật ký từ khi mở phiên làm việc" ở đầu bảng.
- **Giả định cần xác nhận với BE khi có dịp** (không chặn code): `/ws/engineer` phát sự kiện `trace` cho *mọi* turn của *mọi* tài xế trong hệ thống, không chỉ theo yêu cầu — nếu sai giả định này, buffer sẽ trống/thiếu.

### 6.2 KPI tiles — tách 2 khối, không có field "Intent Accuracy"/"Hallucination Rate" realtime

`GET /metrics/summary` (mục "Live") chỉ có `rag.grounded_rate` và `stage_latency_ms.end_to_end` — **không có** field tương đương Intent Accuracy/Hallucination Rate. Lý do: 2 số này là kết quả **eval offline** (tool exact match %, schema validity % — đo bằng bộ test cố định, xem `eval/results/report.md`), không phải thứ tính được realtime từ traffic sống (không có ground-truth cho từng câu người dùng nói thật). Quyết định: **tách UI thành 2 khối rõ ràng**, không giả vờ gộp chung:

| Khối | Nguồn dữ liệu | Cập nhật | Field |
|---|---|---|---|
| **Live** | `GET /metrics/summary` + sự kiện `metrics` trên `/ws/engineer` | Realtime | Grounded Rate (`rag.grounded_rate`, ngưỡng >90% — PRD N5), Latency trung bình (`stage_latency_ms.end_to_end.p50`, ngưỡng <3.000ms — PRD N1) |
| **Đánh giá offline** | Đọc snapshot từ `eval/results/report.md` (không qua API/WS) | Theo đợt chạy eval, không realtime | Intent/Tool Accuracy (ngưỡng >85% — PRD N4), Hallucination/trượt gate (ngưỡng <10% — PRD N6) |

Màu badge: đạt ngưỡng = `--green`, không đạt = `--accent`. Trạng thái log: Xong = `--ink` thường, Từ chối = `--accent`, Chưa hiểu/Đã hủy/Hết giờ = `--amber`, Đã đồng ý = `--cyan`.

### 6.3 Component đề xuất

`src/components/engineer/`: `EngineerHeader`, `AlertBanner`, `StatTileRow` (2 khối Live/Offline riêng biệt, xem 6.2), `LatencyChartPanel` (placeholder → `recharts` sau), `LogsTable` (ring buffer + filter client-side, xem 6.1), `LogsFilterBar`. Data qua `engineerService.getMetrics()` (`GET /metrics/summary`) + `engineerService.getHealth()` (`GET /healthz`) + subscribe `/ws/engineer`; số liệu offline-eval đọc riêng, không qua `engineerService`.

## 7. Nhúng API thật cho Map/YouTube/Spotify/TikTok

| App | Quyết định |
|---|---|
| YouTube | `<iframe>` YouTube Embed thật, 6 video ID cố định |
| Spotify | Spotify Embed widget `<iframe>` thật |
| Map | Leaflet + OpenStreetMap tiles thật, route/ETA vẫn mock |
| TikTok | Giữ mock tĩnh (không có embed feed phù hợp, rủi ro ToS) |

## 8. Next.js 16 — lưu ý khác biệt so với kiến thức cũ

Xem `AGENTS.md`/`node_modules/next/dist/docs/` trước khi dùng API. Điểm hay bị sai nhất: `params`/`searchParams` trong page/layout giờ là Promise (`await props.params`), Tailwind v4 cấu hình theme bằng `@theme` trong CSS (không có `tailwind.config.ts`), `next lint` đã bị gỡ (dùng `eslint` trực tiếp, đã có sẵn trong `package.json`).

**Lưu ý riêng về `PageProps<'/route'>`/`LayoutProps<'/route'>` (typegen helper):** CHỈ dùng khi route thật sự có dynamic params cần type-safe access. Với `layout.tsx` gốc (không có params) đã cố tình đổi từ `LayoutProps<"/">` sang `Readonly<{ children: ReactNode }>` chuẩn — vì `LayoutProps`/`PageProps` phụ thuộc file `.next/types/**/*.ts` sinh ra bởi `next build`/`next dev`/`next typegen`, thư mục này bị gitignore và CHƯA CHẮC tồn tại nếu CI chạy `tsc` độc lập trước khi build (đã bị code review bot phát hiện, xem lịch sử commit `fix(fe): sửa 2 lỗi review...`). Chỉ dùng các helper này cho route có params động (vd `/traces/[id]`) nơi không có cách nào tránh, và đảm bảo pipeline CI luôn chạy `next build`/`next typegen` trước bước type-check.

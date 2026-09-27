@AGENTS.md

# VIVI Cabin Copilot — Frontend (AI20K Build Phase, team P-192)

Next.js (App Router, TS, Tailwind v4) cho 2 màn hình người dùng — `/login`, `/driver` (IVI Screen tài xế, có mô phỏng xe 3D), `/engineer` (Dashboard kỹ sư) — của trợ lý giọng nói trong xe **VIVI Cabin Copilot**. Chưa có Backend thật kết nối — toàn bộ chạy qua mock service có thể swap sang API thật mà không sửa UI (xem `docs/ARCHITECTURE.md` mục 4).

## Đọc theo đúng thứ tự này trước khi sửa bất kỳ file nào

1. File này trước.
2. `docs/ARCHITECTURE.md` — routes, component tree, service layer pattern, endpoint/topic thật của Backend.
3. `docs/DESIGN_TOKENS.md` — bảng màu/font/spacing, nguồn sự thật duy nhất.
4. `docs/CODING_STANDARDS.md` — quy tắc code, naming, Next.js 16 conventions.
5. `PROGRESS.md` — nhật ký commit tự động, xem việc gần nhất đã làm gì trước khi nhận việc mới.
6. Chỉ đọc `../HANDOFF_prototype-to-fe.md` / `../vivi_ivi_vf8style (1).html` ở repo cha nếu cần đối chiếu chi tiết hành vi UI cụ thể — coi là behavior spec, không phải code cần giữ nguyên.

## Quy tắc bắt buộc (không tự suy diễn khác)

- **1 dark theme duy nhất** cho cả 3 route — không tạo toggle sáng/tối, không dùng `prefers-color-scheme` để đổi theme.
- **Không hard-code màu hex mới** — chỉ dùng token trong `docs/DESIGN_TOKENS.md` / `src/styles/tokens.css`.
- Component **không bao giờ import trực tiếp** `mock.ts` hay `real.ts` trong `lib/services/*` — chỉ qua `lib/services/*/index.ts` (chọn theo `NEXT_PUBLIC_USE_MOCK_*`).
- `Car3DViewer` là presentational component thuần — nhận `vehicleState` qua props, không tự gọi API.
- Repo dùng **Next.js 16** — API khác nhiều so với dữ liệu huấn luyện cũ (đã ghi ở khối `@AGENTS.md` phía trên) — đọc `node_modules/next/dist/docs/` khi cần API cụ thể (params/searchParams async, `PageProps`/`LayoutProps` helper, ESLint flat config, Tailwind v4 CSS-first `@theme`).

## Lệnh chạy

```bash
cd frontend
npm run dev        # http://localhost:3000, có Turbopack theo mặc định Next 16
npm run build
npm run lint
npm run test        # Vitest — bắt buộc chạy khi sửa logic trong lib/services/
npm run smoke:turn  # xem nhanh luồng sự kiện mockTurnService bằng mắt (tsx)
```

## Biến môi trường

Service layer (`src/lib/services/{session,turn,engineer}/`) đã dựng xong theo đúng 12 interface trong `docs/api_spec.md` (repo cha) — xem `docs/ARCHITECTURE.md` mục 4. Không có domain "voice"/"vehicle" riêng — gộp chung thành `turn` vì cả giọng nói lẫn thao tác UI đều đi qua `POST /turns/text`/`POST /turns/voice`.

**Mock-first mặc định** — không set `NEXT_PUBLIC_USE_MOCK_*` thì tự dùng mock, không cần tạo `.env` để chạy `npm run dev` (xem `docs/CODING_STANDARDS.md`). Chỉ set `=false` khi thật sự muốn nối API thật.

```bash
NEXT_PUBLIC_USE_MOCK_SESSION=false   # bỏ trống/không set = mock
NEXT_PUBLIC_USE_MOCK_TURN=false
NEXT_PUBLIC_USE_MOCK_ENGINEER=false
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_IVI_URL=ws://localhost:8000/ws/ivi
NEXT_PUBLIC_WS_ENGINEER_URL=ws://localhost:8000/ws/engineer

# Credential demo tài xế cho luồng auto-login 1-click ở /login (xem
# docs/ARCHITECTURE.md mục 3.1) — giá trị THẬT phải xin từ BE sau khi họ
# seed bảng `users`, chưa có sẵn, KHÔNG tự bịa giá trị.
# KHÔNG thêm prefix NEXT_PUBLIC_ (server-only — chỉ đọc trong Route Handler
# /api/auth/demo-driver, tránh bundle credential vào JS phía client).
DEMO_DRIVER_EMAIL=
DEMO_DRIVER_PASSWORD=
```

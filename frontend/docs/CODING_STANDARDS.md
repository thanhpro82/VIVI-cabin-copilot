# Coding Standards — Frontend

## Cấu trúc & naming

- Component: PascalCase, 1 component/file, đặt theo domain: `src/components/ivi/*` (Driver IVI), `src/components/engineer/*` (Dashboard).
- Service: `src/lib/services/<domain>/{types,mock,real,index}.ts` — xem `ARCHITECTURE.md` mục 4. Không tạo domain service mới ngoài `session`, `turn`, `engineer` mà không cập nhật `ARCHITECTURE.md`.
- Route: theo App Router chuẩn (`src/app/<route>/page.tsx`), 1 `layout.tsx` gốc duy nhất — không tạo layout con trừ khi có lý do rõ ràng (hiện chưa cần).

## TypeScript

- `strict` mode (mặc định của `create-next-app --typescript`, không tắt).
- Props của mọi component: khai báo `interface XxxProps` ngay trên component, không dùng `any`.
- Dùng type helper sinh tự động của Next 16 khi cần (`PageProps<'/route'>`, `LayoutProps<'/route'>` — chạy `npx next typegen` nếu type báo thiếu).

## Styling

- Chỉ Tailwind utility + token trong `DESIGN_TOKENS.md`. Không viết CSS module/styled-components mới trừ khi utility không đáp ứng được (hiệu ứng phức tạp như `car3d-glow`/`pulse` animation — khi đó thêm `@keyframes`/class riêng vào `globals.css`, có comment giải thích).
- Không hard-code màu hex/rgba ngoài `tokens.css`.

## Service layer (bắt buộc — xem ARCHITECTURE.md mục 4)

- Component **không** import `mock.ts`/`real.ts` trực tiếp, chỉ qua `index.ts` của domain đó.
- `mock.ts` và `real.ts` implement cùng 1 interface trong `types.ts` — khi sửa 1 bên, kiểm tra bên kia có còn khớp shape không.
- Mock phải mô phỏng độ trễ (`setTimeout`) và trạng thái lỗi giống thật, không chỉ trả data ngay lập tức.
- **Mock-first theo mặc định**: mỗi `index.ts` chọn mock khi biến `NEXT_PUBLIC_USE_MOCK_*` **chưa được set** (không phải khi set `=true`) — để `npm run dev` chạy được ngay không cần `.env`, tránh lỗi network vô nghĩa khi ai đó quên cấu hình. Muốn dùng API thật phải chủ động set `NEXT_PUBLIC_USE_MOCK_*=false`.

## Test (Vitest)

- Logic mock có rủi ro cao (an toàn S0-S3, luồng approval, invariant "chỉ 1 approval đang chờ") **bắt buộc có test** ở `<domain>/mock.test.ts` — `npm run build`/`npm run lint` chỉ bắt lỗi kiểu dữ liệu, không bắt được lỗi hành vi.
- Vì mock giữ state dạng module-singleton, mỗi test phải `vi.resetModules()` rồi `import()` lại để có instance sạch — xem ví dụ mẫu ở `turn/mock.test.ts`.
- Hàm debug-only chỉ tồn tại ở mock (không có ở `real.ts`, không thuộc interface `types.ts` chính thức) đặt tên tiền tố `__` (ví dụ `__setMockSpeedKph`) để rõ ràng không phải API thật.
- `npm run test` chạy toàn bộ test. Muốn xem luồng sự kiện bằng mắt nhanh (không phải test tự động) thì có script riêng, ví dụ `npm run smoke:turn` (`scripts/smoke-turn.ts`, chạy bằng `tsx`).

## Client vs Server Component

- Mặc định Server Component. Chỉ thêm `"use client"` khi cần `useState`/`useEffect`/event handler/`<model-viewer>`/Web API trình duyệt.
- `Car3DViewer`, `VoiceOverlay`, mọi thứ dùng service layer (fetch/WebSocket runtime, không phải server-side data fetch) đều là Client Component.

## Commit & PR

- Theo `docs/GIT_WORKFLOW.md` ở repo cha: `type(scope): mô tả`, scope gợi ý cho FE: `fe`, `ivi`, `car3d`, `engineer`, `voice`.
- 1 PR giải quyết 1 vấn đề — không gộp nhiều feature không liên quan vào 1 nhánh `feature/...`.

## Next.js 16 — điểm hay bị code sai vì kiến thức cũ

- `params`/`searchParams` trong `page.tsx`/`layout.tsx` là **Promise**, phải `await`.
- Tailwind v4: cấu hình theme bằng `@theme`/`@theme inline` trong CSS (`globals.css`), **không có** `tailwind.config.ts` mặc định — không tự tạo file đó trừ khi thật sự cần override sâu (content globs, plugin).
- `next lint` đã bị gỡ — dùng `npm run lint` (đã trỏ tới `eslint` CLI trực tiếp trong `package.json`).
- Không dùng `middleware.ts` cho logic mới — Next 16 đổi tên quy ước thành `proxy.ts` (edge runtime không còn hỗ trợ ở `proxy`).

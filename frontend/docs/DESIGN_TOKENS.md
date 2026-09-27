# Design Tokens — nguồn sự thật duy nhất

Định nghĩa thật ở `src/styles/tokens.css` (màu/radius) + `src/app/layout.tsx` (font, qua `next/font/google`). File này là bảng tra cứu — khi cần thêm/sửa token, sửa 2 file đó trước, rồi cập nhật bảng dưới theo.

## Màu

| Token CSS | Giá trị | Tailwind utility | Vai trò |
|---|---|---|---|
| `--bg` | `#07090D` | `bg-bg` | Nền tổng |
| `--panel-solid` | `#11151C` | `bg-panel-solid` | Nền card tương phản cao |
| `--panel` | `rgba(255,255,255,.045)` | (dùng `bg-[var(--panel)]`) | Nền "đảo nổi" glass card |
| `--line` | `rgba(255,255,255,.09)` | `border-line` | Viền mảnh |
| `--ink` | `#EDEFF3` | `text-ink` | Chữ chính |
| `--ink-soft` | `#8B94A3` | `text-ink-soft` | Chữ phụ |
| `--ink-dim` | `#545D6B` | `text-ink-dim` | Chữ mờ |
| `--accent` | `#FF4D5E` | `text-accent` / `bg-accent` | Nhấn chính, cảnh báo, "Từ chối" |
| `--cyan` | `#38BDF8` | `text-cyan` / `bg-cyan` | Bản đồ, xác nhận thành công |
| `--violet` | `#8B7CF6` | `text-violet` / `bg-violet` | Nhạc trên máy |
| `--green` | `#22C55E` | `text-green` / `bg-green` | Spotify, "đạt ngưỡng" |
| `--amber` | `#FBBF24` | `text-amber` / `bg-amber` | Điều khiển xe, cảnh báo nhẹ |
| `--pink` | `#FF3D9A` | `text-pink` / `bg-pink` | TikTok |
| `--indigo` | `#6366F1` | `text-indigo` / `bg-indigo` | Routines |

**Quy tắc:** không hard-code hex mới ở component. Nếu cần màu mới, thêm vào `tokens.css` + `globals.css` (`@theme inline`) trước, không viết trực tiếp trong JSX.

## Bo góc

`--r-lg: 28px` (khối lớn/card ngoài cùng) · `--r-md: 18px` (card con) · `--r-sm: 12px` (nút/badge nhỏ). Dùng qua `rounded-[var(--r-lg)]` (Tailwind v4 chưa map radius vào `@theme` ở bước scaffold — nếu cần utility riêng, thêm `--radius-*` vào `@theme inline`).

## Font

| Utility | Font thật | Vai trò |
|---|---|---|
| `font-display` | Space Grotesk (500/600/700) | Tiêu đề, số liệu lớn |
| `font-body` (mặc định trên `<body>`) | Inter (400–700) | Nội dung |
| `font-technical` | IBM Plex Mono (400/500/600) | Dữ liệu/số liệu kỹ thuật, bảng log, timestamp |

Nạp qua `next/font/google` trong `src/app/layout.tsx` — không thêm `<link>` Google Fonts thủ công (next/font tự tối ưu, self-host).

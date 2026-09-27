/**
 * Kênh một chiều "token không còn dùng được" từ tầng service lên tầng page.
 *
 * Vì sao cần: tầng `lib/services/*` không có `router` và không được phép có —
 * nó là lớp swap mock/real thuần. Nhưng chỗ *phát hiện* token chết lại nằm đúng
 * ở đó (401 của mọi REST call, close code 4401 của cả hai WebSocket).
 * Trước đây phát hiện xong không làm gì cả: `DriverShellProvider` hiện một toast
 * 3,2 giây rồi tắt, các nút vẫn bấm được, `/ws/ivi` reconnect vô hạn 8 giây/lần
 * với đúng cái token đã chết — người dùng kẹt cho tới khi tự F5. Đó chính là bug
 * `W-5` trong `docs/release/mvp-demo-checklist.md`.
 *
 * Lý do dùng `sessionStorage` chứ không phải `?reason=` trên URL: `useSearchParams`
 * của Next 16 bắt buộc bọc `<Suspense>` khi prerender, đắt hơn hẳn giá trị nó
 * mang lại cho một dòng thông báo. Ghi trước khi điều hướng, `/login` đọc rồi xoá.
 *
 * KHÔNG dùng cho lỗi đăng nhập sai mật khẩu — người dùng đang đứng ở `/login`
 * rồi, đá họ về `/login` lần nữa chỉ xoá mất thông báo của chính màn hình đó.
 */

const NOTICE_KEY = "vivi.auth_notice";

/**
 * Mã lỗi đồng nghĩa "phiên đăng nhập không còn dùng được" — **chỉ** `AUTH_REQUIRED`.
 *
 * `FORBIDDEN` từng nằm trong danh sách này và đó là lỗi. Mọi chỗ trả 403 của backend
 * đều mang đúng mã ấy — `auth_deps.py:58` và `:82` (sai role), `ws.py` 4403 (sai role
 * hoặc Origin), `turns.py:146` và `:354` (session không thuộc về mình),
 * `approvals.py:104`, `citation_routes.py:85`, `vehicle_profile_routes.py:85` — nhưng
 * **không ca nào trong số đó nghĩa là token chết**. Xoá cả phiên đăng nhập vì bị từ
 * chối một tài nguyên là fail-closed quá tay (PM/PO review PR #157).
 *
 * Thu hẹp một mình hàm này KHÔNG đủ: nhánh REST ở `turn/real.ts`, `engineer/real.ts`
 * và `session/real.ts` gate theo HTTP status chứ không gọi hàm này, và mọi 403 đều
 * mang `FORBIDDEN` nên hai đường vốn cho kết quả giống hệt nhau. Cả hai phải hẹp lại
 * cùng lúc, nếu không hành vi không đổi.
 */
export function isAuthFailureCode(code: string | undefined): boolean {
  return code === "AUTH_REQUIRED";
}

type Listener = (message: string) => void;

const listeners = new Set<Listener>();

/**
 * Gọi khi backend đã nói rõ token không dùng được nữa. An toàn khi gọi nhiều lần
 * trong cùng một nhịp (poll 2 giây có thể trượt vài lần trước khi trang kịp
 * chuyển) — listener chỉ điều hướng, và điều hướng lần hai là no-op.
 */
export function reportAuthFailure(message: string): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(NOTICE_KEY, message);
  }
  for (const listener of listeners) listener(message);
}

export function subscribeAuthFailure(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Đọc mà KHÔNG xoá. Phải thuần và ổn định giữa hai lần gọi liên tiếp vì đây là
 * `getSnapshot` của `useSyncExternalStore` ở `/login` — một hàm đọc-rồi-xoá đặt
 * vào đó sẽ trả giá trị khác nhau mỗi lần React kiểm tra và gây vòng render vô hạn.
 */
export function peekAuthNotice(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(NOTICE_KEY);
}

/** Đọc **một lần** rồi xoá — gọi khi thông báo đã hết tác dụng (rời `/login`). */
export function consumeAuthNotice(): string | null {
  const message = peekAuthNotice();
  if (message !== null) window.sessionStorage.removeItem(NOTICE_KEY);
  return message;
}

/** Chỉ dùng trong test — dọn listener giữa các case. */
export function resetAuthFailureListeners(): void {
  listeners.clear();
}

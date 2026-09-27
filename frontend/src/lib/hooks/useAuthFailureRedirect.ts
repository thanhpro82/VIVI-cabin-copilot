"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { sessionService } from "@/lib/services/session";
import { subscribeAuthFailure } from "@/lib/services/shared/authFailure";

/**
 * Đăng xuất sạch và quay về `/login` ngay khi tầng service phát hiện token không
 * còn dùng được (401/403 ở REST, close code 4401/4403 ở WebSocket).
 *
 * Vì sao cần một hook riêng thay vì để guard lúc mount tự lo: guard ở
 * `driver/page.tsx`/`engineer/page.tsx` chỉ chạy **một lần**, và nó chỉ hỏi
 * `getStoredSession()` — thứ chỉ biết `expiresAt` do chính client giữ. Token bị
 * backend vô hiệu giữa chừng (restart backend là ca thường gặp nhất, vì store
 * token nằm trong RAM) không đổi `expiresAt`, nên guard đó vĩnh viễn nói "vẫn
 * đăng nhập" trong khi mọi request đều 401.
 *
 * `logout()` xoá cả `vivi.session` lẫn `vivi.driver_session`, nên lần đăng nhập
 * lại tạo phiên mới sạch thay vì bám vào `session_id` mà server đã quên.
 */
export function useAuthFailureRedirect(): void {
  const router = useRouter();

  useEffect(
    () =>
      subscribeAuthFailure(() => {
        sessionService.logout();
        router.replace("/login");
      }),
    [router],
  );
}

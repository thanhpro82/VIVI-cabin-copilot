"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { sessionService, type AuthUser } from "@/lib/services/session";
import { consumeAuthNotice, peekAuthNotice, subscribeAuthFailure } from "@/lib/services/shared/authFailure";
import { DriverLoginCard } from "@/components/auth/DriverLoginCard";
import { EngineerLoginCard } from "@/components/auth/EngineerLoginCard";

const ROUTE_BY_ROLE: Record<AuthUser["role"], string> = {
  driver: "/driver",
  engineer: "/engineer",
};

export default function LoginPage() {
  const router = useRouter();

  // Lý do bị đá về đây, do tầng service ghi lại trước khi điều hướng. Đọc qua
  // `useSyncExternalStore` chứ không phải `useEffect` + `setState`: server
  // snapshot là `null` nên không có hydration mismatch, và không có cascading
  // render (quy tắc react-hooks/set-state-in-effect của repo).
  //
  // Không có dòng thông báo này thì người dùng chỉ thấy mình bỗng dưng bị đăng
  // xuất — đúng cái trải nghiệm bản trước để lại, chỉ khác là trước đây họ còn
  // chẳng bị đá về mà kẹt luôn tại chỗ với các nút vẫn bấm được.
  const notice = useSyncExternalStore(
    subscribeAuthFailure,
    peekAuthNotice,
    () => null,
  );

  // Vào lại app trong thời hạn token thì bỏ qua /login (ARCHITECTURE.md mục
  // 3.1) — chỉ đọc localStorage sau khi mount (client-only), không setState
  // ở đây để tránh cascading render, router.replace tự thay UI gần như ngay.
  useEffect(() => {
    const stored = sessionService.getStoredSession();
    if (stored) {
      router.replace(ROUTE_BY_ROLE[stored.user.role]);
    }
  }, [router]);

  function handleSuccess(user: AuthUser) {
    // Xoá thông báo ở ĐÂY, không phải ở cleanup của effect: React StrictMode
    // (bật mặc định ở `next dev`) mount → unmount → mount lại, nên một cleanup
    // dọn dẹp sẽ chạy ngay lần unmount giả và xoá mất thông báo trước khi người
    // dùng kịp đọc — đúng lỗi đã quan sát được khi chạy thử tay. Đăng nhập lại
    // thành công là thời điểm duy nhất thông báo chắc chắn hết tác dụng.
    consumeAuthNotice();
    router.replace(ROUTE_BY_ROLE[user.role]);
  }

  return (
    <main className="flex flex-1 items-center justify-center px-6 py-16">
      <div className="w-full max-w-3xl">
        <div className="relative flex flex-col items-center text-center">
          <div
            aria-hidden
            className="ignition-ring pointer-events-none absolute -top-16 h-72 w-72 sm:h-80 sm:w-80"
          />
          <p className="font-technical text-xs tracking-[0.3em] text-ink-dim uppercase">
            Hệ thống sẵn sàng
          </p>
          <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-ink sm:text-5xl">
            VIVI Cabin Copilot
          </h1>
          <p className="mt-4 max-w-md text-sm text-ink-soft">
            Chọn vai trò để tiếp tục — mỗi vai trò có một luồng đăng nhập riêng.
          </p>
        </div>

        {notice ? (
          <p
            role="status"
            className="mt-8 rounded-[var(--r-sm)] border border-amber/40 bg-amber/10 px-4 py-3 text-center text-sm text-amber"
          >
            {/* Không thêm "vui lòng đăng nhập lại" ở đây: thông điệp của backend
                đã kết bằng đúng câu đó, ghép vào thành lặp hai lần. */}
            Phiên đăng nhập đã kết thúc — {notice}
          </p>
        ) : null}

        <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
          <DriverLoginCard onSuccess={handleSuccess} />
          <EngineerLoginCard onSuccess={handleSuccess} />
        </div>

        <p className="mt-10 text-center font-technical text-xs text-ink-dim">
          VIVI Cabin Copilot · AI20K Build Phase · P-192
        </p>
      </div>
    </main>
  );
}

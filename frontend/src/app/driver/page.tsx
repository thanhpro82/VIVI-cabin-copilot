"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { sessionService } from "@/lib/services/session";
import { useAuthFailureRedirect } from "@/lib/hooks/useAuthFailureRedirect";
import { DriverShell } from "@/components/ivi/DriverShell";

/** /driver — chỉ vào được khi đã đăng nhập vai trò Tài xế (xem docs/ARCHITECTURE.md mục 3.1); RBAC thật do server enforce, đây chỉ là UX guard. */
export default function DriverPage() {
  const router = useRouter();

  // Guard dưới chỉ chạy lúc mount; hook này lo ca token chết GIỮA CHỪNG.
  useAuthFailureRedirect();

  // Không setState ở đây để tránh cascading render (giống login/page.tsx) —
  // router.replace tự thay UI gần như ngay nếu chưa đăng nhập đúng vai trò.
  useEffect(() => {
    const session = sessionService.getStoredSession();
    if (!session || session.user.role !== "driver") {
      router.replace("/login");
    }
  }, [router]);

  return <DriverShell />;
}

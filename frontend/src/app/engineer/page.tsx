"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { sessionService } from "@/lib/services/session";
import { useAuthFailureRedirect } from "@/lib/hooks/useAuthFailureRedirect";
import { EngineerDashboard } from "@/components/engineer/EngineerDashboard";

/** /engineer — chỉ vào được khi đã đăng nhập vai trò Kỹ sư (xem docs/ARCHITECTURE.md mục 3.1); RBAC thật do server enforce, đây chỉ là UX guard. */
export default function EngineerPage() {
  const router = useRouter();

  // Guard dưới chỉ chạy lúc mount; hook này lo ca token chết GIỮA CHỪNG.
  useAuthFailureRedirect();

  useEffect(() => {
    const session = sessionService.getStoredSession();
    if (!session || session.user.role !== "engineer") {
      router.replace("/login");
    }
  }, [router]);

  return <EngineerDashboard />;
}

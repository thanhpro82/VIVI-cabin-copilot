"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { sessionService } from "@/lib/services/session";
import { useEngineerShell } from "./EngineerShellProvider";
import { VehicleProfileChip } from "./VehicleProfileChip";

/** displayName phụ thuộc localStorage — chỉ đọc sau mount để tránh hydration mismatch. */
function useDisplayName(): string | null {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    const kickoff = setTimeout(() => {
      setName(sessionService.getStoredSession()?.user.displayName ?? "bạn");
    }, 0);
    return () => clearTimeout(kickoff);
  }, []);
  return name;
}

export function EngineerHeader() {
  const { logs, health } = useEngineerShell();
  const displayName = useDisplayName();
  const router = useRouter();

  const degradedCount = health
    ? Object.values(health.components).filter((c) => c.status !== "ready").length
    : 0;

  function handleLogout() {
    sessionService.logout();
    router.push("/login");
  }

  return (
    <header className="flex h-15 shrink-0 items-center gap-3.5 px-5.5">
      <div>
        <p className="font-display text-lg font-semibold text-ink">Dashboard kỹ sư</p>
      </div>
      {/* Danh tính xe đứng ngay cạnh tên trang, không dồn về cụm badge bên phải:
          nó là ngữ cảnh của cả màn hình, không phải một chỉ số trạng thái. */}
      <VehicleProfileChip />
      <span className="flex-1" />
      <span className="font-display text-sm font-medium text-ink">
        {displayName ? `Xin chào, ${displayName}` : ""}
      </span>
      <span className="flex items-center gap-1.5 rounded-full border border-line bg-(--panel) px-2.5 py-1 font-technical text-[10px] text-ink-soft">
        <span className="h-1.5 w-1.5 rounded-full bg-cyan" />
        {logs.length} lượt · phiên hiện tại
      </span>
      <span
        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-technical text-[10px] tracking-wide ${
          degradedCount > 0 ? "border-amber/40 text-amber" : "border-green/40 text-green"
        }`}
        title={health ? Object.entries(health.components).map(([k, v]) => `${k}: ${v.status}`).join(", ") : ""}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
        {health ? (degradedCount > 0 ? `${degradedCount} thành phần lỗi` : "Hệ thống ổn định") : "Đang kiểm tra…"}
      </span>
      <button
        type="button"
        onClick={handleLogout}
        title="Đăng xuất"
        className="flex h-9.5 w-9.5 items-center justify-center rounded-xl border border-line bg-(--panel) text-ink-soft transition-colors hover:border-accent hover:text-accent"
      >
        ⎋
      </button>
    </header>
  );
}

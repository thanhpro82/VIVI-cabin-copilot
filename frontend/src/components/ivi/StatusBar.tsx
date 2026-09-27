"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { sessionService } from "@/lib/services/session";
import { useDriverShell } from "./DriverShellProvider";
import type { ViewName } from "./DriverShellProvider";
import { HomeIcon } from "./AppIcons";

function useClock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    // setTimeout(0) thay vì gọi setState trực tiếp trong effect — tick đầu
    // tiên chạy trong callback (giống pattern subscribe), tránh cascading render.
    const kickoff = setTimeout(tick, 0);
    const timer = setInterval(tick, 1000 * 30);
    return () => {
      clearTimeout(kickoff);
      clearInterval(timer);
    };
  }, []);
  return now;
}

/** displayName phụ thuộc localStorage — chỉ đọc sau mount để tránh hydration mismatch (SSR không có localStorage). */
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

const HOME: ViewName = "home";

export function StatusBar() {
  const { vehicleState, setActiveView, pending, connectionState, canDrive } = useDriverShell();
  const router = useRouter();
  const now = useClock();
  const displayName = useDisplayName();

  const speed = vehicleState?.motion.speedKph ?? 0;
  const driving = speed > 5;

  function handleLogout() {
    sessionService.logout();
    router.push("/login");
  }

  return (
    <header className="flex h-15 shrink-0 items-center gap-3.5 px-5.5">
      <button
        type="button"
        onClick={() => setActiveView(HOME)}
        title="Về màn hình chính"
        className="flex h-9.5 w-9.5 items-center justify-center rounded-xl border border-line bg-(--panel) text-ink-soft transition-colors hover:border-accent/40 hover:text-ink"
      >
        <HomeIcon size={17} />
      </button>
      <span className="font-display text-lg font-semibold text-ink">
        {now ? now.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }) : "--:--"}
      </span>
      <span className="font-technical text-xs text-ink-soft">{speed} km/h</span>
      {pending && (
        <span className="flex items-center gap-1.5 font-technical text-[10px] text-cyan">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
          Đang xử lý…
        </span>
      )}
      {/* Trạng thái kênh sự kiện (issue #241) — đặt ở StatusBar vì nó đúng trên
          MỌI màn, không riêng "Điều khiển xe": lệnh gửi từ Nhạc/Bản đồ cũng bị
          chặn y hệt, nên tài xế phải thấy lý do ở chỗ luôn nhìn thấy. */}
      {connectionState !== "online" && (
        <span
          role="status"
          className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-technical text-[10px] tracking-wide ${
            connectionState === "connecting" ? "border-amber/40 text-amber" : "border-accent/50 text-accent"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full bg-current ${connectionState === "connecting" ? "animate-pulse" : ""}`}
          />
          {connectionState === "connecting" ? "Đang kết nối…" : "Mất kết nối"}
        </span>
      )}
      {/* Chế độ chỉ xem (pool xe ảo hết, issue #261). Cùng chỗ và cùng lý do
          với huy hiệu kết nối ở trên — nút điều khiển bị khoá trên MỌI màn
          (kể cả ba nút của RightPanel ở Trang chính), nên lý do phải nằm ở chỗ
          luôn nhìn thấy, không chỉ trong panel "An toàn" của màn Điều khiển xe.
          Nếu không, tài xế ở màn Nhạc/Bản đồ chỉ thấy nút xám mà không biết vì sao.

          LÝ DO KHÁC mất kết nối, nên là huy hiệu RIÊNG chứ không gộp câu chữ:
          kênh sự kiện vẫn sống, sổ tay vẫn tra được, chỉ là không còn xe. */}
      {connectionState === "online" && !canDrive && (
        <span
          role="status"
          className="flex items-center gap-1.5 rounded-full border border-amber/40 px-2.5 py-1 font-technical text-[10px] tracking-wide text-amber"
        >
          <span aria-hidden>👁</span>
          Chế độ chỉ xem — hết xe
        </span>
      )}
      <span className="flex-1" />
      <span className="font-display text-sm font-medium text-ink">
        {displayName ? `Xin chào, ${displayName}` : ""}
      </span>
      <span
        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-technical text-[10px] tracking-wide ${
          driving ? "border-amber/40 text-amber" : "border-green/40 text-green"
        }`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
        {driving ? "Đang lái · hạn chế thao tác" : "Đã dừng xe"}
      </span>
      <button
        type="button"
        onClick={handleLogout}
        title="Đăng xuất"
        className="flex h-9.5 w-9.5 items-center justify-center rounded-xl border border-line bg-(--panel) text-ink-soft transition-colors hover:border-accent/40 hover:text-accent"
      >
        ⎋
      </button>
    </header>
  );
}

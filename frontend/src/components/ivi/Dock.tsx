"use client";

import type { ReactNode } from "react";
import { useDriverShell } from "./DriverShellProvider";
import type { ViewName } from "./DriverShellProvider";
import { HomeIcon, MapPinIcon, MicIcon, MusicNoteIcon, SteeringWheelIcon } from "./AppIcons";

/** Theo docs/ARCHITECTURE.md mục 3: "Dock — Home / Bản đồ / Nhạc / Điều khiển xe" (không có YouTube/Spotify/TikTok — vào từ app grid ở Home). */
const DOCK_ITEMS: { view: ViewName; label: string; icon: ReactNode }[] = [
  { view: "home", label: "Trang chính", icon: <HomeIcon size={19} /> },
  { view: "map", label: "Bản đồ", icon: <MapPinIcon size={19} /> },
  { view: "music", label: "Nhạc", icon: <MusicNoteIcon size={19} /> },
  { view: "vehicle", label: "Điều khiển xe", icon: <SteeringWheelIcon size={19} /> },
];

export function Dock() {
  const { activeView, setActiveView, openVoice, voiceOpen, connectionState } = useDriverShell();
  // Khoá mic khi kênh sự kiện chưa/không còn tin được (issue #241, UAT-008).
  // `batDauNghe` đã tự chặn và hiện toast, nhưng nút vẫn phải TRÔNG như đang
  // khoá: mời người ta nói cả câu rồi mới báo không gửi được là kiểu hỏng tệ
  // nhất. Bao gồm cả `connecting` — xem docstring ConnectionState.
  const micLocked = connectionState !== "online";

  return (
    <footer className="flex h-16 shrink-0 items-center gap-2 border-t border-line px-5">
      {DOCK_ITEMS.map((item) => {
        const active = activeView === item.view;
        return (
          <button
            key={item.view}
            type="button"
            onClick={() => setActiveView(item.view)}
            className={`flex flex-col items-center gap-1 rounded-[var(--r-sm)] border px-4 py-2 font-display text-[11px] ${
              active
                ? "border-line bg-panel-solid text-ink"
                : "border-transparent text-ink-soft hover:text-ink"
            }`}
          >
            <span className="leading-none">{item.icon}</span>
            {item.label}
          </button>
        );
      })}
      <span className="flex-1" />
      <button
        type="button"
        onClick={openVoice}
        disabled={voiceOpen || micLocked}
        title={
          connectionState === "connecting"
            ? "Đang kết nối với hệ thống…"
            : connectionState === "offline"
              ? "Mất kết nối với hệ thống — không ra lệnh được lúc này"
              : "Ra lệnh bằng giọng nói"
        }
        className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-cyan/60 bg-panel-solid text-cyan transition-shadow hover:shadow-[0_0_0_8px_rgba(56,189,248,0.12)] disabled:opacity-50"
      >
        <MicIcon size={24} />
      </button>
      <span className="flex-1" />
      <span className="w-[120px] truncate text-right font-technical text-[10px] text-ink-dim">
        Qwen2.5-3B · offline
      </span>
    </footer>
  );
}
